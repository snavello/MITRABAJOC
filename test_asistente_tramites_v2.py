"""Asistente de trámites, la pantalla (static/asistente_tramites/, Preact sin
build; PLAN_ASISTENTE_TRAMITES.md bloque 3).

Lo que no puede romperse sin que se note tarde: todo import pasa por el
importmap con su sello ?v=, nada arma HTML como texto, la pantalla no define
duraciones propias (usa los tokens de movimiento.css), pide SOLO a las rutas
del asistente y la pestaña Herramientas la presenta.

Correr con: python -m pytest test_asistente_tramites_v2.py -q
"""
import json
import os
import re
from pathlib import Path

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

from fastapi.testclient import TestClient

import auth
import main

PAGINA = "/entornos/herramientas/asistente-tramites"
CARPETA = Path("static") / "asistente_tramites"
_IMPORTA = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']""")


def _sin_comentarios(js: str) -> str:
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def test_abre_con_el_importmap_y_la_precarga():
    html = _con_plataforma().get(PAGINA).text
    mapa = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    assert {"preact", "preact/hooks", "htm", "asistente/app", "asistente/circuito"} <= set(mapa)
    assert all("?v=" in url for url in mapa.values()), "un módulo sin sello quedaría cacheado una hora"
    precargas = set(re.findall(r'<link rel="modulepreload" href="([^"]+)">', html))
    assert precargas == set(mapa.values())
    assert html.index("movimiento.css") < html.index("asistente_tramites/asistente.css"), "los tokens van antes"
    assert 'id="asistente"' in html and "data-estados=" in html and "data-isotipo=" in html


def test_todo_import_resuelve_por_el_importmap():
    mapa = json.loads(main._importmap_asistente_tramites())["imports"]
    archivos = list(CARPETA.glob("*.js"))
    assert archivos and {f"asistente/{p.stem}" for p in archivos} <= set(mapa)
    vistos, sin_resolver = 0, []
    for archivo in archivos:
        for nombre in _IMPORTA.findall(_sin_comentarios(archivo.read_text(encoding="utf-8"))):
            vistos += 1
            if nombre not in mapa:
                sin_resolver.append(f"{archivo}: import {nombre!r}")
    assert vistos > 5, "el regex dejó de encontrar imports"
    assert not sin_resolver, "\n".join(sin_resolver)


def test_la_pantalla_no_arma_html_como_texto():
    prohibidos = ("innerHTML", "outerHTML", "insertAdjacentHTML", "dangerouslySetInnerHTML", "document.write")
    hallados = [f"{p.name}: {x}" for p in CARPETA.glob("*.js") for x in prohibidos
                if x in _sin_comentarios(p.read_text(encoding="utf-8"))]
    assert not hallados, hallados


def test_usa_solo_las_rutas_del_asistente():
    """La IA propone y el motor decide EN EL SERVIDOR: la pantalla pide a las
    rutas del asistente y a ninguna otra; no calcula circuitos ni brechas."""
    app = (CARPETA / "app.js").read_text(encoding="utf-8")
    assert 'const API = "/api/entornos/herramientas/asistente"' in app
    for ruta in ("/catalogo", "/entender", "/resolver", "/casos", "/brechas", "/importar"):
        assert f'API + "{ruta}' in app or f"API + `{ruta}" in app, ruta
    assert "preguntas-extra" not in app, "el segundo cuestionario se fue (2026-10-18)"
    otras = set(re.findall(r'fetch\(\s*"([^"]+)"', app)) - set()
    assert not otras, otras


def test_el_movimiento_sale_de_los_tokens():
    css = _sin_comentarios((CARPETA / "asistente.css").read_text(encoding="utf-8"))
    assert not re.findall(r"--(mov|ease)-[a-z]+\s*:", css), "las duraciones viven en movimiento.css"
    assert "var(--mov-" in css and "var(--ease-entrada)" in css and "var(--ease-mueve)" in css
    assert "prefers-reduced-motion" in css
    assert "scale: 0;" not in css and "scale(0)" not in css
    js = _sin_comentarios((CARPETA / "movimiento.js").read_text(encoding="utf-8"))
    assert "getPropertyValue(token)" in js


