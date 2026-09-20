"""Destino por seccional en Noticias y Beneficios: por default van a "todas"
las seccionales (lista vacía); si se targetea a una o varias, solo las ve el
trabajador que tenga esa seccional asignada -- uno sin seccional NO ve
contenido dirigido a seccionales específicas.

Correr con: .venv/Scripts/python.exe -m pytest test_destino_seccionales.py -q
"""


import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, Seccional, Noticia, Beneficio
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Destino", slug="uom-destino", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(uom); s.commit(); s.refresh(uom)
    SID = uom.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    norte = Seccional(sindicato_id=SID, nombre="Norte")
    sur = Seccional(sindicato_id=SID, nombre="Sur")
    s.add(norte); s.add(sur); s.commit(); s.refresh(norte); s.refresh(sur)
    SEC_NORTE, SEC_SUR = norte.id, sur.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Con Norte",
                      activo=True, registrado=True, seccional_id=SEC_NORTE))
    s.add(Trabajador(sindicato_id=SID, cuil="27222222224", nombre="Sin seccional",
                      activo=True, registrado=True, seccional_id=None))
    s.commit()

admin_client = TestClient(main.app)
admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})

trab_norte = TestClient(main.app)
trab_norte.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident="20111111119"))
trab_norte.cookies.set("cuil_trab", "20111111119")

trab_sin_seccional = TestClient(main.app)
trab_sin_seccional.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident="27222222224"))
trab_sin_seccional.cookies.set("cuil_trab", "27222222224")


def test_visible_para_seccional_helper():
    assert db.visible_para_seccional([], None)       # sin destino = todas, incluso sin seccional
    assert db.visible_para_seccional([], 5)
    assert db.visible_para_seccional([5, 6], 5)
    assert not db.visible_para_seccional([5, 6], 7)
    assert not db.visible_para_seccional([5, 6], None)  # dirigido a seccionales, sin seccional no lo ve
    print("OK  test_visible_para_seccional_helper")


def test_noticia_sin_destino_es_para_todas():
    admin_client.post("/admin/noticia", data={
        "titulo": "Para todas", "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    })
    r1 = trab_norte.get("/app/inicio")
    r2 = trab_sin_seccional.get("/app/inicio")
    assert "Para todas" in r1.text
    assert "Para todas" in r2.text
    print("OK  test_noticia_sin_destino_es_para_todas")


def test_noticia_dirigida_a_una_seccional():
    admin_client.post("/admin/noticia", data={
        "titulo": "Solo para Norte", "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
        "destino_seccionales": [str(SEC_NORTE)],
    })
    r_norte = trab_norte.get("/app/inicio")
    r_sin = trab_sin_seccional.get("/app/inicio")
    assert "Solo para Norte" in r_norte.text
    assert "Solo para Norte" not in r_sin.text
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.titulo == "Solo para Norte")).first()
        assert n.destino_seccionales == [SEC_NORTE]
    print("OK  test_noticia_dirigida_a_una_seccional")


def test_beneficio_dirigido_a_una_seccional():
    admin_client.post("/admin/beneficio", data={
        "rubro": "Solo Sur", "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
        "destino_seccionales": [str(SEC_SUR)],
    })
    admin_client.post("/admin/beneficio", data={
        "rubro": "Para todos", "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    })
    r_norte = trab_norte.get("/app/inicio")
    assert "Solo Sur" not in r_norte.text
    assert "Para todos" in r_norte.text
    with Session(db.engine) as s:
        b = s.exec(select(Beneficio).where(Beneficio.rubro == "Solo Sur")).first()
        assert b.destino_seccionales == [SEC_SUR]
    print("OK  test_beneficio_dirigido_a_una_seccional")


def test_no_se_puede_targetear_seccional_de_otro_sindicato():
    with db.get_session() as s:
        otro = Sindicato(nombre="Otro sindicato", slug="otro-destino")
        s.add(otro); s.commit(); s.refresh(otro)
        sec_ajena = Seccional(sindicato_id=otro.id, nombre="Ajena")
        s.add(sec_ajena); s.commit(); s.refresh(sec_ajena)
        sec_ajena_id = sec_ajena.id

    admin_client.post("/admin/noticia", data={
        "titulo": "Con seccional ajena", "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
        "destino_seccionales": [str(sec_ajena_id)],
    })
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.titulo == "Con seccional ajena")).first()
        assert n.destino_seccionales == [], "una seccional de otro sindicato no debe persistirse"
    print("OK  test_no_se_puede_targetear_seccional_de_otro_sindicato")


if __name__ == "__main__":
    test_visible_para_seccional_helper()
    test_noticia_sin_destino_es_para_todas()
    test_noticia_dirigida_a_una_seccional()
    test_beneficio_dirigido_a_una_seccional()
    test_no_se_puede_targetear_seccional_de_otro_sindicato()
    print("\nTodo OK — destino por seccional.")
