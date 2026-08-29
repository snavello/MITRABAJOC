"""Panel Sindical (docs/DASHBOARD.md) — Fase 1: endpoints de agregados.

Cubre las dos reglas innegociables (con test, §5.5 y §5.6):
- Privacidad: un recibo NO enviado voluntariamente jamás expone nombre/CUIL
  en ninguna respuesta de la API (la regla vive en el SQL, no en el front).
- Aislamiento de tenant: ningún endpoint devuelve datos de otro sindicato,
  ni manipulando query params (ids de seccionales/empresas ajenas).

Más: validación de rangos de fecha, feature flag del carril de consultas,
paginación server-side, semáforo por empresa y correctitud de los agregados.

Correr con: .venv/Scripts/python.exe test_dashboard.py
"""
import os
import tempfile
from datetime import date, datetime, timedelta

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
from db import (Sindicato, UsuarioSindicato, Trabajador, Seccional, Empleador,
                ReciboVerificado, TipoTramite, Tramite, Notificacion,
                NotificacionDestinatario, ConsultaConvenio)
import main
from fastapi.testclient import TestClient

db.crear_tablas()

HOY = date.today()


def _ts(dias_atras=0, hora="10:00"):
    return (HOY - timedelta(days=dias_atras)).isoformat() + " " + hora


def _dia(dias_atras=0):
    return (HOY - timedelta(days=dias_atras)).isoformat()


RANGO = {"desde": _dia(30), "hasta": _dia(0)}

