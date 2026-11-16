"""Tests del motor de la consulta de escalas (consulta_escalas.py). Sin base."""
import copy
import itertools
import json
import os

import pytest

import consulta_escalas as ce

_AQUI = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_AQUI, "data", "grillas_bancarias", "2026-08.json"), encoding="utf-8") as f:
    AGOSTO = json.load(f)


def _escalada(grilla, factor, periodo, nombre):
    """Copia sintética de la grilla con todos los importes multiplicados."""
    g = copy.deepcopy(grilla)
    g["periodo"], g["nombre"] = periodo, nombre
    for rama in g["ramas"].values():
        for c in rama["categorias"]:
            for k in ("basico", "conformado"):
                if c.get(k):
                    c[k] = round(c[k] * factor, 2)
    return g


GRILLAS = {"2026-08": AGOSTO}
SEL = {"rama": "administrativa", "anios": 6, "titulo": "universitario", "caja": False}


def _por_clave(resp):
    return {c["clave"]: c for c in resp["conceptos"]}


# ------------------------------------------------------------ aceptación
def test_criterio_de_aceptacion_agosto_2026():
    r = ce.consultar(SEL, GRILLAS)
    c = _por_clave(r)
    assert r["periodo"] == "2026-08"
    assert c["basico"]["importe"] == 1768880.32
    assert c["conformado"]["importe"] == 2511567.97
    assert c["titulo"]["importe"] == 97604.47
    assert "funcion_cajero" not in c and "falla_caja" not in c
    cat = AGOSTO["ramas"]["administrativa"]["categorias"][6]
    assert (cat["basico"], cat["conformado"]) == (1768880.32, 2511567.97)
    assert AGOSTO["adicionales"]["titulos"]["universitario"] == 97604.47
    assert c["basico"]["etiqueta"] == ce.PUBLICADO
    assert r["alcance"] == ce.TEXTO_ALCANCE
    assert r["fuentes"] == AGOSTO["fuentes"] and r["firmada"] == "2026-09-11"


def test_tres_ramas():
    for rama in ce.RAMAS:
        r = ce.consultar({"rama": rama, "anios": 3}, GRILLAS)
        cats = AGOSTO["ramas"][rama]["categorias"]
        cat = next(x for x in cats if x["anios"] == 3)
        assert _por_clave(r)["basico"]["importe"] == cat["basico"]


def test_anios_intermedios_toman_el_tramo_cumplido_mas_alto():
    r = ce.consultar({"rama": "maestranza", "anios": 40}, GRILLAS)
    cat35 = next(x for x in AGOSTO["ramas"]["maestranza"]["categorias"] if x["anios"] == 35)
    assert _por_clave(r)["basico"]["importe"] == cat35["basico"]
    r = ce.consultar({"rama": "administrativa", "anios": 17}, GRILLAS)
    cat15 = next(x for x in AGOSTO["ramas"]["administrativa"]["categorias"] if x["anios"] == 15)
    assert _por_clave(r)["basico"]["importe"] == cat15["basico"]


def test_jerarquia_sin_conformado_y_evolucion_sobre_basico():
    sel = {"rama": "administrativa", "jerarquia": "Jefe Div. de 1a."}
    r = ce.consultar(sel, GRILLAS)
    c = _por_clave(r)
    assert c["basico"]["importe"] == 3847314.71
    assert "conformado" not in c
    g2 = _escalada(AGOSTO, 1.019, "2026-09", "Septiembre 2026")
    ev = ce.evolucion(sel, {"2026-08": AGOSTO, "2026-09": g2})
    assert [m["concepto"] for m in ev["meses"]] == ["basico", "basico"]
    assert ev["meses"][0]["importe"] == 3847314.71


def test_caja_agrega_dos_conceptos():
    r = ce.consultar({"rama": "administrativa", "anios": 0, "caja": True}, GRILLAS)
    c = _por_clave(r)
    assert c["funcion_cajero"]["importe"] == 163963.06
    assert c["falla_caja"]["importe"] == 287355.05


def test_roe_por_defecto_es_el_del_comunicado():
    r = ce.consultar(SEL, GRILLAS)
    roe = _por_clave(r)["roe"]
    assert roe["importe"] == 72413.50
    assert roe["etiqueta"] == ce.REFERENCIA
    assert "depende de tu banco" in roe["nota"]


