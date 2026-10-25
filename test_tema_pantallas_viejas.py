"""Las tres pantallas que habían quedado con el diseño viejo, pasadas a los
dos modelos (PLAN_TEMAS.md): la bandeja de notificaciones y las consultas
sobre el convenio del afiliado, y los resultados de una encuesta del panel.

Lo que se verifica:
- cada pantalla marca el <html> con data-tema y data-paleta de la persona
  (el afiliado con su modelo de la app, el operador con el del panel);
- carga static/temas/<modelo>-<pantalla>.css con su sello ?v=, después de
  sus propios estilos, y solo la del modelo elegido;
- las hojas respetan las reglas de los modelos: todo selector acotado a su
  modelo, la paleta del sindicato derivada de la marca y la trama de colmena
  apagada (body.mesa::before en display:none);
- el título de cada pantalla lleva la clase titulo-pagina;
- las notificaciones del afiliado salen ordenadas por FECHA de envío, no
  por id (la línea de tiempo saltaba para atrás y para adelante).

Correr con: python -m pytest test_tema_pantallas_viejas.py -q
"""
import os
import re
from pathlib import Path

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import auth
import db
import main
from db import (CuentaTrabajador, Notificacion, NotificacionDestinatario, Sindicato,
                Trabajador, UsuarioSindicato)
from fastapi.testclient import TestClient

db.crear_tablas()

AFILIADO = "20391122334"
OPERADOR = "20413344556"
MODELOS = ("laguna", "noticiero")
PANTALLAS = ("notificaciones", "convenio", "encuesta-resultados")

with db.get_session() as s:
    sind = Sindicato(nombre="Pantallas Viejas", slug="pantallas-viejas", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=["notificaciones", "convenio", "tramites", "encuestas"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(CuentaTrabajador(cuil=AFILIADO, nombre="Ana Pérez", clave_hash=auth.hashear_clave("x")))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO, registrado=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=OPERADOR, nombre="Laura Méndez",
                           clave_hash=auth.hashear_clave("clave-op"), es_super_admin=True))
    # Tres avisos dados de alta en un orden que NO es el de su fecha de envío
    # (como un aviso programado o cargado con fecha).
    ids = {}
    for texto, enviado in (("del medio", "2026-09-01 09:51"), ("el más nuevo", "2026-09-29 10:24"),
                           ("el más viejo", "2026-08-06 10:56"), ("mismo minuto", "2026-09-01 09:51")):
        n = Notificacion(sindicato_id=SID, remitente="Secretaría Gremial", texto=texto, enviado_en=enviado)
        s.add(n); s.commit(); s.refresh(n)
        s.add(NotificacionDestinatario(notificacion_id=n.id, cuil=AFILIADO))
        ids[texto] = n.id
    s.commit()
    UID = s.exec(db.select(UsuarioSindicato).where(UsuarioSindicato.usuario == OPERADOR)).first().id

EID = db.crear_encuesta(SID, UID, None, {"titulo": "Clima laboral", "modo": "anonima",
                                         "fecha_desde": "2026-10-01", "fecha_hasta": "2026-10-31"},
                        [{"etiqueta": "¿Cómo estás?", "tipo_dato": "escala", "obligatorio": True,
                          "opciones": [], "escala_min": 1, "escala_max": 5}])


def _afiliado(tema):
    assert db.guardar_tema_persona(AFILIADO, tema, "afiliado")
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=AFILIADO))
    return c


def _operador(tema):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": OPERADOR, "clave": "clave-op"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert c.post("/admin/apariencia/mia", data={"tema": tema}).status_code == 200
    return c


def _pagina(pantalla, tema):
    if pantalla == "notificaciones":
        r = _afiliado(tema).get("/app/notificaciones")
    elif pantalla == "convenio":
        r = _afiliado(tema).get("/app/convenio")
    else:
        r = _operador(tema).get(f"/admin/encuesta/{EID}/resultados")
    assert r.status_code == 200, r.text
    return r.text


