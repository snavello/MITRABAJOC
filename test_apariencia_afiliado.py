"""Apariencia en el perfil del afiliado (PLAN_TEMAS.md, bloque 3a).

La portada (/app/inicio) trae, dentro del modal "Tu perfil", la sección
Apariencia: dos tarjetas-radio (Laguna y Noticiero) con la descripción de
temas.TEMAS, la elegida marcada según la cuenta, y una línea de solo lectura
con la paleta que decidió el sindicato.

Correr con: python -m pytest test_apariencia_afiliado.py -q
"""
import os
import re

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import auth
import db
import main
import temas
from db import CuentaTrabajador, Sindicato, Trabajador
from fastapi.testclient import TestClient

db.crear_tablas()

AFILIADO = "20345678901"

with db.get_session() as s:
    sind = Sindicato(nombre="Apariencia Afiliado", slug="apariencia-afiliado", color_base="#0f2240")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(CuentaTrabajador(cuil=AFILIADO, nombre="Rosa Paz", clave_hash=auth.hashear_clave("x"),
                           provincia="Córdoba", localidad="Río Cuarto"))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO, registrado=True))
    s.commit()


def _afiliado():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=AFILIADO))
    return c


def _portada():
    r = _afiliado().get("/app/inicio")
    assert r.status_code == 200, r.text
    return r.text


def _marcada(html):
    """El valor del radio de modelo que viene marcado."""
    radios = re.findall(r'<input type="radio" name="tema" value="(\w+)"([^>]*)>', html)
    assert {v for v, _ in radios} == set(temas.TEMAS), radios
    marcados = [v for v, resto in radios if "checked" in resto]
    assert len(marcados) == 1, radios
    return marcados[0]


def test_la_portada_trae_la_seccion_con_las_dos_opciones():
    html = _portada()
    assert 'id="ap-sec"' in html and ">Apariencia</h4>" in html
    assert "Elegí cómo querés ver la app. Se guarda en tu cuenta: la ves igual en cualquier teléfono." in html
    # Nombre y descripción, los mismos del catálogo (la plantilla no tiene
    # acceso a temas.py: si el catálogo cambia, este test lo avisa).
    for clave, t in temas.TEMAS.items():
        assert f'data-tema="{clave}"' in html
        assert t["nombre"] in html and t["descripcion"] in html, clave
    assert "Por defecto" in html
    # La sección vive dentro del modal del perfil.
    perfil = html.index('id="overlay-perfil"')
    assert perfil < html.index('id="ap-sec"') < html.index('id="overlay-mapa"')
    assert "fetch('/api/apariencia'" in html


def test_marca_la_elegida_segun_la_cuenta():
    assert db.guardar_tema_persona(AFILIADO, "", "afiliado")
    html = _portada()
    assert _marcada(html) == "laguna"
    assert 'data-defecto="laguna"' in html

    c = _afiliado()
    assert c.post("/api/apariencia", data={"tema": "noticiero"}).json() == {"ok": True, "tema": "noticiero"}
    assert _marcada(_portada()) == "noticiero"

    # Vacío vuelve al del sindicato.
    assert c.post("/api/apariencia", data={"tema": ""}).json() == {"ok": True, "tema": ""}
    assert _marcada(_portada()) == "laguna"


def test_sin_eleccion_sigue_al_sindicato_y_lo_manda_como_defecto():
    assert db.guardar_tema_persona(AFILIADO, "", "afiliado")
    assert db.set_apariencia_sindicato(SID, tema_afiliados="noticiero")
    try:
        html = _portada()
        assert _marcada(html) == "noticiero"
        assert 'data-defecto="noticiero"' in html
    finally:
        assert db.set_apariencia_sindicato(SID, tema_afiliados="laguna")


def test_la_linea_de_paleta_cambia_con_el_sindicato():
    colm3na = "La app se ve con los colores de Colm3na."
    sindicato = "Tu sindicato eligió mostrar la app con sus colores."
    html = _portada()
    assert colm3na in html and sindicato not in html
    assert db.set_apariencia_sindicato(SID, paleta="sindicato")
    try:
        html = _portada()
        assert sindicato in html and colm3na not in html
    finally:
        assert db.set_apariencia_sindicato(SID, paleta="colm3na")


def test_la_elegida_no_se_marca_con_una_barra_al_costado():
    """Regla de SDN: la elegida va con tinte, borde completo y tilde."""
    html = _portada()
    css = html[html.index("/* ---- Apariencia"):html.index("@media (max-width: 380px) { .ap-ops")]
    assert "border-left" not in css and "border-right" not in css
    assert ".ap-op:has(input:checked)" in css and ".ap-tilde" in css
