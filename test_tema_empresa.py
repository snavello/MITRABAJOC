"""Los dos modelos de diseño en la app de la empresa (/empresa/inicio y
/empresa) — PLAN_TEMAS.md, llevado al empleador.

Lo que tienen que garantizar las plantillas y la cuenta, más allá de cómo
se vea:
- las dos páginas marcan `data-tema` y `data-paleta` en <html>;
- la hoja de cada modelo (static/temas/<modelo>-empresa-portada.css y
  <modelo>-empresa.css) se carga SOLO con ese modelo, con su sello ?v=, y
  todos sus selectores están acotados al modelo;
- no está la trama de colmena del diseño viejo;
- el default es el modelo que el sindicato eligió para sus AFILIADOS, y la
  elección de la empresa (en su cuenta, CuentaEmpleador.tema) le gana;
- un valor fuera del catálogo no se guarda;
- Salir lleva su rótulo y cada pestaña su título de la casa.

Correr con: python -m pytest test_tema_empresa.py -q
"""
import os
import re
from pathlib import Path

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import auth
import db
import main
import temas
from db import CuentaEmpleador, Empleador, Sindicato
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES
from sqlmodel import select

db.crear_tablas()

CUIT = "30712345674"
CUIT_SIN_CUENTA = "30712345682"

with db.get_session() as s:
    sind = Sindicato(nombre="Tema Empresa", slug="tema-empresa", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"],
                     tema_afiliados="noticiero", tema_panel="laguna", paleta_tema="sindicato")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Empleador(sindicato_id=SID, cuit=CUIT, razon_social="Talleres del Litoral SA", activo=True))
    s.add(CuentaEmpleador(cuit=CUIT, clave_hash=auth.hashear_clave("x")))
    s.commit()


def _cliente():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0, ident=CUIT))
    c.cookies.set("cuit_emp", CUIT)
    return c


def _paginas(tema=None):
    """Las dos páginas de la empresa con el modelo `tema` elegido (None = el del sindicato)."""
    assert db.guardar_tema_persona(CUIT, tema or "", "empresa")
    c = _cliente()
    salida = {}
    for ruta in ("/empresa/inicio", "/empresa"):
        r = c.get(ruta)
        assert r.status_code == 200, (ruta, r.text[:300])
        salida[ruta] = r.text
    return salida


def _hoja(ruta):
    return "empresa-portada" if ruta == "/empresa/inicio" else "empresa"


# ---------- data-tema / data-paleta ----------

def test_las_dos_paginas_marcan_modelo_y_paleta():
    for tema in ("laguna", "noticiero"):
        for ruta, html in _paginas(tema).items():
            assert re.search(r'<html lang="es" data-tema="%s" data-paleta="sindicato">' % tema, html), (ruta, tema)


def test_el_default_es_el_de_los_afiliados_del_sindicato():
    # El sindicato eligió Noticiero para sus afiliados y Laguna para el panel:
    # la empresa, actor externo como el afiliado, sigue al de los afiliados.
    for ruta, html in _paginas(None).items():
        assert 'data-tema="noticiero"' in html, ruta
    ap = db.apariencia_de(SID, CUIT, rol="empresa")
    assert ap == {"tema": "noticiero", "paleta": "sindicato", "elegido": "", "defecto": "noticiero"}


def test_la_eleccion_de_la_empresa_gana_sobre_el_default():
    for ruta, html in _paginas("laguna").items():
        assert 'data-tema="laguna"' in html, ruta
    ap = db.apariencia_de(SID, CUIT, rol="empresa")
    assert ap["tema"] == "laguna" and ap["elegido"] == "laguna" and ap["defecto"] == "noticiero"
    with db.get_session() as s:
        assert s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == CUIT)).first().tema == "laguna"


def test_los_roles_de_siempre_no_cambian():
    # Una empresa con el mismo número que un afiliado no le cambia el modelo a
    # nadie: cada rol lee su propia cuenta.
    assert db.apariencia_de(SID, CUIT, rol="afiliado")["elegido"] == ""
    assert db.apariencia_de(SID, CUIT, rol="panel")["tema"] == "laguna"


