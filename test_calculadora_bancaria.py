"""Calculadora bancaria de /entornos → Herramientas: el recibo que corresponde
según la grilla (grilla_bancaria.calcular_recibo), la comparación con un
recibo real y los casos guardados. Solo existe donde existe la landing.

Correr con: python -m pytest test_calculadora_bancaria.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient

import auth
import db
import entorno
import grilla_bancaria as g
import main

db.crear_tablas()
API = "/api/entornos/herramientas/bancaria"


def _por_codigo(recibo):
    return {r["codigo"]: r["importe"] for r in recibo["renglones"]}


# ---------------------------------------------------------------- grillas
@pytest.mark.parametrize("periodo", sorted(g.GRILLAS))
def test_cada_grilla_es_coherente(periodo):
    """Una grilla nueva se transcribe a mano de un PDF escaneado: esto atrapa
    un dígito mal copiado (todo básico por encima del piso es coeficiente ×
    la misma unidad) y una estructura incompleta."""
    gr = g.GRILLAS[periodo]
    assert set(gr["ramas"]) == {"administrativa", "maestranza", "ordenanza"}
    for rama in gr["ramas"].values():
        cats = rama["categorias"]
        piso = min(c["basico"] for c in cats)
        unidades = sorted(c["basico"] / c["coef"] for c in cats if c["basico"] > piso + 1)
        unidad = unidades[len(unidades) // 2]
        for c in cats:
            if c["basico"] > piso + 1:
                assert abs(c["basico"] / c["coef"] - unidad) < 20, (periodo, rama["nombre"], c["nombre"])
            if c["conformado"] is not None:
                assert c["anios"] is not None and c["anios"] <= 15 and c["conformado"] > c["basico"]
    assert len(gr["roe"]["tramos"]) == 6
    assert all(len(f["anual"]) == 6 and f["anual"][0] == 0 for f in gr["roe"]["filas"])
    assert gr["roe"]["filas"][-1]["hasta"] is None


def test_las_constantes_del_lote_siguen_siendo_las_de_la_grilla():
    """cargar_bancaria y los PDF de prueba leen las constantes de la grilla
    vigente: tienen que coincidir con el archivo, no con otra copia."""
    admin = g.grilla()["ramas"]["administrativa"]["categorias"]
    assert g.ESCALA_ADMINISTRATIVA[0] == (0, 1.00, admin[0]["basico"], admin[0]["conformado"])
    assert g.JERARQUIAS["Jefe Ppal. de Dpto."] == (4.02, 5_925_749.09)


# ---------------------------------------------------------------- cálculo
def test_el_inicial_da_el_recibo_del_comunicado():
    r = g.calcular_recibo({"periodo": "2026-08", "rama": "administrativa", "categoria": 0, "tramo_roe": 1})
    c = _por_codigo(r)
    assert c["BAS"] == 1_642_764.63 and round(c["BAS"] + c["CONFOR"], 2) == 2_505_061.24
    assert c["ROE"] == 72_413.50
    assert r["totales"]["remunerativo"] == 2_577_474.74          # "Salario inicial + ROE"
    assert c["JUBILACION"] == round(2_577_474.74 * 0.11, 2)
    assert "CUOTA" not in c                                       # sin afiliado no hay cuota


def test_maestranza_y_ordenanza_tienen_su_escala_y_el_mismo_conformado():
    gr = g.grilla("2026-08")
    maes = gr["ramas"]["maestranza"]["categorias"]
    i10 = next(i for i, c in enumerate(maes) if c["nombre"] == "10 años")
    c = _por_codigo(g.calcular_recibo({"rama": "maestranza", "categoria": i10, "tramo_roe": 0}))
    assert c["BAS"] == 1_798_361.66 and round(c["BAS"] + c["CONFOR"], 2) == 2_505_061.24
    assert "ROE" not in c                                          # banco en el tramo que no paga
    orde = gr["ramas"]["ordenanza"]["categorias"]
    c = _por_codigo(g.calcular_recibo({"rama": "ordenanza", "categoria": 0, "tramo_roe": 0}))
    assert c["BAS"] == 1_642_764.49                                # el piso, tal como está impreso
    jefe = next(i for i, x in enumerate(orde) if x["nombre"] == "Mayordomo Gral.")
    assert "CONFOR" not in _por_codigo(g.calcular_recibo({"rama": "ordenanza", "categoria": jefe}))


def test_los_aportes_van_sobre_el_tope():
    admin = g.grilla("2026-08")["ramas"]["administrativa"]["categorias"]
    i = next(i for i, c in enumerate(admin) if c["nombre"] == "SubGte. Deptal de 1a.")
    r = g.calcular_recibo({"categoria": i, "tramo_roe": 5, "afiliado": True, "cuota_pct": 2})
    tope = g.tope_ss("2026-08")
    assert tope["maximo"] == 4_594_798.23
    c = _por_codigo(r)
    assert r["totales"]["remunerativo"] > tope["maximo"] and r["totales"]["base_aportes"] == tope["maximo"]
    assert c["JUBILACION"] == round(tope["maximo"] * 0.11, 2)
    # La cuota sindical no tiene tope: va sobre el remunerativo entero.
    assert c["CUOTA"] == round(r["totales"]["remunerativo"] * 0.02, 2)


def test_adicionales_no_remunerativos_y_ganancias():
    r = g.calcular_recibo({"categoria": 5, "cajero": True, "falla_me": True, "titulo": "universitario",
                           "zona": "La Pampa", "guarderia": True, "conectividad": "diario",
                           "dias_conectividad": 3, "dia_bancario": True, "ganancias": "12345,5"})
    c = _por_codigo(r)
    assert c["CAJFUN"] == 163_963.06 and c["CAJFAL"] == 287_355.05 and c["CAJFME"] == 82_261.33
    assert c["TITULO"] == 97_604.47 and c["ZONA"] == 455_489.91
    assert c["CONECT"] == 2_890 * 3 and c["GUARDE"] == 416_341.95
    assert abs(c["DIABAN"] - (1_973_675.85 + 1.17 * 259_499.59)) < 0.02
    assert c["GANANC"] == 12_345.5
    no_rem = {r_["codigo"] for r_ in r["renglones"] if r_["seccion"] == "no_remunerativos"}
    assert no_rem == {"GUARDE", "CONECT", "DIABAN"}
    # Lo no remunerativo no entra a la base de los aportes.
    assert r["totales"]["base_aportes"] == r["totales"]["remunerativo"]
    t = r["totales"]
    assert round(t["bruto"] - t["descuentos"], 2) == t["neto"]


@pytest.mark.parametrize("entrada", [
    {"rama": "inexistente"}, {"categoria": 999}, {"titulo": "doctorado"}, {"zona": "Marte"},
    {"tramo_roe": 9}, {"conectividad": "semanal"}, {"conectividad": "diario", "dias_conectividad": 9},
    {"periodo": "1999-01"}, {"ganancias": "mucho"},
])
def test_una_entrada_rara_se_rechaza_con_un_mensaje(entrada):
    with pytest.raises(ValueError):
        g.calcular_recibo(entrada)


def test_comparar_marca_lo_que_no_coincide():
    esperado = g.calcular_recibo({"categoria": 0, "tramo_roe": 1})
    comp = g.comparar(esperado, {"renglones": {"BAS": 1_642_764.63, "ROE": 70_000, "JUBILACION": ""},
                                 "totales": {"neto": esperado["totales"]["neto"] + 0.4},
                                 "extras": [{"concepto": "Bonificación especial", "seccion": "haberes",
                                             "importe": 5000}, {"concepto": "", "importe": None}]})
    por = {d["codigo"]: d for d in comp["renglones"]}
    assert por["BAS"]["coincide"] and not por["ROE"]["coincide"] and por["ROE"]["diferencia"] == -2_413.5
    assert "JUBILACION" not in por                     # lo que no se cargó no se compara
    assert comp["totales"][0]["coincide"]              # tolerancia de $ 1
    assert comp["extras"] == [{"concepto": "Bonificación especial", "seccion": "haberes", "importe": 5000.0}]
    assert comp["distintos"] == 1


# ---------------------------------------------------------------- rutas
def _con_pase():
    c = TestClient(main.app)
    assert c.post("/entornos/pin", data={"pin": "13572468"}, follow_redirects=False).status_code == 303
    return c


def _con_plataforma(usuario="snavello"):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident=usuario))
    return c


def test_sin_pase_no_se_ve():
    c = TestClient(main.app)
    assert c.get(API + "/opciones").status_code == 403
    assert c.post(API + "/calcular", json={"entrada": {}}).status_code == 403
    assert c.post(API + "/casos", json={"nota": "x"}).status_code == 403
    r = c.get("/entornos/herramientas/calculadora-bancaria", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = _con_plataforma()
    for ruta in ("/entornos/herramientas/calculadora-bancaria", API + "/opciones", API + "/casos",
                 "/entornos/herramientas/bancaria/casos.csv"):
        assert c.get(ruta).status_code == 404
    assert c.post(API + "/calcular", json={"entrada": {}}).status_code == 404


def test_la_pagina_y_el_calculo_desde_la_api():
    c = _con_plataforma()
    html = c.get("/entornos/herramientas/calculadora-bancaria").text
    assert "Calculadora bancaria" in html and "innerHTML" not in html
    op = c.get(API + "/opciones").json()
    assert op["periodo"] == g.PERIODO_VIGENTE and set(op["ramas"]) == {"administrativa", "maestranza", "ordenanza"}
    assert c.get(API + "/opciones?periodo=1999-01").status_code == 404
    d = c.post(API + "/calcular", json={"entrada": {"categoria": 0, "tramo_roe": 1},
                                        "real": {"renglones": {"BAS": 1_642_764.63}}}).json()
    assert d["esperado"]["totales"]["remunerativo"] == 2_577_474.74 and d["comparacion"]["distintos"] == 0
    assert c.post(API + "/calcular", json={"entrada": {"categoria": 999}}).status_code == 422


def test_guardar_revisar_y_bajar_casos():
    c = _con_plataforma("snavello")
    # Un caso vacío no sirve para revisar.
    assert c.post(API + "/casos", json={"entrada": {"categoria": 0}}).status_code == 422
    # El esperado lo recalcula el servidor: lo que mande el navegador no cuenta.
    r = c.post(API + "/casos", json={
        "entrada": {"categoria": 0, "tramo_roe": 1}, "banco": "Banco de prueba",
        "nota": "El banco lo llama <b>Adicional conformado</b>",
        "real": {"renglones": {"CONFOR": 862_296.61, "ROE": 70_000}}, "esperado": {"falso": True}})
    assert r.status_code == 200
    caso_id = r.json()["id"]
    lista = c.get(API + "/casos").json()["casos"]
    fila = next(x for x in lista if x["id"] == caso_id)
    assert fila["quien"] == "snavello" and fila["estado"] == "nuevo" and fila["distintos"] == 1
    det = c.get(API + f"/casos/{caso_id}").json()
    assert det["esperado"]["totales"]["remunerativo"] == 2_577_474.74 and "falso" not in det["esperado"]
    assert c.get(API + "/casos/999999").status_code == 404

    assert c.post(API + f"/casos/{caso_id}/estado", json={"estado": "inventado"}).status_code == 422
    assert c.post(API + f"/casos/{caso_id}/estado", json={"estado": "aplicado"}).json()["ok"]
    det = c.get(API + f"/casos/{caso_id}").json()
    assert det["estado"] == "aplicado" and det["estado_quien"] == "snavello" and det["estado_cambiado"]

    csv = c.get("/entornos/herramientas/bancaria/casos.csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    texto = csv.content.decode("utf-8-sig")
    assert "Adicional conformado" in texto and "ROE" in texto and "Banco de prueba" in texto


def test_con_el_pin_queda_como_pase():
    c = _con_pase()
    r = c.post(API + "/casos", json={"entrada": {"categoria": 1}, "nota": "solo nota"})
    if r.status_code == 403:
        pytest.skip("El PIN de la transición está apagado en este entorno de tests.")
    caso_id = r.json()["id"]
    assert c.get(API + f"/casos/{caso_id}").json()["quien"] == "pase"
