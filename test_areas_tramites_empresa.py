"""Trámites de empresa ruteados por área -- Fase 5 de SPRINT_AREAS.md.

Espejo de test_areas_tramites.py sobre las tablas de empleador, con UNA
diferencia de fondo que conviene tener presente: acá NO hay recorte por
seccional. Una empresa no pertenece a una seccional -- el Empleador no
tiene `seccional_id`, a diferencia del Trabajador -- así que el único eje
de recorte es el área. Hay un test que fija eso, para que no se "arregle"
por simetría en el futuro.

Correr con: python -m pytest test_areas_tramites_empresa.py -q
"""
import os
import tempfile
import json

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                Empleador, CuentaEmpleador, TipoTramiteEmpleador, TramiteEmpleador)
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM TramEmp", slug="uom-tramemp", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    rosario = Seccional(sindicato_id=SID, nombre="Rosario")
    s.add(central); s.add(rosario)
    s.commit(); s.refresh(central); s.refresh(rosario)
    SEC_CENTRAL, SEC_ROSARIO = central.id, rosario.id

    legales = Area(sindicato_id=SID, nombre="Secretaría Legal")
    tesoreria = Area(sindicato_id=SID, nombre="Tesorería")
    s.add(legales); s.add(tesoreria)
    s.commit(); s.refresh(legales); s.refresh(tesoreria)
    AREA_LEG, AREA_TES = legales.id, tesoreria.id
    for aid in (AREA_LEG, AREA_TES):
        s.add(PermisoArea(area_id=aid, seccion="emp_tramites_recibidos"))
        s.add(PermisoArea(area_id=aid, seccion="emp_tramites_formularios"))

    def _u(cuil, nombre, **kw):
        u = UsuarioSindicato(sindicato_id=SID, usuario=cuil, nombre=nombre,
                             clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False, **kw)
        s.add(u); return u
    jefa = _u("20111111110", "Jefa", es_super_admin=True, seccional_id=SEC_CENTRAL)
    gabriel = _u("20111111111", "Gabriel", area_id=AREA_LEG, seccional_id=SEC_ROSARIO)
    marta = _u("20111111112", "Marta", area_id=AREA_TES, seccional_id=SEC_ROSARIO)
    s.commit()
    for u in (jefa, gabriel, marta):
        s.refresh(u)
    U_JEFA, U_GABRIEL, U_MARTA = jefa.id, gabriel.id, marta.id

    s.add(CuentaEmpleador(cuit="30999888776", razon_social="Metalúrgica SA",
                          clave_hash=auth.hashear_clave("e")))
    s.add(Empleador(sindicato_id=SID, cuit="30999888776", razon_social="Metalúrgica SA",
                    activo=True))
    s.commit()

TIPO_LEG = db.crear_tipo_tramite_empleador(SID, "Reclamo legal", "E01",
                                           [{"etiqueta": "Detalle", "tipo_dato": "texto"}])
TIPO_TES = db.crear_tipo_tramite_empleador(SID, "Nómina", "E02",
                                           [{"etiqueta": "Monto", "tipo_dato": "texto"}])
TIPO_AMBAS = db.crear_tipo_tramite_empleador(SID, "Consulta", "E03",
                                             [{"etiqueta": "Consulta", "tipo_dato": "texto"}])
db.set_areas_tipo_tramite_empleador(TIPO_LEG, [AREA_LEG], SID)
db.set_areas_tipo_tramite_empleador(TIPO_TES, [AREA_TES], SID)
db.set_areas_tipo_tramite_empleador(TIPO_AMBAS, [AREA_LEG, AREA_TES], SID)

T_LEG = db.crear_tramite_empleador(SID, TIPO_LEG, "30999888776", [])["id"]
T_TES = db.crear_tramite_empleador(SID, TIPO_TES, "30999888776", [])["id"]
T_AMBAS = db.crear_tramite_empleador(SID, TIPO_AMBAS, "30999888776", [])["id"]


def _cli(cuil):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": cuil, "clave": "x"}, follow_redirects=False)
    assert r.status_code == 303
    return c


def _ids_que_ve(usuario_id):
    return {t["id"] for t in db.tramites_empleador_del_sindicato(SID, usuario_id=usuario_id)}


