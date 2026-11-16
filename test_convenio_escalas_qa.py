"""QA independiente de Convenio y escalas (pantallas): entradas hostiles y orden
de los renglones. Correr con: python -m pytest test_convenio_escalas_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"

import pytest
from fastapi.testclient import TestClient

import auth
import db
import main

db.crear_tablas()
db.sembrar_grillas()
API = "/api/entornos/herramientas/escalas"
SEL = {"rama": "administrativa", "anios": 6, "titulo": "", "caja": False}


def _cliente():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


@pytest.mark.parametrize("cambio", [
    {"rama": None}, {"rama": 5}, {"anios": 999}, {"anios": -1}, {"anios": 6.5}, {"anios": True},
    {"anios": None, "jerarquia": "Rey"}, {"anios": None, "jerarquia": ["a"]}, {"jerarquia": "Jefe Ppal. de Dpto."},
    {"titulo": "doctor"}, {"titulo": 3}, {"caja": "si"}, {"caja": 1}, {"tramo_roe": 6}, {"tramo_roe": -1},
    {"tramo_roe": 1.5}, {"tramo_roe": True},
    {"anios": "6.5"}, {"anios": "6,5"}, {"anios": " -1"}, {"anios": "1_0"}, {"anios": "+6"}, {"anios": "seis"},
    {"anios": [6]}, {"anios": {"a": 6}}, {"anios": 6.0}, {"tramo_roe": "1.5"}, {"tramo_roe": [1]},
    {"tramo_roe": {"a": 1}}, {"tramo_roe": False}, {"tramo_roe": "uno"},
])
def test_entrada_invalida_da_400_nunca_500(cambio):
    r = _cliente().post(API + "/consulta", json={"seleccion": {**SEL, **cambio}})
    assert r.status_code == 400, r.text


@pytest.mark.parametrize("cuerpo", ["no json", "[1]", "null", '{"seleccion":{"rama":"administrativa","anios":NaN}}'])
def test_cuerpo_invalido_da_400(cuerpo):
    r = _cliente().post(API + "/consulta", content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_ninguna_respuesta_trae_total_ni_suma():
    c = _cliente()
    o = c.get(API + "/opciones").json()
    for rama in o["ramas"]:
        r = c.post(API + "/consulta", json={"seleccion": {**SEL, "rama": rama["clave"], "titulo": "universitario", "caja": True}}).json()
        claves = " ".join(str(k) for k in r) + " ".join(str(k) for k in r["conceptos"][0])
        assert "total" not in claves.lower() and "suma" not in claves.lower()
        assert all(x["etiqueta"] in ("publicado", "referencia") for x in r["conceptos"])


def test_orden_de_los_titulos_en_el_art_10():
    a = _cliente().get(API + "/convenio/articulo/10").json()
    assert [r["rotulo"] for r in a["valores_vigentes"]["renglones"]] == ["secundario", "terciario", "universitario"]


def test_enteros_escritos_como_texto_valen():
    """Un formulario manda todo como texto: "6" y "1" son enteros válidos."""
    r = _cliente().post(API + "/consulta", json={"seleccion": {**SEL, "anios": "6", "tramo_roe": "1"}})
    assert r.status_code == 200, r.text
    assert r.json()["seleccion"]["anios"] == 6 and r.json()["seleccion"]["tramo_roe"] == 1


def test_orden_de_los_importes_de_un_diccionario():
    import convenio_fichas as cf
    f = lambda **k: [{"rotulo": a, "importe": b} for a, b in k.items()]
    # títulos: por la lista explícita, aunque el monto diga otra cosa
    assert [r["rotulo"] for r in cf.ordenar_importes(f(universitario=1, secundario=9, terciario=5))] == \
        ["secundario", "terciario", "universitario"]
    # lo demás: monto creciente y, a igual monto, alfabético
    assert [r["rotulo"] for r in cf.ordenar_importes(f(b=5, a=5, c=1))] == ["c", "a", "b"]
    grilla = {"adicionales": {"titulos": {"universitario": 3.0, "terciario": 2.0, "secundario": 1.0}}}
    ficha = {"importe_grilla": "adicionales.titulos"}
    assert [r["rotulo"] for r in cf.importe_vigente(ficha, grilla)] == ["secundario", "terciario", "universitario"]


def test_las_opciones_de_titulos_y_ramas_tienen_orden_fijo():
    o = _cliente().get(API + "/opciones").json()
    assert [t["clave"] for t in o["titulos"]] == ["sin", "secundario", "terciario", "universitario"]
    assert [r["clave"] for r in o["ramas"]] == ["administrativa", "maestranza", "ordenanza"]


def test_la_grilla_trae_cuando_y_donde_se_publico():
    c = _cliente()
    g = c.get(API + "/opciones").json()["grilla"]
    assert set(("publicada_sindicato", "fuente_nota", "fuente_pdf")) <= set(g)
    r = c.post(API + "/consulta", json={"seleccion": SEL}).json()
    assert set(("publicada_sindicato", "fuente_nota", "fuente_pdf")) == set(r["publicacion"])


@pytest.mark.parametrize("url,ok", [
    ("https://labancaria.org/nota/", True), ("https://www.labancaria.org/a.pdf", True),
    ("http://labancaria.org/a", False), ("https://labancaria.org.malo.com/a", False),
    ("https://evil.com/labancaria.org", False), ("javascript:alert(1)", False), ("", False), (None, False), (5, False),
])
def test_solo_se_enlaza_a_labancaria_https(url, ok):
    assert main._escalas_url_segura(url) == (url if ok else "")


def test_publicacion_de_la_fila_publicada_y_solo_urls_seguras():
    from sqlmodel import Session, select
    with Session(db.engine) as ses:
        fila = ses.exec(select(db.GrillaSalarial).where(db.GrillaSalarial.estado == "publicada").order_by(db.GrillaSalarial.periodo.desc())).first()
        viejo = (fila.publicada_sindicato, fila.fuente_nota, fila.fuente_pdf)
        fila.publicada_sindicato, fila.fuente_nota, fila.fuente_pdf = "2026-09-11", "https://labancaria.org/nota/", "http://malo.com/a.pdf"
        ses.add(fila); ses.commit()
        try:
            r = _cliente().post(API + "/consulta", json={"seleccion": SEL}).json()["publicacion"]
            assert r == {"publicada_sindicato": "2026-09-11", "fuente_nota": "https://labancaria.org/nota/", "fuente_pdf": ""}
            g = _cliente().get(API + "/opciones").json()["grilla"]
            assert g["publicada_sindicato"] == "2026-09-11" and g["fuente_pdf"] == ""
        finally:
            fila.publicada_sindicato, fila.fuente_nota, fila.fuente_pdf = viejo
            ses.add(fila); ses.commit()


def test_la_pantalla_valida_lo_guardado_y_el_roe_se_puede_quitar():
    js = open("static/convenio_escalas.js", encoding="utf-8").read()
    for frase in ("Tu selección guardada ya no coincide con la grilla vigente: elegila de nuevo.",
                  "grilla publicada el ", "Ver el PDF", "'Quitar'", "fechaIsoValida", "urlSegura"):
        assert frase in js, frase
    assert "innerHTML" not in js


def test_no_hay_bloque_de_salida_a_tu_recibo():
    """D25: la pantalla Escala vigente cierra con la evolución, sin «Ir a Tu recibo»."""
    html = _cliente().get("/entornos/herramientas/convenio-escalas").text
    js = open("static/convenio_escalas.js", encoding="utf-8").read()
    for t in ("controlar lo que te pagaron", "Ir a Tu recibo", "es-salida"):
        assert t not in html + js, t
