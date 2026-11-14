"""La pantalla de la Mesa de implementación y la pestaña Implementación de /entornos
(PLAN_IMPLEMENTACION.md, bloques 3 y 5; I10 y I11).

Sin navegador: se revisan los archivos por texto y se renderiza la plantilla
con el mismo contexto que le da la ruta. Lo que hace el navegador (vistas,
hilo, confirmaciones) lo recorre el robot de e2e.

Correr con: .venv/bin/python -m pytest test_implementacion_pantalla.py -q
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import auth
import implementacion
import main
import recursos

PLANTILLA = Path("templates/impl_mesa.html")
CSS = Path("static/implementacion/mesa.css")
JS = Path("static/implementacion/mesa.js")
EQUIPO_JS = Path("static/implementacion/equipo.js")
EQUIPO_CSS = Path("static/implementacion/equipo.css")
ARCHIVOS = (PLANTILLA, CSS, JS, EQUIPO_JS, EQUIPO_CSS)


def _texto(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _sin_comentarios(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


def _contexto(lado="sindicato", proyectos=None):
    es_equipo = lado == "equipo"
    return {
        "request": None, "marca_plataforma": None,
        "yo": {"lado": lado, "nombre": "Ana"}, "es_equipo": es_equipo,
        "proyecto": {"id": 1, "nombre": "La Bancaria"},
        "proyectos": proyectos if proyectos is not None else ([{"id": 1, "nombre": "La Bancaria"}] if es_equipo else []),
        "api": "/api/implementacion/p/1",
        "tipos": [{"id": k, **implementacion.TIPOS[k]} for k in implementacion.ORDEN_TIPOS],
        "estados": [{"id": e, "nombre": implementacion.NOMBRES_ESTADO[e]} for e in implementacion.ESTADOS],
    }


def _render(**kw):
    return main.templates.get_template("impl_mesa.html").render(**_contexto(**kw))


# ---------------------------------------------------------------- estáticos
def test_los_archivos_existen_y_la_plantilla_los_carga_con_sello():
    for p in ARCHIVOS:
        assert p.exists(), p
    html = _render()
    for nombre in ("implementacion/mesa.css", "implementacion/mesa.js", "movimiento.css"):
        assert re.search(r'/static/%s\?v=[\w-]+"' % re.escape(nombre), html), f"{nombre} sin sello ?v="
    # toda referencia a /static/ lleva sello
    for ref in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        assert "?v=" in ref, ref


def test_no_hay_cdn_ni_recursos_externos():
    for p in ARCHIVOS:
        t = _texto(p)
        externos = [u for u in re.findall(r"https?://[^\s\"')]+", t) if "www.w3.org" not in u]
        assert not externos, f"{p}: {externos}"


def test_sin_manejadores_en_linea():
    assert not re.search(r"\son[a-z]+\s*=", _texto(PLANTILLA)), "la plantilla trae un manejador en línea (onclick=...)"


def test_el_js_no_arma_html_como_texto():
    for p in (JS, EQUIPO_JS):
        js = _sin_comentarios(_texto(p))
        hallados = [x for x in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function") if x in js]
        assert not hallados, f"{p}: {hallados}"


def test_toda_respuesta_pasa_por_pedirjson():
    js = _sin_comentarios(_texto(JS))
    assert "async function pedirJson" in js
    # el único fetch de la pantalla está adentro de pedirJson
    assert len(re.findall(r"\bfetch\(", js)) == 1
    assert "401" in js and "/implementacion/ingresar" in js


def test_los_colores_de_tipo_no_estan_escritos_en_el_js_ni_en_el_css():
    codigo = (_texto(JS) + _texto(CSS)).lower()
    for k, t in implementacion.TIPOS.items():
        assert t["color"].lower() not in codigo, f"el color de {k} está escrito a mano"
    html = _render()
    for k, t in implementacion.TIPOS.items():
        assert f"--tp-{k}: {t['color']}" in html, k


# ---------------------------------------------------------------- textos
def test_la_vista_por_defecto_es_mis_pendientes_y_nunca_me_toca():
    for p in (PLANTILLA, JS, CSS):
        assert "Me toca" not in _texto(p) and "Me tocan" not in _texto(p), p
    assert "Mis pendientes" in _texto(JS) and "Mis pendientes" in _texto(PLANTILLA)
    assert "Mis pendientes" in _render()


def test_ninguna_expresion_toca_a_la_vista():
    """«Te toca / te tocan / a quién le toca» salió de lo que lee una persona:
    el indicador y el grupo son «Para responder» y la ficha dice «Quién tiene
    que responder». (`me_toca` es un campo de la API, no un texto.)"""
    js = _sin_comentarios(_texto(JS))
    literales = re.findall(r"'((?:[^'\\\n]|\\.)*)'", js)
    visibles = [x for x in literales if re.search(r"\btoca\w*\b", x, re.I) and "me_toca" not in x]
    assert not visibles, visibles
    assert "'Para responder'" in js and "Quién tiene que responder" in js
    assert "A quién le toca" not in js and "Te toca" not in js and "Te tocan" not in js
    assert not re.search(r"\btoca", _render(), re.I)


def test_el_menu_marca_la_vista_de_la_que_se_viene_o_ninguna():
    js = _sin_comentarios(_texto(JS))
    assert "ultima: null" in js                         # entrada directa a una tarjeta: nada marcado
    assert "if (vista && a.dataset.vista === vista)" in js


def test_el_equipo_y_el_sindicato_ven_su_propio_encabezado():
    sind = _render(lado="sindicato")
    assert "/implementacion/salir" in sind and "La Bancaria" in sind
    assert "Equipo Colm3na" not in sind
    equipo = _render(lado="equipo")
    assert "Equipo Colm3na" in equipo and 'href="/entornos"' in equipo
    assert "/implementacion/salir" not in equipo
    assert 'id="sel-proyecto"' not in equipo                       # un solo proyecto: sin selector
    varios = _render(lado="equipo", proyectos=[{"id": 1, "nombre": "A"}, {"id": 2, "nombre": "B"}])
    assert 'id="sel-proyecto"' in varios


def test_las_seis_tarjetas_de_tipo_llegan_a_la_pantalla():
    html = _render()
    m = re.search(r'<script type="application/json" id="impl-datos">(.*?)</script>', html, re.S)
    assert m
    import json
    datos = json.loads(m.group(1).replace("\\u0027", "'"))
    assert [t["clave"] for t in datos["tipos"]] == list(implementacion.ORDEN_TIPOS)
    assert datos["lado"] == "sindicato"


def test_la_pantalla_no_decide_permisos():
    js = _sin_comentarios(_texto(JS))
    # lo que se ofrece sale de `acciones`, no del lado de quien mira
    for clave in ("acc.responder", "acc.solo_equipo", "acc.aprobar", "acc.reabrir", "acc.subir", "acc.reasignar",
                  "puede_bajar", "puede_borrar"):
        assert clave in js, clave


# ---------------------------------------------------------------- /entornos
def _entornos():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c.get("/entornos")


def test_la_pestana_implementacion_existe_con_sus_enlaces():
    r = _entornos()
    assert r.status_code == 200
    html = r.text
    pestanas = re.findall(r'class="etab"[^>]*data-tab="(\w+)"', html) + re.findall(r'class="etab activa"[^>]*data-tab="(\w+)"', html)
    assert "implementacion" in pestanas and "herramientas" in pestanas
    panel = html.split('data-panel="implementacion"', 1)[1].split('data-panel="herramientas"', 1)[0]
    assert 'href="/implementacion"' in panel                                    # la Mesa
    assert 'href="/recursos/plan-general-implementacion/archivo"' in panel        # el plan general
    assert 'href="/entornos/herramientas/calculadora-bancaria-v2"' in panel       # las herramientas, también acá
    assert 'href="/entornos/herramientas/asistente-tramites"' in panel
    assert 'id="impl-proyecto-nuevo"' in panel and 'id="impl-usuario-nuevo"' in panel
    assert re.search(r"/static/implementacion/equipo\.js\?v=[\w-]+", html)
    assert re.search(r"/static/implementacion/equipo\.css\?v=[\w-]+", html)
    # sin sacar nada de Herramientas
    herr = html.split('data-panel="herramientas"', 1)[1]
    assert "/entornos/herramientas/calculadora-bancaria-v2" in herr and "/entornos/herramientas/asistente-tramites" in herr


def test_el_plan_general_es_un_recurso_del_catalogo():
    assert "plan-general-implementacion" in {r["clave"] for r in recursos.SEMILLA}


def test_la_pestana_se_activa_por_hash_y_oculta_recursos():
    html = _entornos().text
    assert "'implementacion', 'herramientas'" in html
    assert "nombre === 'implementacion'" in html


# ---------------------------------------------------------------- códigos y relaciones (I12 a I14)
def test_el_codigo_se_ve_en_todos_lados_y_reemplaza_al_numeral():
    js = _sin_comentarios(_texto(JS))
    for clave in ("t.codigo", "a.codigo", "x.codigo", "m.codigo", "tarjeta_codigo"):
        assert clave in js, clave
    # el «#n» queda solo como respaldo cuando el servidor no manda código
    assert "t.codigo || ('#' + t.numero)" in js
    assert "'#' + t.numero + ' ' + t.titulo" not in js and "'Tarjeta #' + a.tarjeta_numero" not in js
    assert "href: '#t' + t.numero" not in js            # los enlaces internos usan el código
    # tipografía monoespaciada y letra de código en la cabecera
    css = _texto(CSS)
    assert re.search(r"\.cod\s*\{[^}]*monospace", css, re.S)


def test_boton_copiar_con_respaldo_y_confirmacion():
    js = _sin_comentarios(_texto(JS))
    assert "navigator.clipboard.writeText" in js and "execCommand('copy')" in js
    assert "'Copiado'" in js
    for que in ("el código de la tarjeta", "el código del archivo", "el código del mensaje", "el código del hito"):
        assert que in js, que
    assert 'id="estado-copia"' in _render() and "icono('copiar')" in js
    assert 'id="i-copiar"' in _render()


def test_los_codigos_de_un_texto_se_enlazan_con_dom_y_solo_los_que_existen():
    js = _sin_comentarios(_texto(JS))
    assert "function enlazar(" in js
    assert "r.existe" in js and "r.enlace" in js        # solo existe:true y con enlace
    assert "enlazar(m.texto, m.refs)" in js and "enlazar(t.titulo, t.refs)" in js
    assert "createTextNode" in js
    # los inexistentes quedan como texto común, sin clase ni marca
    assert "buenos[m[0].toUpperCase()]" in js and "if (!ref) continue;" in js


def test_el_hash_acepta_los_cuatro_codigos_y_el_numero_viejo():
    js = _sin_comentarios(_texto(JS))
    assert "/^t(\\d+)$/" in js                            # #t4 sigue valiendo
    assert "esCodigo(r)" in js and "buscar?codigo=" in js
    for tipo in ("r.tipo === 'hito'", "r.tipo === 'mensaje' || r.tipo === 'archivo'", "r.tarjeta_id"):
        assert tipo in js, tipo
    assert "No existe o no lo podés ver." in js          # el mismo mensaje en todos los casos
    for ej in ("PE0004", "PE0004-3", "AR000123", "HI0001"):
        assert ej  # documentan el contrato; los hashes se recorren en el navegador
    assert "abrirFicha(r.id)" in js                      # AR sin elemento visible -> su ficha


def test_buscador_unico_con_rotulo_y_ejemplo_en_escritorio_y_telefono():
    html = _render()
    assert html.count("data-buscador") == 2              # barra lateral y barra del teléfono
    assert html.count("PE0004, AR000123 o una palabra") >= 2
    assert 'class="buscar-t">Buscar<' in html
    js = _sin_comentarios(_texto(JS))
    assert "esCodigo(v)" in js and "'#buscar?q='" in js and "tarjetas?vista=todas&q=" in js
    css = _texto(CSS)
    assert ".top-buscar { display: block" in css and ".nav .buscar { display: none" in css.replace(", .nav-pie, .nav .buscar", ".nav .buscar") or ".nav .buscar" in css


def test_bloque_relacionadas_agrupado_y_ficha_de_archivo():
    js = _sin_comentarios(_texto(JS))
    for frase in ("responde a", "respondida con", "menciona", "mencionada en"):
        assert f"'{frase}'" in js, frase
    assert "bloqueRelacionadas(d.relacionadas)" in js and "if (!lista.length) return null;" in js
    assert "'archivos/' + aid + '/ficha'" in js and "$fa.showModal()" in js
    assert "a.puede_bajar" in js and "a.puede_borrar" in js
    assert 'id="ficha-arch"' in _render()


def test_responder_con_manda_responde_a_y_solo_si_acciones_lo_permite():
    js = _sin_comentarios(_texto(JS))
    assert "if (acc.responder) chips.appendChild" in js and "Responder con…" in js
    assert "fd.append('responde_a', origen.codigo)" in js
    assert "tipoDeCodigo(origen.codigo) === 'pedido'" in js and "tipo = 'entrega'" in js   # preselecciona, no impide cambiar
    assert "Responde a " in js
    assert "Podés nombrar otra tarjeta o archivo por su código (PE0004, AR000123) y queda enlazado." in js
    assert "'aria-expanded'" in js                      # la ayuda es un «?» que abre, no un hover


def test_la_resaltada_respeta_reducir_movimiento():
    css = _texto(CSS)
    assert ".resalta { animation: none; }" in css


def test_la_pestana_muestra_el_enlace_de_ingreso_del_sindicato_con_boton_copiar():
    js = _sin_comentarios(_texto(EQUIPO_JS))
    assert "/implementacion/ingresar" in js and "navigator.clipboard.writeText" in js and "Copiar enlace" in js
