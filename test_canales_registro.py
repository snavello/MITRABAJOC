"""Los canales del registro: mail (Resend), captcha (Turnstile), la CSP que lo
permite y el freno por IP de los dos registros (PLAN_REGISTRO.md, etapa 1).

Qué verifica este archivo:

1. `correo.pista`, los textos de los mails y `correo.enviar` (apagado sin red,
   2xx -> True, error de red o 4xx/5xx -> False, nunca lanza).
2. `captcha.verificar`: apagado deja pasar; prendido FALLA CERRADO.
3. La CSP: sin captcha es la de siempre, byte por byte; con captcha suma
   `challenges.cloudflare.com` en `script-src` y un `frame-src`.
4. El freno de registro: bloquea tras N fallos, tiene su PROPIA tabla (no toca
   la de los logins) y un registro que crea la cuenta limpia la IP.
5. Los dos POST de registro con el captcha prendido: un token malo vuelve a
   `?error=captcha` y no crea la cuenta; con el captcha apagado todo anda como
   antes. El parcial `_captcha.html` y los avisos de las dos pantallas.

Todo con `urlopen` simulado: ningún test sale a la red.

Correr con: python -m pytest test_canales_registro.py -q
"""
import json
import os
import urllib.error

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import captcha
import correo
import cuit
import db
import main
from db import CuentaEmpleador, CuentaTrabajador, Empleador, Sindicato, Trabajador
from fastapi.testclient import TestClient
from modulos import MODULOS
from sqlmodel import Session, select

db.crear_tablas()

for _v in ("RESEND_API_KEY", "MAIL_REMITENTE", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
    os.environ.pop(_v, None)

CUIL_A = "20202790411"            # válidos (módulo 11)
CUIL_B = "20111111112"
CUIT_EMP = "30444640975"
CUIT_EMP_2 = "30999888778"
CUIL_FUERA = cuit.corregir("20123456780")     # válido y que NO está en ningún padrón
assert cuit.es_valido(CUIL_A, cuit.PERSONA) and cuit.es_valido(CUIL_B, cuit.PERSONA)
assert cuit.es_valido(CUIL_FUERA, cuit.PERSONA)

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Canales", slug="sindicato-canales",
                     color_base="#0f1b2d", modulos_habilitados=list(MODULOS.keys()))
    s.add(sind)
    s.commit()
    s.refresh(sind)
    SID = sind.id

DOM = {"provincia": "Santa Fe", "localidad": "Rosario"}

# La CSP que había antes de este bloque, copiada a mano: el test falla si la
# política sin captcha cambia aunque sea un byte.
CSP_DE_SIEMPRE = ("default-src 'self'; "
                  "img-src 'self' data: blob: https:; "
                  "media-src 'self' data: blob:; "
                  "style-src 'self' 'unsafe-inline'; "
                  "script-src 'self' 'unsafe-inline'; "
                  "connect-src 'self' https:; "
                  "frame-ancestors 'none'; "
                  "base-uri 'self'; "
                  "form-action 'self'")


class _Resp:
    """Lo mínimo que `urlopen` devuelve: administrador de contexto con status y body."""

    def __init__(self, status=200, cuerpo=b"{}"):
        self.status = status
        self._cuerpo = cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._cuerpo

    def getcode(self):
        return self.status


def _urlopen(monkeypatch, respuesta=None, error=None, vistos=None):
    """Reemplaza urlopen. Deja en `vistos` cada pedido recibido."""
    def falso(pedido, timeout=None):
        if vistos is not None:
            vistos.append((pedido, timeout))
        if error is not None:
            raise error
        return respuesta
    monkeypatch.setattr(correo.urllib.request, "urlopen", falso)


