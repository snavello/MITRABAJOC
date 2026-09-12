"""Ruteo de trámites por área -- Fase 3 de SPRINT_AREAS_V2.md.

El formulario declara a qué área cae el trámite, seccional por seccional,
con un destino por defecto obligatorio (decisión N6); y puede ser global o
de una seccional (N7).

Lo que más importa probar son los agujeros del mapa: la seccional que nadie
mapeó, la que nace DESPUÉS del formulario, y el trabajador sin seccional
cargada. Los tres tienen que caer en algún lado -- un trámite sin área no
aparece en ninguna bandeja y nadie se entera.

Correr con: python -m pytest test_areas_ruteo.py -q
"""
import json
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                Trabajador, TipoTramite, Tramite)
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

CAMPOS = [{"etiqueta": "Motivo", "tipo_dato": "texto", "obligatorio": True}]

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Ruteo", slug="uom-ruteo", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    rosario = Seccional(sindicato_id=SID, nombre="Rosario")
    cordoba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(central); s.add(rosario); s.add(cordoba); s.commit()
    for x in (central, rosario, cordoba):
        s.refresh(x)
    SEC_CENTRAL, SEC_ROSARIO, SEC_CORDOBA = central.id, rosario.id, cordoba.id

    mesa = Area(sindicato_id=SID, seccional_id=SEC_CENTRAL, nombre="Mesa de Entradas")
    legales_ros = Area(sindicato_id=SID, seccional_id=SEC_ROSARIO, nombre="Legales Rosario")
    legales_cba = Area(sindicato_id=SID, seccional_id=SEC_CORDOBA, nombre="Legales Córdoba")
    s.add(mesa); s.add(legales_ros); s.add(legales_cba); s.commit()
    for x in (mesa, legales_ros, legales_cba):
        s.refresh(x)
    AREA_MESA, AREA_ROS, AREA_CBA = mesa.id, legales_ros.id, legales_cba.id
    for a in (AREA_MESA, AREA_ROS, AREA_CBA):
        s.add(PermisoArea(area_id=a, seccion="tramites_recibidos"))

    # Trabajadores: uno por seccional, y uno SIN seccional cargada.
    s.add(Trabajador(sindicato_id=SID, cuil="20300000001", nombre="Rosarino",
                     seccional_id=SEC_ROSARIO, activo=True, registrado=True))
    s.add(Trabajador(sindicato_id=SID, cuil="20300000002", nombre="Cordobés",
                     seccional_id=SEC_CORDOBA, activo=True, registrado=True))
    s.add(Trabajador(sindicato_id=SID, cuil="20300000003", nombre="Sin Seccional",
                     seccional_id=None, activo=True, registrado=True))

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", cuil="20111111110",
                           nombre="Marta", clave_hash=auth.hashear_clave("marta"),
                           debe_cambiar_clave=False, es_super_admin=True, seccional_id=SEC_CENTRAL))
    # Dos usuarios de área, uno por delegación: mismo permiso, distinta vista.
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111111", cuil="20111111111",
                           nombre="Ana (Rosario)", clave_hash=auth.hashear_clave("ana"),
                           debe_cambiar_clave=False, area_id=AREA_ROS, seccional_id=SEC_ROSARIO))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111112", cuil="20111111112",
                           nombre="Beto (Córdoba)", clave_hash=auth.hashear_clave("beto"),
                           debe_cambiar_clave=False, area_id=AREA_CBA, seccional_id=SEC_CORDOBA))
    s.commit()

with db.get_session() as s:
    U_ANA = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "20111111111")).first().id
    U_BETO = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "20111111112")).first().id


def _admin():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": "20111111110", "clave": "marta"},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def _panel(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def _trabajador(cuil):
    """El sindicato activo sale del CUIL (ver sindicato_activo_trabajador):
    con uno solo empadronado no hace falta la cookie de elección."""
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    c.cookies.set("sind_elegido", str(SID))
    return c


def _crear_tipo(c, titulo, codigo, default, destinos=None, seccional=None):
    datos = {"titulo": titulo, "codigo": codigo, "campos_json": json.dumps(CAMPOS),
             "area_destino_default_id": str(default),
             "destinos_json": json.dumps({str(k): str(v) for k, v in (destinos or {}).items()})}
    if seccional:
        datos["seccional_id"] = str(seccional)
    r = c.post("/admin/tramite-tipo", data=datos, follow_redirects=False)
    with Session(db.engine) as s:
        t = s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == SID, TipoTramite.codigo == codigo)).first()
    return r, (t.id if t else None)


