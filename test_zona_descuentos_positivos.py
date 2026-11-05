"""Aportes del trabajador impresos en positivo en la columna Descuentos, con la
sección mal leída (haberes / no_remunerativos / null): son descuentos, no
ingresos (validador._zona_leida). Caso real: BBVA 20209792630_2025-10 del lote
bancario (2026-11-05), con total de descuentos impreso 972.900.

Correr con: python -m pytest test_zona_descuentos_positivos.py -q
"""
import pytest

import validador

APORTES = [
    ("501", "JUBILACION", 560450.00, "jubilacion"),
    ("502", "OBRA SOCIAL", 152850.00, "obra_social"),
    ("503", "PAMI INSSJP", 152850.00, "pami"),
    ("510", "CUOTA SINDICAL", 101900.00, "cuota_sindical"),
    ("520", "SEGURO", 4850.00, None),
]


def _recibo(secciones):
    lineas = [{"codigo": "100", "descripcion": "SUELDO BASICO", "importe": 5215000.00,
               "tipo": "remuneracion", "seccion": "haberes", "categoria_universal": None}]
    for (c, d, i, cat), sec in zip(APORTES, secciones):
        lineas.append({"codigo": c, "descripcion": d, "importe": i,
                       "tipo": "aporte_trabajador", "seccion": sec,
                       "categoria_universal": cat})
    return {"lineas": lineas,
            "totales_impresos": {"remuneraciones": 5215000.00, "descuentos": 972900.00,
                                 "neto": 4242100.00}}


@pytest.mark.parametrize("secciones", [
    ["haberes", "no_remunerativos", "haberes", None, "haberes"],
    [None] * 5,
    ["descuentos"] * 5,
])
def test_aportes_positivos_son_descuentos(secciones):
    t = validador.totales_leidos(_recibo(secciones))
    assert t["ingresos"] == 5215000.00
    assert t["descuentos"] == 972900.00
    assert t["reintegros"] == 0
    assert t["neto"] == 4242100.00


def test_reintegro_entre_los_descuentos_sigue_siendo_reintegro():
    r = _recibo(["descuentos"] * 5)
    for ln in r["lineas"][1:]:
        ln["importe"] = -ln["importe"]
    r["lineas"].append({"codigo": "433", "descripcion": "DEVOLUCION GANANCIAS",
                        "importe": 1000.0, "tipo": "otro", "seccion": "descuentos",
                        "categoria_universal": None})
    t = validador.totales_leidos(r)
    assert t["descuentos"] == 972900.00
    assert t["reintegros"] == 1000.0
    assert t["ingresos"] == 5215000.00


def test_aporte_negativo_en_haberes_no_se_reclasifica():
    r = _recibo(["haberes"] * 5)
    for ln in r["lineas"][1:]:
        ln["importe"] = -ln["importe"]
    assert validador.totales_leidos(r)["descuentos"] == 0
