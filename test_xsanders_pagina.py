"""La solapa Seguridad (XSANDERS) de /entornos: la ruta que sirve el tablero
de XSK (GET /api/entornos/xsanders). Mismo gate que la landing (PIN o sesión
de plataforma) y, como toda /entornos, 404 en la demo. Lee el registro real
de xsk/proyectos/mitrabajo/.

Correr con: .venv/Scripts/python.exe -m pytest test_xsanders_pagina.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "24681357"

import entorno
import recursos
import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False).status_code == 303


def test_sin_pin_la_solapa_no_da_datos():
    c = TestClient(main.app)  # sin pase
    r = c.get("/api/entornos/xsanders")
    assert r.status_code == 403
    print("OK  test_sin_pin_la_solapa_no_da_datos")


def test_con_pase_devuelve_el_tablero():
    r = client.get("/api/entornos/xsanders")
    assert r.status_code == 200
    d = r.json()
    # Estructura que la página espera.
    for clave in ("avance", "resumen", "ranking", "bloquean", "catalogo_por_eje",
                  "ejes", "puede_salir", "hallazgos", "por_resolucion"):
        assert clave in d, f"falta {clave}"
    # El tri-estado de resolución cubre a todos los hallazgos.
    assert sum(d["por_resolucion"].values()) == len(d["hallazgos"])
    assert set(d["por_resolucion"]) == {"solucionado", "parcial", "pendiente", "aceptado"}
    for h in d["hallazgos"]:
        assert h["resolucion"] in ("solucionado", "parcial", "pendiente", "aceptado")
    assert len(d["avance"]["etapas"]) == 10
    assert set(d["ejes"]) == set(main.xsk_tablero.registro.EJES)
    # El catálogo real tiene tests en los nueve ejes.
    assert all(eje in d["catalogo_por_eje"] for eje in d["ejes"])
    assert isinstance(d["puede_salir"], bool)
    print("OK  test_con_pase_devuelve_el_tablero")


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    r = client.get("/api/entornos/xsanders")
    assert r.status_code == 404
    print("OK  test_en_la_demo_no_existe")


def test_la_pagina_incluye_la_solapa():
    r = client.get("/entornos")
    assert r.status_code == 200
    assert 'data-tab="xsanders"' in r.text
    assert 'data-panel="xsanders"' in r.text
    print("OK  test_la_pagina_incluye_la_solapa")
