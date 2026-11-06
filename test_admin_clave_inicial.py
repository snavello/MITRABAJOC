"""Alta de administradores y clave inicial (2026-11-06).

La clave con la que una persona entra al panel de un sindicato nace como
TRANSITORIA: la escribe quien da el alta (plataforma para el primer Super
Admin; el Super Admin del sindicato para el resto) y se la pasa a la persona
por fuera de la app. `POST /admin/login` no abre la sesión mientras la cuenta
(`CuentaPanel.debe_cambiar_clave`) siga con esa clave: lleva a «Elegí tu
clave» y recién cuando la persona fija la suya abre la sesión.

Qué prueba este archivo:
  1. El flujo entero del dueño: plataforma da de alta al primer Super Admin,
     entra con la transitoria, elige la suya y queda adentro.
  2. «Elegí tu clave»: reglas (coinciden, mínimo 8, distinta de la
     transitoria), la transitoria se vuelve a verificar, el token vence y no
     sirve de otro flujo, y quien trabaja en varios sindicatos pasa por el
     selector DESPUÉS de elegir.
  3. «Cambiar mi clave» (Tu cuenta): con la actual por delante, para
     cualquier operador, no sin sesión.
  4. «Restablecer clave» en Áreas y Usuarios: solo el Super Admin, solo a
     alguien de SU sindicato y activo, nunca a sí mismo, nunca a quien
     trabaja en otro sindicato (la clave es una por persona).

Correr con: python -m pytest test_admin_clave_inicial.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
import main
from db import Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea, CuentaPanel
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()


def _cuil(base: str) -> str:
    """Un CUIL con su dígito verificador, a partir de los 10 primeros."""
    import cuit
    return base + str(cuit.digito_verificador(base))


SUPER_A = _cuil("2011111111")        # Super Admin del sindicato A
LOCAL_A = _cuil("2011111112")        # Admin de seccional del sindicato A
AREA_A = _cuil("2011111113")         # usuario de área del sindicato A
SUPER_B = _cuil("2022222221")        # Super Admin del sindicato B
COMPARTIDA = _cuil("2733333331")     # trabaja en A y en B
NUEVO_PLAT = _cuil("2044444441")     # primer Super Admin dado de alta por plataforma
BAJA_A = _cuil("2055555551")         # usuario de A dado de baja

with db.get_session() as s:
    a = Sindicato(nombre="Sindicato Clave A", slug="sindicato-clave-a", color_base="#0f1b2d",
                  modulos_habilitados=list(MODULOS.keys()))
    b = Sindicato(nombre="Sindicato Clave B", slug="sindicato-clave-b", color_base="#111111",
                  modulos_habilitados=list(MODULOS.keys()))
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id
    sec = Seccional(sindicato_id=SID_A, nombre="Sede Central", ve_todas=True)
    s.add(sec); s.commit(); s.refresh(sec)
    SEC = sec.id
    area = Area(sindicato_id=SID_A, seccional_id=SEC, nombre="Secretaría Legal")
    s.add(area); s.commit(); s.refresh(area)
    AREA_ID = area.id
    s.add(PermisoArea(area_id=AREA_ID, seccion="trabajadores"))

    def _alta(sid, cuil, nombre, clave, **kw):
        s.add(UsuarioSindicato(sindicato_id=sid, usuario=cuil, cuil=cuil, nombre=nombre,
                               clave_hash=auth.hashear_clave(clave), debe_cambiar_clave=False, **kw))

    _alta(SID_A, SUPER_A, "Super A", "super-a-clave", es_super_admin=True, seccional_id=SEC)
    _alta(SID_A, LOCAL_A, "Local A", "local-a-clave", es_admin_seccional=True, seccional_id=SEC)
    _alta(SID_A, AREA_A, "Area A", "area-a-clave", area_id=AREA_ID, seccional_id=SEC)
    _alta(SID_B, SUPER_B, "Super B", "super-b-clave", es_super_admin=True)
    _alta(SID_A, COMPARTIDA, "Compartida", "compartida-clave", area_id=AREA_ID, seccional_id=SEC)
    _alta(SID_B, COMPARTIDA, "Compartida", "otra-que-se-descarta", es_super_admin=True)
    s.commit()
    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario=BAJA_A, cuil=BAJA_A, nombre="De baja",
                           clave_hash=auth.hashear_clave("baja-a-clave"), debe_cambiar_clave=False,
                           area_id=AREA_ID, seccional_id=SEC, activo=False))
    s.commit()


def _login(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    return c, r


def _entrar(usuario, clave):
    """Un cliente con la sesión del panel abierta (la cuenta ya eligió su clave)."""
    c, r = _login(usuario, clave)
    assert r.headers["location"] == "/admin/inicio", r.headers.get("location")
    return c


def _token_de(r):
    assert r.headers["location"].startswith("/admin/cambiar-clave?token="), r.headers["location"]
    return r.headers["location"].split("token=")[1]


def _sin_sesion(c):
    return not c.cookies.get(main.COOKIE_SINDICATO)


# ---------------------------------------------------------------- 1. el flujo del dueño

def test_1_plataforma_da_de_alta_al_primer_admin_y_este_elige_su_clave():
    p = TestClient(main.app)
    p.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", 0, 0))
    r = p.post("/plataforma/usuario", data={"sindicato_id": SID_A, "usuario": NUEVO_PLAT,
                                            "nombre": "Primer Admin", "clave_inicial": "transitoria-1"},
               follow_redirects=False)
    assert r.status_code == 303
    cuenta = db.cuenta_panel(NUEVO_PLAT)
    assert cuenta.debe_cambiar_clave is True and auth.verificar_clave("transitoria-1", cuenta.clave_hash)

    # Entra con la transitoria: NO se abre la sesión, lo manda a elegir la suya.
    c, r = _login(NUEVO_PLAT, "transitoria-1")
    token = _token_de(r)
    assert _sin_sesion(c)
    assert "Tu cuenta" not in c.get("/admin/inicio").text      # sin sesión no hay portada
    pagina = c.get(f"/admin/cambiar-clave?token={token}")
    assert pagina.status_code == 200 and "Elegí tu clave" in pagina.text

    r = c.post("/admin/cambiar-clave", data={"token": token, "clave_actual": "transitoria-1",
                                             "clave": "la-mia-de-verdad", "clave2": "la-mia-de-verdad"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/inicio"
    ses = auth.leer_sesion(r.cookies.get(main.COOKIE_SINDICATO))
    assert ses and ses["sid"] == SID_A
    assert db.cuenta_panel(NUEVO_PLAT).debe_cambiar_clave is False

    # A partir de ahí entra directo con la suya; la transitoria ya no sirve.
    _entrar(NUEVO_PLAT, "la-mia-de-verdad")
    _, r = _login(NUEVO_PLAT, "transitoria-1")
    assert "error=1" in r.headers["location"]


# ---------------------------------------------------------------- 2. «Elegí tu clave»

def _alta_transitoria(cuil, clave="transitoria-2", rol="area"):
    c = _entrar(SUPER_A, "super-a-clave")
    datos = {"usuario": cuil, "nombre": "Alta de prueba", "clave_inicial": clave, "rol": rol,
             "area_id": str(AREA_ID), "seccional_id": str(SEC)}
    r = c.post("/admin/usuario", data=datos, follow_redirects=False)
    assert "ok=usuario" in r.headers["location"], r.headers["location"]


def test_2_las_reglas_de_la_clave_nueva_y_la_transitoria_se_vuelve_a_verificar():
    cuil = _cuil("2766666661")
    _alta_transitoria(cuil)
    c, r = _login(cuil, "transitoria-2")
    token = _token_de(r)

    def intentar(**kw):
        datos = {"token": token, "clave_actual": "transitoria-2",
                 "clave": "clave-nueva-ok", "clave2": "clave-nueva-ok", **kw}
        resp = c.post("/admin/cambiar-clave", data=datos, follow_redirects=False)
        assert resp.status_code == 400 and _sin_sesion(c), (kw, resp.status_code)
        assert db.cuenta_panel(cuil).debe_cambiar_clave is True
        return resp.text

    assert "no coinciden" in intentar(clave2="otra-distinta")
    assert "al menos 8" in intentar(clave="corta", clave2="corta")
    assert "distinta" in intentar(clave="transitoria-2", clave2="transitoria-2")
    # El token firmado por sí solo no alcanza: hay que saber la transitoria.
    assert "no es correcta" in intentar(clave_actual="adivinando-123")
    assert not auth.verificar_clave("clave-nueva-ok", db.cuenta_panel(cuil).clave_hash)

    r = c.post("/admin/cambiar-clave", data={"token": token, "clave_actual": "transitoria-2",
                                             "clave": "clave-nueva-ok", "clave2": "clave-nueva-ok"},
               follow_redirects=False)
    assert r.headers["location"] == "/admin/inicio"
    # Ya no está pendiente: el mismo token no sirve para pisarla otra vez.
    r = c.post("/admin/cambiar-clave", data={"token": token, "clave_actual": "clave-nueva-ok",
                                             "clave": "otra-clave-mas", "clave2": "otra-clave-mas"})
    assert "venció" in r.text
    assert auth.verificar_clave("clave-nueva-ok", db.cuenta_panel(cuil).clave_hash)


def test_3_el_token_vencido_falso_o_de_otro_flujo_no_sirve():
    c = TestClient(main.app)
    assert "venció" in c.get("/admin/cambiar-clave?token=falso").text
    datos = {"clave_actual": "x", "clave": "clave-nueva-ok", "clave2": "clave-nueva-ok"}
    # Un token de otro propósito (el selector de sindicato) no abre este paso.
    otro = auth.firmar_paso({"cuil": SUPER_A}, minutos=10, proposito=main._PROPOSITO_ELEGIR_PANEL)
    r = c.post("/admin/cambiar-clave", data={**datos, "token": otro})
    assert "venció" in r.text and _sin_sesion(c)
    # Una sesión tampoco es un token de paso.
    ses = auth.crear_sesion("sindicato", id_usuario=1, sindicato_id=SID_A)
    r = c.post("/admin/cambiar-clave", data={**datos, "token": ses})
    assert "venció" in r.text and _sin_sesion(c)
    # Y uno vencido de verdad.
    viejo = auth.firmar_paso({"cuil": SUPER_A}, minutos=0, proposito=main._PROPOSITO_CAMBIO_CLAVE_PANEL)
    r = c.post("/admin/cambiar-clave", data={**datos, "token": viejo})
    assert "venció" in r.text and _sin_sesion(c)
    assert auth.verificar_clave("super-a-clave", db.cuenta_panel(SUPER_A).clave_hash)


def test_4_quien_trabaja_en_varios_sindicatos_elige_cual_despues_de_su_clave():
    # Reseteo de plataforma: la clave pasa a ser transitoria para toda la cuenta.
    p = TestClient(main.app)
    p.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", 0, 0))
    r = p.post("/plataforma/reset-clave", data={"tipo": "sindicato", "identificador": COMPARTIDA,
                                                "clave_nueva": "transitoria-3"}, follow_redirects=False)
    assert "reset=ok" in r.headers["location"]
    assert db.cuenta_panel(COMPARTIDA).debe_cambiar_clave is True
    c, r = _login(COMPARTIDA, "transitoria-3")
    token = _token_de(r)
    r = c.post("/admin/cambiar-clave", data={"token": token, "clave_actual": "transitoria-3",
                                             "clave": "elegida-por-ella", "clave2": "elegida-por-ella"},
               follow_redirects=False)
    # Todavía sin sesión: falta elegir el sindicato.
    assert r.headers["location"].startswith("/admin/elegir?token=")
    assert _sin_sesion(c)
    _, r = _login(COMPARTIDA, "elegida-por-ella")
    assert r.headers["location"].startswith("/admin/elegir?token=")


def test_5_un_usuario_dado_de_baja_no_entra_aunque_tenga_la_transitoria():
    db.fijar_clave_panel(BAJA_A, auth.hashear_clave("transitoria-baja"), debe_cambiar=True)
    c, r = _login(BAJA_A, "transitoria-baja")
    assert "error=1" in r.headers["location"] and _sin_sesion(c)


# ---------------------------------------------------------------- 3. «Cambiar mi clave»

def test_6_cambiar_mi_clave_pide_la_actual_y_vale_para_cualquier_operador():
    for cuil, clave in ((AREA_A, "area-a-clave"), (LOCAL_A, "local-a-clave")):
        c = _entrar(cuil, clave)
        # La portada ofrece el formulario.
        html = c.get("/admin/inicio").text
        assert "Cambiar mi clave" in html and "/admin/cuenta/clave" in html

        def pedir(**kw):
            datos = {"clave_actual": clave, "clave": "nueva-clave-1", "clave2": "nueva-clave-1", **kw}
            return c.post("/admin/cuenta/clave", data=datos)

        r = pedir(clave_actual="no-es-esta")
        assert r.status_code == 400 and "actual" in r.json()["error"]
        assert pedir(clave2="distinta-123").status_code == 400
        assert pedir(clave="corta", clave2="corta").status_code == 400
        assert pedir(clave=clave, clave2=clave).status_code == 400
        assert auth.verificar_clave(clave, db.cuenta_panel(cuil).clave_hash)    # nada cambió

        r = pedir()
        assert r.status_code == 200 and r.json() == {"ok": True}
        cuenta = db.cuenta_panel(cuil)
        assert cuenta.debe_cambiar_clave is False
        assert auth.verificar_clave("nueva-clave-1", cuenta.clave_hash)
        _entrar(cuil, "nueva-clave-1")
        _, r = _login(cuil, clave)
        assert "error=1" in r.headers["location"]


def test_7_cambiar_mi_clave_sin_sesion_no_existe():
    c = TestClient(main.app)
    r = c.post("/admin/cuenta/clave", data={"clave_actual": "x", "clave": "clave-nueva-1",
                                            "clave2": "clave-nueva-1"})
    assert r.status_code == 403
    # Una sesión de OTRO rol tampoco vale.
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", 0, 0))
    r = c.post("/admin/cuenta/clave", data={"clave_actual": "x", "clave": "clave-nueva-1",
                                            "clave2": "clave-nueva-1"})
    assert r.status_code == 403


def test_8_el_cambio_de_clave_propio_vale_para_todos_sus_sindicatos():
    # Entra por el selector y cambia: la cuenta es una, así que el cambio vale en los dos.
    _, r = _login(COMPARTIDA, "elegida-por-ella")
    token = r.headers["location"].split("token=")[1]
    uid = {o["sindicato_id"]: o["usuario_id"] for o in db.sindicatos_del_operador(COMPARTIDA)}[SID_B]
    c = TestClient(main.app)
    c.post("/admin/elegir", data={"token": token, "usuario_id": uid}, follow_redirects=False)
    r = c.post("/admin/cuenta/clave", data={"clave_actual": "elegida-por-ella",
                                            "clave": "cambiada-en-b-1", "clave2": "cambiada-en-b-1"})
    assert r.status_code == 200
    _, r = _login(COMPARTIDA, "cambiada-en-b-1")
    assert r.headers["location"].startswith("/admin/elegir")
    with Session(db.engine) as s:
        assert len(s.exec(select(CuentaPanel).where(CuentaPanel.cuil == COMPARTIDA)).all()) == 1


# ---------------------------------------------------------------- 4. «Restablecer clave»

def _id_de(cuil, sid=SID_A):
    with Session(db.engine) as s:
        return s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.cuil == cuil, UsuarioSindicato.sindicato_id == sid)).first().id


def _clave_mostrada(html):
    """La clave transitoria que la pantalla muestra una sola vez."""
    marca = 'id="clave-temporal">'
    return html.split(marca)[1].split("<")[0].strip()


def test_9_el_super_admin_restablece_la_clave_de_un_usuario_de_su_sindicato():
    cuil = _cuil("2777777771")
    _alta_transitoria(cuil, clave="vieja-transitoria")
    c, r = _login(cuil, "vieja-transitoria")
    c.post("/admin/cambiar-clave", data={"token": _token_de(r), "clave_actual": "vieja-transitoria",
                                         "clave": "la-que-eligio-1", "clave2": "la-que-eligio-1"})
    assert db.cuenta_panel(cuil).debe_cambiar_clave is False

    # La pantalla de usuarios ofrece el botón al Super Admin.
    jefe = _entrar(SUPER_A, "super-a-clave")
    assert "/admin/usuario/restablecer-clave" in jefe.get("/admin").text

    r = jefe.post("/admin/usuario/restablecer-clave", data={"id": _id_de(cuil)})
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]
    nueva = _clave_mostrada(r.text)
    assert len(nueva) == 8
    cuenta = db.cuenta_panel(cuil)
    assert cuenta.debe_cambiar_clave is True
    assert auth.verificar_clave(nueva, cuenta.clave_hash)
    assert not auth.verificar_clave("la-que-eligio-1", cuenta.clave_hash)

    # Con la transitoria nueva pasa de nuevo por «Elegí tu clave»; la vieja no sirve.
    _, r = _login(cuil, "la-que-eligio-1")
    assert "error=1" in r.headers["location"]
    c, r = _login(cuil, nueva)
    token = _token_de(r)
    r = c.post("/admin/cambiar-clave", data={"token": token, "clave_actual": nueva,
                                             "clave": "otra-vez-propia", "clave2": "otra-vez-propia"},
               follow_redirects=False)
    assert r.headers["location"] == "/admin/inicio"


def test_10_solo_el_super_admin_y_nunca_el_admin_de_seccional_ni_un_usuario_de_area():
    antes = db.cuenta_panel(AREA_A).clave_hash
    for cuil, clave in ((LOCAL_A, "local-a-clave"), (AREA_A, "area-a-clave")):
        try:
            c = _entrar(cuil, clave)
        except AssertionError:
            continue       # el test 6 ya les cambió la clave: entran con la nueva
        r = c.post("/admin/usuario/restablecer-clave", data={"id": _id_de(AREA_A)}, follow_redirects=False)
        assert r.status_code in (303, 403)
        assert db.cuenta_panel(AREA_A).clave_hash == antes
    for cuil, clave in ((LOCAL_A, "nueva-clave-1"), (AREA_A, "nueva-clave-1")):
        c, r = _login(cuil, clave)
        if r.headers["location"] != "/admin/inicio":
            continue
        r = c.post("/admin/usuario/restablecer-clave", data={"id": _id_de(AREA_A)}, follow_redirects=False)
        assert r.status_code in (303, 403), (cuil, r.status_code)
        assert db.cuenta_panel(AREA_A).clave_hash == antes, cuil
    assert db.cuenta_panel(AREA_A).clave_hash == antes


def test_11_aislamiento_otro_sindicato_uno_mismo_la_baja_y_quien_trabaja_en_dos():
    jefe = _entrar(SUPER_A, "super-a-clave")

    def intentar(uid):
        return jefe.post("/admin/usuario/restablecer-clave", data={"id": uid}, follow_redirects=False)

    # Un usuario de OTRO sindicato: se trata como inexistente.
    antes_b = db.cuenta_panel(SUPER_B).clave_hash
    r = intentar(_id_de(SUPER_B, SID_B))
    assert r.status_code == 303 and "err=" not in r.headers["location"]
    assert db.cuenta_panel(SUPER_B).clave_hash == antes_b

    # Uno mismo: para eso está «Cambiar mi clave».
    antes = db.cuenta_panel(SUPER_A).clave_hash
    r = intentar(_id_de(SUPER_A))
    assert "err=clavepropia" in r.headers["location"]
    assert db.cuenta_panel(SUPER_A).clave_hash == antes

    # Alguien dado de baja.
    antes = db.cuenta_panel(BAJA_A).clave_hash
    r = intentar(_id_de(BAJA_A))
    assert r.status_code == 303 and "err=" not in r.headers["location"]
    assert db.cuenta_panel(BAJA_A).clave_hash == antes

    # Quien también trabaja en el sindicato B: su clave es una sola y abre el
    # panel de B; si A pudiera fijarla, entraría a B con ella.
    antes = db.cuenta_panel(COMPARTIDA).clave_hash
    r = intentar(_id_de(COMPARTIDA))
    assert "err=clavecompartida" in r.headers["location"]
    assert db.cuenta_panel(COMPARTIDA).clave_hash == antes

    # Un id que no existe no explota.
    assert intentar(99999999).status_code == 303


def test_12_los_carteles_del_reseteo_existen_en_la_pantalla_de_usuarios():
    jefe = _entrar(SUPER_A, "super-a-clave")
    for err, texto in (("clavepropia", "Tu propia clave"), ("clavecompartida", "otro sindicato"),
                       ("sinclave", "todavía no tiene clave")):
        html = jefe.get(f"/admin?err={err}&sub=usuarios").text
        assert texto in html, err


def test_13_la_pantalla_de_usuarios_no_ofrece_restablecerse_a_si_mismo():
    jefe = _entrar(SUPER_A, "super-a-clave")
    html = jefe.get("/admin").text
    propio = _id_de(SUPER_A)
    assert f'name="id" value="{propio}"><button class="mini">Restablecer clave' not in html
