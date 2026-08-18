"""Test liviano de la carga de datos de prueba de empleadores agregada a
cargar_demo.py en la Fase 6 del plan de Empleadores: corre el script real
(`python cargar_demo.py`) contra una base SQLite temporal y confirma que
el CUIT compartido resuelve los 2 sindicatos y que el módulo "empleadores"
queda habilitado -- sin duplicar la lógica de carga, solo verificando el
resultado real del script tal como lo correría el usuario.

Correr con: .venv/Scripts/python.exe test_cargar_demo_empleadores.py
"""
import os
import subprocess
import sys
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

env = dict(os.environ)
# Cadena vacía, NO pop -- load_dotenv() (adentro de db.py) no pisa una
# variable ya presente, pero SI la completa desde .env si está ausente.
# Sin esto, el subproceso terminaría escribiendo sobre el Postgres real de
# desarrollo en vez de la base SQLite temporal de este test.
env["DATABASE_URL"] = ""
# cargar_demo.py imprime "✓" -- forzar UTF-8 acá, si no la consola de
# Windows (cp1252) revienta al capturar stdout del subproceso.
env["PYTHONIOENCODING"] = "utf-8"
resultado = subprocess.run(
    [sys.executable, "cargar_demo.py"], cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env, capture_output=True, text=True, timeout=60,
)
assert resultado.returncode == 0, resultado.stdout + resultado.stderr
SALIDA = resultado.stdout

import db
from db import Sindicato, Empleador


def test_salida_menciona_empresa():
    assert "Empresa:" in SALIDA
    assert "30111222339" in SALIDA
    print("OK  test_salida_menciona_empresa")


def test_cuit_compartido_resuelve_dos_sindicatos():
    sinds = db.sindicatos_de_cuit_empleador("30111222339")
    nombres = {s["nombre"] for s in sinds}
    assert nombres == {"Unión Obrera Metalúrgica", "Federación Gastronómica"}
    print("OK  test_cuit_compartido_resuelve_dos_sindicatos")


def test_cuit_no_compartido_resuelve_un_solo_sindicato():
    sinds = db.sindicatos_de_cuit_empleador("30999888776")
    assert len(sinds) == 1
    assert sinds[0]["nombre"] == "Unión Obrera Metalúrgica"
    print("OK  test_cuit_no_compartido_resuelve_un_solo_sindicato")


def test_modulo_empleadores_habilitado():
    from sqlmodel import Session, select
    with Session(db.engine) as s:
        for sind in s.exec(select(Sindicato)).all():
            assert "empleadores" in sind.modulos_habilitados, sind.nombre
    print("OK  test_modulo_empleadores_habilitado")


def test_no_precrea_cuenta_empleador():
    """El autorregistro es el flujo real -- el script no debe crear
    CuentaEmpleador con clave, solo la fila Empleador (CRUD del sindicato)."""
    from db import CuentaEmpleador
    from sqlmodel import Session, select
    with Session(db.engine) as s:
        assert s.exec(select(CuentaEmpleador)).all() == []
    print("OK  test_no_precrea_cuenta_empleador")


if __name__ == "__main__":
    test_salida_menciona_empresa()
    test_cuit_compartido_resuelve_dos_sindicatos()
    test_cuit_no_compartido_resuelve_un_solo_sindicato()
    test_modulo_empleadores_habilitado()
    test_no_precrea_cuenta_empleador()
    print("\nTodo OK — carga de demo de empleadores.")
