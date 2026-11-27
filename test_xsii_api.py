"""XSII bloque 1, la API por HTTP (docs/xsii/API.md): puertas, la forma del
tablero, cada regla de decisión, deshacer, insumos con su tarjeta de la Mesa,
movimientos y entradas hostiles (siempre un 4xx, nunca un 500).

Correr con: python -m pytest test_xsii_api.py -q
"""
import os
from datetime import timedelta

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import itertools
import uuid

import pytest
from fastapi.testclient import TestClient

import auth
import cuit
import db
import fechas
from sqlmodel import select
import entorno
import implementacion as im
import main
import modulos
from xsii.proyectos.colm3na import catalogo

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
_n = itertools.count(1)
BASE = "/api/entornos/xsii"


def _sindicato(modulos_habilitados=None):
    n = next(_n)
    with db.get_session() as s:
        sind = db.Sindicato(nombre=f"Sindicato API XSII {n} {uuid.uuid4().hex[:4]}", slug=f"xsii-api-{n}-{uuid.uuid4().hex[:4]}",
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
        return db.impl_crear_proyecto(s, nombre or "XSII " + uuid.uuid4().hex[:8], EQ, sindicato_id=sid).id


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


def _tarjeta(pid, titulo="Padrón"):
    with db.get_session() as s:
        t = db.impl_crear_tarjeta(s, pid, EQ, "pedido", titulo, "Mandanos la planilla")
        return t.id, t.codigo


# ---------------------------------------------------------------- puertas

RUTAS_GET = ["proyectos", "p/{pid}/tablero", "p/{pid}/tarea/BAS-01", "p/{pid}/movimientos"]
RUTAS_POST = ["p/{pid}/tarea/BAS-01/decision", "p/{pid}/tarea/BAS-01/decision/deshacer",
              "p/{pid}/insumo/planilla_padron", "p/{pid}/insumo/planilla_padron/retirar"]


def test_sin_sesion_es_403_y_con_sesion_vencida_401():
    pid = _proyecto()
    anonimo = TestClient(main.app, follow_redirects=False)
    for ruta in RUTAS_GET:
        assert anonimo.get(f"{BASE}/{ruta.format(pid=pid)}").status_code == 403, ruta
    for ruta in RUTAS_POST:
        assert anonimo.post(f"{BASE}/{ruta.format(pid=pid)}", json={}).status_code == 403, ruta
    baja = _equipo(activo=False)         # sesión vigente de un usuario dado de baja
    assert baja.get(f"{BASE}/proyectos").status_code == 401
    assert baja.post(f"{BASE}/p/{pid}/tarea/BAS-01/decision", json={"tipo": "pospuesta"}).status_code == 401


def test_el_usuario_del_sindicato_de_la_mesa_no_entra():
    """Quien entra a la Mesa con su usuario del sindicato no es del equipo."""
    pid = _proyecto()
    mail = f"{uuid.uuid4().hex[:8]}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, "Carla", mail, "transitoria1", EQ)
        db.impl_usuario_cambiar_clave(s, u.id, "transitoria1", "definitiva-2026")
    c = TestClient(main.app, follow_redirects=False)
    assert c.post("/implementacion/ingresar", data={"mail": mail, "clave": "definitiva-2026"}).status_code == 303
    assert c.get(f"{BASE}/p/{pid}/tablero").status_code == 403
    assert c.post(f"{BASE}/p/{pid}/tarea/BAS-01/decision", json={"tipo": "pospuesta"}).status_code == 403


def test_en_demo_todo_es_404(monkeypatch):
    pid, eq = _mundo()
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    for ruta in RUTAS_GET:
        assert eq.get(f"{BASE}/{ruta.format(pid=pid)}").status_code == 404, ruta
    for ruta in RUTAS_POST:
        assert eq.post(f"{BASE}/{ruta.format(pid=pid)}", json={}).status_code == 404, ruta
    assert eq.get("/entornos/xsii").status_code == 404
    assert eq.get(f"/entornos/xsii/{pid}").status_code == 404


def test_proyecto_inexistente_o_con_id_enorme_es_404():
    pid, eq = _mundo()
    for n in (pid + 100000, 0, -1, 2 ** 31, 10 ** 30):
        for ruta in ("p/{n}/tablero", "p/{n}/tarea/BAS-01", "p/{n}/movimientos"):
            assert eq.get(f"{BASE}/{ruta.format(n=n)}").status_code == 404, (n, ruta)
        assert eq.post(f"{BASE}/p/{n}/tarea/BAS-01/decision", json={"tipo": "pospuesta"}).status_code == 404
        assert eq.post(f"{BASE}/p/{n}/insumo/planilla_padron", json={"estado": "pedido"}).status_code == 404
    assert eq.get(f"{BASE}/p/abc/tablero").status_code in (404, 422)


def test_las_paginas_piden_pase_y_la_del_proyecto_se_renderiza():
    pid, eq = _mundo()
    anonimo = TestClient(main.app, follow_redirects=False, headers={"accept": "text/html"})
    assert anonimo.get("/entornos/xsii").headers["location"].startswith("/entornos")
    assert anonimo.get(f"/entornos/xsii/{pid}").status_code == 303
    assert TestClient(main.app).get(f"/entornos/xsii/{pid}", follow_redirects=False).status_code == 403
    r = eq.get(f"/entornos/xsii/{pid}")
    assert r.status_code == 200 and "XSII" in r.text
    assert eq.get(f"/entornos/xsii/{pid + 100000}").status_code == 404
    assert eq.get(f"/entornos/xsii/{2 ** 31}").status_code == 404


def test_la_lista_de_proyectos_va_directo_si_hay_uno_solo_y_si_no_a_la_pestana_de_entornos(monkeypatch):
    pid, eq = _mundo()
    unico = [type("P", (), {"id": pid, "nombre": "uno"})()]
    monkeypatch.setattr(db, "impl_proyectos", lambda s: unico)
    r = eq.get("/entornos/xsii")
    assert r.status_code == 303 and r.headers["location"] == f"/entornos/xsii/{pid}"
    dos = unico + [type("P", (), {"id": pid + 1, "nombre": "<script>x</script>"})()]
    for lista in (dos, []):
        monkeypatch.setattr(db, "impl_proyectos", lambda s, lista=lista: lista)
        r = eq.get("/entornos/xsii")
        assert r.status_code == 303 and r.headers["location"] == "/entornos#implementacion"
        assert "<script>" not in r.text


# ---------------------------------------------------------------- proyectos y tablero

def test_la_lista_de_proyectos_trae_el_sindicato():
    pid, eq = _mundo()
    sin = _proyecto(con_sindicato=False)
    lista = {p["id"]: p for p in eq.get(f"{BASE}/proyectos").json()["proyectos"]}
    assert set(lista[pid]) == {"id", "nombre", "activo", "sindicato_id", "sindicato_nombre"}
    assert lista[pid]["sindicato_id"] and lista[pid]["sindicato_nombre"].startswith("Sindicato API XSII")
    assert lista[sin]["sindicato_id"] is None and lista[sin]["sindicato_nombre"] is None


def test_la_forma_del_tablero_es_la_del_contrato():
    pid, eq = _mundo()
    t = _tablero(eq, pid)
    assert set(t) == {"proyecto", "disponible", "motivo", "grupos", "rotulos", "resumen", "recomendada",
                      "alternativas", "demorados", "tareas", "movimientos", "preguntame"}
    assert t["disponible"] is True and t["motivo"] == ""
    assert t["proyecto"]["mesa_url"] == f"/implementacion?p={pid}" and t["proyecto"]["sindicato_nombre"]
    assert t["grupos"] == list(catalogo.GRUPOS)
    assert set(t["rotulos"]) == {"estados", "modos", "decisiones"}
    assert t["rotulos"]["estados"]["lista"] == "Se puede hacer"
    assert set(t["resumen"]) == {"total", "aplican", "resueltas", "porcentaje", "por_confirmar", "a_mano",
                                 "con_observaciones", "pospuestas", "por_estado"}
    assert t["resumen"]["total"] == 34 and len(t["tareas"]) == 34
    assert [x["codigo"] for x in t["tareas"]] == [x.codigo for x in catalogo.TAREAS]
    assert set(t["recomendada"]) == {"codigo", "por_que", "destraba", "como"}
    assert t["recomendada"]["por_que"] and t["recomendada"]["como"]
    assert t["movimientos"] == [] and t["demorados"] == []
    claves = {"codigo", "nombre", "grupo", "modo", "descripcion", "para_que", "pasos", "aplica_si", "estado", "con_observaciones",
              "a_mano", "pospuesta", "no_aplica_por", "falta_confirmar", "confirmacion", "detalle", "necesita",
              "mejora_con", "frenada_por", "avisos", "camino", "necesitada_por", "destraba", "nivel", "donde",
              "control", "decisiones", "insumos", "acciones", "asistida"}
    for x in t["tareas"]:
        assert set(x) == claves, x["codigo"]
        assert set(x["acciones"]) == {"confirmar", "completar_a_mano", "no_aplica", "posponer", "deshacer"}
        assert set(x["destraba"]) == {"directo", "transitivo"}
        assert x["control"] and set(x["control"]) == {"estado", "resumen", "cifras", "faltan", "en_curso"}
        assert x["detalle"], x["codigo"]


def test_detalle_nivel_donde_y_camino_de_una_tarea():
    pid, eq = _mundo()
    por = {x["codigo"]: x for x in _tablero(eq, pid)["tareas"]}
    pad = por["PAD-02"]
    assert pad["estado"] == "bloqueada" and pad["detalle"].startswith("Espera a ")
    assert "Seccionales" in pad["detalle"] and " y " in pad["detalle"]
    assert set(pad["camino"]) == {"EST-01", "PAD-01"}
    assert pad["donde"] == {"url": "/admin#trabajadores", "rotulo": "Panel del sindicato · Trabajadores"}
    assert pad["necesitada_por"][:1] == ["PAD-03"] and "PAD-03" in pad["destraba"]["directo"]
    assert por["BAS-01"]["nivel"] == 0 and por["BAS-02"]["nivel"] == 1 and pad["nivel"] > por["EST-01"]["nivel"]
    assert por["BAS-01"]["donde"]["rotulo"] == "Plataforma"
    assert por["TRA-01"]["detalle"].startswith("Módulo ") and por["TRA-01"]["detalle"].endswith("no contratado")
    assert por["REC-08"]["no_aplica_por"] == "condicion"
    assert por["REC-01"]["estado"] == "esperando" and por["REC-01"]["detalle"].startswith("Falta: Recibos de muestra")
    assert por["BAS-03"]["falta_confirmar"] and por["BAS-03"]["detalle"].startswith("Falta confirmar: ")
    assert por["CIE-03"]["donde"] == {"url": f"/implementacion?p={pid}", "rotulo": "Mesa de implementación"}
    assert por["TRA-02"]["donde"]["rotulo"] == "App del afiliado"
    assert por["REC-08"]["donde"]["rotulo"] == "Herramientas · Convenio y escalas"
    cif = por["BAS-01"]["control"]["cifras"]
    assert all(set(c) == {"clave", "nombre", "valor"} for c in cif)


def test_un_proyecto_sin_sindicato_no_esta_disponible_pero_responde():
    pid, eq = _mundo(con_sindicato=False)
    t = _tablero(eq, pid)
    assert t["disponible"] is False and "sindicato" in t["motivo"]
    assert t["tareas"] == [] and t["alternativas"] == [] and t["demorados"] == []
    assert t["recomendada"] is None and t["resumen"] is None
    assert t["proyecto"]["sindicato_id"] is None and t["proyecto"]["sindicato_nombre"] is None
    assert eq.get(f"{BASE}/p/{pid}/tarea/BAS-01").status_code == 409
    assert _decidir(eq, pid, "BAS-01", "pospuesta").status_code == 409
    # pero un insumo se puede pedir antes del alta
    r = _insumo(eq, pid, "planilla_padron", estado="pedido", nota="antes del alta")
    assert r.status_code == 200 and r.json()["insumo"]["estado"] == "pedido"


def test_un_sindicato_que_ya_no_existe_tampoco_esta_disponible():
    pid, eq = _mundo()
    with db.get_session() as s:
        p = db.impl_proyecto(s, pid)
        p.sindicato_id = 2_000_000_000         # un sindicato que no existe (la Mesa no tiene clave foránea)
        s.add(p)
        s.commit()
    t = _tablero(eq, pid)
    assert t["disponible"] is False and "ya no existe" in t["motivo"] and t["proyecto"]["sindicato_nombre"] is None


def test_dos_proyectos_no_se_mezclan():
    a, eq = _mundo()
    b = _proyecto()
    assert _decidir(eq, a, "COM-02", "pospuesta").status_code == 200
    assert _tarea(eq, a, "COM-02")["pospuesta"] is True
    assert _tarea(eq, b, "COM-02")["pospuesta"] is False and _tablero(eq, b)["movimientos"] == []


# ---------------------------------------------------------------- decisiones: las reglas

def test_completada_a_mano_pide_motivo_y_destraba():
    pid, eq = _mundo()
    assert _tarea(eq, pid, "EST-01")["estado"] in ("lista", "esperando")
    for malo in ("", "   ", "abc"):
        r = _decidir(eq, pid, "COM-02", "completada_a_mano", malo)
        assert r.status_code == 400 and r.json()["detail"] == "El motivo es obligatorio (al menos 5 caracteres)."
    assert _decidir(eq, pid, "COM-02", "completada_a_mano").status_code == 400
    r = _decidir(eq, pid, "COM-02", "completada_a_mano", "se cargan al final")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and set(j) == {"ok", "tarea", "resumen"}
    t = j["tarea"]
    assert t["estado"] == "hecha" and t["a_mano"] and t["decisiones"][0]["tipo"] == "completada_a_mano"
    assert t["detalle"].startswith("Completada a mano por Equipo ") and t["detalle"].endswith("se cargan al final")
    assert t["acciones"]["deshacer"] == ["completada_a_mano"] and not t["acciones"]["completar_a_mano"]
    assert j["resumen"]["a_mano"] == 1
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "otra vez").status_code == 409


