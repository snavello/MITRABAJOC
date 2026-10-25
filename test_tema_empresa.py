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


# ---------- segunda auditoría (R1-01 a R1-07, G1-18) ----------

def _css(tema, hoja="empresa"):
    css = Path(f"static/temas/{tema}-{hoja}.css").read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _bloque_media(css, condicion):
    """El cuerpo de cada `@media <condicion> { ... }` de la hoja, juntos."""
    cuerpos = []
    for m in re.finditer(r"@media\s*%s\s*\{" % re.escape(condicion), css):
        nivel, i = 1, m.end()
        while nivel:
            nivel += (css[i] == "{") - (css[i] == "}")
            i += 1
        cuerpos.append(css[m.end():i - 1])
    return "\n".join(cuerpos)


def _regla(css, selector):
    """Las declaraciones de las reglas cuyo selector termina en `selector`."""
    return " ".join(re.findall(r"%s\s*\{([^{}]*)\}" % re.escape(selector), css))


def test_r1_01_el_resaltador_de_la_razon_social_no_pisa_el_renglon_de_abajo():
    css = _css("noticiero", "empresa-portada")
    hola = _regla(css, '.pt-gremio .hola')
    m = re.search(r"line-height:\s*([\d.]+)", hola)
    assert m and float(m.group(1)) >= 1.06, hola
    em = _regla(css, ".pt-gremio .hola em")
    assert "transparent 62%, var(--nt-resalta) 62%, var(--nt-resalta) 88%, transparent 88%" in em
    assert "box-decoration-break: clone" in em


def test_r1_02_lo_no_leido_va_en_el_color_del_modelo_y_no_en_rojo():
    laguna = _regla(_css("laguna"), ".notif-item.no-leida .nh-av::after")
    assert "var(--lg-turq)" in laguna and "--lg-mal" not in laguna
    noticiero_css = _css("noticiero")
    punto = _regla(noticiero_css, ".notif-item.no-leida .nh-av::after")
    assert "var(--nt-coral-ind)" in punto and "--nt-globo" not in punto
    burbuja = _regla(noticiero_css, ".notif-item.no-leida .nh-bur")
    assert "color-mix(in oklab, var(--nt-coral) 10%, var(--nt-carta))" in burbuja
    assert "color-mix(in oklab, var(--nt-coral) 35%, transparent)" in burbuja
    # El rojo sigue en el globo con el número de la tira.
    assert "var(--lg-mal)" in _regla(_css("laguna"), ".tab-badge")
    assert "var(--nt-globo)" in _regla(noticiero_css, ".tab-badge")


def test_r1_03_la_bajada_dice_cuantos_avisos_faltan_leer():
    app = _paginas("laguna")["/empresa"]
    m = re.search(r'<h1 class="titulo-pagina">Notificaciones</h1>\s*'
                  r'<p class="notif-cant" id="notif-cant" aria-live="polite" hidden></p>\s*'
                  r'<p class="sub">Los avisos que te manda ', app)
    assert m, "la línea de pendientes va entre el título y la bajada del remitente"
    assert "<b>${pendientes} sin leer</b> de ${totalNotifEmpresa}" in app
    assert "Estás al día" in app
    # Se actualiza con el mismo número que el globo de la pestaña.
    assert re.search(r"function actualizarBadgeNotifEmpresa\(n\) \{.*?actualizarCantNotifEmpresa\(n\);", app, re.S)
    for tema in ("laguna", "noticiero"):
        css = _css(tema)
        assert _regla(css, "#tp-notificaciones .notif-cant"), tema
        assert "font-size: 13px" in _regla(css, "#tp-notificaciones .notif-cant + .sub"), tema


