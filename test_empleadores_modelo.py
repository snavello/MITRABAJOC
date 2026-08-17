"""Modelo de Empleadores: CuentaEmpleador/Empleador y la precarga de CUITs
desde Concepto.cuit_empleador (db.importar_cuits_de_conceptos).

Correr con: .venv/Scripts/python.exe test_empleadores_modelo.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, Concepto, Empleador
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Empleadores", slug="uom-empleadores")
    fega = Sindicato(nombre="Fega Empleadores", slug="fega-empleadores")
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id


def _limpiar():
    """Aísla cada test: sin esto, los Concepto de un test anterior siguen
    apareciendo en el escaneo de importar_cuits_de_conceptos del siguiente."""
    with db.get_session() as s:
        for c in s.exec(select(Concepto)).all():
            s.delete(c)
        for e in s.exec(select(Empleador)).all():
            s.delete(e)
        s.commit()


def test_importar_cuits_de_conceptos_crea_filas_minimas():
    _limpiar()
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=SID_UOM, codigo="C1", nombre="Concepto 1",
                        tipo="descuento", remunerativo=False, cuit_empleador="30111111111"))
        s.add(Concepto(sindicato_id=SID_UOM, codigo="C2", nombre="Concepto 2",
                        tipo="descuento", remunerativo=False, cuit_empleador="30222222222"))
        s.commit()
    agregados = db.importar_cuits_de_conceptos(SID_UOM)
    assert agregados == 2
    with db.get_session() as s:
        cuits = {e.cuit for e in s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM)).all()}
    assert cuits == {"30111111111", "30222222222"}
    print("OK  test_importar_cuits_de_conceptos_crea_filas_minimas")


def test_importar_cuits_de_conceptos_es_idempotente():
    _limpiar()
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=SID_UOM, codigo="C3", nombre="Concepto 3",
                        tipo="descuento", remunerativo=False, cuit_empleador="30333333333"))
        s.commit()
    primero = db.importar_cuits_de_conceptos(SID_UOM)
    segundo = db.importar_cuits_de_conceptos(SID_UOM)
    assert primero == 1
    assert segundo == 0
    with db.get_session() as s:
        filas = s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM, Empleador.cuit == "30333333333")).all()
    assert len(filas) == 1
    print("OK  test_importar_cuits_de_conceptos_es_idempotente")


def test_importar_cuits_ignora_otro_sindicato():
    _limpiar()
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=SID_FEGA, codigo="C4", nombre="Concepto 4",
                        tipo="descuento", remunerativo=False, cuit_empleador="30444444444"))
        s.commit()
    agregados = db.importar_cuits_de_conceptos(SID_UOM)
    assert agregados == 0
    with db.get_session() as s:
        uom_empleadores = s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM)).all()
    assert uom_empleadores == []
    print("OK  test_importar_cuits_ignora_otro_sindicato")


def test_importar_cuits_ignora_vacios_y_null():
    _limpiar()
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=SID_UOM, codigo="C5", nombre="Concepto 5",
                        tipo="descuento", remunerativo=False, cuit_empleador=None))
        s.add(Concepto(sindicato_id=SID_UOM, codigo="C6", nombre="Concepto 6",
                        tipo="descuento", remunerativo=False, cuit_empleador=""))
        s.commit()
    agregados = db.importar_cuits_de_conceptos(SID_UOM)
    assert agregados == 0
    print("OK  test_importar_cuits_ignora_vacios_y_null")


if __name__ == "__main__":
    test_importar_cuits_de_conceptos_crea_filas_minimas()
    test_importar_cuits_de_conceptos_es_idempotente()
    test_importar_cuits_ignora_otro_sindicato()
    test_importar_cuits_ignora_vacios_y_null()
    print("\nTodo OK — modelo de Empleadores.")
