"""El modelo Noticiero en la app del afiliado (/app) — PLAN_TEMAS.md, bloque 4.

Lo que la plantilla y la hoja tienen que garantizar, más allá de cómo se vea:
- la hoja static/temas/noticiero-app.css se carga SOLO con el modelo
  noticiero, con su sello ?v=, después de los estilos de la plantilla; y la
  de Laguna sigue cargándose solo con Laguna;
- todos sus selectores están acotados a ese modelo;
- declara la paleta del sindicato a partir de los colores crudos del gremio,
  las dos tipografías vendoreadas y el movimiento reducido;
- el coral nunca es texto sobre el papel, y ninguna selección se marca con
  una barra de color a un costado (pautas del modelo y de SDN).

Correr con: python -m pytest test_tema_noticiero_app.py -q
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

AFILIADO = "20345678901"
HOJA = Path("static/temas/noticiero-app.css")
TEMA = 'html[data-tema="noticiero"]'

with db.get_session() as s:
    sind = Sindicato(nombre="Noticiero App", slug="noticiero-app", color_base="#0f1b2d",
                     color_primario="#7a1f2b", color_acento="#3d6b4a", color_secundario="#c19a3e",
                     modulos_habilitados=list(MODULOS))
    s.add(sind); s.commit(); s.refresh(sind)
    s.add(CuentaTrabajador(cuil=AFILIADO, nombre="Rosa Diario", clave_hash=auth.hashear_clave("x")))
    s.add(Trabajador(sindicato_id=sind.id, cuil=AFILIADO, registrado=True))
    s.commit()


def _app(tema="noticiero"):
    assert db.guardar_tema_persona(AFILIADO, tema, "afiliado")
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=AFILIADO))
    r = c.get("/app")
    assert r.status_code == 200, r.text
    return r.text


def _css_sin_comentarios():
    return re.sub(r"/\*.*?\*/", "", HOJA.read_text(encoding="utf-8"), flags=re.S)


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


# ---------- la carga de la hoja ----------

def test_la_hoja_se_carga_solo_con_noticiero_y_con_sello():
    html = _app("noticiero")
    assert 'data-tema="noticiero"' in html
    m = re.search(r'<link rel="stylesheet" href="/static/temas/noticiero-app\.css\?v=([^"]+)">', html)
    assert m and m.group(1), "falta la hoja de Noticiero o su sello ?v="
    # Va después de los estilos propios de la plantilla: si no, no los pisa.
    assert html.index("</style>") < m.start() < html.index("</head>")
    assert "laguna-app.css" not in html


def test_con_laguna_sigue_la_hoja_de_laguna_y_no_la_de_noticiero():
    html = _app("laguna")
    assert re.search(r'<link rel="stylesheet" href="/static/temas/laguna-app\.css\?v=[^"]+">', html)
    assert "noticiero-app.css" not in html


# ---------- la hoja ----------

def test_todo_selector_de_la_hoja_esta_acotado_al_modelo():
    css = _css_sin_comentarios()
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    css = re.sub(r"@font-face\s*\{[^{}]*\}", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    sueltos = []
    for bloque in re.findall(r"([^{}]+)\{[^{}]*\}", css):
        for sel in _partir(bloque):
            sel = sel.strip()
            if sel and not sel.startswith(TEMA):
                sueltos.append(sel)
    assert not sueltos, f"selectores sin {TEMA}: {sueltos[:5]}"


def test_la_hoja_declara_la_paleta_del_sindicato_las_fuentes_y_el_movimiento():
    css = HOJA.read_text(encoding="utf-8")
    assert f'{TEMA}[data-paleta="sindicato"]' in css
    # (el apoyo del gremio no tiene función en este modelo: el mockup solo lo usa en el mapa)
    for gremio in ("--gremio-base", "--gremio-primario", "--gremio-acento",
                   "--gremio-acento-txt", "--gremio-tinta-acento"):
        assert gremio in css, gremio
    # Tipografías vendoreadas (la CSP no deja CDN), con su @font-face acá.
    assert "/static/fonts/anton.woff2" in css
    assert "/static/fonts/archivo.woff2" in css
    assert "font-stretch: 62% 125%" in css
    assert Path("static/fonts/anton.woff2").exists() and Path("static/fonts/archivo.woff2").exists()
    assert "http://" not in css and "https://" not in css
    assert "prefers-reduced-motion" in css


def test_el_coral_nunca_es_texto():
    """El coral es relleno, resaltador o filete; como texto, solo sobre índigo
    (--nt-coral-txt-ind / --nt-coral-ind), nunca sobre el papel."""
    css = _css_sin_comentarios()
    malos = re.findall(r"(?<![-\w])color:\s*var\(--nt-coral(?:-suave)?\)", css)
    assert not malos, malos


def test_ninguna_seleccion_lleva_barra_al_costado():
    """La opción elegida se pinta entera; nunca un filo de color a un lado."""
    css = _css_sin_comentarios()
    malos = []
    for sel, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        # Las flechas (chevrones) se dibujan con dos bordes de un pseudo-elemento.
        if "::after" in sel or "::before" in sel:
            continue
        if re.search(r"border-(?:left|right)\s*:\s*(?!0)[^;]*\d+px", cuerpo):
            malos.append(sel.strip())
        # Un filo lateral hecho con sombra: inset Npx 0 0 <color> (N ≠ 0).
        if re.search(r"inset\s+-?[1-9][\d.]*px\s+0\s+0\s+(?!0)", cuerpo):
            malos.append(sel.strip())
    assert not malos, malos


# ---------- las pautas comunes siguen en pie con este modelo ----------

def test_inicio_y_salir_flotan_con_rotulo_y_los_importes_son_argentinos():
    html = _app("noticiero")
    m = re.search(r'<nav class="flota-sal"[^>]*>(.*?)</nav>', html, re.S)
    assert m
    assert re.search(r'<a class="flota-ini" href="/app/inicio">.*?Inicio</a>', m.group(1), re.S)
    assert re.search(r'<a class="flota-salir" href="/trabajador/salir">.*?Salir</a>', m.group(1), re.S)
    assert "toLocaleString('es-AR', {minimumFractionDigits:2, maximumFractionDigits:2})" in html
