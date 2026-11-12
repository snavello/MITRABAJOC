"""Entradas de la Fiesta (PLAN_FIESTA.md): el motor puro, el acceso a datos y
las rutas, con MercadoPago en modo simulado (MP_MOCK=1). Nada sale a la red.

Correr con: python -m pytest test_fiesta.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import threading
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import select

import auth
import db
import entorno
import fechas
import fiesta
import main
import mercadopago
import qr

db.crear_tablas()
SECRETO = "secreto-webhook-de-prueba"
API = "/api/fiesta"
SIND = "/api/fiesta/sindicato"


# =====================================================================
# Motor puro
# =====================================================================
def _res(cantidad, estado="pagada", vence=""):
    return {"cantidad": cantidad, "estado": estado, "vence": vence}


def test_disponibilidad_cuenta_pagadas_y_pendientes_vigentes():
    ahora = "2026-11-12 12:00:00"
    reservas = [_res(4), _res(2, "pendiente", "2026-11-12 12:30:00"),
                _res(3, "pendiente", "2026-11-12 11:00:00"),     # ya venció: no cuenta
                _res(5, "vencida"), _res(1, "anulada")]
    assert fiesta.ocupadas(reservas, ahora) == 6
    assert fiesta.disponibles(10, reservas, ahora) == 4
    assert fiesta.disponibles(5, reservas, ahora) == 0          # nunca negativo


def test_tope_por_afiliado_es_acumulado():
    previas = [_res(2), _res(1, "vencida"), _res(1, "anulada")]
    assert fiesta.disponibles_afiliado(4, previas) == 2
    assert fiesta.maximo_reservable(1000, 4, [], previas) == 2
    assert fiesta.maximo_reservable(1, 4, [_res(0)], []) == 1    # manda el general


def test_ventana_de_habilitacion():
    evento = "2026-11-14T21:00"
    antes = fechas.ahora().replace(year=2026, month=11, day=13, hour=20, minute=59)
    despues = antes + timedelta(minutes=2)
    assert fiesta.ventana_entrada(evento, 24, antes)[0] is False
    ok, desde = fiesta.ventana_entrada(evento, 24, despues)
    assert ok is True and desde == "2026-11-13T21:00"
    assert fiesta.fecha_corta(desde) == "13/11 a las 21:00"
    assert fiesta.ventana_entrada("", 24)[0] is True            # sin fecha, no se traba


def test_textos_en_castellano():
    assert fiesta.fecha_texto("2026-11-14T21:00") == "sábado 14 de noviembre, 21:00"
    assert fiesta.fecha_texto("2026-11-14") == "sábado 14 de noviembre"
    assert fiesta.numero_reserva(123) == "R-000123"
    assert fiesta.leyenda_entrada("cortesia") == "Invitado Especial"
    assert fiesta.leyenda_entrada("cortesia", "Prensa") == "Prensa"
    assert fiesta.leyenda_entrada("afiliado", "Prensa") == ""


def test_contenido_y_lectura_del_qr():
    url = fiesta.contenido_qr("https://pruebas.test/", "tok_en-1", "1700.abc")
    assert url == "https://pruebas.test/fiesta/e/tok_en-1?k=1700.abc"
    assert fiesta.leer_qr(url) == ("tok_en-1", "1700.abc")
    assert fiesta.leer_qr("tok_en-1?k=1700.abc") == ("tok_en-1", "1700.abc")
    assert fiesta.leer_qr("hola") == ("", "")


def test_csv_del_padron_con_y_sin_cabecera_y_separadores():
    con = fiesta.parsear_padron("legajo;dni;nombre;mail\n10;12.345.678;Ana Pérez;ana@x.com\n"
                                "11;9876543;Luis;\n")
    assert [f["legajo"] for f in con["filas"]] == ["10", "11"] and con["filas"][0]["dni"] == "12345678"
    sin = fiesta.parsear_padron("20,22333444,Rita Gómez,rita@x.com")
    assert sin["filas"][0]["nombre"] == "Rita Gómez" and not sin["errores"]
    assert fiesta.parsear_padron("﻿legajo;dni;nombre\n1;12345678;A")["filas"][0]["legajo"] == "1"


def test_csv_del_padron_errores_fila_por_fila():
    r = fiesta.parsear_padron("1;123;Corto;\n2;12345678;;\n3;12345678;Ok;mal-mail\n"
                              "4;12345678;Bien;\n4;22345678;Repetido;\n5;12345678\n")
    assert [f["legajo"] for f in r["filas"]] == ["4"]
    por_linea = {e["linea"]: e["motivo"] for e in r["errores"]}
    assert "DNI" in por_linea[1] and "nombre" in por_linea[2] and "mail" in por_linea[3]
    assert "repetido" in por_linea[5] and "columnas" in por_linea[6]


# =====================================================================
# Datos de prueba
# =====================================================================
class Fest:
    pass


def _armar(tope_general=10, tope_afiliado=4, vence_min=30, fecha_en_horas=2, horas_antes=24):
    """Un evento activo nuevo (los anteriores quedan inactivos), tres afiliados y
    un operador admin y otro de puerta. Devuelve ids."""
    f = Fest()
    with db.get_session() as s:
        s.exec(db.text("UPDATE fiestaevento SET activo = false"))
        ev = db.FiestaEvento(
            nombre="Fiesta de Prueba", fecha_hora=(fechas.ahora() + timedelta(hours=fecha_en_horas)).strftime("%Y-%m-%dT%H:%M"),
            lugar="Palacio", precio=30000, tope_general=tope_general, tope_por_afiliado=tope_afiliado,
            horas_antes=horas_antes, minutos_vencimiento=vence_min)
        s.add(ev)
        s.commit()
        s.refresh(ev)
        f.ev = ev.id
        for n, (leg, dni, nom) in enumerate([("100", "11111111", "Ana Pérez"), ("200", "22222222", "Beto Díaz"),
                                             ("300", "33333333", "Cora Ríos")]):
            p = db.FiestaPadron(evento_id=ev.id, legajo=leg, dni=dni, nombre=nom, mail="")
            s.add(p)
        s.add(db.FiestaOperador(evento_id=ev.id, usuario="jefe", nombre="Jefa", rol="admin",
                                clave_hash=auth.hashear_clave("clave-jefe-1"), debe_cambiar_clave=False))
        s.add(db.FiestaOperador(evento_id=ev.id, usuario="puerta1", nombre="Puerta", rol="puerta",
                                clave_hash=auth.hashear_clave("clave-puerta-1"), debe_cambiar_clave=False))
        s.commit()
        f.padron = {p.legajo: p.id for p in s.exec(select(db.FiestaPadron).where(db.FiestaPadron.evento_id == ev.id)).all()}
    return f


@pytest.fixture
def fest(monkeypatch):
    monkeypatch.setenv("MP_MOCK", "1")
    monkeypatch.setenv("MP_WEBHOOK_SECRET", SECRETO)
    monkeypatch.delenv("MP_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", True)
    main._intentos_fiesta.clear()
    main._intentos_fiesta_op.clear()
    return _armar()


def _afiliado(legajo="100", dni="11111111"):
    c = TestClient(main.app)
    r = c.post(API + "/entrar", json={"legajo": legajo, "dni": dni})
    assert r.status_code == 200, r.text
    return c


def _operador(usuario="jefe", clave="clave-jefe-1"):
    c = TestClient(main.app)
    r = c.post(SIND + "/entrar", json={"usuario": usuario, "clave": clave})
    assert r.status_code == 200, r.text
    return c


def _reservar(c, cantidad):
    return c.post(API + "/reservar", json={"cantidad": cantidad})


def _pagar_simulado(c, reserva_id, resultado="aprobar"):
    return c.post(f"{API}/mp-simulado/{reserva_id}", json={"resultado": resultado})


def _reserva_pagada(f, legajo="100", dni="11111111", cantidad=2):
    c = _afiliado(legajo, dni)
    rid = _reservar(c, cantidad).json()["reserva_id"]
    assert _pagar_simulado(c, rid).json()["estado"] == "pagada"
    return c, rid


def _token(rid):
    with db.get_session() as s:
        return s.get(db.FiestaReserva, rid).token


def _estado_reserva(rid):
    with db.get_session() as s:
        return s.get(db.FiestaReserva, rid).estado


# =====================================================================
# Entorno y sesiones
# =====================================================================
def test_404_en_demo(fest, monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = TestClient(main.app)
    for ruta in ("/fiesta", "/fiesta/sindicato", API + "/estado", SIND + "/resumen",
                 "/fiesta/mp-simulado/1", "/fiesta/e/abc", "/fiesta/pago/vuelta?reserva=1"):
        assert c.get(ruta, follow_redirects=False).status_code == 404, ruta
    assert c.post(API + "/mp/webhook").status_code == 404
    assert c.post(API + "/entrar", json={"legajo": "100", "dni": "11111111"}).status_code == 404


def test_las_dos_cookies_estan_en_el_mapa_de_roles():
    assert main.COOKIES_POR_ROL["fiesta"] == "sesion_fiesta"
    assert main.COOKIES_POR_ROL["fiesta_op"] == "sesion_fiesta_op"


def test_login_afiliado_ok_y_error_que_no_dice_cual_esta_mal(fest):
    c = TestClient(main.app)
    assert c.get(API + "/estado").status_code == 401
    mal_legajo = c.post(API + "/entrar", json={"legajo": "999", "dni": "11111111"})
    mal_dni = c.post(API + "/entrar", json={"legajo": "100", "dni": "99999999"})
    assert mal_legajo.status_code == mal_dni.status_code == 401
    assert mal_legajo.json() == mal_dni.json() and mal_legajo.json()["codigo"] == "E-FIESTA-01"
    ok = c.post(API + "/entrar", json={"legajo": " 100 ", "dni": "11.111.111"})
    assert ok.status_code == 200 and "sesion_fiesta" in ok.headers.get("set-cookie", "")
    assert c.get(API + "/estado").status_code == 200
    c.post(API + "/salir")
    assert c.get(API + "/estado").status_code == 401


def test_login_afiliado_inactivo_no_entra(fest):
    with db.get_session() as s:
        p = s.get(db.FiestaPadron, fest.padron["100"])
        p.activo = False
        s.add(p)
        s.commit()
    r = TestClient(main.app).post(API + "/entrar", json={"legajo": "100", "dni": "11111111"})
    assert r.status_code == 401


def test_freno_por_ip_en_los_dos_logins(fest):
    c = TestClient(main.app)
    for _ in range(main.LOGIN_MAX_FALLOS):
        assert c.post(API + "/entrar", json={"legajo": "x", "dni": "y"}).status_code == 401
    assert c.post(API + "/entrar", json={"legajo": "100", "dni": "11111111"}).status_code == 429
    c2 = TestClient(main.app)
    for _ in range(main.LOGIN_MAX_FALLOS):
        assert c2.post(SIND + "/entrar", json={"usuario": "jefe", "clave": "mal"}).status_code == 401
    assert c2.post(SIND + "/entrar", json={"usuario": "jefe", "clave": "clave-jefe-1"}).status_code == 429


def test_login_operador(fest):
    c = TestClient(main.app)
    r = c.post(SIND + "/entrar", json={"usuario": "jefe", "clave": "mal"})
    assert r.status_code == 401 and r.json()["codigo"] == "E-FIESTA-10"
    ok = c.post(SIND + "/entrar", json={"usuario": "JEFE", "clave": "clave-jefe-1"})
    assert ok.json()["rol"] == "admin" and ok.json()["debe_cambiar_clave"] is False
    assert "sesion_fiesta_op" in ok.headers.get("set-cookie", "")


def test_operador_con_clave_transitoria_debe_cambiarla(fest):
    with db.get_session() as s:
        s.add(db.FiestaOperador(evento_id=fest.ev, usuario="nuevo", nombre="N", rol="puerta",
                                clave_hash=auth.hashear_clave("transitoria"), debe_cambiar_clave=True))
        s.commit()
    c = _operador("nuevo", "transitoria")
    assert c.get(SIND + "/resumen").status_code == 403                    # hasta elegir clave
    assert c.post(SIND + "/clave", json={"actual": "transitoria", "nueva": "corta", "repetir": "corta"}).status_code == 400
    assert c.post(SIND + "/clave", json={"actual": "transitoria", "nueva": "unaclavenueva", "repetir": "otra"}).status_code == 400
    assert c.post(SIND + "/clave", json={"actual": "transitoria", "nueva": "transitoria", "repetir": "transitoria"}).status_code == 400
    assert c.post(SIND + "/clave", json={"actual": "mal", "nueva": "unaclavenueva", "repetir": "unaclavenueva"}).status_code == 400
    assert c.post(SIND + "/clave", json={"actual": "transitoria", "nueva": "unaclavenueva", "repetir": "unaclavenueva"}).status_code == 200
    assert c.get(SIND + "/resumen").status_code == 200
    assert TestClient(main.app).post(SIND + "/entrar", json={"usuario": "nuevo", "clave": "unaclavenueva"}).status_code == 200


def test_cookies_de_fiesta_no_abren_admin_ni_al_reves(fest):
    afil, op = _afiliado(), _operador()
    anonimo = TestClient(main.app).get("/admin", follow_redirects=False)
    for c in (afil, op):
        r = c.get("/admin", follow_redirects=False)
        assert (r.status_code, r.text) == (anonimo.status_code, anonimo.text)     # sigue viendo el login
        assert c.get("/admin/dashboard/kpis", follow_redirects=False).status_code in (303, 401, 403)
    assert afil.get(SIND + "/resumen").status_code == 401           # el afiliado no es operador
    assert op.get(API + "/estado").status_code == 401               # ni el operador, afiliado
    # una sesión de otro rol (sindicato) tampoco sirve
    otro = TestClient(main.app)
    otro.cookies.set(main.COOKIES_POR_ROL["sindicato"], auth.crear_sesion("sindicato", 1, 1))
    assert otro.get(SIND + "/resumen").status_code == 401
    assert otro.get(API + "/estado").status_code == 401


def test_rol_puerta_solo_puede_lo_suyo(fest):
    p = _operador("puerta1", "clave-puerta-1")
    assert p.get(SIND + "/resumen").status_code == 200
    assert p.get(SIND + "/buscar?q=Perez").status_code == 200
    for metodo, ruta in (("get", "/reservas"), ("get", "/padron"), ("get", "/configuracion"),
                         ("get", "/operadores"), ("post", "/cortesia"), ("post", "/operador"),
                         ("post", "/configuracion"), ("post", "/padron"), ("post", "/foto")):
        r = getattr(p, metodo)(SIND + ruta) if metodo == "get" else p.post(SIND + ruta, json={})
        assert r.status_code == 403, ruta
    assert p.get("/fiesta/sindicato/reservas.csv").status_code == 403


# =====================================================================
# Reservas: cupo, topes, vencimiento
# =====================================================================
def test_reservar_descuenta_y_devuelve_el_checkout_simulado(fest):
    c = _afiliado()
    antes = c.get(API + "/estado").json()
    assert antes["disponibles_generales"] == 10 and antes["disponibles_mias"] == 4
    r = _reservar(c, 3)
    assert r.status_code == 200 and r.json()["init_point"].endswith(f"/fiesta/mp-simulado/{r.json()['reserva_id']}")
    d = c.get(API + "/estado").json()
    assert d["disponibles_generales"] == 7 and d["disponibles_mias"] == 1
    fila = d["reservas"][0]
    assert fila["estado"] == "pendiente" and fila["importe"] == 90000 and fila["url_pago"].startswith("/fiesta/mp-simulado/")
    assert fila["vence_en"] > 0 and fila["url_entrada"] == ""


def test_tope_por_afiliado_acumulado(fest):
    c = _afiliado()
    assert _reservar(c, 3).status_code == 200
    r = _reservar(c, 2)
    assert r.status_code == 409 and r.json()["codigo"] == "E-FIESTA-03"
    assert _reservar(c, 1).status_code == 200
    assert _reservar(c, 1).json()["codigo"] == "E-FIESTA-03"


def test_anulada_y_vencida_no_cuentan_para_el_tope(fest):
    c = _afiliado()
    rid = _reservar(c, 4).json()["reserva_id"]
    assert _reservar(c, 1).json()["codigo"] == "E-FIESTA-03"
    assert c.post(f"{API}/reserva/{rid}/anular").status_code == 200
    assert _reservar(c, 4).status_code == 200


def test_sin_cupo_general(fest):
    a, b = _afiliado("100", "11111111"), _afiliado("200", "22222222")
    with db.get_session() as s:
        e = s.get(db.FiestaEvento, fest.ev)
        e.tope_general = 5
        s.add(e)
        s.commit()
    assert _reservar(a, 4).status_code == 200
    r = _reservar(b, 2)
    assert r.status_code == 409 and r.json()["codigo"] == "E-FIESTA-02"
    assert _reservar(b, 1).status_code == 200
    assert b.get(API + "/estado").json()["disponibles_generales"] == 0


def test_cantidad_invalida(fest):
    c = _afiliado()
    for malo in (0, -1, "x", None, 1.5):
        assert _reservar(c, malo).status_code == 400 or _reservar(c, malo).status_code == 422


def test_concurrencia_de_las_ultimas_entradas(fest):
    """Seis personas piden la última entrada a la vez, con tope 3: entran 3."""
    with db.get_session() as s:
        e = s.get(db.FiestaEvento, fest.ev)
        e.tope_general = 3
        s.add(e)
        for i in range(6):
            s.add(db.FiestaPadron(evento_id=fest.ev, legajo=f"c{i}", dni=f"4000000{i}", nombre=f"Conc {i}"))
        s.commit()
        ids = [p.id for p in s.exec(select(db.FiestaPadron).where(
            db.FiestaPadron.evento_id == fest.ev, db.FiestaPadron.legajo.like("c%"))).all()]
    resultados, barrera = [], threading.Barrier(len(ids))

    def pedir(padron_id):
        with db.get_session() as s:
            ev = db.fiesta_evento_activo(s)
            p = s.get(db.FiestaPadron, padron_id)
            barrera.wait()
            try:
                db.fiesta_crear_reserva(s, ev, p, 1)
                resultados.append("ok")
            except HTTPException as e:
                resultados.append(getattr(e, "codigo", str(e.status_code)))
    hilos = [threading.Thread(target=pedir, args=(i,)) for i in ids]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert resultados.count("ok") == 3 and resultados.count("E-FIESTA-02") == 3
    with db.get_session() as s:
        assert db.fiesta_disponibles(s, db.fiesta_evento_activo(s)) == 0


def test_vencimiento_perezoso_devuelve_el_cupo(fest):
    c = _afiliado()
    rid = _reservar(c, 4).json()["reserva_id"]
    assert c.get(API + "/estado").json()["disponibles_generales"] == 6
    with db.get_session() as s:
        r = s.get(db.FiestaReserva, rid)
        r.vence = fiesta.sello(fechas.ahora() - timedelta(minutes=1))
        s.add(r)
        s.commit()
    d = c.get(API + "/estado").json()
    assert d["disponibles_generales"] == 10 and d["disponibles_mias"] == 4
    assert d["reservas"][0]["estado"] == "vencida" and _estado_reserva(rid) == "vencida"
    assert c.post(f"{API}/reserva/{rid}/anular").status_code == 409     # ya no está pendiente


def test_el_evento_define_cuanto_dura_la_reserva(fest):
    with db.get_session() as s:
        e = s.get(db.FiestaEvento, fest.ev)
        e.minutos_vencimiento = 5
        s.add(e)
        s.commit()
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    vence_en = c.get(f"{API}/reserva/{rid}").json()["vence_en"]
    assert 200 < vence_en <= 300


def test_reserva_ajena_es_404(fest):
    a, b = _afiliado("100", "11111111"), _afiliado("200", "22222222")
    rid = _reservar(a, 1).json()["reserva_id"]
    assert b.get(f"{API}/reserva/{rid}").status_code == 404
    assert b.post(f"{API}/reserva/{rid}/anular").status_code == 404
    assert b.get(f"/fiesta/entrada/{rid}").status_code == 404
    assert b.get(f"/fiesta/mp-simulado/{rid}").status_code == 404
    assert b.post(f"{API}/mp-simulado/{rid}", json={"resultado": "aprobar"}).status_code == 404


def test_cobro_apagado_responde_e_fiesta_05(fest, monkeypatch):
    monkeypatch.delenv("MP_MOCK", raising=False)
    c = _afiliado()
    r = _reservar(c, 1)
    assert r.status_code == 503 and r.json()["codigo"] == "E-FIESTA-05"
    assert c.get(API + "/estado").json()["disponibles_generales"] == 10      # no reservó nada


def test_si_mercadopago_no_responde_la_reserva_se_anula(fest, monkeypatch):
    monkeypatch.delenv("MP_MOCK", raising=False)
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")
    monkeypatch.setattr(mercadopago, "crear_preferencia", lambda *a, **k: None)
    c = _afiliado()
    r = _reservar(c, 2)
    assert r.status_code == 502 and r.json()["codigo"] == "E-FIESTA-04"
    assert c.get(API + "/estado").json()["disponibles_generales"] == 10
    with db.get_session() as s:
        assert s.exec(select(db.FiestaReserva).where(db.FiestaReserva.evento_id == fest.ev)).first().estado == "anulada"


def test_modo_real_guarda_la_preferencia(fest, monkeypatch):
    monkeypatch.delenv("MP_MOCK", raising=False)
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")
    visto = {}

    def _pref(reserva_id, titulo, importe, base, vence):
        visto.update(reserva_id=reserva_id, titulo=titulo, importe=importe, base=base, vence=vence)
        return {"id": "PREF-9", "init_point": "https://mp.test/pagar"}
    monkeypatch.setattr(mercadopago, "crear_preferencia", _pref)
    c = _afiliado()
    r = _reservar(c, 2).json()
    assert r["init_point"] == "https://mp.test/pagar"
    assert visto["importe"] == 60000 and visto["titulo"].endswith("×2") and visto["vence"].endswith("-03:00")
    fila = c.get(f"{API}/reserva/{r['reserva_id']}").json()
    assert fila["url_pago"] == "https://mp.test/pagar"     # el guardado, no uno reconstruido


# =====================================================================
# Pago: simulado y webhook (el mismo camino)
# =====================================================================
def test_pago_simulado_aprobado_rechazado_y_pendiente(fest):
    c = _afiliado()
    rid = _reservar(c, 2).json()["reserva_id"]
    assert _pagar_simulado(c, rid, "rechazar").json()["estado"] == "pendiente"
    assert _pagar_simulado(c, rid, "pendiente").json()["estado"] == "pendiente"
    assert c.post(f"{API}/mp-simulado/{rid}", json={"resultado": "nada"}).status_code == 400
    res = _pagar_simulado(c, rid, "aprobar").json()
    assert res["estado"] == "pagada" and res["vuelta"] == f"/fiesta#reserva-{rid}"
    fila = c.get(f"{API}/reserva/{rid}").json()
    assert fila["estado"] == "pagada" and fila["url_entrada"] == f"/fiesta/entrada/{rid}" and fila["pagada_en"]
    assert fila["mp_estado"] == "approved"


def test_la_pagina_simulada_solo_existe_con_mock(fest, monkeypatch):
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    assert c.get(f"/fiesta/mp-simulado/{rid}").status_code == 200
    monkeypatch.delenv("MP_MOCK")
    assert c.get(f"/fiesta/mp-simulado/{rid}").status_code == 404
    assert c.post(f"{API}/mp-simulado/{rid}", json={"resultado": "aprobar"}).status_code == 404


def _webhook(c, payment_id, firmar=True, tipo="payment", secreto=SECRETO, request_id="req-1"):
    cabeceras = {"x-request-id": request_id}
    if firmar:
        cabeceras["x-signature"] = mercadopago.firmar(payment_id, request_id, "1700000000", secreto)
    return c.post(f"{API}/mp/webhook?data.id={payment_id}&type={tipo}", headers=cabeceras)


def test_webhook_sin_firma_o_con_firma_mala_es_401(fest):
    c = TestClient(main.app)
    rid = 1
    mercadopago.registrar_pago_mock("WH-1", "approved", rid, 1)
    assert _webhook(c, "WH-1", firmar=False).status_code == 401
    assert _webhook(c, "WH-1", secreto="otro").status_code == 401


def test_webhook_sin_secreto_configurado_falla_cerrado(fest, monkeypatch):
    monkeypatch.delenv("MP_WEBHOOK_SECRET")
    assert _webhook(TestClient(main.app), "WH-2").status_code == 401


def test_webhook_firmado_marca_pagada_y_es_idempotente(fest):
    c = _afiliado()
    rid = _reservar(c, 2).json()["reserva_id"]
    mercadopago.registrar_pago_mock("WH-PAGO-1", "approved", rid, 60000)
    anon = TestClient(main.app)
    r = _webhook(anon, "WH-PAGO-1")
    assert r.status_code == 200 and r.json()["resultado"] == "pagada"
    assert _estado_reserva(rid) == "pagada"
    r2 = _webhook(anon, "WH-PAGO-1")                     # MercadoPago reintenta
    assert r2.status_code == 200 and r2.json()["resultado"] == "duplicado"
    with db.get_session() as s:
        avisos = s.exec(select(db.FiestaAvisoPago).where(db.FiestaAvisoPago.mp_payment_id == "WH-PAGO-1")).all()
        assert len(avisos) == 1 and avisos[0].procesado


def test_webhook_otro_tipo_no_hace_nada(fest):
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    mercadopago.registrar_pago_mock("WH-OTRO", "approved", rid, 30000)
    r = _webhook(TestClient(main.app), "WH-OTRO", tipo="merchant_order")
    assert r.status_code == 200 and r.json().get("ignorado")
    assert _estado_reserva(rid) == "pendiente"


def test_webhook_pago_que_no_se_puede_consultar_pide_reintento(fest):
    assert _webhook(TestClient(main.app), "NO-EXISTE-9").status_code == 503


def test_monto_distinto_no_marca_pagada(fest):
    c = _afiliado()
    rid = _reservar(c, 2).json()["reserva_id"]
    mercadopago.registrar_pago_mock("WH-MONTO", "approved", rid, 100)
    r = _webhook(TestClient(main.app), "WH-MONTO")
    assert r.status_code == 200 and "monto distinto" in r.json()["resultado"]
    assert _estado_reserva(rid) == "pendiente"
    with db.get_session() as s:
        aviso = s.exec(select(db.FiestaAvisoPago).where(db.FiestaAvisoPago.mp_payment_id == "WH-MONTO")).first()
        assert aviso.procesado and "monto distinto" in aviso.resultado


def test_pago_rechazado_deja_la_reserva_pendiente(fest):
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    mercadopago.registrar_pago_mock("WH-RECH", "rejected", rid, 30000)
    assert _webhook(TestClient(main.app), "WH-RECH").status_code == 200
    assert _estado_reserva(rid) == "pendiente"
    # y la persona puede volver a intentar y pagar
    mercadopago.registrar_pago_mock("WH-RECH2", "approved", rid, 30000)
    _webhook(TestClient(main.app), "WH-RECH2")
    assert _estado_reserva(rid) == "pagada"


def test_d9_pago_aprobado_sobre_reserva_vencida_se_toma_y_marca_sobrecupo(fest):
    with db.get_session() as s:
        e = s.get(db.FiestaEvento, fest.ev)
        e.tope_general = 4
        s.add(e)
        s.commit()
    a, b = _afiliado("100", "11111111"), _afiliado("200", "22222222")
    rid_a = _reservar(a, 4).json()["reserva_id"]
    with db.get_session() as s:                                    # a venció sin pagar
        r = s.get(db.FiestaReserva, rid_a)
        r.vence = fiesta.sello(fechas.ahora() - timedelta(minutes=5))
        s.add(r)
        s.commit()
    rid_b = _reservar(b, 4).json()["reserva_id"]                    # b se llevó el cupo
    assert _estado_reserva(rid_a) == "vencida"
    mercadopago.registrar_pago_mock("WH-D9", "approved", rid_a, 120000)
    assert _webhook(TestClient(main.app), "WH-D9").json()["resultado"].startswith("pagada tarde")
    with db.get_session() as s:
        ra, rb = s.get(db.FiestaReserva, rid_a), s.get(db.FiestaReserva, rid_b)
        assert ra.estado == "pagada" and ra.sobrecupo is True
        assert rb.sobrecupo is False
    op = _operador()
    assert op.get(SIND + "/resumen").json()["contadores"]["sobrecupo"] == 1
    assert op.get(SIND + "/resumen").json()["contadores"]["disponibles"] == 0     # nunca negativo


def test_d9_vencida_con_lugar_se_toma_sin_sobrecupo(fest):
    c = _afiliado()
    rid = _reservar(c, 2).json()["reserva_id"]
    with db.get_session() as s:
        r = s.get(db.FiestaReserva, rid)
        r.vence = fiesta.sello(fechas.ahora() - timedelta(minutes=5))
        s.add(r)
        s.commit()
    c.get(API + "/estado")                                           # la vence
    assert _estado_reserva(rid) == "vencida"
    mercadopago.registrar_pago_mock("WH-D9B", "approved", rid, 60000)
    _webhook(TestClient(main.app), "WH-D9B")
    with db.get_session() as s:
        r = s.get(db.FiestaReserva, rid)
        assert r.estado == "pagada" and r.sobrecupo is False


# =====================================================================
# La entrada y la verificación pública
# =====================================================================
def test_entrada_habilitada_trae_qr_y_verifica(fest):
    c, rid = _reserva_pagada(fest, cantidad=3)
    r = c.get(f"/fiesta/entrada/{rid}")
    assert r.status_code == 200
    j = c.get(f"{API}/entrada/{rid}/qr")
    assert j.status_code == 200 and "<svg" in j.json()["svg"] and j.json()["vence_en"] == qr.TTL_QR_SEGUNDOS
    url = j.json()["url_verificar"]
    token, k = fiesta.leer_qr(url)
    assert token == _token(rid)
    v = TestClient(main.app).get(f"/fiesta/e/{token}?k={k}")
    assert v.status_code == 200


def test_entrada_en_espera_no_da_qr(fest):
    f2 = _armar(fecha_en_horas=24 * 30, horas_antes=24)
    c, rid = _reserva_pagada(f2)
    assert c.get(f"/fiesta/entrada/{rid}").status_code == 200
    r = c.get(f"{API}/entrada/{rid}/qr")
    assert r.status_code == 403 and r.json()["codigo"] == "E-FIESTA-06"
    fila = c.get(f"{API}/reserva/{rid}").json()
    assert fila["entrada_habilitada"] is False and fila["entrada_desde"]


def test_entrada_pendiente_vuelve_a_la_reserva_y_vencida_no_se_muestra(fest):
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    r = c.get(f"/fiesta/entrada/{rid}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/fiesta#reserva-{rid}"
    assert c.get(f"{API}/entrada/{rid}/qr").status_code == 409
    c.post(f"{API}/reserva/{rid}/anular")
    assert c.get(f"/fiesta/entrada/{rid}").status_code == 404


def test_entrada_sin_sesion_va_al_login(fest):
    c, rid = _reserva_pagada(fest)
    anon = TestClient(main.app)
    assert anon.get(f"/fiesta/entrada/{rid}", follow_redirects=False).status_code == 303
    assert anon.get(f"{API}/entrada/{rid}/qr").status_code == 404
    assert anon.get(f"/fiesta/entrada/{rid}?t=token-falso").status_code == 404


def test_verificacion_publica_sin_codigo_o_vencido_no_muestra_nada(fest):
    c, rid = _reserva_pagada(fest)
    token = _token(rid)
    anon = TestClient(main.app)
    sin_k = anon.get(f"/fiesta/e/{token}")
    assert sin_k.status_code == 200 and "Ana Pérez" not in sin_k.text
    vencido = anon.get(f"/fiesta/e/{token}?k={qr.codigo_efimero(token, ttl=-5)[0]}")
    assert "Ana Pérez" not in vencido.text
    falso = anon.get(f"/fiesta/e/{token}?k=123.abc")
    assert "Ana Pérez" not in falso.text
    bueno = anon.get(f"/fiesta/e/{token}?k={qr.codigo_efimero(token)[0]}")
    assert "Ana Pérez" in bueno.text
    assert anon.get("/fiesta/e/no-existe?k=1.a").status_code == 200


def test_pagina_del_afiliado_y_del_sindicato_cargan(fest):
    anon = TestClient(main.app)
    assert anon.get("/fiesta").status_code == 200
    assert anon.get("/fiesta/sindicato").status_code == 200
    c = _afiliado()
    assert c.get("/fiesta").status_code == 200
    assert _operador().get("/fiesta/sindicato").status_code == 200


def test_pagina_sin_evento_no_rompe(fest):
    with db.get_session() as s:
        s.exec(db.text("UPDATE fiestaevento SET activo = false"))
        s.commit()
    anon = TestClient(main.app)
    assert anon.get("/fiesta").status_code == 200
    assert anon.get("/fiesta/sindicato").status_code == 200
    assert anon.post(API + "/entrar", json={"legajo": "1", "dni": "2"}).status_code == 404


def test_vuelta_de_mercadopago_redirige_a_la_pantalla(fest):
    r = TestClient(main.app).get("/fiesta/pago/vuelta?reserva=7&estado=success", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/fiesta#reserva-7"


# =====================================================================
# Cortesías
# =====================================================================
def test_cortesia_descuenta_del_tope_y_se_ve_por_token(fest):
    op = _operador()
    r = op.post(SIND + "/cortesia", json={"nombre": "Ministra Gómez", "dni": "27.123.456", "cantidad": 2})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "/fiesta/entrada/" in j["url_entrada"] and "?t=" in j["url_entrada"] and j["mail_enviado"] is False
    rid = j["reserva_id"]
    with db.get_session() as s:
        res = s.get(db.FiestaReserva, rid)
        assert res.tipo == "cortesia" and res.estado == "pagada" and res.importe == 0 and res.vence == ""
        assert res.leyenda == "Invitado Especial"
    assert op.get(SIND + "/resumen").json()["contadores"]["disponibles"] == 8
    anon = TestClient(main.app)
    assert anon.get(f"/fiesta/entrada/{rid}?t={_token(rid)}").status_code == 200
    qr_json = anon.get(f"{API}/entrada/{rid}/qr?t={_token(rid)}")
    assert qr_json.status_code == 200
    assert op.post(f"{SIND}/reserva/{rid}/anular").status_code == 200
    assert op.get(SIND + "/resumen").json()["contadores"]["disponibles"] == 10


def test_cortesia_con_leyenda_propia_y_validaciones(fest):
    op = _operador()
    ok = op.post(SIND + "/cortesia", json={"nombre": "Prensa", "dni": "30111222", "cantidad": 1, "leyenda": "Prensa"})
    with db.get_session() as s:
        assert s.get(db.FiestaReserva, ok.json()["reserva_id"]).leyenda == "Prensa"
    assert op.post(SIND + "/cortesia", json={"nombre": "", "dni": "30111222"}).status_code == 400
    assert op.post(SIND + "/cortesia", json={"nombre": "X", "dni": "12"}).status_code == 400
    assert op.post(SIND + "/cortesia", json={"nombre": "X", "dni": "30111222", "cantidad": 99}).status_code == 409


def test_cortesia_manda_mail_si_el_canal_esta_prendido(fest, monkeypatch):
    enviados = []
    monkeypatch.setattr(main.correo, "habilitado", lambda: True)
    monkeypatch.setattr(main.correo, "enviar", lambda d, a, t: enviados.append((d, a, t)) or True)
    r = _operador().post(SIND + "/cortesia", json={"nombre": "Ana", "dni": "30111222", "mail": "ana@x.com"})
    assert r.json()["mail_enviado"] is True and enviados[0][0] == "ana@x.com"
    assert r.json()["url_entrada"] in enviados[0][2]


# =====================================================================
# Puerta: ingreso por QR y por documento
# =====================================================================
def _qr_de(rid):
    token = _token(rid)
    return {"token": token, "k": qr.codigo_efimero(token)[0]}


def test_ingreso_por_qr_total_y_segundo_escaneo_rechazado(fest):
    _, rid = _reserva_pagada(fest, cantidad=3)
    puerta = _operador("puerta1", "clave-puerta-1")
    r = puerta.post(SIND + "/ingreso/qr", json=_qr_de(rid))
    assert r.status_code == 200 and r.json()["ingresaron"] == 3 and r.json()["faltan"] == 0
    assert r.json()["reserva"]["nombre"] == "Ana Pérez"
    r2 = puerta.post(SIND + "/ingreso/qr", json=_qr_de(rid))
    assert r2.status_code == 409 and r2.json()["codigo"] == "E-FIESTA-08"
    with db.get_session() as s:
        res = s.get(db.FiestaReserva, rid)
        assert res.ingresados == 3 and res.ultimo_ingreso
        ing = s.exec(select(db.FiestaIngreso).where(db.FiestaIngreso.reserva_id == rid)).all()
        assert len(ing) == 1 and ing[0].modo == "qr" and ing[0].quien == "puerta1"


def test_ingreso_parcial_y_ambar(fest):
    _, rid = _reserva_pagada(fest, cantidad=4)
    puerta = _operador("puerta1", "clave-puerta-1")
    mirar = puerta.post(SIND + "/ingreso/qr", json={**_qr_de(rid), "solo_verificar": True}).json()
    assert mirar["registrado"] is False and mirar["faltan"] == 4
    r = puerta.post(SIND + "/ingreso/qr", json={**_qr_de(rid), "cantidad": 2})
    assert r.json()["ya_ingresados"] == 0 and r.json()["faltan"] == 2
    segundo = puerta.post(SIND + "/ingreso/qr", json=_qr_de(rid)).json()
    assert segundo["ya_ingresados"] == 2 and segundo["ingresaron"] == 2 and segundo["faltan"] == 0
    assert puerta.post(SIND + "/ingreso/qr", json={**_qr_de(rid), "cantidad": 9}).status_code in (400, 409)


def test_ingreso_acepta_el_texto_entero_del_qr(fest):
    _, rid = _reserva_pagada(fest, cantidad=1)
    q = _qr_de(rid)
    texto = fiesta.contenido_qr("https://pruebas.test", q["token"], q["k"])
    r = _operador("puerta1", "clave-puerta-1").post(SIND + "/ingreso/qr", json={"texto": texto})
    assert r.status_code == 200 and r.json()["ingresaron"] == 1


def test_qr_vencido_o_falso_no_entra(fest):
    _, rid = _reserva_pagada(fest)
    puerta = _operador("puerta1", "clave-puerta-1")
    token = _token(rid)
    vencido = puerta.post(SIND + "/ingreso/qr", json={"token": token, "k": qr.codigo_efimero(token, ttl=-5)[0]})
    assert vencido.status_code == 403 and vencido.json()["codigo"] == "E-FIESTA-07"
    assert puerta.post(SIND + "/ingreso/qr", json={"token": token, "k": "9999999999.abcdef"}).status_code == 403
    assert puerta.post(SIND + "/ingreso/qr", json={"token": "no-existe", "k": "1.a"}).status_code == 404
    assert puerta.post(SIND + "/ingreso/qr", json={}).status_code == 404
    with db.get_session() as s:
        assert s.get(db.FiestaReserva, rid).ingresados == 0


def test_qr_de_una_pendiente_no_habilita(fest):
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    r = _operador("puerta1", "clave-puerta-1").post(SIND + "/ingreso/qr", json=_qr_de(rid))
    assert r.status_code == 409 and r.json()["codigo"] == "E-FIESTA-09"


def test_ingreso_sin_sesion_es_401(fest):
    _, rid = _reserva_pagada(fest)
    assert TestClient(main.app).post(SIND + "/ingreso/qr", json=_qr_de(rid)).status_code == 401


def test_ingreso_con_documento_pide_motivo_y_queda_registrado(fest):
    _, rid = _reserva_pagada(fest, cantidad=2)
    puerta = _operador("puerta1", "clave-puerta-1")
    busca = puerta.get(SIND + "/buscar?q=22222222").json()["reservas"]
    assert busca == []                                              # ese DNI no tiene reserva
    busca = puerta.get(SIND + "/buscar?q=11111111").json()["reservas"]
    assert [b["id"] for b in busca] == [rid] and "token" not in busca[0]
    assert puerta.get(SIND + "/buscar?q=ana").json()["reservas"][0]["id"] == rid
    assert puerta.get(SIND + "/buscar?q=a").json()["reservas"] == []     # muy corto
    sin_motivo = puerta.post(SIND + "/ingreso/documento", json={"reserva_id": rid, "cantidad": 1, "motivo": " "})
    assert sin_motivo.status_code == 400
    ok = puerta.post(SIND + "/ingreso/documento", json={"reserva_id": rid, "cantidad": 1, "motivo": "perdió el teléfono"})
    assert ok.status_code == 200 and ok.json()["faltan"] == 1
    with db.get_session() as s:
        ing = s.exec(select(db.FiestaIngreso).where(db.FiestaIngreso.reserva_id == rid)).one()
        assert ing.modo == "documento" and ing.motivo == "perdió el teléfono" and ing.quien == "puerta1" and ing.cuando
    puerta.post(SIND + "/ingreso/documento", json={"reserva_id": rid, "motivo": "resto"})
    again = puerta.post(SIND + "/ingreso/documento", json={"reserva_id": rid, "motivo": "otra vez"})
    assert again.status_code == 409 and again.json()["codigo"] == "E-FIESTA-08"


def test_buscar_en_puerta_no_trae_pendientes(fest):
    c = _afiliado()
    _reservar(c, 1)
    assert _operador("puerta1", "clave-puerta-1").get(SIND + "/buscar?q=Ana").json()["reservas"] == []


# =====================================================================
# Panel del sindicato
# =====================================================================
def test_resumen_y_listado_con_filtros(fest):
    _reserva_pagada(fest, "100", "11111111", 2)
    c2 = _afiliado("200", "22222222")
    _reservar(c2, 1)
    op = _operador()
    op.post(SIND + "/cortesia", json={"nombre": "Invitada", "dni": "30111222", "cantidad": 2})
    cont = op.get(SIND + "/resumen").json()["contadores"]
    assert cont["pagadas"] == 1 and cont["pendientes"] == 1 and cont["cortesias"] == 2
    assert cont["personas_pagadas"] == 4 and cont["recaudado"] == 60000 and cont["reservadas"] == 5
    assert cont["disponibles"] == 5 and cont["tope_general"] == 10
    todas = op.get(SIND + "/reservas").json()
    assert todas["total"] == 3
    assert op.get(SIND + "/reservas?estado=pagada").json()["total"] == 2
    assert op.get(SIND + "/reservas?tipo=cortesia").json()["total"] == 1
    assert op.get(SIND + "/reservas?q=Beto").json()["total"] == 1
    assert op.get(SIND + "/reservas?q=22222222").json()["total"] == 1
    assert op.get(SIND + "/reservas?ingreso=si").json()["total"] == 0
    assert op.get(SIND + "/reservas?ingreso=no").json()["total"] == 3
    csv = op.get("/fiesta/sindicato/reservas.csv?estado=pagada")
    assert csv.status_code == 200 and csv.text.count("\n") == 3 and "Ana Pérez" in csv.text


def test_csv_no_deja_formulas(fest):
    op = _operador()
    op.post(SIND + "/cortesia", json={"nombre": "=HYPERLINK(1)", "dni": "30111222"})
    assert "'=HYPERLINK" in op.get("/fiesta/sindicato/reservas.csv").text


def test_anular_pendiente_y_no_una_pagada_de_afiliado(fest):
    _, pagada = _reserva_pagada(fest)
    c2 = _afiliado("200", "22222222")
    pend = _reservar(c2, 1).json()["reserva_id"]
    op = _operador()
    assert op.post(f"{SIND}/reserva/{pend}/anular").status_code == 200
    assert _estado_reserva(pend) == "anulada"
    r = op.post(f"{SIND}/reserva/{pagada}/anular")
    assert r.status_code == 409 and _estado_reserva(pagada) == "pagada"
    assert op.post(f"{SIND}/reserva/999999/anular").status_code == 404
    assert op.post(f"{SIND}/reserva/{pagada}/nota", json={"nota": "Avisó que llega tarde"}).status_code == 200
    assert op.get(SIND + "/reservas?estado=pagada").json()["reservas"][0]["nota"] == "Avisó que llega tarde"


def test_padron_alta_busqueda_y_activo(fest):
    op = _operador()
    assert op.post(SIND + "/padron", json={"legajo": "900", "dni": "12.345.678", "nombre": "Nueva Persona"}).json()["nuevos"] == 1
    assert op.post(SIND + "/padron", json={"legajo": "900", "dni": "12345678", "nombre": "Nueva Persona 2"}).json()["actualizados"] == 1
    mal = op.post(SIND + "/padron", json={"legajo": "901", "dni": "12", "nombre": "X"})
    assert mal.status_code == 422 and mal.json()["codigo"] == "E-FIESTA-11"
    lista = op.get(SIND + "/padron?q=Nueva").json()
    assert lista["padron"][0]["nombre"] == "Nueva Persona 2" and lista["padron"][0]["dni"] == "12345678"
    assert op.get(SIND + "/padron?q=12345678").json()["padron"][0]["legajo"] == "900"
    pid = lista["padron"][0]["id"]
    assert op.post(f"{SIND}/padron/{pid}/activo", json={"activo": False}).json()["activo"] is False
    assert TestClient(main.app).post(API + "/entrar", json={"legajo": "900", "dni": "12345678"}).status_code == 401


def test_padron_csv_ensayo_y_confirmacion(fest):
    op = _operador()
    texto = "legajo;dni;nombre;mail\n500;50000001;Uno;u@x.com\n501;50000002;Dos;\n502;mal;Tres;\n100;11111111;Ana Pérez Renovada;\n"
    ensayo = op.post(SIND + "/padron/csv", files={"archivo": ("p.csv", texto.encode(), "text/csv")})
    j = ensayo.json()
    assert ensayo.status_code == 200 and j["ensayo"] is True and j["filas"] == 3 and j["nuevos"] == 2
    assert j["actualizados"] == 1 and len(j["errores"]) == 1 and j["errores"][0]["linea"] == 4
    assert op.get(SIND + "/padron?q=Uno").json()["padron"] == []        # el ensayo no escribió
    real = op.post(SIND + "/padron/csv", data={"confirmar": "1"},
                   files={"archivo": ("p.csv", texto.encode(), "text/csv")}).json()
    assert real["ensayo"] is False
    assert op.get(SIND + "/padron?q=Uno").json()["padron"][0]["legajo"] == "500"
    assert op.get(SIND + "/padron?q=Renovada").json()["total"] >= 4
    assert TestClient(main.app).post(SIND + "/padron/csv", files={"archivo": ("p.csv", b"1;12345678;A", "text/csv")}).status_code == 401


def test_configuracion_se_guarda_y_valida(fest):
    op = _operador()
    cfg = op.get(SIND + "/configuracion").json()
    assert cfg["mp_modo"] == "mock" and cfg["evento"]["nombre"] == "Fiesta de Prueba"
    nuevo = {"nombre": "Otra Fiesta", "fecha_hora": "2026-12-31T22:00", "lugar": "Salón", "leyenda_ticket": "Gracias",
             "precio": 45000, "tope_por_afiliado": 2, "tope_general": 50, "horas_antes": 12,
             "minutos_vencimiento": 45, "leyenda_cortesia": "Autoridad"}
    ok = op.post(SIND + "/configuracion", json=nuevo)
    assert ok.status_code == 200 and ok.json()["evento"]["precio"] == 45000
    assert op.get(SIND + "/configuracion").json()["evento"]["leyenda_cortesia"] == "Autoridad"
    for campo, valor in (("nombre", ""), ("fecha_hora", "ayer"), ("precio", -1), ("tope_por_afiliado", 0),
                         ("tope_general", "x"), ("minutos_vencimiento", 0)):
        assert op.post(SIND + "/configuracion", json={**nuevo, campo: valor}).status_code == 400, campo


def test_foto_de_fondo_se_achica_y_se_sirve(fest):
    from io import BytesIO

    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (3000, 2000), (20, 40, 90)).save(buf, "PNG")
    op = _operador()
    assert op.post(SIND + "/foto", files={"archivo": ("f.png", buf.getvalue(), "image/png")}).json()["foto"] is True
    img = TestClient(main.app).get(f"/fiesta/foto/{fest.ev}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/webp"
    assert Image.open(BytesIO(img.content)).size[0] <= 1600
    assert _afiliado().get(API + "/estado").json()["evento"]["foto"] is True
    assert op.post(SIND + "/foto", files={"archivo": ("f.txt", b"no soy imagen", "text/plain")}).status_code == 400
    assert op.post(SIND + "/foto", data={"quitar": "1"}).json()["foto"] is False
    assert TestClient(main.app).get(f"/fiesta/foto/{fest.ev}").status_code == 404


def test_operadores_alta_activar_restablecer(fest):
    op = _operador()
    ok = op.post(SIND + "/operador", json={"usuario": "Nuevo.Op", "nombre": "Nuevo", "rol": "puerta", "clave_inicial": "inicial1"})
    assert ok.status_code == 200 and ok.json()["operador"]["usuario"] == "nuevo.op"
    assert op.post(SIND + "/operador", json={"usuario": "nuevo.op", "rol": "puerta", "clave_inicial": "inicial1"}).status_code == 409
    assert op.post(SIND + "/operador", json={"usuario": "x", "rol": "puerta", "clave_inicial": "inicial1"}).status_code == 400
    assert op.post(SIND + "/operador", json={"usuario": "otro.op", "rol": "dios", "clave_inicial": "inicial1"}).status_code == 400
    assert op.post(SIND + "/operador", json={"usuario": "otro.op", "rol": "puerta", "clave_inicial": "1"}).status_code == 400
    nuevo = ok.json()["operador"]
    assert nuevo["debe_cambiar_clave"] is True
    # entra con la inicial, pero tiene que elegir otra
    assert _operador("nuevo.op", "inicial1").get(SIND + "/resumen").status_code == 403
    clave = op.post(f"{SIND}/operador/{nuevo['id']}/restablecer").json()["clave"]
    assert len(clave) >= 8
    assert TestClient(main.app).post(SIND + "/entrar", json={"usuario": "nuevo.op", "clave": "inicial1"}).status_code == 401
    assert TestClient(main.app).post(SIND + "/entrar", json={"usuario": "nuevo.op", "clave": clave}).status_code == 200
    assert op.post(f"{SIND}/operador/{nuevo['id']}/activo", json={"activo": False}).json()["activo"] is False
    assert TestClient(main.app).post(SIND + "/entrar", json={"usuario": "nuevo.op", "clave": clave}).status_code == 401
    yo = next(o for o in op.get(SIND + "/operadores").json()["operadores"] if o["usuario"] == "jefe")
    assert op.post(f"{SIND}/operador/{yo['id']}/activo", json={"activo": False}).status_code == 409
    assert op.post(f"{SIND}/operador/{yo['id']}/restablecer").status_code == 409


# =====================================================================
# Arranque desde Herramientas de /entornos
# =====================================================================
def _con_plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def test_arranque_exige_pase(fest):
    assert TestClient(main.app).get("/api/entornos/herramientas/fiesta/estado").status_code == 403
    assert TestClient(main.app).post("/api/entornos/herramientas/fiesta/arranque", json={}).status_code == 403


def test_arranque_crea_evento_y_primer_admin(fest):
    with db.get_session() as s:
        s.exec(db.text("UPDATE fiestaevento SET activo = false"))
        s.commit()
    c = _con_plataforma()
    est = c.get("/api/entornos/herramientas/fiesta/estado").json()
    assert est["hay_evento"] is False and est["mp_modo"] == "mock"
    body = {"nombre": "Fiesta SUPARA", "fecha_hora": "2026-11-14T21:00", "lugar": "Palacio Anchorena",
            "precio": 30000, "tope_por_afiliado": 4, "tope_general": 1000,
            "usuario": "supara", "nombre_op": "SUPARA", "clave_inicial": "inicial1"}
    assert c.post("/api/entornos/herramientas/fiesta/arranque", json={**body, "usuario": "A"}).status_code == 400
    ok = c.post("/api/entornos/herramientas/fiesta/arranque", json=body)
    assert ok.status_code == 200 and ok.json()["evento"]["fecha_texto"] == "sábado 14 de noviembre, 21:00"
    est = c.get("/api/entornos/herramientas/fiesta/estado").json()
    assert est["hay_evento"] and est["hay_admin"] and est["contadores"]["tope_general"] == 1000
    assert c.post("/api/entornos/herramientas/fiesta/arranque", json=body).status_code == 409
    login = TestClient(main.app).post(SIND + "/entrar", json={"usuario": "supara", "clave": "inicial1"})
    assert login.json()["debe_cambiar_clave"] is True


def test_lo_deferido_de_la_foto_no_viaja_en_las_pantallas(fest):
    """Cargar el evento activo no trae los bytes de la foto."""
    with db.get_session() as s:
        e = s.get(db.FiestaEvento, fest.ev)
        e.foto_datos, e.foto_mime = b"x" * 5000, "image/webp"
        s.add(e)
        s.commit()
    with db.get_session() as s:
        ev = db.fiesta_evento_activo(s)
        assert "foto_datos" in ev.__dict__.get("_sa_instance_state").unloaded
        assert db.fiesta_evento_dict(s, ev)["foto"] is True


# =====================================================================
# Endurecimiento del QA de código (2026-11-12)
# =====================================================================
def test_dni_con_letras_no_es_un_dni():
    assert fiesta.normalizar_dni("12.345.678") == "12345678"
    assert fiesta.normalizar_dni(" 12 345 678 ") == "12345678"
    assert fiesta.normalizar_dni("12A345678") == "" and not fiesta.dni_valido("12A345678")
    assert fiesta.normalizar_dni("１２３４５６７８") == ""           # dígitos no ASCII
    r = fiesta.parsear_padron("1;12A345678;Ana;\n2;12-345-678;Bea;\n")
    assert [f["legajo"] for f in r["filas"]] == ["2"] and "DNI" in r["errores"][0]["motivo"]


def test_csv_con_linea_en_blanco_antes_de_la_cabecera():
    r = fiesta.parsear_padron("\n\nlegajo;dni;nombre;mail\n1;12345678;Ana, María;\n2;22345678;Luis;\n")
    assert [f["legajo"] for f in r["filas"]] == ["1", "2"] and not r["errores"]
    assert r["filas"][0]["nombre"] == "Ana, María"


def test_csv_de_5000_filas_se_parsea_rapido():
    import time
    texto = "legajo;dni;nombre;mail\n" + "".join(
        f"{i};{10000000 + i};Nombre {i};n{i}@x.com\n" for i in range(5000))
    t0 = time.time()
    assert len(fiesta.parsear_padron(texto)["filas"]) == 5000
    assert time.time() - t0 < 3


def test_codigo_o_token_con_no_ascii_no_rompe_con_500(fest):
    c, rid = _reserva_pagada(fest)
    tk = _token(rid)
    sin_romper = TestClient(main.app, raise_server_exceptions=False)
    assert sin_romper.get(f"/fiesta/entrada/{rid}?t=ñandú", follow_redirects=False).status_code == 404
    assert sin_romper.get(f"{API}/entrada/{rid}/qr?t=ñandú").status_code == 404
    assert TestClient(main.app, raise_server_exceptions=False).get(
        f"/fiesta/e/{tk}?k=99999999999.ñ").status_code == 200       # página "no válido"
    o = _operador()
    op = TestClient(main.app, raise_server_exceptions=False)
    op.cookies.update(o.cookies)
    assert op.post(SIND + "/ingreso/qr", json={"token": tk, "k": "99999999999.ñ"}).status_code == 403
    assert qr.verificar_codigo_efimero(tk, "99999999999.ñ") is False
    assert mercadopago.validar_firma("ts=1,v1=ñ", "a", "1", "secreto") is False


def test_cortesia_acota_la_leyenda(fest):
    r = _operador().post(SIND + "/cortesia", json={"nombre": "Zoe", "dni": "44444444", "cantidad": 1,
                                                  "leyenda": "L" * 5000})
    assert r.status_code == 200
    with db.get_session() as s:
        assert len(s.get(db.FiestaReserva, r.json()["reserva_id"]).leyenda) == 100


# =====================================================================
# Lote final de correcciones
# =====================================================================
def test_cargar_padron_no_reactiva_a_quien_se_desactivo(fest):
    with db.get_session() as s:
        p = s.get(db.FiestaPadron, fest.padron["100"])
        p.activo = False
        s.add(p)
        s.commit()
        r = db.fiesta_cargar_padron(s, fest.ev, [
            {"legajo": "100", "dni": "11111111", "nombre": "Ana Nueva", "mail": ""},
            {"legajo": "777", "dni": "77777777", "nombre": "Recién", "mail": ""}])
        assert r == {"nuevos": 1, "actualizados": 1}
        s.expire_all()
        assert s.get(db.FiestaPadron, fest.padron["100"]).activo is False
        assert s.get(db.FiestaPadron, fest.padron["100"]).nombre == "Ana Nueva"
        nuevo = s.exec(select(db.FiestaPadron).where(db.FiestaPadron.legajo == "777",
                                                      db.FiestaPadron.evento_id == fest.ev)).one()
        assert nuevo.activo is True


def test_pago_aprobado_sobre_anulada_queda_pagada_con_nota(fest):
    c = _afiliado()
    rid = _reservar(c, 2).json()["reserva_id"]
    c.post(f"{API}/reserva/{rid}/anular")
    mercadopago.registrar_pago_mock("ANU-1", "approved", rid, 60000)
    assert _webhook(TestClient(main.app), "ANU-1").status_code == 200
    with db.get_session() as s:
        r = s.get(db.FiestaReserva, rid)
        assert r.estado == "pagada" and "reserva anulada" in r.nota and "devolver" in r.nota


def test_segundo_pago_aprobado_se_registra_como_duplicado(fest):
    c, rid = _reserva_pagada(fest, cantidad=2)
    mercadopago.registrar_pago_mock("DUP-2", "approved", rid, 60000)
    r = _webhook(TestClient(main.app), "DUP-2")
    assert r.json()["resultado"] == "duplicado"
    with db.get_session() as s:
        res = s.get(db.FiestaReserva, rid)
        assert res.estado == "pagada" and "Pago duplicado DUP-2" in res.nota
        aviso = s.exec(select(db.FiestaAvisoPago).where(db.FiestaAvisoPago.mp_payment_id == "DUP-2")).one()
        assert aviso.resultado == "duplicado" and aviso.procesado


def test_rechazado_antes_no_hace_duplicado_el_primer_aprobado(fest):
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    mercadopago.registrar_pago_mock("R-1", "rejected", rid, 30000)
    _webhook(TestClient(main.app), "R-1")
    mercadopago.registrar_pago_mock("R-2", "approved", rid, 30000)
    assert _webhook(TestClient(main.app), "R-2").json()["resultado"] == "pagada"
    with db.get_session() as s:
        assert s.get(db.FiestaReserva, rid).nota == ""


def test_precio_minimo_uno_en_configuracion_y_arranque(fest):
    op = _operador()
    base = {"nombre": "F", "fecha_hora": "2026-12-31T22:00", "lugar": "L", "precio": 1,
            "tope_por_afiliado": 2, "tope_general": 50, "horas_antes": 12, "minutos_vencimiento": 45}
    assert op.post(SIND + "/configuracion", json=base).status_code == 200
    r = op.post(SIND + "/configuracion", json={**base, "precio": 0})
    assert r.status_code == 400 and "precio" in r.json()["detail"].lower()
    with db.get_session() as s:
        s.exec(db.text("UPDATE fiestaevento SET activo = false"))
        s.commit()
    r = _con_plataforma().post("/api/entornos/herramientas/fiesta/arranque", json={
        **base, "precio": 0, "usuario": "supara2", "clave_inicial": "inicial1"})
    assert r.status_code == 400


def test_se_guarda_el_init_point_real_y_pagar_ahora_lo_devuelve(fest, monkeypatch):
    import json as _json
    from io import BytesIO
    monkeypatch.delenv("MP_MOCK", raising=False)
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")

    class _R(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen", lambda p, timeout=0: _R(_json.dumps({
        "id": "PREF-7", "init_point": "https://mp.test/real", "sandbox_init_point": "https://mp.test/sbx"}).encode()))
    c = _afiliado()
    rid = _reservar(c, 1).json()["reserva_id"]
    with db.get_session() as s:
        assert s.get(db.FiestaReserva, rid).mp_init_point == "https://mp.test/real"
    fila = c.get(f"{API}/reserva/{rid}").json()
    assert fila["url_pago"] == fila["init_point"] == "https://mp.test/real"
    with db.get_session() as s:                                    # sin lo guardado: reconstruye
        r = s.get(db.FiestaReserva, rid)
        r.mp_init_point = ""
        s.add(r)
        s.commit()
    assert c.get(f"{API}/reserva/{rid}").json()["url_pago"].endswith("pref_id=PREF-7")
    assert mercadopago.crear_preferencia(1, "F", 10, "https://x.test")["sandbox_init_point"] == "https://mp.test/sbx"


def test_login_operador_inexistente_sigue_dando_e_fiesta_10(fest):
    c = TestClient(main.app)
    r = c.post(SIND + "/entrar", json={"usuario": "fantasma", "clave": "lo-que-sea"})
    assert r.status_code == 401 and r.json()["codigo"] == "E-FIESTA-10"
    assert main.auth.verificar_clave("x", main._HASH_RELLENO_FIESTA) is False
