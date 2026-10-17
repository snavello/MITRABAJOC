"""El Admin de Seccional acotado en TODO el panel (PLAN_ALCANCE_SECCIONAL.md).

Dos cosas en un archivo:

1. La RED: `ALCANCE_POR_PREFIJO` clasifica toda ruta `/admin/*` según cómo
   se relaciona con la seccional (`seccional` = recorta o exige alcance,
   `sindicato` = es del sindicato entero y no tiene seccional, `entrada` =
   login, portada y pantallas). Una ruta nueva sin clasificar hace fallar el
   test: el olvido se nota (mismo criterio que PERMISOS_RUTAS).
2. El COMPORTAMIENTO, bloque por bloque, con una fixture chica: un general,
   un admin local de Rosario, afiliados de dos seccionales, publicaciones de
   cada una y una global. Cada bloque lleva su "el general sigue viendo todo".

Correr con: python -m pytest test_alcance_seccional_panel.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
import main
from db import (Sindicato, UsuarioSindicato, Seccional, Trabajador, Noticia, Beneficio)
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

GENERAL, LOCAL = "20111111112", "20555555556"
ANA, FABIAN, SIN_SEC = "27222222228", "20888888889", "23999999999"

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Alcance Panel", slug="alcance-panel", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    ros = Seccional(sindicato_id=SID, nombre="Rosario")
    cba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(ros); s.add(cba); s.commit(); s.refresh(ros); s.refresh(cba)
    SEC_ROS, SEC_CBA = ros.id, cba.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=GENERAL, cuil=GENERAL, nombre="General",
                           clave_hash=auth.hashear_clave("gen"), es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=LOCAL, cuil=LOCAL, nombre="Local Rosario",
                           clave_hash=auth.hashear_clave("loc"), es_admin_seccional=True,
                           seccional_id=SEC_ROS))
    for cuil, nombre, sec in ((ANA, "Ana Rosario", SEC_ROS), (FABIAN, "Fabián Córdoba", SEC_CBA),
                              (SIN_SEC, "Sin Seccional", None)):
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, seccional_id=sec, activo=True))
        db.asegurar_cuenta(s, cuil).nombre = nombre
    for titulo, dest in (("Noticia global", []), ("Noticia Rosario", [SEC_ROS]),
                         ("Noticia Córdoba", [SEC_CBA]), ("Noticia ambas", [SEC_ROS, SEC_CBA])):
        s.add(Noticia(sindicato_id=SID, titulo=titulo, fecha_desde="2026-01-01", fecha_hasta="2027-01-01",
                      creada="2026-10-17 10:00", destino_seccionales=dest))
    for rubro, dest in (("Beneficio global", []), ("Beneficio Rosario", [SEC_ROS]),
                        ("Beneficio Córdoba", [SEC_CBA])):
        s.add(Beneficio(sindicato_id=SID, rubro=rubro, fecha_desde="2026-01-01", fecha_hasta="2027-01-01",
                        creada="2026-10-17 10:00", destino_seccionales=dest))
    s.commit()


def _cliente(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def _uid(cuil):
    with Session(db.engine) as s:
        return s.exec(select(UsuarioSindicato).where(UsuarioSindicato.cuil == cuil)).first().id


def _noticia(titulo):
    with Session(db.engine) as s:
        return s.exec(select(Noticia).where(Noticia.sindicato_id == SID, Noticia.titulo == titulo)).first()


def _beneficio(rubro):
    with Session(db.engine) as s:
        return s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID, Beneficio.rubro == rubro)).first()


# ====================== Bloque 0: la red ======================

# Prefijo de ruta -> cómo se relaciona con la seccional. El orden importa:
# gana el primer prefijo que calza.
ALCANCE_POR_PREFIJO = [
    ("/admin/login", "entrada"), ("/admin/salir", "entrada"), ("/admin/elegir", "entrada"),
    ("/admin/cambiar-sindicato", "entrada"), ("/admin/inicio", "entrada"),
    ("/admin/dashboard-v2", "entrada"), ("/admin/dashboard/", "seccional"),
    ("/admin/dashboard", "entrada"),
    # Catálogo del sindicato entero: no tiene seccional (bloque 5: solo
    # lectura para el admin local).
    ("/admin/concepto", "sindicato"), ("/admin/formula", "sindicato"),
    ("/admin/aprender", "sindicato"), ("/admin/convenio", "sindicato"),
    # Empleadores: sin seccional por modelo (N11; bloque 5: el local no entra).
    ("/admin/empleador", "sindicato"), ("/admin/notificacion-empresa", "sindicato"),
    ("/admin/tramite-tipo-empresa", "sindicato"), ("/admin/tramite-empresa", "sindicato"),
    ("/admin/tramites-empresa-nuevos-cantidad", "sindicato"),
    # Todo lo demás recorta o exige alcance.
    ("/admin/trabajador", "seccional"), ("/admin/noticia", "seccional"),
    ("/admin/beneficio", "seccional"), ("/admin/notificacion", "seccional"),
    ("/admin/encuesta", "seccional"), ("/admin/lista", "seccional"),
    ("/admin/reportes", "seccional"), ("/admin/seccional", "seccional"),
    ("/admin/tramite-tipo", "seccional"), ("/admin/tramite", "seccional"),
    ("/admin/tramites-nuevos-cantidad", "seccional"),
    ("/admin/usuario", "seccional"), ("/admin/area", "seccional"),
    ("/admin", "entrada"),
]


def clase_de_alcance(ruta: str):
    for prefijo, clase in ALCANCE_POR_PREFIJO:
        if ruta == prefijo or ruta.startswith(prefijo.rstrip("/") + "/") or ruta.startswith(prefijo) and prefijo.endswith("/"):
            return clase
    return None


def test_0_toda_ruta_admin_tiene_clase_de_alcance():
    rutas = set(main.PERMISOS_RUTAS) | set(main.RUTAS_ADMIN_SIN_PERMISO)
    sin_clase = sorted(r for r in rutas if clase_de_alcance(r) is None)
    assert not sin_clase, f"rutas sin clasificar en ALCANCE_POR_PREFIJO: {sin_clase}"


def test_0_los_prefijos_nombran_rutas_que_existen():
    rutas = set(main.PERMISOS_RUTAS) | set(main.RUTAS_ADMIN_SIN_PERMISO)
    muertos = [p for p, _ in ALCANCE_POR_PREFIJO
               if not any(clase_de_alcance(r) and (r == p or r.startswith(p)) for r in rutas)]
    assert not muertos, f"prefijos que no calzan con ninguna ruta: {muertos}"


# ====================== Bloque 1: Trabajadores ======================

def test_1_el_padron_del_local_es_solo_su_seccional_y_el_del_general_todo():
    with db.get_session() as s:
        todos = {t["cuil"] for t in db.padron_del_sindicato(s, SID, db.alcance_seccional(_uid(GENERAL)))}
        locales = {t["cuil"] for t in db.padron_del_sindicato(s, SID, db.alcance_seccional(_uid(LOCAL)))}
        nada = db.padron_del_sindicato(s, SID, set())
    assert {ANA, FABIAN, SIN_SEC} <= todos
    assert locales == {ANA}, "un afiliado sin seccional no lo alcanza nadie acotado"
    assert nada == []
    html = _cliente(LOCAL, "loc").get("/admin").text
    assert ANA in html and FABIAN not in html and SIN_SEC not in html
    assert FABIAN in _cliente(GENERAL, "gen").get("/admin").text


def test_1_el_local_no_da_de_alta_en_otra_seccional_y_sin_seccional_queda_en_la_suya():
    c = _cliente(LOCAL, "loc")
    base = {"nombre": "Nuevo", "provincia": "Santa Fe", "localidad": "Rosario"}
    r = c.post("/admin/trabajador", data={"cuil": "20333444551", "seccional_id": str(SEC_CBA), **base},
               follow_redirects=False)
    with Session(db.engine) as s:
        assert not s.exec(select(Trabajador).where(Trabajador.cuil == "20333444551")).first(), r.headers
    r = c.post("/admin/trabajador", data={"cuil": "20333444551", **base}, follow_redirects=False)
    with Session(db.engine) as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "20333444551")).first()
        assert t and t.seccional_id == SEC_ROS, r.headers.get("location")


def test_1_el_general_sigue_cargando_donde_quiera_incluso_sin_seccional():
    c = _cliente(GENERAL, "gen")
    c.post("/admin/trabajador", data={"cuil": "27000000006", "nombre": "G1", "provincia": "Córdoba",
                                      "localidad": "Córdoba", "seccional_id": str(SEC_CBA)})
    c.post("/admin/trabajador", data={"cuil": "27131313131", "nombre": "G2", "provincia": "Córdoba",
                                      "localidad": "Córdoba"})
    with Session(db.engine) as s:
        assert s.exec(select(Trabajador).where(Trabajador.cuil == "27000000006")).first().seccional_id == SEC_CBA
        assert s.exec(select(Trabajador).where(Trabajador.cuil == "27131313131")).first().seccional_id is None


def test_1_el_local_no_edita_a_un_afiliado_de_otra_seccional():
    with Session(db.engine) as s:
        fab = s.exec(select(Trabajador).where(Trabajador.cuil == FABIAN)).first()
    r = _cliente(LOCAL, "loc").post("/admin/trabajador", data={
        "id": str(fab.id), "cuil": FABIAN, "nombre": "Pisado", "provincia": "Córdoba",
        "localidad": "Córdoba", "seccional_id": str(SEC_CBA)}, follow_redirects=False)
    assert r.status_code in (303, 403)
    with Session(db.engine) as s:
        assert s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == FABIAN)).first().nombre == "Fabián Córdoba"


def test_1_la_carga_masiva_del_local_omite_otra_seccional_y_asigna_la_suya():
    lista = ("20666666667,Masivo Córdoba,,,,Córdoba,Córdoba,,,,Córdoba\n"
             "20101010105,Masivo Sin Seccional,,,,Rosario,Santa Fe,,,,\n"
             "23121212129,Masivo Rosario,,,,Rosario,Santa Fe,,,,Rosario\n")
    r = _cliente(LOCAL, "loc").post("/admin/trabajador/masivo", data={"lista": lista}, follow_redirects=False)
    assert "altas=2" in r.headers["location"] and "fueraalcance=1" in r.headers["location"], r.headers["location"]
    with Session(db.engine) as s:
        assert not s.exec(select(Trabajador).where(Trabajador.cuil == "20666666667")).first()
        assert s.exec(select(Trabajador).where(Trabajador.cuil == "20101010105")).first().seccional_id == SEC_ROS
        assert s.exec(select(Trabajador).where(Trabajador.cuil == "23121212129")).first().seccional_id == SEC_ROS


def test_1_el_formulario_del_local_no_ofrece_otras_seccionales_ni_sin_asignar():
    html = _cliente(LOCAL, "loc").get("/admin").text
    sel = html[html.index('id="trab-seccional"'):]
    sel = sel[:sel.index("</select>")]
    assert "Rosario" in sel and "Córdoba" not in sel and "Sin asignar" not in sel
    html = _cliente(GENERAL, "gen").get("/admin").text
    sel = html[html.index('id="trab-seccional"'):]
    sel = sel[:sel.index("</select>")]
    assert "Córdoba" in sel and "Sin asignar" in sel


# ====================== Bloque 2: Noticias y Beneficios ======================

def test_2_el_local_ve_las_suyas_y_las_globales_y_no_las_de_otra():
    vistas = {n["titulo"]: n["propia"] for n in db.noticias_del_sindicato(SID, db.alcance_seccional(_uid(LOCAL)))}
    assert set(vistas) == {"Noticia global", "Noticia Rosario", "Noticia ambas"}
    assert vistas == {"Noticia global": False, "Noticia Rosario": True, "Noticia ambas": False}
    todas = {n["titulo"]: n["propia"] for n in db.noticias_del_sindicato(SID, db.alcance_seccional(_uid(GENERAL)))}
    assert len(todas) == 4 and all(todas.values())
    assert db.noticias_del_sindicato(SID, set()) == []
    ben = {b["rubro"] for b in db.beneficios_del_sindicato(SID, db.alcance_seccional(_uid(LOCAL)))}
    assert ben == {"Beneficio global", "Beneficio Rosario"}


def test_2_la_pantalla_del_local_no_trae_la_noticia_de_cordoba_ni_botones_sobre_la_global():
    html = _cliente(LOCAL, "loc").get("/admin").text
    assert "Noticia Rosario" in html and "Noticia Córdoba" not in html
    fila = html[html.index("Noticia global"):]
    fila = fila[:fila.index("</tr>")]
    assert "/admin/noticia/borrar" not in fila and "editarNoticia" not in fila
    fila = html[html.index("Noticia Rosario"):]
    fila = fila[:fila.index("</tr>")]
    assert "/admin/noticia/borrar" in fila


def test_2_el_local_no_edita_ni_borra_una_global_ni_una_de_otra_seccional():
    c = _cliente(LOCAL, "loc")
    for titulo in ("Noticia global", "Noticia Córdoba", "Noticia ambas"):
        n = _noticia(titulo)
        c.post("/admin/noticia", data={"id": str(n.id), "titulo": "PISADA", "fecha_desde": "2026-01-01",
                                       "fecha_hasta": "2027-01-01"}, follow_redirects=False)
        c.post("/admin/noticia/borrar", data={"id": n.id}, follow_redirects=False)
        with Session(db.engine) as s:
            sigue = s.get(Noticia, n.id)
            assert sigue and sigue.titulo == titulo and sigue.destino_seccionales == n.destino_seccionales
    b = _beneficio("Beneficio Córdoba")
    c.post("/admin/beneficio", data={"id": str(b.id), "rubro": "PISADO", "fecha_desde": "2026-01-01",
                                     "fecha_hasta": "2027-01-01"}, follow_redirects=False)
    c.post("/admin/beneficio/borrar", data={"id": b.id}, follow_redirects=False)
    with Session(db.engine) as s:
        assert s.get(Beneficio, b.id).rubro == "Beneficio Córdoba"


def test_2_el_local_si_edita_la_suya_y_no_la_escapa_del_alcance():
    c = _cliente(LOCAL, "loc")
    n = _noticia("Noticia Rosario")
    c.post("/admin/noticia", data={"id": str(n.id), "titulo": "Noticia Rosario editada",
                                   "fecha_desde": "2026-01-01", "fecha_hasta": "2027-01-01",
                                   "destino_seccionales": [str(SEC_CBA)]}, follow_redirects=False)
    with Session(db.engine) as s:
        x = s.get(Noticia, n.id)
        assert x.titulo == "Noticia Rosario editada" and x.destino_seccionales == [SEC_ROS]


def test_2_el_general_edita_y_borra_cualquiera():
    c = _cliente(GENERAL, "gen")
    n = _noticia("Noticia Córdoba")
    c.post("/admin/noticia", data={"id": str(n.id), "titulo": "Córdoba por el general",
                                   "fecha_desde": "2026-01-01", "fecha_hasta": "2027-01-01"},
           follow_redirects=False)
    with Session(db.engine) as s:
        assert s.get(Noticia, n.id).titulo == "Córdoba por el general"
    b = _beneficio("Beneficio global")
    c.post("/admin/beneficio/borrar", data={"id": b.id}, follow_redirects=False)
    with Session(db.engine) as s:
        assert s.get(Beneficio, b.id) is None
