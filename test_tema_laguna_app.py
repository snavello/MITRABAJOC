"""El modelo Laguna en la app del afiliado (/app) — PLAN_TEMAS.md, bloque 4.

Lo que la plantilla tiene que garantizar, más allá de cómo se vea:
- la hoja static/temas/laguna-app.css se carga SOLO con el modelo laguna,
  con su sello ?v=, y todos sus selectores están acotados a ese modelo;
- la tira de pestañas va en el orden acordado con SDN (Mis Recibos ·
  Credencial · Trámites · Novedades · Encuestas · Mis Aportes · Capacitación),
  respetando los módulos del sindicato;
- Inicio y Salir flotan juntos, cada uno con su rótulo a la vista;
- los importes salen en formato argentino ("$ 1.284.560,00").

Correr con: python -m pytest test_tema_laguna_app.py -q
"""
import os
import re
from pathlib import Path

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import auth
import db
import main
from db import CuentaTrabajador, Sindicato, Trabajador
from fastapi.testclient import TestClient
from modulos import MODULOS

db.crear_tablas()

AFILIADO = "20387654329"
AFILIADO_POCOS = "27387654321"
HOJA = Path("static/temas/laguna-app.css")
ORDEN = ["recibo", "credencial", "tramites", "novedades", "encuestas", "aportes", "capacitacion"]

with db.get_session() as s:
    todo = Sindicato(nombre="Laguna App Todo", slug="laguna-app-todo", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=list(MODULOS))
    pocos = Sindicato(nombre="Laguna App Pocos", slug="laguna-app-pocos", color_base="#2a0d12",
                      color_primario="#7a1f2b", color_acento="#3d6b4a", color_secundario="#c19a3e",
                      modulos_habilitados=["noticias", "aportes", "tramites"])
    s.add(todo); s.add(pocos); s.commit(); s.refresh(todo); s.refresh(pocos)
    SID, SID_POCOS = todo.id, pocos.id
    for cuil, sid, nombre in ((AFILIADO, SID, "Marta Lago"), (AFILIADO_POCOS, SID_POCOS, "Ana Río")):
        s.add(CuentaTrabajador(cuil=cuil, nombre=nombre, clave_hash=auth.hashear_clave("x")))
        s.add(Trabajador(sindicato_id=sid, cuil=cuil, registrado=True))
    s.commit()


def _app(cuil=AFILIADO, tema="laguna"):
    assert db.guardar_tema_persona(cuil, tema, "afiliado")
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    r = c.get("/app")
    assert r.status_code == 200, r.text
    return r.text


def _tira(html):
    nav = re.search(r'<nav class="tabbar"[^>]*>(.*?)</nav>', html, re.S)
    assert nav, "no está la tira de pestañas"
    return re.findall(r'data-tp="(\w+)"', nav.group(1))


# ---------- la hoja del modelo ----------

def test_la_hoja_se_carga_solo_con_laguna_y_con_sello():
    html = _app(tema="laguna")
    assert 'data-tema="laguna"' in html
    m = re.search(r'<link rel="stylesheet" href="/static/temas/laguna-app\.css\?v=([^"]+)">', html)
    assert m and m.group(1), "falta la hoja de Laguna o su sello ?v="
    # Va después de los estilos propios de la plantilla: si no, no los pisa.
    assert html.index("</style>") < m.start() < html.index("</head>")

    html = _app(tema="noticiero")
    assert 'data-tema="noticiero"' in html
    assert "laguna-app.css" not in html


def _partir(lista):
    """Parte una lista de selectores por las comas de afuera (no las de :is())."""
    partes, nivel, actual = [], 0, ""
    for ch in lista:
        nivel += (ch == "(") - (ch == ")")
        if ch == "," and nivel == 0:
            partes.append(actual); actual = ""
        else:
            actual += ch
    return partes + [actual]


def test_todo_selector_de_la_hoja_esta_acotado_al_modelo():
    css = HOJA.read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # Saca los @keyframes (sus "selectores" son porcentajes) y los @font-face.
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    css = re.sub(r"@font-face\s*\{[^{}]*\}", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    sueltos = []
    for bloque in re.findall(r"([^{}]+)\{[^{}]*\}", css):
        for sel in _partir(bloque):
            sel = sel.strip()
            if sel and not sel.startswith('html[data-tema="laguna"]'):
                sueltos.append(sel)
    assert not sueltos, f"selectores sin html[data-tema=\"laguna\"]: {sueltos[:5]}"


def test_la_hoja_declara_la_paleta_del_sindicato_y_manrope():
    css = HOJA.read_text(encoding="utf-8")
    assert 'html[data-tema="laguna"][data-paleta="sindicato"]' in css
    for gremio in ("--gremio-base", "--gremio-primario", "--gremio-acento", "--gremio-apoyo",
                   "--gremio-acento-txt", "--gremio-tinta-acento"):
        assert gremio in css, gremio
    assert '/static/fonts/manrope.woff2' in css
    assert "prefers-reduced-motion" in css


def test_la_plantilla_copia_los_colores_crudos_del_gremio():
    html = _app()
    for var, valor in (("--gremio-base", "#0f2240"), ("--gremio-primario", "#1a3d6b"),
                       ("--gremio-acento", "#e8b84b"), ("--gremio-apoyo", "#2fa88f")):
        assert f"{var}: {valor};" in html, var
    # Acento claro (el ámbar de la UOM): el texto encima va en la base del gremio.
    assert "--gremio-tinta-acento: #0f2240;" in html
    # Acento oscuro (el verde de la Gastronómica): texto blanco encima y, como
    # texto sobre oscuro, aclarado.
    html = _app(AFILIADO_POCOS)
    assert "--gremio-tinta-acento: #ffffff;" in html
    m = re.search(r"--gremio-acento-txt: (#[0-9a-f]{6});", html)
    assert m and m.group(1) != "#3d6b4a"   # corregido por temas.paleta_legible


# ---------- pautas comunes (van en la plantilla, para los dos modelos) ----------

def test_orden_de_la_tira_con_todos_los_modulos():
    for tema in ("laguna", "noticiero"):
        assert _tira(_app(tema=tema)) == ORDEN, tema


def test_orden_de_la_tira_respeta_los_modulos():
    tira = _tira(_app(AFILIADO_POCOS))
    assert tira == ["tramites", "novedades", "aportes"]


def test_inicio_y_salir_flotan_juntos_con_rotulo():
    for tema in ("laguna", "noticiero"):
        html = _app(tema=tema)
        m = re.search(r'<nav class="flota-sal"[^>]*>(.*?)</nav>', html, re.S)
        assert m, tema
        dock = m.group(1)
        assert re.search(r'<a class="flota-ini" href="/app/inicio">.*?Inicio</a>', dock, re.S), tema
        assert re.search(r'<a class="flota-salir" href="/trabajador/salir">.*?Salir</a>', dock, re.S), tema
        # Los íconos son decorativos: el nombre del enlace es el rótulo.
        assert dock.count('aria-hidden="true"') == 2
        # Ya no quedan los dos círculos de un ícono solo.
        assert "btn-flotante" not in html
        assert 'id="ic-salir"' in html


def test_importes_en_formato_argentino():
    html = _app()
    assert "toLocaleString('es-AR', {minimumFractionDigits:2, maximumFractionDigits:2})" in html
    assert "'$ ' + Math.abs(v)" in html
