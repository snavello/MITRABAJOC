"""Servidor LOCAL para filmar el paso de «Conceptos desde los recibos de muestra» del tutorial.
Levanta la app con la lectura simulada (MOCK_EXTRACTOR=1) pero reemplaza `main.extraer` para que cada
recibo de ejemplo devuelva conceptos DISTINTOS (el simulado de siempre devuelve el mismo recibo para
cualquier archivo y la revisión quedaría pobre). Todo inventado: empleadores, CUIT (válidos por módulo 11)
y conceptos. Uso:  MOCK_EXTRACTOR=1 ENTORNO=local .venv/bin/python docs/xsii/tutorial/servidor_recibos.py 8765"""
import hashlib
import io
import os
import sys
import time

os.environ["MOCK_EXTRACTOR"] = "1"
os.environ.setdefault("ENTORNO", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import uvicorn  # noqa: E402

import extractor  # noqa: E402
import main  # noqa: E402

DELTA = {"nombre": "Banco Delta SA", "cuit": "30700001004"}
NORTE = {"nombre": "Banco del Norte SA", "cuit": "30700001012"}
SUR = {"nombre": "Banco Austral SA", "cuit": "30700001020"}


def _l(cod, desc, imp, tipo, sec):
    return {"codigo": cod, "descripcion": desc, "cantidad": None, "unidad": None, "importe": imp,
            "tipo": tipo, "seccion": sec, "categoria_universal": None}


BASICO = _l("SUELDO", "Sueldo básico", 1000000, "remuneracion", "haberes")
JUB = _l("JUB", "Aporte jubilatorio", -110000, "aporte_trabajador", "descuentos")
EXTRA = _l("101", "Horas extra 50%", 120000, "remuneracion", "haberes")
TURNO = _l("102", "Adicional por turno rotativo", 90000, "remuneracion", "haberes")
PRES = _l("105", "Presentismo mensual", 83000, "remuneracion", "haberes")
PRES_MAL = _l("105", "Presentismo mensual", 83000, "remuneracion", "no_remunerativos")  # la IA lo leyó en otra sección
VIAT = _l("130", "Bonificación por transporte", 40000, "remuneracion", "no_remunerativos")
SOLID = _l("210", "Aporte solidario", -25000, "aporte_trabajador", "descuentos")
SEPEL = _l("220", "Seguro de sepelio", -8000, "aporte_trabajador", "descuentos")
PREST = _l("230", "Cuota préstamo mutual", -30000, "aporte_trabajador", "descuentos")

RECIBOS = {  # semilla del archivo -> (empleador, líneas)
    "r1": (DELTA, [BASICO, EXTRA, TURNO, PRES_MAL, JUB, SOLID, SEPEL]),
    "r2": (DELTA, [BASICO, EXTRA, TURNO, VIAT, JUB, SOLID]),
    "r3": (NORTE, [BASICO, EXTRA, VIAT, JUB, SOLID, PREST]),
    "r4": (SUR, [BASICO, TURNO, JUB, PREST]),
    "r5": None,  # no se puede leer
}


def falsa(contenido, content_type, modelo=None, imagen=None, aviso_enmascarado=False):
    time.sleep(float(os.getenv("TUTORIAL_LATENCIA", "3")))
    clave = None
    for k in RECIBOS:
        if contenido.startswith(b"\x89PNG") and b"k\x00" + k.encode() in contenido:
            clave = k
    spec = RECIBOS.get(clave)
    if spec is None:
        raise ValueError("lectura ilegible (simulada)")
    emp, lineas = spec
    r = extractor.json.loads(extractor.json.dumps(extractor._RECIBO_MOCK))
    r["empleador"] = dict(emp)
    r["lineas"] = [dict(x) for x in lineas]
    return r, extractor._uso_mock(time.perf_counter())


main.extraer = falsa

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765, log_level="warning")
