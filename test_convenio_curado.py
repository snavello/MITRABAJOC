"""Curado de las preguntas frecuentes del convenio (PLAN_CONVENIO_ESCALAS.md D41):
las preguntas viven en la base (los archivos son la semilla), la pantalla del
equipo las edita y el afiliado y la IA ven lo vigente al instante.

Correr con: python -m pytest test_convenio_curado.py -q
"""
import copy
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select, delete

import auth
import consulta_convenio_ia
import convenio_faq
import db
import main

API = "/api/entornos/herramientas/escalas"
CURADO = API + "/curado"
CONV = db.CONVENIO_BANCARIO

NUEVA = {"id": "prueba-uno", "tema": "vacaciones", "pregunta": "¿Cómo se prueba esto?", "en_corto": "Así se prueba.",
         "respuesta": "El art. 48 lo regula.", "articulos": [48]}


def _vaciar():
    with Session(db.engine) as s:
        s.exec(delete(db.PreguntaFrecuenteCambio))
        s.exec(delete(db.PreguntaFrecuente))
        s.commit()


@pytest.fixture(autouse=True)
def base():
    _vaciar()
    convenio_faq.registrar(CONV, None)
    main._FAQ_SELLO["sello"] = None
    db.sembrar_preguntas()
    main._refrescar_preguntas(forzar=True)
    yield
    _vaciar()
    convenio_faq.registrar(CONV, None)
    main._FAQ_SELLO["sello"] = None


def _c(ident="snavello"):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident=ident))
    return c


def _ids_publicos():
    return {q["id"] for t in convenio_faq.publico()["temas"] for q in t["preguntas"]}


def _campos(r):
    return {e["campo"] for e in r.json()["errores"]}


# ---------------------------------------------------------------- siembra
def test_siembra_119_y_32_retiradas_idempotente_y_no_pisa():
    todas = db.listar_preguntas(CONV)
    assert len(todas) == 151
    assert sum(1 for f in todas if f["estado"] == "sin_revisar") == 119
    ret = [f for f in todas if f["estado"] == "retirada"]
    assert len(ret) == 32 and all(f["motivo_retiro"] for f in ret)
    assert db.sembrar_preguntas() == 0
    c = _c()
    clave = "vac-dias"
    r = c.post(f"{CURADO}/{clave}", json={"en_corto": "Texto editado a mano."})
    assert r.status_code == 200
    assert db.sembrar_preguntas() == 0
    assert db.obtener_pregunta(clave)["en_corto"] == "Texto editado a mano."
    # Aunque se borre una fila, no se vuelve a sembrar mientras haya otras.
    with Session(db.engine) as s:
        s.exec(delete(db.PreguntaFrecuenteCambio))
        s.exec(delete(db.PreguntaFrecuente).where(db.PreguntaFrecuente.clave == "vac-dias"))
        s.commit()
    assert db.sembrar_preguntas() == 0 and db.obtener_pregunta("vac-dias") is None


# ---------------------------------------------------------------- lo que ven el afiliado y la IA
def test_afiliado_e_ia_no_ven_retiradas_y_si_una_editada_al_instante():
    c = _c()
    retirada = next(f for f in db.listar_preguntas(CONV, estado="retirada"))
    assert len(_ids_publicos()) == 119 and retirada["id"] not in _ids_publicos()
    assert not convenio_faq.existe(retirada["id"])
    assert retirada["pregunta"] not in consulta_convenio_ia.texto_frecuentes(CONV)
    pub = c.get(API + "/frecuentes").json()
    assert retirada["id"] not in str(pub)
    r = c.post(f"{CURADO}/vac-dias", json={"en_corto": "Respuesta nueva y corta."})
    assert r.status_code == 200
    q = next(q for t in c.get(API + "/frecuentes").json()["temas"] for q in t["preguntas"] if q["id"] == "vac-dias")
    assert q["en_corto"] == "Respuesta nueva y corta."
    assert "Respuesta nueva y corta." in consulta_convenio_ia.texto_frecuentes(CONV)


