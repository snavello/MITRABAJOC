"""Notificaciones (Fase 2 de Módulos + Notificaciones + Trámites): cada
criterio de destinatarios, preview sin persistir, marcar leída, aislamiento
entre trabajadores y entre sindicatos, bloqueo si el módulo está apagado,
y que una notificación origen="sistema" se distinga en el listado.

Correr con: .venv/Scripts/python.exe test_notificaciones.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, Seccional, Notificacion, NotificacionDestinatario
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

MODULOS_CON_NOTIF = list(MODULOS_INICIALES) + ["notificaciones"]

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Notificaciones", slug="uom-notificaciones",
                     modulos_habilitados=MODULOS_CON_NOTIF)
    fega = Sindicato(nombre="Fega Notificaciones", slug="fega-notificaciones",
                      modulos_habilitados=list(MODULOS_INICIALES))  # SIN notificaciones -- para el bloqueo
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id

    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin UOM",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_FEGA, usuario="20222222220", nombre="Admin Fega",
                            clave_hash=auth.hashear_clave("fega-demo"), debe_cambiar_clave=False, es_super_admin=True))

    norte = Seccional(sindicato_id=SID_UOM, nombre="Norte")
    sur = Seccional(sindicato_id=SID_UOM, nombre="Sur")
    s.add(norte); s.add(sur); s.commit(); s.refresh(norte); s.refresh(sur)
    SEC_NORTE, SEC_SUR = norte.id, sur.id

    # Trabajadores de UOM, cada uno pensado para un criterio distinto.
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20111111119", nombre="Juan", activo=True,
                      registrado=True, seccional_id=SEC_NORTE, provincia="Santa Fe",
                      cuit_empleador="30111222339"))
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="27222222224", nombre="Ana", activo=True,
                      registrado=True, seccional_id=SEC_SUR, provincia="Buenos Aires",
                      cuit_empleador="30999888776"))
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20333333336", nombre="Luis", activo=True,
                      registrado=True, seccional_id=None, provincia="Córdoba"))
    # Pluriempleo: mismo CUIL en UOM (seccional Norte, destinatario real de la
    # notificación de prueba) y en Fega -- el aislamiento entre sindicatos se
    # prueba con ESTE cuil, separado de Juan para no alterar sus asserts.
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20555555551", nombre="Marta", activo=True,
                      registrado=True, seccional_id=SEC_NORTE))
    s.add(Trabajador(sindicato_id=SID_FEGA, cuil="20555555551", nombre="Marta (Fega)",
                      activo=True, registrado=True))
    s.commit()

admin_uom = TestClient(main.app)
admin_uom.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})
admin_fega = TestClient(main.app)
admin_fega.post("/admin/login", data={"usuario": "20222222220", "clave": "fega-demo"})


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


def test_resolver_destinatarios_por_cuil():
    cuils = db.resolver_destinatarios(SID_UOM, "cuil", ["20111111119", "27222222224", "no-existe"])
    assert cuils == ["20111111119", "27222222224"]
    print("OK  test_resolver_destinatarios_por_cuil")


def test_resolver_destinatarios_por_cuit_empleador():
    cuils = db.resolver_destinatarios(SID_UOM, "cuit_empleador", ["30111222339"])
    assert cuils == ["20111111119"]
    print("OK  test_resolver_destinatarios_por_cuit_empleador")


def test_resolver_destinatarios_por_seccional():
    cuils = db.resolver_destinatarios(SID_UOM, "seccional", [str(SEC_SUR)])
    assert cuils == ["27222222224"]
    print("OK  test_resolver_destinatarios_por_seccional")


def test_resolver_destinatarios_por_provincia():
    cuils = db.resolver_destinatarios(SID_UOM, "provincia", ["Córdoba"])
    assert cuils == ["20333333336"]
    print("OK  test_resolver_destinatarios_por_provincia")


def test_preview_no_persiste():
    with Session(db.engine) as s:
        antes = len(s.exec(select(Notificacion)).all())
    r = admin_uom.post("/admin/notificacion/preview", data={
        "criterio": "cuil", "valores": ["20111111119", "27222222224"],
    })
    assert r.status_code == 200
    assert r.json()["cantidad"] == 2
    with Session(db.engine) as s:
        despues = len(s.exec(select(Notificacion)).all())
    assert antes == despues
    print("OK  test_preview_no_persiste")


def test_alta_notificacion_crea_destinatarios_y_snapshot():
    r = admin_uom.post("/admin/notificacion", data={
        "remitente": "Comisión Directiva", "texto": "Aviso importante para todos.",
        "criterio": "seccional", "valores": [str(SEC_NORTE), str(SEC_SUR)],
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        n = s.exec(select(Notificacion).where(Notificacion.sindicato_id == SID_UOM)
                   .order_by(Notificacion.id.desc())).first()
        assert n is not None
        assert n.cantidad_destinatarios == 3
        assert n.origen == "manual"
        dests = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == n.id)).all()
        assert {d.cuil for d in dests} == {"20111111119", "27222222224", "20555555551"}
        assert all(d.leida_en is None for d in dests)
        global NOTIF_ID
        NOTIF_ID = n.id
    print("OK  test_alta_notificacion_crea_destinatarios_y_snapshot")


def test_trabajador_ve_su_notificacion_y_contador():
    c = _sesion_trabajador("20111111119")
    r = c.get("/api/mis-notificaciones")
    assert r.status_code == 200
    data = r.json()
    assert data["no_leidas"] == 1
    assert len(data["notificaciones"]) == 1
    assert data["notificaciones"][0]["id"] == NOTIF_ID
    print("OK  test_trabajador_ve_su_notificacion_y_contador")


def test_marcar_leida_actualiza_contador():
    c = _sesion_trabajador("20111111119")
    r = c.post(f"/api/notificacion/{NOTIF_ID}/leer")
    assert r.status_code == 200
    assert r.json()["no_leidas"] == 0
    r2 = c.get("/api/mis-notificaciones")
    assert r2.json()["no_leidas"] == 0
    assert r2.json()["notificaciones"][0]["leida_en"]
    print("OK  test_marcar_leida_actualiza_contador")


def test_marcar_todas_leidas_solo_las_propias_y_del_sindicato():
    # Dos notificaciones nuevas: una para Juan y Ana en UOM, otra de FEGA
    # para el mismo CUIL de Juan -- "marcar todas" de Juan en UOM toca SOLO
    # la copia de Juan en UOM.
    with db.get_session() as s:
        n1 = Notificacion(sindicato_id=SID_UOM, remitente="Tesorería", texto="Cuota acreditada.",
                          criterio="cuil", enviado_en="2026-09-03 10:00", cantidad_destinatarios=2)
        n2 = Notificacion(sindicato_id=SID_FEGA, remitente="Fega", texto="Aviso Fega.",
                          criterio="cuil", enviado_en="2026-09-03 10:01", cantidad_destinatarios=1)
        s.add(n1); s.add(n2); s.commit(); s.refresh(n1); s.refresh(n2)
        s.add(NotificacionDestinatario(notificacion_id=n1.id, cuil="20111111119"))
        s.add(NotificacionDestinatario(notificacion_id=n1.id, cuil="27222222224"))
        s.add(NotificacionDestinatario(notificacion_id=n2.id, cuil="20111111119"))
        s.commit()
        N1, N2 = n1.id, n2.id
    c = _sesion_trabajador("20111111119")
    assert c.get("/api/mis-notificaciones").json()["no_leidas"] == 1
    r = c.post("/api/notificaciones/leer-todas")
    assert r.status_code == 200
    assert r.json()["marcadas"] == 1 and r.json()["no_leidas"] == 0
    assert c.get("/api/mis-notificaciones").json()["no_leidas"] == 0
    with Session(db.engine) as s:
        ana = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == N1,
            NotificacionDestinatario.cuil == "27222222224")).first()
        assert ana.leida_en is None  # la copia de Ana sigue sin leer
        fega = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == N2)).first()
        assert fega.leida_en is None  # la de otro sindicato tampoco se tocó
    print("OK  test_marcar_todas_leidas_solo_las_propias_y_del_sindicato")


def test_trabajador_sin_seccional_no_ve_notificacion_dirigida():
    c = _sesion_trabajador("20333333336")  # sin seccional asignada
    r = c.get("/api/mis-notificaciones")
    assert r.json()["notificaciones"] == []
    print("OK  test_trabajador_sin_seccional_no_ve_notificacion_dirigida")


def test_no_se_puede_marcar_leida_notificacion_ajena():
    c = _sesion_trabajador("20333333336")  # no es destinatario de NOTIF_ID
    r = c.post(f"/api/notificacion/{NOTIF_ID}/leer")
    assert r.status_code == 404
    with Session(db.engine) as s:
        d = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == NOTIF_ID,
            NotificacionDestinatario.cuil == "27222222224")).first()
        assert d.leida_en is None  # la copia de Ana sigue sin leer
    print("OK  test_no_se_puede_marcar_leida_notificacion_ajena")


def test_aislamiento_entre_sindicatos():
    """Marta está en UOM (destinataria real de NOTIF_ID, por seccional Norte)
    y en Fega (pluriempleo) -- la notificación de UOM no debe aparecerle si
    su sindicato activo es Fega."""
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", "20555555551")
    c.cookies.set("sind_elegido", str(SID_FEGA))
    r = c.get("/api/mis-notificaciones")
    assert r.json()["notificaciones"] == []
    print("OK  test_aislamiento_entre_sindicatos")


def test_bloqueo_403_si_modulo_apagado():
    r1 = admin_fega.post("/admin/notificacion/preview", data={"criterio": "cuil", "valores": ["20111111119"]})
    assert r1.status_code == 403
    r2 = admin_fega.post("/admin/notificacion", data={
        "texto": "no debería mandarse", "criterio": "cuil", "valores": ["20111111119"],
    })
    assert r2.status_code == 403
    print("OK  test_bloqueo_403_si_modulo_apagado")


def test_origen_sistema_distinto_en_listado():
    resultado = db.crear_notificacion(
        SID_UOM, None, "Sistema", "Tu trámite cambió de estado.",
        "cuil", ["20333333336"], origen="sistema",
    )
    assert resultado["cantidad_destinatarios"] == 1
    listado = db.notificaciones_del_sindicato(SID_UOM)
    sistema = next(n for n in listado if n["id"] == resultado["id"])
    assert sistema["origen"] == "sistema"
    manual = next(n for n in listado if n["id"] == NOTIF_ID)
    assert manual["origen"] == "manual"
    print("OK  test_origen_sistema_distinto_en_listado")


def test_adjunto_mayor_a_5mb_no_se_guarda():
    contenido_grande = b"0" * (5 * 1024 * 1024 + 1)
    r = admin_uom.post("/admin/notificacion",
        data={"texto": "con adjunto grande", "criterio": "cuil", "valores": ["20111111119"]},
        files={"adjunto": ("grande.png", contenido_grande, "image/png")},
        follow_redirects=False)
    assert r.status_code == 303
    assert "error=adjunto" in r.headers["location"]
    print("OK  test_adjunto_mayor_a_5mb_no_se_guarda")



def test_formulario_para_iniciar_en_notificacion():
    # La notificacion puede asociar un formulario: el destinatario ve el
    # icono mientras el tipo siga activo.
    tid = db.crear_tipo_tramite(SID_UOM, "Actualizacion de datos", "ACT UOM",
                                 [{"etiqueta": "Telefono", "tipo_dato": "texto", "obligatorio": True}])
    r = admin_uom.post("/admin/notificacion", data={
        "remitente": "Padron", "texto": "Completa los datos haciendo click aca.",
        "criterio": "cuil", "valores": ["20111111119"],
        "formulario_id": str(tid),
    }, follow_redirects=False)
    assert r.status_code == 303
    notifs = db.notificaciones_de_trabajador("20111111119", SID_UOM)
    assert notifs[0]["formulario_id"] == tid
    tipo = db.tipo_tramite_por_id(tid)
    db.editar_tipo_tramite(tid, SID_UOM, tipo["titulo"], tipo["codigo"], False, tipo["campos"])
    assert db.notificaciones_de_trabajador("20111111119", SID_UOM)[0]["formulario_id"] is None
    print("OK  test_formulario_para_iniciar_en_notificacion")


if __name__ == "__main__":
    test_resolver_destinatarios_por_cuil()
    test_resolver_destinatarios_por_cuit_empleador()
    test_resolver_destinatarios_por_seccional()
    test_resolver_destinatarios_por_provincia()
    test_preview_no_persiste()
    test_alta_notificacion_crea_destinatarios_y_snapshot()
    test_trabajador_ve_su_notificacion_y_contador()
    test_marcar_leida_actualiza_contador()
    test_marcar_todas_leidas_solo_las_propias_y_del_sindicato()
    test_trabajador_sin_seccional_no_ve_notificacion_dirigida()
    test_no_se_puede_marcar_leida_notificacion_ajena()
    test_aislamiento_entre_sindicatos()
    test_bloqueo_403_si_modulo_apagado()
    test_origen_sistema_distinto_en_listado()
    test_adjunto_mayor_a_5mb_no_se_guarda()
    test_formulario_para_iniciar_en_notificacion()
    print("\nTodo OK — notificaciones.")
