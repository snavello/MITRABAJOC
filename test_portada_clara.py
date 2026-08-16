"""Fase B del rediseño visual: Sindicato.portada_clara -- opción real por
sindicato (elegida por el admin de plataforma), default False para que
ningún sindicato existente cambie de aspecto el día del deploy.

Correr con: .venv/Scripts/python.exe test_portada_clara.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
from db import Sindicato
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    # Sindicato dado de alta "a mano" (fuera del form de plataforma), como
    # simulación de un sindicato que ya existía antes de esta fase -- debe
    # quedar en False sin que nadie lo toque (grandfathering).
    previo = Sindicato(nombre="Sindicato Previo Portada", slug="previo-portada",
                        color_base="#0f1b2d")
    s.add(previo); s.commit(); s.refresh(previo)
    SID_PREVIO = previo.id

plataforma_client = TestClient(main.app)
plataforma_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def _datos_base(**overrides):
    datos = {
        "nombre": "Sindicato Test Portada Clara", "descripcion": "", "cuit": "",
        "direccion": "", "mail": "", "telefonos": "", "autoridad": "", "cargo_autoridad": "",
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
        "color_base": "#0f1b2d",
    }
    datos.update(overrides)
    return datos


def test_grandfathering_sindicato_previo_queda_en_falso():
    marca = db.marca_sindicato(SID_PREVIO)
    assert marca["portada_clara"] is False
    print("OK  test_grandfathering_sindicato_previo_queda_en_falso")


def test_alta_sin_tildar_portada_clara_queda_en_falso():
    r = plataforma_client.post("/plataforma/sindicato", data=_datos_base(), follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Portada Clara")).first()
        assert sind is not None
        assert sind.portada_clara is False
    print("OK  test_alta_sin_tildar_portada_clara_queda_en_falso")


def test_alta_tildando_portada_clara_queda_en_true():
    r = plataforma_client.post("/plataforma/sindicato", data=_datos_base(
        nombre="Sindicato Test Portada Clara 2", portada_clara="true",
    ), follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Portada Clara 2")).first()
        assert sind.portada_clara is True
    print("OK  test_alta_tildando_portada_clara_queda_en_true")


def test_edicion_cambia_portada_clara():
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Portada Clara")).first()
        sid = sind.id
        assert sind.portada_clara is False

    r = plataforma_client.post("/plataforma/sindicato/editar", data=_datos_base(
        id=sid, nombre="Sindicato Test Portada Clara", portada_clara="true",
    ), follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.get(Sindicato, sid)
        assert sind.portada_clara is True

    # Destildar en una edición posterior vuelve a False (el checkbox no
    # tildado no manda el campo -- Form(False) cubre la ausencia).
    r = plataforma_client.post("/plataforma/sindicato/editar", data=_datos_base(
        id=sid, nombre="Sindicato Test Portada Clara",
    ), follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.get(Sindicato, sid)
        assert sind.portada_clara is False
    print("OK  test_edicion_cambia_portada_clara")


def test_marca_sindicato_expone_portada_clara():
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Portada Clara 2")).first()
        sid = sind.id
    marca = db.marca_sindicato(sid)
    assert marca["portada_clara"] is True
    print("OK  test_marca_sindicato_expone_portada_clara")


# ---------- admin_portada_clara: independiente de portada_clara ----------

def test_admin_portada_clara_independiente_de_la_del_trabajador():
    # Trabajador oscuro (no tildado), admin claro (tildado) en la misma alta.
    r = plataforma_client.post("/plataforma/sindicato", data=_datos_base(
        nombre="Sindicato Test Admin Portada Clara", admin_portada_clara="true",
    ), follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Admin Portada Clara")).first()
        assert sind.portada_clara is False        # trabajador: sin tocar
        assert sind.admin_portada_clara is True    # admin: tildado
    marca = db.marca_sindicato(sind.id)
    assert marca["admin_portada_clara"] is True
    print("OK  test_admin_portada_clara_independiente_de_la_del_trabajador")


def test_edicion_cambia_admin_portada_clara_sin_tocar_la_del_trabajador():
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Admin Portada Clara")).first()
        sid = sind.id

    # Edición: tilda portada_clara (trabajador) pero destilda admin_portada_clara.
    r = plataforma_client.post("/plataforma/sindicato/editar", data=_datos_base(
        id=sid, nombre="Sindicato Test Admin Portada Clara", portada_clara="true",
    ), follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.get(Sindicato, sid)
        assert sind.portada_clara is True
        assert sind.admin_portada_clara is False
    print("OK  test_edicion_cambia_admin_portada_clara_sin_tocar_la_del_trabajador")


if __name__ == "__main__":
    test_grandfathering_sindicato_previo_queda_en_falso()
    test_alta_sin_tildar_portada_clara_queda_en_falso()
    test_alta_tildando_portada_clara_queda_en_true()
    test_edicion_cambia_portada_clara()
    test_marca_sindicato_expone_portada_clara()
    test_admin_portada_clara_independiente_de_la_del_trabajador()
    test_edicion_cambia_admin_portada_clara_sin_tocar_la_del_trabajador()
    print("Todos los tests de portada_clara pasaron.")
