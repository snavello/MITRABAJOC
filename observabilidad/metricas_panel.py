"""Los gráficos de la pestaña "Observabilidad" de /entornos: lo mismo que el tablero de Grafana, pero
adentro de la app, para mirarlo sin iniciar sesión en Grafana (entrás con el PIN y listo).

No define consultas propias: las saca del tablero (`aplicar_tablero.construir_tablero`), así lo que se
ve acá y lo que se ve en Grafana no puede diferir. Los datos se piden a Grafana con el token de LECTURA
(Viewer) por el proxy de su fuente Prometheus; la app no guarda nada.

Regla 0: esto es una comodidad. Si la app se cae, este panel se cae con ella, pero el tablero de Grafana
y los avisos por mail siguen funcionando porque no dependen de la app.

Las respuestas se guardan 45 segundos por rango: abrir la pestaña varias veces seguidas no multiplica
las consultas.
"""
import math
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import aplicar_grafana as ag
from . import aplicar_tablero as at
from . import panel

FUENTE_UID = "grafanacloud-prom"
RANGOS = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
PUNTOS_MAXIMOS = 150
VIGENCIA_CACHE = 45
# Ids de los paneles del tablero (aplicar_tablero.construir_tablero): los números de "ahora" y las series.
TARJETAS = (1, 2, 3, 5, 6, 7, 8, 9, 10, 4)
GRAFICOS = (11, 12, 15, 14, 13, 16, 17)
COLORES = {"green": "ok", "orange": "atencion", "red": "mal"}

_cache = {}
_candado = threading.Lock()


def _paneles() -> dict:
    tablero = at.construir_tablero(ag.cargar_config())
    return {p["id"]: p for p in tablero["panels"]}


def _estado_de(valor, pasos) -> str:
    """El color del umbral que le toca a `valor` (los pasos vienen de menor a mayor)."""
    color = "green"
    for p in pasos:
        if p["value"] is None or valor >= p["value"]:
            color = p["color"]
    return COLORES.get(color, "ok")


def _texto_de(valor, mapeos) -> str:
    for m in mapeos:
        if m.get("type") == "value" and str(int(valor)) in m["options"]:
            return m["options"][str(int(valor))]["text"]
    return ""


def _numero(texto):
    try:
        v = float(texto)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _instantaneo(g, expr: str):
    p = urllib.parse.urlencode({"query": expr})
    st, d = g.pedir("GET", f"/api/datasources/proxy/uid/{FUENTE_UID}/api/v1/query?{p}")
    if st != 200 or (d or {}).get("status") != "success":
        raise panel.ErrorObservabilidad(f"Grafana respondió HTTP {st}.")
    res = d["data"]["result"]
    return _numero(res[0]["value"][1]) if res else None


def _rango(g, expr: str, desde: int, hasta: int, paso: int) -> list:
    p = urllib.parse.urlencode({"query": expr, "start": desde, "end": hasta, "step": paso})
    st, d = g.pedir("GET", f"/api/datasources/proxy/uid/{FUENTE_UID}/api/v1/query_range?{p}")
    if st != 200 or (d or {}).get("status") != "success":
        raise panel.ErrorObservabilidad(f"Grafana respondió HTTP {st}.")
    return d["data"]["result"]


def _leyenda(plantilla: str, etiquetas: dict) -> str:
    texto = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(etiquetas.get(m.group(1), "")), plantilla or "")
    return texto or "valor"


def _tarjeta(g, p: dict) -> dict:
    campo = p["fieldConfig"]["defaults"]
    valor = _instantaneo(g, p["targets"][0]["expr"])
    t = {"id": p["id"], "titulo": p["title"], "descripcion": p.get("description", ""), "unidad": campo.get("unit", "none"),
         "decimales": campo.get("decimals"), "valor": valor, "texto": "", "estado": "sin_datos"}
    if valor is not None:
        t["estado"] = _estado_de(valor, campo["thresholds"]["steps"])
        t["texto"] = _texto_de(valor, [m for m in campo["mappings"] if m.get("type") == "value"])
    return t


def _grafico(g, p: dict, desde: int, hasta: int, paso: int) -> dict:
    campo = p["fieldConfig"]["defaults"]
    pasos = campo["thresholds"]["steps"]
    umbral = pasos[1]["value"] if len(pasos) > 1 else None
    series = []
    for objetivo in p["targets"]:
        for s in _rango(g, objetivo["expr"], desde, hasta, paso):
            puntos = [[int(t), v] for t, raw in s["values"] if (v := _numero(raw)) is not None]
            series.append({"nombre": _leyenda(objetivo.get("legendFormat"), s.get("metric", {})), "puntos": puntos})
    return {"id": p["id"], "titulo": p["title"], "descripcion": p.get("description", ""),
            "unidad": campo.get("unit", "none"), "umbral": umbral, "minimo": campo.get("min"),
            "apilado": p["fieldConfig"]["defaults"]["custom"]["stacking"]["mode"] == "normal", "series": series}


def _leer(rango: str) -> dict:
    g = panel._cliente("GRAFANA_TOKEN_LECTURA")
    paneles = _paneles()
    hasta = int(time.time())
    desde = hasta - RANGOS[rango]
    paso = max(60, RANGOS[rango] // PUNTOS_MAXIMOS)
    errores = []

    def seguro(f, *a):
        try:
            return f(*a)
        except Exception as e:
            errores.append(f"{a[1]['title']}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        tarjetas = list(pool.map(lambda i: seguro(_tarjeta, g, paneles[i]), TARJETAS))
        graficos = list(pool.map(lambda i: seguro(_grafico, g, paneles[i], desde, hasta, paso), GRAFICOS))
    return {"rango": rango, "desde": desde, "hasta": hasta, "paso": paso,
            "tarjetas": [t for t in tarjetas if t], "graficos": [x for x in graficos if x], "errores": errores}


def estado(rango: str = "6h", forzar: bool = False) -> dict:
    """Todo lo que la pestaña dibuja. Nunca lanza: lo que falla queda en `errores`."""
    if rango not in RANGOS:
        raise ValueError("Rango inválido.")
    if not panel.configurado():
        return {"rango": rango, "tarjetas": [], "graficos": [],
                "errores": ["Falta GRAFANA_URL o GRAFANA_TOKEN_LECTURA en este servicio."]}
    with _candado:
        c = _cache.get(rango)
        if c and not forzar and time.monotonic() < c["hasta"]:
            return c["datos"]
    try:
        datos = _leer(rango)
    except Exception as e:
        return {"rango": rango, "tarjetas": [], "graficos": [], "errores": [f"No se pudo consultar a Grafana: {e}"]}
    if datos["tarjetas"] or datos["graficos"]:
        with _candado:
            _cache[rango] = {"hasta": time.monotonic() + VIGENCIA_CACHE, "datos": datos}
    return datos
