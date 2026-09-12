"""Aportes de ley (jubilación, PAMI, obra social) identificados por la IA vía
categoria_universal: red de seguridad para un empleador sin catálogo propio,
y auto-vinculación en Aprendizaje. La cuota sindical NO se autogenera.

Correr con: .venv/Scripts/python.exe -m pytest test_categorias_universales.py -q
"""
from validador import (matchear_lineas, indexar_conceptos, validar,
                        detectar_nuevos, CATEGORIAS_UNIVERSALES, CONCEPTOS_UNIVERSALES)

CUIT_NUEVO = "30999999998"

GENERICOS = [
    {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)", "tipo": "descuento",
     "remunerativo": True, "alias": ["Aporte jubilatorio (SIPA)"], "cuit_empleador": None, "codigo_generico": None},
    {"codigo": "PAMI", "nombre": "Ley 19.032 (PAMI)", "tipo": "descuento",
     "remunerativo": True, "alias": ["Ley 19.032 (PAMI)"], "cuit_empleador": None, "codigo_generico": None},
    {"codigo": "OBRASOCIAL", "nombre": "Obra Social", "tipo": "descuento",
     "remunerativo": True, "alias": ["Obra Social"], "cuit_empleador": None, "codigo_generico": None},
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
     "remunerativo": True, "alias": [], "cuit_empleador": None, "codigo_generico": None},
]

FORMULAS = [
    {"target": "JUBILACION", "descripcion": "Jubilación = 11%", "expr": "0.11 * base_remunerativa",
     "tolerancia": 1.0, "fecha_desde": None, "fecha_hasta": None},
    {"target": "PAMI", "descripcion": "PAMI = 3%", "expr": "0.03 * base_remunerativa",
     "tolerancia": 1.0, "fecha_desde": None, "fecha_hasta": None},
    {"target": "OBRASOCIAL", "descripcion": "Obra Social = 3%", "expr": "0.03 * base_remunerativa",
     "tolerancia": 1.0, "fecha_desde": None, "fecha_hasta": None},
]


def _recibo_empleador_nuevo(importe_jub, importe_pami, importe_os, cuit=CUIT_NUEVO):
    """Un empleador SIN NINGÚN concepto propio cargado: los códigos/nombres de
    sus líneas son totalmente distintos a los del catálogo genérico."""
    return {
        "periodo": "2026-08",
        "empleado": {"cuil": "20111111119"},
        "empleador": {"nombre": "Empleador Nuevo SA", "cuit": cuit},
        "lineas": [
            {"codigo": "001", "descripcion": "Sueldo Básico", "importe": 1000000, "tipo": "remuneracion"},
            {"codigo": "AB12", "descripcion": "Retención previsional Art.11", "importe": importe_jub,
             "tipo": "aporte_trabajador", "categoria_universal": "jubilacion"},
            {"codigo": "AB13", "descripcion": "Aporte INSSJP", "importe": importe_pami,
             "tipo": "aporte_trabajador", "categoria_universal": "pami"},
            {"codigo": "AB14", "descripcion": "Cobertura médica OSPE", "importe": importe_os,
             "tipo": "aporte_trabajador", "categoria_universal": "obra_social"},
        ],
        "totales_impresos": {},
    }


def test_categorias_universales_mapea_a_codigos_fijos():
    assert CATEGORIAS_UNIVERSALES["jubilacion"] == "JUBILACION"
    assert CATEGORIAS_UNIVERSALES["pami"] == "PAMI"
    assert CATEGORIAS_UNIVERSALES["obra_social"] == "OBRASOCIAL"
    assert CATEGORIAS_UNIVERSALES["cuota_sindical"] == "CUOTA_SINDICAL"
    print("OK  test_categorias_universales_mapea_a_codigos_fijos")


def test_conceptos_universales_son_solo_3_sin_cuota_sindical():
    codigos = {c["codigo"] for c in CONCEPTOS_UNIVERSALES}
    assert codigos == {"JUBILACION", "PAMI", "OBRASOCIAL"}, codigos
    print("OK  test_conceptos_universales_son_solo_3_sin_cuota_sindical")