def test_completada_a_mano_no_sobre_lo_que_el_control_ya_da_por_hecho_ni_lo_que_no_aplica():
    pid, eq = _mundo()
    r = _decidir(eq, pid, "BAS-01", "completada_a_mano", "ya estaba")
    assert r.status_code == 409 and "hecha" in r.json()["detail"]
    r = _decidir(eq, pid, "TRA-01", "completada_a_mano", "no corresponde")
    assert r.status_code == 409 and "no aplica" in r.json()["detail"]
    assert _decidir(eq, pid, "COM-03", "no_aplica", "no usan beneficios").status_code == 200
    assert _decidir(eq, pid, "COM-03", "completada_a_mano", "igual la hacen").status_code == 409


def test_no_aplica_declarada_pide_motivo_y_no_si_ya_no_aplica_por_condicion():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "COM-03", "no_aplica", "").status_code == 400
    r = _decidir(eq, pid, "COM-03", "no_aplica", "el sindicato no tiene beneficios")
    assert r.status_code == 200 and r.json()["tarea"]["estado"] == "no_aplica"
    t = r.json()["tarea"]
    assert t["no_aplica_por"] == "decision" and t["detalle"] == "Declarada no aplica: el sindicato no tiene beneficios"
    assert _decidir(eq, pid, "COM-03", "no_aplica", "otra vez").status_code == 409
    r = _decidir(eq, pid, "TRA-01", "no_aplica", "no usan trámites")
    assert r.status_code == 409 and "módulo" in r.json()["detail"]


