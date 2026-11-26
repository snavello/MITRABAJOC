"""XSII bloque 1, QA independiente del servidor: ataques sobre docs/xsii/API.md.

Cada test que falla marca un defecto del servidor (ver el reporte del QA). No
repite lo que ya cubre `test_xsii_api.py`: aislamiento entre proyectos,
puertas, bordes de las reglas, concurrencia, motor, entradas hostiles,
traza, una sola sesión por request, bytes y forma del JSON.

Correr con: python -m pytest test_xsii_bloque1_qa.py -q
"""
import os
from datetime import timedelta

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import itertools
import json
import re
import subprocess
import sys
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlmodel import Session, SQLModel, select

import auth
import cuit
import db
import fechas
import entorno
import implementacion as im
import main
import modulos
import recursos
from xsii.proyectos.colm3na import catalogo

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
_n = itertools.count(1)
BASE = "/api/entornos/xsii"


# ---------------------------------------------------------------- helpers

def _sindicato(modulos_habilitados=None):
    n = next(_n)
    with db.get_session() as s:
        sind = db.Sindicato(nombre=f"Sindicato QA XSII {n} {uuid.uuid4().hex[:4]}",
                            slug=f"xsii-qa-{n}-{uuid.uuid4().hex[:4]}",
                            cuit=cuit.corregir("30700000000"),
                            modulos_habilitados=list(modulos.MODULOS_INICIALES if modulos_habilitados is None
                                                     else modulos_habilitados))
        s.add(sind); s.commit(); s.refresh(sind)
        sid = sind.id
    db.crear_conceptos_universales(sid)
    return sid


def _proyecto(con_sindicato=True, nombre=None):
    sid = _sindicato() if con_sindicato else None
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, nombre or "QA " + uuid.uuid4().hex[:8], EQ, sindicato_id=sid).id


def _sid_de(pid):
    with db.get_session() as s:
        return db.impl_proyecto(s, pid).sindicato_id


def _equipo(activo=True, nombre=None, **extra):
    usuario = "qa" + uuid.uuid4().hex[:8]
    with db.get_session() as s:
        campos = dict(debe_cambiar_clave=False, debe_completar_datos=False)
        campos.update(extra)
        u = db.UsuarioPlataforma(usuario=usuario, nombre=nombre or "Equipo " + usuario, email="",
                                 clave_hash=auth.hashear_clave("x" * 12), activo=activo, **campos)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    return c


def _mundo(con_sindicato=True):
    return _proyecto(con_sindicato), _equipo()


def _tablero(c, pid):
    r = c.get(f"{BASE}/p/{pid}/tablero")
    assert r.status_code == 200, r.text
    return r.json()


def _tarea(c, pid, codigo):
    r = c.get(f"{BASE}/p/{pid}/tarea/{codigo}")
    assert r.status_code == 200, r.text
    return r.json()["tarea"]


def _decidir(c, pid, codigo, tipo, motivo="", **extra):
    return c.post(f"{BASE}/p/{pid}/tarea/{codigo}/decision", json={"tipo": tipo, "motivo": motivo, **extra})


def _deshacer(c, pid, codigo, tipo, motivo=""):
    return c.post(f"{BASE}/p/{pid}/tarea/{codigo}/decision/deshacer", json={"tipo": tipo, "motivo": motivo})


def _insumo(c, pid, clave, **cuerpo):
    return c.post(f"{BASE}/p/{pid}/insumo/{clave}", json=cuerpo)


def _envejecer(pid, clave, dias=3):
    """Atrasa el pedido del insumo: un pedido es «demorado» desde los 2 días."""
    antes = (fechas.hoy() - timedelta(days=dias)).isoformat() + " 10:00:00"
    with db.get_session() as s:
        for i in s.exec(select(db.XsiiInsumo).where(db.XsiiInsumo.proyecto_id == pid,
                                                     db.XsiiInsumo.clave == clave,
                                                     db.XsiiInsumo.activa == True)).all():    # noqa: E712
            i.cuando = antes
            s.add(i)
        s.commit()


def _tarjeta(pid, titulo="Padrón"):
    with db.get_session() as s:
        t = db.impl_crear_tarjeta(s, pid, EQ, "pedido", titulo, "Mandanos la planilla")
        return t.id, t.codigo


def _seccional(sid, nombre="Sede"):
    with db.get_session() as s:
        sec = db.Seccional(sindicato_id=sid, nombre=nombre, ve_todas=True)
        s.add(sec); s.commit(); s.refresh(sec)
        return sec.id


def _borrar_seccionales(sid):
    with db.get_session() as s:
        for sec in s.exec(select(db.Seccional).where(db.Seccional.sindicato_id == sid)).all():
            s.delete(sec)
        s.commit()


def _filas(modelo, pid, **filtros):
    with db.get_session() as s:
        q = select(modelo).where(modelo.proyecto_id == pid)
        for k, v in filtros.items():
            q = q.where(getattr(modelo, k) == v)
        return s.exec(q).all()


def _movs(pid):
    return len(_filas(db.XsiiMovimiento, pid))


