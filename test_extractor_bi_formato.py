"""Verificación del Punto 1 del Sprint A (extractor bi-formato).

No llama a la API real: mockea extractor.client.messages.create con dos
fixtures fijas (un recibo clásico y uno Anexo III) y valida el contrato del
JSON de salida. Correr con: .venv/Scripts/python.exe test_extractor_bi_formato.py
"""
import json
from types import SimpleNamespace

import extractor
import validador

CLASICO = {
    "formato": "clasico",
    "empleado": {"apellido_nombre": "Pérez, Juan", "cuil": "20111111119", "legajo": "45",
                 "categoria": "Oficial", "fecha_ingreso": "2018-03-01"},
    "empleador": {"nombre": "Metalúrgica SA", "cuit": "30-11111111-1"},
    "periodo": "2026-06",
    "fecha_pago": "05/07/2026",
    "lineas": [
        {"codigo": "SUELDO", "descripcion": "Sueldo básico", "cantidad": 30, "unidad": "días", "importe": 500000, "tipo": "remuneracion"},
        {"codigo": "PRESENT", "descripcion": "Presentismo", "cantidad": None, "unidad": None, "importe": 50000, "tipo": "remuneracion"},
        {"codigo": "JUB", "descripcion": "Aporte jubilatorio", "cantidad": None, "unidad": "11%", "importe": -60500, "tipo": "aporte_trabajador"},
        {"codigo": "SINDMET", "descripcion": "Cuota sindical UOM", "cantidad": None, "unidad": None, "importe": -8250, "tipo": "aporte_trabajador"},
    ],
    "totales_impresos": {"remuneraciones": 550000, "descuentos": -68750, "neto": 481250},
    "contribuciones_patronales": [],
    "costo_laboral_total": None,
    "ultimo_deposito": None,
    "confianza": "alta",
    "observaciones": None,
}

NUEVO = {
    "formato": "nuevo",
    "empleado": {"apellido_nombre": "Gómez, Ana", "cuil": "27222222224", "legajo": "12",
                 "categoria": "Mozo", "fecha_ingreso": "2020-01-15"},
    "empleador": {"nombre": "Restaurante SRL", "cuit": "30-22222222-2"},
    "periodo": "2026-06",
    "fecha_pago": "05/07/2026",
    "lineas": [
        {"codigo": "SUELDO", "descripcion": "Sueldo Básico", "cantidad": 30, "unidad": "días", "importe": 400000, "tipo": "remuneracion"},
        {"codigo": "JUB", "descripcion": "Aporte Jubilación", "cantidad": None, "unidad": "11%", "importe": -44000, "tipo": "aporte_trabajador"},
        {"codigo": "LEY19032", "descripcion": "Ley 19.032", "cantidad": None, "unidad": "3%", "importe": -12000, "tipo": "aporte_trabajador"},
        {"codigo": "OOSS", "descripcion": "Obra Social", "cantidad": None, "unidad": "3%", "importe": -12000, "tipo": "aporte_trabajador"},
    ],
    "totales_impresos": {"remuneraciones": 400000, "descuentos": -68000, "neto": 332000},
    "contribuciones_patronales": [
        {"concepto": "ART", "base": 400000, "porcentaje": "3%", "importe": 12000},
        {"concepto": "Contribución Jubilación", "base": 400000, "porcentaje": "18%", "importe": 72000},
        {"concepto": "Contribución OO.SS.", "base": 400000, "porcentaje": "6%", "importe": 24000},
        {"concepto": "Seguro de vida fijo", "base": None, "porcentaje": None, "importe": 500},
    ],
    "costo_laboral_total": 508500,
    "ultimo_deposito": {"fecha": "10/06/2026", "periodo": None, "banco": None},
    "confianza": "alta",
    "observaciones": None,
}


def _mock_response(payload: dict):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def _run_extraer_con_mock(payload: dict) -> dict:
    original = extractor.client.messages.create
    extractor.client.messages.create = lambda **kw: _mock_response(payload)
    try:
        return extractor.extraer(b"fake-bytes", "image/png")
    finally:
        extractor.client.messages.create = original


CONCEPTOS_UOM = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso", "remunerativo": True, "alias": []},
    {"codigo": "PRESENT", "nombre": "Presentismo", "tipo": "ingreso", "remunerativo": True, "alias": []},
    {"codigo": "JUB", "nombre": "Aporte jubilatorio", "tipo": "descuento", "remunerativo": True, "alias": ["Aporte Jubilación"]},
    {"codigo": "SINDMET", "nombre": "Cuota sindical UOM", "tipo": "descuento", "remunerativo": True, "alias": []},
    {"codigo": "LEY19032", "nombre": "Ley 19.032", "tipo": "descuento", "remunerativo": True, "alias": []},
    {"codigo": "OOSS", "nombre": "Obra Social", "tipo": "descuento", "remunerativo": True, "alias": []},
]
FORMULAS_UOM = []


def test_clasico():
    r = _run_extraer_con_mock(CLASICO)
    assert r["formato"] == "clasico", r["formato"]
    assert r["contribuciones_patronales"] == []
    assert r["costo_laboral_total"] is None
    assert all("tipo" in ln for ln in r["lineas"])
    # No regresión: validador.py corre igual que antes sobre este JSON.
    resultado = validador.validar(CONCEPTOS_UOM, FORMULAS_UOM, r)
    assert resultado["estado"] == "OK", resultado
    print("OK  test_clasico")


def test_nuevo():
    r = _run_extraer_con_mock(NUEVO)
    assert r["formato"] == "nuevo", r["formato"]
    assert len(r["contribuciones_patronales"]) == 4
    assert r["costo_laboral_total"] == 508500
    assert r["ultimo_deposito"]["fecha"] == "10/06/2026"

    conceptos_patronales = {c["concepto"] for c in r["contribuciones_patronales"]}
    aportes_trabajador = {ln["descripcion"] for ln in r["lineas"] if ln["tipo"] == "aporte_trabajador"}
    interseccion = conceptos_patronales & aportes_trabajador
    assert not interseccion, f"Contribución patronal filtrada como aporte del trabajador: {interseccion}"

    resultado = validador.validar(CONCEPTOS_UOM, FORMULAS_UOM, r)
    assert resultado["estado"] == "OK", resultado
    print("OK  test_nuevo")


if __name__ == "__main__":
    test_clasico()
    test_nuevo()
    print("\nTodo OK — Punto 1 (extractor bi-formato) pasa sus criterios de aceptación.")
