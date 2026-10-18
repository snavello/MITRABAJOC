"""Asistente de trámites, las rutas (PLAN_ASISTENTE_TRAMITES.md bloque 2):
la puerta de Herramientas, el catálogo, la IA con cliente simulado (nunca
gasta créditos), el motor por la API, los casos guardados y el inventario
de brechas.

Correr con: python -m pytest test_asistente_tramites_api.py -q
"""
import os
from types import SimpleNamespace

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import asistente_tramites as at
import asistente_tramites_ia as ia
import auth
import db
import entorno
import main

db.crear_tablas()
API = main.API_ASISTENTE
PAGINA = "/entornos/herramientas/asistente-tramites"


def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


@pytest.fixture(scope="module")
def sindicato():
    with Session(db.engine) as s:
        sind = db.Sindicato(nombre="Sindicato Asistente", slug="sind-asistente", color_base="#101820",
                            modulos_habilitados=["tramites", "noticias"])
        s.add(sind)
        s.commit()
        s.refresh(sind)
        central = db.Seccional(sindicato_id=sind.id, nombre="Sede Central", ve_todas=True)
        rosario = db.Seccional(sindicato_id=sind.id, nombre="Rosario")
        s.add(central)
        s.add(rosario)
        s.commit()
        s.refresh(central)
        s.add(db.Area(sindicato_id=sind.id, seccional_id=central.id, nombre="Acción Social"))
        s.commit()
        return sind.id


# ---------- Cliente falso ----------
class ClienteFalso:
    def __init__(self, *respuestas, error=None):
        self.guion = list(respuestas)
        self.error = error
        self.llamadas = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        return self.guion.pop(0)


def _respuesta(*bloques):
    return SimpleNamespace(content=list(bloques), stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=1200, output_tokens=300))


def _propuesta(entrada):
    return SimpleNamespace(type="tool_use", id="tu_1", name="proponer_tramite", input=entrada)


@pytest.fixture(autouse=True)
def _sin_cliente():
    ia.usar_cliente(None)
    yield
    ia.usar_cliente(None)