def _presentar(cuil, tipo_id):
    c = _trabajador(cuil)
    with Session(db.engine) as s:
        campo = s.exec(select(db.CampoTramite).where(
            db.CampoTramite.tipo_tramite_id == tipo_id)).first()
    r = c.post("/api/tramite", data={
        "tipo_tramite_id": str(tipo_id), f"campo_{campo.id}": "porque sí"})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- El destino por defecto es obligatorio ----------

def test_sin_destino_por_defecto_no_se_guarda():
    """Un formulario sin destino dejaría trámites sin área, y un trámite sin
    área no aparece en NINGUNA bandeja: el error sería invisible."""
    c = _admin()
    r = c.post("/admin/tramite-tipo", data={
        "titulo": "Sin Destino", "codigo": "SD01", "campos_json": json.dumps(CAMPOS),
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error=sindestino" in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert s.exec(select(TipoTramite).where(TipoTramite.codigo == "SD01")).first() is None
    print("OK  test_sin_destino_por_defecto_no_se_guarda")


# ---------- El mapa rutea ----------

def test_el_mapa_manda_cada_seccional_a_su_area():
    c = _admin()
    r, tipo_id = _crear_tipo(c, "Reintegro", "F01",
                             default=AREA_MESA,
                             destinos={SEC_ROSARIO: AREA_ROS, SEC_CORDOBA: AREA_CBA})
    assert r.status_code == 303 and tipo_id
    assert db.area_destino_para(tipo_id, SEC_ROSARIO) == AREA_ROS
    assert db.area_destino_para(tipo_id, SEC_CORDOBA) == AREA_CBA
    print("OK  test_el_mapa_manda_cada_seccional_a_su_area")


def test_la_seccional_sin_mapear_cae_al_default():
    tipo_id = _tipo("F01")
    # Sede Central no está en el mapa.
    assert db.area_destino_para(tipo_id, SEC_CENTRAL) == AREA_MESA
    print("OK  test_la_seccional_sin_mapear_cae_al_default")


def test_el_trabajador_sin_seccional_cae_al_default():
    """No es un caso teórico: la seccional del trabajador puede quedar en
    NULL si se lo cargó por alta masiva."""
    tipo_id = _tipo("F01")
    assert db.area_destino_para(tipo_id, None) == AREA_MESA
    print("OK  test_el_trabajador_sin_seccional_cae_al_default")


def test_una_seccional_nueva_funciona_sin_tocar_el_formulario():
    """El motivo de que el default sea obligatorio: una delegación que nace
    después del formulario tiene que andar desde el minuto cero."""
    tipo_id = _tipo("F01")
    with db.get_session() as s:
        nueva = Seccional(sindicato_id=SID, nombre="Mendoza")
        s.add(nueva); s.commit(); s.refresh(nueva)
        sec_nueva = nueva.id
    assert db.area_destino_para(tipo_id, sec_nueva) == AREA_MESA
    print("OK  test_una_seccional_nueva_funciona_sin_tocar_el_formulario")


def _tipo(codigo):
    with Session(db.engine) as s:
        return s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == SID, TipoTramite.codigo == codigo)).first().id


# ---------- El trámite nace con su área escrita ----------

def test_el_tramite_queda_con_el_area_que_le_toco():
    tipo_id = _tipo("F01")
    datos = _presentar("20300000001", tipo_id)       # de Rosario
    with Session(db.engine) as s:
        tr = s.get(Tramite, datos["id"])
        assert tr.area_a_cargo_id == AREA_ROS
    datos2 = _presentar("20300000003", tipo_id)      # sin seccional
    with Session(db.engine) as s:
        assert s.get(Tramite, datos2["id"]).area_a_cargo_id == AREA_MESA
    print("OK  test_el_tramite_queda_con_el_area_que_le_toco")


