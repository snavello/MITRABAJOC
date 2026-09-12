"""Botón "Confirmar" de un concepto pendiente de revisión: antes solo se
podía sacar la marca como efecto secundario de editar y guardar (poco
evidente en la UI); ahora hay una acción dedicada que no toca los demás
datos del concepto.

Correr con: .venv/Scripts/python.exe -m pytest test_confirmar_concepto.py -q
"""


import db
import auth
from db import Sindicato, UsuarioSindicato, Concepto
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Confirmar", slug="uom-confirmar", modulos_habilitados=["recibos"])
    fega = Sindicato(nombre="Fega Confirmar", slug="fega-confirmar", modulos_habilitados=["recibos"])
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id
    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Concepto(sindicato_id=SID_UOM, codigo="X1", nombre="Nuevo concepto", tipo="ingreso",
                    remunerativo=True, alias=["Nuevo concepto"], pendiente_revision=True))
    s.add(Concepto(sindicato_id=SID_FEGA, codigo="Y1", nombre="Concepto de Fega", tipo="ingreso",
                    remunerativo=True, alias=["Concepto de Fega"], pendiente_revision=True))
    s.commit()

admin_client = TestClient(main.app)
admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})


def test_confirmar_limpia_la_marca_sin_tocar_los_demas_datos():
    with Session(db.engine) as s:
        c = s.exec(select(Concepto).where(Concepto.sindicato_id == SID_UOM)).first()
        cid, nombre_antes, codigo_antes = c.id, c.nombre, c.codigo

    r = admin_client.post("/admin/concepto/confirmar", data={"id": cid}, follow_redirects=False)
    assert r.status_code == 303

    with Session(db.engine) as s:
        c = s.get(Concepto, cid)
        assert c.pendiente_revision is False
        assert c.nombre == nombre_antes
        assert c.codigo == codigo_antes
    print("OK  test_confirmar_limpia_la_marca_sin_tocar_los_demas_datos")


def test_admin_no_confirma_concepto_de_otro_sindicato():
    with Session(db.engine) as s:
        c_fega = s.exec(select(Concepto).where(Concepto.sindicato_id == SID_FEGA)).first()
        cid_fega = c_fega.id

    admin_client.post("/admin/concepto/confirmar", data={"id": cid_fega})

    with Session(db.engine) as s:
        c_fega = s.get(Concepto, cid_fega)
        assert c_fega.pendiente_revision is True, "no debe poder confirmar un concepto de otro sindicato"
    print("OK  test_admin_no_confirma_concepto_de_otro_sindicato")


if __name__ == "__main__":
    test_confirmar_limpia_la_marca_sin_tocar_los_demas_datos()
    test_admin_no_confirma_concepto_de_otro_sindicato()
    print("\nTodo OK — confirmar concepto.")
