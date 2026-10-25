"""Los modales se pueden mover, y en TODAS las pantallas que tienen modales.

Pedido de Sd el 2026-09-13: "el modal tiene ubicación fija y creo sería útil
poder moverlo al menos en desktop (aplica a todos los modales)". El "aplica a
todos" es lo que este archivo cuida: el arrastre vive en un solo archivo
compartido (`static/modales.js`) justamente para que no pase lo de siempre --
tres modales se mueven, el cuarto no, y nadie se entera hasta que alguien lo
usa en una demo.

Por eso el test no prueba el arrastre (eso necesita un navegador y está en los
robots de e2e): prueba **la cobertura**. Recorre las plantillas, busca las que
tienen una caja de modal y exige que todas carguen el script. Una plantilla
nueva con un modal entra sola a la lista, así que el olvido se nota acá y no
en producción.

Correr con: .venv/bin/python -m pytest test_modales.py -q
"""
import os
import re

import main
from fastapi.testclient import TestClient

PLANTILLAS = "templates"

# Las cajas de modal de la app, las mismas que busca modales.js. Si aparece una
# familia nueva de modal, va en los dos lugares.
CAJAS = ("modal-hoja", "modal-notif-caja", "modal-articulo", "modal-recibo", "modal-det")

cliente = TestClient(main.app)


def _con_modales():
    """Las plantillas que tienen al menos una caja de modal."""
    salida = []
    for nombre in sorted(os.listdir(PLANTILLAS)):
        if not nombre.endswith(".html"):
            continue
        with open(os.path.join(PLANTILLAS, nombre), encoding="utf-8") as f:
            html = f.read()
        # `class="modal-recibo-card"` no cuenta: es una tarjeta de contenido
        # ADENTRO de un modal, no un modal. De ahí el límite de palabra.
        if any(re.search(r'class="[^"]*\b%s\b' % caja, html) for caja in CAJAS):
            salida.append((nombre, html))
    return salida


def test_hay_plantillas_con_modales():
    """Baranda del propio test: si el regex dejara de encontrar cajas, los dos
    tests de abajo pasarían recorriendo una lista vacía."""
    nombres = [n for n, _ in _con_modales()]
    assert len(nombres) >= 7, nombres
    for esperada in ("portada.html", "admin.html", "trabajador.html"):
        assert esperada in nombres, f"{esperada} tiene modales y el test no la ve"
    print(f"OK  test_hay_plantillas_con_modales ({len(nombres)} plantillas)")


def test_todas_las_pantallas_con_modales_cargan_el_script():
    faltan = [nombre for nombre, html in _con_modales() if "modales.js" not in html]
    assert not faltan, ("estas pantallas tienen modales y no cargan modales.js, "
                        f"así que sus modales no se mueven: {faltan}")
    print("OK  test_todas_las_pantallas_con_modales_cargan_el_script")


def test_el_script_va_con_sello_de_version():
    """Regla del proyecto, sin excepciones: todo lo que sale de /static/ va con
    `?v=`. Se sirve con Cache-Control de una hora, así que sin sello un cambio
    tarda hasta una hora en llegar y mientras tanto se ve el HTML nuevo con el
    archivo viejo -- peor que ver la versión anterior entera."""
    for nombre, html in _con_modales():
        if "modales.js" not in html:
            continue
        assert "modales.js?v={{ sello_static('modales.js') }}" in html, nombre
    print("OK  test_el_script_va_con_sello_de_version")


def test_el_navegador_puede_bajarlo():
    r = cliente.get("/static/modales.js")
    assert r.status_code == 200
    assert "javascript" in r.headers.get("content-type", "")
    print("OK  test_el_navegador_puede_bajarlo")


def test_solo_en_escritorio_y_con_mouse():
    """En un teléfono el modal es una hoja pegada al borde inferior: moverla no
    tiene sentido y competiría con el scroll del contenido. El recorte tiene
    que estar en el script Y en el CSS del cursor, o la pista visual aparecería
    donde no se puede arrastrar."""
    with open("static/modales.js", encoding="utf-8") as f:
        js = f.read()
    with open("static/marca.css", encoding="utf-8") as f:
        css = f.read()
    condicion = "(min-width: 700px) and (pointer: fine)"
    assert condicion in js, "modales.js tiene que limitarse a escritorio con mouse"
    assert condicion in css, "el cursor de agarre tiene que limitarse a lo mismo"
    print("OK  test_solo_en_escritorio_y_con_mouse")


