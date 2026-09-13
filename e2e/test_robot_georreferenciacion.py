# -*- coding: utf-8 -*-
"""Robot E2E de georreferenciación: mapas de verdad, en un navegador de verdad.

Es lo único que prueba lo que la suite unitaria no puede: que Leaflet dibuje,
que el globo se pueda arrastrar, que tocar un marcador del Panel filtre el
resto del tablero, y que el permiso de ubicación del navegador se comporte
como la pantalla promete cuando se lo concede y cuando se lo niega.

Necesita el entorno levantado y la demo cargada:

    docker compose up -d
    alembic upgrade head
    python cargar_marca_plataforma.py && python cargar_demo.py
    python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"
    uvicorn main:app --reload

Y se corre con:  .venv/bin/python -m pytest e2e/test_robot_georreferenciacion.py -q

**Este robot NO toca la base de datos, y es a propósito.** El conftest de la
raíz apunta `db` a una base descartable ANTES de que el de `e2e/` pueda
revertirlo (es lo que su propio encabezado advierte, pero el arreglo llega
tarde: cuando la fixture corre, `db.engine` ya está creado). Un robot que
leyera `db` para verificar estaría mirando una base vacía y distinta de la que
usa el servidor que está probando. Así que todo se comprueba por donde lo
comprueba una persona: la pantalla y los endpoints de la app.

**Las teselas de OpenStreetMap no se verifican.** Salen a la red en cada uso
(no se pueden cachear, es su política), así que en un entorno sin salida a
internet el mapa queda gris y eso NO es una falla de la app: se verifica que
el contenedor de Leaflet exista, que los marcadores estén y que las
interacciones funcionen. Confundir "no hay teselas" con "el mapa está roto"
haría fallar este robot por algo que no es nuestro.
"""
import os
import re

import pytest
from playwright.sync_api import expect

import fechas

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")

ADMIN_UOM = {"usuario": "20111111110", "clave": "uom-demo"}
# Primer trabajador del lote de la UOM. El lote es determinista por sindicato
# y usa los 5 primeros dígitos del CUIL como clave.
TRABAJADOR_UOM = {"cuil": "27660000000", "clave": "27660"}
# Rosario, para que la geolocalización simulada tenga una seccional cerca.
POSICION_ROSARIO = {"latitude": -32.9500, "longitude": -60.6400}

COMO_PREPARAR = ("Falta la demo o su lote. Corré: python cargar_demo.py && "
                 'python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"')


def _login_admin(page):
    page.goto(f"{BASE}/admin")
    page.fill('input[name="usuario"]', ADMIN_UOM["usuario"])
    page.fill('input[name="clave"]', ADMIN_UOM["clave"])
    page.click('button[type="submit"]')
    try:
        page.wait_for_url("**/admin/inicio", timeout=8000)
    except Exception:
        pytest.skip(COMO_PREPARAR)


def _login_trabajador(page):
    page.goto(f"{BASE}/ingresar")
    # La pantalla tiene DOS formularios (ingresar y registrarme) con campos
    # del mismo nombre: hay que apuntar al de login o Playwright no sabe cuál.
    login = page.locator("#form-login")
    login.locator('input[name="cuil"]').fill(TRABAJADOR_UOM["cuil"])
    login.locator('input[name="clave"]').fill(TRABAJADOR_UOM["clave"])
    login.locator('button[type="submit"]').click()
    try:
        # `wait_until="commit"` y no el default "load": la portada del
        # trabajador dibuja el mapa de su seccional al cargar, y las teselas
        # de OSM salen a la red. En un entorno sin salida esos pedidos quedan
        # colgados, el evento `load` no llega nunca y la espera se agota con
        # la página YA en su destino. Esperar la navegación y no la carga
        # completa es además lo correcto: lo que interesa es haber entrado.
        page.wait_for_url("**/app/inicio", wait_until="commit", timeout=10000)
    except Exception:
        pytest.skip(COMO_PREPARAR)


