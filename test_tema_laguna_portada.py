"""El modelo Laguna en la portada del afiliado (PLAN_TEMAS.md, bloque 4).

Verifica la hoja static/temas/laguna-portada.css (se carga solo con Laguna,
con sello, y todo selector empieza con html[data-tema="laguna"]) y las
pautas comunes de la portada que van en la plantilla para los dos modelos:
sin diferencias ni faltantes, la última noticia como nota de tapa, los
accesos en un orden fijo, sin Inicio y con Salir flotando con su rótulo.

Correr con: python -m pytest test_tema_laguna_portada.py -q
"""
import os
import re
from pathlib import Path

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import auth
import db
import fechas
import main
from db import CuentaTrabajador, Sindicato, Trabajador
from fastapi.testclient import TestClient
from modulos import MODULOS

db.crear_tablas()

AFILIADO = "20345678902"
HOJA = Path("static/temas/laguna-portada.css")

with db.get_session() as s:
    sind = Sindicato(nombre="Laguna Portada", slug="laguna-portada", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=list(MODULOS))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(CuentaTrabajador(cuil=AFILIADO, nombre="Rosa Paz", clave_hash=auth.hashear_clave("x"),
                           provincia="Córdoba", localidad="Río Cuarto"))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO, registrado=True, activo=True))
    anio = fechas.hoy_texto()[:4]
    # Un recibo con diferencias: la portada NO lo tiene que decir.
    s.add(db.ReciboVerificado(sindicato_id=SID, cuil=AFILIADO, periodo=anio + "-02", estado="OK"))
    s.add(db.ReciboVerificado(sindicato_id=SID, cuil=AFILIADO, periodo=anio + "-03",
                              estado="CON_DISCREPANCIAS"))
    s.add(db.Noticia(sindicato_id=SID, titulo="Nota vieja", bajada="La de antes",
                     fecha_desde="2000-01-01", fecha_hasta="2999-12-31", creada="2026-01-01 09:00"))
    s.add(db.Noticia(sindicato_id=SID, titulo="Nota de tapa", bajada="La más nueva",
                     fecha_desde="2000-01-01", fecha_hasta="2999-12-31", creada="2026-02-01 09:00",
                     imagen1_datos=b"fake", imagen1_mime="image/png"))
    s.commit()


def _portada():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=AFILIADO))
    r = c.get("/app/inicio")
    assert r.status_code == 200, r.text
    return r.text


def _cuerpo():
    """Lo que se ve: el HTML del <body> (sin los comentarios del <style>)."""
    html = _portada()
    return html[html.index("<body"):]


def _con_tema(tema):
    assert db.guardar_tema_persona(AFILIADO, tema, "afiliado")


def test_la_hoja_se_carga_solo_con_laguna_y_con_sello():
    _con_tema("laguna")
    html = _portada()
    assert 'data-tema="laguna"' in html
    m = re.search(r'href="/static/temas/laguna-portada\.css\?v=([^"]+)"', html)
    assert m and m.group(1), "la hoja de Laguna tiene que ir con sello ?v="
    # después de los estilos de la página, para poder pisarlos
    assert html.index("</style>") < m.start()
    _con_tema("noticiero")
    try:
        html = _portada()
        assert 'data-tema="noticiero"' in html
        assert "laguna-portada.css" not in html
    finally:
        _con_tema("")


def test_todo_selector_de_la_hoja_es_de_laguna():
    css = re.sub(r"/\*.*?\*/", "", HOJA.read_text(encoding="utf-8"), flags=re.S)
    prefijo = 'html[data-tema="laguna"]'
    # bloques sueltos de @keyframes no son selectores de la página
    css = re.sub(r"@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    selectores = re.findall(r"([^{}]+)\{[^{}]*\}", css)
    assert selectores
    for bloque in selectores:
        bloque = bloque.strip()
        if bloque.startswith("@media"):
            bloque = bloque.split("{")[-1].strip()
        if not bloque or bloque.startswith("@"):
            continue
        # comas de primer nivel (las de :is(...) no separan selectores)
        partes, nivel, actual = [], 0, ""
        for ch in bloque:
            nivel += ch == "(" ; nivel -= ch == ")"
            if ch == "," and nivel == 0:
                partes.append(actual); actual = ""
            else:
                actual += ch
        partes.append(actual)
        for sel in partes:
            assert sel.strip().startswith(prefijo), sel


def test_la_hoja_no_marca_nada_con_una_barra_al_costado():
    css = HOJA.read_text(encoding="utf-8")
    for prop in re.findall(r"border-left\s*:[^;]+;", css):
        assert re.search(r":\s*0\s*;", prop), prop
    assert not re.search(r"box-shadow\s*:\s*inset\s+-?\d+px\s+0", css), \
        "nada de filetes laterales hechos con box-shadow"
    assert "prefers-reduced-motion" in css
    assert 'data-paleta="sindicato"' in css and "--marca-acento" in css


def test_el_orden_de_los_accesos():
    html = _cuerpo()
    orden = ["/app?tab=credencial", "/app?tab=tramites", "/app/notificaciones",
             "/app?tab=encuestas", "/app?tab=aportes", "/app?tab=capacitacion"]
    pos = [html.index(f'class="pt-fila pt-vid" href="{h}"') for h in orden]
    assert pos == sorted(pos), list(zip(orden, pos))


def test_la_portada_no_muestra_diferencias_ni_faltantes():
    html = _cuerpo()
    assert "recibos verificados este año" in html
    for texto in ("con diferencias", "sin diferencias", "faltante", "Faltan aportes", "impago"):
        assert texto not in html, texto


def test_no_hay_inicio_y_salir_flota_con_su_rotulo():
    html = _cuerpo()
    assert 'href="/app/inicio"' not in html
    assert "btn-home" not in html and 'title="Inicio"' not in html
    m = re.search(r'<a class="pt-salir" href="/trabajador/salir"[^>]*>(.*?)</a>', html, re.S)
    assert m and "<span>Salir</span>" in m.group(1)


def test_las_dos_ultimas_noticias_van_como_notas_de_tapa():
    html = _cuerpo()
    tapa = html[html.index('class="pt-tapa"'):html.index("pt-tapa-leer")]
    assert "Nota de tapa" in tapa and "La más nueva" in tapa
    assert "/noticia-imagen/" in tapa and "Lo último" in tapa
    assert "Nota vieja" not in tapa
    # la anterior es la segunda nota de tapa, sin el chip
    tapas = html.split('class="pt-tapas"', 1)[1].split("</section>", 1)[0]
    assert tapas.count("pt-tapa-leer") == 2 and "Nota vieja" in tapas
    assert tapas.count("pt-tapa-chip") == 1


def test_la_foto_de_portada_se_usa_si_hay():
    _con_tema("laguna")
    html = _portada()
    assert 'class="pt-gremio-foto"' not in html  # sin biblioteca, el degradé solo
    fid = db.crear_foto_tema("laguna", {"datos": b"x", "mime": "image/webp", "ancho": 1600, "alto": 900},
                             descripcion="test", foco_x=0.3, foco_y=0.7)
    try:
        db.editar_foto_tema(fid, publicada=True, todos_los_sindicatos=False, sindicatos=[SID])
        html = _portada()
        assert f'src="/foto-tema/{fid}?v=' in html and 'class="pt-gremio-foto"' in html
        assert "object-position: 30.0% 70.0%" in html  # el punto de interés manda el recorte
    finally:
        db.borrar_foto_tema(fid)
