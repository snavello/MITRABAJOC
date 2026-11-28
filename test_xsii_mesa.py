"""XSII bloque 5, la vuelta a la Mesa (docs/xsii/API.md, «Bloque 5»): los hitos
de la Mesa enlazados a tareas (sugerencias, propuesta, marcar con revalidación)
y los archivos de la Mesa en los insumos (listar, fijar, usarlos en una asistida
de planilla). Todo por HTTP real, más las puertas y el JSON de sugerencias.

Correr con: python -m pytest test_xsii_mesa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import itertools
import json
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import auth
import cuit
import db
import entorno
import implementacion as im
import main
import modulos
from xsii.proyectos.colm3na import catalogo, herramientas as herr, hitos as hitos_mod, vista

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
SIND = im.Actor(im.SINDICATO, 7, "Carla (sindicato)")
BASE = "/api/entornos/xsii"
_n = itertools.count(1)
SEMILLA = Path(__file__).parent / "data" / "implementacion" / "hitos_bancaria.json"
SUGERIDOS = Path(__file__).parent / "data" / "xsii" / "hitos_sugeridos.json"
CAB = "nombre;sede_central;provincia;localidad;calle;numero;latitud;longitud;mail\n"
FILA = "Seccional Rosario;no;Santa Fe;Rosario;Córdoba;1234;-32,9468;-60,6393;\n"


# ---------------------------------------------------------------- mundo

def _sindicato():
    n = next(_n)
    with db.get_session() as s:
        sind = db.Sindicato(nombre=f"Sindicato Mesa XSII {n} {uuid.uuid4().hex[:4]}", slug=f"xsii-mesa-{n}-{uuid.uuid4().hex[:4]}",
                            cuit=cuit.corregir("30700000000"), modulos_habilitados=list(modulos.MODULOS_INICIALES))
        s.add(sind); s.commit(); s.refresh(sind)
        sid = sind.id
    db.crear_conceptos_universales(sid)
    return sid


def _proyecto(con_sindicato=True):
    sid = _sindicato() if con_sindicato else None
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, "XSII " + uuid.uuid4().hex[:8], EQ, sindicato_id=sid).id


def _equipo(activo=True):
    usuario = "eq" + uuid.uuid4().hex[:8]
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario, email="",
                                 clave_hash=auth.hashear_clave("x" * 12), activo=activo,
                                 debe_cambiar_clave=False, debe_completar_datos=False)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    return c


def _mundo():
    return _proyecto(), _equipo()


def _hito(pid, texto, etapa=0):
    with db.get_session() as s:
        et = db.impl_etapas(s, pid)[etapa]
        return db.impl_agregar_hito(s, pid, et.id, texto, EQ).id


def _hitos(c, pid):
    r = c.get(f"{BASE}/p/{pid}/hitos")
    assert r.status_code == 200, r.text
    return r.json()


def _de(c, pid, hid):
    for f in _hitos(c, pid)["fases"]:
        for h in f["hitos"]:
            if h["id"] == hid:
                return h
    raise AssertionError("no está el hito")


def _enlazar(c, pid, hid, codigo):
    return c.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace", json={"codigo": codigo})


def _resolver(c, pid, codigo):
    r = c.post(f"{BASE}/p/{pid}/tarea/{codigo}/decision", json={"tipo": "completada_a_mano", "motivo": "ya está hecha"})
    assert r.status_code == 200, r.text


def _movs(pid, tipo=None):
    with db.get_session() as s:
        m = list(s.exec(select(db.XsiiMovimiento).where(db.XsiiMovimiento.proyecto_id == pid)).all())
    return [x for x in m if tipo is None or x.tipo == tipo]


def _hito_mesa(hid):
    with db.get_session() as s:
        h = s.get(db.ImplHito, hid)
        return h.hecho, h.hecho_por


# ---------------------------------------------------------------- puertas

RUTAS_GET = ["p/{pid}/hitos", "p/{pid}/insumo/lista_seccionales/archivos"]
RUTAS_POST = ["p/{pid}/hitos/sugerencias/aceptar", "p/{pid}/hitos/1/enlace", "p/{pid}/hitos/1/enlace/retirar",
              "p/{pid}/hitos/1/marcar", "p/{pid}/insumo/lista_seccionales/archivo"]


def test_sin_sesion_baja_y_usuario_del_sindicato():
    pid = _proyecto()
    anonimo = TestClient(main.app, follow_redirects=False)
    for ruta in RUTAS_GET:
        assert anonimo.get(f"{BASE}/{ruta.format(pid=pid)}").status_code == 403, ruta
    for ruta in RUTAS_POST:
        assert anonimo.post(f"{BASE}/{ruta.format(pid=pid)}", json={}).status_code == 403, ruta
    baja = _equipo(activo=False)
    assert baja.get(f"{BASE}/p/{pid}/hitos").status_code == 401
    assert baja.post(f"{BASE}/p/{pid}/hitos/1/marcar").status_code == 401
    mail = f"{uuid.uuid4().hex[:8]}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, "Carla", mail, "transitoria1", EQ)
        db.impl_usuario_cambiar_clave(s, u.id, "transitoria1", "definitiva-2026")
    c = TestClient(main.app, follow_redirects=False)
    assert c.post("/implementacion/ingresar", data={"mail": mail, "clave": "definitiva-2026"}).status_code == 303
    assert c.get(f"{BASE}/p/{pid}/hitos").status_code == 403
    assert c.post(f"{BASE}/p/{pid}/hitos/1/marcar").status_code == 403
    assert c.get(f"{BASE}/p/{pid}/insumo/lista_seccionales/archivos").status_code == 403


def test_en_demo_todo_es_404(monkeypatch):
    pid, eq = _mundo()
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    for ruta in RUTAS_GET:
        assert eq.get(f"{BASE}/{ruta.format(pid=pid)}").status_code == 404, ruta
    for ruta in RUTAS_POST:
        assert eq.post(f"{BASE}/{ruta.format(pid=pid)}", json={}).status_code == 404, ruta


def test_proyecto_inexistente_o_con_id_enorme_es_404():
    pid, eq = _mundo()
    for n in (pid + 100000, 0, -1, 2 ** 31, 10 ** 30):
        assert eq.get(f"{BASE}/p/{n}/hitos").status_code == 404, n
        assert eq.post(f"{BASE}/p/{n}/hitos/sugerencias/aceptar", json={}).status_code == 404
        assert eq.post(f"{BASE}/p/{n}/hitos/1/marcar").status_code == 404
        assert eq.get(f"{BASE}/p/{n}/insumo/lista_seccionales/archivos").status_code == 404
        assert eq.post(f"{BASE}/p/{n}/insumo/lista_seccionales/archivo", json={"archivo_id": 1}).status_code == 404
    assert eq.post(f"{BASE}/p/{pid}/hitos/{2 ** 31}/marcar").status_code == 404
    assert eq.post(f"{BASE}/p/{pid}/hitos/0/enlace", json={"codigo": "BAS-01"}).status_code == 404


def test_un_hito_de_otro_proyecto_es_404_en_todas_las_rutas():
    a, eq = _mundo()
    b = _proyecto()
    ajeno = _hito(b, "Un hito del otro proyecto")
    assert _enlazar(eq, a, ajeno, "BAS-01").status_code == 404
    assert eq.post(f"{BASE}/p/{a}/hitos/{ajeno}/enlace/retirar", json={"codigo": "BAS-01"}).status_code == 404
    assert eq.post(f"{BASE}/p/{a}/hitos/{ajeno}/marcar").status_code == 404
    assert eq.post(f"{BASE}/p/{a}/hitos/sugerencias/aceptar", json={"hitos": [ajeno]}).status_code == 404
    assert _hito_mesa(ajeno) == (False, "")
    with db.get_session() as s:
        assert db.xsii_hitos_activos(s, a) == [] and db.xsii_hitos_activos(s, b) == []


# ---------------------------------------------------------------- hitos: lectura y enlaces

def test_la_forma_de_los_hitos_y_el_resumen():
    pid, eq = _mundo()
    h1 = _hito(pid, "Padrón y listas cargados y conciliados contra los totales")
    h2 = _hito(pid, "Reunión de arranque hecha", etapa=1)
    j = _hitos(eq, pid)
    assert set(j) == {"fases", "resumen"}
    assert [f["etapa"] for f in j["fases"]][:2] == [e.nombre for e in _etapas(pid)][:2]
    assert set(j["resumen"]) == {"total", "hechos", "enlazados", "propuestos", "sugerencias"}
    assert j["resumen"] == {"total": 2, "hechos": 0, "enlazados": 0, "propuestos": 0, "sugerencias": 2}
    h = _de(eq, pid, h1)
    assert set(h) == {"id", "codigo", "texto", "hecho", "hecho_por", "hecho_en", "tareas", "propuesto", "porque",
                      "sugeridas"}
    assert h["codigo"].startswith("HI") and h["hecho"] is False and h["tareas"] == [] and h["propuesto"] is False
    assert [x["codigo"] for x in h["sugeridas"]] == ["PAD-02", "PAD-05"]
    assert set(h["sugeridas"][0]) == {"codigo", "nombre"}
    assert _de(eq, pid, h2)["sugeridas"] == []


def _etapas(pid):
    with db.get_session() as s:
        return db.impl_etapas(s, pid)


def test_enlazar_es_idempotente_valida_la_tarea_y_se_puede_retirar():
    pid, eq = _mundo()
    hid = _hito(pid, "Padrón y listas cargados y conciliados")
    assert _enlazar(eq, pid, hid, "ZZZ-99").status_code == 400
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace", json={}).status_code == 400
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace", json={"codigo": 5}).status_code == 400
    r = _enlazar(eq, pid, hid, "pad-02")
    assert r.status_code == 200 and r.json()["ok"]
    assert [t["codigo"] for t in r.json()["hito"]["tareas"]] == ["PAD-02"]
    assert [x["codigo"] for x in r.json()["hito"]["sugeridas"]] == ["PAD-05"]       # la enlazada deja de sugerirse
    assert _enlazar(eq, pid, hid, "PAD-02").status_code == 200
    assert len(_movs(pid, "hito_enlazado")) == 1                                      # repetido: sin cambios
    m = _movs(pid, "hito_enlazado")[0]
    assert m.codigo == "PAD-02" and m.cantidades["hito"] and "Equipo" in m.quien_nombre
    r = eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": "PAD-02"})
    assert r.status_code == 200 and r.json()["hito"]["tareas"] == []
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": "PAD-02"}).status_code == 409
    assert len(_movs(pid, "hito_desenlazado")) == 1
    with db.get_session() as s:                       # desenlazar no borra: queda quién y cuándo
        fila = s.exec(select(db.XsiiHito).where(db.XsiiHito.hito_id == hid)).one()
        assert fila.activa is False and fila.retirado_por_nombre.startswith("Equipo") and fila.retirado_cuando
    assert _enlazar(eq, pid, hid, "PAD-02").status_code == 200       # se puede volver a enlazar
    assert len(_de(eq, pid, hid)["tareas"]) == 1


def test_un_hito_se_enlaza_a_varias_tareas_y_una_tarea_a_varios_hitos():
    pid, eq = _mundo()
    a, b = _hito(pid, "Primer hito"), _hito(pid, "Segundo hito")
    for hid, codigo in ((a, "BAS-06"), (a, "REC-01"), (b, "BAS-06")):
        assert _enlazar(eq, pid, hid, codigo).status_code == 200
    assert [t["codigo"] for t in _de(eq, pid, a)["tareas"]] == ["BAS-06", "REC-01"]
    ficha = eq.get(f"{BASE}/p/{pid}/tarea/BAS-06").json()["tarea"]
    assert sorted(h["id"] for h in ficha["hitos"]) == sorted([a, b])
    assert all("sugeridas" not in h for h in ficha["hitos"])
    assert eq.get(f"{BASE}/p/{pid}/tarea/REC-01").json()["tarea"]["hitos"][0]["id"] == a
    assert eq.get(f"{BASE}/p/{pid}/tarea/PAD-01").json()["tarea"]["hitos"] == []


def test_aceptar_sugerencias_todas_o_de_algunos_hitos_y_todo_o_nada():
    pid, eq = _mundo()
    a = _hito(pid, "Padrón y listas cargados y conciliados")             # PAD-02, PAD-05
    b = _hito(pid, "Padrón recibido y revisado, con las filas con error")  # PAD-01
    c = _hito(pid, "Escalas con vigencia cargadas")                       # REC-08
    assert _hitos(eq, pid)["resumen"]["sugerencias"] == 4
    r = eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": [a]})
    assert r.status_code == 200 and r.json() == {"ok": True, "enlazados": 2}
    assert [t["codigo"] for t in _de(eq, pid, a)["tareas"]] == ["PAD-02", "PAD-05"]
    # un id que no es de este proyecto: 404 y no se enlaza nada de los demás
    ajeno = _hito(_proyecto(), "Otro")
    r = eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": [b, ajeno]})
    assert r.status_code == 404 and _de(eq, pid, b)["tareas"] == []
    for malo in ([True], ["x"], "a", [2 ** 40]):
        assert eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": malo}).status_code == 400, malo
    # sin cuerpo o vacío = todas
    r = eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar")
    assert r.status_code == 200 and r.json()["enlazados"] == 2
    assert eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={}).json()["enlazados"] == 0
    assert _hitos(eq, pid)["resumen"]["sugerencias"] == 0
    assert [t["codigo"] for t in _de(eq, pid, c)["tareas"]] == ["REC-08"]
    assert len(_movs(pid, "hito_enlazado")) == 4


# ---------------------------------------------------------------- hitos: cuándo se propone

def test_un_hito_se_propone_cuando_todas_sus_tareas_estan_resueltas():
    pid, eq = _mundo()
    hid = _hito(pid, "Un hito con dos tareas")
    _enlazar(eq, pid, hid, "BAS-06")
    _enlazar(eq, pid, hid, "REC-01")
    h = _de(eq, pid, hid)
    assert h["propuesto"] is False and h["porque"] == "" and not any(t["resuelta"] for t in h["tareas"])
    _resolver(eq, pid, "BAS-06")
    h = _de(eq, pid, hid)
    assert h["propuesto"] is False and [t["resuelta"] for t in h["tareas"]] == [True, False]
    assert eq.get(f"{BASE}/p/{pid}/tablero").json()["hitos"] == {"propuestos": 0, "sugerencias": 0}
    _resolver(eq, pid, "REC-01")
    h = _de(eq, pid, hid)
    assert h["propuesto"] is True and "BAS-06" in h["porque"] and "REC-01" in h["porque"]
    assert set(h["tareas"][0]) == {"codigo", "nombre", "estado", "resuelta"}
    assert eq.get(f"{BASE}/p/{pid}/tablero").json()["hitos"] == {"propuestos": 1, "sugerencias": 0}
    assert _hitos(eq, pid)["resumen"]["propuestos"] == 1
    r = eq.post(f"{BASE}/p/{pid}/tarea/REC-01/decision/deshacer", json={"tipo": "completada_a_mano"})
    assert r.status_code == 200 and _de(eq, pid, hid)["propuesto"] is False


def test_una_tarea_que_no_aplica_ni_cuenta_ni_frena_pero_si_todas_no_aplican_no_se_propone():
    pid, eq = _mundo()
    solo_no_aplica, mezcla = _hito(pid, "Hito solo con una tarea que no aplica"), _hito(pid, "Hito mixto")
    _enlazar(eq, pid, solo_no_aplica, "BAS-06")
    _enlazar(eq, pid, mezcla, "BAS-06")
    _enlazar(eq, pid, mezcla, "REC-01")
    r = eq.post(f"{BASE}/p/{pid}/tarea/BAS-06/decision", json={"tipo": "no_aplica", "motivo": "no corresponde acá"})
    assert r.status_code == 200
    assert _de(eq, pid, solo_no_aplica)["propuesto"] is False
    assert _de(eq, pid, mezcla)["propuesto"] is False                       # falta REC-01
    _resolver(eq, pid, "REC-01")
    m = _de(eq, pid, mezcla)
    assert m["propuesto"] is True and "REC-01" in m["porque"] and "BAS-06" not in m["porque"]
    assert _de(eq, pid, solo_no_aplica)["propuesto"] is False
    assert eq.post(f"{BASE}/p/{pid}/hitos/{solo_no_aplica}/marcar").status_code == 409
    assert _hito_mesa(solo_no_aplica) == (False, "")


def test_un_hito_sin_tareas_o_ya_hecho_no_se_propone():
    pid, eq = _mundo()
    suelto, hecho = _hito(pid, "Reunión con las autoridades"), _hito(pid, "Ya estaba tildado")
    _enlazar(eq, pid, hecho, "BAS-06")
    _resolver(eq, pid, "BAS-06")
    with db.get_session() as s:
        db.impl_tildar_hito(s, pid, hecho, SIND)
    assert _de(eq, pid, suelto)["propuesto"] is False
    h = _de(eq, pid, hecho)
    assert h["hecho"] is True and h["propuesto"] is False and h["hecho_por"] == "Carla (sindicato)" and h["hecho_en"]
    assert eq.post(f"{BASE}/p/{pid}/hitos/{suelto}/marcar").status_code == 409
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hecho}/marcar").status_code == 409


def test_sin_sindicato_los_hitos_se_listan_y_enlazan_pero_nada_se_propone():
    pid, eq = _proyecto(False), _equipo()
    hid = _hito(pid, "Un hito")
    assert _enlazar(eq, pid, hid, "BAS-06").status_code == 200
    j = _hitos(eq, pid)
    assert j["resumen"]["propuestos"] == 0 and _de(eq, pid, hid)["tareas"][0]["estado"] == ""
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").status_code == 409


# ---------------------------------------------------------------- hitos: marcar

def _propuesto(eq, pid, texto="Hito listo para marcar", tareas=("BAS-06",)):
    hid = _hito(pid, texto)
    for t in tareas:
        _enlazar(eq, pid, hid, t)
        _resolver(eq, pid, t)
    assert _de(eq, pid, hid)["propuesto"] is True
    return hid


def test_marcar_tilda_el_hito_en_la_mesa_a_nombre_de_la_persona_y_deja_el_movimiento():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid, "Texto libre que NO debe viajar al registro de XSII", ("BAS-06", "REC-01"))
    r = eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar")
    assert r.status_code == 200 and r.json()["ok"]
    h = r.json()["hito"]
    assert h["hecho"] is True and h["propuesto"] is False and h["hecho_por"].startswith("Equipo ")
    hecho, por = _hito_mesa(hid)
    assert hecho is True and por.startswith("Equipo ")
    with db.get_session() as s:                                  # el evento de la Mesa también es de la persona
        evs = [e for e in s.exec(select(db.ImplEvento).where(db.ImplEvento.proyecto_id == pid)).all() if e.accion == "hito"]
        assert len(evs) == 1 and evs[0].actor_nombre.startswith("Equipo ") and evs[0].detalle["hecho"] is True
    (m,) = _movs(pid, "hito_marcado")
    assert m.cantidades["tareas"] == ["BAS-06", "REC-01"] and m.cantidades["hito"] == h["codigo"] and m.codigo == ""
    assert "Texto libre" not in m.texto and h["codigo"] in m.texto and "BAS-06" in m.texto
    assert "Texto libre" not in json.dumps(m.cantidades)
    # una vez marcado ya no está propuesto, no se vuelve a marcar y XSII no ofrece desmarcar
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").status_code == 409
    assert len(_movs(pid, "hito_marcado")) == 1
    assert eq.get(f"{BASE}/p/{pid}/tablero").json()["hitos"]["propuestos"] == 0
    # con una sola tarea, el movimiento queda en la ficha de esa tarea
    hid2 = _propuesto(eq, pid, "Otro", ("PAD-01",))
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid2}/marcar").status_code == 200
    assert _movs(pid, "hito_marcado")[-1].codigo == "PAD-01"
    hist = eq.get(f"{BASE}/p/{pid}/tarea/PAD-01").json()["historial"]
    assert any(x["tipo"] == "hito_marcado" for x in hist)


def test_marcar_se_revalida_adentro_de_la_transaccion(monkeypatch):
    pid, eq = _mundo()
    hid = _propuesto(eq, pid)
    # El tablero que armó la ruta decía «propuesto», pero adentro, ya con el hito bloqueado, ya no.
    monkeypatch.setattr(hitos_mod, "revalidar", lambda ctx, h: ("Cambió mientras tanto: ya no se propone.", []))
    r = eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar")
    assert r.status_code == 409 and r.json()["detail"] == "Cambió mientras tanto: ya no se propone."
    assert _hito_mesa(hid) == (False, "") and _movs(pid, "hito_marcado") == []


def test_marcar_si_la_tarea_dejo_de_estar_resuelta_es_409_con_el_motivo():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid, tareas=("BAS-06", "REC-01"))
    eq.post(f"{BASE}/p/{pid}/tarea/REC-01/decision/deshacer", json={"tipo": "completada_a_mano"})
    r = eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar")
    assert r.status_code == 409 and "REC-01" in r.json()["detail"]
    assert _hito_mesa(hid) == (False, "")


def test_marcar_si_alguien_lo_tildo_en_la_mesa_es_409():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid)
    with db.get_session() as s:
        db.impl_tildar_hito(s, pid, hid, SIND)
    r = eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar")
    assert r.status_code == 409 and "ya está marcado" in r.json()["detail"]
    assert _hito_mesa(hid) == (True, "Carla (sindicato)")             # no se lo pisa
    assert _movs(pid, "hito_marcado") == []


def test_dos_marcados_a_la_vez_solo_pasa_uno():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid)
    otro = _equipo()
    resultados, barrera = [], threading.Barrier(2)

    def marcar(c):
        barrera.wait()
        resultados.append(c.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").status_code)
    hilos = [threading.Thread(target=marcar, args=(c,)) for c in (eq, otro)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    assert sorted(resultados) == [200, 409], resultados
    assert len(_movs(pid, "hito_marcado")) == 1
    with db.get_session() as s:
        evs = [e for e in s.exec(select(db.ImplEvento).where(db.ImplEvento.proyecto_id == pid)).all() if e.accion == "hito"]
        assert len(evs) == 1


def test_el_marcado_no_se_dispara_solo_ni_con_todas_las_tareas_hechas():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid)
    assert _hito_mesa(hid) == (False, "")           # XSII propone; quien tilda es una persona
    assert _hitos(eq, pid)["resumen"]["propuestos"] == 1


# ---------------------------------------------------------------- «Preguntame»

def test_preguntame_lee_los_hitos_sin_su_texto():
    pid, eq = _mundo()
    secreto = "Texto del hito con instrucciones para el asistente"
    hid = _propuesto(eq, pid, secreto)
    _hito(pid, "Otro hito sin enlazar")
    with db.get_session() as s:
        ctx = vista.Contexto(s, pid)
        inst = herr.Instantanea.armar(s, ctx)
    esquema, funcion = herr.herramientas(inst)["ver_hitos"]
    assert esquema["input_schema"]["properties"] == {}
    salida = funcion()
    assert salida["cantidad"] == 2 and salida["resumen"]["propuestos"] == 1
    estados = {h["estado"] for h in salida["hitos"]}
    assert estados == {"propuesto", "sin enlazar"}
    prop = next(h for h in salida["hitos"] if h["estado"] == "propuesto")
    assert prop["tareas"][0]["codigo"] == "BAS-06" and set(prop) == {"codigo", "estado", "tareas"}
    assert secreto not in json.dumps(salida, ensure_ascii=False) and "Otro hito" not in json.dumps(salida)
    assert hid


# ---------------------------------------------------------------- archivos de los insumos

CLAVE = "lista_seccionales"


def _tarjeta(pid, titulo="Lista de seccionales"):
    with db.get_session() as s:
        t = db.impl_crear_tarjeta(s, pid, EQ, "pedido", titulo, "Mandanos la planilla")
        return t.id, t.codigo


def _subir(pid, tid, nombre="seccionales.csv", datos=None, actor=SIND, datos_personales=False):
    with db.get_session() as s:
        a = db.impl_subir_archivo(s, pid, tid, actor, nombre, "text/csv", datos if datos is not None else (CAB + FILA).encode(),
                                  datos_personales=datos_personales)
        return a.id, a.codigo


def _pedir(eq, pid, tid=None, clave=CLAVE):
    cuerpo = {"estado": "pedido"}
    if tid is not None:
        cuerpo["tarjeta"] = tid
    r = eq.post(f"{BASE}/p/{pid}/insumo/{clave}", json=cuerpo)
    assert r.status_code == 200, r.text
    return r.json()["insumo"]


def _tiempos(pid, clave, cuando, subidos=None):
    """Fija a mano `cuando` del insumo y `subido_en` de los archivos (los segundos no alcanzan en un test)."""
    with db.get_session() as s:
        i = s.exec(select(db.XsiiInsumo).where(db.XsiiInsumo.proyecto_id == pid, db.XsiiInsumo.clave == clave,
                                               db.XsiiInsumo.activa == True)).one()   # noqa: E712
        i.cuando = cuando
        s.add(i)
        for aid, c in (subidos or {}).items():
            a = s.get(db.ImplArchivo, aid)
            a.subido_en = c
            s.add(a)
        s.commit()


def _insumo_tablero(eq, pid, clave=CLAVE):
    t = eq.get(f"{BASE}/p/{pid}/tablero").json()
    return next(i for x in t["tareas"] for i in x["insumos"] if i["clave"] == clave)


def test_listar_los_archivos_de_la_tarjeta_enlazada_sin_bytes():
    pid, eq = _mundo()
    assert eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json() == {"tarjeta": None, "archivos": []}
    tid, codigo = _tarjeta(pid)
    otra, _ = _tarjeta(pid, "Otra cosa")
    _pedir(eq, pid, tid)
    a1, c1 = _subir(pid, tid, "uno.csv", actor=SIND, datos_personales=True)
    a2, c2 = _subir(pid, tid, "dos.csv", actor=EQ)
    _subir(pid, otra, "ajeno.csv")                                   # de otra tarjeta: no aparece
    borrado, _ = _subir(pid, tid, "borrado.csv")
    with db.get_session() as s:
        db.impl_borrar_archivo(s, pid, borrado, SIND)
    r = eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos")
    assert r.status_code == 200
    j = r.json()
    assert j["tarjeta"] == {"codigo": codigo, "titulo": "Lista de seccionales", "estado": "abierta"}
    assert [a["id"] for a in j["archivos"]] == [a2, a1]                # del más nuevo al más viejo; sin el borrado
    a = j["archivos"][1]
    assert set(a) == {"id", "codigo", "nombre", "tamano", "subido_por", "lado", "cuando", "datos_personales", "elegido"}
    assert a["codigo"] == c1 and a["lado"] == "sindicato" and a["subido_por"] == "Carla (sindicato)"
    assert a["datos_personales"] is True and a["elegido"] is False and a["tamano"] == len((CAB + FILA).encode())
    assert '"datos"' not in r.text and "Seccional Rosario" not in r.text
    assert eq.get(f"{BASE}/p/{pid}/insumo/NOEXISTE/archivos").status_code == 404


def test_fijar_el_archivo_deja_el_insumo_recibido_y_lo_marca_elegido():
    pid, eq = _mundo()
    tid, _c = _tarjeta(pid)
    _pedir(eq, pid, tid)
    aid, acod = _subir(pid, tid, "planilla-secreta.csv")
    r = eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid})
    assert r.status_code == 200 and r.json()["ok"]
    i = r.json()["insumo"]
    assert i["estado"] == "recibido" and i["tarjeta"]["id"] == tid
    j = eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json()
    assert [a["elegido"] for a in j["archivos"]] == [True]
    with db.get_session() as s:
        reg = db.xsii_insumos_activos(s, pid)[CLAVE]
        assert reg.archivo_id == aid and reg.tarjeta_id == tid and reg.estado == "recibido"
    (m,) = _movs(pid, "insumo_archivo")
    assert m.clave_insumo == CLAVE and acod in m.texto
    assert "planilla-secreta" not in m.texto and "Seccional Rosario" not in m.texto + json.dumps(m.cantidades)
    # un segundo archivo reemplaza al fijado
    a2, _ = _subir(pid, tid, "otra.csv")
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": a2}).status_code == 200
    assert [a["id"] for a in eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json()["archivos"] if a["elegido"]] == [a2]


def test_fijar_un_archivo_que_no_corresponde_es_404_o_400():
    pid, eq = _mundo()
    tid, _c = _tarjeta(pid)
    otra, _ = _tarjeta(pid, "Otra")
    ajeno_pid = _proyecto()
    ajeno_tid, _ = _tarjeta(ajeno_pid)
    url = f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo"
    aid, _ = _subir(pid, tid)
    assert eq.post(url, json={"archivo_id": aid}).status_code == 404          # el insumo no tiene tarjeta enlazada
    _pedir(eq, pid, tid)
    de_otra, _ = _subir(pid, otra)
    de_otro_proyecto, _ = _subir(ajeno_pid, ajeno_tid)
    borrado, _ = _subir(pid, tid)
    with db.get_session() as s:
        db.impl_borrar_archivo(s, pid, borrado, SIND)
    for malo in (de_otra, de_otro_proyecto, borrado, aid + 100000):
        assert eq.post(url, json={"archivo_id": malo}).status_code == 404, malo
    for roto in ({}, {"archivo_id": "x"}, {"archivo_id": True}, {"archivo_id": [1]}, {"archivo_id": 2 ** 40}):
        assert eq.post(url, json=roto).status_code == 400, roto
    assert _insumo_tablero(eq, pid)["estado"] == "pedido"
    assert _movs(pid, "insumo_archivo") == []
    assert eq.post(f"{BASE}/p/{pid}/insumo/NOEXISTE/archivo", json={"archivo_id": aid}).status_code == 404


def test_el_tablero_cuenta_los_archivos_nuevos_del_sindicato_si_el_insumo_sigue_pedido():
    pid, eq = _mundo()
    tid, codigo = _tarjeta(pid)
    assert _insumo_tablero(eq, pid)["archivos_nuevos"] == 0
    _pedir(eq, pid, tid)
    viejo, _ = _subir(pid, tid, "viejo.csv", actor=SIND)
    nuevo1, _ = _subir(pid, tid, "nuevo1.csv", actor=SIND)
    nuevo2, _ = _subir(pid, tid, "nuevo2.csv", actor=SIND)
    del_equipo, _ = _subir(pid, tid, "nuestro.csv", actor=EQ)
    _tiempos(pid, CLAVE, "2026-11-20 10:00:00",
             {viejo: "2026-11-19 09:00:00", nuevo1: "2026-11-21 09:00:00", nuevo2: "2026-11-22 09:00:00",
              del_equipo: "2026-11-23 09:00:00"})
    assert _insumo_tablero(eq, pid)["archivos_nuevos"] == 2
    ficha = eq.get(f"{BASE}/p/{pid}/tarea/EST-01").json()["tarea"]
    assert next(i for i in ficha["insumos"] if i["clave"] == CLAVE)["archivos_nuevos"] == 2
    with db.get_session() as s:                                    # un archivo borrado ya no cuenta
        db.impl_borrar_archivo(s, pid, nuevo2, SIND)
    assert _insumo_tablero(eq, pid)["archivos_nuevos"] == 1
    # recibido: ya no avisa
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": nuevo1}).status_code == 200
    assert _insumo_tablero(eq, pid)["archivos_nuevos"] == 0
    assert codigo


# ---------------------------------------------------------------- archivo de la Mesa en una asistida

def _url(pid, que, codigo="EST-01"):
    return f"{BASE}/p/{pid}/tarea/{codigo}/asistida" + (f"/{que}" if que else "")


def _fijado(eq, pid, datos=None, nombre="seccionales.csv"):
    tid, _c = _tarjeta(pid)
    _pedir(eq, pid, tid)
    aid, acod = _subir(pid, tid, nombre, datos)
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 200
    return aid, acod


def _seccionales(sid):
    with db.get_session() as s:
        return list(s.exec(select(db.Seccional).where(db.Seccional.sindicato_id == sid)).all())


def _sid(pid):
    with db.get_session() as s:
        return db.impl_proyecto(s, pid).sindicato_id


def test_la_asistida_informa_el_archivo_fijado_y_lo_usa_en_el_ensayo_y_la_carga():
    pid, eq = _mundo()
    assert eq.get(_url(pid, "")).json()["archivo_mesa"] is None
    aid, acod = _fijado(eq, pid)
    g = eq.get(_url(pid, "")).json()
    assert g["archivo_mesa"] == {"id": aid, "codigo": acod, "nombre": "seccionales.csv"}
    r = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)})
    assert r.status_code == 200, r.text
    ens = r.json()
    assert ens["huella"] and ens["total"] == 1 and _seccionales(_sid(pid)) == []        # el ensayo no escribe
    # el mismo ensayo con el archivo subido a mano da la misma huella
    a_mano = eq.post(_url(pid, "ensayo"), files={"archivo": ("a.csv", (CAB + FILA).encode(), "text/csv")}).json()
    assert a_mano["huella"] == ens["huella"]
    r = eq.post(_url(pid, "carga"), data={"archivo_mesa": str(aid), "huella": ens["huella"]})
    assert r.status_code == 200, r.text
    assert [x.nombre for x in _seccionales(_sid(pid))] == ["Seccional Rosario"]
    assert r.json()["carga"]["creadas"] == 1
    # la descarga queda registrada como toda descarga de la Mesa, a nombre de la persona y dicha como de XSII
    with db.get_session() as s:
        descargas = db.impl_descargas(s, pid, aid)
        assert len(descargas) == 2 and all(d.lado == "equipo" and d.nombre.startswith("Equipo ") for d in descargas)
        bajas = [e for e in s.exec(select(db.ImplEvento).where(db.ImplEvento.proyecto_id == pid)).all() if e.accion == "bajar"]
        assert len(bajas) == 2 and all(e.detalle["motivo"] == "xsii" and e.actor_nombre.startswith("Equipo ") for e in bajas)
    # ni el nombre del archivo ni su contenido van a los movimientos de XSII
    for m in _movs(pid):
        assert "seccionales.csv" not in m.texto and "Seccional Rosario" not in m.texto + json.dumps(m.cantidades)


def test_el_archivo_de_la_mesa_se_valida_igual_que_una_planilla():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid, datos=b"esto no es una planilla\x00\x01")
    r = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)})
    assert r.status_code == 400 and r.json()["detail"]
    assert _seccionales(_sid(pid)) == []


def test_archivo_de_la_mesa_que_no_es_el_fijado_o_que_no_existe_o_viene_mal():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid)
    tid2, _c = _tarjeta(pid, "Otra")
    otro, _ = _subir(pid, tid2)                                       # de este proyecto pero no el fijado
    ajeno_pid = _proyecto()
    ajeno_tid, _ = _tarjeta(ajeno_pid)
    ajeno, _ = _subir(ajeno_pid, ajeno_tid)
    for malo in (otro, ajeno, aid + 100000):
        assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(malo)}).status_code == 404, malo
        assert eq.post(_url(pid, "carga"), data={"archivo_mesa": str(malo), "huella": "x"}).status_code == 404, malo
    for roto in ("abc", "-3", "1.5", str(2 ** 40)):
        assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": roto}).status_code == 400, roto
    r = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}, files={"archivo": ("a.csv", (CAB + FILA).encode())})
    assert r.status_code == 400
    r = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid), "texto": CAB + FILA})
    assert r.status_code == 400
    with db.get_session() as s:
        assert db.impl_descargas(s, pid, otro) == [] and db.impl_descargas(s, ajeno_pid, ajeno) == []
    # una tarea que no tiene planilla (o un archivo fijado a OTRO insumo) tampoco lo acepta
    assert eq.post(_url(pid, "ensayo", "BAS-01"), data={"archivo_mesa": str(aid)}).status_code == 404
    assert eq.post(_url(pid, "ensayo", "PAD-02"), data={"archivo_mesa": str(aid)}).status_code == 404


def test_si_el_archivo_fijado_se_borra_la_asistida_deja_de_ofrecerlo():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid)
    with db.get_session() as s:
        db.impl_borrar_archivo(s, pid, aid, SIND)
    assert eq.get(_url(pid, "")).json()["archivo_mesa"] is None
    r = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)})
    assert r.status_code == 409 and "borrado" in r.json()["detail"]


def test_la_asistida_de_recibos_no_usa_archivos_de_la_mesa():
    pid, eq = _mundo()
    assert eq.get(_url(pid, "", "REC-04")).json()["archivo_mesa"] is None


# ---------------------------------------------------------------- las sugerencias y la migración

def test_el_json_de_sugerencias_es_coherente_con_el_catalogo_y_la_semilla():
    sugerencias = json.loads(SUGERIDOS.read_text(encoding="utf-8"))
    assert isinstance(sugerencias, list) and sugerencias
    semilla = [h["texto"] for f in json.loads(SEMILLA.read_text(encoding="utf-8"))["fases"] for h in f["hitos"]]
    existentes = {t.codigo for t in catalogo.TAREAS}
    for e in sugerencias:
        assert set(e) == {"texto_contiene", "tareas"}
        assert e["texto_contiene"] and e["tareas"] and all(isinstance(f, str) and f.strip() for f in e["texto_contiene"])
        assert set(e["tareas"]) <= existentes, e
        assert len(set(e["tareas"])) == len(e["tareas"])
        # las frases se escriben ya sin mayúsculas ni tildes
        assert all(f == hitos_mod.normalizar(f) for f in e["texto_contiene"]), e
        coinciden = [t for t in semilla if all(f in hitos_mod.normalizar(t) for f in e["texto_contiene"])]
        assert len(coinciden) >= 1, f"la sugerencia {e} no coincide con ningún hito de la semilla"
        assert len(coinciden) == 1, f"la sugerencia {e} es ambigua: {coinciden}"
    # todas las definidas se leen (ninguna se descartó por mal formada)
    assert len(hitos_mod.sugerencias_definidas()) == len(sugerencias)
    # un hito que es una reunión o un acuerdo no recibe nada
    assert hitos_mod.sugeridas_para("Reunión estratégica con las autoridades realizada y acta cargada.") == []
    assert hitos_mod.sugeridas_para("Día fijo de la reunión semanal y de la demostración quincenal.") == []
    # sin mayúsculas ni tildes
    assert hitos_mod.sugeridas_para("PADRÓN Y LISTAS CARGADOS Y CONCILIADOS") == ["PAD-02", "PAD-05"]


def test_las_sugerencias_sobre_los_hitos_semilla_de_la_bancaria():
    semilla = [h["texto"] for f in json.loads(SEMILLA.read_text(encoding="utf-8"))["fases"] for h in f["hitos"]]
    con = {t: hitos_mod.sugeridas_para(t) for t in semilla}
    enlazan = {t: c for t, c in con.items() if c}
    assert len(enlazan) == len(json.loads(SUGERIDOS.read_text(encoding="utf-8")))     # cada sugerencia, un solo hito
    assert len(semilla) == 45 and len(enlazan) == 10


def test_la_migracion_es_idempotente_sobre_una_base_donde_la_tabla_ya_existe():
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    ruta = next(Path(__file__).parent.glob("migrations/versions/*_xsii_hitos.py"))
    spec = importlib.util.spec_from_file_location("mig_xsii_hitos", ruta)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.down_revision == "d3f5a7b9c1e4"
    with db.engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()                                  # la tabla ya está (crear_tablas): no hace nada ni falla
            mig.upgrade()
        assert "xsiihito" in {r[0] for r in conn.exec_driver_sql("select tablename from pg_tables")}


def test_la_tabla_esta_declarada_fuera_del_clonado_y_del_borrado():
    assert "xsiihito" in db.XSII_TABLAS
    assert not any(c.foreign_keys for c in db.XsiiHito.__table__.columns)
