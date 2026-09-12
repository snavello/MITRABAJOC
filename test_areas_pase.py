"""Pase de trámites entre áreas -- Fase 4 de SPRINT_AREAS_V2.md (N8).

El área que recibe un trámite puede derivarlo a otra, si el formulario lo
habilita y hacia una lista CERRADA de destinos. Tres invariantes que los
tests de acá fijan:

  1. SIEMPRE hay exactamente UN área responsable. Si dos pudieran escribir,
     el trabajador recibiría dos respuestas distintas al mismo planteo.
  2. La que derivó CONSERVA LECTURA. Derivar no puede ser perder de vista lo
     que uno pasó.
  3. El circuito es el que declara el formulario, no el que se le ocurra a
     quien deriva.

Correr con: python -m pytest test_areas_pase.py -q
"""
import json
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                Trabajador, TipoTramite, Tramite, CampoTramite)
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

CAMPOS = [{"etiqueta": "Motivo", "tipo_dato": "texto", "obligatorio": True}]

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Pase", slug="uom-pase", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(central); s.commit(); s.refresh(central)
    SEC = central.id

    legales = Area(sindicato_id=SID, seccional_id=SEC, nombre="Legales")
    tesoreria = Area(sindicato_id=SID, seccional_id=SEC, nombre="Tesorería")
    prensa = Area(sindicato_id=SID, seccional_id=SEC, nombre="Prensa")
    s.add(legales); s.add(tesoreria); s.add(prensa); s.commit()
    for x in (legales, tesoreria, prensa):
        s.refresh(x)
    A_LEG, A_TES, A_PRE = legales.id, tesoreria.id, prensa.id
    for a in (A_LEG, A_TES, A_PRE):
        s.add(PermisoArea(area_id=a, seccion="tramites_recibidos"))

    s.add(Trabajador(sindicato_id=SID, cuil="20300000001", nombre="Afiliado",
                     seccional_id=SEC, activo=True, registrado=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", cuil="20111111110",
                           nombre="Marta", clave_hash=auth.hashear_clave("marta"),
                           debe_cambiar_clave=False, es_super_admin=True, seccional_id=SEC))
    for cuil, nombre, area in [("20111111111", "Lea (Legales)", A_LEG),
                               ("20111111112", "Tito (Tesorería)", A_TES),
                               ("20111111113", "Pía (Prensa)", A_PRE)]:
        s.add(UsuarioSindicato(sindicato_id=SID, usuario=cuil, cuil=cuil, nombre=nombre,
                               clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False,
                               area_id=area, seccional_id=SEC))
    s.commit()

with db.get_session() as s:
    def _uid(cuil):
        return s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == cuil)).first().id
    U_LEA, U_TITO, U_PIA = _uid("20111111111"), _uid("20111111112"), _uid("20111111113")


def _cli(cuil, clave="x"):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": cuil, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303
    return c


def _admin():
    return _cli("20111111110", "marta")


def _crear_tipo(codigo, permite_pase, destinos_pase=()):
    datos = {"titulo": codigo, "codigo": codigo, "campos_json": json.dumps(CAMPOS),
             "area_destino_default_id": str(A_LEG)}
    if permite_pase:
        datos["permite_pase"] = "1"
        datos["areas_pase"] = [str(a) for a in destinos_pase]
    r = _admin().post("/admin/tramite-tipo", data=datos, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        return s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == SID, TipoTramite.codigo == codigo)).first().id