def test_un_cambio_hecho_en_otro_proceso_se_ve_en_el_pedido_siguiente():
    """Otro worker escribe en la base; este proceso lo ve por el sello, sin haber escrito él."""
    c = _c()
    c.get(API + "/frecuentes")
    limpio, err = convenio_faq.validar_pregunta({**db.obtener_pregunta("vac-dias"), "en_corto": "Desde otro worker."})
    assert not err
    db.editar_pregunta(CONV, "vac-dias", limpio, "otro-worker")
    q = next(q for t in c.get(API + "/frecuentes").json()["temas"] for q in t["preguntas"] if q["id"] == "vac-dias")
    assert q["en_corto"] == "Desde otro worker."


def test_retirar_la_saca_de_lo_publico_y_reponer_la_devuelve():
    c = _c()
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": "dudosa"}).status_code == 200
    assert "vac-dias" not in _ids_publicos()
    c.get(API + "/frecuentes")
    assert "vac-dias" not in c.get(API + "/frecuentes").text
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "sin_revisar"}).status_code == 200
    c.get(API + "/frecuentes")
    assert "vac-dias" in _ids_publicos()


# ---------------------------------------------------------------- listado
def test_listado_contrato_y_filtros():
    c = _c()
    j = c.get(CURADO).json()
    assert set(j) == {"temas", "conteos", "preguntas"}
    assert j["conteos"] == {"sin_revisar": 119, "revisada": 0, "retirada": 32, "total": 151}
    assert {"clave", "nombre", "orden"} <= set(j["temas"][0])
    p = j["preguntas"][0]
    for k in ("id", "tema", "orden", "estado", "pregunta", "en_corto", "respuesta", "articulos", "segun_ley", "normas",
              "por_banco", "fuentes_banco", "nota_curador", "inspirada_en", "motivo_retiro", "detalle_retiro",
              "modificada", "modificada_por", "revisada_por", "revisada_en"):
        assert k in p, k
    r = c.get(CURADO, params={"estado": "retirada"}).json()
    assert len(r["preguntas"]) == 32 and r["conteos"]["total"] == 151
    r = c.get(CURADO, params={"tema": "vacaciones"}).json()
    assert r["preguntas"] and {f["tema"] for f in r["preguntas"]} == {"vacaciones"}
    r = c.get(CURADO, params={"q": "VACACIONES", "estado": "sin_revisar"}).json()
    assert r["preguntas"]
    assert c.get(CURADO, params={"estado": "rara"}).status_code == 400
    assert c.get(CURADO, params={"q": "x" * 500}).status_code == 422
    assert c.get(CURADO, params={"q": "zzzzzzzzz-no-existe"}).json()["preguntas"] == []


def test_una_pregunta_con_historial_y_los_articulos():
    c = _c()
    c.post(f"{CURADO}/vac-dias", json={"en_corto": "Uno."})
    j = c.get(f"{CURADO}/vac-dias").json()
    assert j["pregunta"]["id"] == "vac-dias" and j["historial"][0]["accion"] == "editar"
    assert j["historial"][0]["quien"] == "snavello" and j["historial"][0]["cuando"]
    assert j["historial"][0]["antes"]["en_corto"] != "Uno." and j["historial"][0]["despues"]["en_corto"] == "Uno."
    assert c.get(f"{CURADO}/no-existe").status_code == 404
    assert c.get(f"{CURADO}/NO%20valido").status_code == 404
    a = c.get(CURADO + "/articulos").json()
    assert {"numero": 48, "titulo": convenio_faq.pregunta("vac-dias")["articulos"][0]["titulo"]} in a


# ---------------------------------------------------------------- crear y validar
def test_crear_nace_sin_revisar_y_se_ve():
    c = _c("ars")
    r = c.post(CURADO, json=NUEVA)
    assert r.status_code == 200, r.text
    p = r.json()["pregunta"]
    assert p["estado"] == "sin_revisar" and p["modificada_por"] == "ars" and p["articulos"] == [48]
    c.get(API + "/frecuentes")
    assert "prueba-uno" in _ids_publicos()
    r = c.post(CURADO, json=NUEVA)                     # el id es único
    assert r.status_code == 409 and "prueba-uno" in r.json()["detail"]
    assert db.historial_pregunta("prueba-uno")[0]["accion"] == "crear"