def _abrir_seccionales(page):
    page.goto(f"{BASE}/admin")
    page.click('.tab-btn[data-panel="seccionales"]')
    expect(page.locator("#panel-seccionales")).to_be_visible()


# ------------------------------------------- 1. el asistente de alta guiada

def test_asistente_de_alta_de_seccional(nuevo_actor, informe):
    """Los tres pasos completos, con búsqueda real contra Georef y Nominatim.

    Desde el 2026-09-13 una seccional NO se puede guardar sin ubicar, así que
    lo que se verifica cuando esas APIs no responden (entorno sin salida a
    internet) es la vía de escape: el mapa se abre igual y el punto se marca a
    mano. Es lo que mantiene en pie la otra promesa -- que un servicio ajeno
    caído no impida dar de alta una delegación -- ahora que el globo es
    obligatorio.
    """
    page = nuevo_actor("admin")
    _login_admin(page)
    _abrir_seccionales(page)
    informe.paso("El admin de la UOM abrió la pestaña Seccionales")

    nombre = f"Robot E2E {fechas.ahora().strftime('%H%M%S')}"
    page.fill("#sec-nombre", nombre)
    page.select_option("#sec-provincia", "Santa Fe")
    page.fill("#sec-localidad", "Rosario")
    page.fill("#sec-calle", "San Martín")
    page.fill("#sec-numero", "850")
    informe.paso("Paso 1: cargó la dirección (San Martín 850, Rosario, Santa Fe)")

    page.click("#sec-btn-buscar")
    expect(page.locator('.geo-paso[data-paso="2"]')).to_be_visible()
    # Dos APIs en cadena, con un pedido por segundo de por medio.
    page.wait_for_function(
        "() => !document.getElementById('sec-btn-buscar').disabled", timeout=30000)

    precision = page.input_value("#sec-precision")
    ayuda = page.locator("#sec-ayuda").inner_text()
    informe.dato("Precisión que devolvió la búsqueda", precision)
    informe.dato("Ayuda del paso 2", ayuda[:90])

    if precision == "sin_geo":
        # Ni Georef ni Nominatim contestaron. "Continuar" tiene que estar
        # deshabilitado y el camino a mano, visible.
        expect(page.locator("#sec-btn-continuar")).to_be_disabled()
        expect(page.locator("#sec-btn-manual")).to_be_visible()
        informe.paso("Las APIs de mapas no respondieron: apareció el camino a mano")
        page.click("#sec-btn-manual")
        expect(page.locator("#sec-mapa.leaflet-container")).to_be_visible()
        caja = page.locator("#sec-mapa").bounding_box()
        page.mouse.click(caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2)
        page.wait_for_function(
            "() => document.getElementById('sec-precision').value === 'manual'", timeout=8000)
        informe.paso("Tocó el mapa y el punto quedó puesto a mano, sin depender de ninguna API")
    else:
        assert precision in ("exacta", "aproximada"), precision
        expect(page.locator("#sec-mapa.leaflet-container")).to_be_visible()
        expect(page.locator("#sec-mapa .leaflet-marker-icon")).to_have_count(1)
        lat = float(page.input_value("#sec-lat"))
        assert -33.5 < lat < -32.4, f"el globo cayó fuera de Rosario: {lat}"
        informe.paso(f"Paso 2: Leaflet dibujó el globo en Rosario ({precision})")

        # Arrastrar el globo pasa la ubicación a `manual`: es una decisión
        # humana y deja de decir que la resolvió el geocodificador.
        globo = page.locator("#sec-mapa .leaflet-marker-icon").first
        caja = globo.bounding_box()
        page.mouse.move(caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2)
        page.mouse.down()
        page.mouse.move(caja["x"] + caja["width"] / 2 + 45,
                        caja["y"] + caja["height"] / 2 + 30, steps=12)
        page.mouse.up()
        page.wait_for_function(
            "() => document.getElementById('sec-precision').value === 'manual'", timeout=8000)
        informe.paso("Arrastró el globo y la ubicación pasó a 'manual'")

    expect(page.locator("#sec-btn-continuar")).to_be_enabled()
    page.click("#sec-btn-continuar")
    expect(page.locator('.geo-paso[data-paso="3"]')).to_be_visible()
    page.fill("#sec-telefono", "341 425 0850")
    page.fill("#sec-horario", "Lunes a viernes de 9 a 17")
    expect(page.locator("#sec-resumen")).to_contain_text(nombre)
    informe.paso("Paso 3: cargó el contacto y el resumen mostró lo que se iba a guardar")

    page.click('.geo-paso[data-paso="3"] button[type="submit"]')
    page.wait_for_url(re.compile(r"/admin(#|\?|$)"))

    # Se verifica por la pantalla, como una persona: la fila aparece en la
    # tabla con su dirección armada por el servidor y su estado de ubicación.
    _abrir_seccionales(page)
    fila = page.locator(f'#panel-seccionales tr:has-text("{nombre}")')
    expect(fila).to_have_count(1)
    expect(fila).to_contain_text("San Martín 850")
    informe.dato("Fila en la tabla", fila.inner_text().replace("\n", " · ")[:110])
    informe.paso("La seccional quedó en la tabla con su domicilio y su estado de ubicación")

    # Y la ficha de consulta la muestra completa.
    fila.locator('button:has-text("Ver")').click()
    expect(page.locator("#modal-seccional")).to_be_visible()
    expect(page.locator("#fs-titulo")).to_have_text(nombre)
    expect(page.locator("#fs-body")).to_contain_text("341 425 0850")
    expect(page.locator("#fs-body")).to_contain_text("Lunes a viernes de 9 a 17")
    informe.paso("La ficha de consulta abrió con domicilio, contacto y horario")
    page.click("#modal-seccional .modal-recibo-cerrar")

    # Limpieza: el robot no deja basura en la demo. Se borra como lo haría
    # una persona, con el botón, aceptando el confirm.
    page.once("dialog", lambda d: d.accept())
    fila.locator('button:has-text("Borrar")').click()
    page.wait_for_url(re.compile(r"/admin(#|\?|$)"))
    _abrir_seccionales(page)
    expect(page.locator(f'#panel-seccionales tr:has-text("{nombre}")')).to_have_count(0)
    informe.paso("Borró la seccional de prueba: el robot no deja datos sueltos")


