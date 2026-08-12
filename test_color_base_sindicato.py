"""4to color de marca (color_base): fondo oscuro de la portada del trabajador
y de los encabezados. A diferencia de primario/secundario/acento, este tiene
que validarse como oscuro -- si no, el texto blanco encima deja de leerse.

Correr con: .venv/Scripts/python.exe test_color_base_sindicato.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import main
from main import _es_oscuro
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)
client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def _payload(**overrides):
    base = {
        "nombre": "Sindicato Test", "color_primario": "#152238",
        "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
        "color_base": "#0f1b2d",
    }
    base.update(overrides)
    return base


def test_es_oscuro_helper():
    assert _es_oscuro("#0f1b2d") is True
    assert _es_oscuro("#000000") is True
    assert _es_oscuro("#ffffff") is False
    assert _es_oscuro("#e8a33d") is False  # ámbar, claro -- no sirve como base
    assert _es_oscuro("") is False
    assert _es_oscuro("no-es-un-color") is False
    print("OK  test_es_oscuro_helper")


def test_alta_sindicato_guarda_color_base_oscuro():
    r = client.post("/plataforma/sindicato", data=_payload(nombre="UOM Test", color_base="#0f1b2d"),
                     follow_redirects=False)
    assert r.status_code == 303
    assert "error" not in r.headers.get("location", "")
    m = db.marca_sindicato(_id_de("UOM Test"))
    assert m["color_base"] == "#0f1b2d"
    print("OK  test_alta_sindicato_guarda_color_base_oscuro")


def test_alta_sindicato_rechaza_color_base_claro():
    r = client.post("/plataforma/sindicato", data=_payload(nombre="Claro Test", color_base="#f5e6c8"),
                     follow_redirects=False)
    assert r.status_code == 303
    assert "error=colorbase" in r.headers.get("location", "")
    # No se creó el sindicato con ese color -- no debe existir en absoluto.
    with db.get_session() as s:
        from sqlmodel import select
        from db import Sindicato
        existe = s.exec(select(Sindicato).where(Sindicato.nombre == "Claro Test")).first()
        assert existe is None
    print("OK  test_alta_sindicato_rechaza_color_base_claro")


def test_editar_sindicato_rechaza_color_base_claro():
    client.post("/plataforma/sindicato", data=_payload(nombre="Editable Test", color_base="#0f1b2d"))
    sid = _id_de("Editable Test")
    r = client.post("/plataforma/sindicato/editar", data={
        **_payload(nombre="Editable Test", color_base="#ffffff"), "id": sid,
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error=colorbase" in r.headers.get("location", "")
    m = db.marca_sindicato(sid)
    assert m["color_base"] == "#0f1b2d", "no debe haberse pisado con el color claro rechazado"
    print("OK  test_editar_sindicato_rechaza_color_base_claro")


def test_editar_sindicato_guarda_color_base_oscuro_nuevo():
    client.post("/plataforma/sindicato", data=_payload(nombre="Editable OK Test", color_base="#0f1b2d"))
    sid = _id_de("Editable OK Test")
    r = client.post("/plataforma/sindicato/editar", data={
        **_payload(nombre="Editable OK Test", color_base="#12241a"), "id": sid,
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error" not in r.headers.get("location", "")
    m = db.marca_sindicato(sid)
    assert m["color_base"] == "#12241a"
    print("OK  test_editar_sindicato_guarda_color_base_oscuro_nuevo")


def _id_de(nombre: str) -> int:
    with db.get_session() as s:
        from sqlmodel import select
        from db import Sindicato
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == nombre)).first()
        return sind.id


if __name__ == "__main__":
    test_es_oscuro_helper()
    test_alta_sindicato_guarda_color_base_oscuro()
    test_alta_sindicato_rechaza_color_base_claro()
    test_editar_sindicato_rechaza_color_base_claro()
    test_editar_sindicato_guarda_color_base_oscuro_nuevo()
    print("\nTodo OK — color_base (4to color de marca) validado como oscuro.")
