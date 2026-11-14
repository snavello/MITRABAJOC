"""QA de seguridad y lógica de la Mesa de implementación (independiente).

Los tests que hoy FALLAN por un defecto real van marcados con
`xfail(strict=True)`: cuando el defecto se corrija el test pasa y strict lo
avisa (hay que sacar la marca). Informe: docs/implementacion/QA-servidor.md.

Correr con: python -m pytest test_implementacion_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import io
import json
import threading
import time
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

import auth
import db
import entorno
import implementacion as im
import main

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
DEFINITIVA = "definitiva-2026"


@pytest.fixture(autouse=True)
def _sin_freno():
    main._intentos_impl.clear()
    yield
    main._intentos_impl.clear()


def _u(prefijo="x"):
    return f"{prefijo}{uuid.uuid4().hex[:8]}"


def _proyecto(nombre=None):
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, nombre or _u("Proy "), EQ).id


def _cliente_sindicato(pid, nombre="Carla Sindicato", raise_exc=False):
    mail = f"{_u()}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, nombre, mail, "transitoria1", EQ)
        db.impl_usuario_cambiar_clave(s, u.id, "transitoria1", DEFINITIVA)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=raise_exc)
    r = c.post("/implementacion/ingresar", data={"mail": mail, "clave": DEFINITIVA})
    assert r.headers["location"] == "/implementacion", r.headers
    c.uid, c.mail = uid, mail
    return c


def _cliente_equipo(raise_exc=False, **campos):
    usuario = _u("eq")
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario, email=campos.pop("email", ""),
                                 clave_hash=auth.hashear_clave("x" * 12),
                                 debe_cambiar_clave=campos.pop("debe_cambiar_clave", False),
                                 debe_completar_datos=campos.pop("debe_completar_datos", False),
                                 activo=campos.pop("activo", True))
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=raise_exc)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    c.uid = uid
    return c


def _mundo():
    pid = _proyecto()
    return pid, _cliente_equipo(), _cliente_sindicato(pid)


def _api(pid, ruta=""):
    return f"/api/implementacion/p/{pid}/{ruta}".rstrip("/")


def _crear(c, pid, tipo="pedido", titulo="Un título", texto="Un texto", archivos=None, **extra):
    r = c.post(_api(pid, "tarjetas"), data={"tipo": tipo, "titulo": titulo, "texto": texto, **extra},
               files=archivos or None)
    assert r.status_code == 200, r.text
    return r.json()["tarjeta"]


def _resp(c, pid, tid, files=None, **datos):
    return c.post(_api(pid, f"tarjetas/{tid}/responder"), data=datos, files=files)


def _det(c, pid, tid):
    r = c.get(_api(pid, f"tarjetas/{tid}"))
    assert r.status_code == 200, r.text
    return r.json()


def _pdf(nombre="a.pdf", datos=b"%PDF-1.4 x", mime="application/pdf"):
    return [("archivos", (nombre, datos, mime))]


def _id_inexistente():
    return 2_000_000_000
