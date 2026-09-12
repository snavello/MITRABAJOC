# -*- coding: utf-8 -*-
"""Smoke test E2E con Playwright: el robot entra por las pantallas REALES.

A diferencia de la suite unitaria (test_*.py de la raíz, que corre contra una
base Postgres descartable), esto necesita el entorno de desarrollo completo
levantado:

    docker compose up -d
    uvicorn main:app --reload           # en otra terminal
    python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"

Y se corre con:

    .venv/Scripts/python.exe -m pytest e2e/ -q

Cubre el camino feliz de las dos puntas del Panel Sindical: el admin que
abre el dashboard y ve datos vivos, y un trabajador del lote que entra a
su app. Es la semilla del robot de QA en tiempo real: cada flujo nuevo se
suma como otro test acá.
"""
import os
import re

import pytest
from playwright.sync_api import Page, expect
import fechas

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")

ADMIN_UOM = {"usuario": "20111111110", "clave": "uom-demo"}

# Primer trabajador del lote sintético de la UOM. Son DOS porque hay dos
# cargadores: `cargar_lote_sindicato.py` (el actual, para cualquier sindicato)
# y `cargar_lote_uom.py` (el anterior, específico). Cada uno genera su propia
# serie de CUILes, así que el robot prueba con los dos en vez de exigir que
# esté cargado justo el que él conocía. La clave son los 5 primeros dígitos.
TRABAJADORES_DEL_LOTE = ["27660000000", "27600000000"]

COMO_PREPARAR_DEMO = ("Falta la demo. Corré: python cargar_marca_plataforma.py && "
                      "python cargar_demo.py")
COMO_PREPARAR_LOTE = ('Falta el lote de la UOM. Corré: python cargar_lote_sindicato.py '
                      '--sindicato "Unión Obrera Metalúrgica"')


def _login_admin(page: Page):
    page.goto(f"{BASE}/admin")
    page.fill('input[name="usuario"]', ADMIN_UOM["usuario"])
    page.fill('input[name="clave"]', ADMIN_UOM["clave"])
    page.click('button[type="submit"]')
    try:
        page.wait_for_url("**/admin/inicio", wait_until="commit", timeout=10000)
    except Exception:
        # Un prerequisito que falta se dice, no se deja morir en un timeout de
        # 30 segundos que parece una falla de la app (regla de e2e/README.md).
        pytest.skip(COMO_PREPARAR_DEMO)


def _login_trabajador(page: Page) -> str:
    """Entra con el primer CUIL del lote que exista. Devuelve cuál fue.

    `wait_until="commit"` y no el default "load": la portada del trabajador
    puede dibujar el mapa de su seccional, y las teselas de OpenStreetMap
    salen a la red. Si esa red no está o va lenta, el evento `load` tarda o no
    llega, y la espera se agota con la página YA en su destino. Lo que
    interesa acá es haber entrado, no que haya terminado de dibujarse el mapa
    de un tercero.
    """
    for cuil in TRABAJADORES_DEL_LOTE:
        page.goto(f"{BASE}/ingresar")
        # La pantalla tiene DOS formularios (ingresar y registrarme) con campos
        # del mismo nombre: hay que apuntar al de login.
        login = page.locator("#form-login")
        login.locator('input[name="cuil"]').fill(cuil)
        login.locator('input[name="clave"]').fill(cuil[:5])
        login.locator('button[type="submit"]').click()
        try:
            page.wait_for_url("**/app/inicio", wait_until="commit", timeout=8000)
            return cuil
        except Exception:
            continue
    pytest.skip(COMO_PREPARAR_LOTE)


def test_admin_dashboard_carga_con_datos(page: Page, informe):
    _login_admin(page)
    informe.paso("El admin de la UOM entró a su panel")
    page.goto(f"{BASE}/admin/dashboard")

    # Los KPIs llegan por fetch: esperar a que "Recibos analizados" tenga un
    # número real (deja de decir el guion del estado de carga).
    expect(page.locator("#v-recibos")).not_to_have_text("—", timeout=15000)
    recibos = page.locator("#v-recibos").inner_text()
    assert re.sub(r"[^0-9]", "", recibos), f"KPI sin número: {recibos!r}"
    informe.paso(f"El Panel Sindical cargó con datos vivos ({recibos} recibos analizados)")
    informe.dato("Recibos analizados (hoy)", recibos)

    # La zona de filtros y los paneles principales están en pantalla.
    expect(page.locator(".filtros-card")).to_be_visible()
    expect(page.locator('[data-panel="semaforo"]')).to_be_visible()

    # Cambiar el período serializa el estado en la URL (link compartible).
    page.click('#presets button[data-p="30"]')
    page.wait_for_url(re.compile(r"desde=\d{4}-\d{2}-\d{2}"))
    informe.paso("Cambió el período a 30 días y los filtros quedaron en la URL (link compartible)")


def test_admin_dashboard_modal_ver(page: Page, informe):
    _login_admin(page)
    page.goto(f"{BASE}/admin/dashboard?desde=2026-06-01&hasta={fechas.hoy().isoformat()}")
    boton = page.locator("#tabla-body .btn-ver").first
    try:
        boton.wait_for(state="visible", timeout=15000)
    except Exception:
        pytest.skip(COMO_PREPARAR_LOTE + " (el explorador no tiene ni un recibo)")
    boton.click()
    expect(page.locator("#overlay-det")).to_be_visible()
    expect(page.locator("#det-contenido")).to_contain_text("Recibo verificado")
    informe.paso('Abrió el modal "Ver" de un recibo del explorador')
    page.keyboard.press("Escape")
    expect(page.locator("#overlay-det")).not_to_be_visible()
    informe.paso("Cerró el modal con la tecla Escape")


def test_trabajador_entra_a_su_app(page: Page, informe):
    cuil = _login_trabajador(page)
    expect(page.locator("body")).to_contain_text("Hola,")
    informe.paso(f"Un trabajador del lote UOM (CUIL {cuil}) entró a su app")
    informe.dato("Portada del trabajador", "saludo personalizado visible")
