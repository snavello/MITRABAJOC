"""Rutas: alta de sindicato autocarga los 3 conceptos+fórmulas universales,
y /admin/aprender sugiere el vínculo genérico por categoria_universal.

Correr con: .venv/Scripts/python.exe -m pytest test_universales_rutas.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
from db import Sindicato, Concepto, Formula, UsuarioSindicato
from modulos import MODULOS_INICIALES
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
        "modulos_habilitados": list(MODULOS_INICIALES),
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
                                clave_hash=auth.hashear_clave("clave-test"), debe_cambiar_clave=False, es_super_admin=True))
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
    main.extraer = lambda contenido, content_type: (
        recibo_mock, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 100, "tokens_salida": 50})
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


def test_boton_no_duplica_si_ya_estan_completos():
    # SID ya tiene los 3 desde el alta (test_alta_sindicato_autocarga...) — el
    # cliente ya está logueado como admin de SID desde el test anterior.
    r = client.post("/admin/conceptos-universales", follow_redirects=False)
    assert r.status_code == 303
    assert "universales=nada" in r.headers.get("location", "")
    with Session(db.engine) as s:
        conceptos = s.exec(select(Concepto).where(
            Concepto.sindicato_id == SID, Concepto.codigo.in_(["JUBILACION", "PAMI", "OBRASOCIAL"]))).all()
        formulas = s.exec(select(Formula).where(
            Formula.sindicato_id == SID, Formula.target.in_(["JUBILACION", "PAMI", "OBRASOCIAL"]))).all()
        assert len(conceptos) == 3, "no debe haber duplicado ningún concepto"
        assert len(formulas) == 3, "no debe haber duplicado ninguna fórmula"
    print("OK  test_boton_no_duplica_si_ya_estan_completos")


def test_boton_completa_sindicato_previo_a_la_funcion():
    """Simula un sindicato dado de alta ANTES de que existiera la autocarga:
    se crea sin llamar a crear_conceptos_universales, y el botón lo completa."""
    with Session(db.engine) as s:
        sind = Sindicato(nombre="Sindicato Anterior", slug="sindicato-anterior", modulos_habilitados=["recibos"])
        s.add(sind); s.commit(); s.refresh(sind)
        sid_previo = sind.id
        s.add(UsuarioSindicato(sindicato_id=sid_previo, usuario="20555555550", nombre="Admin Previo",
                                clave_hash=auth.hashear_clave("clave-previa"), debe_cambiar_clave=False, es_super_admin=True))
        s.commit()

    client.post("/admin/login", data={"usuario": "20555555550", "clave": "clave-previa"})
    with Session(db.engine) as s:
        antes = s.exec(select(Concepto).where(Concepto.sindicato_id == sid_previo)).all()
        assert antes == [], "el sindicato 'previo a la función' no debe tener nada todavía"

    r = client.post("/admin/conceptos-universales", follow_redirects=False)
    assert r.status_code == 303
    assert "universales=ok" in r.headers.get("location", "")

    with Session(db.engine) as s:
        conceptos = s.exec(select(Concepto).where(Concepto.sindicato_id == sid_previo)).all()
        formulas = s.exec(select(Formula).where(Formula.sindicato_id == sid_previo)).all()
        assert {c.codigo for c in conceptos} == {"JUBILACION", "PAMI", "OBRASOCIAL"}
        assert {f.target for f in formulas} == {"JUBILACION", "PAMI", "OBRASOCIAL"}
    print("OK  test_boton_completa_sindicato_previo_a_la_funcion")


if __name__ == "__main__":
    test_alta_sindicato_autocarga_3_conceptos_y_formulas()
    test_aprender_sugiere_generico_por_categoria_universal()
    test_aprender_aplicar_con_vinculo_sugerido_persiste_codigo_generico()
    test_boton_no_duplica_si_ya_estan_completos()
    test_boton_completa_sindicato_previo_a_la_funcion()
    print("\nTodo OK — alta de sindicato + Aprendizaje con categorías universales.")
