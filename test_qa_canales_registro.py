"""QA de la etapa 1 de PLAN_REGISTRO.md (captcha, mail, CSP y freno de registro).

Escrito por QA, NO por el desarrollador: cada test que falla es evidencia de un
hallazgo (el docstring dice cuál). Los que ya pasan fijan lo que se verificó a
mano y no tiene que romperse. Los marcados `xfail` son límites conocidos y
aceptados en el plan (el freno por IP es parcial a propósito) que se dejan
escritos para el día que llegue el perímetro de Cloudflare.

Correr con: python -m pytest test_qa_canales_registro.py -q
"""
import logging
import os
import re
import urllib.error

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import captcha
import correo
import cuit
import db
import main
from db import Sindicato, Trabajador
from fastapi.testclient import TestClient
from modulos import MODULOS
from sqlmodel import select

db.crear_tablas()

for _v in ("RESEND_API_KEY", "MAIL_REMITENTE", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
    os.environ.pop(_v, None)

CUIL_AFILIADO = cuit.corregir("20400500607")
CUIL_FUERA = cuit.corregir("20123456780")
DOM = {"provincia": "Santa Fe", "localidad": "Rosario"}

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato QA Canales", slug="sindicato-qa-canales",
                     color_base="#0f1b2d", modulos_habilitados=list(MODULOS.keys()))
    s.add(sind)
    s.commit()
    s.refresh(sind)
    SID = sind.id


class _Resp:
    def __init__(self, status=200, cuerpo=b"{}"):
        self.status, self._c = status, cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._c

    def getcode(self):
        return self.status


def _limpiar():
    main._intentos_login.clear()
    main._intentos_registro.clear()


def _padron(cuil):
    with db.get_session() as s:
        if not s.exec(select(Trabajador).where(Trabajador.cuil == cuil)).first():
            s.add(Trabajador(sindicato_id=SID, cuil=cuil, activo=True))
        db.guardar_datos_personales(s, cuil, nombre="Persona QA")
        s.commit()


def _con_captcha(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "sitekey-qa")
    monkeypatch.setenv("TURNSTILE_SECRET", "secreto-qa")