def _en_hilos(n, fabrica):
    """Corre `fabrica(i)` en `n` hilos arrancando juntos; devuelve los resultados."""
    barrera, salida, errores = threading.Barrier(n), [None] * n, []

    def hacer(i):
        try:
            barrera.wait()
            salida[i] = fabrica(i)
        except Exception as e:      # noqa: BLE001
            errores.append(repr(e))

    hilos = [threading.Thread(target=hacer, args=(i,)) for i in range(n)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert not errores, errores
    return salida


def _clon(eq):
    c = TestClient(main.app, follow_redirects=False)
    c.cookies = eq.cookies
    return c


RUTAS_GET = ["proyectos", "p/{pid}/tablero", "p/{pid}/tarea/BAS-01", "p/{pid}/movimientos"]
RUTAS_POST = ["p/{pid}/tarea/BAS-01/decision", "p/{pid}/tarea/BAS-01/decision/deshacer",
              "p/{pid}/insumo/planilla_padron", "p/{pid}/insumo/planilla_padron/retirar"]
JSON_H = {"content-type": "application/json"}


# ================================================================ aislamiento

def test_aislamiento_nada_de_un_proyecto_se_ve_ni_se_toca_desde_otro():
    a, eq = _mundo()
    b = _proyecto()
    _tid, cod = _tarjeta(a, "TITULO-SECRETO-DE-A")
    assert _decidir(eq, a, "COM-02", "completada_a_mano", "MOTIVO-SECRETO-A").status_code == 200
    assert _decidir(eq, a, "COM-03", "pospuesta").status_code == 200
    assert _insumo(eq, a, "planilla_padron", estado="pedido", tarjeta=cod, nota="NOTA-SECRETA-A").status_code == 200
    # B no ve nada de A, en ninguna de las lecturas
    for ruta in ("tablero", "movimientos", "tarea/COM-02", "tarea/PAD-01"):
        texto = eq.get(f"{BASE}/p/{b}/{ruta}").text
        for marca in ("SECRETO", "SECRETA"):
            assert marca not in texto, (ruta, marca)
    tb = _tablero(eq, b)
    assert tb["movimientos"] == [] and tb["demorados"] == [] and tb["resumen"]["a_mano"] == 0
    assert tb["resumen"]["pospuestas"] == 0
    # ... ni lo toca: deshacer / retirar desde B no encuentran lo de A
    assert _deshacer(eq, b, "COM-02", "completada_a_mano").status_code == 409
    assert _deshacer(eq, b, "COM-03", "pospuesta").status_code == 409
    assert eq.post(f"{BASE}/p/{b}/insumo/planilla_padron/retirar").status_code == 409
    # y A sigue intacto
    assert _tarea(eq, a, "COM-02")["a_mano"] is True
    assert _tarea(eq, a, "PAD-01")["insumos"][0]["estado"] == "pedido"


def test_la_tarjeta_de_otro_proyecto_no_se_enlaza_por_codigo_ni_por_id():
    a, eq = _mundo()
    b = _proyecto()
    tid, cod = _tarjeta(a, "TITULO-SECRETO-DE-A")
    for ref in (cod, cod + "-1", tid, str(tid), f" {tid} "):
        r = _insumo(eq, b, "planilla_padron", estado="pedido", tarjeta=ref)
        assert r.status_code == 400, (ref, r.text)
        assert "TITULO-SECRETO" not in r.text
    assert _tablero(eq, b)["movimientos"] == []
    # con una tarjeta PROPIA que tiene el mismo código (PE0001 en los dos), enlaza la de B
    _tidb, codb = _tarjeta(b, "Titulo de B")
    assert codb == cod
    r = _insumo(eq, b, "planilla_padron", estado="pedido", tarjeta=cod)
    assert r.status_code == 200 and r.json()["insumo"]["tarjeta"]["titulo"] == "Titulo de B"


def test_un_registro_con_tarjeta_ajena_ya_guardada_no_filtra_su_titulo():
    """Defensa en profundidad: aunque la base tuviera un insumo de B enlazado a
    una tarjeta de A (dato viejo o escrito a mano), el tablero de B no la muestra."""
    a, eq = _mundo()
    b = _proyecto()
    tid, _cod = _tarjeta(a, "TITULO-SECRETO-DE-A")
    with db.get_session() as s:
        s.add(db.XsiiInsumo(proyecto_id=b, clave="planilla_padron", estado="pedido", tarjeta_id=tid,
                            quien_id=1, quien_nombre="x"))
        s.commit()
    texto = eq.get(f"{BASE}/p/{b}/tablero").text
    assert "TITULO-SECRETO" not in texto
    assert _tarea(eq, b, "PAD-01")["insumos"][0]["tarjeta"] is None


def test_el_historial_de_una_tarea_no_mezcla_los_insumos_de_otro_proyecto():
    a, eq = _mundo()
    b = _proyecto()
    _insumo(eq, a, "planilla_padron", estado="pedido", nota="SOLO-DE-A")
    r = eq.get(f"{BASE}/p/{b}/tarea/PAD-01")
    assert r.status_code == 200 and r.json()["historial"] == [] and "SOLO-DE-A" not in r.text
    assert "SOLO-DE-A" not in eq.get(f"{BASE}/p/{b}/movimientos?codigo=PAD-01").text


# ================================================================ puertas

def test_en_demo_todo_404_incluso_anonimo_y_con_cuerpo_roto(monkeypatch):
    pid, eq = _mundo()
    anonimo = TestClient(main.app, follow_redirects=False)
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    for c in (eq, anonimo):
        for ruta in RUTAS_GET:
            assert c.get(f"{BASE}/{ruta.format(pid=pid)}").status_code == 404, ruta
        for ruta in RUTAS_POST:
            r = c.post(f"{BASE}/{ruta.format(pid=pid)}", content=b"{roto", headers=JSON_H)
            assert r.status_code == 404, (ruta, r.status_code)
        assert c.get(f"{BASE}/p/abc/tablero").status_code == 404
        assert c.get("/entornos/xsii").status_code == 404
        assert c.get(f"/entornos/xsii/{pid}").status_code == 404


def test_en_demo_la_pagina_con_pid_no_numerico_tambien_es_404(monkeypatch):
    """La puerta de demo va antes que la validación del id: un 422 delata que la ruta existe."""
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    for c in (_equipo(), TestClient(main.app, follow_redirects=False)):
        for pid in ("abc", "1.5", "-1", str(2 ** 40)):
            assert c.get(f"/entornos/xsii/{pid}").status_code == 404, pid


def test_la_puerta_se_evalua_antes_de_leer_el_cuerpo_y_de_mirar_el_codigo():
    pid = _proyecto()
    anonimo = TestClient(main.app, follow_redirects=False)
    for ruta in RUTAS_POST:
        for cuerpo in (b"{roto", b"[]", b"\xff\xfe", b"x" * 3_000_000):
            r = anonimo.post(f"{BASE}/{ruta.format(pid=pid)}", content=cuerpo, headers=JSON_H)
            assert r.status_code == 403, (ruta, cuerpo[:8], r.status_code)
    # un código de tarea inexistente, un insumo inexistente y un pid inexistente: 403, no 404
    assert anonimo.post(f"{BASE}/p/{pid}/tarea/ZZZ-99/decision", json={}).status_code == 403
    assert anonimo.post(f"{BASE}/p/{pid}/insumo/inventado", json={}).status_code == 403
    assert anonimo.post(f"{BASE}/p/{pid + 10**6}/tarea/BAS-01/decision", json={}).status_code == 403
    assert anonimo.get(f"{BASE}/p/abc/tablero").status_code == 403


def test_usuarios_que_no_son_del_equipo_no_entran_ni_escriben():
    pid = _proyecto()
    casos = {
        "clave pendiente": _equipo(debe_cambiar_clave=True),
        "datos pendientes": _equipo(debe_completar_datos=True),
        "inactivo": _equipo(activo=False),
    }
    for nombre, c in casos.items():
        for ruta in RUTAS_GET:
            assert c.get(f"{BASE}/{ruta.format(pid=pid)}").status_code in (401, 403), (nombre, ruta)
        for ruta in RUTAS_POST:
            assert c.post(f"{BASE}/{ruta.format(pid=pid)}", json={"tipo": "pospuesta", "estado": "pedido"}
                          ).status_code in (401, 403), (nombre, ruta)
    assert _filas(db.XsiiDecision, pid) == [] and _filas(db.XsiiInsumo, pid) == []


def test_el_pase_del_pin_solo_no_escribe_ni_lee(monkeypatch):
    pid = _proyecto()
    monkeypatch.setattr(entorno, "PIN_LANDING_HABILITADO", True)
    c = TestClient(main.app, follow_redirects=False)
    c.cookies.set(recursos.COOKIE_PASE, recursos.crear_pase())
    assert c.get("/entornos/xsii").status_code in (200, 303)        # la página sí abre con pase
    for ruta in RUTAS_GET:
        assert c.get(f"{BASE}/{ruta.format(pid=pid)}").status_code == 403, ruta
    for ruta in RUTAS_POST:
        assert c.post(f"{BASE}/{ruta.format(pid=pid)}", json={"tipo": "pospuesta", "estado": "pedido"}
                      ).status_code == 403, ruta
    assert _filas(db.XsiiDecision, pid) == [] and _filas(db.XsiiInsumo, pid) == []


def test_las_cookies_de_otros_roles_no_abren_la_api():
    pid = _proyecto()
    for rol in ("sindicato", "trabajador", "empleador"):
        c = TestClient(main.app, follow_redirects=False)
        c.cookies.set(main.COOKIES_POR_ROL[rol], auth.crear_sesion(rol, id_usuario=1, ident="20111111112"))
        assert c.get(f"{BASE}/p/{pid}/tablero").status_code == 403, rol
        assert c.post(f"{BASE}/p/{pid}/tarea/COM-02/decision", json={"tipo": "pospuesta"}).status_code == 403, rol


# ================================================================ reglas de las decisiones

@pytest.mark.parametrize("tipo", ["completada_a_mano", "no_aplica"])
def test_motivo_obligatorio_bordes_de_largo(tipo):
    pid, eq = _mundo()
    codigos = itertools.cycle(["COM-02", "COM-03"])
    for largo, esperado in ((0, 400), (4, 400), (5, 200)):
        cod = "COM-02" if tipo == "completada_a_mano" else "COM-03"
        if esperado == 200:
            r = _decidir(eq, pid, cod, tipo, "a" * largo)
        else:
            r = _decidir(eq, pid, cod, tipo, "a" * largo)
        assert r.status_code == esperado, (tipo, largo, r.text)
    # 500 entra, 501 no (tarea nueva para cada uno)
    pid2 = _proyecto()
    assert _decidir(eq, pid2, "COM-02", tipo, "b" * 500).status_code == 200
    r = _decidir(eq, pid2, "COM-03", tipo, "b" * 501)
    assert r.status_code == 400 and "500" in r.json()["detail"]
    # el límite se cuenta DESPUÉS de sanear: espacios alrededor no suman
    assert _decidir(eq, pid2, "COM-03", tipo, "  " + "c" * 500 + "  ").status_code == 200
    del codigos


def test_el_largo_de_5_con_espacios_o_con_NUL_se_cuenta_ya_saneado():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "  ab  ").status_code == 400
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "a\x00b\x00c\x00").status_code == 400   # queda 'abc'
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "ab\x00cde").status_code == 200        # 'abcde'
    r = _tarea(eq, pid, "COM-02")
    assert "\x00" not in json.dumps(r) and r["decisiones"][0]["motivo"] == "abcde"