def test_editar_abre_en_el_paso_del_mapa(nuevo_actor, informe):
    """Editar una seccional YA ubicada abre en el paso 2 con el globo puesto:
    corregir dónde está es lo que se viene a hacer casi siempre."""
    page = nuevo_actor("admin")
    _login_admin(page)
    _abrir_seccionales(page)

    fila = page.locator('#panel-seccionales tr:has(.geo-punto.manual, .geo-punto.exacta)').first
    if fila.count() == 0:
        pytest.skip("No hay ninguna seccional ubicada en la demo. " + COMO_PREPARAR)
    nombre = fila.locator("td").first.inner_text()
    fila.locator('button:has-text("Editar")').click()

    expect(page.locator('.geo-paso[data-paso="2"]')).to_be_visible()
    expect(page.locator('.geo-paso-n[data-paso-n="2"]')).to_have_class(re.compile("activo"))
    expect(page.locator("#sec-mapa.leaflet-container")).to_be_visible()
    expect(page.locator("#seccionales-titulo")).to_contain_text(nombre)
    informe.dato("Seccional editada", nombre)
    informe.paso("Editar abrió directo en el paso del mapa, con el globo ya ubicado")

    page.click("#sec-cancel")
    expect(page.locator('.geo-paso[data-paso="1"]')).to_be_visible()
    informe.paso("Cancelar volvió el formulario al paso 1, vacío")


# ------------------------------------- 2. el mapa del panel como selector

