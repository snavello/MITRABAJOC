"""Rutas de ABM de conceptos y aprendizaje con CUIT de empleador.

Correr con: .venv/Scripts/python.exe test_concepto_cuit_rutas.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, UsuarioSindicato, Concepto
from modulos import MODULOS_INICIALES
import auth
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Federación Gastronómica", slug="fega", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20222222220", nombre="Admin",
                            clave_hash=auth.hashear_clave("fega-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

client = TestClient(main.app)
client.post("/admin/login", data={"usuario": "20222222220", "clave": "fega-demo"})


def test_listado_muestra_codigo_generico_sin_cuit():
    # Bug real: un concepto genérico (sin CUIT) con codigo_generico cargado
    # no se mostraba en /admin -- el template solo lo mostraba si tenía CUIT.
    client.post("/admin/concepto", data={
        "codigo": "42-001", "nombre": "AP. PERS. JUB. ANSES", "tipo": "descuento",
        "remunerativo": "si", "alias": "", "codigo_generico": "JUBILACION",
    })
    r = client.get("/admin")
    assert r.status_code == 200
    assert "genérico → <code>JUBILACION</code>" in r.text
    print("OK  test_listado_muestra_codigo_generico_sin_cuit")


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


def test_codigo_generico_se_guarda_incluso_sin_cuit():
    # Un concepto sin CUIT (catálogo "genérico" del sindicato) también puede
    # apuntar su codigo_generico a otro código genérico -- caso real: un
    # concepto viejo cargado sin CUIT (p.ej. auto-creado antes de que el
    # extractor identificara el CUIT del empleador en el recibo) que el admin
    # vincula a mano al código canónico (ver AEFIP, "42-001" -> "JUBILACION").
    client.post("/admin/concepto", data={
        "codigo": "PRESENT", "nombre": "Presentismo", "tipo": "ingreso",
        "remunerativo": "si", "alias": "",
        "codigo_generico": "ALGO",
    })
    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "PRESENT")).first()
        assert c.cuit_empleador is None
        assert c.codigo_generico == "ALGO"
    print("OK  test_codigo_generico_se_guarda_incluso_sin_cuit")


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
    test_listado_muestra_codigo_generico_sin_cuit()
    test_alta_concepto_generico_no_guarda_cuit()
    test_alta_concepto_especifico_guarda_cuit_y_generico()
    test_codigo_generico_se_guarda_incluso_sin_cuit()
    test_aprender_aplicar_persiste_cuit_y_generico()
    test_aprender_aplicar_no_duplica_mismo_codigo_mismo_cuit()
    test_aprender_aplicar_mismo_codigo_distinto_cuit_no_es_duplicado()
    print("\nTodo OK — rutas de conceptos con CUIT de empleador.")
