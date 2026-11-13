"""Verificación del Punto 2 del Sprint A (tope sindical 2%, Ley 27.802 art. 133).

Sin dependencias de la API: arma un recibo y un catálogo de conceptos a mano.
Correr con: .venv/Scripts/python.exe -m pytest test_tope_sindical.py -q
"""
import validador

CONCEPTOS_BASE = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
     "remunerativo": True, "alias": [], "categoria_sindical": ""},
    {"codigo": "AFIL", "nombre": "Cuota de afiliación", "tipo": "descuento",
     "remunerativo": True, "alias": [], "categoria_sindical": "afiliacion"},
    {"codigo": "SOLID", "nombre": "Cuota solidaria de convenio", "tipo": "descuento",
     "remunerativo": True, "alias": [], "categoria_sindical": "convenio"},
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


def test_los_textos_van_en_formato_argentino():
    """El detalle de una regla que no cierra lo lee el afiliado en el paso 3:
    tiene que decir «$ 25.000,00» como la tabla de abajo, no «$25,000.00», y
    la diferencia negativa con el menos delante del signo («-$ 5.000,00»,
    igual que formato_ar.pesos y peso() de trabajador.html)."""
    conceptos = CONCEPTOS_BASE + [
        {"codigo": "UOM", "nombre": "Cuota UOM", "tipo": "descuento",
         "remunerativo": True, "alias": [], "categoria_sindical": ""}]
    formulas = [{"target": "UOM", "descripcion": "Cuota UOM = 2,5% del remunerativo",
                 "expr": "base_remunerativa * 0.025"}]
    recibo = _recibo(importe_solidaria=-2500)
    recibo["lineas"][0]["importe"] = 1000000
    recibo["lineas"].append({"codigo": "UOM", "descripcion": "Cuota UOM",
                             "importe": -20000, "tipo": "aporte_trabajador"})
    r = validador.validar(conceptos, formulas, recibo, tope_sindical_pct=0.2)
    det = [d["detalle"] for d in r["discrepancias"] if d["tipo"] == "formula"]
    assert det == ["Cuota UOM = 2,5% del remunerativo: esperado $ 25.000,00, "
                   "figura $ 20.000,00 (diferencia -$ 5.000,00)."], det
    tope = [a["detalle"] for a in r["alertas"] if a["tipo"] == "tope_sindical"]
    assert tope and "($ 2.500,00, 0,25% de la remuneración)" in tope[0], tope
    assert "tope legal del 0,2% " in tope[0], tope


if __name__ == "__main__":
    test_supera_el_tope()
    test_no_supera_el_tope()
    test_afiliacion_no_cuenta_para_el_tope()
    print("\nTodo OK — Punto 2 (tope sindical) pasa sus criterios de aceptación.")
