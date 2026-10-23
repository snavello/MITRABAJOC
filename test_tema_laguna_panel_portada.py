"""El modelo Laguna en la portada del panel del sindicato (PLAN_TEMAS.md,
bloque 6; mockup: figura E1 de p162-escritorio.html).

Lo que se verifica:
- la plantilla carga `static/temas/laguna-panel-portada.css` CON sello, solo
  con el modelo Laguna, y no apunta a una hoja que no existe;
- la hoja no se sale de su modelo (todo selector empieza con
  html[data-tema="laguna"]), saca los colores de sus variables, no define
  duraciones propias, respeta "reducir movimiento" y no marca nada con una
  barra de color al costado (D6);
- los colores del modelo y los derivados de los tres gremios de la demo se
  leen (≥ 4,5:1 el texto común);
- las pautas comunes: Salir flota abajo con su rótulo, Inicio no está, "Acerca
  de" y "Tu modelo" siguen, la foto de portada del modelo va en la laguna y
  los accesos son los de siempre más Convenio y Listas (con su permiso).

Correr con: python -m pytest test_tema_laguna_panel_portada.py -q
"""
import os
import re

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import main
from db import Sindicato, UsuarioSindicato
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session

db.crear_tablas()

HOJA = "static/temas/laguna-panel-portada.css"
SUPER = "20314567898"

with db.get_session() as s:
    sind = Sindicato(nombre="Laguna Portada", slug="laguna-portada", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=SUPER, cuil=SUPER, nombre="Laura Méndez",
                           clave_hash=auth.hashear_clave("super"), es_super_admin=True))
    s.commit()


def _cliente(usuario=SUPER, clave="super"):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _css():
    with open(HOJA, encoding="utf-8") as f:
        return f.read()


def _sin_comentarios(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _reglas(css):
    """(selector, cuerpo) de cada regla, entrando en @media/@supports y
    salteando los @keyframes (sus 'from'/'to' no son selectores)."""
    css = _sin_comentarios(css)
    salida, i = [], 0
    while i < len(css):
        a = css.find("{", i)
        if a < 0:
            break
        sel = css[i:a].strip().rstrip(";").split(";")[-1].strip()
        prof, j = 1, a + 1
        while prof and j < len(css):
            prof += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        cuerpo = css[a + 1:j - 1]
        if sel.startswith("@keyframes"):
            pass
        elif sel.startswith("@"):
            salida += _reglas(cuerpo)
        else:
            salida.append((sel, cuerpo))
        i = j
    return salida


# ---------- La plantilla carga la hoja ----------

def test_carga_la_hoja_con_sello_solo_con_laguna():
    assert os.path.exists(HOJA)
    html = _cliente().get("/admin/inicio").text
    assert 'data-tema="laguna"' in html
    assert f"/static/temas/laguna-panel-portada.css?v={main._sello_static('temas/laguna-panel-portada.css')}" in html
    # La hoja va DESPUÉS de los estilos de la plantilla (si no, estos la pisan).
    assert html.index("laguna-panel-portada.css") > html.index("</style>")


def test_con_noticiero_no_carga_la_de_laguna_ni_una_que_no_existe():
    db.set_apariencia_sindicato(SID, tema_panel="noticiero")
    try:
        html = _cliente().get("/admin/inicio").text
        assert 'data-tema="noticiero"' in html
        assert "laguna-panel-portada.css" not in html
        hoja_noticiero = "static/temas/noticiero-panel-portada.css"
        assert ("noticiero-panel-portada.css" in html) == os.path.exists(hoja_noticiero)
    finally:
        db.set_apariencia_sindicato(SID, tema_panel="laguna")


# ---------- La hoja ----------

def test_todo_selector_empieza_con_el_modelo():
    afuera = []
    for sel, _ in _reglas(_css()):
        for parte in sel.split(","):
            if not parte.strip().startswith('html[data-tema="laguna"]'):
                afuera.append(parte.strip())
    assert not afuera, f"selectores que se salen del modelo: {afuera}"


def test_los_colores_salen_de_las_variables():
    """Hex sueltos solo en la declaración de la paleta; afuera, blanco puro."""
    sueltos = []
    for sel, cuerpo in _reglas(_css()):
        if sel.strip() == 'html[data-tema="laguna"]':
            continue                      # la paleta del modelo, declarada una vez
        for hexa in re.findall(r"#[0-9a-fA-F]{3,8}\b", cuerpo):
            if hexa.lower() not in ("#fff", "#ffffff"):
                sueltos.append((sel, hexa))
    assert not sueltos, sueltos


def test_la_paleta_del_sindicato_sale_de_la_marca():
    css = _sin_comentarios(_css())
    bloque = re.search(r'html\[data-tema="laguna"\]\[data-paleta="sindicato"\]\s*\{(.*?)\}', css, re.S).group(1)
    for var in ("--lg-azul", "--lg-turq", "--lg-lag", "--lg-fluor", "--lg-fluor-t", "--lg-agua-f"):
        assert re.search(re.escape(var) + r"\s*:", bloque), var
    assert "var(--marca-base)" in bloque and "var(--marca-acento)" in bloque
    assert "color-mix(in oklab" in bloque
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", bloque), "la paleta del sindicato no lleva colores fijos"


def test_sin_duraciones_propias_y_con_movimiento_reducido():
    css = _sin_comentarios(_css())
    assert not re.search(r"--(mov|ease)-[\w-]+\s*:", css), "las duraciones van en movimiento.css"
    assert "prefers-reduced-motion: reduce" in css
    # Toda animación o transición usa los tokens (salvo la respiración lenta
    # de la foto, que el mockup fija en 28 s y se apaga con movimiento reducido).
    for sel, cuerpo in _reglas(css):
        for decl in re.findall(r"(?:animation|transition)\s*:[^;]+", cuerpo):
            if "lg-adm-respira" in decl or decl.strip().endswith("none"):
                continue
            assert "var(--mov-" in decl, (sel, decl)


def test_la_seleccion_no_lleva_barra_al_costado():
    css = _sin_comentarios(_css())
    assert "border-left" not in css and "border-right" not in css
    # Un box-shadow inset con desplazamiento horizontal es una barra lateral.
    for m in re.finditer(r"inset\s+(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px", css):
        assert float(m.group(1)) == 0, m.group(0)


# ---------- Contraste ----------

def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminancia(rgb):
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a, b):
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _oklab(rgb):
    r, g, b = (_lin(c) for c in rgb)
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _desde_oklab(lab):
    L, a, b = lab
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def gam(c):
        c = min(max(c, 0), 1)
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return tuple(gam(c) for c in lin)


