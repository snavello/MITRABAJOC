"""Pase a la app del afiliado (PLAN_CONVENIO_ESCALAS.md, D42 a D47): la API
`/api/app/grilla/*`, el módulo `grilla_convenio`, el convenio asignado al
sindicato y la ficha de plataforma que lo elige.

Correr con: python -m pytest test_grilla_app.py -q
"""
import hashlib
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"
os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import pytest
from fastapi.testclient import TestClient

import auth
import convenio_fichas
import db
import main
import modulos
from db import CuentaTrabajador, Sindicato, Trabajador

db.crear_tablas()
db.sembrar_grillas()

API = "/api/app/grilla"
API_HERRAMIENTA = "/api/entornos/herramientas/escalas"
SEL = {"rama": "administrativa", "anios": 6, "titulo": "universitario", "caja": False}
SHA_PDF = "973ee4d0d61d6974c9a3cc38a07e2fcfee060d2f5bcf3bda73f18a91677606b0"
CONV = "cct-18-75"

CUILES = {"todo": "20111111112", "sin_convenio": "20111111120", "sin_modulo": "20222222223"}


def _sindicato(nombre, mods, convenio):
    with db.get_session() as s:
        sind = Sindicato(nombre=nombre, slug=nombre.lower().replace(" ", "-"), color_base="#0f2240",
                         modulos_habilitados=mods, convenio_grilla=convenio)
        s.add(sind); s.commit(); s.refresh(sind)
        return sind.id


SID = {
    "todo": _sindicato("Grilla App Todo", ["recibos", "grilla_convenio"], CONV),
    "sin_convenio": _sindicato("Grilla App Sin Convenio", ["recibos", "grilla_convenio"], ""),
    "sin_modulo": _sindicato("Grilla App Sin Modulo", ["recibos"], CONV),
}
with db.get_session() as _s:
    for _k, _cuil in CUILES.items():
        _s.add(CuentaTrabajador(cuil=_cuil, nombre="Afiliada " + _k, clave_hash=auth.hashear_clave("x"),
                                provincia="Córdoba", localidad="Río Cuarto"))
        _s.add(Trabajador(sindicato_id=SID[_k], cuil=_cuil, registrado=True))
    _s.commit()


def _afiliado(clave):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=CUILES[clave]))
    return c


def _plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


# ------------------------------------------------------------ puertas
def test_el_modulo_es_opt_in():
    assert modulos.MODULOS["grilla_convenio"] == "Grilla salarial y convenio"
    assert "grilla_convenio" not in modulos.MODULOS_INICIALES


def _rutas():
    return [("get", API + "/opciones", None), ("post", API + "/consulta", {"seleccion": SEL}),
            ("get", API + "/convenio", None), ("get", API + "/convenio.pdf", None)]


def _pedir(c, metodo, ruta, cuerpo):
    return c.get(ruta) if metodo == "get" else c.post(ruta, json=cuerpo)


@pytest.mark.parametrize("metodo,ruta,cuerpo", _rutas())
def test_sin_sesion(metodo, ruta, cuerpo):
    assert _pedir(TestClient(main.app), metodo, ruta, cuerpo).status_code == 401


@pytest.mark.parametrize("metodo,ruta,cuerpo", _rutas())
def test_sin_modulo_da_403(metodo, ruta, cuerpo):
    assert _pedir(_afiliado("sin_modulo"), metodo, ruta, cuerpo).status_code == 403


@pytest.mark.parametrize("metodo,ruta,cuerpo", _rutas())
def test_sin_convenio_da_404(metodo, ruta, cuerpo):
    assert _pedir(_afiliado("sin_convenio"), metodo, ruta, cuerpo).status_code == 404


def test_un_convenio_asignado_que_no_existe_da_404():
    with db.get_session() as s:
        s.get(Sindicato, SID["sin_convenio"]).convenio_grilla = "../etc/passwd"
        s.commit()
    try:
        assert _afiliado("sin_convenio").get(API + "/convenio.pdf").status_code == 404
        assert _afiliado("sin_convenio").get(API + "/convenio").status_code == 404
    finally:
        with db.get_session() as s:
            s.get(Sindicato, SID["sin_convenio"]).convenio_grilla = ""
            s.commit()