# ---------------------------------------------------------------- las páginas

def test_cada_pantalla_carga_la_hoja_de_su_modelo_con_sello():
    for pantalla in PANTALLAS:
        for tema in MODELOS:
            html = _pagina(pantalla, tema)
            assert f'data-tema="{tema}"' in html, (pantalla, tema)
            assert 'data-paleta="colm3na"' in html, (pantalla, tema)
            hoja = f"temas/{tema}-{pantalla}.css"
            sello = main._sello_static(hoja)
            assert sello, f"falta la hoja {hoja}"
            assert f'href="/static/{hoja}?v={sello}"' in html, (pantalla, tema)
            # después de los estilos propios de la plantilla, para pisarlos
            assert html.index("</style>") < html.index(f"/static/{hoja}?v=") < html.index("</head>")
            otro = [m for m in MODELOS if m != tema][0]
            assert f"{otro}-{pantalla}.css" not in html, (pantalla, tema)


def test_la_paleta_del_sindicato_llega_a_las_tres_pantallas():
    with db.get_session() as s:
        sind = s.get(Sindicato, SID)
        sind.paleta_tema = "sindicato"
        s.add(sind); s.commit()
    try:
        for pantalla in PANTALLAS:
            html = _pagina(pantalla, "laguna")
            assert 'data-paleta="sindicato"' in html, pantalla
            # los derivados legibles (temas.paleta_legible), como en /app y /admin
            assert "-tinta-acento:" in html and "-acento-txt:" in html, pantalla
    finally:
        with db.get_session() as s:
            sind = s.get(Sindicato, SID)
            sind.paleta_tema = "colm3na"
            s.add(sind); s.commit()


def test_cada_pantalla_tiene_su_titulo():
    assert re.search(r'<h1 class="titulo-pagina">Notificaciones</h1>', _pagina("notificaciones", "laguna"))
    assert re.search(r'<h1 class="titulo-pagina">Tu convenio</h1>', _pagina("convenio", "laguna"))
    html = _pagina("encuesta-resultados", "laguna")
    assert re.search(r'<h1 class="titulo-pagina" id="enc-titulo">Clima laboral</h1>', html)
    assert "titulo-encuesta" not in html


def test_el_convenio_vacio_explica_y_ofrece_una_salida():
    html = _pagina("convenio", "noticiero")
    assert "Todavía no está tu convenio" in html
    assert 'href="/app?tab=tramites"' in html


def test_los_resultados_usan_la_pastilla_de_sesion_del_panel():
    html = _pagina("encuesta-resultados", "noticiero")
    # Inicio y Salir con su rótulo a la vista, no dos círculos con un ícono
    assert 'class="flota-sesion"' in html
    assert ">Inicio</span>" in html and ">Salir</span>" in html
    assert "btn-flotante" not in html
    # todo lo de /static con sello, también Chart.js
    assert re.search(r'/static/chart\.umd\.min\.js\?v=[0-9a-f]', html)
    assert "/static/flota.js?v=" in html


# ---------------------------------------------------------------- las hojas

def _partir(lista):
    partes, nivel, actual = [], 0, ""
    for ch in lista:
        nivel += (ch == "(") - (ch == ")")
        if ch == "," and nivel == 0:
            partes.append(actual); actual = ""
        else:
            actual += ch
    return partes + [actual]


