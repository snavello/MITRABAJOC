"""Trámites externos a empleadores (Fase 5 del plan de Empleadores): mismo
alcance que test_tramites.py (alta de tipo con campos de cada tipo_dato,
numeración de expediente sin colisión, validación server-side, cambio de
estado dispara log + notificación de sistema a la empresa, nota de cada
lado en el thread correcto, estado terminado bloquea cambios, aislamiento
entre sindicatos, bloqueo si el módulo está apagado) más un test explícito
de que los trámites de trabajador y de empresa nunca se mezclan.

Correr con: .venv/Scripts/python.exe test_tramites_empresa.py
"""
import os
import tempfile
import json

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import (Sindicato, UsuarioSindicato, Trabajador, Empleador, Area,
                 TipoTramite, CampoTramite, Tramite,
                 TipoTramiteEmpleador, CampoTramiteEmpleador, TramiteEmpleador,
                 NotificacionEmpleador)
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

MODULOS_CON_EMP = list(MODULOS_INICIALES) + ["empleadores", "tramites"]

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Tramites Empresa", slug="uom-tramites-empresa", modulos_habilitados=MODULOS_CON_EMP)
    fega = Sindicato(nombre="Fega Tramites Empresa", slug="fega-tramites-empresa", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id

    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin UOM",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_FEGA, usuario="20222222220", nombre="Admin Fega",
                            clave_hash=auth.hashear_clave("fega-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Empleador(sindicato_id=SID_UOM, cuit="30111222339", razon_social="Constructora A", activo=True))
    # Un trabajador con el mismo "identificador" numérico que el empleador de
    # arriba -- para el test de que las dos tablas nunca se cruzan.
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="30111222339", nombre="Coincidencia", activo=True, registrado=True))
    s.commit()

admin_uom = TestClient(main.app)
admin_uom.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})
admin_fega = TestClient(main.app)
admin_fega.post("/admin/login", data={"usuario": "20222222220", "clave": "fega-demo"})


def _sesion_empleador(cuit):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0))
    c.cookies.set("cuit_emp", cuit)
    c.cookies.set("sind_elegido_emp", str(SID_UOM))
    return c


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    c.cookies.set("sind_elegido", str(SID_UOM))
    return c


def test_alta_tipo_tramite_empresa_con_campos_de_cada_tipo_dato():
    campos = [
        {"etiqueta": "Razón social confirmada", "tipo_dato": "texto", "longitud_maxima": 200, "obligatorio": True},
        {"etiqueta": "CBU", "tipo_dato": "texto", "longitud_exacta": 22, "obligatorio": True},
        {"etiqueta": "Cantidad de empleados", "tipo_dato": "numero", "obligatorio": True},
        {"etiqueta": "Fecha del período", "tipo_dato": "fecha", "obligatorio": False},
        {"etiqueta": "Nómina", "tipo_dato": "archivo", "tipos_archivo_permitidos": "pdf,xlsx", "obligatorio": True},
    ]
    r = admin_uom.post("/admin/tramite-tipo-empresa", data={
        "titulo": "Nómina mensual", "codigo": "F01 EMP", "campos_json": json.dumps(campos),
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        tipo = s.exec(select(TipoTramiteEmpleador).where(
            TipoTramiteEmpleador.sindicato_id == SID_UOM, TipoTramiteEmpleador.codigo == "F01 EMP")).first()
        assert tipo is not None
        campos_db = s.exec(select(CampoTramiteEmpleador).where(CampoTramiteEmpleador.tipo_tramite_id == tipo.id)
                           .order_by(CampoTramiteEmpleador.orden)).all()
        assert len(campos_db) == 5
        assert [c.tipo_dato for c in campos_db] == ["texto", "texto", "numero", "fecha", "archivo"]
        assert campos_db[1].longitud_exacta == 22
        assert campos_db[4].tipos_archivo_permitidos == "pdf,xlsx"
        global TIPO_ID
        TIPO_ID = tipo.id
    print("OK  test_alta_tipo_tramite_empresa_con_campos_de_cada_tipo_dato")


def _campo_id(etiqueta):
    with Session(db.engine) as s:
        c = s.exec(select(CampoTramiteEmpleador).where(
            CampoTramiteEmpleador.tipo_tramite_id == TIPO_ID, CampoTramiteEmpleador.etiqueta == etiqueta)).first()
        return c.id


def test_validacion_obligatorio_falta_campo():
    emp = _sesion_empleador("30111222339")
    r = emp.post("/api/empresa/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('CBU')}": "0" * 22,
        f"campo_{_campo_id('Cantidad de empleados')}": "10",
    })  # falta "Razón social confirmada" (obligatorio) y el archivo "Nómina" (obligatorio)
    assert r.status_code == 422
    errores = r.json()["errores"]
    assert any("Razón social confirmada" in e for e in errores)
    assert any("Nómina" in e for e in errores)
    print("OK  test_validacion_obligatorio_falta_campo")


def test_envio_tramite_empresa_completo_ok():
    emp = _sesion_empleador("30111222339")
    r = emp.post("/api/empresa/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('Razón social confirmada')}": "Constructora A",
        f"campo_{_campo_id('CBU')}": "1" * 22,
        f"campo_{_campo_id('Cantidad de empleados')}": "12",
    }, files={f"archivo_{_campo_id('Nómina')}": ("nomina.pdf", b"%PDF-1.4 contenido", "application/pdf")})
    assert r.status_code == 200
    data = r.json()
    assert data["numero_expediente"].startswith("F01EMP-")
    global TRAMITE_ID, NUMERO_EXPEDIENTE
    TRAMITE_ID, NUMERO_EXPEDIENTE = data["id"], data["numero_expediente"]
    detalle = db.tramite_empleador_detalle(TRAMITE_ID)
    assert detalle["estado"] == "iniciado"
    assert len(detalle["respuestas"]) == 4
    archivo_resp = next(r for r in detalle["respuestas"] if r["etiqueta"] == "Nómina")
    assert archivo_resp["tiene_archivo"]
    assert detalle["log"][0]["evento"] == "creado"
    print("OK  test_envio_tramite_empresa_completo_ok")