# ------------------------------------------------------------ con todo
def test_opciones_y_consulta_dan_lo_mismo_que_la_herramienta():
    c = _afiliado("todo")
    ro = c.get(API + "/opciones")
    assert ro.status_code == 200
    h = _plataforma()
    assert ro.json() == h.get(API_HERRAMIENTA + "/opciones").json()
    rc = c.post(API + "/consulta", json={"seleccion": SEL})
    assert rc.status_code == 200
    assert rc.json() == h.post(API_HERRAMIENTA + "/consulta", json={"seleccion": SEL}).json()
    assert c.post(API + "/consulta", json={"seleccion": "x"}).status_code == 400
    assert c.post(API + "/consulta", content=b"no json").status_code == 400


def test_las_rutas_de_la_herramienta_siguen_igual():
    h = _plataforma()
    assert h.get(API_HERRAMIENTA + "/opciones").json()["disponible"] is True
    conv = h.get(API_HERRAMIENTA + "/convenio").json()
    assert "situaciones" in conv and conv["articulos"] and "resumen" in conv["articulos"][0]
    assert TestClient(main.app).get(API_HERRAMIENTA + "/opciones").status_code == 403


def test_forma_exacta_del_convenio():
    r = _afiliado("todo").get(API + "/convenio")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"convenio", "secciones", "transitorias", "cierre", "pdf"}
    assert set(d["convenio"]) == {"nombre", "descripcion"}
    assert d["pdf"] == API + "/convenio.pdf"
    assert d["cierre"]
    assert d["secciones"] and d["transitorias"]
    for sec in d["secciones"]:
        assert set(sec) == {"id", "titulo", "articulos"} and sec["articulos"]
        for a in sec["articulos"]:
            assert set(a) == {"numero", "titulo", "texto"}
    for a in d["transitorias"]:
        assert set(a) == {"numero", "titulo", "texto"}
    crudo = r.text
    for prohibido in ('"resumen', '"nota"', '"situaciones"', '"fuente"', "sin_revisar", "revisado"):
        assert prohibido not in crudo


def test_todos_los_articulos_aparecen_y_en_el_orden_de_los_grupos():
    d = _afiliado("todo").get(API + "/convenio").json()
    conv = convenio_fichas.cargar(CONV)
    vistos = [str(a["numero"]) for s in d["secciones"] for a in s["articulos"]]
    assert sorted(vistos) == sorted(str(a["numero"]) for a in conv["articulos"])
    assert len(vistos) == len(set(vistos))
    assert [str(a["numero"]) for a in d["transitorias"]] == [str(a["numero"]) for a in conv["transitorias"]]
    esperados = [g["id"] for g in conv["grupos"] if any(str(n) in vistos for n in g["articulos"])]
    assert [s["id"] for s in d["secciones"] if s["id"] != "otros"] == esperados
    # el texto es el literal del convenio
    primero = d["secciones"][0]["articulos"][0]
    assert primero["texto"] == convenio_fichas.articulo(primero["numero"], CONV)["texto"]


def test_un_articulo_sin_grupo_cae_en_otros(monkeypatch):
    conv = convenio_fichas.cargar(CONV)
    sin = {**conv, "grupos": [{**g, "articulos": [n for n in g["articulos"] if str(n) != "10"]}
                              for g in conv["grupos"]]}
    monkeypatch.setattr(convenio_fichas, "cargar", lambda convenio=CONV: sin)
    d = _afiliado("todo").get(API + "/convenio").json()
    assert d["secciones"][-1]["id"] == "otros"
    assert [str(a["numero"]) for a in d["secciones"][-1]["articulos"]] == ["10"]
    assert sum(len(s["articulos"]) for s in d["secciones"]) == len(conv["articulos"])


