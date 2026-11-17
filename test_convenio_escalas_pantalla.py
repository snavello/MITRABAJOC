"""Convenio y escalas, pantallas (PLAN_CONVENIO_ESCALAS.md, bloques 3 y 4): la
página de /entornos → Herramientas pintada como la app del afiliado y la API
que la alimenta. Es una consulta, no un control: ni totales ni sumas.

Correr con: python -m pytest test_convenio_escalas_pantalla.py -q
"""
import json
import os
import re

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient

import auth
import db
import entorno
import main
from db import Sindicato, select

db.crear_tablas()
db.sembrar_grillas()
PAGINA = "/entornos/herramientas/convenio-escalas"
API = "/api/entornos/herramientas/escalas"
SEL = {"rama": "administrativa", "anios": 6, "titulo": "universitario", "caja": False}


def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


@pytest.fixture(scope="module")
def bancaria():
    with db.get_session() as s:
        if not s.exec(select(Sindicato).where(Sindicato.nombre == "La Bancaria")).first():
            s.add(Sindicato(nombre="La Bancaria", slug="la-bancaria", cuit="30-52573385-4",
                            color_base="#132a4a", color_primario="#1d4e89",
                            color_acento="#e8b84b", color_secundario="#2f8f83",
                            modulos_habilitados=["recibos"]))
            s.commit()