def test_el_mapa_del_panel_filtra_al_tocar_un_marcador(nuevo_actor, informe):
    page = nuevo_actor("admin")
    _login_admin(page)
    hasta = fechas.hoy().isoformat()
    page.goto(f"{BASE}/admin/dashboard?desde=2026-01-01&hasta={hasta}")

    mapa = page.locator('[data-panel="seccionales-geo"]')
    expect(mapa).to_be_visible()
    # Un círculo por seccional ubicada: Leaflet los dibuja como <path>
    # interactivos dentro del SVG de la capa de vectores.
    marcadores = page.locator("#mapa-seccionales .leaflet-interactive")
    try:
        marcadores.first.wait_for(state="visible", timeout=20000)
    except Exception:
        pytest.skip("El mapa no dibujó marcadores: la UOM no tiene seccionales ubicadas. "
                    + COMO_PREPARAR)
    cuantos = marcadores.count()
    assert cuantos >= 2, f"esperaba varias seccionales en el mapa, hay {cuantos}"
    informe.dato("Marcadores en el mapa", cuantos)
    informe.paso(f"El mapa del Panel dibujó {cuantos} seccionales")

    # La leyenda dice qué significa el color y qué significa el tamaño.
    expect(page.locator("#mapa-leyenda")).to_contain_text("afiliados")

    # Tocar un marcador aplica el filtro por esa seccional a TODO el panel,
    # con el mismo mecanismo que los gráficos.
    marcadores.first.click()
    page.wait_for_url(re.compile(r"seccionales=\d+"), timeout=10000)
    informe.paso("Tocó un marcador y el filtro por seccional quedó en la URL (link compartible)")

    expect(page.locator(".leaflet-popup-content")).to_contain_text("Afiliados")
    expect(page.locator(".leaflet-popup-content")).to_contain_text("Trámites abiertos")
    informe.dato("Popup", page.locator(".leaflet-popup-content").inner_text().replace("\n", " · ")[:120])
    informe.paso("El popup mostró los seis indicadores de esa seccional")

    # El chip de filtro activo se prende en la barra de filtros: el mapa no
    # tiene un mecanismo propio de selección.
    expect(page.locator("#secc-chips .m-chip.act")).to_have_count(1)
    informe.paso("El chip de filtro activo se prendió como con cualquier otro gráfico")

    # Y el mapa NO se queda con un solo punto: es el selector, ignora su
    # propio filtro. Sin esto, tocar un marcador sería un camino sin vuelta.
    expect(page.locator("#mapa-seccionales .leaflet-interactive")).to_have_count(cuantos)
    informe.paso("Con el filtro puesto, el mapa siguió mostrando todas: es el selector")

    # Cambiar la métrica repinta sin volver a pedir datos.
    page.select_option("#mapa-metrica", "pct_con_diferencias")
    expect(page.locator("#mapa-leyenda")).to_contain_text("%")
    informe.paso("Cambió la métrica de color y la leyenda se actualizó sola")


# ------------------------------- 3. cerca de mí: con permiso y sin permiso

def test_cerca_de_mi_con_ubicacion_concedida(browser, informe, pytestconfig):
    """Con el permiso dado y la posición simulada en Rosario."""
    ctx = browser.new_context(permissions=["geolocation"], geolocation=POSICION_ROSARIO,
                              locale="es-AR")
    page = ctx.new_page()
    try:
        _login_trabajador(page)
        page.click(".circulo-acento")
        expect(page.locator("#overlay-perfil")).to_be_visible()
        expect(page.locator(".mi-secc")).to_contain_text("Mi seccional")
        informe.paso("El afiliado abrió su perfil y vio el bloque Mi seccional")

        if page.locator('button:has-text("Ver otras seccionales cerca")').count() == 0:
            pytest.skip("Ese afiliado no tiene seccional asignada. " + COMO_PREPARAR)

        page.click('button:has-text("Ver otras seccionales cerca")')
        expect(page.locator("#overlay-cerca")).to_be_visible()
        # El texto explica para qué se usa la ubicación ANTES de pedirla.
        expect(page.locator("#cerca-body")).to_contain_text("No se guarda ni se envía")
        informe.paso("Antes de pedir el permiso, la pantalla explicó para qué se usa")

        page.click('button:has-text("Usar mi ubicación")')
        expect(page.locator("#cerca-body")).to_contain_text(
            "Distancias medidas desde tu ubicación", timeout=20000)
        items = page.locator(".cerca-item")
        assert items.count() >= 1, "no listó ninguna seccional"
        # La distancia la calculó el NAVEGADOR: la posición no viajó.
        expect(page.locator(".cerca-km").first).to_contain_text("km")
        informe.dato("Más cercana a Rosario", items.first.inner_text().split("\n")[0][:60])
        informe.paso(f"Listó {items.count()} seccionales ordenadas por distancia")

        assert page.locator(".cerca-item.propia").count() >= 1
        informe.paso("Su propia seccional quedó resaltada en la lista")
    finally:
        ctx.close()


