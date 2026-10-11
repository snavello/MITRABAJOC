"""cuit.py: el módulo 11 de AFIP, en un solo lugar (PLAN_CUIT_MOD11.md).

Puro: no toca la base. El último test es fail-closed: recorre el código con
`ast` y falla si otro módulo vuelve a escribir los pesos del verificador por
su cuenta (el patrón de test_fechas.py)."""
import ast
from pathlib import Path

import pytest

import cuit

RAIZ = Path(__file__).resolve().parent


# ---------------- normalizar ----------------

@pytest.mark.parametrize("entrada, salida", [
    ("20-20279041-1", "20202790411"),
    (" 20 20279041 1 ", "20202790411"),
    ("20.20279041/1", "20202790411"),
    (20202790411, "20202790411"),
    (None, ""),
    ("", ""),
    ("sin numeros", ""),
    ("２０２０２７９０４１１", ""),   # dígitos de ancho completo: no son dígitos ASCII
])
def test_normalizar(entrada, salida):
    assert cuit.normalizar(entrada) == salida


# ---------------- verificador y validez ----------------

@pytest.mark.parametrize("numero", [
    "20202790411",      # el caso real de test_cuil_leer_ajeno.py
    "20-20279041-1",    # con guiones vale igual
    "30444640975",      # el CUIT del recibo de ese mismo caso
    "33693450239",      # AFIP
    "27999999994",
    "23121212129",
    "20111111112",
    "20111111120",
])
def test_validos(numero):
    assert cuit.es_valido(numero)


@pytest.mark.parametrize("numero", [
    "27999999999",      # el usuario de prueba del plan
    "20111111119",      # accesos viejos de la demo: ninguno cumplía
    "20111111110",
    "30999888776",
    "2020279041",       # 10 dígitos
    "202027904111",     # 12 dígitos
    "10202790411",      # prefijo que no existe (con verificador "bien" calculado)
    "",
    None,
])
def test_invalidos(numero):
    assert not cuit.es_valido(numero)


def test_prefijo_desconocido_aunque_cierre_la_cuenta():
    diez = "1020279041"
    dv = cuit.digito_verificador(diez)
    assert dv is not None
    assert not cuit.es_valido(diez + str(dv))


def test_r_11_da_verificador_cero():
    # 2011111112: la suma da múltiplo de 11 -> r = 11 -> verificador 0.
    assert cuit.digito_verificador("2011111112") == 0
    assert cuit.es_valido("20111111120")


def test_r_10_no_tiene_verificador():
    assert cuit.digito_verificador("2012121212") is None
    for ultimo in "0123456789":
        assert not cuit.es_valido("2012121212" + ultimo)


def test_tipo_y_restriccion_por_tipo():
    assert cuit.tipo("20202790411") == cuit.PERSONA
    assert cuit.tipo("30444640975") == cuit.EMPRESA
    assert cuit.tipo("10202790411") == ""
    assert cuit.es_valido("20202790411", de=cuit.PERSONA)
    assert not cuit.es_valido("20202790411", de=cuit.EMPRESA)
    assert cuit.es_valido("30444640975", de=cuit.EMPRESA)
    assert not cuit.es_valido("30444640975", de=cuit.PERSONA)


@pytest.mark.parametrize("prefijo", sorted(cuit.PREFIJOS_PERSONA | cuit.PREFIJOS_EMPRESA))
def test_todos_los_prefijos_conocidos_validan(prefijo):
    # Para cada prefijo hay DNI con verificador: el número armado tiene que validar.
    for dni in range(12345678, 12345700):
        diez = f"{prefijo}{dni:08d}"
        dv = cuit.digito_verificador(diez)
        if dv is not None:
            assert cuit.es_valido(diez + str(dv))
            return
    pytest.fail(f"ningún DNI con verificador para {prefijo}")


# ---------------- corregir ----------------

@pytest.mark.parametrize("viejo, nuevo", [
    ("27999999999", "27999999994"),
    ("27-99999999-9", "27999999994"),
    ("20121212127", "23121212129"),     # r = 10 -> prefijo 23 (como AFIP)
    ("20999999991", "23999999999"),
    ("30111222339", "30111222335"),
    ("20202790411", "20202790411"),     # ya válido: vuelve igual
])
def test_corregir(viejo, nuevo):
    assert cuit.corregir(viejo) == nuevo
    assert cuit.es_valido(nuevo)


