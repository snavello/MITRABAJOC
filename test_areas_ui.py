"""CRUD de Áreas y Usuarios y armado del panel -- Fase 3 de SPRINT_AREAS.md.

El test que más importa acá es el de FUGA DE DATOS: /admin arma UNA página
con todos los paneles adentro, así que esconder pestañas en el cliente no
es ningún control -- los datos viajarían igual en el HTML y se leen con
Ver Código Fuente. La ruta tiene que no pasárselos a la plantilla.

Correr con: python -m pytest test_areas_ui.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea, PermisoUsuario
import main
from permisos import SECCIONES
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM UI", slug="uom-ui", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    # Sindicato vecino: sirve para probar que un id ajeno mandado a mano no entra.
    otro = Sindicato(nombre="Otro UI", slug="otro-ui", color_base="#111111",
                     modulos_habilitados=["recibos"])
    s.add(sind); s.add(otro)
    s.commit(); s.refresh(sind); s.refresh(otro)
    SID, SID_OTRO = sind.id, otro.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    ajena = Seccional(sindicato_id=SID_OTRO, nombre="Seccional Ajena")
    s.add(central); s.add(ajena)
    s.commit(); s.refresh(central); s.refresh(ajena)
    SEC, SEC_AJENA = central.id, ajena.id

    area_ajena = Area(sindicato_id=SID_OTRO, seccional_id=SEC_AJENA, nombre="Área Ajena")
    s.add(area_ajena); s.commit(); s.refresh(area_ajena)
    AREA_AJENA = area_ajena.id

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Jefa",
                           clave_hash=auth.hashear_clave("jefa"), debe_cambiar_clave=False,
                           es_super_admin=True, seccional_id=SEC))
    s.commit()


def _sa():
    """Cliente logueado como Super Admin."""
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": "20111111110", "clave": "jefa"},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def _crear_area(c, nombre, permisos, seccional=None):
    """El alta de área pide seccional desde la Fase 1: el área pertenece a
    una (decisión N2) y sin eso no se guarda."""
    r = c.post("/admin/area", data={"nombre": nombre, "secciones": permisos,
                                    "seccional_id": str(seccional or SEC)},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    with Session(db.engine) as s:
        return s.exec(select(Area).where(Area.sindicato_id == SID,
                                         Area.nombre == nombre)).first().id


# ---------- CRUD de áreas ----------

def test_alta_de_area_con_permisos():
    c = _sa()
    aid = _crear_area(c, "Secretaría Legal", ["tramites_recibidos", "trabajadores"])
    area = [a for a in db.areas_del_sindicato(SID) if a["id"] == aid][0]
    assert area["nombre"] == "Secretaría Legal"
    assert area["activo"] is True
    assert area["permisos"] == ["trabajadores", "tramites_recibidos"]
    print("OK  test_alta_de_area_con_permisos")


def test_edicion_reemplaza_los_permisos_no_los_suma():
    c = _sa()
    aid = _crear_area(c, "Tesorería", ["reportes", "cotizantes"])
    r = c.post("/admin/area", data={"id": str(aid), "nombre": "Tesorería",
                                    "secciones": ["reportes"],
                                    "seccional_id": str(SEC)}, follow_redirects=False)
    assert r.status_code == 303
    area = [a for a in db.areas_del_sindicato(SID) if a["id"] == aid][0]
    assert area["permisos"] == ["reportes"], "editar reemplaza, no acumula"
    print("OK  test_edicion_reemplaza_los_permisos_no_los_suma")


def test_no_se_guarda_una_seccion_inventada():
    """Defensivo, mismo criterio que set_modulos_sindicato: no se persiste
    basura que después haya que filtrar en cada lectura."""
    c = _sa()
    aid = _crear_area(c, "Área Trucha", ["reportes", "seccion_que_no_existe"])
    area = [a for a in db.areas_del_sindicato(SID) if a["id"] == aid][0]
    assert area["permisos"] == ["reportes"]
    print("OK  test_no_se_guarda_una_seccion_inventada")


def test_no_se_guarda_una_seccion_de_modulo_no_contratado():
    """El sindicato vecino no tiene el módulo de empleadores: aunque el POST
    llegue con esa sección, no se guarda."""
    with db.get_session() as s:
        u = UsuarioSindicato(sindicato_id=SID_OTRO, usuario="20222222220", nombre="Jefe Otro",
                             clave_hash=auth.hashear_clave("otro"), debe_cambiar_clave=False,
                             es_super_admin=True)
        s.add(u); s.commit()
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": "20222222220", "clave": "otro"},
           follow_redirects=False)
    # SEC_AJENA y no SEC: la seccional tiene que ser de SU sindicato. Con la
    # del sindicato de al lado el alta se rechaza -- que está bien, pero no
    # es lo que este test quiere probar.
    r = c.post("/admin/area", data={"nombre": "Legales Otro",
                                    "secciones": ["reportes", "emp_empresas"],
                                    "seccional_id": str(SEC_AJENA)},
               follow_redirects=False)
    assert r.status_code == 303
    area = [a for a in db.areas_del_sindicato(SID_OTRO) if a["nombre"] == "Legales Otro"][0]
    assert area["permisos"] == ["reportes"], "emp_empresas no está contratado"
    print("OK  test_no_se_guarda_una_seccion_de_modulo_no_contratado")


def test_desactivar_y_reactivar_area():
    c = _sa()
    aid = _crear_area(c, "Área Temporal", ["noticias"])
    c.post("/admin/area/estado", data={"id": str(aid), "activo": "no"}, follow_redirects=False)
    assert [a for a in db.areas_del_sindicato(SID) if a["id"] == aid][0]["activo"] is False
    c.post("/admin/area/estado", data={"id": str(aid), "activo": "si"}, follow_redirects=False)
    assert [a for a in db.areas_del_sindicato(SID) if a["id"] == aid][0]["activo"] is True
    print("OK  test_desactivar_y_reactivar_area")


def test_no_se_puede_tocar_un_area_de_otro_sindicato():
    c = _sa()
    r = c.post("/admin/area", data={"id": str(AREA_AJENA), "nombre": "Robada",
                                    "secciones": ["reportes"],
                                    "seccional_id": str(SEC)}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        assert s.get(Area, AREA_AJENA).nombre == "Área Ajena", "no se tocó"
    print("OK  test_no_se_puede_tocar_un_area_de_otro_sindicato")


# ---------- Alta y edición de usuarios ----------

def test_alta_de_usuario_de_area_con_ajustes_individuales():
    c = _sa()
    aid = _crear_area(c, "Legales Dos", ["reportes", "formulas", "conceptos"])
    r = c.post("/admin/usuario", data={
        "usuario": "20333333330", "nombre": "Gabriel", "clave_inicial": "gab",
        "rol": "area", "area_id": str(aid), "seccional_id": str(SEC),
        "agregar": ["noticias"], "bloquear": ["formulas"],
    }, follow_redirects=False)
    assert r.status_code == 303, r.text
    u = [x for x in db.usuarios_del_sindicato(SID) if x["usuario"] == "20333333330"][0]
    assert u["es_super_admin"] is False
    assert u["area_id"] == aid and u["seccional_id"] == SEC
    assert u["agregados"] == ["noticias"] and u["bloqueados"] == ["formulas"]
    # (área) reportes+formulas+conceptos + noticias - formulas
    assert u["efectivos"] == ["conceptos", "noticias", "reportes"]
    print("OK  test_alta_de_usuario_de_area_con_ajustes_individuales")


def test_usuario_de_area_sin_area_se_rechaza():
    c = _sa()
    r = c.post("/admin/usuario", data={
        "usuario": "20333333331", "nombre": "Sin Área", "clave_inicial": "x",
        "rol": "area", "area_id": "", "seccional_id": str(SEC),
    }, follow_redirects=False)
    assert "err=sinarea" in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20333333331")).first() is None
    print("OK  test_usuario_de_area_sin_area_se_rechaza")


def test_area_y_seccional_de_otro_sindicato_no_entran():
    """Los <select> viajan como campos del form: un id ajeno se puede mandar
    a mano. Cae en el mismo rechazo que si no hubiera venido nada."""
    c = _sa()
    r = c.post("/admin/usuario", data={
        "usuario": "20333333332", "nombre": "Colado", "clave_inicial": "x",
        "rol": "area", "area_id": str(AREA_AJENA), "seccional_id": str(SEC_AJENA),
    }, follow_redirects=False)
    assert "err=sinarea" in r.headers.get("location", ""), "el área ajena se descarta"
    with Session(db.engine) as s:
        assert s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20333333332")).first() is None
    print("OK  test_area_y_seccional_de_otro_sindicato_no_entran")


def test_alta_de_super_admin_ignora_area_y_permisos():
    c = _sa()
    aid = _crear_area(c, "Área Irrelevante", ["reportes"])
    r = c.post("/admin/usuario", data={
        "usuario": "20333333333", "nombre": "Segunda Jefa", "clave_inicial": "x",
        "rol": "super", "area_id": str(aid), "seccional_id": str(SEC),
        "agregar": ["noticias"],
    }, follow_redirects=False)
    assert r.status_code == 303
    u = [x for x in db.usuarios_del_sindicato(SID) if x["usuario"] == "20333333333"][0]
    assert u["es_super_admin"] is True
    assert u["area_id"] is None, "un Super Admin no cuelga de un área"
    assert u["agregados"] == [] and u["bloqueados"] == []
    assert set(u["efectivos"]) == set(SECCIONES.keys())
    print("OK  test_alta_de_super_admin_ignora_area_y_permisos")


def test_editar_usuario_cambia_rol_area_y_permisos():
    c = _sa()
    aid = _crear_area(c, "Área Editable", ["noticias", "beneficios"])
    c.post("/admin/usuario", data={
        "usuario": "20333333334", "nombre": "Mutante", "clave_inicial": "x",
        "rol": "area", "area_id": str(aid), "seccional_id": str(SEC),
    }, follow_redirects=False)
    uid = [x for x in db.usuarios_del_sindicato(SID) if x["usuario"] == "20333333334"][0]["id"]
    r = c.post("/admin/usuario/editar", data={
        "id": str(uid), "nombre": "Mutante Editado", "rol": "area",
        "area_id": str(aid), "seccional_id": str(SEC), "bloquear": ["beneficios"],
    }, follow_redirects=False)
    assert r.status_code == 303
    u = [x for x in db.usuarios_del_sindicato(SID) if x["id"] == uid][0]
    assert u["nombre"] == "Mutante Editado"
    assert u["efectivos"] == ["noticias"]
    print("OK  test_editar_usuario_cambia_rol_area_y_permisos")


def test_no_se_puede_degradar_al_ultimo_super_admin():
    """Mismo motivo que no se puede desactivarlo: el sindicato quedaría sin
    nadie que pueda administrarlo."""
    with db.get_session() as s:
        for u in s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == SID,
                UsuarioSindicato.es_super_admin == True)).all():
            if u.usuario != "20111111110":
                u.es_super_admin = False
                u.area_id = None
                s.add(u)
        s.commit()
        jefa_id = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20111111110")).first().id
    assert db.contar_super_admins(SID) == 1, "queda una sola Super Admin"
    c = _sa()
    aid = _crear_area(c, "Área Degradadora", ["noticias"])
    r = c.post("/admin/usuario/editar", data={
        "id": str(jefa_id), "nombre": "Jefa", "rol": "area",
        "area_id": str(aid), "seccional_id": str(SEC),
    }, follow_redirects=False)
    assert "err=ultimoadmin" in r.headers.get("location", "")
    assert db.es_super_admin(jefa_id), "sigue siendo Super Admin"
    print("OK  test_no_se_puede_degradar_al_ultimo_super_admin")


# ---------- Seccionales ----------

def test_ve_todas_se_guarda_y_se_edita():
    c = _sa()
    c.post("/admin/seccional", data={"nombre": "Regional Norte", "direccion": "",
                                     "ve_todas": "si"}, follow_redirects=False)
    sec = [x for x in db.seccionales_del_sindicato(SID) if x["nombre"] == "Regional Norte"][0]
    assert sec["ve_todas"] is True
    c.post("/admin/seccional", data={"id": str(sec["id"]), "nombre": "Regional Norte",
                                     "direccion": ""}, follow_redirects=False)
    sec = [x for x in db.seccionales_del_sindicato(SID) if x["id"] == sec["id"]][0]
    assert sec["ve_todas"] is False, "sin el check destildado vuelve a alcance propio"
    print("OK  test_ve_todas_se_guarda_y_se_edita")


# ---------- El panel armado: fuga de datos ----------

def _panel_de(cuil, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": cuil, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303
    return c.get("/admin").text


def test_el_panel_no_manda_los_datos_de_secciones_sin_permiso():
    """El test central de la fase. Si esto falla, el permiso es cosmético:
    los datos se leen con Ver Código Fuente."""
    c = _sa()
    aid = _crear_area(c, "Área Acotada", ["trabajadores"])
    c.post("/admin/usuario", data={
        "usuario": "20555555550", "nombre": "Acotado", "clave_inicial": "acot",
        "rol": "area", "area_id": str(aid), "seccional_id": str(SEC),
    }, follow_redirects=False)

    html = _panel_de("20555555550", "acot")
    for marca in ['id="panel-formulas"', 'id="panel-conceptos"', 'id="panel-reportes"',
                  'id="panel-noticias"', 'id="panel-beneficios"', 'id="panel-seccionales"',
                  'id="panel-empleadores"', 'id="panel-administradores"', 'id="form-usuario"',
                  'id="form-area"', 'PERMISOS_POR_AREA', 'id="panel-tramites"']:
        assert marca not in html, f"se filtró {marca} a un usuario sin ese permiso"
    assert 'id="panel-trabajadores"' in html, "sí tiene que ver lo suyo"
    print("OK  test_el_panel_no_manda_los_datos_de_secciones_sin_permiso")


def test_el_super_admin_ve_todos_los_paneles():
    html = _panel_de("20111111110", "jefa")
    for marca in ['id="panel-formulas"', 'id="panel-conceptos"', 'id="panel-reportes"',
                  'id="panel-noticias"', 'id="panel-seccionales"',
                  # El id del panel sigue siendo "administradores" aunque la
                  # pestaña ahora se llame "Áreas y Usuarios": renombrarlo
                  # arrastraría la portada, sus tests y la documentación
                  # generada, sin ganar nada funcional.
                  'id="panel-administradores"',
                  'id="panel-trabajadores"', 'id="panel-empleadores"']:
        assert marca in html, f"al Super Admin le falta {marca}"
    print("OK  test_el_super_admin_ve_todos_los_paneles")


def test_responder_tramites_no_muestra_el_constructor_de_formularios():
    """La apertura de Trámites en dos, del lado de la UI: el que responde no
    ve la sub-pestaña donde se elige el área receptora."""
    c = _sa()
    aid = _crear_area(c, "Área Solo Responder", ["tramites_recibidos"])
    c.post("/admin/usuario", data={
        "usuario": "20555555551", "nombre": "Solo Responde", "clave_inicial": "resp",
        "rol": "area", "area_id": str(aid), "seccional_id": str(SEC),
    }, follow_redirects=False)
    html = _panel_de("20555555551", "resp")
    assert 'id="tramite-sub-recibidos"' in html
    assert 'id="tramite-sub-tipos"' not in html, "no puede ver el constructor"
    assert 'id="form-tramite-tipo"' not in html
    print("OK  test_responder_tramites_no_muestra_el_constructor_de_formularios")


def test_el_javascript_de_areas_solo_se_emite_para_el_super_admin():
    """Un init de <script> sobre un panel que no se renderiza rompe TODO el
    script de ahí para abajo (ya pasó con el semáforo del trabajador)."""
    html = _panel_de("20555555550", "acot")
    assert "PERMISOS_POR_AREA" not in html
    assert "function pintarHerencia" not in html
    assert "PERMISOS_POR_AREA" in _panel_de("20111111110", "jefa")
    print("OK  test_el_javascript_de_areas_solo_se_emite_para_el_super_admin")


def test_los_otros_bloques_de_javascript_tambien_estan_guardados():
    """El guard de Áreas no alcanza: al gatear los paneles por permiso,
    TODO bloque de <script> que hace init sobre un panel gateado puede
    quedar apuntando a la nada. Ya venían guardados por MÓDULO; ahora el
    panel puede faltar también por PERMISO, así que cada guard tuvo que
    mirar las dos cosas. Este test cubre los tres que quedaban.

    El sindicato de la fixture tiene TODOS los módulos, así que si estos
    bloques aparecen es por el permiso y no por otra cosa."""
    html = _panel_de("20555555551", "resp")   # solo tramites_recibidos
    assert "getElementById('ap-drop')" not in html, "init de Aprendizaje sin su panel"
    assert "conv-nombre" not in html, "JS de Convenio sin su panel"
    assert "actualizarBadgeTramitesEmpresaNuevos" not in html, \
        "polling de trámites de empresa sin su panel"
    # El que SÍ le corresponde tiene que estar -- si no, el test pasaría
    # incluso con todo el script borrado.
    assert "actualizarBadgeTramitesNuevos" in html, "le falta lo suyo"
    # Y el script tiene que llegar entero hasta el final: si un init sobre
    # null hubiera cortado la ejecución, el cierre no estaría.
    assert html.rstrip().endswith("</html>")
    print("OK  test_los_otros_bloques_de_javascript_tambien_estan_guardados")


if __name__ == "__main__":
    test_alta_de_area_con_permisos()
    test_edicion_reemplaza_los_permisos_no_los_suma()
    test_no_se_guarda_una_seccion_inventada()
    test_no_se_guarda_una_seccion_de_modulo_no_contratado()
    test_desactivar_y_reactivar_area()
    test_no_se_puede_tocar_un_area_de_otro_sindicato()
    test_alta_de_usuario_de_area_con_ajustes_individuales()
    test_usuario_de_area_sin_area_se_rechaza()
    test_area_y_seccional_de_otro_sindicato_no_entran()
    test_alta_de_super_admin_ignora_area_y_permisos()
    test_editar_usuario_cambia_rol_area_y_permisos()
    test_no_se_puede_degradar_al_ultimo_super_admin()
    test_ve_todas_se_guarda_y_se_edita()
    test_el_panel_no_manda_los_datos_de_secciones_sin_permiso()
    test_el_super_admin_ve_todos_los_paneles()
    test_responder_tramites_no_muestra_el_constructor_de_formularios()
    test_el_javascript_de_areas_solo_se_emite_para_el_super_admin()
    test_los_otros_bloques_de_javascript_tambien_estan_guardados()
    print("\nTodos los tests de la UI de áreas pasaron.")
