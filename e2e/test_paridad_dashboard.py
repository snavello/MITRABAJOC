# -*- coding: utf-8 -*-
"""Paridad del Panel Sindical v1 / v2 (PLAN_DASHBOARD_V2.md, bloques 0 y 7).

Necesita el entorno levantado, como todo `e2e/`:

    docker compose up -d
    uvicorn main:app --reload           # en otra terminal
    python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"

Y se corre con:

    .venv/Scripts/python.exe -m pytest e2e/test_paridad_dashboard.py -q

Los de paridad:

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
  los mismos datos y los mismos pedidos al servidor.

Y los que manejan la v2 como una persona y, en cada paso, abren la v1 con la
misma dirección: controles y cajón, gráficos, mapa, explorador y modal, y el
Asistente. Este último contesta con respuestas armadas por el test (no llama
al modelo), pero la app tiene que arrancar con una `ANTHROPIC_API_KEY`,
aunque sea falsa, para que el botón exista.

Todos corren con "reducir movimiento" (para leer valores quietos), salvo
`test_la_v2_con_movimiento`, que prueba el movimiento mismo.
"""
import json
import re
import time
from datetime import timedelta
from urllib.parse import parse_qsl

import pytest
from playwright.sync_api import expect

import fechas
import paridad

# La v1 del Panel (templates/dashboard.html + static/dashboard.js) se retiró el
# 2026-10-25: la v2 es /admin/dashboard y no queda contra qué comparar. Se
# conservan como registro de cómo se midió la paridad (PLAN_DASHBOARD_V2.md,
# bloques 0 y 7) y por si se rescatan los que manejan solo la v2.
pytestmark = pytest.mark.skip(reason="la v1 se retiró el 2026-10-25: no hay paridad v1/v2 que medir")


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
    assert 1 <= lectura["max_en_vuelo"] <= 4, (
        f"{lectura['max_en_vuelo']} pedidos en vuelo a la vez; el cupo del servidor es de 4 "
        "(0 sería que el contador de la página no se instaló)")
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
    assert 1 <= v2["max_en_vuelo"] <= 4, v2["max_en_vuelo"]
    informe.paso(f"«{nombre}»: la v1 y la v2 muestran los mismos datos y piden lo mismo")


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
        # Los pedidos no se comparan acá: la v2 los acumula desde que abrió y
        # la v1 recién abre. Lo que se compara es lo que muestran.
        dif = paridad.comparar(de_la_v1, actual, [x for x in paridad.PARTES if x != "pedidos"]
                               if partes == "todo" else partes)
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


def _clic_en_grafico(page, panel, serie=0, indice=0):
    """Hace clic donde Chart.js dibujó ese dato (las barras y los segmentos son
    canvas: no hay elemento que tocar)."""
    punto = page.evaluate("""([panel, serie, indice]) => {
        const cv = document.querySelector('[data-panel="' + panel + '"] canvas');
        const ch = Chart.getChart(cv);
        const el = ch.getDatasetMeta(serie).data[indice];
        const p = el.getCenterPoint(), r = cv.getBoundingClientRect();
        return { x: r.left + p.x, y: r.top + p.y };
    }""", [panel, serie, indice])
    page.mouse.click(punto["x"], punto["y"])


