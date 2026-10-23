"""El modelo Noticiero en el panel del sindicato (PLAN_TEMAS.md, bloque 6).

Lo que se verifica:
- /admin carga static/temas/noticiero-panel.css (con sello) solo con el
  modelo Noticiero; con Laguna carga la suya y no esta.
- El riel es el índice del diario: la misma tira (<nav class="nav-strip">)
  con los mismos botones y data-panel, numerada con un counter de CSS (no
  con números escritos en la plantilla) y con «Índice del panel» arriba.
- La hoja respeta sus reglas: todo selector empieza con
  html[data-tema="noticiero"], los colores salen de variables, la paleta del
  sindicato se deriva de --marca-*, ninguna selección se marca con una barra
  de color a un costado, las fuentes son las vendoreadas y hay versión para
  «reducir movimiento».

Correr con: python -m pytest test_tema_noticiero_panel.py -q
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

OPERADOR = "20412233450"
HOJA = Path("static/temas/noticiero-panel.css")

with db.get_session() as s:
    sind = Sindicato(nombre="Noticiero Panel UOM", slug="noticiero-panel-uom", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=["recibos", "noticias", "beneficios", "notificaciones", "tramites"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=OPERADOR, nombre="Laura Méndez",
                           clave_hash=auth.hashear_clave("clave-op"), es_super_admin=True))
    s.commit()


def _operador(tema="noticiero"):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": OPERADOR, "clave": "clave-op"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert c.post("/admin/apariencia/mia", data={"tema": tema}).status_code == 200
    return c


def _hoja() -> str:
    return HOJA.read_text(encoding="utf-8")


def _sin_comentarios(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ---------------------------------------------------------------- la página

def test_con_noticiero_carga_su_hoja_con_sello():
    html = _operador().get("/admin").text
    assert 'data-tema="noticiero"' in html
    sello = main._sello_static("temas/noticiero-panel.css")
    assert sello, "la hoja tiene que existir"
    assert f'href="/static/temas/noticiero-panel.css?v={sello}"' in html
    # después de los estilos de la página, para poder pisarlos
    assert html.index("/static/temas/noticiero-panel.css?v=") > html.index("</style>")
    assert "/static/temas/laguna-panel.css" not in html


def test_con_laguna_no_se_carga():
    html = _operador("laguna").get("/admin").text
    assert 'data-tema="laguna"' in html
    assert "/static/temas/noticiero-panel.css" not in html
    assert "/static/temas/laguna-panel.css?v=" in html


def test_el_riel_es_la_misma_tira_sin_numeros_en_la_plantilla():
    html = _operador().get("/admin").text
    tira = html[html.index('<nav class="nav-strip">'):html.index("</nav>")]
    paneles = re.findall(r'class="tab-btn"[^>]*data-panel="([a-z_]+)"', tira)
    assert {"trabajadores", "noticias", "tramites", "administradores"} <= set(paneles)
    # el número lo pone el CSS: en la plantilla no hay "01", "02"...
    assert not re.search(r">\s*0\d\s*<", tira)
    assert "document.querySelectorAll('.tab-btn').forEach" in html
    assert "btn.dataset.panel" in html


def test_inicio_y_salir_flotan_juntos_con_rotulo():
    html = _operador().get("/admin").text
    flota = html[html.index('<div class="flota-sesion">'):]
    flota = flota[:flota.index("</div>")]
    assert re.search(r'<a class="btn-home" href="/admin/inicio"[^>]*>.*?<span class="btn-rot">Inicio</span>', flota, re.S)
    assert re.search(r'<a class="btn-cerrar" href="/admin/salir"[^>]*>.*?<span class="btn-rot">Salir</span>', flota, re.S)


# ---------------------------------------------------------------- la hoja

def _selectores(css: str):
    """Los selectores de cada regla, sin comentarios, @font-face ni los
    envoltorios @media/@supports (sus reglas internas sí se revisan)."""
    css = _sin_comentarios(css)
    css = re.sub(r"@font-face\s*\{[^}]*\}", "", css)
    css = re.sub(r"@(media|supports)[^{]*\{", "", css)
    for bloque in re.finditer(r"([^{}]+)\{[^{}]*\}", css):
        nivel, actual = 0, ""
        for ch in bloque.group(1) + ",":
            if ch == "," and nivel == 0:
                if actual.strip():
                    yield actual.strip()
                actual = ""
                continue
            nivel += (ch == "(") - (ch == ")")
            actual += ch


def _reglas(css: str):
    """(selector, cuerpo) de cada regla, sin comentarios."""
    css = _sin_comentarios(css)
    css = re.sub(r"@font-face\s*\{[^}]*\}", "", css)
    css = re.sub(r"@(media|supports)[^{]*\{", "", css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield m.group(1).strip(), m.group(2)


def test_todo_selector_empieza_con_el_modelo():
    selectores = list(_selectores(_hoja()))
    assert len(selectores) > 100
    malos = [sel for sel in selectores if not sel.startswith('html[data-tema="noticiero"]')]
    assert not malos, malos


def test_los_colores_salen_de_variables():
    sueltos = []
    for linea in _sin_comentarios(_hoja()).splitlines():
        decl = linea.strip()
        if decl.startswith("--"):
            continue
        for hexa in re.findall(r"#[0-9a-fA-F]{3,8}\b", decl):
            if hexa.lower() not in ("#fff", "#ffffff"):
                sueltos.append(decl)
    assert not sueltos, sueltos


def test_la_paleta_del_sindicato_se_deriva_de_la_marca():
    css = _sin_comentarios(_hoja())
    m = re.search(r'html\[data-tema="noticiero"\]\[data-paleta="sindicato"\]\s*\{([^}]*)\}', css)
    assert m, "falta la paleta del sindicato"
    cuerpo = m.group(1)
    # la correspondencia del .pg del mockup: tinta índigo -> base, coral -> acento
    assert re.search(r"--nt-indigo:\s*var\(--marca-base\)", cuerpo)
    assert re.search(r"--nt-tinta:\s*var\(--marca-base\)", cuerpo)
    assert re.search(r"--nt-indigo-2:\s*var\(--marca-primario\)", cuerpo)
    assert re.search(r"--nt-coral:\s*var\(--marca-acento\)", cuerpo)
    assert "var(--marca-tinta-acento" in cuerpo and "var(--marca-acento-txt" in cuerpo
    for var in ("--nt-fondo", "--nt-hoja", "--nt-carta", "--nt-linea", "--nt-coral-suave"):
        assert re.search(rf"{var}\s*:\s*color-mix\(in oklab", cuerpo), var
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", cuerpo), "la paleta del sindicato no lleva colores fijos"


def test_el_riel_esta_numerado_con_un_contador():
    css = _sin_comentarios(_hoja())
    assert "counter-reset: nt-sec" in css
    assert re.search(r'\.tab-btn \{[^}]*counter-increment: nt-sec', css)
    assert "content: counter(nt-sec, decimal-leading-zero)" in css
    assert 'content: "Índice del panel"' in css


def test_el_riel_es_fijo_en_escritorio_y_tira_en_telefono():
    css = _sin_comentarios(_hoja())
    escritorio = css[css.index("@media (min-width: 761px)"):]
    nav = re.search(r'\.nav-strip \{([^}]*)\}', escritorio).group(1)
    assert "position: fixed" in nav and "flex-direction: column" in nav
    assert "margin: 0 0 0 var(--nt-riel)" in escritorio
    telefono = css[css.index("@media (max-width: 760px)"):]
    assert "position: fixed" not in re.search(r'\.nav-strip \{([^}]*)\}', telefono).group(1)


def test_ninguna_seleccion_con_barra_al_costado():
    css = _hoja()
    # ningún borde izquierdo con grosor y color
    for m in re.finditer(r"border-left\s*:\s*([^;}]+)", _sin_comentarios(css)):
        assert m.group(1).strip() in ("0", "none"), m.group(0)
    # lo elegido (activa, actual, marcado, abierta) no lleva sombra desplazada en x
    elegidos = re.compile(r"\.activa|\.actual|:checked|\.elegido|\.abierta|\.fijo")
    for sel, cuerpo in _reglas(css):
        if elegidos.search(sel):
            for m in re.finditer(r"inset\s+(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px", cuerpo):
                assert float(m.group(1)) == 0, (sel, m.group(0))
    # la activa del riel: la pastilla entera en índigo
    activa = re.search(r'html\[data-tema="noticiero"\] \.tab-btn\.activa \{([^}]*)\}', _sin_comentarios(css)).group(1)
    assert "background: var(--nt-indigo)" in activa


def test_fuentes_vendoreadas():
    css = _hoja()
    assert 'url("/static/fonts/anton.woff2")' in css and 'url("/static/fonts/archivo.woff2")' in css
    assert Path("static/fonts/anton.woff2").exists() and Path("static/fonts/archivo.woff2").exists()
    assert "http://" not in css and "https://" not in css


def test_respeta_menos_movimiento():
    assert "@media (prefers-reduced-motion: reduce)" in _hoja()
