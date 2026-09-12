"""Dashboard de Actividad de /entornos (db.actividad_resumen,
db.registrar_acceso, GET /api/entornos/actividad): trámites, recibos,
notificaciones, tokens de IA y accesos, por sindicato y totales.

Correr con: .venv/Scripts/python.exe -m pytest test_actividad.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "97531975"

import db
import main
from db import (Sindicato, Trabajador, Tramite, TipoTramite, ReciboVerificado,
                 Notificacion, NotificacionDestinatario, UsoIA)
from fastapi.testclient import TestClient
import fechas

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Actividad", slug="uom-actividad")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    tipo = TipoTramite(sindicato_id=SID, titulo="Licencia", codigo="LIC")
    s.add(tipo); s.commit(); s.refresh(tipo)
    s.add(Tramite(sindicato_id=SID, tipo_tramite_id=tipo.id,
                   numero_expediente="LIC-2026-1", cuil="20111111119"))
    s.add(Tramite(sindicato_id=SID, tipo_tramite_id=tipo.id,
                   numero_expediente="LIC-2026-2", cuil="20111111119"))

    s.add(ReciboVerificado(sindicato_id=SID, cuil="20111111119", periodo="2026-08", estado="OK"))

    notif = Notificacion(sindicato_id=SID, texto="Aviso")
    s.add(notif); s.commit(); s.refresh(notif)
    s.add(NotificacionDestinatario(notificacion_id=notif.id, cuil="20111111119", leida_en="2026-09-09 10:00"))
    s.add(NotificacionDestinatario(notificacion_id=notif.id, cuil="20222222222", leida_en=None))

    s.add(UsoIA(sindicato_id=SID, cuil="20111111119", tipo="recibo", modelo="claude-sonnet-4-6",
                 tokens_entrada=1000, tokens_salida=200,
                 fecha=fechas.ahora_texto()))
    s.commit()

client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "97531975"}, follow_redirects=False).status_code == 303


def test_actividad_resumen_agrega_por_sindicato_y_totales():
    r = db.actividad_resumen()
    fila = next(f for f in r["sindicatos"] if f["id"] == SID)
    assert fila["tramites"] == 2
    assert fila["recibos"] == 1
    assert fila["notificaciones_enviadas"] == 1  # 1 Notificacion (no por destinatario)
    assert fila["notificaciones_leidas"] == 1    # de 2 destinatarios, 1 leyó
    assert fila["tokens_ia"] == 1200
    assert fila["llamadas_ia"] == 1
    assert r["totales"]["tramites"] == 2
    assert r["totales"]["recibos"] == 1
    print("OK  test_actividad_resumen_agrega_por_sindicato_y_totales")


def test_registrar_acceso_y_contarlo():
    antes = db.actividad_resumen()["totales"]["accesos"]
    db.registrar_acceso("trabajador", sindicato_id=SID)
    db.registrar_acceso("plataforma")  # sin sindicato -- cuenta aparte, no se pierde
    despues = db.actividad_resumen()
    assert despues["totales"]["accesos"] == antes + 2
    assert despues["totales"]["accesos_por_rol"].get("trabajador", 0) >= 1
    assert despues["totales"]["accesos_por_rol"].get("plataforma", 0) >= 1
    fila = next(f for f in despues["sindicatos"] if f["id"] == SID)
    assert fila["accesos"] >= 1
    print("OK  test_registrar_acceso_y_contarlo")


def test_login_trabajador_registra_acceso():
    from auth import hashear_clave
    from db import CuentaTrabajador
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID, cuil="20999999990", nombre="Ana"))
        s.add(CuentaTrabajador(cuil="20999999990", clave_hash=hashear_clave("1234")))
        s.commit()
    antes = db.actividad_resumen()["totales"]["accesos_por_rol"].get("trabajador", 0)
    r = client.post("/trabajador/login", data={"cuil": "20999999990", "clave": "1234"},
                     follow_redirects=False)
    assert r.status_code == 303
    despues = db.actividad_resumen()["totales"]["accesos_por_rol"].get("trabajador", 0)
    assert despues == antes + 1
    print("OK  test_login_trabajador_registra_acceso")


def test_api_actividad_es_publica_y_con_cors_abierto():
    c = TestClient(main.app)  # sin pase de PIN a propósito
    r = c.get("/api/entornos/actividad")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
    body = r.json()
    assert "totales" in body and "sindicatos" in body and "servidor" in body
    assert body["entorno"] == "pruebas"
    print("OK  test_api_actividad_es_publica_y_con_cors_abierto")


def test_entornos_renderiza_pestana_actividad():
    r = client.get("/entornos")
    assert r.status_code == 200
    assert "Actividad" in r.text
    assert 'data-act-env="pruebas"' in r.text and 'data-act-env="demo"' in r.text
    assert "actividad-local-json" in r.text
    print("OK  test_entornos_renderiza_pestana_actividad")


if __name__ == "__main__":
    test_actividad_resumen_agrega_por_sindicato_y_totales()
    test_registrar_acceso_y_contarlo()
    test_login_trabajador_registra_acceso()
    test_api_actividad_es_publica_y_con_cors_abierto()
    test_entornos_renderiza_pestana_actividad()
    print("Todo OK")
