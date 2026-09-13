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
    assert len(nombres) >= 8, nombres
    for esperada in ("portada.html", "admin.html", "dashboard.html", "trabajador.html"):
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
