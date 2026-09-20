"""Gráficos de Grafana dentro de la pestaña Observabilidad (observabilidad/metricas_panel.py) y detalle
de un error de Sentry sin salir de la app (sentry_panel.detalle).

Sin red: Grafana y Sentry son de mentira. Lo que se prueba: que las consultas salgan del MISMO tablero
que se ve en Grafana (no pueden diferir), que se use el token de LECTURA, que sin datos se diga "SIN
DATOS" y no un cero, que una consulta caída no tumbe el resto, que las rutas exijan el PIN y solo
Pruebas, y que del detalle de un error solo salga código y etiquetas permitidas.

Correr con: .venv/Scripts/python.exe -m pytest test_metricas_panel.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13571357"
os.environ["PLANIFICADOR"] = "off"

import pytest

import db
import entorno
import main
from observabilidad import aplicar_grafana as ag
from observabilidad import aplicar_tablero as at
from observabilidad import metricas_panel as mp
from observabilidad import sentry_panel as sp
from fastapi.testclient import TestClient

TOKEN_LECTURA = "glsa_LECTURA_de_prueba_0000"

db.crear_tablas()
client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "13571357"}, follow_redirects=False).status_code == 303


class PrometheusDeMentira:
    def __init__(self):
        self.pedidos = []
        self.sin_datos = False
        self.fallar_si = ""              # si la consulta contiene este texto, responde 500

    def pedir(self, cliente, metodo, ruta, cuerpo=None, editable_desde_la_ui=False):
        self.pedidos.append((cliente.token, ruta))
        import urllib.parse
        consulta = urllib.parse.parse_qs(urllib.parse.urlparse(ruta).query)["query"][0]
        if self.fallar_si and self.fallar_si in consulta:
            return 500, {"message": "boom"}
        if self.sin_datos:
            return 200, {"status": "success", "data": {"resultType": "vector", "result": []}}
        if "/query_range?" in ruta:
            return 200, {"status": "success", "data": {"resultType": "matrix", "result": [
                {"metric": {"servicio": "web", "status_code": "200"},
                 "values": [[1000, "10"], [1060, "20"], [1120, "NaN"], [1180, "30"]]}]}}
        # Los estados (probe_success) dan 1; el resto, 96 (para ver un color de alarma).
        valor = "1" if "probe_success" in consulta else "96"
        return 200, {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1180, valor]}]}}


@pytest.fixture
def grafana(monkeypatch):
    monkeypatch.setenv("GRAFANA_URL", "https://prueba.grafana.net")
    monkeypatch.setenv("GRAFANA_TOKEN_LECTURA", TOKEN_LECTURA)
    monkeypatch.setattr(mp, "_cache", {})
    falso = PrometheusDeMentira()
    monkeypatch.setattr(ag.Grafana, "pedir",
                        lambda self, metodo, ruta, cuerpo=None, editable_desde_la_ui=False:
                        falso.pedir(self, metodo, ruta, cuerpo, editable_desde_la_ui))
    return falso


def test_las_consultas_salen_del_tablero_de_grafana_no_de_una_copia():
    tablero = {p["id"]: p for p in at.construir_tablero(ag.cargar_config())["panels"]}
    for i in mp.TARJETAS + mp.GRAFICOS:
        assert i in tablero, f"el tablero ya no tiene el panel {i}"
    assert mp._paneles()[5]["targets"][0]["expr"] == tablero[5]["targets"][0]["expr"]


def test_trae_tarjetas_y_graficos_con_el_token_de_lectura(grafana):
    d = client.get("/api/entornos/observabilidad/metricas?rango=6h").json()
    assert len(d["tarjetas"]) == len(mp.TARJETAS) and len(d["graficos"]) == len(mp.GRAFICOS) and d["errores"] == []
    assert {t for t, _ in grafana.pedidos} == {TOKEN_LECTURA}
    assert all("/api/datasources/proxy/uid/grafanacloud-prom/api/v1/" in r for _, r in grafana.pedidos)
    assert TOKEN_LECTURA not in str(d)


def test_los_estados_y_los_colores_salen_de_los_umbrales_del_tablero(grafana):
    tarjetas = {t["id"]: t for t in client.get("/api/entornos/observabilidad/metricas").json()["tarjetas"]}
    assert tarjetas[1]["estado"] == "ok" and tarjetas[1]["texto"] == "OK"        # app responde
    assert tarjetas[5]["estado"] == "mal" and tarjetas[5]["valor"] == 96         # CPU 96% > 95


def test_sin_datos_no_es_un_cero_ni_verde(grafana):
    grafana.sin_datos = True
    d = client.get("/api/entornos/observabilidad/metricas").json()
    assert all(t["estado"] == "sin_datos" and t["valor"] is None for t in d["tarjetas"])
    assert all(g["series"] == [] for g in d["graficos"])


def test_los_valores_no_numericos_se_descartan_de_las_series(grafana):
    g = client.get("/api/entornos/observabilidad/metricas").json()["graficos"][0]
    assert g["series"][0]["puntos"] == [[1000, 10.0], [1060, 20.0], [1180, 30.0]]
    assert g["series"][0]["nombre"] == "web"                                      # {{servicio}} reemplazado
    assert g["umbral"] == 95


def test_una_consulta_caida_no_tumba_las_demas(grafana):
    grafana.fallar_si = "render_disk_usage_bytes"
    d = client.get("/api/entornos/observabilidad/metricas").json()
    assert d["errores"] and "Disco" in d["errores"][0]
    assert len(d["tarjetas"]) >= len(mp.TARJETAS) - 1 and len(d["graficos"]) >= len(mp.GRAFICOS) - 1


def test_el_rango_es_de_una_lista_cerrada_y_el_paso_acota_los_puntos(grafana):
    assert client.get("/api/entornos/observabilidad/metricas?rango=1000d").status_code == 422
    d = client.get("/api/entornos/observabilidad/metricas?rango=7d").json()
    assert d["hasta"] - d["desde"] == 7 * 86400 and (d["hasta"] - d["desde"]) // d["paso"] <= mp.PUNTOS_MAXIMOS + 1


def test_se_guarda_45_segundos_y_forzar_vuelve_a_preguntar(grafana):
    client.get("/api/entornos/observabilidad/metricas")
    n = len(grafana.pedidos)
    client.get("/api/entornos/observabilidad/metricas")
    assert len(grafana.pedidos) == n
    client.get("/api/entornos/observabilidad/metricas?forzar=1")
    assert len(grafana.pedidos) == 2 * n


def test_sin_variables_dice_que_falta_en_vez_de_romperse(monkeypatch):
    monkeypatch.delenv("GRAFANA_URL", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN_LECTURA", raising=False)
    d = client.get("/api/entornos/observabilidad/metricas").json()
    assert d["tarjetas"] == [] and "GRAFANA_TOKEN_LECTURA" in d["errores"][0]


def test_exige_el_pin_y_solo_pruebas(grafana, monkeypatch):
    assert TestClient(main.app).get("/api/entornos/observabilidad/metricas").status_code == 403
    assert grafana.pedidos == [], "un pedido sin pase llegó a tocar Grafana"
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    assert client.get("/api/entornos/observabilidad/metricas").status_code == 400
    assert grafana.pedidos == []


def test_la_pantalla_trae_los_graficos_y_el_detalle_de_errores():
    html = client.get("/entornos").text
    for pieza in ('id="obs-graficos"', "/api/entornos/observabilidad/metricas", "dibujarGrafico", "sin iniciar sesión",
                  "/api/entornos/observabilidad/sentry/evento/", "Ver detalle", "obs-ver-detalle"):
        assert pieza in html, pieza


# ---------------------------------------------------------------- detalle de un error de Sentry
EVENTO = "52f31cff38134b299b78962a29d5004e"


def _evento_sentry():
    return {"title": "ValueError: x", "dateCreated": "2026-09-20T03:00:00Z",
            "entries": [{"type": "exception", "data": {"values": [{
                "type": "ValueError", "value": "consulta rota",
                "stacktrace": {"frames": [
                    {"filename": "starlette/routing.py", "lineNo": 10, "function": "app", "inApp": False},
                    {"filename": "main.py", "lineNo": 4310, "function": "ruta", "inApp": True,
                     "context": [[4309, "antes"], [4310, "    return dashboard.kpis(ses, f)"]]},
                    {"filename": "dashboard.py", "lineNo": 212, "function": "kpis", "inApp": True, "context": []}]}}]}}],
            "tags": [{"key": "codigo", "value": "E-INTERNO-00"}, {"key": "ref", "value": "abc12345"},
                     {"key": "browser", "value": "no-se-muestra"}, {"key": "server_name", "value": "no-se-muestra"}]}


@pytest.fixture
def sentry(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "sntryu_TOKEN_de_prueba_9999")
    pedidos = []
    monkeypatch.setattr(sp, "_pedir", lambda ruta, params: (pedidos.append(ruta), _evento_sentry())[1])
    return pedidos


def test_el_detalle_muestra_los_pasos_de_la_app_del_mas_reciente_al_mas_viejo(sentry):
    d = client.get(f"/api/entornos/observabilidad/sentry/evento/{EVENTO}").json()
    assert d["tipo"] == "ValueError" and d["mensaje"] == "consulta rota"
    assert [p["archivo"] for p in d["pasos"]] == ["dashboard.py", "main.py"]      # sin starlette, al revés
    assert d["pasos"][1]["codigo"] == "return dashboard.kpis(ses, f)" and d["pasos"][1]["linea"] == 4310
    assert sentry == [f"/projects/{sp._cfg()['org']}/{sp._cfg()['proyecto']}/events/{EVENTO}/"]


def test_del_detalle_solo_salen_las_etiquetas_permitidas(sentry):
    d = client.get(f"/api/entornos/observabilidad/sentry/evento/{EVENTO}").json()
    assert d["etiquetas"] == {"codigo": "E-INTERNO-00", "ref": "abc12345"}
    assert "no-se-muestra" not in str(d)


@pytest.mark.parametrize("malo", ["abc", "../../etc/passwd", "G" * 32, EVENTO + "0", EVENTO.upper()])
def test_un_identificador_raro_no_llega_a_sentry(sentry, malo):
    r = client.get(f"/api/entornos/observabilidad/sentry/evento/{malo}")
    assert r.status_code in (404, 422) and sentry == []


def test_un_sentry_caido_en_el_detalle_es_un_502_legible(monkeypatch):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "sntryu_TOKEN_de_prueba_9999")
    def caido(ruta, params):
        raise sp.ErrorSentry("Sentry respondió HTTP 500.")
    monkeypatch.setattr(sp, "_pedir", caido)
    r = client.get(f"/api/entornos/observabilidad/sentry/evento/{EVENTO}")
    assert r.status_code == 502 and "500" in r.json()["detail"]


def test_el_detalle_exige_el_pin(sentry):
    assert TestClient(main.app).get(f"/api/entornos/observabilidad/sentry/evento/{EVENTO}").status_code == 403
    assert sentry == []
