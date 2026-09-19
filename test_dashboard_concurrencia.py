"""Panel Sindical — regresión del cuelgue del 2026-09-18 en Pruebas.

Un solo admin cambiando filtros (de empresa) sin esperar a que termine de
pintar dejó a la app entera sin responder: la ráfaga de requests del panel
agotó el pool de conexiones (y algunas funciones piden una segunda conexión
teniendo ya una). Reconstrucción en
docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md.

Regla que se prueba acá (C1): un request del panel nunca tiene más de UNA
conexión del pool tomada a la vez. Ni con el filtro de empresa, ni con el de
afiliado, ni en las rutas de detalle, ni en el guardián de permisos que corre
antes de todas.

Correr con: .venv/Scripts/python.exe -m pytest test_dashboard_concurrencia.py -q
"""
import os
from datetime import timedelta

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
from db import (Sindicato, UsuarioSindicato, Trabajador, Seccional, Empleador,
                ReciboVerificado, Notificacion, NotificacionDestinatario)
import main
import fechas
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlmodel import select

db.crear_tablas()

HOY = fechas.hoy()

# Los mismos endpoints que dispara refrescar() en static/dashboard.js.
ENDPOINTS = ["kpis", "serie-recibos", "validacion", "diferencias-empresa",
             "tramites-seccional", "notificaciones", "formato-semana",
             "seccionales-geo", "semaforo", "explorador/recibos",
             "explorador/tramites", "explorador/notificaciones"]

with db.get_session() as s:
    sind = Sindicato(nombre="Concurrencia Dash", slug="conc-dash", color_base="#0f1b2d",
                     modulos_habilitados=["dashboard", "tramites", "notificaciones"])
    s.add(sind)
    s.commit()
    s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20444444440", nombre="Admin Conc",
                           clave_hash=auth.hashear_clave("conc-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    secc = Seccional(sindicato_id=SID, nombre="Rosario")
    s.add(secc)
    s.commit()
    s.refresh(secc)
    empresas = []
    for i, razon in enumerate(("Metalsur SA", "Textil Belgrano", "Gráfica Sur")):
        e = Empleador(sindicato_id=SID, cuit=f"3011111{i}117", razon_social=razon)
        s.add(e)
        empresas.append(e)
    s.commit()
    for e in empresas:
        s.refresh(e)
    IDS_EMPRESAS = [e.id for e in empresas]
    CUITS = [e.cuit for e in empresas]
    for i in range(30):
        cuil = f"2011111{i:04d}9"
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, nombre=f"Trab {i}", registrado=True,
                         seccional_id=secc.id, cuit_empleador=CUITS[i % 3]))
        s.add(ReciboVerificado(
            sindicato_id=SID, cuil=cuil, periodo="2026-08", estado="OK" if i % 4 else "CON_DISCREPANCIAS",
            procesado_en=(HOY - timedelta(days=i % 20)).isoformat() + " 10:00",
            cuit_empleador=CUITS[i % 3], bruto=500000 + i * 1000,
            monto_diferencia=0 if i % 4 else 1500, formato="clasico",
            fecha_ultimo_deposito=(HOY - timedelta(days=i % 40)).isoformat(),
            enviado_sindicato=bool(i % 2)))
    s.commit()
    for criterio, valores in (("seccional", [secc.id]), ("cuit_empleador", CUITS[:2])):
        n = Notificacion(sindicato_id=SID, remitente="CD", texto=f"Aviso por {criterio}",
                         criterio=criterio, criterio_valores=valores, origen="manual",
                         enviado_en=(HOY - timedelta(days=1)).isoformat() + " 09:00",
                         cantidad_destinatarios=3)
        s.add(n)
        s.commit()
        s.refresh(n)
        for i in range(3):
            s.add(NotificacionDestinatario(notificacion_id=n.id, cuil=f"2011111{i:04d}9"))
    s.commit()
    ID_AFILIADO = s.exec(select(Trabajador).where(Trabajador.sindicato_id == SID)).first().id
    ID_RECIBO = s.exec(select(ReciboVerificado).where(ReciboVerificado.sindicato_id == SID)).first().id
    ID_NOTIF = s.exec(select(Notificacion).where(Notificacion.sindicato_id == SID)).first().id

_login = TestClient(main.app)
_login.post("/admin/login", data={"usuario": "20444444440", "clave": "conc-demo"})
COOKIES = dict(_login.cookies)
assert COOKIES, "el login del admin de prueba no dejó cookie"


def _pico_de_conexiones(url_motor, pedidos):
    """Corre los pedidos de a uno contra un engine con un pool de 5 y devuelve
    el máximo de conexiones tomadas AL MISMO TIEMPO por un solo request, más
    los códigos de estado. Un solo hilo: lo que se mide es el anidamiento
    propio del código, no la competencia entre requests."""
    motor_original = db.engine
    motor = create_engine(url_motor, pool_size=5, max_overflow=0, pool_timeout=5)
    picos = {"max": 0}

    @event.listens_for(motor, "checkout")
    def _tomada(dbapi_con, registro, proxy):
        picos["max"] = max(picos["max"], motor.pool.checkedout())

    db.engine = motor
    try:
        cliente = TestClient(main.app, cookies=COOKIES)
        resultado = []
        for ruta, params in pedidos:
            picos["max"] = 0
            r = cliente.get(ruta, params=params)
            resultado.append((ruta, dict(params).get("empresas") and "empresa"
                              or dict(params).get("afiliado") and "afiliado" or "-",
                              r.status_code, picos["max"]))
        return resultado
    finally:
        db.engine = motor_original
        motor.dispose()


def test_ningun_request_del_panel_retiene_dos_conexiones():
    base = {"desde": (HOY - timedelta(days=30)).isoformat(), "hasta": HOY.isoformat()}
    con_empresa = dict(base, empresas=",".join(str(i) for i in IDS_EMPRESAS[:2]))
    con_afiliado = dict(base, afiliado=str(ID_AFILIADO))
    pedidos = []
    for ep in ENDPOINTS:
        for params in (base, con_empresa, con_afiliado):
            pedidos.append((f"/admin/dashboard/{ep}", params))
    pedidos += [
        ("/admin/dashboard/filtros", base),
        ("/admin/dashboard/afiliados", {"q": "Trab"}),
        ("/admin/dashboard/afiliados", {"id": ID_AFILIADO}),
        ("/admin/dashboard/detalle/notificaciones",
         dict(dia=(HOY - timedelta(days=1)).isoformat(), tipo="manual")),
        (f"/admin/dashboard/detalle/notificacion/{ID_NOTIF}/destinatarios", {}),
        (f"/admin/dashboard/detalle/recibo/{ID_RECIBO}", {}),
    ]
    resultado = _pico_de_conexiones(db.engine.url, pedidos)
    for ruta, filtro, status, pico in resultado:
        print(f"{ruta:60s} {filtro:9s} -> {status}  conexiones a la vez: {pico}")
    malos = [r for r in resultado if r[2] != 200]
    excedidos = [r for r in resultado if r[3] > 1]
    assert not malos, f"respuestas que no son 200: {malos[:5]}"
    assert not excedidos, f"requests que retuvieron más de una conexión: {excedidos[:5]}"