def test_no_aplica_no_con_completada_a_mano_activa_hasta_deshacerla():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "se hizo afuera").status_code == 200
    r = _decidir(eq, pid, "COM-02", "no_aplica", "mejor no aplica")
    assert r.status_code == 409 and "deshacé" in r.json()["detail"]
    assert _deshacer(eq, pid, "COM-02", "completada_a_mano").status_code == 200
    assert _decidir(eq, pid, "COM-02", "no_aplica", "mejor no aplica").status_code == 200


def test_confirmar_solo_si_la_tarea_lo_declara_aplica_y_el_control_pasa():
    pid, eq = _mundo()
    assert _tarea(eq, pid, "BAS-03")["acciones"]["confirmar"] is True
    r = _decidir(eq, pid, "COM-02", "confirmada")                 # no declara confirmación
    assert r.status_code == 409 and "confirmación" in r.json()["detail"]
    r = _decidir(eq, pid, "EST-01", "confirmada")                 # el control no pasa (no hay seccionales)
    assert r.status_code == 409 and "control" in r.json()["detail"]
    assert _decidir(eq, pid, "REC-08", "confirmada").status_code == 409     # no aplica (y no declara)
    r = _decidir(eq, pid, "BAS-03", "confirmada")                 # no pide motivo
    assert r.status_code == 200
    t = r.json()["tarea"]
    assert t["estado"] == "hecha" and t["falta_confirmar"] is False and t["acciones"]["deshacer"] == ["confirmada"]
    assert _decidir(eq, pid, "BAS-03", "confirmada").status_code == 409
    assert _tarea(eq, pid, "BAS-05")["estado"] == "lista"