# ---------------------------------------------------------------- puertas
def test_sin_pase_no_entra():
    c = TestClient(main.app)
    r = c.get(PAGINA, headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")
    assert c.get(API + "/opciones").status_code == 403
    assert c.post(API + "/consulta", json={"seleccion": SEL}).status_code == 403
    assert c.get(API + "/convenio").status_code == 403
    assert c.get(API + "/convenio/articulo/10").status_code == 403


def test_con_el_pin_entra():
    c = TestClient(main.app)
    assert c.post("/entornos/pin", data={"pin": "13572468"}, follow_redirects=False).status_code == 303
    assert c.get(PAGINA).status_code == 200


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = _con_plataforma()
    for ruta in (PAGINA, API + "/opciones", API + "/convenio", API + "/convenio/articulo/10"):
        assert c.get(ruta).status_code == 404
    assert c.post(API + "/consulta", json={"seleccion": SEL}).status_code == 404


# ---------------------------------------------------------------- las cuatro combinaciones
@pytest.mark.parametrize("tema", ["laguna", "noticiero"])
@pytest.mark.parametrize("paleta", ["colm3na", "sindicato"])
def test_cada_modelo_y_paleta_carga_su_hoja(bancaria, tema, paleta):
    html = _con_plataforma().get(f"{PAGINA}?tema={tema}&paleta={paleta}").text
    assert f'data-tema="{tema}"' in html and f'data-paleta="{paleta}"' in html
    assert re.search(rf'href="/static/temas/{tema}-escalas\.css\?v=[\w-]+"', html)
    otro = "noticiero" if tema == "laguna" else "laguna"
    assert f"temas/{otro}-escalas.css" not in html
    assert 'class="marca-barra"' in html                       # el encabezado común
    assert "Solo para validar" in html


def test_un_valor_desconocido_cae_al_por_defecto(bancaria):
    html = _con_plataforma().get(f"{PAGINA}?tema=zzz&paleta=zzz").text
    assert 'data-tema="laguna"' in html and 'data-paleta="colm3na"' in html


def test_sin_la_bancaria_cae_a_colm3na(monkeypatch):
    monkeypatch.setattr(main, "_escalas_sindicato_id", lambda: None)
    html = _con_plataforma().get(f"{PAGINA}?paleta=sindicato").text
    assert 'data-paleta="colm3na"' in html and "La Bancaria</a>" not in html


def test_las_hojas_de_los_dos_modelos_existen_y_cubren_lo_mismo():
    css = {}
    for m in ("laguna", "noticiero"):
        with open(f"static/temas/{m}-escalas.css", encoding="utf-8") as f:
            css[m] = f.read()
        assert f'html[data-tema="{m}"][data-paleta="sindicato"]' in css[m]
    clases = set(re.findall(r"\.(es-[\w-]+)", css["laguna"])) ^ set(re.findall(r"\.(es-[\w-]+)", css["noticiero"]))
    assert not clases, f"clases con estilo en un solo modelo: {sorted(clases)}"


# ---------------------------------------------------------------- consulta
def test_los_valores_de_agosto_al_centavo():
    c = _con_plataforma()
    r = c.post(API + "/consulta", json={"seleccion": SEL, "periodo": "2026-08"})
    assert r.status_code == 200
    d = r.json()
    with open("data/grillas_bancarias/2026-08.json", encoding="utf-8") as f:
        g = json.load(f)
    cat = next(x for x in g["ramas"]["administrativa"]["categorias"] if x["anios"] == 6)
    por = {x["clave"]: x for x in d["conceptos"]}
    assert por["basico"]["importe"] == cat["basico"] == 1768880.32
    assert por["conformado"]["importe"] == cat["conformado"] == 2511567.97
    assert por["titulo"]["importe"] == g["adicionales"]["titulos"]["universitario"]
    assert por["roe"]["etiqueta"] == "referencia" and por["basico"]["etiqueta"] == "publicado"
    assert d["alcance"].startswith("Son valores sueltos de la grilla, no se suman")
    assert d["evolucion"]["meses"][0]["periodo"] == "2026-08"
    assert d["actualizacion_pendiente"] is None and d["hoy"]


def _recorrer(x, ruta=""):
    if isinstance(x, dict):
        yield ruta, x
        for k, v in x.items():
            yield from _recorrer(v, f"{ruta}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _recorrer(v, f"{ruta}[{i}]")


PALABRAS_DE_SUMA = ("total", "suma", "subtotal", "neto", "veredicto", "semaforo", "diferencia", "corresponde")


def test_ni_totales_ni_sumas_y_toda_cifra_con_etiqueta():
    c = _con_plataforma()
    respuestas = [c.post(API + "/consulta", json={"seleccion": SEL}).json(),
                  c.post(API + "/consulta", json={"seleccion": {**SEL, "caja": True, "tramo_roe": 2}}).json(),
                  c.get(API + "/convenio").json(), c.get(API + "/opciones").json()]
    for resp in respuestas:
        for ruta, nodo in _recorrer(resp):
            for clave in nodo:
                assert not any(p in clave.lower() for p in PALABRAS_DE_SUMA), (ruta, clave)
            if "importe" in nodo:
                assert nodo.get("etiqueta") in ("publicado", "referencia"), (ruta, nodo)
    conceptos = respuestas[1]["conceptos"]
    assert {x["clave"] for x in conceptos} >= {"funcion_cajero", "falla_caja", "roe"}


def test_entradas_invalidas_dan_400():
    c = _con_plataforma()
    malos = [{}, {"seleccion": "x"}, {"seleccion": {}},
             {"seleccion": {**SEL, "rama": "inventada"}}, {"seleccion": {**SEL, "anios": -1}},
             {"seleccion": {**SEL, "anios": "abc"}}, {"seleccion": {**SEL, "titulo": "doctor"}},
             {"seleccion": {**SEL, "jerarquia": "Jefe", "anios": 3}}, {"seleccion": {**SEL, "tramo_roe": 99}},
             {"seleccion": {**SEL, "caja": "si"}}, {"seleccion": SEL, "periodo": "1999-01"},
             {"seleccion": SEL, "periodo": ["x"]}, []]
    for cuerpo in malos:
        r = c.post(API + "/consulta", json=cuerpo)
        assert r.status_code == 400 and r.json()["detail"], cuerpo
    r = c.post(API + "/consulta", content=b"no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_el_cargo_jerarquico_muestra_el_basico():
    c = _con_plataforma()
    op = c.get(API + "/opciones").json()
    jer = next(r for r in op["ramas"] if r["clave"] == "administrativa")["jerarquias"][0]
    d = c.post(API + "/consulta", json={"seleccion": {"rama": "administrativa", "jerarquia": jer}}).json()
    claves = [x["clave"] for x in d["conceptos"]]
    assert claves[0] == "basico" and "conformado" not in claves
    assert d["categoria"] == jer


# ---------------------------------------------------------------- convenio
def test_la_ficha_del_articulo_10_trae_el_importe_de_titulos():
    c = _con_plataforma()
    f = c.get(API + "/convenio/articulo/10").json()
    reng = {r["rotulo"]: r["importe"] for r in f["valores_vigentes"]["renglones"]}
    assert reng["universitario"] == 97604.47 and set(reng) == {"secundario", "terciario", "universitario"}
    assert f["valores_vigentes"]["etiqueta"] == "publicado"
    assert f["resumen_estado"] == "sin_revisar" and f["agregable"] == "titulo"
    assert f["titulo_del_convenio"] is False
    assert c.get(API + "/convenio/articulo/9999").status_code == 404


def test_el_convenio_trae_indice_situaciones_y_transitorias():
    d = _con_plataforma().get(API + "/convenio").json()
    assert d["cantidad_articulos"] == 62 and len(d["articulos"]) == 70
    assert len(d["situaciones"]) == 6 and d["grupos"]
    zona = next(s for s in d["situaciones"] if s["id"] == "zona")
    assert zona["articulos"] == [25, "VIII"]
    assert d["convenio"]["fuente"].startswith("https://")
    a25 = next(a for a in d["articulos"] if a["numero"] == 25)
    assert a25["importe_titulo"] and a25["importe_nota"]
    assert next(a for a in d["articulos"] if a["numero"] == 1)["titulo_del_convenio"] is True


# ---------------------------------------------------------------- la página en sí
def test_la_pagina_no_arma_totales_ni_usa_innerhtml():
    html = _con_plataforma().get(PAGINA).text
    with open("static/convenio_escalas.js", encoding="utf-8") as f:
        js = f.read()
    assert "innerHTML" not in html and "innerHTML" not in js and "insertAdjacentHTML" not in js
    for texto in (html, js):
        assert not re.search(r"\b(reduce|total|subtotal)\b", texto, flags=re.I), "la pantalla no suma ni totaliza"
    # los textos fijos del plan
    assert "Recordar mi selección" in html and "Solo para validar" in html
    assert "Si conocés el ROE de tu banco, cargalo acá" in js
    assert "controlar lo que te pagaron" not in html + js and "Ir a Tu recibo" not in html + js   # D25
    assert "Hay una actualización publicada el" in js and "La estamos cargando." in js
    # la vista Convenio, segunda versión (D36): consulta con IA, frecuentes, texto plegado
    for frase in ("Preguntale al convenio", "Preguntas frecuentes", "Texto del convenio", "Responde solo con el convenio"):
        assert frase in html, frase
    for frase in ("Respuesta generada por IA sobre el texto del convenio", "Enviar mi consulta", "Consulta enviada",
                  "Según la ley", "Qué dice el convenio", "En tu banco",
                      "Depende de cada banco: confirmalo con tu delegado", "sin revisar", "Artículos que lo sostienen"):
        assert frase in js, frase
    # lo viejo se sacó: buscador de artículos y tarjetas por situación
    assert 'id="buscar"' not in html and 'id="sits"' not in html and "conv-situaciones" not in html
    assert "no regula este punto" not in js   # SDN 2026-11-17: no se dice lo que el convenio no trata
    assert "elegirSituacion" not in js and "Agregarlo a mi selección" not in js


def test_todo_lo_de_static_va_con_sello():
    html = _con_plataforma().get(PAGINA).text
    refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert refs
    for ref in (r for r in refs if "logo_mitrabajo" not in r):   # placeholder del parcial común, sin base de marca
        assert re.search(r"\?v=[\w-]+$", ref), ref
    with open("static/convenio_escalas.js", encoding="utf-8") as f:
        js = f.read()
    assert "/static/" not in js                   # el JS no pide nada de /static/ por su cuenta


def test_las_vistas_llevan_la_marca_de_movimiento_y_el_script_de_modales():
    html = _con_plataforma().get(PAGINA).text
    for vista in ("seleccion", "escala", "convenio"):
        assert re.search(rf'id="vista-{vista}"[^>]*data-mov-vista', html)
    assert "movimiento.css?v=" in html and "modales.js?v=" in html


def test_la_tarjeta_esta_en_herramientas():
    with open("templates/entornos.html", encoding="utf-8") as f:
        t = f.read()
    assert "/entornos/herramientas/convenio-escalas" in t and "Convenio y escalas" in t


def test_la_vista_convenio_habla_con_las_rutas_de_la_segunda_version():
    with open("static/convenio_escalas.js", encoding="utf-8") as f:
        js = f.read()
    for ruta in ("/preguntar", "/frecuentes", "/consultas/", "/enviar", "/convenio/articulo/"):
        assert ruta in js, ruta
    assert "maxlength=\"300\"" in _con_plataforma().get(PAGINA).text
    # lo que viene del modelo o de los datos nunca se arma como HTML
    assert "innerHTML" not in js and "outerHTML" not in js and "document.write" not in js


def test_la_vista_de_estado_tiene_las_preguntas_al_convenio():
    html = _con_plataforma().get(PAGINA + "/estado").text
    assert 'id="t-consultas"' in html and 'id="consultas-lista"' in html and "Preguntas al convenio" in html
    with open("static/escalas_estado.js", encoding="utf-8") as f:
        js = f.read()
    assert "/consultas" in js and "pintarConsultas" in js
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js


def test_la_api_de_la_consulta_sigue_respondiendo_a_la_pantalla():
    c = _con_plataforma()
    f = c.get(API + "/frecuentes").json()
    assert f["temas"] and all("preguntas" in t for t in f["temas"])
    r = c.post(API + "/preguntar", json={"pregunta": "¿Cuántos días de licencia tengo por casamiento?"}).json()
    assert set(r) >= {"responde", "respuesta", "articulos", "frecuentes", "consulta_id", "puede_enviar"}
    assert c.get(API + "/consultas").json()["conteos"]["total"] >= 1


def test_el_cuerpo_de_la_pregunta_abre_con_la_respuesta_directa():
    with open("static/convenio_escalas.js", encoding="utf-8") as f:
        js = f.read()
    cuerpo = js[js.index("function cuerpoPregunta"):js.index("function cerrarPregunta")]
    assert cuerpo.index("en_corto") < cuerpo.index("Qué dice el convenio") < cuerpo.index("Según la ley") < cuerpo.index("En tu banco")
    assert "El convenio no lo trata" not in js and "innerHTML" not in cuerpo
    assert "q.en_corto" in js[js.index("_n: norm("):js.index("_n: norm(") + 80]     # el filtro también busca ahí
    for css in ("static/temas/laguna-escalas.css", "static/temas/noticiero-escalas.css"):
        with open(css, encoding="utf-8") as f:
            hoja = f.read()
        assert ".es-encorto" in hoja and ".es-banco" in hoja, css