# ---------- las hojas ----------

def test_la_hoja_de_cada_modelo_carga_solo_con_ese_modelo_y_con_sello():
    for tema in ("laguna", "noticiero"):
        otro = "noticiero" if tema == "laguna" else "laguna"
        for ruta, html in _paginas(tema).items():
            hoja = _hoja(ruta)
            m = re.search(r'<link rel="stylesheet" href="/static/temas/%s-%s\.css\?v=([^"]+)">' % (tema, hoja), html)
            assert m and m.group(1), (ruta, tema)
            # Después de los estilos de la plantilla: si no, no los pisa.
            assert html.index("</style>") < m.start() < html.index("</head>"), (ruta, tema)
            assert f"{otro}-{hoja}.css" not in html, (ruta, tema)
            # Nunca la hoja del afiliado.
            assert f"/static/temas/{tema}-portada.css" not in html and f"/static/temas/{tema}-app.css" not in html


def _partir(lista):
    partes, nivel, actual = [], 0, ""
    for ch in lista:
        nivel += (ch == "(") - (ch == ")")
        if ch == "," and nivel == 0:
            partes.append(actual); actual = ""
        else:
            actual += ch
    return partes + [actual]


def test_todo_selector_de_las_hojas_esta_acotado_al_modelo():
    for tema in ("laguna", "noticiero"):
        for hoja in ("empresa-portada", "empresa"):
            css = Path(f"static/temas/{tema}-{hoja}.css").read_text(encoding="utf-8")
            css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
            css = re.sub(r"@font-face\s*\{[^{}]*\}", "", css)
            css = re.sub(r"@media[^{]*\{", "", css)
            sueltos = [sel.strip() for bloque in re.findall(r"([^{}]+)\{[^{}]*\}", css)
                       for sel in _partir(bloque)
                       if sel.strip() and not sel.strip().startswith(f'html[data-tema="{tema}"]')]
            assert not sueltos, (tema, hoja, sueltos[:5])
            assert f'html[data-tema="{tema}"][data-paleta="sindicato"]' in css, (tema, hoja)
            assert "prefers-reduced-motion" in Path(f"static/temas/{tema}-{hoja}.css").read_text(encoding="utf-8")


# ---------- sin colmena ----------

def test_no_esta_la_trama_de_colmena():
    for tema in ("laguna", "noticiero"):
        paginas = _paginas(tema)
        # La portada ya no dibuja el ambiente con la retícula de colmena.
        assert "pt-reticula" not in paginas["/empresa/inicio"]
        assert "pt-ambiente" not in paginas["/empresa/inicio"]
        # La app interior lleva la mesa (como el afiliado), pero la hoja del
        # modelo apaga su textura (la retícula) y la franja.
        css = Path(f"static/temas/{tema}-empresa.css").read_text(encoding="utf-8")
        assert re.search(r'html\[data-tema="%s"\] body\.mesa::before,\s*html\[data-tema="%s"\] body\.mesa\.franja::after \{ display: none; \}'
                         % (tema, tema), css), tema
        css = Path(f"static/temas/{tema}-empresa-portada.css").read_text(encoding="utf-8")
        assert ".pt-ambiente { display: none; }" in css, tema


# ---------- la elección se guarda en la cuenta ----------

def test_la_empresa_guarda_su_modelo_por_la_ruta():
    c = _cliente()
    r = c.post("/api/empresa/apariencia", data={"tema": "noticiero"})
    assert r.status_code == 200 and r.json() == {"ok": True, "tema": "noticiero"}
    assert db.apariencia_de(SID, CUIT, rol="empresa")["elegido"] == "noticiero"
    # Vacío vuelve a seguir al sindicato.
    assert c.post("/api/empresa/apariencia", data={"tema": ""}).json() == {"ok": True, "tema": ""}
    assert db.apariencia_de(SID, CUIT, rol="empresa")["elegido"] == ""


