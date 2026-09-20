"""Pestaña "Observabilidad" de /entornos (docs/chat/2026-09-19-plan-observabilidad.md).

La app es la PUERTA, no el motor: lee de Grafana y guarda dos ajustes. Nada de
esto toca Grafana de verdad: se reemplaza `Grafana.pedir` por un Grafana de
mentira que anota lo que le mandan. Lo que se prueba:

- el gate (PIN de la landing, solo Pruebas);
- el semáforo, incluido "gris" cuando todavía no hay reglas (un verde sin reglas
  mentiría: nadie estaría mirando nada);
- que guardar valide ANTES de escribir, conserve lo que no se edita y use el token
  de configuración para escribir y el de lectura para leer;
- que si Grafana no responde la pantalla siga viva y lo diga;
- que ningún token salga en una respuesta.

Correr con: .venv/Scripts/python.exe -m pytest test_entornos_observabilidad.py -q
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
from observabilidad import panel
from fastapi.testclient import TestClient

TOKEN_LECTURA = "glsa_LECTURA_de_prueba_0000"
TOKEN_CONFIG = "glsa_CONFIG_de_prueba_1111"

db.crear_tablas()
client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "13571357"}, follow_redirects=False).status_code == 303


class GrafanaDeMentira:
    """Reemplaza a Grafana.pedir: responde lo que Grafana respondería y anota
    cada pedido (método, ruta, quién lo hizo, cuerpo)."""
    def __init__(self):
        self.pedidos = []
        self.reglas = []
        self.caido = False
        self.politica = {"receiver": "sdn-mail", "group_by": ["alertname", "entorno"],
                         "group_wait": "1m", "group_interval": "5m",
                         "repeat_interval": "1d", "routes": []}
        self.punto = {"uid": "abc123", "name": "sdn-mail", "type": "email",
                      "settings": {"addresses": "snavello@gmail.com", "singleEmail": True},
                      "disableResolveMessage": False}

    def pedir(self, cliente, metodo, ruta, cuerpo=None, editable_desde_la_ui=False):
        self.pedidos.append({"metodo": metodo, "ruta": ruta, "token": cliente.token, "cuerpo": cuerpo})
        if self.caido:
            raise OSError("sin conexión")
        if metodo == "GET" and ruta == "/api/prometheus/grafana/api/v1/rules":
            return 200, {"data": {"groups": [{"file": "Colm3na · Pruebas", "rules": self.reglas}]}}
        if metodo == "GET" and ruta == "/api/v1/provisioning/policies":
            return 200, dict(self.politica)
        if metodo == "GET" and ruta == "/api/v1/provisioning/contact-points":
            return 200, [dict(self.punto)]
        if metodo == "PUT" and ruta == "/api/v1/provisioning/policies":
            self.politica = dict(cuerpo)
            return 202, {}
        if metodo in ("PUT", "POST") and ruta.startswith("/api/v1/provisioning/contact-points"):
            self.punto = dict(cuerpo, uid=self.punto["uid"])
            return 202, {}
        if metodo == "GET" and ruta == "/api/frontend/settings":
            return 200, {"namespace": "stacks-1"}
        if metodo == "POST" and ruta.endswith("/test"):
            return 200, {"status": "success"}
        return 404, {"message": "no existe en el Grafana de mentira"}

    def escrituras(self):
        return [p for p in self.pedidos if p["metodo"] in ("PUT", "POST")]


@pytest.fixture
def grafana(monkeypatch):
    monkeypatch.setenv("GRAFANA_URL", "https://prueba.grafana.net")
    monkeypatch.setenv("GRAFANA_TOKEN_LECTURA", TOKEN_LECTURA)
    monkeypatch.setenv("GRAFANA_TOKEN_CONFIG", TOKEN_CONFIG)
    monkeypatch.delenv("SENTRY_URL", raising=False)
    monkeypatch.setattr(panel, "_ultima_prueba", -panel.ESPERA_ENTRE_PRUEBAS)
    monkeypatch.setattr(panel, "_ultima_actualizacion", -panel.ESPERA_ENTRE_ACTUALIZACIONES)
    monkeypatch.setenv("RENDER_API_KEY", "rnd_CLAVE_de_prueba_2222")
    monkeypatch.setenv("GRAFANA_METRICS_TOKEN", "glc_METRICAS_de_prueba_3333")
    falso = GrafanaDeMentira()
    monkeypatch.setattr(ag.Grafana, "pedir",
                        lambda self, metodo, ruta, cuerpo=None, editable_desde_la_ui=False:
                        falso.pedir(self, metodo, ruta, cuerpo, editable_desde_la_ui))
    return falso


def _regla(nombre, estado="inactive", salud="ok"):
    return {"name": nombre, "state": estado, "health": salud, "labels": {"entorno": "pruebas"}}


# ------------------------- gate -------------------------
def test_sin_pin_no_se_puede_ni_mirar_ni_cambiar(grafana):
    otro = TestClient(main.app)
    assert otro.get("/api/entornos/observabilidad").status_code == 403
    assert otro.post("/entornos/observabilidad/config",
                     json={"email": "x@y.com", "repeat_interval": "24h"}).status_code == 403
    assert otro.post("/entornos/observabilidad/probar-mail").status_code == 403
    assert grafana.pedidos == [], "un pedido sin pase llegó a tocar Grafana"


def test_en_demo_todo_se_rechaza_aunque_se_llame_a_mano(grafana, monkeypatch):
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    assert client.get("/api/entornos/observabilidad").status_code == 400
    r = client.post("/entornos/observabilidad/config", json={"email": "x@y.com", "repeat_interval": "24h"})
    assert r.status_code == 400
    assert grafana.pedidos == []


def test_la_landing_muestra_la_pestana_en_pruebas_y_deshabilitada_en_demo(grafana, monkeypatch):
    pruebas = client.get("/entornos").text
    assert 'data-tab="observabilidad"' in pruebas and 'id="obs-form"' in pruebas
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    demo = client.get("/entornos").text
    assert 'data-tab="observabilidad"' in demo and 'id="obs-form"' not in demo


# ------------------------- semáforo y configuración -------------------------
@pytest.mark.parametrize("reglas, semaforo", [
    ([], "gris"),
    ([_regla("App caída"), _regla("Base caída")], "verde"),
    ([_regla("App caída"), _regla("CPU alta", "pending")], "amarillo"),
    ([_regla("App caída", salud="error")], "amarillo"),
    ([_regla("App caída", "firing"), _regla("CPU alta", "pending")], "rojo"),
])
def test_el_semaforo_sale_de_las_reglas_y_sin_reglas_no_es_verde(grafana, reglas, semaforo):
    grafana.reglas = reglas
    d = client.get("/api/entornos/observabilidad").json()
    assert d["alertas"]["semaforo"] == semaforo
    assert d["alertas"]["total"] == len(reglas)


def test_el_estado_trae_la_configuracion_vigente_de_grafana_y_los_enlaces(grafana):
    d = client.get("/api/entornos/observabilidad").json()
    assert d["configurado"] and d["puede_configurar"] and d["errores"] == []
    assert d["config"]["email"] == "snavello@gmail.com"
    # Grafana guarda "24h" como "1d": la app lo normaliza para que el selector
    # muestre 24 h y no caiga en la primera opción (1 h). Lo encontró la
    # verificación en el navegador contra el Grafana real.
    assert d["config"]["repeat_interval"] == "24h"
    assert d["tablero_url"] == "https://prueba.grafana.net/d/colm3na-pruebas-estado"
    assert d["sentry_url"] == ""


def test_leer_usa_solo_el_token_de_lectura(grafana):
    client.get("/api/entornos/observabilidad")
    assert grafana.pedidos and all(p["token"] == TOKEN_LECTURA for p in grafana.pedidos)
    assert not grafana.escrituras()


# ------------------------- guardar -------------------------
def test_guardar_escribe_con_el_token_de_config_y_conserva_lo_demas(grafana):
    r = client.post("/entornos/observabilidad/config",
                    json={"email": "otro@ejemplo.com", "repeat_interval": "12h",
                          "avisar_al_resolverse": False})
    assert r.status_code == 200, r.text
    escrituras = grafana.escrituras()
    assert {e["ruta"].split("/")[-1] for e in escrituras} >= {"policies"}
    assert all(e["token"] == TOKEN_CONFIG for e in escrituras), "escribió con el token de lectura"
    assert grafana.punto["settings"]["addresses"] == "otro@ejemplo.com"
    assert grafana.punto["disableResolveMessage"] is True
    assert grafana.politica["repeat_interval"] == "12h"
    # lo que la pantalla no edita se conserva como estaba en Grafana
    assert grafana.politica["group_wait"] == "1m" and grafana.politica["group_interval"] == "5m"
    assert grafana.politica["group_by"] == ["alertname", "entorno"]
    assert r.json()["config"]["repeat_interval"] == "12h"


@pytest.mark.parametrize("cuerpo", [
    {"email": "sin-arroba", "repeat_interval": "24h"},
    {"email": "", "repeat_interval": "24h"},
    {"email": "ok@ejemplo.com", "repeat_interval": "1m"},       # un mail por minuto: no
    {"email": "ok@ejemplo.com", "repeat_interval": "cada rato"},
    {"email": "ok@ejemplo.com", "repeat_interval": ""},
])
def test_un_valor_invalido_se_rechaza_antes_de_escribir(grafana, cuerpo):
    r = client.post("/entornos/observabilidad/config", json=cuerpo)
    assert r.status_code == 400, r.text
    assert not grafana.escrituras(), "escribió en Grafana con un valor inválido"


def test_sin_el_token_de_config_no_se_puede_guardar_pero_si_mirar(grafana, monkeypatch):
    monkeypatch.delenv("GRAFANA_TOKEN_CONFIG")
    assert client.get("/api/entornos/observabilidad").json()["puede_configurar"] is False
    r = client.post("/entornos/observabilidad/config", json={"email": "ok@ejemplo.com", "repeat_interval": "24h"})
    assert r.status_code == 502 and "GRAFANA_TOKEN_CONFIG" in r.json()["detail"]
    assert not grafana.escrituras()


# ------------------------- mail de prueba -------------------------
def test_el_mail_de_prueba_sale_una_vez_por_minuto(grafana):
    assert client.post("/entornos/observabilidad/probar-mail").status_code == 200
    segundo = client.post("/entornos/observabilidad/probar-mail")
    assert segundo.status_code == 429 and "esperá" in segundo.json()["detail"]
    pruebas = [e for e in grafana.escrituras() if e["ruta"].endswith("/test")]
    assert len(pruebas) == 1 and pruebas[0]["token"] == TOKEN_CONFIG


# ------------------------- cuando algo falta o falla -------------------------
def test_sin_variables_la_pestana_dice_que_falta_en_vez_de_romperse(monkeypatch):
    for v in ("GRAFANA_URL", "GRAFANA_TOKEN_LECTURA", "GRAFANA_TOKEN_CONFIG"):
        monkeypatch.delenv(v, raising=False)
    r = client.get("/api/entornos/observabilidad")
    assert r.status_code == 200
    d = r.json()
    assert d["configurado"] is False and d["alertas"] is None and d["config"] is None
    assert any("Falta" in e for e in d["errores"])


def test_si_grafana_no_responde_la_pantalla_sigue_viva_y_lo_dice(grafana):
    grafana.caido = True
    r = client.get("/api/entornos/observabilidad")
    assert r.status_code == 200, "un Grafana caído no puede tumbar /entornos"
    d = r.json()
    assert d["alertas"] is None and d["config"] is None and len(d["errores"]) == 2
    assert d["tablero_url"], "el enlace al tablero tiene que seguir estando: es la salida de emergencia"


def test_ningun_token_sale_en_una_respuesta(grafana):
    textos = [client.get("/api/entornos/observabilidad").text,
              client.post("/entornos/observabilidad/config",
                          json={"email": "ok@ejemplo.com", "repeat_interval": "24h"}).text,
              client.get("/entornos").text]
    for t in textos:
        assert TOKEN_LECTURA not in t and TOKEN_CONFIG not in t


# ------------------------- botón "Actualizar métricas ahora" -------------------------
def _ejecutar_falso(monkeypatch, ok=True, errores=(), http=200):
    llamadas = []

    def ejecutar(cfg, clave, token, **kw):
        llamadas.append({"clave": clave, "token": token, **kw})
        return {"series": 25, "puntos": 1096, "errores": list(errores), "estado_http": http, "ok": ok}

    monkeypatch.setattr(panel.cr, "ejecutar", ejecutar)
    return llamadas


def test_el_boton_corre_el_colector_ahora_y_dice_cuanto_dejo(grafana, monkeypatch):
    llamadas = _ejecutar_falso(monkeypatch)
    r = client.post("/entornos/observabilidad/actualizar-metricas")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "series": 25, "puntos": 1096, "errores_de_render": 0}
    (l,) = llamadas
    assert l["via"] == "boton" and l["clave"] == "rnd_CLAVE_de_prueba_2222" and l["token"] == "glc_METRICAS_de_prueba_3333"
    assert l["pausa"] < 1, "el botón tiene que ser más rápido que el colector programado"


def test_el_boton_avisa_si_alguna_metrica_de_render_fallo(grafana, monkeypatch):
    _ejecutar_falso(monkeypatch, errores=["cpu de x: HTTP 500", "memory de x: HTTP 500"])
    assert client.post("/entornos/observabilidad/actualizar-metricas").json()["errores_de_render"] == 2


def test_el_boton_se_puede_apretar_una_vez_por_minuto(grafana, monkeypatch):
    llamadas = _ejecutar_falso(monkeypatch)
    assert client.post("/entornos/observabilidad/actualizar-metricas").status_code == 200
    segundo = client.post("/entornos/observabilidad/actualizar-metricas")
    assert segundo.status_code == 429 and "esperá" in segundo.json()["detail"]
    assert len(llamadas) == 1, "el segundo clic no tiene que gastar consultas de la API de Render"


def test_el_boton_dice_que_falta_en_vez_de_romperse(grafana, monkeypatch):
    _ejecutar_falso(monkeypatch)
    monkeypatch.delenv("GRAFANA_METRICS_TOKEN")
    r = client.post("/entornos/observabilidad/actualizar-metricas")
    assert r.status_code == 502 and "GRAFANA_METRICS_TOKEN" in r.json()["detail"]


def test_si_el_colector_no_pudo_escribir_el_boton_lo_dice(grafana, monkeypatch):
    _ejecutar_falso(monkeypatch, ok=False, http=401)
    r = client.post("/entornos/observabilidad/actualizar-metricas")
    assert r.status_code == 502 and "401" in r.json()["detail"]


def test_el_boton_exige_el_pin_y_solo_pruebas(grafana, monkeypatch):
    llamadas = _ejecutar_falso(monkeypatch)
    assert TestClient(main.app).post("/entornos/observabilidad/actualizar-metricas").status_code == 403
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    assert client.post("/entornos/observabilidad/actualizar-metricas").status_code == 400
    assert llamadas == [], "un pedido sin permiso llegó a consultar Render"


def test_las_claves_no_salen_en_la_respuesta_del_boton(grafana, monkeypatch):
    _ejecutar_falso(monkeypatch)
    texto = client.post("/entornos/observabilidad/actualizar-metricas").text
    assert "rnd_CLAVE" not in texto and "glc_METRICAS" not in texto


def test_la_pestana_trae_el_boton_y_su_manejador():
    html = client.get("/entornos").text
    assert 'id="obs-actualizar"' in html and "Actualizar métricas ahora" in html
    assert "/entornos/observabilidad/actualizar-metricas" in html
