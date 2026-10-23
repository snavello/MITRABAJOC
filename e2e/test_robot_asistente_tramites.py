# -*- coding: utf-8 -*-
"""Robot E2E: el Asistente de trámites de punta a punta, sin IA.

Recorre las cuatro etapas con el ejemplo del kit escolar (el pedido → lo que
entendí → las seis preguntas → los datos → el resultado), verifica que el resultado
traiga el diagrama, la vista previa, lo que falta configurar en el sindicato
elegido y el JSON `colm3na.tramite`, guarda un caso y lo encuentra en Casos y
en el inventario de Brechas. La IA no se toca: `/entender` no se llama
(gastaría créditos), y el flujo "Seguir sin IA" es el que se prueba.

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
    page.set_viewport_size({"width": 1280, "height": 900})
    _con_pase(page)
    page.goto(f"{BASE}{PAGINA}")
    expect(page.get_by_text("Contá qué necesita el sindicato")).to_be_visible()
    informe.paso("El analista abrió el asistente")

    # El sindicato se elige de los que tiene la base DEL SERVIDOR (la suite
    # unitaria arma otra, descartable): se mira la lista, no db.
    expect(page.locator("select")).to_be_visible()
    opciones = page.locator("select option")
    if opciones.count() < 2:
        pytest.skip(COMO_PREPARAR)
    sindicato = opciones.nth(1).inner_text()
    page.select_option("select", index=1)
    page.get_by_role("button", name="Cargar el ejemplo del kit escolar").click()
    page.get_by_role("button", name="Seguir sin IA").click()
    expect(page.get_by_text("Esto entendí")).to_be_visible()
    informe.paso(f"Cargó el ejemplo para «{sindicato}» y siguió sin IA")

    page.locator("button", has_text="preguntas →").click()
    vistas = 0
    for _ in range(20):
        expect(page.locator("h2").first).to_be_visible()
        vistas += 1
        boton = page.locator("button", has_text="Los datos del formulario")
        if boton.count():
            boton.click()
            break
        page.locator("button", has_text="Siguiente").click()
    informe.dato("Preguntas recorridas", vistas)
    assert vistas == 6, "seis preguntas, cada una con su recomendada (SDN, 2026-10-18)"
    expect(page.get_by_text("¿Estos son los datos que se piden?")).to_be_visible()
    page.locator("button", has_text="Ver el resultado").click()

    expect(page.get_by_text("Para importar en Colm3na")).to_be_visible()
    page.wait_for_timeout(600)   # el motor responde 250 ms después del último cambio
    expect(page.locator("svg[role=img]")).to_have_count(1)
    expect(page.locator(".vp-marco")).to_have_count(1)
    json_texto = page.locator("pre.json:not(.prompt)").inner_text()   # el prompt para Code también es un pre.json (2026-10-18)
    assert '"formato": "colm3na.tramite"' in json_texto and '"KE27"' in json_texto
    assert page.locator(".item.ok").count() >= 3, "módulos, área y quien arma el formulario"
    assert page.locator(".item.aj").count() >= 1 and page.locator(".item.dv").count() >= 1
    informe.paso("El resultado trajo el diagrama, la vista previa, lo que falta preparar y el JSON")

    page.locator("button", has_text="Lo que ve el afiliado").click()
    expect(page.get_by_text("Recibimos tu pedido")).to_be_visible()
    page.locator("button", has_text="Diagrama de flujo").click()

    page.fill("input[placeholder^='Qué falta acordar']", "robot e2e")
    page.locator("button", has_text="Guardar caso").click()
    expect(page.get_by_text("guardado.")).to_be_visible()
    informe.paso("Guardó el caso con una nota")

    page.locator("button.pestana", has_text="Casos").click()
    expect(page.get_by_text("Kit escolar 2027").first).to_be_visible()
    page.locator("tr.caso").first.click()
    expect(page.get_by_text("Abrir en el asistente")).to_be_visible()
    informe.paso("Lo encontró en Casos y abrió su detalle")

    page.locator("button.pestana", has_text="Brechas").click()
    expect(page.get_by_text("Lo que los sindicatos piden y Colm3na no tiene")).to_be_visible()
    fila = page.locator("tr.fila", has_text="Abrir y cerrar el formulario por fechas")
    expect(fila).to_be_visible()
    assert int(fila.locator("td.mono").nth(1).inner_text()) >= 1, "la ventana por fechas la pidió este caso"
    informe.paso("El inventario de brechas cuenta el caso recién guardado")