@pytest.mark.parametrize("invisible", ["​", "‍", "⁠", "﻿", "­", "⠀"])
def test_un_motivo_hecho_solo_de_caracteres_invisibles_no_vale(invisible):
    """El motivo obligatorio no se cumple con 5 caracteres que no se ven."""
    pid, eq = _mundo()
    r = _decidir(eq, pid, "COM-02", "completada_a_mano", invisible * 5)
    assert r.status_code == 400, f"U+{ord(invisible):04X} x5 se aceptó como motivo: {r.text[:120]}"


def test_html_en_el_motivo_viaja_como_texto():
    pid, eq = _mundo()
    xss = '<img src=x onerror=alert(1)> & "comillas" <script>x</script>'
    r = _decidir(eq, pid, "COM-02", "completada_a_mano", xss)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.json()["tarea"]["decisiones"][0]["motivo"] == xss
    mov = eq.get(f"{BASE}/p/{pid}/movimientos").json()["movimientos"][0]
    assert mov["texto"].endswith(": " + xss)


@pytest.mark.parametrize("tipo", ["COMPLETADA_A_MANO", " pospuesta", "pospuesta ", "Pospuesta", "", "confirmada;", "x" * 600])
def test_tipo_con_mayusculas_o_basura_es_400(tipo):
    pid, eq = _mundo()
    assert _decidir(eq, pid, "COM-02", tipo, "motivo largo").status_code == 400
    assert _deshacer(eq, pid, "COM-02", tipo).status_code == 400
    assert _filas(db.XsiiDecision, pid) == []


def test_la_matriz_de_reglas_una_por_una():
    pid, eq = _mundo()
    # confirmada: sin confirmación declarada / control que no pasa / no aplica por condición
    assert _decidir(eq, pid, "COM-02", "confirmada").status_code == 409        # no declara confirmación
    assert _decidir(eq, pid, "EST-01", "confirmada").status_code == 409        # el control no pasa
    assert _decidir(eq, pid, "REC-08", "confirmada").status_code == 409        # no aplica por condición
    # completada_a_mano sobre lo hecho por control / no aplica por condición
    assert _decidir(eq, pid, "BAS-01", "completada_a_mano", "ya estaba hecha").status_code == 409
    assert _decidir(eq, pid, "REC-08", "completada_a_mano", "no corresponde").status_code == 409
    # no_aplica sobre no aplica por condición
    assert _decidir(eq, pid, "REC-08", "no_aplica", "no corresponde").status_code == 409
    # pospuesta sobre resueltas: hecha por control, no aplica por condición
    assert _decidir(eq, pid, "BAS-01", "pospuesta").status_code == 409
    assert _decidir(eq, pid, "REC-08", "pospuesta").status_code == 409
    # pospuesta sobre declarada no aplica y sobre hecha a mano
    assert _decidir(eq, pid, "COM-03", "no_aplica", "no usan beneficios").status_code == 200
    assert _decidir(eq, pid, "COM-03", "pospuesta").status_code == 409
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "se hizo afuera").status_code == 200
    assert _decidir(eq, pid, "COM-02", "pospuesta").status_code == 409
    # confirmar una tarea declarada no aplica
    assert _decidir(eq, pid, "BAS-03", "no_aplica", "no usamos módulos").status_code == 200
    assert _decidir(eq, pid, "BAS-03", "confirmada").status_code == 409
    # y nada de eso escribió filas de más
    tipos = sorted((d.codigo, d.tipo) for d in _filas(db.XsiiDecision, pid))
    assert tipos == [("BAS-03", "no_aplica"), ("COM-02", "completada_a_mano"), ("COM-03", "no_aplica")]
    assert _movs(pid) == 3


def test_no_aplica_y_completada_a_mano_se_excluyen_en_los_dos_ordenes():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "COM-03", "no_aplica", "no usan beneficios").status_code == 200
    assert _decidir(eq, pid, "COM-03", "completada_a_mano", "igual la hacen").status_code == 409
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "hecho afuera").status_code == 200
    assert _decidir(eq, pid, "COM-02", "no_aplica", "mejor no aplica").status_code == 409


def test_pospuesta_sobre_una_tarea_confirmada_o_con_no_aplica_por_decision_es_409():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "BAS-03", "confirmada").status_code == 200
    assert _decidir(eq, pid, "BAS-03", "pospuesta").status_code == 409


def test_deshacer_lo_que_no_existe_y_volver_a_decidir():
    pid, eq = _mundo()
    for tipo in db.XSII_DECISIONES:
        assert _deshacer(eq, pid, "COM-02", tipo).status_code == 409
    assert _deshacer(eq, pid, "ZZZ-99", "pospuesta").status_code == 404
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "hecho afuera").status_code == 200
    assert _deshacer(eq, pid, "COM-02", "completada_a_mano", "m" * 501).status_code == 400
    assert _deshacer(eq, pid, "COM-02", "completada_a_mano", "a" * 500).status_code == 200
    assert _deshacer(eq, pid, "COM-02", "completada_a_mano").status_code == 409
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "otra vez hecho").status_code == 200
    filas = _filas(db.XsiiDecision, pid, codigo="COM-02")
    assert sorted(d.activa for d in filas) == [False, True]          # la vieja queda, no se borra
    vieja = next(d for d in filas if not d.activa)
    assert vieja.deshecha_por_nombre and vieja.deshecha_cuando and vieja.deshecha_motivo == "a" * 500
    assert _movs(pid) == 3


