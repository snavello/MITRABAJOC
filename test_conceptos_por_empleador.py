"""Conceptos específicos de un empleador (cuit_empleador) con fallback a los
genéricos del sindicato, y resolución a un único código genérico para que la
Formula los valide sin duplicarla por cada empleador.

Correr con: .venv/Scripts/python.exe -m pytest test_conceptos_por_empleador.py -q
"""
from validador import indexar_conceptos, matchear_lineas, validar, detectar_nuevos, codigo_efectivo

CUIT_A = "30111111112"
CUIT_B = "30222222223"

GENERICO_JUB = {"codigo": "JUB", "nombre": "Aporte jubilatorio", "tipo": "descuento",
                "remunerativo": True, "alias": [], "cuit_empleador": None, "codigo_generico": None}
ESPECIFICO_A = {"codigo": "060", "nombre": "Jubilacion Ley 24241", "tipo": "descuento",
                 "remunerativo": True, "alias": [], "cuit_empleador": CUIT_A, "codigo_generico": "JUB"}
ESPECIFICO_B = {"codigo": "APJUB", "nombre": "Ap. Jubilatorio", "tipo": "descuento",
                 "remunerativo": True, "alias": [], "cuit_empleador": CUIT_B, "codigo_generico": "JUB"}
CATALOGO = [GENERICO_JUB, ESPECIFICO_A, ESPECIFICO_B]


def test_indexar_prioriza_especifico_sobre_generico_en_colision():
    # Los tres conceptos comparten el nombre normalizado -> el del CUIT pisa al genérico.
    generico = {**GENERICO_JUB, "nombre": "Jubilacion Ley 24241"}
    catalogo = [generico, ESPECIFICO_A]
    idx = indexar_conceptos(catalogo, CUIT_A)
    assert idx["JUBILACION LEY 24241"]["codigo"] == "060"
    print("OK  test_indexar_prioriza_especifico_sobre_generico_en_colision")


def test_matchea_linea_por_codigo_especifico_del_empleador():
    idx = indexar_conceptos(CATALOGO, CUIT_A)
    lineas = [{"codigo": "060", "descripcion": "Jubilacion Ley 24241", "importe": -100}]
    matcheadas, desconocidas = matchear_lineas(lineas, idx)
    assert not desconocidas
    assert matcheadas[0]["concepto"]["codigo"] == "060"
    print("OK  test_matchea_linea_por_codigo_especifico_del_empleador")


def test_mismo_codigo_no_matchea_para_otro_empleador():
    # El código "060" es de CUIT_A; para CUIT_B no existe -> queda desconocido.
    idx = indexar_conceptos(CATALOGO, CUIT_B)
    lineas = [{"codigo": "060", "descripcion": "algo que no está en ningún catálogo", "importe": -100}]
    _, desconocidas = matchear_lineas(lineas, idx)
    assert len(desconocidas) == 1
    print("OK  test_mismo_codigo_no_matchea_para_otro_empleador")


def test_cae_al_generico_si_el_cuit_no_tiene_ese_concepto():
    idx = indexar_conceptos(CATALOGO, CUIT_A)
    lineas = [{"codigo": "JUB", "descripcion": "Aporte jubilatorio", "importe": -50}]
    matcheadas, _ = matchear_lineas(lineas, idx)
    assert matcheadas[0]["concepto"]["codigo"] == "JUB"
    print("OK  test_cae_al_generico_si_el_cuit_no_tiene_ese_concepto")


def test_codigo_efectivo_resuelve_al_generico():
    assert codigo_efectivo(ESPECIFICO_A) == "JUB"
    assert codigo_efectivo(ESPECIFICO_B) == "JUB"
    assert codigo_efectivo(GENERICO_JUB) == "JUB"
    print("OK  test_codigo_efectivo_resuelve_al_generico")


def _recibo(cuit_empleador, codigo_linea, importe):
    return {
        "periodo": "08/2026",
        "empleado": {"cuil": "20111111119"},
        "empleador": {"nombre": "Empleador", "cuit": cuit_empleador},
        "lineas": [
            {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 1000},
            {"codigo": codigo_linea, "descripcion": "Jubilacion", "importe": importe},
        ],
        "totales_impresos": {},
    }


def test_validar_controla_variante_de_cualquier_empleador_con_una_sola_formula():
    formulas = [{"target": "JUB", "descripcion": "Jubilación = 11%",
                 "expr": "0.11 * base_remunerativa", "tolerancia": 1.0}]
    conceptos = CATALOGO + [{"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
                              "remunerativo": True, "alias": [], "cuit_empleador": None, "codigo_generico": None}]

    r_a = validar(conceptos, formulas, _recibo(CUIT_A, "060", -110))
    assert r_a["estado"] == "OK", r_a["discrepancias"]

    r_b = validar(conceptos, formulas, _recibo(CUIT_B, "APJUB", -110))
    assert r_b["estado"] == "OK", r_b["discrepancias"]
    print("OK  test_validar_controla_variante_de_cualquier_empleador_con_una_sola_formula")


def test_validar_detecta_discrepancia_en_variante_especifica():
    formulas = [{"target": "JUB", "descripcion": "Jubilación = 11%",
                 "expr": "0.11 * base_remunerativa", "tolerancia": 1.0}]
    conceptos = CATALOGO + [{"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso",
                              "remunerativo": True, "alias": [], "cuit_empleador": None, "codigo_generico": None}]
    r = validar(conceptos, formulas, _recibo(CUIT_A, "060", -50))
    assert r["estado"] == "CON_DISCREPANCIAS"
    assert r["discrepancias"][0]["tipo"] == "formula"
    print("OK  test_validar_detecta_discrepancia_en_variante_especifica")


def test_detectar_nuevos_no_reproponer_lo_ya_cargado_para_ese_cuit():
    lineas = [{"codigo": "060", "descripcion": "Jubilacion Ley 24241", "importe": -100}]
    nuevos = detectar_nuevos(CATALOGO, lineas, CUIT_A)
    assert nuevos == []
    print("OK  test_detectar_nuevos_no_reproponer_lo_ya_cargado_para_ese_cuit")


def test_detectar_nuevos_propone_si_el_cuit_no_tiene_ese_codigo():
    lineas = [{"codigo": "060", "descripcion": "algo nuevo sin match", "importe": -100}]
    nuevos = detectar_nuevos(CATALOGO, lineas, CUIT_B)
    assert len(nuevos) == 1 and nuevos[0]["codigo"] == "060"
    print("OK  test_detectar_nuevos_propone_si_el_cuit_no_tiene_ese_codigo")


if __name__ == "__main__":
    test_indexar_prioriza_especifico_sobre_generico_en_colision()
    test_matchea_linea_por_codigo_especifico_del_empleador()
    test_mismo_codigo_no_matchea_para_otro_empleador()
    test_cae_al_generico_si_el_cuit_no_tiene_ese_concepto()
    test_codigo_efectivo_resuelve_al_generico()
    test_validar_controla_variante_de_cualquier_empleador_con_una_sola_formula()
    test_validar_detecta_discrepancia_en_variante_especifica()
    test_detectar_nuevos_no_reproponer_lo_ya_cargado_para_ese_cuit()
    test_detectar_nuevos_propone_si_el_cuit_no_tiene_ese_codigo()
    print("\nTodo OK — conceptos específicos por empleador con fallback genérico.")
