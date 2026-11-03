"""Dos defectos que encontró la prueba piloto del lote bancario en Pruebas
(2026-11-03, 10 recibos con Sonnet 5.5): la IA leyó bien los 10 y la app los
validó mal por estas dos causas.

1. La cuota sindical de un banco nuevo no se vinculaba con la regla del
   sindicato: la IA la etiqueta `cuota_sindical`, que apunta al código
   `CUOTA_SINDICAL`, y La Bancaria la llama `CUOTA`. Resultado en los 10:
   «El recibo no incluye 'Asoc Bancaria'».
2. En un recibo sin códigos (Galicia), «Antigüedad (16 años)» y «Antigüedad
   (24 años)» recibían el mismo código provisorio. El segundo concepto no se
   creaba, la línea no encajaba con ninguno y salía de la suma de haberes.

Correr con: python -m pytest test_conceptos_bancos.py -q
"""
import validador as V

GALICIA = "30500001735"
BBVA = "30500003193"

# El catálogo de La Bancaria, como está en Pruebas (lo que importa).
CUOTA = {"codigo": "CUOTA", "nombre": "Cuota sindical Asociación Bancaria", "tipo": "descuento",
         "remunerativo": True, "alias": ["Cuota sindical Asociación Bancaria"],
         "pendiente_revision": False, "categoria_sindical": "afiliacion",
         "cuit_empleador": None, "codigo_generico": None}
JUBILACION = {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)", "tipo": "descuento",
              "remunerativo": True, "alias": [], "pendiente_revision": False,
              "categoria_sindical": None, "cuit_empleador": None, "codigo_generico": None}


def _pendiente(codigo, nombre, cuit, tipo="ingreso"):
    return {"codigo": codigo, "nombre": nombre, "tipo": tipo, "remunerativo": True,
            "alias": [nombre], "pendiente_revision": True, "categoria_sindical": None,
            "cuit_empleador": cuit, "codigo_generico": None}


FORMULA_CUOTA = {"target": "CUOTA", "descripcion": "Asoc Bancaria", "expr": "0.02 * base_remunerativa",
                 "tolerancia": 2000.0, "fecha_desde": "2025-10-16", "fecha_hasta": "",
                 "sujeto_a_tope": False}


def _linea(desc, importe, seccion="haberes", codigo=None, tipo="remuneracion", cat=None):
    return {"codigo": codigo, "descripcion": desc, "importe": importe, "tipo": tipo,
            "seccion": seccion, "cantidad": None, "unidad": None, "categoria_universal": cat}


def _recibo(lineas, cuit, remun, desc, neto, periodo="2026-04"):
    return {"formato": "clasico", "periodo": periodo,
            "empleado": {"cuil": "20185331424", "apellido_nombre": "Prueba"},
            "empleador": {"cuit": cuit, "nombre": "Banco"},
            "lineas": lineas,
            "totales_impresos": {"remuneraciones": remun, "descuentos": desc, "neto": neto}}


# ------------------------------------------------------- 1. la cuota -----
def test_la_cuota_se_vincula_al_concepto_marcado_como_afiliacion():
    assert V.generico_de_categoria("cuota_sindical", [CUOTA, JUBILACION]) is CUOTA
    assert V.generico_de_categoria("jubilacion", [CUOTA, JUBILACION]) is JUBILACION
    # Un concepto de un banco no es genérico; dos cuotas genéricas, ambiguo.
    otra = {**CUOTA, "codigo": "CUOTA2"}
    assert V.generico_de_categoria("cuota_sindical", [{**CUOTA, "cuit_empleador": BBVA}]) is None
    assert V.generico_de_categoria("cuota_sindical", [CUOTA, otra]) is None
    assert V.generico_de_categoria(None, [CUOTA]) is None


def test_con_aporte_solidario_cargado_no_se_elige_solo():
    """Para la IA, el aporte solidario de convenio también es «un aporte al
    gremio»: si el sindicato tiene los dos conceptos, no se adivina cuál es."""
    solidario = {**CUOTA, "codigo": "SOLIDARIO", "nombre": "Aporte solidario",
                 "categoria_sindical": "convenio"}
    assert V.generico_de_categoria("cuota_sindical", [CUOTA, solidario]) is None
    # El código universal exacto sigue mandando.
    universal = {**CUOTA, "codigo": "CUOTA_SINDICAL", "categoria_sindical": None}
    assert V.generico_de_categoria("cuota_sindical", [universal, solidario]) is universal
    # Y la línea queda sin vincular (la regla de la cuota no la toma).
    cat = [CUOTA, solidario, _pendiente("515", "Aporte solidario CCT 18/75", BBVA, "descuento"),
           _pendiente("001", "Sueldo básico", BBVA)]
    recibo = _recibo([_linea("Sueldo básico", 2500000, codigo="001"),
                      _linea("Aporte solidario CCT 18/75", 25000, "descuentos", "515",
                             "aporte_trabajador", "cuota_sindical")],
                     BBVA, 2500000, 25000, 2475000)
    m, _ = V.matchear_lineas(recibo["lineas"], V.indexar_conceptos(cat, BBVA))
    assert not next(x for x in m if x["codigo"] == "515").get("chequeo_automatico")


