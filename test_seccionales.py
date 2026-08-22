"""Seccionales del sindicato: CRUD de admin, asignación opcional en el
alta/edición de trabajador, y qué pasa con los trabajadores cuando se
borra la seccional que tenían asignada.

Correr con: .venv/Scripts/python.exe test_seccionales.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, Seccional
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Seccionales", slug="uom-seccionales")
    fega = Sindicato(nombre="Fega Seccionales", slug="fega-seccionales")
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id
    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

admin_client = TestClient(main.app)
admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})


def test_alta_seccional_desde_admin():
    r = admin_client.post("/admin/seccional", data={
        "nombre": "Seccional Norte", "direccion": "Av. Siempreviva 742",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sec = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_UOM)).first()
        assert sec is not None
        assert sec.nombre == "Seccional Norte"
    print("OK  test_alta_seccional_desde_admin")


def test_edicion_seccional():
    with Session(db.engine) as s:
        sec = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_UOM)).first()
        sec_id = sec.id
    r = admin_client.post("/admin/seccional", data={
        "id": str(sec_id), "nombre": "Seccional Norte (renombrada)", "direccion": "Otra dirección",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sec = s.get(Seccional, sec_id)
        assert sec.nombre == "Seccional Norte (renombrada)"
    print("OK  test_edicion_seccional")


def test_alta_trabajador_con_seccional():
    with Session(db.engine) as s:
        sec = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_UOM)).first()
        sec_id = sec.id
    admin_client.post("/admin/trabajador", data={
        "cuil": "20111111119", "nombre": "Juan Pérez", "seccional_id": str(sec_id),
    })
    with Session(db.engine) as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "20111111119")).first()
        assert t.seccional_id == sec_id
    print("OK  test_alta_trabajador_con_seccional")


def test_alta_trabajador_sin_seccional_es_opcional():
    admin_client.post("/admin/trabajador", data={"cuil": "27222222224", "nombre": "Ana López"})
    with Session(db.engine) as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "27222222224")).first()
        assert t.seccional_id is None
    print("OK  test_alta_trabajador_sin_seccional_es_opcional")


def test_no_se_puede_asignar_seccional_de_otro_sindicato():
    with db.get_session() as s:
        s.add(Seccional(sindicato_id=SID_FEGA, nombre="Seccional de Fega"))
        s.commit()
    with Session(db.engine) as s:
        sec_fega = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_FEGA)).first()
        sec_fega_id = sec_fega.id
    admin_client.post("/admin/trabajador", data={
        "cuil": "20333333336", "nombre": "Pedro Gómez", "seccional_id": str(sec_fega_id),
    })
    with Session(db.engine) as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "20333333336")).first()
        assert t.seccional_id is None, "no debe poder asignar una seccional de otro sindicato"
    print("OK  test_no_se_puede_asignar_seccional_de_otro_sindicato")


def test_borrar_seccional_deja_a_los_trabajadores_sin_asignar():
    with Session(db.engine) as s:
        sec = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_UOM)).first()
        sec_id = sec.id
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "20111111119")).first()
        assert t.seccional_id == sec_id  # confirma el estado previo al borrado

    admin_client.post("/admin/seccional/borrar", data={"id": sec_id})

    with Session(db.engine) as s:
        assert s.get(Seccional, sec_id) is None
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "20111111119")).first()
        assert t.seccional_id is None, "el trabajador debe quedar sin seccional, no bloquear el borrado"
    print("OK  test_borrar_seccional_deja_a_los_trabajadores_sin_asignar")


def test_admin_no_edita_seccional_de_otro_sindicato():
    with Session(db.engine) as s:
        sec_fega = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_FEGA)).first()
        sec_fega_id = sec_fega.id
    admin_client.post("/admin/seccional", data={
        "id": str(sec_fega_id), "nombre": "Hackeada por admin de UOM", "direccion": "",
    })
    with Session(db.engine) as s:
        sec_fega = s.get(Seccional, sec_fega_id)
        assert sec_fega.nombre != "Hackeada por admin de UOM"
    print("OK  test_admin_no_edita_seccional_de_otro_sindicato")


if __name__ == "__main__":
    test_alta_seccional_desde_admin()
    test_edicion_seccional()
    test_alta_trabajador_con_seccional()
    test_alta_trabajador_sin_seccional_es_opcional()
    test_no_se_puede_asignar_seccional_de_otro_sindicato()
    test_borrar_seccional_deja_a_los_trabajadores_sin_asignar()
    test_admin_no_edita_seccional_de_otro_sindicato()
    print("\nTodo OK — seccionales.")
