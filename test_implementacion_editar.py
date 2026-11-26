"""Mesa de implementación, I19: el equipo corrige una tarjeta y queda el registro
de lo que tenía antes y de quién lo cambió.

Cubre el motor (`implementacion`), el acceso a datos (`db.impl_editar_tarjeta`),
la API por HTTP y lo que la pantalla tiene que traer (leyendo el JS).

Correr con: .venv/bin/python -m pytest test_implementacion_editar.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import auth
import db
import fechas
import implementacion as im
import main
from implementacion import Actor, ErrorImpl

db.crear_tablas()

EQ = Actor("equipo", 1, "Ana (Colm3na)")
SI = Actor("sindicato", 10, "Carla (Sindicato)")
DEFINITIVA = "definitiva-2026"


def _u(prefijo="x"):
    return f"{prefijo}{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _sin_freno():
    main._intentos_impl.clear()
    yield
    main._intentos_impl.clear()


@pytest.fixture
def proy():
    with db.get_session() as s:
        yield db.impl_crear_proyecto(s, _u("Proy "), EQ).id


def _tarjeta(pid, actor=EQ, tipo="pedido", titulo="Padrón", texto="Mandanos el padrón", **kw):
    with db.get_session() as s:
        return db.impl_crear_tarjeta(s, pid, actor, tipo, titulo, texto, **kw).id


def _editar(pid, tid, actor=EQ, **campos):
    with db.get_session() as s:
        return db.impl_editar_tarjeta(s, pid, tid, actor, **campos)


def _eventos_editar(pid, tid):
    with db.get_session() as s:
        return [e for e in db.impl_eventos(s, pid, "equipo", tid) if e.accion == "editar"]


# ============================================================ motor
def test_solo_el_equipo_edita_y_una_aprobacion_resuelta_no():
    assert im.puede_editar("pedido", "abierta", "equipo")
    assert not im.puede_editar("pedido", "abierta", "sindicato")
    assert im.puede_editar("aviso", "cerrada", "equipo")
    assert im.puede_editar("aprobacion", "abierta", "equipo")
    assert not im.puede_editar("aprobacion", "aprobada", "equipo")
    assert not im.puede_editar("aprobacion", "rechazada", "equipo")


def test_acciones_de_trae_editar_calculado_por_el_servidor():
    for tipo in im.ORDEN_TIPOS:
        for estado in im.ESTADOS:
            for lado in ("equipo", "sindicato"):
                a = im.acciones_de(tipo, estado, "equipo", lado, "sindicato")
                assert "editar" in a
                assert a["editar"] == (lado == "equipo" and not im.es_inmutable(tipo, estado)
                                       and estado in im.TRANSICIONES), (tipo, estado, lado)


def test_validar_edicion_usa_las_reglas_del_alta():
    v = im.validar_edicion({"titulo": "  Nuevo  ", "texto": "Otro", "fecha_limite": "05/12/2026",
                            "etapa_id": None, "hito_id": 7})
    assert v["ok"] and v["datos"] == {"titulo": "Nuevo", "texto": "Otro", "fecha_limite": "2026-12-05",
                                      "etapa_id": None, "hito_id": 7}
    assert im.validar_edicion({"fecha_limite": ""})["datos"] == {"fecha_limite": ""}
    assert im.validar_edicion({})["datos"] == {}
    for malo in ({"titulo": ""}, {"titulo": "x" * (im.TOPE_TITULO + 1)}, {"texto": " "},
                 {"texto": "x" * (im.TOPE_TEXTO + 1)}, {"fecha_limite": "mañana"},
                 {"etapa_id": 2 ** 40}, {"hito_id": "abc"}, {"etapa_id": True}):
        assert not im.validar_edicion(malo)["ok"], malo


def test_el_evento_editar_se_lee_en_castellano():
    d = {"cambios": [{"campo": "fecha_limite"}, {"campo": "titulo"}, {"campo": "hito_id"}]}
    assert im.texto_evento("editar", d) == "corrigió la fecha límite, el título y el hito"
    assert im.texto_evento("editar", {"cambios": [{"campo": "texto"}]}) == "corrigió el texto"


# ============================================================ acceso a datos
def test_edita_y_registra_antes_y_despues(proy):
    tid = _tarjeta(proy, fecha_limite="2020-01-01")
    cod = None
    with db.get_session() as s:
        et = db.impl_etapas(s, proy)
    t = _editar(proy, tid, titulo="Padrón de afiliados", texto="Mandanos el padrón completo",
                fecha_limite="2026-12-05", etapa_id=et[1].id)
    assert t.titulo == "Padrón de afiliados" and t.fecha_limite == "2026-12-05" and t.etapa_id == et[1].id
    cod = t.codigo
    assert cod.startswith("PE")                       # el código no cambia nunca
    with db.get_session() as s:
        h = db.impl_hilo(s, proy, tid, "equipo")
    assert h["mensajes"][0].texto == "Mandanos el padrón completo"
    evs = _eventos_editar(proy, tid)
    assert len(evs) == 1
    e = evs[0]
    assert (e.actor_lado, e.actor_nombre, e.solo_equipo) == ("equipo", "Ana (Colm3na)", False)
    por_campo = {c["campo"]: c for c in e.detalle["cambios"]}
    assert set(por_campo) == {"titulo", "texto", "fecha_limite", "etapa_id"}
    assert por_campo["titulo"]["antes"] == "Padrón" and por_campo["titulo"]["despues"] == "Padrón de afiliados"
    assert por_campo["texto"]["antes"] == "Mandanos el padrón"
    assert por_campo["fecha_limite"]["antes"] == "2020-01-01" and por_campo["fecha_limite"]["despues"] == "2026-12-05"
    assert por_campo["etapa_id"]["antes"] == "" and por_campo["etapa_id"]["despues"] == et[1].nombre
    assert por_campo["etapa_id"]["despues_id"] == et[1].id


def test_quitar_la_fecha_y_la_fase(proy):
    with db.get_session() as s:
        et = db.impl_etapas(s, proy)
    tid = _tarjeta(proy, fecha_limite="2020-01-01", etapa_id=et[0].id)
    t = _editar(proy, tid, fecha_limite="", etapa_id=None)
    assert t.fecha_limite == "" and t.etapa_id is None
    c = {x["campo"]: x for x in _eventos_editar(proy, tid)[0].detalle["cambios"]}
    assert c["fecha_limite"]["despues"] == "" and c["etapa_id"]["antes"] == et[0].nombre and c["etapa_id"]["despues"] == ""


def test_si_no_cambio_nada_no_hay_evento_ni_error(proy):
    tid = _tarjeta(proy, fecha_limite="2026-12-01")
    t = _editar(proy, tid, titulo="Padrón", texto="Mandanos el padrón", fecha_limite="2026-12-01")
    assert t.titulo == "Padrón"
    assert _editar(proy, tid) is not None
    assert _eventos_editar(proy, tid) == []
    with db.get_session() as s:
        assert db.impl_ediciones(s, proy, [tid]) == {}


def test_un_campo_invalido_no_cambia_nada_atomica(proy):
    tid = _tarjeta(proy)
    with pytest.raises(ErrorImpl):
        _editar(proy, tid, titulo="Cambiado", fecha_limite="no es fecha")
    with pytest.raises(ErrorImpl):
        _editar(proy, tid, titulo="Cambiado", etapa_id=999999999)       # etapa que no existe en el proyecto
    with db.get_session() as s:
        t = db.impl_tarjeta(s, proy, tid)
    assert t.titulo == "Padrón" and _eventos_editar(proy, tid) == []


def test_etapa_o_hito_de_otro_proyecto_es_error(proy):
    with db.get_session() as s:
        otro = db.impl_crear_proyecto(s, _u("Otro "), EQ).id
        et_otro = db.impl_etapas(s, otro)[0].id
    tid = _tarjeta(proy)
    with pytest.raises(ErrorImpl):
        _editar(proy, tid, etapa_id=et_otro)
    with pytest.raises(ErrorImpl):
        _editar(proy, tid, hito_id=123456789)


def test_el_hito_tiene_que_ser_de_la_fase_elegida(proy):
    with db.get_session() as s:
        et = [(e.id, e.nombre) for e in db.impl_etapas(s, proy)]
        h = db.impl_agregar_hito(s, proy, et[0][0], "Un hito", EQ)
        hid, hcod = h.id, h.codigo
    tid = _tarjeta(proy)
    with pytest.raises(ErrorImpl):
        _editar(proy, tid, etapa_id=et[1][0], hito_id=hid)
    # solo el hito: la fase sale del hito, como al crear
    t = _editar(proy, tid, hito_id=hid)
    assert t.hito_id == hid and t.etapa_id == et[0][0]
    c = {x["campo"]: x for x in _eventos_editar(proy, tid)[0].detalle["cambios"]}
    assert c["hito_id"]["despues"].startswith(hcod) and c["etapa_id"]["despues"] == et[0][1]
    # cambiar la fase dejando el hito de la otra es un error
    with pytest.raises(ErrorImpl):
        _editar(proy, tid, etapa_id=et[1][0])
    t = _editar(proy, tid, etapa_id=et[1][0], hito_id=None)
    assert t.etapa_id == et[1][0] and t.hito_id is None


def test_solo_el_equipo_y_la_aprobacion_resuelta_no(proy):
    tid = _tarjeta(proy)
    with pytest.raises(ErrorImpl) as e:
        _editar(proy, tid, actor=SI, titulo="x")
    assert e.value.codigo == "sin_permiso"
    ap = _tarjeta(proy, actor=SI, tipo="aprobacion", titulo="Aprobá", texto="x")
    assert _editar(proy, ap, titulo="Aprobá esto").titulo == "Aprobá esto"        # abierta: sí
    with db.get_session() as s:
        db.impl_resolver_aprobacion(s, proy, ap, EQ, True)
    with pytest.raises(ErrorImpl) as e:
        _editar(proy, ap, titulo="Otra vez")
    assert e.value.codigo == "inmutable"
    assert _editar(proy, 987654321) is None


def test_edita_tarjetas_cerradas_y_avisos(proy):
    av = _tarjeta(proy, tipo="aviso", titulo="Aviso", texto="Texto")
    assert _editar(proy, av, titulo="Aviso corregido").titulo == "Aviso corregido"
    pe = _tarjeta(proy)
    with db.get_session() as s:
        db.impl_responder(s, proy, pe, SI, texto="hecho", estado_nuevo="cerrada")
    assert _editar(proy, pe, titulo="Cerrada y corregida").titulo == "Cerrada y corregida"


def test_las_menciones_se_recalculan(proy):
    a = _tarjeta(proy, titulo="Primera", texto="a")
    b = _tarjeta(proy, titulo="Segunda", texto="b")
    with db.get_session() as s:
        ca, cb = db.impl_tarjeta(s, proy, a).codigo, db.impl_tarjeta(s, proy, b).codigo
    t = _tarjeta(proy, titulo="Tercera", texto=f"Ver {ca}")

    def rels():
        with db.get_session() as s:
            return {(r["codigo"], r["texto"]) for r in db.impl_relacionadas(s, proy, "tarjeta", t, "equipo")}
    assert (ca, "menciona") in rels()
    _editar(proy, t, texto=f"Ahora ver {cb}")
    r = rels()
    assert (cb, "menciona") in r and (ca, "menciona") not in r
    # lo que se nombra en el título también cuenta, y lo vinculado con «Responder con…» no se toca
    with db.get_session() as s:
        db.impl_relacionar(s, proy, "tarjeta", t, "tarjeta", a, "responde", EQ)
        s.commit()
    _editar(proy, t, titulo=f"Tercera ({ca})", texto="sin códigos")
    r = rels()
    assert (ca, "menciona") in r and (cb, "menciona") not in r
    assert any(x[0] == ca and x[1] != "menciona" for x in r)          # la de «responde» sigue


def test_una_mencion_que_hizo_otro_mensaje_no_se_borra(proy):
    a = _tarjeta(proy, titulo="Primera", texto="a")
    with db.get_session() as s:
        ca = db.impl_tarjeta(s, proy, a).codigo
    t = _tarjeta(proy, titulo="Tercera", texto=f"Ver {ca}")
    with db.get_session() as s:
        db.impl_responder(s, proy, t, EQ, texto=f"Recuerden {ca}")
    _editar(proy, t, texto="sin códigos")
    with db.get_session() as s:
        assert any(r["codigo"] == ca for r in db.impl_relacionadas(s, proy, "tarjeta", t, "equipo"))


def test_impl_ediciones_da_la_ultima(proy):
    tid = _tarjeta(proy)
    _editar(proy, tid, titulo="Uno")
    _editar(proy, tid, titulo="Dos")
    with db.get_session() as s:
        cuando, quien = db.impl_ediciones(s, proy, [tid])[tid]
    assert quien == "Ana (Colm3na)" and cuando


def test_la_traza_de_edicion_es_inmutable(proy):
    tid = _tarjeta(proy)
    _editar(proy, tid, titulo="Uno")
    with db.get_session() as s:
        ev = s.exec(select(db.ImplEvento).where(db.ImplEvento.accion == "editar",
                                                db.ImplEvento.tarjeta_id == tid)).first()
        ev.detalle = {}
        s.add(ev)
        with pytest.raises(Exception):
            s.commit()


# ============================================================ API
def _api(pid, ruta=""):
    return f"/api/implementacion/p/{pid}/{ruta}".rstrip("/")


def _cliente_sindicato(pid):
    mail = f"{_u()}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, "Carla Sindicato", mail, "transitoria1", EQ)
        db.impl_usuario_cambiar_clave(s, u.id, "transitoria1", DEFINITIVA)
    c = TestClient(main.app, follow_redirects=False)
    r = c.post("/implementacion/ingresar", data={"mail": mail, "clave": DEFINITIVA})
    assert r.headers["location"] == "/implementacion"
    return c


def _cliente_equipo():
    usuario = _u("eq")
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario, email="",
                                 clave_hash=auth.hashear_clave("x" * 12),
                                 debe_cambiar_clave=False, debe_completar_datos=False)
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    return c


def _mundo():
    with db.get_session() as s:
        pid = db.impl_crear_proyecto(s, _u("Proy "), EQ).id
    return pid, _cliente_equipo(), _cliente_sindicato(pid)


def _crear(c, pid, **extra):
    datos = {"tipo": "pedido", "titulo": "Un título", "texto": "Un texto", **extra}
    r = c.post(_api(pid, "tarjetas"), data=datos)
    assert r.status_code == 200, r.text
    return r.json()["tarjeta"]


def test_api_el_equipo_edita_y_los_dos_lados_ven_el_registro():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, fecha_limite="2020-01-01")
    assert t["vencida"] is True and t["editada"] is False
    r = eq.post(_api(pid, f"tarjetas/{t['id']}/editar"),
                json={"titulo": "Título corregido", "texto": "Texto corregido", "fecha_limite": "2030-05-12"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tarjeta"]["titulo"] == "Título corregido" and d["tarjeta"]["vencida"] is False
    assert d["tarjeta"]["editada"] is True and d["tarjeta"]["editada_por"] == d["eventos"][-1]["quien"]
    assert d["acciones"]["editar"] is True and d["tarjeta"]["codigo"] == t["codigo"]
    assert d["mensajes"][0]["texto"] == "Texto corregido"
    for c in (eq, sin):                                     # el sindicato también VE qué cambió
        det = c.get(_api(pid, f"tarjetas/{t['id']}")).json()
        ev = [e for e in det["eventos"] if e["que"] == "editar"]
        assert len(ev) == 1 and ev[0]["lado"] == "equipo" and ev[0]["cuando"]
        cambios = {x["campo"]: x for x in ev[0]["cambios"]}
        assert cambios["titulo"]["antes"] == "Un título"
        assert cambios["texto"]["antes"] == "Un texto" and cambios["texto"]["despues"] == "Texto corregido"
        assert cambios["fecha_limite"]["antes"] == "2020-01-01" and cambios["fecha_limite"]["despues"] == "2030-05-12"
        assert ev[0]["texto"].startswith("corrigió")
        assert det["tarjeta"]["editada"] is True
        lista = c.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"]
        assert [x["editada"] for x in lista if x["id"] == t["id"]] == [True]


def test_api_sin_cambios_no_hay_evento():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    r = eq.post(_api(pid, f"tarjetas/{t['id']}/editar"), json={"titulo": "Un título", "fecha_limite": ""})
    assert r.status_code == 200 and r.json()["tarjeta"]["editada"] is False
    assert not [e for e in r.json()["eventos"] if e["que"] == "editar"]


def test_api_permisos_y_aislamiento():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    ruta = _api(pid, f"tarjetas/{t['id']}/editar")
    assert sin.post(ruta, json={"titulo": "x"}).status_code == 403
    assert sin.get(_api(pid, f"tarjetas/{t['id']}")).json()["acciones"]["editar"] is False
    assert TestClient(main.app).post(ruta, json={"titulo": "x"}).status_code in (401, 403, 404)
    assert eq.post(_api(pid, "tarjetas/987654321/editar"), json={"titulo": "x"}).status_code == 404
    pid2, eq2, sin2 = _mundo()
    assert sin2.post(ruta, json={"titulo": "x"}).status_code == 404            # proyecto ajeno: 404
    assert sin2.post(_api(pid2, f"tarjetas/{t['id']}/editar"), json={"titulo": "x"}).status_code in (403, 404)
    assert eq2.post(_api(pid2, f"tarjetas/{t['id']}/editar"), json={"titulo": "x"}).status_code == 404
    assert sin.get(_api(pid, f"tarjetas/{t['id']}")).json()["tarjeta"]["titulo"] == "Un título"


def test_api_campos_invalidos_son_400_y_no_cambian_nada():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    ruta = _api(pid, f"tarjetas/{t['id']}/editar")
    for cuerpo in ({"titulo": ""}, {"titulo": "x" * 141}, {"texto": ""}, {"titulo": None}, {"titulo": 5},
                   {"fecha_limite": "ayer"}, {"fecha_limite": 7}, {"etapa_id": 2 ** 40}, {"etapa_id": "a"},
                   {"hito_id": 99999999}, {"etapa_id": 99999999}, {"titulo": "ok", "fecha_limite": "xx"}):
        r = eq.post(ruta, json=cuerpo)
        assert r.status_code == 400, (cuerpo, r.status_code, r.text)
    assert eq.post(ruta, data="no es json").status_code in (400, 422)
    det = eq.get(_api(pid, f"tarjetas/{t['id']}")).json()
    assert det["tarjeta"]["titulo"] == "Un título" and det["tarjeta"]["editada"] is False


def test_api_aprobacion_resuelta_409_y_la_abierta_se_edita():
    pid, eq, sin = _mundo()
    ap = _crear(sin, pid, tipo="aprobacion", titulo="Aprobá", texto="x")
    ruta = _api(pid, f"tarjetas/{ap['id']}/editar")
    assert eq.post(ruta, json={"titulo": "Aprobá esto"}).status_code == 200
    assert eq.post(_api(pid, f"tarjetas/{ap['id']}/aprobacion"), json={"aprobar": True}).status_code == 200
    r = eq.post(ruta, json={"titulo": "Otra vez"})
    assert r.status_code == 409
    assert eq.get(_api(pid, f"tarjetas/{ap['id']}")).json()["acciones"]["editar"] is False


def test_api_quitar_fecha_fase_y_hito_con_null():
    pid, eq, sin = _mundo()
    plan = eq.get(_api(pid, "plan")).json()["etapas"]
    t = _crear(sin, pid, etapa_id=plan[0]["id"], fecha_limite="2030-01-01")
    r = eq.post(_api(pid, f"tarjetas/{t['id']}/editar"), json={"fecha_limite": "", "etapa_id": None, "hito_id": None})
    assert r.status_code == 200
    tj = r.json()["tarjeta"]
    assert tj["fecha_limite"] == "" and tj["etapa_id"] is None and tj["vencida"] is False


def test_api_resumen_trae_el_hoy_del_servidor():
    pid, eq, sin = _mundo()
    for c in (eq, sin):
        assert c.get(_api(pid, "resumen")).json()["hoy"] == fechas.hoy_texto()


def test_api_exportaciones_siguen_andando_con_ediciones():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    eq.post(_api(pid, f"tarjetas/{t['id']}/editar"), json={"titulo": "Corregido"})
    for ruta in ("exportar.zip", "aprobaciones.csv"):
        r = eq.get(_api(pid, ruta))
        assert r.status_code == 200, (ruta, r.status_code)


# ============================================================ pantalla (lee el JS)
JS = Path("static/implementacion/mesa.js")
CSS = Path("static/implementacion/mesa.css")


def _js():
    js = JS.read_text(encoding="utf-8")
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


def test_la_pantalla_ofrece_editar_solo_si_acciones_lo_dice():
    js = _js()
    assert "acc.editar" in js and "tarjetas/' + t.id + '/editar'" in js
    assert "Editar" in js and "Guardar cambios" in js and "Cancelar" in js
    assert "Ver el texto anterior" in js and "'Editada'" in js
    assert "e.cambios" in js and "lineaCambio" in js


def test_la_pantalla_avisa_la_fecha_pasada_con_el_hoy_del_servidor():
    js = _js()
    assert "Esa fecha ya pasó: la tarjeta va a nacer vencida." in js
    assert "res.hoy" in js
    assert "new Date()" not in js.split("function fechaNum")[0].split("function vistaNueva")[1] if "function vistaNueva" in js else True


def test_el_codigo_de_edicion_no_arma_html_con_datos():
    js = _js()
    desde = js.index("function formEditar")
    cuerpo = js[js.index("function fechaNum"):js.index("function adjunto(a)")]
    assert "innerHTML" not in cuerpo and "insertAdjacentHTML" not in cuerpo
    assert desde > 0


def test_el_css_tiene_lo_de_la_edicion():
    css = CSS.read_text(encoding="utf-8")
    for clase in (".ed-form", ".fecha-pasada", ".ed-antes", ".chip.editada"):
        assert clase in css, clase


# ============================================================ QA independiente (I19)
def test_qa_una_tarjeta_con_fase_y_hito_incoherentes_corrige_su_titulo():
    """El alta admite una fase y un hito de otra fase; esa tarjeta no puede quedar
    sin poder editarse (el título, el texto o la fecha) por un par que el pedido no toca."""
    pid, eq, _sin = _mundo()
    with db.get_session() as s:
        e1, e2 = [e.id for e in db.impl_etapas(s, pid)][:2]
        h = db.impl_agregar_hito(s, pid, e1, "Un hito", EQ).id
    r = eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "a", "texto": "b",
                                            "etapa_id": e2, "hito_id": h})
    assert r.status_code == 200, r.text
    tid = r.json()["tarjeta"]["id"]
    r = eq.post(_api(pid, f"tarjetas/{tid}/editar"), json={"titulo": "solo el título", "etapa_id": e2, "hito_id": h})
    assert r.status_code == 200, r.text
    assert r.json()["tarjeta"]["titulo"] == "solo el título"
    # tocar el par sí exige coherencia
    r = eq.post(_api(pid, f"tarjetas/{tid}/editar"), json={"hito_id": None})
    assert r.status_code == 200
    r = eq.post(_api(pid, f"tarjetas/{tid}/editar"), json={"etapa_id": e2, "hito_id": h})
    assert r.status_code == 400


def test_qa_el_evento_de_creacion_se_lee_por_codigo_y_no_por_numero():
    assert im.texto_evento("crear", {"numero": 1, "codigo": "PE0001"}) == "creó la tarjeta PE0001"
    assert im.texto_evento("crear", {"numero": 3}) == "creó la tarjeta #3"      # evento viejo, sin código
    pid, eq, _sin = _mundo()
    t = _crear(eq, pid)
    ev = eq.get(_api(pid, f"tarjetas/{t['id']}")).json()["eventos"]
    assert ev[0]["texto"] == f"creó la tarjeta {t['codigo']}"


def test_qa_el_historial_no_muestra_la_clave_tecnica_de_la_accion():
    js = _js()
    assert "h('b', null, e.que" not in js and "h('b', null, 'editar')" not in js
    assert "e.quien || 'Alguien'" in js