def test_posponer_solo_lo_no_resuelto_saca_de_recomendada_y_puede_convivir_con_confirmada():
    pid, eq = _mundo()
    rec = _tablero(eq, pid)["recomendada"]["codigo"]
    assert _decidir(eq, pid, "BAS-01", "pospuesta").status_code == 409          # hecha
    assert _decidir(eq, pid, "REC-08", "pospuesta").status_code == 409          # no aplica
    r = _decidir(eq, pid, rec, "pospuesta", "")                                 # sin motivo vale
    assert r.status_code == 200 and r.json()["tarea"]["pospuesta"] is True
    t = _tablero(eq, pid)
    assert t["recomendada"] is None or t["recomendada"]["codigo"] != rec
    assert rec not in t["alternativas"] and t["resumen"]["pospuestas"] == 1
    assert _decidir(eq, pid, rec, "pospuesta").status_code == 409
    # pospuesta + confirmada a la vez
    assert _decidir(eq, pid, "BAS-05", "pospuesta", "después").status_code == 200
    r = _decidir(eq, pid, "BAS-05", "confirmada")
    assert r.status_code == 200
    t = r.json()["tarea"]
    assert t["estado"] == "hecha" and t["pospuesta"] and [d["tipo"] for d in t["decisiones"]] == ["pospuesta", "confirmada"]
    assert t["acciones"]["deshacer"] == ["confirmada", "pospuesta"] or set(t["acciones"]["deshacer"]) == {"confirmada", "pospuesta"}
    assert t["acciones"]["posponer"] is False        # una tarea hecha no se pospone (y ya había una)