def test_deshacer_con_motivo_con_html_o_NUL_no_rompe():
    pid, eq = _mundo()
    _decidir(eq, pid, "COM-02", "pospuesta")
    r = _deshacer(eq, pid, "COM-02", "pospuesta", "<b>x</b>\x00‮")
    assert r.status_code == 200, r.text


def test_confirmada_y_no_aplica_a_la_vez_y_deshacer_vuelve_a_hecha():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "BAS-03", "confirmada").status_code == 200
    r = _decidir(eq, pid, "BAS-03", "no_aplica", "decidimos que no aplica")
    assert r.status_code == 200 and r.json()["tarea"]["estado"] == "no_aplica"
    r = _deshacer(eq, pid, "BAS-03", "no_aplica")
    assert r.json()["tarea"]["estado"] == "hecha"


# ================================================================ concurrencia

def test_diez_decisiones_iguales_a_la_vez_una_sola_gana():
    pid, eq = _mundo()
    cs = [_clon(eq) for _ in range(10)]
    codigos = [r.status_code for r in _en_hilos(10, lambda i: _decidir(cs[i], pid, "COM-02", "pospuesta"))]
    assert sorted(codigos) == [200] + [409] * 9, codigos
    assert len(_filas(db.XsiiDecision, pid, activa=True)) == 1
    assert _movs(pid) == 1


def test_decisiones_con_motivo_iguales_a_la_vez():
    pid, eq = _mundo()
    cs = [_clon(eq) for _ in range(6)]
    codigos = [r.status_code for r in _en_hilos(
        6, lambda i: _decidir(cs[i], pid, "COM-02", "completada_a_mano", "se hizo afuera"))]
    assert codigos.count(200) == 1 and set(codigos) <= {200, 409}, codigos
    assert len(_filas(db.XsiiDecision, pid, activa=True)) == 1 and _movs(pid) == 1


def test_insumos_iguales_a_la_vez_sin_registro_previo_nunca_500():
    pid, eq = _mundo()
    cs = [_clon(eq) for _ in range(8)]
    codigos = [r.status_code for r in _en_hilos(8, lambda i: _insumo(cs[i], pid, "planilla_padron", estado="pedido"))]
    assert set(codigos) <= {200, 409} and codigos.count(200) >= 1, codigos
    assert len(_filas(db.XsiiInsumo, pid, activa=True)) == 1
    assert _movs(pid) == codigos.count(200)               # cada 200 dejó UN movimiento, ningún 409 dejó nada


def test_insumos_iguales_a_la_vez_con_registro_previo_nunca_500():
    pid, eq = _mundo()
    assert _insumo(eq, pid, "porcentajes_cuota", estado="pedido").status_code == 200
    cs = [_clon(eq) for _ in range(8)]
    codigos = [r.status_code for r in _en_hilos(8, lambda i: _insumo(cs[i], pid, "porcentajes_cuota", estado="recibido"))]
    assert set(codigos) <= {200, 409} and codigos.count(200) >= 1, codigos
    assert len(_filas(db.XsiiInsumo, pid, activa=True)) == 1
    assert _movs(pid) == 1 + codigos.count(200)


def test_deshacer_y_retirar_a_la_vez_uno_solo_gana():
    pid, eq = _mundo()
    _decidir(eq, pid, "COM-02", "pospuesta")
    _insumo(eq, pid, "planilla_padron", estado="pedido")
    cs = [_clon(eq) for _ in range(6)]
    c1 = [r.status_code for r in _en_hilos(6, lambda i: _deshacer(cs[i], pid, "COM-02", "pospuesta"))]
    assert sorted(c1) == [200] + [409] * 5, c1
    c2 = [r.status_code for r in _en_hilos(
        6, lambda i: cs[i].post(f"{BASE}/p/{pid}/insumo/planilla_padron/retirar"))]
    assert sorted(c2) == [200] + [409] * 5, c2
    tipos = sorted(m.tipo for m in _filas(db.XsiiMovimiento, pid))
    assert tipos == ["decision", "decision_deshecha", "insumo_pedido", "insumo_retirado"]


def test_dos_decisiones_incompatibles_a_la_vez_no_dejan_las_dos_activas():
    """completada_a_mano y no_aplica se excluyen (tabla del contrato): si llegan
    juntas no pueden quedar las dos activas."""
    pid, eq = _mundo()
    a, b = _clon(eq), _clon(eq)
    for cod in ("COM-02", "COM-03", "EST-04", "BAS-04", "BAS-06", "EST-02", "PAD-05", "CIE-03"):
        for _ in range(1):
            _en_hilos(2, lambda i: (_decidir(a, pid, cod, "completada_a_mano", "se hizo afuera") if i == 0
                                    else _decidir(b, pid, cod, "no_aplica", "no corresponde")))
        activos = {d.tipo for d in _filas(db.XsiiDecision, pid, codigo=cod, activa=True)}
        assert not {"completada_a_mano", "no_aplica"} <= activos, (cod, activos)


# ================================================================ motor

def test_completada_a_mano_destraba_a_las_dependientes_y_deshacer_las_vuelve_a_bloquear():
    pid, eq = _mundo()
    antes = _tarea(eq, pid, "EST-01")["control"]
    assert _tarea(eq, pid, "EST-02")["estado"] == "bloqueada"
    assert _decidir(eq, pid, "EST-01", "completada_a_mano", "las cargamos en otro sistema").status_code == 200
    est1 = _tarea(eq, pid, "EST-01")
    assert est1["estado"] == "hecha" and est1["a_mano"] is True
    assert est1["control"] == antes                          # el control se sigue mostrando, sin tocar
    assert est1["control"]["estado"] == "incompleta"
    assert _tarea(eq, pid, "EST-02")["estado"] != "bloqueada"
    assert "EST-01" not in _tarea(eq, pid, "EST-02")["camino"]
    assert _deshacer(eq, pid, "EST-01", "completada_a_mano").status_code == 200
    assert _tarea(eq, pid, "EST-02")["estado"] == "bloqueada"
    assert _tarea(eq, pid, "EST-01")["control"] == antes


def test_no_aplica_declarada_cuenta_como_resuelta_y_sale_del_porcentaje():
    pid, eq = _mundo()
    r0 = _tablero(eq, pid)["resumen"]
    assert _decidir(eq, pid, "EST-01", "no_aplica", "este sindicato no tiene seccionales").status_code == 200
    tb = _tablero(eq, pid)
    r1 = tb["resumen"]
    assert r1["aplican"] == r0["aplican"] - 1 and r1["resueltas"] == r0["resueltas"]
    assert r1["por_estado"]["no_aplica"] == r0["por_estado"]["no_aplica"] + 1
    assert r1["porcentaje"] == (100 * r1["resueltas"]) // r1["aplican"]
    por = {t["codigo"]: t for t in tb["tareas"]}
    assert por["EST-02"]["estado"] != "bloqueada"                       # dependencia dura ya resuelta
    assert por["EST-01"]["estado"] == "no_aplica" and por["EST-01"]["no_aplica_por"] == "decision"
    assert _deshacer(eq, pid, "EST-01", "no_aplica").status_code == 200
    assert _tablero(eq, pid)["resumen"] == r0


