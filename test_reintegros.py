"""Reintegros entre los descuentos: la zona de una línea la dice dónde está
impresa, no el signo de su importe (validador.repartir_por_zona).

Caso real (SDN, 2026-10-11): recibo de AEFIP de febrero de 2015 con
"IMP.GCIAS. PERIODOS ANTERIORES" en +62.949,21 entre los descuentos -- una
devolución de Ganancias. La app la dio de alta como haber REMUNERATIVO (por
el signo), el bruto dio 107.924,61 contra 44.975,40 impreso, el total de
descuentos no cerró contra el impreso (46.460,13 = reintegro - descuentos) y
la jubilación salió con una diferencia de $72,65, que en realidad venía del
tope de esa fecha (cargado mal en la semilla; ver la migración e28e33b0aec5).

Los importes son los del recibo; la identidad, sintética.

Correr con: python -m pytest test_reintegros.py -q
"""
import csv

import validador

CUIL = "20111111112"

HABERES = [
    ("1-026", "SUELDO BASICO", 3451.00),
    ("4-001", "ADICIONAL TECNICO", 5608.20),
    ("6-026", "BONIFICACION ESPECIAL", 5177.00),
    ("20-024", "REFRIGERIO", 1434.00),
    ("37-026", "PERMANENCIA EN EL GRUPO 26", 2588.40),
    ("100-001", "ADIC. POR JEFATURA DIRECCION", 7250.00),
    ("108-001", "ANTIGUEDAD LAUDO 15/91", 578.97),
    ("126-001", "TITULO UNIV/TERC.LAUDO15/91 - INCISO A)", 892.00),
    ("704-001", "INCREMENTO SALARIAL -SUMA FIJA", 1693.00),
    ("707-001", "ADICIONAL POR SERV. ACREDITADO", 1705.83),
    ("795-019", "COMP. P/DEDICACION ESPECIAL", 14597.00),
]
DESCUENTOS = [
    ("38-001", "APORTE PERSONAL I.N.S.S.J.Y P.", -1095.94, "pami"),
    ("42-001", "AP. PERS. JUB. ANSES", -4018.46, "jubilacion"),
    ("44-001", "SEGURO OBLIGATORIO - DGI", -3.80, None),
    ("85-117", "O.S. DE COMISARIOS NAVALES", -1095.94, "obra_social"),
    ("161-001", "IMPUESTO A LAS GANANCIAS", -10274.94, None),
    ("433-001", "IMP.GCIAS. PERIODOS ANTERIORES", 62949.21, None),
]
GENERICO = {"38-001": "PAMI", "42-001": "JUBILACION", "85-117": "OBRASOCIAL"}


def _recibo(con_seccion=True, descuentos_impresos=46460.13):
    lineas = [{"codigo": c, "descripcion": d, "importe": i, "tipo": "remuneracion",
               "categoria_universal": None} for c, d, i in HABERES]
    lineas += [{"codigo": c, "descripcion": d, "importe": i,
                "tipo": "aporte_trabajador" if cat else "otro", "categoria_universal": cat}
               for c, d, i, cat in DESCUENTOS]
    if con_seccion:
        for ln in lineas:
            ln["seccion"] = "haberes" if ln["tipo"] == "remuneracion" else "descuentos"
    return {
        "empleado": {"cuil": CUIL}, "empleador": {"cuit": "33693450239"},
        "periodo": "2015-02", "lineas": lineas,
        "totales_impresos": {"remuneraciones": 44975.40, "descuentos": descuentos_impresos,
                             "neto": 91435.53},
    }


def _conceptos(reintegro=None):
    """Catálogo como el de AEFIP. `reintegro`: el concepto 433-001 tal como
    está cargado (None = no está)."""
    cs = [{"codigo": c, "nombre": d, "tipo": "ingreso", "remunerativo": True, "alias": []}
          for c, d, _ in HABERES]
    cs += [{"codigo": c, "nombre": d, "tipo": "descuento", "remunerativo": True, "alias": [],
            "codigo_generico": GENERICO.get(c)} for c, d, _, _ in DESCUENTOS if c != "433-001"]
    cs += [{"codigo": g, "nombre": g, "tipo": "descuento", "remunerativo": True, "alias": []}
           for g in ("JUBILACION", "PAMI", "OBRASOCIAL")]
    if reintegro:
        cs.append({"codigo": "433-001", "nombre": "IMP.GCIAS. PERIODOS ANTERIORES", "alias": [],
                   **reintegro})
    return cs


