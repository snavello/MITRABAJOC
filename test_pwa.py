"""Instalabilidad de la app del trabajador (PWA): manifest.json + service
worker servido desde la raiz con el header Service-Worker-Allowed (sin eso,
el navegador rechaza el scope /app porque el archivo vive bajo /static/).

Correr con: .venv/Scripts/python.exe -m pytest test_pwa.py -q
"""
import json


import db
db.crear_tablas()
import main
from fastapi.testclient import TestClient

c = TestClient(main.app)


def test_sw_servido_desde_la_raiz_con_scope_permitido():
    r = c.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["service-worker-allowed"] == "/app"
    assert "javascript" in r.headers["content-type"]
    print("OK  test_sw_servido_desde_la_raiz_con_scope_permitido")


def test_manifest_valido_con_iconos():
    r = c.get("/static/manifest.json")
    assert r.status_code == 200
    data = json.loads(r.text)
    assert data["scope"] == "/app"
    assert data["start_url"] == "/app/inicio"
    assert len(data["icons"]) == 3
    print("OK  test_manifest_valido_con_iconos")


def test_iconos_referenciados_existen():
    r = c.get("/static/manifest.json")
    data = json.loads(r.text)
    for icono in data["icons"]:
        r2 = c.get(icono["src"])
        assert r2.status_code == 200, icono["src"]
    print("OK  test_iconos_referenciados_existen")


if __name__ == "__main__":
    test_sw_servido_desde_la_raiz_con_scope_permitido()
    test_manifest_valido_con_iconos()
    test_iconos_referenciados_existen()
    print("\nTodo OK — PWA.")
