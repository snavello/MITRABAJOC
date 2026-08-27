"""La ruta /admin/formula prueba la expresión ANTES de guardarla.

Antes no se probaba: una fórmula mal escrita se guardaba sin chistar y recién
fallaba en la pantalla del TRABAJADOR, la primera vez que llegaba un recibo
que trajera ese concepto (una fórmula solo se evalúa si su concepto está en el
recibo). Ahí tumbaba la verificación entera y salía el 500 genérico de la app.

Correr con: DATABASE_URL= .venv/Scripts/python.exe test_formula_expresion_ruta.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, UsuarioSindicato, Formula
import auth
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Expresion", slug="test-expresion")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20999999999", nombre="Admin",
                            clave_hash=auth.hashear_clave("test-demo"), debe_cambiar_clave=False))
    s.commit()

client = TestClient(main.app)
client.post("/admin/login", data={"usuario": "20999999999", "clave": "test-demo"})


def _guardar(expr, target="SIND", descripcion="Cuota sindical"):
    return client.post("/admin/formula", data={
        "target": target, "descripcion": descripcion, "expr": expr, "tolerancia": "1.0",
    }, follow_redirects=False)


def _cuantas():
    with Session(db.engine) as s:
        return len(s.exec(select(Formula).where(Formula.sindicato_id == SID)).all())


def test_expresion_valida_se_guarda():
    r = _guardar("0.015 * base_remunerativa")
    assert r.status_code == 303 and "error" not in (r.headers.get("location") or "")
    assert _cuantas() == 1
    print("OK  test_expresion_valida_se_guarda")


def test_coma_decimal_se_rechaza():
    antes = _cuantas()
    r = _guardar("0,015 * base_remunerativa", target="SIND2")
    destino = r.headers.get("location", "")
    assert "error=formulaexpr" in destino, destino
    assert "coma" in destino.lower(), destino   # el motivo viaja en la URL
    assert _cuantas() == antes, "no debe haber guardado nada"
    print("OK  test_coma_decimal_se_rechaza")


def test_signo_porcentaje_se_rechaza():
    antes = _cuantas()
    assert "error=formulaexpr" in _guardar("1.5% * base_remunerativa", target="SIND3").headers.get("location", "")
    assert _cuantas() == antes
    print("OK  test_signo_porcentaje_se_rechaza")


def test_variable_inexistente_se_rechaza():
    antes = _cuantas()
    destino = _guardar("0.015 * sueldo_bruto", target="SIND4").headers.get("location", "")
    assert "error=formulaexpr" in destino, destino
    assert "sueldo_bruto" in destino, destino   # dice cuál es la variable que no existe
    assert _cuantas() == antes
    print("OK  test_variable_inexistente_se_rechaza")


def test_editar_a_una_expresion_rota_tampoco_pasa():
    with Session(db.engine) as s:
        f = s.exec(select(Formula).where(Formula.sindicato_id == SID)).first()
        fid, expr_original = f.id, f.expr
    r = client.post("/admin/formula", data={
        "id": str(fid), "target": "SIND", "descripcion": "Cuota sindical",
        "expr": "1,5 % base_remunerativa", "tolerancia": "1.0",
    }, follow_redirects=False)
    assert "error=formulaexpr" in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert s.get(Formula, fid).expr == expr_original, "no debe haber tocado la fórmula"
    print("OK  test_editar_a_una_expresion_rota_tampoco_pasa")


if __name__ == "__main__":
    test_expresion_valida_se_guarda()
    test_coma_decimal_se_rechaza()
    test_signo_porcentaje_se_rechaza()
    test_variable_inexistente_se_rechaza()
    test_editar_a_una_expresion_rota_tampoco_pasa()
    print("\nTodo OK — /admin/formula no guarda una expresión que no se puede evaluar.")
