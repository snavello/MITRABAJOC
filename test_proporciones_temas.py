"""Proporciones de las cuatro pantallas en los dos modelos (revisión del
2026-10-23, pedido de SDN: «los logos diminutos y la foto chica en
desktop»). Lo que la revisión fijó y no tiene que volver.

Correr con: python -m pytest test_proporciones_temas.py -q
"""
import re
from pathlib import Path

PLANTILLAS = ("trabajador", "admin", "portada", "admin_portada")
HOJAS = [f"{m}-{p}" for m in ("laguna", "noticiero") for p in ("portada", "app", "panel-portada", "panel")]


def _t(nombre):
    return Path(f"templates/{nombre}.html").read_text(encoding="utf-8")


def _h(nombre):
    return Path(f"static/temas/{nombre}.css").read_text(encoding="utf-8")


def test_la_pastilla_de_sesion_se_corre_al_bajar_en_las_cuatro():
    js = Path("static/flota.js").read_text(encoding="utf-8")
    for clase in (".flota-sal", ".flota-sesion", ".pt-sesion", ".pt-flota"):
        assert clase in js
    assert "position === 'fixed'" in js       # la que va quieta en la barra no se toca
    for nombre in PLANTILLAS:
        assert "/static/flota.js?v={{ sello_static('flota.js') }}" in _t(nombre), nombre


def test_en_el_telefono_inicio_y_salir_van_en_la_barra_del_nombre():
    html = _t("trabajador")
    ident = re.search(r'<div class="ident">(.*?)\n</div>', html, re.S).group(1)
    assert '<nav class="flota-sal"' in ident
    assert re.search(r"@media \(max-width:760px\) \{\s*\.ident \{ display:grid", html)


def test_beneficios_bajo_tus_cosas_en_escritorio():
    """SDN, 2026-10-26: dos notas de tapa a la izquierda; Tus cosas y
    Beneficios, uno debajo del otro, a la derecha."""
    assert 'grid-template-areas: "nov tus" "nov ben"' in _t("portada")


def test_la_portada_sin_alto_fijo_y_con_la_foto_de_perfil_junto_al_saludo():
    """SDN, 2026-10-24: con 440 px fijos el saludo quedaba lejos del
    encabezado. Ahora el alto lo dan el saludo y el widget de datos útiles, y
    la foto de perfil va grande, antes del saludo."""
    for hoja in ("laguna-portada", "noticiero-portada"):
        css = _h(hoja)
        assert re.search(r"\.pt-gremio(\.con-foto)? \{ min-height: 0; \}", css), hoja
        assert ".circulo-acento:has(img) { width: 120px; height: 120px; }" in css, hoja
    assert ".pt-gremio-hola .fila-hola > .circulo-acento { order: -1; }" in _t("portada")


def test_sin_logo_el_nombre_es_un_logotipo_del_mismo_tamano_en_las_cuatro():
    for hoja in HOJAS:
        css = _h(hoja)
        m = re.search(r'\.marca-barra \.marca-nombre \{[^}]*font-size: (\d+)px', css)
        assert m and int(m.group(1)) >= 30, hoja
        assert "-webkit-line-clamp: 2" in css, hoja


def test_la_app_en_escritorio_sigue_en_la_columna_del_telefono():
    """SDN, 2026-10-23: la columna de 680 px se veía peor distribuida que la
    del teléfono; se volvió a 520 / 540 y Inicio/Salir quedó afuera."""
    for hoja, ancho in (("laguna-app", 520), ("noticiero-app", 540)):
        css = _h(hoja)
        assert f".cont {{ max-width: {ancho}px; }}" in css, hoja
        assert "calc(50% - 634px)" not in css, hoja


def test_la_pestana_encuestas_tiene_titulo_y_estado_vacio():
    html = _t("trabajador")
    bloque = html.split('id="tp-encuestas"', 1)[1][:400]
    assert '<h1 class="titulo-pagina">Encuestas</h1>' in bloque
    assert 'class="vacio-tab"' in html


def test_colm3na_en_escritorio_a_34_px():
    assert "height: 34px" in Path("static/encabezado.css").read_text(encoding="utf-8").split(".marca-colmena {", 1)[1][:120]
    for hoja in ("laguna-app", "noticiero-app"):
        assert '.marca-colmena { height: 34px;' in _h(hoja), hoja


def test_los_grupos_del_panel_sin_titulo_a_la_vista():
    html = _t("admin_portada")
    assert "clip-path: inset(50%)" in html.split(".pt-grupo-tit {", 1)[1][:250]
    for hoja in ("laguna-panel-portada", "noticiero-panel-portada"):
        assert ".pt-grupo-tit {" not in _h(hoja), hoja


def test_la_tira_del_panel_muestra_la_pestana_elegida():
    assert "tira.scrollTo(" in _t("admin")
