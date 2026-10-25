"""Panel Sindical: la página y su andamio (PLAN_DASHBOARD_V2.md, bloque 1).

Desde el 2026-10-25 la v2 ES el Panel Sindical, en /admin/dashboard y en
todos los entornos; la v1 se retiró. Lo que se verifica:

- **Las puertas**: sin sesión, el login; sin el módulo o sin el permiso de la
  sección "dashboard", de vuelta al panel. **Existe también en demo y prod**
  (durante el piloto daba 404 donde no había distintivo).
- **La dirección del piloto**, /admin/dashboard-v2, redirige al panel con
  los mismos filtros: un enlace guardado no se rompe.
- **El importmap (D3)**: cada módulo sale con su sello `?v=`, y TODO `import`
  de la v2 y de las librerías vendoreadas resuelve a una entrada del mapa.
  Un import por ruta ("./html.js") saldría sin sello y quedaría cacheado una
  hora después de un deploy: la página nueva con el módulo viejo.
- **Nada de HTML armado como texto** en la v2 (línea roja 5): Preact escapa
  lo que pinta, y eso deja de valer en cuanto alguien usa innerHTML.
- **Las librerías vendoreadas son las registradas**: el SHA-256 de cada
  archivo tiene que coincidir con `static/vendor/preact/ORIGEN.md`.
- **No queda rastro de la v1**: ni sus archivos ni el enlace entre versiones.

Correr con: .venv/bin/python -m pytest test_dashboard_v2.py -q
"""
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import auth
import db
import entorno
import fechas
import main
from db import Area, Seccional, Sindicato, UsuarioSindicato

db.crear_tablas()

PANEL = Path("static") / "panel_v2"
VENDOR = Path("static") / "vendor" / "preact"

