"""Los seis controles de la grilla leída (escalas_controles.py), con grillas
ADULTERADAS a propósito: una celda cambiada, una categoría faltante, un
porcentaje distinto en un adicional, un mes salteado, dos lecturas que no
coinciden. Ninguna puede pasar los seis.

La «grilla de septiembre» de estos tests es la de agosto de 2026 (la
transcripta a mano, la única real que hay en el repo) multiplicada por el
factor que da el comunicado real de septiembre (inicial 2.552.560,34 contra
2.505.061,24): sirve para ejercitar los controles sin gastar IA.

Correr con: python -m pytest test_escalas_controles.py -q
"""
import copy
import json
from pathlib import Path

import pytest

import escalas_controles as c

AGOSTO = json.loads((Path(__file__).parent / "data" / "grillas_bancarias" / "2026-08.json").read_text(encoding="utf-8"))
DATOS_AGOSTO = {k: AGOSTO[k] for k in c.CLAVES_DATOS}
FACTOR = 2552560.34 / 2505061.24
COMUNICADO = {"inicial": 2552560.34, "roe": 73786.55, "porcentaje": 1.9, "dia_bancario_minimo": 2275519.25,
              "periodo": "2026-09"}


def escalar(datos, f=FACTOR):
    g = copy.deepcopy(datos)
    for r in g["ramas"].values():
        for cat in r["categorias"]:
            cat["basico"] = round(cat["basico"] * f, 2)
            if cat["conformado"] is not None:
                cat["conformado"] = round(cat["conformado"] * f, 2)
    for k, v in g["adicionales"].items():
        if isinstance(v, dict):
            for k2 in v:
                v[k2] = round(v[k2] * f, 2)
        else:
            g["adicionales"][k] = round(v * f, 2)
    for fila in g["roe"]["filas"]:
        fila["anual"] = [round(x * f, 2) for x in fila["anual"]]
        if fila["hasta"]:
            fila["hasta"] = round(fila["hasta"] * f)
    for k in g["dia_bancario"]:
        g["dia_bancario"][k] = round(g["dia_bancario"][k] * f, 2)
    # El día del bancario de la grilla real cierra con el comunicado: se fija el mínimo exacto.
    g["dia_bancario"]["minimo"] = round(g["dia_bancario"]["suma_fija"] + g["dia_bancario"]["por_coeficiente"], 2)
    return g


def lectura(datos, periodo_impreso="2026-09", notas=None):
    return {"contenido": copy.deepcopy(datos), "notas": notas or [], "periodo_impreso": periodo_impreso}


def controlar(datos_a, datos_b=None, com=None, periodo="2026-09", vigente="2026-08", **kw):
    b = datos_a if datos_b is None else datos_b
    return c.controlar([lectura(datos_a), lectura(b)], DATOS_AGOSTO, com if com is not None else COMUNICADO,
                       periodo, vigente, **kw)


def por_control(resultados):
    return {r["control"]: r for r in resultados}


SEPT = escalar(DATOS_AGOSTO)


def _ruta_basico(rama, nombre):
    r = SEPT["ramas"][rama]["categorias"]
    return next(f"ramas.{rama}.categorias.{i}.basico" for i, x in enumerate(r) if x["nombre"] == nombre)


# ---------------------------------------------------------------- el caso que pasa
def test_una_grilla_bien_leida_pasa_los_seis():
    r = controlar(SEPT)
    assert [x["control"] for x in r] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert c.todos_pasan(r), [(x["control"], x["resumen"]) for x in r if x["pasa"] is not True]
    assert c.fallan(r) == []
    m = por_control(r)["C4"]["medidas"]
    assert m["celdas_comparadas"] > 150 and m["desvio_max"] < 0.02


