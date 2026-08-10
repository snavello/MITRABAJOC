"""Vigencia por fecha de las fórmulas: un recibo se valida con la fórmula
que regía en SU período (no la actual), sin fórmulas superpuestas para el
mismo concepto, y sin discrepancia si ninguna fórmula estaba vigente.

Correr con: .venv/Scripts/python.exe test_formula_vigencia.py
"""
from validador import formula_vigente_en, rangos_se_superponen, validar


def test_formula_sin_fechas_siempre_vigente():
    f = {"fecha_desde": None, "fecha_hasta": None}
    assert formula_vigente_en(f, "2011-03")
    assert formula_vigente_en(f, "2030-01")
    assert formula_vigente_en(f, None)
    print("OK  test_formula_sin_fechas_siempre_vigente")


def test_formula_con_rango_respeta_limites():
    f = {"fecha_desde": "2020-01-01", "fecha_hasta": "2020-12-31"}
    assert not formula_vigente_en(f, "2019-12")
    assert formula_vigente_en(f, "2020-01")
    assert formula_vigente_en(f, "2020-12")
    assert not formula_vigente_en(f, "2021-01")
    print("OK  test_formula_con_rango_respeta_limites")


def test_formula_hasta_null_es_vigente_hoy_y_a_futuro():
    f = {"fecha_desde": "2021-01-01", "fecha_hasta": None}
    assert formula_vigente_en(f, "2021-01")
    assert formula_vigente_en(f, "2030-06")
    assert not formula_vigente_en(f, "2020-12")
    print("OK  test_formula_hasta_null_es_vigente_hoy_y_a_futuro")


def test_formula_con_limite_sin_periodo_no_vigente():
    # Si la fórmula tiene un límite pero no se sabe el período del recibo,
    # mejor no aplicarla que adivinar.
    f = {"fecha_desde": "2020-01-01", "fecha_hasta": None}
    assert not formula_vigente_en(f, None)
    assert not formula_vigente_en(f, "")
    print("OK  test_formula_con_limite_sin_periodo_no_vigente")


def test_rangos_contiguos_no_se_superponen():
    assert not rangos_se_superponen("2000-01-01", "2010-12-31", "2011-01-01", "2020-12-31")
    print("OK  test_rangos_contiguos_no_se_superponen")


def test_rangos_mismo_mes_limite_se_superponen():
    # Ambos "vigentes" en 2010-12 -> superposición real, debe rechazarse.
    assert rangos_se_superponen("2000-01-01", "2010-12-31", "2010-12-01", "2020-12-31")
    print("OK  test_rangos_mismo_mes_limite_se_superponen")


def test_rango_abierto_se_superpone_con_cualquiera():
    assert rangos_se_superponen(None, None, "2020-01-01", "2020-12-31")
    assert rangos_se_superponen("2021-01-01", None, "2020-01-01", "2020-06-30") is False
    print("OK  test_rango_abierto_se_superpone_con_cualquiera")


def _recibo(periodo, importe_jub):
    return {
        "periodo": periodo,
        "empleado": {"cuil": "20111111119"},
        "empleador": {"nombre": "Empleador", "cuit": None},
        "lineas": [
            {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 1000},
            {"codigo": "JUB", "descripcion": "Aporte jubilatorio", "importe": importe_jub},
        ],
        "totales_impresos": {},
    }


CONCEPTOS = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso", "remunerativo": True,
     "alias": [], "cuit_empleador": None, "codigo_generico": None},
    {"codigo": "JUB", "nombre": "Aporte jubilatorio", "tipo": "descuento", "remunerativo": True,
     "alias": [], "cuit_empleador": None, "codigo_generico": None},
]


def test_validar_usa_la_formula_historica_del_periodo():
    formulas = [
        {"target": "JUB", "descripcion": "Jubilación vieja = 10%", "expr": "0.10 * base_remunerativa",
         "tolerancia": 1.0, "fecha_desde": None, "fecha_hasta": "2015-12-31"},
        {"target": "JUB", "descripcion": "Jubilación nueva = 11%", "expr": "0.11 * base_remunerativa",
         "tolerancia": 1.0, "fecha_desde": "2016-01-01", "fecha_hasta": None},
    ]
    r_viejo = validar(CONCEPTOS, formulas, _recibo("2011-03", -100))
    assert r_viejo["estado"] == "OK", r_viejo["discrepancias"]

    r_nuevo = validar(CONCEPTOS, formulas, _recibo("2026-08", -110))
    assert r_nuevo["estado"] == "OK", r_nuevo["discrepancias"]

    # con la fórmula vieja (10%), un recibo actual con 11% debería marcar diferencia
    r_cruzado = validar(CONCEPTOS, formulas, _recibo("2011-03", -110))
    assert r_cruzado["estado"] == "CON_DISCREPANCIAS"
    print("OK  test_validar_usa_la_formula_historica_del_periodo")


def test_validar_sin_formula_vigente_no_marca_discrepancia():
    formulas = [
        {"target": "JUB", "descripcion": "Jubilación nueva = 11%", "expr": "0.11 * base_remunerativa",
         "tolerancia": 1.0, "fecha_desde": "2016-01-01", "fecha_hasta": None},
    ]
    # período anterior a que exista CUALQUIER fórmula para JUB -> no se chequea
    r = validar(CONCEPTOS, formulas, _recibo("2005-01", -1))
    assert r["estado"] == "OK"
    assert r["formulas_validadas"] == []
    assert r["discrepancias"] == []
    print("OK  test_validar_sin_formula_vigente_no_marca_discrepancia")


if __name__ == "__main__":
    test_formula_sin_fechas_siempre_vigente()
    test_formula_con_rango_respeta_limites()
    test_formula_hasta_null_es_vigente_hoy_y_a_futuro()
    test_formula_con_limite_sin_periodo_no_vigente()
    test_rangos_contiguos_no_se_superponen()
    test_rangos_mismo_mes_limite_se_superponen()
    test_rango_abierto_se_superpone_con_cualquiera()
    test_validar_usa_la_formula_historica_del_periodo()
    test_validar_sin_formula_vigente_no_marca_discrepancia()
    print("\nTodo OK — vigencia por fecha de las fórmulas.")