def test_numeracion_expediente_sin_colision():
    emp = _sesion_empleador("30111222339")
    numeros = {NUMERO_EXPEDIENTE}
    for _ in range(3):
        r = emp.post("/api/empresa/tramite", data={
            "tipo_tramite_id": TIPO_ID,
            f"campo_{_campo_id('Razón social confirmada')}": "Constructora A",
            f"campo_{_campo_id('CBU')}": "2" * 22,
            f"campo_{_campo_id('Cantidad de empleados')}": "5",
        }, files={f"archivo_{_campo_id('Nómina')}": ("n.pdf", b"%PDF", "application/pdf")})
        assert r.status_code == 200
        numero = r.json()["numero_expediente"]
        assert numero not in numeros
        numeros.add(numero)
    assert len(numeros) == 4
    print("OK  test_numeracion_expediente_sin_colision")


def test_cambio_estado_dispara_log_y_notificacion_empresa():
    with Session(db.engine) as s:
        antes = len(s.exec(select(NotificacionEmpleador).where(NotificacionEmpleador.sindicato_id == SID_UOM)).all())
    r = admin_uom.post(f"/admin/tramite-empresa/{TRAMITE_ID}/estado", data={"estado": "en_tratamiento"})
    assert r.status_code == 200
    detalle = db.tramite_empleador_detalle(TRAMITE_ID)
    assert detalle["estado"] == "en_tratamiento"
    assert any(l["evento"] == "cambio_estado" for l in detalle["log"])
    with Session(db.engine) as s:
        despues = s.exec(select(NotificacionEmpleador).where(NotificacionEmpleador.sindicato_id == SID_UOM)
                         .order_by(NotificacionEmpleador.id.desc())).first()
        cantidad = len(s.exec(select(NotificacionEmpleador).where(NotificacionEmpleador.sindicato_id == SID_UOM)).all())
    assert cantidad == antes + 1
    assert despues.origen == "sistema"
    assert NUMERO_EXPEDIENTE in despues.texto
    print("OK  test_cambio_estado_dispara_log_y_notificacion_empresa")


