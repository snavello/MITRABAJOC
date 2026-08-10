"""Rutas de ABM de conceptos y aprendizaje con CUIT de empleador.

Correr con: .venv/Scripts/python.exe test_concepto_cuit_rutas.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, UsuarioSindicato, Concepto
import auth
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Federación Gastronómica", slug="fega")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20222222220", nombre="Admin",
                            clave_hash=auth.hashear_clave("fega-demo"), debe_cambiar_clave=False))
    s.commit()

client = TestClient(main.app)
client.post("/admin/login", data={"usuario": "20222222220", "clave": "fega-demo"})


def test_alta_concepto_generico_no_guarda_cuit():
    client.post("/admin/concepto", data={
        "codigo": "JUB", "nombre": "Aporte jubilatorio", "tipo": "descuento",
        "remunerativo": "si", "alias": "",
    })
    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "JUB")).first()
        assert c.cuit_empleador is None and c.codigo_generico is None
    print("OK  test_alta_concepto_generico_no_guarda_cuit")


def test_alta_concepto_especifico_guarda_cuit_y_generico():
    client.post("/admin/concepto", data={
        "codigo": "060", "nombre": "Jubilacion Ley 24241", "tipo": "descuento",
        "remunerativo": "si", "alias": "",
        "cuit_empleador": "30-11111111-2", "codigo_generico": "JUB",
    })
    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "060")).first()
        assert c.cuit_empleador == "30111111112", c.cuit_empleador
        assert c.codigo_generico == "JUB"
    print("OK  test_alta_concepto_especifico_guarda_cuit_y_generico")


def test_codigo_generico_se_ignora_sin_cuit():
    client.post("/admin/concepto", data={
        "codigo": "PRESENT", "nombre": "Presentismo", "tipo": "ingreso",
        "remunerativo": "si", "alias": "",
        "codigo_generico": "ALGO",  # sin cuit_empleador -> se ignora
    })
    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "PRESENT")).first()
        assert c.cuit_empleador is None and c.codigo_generico is None
    print("OK  test_codigo_generico_se_ignora_sin_cuit")


def test_aprender_aplicar_persiste_cuit_y_generico():
    r = client.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "APJUB", "descripcion": "Ap. Jubilatorio", "tipo": "descuento",
         "remunerativo": True, "cuit_empleador": "30222222223", "codigo_generico": "JUB"},
    ]})
    assert r.status_code == 200 and r.json()["altas"] == 1
    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "APJUB")).first()
        assert c.cuit_empleador == "30222222223"
        assert c.codigo_generico == "JUB"
    print("OK  test_aprender_aplicar_persiste_cuit_y_generico")


def test_aprender_aplicar_no_duplica_mismo_codigo_mismo_cuit():
    r1 = client.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "VIAT", "descripcion": "Viáticos", "tipo": "ingreso",
         "remunerativo": False, "cuit_empleador": "30222222223"},
    ]})
    r2 = client.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "VIAT", "descripcion": "Viáticos", "tipo": "ingreso",
         "remunerativo": False, "cuit_empleador": "30222222223"},
    ]})
    assert r1.json()["altas"] == 1
    assert r2.json()["altas"] == 0, "no debe duplicar el mismo código para el mismo CUIT"
    print("OK  test_aprender_aplicar_no_duplica_mismo_codigo_mismo_cuit")


def test_aprender_aplicar_mismo_codigo_distinto_cuit_no_es_duplicado():
    r1 = client.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "999", "descripcion": "Concepto A", "tipo": "ingreso",
         "remunerativo": False, "cuit_empleador": "30111111112"},
    ]})
    r2 = client.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "999", "descripcion": "Concepto B (otro empleador)", "tipo": "ingreso",
         "remunerativo": False, "cuit_empleador": "30222222223"},
    ]})
    assert r1.json()["altas"] == 1
    assert r2.json()["altas"] == 1, "mismo código pero distinto CUIT no es duplicado"
    print("OK  test_aprender_aplicar_mismo_codigo_distinto_cuit_no_es_duplicado")


if __name__ == "__main__":
    test_alta_concepto_generico_no_guarda_cuit()
    test_alta_concepto_especifico_guarda_cuit_y_generico()
    test_codigo_generico_se_ignora_sin_cuit()
    test_aprender_aplicar_persiste_cuit_y_generico()
    test_aprender_aplicar_no_duplica_mismo_codigo_mismo_cuit()
    test_aprender_aplicar_mismo_codigo_distinto_cuit_no_es_duplicado()
    print("\nTodo OK — rutas de conceptos con CUIT de empleador.")