def test_la_grilla_de_agosto_contra_si_misma_no_pasa_los_seis_pero_no_falla_ninguno():
    """Sin grilla anterior (el ensayo de la primera grilla) C4 y C6 no aplican:
    quedan en None, y None nunca cuenta como aprobado."""
    r = c.controlar([lectura(DATOS_AGOSTO, "2026-08")] * 2, None, {"inicial": 2505061.24, "roe": 72413.50}, "2026-08", None)
    m = por_control(r)
    assert m["C4"]["pasa"] is None and m["C6"]["pasa"] is None
    assert m["C1"]["pasa"] and m["C2"]["pasa"] and m["C3"]["pasa"] and m["C5"]["pasa"]
    assert not c.todos_pasan(r)


# ---------------------------------------------------------------- adulteraciones: ninguna pasa los seis
def test_una_celda_cambiada_la_atrapan_el_factor_y_la_coherencia():
    g = c.asignar(SEPT, _ruta_basico("administrativa", "10 años"), 2_027_723.08 + 100)
    r = por_control(controlar(g))
    assert r["C4"]["pasa"] is False and r["C5"]["pasa"] is False
    assert any(d["etiqueta"].endswith("10 años · básico") for d in r["C4"]["detalle"])
    assert not c.todos_pasan(controlar(g))


def test_un_digito_mal_leido_con_las_dos_lecturas_iguales_igual_se_atrapa():
    """La doble lectura no alcanza: si las dos leen el mismo dígito mal, el
    factor y la coherencia lo cazan."""
    g = c.asignar(SEPT, _ruta_basico("maestranza", "20 años"), 2_227_619.07)       # 2.221... leído 2.227...
    r = controlar(g, g)
    assert por_control(r)["C2"]["pasa"] is True
    assert not c.todos_pasan(r) and "C4" in c.fallan(r)


def test_un_cambio_de_un_peso_en_una_celda_grande_se_atrapa():
    ruta = _ruta_basico("administrativa", "Jefe Dep. de 1a.")
    valor = next(x for x in c.celdas(SEPT) if x["ruta"] == ruta)["valor"]
    r = por_control(controlar(c.asignar(SEPT, ruta, valor + 1)))
    assert r["C4"]["pasa"] is False or r["C5"]["pasa"] is False


def test_una_categoria_faltante_rompe_la_estructura():
    g = copy.deepcopy(SEPT)
    quitada = g["ramas"]["administrativa"]["categorias"].pop(7)
    r = por_control(controlar(g))
    assert r["C1"]["pasa"] is False
    assert any(d.get("problema") == "categoría que falta" and quitada["nombre"] in d["etiqueta"] for d in r["C1"]["detalle"])
    assert not c.todos_pasan(controlar(g))


def test_una_categoria_que_sobra_rompe_la_estructura():
    g = copy.deepcopy(SEPT)
    g["ramas"]["ordenanza"]["categorias"].append({"nombre": "Categoría nueva", "anios": None, "coef": 3.0,
                                                  "basico": 4_000_000.0, "conformado": None})
    r = por_control(controlar(g))
    assert r["C1"]["pasa"] is False and any(d["problema"] == "categoría que sobra" for d in r["C1"]["detalle"])


def test_un_porcentaje_distinto_en_un_adicional_rompe_el_factor_unico():
    g = copy.deepcopy(SEPT)
    g["adicionales"]["guarderia"] = round(g["adicionales"]["guarderia"] * 1.05, 2)
    r = por_control(controlar(g))
    assert r["C4"]["pasa"] is False
    assert [d["etiqueta"] for d in r["C4"]["detalle"] if "etiqueta" in d] == ["Adicional · guarderia"]
    assert r["C1"]["pasa"] is True                  # la estructura está bien: es un problema de importe
    assert not c.todos_pasan(controlar(g))


def test_un_mes_salteado_no_pasa_el_periodo():
    r = controlar(SEPT, periodo="2026-10", com={**COMUNICADO, "periodo": "2026-10"})
    assert por_control(r)["C6"]["pasa"] is False
    assert any(d["problema"] == "no es el mes siguiente al vigente" for d in por_control(r)["C6"]["detalle"])
    assert not c.todos_pasan(r)


