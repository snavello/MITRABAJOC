"""Topes de base imponible de la seguridad social (jubilación, INSSJP,
obra social) -- Fase 1: modelo de datos, semilla desde data/topes_ss.csv y
la marca `sujeto_a_tope` en Formula. La Fase 2 (lógica en validador.py) se
prueba en la sección de más abajo del mismo archivo.

Correr con: .venv/Scripts/python.exe test_topes_base_imponible.py
"""
import os
import tempfile
from datetime import datetime, timedelta

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, TopeBaseImponible
import validador
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Test Topes", color_base="#0f1b2d")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id


# ---------- Fase 1: semilla + CRUD ----------

def test_sembrado_carga_59_filas_respetando_estado():
    db.sembrar_topes_si_vacio()
    topes = db.topes_como_dicts()
    assert len(topes) == 59
    sospechosos = [t for t in topes if t["estado"] == "SOSPECHOSO"]
    assert len(sospechosos) == 14
    marzo_2026 = next(t for t in topes if t["vigencia_desde"] == "2026-03")
    assert marzo_2026["estado"] == "verificado"
    assert marzo_2026["tope_maximo"] == 4045590.45
    print("OK  test_sembrado_carga_59_filas_respetando_estado")


def test_sembrado_no_duplica_si_ya_hay_datos():
    db.sembrar_topes_si_vacio()  # ya corrió arriba, esto no debería agregar nada más
    assert len(db.topes_como_dicts()) == 59
    print("OK  test_sembrado_no_duplica_si_ya_hay_datos")


def test_crear_tope_rechaza_vigencia_duplicada():
    assert db.crear_tope("2030-01", 1000, 100, "por_verificar", "test") is True
    assert db.crear_tope("2030-01", 2000, 200, "por_verificar", "test") is False
    print("OK  test_crear_tope_rechaza_vigencia_duplicada")


def test_tope_anterior_a():
    anterior = db.tope_anterior_a("2026-08")
    assert anterior["vigencia_desde"] == "2026-07"
    assert db.tope_anterior_a("2015-01") is None  # no hay ninguno antes del primero
    print("OK  test_tope_anterior_a")


def test_editar_tope():
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2030-01")).first()
        tid = t.id
    assert db.editar_tope(tid, 5000, 500, "verificado", "corregido a mano")
    with Session(db.engine) as s:
        t = s.get(TopeBaseImponible, tid)
        assert t.tope_maximo == 5000 and t.estado == "verificado"
    print("OK  test_editar_tope")


def test_borrar_tope():
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2030-01")).first()
        tid = t.id
    db.borrar_tope(tid)
    with Session(db.engine) as s:
        assert s.get(TopeBaseImponible, tid) is None
    print("OK  test_borrar_tope")


def test_orden_prioridad_sospechosos_recientes_primero():
    listado = db.topes_listado()
    hace_12 = (datetime.now().replace(day=1) - timedelta(days=365)).strftime("%Y-%m")
    urgentes_esperados = {t.vigencia_desde for t in listado
                           if t.estado in ("SOSPECHOSO", "por_verificar") and t.vigencia_desde >= hace_12}
    cantidad_urgentes = len(urgentes_esperados)
    primeros = {t.vigencia_desde for t in listado[:cantidad_urgentes]}
    assert primeros == urgentes_esperados, (primeros, urgentes_esperados)
    # dentro del grupo urgente, el más reciente va primero
    if cantidad_urgentes >= 2:
        assert listado[0].vigencia_desde > listado[1].vigencia_desde
    print("OK  test_orden_prioridad_sospechosos_recientes_primero")


def test_crear_conceptos_universales_marca_sujeto_a_tope():
    db.crear_conceptos_universales(SID)
    formulas = {f["target"]: f for f in db.formulas_como_dicts(SID)}
    assert formulas["JUBILACION"]["sujeto_a_tope"] is True
    assert formulas["PAMI"]["sujeto_a_tope"] is True
    assert formulas["OBRASOCIAL"]["sujeto_a_tope"] is True
    print("OK  test_crear_conceptos_universales_marca_sujeto_a_tope")


def test_formula_nueva_sin_tope_por_defecto():
    from db import Formula
    with db.get_session() as s:
        s.add(Formula(sindicato_id=SID, target="SINDMET", descripcion="Cuota sindical",
                       expr="0.02 * base_remunerativa"))
        s.commit()
    formulas = {f["target"]: f for f in db.formulas_como_dicts(SID)}
    assert formulas["SINDMET"]["sujeto_a_tope"] is False
    print("OK  test_formula_nueva_sin_tope_por_defecto")


if __name__ == "__main__":
    test_sembrado_carga_59_filas_respetando_estado()
    test_sembrado_no_duplica_si_ya_hay_datos()
    test_crear_tope_rechaza_vigencia_duplicada()
    test_tope_anterior_a()
    test_editar_tope()
    test_borrar_tope()
    test_orden_prioridad_sospechosos_recientes_primero()
    test_crear_conceptos_universales_marca_sujeto_a_tope()
    test_formula_nueva_sin_tope_por_defecto()
    print("\nTodos los tests de Fase 1 (topes) pasaron.")