with db.get_session() as s:
    con = Sindicato(nombre="UOM V2", slug="uom-v2", color_base="#0f1b2d",
                    modulos_habilitados=["dashboard"])
    sin = Sindicato(nombre="Fega V2", slug="fega-v2", color_base="#0d2027",
                    modulos_habilitados=["tramites"])
    s.add(con); s.add(sin); s.commit(); s.refresh(con); s.refresh(sin)
    SID_CON, SID_SIN = con.id, sin.id
    s.add(UsuarioSindicato(sindicato_id=SID_CON, usuario="20300000016", nombre="Admin V2",
                           clave_hash=auth.hashear_clave("v2-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_SIN, usuario="20300000024", nombre="Admin sin panel",
                           clave_hash=auth.hashear_clave("v2-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    sec = Seccional(sindicato_id=SID_CON, nombre="Rosario V2")
    s.add(sec); s.commit(); s.refresh(sec)
    SEC_ID = sec.id
    area = Area(sindicato_id=SID_CON, seccional_id=SEC_ID, nombre="Solo Reglas")
    s.add(area); s.commit(); s.refresh(area)
    AREA_ID = area.id
db.set_permisos_area(AREA_ID, ["formulas"], SID_CON)
with db.get_session() as s:
    s.add(UsuarioSindicato(sindicato_id=SID_CON, usuario="20300000032", nombre="Sin tablero",
                           clave_hash=auth.hashear_clave("v2-demo"), debe_cambiar_clave=False,
                           es_super_admin=False, seccional_id=SEC_ID, area_id=AREA_ID))
    s.commit()


@pytest.fixture(autouse=True)
def con_distintivo(monkeypatch):
    """Por defecto, un entorno con distintivo (local/pruebas). La demo se
    prueba aparte: el panel tiene que andar igual."""
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", True)
    monkeypatch.setitem(main.templates.env.globals, "distintivo_entorno", True)


def _cliente(usuario):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": "v2-demo"},
               follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    return c


def _importmap(html: str) -> dict:
    m = re.search(r'<script type="importmap">(.*?)</script>', html, re.S)
    assert m, "la página no trae el importmap"
    return json.loads(m.group(1))["imports"]


def _sin_comentarios(js: str) -> str:
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


# Lo que un módulo importa: `from "x"`, `import "x"` e `import("x")`, también
# en el código minificado de las librerías (`}from"preact"`).
_IMPORTA = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']""")


# ---------------------------------------------------------------------------
# Las puertas
# ---------------------------------------------------------------------------
def test_sin_sesion_muestra_el_login():
    r = TestClient(main.app).get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 200
    assert 'name="usuario"' in r.text and "importmap" not in r.text


def test_sin_el_modulo_vuelve_al_panel():
    r = _cliente("20300000024").get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"


def test_sin_el_permiso_vuelve_al_panel():
    r = _cliente("20300000032").get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"


def test_en_demo_y_prod_tambien_existe(monkeypatch):
    """Durante el piloto (D4) la v2 daba 404 donde no había distintivo. Desde
    que reemplazó a la v1 es EL panel: en la demo se ve igual."""
    c = _cliente("20300000016")
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    monkeypatch.setitem(main.templates.env.globals, "distintivo_entorno", False)
    r = c.get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 200 and "importmap" in r.text
    r = TestClient(main.app).get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 200 and 'name="usuario"' in r.text


def test_la_direccion_del_piloto_redirige_con_los_filtros():
    c = _cliente("20300000016")
    r = c.get("/admin/dashboard-v2?desde=2026-10-01&hasta=2026-10-12&seccionales=3",
              follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/dashboard?desde=2026-10-01&hasta=2026-10-12&seccionales=3"
    r = c.get("/admin/dashboard-v2", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/dashboard"
    # Sin sesión también redirige: la puerta la pone la página de destino.
    r = TestClient(main.app).get("/admin/dashboard-v2", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/dashboard"


def test_con_todo_abre_con_la_fecha_del_servidor_y_el_importmap():
    r = _cliente("20300000016").get("/admin/dashboard")
    assert r.status_code == 200, r.text
    assert f'data-hoy="{fechas.hoy_texto()}"' in r.text
    mapa = _importmap(r.text)
    for nombre in ("preact", "preact/hooks", "htm", "panel/app", "panel/html"):
        assert nombre in mapa, f"falta {nombre} en el importmap"
    for nombre, url in mapa.items():
        assert re.search(r"\?v=\d+-\d+$", url), f"{nombre} sale sin sello: {url}"
    assert re.search(r'<script type="module" src="/static/panel_v2/app\.js\?v=\d+-\d+">',
                     r.text), "la raíz de la v2 se carga sin sello"
    # Cada módulo del mapa se precarga (y con el mismo sello): sin eso se
    # descubren en cascada, un viaje al servidor por escalón.
    precargas = set(re.findall(r'<link rel="modulepreload" href="([^"]+)">', r.text))
    assert precargas == set(mapa.values()), set(mapa.values()) ^ precargas
    assert r.text.index('type="importmap"') < r.text.index('rel="modulepreload"') < r.text.index("</head>")


# ---------------------------------------------------------------------------
# El importmap: todo import resuelve, y siempre por nombre
# ---------------------------------------------------------------------------
def test_cada_modulo_de_la_carpeta_esta_en_el_mapa():
    mapa = json.loads(main._importmap_panel_v2())["imports"]
    propios = {f"panel/{p.stem}" for p in PANEL.glob("*.js")}
    assert propios and propios <= set(mapa), propios - set(mapa)
    for nombre, ruta in main._VENDOR_PANEL_V2.items():
        assert (Path("static") / ruta).exists(), f"{nombre}: no existe {ruta}"


def test_todo_import_resuelve_por_el_importmap():
    mapa = json.loads(main._importmap_panel_v2())["imports"]
    archivos = list(PANEL.glob("*.js")) + [Path("static") / r for r in main._VENDOR_PANEL_V2.values()]
    sin_resolver = []
    for archivo in archivos:
        for nombre in _IMPORTA.findall(_sin_comentarios(archivo.read_text(encoding="utf-8"))):
            if nombre not in mapa:
                sin_resolver.append(f"{archivo}: import {nombre!r}")
    assert not sin_resolver, ("estos imports no pasan por el importmap (saldrían sin "
                              "sello ?v=):\n" + "\n".join(sin_resolver))


def test_la_v2_importa_algo():
    """Baranda del test de arriba: si el regex dejara de encontrar imports,
    pasaría recorriendo nada."""
    app = _sin_comentarios((PANEL / "app.js").read_text(encoding="utf-8"))
    assert {"preact", "panel/html"} <= set(_IMPORTA.findall(app))
    hooks = (VENDOR / "hooks.module.js").read_text(encoding="utf-8")
    assert _IMPORTA.findall(hooks) == ["preact"]


# ---------------------------------------------------------------------------
# Nada de HTML armado como texto
# ---------------------------------------------------------------------------
_PROHIBIDOS = ("innerHTML", "outerHTML", "insertAdjacentHTML",
               "dangerouslySetInnerHTML", "document.write")


def test_la_v2_no_arma_html_como_texto():
    hallados = [f"{p.name}: {x}" for p in sorted(PANEL.glob("*.js"))
                for x in _PROHIBIDOS
                if x in _sin_comentarios(p.read_text(encoding="utf-8"))]
    assert not hallados, ("la v2 pinta con Preact, que escapa todo; esto arma HTML "
                          "como texto:\n" + "\n".join(hallados))


# ---------------------------------------------------------------------------
# Las librerías vendoreadas son las registradas
# ---------------------------------------------------------------------------
def test_las_librerias_vendoreadas_son_las_de_origen_md():
    registro = dict((nombre, sha) for sha, nombre in re.findall(
        r"^([0-9a-f]{64})\s+(\S+)$", (VENDOR / "ORIGEN.md").read_text(encoding="utf-8"), re.M))
    archivos = {p.name for p in VENDOR.iterdir()
                if p.is_file() and p.suffix in (".js", ".map")}
    assert archivos == set(registro), ("ORIGEN.md y la carpeta no listan los mismos "
                                       f"archivos: {archivos ^ set(registro)}")
    for nombre, sha in registro.items():
        real = hashlib.sha256((VENDOR / nombre).read_bytes()).hexdigest()
        assert real == sha, f"{nombre} cambió sin actualizar ORIGEN.md"
    for licencia in ("LICENSE-preact", "LICENSE-htm"):
        assert (VENDOR / licencia).exists(), f"falta {licencia}"


# ---------------------------------------------------------------------------
# La v1 se fue entera
# ---------------------------------------------------------------------------
def test_no_queda_rastro_de_la_v1():
    assert not Path("templates/dashboard.html").exists()
    assert not Path("static/dashboard.js").exists()
    html = _cliente("20300000016").get("/admin/dashboard").text
    assert "dashboard.js" not in html and "dashboard-v2" not in html
    assert "versión actual" not in html and "versión nueva" not in html
    # Ningún módulo del panel ofrece volver a otra versión.
    for p in PANEL.glob("*.js"):
        assert "/admin/dashboard-v2" not in p.read_text(encoding="utf-8"), p.name