def test_el_periodo_que_imprime_el_pdf_tiene_que_ser_el_esperado():
    l1, l2 = lectura(SEPT, "2026-08"), lectura(SEPT, "2026-08")
    r = por_control(c.controlar([l1, l2], DATOS_AGOSTO, COMUNICADO, "2026-09", "2026-08"))
    assert r["C6"]["pasa"] is False
    r = por_control(c.controlar([lectura(SEPT, None), lectura(SEPT, None)], DATOS_AGOSTO, COMUNICADO, "2026-09", "2026-08"))
    assert r["C6"]["pasa"] is False      # un período sin leer no pasa


def test_el_comunicado_de_otro_mes_no_pasa_el_periodo():
    r = por_control(controlar(SEPT, com={**COMUNICADO, "periodo": "2026-08"}))
    assert r["C6"]["pasa"] is False


def test_dos_lecturas_que_no_coinciden_no_pasan_la_doble_lectura():
    b = c.asignar(SEPT, _ruta_basico("administrativa", "3 años"), 1_673_913.52)       # un centavo
    r = controlar(SEPT, b)
    m = por_control(r)
    assert m["C2"]["pasa"] is False
    assert m["C2"]["detalle"][0]["ruta"].endswith("categorias.3.basico")
    assert not c.todos_pasan(r)


def test_dos_lecturas_con_un_nombre_distinto_tampoco_coinciden():
    b = copy.deepcopy(SEPT)
    b["ramas"]["administrativa"]["categorias"][3]["nombre"] = "3 Años"
    assert por_control(controlar(SEPT, b))["C2"]["pasa"] is False


def test_una_sola_lectura_no_alcanza():
    r = c.controlar([lectura(SEPT)], DATOS_AGOSTO, COMUNICADO, "2026-09", "2026-08")
    assert por_control(r)["C2"]["pasa"] is False and not c.todos_pasan(r)


# ---------------------------------------------------------------- C1 en detalle
def test_una_celda_sin_leer_no_pasa():
    ruta = _ruta_basico("administrativa", "5 años")
    r = por_control(controlar(c.asignar(SEPT, ruta, None)))
    assert r["C1"]["pasa"] is False and any(d["problema"] == "celda sin leer" and d["ruta"] == ruta for d in r["C1"]["detalle"])


def test_la_ia_que_anota_una_diferencia_hace_retener():
    l = lectura(SEPT, notas=["falta la categoría Jefe de Equipo de 3º"])
    r = por_control(c.controlar([l, l], DATOS_AGOSTO, COMUNICADO, "2026-09", "2026-08"))
    assert r["C1"]["pasa"] is False


def test_un_coeficiente_distinto_es_un_cambio_de_estructura():
    g = c.asignar(SEPT, "ramas.administrativa.categorias.5.coef", 1.18)
    r = por_control(controlar(g))
    assert r["C1"]["pasa"] is False and any(d["problema"] == "cambió el coef" for d in r["C1"]["detalle"])


def test_conectividad_de_un_trimestre_ya_publicado_no_cambia_sola():
    g = copy.deepcopy(SEPT)
    g["conectividad"][1]["mensual"] = 99999.0
    assert por_control(controlar(g))["C1"]["pasa"] is False


def test_un_trimestre_nuevo_de_conectividad_retiene_siempre_con_el_detalle_para_revisarlo():
    """Decisión conservadora a propósito (RETENER_TRIMESTRE_NUEVO_DE_CONECTIVIDAD): el trimestre
    consecutivo siguiente no tiene control propio, así que la grilla queda retenida y se revisa a mano."""
    g = copy.deepcopy(SEPT)
    g["conectividad"].append({"meses": ["2026-12", "2027-01", "2027-02"], "diario": 3300.0, "mas_de_4_dias": 29000.0, "mensual": 71000.0})
    r = por_control(controlar(g))["C1"]
    assert r["pasa"] is False
    d = next(x for x in r["detalle"] if x["problema"].startswith("Trimestre nuevo de conectividad 2026-12 a 2027-02"))
    assert "revisarlo a mano contra el PDF" in d["problema"]
    assert d["leido"]["mensual"] == 71000.0 and d["cociente_contra_el_anterior"]["mensual"] == round(71000.0 / 67193, 4)
    sin = copy.deepcopy(SEPT)
    sin["conectividad"] = [x for x in sin["conectividad"] if "2026-09" not in x["meses"]]
    assert por_control(controlar(sin))["C1"]["pasa"] is False


