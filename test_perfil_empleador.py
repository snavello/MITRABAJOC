"""Modal de perfil del empleador (nueva portada /empresa/inicio): edición
de datos propios (todo menos el CUIT) y foto de perfil (una por CUIT, no
por sindicato -- ver CuentaEmpleador.foto_datos). Mismo patrón que
test_perfil_trabajador.py.

Correr con: .venv/Scripts/python.exe test_perfil_empleador.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, Empleador, CuentaEmpleador
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Perfil Empleador", slug="test-perfil-empleador",
                      modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Empleador(sindicato_id=SID, cuit="30111222339", razon_social="Constructora A", activo=True))
    s.add(CuentaEmpleador(cuit="30111222339", clave_hash=auth.hashear_clave("demo1234")))
    s.add(Empleador(sindicato_id=SID, cuit="30999888776", razon_social="Metalúrgica B", activo=True))
    s.add(CuentaEmpleador(cuit="30999888776", clave_hash=auth.hashear_clave("demo1234")))
    s.commit()


def _sesion_empleador(cuit):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0))
    c.cookies.set("cuit_emp", cuit)
    return c


def test_actualizar_perfil_no_toca_cuit():
    emp = _sesion_empleador("30111222339")
    r = emp.post("/api/empresa/perfil", data={
        "razon_social": "Constructora A Actualizada", "domicilio": "Av. Rivadavia 1234",
        "provincia": "Santa Fe", "telefono": "3411234567", "mail": "contacto@constructoraa.com",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["razon_social"] == "Constructora A Actualizada"
    perfil = db.perfil_empleador("30111222339", SID)
    assert perfil["razon_social"] == "Constructora A Actualizada"
    assert perfil["cuit"] == "30111222339"  # el CUIT nunca se toca
    assert perfil["domicilio"] == "Av. Rivadavia 1234"
    assert perfil["mail"] == "contacto@constructoraa.com"
    print("OK  test_actualizar_perfil_no_toca_cuit")


def test_razon_social_vacia_rechazada():
    emp = _sesion_empleador("30111222339")
    r = emp.post("/api/empresa/perfil", data={"razon_social": "   "})
    assert r.status_code == 400
    print("OK  test_razon_social_vacia_rechazada")


def test_perfil_requiere_sesion_empleador():
    sin_sesion = TestClient(main.app)
    r = sin_sesion.post("/api/empresa/perfil", data={"razon_social": "Otra"})
    assert r.status_code == 403
    print("OK  test_perfil_requiere_sesion_empleador")


def test_subir_foto_y_servirla():
    emp = _sesion_empleador("30111222339")
    r = emp.post("/api/empresa/perfil/foto", files={"foto": ("f.jpg", b"contenido-fake-jpeg", "image/jpeg")})
    assert r.status_code == 200, r.text
    r2 = emp.get("/perfil-empleador-foto/30111222339")
    assert r2.status_code == 200
    assert r2.content == b"contenido-fake-jpeg"
    assert r2.headers["content-type"] == "image/jpeg"
    print("OK  test_subir_foto_y_servirla")


def test_foto_rechaza_tipo_no_permitido():
    emp = _sesion_empleador("30111222339")
    r = emp.post("/api/empresa/perfil/foto", files={"foto": ("f.txt", b"no es una imagen", "text/plain")})
    assert r.status_code == 400
    print("OK  test_foto_rechaza_tipo_no_permitido")


def test_foto_solo_la_ve_el_dueno():
    emp = _sesion_empleador("30111222339")
    emp.post("/api/empresa/perfil/foto", files={"foto": ("f.jpg", b"foto de la constructora", "image/jpeg")})
    otro = _sesion_empleador("30999888776")
    r = otro.get("/perfil-empleador-foto/30111222339")
    assert r.status_code == 403
    print("OK  test_foto_solo_la_ve_el_dueno")


def test_sin_foto_devuelve_404():
    emp = _sesion_empleador("30999888776")
    r = emp.get("/perfil-empleador-foto/30999888776")
    assert r.status_code == 404
    print("OK  test_sin_foto_devuelve_404")


def test_portada_empresa_muestra_perfil_y_permite_ir_a_las_pestanas():
    emp = _sesion_empleador("30111222339")
    r = emp.get("/empresa/inicio")
    assert r.status_code == 200
    assert "Constructora A" in r.text
    assert "/empresa#notificaciones" in r.text
    assert "/empresa#tramites" in r.text
    print("OK  test_portada_empresa_muestra_perfil_y_permite_ir_a_las_pestanas")


if __name__ == "__main__":
    test_actualizar_perfil_no_toca_cuit()
    test_razon_social_vacia_rechazada()
    test_perfil_requiere_sesion_empleador()
    test_subir_foto_y_servirla()
    test_foto_rechaza_tipo_no_permitido()
    test_foto_solo_la_ve_el_dueno()
    test_sin_foto_devuelve_404()
    test_portada_empresa_muestra_perfil_y_permite_ir_a_las_pestanas()
    print("\nTodo OK — perfil del empleador.")
