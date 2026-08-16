"""Autogestión de administradores por el propio sindicato (antes solo
plataforma podía dar de alta/ver los UsuarioSindicato de un sindicato):
alta con clave inicial, editar nombre, activar/desactivar, siempre scopeado
al sindicato de la sesión -- y bloqueo de quedarse sin ningún admin activo.

Correr con: .venv/Scripts/python.exe test_admin_usuarios.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind_a = Sindicato(nombre="Sindicato Usuarios A", slug="sindicato-usuarios-a", color_base="#0f1b2d")
    sind_b = Sindicato(nombre="Sindicato Usuarios B", slug="sindicato-usuarios-b", color_base="#111111")
    s.add(sind_a); s.add(sind_b)
    s.commit(); s.refresh(sind_a); s.refresh(sind_b)
    SID_A, SID_B = sind_a.id, sind_b.id

    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20111111110", nombre="Admin Uno",
                            clave_hash=auth.hashear_clave("clave-a"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_B, usuario="20222222220", nombre="Admin B",
                            clave_hash=auth.hashear_clave("clave-b"), debe_cambiar_clave=False))
    s.commit()


def _admin_client(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def test_alta_de_un_segundo_admin_queda_en_el_sindicato_de_la_sesion():
    c = _admin_client("20111111110", "clave-a")
    r = c.post("/admin/usuario", data={
        "usuario": "20333333330", "nombre": "Admin Dos", "clave_inicial": "nueva-clave",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        u = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == "20333333330")).first()
        assert u is not None
        assert u.sindicato_id == SID_A          # no un campo del form -- sale de la sesión
        assert u.nombre == "Admin Dos"
        assert u.debe_cambiar_clave is True
        assert auth.verificar_clave("nueva-clave", u.clave_hash)
    print("OK  test_alta_de_un_segundo_admin_queda_en_el_sindicato_de_la_sesion")


def test_alta_duplicada_en_el_mismo_sindicato_rechaza():
    c = _admin_client("20111111110", "clave-a")
    r = c.post("/admin/usuario", data={
        "usuario": "20333333330", "nombre": "Otra vez", "clave_inicial": "x",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "err=usuarioexiste" in r.headers["location"]
    print("OK  test_alta_duplicada_en_el_mismo_sindicato_rechaza")


def test_listado_de_admin_no_ve_los_de_otro_sindicato():
    c = _admin_client("20111111110", "clave-a")
    r = c.get("/admin")
    assert "20111111110" in r.text
    assert "20333333330" in r.text
    assert "20222222220" not in r.text  # del sindicato B, no debe aparecer
    print("OK  test_listado_de_admin_no_ve_los_de_otro_sindicato")


def test_editar_solo_cambia_nombre():
    with Session(db.engine) as s:
        u = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == "20333333330")).first()
        uid = u.id

    c = _admin_client("20111111110", "clave-a")
    r = c.post("/admin/usuario/editar", data={"id": uid, "nombre": "Admin Dos Editado"}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        u = s.get(UsuarioSindicato, uid)
        assert u.nombre == "Admin Dos Editado"
        assert u.usuario == "20333333330"  # sin cambios
    print("OK  test_editar_solo_cambia_nombre")


def test_no_puede_editar_ni_dar_de_baja_admin_de_otro_sindicato():
    with Session(db.engine) as s:
        u_b = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == "20222222220")).first()
        uid_b = u_b.id

    c = _admin_client("20111111110", "clave-a")  # admin del sindicato A
    c.post("/admin/usuario/editar", data={"id": uid_b, "nombre": "Hackeado"}, follow_redirects=False)
    c.post("/admin/usuario/baja", data={"id": uid_b}, follow_redirects=False)
    with Session(db.engine) as s:
        u_b = s.get(UsuarioSindicato, uid_b)
        assert u_b.nombre == "Admin B"   # sin cambios
        assert u_b.activo is True        # sin cambios
    print("OK  test_no_puede_editar_ni_dar_de_baja_admin_de_otro_sindicato")


def test_baja_y_reactivar():
    with Session(db.engine) as s:
        u = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == "20333333330")).first()
        uid = u.id

    c = _admin_client("20111111110", "clave-a")
    r = c.post("/admin/usuario/baja", data={"id": uid}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        assert s.get(UsuarioSindicato, uid).activo is False

    r = c.post("/admin/usuario/alta-logica", data={"id": uid}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        assert s.get(UsuarioSindicato, uid).activo is True
    print("OK  test_baja_y_reactivar")


def test_no_se_puede_dar_de_baja_al_ultimo_admin_activo():
    c = _admin_client("20222222220", "clave-b")  # sindicato B: un solo admin activo
    with Session(db.engine) as s:
        u_b = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == "20222222220")).first()
        uid_b = u_b.id

    r = c.post("/admin/usuario/baja", data={"id": uid_b}, follow_redirects=False)
    assert r.status_code == 303
    assert "err=ultimoadmin" in r.headers["location"]
    with Session(db.engine) as s:
        assert s.get(UsuarioSindicato, uid_b).activo is True  # sigue activo
    print("OK  test_no_se_puede_dar_de_baja_al_ultimo_admin_activo")


if __name__ == "__main__":
    test_alta_de_un_segundo_admin_queda_en_el_sindicato_de_la_sesion()
    test_alta_duplicada_en_el_mismo_sindicato_rechaza()
    test_listado_de_admin_no_ve_los_de_otro_sindicato()
    test_editar_solo_cambia_nombre()
    test_no_puede_editar_ni_dar_de_baja_admin_de_otro_sindicato()
    test_baja_y_reactivar()
    test_no_se_puede_dar_de_baja_al_ultimo_admin_activo()
    print("\nTodos los tests de admin_usuarios pasaron.")