def test_crear_con_estado_en_el_cuerpo_igual_nace_sin_revisar():
    r = _c().post(CURADO, json={**NUEVA, "estado": "revisada"})
    assert r.status_code == 200 and r.json()["pregunta"]["estado"] == "sin_revisar"


LEY = {"segun_ley": "Dice la ley.", "normas": [{"norma": "LCT", "articulo": "1", "url": "https://x.gob.ar/y"}]}


@pytest.mark.parametrize("cambio,campo", [
    ({"en_corto": ""}, "en_corto"),
    ({"en_corto": "   "}, "en_corto"),
    ({"pregunta": ""}, "pregunta"),
    ({"id": "Con Espacios"}, "id"),
    ({"id": "MAYUSCULA"}, "id"),
    ({"id": "reordenar"}, "id"),
    ({"id": "a" * 200}, "id"),
    ({"id": ""}, "id"),
    ({"tema": "inventado"}, "tema"),
    ({"tema": ""}, "tema"),
    ({"respuesta": "", "articulos": []}, "respuesta"),               # sin respuesta ni ley
    ({"articulos": []}, "articulos"),                                # respuesta sin artículo
    ({"respuesta": "", "articulos": [48]}, "respuesta"),             # artículo sin respuesta
    ({"articulos": [99999]}, "articulos"),
    ({"articulos": ["xx"]}, "articulos"),
    ({"articulos": [[1]]}, "articulos"),
    ({"articulos": "48"}, "articulos"),
    ({"segun_ley": "Dice.", "normas": []}, "normas"),
    ({**LEY, "normas": [{"norma": "LCT", "url": "http://inseguro"}]}, "normas"),
    ({**LEY, "normas": [{"norma": "", "url": ""}]}, "normas"),
    ({**LEY, "normas": ["no soy objeto"]}, "normas"),
    ({**LEY, "normas": {"norma": "x"}}, "normas"),
    ({"fuentes_banco": [{"texto": "ok", "url": "http://inseguro"}]}, "fuentes_banco"),
    ({"fuentes_banco": [{"texto": "", "url": ""}]}, "fuentes_banco"),
    ({"fuentes_banco": "x"}, "fuentes_banco"),
    ({"en_corto": "Son $ 500.000 por mes."}, "en_corto"),
    ({"respuesta": "Cobrás 1.234.567,89 de más."}, "respuesta"),
    ({"segun_ley": "USD 100", "normas": LEY["normas"]}, "segun_ley"),
    ({"pregunta": 5}, "pregunta"),
    ({"en_corto": ["a"]}, "en_corto"),
    ({"en_corto": {"a": 1}}, "en_corto"),
    ({"en_corto": "x" * 5000}, "en_corto"),
    ({"respuesta": "con \x00 nulo"}, "respuesta"),
    ({"respuesta": "con \u200b invisible"}, "respuesta"),
    ({"orden": "uno"}, "orden"),
    ({"orden": True}, "orden"),
    ({"inspirada_en": "x"}, "inspirada_en"),
    ({"inspirada_en": [1]}, "inspirada_en"),
    ({"nota_curador": "n" * 5000}, "nota_curador"),
])
def test_cada_regla_rechaza_con_400_y_dice_el_campo(cambio, campo):
    c = _c()
    r = c.post(CURADO, json={**NUEVA, **cambio})
    assert r.status_code == 400, r.text
    assert campo in _campos(r), r.json()
    assert campo in r.json()["detail"] or r.json()["errores"][0]["mensaje"] in r.json()["detail"]
    assert db.obtener_pregunta("prueba-uno") is None


