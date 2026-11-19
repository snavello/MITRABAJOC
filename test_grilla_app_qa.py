"""QA independiente del pase a la app del afiliado (PLAN_CONVENIO_ESCALAS.md D42 a D48):
puertas con roles ajenos, pluriempleo, convenio inexistente, entradas hostiles a
`/consulta`, qué HTML sale cuando la pestaña no corresponde y lo que el afiliado
nunca debe ver. Ataques y casos que hoy no cubre test_grilla_app.py.

Correr con: python -m pytest test_grilla_app_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"
os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import json
import re

import pytest
from fastapi.testclient import TestClient

import auth
import consulta_convenio_ia
import convenio_faq
import db
import main
from db import CuentaTrabajador, Sindicato, Trabajador

db.crear_tablas()
db.sembrar_grillas()

API = "/api/app/grilla"
CONV = "cct-18-75"
SEL = {"rama": "administrativa", "anios": 6, "titulo": "universitario", "caja": False}


def _sindicato(nombre, mods, convenio):
    with db.get_session() as s:
        sind = Sindicato(nombre=nombre, slug=nombre.lower().replace(" ", "-"), color_base="#0f2240",
                         modulos_habilitados=mods, convenio_grilla=convenio)
        s.add(sind); s.commit(); s.refresh(sind)
        return sind.id


SID = {
    "con": _sindicato("QA Grilla Con", ["recibos", "grilla_convenio"], CONV),
    "sin_modulo": _sindicato("QA Grilla SinMod", ["recibos"], CONV),
    "inexistente": _sindicato("QA Grilla Inexistente", ["recibos", "grilla_convenio"], "cct-99-99"),
    "sin_recibos": _sindicato("QA Grilla SinRecibos", ["grilla_convenio"], CONV),
}
CUIL = {"con": "20111111112", "sin_modulo": "20222222223", "inexistente": "20222222231",
        "sin_recibos": "20333444551", "pluri": "27222222228"}
with db.get_session() as _s:
    for _k, _c in CUIL.items():
        _s.add(CuentaTrabajador(cuil=_c, nombre="Afiliada " + _k, clave_hash=auth.hashear_clave("x"),
                                provincia="Córdoba", localidad="Río Cuarto"))
    for _k in ("con", "sin_modulo", "inexistente", "sin_recibos"):
        _s.add(Trabajador(sindicato_id=SID[_k], cuil=CUIL[_k], registrado=True))
    # pluriempleo: uno con el módulo y otro sin
    _s.add(Trabajador(sindicato_id=SID["con"], cuil=CUIL["pluri"], registrado=True))
    _s.add(Trabajador(sindicato_id=SID["sin_modulo"], cuil=CUIL["pluri"], registrado=True))
    _s.commit()


def _afiliado(clave, elegido=None):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=CUIL[clave]))
    if elegido is not None:
        c.cookies.set("sind_elegido", str(elegido))
    return c


def _rutas():
    return [("get", API + "/opciones", None), ("post", API + "/consulta", {"seleccion": SEL}),
            ("get", API + "/convenio", None), ("get", API + "/convenio.pdf", None)]


def _pedir(c, metodo, ruta, cuerpo):
    return c.get(ruta) if metodo == "get" else c.post(ruta, json=cuerpo)


# ------------------------------------------------------------ roles ajenos
@pytest.mark.parametrize("rol", ["sindicato", "empleador", "plataforma", "fiesta", "implementacion"])
@pytest.mark.parametrize("metodo,ruta,cuerpo", _rutas())
def test_una_sesion_de_otro_rol_no_entra(rol, metodo, ruta, cuerpo):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL[rol], auth.crear_sesion(rol, id_usuario=1, sindicato_id=SID["con"],
                                                                ident=CUIL["con"]))
    assert _pedir(c, metodo, ruta, cuerpo).status_code == 401


@pytest.mark.parametrize("metodo,ruta,cuerpo", _rutas())
def test_un_token_de_otro_rol_puesto_en_la_cookie_del_afiliado_no_entra(metodo, ruta, cuerpo):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("sindicato", id_usuario=1, sindicato_id=SID["con"],
                                                             ident=CUIL["con"]))
    assert _pedir(c, metodo, ruta, cuerpo).status_code == 401
    c.cookies.set(main.COOKIE_TRABAJADOR, "basura.firmada.mal")
    assert _pedir(c, metodo, ruta, cuerpo).status_code == 401


def test_la_cookie_plana_cuil_trab_no_alcanza():
    c = TestClient(main.app)
    c.cookies.set("cuil_trab", CUIL["con"])
    assert c.get(API + "/opciones").status_code == 401


def test_el_sindicato_sale_de_la_sesion_no_de_un_parametro():
    # un afiliado del sindicato sin módulo no entra por pasar el id de otro
    c = _afiliado("sin_modulo")
    for extra in ("?sindicato_id=%d" % SID["con"], "?sid=%d" % SID["con"]):
        assert c.get(API + "/convenio" + extra).status_code == 403
    r = c.post(API + "/consulta", json={"seleccion": SEL, "sindicato_id": SID["con"]})
    assert r.status_code == 403


# ------------------------------------------------------------ convenio inexistente y módulo sin recibos
@pytest.mark.parametrize("metodo,ruta,cuerpo", _rutas())
def test_convenio_asignado_que_no_existe_en_el_catalogo_da_404(metodo, ruta, cuerpo):
    assert _pedir(_afiliado("inexistente"), metodo, ruta, cuerpo).status_code == 404


def test_funciona_con_el_modulo_recibos_apagado():
    c = _afiliado("sin_recibos")
    assert c.get(API + "/opciones").json()["disponible"] is True
    assert c.get(API + "/convenio").status_code == 200
    html = c.get("/app").text
    assert 'data-tp="grilla"' in html and 'id="tp-grilla"' in html
    assert 'data-tp="recibo"' not in html


# ------------------------------------------------------------ pluriempleo
def test_pluriempleo_sin_elegir_sindicato_da_403():
    assert _afiliado("pluri").get(API + "/convenio").status_code == 403


def test_pluriempleo_con_el_sindicato_que_tiene_el_modulo_entra_y_con_el_otro_no():
    assert _afiliado("pluri", SID["con"]).get(API + "/convenio").status_code == 200
    assert _afiliado("pluri", SID["sin_modulo"]).get(API + "/convenio").status_code == 403


def test_pluriempleo_no_puede_elegir_un_sindicato_ajeno():
    # elige uno de otra persona (con módulo) sin ser suyo: no cuenta
    assert _afiliado("pluri", SID["sin_recibos"]).get(API + "/convenio").status_code == 403
    assert _afiliado("pluri", "999999").get(API + "/convenio").status_code == 403
    assert _afiliado("pluri", "x'; drop table sindicato; --").get(API + "/convenio").status_code == 403


def test_pluriempleo_la_pestana_sigue_al_sindicato_elegido():
    assert 'id="tp-grilla"' in _afiliado("pluri", SID["con"]).get("/app").text
    assert 'id="tp-grilla"' not in _afiliado("pluri", SID["sin_modulo"]).get("/app").text


# ------------------------------------------------------------ la pantalla no aparece cuando no corresponde
@pytest.mark.parametrize("clave", ["sin_modulo", "inexistente"])
def test_sin_modulo_o_con_convenio_inexistente_no_hay_pestana_ni_acceso_ni_archivos(clave):
    c = _afiliado(clave)
    app = c.get("/app").text
    for marca in ('id="tp-grilla"', 'data-tp="grilla"', "grilla_app.js", "grilla_app.css", "-grilla.css", "gr-raiz"):
        assert marca not in app, marca
    portada = c.get("/app/inicio").text
    assert "tab=grilla" not in portada and "Grilla salarial y convenio" not in portada


def test_con_todo_hay_pestana_acceso_y_archivos_con_sello():
    c = _afiliado("con")
    app = c.get("/app").text
    assert 'id="tp-grilla"' in app
    assert re.search(r'/static/grilla_app\.js\?v=\S+', app) and re.search(r'/static/grilla_app\.css\?v=\S+', app)
    assert "tab=grilla" in c.get("/app/inicio").text


def test_el_html_del_afiliado_no_dice_lo_interno():
    app = _afiliado("con").get("/app").text
    panel = app[app.index('id="tp-grilla"'): app.index('id="tp-novedades"') if 'id="tp-novedades"' in app
                else app.index('id="tp-grilla"') + 6000]
    for palabra in ("herramienta", "validaci", "entornos", "sin revisar", "consulta con ia", "preguntas frecuentes"):
        assert palabra not in panel.lower(), palabra
    assert "selector" not in panel.lower() and "paleta" not in panel.lower()
    assert "/api/entornos" not in panel
    assert "/app?tab=recibo" not in panel


# ------------------------------------------------------------ entradas hostiles a /consulta
HOSTILES = [
    {"seleccion": {}}, {"seleccion": []}, {"seleccion": None}, {"seleccion": "x"}, {"seleccion": 5},
    {"seleccion": {"rama": 5}}, {"seleccion": {"rama": ["a"]}}, {"seleccion": {"rama": {"x": 1}}},
    {"seleccion": {"rama": None, "anios": None, "titulo": None, "caja": None}},
    {"seleccion": {"rama": "administrativa", "anios": "seis"}},
    {"seleccion": {"rama": "administrativa", "anios": -1}},
    {"seleccion": {"rama": "administrativa", "anios": 10 ** 30}},
    {"seleccion": {"rama": "administrativa", "anios": 1.5}},
    {"seleccion": {"rama": "administrativa", "anios": True}},
    {"seleccion": {"rama": "administrativa", "anios": float("1e308")}},
    {"seleccion": {"rama": "administrativa", "anios": 6, "jerarquia": 7}},
    {"seleccion": {"rama": "administrativa", "anios": 6, "jerarquia": "x" * 5000}},
    {"seleccion": {"rama": "administrativa", "anios": 6, "titulo": {"a": 1}, "caja": "si"}},
    {"seleccion": {"rama": "administrativa", "anios": 6, "titulo": ["a"]}},
    {"seleccion": {"rama": "administrativa", "anios": 6, "roe": "no"}},
    {"seleccion": {"rama": "administrativa", "anios": 6, "roe": {"tramo": 99}}},
    {"seleccion": {"rama": "administrativa", "anios": 6, "roe_tramo": 10 ** 20}},
    {"seleccion": {"rama": "x" * 100000}},
    {"seleccion": SEL, "periodo": "9999-99"}, {"seleccion": SEL, "periodo": ""},
    {"seleccion": SEL, "periodo": "' OR 1=1 --"}, {"seleccion": SEL, "periodo": 202608},
    {"seleccion": SEL, "periodo": ["2026-08"]}, {"seleccion": SEL, "periodo": {"a": 1}},
    {"seleccion": SEL, "periodo": "\u0000"}, {"seleccion": SEL, "periodo": "2026-08\n"},
]


@pytest.mark.parametrize("cuerpo", HOSTILES, ids=lambda c: json.dumps(c)[:60])
def test_consulta_hostil_nunca_da_500(cuerpo):
    r = _afiliado("con").post(API + "/consulta", content=json.dumps(cuerpo), headers={"content-type": "application/json"})
    assert r.status_code in (200, 400, 422), (r.status_code, r.text[:200])
    if r.status_code == 200:
        j = r.json()
        crudo = json.dumps(j).lower()
        assert "traceback" not in crudo and "sql" not in crudo


@pytest.mark.parametrize("cuerpo", [b"", b"null", b"[]", b"[1,2]", b"123", b'"texto"', b"{", b"\xff\xfe\x00", b"{" * 10000,
                                    b"[" * 100000, b'{"seleccion":' * 5000])
def test_cuerpos_que_no_son_un_pedido_dan_400(cuerpo):
    r = _afiliado("con").post(API + "/consulta", content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code in (400, 422), (r.status_code, r.text[:200])


def test_cuerpo_enorme_no_tumba():
    grande = json.dumps({"seleccion": SEL, "relleno": "a" * (6 * 1024 * 1024)})
    r = _afiliado("con").post(API + "/consulta", content=grande, headers={"content-type": "application/json"})
    assert r.status_code < 500


def test_otro_content_type_no_da_500():
    c = _afiliado("con")
    for ct in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""):
        r = c.post(API + "/consulta", content=json.dumps({"seleccion": SEL}), headers={"content-type": ct})
        assert r.status_code < 500, ct


def test_metodos_no_previstos_no_dan_500():
    c = _afiliado("con")
    assert c.get(API + "/consulta").status_code == 405
    assert c.post(API + "/opciones").status_code == 405
    assert c.delete(API + "/convenio").status_code == 405
    assert c.get(API + "/convenio.pdf/../opciones").status_code in (200, 404)
    assert c.get(API + "/articulo/1").status_code == 404      # lo de la herramienta no existe acá


def test_un_periodo_inexistente_no_inventa_valores():
    r = _afiliado("con").post(API + "/consulta", json={"seleccion": SEL, "periodo": "1999-01"})
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert "2.511.567" not in json.dumps(r.json()) or r.json().get("periodo") != "1999-01"


# ------------------------------------------------------------ lo que el afiliado nunca ve
def test_la_consulta_no_trae_totales_ni_veredicto():
    j = _afiliado("con").post(API + "/consulta", json={"seleccion": SEL}).json()
    crudo = json.dumps(j, ensure_ascii=False).lower()
    for prohibido in ("total", "veredicto", "semaforo", "semáforo", "coincide", "diferencia", "tu_recibo", "sin_revisar"):
        assert prohibido not in crudo, prohibido


def test_el_convenio_no_trae_resumenes_ni_situaciones_ni_estados():
    crudo = _afiliado("con").get(API + "/convenio").text
    for prohibido in ('"resumen', '"situaciones"', "sin_revisar", '"revisado"', '"nota"', '"fuente"'):
        assert prohibido not in crudo


def test_no_existen_las_rutas_de_ia_ni_frecuentes_para_el_afiliado():
    c = _afiliado("con")
    for ruta in ("/frecuentes", "/preguntar", "/consulta-ia", "/situaciones", "/curado", "/estado"):
        assert c.get(API + ruta).status_code in (404, 405), ruta


def test_la_herramienta_de_entornos_sigue_cerrada_al_afiliado():
    c = _afiliado("con")
    for ruta in ("/opciones", "/convenio", "/frecuentes", "/curado"):
        assert c.get("/api/entornos/herramientas/escalas" + ruta).status_code in (401, 403, 404), ruta


def test_el_pdf_sale_como_descarga_y_sin_sniffing():
    r = _afiliado("con").get(API + "/convenio.pdf")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "private" in r.headers["cache-control"]


# ------------------------------------------------------------ Eliminar en el curado (D48), lo que pasa afuera
def _plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def _restaurar_preguntas():
    from sqlmodel import Session, delete
    with Session(db.engine) as s:
        s.exec(delete(db.PreguntaFrecuenteCambio))
        s.exec(delete(db.PreguntaFrecuente))
        s.commit()
    convenio_faq.registrar(db.CONVENIO_BANCARIO, None)
    main._FAQ_SELLO["sello"] = None


@pytest.fixture
def preguntas():
    _restaurar_preguntas()
    db.sembrar_preguntas()
    main._refrescar_preguntas(forzar=True)
    yield
    _restaurar_preguntas()


def test_una_eliminada_no_le_llega_a_la_ia_ni_a_la_siembra_tras_reiniciar(preguntas):
    c = _plataforma()
    clave = db.listar_preguntas(db.CONVENIO_BANCARIO)[0]["id"]
    assert c.post(f"/api/entornos/herramientas/escalas/curado/{clave}/eliminar", json={}).status_code == 200
    assert f"[{clave}]" not in consulta_convenio_ia.texto_frecuentes() and clave not in consulta_convenio_ia.texto_frecuentes()
    # «reinicio»: cache vacía y siembra otra vez
    convenio_faq.registrar(db.CONVENIO_BANCARIO, None)
    main._FAQ_SELLO["sello"] = None
    assert db.sembrar_preguntas() == 0
    main._refrescar_preguntas(forzar=True)
    assert clave not in {q["id"] for t in convenio_faq.publico()["temas"] for q in t["preguntas"]}
    assert clave not in consulta_convenio_ia.texto_frecuentes()
    assert db.obtener_pregunta(clave) is None


def test_eliminar_con_version_vieja_da_409_y_no_elimina(preguntas):
    c = _plataforma()
    p = db.listar_preguntas(db.CONVENIO_BANCARIO)[0]
    url = f"/api/entornos/herramientas/escalas/curado/{p['id']}/eliminar"
    assert c.post(url, json={"version": p["version"] + 3}).status_code == 409
    assert db.obtener_pregunta(p["id"]) is not None
    assert c.post(url, json={"version": p["version"]}).status_code == 200
    assert c.post(url, json={"version": p["version"]}).status_code == 404


@pytest.mark.parametrize("clave", ["../x", "a b", "x" * 400, "%00", "<script>", "'--"])
def test_eliminar_con_claves_raras_no_da_500(preguntas, clave):
    r = _plataforma().post(f"/api/entornos/herramientas/escalas/curado/{clave}/eliminar", json={})
    assert r.status_code < 500


def test_eliminar_sin_pase_no_entra(preguntas):
    assert TestClient(main.app).post("/api/entornos/herramientas/escalas/curado/vac-dias/eliminar",
                                     json={}).status_code in (401, 403, 404)
    assert _afiliado("con").post("/api/entornos/herramientas/escalas/curado/vac-dias/eliminar",
                                 json={}).status_code in (401, 403, 404)
    assert db.obtener_pregunta("vac-dias") is not None


# ------------------------------------------------------------ ficha de plataforma
def test_editar_otros_datos_de_la_ficha_no_borra_convenio_ni_modulos():
    sid = _sindicato("QA Ficha Otros", ["recibos", "grilla_convenio", "noticias"], CONV)
    import modulos
    datos = {"id": str(sid), "nombre": "QA Ficha Otros Renombrado", "color_base": "#0f2240",
             "modulos_habilitados": ["recibos", "grilla_convenio", "noticias"],
             "modulos_ofrecidos": list(modulos.MODULOS)}
    r = _plataforma().post("/plataforma/sindicato/editar", data=datos, follow_redirects=False)
    assert r.status_code == 303
    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
        assert sind.nombre == "QA Ficha Otros Renombrado"
        assert sind.convenio_grilla == CONV
        assert set(sind.modulos_habilitados) == {"recibos", "grilla_convenio", "noticias"}


def test_la_ficha_rechaza_valores_raros_de_convenio_sin_tocar_el_guardado():
    sid = _sindicato("QA Ficha Raro", ["recibos", "grilla_convenio"], CONV)
    import modulos
    for raro in ("cct-99-99", "../cct-18-75", "CCT-18-75", " cct-18-75", "cct-18-75\n", "cct-18-75-faq", "x" * 5000):
        _plataforma().post("/plataforma/sindicato/editar",
                           data={"id": str(sid), "nombre": "QA Ficha Raro", "color_base": "#0f2240",
                                 "modulos_habilitados": ["recibos", "grilla_convenio"],
                                 "modulos_ofrecidos": list(modulos.MODULOS), "convenio_grilla": raro},
                           follow_redirects=False)
        with db.get_session() as s:
            assert s.get(Sindicato, sid).convenio_grilla == CONV, repr(raro)


def test_el_catalogo_de_convenios_no_incluye_las_preguntas_frecuentes():
    import convenio_fichas
    assert [c for c, _ in convenio_fichas.convenios_disponibles()] == [CONV]
    assert not convenio_fichas.existe("cct-18-75-faq")
    assert not convenio_fichas.existe(None) and not convenio_fichas.existe(["cct-18-75"])
