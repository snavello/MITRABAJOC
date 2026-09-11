# -*- coding: utf-8 -*-
"""El catálogo de planes de Render que ve la pantalla.

Los datos salen de data/render_planes.json, que genera
actualizar_planes_render.py leyendo render.com/pricing. Este módulo solo lo
carga y le da formato en castellano. Si el archivo no está (clon viejo, o el
scraper nunca corrió), devuelve un catálogo vacío y la pantalla lo dice --
nunca un precio inventado.
"""
import json
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parent / "data" / "render_planes.json"


def _num(x) -> str:
    """1234.5 -> "1.234,5" (separadores castellanos, sin decimales si es entero)."""
    entero = float(x) == int(float(x))
    txt = f"{float(x):,.0f}" if entero else f"{float(x):,.2f}"
    return txt.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _vcpu(v) -> str:
    return _num(v) + (" vCPU" if float(v) != 1 else " vCPU")


def _ram(mb) -> str:
    return f"{_num(mb / 1024)} GB" if mb >= 1024 else f"{_num(mb)} MB"


def _decorar(p: dict, tipo: str) -> dict:
    """Agrega los textos ya armados para no hacer cuentas en la plantilla."""
    d = dict(p)
    d["etiqueta"] = f"{_vcpu(p['vcpu'])} / {_ram(p['ram_mb'])}"
    d["precio_txt"] = f"US$ {_num(p['usd_mes'])}/mes"
    d["usd_dia"] = round(p["usd_mes"] / 30, 2)
    # Render prorratea por segundo, así que lo que de verdad cuesta prender
    # un plan grande unas horas es esto, no el precio mensual.
    d["usd_hora_txt"] = f"US$ {_num(round(p['usd_mes'] / 730, 3))}/hora"
    d["tipo"] = tipo
    if tipo == "db":
        d["conexiones_txt"] = f"{_num(p['conexiones_max'])} conexiones"
    return d


def catalogo() -> dict:
    if not ARCHIVO.exists():
        return {"disponible": False, "web": [], "db": [], "leido_utc": "",
                "fuente": "https://render.com/pricing"}
    d = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    return {
        "disponible": True,
        "fuente": d.get("fuente", ""),
        "leido_utc": d.get("leido_utc", ""),
        "web": [_decorar(p, "web") for p in d.get("web", [])],
        "db": [_decorar(p, "db") for p in d.get("db", [])],
    }


def buscar(tipo: str, plan_id: str):
    """El plan por su identificador de Render, o None. Sirve además como
    validación: un identificador que no está en el catálogo no se manda a la
    API, así no hay forma de que la pantalla pida un plan inexistente."""
    for p in catalogo().get(tipo, []):
        if p["id"] == plan_id:
            return p
    return None


def workers_para(plan_id: str) -> int:
    """Cuántos `--workers` de uvicorn corresponden a un plan web: uno por
    núcleo entero, mínimo 1.

    No es una preferencia: los tests 2 y 4 lo midieron. Sumar workers sin
    CPU empeora los tiempos (el test 2 quedó peor que la línea base con el
    doble de workers sobre media vCPU) y sumar CPU sin workers deja los
    núcleos nuevos sin usar. Por eso la pantalla ofrece ajustarlos junto con
    el plan en vez de dejar la combinación librada al olvido -- que ya pasó
    dos veces durante las pruebas."""
    p = buscar("web", plan_id)
    if not p:
        return 1
    return max(1, int(p["vcpu"]))
