"""Los dos modelos de diseño en el panel de plataforma (PLAN_TEMAS.md,
llevado a plataforma el 2026-10-25).

Lo que se verifica:
- las tres páginas (/plataforma/inicio, /plataforma y /plataforma/usuarios)
  llevan `data-tema` y `data-paleta` en <html>, y la paleta es SIEMPRE la de
  Colm3na: plataforma no tiene sindicato;
- cada página carga la hoja de su modelo (static/temas/<modelo>-plataforma*.css)
  con sello, después de sus estilos, y nunca la del otro modelo;
- no está la trama de colmena (ni la retícula de la portada ni la mesa de
  las pantallas interiores);
- la elección del usuario se guarda en su fila (UsuarioPlataforma.tema) y se
  respeta en las tres páginas; un valor fuera del catálogo no se guarda; el
  genérico de transición no tiene dónde guardarla;
- el riel es la misma tira (los mismos data-pp, en su orden), con Usuarios
  como enlace solo para el superadmin, y Usuarios entró al sistema (mismo
  encabezado, mismo riel, mismos flotantes);
- Inicio y Salir flotan con su rótulo;
- las cuatro hojas respetan las reglas de los modelos.

Correr con: python -m pytest test_tema_plataforma.py -q
"""
import os
import re
from pathlib import Path

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import auth
import db
import main
import temas
from fastapi.testclient import TestClient

db.crear_tablas()

HOJAS = {(m, p): Path(f"static/temas/{m}-{p}.css")
         for m in temas.TEMAS for p in ("plataforma", "plataforma-portada")}
PAGINAS = {"/plataforma/inicio": "plataforma-portada", "/plataforma": "plataforma",
           "/plataforma/usuarios": "plataforma"}


def _usuario(nombre, rol="superadmin", tema=""):
    """Un usuario de plataforma con los datos ya completos (no lo manda a
    /plataforma/completar)."""
    with db.get_session() as s:
        u = s.exec(db.select(db.UsuarioPlataforma).where(db.UsuarioPlataforma.usuario == nombre)).first()
        if not u:
            u = db.UsuarioPlataforma(usuario=nombre, nombre="Prueba Modelo", rol=rol,
                                     clave_hash=auth.hashear_clave("x" * 12), activo=True,
                                     debe_cambiar_clave=False, debe_completar_datos=False,
                                     cuil="20310001113", email=f"{nombre}@colm3na.test")
        u.rol, u.tema = rol, tema
        s.add(u); s.commit(); s.refresh(u)
        return u.id


def _cliente(uid, usuario="x"):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_PLATAFORMA, auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    return c


def _tema_guardado(uid):
    with db.get_session() as s:
        return s.get(db.UsuarioPlataforma, uid).tema