# ---------- Ruteo por área ----------

def test_cada_area_ve_solo_los_tipos_dirigidos_a_ella():
    assert _ids_que_ve(U_GABRIEL) == {T_LEG, T_AMBAS}
    assert _ids_que_ve(U_MARTA) == {T_TES, T_AMBAS}
    print("OK  test_cada_area_ve_solo_los_tipos_dirigidos_a_ella")


def test_el_super_admin_ve_todos():
    assert _ids_que_ve(U_JEFA) == {T_LEG, T_TES, T_AMBAS}
    print("OK  test_el_super_admin_ve_todos")


def test_no_hay_recorte_por_seccional_en_los_de_empresa():
    """A propósito: una empresa NO pertenece a una seccional (Empleador no
    tiene seccional_id). El único eje acá es el área. Si algún día se
    quisiera cambiar, hay que decidir antes qué seccional le corresponde a
    una empresa -- no es un olvido de simetría con el trabajador."""
    assert not hasattr(Empleador, "seccional_id") or \
        "seccional_id" not in Empleador.model_fields, \
        "si Empleador gana seccional, revisar este recorte"
    antes = _ids_que_ve(U_GABRIEL)
    with db.get_session() as s:
        sec = s.get(Seccional, SEC_ROSARIO)
        sec.ve_todas = True
        s.add(sec); s.commit()
    assert _ids_que_ve(U_GABRIEL) == antes, "ve_todas no cambia nada acá"
    with db.get_session() as s:
        sec = s.get(Seccional, SEC_ROSARIO)
        sec.ve_todas = False
        s.add(sec); s.commit()
    print("OK  test_no_hay_recorte_por_seccional_en_los_de_empresa")


def test_no_se_puede_abrir_por_url_uno_de_otra_area():
    c = _cli("20111111111")   # Gabriel, Legales
    assert c.get(f"/admin/tramite-empresa/{T_LEG}").status_code == 200
    assert c.get(f"/admin/tramite-empresa/{T_TES}").status_code == 403
    print("OK  test_no_se_puede_abrir_por_url_uno_de_otra_area")


# ---------- Tomar / liberar ----------

def test_tomar_deja_a_la_otra_area_en_solo_lectura():
    c = _cli("20111111111")
    r = c.post(f"/admin/tramite-empresa/{T_AMBAS}/tomar")
    assert r.status_code == 200 and r.json()["ok"] is True
    de_marta = [t for t in db.tramites_empleador_del_sindicato(SID, usuario_id=U_MARTA)
                if t["id"] == T_AMBAS][0]
    assert de_marta["area_a_cargo"] == "Secretaría Legal"
    assert de_marta["puede_responder"] is False
    print("OK  test_tomar_deja_a_la_otra_area_en_solo_lectura")


def test_la_otra_area_no_responde_ni_cambia_estado():
    c = _cli("20111111112")   # Marta
    assert c.post(f"/admin/tramite-empresa/{T_AMBAS}/nota",
                  data={"texto": "Me meto"}).status_code == 403
    assert c.post(f"/admin/tramite-empresa/{T_AMBAS}/estado",
                  data={"estado": "terminado"}).status_code == 403
    print("OK  test_la_otra_area_no_responde_ni_cambia_estado")


def test_el_area_a_cargo_responde_y_queda_su_area_en_la_nota():
    c = _cli("20111111111")
    r = c.post(f"/admin/tramite-empresa/{T_AMBAS}/nota", data={"texto": "Lo vemos"})
    assert r.status_code == 200, r.text
    detalle = db.tramite_empleador_detalle(T_AMBAS)
    nota = [n for n in detalle["notas"] if n["autor"] == "admin"][-1]
    assert nota["area"] == "Secretaría Legal"
    assert nota["autor_nombre"] == "Gabriel", "en el panel sí se ve quién"
    print("OK  test_el_area_a_cargo_responde_y_queda_su_area_en_la_nota")


def test_liberar_lo_devuelve_a_la_bandeja():
    c = _cli("20111111111")
    assert c.post(f"/admin/tramite-empresa/{T_AMBAS}/liberar").json()["ok"] is True
    de_marta = [t for t in db.tramites_empleador_del_sindicato(SID, usuario_id=U_MARTA)
                if t["id"] == T_AMBAS][0]
    assert de_marta["area_a_cargo_id"] is None and de_marta["puede_responder"] is True
    print("OK  test_liberar_lo_devuelve_a_la_bandeja")


