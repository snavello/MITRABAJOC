"""Mesa de implementación, bloques 3 y 4: la API de la mesa por HTTP, los dos
lados (equipo y sindicato), según docs/implementacion/API.md.

Cubre: una tarjeta de cada tipo, responder + estado en un acto, la nota interna
que NO sale en ninguna respuesta del sindicato (fail-closed sobre TODAS las
rutas GET), archivos con datos personales, borrar con constancia, aprobaciones,
aislamiento entre proyectos, plan operativo, CSV, ZIP, semilla y avisos por mail.

Correr con: python -m pytest test_implementacion_api.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import io
import json
import re
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import auth
import correo
import db
import entorno
import implementacion as im
import main

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
DEFINITIVA = "definitiva-2026"
NOTA = "NOTA-INTERNA-ULTRA-SECRETA-7731"


@pytest.fixture(autouse=True)
def _sin_freno():
    main._intentos_impl.clear()
    yield
    main._intentos_impl.clear()


def _u(prefijo="x"):
    return f"{prefijo}{uuid.uuid4().hex[:8]}"


def _proyecto(nombre=None):
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, nombre or _u("Proy "), EQ).id


def _cliente_sindicato(pid, nombre="Carla Sindicato"):
    mail = f"{_u()}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, nombre, mail, "transitoria1", EQ)
        db.impl_usuario_cambiar_clave(s, u.id, "transitoria1", DEFINITIVA)
    c = TestClient(main.app, follow_redirects=False)
    r = c.post("/implementacion/ingresar", data={"mail": mail, "clave": DEFINITIVA})
    assert r.headers["location"] == "/implementacion", r.headers
    return c, mail


def _cliente_equipo(email=""):
    usuario = _u("eq")
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario, email=email,
                                 clave_hash=auth.hashear_clave("x" * 12),
                                 debe_cambiar_clave=False, debe_completar_datos=False)
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    return c


def _mundo():
    """(pid, equipo, sindicato)"""
    pid = _proyecto()
    return pid, _cliente_equipo(), _cliente_sindicato(pid)[0]


def _api(pid, ruta=""):
    return f"/api/implementacion/p/{pid}/{ruta}".rstrip("/")


def _crear(c, pid, tipo="pedido", titulo="Un título", texto="Un texto", archivos=None, **extra):
    datos = {"tipo": tipo, "titulo": titulo, "texto": texto, **extra}
    r = c.post(_api(pid, "tarjetas"), data=datos, files=archivos or None)
    assert r.status_code == 200, r.text
    return r.json()["tarjeta"]


def _archivo(nombre="informe.pdf", datos=b"%PDF-1.4 contenido", mime="application/pdf"):
    return ("archivos", (nombre, datos, mime))


def _responder(c, pid, tid, **datos):
    return c.post(_api(pid, f"tarjetas/{tid}/responder"), data=datos)


def _detalle(c, pid, tid):
    r = c.get(_api(pid, f"tarjetas/{tid}"))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Tarjetas ----------
def test_cada_tipo_de_tarjeta_nace_como_corresponde():
    pid, eq, sin = _mundo()
    for tipo in im.ORDEN_TIPOS:
        t = _crear(sin, pid, tipo, titulo=f"Tarjeta {tipo}")
        assert t["tipo"] == tipo and t["tipo_nombre"] == im.TIPOS[tipo]["nombre"]
        assert t["color"] == im.TIPOS[tipo]["color"] and t["icono"] == im.TIPOS[tipo]["icono"]
        if tipo == "aviso":
            assert t["estado"] == "cerrada" and t["espera"] == "" and t["espera_texto"] == ""
        else:
            assert t["estado"] == "abierta" and t["espera"] == "equipo"
            assert t["espera_texto"] == "espera a Colm3na" and t["me_toca"] is False
        # el equipo la ve como suya si le toca
        visto = _detalle(eq, pid, t["id"])["tarjeta"]
        assert visto["me_toca"] is (tipo != "aviso")
    numeros = sorted(x["numero"] for x in eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"])
    assert numeros == [1, 2, 3, 4, 5, 6]


def test_el_equipo_crea_y_espera_al_sindicato():
    pid, eq, sin = _mundo()
    t = _crear(eq, pid, "consulta", titulo="¿Cuántas seccionales?")
    assert t["espera"] == "sindicato" and t["espera_texto"] == "espera al sindicato"
    assert sin.get(_api(pid, f"tarjetas/{t['id']}")).json()["tarjeta"]["me_toca"] is True
    assert [x["id"] for x in sin.get(_api(pid, "tarjetas")).json()["tarjetas"]] == [t["id"]]   # mis pendientes
    assert eq.get(_api(pid, "tarjetas")).json()["tarjetas"] == []


def test_una_tarjeta_invalida_da_400_con_codigo():
    pid, eq, sin = _mundo()
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "", "texto": ""})
    assert r.status_code == 400 and r.json()["codigo"] == "invalida" and "título" in r.json()["detail"].lower()
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "x", "texto": "y", "etapa_id": "abc"})
    assert r.status_code == 400
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "x", "texto": "y", "etapa_id": "999999"})
    assert r.status_code == 400 and r.json()["codigo"] == "etapa"


def test_etapa_y_hito_y_fecha_limite_en_la_tarjeta():
    pid, eq, sin = _mundo()
    with db.get_session() as s:
        et = db.impl_etapas(s, pid)[2]
        h = db.impl_agregar_hito(s, pid, et.id, "Taller de padrón", EQ)
        et_id, h_id, et_nombre = et.id, h.id, et.nombre
    t = _crear(sin, pid, hito_id=str(h_id), fecha_limite="2020-01-01")
    assert t["etapa_id"] == et_id and t["etapa_nombre"] == et_nombre and t["hito_id"] == h_id
    assert t["fecha_limite"] == "2020-01-01" and t["vencida"] is True
    resumen = eq.get(_api(pid, "resumen")).json()
    assert resumen["vencidas"] == 1 and resumen["con_fecha"] == 1 and resumen["esperan_otro"] == 0
    assert resumen["pendientes"] == 1
    plan = sin.get(_api(pid, "plan")).json()["etapas"]
    hito = [x for e in plan for x in e["hitos"] if x["id"] == h_id][0]
    assert hito["tarjetas"] == [{"numero": t["numero"], "titulo": t["titulo"], "estado": "abierta"}]


def test_responder_y_cambiar_el_estado_es_un_solo_acto():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    r = _responder(eq, pid, t["id"], texto="Listo, ya lo tenemos.", estado_nuevo="respondida")
    assert r.status_code == 200
    d = r.json()
    assert d["tarjeta"]["estado"] == "respondida" and d["tarjeta"]["espera"] == "sindicato"
    assert [m["texto"] for m in d["mensajes"]] == ["Un texto", "Listo, ya lo tenemos."]
    assert d["mensajes"][1]["mio"] is True and d["mensajes"][0]["mio"] is False
    resp = [e for e in d["eventos"] if e["que"] == "responder"]
    assert len(resp) == 1 and resp[0]["texto"] == "respondió y la pasó a Respondida"
    assert "Listo, ya lo tenemos" not in json.dumps(d["eventos"])
    # el sindicato cierra
    r2 = _responder(sin, pid, t["id"], estado_nuevo="cerrada")
    assert r2.json()["tarjeta"]["estado"] == "cerrada" and r2.json()["tarjeta"]["espera"] == ""
    acc = r2.json()["acciones"]
    assert acc["reabrir"] is True and acc["responder"] is False and acc["estados"] == []
    # reabrir
    r3 = _responder(sin, pid, t["id"], estado_nuevo="abierta", texto="Falta algo")
    assert r3.json()["tarjeta"]["estado"] == "abierta" and r3.json()["tarjeta"]["espera"] == "equipo"
    # una transición que no existe
    r4 = _responder(eq, pid, t["id"], estado_nuevo="abierta")
    assert r4.status_code in (400, 409)
    # vacío
    assert _responder(eq, pid, t["id"]).status_code == 400
    assert _responder(eq, pid, 999999, texto="x").status_code == 404


def test_las_acciones_las_calcula_el_servidor():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    a_sin = _detalle(sin, pid, t["id"])["acciones"]
    a_eq = _detalle(eq, pid, t["id"])["acciones"]
    assert a_sin["responder"] and a_eq["responder"]
    assert a_sin["solo_equipo"] is False and a_eq["solo_equipo"] is True
    assert {e["id"] for e in a_sin["estados"]} == {"en_curso", "respondida", "cerrada"}
    assert a_sin["aprobar"] is False and a_eq["aprobar"] is False and a_sin["subir"] and a_sin["reasignar"]
    aviso = _crear(eq, pid, "aviso", titulo="Hoy no hay mesa")
    assert not any(v for k, v in _detalle(sin, pid, aviso["id"])["acciones"].items() if k != "estados")


def test_aviso_no_se_responde_y_registra_quien_lo_leyo():
    pid, eq, sin = _mundo()
    a = _crear(eq, pid, "aviso", titulo="Cambio de horario")
    assert _responder(sin, pid, a["id"], texto="ok").status_code == 400
    assert sin.post(_api(pid, f"tarjetas/{a['id']}/leido")).json() == {"ok": True}
    assert sin.post(_api(pid, f"tarjetas/{a['id']}/leido")).json() == {"ok": True}      # una vez por persona
    lecturas = _detalle(eq, pid, a["id"])["lecturas"]
    assert [l["nombre"] for l in lecturas] == ["Carla Sindicato"] and lecturas[0]["lado"] == "sindicato"
    comun = _crear(sin, pid)
    assert sin.post(_api(pid, f"tarjetas/{comun['id']}/leido")).status_code == 400


def test_reasignar():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    r = eq.post(_api(pid, f"tarjetas/{t['id']}/reasignar"), json={"responsable": "Bruno", "responsable_lado": "equipo"})
    assert r.status_code == 200 and r.json()["tarjeta"]["responsable"] == "Bruno"
    assert "reasignó la tarjeta a Bruno" in [e["texto"] for e in r.json()["eventos"]]
    bad = eq.post(_api(pid, f"tarjetas/{t['id']}/reasignar"), json={"responsable": "X", "responsable_lado": "otro"})
    assert bad.status_code == 400


def test_busqueda_filtros_y_vistas():
    pid, eq, sin = _mundo()
    a = _crear(sin, pid, "pedido", titulo="Padrón de afiliados", texto="Mandamos el padrón")
    b = _crear(eq, pid, "consulta", titulo="Seccionales", texto="¿Cuántas hay?")
    ids = lambda c, **p: sorted(x["id"] for x in c.get(_api(pid, "tarjetas"), params=p).json()["tarjetas"])
    assert ids(sin, vista="todas") == sorted([a["id"], b["id"]])
    assert ids(sin) == [b["id"]] and ids(eq) == [a["id"]]
    assert ids(sin, vista="todas", q="padrón") == [a["id"]]
    assert ids(sin, vista="todas", q="hay") == [b["id"]]               # busca en el texto de los mensajes
    assert ids(sin, vista="todas", q=f"#{a['numero']}") == [a["id"]]
    assert ids(sin, vista="todas", tipo="consulta") == [b["id"]]
    assert ids(sin, vista="todas", estado="cerrada") == []
    assert ids(sin, vista="todas", q="%") == []                        # los comodines no comodinean
    assert sin.get(_api(pid, "tarjetas"), params={"vista": "rara"}).status_code == 400
    assert sin.get(_api(pid, "tarjetas"), params={"estado": "rara"}).status_code == 400
    assert sin.get(_api(pid, "tarjetas"), params={"tipo": "rara"}).status_code == 400


# ---------- Notas internas: fail-closed ----------
def _rutas_get():
    return sorted(r.path for r in main.app.routes
                  if getattr(r, "path", "").startswith("/api/implementacion/p/{pid}")
                  and "GET" in getattr(r, "methods", ()))


def test_la_nota_interna_no_aparece_en_ninguna_respuesta_del_sindicato():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, titulo="Consulta pública", texto="Texto del sindicato")
    # nota interna con un archivo adjunto, y una nota que también dispara una búsqueda
    r = eq.post(_api(pid, f"tarjetas/{t['id']}/responder"),
                data={"texto": NOTA, "solo_equipo": "1"},
                files=[_archivo("archivo-interno-9922.pdf", b"%PDF interno")])
    assert r.status_code == 200
    interno = [m for m in r.json()["mensajes"] if m["solo_equipo"]][0]
    arch_interno = [a for a in r.json()["archivos"] if a["nombre"] == "archivo-interno-9922.pdf"][0]
    assert arch_interno["mensaje_id"] == interno["id"]
    # y un archivo público, para comparar
    eq.post(_api(pid, f"tarjetas/{t['id']}/responder"), data={"texto": "Respuesta pública"},
            files=[_archivo("publico.pdf")])
    eq.post(_api(pid, f"tarjetas/{t['id']}/responder"), data={"texto": "otra nota", "solo_equipo": "1"})

    # La nota no cambió el estado ni a quién le toca.
    visto_eq = _detalle(eq, pid, t["id"])
    assert any(NOTA in m["texto"] for m in visto_eq["mensajes"])
    assert visto_eq["acciones"]["solo_equipo"] is True

    # El sindicato recorre TODAS las rutas GET del contrato.
    sustitutos = {"{pid}": str(pid), "{tid}": str(t["id"]), "{aid}": str(arch_interno["id"])}
    prohibidos = (NOTA, "archivo-interno-9922", "otra nota")
    recorridas = []
    for plantilla in _rutas_get():
        ruta = plantilla
        for k, v in sustitutos.items():
            ruta = ruta.replace(k, v)
        consultas = [{}]
        if ruta.endswith("/carpetas"):
            consultas = [{"sentido": "entrada"}, {"sentido": "salida"}]
        if ruta.endswith("/tarjetas"):
            consultas = [{"vista": "todas"}, {"vista": "pendientes"}, {"vista": "todas", "q": "SECRETA"},
                         {"vista": "todas", "q": "archivo-interno"}, {"vista": "todas", "q": "otra nota"}]
        for params in consultas:
            r = sin.get(ruta, params=params)
            assert r.status_code in (200, 403, 404), (ruta, params, r.status_code, r.text[:200])
            for malo in prohibidos:
                assert malo not in r.text, (ruta, params, malo)
            if params.get("q") in ("SECRETA", "archivo-interno", "otra nota"):
                assert r.json()["tarjetas"] == [], (params, r.text)       # ni siquiera "hay algo"
        recorridas.append(plantilla)
    assert set(recorridas) == set(_rutas_get())
    # El archivo de la nota interna no existe para el sindicato (ni bajarlo ni borrarlo).
    assert sin.get(_api(pid, f"archivos/{arch_interno['id']}")).status_code == 404
    assert sin.post(_api(pid, f"archivos/{arch_interno['id']}/borrar")).status_code == 404
    # El hilo del sindicato: sin notas, y con el conteo que ve.
    d = _detalle(sin, pid, t["id"])
    assert [m["texto"] for m in d["mensajes"]] == ["Texto del sindicato", "Respuesta pública"]
    assert all(m["solo_equipo"] is False for m in d["mensajes"])
    assert [a["nombre"] for a in d["archivos"]] == ["publico.pdf"]
    assert d["tarjeta"]["n_mensajes"] == 2 and d["tarjeta"]["n_archivos"] == 1
    assert d["acciones"]["solo_equipo"] is False
    # Y no puede escribir una nota interna.
    r = sin.post(_api(pid, f"tarjetas/{t['id']}/responder"), data={"texto": "x", "solo_equipo": "1"})
    assert r.status_code == 403 and r.json()["codigo"] == "sin_permiso"
    # El equipo, en cambio, sí ve todo.
    assert {a["nombre"] for a in visto_eq["archivos"]} >= {"archivo-interno-9922.pdf"}
    carpeta = eq.get(_api(pid, "carpetas"), params={"sentido": "salida"}).text
    assert "archivo-interno-9922" in carpeta


def test_una_nota_interna_no_cambia_el_estado_ni_a_quien_le_toca():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    antes = _detalle(sin, pid, t["id"])["tarjeta"]
    r = _responder(eq, pid, t["id"], texto="pensando", solo_equipo="1", estado_nuevo="cerrada")
    assert r.status_code == 400 and r.json()["codigo"] == "nota_interna"
    _responder(eq, pid, t["id"], texto="pensando", solo_equipo="1")
    despues = _detalle(sin, pid, t["id"])["tarjeta"]
    assert (despues["estado"], despues["espera"], despues["actualizada_en"], despues["n_mensajes"]) == \
        (antes["estado"], antes["espera"], antes["actualizada_en"], antes["n_mensajes"])


# ---------- Archivos ----------
def test_archivo_con_datos_personales_solo_lo_baja_el_equipo_y_quien_lo_subio():
    pid, eq, sin_a = _mundo()
    sin_b, _ = _cliente_sindicato(pid, "Dario Sindicato")
    t = _crear(sin_a, pid, "entrega", titulo="Padrón", datos_personales="1",
               archivos=[_archivo("padron.csv", b"cuil;nombre\n2011111111;Ana", "text/csv")])
    a = _detalle(sin_a, pid, t["id"])["archivos"][0]
    assert a["datos_personales"] is True and a["puede_bajar"] is True and a["puede_borrar"] is True
    # quien lo subió y el equipo lo bajan; el otro usuario del sindicato, no
    r = sin_a.get(_api(pid, f"archivos/{a['id']}"))
    assert r.status_code == 200 and r.content.startswith(b"cuil;nombre")
    assert eq.get(_api(pid, f"archivos/{a['id']}")).status_code == 200
    r = sin_b.get(_api(pid, f"archivos/{a['id']}"))
    assert r.status_code == 403 and r.json()["codigo"] == "sin_permiso"
    visto_b = _detalle(sin_b, pid, t["id"])["archivos"][0]
    assert visto_b["puede_bajar"] is False and visto_b["puede_borrar"] is False
    # cada descarga quedó registrada (la rechazada no)
    with db.get_session() as s:
        quienes = [(d.lado, d.nombre) for d in db.impl_descargas(s, pid, a["id"])]
    assert len(quienes) == 2 and {l for l, _ in quienes} == {"sindicato", "equipo"}
    # un archivo sin datos personales lo baja cualquiera del proyecto
    t2 = _crear(sin_a, pid, "entrega", titulo="Logo", archivos=[_archivo("logo.png", b"\x89PNG", "image/png")])
    a2 = _detalle(sin_a, pid, t2["id"])["archivos"][0]
    assert sin_b.get(_api(pid, f"archivos/{a2['id']}")).status_code == 200


def test_la_descarga_es_siempre_attachment_y_nunca_html_en_linea():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "entrega", archivos=[
        _archivo('mal"nombre;ñ.html', b"<script>alert(1)</script>", "text/html")])
    a = _detalle(sin, pid, t["id"])["archivos"][0]
    r = sin.get(_api(pid, f"archivos/{a['id']}"))
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;")
    assert 'filename="mal' in r.headers["content-disposition"] and "ñ" not in r.headers["content-disposition"] and "filename*=UTF-8''" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"].startswith("application/octet-stream")
    t2 = _crear(sin, pid, "entrega", archivos=[_archivo("dibujo.svg", b"<svg onload=x/>", "image/svg+xml")])
    a2 = _detalle(sin, pid, t2["id"])["archivos"][0]
    r2 = sin.get(_api(pid, f"archivos/{a2['id']}"))
    assert r2.headers["content-type"].startswith("application/octet-stream")
    assert r2.headers["content-disposition"].startswith("attachment;")


def test_el_tope_de_20mb_se_rechaza_sin_crear_la_tarjeta():
    pid, eq, sin = _mundo()
    grande = b"0" * (im.TOPE_ARCHIVO + 1)
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "entrega", "titulo": "Enorme", "texto": "x"},
                 files=[_archivo("enorme.bin", grande, "application/octet-stream")])
    assert r.status_code == 413 and r.json()["codigo"] == "archivo_grande"
    assert sin.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"] == []
    vacio = sin.post(_api(pid, "tarjetas"), data={"tipo": "entrega", "titulo": "Vacío", "texto": "x"},
                     files=[_archivo("vacio.bin", b"")])
    assert vacio.status_code == 400
    seis = [_archivo(f"a{i}.txt", b"x", "text/plain") for i in range(im_max() + 1)]
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "entrega", "titulo": "Muchos", "texto": "x"}, files=seis)
    assert r.status_code == 400 and r.json()["codigo"] == "archivos"


def im_max():
    return main.IMPL_MAX_ARCHIVOS


def test_el_campo_archivos_con_corchetes_tambien_vale():
    pid, eq, sin = _mundo()
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "entrega", "titulo": "Corchetes", "texto": "x"},
                 files=[("archivos[]", ("a.txt", b"hola", "text/plain"))])
    assert r.status_code == 200 and r.json()["tarjeta"]["n_archivos"] == 1


def test_borrar_un_archivo_deja_la_constancia():
    pid, eq, sin_a = _mundo()
    sin_b, _ = _cliente_sindicato(pid, "Dario Sindicato")
    t = _crear(sin_a, pid, "entrega", archivos=[_archivo("contrato.pdf", b"%PDF contrato")])
    a = _detalle(sin_a, pid, t["id"])["archivos"][0]
    # otro usuario del sindicato no lo borra
    r = sin_b.post(_api(pid, f"archivos/{a['id']}/borrar"))
    assert r.status_code == 403 and r.json()["codigo"] == "sin_permiso"
    assert sin_a.post(_api(pid, f"archivos/{a['id']}/borrar")).json() == {"ok": True}
    d = _detalle(eq, pid, t["id"])
    borrado = d["archivos"][0]
    assert borrado["borrado"] is True and borrado["nombre"] == "contrato.pdf" and borrado["tamano"] == len(b"%PDF contrato")
    assert borrado["subido_por"] == "Carla Sindicato" and borrado["borrado_por"] == "Carla Sindicato"
    assert borrado["puede_bajar"] is False and borrado["puede_borrar"] is False
    assert d["tarjeta"]["n_archivos"] == 0
    assert "borró contrato.pdf" in [e["texto"] for e in d["eventos"]]
    r = eq.get(_api(pid, f"archivos/{a['id']}"))
    assert r.status_code == 410 and r.json()["codigo"] == "borrado"
    assert eq.post(_api(pid, f"archivos/{a['id']}/borrar")).status_code == 410
    # sigue en la carpeta como constancia
    carpeta = eq.get(_api(pid, "carpetas"), params={"sentido": "entrada"}).json()["etapas"]
    arch = carpeta[0]["archivos"][0]
    assert arch["borrado"] is True and arch["nombre"] == "contrato.pdf" and arch["tarjeta_numero"] == t["numero"]
    # el equipo puede borrar lo del sindicato
    t2 = _crear(sin_a, pid, "entrega", archivos=[_archivo("otro.pdf")])
    a2 = _detalle(eq, pid, t2["id"])["archivos"][0]
    assert eq.post(_api(pid, f"archivos/{a2['id']}/borrar")).json() == {"ok": True}


def test_carpetas_entrada_y_salida_por_etapa():
    pid, eq, sin = _mundo()
    with db.get_session() as s:
        e = db.impl_etapas(s, pid)
        e1, e2 = e[0].id, e[1].id
    _crear(sin, pid, "entrega", titulo="Entrada 2", etapa_id=str(e2), archivos=[_archivo("e2.pdf")])
    _crear(sin, pid, "entrega", titulo="Entrada 1", etapa_id=str(e1), archivos=[_archivo("e1.pdf")])
    _crear(eq, pid, "entrega", titulo="Salida", archivos=[_archivo("salida.pdf")])
    ent = sin.get(_api(pid, "carpetas"), params={"sentido": "entrada"}).json()["etapas"]
    assert [g["etapa_id"] for g in ent] == [e1, e2]
    assert [g["archivos"][0]["nombre"] for g in ent] == ["e1.pdf", "e2.pdf"]
    sal = sin.get(_api(pid, "carpetas"), params={"sentido": "salida"}).json()["etapas"]
    assert sal[0]["etapa"] == "Sin etapa" and sal[0]["archivos"][0]["nombre"] == "salida.pdf"
    assert sin.get(_api(pid, "carpetas"), params={"sentido": "x"}).status_code == 400


# ---------- Aprobaciones ----------
def test_aprobacion_no_la_resuelve_quien_la_pidio_y_es_inmutable():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "aprobacion", titulo="Plan v1", texto="Aprobar el plan v1")
    # quien la pidió (sindicato) no la aprueba; le toca al equipo
    r = sin.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": True})
    assert r.status_code == 403 and r.json()["codigo"] == "sin_permiso"
    assert _detalle(sin, pid, t["id"])["acciones"]["aprobar"] is False
    assert _detalle(eq, pid, t["id"])["acciones"]["aprobar"] is True
    assert eq.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={}).status_code == 400
    r = eq.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": True, "texto": "Conforme"})
    assert r.status_code == 200
    d = r.json()
    assert d["tarjeta"]["estado"] == "aprobada" and d["tarjeta"]["espera"] == ""
    assert not any(v for k, v in d["acciones"].items() if k != "estados") and d["acciones"]["estados"] == []
    assert "aprobó" in [e["texto"] for e in d["eventos"]]
    # inmutable: ni otra resolución, ni respuesta, ni reasignación, ni archivos
    for rr in (eq.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": False}),
               sin.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": False}),
               _responder(eq, pid, t["id"], texto="cambio de idea"),
               eq.post(_api(pid, f"tarjetas/{t['id']}/reasignar"), json={"responsable": "X", "responsable_lado": "equipo"}),
               eq.post(_api(pid, f"tarjetas/{t['id']}/responder"), data={"texto": "x"}, files=[_archivo()])):
        assert rr.status_code in (403, 409), rr.text
    assert _detalle(eq, pid, t["id"])["tarjeta"]["estado"] == "aprobada"
    # el registro
    reg = sin.get(_api(pid, "aprobaciones")).json()["aprobaciones"]
    assert len(reg) == 1
    fila = reg[0]
    assert (fila["numero"], fila["estado"], fila["pedida_por"], fila["texto"]) == (t["numero"], "aprobada", "Carla Sindicato", "Conforme")
    assert fila["resuelta_por"].startswith("Equipo ") and fila["resuelta_en"] and fila["pedida_en"]


def test_aprobacion_pedida_por_el_equipo_la_rechaza_el_sindicato():
    pid, eq, sin = _mundo()
    t = _crear(eq, pid, "aprobacion", titulo="Aceptación", texto="¿Aceptan la configuración?")
    assert _detalle(sin, pid, t["id"])["acciones"]["aprobar"] is True
    r = sin.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": False, "texto": "Falta el logo"})
    assert r.json()["tarjeta"]["estado"] == "rechazada"
    pendiente = _crear(eq, pid, "aprobacion", titulo="Pendiente", texto="x")
    reg = sin.get(_api(pid, "aprobaciones")).json()["aprobaciones"]
    estados = {f["titulo"]: f["estado"] for f in reg}
    assert estados == {"Aceptación": "rechazada", "Pendiente": "abierta"}
    assert pendiente["estado"] == "abierta"
    # una tarjeta que no es aprobación
    comun = _crear(eq, pid)
    assert sin.post(_api(pid, f"tarjetas/{comun['id']}/aprobacion"), json={"aprobar": True}).status_code == 400


def test_registro_de_aprobaciones_en_csv():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "aprobacion", titulo="=HYPERLINK(\"x\")", texto="y")
    eq.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": True})
    r = sin.get(_api(pid, "aprobaciones.csv"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"
    texto = r.content.decode("utf-8")
    assert texto.startswith("﻿Número;Título;Estado;Pidió;Resolvió;Cuándo;Etapa")
    assert "'=HYPERLINK" in texto and "Aprobada" in texto and "Carla Sindicato" in texto


# ---------- Aislamiento entre proyectos ----------
def test_un_proyecto_no_ve_nada_del_otro_en_ninguna_ruta():
    pid1, eq, sin1 = _mundo()
    pid2 = _proyecto()
    sin2, _ = _cliente_sindicato(pid2, "Elena Otro")
    t2 = _crear(sin2, pid2, "aprobacion", titulo="Del otro", texto="reservado del otro",
                archivos=[_archivo("ajeno.pdf")])
    det2 = _detalle(eq, pid2, t2["id"])
    aid2 = det2["archivos"][0]["id"]
    with db.get_session() as s:
        et2 = db.impl_etapas(s, pid2)[0]
        h2 = db.impl_agregar_hito(s, pid2, et2.id, "Hito del otro", EQ)
        et2_id, h2_id = et2.id, h2.id
    t1 = _crear(sin1, pid1, titulo="Mío")

    # 1) el sindicato del proyecto 1 pidiendo el id del proyecto 2: 404 en TODAS las rutas
    casos = [
        ("GET", "resumen", {}), ("GET", "tarjetas", {}), ("GET", f"tarjetas/{t2['id']}", {}),
        ("POST", "tarjetas", {"data": {"tipo": "pedido", "titulo": "x", "texto": "y"}}),
        ("POST", f"tarjetas/{t2['id']}/responder", {"data": {"texto": "x"}}),
        ("POST", f"tarjetas/{t2['id']}/aprobacion", {"json": {"aprobar": True}}),
        ("POST", f"tarjetas/{t2['id']}/leido", {}),
        ("POST", f"tarjetas/{t2['id']}/reasignar", {"json": {"responsable": "x", "responsable_lado": "equipo"}}),
        ("GET", f"archivos/{aid2}", {}), ("POST", f"archivos/{aid2}/borrar", {}),
        ("GET", "carpetas", {}), ("GET", "aprobaciones", {}), ("GET", "aprobaciones.csv", {}),
        ("GET", "plan", {}), ("POST", "plan/hitos", {"json": {"etapa_id": et2_id, "texto": "x"}}),
        ("POST", f"plan/hitos/{h2_id}", {"json": {"hecho": True}}),
        ("POST", f"plan/etapas/{et2_id}", {"json": {"nombre": "x"}}), ("GET", "exportar.zip", {}),
    ]
    for metodo, ruta, kw in casos:
        r = sin1.request(metodo, _api(pid2, ruta), **kw)
        assert r.status_code == 404, (metodo, ruta, r.status_code)
        assert "reservado del otro" not in r.text and "ajeno.pdf" not in r.text

    # 2) ids del proyecto 2 usados dentro de la ruta del proyecto 1 (ni el equipo los cruza)
    for cliente in (sin1, eq):
        for metodo, ruta, kw in [
                ("GET", f"tarjetas/{t2['id']}", {}),
                ("POST", f"tarjetas/{t2['id']}/responder", {"data": {"texto": "x"}}),
                ("POST", f"tarjetas/{t2['id']}/aprobacion", {"json": {"aprobar": True}}),
                ("POST", f"tarjetas/{t2['id']}/leido", {}),
                ("POST", f"tarjetas/{t2['id']}/reasignar", {"json": {"responsable": "x", "responsable_lado": "equipo"}}),
                ("GET", f"archivos/{aid2}", {}), ("POST", f"archivos/{aid2}/borrar", {}),
                ("POST", f"plan/hitos/{h2_id}", {"json": {"hecho": True}}),
                ("POST", f"plan/etapas/{et2_id}", {"json": {"nombre": "x"}}),
                ("POST", "plan/hitos", {"json": {"etapa_id": et2_id, "texto": "x"}})]:
            r = cliente.request(metodo, _api(pid1, ruta), **kw)
            assert r.status_code in (403, 404), (metodo, ruta, r.status_code)
            if cliente is eq or "plan" not in ruta:
                assert r.status_code == 404, (metodo, ruta, r.status_code)
    # nada de lo del proyecto 1 trae algo del 2
    for ruta in ("tarjetas", "carpetas", "aprobaciones", "plan"):
        texto = sin1.get(_api(pid1, ruta), params={"vista": "todas"} if ruta == "tarjetas" else None).text
        assert "Del otro" not in texto and "Hito del otro" not in texto and "ajeno.pdf" not in texto
    # lo del 2 sigue intacto
    assert _detalle(eq, pid2, t2["id"])["tarjeta"]["estado"] == "abierta"
    assert len(_detalle(eq, pid2, t2["id"])["mensajes"]) == 1
    assert t1["numero"] == 1 and t2["numero"] == 1                     # correlativos por proyecto


def test_sin_sesion_es_401_y_en_demo_todo_404(monkeypatch):
    pid, eq, sin = _mundo()
    anonimo = TestClient(main.app, follow_redirects=False)
    for ruta in ("resumen", "tarjetas", "plan", "carpetas", "aprobaciones", "exportar.zip", "archivos/1"):
        assert anonimo.get(_api(pid, ruta)).status_code == 401, ruta
    assert anonimo.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "x", "texto": "y"}).status_code == 401
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    for c in (eq, sin):
        assert c.get(_api(pid, "resumen")).status_code == 404
        assert c.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "x", "texto": "y"}).status_code == 404
        assert c.get(f"/implementacion?p={pid}").status_code == 404


# ---------- Plan operativo ----------
def test_plan_tildar_los_dos_lados_y_editar_solo_el_equipo():
    pid, eq, sin = _mundo()
    etapas = eq.get(_api(pid, "plan")).json()["etapas"]
    assert len(etapas) == 6 and etapas[0]["nombre"] == "Preparar" and all(e["hitos"] == [] for e in etapas)
    e1, e2 = etapas[0]["id"], etapas[1]["id"]
    # solo el equipo suma hitos
    assert sin.post(_api(pid, "plan/hitos"), json={"etapa_id": e1, "texto": "Hito"}).status_code == 403
    for texto in ("Reunión", "Acta", "Plan v1"):
        r = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": e1, "texto": texto})
        assert r.status_code == 200
    assert eq.post(_api(pid, "plan/hitos"), json={"etapa_id": e1, "texto": "  "}).status_code == 400
    hitos = eq.get(_api(pid, "plan")).json()["etapas"][0]["hitos"]
    assert [h["texto"] for h in hitos] == ["Reunión", "Acta", "Plan v1"] and [h["orden"] for h in hitos] == [1, 2, 3]
    h1, h2, h3 = (h["id"] for h in hitos)
    # los dos lados tildan
    r = sin.post(_api(pid, f"plan/hitos/{h1}"), json={"hecho": True})
    assert r.status_code == 200
    mio = [h for h in r.json()["etapas"][0]["hitos"] if h["id"] == h1][0]
    assert mio["hecho"] is True and mio["hecho_por"] == "Carla Sindicato" and mio["hecho_en"]
    r = eq.post(_api(pid, f"plan/hitos/{h2}"), json={"hecho": True})
    assert r.json()["etapas"][0]["pct"] == 67
    assert eq.post(_api(pid, f"plan/hitos/{h2}"), json={"hecho": False}).json()["etapas"][0]["pct"] == 33
    resumen = sin.get(_api(pid, "resumen")).json()
    assert resumen["plan_pct"] == 33
    e1_res = [e for e in resumen["etapas"] if e["id"] == e1][0]
    assert (e1_res["total"], e1_res["hechos"], e1_res["pct"]) == (3, 1, 33) and e1_res["nombre"] == "Preparar"
    # el sindicato no edita (ni mezclado con tildar)
    for cuerpo in ({"texto": "otro"}, {"orden": 1}, {"borrar": True}, {"hecho": True, "texto": "otro"}):
        assert sin.post(_api(pid, f"plan/hitos/{h3}"), json=cuerpo).status_code == 403, cuerpo
    assert sin.post(_api(pid, f"plan/etapas/{e1}"), json={"nombre": "x"}).status_code == 403
    assert [h["texto"] for h in sin.get(_api(pid, "plan")).json()["etapas"][0]["hitos"]] == ["Reunión", "Acta", "Plan v1"]
    # el equipo edita, reordena, renombra y borra
    r = eq.post(_api(pid, f"plan/hitos/{h3}"), json={"texto": "Plan v1 aprobado", "orden": 1})
    assert [h["texto"] for h in r.json()["etapas"][0]["hitos"]] == ["Plan v1 aprobado", "Reunión", "Acta"]
    assert [h["orden"] for h in r.json()["etapas"][0]["hitos"]] == [1, 2, 3]
    assert eq.post(_api(pid, f"plan/hitos/{h3}"), json={"texto": ""}).status_code == 400
    r = eq.post(_api(pid, f"plan/etapas/{e2}"), json={"nombre": "Acordar el alcance"})
    assert r.json()["etapas"][1]["nombre"] == "Acordar el alcance"
    assert eq.post(_api(pid, f"plan/etapas/{e2}"), json={"nombre": ""}).status_code == 400
    t = _crear(sin, pid, hito_id=str(h2))
    r = eq.post(_api(pid, f"plan/hitos/{h2}"), json={"borrar": True})
    assert [h["texto"] for h in r.json()["etapas"][0]["hitos"]] == ["Plan v1 aprobado", "Reunión"]
    assert _detalle(sin, pid, t["id"])["tarjeta"]["hito_id"] is None
    assert eq.post(_api(pid, f"plan/hitos/{h2}"), json={"borrar": True}).status_code == 404
    # la traza del plan quedó (para el equipo; el sindicato no ve eventos sueltos)
    with db.get_session() as s:
        acciones = {e.accion for e in db.impl_eventos(s, pid, im.EQUIPO)}
    assert {"hito_nuevo", "hito", "hito_editar", "hito_borrar", "etapa_renombrar"} <= acciones


# ---------- Exportación ----------
def test_exportar_zip_solo_el_equipo_con_todo_adentro():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "entrega", titulo="Padrón", archivos=[_archivo("padron.csv", b"cuil;x\n1;2", "text/csv")])
    eq.post(_api(pid, f"tarjetas/{t['id']}/responder"), data={"texto": NOTA, "solo_equipo": "1"})
    ap = _crear(sin, pid, "aprobacion", titulo="Plan", texto="ok")
    eq.post(_api(pid, f"tarjetas/{ap['id']}/aprobacion"), json={"aprobar": True})
    borrado = _crear(sin, pid, "entrega", titulo="Borrado", archivos=[_archivo("chau.pdf")])
    aid = _detalle(sin, pid, borrado["id"])["archivos"][0]["id"]
    sin.post(_api(pid, f"archivos/{aid}/borrar"))

    assert sin.get(_api(pid, "exportar.zip")).status_code == 403
    r = eq.get(_api(pid, "exportar.zip"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith("attachment;")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nombres = set(z.namelist())
    assert {"proyecto.json", "etapas.json", "hitos.json", "tarjetas.json", "tarjetas.csv", "eventos.json",
            "descargas.json", "aprobaciones.json", "aprobaciones.csv"} <= nombres
    assert f"archivos/{t['numero']:04d}/{_detalle(eq, pid, t['id'])['archivos'][0]['id']}-padron.csv" in nombres
    assert not any("chau.pdf" in n for n in nombres)                    # borrado: sin bytes
    clave = [n for n in nombres if n.endswith("-padron.csv")][0]
    assert z.read(clave) == b"cuil;x\n1;2"
    tarjetas = json.loads(z.read("tarjetas.json"))
    por_num = {x["numero"]: x for x in tarjetas}
    assert NOTA in json.dumps(por_num[t["numero"]]["mensajes"])           # el equipo sí exporta las notas
    assert "datos" not in por_num[t["numero"]]["archivos"][0]
    assert any(a["nombre"] == "chau.pdf" and a["borrado_en"] for x in tarjetas for a in x["archivos"])
    assert json.loads(z.read("aprobaciones.json"))[0]["estado"] == "aprobada"
    # la exportación deja su evento (solo para el equipo)
    with db.get_session() as s:
        assert "exportar" in {e.accion for e in db.impl_eventos(s, pid, im.EQUIPO)}
        assert "exportar" not in {e.accion for e in db.impl_eventos(s, pid, im.SINDICATO)}


# ---------- Semilla ----------
def test_la_semilla_son_seis_fases_de_ocho_hitos():
    fases = im.cargar_hitos_semilla()
    assert [n for n, _ in fases] == [n for n, _ in im.FASES_POR_DEFECTO]
    assert all(len(h) == 8 for _, h in fases)
    assert "**" not in json.dumps(fases)


def test_hitos_semilla_por_api_solo_en_un_proyecto_sin_hitos():
    pid, eq, sin = _mundo()
    ruta = f"/api/entornos/implementacion/proyectos/{pid}/hitos-semilla"
    assert TestClient(main.app).post(ruta).status_code in (401, 403)
    r = eq.post(ruta)
    assert r.status_code == 200 and r.json() == {"ok": True, "cargados": 48}
    plan = sin.get(_api(pid, "plan")).json()["etapas"]
    assert [len(e["hitos"]) for e in plan] == [8] * 6 and plan[0]["hitos"][0]["orden"] == 1
    assert eq.post(ruta).status_code == 409                            # no se pisan
    assert eq.post("/api/entornos/implementacion/proyectos/99999999/hitos-semilla").status_code == 404
    otro = _proyecto()
    assert eq.get(_api(otro, "plan")).json()["etapas"][0]["hitos"] == []   # solo el suyo


def test_el_script_de_semilla_ensaya_y_es_idempotente(capsys):
    import cargar_implementacion_bancaria as semilla
    with db.get_session() as s:
        antes = [p.id for p in db.impl_proyectos(s) if p.nombre == semilla.NOMBRE_PROYECTO]
    assert semilla.main(False) == 0
    salida = capsys.readouterr().out
    assert "Ensayo" in salida or "ya tiene hitos" in salida
    with db.get_session() as s:
        assert [p.id for p in db.impl_proyectos(s) if p.nombre == semilla.NOMBRE_PROYECTO] == antes
    if antes:
        return                                  # la base ya tenía uno: no se escribe en ella desde un test
    semilla.main(True)
    semilla.main(True)
    with db.get_session() as s:
        ps = [p for p in db.impl_proyectos(s) if p.nombre == semilla.NOMBRE_PROYECTO]
        assert len(ps) == 1 and sum(e["total"] for e in db.impl_avance(s, ps[0].id)) == 48
        ps[0].nombre = "La Bancaria (prueba)"          # que otra corrida del test no lo vea
        s.add(ps[0])
        s.commit()


# ---------- Avisos por mail ----------
@pytest.fixture
def correo_simulado(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "habilitado", lambda: True)
    monkeypatch.setattr(correo, "enviar", lambda destino, asunto, texto: enviados.append((destino, asunto, texto)) or True)
    monkeypatch.setattr(main, "IMPL_AVISOS_SINCRONO", True)
    return enviados


def test_los_avisos_salen_a_quien_le_toca_y_sin_el_contenido(correo_simulado):
    mail_eq = f"{_u('equipo')}@colm3na.test"
    pid = _proyecto("La Bancaria avisos")
    eq = _cliente_equipo(email=mail_eq)
    sin_a, mail_a = _cliente_sindicato(pid, "Carla Sindicato")
    sin_b, mail_b = _cliente_sindicato(pid, "Dario Sindicato")
    with db.get_session() as s:
        inactivo = db.impl_usuario_alta(s, pid, "Baja", f"{_u()}@sindicato.test", "transitoria1", EQ)
        db.impl_usuario_activar(s, pid, inactivo.id, False, EQ)
        mail_baja = inactivo.mail
    # el sindicato crea un pedido: le avisan al equipo
    secreto = "CONTENIDO-PRIVADO-4410"
    t = _crear(sin_a, pid, titulo="Necesitamos el logo", texto=secreto, archivos=[_archivo("reservado-5521.pdf")])
    destinos = [d for d, _, _ in correo_simulado]
    assert mail_eq in destinos and mail_a not in destinos and mail_b not in destinos
    d, asunto, cuerpo = next(x for x in correo_simulado if x[0] == mail_eq)
    assert f"#{t['numero']}" in asunto and "Necesitamos el logo" in asunto
    assert f"/implementacion?p={pid}#t{t['numero']}" in cuerpo
    assert secreto not in asunto + cuerpo and "reservado-5521" not in asunto + cuerpo
    correo_simulado.clear()
    # el equipo responde: avisan a los usuarios activos del sindicato (no al de baja)
    r = _responder(eq, pid, t["id"], texto="Lo subimos mañana " + secreto, estado_nuevo="respondida")
    assert r.status_code == 200
    destinos = sorted(d for d, _, _ in correo_simulado)
    assert destinos == sorted([mail_a, mail_b]) and mail_baja not in destinos and mail_eq not in destinos
    assert all(secreto not in a + c and "Lo subimos" not in a + c for _, a, c in correo_simulado)
    correo_simulado.clear()
    # una nota interna no avisa a nadie
    _responder(eq, pid, t["id"], texto="entre nosotros", solo_equipo="1")
    assert correo_simulado == []
    # un aviso de Colm3na le llega al sindicato aunque no espere respuesta
    _crear(eq, pid, "aviso", titulo="Mañana no hay mesa", texto="x")
    assert sorted(d for d, _, _ in correo_simulado) == sorted([mail_a, mail_b])
    correo_simulado.clear()
    # el sindicato responde y el estado deja de esperarlo a él: avisa al equipo
    _responder(sin_a, pid, t["id"], texto="Gracias")
    assert [d for d, _, _ in correo_simulado].count(mail_eq) == 1
    correo_simulado.clear()
    # cerrar no avisa: no le toca a nadie
    _responder(sin_a, pid, t["id"], estado_nuevo="cerrada")
    assert correo_simulado == []


def test_con_el_canal_apagado_o_roto_nada_falla(monkeypatch):
    pid, eq, sin = _mundo()
    monkeypatch.setattr(correo, "habilitado", lambda: False)
    assert _crear(sin, pid)["estado"] == "abierta"
    monkeypatch.setattr(correo, "habilitado", lambda: True)
    monkeypatch.setattr(main, "IMPL_AVISOS_SINCRONO", True)

    def roto(*a, **k):
        raise RuntimeError("Resend caído")
    monkeypatch.setattr(correo, "enviar", roto)
    with db.get_session() as s:
        # un equipo con mail para que haya a quién mandar
        s.add(db.UsuarioPlataforma(usuario=_u("mail"), email=f"{_u()}@colm3na.test", activo=True,
                                   clave_hash="x", debe_cambiar_clave=False, debe_completar_datos=False))
        s.commit()
    assert _crear(sin, pid)["estado"] == "abierta"                     # el pedido sigue en pie


def test_texto_del_aviso_no_lleva_el_contenido():
    asunto, cuerpo = correo.texto_aviso_mesa("La Bancaria", 7, "Título\ncon salto", "https://x/implementacion?p=1#t7", "nueva")
    assert asunto == "Mesa de implementación · #7 Título con salto" and "\n" not in asunto
    assert "https://x/implementacion?p=1#t7" in cuerpo and "tarjeta nueva" in cuerpo
    assert "respuesta" in correo.texto_aviso_mesa("P", 1, "t", "u", "respuesta")[1]


# ---------- Página ----------
def test_la_pagina_de_la_mesa_y_su_contexto(monkeypatch):
    capturado = {}

    class Falsa:
        def get_template(self, nombre):
            return object()

        def TemplateResponse(self, nombre, contexto, **kw):
            capturado["nombre"], capturado["ctx"] = nombre, contexto
            return JSONResponse({"ok": True})

    p1 = _proyecto("Mesa A")
    p2 = _proyecto("Mesa B")
    eq = _cliente_equipo()
    sin, _ = _cliente_sindicato(p2)
    monkeypatch.setattr(main, "templates", Falsa())
    # equipo con varios proyectos y sin ?p=: el primero activo
    assert eq.get("/implementacion").status_code == 200
    ctx = capturado["ctx"]
    assert capturado["nombre"] == "impl_mesa.html"
    with db.get_session() as s:
        primero = [p for p in db.impl_proyectos(s) if p.activo][0]
    assert ctx["proyecto"]["id"] == primero.id and ctx["yo"]["lado"] == "equipo" and ctx["es_equipo"] is True
    assert {"id": p1, "nombre": "Mesa A"} in ctx["proyectos"] and len(ctx["proyectos"]) >= 2
    assert [t["id"] for t in ctx["tipos"]] == list(im.ORDEN_TIPOS) and ctx["tipos"][0]["color"]
    assert [e["id"] for e in ctx["estados"]] == list(im.ESTADOS)
    assert ctx["api"] == f"/api/implementacion/p/{primero.id}"
    # con ?p=
    assert eq.get(f"/implementacion?p={p2}").status_code == 200
    assert capturado["ctx"]["proyecto"] == {"id": p2, "nombre": "Mesa B"}
    assert eq.get("/implementacion?p=99999999").status_code == 404
    # el sindicato entra siempre al suyo y no ve la lista de proyectos
    assert sin.get("/implementacion").status_code == 200
    ctx = capturado["ctx"]
    assert ctx["proyecto"]["id"] == p2 and ctx["proyectos"] == [] and ctx["yo"]["lado"] == "sindicato"
    assert sin.get(f"/implementacion?p={p2}").status_code == 200
    assert sin.get(f"/implementacion?p={p1}").status_code == 404
    assert TestClient(main.app).get("/implementacion").status_code == 401


# ---------- Motor puro agregado ----------
def test_acciones_de_y_texto_evento_puros():
    assert im.acciones_de("pedido", "abierta", "equipo", "equipo")["solo_equipo"] is True
    assert im.acciones_de("pedido", "abierta", "equipo", "sindicato")["solo_equipo"] is False
    assert im.acciones_de("pedido", "cerrada", "", "equipo")["reabrir"] is True
    assert im.acciones_de("aprobacion", "abierta", "sindicato", "sindicato")["aprobar"] is True
    assert {e["id"] for e in im.acciones_de("aprobacion", "abierta", "equipo", "equipo")["estados"]} == {"en_curso", "respondida"}
    assert im.acciones_de("pedido", "inexistente", "", "equipo")["responder"] is False
    assert im.texto_evento("subir", {"nombre": "a.pdf", "datos_personales": True}) == "subió a.pdf (con datos personales)"
    assert im.texto_evento("rara", {}) == "rara"
    assert set(im.ACCIONES) >= {"hito_editar", "hito_borrar", "etapa_renombrar", "hitos_semilla", "exportar"}


def test_error_impl_sin_atrapar_sale_como_json_con_su_status():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    r = sin.post(_api(pid, f"tarjetas/{t['id']}/responder"), data={"texto": "x" * (im.TOPE_TEXTO + 1)})
    assert r.status_code == 400 and r.json()["codigo"] == "texto" and "detail" in r.json()
    with pytest.raises(HTTPException):
        main._actor_impl(main.Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                                       "headers": []}), pid)
    assert re.fullmatch(r"[a-z_]+", r.json()["codigo"])
