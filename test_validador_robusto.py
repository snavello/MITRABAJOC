"""El motor de validación no puede explotar por lo que devuelva la IA ni por
una fórmula mal cargada por el sindicato.

Contexto (2026-08-26): un recibo se leía bien y, al tocar "Verificar", el
trabajador veía "No pudimos verificar este recibo. Probá con una foto más
nítida o el PDF." Ese texto era el 500 genérico de la app: cualquier excepción
no manejada en /api/validar salía disfrazada de problema de foto. Las dos
causas reales posibles eran un importe que la IA no pudo leer (null o texto,
que reventaba la suma con TypeError) y una fórmula cargada en /admin que no es
una expresión de Python válida (SyntaxError/NameError dentro del eval).

Correr con: DATABASE_URL= .venv/Scripts/python.exe test_validador_robusto.py
"""
import validador

CONCEPTOS = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
     "remunerativo": True, "alias": [], "categoria_sindical": ""},
    {"codigo": "SIND", "nombre": "Cuota sindical", "tipo": "descuento",
     "remunerativo": True, "alias": [], "categoria_sindical": "convenio"},
]
FORMULA_OK = {"target": "SIND", "descripcion": "Cuota sindical = 1,5%",
              "expr": "0.015 * base_remunerativa", "tolerancia": 1.0,
              "fecha_desde": None, "fecha_hasta": None}


def _recibo(importe_sindical=-1500):
    return {
        "empleado": {"cuil": "20111111119"},
        "periodo": "2025-04",
        "lineas": [
            {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 100000,
             "tipo": "remuneracion"},
            {"codigo": "SIND", "descripcion": "Cuota sindical", "importe": importe_sindical,
             "tipo": "aporte_trabajador"},
        ],
        "totales_impresos": {"remuneraciones": 100000, "descuentos": -1500, "neto": 98500},
    }


# --------------------------------------------------------------- a_numero ---
def test_a_numero_convierte_lo_convertible():
    casos = [(1500, 1500.0), (-1500.5, -1500.5), ("1500", 1500.0),
             ("$ 1.234,56", 1234.56), ("1,234.56", 1234.56), ("1.234.567", 1234567.0),
             ("(1500)", -1500.0), ("1,5", 1.5)]
    for entrada, esperado in casos:
        assert validador.a_numero(entrada) == esperado, (entrada, validador.a_numero(entrada))
    print("OK  test_a_numero_convierte_lo_convertible")


def test_a_numero_devuelve_none_ante_la_duda():
    # Mejor "no lo pude leer" que un número inventado.
    for entrada in [None, "", "   ", "ilegible", True, False, {}, [], float("nan"), float("inf")]:
        assert validador.a_numero(entrada) is None, entrada
    print("OK  test_a_numero_devuelve_none_ante_la_duda")


# ------------------------------------------------------ importes ilegibles ---
def test_importe_nulo_no_rompe_y_se_avisa():
    r = validador.validar(CONCEPTOS, [FORMULA_OK], _recibo(importe_sindical=None),
                          cuil_sesion="20111111119")
    tipos = [a["tipo"] for a in r["alertas"]]
    assert "importe_ilegible" in tipos, r["alertas"]
    # la línea ilegible NO se cuenta como $0: no entra en los cálculos
    assert r["totales"]["descuentos"] == 0.0, r["totales"]
    print("OK  test_importe_nulo_no_rompe_y_se_avisa")


def test_importe_como_texto_se_usa_igual():
    r = validador.validar(CONCEPTOS, [FORMULA_OK], _recibo(importe_sindical="-1.500,00"),
                          cuil_sesion="20111111119")
    assert r["totales"]["descuentos"] == 1500.0, r["totales"]
    assert not [a for a in r["alertas"] if a["tipo"] == "importe_ilegible"], r["alertas"]
    print("OK  test_importe_como_texto_se_usa_igual")


def test_recibo_sin_lineas_no_rompe():
    r = validador.validar(CONCEPTOS, [FORMULA_OK], {"empleado": {"cuil": "20111111119"},
                                                    "periodo": "2025-04"},
                          cuil_sesion="20111111119")
    assert r["estado"] == "CON_DISCREPANCIAS", r["estado"]
    print("OK  test_recibo_sin_lineas_no_rompe")


def test_totales_impresos_ilegibles_saltean_el_chequeo():
    recibo = _recibo()
    recibo["totales_impresos"]["neto"] = "ilegible"
    r = validador.validar(CONCEPTOS, [FORMULA_OK], recibo, cuil_sesion="20111111119")
    assert not [d for d in r["discrepancias"] if d["codigo"] == "neto"], r["discrepancias"]
    print("OK  test_totales_impresos_ilegibles_saltean_el_chequeo")


# ---------------------------------------------------------- fórmulas rotas ---
def test_formula_rota_no_tumba_el_recibo():
    rota = {**FORMULA_OK, "expr": "1,5 % base_remunerativa"}
    r = validador.validar(CONCEPTOS, [rota], _recibo(), cuil_sesion="20111111119")
    tipos = [a["tipo"] for a in r["alertas"]]
    assert "formula_invalida" in tipos, r["alertas"]
    # el resto del recibo se verificó igual
    assert r["totales"]["remunerativo"] == 100000.0, r["totales"]
    print("OK  test_formula_rota_no_tumba_el_recibo")


def test_tolerancia_nula_no_rompe():
    r = validador.validar(CONCEPTOS, [{**FORMULA_OK, "tolerancia": None}], _recibo(),
                          cuil_sesion="20111111119")
    assert r["formulas_validadas"][0]["codigo"] == "SIND", r["formulas_validadas"]
    print("OK  test_tolerancia_nula_no_rompe")


