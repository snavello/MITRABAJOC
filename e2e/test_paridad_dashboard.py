# -*- coding: utf-8 -*-
"""Paridad del Panel Sindical v1 / v2 (PLAN_DASHBOARD_V2.md, bloques 0 y 7).

Necesita el entorno levantado, como todo `e2e/`:

    docker compose up -d
    uvicorn main:app --reload           # en otra terminal
    python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"

Y se corre con:

    .venv/Scripts/python.exe -m pytest e2e/test_paridad_dashboard.py -q

Tres tests:

- `test_linea_de_base_v1` abre la v1 con cada combinación de filtros de
  `paridad.NOMBRES` y verifica que esté sana: ningún panel en error, ningún
  pedido rechazado y **nunca más de 4 pedidos en vuelo**, medido en el
  navegador. Deja la lectura en JSON y una captura en
  `e2e/resultados/paridad/`.
- `test_la_lectura_es_estable` abre la v1 dos veces con los mismos filtros y
  exige que las dos lecturas sean iguales. Es la baranda del robot: si leer
  dos veces lo mismo diera distinto, la comparación con la v2 fallaría por
  el robot y no por la v2.
- `test_paridad_v1_v2` lee las dos versiones con cada combinación y exige
  los mismos datos y los mismos pedidos al servidor. Se saltea, diciendo por
  qué, hasta que exista la v2 y su lector (bloque 7 del plan).
"""
import re
from urllib.parse import parse_qsl

import pytest
from playwright.sync_api import expect

import fechas
import paridad


def _preparar(page, nombre):
    paridad.entrar_como_admin(page)
    params = paridad.parametros(nombre, fechas.hoy(), paridad.catalogo(page))
    return params


@pytest.mark.parametrize("nombre", paridad.NOMBRES)
def test_linea_de_base_v1(page, informe, nombre):
    params = _preparar(page, nombre)
    lectura = paridad.leer(page, "v1", params)
    destino = paridad.guardar(page, "v1", nombre, lectura)
    informe.paso(f"Abrió la v1 con «{nombre}» ({lectura['url'] or 'sin filtros'})")

    assert not lectura["paneles_con_error"], lectura["paneles_con_error"]
    assert not lectura["aviso"], f"el servidor rechazó los filtros: {lectura['aviso']}"
    assert not lectura["pedidos_fallidos"], lectura["pedidos_fallidos"]
    assert lectura["pedidos"], "el panel no le pidió nada al servidor"
    assert lectura["max_en_vuelo"] <= 4, (
        f"{lectura['max_en_vuelo']} pedidos en vuelo a la vez; el cupo del servidor es de 4")
    assert paridad.numeros(lectura["kpis"].get("recibos")), lectura["kpis"]

    if nombre == "url-con-fecha-futura":
        # Descartada la URL, el panel abre en "Hoy": desde y hasta son hoy.
        hoy = fechas.hoy().isoformat()
        assert f"desde={hoy}" in lectura["url"] and f"hasta={hoy}" in lectura["url"], lectura["url"]

    informe.dato(f"{nombre}: recibos analizados", lectura["kpis"]["recibos"])
    informe.dato(f"{nombre}: pedidos distintos / máximo en vuelo",
                 f"{len(lectura['pedidos'])} / {lectura['max_en_vuelo']}")
    informe.dato(f"{nombre}: lectura y captura", destino.name + ".json / .png")


def test_la_lectura_es_estable(page, informe):
    params = _preparar(page, "90-dias-seccional-salario")
    primera = paridad.leer(page, "v1", params)
    segunda = paridad.leer(page, "v1", params)
    diferencias = paridad.comparar(primera, segunda)
    assert not diferencias, "dos lecturas de la v1 no coinciden:\n" + "\n".join(diferencias)
    informe.paso("Dos lecturas seguidas de la v1 con los mismos filtros dieron lo mismo")


@pytest.mark.parametrize("nombre", paridad.NOMBRES)
def test_paridad_v1_v2(page, informe, nombre):
    params = _preparar(page, nombre)
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    if paridad.LECTORES.get("v2", {}).get("cubre") != "todo":
        pytest.skip("La v2 todavía no tiene todos los paneles: compara solo "
                    f"{paridad.LECTORES['v2']['cubre']} (test_lo_que_ya_tiene_la_v2_coincide). "
                    "Paridad completa: PLAN_DASHBOARD_V2.md, bloque 7.")
    v1 = paridad.leer(page, "v1", params)
    v2 = paridad.leer(page, "v2", params)
    paridad.guardar(page, "v2", nombre, v2)
    diferencias = paridad.comparar(v1, v2)
    assert not diferencias, f"«{nombre}»: la v2 no muestra lo mismo que la v1:\n" + "\n".join(diferencias)
    assert v2["max_en_vuelo"] <= 4, v2["max_en_vuelo"]
    informe.paso(f"«{nombre}»: la v1 y la v2 muestran los mismos datos")


@pytest.mark.parametrize("nombre", paridad.NOMBRES)
def test_lo_que_ya_tiene_la_v2_coincide(page, informe, nombre):
    """Mientras la v2 se arma por bloques: lo que ya tiene (`cubre` en su
    lector) muestra lo mismo que la v1, y no le pide al servidor nada que la
    v1 no pida (línea roja 3 del plan)."""
    params = _preparar(page, nombre)
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    partes = paridad.LECTORES["v2"]["cubre"]
    v1 = paridad.leer(page, "v1", params)
    v2 = paridad.leer(page, "v2", params)
    paridad.guardar(page, "v2", nombre, v2)
    diferencias = paridad.comparar(v1, v2, partes if partes != "todo" else paridad.PARTES)
    assert not diferencias, f"«{nombre}»: la v2 no muestra lo mismo que la v1:\n" + "\n".join(diferencias)
    de_mas = sorted(set(v2["pedidos"]) - set(v1["pedidos"]))
    assert not de_mas, "la v2 pide cosas que la v1 no pide:\n" + "\n".join(de_mas)
    assert not v2["paneles_con_error"] and not v2["aviso"], (v2["paneles_con_error"], v2["aviso"])
    assert v2["max_en_vuelo"] <= 4, v2["max_en_vuelo"]
    assert v2["url"] == v1["url"], f"la dirección quedó distinta: v1 {v1['url']!r} / v2 {v2['url']!r}"
    informe.paso(f"«{nombre}»: la v2 coincide con la v1 en {', '.join(partes)}")
    informe.dato(f"{nombre}: recibos v1 / v2", f"{v1['kpis'].get('recibos')} / {v2['kpis'].get('recibos')}")


