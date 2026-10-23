"""El alta de usuario del panel consulta el padrón, y el padrón ofrece dar
usuario (2026-10-17). Las dos puertas siguen separadas (Trabajadores es el
padrón, Áreas y Usuarios el equipo del gremio): esto solo evita tipear el
CUIL dos veces y dice de antemano qué va a pasar con la clave.

Correr con: python -m pytest test_alta_usuario_padron.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
import main
from db import Sindicato, UsuarioSindicato, Seccional, Trabajador
from fastapi.testclient import TestClient
from sqlmodel import Session

db.crear_tablas()

ADMIN = "20111111112"
LOCAL = "20555555556"
AFILIADO = "27222222228"      # en el padrón, seccional Rosario
AFILIADO_CBA = "20888888889"  # en el padrón, seccional Córdoba
NADIE = "23010101018"         # válido, no está en ningún lado

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Padrón Alta", slug="padron-alta", color_base="#0f1b2d")
    otro = Sindicato(nombre="Otro Padrón", slug="otro-padron", color_base="#0f1b2d")
    s.add(sind); s.add(otro); s.commit(); s.refresh(sind); s.refresh(otro)
    SID = sind.id
    ros = Seccional(sindicato_id=SID, nombre="Rosario")
    cba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(ros); s.add(cba); s.commit(); s.refresh(ros); s.refresh(cba)
    SEC_ROS, SEC_CBA = ros.id, cba.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=ADMIN, cuil=ADMIN, nombre="General",
                           clave_hash=auth.hashear_clave("adm"), es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=LOCAL, cuil=LOCAL, nombre="Local Rosario",
                           clave_hash=auth.hashear_clave("loc"), es_admin_seccional=True,
                           seccional_id=SEC_ROS))
    # Un usuario del OTRO sindicato con el CUIL del afiliado de Córdoba: ya
    # tiene clave del panel.
    s.add(UsuarioSindicato(sindicato_id=otro.id, usuario=AFILIADO_CBA, cuil=AFILIADO_CBA,
                           nombre="Fabián", clave_hash=auth.hashear_clave("otra"), es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO, seccional_id=SEC_ROS, activo=True))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO_CBA, seccional_id=SEC_CBA, activo=True))
    db.asegurar_cuenta(s, AFILIADO).nombre = "Ana Pérez"
    db.asegurar_cuenta(s, AFILIADO_CBA).nombre = "Fabián Luna"
    s.commit()


def _cliente(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def test_1_el_afiliado_del_padron_sale_con_nombre_y_seccional():
    d = _cliente(ADMIN, "adm").get(f"/admin/usuario/padron?cuil={AFILIADO}").json()
    assert d["en_padron"] and d["nombre"] == "Ana Pérez"
    assert d["seccional_id"] == SEC_ROS and d["seccional"] == "Rosario"
    assert d["ya_es_usuario"] is False and d["tiene_clave_panel"] is False


def test_2_quien_no_esta_en_el_padron_no_revela_nada():
    d = _cliente(ADMIN, "adm").get(f"/admin/usuario/padron?cuil={NADIE}").json()
    assert d == {"en_padron": False, "valido": True, "tiene_clave_panel": False}
    assert _cliente(ADMIN, "adm").get("/admin/usuario/padron?cuil=123").json() == {
        "en_padron": False, "valido": False}


def test_3_la_clave_del_panel_de_otro_sindicato_se_avisa():
    d = _cliente(ADMIN, "adm").get(f"/admin/usuario/padron?cuil={AFILIADO_CBA}").json()
    assert d["en_padron"] and d["tiene_clave_panel"] is True
    assert d["nombre"] == "Fabián Luna"


def test_4_el_admin_local_no_lee_el_padron_de_otra_seccional():
    c = _cliente(LOCAL, "loc")
    propio = c.get(f"/admin/usuario/padron?cuil={AFILIADO}").json()
    assert propio["en_padron"] and propio["nombre"] == "Ana Pérez"
    ajeno = c.get(f"/admin/usuario/padron?cuil={AFILIADO_CBA}").json()
    assert ajeno["en_padron"] and ajeno.get("fuera_alcance") is True
    assert "nombre" not in ajeno and "seccional" not in ajeno


def test_5_un_usuario_de_area_no_consulta():
    with db.get_session() as s:
        s.add(UsuarioSindicato(sindicato_id=SID, usuario="20666666667", cuil="20666666667",
                               clave_hash=auth.hashear_clave("area"), seccional_id=SEC_ROS))
        s.commit()
    r = _cliente("20666666667", "area").get(f"/admin/usuario/padron?cuil={AFILIADO}",
                                            follow_redirects=False)
    assert r.status_code in (303, 403)


def test_6_el_padron_ofrece_dar_usuario_solo_a_quien_administra_y_dentro_del_alcance():
    html_admin = _cliente(ADMIN, "adm").get("/admin").text
    assert f"/admin?sub=usuarios&cuil={AFILIADO}&" in html_admin
    assert f"/admin?sub=usuarios&cuil={AFILIADO_CBA}&" in html_admin
    html_local = _cliente(LOCAL, "loc").get("/admin").text
    assert f"/admin?sub=usuarios&cuil={AFILIADO}&" in html_local
    assert f"/admin?sub=usuarios&cuil={AFILIADO_CBA}&" not in html_local


def test_7_quien_ya_es_empleado_no_tiene_el_boton():
    c = _cliente(ADMIN, "adm")
    r = c.post("/admin/usuario", data={"usuario": AFILIADO, "nombre": "Ana Pérez",
                                       "clave_inicial": "x", "rol": "seccional",
                                       "seccional_id": str(SEC_ROS)}, follow_redirects=False)
    assert "ok=usuario" in r.headers["location"]
    assert f"/admin?sub=usuarios&cuil={AFILIADO}&" not in c.get("/admin").text
    assert c.get(f"/admin/usuario/padron?cuil={AFILIADO}").json()["ya_es_usuario"] is True


def test_8_la_pantalla_lleva_el_aviso_y_la_consulta():
    html = _cliente(ADMIN, "adm").get("/admin?sub=usuarios&cuil=20111111112&nombre=X").text
    assert 'id="usu-padron-aviso"' in html
    assert "consultarPadronUsuario" in html and "/admin/usuario/padron?cuil=" in html