# ---------- Formularios ----------

def test_no_se_puede_crear_un_formulario_externo_sin_area():
    c = _cli("20111111110")
    r = c.post("/admin/tramite-tipo-empresa", data={
        "titulo": "Sin destino", "codigo": "E99",
        "campos_json": json.dumps([{"etiqueta": "X", "tipo_dato": "texto"}]),
    }, follow_redirects=False)
    assert "error=sinareadestino" in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert s.exec(select(TipoTramiteEmpleador).where(
            TipoTramiteEmpleador.codigo == "E99")).first() is None
    print("OK  test_no_se_puede_crear_un_formulario_externo_sin_area")


def test_area_de_otro_sindicato_no_entra_como_destino():
    with db.get_session() as s:
        otro = Sindicato(nombre="Otro TramEmp", slug="otro-tramemp", color_base="#111111")
        s.add(otro); s.commit(); s.refresh(otro)
        ajena = Area(sindicato_id=otro.id, nombre="Ajena")
        s.add(ajena); s.commit(); s.refresh(ajena)
        AJENA = ajena.id
    db.set_areas_tipo_tramite_empleador(TIPO_LEG, [AREA_LEG, AJENA], SID)
    assert db.areas_de_tipo_tramite_empleador(TIPO_LEG) == [AREA_LEG]
    print("OK  test_area_de_otro_sindicato_no_entra_como_destino")


# ---------- El globo y lo que ve la empresa ----------

def test_el_globo_se_recorta_por_area():
    total = db.contar_tramites_empleador_nuevos(SID)
    assert db.contar_tramites_empleador_nuevos(SID, usuario_id=U_GABRIEL) < total
    assert db.contar_tramites_empleador_nuevos(SID, usuario_id=U_JEFA) == total
    print("OK  test_el_globo_se_recorta_por_area")


def test_la_api_de_la_empresa_no_manda_el_nombre_ni_el_ruteo():
    detalle = db.tramite_empleador_detalle(T_AMBAS)
    limpio = main._detalle_sin_datos_internos(detalle)
    assert all("autor_nombre" not in n for n in limpio["notas"])
    assert all("area" in n for n in limpio["notas"])
    for interno in ("area_a_cargo", "area_a_cargo_id", "areas_destino"):
        assert interno not in limpio
    print("OK  test_la_api_de_la_empresa_no_manda_el_nombre_ni_el_ruteo")


def test_los_dos_sistemas_de_tramites_no_se_cruzan():
    """Las tablas son espejos separados a propósito: un id de trámite de
    trabajador no puede resolverse como uno de empresa ni al revés."""
    assert db.tramite_empleador_detalle(999999) is None
    ids_emp = {t["id"] for t in db.tramites_empleador_del_sindicato(SID)}
    ids_trab = {t["id"] for t in db.tramites_del_sindicato(SID)}
    assert ids_emp and not ids_trab, "este sindicato solo tiene trámites de empresa"
    print("OK  test_los_dos_sistemas_de_tramites_no_se_cruzan")


if __name__ == "__main__":
    test_cada_area_ve_solo_los_tipos_dirigidos_a_ella()
    test_el_super_admin_ve_todos()
    test_no_hay_recorte_por_seccional_en_los_de_empresa()
    test_no_se_puede_abrir_por_url_uno_de_otra_area()
    test_tomar_deja_a_la_otra_area_en_solo_lectura()
    test_la_otra_area_no_responde_ni_cambia_estado()
    test_el_area_a_cargo_responde_y_queda_su_area_en_la_nota()
    test_liberar_lo_devuelve_a_la_bandeja()
    test_no_se_puede_crear_un_formulario_externo_sin_area()
    test_area_de_otro_sindicato_no_entra_como_destino()
    test_el_globo_se_recorta_por_area()
    test_la_api_de_la_empresa_no_manda_el_nombre_ni_el_ruteo()
    test_los_dos_sistemas_de_tramites_no_se_cruzan()
    print("\nTodos los tests de trámites de empresa por área pasaron.")
