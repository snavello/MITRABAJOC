"""Ingreso con Google (google_auth.py): Google solo IDENTIFICA, nunca crea cuentas.

Lo que se cuida:

1. Sin `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` no existe: el botón no se
   dibuja y las tres rutas dan 404.
2. Con ellas, el botón aparece en los dos ingresos y `/ingresar/google` manda a
   Google con un `state` firmado, el `redirect_uri` del entorno y el nonce del
   intento atado al navegador (cookie).
3. La vuelta (`/ingresar/google/callback`) rechaza un `state` inválido, vencido, de
   otro propósito o de OTRO navegador; un intento cancelado y un id_token que no
   cierra vuelven al login con aviso y sin cookie de sesión.
4. Un mail CONFIRMADO y único abre exactamente la sesión del login con clave
   (cookie del rol, acceso registrado, selector si hay pluriempleo) y guarda el
   `sub`; la próxima vez entra por el `sub` aunque el mail cambie. Mail sin
   confirmar, inexistente, repetido en dos cuentas, cuenta con clave temporal o
   mail atado a otro `sub`: aviso y sin cookie. Nunca se crea una cuenta.
5. Restablecer la clave desde el panel corta el ingreso con Google.
6. `mail_verificado` verifica la FIRMA RS256 y los reclamos (alg, iss, aud, exp,
   email_verified, nonce) y falla cerrado. La firma se prueba con una clave RSA
   generada acá; ningún test sale a la red.

Correr con: python -m pytest test_google_login.py -q
"""
import base64
import hashlib
import json
import os
import random
import time
from urllib.parse import parse_qs, urlsplit

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import entorno
import google_auth
import main
from db import (CuentaEmpleador, CuentaTrabajador, Empleador, Sindicato, Trabajador,
                UsuarioSindicato)
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES
from sqlalchemy import delete as sa_delete
from sqlmodel import select

db.crear_tablas()

CLIENT_ID = "cliente-de-prueba.apps.googleusercontent.com"