def _sin_red(monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("salió a la red")
    monkeypatch.setattr(correo.urllib.request, "urlopen", prohibido)


def _limpiar_frenos():
    main._intentos_login.clear()
    main._intentos_registro.clear()


def _padron(cuil):
    with db.get_session() as s:
        if not s.exec(select(Trabajador).where(Trabajador.cuil == cuil)).first():
            s.add(Trabajador(sindicato_id=SID, cuil=cuil, activo=True))
        db.guardar_datos_personales(s, cuil, nombre="Persona de Prueba")
        s.commit()


def _clave_de(cuil):
    with Session(db.engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        return c.clave_hash if c else None


def _con_captcha(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "sitekey-de-prueba")
    monkeypatch.setenv("TURNSTILE_SECRET", "secreto-de-prueba")


# =============================================================================
# 1. correo.py
# =============================================================================

def test_pista_del_mail():
    assert correo.pista("juan.perez@gmail.com") == "j***@gmail.com"
    assert correo.pista("ab@x.ar") == "a***@x.ar"
    assert correo.pista("  Maria@Dominio.com.ar ") == "M***@Dominio.com.ar"
    assert correo.pista("") == "" and correo.pista(None) == ""
    assert correo.pista("sin-arroba") == "" and correo.pista("@x.ar") == ""
    print("OK  test_pista_del_mail")


def test_textos_de_los_mails_sin_nombre_ni_enlaces():
    for armar, palabra in ((correo.texto_codigo_registro, "crear tu cuenta"),
                           (correo.texto_codigo_recuperacion, "clave nueva")):
        asunto, cuerpo = armar("123456", 15)
        assert "123456" in asunto and "123456" in cuerpo
        assert "15 minutos" in cuerpo and palabra in cuerpo
        assert "ignorá" in cuerpo                       # si no lo pidió, que lo ignore
        assert "http" not in cuerpo.lower() and "http" not in asunto.lower()
    print("OK  test_textos_de_los_mails_sin_nombre_ni_enlaces")


def test_enviar_apagado_devuelve_false_sin_tocar_la_red(monkeypatch):
    _sin_red(monkeypatch)
    for v in ("RESEND_API_KEY", "MAIL_REMITENTE"):
        monkeypatch.delenv(v, raising=False)
    assert correo.habilitado() is False
    assert correo.enviar("a@b.ar", "hola", "texto") is False
    # una sola de las dos variables no alcanza
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    assert correo.habilitado() is False and correo.enviar("a@b.ar", "h", "t") is False
    monkeypatch.delenv("RESEND_API_KEY")
    monkeypatch.setenv("MAIL_REMITENTE", "Colm3na <no-responder@avisos.colm3na.com.ar>")
    assert correo.habilitado() is False and correo.enviar("a@b.ar", "h", "t") is False
    print("OK  test_enviar_apagado_devuelve_false_sin_tocar_la_red")


def test_enviar_2xx_es_true_y_arma_bien_el_pedido(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_secreta")
    monkeypatch.setenv("MAIL_REMITENTE", "Colm3na <no-responder@avisos.colm3na.com.ar>")
    vistos = []
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"id":"1"}'), vistos=vistos)
    assert correo.habilitado() is True
    assert correo.enviar("persona@correo.ar", "Asunto", "Cuerpo del mail") is True
    pedido, timeout = vistos[0]
    assert pedido.full_url == "https://api.resend.com/emails" and pedido.get_method() == "POST"
    assert pedido.get_header("Authorization") == "Bearer re_secreta"
    assert timeout == 10
    assert json.loads(pedido.data) == {
        "from": "Colm3na <no-responder@avisos.colm3na.com.ar>", "to": ["persona@correo.ar"],
        "subject": "Asunto", "text": "Cuerpo del mail"}
    _urlopen(monkeypatch, respuesta=_Resp(202))
    assert correo.enviar("persona@correo.ar", "a", "b") is True
    print("OK  test_enviar_2xx_es_true_y_arma_bien_el_pedido")


def test_enviar_nunca_levanta(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_secreta")
    monkeypatch.setenv("MAIL_REMITENTE", "Colm3na <x@avisos.colm3na.com.ar>")
    _urlopen(monkeypatch, error=urllib.error.URLError("sin red"))
    assert correo.enviar("a@b.ar", "h", "t") is False
    _urlopen(monkeypatch, error=TimeoutError("lento"))
    assert correo.enviar("a@b.ar", "h", "t") is False
    _urlopen(monkeypatch, error=urllib.error.HTTPError(correo.API, 422, "mal", {}, None))
    assert correo.enviar("a@b.ar", "h", "t") is False
    _urlopen(monkeypatch, respuesta=_Resp(500))              # un 5xx que no levanta
    assert correo.enviar("a@b.ar", "h", "t") is False
    assert correo.enviar("", "h", "t") is False              # sin destino, ni lo intenta
    print("OK  test_enviar_nunca_levanta")


# =============================================================================
# 2. captcha.py
# =============================================================================

def test_captcha_apagado_deja_pasar_sin_red(monkeypatch):
    _sin_red(monkeypatch)
    for v in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
        monkeypatch.delenv(v, raising=False)
    assert captcha.habilitado() is False and captcha.site_key() == ""
    assert captcha.verificar("", "1.2.3.4") is True
    assert captcha.verificar("cualquier-cosa", "1.2.3.4") is True
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "solo-la-publica")        # falta el secreto
    assert captcha.habilitado() is False and captcha.verificar("", "1.2.3.4") is True
    print("OK  test_captcha_apagado_deja_pasar_sin_red")


def test_captcha_prendido_verifica_y_falla_cerrado(monkeypatch):
    _con_captcha(monkeypatch)
    assert captcha.habilitado() is True and captcha.site_key() == "sitekey-de-prueba"
    vistos = []
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": true}'), vistos=vistos)
    assert captcha.verificar("tok-ok", "9.9.9.9") is True
    pedido, timeout = vistos[0]
    assert pedido.full_url == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert timeout == 5
    cuerpo = pedido.data.decode()
    assert "secret=secreto-de-prueba" in cuerpo and "response=tok-ok" in cuerpo
    assert "remoteip=9.9.9.9" in cuerpo
    # success false
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": false, "error-codes": ["x"]}'))
    assert captcha.verificar("tok", "1.1.1.1") is False
    # sin token ni llama
    _sin_red(monkeypatch)
    assert captcha.verificar("", "1.1.1.1") is False and captcha.verificar("   ", "1.1.1.1") is False
    # red caída, timeout, JSON roto, JSON que no es un objeto, "success" que no es True
    _urlopen(monkeypatch, error=urllib.error.URLError("sin red"))
    assert captcha.verificar("tok", "1.1.1.1") is False
    _urlopen(monkeypatch, error=TimeoutError("lento"))
    assert captcha.verificar("tok", "1.1.1.1") is False
    _urlopen(monkeypatch, respuesta=_Resp(200, b"<html>no es json</html>"))
    assert captcha.verificar("tok", "1.1.1.1") is False
    _urlopen(monkeypatch, respuesta=_Resp(200, b"[1, 2]"))
    assert captcha.verificar("tok", "1.1.1.1") is False
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": "true"}'))
    assert captcha.verificar("tok", "1.1.1.1") is False
    print("OK  test_captcha_prendido_verifica_y_falla_cerrado")


# =============================================================================
# 3. La CSP
# =============================================================================

def test_csp_sin_captcha_es_identica_a_la_de_siempre(monkeypatch):
    assert main._armar_csp(False) == CSP_DE_SIEMPRE
    for v in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
        monkeypatch.delenv(v, raising=False)
    assert main._armar_csp() == CSP_DE_SIEMPRE
    assert main.CSP == CSP_DE_SIEMPRE                       # evaluada al importar, con el captcha apagado
    assert "cloudflare" not in main.CSP
    r = TestClient(main.app).get("/ingresar")
    assert r.headers["Content-Security-Policy"] == CSP_DE_SIEMPRE
    print("OK  test_csp_sin_captcha_es_identica_a_la_de_siempre")


def test_csp_con_captcha_suma_los_dos_origenes(monkeypatch):
    _con_captcha(monkeypatch)
    for csp in (main._armar_csp(), main._armar_csp(True)):
        directivas = {d.split(" ", 1)[0]: d for d in csp.split("; ")}
        assert "https://challenges.cloudflare.com" in directivas["script-src"]
        assert "'self' 'unsafe-inline'" in directivas["script-src"]
        assert directivas["frame-src"] == "frame-src https://challenges.cloudflare.com"
        assert directivas["frame-ancestors"] == "frame-ancestors 'none'"
        # lo demás, intacto
        sin = [d for d in csp.split("; ") if not d.startswith(("script-src", "frame-src"))]
        esperado = [d for d in CSP_DE_SIEMPRE.split("; ") if not d.startswith("script-src")]
        assert sin == esperado
    print("OK  test_csp_con_captcha_suma_los_dos_origenes")


# =============================================================================
# 4. El freno de los registros
# =============================================================================

def test_el_freno_de_registro_bloquea_tras_n_fallos_y_no_toca_el_de_login():
    _limpiar_frenos()
    c = TestClient(main.app)
    n = main.LOGIN_MAX_FALLOS
    for _ in range(n):
        r = c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "clave123", **DOM},
                   follow_redirects=False)
        assert r.headers["location"] == "/ingresar?error=nohabilitado", r.headers
    r = c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "clave123", **DOM},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ingresar?error=espera", r.headers
    # la empresa comparte la tabla de registro: la misma IP sigue frenada
    r = c.post("/empresa/registro", data={"cuit": CUIT_EMP, "clave": "clave123"}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar-empresa?error=espera", r.headers
    # ...pero el login NO está bloqueado: otra tabla
    r = c.post("/trabajador/login", data={"cuil": CUIL_FUERA, "clave": "x"}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=login", r.headers
    assert "testclient" not in main._intentos_login or main._intentos_login["testclient"][1] == 0.0
    # y al revés: bloquear los logins no frena el registro
    _limpiar_frenos()
    for _ in range(n):
        c.post("/trabajador/login", data={"cuil": CUIL_FUERA, "clave": "x"}, follow_redirects=False)
    r = c.post("/trabajador/login", data={"cuil": CUIL_FUERA, "clave": "x"}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=espera"
    r = c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "clave123", **DOM},
               follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=nohabilitado", r.headers
    _limpiar_frenos()
    print("OK  test_el_freno_de_registro_bloquea_tras_n_fallos_y_no_toca_el_de_login")


def test_cada_fallo_de_registro_cuenta_y_el_exito_limpia_la_ip():
    _limpiar_frenos()
    c = TestClient(main.app)
    # un CUIL mal escrito y otro no habilitado cuentan
    c.post("/trabajador/registro", data={"cuil": "27999999999", "clave": "clave123", **DOM})
    c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "clave123", **DOM})
    assert main._intentos_registro["testclient"][0] == 2
    # una cuenta ya creada cuenta como fallo
    _padron(CUIL_B)
    with db.get_session() as s:
        db.asegurar_cuenta(s, CUIL_B).clave_hash = auth.hashear_clave("la-de-antes")
        s.commit()
    c.post("/trabajador/registro", data={"cuil": CUIL_B, "clave": "clave123", **DOM})
    assert main._intentos_registro["testclient"][0] == 3
    # un registro que crea la cuenta limpia la tabla de esa IP
    _padron(CUIL_A)
    r = c.post("/trabajador/registro", data={"cuil": CUIL_A, "clave": "clave123", **DOM},
               follow_redirects=False)
    assert r.headers["location"] == "/app/inicio", r.headers
    assert "testclient" not in main._intentos_registro
    assert _clave_de(CUIL_A)
    _limpiar_frenos()
    print("OK  test_cada_fallo_de_registro_cuenta_y_el_exito_limpia_la_ip")


