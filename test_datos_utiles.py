"""Datos útiles de la portada del afiliado (datos_utiles.py, SDN 2026-10-24).

Sin red: los servicios de afuera se simulan.
Correr con: python -m pytest test_datos_utiles.py -q
"""
import json
from datetime import date
from pathlib import Path

import pytest

import datos_utiles as du


@pytest.fixture(autouse=True)
def _sin_cache():
    du._cache.clear()
    yield
    du._cache.clear()


def test_fechas_en_castellano():
    assert du.fecha_texto(date(2026, 10, 24)) == "sábado 24 de octubre"
    assert du.fecha_corta(date(2026, 11, 9)) == "Lun 9/11"


def test_proximo_feriado_desde_hoy_y_el_puente_con_nombre_propio():
    lista = [{"fecha": "2026-03-23", "nombre": "Puente turístico no laborable", "tipo": "puente"},
             {"fecha": "2026-03-24", "nombre": "Día de la Memoria", "tipo": "inamovible"}]
    f = du.proximo_feriado(date(2026, 3, 20), lista)
    assert f["nombre"] == "Feriado puente" and f["dias"] == 3 and f["corto"] == "Lun 23/3"
    assert du.proximo_feriado(date(2026, 3, 24), lista)["corto"] == "Hoy"
    assert du.proximo_feriado(date(2026, 3, 25), lista) is None
    assert du.proximo_feriado(date(2026, 3, 25), None) is None


def test_efemeride_de_hoy_o_la_proxima_dentro_de_tres_semanas():
    lista = [{"dia": "11-06", "nombre": "Día del Bancario"}, {"dia": "05-01", "nombre": "Día del Trabajador"}]
    assert du.efemeride(date(2026, 11, 6), lista)["corto"] == "Hoy"
    e = du.efemeride(date(2026, 10, 24), lista)
    assert e["nombre"] == "Día del Bancario" and e["corto"] == "6/11"
    assert du.efemeride(date(2026, 7, 1), lista) is None          # nada en 21 días
    assert du.efemeride(date(2026, 12, 20), [{"dia": "01-01", "nombre": "Año"}])["corto"] == "1/1"


def test_la_lista_de_efemerides_es_valida():
    datos = json.loads(Path("data/efemerides.json").read_text(encoding="utf-8"))["efemerides"]
    assert len(datos) >= 15
    for e in datos:
        mes, dia = (int(x) for x in e["dia"].split("-"))
        date(2024, mes, dia)
        assert e["nombre"].strip()


def test_clima_redondea_las_coordenadas_y_traduce_el_codigo(monkeypatch):
    pedidos = []
    def falso(url):
        pedidos.append(url)
        return {"current": {"temperature_2m": 17.4, "weather_code": 3},
                "daily": {"temperature_2m_max": [20.6], "temperature_2m_min": [13.5]}}
    monkeypatch.setattr(du, "_pedir_json", falso)
    c = du.clima(-31.419157, -64.191904)
    assert c == {"temp": 17, "max": 21, "min": 14, "texto": "Nublado", "icono": "nubes"}
    assert "latitude=-31.4" in pedidos[0] and "longitude=-64.2" in pedidos[0]   # ~10 km, no un domicilio
    du.clima(-31.43, -64.18)
    assert len(pedidos) == 1                                                # misma celda: de la memoria


def test_sin_coordenadas_o_fuera_del_pais_no_se_pide(monkeypatch):
    monkeypatch.setattr(du, "_pedir_json", lambda url: pytest.fail("no tenía que pedir"))
    assert du.clima(None, None) is None
    assert du.clima(40.4, -3.7) is None


def test_una_falla_no_rompe_y_no_se_recuerda_mucho(monkeypatch):
    def cae(url):
        raise OSError("sin red")
    monkeypatch.setattr(du, "_pedir_json", cae)
    assert du.clima(-34.6, -58.4) is None
    assert du.feriados(2026) is None
    d = du.datos_de_portada(-34.6, -58.4)
    assert d["clima"] is None and d["feriado"] is None and d["fecha"]


def test_la_ruta_exige_la_sesion_del_afiliado():
    from fastapi.testclient import TestClient
    import main
    r = TestClient(main.app).get("/api/portada/datos")
    assert r.status_code == 401


def test_la_portada_trae_el_widget_y_lo_llena_con_textcontent():
    html = Path("templates/portada.html").read_text(encoding="utf-8")
    assert 'id="pt-datos"' in html and "/api/portada/datos" in html
    js = html.split("fetch('/api/portada/datos'", 1)[1].split("</script>", 1)[0]
    assert "innerHTML" not in js
    assert "pt-hola-k" not in html                     # el «LB» arriba del saludo ya no está
