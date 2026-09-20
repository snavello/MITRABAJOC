"""Vencimientos de tokens (observabilidad/aplicar_vencimientos.py y la pestaña Observabilidad).

Un token vencido rompe algo en silencio (el disparador del colector, la pestaña...). Se
avisa ANTES, por mail, con la política anti-ruido ya configurada; y la pestaña de /entornos
muestra cuánto falta. Sin red.

Correr con: .venv/Scripts/python.exe -m pytest test_observabilidad_vencimientos.py -q
"""
import copy
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "observabilidad"))
sys.path.insert(0, str(RAIZ))
import aplicar_grafana as ag
import aplicar_vencimientos as av
from observabilidad import panel

CFG = ag.cargar_config()
GITHUB = next(r for r in CFG["renovaciones"] if r["id"] == "github-disparador")


def test_la_configuracion_del_repo_es_valida():
    assert av.validar_renovaciones(CFG) == []


def test_el_token_de_github_vence_el_18_de_octubre_de_2026_y_avisa_una_semana_antes():
    assert GITHUB["vence"] == "2026-10-18" and GITHUB["aviso_dias"] == 7
    assert "aplicar_disparador.py" in GITHUB["como"] and "MITRABAJOC" in GITHUB["como"]


def test_valores_invalidos_se_rechazan():
    def con(**cambios):
        c = copy.deepcopy(CFG)
        c["renovaciones"][0].update(cambios)
        return av.validar_renovaciones(c)
    assert con(vence="18/10/2026") and con(vence="") and con(aviso_dias=0) and con(aviso_dias=365) and con(como="")
    assert av.validar_renovaciones({}) == ["renovaciones tiene que ser una lista no vacía"]
    repetido = copy.deepcopy(CFG)
    repetido["renovaciones"][1]["id"] = repetido["renovaciones"][0]["id"]
    assert any("repetido" in e for e in av.validar_renovaciones(repetido))


def test_el_token_sirve_todo_el_dia_de_su_fecha():
    """Vence al terminar el 18, hora de Buenos Aires: 2026-10-19 00:00 (-03:00) = 03:00 UTC."""
    e = av.epoch_de_vencimiento("2026-10-18")
    assert datetime.fromtimestamp(e, timezone.utc) == datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)


def test_la_regla_calcula_los_dias_que_faltan_contra_el_reloj_de_prometheus():
    r = av.payload_regla(CFG, GITHUB)
    assert r["data"][0]["model"]["expr"] == f"({av.epoch_de_vencimiento('2026-10-18')} - time()) / 86400"
    assert r["data"][2]["model"]["conditions"][0]["evaluator"] == {"params": [7], "type": "lt"}   # faltan menos de 7 días
    assert r["for"] == "0m" and r["noDataState"] == "OK"
    assert "aplicar_disparador.py" in r["annotations"]["description"] and "2026-10-18" in r["annotations"]["description"]
    assert r["uid"] == "colm3na-pruebas-vence-github-disparador" and r["ruleGroup"] == "vencimientos"
    assert r["folderUID"] == "colm3na-pruebas" and r["labels"] == {"entorno": "pruebas", "evento": "vencimiento-github-disparador"}


def test_cada_token_tiene_su_propia_regla_con_uid_estable():
    uids = {av.payload_regla(CFG, r)["uid"] for r in CFG["renovaciones"]}
    assert len(uids) == len(CFG["renovaciones"])


# ------------------------- la pestaña -------------------------
def _dias(hoy):
    return {r["id"]: r for r in panel.renovaciones(hoy)}


def test_la_pestana_dice_cuantos_dias_faltan_y_en_que_estado_esta():
    assert _dias(date(2026, 9, 20))["github-disparador"]["dias"] == 28
    assert _dias(date(2026, 9, 20))["github-disparador"]["estado"] == "ok"
    assert _dias(date(2026, 10, 11))["github-disparador"]["estado"] == "pronto"        # dentro del aviso de 7 días
    assert _dias(date(2026, 10, 15))["github-disparador"]["estado"] == "urgente"       # 3 días o menos
    assert _dias(date(2026, 10, 18))["github-disparador"]["estado"] == "urgente"       # el último día todavía sirve
    assert _dias(date(2026, 10, 19))["github-disparador"]["estado"] == "vencido"
    assert _dias(date(2026, 10, 19))["github-disparador"]["dias"] == -1


def test_el_mas_urgente_va_primero():
    orden = panel.renovaciones(date(2026, 9, 20))
    assert [r["id"] for r in orden][0] == "github-disparador"
    assert [r["dias"] for r in orden] == sorted(r["dias"] for r in orden)


def test_el_estado_de_la_pestana_incluye_los_vencimientos(monkeypatch):
    for v in ("GRAFANA_URL", "GRAFANA_TOKEN_LECTURA", "GRAFANA_TOKEN_CONFIG"):
        monkeypatch.delenv(v, raising=False)
    d = panel.estado()
    assert {r["id"] for r in d["renovaciones"]} == {"github-disparador", "grafana-app"}


def test_la_pestana_trae_el_lugar_donde_se_muestran():
    plantilla = (RAIZ / "templates" / "_observabilidad.html").read_text(encoding="utf-8")
    landing = (RAIZ / "templates" / "entornos.html").read_text(encoding="utf-8")
    assert 'id="obs-renovaciones"' in plantilla and "obs-renovaciones" in landing


def test_nada_del_repo_lleva_el_token():
    for archivo in ("aplicar_vencimientos.py", "config.json"):
        t = (RAIZ / "observabilidad" / archivo).read_text(encoding="utf-8")
        assert "github_pat_11" not in t, archivo
