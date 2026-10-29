"""La pantalla "Biblioteca de fotos" del panel de plataforma (PLAN_TEMAS.md, D5).

Las rutas JSON se prueban en test_fotos_tema.py; acá se cuida la pantalla que
las usa: que la pestaña exista con los dos modelos, la zona de subida, la
lista de sindicatos para elegir, y que su JS no arme HTML con lo que devuelve
la API (una descripción la escribe una persona: con innerHTML sería un XSS).

Correr con: python -m pytest test_biblioteca_fotos_pantalla.py -q
"""
import os
import re
from pathlib import Path

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from fastapi.testclient import TestClient

import auth
import db
import main

db.crear_tablas()

with db.get_session() as s:
    a = db.Sindicato(nombre="Biblioteca <A>", slug="biblioteca-a", color_base="#0f2240")
    b = db.Sindicato(nombre="Biblioteca B", slug="biblioteca-b", color_base="#2a0d12")
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id

PLANTILLA = Path("templates/plataforma.html").read_text(encoding="utf-8")


def _plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"],
                  auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def _bloque_js() -> str:
    """El JS de la biblioteca, entre sus dos marcas."""
    m = re.search(r"/\* -+ Biblioteca de fotos de los modelos.*?/\* -+ fin de la Biblioteca de fotos -+ \*/",
                  PLANTILLA, re.S)
    assert m, "no se encontró el bloque de JS de la biblioteca de fotos"
    return m.group(0)


def test_la_pagina_trae_la_pestana_con_los_dos_modelos():
    html = _plataforma().get("/plataforma").text
    assert 'data-pp="fotos"' in html and 'id="pp-fotos"' in html
    assert "Biblioteca de fotos" in html
    assert 'data-ft-tema="laguna"' in html and "Laguna (por defecto)" in html
    assert 'data-ft-tema="noticiero"' in html and ">Noticiero<" in html
    # la pestaña se arma como las demás (test_modales lo exige a todas)
    assert re.search(r'<div class="ppanel" data-mov-vista id="pp-fotos">', html)


def test_la_zona_de_subida_y_su_ayuda():
    html = _plataforma().get("/plataforma").text
    assert 'id="ft-zona"' in html and 'type="file" id="ft-archivo"' in html
    assert "image/jpeg,image/png,image/webp" in html
    assert "hasta 8 MB" in html and "600 px" in html
    # Desde 2026-10-29 se guardan las dos versiones y la ayuda lo dice.
    assert "normalizada</b>" in html and "original en color</b>" in html
    assert "cuánto color mostrar" in html
    # la fila Original → Normalizada
    assert 'id="ft-original"' in html and 'id="ft-normalizada"' in html
    # el editor deja ver la versión en color y reponer el archivo de las viejas
    assert 'id="ft-ver-color"' in html and 'id="ft-archivo-reponer"' in html and 'id="ft-sin-color"' in html


def test_los_sindicatos_para_elegir_vienen_escapados():
    html = _plataforma().get("/plataforma").text
    assert f'class="ft-sind" value="{SID_A}"' in html
    assert f'class="ft-sind" value="{SID_B}"' in html
    assert "Biblioteca &lt;A&gt;" in html and "Biblioteca <A>" not in html
    assert "Todos los sindicatos" in html and "Los que elija" in html


def test_el_js_no_arma_html_con_datos_de_la_api():
    js = _bloque_js()
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "escHTML"):
        assert prohibido not in js, prohibido
    assert "textContent" in js


def test_la_seleccion_no_es_una_barra_lateral():
    """D6: lo elegido se pinta con relleno, nunca con un borde de un solo lado."""
    css = re.search(r"Biblioteca de fotos de los modelos \(PLAN_TEMAS.md, D5\) =+(.*?)</style>",
                    PLANTILLA, re.S).group(1)
    assert not re.search(r"border-(left|right)\s*:", css)
    assert ".ft-foto.elegida { background:" in css


def test_destildar_todos_los_sindicatos_se_guarda():
    """El JS manda siempre `sindicatos=""` además de los tildados: sin el campo
    el servidor no toca la lista, y dejarla vacía no se guardaría nunca."""
    assert "fd.append('sindicatos', '');" in _bloque_js()
    with db.get_session() as s:
        f = db.FotoTema(tema="laguna", datos=b"x", mime="image/webp", ancho=800, alto=600,
                        todos_los_sindicatos=False, sindicatos=[SID_A])
        s.add(f); s.commit(); s.refresh(f)
        fid = f.id
    c = _plataforma()
    r = c.post(f"/plataforma/fotos-tema/{fid}", data={"sindicatos": ["", str(SID_B)]})
    assert r.status_code == 200, r.text
    assert db.foto_tema(fid).sindicatos == [SID_B]
    r = c.post(f"/plataforma/fotos-tema/{fid}", data={"sindicatos": [""]})
    assert r.status_code == 200, r.text
    assert db.foto_tema(fid).sindicatos == []