def test_roe_con_tramo_usa_la_fila_del_conformado():
    # conformado 2.511.567,97 <= 3.275.626: fila 0; tramo 3 (14,5% a 19,75%)
    r = ce.consultar({**SEL, "tramo_roe": 3}, GRILLAS)
    roe = _por_clave(r)["roe"]
    assert roe["importe"] == round(1357708.22 / 12, 2)
    assert roe["etiqueta"] == ce.REFERENCIA
    # una jerarquía alta cae en otra fila (básico 7.208.187,32 -> última)
    r = ce.consultar({"rama": "administrativa", "jerarquia": "SubGte. Deptal de 1a.", "tramo_roe": 5}, GRILLAS)
    assert _por_clave(r)["roe"]["importe"] == round(5339346.99 / 12, 2)


def test_periodo_pedido_y_vigente():
    g2 = _escalada(AGOSTO, 1.019, "2026-09", "Septiembre 2026")
    grillas = {"2026-08": AGOSTO, "2026-09": g2}
    assert ce.consultar(SEL, grillas)["periodo"] == "2026-09"
    assert ce.consultar(SEL, grillas, "2026-08")["periodo"] == "2026-08"
    with pytest.raises(ce.ConsultaInvalida):
        ce.consultar(SEL, grillas, "2026-07")
    with pytest.raises(ce.ConsultaInvalida):
        ce.consultar(SEL, {})


def test_dato_que_falta_no_se_inventa():
    g = copy.deepcopy(AGOSTO)
    del g["adicionales"]["titulos"]["universitario"]
    del g["adicionales"]["falla_caja"]
    del g["roe"]
    r = ce.consultar({**SEL, "caja": True}, {"2026-08": g})
    c = _por_clave(r)
    assert "titulo" not in c and "falla_caja" not in c and "roe" not in c
    assert "funcion_cajero" in c


# ------------------------------------------------------------- opciones
def test_opciones():
    o = ce.opciones(AGOSTO)
    assert [r["clave"] for r in o["ramas"]] == ["administrativa", "maestranza", "ordenanza"]
    adm = o["ramas"][0]
    assert adm["anios"][:3] == [0, 1, 2] and adm["anios"][-1] == 35
    assert "Jefe Div. de 1a." in adm["jerarquias"] and len(adm["jerarquias"]) == 16
    assert [t["clave"] for t in o["titulos"]] == ["sin", "secundario", "terciario", "universitario"]
    assert len(o["tramos_roe"]) == 6 and o["tramos_roe"][1]["rotulo"] == "3,5% a 8,75%"


# ------------------------------------------------------------ evolución
def test_evolucion_dos_y_tres_grillas_con_salto():
    g2 = _escalada(AGOSTO, 1.019, "2026-09", "Septiembre 2026")
    g3 = _escalada(AGOSTO, 1.04, "2026-10", "Octubre 2026")
    ev = ce.evolucion(SEL, {"2026-08": AGOSTO, "2026-09": g2})
    m = ev["meses"]
    assert [x["periodo"] for x in m] == ["2026-08", "2026-09"]
    assert m[0]["concepto"] == "conformado" and m[0]["importe"] == 2511567.97
    assert m[0]["variacion_pct"] is None
    assert m[1]["variacion_pct"] == 1.9
    assert ev["alcance"] == ce.TEXTO_EVOLUCION
    # mes salteado: sin septiembre, octubre no compara contra agosto
    ev = ce.evolucion(SEL, {"2026-08": AGOSTO, "2026-10": g3})
    assert [x["periodo"] for x in ev["meses"]] == ["2026-08", "2026-10"]
    assert ev["meses"][1]["variacion_pct"] is None
    # tres seguidos
    ev = ce.evolucion(SEL, {"2026-08": AGOSTO, "2026-09": g2, "2026-10": g3})
    assert [x["variacion_pct"] for x in ev["meses"]][0] is None
    assert ev["meses"][2]["variacion_pct"] is not None


def test_evolucion_cruza_de_anio():
    dic = _escalada(AGOSTO, 1.0, "2026-12", "Diciembre 2026")
    ene = _escalada(AGOSTO, 1.02, "2027-01", "Enero 2027")
    ev = ce.evolucion(SEL, {"2026-12": dic, "2027-01": ene})
    assert ev["meses"][1]["variacion_pct"] == 2.0


