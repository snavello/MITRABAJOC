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
                                 # neto real = convenio + la bonificación menos sus aportes (17%) + $ 0,40
                                 "totales": {"neto": esperado["totales"]["neto"] + 4_150 + 0.4},
                                 "extras": [{"concepto": "Bonificación especial", "seccion": "haberes",
                                             "importe": 5000}, {"concepto": "", "importe": None}]})
    por = {d["codigo"]: d for d in comp["renglones"]}
    assert por["BAS"]["coincide"] and not por["ROE"]["coincide"] and por["ROE"]["diferencia"] == -2_413.5
    assert "JUBILACION" not in por                     # lo que no se cargó no se compara
    assert comp["totales"][0]["coincide"]              # tolerancia de $ 1
    assert comp["extras"] == [{"concepto": "Bonificación especial", "seccion": "haberes", "importe": 5000.0}]
    assert comp["distintos"] == 1
    assert por["BAS"]["gravedad"] == "coincide" and por["ROE"]["gravedad"] == "grave"   # 3,3% de 72.413,50


def test_lo_que_el_recibo_trae_y_la_calculadora_no_tiene_elegido_se_muestra():
    """El recibo trae función cajero y la calculadora no tiene tildado Cajero:
    no se pierde. Sale con esperado $ 0 y qué tocar; nunca se tilda solo."""
    esperado = g.calcular_recibo({"categoria": 0, "tramo_roe": 1})
    comp = g.comparar(esperado, {"renglones": {"CAJFUN": 163_963.06, "XYZ": 5}})
    (c,) = comp["renglones"]                            # un código desconocido no se inventa
    assert c["fuera"] and c["esperado"] == 0 and c["gravedad"] == "grave" and "Cajero" in c["como"]
    assert comp["distintos"] == 1
    con_cajero = g.calcular_recibo({"categoria": 0, "tramo_roe": 1, "cajero": True})
    (c,) = g.comparar(con_cajero, {"renglones": {"CAJFUN": 163_963.06}})["renglones"]
    assert c["coincide"] and not c.get("fuera")


def test_otros_del_recibo_suman_a_la_par_sin_tocar_el_convenio():
    """Un concepto ajeno al convenio (SDN, 2026-10-13): va a "Otros", no se
    juzga, y arrastra sus aportes y su cuota; el convenio queda igual."""
    entrada = {"categoria": 7, "tramo_roe": 2, "cajero": True, "titulo": "secundario", "afiliado": True}
    esperado = g.calcular_recibo(entrada)
    conv = {r["codigo"]: r["importe"] for r in esperado["renglones"]}
    real = {"renglones": {"JUBILACION": conv["JUBILACION"] + 5_500, "CUOTA": conv["CUOTA"] + 1_000,
                          "BAS": conv["BAS"]},
            "extras": [{"concepto": "Bonificación especial", "seccion": "haberes", "importe": 50_000},
                       {"concepto": "Devolución Ganancias", "seccion": "descuentos", "importe": -12_000}],
            "totales": {"bruto": esperado["totales"]["bruto"] + 50_000,
                        "descuentos": esperado["totales"]["descuentos"] + 8_500 + 1_000 - 12_000,
                        "neto": esperado["totales"]["neto"] + 50_000 - 8_500 - 1_000 + 12_000}}
    comp = g.comparar(esperado, real)
    otros = comp["otros"]
    assert otros["renglones"] == {"JUBILACION": 5_500, "PAMI": 1_500, "OBRASOCIAL": 1_500, "CUOTA": 1_000}
    assert otros["totales"]["bruto"] == 50_000 and otros["totales"]["descuentos"] == -2_500
    assert comp["distintos"] == 0, comp                     # todo cierra con convenio + otros
    assert g.calcular_recibo(entrada) == esperado           # el convenio no se tocó
    por = {d["codigo"]: d for d in comp["renglones"]}
    assert por["JUBILACION"]["esperado"] == conv["JUBILACION"] and por["JUBILACION"]["otros"] == 5_500


def test_otros_respetan_el_tope_de_aportes():
    entrada = {"categoria": 0, "tramo_roe": 1}
    esperado = g.calcular_recibo(entrada)
    tope = esperado["tope"]["maximo"]
    otros = g.otros_del_recibo(esperado, [{"concepto": "x", "seccion": "haberes", "importe": tope * 3}])
    assert otros["renglones"]["JUBILACION"] == round(round(tope * 0.11, 2) - esperado["renglones"][[
        r["codigo"] for r in esperado["renglones"]].index("JUBILACION")]["importe"], 2)
    no_rem = g.otros_del_recibo(esperado, [{"concepto": "x", "seccion": "no_remunerativos", "importe": 9_000}])
    assert no_rem["renglones"] == {} and no_rem["totales"]["neto"] == 9_000     # sin aportes


