"""Filigrana determinística y número de credencial sin duplicar guiones.
Correr con: .venv/Scripts/python.exe test_credencial_v2.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

from filigrana import filigrana_svg
import db
from db import Sindicato, Trabajador

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Unión Obrera Metalúrgica", slug="union-obrera-metalurgica")
    s.add(sind); s.commit(); s.refresh(sind)
    s.add(Trabajador(sindicato_id=sind.id, cuil="20111111119", nombre="Juan"))
    s.commit()
    SID = sind.id


def test_filigrana_es_determinista():
    a = filigrana_svg("Unión Obrera Metalúrgica", "#2fa88f", "#e8b84b")
    b = filigrana_svg("Unión Obrera Metalúrgica", "#2fa88f", "#e8b84b")
    assert a == b
    print("OK  test_filigrana_es_determinista")


def test_filigrana_varia_por_sindicato():
    a = filigrana_svg("Unión Obrera Metalúrgica", "#2fa88f", "#e8b84b")
    b = filigrana_svg("Federación Gastronómica", "#c9a227", "#2f6b3d")
    assert a != b
    print("OK  test_filigrana_varia_por_sindicato")


def test_filigrana_es_svg_valido_y_usa_los_colores():
    svg = filigrana_svg("AEFIP", "#3f8fd4", "#8ab4d8")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "#3f8fd4" in svg and "#8ab4d8" in svg
    print("OK  test_filigrana_es_svg_valido_y_usa_los_colores")


def test_filigrana_no_rompe_con_nombre_vacio():
    svg = filigrana_svg("", "#000000", "#ffffff")
    assert svg.startswith("<svg")
    print("OK  test_filigrana_no_rompe_con_nombre_vacio")


def test_numero_credencial_no_duplica_guion():
    # El bug real: slug ya trae guiones ('union-obrera-metalurgica'), y
    # slug[:6] se comía uno ('union-'), dando 'UNION--000001'.
    numero = db.numero_credencial("20111111119", SID, "union-obrera-metalurgica")
    assert numero == "UNIONO-000001", numero
    assert "--" not in numero, numero
    print(f"OK  test_numero_credencial_no_duplica_guion ({numero})")


def test_numero_credencial_sin_empadronamiento_es_vacio():
    assert db.numero_credencial("20999999999", SID, "union-obrera-metalurgica") == ""
    print("OK  test_numero_credencial_sin_empadronamiento_es_vacio")


if __name__ == "__main__":
    test_filigrana_es_determinista()
    test_filigrana_varia_por_sindicato()
    test_filigrana_es_svg_valido_y_usa_los_colores()
    test_filigrana_no_rompe_con_nombre_vacio()
    test_numero_credencial_no_duplica_guion()
    test_numero_credencial_sin_empadronamiento_es_vacio()
    print("\nTodo OK — filigrana y número de credencial.")