def test_un_fallo_de_captcha_cuenta_para_el_freno(monkeypatch):
    _limpiar_frenos()
    _con_captcha(monkeypatch)
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": false}'))
    c = TestClient(main.app)
    for _ in range(main.LOGIN_MAX_FALLOS):
        r = c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "x", **DOM,
                                                 "cf-turnstile-response": "malo"},
                   follow_redirects=False)
        assert r.headers["location"] == "/ingresar?error=captcha", r.headers
    r = c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "x", **DOM,
                                             "cf-turnstile-response": "malo"}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=espera", r.headers
    _limpiar_frenos()
    print("OK  test_un_fallo_de_captcha_cuenta_para_el_freno")


# =============================================================================
# 5. Los registros con el captcha
# =============================================================================

CUIL_C = cuit.corregir("27304050600")


def test_registro_del_afiliado_con_token_malo_no_crea_la_cuenta(monkeypatch):
    _limpiar_frenos()
    _padron(CUIL_C)
    _con_captcha(monkeypatch)
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": false}'))
    c = TestClient(main.app)
    r = c.post("/trabajador/registro", data={"cuil": CUIL_C, "clave": "clave123", **DOM,
                                             "cf-turnstile-response": "token-malo"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ingresar?error=captcha", r.headers
    assert not _clave_de(CUIL_C)
    # sin token es lo mismo
    r = c.post("/trabajador/registro", data={"cuil": CUIL_C, "clave": "clave123", **DOM},
               follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=captcha"
    assert not _clave_de(CUIL_C)
    # la pantalla lo explica y deja abierta la pestaña de registro
    page = c.get("/ingresar?error=captcha")
    assert "No pudimos comprobar que sos una persona. Volvé a intentar." in page.text
    assert "'captcha'" in page.text
    # con el token bueno entra
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": true}'))
    r = c.post("/trabajador/registro", data={"cuil": CUIL_C, "clave": "clave123", **DOM,
                                             "cf-turnstile-response": "token-bueno"},
               follow_redirects=False)
    assert r.headers["location"] == "/app/inicio", r.headers
    assert _clave_de(CUIL_C)
    _limpiar_frenos()
    print("OK  test_registro_del_afiliado_con_token_malo_no_crea_la_cuenta")


def test_registro_de_la_empresa_con_token_malo_no_crea_la_cuenta(monkeypatch):
    _limpiar_frenos()
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=SID, cuit=CUIT_EMP, razon_social="Empresa Canales SA"))
        s.commit()
    _con_captcha(monkeypatch)
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": false}'))
    c = TestClient(main.app)
    r = c.post("/empresa/registro", data={"cuit": CUIT_EMP, "clave": "clave123",
                                          "cf-turnstile-response": "token-malo"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ingresar-empresa?error=captcha", r.headers
    with Session(db.engine) as s:
        assert not s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == CUIT_EMP)).first()
    page = c.get("/ingresar-empresa?error=captcha")
    assert "No pudimos comprobar que sos una persona. Volvé a intentar." in page.text
    assert "'captcha'" in page.text
    _urlopen(monkeypatch, respuesta=_Resp(200, b'{"success": true}'))
    r = c.post("/empresa/registro", data={"cuit": CUIT_EMP, "clave": "clave123",
                                          "cf-turnstile-response": "token-bueno"},
               follow_redirects=False)
    assert r.headers["location"] == "/empresa/inicio", r.headers
    with Session(db.engine) as s:
        assert s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == CUIT_EMP)).first()
    _limpiar_frenos()
    print("OK  test_registro_de_la_empresa_con_token_malo_no_crea_la_cuenta")