def test_una_pospuesta_no_sale_recomendada_ni_alternativa_aunque_se_pospongan_todas():
    pid, eq = _mundo()
    vistas = set()
    for _ in range(8):
        tb = _tablero(eq, pid)
        rec = tb["recomendada"]
        if rec is None:
            break
        assert rec["codigo"] not in vistas and not (set(tb["alternativas"]) & vistas)
        assert _decidir(eq, pid, rec["codigo"], "pospuesta").status_code == 200
        vistas.add(rec["codigo"])
    for t in _tablero(eq, pid)["tareas"]:
        if t["pospuesta"]:
            assert t["estado"] in ("lista", "en_curso", "esperando", "bloqueada")


def test_la_pospuesta_no_cambia_el_estado_ni_destraba():
    pid, eq = _mundo()
    antes = _tarea(eq, pid, "COM-02")["estado"]
    _decidir(eq, pid, "COM-02", "pospuesta")
    assert _tarea(eq, pid, "COM-02")["estado"] == antes
    _decidir(eq, pid, "EST-01", "pospuesta")
    assert _tarea(eq, pid, "EST-02")["estado"] == "bloqueada"


def test_si_el_control_deja_de_pasar_la_tarea_confirmada_deja_de_estar_hecha():
    pid, eq = _mundo()
    sid = _sid_de(pid)
    _seccional(sid)
    assert _insumo(eq, pid, "lista_seccionales", estado="recibido").status_code == 200
    assert _tarea(eq, pid, "EST-01")["falta_confirmar"] is True
    assert _decidir(eq, pid, "EST-01", "confirmada").json()["tarea"]["estado"] == "hecha"
    assert _tarea(eq, pid, "EST-02")["estado"] != "bloqueada"
    _borrar_seccionales(sid)                       # el control deja de pasar
    t = _tarea(eq, pid, "EST-01")
    assert t["estado"] != "hecha", t["estado"]
    assert _tarea(eq, pid, "EST-02")["estado"] == "bloqueada"
    assert [d["tipo"] for d in t["decisiones"]] == ["confirmada"]       # la decisión no se pierde
    assert t["acciones"]["deshacer"] == ["confirmada"]
    _seccional(sid)                                # vuelve a pasar: sigue confirmada
    assert _tarea(eq, pid, "EST-01")["estado"] == "hecha"


def test_insumo_sin_registrar_con_datos_cargados_no_deja_esperando_pero_la_planilla_si():
    pid, eq = _mundo()
    sid = _sid_de(pid)
    assert _tarea(eq, pid, "EST-01")["estado"] == "esperando"
    _seccional(sid)
    est = _tarea(eq, pid, "EST-01")
    assert est["estado"] != "esperando" and est["insumos"][0]["sin_registrar"] is True
    assert est["insumos"][0]["estado"] == "falta"
    # REC-01 y PAD-01 solo se confirman: sin registrar el insumo siguen esperando
    for cod, clave in (("REC-01", "recibos_muestra"), ("PAD-01", "planilla_padron")):
        t = _tarea(eq, pid, cod)
        assert t["estado"] == "esperando" and t["insumos"][0]["sin_registrar"] is False, cod
        assert t["detalle"].startswith("Falta: ")
    # al registrar el insumo de la planilla ya no esta esperando y la persona puede confirmar
    assert _insumo(eq, pid, "planilla_padron", estado="recibido").status_code == 200
    assert _tarea(eq, pid, "PAD-01")["falta_confirmar"] is True


def test_una_tarea_solo_confirmacion_no_se_confirma_sin_el_insumo():
    """PAD-01: el control pasa siempre, pero sin la planilla registrada la tarea
    espera; confirmar en ese estado no puede darla por hecha."""
    pid, eq = _mundo()
    r = _decidir(eq, pid, "PAD-01", "confirmada")
    t = _tarea(eq, pid, "PAD-01")
    assert not (r.status_code == 200 and t["estado"] == "hecha"), \
        "se confirmó PAD-01 sin que la planilla del padrón esté recibida"


def test_el_motor_sigue_puro():
    raiz = os.path.dirname(os.path.abspath(__file__))
    codigo = (f"import sys; sys.path.insert(0, {raiz!r}); import xsii.motor.estados, xsii.motor.consulta, xsii.motor.catalogo;"
              "malos=[m for m in ('db','main','sqlmodel','sqlalchemy','fastapi') if m in sys.modules];"
              "print('MALOS',malos)")
    r = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    assert "MALOS []" in r.stdout, r.stdout


# ================================================================ robustez

@pytest.mark.parametrize("pid_raro", ["-1", "0", "2147483648", "99999999999999999999", "1e3", "%00", "٣", "1.5",
                                      "%20", "null", "0x10"])
def test_pid_raro_nunca_da_500(pid_raro):
    eq = _equipo()
    for ruta in ("tablero", "tarea/BAS-01", "movimientos"):
        assert eq.get(f"{BASE}/p/{pid_raro}/{ruta}").status_code in (404, 422), (pid_raro, ruta)
    for ruta in ("tarea/BAS-01/decision", "tarea/BAS-01/decision/deshacer", "insumo/planilla_padron",
                 "insumo/planilla_padron/retirar"):
        assert eq.post(f"{BASE}/p/{pid_raro}/{ruta}", json={"tipo": "pospuesta", "estado": "pedido"}
                       ).status_code in (404, 422), (pid_raro, ruta)


CODIGOS_RAROS = ["../", "..%2f..%2fetc%2fpasswd", "%00", "BAS-01%00", "ÑÑÑ", "😀", "%E2%80%AE", "A" * 500,
                 "BAS-01;DROP", "BAS-01'--", "bas 01", "%20BAS-01%20", "ＢＡＳ-０１", "BAS-01/decision", "*", "%25"]


@pytest.mark.parametrize("raro", CODIGOS_RAROS)
def test_codigos_de_tarea_e_insumo_raros_nunca_dan_500(raro):
    pid, eq = _mundo()
    assert eq.get(f"{BASE}/p/{pid}/tarea/{raro}").status_code in (200, 404, 405)
    assert _decidir(eq, pid, raro, "pospuesta").status_code in (200, 404, 405, 409)
    assert _deshacer(eq, pid, raro, "pospuesta").status_code in (404, 405, 409)
    assert eq.post(f"{BASE}/p/{pid}/insumo/{raro}", json={"estado": "pedido"}).status_code == 404
    assert eq.post(f"{BASE}/p/{pid}/insumo/{raro}/retirar").status_code == 404
    assert eq.get(f"{BASE}/p/{pid}/movimientos?codigo={raro}").status_code in (200, 400), raro


CUERPOS = [b"", b"{", b"[]", b"null", b"5", b'"x"', b"true", b'{"tipo":', b"\xff\xfe\x00", b"{\"tipo\": 1e999}",
           b"[" * 100000, b'{"a":' * 50000, b'{"tipo": "pospuesta", "motivo": "' + b"x" * 5_000_000 + b'"}',
           b'{"tipo": "pospuesta", "tipo": "completada_a_mano", "motivo": "abcdef"}', b'{"tipo": NaN}',
           b'{"\\ud800": 1, "tipo": "pospuesta", "motivo": "\\ud800\\udc00\\ud800 vale"}']


