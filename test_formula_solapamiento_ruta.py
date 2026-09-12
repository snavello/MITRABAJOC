"""La ruta /admin/formula rechaza altas/ediciones cuya vigencia se superpone
con otra fórmula existente del mismo target.

Correr con: .venv/Scripts/python.exe -m pytest test_formula_solapamiento_ruta.py -q
"""


import db
from db import Sindicato, UsuarioSindicato, Formula
import auth
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Vigencia", slug="test-vigencia", modulos_habilitados=["recibos"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20999999999", nombre="Admin",
                            clave_hash=auth.hashear_clave("test-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

client = TestClient(main.app)
client.post("/admin/login", data={"usuario": "20999999999", "clave": "test-demo"})


def test_alta_normal_sin_fechas_ok():
    r = client.post("/admin/formula", data={
        "target": "JUB", "descripcion": "Jubilación", "expr": "0.11*base_remunerativa",
        "tolerancia": "1.0",
    }, follow_redirects=False)
    assert r.status_code == 303 and "error" not in (r.headers.get("location") or "")
    with Session(db.engine) as s:
        f = s.exec(select(Formula).where(Formula.sindicato_id == SID, Formula.target == "JUB")).first()
        assert f.fecha_desde is None and f.fecha_hasta is None
    print("OK  test_alta_normal_sin_fechas_ok")


def test_segunda_formula_superpuesta_se_rechaza():
    # La primera (sin fechas) cubre TODO el tiempo -> cualquier otra se superpone.
    r = client.post("/admin/formula", data={
        "target": "JUB", "descripcion": "Jubilación vieja", "expr": "0.10*base_remunerativa",
        "tolerancia": "1.0", "fecha_desde": "2010-01-01", "fecha_hasta": "2015-12-31",
    }, follow_redirects=False)
    assert "error=superposicion" in r.headers.get("location", "")
    with Session(db.engine) as s:
        n = len(s.exec(select(Formula).where(Formula.sindicato_id == SID, Formula.target == "JUB")).all())
        assert n == 1, "no debe haber creado la segunda fórmula"
    print("OK  test_segunda_formula_superpuesta_se_rechaza")


def test_formula_sin_superposicion_se_acepta():
    # Cerrar la primera con fecha_hasta para dejar lugar a una posterior.
    with Session(db.engine) as s:
        f = s.exec(select(Formula).where(Formula.sindicato_id == SID, Formula.target == "JUB")).first()
        f.fecha_hasta = "2020-12-31"
        s.add(f); s.commit()
    r = client.post("/admin/formula", data={
        "target": "JUB", "descripcion": "Jubilación nueva", "expr": "0.11*base_remunerativa",
        "tolerancia": "1.0", "fecha_desde": "2021-01-01",
    }, follow_redirects=False)
    assert "error" not in (r.headers.get("location") or "")
    with Session(db.engine) as s:
        n = len(s.exec(select(Formula).where(Formula.sindicato_id == SID, Formula.target == "JUB")).all())
        assert n == 2
    print("OK  test_formula_sin_superposicion_se_acepta")


def test_editar_a_una_superposicion_tambien_se_rechaza():
    # La original ("Jubilación", cerrada en 2020-12-31 por el test anterior):
    # intentar estirarla hasta 2021-06 pisa a "Jubilación nueva" (desde 2021-01).
    with Session(db.engine) as s:
        original = s.exec(select(Formula).where(Formula.sindicato_id == SID,
                           Formula.descripcion == "Jubilación")).first()
        ORIGINAL_ID = original.id
    r = client.post("/admin/formula", data={
        "id": str(ORIGINAL_ID), "target": "JUB", "descripcion": "Jubilación",
        "expr": "0.10*base_remunerativa", "tolerancia": "1.0",
        "fecha_desde": "", "fecha_hasta": "2021-06-30",
    }, follow_redirects=False)
    assert "error=superposicion" in r.headers.get("location", "")
    with Session(db.engine) as s:
        original = s.get(Formula, ORIGINAL_ID)
        assert original.fecha_hasta == "2020-12-31", "no debe haber modificado la fórmula"
    print("OK  test_editar_a_una_superposicion_tambien_se_rechaza")


if __name__ == "__main__":
    test_alta_normal_sin_fechas_ok()
    test_segunda_formula_superpuesta_se_rechaza()
    test_formula_sin_superposicion_se_acepta()
    test_editar_a_una_superposicion_tambien_se_rechaza()
    print("\nTodo OK — /admin/formula rechaza vigencias superpuestas.")
