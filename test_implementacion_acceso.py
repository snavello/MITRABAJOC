"""Mesa de implementación, bloque 2: el acceso (login del sindicato con mail y
clave, clave transitoria, aislamiento por proyecto, API del equipo, freno por
IP y 404 en demo).

Correr con: python -m pytest test_implementacion_acceso.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import auth
import db
import entorno
import implementacion as im
import main

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
COOKIE_IMPL = main.COOKIES_POR_ROL["implementacion"]
TRANSITORIA = "transitoria1"
DEFINITIVA = "definitiva-2026"


@pytest.fixture(autouse=True)
def _sin_freno():
    main._intentos_impl.clear()
    yield
    main._intentos_impl.clear()


def _unico(prefijo="u"):
    return f"{prefijo}{uuid.uuid4().hex[:8]}"


def _cliente():
    return TestClient(main.app, follow_redirects=False)


def _proyecto(nombre=None):
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, nombre or _unico("Proy "), EQ).id


def _usuario(pid, definitiva=True, nombre="Carla Sindicato", mail=None):
    """Devuelve (id, mail). Con `definitiva` ya eligió su clave (DEFINITIVA)."""
    mail = mail or f"{_unico()}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, nombre, mail, TRANSITORIA, EQ)
        if definitiva:
            db.impl_usuario_cambiar_clave(s, u.id, TRANSITORIA, DEFINITIVA)
        return u.id, mail


def _entrar(c, mail, clave=DEFINITIVA, **kw):
    return c.post("/implementacion/ingresar", data={"mail": mail, "clave": clave}, **kw)


def _usuario_plataforma(usuario=None, **campos):
    usuario = usuario or _unico("eq")
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario,
                                 clave_hash=auth.hashear_clave("x" * 12),
                                 debe_cambiar_clave=False, debe_completar_datos=False, **campos)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id, usuario


def _equipo():
    uid, usuario = _usuario_plataforma()
    c = _cliente()
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    return c, uid


def _request_con(cookies: dict) -> Request:
    cabecera = "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                    "headers": [(b"cookie", cabecera)] if cookies else []})


# ---------- Login ----------
def test_login_correcto_abre_la_sesion_y_confirma_el_ingreso():
    pid = _proyecto("La Bancaria prueba")
    _, mail = _usuario(pid, nombre="Carla Sindicato")
    c = _cliente()
    r = _entrar(c, mail)
    assert r.status_code == 303 and r.headers["location"] == "/implementacion"
    assert COOKIE_IMPL in r.cookies
    pagina = c.get("/implementacion")
    assert pagina.status_code == 200
    assert "Carla Sindicato" in pagina.text and "La Bancaria prueba" in pagina.text


def test_login_incorrecto_da_el_mismo_aviso_exista_o_no_el_mail():
    pid = _proyecto()
    _, mail = _usuario(pid)
    mala = _entrar(_cliente(), mail, "clave-equivocada")
    inexistente = _entrar(_cliente(), "nadie@sindicato.test", "clave-equivocada")
    for r in (mala, inexistente):
        assert r.status_code == 303 and r.headers["location"] == "/implementacion/ingresar?error=login"
        assert COOKIE_IMPL not in r.cookies
    assert "Mail o clave incorrectos" in _cliente().get("/implementacion/ingresar?error=login").text


def test_usuario_inactivo_no_entra_y_su_sesion_deja_de_valer():
    pid = _proyecto()
    uid, mail = _usuario(pid)
    c = _cliente()
    assert _entrar(c, mail).headers["location"] == "/implementacion"
    assert c.get("/implementacion").status_code == 200
    with db.get_session() as s:
        db.impl_usuario_activar(s, pid, uid, False, EQ)
    assert c.get("/implementacion").status_code == 401           # la sesión ya abierta tampoco sirve
    r = _entrar(_cliente(), mail)
    assert r.headers["location"] == "/implementacion/ingresar?error=login"


def test_proyecto_inactivo_no_deja_entrar():
    pid = _proyecto()
    _, mail = _usuario(pid)
    with db.get_session() as s:
        p = db.impl_proyecto(s, pid)
        p.activo = False
        s.add(p)
        s.commit()
    assert _entrar(_cliente(), mail).headers["location"] == "/implementacion/ingresar?error=login"


# ---------- Clave transitoria ----------
def test_la_transitoria_no_abre_sesion_y_obliga_a_elegir_clave():
    pid = _proyecto()
    _, mail = _usuario(pid, definitiva=False)
    c = _cliente()
    r = _entrar(c, mail, TRANSITORIA)
    assert r.status_code == 303 and r.headers["location"].startswith("/implementacion/cambiar-clave?token=")
    assert COOKIE_IMPL not in r.cookies
    assert c.get("/implementacion").status_code == 401           # sin sesión todavía
    token = r.headers["location"].split("token=")[1]
    pantalla = c.get(f"/implementacion/cambiar-clave?token={token}")
    assert pantalla.status_code == 200 and "Elegí tu clave" in pantalla.text and token in pantalla.text

    def cambiar(**kw):
        datos = {"token": token, "clave_actual": TRANSITORIA, "clave": DEFINITIVA, "clave2": DEFINITIVA}
        datos.update(kw)
        return c.post("/implementacion/cambiar-clave", data=datos)

    assert cambiar(clave2="otra-distinta-1").status_code == 400            # no coinciden
    assert cambiar(clave="corta", clave2="corta").status_code == 400      # menos de 8
    assert cambiar(clave=TRANSITORIA, clave2=TRANSITORIA).status_code == 400   # igual a la transitoria
    assert cambiar(clave_actual="no-es-la-transitoria").status_code == 400
    assert COOKIE_IMPL not in c.cookies

    ok = cambiar()
    assert ok.status_code == 303 and ok.headers["location"] == "/implementacion"
    assert COOKIE_IMPL in ok.cookies
    assert c.get("/implementacion").status_code == 200
    # Ahora entra con la nueva y la transitoria ya no sirve.
    assert _entrar(_cliente(), mail).headers["location"] == "/implementacion"
    assert _entrar(_cliente(), mail, TRANSITORIA).headers["location"] == "/implementacion/ingresar?error=login"


def test_token_falso_o_de_otro_flujo_da_pedido_vencido():
    c = _cliente()
    for token in ("", "falso.falso", auth.firmar_paso({"uid": 1}, proposito="cambio_clave")):
        r = c.post("/implementacion/cambiar-clave",
                   data={"token": token, "clave_actual": "x", "clave": "unaclave123", "clave2": "unaclave123"})
        assert r.status_code == 200 and "El pedido venció" in r.text
    assert "El pedido venció" in c.get("/implementacion/cambiar-clave?token=falso").text


def test_el_token_solo_no_alcanza_si_la_transitoria_es_otra():
    pid = _proyecto()
    uid, _ = _usuario(pid, definitiva=False)
    token = auth.firmar_paso({"uid": uid}, minutos=10, proposito=main._PROPOSITO_CAMBIO_CLAVE_IMPL)
    r = _cliente().post("/implementacion/cambiar-clave", data={
        "token": token, "clave_actual": "adivinada", "clave": DEFINITIVA, "clave2": DEFINITIVA})
    assert r.status_code == 400 and COOKIE_IMPL not in r.cookies


# ---------- Sin sesión ----------
def test_sin_sesion_no_entra():
    c = _cliente()
    r = c.get("/implementacion")
    assert r.status_code == 401                                    # llamada fetch: JSON
    nav = c.get("/implementacion", headers={"accept": "text/html"})
    assert nav.status_code == 303 and nav.headers["location"] == "/implementacion/ingresar"
    c.cookies.set(COOKIE_IMPL, "x.y")
    assert c.get("/implementacion").status_code == 401


def test_salir_borra_la_cookie():
    pid = _proyecto()
    _, mail = _usuario(pid)
    c = _cliente()
    _entrar(c, mail)
    r = c.post("/implementacion/salir")
    assert r.status_code == 303 and r.headers["location"] == "/implementacion/ingresar"
    assert c.get("/implementacion").status_code == 401


# ---------- Aislamiento: _actor_impl ----------
def test_actor_sindicato_solo_ve_su_proyecto_y_otro_id_es_404():
    p1, p2 = _proyecto(), _proyecto()
    uid, _ = _usuario(p1, nombre="Dante")
    req = _request_con({COOKIE_IMPL: auth.crear_sesion("implementacion", uid, p1, ident=f"{uid}:{p1}")})
    actor, pid = main._actor_impl(req)
    assert actor == im.Actor(im.SINDICATO, uid, "Dante") and pid == p1
    assert main._actor_impl(req, p1)[1] == p1
    for ajeno in (p2, 99999999):                                    # existente o no: igual 404, nunca 403
        with pytest.raises(HTTPException) as e:
            main._actor_impl(req, ajeno)
        assert e.value.status_code == 404
    # Una sesión armada con otro proyecto en el token no sirve: manda la base.
    falsa = _request_con({COOKIE_IMPL: auth.crear_sesion("implementacion", uid, p2, ident=f"{uid}:{p2}")})
    with pytest.raises(HTTPException) as e:
        main._actor_impl(falsa)
    assert e.value.status_code == 401


def test_actor_equipo_puede_cualquier_proyecto():
    p1, p2 = _proyecto(), _proyecto()
    uid, usuario = _usuario_plataforma()
    req = _request_con({main.COOKIES_POR_ROL["plataforma"]: auth.crear_sesion("plataforma", uid, ident=usuario)})
    actor, pid = main._actor_impl(req)
    assert actor.lado == im.EQUIPO and actor.id == uid and pid is None
    assert main._actor_impl(req, p1)[1] == p1 and main._actor_impl(req, p2)[1] == p2
    with pytest.raises(HTTPException) as e:
        main._actor_impl(req, 99999999)
    assert e.value.status_code == 404


def test_actor_equipo_exige_usuario_nominal_activo_y_completo():
    sin_sesion = _request_con({})
    with pytest.raises(HTTPException) as e:
        main._actor_impl(sin_sesion)
    assert e.value.status_code == 401
    cookie = main.COOKIES_POR_ROL["plataforma"]
    generico = _request_con({cookie: auth.crear_sesion("plataforma")})        # uid 0
    with pytest.raises(HTTPException):
        main._actor_impl(generico)
    uid, usuario = _usuario_plataforma(activo=False)
    with pytest.raises(HTTPException):
        main._actor_impl(_request_con({cookie: auth.crear_sesion("plataforma", uid, ident=usuario)}))
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=_unico("pend"), nombre="P", clave_hash="x", debe_cambiar_clave=True)
        s.add(u)
        s.commit()
        pend = u.id
    with pytest.raises(HTTPException):
        main._actor_impl(_request_con({cookie: auth.crear_sesion("plataforma", pend, ident="p")}))


def test_actor_impl_usa_la_sesion_que_le_pasan():
    pid = _proyecto()
    uid, _ = _usuario(pid)
    req = _request_con({COOKIE_IMPL: auth.crear_sesion("implementacion", uid, pid)})
    with db.get_session() as s:
        assert main._actor_impl(req, pid, s=s)[1] == pid


# ---------- Equipo: API de proyectos y usuarios ----------
def test_la_api_del_equipo_exige_la_puerta_de_las_herramientas():
    c = _cliente()
    assert c.get("/api/entornos/implementacion/proyectos").status_code == 403
    assert c.post("/api/entornos/implementacion/proyectos", json={"nombre": "X"}).status_code == 403
    pid = _proyecto()
    assert c.get(f"/api/entornos/implementacion/proyectos/{pid}/usuarios").status_code == 403
    assert c.post(f"/api/entornos/implementacion/proyectos/{pid}/usuarios", json={}).status_code == 403
    # Un usuario del sindicato no es "equipo": tampoco abre la API.
    uid, _ = _usuario(pid)
    c.cookies.set(COOKIE_IMPL, auth.crear_sesion("implementacion", uid, pid))
    assert c.get("/api/entornos/implementacion/proyectos").status_code == 403


def test_el_equipo_crea_proyecto_y_usuarios_y_los_administra():
    c, uid_eq = _equipo()
    API = "/api/entornos/implementacion/proyectos"
    nombre = _unico("Proyecto ")
    r = c.post(API, json={"nombre": nombre})
    assert r.status_code == 200
    pid = r.json()["proyecto"]["id"]
    assert r.json()["proyecto"]["sindicato_id"] is None
    assert c.post(API, json={"nombre": "  "}).status_code == 400
    assert c.post(API, json={"nombre": "X", "sindicato_id": 99999999}).status_code == 400
    assert nombre in [p["nombre"] for p in c.get(API).json()["proyectos"]]

    mail = f"{_unico()}@Sindicato.test"
    alta = c.post(f"{API}/{pid}/usuarios", json={"nombre": "Eva", "mail": mail, "clave_inicial": TRANSITORIA})
    assert alta.status_code == 200
    u = alta.json()["usuario"]
    assert u["mail"] == mail.lower() and u["debe_cambiar_clave"] is True and u["activo"] is True
    assert "clave_hash" not in u and TRANSITORIA not in str(alta.json())
    # Mail único por proyecto, mail válido, clave de al menos 6.
    assert c.post(f"{API}/{pid}/usuarios", json={"nombre": "Otra", "mail": mail.upper(),
                                                 "clave_inicial": TRANSITORIA}).status_code == 409
    assert c.post(f"{API}/{pid}/usuarios", json={"nombre": "N", "mail": "no-es-mail",
                                                 "clave_inicial": TRANSITORIA}).status_code == 400
    assert c.post(f"{API}/{pid}/usuarios", json={"nombre": "N", "mail": f"{_unico()}@x.test",
                                                 "clave_inicial": "123"}).status_code == 400
    assert c.post(f"{API}/{pid}/usuarios", json={"nombre": "", "mail": f"{_unico()}@x.test",
                                                 "clave_inicial": TRANSITORIA}).status_code == 400
    assert [x["mail"] for x in c.get(f"{API}/{pid}/usuarios").json()["usuarios"]] == [mail.lower()]
    assert c.get(f"{API}/99999999/usuarios").status_code == 404
    assert c.post(f"{API}/99999999/usuarios", json={"nombre": "N", "mail": "a@b.cd",
                                                    "clave_inicial": TRANSITORIA}).status_code == 404

    # La clave inicial vale para el primer ingreso (y lo manda a elegir otra).
    assert _entrar(_cliente(), mail, TRANSITORIA).headers["location"].startswith("/implementacion/cambiar-clave")

    # Restablecer: transitoria nueva al azar, una vez, y la anterior deja de valer.
    rest = c.post(f"{API}/{pid}/usuarios/{u['id']}/restablecer-clave")
    assert rest.status_code == 200 and rest.headers["cache-control"] == "no-store"
    nueva = rest.json()["clave"]
    assert len(nueva) >= 8 and nueva != TRANSITORIA
    assert _entrar(_cliente(), mail, TRANSITORIA).headers["location"].endswith("error=login")
    assert _entrar(_cliente(), mail, nueva).headers["location"].startswith("/implementacion/cambiar-clave")

    # Activar / desactivar.
    off = c.post(f"{API}/{pid}/usuarios/{u['id']}/estado", json={"activo": False})
    assert off.status_code == 200 and off.json()["usuario"]["activo"] is False
    assert _entrar(_cliente(), mail, nueva).headers["location"].endswith("error=login")
    on = c.post(f"{API}/{pid}/usuarios/{u['id']}/estado", json={"activo": True})
    assert on.json()["usuario"]["activo"] is True

    # El usuario de un proyecto no se toca por la ruta de otro (404).
    otro = _proyecto()
    assert c.post(f"{API}/{otro}/usuarios/{u['id']}/restablecer-clave").status_code == 404
    assert c.post(f"{API}/{otro}/usuarios/{u['id']}/estado", json={"activo": False}).status_code == 404

    # Todo queda en la traza, solo para el equipo.
    with db.get_session() as s:
        acciones = {e.accion for e in db.impl_eventos(s, pid, "equipo")}
        assert {"usuario_alta", "usuario_clave", "usuario_estado"} <= acciones
        assert not any(e.accion.startswith("usuario_") for e in db.impl_eventos(s, pid, "sindicato"))


def test_el_mismo_mail_puede_estar_en_dos_proyectos():
    p1, p2 = _proyecto(), _proyecto()
    mail = f"{_unico()}@compartido.test"
    _usuario(p1, mail=mail)
    _usuario(p2, mail=mail)           # no choca: la unicidad es por proyecto
    assert _entrar(_cliente(), mail).headers["location"] == "/implementacion"


# ---------- Freno por IP ----------
def test_freno_por_ip_tras_demasiados_fallos(monkeypatch):
    monkeypatch.setattr(main, "LOGIN_MAX_FALLOS", 3)
    pid = _proyecto()
    _, mail = _usuario(pid)
    c = _cliente()
    for _ in range(3):
        assert _entrar(c, mail, "mala").headers["location"].endswith("error=login")
    r = _entrar(c, mail)                                           # aun con la clave buena
    assert r.headers["location"] == "/implementacion/ingresar?error=espera"
    assert COOKIE_IMPL not in r.cookies
    assert "Demasiados intentos" in c.get("/implementacion/ingresar?error=espera").text


def test_los_intentos_con_transitoria_errada_cuentan_para_el_freno(monkeypatch):
    monkeypatch.setattr(main, "LOGIN_MAX_FALLOS", 2)
    pid = _proyecto()
    uid, _ = _usuario(pid, definitiva=False)
    token = auth.firmar_paso({"uid": uid}, minutos=10, proposito=main._PROPOSITO_CAMBIO_CLAVE_IMPL)
    c = _cliente()
    datos = {"token": token, "clave_actual": "mala", "clave": DEFINITIVA, "clave2": DEFINITIVA}
    assert c.post("/implementacion/cambiar-clave", data=datos).status_code == 400
    assert c.post("/implementacion/cambiar-clave", data=datos).status_code == 400
    assert c.post("/implementacion/cambiar-clave", data={**datos, "clave_actual": TRANSITORIA}).status_code == 429


# ---------- Demo ----------
def test_en_demo_todo_responde_404(monkeypatch):
    pid = _proyecto()
    uid, mail = _usuario(pid)
    c, _ = _equipo()
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c.cookies.set(COOKIE_IMPL, auth.crear_sesion("implementacion", uid, pid))
    for metodo, ruta, kw in [
        ("GET", "/implementacion", {}),
        ("GET", "/implementacion/ingresar", {}),
        ("POST", "/implementacion/ingresar", {"data": {"mail": mail, "clave": DEFINITIVA}}),
        ("GET", "/implementacion/cambiar-clave", {}),
        ("POST", "/implementacion/cambiar-clave", {"data": {"token": "x"}}),
        ("POST", "/implementacion/salir", {}),
        ("GET", "/api/entornos/implementacion/proyectos", {}),
        ("POST", "/api/entornos/implementacion/proyectos", {"json": {"nombre": "X"}}),
        ("GET", f"/api/entornos/implementacion/proyectos/{pid}/usuarios", {}),
    ]:
        assert c.request(metodo, ruta, **kw).status_code == 404, (metodo, ruta)


# ---------- Inventario ----------
def test_la_cookie_nueva_esta_en_el_mapa_de_roles_y_se_renueva():
    assert COOKIE_IMPL == "sesion_implementacion"
    assert main._rol_de("/implementacion/ingresar") == "implementacion"
    assert main._panel_de("/implementacion") == "/implementacion/ingresar"
    pid = _proyecto()
    _, mail = _usuario(pid)
    c = _cliente()
    _entrar(c, mail)
    antes = c.cookies.get(COOKIE_IMPL)
    r = c.get("/implementacion")
    assert r.status_code == 200 and COOKIE_IMPL in r.headers.get("set-cookie", "")
    assert antes
