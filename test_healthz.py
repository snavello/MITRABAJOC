"""Health checks (C6 del cuelgue de Pruebas del 2026-09-18,
docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md).

- /healthz: el proceso está vivo. NO toca la base: tiene que contestar 200 con
  el pool de conexiones agotado y hasta con el engine roto. Es la que Render
  usa para decidir si reinicia el servicio.
- /readyz: se puede atender ahora. SELECT 1 con techo de 2 s; 503 si la base
  no contesta a tiempo o falla.

Correr con: .venv/Scripts/python.exe -m pytest test_healthz.py -q
"""
import time

import db
import main
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

db.crear_tablas()

client = TestClient(main.app, raise_server_exceptions=False)


def test_healthz_responde_200_sin_sesion_ni_datos():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert r.headers["cache-control"] == "no-store"
    print("OK  test_healthz_responde_200_sin_sesion_ni_datos")


def test_healthz_no_toca_la_base_ni_con_el_pool_agotado():
    original = db.engine
    db.engine = create_engine(original.url, pool_size=1, max_overflow=0, pool_timeout=5)
    try:
        with db.engine.connect():                       # la única conexión, retenida
            inicio = time.monotonic()
            r = client.get("/healthz")
            duracion = time.monotonic() - inicio
        assert r.status_code == 200 and duracion < 0.5, (r.status_code, duracion)
    finally:
        db.engine.dispose()
        db.engine = original
    print(f"OK  test_healthz_no_toca_la_base_ni_con_el_pool_agotado ({duracion * 1000:.0f} ms)")


def test_healthz_responde_aunque_el_engine_este_roto():
    original = db.engine
    db.engine = create_engine("postgresql+psycopg://nadie:nada@127.0.0.1:1/inexistente")
    try:
        assert client.get("/healthz").status_code == 200
    finally:
        db.engine = original
    print("OK  test_healthz_responde_aunque_el_engine_este_roto")


def test_readyz_200_con_la_base_sana():
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["cache-control"] == "no-store"
    print("OK  test_readyz_200_con_la_base_sana")


def test_readyz_503_en_menos_de_3_s_si_el_pool_esta_agotado():
    original = db.engine
    db.engine = create_engine(original.url, pool_size=1, max_overflow=0, pool_timeout=30)
    try:
        with db.engine.connect():
            inicio = time.monotonic()
            r = client.get("/readyz")
            duracion = time.monotonic() - inicio
    finally:
        db.engine.dispose()
        db.engine = original
    assert r.status_code == 503, (r.status_code, r.text)
    assert r.json()["ok"] is False and "2 s" in r.json()["motivo"]
    assert duracion < 3, f"readyz tardó {duracion:.1f} s"
    print(f"OK  test_readyz_503_en_menos_de_3_s_si_el_pool_esta_agotado ({duracion:.1f} s)")


def test_readyz_503_si_la_base_esta_caida():
    original = db.engine
    db.engine = create_engine("postgresql+psycopg://nadie:nada@127.0.0.1:1/inexistente")
    try:
        r = client.get("/readyz")
    finally:
        db.engine = original
    assert r.status_code == 503 and r.json()["ok"] is False
    print("OK  test_readyz_503_si_la_base_esta_caida")
