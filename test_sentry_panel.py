"""Reporte de errores de Sentry en la pestaña Observabilidad (observabilidad/sentry_panel.py).

Se lee con un token de solo lectura. Sin red: `_pedir` se reemplaza por un Sentry de mentira que
anota qué se le pidió. Lo que se prueba, además de que el reporte salga bien armado: que solo se
cuenten los errores del ENTORNO de la app (las pruebas de conexión van aparte), que un Sentry
caído o un token vencido no rompa la pestaña, y que un error de prueba llegue a un entorno
distinto para no ensuciar el reporte de errores reales.

Correr con: .venv/Scripts/python.exe -m pytest test_sentry_panel.py -q
"""
import json
import os
import time
import types

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13571357"
os.environ["PLANIFICADOR"] = "off"

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

import db
import entorno
import main
import sentry_config as sc
from observabilidad import sentry_panel as sp
from fastapi.testclient import TestClient

TOKEN = "sntryu_TOKEN_de_prueba_9999"
# Un `time` propio del módulo, sin espera: patchear `sp.time.sleep` cambiaría `time.sleep` de TODO el proceso.
RELOJ_SIN_ESPERA = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic)

db.crear_tablas()
client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "13571357"}, follow_redirects=False).status_code == 303


def _fila(minuto, codigo="E-INTERNO-00", ruta="/admin/dashboard/kpis", rol="sindicato", sid="7", ref="abc12345"):
    return {"timestamp": f"2026-09-20T03:{minuto:02d}:00+00:00", "title": "ValueError: consulta rota",
            "issue": "COLM3NA-PRUEBAS-4", "issue.id": "774329", "codigo": codigo, "ref": ref, "rol": rol,
            "sindicato_id": sid, "ruta": ruta}


class SentryDeMentira:
    def __init__(self):
        self.pedidos = []
        self.caido = None                      # None | código HTTP a devolver
        self.recientes = [_fila(40), _fila(30, "E-RECIBO-03", "/api/validar", "trabajador", "", "def67890")]
        self.prueba = None

    def pedir(self, ruta, params):
        self.pedidos.append((ruta, dict((k, v) for k, v in params if k != "field"), [v for k, v in params if k == "field"]))
        if self.caido:
            raise sp.ErrorSentry(f"Sentry respondió HTTP {self.caido}.")
        consulta = dict(params).get("query", "")
        campos = [v for k, v in params if k == "field"]
        if "prueba-de-conexion" in consulta:
            return {"data": [self.prueba] if self.prueba else []}
        if campos == ["codigo", "count()"]:
            return {"data": [{"codigo": "E-INTERNO-00", "count()": 5}, {"codigo": "E-RECIBO-03", "count()": 2}]}
        if campos == ["count()"]:
            return {"data": [{"count()": 3 if dict(params)["statsPeriod"] == "24h" else 7}]}
        if campos == ["count_unique(issue)"]:
            return {"data": [{"count_unique(issue)": 2}]}
        return {"data": list(self.recientes)}


