"""Borrador de tipo de trámite (SDN, 2026-10-19): un formulario guardado a
medias, sin exigir campos ni área, inactivo y con la marca `borrador`; al
publicarlo rigen todas las exigencias del alta y la marca se va. El afiliado
nunca ve un borrador.

Correr con: .venv/bin/python -m pytest test_tramites_borrador.py -q
"""
import json

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, TipoTramite, Seccional, Area
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Borrador", slug="uom-borrador",
                    modulos_habilitados=list(MODULOS_INICIALES) + ["tramites", "notificaciones"])
    s.add(uom); s.commit(); s.refresh(uom)
    SID = uom.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111120", nombre="Admin UOM",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID, cuil="20111111112", activo=True, registrado=True))
    db.guardar_datos_personales(s, "20111111112", nombre="Juan")
    sec = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(sec); s.commit(); s.refresh(sec)
    area = Area(sindicato_id=SID, seccional_id=sec.id, nombre="Acción Social")
    s.add(area); s.commit(); s.refresh(area)
    AREA = area.id

admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": "20111111120", "clave": "uom-demo"})


def _afiliado():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident="20111111112"))
    c.cookies.set("cuil_trab", "20111111112")
    return c


def _tipo(codigo):
    with Session(db.engine) as s:
        return s.exec(select(TipoTramite).where(TipoTramite.sindicato_id == SID,
                                                TipoTramite.codigo == codigo)).first()


def test_borrador_se_guarda_sin_campos_ni_area_y_nace_inactivo():
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Kit escolar", "codigo": "KIT-B1", "campos_json": "[]", "accion": "borrador",
    }, follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    t = _tipo("KIT-B1")
    assert t is not None and t.borrador and not t.activo and t.area_destino_default_id is None


def test_borrador_conserva_los_campos_sin_etiqueta():
    campos = [{"etiqueta": "Nombre del hijo/a", "tipo_dato": "texto"},
              {"etiqueta": "", "tipo_dato": "numero"}]
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Kit escolar", "codigo": "KIT-B2", "campos_json": json.dumps(campos), "accion": "borrador",
    }, follow_redirects=False)
    assert r.status_code == 303
    t = db.tipo_tramite_por_id(_tipo("KIT-B2").id)
    assert [c["etiqueta"] for c in t["campos"]] == ["Nombre del hijo/a", ""]
    assert t["borrador"] is True


def test_publicar_exige_campos_con_etiqueta_y_area():
    # sin área: rechazado
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Kit", "codigo": "KIT-P1",
        "campos_json": json.dumps([{"etiqueta": "Nombre", "tipo_dato": "texto"}]),
    }, follow_redirects=False)
    assert "error=sindestino" in r.headers["location"]
    # con área pero solo campos sin etiqueta: rechazado (se descartan y no queda ninguno)
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Kit", "codigo": "KIT-P2", "area_destino_default_id": str(AREA),
        "campos_json": json.dumps([{"etiqueta": "", "tipo_dato": "texto"}]),
    }, follow_redirects=False)
    assert "error=campos" in r.headers["location"]
    assert _tipo("KIT-P1") is None and _tipo("KIT-P2") is None


def test_el_afiliado_no_ve_el_borrador_y_si_lo_publicado():
    admin.post("/admin/tramite-tipo", data={
        "titulo": "Solo borrador", "codigo": "KIT-B3", "accion": "borrador",
        "campos_json": json.dumps([{"etiqueta": "Nombre", "tipo_dato": "texto"}]),
    }, follow_redirects=False)
    tipos = _afiliado().get("/api/tramites/tipos").json()["tipos"]
    assert "KIT-B3" not in [t["codigo"] for t in tipos]
    # publicar el borrador: con área y campos, la marca se va y queda activo
    tid = _tipo("KIT-B3").id
    r = admin.post("/admin/tramite-tipo", data={
        "id": str(tid), "titulo": "Ya publicado", "codigo": "KIT-B3", "area_destino_default_id": str(AREA),
        "campos_json": json.dumps([{"etiqueta": "Nombre", "tipo_dato": "texto"}]),
    }, follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    t = _tipo("KIT-B3")
    assert not t.borrador and t.activo and t.area_destino_default_id == AREA
    tipos = _afiliado().get("/api/tramites/tipos").json()["tipos"]
    assert "KIT-B3" in [t["codigo"] for t in tipos]


def test_volver_a_guardar_como_borrador_un_publicado_lo_saca_de_la_vista():
    tid = _tipo("KIT-B3").id
    admin.post("/admin/tramite-tipo", data={
        "id": str(tid), "titulo": "Ya publicado", "codigo": "KIT-B3", "accion": "borrador",
        "campos_json": json.dumps([{"etiqueta": "Nombre", "tipo_dato": "texto"}]),
    }, follow_redirects=False)
    t = _tipo("KIT-B3")
    assert t.borrador and not t.activo
    assert "KIT-B3" not in [x["codigo"] for x in _afiliado().get("/api/tramites/tipos").json()["tipos"]]


def test_el_panel_lista_el_estado_borrador_y_la_hoja_de_trabajo():
    html = admin.get("/admin").text
    assert ">borrador<" in html
    for pieza in ('id="tt-riel"', 'class="ct-area"', 'name="accion" value="borrador"', 'id="tt-estado"'):
        assert pieza in html, pieza
