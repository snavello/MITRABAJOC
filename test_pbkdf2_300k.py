"""PBKDF2 a 300.000 vueltas (decisión de SDN, 2026-11-05) y rehash al próximo
login exitoso: las claves a 600.000 y las legado siguen entrando y quedan
guardadas al costo vigente.

Correr con: python -m pytest test_pbkdf2_300k.py -q
"""
import hashlib

import auth
import db
import main
from db import (CuentaPanel, CuentaTrabajador, Sindicato, Trabajador,
                UsuarioPlataforma, UsuarioSindicato)
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES
from sqlmodel import select


def _hash(clave, iteraciones, sal="sal-de-prueba"):
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), iteraciones)
    return f"sha256${iteraciones}${sal}${dk.hex()}"


def _legado(clave, sal="sal-legado"):
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), 100_000)
    return f"{sal}${dk.hex()}"


def test_hashear_clave_usa_300k():
    assert auth.ITERACIONES == 300_000
    assert auth.hashear_clave("x").startswith("sha256$300000$")


def test_verifica_600k_y_legado_y_marca_rehash():
    h600, hleg = _hash("clave-larga", 600_000), _legado("clave-larga")
    assert auth.verificar_clave("clave-larga", h600)
    assert auth.verificar_clave("clave-larga", hleg)
    assert auth.necesita_rehash(h600)
    assert auth.necesita_rehash(hleg)
    assert not auth.necesita_rehash(auth.hashear_clave("clave-larga"))
    assert auth.necesita_rehash("")


db.crear_tablas()
CUIL_T, CUIL_P = "20111111112", "20111111120"
with db.get_session() as s:
    sind = Sindicato(nombre="Sind Rehash", slug="sind-rehash", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil=CUIL_T, activo=True, registrado=True))
    s.commit()
    cuenta = db.asegurar_cuenta(s, CUIL_T)
    cuenta.clave_hash = _hash("clave-trab", 600_000)
    s.add(cuenta)
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=CUIL_P, nombre="Admin",
                           clave_hash=_hash("clave-panel", 600_000),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioPlataforma(usuario="rehasher", nombre="Rehasher",
                            clave_hash=_hash("clave-plat", 600_000),
                            debe_cambiar_clave=False, debe_completar_datos=False, activo=True))
    s.commit()


def _guardado(modelo, **donde):
    with db.get_session() as s:
        return s.exec(select(modelo).filter_by(**donde)).first().clave_hash


def test_login_trabajador_rehashea():
    assert _guardado(CuentaTrabajador, cuil=CUIL_T).startswith("sha256$600000$")
    r = TestClient(main.app).post("/trabajador/login", data={"cuil": CUIL_T, "clave": "clave-trab"},
                                  follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    h = _guardado(CuentaTrabajador, cuil=CUIL_T)
    assert h.startswith("sha256$300000$") and auth.verificar_clave("clave-trab", h)


def test_login_panel_rehashea():
    assert _guardado(CuentaPanel, cuil=CUIL_P).startswith("sha256$600000$")
    r = TestClient(main.app).post("/admin/login", data={"usuario": CUIL_P, "clave": "clave-panel"},
                                  follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    h = _guardado(CuentaPanel, cuil=CUIL_P)
    assert h.startswith("sha256$300000$") and auth.verificar_clave("clave-panel", h)


def test_login_plataforma_rehashea():
    r = TestClient(main.app).post("/plataforma/login", data={"usuario": "rehasher", "clave": "clave-plat"},
                                  follow_redirects=False)
    assert r.status_code in (200, 303)
    h = _guardado(UsuarioPlataforma, usuario="rehasher")
    assert h.startswith("sha256$300000$") and auth.verificar_clave("clave-plat", h)


def test_clave_mala_no_rehashea():
    TestClient(main.app).post("/trabajador/login", data={"cuil": CUIL_T, "clave": "mala"},
                              follow_redirects=False)
    # la del trabajador ya está a 300k por el test anterior; probamos con el panel recién hecho
    h0 = _guardado(CuentaPanel, cuil=CUIL_P)
    TestClient(main.app).post("/admin/login", data={"usuario": CUIL_P, "clave": "mala"},
                              follow_redirects=False)
    assert _guardado(CuentaPanel, cuil=CUIL_P) == h0
