"""Modal de perfil del trabajador: edición de datos propios (todo menos el
CUIL) y foto de perfil (una por CUIL, no por sindicato -- ver
CuentaTrabajador.foto_datos). El achicado a baja resolución lo hace el
cliente (canvas); el servidor solo valida tipo/tamaño y guarda tal cual.

Correr con: .venv/Scripts/python.exe test_perfil_trabajador.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, Trabajador, CuentaTrabajador, UsuarioSindicato
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Perfil", slug="test-perfil")
    otro_sind = Sindicato(nombre="Test Perfil Otro", slug="test-perfil-otro")
    s.add(sind); s.add(otro_sind); s.commit(); s.refresh(sind); s.refresh(otro_sind)
    SID = sind.id
    SID_OTRO = otro_sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan", activo=True, registrado=True))
    s.add(CuentaTrabajador(cuil="20111111119", clave_hash=auth.hashear_clave("demo1234")))
    s.add(Trabajador(sindicato_id=SID, cuil="20444444440", nombre="Ana", activo=True, registrado=True))
    s.add(CuentaTrabajador(cuil="20444444440", clave_hash=auth.hashear_clave("demo1234")))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20777777770", nombre="Admin Test Perfil",
                            clave_hash=auth.hashear_clave("admin-demo"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_OTRO, usuario="20888888880", nombre="Admin Otro",
                            clave_hash=auth.hashear_clave("admin-demo"), debe_cambiar_clave=False))
    s.commit()


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


def _sesion_admin(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def test_actualizar_perfil_no_toca_cuil():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/perfil", data={
        "nombre": "Juan Pérez", "calle": "Av. Rivadavia", "numero": "1234", "piso": "",
        "ciudad": "CABA", "provincia": "Ciudad Autónoma de Buenos Aires",
        "telefono": "1122334455", "mail": "juan@example.com",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["nombre"] == "Juan Pérez"
    assert data["primer_nombre"] == "Juan"
    perfil = db.perfil_trabajador("20111111119", SID)
    assert perfil["nombre"] == "Juan Pérez"
    assert perfil["cuil"] == "20111111119"  # el CUIL nunca se toca
    assert perfil["calle"] == "Av. Rivadavia"
    assert perfil["mail"] == "juan@example.com"
    print("OK  test_actualizar_perfil_no_toca_cuil")


def test_nombre_vacio_rechazado():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/perfil", data={"nombre": "   "})
    assert r.status_code == 400
    print("OK  test_nombre_vacio_rechazado")


def test_perfil_requiere_sesion_trabajador():
    sin_sesion = TestClient(main.app)
    r = sin_sesion.post("/api/perfil", data={"nombre": "Otro"})
    assert r.status_code == 403
    print("OK  test_perfil_requiere_sesion_trabajador")


def test_subir_foto_y_servirla():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/perfil/foto", files={"foto": ("f.jpg", b"contenido-fake-jpeg", "image/jpeg")})
    assert r.status_code == 200, r.text
    r2 = trab.get("/perfil-foto/20111111119")
    assert r2.status_code == 200
    assert r2.content == b"contenido-fake-jpeg"
    assert r2.headers["content-type"] == "image/jpeg"
    print("OK  test_subir_foto_y_servirla")


def test_foto_rechaza_tipo_no_permitido():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/perfil/foto", files={"foto": ("f.txt", b"no es una imagen", "text/plain")})
    assert r.status_code == 400
    print("OK  test_foto_rechaza_tipo_no_permitido")


def test_foto_solo_la_ve_el_dueno():
    trab = _sesion_trabajador("20111111119")
    trab.post("/api/perfil/foto", files={"foto": ("f.jpg", b"foto de juan", "image/jpeg")})
    otro = _sesion_trabajador("20444444440")
    r = otro.get("/perfil-foto/20111111119")
    assert r.status_code == 403
    print("OK  test_foto_solo_la_ve_el_dueno")


def test_sin_foto_devuelve_404():
    trab = _sesion_trabajador("20444444440")
    r = trab.get("/perfil-foto/20444444440")
    assert r.status_code == 404
    print("OK  test_sin_foto_devuelve_404")


def test_admin_del_sindicato_puede_ver_la_foto_para_el_chat_de_tramites():
    trab = _sesion_trabajador("20111111119")
    trab.post("/api/perfil/foto", files={"foto": ("f.jpg", b"foto de juan para admin", "image/jpeg")})
    admin = _sesion_admin("20777777770", "admin-demo")
    r = admin.get("/perfil-foto/20111111119")
    assert r.status_code == 200
    assert r.content == b"foto de juan para admin"
    print("OK  test_admin_del_sindicato_puede_ver_la_foto_para_el_chat_de_tramites")


def test_admin_de_otro_sindicato_no_puede_ver_la_foto():
    trab = _sesion_trabajador("20111111119")
    trab.post("/api/perfil/foto", files={"foto": ("f.jpg", b"foto privada", "image/jpeg")})
    admin_ajeno = _sesion_admin("20888888880", "admin-demo")
    r = admin_ajeno.get("/perfil-foto/20111111119")
    assert r.status_code == 403
    print("OK  test_admin_de_otro_sindicato_no_puede_ver_la_foto")


if __name__ == "__main__":
    test_actualizar_perfil_no_toca_cuil()
    test_nombre_vacio_rechazado()
    test_perfil_requiere_sesion_trabajador()
    test_subir_foto_y_servirla()
    test_foto_rechaza_tipo_no_permitido()
    test_foto_solo_la_ve_el_dueno()
    test_sin_foto_devuelve_404()
    test_admin_del_sindicato_puede_ver_la_foto_para_el_chat_de_tramites()
    test_admin_de_otro_sindicato_no_puede_ver_la_foto()
    print("\nTodo OK — perfil del trabajador.")
