"""Reproduce el bug reportado: /api/reportar guardaba SIEMPRE bajo sindicato_id=1
(el default del modelo), sin importar el sindicato real del trabajador. Por eso
un trabajador de un sindicato con id != 1 nunca veía sus reportes en su panel,
aunque los conceptos nuevos (que sí resuelven el sindicato) se veían bien.

Usa un SQLite temporal, no toca la base de desarrollo.
Correr con: .venv/Scripts/python.exe test_reportar_sindicato_correcto.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, Trabajador
import main
from fastapi.testclient import TestClient

db.crear_tablas()
with db.get_session() as s:
    # Sindicato "señuelo" con id=1 (el default de Reporte.sindicato_id):
    # si el bug reaparece, el reporte cae acá en vez de en el sindicato real.
    s.add(Sindicato(nombre="Señuelo (id 1)"))
    s.commit()

    real = Sindicato(nombre="Gastronómica (id 2)")
    s.add(real)
    s.commit()
    s.refresh(real)
    s.add(Trabajador(sindicato_id=real.id, cuil="20222222224", nombre="Ana", registrado=True))
    s.commit()
    SID_REAL = real.id

assert SID_REAL == 2, "el test asume que el sindicato real quedó con id=2"

client = TestClient(main.app)
client.cookies.set("cuil_trab", "20222222224")


def test_reportar_usa_el_sindicato_real_del_trabajador():
    r = client.post("/api/reportar", json={"cuil": "20222222224", "periodo": "2026-06", "estado": "CON_DISCREPANCIAS"})
    assert r.status_code == 200, r.text

    with db.get_session() as s:
        from sqlmodel import select
        reporte = s.exec(select(db.Reporte)).first()
        assert reporte is not None, "no se guardó ningún reporte"
        assert reporte.sindicato_id == SID_REAL, (
            f"el reporte quedó en sindicato_id={reporte.sindicato_id}, "
            f"debería ser {SID_REAL} (el sindicato real del trabajador)"
        )
    print("OK  test_reportar_usa_el_sindicato_real_del_trabajador")


def test_reportar_sin_sesion_no_guarda_nada():
    client_anonimo = TestClient(main.app)  # sin cookie cuil_trab
    r = client_anonimo.post("/api/reportar", json={"cuil": "x", "periodo": "2026-06"})
    assert r.status_code == 400, r.text
    print("OK  test_reportar_sin_sesion_no_guarda_nada")


if __name__ == "__main__":
    test_reportar_usa_el_sindicato_real_del_trabajador()
    test_reportar_sin_sesion_no_guarda_nada()
    print("\nTodo OK — /api/reportar guarda en el sindicato correcto.")