def test_un_valor_fuera_del_catalogo_no_se_guarda():
    c = _cliente()
    assert c.post("/api/empresa/apariencia", data={"tema": "laguna"}).status_code == 200
    r = c.post("/api/empresa/apariencia", data={"tema": "rosa-chicle"})
    assert r.status_code == 400
    with db.get_session() as s:
        assert s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == CUIT)).first().tema == "laguna"
    assert not db.guardar_tema_persona(CUIT, "<script>", "empresa")
    assert not db.guardar_tema_persona(CUIT_SIN_CUENTA, "laguna", "empresa")


def test_sin_sesion_de_empresa_no_se_guarda():
    assert TestClient(main.app).post("/api/empresa/apariencia", data={"tema": "laguna"}).status_code == 403
    # Una sesión de afiliado no sirve para la cuenta de la empresa.
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=CUIT))
    assert c.post("/api/empresa/apariencia", data={"tema": "laguna"}).status_code == 403


def test_el_perfil_ofrece_los_dos_modelos_del_catalogo():
    html = _paginas("laguna")["/empresa/inicio"]
    assert "fetch('/api/empresa/apariencia'" in html
    for clave, t in temas.TEMAS.items():
        assert f'<input type="radio" name="tema" value="{clave}"' in html
        assert t["descripcion"] in html
        assert f'>{t["nombre"]}' in html
    assert re.search(r'value="laguna" checked', html)
    assert 'data-defecto="noticiero"' in html


# ---------- pautas de la casa ----------

def test_salir_con_rotulo_y_sin_la_cruz():
    paginas = _paginas("laguna")
    portada, app = paginas["/empresa/inicio"], paginas["/empresa"]
    assert re.search(r'<a class="pt-salir" href="/empresa/salir">.*?<span>Salir</span>', portada, re.S)
    m = re.search(r'<nav class="flota-sal"[^>]*>(.*?)</nav>', app, re.S)
    assert m
    assert re.search(r'<a class="flota-ini" href="/empresa/inicio">.*?Inicio</a>', m.group(1), re.S)
    assert re.search(r'<a class="flota-salir" href="/empresa/salir">.*?Salir</a>', m.group(1), re.S)
    for html in (portada, app):
        assert "btn-flotante" not in html and "btn-cerrar" not in html
        assert "flota.js?v=" in html


def test_cada_pestana_con_su_titulo_de_la_casa():
    app = _paginas("noticiero")["/empresa"]
    assert '<h1 class="titulo-pagina">Notificaciones</h1>' in app
    assert '<h1 class="titulo-pagina">Trámites</h1>' in app
    # La razón social ya no es el título: va chica en la barra de la identidad.
    assert '<div class="ident-nombre">Talleres del Litoral SA</div>' in app
    assert f'<div class="ident-cuit">CUIT {CUIT}</div>' in app
    assert "<h1>Talleres del Litoral SA</h1>" not in app


def test_la_paleta_legible_llega_a_las_dos_paginas():
    paginas = _paginas("laguna")
    # Acento claro (ámbar): el texto encima va en la base del gremio.
    assert "--marca-tinta-acento: #0f2240;" in paginas["/empresa/inicio"]
    assert "--gremio-tinta-acento: #0f2240;" in paginas["/empresa"]
    assert "--gremio-acento: #e8b84b;" in paginas["/empresa"]
    # El filo ámbar de 5 px que la app le agregaba al encabezado común, fuera.
    assert ".marca-enc { border-left" not in paginas["/empresa"]
    assert "border-left:5px solid var(--marca-acento)" not in paginas["/empresa"]


def test_la_portada_dice_el_estado_de_cada_acceso():
    portada = _paginas("laguna")["/empresa/inicio"]
    assert "Sin mensajes nuevos" in portada
    assert "Ningún trámite en curso" in portada
    assert "Cuando tu sindicato te mande un aviso, lo vas a ver acá." in portada
