"""Ingreso con Google al PANEL del sindicato (`/admin/google`).

El operador tiene un mail PROPIO en su cuenta (`CuentaPanel.mail`, de la persona
como la clave) y Google lo identifica contra él o contra el mail que el
sindicato cargó en el padrón (`CuentaTrabajador.mail_padron`) SI ella está
empadronada en alguno de sus sindicatos. Nunca contra el mail de contacto del
afiliado ni el declarado (los escribe quien se registre primero con ese CUIL).

Lo que se cuida:

1. Entra por `CuentaPanel.mail` y por el mail del padrón de su sindicato; un
   sindicato, sesión directa; varios, el selector; `registrar_acceso("admin")`.
2. Clave transitoria, sin cuenta, mail en dos cuentas, mail del padrón de un
   sindicato donde NO es operadora y mail de contacto del afiliado: no entra.
3. Restablecer la clave corta Google (se borra el `sub`, el mail queda) y la
   clave transitoria lo frena igual.
4. El mail entra por el alta (panel y plataforma), a la cuenta de la persona y
   solo si estaba vacío; «Tu cuenta» lo cambia con la clave actual.

Ningún test sale a la red (Google va simulado).

Correr con: python -m pytest test_google_panel.py -q
"""
import os
from urllib.parse import parse_qs, urlsplit

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import cuit
import db
import google_auth
import main
from db import (CuentaPanel, CuentaTrabajador, Sindicato, Trabajador, UsuarioSindicato)
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES
from sqlalchemy import delete as sa_delete

db.crear_tablas()

CLIENT_ID = "cliente-panel.apps.googleusercontent.com"
CLAVE = "clave-del-panel-1"
MAIL = "operadora@gmail.com"
SUB = "sub-operadora"


def _cuil(base):
    return cuit.corregir(base)


OPERA = _cuil("27555500010")        # la operadora de casi todos los tests
OTRA = _cuil("20555500020")         # otra operadora
SUPER = _cuil("20555500030")        # Super Admin de A (hace altas y resets)
NUEVA = _cuil("27555500040")        # persona que se da de alta

with db.get_session() as s:
    _a = Sindicato(nombre="Panel Google A", slug="panel-google-a", color_base="#0f1b2d",
                   modulos_habilitados=list(MODULOS_INICIALES))
    _b = Sindicato(nombre="Panel Google B", slug="panel-google-b", color_base="#0f1b2d",
                   modulos_habilitados=list(MODULOS_INICIALES))
    s.add(_a)
    s.add(_b)
    s.commit()
    s.refresh(_a)
    s.refresh(_b)
    SID_A, SID_B = _a.id, _b.id
    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario=SUPER, cuil=SUPER, nombre="Super A",
                           clave_hash=auth.hashear_clave("super-a-1234"), debe_cambiar_clave=False,
                           es_super_admin=True))
    s.commit()


@pytest.fixture(autouse=True)
def entorno_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secreto-de-prueba")
    main._intentos_login.clear()
    # Cada test arranca sin operadoras (la Super A de arriba se conserva) ni
    # afiliados.
    with db.get_session() as s:
        for cuil in (OPERA, OTRA, NUEVA):
            s.exec(sa_delete(UsuarioSindicato).where(UsuarioSindicato.cuil == cuil))
            s.exec(sa_delete(CuentaPanel).where(CuentaPanel.cuil == cuil))
        s.exec(sa_delete(Trabajador))
        s.exec(sa_delete(CuentaTrabajador))
        s.commit()
    accesos = []
    monkeypatch.setattr(main.db, "registrar_acceso",
                        lambda rol, sindicato_id=None: accesos.append((rol, sindicato_id)))
    return accesos