def test_deshacer_vuelve_el_estado_deja_la_traza_y_sin_activa_es_409():
    pid, eq = _mundo()
    assert _deshacer(eq, pid, "COM-02", "pospuesta").status_code == 409
    _decidir(eq, pid, "COM-02", "completada_a_mano", "hecho afuera")
    r = _deshacer(eq, pid, "COM-02", "completada_a_mano", "me equivoqué")
    assert r.status_code == 200
    t = r.json()["tarea"]
    assert t["estado"] == "lista" and t["decisiones"] == [] and t["acciones"]["deshacer"] == []
    hist = eq.get(f"{BASE}/p/{pid}/tarea/COM-02").json()["historial"]
    assert [h["tipo"] for h in hist] == ["decision_deshecha", "decision"]
    assert "Deshizo «Completada a mano» de Noticias iniciales: me equivoqué" == hist[0]["texto"]
    assert _deshacer(eq, pid, "COM-02", "completada_a_mano").status_code == 409
    assert _decidir(eq, pid, "COM-02", "completada_a_mano", "ahora sí hecho").status_code == 200


def test_cualquier_usuario_del_equipo_puede_deshacer_lo_de_otro():
    pid, uno = _mundo()
    otro = _equipo()
    _decidir(uno, pid, "COM-02", "pospuesta")
    r = _deshacer(otro, pid, "COM-02", "pospuesta")
    assert r.status_code == 200
    with db.get_session() as s:
        d = s.exec(db.select(db.XsiiDecision).where(db.XsiiDecision.proyecto_id == pid)).one()
        assert not d.activa and d.deshecha_por_nombre.startswith("Equipo ") and d.quien_nombre != d.deshecha_por_nombre


def test_tipo_desconocido_o_tarea_inexistente():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "COM-02", "inventada", "motivo largo").status_code == 400
    assert _deshacer(eq, pid, "COM-02", "inventada").status_code == 400
    assert _decidir(eq, pid, "ZZZ-99", "pospuesta").status_code == 404
    assert eq.get(f"{BASE}/p/{pid}/tarea/ZZZ-99").status_code == 404
    assert _decidir(eq, pid, "com-02", "pospuesta").status_code == 200      # el código se normaliza