def test_la_conectividad_de_otro_trimestre_o_de_mas_no_pasa_ni_se_revisa_como_nueva():
    salteado = copy.deepcopy(SEPT)
    salteado["conectividad"].append({"meses": ["2027-03", "2027-04", "2027-05"], "diario": 1.0, "mas_de_4_dias": 2.0, "mensual": 3.0})
    r = por_control(controlar(salteado))["C1"]
    assert r["pasa"] is False and any("no es el trimestre siguiente" in d["problema"] for d in r["detalle"])
    dos = copy.deepcopy(SEPT)
    dos["conectividad"] += [{"meses": ["2026-12", "2027-01", "2027-02"], "diario": 3.0, "mas_de_4_dias": 4.0, "mensual": 5.0},
                            {"meses": ["2027-03", "2027-04", "2027-05"], "diario": 3.0, "mas_de_4_dias": 4.0, "mensual": 5.0}]
    assert any("más de una" in d["problema"] for d in por_control(controlar(dos))["C1"]["detalle"])


def test_la_conectividad_no_entra_en_el_factor_unico():
    g = copy.deepcopy(SEPT)
    g["conectividad"][1]["mensual"] = g["conectividad"][1]["mensual"] * 1.5       # lo cazaría C1, no C4
    assert por_control(controlar(g))["C4"]["pasa"] is True


# ---------------------------------------------------------------- C3
def test_las_anclas_se_controlan_al_centavo():
    r = por_control(controlar(SEPT, com={**COMUNICADO, "inicial": 2552560.35}))
    assert r["C3"]["pasa"] is False
    r = por_control(controlar(SEPT, com={**COMUNICADO, "roe": 73786.60}))
    assert r["C3"]["pasa"] is False and any("ROE" in d["ancla"] for d in r["C3"]["detalle"])
    r = por_control(controlar(SEPT, com={**COMUNICADO, "dia_bancario_minimo": 2275519.99}))
    assert r["C3"]["pasa"] is False
    r = por_control(controlar(SEPT, com={**COMUNICADO, "dia_bancario_minimo": None}))
    assert r["C3"]["pasa"] is True              # el comunicado de octubre no trae el mínimo


def test_sin_comunicado_las_anclas_no_pasan():
    r = c.controlar([lectura(SEPT)] * 2, DATOS_AGOSTO, None, "2026-09", "2026-08")
    assert por_control(r)["C3"]["pasa"] is False


def test_el_inicial_leido_mal_en_una_rama_se_atrapa():
    ini = next(i for i, x in enumerate(SEPT["ramas"]["maestranza"]["categorias"]) if x["anios"] == 0)
    g = c.asignar(SEPT, f"ramas.maestranza.categorias.{ini}.conformado", 2_552_560.43)
    assert por_control(controlar(g))["C3"]["pasa"] is False


# ---------------------------------------------------------------- C4 en detalle
def test_el_factor_tiene_que_redondear_al_porcentaje_del_comunicado():
    r = por_control(controlar(SEPT, com={**COMUNICADO, "porcentaje": 2.5}))
    assert r["C4"]["pasa"] is False and any("porcentaje" in d.get("problema", "") for d in r["C4"]["detalle"])
    assert por_control(controlar(SEPT, com={**COMUNICADO, "porcentaje": 1.9}))["C4"]["pasa"] is True


def test_los_topes_del_roe_se_aceptan_iguales_o_escalados_pero_no_otra_cosa():
    iguales = copy.deepcopy(SEPT)
    for fila, orig in zip(iguales["roe"]["filas"], DATOS_AGOSTO["roe"]["filas"]):
        fila["hasta"] = orig["hasta"]
    r = por_control(controlar(iguales))
    assert r["C4"]["pasa"] is True and r["C4"]["medidas"]["topes_hasta"] == ["igual"]
    assert por_control(controlar(SEPT))["C4"]["medidas"]["topes_hasta"] == ["escalado"]
    raro = c.asignar(SEPT, "roe.filas.0.hasta", 3_500_000)
    assert por_control(controlar(raro))["C4"]["pasa"] is False


