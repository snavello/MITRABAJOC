"""El modelo Noticiero en la portada del panel del sindicato (PLAN_TEMAS.md,
bloque 6; mockup: figura E1 de p147-escritorio.html).

Lo que se verifica:
- la plantilla carga `static/temas/noticiero-panel-portada.css` CON sello,
  solo con el modelo Noticiero, después de sus estilos, y no carga la de
  Laguna;
- la hoja no se sale de su modelo (todo selector empieza con
  html[data-tema="noticiero"]), declara sus dos fuentes vendoreadas (Anton y
  Archivo) y no carga nada de afuera, saca los colores de sus variables, no
  define duraciones propias, respeta "reducir movimiento" y no marca la
  opción elegida con una barra de color al costado (D6);
- los colores del modelo y los derivados de los tres gremios de la demo se
  leen (≥ 4,5:1 el texto);
- lo que la portada tenía sigue: Salir flota con su rótulo, no hay Inicio,
  "Acerca de", "Tu cuenta" y "Tu modelo" siguen, la foto de portada va en la
  tapa con su punto de interés y los accesos son los de siempre.

Correr con: python -m pytest test_tema_noticiero_panel_portada.py -q
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

HOJA = "static/temas/noticiero-panel-portada.css"
MODELO = 'html[data-tema="noticiero"]'
SUPER = "20314567898"

with db.get_session() as s:
    sind = Sindicato(nombre="Noticiero Portada", slug="noticiero-portada", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=list(MODULOS.keys()), tema_panel="noticiero")
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
    salteando @keyframes y @font-face (no tienen selectores)."""
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
        if sel.startswith("@keyframes") or sel.startswith("@font-face"):
            pass
        elif sel.startswith("@"):
            salida += _reglas(cuerpo)
        else:
            salida.append((sel, cuerpo))
        i = j
    return salida


# ---------- La plantilla carga la hoja ----------

def test_carga_la_hoja_con_sello_solo_con_noticiero():
    assert os.path.exists(HOJA)
    html = _cliente().get("/admin/inicio").text
    assert 'data-tema="noticiero"' in html
    sello = main._sello_static("temas/noticiero-panel-portada.css")
    assert sello
    assert f"/static/temas/noticiero-panel-portada.css?v={sello}" in html
    assert "laguna-panel-portada.css" not in html
    # Después de los estilos de la plantilla (si no, estos la pisan).
    assert html.index("noticiero-panel-portada.css") > html.index("</style>")


def test_con_laguna_no_carga_la_de_noticiero():
    db.set_apariencia_sindicato(SID, tema_panel="laguna")
    try:
        html = _cliente().get("/admin/inicio").text
        assert 'data-tema="laguna"' in html
        assert "noticiero-panel-portada.css" not in html
    finally:
        db.set_apariencia_sindicato(SID, tema_panel="noticiero")


def test_la_paleta_del_sindicato_llega_a_la_pagina():
    db.set_apariencia_sindicato(SID, paleta="sindicato")
    try:
        html = _cliente().get("/admin/inicio").text
        assert 'data-paleta="sindicato"' in html
        assert "--marca-acento: #e8b84b" in html
    finally:
        db.set_apariencia_sindicato(SID, paleta="colm3na")


# ---------- La hoja ----------

def test_todo_selector_empieza_con_el_modelo():
    afuera = []
    for sel, _ in _reglas(_css()):
        for parte in sel.split(","):
            if not parte.strip().startswith(MODELO):
                afuera.append(parte.strip())
    assert not afuera, f"selectores que se salen del modelo: {afuera}"


def test_fuentes_vendoreadas_y_nada_de_afuera():
    css = _sin_comentarios(_css())
    caras = re.findall(r"@font-face\s*\{(.*?)\}", css, re.S)
    familias = {re.search(r'font-family:\s*"([^"]+)"', c).group(1): c for c in caras}
    assert set(familias) == {"Anton", "Archivo"}
    assert 'url("/static/fonts/anton.woff2")' in familias["Anton"]
    assert 'url("/static/fonts/archivo.woff2")' in familias["Archivo"]
    assert "font-weight: 100 900" in familias["Archivo"] and "font-stretch: 62% 125%" in familias["Archivo"]
    for f in ("static/fonts/anton.woff2", "static/fonts/archivo.woff2"):
        assert os.path.exists(f), f
    # La CSP no deja cargar nada de otro origen: ninguna URL absoluta.
    assert not re.search(r"url\(\s*[\"']?(https?:)?//", css)
    assert "@import" not in css