def test_con_el_captcha_apagado_el_registro_anda_como_siempre(monkeypatch):
    _limpiar_frenos()
    for v in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
        monkeypatch.delenv(v, raising=False)
    _sin_red(monkeypatch)
    cuil = cuit.corregir("20311222330")
    _padron(cuil)
    c = TestClient(main.app)
    r = c.post("/trabajador/registro", data={"cuil": cuil, "clave": "clave123", **DOM},
               follow_redirects=False)
    assert r.headers["location"] == "/app/inicio", r.headers
    assert _clave_de(cuil)
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=SID, cuit=CUIT_EMP_2, razon_social="Otra SA"))
        s.commit()
    r = c.post("/empresa/registro", data={"cuit": CUIT_EMP_2, "clave": "clave123"}, follow_redirects=False)
    assert r.headers["location"] == "/empresa/inicio", r.headers
    _limpiar_frenos()
    print("OK  test_con_el_captcha_apagado_el_registro_anda_como_siempre")


def test_el_parcial_del_captcha_solo_dibuja_con_clave(monkeypatch):
    c = TestClient(main.app)
    for ruta in ("/ingresar", "/ingresar-empresa"):
        monkeypatch.setitem(main.templates.env.globals, "captcha_site_key", "")
        page = c.get(ruta).text
        assert "cf-turnstile" not in page and "challenges.cloudflare.com" not in page
        monkeypatch.setitem(main.templates.env.globals, "captcha_site_key", "mi-site-key")
        page = c.get(ruta).text
        assert 'class="cf-turnstile" data-sitekey="mi-site-key"' in page
        assert "https://challenges.cloudflare.com/turnstile/v0/api.js" in page
        # el widget va DENTRO del formulario de registro, antes del botón
        form = page[page.index('id="form-registro"'):]
        assert form.index("cf-turnstile") < form.index("Crear mi cuenta")
    print("OK  test_el_parcial_del_captcha_solo_dibuja_con_clave")


def test_las_pantallas_explican_la_espera_y_abren_el_registro():
    c = TestClient(main.app)
    for ruta in ("/ingresar?error=espera", "/ingresar-empresa?error=espera"):
        page = c.get(ruta).text
        assert "Demasiados intentos seguidos" in page, ruta
        assert "'espera'" in page, ruta
    print("OK  test_las_pantallas_explican_la_espera_y_abren_el_registro")
