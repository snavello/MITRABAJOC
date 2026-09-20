"""Motor de XSK: lee el catálogo, los hallazgos y las corridas de un proyecto y
calcula riesgo y ranking. **Puro**: no importa `db` ni nada de la app, así se
prueba solo y se lleva a otro repositorio sin arrastrar nada.

Todo archivo de XSK es Markdown con una cabecera de líneas `clave: valor`
entre dos `---`. No se usa YAML de verdad a propósito: no hace falta una
dependencia para leer diez claves, y el formato que se puede leer a ojo es el
que sobrevive cuando la herramienta no está.

Principio "hechos, no derivados": los archivos guardan probabilidad, daño y
complejidad; el riesgo, el nivel y el ranking se calculan acá, al mostrarlos.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CATALOGO = RAIZ / "catalogo"
PROYECTOS = RAIZ / "proyectos"

# Los nueve ejes. Genéricos: cualquier sistema web con usuarios y datos los
# tiene, aunque en algunos un eje quede vacío en el alcance.
EJES = {
    "IDS": "Identidad y sesiones",
    "AUT": "Autorización y aislamiento",
    "ENT": "Entradas",
    "IA": "Superficie de la IA",
    "DAT": "Datos y criptografía",
    "DIS": "Disponibilidad y abuso",
    "INF": "Infraestructura y cadena de suministro",
    "OBS": "Detección y respuesta",
    "LEY": "Protección de datos",
}

ESTADOS = ("abierto", "en_correccion", "corregido", "verificado", "aceptado")
ESTADOS_NO_CERRADOS = ("abierto", "en_correccion")

TIPOS_TEST = ("revision", "estatico", "dinamico", "configuracion", "manual")
RESULTADOS = ("paso", "fallo", "no_aplica", "error")

# (riesgo mínimo, nivel). Se recorre de arriba a abajo.
NIVELES = ((15, "critico"), (10, "alto"), (5, "medio"), (1, "bajo"))

CLAVES_HALLAZGO = (
    "id", "titulo", "eje", "test", "estado",
    "probabilidad", "dano", "complejidad",
    "owasp", "asvs", "cwe", "encontrado", "corrida",
)
CLAVES_TEST = (
    "id", "eje", "titulo", "tipo", "herramienta", "entorno", "destructivo",
    "owasp", "asvs", "cwe", "activo",
)
CLAVES_CORRIDA = ("fecha", "eje", "entorno", "iteracion")

_ID_HALLAZGO = re.compile(r"^H-\d{4}$")
_ID_TEST = re.compile(r"^[A-Z]{2,3}-\d{2}$")
# Una línea de resultado dentro de una corrida: "- IDS-01: paso — evidencia".
_LINEA_RESULTADO = re.compile(
    r"^- (?P<test>[A-Z]{2,3}-\d{2}): (?P<resultado>[a-z_]+)(?: [—-] (?P<nota>.*))?$"
)


class ErrorRegistro(ValueError):
    """Un archivo del registro está mal formado. El mensaje nombra el archivo y
    la clave: un registro que no se puede leer no es un registro."""


def leer_cabecera(texto: str) -> tuple[dict, str]:
    """Separa la cabecera `clave: valor` del cuerpo. Devuelve (cabecera, cuerpo)."""
    lineas = texto.replace("\r\n", "\n").split("\n")
    if not lineas or lineas[0].strip() != "---":
        raise ErrorRegistro("falta la cabecera (el archivo no empieza con ---)")
    cabecera: dict[str, str] = {}
    for i, linea in enumerate(lineas[1:], start=1):
        if linea.strip() == "---":
            return cabecera, "\n".join(lineas[i + 1:])
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        if ":" not in linea:
            raise ErrorRegistro(f"línea {i + 1} de la cabecera sin 'clave: valor': {linea!r}")
        clave, valor = linea.split(":", 1)
        cabecera[clave.strip()] = valor.strip()
    raise ErrorRegistro("la cabecera no se cierra (falta el segundo ---)")


def leer_archivo(ruta: Path) -> dict:
    """Lee un archivo del registro. Devuelve la cabecera como dict, más `cuerpo`
    y `archivo`."""
    try:
        cabecera, cuerpo = leer_cabecera(ruta.read_text(encoding="utf-8"))
    except ErrorRegistro as e:
        raise ErrorRegistro(f"{ruta.name}: {e}") from None
    cabecera["cuerpo"] = cuerpo
    cabecera["archivo"] = ruta.name
    return cabecera


def _archivos(carpeta: Path) -> list[Path]:
    """Los .md de una carpeta, sin las plantillas ni los README, en orden."""
    if not carpeta.is_dir():
        return []
    return sorted(
        p for p in carpeta.glob("*.md")
        if not p.name.startswith("_") and p.name.upper() != "README.MD"
    )


def _exigir(datos: dict, claves: tuple[str, ...]) -> None:
    faltan = [c for c in claves if not datos.get(c)]
    if faltan:
        raise ErrorRegistro(f"{datos.get('archivo', '?')}: faltan las claves {', '.join(faltan)}")


def _entero_1_a_5(datos: dict, clave: str) -> int:
    try:
        valor = int(datos[clave])
    except (TypeError, ValueError):
        raise ErrorRegistro(f"{datos['archivo']}: {clave} tiene que ser un entero de 1 a 5, no {datos[clave]!r}") from None
    if not 1 <= valor <= 5:
        raise ErrorRegistro(f"{datos['archivo']}: {clave} tiene que estar entre 1 y 5, no {valor}")
    return valor


# --- Hallazgos ----------------------------------------------------------------

def validar_hallazgo(h: dict) -> dict:
    """Verifica un hallazgo y convierte los números. Devuelve el mismo dict."""
    _exigir(h, CLAVES_HALLAZGO)
    if not _ID_HALLAZGO.match(h["id"]):
        raise ErrorRegistro(f"{h['archivo']}: id {h['id']!r} no tiene la forma H-0000")
    if h["eje"] not in EJES:
        raise ErrorRegistro(f"{h['archivo']}: eje {h['eje']!r} no es uno de {', '.join(EJES)}")
    if not _ID_TEST.match(h["test"]):
        raise ErrorRegistro(f"{h['archivo']}: test {h['test']!r} no tiene la forma EJE-00")
    if h["estado"] not in ESTADOS:
        raise ErrorRegistro(f"{h['archivo']}: estado {h['estado']!r} no es uno de {', '.join(ESTADOS)}")
    for clave in ("probabilidad", "dano", "complejidad"):
        h[clave] = _entero_1_a_5(h, clave)
    if h["estado"] == "aceptado":
        _exigir(h, ("aceptado_por", "aceptado_hasta", "motivo"))
    return h


def riesgo(h: dict) -> int:
    return int(h["probabilidad"]) * int(h["dano"])


def nivel(valor: int) -> str:
    for minimo, nombre in NIVELES:
        if valor >= minimo:
            return nombre
    return "bajo"


def leer_hallazgos(carpeta: Path) -> list[dict]:
    """Todos los hallazgos de la carpeta, validados, con `riesgo` y `nivel`."""
    hallazgos = []
    vistos: dict[str, str] = {}
    for ruta in _archivos(carpeta):
        h = validar_hallazgo(leer_archivo(ruta))
        if h["id"] in vistos:
            raise ErrorRegistro(f"{ruta.name}: el id {h['id']} ya está en {vistos[h['id']]}")
        vistos[h["id"]] = ruta.name
        h["riesgo"] = riesgo(h)
        h["nivel"] = nivel(h["riesgo"])
        hallazgos.append(h)
    return hallazgos


def ranking(hallazgos: list[dict]) -> list[dict]:
    """Los no cerrados, del más al menos urgente: riesgo descendente y, a
    igual riesgo, complejidad ascendente (primero lo más fácil)."""
    abiertos = [h for h in hallazgos if h["estado"] in ESTADOS_NO_CERRADOS]
    return sorted(abiertos, key=lambda h: (-h["riesgo"], h["complejidad"], h["id"]))


def resumen(hallazgos: list[dict]) -> dict:
    """Conteos para el tablero: por estado, por nivel (solo no cerrados) y por eje."""
    por_estado = {e: 0 for e in ESTADOS}
    por_nivel = {n: 0 for _, n in NIVELES}
    por_eje = {e: {"total": 0, "abiertos": 0} for e in EJES}
    for h in hallazgos:
        por_estado[h["estado"]] += 1
        por_eje[h["eje"]]["total"] += 1
        if h["estado"] in ESTADOS_NO_CERRADOS:
            por_nivel[h["nivel"]] += 1
            por_eje[h["eje"]]["abiertos"] += 1
    return {"por_estado": por_estado, "por_nivel": por_nivel, "por_eje": por_eje,
            "total": len(hallazgos)}


def bloquea_produccion(hallazgos: list[dict]) -> list[dict]:
    """Los que, según el criterio de salida, impiden salir: Críticos y Altos
    no cerrados."""
    return [h for h in ranking(hallazgos) if h["nivel"] in ("critico", "alto")]


def proximo_id(hallazgos: list[dict]) -> str:
    """El id siguiente al mayor existente. Nunca se reutiliza un número."""
    mayor = max((int(h["id"][2:]) for h in hallazgos), default=0)
    return f"H-{mayor + 1:04d}"


# --- Catálogo -----------------------------------------------------------------

def validar_test(t: dict) -> dict:
    _exigir(t, CLAVES_TEST)
    if not _ID_TEST.match(t["id"]):
        raise ErrorRegistro(f"{t['archivo']}: id {t['id']!r} no tiene la forma EJE-00")
    if t["eje"] not in EJES:
        raise ErrorRegistro(f"{t['archivo']}: eje {t['eje']!r} no es uno de {', '.join(EJES)}")
    if not t["id"].startswith(t["eje"] + "-"):
        raise ErrorRegistro(f"{t['archivo']}: el id {t['id']} no empieza por el eje {t['eje']}")
    if t["tipo"] not in TIPOS_TEST:
        raise ErrorRegistro(f"{t['archivo']}: tipo {t['tipo']!r} no es uno de {', '.join(TIPOS_TEST)}")
    if t["destructivo"] not in ("si", "no"):
        raise ErrorRegistro(f"{t['archivo']}: destructivo tiene que ser 'si' o 'no'")
    return t


def leer_catalogo(carpeta: Path = CATALOGO) -> list[dict]:
    tests = []
    vistos: dict[str, str] = {}
    for ruta in _archivos(carpeta):
        t = validar_test(leer_archivo(ruta))
        if t["id"] in vistos:
            raise ErrorRegistro(f"{ruta.name}: el id {t['id']} ya está en {vistos[t['id']]}")
        vistos[t["id"]] = ruta.name
        tests.append(t)
    return sorted(tests, key=lambda t: t["id"])


# --- Corridas -----------------------------------------------------------------

def resultados_de_corrida(cuerpo: str) -> list[dict]:
    """Las líneas `- EJE-00: resultado — nota` del cuerpo de una corrida."""
    salida = []
    for linea in cuerpo.replace("\r\n", "\n").split("\n"):
        m = _LINEA_RESULTADO.match(linea.strip())
        if not m:
            continue
        if m["resultado"] not in RESULTADOS:
            raise ErrorRegistro(f"resultado {m['resultado']!r} de {m['test']} no es uno de {', '.join(RESULTADOS)}")
        salida.append({"test": m["test"], "resultado": m["resultado"], "nota": m["nota"] or ""})
    return salida


def leer_corridas(carpeta: Path) -> list[dict]:
    """Las corridas, de la más reciente a la más vieja, cada una con `resultados`."""
    corridas = []
    for ruta in _archivos(carpeta):
        c = leer_archivo(ruta)
        _exigir(c, CLAVES_CORRIDA)
        try:
            c["resultados"] = resultados_de_corrida(c["cuerpo"])
        except ErrorRegistro as e:
            raise ErrorRegistro(f"{ruta.name}: {e}") from None
        corridas.append(c)
    return sorted(corridas, key=lambda c: c["fecha"], reverse=True)


def ultimo_resultado_por_test(corridas: list[dict]) -> dict[str, dict]:
    """Para cada test, su resultado en la corrida más reciente que lo incluyó."""
    ultimo: dict[str, dict] = {}
    for c in corridas:  # ya vienen de la más reciente a la más vieja
        for r in c["resultados"]:
            if r["test"] not in ultimo:
                ultimo[r["test"]] = {**r, "fecha": c["fecha"], "entorno": c["entorno"]}
    return ultimo


# --- Proyecto -----------------------------------------------------------------

def carpeta_proyecto(nombre: str) -> Path:
    carpeta = PROYECTOS / nombre
    if not carpeta.is_dir():
        raise ErrorRegistro(f"no existe el proyecto {nombre!r} en {PROYECTOS}")
    return carpeta


ESTADOS_ETAPA = ("pendiente", "en_curso", "hecha")
CLAVES_AVANCE = ("iteracion", "etapa_actual") + tuple(f"etapa{n}" for n in range(10))


def leer_avance(carpeta: Path) -> dict:
    """`avance.md` del proyecto: en qué iteración y etapa está, y el estado de
    cada una de las diez. El cuerpo es el texto libre de "cómo seguir"."""
    a = leer_archivo(carpeta / "avance.md")
    _exigir(a, CLAVES_AVANCE)
    for n in range(10):
        if a[f"etapa{n}"] not in ESTADOS_ETAPA:
            raise ErrorRegistro(f"avance.md: etapa{n} tiene que ser uno de {', '.join(ESTADOS_ETAPA)}")
    a["iteracion"] = int(a["iteracion"])
    a["etapa_actual"] = int(a["etapa_actual"])
    a["etapas"] = [a[f"etapa{n}"] for n in range(10)]
    return a


def estado_proyecto(nombre: str) -> dict:
    """Todo lo que la página de avance necesita, en un solo dict."""
    carpeta = carpeta_proyecto(nombre)
    hallazgos = leer_hallazgos(carpeta / "hallazgos")
    corridas = leer_corridas(carpeta / "corridas")
    return {
        "proyecto": nombre,
        "avance": leer_avance(carpeta),
        "catalogo": leer_catalogo(),
        "hallazgos": hallazgos,
        "ranking": ranking(hallazgos),
        "bloquean": bloquea_produccion(hallazgos),
        "resumen": resumen(hallazgos),
        "corridas": corridas,
        "ultimo_por_test": ultimo_resultado_por_test(corridas),
    }
