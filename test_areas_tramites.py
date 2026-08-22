"""Trámites ruteados por área -- Fase 4 de SPRINT_AREAS.md.

Dos ejes que se cruzan y hay que probar por separado y juntos:
- ÁREA: el trámite lo ven las áreas destino del formulario.
- SECCIONAL: y además, solo si el trabajador cae en el alcance del usuario.

Más el "una lo toma": las dos áreas destino lo ven, pero responde la que lo
tomó, para que el trabajador no reciba dos respuestas al mismo planteo.

Correr con: python -m pytest test_areas_tramites.py -q
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                Trabajador, CuentaTrabajador, TipoTramite, AreaTipoTramite, Tramite)
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Tram", slug="uom-tram", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    rosario = Seccional(sindicato_id=SID, nombre="Rosario")
    cordoba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(central); s.add(rosario); s.add(cordoba)
    s.commit(); s.refresh(central); s.refresh(rosario); s.refresh(cordoba)
    SEC_CENTRAL, SEC_ROSARIO, SEC_CORDOBA = central.id, rosario.id, cordoba.id

    legales = Area(sindicato_id=SID, nombre="Secretaría Legal")
    tesoreria = Area(sindicato_id=SID, nombre="Tesorería")
    s.add(legales); s.add(tesoreria)
    s.commit(); s.refresh(legales); s.refresh(tesoreria)
    AREA_LEG, AREA_TES = legales.id, tesoreria.id
    for aid in (AREA_LEG, AREA_TES):
        s.add(PermisoArea(area_id=aid, seccion="tramites_recibidos"))

    # Jefa: Super Admin. Gabriel: Legales/Rosario. Marta: Tesorería/Rosario.
    # Carlos: Legales pero en Córdoba -- sirve para el eje seccional.
    def _u(cuil, nombre, **kw):
        u = UsuarioSindicato(sindicato_id=SID, usuario=cuil, nombre=nombre,
                             clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False, **kw)
        s.add(u); return u
    jefa = _u("20111111110", "Jefa", es_super_admin=True, seccional_id=SEC_CENTRAL)
    gabriel = _u("20111111111", "Gabriel", area_id=AREA_LEG, seccional_id=SEC_ROSARIO)
    marta = _u("20111111112", "Marta", area_id=AREA_TES, seccional_id=SEC_ROSARIO)
    carlos = _u("20111111113", "Carlos", area_id=AREA_LEG, seccional_id=SEC_CORDOBA)
    s.commit()
    for u in (jefa, gabriel, marta, carlos):
        s.refresh(u)
    U_JEFA, U_GABRIEL, U_MARTA, U_CARLOS = jefa.id, gabriel.id, marta.id, carlos.id

    # Dos trabajadores, uno por seccional.
    for cuil, nombre, sec in [("20999999990", "Ana Rosario", SEC_ROSARIO),
                              ("20999999991", "Beto Córdoba", SEC_CORDOBA)]:
        s.add(CuentaTrabajador(cuil=cuil, nombre=nombre, clave_hash=auth.hashear_clave("t")))
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, nombre=nombre, activo=True,
                         registrado=True, seccional_id=sec))
    s.commit()

# Tres formularios: uno a Legales, uno a Tesorería, uno a las dos.
TIPO_LEG = db.crear_tipo_tramite(SID, "Reclamo legal", "F01",
                                 [{"etiqueta": "Detalle", "tipo_dato": "texto"}])
TIPO_TES = db.crear_tipo_tramite(SID, "Reintegro", "F02",
                                 [{"etiqueta": "Monto", "tipo_dato": "texto"}])
TIPO_AMBAS = db.crear_tipo_tramite(SID, "Consulta general", "F03",
                                   [{"etiqueta": "Consulta", "tipo_dato": "texto"}])
db.set_areas_tipo_tramite(TIPO_LEG, [AREA_LEG], SID)
db.set_areas_tipo_tramite(TIPO_TES, [AREA_TES], SID)
db.set_areas_tipo_tramite(TIPO_AMBAS, [AREA_LEG, AREA_TES], SID)

# Trámites: Ana (Rosario) presenta los tres; Beto (Córdoba) presenta el legal.
T_LEG_ANA = db.crear_tramite(SID, TIPO_LEG, "20999999990", [])["id"]
T_TES_ANA = db.crear_tramite(SID, TIPO_TES, "20999999990", [])["id"]
T_AMBAS_ANA = db.crear_tramite(SID, TIPO_AMBAS, "20999999990", [])["id"]
T_LEG_BETO = db.crear_tramite(SID, TIPO_LEG, "20999999991", [])["id"]


def _cli(cuil):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": cuil, "clave": "x"}, follow_redirects=False)
    assert r.status_code == 303
    return c


def _ids_que_ve(usuario_id):
    return {t["id"] for t in db.tramites_del_sindicato(SID, usuario_id=usuario_id)}


# ---------- Eje ÁREA ----------

def test_cada_area_ve_solo_los_tipos_dirigidos_a_ella():
    assert _ids_que_ve(U_GABRIEL) == {T_LEG_ANA, T_AMBAS_ANA}, "Legales no ve el de Tesorería"
    assert _ids_que_ve(U_MARTA) == {T_TES_ANA, T_AMBAS_ANA}, "Tesorería no ve el legal"
    print("OK  test_cada_area_ve_solo_los_tipos_dirigidos_a_ella")


def test_el_super_admin_ve_todos():
    assert _ids_que_ve(U_JEFA) == {T_LEG_ANA, T_TES_ANA, T_AMBAS_ANA, T_LEG_BETO}
    print("OK  test_el_super_admin_ve_todos")


def test_usuario_sin_area_no_ve_ninguno():
    with db.get_session() as s:
        u = UsuarioSindicato(sindicato_id=SID, usuario="20111111119", nombre="Huérfano",
                             clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False,
                             seccional_id=SEC_CENTRAL)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    assert _ids_que_ve(uid) == set()
    print("OK  test_usuario_sin_area_no_ve_ninguno")


# ---------- Eje SECCIONAL ----------

def test_la_seccional_recorta_ademas_del_area():
    """Carlos es de Legales igual que Gabriel, pero en Córdoba: ve el trámite
    de Beto (Córdoba) y NO el de Ana (Rosario)."""
    assert _ids_que_ve(U_CARLOS) == {T_LEG_BETO}
    assert T_LEG_ANA in _ids_que_ve(U_GABRIEL)
    assert T_LEG_ANA not in _ids_que_ve(U_CARLOS)
    print("OK  test_la_seccional_recorta_ademas_del_area")


def test_ve_todas_levanta_el_recorte_de_seccional():
    with db.get_session() as s:
        sec = s.get(Seccional, SEC_CORDOBA)
        sec.ve_todas = True
        s.add(sec); s.commit()
    assert _ids_que_ve(U_CARLOS) == {T_LEG_ANA, T_AMBAS_ANA, T_LEG_BETO}, \
        "con ve_todas alcanza las dos seccionales, pero sigue acotado a su área"
    with db.get_session() as s:
        sec = s.get(Seccional, SEC_CORDOBA)
        sec.ve_todas = False
        s.add(sec); s.commit()
    print("OK  test_ve_todas_levanta_el_recorte_de_seccional")


# ---------- Ruta de detalle ----------

def test_no_se_puede_abrir_un_tramite_de_otra_area_por_url():
    """El listado viene filtrado, pero el id de detalle llega por la URL."""
    c = _cli("20111111111")   # Gabriel, Legales
    assert c.get(f"/admin/tramite/{T_LEG_ANA}").status_code == 200
    assert c.get(f"/admin/tramite/{T_TES_ANA}").status_code == 403, "es de Tesorería"
    assert c.get(f"/admin/tramite/{T_LEG_BETO}").status_code == 403, "es de otra seccional"
    print("OK  test_no_se_puede_abrir_un_tramite_de_otra_area_por_url")


# ---------- Tomar / liberar ----------

def test_tomar_deja_a_la_otra_area_en_solo_lectura():
    c = _cli("20111111111")   # Gabriel, Legales
    r = c.post(f"/admin/tramite/{T_AMBAS_ANA}/tomar")
    assert r.status_code == 200 and r.json()["ok"] is True

    de_gabriel = [t for t in db.tramites_del_sindicato(SID, usuario_id=U_GABRIEL)
                  if t["id"] == T_AMBAS_ANA][0]
    de_marta = [t for t in db.tramites_del_sindicato(SID, usuario_id=U_MARTA)
                if t["id"] == T_AMBAS_ANA][0]
    assert de_gabriel["area_a_cargo"] == "Secretaría Legal"
    assert de_gabriel["puede_responder"] is True
    assert de_marta["area_a_cargo"] == "Secretaría Legal", "Tesorería lo sigue viendo"
    assert de_marta["puede_responder"] is False, "pero en solo lectura"
    print("OK  test_tomar_deja_a_la_otra_area_en_solo_lectura")


def test_la_otra_area_no_puede_responder_ni_cambiar_estado():
    c = _cli("20111111112")   # Marta, Tesorería
    r = c.post(f"/admin/tramite/{T_AMBAS_ANA}/nota", data={"texto": "Me meto"})
    assert r.status_code == 403, "lo tomó Legales"
    r = c.post(f"/admin/tramite/{T_AMBAS_ANA}/estado", data={"estado": "terminado"})
    assert r.status_code == 403
    print("OK  test_la_otra_area_no_puede_responder_ni_cambiar_estado")


def test_el_area_a_cargo_si_puede_responder():
    c = _cli("20111111111")   # Gabriel
    r = c.post(f"/admin/tramite/{T_AMBAS_ANA}/nota", data={"texto": "Lo vemos"})
    assert r.status_code == 200, r.text
    print("OK  test_el_area_a_cargo_si_puede_responder")


def test_el_super_admin_responde_aunque_lo_tenga_otra_area():
    c = _cli("20111111110")
    r = c.post(f"/admin/tramite/{T_AMBAS_ANA}/nota", data={"texto": "Desde arriba"})
    assert r.status_code == 200, r.text
    print("OK  test_el_super_admin_responde_aunque_lo_tenga_otra_area")


def test_liberar_lo_devuelve_a_la_bandeja_comun():
    c = _cli("20111111111")
    r = c.post(f"/admin/tramite/{T_AMBAS_ANA}/liberar")
    assert r.status_code == 200 and r.json()["ok"] is True
    de_marta = [t for t in db.tramites_del_sindicato(SID, usuario_id=U_MARTA)
                if t["id"] == T_AMBAS_ANA][0]
    assert de_marta["area_a_cargo_id"] is None
    assert de_marta["puede_responder"] is True, "vuelve a estar disponible para las dos"
    print("OK  test_liberar_lo_devuelve_a_la_bandeja_comun")


def test_no_se_puede_tomar_un_tramite_de_otra_area():
    c = _cli("20111111112")   # Marta, Tesorería
    r = c.post(f"/admin/tramite/{T_LEG_ANA}/tomar")
    assert r.status_code == 403
    print("OK  test_no_se_puede_tomar_un_tramite_de_otra_area")


# ---------- El globo ----------

def test_el_globo_cuenta_solo_lo_que_ese_usuario_ve():
    """Un globo que contara trámites de otra área sería un número que nunca
    baja al abrirlos, porque no aparecen en su bandeja."""
    total = db.contar_tramites_nuevos(SID)
    assert db.contar_tramites_nuevos(SID, usuario_id=U_CARLOS) < total
    assert db.contar_tramites_nuevos(SID, usuario_id=U_JEFA) == total
    print("OK  test_el_globo_cuenta_solo_lo_que_ese_usuario_ve")


# ---------- Formularios ----------

def test_no_se_puede_crear_un_formulario_sin_area_receptora():
    """Un formulario sin área genera trámites que no ve nadie -- justo lo
    que esta fase vino a evitar."""
    c = _cli("20111111110")
    r = c.post("/admin/tramite-tipo", data={
        "titulo": "Sin destino", "codigo": "F99",
        "campos_json": '[{"etiqueta":"X","tipo_dato":"texto"}]',
    }, follow_redirects=False)
    assert "error=sinareadestino" in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert s.exec(select(TipoTramite).where(TipoTramite.codigo == "F99")).first() is None
    print("OK  test_no_se_puede_crear_un_formulario_sin_area_receptora")


def test_un_area_de_otro_sindicato_no_entra_como_destino():
    with db.get_session() as s:
        otro = Sindicato(nombre="Otro Tram", slug="otro-tram", color_base="#111111")
        s.add(otro); s.commit(); s.refresh(otro)
        ajena = Area(sindicato_id=otro.id, nombre="Ajena")
        s.add(ajena); s.commit(); s.refresh(ajena)
        AJENA = ajena.id
    db.set_areas_tipo_tramite(TIPO_LEG, [AREA_LEG, AJENA], SID)
    assert db.areas_de_tipo_tramite(TIPO_LEG) == [AREA_LEG]
    print("OK  test_un_area_de_otro_sindicato_no_entra_como_destino")


# ---------- Lo que ve el trabajador ----------

def test_el_trabajador_ve_el_area_pero_no_la_persona():
    detalle = db.tramite_detalle(T_AMBAS_ANA)
    notas = [n for n in detalle["notas"] if n["autor"] == "admin"]
    assert notas, "el test de responder dejó notas"
    de_gabriel = [n for n in notas if n["autor_nombre"] == "Gabriel"]
    assert de_gabriel, "en el panel sí se ve quién escribió"
    assert de_gabriel[0]["area"] == "Secretaría Legal"
    # Un Super Admin no tiene área: se sigue firmando como "Tu sindicato".
    de_jefa = [n for n in notas if n["autor_nombre"] == "Jefa"]
    assert de_jefa and de_jefa[0]["area"] == ""
    print("OK  test_el_trabajador_ve_el_area_pero_no_la_persona")


def test_la_api_del_trabajador_no_manda_el_nombre_ni_el_ruteo():
    """El detalle interno lleva autor_nombre y el ruteo: la API del
    trabajador tiene que sacarlos antes de responder."""
    detalle = db.tramite_detalle(T_AMBAS_ANA)
    limpio = main._detalle_sin_datos_internos(detalle)
    assert all("autor_nombre" not in n for n in limpio["notas"])
    assert all("area" in n for n in limpio["notas"]), "el área sí la ve"
    for interno in ("area_a_cargo", "area_a_cargo_id", "areas_destino"):
        assert interno not in limpio
    print("OK  test_la_api_del_trabajador_no_manda_el_nombre_ni_el_ruteo")


if __name__ == "__main__":
    test_cada_area_ve_solo_los_tipos_dirigidos_a_ella()
    test_el_super_admin_ve_todos()
    test_usuario_sin_area_no_ve_ninguno()
    test_la_seccional_recorta_ademas_del_area()
    test_ve_todas_levanta_el_recorte_de_seccional()
    test_no_se_puede_abrir_un_tramite_de_otra_area_por_url()
    test_tomar_deja_a_la_otra_area_en_solo_lectura()
    test_la_otra_area_no_puede_responder_ni_cambiar_estado()
    test_el_area_a_cargo_si_puede_responder()
    test_el_super_admin_responde_aunque_lo_tenga_otra_area()
    test_liberar_lo_devuelve_a_la_bandeja_comun()
    test_no_se_puede_tomar_un_tramite_de_otra_area()
    test_el_globo_cuenta_solo_lo_que_ese_usuario_ve()
    test_no_se_puede_crear_un_formulario_sin_area_receptora()
    test_un_area_de_otro_sindicato_no_entra_como_destino()
    test_el_trabajador_ve_el_area_pero_no_la_persona()
    test_la_api_del_trabajador_no_manda_el_nombre_ni_el_ruteo()
    print("\nTodos los tests de trámites por área pasaron.")