def test_el_pdf():
    r = _afiliado("todo").get(API + "/convenio.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="convenio-cct-18-75.pdf"'
    assert hashlib.sha256(r.content).hexdigest() == SHA_PDF
    assert r.content.startswith(b"%PDF")


def test_aislamiento_entre_sindicatos():
    # el afiliado del sindicato sin módulo no ve nada, aunque el otro sí
    assert _afiliado("todo").get(API + "/convenio").status_code == 200
    assert _afiliado("sin_modulo").get(API + "/convenio").status_code == 403


# ------------------------------------------------------------ plantillas
def test_la_variable_de_plantilla(monkeypatch):
    visto = {}
    orig = main.templates.TemplateResponse

    def espiar(nombre, contexto, *a, **k):
        visto[nombre] = contexto.get("grilla_convenio_disponible")
        return orig(nombre, contexto, *a, **k)
    monkeypatch.setattr(main.templates, "TemplateResponse", espiar)
    esperado = {"todo": True, "sin_convenio": False, "sin_modulo": False}
    for clave, valor in esperado.items():
        for ruta, plantilla in (("/app", "trabajador.html"), ("/app/inicio", "portada.html")):
            visto.clear()
            assert _afiliado(clave).get(ruta).status_code == 200
            assert visto[plantilla] is valor, (clave, ruta)


# ------------------------------------------------------------ ficha de plataforma
def _datos(sid, **extra):
    d = {"id": str(sid), "nombre": "Grilla Ficha", "color_base": "#0f2240",
         "modulos_habilitados": ["recibos", "grilla_convenio"],
         "modulos_ofrecidos": list(modulos.MODULOS)}
    d.update(extra)
    return d


def _convenio_de(sid):
    with db.get_session() as s:
        return s.get(Sindicato, sid).convenio_grilla


def test_la_ficha_ofrece_los_convenios_que_existen():
    html = _plataforma().get("/plataforma").text
    assert 'name="convenio_grilla"' in html
    for cid, nombre in convenio_fichas.convenios_disponibles():
        assert f'<option value="{cid}">' in html
    assert [c for c, _ in convenio_fichas.convenios_disponibles()] == [CONV]


def test_editar_la_ficha_guarda_solo_convenios_del_catalogo():
    sid = _sindicato("Grilla Ficha", ["recibos"], "")
    c = _plataforma()
    assert c.post("/plataforma/sindicato/editar", data=_datos(sid, convenio_grilla=CONV),
                  follow_redirects=False).status_code == 303
    assert _convenio_de(sid) == CONV
    # fuera del catálogo: no se guarda, queda el anterior
    c.post("/plataforma/sindicato/editar", data=_datos(sid, convenio_grilla="inventado"), follow_redirects=False)
    assert _convenio_de(sid) == CONV
    # un formulario viejo, sin el campo, no lo toca
    c.post("/plataforma/sindicato/editar", data=_datos(sid), follow_redirects=False)
    assert _convenio_de(sid) == CONV
    # «Ninguno» lo borra
    c.post("/plataforma/sindicato/editar", data=_datos(sid, convenio_grilla=""), follow_redirects=False)
    assert _convenio_de(sid) == ""


def test_el_alta_valida_el_convenio():
    c = _plataforma()
    for nombre, valor, esperado in (("Grilla Alta Uno", CONV, CONV), ("Grilla Alta Dos", "zzz", "")):
        c.post("/plataforma/sindicato", data={"nombre": nombre, "color_base": "#0f2240",
                                              "convenio_grilla": valor}, follow_redirects=False)
        with db.get_session() as s:
            sind = s.exec(db.select(Sindicato).where(Sindicato.nombre == nombre)).first()
            assert sind is not None and sind.convenio_grilla == esperado


def test_la_ficha_no_apaga_el_modulo_si_el_formulario_no_lo_mostro():
    sid = _sindicato("Grilla Ficha Vieja", ["recibos", "grilla_convenio"], CONV)
    # pantalla abierta antes de que el módulo existiera: no lo ofrece ni lo tilda
    ofrecidos = [m for m in modulos.MODULOS if m != "grilla_convenio"]
    _plataforma().post("/plataforma/sindicato/editar",
                       data=_datos(sid, modulos_habilitados=["recibos"], modulos_ofrecidos=ofrecidos),
                       follow_redirects=False)
    assert db.modulo_habilitado(sid, "grilla_convenio")