# ---------- Puerta ----------
def test_sin_pase_no_se_ve():
    c = TestClient(main.app)
    assert c.get(API + "/catalogo").status_code == 403
    assert c.post(API + "/resolver", json={"entrada": {}}).status_code == 403
    r = c.get(PAGINA, headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = _con_plataforma()
    for ruta in (PAGINA, API + "/catalogo", API + "/casos", API + "/brechas", "/entornos/herramientas/asistente/casos.csv"):
        assert c.get(ruta).status_code == 404, ruta


def test_la_pagina_abre_con_importmap_y_sin_html_como_texto():
    html = _con_plataforma().get(PAGINA).text
    assert "Asistente de trámites" in html and 'id="asistente"' in html
    assert '<script type="importmap">' in html and "asistente/app" in html
    assert html.index("movimiento.css") < html.index("asistente_tramites/asistente.css")


# ---------- Catálogo ----------
def test_el_catalogo_trae_todo_lo_que_la_pantalla_necesita(sindicato):
    cat = _con_plataforma().get(API + "/catalogo").json()
    assert [p["clave"] for p in cat["preguntas"]] == [p["clave"] for p in at.PREGUNTAS]
    assert set(cat["brechas"]) == set(at.BRECHAS) and cat["ia"] is False
    assert any(s["id"] == sindicato for s in cat["sindicatos"])
    assert cat["ejemplo"]["relato"].startswith("En La Bancaria")


# ---------- Entender (IA) ----------
def test_sin_ia_configurada_dice_que_no_esta():
    r = _con_plataforma().post(API + "/entender", json={"relato": at.EJEMPLO_RELATO})
    assert r.status_code == 200 and r.json() == {"disponible": False}


def test_relato_corto_422():
    ia.usar_cliente(ClienteFalso())
    r = _con_plataforma().post(API + "/entender", json={"relato": "kit escolar"})
    assert r.status_code == 422 and "Contá un poco más" in r.json()["detail"]


def test_la_ia_propone_y_el_motor_sanea_y_se_registra_el_uso(sindicato):
    crudo = {"nombre": "Kit escolar", "codigo": "ke27", "objetivo": "Un kit por chico.",
             "respuestas": {"quien": "afiliado", "fin": "entrega", "atiende": "marciano", "area": "Acción Social",
                            "requisitos": ["titular", "inventado"]},
             "campos": [{"etiqueta": "DNI", "tipo": "numero", "obligatorio": True, "opciones": "", "control": "unico"},
                        {"etiqueta": "Foto", "tipo": "archivo", "obligatorio": True, "opciones": "jpg", "control": ""}],
             "dudas": ["¿Hasta qué edad?"]}
    falso = ClienteFalso(_respuesta(_propuesta(crudo)))
    ia.usar_cliente(falso)
    antes = len(db.usos_ia_recientes()) if hasattr(db, "usos_ia_recientes") else None
    r = _con_plataforma().post(API + "/entender", json={"relato": at.EJEMPLO_RELATO, "sindicato_id": sindicato})
    assert r.status_code == 200
    p = r.json()["propuesta"]
    assert p["codigo"] == "KE27" and p["respuestas"]["fin"] == "entrega"
    assert p["respuestas"]["atiende"] == "seccional" and "atiende" in p["recomendadas"], "un valor inválido cae a la recomendada"
    assert p["respuestas"]["requisitos"] == ["titular"]
    assert p["campos"][1]["opciones"] == "jpg,jpeg"
    assert set(p["de_ia"]) == {"quien", "fin", "requisitos"}
    assert r.json()["uso"]["tokens_entrada"] == 1200
    # La llamada fue UNA, con la herramienta obligatoria y el relato adentro.
    assert len(falso.llamadas) == 1
    ll = falso.llamadas[0]
    assert ll["tools"][0]["name"] == "proponer_tramite" and ll["tool_choice"] == {"type": "any"}
    assert "kit escolar" in ll["messages"][0]["content"]
    assert ll["output_config"] == {"effort": "low"}
    # Quedó en Uso de IA con tipo "herramienta", a nombre del sindicato elegido.
    with Session(db.engine) as s:
        from sqlmodel import select
        fila = s.exec(select(db.UsoIA).order_by(db.UsoIA.id.desc())).first()
        assert fila.tipo == "herramienta" and fila.sindicato_id == sindicato and fila.tokens_salida == 300
    del antes


def test_si_el_modelo_no_propone_es_502_y_el_uso_igual_se_registra():
    ia.usar_cliente(ClienteFalso(_respuesta(SimpleNamespace(type="text", text="no sé"))))
    with Session(db.engine) as s:
        from sqlmodel import select
        antes = len(s.exec(select(db.UsoIA)).all())
    r = _con_plataforma().post(API + "/entender", json={"relato": at.EJEMPLO_RELATO})
    assert r.status_code == 502
    with Session(db.engine) as s:
        assert len(s.exec(select(db.UsoIA)).all()) == antes + 1, "la API contestó: ya se pagó"


def test_error_de_red_es_502_sin_registrar():
    ia.usar_cliente(ClienteFalso(error=RuntimeError("timeout")))
    with Session(db.engine) as s:
        from sqlmodel import select
        antes = len(s.exec(select(db.UsoIA)).all())
    assert _con_plataforma().post(API + "/entender", json={"relato": at.EJEMPLO_RELATO}).status_code == 502
    with Session(db.engine) as s:
        assert len(s.exec(select(db.UsoIA)).all()) == antes


def test_la_herramienta_de_la_ia_enumera_las_opciones_del_catalogo():
    esquema = ia.herramienta()["input_schema"]
    props = esquema["properties"]["respuestas"]["properties"]
    assert props["quien"]["anyOf"][0]["enum"] == ["afiliado", "empresa", "publico"]
    assert props["requisitos"]["items"]["enum"][-1] == "ninguno"
    # El calculado lo arma el constructor con una fórmula: la IA no lo propone.
    assert set(esquema["properties"]["campos"]["items"]["properties"]["tipo"]["enum"]) == set(at.TIPOS_QUE_PROPONE)
    assert set(at.TIPOS) - set(at.TIPOS_QUE_PROPONE) == {"calculado"}
    assert "unico" in esquema["properties"]["campos"]["items"]["properties"]["control"]["enum"]


# ---------- Resolver ----------
def test_resolver_devuelve_el_resultado_del_motor_con_el_sindicato(sindicato):
    r = _con_plataforma().post(API + "/resolver", json={
        "entrada": {**at.EJEMPLO_PROPUESTA, "relato": at.EJEMPLO_RELATO}, "sindicato_id": sindicato}).json()
    assert r["sindicato"]["nombre"] == "Sindicato Asistente" and r["sindicato"]["seccionales"] == ["Rosario", "Sede Central"]
    res = r["resultado"]
    assert res["codigo"] == "KE27" and res["json"]["formato"] == "colm3na.tramite"
    cfg = {x["clave"]: x for x in res["preparar"]["configurar"]}
    assert cfg["modulos"]["estado"] == "falta" and "Notificaciones" in cfg["modulos"]["detalle"]
    assert cfg["area"]["estado"] == "falta" and "Rosario" in cfg["area"]["detalle"]
    sin = _con_plataforma().post(API + "/resolver", json={"entrada": at.EJEMPLO_PROPUESTA, "sindicato_id": 999999}).json()
    assert sin["sindicato"] is None


def test_el_segundo_cuestionario_ya_no_existe():
    """SDN, 2026-10-18: se pregunta una vez. La ruta de preguntas extra se fue."""
    assert _con_plataforma().post(API + "/preguntas-extra", json={"entrada": at.EJEMPLO_PROPUESTA}).status_code == 404
    assert not hasattr(ia, "preguntas_extra")


def test_el_prompt_de_la_ia_lleva_el_catalogo_de_funciones():
    """La IA solo puede proponer fórmulas con lo que existe: el catálogo va
    en el prompt de sistema, sacado del código, y la herramienta pide por
    campo la regla, la fórmula y la función nueva."""
    assert "sistema.credencial_vigente" in ia.PROMPT_SISTEMA and "lista.fecha_nacimiento" in ia.PROMPT_SISTEMA
    assert "anios_entre" in ia.PROMPT_SISTEMA
    props = ia.herramienta()["input_schema"]["properties"]["campos"]["items"]["properties"]
    assert {"aclaracion", "regla", "formula", "funcion_nueva"} <= set(props)
    assert "segundo" in ia.herramienta()["input_schema"]["properties"]["respuestas"]["properties"], "las inferidas también las propone"


# ---------- Casos y brechas ----------
def test_guardar_listar_cambiar_estado_y_csv(sindicato):
    c = _con_plataforma()
    vacio = c.post(API + "/casos", json={"entrada": {"nombre": "", "relato": ""}})
    assert vacio.status_code == 422
    r = c.post(API + "/casos", json={"entrada": {**at.EJEMPLO_PROPUESTA, "relato": at.EJEMPLO_RELATO},
                                     "sindicato_id": sindicato, "nota": "primera vuelta"})
    assert r.status_code == 200
    caso_id = r.json()["id"]
    lista = c.get(API + "/casos").json()["casos"]
    mio = next(x for x in lista if x["id"] == caso_id)
    assert mio["nombre"] == "Kit escolar 2027" and mio["sindicato"] == "Sindicato Asistente"
    # 7 brechas distintas desde el bloque 5 de Listas y validaciones (antes 8: «requisitos» ya existe).
    assert mio["quien"] == "snavello" and mio["distintos"] == 7 and "ventana" in mio["brechas"]
    detalle = c.get(API + f"/casos/{caso_id}").json()
    assert detalle["resultado"]["json"]["formato"] == "colm3na.tramite" and detalle["entrada"]["sindicato"]["id"] == sindicato
    assert c.post(API + f"/casos/{caso_id}/estado", json={"estado": "revisado"}).status_code == 200
    assert c.post(API + f"/casos/{caso_id}/estado", json={"estado": "raro"}).status_code == 422
    assert c.get(API + "/casos/999999").status_code == 404
    csv = c.get("/entornos/herramientas/asistente/casos.csv").text
    assert "Kit escolar 2027" in csv and ";ventana;ajuste;" in csv


def test_el_inventario_de_brechas_cuenta_los_casos_no_descartados(sindicato):
    c = _con_plataforma()
    r = c.post(API + "/casos", json={"entrada": {"nombre": "Turno médico", "respuestas": {"fin": "turno"}}, "sindicato_id": sindicato})
    desc = c.post(API + "/casos", json={"entrada": {"nombre": "Descartado", "respuestas": {"fin": "turno"}}}).json()["id"]
    c.post(API + f"/casos/{desc}/estado", json={"estado": "descartado"})
    inv = c.get(API + "/brechas").json()
    turnos = next(b for b in inv["brechas"] if b["clave"] == "turnos")
    assert turnos["casos"] == 1 and turnos["sindicatos"] == ["Sindicato Asistente"] and turnos["nivel"] == "desarrollo"
    assert turnos["tramites"][0]["nombre"] == "Turno médico"
    assert {b["clave"] for b in inv["brechas"]} == set(at.BRECHAS)
    assert inv["brechas"][0]["casos"] >= inv["brechas"][-1]["casos"], "ordenado por cuántos lo piden"
    del r
