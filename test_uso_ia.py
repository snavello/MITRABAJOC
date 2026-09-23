"""Consumo de la API de IA: se registra en cada llamada real (recibo,
aportes de ARCA, aprendizaje del admin), no solo cuando se reporta al
sindicato -- y se puede ver/filtrar desde /plataforma.

Correr con: .venv/Scripts/python.exe -m pytest test_uso_ia.py -q
"""
import os
from types import SimpleNamespace

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, Trabajador, UsuarioSindicato
from modulos import MODULOS_INICIALES
import main
import extractor
from fastapi.testclient import TestClient

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="UOM Uso IA", slug="uom-uso-ia", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119",
                      activo=True, registrado=True))
    db.guardar_datos_personales(s, "20111111119", nombre="Juan")
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("clave-test"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

trab_client = TestClient(main.app)
trab_client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident="20111111119"))
trab_client.cookies.set("cuil_trab", "20111111119")

admin_client = TestClient(main.app)
admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})

plataforma_client = TestClient(main.app)
plataforma_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def _mock_msg(payload_json: str, tokens_entrada=1000, tokens_salida=200):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=payload_json)],
        usage=SimpleNamespace(input_tokens=tokens_entrada, output_tokens=tokens_salida),
    )


def test_registrar_y_leer_uso_ia():
    db.registrar_uso_ia(SID, "20111111119", "recibo", "claude-sonnet-4-6", 1500, 300)
    listado = db.uso_ia_listado()
    assert len(listado) == 1
    fila = listado[0]
    assert fila["sindicato"] == "UOM Uso IA"
    assert fila["tokens_entrada"] == 1500
    assert fila["tokens_salida"] == 300
    print("OK  test_registrar_y_leer_uso_ia")


def test_api_leer_registra_uso_real(monkeypatch):
    import json
    recibo_json = json.dumps({
        "formato": "clasico", "confianza": "alta",
        "empleado": {"cuil": "20111111119"}, "empleador": {"nombre": "X", "cuit": None},
        "periodo": "2026-08", "lineas": [], "totales_impresos": {},
    })
    original = extractor.client.messages.create
    extractor.client.messages.create = lambda **kw: _mock_msg(recibo_json, 2000, 400)
    try:
        r = trab_client.post("/api/leer", files={"archivo": ("recibo.png", b"fake", "image/png")})
    finally:
        extractor.client.messages.create = original
    assert r.status_code == 200, r.text

    listado = db.uso_ia_listado()
    fila = next(f for f in listado if f["tokens_entrada"] == 2000)
    assert fila["tipo"] == "recibo"
    assert fila["cuil"] == "20111111119"
    assert fila["sindicato"] == "UOM Uso IA"
    print("OK  test_api_leer_registra_uso_real")


def test_confianza_baja_igual_registra_el_gasto():
    """El costo ya se generó aunque la lectura no sirva -- no hay que
    perderlo solo porque la ruta después rechaza el resultado."""
    import json
    recibo_json = json.dumps({"confianza": "baja"})
    original = extractor.client.messages.create
    extractor.client.messages.create = lambda **kw: _mock_msg(recibo_json, 111, 22)
    antes = len(db.uso_ia_listado())
    try:
        r = trab_client.post("/api/leer", files={"archivo": ("recibo.png", b"fake", "image/png")})
    finally:
        extractor.client.messages.create = original
    assert r.status_code == 422
    despues = db.uso_ia_listado()
    assert len(despues) == antes + 1, "confianza baja igual consumió tokens, tiene que quedar registrado"
    print("OK  test_confianza_baja_igual_registra_el_gasto")


def test_admin_aprender_registra_tipo_aprendizaje(monkeypatch):
    import json
    recibo_json = json.dumps({
        "confianza": "alta", "empleador": {"nombre": "Y", "cuit": None},
        "lineas": [], "periodo": "2026-08",
    })
    original = extractor.client.messages.create
    extractor.client.messages.create = lambda **kw: _mock_msg(recibo_json, 800, 150)
    try:
        r = admin_client.post("/admin/aprender", files={"archivos": ("r.png", b"fake", "image/png")})
    finally:
        extractor.client.messages.create = original
    assert r.status_code == 200, r.text
    fila = next(f for f in db.uso_ia_listado() if f["tokens_entrada"] == 800)
    assert fila["tipo"] == "aprendizaje"
    assert fila["cuil"] == ""
    print("OK  test_admin_aprender_registra_tipo_aprendizaje")


def test_plataforma_lista_y_filtra_por_sindicato_y_modelo():
    r = plataforma_client.get("/plataforma")
    assert r.status_code == 200
    assert "Uso de la API de IA" in r.text
    assert "UOM Uso IA" in r.text
    assert "claude-sonnet-4-6" in r.text
    print("OK  test_plataforma_lista_y_filtra_por_sindicato_y_modelo")


if __name__ == "__main__":
    test_registrar_y_leer_uso_ia()
    test_api_leer_registra_uso_real(None)
    test_confianza_baja_igual_registra_el_gasto()
    test_admin_aprender_registra_tipo_aprendizaje(None)
    test_plataforma_lista_y_filtra_por_sindicato_y_modelo()
    print("\nTodo OK — uso de IA.")