def test_cambiar_el_mapa_no_mueve_los_tramites_ya_presentados():
    """El área queda ESCRITA en la fila. Si se recalculara en cada consulta,
    reconfigurar el formulario le sacaría de la bandeja trámites que alguien
    ya venía trabajando, sin que nadie se entere."""
    tipo_id = _tipo("F01")
    with Session(db.engine) as s:
        antes = s.exec(select(Tramite).where(
            Tramite.tipo_tramite_id == tipo_id, Tramite.cuil == "20300000001")).first()
        area_antes = antes.area_a_cargo_id
    db.set_destinos_tipo_tramite(tipo_id, {SEC_ROSARIO: AREA_MESA}, SID)
    with Session(db.engine) as s:
        assert s.get(Tramite, antes.id).area_a_cargo_id == area_antes
    # se restaura para los tests que siguen
    db.set_destinos_tipo_tramite(tipo_id, {SEC_ROSARIO: AREA_ROS, SEC_CORDOBA: AREA_CBA}, SID)
    print("OK  test_cambiar_el_mapa_no_mueve_los_tramites_ya_presentados")


# ---------- Los dos ejes en la bandeja ----------

def test_cada_area_ve_solo_lo_suyo():
    tipo_id = _tipo("F01")
    _presentar("20300000002", tipo_id)               # de Córdoba -> AREA_CBA
    de_ana = db.tramites_del_sindicato(SID, usuario_id=U_ANA)
    de_beto = db.tramites_del_sindicato(SID, usuario_id=U_BETO)
    assert de_ana and all(t["cuil"] == "20300000001" for t in de_ana), de_ana
    assert de_beto and all(t["cuil"] == "20300000002" for t in de_beto), de_beto
    # El administrador general los ve todos.
    assert len(db.tramites_del_sindicato(SID)) >= len(de_ana) + len(de_beto)
    print("OK  test_cada_area_ve_solo_lo_suyo")


def test_dos_areas_de_la_MISMA_seccional_no_se_ven_entre_si():
    """Aísla el eje ÁREA. Los tests de arriba comparan a Ana (Rosario) con
    Beto (Córdoba), así que el recorte por seccional ALCANZA para separarlos
    -- y el filtro por área podría estar roto sin que nadie se entere. Se
    confirmó mutando el código: sacando el recorte por área, aquellos tests
    seguían pasando.

    Acá los dos trámites son del MISMO trabajador, de la MISMA seccional, y
    lo único que los separa es el área destino de su formulario."""
    c = _admin()
    with db.get_session() as s:
        tesoreria = Area(sindicato_id=SID, seccional_id=SEC_ROSARIO, nombre="Tesorería Rosario")
        s.add(tesoreria); s.commit(); s.refresh(tesoreria)
        area_tes = tesoreria.id
        s.add(PermisoArea(area_id=area_tes, seccion="tramites_recibidos"))
        tito = UsuarioSindicato(
            sindicato_id=SID, usuario="20111111113", cuil="20111111113",
            nombre="Tito (Tesorería Rosario)", clave_hash=auth.hashear_clave("tito"),
            debe_cambiar_clave=False, area_id=area_tes, seccional_id=SEC_ROSARIO)
        s.add(tito); s.commit(); s.refresh(tito)
        u_tito = tito.id

    # Un formulario que manda lo de Rosario a Tesorería, no a Legales.
    _crear_tipo(c, "Reintegro Tesorería", "F02", default=AREA_MESA,
                destinos={SEC_ROSARIO: area_tes})
    presentado = _presentar("20300000001", _tipo("F02"))   # el MISMO trabajador

    de_ana = {t["numero_expediente"] for t in db.tramites_del_sindicato(SID, usuario_id=U_ANA)}
    de_tito = {t["numero_expediente"] for t in db.tramites_del_sindicato(SID, usuario_id=u_tito)}
    with Session(db.engine) as s:
        numero = s.get(Tramite, presentado["id"]).numero_expediente
    assert numero in de_tito, "le toca a Tesorería"
    assert numero not in de_ana, "Legales NO lo ve, aunque sea de su misma seccional"
    assert de_ana, "y Legales sigue viendo los suyos"
    print("OK  test_dos_areas_de_la_MISMA_seccional_no_se_ven_entre_si")


def test_el_globo_cuenta_lo_mismo_que_la_bandeja():
    """Un globo que contara trámites de otra área nunca bajaría a cero: al
    abrir la pestaña no aparecen, así que no hay forma de hacerlo
    desaparecer."""
    for uid in (U_ANA, U_BETO):
        bandeja = [t for t in db.tramites_del_sindicato(SID, usuario_id=uid)
                   if t["estado"] == "iniciado"]
        assert db.contar_tramites_nuevos(SID, uid) == len(bandeja)
    print("OK  test_el_globo_cuenta_lo_mismo_que_la_bandeja")