def test_dos_decisiones_a_la_vez_una_sola_gana():
    import threading
    pid, eq = _mundo()
    codigos, barrera = [], threading.Barrier(2)

    def hacer():
        c = TestClient(main.app, follow_redirects=False)
        c.cookies = eq.cookies
        barrera.wait()
        codigos.append(_decidir(c, pid, "COM-02", "pospuesta").status_code)

    hilos = [threading.Thread(target=hacer) for _ in range(2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sorted(codigos) == [200, 409]


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


# ---------------------------------------------------------------- insumos

def test_pedir_y_recibir_un_insumo_con_su_tarjeta_de_la_mesa():
    pid, eq = _mundo()
    tid, codigo = _tarjeta(pid, "Planilla del padrón")
    r = _insumo(eq, pid, "planilla_padron", estado="pedido", tarjeta=codigo, nota="se la pedimos a Marta")
    assert r.status_code == 200 and r.json()["ok"]
    i = r.json()["insumo"]
    assert set(i) == {"clave", "nombre", "descripcion", "tipo", "formato", "estado", "sin_registrar", "dias", "nota", "quien",
                      "cuando", "tarjeta"}
    assert i["estado"] == "pedido" and i["dias"] == 0 and i["nota"] == "se la pedimos a Marta"
    assert i["tarjeta"] == {"id": tid, "codigo": codigo, "titulo": "Planilla del padrón", "estado": "abierta",
                            "url": f"/implementacion?p={pid}"}
    t = _tablero(eq, pid)
    por = {x["codigo"]: x for x in t["tareas"]}
    assert por["PAD-01"]["estado"] == "esperando" and "pedido hoy" in por["PAD-01"]["detalle"]
    assert codigo in por["PAD-01"]["detalle"]
    assert t["demorados"] == []                       # recién pedido: todavía no está demorado
    _envejecer(pid, "planilla_padron", 1)
    assert "pedido ayer" in {x["codigo"]: x for x in _tablero(eq, pid)["tareas"]}["PAD-01"]["detalle"]
    assert _tablero(eq, pid)["demorados"] == []
    _envejecer(pid, "planilla_padron", 3)
    assert "pedido hace 3 días" in {x["codigo"]: x for x in _tablero(eq, pid)["tareas"]}["PAD-01"]["detalle"]
    dem = _tablero(eq, pid)["demorados"]
    assert len(dem) == 1 and dem[0]["clave"] == "planilla_padron" and dem[0]["codigo"] == "PAD-01"
    assert dem[0]["tarjeta"] == {"codigo": codigo, "titulo": "Planilla del padrón"} and dem[0]["frena"] >= 2
    # recibido sin mandar otra tarjeta: conserva la anterior
    r = _insumo(eq, pid, "planilla_padron", estado="recibido")
    i = r.json()["insumo"]
    assert i["estado"] == "recibido" and i["dias"] is None and i["tarjeta"]["codigo"] == codigo
    t = _tablero(eq, pid)
    assert t["demorados"] == []
    assert {x["codigo"]: x for x in t["tareas"]}["PAD-01"]["estado"] == "lista"       # ya no espera
    assert [m["tipo"] for m in t["movimientos"]] == ["insumo_recibido", "insumo_pedido"]


def test_la_tarjeta_por_id_y_la_de_otro_proyecto():
    pid, eq = _mundo()
    otro = _proyecto()
    tid, codigo = _tarjeta(pid)
    _tarjeta(otro)
    tid_ajena, _ = _tarjeta(otro)
    tid_ajena, codigo_ajeno = _tarjeta(otro)          # PE0003: en `pid` no existe
    r = _insumo(eq, pid, "lista_seccionales", estado="pedido", tarjeta=tid)
    assert r.status_code == 200 and r.json()["insumo"]["tarjeta"]["codigo"] == codigo
    for ajena in (codigo_ajeno, tid_ajena, "PE9999", "xx", 99999999999):
        r = _insumo(eq, pid, "recibos_muestra", estado="pedido", tarjeta=ajena)
        assert r.status_code == 400 and r.json()["detail"] == "No encontré esa tarjeta en la Mesa de este proyecto.", ajena
    _envejecer(pid, "lista_seccionales")
    assert _tablero(eq, pid)["demorados"][0]["clave"] == "lista_seccionales"   # y lo ajeno no quedó registrado


def test_retirar_un_insumo_y_sus_rechazos():
    pid, eq = _mundo()
    assert eq.post(f"{BASE}/p/{pid}/insumo/planilla_padron/retirar").status_code == 409
    _insumo(eq, pid, "planilla_padron", estado="recibido")
    r = eq.post(f"{BASE}/p/{pid}/insumo/planilla_padron/retirar")
    assert r.status_code == 200 and r.json()["insumo"]["estado"] == "falta"
    assert {x["codigo"]: x for x in _tablero(eq, pid)["tareas"]}["PAD-01"]["estado"] == "esperando"
    assert eq.post(f"{BASE}/p/{pid}/insumo/inventado/retirar").status_code == 404
    assert _insumo(eq, pid, "inventado", estado="pedido").status_code == 404
    assert _insumo(eq, pid, "planilla_padron", estado="listo").status_code == 400
    assert _insumo(eq, pid, "planilla_padron", estado="pedido", nota="n" * 501).status_code == 400


def test_insumo_sin_registrar_con_datos_cargados_no_deja_esperando():
    pid, eq = _mundo()
    with db.get_session() as s:
        sid = db.impl_proyecto(s, pid).sindicato_id
        s.add(db.Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=True))
        s.commit()
    por = {x["codigo"]: x for x in _tablero(eq, pid)["tareas"]}
    est = por["EST-01"]
    assert est["estado"] == "en_curso" and est["falta_confirmar"]
    ins = est["insumos"][0]
    assert ins["clave"] == "lista_seccionales" and ins["estado"] == "falta" and ins["sin_registrar"] is True
    # una solo_confirmacion con control que pasa sin insumo registrado sigue esperando
    assert por["REC-01"]["estado"] == "esperando" and por["REC-01"]["insumos"][0]["sin_registrar"] is False
    # registrado, deja de ser «sin registrar»
    _insumo(eq, pid, "lista_seccionales", estado="recibido")
    ins = {x["codigo"]: x for x in _tablero(eq, pid)["tareas"]}["EST-01"]["insumos"][0]
    assert ins["estado"] == "recibido" and ins["sin_registrar"] is False


def test_el_historial_de_la_tarea_incluye_sus_insumos():
    pid, eq = _mundo()
    _decidir(eq, pid, "PAD-01", "pospuesta", "esperamos a Marta")
    _insumo(eq, pid, "planilla_padron", estado="pedido")
    _decidir(eq, pid, "COM-02", "pospuesta")
    hist = eq.get(f"{BASE}/p/{pid}/tarea/PAD-01").json()["historial"]
    assert [h["tipo"] for h in hist] == ["insumo_pedido", "decision"]
    assert set(hist[0]) == {"id", "codigo", "tipo", "texto", "cantidades", "quien", "cuando"}
    assert hist[1]["texto"] == "Pospuso Padrón recibido: esperamos a Marta"
    assert len(_tablero(eq, pid)["movimientos"]) == 3


def test_movimientos_con_filtro_y_limite():
    pid, eq = _mundo()
    for c in ("COM-02", "COM-03", "BAS-03", "BAS-05"):
        _decidir(eq, pid, c, "pospuesta")
    todos = eq.get(f"{BASE}/p/{pid}/movimientos").json()["movimientos"]
    assert [m["codigo"] for m in todos] == ["BAS-05", "BAS-03", "COM-03", "COM-02"]
    assert len(eq.get(f"{BASE}/p/{pid}/movimientos?limite=2").json()["movimientos"]) == 2
    assert len(eq.get(f"{BASE}/p/{pid}/movimientos?limite=0").json()["movimientos"]) == 1
    assert len(eq.get(f"{BASE}/p/{pid}/movimientos?limite=100000").json()["movimientos"]) == 4
    assert [m["codigo"] for m in eq.get(f"{BASE}/p/{pid}/movimientos?codigo=COM-03").json()["movimientos"]] == ["COM-03"]
    assert eq.get(f"{BASE}/p/{pid}/movimientos?codigo=NOEXISTE").json() == {"movimientos": []}
    assert eq.get(f"{BASE}/p/{pid}/movimientos?limite=abc").status_code == 400
    assert len(_tablero(eq, pid)["movimientos"]) == 4


def test_el_tablero_trae_solo_los_ultimos_ocho_movimientos():
    pid, eq = _mundo()
    for c in ("COM-02", "COM-03", "BAS-03", "BAS-05", "EST-01", "REC-01", "PAD-01", "BAS-02", "BAS-04"):
        _decidir(eq, pid, c, "pospuesta")
    assert len(_tablero(eq, pid)["movimientos"]) == 8


# ---------------------------------------------------------------- entradas hostiles

@pytest.mark.parametrize("cuerpo", ['[]', '"texto"', '123', 'null', 'true', '{', '', '\xff\xfe'])
def test_un_cuerpo_que_no_es_un_objeto_es_400(cuerpo):
    pid, eq = _mundo()
    for ruta in ("tarea/COM-02/decision", "tarea/COM-02/decision/deshacer", "insumo/planilla_padron"):
        r = eq.post(f"{BASE}/p/{pid}/{ruta}", content=cuerpo.encode("latin-1"),
                    headers={"content-type": "application/json"})
        assert r.status_code == 400, (ruta, cuerpo, r.status_code)


HOSTILES = [None, 5, True, [], {}, ["a"], {"a": 1}, "\x00", "x" * 100000, "'; DROP TABLE xsiidecision; --",
            "<script>alert(1)</script>", "😀" * 600, "\ud800"]


@pytest.mark.parametrize("valor", HOSTILES)
def test_valores_hostiles_nunca_dan_500(valor):
    pid, eq = _mundo()
    for cuerpo in ({"tipo": valor, "motivo": "motivo largo"}, {"tipo": "no_aplica", "motivo": valor},
                   {"tipo": "pospuesta", "motivo": valor}):
        try:
            r = eq.post(f"{BASE}/p/{pid}/tarea/COM-02/decision", json=cuerpo)
        except Exception as e:      # noqa: BLE001 - un valor que el cliente mismo no puede serializar
            assert isinstance(e, (UnicodeEncodeError, ValueError)), e
            continue
        assert r.status_code < 500, (cuerpo, r.status_code)
    for cuerpo in ({"estado": valor}, {"estado": "pedido", "nota": valor}, {"estado": "pedido", "tarjeta": valor}):
        try:
            r = eq.post(f"{BASE}/p/{pid}/insumo/planilla_padron", json=cuerpo)
        except Exception as e:      # noqa: BLE001
            assert isinstance(e, (UnicodeEncodeError, ValueError)), e
            continue
        assert r.status_code < 500, (cuerpo, r.status_code)
    try:
        r = eq.post(f"{BASE}/p/{pid}/tarea/COM-02/decision/deshacer",
                    json={"tipo": valor if isinstance(valor, str) else "pospuesta"})
    except (UnicodeEncodeError, ValueError):
        return
    assert r.status_code < 500


def test_motivo_de_texto_malo_se_rechaza_o_se_sanea_y_nunca_rompe():
    pid, eq = _mundo()
    assert _decidir(eq, pid, "COM-02", "no_aplica", "x" * 501).status_code == 400
    assert _decidir(eq, pid, "COM-02", "no_aplica", "\x00\x00\x00\x00\x00").status_code == 400     # queda vacío
    r = _decidir(eq, pid, "COM-02", "no_aplica", "  con\x00 NUL y espacios  ")
    assert r.status_code == 200 and r.json()["tarea"]["decisiones"][0]["motivo"] == "con NUL y espacios"
    r = _decidir(eq, pid, "COM-03", "no_aplica", {"a": 1})
    assert r.status_code == 400
    r = _insumo(eq, pid, "planilla_padron", estado="pedido", tarjeta=True)
    assert r.status_code == 400
    r = _insumo(eq, pid, "planilla_padron", estado="pedido", tarjeta=["PE0001"])
    assert r.status_code == 400


def test_codigos_de_tarea_e_insumo_raros_son_404():
    pid, eq = _mundo()
    for raro in ("%00", "..%2F..", "%27OR%271", "A" * 500, "bas_01"):
        assert eq.get(f"{BASE}/p/{pid}/tarea/{raro}").status_code in (404, 422), raro
        assert _insumo(eq, pid, raro, estado="pedido").status_code in (404, 422), raro


def test_tablero_y_ficha_traen_la_guia_clara():
    pid, eq = _mundo()
    tab = {x["codigo"]: x for x in _tablero(eq, pid)["tareas"]}
    for codigo, t in tab.items():
        assert t["para_que"] and isinstance(t["pasos"], list) and 2 <= len(t["pasos"]) <= 5, codigo
        for i in t["insumos"]:
            assert i["tipo"] in ("archivo", "dato") and i["formato"], codigo
    ficha = _tarea(eq, pid, "EST-01")
    assert ficha["para_que"] == tab["EST-01"]["para_que"] and ficha["pasos"] == tab["EST-01"]["pasos"]
    assert ficha["insumos"][0]["tipo"] == "archivo" and "seccional" in ficha["insumos"][0]["formato"].lower()