def _operadora(cuil=OPERA, sids=(SID_A,), mail="", temporal=False, sub="", activo=True):
    """Una operadora con clave propia (o transitoria) en esos sindicatos."""
    with db.get_session() as s:
        for i, sid in enumerate(sids):
            s.add(UsuarioSindicato(
                sindicato_id=sid, usuario=cuil, cuil=cuil, nombre="Operadora",
                clave_hash=auth.hashear_clave(CLAVE) if i == 0 else "",
                debe_cambiar_clave=temporal, es_super_admin=True, activo=activo))
            s.commit()
    with db.get_session() as s:
        c = s.exec(db.select(CuentaPanel).where(CuentaPanel.cuil == cuil)).first()
        c.mail, c.google_sub, c.debe_cambiar_clave = mail, sub, temporal
        s.add(c)
        s.commit()


def _afiliada(cuil, sid, padron="", contacto="", declarado=""):
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=sid, cuil=cuil, activo=True, registrado=True))
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave(CLAVE), mail_padron=padron,
                               mail=contacto, mail_declarado=declarado))
        s.commit()


def _cuenta(cuil):
    return db.cuenta_panel(cuil)


def _empezar():
    c = TestClient(main.app)
    r = c.get("/admin/google", follow_redirects=False)
    assert r.status_code == 303, r.text
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return c, q["state"][0], q["nonce"][0]


def _simular_google(monkeypatch, mail=MAIL, sub=SUB):
    monkeypatch.setattr(google_auth, "canjear_codigo", lambda code, uri: {"id_token": "x.y.z"})
    monkeypatch.setattr(google_auth, "mail_verificado", lambda tokens, nonce="": (mail, sub))


def _volver(c, state):
    return c.get("/ingresar/google/callback", params={"code": "codigo", "state": state},
                 follow_redirects=False)


def _entra(monkeypatch, mail=MAIL, sub=SUB):
    _simular_google(monkeypatch, mail=mail, sub=sub)
    c, state, _ = _empezar()
    return c, _volver(c, state)


