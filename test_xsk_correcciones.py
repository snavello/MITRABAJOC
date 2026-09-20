"""Regresión de las correcciones de XSK (bloque 4). Un test por hallazgo
corregido: si alguien revierte el arreglo, este archivo lo caza.

Correr con: .venv/Scripts/python.exe -m pytest test_xsk_correcciones.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # COOKIE_SECURE = True en este entorno
os.environ.setdefault("PIN_ENTORNOS", "24681357")

import importlib
import pytest


# ---- H-0001 / H-0002: secretos fail-closed (auth._requerido) ----

def test_h0001_h0002_secretos_fallan_cerrado(monkeypatch):
    import auth
    # Sin la variable y sin default: RuntimeError con el nombre adentro.
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        auth._requerido("SESSION_SECRET", "ayuda")
    monkeypatch.delenv("PLATAFORMA_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="PLATAFORMA_PASSWORD"):
        auth._requerido("PLATAFORMA_PASSWORD", "ayuda")
    # Con valor, lo devuelve tal cual (recortado).
    monkeypatch.setenv("SESSION_SECRET", "  un-secreto-largo  ")
    assert auth._requerido("SESSION_SECRET", "ayuda") == "un-secreto-largo"


def test_h0001_no_queda_el_default_viejo_en_el_codigo():
    import auth
    fuente = open(auth.__file__, encoding="utf-8").read()
    assert "cambiar-este-secreto-en-produccion" not in fuente
    assert "plataforma-demo-2026" not in fuente


# ---- H-0006: cookies con Secure + SameSite ----

def test_h0006_set_cookie_segura_pone_httponly_y_samesite():
    import main
    from starlette.responses import Response
    r = Response()
    main.set_cookie_segura(r, "sesion_trabajador", "tok")
    sc = [v.decode() for k, v in r.raw_headers if k == b"set-cookie"][0]
    assert "HttpOnly" in sc
    assert "samesite=lax" in sc.lower()
    # En 'pruebas' (este test) Secure va apagado a proposito (TestClient habla
    # HTTP). El flag Secure se decide por entorno: solo demo/prod.
    assert main.COOKIE_SECURE is False


def test_h0006_secure_se_activa_en_demo_y_prod():
    # El helper mira main.COOKIE_SECURE; con el flag en True, la cookie sale Secure.
    import main
    from starlette.responses import Response
    orig = main.COOKIE_SECURE
    try:
        main.COOKIE_SECURE = True   # simula demo/prod
        r = Response()
        main.set_cookie_segura(r, "sesion_trabajador", "tok")
        sc = [v.decode() for k, v in r.raw_headers if k == b"set-cookie"][0]
        assert "Secure" in sc
    finally:
        main.COOKIE_SECURE = orig


def test_h0006_no_quedan_set_cookie_crudos_de_sesion():
    import main
    fuente = open(main.__file__, encoding="utf-8").read()
    # El unico set_cookie( a pelo permitido es el del propio helper.
    crudos = [l for l in fuente.splitlines()
              if ".set_cookie(" in l and "set_cookie_segura" not in l]
    assert len(crudos) == 1, f"set_cookie crudos inesperados: {crudos}"


# ---- H-0008: límite de intentos de login ----

def test_h0008_login_se_bloquea_tras_los_fallos(monkeypatch):
    import main

    class FakeReq:
        def __init__(self, ip):
            self.headers = {"x-forwarded-for": ip}
            self.client = None
    req = FakeReq("203.0.113.9")
    main._intentos_login.clear()
    assert main._login_bloqueado(req) is False
    for _ in range(main.LOGIN_MAX_FALLOS):
        main._login_fallo(req)
    assert main._login_bloqueado(req) is True
    # Un login exitoso limpia el contador de esa IP.
    main._login_ok(req)
    assert main._login_bloqueado(req) is False


def test_h0008_los_cuatro_logins_chequean_el_limite():
    import main
    fuente = open(main.__file__, encoding="utf-8").read()
    # Cada login tiene que llamar al chequeo.
    assert fuente.count("_login_bloqueado(request)") >= 4


# ---- H-0004: la identidad sale de la sesión firmada, no de la cookie plana ----

def test_h0004_la_identidad_va_en_el_token_firmado():
    import auth
    tok = auth.crear_sesion("trabajador", id_usuario=7, sindicato_id=0, ident="20111111119")
    payload = auth.leer_sesion(tok)
    assert payload["ident"] == "20111111119"


def test_h0004_cuil_seguro_lee_la_sesion_no_la_cookie():
    """El corazón del fix: forjar cuil_trab NO cambia la identidad; manda la
    sesión firmada. Sin sesión válida, no hay identidad."""
    import main, auth

    class Req:
        def __init__(self, cookies):
            self.cookies = cookies
    # Sesión firmada de A + cookie plana forjada con el CUIL de B.
    ses_a = auth.crear_sesion("trabajador", id_usuario=1, sindicato_id=0, ident="20111111119")
    req = Req({main.COOKIE_TRABAJADOR: ses_a, "cuil_trab": "27999999999"})
    assert main._cuil_seguro(req) == "20111111119"   # gana la sesión, no la cookie forjada
    # Sin sesión, solo la cookie plana forjada -> sin identidad.
    req2 = Req({"cuil_trab": "27999999999"})
    assert main._cuil_seguro(req2) == ""


def test_h0004_no_quedan_lecturas_crudas_de_identidad():
    import main
    fuente = open(main.__file__, encoding="utf-8").read()
    # Ninguna ruta debe volver a leer la identidad de la cookie plana.
    assert 'cookies.get("cuil_trab", "")' not in fuente
    assert 'cookies.get("cuit_emp", "")' not in fuente
