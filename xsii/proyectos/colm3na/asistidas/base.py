"""Lo común de las tareas asistidas (docs/xsii/API.md, «Bloque 3»)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter

import listas


class ErrorAsistida(Exception):
    """Un rechazo de una tarea asistida: `estado` es el código HTTP (400 el
    archivo no sirve, 409 conflicto) y `mensaje` la frase para la persona."""

    def __init__(self, estado: int, mensaje: str):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje
        self.detalle = None       # lista de {indice, campo, mensaje} cuando el rechazo es por ítem


def huella(contenido: bytes, opciones: dict) -> str:
    """SHA-256 del contenido más las opciones ya normalizadas: lo que el
    ensayo vio es EXACTAMENTE lo que la carga recibe."""
    h = hashlib.sha256()
    h.update(contenido or b"")
    h.update(b"\x00")
    h.update(json.dumps(opciones, sort_keys=True, ensure_ascii=True).encode("ascii"))
    return h.hexdigest()


def plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def miles(n: int) -> str:
    """Un tope para leer: 500 -> «500», 20000 -> «20.000»."""
    return f"{n:,}".replace(",", ".")


_INVISIBLES_RAROS = "\u2800\u115f\u1160\u3164\uffa0"      # espacios que no se ven


def limpiar(valor) -> str:
    """El texto de una celda sin caracteres de control ni invisibles; los
    espacios raros pasan a espacio común y se recortan los bordes. Lo que
    empieza con = + - @ se deja tal cual (no es una planilla de salida)."""
    salida = []
    for c in str(valor or ""):
        cat = unicodedata.category(c)
        if cat == "Zs":
            salida.append(" ")
        elif cat in ("Cc", "Cf", "Cs", "Zl", "Zp") or c in _INVISIBLES_RAROS:
            continue
        else:
            salida.append(c)
    return re.sub(r" {2,}", " ", "".join(salida)).strip()


def leer_csv(contenido: bytes, tope_filas: int, tope_bytes: int):
    """`(cabecera, [(linea, celdas)])`. Rechaza (400) lo que no sirve para nada.
    Cada módulo dice sus topes: Seccionales 500 filas y 1 MB, el Padrón 20.000
    y 5 MB."""
    if not contenido or not contenido.strip():
        raise ErrorAsistida(400, "El archivo está vacío.")
    if len(contenido) > tope_bytes:
        raise ErrorAsistida(400, f"El archivo pesa más de {tope_bytes // (1024 * 1024)} MB: partilo en dos.")
    if b"\x00" in contenido or contenido[:2] == b"PK":
        raise ErrorAsistida(400, "No pude leer el archivo: tiene que ser un CSV (si es de Excel, guardalo como "
                                 "«CSV» o bajá el modelo).")
    texto = listas._decodificar(contenido)
    lector = csv.reader(io.StringIO(texto), delimiter=listas._dialecto(texto))
    cabecera, filas = None, []
    try:
        for celdas in lector:
            if not any(str(x).strip() for x in celdas):
                continue
            if cabecera is None:
                cabecera = celdas
                continue
            if len(filas) >= tope_filas:
                raise ErrorAsistida(400, f"La planilla tiene más de {miles(tope_filas)} filas: partila en varias.")
            filas.append((lector.line_num, celdas))
    except csv.Error:
        raise ErrorAsistida(400, "No pude leer el archivo: el CSV está mal formado.")
    if cabecera is None:
        raise ErrorAsistida(400, "El archivo está vacío.")
    return cabecera, filas


# ------------------------------------------------------------------ mapeo de columnas
# Lo comparten todas las tareas asistidas con planilla (Seccionales, Padrón): la
# planilla del sindicato trae las cabeceras que quiso, y acá se detecta qué campo
# es cada columna por sinónimos y se aplica lo que corrigió la persona.

def detectar(cabecera, claves, sinonimos: dict, especiales: dict | None = None, omitir=None) -> dict:
    """`{indice de columna: clave de campo}` por sinónimos de la cabecera (sin
    mirar mayúsculas, acentos ni signos). Cada columna va a un solo campo y cada
    campo toma una sola columna: la primera que lo nombra. `claves` es el orden de
    detección; `sinonimos[clave]` el conjunto de cabeceras planas; `especiales[clave]`
    una función `plano -> bool` que reemplaza al conjunto; `omitir(clave, asignado,
    planas)` saltea un campo según lo ya detectado."""
    especiales = especiales or {}
    planas = [listas._plano(h) for h in cabecera]
    asignado, usadas = {}, set()
    for clave in claves:
        if omitir and omitir(clave, asignado, planas):
            continue
        for i, p in enumerate(planas):
            if i in usadas or not p:
                continue
            if (especiales[clave](p) if clave in especiales
                    else (p == clave or p in sinonimos.get(clave, ()))):
                asignado[i] = clave
                usadas.add(i)
                break
    return asignado


def normalizar_mapeo(mapeo, claves) -> dict:
    """El `opciones.mapeo` que manda la persona: `{"<indice>": "<campo>" | ""}`."""
    if mapeo is None:
        return {}
    if not isinstance(mapeo, dict):
        raise ErrorAsistida(400, "El mapeo de columnas tiene que ser un objeto.")
    salida = {}
    for k, v in mapeo.items():
        try:
            idx = int(str(k).strip())
        except ValueError:
            raise ErrorAsistida(400, "El mapeo de columnas no es válido: la columna no es un número.")
        if idx < 0 or idx > 999 or isinstance(k, bool):
            raise ErrorAsistida(400, "El mapeo de columnas no es válido: la columna no existe.")
        if v is None:
            v = ""
        if not isinstance(v, str) or (v and v not in claves):
            raise ErrorAsistida(400, "El mapeo de columnas no es válido: ese campo no existe.")
        salida[str(idx)] = v
    return dict(sorted(salida.items(), key=lambda kv: int(kv[0])))


def aplicar_mapeo(detectado: dict, mapeo: dict, ancho: int, rotulos: dict) -> dict:
    """La detección con lo que corrigió la persona. Lo que ella nombra manda: se
    le quita a cualquier columna detectada para ese mismo campo. Dos columnas
    que ELLA asigna al mismo campo son un error (400)."""
    asignado = dict(detectado)
    explicitas = {}
    for k, campo in mapeo.items():
        idx = int(k)
        if idx >= ancho:
            raise ErrorAsistida(400, f"La columna {idx + 1} no existe en la planilla (tiene {ancho}).")
        if campo:
            explicitas[idx] = campo
            asignado[idx] = campo
        else:
            asignado.pop(idx, None)
    for idx, campo in explicitas.items():
        for j in [j for j, c in asignado.items() if c == campo and j != idx and j not in explicitas]:
            del asignado[j]
    repetidos = [c for c, n in Counter(asignado.values()).items() if n > 1]
    if repetidos:
        raise ErrorAsistida(400, f"Dos columnas están asignadas a «{rotulos[repetidos[0]]}»: dejá una sola.")
    return asignado


def muestras(crudas, indice: int, cantidad: int = 3) -> list:
    salida = []
    for _linea, celdas in crudas:
        if indice < len(celdas):
            v = limpiar(celdas[indice])
            if v:
                salida.append(v[:40])
                if len(salida) >= cantidad:
                    break
    return salida


def mapeo_json(cabecera, crudas, asignado: dict, obligatorios) -> dict:
    """La forma del contrato: `{columnas, sin_usar, faltan}`."""
    columnas = [{"indice": i, "cabecera": limpiar(h)[:60], "campo": asignado.get(i, ""),
                 "muestra": muestras(crudas, i)} for i, h in enumerate(cabecera)]
    return {"columnas": columnas,
            "sin_usar": [c["cabecera"] for c in columnas if not c["campo"] and c["cabecera"]],
            "faltan": [c for c in obligatorios if c not in asignado.values()]}