def _presentar(tipo_id):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", "20300000001")
    c.cookies.set("sind_elegido", str(SID))
    with Session(db.engine) as s:
        campo = s.exec(select(CampoTramite).where(
            CampoTramite.tipo_tramite_id == tipo_id)).first()
    r = c.post("/api/tramite", data={"tipo_tramite_id": str(tipo_id),
                                     f"campo_{campo.id}": "porque sí"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _area_de(tramite_id):
    with Session(db.engine) as s:
        return s.get(Tramite, tramite_id).area_a_cargo_id


# ---------- Sin pase habilitado ----------

def test_sin_permitir_pase_no_hay_a_donde_derivar():
    """Default False: un formulario que no diga nada no habilita circuitos."""
    tipo = _crear_tipo("NOPASE", permite_pase=False)
    tr = _presentar(tipo)
    assert db.areas_a_las_que_puede_pasar(tr) == []
    r = _cli("20111111111").post(f"/admin/tramite/{tr}/pase",
                                 data={"area_destino_id": str(A_TES)})
    assert r.status_code == 400
    assert _area_de(tr) == A_LEG
    print("OK  test_sin_permitir_pase_no_hay_a_donde_derivar")


# ---------- El circuito lo declara el formulario ----------

def test_solo_se_deriva_a_las_areas_que_el_formulario_declara():
    tipo = _crear_tipo("CONPASE", True, (A_TES,))
    tr = _presentar(tipo)
    ofrecidas = {a["id"] for a in db.areas_a_las_que_puede_pasar(tr)}
    assert ofrecidas == {A_TES}, "Prensa no está en la lista del formulario"
    r = _cli("20111111111").post(f"/admin/tramite/{tr}/pase",
                                 data={"area_destino_id": str(A_PRE)})
    assert r.status_code == 400, "un destino fuera de la lista se rechaza"
    assert _area_de(tr) == A_LEG
    print("OK  test_solo_se_deriva_a_las_areas_que_el_formulario_declara")


def test_no_se_ofrece_el_area_que_ya_lo_tiene():
    """Derivarle al que lo tiene no es un pase."""
    tipo = _crear_tipo("CONPASE2", True, (A_LEG, A_TES))
    tr = _presentar(tipo)
    assert {a["id"] for a in db.areas_a_las_que_puede_pasar(tr)} == {A_TES}
    print("OK  test_no_se_ofrece_el_area_que_ya_lo_tiene")


# ---------- El pase transfiere ----------

def test_el_pase_transfiere_y_la_que_derivo_conserva_lectura():
    tipo = _crear_tipo("F_TRANS", True, (A_TES,))
    tr = _presentar(tipo)
    r = _cli("20111111111").post(f"/admin/tramite/{tr}/pase",
                                 data={"area_destino_id": str(A_TES),
                                       "motivo": "esto es de Tesorería"})
    assert r.status_code == 200, r.text
    assert _area_de(tr) == A_TES

    # Lea (Legales) lo VE pero no lo responde.
    assert db.puede_ver_tramite(tr, U_LEA, SID) is True
    assert db.puede_responder_tramite(tr, U_LEA, SID) is False
    # Tito (Tesorería) lo ve Y lo responde.
    assert db.puede_ver_tramite(tr, U_TITO, SID) is True
    assert db.puede_responder_tramite(tr, U_TITO, SID) is True
    # Pía (Prensa) nunca lo tuvo: ni lo ve.
    assert db.puede_ver_tramite(tr, U_PIA, SID) is False
    print("OK  test_el_pase_transfiere_y_la_que_derivo_conserva_lectura")


def test_la_que_derivo_no_puede_escribir_aunque_mande_el_post_a_mano():
    """El 403 tiene que venir de la ruta, no de que la pantalla esconda el
    cajón de respuesta."""
    tipo = _crear_tipo("F_ESCR", True, (A_TES,))
    tr = _presentar(tipo)
    lea = _cli("20111111111")
    assert lea.post(f"/admin/tramite/{tr}/pase",
                    data={"area_destino_id": str(A_TES)}).status_code == 200
    assert lea.post(f"/admin/tramite/{tr}/nota", data={"texto": "igual contesto"}).status_code == 403
    assert lea.post(f"/admin/tramite/{tr}/nota",
                    data={"texto": "termino", "estado": "terminado"}).status_code == 403
    # Pero SÍ puede abrirlo.
    assert lea.get(f"/admin/tramite/{tr}").status_code == 200
    print("OK  test_la_que_derivo_no_puede_escribir_aunque_mande_el_post_a_mano")


def test_la_que_derivo_lo_sigue_viendo_en_su_bandeja():
    """Si el listado filtrara solo por área a cargo, derivar sería perderlo
    de vista y no habría forma de seguirle el rastro."""
    tipo = _crear_tipo("F_BAND", True, (A_TES,))
    tr = _presentar(tipo)
    _cli("20111111111").post(f"/admin/tramite/{tr}/pase", data={"area_destino_id": str(A_TES)})
    ids_lea = {t["id"] for t in db.tramites_del_sindicato(SID, usuario_id=U_LEA)}
    ids_tito = {t["id"] for t in db.tramites_del_sindicato(SID, usuario_id=U_TITO)}
    ids_pia = {t["id"] for t in db.tramites_del_sindicato(SID, usuario_id=U_PIA)}
    assert tr in ids_lea and tr in ids_tito and tr not in ids_pia
    print("OK  test_la_que_derivo_lo_sigue_viendo_en_su_bandeja")


# ---------- Cadena ----------

def test_la_cadena_funciona_y_se_puede_devolver():
    """El caso real: 'esto no era para nosotros'."""
    tipo = _crear_tipo("F_CAD", True, (A_LEG, A_TES, A_PRE))
    tr = _presentar(tipo)
    assert _cli("20111111111").post(f"/admin/tramite/{tr}/pase",
                                    data={"area_destino_id": str(A_TES)}).status_code == 200
    # Tesorería lo vuelve a derivar a Prensa
    assert _cli("20111111112").post(f"/admin/tramite/{tr}/pase",
                                    data={"area_destino_id": str(A_PRE)}).status_code == 200
    assert _area_de(tr) == A_PRE
    # Prensa lo DEVUELVE a Legales
    assert _cli("20111111113").post(f"/admin/tramite/{tr}/pase",
                                    data={"area_destino_id": str(A_LEG)}).status_code == 200
    assert _area_de(tr) == A_LEG
    # Las tres lo ven; solo Legales lo responde.
    for uid in (U_LEA, U_TITO, U_PIA):
        assert db.puede_ver_tramite(tr, uid, SID) is True
    assert db.puede_responder_tramite(tr, U_LEA, SID) is True
    assert db.puede_responder_tramite(tr, U_TITO, SID) is False
    assert db.puede_responder_tramite(tr, U_PIA, SID) is False
    print("OK  test_la_cadena_funciona_y_se_puede_devolver")


def test_siempre_hay_exactamente_un_area_responsable():
    """La invariante que sostiene todo: si dos pudieran escribir, el
    trabajador recibiría dos respuestas al mismo planteo."""
    tipo = _crear_tipo("F_UNO", True, (A_LEG, A_TES, A_PRE))
    tr = _presentar(tipo)
    for destino, quien in [(A_TES, "20111111111"), (A_PRE, "20111111112")]:
        _cli(quien).post(f"/admin/tramite/{tr}/pase", data={"area_destino_id": str(destino)})
        responden = [u for u in (U_LEA, U_TITO, U_PIA)
                     if db.puede_responder_tramite(tr, u, SID)]
        assert len(responden) == 1, responden
    print("OK  test_siempre_hay_exactamente_un_area_responsable")


# ---------- El movimiento queda en el chat ----------

def test_el_pase_queda_en_el_chat_nombrando_areas_y_no_personas():
    """Al afiliado se le dice el ÁREA, nunca la persona -- la misma regla
    que rige las respuestas. Protege al empleado de reclamos personales."""
    tipo = _crear_tipo("F_LOG", True, (A_TES,))
    tr = _presentar(tipo)
    _cli("20111111111").post(f"/admin/tramite/{tr}/pase",
                             data={"area_destino_id": str(A_TES), "motivo": "no es nuestro"})
    detalle = db.tramite_detalle(tr)
    pases = [l for l in detalle["log"] if l["evento"] == "pase"]
    assert len(pases) == 1, detalle["log"]
    texto = pases[0]["detalle"]
    assert "Legales" in texto and "Tesorería" in texto
    assert "no es nuestro" in texto
    assert "Lea" not in texto, "el nombre de la persona no va al chat"
    print("OK  test_el_pase_queda_en_el_chat_nombrando_areas_y_no_personas")


def test_un_tramite_terminado_no_se_deriva():
    tipo = _crear_tipo("F_FIN", True, (A_TES,))
    tr = _presentar(tipo)
    # El estado ya no se mueve solo: viaja con el mensaje (decisión N9).
    assert _cli("20111111111").post(
        f"/admin/tramite/{tr}/nota",
        data={"texto": "listo", "estado": "terminado"}).status_code == 200
    r = _cli("20111111111").post(f"/admin/tramite/{tr}/pase",
                                 data={"area_destino_id": str(A_TES)})
    assert r.status_code == 400
    assert _area_de(tr) == A_LEG
    print("OK  test_un_tramite_terminado_no_se_deriva")


def test_el_detalle_le_dice_a_cada_uno_que_puede_hacer():
    tipo = _crear_tipo("F_DET", True, (A_TES,))
    tr = _presentar(tipo)
    _cli("20111111111").post(f"/admin/tramite/{tr}/pase", data={"area_destino_id": str(A_TES)})
    de_lea = db.tramite_detalle(tr, usuario_id=U_LEA)
    de_tito = db.tramite_detalle(tr, usuario_id=U_TITO)
    assert de_lea["puede_responder"] is False and de_lea["areas_pase"] == []
    assert de_tito["puede_responder"] is True
    assert de_tito["area_a_cargo"] == "Tesorería"
    print("OK  test_el_detalle_le_dice_a_cada_uno_que_puede_hacer")


def test_el_chat_de_las_tres_apps_muestra_el_pase():
    """Un test de PLANTILLA, y hace falta: el chat se arma en el cliente
    filtrando los eventos del log, así que el movimiento puede existir en la
    base y no llegar nunca a la pantalla. Fue exactamente lo que pasó --
    db.tramite_detalle traía el pase y el chat lo descartaba, porque el
    filtro solo dejaba pasar "creado" y "cambio_estado". Ningún test contra
    db lo habría agarrado.
    """
    for archivo in ("templates/admin.html", "templates/trabajador.html",
                    "templates/empresa.html"):
        with open(archivo, encoding="utf-8") as f:
            html = f.read()
        assert "l.evento === 'pase'" in html, f"{archivo} no muestra los pases en el chat"
    print("OK  test_el_chat_de_las_tres_apps_muestra_el_pase")


def test_el_chat_ordena_el_pase_y_la_respuesta_del_mismo_minuto():
    """Contestar y derivar seguido es el caso normal, y las dos cosas caen en
    el mismo minuto: las fechas del chat se guardan a esa granularidad. Con
    solo la fecha, el empate lo rompía el orden en que el cliente concatena
    notas y eventos, así que el pase salía SIEMPRE después de todas las
    respuestas. `orden` (el id del log, que es la secuencia real de actos)
    es lo que arregla el hilo."""
    tipo = _crear_tipo("F_ORDEN", True, (A_TES,))
    tr = _presentar(tipo)
    c = _cli("20111111111")
    c.post(f"/admin/tramite/{tr}/nota", data={"texto": "Primero contesto.",
                                              "estado": "en_tratamiento"})
    c.post(f"/admin/tramite/{tr}/pase", data={"area_destino_id": str(A_TES)})
    _cli("20111111112").post(f"/admin/tramite/{tr}/nota",
                             data={"texto": "Y después sigo yo.",
                                   "estado": "respondido"})
    d = db.tramite_detalle(tr)

    hilo = sorted(
        [("nota", n["texto"], n["creado"], n["orden"]) for n in d["notas"]]
        + [("log", l["evento"], l["creado"], l["orden"]) for l in d["log"]
           if l["evento"] in ("creado", "pase")],
        key=lambda x: (x[2], x[3]))
    assert [x[1] for x in hilo] == [
        "creado", "Primero contesto.", "pase", "Y después sigo yo."], hilo
    # Y el `orden` es lo único que los separa: las fechas empatan.
    assert len({x[2] for x in hilo}) == 1, "el test no prueba nada si cambian de minuto"
    # De paso: cada mensaje llevó SU estado (N9), no uno suelto en el hilo.
    assert [n["estado_nuevo"] for n in d["notas"]] == ["en_tratamiento", "respondido"]
    assert d["estado"] == "respondido"
    print("OK  test_el_chat_ordena_el_pase_y_la_respuesta_del_mismo_minuto")


def test_las_tres_plantillas_desempatan_por_orden():
    """De plantilla, misma razón que el test del filtro de arriba: el hilo se
    arma en el cliente. Si el `.sort` vuelve a mirar solo la fecha, el pase
    se va otra vez al final del minuto y ningún test contra db lo ve."""
    for archivo in ("templates/admin.html", "templates/trabajador.html",
                    "templates/empresa.html"):
        with open(archivo, encoding="utf-8") as f:
            html = f.read()
        assert "(a.orden || 0) - (b.orden || 0)" in html, \
            f"{archivo} ordena el chat solo por fecha"
    print("OK  test_las_tres_plantillas_desempatan_por_orden")


def test_el_trabajador_ve_el_movimiento_sin_saber_quien_lo_movio():
    """Lo que le llega al afiliado por su propio endpoint. El área sí, la
    persona no -- protege al empleado de reclamos personales y mantiene la
    trazabilidad puertas adentro."""
    tipo = _crear_tipo("F_TRAB", True, (A_TES,))
    tr = _presentar(tipo)
    _cli("20111111111").post(f"/admin/tramite/{tr}/pase",
                             data={"area_destino_id": str(A_TES)})
    with Session(db.engine) as s:
        numero = s.get(Tramite, tr).numero_expediente

    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", "20300000001")
    c.cookies.set("sind_elegido", str(SID))
    d = c.get(f"/api/tramite/{numero}").json()

    pases = [l for l in d["log"] if l["evento"] == "pase"]
    assert len(pases) == 1
    assert "Tesorería" in pases[0]["detalle"]
    assert "Lea" not in json.dumps(d), "el nombre del empleado no viaja al afiliado"
    # Y no se le manda lo que es del panel.
    assert "puede_responder" not in d and "areas_pase" not in d
    print("OK  test_el_trabajador_ve_el_movimiento_sin_saber_quien_lo_movio")


if __name__ == "__main__":
    test_sin_permitir_pase_no_hay_a_donde_derivar()
    test_solo_se_deriva_a_las_areas_que_el_formulario_declara()
    test_no_se_ofrece_el_area_que_ya_lo_tiene()
    test_el_pase_transfiere_y_la_que_derivo_conserva_lectura()
    test_la_que_derivo_no_puede_escribir_aunque_mande_el_post_a_mano()
    test_la_que_derivo_lo_sigue_viendo_en_su_bandeja()
    test_la_cadena_funciona_y_se_puede_devolver()
    test_siempre_hay_exactamente_un_area_responsable()
    test_el_pase_queda_en_el_chat_nombrando_areas_y_no_personas()
    test_un_tramite_terminado_no_se_deriva()
    test_el_detalle_le_dice_a_cada_uno_que_puede_hacer()
    test_el_chat_de_las_tres_apps_muestra_el_pase()
    test_el_chat_ordena_el_pase_y_la_respuesta_del_mismo_minuto()
    test_las_tres_plantillas_desempatan_por_orden()
    test_el_trabajador_ve_el_movimiento_sin_saber_quien_lo_movio()
    print("\nTodos los tests del pase pasaron.")
