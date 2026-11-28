"""QA independiente de servidor del bloque 5 de XSII (vuelta a la Mesa: hitos
enlazados a tareas y archivos de los insumos), `docs/xsii/API.md`.

Todo por HTTP real contra la app. Complementa `test_xsii_mesa.py` (el del
desarrollo) con ataques: aislamiento, lo que ve el sindicato, entradas hostiles,
concurrencia, archivos raros en las asistidas, coherencia del insumo y las
sugerencias contra cada hito de la semilla.

Correr con: python -m pytest test_xsii_bloque5_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import json
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import db
import implementacion as im
import main
from test_implementacion_api import _cliente_sindicato
from test_xsii_mesa import (BASE, CAB, CLAVE, EQ, FILA, SEMILLA, SIND, _de, _enlazar, _equipo, _fijado, _hito,
                            _hitos, _hito_mesa, _insumo_tablero, _mundo, _movs, _pedir, _propuesto, _proyecto,
                            _resolver, _seccionales, _sid, _subir, _tarjeta, _tiempos, _url)
from xsii.proyectos.colm3na import catalogo, hitos as hitos_mod

db.crear_tablas()


def _sin_500(r):
    assert r.status_code < 500, (r.status_code, r.text[:300])
    return r


def _clon(eq):
    """Otro cliente con la MISMA sesión (los 500 se ven como 500, no se relanzan)."""
    c = TestClient(main.app, raise_server_exceptions=False, follow_redirects=False)
    for ck in eq.cookies.jar:
        c.cookies.jar.set_cookie(ck)
    return c


def _nota_interna_con_archivo(pid, tid, nombre="interno.csv", datos=None):
    with db.get_session() as s:
        m = db.impl_responder(s, pid, tid, EQ, "nota solo del equipo", solo_equipo=True,
                              adjuntos=[(nombre, "text/csv", datos if datos is not None else (CAB + FILA).encode())])
        assert m is not None
        a = s.exec(select(db.ImplArchivo).where(db.ImplArchivo.tarjeta_id == tid,
                                               db.ImplArchivo.nombre == nombre)).one()
        return a.id, a.codigo


# =================================================================== aislamiento y lo que ve el sindicato

def test_el_sindicato_de_la_mesa_no_ve_nada_de_xsii_en_la_api_de_la_mesa():
    pid, eq = _mundo()
    tid, tcod = _tarjeta(pid)
    _pedir(eq, pid, tid)
    sc, _mail = _cliente_sindicato(pid)
    sub_id, sub_cod = _subir(pid, tid, "padron-sindicato.csv", actor=SIND)
    # el sindicato sube un archivo; el equipo lo fija y lo usa en la asistida
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": sub_id}).status_code == 200
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(sub_id)}).status_code == 200
    hid = _propuesto(eq, pid, "Hito secreto del equipo con XSII", ("BAS-06",))
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").status_code == 200
    # lo que el sindicato lee de la Mesa
    visto = {}
    for ruta in ("/resumen", "/tarjetas?vista=todas", f"/tarjetas/{tid}", "/plan", "/carpetas?sentido=entrada",
                 f"/archivos/{sub_id}/ficha"):
        r = sc.get(f"/api/implementacion/p/{pid}{ruta}")
        assert r.status_code in (200, 404), (ruta, r.status_code)
        visto[ruta] = r.text
    todo = "\n".join(visto.values())
    for prohibido in ("hito_enlazado", "hito_marcado", "XsiiHito", "insumo_archivo", "lista_seccionales",
                      "BAS-06", "Seccionales y Sede Central", "asistida", "xsii/"):
        assert prohibido not in todo, prohibido
    # el hito tildado SÍ lo ve (es del plan compartido), a nombre de una persona del equipo, nunca «XSII»
    plan = json.loads(visto["/plan"])
    assert "Hito secreto" in visto["/plan"] or plan


def test_lo_que_el_sindicato_lee_del_registro_de_descargas_de_xsii(monkeypatch):
    """La descarga desde XSII queda en el hilo de la tarjeta. Lo que el sindicato lee dice «bajó X desde
    XSII»: se comprueba que no sale nada más interno (ni usuarios de plataforma con su usuario, ni ids)."""
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    _pedir(eq, pid, tid)
    sc, _m = _cliente_sindicato(pid)
    aid, _ = _subir(pid, tid, "p.csv", actor=SIND)
    eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid})
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}).status_code == 200
    d = sc.get(f"/api/implementacion/p/{pid}/tarjetas/{tid}").json()
    bajas = [e for e in d["eventos"] if e["que"] == "bajar"]
    assert len(bajas) == 1 and bajas[0]["texto"] == "bajó p.csv para cargarlo en el sistema"
    assert set(bajas[0]) <= {"quien", "lado", "cuando", "que", "texto"}
    ficha = sc.get(f"/api/implementacion/p/{pid}/archivos/{aid}/ficha")
    assert ficha.status_code == 200
    assert "xsii" not in ficha.text.lower().replace("desde xsii", "")


def test_el_sindicato_no_ve_la_descarga_de_un_archivo_de_nota_interna():
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    _pedir(eq, pid, tid)
    sc, _m = _cliente_sindicato(pid)
    aid, _ = _nota_interna_con_archivo(pid, tid)
    # el equipo lo lista, lo fija y lo usa (es suyo)
    j = eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json()
    assert [a["id"] for a in j["archivos"]] == [aid]
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 200
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}).status_code == 200
    # pero el sindicato no sabe ni que existe: ni el archivo, ni el evento de la descarga
    d = sc.get(f"/api/implementacion/p/{pid}/tarjetas/{tid}")
    assert d.status_code == 200
    assert "interno.csv" not in d.text and "nota solo del equipo" not in d.text
    assert sc.get(f"/api/implementacion/p/{pid}/archivos/{aid}/ficha").status_code == 404
    assert sc.get(f"/api/implementacion/p/{pid}/archivos/{aid}").status_code == 404
    # y un archivo interno no cuenta como «nuevo del sindicato»
    assert _insumo_tablero(eq, pid)["archivos_nuevos"] == 0


def test_un_sindicato_de_otro_proyecto_no_toca_ninguna_ruta_nueva():
    pid, eq = _mundo()
    otro = _proyecto()
    sc, _m = _cliente_sindicato(otro)
    hid = _hito(pid, "hito")
    for met, ruta in (("get", f"p/{pid}/hitos"), ("post", f"p/{pid}/hitos/{hid}/marcar"),
                      ("post", f"p/{pid}/hitos/{hid}/enlace"), ("post", f"p/{pid}/hitos/sugerencias/aceptar"),
                      ("get", f"p/{pid}/insumo/{CLAVE}/archivos"), ("post", f"p/{pid}/insumo/{CLAVE}/archivo"),
                      ("post", f"p/{pid}/tarea/EST-01/asistida/ensayo")):
        r = getattr(sc, met)(f"{BASE}/{ruta}", **({"json": {"codigo": "BAS-01", "archivo_id": 1}} if met == "post" else {}))
        assert r.status_code == 403, (ruta, r.status_code)
    assert _de(eq, pid, hid)["tareas"] == []


def test_archivo_y_tarjeta_de_otro_proyecto_no_hacen_nada_en_ninguna_ruta():
    pid, eq = _mundo()
    ajeno = _proyecto()
    ajeno_tid, _ = _tarjeta(ajeno)
    ajeno_aid, _ = _subir(ajeno, ajeno_tid)
    tid, _ = _tarjeta(pid)
    # pedir el insumo enlazado a una tarjeta AJENA: 400, y no queda enlazado
    r = eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}", json={"estado": "pedido", "tarjeta": ajeno_tid})
    assert r.status_code == 400
    r = eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}", json={"estado": "pedido", "tarjeta": "PE9999"})
    assert r.status_code == 400
    _pedir(eq, pid, tid)
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": ajeno_aid}).status_code == 404
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(ajeno_aid)}).status_code == 404
    with db.get_session() as s:
        assert db.impl_descargas(s, ajeno, ajeno_aid) == [] and db.impl_descargas(s, pid, ajeno_aid) == []
    assert _movs(pid, "insumo_archivo") == []


# =================================================================== archivos y el insumo

def test_archivos_borrados_cerrada_y_fijado_que_se_borra_despues():
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    _pedir(eq, pid, tid)
    aid, _ = _subir(pid, tid)
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 200
    # la tarjeta se cierra: sigue listando y se puede fijar otro
    with db.get_session() as s:
        db.impl_responder(s, pid, tid, EQ, "listo", estado_nuevo="cerrada")
    j = eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json()
    assert j["tarjeta"]["estado"] == "cerrada" and [a["elegido"] for a in j["archivos"]] == [True]
    # el fijado se borra: ya no está en la lista, el insumo sigue «recibido» y la asistida no lo ofrece
    with db.get_session() as s:
        try:
            db.impl_borrar_archivo(s, pid, aid, SIND)
        except im.ErrorImpl:
            db.impl_borrar_archivo(s, pid, aid, EQ)
    assert eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json()["archivos"] == []
    assert eq.get(_url(pid, "")).json()["archivo_mesa"] is None
    r = eq.post(_url(pid, "carga"), data={"archivo_mesa": str(aid), "huella": "x"})
    assert r.status_code == 409
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 404
    assert _seccionales(_sid(pid)) == []


def test_insumo_sin_tarjeta_o_retirado_no_deja_un_archivo_colgado():
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    # pedido SIN tarjeta: listar da vacío y fijar 404
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}", json={"estado": "pedido"}).status_code == 200
    aid, _ = _subir(pid, tid)
    assert eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json() == {"tarjeta": None, "archivos": []}
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 404
    # con tarjeta, fijado, y después RETIRADO y vuelto a pedir: el archivo fijado no sobrevive
    _pedir(eq, pid, tid)
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 200
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/retirar").status_code == 200
    assert eq.get(_url(pid, "")).json()["archivo_mesa"] is None
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}).status_code == 404
    _pedir(eq, pid, tid)
    assert eq.get(_url(pid, "")).json()["archivo_mesa"] is None
    assert [a["elegido"] for a in eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json()["archivos"]] == [False]


def test_cambiar_la_tarjeta_del_insumo_no_deja_fijado_un_archivo_de_la_tarjeta_anterior():
    """DEFECTO: re-registrar el insumo con OTRA tarjeta heredaba el `archivo_id` del registro anterior, que es
    de la tarjeta vieja: la asistida seguía ofreciendo (y leyendo) un archivo que ya no es del insumo."""
    pid, eq = _mundo()
    t1, _ = _tarjeta(pid, "Primera")
    t2, _ = _tarjeta(pid, "Segunda")
    _pedir(eq, pid, t1)
    a1, _ = _subir(pid, t1, "viejo.csv")
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": a1}).status_code == 200
    _pedir(eq, pid, t2)                                           # el insumo pasa a la tarjeta 2
    assert eq.get(_url(pid, "")).json()["archivo_mesa"] is None
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(a1)}).status_code == 404
    j = eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").json()
    assert j["archivos"] == [] or not any(a["elegido"] for a in j["archivos"])
    # registrarlo de nuevo con la MISMA tarjeta conserva el fijado
    a2, _ = _subir(pid, t2, "nuevo.csv")
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": a2}).status_code == 200
    _pedir(eq, pid, t2)
    assert eq.get(_url(pid, "")).json()["archivo_mesa"]["id"] == a2


def test_archivos_nuevos_cuenta_lo_que_debe():
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    _pedir(eq, pid, tid)
    interno, _ = _nota_interna_con_archivo(pid, tid)
    dp, _ = _subir(pid, tid, "dp.csv", actor=SIND, datos_personales=True)          # con datos personales: cuenta
    ajeno_pid = _proyecto()
    ajeno_tid, _ = _tarjeta(ajeno_pid)
    otro, _ = _subir(ajeno_pid, ajeno_tid, actor=SIND)                              # otro proyecto: no cuenta
    otra_tarjeta, _ = _tarjeta(pid, "Otra")
    otro2, _ = _subir(pid, otra_tarjeta, actor=SIND)                                # otra tarjeta: no cuenta
    _tiempos(pid, CLAVE, "2026-11-20 10:00:00", {interno: "2026-11-21 10:00:00", dp: "2026-11-21 10:00:00",
                                                 otro2: "2026-11-21 10:00:00"})
    assert _insumo_tablero(eq, pid)["archivos_nuevos"] == 1
    assert otro


def test_el_nombre_ni_el_contenido_de_un_archivo_llegan_a_los_movimientos():
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    _pedir(eq, pid, tid)
    nombre = "NOMBRE-SECRETO-<script>alert(1)</script>.csv"
    aid, acod = _subir(pid, tid, nombre, datos=(CAB + "Seccional CONTENIDO-SECRETO;no;Santa Fe;Rosario;Córdoba;1;-32,9;-60,6;\n").encode())
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 200
    ens = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)})
    assert ens.status_code == 200
    assert eq.post(_url(pid, "carga"), data={"archivo_mesa": str(aid), "huella": ens.json()["huella"]}).status_code == 200
    for m in _movs(pid):
        blob = m.texto + json.dumps(m.cantidades) + m.clave_insumo + m.codigo
        assert "SECRETO" not in blob and "script" not in blob
    t = eq.get(f"{BASE}/p/{pid}/tablero").text
    assert "CONTENIDO-SECRETO" not in t and "NOMBRE-SECRETO" not in t


# =================================================================== archivo_mesa en las asistidas

def test_archivo_mesa_con_archivos_raros_vacio_binario_y_de_20mb():
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    _pedir(eq, pid, tid)
    for datos in (b"   \n", bytes(range(256)) * 50, b"\xff\xfe\x00\x00" * 100, b"a" * (20 * 1024 * 1024)):
        aid, _ = _subir(pid, tid, "raro.csv", datos=datos)
        assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 200
        r = _sin_500(_clon(eq).post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}))
        assert r.status_code in (200, 400, 413), (len(datos), r.status_code, r.text[:200])
        r = _sin_500(_clon(eq).post(_url(pid, "carga"), data={"archivo_mesa": str(aid), "huella": "no-es-la-huella"}))
        assert r.status_code in (400, 409), (len(datos), r.status_code)
    assert _seccionales(_sid(pid)) == []


def test_archivo_mesa_con_archivo_o_texto_en_el_mismo_pedido_y_en_la_asistida_de_recibos():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid)
    for extra in ({"files": {"archivo": ("a.csv", (CAB + FILA).encode(), "text/csv")}}, {"data": {"texto": CAB + FILA}}):
        d = {"archivo_mesa": str(aid)}
        d.update(extra.get("data", {}))
        r = _sin_500(eq.post(_url(pid, "ensayo"), data=d, files=extra.get("files")))
        assert r.status_code == 400
        r = _sin_500(eq.post(_url(pid, "carga"), data=d, files=extra.get("files")))
        assert r.status_code == 400
    # texto en blanco + archivo_mesa vale (no hay planilla)
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid), "texto": "   "}).status_code == 200
    # la asistida de recibos ignora/rechaza archivo_mesa sin 500
    for ruta in ("ensayo", "carga"):
        r = _sin_500(eq.post(_url(pid, ruta, "REC-04"), data={"archivo_mesa": str(aid)}))
        assert r.status_code in (400, 404, 409, 415, 422), (ruta, r.status_code)
    with db.get_session() as s:
        assert len(db.impl_descargas(s, pid, aid)) == 1                      # el de «texto en blanco»


def test_cada_uso_registra_una_descarga_y_una_carga_fallida_no_deja_registro_incoherente():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid)
    ens = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}).json()
    # carga con huella equivocada: falla, pero la descarga ya está dicha (una por intento)
    r = eq.post(_url(pid, "carga"), data={"archivo_mesa": str(aid), "huella": "equivocada"})
    assert r.status_code in (400, 409)
    with db.get_session() as s:
        assert len(db.impl_descargas(s, pid, aid)) == 2
        bajas = [e for e in s.exec(select(db.ImplEvento).where(db.ImplEvento.proyecto_id == pid)).all()
                 if e.accion == "bajar"]
        assert len(bajas) == 2                                                # una descarga, un evento
    assert _seccionales(_sid(pid)) == [] and _movs(pid, "asistida_carga") == []
    r = eq.post(_url(pid, "carga"), data={"archivo_mesa": str(aid), "huella": ens["huella"]})
    assert r.status_code == 200
    with db.get_session() as s:
        assert len(db.impl_descargas(s, pid, aid)) == 3
    assert len(_movs(pid, "asistida_carga")) == 1


def test_huella_entre_ensayo_y_carga_si_el_archivo_de_la_mesa_se_reemplaza_o_se_borra():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid)
    ens = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}).json()
    # se fija OTRO archivo con otro contenido: el id viejo ya no es el del insumo (404) y la huella no vale
    tid = db_tarjeta_del_insumo(pid)
    otro, _ = _subir(pid, tid, "otro.csv", datos=(CAB + "Seccional Otra;no;Salta;Salta;Balcarce;10;-24,7;-65,4;\n").encode())
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": otro}).status_code == 200
    assert eq.post(_url(pid, "carga"), data={"archivo_mesa": str(aid), "huella": ens["huella"]}).status_code == 404
    assert eq.post(_url(pid, "carga"), data={"archivo_mesa": str(otro), "huella": ens["huella"]}).status_code in (400, 409)
    assert _seccionales(_sid(pid)) == []
    # se borra el fijado entre el ensayo y la carga
    ens2 = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(otro)}).json()
    with db.get_session() as s:
        db.impl_borrar_archivo(s, pid, otro, EQ)
    assert eq.post(_url(pid, "carga"), data={"archivo_mesa": str(otro), "huella": ens2["huella"]}).status_code == 409
    assert _seccionales(_sid(pid)) == []


def db_tarjeta_del_insumo(pid):
    with db.get_session() as s:
        return db.xsii_insumos_activos(s, pid)[CLAVE].tarjeta_id


def test_el_ensayo_con_archivo_de_la_mesa_tampoco_escribe_nada():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid)
    antes = (len(_movs(pid)), len(_seccionales(_sid(pid))))
    assert eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(aid)}).status_code == 200
    assert (len(_movs(pid)), len(_seccionales(_sid(pid)))) == antes


def test_archivo_mesa_con_ids_hostiles_o_campos_repetidos():
    pid, eq = _mundo()
    aid, _ = _fijado(eq, pid)
    for malo in ("0", "-1", "٣", "1e3", " ", "NaN", "9" * 400, "1 2", "0x10", "1\n2", "+5"):
        r = _sin_500(eq.post(_url(pid, "ensayo"), data={"archivo_mesa": malo}))
        assert r.status_code in (400, 404, 200), (malo, r.status_code)
        if malo.strip() == "":
            assert r.status_code == 400 or r.status_code == 200
    r = eq.post(_url(pid, "ensayo"), json={"archivo_mesa": aid})
    assert r.status_code < 500


# =================================================================== hitos: entradas hostiles

CUERPOS_CODIGO = [None, 5, [], {}, "", "   ", "bas 01", "BAS-01 ; DROP", "\u0000", "BAS-01\u200b", "ＢＡＳ-01",
                  "x" * 100000, True, ["BAS-01"], {"a": 1}]


def test_enlazar_y_retirar_con_cuerpos_hostiles_no_dan_500():
    pid, eq = _mundo()
    hid = _hito(pid, "Un hito")
    for c in CUERPOS_CODIGO:
        for ruta in ("enlace", "enlace/retirar"):
            r = _sin_500(_clon(eq).post(f"{BASE}/p/{pid}/hitos/{hid}/{ruta}", json={"codigo": c}))
            assert r.status_code in (400, 409), (ruta, repr(c)[:30], r.status_code)
    for cuerpo in ("esto no es json", "[1,2]", "null", "5", "{", ""):
        r = _sin_500(_clon(eq).post(f"{BASE}/p/{pid}/hitos/{hid}/enlace", content=cuerpo,
                                    headers={"content-type": "application/json"}))
        assert r.status_code == 400, repr(cuerpo)
    r = _sin_500(_clon(eq).post(f"{BASE}/p/{pid}/hitos/{hid}/enlace", content=b"\xff\xfe\x00{",
                                headers={"content-type": "application/json"}))
    assert r.status_code == 400
    r = _sin_500(_clon(eq).post(f"{BASE}/p/{pid}/hitos/{hid}/enlace", content='{"codigo":"BAS-01"}'))
    assert r.status_code == 400                                              # sin content-type json
    assert _de(eq, pid, hid)["tareas"] == [] and _movs(pid, "hito_enlazado") == []


def test_codigos_de_tarea_con_otras_mayusculas_y_espacios_valen_o_se_rechazan_sin_duplicar():
    pid, eq = _mundo()
    hid = _hito(pid, "Un hito")
    assert _enlazar(eq, pid, hid, "  bas-01  ").status_code == 200
    assert _enlazar(eq, pid, hid, "BAS-01").status_code == 200
    assert _enlazar(eq, pid, hid, "Bas-01").status_code == 200
    assert [t["codigo"] for t in _de(eq, pid, hid)["tareas"]] == ["BAS-01"]
    assert len(_movs(pid, "hito_enlazado")) == 1
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": " bas-01"}).status_code == 200
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": "BAS-01"}).status_code == 409
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": "REC-01"}).status_code == 409


def test_ids_de_hito_hostiles_en_la_ruta():
    pid, eq = _mundo()
    for h in ("abc", "-1", "0", "1.5", "99999999999999999999", "%00", "1;2", "٣"):
        for met, ruta, kw in (("post", f"hitos/{h}/marcar", {}), ("post", f"hitos/{h}/enlace", {"json": {"codigo": "BAS-01"}}),
                              ("post", f"hitos/{h}/enlace/retirar", {"json": {"codigo": "BAS-01"}})):
            r = _sin_500(_clon(eq).post(f"{BASE}/p/{pid}/{ruta}", **kw))
            assert r.status_code in (404, 422, 400), (ruta, r.status_code)


def test_aceptar_con_listas_gigantes_duplicadas_o_raras():
    pid, eq = _mundo()
    a = _hito(pid, "Padrón y listas cargados y conciliados")
    r = eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": [a] * 1000})
    assert r.status_code == 200 and r.json()["enlazados"] == 2
    r = _sin_500(eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": [a] * 1001}))
    assert r.status_code == 400
    r = _sin_500(eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": list(range(1, 1000000))}))
    assert r.status_code == 400
    for malo in ([None], [[1]], [{"a": 1}], [1.5], [-1], [0], ["1"], {"1": 1}, 7, "todos"):
        r = _sin_500(eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": malo}))
        assert r.status_code in (400, 404), (malo, r.status_code)
    assert eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": []}).status_code == 200
    for c in ("esto no es json", "[1]", "null"):
        r = _sin_500(eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", content=c,
                             headers={"content-type": "application/json"}))
        assert r.status_code == 400, c


def test_enlazar_dos_veces_desenlazar_lo_no_enlazado_y_hito_ya_hecho():
    pid, eq = _mundo()
    hid = _hito(pid, "Algo")
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": "BAS-01"}).status_code == 409
    assert _movs(pid, "hito_desenlazado") == []
    with db.get_session() as s:
        db.impl_tildar_hito(s, pid, hid, SIND)
    assert _enlazar(eq, pid, hid, "BAS-01").status_code == 200                # enlazar a uno ya hecho: vale
    assert _de(eq, pid, hid)["propuesto"] is False


def test_marcar_hito_no_propuesto_sin_enlaces_o_con_todas_no_aplica_es_409_sin_efecto():
    pid, eq = _mundo()
    sin = _hito(pid, "Sin enlaces")
    nop = _hito(pid, "Todas no aplican")
    parcial = _hito(pid, "Una sola pendiente")
    _enlazar(eq, pid, nop, "BAS-06")
    _enlazar(eq, pid, parcial, "BAS-06")
    assert eq.post(f"{BASE}/p/{pid}/tarea/BAS-06/decision", json={"tipo": "no_aplica", "motivo": "no corresponde acá"}).status_code == 200
    for h in (sin, nop, parcial):
        assert eq.post(f"{BASE}/p/{pid}/hitos/{h}/marcar").status_code == 409
        assert _hito_mesa(h) == (False, "")
    assert _movs(pid, "hito_marcado") == []
    with db.get_session() as s:
        evs = [e for e in s.exec(select(db.ImplEvento).where(db.ImplEvento.proyecto_id == pid)).all() if e.accion == "hito"]
        assert evs == []


def test_hito_borrado_o_editado_en_la_mesa_con_enlaces_activos():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid, "Texto original", ("BAS-06",))
    otro = _hito(pid, "El que sobrevive")
    _enlazar(eq, pid, otro, "BAS-06")
    # editado: el propuesto sigue y muestra el texto nuevo
    with db.get_session() as s:
        db.impl_editar_hito(s, pid, hid, EQ, texto="Texto editado")
    assert _de(eq, pid, hid)["texto"] == "Texto editado" and _de(eq, pid, hid)["propuesto"] is True
    # borrado: el enlace queda huérfano pero nada se rompe, no se lista y no se puede marcar
    with db.get_session() as s:
        assert db.impl_borrar_hito(s, pid, hid, EQ)
    j = _hitos(eq, pid)
    ids = [h["id"] for f in j["fases"] for h in f["hitos"]]
    assert hid not in ids and otro in ids and j["resumen"]["total"] == 1 and j["resumen"]["propuestos"] == 1
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").status_code == 404
    assert _enlazar(eq, pid, hid, "BAS-01").status_code == 404
    assert eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar", json={"hitos": [hid]}).status_code == 404
    assert eq.get(f"{BASE}/p/{pid}/tarea/BAS-06").json()["tarea"]["hitos"][0]["id"] == otro
    assert eq.get(f"{BASE}/p/{pid}/tablero").status_code == 200
    # aceptar todas con un huérfano en la tabla
    assert eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar").status_code == 200
    # el hito de un proyecto borrado entero no deja nada que rompa a otro proyecto
    otro_pid = _proyecto()
    assert _hitos(_equipo(), otro_pid)["resumen"]["total"] >= 0


def test_proyecto_sin_hitos_y_hito_desmarcado_en_la_mesa_vuelve_a_proponerse():
    pid, eq = _mundo()
    with db.get_session() as s:
        for h in s.exec(select(db.ImplHito).where(db.ImplHito.proyecto_id == pid)).all():
            s.delete(h)
        s.commit()
    j = _hitos(eq, pid)
    assert j["resumen"] == {"total": 0, "hechos": 0, "enlazados": 0, "propuestos": 0, "sugerencias": 0}
    assert eq.get(f"{BASE}/p/{pid}/tablero").json()["hitos"] == {"propuestos": 0, "sugerencias": 0}
    assert eq.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar").json() == {"ok": True, "enlazados": 0}
    hid = _propuesto(eq, pid, "Se marca y se desmarca", ("BAS-06",))
    assert eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").status_code == 200
    with db.get_session() as s:                                  # una persona lo desmarca en la Mesa
        db.impl_tildar_hito(s, pid, hid, SIND, False)
    h = _de(eq, pid, hid)
    # se vuelve a proponer: es coherente con «las tareas están hechas y el hito no» (XSII nunca lo marca solo)
    assert h["hecho"] is False and h["propuesto"] is True
    assert _hito_mesa(hid) == (False, "")


def test_hito_sin_etapa_valida_no_rompe_la_lista():
    pid, eq = _mundo()
    hid = _hito(pid, "Colgado de una etapa que ya no existe")
    with db.get_session() as s:
        h = s.get(db.ImplHito, hid)
        h.etapa_id = 987654321
        s.add(h)
        s.commit()
    j = _sin_500(eq.get(f"{BASE}/p/{pid}/hitos")).json()
    assert j["resumen"]["total"] >= 1
    assert _sin_500(eq.get(f"{BASE}/p/{pid}/tablero")).status_code == 200


# =================================================================== concurrencia

def test_seis_marcados_simultaneos_del_mismo_hito_uno_gana():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid, "Carrera", ("BAS-06",))
    clientes = [_clon(eq) for _ in range(6)]
    res, barrera = [], threading.Barrier(6)

    def marcar(c):
        barrera.wait()
        res.append(c.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").status_code)
    hilos = [threading.Thread(target=marcar, args=(c,)) for c in clientes]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=90)
    assert sorted(res) == [200] + [409] * 5, res
    assert len(_movs(pid, "hito_marcado")) == 1
    with db.get_session() as s:
        evs = [e for e in s.exec(select(db.ImplEvento).where(db.ImplEvento.proyecto_id == pid)).all() if e.accion == "hito"]
        assert len(evs) == 1


def test_enlazar_y_marcar_a_la_vez_no_dejan_nada_incoherente():
    pid, eq = _mundo()
    hid = _propuesto(eq, pid, "Enlazar y marcar", ("BAS-06",))
    res, barrera = {}, threading.Barrier(3)
    c1, c2, c3 = _clon(eq), _clon(eq), _clon(eq)

    def hacer(clave, f):
        barrera.wait()
        res[clave] = f().status_code
    hilos = [threading.Thread(target=hacer, args=("marcar", lambda: c1.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar"))),
             threading.Thread(target=hacer, args=("enlazar", lambda: c2.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace", json={"codigo": "REC-01"}))),
             threading.Thread(target=hacer, args=("retirar", lambda: c3.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": "BAS-06"})))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=90)
    assert all(v < 500 for v in res.values()), res
    assert res["marcar"] in (200, 409)
    marcados = len(_movs(pid, "hito_marcado"))
    assert marcados == (1 if res["marcar"] == 200 else 0)
    assert _hito_mesa(hid)[0] == (res["marcar"] == 200)
    with db.get_session() as s:
        activos = s.exec(select(db.XsiiHito).where(db.XsiiHito.hito_id == hid, db.XsiiHito.activa == True)).all()   # noqa: E712
        codigos = [a.codigo for a in activos]
        assert len(codigos) == len(set(codigos))


def test_aceptar_todas_en_paralelo_no_duplica_enlaces():
    pid, eq = _mundo()
    for t in ("Padrón y listas cargados y conciliados", "Seccionales cargadas desde el archivo, ubicadas en el mapa",
              "Alta del sindicato con logo, colores; primer administrador"):
        _hito(pid, t)
    clientes = [_clon(eq) for _ in range(6)]
    res, barrera = [], threading.Barrier(6)

    def aceptar(c):
        barrera.wait()
        r = c.post(f"{BASE}/p/{pid}/hitos/sugerencias/aceptar")
        res.append((r.status_code, r.json().get("enlazados") if r.status_code == 200 else None))
    hilos = [threading.Thread(target=aceptar, args=(c,)) for c in clientes]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=90)
    assert all(c in (200, 409) for c, _ in res), res
    with db.get_session() as s:
        activos = s.exec(select(db.XsiiHito).where(db.XsiiHito.proyecto_id == pid, db.XsiiHito.activa == True)).all()   # noqa: E712
        pares = [(a.hito_id, a.codigo) for a in activos]
        assert len(pares) == len(set(pares)) and len(pares) == sum(n or 0 for c, n in res if c == 200)
    assert len(_movs(pid, "hito_enlazado")) == len(pares)


# =================================================================== sugerencias

def _semilla():
    return [h["texto"] for f in json.loads(SEMILLA.read_text(encoding="utf-8"))["fases"] for h in f["hitos"]]


def test_las_sugerencias_resisten_variantes_de_texto():
    base = "Padrón y listas cargados y conciliados contra los totales del sindicato."
    esperado = ["PAD-02", "PAD-05"]
    for v in (base, base.upper(), base.lower(), base.replace("ó", "o"), "  " + base.replace(" ", "   ") + "  ",
              base.replace(" ", " "), "\n".join(base.split(" ")), "PADRÓN Y LISTAS CARGADOS"):
        assert hitos_mod.sugeridas_para(v) == esperado, repr(v)
    # NFD y NFC valen lo mismo
    import unicodedata
    assert hitos_mod.sugeridas_para(unicodedata.normalize("NFD", base)) == esperado
    for no in ("Padrón cargado", "Listas del padrón", "padron y listas", "", "   ", "Seccionales", "Alta del sindicato"):
        assert hitos_mod.sugeridas_para(no) == [], no
    # hostil: texto enorme y con caracteres raros no revienta ni es lento
    assert hitos_mod.sugeridas_para("x" * 1000000) == []
    assert hitos_mod.sugeridas_para("\u0000\u202e" * 1000) == []


def test_cada_sugerencia_sobre_la_semilla_tiene_sentido_y_no_hay_falsos_positivos():
    """Revisión hito por hito: exactamente estos 10 hitos reciben enlaces y a estas tareas; ningún otro."""
    esperado = {
        "alta del sindicato con logo": ["BAS-01", "BAS-02", "BAS-03", "BAS-04"],
        "seccionales cargadas desde el archivo": ["EST-01", "EST-02", "EST-03", "EST-04"],
        "padron y listas cargados": ["PAD-02", "PAD-05"],
        "catalogo de conceptos y reglas": ["REC-04", "REC-05"],
        "escalas con vigencia": ["REC-08"],
        "al menos 20 recibos reales": ["REC-07"],
        "primeros dos o tres tramites": ["TRA-01", "TRA-02"],
        "operadores capacitados": ["CIE-03"],
        "padron recibido y revisado": ["PAD-01"],
        "de 30 a 60 recibos de muestra": ["REC-01"],
    }
    asignados = {}
    for t in _semilla():
        s = hitos_mod.sugeridas_para(t)
        if s:
            n = hitos_mod.normalizar(t)
            clave = next(k for k in esperado if n.startswith(k) or k in n)
            asignados[clave] = s
    assert asignados == esperado
    # cada tarea sugerida existe y aplica a un hito de la fase correcta (nada de «Piloto» ni «Implementación total»)
    fases = {h["texto"]: f.get("nombre") or f.get("etapa") for f in json.loads(SEMILLA.read_text(encoding="utf-8"))["fases"]
             for h in f["hitos"]}
    for t in _semilla():
        if hitos_mod.sugeridas_para(t):
            assert fases[t] in ("Relevar", "Configurar"), (t, fases[t])
    # una tarea sugerida nunca es «manual solo confirmación» de otra cosa distinta (BAS-05/06 no se sugieren a nadie)
    todas = {c for t in _semilla() for c in hitos_mod.sugeridas_para(t)}
    assert not todas & {"BAS-05", "BAS-06", "COM-01", "COM-02", "COM-03", "COM-04", "COM-05", "COM-06", "CIE-01", "CIE-02"}
    assert todas <= {t.codigo for t in catalogo.TAREAS}


def test_el_json_de_sugerencias_mal_formado_no_tumba_nada(monkeypatch, tmp_path):
    malo = tmp_path / "s.json"
    for contenido in ("no es json", "{}", "[1, null, 'x']", '[{"texto_contiene": "a", "tareas": ["BAS-01"]}]',
                      '[{"texto_contiene": [""], "tareas": ["BAS-01"]}]', '[{"texto_contiene": ["a"], "tareas": [5]}]',
                      '[{"texto_contiene": ["a"], "tareas": ["NOEXISTE"]}]', ""):
        malo.write_text(contenido, encoding="utf-8")
        monkeypatch.setattr(hitos_mod, "ARCHIVO_SUGERIDOS", malo)
        monkeypatch.setattr(hitos_mod, "_cache", {})
        r = hitos_mod.sugeridas_para("a")
        assert isinstance(r, list) and "NOEXISTE" not in r
    monkeypatch.setattr(hitos_mod, "ARCHIVO_SUGERIDOS", tmp_path / "no-existe.json")
    monkeypatch.setattr(hitos_mod, "_cache", {})
    assert hitos_mod.sugeridas_para("lo que sea") == []


# =================================================================== «Preguntame»

def test_ver_hitos_no_entrega_texto_libre_ni_nombres_de_archivo_y_la_validacion_acepta_solo_codigos_reales():
    from xsii.proyectos.colm3na import herramientas as herr, vista
    pid, eq = _mundo()
    secreto = "SECRETO-DEL-HITO-ñandú"
    hid = _propuesto(eq, pid, secreto, ("BAS-06",))
    tid, _ = _tarjeta(pid, "TITULO-SECRETO-TARJETA")
    _pedir(eq, pid, tid)
    aid, _ = _subir(pid, tid, "ARCHIVO-SECRETO.csv")
    eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid})
    with db.get_session() as s:
        ctx = vista.Contexto(s, pid)
        inst = herr.Instantanea.armar(s, ctx)
    esquema, funcion = herr.herramientas(inst)["ver_hitos"]
    salida = json.dumps(funcion(), ensure_ascii=False)
    assert secreto not in salida and "ARCHIVO-SECRETO" not in salida and "TITULO-SECRETO" not in salida
    hcod = _de(eq, pid, hid)["codigo"]
    assert hcod in salida
    # la validación: un código de hito que salió de la herramienta pasa; uno inventado, no (aunque su
    # número aparezca en otro lado de lo que devolvió la herramienta)
    from xsii import asistente as asis
    visto = json.dumps(funcion(), ensure_ascii=False)
    ok = asis.validar(f"El hito {hcod} está propuesto.", visto=visto, codigos_validos=herr.CODIGOS)
    assert ok["ok"], ok
    visto = visto + ' "total": 7, "tareas": 12'     # el número suelto sale de las herramientas...
    inventado = "HI0007"                             # ...pero ESE hito no existe: antes pasaba como «el número 7»
    assert inventado not in visto and hcod != inventado
    for texto in (f"El hito {inventado} está propuesto.", f"el hito {inventado.lower()} ya está", f"{hcod} y {inventado}"):
        assert not asis.validar(texto, visto=visto, codigos_validos=herr.CODIGOS)["ok"], texto
    # un código de la Mesa que no es de hitos (tarjeta, archivo) tampoco pasa si no salió de las herramientas
    for texto in ("Mirá la tarjeta PE0042.", "Está en AR000123."):
        assert not asis.validar(texto, visto=visto, codigos_validos=herr.CODIGOS)["ok"], texto
    assert asis.validar("Mirá la tarjeta PE0042.", visto=visto + " PE0042", codigos_validos=herr.CODIGOS)["ok"]


# =================================================================== la migración y las tablas

def test_la_migracion_corre_dos_veces_y_tiene_downgrade_coherente():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    ruta = next(Path(__file__).parent.glob("migrations/versions/*_xsii_hitos.py"))
    spec = importlib.util.spec_from_file_location("mig_xsii_hitos_qa", ruta)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from sqlalchemy import inspect
    with db.engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()
        cols = {c["name"] for c in inspect(conn).get_columns("xsiihito")}
        assert {"id", "proyecto_id", "hito_id", "codigo", "quien_id", "quien_nombre", "cuando", "activa",
                "retirado_por_id", "retirado_por_nombre", "retirado_cuando"} <= cols
        idx = {i["name"] for i in inspect(conn).get_indexes("xsiihito")}
        assert "uq_xsiihito_activo" in idx
    if hasattr(mig, "downgrade"):
        with db.engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mig.downgrade()
                mig.downgrade()                 # idempotente
                mig.upgrade()
            assert "xsiihito" in inspect(conn).get_table_names()


def test_la_tabla_esta_fuera_del_clonado_y_del_borrado_de_un_sindicato():
    import re
    from pathlib import Path
    assert "xsiihito" in db.XSII_TABLAS
    clon = Path("clonar_demo_a_pruebas.py").read_text(encoding="utf-8")
    assert "XSII_TABLAS" in clon or "xsii" in clon.lower()
    # borrar un sindicato no toca el registro del proyecto XSII
    pid, eq = _mundo()
    hid = _hito(pid, "h")
    _enlazar(eq, pid, hid, "BAS-01")
    with db.get_session() as s:
        n = len(s.exec(select(db.XsiiHito).where(db.XsiiHito.proyecto_id == pid)).all())
    assert n == 1
    fuente = Path("db.py").read_text(encoding="utf-8")
    assert re.search(r"XSII_TABLAS", fuente)


# =================================================================== archivos que no son planillas

PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


def test_un_pdf_no_se_lee_como_planilla_ni_de_la_mesa_ni_subido_directo():
    pid, eq = _mundo()
    tid, _ = _tarjeta(pid)
    _pedir(eq, pid, tid)
    aid, _ = _subir(pid, tid, "informe.pdf", datos=PDF)
    assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": aid}).status_code == 200
    for ruta in ("ensayo", "carga"):
        r = eq.post(_url(pid, ruta, "EST-01"), data={"archivo_mesa": str(aid), "huella": "x"})
        assert r.status_code == 400 and "no es una planilla" in r.json()["detail"], (ruta, r.text)
    # sin extensión conocida pero con la firma de un PDF o un ZIP: también
    for datos in (PDF, b"PK\x03\x04resto", b"\x89PNG\r\n", b"\xff\xd8\xff\xe0jfif", b"GIF89a"):
        b, _ = _subir(pid, tid, "planilla.csv", datos=datos)
        assert eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": b}).status_code == 200
        r = eq.post(_url(pid, "ensayo"), data={"archivo_mesa": str(b)})
        assert r.status_code == 400 and "no es una planilla" in r.json()["detail"], datos
        r = eq.post(_url(pid, "ensayo"), files={"archivo": ("x.csv", datos, "text/csv")})
        assert r.status_code == 400 and "no es una planilla" in r.json()["detail"], datos
    r = eq.post(_url(pid, "ensayo", "PAD-02"), files={"archivo": ("x.pdf", PDF, "application/pdf")})
    assert r.status_code == 400 and "no es una planilla" in r.json()["detail"]
    # un CSV que empieza con letras parecidas a una firma sigue valiendo
    ok = (CAB.replace("nombre", "BMW nombre", 1) + FILA).encode()
    assert eq.post(_url(pid, "ensayo"), files={"archivo": ("x.csv", ok, "text/csv")}).status_code == 200
    assert _seccionales(_sid(pid)) == []


def test_los_mensajes_de_hitos_dicen_asociar_y_no_enlazar():
    pid, eq = _mundo()
    hid = _hito(pid, "Un hito")
    textos = [eq.post(f"{BASE}/p/{pid}/hitos/{hid}/enlace/retirar", json={"codigo": "BAS-01"}).json()["detail"],
              eq.post(f"{BASE}/p/{pid}/hitos/{hid}/marcar").json()["detail"],
              eq.get(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivos").text,
              eq.post(f"{BASE}/p/{pid}/insumo/{CLAVE}/archivo", json={"archivo_id": 1}).json()["detail"]]
    _enlazar(eq, pid, hid, "BAS-01")
    textos.append(_de(eq, pid, hid)["porque"])
    textos += [m.texto for m in _movs(pid)]
    for t in textos:
        assert "nlaz" not in t, t