def test_los_graficos_el_mapa_y_el_explorador_de_la_v2(page, informe):
    """El filtrado cruzado de la v2 tocando los gráficos y el mapa, el cambio
    de pestaña, "Ver más" y el modal "Ver". Después de cada filtro, la v1
    abierta con la misma dirección tiene que mostrar lo mismo."""
    params = _preparar(page, "90-dias")
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    page.set_viewport_size({"width": 1366, "height": 2600})
    monitor = paridad.abrir(page, "v2", params)
    v1 = page.context.new_page()
    sin_pedidos = [x for x in paridad.PARTES if x != "pedidos"]

    def tocar(paso, accion, comparar=True):
        antes = len(monitor.hechos)
        accion()
        paridad.esperar_ronda(page, "v2", monitor, antes)
        actual = paridad.lectura_actual(page, "v2", monitor)
        if comparar:
            de_la_v1 = paridad.leer(v1, "v1", dict(parse_qsl(actual["url"])))
            dif = paridad.comparar(de_la_v1, actual, sin_pedidos)
            assert not dif, f"«{paso}»: la v2 no muestra lo mismo que la v1:\n" + "\n".join(dif)
        informe.paso(f"«{paso}»: {actual['url']}")
        return actual

    a = tocar("clic en «Con diferencias» de la dona", lambda: _clic_en_grafico(page, "validacion", 0, 1))
    assert "resultado=con_diferencias" in a["url"] and a["explorador"]["pestana"] == "recibos"
    a = tocar("clic en la primera empresa", lambda: _clic_en_grafico(page, "empresas", 0, 0))
    assert "empresas=" in a["url"]
    a = tocar("clic en una barra de trámites", lambda: _clic_en_grafico(page, "tramites", 1, 0))
    assert "estado_tramite=en_proceso" in a["url"] and a["explorador"]["pestana"] == "tramites"
    a = tocar("Reiniciar", lambda: page.click(".v2-reiniciar"))
    tocar("90 días", lambda: page.click('.v2-presets button:has-text("90 días")'))
    a = tocar("clic en una burbuja del mapa", lambda: page.locator('[data-panel="seccionales-geo"] .mt-burbuja').first.click())
    assert "seccionales=" in a["url"]

    # Cambiar SOLO de pestaña trae solo el explorador, como la v1.
    antes = set(monitor.hechos)
    a = tocar("pestaña Notificaciones", lambda: page.click('#tabs-datos [data-t="notificaciones"]'))
    nuevos = set(monitor.hechos) - antes
    assert nuevos and all("/explorador/notificaciones" in x for x in nuevos), nuevos
    assert a["explorador"]["pestana"] == "notificaciones"

    tocar("pestaña Recibos", lambda: page.click('#tabs-datos [data-t="recibos"]'), comparar=False)
    filas = paridad.lectura_actual(page, "v2", monitor)["explorador"]["filas"]
    if page.locator("#ver-mas").is_visible():
        tocar("Ver más", lambda: page.click("#ver-mas"), comparar=False)
        despues = paridad.lectura_actual(page, "v2", monitor)["explorador"]["filas"]
        assert despues > filas, (filas, despues)
        assert any("page=2" in x for x in monitor.hechos)
        informe.paso(f"«Ver más» sumó filas: {filas} → {despues}")

    # La v1 se abrió en otra pestaña para comparar: las teclas van a la que
    # está al frente, así que la v2 vuelve adelante antes de usar Escape.
    page.bring_to_front()
    page.locator("#tabla-body .btn-ver").first.click()
    expect(page.locator("#overlay-det")).to_have_class(re.compile(r"\babierto\b"), timeout=10000)
    expect(page.locator("#det-contenido")).to_contain_text("Recibo verificado")
    informe.paso("El modal «Ver» abrió con el recibo")
    # El modal enfoca la X en el mismo paso en que empieza a escuchar el
    # Escape: esperar el foco evita apretar la tecla un cuadro antes.
    expect(page.locator("#det-cerrar")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#overlay-det")).not_to_have_class(re.compile(r"\babierto\b"))
    informe.paso("El modal cerró con Escape")
    assert 1 <= monitor.maximo <= 4, monitor.maximo


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


def _respuestas_del_asistente(page):
    """Cuatro respuestas armadas a mano, con datos reales del sindicato, para
    no llamar al modelo (gastaría créditos en cada corrida): una que filtra,
    una que no toca el panel, una con homónimos y un rechazo del servidor."""
    cat = paridad.catalogo(page)
    hoy = fechas.hoy()
    r = page.request.get(f"{paridad.BASE}/admin/dashboard/afiliados?q=a")
    candidatos = (r.json().get("items") if r.status == 200 else [])[:2]
    if not cat.get("seccionales") or len(candidatos) < 2:
        pytest.skip("Hace falta el lote de la UOM con seccionales y padrón. " + paridad.COMO_PREPARAR_LOTE)
    seccional = cat["seccionales"][0]

    def hace(dias):
        return (hoy - timedelta(days=dias)).isoformat()
    filtra = {"respuesta": "En los últimos 30 días hubo recibos con diferencias en " + seccional["nombre"] + ".",
              "filtros": {"desde": hace(29), "hasta": hoy.isoformat(), "seccionales": [seccional["id"]],
                          "resultado": "con_diferencias", "tab": "recibos"},
              "aplicar": True, "afiliado": None, "candidatos": [], "filtros_pendientes": {}}
    repregunta = {"respuesta": "¿De qué período querés ver los trámites?", "filtros": {}, "aplicar": False,
                  "afiliado": None, "candidatos": [], "filtros_pendientes": {}}
    homonimos = {"respuesta": "Encontré más de un afiliado con ese nombre. ¿Cuál es?", "filtros": {},
                 "aplicar": False, "afiliado": None, "candidatos": candidatos,
                 "filtros_pendientes": {"desde": hace(89), "hasta": hoy.isoformat(), "tab": "tramites"}}
    tope = {"detail": "El asistente llegó al tope de preguntas por día de tu sindicato.", "codigo": "E-PRUEBA-01"}
    return [(200, filtra), (200, repregunta), (200, homonimos), (429, tope)]


def _recorrer_asistente(page, version, params, respuestas):
    """Hace las mismas cuatro preguntas en una versión y devuelve lo que viajó
    al servidor, lo que dijo el hilo y cómo quedó la dirección en cada paso."""
    enviados, cola = [], list(respuestas)

    def responder(route):
        enviados.append(route.request.post_data_json)
        status, cuerpo = cola.pop(0)
        route.fulfill(status=status, content_type="application/json", body=json.dumps(cuerpo))
    page.route("**/admin/dashboard/asistente", responder)
    monitor = paridad.abrir(page, version, params)
    if page.locator("#btn-asist").count() == 0:
        pytest.skip("El Asistente no está en este entorno (sin ANTHROPIC_API_KEY). Para el robot alcanza "
                    "una clave cualquiera: las respuestas las arma el test, no el modelo.")
    page.click("#btn-asist")
    expect(page.locator("#asist")).to_have_class(re.compile(r"\babierto\b"))
    urls = {}

    def burbujas():
        return [" ".join(t.split()) for t in page.locator("#asist-hilo .burb").all_inner_texts()]

    def preguntar(texto, ronda):
        n = len(burbujas())
        antes = len(monitor.hechos)
        page.fill("#asist-caja", texto)
        page.press("#asist-caja", "Enter")
        expect(page.locator("#asist-hilo .burb:not(.pensando)")).to_have_count(n + 2, timeout=10000)
        if ronda:
            paridad.esperar_ronda(page, version, monitor, antes)

    def tocar(selector):
        antes = len(monitor.hechos)
        page.locator(selector).last.click()
        paridad.esperar_ronda(page, version, monitor, antes)

    preguntar("recibos con diferencias del último mes", ronda=True)
    urls["filtró"] = sorted(parse_qsl(page.url.split("?", 1)[1]))
    preguntar("y los trámites?", ronda=False)
    preguntar("recibos de García", ronda=False)
    tocar("#asist-hilo .candidatos button")
    urls["eligió homónimo"] = sorted(parse_qsl(page.url.split("?", 1)[1]))
    tocar('#asist-hilo .aplicado button:has-text("Volver")')
    urls["volvió"] = sorted(parse_qsl(page.url.split("?", 1)[1]))
    preguntar("una más", ronda=False)
    return {"enviados": enviados, "burbujas": burbujas(), "urls": urls}


def test_el_asistente_de_la_v2_hace_lo_mismo_que_el_de_la_v1(page, informe):
    """Las mismas cuatro preguntas en las dos versiones, con las respuestas
    del servidor simuladas: tiene que viajar exactamente lo mismo (la pregunta,
    la foto del estado y el historial), el hilo tiene que decir lo mismo, y la
    dirección tiene que quedar igual al filtrar, al elegir un homónimo y al
    "Volver"."""
    params = _preparar(page, "90-dias")
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    respuestas = _respuestas_del_asistente(page)
    v1 = _recorrer_asistente(page, "v1", params, respuestas)
    otra = page.context.new_page()
    v2 = _recorrer_asistente(otra, "v2", params, respuestas)
    assert v1["enviados"] == v2["enviados"], (v1["enviados"], v2["enviados"])
    informe.paso(f"Al servidor le llegó lo mismo en las {len(v2['enviados'])} preguntas")
    assert v1["burbujas"] == v2["burbujas"], (v1["burbujas"], v2["burbujas"])
    informe.paso(f"El hilo dice lo mismo ({len(v2['burbujas'])} burbujas)")
    assert v1["urls"] == v2["urls"], (v1["urls"], v2["urls"])
    assert v2["urls"]["volvió"] == v2["urls"]["filtró"], "«Volver» no dejó el panel como estaba"
    assert ("resultado", "con_diferencias") in v2["urls"]["filtró"]
    assert ("tab", "tramites") in v2["urls"]["eligió homónimo"]
    informe.paso("La dirección quedó igual al filtrar, al elegir el homónimo y al volver")


def _hasta_que(page, js, args=None, segundos=8.0):
    """Repite `js` (una función) hasta que dé verdadero. No `wait_for_function`:
    la CSP de la app no deja evaluar texto como JavaScript."""
    fin = time.time() + segundos
    while time.time() < fin:
        if page.evaluate(js, args):
            return True
        page.wait_for_timeout(50)
    return False


_ANIMANDO = """(panel) => {
    const ch = Chart.getChart(document.querySelector('[data-panel="' + panel + '"] canvas'));
    return !!ch && Chart.animator.running(ch);
}"""
_CON_DATOS = """(panel) => {
    const ch = Chart.getChart(document.querySelector('[data-panel="' + panel + '"] canvas'));
    return !!ch && ch.data.datasets.length > 0 && ch.data.datasets[0].data.length > 0;
}"""


def test_la_v2_con_movimiento(page, informe):
    """Los otros robots corren con "reducir movimiento", para leer valores
    quietos; este no. Verifica el movimiento de la v2: un panel de abajo
    espera a que se lo mire (su gráfico ya tiene los datos, pero se dibuja al
    entrar en pantalla), el modal "Ver" abre al instante con un esqueleto, la
    marca de la pestaña se desliza, las filas de "Ver más" entran escalonadas,
    y nada de eso deja errores en la consola."""
    paridad.entrar_como_admin(page)
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    errores = []
    page.on("console", lambda m: errores.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errores.append(str(e)))
    page.emulate_media(reduced_motion="no-preference")
    page.set_viewport_size({"width": 1366, "height": 800})
    hoy = fechas.hoy()
    page.goto(f"{paridad.BASE}{paridad.RUTAS['v2']}?desde={(hoy - timedelta(days=89)).isoformat()}&hasta={hoy.isoformat()}",
              wait_until="domcontentloaded")
    expect(page.locator("#v-recibos")).to_have_text(re.compile(r"\d"), timeout=15000)
    visto = re.compile(r"\bvisto\b")

    expect(page.locator('[data-panel="serie"]')).to_have_class(visto)
    formato = page.locator('[data-panel="formato"]')
    assert _hasta_que(page, _CON_DATOS, "formato"), "el gráfico de formato no recibió sus datos"
    expect(formato).not_to_have_class(visto)
    informe.paso("Arriba, los paneles ya entraron; el de formato, fuera de pantalla, espera con sus datos cargados")

    formato.scroll_into_view_if_needed()
    expect(formato).to_have_class(visto)
    assert _hasta_que(page, _ANIMANDO, "formato", 2), "el gráfico no se dibujó al entrar en pantalla"
    assert _hasta_que(page, f"(p) => !({_ANIMANDO})(p)", "formato", 8), "la entrada no terminó"
    informe.paso("Al bajar, el panel de formato entró y su gráfico se dibujó delante de quien mira")

    # El modal abre en el momento del clic: el detalle se retiene para ver el esqueleto.
    retenidos = []
    page.route("**/admin/dashboard/detalle/**", lambda r: retenidos.append(r))
    page.locator("#tabla-body .btn-ver").first.scroll_into_view_if_needed()
    page.locator("#tabla-body .btn-ver").first.click()
    expect(page.locator("#overlay-det")).to_have_class(re.compile(r"\babierto\b"))
    # Se arma con lo que la fila ya sabe, mientras el resto viaja.
    expect(page.locator("#det-contenido")).to_contain_text("Recibo verificado")
    expect(page.locator(".v2-det-cargando")).to_be_visible()
    informe.paso("El modal abrió al instante del clic y se armó con lo que ya sabía la fila mientras llega el detalle")
    fin = time.time() + 5
    while not retenidos and time.time() < fin:
        page.wait_for_timeout(50)
    assert retenidos, "el detalle no se pidió"
    retenidos[0].continue_()
    page.unroute("**/admin/dashboard/detalle/**")
    expect(page.locator(".v2-det-cargando")).to_have_count(0, timeout=10000)
    expect(page.locator("#det-contenido")).to_contain_text("Totales")
    expect(page.locator("#det-cerrar")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#overlay-det")).not_to_have_class(re.compile(r"\babierto\b"))

    # La marca de la pestaña va a parar debajo de la pestaña elegida.
    page.click('#tabs-datos [data-t="tramites"]')
    assert _hasta_que(page, """() => {
        const i = document.querySelector('.v2-indicador'), b = document.querySelector('.tab-d.act');
        if (!i || !b) return false;
        const ri = i.getBoundingClientRect(), rb = b.getBoundingClientRect();
        return Math.abs(ri.left - rb.left) < 1.5 && Math.abs(ri.width - rb.width) < 1.5;
    }""", None, 3), "la marca de la pestaña no quedó debajo de la elegida"
    informe.paso("La marca de la pestaña se deslizó hasta «Trámites»")

    if page.locator("#ver-mas").is_visible():
        antes = page.locator("#tabla-body tr").count()
        page.click("#ver-mas")
        expect(page.locator("#tabla-body tr")).not_to_have_count(antes, timeout=10000)
        nuevas = page.locator("#tabla-body tr.v2-fila-nueva").count()
        assert nuevas == page.locator("#tabla-body tr").count() - antes, nuevas
        informe.paso(f"«Ver más» sumó {nuevas} filas, que entraron escalonadas")
    assert not errores, errores
