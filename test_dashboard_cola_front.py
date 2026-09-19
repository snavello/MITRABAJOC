"""Front del Panel Sindical: menos presión sobre el servidor (C4 del cuelgue de
Pruebas del 2026-09-18, docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md).

`refrescar()` de static/dashboard.js disparaba ~13 requests a la vez por cada
cambio de filtro. Ahora salen en una cola de a 4, con debounce de 400 ms, los
contadores de las pestañas inactivas se piden después de los paneles, y un 503
("servidor ocupado") se reintenta en vez de dejar el panel en error.

`enCola` se prueba corriéndola de verdad con Node (se saltea si no está
instalado); el resto son chequeos sobre el código fuente, porque el archivo es
una IIFE atada al DOM y no se puede importar. Lo que cierra el círculo es mirar
la pestaña Network con el panel abierto: nunca más de 4 pedidos en vuelo.

Correr con: .venv/Scripts/python.exe -m pytest test_dashboard_cola_front.py -q
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = (Path(__file__).parent / "static" / "dashboard.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _funcion(nombre):
    m = re.search(rf"  function {nombre}\(.*?\n  \}}\n", JS, re.S)
    assert m, f"no encontré function {nombre} en dashboard.js"
    return m.group(0)


@pytest.mark.skipif(NODE is None, reason="Node no está instalado")
def test_la_cola_nunca_pasa_de_cuatro_en_vuelo_y_termina_todo():
    programa = f"""
    var MAX_EN_VUELO = 4;
    {_funcion("enCola")}
    var vuelo = 0, pico = 0, orden = [];
    function tarea(n, falla) {{
      return function () {{
        vuelo++; pico = Math.max(pico, vuelo); orden.push(n);
        return new Promise(function (ok, no) {{
          setTimeout(function () {{ vuelo--; falla ? no(new Error("x")) : ok(); }}, 5 + (n % 3) * 5);
        }});
      }};
    }}
    var tareas = [];
    for (var i = 0; i < 25; i++) tareas.push(tarea(i, i % 7 === 0));   // algunas fallan
    enCola(tareas, MAX_EN_VUELO).then(function () {{
      var enOrden = orden.every(function (n, k) {{ return n === k; }});
      console.log(JSON.stringify({{ pico: pico, arrancaron: orden.length, enOrden: enOrden, vuelo: vuelo }}));
    }});
    enCola([], 4).then(function () {{ console.log("vacia-ok"); }});
    """
    r = subprocess.run([NODE, "-e", programa], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    salida = r.stdout
    assert "vacia-ok" in salida
    import json
    resumen = json.loads([l for l in salida.splitlines() if l.startswith("{")][0])
    assert resumen["pico"] == 4, resumen
    assert resumen["arrancaron"] == 25 and resumen["enOrden"] and resumen["vuelo"] == 0, resumen
    print("OK  test_la_cola_nunca_pasa_de_cuatro_en_vuelo_y_termina_todo", resumen)


def test_el_refresco_usa_la_cola_y_no_una_rafaga():
    refrescar = _funcion("refrescar")
    assert "Promise.all" not in refrescar, "refrescar() volvió a lanzar todo junto"
    assert "enCola(tareas, MAX_EN_VUELO)" in refrescar
    assert re.search(r"var MAX_EN_VUELO = 4;", JS)
    print("OK  test_el_refresco_usa_la_cola_y_no_una_rafaga")


def test_los_contadores_de_pestanas_inactivas_van_despues_de_los_paneles():
    refrescar = _funcion("refrescar")
    assert refrescar.index("enCola(tareas, MAX_EN_VUELO)") < refrescar.index("enCola(contadores, MAX_EN_VUELO)")
    # ...y ningún pedido de contador sale suelto antes de la cola de paneles.
    antes_de_la_cola = refrescar[:refrescar.index("enCola(tareas, MAX_EN_VUELO)")]
    assert not re.search(r"page_size: 1(?!\d)", antes_de_la_cola)
    print("OK  test_los_contadores_de_pestanas_inactivas_van_despues_de_los_paneles")


def test_debounce_de_400_ms_y_abortador_vigente():
    assert "debounceId = setTimeout(refrescar, 400);" in JS
    refrescar = _funcion("refrescar")
    assert "abortador.abort()" in refrescar and "new AbortController()" in refrescar
    # una tarea que espera turno en una ronda ya abortada no arranca
    assert "if (signal.aborted) return Promise.resolve();" in _funcion("cargarEnCola")
    print("OK  test_debounce_de_400_ms_y_abortador_vigente")


def test_un_503_se_reintenta_y_solo_el_503():
    assert re.search(r"var ESPERA_503_MS = \[\d+, \d+\];", JS)
    pedir = _funcion("pedir")
    assert "r.status === 503 && intento < ESPERA_503_MS.length" in pedir
    print("OK  test_un_503_se_reintenta_y_solo_el_503")
