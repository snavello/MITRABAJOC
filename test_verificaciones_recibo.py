"""Verificación de: (1) Total neto = ingresos - descuentos, (2) el CUIL del
recibo debe coincidir con el CUIL de la sesión que lo está verificando.
Sin dependencias externas. Correr con: .venv/Scripts/python.exe test_verificaciones_recibo.py
"""
import validador

CONCEPTOS = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
     "remunerativo": True, "alias": [], "categoria_sindical": ""},
    {"codigo": "JUB", "nombre": "Aporte jubilatorio", "tipo": "descuento",
     "remunerativo": True, "alias": [], "categoria_sindical": ""},
]


def _recibo(cuil="20111111119"):
    return {
        "empleado": {"cuil": cuil},
        "periodo": "2026-06",
        "lineas": [
            {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 100000, "tipo": "remuneracion"},
            {"codigo": "JUB", "descripcion": "Aporte jubilatorio", "importe": -11000, "tipo": "aporte_trabajador"},
        ],
        "totales_impresos": {},
    }


def test_total_neto_es_ingresos_menos_descuentos():
    r = validador.validar(CONCEPTOS, [], _recibo(), cuil_sesion="20111111119")
    assert r["totales"]["ingresos"] == 100000.0
    assert r["totales"]["descuentos"] == 11000.0
    assert r["totales"]["neto"] == 89000.0
    print("OK  test_total_neto_es_ingresos_menos_descuentos")


def test_cuil_no_coincide_genera_discrepancia():
    r = validador.validar(CONCEPTOS, [], _recibo(cuil="20999999999"), cuil_sesion="20111111119")
    assert r["estado"] == "CON_DISCREPANCIAS", r
    tipos = [d["tipo"] for d in r["discrepancias"]]
    assert "cuil_no_coincide" in tipos, r["discrepancias"]
    print("OK  test_cuil_no_coincide_genera_discrepancia")


def test_cuil_coincide_no_genera_discrepancia():
    r = validador.validar(CONCEPTOS, [], _recibo(cuil="20111111119"), cuil_sesion="20-11111111-9")
    assert r["estado"] == "OK", r
    print("OK  test_cuil_coincide_no_genera_discrepancia")


def test_sin_cuil_sesion_no_rompe():
    # /api/validar siempre exige sesión, pero el validador no debe explotar
    # si por algún motivo no se pasa cuil_sesion.
    r = validador.validar(CONCEPTOS, [], _recibo(), cuil_sesion=None)
    assert r["estado"] == "OK", r
    print("OK  test_sin_cuil_sesion_no_rompe")


if __name__ == "__main__":
    test_total_neto_es_ingresos_menos_descuentos()
    test_cuil_no_coincide_genera_discrepancia()
    test_cuil_coincide_no_genera_discrepancia()
    test_sin_cuil_sesion_no_rompe()
    print("\nTodo OK — total neto y verificación de CUIL.")
