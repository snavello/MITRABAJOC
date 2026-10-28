"""Asistente de trámites, segunda vuelta (PLAN_ASISTENTE_TRAMITES_V2.md):
el veredicto con los datos del sindicato, actualizar un caso y el
importador que crea los tipos de trámite como BORRADOR.

La prueba es un sindicato con la estructura de La Bancaria (V10): Sede
Central con `ve_todas`, Rosario y Córdoba; «Acción Social» en Central y en
Rosario pero no en Córdoba; el grupo familiar cargado.

Correr con: python -m pytest test_asistente_importar.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asistente_tramites as at
import auth
import db
import main

db.crear_tablas()
API = main.API_ASISTENTE


def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


@pytest.fixture(scope="module")
def bancaria():
    with Session(db.engine) as s:
        sind = db.Sindicato(nombre="La Bancaria Prueba", slug="bancaria-prueba", color_base="#101820",
                            modulos_habilitados=["tramites", "noticias", "notificaciones"])
        s.add(sind)
        s.commit()
        s.refresh(sind)
        sid = sind.id
        secs = {}
        for nombre, ve in (("Sede Central", True), ("Rosario", False), ("Córdoba", False)):
            x = db.Seccional(sindicato_id=sid, nombre=nombre, ve_todas=ve)
            s.add(x)
            s.commit()
            s.refresh(x)
            secs[nombre] = x.id
        areas = {}
        for sec in ("Sede Central", "Rosario"):
            a = db.Area(sindicato_id=sid, seccional_id=secs[sec], nombre="Acción Social")
            s.add(a)
            s.commit()
            s.refresh(a)
            areas[sec] = a.id
        # Un formulario que ya existe, para el punto 5 del veredicto.
        s.add(db.Trabajador(sindicato_id=sid, cuil="20111111112", activo=True, registrado=True, seccional_id=secs["Rosario"]))
        db.guardar_datos_personales(s, "20111111112", nombre="Pérez, Juan")
        s.add(db.UsuarioSindicato(sindicato_id=sid, usuario="20111111120", nombre="Admin",
                                  clave_hash=auth.hashear_clave("banc-demo"), debe_cambiar_clave=False, es_super_admin=True))
        s.commit()
    previo = db.crear_tipo_tramite(sid, "Declaración de grupo familiar", "DGF", [
        {"etiqueta": "DNI del familiar", "tipo_dato": "numero", "obligatorio": True, "validaciones": []}],
        area_destino_default_id=areas["Sede Central"])
    return {"id": sid, "secs": secs, "areas": areas, "previo": previo}


def _entrada(**cambios):
    e = {**at.EJEMPLO_PROPUESTA, "relato": at.EJEMPLO_RELATO}
    e["respuestas"] = {**e["respuestas"], **cambios.pop("respuestas", {})}
    e.update(cambios)
    return e


# ---------------------------------------------------------------- sindicato completo
def test_el_sindicato_trae_listas_formularios_y_ids(bancaria):
    sind = main._sindicato_para_asistente(bancaria["id"])
    assert sind["seccionales"] == ["Córdoba", "Rosario", "Sede Central"]
    assert {s["nombre"]: s["ve_todas"] for s in sind["seccionales_detalle"]}["Sede Central"] is True
    assert {(a["nombre"], a["seccional"]) for a in sind["areas"]} == {("Acción Social", "Sede Central"), ("Acción Social", "Rosario")}
    assert all(a["id"] and a["seccional_id"] for a in sind["areas"])
    assert sind["listas"] == [] and sind["formularios"][0]["titulo"] == "Declaración de grupo familiar"


# ---------------------------------------------------------------- veredicto
def test_el_veredicto_dice_que_falta_en_el_sindicato(bancaria):
    c = _con_plataforma()
    r = c.post(API + "/resolver", json={"entrada": _entrada(), "sindicato_id": bancaria["id"]}).json()["resultado"]
    v = r["veredicto"]
    puntos = {p["clave"]: p for p in v["puntos"]}
    assert v["conclusion"] == "prerrequisito" and v["complejidad"] == "alta"
    assert puntos["prerrequisito"]["si"] is True
    assert "Córdoba" in puntos["prerrequisito"]["detalle"] and "Grupo familiar" in puntos["prerrequisito"]["detalle"]
    assert puntos["importar"]["si"] is False and "borrador" in puntos["importar"]["detalle"]
    assert puntos["manual"]["si"] is True and "DNI del chico" in puntos["manual"]["detalle"]
    assert puntos["desarrollo"]["si"] is True and "complejidad alta" in puntos["desarrollo"]["detalle"]
    assert puntos["formulario_existente"]["si"] is False and puntos["formulario_nuevo"]["si"] is False
    plan = r["importacion"]
    assert plan["central"] == "Sede Central" and plan["formularios"][0]["destino"]["existe"] is True
    assert {m["seccional"]: m["existe"] for m in plan["formularios"][0]["mapa"]} == {"Córdoba": False, "Rosario": True, "Sede Central": True}
    assert plan["faltan"] == ["Área «Acción Social» en Córdoba"]


def test_el_formulario_previo_existente_o_a_construir(bancaria):
    c = _con_plataforma()
    base = {"nombre": "Ayuda escolar", "respuestas": {"previo": "si", "previo_nombre": "declaracion de grupo familiar"},
            "campos": [{"etiqueta": "Monto", "tipo": "numero"}]}
    v = c.post(API + "/resolver", json={"entrada": base, "sindicato_id": bancaria["id"]}).json()["resultado"]["veredicto"]
    p = {x["clave"]: x for x in v["puntos"]}
    assert p["formulario_existente"]["si"] is True and "DGF" in p["formulario_existente"]["detalle"]
    assert p["formulario_nuevo"]["si"] is False and v["previo"]["existe"]["codigo"] == "DGF"
    assert "previo" in [b for b in c.post(API + "/resolver", json={"entrada": base, "sindicato_id": bancaria["id"]}).json()["resultado"]["brechas"]]
    base["respuestas"]["previo_nombre"] = "Carnet de delegado"
    v = c.post(API + "/resolver", json={"entrada": base, "sindicato_id": bancaria["id"]}).json()["resultado"]["veredicto"]
    p = {x["clave"]: x for x in v["puntos"]}
    assert p["formulario_nuevo"]["si"] is True and v["conclusion"] == "formulario_nuevo"
    assert "Carnet de delegado" in v["titular"]
    # Sin sindicato, no se sabe.
    v = c.post(API + "/resolver", json={"entrada": base}).json()["resultado"]["veredicto"]
    assert v["conclusion"] == "sin_sindicato" and {x["si"] for x in v["puntos"][:3]} == {None}


def test_un_tramite_simple_se_puede_importar_ya(bancaria):
    c = _con_plataforma()
    e = {"nombre": "Cambio de domicilio", "respuestas": {"atiende": "central", "area": "Acción Social"},
         "campos": [{"etiqueta": "Domicilio nuevo", "tipo": "texto"}, {"etiqueta": "Comprobante", "tipo": "archivo"}]}
    v = c.post(API + "/resolver", json={"entrada": e, "sindicato_id": bancaria["id"]}).json()["resultado"]["veredicto"]
    assert v["conclusion"] == "importar" and v["complejidad"] == "ninguna"
    assert [x["si"] for x in v["puntos"]] == [True, False, False, False, False, False]
    assert "2 preguntas" in v["puntos"][0]["detalle"]


def test_la_complejidad_sigue_a_las_brechas():
    assert at.complejidad_de({}) == "ninguna"
    assert at.complejidad_de({"ventana": ["x"]}) == "baja"
    assert at.complejidad_de({"ventana": ["x"], "exportar": ["x"]}) == "media"
    assert at.complejidad_de({"exportar": ["x"], "turnos": ["x"]}) == "alta"
    assert "previo" in at.BRECHAS and at.BRECHAS["previo"]["nivel"] == "ajuste"


# ---------------------------------------------------------------- importar
def test_importar_crea_borradores_con_destino_mapa_y_registro(bancaria):
    c = _con_plataforma()
    sid = bancaria["id"]
    # Sin sindicato o sin preguntas, no hay qué importar.
    assert c.post(API + "/importar", json={"entrada": _entrada()}).status_code == 422
    assert c.post(API + "/importar", json={"entrada": {"nombre": "Vacío", "campos": []}, "sindicato_id": sid}).status_code == 422
    # El ensayo dice qué haría y no escribe.
    e = _entrada(respuestas={"aprueba": "otra", "area_aprueba": "Acción Social", "segundo": "si",
                             "enc_nombre": "Registro de retiro", "enc_datos": "Quién retira, DNI de quien retira"})
    antes = len(db.formularios_para_asistente(sid))
    ens = c.post(API + "/importar", json={"entrada": e, "sindicato_id": sid, "ensayo": True}).json()
    assert ens["ensayo"] is True and [x["clave"] for x in ens["creados"]] == ["encadenado_1", "principal"]
    assert ens["creados"][1]["codigo"] == "KE27" and ens["creados"][1]["id"] is None
    assert ens["creados"][1]["mapa"] == "2 de 3" and ens["creados"][1]["pase"] == "1 de 1"
    assert "Crear Área «Acción Social» en Córdoba" in ens["pendientes"]
    assert any("Grupo familiar" in p for p in ens["pendientes"])
    assert any("DNI del chico" in p for p in ens["pendientes"])
    assert len(db.formularios_para_asistente(sid)) == antes
    # Guardar el caso y después importar de verdad.
    caso_id = c.post(API + "/casos", json={"entrada": e, "sindicato_id": sid, "nota": "prueba"}).json()["id"]
    r = c.post(API + "/importar", json={"entrada": e, "sindicato_id": sid, "caso_id": caso_id}).json()
    assert r["ensayo"] is False and r["caso_id"] == caso_id
    enc, pri = r["creados"]
    assert pri["id"] and enc["id"] and pri["preguntas"] == 11 and pri["requisitos"] == 1
    t = db.tipo_tramite_por_id(pri["id"])
    assert t["borrador"] is True and t["activo"] is False and t["titulo"] == "Kit escolar 2027"
    assert t["area_destino_default_id"] == bancaria["areas"]["Sede Central"] and t["seccional_id"] is None
    assert len(t["campos"]) == 15 and t["campos"][5]["etiqueta"] == "DNI del chico"
    assert t["campos"][0]["tipo_dato"] == "calculado" and t["campos"][0]["validaciones"][0]["trae"] == "nombre"
    assert t["requisitos"][0]["trae"] == "en_padron"
    with Session(db.engine) as s:
        tipo = s.get(db.TipoTramite, pri["id"])
        assert tipo.permite_pase is True
        mapa = {d.seccional_id: d.area_id for d in s.exec(select(db.DestinoTipoTramite).where(db.DestinoTipoTramite.tipo_tramite_id == pri["id"])).all()}
        assert mapa == {bancaria["secs"]["Sede Central"]: bancaria["areas"]["Sede Central"],
                        bancaria["secs"]["Rosario"]: bancaria["areas"]["Rosario"]}
        pases = [x.area_id for x in s.exec(select(db.PaseTipoTramite).where(db.PaseTipoTramite.tipo_tramite_id == pri["id"])).all()]
        assert pases == [bancaria["areas"]["Sede Central"]]
        enc_tipo = s.get(db.TipoTramite, enc["id"])
        assert enc_tipo.borrador and enc_tipo.codigo == "KE27C1" and enc_tipo.titulo.startswith("Registro de retiro")
    # El caso registra la importación y pasa a aplicado.
    caso = c.get(API + f"/casos/{caso_id}").json()
    assert caso["estado"] == "aplicado" and caso["importaciones"][0]["quien"] == "snavello"
    assert [x["codigo"] for x in caso["importaciones"][0]["tipos"]] == ["KE27C1", "KE27"]
    assert caso["veredicto"] == "prerrequisito" and caso["titular"]
    # Importar otra vez renumera el código: KE27 ya está tomado.
    r2 = c.post(API + "/importar", json={"entrada": _entrada(), "sindicato_id": sid}).json()
    assert r2["creados"][0]["codigo"] == "KE27B"
    # El panel del sindicato lo lista como borrador y el afiliado no lo ve.
    admin = TestClient(main.app)
    admin.post("/admin/login", data={"usuario": "20111111120", "clave": "banc-demo"})
    html = admin.get("/admin").text
    assert "Kit escolar 2027" in html and ">borrador<" in html
    assert "KE27B" in html


def test_el_formulario_importado_abre_con_el_nombre_y_el_cuil_del_afiliado(bancaria):
    """SDN, 2026-10-28: «el formulario ya debe venir con el nombre y el
    documento del peticionante». Los dos primeros campos son extraídos del
    padrón; al publicar el borrador y abrirlo desde la app, vienen completos."""
    c = _con_plataforma()
    sid = bancaria["id"]
    e = {"nombre": "Cambio de domicilio", "respuestas": {"atiende": "central", "area": "Acción Social"},
         "campos": [{"etiqueta": "Domicilio nuevo", "tipo": "texto"}, {"etiqueta": "Nombre y apellido", "tipo": "texto"}]}
    r = c.post(API + "/importar", json={"entrada": e, "sindicato_id": sid}).json()
    tid = r["creados"][0]["id"]
    t = db.tipo_tramite_por_id(tid)
    assert [x["etiqueta"] for x in t["campos"]] == ["Apellido y nombre", "CUIL", "Domicilio nuevo"], "el nombre pedido de más se descartó"
    # Publicarlo como lo haría el Super Admin.
    db.editar_tipo_tramite(tid, sid, t["titulo"], t["codigo"], True, t["campos"], [],
                           area_destino_default_id=bancaria["areas"]["Sede Central"], borrador=False)
    afiliado = TestClient(main.app)
    afiliado.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=sid, ident="20111111112"))
    afiliado.cookies.set("cuil_trab", "20111111112")
    abre = afiliado.get(f"/api/tramite/requisitos/{tid}")
    assert abre.status_code == 200, abre.text
    calc = abre.json()["calculados"]
    ids = {x["etiqueta"]: x["id"] for x in db.tipo_tramite_por_id(tid)["campos"]}
    assert calc[str(ids["Apellido y nombre"])] == "Pérez, Juan" and calc[str(ids["CUIL"])] == "20111111112"


def test_actualizar_un_caso_lo_reescribe_sin_duplicar(bancaria):
    c = _con_plataforma()
    sid = bancaria["id"]
    caso_id = c.post(API + "/casos", json={"entrada": {"nombre": "Turno médico", "respuestas": {"fin": "turno"},
                                                       "campos": [{"etiqueta": "Motivo", "tipo": "texto"}]}, "sindicato_id": sid}).json()["id"]
    cuantos = len(c.get(API + "/casos").json()["casos"])
    r = c.post(API + f"/casos/{caso_id}", json={"entrada": {"nombre": "Turno odontológico", "respuestas": {"fin": "turno"},
                                                            "campos": [{"etiqueta": "Motivo", "tipo": "texto"}],
                                                            "aclaraciones": [{"pregunta": "¿Plazo?", "respuesta": "una semana"}]},
                                                "sindicato_id": sid, "nota": "segunda vuelta"})
    assert r.status_code == 200 and r.json()["id"] == caso_id
    assert len(c.get(API + "/casos").json()["casos"]) == cuantos
    d = c.get(API + f"/casos/{caso_id}").json()
    assert d["nombre"] == "Turno odontológico" and d["nota"] == "segunda vuelta"
    assert d["entrada"]["aclaraciones"] == [{"pregunta": "¿Plazo?", "respuesta": "una semana"}]
    assert "## Aclaraciones del analista" in d["resultado"]["prompt"] and "¿Plazo? una semana" in d["resultado"]["prompt"]
    assert c.post(API + "/casos/999999", json={"entrada": {"nombre": "x"}}).status_code == 404
