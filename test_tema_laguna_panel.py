"""El modelo Laguna en el panel del sindicato (PLAN_TEMAS.md, bloque 6).

Lo que se verifica:
- /admin carga static/temas/laguna-panel.css (con sello) solo con el modelo
  Laguna; con Noticiero, no.
- El riel es una regla de layout: la tira sigue siendo el mismo <nav
  class="nav-strip"> con los mismos botones y data-panel, en su orden, y el
  Panel Sindical lleva su flechita de "abre otra página".
- Inicio y Salir flotan juntos y con su rótulo a la vista.
- La hoja respeta sus reglas: todo selector empieza con
  html[data-tema="laguna"], los colores salen de variables, la paleta del
  sindicato se deriva de --marca-*, y ninguna selección se marca con una
  barra de color a un costado.

Correr con: python -m pytest test_tema_laguna_panel.py -q
"""
import os
import re
from pathlib import Path

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import main
from db import Sindicato, UsuarioSindicato
from fastapi.testclient import TestClient

db.crear_tablas()

OPERADOR = "20412233442"
HOJA = Path("static/temas/laguna-panel.css")

with db.get_session() as s:
    sind = Sindicato(nombre="Laguna Panel UOM", slug="laguna-panel-uom", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=["recibos", "noticias", "beneficios", "notificaciones", "tramites"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=OPERADOR, nombre="Laura Méndez",
                           clave_hash=auth.hashear_clave("clave-op"), es_super_admin=True))
    s.commit()


def _operador():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": OPERADOR, "clave": "clave-op"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _hoja() -> str:
    return HOJA.read_text(encoding="utf-8")