def test_la_tarjeta_de_contenido_no_es_un_modal():
    """`.modal-recibo-card` es una tarjeta ADENTRO del modal de trámite. Si
    entrara en la lista de cajas, `closest()` la encontraría primero y el
    arrastre movería el contenido dentro del modal en vez del modal."""
    with open("static/modales.js", encoding="utf-8") as f:
        js = f.read()
    cajas = re.search(r'var CAJAS = "([^"]+)"', js).group(1)
    assert "modal-recibo-card" not in cajas, cajas
    print("OK  test_la_tarjeta_de_contenido_no_es_un_modal")


# ---------- El movimiento de los modales (2026-10-13) ----------
# Mismo criterio que el arrastre: el movimiento vive en dos archivos
# compartidos (static/movimiento.css y el segundo bloque de modales.js) para
# que no pase que tres modales entren con movimiento y el cuarto aparezca de
# golpe. Lo que se prueba acá es la cobertura; cómo se ve, los robots.

# Pantallas con modales que, a propósito, no cargan el movimiento común. Era
# la v1 del Panel (dashboard.html), que se retiró el 2026-10-25: el panel de
# hoy arma sus modales con Preact y su propio movimiento.
SIN_MOVIMIENTO = set()


def test_todas_las_pantallas_con_modales_cargan_el_movimiento():
    faltan = [nombre for nombre, html in _con_modales()
              if nombre not in SIN_MOVIMIENTO
              and "movimiento.css?v={{ sello_static('movimiento.css') }}" not in html]
    assert not faltan, ("estas pantallas tienen modales y no cargan movimiento.css "
                        f"(o lo cargan sin sello): sus modales aparecerían de golpe: {faltan}")
    print("OK  test_todas_las_pantallas_con_modales_cargan_el_movimiento")


def _fondos_js():
    with open("static/modales.js", encoding="utf-8") as f:
        js = f.read()
    lista = re.search(r'var FONDOS_MOV = "([^"]+)"', js).group(1)
    return [x.strip().lstrip(".") for x in lista.split(",")]


def test_el_css_cubre_los_mismos_fondos_que_el_script():
    """El script sostiene la salida con `mov-sale` y el CSS es el que la deja
    visible: un fondo que esté en uno solo se cerraría de golpe (o quedaría
    abierto, invisible y sin recibir clics, el tiempo de la salida)."""
    with open("static/movimiento.css", encoding="utf-8") as f:
        css = f.read()
    fondos = _fondos_js()
    assert len(fondos) >= 4, fondos
    for fondo in fondos:
        assert f".{fondo}.mov-sale" in css, f"{fondo}: falta su regla de salida en movimiento.css"
    print("OK  test_el_css_cubre_los_mismos_fondos_que_el_script")


def test_el_ver_del_panel_no_entra_en_el_movimiento_compartido():
    """`.overlay-det` es el "Ver" del Panel Sindical: la v1 no se toca y la v2
    trae su propio movimiento en panel.css. Si entrara acá, la v2 tendría dos
    motores peleándose por la misma caja."""
    assert "overlay-det" not in _fondos_js()
    with open("static/movimiento.css", encoding="utf-8") as f:
        css = f.read()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert "overlay-det" not in sin_comentarios and "modal-det" not in sin_comentarios
    print("OK  test_el_ver_del_panel_no_entra_en_el_movimiento_compartido")


