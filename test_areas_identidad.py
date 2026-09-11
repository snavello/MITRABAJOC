"""Identidad del empleado del sindicato -- Fase 2 de SPRINT_AREAS_V2.md.

El operador del panel y el afiliado dejan de ser dos desconocidos: se
vinculan POR CUIL (decisión N1). El vínculo no se elige en ninguna pantalla
-- se resuelve solo -- así que lo que hay que probar es que se arme y se
deshaga en los dos sentidos y en cualquier orden.

Lo que más importa acá es lo que pasa en los bordes: el empleado que NO está
afiliado, el que se carga en el padrón después de tener usuario, la baja que
tiene que apagar la marca, y los dos usuarios con el mismo CUIL donde apagar
de más sería un bug silencioso.

Correr con: python -m pytest test_areas_identidad.py -q
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea, Trabajador
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Identidad", slug="uom-ident", color_base="#0f1b2d",
                    modulos_habilitados=list(MODULOS.keys()))
    fega = Sindicato(nombre="Fega Identidad", slug="fega-ident", color_base="#111111",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID, SID_OTRO = uom.id, fega.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(central); s.commit(); s.refresh(central)
    SEC = central.id
    sec_otro = Seccional(sindicato_id=SID_OTRO, nombre="Sede Central", ve_todas=True)
    s.add(sec_otro); s.commit(); s.refresh(sec_otro)

    legales = Area(sindicato_id=SID, seccional_id=SEC, nombre="Secretaría Legal")
    s.add(legales); s.commit(); s.refresh(legales)
    AREA = legales.id
    s.add(PermisoArea(area_id=AREA, seccion="trabajadores"))

    # AFILIADA: está en el padrón ANTES de que le den usuario.
    s.add(Trabajador(sindicato_id=SID, cuil="27300000001", nombre="Lucía Ferreyra",
                     seccional_id=SEC, registrado=False, activo=True))
    # El MISMO CUIL, pero empadronado en el OTRO sindicato: no tiene que
    # vincularse ni marcarse por lo que pase en la UOM.
    s.add(Trabajador(sindicato_id=SID_OTRO, cuil="20300000002", nombre="Homónimo Fega",
                     seccional_id=sec_otro.id, registrado=False, activo=True))

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", cuil="20111111110",
                           nombre="Marta", clave_hash=auth.hashear_clave("marta"),
                           debe_cambiar_clave=False, es_super_admin=True, seccional_id=SEC))
    s.commit()


def _marta():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": "20111111110", "clave": "marta"},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def _alta_usuario(c, cuil, nombre="Empleado"):
    return c.post("/admin/usuario", data={
        "usuario": cuil, "nombre": nombre, "clave_inicial": "x",
        "rol": "area", "area_id": str(AREA), "seccional_id": str(SEC),
    }, follow_redirects=False)


def _usuario(cuil):
    with Session(db.engine) as s:
        return s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == SID, UsuarioSindicato.cuil == cuil)).first()


def _usuario_activo(cuil):
    """El usuario ACTIVO con ese CUIL. Existe porque el sistema permite dos
    usuarios con el mismo CUIL (dos altas de la misma persona), así que
    buscar "el" usuario por CUIL a secas es ambiguo."""
    with Session(db.engine) as s:
        return s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == SID, UsuarioSindicato.cuil == cuil,
            UsuarioSindicato.activo == True)).first()


def _trabajador(cuil, sindicato_id=None):
    with Session(db.engine) as s:
        return s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == (sindicato_id or SID),
            Trabajador.cuil == cuil)).first()


# ---------- El vínculo se arma solo ----------

def test_el_empleado_que_ya_estaba_en_el_padron_queda_vinculado_y_marcado():
    c = _marta()
    r = _alta_usuario(c, "27300000001", "Lucía Ferreyra")
    assert r.status_code == 303
    u, t = _usuario("27300000001"), _trabajador("27300000001")
    assert u is not None and t is not None
    assert u.trabajador_id == t.id, "el vínculo se resuelve por CUIL, sin elegir nada"
    assert t.es_empleado_sindicato is True
    print("OK  test_el_empleado_que_ya_estaba_en_el_padron_queda_vinculado_y_marcado")


def test_el_empleado_que_no_esta_afiliado_se_crea_igual_sin_vinculo():
    """Trabajar en el gremio sin estar afiliado a él es un caso real, no un
    error: el usuario tiene que existir, simplemente sin vínculo."""
    c = _marta()
    r = _alta_usuario(c, "20400000004", "Externo Sin Padrón")
    assert r.status_code == 303
    u = _usuario("20400000004")
    assert u is not None and u.trabajador_id is None
    assert _trabajador("20400000004") is None, "no se le inventa una fila en el padrón"
    print("OK  test_el_empleado_que_no_esta_afiliado_se_crea_igual_sin_vinculo")


def test_el_orden_no_importa_si_primero_se_da_el_usuario():
    """El camino inverso: alguien tiene usuario del panel y RECIÉN DESPUÉS
    lo cargan en el padrón. Sin la sincronización desde el alta de
    trabajador, quedaría en el padrón sin marca y en silencio."""
    c = _marta()
    _alta_usuario(c, "27500000005", "Se Afilia Después")
    assert _usuario("27500000005").trabajador_id is None

    r = c.post("/admin/trabajador", data={
        "cuil": "27500000005", "nombre": "Se Afilia Después", "seccional_id": str(SEC),
    }, follow_redirects=False)
    assert r.status_code == 303
    t = _trabajador("27500000005")
    assert t is not None and t.es_empleado_sindicato is True
    assert _usuario("27500000005").trabajador_id == t.id
    print("OK  test_el_orden_no_importa_si_primero_se_da_el_usuario")


# ---------- El vínculo no cruza sindicatos ----------

def test_el_mismo_cuil_en_otro_gremio_no_se_vincula_ni_se_marca():
    """El mismo CUIL puede estar empadronado en varios sindicatos. Ser
    empleado de uno no dice nada sobre su afiliación al otro."""
    c = _marta()
    _alta_usuario(c, "20300000002", "Homónimo")
    u = _usuario("20300000002")
    assert u is not None and u.trabajador_id is None, "no hay fila suya en ESTE padrón"
    ajeno = _trabajador("20300000002", SID_OTRO)
    assert ajeno is not None and ajeno.es_empleado_sindicato is False, \
        "la marca del otro sindicato no se toca"
    print("OK  test_el_mismo_cuil_en_otro_gremio_no_se_vincula_ni_se_marca")


# ---------- El vínculo se deshace ----------

def test_la_baja_del_usuario_apaga_la_marca_del_padron():
    c = _marta()
    u = _usuario("27300000001")
    r = c.post("/admin/usuario/baja", data={"id": str(u.id)}, follow_redirects=False)
    assert r.status_code == 303
    t = _trabajador("27300000001")
    assert t.es_empleado_sindicato is False, "ya no trabaja en el sindicato"
    assert _usuario("27300000001").trabajador_id is None
    print("OK  test_la_baja_del_usuario_apaga_la_marca_del_padron")


def test_reactivarlo_vuelve_a_prender_la_marca():
    c = _marta()
    u = _usuario("27300000001")
    r = c.post("/admin/usuario/alta-logica", data={"id": str(u.id)}, follow_redirects=False)
    assert r.status_code == 303
    assert _trabajador("27300000001").es_empleado_sindicato is True
    assert _usuario("27300000001").trabajador_id is not None
    print("OK  test_reactivarlo_vuelve_a_prender_la_marca")


def test_con_dos_usuarios_del_mismo_cuil_la_baja_de_uno_no_apaga_la_marca():
    """El caso que un apagado ingenuo rompe: dos altas para la misma persona
    (pasa con un typo en el nombre, o un alta duplicada desde plataforma).
    Dar de baja a una no puede dejar sin marca a la otra, que sigue
    trabajando -- y el error sería silencioso."""
    with db.get_session() as s:
        gemelo = UsuarioSindicato(
            sindicato_id=SID, usuario="27300000001-bis", cuil="27300000001",
            nombre="Lucía (segunda alta)", clave_hash=auth.hashear_clave("x"),
            debe_cambiar_clave=False, area_id=AREA, seccional_id=SEC)
        s.add(gemelo); s.commit(); s.refresh(gemelo)
        gid = gemelo.id
    db.sincronizar_empleado(gid)
    assert _trabajador("27300000001").es_empleado_sindicato is True

    c = _marta()
    primero = [u for u in db.usuarios_del_sindicato(SID)
               if u["cuil"] == "27300000001" and u["id"] != gid][0]
    c.post("/admin/usuario/baja", data={"id": str(primero["id"])}, follow_redirects=False)
    assert _trabajador("27300000001").es_empleado_sindicato is True, \
        "el otro empleado sigue activo: la marca tiene que quedar"

    c.post("/admin/usuario/baja", data={"id": str(gid)}, follow_redirects=False)
    assert _trabajador("27300000001").es_empleado_sindicato is False, \
        "con los dos de baja sí se apaga"
    # Se deja como estaba para no afectar a los tests que siguen.
    c.post("/admin/usuario/alta-logica", data={"id": str(primero["id"])},
           follow_redirects=False)
    print("OK  test_con_dos_usuarios_del_mismo_cuil_la_baja_de_uno_no_apaga_la_marca")


# ---------- Lo que la pantalla muestra ----------

def test_el_panel_distingue_al_afiliado_del_externo():
    html = _marta().get("/admin").text
    assert "afiliado" in html and "no empadronado" in html
    assert "empleado del sindicato" in html, "la marca aparece en el padrón"
    print("OK  test_el_panel_distingue_al_afiliado_del_externo")


def test_usuarios_del_sindicato_informa_el_vinculo():
    """Se indexa por ID y no por CUIL a propósito: el test de más arriba
    deja DOS usuarios con el mismo CUIL, que es un caso que el sistema
    permite. Un dict por CUIL se quedaría con uno solo de los dos y este
    test pasaría o fallaría según cuál -- que es exactamente el tipo de
    test que miente."""
    filas = {u["id"]: u for u in db.usuarios_del_sindicato(SID)}
    afiliada = _usuario_activo("27300000001")
    externo = _usuario_activo("20400000004")
    assert filas[afiliada.id]["es_afiliado"] is True
    assert filas[externo.id]["es_afiliado"] is False
    print("OK  test_usuarios_del_sindicato_informa_el_vinculo")


def test_cuil_y_usuario_son_campos_distintos():
    """Hoy coinciden porque el alta pide el CUIT/CUIL como nombre de
    usuario. Se guardan separados para que habilitar el login por mail no
    borre la identidad de la persona -- este test fija esa separación."""
    u = _usuario("27300000001")
    assert u.cuil == "27300000001"
    with db.get_session() as s:
        fila = s.get(UsuarioSindicato, u.id)
        fila.usuario = "lucia@sindicato.org"   # como sería con login por mail
        s.add(fila); s.commit()
    db.sincronizar_empleado(u.id)
    assert _trabajador("27300000001").es_empleado_sindicato is True, \
        "cambiar el login no puede romper el vínculo"
    with db.get_session() as s:
        fila = s.get(UsuarioSindicato, u.id)
        fila.usuario = "27300000001"
        s.add(fila); s.commit()
    print("OK  test_cuil_y_usuario_son_campos_distintos")


if __name__ == "__main__":
    test_el_empleado_que_ya_estaba_en_el_padron_queda_vinculado_y_marcado()
    test_el_empleado_que_no_esta_afiliado_se_crea_igual_sin_vinculo()
    test_el_orden_no_importa_si_primero_se_da_el_usuario()
    test_el_mismo_cuil_en_otro_gremio_no_se_vincula_ni_se_marca()
    test_la_baja_del_usuario_apaga_la_marca_del_padron()
    test_reactivarlo_vuelve_a_prender_la_marca()
    test_con_dos_usuarios_del_mismo_cuil_la_baja_de_uno_no_apaga_la_marca()
    test_el_panel_distingue_al_afiliado_del_externo()
    test_usuarios_del_sindicato_informa_el_vinculo()
    test_cuil_y_usuario_son_campos_distintos()
    print("\nTodos los tests de identidad pasaron.")