def test_los_colores_salen_de_las_variables():
    """Hex sueltos solo en la declaración de la paleta; afuera, blanco puro
    (el número del globo, color de estado)."""
    sueltos = []
    for sel, cuerpo in _reglas(_css()):
        if sel.strip() == MODELO:
            continue                      # la paleta del modelo, declarada una vez
        for hexa in re.findall(r"#[0-9a-fA-F]{3,8}\b", cuerpo):
            if hexa.lower() not in ("#fff", "#ffffff"):
                sueltos.append((sel, hexa))
    assert not sueltos, sueltos


def test_la_paleta_del_sindicato_sale_de_la_marca():
    css = _sin_comentarios(_css())
    bloque = re.search(r'html\[data-tema="noticiero"\]\[data-paleta="sindicato"\]\s*\{(.*?)\}', css, re.S).group(1)
    for var in ("--nt-fondo", "--nt-carta", "--nt-tinta", "--nt-indigo", "--nt-indigo-2", "--nt-marfil",
                "--nt-coral", "--nt-coral-tinta", "--nt-coral-osc", "--nt-resaltador"):
        assert re.search(re.escape(var) + r"\s*:", bloque), var
    for marca in ("--marca-base", "--marca-primario", "--marca-acento"):
        assert f"var({marca})" in bloque, marca
    assert "color-mix(in oklab" in bloque
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", bloque), "la paleta del sindicato no lleva colores fijos"
    # El rojo del globo es un estado: no lo toca la paleta.
    assert "--nt-mal" not in bloque


def test_sin_duraciones_propias_y_con_movimiento_reducido():
    css = _sin_comentarios(_css())
    assert not re.search(r"--(mov|ease)-[\w-]+\s*:", css), "las duraciones van en movimiento.css"
    assert "prefers-reduced-motion: reduce" in css
    # Toda animación o transición usa los tokens (salvo el zoom lento de la
    # foto, 24 s como en el mockup, que se apaga con movimiento reducido).
    for sel, cuerpo in _reglas(css):
        for decl in re.findall(r"(?:animation|transition)\s*:[^;]+", cuerpo):
            if "nt-adm-zoom" in decl or decl.strip().endswith("none"):
                continue
            assert "var(--mov-" in decl, (sel, decl)
    reducido = css[css.index("prefers-reduced-motion: reduce"):]
    assert ".pt-media img { animation: none" in reducido


def test_la_seleccion_no_lleva_barra_al_costado():
    """La opción elegida de "Tu modelo" se pinta entera (D6)."""
    for sel, cuerpo in _reglas(_css()):
        if ".activa" not in sel and "aria-checked" not in sel:
            continue
        assert "border-left" not in cuerpo and "border-right" not in cuerpo, sel
        for m in re.finditer(r"inset\s+(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px", cuerpo):
            assert float(m.group(1)) == 0, (sel, m.group(0))
        assert re.search(r"background:\s*var\(--nt-indigo\)", cuerpo), sel


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
# Los gremios de la demo (cargar_demo.py y cargar_bancaria.py). Gastronómica
# va dos veces: con la base por defecto que le deja cargar_demo y con la
# bordó de los mockups.
GREMIOS = {
    "UOM": ("#0f1b2d", "#1a3d6b", "#e8b84b", "#2fa88f"),
    "La Bancaria": ("#132a4a", "#1d4e89", "#e8b84b", "#2f8f83"),
    "Gastronómica": ("#0f1b2d", "#7a1f2b", "#3d6b4a", "#c19a3e"),
    "Gastronómica bordó": ("#2a0d12", "#7a1f2b", "#3d6b4a", "#c19a3e"),
}


def _paleta_modelo():
    return {k: v for k, v in re.findall(r"--nt-([\w-]+):\s*(#[0-9a-fA-F]{6})", _css())}


def _pares(p):
    """Los textos de la portada y su fondo, con los nombres de la hoja."""
    return {
        "saludo y títulos sobre el papel": (p["tinta"], p["fondo"]),
        "rol bajo el saludo": (p["tinta-1"], p["fondo"]),
        "bajada de una celda": (p["tinta-2"], p["fondo"]),
        "«Acerca de»": (p["tinta-3"], p["fondo"]),
        "bajada de «Lo primero»": (p["tinta-1"], p["carta"]),
        "bajada de una celda al pasar el mouse": (p["tinta-2"], p["carta"]),
        "el nombre sobre el resaltador": (p["tinta"], p["resaltador"]),
        "«Nuevo» y «Abrir el panel»": (p["coral-tinta"], p["coral"]),
        "«Lo primero», Salir y el modal": (p["marfil"], p["indigo"]),
        "Salir al pasar el mouse": (p["marfil"], p["indigo-2"]),
        "Tu modelo elegido": (p["marfil"], p["indigo"]),
        "filas del modal": (p["tinta-2"], p["fondo"]),
    }


