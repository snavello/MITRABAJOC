"""Las pantallas de la Fiesta (PLAN_FIESTA.md): la app del afiliado (test_afiliado_*)
y la del sindicato (test_sindicato_*).

Correr con: .venv/bin/python -m pytest test_fiesta_pantallas.py -q
"""
import hashlib
import re
from pathlib import Path

import main


# ---------------------------------------------------------------------------
# App del sindicato (/fiesta/sindicato)
# ---------------------------------------------------------------------------
PLANTILLA_SIND = Path("templates") / "fiesta_sindicato.html"
JS_SIND = Path("static") / "fiesta" / "sindicato.js"
CSS_SIND = Path("static") / "fiesta" / "sindicato.css"
VENDOR_JSQR = Path("static") / "vendor" / "jsqr"

# Las rutas JSON del sindicato, tal cual las fija PLAN_FIESTA.md (los {x} son
# parámetros). Si el backend ya las escribió, también se contrasta contra
# main.app.routes.
RUTAS_SIND_PLAN = {
    "entrar", "salir", "clave", "resumen", "reservas", "reserva/{x}/anular",
    "reserva/{x}/nota", "padron", "padron/csv", "padron/{x}/activo", "cortesia",
    "configuracion", "foto", "operadores", "operador", "operador/{x}/activo",
    "operador/{x}/restablecer", "ingreso/qr", "ingreso/documento", "buscar",
}
RUTAS_PUBLICAS_SIND = {"/fiesta/sindicato/reservas.csv", "/fiesta/entrada/{x}", "/fiesta/foto/{x}"}


def _sin_comentarios_js(texto):
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"(?m)(^|[^:'\"])//.*$", r"\1", texto)


def _rutas_api_del_js():
    """Los `B + 'ruta' + id + '/otra'` del JS, normalizados a 'ruta/{x}/otra'."""
    js = JS_SIND.read_text(encoding="utf-8")
    salida = set()
    for expr in re.findall(r"\bB \+ ((?:'[^']*'|\w[\w.]*)(?: \+ (?:'[^']*'|\w[\w.]*))*)", js):
        ruta = ""
        for pieza in expr.split(" + "):
            if pieza.startswith("'"):
                ruta += pieza[1:-1]
            else:
                ruta += "{x}"
        salida.add(ruta.split("?")[0])
    return salida


def test_sindicato_el_js_llama_solo_a_rutas_del_plan():
    usadas = _rutas_api_del_js()
    assert usadas, "el regex no encontró ninguna llamada: el test no verifica nada"
    assert usadas <= RUTAS_SIND_PLAN, f"rutas que no están en el plan: {usadas - RUTAS_SIND_PLAN}"
    # Y las que existen en main.py (si el backend ya las escribió) las cubren.
    reales = {re.sub(r"\{[^}]+\}", "{x}", r.path) for r in main.app.routes if hasattr(r, "path")}
    prefijo = "/api/fiesta/sindicato/"
    hay_backend = any(p.startswith(prefijo) for p in reales)
    if hay_backend:
        faltan = {u for u in usadas if prefijo + u not in reales}
        assert not faltan, f"el JS llama a rutas que main.py no tiene: {faltan}"
    # Las páginas y descargas que el JS arma a mano.
    js = JS_SIND.read_text(encoding="utf-8")
    for ruta in ("/fiesta/sindicato/reservas.csv", "/fiesta/foto/", "/fiesta/entrada/"):
        assert ruta in js, ruta
    if hay_backend:
        for ruta in RUTAS_PUBLICAS_SIND:
            assert ruta in reales, f"falta la ruta {ruta} en main.py"


def test_sindicato_la_plantilla_no_apunta_a_rutas_que_no_existen():
    html = PLANTILLA_SIND.read_text(encoding="utf-8")
    # Ningún formulario hace un POST de página completa: todo va por fetch.
    assert "action=" not in html
    hrefs = set(re.findall(r'href="(/[^"{]*)"', html))
    assert hrefs <= {"/fiesta/sindicato/reservas.csv"}, hrefs
    # No hay fetch( en la plantilla: la lógica vive en el .js.
    assert "fetch(" not in html