FORMULAS = [
    {"target": u["codigo"], "descripcion": u["descripcion_formula"],
     "expr": f"{u['pct']} * base_remunerativa", "tolerancia": 1.0,
     "fecha_desde": None, "fecha_hasta": None, "sujeto_a_tope": True}
    for u in validador.CONCEPTOS_UNIVERSALES
]


def _topes():
    with open("data/topes_ss.csv", newline="", encoding="utf-8") as f:
        return [{**fila, "tope_maximo": float(fila["tope_maximo"]),
                 "base_minima": float(fila["base_minima"])} for fila in csv.DictReader(f)]


def _validar(conceptos, recibo):
    return validador.validar(conceptos, FORMULAS, recibo, cuil_sesion=CUIL, topes=_topes())


def _alerta(r, tipo):
    return next((a for a in r["alertas"] if a["tipo"] == tipo), None)


# ------------------------------------------------------- el recibo real ---
def test_recibo_aefip_con_reintegro_cierra_entero():
    r = _validar(_conceptos({"tipo": "descuento", "remunerativo": False}), _recibo())
    assert r["estado"] == "OK", r["discrepancias"]
    assert r["totales"] == {"remunerativo": 44975.40, "ingresos": 44975.40,
                            "descuentos": 16489.08, "reintegros": 62949.21,
                            "neto": 91435.53}, r["totales"]
    jub = next(f for f in r["formulas_validadas"] if f["codigo"] == "JUBILACION")
    assert jub["esperado"] == 4018.46 and jub["ok"], jub
    assert [x["codigo"] for x in r["reintegros"]] == ["433-001"]
    aviso = _alerta(r, "reintegro")
    assert aviso and "IMP.GCIAS. PERIODOS ANTERIORES ($62,949.21)" in aviso["detalle"]
    assert "ya tiene restado el reintegro" in aviso["detalle"], aviso["detalle"]


def test_concepto_pendiente_cargado_por_el_signo_no_cuenta_como_haber():
    # Así quedó en Pruebas: el alta automática lo hizo ingreso remunerativo.
    # Mientras nadie lo revise, manda la sección que leyó la IA.
    pendiente = {"tipo": "ingreso", "remunerativo": True, "pendiente_revision": True}
    r = _validar(_conceptos(pendiente), _recibo())
    assert r["estado"] == "OK", r["discrepancias"]
    assert r["totales"]["ingresos"] == 44975.40
    assert r["totales"]["reintegros"] == 62949.21


def test_un_concepto_revisado_en_el_rubro_equivocado_lo_corrigen_los_totales():
    # Alguien CONFIRMÓ la devolución como haber. Con el catálogo no cierra
    # ningún total impreso y con lo que dice el recibo cierran todos: gana el
    # recibo, y se avisa para que el sindicato corrija su catálogo.
    revisado = {"tipo": "ingreso", "remunerativo": False, "pendiente_revision": False}
    r = _validar(_conceptos(revisado), _recibo())
    assert r["estado"] == "OK", r["discrepancias"]
    assert r["totales"]["ingresos"] == 44975.40
    assert r["totales"]["reintegros"] == 62949.21
    aviso = _alerta(r, "concepto_mal_clasificado")
    assert aviso and aviso["codigos"] == ["433-001"]
    assert ("IMP.GCIAS. PERIODOS ANTERIORES figura entre los descuentos de tu recibo, "
            "pero tu sindicato lo tiene cargado como haber") in aviso["detalle"]


