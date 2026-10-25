"""Los dos modelos de diseño en el Panel Sindical (PLAN_TEMAS.md; la v2 del
panel reemplazó a la v1 el 2026-10-25).

Lo que se verifica:
- /admin/dashboard marca `data-tema`/`data-paleta` en <html>, vuelca la
  paleta legible del sindicato y carga static/temas/<modelo>-tablero.css con
  su sello, DESPUÉS de los estilos de la página, solo la del modelo elegido.
- Inicio y Salir flotan juntos, con su rótulo, como en /admin.
- Las dos hojas respetan las reglas de los modelos: todo selector empieza con
  el modelo, los colores salen de variables, la paleta del sindicato se
  deriva de --marca-*, ninguna selección se marca con una barra de color al
  costado, sin trama de colmena, y le dicen a los gráficos con qué pintar
  (--graf-*), que graficos.js lee de las variables.
- Lo que se resolvió de la auditoría (encargo "tablero"): estados vacíos
  (G7-01), leyenda de Trámites con el color del estado (G7-05), fecha del
  encabezado en el teléfono (G7-03), explorador como fichas en el teléfono
  (G7-04), aviso de movimiento en una línea y que no vuelve (G7-21) y la
  celda huérfana de los indicadores chicos (G7-22). El período inicial de
  30 días (G7-02) lo prueba test_dashboard_v2_nucleo.py corriendo el núcleo.

Correr con: python -m pytest test_tema_tablero.py -q
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

OPERADOR = "20412233469"
PANEL = Path("static/panel_v2")
HOJAS = {m: Path(f"static/temas/{m}-tablero.css") for m in ("laguna", "noticiero")}

with db.get_session() as s:
    sind = Sindicato(nombre="Tablero Temas UOM", slug="tablero-temas-uom", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=["recibos", "dashboard", "tramites", "notificaciones"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=OPERADOR, nombre="Marta Ríos",
                           clave_hash=auth.hashear_clave("clave-op"), es_super_admin=True))
    s.commit()


def _operador(tema):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": OPERADOR, "clave": "clave-op"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert c.post("/admin/apariencia/mia", data={"tema": tema}).status_code == 200
    return c


def _sin_comentarios(texto: str) -> str:
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.S)


def _js(nombre: str) -> str:
    return (PANEL / nombre).read_text(encoding="utf-8")


# ---------------------------------------------------------------- la página

def test_cada_modelo_carga_su_hoja_con_sello():
    for tema, otro in (("laguna", "noticiero"), ("noticiero", "laguna")):
        html = _operador(tema).get("/admin/dashboard").text
        assert f'data-tema="{tema}"' in html.split(">", 2)[1], tema
        assert 'data-paleta="' in html.split(">", 2)[1]
        sello = main._sello_static(f"temas/{tema}-tablero.css")
        assert sello, f"falta static/temas/{tema}-tablero.css"
        assert f'href="/static/temas/{tema}-tablero.css?v={sello}"' in html
        # después de los estilos del panel, para poder pisarlos
        assert html.index(f"/static/temas/{tema}-tablero.css?v=") > html.index("</style>")
        assert html.index(f"/static/temas/{tema}-tablero.css?v=") > html.index("panel_v2/panel.css")
        assert f"/static/temas/{otro}-tablero.css" not in html


def test_la_paleta_legible_viaja_en_la_pagina():
    html = _operador("laguna").get("/admin/dashboard").text
    raiz = html[html.index(":root {"):html.index("</style>")]
    for var in ("--marca-tinta-acento", "--marca-acento-txt", "--marca-primario-relleno",
                "--marca-base-tinta", "--destacado"):
        assert var + ":" in raiz, var


def test_inicio_y_salir_flotan_juntos_con_rotulo():
    html = _operador("noticiero").get("/admin/dashboard").text
    flota = html[html.index('<div class="flota-sesion">'):]
    flota = flota[:flota.index("</div>")]
    assert re.search(r'<a class="btn-home" href="/admin/inicio"[^>]*>.*?<span class="btn-rot">Inicio</span>', flota, re.S)
    assert re.search(r'<a class="btn-cerrar" href="/admin/salir"[^>]*>.*?<span class="btn-rot">Salir</span>', flota, re.S)
    assert re.search(r'<script defer src="/static/flota\.js\?v=\d+-\d+">', html)


# ---------------------------------------------------------------- las hojas

def _selectores(css: str):
    """Los selectores de cada regla (sin comentarios, @font-face ni los
    envoltorios @media/@supports), partidos por las comas de afuera."""
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


def test_todo_selector_empieza_con_el_modelo():
    for tema, hoja in HOJAS.items():
        selectores = list(_selectores(hoja.read_text(encoding="utf-8")))
        assert len(selectores) > 60, tema
        malos = [s for s in selectores if not s.startswith(f'html[data-tema="{tema}"]')]
        assert not malos, (tema, malos)


def test_los_colores_salen_de_variables():
    for tema, hoja in HOJAS.items():
        sueltos = []
        for linea in _sin_comentarios(hoja.read_text(encoding="utf-8")).splitlines():
            decl = linea.strip()
            if decl.startswith("--"):
                continue
            sueltos += [decl for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", decl)
                        if h.lower() not in ("#fff", "#ffffff")]
        assert not sueltos, (tema, sueltos)


def test_la_paleta_del_sindicato_se_deriva_de_la_marca():
    for tema, hoja in HOJAS.items():
        css = _sin_comentarios(hoja.read_text(encoding="utf-8"))
        m = re.search(rf'html\[data-tema="{tema}"\]\[data-paleta="sindicato"\]\s*\{{([^}}]*)\}}', css)
        assert m, f"{tema}: falta la paleta del sindicato"
        assert "var(--marca-" in m.group(1)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", m.group(1)), f"{tema}: colores fijos en la paleta del sindicato"


def test_ninguna_seleccion_con_barra_al_costado_ni_colmena():
    for tema, hoja in HOJAS.items():
        css = _sin_comentarios(hoja.read_text(encoding="utf-8"))
        for m in re.finditer(r"border-left\s*:\s*([^;}]+)", css):
            valor = m.group(1).strip()
            # 0, o a lo sumo el filete neutro de 1px que separa columnas
            assert valor in ("0", "none") or re.fullmatch(r"1px solid var\(--\w+-linea\w*\)", valor), (tema, valor)
        # la trama de colmena de fondo es el diseño viejo
        assert "hexagon" not in css.lower() and "panal" not in css.lower(), tema
        for m in re.finditer(r"background(?:-image)?\s*:[^;}]*url\(([^)]*)\)", css):
            assert "colmena" not in m.group(1), (tema, m.group(0))


def test_los_graficos_toman_los_colores_del_modelo():
    for tema, hoja in HOJAS.items():
        css = _sin_comentarios(hoja.read_text(encoding="utf-8"))
        for var in ("--graf-primario", "--graf-acento", "--graf-linea", "--graf-texto",
                    "--graf-fuente", "--graf-ok", "--graf-error", "--graf-aviso"):
            assert re.search(rf"{var}\s*:", css), (tema, var)
        # el semáforo y los estados nunca toman la marca
        for var in ("--graf-ok", "--graf-error", "--graf-aviso"):
            valor = re.search(rf"{var}\s*:\s*([^;]+);", css).group(1)
            assert "marca" not in valor, (tema, var, valor)
    js = _sin_comentarios(_js("graficos.js"))
    assert 'v("--graf-" + n)' in js, "graficos.js tiene que leer las variables --graf-*"
    assert "Chart.defaults.color" in js and "Chart.defaults.font.family" in js


# ---------------------------------------------------------------- la auditoría

def test_g7_01_estados_vacios_y_ejes_de_conteo():
    js = _sin_comentarios(_js("graficos.js"))
    assert "export function vacioDe" in js
    assert "precision: 0" in js and "suggestedMax: 5" in js
    app = _sin_comentarios(_js("app.js"))
    assert 'vacio("serie")' in app and "Ver los últimos" in app
    css = _sin_comentarios((PANEL / "panel.css").read_text(encoding="utf-8"))
    assert ".panel.vacio .c-wrap" in css and ".v2-vacio" in css


def test_g7_05_la_leyenda_de_tramites_lleva_el_color_del_estado():
    js = _sin_comentarios(_js("graficos.js"))
    tramites = js[js.index("export function Tramites"):js.index("export function Notificaciones")]
    assert "generateLabels" in tramites and "[C.aviso, C.apoyo, C.ok][i]" in tramites


def test_g7_03_la_fecha_del_encabezado_en_el_telefono():
    css = _sin_comentarios((PANEL / "panel.css").read_text(encoding="utf-8"))
    assert ".marca-barra .marca-fecha strong { text-transform: none; }" in css
    telefono = css[css.index("@media (max-width: 600px)"):]
    assert ".marca-barra .marca-fecha strong { display: none; }" in telefono
    app = _sin_comentarios(_js("app.js"))
    assert "charAt(0).toUpperCase()" in app and "fCorta" in app


def test_g7_04_el_explorador_en_el_telefono_son_fichas():
    exp = _sin_comentarios(_js("explorador.js"))
    assert 'setAttribute("data-et"' in exp
    assert 'class="vacio-exp" id="tabla-vacia"' in exp
    css = _sin_comentarios((PANEL / "panel.css").read_text(encoding="utf-8"))
    assert ".tabla-exp thead { display: none; }" in css
    assert "content: attr(data-et)" in css


def test_g7_21_el_aviso_de_movimiento_se_pliega_y_no_vuelve():
    app = _sin_comentarios(_js("app.js"))
    assert "<details>" in app and "<summary>" in app
    assert "localStorage.setItem(AVISO_MOV" in app
    # toda lectura y escritura del almacenamiento, envuelta
    for m in re.finditer(r"localStorage\.\w+\(", app):
        antes = app[max(0, m.start() - 60):m.start()]
        assert "try {" in antes, app[m.start() - 60:m.end()]


def test_g7_22_sin_celda_huerfana_en_los_indicadores_chicos():
    css = _sin_comentarios((PANEL / "panel.css").read_text(encoding="utf-8"))
    assert ".v2-minis > .v2-mini:last-child:nth-child(odd) { grid-column: 1 / -1; }" in css


# ---------------------------------------------------------------- segunda auditoría (R4)

def _css_panel(comentarios=False):
    css = (PANEL / "panel.css").read_text(encoding="utf-8")
    return css if comentarios else _sin_comentarios(css)


def test_r4_01_volver_al_panel():
    """Se entra desde la tira de /admin: «Volver al panel» lleva ahí en un
    paso, a la izquierda de la fecha."""
    for tema in ("laguna", "noticiero"):
        html = _operador(tema).get("/admin/dashboard").text
        assert re.search(r'<a class="marca-volver" href="/admin">', html), tema
        assert html.index('id="hoy-fecha"') < html.index('class="marca-volver"')  # el parcial la pone después...
    css = _css_panel()
    assert ".marca-barra .marca-volver { order: 1;" in css          # ...y el CSS la lleva antes
    assert ".marca-barra .marca-fecha { order: 2;" in css
    assert '.marca-barra .marca-volver::after { content: "al panel"; }' in css
    # sobre el blanco de los dos modelos, en tinta
    for tema, hoja in HOJAS.items():
        assert re.search(rf'html\[data-tema="{tema}"\] \.marca-volver \{{[^}}]*color: var\(--\w+-tinta\)',
                         _sin_comentarios(hoja.read_text(encoding="utf-8"))), tema


def test_r4_02_numeros_en_argentino_en_ejes_y_cuil(tmp_path):
    import shutil
    import subprocess
    html = _operador("laguna").get("/admin/dashboard").text
    sello = main._sello_static("numeros_ar.js")
    assert f'src="/static/numeros_ar.js?v={sello}"' in html
    assert html.index("/static/numeros_ar.js") < html.index('<script type="module" src="/static/panel_v2/app.js')
    js = _sin_comentarios(_js("graficos.js"))
    assert 'Chart.defaults.locale = "es-AR"' in js
    assert "fmtMEje(v)" in js and "fmtEje(v)" in js
    assert '+ "k"' not in js and '"M" :' not in js
    exp = _sin_comentarios(_js("explorador.js"))
    assert "fCuil(r.trabajador_cuil)" in exp and "${r.trabajador_cuil ||" not in exp
    node = shutil.which("node")
    if not node:
        return
    (tmp_path / "formato.mjs").write_text(_js("formato.js"), encoding="utf-8")
    (tmp_path / "numeros_ar.js").write_text(Path("static/numeros_ar.js").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "prueba.mjs").write_text("""
