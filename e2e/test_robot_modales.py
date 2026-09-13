# -*- coding: utf-8 -*-
"""Robot E2E: los modales se pueden mover en escritorio.

Es de las cosas que sólo se pueden probar en un navegador de verdad: el
arrastre son eventos de puntero, la posición la aplica un `transform` y el
recorte depende del tamaño real de la ventana. La suite unitaria
(`test_modales.py`) prueba lo otro, que es la COBERTURA: que todas las
pantallas con modales carguen el script.

Se prueban las dos familias de modal que más se usan, una en cada app, porque
el pedido fue "aplica a todos los modales" y lo que puede romperse es
justamente que una familia quede afuera:

- `.modal-notif-caja` con su encabezado pegajoso (perfil del afiliado).
- `.modal-recibo` del panel del sindicato (la ficha de una seccional).

Necesita el entorno levantado y la demo cargada, igual que el resto de e2e/:

    docker compose up -d && alembic upgrade head
    python cargar_marca_plataforma.py && python cargar_demo.py
    python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"
    uvicorn main:app --reload

Y se corre con:  .venv/bin/python -m pytest e2e/test_robot_modales.py -q
"""
import os

import pytest
from playwright.sync_api import expect

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")

ADMIN_UOM = {"usuario": "20111111110", "clave": "uom-demo"}
# Primer trabajador del lote de la UOM (clave = 5 primeros dígitos del CUIL).
TRABAJADOR_UOM = {"cuil": "27660000000", "clave": "27660"}

COMO_PREPARAR = ("Falta la demo o su lote. Corré: python cargar_demo.py && "
                 'python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"')


def _arrastrar(page, agarre, dx, dy):
    """Arrastra desde el centro del agarre. Devuelve nada: lo que se mide
    después es dónde quedó la caja."""
    caja = agarre.bounding_box()
    x, y = caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=12)
    page.mouse.up()


def test_el_modal_de_perfil_se_mueve_y_vuelve(nuevo_actor, informe):
    page = nuevo_actor("afiliado")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{BASE}/ingresar")
    page.fill('#form-login input[name="cuil"]', TRABAJADOR_UOM["cuil"])
    page.fill('#form-login input[name="clave"]', TRABAJADOR_UOM["clave"])
    page.click('#form-login button[type="submit"]')
    try:
        page.wait_for_url("**/app/inicio", wait_until="commit", timeout=15000)
    except Exception:
        pytest.skip(COMO_PREPARAR)
    page.click("button.circulo-acento")
    expect(page.locator("#overlay-perfil")).to_have_class("overlay abierto")
    informe.paso("El afiliado abrió su perfil")

    caja = page.locator("#overlay-perfil .modal-notif-caja")
    antes = caja.bounding_box()
    _arrastrar(page, page.locator("#overlay-perfil .modal-notif-enc"), 170, -110)
    despues = caja.bounding_box()
    assert abs(despues["x"] - antes["x"] - 170) < 8, (antes, despues)
    assert abs(despues["y"] - antes["y"] + 110) < 8, (antes, despues)
    informe.dato("Desplazamiento", f"{despues['x']-antes['x']:.0f} x {despues['y']-antes['y']:.0f} px")
    informe.paso("Arrastrando el encabezado, el modal se movió")

    # Llevarlo lejísimo no lo saca de la ventana: si se fuera, la X de cerrar
    # quedaría afuera y el modal sería imposible de cerrar.
    _arrastrar(page, page.locator("#overlay-perfil .modal-notif-enc"), 3000, 3000)
    lejos = caja.bounding_box()
    ancho = page.evaluate("innerWidth")
    alto = page.evaluate("innerHeight")
    assert lejos["x"] >= -1 and lejos["x"] + lejos["width"] <= ancho + 1, lejos
    assert lejos["y"] >= -1 and lejos["y"] + lejos["height"] <= alto + 1, lejos
    informe.paso("Empujándolo contra el borde queda entero adentro de la ventana")

    page.click("#overlay-perfil .modal-cerrar-clara")
    page.click("button.circulo-acento")
    expect(page.locator("#overlay-perfil")).to_have_class("overlay abierto")
    vuelta = caja.bounding_box()
    assert abs(vuelta["x"] - antes["x"]) < 2 and abs(vuelta["y"] - antes["y"]) < 2, (antes, vuelta)
    informe.paso("Al cerrarlo y volver a abrirlo aparece en su lugar de siempre")


def test_un_modal_del_panel_del_sindicato_tambien_se_mueve(nuevo_actor, informe):
    page = nuevo_actor("admin")
    page.set_viewport_size({"width": 1440, "height": 950})
    page.goto(f"{BASE}/admin")
    page.fill('input[name="usuario"]', ADMIN_UOM["usuario"])
    page.fill('input[name="clave"]', ADMIN_UOM["clave"])
    page.click('button[type="submit"]')
    try:
        page.wait_for_url("**/admin/inicio", wait_until="commit", timeout=15000)
    except Exception:
        pytest.skip(COMO_PREPARAR)
    page.goto(f"{BASE}/admin", wait_until="commit")
    page.click('.tab-btn[data-panel="seccionales"]')
    # Solo filas con botón "Ver": la primera fila de la tabla es el
    # encabezado y no tiene ninguno.
    fila = page.locator('#panel-seccionales tr:has(button:has-text("Ver"))').first
    if fila.count() == 0:
        pytest.skip("No hay seccionales cargadas. " + COMO_PREPARAR)
    fila.locator('button:has-text("Ver")').click()
    expect(page.locator("#modal-seccional")).to_be_visible()
    informe.paso("El admin abrió la ficha de una seccional")

    caja = page.locator("#modal-seccional .modal-recibo")
    antes = caja.bounding_box()
    _arrastrar(page, page.locator("#modal-seccional .modal-recibo-enc"), 130, 70)
    despues = caja.bounding_box()
    assert abs(despues["x"] - antes["x"] - 130) < 8, (antes, despues)
    informe.dato("Desplazamiento", f"{despues['x']-antes['x']:.0f} x {despues['y']-antes['y']:.0f} px")
    informe.paso("La ficha también se mueve: el arrastre no es sólo del modal de perfil")