def test_sin_totales_impresos_que_lo_decidan_manda_el_catalogo():
    revisado = {"tipo": "ingreso", "remunerativo": False, "pendiente_revision": False}
    recibo = _recibo()
    recibo["totales_impresos"] = {}
    r = _validar(_conceptos(revisado), recibo)
    assert r["totales"]["ingresos"] == round(44975.40 + 62949.21, 2)
    assert r["totales"]["reintegros"] == 0.0
    assert _alerta(r, "concepto_mal_clasificado") is None


def test_si_la_ia_ubica_mal_una_linea_y_el_catalogo_cierra_manda_el_catalogo():
    # Al revés: el catálogo tiene bien la devolución (descuento) y la IA la
    # leyó entre los haberes. Con el catálogo cierran los totales: no se
    # toca nada ni se avisa.
    recibo = _recibo()
    next(ln for ln in recibo["lineas"] if ln["codigo"] == "433-001")["seccion"] = "haberes"
    r = _validar(_conceptos({"tipo": "descuento", "remunerativo": False}), recibo)
    assert r["estado"] == "OK", r["discrepancias"]
    assert r["totales"]["reintegros"] == 62949.21
    assert _alerta(r, "concepto_mal_clasificado") is None


def test_un_descuento_que_el_recibo_imprime_como_no_remunerativo_no_entra_a_la_base():
    # Al revés del caso real: cargado como descuento (con la marca de
    # remunerativo que traen los descuentos por defecto) e impreso en la
    # columna de no remunerativos. Gana el recibo, y su marca de
    # remunerativo no cuenta: lo dice la sección.
    conceptos = [
        {"codigo": "SUELDO", "nombre": "Sueldo", "tipo": "ingreso", "remunerativo": True, "alias": []},
        {"codigo": "JUBILACION", "nombre": "Jubilación", "tipo": "descuento", "remunerativo": True, "alias": []},
        {"codigo": "ACUERDO", "nombre": "Suma acuerdo", "tipo": "descuento", "remunerativo": True, "alias": []},
    ]
    recibo = {"empleado": {"cuil": CUIL}, "periodo": "2026-08", "lineas": [
        {"codigo": "SUELDO", "importe": 100000, "seccion": "haberes"},
        {"codigo": "ACUERDO", "importe": 20000, "seccion": "no_remunerativos"},
        {"codigo": "JUBILACION", "importe": -11000, "seccion": "descuentos",
         "categoria_universal": "jubilacion"},
    ], "totales_impresos": {"remuneraciones": 120000, "descuentos": 11000, "neto": 109000}}
    r = validador.validar(conceptos, [{**FORMULAS[0], "sujeto_a_tope": False}], recibo,
                          cuil_sesion=CUIL)
    assert r["estado"] == "OK", r["discrepancias"]
    assert r["totales"]["ingresos"] == 120000.0
    assert r["totales"]["remunerativo"] == 100000.0
    assert _alerta(r, "concepto_mal_clasificado")


def test_si_los_totales_no_cierran_de_ninguna_forma_manda_el_catalogo():
    revisado = {"tipo": "ingreso", "remunerativo": False, "pendiente_revision": False}
    recibo = _recibo()
    recibo["totales_impresos"]["remuneraciones"] = 1.0   # mal leído
    r = _validar(_conceptos(revisado), recibo)
    assert r["totales"]["reintegros"] == 0.0
    assert _alerta(r, "concepto_mal_clasificado") is None


def test_el_total_de_descuentos_impreso_sin_restar_el_reintegro_tambien_cierra():
    r = _validar(_conceptos({"tipo": "descuento"}), _recibo(descuentos_impresos=-16489.08))
    assert r["estado"] == "OK", r["discrepancias"]
    aviso = _alerta(r, "reintegro")
    assert aviso and "ya tiene restado" not in aviso["detalle"]


def test_un_total_de_descuentos_que_no_cierra_se_sigue_diciendo():
    r = _validar(_conceptos({"tipo": "descuento"}), _recibo(descuentos_impresos=50000))
    disc = [d for d in r["discrepancias"] if d["codigo"] == "descuentos"]
    assert disc, r["discrepancias"]
    assert "$16,489.08; $46,460.13 restando los reintegros" in disc[0]["detalle"]


