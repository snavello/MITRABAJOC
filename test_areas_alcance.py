"""Una sola regla de alcance, para escribir Y para ver -- Fase 6 (N10).

Hasta acá el alcance de seccional regía trámites. Ahora rige también
Notificaciones, Noticias y Beneficios, y no solo a quién se le puede
escribir sino QUÉ HISTORIAL se ve. Es la definición que cerró la entrada 3
del BACKLOG, abierta desde agosto:

    Prensa de Sede Central le escribe a todo el país y ve todo el historial.
    Prensa de Córdoba le escribe solo a Córdoba y ve solo eso.

Correr con: python -m pytest test_areas_alcance.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                Trabajador, Noticia, Beneficio)
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Alcance", slug="uom-alcance", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    cordoba = Seccional(sindicato_id=SID, nombre="Córdoba")
    rosario = Seccional(sindicato_id=SID, nombre="Rosario")
    s.add(central); s.add(cordoba); s.add(rosario); s.commit()
    for x in (central, cordoba, rosario):
        s.refresh(x)
    SEC_CEN, SEC_CBA, SEC_ROS = central.id, cordoba.id, rosario.id

    prensa_cen = Area(sindicato_id=SID, seccional_id=SEC_CEN, nombre="Prensa")
    prensa_cba = Area(sindicato_id=SID, seccional_id=SEC_CBA, nombre="Prensa")
    s.add(prensa_cen); s.add(prensa_cba); s.commit()
    s.refresh(prensa_cen); s.refresh(prensa_cba)
    for a in (prensa_cen.id, prensa_cba.id):
        for seccion in ("notificaciones", "noticias", "beneficios"):
            s.add(PermisoArea(area_id=a, seccion=seccion))

    for cuil, nombre, sec in [("20300000001", "Cordobés Uno", SEC_CBA),
                              ("20300000002", "Cordobés Dos", SEC_CBA),
                              ("20300000003", "Rosarino", SEC_ROS),
                              ("20300000004", "Central", SEC_CEN)]:
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, nombre=nombre, seccional_id=sec,
                         activo=True, registrado=True))

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", cuil="20111111110",
                           nombre="Prensa Central", clave_hash=auth.hashear_clave("cen"),
                           debe_cambiar_clave=False, area_id=prensa_cen.id,
                           seccional_id=SEC_CEN))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111111", cuil="20111111111",
                           nombre="Prensa Córdoba", clave_hash=auth.hashear_clave("cba"),
                           debe_cambiar_clave=False, area_id=prensa_cba.id,
                           seccional_id=SEC_CBA))
    s.commit()

with db.get_session() as s:
    U_CEN = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "20111111110")).first().id
    U_CBA = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "20111111111")).first().id


def _cli(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def _central():
    return _cli("20111111110", "cen")


def _cordoba():
    return _cli("20111111111", "cba")


# ---------- A quién se le puede escribir ----------

def test_central_alcanza_a_todos_y_cordoba_solo_a_los_suyos():
    """Sede Central tiene ve_todas; Córdoba no."""
    todos = db.resolver_destinatarios(SID, "seccional",
                                      [str(SEC_CEN), str(SEC_CBA), str(SEC_ROS)],
                                      usuario_id=U_CEN)
    solo_cba = db.resolver_destinatarios(SID, "seccional",
                                         [str(SEC_CEN), str(SEC_CBA), str(SEC_ROS)],
                                         usuario_id=U_CBA)
    assert len(todos) == 4
    assert set(solo_cba) == {"20300000001", "20300000002"}
    print("OK  test_central_alcanza_a_todos_y_cordoba_solo_a_los_suyos")


def test_el_recorte_vale_para_TODOS_los_criterios_no_solo_seccional():
    """Pidiendo por CUIL se llegaría igual a gente de afuera, así que el
    recorte no puede depender del criterio elegido."""
    ajeno = db.resolver_destinatarios(SID, "cuil", ["20300000003"], usuario_id=U_CBA)
    assert ajeno == [], "el rosarino no está en su alcance"
    propio = db.resolver_destinatarios(SID, "cuil", ["20300000001"], usuario_id=U_CBA)
    assert propio == ["20300000001"]
    print("OK  test_el_recorte_vale_para_TODOS_los_criterios_no_solo_seccional")


def test_el_preview_cuenta_EXACTAMENTE_lo_que_sale():
    """La razón por la que el recorte vive en resolver_destinatarios y no en
    la ruta: preview y envío usan la MISMA función. Si contaran distinto, el
    admin confirmaría un número y saldría otro, y nadie los compara."""
    c = _cordoba()
    r = c.post("/admin/notificacion/preview",
               data={"criterio": "seccional",
                     "valores": [str(SEC_CBA), str(SEC_ROS)]})
    contados = r.json()["cantidad"]
    c.post("/admin/notificacion", data={
        "remitente": "Prensa", "texto": "Aviso de Córdoba",
        "criterio": "seccional", "valores": [str(SEC_CBA), str(SEC_ROS)]},
        follow_redirects=False)
    enviada = db.notificaciones_del_sindicato(SID)[0]
    assert contados == enviada["cantidad_destinatarios"] == 2, (contados, enviada)
    print("OK  test_el_preview_cuenta_EXACTAMENTE_lo_que_sale")


# ---------- Qué historial se ve ----------

def test_cada_uno_ve_el_historial_de_los_que_puede_escribir():
    c = _central()
    c.post("/admin/notificacion", data={
        "remitente": "Prensa", "texto": "Solo para Rosario",
        "criterio": "seccional", "valores": [str(SEC_ROS)]}, follow_redirects=False)

    textos_cen = {n["texto"] for n in db.notificaciones_del_sindicato(SID, usuario_id=U_CEN)}
    textos_cba = {n["texto"] for n in db.notificaciones_del_sindicato(SID, usuario_id=U_CBA)}
    assert "Solo para Rosario" in textos_cen, "central ve todo"
    assert "Aviso de Córdoba" in textos_cen
    assert "Solo para Rosario" not in textos_cba, "no fue a nadie suyo"
    assert "Aviso de Córdoba" in textos_cba, "esta sí"
    print("OK  test_cada_uno_ve_el_historial_de_los_que_puede_escribir")


def test_una_notificacion_a_todo_el_pais_la_ve_tambien_el_admin_local():
    """Incluye a su gente, así que le corresponde -- lo que no ve son las
    que fueron SOLO a otras delegaciones."""
    _central().post("/admin/notificacion", data={
        "remitente": "Prensa", "texto": "Para todo el país",
        "criterio": "seccional",
        "valores": [str(SEC_CEN), str(SEC_CBA), str(SEC_ROS)]}, follow_redirects=False)
    textos_cba = {n["texto"] for n in db.notificaciones_del_sindicato(SID, usuario_id=U_CBA)}
    assert "Para todo el país" in textos_cba
    print("OK  test_una_notificacion_a_todo_el_pais_la_ve_tambien_el_admin_local")


def test_los_destinatarios_de_una_compartida_tambien_se_recortan():
    """La otra mitad del recorte. Sin esto el listado escondería lo ajeno
    pero el detalle entregaría igual los CUIL de todas las delegaciones."""
    nacional = [n for n in db.notificaciones_del_sindicato(SID)
                if n["texto"] == "Para todo el país"][0]
    r = _cordoba().get(f"/admin/notificacion/{nacional['id']}/destinatarios")
    cuiles = {d["cuil"] for d in r.json()["destinatarios"]}
    assert cuiles == {"20300000001", "20300000002"}, cuiles
    r2 = _central().get(f"/admin/notificacion/{nacional['id']}/destinatarios")
    assert len({d["cuil"] for d in r2.json()["destinatarios"]}) == 4
    print("OK  test_los_destinatarios_de_una_compartida_tambien_se_recortan")


# ---------- Noticias y Beneficios ----------

def test_una_noticia_de_un_admin_local_no_sale_a_todo_el_pais():
    """El caso que un recorte ingenuo deja pasar: la lista de destinos VACÍA
    significa "a todas las seccionales". Dejarla vacía para alguien acotado
    sería darle justo lo que el alcance le niega."""
    _cordoba().post("/admin/noticia", data={
        "titulo": "Novedad cordobesa", "bajada": "", "texto_completo": "x",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
        "destino_seccionales": []}, follow_redirects=False)
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.titulo == "Novedad cordobesa")).first()
    assert n is not None
    assert n.destino_seccionales == [SEC_CBA], n.destino_seccionales
    print("OK  test_una_noticia_de_un_admin_local_no_sale_a_todo_el_pais")


def test_un_destino_fuera_del_alcance_se_descarta():
    _cordoba().post("/admin/beneficio", data={
        "rubro": "Descuento cordobés", "descripcion": "x", "link": "",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
        "destino_seccionales": [str(SEC_CBA), str(SEC_ROS)]}, follow_redirects=False)
    with Session(db.engine) as s:
        b = s.exec(select(Beneficio).where(Beneficio.rubro == "Descuento cordobés")).first()
    assert b.destino_seccionales == [SEC_CBA], "Rosario se descarta"
    print("OK  test_un_destino_fuera_del_alcance_se_descarta")


def test_central_si_puede_publicar_a_todos():
    """El contrapeso: que el recorte venga del alcance y no de un bug."""
    _central().post("/admin/noticia", data={
        "titulo": "Novedad nacional", "bajada": "", "texto_completo": "x",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
        "destino_seccionales": []}, follow_redirects=False)
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.titulo == "Novedad nacional")).first()
    assert n.destino_seccionales == [], "vacío = a todas, y central puede"
    print("OK  test_central_si_puede_publicar_a_todos")


if __name__ == "__main__":
    test_central_alcanza_a_todos_y_cordoba_solo_a_los_suyos()
    test_el_recorte_vale_para_TODOS_los_criterios_no_solo_seccional()
    test_el_preview_cuenta_EXACTAMENTE_lo_que_sale()
    test_cada_uno_ve_el_historial_de_los_que_puede_escribir()
    test_una_notificacion_a_todo_el_pais_la_ve_tambien_el_admin_local()
    test_los_destinatarios_de_una_compartida_tambien_se_recortan()
    test_una_noticia_de_un_admin_local_no_sale_a_todo_el_pais()
    test_un_destino_fuera_del_alcance_se_descarta()
    test_central_si_puede_publicar_a_todos()
    print("\nTodos los tests de alcance único pasaron.")