with db.get_session() as s:
    # --- Sindicato A: el tenant bajo prueba ---
    sind_a = Sindicato(nombre="UOM Dash", slug="uom-dash", color_base="#0f1b2d",
                       modulos_habilitados=["dashboard", "tramites", "notificaciones"])
    # --- Sindicato B: el "otro" tenant, para aislamiento ---
    sind_b = Sindicato(nombre="Fega Dash", slug="fega-dash", color_base="#0d2027",
                       modulos_habilitados=["dashboard"])
    # --- Sindicato C: sin el módulo dashboard ---
    sind_c = Sindicato(nombre="Sind Sin Dash", slug="sind-sin-dash", color_base="#111111",
                       modulos_habilitados=["recibos"])
    s.add(sind_a); s.add(sind_b); s.add(sind_c)
    s.commit(); s.refresh(sind_a); s.refresh(sind_b); s.refresh(sind_c)
    SID_A, SID_B, SID_C = sind_a.id, sind_b.id, sind_c.id

    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20111111110", nombre="Admin A",
                            clave_hash=auth.hashear_clave("a-demo"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_B, usuario="20222222220", nombre="Admin B",
                            clave_hash=auth.hashear_clave("b-demo"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_C, usuario="20333333330", nombre="Admin C",
                            clave_hash=auth.hashear_clave("c-demo"), debe_cambiar_clave=False))

    secc_1 = Seccional(sindicato_id=SID_A, nombre="Rosario")
    secc_2 = Seccional(sindicato_id=SID_A, nombre="Córdoba")
    secc_b = Seccional(sindicato_id=SID_B, nombre="Ajena")
    s.add(secc_1); s.add(secc_2); s.add(secc_b)
    s.commit(); s.refresh(secc_1); s.refresh(secc_2); s.refresh(secc_b)

    emp_1 = Empleador(sindicato_id=SID_A, cuit="30111111117", razon_social="Metalsur SA")
    emp_2 = Empleador(sindicato_id=SID_A, cuit="30-22222222-5", razon_social="Textil Belgrano")
    emp_b = Empleador(sindicato_id=SID_B, cuit="30999999993", razon_social="Ajena SA")
    s.add(emp_1); s.add(emp_2); s.add(emp_b)
    s.commit(); s.refresh(emp_1); s.refresh(emp_2); s.refresh(emp_b)

    CUIL_1, CUIL_2, CUIL_B = "20111111119", "20222222227", "20999999995"
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_1, nombre="Juan Enviado",
                      registrado=True, seccional_id=secc_1.id, cuit_empleador="30111111117"))
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_2, nombre="Ana Privada",
                      registrado=False, seccional_id=secc_2.id, cuit_empleador="30222222225"))
    s.add(Trabajador(sindicato_id=SID_B, cuil=CUIL_B, nombre="Beto Ajeno",
                      registrado=True, seccional_id=secc_b.id))

    # --- Recibos del sindicato A ---
    # r1: con diferencias, ENVIADO voluntariamente (nombre/CUIL visibles).
    s.add(ReciboVerificado(
        sindicato_id=SID_A, cuil=CUIL_1, periodo="2026-07", fecha="01/08/2026 10:00",
        estado="CON_DISCREPANCIAS", enviado_sindicato=True, fecha_envio=_ts(2),
        detalle={}, procesado_en=_ts(2), cuit_empleador="30111111117",
        categoria="Operario A", formato="nuevo", bruto=900000.0,
        monto_diferencia=5000.0, fecha_ultimo_deposito=_dia(10)))
    # r2: con diferencias, NO enviado (debe salir anonimizado SIEMPRE).
    s.add(ReciboVerificado(
        sindicato_id=SID_A, cuil=CUIL_2, periodo="2026-07", fecha="02/08/2026 11:00",
        estado="CON_DISCREPANCIAS", enviado_sindicato=False,
        detalle={}, procesado_en=_ts(1), cuit_empleador="30222222225",
        categoria="Administrativo", formato="clasico", bruto=500000.0,
        monto_diferencia=3000.0, fecha_ultimo_deposito=_dia(90)))
    # r3: OK.
    s.add(ReciboVerificado(
        sindicato_id=SID_A, cuil=CUIL_1, periodo="2026-06", fecha="03/08/2026 12:00",
        estado="OK", enviado_sindicato=False,
        detalle={}, procesado_en=_ts(1, "15:00"), cuit_empleador="30111111117",
        categoria="Operario A", formato="nuevo", bruto=700000.0, monto_diferencia=0.0))
    # --- Recibo del sindicato B (jamás debe aparecer para A) ---
    s.add(ReciboVerificado(
        sindicato_id=SID_B, cuil=CUIL_B, periodo="2026-07", fecha="03/08/2026 09:00",
        estado="CON_DISCREPANCIAS", enviado_sindicato=True, fecha_envio=_ts(1),
        detalle={}, procesado_en=_ts(1), cuit_empleador="30999999993",
        categoria="Ajena", formato="nuevo", bruto=650000.0, monto_diferencia=7777.0))

    # --- Trámites del sindicato A ---
    tt = TipoTramite(sindicato_id=SID_A, titulo="Reclamo de aportes", codigo="F01", creado=_ts(20))
    s.add(tt); s.commit(); s.refresh(tt)
    s.add(Tramite(sindicato_id=SID_A, tipo_tramite_id=tt.id, numero_expediente="F01-2026-000001",
                   cuil=CUIL_1, estado="iniciado", creado=_ts(0), actualizado=_ts(0)))
    s.add(Tramite(sindicato_id=SID_A, tipo_tramite_id=tt.id, numero_expediente="F01-2026-000002",
                   cuil=CUIL_2, estado="terminado", creado=_ts(5), actualizado=_ts(2),
                   resuelto_en=_ts(2)))
    tt_b = TipoTramite(sindicato_id=SID_B, titulo="Ajeno", codigo="X01", creado=_ts(20))
    s.add(tt_b); s.commit(); s.refresh(tt_b)
    s.add(Tramite(sindicato_id=SID_B, tipo_tramite_id=tt_b.id, numero_expediente="X01-2026-000001",
                   cuil=CUIL_B, estado="iniciado", creado=_ts(1), actualizado=_ts(1)))

    # --- Notificaciones del sindicato A ---
    n1 = Notificacion(sindicato_id=SID_A, remitente="CD", texto="Aviso manual",
                       criterio="cuil", origen="manual", enviado_en=_ts(3),
                       cantidad_destinatarios=2)
    n2 = Notificacion(sindicato_id=SID_A, remitente="Sistema", texto="Cambio de trámite",
                       criterio="cuil", origen="sistema", enviado_en=_ts(1),
                       cantidad_destinatarios=1)
    s.add(n1); s.add(n2); s.commit(); s.refresh(n1); s.refresh(n2)
    s.add(NotificacionDestinatario(notificacion_id=n1.id, cuil=CUIL_1, leida_en=_ts(2)))
    s.add(NotificacionDestinatario(notificacion_id=n1.id, cuil=CUIL_2))
    s.add(NotificacionDestinatario(notificacion_id=n2.id, cuil=CUIL_1))
    nb = Notificacion(sindicato_id=SID_B, remitente="CD B", texto="Ajena",
                       criterio="cuil", origen="manual", enviado_en=_ts(1),
                       cantidad_destinatarios=1)
    s.add(nb); s.commit(); s.refresh(nb)
    s.add(NotificacionDestinatario(notificacion_id=nb.id, cuil=CUIL_B))

    # --- Consultas (piloto RAG) del sindicato A ---
    s.add(ConsultaConvenio(sindicato_id=SID_A, cuil=CUIL_1, pregunta="¿Horas extras?",
                            hubo_respuesta=True, creado=_ts(1), tema="Horas extras"))
    s.add(ConsultaConvenio(sindicato_id=SID_A, cuil=CUIL_2, pregunta="¿Licencias?",
                            hubo_respuesta=False, creado=_ts(2), tema="Licencias"))
    s.add(ConsultaConvenio(sindicato_id=SID_B, cuil=CUIL_B, pregunta="Ajena",
                            hubo_respuesta=True, creado=_ts(1), tema="Ajena"))
    s.commit()
    SECC_1, SECC_2, SECC_B_ID = secc_1.id, secc_2.id, secc_b.id
    EMP_1, EMP_2, EMP_B_ID = emp_1.id, emp_2.id, emp_b.id