def _sin_comentarios(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ---------------------------------------------------------------- las páginas

def test_las_tres_paginas_llevan_modelo_y_paleta_de_colm3na():
    uid = _usuario("tema-plat-1")
    c = _cliente(uid, "tema-plat-1")
    for ruta in PAGINAS:
        html = c.get(ruta).text
        assert '<html lang="es" data-tema="laguna" data-paleta="colm3na">' in html, ruta


def test_cada_pagina_carga_la_hoja_de_su_modelo_con_sello():
    uid = _usuario("tema-plat-2")
    c = _cliente(uid, "tema-plat-2")
    for modelo in temas.TEMAS:
        _usuario("tema-plat-2", tema=modelo)
        for ruta, pantalla in PAGINAS.items():
            html = c.get(ruta).text
            hoja = f"temas/{modelo}-{pantalla}.css"
            sello = main._sello_static(hoja)
            assert sello, f"falta la hoja {hoja}"
            assert f'href="/static/{hoja}?v={sello}"' in html, (ruta, modelo)
            # después de los estilos de la plantilla, para poder pisarlos
            assert html.index(f"/static/{hoja}?v=") > html.index("</style>"), (ruta, modelo)
            # nunca la del otro modelo
            for otro in temas.TEMAS:
                if otro != modelo:
                    assert f"temas/{otro}-" not in html, (ruta, modelo, otro)


def test_sin_la_trama_de_colmena():
    uid = _usuario("tema-plat-3")
    c = _cliente(uid, "tema-plat-3")
    for ruta in PAGINAS:
        html = c.get(ruta).text
        assert "pt-reticula" not in html and "pt-ambiente" not in html, ruta
        assert "interior.css" not in html, ruta                    # la mesa con la retícula
        assert not re.search(r'<body[^>]*class="[^"]*\bmesa\b', html), ruta
    for hoja in HOJAS.values():
        assert "M28 1 55 16.5" not in hoja.read_text(encoding="utf-8")   # el hexágono


def test_la_eleccion_se_guarda_y_se_respeta():
    uid = _usuario("tema-plat-4")
    c = _cliente(uid, "tema-plat-4")
    r = c.post("/plataforma/apariencia/mia", data={"tema": "noticiero"})
    assert r.status_code == 200 and r.json() == {"ok": True, "tema": "noticiero"}
    assert _tema_guardado(uid) == "noticiero"
    for ruta in PAGINAS:
        assert 'data-tema="noticiero"' in c.get(ruta).text, ruta
    # en la portada, la opción elegida se pinta entera
    portada = c.get("/plataforma/inicio").text
    assert re.search(r'class="tm-op activa"[^>]*onclick="elegirMiModelo\(\'noticiero\'\)"', portada)
    # "" vuelve al por defecto
    assert c.post("/plataforma/apariencia/mia", data={"tema": ""}).status_code == 200
    assert _tema_guardado(uid) == ""
    assert 'data-tema="laguna"' in c.get("/plataforma").text


def test_un_valor_fuera_del_catalogo_no_se_guarda():
    uid = _usuario("tema-plat-5", tema="noticiero")
    c = _cliente(uid, "tema-plat-5")
    for malo in ("rosa-chicle", "LAGUNA ' or 1=1", "x" * 80):
        assert c.post("/plataforma/apariencia/mia", data={"tema": malo}).status_code == 400
        assert _tema_guardado(uid) == "noticiero"
    # un valor viejo o mal escrito que ya esté en la base vale el por defecto
    _usuario("tema-plat-5", tema="rosa-chicle")
    assert db.apariencia_plataforma(uid)["tema"] == temas.TEMA_DEFECTO
    assert 'data-tema="laguna"' in c.get("/plataforma").text


def test_sin_sesion_o_generico_no_se_guarda():
    assert TestClient(main.app).post("/plataforma/apariencia/mia", data={"tema": "noticiero"}).status_code == 403
    generico = _cliente(0, "")
    assert generico.post("/plataforma/apariencia/mia", data={"tema": "noticiero"}).status_code == 400
    html = generico.get("/plataforma/inicio").text
    assert 'data-tema="laguna"' in html and "elegirMiModelo('noticiero')" not in html


def test_el_selector_tu_modelo_esta_en_la_portada():
    uid = _usuario("tema-plat-6")
    html = _cliente(uid, "tema-plat-6").get("/plataforma/inicio").text
    assert 'id="overlay-perfil"' in html and "Tu modelo" in html
    for clave in temas.TEMAS:
        assert f"elegirMiModelo('{clave}')" in html
    assert "fetch('/plataforma/apariencia/mia'" in html


# ---------------------------------------------------------------- el riel

def test_el_riel_es_la_misma_tira_y_usuarios_solo_para_superadmin():
    orden = ["lista", "nuevo", "admin", "clave", "marca", "fotos", "config", "usoia", "sospechosos", "topes"]
    sup = _cliente(_usuario("tema-plat-7"), "tema-plat-7")
    html = sup.get("/plataforma").text
    tira = html[html.index('<nav class="nav-strip"'):html.index("</nav>")]
    assert re.findall(r'class="ptab[^"]*" data-pp="([a-z]+)"', tira) == orden
    assert 'href="/plataforma/usuarios"' in tira
    # el JS de las pestañas solo engancha las que cambian de pestaña
    assert "document.querySelectorAll('.ptab[data-pp]').forEach" in html
    admin = _cliente(_usuario("tema-plat-8", rol="admin"), "tema-plat-8")
    tira = admin.get("/plataforma").text
    tira = tira[tira.index('<nav class="nav-strip"'):tira.index("</nav>")]
    assert "/plataforma/usuarios" not in tira


def test_usuarios_entro_al_sistema():
    html = _cliente(_usuario("tema-plat-9"), "tema-plat-9").get("/plataforma/usuarios").text
    assert 'class="marca-enc' in html                       # el encabezado común
    tira = html[html.index('<nav class="nav-strip"'):html.index("</nav>")]
    assert re.search(r'class="ptab ptab-pagina activa" href="/plataforma/usuarios" aria-current="page"', tira)
    assert 'href="/plataforma#topes"' in tira               # las demás secciones, como enlaces
    assert 'class="titulo-pagina">Usuarios de plataforma' in html
    # la jerga interna no llega a la pantalla
    with db.get_session() as s:
        u = s.exec(db.select(db.UsuarioPlataforma).where(db.UsuarioPlataforma.usuario == "tema-plat-9")).first()
        u.creado_por, u.creado_en = "semilla", "2026-10-23 16:06"
        s.add(u); s.commit()
        uid = u.id
    html = _cliente(uid, "tema-plat-9").get("/plataforma/usuarios").text
    assert "Alta inicial<br>23/10/2026 16:06" in html and "semilla" not in html


def test_inicio_y_salir_flotan_con_rotulo():
    c = _cliente(_usuario("tema-plat-10"), "tema-plat-10")
    for ruta in ("/plataforma", "/plataforma/usuarios"):
        html = c.get(ruta).text
        flota = html[html.index('<div class="flota-sesion">'):]
        flota = flota[:flota.index("</div>")]
        assert re.search(r'<a class="btn-home" href="/plataforma/inicio"[^>]*>.*?<span class="btn-rot">Inicio</span>', flota, re.S)
        assert re.search(r'<a class="btn-cerrar" href="/plataforma/salir"[^>]*>.*?<span class="btn-rot">Salir</span>', flota, re.S)
        assert f"flota.js?v={main._sello_static('flota.js')}" in html
    portada = c.get("/plataforma/inicio").text
    assert re.search(r'<a class="pt-salir" href="/plataforma/salir"[^>]*>.*?<span>Salir</span>', portada, re.S)
    assert 'href="/plataforma/inicio"' not in portada.split('class="pt-flota"')[1]   # en la portada no va Inicio


# ---------------------------------------------------------------- las hojas

def _selectores(css):
    css = _sin_comentarios(css)
    css = re.sub(r"@font-face\s*\{[^}]*\}", "", css)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
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


def test_las_hojas_respetan_las_reglas_de_los_modelos():
    for (modelo, pantalla), hoja in HOJAS.items():
        css = hoja.read_text(encoding="utf-8")
        limpio = _sin_comentarios(css)
        prefijo = f'html[data-tema="{modelo}"]'
        malos = [s for s in _selectores(css) if not s.startswith(prefijo) and s not in ("from", "to")]
        assert not malos, (hoja, malos[:5])
        # los colores salen de variables (hex solo al declararlas)
        for linea in limpio.splitlines():
            decl = linea.strip()
            if decl.startswith("--") or "data:image" in decl:
                continue
            for hexa in re.findall(r"#[0-9a-fA-F]{3,8}\b", decl):
                assert hexa.lower() in ("#fff", "#ffffff"), (hoja, decl)
        # las duraciones viven en movimiento.css, y se respeta "menos movimiento"
        assert not re.search(r"--(mov|ease)-[\w-]+\s*:", limpio), hoja
        assert "prefers-reduced-motion: reduce" in limpio, hoja
        # plataforma no tiene sindicato: no hay paleta del sindicato
        assert 'data-paleta="sindicato"' not in limpio, hoja


def test_ninguna_seleccion_con_barra_al_costado():
    for (modelo, pantalla), hoja in HOJAS.items():
        css = _sin_comentarios(hoja.read_text(encoding="utf-8"))
        # un borde izquierdo solo puede ser 0 o el filete fino y neutro que
        # separa columnas en el índice de Noticiero (no marca nada elegido)
        for m in re.finditer(r"border-left\s*:\s*([^;}]+)", css):
            valor = m.group(1).strip()
            assert valor in ("0", "none") or re.fullmatch(r"1px solid var\(--(nt|lg)-linea\)", valor), (hoja, m.group(0))
        for sel, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            for m in re.finditer(r"inset\s+(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px", cuerpo):
                if float(m.group(1)) != 0:
                    # la única excepción: el filete coral del encabezado de
                    # Noticiero, que es la firma del modelo y no una selección
                    assert modelo == "noticiero" and ".marca-barra" in sel, (hoja, sel.strip(), m.group(0))


def test_lo_elegido_va_en_un_solo_color():
    """Pestaña activa del riel y sub-pestañas de Uso de IA y Fotos: el mismo
    relleno (antes eran tres colores para "esto está elegido")."""
    for modelo, color in (("laguna", "var(--lg-azul)"), ("noticiero", "var(--nt-indigo)")):
        css = _sin_comentarios(HOJAS[(modelo, "plataforma")].read_text(encoding="utf-8"))
        activa = re.search(r'html\[data-tema="%s"\] \.ptab\.activa \{([^}]*)\}' % modelo, css).group(1)
        assert f"background: {color}" in activa
        sub = re.search(r'html\[data-tema="%s"\] :is\(\.ia-subtab, \.ft-subtab\)\.activa \{([^}]*)\}' % modelo, css).group(1)
        assert f"background: {color}" in sub


def test_el_riel_es_fijo_en_escritorio_y_tira_en_telefono():
    for modelo, var in (("laguna", "--lg-riel"), ("noticiero", "--nt-riel")):
        css = _sin_comentarios(HOJAS[(modelo, "plataforma")].read_text(encoding="utf-8"))
        escritorio = css[css.index("@media (min-width: 761px)"):]
        nav = re.search(r"\.nav-strip \{([^}]*)\}", escritorio).group(1)
        assert "position: fixed" in nav and "flex-direction: column" in nav
        assert f"margin: 0 0 0 var({var})" in escritorio
        telefono = css[css.index("@media (max-width: 760px)"):]
        assert "position: fixed" not in re.search(r"\.nav-strip \{([^}]*)\}", telefono).group(1)
