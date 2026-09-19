"""Los techos del engine (C2 del cuelgue de Pruebas del 2026-09-18,
docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md).

Sin ellos, nada tenía límite: un request esperaba 30 s una conexión que nunca
llegaba, y una consulta lenta o una transacción abierta seguían vivas en
Postgres. Lo que se prueba acá:

- el engine de la app lleva pool_timeout, statement_timeout e
  idle_in_transaction_session_timeout, con los valores por defecto;
- el engine de las migraciones NO lleva los de la app (un ALTER largo no
  puede morir a los 15 s) y sí lleva lock_timeout;
- un pool agotado devuelve 503 con JSON en menos de 6 s, no un 500 ni un
  cuelgue;
- una consulta que se pasa del statement_timeout devuelve 503 con su propio
  código, y cualquier otro error de la base sigue siendo el 500 de siempre.

Correr con: .venv/Scripts/python.exe -m pytest test_db_timeouts.py -q
"""
import os
import time

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import fechas
import dashboard
import main
from db import Sindicato, UsuarioSindicato
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="Timeouts Dash", slug="timeouts-dash", color_base="#0f1b2d",
                     modulos_habilitados=["dashboard"])
    s.add(sind)
    s.commit()
    s.refresh(sind)
    s.add(UsuarioSindicato(sindicato_id=sind.id, usuario="20555555550", nombre="Admin T",
                           clave_hash=auth.hashear_clave("t-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

_login = TestClient(main.app)
_login.post("/admin/login", data={"usuario": "20555555550", "clave": "t-demo"})
COOKIES = dict(_login.cookies)
assert COOKIES, "el login del admin de prueba no dejó cookie"

HOY = fechas.hoy().isoformat()
PARAMS = {"desde": HOY, "hasta": HOY}
RUTA = "/admin/dashboard/validacion"


def _cliente():
    return TestClient(main.app, cookies=COOKIES, raise_server_exceptions=False)


def _show(conexion, parametro):
    return conexion.execute(text(f"SHOW {parametro}")).scalar()


def test_el_engine_de_la_app_lleva_los_techos():
    with db.engine.connect() as c:
        assert _show(c, "statement_timeout") == "15s"
        assert _show(c, "idle_in_transaction_session_timeout") == "30s"
    assert db.engine.pool.timeout() == 5
    assert db.engine.pool.size() == 5
    print("OK  test_el_engine_de_la_app_lleva_los_techos")


def test_el_engine_de_migraciones_no_lleva_los_techos_de_la_app():
    motor = db.engine_para_migraciones()
    try:
        with motor.connect() as c:
            assert _show(c, "statement_timeout") == "0"
            assert _show(c, "idle_in_transaction_session_timeout") == "0"
            assert _show(c, "lock_timeout") == "5s"
    finally:
        motor.dispose()
    print("OK  test_el_engine_de_migraciones_no_lleva_los_techos_de_la_app")


def test_pool_agotado_devuelve_503_rapido():
    original = db.engine
    db.engine = create_engine(original.url, pool_size=1, max_overflow=0,
                              pool_timeout=db.POOL_TIMEOUT)
    try:
        with db.engine.connect():            # la única conexión del pool, retenida
            inicio = time.monotonic()
            r = _cliente().get(RUTA, params=PARAMS)
            duracion = time.monotonic() - inicio
    finally:
        db.engine.dispose()
        db.engine = original
    assert r.status_code == 503, (r.status_code, r.text[:200])
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["codigo"] == "E-SERVIDOR-01" and r.json()["detail"]
    assert r.headers.get("retry-after") == str(db.POOL_TIMEOUT)
    assert duracion < 6, f"tardó {duracion:.1f} s en rendirse"
    print(f"OK  test_pool_agotado_devuelve_503_rapido ({duracion:.1f} s)")


def test_consulta_que_pasa_el_statement_timeout_devuelve_503():
    original_engine, original_fn = db.engine, dashboard.validacion
    db.engine = create_engine(original_engine.url,
                              connect_args={"options": "-c statement_timeout=200"})

    def _lenta(sid, f):
        with db.get_session() as s:
            s.execute(text("SELECT pg_sleep(3)"))

    dashboard.validacion = _lenta
    try:
        inicio = time.monotonic()
        r = _cliente().get(RUTA, params=PARAMS)
        duracion = time.monotonic() - inicio
    finally:
        dashboard.validacion = original_fn
        db.engine.dispose()
        db.engine = original_engine
    assert r.status_code == 503, (r.status_code, r.text[:200])
    assert r.json()["codigo"] == "E-SERVIDOR-02"
    assert duracion < 2.5, f"la consulta no se cortó: {duracion:.1f} s"
    print(f"OK  test_consulta_que_pasa_el_statement_timeout_devuelve_503 ({duracion:.1f} s)")


def test_otro_error_de_la_base_sigue_siendo_500_con_ref():
    """Solo la consulta cortada por tiempo es un 503. Un error operacional
    cualquiera (conexión caída, por ejemplo) sigue por la red de seguridad."""
    original_fn = dashboard.validacion

    def _rota(sid, f):
        raise OperationalError("SELECT 1", {}, Exception("conexión caída"))

    dashboard.validacion = _rota
    try:
        r = _cliente().get(RUTA, params=PARAMS)
    finally:
        dashboard.validacion = original_fn
    assert r.status_code == 500, (r.status_code, r.text[:200])
    assert r.json()["codigo"] == "E-INTERNO-00" and r.json().get("ref")
    print("OK  test_otro_error_de_la_base_sigue_siendo_500_con_ref")