# ---------------------------------------------------------------- la ida
def test_sin_configurar_no_hay_boton_ni_ruta(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    c = TestClient(main.app)
    assert "Continuar con Google" not in c.get("/admin").text
    assert c.get("/admin/google", follow_redirects=False).status_code == 404


def test_el_login_del_panel_tiene_el_boton():
    html = TestClient(main.app).get("/admin").text
    assert "Continuar con Google" in html and 'href="/admin/google"' in html
    assert "«Tu cuenta»" in html
    assert "gstatic" not in html and "accounts.google" not in html


def test_ir_a_google_lleva_el_rol_panel_en_el_state():
    _, state, nonce = _empezar()
    datos = auth.leer_paso(state, "google")
    assert datos == {"rol": "panel", "n": nonce}


# ---------------------------------------------------------------- 1. entra
def test_entra_por_el_mail_de_la_cuenta_con_un_solo_sindicato(monkeypatch, entorno_google):
    _operadora(mail="  Operadora@Gmail.com ")
    c, r = _entra(monkeypatch)
    assert r.status_code == 303 and r.headers["location"] == "/admin/inicio"
    ses = auth.leer_sesion(c.cookies.get(main.COOKIE_SINDICATO))
    assert ses and ses["rol"] == "sindicato" and ses["sid"] == SID_A
    assert entorno_google == [("admin", SID_A)]
    assert _cuenta(OPERA).google_sub == SUB
    assert c.get("/admin/inicio").status_code == 200


def test_la_proxima_vez_entra_por_el_sub_aunque_cambie_el_mail(monkeypatch):
    _operadora(mail=MAIL)
    assert _entra(monkeypatch)[1].headers["location"] == "/admin/inicio"
    c, r = _entra(monkeypatch, mail="otro.mail@gmail.com")
    assert r.headers["location"] == "/admin/inicio"
    assert auth.leer_sesion(c.cookies.get(main.COOKIE_SINDICATO))["sid"] == SID_A


def test_entra_por_el_mail_del_padron_de_su_sindicato(monkeypatch):
    _operadora(mail="")                                    # sin mail propio
    _afiliada(OPERA, SID_A, padron="Padron.Operadora@Gmail.com")
    c, r = _entra(monkeypatch, mail="padron.operadora@gmail.com", sub="sub-padron")
    assert r.headers["location"] == "/admin/inicio"
    cuenta = _cuenta(OPERA)
    assert cuenta.google_sub == "sub-padron"
    assert cuenta.mail == "padron.operadora@gmail.com"     # queda cargado en la cuenta


def test_el_mail_del_padron_de_un_sindicato_ajeno_no_vale(monkeypatch):
    """Está empadronada en B pero opera solo en A: ese mail no la identifica."""
    _operadora(mail="")
    _afiliada(OPERA, SID_B, padron="ajeno@gmail.com")
    c, r = _entra(monkeypatch, mail="ajeno@gmail.com", sub="sub-ajeno")
    assert r.headers["location"] == "/admin?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_SINDICATO) is None


def test_el_mail_de_contacto_o_declarado_del_afiliado_no_abre_el_panel(monkeypatch):
    """Los escribe quien se registre primero como afiliado con ese CUIL (público)."""
    _operadora(mail="")
    _afiliada(OPERA, SID_A, padron="", contacto="impostor@gmail.com", declarado="impostor@gmail.com")
    c, r = _entra(monkeypatch, mail="impostor@gmail.com", sub="sub-impostor")
    assert r.headers["location"] == "/admin?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_SINDICATO) is None


def test_varios_sindicatos_van_al_selector(monkeypatch, entorno_google):
    _operadora(mail=MAIL, sids=(SID_A, SID_B))
    c, r = _entra(monkeypatch)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/elegir?token=")
    assert c.cookies.get(main.COOKIE_SINDICATO) is None     # todavía no eligió
    assert entorno_google == []
    pagina = c.get(r.headers["location"])
    assert pagina.status_code == 200 and "Panel Google A" in pagina.text and "Panel Google B" in pagina.text
    assert _cuenta(OPERA).google_sub == SUB


# ---------------------------------------------------------------- 2. no entra
def test_clave_transitoria_no_se_saltea_por_google(monkeypatch):
    _operadora(mail=MAIL, temporal=True)
    c, r = _entra(monkeypatch)
    assert r.headers["location"] == "/admin?error=google_temporal"
    assert c.cookies.get(main.COOKIE_SINDICATO) is None
    assert _cuenta(OPERA).google_sub == ""
    assert "clave es transitoria" in c.get("/admin?error=google_temporal").text


def test_sin_cuenta_con_ese_mail(monkeypatch):
    _operadora(mail="otro@gmail.com")
    antes = len(_todas())
    c, r = _entra(monkeypatch, mail="nadie@gmail.com", sub="sub-nadie")
    assert r.headers["location"] == "/admin?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_SINDICATO) is None
    assert len(_todas()) == antes                           # no crea cuentas
    html = c.get("/admin?error=google_sinmail").text
    assert "No encontramos una cuenta del panel con ese mail" in html
    assert "cargá tu mail en Tu cuenta" in html


def _todas():
    with db.get_session() as s:
        return s.exec(db.select(CuentaPanel)).all()


def test_el_mismo_mail_en_dos_cuentas_es_varias(monkeypatch):
    _operadora(OPERA, mail=MAIL)
    _operadora(OTRA, mail="")
    _afiliada(OTRA, SID_A, padron=MAIL)                     # por el padrón, en la otra
    c, r = _entra(monkeypatch)
    assert r.headers["location"] == "/admin?error=google_varias"
    assert c.cookies.get(main.COOKIE_SINDICATO) is None
    assert _cuenta(OPERA).google_sub == "" == _cuenta(OTRA).google_sub
    assert "más de una cuenta del panel" in c.get("/admin?error=google_varias").text


def test_un_mail_atado_a_otro_sub_no_se_reasigna(monkeypatch):
    _operadora(mail=MAIL, sub="sub-del-dueno")
    c, r = _entra(monkeypatch, sub="sub-de-otro")
    assert r.headers["location"] == "/admin?error=google_sinmail"
    assert _cuenta(OPERA).google_sub == "sub-del-dueno"


def test_una_cuenta_sin_usuarios_activos_no_entra(monkeypatch):
    _operadora(mail=MAIL, activo=False)
    c, r = _entra(monkeypatch)
    assert r.headers["location"] == "/admin?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_SINDICATO) is None


# ---------------------------------------------------------------- 3. restablecer
def test_restablecer_corta_google_y_la_clave_transitoria_lo_frena(monkeypatch):
    _operadora(OTRA, mail="otra@gmail.com", sub="sub-otra")
    admin = TestClient(main.app)
    assert admin.post("/admin/login", data={"usuario": SUPER, "clave": "super-a-1234"},
                      follow_redirects=False).status_code == 303
    with db.get_session() as s:
        uid = s.exec(db.select(UsuarioSindicato).where(UsuarioSindicato.cuil == OTRA)).first().id
    r = admin.post("/admin/usuario/restablecer-clave", data={"id": uid}, follow_redirects=False)
    assert r.status_code == 200, r.text
    cuenta = _cuenta(OTRA)
    assert cuenta.debe_cambiar_clave and cuenta.google_sub == ""
    assert cuenta.mail == "otra@gmail.com"                  # el mail se deja
    c, r = _entra(monkeypatch, mail="otra@gmail.com", sub="sub-otra")
    assert r.headers["location"] == "/admin?error=google_temporal"


def test_el_reseteo_de_plataforma_tambien_suelta_google():
    _operadora(OTRA, mail="otra@gmail.com", sub="sub-otra")
    p = TestClient(main.app)
    p.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", 0, 0))
    r = p.post("/plataforma/reset-clave", data={"tipo": "sindicato", "identificador": OTRA,
                                                 "clave_nueva": "transitoria-12"}, follow_redirects=False)
    assert r.headers["location"] == "/plataforma?reset=ok"
    cuenta = _cuenta(OTRA)
    assert cuenta.google_sub == "" and cuenta.debe_cambiar_clave and cuenta.mail == "otra@gmail.com"


# ---------------------------------------------------------------- 4. de dónde sale el mail
def _admin_super():
    c = TestClient(main.app)
    assert c.post("/admin/login", data={"usuario": SUPER, "clave": "super-a-1234"},
                  follow_redirects=False).status_code == 303
    return c


def test_el_alta_con_mail_lo_guarda_en_la_cuenta():
    r = _admin_super().post("/admin/usuario", data={
        "usuario": NUEVA, "nombre": "Nueva", "clave_inicial": "inicial-1234", "rol": "super",
        "mail": "Nueva@Gmail.com"}, follow_redirects=False)
    assert "ok=usuario" in r.headers["location"]
    assert _cuenta(NUEVA).mail == "nueva@gmail.com"


def test_el_alta_no_pisa_un_mail_ya_cargado_ni_exige_mail():
    _operadora(OTRA, mail="propio@gmail.com", sids=(SID_B,))
    r = _admin_super().post("/admin/usuario", data={
        "usuario": OTRA, "nombre": "Otra", "clave_inicial": "", "rol": "super",
        "mail": "del-sindicato-a@gmail.com"}, follow_redirects=False)
    assert "ok=usuariocuenta" in r.headers["location"]
    assert _cuenta(OTRA).mail == "propio@gmail.com"
    # Sin mail también se da de alta (es opcional).
    r = _admin_super().post("/admin/usuario", data={
        "usuario": NUEVA, "nombre": "Nueva", "clave_inicial": "inicial-1234", "rol": "super"},
        follow_redirects=False)
    assert "ok=usuario" in r.headers["location"] and _cuenta(NUEVA).mail == ""


def test_un_mail_invalido_en_el_alta_no_crea_nada():
    r = _admin_super().post("/admin/usuario", data={
        "usuario": NUEVA, "nombre": "Nueva", "clave_inicial": "inicial-1234", "rol": "super",
        "mail": "esto no es un mail"}, follow_redirects=False)
    assert "err=mail" in r.headers["location"]
    assert _cuenta(NUEVA) is None


def test_la_edicion_carga_el_mail_solo_si_estaba_vacio():
    _operadora(OTRA, mail="")
    admin = _admin_super()
    with db.get_session() as s:
        uid = s.exec(db.select(UsuarioSindicato).where(UsuarioSindicato.cuil == OTRA)).first().id
    datos = {"id": uid, "nombre": "Otra", "rol": "super", "mail": "primero@gmail.com"}
    assert "ok=usuario" in admin.post("/admin/usuario/editar", data=datos, follow_redirects=False).headers["location"]
    assert _cuenta(OTRA).mail == "primero@gmail.com"
    datos["mail"] = "segundo@gmail.com"
    admin.post("/admin/usuario/editar", data=datos, follow_redirects=False)
    assert _cuenta(OTRA).mail == "primero@gmail.com"


def test_el_primer_admin_de_plataforma_puede_llevar_mail():
    p = TestClient(main.app)
    p.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", 0, 0))
    r = p.post("/plataforma/usuario", data={"sindicato_id": SID_B, "usuario": NUEVA, "nombre": "Primera",
                                             "clave_inicial": "inicial-1234", "mail": "primera@gmail.com"},
               follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    assert _cuenta(NUEVA).mail == "primera@gmail.com"
    mala = p.post("/plataforma/usuario", data={"sindicato_id": SID_B, "usuario": OTRA, "nombre": "X",
                                                "clave_inicial": "inicial-1234", "mail": "no-es-mail"},
                  follow_redirects=False)
    assert mala.headers["location"] == "/plataforma?error=mail#admin"
    assert _cuenta(OTRA) is None


def _sesion_de(cuil=OPERA):
    c = TestClient(main.app)
    assert c.post("/admin/login", data={"usuario": cuil, "clave": CLAVE},
                  follow_redirects=False).status_code == 303
    return c


def test_tu_cuenta_carga_y_cambia_el_mail_con_la_clave_actual():
    _operadora(mail="", sub="sub-viejo")
    c = _sesion_de()
    portada = c.get("/admin/inicio").text
    assert "Tu mail" in portada and "Cargar mi mail" in portada and "/admin/cuenta/mail" in portada
    # Sin la clave actual, o con una mala, no cambia nada.
    assert c.post("/admin/cuenta/mail", data={"mail": "nuevo@gmail.com", "clave_actual": "mala"}).status_code == 400
    assert c.post("/admin/cuenta/mail", data={"mail": "nuevo@gmail.com"}).status_code == 400
    assert _cuenta(OPERA).mail == ""
    # Un mail inválido tampoco.
    assert c.post("/admin/cuenta/mail", data={"mail": "x y", "clave_actual": CLAVE}).status_code == 400
    r = c.post("/admin/cuenta/mail", data={"mail": "Nuevo@Gmail.com", "clave_actual": CLAVE})
    assert r.status_code == 200 and r.json() == {"ok": True, "mail": "nuevo@gmail.com"}
    cuenta = _cuenta(OPERA)
    assert cuenta.mail == "nuevo@gmail.com" and cuenta.google_sub == ""   # cambiar el mail suelta Google
    assert "Cargado: nuevo@gmail.com" in c.get("/admin/inicio").text
    # Vaciarlo lo borra.
    assert c.post("/admin/cuenta/mail", data={"mail": "", "clave_actual": CLAVE}).status_code == 200
    assert _cuenta(OPERA).mail == ""


def test_tu_cuenta_mail_pide_sesion():
    r = TestClient(main.app).post("/admin/cuenta/mail", data={"mail": "a@b.com", "clave_actual": "x"},
                                  follow_redirects=False)
    assert r.status_code in (401, 403, 303)
    assert _cuenta(OPERA) is None or _cuenta(OPERA).mail != "a@b.com"


# ---------------------------------------------------------------- SSO: una persona, una identidad
def _afiliado_sso(cuil, sid=SID_A, declarado="", confirmado="2026-11-06 12:00", sub="", origen="",
                  padron="", contacto=""):
    """La cuenta de afiliado de la operadora, con el respaldo (`nivel_origen`) que se diga."""
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=sid, cuil=cuil, activo=True, registrado=True))
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave(CLAVE), mail_declarado=declarado,
                               mail_declarado_confirmado=confirmado if declarado else "",
                               google_sub=sub, nivel_origen=origen, mail_padron=padron, mail=contacto,
                               nivel_fiabilidad=3 if origen else 1))
        s.commit()


