"""Cupo del Panel Sindical (C3 del cuelgue de Pruebas del 2026-09-18,
docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md).

Cada refresco del panel dispara ~13 requests y el servidor termina cada query
aunque el navegador ya la haya cancelado. Sin un tope, esa ráfaga ocupaba los
hilos del threadpool que la app comparte con el login y con todo lo demás. El
cupo limita cuántos endpoints de agregados corren a la vez en el proceso, y al
que no entra le contesta un 503 rápido con JSON.

Se prueba que: el cupo por defecto es 4; con 20 pedidos simultáneos corren a
lo sumo 4 a la vez y el resto recibe 503 (E-SERVIDOR-03) sin esperar de más;
el login sigue respondiendo con el panel saturado; un pedido sin sesión o
mal formado NO gasta un lugar; el detalle ("Ver") y el asistente quedan
afuera del cupo; y un endpoint que revienta devuelve su lugar.

Nota: TestClient arma un event loop (y por eso un threadpool) por cliente, así
que acá no se reproduce que los 40 hilos de la app sean compartidos; lo que se
prueba es el mecanismo que evita llegar a eso.

Correr con: .venv/Scripts/python.exe -m pytest test_dashboard_cupo.py -q
"""
import os
import threading
import time

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import fechas
import dashboard
import main
from db import Sindicato, UsuarioSindicato
from fastapi.testclient import TestClient

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="Cupo Dash", slug="cupo-dash", color_base="#0f1b2d",
                     modulos_habilitados=["dashboard"])
    s.add(sind)
    s.commit()
    s.refresh(sind)
    s.add(UsuarioSindicato(sindicato_id=sind.id, usuario="20666666660", nombre="Admin Cupo",
                           clave_hash=auth.hashear_clave("c-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

_login = TestClient(main.app)
_login.post("/admin/login", data={"usuario": "20666666660", "clave": "c-demo"})
COOKIES = dict(_login.cookies)
assert COOKIES, "el login del admin de prueba no dejó cookie"

HOY = fechas.hoy().isoformat()
PARAMS = {"desde": HOY, "hasta": HOY}
RUTA = "/admin/dashboard/validacion"


def _cliente(con_sesion=True):
    return TestClient(main.app, cookies=COOKIES if con_sesion else None,
                      raise_server_exceptions=False)


def test_el_cupo_por_defecto_es_cuatro():
    assert main.CUPO_PANEL == 4
    assert main._cupo_panel_semaforo._value == 4
    print("OK  test_el_cupo_por_defecto_es_cuatro")


def test_veinte_pedidos_simultaneos_corren_de_a_cuatro_y_el_resto_recibe_503():
    original_fn, original_espera = dashboard.validacion, main.CUPO_PANEL_ESPERA
    main.CUPO_PANEL_ESPERA = 0.5            # que el test no espere 2 s por pedido
    corriendo, pico, lock = [0], [0], threading.Lock()

    def _lenta(sid, f):
        with lock:
            corriendo[0] += 1
            pico[0] = max(pico[0], corriendo[0])
        time.sleep(1.5)
        with lock:
            corriendo[0] -= 1
        return {"ok": 0, "con_diferencias": 0}

    dashboard.validacion = _lenta
    resultados = []

    def pedir():
        t = time.monotonic()
        r = _cliente().get(RUTA, params=PARAMS)
        with lock:
            resultados.append((r.status_code, time.monotonic() - t,
                               (r.json() or {}).get("codigo") if r.status_code == 503 else None))

    login = []

    def ingresar():
        t = time.monotonic()
        r = _cliente(con_sesion=False).get("/ingresar")
        login.append((r.status_code, time.monotonic() - t))

    try:
        hilos = [threading.Thread(target=pedir) for _ in range(20)]
        for h in hilos:
            h.start()
        time.sleep(0.2)                     # el panel ya está saturado
        hl = threading.Thread(target=ingresar)
        hl.start()
        for h in hilos + [hl]:
            h.join(timeout=30)
    finally:
        dashboard.validacion = original_fn
        main.CUPO_PANEL_ESPERA = original_espera

    ok = [r for r in resultados if r[0] == 200]
    ocupados = [r for r in resultados if r[0] == 503]
    print(f"{len(ok)} 200, {len(ocupados)} 503, pico de {pico[0]} corriendo a la vez; "
          f"/ingresar: {login}")
    assert len(resultados) == 20
    assert pico[0] <= 4, f"corrieron {pico[0]} a la vez con un cupo de 4"
    assert len(ok) == 4 and len(ocupados) == 16, (len(ok), len(ocupados))
    assert all(r[2] == "E-SERVIDOR-03" for r in ocupados)
    assert max(r[1] for r in ocupados) < 1.5, "un 503 tiene que llegar antes de que termine el que corre"
    assert login and login[0][0] == 200 and login[0][1] < 1, login
    assert main._cupo_panel_semaforo._value == 4, "el cupo no volvió a quedar completo"
    print("OK  test_veinte_pedidos_simultaneos_corren_de_a_cuatro_y_el_resto_recibe_503")


def test_sin_sesion_o_mal_formado_no_gastan_lugar():
    tomados = [main._cupo_panel_semaforo.acquire() for _ in range(main.CUPO_PANEL)]
    assert all(tomados)
    try:
        assert _cliente(con_sesion=False).get(RUTA, params=PARAMS).status_code == 403
        assert _cliente().get(RUTA, params={"desde": "no-es-fecha", "hasta": HOY}).status_code == 422
        # Con el cupo lleno, un pedido válido sí es 503...
        original_espera = main.CUPO_PANEL_ESPERA
        main.CUPO_PANEL_ESPERA = 0.1
        try:
            assert _cliente().get(RUTA, params=PARAMS).status_code == 503
        finally:
            main.CUPO_PANEL_ESPERA = original_espera
        # ...pero el detalle no entra en el cupo: llega a su 404 de siempre.
        assert _cliente().get("/admin/dashboard/detalle/recibo/999999").status_code == 404
    finally:
        for _ in tomados:
            main._cupo_panel_semaforo.release()
    print("OK  test_sin_sesion_o_mal_formado_no_gastan_lugar")


def test_un_endpoint_que_revienta_devuelve_su_lugar():
    original_fn = dashboard.validacion

    def _rota(sid, f):
        raise ValueError("boom")

    dashboard.validacion = _rota
    try:
        for _ in range(6):                  # más que el cupo: si no devolviera, ya se habría trabado
            assert _cliente().get(RUTA, params=PARAMS).status_code == 500
    finally:
        dashboard.validacion = original_fn
    assert main._cupo_panel_semaforo._value == main.CUPO_PANEL
    assert _cliente().get(RUTA, params=PARAMS).status_code == 200
    print("OK  test_un_endpoint_que_revienta_devuelve_su_lugar")
