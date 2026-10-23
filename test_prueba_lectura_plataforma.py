"""La prueba de lectura de los colores del sindicato en la ficha de plataforma
(PLAN_TEMAS.md, D4). La calcula el servidor con temas.prueba_de_lectura, la
misma que ve el Super Admin en Apariencia; la pantalla solo la muestra.

Correr con: python -m pytest test_prueba_lectura_plataforma.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from fastapi.testclient import TestClient

import auth
import db
import main

db.crear_tablas()


def _plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"],
                  auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def test_sin_sesion_de_plataforma_es_403():
    assert TestClient(main.app).get("/plataforma/prueba-lectura?base=%23000000").status_code == 403


def test_devuelve_lo_mismo_que_temas():
    import temas
    c = _plataforma()
    colores = {"base": "#2a0d12", "primario": "#7a1f2b", "acento": "#3d6b4a", "apoyo": "#c19a3e"}
    r = c.get("/plataforma/prueba-lectura", params=colores)
    assert r.status_code == 200
    assert r.json()["avisos"] == temas.prueba_de_lectura(**colores)
    assert any(a["clave"] == "acento_sobre_base" for a in r.json()["avisos"])   # el verde oscuro de FEGA


def test_un_color_ilegible_se_avisa_y_no_rompe():
    r = _plataforma().get("/plataforma/prueba-lectura", params={"base": "verde", "primario": "#1a3d6b",
                                                                 "acento": "#e8b84b", "apoyo": "#2fa88f"})
    assert r.status_code == 200 and r.json()["avisos"][0]["clave"] == "color_base"


def test_la_ficha_trae_el_recuadro_y_no_usa_innerhtml():
    html = open("templates/plataforma.html", encoding="utf-8").read()
    assert 'id="prueba-lectura"' in html and "/plataforma/prueba-lectura" in html
    bloque = html[html.find("function probarLectura"):html.find("function probarLectura") + 2000]
    assert "innerHTML" not in bloque
