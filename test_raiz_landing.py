"""La raíz es una landing con las tres entradas, no la pantalla de subir
recibos; y las rutas que mandan un documento a la IA exigen sesión.

Contexto (2026-09-26): `/` servía trabajador.html sin sesión, así que quien
entraba a la URL caía en "subí tu recibo" salteándose el login, y /api/leer
le leía el archivo con la IA (créditos pagos) sin saber quién era.

Correr con: .venv/Scripts/python.exe -m pytest test_raiz_landing.py -q
"""

import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()
anonimo = TestClient(main.app, raise_server_exceptions=False)


def test_raiz_es_la_landing_con_las_tres_entradas():
    r = anonimo.get("/")
    assert r.status_code == 200
    for destino in ('href="/ingresar"', 'href="/admin"', 'href="/ingresar-empresa"'):
        assert destino in r.text, destino
    # Nada de la app del trabajador: ni el formulario de subida ni su API.
    assert "/api/leer" not in r.text
    assert "/api/validar" not in r.text


def test_leer_sin_sesion_no_llama_a_la_ia():
    llamadas = []
    original = main.extraer
    main.extraer = lambda *a, **k: llamadas.append(1)
    try:
        r = anonimo.post("/api/leer", files={"archivo": ("r.png", b"x", "image/png")})
    finally:
        main.extraer = original
    assert r.status_code == 400, r.status_code
    assert r.json()["codigo"] == "E-SESION-02"
    assert not llamadas


def test_aportes_sin_sesion_no_llama_a_la_ia():
    llamadas = []
    original = main.extraer_aportes
    main.extraer_aportes = lambda *a, **k: llamadas.append(1)
    try:
        r = anonimo.post("/api/aportes", files={"archivo": ("a.png", b"x", "image/png")})
    finally:
        main.extraer_aportes = original
    assert r.status_code == 400, r.status_code
    assert r.json()["codigo"] == "E-SESION-02"
    assert not llamadas
