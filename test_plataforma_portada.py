"""Portada de /plataforma con tarjetas (GET /plataforma/inicio), mismo
patrón que la de /admin: login redirige ahí, 7 tarjetas (Sindicatos agrupa
alta/nuevo admin), colores/portada_clara propios de la marca de plataforma
(ConfiguracionPlataforma, independiente de cualquier sindicato).

Correr con: .venv/Scripts/python.exe -m pytest test_plataforma_portada.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()

plataforma_client = TestClient(main.app)
plataforma_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def test_sin_sesion_sirve_login():
    c = TestClient(main.app)
    r = c.get("/plataforma/inicio")
    assert r.status_code == 200
    assert "clave" in r.text.lower()
    assert 'href="/plataforma#lista"' not in r.text
    print("OK  test_sin_sesion_sirve_login")


def test_login_exitoso_redirige_a_inicio():
    c = TestClient(main.app)
    r = c.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/plataforma/inicio"
    print("OK  test_login_exitoso_redirige_a_inicio")


def test_muestra_las_7_tarjetas():
    r = plataforma_client.get("/plataforma/inicio")
    assert r.status_code == 200
    for panel in ("lista", "clave", "marca", "config", "usoia", "sospechosos", "topes"):
        assert f'href="/plataforma#{panel}"' in r.text, panel
    # "Nuevo sindicato" y "Nuevo administrador" quedan agrupados en la
    # tarjeta de Sindicatos -- no tienen tarjeta propia.
    assert 'href="/plataforma#nuevo"' not in r.text
    assert 'href="/plataforma#admin"' not in r.text
    print("OK  test_muestra_las_7_tarjetas")


def test_marca_plataforma_expone_portada_clara_default_falso():
    marca = db.marca_plataforma()
    assert marca["portada_clara"] is False
    print("OK  test_marca_plataforma_expone_portada_clara_default_falso")


def test_marca_plataforma_guarda_portada_clara():
    r = plataforma_client.post("/plataforma/marca", data={
        "color_primario": "#152238", "color_secundario": "#1a7a6b",
        "color_acento": "#b23a2e", "portada_clara": "true",
    }, follow_redirects=False)
    assert r.status_code == 303
    marca = db.marca_plataforma()
    assert marca["portada_clara"] is True

    # Sin tildar en un guardado posterior vuelve a False.
    r = plataforma_client.post("/plataforma/marca", data={
        "color_primario": "#152238", "color_secundario": "#1a7a6b",
        "color_acento": "#b23a2e",
    }, follow_redirects=False)
    assert r.status_code == 303
    marca = db.marca_plataforma()
    assert marca["portada_clara"] is False
    print("OK  test_marca_plataforma_guarda_portada_clara")


if __name__ == "__main__":
    test_sin_sesion_sirve_login()
    test_login_exitoso_redirige_a_inicio()
    test_muestra_las_7_tarjetas()
    test_marca_plataforma_expone_portada_clara_default_falso()
    test_marca_plataforma_guarda_portada_clara()
    print("\nTodos los tests de plataforma_portada pasaron.")