def _con_correo(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_CLAVE_SECRETA_QA")
    monkeypatch.setenv("MAIL_REMITENTE", "Colm3na <no-responder@avisos.colm3na.com.ar>")


class _Pedido:
    """Request mínimo para llamar a _login_* sin pasar por HTTP."""
    def __init__(self, ip):
        self.headers = {"x-forwarded-for": ip}
        self.client = None


# =============================================================================
# SEGURIDAD
# =============================================================================

def test_captcha_un_token_gigante_no_viaja_entero_a_cloudflare(monkeypatch):
    """HALLAZGO (Bajo): `captcha.verificar` manda el token tal cual. Turnstile
    emite tokens de hasta 2048 caracteres; lo que pase de ahí es basura y no
    tiene por qué reenviarse a Cloudflare. Arreglo mínimo:
    `if len(token) > 2048: return False`."""
    _con_captcha(monkeypatch)
    vistos = []

    def falso(pedido, timeout=None):
        vistos.append(pedido)
        return _Resp(200, b'{"success": false}')
    monkeypatch.setattr(captcha.urllib.request, "urlopen", falso)
    assert captcha.verificar("A" * 200_000, "1.1.1.1") is False
    assert not vistos or len(vistos[0].data) < 10_000, (
        "se reenviaron %d bytes a Cloudflare" % len(vistos[0].data))


def test_captcha_el_token_no_inyecta_parametros(monkeypatch):
    """Verificado: el cuerpo va con urlencode, un token con `&secret=x` o
    saltos de línea no agrega campos."""
    _con_captcha(monkeypatch)
    vistos = []

    def falso(pedido, timeout=None):
        vistos.append(pedido)
        return _Resp(200, b'{"success": true}')
    monkeypatch.setattr(captcha.urllib.request, "urlopen", falso)
    assert captcha.verificar("tok&secret=otro\r\nX: y", "1.1.1.1") is True
    cuerpo = vistos[0].data.decode()
    assert cuerpo.count("secret=") == 1 and "\r" not in cuerpo and "\n" not in cuerpo


def test_captcha_no_loguea_ni_el_token_ni_el_secreto(monkeypatch, caplog):
    _con_captcha(monkeypatch)

    def falso(pedido, timeout=None):
        raise urllib.error.URLError("fallo con secret=secreto-qa response=tok-privado")
    monkeypatch.setattr(captcha.urllib.request, "urlopen", falso)
    with caplog.at_level(logging.DEBUG):
        assert captcha.verificar("tok-privado", "1.1.1.1") is False
    assert "secreto-qa" not in caplog.text and "tok-privado" not in caplog.text


@pytest.mark.parametrize("cuerpo", [b'{"success": 1}', b'{"success": "True"}', b'{"success": null}',
                                    b'{}', b'null', b'"true"', b'{"Success": true}', b""])
def test_captcha_solo_acepta_success_true_booleano(monkeypatch, cuerpo):
    _con_captcha(monkeypatch)
    monkeypatch.setattr(captcha.urllib.request, "urlopen", lambda p, timeout=None: _Resp(200, cuerpo))
    assert captcha.verificar("tok", "1.1.1.1") is False


def test_correo_no_filtra_la_clave_ni_el_destino_en_el_log(monkeypatch, caplog):
    """Verificado: ante cualquier excepción solo se loguea el NOMBRE del tipo."""
    _con_correo(monkeypatch)

    def falso(pedido, timeout=None):
        raise urllib.error.URLError("Bearer re_CLAVE_SECRETA_QA para victima@correo.ar")
    monkeypatch.setattr(correo.urllib.request, "urlopen", falso)
    with caplog.at_level(logging.DEBUG):
        assert correo.enviar("victima@correo.ar", "a", "t") is False
        monkeypatch.setenv("RESEND_API_KEY", "re_CLAVE\r\nSECRETA_QA")   # cabecera inválida -> ValueError
        assert correo.enviar("victima@correo.ar", "a", "t") is False
    assert "re_CLAVE" not in caplog.text and "victima@correo.ar" not in caplog.text


@pytest.mark.parametrize("destino", [
    "a@b.com\r\nBcc: espia@x.com",       # cabecera inyectada
    "a@b.com, otro@x.com",               # dos destinatarios en un string
    "a@b.com;otro@x.com",
    "a@@b.com",
    "sin-arroba",
])
def test_correo_enviar_rechaza_un_destino_que_no_es_una_sola_direccion(monkeypatch, destino):
    """HALLAZGO (Bajo hoy, sube a Alto cuando llegue el mail declarado de la
    etapa 2): `correo.enviar` solo hace `.strip()` y manda el destino a Resend.
    Con el mail declarado por un atacante (D1), un `a@b.com, victima@x.com` o un
    CRLF depende de cómo lo trate Resend: la app no debería delegar esa
    validación. Arreglo mínimo: en `enviar`, `re.fullmatch(
    r"[^@\\s,;<>]+@[^@\\s,;<>]+\\.[^@\\s,;<>]+", destino)` antes de armar el pedido."""
    _con_correo(monkeypatch)
    vistos = []

    def falso(pedido, timeout=None):
        vistos.append(pedido)
        return _Resp(200)
    monkeypatch.setattr(correo.urllib.request, "urlopen", falso)
    correo.enviar(destino, "Asunto", "Cuerpo")
    assert not vistos, "se mandó un pedido a Resend con destino %r" % destino


def test_correo_json_con_comillas_y_unicode_queda_bien_formado(monkeypatch):
    """Verificado: el cuerpo es json.dumps, un asunto con comillas/emoji/\\u2028
    no rompe el JSON."""
    import json
    _con_correo(monkeypatch)
    vistos = []

    def falso(pedido, timeout=None):
        vistos.append(pedido)
        return _Resp(200)
    monkeypatch.setattr(correo.urllib.request, "urlopen", falso)
    raro = 'a"b\\c ñ\U0001F600'
    assert correo.enviar("ok@correo.ar", raro, raro) is True
    d = json.loads(vistos[0].data)
    assert d["subject"] == raro and d["to"] == ["ok@correo.ar"]


def test_orden_freno_captcha_padron_el_padron_no_se_toca_antes(monkeypatch):
    """Verificado: con la IP frenada no se llama ni a Cloudflare ni al padrón;
    con el captcha malo no se llama al padrón."""
    _limpiar()
    _con_captcha(monkeypatch)

    def padron_prohibido(*a, **k):
        raise AssertionError("se consultó el padrón antes de tiempo")

    def red_prohibida(*a, **k):
        raise AssertionError("se llamó a Cloudflare con la IP frenada")
    monkeypatch.setattr(main.db, "sindicatos_de_cuil", padron_prohibido)
    monkeypatch.setattr(main.db, "sindicatos_de_cuit_empleador", padron_prohibido)
    monkeypatch.setattr(captcha.urllib.request, "urlopen",
                        lambda p, timeout=None: _Resp(200, b'{"success": false}'))
    c = TestClient(main.app)
    r = c.post("/trabajador/registro", data={"cuil": CUIL_AFILIADO, "clave": "x", **DOM},
               follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=captcha"
    r = c.post("/empresa/registro", data={"cuit": "30444640975", "clave": "x"}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar-empresa?error=captcha"
    main._intentos_registro["testclient"] = [0, 9e12]            # IP ya frenada
    monkeypatch.setattr(captcha.urllib.request, "urlopen", red_prohibida)
    r = c.post("/trabajador/registro", data={"cuil": CUIL_AFILIADO, "clave": "x", **DOM,
                                             "cf-turnstile-response": "t"}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=espera_registro"
    _limpiar()


def test_el_error_domicilio_no_es_un_oraculo_gratis_de_afiliacion():
    """HALLAZGO (Bajo con captcha, Medio sin él): el fallo `domicilio` se decide
    DESPUES de consultar el padrón y NO cuenta para el freno. Mandando el
    formulario sin provincia: un CUIL que no está en el padrón vuelve como
    `nohabilitado` (cuenta como fallo) y uno que SI está vuelve como
    `domicilio` (gratis, ilimitado). Se puede preguntar por un listado de CUILes
    afiliados sin frenarse nunca, y la respuesta distinta es exactamente el
    dato sensible (Ley 25.326) que el freno quería proteger. Arreglo mínimo:
    `_login_fallo(request, _intentos_registro)` también antes del redirect
    `domicilio` (o validar el domicilio ANTES de consultar el padrón, así la
    respuesta no depende de la afiliación)."""
    _limpiar()
    _padron(CUIL_AFILIADO)
    c = TestClient(main.app)
    vistas = []
    for _ in range(main.LOGIN_MAX_FALLOS + 5):
        r = c.post("/trabajador/registro", data={"cuil": CUIL_AFILIADO, "clave": "x"},
                   follow_redirects=False)
        vistas.append(r.headers["location"])
    assert "/ingresar?error=espera_registro" in vistas, (
        "15 consultas a un CUIL afiliado, ninguna frenada: %s" % set(vistas))
    _limpiar()


@pytest.mark.xfail(reason="Aceptado en el plan (sec. 6): el freno por IP en memoria usa el primer "
                          "valor de X-Forwarded-For, que el cliente controla. Se cierra con el "
                          "perímetro de Cloudflare (INF-05).", strict=False)
def test_el_freno_se_saltea_rotando_x_forwarded_for():
    """DOCUMENTA el bypass: `_ip_de` toma `x-forwarded-for.split(',')[0]`, y detrás
    de Render ese primer valor lo escribe el atacante (el proxy agrega el suyo al
    FINAL). Con una cabecera distinta por intento nunca se llega a 10 fallos.
    Además la tabla crece una entrada por valor (hasta 5000, con claves de hasta
    el tamaño de una cabecera) y al pasar de 5000 se VACIA entera."""
    _limpiar()
    c = TestClient(main.app)
    vistas = set()
    for i in range(main.LOGIN_MAX_FALLOS * 3):
        r = c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "x", **DOM},
                   headers={"X-Forwarded-For": f"10.0.{i // 250}.{i % 250}"}, follow_redirects=False)
        vistas.add(r.headers["location"])
    assert "/ingresar?error=espera_registro" in vistas
    _limpiar()


@pytest.mark.xfail(reason="Ídem: la tabla se vacía al pasar de 5000 claves y las claves vienen de una "
                          "cabecera controlada por el cliente.", strict=False)
def test_inundar_la_tabla_de_ips_no_libera_a_una_ip_ya_frenada():
    _limpiar()
    main._intentos_registro["8.8.8.8"] = [0, 9e12]
    for i in range(5002):
        main._login_fallo(_Pedido(f"x{i}"), main._intentos_registro)
    assert main._login_bloqueado(_Pedido("8.8.8.8"), main._intentos_registro)
    _limpiar()


def test_csp_con_captcha_agrega_solo_lo_necesario_y_nada_mas():
    """Verificado byte a byte contra la CSP de origin/main (095033a)."""
    original = ("default-src 'self'; img-src 'self' data: blob: https:; media-src 'self' data: blob:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    assert main._armar_csp(False) == original
    con = main._armar_csp(True)
    assert con.replace(" https://challenges.cloudflare.com", "", 1) \
              .replace("; frame-src https://challenges.cloudflare.com", "", 1) == original
    assert con.count("cloudflare") == 2


def test_la_csp_con_captcha_solo_se_ensancha_en_las_pantallas_de_registro(monkeypatch):
    """HALLAZGO (Bajo): la docstring de `_armar_csp` y D7 dicen que el origen de
    Cloudflare se abre "solo en las pantallas de registro y recuperación", pero
    `CSP` es una constante global y el middleware la pone en TODAS las respuestas:
    /admin, /plataforma, /app y /entornos quedan con `script-src` y `frame-src` de
    un tercero que no usan. (El `'unsafe-inline'` ya existente hace que pese
    poco, pero es superficie que D7 decía acotar.) Arreglo mínimo: que el
    middleware use `_armar_csp(True)` solo para `/ingresar`, `/ingresar-empresa`
    (y las de recuperación después) y la CSP de siempre para el resto."""
    monkeypatch.setattr(main, "CSP", main._armar_csp(True))
    c = TestClient(main.app)
    for ruta in ("/plataforma", "/admin", "/ingresar-plataforma"):
        r = c.get(ruta, follow_redirects=False)
        csp = r.headers.get("Content-Security-Policy", "")
        assert "cloudflare" not in csp, f"{ruta} lleva la CSP ensanchada: {csp}"


# =============================================================================
# COMPORTAMIENTO (todo apagado = lo de hoy)
# =============================================================================

def test_todo_apagado_el_registro_hace_lo_mismo_que_antes(monkeypatch):
    """Verificado: sin variables, mismo redirect, mismas cookies, la cuenta con
    la clave, marca de registrado en el empadronamiento y los datos del
    formulario (teléfono, mail) guardados; y no se sale a la red."""
    _limpiar()
    for v in ("RESEND_API_KEY", "MAIL_REMITENTE", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(captcha.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("red con todo apagado")))
    cuil = cuit.corregir("27501234560")
    _padron(cuil)
    c = TestClient(main.app)
    r = c.post("/trabajador/registro",
               data={"cuil": cuil, "clave": "clave123", **DOM, "telefono": "341555", "mail": "yo@correo.ar"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio"
    nombres = set(r.cookies.keys())
    assert "cuil_trab" in nombres and main.COOKIE_TRABAJADOR in nombres, nombres
    with db.get_session() as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == cuil)).first()
        assert t.registrado is True
        persona = db.asegurar_cuenta(s, cuil)
        assert persona.clave_hash and persona.mail == "yo@correo.ar" and persona.telefono == "341555"
    _limpiar()


def test_el_exito_de_una_ip_limpia_los_fallos_de_esa_ip_y_no_de_las_otras():
    """Verificado + límite conocido: el éxito borra la entrada de SU IP. (Detrás
    de un NAT compartido un afiliado legítimo también le resetea el contador al
    atacante que comparte IP: es parte de lo aceptado del freno parcial.)"""
    _limpiar()
    main._intentos_registro["otra"] = [7, 0.0]
    cuil = cuit.corregir("27511234563")
    _padron(cuil)
    c = TestClient(main.app)
    c.post("/trabajador/registro", data={"cuil": CUIL_FUERA, "clave": "x", **DOM})
    assert main._intentos_registro["testclient"][0] == 1
    r = c.post("/trabajador/registro", data={"cuil": cuil, "clave": "clave123", **DOM}, follow_redirects=False)
    assert r.headers["location"] == "/app/inicio"
    assert "testclient" not in main._intentos_registro and main._intentos_registro["otra"][0] == 7
    _limpiar()


# =============================================================================
# pista() y textos
# =============================================================================

@pytest.mark.parametrize("mail", ["a@", "a@b@c.com", "@", "@@", "a", " ", None])
def test_pista_con_mails_raros_nunca_levanta_ni_devuelve_basura(mail):
    """HALLAZGO (Bajo, cosmético): 'a@' -> 'a***@' y 'a@b@c.com' -> 'a***@b@c.com'
    (se parte en la PRIMERA arroba). Una pista de un mail mal formado tendría
    que ser '' (el padrón no debería tener esos, pero si los tiene la pantalla
    mostraría un mail roto). Arreglo: exigir exactamente una arroba y dominio no vacío."""
    p = correo.pista(mail)
    assert isinstance(p, str)
    assert p == "" or re.fullmatch(r".\*\*\*@[^@]+", p), repr(p)


def test_pista_de_un_mail_con_local_de_una_letra_no_lo_regala_entero():
    """HALLAZGO (Bajo): 'j@gmail.com' -> 'j***@gmail.com' muestra la dirección
    ENTERA (con tres asteriscos de relleno). Con locales de 1 carácter la pista
    no esconde nada; sugerencia: en ese caso devolver '***@gmail.com'."""
    assert correo.pista("j@gmail.com") != "j***@gmail.com"


def test_texto_de_mail_con_un_minuto_no_dice_1_minutos():
    """HALLAZGO (Bajo, estético): `f"{minutos} minutos"` con minutos=1 da
    '1 minutos'. Hoy se llama con 15, pero la función recibe el parámetro."""
    for armar in (correo.texto_codigo_registro, correo.texto_codigo_recuperacion):
        assert "1 minutos" not in armar("123456", 1)[1]


def test_los_textos_de_mail_cumplen_la_regla_de_la_casa():
    """Castellano rioplatense, sin nombre, sin enlaces, con los minutos y el
    código, y sin pedirle nada a quien no lo pidió."""
    for armar in (correo.texto_codigo_registro, correo.texto_codigo_recuperacion):
        asunto, cuerpo = armar("482913", 15)
        t = (asunto + cuerpo).lower()
        assert "482913" in cuerpo and "15 minutos" in cuerpo
        assert "http" not in t and "www." not in t and ".com" not in t and "@" not in t
        assert "hola" not in t and "estimad" not in t       # sin saludo con nombre
        assert "ignorá" in cuerpo


# =============================================================================
# PANTALLAS
# =============================================================================

def _lista_de_errores_que_abren_registro(html):
    m = re.search(r"\[((?:'[a-z_]+',?\s*)+)\]\.indexOf\(err\)\s*>=\s*0\)\s*mostrar\('registro'\)", html)
    assert m, "no se encontró la lista del JS que abre Registrarme"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_la_espera_de_un_login_no_abre_registrarme_y_la_del_registro_si():
    c = TestClient(main.app)
    for ruta in ("/ingresar", "/ingresar-empresa"):
        lista = _lista_de_errores_que_abren_registro(c.get(ruta).text)
        assert "espera" not in lista and "espera_registro" in lista and "captcha" in lista, (ruta, lista)


def test_el_widget_no_se_dibuja_sin_clave_y_va_antes_del_boton(monkeypatch):
    c = TestClient(main.app)
    monkeypatch.setitem(main.templates.env.globals, "captcha_site_key", "")
    for ruta in ("/ingresar", "/ingresar-empresa"):
        assert "turnstile" not in c.get(ruta).text.lower()
    monkeypatch.setitem(main.templates.env.globals, "captcha_site_key", "k")
    for ruta in ("/ingresar", "/ingresar-empresa"):
        h = c.get(ruta).text
        assert h.count("cf-turnstile") == 1                      # una sola instancia, no una por pestaña
        reg = h[h.index('id="form-registro"'):]
        assert reg.index("cf-turnstile") < reg.index("Crear mi cuenta")
        assert "cf-turnstile" not in h[:h.index('id="form-registro"')]