# ---------------------------------------------------- debajo del tope ---
def test_un_reintegro_no_infla_la_base_de_los_aportes():
    # Arriba del tope el error no se veía (la base quedaba topeada igual).
    # Acá sí: con el reintegro en la base, la jubilación esperada se duplicaba.
    conceptos = [
        {"codigo": "SUELDO", "nombre": "Sueldo", "tipo": "ingreso", "remunerativo": True, "alias": []},
        {"codigo": "JUBILACION", "nombre": "Jubilación", "tipo": "descuento", "remunerativo": True, "alias": []},
        {"codigo": "DEVGAN", "nombre": "Devolución Ganancias", "tipo": "ingreso",
         "remunerativo": True, "alias": [], "pendiente_revision": True},
    ]
    recibo = {"empleado": {"cuil": CUIL}, "periodo": "2026-08", "lineas": [
        {"codigo": "SUELDO", "importe": 100000, "seccion": "haberes"},
        {"codigo": "JUBILACION", "importe": -11000, "seccion": "descuentos",
         "categoria_universal": "jubilacion"},
        {"codigo": "DEVGAN", "importe": 50000, "seccion": "descuentos"},
    ], "totales_impresos": {"remuneraciones": 100000, "descuentos": 39000, "neto": 139000}}
    formula = [{**FORMULAS[0], "sujeto_a_tope": False}]
    r = validador.validar(conceptos, formula, recibo, cuil_sesion=CUIL)
    assert r["estado"] == "OK", r["discrepancias"]
    assert r["totales"]["remunerativo"] == 100000.0


# --------------------------------------- descuentos impresos sin signo ---
def test_recibo_con_descuentos_sin_signo_y_reintegro_en_negativo():
    # Otros recibos imprimen la columna de descuentos sin signo; ahí el
    # reintegro es el que viene en negativo.
    conceptos = [
        {"codigo": "SUELDO", "nombre": "Sueldo", "tipo": "ingreso", "remunerativo": True, "alias": []},
        {"codigo": "JUBILACION", "nombre": "Jubilación", "tipo": "descuento", "remunerativo": True, "alias": []},
        {"codigo": "GAN", "nombre": "Ganancias", "tipo": "descuento", "remunerativo": True, "alias": []},
        {"codigo": "DEVGAN", "nombre": "Devolución Ganancias", "tipo": "descuento", "remunerativo": True, "alias": []},
    ]
    recibo = {"empleado": {"cuil": CUIL}, "periodo": "2026-08", "lineas": [
        {"codigo": "SUELDO", "importe": 100000},
        {"codigo": "JUBILACION", "importe": 11000, "categoria_universal": "jubilacion"},
        {"codigo": "GAN", "importe": 4000},
        {"codigo": "DEVGAN", "importe": -2500},
    ], "totales_impresos": {"remuneraciones": 100000, "descuentos": 12500, "neto": 87500}}
    r = validador.validar(conceptos, [FORMULAS[0]], recibo, cuil_sesion=CUIL)
    assert r["estado"] == "OK", r["discrepancias"]
    assert r["totales"] == {"remunerativo": 100000.0, "ingresos": 100000.0, "descuentos": 15000.0,
                            "reintegros": 2500.0, "neto": 87500.0}, r["totales"]


def test_un_reintegro_de_cuota_sindical_resta_de_la_retencion():
    conceptos = [
        {"codigo": "SUELDO", "nombre": "Sueldo", "tipo": "ingreso", "remunerativo": True, "alias": []},
        {"codigo": "CUOTA", "nombre": "Cuota", "tipo": "descuento", "remunerativo": True, "alias": [],
         "categoria_sindical": "afiliacion"},
        {"codigo": "DEVCUOTA", "nombre": "Devolución cuota", "tipo": "descuento", "remunerativo": True,
         "alias": [], "categoria_sindical": "afiliacion"},
    ]
    recibo = {"empleado": {"cuil": CUIL}, "periodo": "2026-08", "lineas": [
        {"codigo": "SUELDO", "importe": 100000},
        {"codigo": "CUOTA", "importe": -2000, "tipo": "aporte_trabajador"},
        {"codigo": "DEVCUOTA", "importe": 500, "tipo": "aporte_trabajador"},
    ], "totales_impresos": {}}
    r = validador.validar(conceptos, [], recibo, cuil_sesion=CUIL)
    assert r["retencion_sindical"]["afiliacion"] == 1500.0, r["retencion_sindical"]