def test_la_tolerancia_es_un_parametro():
    ruta = _ruta_basico("administrativa", "8 años")
    valor = next(x for x in c.celdas(SEPT) if x["ruta"] == ruta)["valor"]
    g = c.asignar(SEPT, ruta, round(valor + 0.04, 2))
    assert por_control(controlar(g))["C4"]["pasa"] is False
    assert por_control(controlar(g, tolerancias={"c4_extra": 0.1, "c5_pesos": 2.0}))["C4"]["pasa"] is True


def test_pocas_celdas_no_alcanzan_para_medir_el_factor():
    chica = {"contenido": {"ramas": {}, "adicionales": {"guarderia": 1000.0}, "conectividad": [], "roe": {"tramos": [], "filas": []},
                           "dia_bancario": {}}}
    prev = {"ramas": {}, "adicionales": {"guarderia": 990.0}, "conectividad": [], "roe": {"tramos": [], "filas": []}, "dia_bancario": {}}
    assert c.c4_factor_unico(chica, prev, COMUNICADO)["pasa"] is False


# ---------------------------------------------------------------- C5 en detalle
def test_el_escalafon_no_puede_decrecer():
    ruta = "ramas.administrativa.categorias.12.coef"           # 12 años: 1,43
    g = c.asignar(SEPT, ruta, 1.01)
    r = por_control(controlar(g))
    assert r["C5"]["pasa"] is False and any("decrece" in d["problema"] for d in r["C5"]["detalle"])


def test_el_basico_por_debajo_del_piso_o_inconsistente_con_el_coeficiente_no_pasa():
    ruta = _ruta_basico("administrativa", "Inicial")
    r = por_control(controlar(c.asignar(SEPT, ruta, 1_600_000.0)))
    assert r["C5"]["pasa"] is False
    ruta = _ruta_basico("ordenanza", "Mayordomo Gral.")
    r = por_control(controlar(c.asignar(SEPT, ruta, 3_000_000.0)))
    assert r["C5"]["pasa"] is False


def test_el_roe_y_el_dia_del_bancario_se_controlan_por_dentro():
    g = c.asignar(SEPT, "roe.filas.1.anual.3", 1.0)
    assert por_control(controlar(g))["C5"]["pasa"] is False
    g = c.asignar(SEPT, "dia_bancario.minimo", SEPT["dia_bancario"]["minimo"] + 10)
    r = por_control(controlar(g))
    assert r["C5"]["pasa"] is False


def test_los_titulos_tienen_que_crecer():
    g = copy.deepcopy(SEPT)
    g["adicionales"]["titulos"]["secundario"], g["adicionales"]["titulos"]["universitario"] = (
        g["adicionales"]["titulos"]["universitario"], g["adicionales"]["titulos"]["secundario"])
    assert por_control(controlar(g))["C5"]["pasa"] is False


def test_la_irregularidad_de_un_peso_de_la_grilla_firmada_de_ordenanza_no_hace_retener_a_c5():
    """La grilla firmada de agosto trae en ordenanza diferencias de hasta ~1,7
    contra coeficiente × unidad (es la fuente, no un error): C5 las tolera
    (c5_pesos = 2); un error de un dígito (decenas de pesos) no."""
    assert c.c5_coherencia(lectura(DATOS_AGOSTO))["pasa"] is True
    g = c.asignar(DATOS_AGOSTO, "ramas.ordenanza.categorias.10.basico",
                  DATOS_AGOSTO["ramas"]["ordenanza"]["categorias"][10]["basico"] + 20)
    assert c.c5_coherencia(lectura(g))["pasa"] is False


