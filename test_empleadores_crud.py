"""CRUD de Empresas (Empleador) en /admin -- alta/edición/baja lógica,
aislamiento por sindicato, botón de importar CUITs desde Conceptos, y que
las 4 rutas y el tab de la UI respeten el módulo "empleadores".

Correr con: .venv/Scripts/python.exe test_empleadores_crud.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, UsuarioSindicato, Concepto, Empleador
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Empleadores CRUD", slug="uom-empleadores-crud",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    otro = Sindicato(nombre="Otro Empleadores CRUD", slug="otro-empleadores-crud",
                      modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    fega = Sindicato(nombre="Fega Sin Empleadores", slug="fega-sin-empleadores",
                      modulos_habilitados=list(MODULOS_INICIALES))  # sin "empleadores"
    s.add(uom); s.add(otro); s.add(fega)
    s.commit(); s.refresh(uom); s.refresh(otro); s.refresh(fega)
    SID_UOM, SID_OTRO, SID_FEGA = uom.id, otro.id, fega.id

    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin UOM",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_OTRO, usuario="20555555550", nombre="Admin Otro",
                            clave_hash=auth.hashear_clave("otro-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_FEGA, usuario="20222222220", nombre="Admin Fega",
                            clave_hash=auth.hashear_clave("fega-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()


def _admin_client(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


admin_uom = _admin_client("20111111110", "uom-demo")
admin_otro = _admin_client("20555555550", "otro-demo")
admin_fega = _admin_client("20222222220", "fega-demo")


def test_alta_empleador_ok():
    r = admin_uom.post("/admin/empleador", data={
        "cuit": "30-111222-334", "razon_social": "Constructora Demo",
        "provincia": "Buenos Aires",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        e = s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM, Empleador.cuit == "30111222334")).first()
        assert e is not None
        assert e.razon_social == "Constructora Demo"
        assert e.activo is True
    print("OK  test_alta_empleador_ok")


def test_alta_empleador_cuit_invalido_no_crea():
    r = admin_uom.post("/admin/empleador", data={
        "cuit": "123", "razon_social": "CUIT corto",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error=cuit" in r.headers["location"]
    with Session(db.engine) as s:
        e = s.exec(select(Empleador).where(Empleador.razon_social == "CUIT corto")).first()
        assert e is None
    print("OK  test_alta_empleador_cuit_invalido_no_crea")


def test_edicion_empleador_solo_de_su_sindicato():
    with Session(db.engine) as s:
        e = s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM, Empleador.cuit == "30111222334")).first()
        eid = e.id
    # El admin de OTRO sindicato intenta editar el empleador de UOM.
    admin_otro.post("/admin/empleador", data={
        "id": str(eid), "cuit": "30111222334", "razon_social": "Nombre pisado por otro admin",
    })
    with Session(db.engine) as s:
        e = s.get(Empleador, eid)
        assert e.razon_social == "Constructora Demo", "un admin de otro sindicato no puede editar"
    # El admin dueño sí puede.
    admin_uom.post("/admin/empleador", data={
        "id": str(eid), "cuit": "30111222334", "razon_social": "Constructora Demo (renombrada)",
    })
    with Session(db.engine) as s:
        e = s.get(Empleador, eid)
        assert e.razon_social == "Constructora Demo (renombrada)"
    print("OK  test_edicion_empleador_solo_de_su_sindicato")


def test_baja_y_reactivacion_logica():
    with Session(db.engine) as s:
        e = s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM, Empleador.cuit == "30111222334")).first()
        eid = e.id
    admin_uom.post("/admin/empleador/baja", data={"id": str(eid)})
    with Session(db.engine) as s:
        assert s.get(Empleador, eid).activo is False
    admin_uom.post("/admin/empleador/alta-logica", data={"id": str(eid)})
    with Session(db.engine) as s:
        assert s.get(Empleador, eid).activo is True
    print("OK  test_baja_y_reactivacion_logica")


def test_importar_cuits_boton_agrega_y_es_idempotente():
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=SID_UOM, codigo="IMP1", nombre="Concepto importar 1",
                        tipo="descuento", remunerativo=False, cuit_empleador="30999888777"))
        s.commit()
    r1 = admin_uom.post("/admin/empleador/importar-cuits", follow_redirects=False)
    assert r1.status_code == 303
    assert "importados=1" in r1.headers["location"]
    r2 = admin_uom.post("/admin/empleador/importar-cuits", follow_redirects=False)
    assert "importados=0" in r2.headers["location"]
    with Session(db.engine) as s:
        filas = s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM, Empleador.cuit == "30999888777")).all()
        assert len(filas) == 1
    print("OK  test_importar_cuits_boton_agrega_y_es_idempotente")


def test_rutas_empleador_bloqueadas_403_sin_modulo():
    r1 = admin_fega.post("/admin/empleador", data={"cuit": "30111111111"})
    assert r1.status_code == 403
    r2 = admin_fega.post("/admin/empleador/baja", data={"id": "1"})
    assert r2.status_code == 403
    r3 = admin_fega.post("/admin/empleador/alta-logica", data={"id": "1"})
    assert r3.status_code == 403
    r4 = admin_fega.post("/admin/empleador/importar-cuits")
    assert r4.status_code == 403
    print("OK  test_rutas_empleador_bloqueadas_403_sin_modulo")


def test_admin_muestra_tab_empleadores_con_modulo():
    r = admin_uom.get("/admin")
    assert 'data-panel="empleadores"' in r.text
    print("OK  test_admin_muestra_tab_empleadores_con_modulo")


def test_admin_oculta_tab_empleadores_sin_modulo():
    r = admin_fega.get("/admin")
    assert 'data-panel="empleadores"' not in r.text
    print("OK  test_admin_oculta_tab_empleadores_sin_modulo")


if __name__ == "__main__":
    test_alta_empleador_ok()
    test_alta_empleador_cuit_invalido_no_crea()
    test_edicion_empleador_solo_de_su_sindicato()
    test_baja_y_reactivacion_logica()
    test_importar_cuits_boton_agrega_y_es_idempotente()
    test_rutas_empleador_bloqueadas_403_sin_modulo()
    test_admin_muestra_tab_empleadores_con_modulo()
    test_admin_oculta_tab_empleadores_sin_modulo()
    print("\nTodo OK — CRUD de Empleadores.")