def _mezcla(a, b, peso_a):
    """color-mix(in oklab, a peso_a%, b)."""
    la, lb = _oklab(a), _oklab(b)
    return _desde_oklab(tuple(x * peso_a + y * (1 - peso_a) for x, y in zip(la, lb)))


BLANCO = (1.0, 1.0, 1.0)
GREMIOS = {
    "UOM": ("#0f2240", "#1a3d6b", "#e8b84b", "#2fa88f"),
    "La Bancaria": ("#132a4a", "#1d4e89", "#e8b84b", "#2f8f83"),
    "Gastronómica": ("#2a0d12", "#7a1f2b", "#3d6b4a", "#c19a3e"),
}


def test_contraste_con_la_paleta_del_modelo():
    css = _css()
    pal = {k: v for k, v in re.findall(r"--lg-([\w-]+):\s*(#[0-9a-fA-F]{6})", css)}
    azul, fluor = _rgb(pal["azul"]), _rgb(pal["fluor"])
    pares = {
        "saludo y textos sobre la laguna": (BLANCO, azul),
        "bajadas sobre la laguna": (_rgb(pal["agua-txt"]), azul),
        "el nombre resaltado y el botón": (azul, fluor),
        "título de una tarjeta": (azul, BLANCO),
        "bajada de una tarjeta": (_rgb(pal["azgris"]), BLANCO),
        "ícono de una tarjeta": (_rgb(pal["turq-osc"]), _rgb(pal["agua-f"])),
        "Tu modelo elegido": (BLANCO, _rgb(pal["turq"])),
        "filas del modal": (_rgb(pal["gris2"]), BLANCO),
    }
    for nombre, (texto, fondo) in pares.items():
        assert _contraste(texto, fondo) >= 4.5, (nombre, round(_contraste(texto, fondo), 2))


