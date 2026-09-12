"""La estructura de Áreas V2 que carga cargar_demo.py, verificada corriendo
el script real (`python cargar_demo.py`) contra la base de test.

Mismo criterio que test_cargar_demo_empleadores.py: no se duplica la lógica
de carga, se verifica el resultado tal como lo vería quien corre el script.
Vale la pena porque la demo es lo que se muestra en vivo: si queda con un
usuario cuya área es de otra seccional, o con un formulario sin área
destino, el sindicato lo descubre en la demo y no acá.

Correr con: .venv/bin/python -m pytest test_cargar_demo_areas.py -q
"""
import os
import subprocess
import sys


# El subproceso hereda la DATABASE_URL de la base descartable que arma
# conftest.py: cargar_demo.py ya no crea tablas (el esquema lo pone Alembic
# en los entornos reales y create_all en la de los tests), así que tiene que
# escribir en una base que YA tenga el esquema.
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
resultado = subprocess.run(
    [sys.executable, "cargar_demo.py"], cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env, capture_output=True, text=True, timeout=120,
)
assert resultado.returncode == 0, resultado.stdout + resultado.stderr
SALIDA = resultado.stdout

import db
from db import (Sindicato, Seccional, Area, PermisoArea, UsuarioSindicato, Trabajador,
                TipoTramite, DestinoTipoTramite, PaseTipoTramite)
from sqlmodel import Session, select


def _todo():
    with Session(db.engine) as s:
        return (s.exec(select(Sindicato)).all(), s.exec(select(Seccional)).all(),
                s.exec(select(Area)).all(), s.exec(select(UsuarioSindicato)).all())


def test_cada_sindicato_tiene_sede_central_que_ve_todas():
    sinds, secs, _, _ = _todo()
    for sind in sinds:
        propias = [x for x in secs if x.sindicato_id == sind.id]
        assert propias, sind.nombre
        centrales = [x for x in propias if x.ve_todas]
        assert len(centrales) == 1, f"{sind.nombre}: {[x.nombre for x in centrales]}"
        assert centrales[0].nombre == "Sede Central"
    print("OK  test_cada_sindicato_tiene_sede_central_que_ve_todas")


def test_toda_area_pertenece_a_una_seccional_del_mismo_sindicato():
    _, secs, areas, _ = _todo()
    por_id = {x.id: x for x in secs}
    assert areas
    for a in areas:
        assert a.seccional_id in por_id, a.nombre
        assert por_id[a.seccional_id].sindicato_id == a.sindicato_id, a.nombre
    print("OK  test_toda_area_pertenece_a_una_seccional_del_mismo_sindicato")


def test_usuario_y_su_area_son_de_la_misma_seccional():
    """La regla de coherencia que fuerzan las rutas. Una demo que la viole
    muestra un usuario del que nadie sabe qué ve."""
    _, _, areas, usuarios = _todo()
    por_id = {a.id: a for a in areas}
    con_area = [u for u in usuarios if u.area_id]
    assert con_area
    for u in con_area:
        assert por_id[u.area_id].seccional_id == u.seccional_id, u.usuario
    print("OK  test_usuario_y_su_area_son_de_la_misma_seccional")


def test_los_super_admin_de_siempre_siguen_siendo_super_admin():
    """La premisa del sprint: el admin que hoy se usa en las demos no pierde
    nada. Uno por sindicato, en Sede Central y sin área."""
    sinds, secs, _, usuarios = _todo()
    centrales = {x.sindicato_id: x.id for x in secs if x.ve_todas}
    for sind in sinds:
        sa = [u for u in usuarios if u.sindicato_id == sind.id and u.es_super_admin]
        assert len(sa) == 1, f"{sind.nombre}: {len(sa)}"
        assert sa[0].seccional_id == centrales[sind.id]
        assert sa[0].area_id is None
        assert not sa[0].es_admin_seccional
    print("OK  test_los_super_admin_de_siempre_siguen_siendo_super_admin")


def test_hay_un_admin_de_seccional_y_no_es_de_sede_central():
    """El rol nuevo tiene que estar EN la demo (si no, no se puede mostrar)
    y tiene que estar en una delegación: un Admin de Seccional de Sede
    Central sería indistinguible del Super Admin."""
    _, secs, _, usuarios = _todo()
    centrales = {x.id for x in secs if x.ve_todas}
    locales = [u for u in usuarios if u.es_admin_seccional]
    assert locales, "la demo no muestra el rol de Admin de Seccional"
    for u in locales:
        assert u.seccional_id not in centrales, u.usuario
        assert not u.es_super_admin, u.usuario
    print("OK  test_hay_un_admin_de_seccional_y_no_es_de_sede_central")


def test_las_areas_tienen_perfiles_distintos():
    """Si todas las áreas heredan lo mismo, la pantalla de permisos parece
    decorativa. La demo tiene que mostrar al menos un área sin Trámites y
    una sin Noticias."""
    with Session(db.engine) as s:
        perfiles = {}
        for a in s.exec(select(Area)).all():
            perfiles[a.id] = {p.seccion for p in s.exec(select(PermisoArea).where(
                PermisoArea.area_id == a.id)).all()}
    assert all(perfiles.values()), "hay un área sin ningún permiso"
    assert len(set(map(frozenset, perfiles.values()))) > 1
    assert any("tramites_recibidos" not in p for p in perfiles.values())
    assert any("noticias" not in p for p in perfiles.values())
    print("OK  test_las_areas_tienen_perfiles_distintos")


