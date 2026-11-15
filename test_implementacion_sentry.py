"""La Mesa de implementación con Sentry prendido DESDE EL ARRANQUE, como en Pruebas.

El 2026-11-15 crear una tarjeta en Pruebas se quedaba en «Creando…» para
siempre. Con `SENTRY_DSN` puesto, main.py prende Sentry antes de crear la app
y sus rutas quedan envueltas: la integración leía el cuerpo del pedido antes
que la ruta, y `_impl_formulario` armaba un `Request` nuevo que esperaba un
cuerpo que ya no iba a llegar. En local y en el CI no hay DSN, así que ningún
test lo veía. Por eso este test corre los de la API en OTRO proceso, con el
DSN puesto antes de importar main, y con un tope de tiempo: si se cuelga, falla.

Correr con: .venv/bin/python -m pytest test_implementacion_sentry.py -q
"""
import os
import subprocess
import sys

import sentry_sdk

import sentry_config as sc

DSN = "https://clavepublica@o1.ingest.us.sentry.io/1"       # no se usa la red: solo viaja si hay un error


def test_la_mesa_no_se_cuelga_con_sentry_prendido_desde_el_arranque():
    entorno = dict(os.environ, SENTRY_DSN=DSN)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "test_implementacion_api.py", "-q", "-x",
             "-k", "crear or responder or archivo", "-p", "no:cacheprovider"],
            env=entorno, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        raise AssertionError("con Sentry prendido la Mesa quedó esperando el cuerpo del pedido")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]
    assert " passed" in r.stdout


def test_sentry_ni_lee_el_cuerpo_de_los_pedidos():
    """Regla del proyecto: los cuerpos no viajan a Sentry. Con `never` tampoco los lee."""
    try:
        assert sc.iniciar(DSN, "pruebas", release="abc1234")
        assert sentry_sdk.get_client().options["max_request_body_size"] == "never"
    finally:
        sentry_sdk.init(dsn="")