def test_lo_propuesto_por_la_ia_se_distingue():
    """Lo que la IA propuso y espera confirmación va en fucsia (`--propuesta`),
    como las propuestas de la Calculadora, nunca en el ámbar de los botones."""
    app = (CARPETA / "app.js").read_text(encoding="utf-8")
    css = _sin_comentarios((CARPETA / "asistente.css").read_text(encoding="utf-8"))
    assert 'class="marca-ia"' in app and "Propuesto" in app
    assert re.search(r"\.marca-ia \{[^}]*var\(--propuesta\)", css)


def test_la_hoja_de_trabajo_con_varios_tramites():
    """V1, V2 y V8 de PLAN_ASISTENTE_TRAMITES_V2.md: riel con «Nuevo trámite»
    y la lista de los tratados, cuatro pasos (sin el cuestionario una
    pregunta por pantalla), las dudas con opciones, el veredicto con sus seis
    puntos e importar como borrador; fondo claro."""
    app = _sin_comentarios((CARPETA / "app.js").read_text(encoding="utf-8"))
    css = _sin_comentarios((CARPETA / "asistente.css").read_text(encoding="utf-8"))
    assert "+ Nuevo trámite" in app and 'class="lista-tramites"' in app and "Trámites tratados" in app
    assert '["relato", "El relato"' in app and '["veredicto", "El veredicto"' in app
    assert "function Pregunta(" not in app and "Pregunta ${qi + 1} de" not in app, "el cuestionario una por pantalla se fue"
    assert "function Dudas(" in app and "Lo que no quedó claro" in app and 'placeholder="O contestá con tus palabras"' in app
    assert "function Veredicto(" in app and "v.puntos.map" in app and "Confirmar la importación" in app
    assert "Importar a ${sind.nombre}" in app and "ensayo" in app and "/casos/${E.caso_id}" in app
    assert "hoja-layout" in css and "ct-area" in css and "ct-der" in css
    assert "html { background: var(--mesa); }" in css and "--mesa: #eef1f5" in css
    assert "#0d1626" not in css, "la colmena nocturna se fue"


def test_la_pestana_herramientas_la_presenta():
    html = _con_plataforma().get("/entornos").text
    assert f'href="{PAGINA}"' in html and "Asistente de trámites" in html
    assert f'href="{PAGINA}#brechas"' in html


def test_los_datos_se_editan_en_tarjetas_con_todo_el_detalle():
    """2026-10-18: el paso "Los datos" dejó la tabla con cuatro cajas sueltas
    por fila. Cada dato es una tarjeta con la pregunta, tipo / control /
    opciones / obligatorio y un renglón plegado con la aclaración, la regla,
    la fórmula y la función nueva: los cuatro siguen ahí (sin perder un
    dato) y el catálogo muestra qué devuelve cada uno y un ejemplo."""
    app = _sin_comentarios((CARPETA / "app.js").read_text(encoding="utf-8"))
    css = _sin_comentarios((CARPETA / "asistente.css").read_text(encoding="utf-8"))
    assert "campo-extra" not in app and "campo-extra" not in css
    for rotulo in ("Aclaración", "Validar", "Validar con fórmula", "Función a desarrollar"):
        assert f'"{rotulo}"' in app, rotulo
    assert 'class="cp-det-cab" aria-expanded=' in app and 'class="cp-chip"' in app
    assert "function Catalogo" in app and "d.ejemplo" in app and "f.ejemplo" in app and "cat.comparar" in app
    assert 'list=${k === "formula" ? "at-nombres" : null}' in app, "la fórmula sigue sugiriendo los nombres"
    assert re.search(r"\.cp-det-cab\[aria-expanded=\"true\"\] \.cp-chev \{ rotate: 90deg; \}", css)
    assert "transition: rotate var(--mov-rapido) var(--ease-mueve)" in css
