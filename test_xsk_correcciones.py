"""Regresión de las correcciones de XSK (bloque 4). Un test por hallazgo
corregido: si alguien revierte el arreglo, este archivo lo caza.

Correr con: .venv/Scripts/python.exe -m pytest test_xsk_correcciones.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # COOKIE_SECURE queda en False (pruebas) -> ver H-0006
os.environ.setdefault("PIN_ENTORNOS", "24681357")

import importlib
import pytest
from fastapi.testclient import TestClient


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


# ---- H-0005: el motor de fórmulas ya no usa eval (sin escape de sandbox) ----

def test_h0005_formulas_legitimas_siguen_evaluando():
    import validador
    v = {"total_ingresos": 1000.0, "base_remunerativa": 2000.0, "c": lambda cod: {"128": 50.0}.get(cod, 0.0)}
    assert validador._evaluar("base_remunerativa * 0.015", v) == 30.0
    assert validador._evaluar("total_ingresos * 0.03 + c(\"128\")", v) == 80.0
    assert validador._evaluar("(base_remunerativa - total_ingresos) / 2", v) == 500.0
    assert validador._evaluar("-total_ingresos", v) == -1000.0
    # con espacios/saltos alrededor (como quedan guardadas): deben evaluar igual
    assert validador._evaluar("  base_remunerativa * 0.015  ", v) == 30.0
    assert validador._evaluar("\n0.03*total_ingresos\n", v) == 30.0


def test_h0005_el_escape_de_sandbox_ya_no_ejecuta():
    import validador
    v = dict(validador.VARIABLES_DE_PRUEBA)
    # El clásico escape por dunders: antes con eval llegaba a las clases del
    # intérprete; ahora es una expresión no permitida (no ejecuta nada).
    for payload in (
        '().__class__.__bases__[0].__subclasses__()',
        '"".__class__',
        '__import__("os").system("echo x")',
    ):
        with pytest.raises((SyntaxError, NameError, ValueError)):
            validador._evaluar(payload, v)


def test_h0005_no_queda_eval_en_validador():
    import validador
    fuente = open(validador.__file__, encoding="utf-8").read()
    # No debe quedar ninguna llamada eval( en el motor de fórmulas.
    assert "eval(" not in fuente, "quedó un eval( en validador.py"


# ---- H-0007: cabeceras de seguridad en toda respuesta ----

def test_h0007_cabeceras_de_seguridad_presentes():
    import main
    c = TestClient(main.app)
    r = c.get("/healthz")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "strict-origin" in r.headers.get("referrer-policy", "")
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp


def test_h0007_la_csp_deja_pasar_los_blob_que_la_propia_app_fabrica():
    """La CSP de H-0007 salió sin `blob:` y eso ROMPIÓ la carga de foto de
    perfil (2026-09-22), en la app del afiliado y en la del empleador.

    Para achicar la foto antes de subirla, el navegador la carga en un
    `<img src="blob:...">` que fabrica el mismo documento con
    `URL.createObjectURL(archivo)`. Sin `blob:` en `img-src` el navegador lo
    bloquea, salta `onerror` y la pantalla dice "no se pudo leer la imagen"
    sin que el archivo haya llegado nunca al servidor -- un error que no
    aparece en ningún log porque no hubo request. Lo mismo con `media-src` y
    la vista previa de un video en Recursos.

    Un `blob:` no es una fuente externa: lo fabrica el propio documento a
    partir de un archivo que la persona eligió, así que no abre ninguna
    puerta que `data:` no tuviera ya abierta."""
    import main
    csp = TestClient(main.app).get("/healthz").headers.get("content-security-policy", "")
    for directiva in ("img-src", "media-src"):
        valores = next((d for d in csp.split("; ") if d.startswith(directiva + " ")), "")
        assert "blob:" in valores, f"{directiva} sin blob:: {csp}"


def test_h0007_hsts_solo_en_demo_prod():
    import main
    c = TestClient(main.app)
    r = c.get("/healthz")
    # En 'pruebas' (este test) COOKIE_SECURE es False -> sin HSTS.
    assert main.COOKIE_SECURE is False
    assert "strict-transport-security" not in {k.lower() for k in r.headers}


# ---- H-0009: PBKDF2 a 600.000 iteraciones, backward-compatible ----

def test_h0009_hash_nuevo_usa_600k_y_verifica():
    import auth
    h = auth.hashear_clave("secreta")
    assert h.startswith("sha256$600000$")
    assert auth.verificar_clave("secreta", h)
    assert not auth.verificar_clave("otra", h)
    assert not auth.hash_desactualizado(h)


def test_h0009_hash_legado_sigue_validando():
    import auth, hashlib
    # Formato viejo 'sal$hash' a 100.000 iteraciones.
    sal = "a" * 32
    dk = hashlib.pbkdf2_hmac("sha256", "vieja".encode(), sal.encode(), 100_000)
    legado = f"{sal}${dk.hex()}"
    assert auth.verificar_clave("vieja", legado)          # se sigue validando
    assert auth.hash_desactualizado(legado)               # pero marcado para re-hashear
