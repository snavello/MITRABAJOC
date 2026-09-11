"""Admin de Seccional -- Fase 1 de SPRINT_AREAS_V2.md.

El rol intermedio: "el admin grande en chiquito". Tiene EXACTAMENTE las
mismas secciones que el administrador general (eso es a propósito, no un
descuido) y lo que lo achica es el ALCANCE. Por eso la mayoría de los tests
de acá son de lo que NO puede hacer: en un sistema de permisos, equivocarse
para el lado de dar de más es el único error que importa.

Los cuatro caminos de escalada que se cierran:
  1. otorgar el rol general,
  2. tildar `ve_todas` sobre su propia seccional,
  3. tocar a un Super Admin,
  4. meterse con áreas o usuarios de otra seccional.

Correr con: python -m pytest test_areas_seccional.py -q
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Local", slug="uom-local", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    rosario = Seccional(sindicato_id=SID, nombre="Rosario")
    cordoba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(central); s.add(rosario); s.add(cordoba)
    s.commit()
    for x in (central, rosario, cordoba):
        s.refresh(x)
    SEC_CENTRAL, SEC_ROSARIO, SEC_CORDOBA = central.id, rosario.id, cordoba.id

    # Un área por seccional. Se llaman igual a propósito: son distintas
    # porque cuelgan de seccionales distintas, no por el nombre.
    legales_ros = Area(sindicato_id=SID, seccional_id=SEC_ROSARIO, nombre="Legales")
    legales_cba = Area(sindicato_id=SID, seccional_id=SEC_CORDOBA, nombre="Legales")
    s.add(legales_ros); s.add(legales_cba); s.commit()
    s.refresh(legales_ros); s.refresh(legales_cba)
    AREA_ROS, AREA_CBA = legales_ros.id, legales_cba.id
    for seccion in ("tramites_recibidos", "trabajadores"):
        s.add(PermisoArea(area_id=AREA_ROS, seccion=seccion))
        s.add(PermisoArea(area_id=AREA_CBA, seccion=seccion))

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Marta (general)",
                           clave_hash=auth.hashear_clave("marta"), debe_cambiar_clave=False,
                           es_super_admin=True, seccional_id=SEC_CENTRAL))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111111", nombre="Raúl (Rosario)",
                           clave_hash=auth.hashear_clave("raul"), debe_cambiar_clave=False,
                           es_admin_seccional=True, seccional_id=SEC_ROSARIO))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111112", nombre="Cielo (Córdoba)",
                           clave_hash=auth.hashear_clave("cielo"), debe_cambiar_clave=False,
                           area_id=AREA_CBA, seccional_id=SEC_CORDOBA))
    s.commit()

with db.get_session() as s:
    U_MARTA = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "20111111110")).first().id
    U_RAUL = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "20111111111")).first().id
    U_CIELO = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "20111111112")).first().id


def _cliente(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave},
               follow_redirects=False)
    assert r.status_code == 303, "el login de la fixture tiene que funcionar"
    return c


def _raul():
    return _cliente("20111111111", "raul")


def _marta():
    return _cliente("20111111110", "marta")


# ---------- Lo que SÍ es: el admin grande en chiquito ----------

def test_tiene_las_mismas_secciones_que_el_general():
    """No es un descuido: lo que lo achica es el alcance, no el catálogo.
    Tener dos catálogos sería tener dos cosas que mantener."""
    assert db.permisos_efectivos(U_RAUL) == db.permisos_efectivos(U_MARTA)
    print("OK  test_tiene_las_mismas_secciones_que_el_general")


def test_su_alcance_es_su_seccional_y_el_del_general_es_todo():
    assert db.alcance_seccional(U_MARTA) is None, "None = todas"
    assert db.alcance_seccional(U_RAUL) == {SEC_ROSARIO}
    print("OK  test_su_alcance_es_su_seccional_y_el_del_general_es_todo")


def test_entra_a_la_pantalla_de_areas_y_usuarios():
    c = _raul()
    html = c.get("/admin").text
    assert 'id="panel-administradores"' in html, "el admin local administra su seccional"
    print("OK  test_entra_a_la_pantalla_de_areas_y_usuarios")


def test_crea_areas_y_usuarios_en_su_seccional():
    c = _raul()
    r = c.post("/admin/area", data={"nombre": "Tesorería Rosario",
                                    "seccional_id": str(SEC_ROSARIO),
                                    "secciones": ["reportes"]}, follow_redirects=False)
    assert r.status_code == 303
    creada = [a for a in db.areas_del_sindicato(SID) if a["nombre"] == "Tesorería Rosario"]
    assert creada and creada[0]["seccional_id"] == SEC_ROSARIO

    r = c.post("/admin/usuario", data={
        "usuario": "20777777770", "nombre": "Nuevo Rosario", "clave_inicial": "x",
        "rol": "area", "area_id": str(AREA_ROS), "seccional_id": str(SEC_ROSARIO),
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        u = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20777777770")).first()
        assert u is not None and u.seccional_id == SEC_ROSARIO
    print("OK  test_crea_areas_y_usuarios_en_su_seccional")


# ---------- Los cuatro caminos de escalada ----------

def test_no_puede_otorgar_el_rol_general():
    """Con esto se fabricaría un usuario sin techo y el alcance local
    dejaría de significar nada."""
    c = _raul()
    r = c.post("/admin/usuario", data={
        "usuario": "20777777771", "nombre": "Colado", "clave_inicial": "x",
        "rol": "super", "seccional_id": str(SEC_ROSARIO),
    }, follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        assert s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20777777771")).first() is None
    print("OK  test_no_puede_otorgar_el_rol_general")


def test_no_puede_ascenderse_a_si_mismo():
    c = _raul()
    r = c.post("/admin/usuario/editar", data={
        "id": str(U_RAUL), "nombre": "Raúl", "rol": "super",
    }, follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        assert not s.get(UsuarioSindicato, U_RAUL).es_super_admin
    print("OK  test_no_puede_ascenderse_a_si_mismo")


def test_no_puede_tildar_ve_todas_en_su_seccional():
    """Sería darse alcance sobre todo el sindicato de un clic."""
    c = _raul()
    r = c.post("/admin/seccional", data={
        "id": str(SEC_ROSARIO), "nombre": "Rosario", "direccion": "", "ve_todas": "1",
    }, follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        assert not s.get(Seccional, SEC_ROSARIO).ve_todas
    print("OK  test_no_puede_tildar_ve_todas_en_su_seccional")


def test_puede_editar_el_nombre_de_su_seccional_sin_tocar_ve_todas():
    """El contrapeso del test anterior: lo que se bloquea es la escalada,
    no la administración normal."""
    c = _raul()
    r = c.post("/admin/seccional", data={
        "id": str(SEC_ROSARIO), "nombre": "Rosario Centro", "direccion": "Córdoba 1234",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sec = s.get(Seccional, SEC_ROSARIO)
        assert sec.nombre == "Rosario Centro" and not sec.ve_todas
        sec.nombre = "Rosario"
        s.add(sec); s.commit()
    print("OK  test_puede_editar_el_nombre_de_su_seccional_sin_tocar_ve_todas")


def test_no_puede_crear_ni_borrar_seccionales():
    """El mapa de delegaciones del sindicato no lo dibuja una delegación."""
    c = _raul()
    r = c.post("/admin/seccional", data={"nombre": "Inventada", "direccion": ""},
               follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/admin/seccional/borrar", data={"id": str(SEC_CORDOBA)},
               follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        assert s.exec(select(Seccional).where(Seccional.nombre == "Inventada")).first() is None
        assert s.get(Seccional, SEC_CORDOBA) is not None
    print("OK  test_no_puede_crear_ni_borrar_seccionales")


def test_no_puede_tocar_a_un_super_admin():
    """Si pudiera editarlo, le cambiaría el rol al de arriba y se quedaría
    con el sindicato."""
    c = _raul()
    for ruta, datos in [
        ("/admin/usuario/editar", {"id": str(U_MARTA), "nombre": "Hackeada", "rol": "area"}),
        ("/admin/usuario/baja", {"id": str(U_MARTA)}),
    ]:
        r = c.post(ruta, data=datos, follow_redirects=False)
        assert r.status_code == 403, f"{ruta} debería dar 403"
    with Session(db.engine) as s:
        marta = s.get(UsuarioSindicato, U_MARTA)
        assert marta.es_super_admin and marta.activo and marta.nombre != "Hackeada"
    print("OK  test_no_puede_tocar_a_un_super_admin")


def test_no_puede_tocar_areas_de_otra_seccional():
    c = _raul()
    r = c.post("/admin/area", data={"id": str(AREA_CBA), "nombre": "Robada",
                                    "secciones": []}, follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/admin/area/estado", data={"id": str(AREA_CBA), "activo": ""},
               follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        a = s.get(Area, AREA_CBA)
        assert a.nombre == "Legales" and a.activo
    print("OK  test_no_puede_tocar_areas_de_otra_seccional")


def test_no_puede_crear_un_area_en_otra_seccional():
    c = _raul()
    r = c.post("/admin/area", data={"nombre": "Sucursal Ajena",
                                    "seccional_id": str(SEC_CORDOBA),
                                    "secciones": []}, follow_redirects=False)
    assert r.status_code == 403
    assert not [a for a in db.areas_del_sindicato(SID) if a["nombre"] == "Sucursal Ajena"]
    print("OK  test_no_puede_crear_un_area_en_otra_seccional")


def test_no_puede_tocar_usuarios_de_otra_seccional():
    c = _raul()
    r = c.post("/admin/usuario/editar", data={
        "id": str(U_CIELO), "nombre": "Intervenida", "rol": "area",
        "area_id": str(AREA_CBA), "seccional_id": str(SEC_CORDOBA),
    }, follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        assert s.get(UsuarioSindicato, U_CIELO).nombre != "Intervenida"
    print("OK  test_no_puede_tocar_usuarios_de_otra_seccional")


def test_no_puede_crear_usuarios_en_otra_seccional():
    c = _raul()
    r = c.post("/admin/usuario", data={
        "usuario": "20777777772", "nombre": "Infiltrado", "clave_inicial": "x",
        "rol": "area", "area_id": str(AREA_CBA), "seccional_id": str(SEC_CORDOBA),
    }, follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        assert s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20777777772")).first() is None
    print("OK  test_no_puede_crear_usuarios_en_otra_seccional")


# ---------- Coherencia área/seccional ----------

def test_area_y_seccional_del_usuario_tienen_que_coincidir():
    """"Legales de Rosario" con alcance Córdoba es un usuario que nadie sabe
    qué ve. El general tampoco puede armarlo."""
    c = _marta()
    r = c.post("/admin/usuario", data={
        "usuario": "20777777773", "nombre": "Mezclado", "clave_inicial": "x",
        "rol": "area", "area_id": str(AREA_ROS), "seccional_id": str(SEC_CORDOBA),
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "err=areaajena" in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20777777773")).first() is None
    print("OK  test_area_y_seccional_del_usuario_tienen_que_coincidir")


def test_un_admin_de_seccional_sin_seccional_se_rechaza():
    c = _marta()
    r = c.post("/admin/usuario", data={
        "usuario": "20777777774", "nombre": "Sin Alcance", "clave_inicial": "x",
        "rol": "seccional", "seccional_id": "",
    }, follow_redirects=False)
    assert "err=sinseccional" in r.headers.get("location", "")
    print("OK  test_un_admin_de_seccional_sin_seccional_se_rechaza")


# ---------- La fuga de datos ----------

def test_el_panel_del_admin_local_no_trae_las_otras_seccionales():
    """El recorte vive en la CONSULTA, no en la plantilla: si estuviera en
    el HTML, las áreas y los CUIT de las otras delegaciones viajarían igual
    y se leen con Ver Código Fuente."""
    areas_raul = db.areas_del_sindicato(SID, db.alcance_seccional(U_RAUL))
    assert all(a["seccional_id"] == SEC_ROSARIO for a in areas_raul), areas_raul
    assert AREA_CBA not in [a["id"] for a in areas_raul]

    usuarios_raul = db.usuarios_del_sindicato(SID, db.alcance_seccional(U_RAUL))
    ids = [u["id"] for u in usuarios_raul]
    assert U_RAUL in ids
    assert U_CIELO not in ids, "un usuario de Córdoba no es asunto suyo"

    html = _raul().get("/admin").text
    assert "20111111112" not in html, "se filtró el CUIT de la usuaria de Córdoba"
    print("OK  test_el_panel_del_admin_local_no_trae_las_otras_seccionales")


def test_el_general_si_ve_todo():
    """El contrapeso: que el recorte venga del alcance y no de un bug."""
    areas = db.areas_del_sindicato(SID, db.alcance_seccional(U_MARTA))
    assert {AREA_ROS, AREA_CBA} <= {a["id"] for a in areas}
    html = _marta().get("/admin").text
    assert "20111111112" in html
    print("OK  test_el_general_si_ve_todo")


if __name__ == "__main__":
    test_tiene_las_mismas_secciones_que_el_general()
    test_su_alcance_es_su_seccional_y_el_del_general_es_todo()
    test_entra_a_la_pantalla_de_areas_y_usuarios()
    test_crea_areas_y_usuarios_en_su_seccional()
    test_no_puede_otorgar_el_rol_general()
    test_no_puede_ascenderse_a_si_mismo()
    test_no_puede_tildar_ve_todas_en_su_seccional()
    test_puede_editar_el_nombre_de_su_seccional_sin_tocar_ve_todas()
    test_no_puede_crear_ni_borrar_seccionales()
    test_no_puede_tocar_a_un_super_admin()
    test_no_puede_tocar_areas_de_otra_seccional()
    test_no_puede_crear_un_area_en_otra_seccional()
    test_no_puede_tocar_usuarios_de_otra_seccional()
    test_no_puede_crear_usuarios_en_otra_seccional()
    test_area_y_seccional_del_usuario_tienen_que_coincidir()
    test_un_admin_de_seccional_sin_seccional_se_rechaza()
    test_el_panel_del_admin_local_no_trae_las_otras_seccionales()
    test_el_general_si_ve_todo()
    print("\nTodos los tests del Admin de Seccional pasaron.")
