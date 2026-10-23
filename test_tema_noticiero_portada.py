"""El modelo Noticiero en la portada del afiliado (PLAN_TEMAS.md, bloque 4).

Verifica la hoja static/temas/noticiero-portada.css (se carga solo con
Noticiero, con sello y después de los estilos de la página; todo selector
empieza con html[data-tema="noticiero"]; sus fuentes son locales) y la cinta
de titulares, la única pieza de estructura propia del modelo: existe solo en
Noticiero y no se ve si la hoja no está.

Las pautas comunes de la portada (orden de accesos, nota de tapa, Salir
flotando, sin diferencias) las verifica test_tema_laguna_portada.py.

Correr con: python -m pytest test_tema_noticiero_portada.py -q
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

AFILIADO = "27345678904"
HOJA = Path("static/temas/noticiero-portada.css")
PREFIJO = 'html[data-tema="noticiero"]'

with db.get_session() as s:
    sind = Sindicato(nombre="Noticiero Portada", slug="noticiero-portada", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=list(MODULOS))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(CuentaTrabajador(cuil=AFILIADO, nombre="Ana Ruiz", clave_hash=auth.hashear_clave("x"),
                           provincia="Córdoba", localidad="Río Cuarto"))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO, registrado=True, activo=True))
    s.add(db.Noticia(sindicato_id=SID, titulo="Paritaria cerrada", bajada="La de tapa",
                     fecha_desde="2000-01-01", fecha_hasta="2999-12-31", creada="2026-02-01 09:00"))
    s.add(db.Noticia(sindicato_id=SID, titulo="Jornada de salud",
                     fecha_desde="2000-01-01", fecha_hasta="2999-12-31", creada="2026-01-01 09:00"))
    s.add(db.Beneficio(sindicato_id=SID, rubro="Turismo", descripcion="20% en el hotel",
                       fecha_desde="2000-01-01", fecha_hasta="2999-12-31"))
    s.commit()


def _portada():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=AFILIADO))
    r = c.get("/app/inicio")
    assert r.status_code == 200, r.text
    return r.text


def _con_tema(tema):
    assert db.guardar_tema_persona(AFILIADO, tema, "afiliado")


def _sin_comentarios(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_la_hoja_se_carga_solo_con_noticiero_y_con_sello():
    _con_tema("noticiero")
    try:
        html = _portada()
        assert 'data-tema="noticiero"' in html
        m = re.search(r'href="/static/temas/noticiero-portada\.css\?v=([^"]+)"', html)
        assert m and m.group(1), "la hoja de Noticiero tiene que ir con sello ?v="
        assert html.index("</style>") < m.start(), "va después de los estilos de la página"
        assert "laguna-portada.css" not in html
    finally:
        _con_tema("")
    _con_tema("laguna")
    try:
        html = _portada()
        assert "noticiero-portada.css" not in html
    finally:
        _con_tema("")


def test_todo_selector_de_la_hoja_es_de_noticiero():
    css = _sin_comentarios(HOJA.read_text(encoding="utf-8"))
    css = re.sub(r"@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    css = re.sub(r"@font-face\s*\{[^{}]*\}", "", css)
    selectores = re.findall(r"([^{}]+)\{[^{}]*\}", css)
    assert selectores
    for bloque in selectores:
        bloque = bloque.strip()
        if bloque.startswith("@media"):
            bloque = bloque.split("{")[-1].strip()
        if not bloque or bloque.startswith("@"):
            continue
        partes, nivel, actual = [], 0, ""
        for ch in bloque:
            nivel += ch == "(" ; nivel -= ch == ")"
            if ch == "," and nivel == 0:
                partes.append(actual); actual = ""
            else:
                actual += ch
        partes.append(actual)
        for sel in partes:
            assert sel.strip().startswith(PREFIJO), sel


def test_las_fuentes_son_locales_y_existen():
    css = HOJA.read_text(encoding="utf-8")
    caras = re.findall(r"@font-face\s*\{([^{}]*)\}", css)
    familias = {re.search(r'font-family:\s*"([^"]+)"', c).group(1) for c in caras}
    assert {"Anton", "Archivo"} <= familias
    for url in re.findall(r"url\(\"?([^\")]+)\"?\)", css):
        if url == "/logo-plataforma":   # el logo de Colm3na para fondo claro, de la propia app
            continue
        assert url.startswith("/static/"), f"nada de CDN (CSP): {url}"
        assert Path(url.lstrip("/")).exists(), url
    archivo = next(c for c in caras if '"Archivo"' in c)
    assert "font-weight: 100 900" in archivo and "font-stretch: 62% 125%" in archivo


def test_paleta_estados_y_movimiento():
    css = HOJA.read_text(encoding="utf-8")
    sin = _sin_comentarios(css)
    assert f'{PREFIJO}[data-paleta="sindicato"]' in sin
    for marca in ("--marca-base", "--marca-primario", "--marca-acento"):
        assert marca in sin, marca
    # nada marcado con una barra al costado
    for prop in re.findall(r"border-left\s*:[^;]+;", sin):
        assert re.search(r":\s*0\s*;", prop), prop
    assert not re.search(r"box-shadow\s*:\s*inset\s+-?[1-9]\d*px\s+0", sin), \
        "nada de filetes laterales hechos con box-shadow"
    assert "prefers-reduced-motion" in sin


def test_la_cinta_de_titulares_es_solo_de_noticiero():
    _con_tema("laguna")
    try:
        assert 'class="pt-tick"' not in _portada()
    finally:
        _con_tema("")
    _con_tema("noticiero")
    try:
        html = _portada()
    finally:
        _con_tema("")
    cuerpo = html[html.index("<body"):]
    m = re.search(r'<a class="pt-tick" href="/app\?tab=novedades"[^>]*>(.*?)</a>', cuerpo, re.S)
    assert m, "la cinta lleva a Novedades"
    cinta = m.group(1)
    for texto in ("Paritaria cerrada", "Jornada de salud", "20% en el hotel"):
        # dos vueltas para el desplazamiento continuo: la segunda, oculta al lector
        assert cinta.count(texto) == 2, texto
    assert cinta.count('aria-hidden="true">Paritaria cerrada') == 1
    # va entre la tapa del gremio y el cuerpo
    assert cuerpo.index('class="pt-gremio') < m.start() < cuerpo.index('class="pad pt-cuerpo"')
    # sin la hoja del modelo, no se ve
    assert re.search(r"\.pt-tick\s*\{\s*display:\s*none;", html)
    assert re.search(re.escape(PREFIJO) + r" \.pt-tick \{[^}]*display: flex", HOJA.read_text(encoding="utf-8"))
