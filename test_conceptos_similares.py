"""Detección de conceptos con código provisorio y sugerencia de similar.

Usa el catálogo REAL de AEFIP (33 conceptos, producción) como caso de prueba,
porque es el que expuso el problema: comparar por similitud de nombre a secas
marca 6 pares legítimos por cada duplicado real.

Correr con: .venv/Scripts/python.exe test_conceptos_similares.py
"""
import validador

# Catálogo real de AEFIP. Las variantes por grado del escalafón (GRUPO 26,
# - A.3, INC B.) son conceptos DISTINTOS a propósito, no duplicados.
AEFIP = [
    {"codigo": "115-001", "nombre": "CTA. DE JERARQUIZACION INC A.", "alias": []},
    {"codigo": "116-001", "nombre": "CTA. DE JERARQUIZACION INC B.", "alias": []},
    {"codigo": "38-001", "nombre": "APORTE PERSONAL I.N.S.S.J.Y P.", "alias": []},
    {"codigo": "42-001", "nombre": "AP. PERS. JUB. ANSES", "alias": []},
    {"codigo": "85-117", "nombre": "O.S. DE COMISARIOS NAVALES", "alias": []},
    {"codigo": "1-026", "nombre": "SUELDO BASICO GRUPO 26", "alias": []},
    {"codigo": "1-013", "nombre": "SUELDO BASICO", "alias": []},
    {"codigo": "4-001", "nombre": "ADICIONAL TECNICO", "alias": []},
    {"codigo": "4-003", "nombre": "ADICIONAL TECNICO - A.3", "alias": []},
    {"codigo": "37-025", "nombre": "ADICIONAL TECNICO - A1", "alias": []},
    {"codigo": "6-026", "nombre": "BONIFICACION ESPECIAL GRUPO 26", "alias": []},
    {"codigo": "6-013", "nombre": "BONIFICACION ESPECIAL", "alias": []},
    {"codigo": "37-026", "nombre": "PERMANENCIA EN EL GRUPO 26", "alias": []},
    {"codigo": "37-013", "nombre": "PERMANENCIA EN EL GRUPO", "alias": []},
    {"codigo": "795-019", "nombre": "COMP. P/DEDICACION ESPECIAL", "alias": []},
    {"codigo": "797-011", "nombre": "COMP. P/DEDICACION ESP. S/GRUPO", "alias": []},
    # El duplicado real: misma línea que 795-019, pero la IA no leyó el código.
    {"codigo": "NUEVO-COMP.P/DEDIC", "nombre": "COMP.P/DEDICACION ESPECIAL (línea extra)", "alias": []},
]


def test_marca_el_provisorio_y_le_encuentra_el_original():
    provisorios = validador.detectar_provisorios(AEFIP)
    assert len(provisorios) == 1, provisorios
    p = provisorios[0]
    assert p["concepto"]["codigo"] == "NUEVO-COMP.P/DEDIC"
    assert p["similar"] is not None, "debería sugerir el concepto original"
    assert p["similar"]["concepto"]["codigo"] == "795-019", p["similar"]
    print("OK  test_marca_el_provisorio_y_le_encuentra_el_original")


def test_no_marca_variantes_legitimas_del_escalafon():
    """El corazón del asunto: estos pares se parecen MÁS que el duplicado real
    (hasta 0.95), pero son conceptos distintos. No deben aparecer nunca."""
    codigos_marcados = {p["concepto"]["codigo"] for p in validador.detectar_provisorios(AEFIP)}
    for codigo in ["1-013", "1-026", "4-001", "4-003", "37-025", "37-013",
                   "37-026", "6-013", "6-026", "115-001", "116-001", "797-011"]:
        assert codigo not in codigos_marcados, f"{codigo} es legítimo, no debe marcarse"
    print("OK  test_no_marca_variantes_legitimas_del_escalafon")


def test_la_similitud_sola_no_alcanza():
    """Deja constancia de por qué se filtra por código provisorio: un par
    legítimo puntúa MÁS ALTO que el duplicado verdadero."""
    dup = validador.similitud("COMP. P/DEDICACION ESPECIAL", "COMP.P/DEDICACION ESPECIAL (línea extra)")
    legitimo = validador.similitud("PERMANENCIA EN EL GRUPO", "PERMANENCIA EN EL GRUPO 26")
    assert legitimo > dup, (
        f"si esto cambia, revisar el diseño: legítimo={legitimo:.3f} dup={dup:.3f}")
    print(f"OK  test_la_similitud_sola_no_alcanza (legítimo={legitimo:.3f} > duplicado={dup:.3f})")


def test_catalogo_sin_provisorios_no_marca_nada():
    limpio = [c for c in AEFIP if not c["codigo"].startswith("NUEVO-")]
    assert validador.detectar_provisorios(limpio) == []
    print("OK  test_catalogo_sin_provisorios_no_marca_nada")


def test_provisorio_sin_parecido_se_marca_igual():
    """Un código provisorio es frágil aunque no sea duplicado: nunca matchea
    por código. Se marca con similar=None."""
    catalogo = AEFIP + [{"codigo": "NUEVO-XYZ", "nombre": "CONCEPTO TOTALMENTE NUEVO", "alias": []}]
    marcados = {p["concepto"]["codigo"]: p for p in validador.detectar_provisorios(catalogo)}
    assert "NUEVO-XYZ" in marcados
    assert marcados["NUEVO-XYZ"]["similar"] is None, marcados["NUEVO-XYZ"]
    print("OK  test_provisorio_sin_parecido_se_marca_igual")


if __name__ == "__main__":
    test_marca_el_provisorio_y_le_encuentra_el_original()
    test_no_marca_variantes_legitimas_del_escalafon()
    test_la_similitud_sola_no_alcanza()
    test_catalogo_sin_provisorios_no_marca_nada()
    test_provisorio_sin_parecido_se_marca_igual()
    print("\nTodo OK — detección de conceptos provisorios / duplicados.")
