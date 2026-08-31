# -*- coding: utf-8 -*-
"""Robot E2E: el ciclo de vida completo de un trámite, con dos personas.

Guion (pedido de Sd, 2026-08-31):
  ACTO 1 -- Un trabajador de AEFIP entra a su app, busca un trámite
            relacionado con guardería, completa el formulario y lo envía.
  ACTO 2 -- Un admin del sindicato entra, ve el globo de trámites nuevos,
            abre el expediente, responde afirmativamente por el chat y lo
            termina.
  ACTO 3 -- El mismo trabajador vuelve, busca su expediente y ve el
            detalle con la respuesta del sindicato y el trámite cerrado.

Prerequisitos (los datos los garantiza el fixture entorno_aefip):
    docker compose up -d
    uvicorn main:app --reload
    python cargar_lote_sindicato.py --sindicato "AEFIP"   # una vez

Correr:  .venv/Scripts/python.exe -m pytest e2e/test_robot_tramite_guarderia.py -q

Cada corrida crea UN trámite nuevo (queda en la base local como un caso
más del lote; no ensucia nada que un --limpiar no borre).
"""
import os
import re

from playwright.sync_api import expect

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")

RESPUESTA_ADMIN = ("Aprobado: el reintegro de guardería corresponde según el convenio. "
                   "Se acredita con la próxima liquidación.")
JARDIN = "Jardín Rayito de Sol"


def test_flujo_tramite_guarderia(nuevo_actor, entorno_aefip, informe):
    # Dos sesiones de navegador independientes, como dos personas reales
    # (nuevo_actor las graba si se corre con --video / --tracing).
    trab = nuevo_actor("trabajador")
    admin = nuevo_actor("admin")

    # ================= ACTO 1: el trabajador presenta el trámite =========
    trab.bring_to_front()   # con --headed, que se vea quién está actuando
    creds = entorno_aefip["trabajador"]
    trab.goto(f"{BASE}/ingresar")
    trab.fill('input[name="cuil"]', creds["cuil"])
    trab.fill('input[name="clave"]', creds["clave"])
    trab.click('button[type="submit"]')
    trab.wait_for_url("**/app/inicio")
    informe.paso(f"El trabajador ({creds['nombre']}) entró a su app con CUIL y clave")
    informe.dato("Trabajador", f"{creds['nombre']} · CUIL {creds['cuil']}")

    trab.goto(f"{BASE}/app?tab=tramites")
    trab.click("#tram-nuevo")

    # "Busca algún trámite relacionado con guardería": elige por el texto.
    tarjeta = trab.locator("#tram-tipos-lista button",
                           has_text=re.compile("guarder", re.I)).first
    tarjeta.wait_for(state="visible", timeout=10000)
    informe.paso(f'Buscó y eligió el trámite de guardería: "{tarjeta.inner_text().splitlines()[0]}"')
    tarjeta.click()

    # Completa el formulario campo por campo, según la etiqueta.
    campos = trab.locator("#tram-form-campos .campo-tram")
    for i in range(campos.count()):
        campo = campos.nth(i)
        etiqueta = campo.locator("label").inner_text().lower()
        entrada = campo.locator("input, select, textarea").first
        if "edad" in etiqueta:
            entrada.fill("4")
        elif "monto" in etiqueta:
            entrada.fill("185000")
        elif "nombre" in etiqueta:
            entrada.fill("Martina Gómez")
        else:
            entrada.fill(JARDIN)
    trab.click("#tram-form-enviar")

    # El envío abre el detalle con el número de expediente real.
    expect(trab.locator("#tram-det-expediente")).to_contain_text("-", timeout=15000)
    encabezado = trab.locator("#tram-det-expediente").inner_text()
    numero = re.search(r"[A-Z0-9]+-\d{4}-\d{6}", encabezado).group(0)
    assert "GUARD" in numero, f"El expediente no es del tipo guardería: {numero}"
    informe.paso(f"Completó el formulario (hijo/a, edad, jardín, monto) y lo envió → {numero}")
    informe.dato("Expediente generado", numero)
    informe.dato("Formulario", "Martina Gómez · 4 años · " + JARDIN + " · $185.000")

    # ================= ACTO 2: el admin responde y cierra ================
    admin.bring_to_front()
    creds = entorno_aefip["admin"]
    admin.goto(f"{BASE}/admin")
    admin.fill('input[name="usuario"]', creds["usuario"])
    admin.fill('input[name="clave"]', creds["clave"])
    admin.click('button[type="submit"]')
    admin.wait_for_url("**/admin/inicio")

    # Ve la notificación de trámites nuevos (globo en la pestaña).
    admin.goto(f"{BASE}/admin")
    badge = admin.locator("#badge-tramites-nuevos-tab")
    expect(badge).to_be_visible()
    pendientes = int(re.sub(r"[^0-9]", "", badge.inner_text()) or 0)
    assert pendientes >= 1
    informe.paso(f"El admin entró y vio el globo de trámites nuevos ({pendientes} sin abrir)")

    # Entra a Trámites, encuentra el expediente recién presentado.
    admin.click('.tab-btn[data-panel="tramites"]')
    admin.fill("#f-tramites-nombre", numero)
    fila = admin.locator(f'tr.fila-tramite[data-nombre="{numero}"]')
    expect(fila).to_be_visible()
    expect(fila).to_contain_text("Iniciado")
    fila.get_by_role("button", name="Ver").click()

    # El detalle muestra el formulario que completó el trabajador.
    expect(admin.locator("#mt-contenido")).to_contain_text(JARDIN, timeout=10000)
    expect(admin.locator("#mt-contenido")).to_contain_text("Conversación")
    informe.paso("Abrió el expediente y verificó que el formulario llegó completo")

    # Contesta afirmativamente por el chat...
    admin.click(".tram-chat-responder")
    admin.fill("#mmt-nota-texto", RESPUESTA_ADMIN)
    admin.locator('#mmt-form-nota button[type="submit"]').click()
    expect(admin.locator("#mt-contenido")).to_contain_text("Aprobado", timeout=10000)
    informe.paso("Respondió afirmativamente por el chat del trámite")
    informe.dato("Respuesta del sindicato", RESPUESTA_ADMIN)

    # ...y cierra el trámite.
    admin.click(".tram-chat-responder")
    admin.select_option("#mmt-estado-select", "terminado")
    admin.get_by_role("button", name="Actualizar estado").click()
    expect(admin.locator("#mt-contenido")).to_contain_text("Trámite terminado", timeout=10000)
    expect(fila).to_contain_text("Terminado")
    informe.paso("Cerró el expediente: el estado pasó a Terminado")

    # ================= ACTO 3: el trabajador ve respuesta y cierre =======
    trab.bring_to_front()
    trab.goto(f"{BASE}/app?tab=tramites")
    trab.fill("#tram-buscar-input", numero)
    trab.click("#tram-buscar-btn")
    expect(trab.locator("#tram-det-expediente")).to_contain_text(numero, timeout=10000)
    detalle = trab.locator("#tram-det-contenido")
    expect(detalle).to_contain_text(JARDIN)              # su formulario
    expect(detalle).to_contain_text("Aprobado")          # la respuesta del sindicato
    # Trámite terminado: ya no se le ofrece seguir escribiendo.
    expect(trab.locator(".tram-chat-responder")).to_have_count(0)
    informe.paso("El trabajador volvió, buscó su expediente y vio la respuesta del sindicato")
    informe.paso("Verificado que el trámite quedó cerrado (ya no puede seguir escribiendo)")
    informe.dato("Estado final", "Terminado")
