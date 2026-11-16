"""Preguntas frecuentes del convenio (PLAN_CONVENIO_ESCALAS.md, D35 y el contrato
del JSON): carga y validación puras, y las rutas que las sirven.

Correr con: python -m pytest test_convenio_faq.py -q
"""
import copy
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

from fastapi.testclient import TestClient

import auth
import convenio_faq
import convenio_fichas
import db
import main

API = "/api/entornos/herramientas/escalas"

BASE = {
    "convenio": "cct-18-75", "leido": "2026-11-16",
    "temas": [{"clave": "a", "nombre": "Tema A", "orden": 2}, {"clave": "b", "nombre": "Tema B", "orden": 1},
              {"clave": "vacio", "nombre": "Sin preguntas", "orden": 3}],
    "preguntas": [
        {"id": "p1", "tema": "a", "orden": 2, "pregunta": "¿Uno?", "respuesta": "Texto.", "articulos": [48],
         "segun_ley": "", "normas": [], "estado": "sin_revisar", "nota_curador": "ojo", "inspirada_en": ["x"]},
        {"id": "p2", "tema": "a", "orden": 1, "pregunta": "¿Dos?", "respuesta": "Texto.", "articulos": [49, "50"],
         "segun_ley": "La ley dice.", "normas": [{"norma": "LCT", "articulo": "158", "url": "http://inseguro"}],
         "estado": "sin_revisar"},
        {"id": "p3", "tema": "b", "pregunta": "¿Tres?", "respuesta": "", "articulos": [],
         "segun_ley": "Solo la ley.", "normas": [{"norma": "LCT", "articulo": "1", "url": "https://x.gob.ar/y"}]},
    ],
}


def _motivos(r):
    return {d["id"]: d["motivo"] for d in r["descartadas"]}


def test_el_archivo_real_se_carga_sin_descartes():
    c = convenio_faq.cargar()
    assert c["descartadas"] == []
    assert sum(len(t["preguntas"]) for t in c["temas"]) >= 3
    for t in c["temas"]:
        for q in t["preguntas"]:
            for a in q["articulos"]:
                assert convenio_fichas.articulo(a["numero"])["titulo"] == a["titulo"]


def test_orden_y_temas_vacios():
    r = convenio_faq.validar_datos(BASE)
    assert [t["clave"] for t in r["temas"]] == ["b", "a"]            # por orden; el vacío no sale
    assert [q["id"] for q in r["temas"][1]["preguntas"]] == ["p2", "p1"]
    assert r["descartadas"] == []


def test_articulo_con_titulo_y_romano_o_cadena():
    r = convenio_faq.validar_datos(BASE)
    q = r["preguntas"]["p2"]
    assert q["articulos"] == [{"numero": 49, "titulo": convenio_fichas.articulo(49)["titulo"]},
                              {"numero": 50, "titulo": convenio_fichas.articulo(50)["titulo"]}]


def test_url_no_https_se_quita_y_https_se_conserva():
    r = convenio_faq.validar_datos(BASE)
    assert r["preguntas"]["p2"]["normas"][0]["url"] == ""
    assert r["preguntas"]["p3"]["normas"][0]["url"] == "https://x.gob.ar/y"


def test_se_descarta_y_se_reporta_lo_mal_formado():
    d = copy.deepcopy(BASE)
    d["preguntas"] += [
        {"id": "p1", "tema": "a", "pregunta": "repetida", "respuesta": "x", "articulos": [1]},
        {"id": "t", "tema": "no-existe", "pregunta": "q", "respuesta": "x", "articulos": [1]},
        {"id": "art", "tema": "a", "pregunta": "q", "respuesta": "x", "articulos": [9999]},
        {"id": "sincita", "tema": "a", "pregunta": "q", "respuesta": "x", "articulos": []},
        {"id": "vacia", "tema": "a", "pregunta": "q", "respuesta": "", "articulos": []},
        {"id": "leysola", "tema": "a", "pregunta": "q", "respuesta": "", "articulos": [],
         "segun_ley": "ley", "normas": []},
        {"id": "", "tema": "a", "pregunta": "sin id"},
        {"id": "lista", "tema": "a", "pregunta": "q", "respuesta": "x", "articulos": "48"},
        {"id": "boo", "tema": "a", "pregunta": "q", "respuesta": "x", "articulos": [True]},
        "no soy un objeto",
    ]
    r = convenio_faq.validar_datos(d)
    m = _motivos(r)
    assert m["p1"] == "id repetido"
    assert "tema inexistente" in m["t"]
    assert "no existe en el convenio" in m["art"]
    assert "ningún artículo" in m["sincita"]
    assert "ni «Según la ley»" in m["vacia"]
    assert "sin norma" in m["leysola"]
    assert "no es una lista" in m["lista"]
    assert "no existe" in m["boo"]
    assert len(r["descartadas"]) == 10
    # lo bueno sigue en pie y la repetida no pisó a la original
    assert r["preguntas"]["p1"]["pregunta"] == "¿Uno?"
    assert set(r["preguntas"]) == {"p1", "p2", "p3"}


def test_archivo_que_no_es_un_objeto():
    r = convenio_faq.validar_datos(["x"])
    assert r["temas"] == [] and r["descartadas"]


def test_convenio_inexistente_no_sale_de_la_carpeta():
    r = convenio_faq.cargar("../cct-18-75")
    assert r["temas"] == [] and r["descartadas"]


def test_publico_no_trae_notas_y_curado_si():
    pub = convenio_faq.publico()
    cur = convenio_faq.curado()
    for t in pub["temas"]:
        for q in t["preguntas"]:
            assert "nota_curador" not in q and "inspirada_en" not in q
    assert any("nota_curador" in q and "inspirada_en" in q for t in cur["temas"] for q in t["preguntas"])
    assert cur["descartadas"] == []


def test_existe_y_pregunta():
    assert convenio_faq.existe("licencia-examen")
    assert not convenio_faq.existe("nada") and not convenio_faq.existe(None) and not convenio_faq.existe(3)
    assert convenio_faq.pregunta("nada") is None


def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def test_rutas_con_su_puerta():
    anon = TestClient(main.app)
    assert anon.get(API + "/frecuentes").status_code == 403
    assert anon.get(API + "/frecuentes/curado").status_code == 403
    c = _con_plataforma()
    pub = c.get(API + "/frecuentes")
    assert pub.status_code == 200
    j = pub.json()
    assert set(j) == {"leido", "temas"}
    q = j["temas"][0]["preguntas"][0]
    assert set(q) == {"id", "pregunta", "respuesta", "articulos", "segun_ley", "normas", "estado"}
    assert set(q["articulos"][0]) == {"numero", "titulo"}
    assert "nota_curador" not in pub.text and "inspirada_en" not in pub.text
    cur = c.get(API + "/frecuentes/curado").json()
    assert "nota_curador" in cur["temas"][0]["preguntas"][0]
    assert db is not None