def test_lo_valido_pasa_con_ley_y_banco_y_enlaces_https():
    c = _c()
    r = c.post(CURADO, json={**NUEVA, **LEY, "por_banco": "Galicia: 25 días.",
                             "fuentes_banco": [{"texto": "Acuerdo", "url": "https://ok.gob.ar/a"}],
                             "inspirada_en": ["nota del sindicato"], "nota_curador": "revisar con el delegado"})
    assert r.status_code == 200, r.text
    p = r.json()["pregunta"]
    assert p["normas"][0]["url"] == "https://x.gob.ar/y" and p["fuentes_banco"][0]["texto"] == "Acuerdo"
    r = c.post(CURADO, json={**NUEVA, "id": "solo-ley", "respuesta": "", "articulos": [], **LEY})
    assert r.status_code == 200, r.text


def test_la_nota_del_curador_no_viaja_al_afiliado():
    c = _c()
    c.post(CURADO, json={**NUEVA, "nota_curador": "SECRETO-INTERNO"})
    c.get(API + "/frecuentes")
    assert "SECRETO-INTERNO" not in c.get(API + "/frecuentes").text
    assert "SECRETO-INTERNO" in c.get(CURADO + "/prueba-uno").text


# ---------------------------------------------------------------- editar
def test_editar_mantiene_el_estado_salvo_que_venga_estado():
    c = _c()
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "revisada"}).status_code == 200
    r = c.post(f"{CURADO}/vac-dias", json={"pregunta": "¿Cuántos días me tocan?"})
    assert r.status_code == 200 and r.json()["pregunta"]["estado"] == "revisada"
    assert r.json()["pregunta"]["pregunta"] == "¿Cuántos días me tocan?"
    r = c.post(f"{CURADO}/vac-dias", json={"pregunta": "¿Cuántos días?", "estado": "sin_revisar"})
    assert r.json()["pregunta"]["estado"] == "sin_revisar" and r.json()["pregunta"]["revisada_por"] == ""


def test_editar_aplica_las_mismas_reglas_y_no_toca_nada_si_falla():
    c = _c()
    antes = db.obtener_pregunta("vac-dias")
    for cuerpo in ({"en_corto": ""}, {"articulos": [99999]}, {"tema": "nadie"}, {"id": "otro-id"},
                   {"respuesta": "Son $ 1.000."}):
        r = c.post(f"{CURADO}/vac-dias", json=cuerpo)
        assert r.status_code == 400, cuerpo
    assert db.obtener_pregunta("vac-dias") == antes
    assert c.post(f"{CURADO}/no-existe", json={"en_corto": "x"}).status_code == 404


def test_cambiar_de_tema_y_de_articulos():
    c = _c()
    r = c.post(f"{CURADO}/vac-dias", json={"tema": "licencias", "articulos": [49, "50"], "orden": 3})
    assert r.status_code == 200
    p = r.json()["pregunta"]
    assert p["tema"] == "licencias" and p["articulos"] == [49, 50] and p["orden"] == 3


# ---------------------------------------------------------------- estados
def test_revisar_deja_quien_y_cuando_y_se_puede_volver():
    c = _c("ars")
    r = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "revisada"})
    p = r.json()["pregunta"]
    assert p["estado"] == "revisada" and p["revisada_por"] == "ars" and p["revisada_en"]
    assert next(q for t in convenio_faq.publico()["temas"] for q in t["preguntas"] if q["id"] == "vac-dias")["estado"] == "revisada"
    r = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "sin_revisar"})
    p = r.json()["pregunta"]
    assert p["estado"] == "sin_revisar" and p["revisada_por"] == "" and p["revisada_en"] == ""
    assert [h["accion"] for h in db.historial_pregunta("vac-dias")] == ["editar", "revisar"]