def test_matchear_lineas_usa_categoria_universal_como_red_de_seguridad():
    idx = indexar_conceptos(GENERICOS, CUIT_NUEVO)
    lineas = [
        {"codigo": "AB12", "descripcion": "Retención previsional Art.11", "importe": -110000,
         "tipo": "aporte_trabajador", "categoria_universal": "jubilacion"},
    ]
    matcheadas, desconocidas = matchear_lineas(lineas, idx)
    assert not desconocidas
    assert matcheadas[0]["concepto"]["codigo"] == "JUBILACION"
    assert matcheadas[0]["chequeo_automatico"] is True
    print("OK  test_matchear_lineas_usa_categoria_universal_como_red_de_seguridad")


def test_matchear_lineas_sin_categoria_universal_no_matchea():
    idx = indexar_conceptos(GENERICOS, CUIT_NUEVO)
    lineas = [{"codigo": "XYZ", "descripcion": "Algo raro", "importe": -500, "tipo": "otro"}]
    matcheadas, desconocidas = matchear_lineas(lineas, idx)
    assert matcheadas == [] and len(desconocidas) == 1
    print("OK  test_matchear_lineas_sin_categoria_universal_no_matchea")


def test_validar_empleador_nuevo_sin_catalogo_igual_se_chequea():
    r = validar(GENERICOS, FORMULAS, _recibo_empleador_nuevo(-110000, -30000, -30000))
    assert r["estado"] == "OK", r["discrepancias"]
    assert len(r["formulas_validadas"]) == 3
    assert all(f["chequeo_automatico"] for f in r["formulas_validadas"])
    print("OK  test_validar_empleador_nuevo_sin_catalogo_igual_se_chequea")


def test_validar_empleador_nuevo_detecta_discrepancia_real():
    # PAMI mal calculado (debería ser 30000, viene 20000)
    r = validar(GENERICOS, FORMULAS, _recibo_empleador_nuevo(-110000, -20000, -30000))
    assert r["estado"] == "CON_DISCREPANCIAS"
    tipos = [d["tipo"] for d in r["discrepancias"]]
    assert "formula" in tipos
    print("OK  test_validar_empleador_nuevo_detecta_discrepancia_real")


def test_chequeo_normal_no_se_marca_como_automatico():
    conceptos = GENERICOS + [{"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
                              "remunerativo": True, "alias": [], "cuit_empleador": None, "codigo_generico": None}]
    recibo = {
        "periodo": "2026-08", "empleado": {"cuil": "20111111119"},
        "empleador": {"nombre": "Otro", "cuit": None},
        "lineas": [
            {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 1000000, "tipo": "remuneracion"},
            {"codigo": "JUBILACION", "descripcion": "Aporte jubilatorio (SIPA)", "importe": -110000,
             "tipo": "aporte_trabajador"},
        ],
        "totales_impresos": {},
    }
    r = validar(conceptos, [FORMULAS[0]], recibo)
    assert r["formulas_validadas"][0]["chequeo_automatico"] is False
    print("OK  test_chequeo_normal_no_se_marca_como_automatico")


GENERICOS_SIN_INGRESO = [c for c in GENERICOS if c["tipo"] != "ingreso"]


def _recibo_sin_ningun_ingreso_cargado(importe_jub):
    """Un sindicato que cargó los 3 genéricos de descuento pero NINGÚN
    concepto de haberes para este empleador: el bug real encontrado con un
    recibo de AFIP — sin esto, base_remunerativa da $0 y la fórmula compara
    contra cero (falsa discrepancia) en vez de contra el total impreso."""
    return {
        "periodo": "2026-08",
        "empleado": {"cuil": "20111111119"},
        "empleador": {"nombre": "Empleador Nuevo SA", "cuit": CUIT_NUEVO},
        "lineas": [
            {"codigo": "1-026", "descripcion": "Sueldo Basico AFIP", "importe": 27892.56, "tipo": "remuneracion"},
            {"codigo": "42-001", "descripcion": "AP. PERS. JUB. ANSES", "importe": importe_jub,
             "tipo": "aporte_trabajador", "categoria_universal": "jubilacion"},
        ],
        "totales_impresos": {"remuneraciones": 27892.56},
    }