def test_ninguna_area_queda_sin_usuario():
    """Un área destino de trámite (o de pase) sin nadie adentro es, en la
    demo, un expediente que no atiende nadie: el circuito se corta a la
    vista del sindicato."""
    _, _, areas, usuarios = _todo()
    con_gente = {u.area_id for u in usuarios if u.area_id}
    huerfanas = [a.nombre for a in areas if a.id not in con_gente]
    assert not huerfanas, huerfanas
    print("OK  test_ninguna_area_queda_sin_usuario")


def test_el_empleado_afiliado_queda_marcado_y_vinculado():
    with Session(db.engine) as s:
        vinculados = [u for u in s.exec(select(UsuarioSindicato)).all() if u.trabajador_id]
        assert vinculados
        for u in vinculados:
            t = s.get(Trabajador, u.trabajador_id)
            assert t.cuil == u.cuil
            assert t.sindicato_id == u.sindicato_id
            assert t.es_empleado_sindicato, u.usuario
    print("OK  test_el_empleado_afiliado_queda_marcado_y_vinculado")


def test_el_empleado_no_afiliado_no_inventa_fila_en_el_padron():
    """Trabajar en el gremio sin estar afiliado a él es un caso real: el
    usuario existe, la fila del padrón no, y el vínculo queda en NULL."""
    with Session(db.engine) as s:
        u = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "27777777774")).first()
        assert u is not None and u.area_id
        assert u.trabajador_id is None
        assert not s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == u.sindicato_id,
            Trabajador.cuil == u.cuil)).all()
    print("OK  test_el_empleado_no_afiliado_no_inventa_fila_en_el_padron")


def test_ningun_formulario_queda_sin_area_destino():
    """El default es lo que evita que una seccional nueva deje trámites sin
    dueño. Un formulario sin él es un agujero silencioso."""
    with Session(db.engine) as s:
        tipos = s.exec(select(TipoTramite)).all()
        assert tipos
        areas = {a.id: a for a in s.exec(select(Area)).all()}
        for t in tipos:
            assert t.area_destino_default_id, t.codigo
            assert areas[t.area_destino_default_id].sindicato_id == t.sindicato_id
    print("OK  test_ningun_formulario_queda_sin_area_destino")


def test_el_tramite_de_una_delegacion_cae_en_un_area_de_esa_delegacion():
    """El ruteo end-to-end tal como lo resuelve la app: para cada seccional
    mapeada, el área que sale es de ESA seccional."""
    with Session(db.engine) as s:
        areas = {a.id: a for a in s.exec(select(Area)).all()}
        mapeos = s.exec(select(DestinoTipoTramite)).all()
        assert mapeos
        for d in mapeos:
            destino = db.area_destino_para(d.tipo_tramite_id, d.seccional_id)
            assert destino == d.area_id
            assert areas[destino].seccional_id == d.seccional_id
    print("OK  test_el_tramite_de_una_delegacion_cae_en_un_area_de_esa_delegacion")


def test_solo_el_formulario_con_pase_declara_destinos_de_pase():
    with Session(db.engine) as s:
        tipos = s.exec(select(TipoTramite)).all()
        con_pase = [t for t in tipos if t.permite_pase]
        assert con_pase, "la demo no muestra el pase entre áreas"
        for t in tipos:
            destinos = db.areas_de_pase_de_tipo(t.id)
            if t.permite_pase:
                assert destinos, t.codigo
                assert t.area_destino_default_id not in destinos, \
                    f"{t.codigo}: derivar al que ya lo tiene no es un pase"
            else:
                assert not destinos, t.codigo
    print("OK  test_solo_el_formulario_con_pase_declara_destinos_de_pase")


def test_la_salida_lista_los_usuarios_nuevos():
    """El script se corre a mano antes de una demo: si no imprime las claves
    de los usuarios de área, hay que ir a buscarlas al código."""
    assert "Admin de Seccional" in SALIDA
    assert "usuario de área" in SALIDA
    assert "rosario-demo" in SALIDA
    print("OK  test_la_salida_lista_los_usuarios_nuevos")


if __name__ == "__main__":
    test_cada_sindicato_tiene_sede_central_que_ve_todas()
    test_toda_area_pertenece_a_una_seccional_del_mismo_sindicato()
    test_usuario_y_su_area_son_de_la_misma_seccional()
    test_los_super_admin_de_siempre_siguen_siendo_super_admin()
    test_hay_un_admin_de_seccional_y_no_es_de_sede_central()
    test_las_areas_tienen_perfiles_distintos()
    test_ninguna_area_queda_sin_usuario()
    test_el_empleado_afiliado_queda_marcado_y_vinculado()
    test_el_empleado_no_afiliado_no_inventa_fila_en_el_padron()
    test_ningun_formulario_queda_sin_area_destino()
    test_el_tramite_de_una_delegacion_cae_en_un_area_de_esa_delegacion()
    test_solo_el_formulario_con_pase_declara_destinos_de_pase()
    test_la_salida_lista_los_usuarios_nuevos()
    print("\nTodo OK — estructura de Áreas V2 en la demo.")