def test_la_cuota_de_un_banco_nuevo_ya_pendiente_se_valida_contra_la_regla():
    """El caso de los 10 recibos: el banco ya tenía su `510` pendiente y sin
    vincular. Antes: «El recibo no incluye 'Asoc Bancaria'»."""
    cat = [CUOTA, JUBILACION, _pendiente("510", "Cuota sindical Asoc. Bancaria 2%", BBVA, "descuento"),
           _pendiente("001", "Sueldo básico", BBVA)]
    recibo = _recibo([_linea("Sueldo básico", 2500000, codigo="001"),
                      _linea("Cuota sindical Asoc. Bancaria 2%", 50000, "descuentos", "510",
                             "aporte_trabajador", "cuota_sindical")],
                     BBVA, 2500000, 50000, 2450000)
    res = V.validar(cat, [FORMULA_CUOTA], recibo)
    assert not [d for d in res["discrepancias"] if d["tipo"] == "concepto_faltante"], res["discrepancias"]
    assert res["estado"] == "OK"


def test_la_cuota_que_no_coincide_se_sigue_marcando():
    cat = [CUOTA, _pendiente("510", "Cuota sindical Asoc. Bancaria 2%", BBVA, "descuento"),
           _pendiente("001", "Sueldo básico", BBVA)]
    recibo = _recibo([_linea("Sueldo básico", 2500000, codigo="001"),
                      _linea("Cuota sindical Asoc. Bancaria 2%", 80000, "descuentos", "510",
                             "aporte_trabajador", "cuota_sindical")],
                     BBVA, 2500000, 80000, 2420000)
    res = V.validar(cat, [FORMULA_CUOTA], recibo)
    assert any(d["tipo"] == "formula" for d in res["discrepancias"])


# ----------------------------------------------- 2. código provisorio ----
def test_el_codigo_provisorio_no_depende_de_los_numeros():
    assert V.codigo_provisorio("Antigüedad (16 años)") == V.codigo_provisorio("Antigüedad (24 años)") \
        == "NUEVO-ANTIGUEDAD"
    assert V.codigo_provisorio("Adicional por título") != V.codigo_provisorio("Adicional por zona")
    assert V.codigo_provisorio("S.A.C. 1/2 aguinaldo") == "NUEVO-S.A.C. AGUINALDO"
    assert V.codigo_provisorio("123") == "NUEVO-123"          # sin letras, queda el original


def test_la_antiguedad_de_otra_persona_no_sale_de_la_suma():
    """Recibo real de Galicia del piloto (20311447034, 2025-12): antes la suma
    de haberes daba $3.877.810,84 contra $4.258.348,65 impresos."""
    cat = [JUBILACION, _pendiente("NUEVO-ANTIGUEDAD", "Antigüedad (24 años)", GALICIA),
           _pendiente("NUEVO-SUELDO BASICO", "Sueldo básico", GALICIA),
           _pendiente("NUEVO-S.A.C. AGUINALDO", "S.A.C. 1/2 aguinaldo", GALICIA),
           _pendiente("NUEVO-COMPENSACION NO REMUNE", "Compensación no remunerativa", GALICIA)]
    lineas = [_linea("Sueldo básico", 2378361.29), _linea("Antigüedad (16 años)", 380537.81),
              _linea("S.A.C. 1/2 aguinaldo", 1379449.55), _linea("Compensación no remunerativa", 120000.0)]
    recibo = _recibo(lineas, GALICIA, 4258348.65, 0, 4258348.65, "2025-12")
    assert V.detectar_nuevos(cat, lineas, GALICIA) == []          # ya encaja: no hay nada que crear
    res = V.validar(cat, [], recibo)
    assert round(res["totales"]["ingresos"], 2) == 4258348.65
    assert not [d for d in res["discrepancias"] if d["tipo"] == "total_inconsistente"]


def test_la_primera_vez_se_crea_un_solo_concepto_para_las_dos_antiguedades():
    lineas = [_linea("Antigüedad (16 años)", 100.0), _linea("Antigüedad (24 años)", 200.0)]
    nuevos = V.detectar_nuevos([], lineas, GALICIA)
    assert [n["codigo"] for n in nuevos] == ["NUEVO-ANTIGUEDAD"]