def _sin_comentarios(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ---------------------------------------------------------------- la página

def test_con_laguna_carga_su_hoja_con_sello():
    c = _operador()
    c.post("/admin/apariencia/mia", data={"tema": "laguna"})
    html = c.get("/admin").text
    assert 'data-tema="laguna"' in html
    sello = main._sello_static("temas/laguna-panel.css")
    assert sello, "la hoja tiene que existir"
    assert f'href="/static/temas/laguna-panel.css?v={sello}"' in html
    # la hoja va después de los estilos de la página, para poder pisarlos
    assert html.index("/static/temas/laguna-panel.css?v=") > html.index("</style>")
    # el logo de Colm3na para el encabezado blanco
    assert 'class="enc-c3-claro"' in html


def test_con_noticiero_no_se_carga():
    c = _operador()
    try:
        assert c.post("/admin/apariencia/mia", data={"tema": "noticiero"}).status_code == 200
        html = c.get("/admin").text
        assert 'data-tema="noticiero"' in html
        assert "/static/temas/laguna-panel.css" not in html and 'class="enc-c3-claro"' not in html
    finally:
        c.post("/admin/apariencia/mia", data={"tema": "laguna"})


def test_el_riel_es_la_misma_tira_con_los_mismos_botones():
    html = _operador().get("/admin").text
    tira = html[html.index('<nav class="nav-strip">'):html.index("</nav>")]
    paneles = re.findall(r'class="tab-btn"[^>]*data-panel="([a-z_]+)"', tira)
    # el orden de siempre (lo que este sindicato tiene habilitado)
    orden = ["reportes", "formulas", "conceptos", "trabajadores", "aprendizaje", "noticias",
             "beneficios", "notificaciones", "tramites", "seccionales", "listas", "administradores"]
    assert [p for p in paneles if p in orden] == [p for p in orden if p in paneles]
    assert {"trabajadores", "noticias", "tramites", "administradores"} <= set(paneles)
    # el JS que cambia de pestaña sigue enganchado a .tab-btn y data-panel
    assert "document.querySelectorAll('.tab-btn').forEach" in html
    assert "btn.dataset.panel" in html


def test_el_panel_sindical_lleva_la_flechita():
    with db.get_session() as s:
        sind = s.get(Sindicato, SID)
        sind.modulos_habilitados = list(sind.modulos_habilitados or []) + ["dashboard"]
        s.add(sind); s.commit()
    try:
        html = _operador().get("/admin").text
        tira = html[html.index('<nav class="nav-strip">'):html.index("</nav>")]
        link = re.search(r'<a class="tab-btn"[^>]*href="/admin/dashboard".*?</a>', tira, re.S).group(0)
        assert 'class="tab-ext"' in link and 'aria-label="abre otra página"' in link
        assert tira.index("/admin/dashboard") < tira.index('data-panel=')   # va primero
    finally:
        with db.get_session() as s:
            sind = s.get(Sindicato, SID)
            sind.modulos_habilitados = [m for m in sind.modulos_habilitados if m != "dashboard"]
            s.add(sind); s.commit()


def test_inicio_y_salir_flotan_juntos_con_rotulo():
    html = _operador().get("/admin").text
    flota = html[html.index('<div class="flota-sesion">'):]
    flota = flota[:flota.index("</div>")]
    assert re.search(r'<a class="btn-home" href="/admin/inicio"[^>]*>.*?<span class="btn-rot">Inicio</span>', flota, re.S)
    assert re.search(r'<a class="btn-cerrar" href="/admin/salir"[^>]*>.*?<span class="btn-rot">Salir</span>', flota, re.S)
    assert flota.index("btn-home") < flota.index("btn-cerrar")       # Salir al final
    assert 'id="btn-ayuda"' in flota                                  # la ayuda sigue con su id


# ---------------------------------------------------------------- la hoja

def _selectores(css: str):
    """Los selectores de cada regla. Se sacan los comentarios, el @font-face
    y los envoltorios @media (sus reglas internas sí se revisan)."""
    css = _sin_comentarios(css)
    css = re.sub(r"@font-face\s*\{[^}]*\}", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    for bloque in re.finditer(r"([^{}]+)\{[^{}]*\}", css):
        # se parte por las comas de primer nivel: las de :is() y :not() no
        nivel, actual = 0, ""
        for ch in bloque.group(1) + ",":
            if ch == "," and nivel == 0:
                if actual.strip():
                    yield actual.strip()
                actual = ""
                continue
            nivel += (ch == "(") - (ch == ")")
            actual += ch


def test_todo_selector_empieza_con_el_modelo():
    selectores = list(_selectores(_hoja()))
    assert len(selectores) > 100
    malos = [sel for sel in selectores if not sel.startswith('html[data-tema="laguna"]')]
    assert not malos, malos


def test_los_colores_salen_de_variables():
    css = _sin_comentarios(_hoja())
    sueltos = []
    for linea in css.splitlines():
        decl = linea.strip()
        if decl.startswith("--") or "data:image" in decl:
            continue
        for hexa in re.findall(r"#[0-9a-fA-F]{3,8}\b", decl):
            if hexa.lower() not in ("#fff", "#ffffff"):
                sueltos.append(decl)
    assert not sueltos, sueltos


def test_la_paleta_del_sindicato_se_deriva_de_la_marca():
    css = _sin_comentarios(_hoja())
    m = re.search(r'html\[data-tema="laguna"\]\[data-paleta="sindicato"\]\s*\{([^}]*)\}', css)
    assert m, "falta la paleta del sindicato"
    cuerpo = m.group(1)
    for var in ("--lg-azul", "--lg-turq", "--lg-lag", "--lg-agua-f", "--lg-fluor", "--lg-fluor-t", "--lg-fluor-txt"):
        assert re.search(rf"{var}\s*:", cuerpo), var
    assert "var(--marca-base)" in cuerpo and "var(--marca-primario)" in cuerpo and "var(--marca-acento)" in cuerpo
    assert "color-mix(in oklab" in cuerpo
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", cuerpo), "la paleta del sindicato no lleva colores fijos"


def test_la_plantilla_da_el_texto_sobre_el_acento():
    html = _operador().get("/admin").text
    # acento claro (#e8b84b): el texto encima va en la base
    assert "--marca-tinta-acento: var(--marca-base)" in html
    assert "--marca-apoyo: #2fa88f" in html


def test_ninguna_seleccion_con_barra_al_costado():
    css = _sin_comentarios(_hoja())
    # ningún borde izquierdo con grosor y color
    for m in re.finditer(r"border-left\s*:\s*([^;}]+)", css):
        assert m.group(1).strip() in ("0", "none"), m.group(0)
    # ninguna sombra interior desplazada en x (el "corchete" de 3px)
    for m in re.finditer(r"inset\s+(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px", css):
        assert float(m.group(1)) == 0, m.group(0)
    # la activa del riel: relleno entero
    activa = re.search(r'html\[data-tema="laguna"\] \.tab-btn\.activa \{([^}]*)\}', css).group(1)
    assert "background: var(--lg-azul)" in activa


def test_respeta_menos_movimiento():
    assert "@media (prefers-reduced-motion: reduce)" in _hoja()


def test_el_riel_es_fijo_en_escritorio_y_tira_en_telefono():
    css = _sin_comentarios(_hoja())
    escritorio = css[css.index("@media (min-width: 761px)"):]
    nav = re.search(r'\.nav-strip \{([^}]*)\}', escritorio).group(1)
    assert "position: fixed" in nav and "flex-direction: column" in nav
    assert "margin: 0 0 0 var(--lg-riel)" in escritorio        # el contenido le deja el lugar
    telefono = css[css.index("@media (max-width: 760px)"):]
    assert ".nav-strip" in telefono and "position: fixed" not in re.search(r'\.nav-strip \{([^}]*)\}', telefono).group(1)
