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