def test_tope_sin_valores_no_rompe():
    topes = [{"vigencia_desde": "2025-01", "tope_maximo": None, "base_minima": None,
              "estado": "verificado"}]
    r = validador.validar(CONCEPTOS, [{**FORMULA_OK, "sujeto_a_tope": True}], _recibo(),
                          cuil_sesion="20111111119", topes=topes)
    assert r["formulas_validadas"], r
    print("OK  test_tope_sin_valores_no_rompe")


# ------------------------------------ catálogo del sindicato mal cargado ----
def test_concepto_con_codigo_numerico_y_alias_suelto():
    # El catálogo lo carga una persona y lo tocan varias rutas: no es más
    # confiable que la salida de la IA. Código numérico (no texto), nombre
    # vacío y alias guardado como texto suelto en vez de lista.
    raro = {"codigo": 288, "nombre": None, "tipo": "descuento", "remunerativo": True,
            "alias": "CUOTA SINDICAL AEFIP", "categoria_sindical": "convenio"}
    idx = validador.indexar_conceptos([raro])
    # el alias entra entero, NO letra por letra (eso ensuciaba el índice y
    # podía hacer matchear una línea contra el concepto equivocado)
    assert set(idx) == {"288", "CUOTA SINDICAL AEFIP"}, sorted(idx)
    recibo = {"empleado": {"cuil": "20111111119"}, "periodo": "2025-04",
              "totales_impresos": None,
              "lineas": [{"codigo": 288, "descripcion": "CUOTA SINDICAL AEFIP",
                          "importe": -1500, "tipo": "aporte_trabajador"}]}
    r = validador.validar([raro], [], recibo, cuil_sesion="20111111119")
    assert r["totales"]["descuentos"] == 1500.0, r["totales"]
    print("OK  test_concepto_con_codigo_numerico_y_alias_suelto")


def test_codigo_con_espacios_matchea_igual():
    concepto = {"codigo": "288-001 ", "nombre": "Cuota", "tipo": "descuento",
                "remunerativo": True, "alias": [], "categoria_sindical": ""}
    idx = validador.indexar_conceptos([concepto])
    assert idx.get("288-001") is concepto, sorted(idx)
    print("OK  test_codigo_con_espacios_matchea_igual")


def test_linea_que_no_es_diccionario_se_ignora():
    recibo = {"empleado": {"cuil": "20111111119"}, "periodo": "2025-04",
              "lineas": ["esto no es una línea", None], "totales_impresos": {}}
    r = validador.validar(CONCEPTOS, [], recibo, cuil_sesion="20111111119")
    assert r["estado"] == "OK", r
    assert validador.detectar_nuevos(CONCEPTOS, recibo["lineas"]) == []
    print("OK  test_linea_que_no_es_diccionario_se_ignora")


def test_concepto_nuevo_sale_siempre_con_texto():
    # Lo que devuelve detectar_nuevos termina como Concepto en la base: el
    # código y el nombre tienen que ser texto sí o sí.
    nuevos = validador.detectar_nuevos([], [{"codigo": 288, "descripcion": 123, "importe": -100}])
    assert isinstance(nuevos[0]["codigo"], str) and isinstance(nuevos[0]["descripcion"], str), nuevos
    print("OK  test_concepto_nuevo_sale_siempre_con_texto")


# -------------------------------------------------- error_de_expresion() ----
def test_error_de_expresion_acepta_las_validas():
    for expr in ["0.015 * base_remunerativa", "1.5/100 * base_remunerativa",
                 "0.11 * base_remunerativa - c(\"JUB\")", "  0.03*total_ingresos  "]:
        assert validador.error_de_expresion(expr) is None, expr
    print("OK  test_error_de_expresion_acepta_las_validas")


def test_error_de_expresion_rechaza_las_rotas():
    for expr in ["", "   ", "0,015 * base_remunerativa", "1,5 % base_remunerativa",
                 "1.5% * base_remunerativa", "0.015 x base_remunerativa",
                 "0.015 * BASE_REMUNERATIVA", "0.015 * remunerativo",
                 "base_remunerativa / 0"]:
        motivo = validador.error_de_expresion(expr)
        assert motivo, expr
        assert isinstance(motivo, str) and len(motivo) > 10, (expr, motivo)
    # el motivo tiene que explicar el problema de la coma, que es el más común
    assert "coma" in validador.error_de_expresion("0,015 * base_remunerativa").lower()
    print("OK  test_error_de_expresion_rechaza_las_rotas")


if __name__ == "__main__":
    test_a_numero_convierte_lo_convertible()
    test_a_numero_devuelve_none_ante_la_duda()
    test_importe_nulo_no_rompe_y_se_avisa()
    test_importe_como_texto_se_usa_igual()
    test_recibo_sin_lineas_no_rompe()
    test_totales_impresos_ilegibles_saltean_el_chequeo()
    test_formula_rota_no_tumba_el_recibo()
    test_tolerancia_nula_no_rompe()
    test_tope_sin_valores_no_rompe()
    test_concepto_con_codigo_numerico_y_alias_suelto()
    test_codigo_con_espacios_matchea_igual()
    test_linea_que_no_es_diccionario_se_ignora()
    test_concepto_nuevo_sale_siempre_con_texto()
    test_error_de_expresion_acepta_las_validas()
    test_error_de_expresion_rechaza_las_rotas()
    print("\nTodo OK — el motor aguanta datos sucios de la IA y fórmulas mal cargadas.")