# ------------------------------------------------------------ inválidas
@pytest.mark.parametrize("sel", [
    {},
    "x",
    {"rama": "x", "anios": 1},
    {"rama": "administrativa"},
    {"rama": "administrativa", "anios": -1},
    {"rama": "administrativa", "anios": "abc"},
    {"rama": "administrativa", "anios": 1.5},
    {"rama": "administrativa", "anios": 999},
    {"rama": "administrativa", "anios": 1, "jerarquia": "Jefe Div. de 1a."},
    {"rama": "administrativa", "jerarquia": "Inventada"},
    {"rama": "maestranza", "jerarquia": "Jefe Div. de 1a."},
    {"rama": "administrativa", "anios": 1, "titulo": "doctorado"},
    {"rama": "administrativa", "anios": 1, "caja": "si"},
    {"rama": "administrativa", "anios": 1, "tramo_roe": 6},
    {"rama": "administrativa", "anios": 1, "tramo_roe": "x"},
])
def test_seleccion_invalida(sel):
    with pytest.raises(ce.ConsultaInvalida) as e:
        ce.validar_seleccion(sel, AGOSTO)
    assert str(e.value)
    with pytest.raises(ce.ConsultaInvalida):
        ce.consultar(sel, GRILLAS)


def test_seleccion_normalizada():
    s = ce.validar_seleccion({"rama": "ordenanza", "anios": "4", "titulo": "sin"}, AGOSTO)
    assert s == {"rama": "ordenanza", "anios": 4, "jerarquia": None,
                 "titulo": "", "caja": False, "tramo_roe": None}


# ----------------------------------------------- regla dura: nada se suma
PROHIBIDAS = ("total", "suma", "neto", "bruto", "veredicto")


def _claves(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _claves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _claves(v)


def _importes(obj):
    if isinstance(obj, dict):
        if "importe" in obj:
            yield obj["importe"]
        for v in obj.values():
            yield from _importes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _importes(v)


def _numeros(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _numeros(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numeros(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield obj


def _sin_etiqueta(obj):
    if isinstance(obj, dict):
        if "importe" in obj and obj.get("etiqueta") not in (ce.PUBLICADO, ce.REFERENCIA):
            yield obj
        for v in obj.values():
            yield from _sin_etiqueta(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _sin_etiqueta(v)


def _respuestas():
    g2 = _escalada(AGOSTO, 1.019, "2026-09", "Septiembre 2026")
    grillas = {"2026-08": AGOSTO, "2026-09": g2}
    sels = [SEL, {**SEL, "caja": True, "tramo_roe": 2},
            {"rama": "ordenanza", "jerarquia": "Mayordomo Gral.", "caja": True, "titulo": "terciario"}]
    for s in sels:
        yield ce.consultar(s, grillas)
        yield ce.evolucion(s, grillas)


def test_ningun_total_ni_suma_ni_veredicto():
    for resp in _respuestas():
        for k in _claves(resp):
            assert not any(p in str(k).lower() for p in PROHIBIDAS), k
        imps = [x for x in _importes(resp)]
        # ningún número de la respuesta es la suma de dos o más importes
        sumas = set()
        for n in range(2, len(imps) + 1):
            for combo in itertools.combinations(imps, n):
                sumas.add(round(sum(combo), 2))
        for numero in _numeros(resp):
            if numero in imps:
                continue
            assert round(numero, 2) not in sumas, numero


def test_toda_cifra_tiene_etiqueta():
    for resp in _respuestas():
        assert list(_sin_etiqueta(resp)) == []
        assert any(True for _ in _importes(resp))


# ------------------------------------------------ enteros estrictos (anios, tramo_roe)
@pytest.mark.parametrize("campo,valor", [
    ("anios", 6.5), ("anios", 6.0), ("anios", True), ("anios", [6]), ("anios", {"a": 6}), ("anios", "6.5"),
    ("anios", "1_0"), ("anios", "+6"), ("anios", "-1"), ("anios", "٦"),
    ("tramo_roe", 1.5), ("tramo_roe", True), ("tramo_roe", [1]), ("tramo_roe", {"a": 1}), ("tramo_roe", "1.0"),
])
def test_anios_y_tramo_son_enteros_estrictos(campo, valor):
    with pytest.raises(ce.ConsultaInvalida):
        ce.validar_seleccion({**SEL, campo: valor}, AGOSTO)


def test_un_entero_escrito_como_texto_vale():
    s = ce.validar_seleccion({**SEL, "anios": "6", "tramo_roe": "2"}, AGOSTO)
    assert s["anios"] == 6 and s["tramo_roe"] == 2


def test_el_roe_dice_que_es_por_mes():
    r = ce.consultar({**SEL, "tramo_roe": 2}, GRILLAS)
    assert "por mes" in _por_clave(r)["roe"]["rotulo"]
    assert "por mes" in _por_clave(ce.consultar(SEL, GRILLAS))["roe"]["rotulo"]
