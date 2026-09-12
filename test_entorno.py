"""Distintivo de entorno (entorno.py + templates/_entorno.html): se muestra
en local/pruebas, NUNCA en demo/prod ni sin la variable, y el "Acerca de"
lleva el entorno junto a la versión.

Correr con: .venv/Scripts/python.exe -m pytest test_entorno.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar

import entorno
import db
import auth
import main
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)


def test_normalizacion_y_regla_de_distintivo():
    assert entorno.normalizar(" Pruebas ") == "pruebas"
    assert entorno.normalizar(None) == ""
    assert entorno.normalizar("produccion") == ""      # desconocido = nada
    assert entorno.muestra_distintivo("local")
    assert entorno.muestra_distintivo("pruebas")
    assert not entorno.muestra_distintivo("demo")
    assert not entorno.muestra_distintivo("prod")
    assert not entorno.muestra_distintivo("")           # sin variable = nada
    assert not entorno.muestra_distintivo("PRUEBAS-typo")


def test_distintivo_en_los_logins_de_las_cuatro_apps():
    # Pruebas -> el distintivo aparece en toda página, logins incluidos.
    for ruta in ("/ingresar", "/admin", "/plataforma", "/ingresar-empresa"):
        r = client.get(ruta)
        assert r.status_code == 200, ruta
        assert 'id="distintivo-entorno"' in r.text, ruta
        assert ">pruebas<" in r.text or ">pruebas ·" in r.text or "pruebas" in r.text, ruta


def test_acerca_de_muestra_entorno_y_version():
    # Portada de plataforma: sesión de plataforma firmada como hace el login.
    client.cookies.set("sesion_plataforma", auth.crear_sesion("plataforma"))
    r = client.get("/plataforma/inicio")
    assert r.status_code == 200
    assert "Entorno" in r.text and "pruebas" in r.text
    assert f"v{main.VERSION_PLATAFORMA}" in r.text   # el distintivo lleva la versión de la app


def test_seed_aefip_ya_no_se_siembra_solo():
    # init_db sobre una base vacía no crea el sindicato fantasma con id=1.
    db.init_db()
    with db.get_session() as s:
        from sqlmodel import select
        assert s.exec(select(db.Sindicato)).first() is None


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
