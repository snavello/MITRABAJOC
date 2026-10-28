# -*- coding: utf-8 -*-
"""Robot E2E: el Asistente de trámites de punta a punta, sin IA.

Recorre los cuatro pasos con el ejemplo del kit escolar (el relato → lo que
entendí → los datos → el veredicto, PLAN_ASISTENTE_TRAMITES_V2.md), contesta
una duda con texto, verifica el veredicto con sus seis puntos, la vista previa
y el JSON `colm3na.tramite`, ensaya la importación al sindicato elegido,
guarda el trámite y lo encuentra en la lista de la izquierda y en el
inventario de Brechas. La IA no se toca: `/entender` no se llama (gastaría
créditos), y el flujo "Seguir sin IA" es el que se prueba. No confirma la
importación: eso crea tipos de trámite reales en la base del servidor.

Necesita el entorno levantado y al menos un sindicato con una seccional
"Sede Central" (la demo alcanza):

    docker compose up -d && alembic upgrade head
    python cargar_marca_plataforma.py && python cargar_demo.py
    uvicorn main:app --reload

Entra con una sesión de plataforma armada con el SESSION_SECRET del .env
(el mismo que usa el servidor): la landing no tiene usuario de prueba.

Se corre con:  .venv/bin/python -m pytest e2e/test_robot_asistente_tramites.py -q
"""
import os

import pytest
from playwright.sync_api import expect

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
PAGINA = "/entornos/herramientas/asistente-tramites"
COMO_PREPARAR = "Falta un sindicato en la base del servidor. Corré: python cargar_demo.py"


def _con_pase(page):
    import auth
    page.context.add_cookies([{"name": "sesion_plataforma", "url": BASE,
                               "value": auth.crear_sesion("plataforma", id_usuario=1, ident="robot-e2e")}])


def test_del_relato_al_json_sin_ia(nuevo_actor, informe):
    page = nuevo_actor("analista")
    page.set_viewport_size({"width": 1440, "height": 950})
    _con_pase(page)
    page.goto(f"{BASE}{PAGINA}")
    page.evaluate("localStorage.clear()")
    page.reload()
    expect(page.get_by_role("heading", name="Contá el trámite como te lo contó el sindicato")).to_be_visible()
    expect(page.locator(".riel-paso")).to_have_count(4)
    informe.paso("El analista abrió el asistente: cuatro pasos en el riel")

    # El sindicato se elige de los que tiene la base DEL SERVIDOR (la suite
    # unitaria arma otra, descartable): se mira la lista, no db.
    opciones = page.locator("select option")
    if opciones.count() < 2:
        pytest.skip(COMO_PREPARAR)
    sindicato = opciones.nth(1).inner_text()
    page.select_option("select", index=1)
    page.get_by_role("button", name="Cargar el ejemplo del kit escolar").click()
    page.get_by_role("button", name="Seguir sin IA").click()
    expect(page.get_by_text("Esto entendí")).to_be_visible()
    expect(page.locator(".grupo-frases")).to_have_count(5)
    expect(page.locator(".frase")).to_have_count(13)
    informe.paso(f"Cargó el ejemplo para «{sindicato}» y siguió sin IA: trece respuestas en cinco grupos, sin cuestionario")

    expect(page.locator(".duda")).to_have_count(2)
    page.locator(".duda input").first.fill("Aprueba la seccional")
    page.locator(".duda input").first.press("Enter")
    expect(page.locator(".duda")).to_have_count(1)
    expect(page.locator(".aclaracion")).to_have_count(1)
    informe.paso("Contestó una duda con texto y la otra la dejó para el sindicato")

    page.locator("button", has_text="Los datos →").click()
    expect(page.get_by_text("Los datos que se le piden")).to_be_visible()
    expect(page.locator(".cp")).to_have_count(13)
    page.locator("button", has_text="El veredicto →").click()
    page.wait_for_timeout(600)   # el motor responde 250 ms después del último cambio
    expect(page.locator(".v-puntos li")).to_have_count(6)
    expect(page.locator(".vp-marco")).to_have_count(1)
    informe.dato("Veredicto", page.locator(".paso h2").first.inner_text())
    informe.paso("El veredicto contesta las seis preguntas")

    page.locator("button", has_text=f"Importar a {sindicato}").click()
    expect(page.locator(".imp h3")).to_contain_text("como borrador")
    expect(page.locator(".imp tr.fila").first).to_be_visible()
    informe.paso("El ensayo de la importación dice qué se crearía y qué queda pendiente")

    page.locator(".secc-cab", has_text="El JSON colm3na.tramite").click()
    json_texto = page.locator("pre.json:not(.prompt)").inner_text()
    assert '"formato": "colm3na.tramite"' in json_texto and '"KE27"' in json_texto
    page.locator(".secc-cab", has_text="El circuito").click()
    expect(page.locator("svg[role=img]")).to_have_count(1)
    informe.paso("El JSON y el diagrama están en sus secciones plegadas")

    antes = page.locator(".tramite-item").count()
    page.get_by_role("button", name="Guardar trámite").click()
    expect(page.locator(".v-importar .estado-ia")).to_contain_text("Guardado")
    expect(page.locator(".tramite-item")).to_have_count(antes + 1)
    informe.paso("Guardó el trámite y apareció en la lista de la izquierda")

    page.get_by_role("button", name="+ Nuevo trámite").click()
    expect(page.locator("textarea")).to_have_value("")
    page.locator(".tramite-item").first.click()
    expect(page.locator(".v-puntos li")).to_have_count(6)
    informe.paso("Abrió uno nuevo y retomó el guardado desde la lista")

    page.locator("a", has_text="Lo que Colm3na no tiene todavía").click()
    expect(page.get_by_text("Lo que los sindicatos piden y Colm3na no tiene")).to_be_visible()
    fila = page.locator("tr.fila", has_text="Abrir y cerrar el formulario por fechas")
    expect(fila).to_be_visible()
    assert int(fila.locator("td.mono").nth(1).inner_text()) >= 1, "la ventana por fechas la pidió este trámite"
    informe.paso("El inventario de brechas cuenta el trámite recién guardado")
