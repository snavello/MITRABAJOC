"""Notificaciones a empleadores (Fase 4 del plan de Empleadores): cada
criterio de destinatarios (cuit/todos/provincia), preview sin persistir,
marcar leída, aislamiento entre empleadores y entre sindicatos, bloqueo si
el módulo está apagado, y que nunca se mezclen con las notificaciones al
trabajador (tablas separadas a propósito).

Correr con: .venv/Scripts/python.exe test_notificaciones_empresa.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import (Sindicato, UsuarioSindicato, Trabajador, Empleador,
                 NotificacionEmpleador, NotificacionEmpleadorDestinatario)
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

MODULOS_CON_EMP = list(MODULOS_INICIALES) + ["empleadores"]

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Notif Empresa", slug="uom-notif-empresa",
                     modulos_habilitados=MODULOS_CON_EMP)
    fega = Sindicato(nombre="Fega Notif Empresa", slug="fega-notif-empresa",
                      modulos_habilitados=list(MODULOS_INICIALES))  # SIN empleadores -- para el bloqueo
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id

    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin UOM",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_FEGA, usuario="20222222220", nombre="Admin Fega",
                            clave_hash=auth.hashear_clave("fega-demo"), debe_cambiar_clave=False))

    # Empleadores de UOM, cada uno pensado para un criterio distinto.
    s.add(Empleador(sindicato_id=SID_UOM, cuit="30111222339", razon_social="Constructora A",
                     provincia="Santa Fe", activo=True))
    s.add(Empleador(sindicato_id=SID_UOM, cuit="30999888776", razon_social="Metalúrgica B",
                     provincia="Córdoba", activo=True))
    s.add(Empleador(sindicato_id=SID_UOM, cuit="30555444333", razon_social="Inactiva SA",
                     provincia="Santa Fe", activo=False))
    # Mismo CUIT en Fega -- para el aislamiento entre sindicatos.
    s.add(Empleador(sindicato_id=SID_FEGA, cuit="30111222339", razon_social="Constructora A (Fega)",
                     provincia="Santa Fe", activo=True))
    # Un trabajador con el mismo "identificador" numérico que un CUIT de
    # arriba, para el test de que las dos tablas nunca se cruzan.
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="30111222339", nombre="Coincidencia", activo=True))
    s.commit()

admin_uom = TestClient(main.app)
admin_uom.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})
admin_fega = TestClient(main.app)
admin_fega.post("/admin/login", data={"usuario": "20222222220", "clave": "fega-demo"})


def _sesion_empleador(cuit):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0))
    c.cookies.set("cuit_emp", cuit)
    return c


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


def test_resolver_destinatarios_por_cuit():
    cuits = db.resolver_destinatarios_empleador(SID_UOM, "cuit", ["30111222339", "no-existe"])
    assert cuits == ["30111222339"]
    print("OK  test_resolver_destinatarios_por_cuit")


def test_resolver_destinatarios_por_todos():
    cuits = db.resolver_destinatarios_empleador(SID_UOM, "todos", [])
    assert cuits == ["30111222339", "30999888776"]  # el inactivo queda afuera
    print("OK  test_resolver_destinatarios_por_todos")


def test_resolver_destinatarios_por_provincia():
    cuits = db.resolver_destinatarios_empleador(SID_UOM, "provincia", ["Córdoba"])
    assert cuits == ["30999888776"]
    print("OK  test_resolver_destinatarios_por_provincia")


def test_resolver_destinatarios_solo_activos_de_ese_sindicato():
    # El CUIT compartido con Fega no debe sumar destinatarios de UOM salvo
    # que UOM también tenga ese CUIT dado de alta (que sí tiene, activo).
    cuits_fega = db.resolver_destinatarios_empleador(SID_FEGA, "cuit", ["30111222339"])
    assert cuits_fega == ["30111222339"]
    cuits_uom = db.resolver_destinatarios_empleador(SID_UOM, "cuit", ["30111222339"])
    assert cuits_uom == ["30111222339"]
    print("OK  test_resolver_destinatarios_solo_activos_de_ese_sindicato")


def test_envio_preview_no_persiste():
    with Session(db.engine) as s:
        antes = len(s.exec(select(NotificacionEmpleador)).all())
    r = admin_uom.post("/admin/notificacion-empresa/preview", data={"criterio": "todos", "valores": []})
    assert r.status_code == 200
    assert r.json()["cantidad"] == 2
    with Session(db.engine) as s:
        despues = len(s.exec(select(NotificacionEmpleador)).all())
    assert antes == despues
    print("OK  test_envio_preview_no_persiste")


def test_envio_real_fija_snapshot_de_cantidad():
    r = admin_uom.post("/admin/notificacion-empresa", data={
        "remitente": "Comisión Directiva", "texto": "Recordatorio de presentación de aportes.",
        "criterio": "todos", "valores": [],
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        n = s.exec(select(NotificacionEmpleador).where(NotificacionEmpleador.sindicato_id == SID_UOM)
                   .order_by(NotificacionEmpleador.id.desc())).first()
        assert n is not None
        assert n.cantidad_destinatarios == 2
        assert n.origen == "manual"
        dests = s.exec(select(NotificacionEmpleadorDestinatario).where(
            NotificacionEmpleadorDestinatario.notificacion_empleador_id == n.id)).all()
        assert {d.cuit for d in dests} == {"30111222339", "30999888776"}
        assert all(d.leida_en is None for d in dests)
        global NOTIF_ID
        NOTIF_ID = n.id
    print("OK  test_envio_real_fija_snapshot_de_cantidad")


def test_empleador_ve_solo_sus_notificaciones_del_sindicato_activo():
    c = _sesion_empleador("30111222339")
    r = c.get("/api/empresa/notificaciones")
    assert r.status_code == 200
    data = r.json()
    assert data["no_leidas"] == 0, "el CUIT está en 2 sindicatos, sin sindicato activo elegido no ve nada todavía"
    print("OK  test_empleador_ve_solo_sus_notificaciones_del_sindicato_activo")


def test_marcar_leida_aisla_por_cuit():
    c = _sesion_empleador("30999888776")
    r1 = c.get("/api/empresa/notificaciones")
    assert r1.json()["no_leidas"] == 1
    r2 = c.post(f"/api/empresa/notificacion/{NOTIF_ID}/leer")
    assert r2.status_code == 200
    assert r2.json()["no_leidas"] == 0

    otro = _sesion_empleador("30111222339")
    otro.cookies.set("sind_elegido_emp", str(SID_UOM))
    r3 = otro.get("/api/empresa/notificaciones")
    assert r3.json()["no_leidas"] == 1, "marcar leída para un CUIT no debe afectar a otro"
    print("OK  test_marcar_leida_aisla_por_cuit")


def test_ruta_notificacion_empresa_bloqueada_sin_modulo_empleadores():
    r1 = admin_fega.post("/admin/notificacion-empresa/preview", data={"criterio": "todos", "valores": []})
    assert r1.status_code == 403
    r2 = admin_fega.post("/admin/notificacion-empresa", data={
        "texto": "no debería mandarse", "criterio": "todos", "valores": [],
    })
    assert r2.status_code == 403
    print("OK  test_ruta_notificacion_empresa_bloqueada_sin_modulo_empleadores")


def test_notificacion_trabajador_y_empleador_no_se_mezclan():
    # El trabajador y el empleador comparten el mismo "número" de identidad
    # (30111222339) a propósito -- confirmar que ninguno ve mensajes del otro.
    db.crear_notificacion(SID_UOM, None, "Sistema", "Aviso para trabajadores.",
                           "cuil", ["30111222339"])
    trab = _sesion_trabajador("30111222339")
    r_trab = trab.get("/api/mis-notificaciones")
    trab.cookies.set("sind_elegido", str(SID_UOM))
    r_trab = trab.get("/api/mis-notificaciones")
    textos_trab = [n["texto"] for n in r_trab.json()["notificaciones"]]
    assert "Recordatorio de presentación de aportes." not in textos_trab

    emp = _sesion_empleador("30111222339")
    emp.cookies.set("sind_elegido_emp", str(SID_UOM))
    r_emp = emp.get("/api/empresa/notificaciones")
    textos_emp = [n["texto"] for n in r_emp.json()["notificaciones"]]
    assert "Aviso para trabajadores." not in textos_emp
    assert "Recordatorio de presentación de aportes." in textos_emp
    print("OK  test_notificacion_trabajador_y_empleador_no_se_mezclan")


if __name__ == "__main__":
    test_resolver_destinatarios_por_cuit()
    test_resolver_destinatarios_por_todos()
    test_resolver_destinatarios_por_provincia()
    test_resolver_destinatarios_solo_activos_de_ese_sindicato()
    test_envio_preview_no_persiste()
    test_envio_real_fija_snapshot_de_cantidad()
    test_empleador_ve_solo_sus_notificaciones_del_sindicato_activo()
    test_marcar_leida_aisla_por_cuit()
    test_ruta_notificacion_empresa_bloqueada_sin_modulo_empleadores()
    test_notificacion_trabajador_y_empleador_no_se_mezclan()
    print("\nTodo OK — notificaciones a empleadores.")