def test_contraste_con_la_paleta_del_modelo():
    pal = {k: _rgb(v) for k, v in _paleta_modelo().items()}
    p = {k: pal["k-" + k] if "k-" + k in pal else pal.get(k) for k in
         ("fondo", "carta", "tinta", "tinta-1", "tinta-2", "tinta-3", "indigo", "indigo-2",
          "marfil", "coral", "coral-tinta")}
    p["resaltador"] = p["coral"]
    for nombre, (texto, fondo) in _pares(p).items():
        assert texto and fondo, nombre
        assert _contraste(texto, fondo) >= 4.5, (nombre, round(_contraste(texto, fondo), 2))
    # El globo: blanco sobre el rojo de estado.
    assert _contraste(BLANCO, pal["mal"]) >= 4.5


def test_contraste_con_los_colores_de_los_tres_gremios():
    """Las mismas mezclas que la hoja, con los colores de la demo."""
    pal = {k: _rgb(v) for k, v in _paleta_modelo().items()}
    for gremio, colores in GREMIOS.items():
        base, primario, acento, _apoyo = (_rgb(c) for c in colores)
        fondo = _mezcla(base, pal["k-fondo"], 0.05)
        carta = _mezcla(base, pal["k-carta"], 0.03)
        # --nt-tinta-acento: blanco si el acento es oscuro (L oklab < 0,57), si no casi negro.
        tinta_acento = BLANCO if _oklab(acento)[0] < 0.57 else _desde_oklab((0.12, 0, 0))
        p = {
            "fondo": fondo, "carta": carta, "tinta": base,
            "tinta-1": _mezcla(base, fondo, 0.88), "tinta-2": _mezcla(base, fondo, 0.80),
            "tinta-3": _mezcla(base, fondo, 0.72), "indigo": base, "indigo-2": primario,
            "marfil": _mezcla(base, pal["k-fondo"], 0.04), "coral": acento, "coral-tinta": tinta_acento,
            "resaltador": _mezcla(acento, carta, 0.45),
        }
        for nombre, (texto, fondo_) in _pares(p).items():
            c = _contraste(texto, fondo_)
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
    assert 'class="circulo-acento" onclick="abrirPerfil()"' in html
    # Las clases que la hoja viste siguen en la plantilla.
    for clase in ("pt-heroe", "pt-media", "fila-hola", "pt-hola-baj", "pt-hero pt-hero-chico", "pt-hero-k",
                  "pt-hero-t", "pt-hero-e", "pt-hero-cta", "pt-hero-ico", "pt-filas pt-tres", "pt-fila pt-vid",
                  "pt-pastilla", "pt-fila-t", "pt-fila-e", "pt-fila-f", "pt-pie", "pt-flota", "pt-salir"):
        assert f'class="{clase}' in html, clase


def test_sin_foto_la_tapa_es_papel():
    html = _cliente().get("/admin/inicio").text
    media = re.search(r'<div class="pt-media".*?</div>', html, re.S).group(0)
    assert "<img" not in media
    # La hoja prevé ese caso: sin foto no hay duotono (que oscurecería el papel).
    assert '.pt-media:not(:has(img))' in _css()


def test_con_foto_va_en_la_tapa_con_su_punto_de_interes():
    fid = db.crear_foto_tema("noticiero", {"datos": b"RIFF-foto", "mime": "image/webp",
                                           "ancho": 1600, "alto": 1000},
                             descripcion="Taller", foco_x=0.3, foco_y=0.55)
    db.editar_foto_tema(fid, publicada=True)
    try:
        html = _cliente().get("/admin/inicio").text
        media = re.search(r'<div class="pt-media".*?</div>', html, re.S).group(0)
        assert f'src="/foto-tema/{fid}?v=' in media
        assert 'alt=""' in media and 'aria-hidden="true"' in media
        assert "object-position:30.0% 55.0%" in media
    finally:
        with Session(db.engine) as s:
            s.delete(s.get(db.FotoTema, fid)); s.commit()


def test_accesos_de_siempre():
    html = _cliente().get("/admin/inicio").text
    for panel in ("reportes", "formulas", "conceptos", "trabajadores", "aprendizaje", "noticias",
                  "beneficios", "notificaciones", "encuestas", "tramites", "empleadores",
                  "convenio", "seccionales", "listas", "administradores"):
        assert f'href="/admin#{panel}"' in html, panel
    assert 'href="/admin/dashboard"' in html
    # Áreas y Usuarios va a lo ancho: tiene que seguir siendo el último acceso
    # (si no, dejaría un hueco en el medio del índice).
    assert html.index('href="/admin#administradores"') > html.index('href="/admin#listas"')