# ---------------------------------------------------------------- forma, helpers
def test_la_forma_valida_de_la_grilla_real_y_las_rotas():
    assert c.forma_valida(AGOSTO) == []
    for rota in ({**AGOSTO, "ramas": {}}, {k: v for k, v in AGOSTO.items() if k != "roe"},
                 c.asignar({**AGOSTO}, "adicionales.guarderia", None),
                 {**AGOSTO, "periodo": ""}):
        assert c.forma_valida(rota)
    sin_admin = copy.deepcopy(AGOSTO)
    sin_admin["ramas"].pop("administrativa")
    assert any("administrativa" in p for p in c.forma_valida(sin_admin))


def test_todos_pasan_exige_seis_verdaderos():
    ok = {"pasa": True}
    assert c.todos_pasan([ok] * 6)
    assert not c.todos_pasan([ok] * 5)
    assert not c.todos_pasan([ok] * 5 + [{"pasa": None}])
    assert not c.todos_pasan([ok] * 5 + [{"pasa": False}])


def test_un_control_que_revienta_no_cuenta_como_aprobado():
    r = c.controlar([{"contenido": {}}, {"contenido": {}}], DATOS_AGOSTO, COMUNICADO, "2026-09", "2026-08")
    assert not c.todos_pasan(r) and all(x["pasa"] is not True for x in r if x["control"] in ("C1", "C3", "C5"))


def test_asignar_no_crea_estructura_ni_toca_el_original():
    original = copy.deepcopy(SEPT)
    nuevo = c.asignar(SEPT, "adicionales.guarderia", 1.0)
    assert SEPT == original and nuevo["adicionales"]["guarderia"] == 1.0
    for ruta in ("adicionales.no_existe", "ramas.administrativa.categorias.999.basico", "ramas.no.categorias.0.basico"):
        with pytest.raises((KeyError, IndexError, ValueError)):
            c.asignar(SEPT, ruta, 1.0)


def test_comparar_con_publicada_celda_por_celda():
    leida = copy.deepcopy(DATOS_AGOSTO)
    assert c.comparar_con_publicada(leida, AGOSTO)["distintas"] == 0
    leida = c.asignar(leida, "adicionales.guarderia", 1.0)
    leida["ramas"]["administrativa"]["categorias"].pop()
    cmp = c.comparar_con_publicada(leida, AGOSTO)
    assert cmp["distintas"] >= 5 and any(d["etiqueta"] == "Adicional · guarderia" for d in cmp["detalle"])
    assert cmp["iguales"] + cmp["distintas"] == cmp["celdas"]


# ---------------------------------------------------------------- C4 al centavo (bloque 5, corrección del QA)
def test_los_comunicados_reales_admiten_un_factor_comun_al_centavo():
    """Los únicos importes reales de septiembre y octubre (inicial, ROE mensual y mínimo del Día del
    Bancario) son agosto × un mismo factor, redondeado al centavo, en cada paso."""
    reales = {"ago-sep": [(2505061.24, 2552560.34), (72413.50, 73786.55), (2233175.44, 2275519.25)],
              "sep-oct": [(2552560.34, 2608320.16), (73786.55, 75398.39)]}
    for paso, pares in reales.items():
        intervalos = [((n - 0.005) / a, (n + 0.005) / a) for a, n in pares]
        f, fuera = c._factor_de_mayor_cobertura(intervalos)
        assert not fuera, paso
        assert all(round(a * f, 2) == n for a, n in pares), paso


def test_tres_centavos_de_error_en_un_basico_se_atrapan_aunque_las_dos_lecturas_coincidan():
    """El piso de C4 es lo que explica el redondeo (0,0102 + 0,005 × coeficiente, ~1,7 centavos en este
    básico): un error menor se confunde con el redondeo y lo cubre C2/C5."""
    ruta = _ruta_basico("administrativa", "8 años")
    valor = next(x for x in c.celdas(SEPT) if x["ruta"] == ruta)["valor"]
    for delta in (0.03, -0.03, 0.05):
        r = por_control(controlar(c.asignar(SEPT, ruta, round(valor + delta, 2))))["C4"]
        assert r["pasa"] is False and any(d["ruta"] == ruta for d in r["detalle"]), delta


