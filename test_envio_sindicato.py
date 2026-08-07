"""Verificación del Punto 5B del Sprint B (retención de cuota para el envío al sindicato).

Sin dependencias externas. Correr con: .venv/Scripts/python.exe test_envio_sindicato.py
"""
import validador

CONCEPTOS = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
     "remunerativo": True, "alias": [], "categoria_sindical": ""},
    {"codigo": "AFIL", "nombre": "Cuota de afiliación", "tipo": "descuento",
     "remunerativo": True, "alias": [], "categoria_sindical": "afiliacion"},
    {"codigo": "SOLID", "nombre": "Cuota solidaria de convenio", "tipo": "descuento",
     "remunerativo": True, "alias": [], "categoria_sindical": "convenio"},
]

RECIBO = {
    "empleado": {"cuil": "20111111119"},
    "periodo": "2026-06",
    "lineas": [
        {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 100000, "tipo": "remuneracion"},
        {"codigo": "AFIL", "descripcion": "Cuota de afiliación", "importe": -1000, "tipo": "aporte_trabajador"},
        {"codigo": "SOLID", "descripcion": "Cuota solidaria de convenio", "importe": -1500, "tipo": "aporte_trabajador"},
    ],
    "totales_impresos": {},
}


def test_retencion_sindical_suma_convenio_y_afiliacion():
    r = validador.validar(CONCEPTOS, [], RECIBO, tope_sindical_pct=5.0)  # tope alto: no dispara alerta
    ret = r["retencion_sindical"]
    assert ret["convenio"] == 1500.0, ret
    assert ret["afiliacion"] == 1000.0, ret
    assert ret["total"] == 2500.0, ret
    print("OK  test_retencion_sindical_suma_convenio_y_afiliacion")


def test_retencion_sindical_cero_si_no_hay_conceptos_sindicales():
    conceptos_sin_sindical = [c for c in CONCEPTOS if c["codigo"] != "AFIL" and c["codigo"] != "SOLID"]
    recibo_sin_sindical = {**RECIBO, "lineas": [RECIBO["lineas"][0]]}
    r = validador.validar(conceptos_sin_sindical, [], recibo_sin_sindical)
    assert r["retencion_sindical"] == {"convenio": 0.0, "afiliacion": 0.0, "total": 0.0}
    print("OK  test_retencion_sindical_cero_si_no_hay_conceptos_sindicales")


if __name__ == "__main__":
    test_retencion_sindical_suma_convenio_y_afiliacion()
    test_retencion_sindical_cero_si_no_hay_conceptos_sindicales()
    print("\nTodo OK — Punto 5B (retención de cuota / envío al sindicato) pasa sus criterios.")
