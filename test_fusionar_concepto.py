"""Fusión de un concepto provisorio con el concepto real del que es duplicado.

Lo importante: además de mover el alias, tiene que REPUNTAR las fórmulas que
apuntaban al código provisorio. Si no, quedan huérfanas y no matchean nunca —
exactamente el bug que tenía AEFIP con los targets de texto libre.

Usa un SQLite temporal. Correr con: .venv/Scripts/python.exe test_fusionar_concepto.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, Concepto, Formula, UsuarioSindicato
import auth
import main
from fastapi.testclient import TestClient
from sqlmodel import select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test")
    s.add(sind)
    s.commit()
    s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110",
                           clave_hash=auth.hashear_clave("clave"), debe_cambiar_clave=False))
    real = Concepto(sindicato_id=SID, codigo="795-019", nombre="COMP. P/DEDICACION ESPECIAL",
                    tipo="ingreso", alias=["COMP. P/DEDICACION ESPECIAL"])
    prov = Concepto(sindicato_id=SID, codigo="NUEVO-COMP.P/DEDIC",
                    nombre="COMP.P/DEDICACION ESPECIAL (línea extra)",
                    tipo="ingreso", alias=[], pendiente_revision=True)
    s.add(real); s.add(prov)
    s.commit()
    s.refresh(real); s.refresh(prov)
    ID_REAL, ID_PROV = real.id, prov.id
    s.add(Formula(sindicato_id=SID, target="NUEVO-COMP.P/DEDIC",
                  descripcion="apunta al provisorio", expr="0.01 * base_remunerativa"))
    s.commit()

client = TestClient(main.app)
client.cookies.set(main.COOKIE_SINDICATO, auth.crear_sesion("sindicato", sindicato_id=SID))


def test_fusion_mueve_alias_repunta_formula_y_borra_provisorio():
    r = client.post("/admin/concepto/fusionar",
                    data={"id": ID_PROV, "destino_id": ID_REAL}, follow_redirects=False)
    assert r.status_code == 303, r.text

    with db.get_session() as s:
        assert s.get(Concepto, ID_PROV) is None, "el provisorio debía borrarse"
        destino = s.get(Concepto, ID_REAL)
        assert "COMP.P/DEDICACION ESPECIAL (línea extra)" in destino.alias, destino.alias
        f = s.exec(select(Formula)).first()
        assert f.target == "795-019", f"la fórmula quedó huérfana: target={f.target}"
    print("OK  test_fusion_mueve_alias_repunta_formula_y_borra_provisorio")


def test_no_fusiona_conceptos_de_otro_sindicato():
    with db.get_session() as s:
        otro = Sindicato(nombre="Otro")
        s.add(otro); s.commit(); s.refresh(otro)
        ajeno = Concepto(sindicato_id=otro.id, codigo="AJENO", nombre="De otro sindicato", tipo="ingreso")
        propio = Concepto(sindicato_id=SID, codigo="NUEVO-PROPIO", nombre="Propio", tipo="ingreso")
        s.add(ajeno); s.add(propio); s.commit()
        s.refresh(ajeno); s.refresh(propio)
        id_ajeno, id_propio = ajeno.id, propio.id

    r = client.post("/admin/concepto/fusionar",
                    data={"id": id_propio, "destino_id": id_ajeno}, follow_redirects=False)
    assert r.status_code == 303
    with db.get_session() as s:
        assert s.get(Concepto, id_propio) is not None, "no debía tocar nada entre sindicatos"
        assert s.get(Concepto, id_ajeno) is not None
    print("OK  test_no_fusiona_conceptos_de_otro_sindicato")


if __name__ == "__main__":
    test_fusion_mueve_alias_repunta_formula_y_borra_provisorio()
    test_no_fusiona_conceptos_de_otro_sindicato()
    print("\nTodo OK — fusión de conceptos duplicados.")
