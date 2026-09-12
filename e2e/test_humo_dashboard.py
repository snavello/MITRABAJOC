# -*- coding: utf-8 -*-
"""Smoke test E2E con Playwright: el robot entra por las pantallas REALES.

A diferencia de la suite unitaria (test_*.py de la raíz, SQLite aislado),
esto necesita el entorno de desarrollo completo levantado:

    docker compose up -d
    uvicorn main:app --reload           # en otra terminal
    python cargar_lote_uom.py           # si el lote UOM no está cargado

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
# Del lote sintético (cargar_lote_uom.py): clave = 5 primeros dígitos del CUIL.
TRABAJADOR = {"cuil": "27600000000", "clave": "27600"}


def _login_admin(page: Page):
    page.goto(f"{BASE}/admin")
    page.fill('input[name="usuario"]', ADMIN_UOM["usuario"])
    page.fill('input[name="clave"]', ADMIN_UOM["clave"])
    page.click('button[type="submit"]')
    page.wait_for_url("**/admin/inicio")


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
    boton.wait_for(state="visible", timeout=15000)
    boton.click()
    expect(page.locator("#overlay-det")).to_be_visible()
    expect(page.locator("#det-contenido")).to_contain_text("Recibo verificado")
    informe.paso('Abrió el modal "Ver" de un recibo del explorador')
    page.keyboard.press("Escape")
    expect(page.locator("#overlay-det")).not_to_be_visible()
    informe.paso("Cerró el modal con la tecla Escape")


def test_trabajador_entra_a_su_app(page: Page, informe):
    page.goto(f"{BASE}/ingresar")
    page.fill('input[name="cuil"]', TRABAJADOR["cuil"])
    page.fill('input[name="clave"]', TRABAJADOR["clave"])
    page.click('button[type="submit"]')
    page.wait_for_url("**/app/inicio")
    expect(page.locator("body")).to_contain_text("Hola,")
    informe.paso(f"Un trabajador del lote UOM (CUIL {TRABAJADOR['cuil']}) entró a su app")
    informe.dato("Portada del trabajador", "saludo personalizado visible")