@pytest.mark.parametrize("origen", ["mail_padron", "recibo_propio", "presencial"])
def test_entra_al_panel_por_el_sub_de_su_cuenta_de_afiliado(monkeypatch, origen):
    _operadora(mail="")                                    # el panel no conoce su mail
    _afiliado_sso(OPERA, sub=SUB, origen=origen, declarado="otro-mail@gmail.com")
    c, r = _entra(monkeypatch, mail="cualquiera@gmail.com", sub=SUB)
    assert r.headers["location"] == "/admin/inicio"
    cuenta = _cuenta(OPERA)
    assert cuenta.google_sub == SUB and cuenta.mail == "cualquiera@gmail.com"   # próxima vez, por sub directo


def test_entra_al_panel_por_el_mail_confirmado_de_su_cuenta_de_afiliado(monkeypatch):
    _operadora(mail="")
    _afiliado_sso(OPERA, declarado="Afiliada@Gmail.com", origen="mail_padron")
    c, r = _entra(monkeypatch, mail="afiliada@gmail.com", sub="sub-afiliada")
    assert r.headers["location"] == "/admin/inicio"
    assert _cuenta(OPERA).google_sub == "sub-afiliada"


@pytest.mark.parametrize("caso", ["contacto", "declarado_sin_confirmar", "sub_sin_respaldo",
                                  "declarado_confirmado_sin_respaldo", "cuil_padron"])
