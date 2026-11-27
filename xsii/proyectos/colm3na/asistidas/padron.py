"""Tarea asistida PAD-02: cargar el padrón (los afiliados) desde una planilla CSV.
Contrato: docs/xsii/API.md, «Bloque 4a: Padrón desde planilla».

Mismo protocolo que Seccionales (describir, ensayar, cargar) más el MAPEO DE
COLUMNAS: la planilla del sindicato trae las cabeceras que quiso («Apellido y
Nombre», «Nro CUIL», «Delegación», «F. Ingreso»…); `leer` detecta qué campo es
cada columna por sinónimos y la persona puede corregirlo (`opciones.mapeo`).

`leer` es PURA (sin base, sin red). La clasificación fila por fila y la escritura
NO están acá: son las de la alta masiva de Trabajadores, extraídas a
`padron_carga.procesar` (una sola implementación, X25). Este módulo arma las filas
de esa función, la llama y traduce su detalle a los estados del protocolo
(`valida` | `dudosa` | `rechazada` | `ya_existe`). No se geocodifica nada y la
asistida corre SIN alcance de seccional (la usa el equipo).

Lo que la planilla trae (identificaciones, nombres) vuelve en el resultado del
ensayo para quien la tiene en la mano; NADA de eso entra en el movimiento, en
`UsoIA` ni en lo que leen las herramientas de «Preguntame».
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter

from sqlmodel import select

import cuit
import listas
import padron_carga

from . import base
from .base import ErrorAsistida, huella

NOMBRE_ARCHIVO = "modelo-padron.csv"
TOPE_FILAS = 20000           # X27
TOPE_BYTES = 5 * 1024 * 1024
TOPE_FILAS_DEVUELTAS = 300   # filas no válidas que viajan en el ensayo
LINEAS_POR_MOTIVO = 10
TOTAL_DECLARADO_MAX = 10_000_000

# (clave, rótulo, obligatorio, ejemplo, ayuda). El orden es el de la detección:
# lo que se reconoce primero no se le quita a lo que sigue.
CAMPOS = (
    ("cuil", "Identificación (CUIL)", True, "20-30123456-7",
     "El número de 11 dígitos de la persona, con o sin guiones. Un DNI de 7 u 8 dígitos no sirve."),
    ("nombre", "Nombre", True, "Pérez, Juan",
     "Apellido y nombre en una sola columna, o solo el nombre si el apellido viene aparte."),
    ("apellido", "Apellido", False, "Pérez",
     "Si el apellido viene en otra columna, se une al nombre como «Apellido, Nombre»."),
    ("calle", "Calle (o domicilio)", False, "Córdoba",
     "La calle; una columna «Domicilio» con calle y número juntos también va acá."),
    ("numero", "Altura", False, "1234", "Número de la calle."),
    ("piso_depto", "Piso o depto", False, "3° B", "Piso o departamento, si tiene."),
    ("localidad", "Localidad", False, "Rosario", "Obligatoria para que la persona entre al padrón."),
    ("provincia", "Provincia", False, "Santa Fe", "Obligatoria para que la persona entre al padrón."),
    ("codigo_postal", "Código postal", False, "2000", "Código postal, si lo tienen."),
    ("telefono", "Teléfono", False, "341 555-0100", "Teléfono de contacto."),
    ("mail", "Mail", False, "juan@ejemplo.org",
     "Mail de la persona: queda como el mail del padrón, el que se usa para confirmar el registro."),
    ("seccional", "Seccional", False, "Seccional Rosario",
     "Por nombre, sin importar mayúsculas ni tildes. Una que no existe deja a la persona sin seccional."),
    ("fecha_afiliacion", "Fecha de afiliación", False, "2018-03-01", "AAAA-MM-DD o DD/MM/AAAA."),
    ("fecha_nacimiento", "Fecha de nacimiento", False, "1985-07-12", "AAAA-MM-DD o DD/MM/AAAA."),
)
CLAVES = tuple(c[0] for c in CAMPOS)
ROTULO = {c[0]: c[1] for c in CAMPOS}
OBLIGATORIOS = tuple(c[0] for c in CAMPOS if c[2])

_NOMBRE_COMPLETO = {
    "apellido_y_nombre", "apellido_y_nombres", "apellidos_y_nombres", "apellidos_y_nombre",
    "nombre_y_apellido", "nombres_y_apellidos", "nombre_y_apellidos", "nombre_completo",
    "apellido_nombre", "apellido_nombres", "apellidos_nombres", "nombre_apellido",
    "afiliado", "afiliada", "nombre_afiliado", "nombre_del_afiliado", "apellido_y_nombre_del_afiliado",
}
_SINONIMOS = {
    "nombre": {"nombre", "nombres"} | _NOMBRE_COMPLETO,
    "apellido": {"apellido", "apellidos"},
    "calle": {"calle", "domicilio", "direccion", "dir", "domicilio_calle", "direccion_calle",
              "domicilio_real"},
    "numero": {"numero", "altura", "nro", "num", "n", "nro_calle", "numero_calle", "altura_calle"},
    "piso_depto": {"piso_depto", "piso_dpto", "piso", "depto", "dpto", "departamento", "piso_y_depto",
                   "piso_y_dpto"},
    "localidad": {"localidad", "ciudad", "municipio", "partido"},
    "provincia": {"provincia", "prov", "pcia"},
    "codigo_postal": {"codigo_postal", "cod_postal", "cp", "c_p", "cpa", "codigo_postal_argentino"},
    "telefono": {"telefono", "tel", "celular", "cel", "tel_celular", "telefono_celular", "movil",
                 "telefono_movil", "tel_movil"},
    "mail": {"mail", "email", "e_mail", "correo", "correo_electronico", "mail_personal"},
    "seccional": {"seccional", "delegacion", "filial", "regional", "delegacion_seccional"},
    "fecha_afiliacion": {"fecha_afiliacion", "fecha_de_afiliacion", "f_afiliacion", "afiliacion",
                         "f_ingreso", "fecha_ingreso", "fecha_de_ingreso", "ingreso", "fecha_alta",
                         "fecha_de_alta", "f_alta", "alta"},
    "fecha_nacimiento": {"fecha_nacimiento", "fecha_de_nacimiento", "f_nacimiento", "f_nac",
                         "fecha_nac", "fecha_de_nac", "nacimiento"},
}
# Una columna con el CUIT de la empresa no es la identificación de la persona.
_NO_ES_DE_LA_PERSONA = {"empleador", "empleadora", "empresa", "razon"}
_CUIL_EXACTOS = {"c_u_i_l", "c_u_i_t", "identificacion", "nro_identificacion", "numero_identificacion",
                 "nro_de_identificacion", "numero_de_identificacion", "id_fiscal"}
# Se reconocen para AVISAR que no se usan: el padrón no se identifica por DNI.
_DOCUMENTO = {"dni", "documento", "nro_documento", "numero_documento", "nro_dni", "numero_dni",
              "nro_de_documento", "numero_de_documento", "doc"}

OPCIONES = (
    {"clave": "sin_seccional_desconocida", "rotulo": "Dejar afuera las de seccional desconocida",
     "ayuda": "Si la seccional que escribe la planilla no existe en el sindicato, deja a esa persona "
              "afuera en vez de cargarla sin seccional.",
     "defecto": False},
    {"clave": "total_declarado", "rotulo": "Total declarado por el sindicato", "tipo": "numero",
     "minimo": 0, "maximo": TOTAL_DECLARADO_MAX, "defecto": None,
     "ayuda": "Cuántos afiliados dice el sindicato que tiene. Al terminar se compara con lo que quedó en el padrón."},
)

_RE_FECHA_CON_HORA = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$")
_TEXTOS_RECHAZO = {
    "fecha": "Una de las fechas no se entiende (usá AAAA-MM-DD o DD/MM/AAAA).",
    "repetida": "Repetida en la planilla: se carga la primera.",
    "sin_cuil": "Falta la identificación.",
    "cuil_longitud": "Identificación inválida: no tiene 11 números.",
    "cuil_invalido": "Identificación inválida: el dígito verificador no cierra.",
    "sin_nombre": "Falta el nombre.",
    "domicilio": "Falta la localidad o la provincia.",
    "alcance": "La seccional no es la tuya.",
}


# ------------------------------------------------------------------ describir

def modelo_csv() -> str:
    """La planilla para completar: la cabecera de la alta masiva con las claves y
    dos filas de ejemplo (punto y coma, que es lo que Excel en castellano guarda)."""
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\n")
    w.writerow(padron_carga.ORDEN_LISTA)
    w.writerow(["20-90000001-4", "Pérez, Juan", "Córdoba", "1234", "", "Rosario", "Santa Fe",
                "341 555-0100", "juan.perez@ejemplo.org", "2000", "Seccional Rosario", "2018-03-01", "1985-07-12"])
    w.writerow(["27-90000002-7", "Gómez, María", "Avenida Colón", "650", "2° A", "Córdoba", "Córdoba",
                "351 555-0101", "", "5000", "Seccional Córdoba", "01/06/2020", ""])
    return "﻿" + salida.getvalue()


def describir() -> dict:
    return {
        "titulo": "Padrón de afiliados desde una planilla",
        "que_voy_a_hacer": [
            "Leo la planilla, detecto qué es cada columna y te muestro, persona por persona, qué cargaría y qué no: "
            "en el ensayo no se guarda nada.",
            "Si estás de acuerdo, cargo el padrón de una vez, lo comparo con el total que declaró el sindicato "
            "y dejo registrado quién lo hizo.",
        ],
        "insumo": "planilla_padron",
        "mapeo": True,
        "campos": [{"clave": c[0], "rotulo": c[1], "obligatorio": c[2], "ayuda": c[4]} for c in CAMPOS],
        "columnas": [{"clave": c[0], "rotulo": c[1], "obligatoria": c[2], "ejemplo": c[3], "ayuda": c[4]}
                     for c in CAMPOS],
        "modelo_csv": modelo_csv(),
        "opciones": [dict(o) for o in OPCIONES],
        "tope_filas": TOPE_FILAS,
        "tope_bytes": TOPE_BYTES,
    }


def _entero(valor, nombre: str):
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise ErrorAsistida(400, f"«{nombre}» tiene que ser un número.")
    try:
        n = float(str(valor).strip().replace(",", ".")) if isinstance(valor, str) else float(valor)
    except ValueError:
        raise ErrorAsistida(400, f"«{nombre}» tiene que ser un número.")
    if n != n or n in (float("inf"), float("-inf")) or n != int(n):
        raise ErrorAsistida(400, f"«{nombre}» tiene que ser un número entero.")
    n = int(n)
    if not 0 <= n <= TOTAL_DECLARADO_MAX:
        raise ErrorAsistida(400, f"«{nombre}» tiene que estar entre 0 y {base.miles(TOTAL_DECLARADO_MAX)}.")
    return n


def normalizar_opciones(opciones) -> dict:
    """Las opciones completas, con su defecto (incluye el `mapeo` que corrigió la
    persona, `{}` si no corrigió nada). Una opción mal formada es un error del
    pedido (400); una clave desconocida se ignora."""
    if opciones is None:
        opciones = {}
    if not isinstance(opciones, dict):
        raise ErrorAsistida(400, "Las opciones tienen que ser un objeto.")
    valor = opciones.get("sin_seccional_desconocida", False)
    if not isinstance(valor, bool):
        raise ErrorAsistida(400, "La opción «Dejar afuera las de seccional desconocida» tiene que ser verdadero o falso.")
    return {"sin_seccional_desconocida": valor,
            "total_declarado": _entero(opciones.get("total_declarado"), "Total declarado"),
            "mapeo": base.normalizar_mapeo(opciones.get("mapeo"), CLAVES)}


# ------------------------------------------------------------------ lectura

def _es_cuil(plano: str) -> bool:
    tokens = set(plano.split("_"))
    if tokens & _NO_ES_DE_LA_PERSONA:
        return False
    return bool(tokens & {"cuil", "cuit"}) or plano in _CUIL_EXACTOS


def _omitir_apellido(clave, asignado, planas) -> bool:
    # «Apellido y nombre» ya trae el apellido: no se duplica.
    return clave == "apellido" and any(c == "nombre" and planas[i] in _NOMBRE_COMPLETO
                                       for i, c in asignado.items())


def detectar(cabecera) -> dict:
    return base.detectar(cabecera, CLAVES, _SINONIMOS, {"cuil": _es_cuil}, _omitir_apellido)


def _fecha(valor: str) -> str:
    """Una fecha de planilla: si Excel la guardó con hora, se le saca la hora."""
    m = _RE_FECHA_CON_HORA.match(valor)
    return m.group(1) if m else valor


def leer(contenido: bytes, opciones: dict | None = None) -> dict:
    """Parsea la planilla. PURA. Devuelve `{opciones, mapeo, filas, total, avisos}`:
    `mapeo` es `{columnas, sin_usar, faltan}` y `filas` son las filas de
    `padron_carga.procesar` (`(linea, "", campos)`); con un campo obligatorio sin
    columna (`faltan`) no hay filas."""
    opciones = normalizar_opciones(opciones)
    cabecera, crudas = base.leer_csv(contenido, TOPE_FILAS, TOPE_BYTES)
    asignado = base.aplicar_mapeo(detectar(cabecera), opciones["mapeo"], len(cabecera), ROTULO)
    mapeo = base.mapeo_json(cabecera, crudas, asignado, OBLIGATORIOS)
    columnas, faltan, sin_usar = mapeo["columnas"], mapeo["faltan"], mapeo["sin_usar"]
    avisos = []
    es_doc = lambda c: listas._plano(c["cabecera"]) in _DOCUMENTO and not c["campo"]      # noqa: E731
    # La columna del documento tiene su propio aviso (dice por qué): no se repite en «No uso…».
    otras = [x for x in sin_usar if not any(es_doc(c) and c["cabecera"] == x for c in columnas)]
    if otras:
        avisos.append("No uso estas columnas: " + ", ".join(f"«{x}»" for x in otras) + ".")
    if any(es_doc(c) for c in columnas):
        avisos.append("La columna del documento (DNI) no se usa: el padrón se identifica por el número de 11 dígitos.")
    ley = {"opciones": opciones, "avisos": avisos, "total": 0, "filas": [],
           "mapeo": mapeo}
    if faltan:
        avisos.append("Falta indicar qué columna es " + " y ".join(f"«{ROTULO[c]}»" for c in faltan)
                      + ": elegila abajo y volvé a ensayar.")
        return ley
    por_campo = {c: i for i, c in asignado.items()}
    filas = []
    for linea, celdas in crudas:
        def celda(clave):
            i = por_campo.get(clave)
            return base.limpiar(celdas[i]) if i is not None and i < len(celdas) else ""
        campos = {k: celda(k) for k in padron_carga.CAMPOS_FILA}
        apellido, nombre = celda("apellido"), campos["nombre"]
        if apellido and nombre:
            campos["nombre"] = f"{apellido}, {nombre}"
        campos["fecha_afiliacion"] = _fecha(campos["fecha_afiliacion"])
        campos["fecha_nacimiento"] = _fecha(campos["fecha_nacimiento"])
        filas.append((linea, "", campos))
    ley.update(filas=filas, total=len(filas))
    return ley


# ------------------------------------------------------------------ ensayo

def _identificacion(d: dict) -> str:
    c = d["cuil"]
    return cuit.formatear(c) if len(c) == 11 else (c or "(vacía)")[:20]


def _clasificar(d: dict) -> tuple:
    """`(estado, motivos, accion)` de una fila del detalle de `procesar`."""
    if d["resultado"] == "alta":
        return ("dudosa" if d["dudas"] else "valida"), list(d["dudas"]), "crear"
    if d["resultado"] == "actualiza":
        cambia = d["cambia"]
        motivo = ("Ya está en el padrón: se actualiza solo lo que trae de mail o fecha de afiliación."
                  if cambia else "Ya está en el padrón: no cambia nada.")
        return "ya_existe", [motivo, *d["dudas"]], ("actualizar" if cambia else "sin_tocar")
    if d["tipo"] == "existe":
        return ("ya_existe",
                ["Ya está en el padrón: la fila no trae mail ni fecha de afiliación para actualizar."],
                "sin_tocar")
    return "rechazada", [d["motivo"] if d["tipo"] in ("seccional_desconocida", "existe")
                         else _TEXTOS_RECHAZO.get(d["tipo"], d["motivo"])], ""


def _resumen(d: dict, accion: str) -> dict:
    r = {"identificacion": _identificacion(d), "nombre": d["nombre"][:80],
         "seccional": d["seccional"][:60], "accion": accion}
    return {k: v for k, v in r.items() if v}


def _padron_actual(s, sid: int) -> int:
    from sqlalchemy import func
    from db import Trabajador
    return int(s.exec(select(func.count()).select_from(Trabajador).where(Trabajador.sindicato_id == sid)).one())


def _opciones_de_carga(opciones: dict) -> dict:
    return {"seccional_desconocida": "dejar_afuera" if opciones["sin_seccional_desconocida"] else "ignorar",
            "repetidas": "rechazar"}


def ensayar(s, sid: int, contenido: bytes, opciones: dict | None = None) -> dict:
    """El ensayo: lee la planilla y dice qué haría. No escribe nada."""
    ley = leer(contenido, opciones)
    opciones = ley["opciones"]
    salida = {"total": 0, "validas": 0, "dudosas": 0, "rechazadas": 0, "ya_existen": 0, "a_escribir": 0,
              "filas": [], "filas_truncadas": False, "motivos": [], "avisos": ley["avisos"], "muestra": [],
              "mapeo": ley["mapeo"], "opciones": opciones, "huella": huella(contenido, opciones),
              "padron_actual": _padron_actual(s, sid)}
    if ley["mapeo"]["faltan"]:
        return salida
    r = padron_carga.procesar(s, sid, ley["filas"], None, ensayo=True, **_opciones_de_carga(opciones))
    cuenta = Counter()
    grupos = {"dudosa": [], "rechazada": [], "ya_existe": []}
    motivos, a_escribir = {}, 0
    for d in r["filas"]:
        estado, ms, accion = _clasificar(d)
        cuenta[estado] += 1
        if estado in ("valida", "dudosa") or accion == "actualizar":
            a_escribir += 1
        if estado == "valida":
            if len(salida["muestra"]) < 5:
                salida["muestra"].append({"linea": d["linea"], "estado": estado, "motivos": [],
                                          "resumen": _resumen(d, accion)})
            continue
        grupos[estado].append((d, ms, accion))
        for m in ms:
            g = motivos.setdefault((estado, m), {"estado": estado, "motivo": m, "cantidad": 0, "lineas": []})
            g["cantidad"] += 1
            if len(g["lineas"]) < LINEAS_POR_MOTIVO:
                g["lineas"].append(d["linea"])
    # Primero lo que pide una decisión (las dudosas), después lo rechazado y lo que ya estaba.
    ordenadas = [x for e in ("dudosa", "rechazada", "ya_existe") for x in grupos[e]]
    for d, ms, accion in ordenadas[:TOPE_FILAS_DEVUELTAS]:
        estado = _clasificar(d)[0]
        salida["filas"].append({"linea": d["linea"], "estado": estado, "motivos": ms, "resumen": _resumen(d, accion)})
    salida["filas_truncadas"] = len(ordenadas) > TOPE_FILAS_DEVUELTAS
    orden = {"dudosa": 0, "rechazada": 1, "ya_existe": 2}
    salida["motivos"] = sorted(motivos.values(), key=lambda g: (orden[g["estado"]], -g["cantidad"], g["motivo"]))
    salida.update(total=ley["total"], validas=cuenta["valida"], dudosas=cuenta["dudosa"],
                  rechazadas=cuenta["rechazada"], ya_existen=cuenta["ya_existe"], a_escribir=a_escribir)
    if opciones["total_declarado"] is not None:
        previsto = salida["padron_actual"] + r["altas"]
        salida["avisos"].append(
            f"Con esta carga el padrón quedaría en {base.miles(previsto)} afiliados; el sindicato declaró "
            f"{base.miles(opciones['total_declarado'])}.")
    return salida


# ------------------------------------------------------------------ carga

def cargar(s, sid: int, contenido: bytes, opciones: dict | None = None, dejar_afuera=()) -> dict:
    """Vuelve a leer con la MISMA función del ensayo y escribe con la función
    compartida de la alta masiva. NO confirma la transacción. `dejar_afuera`:
    líneas dudosas que no entran (una línea que no es dudosa se ignora)."""
    ley = leer(contenido, opciones)
    opciones = ley["opciones"]
    if ley["mapeo"]["faltan"]:
        raise ErrorAsistida(400, "Falta indicar qué columna es "
                            + " y ".join(f"«{ROTULO[c]}»" for c in ley["mapeo"]["faltan"]) + ".")
    r = padron_carga.procesar(s, sid, ley["filas"], None, ensayo=False,
                              lineas_afuera={int(x) for x in dejar_afuera}, **_opciones_de_carga(opciones))
    res = {"creadas": r["altas"], "actualizadas": 0, "sin_tocar": 0, "afuera": r["elegidas_afuera"],
           "rechazadas": 0, "detalle": [], "detalle_truncado": False, "avisos": ley["avisos"]}

    def anotar(d, accion):
        if len(res["detalle"]) < TOPE_FILAS_DEVUELTAS:
            res["detalle"].append({"linea": d["linea"], "identificacion": _identificacion(d), "accion": accion})
        else:
            res["detalle_truncado"] = True

    for d in r["filas"]:
        if d["resultado"] == "alta":
            continue
        if d["resultado"] == "actualiza" and d["cambia"]:
            res["actualizadas"] += 1
            anotar(d, "actualizada")
        elif d["resultado"] == "actualiza" or d["tipo"] == "existe":
            res["sin_tocar"] += 1
        elif d["tipo"] == "elegida":
            anotar(d, "afuera")
        else:
            res["rechazadas"] += 1
            anotar(d, "rechazada")
    if opciones["total_declarado"] is not None:
        s.flush()
        cargado = _padron_actual(s, sid)
        res["comparacion"] = {"declarado": opciones["total_declarado"], "cargado": cargado,
                              "diferencia": cargado - opciones["total_declarado"]}
    return res


def movimiento(carga: dict) -> tuple:
    """`(texto, cantidades)` del movimiento `asistida_carga`: solo cantidades,
    nunca una identificación ni un nombre de la planilla."""
    texto = (f"Cargó {base.plural(carga['creadas'], 'afiliado', 'afiliados')} al padrón desde planilla "
             f"({base.plural(carga['actualizadas'], 'actualizado', 'actualizados')}, {carga['afuera']} afuera)")
    cantidades = {k: carga[k] for k in ("creadas", "actualizadas", "sin_tocar", "afuera", "rechazadas")}
    if carga.get("comparacion"):
        cantidades.update(carga["comparacion"])
    return texto, cantidades
