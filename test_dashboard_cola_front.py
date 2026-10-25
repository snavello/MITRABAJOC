"""Front del Panel Sindical: menos presión sobre el servidor (C4 del cuelgue de
Pruebas del 2026-09-18, docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md).

El refresco del panel disparaba ~13 requests a la vez por cada cambio de
filtro. Desde entonces salen en una cola de a 4, con una espera de 400 ms
después del último cambio, los contadores de las pestañas inactivas se piden
después de los paneles, y un 503 ("servidor ocupado") se reintenta en vez de
dejar el panel en error.

La v1 (static/dashboard.js) se retiró el 2026-10-25: estas reglas se miran
ahora en el panel de siempre, static/panel_v2/. La cola y el reintento se
CORREN de verdad con Node en test_dashboard_v2_nucleo.py (`enCola`, `pedir`);
acá se fija que la ronda de app.js los use. Lo que cierra el círculo es mirar
la pestaña Network con el panel abierto: nunca más de 4 pedidos en vuelo.

Correr con: .venv/bin/python -m pytest test_dashboard_cola_front.py -q
"""
import re
from pathlib import Path

CARPETA = Path(__file__).parent / "static" / "panel_v2"
APP = (CARPETA / "app.js").read_text(encoding="utf-8")
API = (CARPETA / "api.js").read_text(encoding="utf-8")


def _refrescar():
    m = re.search(r"const refrescar = useCallback\(\(\) => \{.*?\n  \}, \[", APP, re.S)
    assert m, "no encontré refrescar en static/panel_v2/app.js"
    return m.group(0)


def test_el_refresco_usa_la_cola_y_no_una_rafaga():
    refrescar = _refrescar()
    assert "Promise.all" not in refrescar, "refrescar volvió a lanzar todo junto"
    assert "enCola(tareas, MAX_EN_VUELO)" in refrescar
    assert re.search(r"export const MAX_EN_VUELO = 4;", API)
    print("OK  test_el_refresco_usa_la_cola_y_no_una_rafaga")


def test_los_contadores_de_pestanas_inactivas_van_despues_de_los_paneles():
    refrescar = _refrescar()
    cola = refrescar.index("enCola(tareas, MAX_EN_VUELO)")
    assert cola < refrescar.index('q.set("page_size", 1)')
    # ...y ningún pedido de contador sale suelto antes de la cola de paneles.
    assert not re.search(r"page_size\D{0,4}1(?!\d)", refrescar[:cola])
    print("OK  test_los_contadores_de_pestanas_inactivas_van_despues_de_los_paneles")


def test_espera_de_400_ms_y_abortador_vigente():
    assert "const ESPERA_MS = 400;" in APP
    assert "setTimeout(refrescar, ESPERA_MS)" in APP
    refrescar = _refrescar()
    assert "ronda.current.abort()" in refrescar and "new AbortController()" in refrescar
    # una tarea que espera turno en una ronda ya abortada no arranca
    assert "if (ac.signal.aborted) return Promise.resolve();" in refrescar
    print("OK  test_espera_de_400_ms_y_abortador_vigente")


def test_un_503_se_reintenta_y_solo_el_503():
    assert re.search(r"export const ESPERA_503_MS = \[\d+, \d+\];", API)
    assert "r.status === 503 && intento < ESPERA_503_MS.length" in API
    print("OK  test_un_503_se_reintenta_y_solo_el_503")