def test_lo_que_escribio_quien_se_registro_no_abre_el_panel(monkeypatch, caso):
    """El CUIL es público: alguien se registra como afiliado con el de la operadora
    y cuelga su Gmail. Nada de eso alcanza sin respaldo (padrón, recibo, presencial)."""
    _operadora(mail="")
    mail = "impostor@gmail.com"
    if caso == "contacto":
        _afiliado_sso(OPERA, contacto=mail, origen="mail_padron")
    elif caso == "declarado_sin_confirmar":
        with db.get_session() as s:
            s.add(Trabajador(sindicato_id=SID_A, cuil=OPERA, activo=True, registrado=True))
            s.add(CuentaTrabajador(cuil=OPERA, clave_hash=auth.hashear_clave(CLAVE), mail_declarado=mail,
                                   mail_declarado_confirmado="", nivel_origen="mail_padron"))
            s.commit()
    elif caso == "sub_sin_respaldo":
        _afiliado_sso(OPERA, sub="sub-impostor", origen="mail_declarado")
    elif caso == "declarado_confirmado_sin_respaldo":
        _afiliado_sso(OPERA, declarado=mail, origen="mail_declarado")
    else:
        _afiliado_sso(OPERA, declarado=mail, sub="sub-impostor", origen="cuil_padron")
    c, r = _entra(monkeypatch, mail=mail, sub="sub-impostor")
    assert r.headers["location"] == "/admin?error=google_sinmail"
    assert c.cookies.get(main.COOKIE_SINDICATO) is None
    assert _cuenta(OPERA).google_sub == ""


