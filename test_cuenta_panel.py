"""Una persona, una clave para el panel de todos los sindicatos (2026-10-17).

La clave del operador vive en `CuentaPanel` (una fila por CUIL) y no en cada
`UsuarioSindicato`. Quien trabaja en el panel de más de un sindicato entra
con su única clave y elige a cuál, como el afiliado con pluriempleo.

El caso que lo destapó: un usuario de área dado de alta en La Bancaria no
podía entrar porque su CUIL ya tenía usuario en otro sindicato, y el login
probaba la clave contra la primera fila que encontraba.

Correr con: python -m pytest test_cuenta_panel.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
import main
from db import Sindicato, UsuarioSindicato, Seccional, Area, CuentaPanel
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

PERSONA = "27000000006"     # trabaja en los dos sindicatos
ADMIN_A = "20111111112"
ADMIN_B = "20222222228"

with db.get_session() as s:
    a = Sindicato(nombre="Bancaria Cuenta", slug="bancaria-cuenta", color_base="#0f1b2d")
    b = Sindicato(nombre="Otro Cuenta", slug="otro-cuenta", color_base="#111111")
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id
    sec = Seccional(sindicato_id=SID_A, nombre="Lomas de Zamora")
    s.add(sec); s.commit(); s.refresh(sec)
    area = Area(sindicato_id=SID_A, nombre="Secretaria General", seccional_id=sec.id)
    s.add(area); s.commit(); s.refresh(area)
    SEC_A, AREA_A = sec.id, area.id
    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario=ADMIN_A, nombre="Admin A",
                           clave_hash=auth.hashear_clave("clave-a"), es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_B, usuario=ADMIN_B, nombre="Admin B",
                           clave_hash=auth.hashear_clave("clave-b"), es_super_admin=True))
    s.commit()


def _cliente(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    return c, r


def _alta(admin, clave_admin, sid_area=None, clave_inicial="", **extra):
    c, _ = _cliente(admin, clave_admin)
    datos = {"usuario": PERSONA, "nombre": "Juana Manso", "clave_inicial": clave_inicial, **extra}
    return c.post("/admin/usuario", data=datos, follow_redirects=False)


def test_1_la_fila_nunca_guarda_la_clave_y_la_cuenta_nace_con_el_alta():
    r = _alta(ADMIN_B, "clave-b", clave_inicial="primera", rol="super")
    assert "ok=usuario&" in r.headers["location"]
    with Session(db.engine) as s:
        filas = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.cuil == PERSONA)).all()
    assert len(filas) == 1 and filas[0].clave_hash == ""
    cuenta = db.cuenta_panel(PERSONA)
    assert cuenta and auth.verificar_clave("primera", cuenta.clave_hash)


def test_2_un_solo_sindicato_entra_directo():
    _, r = _cliente(PERSONA, "primera")
    assert r.status_code == 303 and r.headers["location"] == "/admin/inicio"


def test_3_el_segundo_sindicato_no_pisa_la_clave():
    """El admin de La Bancaria da de alta a alguien que ya trabaja en otro
    sindicato: la clave que escribe se descarta y el aviso lo dice. Si la
    usara, entraría al panel del otro gremio con una clave elegida por él."""
    r = _alta(ADMIN_A, "clave-a", clave_inicial="la-del-segundo", rol="area",
              area_id=str(AREA_A), seccional_id=str(SEC_A))
    assert "ok=usuariocuenta" in r.headers["location"], r.headers["location"]
    cuenta = db.cuenta_panel(PERSONA)
    assert auth.verificar_clave("primera", cuenta.clave_hash)
    assert not auth.verificar_clave("la-del-segundo", cuenta.clave_hash)
    _, r = _cliente(PERSONA, "la-del-segundo")
    assert "error=1" in r.headers["location"]


def test_4_dos_sindicatos_eligen_despues_del_login_y_entran_a_los_dos():
    c, r = _cliente(PERSONA, "primera")
    assert r.headers["location"].startswith("/admin/elegir?token=")
    pagina = c.get(r.headers["location"])
    assert "Bancaria Cuenta" in pagina.text and "Otro Cuenta" in pagina.text
    assert "Secretaria General" in pagina.text and "Lomas de Zamora" in pagina.text
    token = r.headers["location"].split("token=")[1]
    opciones = {o["sindicato_id"]: o["usuario_id"] for o in db.sindicatos_del_operador(PERSONA)}
    for sid in (SID_A, SID_B):
        c2 = TestClient(main.app)
        r2 = c2.post("/admin/elegir", data={"token": token, "usuario_id": opciones[sid]},
                     follow_redirects=False)
        assert r2.headers["location"] == "/admin/inicio"
        ses = auth.leer_sesion(r2.cookies.get(main.COOKIE_SINDICATO))
        assert ses["sid"] == sid and ses["uid"] == opciones[sid]


def test_5_el_selector_no_abre_el_usuario_de_otra_persona():
    _, r = _cliente(PERSONA, "primera")
    token = r.headers["location"].split("token=")[1]
    with Session(db.engine) as s:
        ajeno = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == ADMIN_A)).first()
    c = TestClient(main.app)
    r = c.post("/admin/elegir", data={"token": token, "usuario_id": ajeno.id}, follow_redirects=False)
    assert r.headers["location"] == "/admin"
    assert not r.cookies.get(main.COOKIE_SINDICATO)


def test_6_sin_token_valido_no_hay_selector():
    c = TestClient(main.app)
    assert c.get("/admin/elegir?token=falso", follow_redirects=False).headers["location"] == "/admin"
    sesion = auth.crear_sesion("sindicato", id_usuario=1, sindicato_id=SID_A)
    r = c.post("/admin/elegir", data={"token": sesion, "usuario_id": 1}, follow_redirects=False)
    assert r.headers["location"] == "/admin"


def test_7_cambiar_de_sindicato_vuelve_al_selector_sin_pedir_clave():
    c, r = _cliente(PERSONA, "primera")
    token = r.headers["location"].split("token=")[1]
    uid = {o["sindicato_id"]: o["usuario_id"] for o in db.sindicatos_del_operador(PERSONA)}[SID_A]
    c.post("/admin/elegir", data={"token": token, "usuario_id": uid}, follow_redirects=False)
    assert "Cambiar de sindicato" in c.get("/admin/inicio").text
    r = c.get("/admin/cambiar-sindicato", follow_redirects=False)
    assert r.headers["location"].startswith("/admin/elegir?token=")
    # quien trabaja en uno solo no ve el enlace
    c_a, _ = _cliente(ADMIN_A, "clave-a")
    assert "Cambiar de sindicato" not in c_a.get("/admin/inicio").text


def test_8_un_usuario_dado_de_baja_no_se_ofrece():
    with Session(db.engine) as s:
        u = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.cuil == PERSONA, UsuarioSindicato.sindicato_id == SID_B)).first()
        u.activo = False; s.add(u); s.commit()
    _, r = _cliente(PERSONA, "primera")
    assert r.headers["location"] == "/admin/inicio"      # le queda uno: entra directo
    with Session(db.engine) as s:
        for u in s.exec(select(UsuarioSindicato).where(UsuarioSindicato.cuil == PERSONA)).all():
            u.activo = False; s.add(u)
        s.commit()
    _, r = _cliente(PERSONA, "primera")
    assert "error=1" in r.headers["location"]
    with Session(db.engine) as s:
        for u in s.exec(select(UsuarioSindicato).where(UsuarioSindicato.cuil == PERSONA)).all():
            u.activo = True; s.add(u)
        s.commit()


def test_9_el_reseteo_de_plataforma_cambia_la_clave_de_la_persona():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", 0, 0))
    r = c.post("/plataforma/reset-clave", data={"tipo": "sindicato", "identificador": PERSONA,
                                                "clave_nueva": "nueva"}, follow_redirects=False)
    assert "reset=ok" in r.headers["location"]
    _, r = _cliente(PERSONA, "nueva")
    assert r.headers["location"].startswith("/admin/elegir")
    with Session(db.engine) as s:
        assert len(s.exec(select(CuentaPanel).where(CuentaPanel.cuil == PERSONA)).all()) == 1


def test_10_la_pantalla_de_usuarios_marca_la_clave_inicial_de_la_cuenta():
    c, _ = _cliente(ADMIN_A, "clave-a")
    html = c.get("/admin").text
    assert "clave pendiente" not in html
    listado = {u["cuil"]: u for u in db.usuarios_del_sindicato(SID_A)}
    assert listado[PERSONA]["sin_clave"] is False
    # Aislamiento: el sindicato no se entera de en qué otro gremio trabaja.
    assert "Otro Cuenta" not in html


def test_11_plataforma_ve_a_la_persona_con_sus_dos_sindicatos():
    filas = {o["cuil"]: o for o in db.operadores_de_todos_los_sindicatos()}
    nombres = [x["sindicato"] for x in filas[PERSONA]["sindicatos"]]
    assert nombres == ["Bancaria Cuenta", "Otro Cuenta"]
