"""Verificación de "Mis recibos" y el envío al sindicato (corrección de dic. 2026):
cada verificación se registra, y "enviado" marca el INTENTO EXACTO que se mandó,
no todos los intentos del mismo período. Usa un SQLite temporal, no toca la base
de desarrollo. Correr con: .venv/Scripts/python.exe test_historial_recibos.py
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
    sind = Sindicato(nombre="UOM Test")
    s.add(sind)
    s.commit()
    s.refresh(sind)
    s.add(Trabajador(sindicato_id=sind.id, cuil="20111111119", nombre="Juan", registrado=True))
    s.commit()
    SID = sind.id

client = TestClient(main.app)
client.cookies.set("cuil_trab", "20111111119")

RECIBO = {
    "periodo": "2026-06", "empleado": {"cuil": "20111111119"},
    "lineas": [{"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 500000, "tipo": "remuneracion"}],
    "totales_impresos": {},
}


def test_envio_marca_solo_el_intento_exacto():
    # Intento 1: se verifica pero NO se envía.
    r1 = client.post("/api/validar", json={"recibo": RECIBO, "conceptos_nuevos": []})
    assert r1.status_code == 200, r1.text
    resultado1 = r1.json()
    assert "recibo_verificado_id" in resultado1

    # Intento 2: se verifica Y se envía al sindicato.
    r2 = client.post("/api/validar", json={"recibo": RECIBO, "conceptos_nuevos": []})
    resultado2 = r2.json()
    envio = client.post("/api/enviar-sindicato", json={"recibo": RECIBO, "resultado": resultado2})
    assert envio.status_code == 200, envio.text

    lista = client.get("/api/mis-recibos").json()
    assert len(lista) == 2, lista

    por_id = {r["id"]: r for r in lista}
    assert por_id[resultado1["recibo_verificado_id"]]["enviado"] is False, "el intento 1 NO se envió, no debe figurar enviado"
    assert por_id[resultado2["recibo_verificado_id"]]["enviado"] is True, "el intento 2 SÍ se envió, debe figurar enviado"
    print("OK  test_envio_marca_solo_el_intento_exacto")


if __name__ == "__main__":
    test_envio_marca_solo_el_intento_exacto()
    print("\nTodo OK — historial de recibos y envío preciso al sindicato.")
