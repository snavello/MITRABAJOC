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


# ================= Etapa 1: login nominal + primer ingreso forzado =================
os.environ.setdefault("PLATAFORMA_CUIT", "20000000000")
os.environ["PLATAFORMA_PASSWORD"] = "generico-test"

import main
from fastapi.testclient import TestClient


def _cli():
    return TestClient(main.app)


def test_login_nominal_manda_a_completar_en_el_primer_ingreso():
    _limpiar()
    db.sembrar_superadmins_iniciales()
    c = _cli()
    r = c.post("/plataforma/login", data={"usuario": "snavello", "clave": "snaSandro"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/plataforma/completar"
    assert c.cookies.get(main.COOKIE_PLATAFORMA)
    # queda registrado el login
    from db import LogPlataforma
    with db.get_session() as s:
        assert any(l.accion == "login" and l.usuario == "snavello"
                   for l in s.exec(select(LogPlataforma)).all())
    # y el panel lo empuja a completar
    r2 = c.get("/plataforma/inicio", follow_redirects=False)
    assert r2.status_code == 303 and r2.headers["location"] == "/plataforma/completar"
    print("OK  test_login_nominal_manda_a_completar_en_el_primer_ingreso")


def test_completar_cuenta_exitoso_habilita_el_panel():
    _limpiar()
    db.sembrar_superadmins_iniciales()
    c = _cli()
    c.post("/plataforma/login", data={"usuario": "snavello", "clave": "snaSandro"})
    r = c.post("/plataforma/completar", data={
        "clave_nueva": "claveLarga2026", "clave_repetir": "claveLarga2026",
        "cuil": "20-31000111-3", "dni": "31000111", "email": "san@colmena.ar",
        "direccion": "Calle 1 234", "telefono": "3411234567"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/plataforma/inicio"
    u = db.usuario_plataforma_por_usuario("snavello")
    assert not u.debe_cambiar_clave and not u.debe_completar_datos
    assert u.cuil == "20310001113" and u.email == "san@colmena.ar"
    assert auth.verificar_clave("claveLarga2026", u.clave_hash)
    # ya entra directo al panel
    c2 = _cli()
    r2 = c2.post("/plataforma/login", data={"usuario": "snavello", "clave": "claveLarga2026"},
                 follow_redirects=False)
    assert r2.headers["location"] == "/plataforma/inicio"
    print("OK  test_completar_cuenta_exitoso_habilita_el_panel")


def test_completar_rechaza_datos_invalidos():
    _limpiar()
    db.sembrar_superadmins_iniciales()
    base = {"clave_nueva": "claveLarga2026", "clave_repetir": "claveLarga2026",
            "cuil": "20310001113", "dni": "31000111", "email": "a@b.com",
            "direccion": "x", "telefono": "1"}
    casos = [
        ({"clave_nueva": "corta1", "clave_repetir": "corta1"}, "10 caracteres"),
        ({"clave_repetir": "otradistinta9"}, "no coinciden"),
        ({"cuil": "123"}, "11 dígitos"),
        ({"email": "no-es-mail"}, "formato válido"),
        ({"dni": ""}, "DNI"),
        ({"direccion": ""}, "dirección"),
        ({"telefono": ""}, "teléfono"),
    ]
    for parche, texto in casos:
        c = _cli()
        c.post("/plataforma/login", data={"usuario": "snavello", "clave": "snaSandro"})
        r = c.post("/plataforma/completar", data={**base, **parche})
        assert r.status_code == 400 and texto in r.text, f"{parche} -> {texto}"
        # no se completó
        assert db.usuario_plataforma_por_usuario("snavello").debe_completar_datos
    print("OK  test_completar_rechaza_datos_invalidos")


def test_email_duplicado_se_rechaza():
    _limpiar()
    db.sembrar_superadmins_iniciales()
    # snavello completa con un mail
    c = _cli(); c.post("/plataforma/login", data={"usuario": "snavello", "clave": "snaSandro"})
    c.post("/plataforma/completar", data={
        "clave_nueva": "claveLarga2026", "clave_repetir": "claveLarga2026",
        "cuil": "20310001113", "dni": "31000111", "email": "compartido@colmena.ar",
        "direccion": "x", "telefono": "1"})
    # arsantagati intenta el mismo mail
    c2 = _cli(); c2.post("/plataforma/login", data={"usuario": "arsantagati", "clave": "arsAlejandro"})
    r = c2.post("/plataforma/completar", data={
        "clave_nueva": "otraClave2026", "clave_repetir": "otraClave2026",
        "cuil": "20320002224", "dni": "32000222", "email": "compartido@colmena.ar",
        "direccion": "y", "telefono": "2"})
    assert r.status_code == 400 and "ya está en uso" in r.text
    print("OK  test_email_duplicado_se_rechaza")


def test_login_generico_sigue_andando_en_transicion(monkeypatch):
    _limpiar()
    monkeypatch.setattr(auth, "CLAVE_PLATAFORMA", "generico-test")
    monkeypatch.setattr(auth, "CUIT_PLATAFORMA", "20000000000")
    c = _cli()
    r = c.post("/plataforma/login", data={"cuit": "20000000000", "clave": "generico-test"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/plataforma/inicio"
    print("OK  test_login_generico_sigue_andando_en_transicion")


def test_clave_transitoria_vencida_no_deja_entrar():
    _limpiar()
    from db import UsuarioPlataforma
    with db.get_session() as s:
        s.add(UsuarioPlataforma(usuario="vencido", nombre="V",
              clave_hash=auth.hashear_clave("transitoria1"), rol="admin",
              debe_cambiar_clave=True, clave_vence="2000-01-01 00:00",
              debe_completar_datos=True, creado_por="test"))
        s.commit()
    c = _cli()
    r = c.post("/plataforma/login", data={"usuario": "vencido", "clave": "transitoria1"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/plataforma?error=vencida"
    assert not c.cookies.get(main.COOKIE_PLATAFORMA)
    print("OK  test_clave_transitoria_vencida_no_deja_entrar")


def test_usuario_inactivo_no_entra():
    _limpiar()
    from db import UsuarioPlataforma
    with db.get_session() as s:
        s.add(UsuarioPlataforma(usuario="baja", nombre="B",
              clave_hash=auth.hashear_clave("claveLarga2026"), rol="admin",
              activo=False, debe_cambiar_clave=False, debe_completar_datos=False,
              creado_por="test"))
        s.commit()
    c = _cli()
    r = c.post("/plataforma/login", data={"usuario": "baja", "clave": "claveLarga2026"},
               follow_redirects=False)
    assert r.headers["location"] == "/plataforma?error=1"
    print("OK  test_usuario_inactivo_no_entra")


def test_clave_nueva_no_puede_ser_la_transitoria():
    _limpiar()
    from db import UsuarioPlataforma
    with db.get_session() as s:
        s.add(UsuarioPlataforma(usuario="largo", nombre="L",
              clave_hash=auth.hashear_clave("transitoria10"), rol="admin",
              debe_cambiar_clave=True, debe_completar_datos=True, creado_por="test"))
        s.commit()
    c = _cli()
    c.post("/plataforma/login", data={"usuario": "largo", "clave": "transitoria10"})
    r = c.post("/plataforma/completar", data={
        "clave_nueva": "transitoria10", "clave_repetir": "transitoria10",
        "cuil": "20310001113", "dni": "31000111", "email": "l@c.ar",
        "direccion": "x", "telefono": "1"})
    assert r.status_code == 400 and "distinta de la transitoria" in r.text
    print("OK  test_clave_nueva_no_puede_ser_la_transitoria")


# ================= Etapa 3: gestión de usuarios (solo superadmin) =================
from db import UsuarioPlataforma as _UP


def _superadmin_completo(usuario="jefe", clave="ClaveJefe2026", rol="superadmin"):
    """Crea un usuario de plataforma YA completo (no pendiente) y devuelve un
    cliente logueado como él."""
    with db.get_session() as s:
        s.add(_UP(usuario=usuario, nombre=usuario.title(), clave_hash=auth.hashear_clave(clave),
                  rol=rol, activo=True, debe_cambiar_clave=False, debe_completar_datos=False,
                  cuil="20999999990", email=f"{usuario}@c.ar", creado_por="test"))
        s.commit()
    c = _cli()
    c.post("/plataforma/login", data={"usuario": usuario, "clave": clave})
    return c


def test_superadmin_crea_usuario_con_clave_transitoria():
    _limpiar()
    c = _superadmin_completo()
    r = c.post("/plataforma/usuarios", data={
        "usuario": "nuevo", "nombre": "Nuevo Op", "rol": "admin",
        "clave_transitoria": "transi123"}, follow_redirects=False)
    assert r.headers["location"] == "/plataforma/usuarios?aviso=creado"
    u = db.usuario_plataforma_por_usuario("nuevo")
    assert u and u.rol == "admin" and u.debe_cambiar_clave and u.clave_vence and u.creado_por == "jefe"
    # el nuevo puede entrar con la transitoria y lo mandan a completar
    c2 = _cli()
    r2 = c2.post("/plataforma/login", data={"usuario": "nuevo", "clave": "transi123"},
                 follow_redirects=False)
    assert r2.headers["location"] == "/plataforma/completar"
    # quedó en el log
    from db import LogPlataforma
    with db.get_session() as s:
        assert any(l.accion == "alta" and l.objetivo == "nuevo" for l in s.exec(select(LogPlataforma)).all())
    print("OK  test_superadmin_crea_usuario_con_clave_transitoria")


def test_clave_transitoria_corta_se_rechaza():
    _limpiar()
    c = _superadmin_completo()
    r = c.post("/plataforma/usuarios", data={"usuario": "x", "rol": "admin",
               "clave_transitoria": "corta"}, follow_redirects=False)
    assert r.headers["location"] == "/plataforma/usuarios?aviso=clave_corta"
    assert db.usuario_plataforma_por_usuario("x") is None
    print("OK  test_clave_transitoria_corta_se_rechaza")


def test_admin_comun_no_puede_gestionar():
    _limpiar()
    c = _superadmin_completo(usuario="opadmin", clave="ClaveAdmin2026", rol="admin")
    r = c.get("/plataforma/usuarios")
    assert r.status_code == 403
    r2 = c.post("/plataforma/usuarios", data={"usuario": "z", "rol": "admin",
                "clave_transitoria": "transi123"})
    assert r2.status_code == 403
    assert db.usuario_plataforma_por_usuario("z") is None
    print("OK  test_admin_comun_no_puede_gestionar")


def test_guarda_del_ultimo_superadmin():
    _limpiar()
    c = _superadmin_completo(usuario="unico")   # único superadmin activo
    uid = db.usuario_plataforma_por_usuario("unico").id
    # desactivarlo: no se puede
    r = c.post(f"/plataforma/usuarios/{uid}/activar", data={"activo": "0"}, follow_redirects=False)
    assert r.headers["location"] == "/plataforma/usuarios?aviso=ultimo"
    assert db.usuario_plataforma_por_usuario("unico").activo
    # bajarlo a admin: tampoco
    r2 = c.post(f"/plataforma/usuarios/{uid}/editar", data={"nombre": "U", "rol": "admin"},
                follow_redirects=False)
    assert r2.headers["location"] == "/plataforma/usuarios?aviso=ultimo"
    assert db.usuario_plataforma_por_usuario("unico").rol == "superadmin"
    print("OK  test_guarda_del_ultimo_superadmin")


def test_resetear_clave_vuelve_a_forzar_cambio():
    _limpiar()
    c = _superadmin_completo()
    c.post("/plataforma/usuarios", data={"usuario": "reset", "rol": "admin",
           "clave_transitoria": "primera12"})
    # el usuario completa su cuenta
    u = db.usuario_plataforma_por_usuario("reset")
    db.completar_usuario_plataforma(u.id, auth.hashear_clave("DefinitivaLarga1"),
                                    "20111111112", "111", "reset@c.ar", "x", "1")
    assert not db.usuario_plataforma_por_usuario("reset").debe_cambiar_clave
    # el superadmin le resetea la clave
    uid = u.id
    r = c.post(f"/plataforma/usuarios/{uid}/resetear", data={"clave_transitoria": "nueva123456"},
               follow_redirects=False)
    assert r.headers["location"] == "/plataforma/usuarios?aviso=reseteado"
    u2 = db.usuario_plataforma_por_usuario("reset")
    assert u2.debe_cambiar_clave and u2.clave_vence and auth.verificar_clave("nueva123456", u2.clave_hash)
    print("OK  test_resetear_clave_vuelve_a_forzar_cambio")