def test_abrir_por_url_un_tramite_de_otra_area_da_403():
    """Filtrar el listado no alcanza: acá el id llega por la URL."""
    tipo_id = _tipo("F01")
    with Session(db.engine) as s:
        del_cordobes = s.exec(select(Tramite).where(
            Tramite.tipo_tramite_id == tipo_id, Tramite.cuil == "20300000002")).first()
    c = _panel("20111111111", "ana")                 # Ana es de Rosario
    r = c.get(f"/admin/tramite/{del_cordobes.id}")
    assert r.status_code == 403, r.status_code
    r = c.post(f"/admin/tramite/{del_cordobes.id}/nota", data={"texto": "me colé"})
    assert r.status_code == 403
    r = c.post(f"/admin/tramite/{del_cordobes.id}/nota",
               data={"texto": "me colé", "estado": "terminado"})
    assert r.status_code == 403
    # Y el suyo sí lo abre, para que el 403 no venga de otra cosa.
    with Session(db.engine) as s:
        propio = s.exec(select(Tramite).where(
            Tramite.tipo_tramite_id == tipo_id, Tramite.cuil == "20300000001")).first()
    assert c.get(f"/admin/tramite/{propio.id}").status_code == 200
    print("OK  test_abrir_por_url_un_tramite_de_otra_area_da_403")


# ---------- Formularios propios de la seccional (N7) ----------

def test_el_trabajador_ve_los_globales_y_los_de_su_seccional():
    c = _admin()
    _crear_tipo(c, "Solo Rosario", "ROS1", default=AREA_ROS, seccional=SEC_ROSARIO)
    _crear_tipo(c, "Solo Córdoba", "CBA1", default=AREA_CBA, seccional=SEC_CORDOBA)

    codigos_ros = {t["codigo"] for t in _trabajador("20300000001")
                   .get("/api/tramites/tipos").json()["tipos"]}
    assert "F01" in codigos_ros, "el global lo ve"
    assert "ROS1" in codigos_ros, "el suyo también"
    assert "CBA1" not in codigos_ros, "el de otra delegación no"

    # Se afirma la PROPIEDAD (ningún formulario de seccional), no una lista
    # exacta: cualquier test que sume un formulario global rompería una
    # igualdad literal sin que haya nada mal.
    codigos_sin_sec = {t["codigo"] for t in _trabajador("20300000003")
                       .get("/api/tramites/tipos").json()["tipos"]}
    assert "F01" in codigos_sin_sec
    assert not ({"ROS1", "CBA1"} & codigos_sin_sec), "sin seccional, solo los globales"
    print("OK  test_el_trabajador_ve_los_globales_y_los_de_su_seccional")


def test_no_se_puede_enviar_un_formulario_de_otra_seccional():
    """Que la lista no lo ofrezca es una comodidad, no un control: el id
    del tipo viaja en el form y se puede escribir a mano."""
    tipo_cba = _tipo("CBA1")
    c = _trabajador("20300000001")                   # de Rosario
    with Session(db.engine) as s:
        campo = s.exec(select(db.CampoTramite).where(
            db.CampoTramite.tipo_tramite_id == tipo_cba)).first()
    r = c.post("/api/tramite", data={
        "tipo_tramite_id": str(tipo_cba), f"campo_{campo.id}": "me colé"})
    assert r.status_code == 404, r.status_code
    print("OK  test_no_se_puede_enviar_un_formulario_de_otra_seccional")


if __name__ == "__main__":
    test_sin_destino_por_defecto_no_se_guarda()
    test_el_mapa_manda_cada_seccional_a_su_area()
    test_la_seccional_sin_mapear_cae_al_default()
    test_el_trabajador_sin_seccional_cae_al_default()
    test_una_seccional_nueva_funciona_sin_tocar_el_formulario()
    test_el_tramite_queda_con_el_area_que_le_toco()
    test_cambiar_el_mapa_no_mueve_los_tramites_ya_presentados()
    test_cada_area_ve_solo_lo_suyo()
    test_dos_areas_de_la_MISMA_seccional_no_se_ven_entre_si()
    test_el_globo_cuenta_lo_mismo_que_la_bandeja()
    test_abrir_por_url_un_tramite_de_otra_area_da_403()
    test_el_trabajador_ve_los_globales_y_los_de_su_seccional()
    test_no_se_puede_enviar_un_formulario_de_otra_seccional()
    print("\nTodos los tests de ruteo pasaron.")
