"""Verificación del Punto 2 del Sprint A (tope sindical 2%, Ley 27.802 art. 133).

Sin dependencias de la API: arma un recibo y un catálogo de conceptos a mano.
Correr con: .venv/Scripts/python.exe test_tope_sindical.py
"""
import validador

CONCEPTOS_BASE = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
     "remunerativo": True, "alias": [], "carga_sindical_convenio": False},
    {"codigo": "AFIL", "nombre": "Cuota de afiliación", "tipo": "descuento",
     "remunerativo": True, "alias": [], "carga_sindical_convenio": False},
    {"codigo": "SOLID", "nombre": "Cuota solidaria de convenio", "tipo": "descuento",
     "remunerativo": True, "alias": [], "carga_sindical_convenio": True},
]


def _recibo(importe_solidaria: float, importe_afiliacion: float = -1000):
    return {
        "empleado": {"cuil": "20111111119"},
        "periodo": "2026-06",
        "lineas": [
            {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 100000, "tipo": "remuneracion"},
            {"codigo": "AFIL", "descripcion": "Cuota de afiliación", "importe": importe_afiliacion, "tipo": "aporte_trabajador"},
            {"codigo": "SOLID", "descripcion": "Cuota solidaria de convenio", "importe": importe_solidaria, "tipo": "aporte_trabajador"},
        ],
        "totales_impresos": {},
    }


def test_supera_el_tope():
    # 2.5% de 100000 = 2500 -> por encima del tope 2% (2000)
    recibo = _recibo(importe_solidaria=-2500)
    r = validador.validar(CONCEPTOS_BASE, [], recibo, tope_sindical_pct=2.0)
    assert len(r["alertas"]) == 1, r["alertas"]
    assert r["alertas"][0]["tipo"] == "tope_sindical"
    print("OK  test_supera_el_tope")


def test_no_supera_el_tope():
    # 1.5% de 100000 = 1500 -> por debajo del tope 2% (2000)
    recibo = _recibo(importe_solidaria=-1500)
    r = validador.validar(CONCEPTOS_BASE, [], recibo, tope_sindical_pct=2.0)
    assert r["alertas"] == [], r["alertas"]
    print("OK  test_no_supera_el_tope")


def test_afiliacion_no_cuenta_para_el_tope():
    # La cuota de afiliación sola, aunque sea grande, no debe disparar la alerta.
    recibo = _recibo(importe_solidaria=0, importe_afiliacion=-5000)
    r = validador.validar(CONCEPTOS_BASE, [], recibo, tope_sindical_pct=2.0)
    assert r["alertas"] == [], r["alertas"]
    print("OK  test_afiliacion_no_cuenta_para_el_tope")


if __name__ == "__main__":
    test_supera_el_tope()
    test_no_supera_el_tope()
    test_afiliacion_no_cuenta_para_el_tope()
    print("\nTodo OK — Punto 2 (tope sindical) pasa sus criterios de aceptación.")