def _cliente(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


admin_a = _cliente("20111111110", "a-demo")
admin_b = _cliente("20222222220", "b-demo")
admin_c = _cliente("20333333330", "c-demo")

ENDPOINTS = ["kpis", "serie-recibos", "validacion", "diferencias-empresa",
             "tramites-seccional", "notificaciones", "formato-semana", "semaforo",
             "explorador/recibos", "explorador/tramites", "explorador/notificaciones",
             "filtros"]


# ---------- Acceso ----------

def test_sin_sesion_403():
    c = TestClient(main.app)
    for ep in ENDPOINTS + ["consultas", "explorador/consultas"]:
        r = c.get(f"/admin/dashboard/{ep}", params=RANGO)
        assert r.status_code == 403, (ep, r.status_code)
    print("OK  test_sin_sesion_403")


def test_sin_modulo_403():
    for ep in ENDPOINTS:
        r = admin_c.get(f"/admin/dashboard/{ep}", params=RANGO)
        assert r.status_code == 403, (ep, r.status_code)
    print("OK  test_sin_modulo_403")


# ---------- Validación de filtros (§3.1) ----------

def test_rangos_invalidos_422():
    casos = [
        {},                                                      # falta desde/hasta
        {"desde": _dia(0), "hasta": (HOY + timedelta(days=1)).isoformat()},  # futuro
        {"desde": _dia(0), "hasta": _dia(5)},                    # desde > hasta
        {"desde": (HOY - timedelta(days=400)).isoformat(), "hasta": _dia(0)},  # >366 días
        {"desde": "29/08/2026", "hasta": _dia(0)},               # formato no ISO
        dict(RANGO, formato="rarisimo"),
        dict(RANGO, resultado="en_revision"),                    # ya no existe (2 estados)
        dict(RANGO, estado_tramite="cerrado"),
        dict(RANGO, sal_min="mucho"),
    ]
    for params in casos:
        r = admin_a.get("/admin/dashboard/kpis", params=params)
        assert r.status_code == 422, (params, r.status_code, r.text)
    print("OK  test_rangos_invalidos_422")


# ---------- KPIs ----------

def test_kpis():
    r = admin_a.get("/admin/dashboard/kpis", params=RANGO)
    assert r.status_code == 200, r.text
    k = r.json()["actual"]
    assert k["recibos"] == 3
    assert k["pct_con_diferencias"] == 66.7
    assert k["monto_observado"] == 8000.0
    assert k["enviados_sindicato"] == 1
    assert k["tramites"] == 2
    assert k["tramites_sin_resolver"] == 1
    assert k["notif_enviadas"] == 3
    assert k["notif_leidas"] if "notif_leidas" in k else True
    assert k["tasa_lectura"] == 33.3
    assert k["padron_total"] == 2
    assert k["padron_registrados"] == 1
    assert k["consultas"] is None  # flag apagado
    assert r.json()["anterior"]["recibos"] == 0
    print("OK  test_kpis")


def test_kpis_reaccionan_a_filtros():
    # Por seccional: Rosario tiene r1 y r3.
    k = admin_a.get("/admin/dashboard/kpis",
                    params={**RANGO, "seccionales": SECC_1}).json()["actual"]
    assert k["recibos"] == 2 and k["monto_observado"] == 5000.0
    assert k["padron_total"] == 1 and k["padron_registrados"] == 1
    # Por resultado.
    k = admin_a.get("/admin/dashboard/kpis",
                    params={**RANGO, "resultado": "con_diferencias"}).json()["actual"]
    assert k["recibos"] == 2
    # Por formato ("viejo" mapea a "clasico").
    k = admin_a.get("/admin/dashboard/kpis",
                    params={**RANGO, "formato": "viejo"}).json()["actual"]
    assert k["recibos"] == 1 and k["monto_observado"] == 3000.0
    # Por rango salarial.
    k = admin_a.get("/admin/dashboard/kpis",
                    params={**RANGO, "sal_min": 600000}).json()["actual"]
    assert k["recibos"] == 2
    # Por empresa.
    k = admin_a.get("/admin/dashboard/kpis",
                    params={**RANGO, "empresas": EMP_1}).json()["actual"]
    assert k["recibos"] == 2 and k["enviados_sindicato"] == 1
    print("OK  test_kpis_reaccionan_a_filtros")


# ---------- Aislamiento de tenant (§5.6) ----------

def test_aislamiento_totales():
    ka = admin_a.get("/admin/dashboard/kpis", params=RANGO).json()["actual"]
    kb = admin_b.get("/admin/dashboard/kpis", params=RANGO).json()["actual"]
    assert ka["recibos"] == 3 and kb["recibos"] == 1      # ni uno más
    assert kb["monto_observado"] == 7777.0
    assert ka["monto_observado"] == 8000.0                # el 7777 de B no se cuela
    print("OK  test_aislamiento_totales")


def test_aislamiento_por_manipulacion_de_params():
    # Ids de seccional/empresa de OTRO sindicato: filtran a nada, jamás
    # abren la puerta a datos ajenos.
    k = admin_a.get("/admin/dashboard/kpis",
                    params={**RANGO, "seccionales": SECC_B_ID}).json()["actual"]
    assert k["recibos"] == 0 and k["monto_observado"] == 0
    k = admin_a.get("/admin/dashboard/kpis",
                    params={**RANGO, "empresas": EMP_B_ID}).json()["actual"]
    assert k["recibos"] == 0
    r = admin_a.get("/admin/dashboard/explorador/recibos",
                    params={**RANGO, "empresas": EMP_B_ID})
    assert r.json()["total"] == 0
    print("OK  test_aislamiento_por_manipulacion_de_params")


def test_aislamiento_en_todas_las_respuestas():
    """En NINGUNA respuesta de A aparecen el CUIL, la empresa o el monto del
    tenant B (barrido crudo sobre el JSON)."""
    for ep in ENDPOINTS:
        r = admin_a.get(f"/admin/dashboard/{ep}", params=RANGO)
        assert r.status_code == 200, (ep, r.text)
        texto = r.text
        assert CUIL_B not in texto, ep
        assert "7777" not in texto, ep
        assert "Ajena" not in texto, ep
        assert "Beto" not in texto, ep
    print("OK  test_aislamiento_en_todas_las_respuestas")


# ---------- Privacidad del detalle de recibos (§5.5) ----------

def test_privacidad_recibo_no_enviado_anonimo():
    r = admin_a.get("/admin/dashboard/explorador/recibos", params=RANGO)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["total"] == 2  # solo los que no están OK
    por_monto = {item["diferencia"]: item for item in datos["items"]}
    enviado, privado = por_monto[5000.0], por_monto[3000.0]
    # El enviado voluntariamente viene identificado.
    assert enviado["enviado"] is True
    assert enviado["trabajador_nombre"] == "Juan Enviado"
    assert enviado["trabajador_cuil"] == CUIL_1
    # El NO enviado viene anonimizado: ni nombre ni CUIL, en ningún campo.
    assert privado["enviado"] is False
    assert privado["trabajador_nombre"] is None
    assert privado["trabajador_cuil"] is None
    assert CUIL_2 not in r.text
    assert "Ana" not in r.text
    print("OK  test_privacidad_recibo_no_enviado_anonimo")


def test_privacidad_en_ninguna_otra_respuesta():
    """El CUIL de un trabajador con recibo NO enviado no aparece en ninguna
    respuesta del dashboard (el nombre sí puede aparecer por otras fuentes
    legítimas -- acá el dato sensible es CUIL+recibo)."""
    for ep in ENDPOINTS:
        r = admin_a.get(f"/admin/dashboard/{ep}", params=RANGO)
        assert CUIL_2 not in r.text, ep
    print("OK  test_privacidad_en_ninguna_otra_respuesta")


# ---------- Agregados ----------

def test_serie_recibos_rellena_dias_vacios():
    r = admin_a.get("/admin/dashboard/serie-recibos",
                    params={"desde": _dia(4), "hasta": _dia(0)})
    serie = r.json()["serie"]
    assert len(serie) == 5
    assert sum(p["cantidad"] for p in serie) == 3
    assert serie[-1]["dia"] == _dia(0) and serie[-1]["cantidad"] == 0
    print("OK  test_serie_recibos_rellena_dias_vacios")


def test_validacion_dos_estados():
    r = admin_a.get("/admin/dashboard/validacion", params=RANGO)
    assert r.json() == {"ok": 1, "con_diferencias": 2}
    print("OK  test_validacion_dos_estados")


def test_diferencias_empresa_top():
    r = admin_a.get("/admin/dashboard/diferencias-empresa", params=RANGO)
    empresas = r.json()["empresas"]
    assert [e["monto"] for e in empresas] == [5000.0, 3000.0]
    assert empresas[0]["nombre"] == "Metalsur SA"
    # El CUIT cargado con guiones en el CRUD etiqueta igual (normalización).
    assert empresas[1]["nombre"] == "Textil Belgrano"
    print("OK  test_diferencias_empresa_top")


def test_tramites_seccional_matriz():
    r = admin_a.get("/admin/dashboard/tramites-seccional", params=RANGO)
    filas = {f["seccional"]: f for f in r.json()["seccionales"]}
    assert filas["Rosario"]["abierto"] == 1
    assert filas["Córdoba"]["resuelto"] == 1
    print("OK  test_tramites_seccional_matriz")


def test_notificaciones_por_tipo():
    r = admin_a.get("/admin/dashboard/notificaciones", params=RANGO)
    d = r.json()
    assert d["enviadas"] == 3 and d["leidas"] == 1 and d["sin_leer"] == 2
    assert d["tasa_lectura"] == 33.3
    tipos = {t["tipo"]: t for t in d["por_tipo"]}
    assert tipos["manual"]["enviadas"] == 2 and tipos["manual"]["leidas"] == 1
    assert tipos["sistema"]["enviadas"] == 1 and tipos["sistema"]["leidas"] == 0
    assert tipos["manual"]["etiqueta"] == "Comunicaciones"
    print("OK  test_notificaciones_por_tipo")


def test_formato_semana():
    r = admin_a.get("/admin/dashboard/formato-semana", params=RANGO)
    semanas = r.json()["semanas"]
    assert sum(x["nuevo"] for x in semanas) == 2
    assert sum(x["clasico"] for x in semanas) == 1
    print("OK  test_formato_semana")


def test_semaforo():
    r = admin_a.get("/admin/dashboard/semaforo", params=RANGO)
    d = r.json()
    assert d["umbrales"] == {"verde_hasta": 35, "amarillo_hasta": 60}
    assert d["resumen"] == {"verde": 1, "amarillo": 0, "rojo": 1}
    por_cuit = {e["cuit"]: e for e in d["empresas"]}
    assert por_cuit["30111111117"]["estado"] == "verde"
    assert por_cuit["30111111117"]["dias"] == 10
    assert por_cuit["30222222225"]["estado"] == "rojo"
    assert d["empresas"][0]["dias"] >= d["empresas"][-1]["dias"]  # peor primero
    print("OK  test_semaforo")


# ---------- Feature flag del carril de consultas (§4.7) ----------

def test_consultas_apagado_404():
    assert admin_a.get("/admin/dashboard/consultas", params=RANGO).status_code == 404
    assert admin_a.get("/admin/dashboard/explorador/consultas", params=RANGO).status_code == 404
    assert admin_a.get("/admin/dashboard/filtros", params=RANGO).json()[
        "consultas_bot_habilitado"] is False
    print("OK  test_consultas_apagado_404")


def test_consultas_prendido():
    db.set_config_dashboard(35, 60, True)
    try:
        r = admin_a.get("/admin/dashboard/consultas", params=RANGO)
        assert r.status_code == 200, r.text
        temas = {t["tema"]: t["cantidad"] for t in r.json()["temas"]}
        assert temas == {"Horas extras": 1, "Licencias": 1}  # la de B no está
        r = admin_a.get("/admin/dashboard/explorador/consultas", params=RANGO)
        assert r.json()["total"] == 2
        estados = {i["tema"]: i["resuelta_por_bot"] for i in r.json()["items"]}
        assert estados == {"Horas extras": True, "Licencias": False}
        k = admin_a.get("/admin/dashboard/kpis", params=RANGO).json()["actual"]
        assert k["consultas"] == 2
    finally:
        db.set_config_dashboard(35, 60, False)
    print("OK  test_consultas_prendido")


# ---------- Explorador (§3.3) ----------

def test_explorador_paginacion():
    r = admin_a.get("/admin/dashboard/explorador/recibos",
                    params={**RANGO, "page_size": 1})
    d = r.json()
    assert d["total"] == 2 and len(d["items"]) == 1
    assert d["items"][0]["diferencia"] == 5000.0  # orden: mayor monto primero
    r2 = admin_a.get("/admin/dashboard/explorador/recibos",
                     params={**RANGO, "page_size": 1, "page": 2})
    assert r2.json()["items"][0]["diferencia"] == 3000.0
    # page_size se recorta al máximo (50) sin reventar.
    r3 = admin_a.get("/admin/dashboard/explorador/recibos",
                     params={**RANGO, "page_size": 9999})
    assert r3.json()["page_size"] == 50
    print("OK  test_explorador_paginacion")


def test_explorador_tramites_dias():
    r = admin_a.get("/admin/dashboard/explorador/tramites", params=RANGO)
    d = r.json()
    assert d["total"] == 2
    por_numero = {i["numero"]: i for i in d["items"]}
    abierto = por_numero["F01-2026-000001"]
    resuelto = por_numero["F01-2026-000002"]
    assert abierto["estado"] == "abierto" and abierto["sigue"] is True and abierto["dias"] == 0
    assert resuelto["estado"] == "resuelto" and resuelto["sigue"] is False and resuelto["dias"] == 3
    assert resuelto["tipo"] == "Reclamo de aportes"
    print("OK  test_explorador_tramites_dias")


def test_explorador_notificaciones_agregado():
    r = admin_a.get("/admin/dashboard/explorador/notificaciones", params=RANGO)
    d = r.json()
    assert d["total"] == 3  # (día, seccional, tipo): n1×2 seccionales + n2×1
    filas = {(i["tipo"], i["seccional"]): i for i in d["items"]}
    assert filas[("manual", "Rosario")]["leidas"] == 1
    assert filas[("manual", "Córdoba")]["sin_leer"] == 1
    assert filas[("sistema", "Rosario")]["enviadas"] == 1
    assert filas[("manual", "Rosario")]["tasa_lectura"] == 100
    print("OK  test_explorador_notificaciones_agregado")


def test_explorador_fuente_desconocida_404():
    assert admin_a.get("/admin/dashboard/explorador/loquesea",
                       params=RANGO).status_code == 404
    print("OK  test_explorador_fuente_desconocida_404")


# ---------- Catálogo de filtros ----------

def test_catalogo_filtros():
    r = admin_a.get("/admin/dashboard/filtros", params=RANGO)
    d = r.json()
    assert {s_["nombre"] for s_ in d["seccionales"]} == {"Rosario", "Córdoba"}
    assert {e["nombre"] for e in d["empresas"]} == {"Metalsur SA", "Textil Belgrano"}
    assert set(d["categorias"]) == {"Operario A", "Administrativo"}
    assert d["bruto_min"] == 500000.0 and d["bruto_max"] == 900000.0
    print("OK  test_catalogo_filtros")


# ---------- Página del dashboard (Fase 2, server-rendered) ----------

def test_pagina_dashboard():
    r = admin_a.get("/admin/dashboard")
    assert r.status_code == 200
    assert "Panel Sindical" in r.text
    assert "chart.umd.min.js" in r.text          # vendoreado, jamás un CDN
    assert "cdn" not in r.text.lower()
    assert "#E5188F" in r.text                    # --destacado inyectado
    # Flag del bot APAGADO: el carril entero no llega al HTML.
    assert "Consultas al asistente" not in r.text
    assert 'data-t="consultas"' not in r.text
    print("OK  test_pagina_dashboard")


def test_pagina_dashboard_flag_prendido():
    db.set_config_dashboard(35, 60, True)
    try:
        r = admin_a.get("/admin/dashboard")
        assert "Consultas al asistente" in r.text
        assert 'data-t="consultas"' in r.text
    finally:
        db.set_config_dashboard(35, 60, False)
    print("OK  test_pagina_dashboard_flag_prendido")


def test_chartjs_vendoreado_con_cache():
    r = admin_a.get("/static/chart.umd.min.js?v=4.4.9")
    assert r.status_code == 200
    assert "Chart" in r.text[:3000]
    assert r.headers.get("cache-control") == "public, max-age=3600"
    print("OK  test_chartjs_vendoreado_con_cache")


def test_pagina_dashboard_sin_modulo_redirige():
    r = admin_c.get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    print("OK  test_pagina_dashboard_sin_modulo_redirige")


def test_nav_muestra_dashboard_solo_con_modulo():
    assert 'href="/admin/dashboard"' in admin_a.get("/admin").text
    assert 'href="/admin/dashboard"' not in admin_c.get("/admin").text
    assert 'href="/admin/dashboard"' in admin_a.get("/admin/inicio").text
    assert 'href="/admin/dashboard"' not in admin_c.get("/admin/inicio").text
    print("OK  test_nav_muestra_dashboard_solo_con_modulo")


# ---------- Configuración de plataforma (§2.3) ----------

def test_color_destacado_default_y_marca():
    marca = db.marca_sindicato(SID_A)
    assert marca["color_destacado"] == "#E5188F"
    print("OK  test_color_destacado_default_y_marca")


def test_plataforma_edita_color_destacado_y_umbrales():
    plataforma = TestClient(main.app)
    plataforma.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})
    # Alta de sindicato con color destacado propio.
    r = plataforma.post("/plataforma/sindicato", data={
        "nombre": "Sindicato Destacado", "descripcion": "", "cuit": "", "direccion": "",
        "mail": "", "telefonos": "", "autoridad": "", "cargo_autoridad": "",
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
        "color_base": "#0f1b2d", "color_destacado": "#00A0FF",
    }, follow_redirects=False)
    assert r.status_code == 303
    from sqlmodel import Session, select
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Destacado")).first()
        assert sind.color_destacado == "#00A0FF"
    # Umbrales del semáforo + flag, por la ruta de plataforma.
    r = plataforma.post("/plataforma/config-dashboard", data={
        "semaforo_verde_hasta_dias": 20, "semaforo_amarillo_hasta_dias": 45,
    }, follow_redirects=False)
    assert r.status_code == 303
    cfg = db.config_dashboard()
    assert cfg == {"semaforo_verde_hasta_dias": 20, "semaforo_amarillo_hasta_dias": 45,
                   "consultas_bot_habilitado": False}
    # El semáforo del dashboard los usa al toque.
    d = admin_a.get("/admin/dashboard/semaforo", params=RANGO).json()
    assert d["umbrales"] == {"verde_hasta": 20, "amarillo_hasta": 45}
    # Umbrales incoherentes (verde >= amarillo) se ignoran.
    plataforma.post("/plataforma/config-dashboard", data={
        "semaforo_verde_hasta_dias": 50, "semaforo_amarillo_hasta_dias": 40,
    }, follow_redirects=False)
    assert db.config_dashboard()["semaforo_verde_hasta_dias"] == 20
    # Volver a los defaults para no ensuciar otros tests.
    db.set_config_dashboard(35, 60, False)
    print("OK  test_plataforma_edita_color_destacado_y_umbrales")


