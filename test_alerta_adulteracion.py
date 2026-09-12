"""Alerta de posible adulteración al leer un recibo: si la IA marca
alerta_adulteracion.detectada=true (en totales, CUIL, CUIT del empleador o
fechas), /api/leer no bloquea -- devuelve la alerta en la respuesta y guarda
el archivo original en ReciboSospechoso para que la plataforma lo revise.

Correr con: .venv/Scripts/python.exe -m pytest test_alerta_adulteracion.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, Trabajador, ReciboSospechoso
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Adulteracion", slug="test-adulteracion")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan",
                      activo=True, registrado=True))
    s.commit()

trab_client = TestClient(main.app)
trab_client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
trab_client.cookies.set("cuil_trab", "20111111119")

RECIBO_BASE = {
    "periodo": "2026-07", "empleado": {"cuil": "20111111119"},
    "empleador": {"nombre": "Acme SA", "cuit": "30111111113"},
    "lineas": [{"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 500000,
                "tipo": "remuneracion"}],
    "totales_impresos": {"remuneraciones": 500000, "descuentos": 0, "neto": 500000},
    "contribuciones_patronales": [], "confianza": "alta",
}


def _mockear_extraer(alerta):
    recibo = dict(RECIBO_BASE, alerta_adulteracion=alerta)
    def fake(contenido, content_type):
        return recibo, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 100, "tokens_salida": 50}
    return fake


def test_sin_alerta_no_guarda_nada():
    original = main.extraer
    main.extraer = _mockear_extraer({"detectada": False, "motivo": None})
    try:
        r = trab_client.post("/api/leer", files={"archivo": ("recibo.png", b"fake", "image/png")})
    finally:
        main.extraer = original
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alerta_adulteracion"] is None
    with Session(db.engine) as s:
        assert s.exec(select(ReciboSospechoso)).first() is None
    print("OK  test_sin_alerta_no_guarda_nada")


def test_con_alerta_no_bloquea_y_guarda_el_archivo():
    original = main.extraer
    main.extraer = _mockear_extraer({
        "detectada": True, "motivo": "el neto tiene un dígito con trazo distinto al resto",
    })
    try:
        r = trab_client.post("/api/leer", files={"archivo": ("recibo.png", b"contenido-fake-del-recibo", "image/png")})
    finally:
        main.extraer = original
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alerta_adulteracion"] is not None
    assert body["alerta_adulteracion"]["detectada"] is True
    assert "recibo" in body  # el proceso sigue normalmente, no se corta

    with Session(db.engine) as s:
        rs = s.exec(select(ReciboSospechoso)).first()
        assert rs is not None
        assert rs.cuil == "20111111119"
        assert rs.periodo == "2026-07"
        assert "trazo distinto" in rs.motivo
        assert rs.archivo_datos == b"contenido-fake-del-recibo"
        assert rs.archivo_mime == "image/png"
        assert rs.sindicato_id == SID
        global RECIBO_ID
        RECIBO_ID = rs.id
    print("OK  test_con_alerta_no_bloquea_y_guarda_el_archivo")


def test_solo_plataforma_puede_ver_el_archivo():
    r_anon = TestClient(main.app).get(f"/plataforma/recibos-sospechosos/{RECIBO_ID}/archivo")
    assert r_anon.status_code == 403

    r_trab = trab_client.get(f"/plataforma/recibos-sospechosos/{RECIBO_ID}/archivo")
    assert r_trab.status_code == 403

    plat_client = TestClient(main.app)
    plat_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})
    r_plat = plat_client.get(f"/plataforma/recibos-sospechosos/{RECIBO_ID}/archivo")
    assert r_plat.status_code == 200
    assert r_plat.content == b"contenido-fake-del-recibo"
    assert r_plat.headers["content-type"] == "image/png"
    print("OK  test_solo_plataforma_puede_ver_el_archivo")


def test_listado_de_plataforma_incluye_el_recibo():
    plat_client = TestClient(main.app)
    plat_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})
    r = plat_client.get("/plataforma")
    assert r.status_code == 200
    assert "Recibos con alerta" in r.text
    assert "20111111119" in r.text
    print("OK  test_listado_de_plataforma_incluye_el_recibo")


if __name__ == "__main__":
    test_sin_alerta_no_guarda_nada()
    test_con_alerta_no_bloquea_y_guarda_el_archivo()
    test_solo_plataforma_puede_ver_el_archivo()
    test_listado_de_plataforma_incluye_el_recibo()
    print("\nTodo OK — alerta de adulteración.")