def _selectores(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    css = re.sub(r"@font-face\s*\{[^{}]*\}", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    for bloque in re.findall(r"([^{}]+)\{[^{}]*\}", css):
        for sel in _partir(bloque):
            if sel.strip():
                yield sel.strip()


def test_las_hojas_estan_acotadas_a_su_modelo():
    for tema in MODELOS:
        for pantalla in PANTALLAS:
            css = Path(f"static/temas/{tema}-{pantalla}.css").read_text(encoding="utf-8")
            sueltos = [x for x in _selectores(css) if not x.startswith(f'html[data-tema="{tema}"]')]
            assert not sueltos, (tema, pantalla, sueltos[:5])
            assert f'html[data-tema="{tema}"][data-paleta="sindicato"]' in css, (tema, pantalla)
            assert "prefers-reduced-motion" in css, (tema, pantalla)


def test_las_hojas_apagan_la_trama_de_colmena():
    """La retícula de colmena (body.mesa::before) y la franja oscura son el
    diseño viejo: las pantallas migradas no las llevan."""
    for tema in MODELOS:
        for pantalla in PANTALLAS:
            css = re.sub(r"/\*.*?\*/", "", Path(f"static/temas/{tema}-{pantalla}.css").read_text(encoding="utf-8"),
                         flags=re.S)
            m = re.search(rf'html\[data-tema="{tema}"\] body\.mesa::before,\s*'
                          rf'html\[data-tema="{tema}"\] body\.mesa\.franja::after\s*\{{\s*display:\s*none;', css)
            assert m, (tema, pantalla)


def test_las_plantillas_no_dibujan_su_propia_trama():
    """Ni la colmena del hito ni el grano de la franja oscura que tenía la
    bandeja, ni la trama de puntos de los filtros de la encuesta."""
    for plantilla in ("notificaciones.html", "convenio.html", "encuesta_resultados.html"):
        txt = Path("templates", plantilla).read_text(encoding="utf-8")
        assert "feTurbulence" not in txt, plantilla
        assert 'id="i-hex"' not in txt, plantilla
        assert "radial-gradient(" not in txt, plantilla


def test_los_avatares_solo_usan_colores_de_la_marca():
    txt = Path("templates/notificaciones.html").read_text(encoding="utf-8")
    m = re.search(r"const COLORES_AVATAR = \[([^\]]*)\]", txt)
    assert m
    assert not re.search(r"#[0-9a-fA-F]{3,6}", m.group(1)), "un avatar con un color fijo, fuera de la marca"


# ---------------------------------------------------------------- el orden

def test_las_notificaciones_salen_por_fecha_de_envio():
    notifs = db.notificaciones_de_trabajador(AFILIADO, SID)
    fechas_ = [n["enviado_en"] for n in notifs]
    assert fechas_ == sorted(fechas_, reverse=True), fechas_
    assert notifs[0]["texto"] == "el más nuevo"
    assert notifs[-1]["texto"] == "el más viejo"
    # dos del mismo minuto: primero la que se dio de alta después
    del_minuto = [n["id"] for n in notifs if n["enviado_en"] == "2026-09-01 09:51"]
    assert del_minuto == sorted(del_minuto, reverse=True)


def test_la_api_de_la_bandeja_respeta_el_orden():
    r = _afiliado("laguna").get("/api/mis-notificaciones")
    assert r.status_code == 200
    fechas_ = [n["enviado_en"] for n in r.json()["notificaciones"]]
    assert fechas_ == sorted(fechas_, reverse=True)


def test_la_bandeja_recibe_el_hoy_del_servidor():
    """Hoy y Ayer de la línea de tiempo salen de la hora de Buenos Aires
    (fechas.py), no del reloj del teléfono."""
    import fechas
    html = _pagina("notificaciones", "laguna")
    assert f'data-hoy="{fechas.hoy_texto()}"' in html


# ---------------------------------------------------------------- segunda auditoría

def _sin_coment(txt):
    return re.sub(r"/\*.*?\*/", "", txt, flags=re.S)


def _leer(ruta):
    return Path(ruta).read_text(encoding="utf-8")


def test_r4_05_el_historial_se_apila_en_el_telefono():
    txt = _leer("templates/encuesta_resultados.html")
    tel = txt[txt.index("@media (max-width: 760px)"):]
    assert "table.hist { min-width: 0; }" in tel
    assert 'grid-template-areas: "fecha" "evento" "detalle" "quien"' in tel
    for area in ("fecha", "evento", "detalle", "quien"):
        assert f"grid-area: {area};" in tel, area
    for tema in MODELOS:
        css = _sin_coment(_leer(f"static/temas/{tema}-encuesta-resultados.css"))
        assert f'html[data-tema="{tema}"] table.hist td:is(.fecha, :nth-child(4))' in css, tema


def test_r4_06_el_selector_de_vista_no_aplasta_la_pregunta():
    txt = _leer("templates/encuesta_resultados.html")
    assert ".panel-enc { display: flex; flex-wrap: wrap;" in txt
    assert ".panel-enc > div:first-child { flex: 1 1 260px; min-width: 0; }" in txt
    tel = txt[txt.index("@media (max-width: 760px)"):]
    assert ".panel-enc { flex-direction: column;" in tel
    css = _sin_coment(_leer("static/temas/noticiero-encuesta-resultados.css"))
    m = re.search(r'html\[data-tema="noticiero"\] \.panel \.panel-enc h3 \{ line-height: ([\d.]+); \}', css)
    assert m and float(m.group(1)) >= 1.05


def test_r4_07_ritmo_dice_la_semana_y_no_repite_el_total():
    html = _pagina("encuesta-resultados", "laguna")
    import fechas
    assert f'<main class="mesa-cont" data-hoy="{fechas.hoy_texto()}">' in html
    js = _sin_coment(_leer("static/encuesta_resultados.js"))
    assert "function semanaDeRitmo(ritmo, enc)" in js
    assert "'esta semana'" in js and "'en su última semana'" in js
    assert "$('k-ritmo').textContent = !ultimo ? '—' : (sem.cantidad ? '+' + num(sem.cantidad) : '0');" in js
    # la frase que repetía los dos porcentajes ya no existe
    assert "del padrón.`" not in js
    assert "nota.hidden = !nota.textContent;" in js


def test_r4_08_descargar_csv_es_de_contorno_en_noticiero():
    css = _sin_coment(_leer("static/temas/noticiero-encuesta-resultados.css"))
    regla = re.search(r'html\[data-tema="noticiero"\] a\.btn-descargar \{([^}]*)\}', css).group(1)
    assert "background: transparent" in regla and "inset 0 0 0 1.5px var(--nt-tinta)" in regla
    assert "nt-coral" not in regla


def test_r4_09_el_vacio_del_convenio_no_parece_una_zona_para_soltar():
    for ruta in ("templates/convenio.html", "static/temas/laguna-convenio.css", "static/temas/noticiero-convenio.css"):
        txt = _sin_coment(_leer(ruta))
        regla = re.search(r"\.sin-convenio \{([^}]*)\}", txt).group(1)
        assert "dashed" not in regla and "solid" in regla, ruta


def test_g3_13_el_mes_partido_dice_antes():
    txt = _leer("templates/notificaciones.html")
    assert "`Antes, en ${nombre.toLowerCase()}" in txt
    assert "const mesCorte = HOY ?" in txt


def test_g3_15_los_avatares_de_noticiero_se_distinguen():
    css = _sin_coment(_leer("static/temas/noticiero-notificaciones.css"))
    av = dict(re.findall(r"--av-(\d): ([^;]+);", css))
    assert av["1"] == "var(--nt-tinta)"
    assert "var(--nt-coral) 70%" in av["2"]
    assert "var(--nt-indigo)" in av["3"] and "var(--nt-fondo)" in av["3"]
    assert len(set(av.values())) == 3
    assert not any(re.search(r"#[0-9a-fA-F]{3,6}", v) for v in av.values())


def test_g5_31_la_leyenda_dibuja_el_trazo_punteado():
    js = _sin_coment(_leer("static/encuesta_resultados.js"))
    assert "function muestraLinea(color, guion, punto)" in js
    assert "g.setLineDash(guion || [])" in js
    assert "generateLabels: leyendaDeLineas" in js
    assert "pointStyle: muestraLinea(ds.borderColor, ds.borderDash, ds.pointStyle)" in js
    assert "pointStyle: 'line'" not in js