# ---------- campos_analiticos (lo que persiste cada recibo nuevo) ----------

def test_campos_analiticos():
    import dashboard
    recibo = {"formato": "nuevo",
              "empleado": {"categoria": " Operario B ", "cuil": "20111111119"},
              "empleador": {"cuit": "30-11111111-7"},
              "ultimo_deposito": {"fecha": "10/06/2026"}}
    resultado = {"totales": {"ingresos": 123456.78},
                 "formulas_validadas": [
                     {"ok": True, "diferencia": 999.0},
                     {"ok": False, "diferencia": -1500.5},
                     {"ok": False, "diferencia": None},   # ilegible: no suma
                     {"ok": False, "diferencia": 200.0}]}
    campos = dashboard.campos_analiticos(recibo, resultado)
    assert campos["cuit_empleador"] == "30111111117"
    assert campos["categoria"] == "Operario B"
    assert campos["formato"] == "nuevo"
    assert campos["bruto"] == 123456.78
    assert campos["monto_diferencia"] == 1700.5
    assert campos["fecha_ultimo_deposito"] == "2026-06-10"
    assert campos["procesado_en"][:4].isdigit() and " " in campos["procesado_en"]
    # Un recibo/resultado raquítico no revienta (salida de IA, no contrato).
    campos = dashboard.campos_analiticos({}, {})
    assert campos["monto_diferencia"] == 0.0 and campos["bruto"] is None
    print("OK  test_campos_analiticos")


