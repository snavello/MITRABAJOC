"""Rutas: alta de sindicato autocarga los 3 conceptos+fórmulas universales,
y /admin/aprender sugiere el vínculo genérico por categoria_universal.

Correr con: .venv/Scripts/python.exe test_universales_rutas.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
from db import Sindicato, Concepto, Formula, UsuarioSindicato
import auth
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
client = TestClient(main.app)
client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def test_alta_sindicato_autocarga_3_conceptos_y_formulas():
    r = client.post("/plataforma/sindicato", data={
        "nombre": "Sindicato Test Universales", "descripcion": "", "cuit": "", "direccion": "",
        "mail": "", "telefonos": "", "autoridad": "", "cargo_autoridad": "",
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
    }, follow_redirects=False)
    assert r.status_code == 303

    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Universales")).first()
        assert sind is not None
        conceptos = s.exec(select(Concepto).where(Concepto.sindicato_id == sind.id)).all()
        formulas = s.exec(select(Formula).where(Formula.sindicato_id == sind.id)).all()
        codigos_c = {c.codigo for c in conceptos}
        codigos_f = {f.target for f in formulas}
        assert codigos_c == {"JUBILACION", "PAMI", "OBRASOCIAL"}, codigos_c
        assert codigos_f == {"JUBILACION", "PAMI", "OBRASOCIAL"}, codigos_f
        assert "CUOTA_SINDICAL" not in codigos_c, "la cuota sindical no se autogenera"
        jub = next(f for f in formulas if f.target == "JUBILACION")
        assert jub.expr == "0.11 * base_remunerativa"
        global SID
        SID = sind.id
    print("OK  test_alta_sindicato_autocarga_3_conceptos_y_formulas")


def test_aprender_sugiere_generico_por_categoria_universal():
    """Prueba la ruta /admin/aprender de punta a punta, mockeando extraer()
    (igual que test_extractor_bi_formato.py) para no depender de la API real."""
    with Session(db.engine) as s:
        s.add(UsuarioSindicato(sindicato_id=SID, usuario="20333333330", nombre="Admin",
                                clave_hash=auth.hashear_clave("clave-test"), debe_cambiar_clave=False))
        s.commit()
    client.post("/admin/login", data={"usuario": "20333333330", "clave": "clave-test"})

    recibo_mock = {
        "periodo": "2026-08", "empleado": {"cuil": "20111111119"},
        "empleador": {"nombre": "Empleador Nuevo SA", "cuit": "30111222339"},
        "lineas": [
            {"codigo": "AB12", "descripcion": "Retención previsional Art.11", "importe": -110000,
             "tipo": "aporte_trabajador", "categoria_universal": "jubilacion"},
        ],
        "totales_impresos": {}, "contribuciones_patronales": [], "confianza": "alta",
    }
    original = main.extraer
    main.extraer = lambda contenido, content_type: recibo_mock
    try:
        r = client.post("/admin/aprender", files={"archivos": ("recibo.png", b"fake", "image/png")})
    finally:
        main.extraer = original

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["leidos"] == 1
    propuestas = data["propuestas"]
    assert len(propuestas) == 1
    p = propuestas[0]
    assert p["categoria_universal"] == "jubilacion"
    assert p["generico_sugerido"] == {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)"}
    print("OK  test_aprender_sugiere_generico_por_categoria_universal")


def test_aprender_aplicar_con_vinculo_sugerido_persiste_codigo_generico():
    r = client.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "AB12", "descripcion": "Retención previsional Art.11", "tipo": "descuento",
         "remunerativo": True, "cuit_empleador": "30111222339", "codigo_generico": "JUBILACION"},
    ]})
    assert r.status_code == 200 and r.json()["altas"] == 1
    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "AB12")).first()
        assert c.codigo_generico == "JUBILACION"
        assert c.cuit_empleador == "30111222339"
    print("OK  test_aprender_aplicar_con_vinculo_sugerido_persiste_codigo_generico")


if __name__ == "__main__":
    test_alta_sindicato_autocarga_3_conceptos_y_formulas()
    test_aprender_sugiere_generico_por_categoria_universal()
    test_aprender_aplicar_con_vinculo_sugerido_persiste_codigo_generico()
    print("\nTodo OK — alta de sindicato + Aprendizaje con categorías universales.")
