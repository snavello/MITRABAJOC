"""Calculadora bancaria v2 (Herramientas de /entornos): la misma herramienta
con la interfaz en Preact y el movimiento de la plataforma. Convive con la
v1 hasta que SDN decida, con un enlace de ida y vuelta.

Lo que se prueba acá es lo que no puede romperse sin que se note tarde:
misma puerta que la v1, todo import pasa por el importmap (con su sello
?v=), nada arma HTML como texto, la v2 no define duraciones propias y usa
las mismas rutas de la API que la v1 (no hay cálculo nuevo).

Correr con: python -m pytest test_calculadora_bancaria_v2.py -q
"""
import json
import os
import re
from pathlib import Path

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

from fastapi.testclient import TestClient

import auth
import entorno
import main

V2 = "/entornos/herramientas/calculadora-bancaria-v2"
V1 = "/entornos/herramientas/calculadora-bancaria"
CARPETA = Path("static") / "calc_v2"
_IMPORTA = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']""")


def _sin_comentarios(js: str) -> str:
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def test_misma_puerta_que_la_v1(monkeypatch):
    r = TestClient(main.app).get(V2, headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    assert _con_plataforma().get(V2).status_code == 404


def test_abre_con_el_importmap_y_la_precarga():
    html = _con_plataforma().get(V2).text
    mapa = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    assert {"preact", "preact/hooks", "htm", "calc/app"} <= set(mapa)
    assert all("?v=" in url for url in mapa.values()), "un módulo sin sello quedaría cacheado una hora"
    precargas = set(re.findall(r'<link rel="modulepreload" href="([^"]+)">', html))
    assert precargas == set(mapa.values())
    assert html.index("movimiento.css") < html.index("calc_v2/calc.css"), "los tokens van antes que la v2"
    assert 'id="calculadora"' in html and "data-estados=" in html


def test_ida_y_vuelta_entre_versiones():
    c = _con_plataforma()
    assert f'href="{V2}"' in c.get(V1).text
    assert f'href="{V1}"' in c.get(V2).text


def test_todo_import_resuelve_por_el_importmap():
    mapa = json.loads(main._importmap_calculadora_v2())["imports"]
    archivos = list(CARPETA.glob("*.js"))
    assert archivos and {f"calc/{p.stem}" for p in archivos} <= set(mapa)
    vistos, sin_resolver = 0, []
    for archivo in archivos:
        for nombre in _IMPORTA.findall(_sin_comentarios(archivo.read_text(encoding="utf-8"))):
            vistos += 1
            if nombre not in mapa:
                sin_resolver.append(f"{archivo}: import {nombre!r}")
    assert vistos > 5, "el regex dejó de encontrar imports"
    assert not sin_resolver, "\n".join(sin_resolver)


def test_la_v2_no_arma_html_como_texto():
    prohibidos = ("innerHTML", "outerHTML", "insertAdjacentHTML", "dangerouslySetInnerHTML", "document.write")
    hallados = [f"{p.name}: {x}" for p in CARPETA.glob("*.js") for x in prohibidos
                if x in _sin_comentarios(p.read_text(encoding="utf-8"))]
    assert not hallados, hallados


def test_usa_las_mismas_rutas_que_la_v1():
    """No hay cálculo nuevo: la v2 pide a /api/entornos/herramientas/bancaria,
    las mismas rutas que la v1 (el servidor decide, la pantalla muestra)."""
    app = (CARPETA / "app.js").read_text(encoding="utf-8")
    assert 'const API = "/api/entornos/herramientas/bancaria"' in app
    for ruta in ("/opciones", "/calcular", "/leer", "/casos"):
        assert f'API + "{ruta}' in app, ruta


def test_el_movimiento_sale_de_los_tokens():
    """Las duraciones viven en static/movimiento.css: la v2 las usa, no las
    define (lo exige también test_modales.py para todo static/)."""
    css = _sin_comentarios((CARPETA / "calc.css").read_text(encoding="utf-8"))
    assert not re.findall(r"--(mov|ease)-[a-z]+\s*:", css)
    assert "var(--mov-" in css and "var(--ease-entrada)" in css
    assert "prefers-reduced-motion" in css
    # Nada aparece desde escala cero (salvo la barra, que crece de su borde).
    assert "scale: 0;" not in css and "scale(0)" not in css


def test_las_propuestas_se_distinguen_y_titilan():
    """Lo que la calculadora propone y espera una acción (la categoría, cada
    "Ajustar al recibo") va en su propio color, no en el ámbar ni el amarillo
    de lo permanente, y titila hasta que se aplica (SDN, 2026-10-14: en el
    recibo 04 no se vio que proponía Cajero y el ROE)."""
    app = (CARPETA / "app.js").read_text(encoding="utf-8")
    css = _sin_comentarios((CARPETA / "calc.css").read_text(encoding="utf-8"))
    assert app.count("data-propuesta") >= 3          # categoría, renglón y caja de la IA
    assert 'class="ajustar propuesta"' in app and "aviso-propuestas" in app
    assert re.search(r"\.ajustar \{[^}]*var\(--propuesta\)", css)
    assert "--propuesta:" in css and "@keyframes titila" in css
    quieto = css[css.index("prefers-reduced-motion"):]
    assert ".propuesta::after { animation: none" in quieto, "con menos movimiento no titila"