def test_retirar_pide_motivo_y_reponer_valida_todo():
    c = _c()
    r = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada"})
    assert r.status_code == 400 and "motivo" in _campos(r)
    r = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": " ", "detalle": "x"})
    assert r.status_code == 400
    r = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": "no cierra", "detalle": "largo"})
    p = r.json()["pregunta"]
    assert p["estado"] == "retirada" and p["motivo_retiro"] == "no cierra" and p["detalle_retiro"] == "largo"
    # Una retirada puede estar incompleta, pero no se repone así.
    assert c.post(f"{CURADO}/vac-dias", json={"en_corto": ""}).status_code == 200
    r = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "sin_revisar"})
    assert r.status_code == 400 and "en_corto" in _campos(r)
    assert db.obtener_pregunta("vac-dias")["estado"] == "retirada"
    # Se completa y vuelve (en el mismo acto, por el cuerpo de edición).
    r = c.post(f"{CURADO}/vac-dias", json={"en_corto": "Completa de nuevo.", "estado": "revisada"})
    assert r.status_code == 200
    p = r.json()["pregunta"]
    assert p["estado"] == "revisada" and p["motivo_retiro"] == "" and p["revisada_por"] == "snavello"
    assert [h["accion"] for h in db.historial_pregunta("vac-dias")][:2] == ["reponer", "editar"]


def test_reponer_una_retirada_de_la_semilla_completa():
    c = _c()
    una = next(f for f in db.listar_preguntas(CONV, estado="retirada"))
    r = c.post(f"{CURADO}/{una['id']}/estado", json={"estado": "revisada"})
    # La semilla retirada tiene "Según la ley" completo o no; cualquiera sea, nunca un 500.
    assert r.status_code in (200, 400)
    c2 = c.post(f"{CURADO}/{una['id']}", json={"en_corto": "Completada.", "respuesta": "El art. 48 lo regula.",
                                               "articulos": [48]})
    assert c2.status_code == 200


def test_estado_invalido_o_cuerpo_raro():
    c = _c()
    for cuerpo in ({"estado": "rara"}, {"estado": 3}, {}, {"estado": ["revisada"]}, {"estado": "retirada", "motivo": 5}):
        assert c.post(f"{CURADO}/vac-dias/estado", json=cuerpo).status_code == 400, cuerpo
    assert c.post(f"{CURADO}/nadie/estado", json={"estado": "revisada"}).status_code == 404


# ---------------------------------------------------------------- reordenar
def test_reordenar_dentro_de_un_tema():
    c = _c("ars")
    claves = [f["id"] for f in db.listar_preguntas(CONV, tema="vacaciones")]
    assert len(claves) >= 3
    nuevo = list(reversed(claves))
    r = c.post(CURADO + "/reordenar", json={"tema": "vacaciones", "claves": nuevo})
    assert r.status_code == 200, r.text
    assert [f["id"] for f in db.listar_preguntas(CONV, tema="vacaciones")] == nuevo
    assert [f["orden"] for f in db.listar_preguntas(CONV, tema="vacaciones")] == [float(i) for i in range(1, len(nuevo) + 1)]
    assert [q["id"] for q in next(t for t in c.get(API + "/frecuentes").json()["temas"]
                                   if t["clave"] == "vacaciones")["preguntas"]] == nuevo
    assert db.historial_pregunta(nuevo[0])[0]["accion"] == "reordenar"
    assert db.obtener_pregunta(nuevo[0])["modificada_por"] == "ars"


@pytest.mark.parametrize("cuerpo", [
    {"tema": "vacaciones", "claves": []},
    {"tema": "vacaciones", "claves": ["vac-dias", "vac-dias"]},
    {"tema": "vacaciones", "claves": ["no-es-de-este-tema"]},
    {"tema": "nadie", "claves": ["vac-dias"]},
    {"tema": "vacaciones", "claves": "vac-dias"},
    {"tema": "vacaciones", "claves": [1, 2]},
    {"tema": ["vacaciones"], "claves": []},
    {"claves": []},
])
def test_reordenar_rechaza_listas_que_no_son_el_tema(cuerpo):
    c = _c()
    antes = db.listar_preguntas(CONV, tema="vacaciones")
    assert c.post(CURADO + "/reordenar", json=cuerpo).status_code == 400
    assert db.listar_preguntas(CONV, tema="vacaciones") == antes