def test_los_controles_de_la_v2_dan_lo_mismo_que_la_v1(page, informe):
    """Manejar la v2 como una persona (período, seccional en el cajón, quitar
    una pastilla, Reiniciar) y, en cada paso, abrir la v1 con la MISMA
    dirección en otra pestaña: tienen que mostrar lo mismo. Prueba que los
    controles de la v2 arman el estado correcto, no solo que lo lean."""
    params = _preparar(page, "90-dias")
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    partes = paridad.LECTORES["v2"]["cubre"]
    monitor = paridad.abrir(page, "v2", params)
    v1 = page.context.new_page()

    def comparar_con_v1(paso):
        actual = paridad.lectura_actual(page, "v2", monitor)
        de_la_v1 = paridad.leer(v1, "v1", dict(parse_qsl(actual["url"])))
        dif = paridad.comparar(de_la_v1, actual, partes)
        assert not dif, f"«{paso}»: la v2 no muestra lo mismo que la v1:\n" + "\n".join(dif)
        informe.paso(f"«{paso}»: igual a la v1 ({actual['kpis'].get('recibos')} recibos, "
                     f"{len(actual['filtros_activos'])} filtros)")

    def tocar(paso, accion):
        antes = len(monitor.hechos)
        accion()
        paridad.esperar_ronda(page, "v2", monitor, antes)
        comparar_con_v1(paso)

    tocar("30 días", lambda: page.click('.v2-presets button:has-text("30 días")'))

    def elegir_seccional():
        page.click(".v2-btn-filtros")
        page.locator(".v2-cajon .multi-chips").first.locator(".m-chip").nth(1).click()
        page.keyboard.press("Escape")
    tocar("una seccional desde el cajón", elegir_seccional)

    def formato_nuevo():
        page.click(".v2-btn-filtros")
        page.click('.v2-cajon .seg button:has-text("Ley 27.802")')
        page.keyboard.press("Escape")
    tocar("formato Ley 27.802", formato_nuevo)
    tocar("quitar la pastilla de la seccional", lambda: page.locator(".v2-puesto button").first.click())
    tocar("Reiniciar", lambda: page.click(".v2-reiniciar"))
    assert monitor.maximo <= 4, monitor.maximo


def test_la_v2_abre_sin_errores(page, informe):
    """La v2 abre en un navegador de verdad: todos sus módulos cargan por el
    importmap, sin errores en la consola ni archivos de /static/ rechazados,
    pinta la fecha de hoy que manda el servidor y los indicadores, el cajón de
    filtros queda por ENCIMA del encabezado, y los enlaces llevan de una
    versión a la otra con los filtros."""
    paridad.entrar_como_admin(page)
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    errores, rechazados = [], []
    # "Failed to load resource" lo cubre el control de /static/ de abajo: el
    # /favicon.ico que falta en toda la app no es de la v2.
    page.on("console", lambda m: errores.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errores.append(str(e)))
    page.on("response", lambda r: rechazados.append(f"{r.status} {r.url}")
            if r.status >= 400 and "/static/" in r.url else None)
    page.goto(f"{paridad.BASE}{paridad.RUTAS['v2']}?desde=2026-01-01&hasta={fechas.hoy().isoformat()}",
              wait_until="domcontentloaded")
    # Una espera sobre el elemento y no `wait_for_function`: la CSP de la app no
    # deja evaluar texto como JavaScript (sin 'unsafe-eval'), y eso es buscado.
    expect(page.locator("#v-recibos")).to_have_text(re.compile(r"\d"), timeout=15000)
    assert str(fechas.hoy().year) in page.locator("#hoy-fecha").inner_text()
    informe.paso("La v2 abrió con la fecha del servidor y los indicadores: "
                 f"{page.locator('#v-recibos').inner_text()} recibos")

    page.click(".v2-btn-filtros")
    page.wait_for_timeout(500)
    arriba = page.evaluate("""() => { const c = document.querySelector('.v2-cajon').getBoundingClientRect();
        const e = document.elementFromPoint(c.left + c.width / 2, 20); return !!(e && e.closest('.v2-cajon')); }""")
    assert arriba, "el encabezado tapa el cajón de filtros"
    page.keyboard.press("Escape")
    informe.paso("El cajón de filtros abrió por encima del encabezado y cerró con Escape")
    assert not errores, errores
    assert not rechazados, rechazados

    page.click("text=Ver en la versión actual")
    page.wait_for_url(re.compile(r"/admin/dashboard\?.*desde=2026-01-01"), wait_until="commit")
    informe.paso("El enlace «Ver en la versión actual» llevó a la v1 con los filtros")
    page.wait_for_load_state("domcontentloaded")
    page.click("text=Probar la versión nueva")
    page.wait_for_url(re.compile(r"/admin/dashboard-v2\?.*desde=2026-01-01"), wait_until="commit")
    informe.paso("El enlace «Probar la versión nueva» llevó a la v2 con los filtros de la v1")