# ------------------------------------------ alta de conceptos nuevos ---
def test_detectar_nuevos_decide_por_la_seccion_y_no_por_el_signo():
    recibo = _recibo()
    recibo["lineas"] += [
        {"codigo": "900", "descripcion": "INASISTENCIAS", "importe": -500, "seccion": "haberes"},
        {"codigo": "901", "descripcion": "SUMA NO REMUNERATIVA", "importe": 8000,
         "seccion": "no_remunerativos"},
    ]
    nuevos = {n["codigo"]: n for n in validador.detectar_nuevos(
        _conceptos(), recibo["lineas"])}
    assert set(nuevos) == {"433-001", "900", "901"}
    assert nuevos["433-001"]["tipo"] == "descuento"
    assert nuevos["433-001"]["reintegro"] is True
    assert nuevos["433-001"]["remunerativo"] is False
    # Un haber negativo sigue siendo un haber: baja el bruto.
    assert nuevos["900"]["tipo"] == "ingreso" and nuevos["900"]["remunerativo"] is True
    assert nuevos["900"]["reintegro"] is False
    assert nuevos["901"]["tipo"] == "ingreso" and nuevos["901"]["remunerativo"] is False


def test_detectar_nuevos_sin_seccion_sigue_usando_el_signo():
    # Lecturas viejas (o una IA que no la dijo): el criterio de antes.
    nuevos = validador.detectar_nuevos(_conceptos(), _recibo(con_seccion=False)["lineas"])
    assert [(n["codigo"], n["tipo"], n["reintegro"]) for n in nuevos] == [
        ("433-001", "ingreso", False)]


# ---------------------------------------- pantalla de confirmar ---
def test_totales_leidos_para_la_pantalla_de_confirmar():
    assert validador.totales_leidos(_recibo()) == {
        "ingresos": 44975.40, "descuentos": 16489.08, "reintegros": 62949.21, "neto": 91435.53}


def test_seccion_de_tolera_variantes_y_descarta_lo_que_no_es():
    casos = {"Descuentos": "descuentos", " haberes ": "haberes",
             "no remunerativos": "no_remunerativos", "No-Remunerativos": "no_remunerativos",
             "otra": None, None: None, 3: None}
    for valor, esperado in casos.items():
        assert validador.seccion_de({"seccion": valor}) == esperado, valor


# ------------------------------- qué rubro sugieren los recibos leídos ---
def test_clasificacion_vista_propone_por_mayoria_y_no_ante_un_empate():
    cv = validador.clasificacion_vista
    assert cv({}) is None
    assert cv({"descuentos": 2, "haberes": 2}) is None
    assert cv({"descuentos": 3, "haberes": 1}) == {
        "tipo": "descuento", "remunerativo": False, "veces": 3, "total": 4}
    assert cv({"haberes": 1, "no_remunerativos": 4})["remunerativo"] is False
    assert cv({"haberes": 5})["tipo"] == "ingreso"
    assert cv({"haberes": 5})["remunerativo"] is True


# ------------------------------------------------- el tope de esa fecha ---
def test_el_tope_de_febrero_2015_es_el_de_la_res_anses_449_2014():
    tope = validador.tope_vigente_en(_topes(), "2015-02")
    assert tope["vigencia_desde"] == "2014-09"
    assert tope["tope_maximo"] == 36531.48 and tope["base_minima"] == 1124.06
    assert tope["estado"] == "verificado"
    # Y en marzo ya rige el siguiente.
    assert validador.tope_vigente_en(_topes(), "2015-03")["tope_maximo"] == 43202.17