@pytest.mark.parametrize("cuerpo", CUERPOS, ids=[f"c{i}" for i in range(len(CUERPOS))])
def test_cuerpos_hostiles_nunca_dan_500(cuerpo):
    pid, eq = _mundo()
    for ruta in ("tarea/COM-02/decision", "tarea/COM-02/decision/deshacer", "insumo/planilla_padron"):
        r = eq.post(f"{BASE}/p/{pid}/{ruta}", content=cuerpo, headers=JSON_H)
        assert r.status_code < 500, (ruta, cuerpo[:12], r.status_code, r.text[:200])
        assert r.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("limite", ["0", "-5", "1", "200", "201", "999999999999", "99999999999999999999",
                                    "٣", "1_0", " 5 ", "", "abc", "1e3", "NaN", "5.5", "9" * 5000, "%00"])
def test_limite_hostil(limite):
    pid, eq = _mundo()
    r = eq.get(f"{BASE}/p/{pid}/movimientos", params={"limite": limite})
    assert r.status_code in (200, 400), (limite[:20], r.status_code)
    if r.status_code == 200:
        assert len(r.json()["movimientos"]) <= 200


@pytest.mark.parametrize("codigo", ["\x00", "BAS-01\x00x", "😀" * 30, "'; DROP TABLE xsiidecision;--", "%", "_",
                                    "A" * 10000, "\ud800"])
def test_codigo_hostil_en_movimientos_nunca_da_500(codigo):
    pid, eq = _mundo()
    try:
        r = eq.get(f"{BASE}/p/{pid}/movimientos", params={"codigo": codigo})
    except UnicodeEncodeError:
        pytest.skip("el cliente no puede ni armar el pedido")
    assert r.status_code in (200, 400), (repr(codigo[:12]), r.status_code, r.text[:200])


TARJETAS_MALAS = [True, False, 1.5, [], {}, ["PE0001"], 10 ** 30, -1, 0, "9" * 5000, "\x00", "PE0001\x00", "-5", "1e3",
                  "٣", "PE0001-99999999999999999999", "PE9999", "  "]


@pytest.mark.parametrize("tarjeta", TARJETAS_MALAS, ids=[f"t{i}" for i in range(len(TARJETAS_MALAS))])
def test_tarjeta_hostil_en_un_insumo(tarjeta):
    pid, eq = _mundo()
    r = _insumo(eq, pid, "planilla_padron", estado="pedido", tarjeta=tarjeta)
    assert r.status_code in (200, 400), (repr(tarjeta)[:30], r.status_code, r.text[:200])
    if r.status_code == 200:      # solo los vacíos pueden pasar, y sin tarjeta
        assert r.json()["insumo"]["tarjeta"] is None


@pytest.mark.parametrize("campos", [
    {"estado": "RECIBIDO"}, {"estado": " pedido"}, {"estado": 1}, {"estado": ["pedido"]}, {"estado": None},
    {}, {"estado": "pedido", "nota": "n" * 501}, {"estado": "pedido", "nota": 5}, {"estado": "pedido", "nota": ["x"]},
    {"estado": "pedido", "nota": "a\x00b"}, {"estado": "pedido", "nota": "<script>1</script>"},
    {"estado": "pedido", "tarjeta": "", "nota": "‮​"}])
def test_estado_y_nota_hostiles(campos):
    pid, eq = _mundo()
    r = _insumo(eq, pid, "planilla_padron", **campos)
    assert r.status_code in (200, 400), (campos, r.status_code, r.text[:200])
    assert r.status_code == 400 or r.json()["insumo"]["estado"] in ("pedido", "recibido")
    assert _movs(pid) == (1 if r.status_code == 200 else 0)


def test_nota_de_500_entra_y_de_501_no_y_el_html_viaja_como_texto():
    pid, eq = _mundo()
    assert _insumo(eq, pid, "planilla_padron", estado="pedido", nota="n" * 500).status_code == 200
    assert _insumo(eq, pid, "planilla_padron", estado="pedido", nota="n" * 501).status_code == 400
    r = _insumo(eq, pid, "planilla_padron", estado="recibido", nota="<b>x</b> & \"y\"")
    assert r.status_code == 200 and r.json()["insumo"]["nota"] == "<b>x</b> & \"y\""


def test_un_sindicato_borrado_despues_de_crear_el_proyecto():
    pid, eq = _mundo()
    sid = _sid_de(pid)
    assert _decidir(eq, pid, "COM-02", "pospuesta").status_code == 200
    with db.get_session() as s:
        # borra lo que cuelga del sindicato (claves foráneas) y después el sindicato
        for tabla in SQLModel.metadata.sorted_tables[::-1]:
            if tabla.name != "sindicato" and "sindicato_id" in tabla.c and any(
                    fk.column.table.name == "sindicato" for fk in tabla.c["sindicato_id"].foreign_keys):
                s.exec(tabla.delete().where(tabla.c.sindicato_id == sid))
        s.delete(s.get(db.Sindicato, sid))
        s.commit()
    tb = _tablero(eq, pid)
    assert tb["disponible"] is False and tb["tareas"] == [] and tb["resumen"] is None and tb["recomendada"] is None
    assert eq.get(f"{BASE}/p/{pid}/tarea/COM-02").status_code == 409
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "se hizo afuera").status_code == 409
    assert _deshacer(eq, pid, "COM-02", "pospuesta").status_code == 409
    assert _insumo(eq, pid, "planilla_padron", estado="pedido").status_code == 200
    assert eq.post(f"{BASE}/p/{pid}/insumo/planilla_padron/retirar").status_code == 200
    assert eq.get(f"{BASE}/p/{pid}/movimientos").status_code == 200
    assert eq.get(f"{BASE}/proyectos").status_code == 200
    assert eq.get(f"/entornos/xsii/{pid}").status_code == 200


@pytest.mark.parametrize("raros", [[], [1, None, ["x"], "recibos", {"a": 1}], "recibos", {"recibos": True}, 5, [[]],
                                   ["recibos"] * 500, ["💥", "ñ"]])
def test_sindicato_con_modulos_habilitados_raros_no_tumba_el_tablero(raros):
    pid, eq = _mundo()
    sid = _sid_de(pid)
    with db.get_session() as s:
        sind = s.get(db.Sindicato, sid)
        sind.modulos_habilitados = raros
        s.add(sind); s.commit()
    r = eq.get(f"{BASE}/p/{pid}/tablero")
    assert r.status_code == 200, (raros, r.text[:300])
    assert r.json()["disponible"] is True and len(r.json()["tareas"]) == 34
    assert _decidir(eq, pid, "BAS-02", "pospuesta").status_code in (200, 409)


def test_sindicato_con_modulos_habilitados_null():
    pid, eq = _mundo()
    sid = _sid_de(pid)
    try:
        with db.get_session() as s:
            s.exec(db.text("UPDATE sindicato SET modulos_habilitados = 'null'::jsonb WHERE id = :i").bindparams(i=sid))
            s.commit()
    except Exception:       # noqa: BLE001 - la columna no admite el nulo JSON: no hay caso
        pytest.skip("la columna no admite null")
    assert eq.get(f"{BASE}/p/{pid}/tablero").status_code == 200


# ================================================================ traza