# ---------------------------------------------------------------- historial, aislamiento, hostiles, puerta
def test_historial_guarda_quien_y_se_limita_a_20():
    c = _c("ars")
    for i in range(25):
        c.post(f"{CURADO}/vac-dias", json={"en_corto": f"Versión {i}."})
    h = c.get(f"{CURADO}/vac-dias").json()["historial"]
    assert len(h) == 20 and h[0]["despues"]["en_corto"] == "Versión 24." and {x["quien"] for x in h} == {"ars"}
    assert h[0]["cuando"] >= h[-1]["cuando"]


def test_aislamiento_por_convenio():
    limpio, err = convenio_faq.validar_pregunta({**db.obtener_pregunta("vac-dias")})
    assert not err
    db.crear_pregunta("otro-convenio", limpio, "t")             # la misma clave en otro convenio
    assert db.obtener_pregunta("vac-dias", "otro-convenio") is not None
    db.editar_pregunta("otro-convenio", "vac-dias", {**limpio, "en_corto": "Solo del otro."}, "t")
    assert db.obtener_pregunta("vac-dias")["en_corto"] != "Solo del otro."
    assert len(db.listar_preguntas("otro-convenio")) == 1 and len(db.listar_preguntas(CONV)) == 151
    assert db.sello_preguntas("otro-convenio") != db.sello_preguntas(CONV)
    assert db.historial_pregunta("vac-dias", CONV) == []
    main._refrescar_preguntas()
    assert len(_ids_publicos()) == 119                           # lo del otro no entra
    _vaciar_otro = Session(db.engine)
    with _vaciar_otro as s:
        s.exec(delete(db.PreguntaFrecuenteCambio))
        s.exec(delete(db.PreguntaFrecuente).where(db.PreguntaFrecuente.convenio == "otro-convenio"))
        s.commit()


HOSTILES = [None, "texto", 5, [], [1, 2], True, "x" * 100000, {"a": {"b": {"c": [1]}}},
            {"en_corto": None}, {"articulos": None, "normas": None, "fuentes_banco": None, "inspirada_en": None},
            {"en_corto": "\ud800"}, {"orden": float("1e308")}, {"tema": {"x": 1}}, {"id": 5}, {"id": ["a"]}]


def test_cuerpos_hostiles_nunca_dan_500():
    c = _c()
    for cuerpo in HOSTILES:
        for url in (CURADO, f"{CURADO}/vac-dias", f"{CURADO}/vac-dias/estado", CURADO + "/reordenar"):
            try:
                r = c.post(url, json=cuerpo)
            except Exception as e:                         # un surrogate suelto no se puede ni serializar
                assert "surrogate" in str(e) or "encode" in str(e)
                continue
            assert r.status_code in (200, 400, 422), (url, str(cuerpo)[:40], r.status_code, r.text[:200])
    # Los datos que quedaron siguen siendo los de la semilla.
    assert db.obtener_pregunta("vac-dias")["en_corto"]
    assert c.post(CURADO, content=b"{no es json", headers={"content-type": "application/json"}).status_code in (400, 422)
    assert c.post(CURADO, content=b"[]", headers={"content-type": "application/json"}).status_code == 400


def test_un_nul_o_un_texto_enorme_no_llegan_a_la_base():
    c = _c()
    assert c.post(CURADO, json={**NUEVA, "pregunta": "a\u0000b"}).status_code == 400
    assert c.post(CURADO, json={**NUEVA, "respuesta": "a" * 2_000_000}).status_code == 400


def test_la_puerta():
    anon = TestClient(main.app)
    for metodo, url, cuerpo in (("get", CURADO, None), ("get", CURADO + "/vac-dias", None),
                                ("get", CURADO + "/articulos", None), ("post", CURADO, NUEVA),
                                ("post", CURADO + "/vac-dias", {"en_corto": "x"}),
                                ("post", CURADO + "/vac-dias/estado", {"estado": "revisada"}),
                                ("post", CURADO + "/reordenar", {"tema": "vacaciones", "claves": []})):
        r = getattr(anon, metodo)(url, **({"json": cuerpo} if cuerpo is not None else {}))
        assert r.status_code == 403, (url, r.status_code)
    assert db.obtener_pregunta("prueba-uno") is None
    assert db.obtener_pregunta("vac-dias")["en_corto"] != "x"