def test_el_aviso_del_panel_sugiere_la_misma_cuenta_de_google(monkeypatch):
    html = TestClient(main.app).get("/admin?error=google_sinmail").text
    assert "usá la misma cuenta de Google" in html


def test_el_mail_de_otra_persona_en_su_cuenta_de_afiliado_cuenta_para_la_unicidad(monkeypatch):
    """Dos operadoras que se reconocen por el mismo mail (una por el panel, otra por
    su afiliado respaldado) no se adivinan: varias."""
    _operadora(OPERA, mail=MAIL)
    _operadora(OTRA, mail="")
    _afiliado_sso(OTRA, declarado=MAIL, origen="mail_padron")
    c, r = _entra(monkeypatch)
    assert r.headers["location"] == "/admin?error=google_varias"


def _empezar_afiliado():
    c = TestClient(main.app)
    r = c.get("/ingresar/google", follow_redirects=False)
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return c, q["state"][0]


def test_el_afiliado_que_entra_con_google_ata_la_cuenta_del_panel_del_mismo_cuil(monkeypatch):
    _operadora(mail="")
    _afiliado_sso(OPERA, padron="mi.padron@gmail.com", origen="mail_padron")   # respaldada por el padrón
    _simular_google(monkeypatch, mail="mi.padron@gmail.com", sub="sub-unica")
    c, state = _empezar_afiliado()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    assert _cuenta(OPERA).google_sub == "sub-unica"                      # una persona, una identidad
    # Y ahora el panel la reconoce por ese sub, sin mail alguno cargado en el panel.
    c2, r = _entra(monkeypatch, mail="mi.padron@gmail.com", sub="sub-unica")
    assert r.headers["location"] == "/admin/inicio"


