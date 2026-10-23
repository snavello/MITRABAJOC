"""Listas del sindicato: las plantillas y el parseo del CSV (PLAN_LISTAS_VALIDACIONES.md, D1 y D5).

Módulo PURO: no importa `db`. Una lista es una tabla por sindicato con
columnas declaradas; lo que el admin ve son PLANTILLAS con cabecera fija
(grupo familiar, datos del afiliado, lista simple), que se descargan como
CSV modelo, se completan y se suben. Acá vive todo lo que no toca la base:

- `PLANTILLAS`: qué columnas tiene cada una, de qué tipo, y cuáles son las
  claves de búsqueda (la primera es SIEMPRE el CUIL del afiliado).
- `csv_modelo`: el archivo que el admin descarga para completar.
- `parsear_csv`: lee lo que subió, normaliza y valida FILA POR FILA, y
  devuelve las filas buenas y los errores con su número de línea. No
  escribe nada: el ensayo y la carga usan el mismo parseo.

Reglas:
- El CUIL se exige con módulo 11 (`cuit.es_valido`): en una lista el número
  NACE, no se referencia (CLAUDE.md, "El CUIL/CUIT cumple el módulo 11
  donde NACE").
- Las fechas se aceptan como AAAA-MM-DD o DD/MM/AAAA y se guardan ISO, como
  todas las fechas del proyecto.
- Hechos, no derivados: se guarda la fecha de afiliación, nunca la
  antigüedad; la fecha de nacimiento, nunca la edad.
"""
import csv
import io
import re
import unicodedata
from datetime import date

import cuit

MAX_FILAS = 50_000
MAX_ERRORES = 200            # los que se devuelven; el resto se cuenta
LARGO_TEXTO = 120

# tipo: cuil | dni | texto | fecha. `clave` 1 o 2 marca las columnas por las
# que se busca (1 = CUIL del afiliado, siempre; 2 = la segunda clave, si hay).
PLANTILLAS = {
    "grupo_familiar": {
        "nombre": "Grupo familiar",
        "descripcion": "Los familiares a cargo de cada afiliado: una fila por familiar. Sirve para validar el DNI del familiar en un trámite (kit escolar, guardería, ayuda por nacimiento).",
        "columnas": [
            {"clave": "cuil", "tipo": "cuil", "rotulo": "CUIL del afiliado", "busqueda": 1},
            {"clave": "dni", "tipo": "dni", "rotulo": "DNI del familiar", "busqueda": 2},
            {"clave": "apellido_nombre", "tipo": "texto", "rotulo": "Apellido y nombre del familiar"},
            {"clave": "vinculo", "tipo": "texto", "rotulo": "Vínculo (hijo/a, cónyuge…)"},
            {"clave": "fecha_nacimiento", "tipo": "fecha", "rotulo": "Fecha de nacimiento"},
        ],
        "ejemplo": [["20111111112", "55123456", "Pérez, Martina", "Hija", "2017-03-09"],
                    ["20111111112", "58765432", "Pérez, Tomás", "Hijo", "2021-11-21"]],
    },
    "datos_afiliado": {
        "nombre": "Datos del afiliado",
        "descripcion": "Un dato por afiliado que el padrón todavía no tiene: fecha de afiliación, fecha de nacimiento, categoría. Una fila por CUIL.",
        "columnas": [
            {"clave": "cuil", "tipo": "cuil", "rotulo": "CUIL del afiliado", "busqueda": 1},
            {"clave": "fecha_afiliacion", "tipo": "fecha", "rotulo": "Fecha de afiliación"},
            {"clave": "fecha_nacimiento", "tipo": "fecha", "rotulo": "Fecha de nacimiento"},
            {"clave": "categoria", "tipo": "texto", "rotulo": "Categoría"},
        ],
        "ejemplo": [["20111111112", "2019-05-02", "1988-07-15", "Administrativo inicial"],
                    ["27222222228", "2024-10-01", "1995-01-30", "Cajero"]],
    },
    "simple": {
        "nombre": "Lista simple",
        "descripcion": "Solo CUIL: quiénes están (o no) en una lista. Sirve para «está en la lista» / «no está»: beneficiarios de una campaña, delegados, excluidos.",
        "columnas": [
            {"clave": "cuil", "tipo": "cuil", "rotulo": "CUIL del afiliado", "busqueda": 1},
        ],
        "ejemplo": [["20111111112"], ["27222222228"]],
    },
}

