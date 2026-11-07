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


def test_pantallas_por_quien_llama_de_verdad():
    por_nombre = {(f["app"], f["nombre"]): {n["id"] for n in f["nodos"] if n["col"] == 0}
                  for f in mapa_funcional.armar()["funcionalidades"]}
    # Se detecta por fetch/action: el perfil del afiliado se edita desde la portada.
    assert "p:portada.html" in por_nombre[("Afiliado", "Perfil y domicilio")]
    # Ni el login que se muestra sin sesión, ni un parcial citado por nombre,
    # ni un .js nombrado en un comentario del encabezado.
    # El Panel Sindical es una sola pantalla desde que la v2 reemplazó a la v1
    # (2026-10-25).
    assert por_nombre[("Sindicato", "Panel Sindical")] == {"p:dashboard_v2.html"}
    # La pestaña transitoria de plataforma queda a la vista con nombre propio.
    assert any(a == "Plataforma" and n.startswith("Cambiar clave") for a, n in por_nombre)


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


def test_un_script_module_trae_su_carpeta():
    """Los módulos de la v2 del panel se importan entre sí por un importmap
    que la plantilla recibe ya armado: el mapa no lo puede leer, así que un
    <script type="module"> trae todos los .js de su carpeta."""
    js = mapa_funcional.js_de_plantilla("dashboard_v2.html")
    assert {"panel_v2/app.js", "panel_v2/html.js"} <= set(js), js
    assert not any("vendor" in j for j in js), js



def test_en_memoria_queda_el_texto_comprimido_y_no_el_grafo():
    """El servidor de Pruebas (512 MiB) se quedaba con +46 MiB por haber armado
    el mapa una vez: el pico del `ast` no se devuelve al sistema. Ahora se arma
    en un proceso aparte y lo que queda es el HTML comprimido."""
    import json
    import zlib
    resumen, datos_json = mapa_funcional.armar_aparte()
    assert isinstance(datos_json, str) and resumen["rutas"] == json.loads(datos_json)["total_rutas"]
    assert resumen["generado"].startswith("Generado ") and resumen["funcionalidades"] > 40
    memoria = main._mapa_funcional(forzar=True)
    assert set(memoria) == {"html_z", "resumen"}, set(memoria)       # ni el grafo ni el HTML sin comprimir
    assert isinstance(memoria["html_z"], bytes) and len(memoria["html_z"]) < 400_000
    assert b"vis-network" in zlib.decompress(memoria["html_z"])
    assert memoria["resumen"]["rutas"] == resumen["rutas"]


def test_si_el_proceso_aparte_falla_se_arma_en_el_servidor(monkeypatch):
    def roto(*a, **k):
        raise RuntimeError("sin subproceso")
    monkeypatch.setattr(mapa_funcional, "armar_aparte", roto)
    memoria = main._mapa_funcional(forzar=True)
    assert memoria["resumen"]["funcionalidades"] > 40 and memoria["html_z"]
    c = _con_pase()
    assert "vis-network" in c.get("/entornos/mapa").text