def test_las_duraciones_viven_en_un_solo_lugar():
    """Los `--mov-*` y `--ease-*` se definen solo en movimiento.css: con dos
    copias, cambiar una duración en una dejaría la otra pantalla con la vieja,
    y la v2 del Panel (que los lee desde JS para Chart.js) dejaría de coincidir
    con su propio CSS."""
    definiciones = re.compile(r"--(mov|ease)-[a-z]+\s*:")
    for raiz, _, archivos in os.walk("static"):
        if "vendor" in raiz:
            continue
        for nombre in archivos:
            if not nombre.endswith(".css"):
                continue
            ruta = os.path.join(raiz, nombre)
            with open(ruta, encoding="utf-8") as f:
                hay = definiciones.findall(re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S))
            if ruta.replace(os.sep, "/") == "static/movimiento.css":
                assert len(hay) >= 10, "movimiento.css perdió sus duraciones"
            else:
                assert not hay, f"{ruta} define duraciones propias: van en movimiento.css"
    with open("templates/dashboard_v2.html", encoding="utf-8") as f:
        v2 = f.read()
    assert v2.index("movimiento.css") < v2.index("panel_v2/panel.css"), \
        "la v2 tiene que cargar movimiento.css antes que su panel.css"
    print("OK  test_las_duraciones_viven_en_un_solo_lugar")


def test_nada_del_movimiento_anima_transform():
    """modales.js arrastra la caja con `style.transform`: una animación sobre
    `transform` lo pisaría y el modal saltaría al centro en plena entrada o
    salida. Se anima `scale` y `translate`, que se suman al arrastre."""
    with open("static/movimiento.css", encoding="utf-8") as f:
        css = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
    for bloque in re.findall(r"@keyframes\s+[\w-]+\s*\{(.*?)\}\s*\}", css, flags=re.S):
        assert "transform" not in bloque, bloque
    print("OK  test_nada_del_movimiento_anima_transform")


def test_las_vistas_de_tramites_se_arman_como_un_modal():
    """Los trámites del afiliado y de la empresa no abren un modal: cambian de
    vista adentro de la pestaña. SDN lo notó en Pruebas ("los trámites del
    trabajador no tienen el efecto", 2026-10-13). La pestaña y sus cuatro
    vistas llevan `data-mov-vista`, que modales.js vigila y movimiento.css
    arma; si una vista nueva no la lleva, cambia de golpe."""
    for plantilla, prefijo in (("trabajador.html", "tram"), ("empresa.html", "trx")):
        with open(os.path.join(PLANTILLAS, plantilla), encoding="utf-8") as f:
            html = f.read()
        assert 'id="tp-tramites" data-mov-vista' in html, plantilla
        for vista in ("inicio", "tipos", "form", "detalle"):
            assert f'id="{prefijo}-{vista}" data-mov-vista' in html, (plantilla, vista)
    with open("static/modales.js", encoding="utf-8") as f:
        js = f.read()
    assert 'querySelectorAll("[data-mov-vista]")' in js
    with open("static/movimiento.css", encoding="utf-8") as f:
        css = f.read()
    assert "[data-mov-vista]) [data-armado]" in css
    print("OK  test_las_vistas_de_tramites_se_arman_como_un_modal")


def test_las_pestanas_de_las_cuatro_apps_se_arman():
    """Cada pestaña de las cuatro apps (y las sub-pestañas del panel del
    sindicato y de plataforma) lleva `data-mov-vista`: una pestaña nueva sin
    la marca aparece de golpe mientras las demás se arman. Se cuentan los
    `<div>` de cada clase de pestaña y se exige la marca en todos."""
    clases = {
        "trabajador.html": ["tpanel"],
        "empresa.html": ["tpanel"],
        "admin.html": ["panel", "subpanel", "tramite-subpanel", "emp-subpanel",
                       "emptram-subpanel", "enc-subpanel", "au-subpanel"],
        "plataforma.html": ["ppanel", "ia-subpanel"],
    }
    for plantilla, nombres in clases.items():
        with open(os.path.join(PLANTILLAS, plantilla), encoding="utf-8") as f:
            html = f.read()
        for nombre in nombres:
            divs = re.findall(r'<div class="%s(?:[ "][^>]*)?>' % re.escape(nombre), html)
            assert divs, (plantilla, nombre)
            sin = [d for d in divs if "data-mov-vista" not in d]
            assert not sin, (plantilla, nombre, sin)
        assert "modales.js?v={{ sello_static('modales.js') }}" in html, plantilla
        assert "movimiento.css?v={{ sello_static('movimiento.css') }}" in html, plantilla
    print("OK  test_las_pestanas_de_las_cuatro_apps_se_arman")
