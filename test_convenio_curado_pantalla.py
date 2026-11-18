"""Curar las preguntas del convenio, la pantalla (PLAN_CONVENIO_ESCALAS.md D41):
la página de /entornos → Herramientas para leer, corregir y dar por revisadas las
preguntas frecuentes. La API que la alimenta se prueba en test_convenio_curado.py.

Correr con: python -m pytest test_convenio_curado_pantalla.py -q
"""
import os
import re

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient

import auth
import db
import entorno
import main

db.crear_tablas()
PAGINA = "/entornos/herramientas/convenio-escalas/preguntas"
JS = "static/escalas_preguntas.js"
CSS = "static/escalas_preguntas.css"


def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def test_sin_pase_no_entra():
    c = TestClient(main.app)
    r = c.get(PAGINA, headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")


def test_con_el_pin_entra():
    c = TestClient(main.app)
    assert c.post("/entornos/pin", data={"pin": "13572468"}, follow_redirects=False).status_code == 303
    assert c.get(PAGINA).status_code == 200


def test_en_demo_es_404(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = _con_plataforma()
    assert c.get(PAGINA).status_code == 404


def test_la_pagina_carga_sus_archivos_con_sello():
    html = _con_plataforma().get(PAGINA).text
    for archivo in ("escalas_preguntas.js", "escalas_preguntas.css", "escalas_estado.css", "movimiento.css"):
        assert re.search(r"/static/" + re.escape(archivo) + r"\?v=[^\"']+", html), archivo
    assert "{{" not in html and "{%" not in html


def test_la_pagina_tiene_las_frases_clave():
    html = _con_plataforma().get(PAGINA).text
    for frase in ("Curar las preguntas", "+ Nueva pregunta", "Volver a la lista", 'id="pastillas"', 'id="f-buscar"',
                  'id="f-tema"', 'id="editor"', 'id="acciones"'):
        assert frase in html, frase
    js = _leer(JS)
    for frase in ("Sin revisar", "Revisadas", "Retiradas", "Así lo ve el afiliado", "Guardar cambios",
                  "Guardar y marcar revisada", "Volver a sin revisar", "Retirar", "Publicar", "Volver a esta versión",
                  "Tiene una duda para resolver", "Hay una duda para resolver", "Marcar como revisada quiere decir",
                  "no tenía una respuesta concreta", "el dato no estaba confirmado", "Tenés cambios sin guardar",
                  "Respuesta directa", "Qué dice el convenio", "Según la ley", "En tu banco", "Nota para quien cura",
                  "Quién cambió qué", "ese nombre corto", "retiradas no se muestran"):
        assert frase in js, frase
    # los topes del servidor y las rutas del curado
    for tope in (1500, 4000, 2000, 300):
        assert str(tope) in js
    for ruta in ("/curado", "/articulos", "/reordenar", "/convenio/articulo/"):
        assert ruta in js, ruta


def test_la_vista_del_afiliado_abre_con_la_respuesta_directa():
    js = _leer(JS)
    vista = js[js.index("function pintarVista"):js.index("// ---------------------------------------------------------------- acciones")]
    assert vista.index("en_corto") < vista.index("Qué dice el convenio") < vista.index("Según la ley") < vista.index("En tu banco")


def test_nada_se_arma_como_html():
    js = _leer(JS)
    for peligro in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert peligro not in js, peligro
    assert "textContent" in js


def test_el_editor_ocupa_toda_la_pantalla_en_el_telefono():
    css = _leer(CSS)
    assert "max-width: 979px" in css and "position: fixed; inset: 0" in css


def test_el_boton_esta_en_la_tarjeta_de_la_herramienta():
    c = _con_plataforma()
    c.get("/entornos")
    html = c.get("/entornos").text
    assert 'href="/entornos/herramientas/convenio-escalas/preguntas"' in html and "Curar las preguntas" in html
    # ... al lado de «Estado de las grillas»
    assert html.index("convenio-escalas/estado") < html.index("convenio-escalas/preguntas")


def test_las_tres_paginas_se_enlazan_entre_si():
    c = _con_plataforma()
    for pagina in (PAGINA, PAGINA.replace("/preguntas", "/estado"), PAGINA.replace("/preguntas", "")):
        html = c.get(pagina).text
        assert "convenio-escalas/preguntas" in html and "convenio-escalas/estado" in html, pagina
    assert 'href="/entornos/herramientas/convenio-escalas"' in c.get(PAGINA).text