def test_sindicato_todo_static_lleva_sello():
    html = PLANTILLA_SIND.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/static/[^"]*)"', html)
    assert len(refs) >= 5
    for ref in refs:
        assert "?v={{ sello_static('" in ref, f"{ref} sin sello ?v="
    for esperado in ("fiesta/fiesta.css", "fiesta/sindicato.css", "fiesta/sindicato.js",
                     "vendor/jsqr/jsQR.js", "movimiento.css", "numeros_ar.js"):
        assert f"sello_static('{esperado}')" in html, esperado
    # Las URLs de /static/ que arma el JS a mano también (aquí: ninguna).
    assert "/static/" not in JS_SIND.read_text(encoding="utf-8")


def test_sindicato_el_texto_de_personas_nunca_entra_como_html():
    for ruta in (JS_SIND, Path("static") / "fiesta" / "sindicato.css"):
        texto = _sin_comentarios_js(ruta.read_text(encoding="utf-8"))
        for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert prohibido not in texto, f"{ruta.name}: {prohibido}"
    # El único HTML armado como texto es el de los íconos del resultado: una
    # constante propia (ICONOS), leída con DOMParser, que no lleva datos.
    js = JS_SIND.read_text(encoding="utf-8")
    assert "DOMParser" in js and "ICONOS" in js


def _plantilla_renderizada(operador):
    evento = dict(id=1, nombre="Fiesta de prueba", fecha_hora="2026-11-14T21:00",
                  fecha_texto="sábado 14 de noviembre, 21:00", lugar="Palacio", precio=30000,
                  tope_por_afiliado=4, tope_general=1000, horas_antes=24, minutos_vencimiento=30,
                  leyenda_cortesia="Invitado Especial", foto=False)
    return main.templates.get_template("fiesta_sindicato.html").render(
        request=None, evento=evento, operador=operador, mp_modo="mock")


def test_sindicato_las_pestanas_y_vistas_llevan_data_mov_vista():
    admin = _plantilla_renderizada(dict(usuario="a", nombre="Ana", rol="admin", debe_cambiar_clave=False))
    paneles = re.findall(r'<section class="fs-panel"[^>]*>', admin)
    assert len(paneles) == 5, paneles
    assert all("data-mov-vista" in p for p in paneles), paneles
    assert re.findall(r'data-tab="(\w+)"', admin) == ["panel", "puerta", "padron", "cortesias", "config"]
    login = _plantilla_renderizada(None)
    assert 'id="form-login"' in login and "data-mov-vista" in login
    clave = _plantilla_renderizada(dict(usuario="a", nombre="Ana", rol="admin", debe_cambiar_clave=True))
    assert 'id="form-clave"' in clave and 'id="tabs"' not in clave


def test_sindicato_el_rol_puerta_solo_ve_la_puerta():
    html = _plantilla_renderizada(dict(usuario="p", nombre="Pedro", rol="puerta", debe_cambiar_clave=False))
    assert re.findall(r'data-tab="(\w+)"', html) == ["puerta"]
    assert 'data-panel="puerta"' in html
    for ajeno in ('data-panel="panel"', 'data-panel="padron"', 'data-panel="cortesias"', 'data-panel="config"'):
        assert ajeno not in html, ajeno
    assert 'id="btn-salir"' in html
    assert 'id="video"' in html and 'id="form-buscar"' in html and 'id="form-pegar"' in html


def test_sindicato_la_puerta_tiene_camara_trasera_barcodedetector_y_jsqr():
    js = JS_SIND.read_text(encoding="utf-8")
    assert "facingMode: { ideal: 'environment' }" in js
    assert "BarcodeDetector" in js and "jsQR(" in js
    assert "ingreso/qr" in js and "ingreso/documento" in js
    assert "navigator.vibrate" in js
    assert "2500" in js and "5000" in js  # vuelve solo a los 2,5 s; memoria de 5 s
    # Todos los resultados que pide el plan.
    for texto in ("Pasa · ", "Ya ingresaron ", "Ya ingresó todo", "Código vencido", "No existe", "Reserva sin pagar"):
        assert texto in js, texto
    # El motivo del ingreso con documento es obligatorio en la pantalla.
    assert "required" in js and "Motivo (obligatorio)" in js


def test_sindicato_el_js_traduce_los_5xx_y_el_html_a_un_mensaje_claro():
    js = JS_SIND.read_text(encoding="utf-8")
    assert "async function pedirJson" in js
    assert "El servidor no respondió" in js
    assert "r.json()" in js and js.count("r.json()") == 1  # solo adentro de pedirJson


def test_sindicato_jsqr_vendoreado_es_el_registrado():
    ficha = (VENDOR_JSQR / "ORIGEN.md").read_text(encoding="utf-8")
    registro = dict((nombre, sha) for sha, nombre in re.findall(r"^([0-9a-f]{64})\s+(\S+)$", ficha, re.M))
    archivos = {p.name for p in VENDOR_JSQR.iterdir() if p.is_file() and p.name != "ORIGEN.md"}
    assert archivos == set(registro), f"ORIGEN.md y la carpeta no listan lo mismo: {archivos ^ set(registro)}"
    for nombre, sha in registro.items():
        assert hashlib.sha256((VENDOR_JSQR / nombre).read_bytes()).hexdigest() == sha, \
            f"{nombre} cambió sin actualizar ORIGEN.md"
    assert "1.4.0" in ficha and "jsQR.js" in registro and "LICENSE" in registro


def test_sindicato_la_tarjeta_de_entornos_apunta_a_las_rutas_de_arranque():
    html = Path("templates/entornos.html").read_text(encoding="utf-8")
    assert 'href="/fiesta"' in html and 'href="/fiesta/sindicato"' in html
    assert "/api/entornos/herramientas/fiesta/estado" in html
    assert "/api/entornos/herramientas/fiesta/arranque" in html
    form = re.search(r'<form id="fiesta-arranque".*?</form>', html, re.S).group(0)
    campos = set(re.findall(r'name="(\w+)"', form))
    assert campos == {"nombre", "fecha_hora", "lugar", "precio", "tope_por_afiliado",
                      "tope_general", "usuario", "nombre_op", "clave_inicial"}
    for prellenado in ("Fiesta de Fin de Año SUPARA 2026", "2026-11-14T21:00", "Palacio Anchorena",
                       'value="30000"', 'value="4"', 'value="1000"'):
        assert prellenado in form, prellenado
    reales = {r.path for r in main.app.routes if hasattr(r, "path")}
    if "/api/entornos/herramientas/fiesta/estado" in reales:
        assert "/api/entornos/herramientas/fiesta/arranque" in reales


# ---------------------------------------------------------------------------
# App del afiliado, el ticket y las páginas públicas (test_afiliado_*)
# ---------------------------------------------------------------------------
PLANTILLAS_AF = ["fiesta_afiliado.html", "fiesta_entrada.html", "fiesta_verificar.html",
                 "fiesta_mp_simulado.html"]
JS_AF = [Path("static") / "fiesta" / "afiliado.js", Path("static") / "fiesta" / "entrada.js"]
CSS_FIESTA = Path("static") / "fiesta" / "fiesta.css"

# Las rutas que las pantallas del afiliado pueden llamar (PLAN_FIESTA.md,
# «Afiliado»). `{x}` = un parámetro de la ruta.
RUTAS_AF_PLAN = {
    "/api/fiesta/entrar", "/api/fiesta/salir", "/api/fiesta/estado", "/api/fiesta/reservar",
    "/api/fiesta/reserva/{x}", "/api/fiesta/reserva/{x}/anular", "/api/fiesta/mp-simulado/{x}",
    "/fiesta", "/fiesta/pago/vuelta", "/fiesta/entrada/{x}", "/fiesta/foto/{x}",
}


def _leer(ruta):
    return Path(ruta).read_text(encoding="utf-8")


def _normalizar_ruta(expr):
    """'/api/fiesta/reserva/' + id + '/anular'  ->  /api/fiesta/reserva/{x}/anular"""
    ruta = ""
    for pieza in re.split(r"\s*\+\s*", expr.strip()):
        if pieza[:1] in "'\"":
            ruta += pieza[1:-1]
        else:
            ruta += "{x}"
    return ruta.split("?")[0].split("#")[0]


def _rutas_de_js_af():
    salida = set()
    for ruta in JS_AF:
        js = _leer(ruta)
        for expr in re.findall(r"(?:pedirJson|postJson|fetch)\(\s*((?:'[^']*'|\"[^\"]*\")(?:\s*\+\s*(?:'[^']*'|\"[^\"]*\"|[\w.]+))*)", js):
            salida.add(_normalizar_ruta(expr))
    return salida


def test_afiliado_todo_static_con_sello():
    for nombre in PLANTILLAS_AF:
        html = _leer(Path("templates") / nombre)
        refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
        assert refs, nombre
        for ref in refs:
            assert "?v={{ sello_static(" in ref, f"{nombre}: {ref} sin sello ?v="
    # y los url() de las hojas (fuentes) llevan el sello de la hoja que los carga
    css = _leer(CSS_FIESTA)
    for fuente in re.findall(r'url\("(/static/fonts/[^"]+)"\)', css):
        assert (Path(fuente.lstrip("/"))).exists(), fuente


def test_afiliado_los_fetch_apuntan_a_rutas_del_plan():
    usadas = _rutas_de_js_af()
    assert "/api/fiesta/estado" in usadas, "el regex no encontró las llamadas: el test no verifica nada"
    assert usadas <= RUTAS_AF_PLAN, f"rutas que no están en el plan: {usadas - RUTAS_AF_PLAN}"
    # la plantilla del simulado y el JS de la entrada
    sim = _leer("templates/fiesta_mp_simulado.html")
    assert "/api/fiesta/mp-simulado/' + id" in sim and "/fiesta/pago/vuelta?reserva=" in sim
    assert "action=" not in "".join(_leer(Path("templates") / n) for n in PLANTILLAS_AF)
    # si el backend ya las escribió, existen de verdad
    reales = {re.sub(r"\{[^}]+\}", "{x}", r.path) for r in main.app.routes if hasattr(r, "path")}
    if "/api/fiesta/estado" in reales:
        faltan = {u for u in usadas if u not in reales}
        assert not faltan, f"el JS llama a rutas que main.py no tiene: {faltan}"
        for ruta in ("/fiesta/pago/vuelta", "/fiesta/entrada/{x}", "/fiesta/e/{x}"):
            assert ruta in reales, ruta


def test_afiliado_nada_de_innerhtml_con_datos():
    for ruta in JS_AF + [Path("templates") / n for n in PLANTILLAS_AF]:
        texto = _leer(ruta)
        assert "innerHTML" not in texto, f"{ruta}: usar textContent"
        assert "document.write" not in texto, ruta
    # la única inserción de markup es el SVG del QR que arma el servidor
    assert _leer(JS_AF[1]).count("insertAdjacentHTML") == 1


def test_afiliado_las_vistas_llevan_data_mov_vista():
    html = _leer("templates/fiesta_afiliado.html")
    for vista in ("v-ingreso", "v-inicio", "v-sin-evento"):
        assert re.search(r'id="%s"' % vista, html), vista
        assert re.search(r'data-mov-vista[^>]*id="%s"' % vista, html), f"{vista} sin data-mov-vista"
    assert "data-mov-vista" in _leer("templates/fiesta_entrada.html")
    assert "data-mov-vista" in _leer("templates/fiesta_verificar.html")
    # movimiento.css va ANTES de fiesta.css y el script que arma las vistas se carga con sello
    for nombre in PLANTILLAS_AF:
        h = _leer(Path("templates") / nombre)
        assert h.index("movimiento.css") < h.index("fiesta/fiesta.css"), nombre
        assert "modales.js?v={{ sello_static('modales.js') }}" in h, nombre


def test_afiliado_las_duraciones_salen_de_movimiento_css():
    css = _sin_comentarios_css(_leer(CSS_FIESTA))
    assert not re.search(r"--(mov|ease)-[a-z]+\s*:", css), "fiesta.css define duraciones propias"
    for nombre in PLANTILLAS_AF:
        h = _leer(Path("templates") / nombre)
        for dur in re.findall(r"(?:transition|animation)[^;{}]*?\b(\d+(?:\.\d+)?m?s)\b", _sin_comentarios_css(h)):
            # los tiempos sueltos solo valen para animaciones decorativas largas (>= 900 ms)
            assert dur.endswith("ms") and int(dur[:-2]) >= 900 or dur.endswith("s"), f"{nombre}: {dur}"


def _sin_comentarios_css(t):
    return re.sub(r"/\*.*?\*/", "", t, flags=re.S)


def test_afiliado_las_fuentes_nuevas_tienen_licencia():
    css = _leer(CSS_FIESTA)
    for fuente, licencia in (("cinzel-700.woff2", "OFL-cinzel.txt"), ("playfair-italic.woff2", "OFL-playfair.txt")):
        assert (Path("static/fonts") / fuente).stat().st_size > 5000, fuente
        assert fuente in css, fuente
        txt = _leer(Path("static/fonts/licencias") / licencia)
        assert "SIL Open Font License" in txt, licencia
        assert fuente in _leer("static/fonts/licencias/LEEME.md"), fuente


def test_afiliado_los_tokens_del_plan():
    css = _leer(CSS_FIESTA)
    for token in ("--f-noche", "--f-noche-2", "--f-tinta", "--f-papel", "--f-oro", "--f-oro-claro",
                  "--f-oro-oscuro", "--f-texto", "--f-texto-suave", "--f-ok", "--f-aviso", "--f-error",
                  "--f-info", "--f-display", "--f-texto-fuente", "--f-mono", "--f-radio",
                  "--f-radio-chico", "--f-sombra", "--f-velo"):
        assert re.search(re.escape(token) + r"\s*:", css), token
    assert "prefers-reduced-motion" in css


def test_afiliado_colm3na_no_aparece():
    for nombre in PLANTILLAS_AF:
        assert "colm3na" not in _leer(Path("templates") / nombre).lower(), nombre
    for ruta in JS_AF + [CSS_FIESTA]:
        assert "colm3na" not in _leer(ruta).lower(), ruta


def test_afiliado_las_plantillas_renderizan_con_el_contexto_del_backend():
    ev = dict(id=1, nombre="Fiesta", fecha_hora="2026-11-14T21:00", fecha_texto="sábado 14 de noviembre, 21:00",
              lugar="Palacio", precio=30000, tope_por_afiliado=4, horas_antes=24, foto=True)
    res = dict(id=1, numero="R-000001", nombre="Ana <b>Pérez</b>", cantidad=2, tipo="cortesia",
               estado="pagada", leyenda="Invitado Especial", ingresados=1, ultimo_ingreso="2026-11-14T21:42:10",
               importe=0)
    t = main.templates.env
    h = t.get_template("fiesta_afiliado.html").render(request=None, hay_evento=True, evento=ev, sesion=None, mp_modo="mock")
    assert "/fiesta/foto/1" in h and "Fiesta" in h
    h = t.get_template("fiesta_afiliado.html").render(request=None, hay_evento=False, evento=None, sesion=None, mp_modo="apagado")
    assert "v-sin-evento" in h
    h = t.get_template("fiesta_entrada.html").render(
        request=None, evento=ev, reserva=res, habilitada=True, entrada_desde="el 13/11", qr_svg="<svg></svg>",
        qr_vence_en=600, filigrana="<svg></svg>", url_renovar="/api/fiesta/entrada/1/qr", url_verificar="x")
    assert "INVITADO ESPECIAL" in h and "ADMITE 2 PERSONAS" in h and "21:42" in h
    assert "<b>Pérez</b>" not in h, "el nombre de la persona tiene que ir escapado"
    h = t.get_template("fiesta_verificar.html").render(request=None, valido=True, motivo="", evento=ev, reserva=res)
    assert "Entrada válida" in h and "dni" not in h.lower()
    h = t.get_template("fiesta_verificar.html").render(request=None, valido=False, motivo="Venció", evento=ev, reserva=None)
    assert "Entrada no válida" in h
    h = t.get_template("fiesta_mp_simulado.html").render(request=None, evento=ev, reserva=res, importe_texto="$ 1,00")
    assert "MP_MOCK" in h


def test_formulario_de_arranque_respeta_hidden():
    from pathlib import Path
    html = (Path(__file__).parent / "templates" / "entornos.html").read_text(encoding="utf-8")
    assert ".fiesta-arranque[hidden]" in html
