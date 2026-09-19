"""Monitor de uptime de Pruebas (observabilidad/aplicar_uptime.py).
Plan en docs/chat/2026-09-19-plan-observabilidad.md.

Lo que se prueba sin red: que la configuración se valide antes de tocar Grafana, que
las ejecuciones por mes se mantengan bajo el tope gratuito, y que los cuerpos que se
le mandan a Synthetic Monitoring y a las reglas de alerta sean los que se quieren:

- la alerta dispara solo si fallan TODAS las ubicaciones (max, no min ni avg) y solo
  después de los minutos pedidos: un solo sitio caído no es una caída;
- un monitor que dejó de reportar NO se calla (NoData avisa);
- un 200 con otro cuerpo no cuenta como "la app vive".

Correr con: .venv/Scripts/python.exe -m pytest test_observabilidad_uptime.py -q
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "observabilidad"))
import aplicar_grafana as ag
import aplicar_uptime as up

CFG = ag.cargar_config()
APP, BASE = CFG["uptime"]["checks"]


def _con(**cambios):
    c = copy.deepcopy(CFG)
    c["uptime"].update(cambios)
    return c


def test_la_configuracion_del_repo_es_valida():
    assert ag.validar(CFG) == []
    assert up.validar_uptime(CFG) == []


def test_las_ejecuciones_del_mes_entran_en_el_tope_gratuito():
    n = up.ejecuciones_por_mes(CFG)
    # 2 checks x 2 ubicaciones: healthz cada 2 min, readyz cada 3 min
    assert n == (30 * 24 * 3600 // 120 + 30 * 24 * 3600 // 180) * 2 == 72000
    assert n <= CFG["uptime"]["tope_ejecuciones_mes"] == 100000


def test_pasarse_del_tope_se_rechaza_antes_de_crear_nada():
    c = copy.deepcopy(CFG)
    c["uptime"]["checks"][0]["frecuencia_s"] = 60
    c["uptime"]["checks"][1]["frecuencia_s"] = 60
    assert any("pasan del tope" in e for e in up.validar_uptime(c))


def test_valores_invalidos_se_rechazan():
    def con_check(**cambios):
        c = copy.deepcopy(CFG)
        c["uptime"]["checks"][0].update(cambios)
        return up.validar_uptime(c)
    assert con_check(ruta="healthz")                   # sin barra inicial
    assert con_check(frecuencia_s=10)                  # menos de un minuto
    assert con_check(timeout_s=30)                     # SM no admite más de 10 s en HTTP
    assert con_check(timeout_s=120, frecuencia_s=120)  # el timeout no puede igualar el intervalo
    assert con_check(falla_minutos=0)
    assert _con(probes=[])["uptime"] and up.validar_uptime(_con(probes=[]))
    assert up.validar_uptime(_con(base_url="http://inseguro"))
    duplicado = copy.deepcopy(CFG)
    duplicado["uptime"]["checks"][1]["job"] = duplicado["uptime"]["checks"][0]["job"]
    assert any("repetido" in e for e in up.validar_uptime(duplicado))


def test_el_check_pega_al_endpoint_correcto_desde_las_ubicaciones_pedidas():
    p = up.payload_check(CFG, APP, [7, 17])
    assert p["target"] == "https://mitrabajo-pruebas.onrender.com/healthz"
    assert p["frequency"] == 120000 and p["timeout"] == 10000 and p["probes"] == [7, 17]
    assert p["enabled"] is True and p["alertSensitivity"] == "none"
    etiquetas = {e["name"]: e["value"] for e in p["labels"]}
    assert etiquetas == {"entorno": "pruebas", "servicio": "app"}
    assert up.payload_check(CFG, BASE, [7])["target"].endswith("/readyz")


def test_un_200_con_otro_cuerpo_no_cuenta_como_la_app_viva():
    http = up.payload_check(CFG, APP, [7])["settings"]["http"]
    assert http["validStatusCodes"] == [200]
    regexp = http["failIfBodyNotMatchesRegexp"][0]
    import re
    assert re.search(regexp, '{"ok":true}') and re.search(regexp, '{"ok": true}')
    assert not re.search(regexp, "<html>Bad gateway</html>")
    assert not re.search(regexp, '{"ok":false,"motivo":"la base no respondió"}')


def test_actualizar_un_check_existente_conserva_su_id():
    p = up.payload_check(CFG, APP, [7], existente={"id": 42, "tenantId": 5822})
    assert p["id"] == 42 and p["tenantId"] == 5822


def test_la_alerta_dispara_solo_si_fallan_todas_las_ubicaciones_durante_el_tiempo_pedido():
    r = up.payload_regla(CFG, APP)
    consulta = r["data"][0]["model"]["expr"]
    assert consulta == 'max by (job) (probe_success{job="colm3na-pruebas-healthz"})'
    assert "max by" in consulta and "min by" not in consulta      # el MEJOR resultado: todas caídas
    assert r["for"] == "3m" and up.payload_regla(CFG, BASE)["for"] == "5m"
    umbral = r["data"][2]["model"]["conditions"][0]["evaluator"]
    assert umbral == {"params": [1], "type": "lt"}                # probe_success < 1
    assert r["condition"] == "C"


def test_un_monitor_que_dejo_de_reportar_no_se_calla():
    r = up.payload_regla(CFG, APP)
    assert r["noDataState"] == "NoData" and r["execErrState"] == "Error"


def test_la_regla_lleva_las_etiquetas_que_agrupan_el_aviso_y_vive_en_la_carpeta_de_pruebas():
    r = up.payload_regla(CFG, BASE)
    assert r["labels"] == {"entorno": "pruebas", "evento": "base-caida"}
    assert set(CFG["alertas"]["group_by"]) <= {"alertname", *r["labels"]}   # la política puede agrupar
    assert r["folderUID"] == CFG["grafana"]["carpeta_uid"] == "colm3na-pruebas"
    assert r["title"] == "Base de datos no responde (Pruebas)"
    assert "docs/OPERATIVA.md" in r["annotations"]["description"]           # qué hacer cuando llega


def test_las_reglas_tienen_uid_estable_para_poder_actualizarlas_sin_duplicar():
    assert up.uid_de_regla(CFG, APP) == "colm3na-pruebas-app-caida"
    assert up.uid_de_regla(CFG, BASE) == "colm3na-pruebas-base-caida"
    assert up.payload_regla(CFG, APP)["uid"] == up.payload_regla(CFG, APP)["uid"]


def test_el_script_de_uptime_no_lleva_ningun_token():
    for archivo in ("aplicar_uptime.py", "config.json"):
        t = (Path(__file__).parent / "observabilidad" / archivo).read_text(encoding="utf-8")
        assert "glsa_" not in t.replace("glsa_...", "") and "rnd_" not in t