import fs from "node:fs";
globalThis.window = globalThis;
(0, eval)(fs.readFileSync(new URL("./numeros_ar.js", import.meta.url), "utf8"));
const { fmtEje, fmtMEje, fCuil } = await import("./formato.mjs");
console.log(JSON.stringify({ eje: [fmtEje(1000), fmtEje(2500), fmtEje(0)],
  monto: [fmtMEje(0), fmtMEje(500000), fmtMEje(1500000), fmtMEje(2000000), fmtMEje(750)],
  cuil: [fCuil("20660000048"), fCuil(""), fCuil("123")] }));
""", encoding="utf-8")
    import json
    r = json.loads(subprocess.run([node, str(tmp_path / "prueba.mjs")], capture_output=True, text=True,
                                  check=True).stdout)
    assert r["eje"] == ["1.000", "2.500", "0"]
    assert r["monto"] == ["$ 0", "$ 500 mil", "$ 1,5 M", "$ 2 M", "$ 750"]
    assert r["cuil"] == ["20-66000004-8", "—", "123"]


def test_r4_03_ficha_compacta_y_pestana_corta_en_el_telefono():
    exp = _sin_comentarios(_js("explorador.js"))
    # las cuatro tablas con "Ver" marcan su ficha: título, valor, renglón gris y "Ver" estirado
    assert exp.count('<tr class="ficha">') == 4
    assert exp.count('class="f-ver"') == 4 and exp.count("${meta(") == 4
    assert 'notificaciones: "Notif."' in exp and 'class="t-corto"' in exp
    css = _css_panel()
    crudo = _css_panel(comentarios=True)
    ficha = crudo[crudo.index("R4-03: el explorador"):]
    assert ".tabla-exp td.f-meta, .tab-d .t-corto { display: none; }" in css
    assert ".tabla-exp tr.ficha td { display: none; }" in ficha
    assert "min-height: 44px" in ficha
    assert ".tabla-exp tr.ficha td.f-ver { display: block; position: absolute; inset: 0;" in ficha
    # las fichas arrancan en 760 px, como el resto de la pantalla
    assert "@media (max-width: 760px) {\n  .tabs-datos {" in css


def test_r4_04_controles_del_periodo_a_44_px():
    crudo = _css_panel(comentarios=True)
    bloque = crudo[crudo.index("R4-04: los controles"):]
    assert ".v2-barra .v2-chip, .v2-barra .v2-btn-filtros { min-height: 44px; }" in bloque
    assert ".v2-barra .v2-reiniciar { padding: 12px 4px; min-height: 44px; }" in bloque
    assert ".v2-presets { gap: 8px; }" in bloque


def test_r4_10_un_solo_encuadre_para_los_dos_mapas():
    mapa = _sin_comentarios(Path("static/mapa.js").read_text(encoding="utf-8"))
    assert "function encuadrarTablero(mapa, puntos)" in mapa
    assert "padding: [56, 56], maxZoom: 7" in mapa
    assert "function separarBurbujas(mapa, capa)" in mapa
    assert "encuadrarTablero: encuadrarTablero" in mapa and "separarBurbujas: separarBurbujas" in mapa
    # la burbuja sabe su lugar real y su diámetro, para correrla y trazar la guía
    assert "marca._lugar = L.latLng(lat, lon);" in mapa and "L.polyline([m._lugar" in mapa
    graf = _sin_comentarios(_js("graficos.js"))
    enc = _sin_comentarios(Path("static/encuesta_resultados.js").read_text(encoding="utf-8"))
    for nombre, js in (("panel", graf), ("encuesta", enc)):
        assert "MapaMT.encuadrarTablero(" in js and "MapaMT.separarBurbujas(" in js, nombre
        assert "fitBounds" not in js and ".encuadrar(" not in js, nombre
    # en el teléfono el + y el − no tapan burbujas: se acerca con dos dedos
    assert ".mapa-panel .leaflet-control-zoom { display: none; }" in _css_panel()


def test_r4_11_laguna_rotula_los_indicadores_como_resultados():
    css = _sin_comentarios(HOJAS["laguna"].read_text(encoding="utf-8"))
    m = re.search(r'html\[data-tema="laguna"\] :is\(\.v2-kicker, \.v2-hero \.et, \.v2-mini \.et\) \{([^}]*)\}', css)
    assert m, "los nueve rótulos de indicador van juntos"
    assert "700 11px" in m.group(1) and "letter-spacing: .12em" in m.group(1) and "uppercase" in m.group(1)
    enc = _sin_comentarios(Path("static/temas/laguna-encuesta-resultados.css").read_text(encoding="utf-8"))
    secc = re.search(r'html\[data-tema="laguna"\] h2\.secc \{([^}]*)\}', enc).group(1)
    assert "font-size: 17px" in secc and "text-transform: none" in secc
    kpi = re.search(r'html\[data-tema="laguna"\] \.kpi \.et \{([^}]*)\}', enc).group(1)
    assert "letter-spacing: .12em" in kpi and "uppercase" in kpi