@pytest.fixture
def sentry(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("SENTRY_DSN", "https://clave@o1.ingest.us.sentry.io/1")
    monkeypatch.setattr(sp, "_cache", {"hasta": 0.0, "datos": None})
    monkeypatch.setattr(sp, "_ultima_prueba", -sp.ESPERA_ENTRE_PRUEBAS)
    falso = SentryDeMentira()
    monkeypatch.setattr(sp, "_pedir", falso.pedir)
    return falso


# ------------------------- el reporte -------------------------
def test_el_reporte_trae_numeros_codigos_y_ultimos_errores(sentry):
    d = sp.estado()
    assert d["kpis"] == {"errores_24h": 3, "errores_7d": 7, "tipos_distintos": 2, "ultimo": "2026-09-20T03:40:00+00:00"}
    assert [c["codigo"] for c in d["por_codigo"]] == ["E-INTERNO-00", "E-RECIBO-03"]
    assert d["por_codigo"][0]["cantidad"] == 5
    assert len(d["recientes"]) == 2 and d["errores"] == []


def test_cada_error_dice_cuando_donde_quien_y_con_que_referencia(sentry):
    e = sp.estado()["recientes"][0]
    assert (e["ruta"], e["rol"], e["sindicato_id"], e["ref"]) == ("/admin/dashboard/kpis", "sindicato", "7", "abc12345")
    assert e["url"] == "https://ats-xp-qk.sentry.io/issues/774329/" and e["incidencia"] == "COLM3NA-PRUEBAS-4"


def test_un_codigo_conocido_trae_su_significado_del_catalogo_de_errores(sentry):
    d = sp.estado()
    assert "verificar este recibo" in d["por_codigo"][1]["descripcion"]          # E-RECIBO-03
    assert d["recientes"][1]["descripcion"] == d["por_codigo"][1]["descripcion"]
    assert sp.descripcion_del_codigo("E-NO-EXISTE") == "" and sp.descripcion_del_codigo("") == ""


def test_lo_inesperado_se_distingue_de_lo_conocido(sentry):
    assert sp.gravedad("E-INTERNO-00") == "inesperado" and sp.gravedad("") == "inesperado"
    assert sp.gravedad("E-RECIBO-03") == "conocido"
    d = sp.estado()
    assert d["recientes"][0]["gravedad"] == "inesperado" and d["recientes"][1]["gravedad"] == "conocido"


def test_solo_se_cuentan_los_errores_del_entorno_de_la_app_no_las_pruebas_de_conexion(sentry):
    sp.estado()
    consultas = [p[1]["query"] for p in sentry.pedidos if "prueba-de-conexion" not in p[1]["query"]]
    assert consultas and all("environment:pruebas" in q for q in consultas)


def test_se_pide_el_proyecto_correcto_y_solo_errores(sentry):
    sp.estado()
    for ruta, params, _ in sentry.pedidos:
        assert ruta == "/organizations/ats-xp-qk/events/"
        assert params["project"] == "4512116285833216" and params["dataset"] == "errors"


def test_sin_errores_el_reporte_lo_dice_en_vez_de_mostrar_una_tabla_vacia(sentry):
    sentry.recientes = []
    d = sp.estado()
    assert d["recientes"] == [] and d["kpis"]["ultimo"] is None


def test_las_respuestas_se_guardan_45_segundos_y_forzar_las_renueva(sentry):
    sp.estado()
    n = len(sentry.pedidos)
    sp.estado()
    assert len(sentry.pedidos) == n, "abrir la pestaña dos veces seguidas no tiene que repetir las consultas"
    sp.estado(forzar=True)
    assert len(sentry.pedidos) == 2 * n


def test_el_enlace_lleva_a_los_errores_reales_del_entorno_y_no_al_evento_de_prueba():
    u = sp._url_todos()
    assert u.startswith("https://ats-xp-qk.sentry.io/issues/?")
    assert "environment=pruebas" in u and "is%3Aunresolved" in u and "project=4512116285833216" in u


# ------------------------- cuando algo falta o falla -------------------------
def test_sin_token_dice_que_falta_pero_no_rompe(monkeypatch):
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    d = sp.estado()
    assert d["token_configurado"] is False and d["kpis"] is None and "SENTRY_AUTH_TOKEN" in d["errores"][0]


def test_un_sentry_caido_o_un_token_vencido_no_rompe_la_pestana(sentry):
    sentry.caido = 401
    r = client.get("/api/entornos/observabilidad/sentry")
    assert r.status_code == 200
    d = r.json()
    assert d["kpis"] is None and d["errores"] and d["url_todos"], "el enlace a Sentry tiene que seguir estando"


def test_un_401_real_se_explica_en_castellano(monkeypatch):
    import urllib.error

    def rechaza(*a, **k):
        raise urllib.error.HTTPError("https://sentry.io", 401, "no", {}, None)
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(sp.urllib.request, "urlopen", rechaza)
    with pytest.raises(sp.ErrorSentry) as e:
        sp._pedir("/x", [])
    assert "vencido, revocado o sin permisos" in str(e.value)


def test_el_estado_informa_si_el_envio_esta_activo(sentry):
    sentry_sdk.init(dsn="")
    assert sp.estado()["sdk_activo"] is False and sp.estado()["dsn_configurado"] is True


# ------------------------- el error de prueba -------------------------
class TransporteFalso(Transport):
    def __init__(self):
        super().__init__()
        self.eventos = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.eventos.append(item.payload.json)


@pytest.fixture
def envio(monkeypatch):
    monkeypatch.setattr(sp.sentry_sdk, "flush", lambda *a, **k: None)      # sin espera real
    t = TransporteFalso()
    sc._recientes.clear()
    sc.iniciar("https://clave@o1.ingest.us.sentry.io/1", "pruebas", release="r", transport=t)
    yield t
    sentry_sdk.init(dsn="")
    sc._recientes.clear()


def test_el_error_de_prueba_llega_a_otro_entorno_para_no_ensuciar_el_reporte(sentry, envio, monkeypatch):
    monkeypatch.setattr(sp, "time", RELOJ_SIN_ESPERA)
    sentry.prueba = {"timestamp": "2026-09-20T03:50:00+00:00", "ref": "x"}
    r = client.post("/entornos/observabilidad/sentry-prueba")
    assert r.status_code == 200 and r.json()["llego"] is True and r.json()["verificable"] is True
    (e,) = envio.eventos
    assert e["environment"] == "prueba-de-conexion", "si fuera 'pruebas' contaría como un error real"
    assert e["tags"]["codigo"] == "E-PRUEBA-00" and e["tags"]["prueba"] == "si" and e["tags"]["ref"] == r.json()["ref"]


def test_la_prueba_dice_si_no_llego_a_verse(sentry, envio, monkeypatch):
    monkeypatch.setattr(sp, "time", RELOJ_SIN_ESPERA)
    sentry.prueba = None
    j = client.post("/entornos/observabilidad/sentry-prueba").json()
    assert j["llego"] is False and j["verificable"] is True


def test_la_prueba_se_puede_mandar_una_vez_por_minuto(sentry, envio, monkeypatch):
    monkeypatch.setattr(sp, "time", RELOJ_SIN_ESPERA)
    assert client.post("/entornos/observabilidad/sentry-prueba").status_code == 200
    segundo = client.post("/entornos/observabilidad/sentry-prueba")
    assert segundo.status_code == 429 and "esperá" in segundo.json()["detail"]
    assert len(envio.eventos) == 1


def test_con_el_envio_apagado_la_prueba_lo_dice(sentry):
    sentry_sdk.init(dsn="")
    r = client.post("/entornos/observabilidad/sentry-prueba")
    assert r.status_code == 502 and "SENTRY_DSN" in r.json()["detail"]


def test_un_error_normal_no_cambia_de_entorno(envio):
    sc.capturar(ValueError("x"), ruta="/r", ref="abc", codigo="E-INTERNO-00")
    (e,) = envio.eventos
    assert e["environment"] == "pruebas" and "prueba" not in e["tags"]


# ------------------------- acceso y presentación -------------------------
def test_sin_pin_no_se_puede_ver_el_reporte_ni_mandar_pruebas(sentry):
    otro = TestClient(main.app)
    assert otro.get("/api/entornos/observabilidad/sentry").status_code == 403
    assert otro.post("/entornos/observabilidad/sentry-prueba").status_code == 403
    assert sentry.pedidos == []


def test_en_demo_se_rechaza(sentry, monkeypatch):
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    assert client.get("/api/entornos/observabilidad/sentry").status_code == 400
    assert client.post("/entornos/observabilidad/sentry-prueba").status_code == 400


def test_el_token_no_sale_en_ninguna_respuesta(sentry):
    textos = [client.get("/api/entornos/observabilidad/sentry").text, client.get("/api/entornos/observabilidad").text,
              client.get("/entornos").text]
    assert all(TOKEN not in t for t in textos)


def test_la_pantalla_trae_el_reporte_con_lo_necesario_para_identificar_errores():
    html = client.get("/entornos").text
    for pieza in ('id="obs-sentry"', "Últimos errores", "Por código de error", "Mandar error de prueba",
                  "Referencia", "Sindicato #", "Sin errores", "/api/entornos/observabilidad/sentry",
                  ".obs-cod.inesperado", ".obs-cod.conocido", "obs-cod ${e.gravedad}",
                  "Ver ejemplo", "EJEMPLO: así se vería", "de mentira, no vienen de Sentry"):
        assert pieza in html, pieza
    assert "Errores de la app (Sentry)" in html


def test_el_boton_de_sentry_del_panel_general_lleva_a_los_errores_reales(sentry):
    assert client.get("/api/entornos/observabilidad").json()["sentry_url"] == sp._url_todos()


def test_el_token_de_sentry_no_esta_en_el_repo():
    for archivo in ("observabilidad/sentry_panel.py", "observabilidad/config.json", "main.py", "sentry_config.py"):
        assert "sntryu_" not in open(archivo, encoding="utf-8").read().replace("sntryu_TOKEN", ""), archivo