def test_corregir_con_r_10_respeta_la_regla_de_afip():
    # AFIP: 20 -> 23 con verificador 9; 27 -> 23 con verificador 4; 30 -> 33 con 9.
    for prefijo, nuevo_prefijo, dv_esperado in (("20", "23", 9), ("27", "23", 4), ("30", "33", 9)):
        for dni in range(10000000, 10002000):
            diez = f"{prefijo}{dni:08d}"
            if cuit.digito_verificador(diez) is None:
                corregido = cuit.corregir(diez + "0")
                assert corregido == f"{nuevo_prefijo}{dni:08d}{dv_esperado}"
                break
        else:
            pytest.fail(f"no apareció un caso r = 10 para {prefijo}")


def test_corregir_no_inventa():
    assert cuit.corregir("") == ""
    assert cuit.corregir("2020279041") == ""        # 10 dígitos
    assert cuit.corregir("10202790411") == ""       # prefijo desconocido
    # Un 23 sin verificador posible no tiene a qué prefijo pasar.
    for dni in range(10000000, 10002000):
        diez = f"23{dni:08d}"
        if cuit.digito_verificador(diez) is None:
            assert cuit.corregir(diez + "0") == ""
            break
    else:
        pytest.fail("no apareció un 23 con r = 10")


def test_la_trampa_del_plan_dos_numeros_un_solo_corregido():
    # Por esto la conversión verifica colisiones antes de escribir (D4).
    assert cuit.corregir("20111111110") == cuit.corregir("20111111119") == "20111111112"


# ---------------- siguiente_libre ----------------

def test_siguiente_libre_salta_lo_ocupado():
    assert cuit.siguiente_libre("20111111110", {"20111111112"}) == "20111111120"
    nuevo = cuit.siguiente_libre("20111111110", {"20111111120"})
    assert nuevo != "20111111120" and cuit.es_valido(nuevo) and nuevo[:2] == "20"


def test_siguiente_libre_no_cambia_el_prefijo_y_saltea_r_10():
    # 2012121212 no tiene verificador: el siguiente libre de 2012121211x lo saltea.
    nuevo = cuit.siguiente_libre("20121212110")
    assert nuevo[:2] == "20" and cuit.es_valido(nuevo)
    assert nuevo[:10] != "2012121212"


def test_siguiente_libre_ignora_formato_en_ocupados():
    assert cuit.siguiente_libre("20111111110", {"20-11111112-0"}) != "20111111120"


# ---------------- formato ----------------

def test_formatear():
    assert cuit.formatear("20202790411") == "20-20279041-1"
    assert cuit.formatear("20-20279041-1") == "20-20279041-1"
    assert cuit.formatear("123") == "123"
    assert cuit.formatear(None) == ""


def test_con_formato_de():
    assert cuit.con_formato_de("30-11111111-1", "30111111118") == "30-11111111-8"
    assert cuit.con_formato_de("30111111111", "30111111118") == "30111111118"
    assert cuit.con_formato_de("20 11111111 9", "20111111112") == "20-11111111-2"
    assert cuit.con_formato_de(None, "20111111112") == "20111111112"


# ---------------- una sola implementación (fail-closed) ----------------

def _modulos_de_la_app():
    for p in sorted(RAIZ.rglob("*.py")):
        rel = p.relative_to(RAIZ)
        if rel.parts[0] in {".venv", "venv", "node_modules", "migrations"}:
            continue
        if p.name.startswith("test_") or p.name in {"cuit.py", "conftest.py"}:
            continue
        yield p


def test_nadie_mas_escribe_los_pesos_del_verificador():
    """Los pesos 5,4,3,2,7,6,5,4,3,2 viven solo en cuit.py. Si otro archivo
    los escribe, calcula el verificador por su cuenta y tarde o temprano se
    desalinea (pasó con _norm_cuil, que estaba copiado en main.py y en
    validador.py)."""
    pesos = list(cuit.PESOS)
    infractores = []
    for p in _modulos_de_la_app():
        try:
            arbol = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.Tuple, ast.List)) and len(nodo.elts) == 10:
                valores = [e.value for e in nodo.elts if isinstance(e, ast.Constant)]
                if valores == pesos:
                    infractores.append(f"{p.relative_to(RAIZ)}:{nodo.lineno}")
            if isinstance(nodo, ast.Constant) and nodo.value == "5432765432":
                infractores.append(f"{p.relative_to(RAIZ)}:{nodo.lineno}")
    assert not infractores, ("estos archivos calculan el verificador por su cuenta; "
                             "tienen que usar cuit.py: " + ", ".join(infractores))
