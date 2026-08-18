"""Punto 1 (pedido 2026-08-18): un recibo reportado con inconsistencias
también tiene que figurar en el padrón de afiliados cotizantes -- antes
solo llegaban ahí los recibos sin discrepancias (enviados con "Enviar a mi
sindicato"). /api/reportar ahora, además del Reporte de siempre (para que
el sindicato lo revise), registra un EnvioSindicato -- mismo padrón que ya
usa /api/enviar-sindicato -- y marca el ReciboVerificado como enviado.

Usa un SQLite temporal, no toca la base de desarrollo.
Correr con: .venv/Scripts/python.exe test_reportar_afiliado_cotizante.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, Trabajador, Concepto, Formula, EnvioSindicato, Reporte
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="UOM Test Cotizantes")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan", registrado=True))
    # Fórmula que el recibo de abajo NO va a cumplir a propósito, para que la
    # validación termine con discrepancias reales (no simuladas a mano).
    s.add(Concepto(sindicato_id=SID, codigo="JUB", nombre="Aporte jubilatorio",
                    tipo="descuento", remunerativo=True, alias=["Jubilación"]))
    s.add(Formula(sindicato_id=SID, target="JUB", descripcion="Jubilación = 11% del remunerativo",
                   expr="0.11 * base_remunerativa", tolerancia=1.0))
    s.commit()

client = TestClient(main.app)
client.cookies.set("cuil_trab", "20111111119")

RECIBO_CON_DISCREPANCIA = {
    "periodo": "2026-06", "empleado": {"cuil": "20111111119"},
    "lineas": [
        {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 100000, "tipo": "remuneracion"},
        # Debería ser -11000 (11% de 100000); -100 dispara la discrepancia.
        {"codigo": "JUB", "descripcion": "Aporte jubilatorio", "importe": -100, "tipo": "aporte_trabajador"},
    ],
    "totales_impresos": {},
}


def _validar_con_discrepancia():
    r = client.post("/api/validar", json={"recibo": RECIBO_CON_DISCREPANCIA, "conceptos_nuevos": []})
    assert r.status_code == 200, r.text
    resultado = r.json()
    assert resultado["estado"] == "CON_DISCREPANCIAS", resultado
    assert resultado["discrepancias"], "el fixture debería generar al menos una discrepancia real"
    return resultado


def test_reportar_crea_envio_sindicato_ademas_del_reporte():
    resultado = _validar_con_discrepancia()
    with Session(db.engine) as s:
        antes_reportes = len(s.exec(select(Reporte).where(Reporte.sindicato_id == SID)).all())
        antes_envios = len(s.exec(select(EnvioSindicato).where(EnvioSindicato.sindicato_id == SID)).all())

    r = client.post("/api/reportar", json={"recibo": RECIBO_CON_DISCREPANCIA, "resultado": resultado})
    assert r.status_code == 200, r.text

    with Session(db.engine) as s:
        reportes = s.exec(select(Reporte).where(Reporte.sindicato_id == SID)).all()
        envios = s.exec(select(EnvioSindicato).where(EnvioSindicato.sindicato_id == SID)).all()
        assert len(reportes) == antes_reportes + 1, "el reporte de siempre tiene que seguir creándose"
        assert len(envios) == antes_envios + 1, "el recibo reportado tiene que sumarse al padrón de cotizantes"
        envio = envios[-1]
        assert envio.cuil == "20111111119"
        assert envio.periodo == "2026-06"
    print("OK  test_reportar_crea_envio_sindicato_ademas_del_reporte")


def test_reportar_marca_el_recibo_como_enviado():
    resultado = _validar_con_discrepancia()
    rv_id = resultado["recibo_verificado_id"]

    r = client.post("/api/reportar", json={"recibo": RECIBO_CON_DISCREPANCIA, "resultado": resultado})
    assert r.status_code == 200, r.text

    lista = client.get("/api/mis-recibos").json()
    por_id = {x["id"]: x for x in lista}
    assert por_id[rv_id]["enviado"] is True, "reportar un recibo también debe marcarlo como enviado al sindicato"
    print("OK  test_reportar_marca_el_recibo_como_enviado")


if __name__ == "__main__":
    test_reportar_crea_envio_sindicato_ademas_del_reporte()
    test_reportar_marca_el_recibo_como_enviado()
    print("\nTodo OK — recibos reportados con discrepancias entran al padrón de cotizantes.")
