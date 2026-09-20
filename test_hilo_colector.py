"""Segunda vía del colector de métricas: el hilo dentro de la app de Pruebas
(observabilidad/hilo_colector.py) y la función `ejecutar` que comparte con GitHub Actions.

El 2026-09-19 (21:38) el cron de GitHub tardó más de 20 minutos en correr por primera
vez y el tablero se quedó en "No data". Un colector que a veces no corre es el problema
que se quiere resolver, así que hay dos vías que se cubren entre sí. Lo que se prueba:

- cuándo arranca el hilo (solo en el entorno del colector, con las dos claves, y no
  si se lo apaga a mano) y que nunca arranque dos veces;
- que un error en una corrida no lo mate, y que si el bucle muriera por algo
  imprevisto, reviva solo;
- que una escritura rechazada por puntos repetidos o viejos no cuente como falla,
  pero una rechazada por otra cosa (token inválido, por ejemplo) sí;
- que si Render falla en TODAS las métricas la corrida cuente como fallida.

Correr con: .venv/Scripts/python.exe -m pytest test_hilo_colector.py -q
"""
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ))
from observabilidad import aplicar_grafana as ag
from observabilidad import colector_render as cr
from observabilidad import hilo_colector as hc

CFG = ag.cargar_config()
ENV_OK = {"RENDER_API_KEY": "rnd_x", "GRAFANA_METRICS_TOKEN": "glc_x"}


def _serie(v=1.0):
    return [{"labels": [{"field": "resource", "value": "srv-x"}],
             "values": [{"timestamp": "2026-09-20T00:00:00Z", "value": v}]}]


# ------------------------- cuándo arranca -------------------------
def test_arranca_solo_en_el_entorno_del_colector_con_las_dos_claves():
    assert hc.debe_correr("pruebas", CFG, ENV_OK) == (True, "ok")
    ok, motivo = hc.debe_correr("demo", CFG, ENV_OK)
    assert not ok and "demo" in motivo
    ok, motivo = hc.debe_correr("pruebas", CFG, {"RENDER_API_KEY": "x"})
    assert not ok and "GRAFANA_METRICS_TOKEN" in motivo
    ok, motivo = hc.debe_correr("pruebas", CFG, {"GRAFANA_METRICS_TOKEN": "x"})
    assert not ok and "RENDER_API_KEY" in motivo
    assert not hc.debe_correr("pruebas", CFG, {**ENV_OK, "RENDER_API_KEY": "  "})[0]


def test_se_puede_apagar_a_mano():
    ok, motivo = hc.debe_correr("pruebas", CFG, {**ENV_OK, "COLECTOR_METRICAS": "OFF"})
    assert not ok and "COLECTOR_METRICAS" in motivo


def test_la_app_lo_arranca_solo_en_pruebas_y_sin_poder_tumbar_el_arranque():
    fuente = (RAIZ / "main.py").read_text(encoding="utf-8")
    i = fuente.index("hilo_colector.arrancar(entorno.ENTORNO)")
    bloque = fuente[fuente.rindex('if entorno.ENTORNO == "pruebas":', 0, i):i + 200]
    assert "try:" in bloque and "except Exception" in bloque


# ------------------------- el hilo -------------------------
def _limpiar(monkeypatch):
    monkeypatch.setattr(hc, "_hilo", None)
    monkeypatch.setattr(hc, "PISO_ESPERA", 0.02)
    monkeypatch.setattr(hc, "REINICIO_ESPERA", 0.02)
    hc.estado.update(corridas=0, ultima_utc=None, ultimo_resultado="")
    monkeypatch.setenv("RENDER_API_KEY", "rnd_x")
    monkeypatch.setenv("GRAFANA_METRICS_TOKEN", "glc_x")
    monkeypatch.delenv("COLECTOR_METRICAS", raising=False)


def _esperar(condicion, segundos=5):
    fin = time.time() + segundos
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def test_el_hilo_corre_una_y_otra_vez_y_solo_hay_uno(monkeypatch):
    _limpiar(monkeypatch)
    llamadas = []
    monkeypatch.setattr(cr, "ejecutar", lambda cfg, clave, token, **kw: (
        llamadas.append((clave, token)) or {"series": 21, "puntos": 400, "errores": [], "estado_http": 200, "ok": True}))
    assert hc.arrancar("pruebas", intervalo=0, espera_inicial=0) is True
    assert hc.arrancar("pruebas", intervalo=0, espera_inicial=0) is False        # no arranca dos veces
    assert _esperar(lambda: len(llamadas) >= 3), "el hilo no siguió corriendo"
    assert all(c == ("rnd_x", "glc_x") for c in llamadas)
    assert hc.estado["corridas"] >= 3 and "21 series" in hc.estado["ultimo_resultado"]
    assert sum(1 for t in threading.enumerate() if t.name == "colector-metricas") == 1


def test_un_error_en_una_corrida_no_mata_el_hilo(monkeypatch):
    _limpiar(monkeypatch)
    n = []

    def ejecutar(cfg, clave, token, **kw):
        n.append(1)
        if len(n) == 1:
            raise RuntimeError("Render se cayó")
        return {"series": 1, "puntos": 1, "errores": [], "estado_http": 200, "ok": True}

    monkeypatch.setattr(cr, "ejecutar", ejecutar)
    hc.arrancar("pruebas", intervalo=0, espera_inicial=0)
    assert _esperar(lambda: len(n) >= 3)
    assert _esperar(lambda: "error inesperado" not in hc.estado["ultimo_resultado"])   # ya se recuperó


