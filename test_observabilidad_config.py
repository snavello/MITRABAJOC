"""Configuración de la observabilidad (observabilidad/config.json y
observabilidad/aplicar_grafana.py). Plan en docs/chat/2026-09-19-plan-observabilidad.md.

Solo lo que se puede probar sin red: que la configuración se valide ANTES de tocar
Grafana y que los cuerpos que se le mandan sean los que se quieren. Un mail mal
escrito no debe dejar la política de notificaciones apuntando a la nada, y el
intervalo de repetición de 24 h (para no agobiar en Pruebas) no se puede perder.

Correr con: .venv/Scripts/python.exe -m pytest test_observabilidad_config.py -q
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "observabilidad"))
import aplicar_grafana as ag

CFG = ag.cargar_config()


def _con(**cambios_alertas):
    c = copy.deepcopy(CFG)
    c["alertas"].update(cambios_alertas)
    return c


def test_la_configuracion_del_repo_es_valida():
    assert ag.validar(CFG) == []


def test_pruebas_repite_cada_24_horas_y_solo_al_mail_de_sdn():
    a = CFG["alertas"]
    assert a["repeat_interval"] == "24h"
    assert a["email"] == "snavello@gmail.com"
    assert a["avisar_al_resolverse"] is True


def test_un_mail_o_un_intervalo_mal_escritos_se_rechazan_antes_de_tocar_grafana():
    assert ag.validar(_con(email="sin-arroba"))
    assert ag.validar(_con(repeat_interval="un dia"))
    assert ag.validar(_con(repeat_interval="24"))
    assert ag.validar(_con(group_by=[]))
    assert ag.validar(_con(avisar_al_resolverse="si"))
    malo = copy.deepcopy(CFG)
    malo["grafana"]["url"] = "http://inseguro.example"
    assert ag.validar(malo)


def test_los_intervalos_admiten_segundos_minutos_y_horas():
    for v in ("30s", "5m", "12h", "24h"):
        assert ag.validar(_con(repeat_interval=v)) == [], v


def test_el_punto_de_contacto_es_un_solo_mail_con_aviso_al_resolverse():
    p = ag.payload_contact_point(CFG)
    assert p["type"] == "email" and p["name"] == "sdn-mail"
    assert p["settings"] == {"addresses": "snavello@gmail.com", "singleEmail": True}
    assert p["disableResolveMessage"] is False
    assert ag.payload_contact_point(_con(avisar_al_resolverse=False))["disableResolveMessage"] is True


def test_la_politica_lleva_las_reglas_anti_ruido_y_apunta_al_punto_de_contacto():
    p = ag.payload_politica(CFG)
    assert p["receiver"] == CFG["alertas"]["contact_point"]
    assert p["repeat_interval"] == "24h" and p["group_wait"] == "1m" and p["group_interval"] == "5m"
    assert p["group_by"] == ["alertname", "entorno"]      # un mail por problema y por entorno
    assert p["routes"] == []


def test_cambiar_el_mail_o_el_intervalo_es_editar_una_linea():
    c = _con(email="otro@ejemplo.com", repeat_interval="12h")
    assert ag.validar(c) == []
    assert ag.payload_contact_point(c)["settings"]["addresses"] == "otro@ejemplo.com"
    assert ag.payload_politica(c)["repeat_interval"] == "12h"


def test_grafana_devuelve_24h_como_1d_y_se_normaliza_para_poder_compararlo():
    n = ag.normalizar_duracion
    assert n("1d") == "24h" and n("2d") == "48h" and n("24h") == "24h"
    assert n("60m") == "1h" and n("90m") == "90m" and n("30s") == "30s"
    assert n("") == "" and n(None) == "" and n("raro") == "raro"
    for elegible in ("1h", "6h", "12h", "24h", "48h"):     # los del selector
        assert n(elegible) == elegible


def test_el_nombre_de_recurso_de_grafana_13_es_base64_sin_relleno():
    assert ag.nombre_de_recurso("sdn-mail") == "c2RuLW1haWw"      # el que devolvió la API real
    assert "=" not in ag.nombre_de_recurso("un nombre de largo distinto")


def test_el_config_no_lleva_ningun_token():
    texto = (Path(__file__).parent / "observabilidad" / "config.json").read_text(encoding="utf-8")
    assert "glsa_" not in texto and "rnd_" not in texto      # los valores de los tokens
    def claves(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from claves(v)
    assert not [k for k in claves(json.loads(texto)) if "token" in k.lower() or "clave" in k.lower()]
