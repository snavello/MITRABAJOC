"""Bug real encontrado con un recibo de AFIP: /api/validar daba de alta un
concepto nuevo detectado (código crudo del empleador, ej. "42-001") pero
nunca lo vinculaba al genérico correspondiente aunque la IA hubiera
identificado la categoría universal (jubilación/PAMI/obra social) y el
sindicato ya tuviera ese genérico cargado — quedaba "huérfano": matcheaba
por código exacto pero la fórmula del genérico nunca lo encontraba (porque
buscaba por su propio código, no por el del genérico).

Correr con: .venv/Scripts/python.exe -m pytest test_autolink_api_validar.py -q
"""


import db
from db import Sindicato, Trabajador, Concepto
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Autolink", slug="test-autolink")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan", activo=True, registrado=True))
    s.commit()
# El genérico JUBILACION ya está cargado (como pasaría con el botón de
# "Cargar aportes de ley", o la autocarga al crear el sindicato).
db.crear_conceptos_universales(SID)

client = TestClient(main.app)
client.cookies.set("cuil_trab", "20111111119")


def _payload():
    return {
        "recibo": {
            "periodo": "2026-08",
            "empleado": {"cuil": "20111111119"},
            "empleador": {"nombre": "AFIP", "cuit": "33-69345023-9"},
            "lineas": [
                {"codigo": "1-026", "descripcion": "Sueldo Basico", "importe": 1000000, "tipo": "remuneracion"},
                {"codigo": "42-001", "descripcion": "AP. PERS. JUB. ANSES", "importe": -110000,
                 "tipo": "aporte_trabajador", "categoria_universal": "jubilacion"},
            ],
            "totales_impresos": {},
        },
        "conceptos_nuevos": [
            {"codigo": "1-026", "descripcion": "Sueldo Basico", "tipo": "ingreso", "importe": 1000000,
             "categoria_universal": None},
            {"codigo": "42-001", "descripcion": "AP. PERS. JUB. ANSES", "tipo": "descuento", "importe": -110000,
             "categoria_universal": "jubilacion"},
        ],
    }


def test_concepto_nuevo_con_categoria_universal_se_vincula_al_generico():
    r = client.post("/api/validar", json=_payload())
    assert r.status_code == 200, r.text

    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "42-001")).first()
        assert c is not None
        assert c.codigo_generico == "JUBILACION", c.codigo_generico

        # El de sueldo, sin categoria_universal, no se vincula a nada.
        sueldo = s.exec(select(Concepto).where(Concepto.sindicato_id == SID, Concepto.codigo == "1-026")).first()
        assert sueldo.codigo_generico is None
    print("OK  test_concepto_nuevo_con_categoria_universal_se_vincula_al_generico")


def test_formula_del_generico_ahora_encuentra_el_importe():
    # Con el vínculo hecho, un recibo NUEVO (mismo empleador) ya no debería
    # dar "concepto_faltante" para JUBILACION: matchea "42-001" -> codigo
    #_generico="JUBILACION" -> la fórmula lo encuentra.
    r = client.post("/api/validar", json=_payload())
    body = r.json()
    codigos_formula = {f["codigo"] for f in body["formulas_validadas"]}
    assert "JUBILACION" in codigos_formula, body
    # El recibo de este test solo trae la línea de jubilación (no PAMI/obra
    # social) — esas SÍ deben quedar como concepto_faltante, es correcto.
    # Lo que probamos es que JUBILACION específicamente ya no lo esté.
    faltantes = {d["codigo"] for d in body["discrepancias"] if d["tipo"] == "concepto_faltante"}
    assert "JUBILACION" not in faltantes, body["discrepancias"]
    print("OK  test_formula_del_generico_ahora_encuentra_el_importe")


def test_no_se_vincula_si_el_sindicato_no_tiene_el_generico_cargado():
    with db.get_session() as s:
        sind2 = Sindicato(nombre="Test Sin Generico", slug="test-sin-generico")
        s.add(sind2); s.commit(); s.refresh(sind2)
        sid2 = sind2.id
        s.add(Trabajador(sindicato_id=sid2, cuil="20222222220", nombre="Ana", activo=True, registrado=True))
        s.commit()
    # OJO: acá NO se llama a crear_conceptos_universales — el sindicato no
    # tiene JUBILACION cargado todavía.
    client2 = TestClient(main.app)
    client2.cookies.set("cuil_trab", "20222222220")
    payload = _payload()
    payload["recibo"]["empleado"]["cuil"] = "20222222220"
    r = client2.post("/api/validar", json=payload)
    assert r.status_code == 200

    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == sid2, Concepto.codigo == "42-001")).first()
        assert c is not None
        assert c.codigo_generico is None, "no hay JUBILACION genérico cargado, no debe inventarse un vínculo"
    print("OK  test_no_se_vincula_si_el_sindicato_no_tiene_el_generico_cargado")


if __name__ == "__main__":
    test_concepto_nuevo_con_categoria_universal_se_vincula_al_generico()
    test_formula_del_generico_ahora_encuentra_el_importe()
    test_no_se_vincula_si_el_sindicato_no_tiene_el_generico_cargado()
    print("\nTodo OK — /api/validar vincula conceptos nuevos al genérico universal.")
