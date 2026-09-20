"""Disparador del colector (observabilidad/aplicar_disparador.py): un check de Grafana
que cada 5 minutos le pide a GitHub que corra el workflow del colector.

El cron de GitHub Actions no disparó ni una vez en más de una hora (2026-09-19); un
`workflow_dispatch` corre al instante, y el reloj lo pone algo puntual. Sin red. Lo que
se prueba: que el pedido sea el que GitHub acepta, que el token nunca salga del check,
que un token vencido se note y que la cuenta de ejecuciones siga entrando en el tope
gratuito.

Correr con: .venv/Scripts/python.exe -m pytest test_observabilidad_disparador.py -q
"""
import copy
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "observabilidad"))
import aplicar_disparador as ad
import aplicar_grafana as ag
import aplicar_uptime as up

CFG = ag.cargar_config()
FLUJO = (RAIZ / ".github" / "workflows" / "metricas-render.yml").read_text(encoding="utf-8")


def test_la_configuracion_es_valida_y_entra_en_el_tope_gratuito():
    assert ad.validar_disparador(CFG) == []
    total = up.ejecuciones_por_mes(CFG) + ad.ejecuciones_por_mes(CFG)
    assert total == 72000 + 8640 <= CFG["uptime"]["tope_ejecuciones_mes"]


def test_pasarse_del_tope_se_rechaza():
    c = copy.deepcopy(CFG)
    c["uptime"]["tope_ejecuciones_mes"] = 80000                # 72.000 del uptime + 8.640 del disparador = 80.640
    assert any("pasan del tope" in e for e in ad.validar_disparador(c))
    c["disparador"]["frecuencia_s"] = 120                      # 72.000 + 21.600 = 93.600: todavía entra en 100.000
    c["uptime"]["tope_ejecuciones_mes"] = 100000
    assert ad.validar_disparador(c) == []


def test_valores_invalidos_se_rechazan():
    def con(**cambios):
        c = copy.deepcopy(CFG)
        c["disparador"].update(cambios)
        return ad.validar_disparador(c)
    assert con(repo="sin-barra") and con(frecuencia_s=30) and con(falla_minutos=0) and con(workflow="")
    assert ad.validar_disparador({}) == ["falta la sección 'disparador'"]


def test_el_pedido_es_el_que_github_acepta_para_disparar_un_workflow():
    p = ad.payload_check(CFG, "github_pat_X", 7)
    assert p["target"] == "https://api.github.com/repos/snavello/MITRABAJOC/actions/workflows/metricas-render.yml/dispatches"
    h = p["settings"]["http"]
    assert h["method"] == "POST" and h["validStatusCodes"] == [204]
    assert json.loads(h["body"]) == {"ref": "main"}
    cab = {x["name"]: x["value"] for x in h["headers"]}
    assert cab["Authorization"] == "Bearer github_pat_X" and cab["Accept"] == "application/vnd.github+json"
    assert cab["X-GitHub-Api-Version"] == "2022-11-28"
    assert p["frequency"] == 300000 and p["timeout"] == 10000 and p["probes"] == [7]
    assert h["failIfNotSSL"] is True


def test_el_token_solo_vive_en_el_check_nunca_en_el_repo():
    for archivo in ("aplicar_disparador.py", "config.json"):
        t = (RAIZ / "observabilidad" / archivo).read_text(encoding="utf-8")
        assert "github_pat_" not in t.replace("github_pat_...", ""), archivo
    assert "github_pat_X" not in json.dumps(CFG)


def test_actualizar_un_check_existente_conserva_su_id():
    p = ad.payload_check(CFG, "t", 7, existente={"id": 9, "tenantId": 5822})
    assert p["id"] == 9 and p["tenantId"] == 5822


def test_un_token_vencido_se_nota_porque_el_check_falla_y_hay_alerta():
    r = ad.payload_regla(CFG)
    assert r["data"][0]["model"]["expr"] == 'max by (job) (probe_success{job="colm3na-disparador-colector"})'
    assert r["data"][2]["model"]["conditions"][0]["evaluator"] == {"params": [1], "type": "lt"}
    assert r["for"] == "15m" and r["noDataState"] == "NoData"       # que el monitor calle también avisa
    assert r["folderUID"] == "colm3na-pruebas" and r["uid"] == "colm3na-pruebas-disparador-caido"
    assert "aplicar_disparador.py" in r["annotations"]["description"]


def test_el_workflow_puede_recibir_el_disparo_y_no_se_pisa_si_llegan_varios():
    assert "workflow_dispatch:" in FLUJO
    assert "concurrency:" in FLUJO and "cancel-in-progress: false" in FLUJO
    # el workflow que se dispara es el que el disparador nombra
    assert CFG["disparador"]["workflow"] == "metricas-render.yml"
    assert (RAIZ / ".github" / "workflows" / CFG["disparador"]["workflow"]).exists()


def test_el_disparador_es_una_tercera_via_que_no_reemplaza_a_las_otras():
    """Las tres escriben lo mismo: el cron de GitHub, el hilo de la app y este disparador."""
    assert "schedule:" in FLUJO                              # el cron sigue, por si GitHub lo atiende
    assert (RAIZ / "observabilidad" / "hilo_colector.py").exists()
