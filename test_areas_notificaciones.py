"""Notificaciones acotadas por seccional -- Fase 6 de SPRINT_AREAS.md.

Decisión 8: notificar usa el MISMO alcance que trámites. Una sola regla de
alcance para todo el panel, no una por módulo.

Lo que más importa acá: que el PREVIEW y el ENVÍO cuenten lo mismo. Si el
preview contara de más, el admin vería un número y saldría otro -- y el
error sería silencioso, porque nadie compara los dos.

Correr con: python -m pytest test_areas_notificaciones.py -q
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                Trabajador, Notificacion, NotificacionDestinatario)
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Notif", slug="uom-notif", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    rosario = Seccional(sindicato_id=SID, nombre="Rosario")
    cordoba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(central); s.add(rosario); s.add(cordoba)
    s.commit(); s.refresh(central); s.refresh(rosario); s.refresh(cordoba)
    SEC_CENTRAL, SEC_ROSARIO, SEC_CORDOBA = central.id, rosario.id, cordoba.id

    comunicacion = Area(sindicato_id=SID, nombre="Comunicación")
    s.add(comunicacion); s.commit(); s.refresh(comunicacion)
    AREA = comunicacion.id
    s.add(PermisoArea(area_id=AREA, seccion="notificaciones"))

    def _u(cuil, nombre, **kw):
        u = UsuarioSindicato(sindicato_id=SID, usuario=cuil, nombre=nombre,
                             clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False, **kw)
        s.add(u); return u
    jefa = _u("20111111110", "Jefa", es_super_admin=True, seccional_id=SEC_CENTRAL)
    rosa = _u("20111111111", "Rosa", area_id=AREA, seccional_id=SEC_ROSARIO)
    caro = _u("20111111112", "Caro", area_id=AREA, seccional_id=SEC_CENTRAL)
    s.commit()
    for u in (jefa, rosa, caro):
        s.refresh(u)
    U_JEFA, U_ROSA, U_CARO = jefa.id, rosa.id, caro.id

    # 2 trabajadores en Rosario, 3 en Córdoba.
    for cuil, sec in [("20999999990", SEC_ROSARIO), ("20999999991", SEC_ROSARIO),
                      ("20999999992", SEC_CORDOBA), ("20999999993", SEC_CORDOBA),
                      ("20999999994", SEC_CORDOBA)]:
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, nombre="T " + cuil[-2:],
                         activo=True, registrado=True, seccional_id=sec,
                         provincia="Santa Fe"))
    s.commit()

TODOS = ["20999999990", "20999999991", "20999999992", "20999999993", "20999999994"]
DE_ROSARIO = {"20999999990", "20999999991"}


def _cli(cuil):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": cuil, "clave": "x"}, follow_redirects=False)
    assert r.status_code == 303
    return c


# ---------- El recorte ----------

def test_sin_usuario_no_hay_recorte():
    """El comportamiento de siempre queda intacto para los llamados internos
    que no representan a una persona."""
    assert set(db.resolver_destinatarios(SID, "cuil", TODOS)) == set(TODOS)
    print("OK  test_sin_usuario_no_hay_recorte")


def test_el_super_admin_alcanza_a_todos():
    assert set(db.resolver_destinatarios(SID, "cuil", TODOS, usuario_id=U_JEFA)) == set(TODOS)
    print("OK  test_el_super_admin_alcanza_a_todos")


def test_usuario_de_area_solo_alcanza_su_seccional():
    alcanzados = set(db.resolver_destinatarios(SID, "cuil", TODOS, usuario_id=U_ROSA))
    assert alcanzados == DE_ROSARIO, "Rosa es de Rosario: los de Córdoba no le corresponden"
    print("OK  test_usuario_de_area_solo_alcanza_su_seccional")


def test_ve_todas_levanta_el_recorte():
    """Caro está en Sede Central, que tiene ve_todas: misma área que Rosa,
    alcance distinto."""
    assert set(db.resolver_destinatarios(SID, "cuil", TODOS, usuario_id=U_CARO)) == set(TODOS)
    print("OK  test_ve_todas_levanta_el_recorte")


def test_el_recorte_vale_para_todos_los_criterios():
    """No alcanza con recortar el criterio "cuil": por provincia o por
    seccional se podría llegar igual a gente de otra seccional."""
    por_provincia = set(db.resolver_destinatarios(SID, "provincia", ["Santa Fe"], usuario_id=U_ROSA))
    assert por_provincia == DE_ROSARIO
    # Pidiendo explícitamente OTRA seccional no se la alcanza igual.
    por_seccional = db.resolver_destinatarios(SID, "seccional", [str(SEC_CORDOBA)], usuario_id=U_ROSA)
    assert por_seccional == [], "pedir Córdoba desde Rosario no alcanza a nadie"
    print("OK  test_el_recorte_vale_para_todos_los_criterios")


# ---------- Preview vs envío ----------

def test_el_preview_cuenta_lo_mismo_que_sale():
    """Si estos dos números difieren, el admin ve uno y sale otro -- y el
    error es silencioso, porque nadie los compara."""
    c = _cli("20111111111")   # Rosa
    r = c.post("/admin/notificacion/preview", data={"criterio": "cuil", "valores": TODOS})
    assert r.status_code == 200
    cantidad_preview = r.json()["cantidad"]

    r = c.post("/admin/notificacion", data={
        "remitente": "Rosa", "texto": "Aviso de prueba",
        "criterio": "cuil", "valores": TODOS}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        n = s.exec(select(Notificacion).where(
            Notificacion.sindicato_id == SID).order_by(Notificacion.id.desc())).first()
        dests = {d.cuil for d in s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == n.id)).all()}
    assert cantidad_preview == len(dests) == 2, f"preview={cantidad_preview}, envío={len(dests)}"
    assert dests == DE_ROSARIO
    print("OK  test_el_preview_cuenta_lo_mismo_que_sale")


def test_la_notificacion_del_super_admin_llega_a_todos():
    c = _cli("20111111110")
    r = c.post("/admin/notificacion", data={
        "remitente": "Sindicato", "texto": "Para todos",
        "criterio": "cuil", "valores": TODOS}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        n = s.exec(select(Notificacion).where(
            Notificacion.sindicato_id == SID).order_by(Notificacion.id.desc())).first()
        dests = {d.cuil for d in s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == n.id)).all()}
    assert dests == set(TODOS)
    print("OK  test_la_notificacion_del_super_admin_llega_a_todos")


# ---------- El helper de alcance ----------

def test_cuiles_alcanzados_es_la_misma_regla_que_los_tramites():
    assert db.cuiles_alcanzados(SID, U_JEFA) is None, "Super Admin: sin recorte"
    assert db.cuiles_alcanzados(SID, U_CARO) is None, "ve_todas: sin recorte"
    assert db.cuiles_alcanzados(SID, U_ROSA) == DE_ROSARIO
    print("OK  test_cuiles_alcanzados_es_la_misma_regla_que_los_tramites")


def test_usuario_sin_seccional_no_alcanza_a_nadie():
    """Falla cerrado, igual que en trámites."""
    with db.get_session() as s:
        u = UsuarioSindicato(sindicato_id=SID, usuario="20111111119", nombre="Sin seccional",
                             clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False,
                             area_id=AREA)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    assert db.cuiles_alcanzados(SID, uid) == set()
    assert db.resolver_destinatarios(SID, "cuil", TODOS, usuario_id=uid) == []
    print("OK  test_usuario_sin_seccional_no_alcanza_a_nadie")


if __name__ == "__main__":
    test_sin_usuario_no_hay_recorte()
    test_el_super_admin_alcanza_a_todos()
    test_usuario_de_area_solo_alcanza_su_seccional()
    test_ve_todas_levanta_el_recorte()
    test_el_recorte_vale_para_todos_los_criterios()
    test_el_preview_cuenta_lo_mismo_que_sale()
    test_la_notificacion_del_super_admin_llega_a_todos()
    test_cuiles_alcanzados_es_la_misma_regla_que_los_tramites()
    test_usuario_sin_seccional_no_alcanza_a_nadie()
    print("\nTodos los tests de notificaciones por seccional pasaron.")