def test_cada_escritura_deja_su_movimiento_y_un_rechazo_no_deja_nada():
    pid, eq = _mundo()
    assert _movs(pid) == 0
    _decidir(eq, pid, "COM-02", "pospuesta")
    _decidir(eq, pid, "COM-02", "pospuesta")                    # 409
    _decidir(eq, pid, "COM-02", "completada_a_mano", "x")       # 400
    _decidir(eq, pid, "BAS-01", "completada_a_mano", "ya estaba")   # 409
    _insumo(eq, pid, "planilla_padron", estado="inventado")     # 400
    _insumo(eq, pid, "planilla_padron", estado="pedido", tarjeta="PE9999")   # 400
    eq.post(f"{BASE}/p/{pid}/insumo/planilla_padron/retirar")   # 409
    assert _movs(pid) == 1
    assert len(_filas(db.XsiiDecision, pid)) == 1 and _filas(db.XsiiInsumo, pid) == []
    _insumo(eq, pid, "planilla_padron", estado="pedido")
    _insumo(eq, pid, "planilla_padron", estado="recibido")
    eq.post(f"{BASE}/p/{pid}/insumo/planilla_padron/retirar")
    _deshacer(eq, pid, "COM-02", "pospuesta")
    tipos = [m.tipo for m in sorted(_filas(db.XsiiMovimiento, pid), key=lambda m: m.id)]
    assert tipos == ["decision", "insumo_pedido", "insumo_recibido", "insumo_retirado", "decision_deshecha"]
    assert [i.activa for i in _filas(db.XsiiInsumo, pid)] == [False, False]


def test_si_falla_el_movimiento_no_queda_la_decision_ni_el_insumo(monkeypatch):
    pid, eq = _mundo()
    sin_raise = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    sin_raise.cookies = eq.cookies

    def roto(*a, **k):
        raise RuntimeError("falla el movimiento")

    monkeypatch.setattr(db, "_xsii_movimiento", roto)
    assert _decidir(sin_raise, pid, "COM-02", "pospuesta").status_code == 500
    assert _insumo(sin_raise, pid, "planilla_padron", estado="pedido").status_code == 500
    monkeypatch.undo()
    assert _filas(db.XsiiDecision, pid) == [] and _filas(db.XsiiInsumo, pid) == []
    assert _decidir(eq, pid, "COM-02", "pospuesta").status_code == 200     # el índice único no quedó trabado
    assert _insumo(eq, pid, "planilla_padron", estado="pedido").status_code == 200


def test_el_movimiento_es_inmutable():
    pid, eq = _mundo()
    _decidir(eq, pid, "COM-02", "pospuesta")
    with db.get_session() as s:
        m = s.exec(select(db.XsiiMovimiento).where(db.XsiiMovimiento.proyecto_id == pid)).one()
        m.texto = "otra cosa"
        s.add(m)
        with pytest.raises(ValueError):
            s.commit()
        s.rollback()
        m = s.exec(select(db.XsiiMovimiento).where(db.XsiiMovimiento.proyecto_id == pid)).one()
        s.delete(m)
        with pytest.raises(ValueError):
            s.commit()
        s.rollback()
    assert _movs(pid) == 1


def test_nombres_raros_de_quien_decide_no_rompen_ni_se_pierden():
    raro = "<b>Ana</b> {x} %s %(y)s 'Ñandú' 😀 \\n"
    eq = _equipo(nombre=raro)
    pid = _proyecto()
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "texto {con} llaves %s %d").status_code == 200
    assert _insumo(eq, pid, "planilla_padron", estado="pedido", nota="{0} %s {nombre}").status_code == 200
    movs = eq.get(f"{BASE}/p/{pid}/movimientos").json()["movimientos"]
    assert len(movs) == 2 and all(m["quien"] == raro for m in movs)
    t = _tarea(eq, pid, "COM-02")
    assert t["decisiones"][0]["quien"] == raro and t["detalle"].startswith(f"Completada a mano por {raro}")
    # el nombre del proyecto con caracteres raros tampoco rompe la lista ni el tablero
    p2 = _proyecto(nombre="<i>Raro</i> {%s} 😀")
    assert eq.get(f"{BASE}/p/{p2}/tablero").status_code == 200
    assert any(p["nombre"] == "<i>Raro</i> {%s} 😀" for p in eq.get(f"{BASE}/proyectos").json()["proyectos"])


# ================================================================ una sesión por request, bytes

class _SesionContada(Session):
    abiertas = 0
    maximo = 0

    def __enter__(self):
        type(self).abiertas += 1
        type(self).maximo = max(type(self).maximo, type(self).abiertas)
        return super().__enter__()

    def __exit__(self, *a):
        type(self).abiertas -= 1
        return super().__exit__(*a)


def test_ninguna_ruta_xsii_abre_una_sesion_adentro_de_otra(monkeypatch):
    pid, eq = _mundo()
    _tid, cod = _tarjeta(pid)
    monkeypatch.setattr(db, "get_session", lambda: _SesionContada(db.engine))
    _SesionContada.abiertas = _SesionContada.maximo = 0
    pedidos = [
        ("get", f"{BASE}/proyectos", None), ("get", f"{BASE}/p/{pid}/tablero", None),
        ("get", f"{BASE}/p/{pid}/tarea/PAD-01", None), ("get", f"{BASE}/p/{pid}/movimientos?codigo=PAD-01", None),
        ("post", f"{BASE}/p/{pid}/tarea/COM-02/decision", {"tipo": "completada_a_mano", "motivo": "hecho afuera"}),
        ("post", f"{BASE}/p/{pid}/tarea/COM-02/decision", {"tipo": "completada_a_mano", "motivo": "hecho afuera"}),
        ("post", f"{BASE}/p/{pid}/tarea/COM-02/decision/deshacer", {"tipo": "completada_a_mano"}),
        ("post", f"{BASE}/p/{pid}/insumo/planilla_padron", {"estado": "pedido", "tarjeta": cod}),
        ("post", f"{BASE}/p/{pid}/insumo/planilla_padron/retirar", None),
        ("post", f"{BASE}/p/{pid}/insumo/planilla_padron/retirar", None),
        ("post", f"{BASE}/p/{pid}/tarea/COM-02/decision", {"tipo": "inventada"}),
        ("get", f"/entornos/xsii/{pid}", None), ("get", "/entornos/xsii", None),
    ]
    for metodo, url, cuerpo in pedidos:
        r = getattr(eq, metodo)(url, **({"json": cuerpo} if cuerpo is not None else {}))
        assert r.status_code < 500, (url, r.status_code)
        assert _SesionContada.maximo <= 1, (metodo, url, "sesiones abiertas a la vez:", _SesionContada.maximo)
    assert _SesionContada.abiertas == 0


def test_el_tablero_no_trae_columnas_de_bytes():
    pid, eq = _mundo()
    sid = _sid_de(pid)
    with db.get_session() as s:
        sind = s.get(db.Sindicato, sid)
        sind.logo_datos, sind.logo_mime = b"\x89PNG" + b"0" * 2000, "image/png"
        s.add(sind); s.commit()
    binarias = {c.name for t in SQLModel.metadata.tables.values() for c in t.columns
                if c.type.__class__.__name__ == "LargeBinary"}
    assert "logo_datos" in binarias
    vistas = []

    def espiar(conn, cursor, statement, parameters, context, executemany):
        vistas.append(statement)

    sa_event.listen(db.engine, "before_cursor_execute", espiar)
    try:
        assert eq.get(f"{BASE}/p/{pid}/tablero").status_code == 200
        assert eq.get(f"{BASE}/p/{pid}/tarea/EST-01").status_code == 200
        assert _decidir(eq, pid, "COM-02", "pospuesta").status_code == 200
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", espiar)
    assert vistas
    malas = []
    for sql in vistas:
        limpio = re.sub(r"octet_length\([^)]*\)", "", sql, flags=re.I)
        limpio = re.sub(r"\b[\w.]*\s+IS\s+(NOT\s+)?NULL", "", limpio, flags=re.I)
        for col in binarias:
            if re.search(rf"\b{col}\b", limpio) and limpio.lstrip().upper().startswith("SELECT"):
                malas.append((col, sql[:160]))
    assert not malas, malas[:3]