def test_un_afiliado_sin_respaldo_no_ata_el_panel(monkeypatch):
    """Se registró con el CUIL ajeno y puso su Gmail de contacto: entra como afiliado
    (la ficha lo permite) pero no arrastra la cuenta del panel."""
    _operadora(mail="")
    _afiliado_sso(OPERA, contacto="impostor@gmail.com", origen="")
    _simular_google(monkeypatch, mail="impostor@gmail.com", sub="sub-impostor")
    c, state = _empezar_afiliado()
    assert _volver(c, state).headers["location"] == "/app/inicio"
    assert _cuenta(OPERA).google_sub == ""
    c2, r = _entra(monkeypatch, mail="impostor@gmail.com", sub="sub-impostor")
    assert r.headers["location"] == "/admin?error=google_sinmail"
    assert c2.cookies.get(main.COOKIE_SINDICATO) is None


def _nota_del_mail(html):
    """El texto de <div id="cm-actual"> (el JS de la página repite frases parecidas)."""
    import re
    return re.search(r'id="cm-actual">(.*?)</div>', html, re.S).group(1)


def test_tu_cuenta_muestra_el_mail_del_perfil_de_afiliado():
    _operadora(mail="")
    _afiliado_sso(OPERA, declarado="del.perfil@gmail.com", origen="mail_padron")
    portada = _sesion_de().get("/admin/inicio").text
    assert "Tu mail (de tu perfil de afiliado): del.perfil@gmail.com" in _nota_del_mail(portada)
    assert "Cargar otro mail" in portada


def test_tu_cuenta_no_ofrece_el_mail_de_un_afiliado_sin_respaldo():
    _operadora(mail="")
    _afiliado_sso(OPERA, declarado="tipeado@gmail.com", origen="mail_declarado")
    portada = _sesion_de().get("/admin/inicio").text
    assert _nota_del_mail(portada).strip() == "Todavía no cargaste un mail."


def test_el_mail_propio_del_panel_manda_sobre_el_del_perfil():
    _operadora(mail="propio@gmail.com")
    _afiliado_sso(OPERA, declarado="del.perfil@gmail.com", origen="mail_padron")
    portada = _sesion_de().get("/admin/inicio").text
    assert _nota_del_mail(portada).strip() == "Cargado: propio@gmail.com"