def test_si_las_celdas_no_admiten_un_factor_unico_c4_lista_las_que_rompen():
    ruta = "adicionales.guarderia"
    valor = next(x for x in c.celdas(SEPT) if x["ruta"] == ruta)["valor"]
    r = por_control(controlar(c.asignar(SEPT, ruta, round(valor * 1.001, 2))))["C4"]
    assert r["pasa"] is False and [d["ruta"] for d in r["detalle"] if "ruta" in d] == [ruta]


def test_un_tope_hasta_no_entero_o_corrido_en_dos_pesos_no_pasa():
    # D26 (2026-11-16): hasta 1 peso de diferencia contra el valor escalado SÍ pasa (el sindicato
    # a veces trunca en vez de redondear); a 2 pesos o más, o con decimales, sigue reteniendo.
    escalado = next(x for x in c.celdas(SEPT) if x["ruta"] == "roe.filas.0.hasta")["valor"]
    for malo in (escalado + 2, escalado - 2, escalado + 0.5, escalado + 100):
        assert por_control(controlar(c.asignar(SEPT, "roe.filas.0.hasta", malo)))["C4"]["pasa"] is False, malo


# ---------------------------------------------------------------- la primera grilla real (septiembre 2026)
COMUNICADO_REAL = {"inicial": 2552560.34, "roe": 73786.55, "porcentaje": 1.9, "dia_bancario_minimo": 2275519.25,
                   "periodo": "2026-09"}
TOPES_REALES = (3337736, 4323405, 5188128)          # el sindicato TRUNCÓ el segundo y el tercero


def septiembre_real():
    """Agosto × 1,01896125 al centavo, con los dos hechos de la grilla real: los topes `hasta` del
    ROE truncados y sin el trimestre 2026-06/08 de conectividad (terminó; el PDF solo trae 2026-09/11,
    idéntico al publicado). Los anclas del comunicado se fijan al centavo (el factor redondeado a
    8 decimales no cae exacto en todas las celdas)."""
    g = escalar(DATOS_AGOSTO, 1.01896125)
    for fila, hasta in zip(g["roe"]["filas"], TOPES_REALES + (None,)):
        fila["hasta"] = hasta
    g["conectividad"] = [copy.deepcopy(DATOS_AGOSTO["conectividad"][1])]
    for rk, r in DATOS_AGOSTO["ramas"].items():
        inicial = r["categorias"][0]["conformado"]
        for i, cat in enumerate(r["categorias"]):
            if cat["conformado"] == inicial:
                g["ramas"][rk]["categorias"][i]["conformado"] = 2552560.34
    g["dia_bancario"]["minimo"] = 2275519.25
    g["dia_bancario"]["por_coeficiente"] = round(g["dia_bancario"]["por_coeficiente"] + 0.01, 2)
    return g


def _real(g, **kw):
    return por_control(controlar(g, com=COMUNICADO_REAL, **kw))


def test_la_septiembre_real_con_topes_truncados_y_trimestre_vencido_ausente_pasa_los_seis():
    g = septiembre_real()
    assert [x["valor"] for x in c.celdas(g) if x["tipo"] == "hasta"][:3] == list(TOPES_REALES)
    r = _real(g)
    assert all(x["pasa"] is True for x in r.values()), {k: (v["pasa"], v["resumen"], v["detalle"][:2]) for k, v in r.items()}
    assert r["C4"]["medidas"]["exceso_max"] == 0 and r["C4"]["medidas"]["topes_hasta"] == ["escalado"]
    # D27: C1 lo dice en su detalle y el contenido que se guarda conserva el trimestre.
    assert "conservada de la grilla anterior" in r["C1"]["resumen"]
    assert r["C1"]["detalle"][0]["meses"] == ["2026-06", "2026-07", "2026-08"]
    cons = c.conectividad_conservada(DATOS_AGOSTO, g, "2026-09")
    assert [x["meses"][0] for x in cons] == ["2026-06"]
    guardado = c.con_conectividad_conservada(g, cons)
    assert [x["meses"][0] for x in guardado["conectividad"]] == ["2026-06", "2026-09"]       # cronológico
    assert guardado["conectividad"][0] == DATOS_AGOSTO["conectividad"][0]
    assert c.forma_valida({**guardado, "periodo": "2026-09", "nombre": "x", "firmada": "x"}) == []
    # Y la grilla guardada, con la entrada conservada, vuelve a pasar C1 (corregir a mano la re-controla).
    assert c.c1_estructura({"contenido": guardado, "notas": []}, DATOS_AGOSTO, "2026-09")["pasa"] is True


