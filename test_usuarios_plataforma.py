"""Usuarios de plataforma nominales (SPRINT_R1.md, etapa 0): modelo, siembra
de los dos superadmin y funciones de acceso. La suite usa create_all (no la
migración), así que la siembra se prueba llamando a la función idempotente.

Correr con: .venv/Scripts/python.exe -m pytest test_usuarios_plataforma.py -q
"""
import os
os.environ.setdefault("PLATAFORMA_PASSWORD", "x")

import db
import auth
from db import UsuarioPlataforma, LogPlataforma
from sqlmodel import select


def _limpiar():
    with db.get_session() as s:
        for u in s.exec(select(UsuarioPlataforma)).all():
            s.delete(u)
        for l in s.exec(select(LogPlataforma)).all():
            s.delete(l)
        s.commit()


def test_siembra_crea_los_dos_superadmin_y_es_idempotente():
    _limpiar()
    assert db.sembrar_superadmins_iniciales() == 2
    assert db.sembrar_superadmins_iniciales() == 0     # segunda vez no duplica
    snav = db.usuario_plataforma_por_usuario("snavello")
    ars = db.usuario_plataforma_por_usuario("arsantagati")
    for row, clave in ((snav, "snaSandro"), (ars, "arsAlejandro")):
        assert row.rol == "superadmin"
        assert row.activo and row.debe_cambiar_clave and row.debe_completar_datos
        assert row.clave_vence is None                 # las semillas no vencen
        assert row.creado_por == "semilla"
        assert auth.verificar_clave(clave, row.clave_hash)   # clave de un solo uso válida
        assert not auth.verificar_clave("otra", row.clave_hash)
    print("OK  test_siembra_crea_los_dos_superadmin_y_es_idempotente")


def test_lookup_por_usuario_normaliza_y_no_filtra_por_activo():
    _limpiar()
    db.sembrar_superadmins_iniciales()
    # Normaliza espacios y mayúsculas.
    assert db.usuario_plataforma_por_usuario("  SNAVELLO ").usuario == "snavello"
    assert db.usuario_plataforma_por_usuario("") is None
    assert db.usuario_plataforma_por_usuario("nadie") is None
    print("OK  test_lookup_por_usuario_normaliza_y_no_filtra_por_activo")


def test_hay_usuarios_y_conteo_de_superadmins():
    _limpiar()
    assert db.hay_usuarios_plataforma() is False
    assert db.superadmins_activos() == 0
    db.sembrar_superadmins_iniciales()
    assert db.hay_usuarios_plataforma() is True
    assert db.superadmins_activos() == 2
    print("OK  test_hay_usuarios_y_conteo_de_superadmins")


def test_log_plataforma_registra():
    _limpiar()
    db.registrar_log_plataforma("login", "snavello", ip="1.2.3.4")
    db.registrar_log_plataforma("alta", "snavello", objetivo="nuevo", detalle="rol=admin")
    with db.get_session() as s:
        filas = s.exec(select(LogPlataforma)).all()
    assert len(filas) == 2
    login = [f for f in filas if f.accion == "login"][0]
    assert login.usuario == "snavello" and login.ip == "1.2.3.4" and login.cuando
    print("OK  test_log_plataforma_registra")