def test_base_remunerativa_usa_total_impreso_si_no_matchea_ningun_ingreso():
    formulas = [{"target": "JUBILACION", "descripcion": "Jubilación = 11%",
                 "expr": "0.11 * base_remunerativa", "tolerancia": 1.0,
                 "fecha_desde": None, "fecha_hasta": None}]
    # 11% de 27892.56 = 3068.18 — el recibo trae justo ese importe.
    r = validar(GENERICOS_SIN_INGRESO, formulas, _recibo_sin_ningun_ingreso_cargado(-3068.18))
    assert r["base_remunerativa_aproximada"] is True
    assert r["estado"] == "OK", r["discrepancias"]
    print("OK  test_base_remunerativa_usa_total_impreso_si_no_matchea_ningun_ingreso")


def test_base_remunerativa_aproximada_detecta_discrepancia_real():
    formulas = [{"target": "JUBILACION", "descripcion": "Jubilación = 11%",
                 "expr": "0.11 * base_remunerativa", "tolerancia": 1.0,
                 "fecha_desde": None, "fecha_hasta": None}]
    r = validar(GENERICOS_SIN_INGRESO, formulas, _recibo_sin_ningun_ingreso_cargado(-1526.72))
    assert r["base_remunerativa_aproximada"] is True
    assert r["estado"] == "CON_DISCREPANCIAS"
    print("OK  test_base_remunerativa_aproximada_detecta_discrepancia_real")


def test_base_remunerativa_no_se_aproxima_si_matchea_algun_ingreso():
    conceptos = GENERICOS + [{"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
                              "remunerativo": True, "alias": [], "cuit_empleador": None, "codigo_generico": None}]
    recibo = {
        "periodo": "2026-08", "empleado": {"cuil": "20111111119"},
        "empleador": {"nombre": "Otro", "cuit": None},
        "lineas": [
            {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 1000000, "tipo": "remuneracion"},
            {"codigo": "JUBILACION", "descripcion": "Aporte jubilatorio (SIPA)", "importe": -110000,
             "tipo": "aporte_trabajador"},
        ],
        "totales_impresos": {"remuneraciones": 999999999},  # deliberadamente distinto: no debe usarse
    }
    r = validar(conceptos, [FORMULAS[0]], recibo)
    assert r["base_remunerativa_aproximada"] is False
    assert r["totales"]["remunerativo"] == 1000000.0
    print("OK  test_base_remunerativa_no_se_aproxima_si_matchea_algun_ingreso")


def test_detectar_nuevos_propaga_categoria_universal():
    lineas = [{"codigo": "AB99", "descripcion": "Algo sin catalogar", "importe": -5000,
               "tipo": "aporte_trabajador", "categoria_universal": "cuota_sindical"}]
    nuevos = detectar_nuevos(GENERICOS, lineas, CUIT_NUEVO)
    assert len(nuevos) == 1
    assert nuevos[0]["categoria_universal"] == "cuota_sindical"
    print("OK  test_detectar_nuevos_propaga_categoria_universal")


if __name__ == "__main__":
    test_categorias_universales_mapea_a_codigos_fijos()
    test_conceptos_universales_son_solo_3_sin_cuota_sindical()
    test_matchear_lineas_usa_categoria_universal_como_red_de_seguridad()
    test_matchear_lineas_sin_categoria_universal_no_matchea()
    test_validar_empleador_nuevo_sin_catalogo_igual_se_chequea()
    test_validar_empleador_nuevo_detecta_discrepancia_real()
    test_chequeo_normal_no_se_marca_como_automatico()
    test_base_remunerativa_usa_total_impreso_si_no_matchea_ningun_ingreso()
    test_base_remunerativa_aproximada_detecta_discrepancia_real()
    test_base_remunerativa_no_se_aproxima_si_matchea_algun_ingreso()
    test_detectar_nuevos_propaga_categoria_universal()
    print("\nTodo OK — categorías universales (aportes de ley) como red de seguridad.")
