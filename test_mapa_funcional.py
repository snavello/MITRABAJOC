"""Mapa funcional (mapa_funcional.py) y su pestaña en /entornos: se arma del
código, clasifica cada ruta en una funcionalidad, y solo existe donde existe
la landing (local/pruebas), detrás del mismo pase.

Correr con: .venv/Scripts/python.exe -m pytest test_mapa_funcional.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import entorno
import mapa_funcional
import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()


def _con_pase():
    c = TestClient(main.app)
    assert c.post("/entornos/pin", data={"pin": "13572468"}, follow_redirects=False).status_code == 303
    return c


def test_lee_el_codigo_y_encuentra_lo_que_ya_se_sabe():
    datos = mapa_funcional.armar()
    por_nombre = {(f["app"], f["nombre"]): f for f in datos["funcionalidades"]}
    # Cada ruta de main.py queda en alguna funcionalidad o, visible, en "sin clasificar".
    clasificadas = sum(len(f["rutas"]) for f in datos["funcionalidades"])
    assert clasificadas + len(datos["sin_clasificar"]) == datos["total_rutas"]
    ids = lambda f: {n["id"] for n in f["nodos"]}
    # Hechos de CLAUDE.md: si el detector los pierde, es un hueco del detector.
    assert "s:API de Anthropic (Claude)" in ids(por_nombre[("Afiliado", "Tu Recibo")])
    assert "t:ReciboVerificado" in ids(por_nombre[("Sindicato", "Panel Sindical")])   # SQL escrito a mano
    assert "s:Georef" in ids(por_nombre[("Sindicato", "Seccionales")])
    assert "s:API de Anthropic (Claude)" in ids(por_nombre[("Afiliado", "Consultas al convenio")])
    assert ("Entornos", "Mapa funcional") in por_nombre


def test_no_vuelven_las_distorsiones_de_la_revision():
    """Las cuatro que se encontraron revisando el mapa pieza por pieza
    (2026-09-30), más la de las docstrings."""
    por_nombre = {(f["app"], f["nombre"]): {n["id"] for n in f["nodos"]}
                  for f in mapa_funcional.armar()["funcionalidades"]}
    # a. La página completa de la app no se le carga a una pestaña.
    assert not {"m:qr", "m:filigrana"} & por_nombre[("Afiliado", "Tu Recibo")]
    assert {"m:qr", "m:filigrana"} <= por_nombre[("Afiliado", "Página de la app (carga inicial)")]
    # b. Mostrar si Telegram está configurado no es llamar a Telegram.
    assert "s:Telegram" not in por_nombre[("Entornos", "Sala de mando")]
    # c. El pase de la landing es un guardián, no uso del catálogo de Recursos.
    assert "m:recursos" not in por_nombre[("Entornos", "Tests de carga")]
    # d. Limpiar un CUIL con validador._norm_cuil no es usar el motor de validación.
    assert "m:validador" not in por_nombre[("Sindicato", "Reportes")]
    # Una docstring que dice "...del JOIN" y nombra "empleador" no es SQL.
    assert "t:Empleador" not in por_nombre[("Plataforma", "Trabajadores de la plataforma")]


def test_sin_pase_no_se_ve_y_con_pase_se_arma():
    c = TestClient(main.app)
    assert c.get("/api/entornos/mapa").status_code == 403
    r = c.get("/entornos/mapa", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")
    c = _con_pase()
    resumen = c.get("/api/entornos/mapa").json()
    assert resumen["funcionalidades"] > 40 and resumen["apps"] == 6
    html = c.get("/entornos/mapa").text
    # La librería del grafo va vendoreada (la CSP no deja cargar de un CDN).
    assert "/static/vendor/vis-network/vis-network.min.js?v=" in html and "cdn." not in html
    r = c.post("/entornos/mapa/actualizar", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entornos/mapa"


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = TestClient(main.app)
    for ruta in ("/entornos/mapa", "/api/entornos/mapa"):
        assert c.get(ruta).status_code == 404
    assert c.post("/entornos/mapa/actualizar").status_code == 404