def test_nota_admin_y_empresa_en_thread_correcto():
    with Session(db.engine) as s:
        antes = len(s.exec(select(NotificacionEmpleador).where(NotificacionEmpleador.sindicato_id == SID_UOM)).all())
    r1 = admin_uom.post(f"/admin/tramite-empresa/{TRAMITE_ID}/nota", data={"texto": "Nos falta el detalle de aportes."})
    assert r1.status_code == 200
    emp = _sesion_empleador("30111222339")
    r2 = emp.post(f"/api/empresa/tramite/{TRAMITE_ID}/nota", data={"texto": "Ya lo adjunté en la nómina."})
    assert r2.status_code == 200

    detalle = db.tramite_empleador_detalle(TRAMITE_ID)
    notas = detalle["notas"]
    assert notas[-2]["autor"] == "admin" and "aportes" in notas[-2]["texto"]
    assert notas[-1]["autor"] == "empresa" and "adjunté" in notas[-1]["texto"]
    eventos = [l["evento"] for l in detalle["log"]]
    assert "nota_admin" in eventos and "nota_empresa" in eventos

    with Session(db.engine) as s:
        despues = len(s.exec(select(NotificacionEmpleador).where(NotificacionEmpleador.sindicato_id == SID_UOM)).all())
    # Solo la nota del ADMIN notifica -- la de la empresa no se auto-notifica.
    assert despues == antes + 1
    print("OK  test_nota_admin_y_empresa_en_thread_correcto")


def test_terminado_bloquea_cambios():
    emp = _sesion_empleador("30111222339")
    r = emp.post("/api/empresa/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('Razón social confirmada')}": "Constructora A",
        f"campo_{_campo_id('CBU')}": "3" * 22,
        f"campo_{_campo_id('Cantidad de empleados')}": "7",
    }, files={f"archivo_{_campo_id('Nómina')}": ("n.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 200
    tid = r.json()["id"]
    r_term = admin_uom.post(f"/admin/tramite-empresa/{tid}/estado", data={"estado": "terminado"})
    assert r_term.status_code == 200
    assert db.tramite_empleador_detalle(tid)["estado"] == "terminado"

    r_reabrir = admin_uom.post(f"/admin/tramite-empresa/{tid}/estado", data={"estado": "en_tratamiento"})
    assert r_reabrir.status_code == 400
    assert db.tramite_empleador_detalle(tid)["estado"] == "terminado"

    r_nota_admin = admin_uom.post(f"/admin/tramite-empresa/{tid}/nota", data={"texto": "no debería poder"})
    assert r_nota_admin.status_code == 400
    r_nota_emp = emp.post(f"/api/empresa/tramite/{tid}/nota", data={"texto": "no debería poder"})
    assert r_nota_emp.status_code == 400
    assert db.tramite_empleador_detalle(tid)["notas"] == []
    print("OK  test_terminado_bloquea_cambios")


def test_consulta_por_expediente_aislada_por_cuit():
    r_ok = _sesion_empleador("30111222339").get(f"/api/empresa/tramite/{NUMERO_EXPEDIENTE}")
    assert r_ok.status_code == 200
    r_ajeno = _sesion_empleador("30999888776").get(f"/api/empresa/tramite/{NUMERO_EXPEDIENTE}")
    assert r_ajeno.status_code == 404
    print("OK  test_consulta_por_expediente_aislada_por_cuit")


def test_cantidad_nuevos_para_el_polling_del_globo():
    r = admin_uom.get("/admin/tramites-empresa-nuevos-cantidad")
    assert r.status_code == 200
    esperado = db.contar_tramites_empleador_nuevos(SID_UOM)
    assert r.json() == {"cantidad": esperado}
    r_sin_sesion = TestClient(main.app).get("/admin/tramites-empresa-nuevos-cantidad")
    assert r_sin_sesion.status_code == 403
    print("OK  test_cantidad_nuevos_para_el_polling_del_globo")


def test_aislamiento_entre_sindicatos():
    with Session(db.engine) as s:
        fega = s.get(Sindicato, SID_FEGA)
        fega.modulos_habilitados = list(fega.modulos_habilitados) + ["empleadores"]
        s.add(fega); s.commit()
    try:
        r = admin_fega.get(f"/admin/tramite-empresa/{TRAMITE_ID}")
        assert r.status_code == 404
        r2 = admin_fega.post(f"/admin/tramite-empresa/{TRAMITE_ID}/estado", data={"estado": "terminado"})
        assert r2.status_code == 404
    finally:
        with Session(db.engine) as s:
            fega = s.get(Sindicato, SID_FEGA)
            fega.modulos_habilitados = list(MODULOS_INICIALES)
            s.add(fega); s.commit()
    print("OK  test_aislamiento_entre_sindicatos")


def test_bloqueo_403_si_modulo_apagado():
    r1 = admin_fega.post("/admin/tramite-tipo-empresa", data={
        "titulo": "No debería crearse", "codigo": "X", "campos_json": json.dumps([
            {"etiqueta": "Campo", "tipo_dato": "texto", "obligatorio": True}]),
    })
    assert r1.status_code == 403
    r2 = admin_fega.post("/admin/tramite-tipo-empresa/borrar", data={"id": TIPO_ID})
    assert r2.status_code == 403
    with Session(db.engine) as s:
        fega_emp = Empleador(sindicato_id=SID_FEGA, cuit="30444444440", razon_social="Ajena", activo=True)
        s.add(fega_emp); s.commit()
    emp_fega = TestClient(main.app)
    emp_fega.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0))
    emp_fega.cookies.set("cuit_emp", "30444444440")
    emp_fega.cookies.set("sind_elegido_emp", str(SID_FEGA))
    r3 = emp_fega.post("/api/empresa/tramite", data={"tipo_tramite_id": TIPO_ID, "campo_1": "x"})
    assert r3.status_code == 403
    print("OK  test_bloqueo_403_si_modulo_apagado")