def test_si_el_bucle_muere_por_algo_imprevisto_revive_solo(monkeypatch):
    _limpiar(monkeypatch)
    vidas = []

    def bucle(cfg, intervalo, espera):
        vidas.append(1)
        if len(vidas) < 3:
            raise KeyError("algo que nadie previó")
        vidas.append("viva")

    monkeypatch.setattr(hc, "_bucle", bucle)
    hc.arrancar("pruebas", intervalo=0, espera_inicial=0)
    assert _esperar(lambda: "viva" in vidas), "el hilo no revivió tras morir"


def test_una_corrida_nunca_lanza(monkeypatch):
    def boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(cr, "ejecutar", boom)
    texto = hc.una_corrida(CFG, "k", "t")
    assert "error inesperado" in texto and "ValueError" in texto


def test_el_resultado_de_una_corrida_fallida_lo_dice(monkeypatch):
    monkeypatch.setattr(cr, "ejecutar", lambda *a, **k: {
        "series": 3, "puntos": 9, "errores": ["cpu de x: HTTP 500"], "estado_http": 401, "ok": False})
    texto = hc.una_corrida(CFG, "k", "t")
    assert "FALLÓ" in texto and "HTTP 401" in texto


# ------------------------- ejecutar / escritura aceptable -------------------------
def test_puntos_repetidos_o_viejos_no_son_una_falla_pero_otro_rechazo_si():
    assert cr.escritura_aceptable(200, "")
    assert cr.escritura_aceptable(400, "err-mimir-sample-timestamp-too-old ...")
    assert cr.escritura_aceptable(400, "sample timestamp out of bounds: duplicate sample for timestamp")
    assert cr.escritura_aceptable(400, "the sample has been rejected because another sample ... out-of-order")
    assert not cr.escritura_aceptable(401, "authentication error: invalid token")
    assert not cr.escritura_aceptable(500, "internal error")


def _fakes(monkeypatch, render_falla=False, http=(200, "")):
    def pedir(clave, metrica, recurso, ini, fin, res, extra):
        if render_falla:
            raise cr.ErrorRender(f"{metrica}: HTTP 500")
        return _serie()
    escrituras = []
    monkeypatch.setattr(cr, "pedir_render", pedir)
    monkeypatch.setattr(cr.rw, "escribir", lambda url, usuario, token, series: escrituras.append(series) or http)
    return escrituras


def test_ejecutar_lee_y_escribe(monkeypatch):
    escrituras = _fakes(monkeypatch)
    r = cr.ejecutar(CFG, "k", "t", pausa=0)
    assert r["ok"] and r["estado_http"] == 200 and r["series"] > 0 and len(escrituras) == 1
    nombres = {s[0]["__name__"] for s in escrituras[0]}
    assert "render_colector_ultima_corrida_segundos" in nombres and "render_cpu_cores" in nombres


def test_si_render_falla_en_todo_la_corrida_cuenta_como_fallida(monkeypatch):
    _fakes(monkeypatch, render_falla=True)
    r = cr.ejecutar(CFG, "k", "t", pausa=0)
    assert r["ok"] is False and r["errores"]


def test_un_token_invalido_de_grafana_es_una_falla(monkeypatch):
    _fakes(monkeypatch, http=(401, "invalid token"))
    assert cr.ejecutar(CFG, "k", "t", pausa=0)["ok"] is False


def test_un_rechazo_por_puntos_viejos_no_es_una_falla(monkeypatch):
    _fakes(monkeypatch, http=(400, "err-mimir-sample-timestamp-too-old"))
    assert cr.ejecutar(CFG, "k", "t", pausa=0)["ok"] is True


def test_cada_via_se_identifica_para_poder_ver_que_las_dos_estan_vivas(monkeypatch):
    escrituras = _fakes(monkeypatch)
    cr.ejecutar(CFG, "k", "t", pausa=0, via="app")
    cr.ejecutar(CFG, "k", "t", pausa=0)
    vias = [next(s[0]["via"] for s in tanda if s[0]["__name__"] == "render_colector_ultima_corrida_segundos")
            for tanda in escrituras]
    assert vias == ["app", "manual"]
    assert all("via" not in s[0] for s in escrituras[0] if s[0]["__name__"] == "render_cpu_cores")   # solo la salud lleva `via`


def test_el_hilo_de_la_app_se_identifica_como_app(monkeypatch):
    vistas = []
    monkeypatch.setattr(cr, "ejecutar", lambda cfg, clave, token, **kw: (
        vistas.append(kw.get("via")) or {"series": 1, "puntos": 1, "errores": [], "estado_http": 200, "ok": True}))
    hc.una_corrida(CFG, "k", "t")
    assert vistas == ["app"]


def test_el_dry_run_no_escribe(monkeypatch):
    escrituras = _fakes(monkeypatch)
    r = cr.ejecutar(CFG, "k", "", dry_run=True, pausa=0)
    assert escrituras == [] and r["estado_http"] is None and r["series"] > 0


def test_la_ventana_es_de_una_hora_para_no_pasarse_del_limite_de_grafana():
    """Grafana Cloud aceptó puntos de hace 1 h y rechazó los de hace 2 h."""
    assert CFG["metricas_render"]["ventana_min"] == 60
