"""/api/validar corta apenas detecta que el recibo no es del CUIL logueado:
no da de alta conceptos nuevos, no valida nada, y no queda en el historial.

Correr con: .venv/Scripts/python.exe -m pytest test_cuil_bloqueo_ruta.py -q
"""


import db
from db import Sindicato, Trabajador, Concepto, ReciboVerificado
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Bloqueo", slug="test-bloqueo")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan", activo=True, registrado=True))
    s.commit()

client = TestClient(main.app)
client.cookies.set("cuil_trab", "20111111119")


def _payload(cuil_recibo):
    return {
        "recibo": {
            "periodo": "2026-08",
            "empleado": {"cuil": cuil_recibo},
            "empleador": {"nombre": "Otro", "cuit": None},
            "lineas": [{"codigo": "NUEVO-1", "descripcion": "Algo raro", "importe": -500}],
            "totales_impresos": {},
        },
        "conceptos_nuevos": [{"codigo": "NUEVO-1", "descripcion": "Algo raro",
                               "tipo": "descuento", "importe": -500}],
    }


def test_cuil_distinto_bloquea_sin_crear_conceptos_ni_historial():
    r = client.post("/api/validar", json=_payload("20999999999"))
    assert r.status_code == 200
    body = r.json()
    assert body["estado"] == "CUIL_NO_COINCIDE"
    assert body["bloqueado"] is True

    with Session(db.engine) as s:
        conceptos = s.exec(select(Concepto).where(Concepto.sindicato_id == SID)).all()
        assert conceptos == [], "no debe haber creado el concepto nuevo del recibo ajeno"
        historial = s.exec(select(ReciboVerificado).where(ReciboVerificado.sindicato_id == SID)).all()
        assert historial == [], "no debe haber quedado registro en el historial"
    print("OK  test_cuil_distinto_bloquea_sin_crear_conceptos_ni_historial")


def test_cuil_igual_no_bloquea():
    r = client.post("/api/validar", json=_payload("20111111119"))
    assert r.status_code == 200
    body = r.json()
    assert body.get("estado") != "CUIL_NO_COINCIDE"
    with Session(db.engine) as s:
        conceptos = s.exec(select(Concepto).where(Concepto.sindicato_id == SID)).all()
        assert len(conceptos) == 1, "con el CUIL propio sí se debe cargar el concepto nuevo"
    print("OK  test_cuil_igual_no_bloquea")


if __name__ == "__main__":
    test_cuil_distinto_bloquea_sin_crear_conceptos_ni_historial()
    test_cuil_igual_no_bloquea()
    print("\nTodo OK — /api/validar bloquea recibos que no son del CUIL logueado.")