def test_contraste_con_los_colores_de_los_tres_gremios():
    """Las mismas mezclas que la hoja, con los colores de la demo."""
    for gremio, colores in GREMIOS.items():
        base, primario, acento, apoyo = (_rgb(c) for c in colores)
        # --lg-tinta-acento: blanco si el acento es oscuro (L oklab < 0,57), si no casi negro.
        l_acento = _oklab(acento)[0]
        tinta_acento = BLANCO if l_acento < 0.57 else _desde_oklab((0.12, 0, 0))
        agua_f = _mezcla(apoyo, BLANCO, 0.14)
        azgris = _mezcla(base, BLANCO, 0.78)
        turq_osc = _mezcla(primario, base, 0.75)
        agua_txt = _mezcla(apoyo, BLANCO, 0.16)
        pares = {
            "saludo sobre la laguna": (BLANCO, base),
            "bajadas sobre la laguna": (agua_txt, base),
            "texto sobre el acento": (tinta_acento, acento),
            "título de una tarjeta": (base, BLANCO),
            "bajada de una tarjeta": (azgris, BLANCO),
            "ícono de una tarjeta": (turq_osc, agua_f),
            "Tu modelo elegido": (BLANCO, primario),
            "Salir": (BLANCO, base),
        }
        for nombre, (texto, fondo) in pares.items():
            c = _contraste(texto, fondo)
            assert c >= 4.5, (gremio, nombre, round(c, 2))


# ---------- La página ----------

def test_salir_flota_con_su_rotulo_y_no_hay_inicio():
    html = _cliente().get("/admin/inicio").text
    flota = re.search(r'<nav class="pt-flota".*?</nav>', html, re.S).group(0)
    assert 'href="/admin/salir"' in flota and "<span>Salir</span>" in flota
    assert ">Inicio<" not in html


def test_conserva_tu_cuenta_tu_modelo_y_acerca_de():
    html = _cliente().get("/admin/inicio").text
    assert 'id="overlay-perfil"' in html and "Tu modelo" in html
    assert "elegirMiModelo(" in html
    assert 'onclick="abrirAcerca()"' in html and 'id="overlay-acerca"' in html
    assert "Hola, <em>Laura</em>" in html


def test_sin_foto_la_laguna_es_el_degrade_solo():
    html = _cliente().get("/admin/inicio").text
    media = re.search(r'<div class="pt-media".*?</div>', html, re.S).group(0)
    assert "<img" not in media


def test_con_foto_va_en_la_laguna_con_su_punto_de_interes():
    fid = db.crear_foto_tema("laguna", {"datos": b"RIFF-foto", "mime": "image/webp",
                                        "ancho": 1600, "alto": 1000},
                             descripcion="Planta", foco_x=0.62, foco_y=0.4)
    db.editar_foto_tema(fid, publicada=True)
    try:
        html = _cliente().get("/admin/inicio").text
        media = re.search(r'<div class="pt-media".*?</div>', html, re.S).group(0)
        assert f'src="/foto-tema/{fid}?v=' in media
        assert 'alt=""' in media and 'aria-hidden="true"' in media
        assert "object-position:62.0% 40.0%" in media
    finally:
        with Session(db.engine) as s:
            s.delete(s.get(db.FotoTema, fid)); s.commit()


def test_accesos_de_siempre_mas_convenio_y_listas():
    html = _cliente().get("/admin/inicio").text
    for panel in ("reportes", "formulas", "conceptos", "trabajadores", "aprendizaje", "noticias",
                  "beneficios", "notificaciones", "encuestas", "tramites", "empleadores",
                  "convenio", "seccionales", "listas", "administradores"):
        assert f'href="/admin#{panel}"' in html, panel
    assert 'href="/admin/dashboard"' in html
    # En cuatro grupos (SDN, 2026-10-23): Recibos, Afiliados, Comunicación y
    # El gremio, en ese orden.
    for grupo in ("Recibos", "Afiliados", "Comunicación", "El gremio"):
        assert f">{grupo}</h2>" in html, grupo
    assert html.index("/admin#reportes") < html.index("/admin#trabajadores") < html.index("/admin#listas") \
        < html.index("/admin#noticias") < html.index("/admin#convenio") < html.index("/admin#administradores")


def test_convenio_sigue_el_modulo():
    with Session(db.engine) as s:
        sind = s.get(Sindicato, SID)
        sind.modulos_habilitados = [m for m in MODULOS if m != "convenio"]
        s.add(sind); s.commit()
    try:
        html = _cliente().get("/admin/inicio").text
        assert 'href="/admin#convenio"' not in html
        assert 'href="/admin#listas"' in html          # Listas no depende de un módulo
    finally:
        with Session(db.engine) as s:
            sind = s.get(Sindicato, SID)
            sind.modulos_habilitados = list(MODULOS.keys())
            s.add(sind); s.commit()
