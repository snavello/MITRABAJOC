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


@pytest.mark.xfail(strict=True, reason="JSONB no conserva el orden de claves: el art. 10 sale Terciario, Secundario, Universitario")
def test_orden_de_los_titulos_en_el_art_10():
    a = _cliente().get(API + "/convenio/articulo/10").json()
    assert [r["rotulo"] for r in a["valores_vigentes"]["renglones"]] == ["secundario", "terciario", "universitario"]