def test_r1_04_los_estados_del_tramite_con_el_codigo_de_colores_del_afiliado():
    app = _paginas("laguna")["/empresa"]
    # Sin colores en línea: las clases est-* (las mismas que el afiliado).
    assert "ESTADO_TAG_COLOR" not in app
    assert 'class="tx-tag ${claseEstadoTrx(estado)}"' in app
    assert 'class="tag ${claseEstadoTrx(estado)}"' in app
    assert "'est est-' + (ESTADOS_TRX.includes(estado) ? estado : 'iniciado')" in app
    afiliado = Path("templates/trabajador.html").read_text(encoding="utf-8")
    for estado in ("iniciado", "en_tratamiento", "respondido", "espera_info", "terminado"):
        assert f".est-{estado} {{" in app and f".est-{estado} {{" in afiliado, estado
    # Iniciado, solo el contorno, igual que el afiliado.
    assert ".est-iniciado { --est-f:var(--est-ini-f); --est-t:var(--est-ini-t); box-shadow:inset 0 0 0 1px currentColor; }" in app
    # Cada modelo pone los mismos colores de estado que en la app del afiliado.
    for tema in ("laguna", "noticiero"):
        def variables(css):
            bloque = re.search(r'html\[data-tema="%s"\] \{\s*(--est-ini-f[^}]*)\}' % tema, css).group(1)
            return dict(re.findall(r"(--est-[a-z-]+):\s*([^;]+);", bloque))
        assert variables(_css(tema)) == variables(_css(tema, "app")), tema
    assert "--lg-amb-t: #6a3f06;" in _css("laguna")


def test_r1_05_inicio_y_salir_miden_44_px_en_el_telefono():
    for tema in ("laguna", "noticiero"):
        movil = _bloque_media(_css(tema), "(max-width: 760px)")
        assert "height: 44px" in _regla(movil, ".ident .flota-sal a"), tema
        assert "36px" not in _regla(movil, ".ident .flota-sal"), tema
    app = _paginas("laguna")["/empresa"]
    assert ".ident .flota-sal a { height:44px;" in app
    assert re.search(r"\.ident \{ display:grid; grid-template-columns:minmax\(0,1fr\) auto;", app)


def test_r1_06_y_g1_18_la_identidad_la_columna_y_la_tira_leen_el_mismo_ancho():
    app = _paginas("laguna")["/empresa"]
    assert "--emp-col:680px;" in app
    escritorio_app = _bloque_media(re.sub(r"/\*.*?\*/", "", app, flags=re.S), "(min-width:761px)")
    assert ".cont { max-width:var(--emp-col); }" in escritorio_app
    assert "max-width:var(--emp-col); margin:0 auto;" in escritorio_app
    for tema, aire in (("laguna", "20px"), ("noticiero", "16px")):
        css = _css(tema)
        # El aire de la columna es el mismo que suma la barra de la identidad.
        assert re.search(r'html\[data-tema="%s"\] \.cont \{ padding: 24px %s ' % (tema, aire), css), tema
        escritorio = _bloque_media(css, "(min-width: 761px)")
        assert "max-width: var(--emp-col)" in _regla(escritorio, ".cont"), tema
        assert f"padding-inline: max({aire}, calc(50% - var(--emp-col) / 2 + {aire}))" in _regla(escritorio, ".ident"), tema
        tira = _regla(escritorio, ".tabbar")
        assert "max-width: var(--emp-col)" in tira and "margin: 0 auto" in tira and "border-bottom: 0" in tira, tema


def test_r1_07_salir_en_la_misma_esquina_en_la_portada_y_en_las_pestanas():
    for tema in ("laguna", "noticiero"):
        assert "right: 16px; bottom: calc(16px + env(safe-area-inset-bottom))" in _regla(_css(tema, "empresa-portada"), ".pt-sesion"), tema
        escritorio = _bloque_media(_css(tema), "(min-width: 761px)")
        assert "right: 16px; bottom: calc(16px + env(safe-area-inset-bottom))" in _regla(escritorio, ".flota-sal"), tema
        # Mientras la tira llegue hasta la esquina, la pastilla sube por encima.
        angosto = _bloque_media(_css(tema), "(min-width: 761px) and (max-width: 1159px)")
        assert "bottom: calc(80px" in _regla(angosto, ".flota-sal"), tema
        assert "calc(50% - 4" not in _css(tema), tema
    paginas = _paginas("laguna")
    assert ".pt-sesion { position: fixed; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom));" in paginas["/empresa/inicio"]
    assert ".flota-sal { right:16px; bottom:calc(16px + env(safe-area-inset-bottom)); }" in paginas["/empresa"]
