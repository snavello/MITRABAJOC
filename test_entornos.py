"""Landing interna de entornos (GET /entornos) y la versión pública de cada
servicio (GET /api/version): los 8 accesos (4 logins x Pruebas/Demo) con su
versión, visible solo en local/pruebas (mismo criterio que el distintivo de
entorno.py), nunca en la demo.

Correr con: .venv/Scripts/python.exe test_entornos.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar

import entorno
import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)

LOGINS = ("/ingresar", "/admin", "/ingresar-empresa", "/plataforma")


def test_landing_con_los_ocho_accesos():
    r = client.get("/entornos")
    assert r.status_code == 200
    for base in entorno.URLS.values():
        for ruta in LOGINS:
            assert f'href="{base}{ruta}"' in r.text, (base, ruta)
    # Los dos entornos se anuncian con su nombre y su host, y nada de esto
    # tiene que terminar indexado por un buscador.
    assert "mitrabajo-pruebas.onrender.com" in r.text
    assert "mitrabajo.onrender.com" in r.text
    assert 'name="robots" content="noindex' in r.text
    assert 'id="distintivo-entorno"' in r.text      # es una página más de Pruebas
    print("OK  test_landing_con_los_ocho_accesos")


def test_landing_prellena_la_version_del_propio_entorno():
    # Servida desde Pruebas, las versiones de Pruebas salen en el HTML (sin
    # esperar al JS); las de la demo quedan para que el JS las pida.
    r = client.get("/entornos")
    assert f'data-version="pruebas:trabajador">v{main.VERSION_TRABAJADOR}<' in r.text
    assert f'data-version="pruebas:admin">v{main.VERSION_ADMIN}<' in r.text
    assert f'data-version="pruebas:plataforma">v{main.VERSION_PLATAFORMA}<' in r.text
    assert 'data-version="demo:trabajador">…<' in r.text
    # Empresa no tiene versión propia en version.py: se dice, no se inventa.
    assert 'data-version="pruebas:empresa"' in r.text and "sin versión propia" in r.text
    print("OK  test_landing_prellena_la_version_del_propio_entorno")


def test_api_version_es_publica_y_con_cors():
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"   # la lee el otro origen
    assert "no-store" in r.headers["cache-control"]
    v = r.json()
    assert v["entorno"] == "pruebas"
    assert v["trabajador"] == main.VERSION_TRABAJADOR
    assert v["admin"] == main.VERSION_ADMIN
    assert v["plataforma"] == main.VERSION_PLATAFORMA
    assert v["fecha"] == main.FECHA_VERSION
    print("OK  test_api_version_es_publica_y_con_cors")


def test_en_la_demo_la_landing_no_existe_pero_la_version_si(monkeypatch):
    # Mismo criterio que el distintivo: donde no se muestra, no hay landing.
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    assert client.get("/entornos").status_code == 404
    r = client.get("/api/version")               # esta sí: la landing de Pruebas la necesita
    assert r.status_code == 200 and r.json()["entorno"] == "demo"
    print("OK  test_en_la_demo_la_landing_no_existe_pero_la_version_si")


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