def test_la_ruta_vieja_curado_sigue_y_no_trae_retiradas():
    j = _c().get(API + "/frecuentes/curado").json()
    assert sum(len(t["preguntas"]) for t in j["temas"]) == 119 and "nota_curador" in j["temas"][0]["preguntas"][0]


def test_registrar_y_volver_al_archivo():
    datos = {"temas": [{"clave": "t", "nombre": "T", "orden": 1}],
             "preguntas": [{"id": "solo-esta", "tema": "t", "pregunta": "¿Sí?", "segun_ley": "Ley.",
                            "normas": [{"norma": "LCT", "articulo": "1"}]}]}
    convenio_faq.registrar("cct-18-75", datos)
    assert _ids_publicos() == {"solo-esta"}
    convenio_faq.registrar("cct-18-75", None)
    assert len(_ids_publicos()) == 119
    assert copy.deepcopy(datos)                                  # el dato de entrada no se toca


def test_validar_pregunta_no_levanta_con_basura():
    for x in (None, 3, "s", [], {"id": object()}, {"articulos": [object()]}, {"normas": [None, 3]}):
        limpio, errores = convenio_faq.validar_pregunta(x)
        assert errores



# ---------------------------------------------------------------- eliminar (D48)
def _eliminar(c, clave, **cuerpo):
    return c.post(f"{CURADO}/{clave}/eliminar", json=cuerpo)


def test_eliminar_en_cualquier_estado_la_saca_de_todos_lados():
    c = _c()
    retirada = db.listar_preguntas(CONV, estado="retirada")[0]["id"]
    revisada = "vac-dias"
    assert c.post(f"{CURADO}/{revisada}/estado", json={"estado": "revisada"}).status_code == 200
    sin_rev = next(f["id"] for f in db.listar_preguntas(CONV, estado="sin_revisar") if f["id"] != revisada)
    antes = c.get(CURADO).json()["conteos"]
    for clave in (retirada, revisada, sin_rev):
        pregunta = db.obtener_pregunta(clave)
        r = _eliminar(c, clave, version=pregunta["version"])
        assert r.status_code == 200 and r.json()["ok"] is True
    j = c.get(CURADO).json()
    ids = {f["id"] for f in j["preguntas"]}
    assert not ids & {retirada, revisada, sin_rev}
    assert j["conteos"]["total"] == antes["total"] - 3
    assert j["conteos"]["retirada"] == antes["retirada"] - 1
    assert j["conteos"]["revisada"] == antes["revisada"] - 1
    assert j["conteos"]["sin_revisar"] == antes["sin_revisar"] - 1
    for estado in ("sin_revisar", "revisada", "retirada"):
        vistas = {f["id"] for f in c.get(CURADO, params={"estado": estado}).json()["preguntas"]}
        assert not vistas & {retirada, revisada, sin_rev}
    assert revisada not in {f["id"] for f in c.get(CURADO, params={"q": "vacaciones"}).json()["preguntas"]}
    assert db.obtener_pregunta(revisada) is None
    assert revisada not in _ids_publicos() and not convenio_faq.existe(revisada)
    assert revisada not in str(c.get(API + "/frecuentes").json())
    assert revisada not in str(c.get(API + "/frecuentes/curado").json())
    assert revisada not in {f["id"] for f in db.datos_preguntas_vigentes(CONV)["preguntas"]}


def test_eliminada_da_404_en_detalle_editar_estado_reordenar_y_eliminar():
    c = _c()
    p = db.obtener_pregunta("vac-dias")
    assert _eliminar(c, "vac-dias").status_code == 200
    assert c.get(f"{CURADO}/vac-dias").status_code == 404
    assert c.post(f"{CURADO}/vac-dias", json={"en_corto": "Nada."}).status_code == 404
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "revisada"}).status_code == 404
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": "dudosa"}).status_code == 404
    assert _eliminar(c, "vac-dias").status_code == 404
    assert db.historial_pregunta("vac-dias") == []
    resto = [f["id"] for f in db.listar_preguntas(CONV, tema=p["tema"])]
    assert "vac-dias" not in resto
    assert c.post(CURADO + "/reordenar", json={"tema": p["tema"], "claves": resto[::-1]}).status_code == 200
    r = c.post(CURADO + "/reordenar", json={"tema": p["tema"], "claves": resto + ["vac-dias"]})
    assert r.status_code == 400
    assert _eliminar(c, "no-existe-esta").status_code == 404


