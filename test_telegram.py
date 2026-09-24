"""Avisos por Telegram (telegram.py, resumen_diario.py, db.reclamar_aviso_diario,
POST /entornos/observabilidad/probar-telegram y /resumen-ahora, y el punto de
contacto de Grafana): sin red (urlopen simulado) y sin claves reales.

Correr con: .venv/Scripts/python.exe -m pytest test_telegram.py -q
"""
import io
import json
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "24681357"
os.environ["PIN_ENTORNOS_HABILITADO"] = "1"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("TELEGRAM_CHAT_ID", None)

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import db
import main
import resumen_diario
import telegram
from observabilidad import aplicar_grafana as ag

db.crear_tablas()


@pytest.fixture
def con_bot(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:prueba")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "6107189362")
    telegram._ultimo_por_codigo.clear()


@pytest.fixture
def red_simulada(monkeypatch):
    """urlopen falso: guarda lo que se mandó y contesta {"ok": true}."""
    mandados = []

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(pedido, timeout=0):
        mandados.append({"url": pedido.full_url, "cuerpo": json.loads(pedido.data.decode("utf-8"))})
        return Resp(b'{"ok": true, "result": {}}')

    monkeypatch.setattr(telegram.urllib.request, "urlopen", urlopen)
    return mandados


def test_sin_variables_no_esta_configurado_y_no_toca_la_red(monkeypatch):
    assert telegram.configurado() is False
    monkeypatch.setattr(telegram.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tocó la red")))
    assert telegram.enviar("hola") is False
    assert telegram.avisar_error("E-X", "abcd1234", "/x", "", None, "pruebas") is False
    assert telegram.estado()["configurado"] is False and telegram.estado()["chat_id_oculto"] == ""
    print("OK  test_sin_variables_no_esta_configurado_y_no_toca_la_red")


def test_enviar_hace_un_post_con_el_chat_y_el_texto(con_bot, red_simulada):
    assert telegram.enviar("hola <b>equipo</b>") is True
    assert len(red_simulada) == 1
    assert red_simulada[0]["url"] == "https://api.telegram.org/bot123:prueba/sendMessage"
    c = red_simulada[0]["cuerpo"]
    assert c["chat_id"] == "6107189362" and c["text"] == "hola <b>equipo</b>" and c["parse_mode"] == "HTML"
    assert telegram.estado()["chat_id_oculto"] == "…362"     # nunca el número entero ni el token
    print("OK  test_enviar_hace_un_post_con_el_chat_y_el_texto")


def test_un_fallo_de_red_devuelve_false_sin_lanzar(con_bot, monkeypatch):
    def urlopen(*a, **k):
        raise OSError("sin red")
    monkeypatch.setattr(telegram.urllib.request, "urlopen", urlopen)
    assert telegram.enviar("x") is False
    print("OK  test_un_fallo_de_red_devuelve_false_sin_lanzar")


def test_freno_por_codigo_un_aviso_cada_diez_minutos(con_bot):
    assert telegram.frenado("E-A", ahora=1000.0) is False
    assert telegram.frenado("E-A", ahora=1000.0 + 599) is True
    assert telegram.frenado("E-B", ahora=1000.0 + 599) is False    # otro código no se frena
    assert telegram.frenado("E-A", ahora=1000.0 + 601) is False
    print("OK  test_freno_por_codigo_un_aviso_cada_diez_minutos")


def test_avisar_error_despacha_una_vez_y_sin_datos_personales(con_bot, monkeypatch):
    textos = []
    monkeypatch.setattr(telegram, "enviar_en_segundo_plano", textos.append)
    assert telegram.avisar_error("E-INTERNO-00", "ab12cd34", "/api/leer", "trabajador", 7, "pruebas") is True
    assert telegram.avisar_error("E-INTERNO-00", "ef56gh78", "/api/leer", "trabajador", 7, "pruebas") is False  # frenado
    assert len(textos) == 1
    t = textos[0]
    assert "E-INTERNO-00" in t and "ab12cd34" in t and "/api/leer" in t and "trabajador" in t and "pruebas" in t
    print("OK  test_avisar_error_despacha_una_vez_y_sin_datos_personales")


def test_texto_resumen_lleva_los_indicadores_y_escapa_html():
    kpis = {"recibos_hoy": 12, "recibos_total": 65000, "lecturas_hoy": 3, "costo_hoy_usd": 0.42,
            "en_linea_total": 5, "en_linea": {"trabajador": 4, "admin": 1}, "minutos_en_linea": 15,
            "tramites_abiertos": 4102, "tramites_esperan": 1096, "registrados": 3329, "padron": 5306,
            "porcentaje_registrados": 63, "sindicatos": ["A", "B", "C"]}
    t = telegram.texto_resumen(kpis, {"errores_24h": 2, "errores_7d": 9}, "verde", "pruebas<x>", "23/09/2026")
    assert "65.000" in t and "4.102" in t and "3.329 de 5.306" in t and "US$ 0.42" in t
    assert "🟢" in t and "2 en 24 h" in t and "Sindicatos activos: 3" in t
    assert "pruebas&lt;x&gt;" in t                       # escapado
    t2 = telegram.texto_resumen({}, None, None, "pruebas", "23/09/2026")
    assert "sin dato" in t2 and "—" in t2                # nada inventado cuando falta
    print("OK  test_texto_resumen_lleva_los_indicadores_y_escapa_html")


def test_hora_del_resumen_por_defecto_21_y_configurable(monkeypatch):
    monkeypatch.delenv("TELEGRAM_RESUMEN_HORA", raising=False)
    assert telegram.hora_resumen() == "21:00"
    monkeypatch.setenv("TELEGRAM_RESUMEN_HORA", "07:30")
    assert telegram.hora_resumen() == "07:30"
    monkeypatch.setenv("TELEGRAM_RESUMEN_HORA", "25:99")
    assert telegram.hora_resumen() == "21:00"
    assert resumen_diario.toca_ahora(datetime(2026, 9, 23, 20, 59), "21:00") is False
    assert resumen_diario.toca_ahora(datetime(2026, 9, 23, 21, 0), "21:00") is True
    assert resumen_diario.toca_ahora(datetime(2026, 9, 23, 23, 59), "21:00") is True
    print("OK  test_hora_del_resumen_por_defecto_21_y_configurable")


def test_el_reclamo_del_dia_lo_gana_uno_solo():
    assert db.reclamar_aviso_diario("test-reclamo", "2031-01-01") is True
    assert db.reclamar_aviso_diario("test-reclamo", "2031-01-01") is False    # el mismo día, no
    assert db.reclamar_aviso_diario("test-reclamo", "2031-01-02") is True     # otro día, sí
    assert db.reclamar_aviso_diario("otra-clave", "2031-01-01") is True       # otra clave, sí
    print("OK  test_el_reclamo_del_dia_lo_gana_uno_solo")


def test_intentar_manda_una_sola_vez_por_dia(con_bot, monkeypatch):
    enviados = []
    monkeypatch.setattr(telegram, "enviar", lambda texto: enviados.append(texto) or True)
    monkeypatch.setattr(resumen_diario, "armar_texto", lambda ahora=None: "resumen de prueba")
    temprano = datetime(2031, 3, 3, 20, 30)
    tarde = datetime(2031, 3, 3, 21, 5)
    assert resumen_diario.intentar(temprano) is False and enviados == []
    assert resumen_diario.intentar(tarde) is True and enviados == ["resumen de prueba"]
    assert resumen_diario.intentar(datetime(2031, 3, 3, 22, 0)) is False and len(enviados) == 1
    assert resumen_diario.debe_correr("demo")[0] is False and resumen_diario.debe_correr("pruebas")[0] is True
    print("OK  test_intentar_manda_una_sola_vez_por_dia")


def test_grafana_suma_el_punto_de_contacto_de_telegram_solo_si_hay_claves(con_bot, monkeypatch):
    cfg = ag.cargar_config()
    assert cfg["alertas"]["telegram"]["contact_point"] == "sdn-telegram"
    puntos = ag.payloads_contact_points(cfg)
    assert [p["type"] for p in puntos] == ["email", "telegram"]
    tg = puntos[1]
    assert tg["name"] == "sdn-telegram" and tg["settings"]["chatid"] == "6107189362" and tg["settings"]["bottoken"] == "123:prueba"
    pol = ag.payload_politica(cfg)
    assert pol["receiver"] == "sdn-mail"
    assert [r["receiver"] for r in pol["routes"]] == ["sdn-telegram", "sdn-mail"] and pol["routes"][0]["continue"] is True
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert [p["type"] for p in ag.payloads_contact_points(cfg)] == ["email"]
    assert ag.payload_politica(cfg)["routes"] == []
    print("OK  test_grafana_suma_el_punto_de_contacto_de_telegram_solo_si_hay_claves")


def test_rutas_de_prueba_piden_pase_y_avisan_si_falta_configurar(monkeypatch):
    c = TestClient(main.app)
    assert c.post("/entornos/observabilidad/probar-telegram").status_code == 403
    assert c.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False).status_code == 303
    r = c.post("/entornos/observabilidad/probar-telegram")
    assert r.status_code == 503 and "TELEGRAM" in r.json()["detail"]
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:prueba")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "6107189362")
    textos = []
    monkeypatch.setattr(telegram, "enviar", lambda texto: textos.append(texto) or True)
    assert c.post("/entornos/observabilidad/probar-telegram").json()["ok"] is True
    monkeypatch.setattr(resumen_diario, "armar_texto", lambda ahora=None: "resumen ya")
    assert c.post("/entornos/observabilidad/resumen-ahora").json()["ok"] is True
    assert len(textos) == 2 and textos[1] == "resumen ya"
    d = c.get("/api/entornos/esquema").json()
    assert d["telegram"] is True                          # la Sala lo dibuja como activo
    obs = c.get("/api/entornos/observabilidad").json()
    assert obs["telegram"]["configurado"] is True and obs["telegram"]["hora_resumen"] == "21:00"
    print("OK  test_rutas_de_prueba_piden_pase_y_avisan_si_falta_configurar")
