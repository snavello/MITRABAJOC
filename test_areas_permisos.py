"""Áreas y permisos del sindicato -- Fase 1 de SPRINT_AREAS.md.

Cubre el cálculo de permisos efectivos (herencia del área, agregado y
bloqueo individual, filtro por módulos del sindicato) y el alcance por
seccional. Todavía NO hay gateo de rutas: eso es la Fase 2.

Lo que más importa acá son los casos donde el sistema tiene que FALLAR
CERRADO: usuario dado de baja, área desactivada, seccional faltante,
módulo apagado por plataforma. En un sistema de permisos, equivocarse para
el lado de dar de más es el único error que importa.

Correr con: python -m pytest test_areas_permisos.py -q
(vía pytest, para que conftest.py fuerce SQLite y no tome el Postgres
local de .env -- ver conftest.py)
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                PermisoUsuario)
from permisos import (SECCIONES, SECCION_SUPER_ADMIN, secciones_de_modulos,
                      agrupar_para_ui, calcular_efectivos)
from modulos import MODULOS
from sqlmodel import select

db.crear_tablas()

# Sindicato A: todo el catálogo. Sindicato B: solo recibos y noticias --
# sirve para probar que los módulos filtran permisos ya asignados.
with db.get_session() as s:
    completo = Sindicato(nombre="UOM Areas", slug="uom-areas", color_base="#0f1b2d",
                         modulos_habilitados=list(MODULOS.keys()))
    parcial = Sindicato(nombre="Fega Areas", slug="fega-areas", color_base="#0d2027",
                        modulos_habilitados=["recibos", "noticias"])
    s.add(completo); s.add(parcial)
    s.commit(); s.refresh(completo); s.refresh(parcial)
    SID_A, SID_B = completo.id, parcial.id

    central = Seccional(sindicato_id=SID_A, nombre="Sede Central", ve_todas=True)
    rosario = Seccional(sindicato_id=SID_A, nombre="Rosario")
    cordoba = Seccional(sindicato_id=SID_A, nombre="Córdoba")
    s.add(central); s.add(rosario); s.add(cordoba)
    s.commit(); s.refresh(central); s.refresh(rosario); s.refresh(cordoba)
    SEC_CENTRAL, SEC_ROSARIO, SEC_CORDOBA = central.id, rosario.id, cordoba.id

    # Seccional del OTRO sindicato: la necesitan tanto el área de B como el
    # usuario al que después se le asigna a mano para probar que una
    # seccional ajena no habilita nada.
    sec_ajena = Seccional(sindicato_id=SID_B, nombre="Seccional Fega", ve_todas=True)
    s.add(sec_ajena); s.commit(); s.refresh(sec_ajena)
    SEC_B = sec_ajena.id

    # Desde la Fase 1 el área pertenece a una seccional (decisión N2), así
    # que la fixture tiene que decir a cuál: "Legales" de Sede Central y
    # "Legales" de Rosario son áreas distintas.
    legales = Area(sindicato_id=SID_A, seccional_id=SEC_CENTRAL, nombre="Secretaría Legal")
    tesoreria = Area(sindicato_id=SID_A, seccional_id=SEC_CENTRAL, nombre="Tesorería")
    disuelta = Area(sindicato_id=SID_A, seccional_id=SEC_CENTRAL, nombre="Área Vieja", activo=False)
    legales_b = Area(sindicato_id=SID_B, seccional_id=SEC_B, nombre="Legales Fega")
    s.add(legales); s.add(tesoreria); s.add(disuelta); s.add(legales_b)
    s.commit()
    s.refresh(legales); s.refresh(tesoreria); s.refresh(disuelta); s.refresh(legales_b)
    AREA_LEGALES, AREA_TESORERIA = legales.id, tesoreria.id
    AREA_DISUELTA, AREA_LEGALES_B = disuelta.id, legales_b.id

    # Legales: responde trámites y notifica, pero NO diseña formularios.
    for seccion in ("tramites_recibidos", "notificaciones", "trabajadores"):
        s.add(PermisoArea(area_id=AREA_LEGALES, seccion=seccion))
    s.add(PermisoArea(area_id=AREA_TESORERIA, seccion="reportes"))
    s.add(PermisoArea(area_id=AREA_DISUELTA, seccion="reportes"))
    # En el sindicato B el área tiene permisos de módulos que NO contrató.
    for seccion in ("reportes", "tramites_recibidos", "emp_empresas"):
        s.add(PermisoArea(area_id=AREA_LEGALES_B, seccion=seccion))

    def _usuario(sid, cuil, nombre, **kw):
        u = UsuarioSindicato(sindicato_id=sid, usuario=cuil, nombre=nombre,
                             clave_hash=auth.hashear_clave("x"),
                             debe_cambiar_clave=False, **kw)
        s.add(u)
        return u

    jefe = _usuario(SID_A, "20111111110", "Jefa", es_super_admin=True,
                    seccional_id=SEC_CENTRAL)
    gabriel = _usuario(SID_A, "20111111111", "Gabriel Chávez",
                       area_id=AREA_LEGALES, seccional_id=SEC_ROSARIO)
    central_legales = _usuario(SID_A, "20111111112", "Legales Central",
                               area_id=AREA_LEGALES, seccional_id=SEC_CENTRAL)
    baja = _usuario(SID_A, "20111111113", "Dado de baja", activo=False,
                    area_id=AREA_LEGALES, seccional_id=SEC_ROSARIO)
    huerfano = _usuario(SID_A, "20111111114", "Sin área ni seccional")
    zombi = _usuario(SID_A, "20111111115", "De área desactivada",
                     area_id=AREA_DISUELTA, seccional_id=SEC_CORDOBA)
    ajeno = _usuario(SID_A, "20111111116", "Seccional de otro sindicato",
                     area_id=AREA_LEGALES)
    fega = _usuario(SID_B, "20222222220", "Legales Fega",
                    area_id=AREA_LEGALES_B, seccional_id=SEC_ROSARIO)
    s.commit()
    for u in (jefe, gabriel, central_legales, baja, huerfano, zombi, ajeno, fega):
        s.refresh(u)
    U_JEFE, U_GABRIEL, U_CENTRAL = jefe.id, gabriel.id, central_legales.id
    U_BAJA, U_HUERFANO, U_ZOMBI = baja.id, huerfano.id, zombi.id
    U_AJENO, U_FEGA = ajeno.id, fega.id

    # Seccional de OTRO sindicato asignada a mano: no debería habilitar nada.
    u = s.get(UsuarioSindicato, U_AJENO)
    u.seccional_id = SEC_B
    s.add(u); s.commit()


# ---------- Catálogo ----------

def test_catalogo_coherente_con_modulos():
    """Toda sección apunta a un módulo real, o a ninguno."""
    for seccion, (etiqueta, modulo, grupo) in SECCIONES.items():
        assert etiqueta, f"{seccion} sin etiqueta"
        assert grupo, f"{seccion} sin grupo"
        assert modulo == "" or modulo in MODULOS, f"{seccion} apunta a módulo inexistente: {modulo}"
    print("OK  test_catalogo_coherente_con_modulos")


def test_seccion_de_super_admin_no_es_asignable():
    """areas_usuarios no puede estar en SECCIONES: si estuviera, aparecería
    como un check más y un usuario de área podría recibir la llave de la
    gestión de usuarios."""
    assert SECCION_SUPER_ADMIN not in SECCIONES
    print("OK  test_seccion_de_super_admin_no_es_asignable")


def test_secciones_de_modulos_filtra():
    todas = secciones_de_modulos(list(MODULOS.keys()))
    assert set(todas) == set(SECCIONES.keys())

    pocas = secciones_de_modulos(["noticias"])
    assert "noticias" in pocas
    assert "reportes" not in pocas
    # Las que no dependen de módulo se ofrecen siempre.
    assert "trabajadores" in pocas and "seccionales" in pocas

    # Sin ningún módulo quedan solo las independientes.
    assert set(secciones_de_modulos([])) == {"trabajadores", "seccionales"}
    print("OK  test_secciones_de_modulos_filtra")


def test_tramites_se_puede_dar_sin_crear_formularios():
    """El caso que motivó abrir Trámites en dos: responder sin poder
    diseñar el formulario (donde se elige el área receptora)."""
    assert "tramites_recibidos" in SECCIONES and "tramites_formularios" in SECCIONES
    efectivos = calcular_efectivos(["tramites_recibidos"], [], [], ["tramites"])
    assert efectivos == {"tramites_recibidos"}
    assert "tramites_formularios" not in efectivos
    print("OK  test_tramites_se_puede_dar_sin_crear_formularios")


def test_agrupar_para_ui_no_devuelve_grupos_vacios():
    grupos = agrupar_para_ui(secciones_de_modulos(["noticias"]))
    nombres = [g for g, _ in grupos]
    assert "Recibos" not in nombres, "un grupo sin secciones disponibles no se muestra"
    assert "Comunicación" in nombres and "Padrón" in nombres
    for _, items in grupos:
        assert items, "ningún grupo puede venir vacío"
    print("OK  test_agrupar_para_ui_no_devuelve_grupos_vacios")


# ---------- Cálculo puro ----------

def test_bloqueo_le_gana_al_area():
    efectivos = calcular_efectivos(
        del_area=["reportes", "notificaciones"], agregados=[], bloqueados=["notificaciones"],
        modulos=list(MODULOS.keys()))
    assert efectivos == {"reportes"}
    print("OK  test_bloqueo_le_gana_al_area")


def test_bloqueo_le_gana_tambien_al_agregado():
    """Si el agregado ganara, 'bloqueado' no significaría nada estable."""
    efectivos = calcular_efectivos(
        del_area=[], agregados=["reportes"], bloqueados=["reportes"],
        modulos=list(MODULOS.keys()))
    assert efectivos == set()
    print("OK  test_bloqueo_le_gana_tambien_al_agregado")


def test_agregado_suma_sobre_el_area():
    efectivos = calcular_efectivos(
        del_area=["reportes"], agregados=["noticias"], bloqueados=[],
        modulos=list(MODULOS.keys()))
    assert efectivos == {"reportes", "noticias"}
    print("OK  test_agregado_suma_sobre_el_area")


def test_modulo_apagado_anula_permisos_ya_asignados():
    """Red de seguridad: si plataforma apaga un módulo, los permisos viejos
    dejan de valer solos, sin salir a limpiar filas."""
    efectivos = calcular_efectivos(
        del_area=["reportes", "noticias"], agregados=["emp_empresas"], bloqueados=[],
        modulos=["noticias"])
    assert efectivos == {"noticias"}
    print("OK  test_modulo_apagado_anula_permisos_ya_asignados")


# ---------- Contra la base ----------

def test_super_admin_tiene_todo_lo_contratado():
    efectivos = db.permisos_efectivos(U_JEFE)
    assert efectivos == set(SECCIONES.keys())
    assert db.tiene_permiso(U_JEFE, "tramites_formularios")
    print("OK  test_super_admin_tiene_todo_lo_contratado")


def test_super_admin_no_ve_secciones_de_modulos_apagados():
    """Ni siquiera el Super Admin ve secciones de un módulo que el sindicato
    no contrató -- si no, el panel mostraría pestañas muertas."""
    with db.get_session() as s:
        u = _crear_super_admin_en(s, SID_B, "20222222229")
    efectivos = db.permisos_efectivos(u)
    assert "reportes" in efectivos and "noticias" in efectivos
    assert "emp_empresas" not in efectivos, "empleadores no está contratado en el sindicato B"
    assert "tramites_recibidos" not in efectivos
    print("OK  test_super_admin_no_ve_secciones_de_modulos_apagados")


def _crear_super_admin_en(s, sid, cuil):
    u = UsuarioSindicato(sindicato_id=sid, usuario=cuil, nombre="Jefe B",
                         clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False,
                         es_super_admin=True)
    s.add(u); s.commit(); s.refresh(u)
    return u.id


def test_usuario_de_area_hereda_del_area():
    efectivos = db.permisos_efectivos(U_GABRIEL)
    assert efectivos == {"tramites_recibidos", "notificaciones", "trabajadores"}
    assert not db.tiene_permiso(U_GABRIEL, "tramites_formularios")
    assert not db.tiene_permiso(U_GABRIEL, "formulas")
    print("OK  test_usuario_de_area_hereda_del_area")


def test_permiso_individual_suma_y_resta_contra_la_base():
    with db.get_session() as s:
        s.add(PermisoUsuario(usuario_id=U_GABRIEL, seccion="reportes", tipo="agregar"))
        s.add(PermisoUsuario(usuario_id=U_GABRIEL, seccion="notificaciones", tipo="bloquear"))
        s.commit()
    efectivos = db.permisos_efectivos(U_GABRIEL)
    assert "reportes" in efectivos, "el agregado individual tiene que sumar"
    assert "notificaciones" not in efectivos, "el bloqueo individual tiene que ganarle al área"
    assert "tramites_recibidos" in efectivos, "lo demás del área no se toca"
    # Se deshace y vuelve a lo heredado, sin tocar el área.
    with db.get_session() as s:
        for p in s.exec(select(PermisoUsuario).where(
                PermisoUsuario.usuario_id == U_GABRIEL)).all():
            s.delete(p)
        s.commit()
    assert db.permisos_efectivos(U_GABRIEL) == {"tramites_recibidos", "notificaciones", "trabajadores"}
    print("OK  test_permiso_individual_suma_y_resta_contra_la_base")


def test_usuario_dado_de_baja_no_tiene_permisos():
    assert db.permisos_efectivos(U_BAJA) == set()
    assert db.alcance_seccional(U_BAJA) == set()
    print("OK  test_usuario_dado_de_baja_no_tiene_permisos")


def test_usuario_inexistente_no_rompe():
    assert db.permisos_efectivos(999999) == set()
    assert db.alcance_seccional(999999) == set()
    print("OK  test_usuario_inexistente_no_rompe")


def test_area_desactivada_no_da_permisos():
    """Desactivar un área le corta el acceso a todo su equipo de una."""
    assert db.permisos_efectivos(U_ZOMBI) == set()
    print("OK  test_area_desactivada_no_da_permisos")


def test_usuario_sin_area_no_tiene_permisos():
    assert db.permisos_efectivos(U_HUERFANO) == set()
    print("OK  test_usuario_sin_area_no_tiene_permisos")


def test_permisos_del_sindicato_b_filtrados_por_sus_modulos():
    """El área de Fega tiene asignadas 3 secciones, pero el sindicato solo
    contrató recibos y noticias: emp_empresas y tramites no sobreviven."""
    efectivos = db.permisos_efectivos(U_FEGA)
    assert efectivos == {"reportes"}
    print("OK  test_permisos_del_sindicato_b_filtrados_por_sus_modulos")


# ---------- Alcance por seccional ----------

def test_alcance_super_admin_es_todas():
    assert db.alcance_seccional(U_JEFE) is None
    print("OK  test_alcance_super_admin_es_todas")


def test_alcance_de_seccional_comun_es_solo_la_suya():
    assert db.alcance_seccional(U_GABRIEL) == {SEC_ROSARIO}
    print("OK  test_alcance_de_seccional_comun_es_solo_la_suya")


def test_alcance_de_sede_central_es_todas():
    """ve_todas tildado: el usuario de área alcanza todo el sindicato."""
    assert db.alcance_seccional(U_CENTRAL) is None
    print("OK  test_alcance_de_sede_central_es_todas")


def test_ve_todas_es_configurable_en_cualquier_seccional():
    """No está atado al nombre 'Sede Central': el Super Admin puede tildarlo
    en una regional que supervisa varias."""
    assert db.alcance_seccional(U_GABRIEL) == {SEC_ROSARIO}
    with db.get_session() as s:
        sec = s.get(Seccional, SEC_ROSARIO)
        sec.ve_todas = True
        s.add(sec); s.commit()
    assert db.alcance_seccional(U_GABRIEL) is None
    with db.get_session() as s:
        sec = s.get(Seccional, SEC_ROSARIO)
        sec.ve_todas = False
        s.add(sec); s.commit()
    assert db.alcance_seccional(U_GABRIEL) == {SEC_ROSARIO}
    print("OK  test_ve_todas_es_configurable_en_cualquier_seccional")


def test_usuario_de_area_sin_seccional_no_alcanza_nada():
    """Falla cerrado: un dato incompleto no puede terminar en ver TODO."""
    assert db.alcance_seccional(U_HUERFANO) == set()
    print("OK  test_usuario_de_area_sin_seccional_no_alcanza_nada")


def test_seccional_de_otro_sindicato_no_alcanza_nada():
    """Aunque tenga ve_todas tildado: es de otro sindicato, no cuenta."""
    assert db.alcance_seccional(U_AJENO) == set()
    print("OK  test_seccional_de_otro_sindicato_no_alcanza_nada")


if __name__ == "__main__":
    test_catalogo_coherente_con_modulos()
    test_seccion_de_super_admin_no_es_asignable()
    test_secciones_de_modulos_filtra()
    test_tramites_se_puede_dar_sin_crear_formularios()
    test_agrupar_para_ui_no_devuelve_grupos_vacios()
    test_bloqueo_le_gana_al_area()
    test_bloqueo_le_gana_tambien_al_agregado()
    test_agregado_suma_sobre_el_area()
    test_modulo_apagado_anula_permisos_ya_asignados()
    test_super_admin_tiene_todo_lo_contratado()
    test_super_admin_no_ve_secciones_de_modulos_apagados()
    test_usuario_de_area_hereda_del_area()
    test_permiso_individual_suma_y_resta_contra_la_base()
    test_usuario_dado_de_baja_no_tiene_permisos()
    test_usuario_inexistente_no_rompe()
    test_area_desactivada_no_da_permisos()
    test_usuario_sin_area_no_tiene_permisos()
    test_permisos_del_sindicato_b_filtrados_por_sus_modulos()
    test_alcance_super_admin_es_todas()
    test_alcance_de_seccional_comun_es_solo_la_suya()
    test_alcance_de_sede_central_es_todas()
    test_ve_todas_es_configurable_en_cualquier_seccional()
    test_usuario_de_area_sin_seccional_no_alcanza_nada()
    test_seccional_de_otro_sindicato_no_alcanza_nada()
    print("\nTodos los tests de áreas y permisos pasaron.")
