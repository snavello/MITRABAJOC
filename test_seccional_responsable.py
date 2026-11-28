"""El RESPONSABLE de una seccional (texto, hasta 120): alta y edición por el panel
(con el mismo alcance que el resto de los campos), la ficha, la app del afiliado
y la carga desde planilla de XSII. La columna nace con la migración d3f5a7b9c1e4
(`test_migraciones.py` compara modelo y migraciones).

Correr con: .venv/bin/python -m pytest test_seccional_responsable.py -q
"""
import auth
import db
import main
from db import Seccional, Sindicato, Trabajador, UsuarioSindicato
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

GENERAL, LOCAL, AFIL = "20111111112", "20555555556", "23999999999"
VALIDO = {"provincia": "Santa Fe", "localidad": "Rosario", "calle": "San Martín", "numero": "850",
          "piso_depto": "", "codigo_postal": "2000", "latitud": "-32.947338", "longitud": "-60.636893",
          "precision_geo": "exacta"}

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Responsable", slug="sind-responsable", color_base="#0f1b2d")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    ros = Seccional(sindicato_id=SID, nombre="Rosario", responsable="Marta Quiroga")
    cba = Seccional(sindicato_id=SID, nombre="Córdoba", responsable="Hugo Lezama")
    s.add(ros); s.add(cba); s.commit(); s.refresh(ros); s.refresh(cba)
    SEC_ROS, SEC_CBA = ros.id, cba.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=GENERAL, cuil=GENERAL, nombre="General",
                           clave_hash=auth.hashear_clave("gen"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=LOCAL, cuil=LOCAL, nombre="Local Rosario",
                           clave_hash=auth.hashear_clave("loc"), debe_cambiar_clave=False, es_admin_seccional=True,
                           seccional_id=SEC_ROS))
    s.add(Trabajador(sindicato_id=SID, cuil=AFIL, registrado=True, seccional_id=SEC_ROS))
    db.guardar_datos_personales(s, AFIL, nombre="Afiliada").clave_hash = auth.hashear_clave("x")
    s.commit()


def _panel(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def _sec(sec_id):
    with Session(db.engine) as s:
        return s.get(Seccional, sec_id)


def _datos(nombre, **extra):
    return {**VALIDO, "nombre": nombre, **extra}


def test_la_columna_existe_y_el_default_es_vacio():
    with Session(db.engine) as s:
        nueva = Seccional(sindicato_id=SID, nombre="Sin responsable")
        s.add(nueva); s.commit(); s.refresh(nueva)
        assert nueva.responsable == ""
    assert db.seccional_del_sindicato(SID, SEC_ROS)["responsable"] == "Marta Quiroga"


def test_alta_con_y_sin_responsable_y_recorte_a_120():
    c = _panel(GENERAL, "gen")
    r = c.post("/admin/seccional", data=_datos("Con", responsable="  Ana Paz  "), follow_redirects=False)
    assert r.status_code == 303
    r = c.post("/admin/seccional", data=_datos("Sin"), follow_redirects=False)
    r = c.post("/admin/seccional", data=_datos("Larga", responsable="x" * 300), follow_redirects=False)
    with Session(db.engine) as s:
        por = {x.nombre: x for x in s.exec(select(Seccional).where(Seccional.sindicato_id == SID)).all()}
    assert por["Con"].responsable == "Ana Paz" and por["Sin"].responsable == "" and len(por["Larga"].responsable) == 120


def test_edicion_cambia_y_borra_el_responsable_y_la_ficha_lo_trae():
    c = _panel(GENERAL, "gen")
    c.post("/admin/seccional", data=_datos("Córdoba", id=str(SEC_CBA), responsable="Nuevo Titular"))
    assert _sec(SEC_CBA).responsable == "Nuevo Titular"
    assert c.get(f"/admin/seccional/{SEC_CBA}/ficha").json()["responsable"] == "Nuevo Titular"
    c.post("/admin/seccional", data=_datos("Córdoba", id=str(SEC_CBA), responsable=""))
    assert _sec(SEC_CBA).responsable == ""


def test_el_admin_de_seccional_edita_el_de_la_suya_y_no_el_de_otra():
    c = _panel(LOCAL, "loc")
    r = c.post("/admin/seccional", data=_datos("Rosario", id=str(SEC_ROS), responsable="Edita el local"), follow_redirects=False)
    assert r.status_code == 303 and _sec(SEC_ROS).responsable == "Edita el local"
    antes = _sec(SEC_CBA).responsable
    r = c.post("/admin/seccional", data=_datos("Córdoba", id=str(SEC_CBA), responsable="Intruso"), follow_redirects=False)
    assert r.status_code == 403 and _sec(SEC_CBA).responsable == antes
    # y no puede crear (eso es del administrador general)
    assert c.post("/admin/seccional", data=_datos("Otra", responsable="X"), follow_redirects=False).status_code == 403


def test_el_formulario_y_la_ficha_del_panel_tienen_el_campo():
    html = _panel(GENERAL, "gen").get("/admin").text
    assert 'name="responsable"' in html and "Responsable (opcional)" in html and "sec-responsable" in html


def test_la_app_del_afiliado_lo_recibe_como_dato():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=AFIL))
    c.cookies.set("cuil_trab", AFIL)
    d = c.get("/api/seccionales").json()
    assert {s["nombre"]: s["responsable"] for s in d["seccionales"]}["Rosario"] == _sec(SEC_ROS).responsable
    assert all("responsable" in s for s in d["seccionales"])


def test_la_portada_del_afiliado_dibuja_el_responsable_como_texto():
    with Session(db.engine) as s:
        s.get(Seccional, SEC_ROS).responsable = "<b>Ana</b> & Co"
        s.commit()
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=SID, ident=AFIL))
    c.cookies.set("cuil_trab", AFIL)
    html = c.get("/app/inicio").text
    assert "Responsable: &lt;b&gt;Ana&lt;/b&gt; &amp; Co" in html and "<b>Ana</b>" not in html
    assert "escS(s.responsable)" in html           # el JS de «cerca de mí» escapa