with db.get_session() as s:
    _a = Sindicato(nombre="Sindicato Google A", slug="sindicato-google-a", color_base="#0f1b2d",
                   modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    _b = Sindicato(nombre="Sindicato Google B", slug="sindicato-google-b", color_base="#0f1b2d",
                   modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    s.add(_a)
    s.add(_b)
    s.commit()
    s.refresh(_a)
    s.refresh(_b)
    SID_A, SID_B = _a.id, _b.id

CLAVE = "clave-de-prueba-1"
MAIL = "ana.perez@gmail.com"
SUB = "1234567890"
AHORA = "2026-11-06 12:00"


@pytest.fixture(autouse=True)
def entorno_google(monkeypatch):
    """Google configurado; frenos limpios; `registrar_acceso` espiado."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secreto-de-prueba")
    main._intentos_login.clear()
    with db.get_session() as s:       # cada test arranca sin cuentas ni padrón
        for modelo in (Trabajador, CuentaTrabajador, Empleador, CuentaEmpleador):
            s.exec(sa_delete(modelo))
        s.commit()
    llamadas = []
    monkeypatch.setattr(main.db, "registrar_acceso",
                        lambda rol, sindicato_id=None: llamadas.append((rol, sindicato_id)))
    return llamadas


def _cuenta(cuil, declarado="", confirmado=AHORA, sids=(SID_A,), temporal=False, sub="",
            padron="", contacto="", clave=CLAVE):
    with db.get_session() as s:
        # Los tests comparten base: la cuenta empieza de cero en cada uno.
        s.exec(sa_delete(Trabajador).where(Trabajador.cuil == cuil))
        s.exec(sa_delete(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil))
        for sid in sids:
            s.add(Trabajador(sindicato_id=sid, cuil=cuil, activo=True, registrado=True))
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave(clave) if clave else "",
                               mail_declarado=declarado, mail_declarado_confirmado=confirmado,
                               mail_padron=padron, mail=contacto,
                               clave_temporal=temporal, google_sub=sub))
        s.commit()


def _empresa(cuit, declarado="", confirmado=AHORA, padron="", contacto=""):
    with db.get_session() as s:
        s.exec(sa_delete(Empleador).where(Empleador.cuit == cuit))
        s.exec(sa_delete(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit))
        s.add(Empleador(sindicato_id=SID_A, cuit=cuit, razon_social="Empresa Google",
                        activo=True, registrado=True, mail_padron=padron, mail=contacto))
        s.add(CuentaEmpleador(cuit=cuit, clave_hash=auth.hashear_clave(CLAVE),
                              mail_declarado=declarado, mail_declarado_confirmado=confirmado))
        s.commit()


def _cuenta_db(cuil):
    with db.get_session() as s:
        return s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()


def _empresa_db(cuit):
    with db.get_session() as s:
        return s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()


def _cuantas_cuentas():
    with db.get_session() as s:
        return len(s.exec(select(CuentaTrabajador)).all()), len(s.exec(select(CuentaEmpleador)).all())


def _empezar(ruta="/ingresar/google"):
    """Un navegador que ya pasó por el paso 1: devuelve (cliente, state, nonce)."""
    c = TestClient(main.app)
    r = c.get(ruta, follow_redirects=False)
    assert r.status_code == 303, r.text
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return c, q["state"][0], q["nonce"][0]


def _simular_google(monkeypatch, mail=MAIL, sub=SUB, canje=True):
    """Simula a Google: el canje de código y el id_token ya verificado."""
    pedidos = []
    monkeypatch.setattr(google_auth, "canjear_codigo",
                        lambda code, redirect_uri: pedidos.append((code, redirect_uri)) or
                        ({"id_token": "x.y.z"} if canje else None))
    monkeypatch.setattr(google_auth, "mail_verificado", lambda tokens, nonce="": (mail, sub))
    return pedidos


def _volver(c, state, code="codigo-de-google", **extra):
    return c.get("/ingresar/google/callback", params={"code": code, "state": state, **extra},
                 follow_redirects=False)


# ---------------------------------------------------------------- 1. sin configurar
def test_sin_configurar_no_hay_boton_ni_rutas(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    assert not google_auth.configurado()
    c = TestClient(main.app)
    assert "Continuar con Google" not in c.get("/ingresar").text
    assert "Continuar con Google" not in c.get("/ingresar-empresa").text
    for ruta in ("/ingresar/google", "/ingresar-empresa/google"):
        assert c.get(ruta, follow_redirects=False).status_code == 404
    assert c.get("/ingresar/google/callback", params={"code": "x", "state": "y"},
                 follow_redirects=False).status_code == 404


def test_con_una_sola_variable_sigue_apagado(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    assert not google_auth.configurado()
    assert TestClient(main.app).get("/ingresar/google", follow_redirects=False).status_code == 404


# ---------------------------------------------------------------- 2. el botón y la ida
def test_el_boton_aparece_en_los_dos_ingresos_sin_cargar_nada_de_google():
    c = TestClient(main.app)
    for ruta, destino in (("/ingresar", "/ingresar/google"),
                          ("/ingresar-empresa", "/ingresar-empresa/google")):
        html = c.get(ruta).text
        assert "Continuar con Google" in html
        assert f'href="{destino}"' in html
        # Solo un enlace del propio sitio y un SVG en línea: nada externo.
        assert "gstatic" not in html and "googleapis" not in html and "accounts.google" not in html


def test_ir_a_google_manda_a_google_con_state_firmado_y_nonce():
    c = TestClient(main.app)
    r = c.get("/ingresar/google", follow_redirects=False)
    assert r.status_code == 303
    u = urlsplit(r.headers["location"])
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q["client_id"] == CLIENT_ID
    assert q["response_type"] == "code" and q["scope"] == "openid email"
    assert q["prompt"] == "select_account"
    assert q["redirect_uri"].endswith("/ingresar/google/callback")
    datos = auth.leer_paso(q["state"], "google")
    assert datos and datos["rol"] == "trabajador" and datos["n"] == q["nonce"]
    assert c.cookies.get("google_estado") == q["nonce"]
    # El state de Google no es una sesión ni sirve para otro flujo.
    assert auth.leer_sesion(q["state"]) is None
    assert auth.leer_paso(q["state"], "registro") is None


def test_la_empresa_va_con_su_rol():
    _, state, _ = _empezar("/ingresar-empresa/google")
    assert auth.leer_paso(state, "google")["rol"] == "empleador"


def test_el_redirect_uri_sale_del_entorno_y_no_del_host(monkeypatch):
    def uri(host=None):
        r = TestClient(main.app).get("/ingresar/google", follow_redirects=False,
                                     headers={"host": host} if host else {})
        return parse_qs(urlsplit(r.headers["location"]).query)["redirect_uri"][0]
    monkeypatch.setattr(entorno, "ENTORNO", "pruebas")
    assert uri("evil.example.com") == "https://mitrabajo-pruebas.onrender.com/ingresar/google/callback"
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    assert uri() == "https://mitrabajo.onrender.com/ingresar/google/callback"
    monkeypatch.setattr(entorno, "ENTORNO", "local")
    assert uri() == "http://testserver/ingresar/google/callback"


def test_url_de_autorizacion_directa(monkeypatch):
    u = google_auth.url_autorizacion("https://x/cb", "st", "no")
    q = {k: v[0] for k, v in parse_qs(urlsplit(u).query).items()}
    assert q["scope"] == "openid email" and q["state"] == "st" and q["nonce"] == "no"
    assert q["redirect_uri"] == "https://x/cb" and q["prompt"] == "select_account"


# ---------------------------------------------------------------- 3. la vuelta rechaza
def test_state_invalido_vuelve_al_login(monkeypatch):
    pedidos = _simular_google(monkeypatch)
    c, state, _ = _empezar()
    ajeno = auth.firmar_paso({"rol": "trabajador", "n": "n"}, proposito="registro")
    for malo in ("", "basura", state + "x", ajeno):
        r = _volver(c, malo)
        assert r.status_code == 303 and r.headers["location"] == "/ingresar?error=google"
        assert c.cookies.get(main.COOKIE_TRABAJADOR) is None
    assert pedidos == []          # ni siquiera se canjeó el código


def test_state_vencido_no_sirve(monkeypatch):
    pedidos = _simular_google(monkeypatch)
    c, _, nonce = _empezar()
    viejo = auth.firmar_paso({"rol": "trabajador", "n": nonce}, minutos=-1, proposito="google")
    r = _volver(c, viejo)
    assert r.headers["location"] == "/ingresar?error=google" and pedidos == []


def test_state_de_otro_navegador_no_sirve(monkeypatch):
    """Login CSRF: un enlace de retorno armado por un tercero no abre sesión acá."""
    _cuenta("27222222228", declarado=MAIL)
    pedidos = _simular_google(monkeypatch)
    _, state_ajeno, _ = _empezar()
    victima = TestClient(main.app)            # no pasó por /ingresar/google: sin cookie
    r = _volver(victima, state_ajeno)
    assert r.headers["location"] == "/ingresar?error=google" and pedidos == []
    assert victima.cookies.get(main.COOKIE_TRABAJADOR) is None
    victima.cookies.set("google_estado", "otro-nonce")
    assert _volver(victima, state_ajeno).headers["location"] == "/ingresar?error=google"
    assert pedidos == []


def test_cancelar_en_google_vuelve_con_aviso(monkeypatch):
    pedidos = _simular_google(monkeypatch)
    c, state, _ = _empezar()
    r = c.get("/ingresar/google/callback", params={"error": "access_denied", "state": state},
              follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=google" and pedidos == []
    assert "No pudimos ingresar con Google" in c.get("/ingresar?error=google").text


def test_codigo_que_google_no_canjea(monkeypatch):
    _cuenta("27222222228", declarado=MAIL)
    _simular_google(monkeypatch, canje=False)
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None


def test_id_token_que_no_cierra(monkeypatch):
    _cuenta("27222222228", declarado=MAIL)
    monkeypatch.setattr(google_auth, "canjear_codigo", lambda code, uri: {"id_token": "a.b.c"})
    monkeypatch.setattr(google_auth, "mail_verificado", lambda tokens, nonce="": None)
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None


# ---------------------------------------------------------------- 4. la sesión
def test_mail_confirmado_unico_abre_la_sesion_del_trabajador(monkeypatch, entorno_google):
    _cuenta("20111111112", declarado="  Ana.Perez@Gmail.com ")
    pedidos = _simular_google(monkeypatch)
    c, state, _ = _empezar()
    r = _volver(c, state)
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio"
    ses = auth.leer_sesion(c.cookies.get(main.COOKIE_TRABAJADOR))
    assert ses and ses["rol"] == "trabajador" and ses["ident"] == "20111111112"
    assert c.cookies.get("cuil_trab") == "20111111112"
    assert entorno_google == [("trabajador", SID_A)]          # acceso registrado
    assert pedidos[0][0] == "codigo-de-google" and pedidos[0][1].endswith("/ingresar/google/callback")
    assert _cuenta_db("20111111112").google_sub == SUB
    assert c.cookies.get("google_estado") in (None, "")       # el intento se limpia
    # Y la portada abre con esa sesión, igual que tras el login con clave.
    assert c.get("/app/inicio").status_code == 200


def test_la_proxima_vez_entra_por_el_sub_aunque_cambie_el_mail(monkeypatch):
    _cuenta("20111111121", declarado=MAIL)
    _simular_google(monkeypatch)
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    _simular_google(monkeypatch, mail="otro.mail@gmail.com")   # mismo sub, otro mail
    c2, state2, _ = _empezar()
    r = _volver(c2, state2)
    assert r.headers["location"] == "/app/inicio"
    assert auth.leer_sesion(c2.cookies.get(main.COOKIE_TRABAJADOR))["ident"] == "20111111121"


def test_un_mail_atado_a_otro_sub_no_se_reasigna(monkeypatch):
    """El mail pudo cambiar de manos en Google: su cuenta ya tiene dueño."""
    _cuenta("20512345671", declarado="atada@gmail.com", sub="sub-del-dueno")
    _simular_google(monkeypatch, mail="atada@gmail.com", sub="sub-de-otro")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None
    assert _cuenta_db("20512345671").google_sub == "sub-del-dueno"


def test_entra_por_mail_declarado_sin_confirmar_y_queda_confirmado(monkeypatch):
    """Google es la confirmación: el declarado que nunca se confirmó por código
    vale, y al entrar queda confirmado."""
    _cuenta("20606060603", declarado="sinconfirmar@gmail.com", confirmado="")
    _simular_google(monkeypatch, mail="sinconfirmar@gmail.com", sub="sub-nc")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    cuenta = _cuenta_db("20606060603")
    assert cuenta.google_sub == "sub-nc"
    assert cuenta.mail_declarado == "sinconfirmar@gmail.com"
    assert cuenta.mail_declarado_confirmado       # con fecha
    assert cuenta.nivel_fiabilidad == 2 and cuenta.nivel_origen == "mail_declarado"


def test_entra_por_el_mail_del_padron(monkeypatch):
    _cuenta("20700000002", padron="Padron@Gmail.com ", declarado="", confirmado="")
    _simular_google(monkeypatch, mail="padron@gmail.com", sub="sub-padron")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    cuenta = _cuenta_db("20700000002")
    assert cuenta.google_sub == "sub-padron"
    assert cuenta.mail_declarado == "padron@gmail.com" and cuenta.mail_declarado_confirmado
    assert cuenta.mail_padron == "Padron@Gmail.com "          # el del sindicato no se toca
    assert cuenta.nivel_fiabilidad == 2 and cuenta.nivel_origen == "mail_padron"


def test_entra_por_el_mail_de_contacto(monkeypatch):
    _cuenta("20111111112", contacto="contacto@gmail.com", declarado="", confirmado="")
    _simular_google(monkeypatch, mail="contacto@gmail.com", sub="sub-contacto")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    cuenta = _cuenta_db("20111111112")
    assert cuenta.google_sub == "sub-contacto"
    assert cuenta.mail_declarado == "contacto@gmail.com" and cuenta.mail_declarado_confirmado
    assert cuenta.mail == "contacto@gmail.com"


def test_no_pisa_un_declarado_confirmado_distinto(monkeypatch):
    _cuenta("20512345671", declarado="confirmado@gmail.com", padron="otro@gmail.com")
    antes = _cuenta_db("20512345671").mail_declarado_confirmado
    _simular_google(monkeypatch, mail="otro@gmail.com", sub="sub-otro")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    cuenta = _cuenta_db("20512345671")
    assert cuenta.google_sub == "sub-otro"
    assert cuenta.mail_declarado == "confirmado@gmail.com"
    assert cuenta.mail_declarado_confirmado == antes


def test_el_nivel_respeta_la_politica_del_sindicato(monkeypatch):
    """Entrar con el mail de contacto no sube el nivel si el sindicato no acepta
    mails declarados (misma regla que el registro); el mail igual queda."""
    with db.get_session() as s:
        estricto = Sindicato(nombre="Sindicato Google Estricto", slug="sindicato-google-estricto",
                             color_base="#0f1b2d", acepta_mail_declarado=False,
                             modulos_habilitados=list(MODULOS_INICIALES))
        s.add(estricto)
        s.commit()
        s.refresh(estricto)
        sid = estricto.id
    _cuenta("20900000015", contacto="estricto@gmail.com", sids=(sid,), declarado="", confirmado="")
    _simular_google(monkeypatch, mail="estricto@gmail.com", sub="sub-estricto")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    cuenta = _cuenta_db("20900000015")
    assert cuenta.mail_declarado_confirmado and cuenta.nivel_fiabilidad == 1


def test_una_fila_del_padron_sin_clave_no_es_una_cuenta(monkeypatch):
    """El sindicato cargó el mail pero la persona nunca se registró: Google no abre ni cuenta."""
    _cuenta("20800000008", padron="sinclave@gmail.com", declarado="", confirmado="", clave="")
    _simular_google(monkeypatch, mail="sinclave@gmail.com", sub="sub-sinclave")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None
    cuenta = _cuenta_db("20800000008")
    assert cuenta.google_sub == "" and cuenta.mail_declarado == "" and not cuenta.clave_hash
    # Y no cuenta para la unicidad de la que sí tiene cuenta.
    _cuenta("20111111130", contacto="sinclave@gmail.com")
    c2, state2, _ = _empezar()
    assert _volver(c2, state2).headers["location"] == "/app/inicio"


def test_sin_cuenta_el_aviso_no_pide_confirmar(monkeypatch):
    _simular_google(monkeypatch, mail="nadie@gmail.com", sub="sub-nadie")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google_sinmail"
    html = c.get("/ingresar?error=google_sinmail").text
    assert "No encontramos una cuenta con ese mail. Ingresá con tu CUIL y clave y cargá tu mail en Tu perfil." in html
    assert "confirmá tu mail" not in html
    assert "tu mail está cargado en «Tu perfil»" in html


def test_mail_inexistente_no_crea_cuenta(monkeypatch):
    _simular_google(monkeypatch, mail="nadie@gmail.com", sub="sub-nadie")
    antes = _cuantas_cuentas()
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None
    assert _cuantas_cuentas() == antes


def test_dos_cuentas_con_el_mismo_mail_confirmado(monkeypatch):
    _cuenta("20111111130", declarado="familia@gmail.com")
    _cuenta("20111111147", declarado="familia@gmail.com")
    _simular_google(monkeypatch, mail="familia@gmail.com", sub="sub-familia")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google_varias"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None
    assert _cuenta_db("20111111130").google_sub == "" == _cuenta_db("20111111147").google_sub
    assert "más de una cuenta" in c.get("/ingresar?error=google_varias").text


def test_el_mismo_mail_en_campos_distintos_de_dos_cuentas_es_varias(monkeypatch):
    """La unicidad es entre cuentas, mirando los tres campos de todas."""
    _cuenta("20111111130", padron="compartido@gmail.com")
    _cuenta("20111111147", contacto="compartido@gmail.com")
    _cuenta("20111111163", declarado="Compartido@gmail.com", confirmado="")
    _simular_google(monkeypatch, mail="compartido@gmail.com", sub="sub-compartido")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google_varias"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None
    for cuil in ("20111111130", "20111111147", "20111111163"):
        cuenta = _cuenta_db(cuil)
        assert cuenta.google_sub == ""


def test_dos_mails_de_la_misma_cuenta_no_son_varias(monkeypatch):
    _cuenta("20111111130", padron="mismo@gmail.com", contacto="MISMO@gmail.com", declarado="mismo@gmail.com")
    _simular_google(monkeypatch, mail="mismo@gmail.com", sub="sub-mismo")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"


def test_clave_temporal_no_se_saltea_por_google(monkeypatch):
    _cuenta("20900000015", declarado="temporal@gmail.com", temporal=True)
    _simular_google(monkeypatch, mail="temporal@gmail.com", sub="sub-temporal")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=google_temporal"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None


def test_pluriempleo_va_al_selector_como_con_clave(monkeypatch, entorno_google):
    _cuenta("27712345670", declarado="pluri@gmail.com", sids=(SID_A, SID_B))
    _simular_google(monkeypatch, mail="pluri@gmail.com", sub="sub-pluri")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    assert entorno_google == [("trabajador", None)]           # todavía no eligió sindicato
    # Mismo resultado que el login con clave de la misma cuenta.
    por_clave = TestClient(main.app)
    r2 = por_clave.post("/trabajador/login", data={"cuil": "27712345670", "clave": CLAVE},
                        follow_redirects=False)
    assert r2.headers["location"] == "/app/inicio"
    assert c.get("/app/inicio").status_code == por_clave.get("/app/inicio").status_code
    pagina = c.get("/app").text
    assert "Sindicato Google A" in pagina and "Sindicato Google B" in pagina


def test_cuenta_sin_sindicato_activo(monkeypatch):
    with db.get_session() as s:
        s.add(CuentaTrabajador(cuil="20800000008", clave_hash=auth.hashear_clave(CLAVE),
                               mail_declarado="solo@gmail.com", mail_declarado_confirmado=AHORA))
        s.commit()
    _simular_google(monkeypatch, mail="solo@gmail.com", sub="sub-solo")
    c, state, _ = _empezar()
    assert _volver(c, state).headers["location"] == "/ingresar?error=sinsind"
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None


def test_el_freno_por_ip_alcanza_a_la_ida():
    c = TestClient(main.app)
    main._intentos_login[main._ip_de(type("R", (), {
        "headers": {}, "client": type("C", (), {"host": "testclient"})()})())] = [0, time.time() + 60]
    r = c.get("/ingresar/google", follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=espera"


# ---------------------------------------------------------------- empresa
def test_la_empresa_entra_con_su_mail_confirmado(monkeypatch, entorno_google):
    _empresa("30999888778", declarado="empresa@gmail.com")
    _simular_google(monkeypatch, mail="empresa@gmail.com", sub="sub-empresa")
    c, state, _ = _empezar("/ingresar-empresa/google")
    assert _volver(c, state).headers["location"] == "/empresa/inicio"
    ses = auth.leer_sesion(c.cookies.get(main.COOKIE_EMPLEADOR))
    assert ses and ses["rol"] == "empleador" and ses["ident"] == "30999888778"
    assert entorno_google == [("empresa", SID_A)]
    assert _empresa_db("30999888778").google_sub == "sub-empresa"


def test_la_empresa_entra_por_el_mail_del_padron_y_por_el_de_contacto(monkeypatch, entorno_google):
    _empresa("30712345671", padron="e2@gmail.com", declarado="", confirmado="")
    _simular_google(monkeypatch, mail="e2@gmail.com", sub="sub-e2")
    c, state, _ = _empezar("/ingresar-empresa/google")
    assert _volver(c, state).headers["location"] == "/empresa/inicio"
    cuenta = _empresa_db("30712345671")
    assert cuenta.google_sub == "sub-e2" and cuenta.mail_declarado == "e2@gmail.com"
    assert cuenta.mail_declarado_confirmado and cuenta.nivel_origen == "mail_padron"
    _empresa("30700000016", contacto="contacto-e@gmail.com", declarado="", confirmado="")
    _simular_google(monkeypatch, mail="contacto-e@gmail.com", sub="sub-e3")
    c, state, _ = _empezar("/ingresar-empresa/google")
    assert _volver(c, state).headers["location"] == "/empresa/inicio"
    assert _empresa_db("30700000016").google_sub == "sub-e3"


def test_la_empresa_con_el_mail_en_dos_cuentas_es_varias(monkeypatch):
    _empresa("30712345671", padron="dos@gmail.com")
    _empresa("30700000016", declarado="dos@gmail.com", confirmado="")
    _simular_google(monkeypatch, mail="dos@gmail.com", sub="sub-dos")
    c, state, _ = _empezar("/ingresar-empresa/google")
    assert _volver(c, state).headers["location"] == "/ingresar-empresa?error=google_varias"
    assert c.cookies.get(main.COOKIE_EMPLEADOR) is None


def test_la_empresa_sin_mail_vuelve_al_ingreso_de_empresa(monkeypatch):
    _empresa("30712345671", declarado="e2@gmail.com", confirmado="")
    _simular_google(monkeypatch, mail="otra@gmail.com", sub="sub-e4")
    c, state, _ = _empezar("/ingresar-empresa/google")
    assert _volver(c, state).headers["location"] == "/ingresar-empresa?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_EMPLEADOR) is None
    assert "CUIT" in c.get("/ingresar-empresa?error=google_sinmail").text


def test_un_mail_de_afiliado_no_abre_la_empresa(monkeypatch):
    """Los roles están aislados: el mail de una cuenta de afiliado no sirve en el ingreso de empresa."""
    _cuenta("20111111163", declarado="soloafiliado@gmail.com")
    _simular_google(monkeypatch, mail="soloafiliado@gmail.com", sub="sub-sa")
    c, state, _ = _empezar("/ingresar-empresa/google")
    assert _volver(c, state).headers["location"] == "/ingresar-empresa?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_EMPLEADOR) is None


# ---------------------------------------------------------------- 5. restablecer clave
def test_restablecer_la_clave_corta_el_ingreso_con_google(monkeypatch):
    cuil = "20577777772"
    _cuenta(cuil, declarado="impostor@gmail.com", contacto="impostor@gmail.com", sub="sub-impostor",
            padron="dueno@gmail.com")
    with db.get_session() as s:
        s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20577777771", cuil="20577777771",
                               nombre="Super", clave_hash=auth.hashear_clave("super-a"),
                               debe_cambiar_clave=False, es_super_admin=True))
        s.commit()
    admin = TestClient(main.app)
    assert admin.post("/admin/login", data={"usuario": "20577777771", "clave": "super-a"},
                      follow_redirects=False).status_code == 303
    r = admin.post("/admin/trabajador/restablecer-clave", data={"cuil": cuil}, follow_redirects=False)
    assert r.status_code == 200, r.text
    c = _cuenta_db(cuil)
    assert c.clave_temporal and c.google_sub == "" and c.mail_declarado_confirmado == ""
    assert c.mail_declarado == "" and c.mail == "" and c.mail_padron == "dueno@gmail.com"
    # El mail del impostor ya no abre la cuenta, ni por el sub ni por el mail.
    for mail, sub in (("impostor@gmail.com", "sub-impostor"), ("impostor@gmail.com", "otro-sub")):
        _simular_google(monkeypatch, mail=mail, sub=sub)
        cli, state, _ = _empezar()
        assert _volver(cli, state).headers["location"] == "/ingresar?error=google_sinmail"
        assert cli.cookies.get(main.COOKIE_TRABAJADOR) is None
    # El del padrón (del sindicato) sigue siendo del dueño, pero con la clave
    # temporal pendiente Google no se la saltea.
    _simular_google(monkeypatch, mail="dueno@gmail.com", sub="sub-dueno")
    cli, state, _ = _empezar()
    assert _volver(cli, state).headers["location"] == "/ingresar?error=google_temporal"


# ---------------------------------------------------------------- 6. el id_token
def _generar_clave_rsa():
    """Una RSA de 2048 bits con enteros de Python (sin librerías), determinista."""
    rnd = random.Random(20261106)
    bases = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)

    def es_primo(n):
        d, r = n - 1, 0
        while d % 2 == 0:
            d //= 2
            r += 1
        for a in bases:
            x = pow(a, d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                return False
        return True

    def primo(bits):
        while True:
            n = rnd.getrandbits(bits) | (1 << (bits - 1)) | 1
            if es_primo(n):
                return n

    e = 65537
    while True:
        p, q = primo(1024), primo(1024)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


_RSA = {}


def _rsa():
    if not _RSA:
        _RSA["n"], _RSA["e"], _RSA["d"] = _generar_clave_rsa()
    return _RSA["n"], _RSA["e"], _RSA["d"]


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _firmar(cabecera, reclamos):
    n, _, d = _rsa()
    cuerpo = _b64(json.dumps(cabecera).encode()) + "." + _b64(json.dumps(reclamos).encode())
    largo = (n.bit_length() + 7) // 8
    sufijo = google_auth._PREFIJO_SHA256 + hashlib.sha256(cuerpo.encode()).digest()
    em = b"\x00\x01" + b"\xff" * (largo - 3 - len(sufijo)) + b"\x00" + sufijo
    firma = pow(int.from_bytes(em, "big"), d, n).to_bytes(largo, "big")
    return cuerpo + "." + _b64(firma)


def _reclamos(**cambios):
    base = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": SUB,
            "email": "  Ana.Perez@Gmail.com ", "email_verified": True,
            "exp": int(time.time()) + 3600, "nonce": "nonce-1"}
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}


CAB = {"alg": "RS256", "kid": "k1", "typ": "JWT"}


@pytest.fixture
def claves_de_google(monkeypatch):
    n, e, _ = _rsa()
    monkeypatch.setattr(google_auth, "_clave_publica", lambda kid: (n, e) if kid == "k1" else None)


def test_id_token_valido(claves_de_google):
    token = _firmar(CAB, _reclamos())
    assert google_auth.mail_verificado({"id_token": token}, "nonce-1") == ("ana.perez@gmail.com", SUB)
    assert google_auth.mail_verificado({"id_token": token}) == ("ana.perez@gmail.com", SUB)
    # El otro emisor que usa Google, sin el esquema, también vale.
    assert google_auth.mail_verificado({"id_token": _firmar(CAB, _reclamos(iss="accounts.google.com"))})
    # email_verified como texto, que es como lo manda tokeninfo.
    assert google_auth.mail_verificado({"id_token": _firmar(CAB, _reclamos(email_verified="true"))})


@pytest.mark.parametrize("cambios", [
    {"iss": "https://evil.example.com"},
    {"aud": "otro-cliente.apps.googleusercontent.com"},
    {"aud": None},
    {"exp": 1},
    {"exp": None},
    {"exp": "mañana"},
    {"email_verified": False},
    {"email_verified": "false"},
    {"email_verified": None},
    {"email": None},
    {"email": "dos@arrobas@gmail.com"},
    {"email": "con espacio@gmail.com"},
    {"sub": None},
    {"sub": ""},
    {"nonce": "otro-nonce"},
    {"nonce": None},
], ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()))
def test_id_token_con_reclamos_malos(claves_de_google, cambios):
    token = _firmar(CAB, _reclamos(**cambios))
    assert google_auth.mail_verificado({"id_token": token}, "nonce-1") is None


def test_id_token_con_firma_mala(claves_de_google):
    cab, cuerpo, firma = _firmar(CAB, _reclamos()).split(".")
    # Reclamos cambiados con la firma de los originales.
    otros = _b64(json.dumps(_reclamos(email="victima@gmail.com")).encode())
    assert google_auth.mail_verificado({"id_token": f"{cab}.{otros}.{firma}"}) is None
    # Firma vacía, truncada, con basura o del largo justo pero de otro mensaje.
    for mala in ("", "AAAA", firma[:-4], "!!!", _b64(b"\x01" * 256)):
        assert google_auth.mail_verificado({"id_token": f"{cab}.{cuerpo}.{mala}"}) is None


def test_id_token_alg_none_hs256_y_kid_desconocido(claves_de_google):
    sin_firma = _b64(b'{"alg":"none"}') + "." + _b64(json.dumps(_reclamos()).encode()) + "."
    assert google_auth.mail_verificado({"id_token": sin_firma}) is None
    for cab in ({"alg": "none", "kid": "k1"}, {"alg": "HS256", "kid": "k1"},
                {"alg": "RS256"}, {"alg": "RS256", "kid": "desconocida"}):
        assert google_auth.mail_verificado({"id_token": _firmar(cab, _reclamos())}) is None


def test_id_token_roto_nunca_lanza(claves_de_google):
    for tokens in (None, {}, {"id_token": None}, {"id_token": 5}, {"id_token": "a.b"},
                   {"id_token": "a.b.c.d"}, {"id_token": "!!.!!.!!"}, "texto"):
        assert google_auth.mail_verificado(tokens) is None


def test_sin_configurar_no_se_acepta_ningun_token(monkeypatch, claves_de_google):
    token = _firmar(CAB, _reclamos())
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    assert google_auth.mail_verificado({"id_token": token}) is None


def test_claves_de_google_con_cache_y_un_solo_reintento(monkeypatch):
    llamadas = []
    monkeypatch.setattr(google_auth, "_descargar_claves",
                        lambda: llamadas.append(1) or {"k1": (3, 5)})
    google_auth._cache_claves.update({"claves": {}, "hasta": 0.0, "ultimo_intento": 0.0})
    try:
        assert google_auth._clave_publica("k1") == (3, 5)
        assert google_auth._clave_publica("k1") == (3, 5)
        assert len(llamadas) == 1                           # la segunda sale del caché
        # Recién bajadas, un kid desconocido no vuelve a pedirlas…
        assert google_auth._clave_publica("nueva") is None
        assert len(llamadas) == 1
        # …pero pasado el minuto sí (rotación de claves), una sola vez.
        google_auth._cache_claves["ultimo_intento"] -= 120
        assert google_auth._clave_publica("nueva") is None
        assert len(llamadas) == 2
        assert google_auth._clave_publica("otra") is None   # …pero no más de uno por minuto
        assert len(llamadas) == 2
    finally:
        google_auth._cache_claves.update({"claves": {}, "hasta": 0.0, "ultimo_intento": 0.0})


def test_si_google_no_responde_se_falla_cerrado(monkeypatch):
    def caida(*a, **k):
        raise OSError("sin red")
    monkeypatch.setattr(google_auth.urllib.request, "urlopen", caida)
    google_auth._cache_claves.update({"claves": {}, "hasta": 0.0, "ultimo_intento": 0.0})
    try:
        assert google_auth.canjear_codigo("codigo", "http://x/cb") is None
        assert google_auth._descargar_claves() == {}
        assert google_auth.mail_verificado({"id_token": _firmar(CAB, _reclamos())}) is None
    finally:
        google_auth._cache_claves.update({"claves": {}, "hasta": 0.0, "ultimo_intento": 0.0})


def test_canjear_sin_codigo_ni_configuracion(monkeypatch):
    assert google_auth.canjear_codigo("", "http://x/cb") is None
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert google_auth.canjear_codigo("codigo", "http://x/cb") is None