def test_d26_un_tope_a_un_peso_pasa_y_a_dos_no():
    g = septiembre_real()
    assert _real(c.asignar(g, "roe.filas.1.hasta", 4323406))["C4"]["pasa"] is True       # redondeado
    assert _real(c.asignar(g, "roe.filas.1.hasta", 4323404))["C4"]["pasa"] is False      # 1,72 del escalado
    assert _real(c.asignar(g, "roe.filas.0.hasta", 3337738))["C4"]["pasa"] is False      # a 2 pesos
    assert _real(c.asignar(g, "roe.filas.0.hasta", 3337736.5))["C4"]["pasa"] is False    # no entero
    assert _real(c.asignar(g, "roe.filas.2.hasta", 5188120))["C4"]["pasa"] is False      # un dígito mal leído


def test_d26_no_afloja_los_importes_que_siguen_al_centavo():
    g = septiembre_real()
    ruta = _ruta_basico("administrativa", "8 años")
    valor = next(x for x in c.celdas(g) if x["ruta"] == ruta)["valor"]
    assert _real(c.asignar(g, ruta, round(valor + 0.04, 2)))["C4"]["pasa"] is False


def test_d27_falta_el_trimestre_que_cubre_el_periodo():
    g = septiembre_real()
    g["conectividad"] = []
    r = _real(g)["C1"]
    assert r["pasa"] is False
    assert any(d["problema"] == "falta la conectividad de un trimestre ya publicado" and d["etiqueta"] == "2026-09+2026-10+2026-11"
               for d in r["detalle"])


def test_d27_el_trimestre_vigente_con_un_importe_cambiado_no_pasa():
    g = septiembre_real()
    g["conectividad"][0]["mensual"] = 67194
    r = _real(g)["C1"]
    assert r["pasa"] is False and any(d["problema"] == "cambió la conectividad de un trimestre ya publicado" for d in r["detalle"])


def test_d27_un_trimestre_vencido_que_si_viene_tiene_que_ser_identico():
    g = septiembre_real()
    g["conectividad"].insert(0, copy.deepcopy(DATOS_AGOSTO["conectividad"][0]))
    r = _real(g)
    assert r["C1"]["pasa"] is True and r["C1"]["detalle"] == []              # idéntico: nada que conservar
    assert c.conectividad_conservada(DATOS_AGOSTO, g, "2026-09") == []
    g["conectividad"][0]["diario"] = 2891
    r = _real(g)["C1"]
    assert r["pasa"] is False and any(d.get("antes") == 2890 and d.get("ahora") == 2891 for d in r["detalle"])


def test_d27_un_trimestre_nuevo_sigue_reteniendo_siempre():
    g = septiembre_real()
    g["conectividad"].append({"meses": ["2026-12", "2027-01", "2027-02"], "diario": 3300.0, "mas_de_4_dias": 29000.0, "mensual": 71000.0})
    r = _real(g)["C1"]
    assert r["pasa"] is False and any(d["problema"].startswith("Trimestre nuevo de conectividad") for d in r["detalle"])


def test_d27_un_trimestre_que_no_vencio_no_se_conserva():
    # El que cubre el período o es posterior nunca se conserva: tiene que venir.
    assert c.conectividad_vencida(["2026-06", "2026-07", "2026-08"], "2026-09") is True
    assert c.conectividad_vencida(["2026-07", "2026-08", "2026-09"], "2026-09") is False
    assert c.conectividad_vencida(["2026-09", "2026-10", "2026-11"], "2026-09") is False
    assert c.conectividad_vencida(["2026-06", "2026-07", "2026-08"], None) is False
    assert c.conectividad_conservada(None, {}, "2026-09") == []