def test_tramites_de_trabajador_y_empresa_nunca_se_mezclan():
    """El trabajador y el empleador comparten el mismo "número" de identidad
    (30111222339) a propósito -- confirmar que ninguno ve trámites del otro,
    y que las tablas TramiteEmpleador/Tramite nunca se cruzan."""
    campos = [{"etiqueta": "Campo", "tipo_dato": "texto", "obligatorio": True}]
    with db.get_session() as s:
        area = Area(sindicato_id=SID_UOM, nombre="Mesa de Entradas")
        s.add(area); s.commit(); s.refresh(area)
        area_id = area.id
    r_tipo_trab = admin_uom.post("/admin/tramite-tipo", data={
        "titulo": "Tipo trabajador", "codigo": "TRAB", "campos_json": json.dumps(campos),
        "areas": [str(area_id)],
    }, follow_redirects=False)
    assert r_tipo_trab.status_code == 303
    with Session(db.engine) as s:
        tipo_trab = s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == SID_UOM, TipoTramite.codigo == "TRAB")).first()
        campo_trab_id = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo_trab.id)).first().id

    trab = _sesion_trabajador("30111222339")
    r_trab = trab.post("/api/tramite", data={"tipo_tramite_id": tipo_trab.id, f"campo_{campo_trab_id}": "hola"})
    assert r_trab.status_code == 200

    r_mis_trab = trab.get("/api/tramites/mios")
    numeros_trab = [t["numero_expediente"] for t in r_mis_trab.json()["tramites"]]
    assert all(not n.startswith("F01EMP-") for n in numeros_trab)

    emp = _sesion_empleador("30111222339")
    r_mis_emp = emp.get("/api/empresa/tramites/mios")
    numeros_emp = [t["numero_expediente"] for t in r_mis_emp.json()["tramites"]]
    assert not any(n.startswith("TRAB-") for n in numeros_emp)
    assert any(n.startswith("F01EMP-") for n in numeros_emp)

    with Session(db.engine) as s:
        cuits_tramite_empleador = {t.cuit for t in s.exec(select(TramiteEmpleador)).all()}
        cuils_tramite_trabajador = {t.cuil for t in s.exec(select(Tramite)).all()}
        assert cuits_tramite_empleador == {"30111222339"}
        assert cuils_tramite_trabajador == {"30111222339"}
    print("OK  test_tramites_de_trabajador_y_empresa_nunca_se_mezclan")


if __name__ == "__main__":
    test_alta_tipo_tramite_empresa_con_campos_de_cada_tipo_dato()
    test_validacion_obligatorio_falta_campo()
    test_envio_tramite_empresa_completo_ok()
    test_numeracion_expediente_sin_colision()
    test_cambio_estado_dispara_log_y_notificacion_empresa()
    test_nota_admin_y_empresa_en_thread_correcto()
    test_terminado_bloquea_cambios()
    test_consulta_por_expediente_aislada_por_cuit()
    test_cantidad_nuevos_para_el_polling_del_globo()
    test_aislamiento_entre_sindicatos()
    test_bloqueo_403_si_modulo_apagado()
    test_tramites_de_trabajador_y_empresa_nunca_se_mezclan()
    print("\nTodo OK — trámites externos a empleadores.")