_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_AR = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _plano(s: str) -> str:
    """Minúsculas, sin tildes, espacios → guion bajo: para comparar cabeceras."""
    plano = unicodedata.normalize("NFD", str(s or "").strip().lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", plano).strip("_")


def columnas(plantilla: str) -> list:
    return list(PLANTILLAS[plantilla]["columnas"])


def claves_de(plantilla: str) -> tuple:
    """(clave de la columna 1, clave de la columna 2 o None)."""
    cols = columnas(plantilla)
    c1 = next(c["clave"] for c in cols if c.get("busqueda") == 1)
    c2 = next((c["clave"] for c in cols if c.get("busqueda") == 2), None)
    return c1, c2


def csv_modelo(plantilla: str) -> str:
    """El archivo para completar: cabecera con las claves de las columnas y
    dos filas de ejemplo. Con punto y coma, que es lo que Excel en
    castellano abre y guarda sin pelear."""
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\n")
    w.writerow([c["clave"] for c in columnas(plantilla)])
    for fila in PLANTILLAS[plantilla]["ejemplo"]:
        w.writerow(fila)
    return "﻿" + salida.getvalue()


def normalizar_fecha(valor: str):
    """AAAA-MM-DD o DD/MM/AAAA → AAAA-MM-DD; None si no es una fecha."""
    v = str(valor or "").strip()
    m = _RE_ISO.match(v)
    if m:
        a, mes, d = (int(x) for x in m.groups())
    else:
        m = _RE_AR.match(v)
        if not m:
            return None
        d, mes, a = (int(x) for x in m.groups())
    try:
        return date(a, mes, d).isoformat()
    except ValueError:
        return None


def normalizar_dni(valor: str):
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos if 6 <= len(digitos) <= 9 else None


def _decodificar(contenido: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return contenido.decode(enc)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1", errors="replace")


def _dialecto(texto: str) -> str:
    primera = texto.splitlines()[0] if texto.strip() else ""
    for sep in (";", ",", "\t"):
        if sep in primera:
            return sep
    return ";"


def _valor(col: dict, crudo: str):
    """(valor normalizado, motivo del error o None)."""
    v = str(crudo or "").strip()
    if col["tipo"] == "cuil":
        n = cuit.normalizar(v)
        if not n or not cuit.es_valido(n):
            return None, "CUIL inválido (dígito verificador)"
        return n, None
    if col["tipo"] == "dni":
        n = normalizar_dni(v)
        return (n, None) if n else (None, "DNI inválido")
    if col["tipo"] == "fecha":
        if not v:
            return "", None
        f = normalizar_fecha(v)
        return (f, None) if f else (None, "fecha ilegible (usá AAAA-MM-DD o DD/MM/AAAA)")
    return v[:LARGO_TEXTO], None


def parsear_csv(plantilla: str, contenido: bytes) -> dict:
    """Lee el CSV y devuelve {"filas": [...], "errores": [...], "total",
    "validas", "con_error"}. Cada fila buena trae clave1, clave2 y datos (todas
    las columnas, ya normalizadas). Cada error trae la línea (contando la
    cabecera como 1) y el motivo. Nunca escribe nada."""
    if plantilla not in PLANTILLAS:
        raise ValueError("Plantilla desconocida.")
    cols = columnas(plantilla)
    c1, c2 = claves_de(plantilla)
    texto = _decodificar(contenido or b"")
    lector = csv.reader(io.StringIO(texto), delimiter=_dialecto(texto))
    filas, errores, vistas = [], [], set()
    total = con_error = 0
    try:
        cabecera = next(lector)
    except StopIteration:
        return {"filas": [], "errores": [{"linea": 1, "motivo": "El archivo está vacío."}],
                "total": 0, "validas": 0, "con_error": 1, "columnas": cols}
    posicion = {}
    planas = [_plano(h) for h in cabecera]
    for col in cols:
        candidatos = {col["clave"], _plano(col["rotulo"])}
        idx = next((i for i, h in enumerate(planas) if h in candidatos), None)
        if idx is None:
            return {"filas": [], "errores": [{"linea": 1, "motivo": f"Falta la columna «{col['clave']}» en la cabecera."}],
                    "total": 0, "validas": 0, "con_error": 1, "columnas": cols}
        posicion[col["clave"]] = idx

    def error(linea, motivo):
        nonlocal con_error
        con_error += 1
        if len(errores) < MAX_ERRORES:
            errores.append({"linea": linea, "motivo": motivo})

    for numero, celdas in enumerate(lector, start=2):
        if not any(str(x).strip() for x in celdas):
            continue
        total += 1
        if total > MAX_FILAS:
            error(numero, f"Más de {MAX_FILAS} filas: partí el archivo.")
            break
        datos, motivos = {}, []
        for col in cols:
            crudo = celdas[posicion[col["clave"]]] if posicion[col["clave"]] < len(celdas) else ""
            valor, motivo = _valor(col, crudo)
            if motivo:
                motivos.append(f"{col['clave']}: {motivo}")
            datos[col["clave"]] = valor
        if motivos:
            error(numero, "; ".join(motivos))
            continue
        clave = (datos[c1], datos[c2] if c2 else "")
        if clave in vistas:
            error(numero, "fila repetida (misma clave que una anterior)")
            continue
        vistas.add(clave)
        filas.append({"clave1": clave[0], "clave2": clave[1], "datos": datos})
    return {"filas": filas, "errores": errores, "total": total, "validas": len(filas),
            "con_error": con_error, "columnas": cols}


def resumen_plantillas() -> list:
    """Lo que la pantalla muestra de cada plantilla."""
    return [{"clave": k, "nombre": p["nombre"], "descripcion": p["descripcion"],
             "columnas": [{"clave": c["clave"], "rotulo": c["rotulo"], "tipo": c["tipo"], "busqueda": c.get("busqueda", 0)}
                          for c in p["columnas"]]}
            for k, p in PLANTILLAS.items()]