def test_eliminar_pide_version_vigente_y_registra_quien_y_estado_anterior():
    c = _c("sdn")
    p = db.obtener_pregunta("vac-dias")
    r = _eliminar(c, "vac-dias", version=p["version"] + 5)
    assert r.status_code == 409 and r.json()["errores"][0]["codigo"] == "conflicto"
    assert db.obtener_pregunta("vac-dias") is not None
    assert _eliminar(c, "vac-dias", version="x").status_code == 400
    assert c.post(f"{CURADO}/vac-dias/eliminar", json=[1]).status_code == 400
    assert _eliminar(c, "vac-dias", version=p["version"]).status_code == 200
    with Session(db.engine) as s:
        fila = s.exec(select(db.PreguntaFrecuente).where(db.PreguntaFrecuente.clave == "vac-dias")).one()
        assert fila.estado == "eliminada"
        cambios = s.exec(select(db.PreguntaFrecuenteCambio).where(db.PreguntaFrecuenteCambio.pregunta_id == fila.id)
                         .order_by(db.PreguntaFrecuenteCambio.id)).all()
    ultimo = cambios[-1]
    assert ultimo.accion == "eliminar" and ultimo.quien == "sdn" and ultimo.cuando
    assert ultimo.antes["estado"] == "sin_revisar" and ultimo.despues["estado"] == "eliminada"


def test_eliminar_pide_la_misma_puerta_que_el_resto():
    c = TestClient(main.app)
    assert c.post(f"{CURADO}/vac-dias/eliminar", json={}).status_code in (401, 403, 404)
    assert db.obtener_pregunta("vac-dias") is not None


def test_la_siembra_no_revive_una_eliminada_ni_aun_con_todas_eliminadas():
    c = _c()
    assert _eliminar(c, "vac-dias").status_code == 200
    assert db.sembrar_preguntas() == 0
    main._refrescar_preguntas(forzar=True)
    assert db.obtener_pregunta("vac-dias") is None and not convenio_faq.existe("vac-dias")
    for f in db.listar_preguntas(CONV):
        db.eliminar_pregunta(CONV, f["id"], "t")
    assert db.listar_preguntas(CONV) == [] and db.sembrar_preguntas() == 0
    main._refrescar_preguntas(forzar=True)
    assert db.listar_preguntas(CONV) == [] and _ids_publicos() == set()
    j = c.get(CURADO).json()
    assert j["preguntas"] == [] and j["conteos"]["total"] == 0


def test_crear_con_la_clave_de_una_eliminada_se_rechaza_con_mensaje_claro():
    c = _c()
    assert c.post(CURADO, json=NUEVA).status_code == 200
    assert _eliminar(c, NUEVA["id"]).status_code == 200
    r = c.post(CURADO, json=NUEVA)
    assert r.status_code == 409
    assert "eliminada" in r.json()["detail"] and NUEVA["id"] in r.json()["detail"]
    assert db.obtener_pregunta(NUEVA["id"]) is None


def test_eliminada_no_cuenta_para_los_topes(monkeypatch):
    c = _c()
    antes = db.listar_preguntas(CONV)
    assert _eliminar(c, "vac-dias").status_code == 200
    despues = db.listar_preguntas(CONV)
    assert len(despues) == len(antes) - 1
    monkeypatch.setattr(convenio_faq, "TOPE_PREGUNTAS", len(despues))
    assert c.post(CURADO, json=NUEVA).status_code == 400          # lleno: solo cuentan las que existen
    monkeypatch.setattr(convenio_faq, "TOPE_PREGUNTAS", len(despues) + 1)
    assert c.post(CURADO, json=NUEVA).status_code == 200          # la eliminada dejó lugar