@pytest.mark.parametrize("diferencia, esperado, gravedad", [
    (0.99, 1000, "coincide"),          # menos de $ 1
    (10, 1000, "leve"),                # justo el 1%
    (-10, 1000, "leve"),
    (10.01, 1000, "grave"),            # más del 1%
    (5, 0, "grave"),                   # se esperaba $ 0
    (-25_000, 2_505_061.24, "leve"),   # $ 25.000 sobre el conformado: 0,998%
    (-30_000, 2_505_061.24, "grave"),  # $ 30.000: 1,2%
])
def test_gravedad_de_una_diferencia(diferencia, esperado, gravedad):
    """Rojo más del 1% de lo esperado, amarillo hasta el 1% (pedido de SDN)."""
    assert g.gravedad(diferencia, esperado) == gravedad


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


# ---------------------------------------------------------------- leer con IA
RECIBO_LEIDO = {
    "periodo": "2026-08", "empleador": {"nombre": "Banco de Prueba", "cuit": "30710000011"},
    "empleado": {"cuil": "27999999994", "apellido_nombre": "PRUEBA, USUARIA"},
    "lineas": [
        {"descripcion": "Sueldo Básico", "importe": 1642764.63, "seccion": "haberes"},
        {"descripcion": "Adic. Salario Conformado", "importe": 862296.61, "seccion": "haberes"},
        {"descripcion": "Participación en las Ganancias", "importe": 72413.5, "seccion": "haberes"},
        {"descripcion": "Falla de caja M.E.", "importe": 82261.33, "seccion": "haberes"},
        {"descripcion": "Falla de caja", "importe": 287355.05, "seccion": "haberes"},
        {"descripcion": "Bonificación especial", "importe": 15000, "seccion": "haberes"},
        {"descripcion": "Jubilación", "importe": -283522.22, "seccion": "descuentos", "categoria_universal": "jubilacion"},
        {"descripcion": "Ley 19032", "importe": -77324.24, "seccion": "descuentos"},
        {"descripcion": "OSBA", "importe": -77324.24, "seccion": "descuentos", "categoria_universal": "obra_social"},
        {"descripcion": "Impuesto a las Ganancias", "importe": -50000, "seccion": "descuentos"},
        {"descripcion": "Devolución Ganancias", "importe": 12000, "seccion": "descuentos"},
        {"descripcion": "Retroactivo julio", "importe": 30000, "seccion": "haberes"},
    ],
    "totales_impresos": {"remuneraciones": 2962090.12, "descuentos": -476170.70, "neto": 2485919.42},
}


def test_lo_leido_se_ubica_en_los_renglones():
    m = g.mapear_recibo_leido(RECIBO_LEIDO)
    r = m["renglones"]
    assert r["BAS"] == 1642764.63 and r["CONFOR"] == 862296.61 and r["ROE"] == 72413.5
    assert r["CAJFME"] == 82261.33 and r["CAJFAL"] == 287355.05      # "M.E." no cae en falla común
    assert r["JUBILACION"] == 283522.22 and r["PAMI"] == 77324.24 and r["OBRASOCIAL"] == 77324.24
    assert r["GANANC"] == 50000                                       # descuento en positivo
    # Lo que no se reconoce y el reintegro van a la vista, nunca a un renglón ajeno.
    extras = {e["concepto"]: e for e in m["extras"]}
    assert extras["Bonificación especial"]["importe"] == 15000
    assert extras["Retroactivo julio"]["seccion"] == "haberes"
    assert extras["Devolución Ganancias (reintegro)"]["importe"] == -12000 and m["reintegros"] == 1
    assert m["totales"] == {"bruto": 2962090.12, "descuentos": 476170.7, "neto": 2485919.42}


def test_leer_con_ia_por_la_api(monkeypatch):
    llamadas = []

    def falso_extraer(contenido, content_type, modelo=None, **kw):
        llamadas.append(content_type)
        return RECIBO_LEIDO, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1000, "tokens_salida": 500,
                              "duracion_ms": 10}
    monkeypatch.setattr(main, "extraer", falso_extraer)
    c = _con_plataforma()
    r = c.post(API + "/leer", files={"archivo": ("recibo.pdf", b"%PDF-1.4 falso", "application/pdf")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["renglones"]["BAS"] == 1642764.63 and d["banco"] == "Banco de Prueba" and d["periodo"] == "2026-08"
    # El básico del piso lo comparten varias categorías: vuelven todas.
    assert {"rama": "administrativa", "categoria": 0, "nombre": "Inicial"} in d["categorias"]
    assert g.categorias_por_basico(2_402_729.11) == [{"rama": "administrativa", "categoria": 15, "nombre": "15 años"}]
    # Solo vuelven importes: ni el CUIL ni el nombre de la persona.
    assert "27999999994" not in r.text and "PRUEBA" not in r.text
    assert llamadas == ["application/pdf"]
    with db.get_session() as s:
        from sqlmodel import select
        assert s.exec(select(db.UsoIA).where(db.UsoIA.tipo == "herramienta")).first()
    assert c.post(API + "/leer", files={"archivo": ("vacio.pdf", b"", "application/pdf")}).status_code == 422
    # Sin pase, no se lee nada.
    assert TestClient(main.app).post(API + "/leer", files={"archivo": ("r.pdf", b"x", "application/pdf")}).status_code == 403