if __name__ == "__main__":
    test_sin_sesion_403()
    test_sin_modulo_403()
    test_rangos_invalidos_422()
    test_kpis()
    test_kpis_reaccionan_a_filtros()
    test_aislamiento_totales()
    test_aislamiento_por_manipulacion_de_params()
    test_aislamiento_en_todas_las_respuestas()
    test_privacidad_recibo_no_enviado_anonimo()
    test_privacidad_en_ninguna_otra_respuesta()
    test_serie_recibos_rellena_dias_vacios()
    test_validacion_dos_estados()
    test_diferencias_empresa_top()
    test_tramites_seccional_matriz()
    test_notificaciones_por_tipo()
    test_formato_semana()
    test_semaforo()
    test_consultas_apagado_404()
    test_consultas_prendido()
    test_explorador_paginacion()
    test_explorador_tramites_dias()
    test_explorador_notificaciones_agregado()
    test_explorador_fuente_desconocida_404()
    test_catalogo_filtros()
    test_pagina_dashboard()
    test_pagina_dashboard_flag_prendido()
    test_chartjs_vendoreado_con_cache()
    test_pagina_dashboard_sin_modulo_redirige()
    test_nav_muestra_dashboard_solo_con_modulo()
    test_color_destacado_default_y_marca()
    test_plataforma_edita_color_destacado_y_umbrales()
    test_campos_analiticos()
    print("\nTodos los tests del Panel Sindical (Fase 1) pasaron.")