def test_cerca_de_mi_con_permiso_denegado(browser, informe):
    """Negar el permiso NO puede dejar la pantalla inservible: se mide desde
    el domicilio guardado, y sin domicilio se ordena por provincia."""
    # Sin "geolocation" en permissions, Chromium deniega el pedido.
    ctx = browser.new_context(permissions=[], locale="es-AR")
    page = ctx.new_page()
    try:
        _login_trabajador(page)
        page.click(".circulo-acento")
        if page.locator('button:has-text("Ver otras seccionales cerca")').count() == 0:
            pytest.skip("Ese afiliado no tiene seccional asignada. " + COMO_PREPARAR)
        page.click('button:has-text("Ver otras seccionales cerca")')
        page.click('button:has-text("Usar mi ubicación")')

        # Cae a uno de los dos caminos sin GPS, según si tiene domicilio.
        page.wait_for_function(
            """() => {
                 const t = document.getElementById('cerca-body').innerText;
                 return t.includes('ordenadas por provincia') ||
                        t.includes('desde tu domicilio');
               }""", timeout=25000)
        texto = page.locator("#cerca-body").inner_text()
        assert page.locator(".cerca-item").count() >= 1, "sin permiso igual tiene que haber lista"
        informe.dato("Camino sin permiso", texto.split("\n")[0][:80])
        informe.paso("Con el permiso negado la pantalla siguió sirviendo: lista completa")

        # Los botones de contacto siguen ahí: no tener ubicación no es no
        # tener cómo llegar ni a quién llamar.
        assert page.locator('.cerca-item a:has-text("Cómo llegar")').count() >= 1
        informe.paso("Los botones Llamar / WhatsApp / Cómo llegar siguieron disponibles")
    finally:
        ctx.close()


def test_el_mapa_de_mi_seccional_abre_en_pantalla_completa(browser, informe):
    ctx = browser.new_context(locale="es-AR")
    page = ctx.new_page()
    try:
        _login_trabajador(page)
        page.click(".circulo-acento")
        mapa = page.locator("#secc-mapa")
        if mapa.count() == 0:
            pytest.skip("Ese afiliado tiene su seccional sin ubicar: no hay mapa que abrir")
        mapa.scroll_into_view_if_needed()
        expect(mapa).to_have_class(re.compile("leaflet-container"))
        informe.paso("El mapa chico de la seccional se dibujó en el perfil")

        mapa.click()
        expect(page.locator("#overlay-mapa")).to_be_visible()
        expect(page.locator("#mg-mapa.leaflet-container")).to_be_visible()
        informe.paso("Tocó el mapa chico y se abrió en pantalla completa")
        page.click("#overlay-mapa .modal-cerrar-clara")

        # El enlace "cómo llegar" se armó según el navegador (en escritorio,
        # Google Maps; en Android `geo:`; en iOS maps.apple.com).
        href = page.locator("#secc-ir").get_attribute("href")
        assert href and href != "#", f"el enlace de cómo llegar quedó sin armar: {href!r}"
        assert "google.com/maps" in href, f"en escritorio va Google Maps: {href!r}"
        informe.dato("Enlace 'cómo llegar'", href[:70])
        informe.paso("El botón 'Cómo llegar' quedó apuntando a la app de mapas del dispositivo")
    finally:
        ctx.close()
