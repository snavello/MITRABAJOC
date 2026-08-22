"""Noticias del sindicato: CRUD de admin, vigencia por fecha, aislamiento
entre sindicatos, y la API de detalle que consume el trabajador.

Correr con: .venv/Scripts/python.exe test_noticias.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, Noticia
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Noticias", slug="uom-noticias", modulos_habilitados=list(MODULOS_INICIALES))
    fega = Sindicato(nombre="Fega Noticias", slug="fega-noticias", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id
    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20111111119", nombre="Juan",
                      activo=True, registrado=True))
    s.commit()

admin_client = TestClient(main.app)
admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})

trab_client = TestClient(main.app)
trab_client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
trab_client.cookies.set("cuil_trab", "20111111119")


def test_vigencia_helper():
    assert db.noticia_vigente({"fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31"}, "2026-06-15")
    assert not db.noticia_vigente({"fecha_desde": "2026-01-01", "fecha_hasta": "2026-03-31"}, "2026-06-15")
    assert not db.noticia_vigente({"fecha_desde": "2026-08-01", "fecha_hasta": "2026-12-31"}, "2026-06-15")
    print("OK  test_vigencia_helper")


def test_alta_noticia_desde_admin():
    r = admin_client.post("/admin/noticia", data={
        "titulo": "Paritaria: nuevo acuerdo salarial", "bajada": "Aumento del 8% en dos tramos",
        "texto_completo": "Más info en https://ejemplo.com/paritaria",
        "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.sindicato_id == SID_UOM)).first()
        assert n is not None
        assert n.titulo == "Paritaria: nuevo acuerdo salarial"
        assert n.creada  # se completó sola
    print("OK  test_alta_noticia_desde_admin")


def test_edicion_noticia():
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.sindicato_id == SID_UOM)).first()
        nid = n.id
    r = admin_client.post("/admin/noticia", data={
        "id": str(nid), "titulo": "Paritaria: acuerdo firmado", "bajada": "Ya está firmado",
        "texto_completo": "Más info en https://ejemplo.com/paritaria",
        "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        n = s.get(Noticia, nid)
        assert n.titulo == "Paritaria: acuerdo firmado"
    print("OK  test_edicion_noticia")


def test_noticia_no_vigente_no_aparece_al_trabajador():
    with db.get_session() as s:
        s.add(Noticia(sindicato_id=SID_UOM, titulo="Vieja, ya venció", fecha_desde="2020-01-01",
                      fecha_hasta="2020-01-31", creada="2020-01-01"))
        s.add(Noticia(sindicato_id=SID_UOM, titulo="Futura, todavía no arrancó",
                      fecha_desde="2099-01-01", fecha_hasta="2099-12-31", creada="2026-01-01"))
        s.commit()
    r = trab_client.get("/app/inicio")
    assert "Vieja, ya venció" not in r.text
    assert "Futura, todavía no arrancó" not in r.text
    assert "Paritaria: acuerdo firmado" in r.text
    print("OK  test_noticia_no_vigente_no_aparece_al_trabajador")


def test_aislamiento_entre_sindicatos():
    with db.get_session() as s:
        s.add(Noticia(sindicato_id=SID_FEGA, titulo="Noticia de Fega, no de UOM",
                      fecha_desde="2020-01-01", fecha_hasta="2030-12-31", creada="2026-01-01"))
        s.commit()
    r = trab_client.get("/app/inicio")
    assert "Noticia de Fega, no de UOM" not in r.text
    print("OK  test_aislamiento_entre_sindicatos")


def test_api_noticia_detalle_linkifica_urls_y_bloquea_otro_sindicato():
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.sindicato_id == SID_UOM,
                                          Noticia.titulo == "Paritaria: acuerdo firmado")).first()
        nid = n.id
        n_fega = s.exec(select(Noticia).where(Noticia.sindicato_id == SID_FEGA)).first()
        nid_fega = n_fega.id

    r = trab_client.get(f"/api/noticia/{nid}")
    assert r.status_code == 200
    body = r.json()
    assert '<a href="https://ejemplo.com/paritaria"' in body["texto_completo_html"]

    r2 = trab_client.get(f"/api/noticia/{nid_fega}")
    assert r2.status_code == 404, "no debe poder ver una noticia de otro sindicato"
    print("OK  test_api_noticia_detalle_linkifica_urls_y_bloquea_otro_sindicato")


def test_admin_no_edita_noticia_de_otro_sindicato():
    with Session(db.engine) as s:
        n_fega = s.exec(select(Noticia).where(Noticia.sindicato_id == SID_FEGA)).first()
        nid_fega = n_fega.id
    admin_client.post("/admin/noticia", data={
        "id": str(nid_fega), "titulo": "Hackeada por admin de UOM", "fecha_desde": "2020-01-01",
        "fecha_hasta": "2030-12-31",
    })
    with Session(db.engine) as s:
        n_fega = s.get(Noticia, nid_fega)
        assert n_fega.titulo != "Hackeada por admin de UOM"
    print("OK  test_admin_no_edita_noticia_de_otro_sindicato")


def test_miniatura_se_ve_en_el_feed_si_tiene_imagen1():
    # Bug real: la imagen se veía bien al abrir el detalle, pero la tarjeta
    # del feed (portada y pestaña Novedades) nunca mostraba una miniatura --
    # faltaba el <img> en el template, aunque tiene_imagen1 ya viajaba en el dict.
    png_1x1 = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a4944415478da6360000002000155"
    )
    admin_client.post("/admin/noticia", data={
        "titulo": "Con miniatura", "bajada": "", "texto_completo": "",
        "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31",
    }, files={"imagen1": ("foto.png", png_1x1, "image/png")})
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.sindicato_id == SID_UOM,
                                          Noticia.titulo == "Con miniatura")).first()
        nid = n.id

    r_portada = trab_client.get("/app/inicio")
    assert f'src="/noticia-imagen/{nid}/1"' in r_portada.text

    r_novedades = trab_client.get("/app?tab=novedades")
    assert f'src="/noticia-imagen/{nid}/1"' in r_novedades.text

    r_img = trab_client.get(f"/noticia-imagen/{nid}/1")
    assert r_img.status_code == 200
    assert r_img.headers["content-type"] == "image/png"
    print("OK  test_miniatura_se_ve_en_el_feed_si_tiene_imagen1")


def test_borrar_noticia():
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.sindicato_id == SID_UOM,
                                          Noticia.titulo == "Vieja, ya venció")).first()
        nid = n.id
    admin_client.post("/admin/noticia/borrar", data={"id": nid})
    with Session(db.engine) as s:
        assert s.get(Noticia, nid) is None
    print("OK  test_borrar_noticia")


if __name__ == "__main__":
    test_vigencia_helper()
    test_alta_noticia_desde_admin()
    test_edicion_noticia()
    test_noticia_no_vigente_no_aparece_al_trabajador()
    test_aislamiento_entre_sindicatos()
    test_api_noticia_detalle_linkifica_urls_y_bloquea_otro_sindicato()
    test_admin_no_edita_noticia_de_otro_sindicato()
    test_miniatura_se_ve_en_el_feed_si_tiene_imagen1()
    test_borrar_noticia()
    print("\nTodo OK — noticias.")