# ================================================================ forma del JSON contra el contrato

def test_forma_de_cada_objeto_contra_el_contrato():
    pid, eq = _mundo()
    tid, cod = _tarjeta(pid, "Planilla del padrón")
    _insumo(eq, pid, "planilla_padron", estado="pedido", tarjeta=cod, nota="pedida")
    _envejecer(pid, "planilla_padron")
    _decidir(eq, pid, "COM-02", "pospuesta", "luego")
    tb = _tablero(eq, pid)
    assert set(tb["proyecto"]) == {"id", "nombre", "sindicato_id", "sindicato_nombre", "mesa_url"}
    assert list(tb["rotulos"]["estados"]) == ["hecha", "lista", "en_curso", "esperando", "bloqueada", "no_aplica"]
    assert list(tb["rotulos"]["modos"]) == ["asistida", "herramienta", "aplicacion", "manual", "automatica"]
    assert list(tb["rotulos"]["decisiones"]) == ["confirmada", "completada_a_mano", "no_aplica", "pospuesta"]
    assert set(tb["resumen"]["por_estado"]) == {"hecha", "lista", "en_curso", "esperando", "bloqueada", "no_aplica"}
    assert set(tb["resumen"]) == {"total", "aplican", "resueltas", "porcentaje", "por_confirmar", "a_mano",
                                  "con_observaciones", "pospuestas", "por_estado"}
    assert all(isinstance(tb["resumen"][k], int) for k in tb["resumen"] if k != "por_estado")
    assert set(tb["recomendada"]) == {"codigo", "por_que", "destraba", "como"} and isinstance(tb["recomendada"]["destraba"], int)
    assert isinstance(tb["alternativas"], list) and len(tb["alternativas"]) <= 3
    assert len(tb["demorados"]) == 1
    d = tb["demorados"][0]
    assert set(d) == {"clave", "nombre", "codigo", "dias", "tarjeta", "frena"} and set(d["tarjeta"]) == {"codigo", "titulo"}
    assert d["codigo"] == "PAD-01" and d["tarjeta"] == {"codigo": cod, "titulo": "Planilla del padrón"} and d["frena"] >= 2
    por = {t["codigo"]: t for t in tb["tareas"]}
    for t in por.values():
        assert isinstance(t["necesita"], list) and isinstance(t["camino"], list) and isinstance(t["nivel"], int)
        assert isinstance(t["control"]["cifras"], list) and isinstance(t["control"]["faltan"], list)
        assert t["donde"] is None or set(t["donde"]) == {"url", "rotulo"}
        for i in t["insumos"]:
            assert set(i) == {"clave", "nombre", "descripcion", "estado", "sin_registrar", "dias", "nota", "quien",
                              "cuando", "tarjeta"}
            assert i["estado"] in ("recibido", "pedido", "falta") and isinstance(i["sin_registrar"], bool)
        for dec in t["decisiones"]:
            assert set(dec) == {"tipo", "motivo", "quien", "cuando"}
    ins = por["PAD-01"]["insumos"][0]
    assert ins["estado"] == "pedido" and ins["dias"] == 3 and ins["nota"] == "pedida" and ins["quien"] and ins["cuando"]
    assert set(ins["tarjeta"]) == {"id", "codigo", "titulo", "estado", "url"} and ins["tarjeta"]["url"] == f"/implementacion?p={pid}"
    assert por["BAS-01"]["insumos"] == [] and por["COM-02"]["pospuesta"] is True
    assert por["COM-02"]["decisiones"][0]["motivo"] == "luego"
    mov = tb["movimientos"][0]
    assert set(mov) == {"id", "codigo", "tipo", "texto", "cantidades", "quien", "cuando"} and mov["cantidades"] == {}
    assert [m["id"] for m in tb["movimientos"]] == sorted((m["id"] for m in tb["movimientos"]), reverse=True)
    ficha = eq.get(f"{BASE}/p/{pid}/tarea/PAD-01").json()
    assert set(ficha) == {"tarea", "historial"} and ficha["historial"][0]["tipo"] == "insumo_pedido"
    rp = _decidir(eq, pid, "COM-03", "pospuesta").json()
    assert set(rp) == {"ok", "tarea", "resumen"} and rp["ok"] is True and rp["tarea"]["codigo"] == "COM-03"
    ri = _insumo(eq, pid, "recibos_muestra", estado="recibido").json()
    assert set(ri) == {"ok", "insumo"} and ri["insumo"]["estado"] == "recibido"
    # pedido -> recibido conserva la tarjeta si no se manda otra
    rr = _insumo(eq, pid, "planilla_padron", estado="recibido").json()["insumo"]
    assert rr["tarjeta"]["codigo"] == cod and rr["dias"] is None
    lista = eq.get(f"{BASE}/p/{pid}/movimientos?limite=2").json()["movimientos"]
    assert len(lista) == 2 and set(eq.get(f"{BASE}/p/{pid}/movimientos").json()) == {"movimientos"}


def test_movimientos_por_tarea_incluye_sus_insumos_y_no_los_de_otras():
    pid, eq = _mundo()
    _insumo(eq, pid, "planilla_padron", estado="pedido")          # PAD-01
    _insumo(eq, pid, "recibos_muestra", estado="pedido")          # REC-01
    _decidir(eq, pid, "COM-02", "pospuesta")
    pad = eq.get(f"{BASE}/p/{pid}/movimientos?codigo=pad-01").json()["movimientos"]
    assert [m["tipo"] for m in pad] == ["insumo_pedido"] and "padrón" in pad[0]["texto"].lower()
    com = eq.get(f"{BASE}/p/{pid}/movimientos?codigo=COM-02").json()["movimientos"]
    assert [m["tipo"] for m in com] == ["decision"]
    assert len(eq.get(f"{BASE}/p/{pid}/movimientos").json()["movimientos"]) == 3
    assert eq.get(f"{BASE}/p/{pid}/movimientos?codigo=ZZZ-99").json()["movimientos"] == []


def test_la_ficha_del_proyecto_sin_sindicato_y_los_demorados_con_tarea_resuelta():
    pid, eq = _mundo()
    _insumo(eq, pid, "porcentajes_cuota", estado="pedido")       # REC-03, se resuelve a mano
    assert _tablero(eq, pid)["demorados"] == []                       # pedido hoy: todavía no demora
    _envejecer(pid, "porcentajes_cuota")
    assert [d["clave"] for d in _tablero(eq, pid)["demorados"]] == ["porcentajes_cuota"]
    assert _decidir(eq, pid, "REC-03", "completada_a_mano", "se cargó sin planilla").status_code == 200
    assert _tablero(eq, pid)["demorados"] == []


# ================================================================ migración

def test_las_tablas_xsii_estan_en_la_lista_fail_closed():
    assert db.XSII_TABLAS == ("xsiidecision", "xsiiinsumo", "xsiimovimiento")
    with db.get_session() as s:
        presentes = {r[0] for r in s.exec(db.text(
            "select tablename from pg_tables where schemaname = current_schema() and tablename like 'xsii%'")).all()}
    assert presentes == set(db.XSII_TABLAS)
