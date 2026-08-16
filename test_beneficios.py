"""Beneficios del sindicato: CRUD de admin, vigencia por fecha (igual que
Noticia), carrusel en la portada, aislamiento entre sindicatos, y la API de
detalle que consume el trabajador.

Correr con: .venv/Scripts/python.exe test_beneficios.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, Beneficio
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Beneficios", slug="uom-beneficios", modulos_habilitados=list(MODULOS_INICIALES))
    fega = Sindicato(nombre="Fega Beneficios", slug="fega-beneficios", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id
    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False))
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20111111119", nombre="Juan",
                      activo=True, registrado=True))
    s.commit()

admin_client = TestClient(main.app)
admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})

trab_client = TestClient(main.app)
trab_client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
trab_client.cookies.set("cuil_trab", "20111111119")

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a4944415478da6360000002000155"
)


def test_vigencia_helper():
    assert db.beneficio_vigente({"fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31"}, "2026-06-15")
    assert not db.beneficio_vigente({"fecha_desde": "2026-01-01", "fecha_hasta": "2026-03-31"}, "2026-06-15")
    assert not db.beneficio_vigente({"fecha_desde": "2026-08-01", "fecha_hasta": "2026-12-31"}, "2026-06-15")
    print("OK  test_vigencia_helper")


def test_alta_beneficio_desde_admin():
    r = admin_client.post("/admin/beneficio", data={
        "rubro": "Indumentaria", "descripcion": "20% en tienda X. Más info en https://ejemplo.com/desc",
        "link": "https://ejemplo.com/desc",
        "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    }, files={"imagen": ("foto.png", PNG_1X1, "image/png")}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        b = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID_UOM)).first()
        assert b is not None
        assert b.rubro == "Indumentaria"
        assert b.creada  # se completó sola
        assert b.imagen_datos
    print("OK  test_alta_beneficio_desde_admin")


def test_edicion_beneficio():
    with Session(db.engine) as s:
        b = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID_UOM)).first()
        bid = b.id
    r = admin_client.post("/admin/beneficio", data={
        "id": str(bid), "rubro": "Indumentaria (actualizado)", "descripcion": "30% en tienda X",
        "link": "", "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        b = s.get(Beneficio, bid)
        assert b.rubro == "Indumentaria (actualizado)"
    print("OK  test_edicion_beneficio")


def test_beneficio_no_vigente_no_aparece_al_trabajador():
    with db.get_session() as s:
        s.add(Beneficio(sindicato_id=SID_UOM, rubro="Vencido", fecha_desde="2020-01-01",
                        fecha_hasta="2020-01-31", creada="2020-01-01"))
        s.add(Beneficio(sindicato_id=SID_UOM, rubro="Todavía no arrancó",
                        fecha_desde="2099-01-01", fecha_hasta="2099-12-31", creada="2026-01-01"))
        s.commit()
    r = trab_client.get("/app/inicio")
    assert "Vencido" not in r.text
    assert "Todavía no arrancó" not in r.text
    assert "Indumentaria (actualizado)" in r.text
    print("OK  test_beneficio_no_vigente_no_aparece_al_trabajador")


def test_aislamiento_entre_sindicatos():
    with db.get_session() as s:
        s.add(Beneficio(sindicato_id=SID_FEGA, rubro="Beneficio de Fega, no de UOM",
                        fecha_desde="2020-01-01", fecha_hasta="2030-12-31", creada="2026-01-01"))
        s.commit()
    r = trab_client.get("/app/inicio")
    assert "Beneficio de Fega, no de UOM" not in r.text
    print("OK  test_aislamiento_entre_sindicatos")


def test_carrusel_muestra_flechas_solo_con_mas_de_un_vigente():
    r = trab_client.get("/app/inicio")
    assert 'id="carrusel-beneficios"' in r.text
    # Un solo vigente de UOM a esta altura ("Vencido" y "Todavía no arrancó" no lo son) -> sin flechas.
    assert 'carrusel-flecha carrusel-izq' not in r.text

    with db.get_session() as s:
        s.add(Beneficio(sindicato_id=SID_UOM, rubro="Segundo vigente", fecha_desde="2020-01-01",
                        fecha_hasta="2030-12-31", creada="2026-01-01"))
        s.commit()
    r2 = trab_client.get("/app/inicio")
    assert 'carrusel-flecha carrusel-izq' in r2.text  # ahora hay 2 vigentes -> sí hay flechas
    print("OK  test_carrusel_muestra_flechas_solo_con_mas_de_un_vigente")


def test_imagen_del_beneficio_se_sirve():
    with Session(db.engine) as s:
        b = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID_UOM,
                                            Beneficio.rubro == "Indumentaria (actualizado)")).first()
        bid = b.id
    assert f'src="/beneficio-imagen/{bid}"' in trab_client.get("/app/inicio").text
    r_img = trab_client.get(f"/beneficio-imagen/{bid}")
    assert r_img.status_code == 200
    assert r_img.headers["content-type"] == "image/png"
    print("OK  test_imagen_del_beneficio_se_sirve")


def test_api_beneficio_detalle_linkifica_urls_y_bloquea_otro_sindicato():
    with Session(db.engine) as s:
        b = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID_UOM,
                                            Beneficio.rubro == "Indumentaria (actualizado)")).first()
        bid = b.id
        b_fega = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID_FEGA)).first()
        bid_fega = b_fega.id

    r = trab_client.get(f"/api/beneficio/{bid}")
    assert r.status_code == 200
    body = r.json()
    assert body["rubro"] == "Indumentaria (actualizado)"

    r2 = trab_client.get(f"/api/beneficio/{bid_fega}")
    assert r2.status_code == 404, "no debe poder ver un beneficio de otro sindicato"
    print("OK  test_api_beneficio_detalle_linkifica_urls_y_bloquea_otro_sindicato")


def test_admin_no_edita_beneficio_de_otro_sindicato():
    with Session(db.engine) as s:
        b_fega = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID_FEGA)).first()
        bid_fega = b_fega.id
    admin_client.post("/admin/beneficio", data={
        "id": str(bid_fega), "rubro": "Hackeado por admin de UOM", "descripcion": "",
        "link": "", "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    })
    with Session(db.engine) as s:
        b_fega = s.get(Beneficio, bid_fega)
        assert b_fega.rubro != "Hackeado por admin de UOM"
    print("OK  test_admin_no_edita_beneficio_de_otro_sindicato")


def test_borrar_beneficio():
    with Session(db.engine) as s:
        b = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID_UOM,
                                            Beneficio.rubro == "Vencido")).first()
        bid = b.id
    admin_client.post("/admin/beneficio/borrar", data={"id": bid})
    with Session(db.engine) as s:
        assert s.get(Beneficio, bid) is None
    print("OK  test_borrar_beneficio")


if __name__ == "__main__":
    test_vigencia_helper()
    test_alta_beneficio_desde_admin()
    test_edicion_beneficio()
    test_beneficio_no_vigente_no_aparece_al_trabajador()
    test_aislamiento_entre_sindicatos()
    test_carrusel_muestra_flechas_solo_con_mas_de_un_vigente()
    test_imagen_del_beneficio_se_sirve()
    test_api_beneficio_detalle_linkifica_urls_y_bloquea_otro_sindicato()
    test_admin_no_edita_beneficio_de_otro_sindicato()
    test_borrar_beneficio()
    print("\nTodo OK — beneficios.")
