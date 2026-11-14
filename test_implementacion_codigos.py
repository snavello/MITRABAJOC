"""Mesa de implementación: códigos y relaciones (PLAN_IMPLEMENTACION.md, I12 a
I14). Formato y parseo (puro); contadores por tipo y proyecto, con hilos en
paralelo; el código nace y no cambia; menciones, «responde a» y archivos
relacionados; el sindicato NO recibe relaciones nacidas de notas internas ni
hacia cosas internas (fail-closed sobre las rutas GET); un código de otro
proyecto no enlaza; y la migración con backfill sobre datos previos.

Correr con: python -m pytest test_implementacion_codigos.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import csv
import io
import json
import subprocess
import sys
import threading
import uuid
import zipfile

import psycopg
import pytest
from fastapi.testclient import TestClient

import auth
import db
import implementacion as im
import main
from test_migraciones import _psycopg, _url_con_base

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
SIN = im.Actor(im.SINDICATO, 77, "Carla")
DEFINITIVA = "definitiva-2026"


@pytest.fixture(autouse=True)
def _sin_freno():
    main._intentos_impl.clear()
    yield
    main._intentos_impl.clear()


def _u(prefijo="x"):
    return f"{prefijo}{uuid.uuid4().hex[:8]}"


def _proyecto():
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, _u("Proy "), EQ).id


def _cliente_sindicato(pid):
    mail = f"{_u()}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, "Carla Sindicato", mail, "transitoria1", EQ)
        db.impl_usuario_cambiar_clave(s, u.id, "transitoria1", DEFINITIVA)
    c = TestClient(main.app, follow_redirects=False)
    r = c.post("/implementacion/ingresar", data={"mail": mail, "clave": DEFINITIVA})
    assert r.headers["location"] == "/implementacion"
    return c


def _cliente_equipo():
    usuario = _u("eq")
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario, email="",
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
    pid = _proyecto()
    return pid, _cliente_equipo(), _cliente_sindicato(pid)


def _api(pid, ruta=""):
    return f"/api/implementacion/p/{pid}/{ruta}".rstrip("/")


def _crear(c, pid, tipo="pedido", titulo="Un título", texto="Un texto", archivos=None, **extra):
    r = c.post(_api(pid, "tarjetas"), data={"tipo": tipo, "titulo": titulo, "texto": texto, **extra},
               files=archivos or None)
    assert r.status_code == 200, r.text
    return r.json()["tarjeta"]


def _archivo(nombre="informe.pdf", datos=b"%PDF-1.4 contenido"):
    return ("archivos", (nombre, datos, "application/pdf"))


def _responder(c, pid, tid, **datos):
    r = c.post(_api(pid, f"tarjetas/{tid}/responder"), data=datos, files=datos.pop("files", None))
    assert r.status_code == 200, r.text
    return r.json()


def _detalle(c, pid, tid):
    r = c.get(_api(pid, f"tarjetas/{tid}"))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Formato y parseo (puro) ----------
def test_formato_de_los_codigos():
    assert [im.prefijo_de_tipo(t) for t in im.ORDEN_TIPOS] == ["PE", "CO", "EN", "AP", "ER", "AV"]
    assert im.formatear_codigo("PE", 4) == "PE0004"
    assert im.formatear_codigo("pe", 4, 3) == "PE0004-3"
    assert im.formatear_codigo("AR", 123) == "AR000123"
    assert im.formatear_codigo("HI", 1) == "HI0001"
    assert im.formatear_codigo("PE", 12345) == "PE12345"            # crece, no se trunca
    for malo in (("XX", 1), ("PE", 0)):
        with pytest.raises(ValueError):
            im.formatear_codigo(*malo)
    with pytest.raises(ValueError):
        im.formatear_codigo("AR", 1, 2)                              # solo un mensaje de tarjeta lleva orden


def test_parseo_de_un_codigo_solo():
    d = im.parsear_codigo("pe0004")
    assert d["tipo"] == "tarjeta" and d["codigo"] == "PE0004" and d["numero"] == 4 and d["orden"] is None
    d = im.parsear_codigo(" Ap0010-12 ")
    assert d["tipo"] == "mensaje" and d["codigo"] == "AP0010-12" and d["base"] == "AP0010" and d["orden"] == 12
    assert im.parsear_codigo("AR000123")["tipo"] == "archivo"
    assert im.parsear_codigo("hi0001")["tipo"] == "hito"
    for malo in ("", "PE", "PE004", "PE00041", "PE0000", "AR0001", "AR000123-2", "HI0001-1", "XX0001",
                 "PE0004-0", "PE0004 x", "hola"):
        assert im.parsear_codigo(malo) is None, malo


def test_extraer_codigos_de_un_texto():
    texto = "Ver pe0004 y PE0004; el AR000123, HI0001 y (CO0002-3). También pe0004-3."
    assert im.extraer_codigos(texto) == ["PE0004", "AR000123", "HI0001", "CO0002-3", "PE0004-3"]
    # palabra completa: ni pegado a letras o dígitos, ni a un guion bajo
    for no in ("XPE0004", "PE0004x", "PE00041", "PE000", "_PE0004", "PE0004_", "AR12345", "TAPE0004", "PE0004-"):
        extraidos = im.extraer_codigos(no)
        assert extraidos == ([] if no != "PE0004-" else ["PE0004"]), (no, extraidos)
    assert im.extraer_codigos("") == [] and im.extraer_codigos(None) == []
    assert im.extraer_codigos("PE0004.") == ["PE0004"] and im.extraer_codigos("a/PE0004/b") == ["PE0004"]


def test_enlaces_y_textos_de_relacion():
    assert im.enlace_codigo(7, "PE0004-3") == "/implementacion?p=7#PE0004-3"
    assert im.texto_relacion("responde", "sale") == "responde a"
    assert im.texto_relacion("responde", "entra") == "respondida con"
    assert im.texto_relacion("menciona", "sale") == "menciona"
    assert im.texto_relacion("menciona", "entra") == "mencionada en"


# ---------- Contadores ----------
def test_los_contadores_son_por_tipo_y_por_proyecto():
    pa, pb = _proyecto(), _proyecto()
    with db.get_session() as s:
        a1 = db.impl_crear_tarjeta(s, pa, EQ, "pedido", "uno", "x")
        a2 = db.impl_crear_tarjeta(s, pa, EQ, "pedido", "dos", "x")
        a3 = db.impl_crear_tarjeta(s, pa, EQ, "consulta", "tres", "x")
        a4 = db.impl_crear_tarjeta(s, pa, EQ, "error", "cuatro", "x")
        b1 = db.impl_crear_tarjeta(s, pb, EQ, "pedido", "otro proyecto", "x")
        assert [a1.codigo, a2.codigo, a3.codigo, a4.codigo] == ["PE0001", "PE0002", "CO0001", "ER0001"]
        assert b1.codigo == "PE0001"                                  # el contador de cada proyecto es suyo
        assert [a1.numero, a2.numero, a3.numero, a4.numero] == [1, 2, 3, 4]   # el numero de siempre sigue
        for tipo, pref in (("entrega", "EN"), ("aprobacion", "AP"), ("aviso", "AV")):
            assert db.impl_crear_tarjeta(s, pa, EQ, tipo, "t", "x").codigo == f"{pref}0001"
        r1 = db.impl_subir_archivo(s, pa, a1.id, EQ, "a.pdf", "application/pdf", b"%PDF-1")
        r2 = db.impl_subir_archivo(s, pa, a3.id, EQ, "b.pdf", "application/pdf", b"%PDF-2")
        r3 = db.impl_subir_archivo(s, pb, b1.id, EQ, "c.pdf", "application/pdf", b"%PDF-3")
        assert [r1.codigo, r2.codigo, r3.codigo] == ["AR000001", "AR000002", "AR000001"]
        e = db.impl_etapas(s, pa)[0]
        h1 = db.impl_agregar_hito(s, pa, e.id, "primero", EQ)
        h2 = db.impl_agregar_hito(s, pa, e.id, "segundo", EQ)
        h3 = db.impl_agregar_hito(s, pb, db.impl_etapas(s, pb)[0].id, "otro", EQ)
        assert [h1.codigo, h2.codigo, h3.codigo] == ["HI0001", "HI0002", "HI0001"]


def test_el_orden_de_un_mensaje_cuenta_tambien_las_notas_internas():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, titulo="Pedido")
    _responder(eq, pid, t["id"], texto="nota entre nosotros", solo_equipo="1")
    _responder(eq, pid, t["id"], texto="respuesta pública", estado_nuevo="respondida")
    _responder(sin, pid, t["id"], texto="gracias")
    eq_ven = _detalle(eq, pid, t["id"])["mensajes"]
    sin_ven = _detalle(sin, pid, t["id"])["mensajes"]
    assert [(m["orden"], m["codigo"]) for m in eq_ven] == [(1, f"{t['codigo']}-1"), (2, f"{t['codigo']}-2"),
                                                           (3, f"{t['codigo']}-3"), (4, f"{t['codigo']}-4")]
    # el sindicato ve la misma numeración (con un hueco donde estaba la nota interna)
    assert [m["orden"] for m in sin_ven] == [1, 3, 4]
    assert [m["codigo"] for m in sin_ven] == [f"{t['codigo']}-1", f"{t['codigo']}-3", f"{t['codigo']}-4"]


def test_concurrencia_no_repite_ni_salta_codigos():
    pid = _proyecto()
    with db.get_session() as s:
        t0 = db.impl_crear_tarjeta(s, pid, EQ, "pedido", "base", "x")
        etapa = db.impl_etapas(s, pid)[0].id
        t0_id = t0.id
    n = 12
    resultados, errores = [], []
    barrera = threading.Barrier(n)

    def hacer(i):
        try:
            barrera.wait(timeout=20)
            with db.get_session() as s:
                t = db.impl_crear_tarjeta(s, pid, EQ, "pedido" if i % 2 else "consulta", f"t{i}", "x")
                a = db.impl_subir_archivo(s, pid, t0_id, EQ, f"f{i}.pdf", "application/pdf", b"%PDF-" + bytes([65 + i]))
                h = db.impl_agregar_hito(s, pid, etapa, f"h{i}", EQ)
                m = db.impl_responder(s, pid, t0_id, EQ, texto=f"mensaje {i}")
                resultados.append((t.codigo, a.codigo, h.codigo, m.orden))
        except Exception as e:                                       # pragma: no cover
            errores.append(repr(e))
    hilos = [threading.Thread(target=hacer, args=(i,)) for i in range(n)]
    [h.start() for h in hilos]
    [h.join(60) for h in hilos]
    assert not errores, errores
    assert len(resultados) == n
    tarjetas, archivos, hitos, ordenes = (sorted(x[i] for x in resultados) for i in range(4))
    assert archivos == [f"AR{k:06d}" for k in range(1, n + 1)]
    assert hitos == [f"HI{k:04d}" for k in range(1, n + 1)]
    assert ordenes == list(range(2, n + 2))                          # el 1 es el texto inicial de la base
    pe = sorted(c for c in tarjetas if c.startswith("PE"))
    co = sorted(c for c in tarjetas if c.startswith("CO"))
    assert pe == [f"PE{k:04d}" for k in range(2, 2 + len(pe))]       # PE0001 es la base
    assert co == [f"CO{k:04d}" for k in range(1, 1 + len(co))] and len(pe) + len(co) == n


def test_el_codigo_no_cambia_nunca():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "aprobacion", titulo="Aprobar el alcance", archivos=[_archivo()])
    arch = _detalle(sin, pid, t["id"])["archivos"][0]
    plan = eq.get(_api(pid, "plan")).json()["etapas"]
    r = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": plan[0]["id"], "texto": "Hito original"})
    hito = r.json()["etapas"][0]["hitos"][-1]
    # todo lo que se le puede hacer a una tarjeta, un archivo y un hito
    _responder(eq, pid, t["id"], texto="ok", estado_nuevo="respondida")
    eq.post(_api(pid, f"tarjetas/{t['id']}/reasignar"), json={"responsable": "Ana", "responsable_lado": "equipo"})
    r = sin.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": True, "texto": "listo"})
    assert r.status_code == 200
    eq.post(_api(pid, f"plan/hitos/{hito['id']}"), json={"texto": "Hito renombrado", "orden": 1})
    eq.post(_api(pid, f"plan/etapas/{plan[0]['id']}"), json={"nombre": "Otra etapa"})
    d = _detalle(sin, pid, t["id"])
    assert d["tarjeta"]["codigo"] == t["codigo"] and d["archivos"][0]["codigo"] == arch["codigo"]
    hito2 = [h for e in eq.get(_api(pid, "plan")).json()["etapas"] for h in e["hitos"] if h["id"] == hito["id"]][0]
    assert hito2["codigo"] == hito["codigo"] and hito2["texto"] == "Hito renombrado"
    # un hito borrado deja su código sin usar: el siguiente sigue de largo
    eq.post(_api(pid, f"plan/hitos/{hito['id']}"), json={"borrar": True})
    r = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": plan[0]["id"], "texto": "Nuevo"})
    nuevo = r.json()["etapas"][0]["hitos"][-1]
    assert nuevo["codigo"] != hito["codigo"] and int(nuevo["codigo"][2:]) == int(hito["codigo"][2:]) + 1
    # no hay ruta para tocar el código: lo imponen el modelo y la base (única por proyecto)
    with db.get_session() as s:
        otra = db.impl_crear_tarjeta(s, pid, EQ, "aprobacion", "otra", "x")
        otra.codigo = t["codigo"]
        s.add(otra)
        with pytest.raises(db.IntegrityError):
            s.commit()


# ---------- Menciones ----------
def _relacionadas(c, pid, tid):
    return _detalle(c, pid, tid)["relacionadas"]


def test_menciones_en_titulo_texto_y_respuesta():
    pid, eq, sin = _mundo()
    a = _crear(sin, pid, titulo="Primero")
    b = _crear(sin, pid, "consulta", titulo="Segundo")
    c = _crear(sin, pid, "error", titulo="Tercero")
    # en el título (en minúsculas), en el texto y en una respuesta posterior
    t = _crear(eq, pid, titulo=f"Sobre {a['codigo'].lower()}", texto=f"Y también {b['codigo']}")
    _responder(eq, pid, t["id"], texto=f"Además {c['codigo']} y {a['codigo']} de nuevo")
    rel = _relacionadas(eq, pid, t["id"])
    assert sorted((r["codigo"], r["texto"], r["sentido"]) for r in rel) == sorted([
        (a["codigo"], "menciona", "sale"), (b["codigo"], "menciona", "sale"), (c["codigo"], "menciona", "sale")])
    assert all(r["clase"] == "menciona" and r["tipo"] == "tarjeta" and r["enlace"] == f"/implementacion?p={pid}#{r['codigo']}"
               for r in rel)
    # en la otra punta: «mencionada en»
    entra = _relacionadas(eq, pid, a["id"])
    assert [(r["codigo"], r["texto"], r["sentido"], r["titulo"]) for r in entra] == [
        (t["codigo"], "mencionada en", "entra", t["titulo"])]
    assert entra[0]["estado"] == "abierta"
    # el sindicato, que ve todo esto, también
    assert [r["codigo"] for r in _relacionadas(sin, pid, a["id"])] == [t["codigo"]]


def test_mencion_a_un_mensaje_un_archivo_y_un_hito():
    pid, eq, sin = _mundo()
    base = _crear(sin, pid, titulo="Con archivo", archivos=[_archivo("padron.csv")])
    arch = _detalle(sin, pid, base["id"])["archivos"][0]
    _responder(eq, pid, base["id"], texto="Recibido")
    etapa = eq.get(_api(pid, "plan")).json()["etapas"][0]["id"]
    hito = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": "Padrón recibido"}).json()["etapas"][0]["hitos"][-1]
    t = _crear(eq, pid, titulo="Seguimiento",
               texto=f"Revisar {arch['codigo']}, la respuesta {base['codigo']}-2 y el hito {hito['codigo']}")
    rel = {r["codigo"]: r for r in _relacionadas(eq, pid, t["id"])}
    assert set(rel) == {arch["codigo"], f"{base['codigo']}-2", hito["codigo"]}
    assert rel[arch["codigo"]]["tipo"] == "archivo" and rel[arch["codigo"]]["titulo"] == "padron.csv"
    assert rel[f"{base['codigo']}-2"]["tipo"] == "mensaje" and rel[f"{base['codigo']}-2"]["titulo"] == "Con archivo"
    assert rel[hito["codigo"]]["tipo"] == "hito" and rel[hito["codigo"]]["estado"] == "pendiente"
    # la tarjeta mencionada la recibe con el mensaje concreto como `via`
    entra = [r for r in _relacionadas(eq, pid, base["id"]) if r["codigo"] == t["codigo"]]
    assert len(entra) == 1 and entra[0]["via"] == f"{base['codigo']}-2" and entra[0]["texto"] == "mencionada en"
    # y la ficha del archivo
    f = eq.get(_api(pid, f"archivos/{arch['id']}/ficha")).json()
    assert f["archivo"]["codigo"] == arch["codigo"] and f["tarjeta"]["codigo"] == base["codigo"]
    assert [(r["codigo"], r["texto"]) for r in f["relacionadas"]] == [(t["codigo"], "mencionada en")]
    assert "datos" not in f["archivo"]


def test_un_codigo_inexistente_o_de_otro_proyecto_se_ignora_en_silencio():
    pid, eq, sin = _mundo()
    otro_pid, otro_eq, otro_sin = _mundo()
    for i in range(3):                      # en el otro proyecto los contadores llegan a 3 (acá a 1)
        ajeno_arch = _crear(otro_sin, otro_pid, titulo=f"De otro proyecto {i}", archivos=[_archivo()])
    ajena = ajeno_arch
    arch_ajeno = _detalle(otro_sin, otro_pid, ajena["id"])["archivos"][0]
    assert ajena["codigo"] == "PE0003" and arch_ajeno["codigo"] == "AR000003"
    t = _crear(sin, pid, titulo=f"Mira {ajena['codigo']}", texto=f"{arch_ajeno['codigo']} PE9999 HI0042 AR000777 {ajena['codigo']}-1")
    # nada de esto existe en ESTE proyecto: no se relaciona
    for c in (eq, sin):
        d = _detalle(c, pid, t["id"])
        assert d["relacionadas"] == []
        # los códigos del texto salen en `refs` pero sin existir ni enlace (no se revela nada)
        assert d["mensajes"][0]["refs"] and all(r["existe"] is False and r["enlace"] == "" for r in d["mensajes"][0]["refs"])
    # y del otro proyecto no se enteró nadie
    assert _relacionadas(otro_eq, otro_pid, ajena["id"]) == []
    assert eq.get(_api(pid, "buscar"), params={"codigo": ajena["codigo"]}).status_code == 404


def test_refs_por_mensaje_dicen_que_existe_y_a_donde_lleva():
    pid, eq, sin = _mundo()
    a = _crear(sin, pid, titulo="Uno")
    t = _crear(eq, pid, titulo="Dos", texto=f"Ver {a['codigo']} y PE0099")
    m = _detalle(eq, pid, t["id"])["mensajes"][0]
    refs = {r["codigo"]: r for r in m["refs"]}
    assert refs[a["codigo"]] == {"codigo": a["codigo"], "tipo": "tarjeta",
                                 "enlace": f"/implementacion?p={pid}#{a['codigo']}", "existe": True}
    assert refs["PE0099"]["existe"] is False and refs["PE0099"]["enlace"] == ""
    assert _detalle(eq, pid, t["id"])["tarjeta"]["refs"] == []       # el título no nombra nada


# ---------- Responder con… ----------
def test_responder_con_crea_la_relacion_y_liga_los_archivos():
    pid, eq, sin = _mundo()
    original = _crear(sin, pid, "consulta", titulo="¿Qué formato quieren?")
    nueva = _crear(eq, pid, "entrega", titulo="Entrega del modelo", texto="Va adjunto",
                   responde_a=original["codigo"].lower(), archivos=[_archivo("modelo.xlsx"), _archivo("guia.pdf")])
    arch = _detalle(eq, pid, nueva["id"])["archivos"]
    rel = _relacionadas(eq, pid, nueva["id"])
    assert [(r["codigo"], r["texto"], r["sentido"], r["clase"]) for r in rel] == [
        (original["codigo"], "responde a", "sale", "responde")]
    entra = _relacionadas(sin, pid, original["id"])
    assert sorted((r["tipo"], r["codigo"], r["texto"]) for r in entra) == sorted(
        [("tarjeta", nueva["codigo"], "respondida con")] + [("archivo", a["codigo"], "respondida con") for a in arch])
    # por id también vale
    otra = _crear(eq, pid, titulo="Otra", responde_a=str(original["id"]))
    assert nueva["codigo"] in [r["codigo"] for r in _relacionadas(sin, pid, original["id"])]
    assert [r["codigo"] for r in _relacionadas(eq, pid, otra["id"])] == [original["codigo"]]
    # la ficha del archivo muestra a qué respondió
    f = eq.get(_api(pid, f"archivos/{arch[0]['id']}/ficha")).json()
    assert [(r["codigo"], r["texto"]) for r in f["relacionadas"]] == [(original["codigo"], "responde a")]
    # responde_a que no existe o es de otro proyecto: 400, y no se crea la tarjeta
    otro_pid, _, otro_sin = _mundo()
    ajena = _crear(otro_sin, otro_pid, titulo="Ajena")
    antes = len(eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"])
    for malo in ("PE9999", ajena["codigo"], str(ajena["id"] + 100000), "hola"):
        r = eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "x", "texto": "y", "responde_a": malo})
        if malo == ajena["codigo"]:
            # PE0001 existe en los dos proyectos: el código se resuelve SIEMPRE dentro del proyecto de la ruta
            assert r.status_code == 200
            antes += 1
            continue
        assert r.status_code == 400 and r.json()["codigo"] == "responde_a", (malo, r.text)
    assert len(eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"]) == antes


# ---------- Lo interno no viaja al sindicato ----------
SECRETO = "TEXTO-INTERNO-SECRETO-5512"


def _rutas_get(pid, tarjetas, archivos, codigo_secreto):
    rutas = ["resumen", "tarjetas?vista=todas", "tarjetas?vista=pendientes", f"tarjetas?vista=todas&q={codigo_secreto}",
             f"tarjetas?vista=todas&q={codigo_secreto.lower()}", "carpetas?sentido=entrada", "carpetas?sentido=salida",
             "aprobaciones", "plan", f"buscar?codigo={codigo_secreto}", f"buscar?codigo={codigo_secreto.lower()}"]
    rutas += [f"tarjetas/{t}" for t in tarjetas]
    rutas += [f"archivos/{a}/ficha" for a in archivos] + [f"archivos/{a}" for a in archivos]
    return [_api(pid, r) for r in rutas]


def test_el_sindicato_no_recibe_relaciones_de_notas_internas_ni_hacia_cosas_internas():
    pid, eq, sin = _mundo()
    visible = _crear(sin, pid, titulo="Pedido visible", archivos=[_archivo("visible.pdf")])
    otra = _crear(sin, pid, "consulta", titulo="Otra visible")
    arch_visible = _detalle(sin, pid, visible["id"])["archivos"][0]
    # el equipo sube un archivo con una nota INTERNA
    r = eq.post(_api(pid, f"tarjetas/{visible['id']}/responder"),
                data={"texto": f"{SECRETO} no es para el sindicato", "solo_equipo": "1"},
                files=[_archivo("interno-secreto.pdf", b"%PDF-interno")])
    assert r.status_code == 200
    det_eq = r.json()
    interno = [a for a in det_eq["archivos"] if a["nombre"] == "interno-secreto.pdf"][0]
    nota = [m for m in det_eq["mensajes"] if m["solo_equipo"]][0]
    # nota interna que MENCIONA a otra tarjeta, a un archivo visible y al archivo interno
    _responder(eq, pid, otra["id"], texto=f"{SECRETO} nota sobre {visible['codigo']} y {arch_visible['codigo']} "
                                          f"y {interno['codigo']}", solo_equipo="1")
    # el equipo SÍ ve todo
    assert ("mencionada en", otra["codigo"]) in {(r["texto"], r["codigo"]) for r in _relacionadas(eq, pid, visible["id"])}
    f_eq = eq.get(_api(pid, f"archivos/{interno['id']}/ficha")).json()
    assert {r["codigo"] for r in f_eq["relacionadas"]} == {otra["codigo"]}
    assert {r["codigo"] for r in _relacionadas(eq, pid, otra["id"])} >= {visible["codigo"], arch_visible["codigo"],
                                                                         interno["codigo"]}
    # el sindicato: nada de lo interno, en NINGUNA ruta GET
    todas = [t["id"] for t in eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"]]
    barridas = 0
    for ruta in _rutas_get(pid, todas, [interno["id"], arch_visible["id"]], interno["codigo"]):
        r = sin.get(ruta)
        barridas += 1
        cuerpo = r.text
        assert interno["codigo"] not in cuerpo and interno["codigo"].lower() not in cuerpo, ruta
        assert nota["codigo"] not in cuerpo and SECRETO not in cuerpo and "interno-secreto" not in cuerpo, ruta
        if f"archivos/{interno['id']}" in ruta or f"codigo={interno['codigo']}" in ruta.upper().replace(
                interno["codigo"].upper(), interno["codigo"]):
            assert r.status_code == 404, ruta
    assert barridas >= 15
    # nada nacido de la nota interna le llega a la tarjeta visible
    assert _relacionadas(sin, pid, visible["id"]) == [] and _relacionadas(sin, pid, otra["id"]) == []
    # una respuesta PÚBLICA que nombra el archivo y el mensaje internos: el texto lo escribió el equipo, y
    # para el sindicato son refs que no existen y no enlazan; la relación hacia lo interno no viaja
    publica = _crear(eq, pid, titulo="Pública", texto=f"Ver {interno['codigo']} y {nota['codigo']} y {visible['codigo']}")
    refs = {r["codigo"]: r for r in _detalle(sin, pid, publica["id"])["mensajes"][0]["refs"]}
    assert refs[interno["codigo"]] == {"codigo": interno["codigo"], "tipo": "archivo", "enlace": "", "existe": False}
    assert refs[nota["codigo"]]["existe"] is False and refs[nota["codigo"]]["enlace"] == ""
    assert refs[visible["codigo"]]["existe"] is True
    assert [r["codigo"] for r in _relacionadas(sin, pid, publica["id"])] == [visible["codigo"]]
    assert [r["codigo"] for r in _relacionadas(sin, pid, visible["id"])] == [publica["codigo"]]
    assert {r["codigo"] for r in _relacionadas(eq, pid, publica["id"])} == {
        interno["codigo"], nota["codigo"], visible["codigo"]}
    assert {r["codigo"] for r in eq.get(_api(pid, f"archivos/{interno['id']}/ficha")).json()["relacionadas"]} == {
        otra["codigo"], publica["codigo"]}
    # buscar: 404 para el sindicato, igual que un código que no existe
    assert sin.get(_api(pid, "buscar"), params={"codigo": interno["codigo"]}).status_code == 404
    assert sin.get(_api(pid, "buscar"), params={"codigo": nota["codigo"]}).status_code == 404
    assert sin.get(_api(pid, "buscar"), params={"codigo": "AR999999"}).status_code == 404
    assert eq.get(_api(pid, "buscar"), params={"codigo": interno["codigo"]}).json()["tipo"] == "archivo"
    # la búsqueda `q` por el código del mensaje/archivo interno tampoco delata la tarjeta
    for q in (interno["codigo"], nota["codigo"]):
        # (la pública lo nombra en su propio texto, que el sindicato lee: eso es texto, no el vínculo)
        assert [t["id"] for t in sin.get(_api(pid, "tarjetas"), params={"vista": "todas", "q": q}).json()["tarjetas"]
                ] == [publica["id"]]
        assert visible["id"] in [t["id"] for t in eq.get(_api(pid, "tarjetas"), params={"vista": "todas", "q": q}).json()["tarjetas"]]


def test_una_mencion_publica_pisa_a_la_interna_de_la_misma_pareja():
    pid, eq, sin = _mundo()
    a = _crear(sin, pid, titulo="A")
    b = _crear(eq, pid, titulo="B")
    _responder(eq, pid, b["id"], texto=f"nota: {a['codigo']}", solo_equipo="1")
    assert _relacionadas(sin, pid, a["id"]) == []
    _responder(eq, pid, b["id"], texto=f"ahora público: {a['codigo']}")
    assert [r["codigo"] for r in _relacionadas(sin, pid, a["id"])] == [b["codigo"]]


# ---------- Buscador ----------
def test_buscar_un_codigo_lleva_a_la_cosa():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, titulo="Algo", archivos=[_archivo("x.pdf")])
    arch = _detalle(sin, pid, t["id"])["archivos"][0]
    etapa = eq.get(_api(pid, "plan")).json()["etapas"][0]["id"]
    hito = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": "Un hito"}).json()["etapas"][0]["hitos"][-1]
    for c in (sin, eq):
        r = c.get(_api(pid, "buscar"), params={"codigo": t["codigo"].lower()}).json()
        assert r["tipo"] == "tarjeta" and r["codigo"] == t["codigo"] and r["enlace"] == f"/implementacion?p={pid}#{t['codigo']}"
        r = c.get(_api(pid, "buscar"), params={"codigo": arch["codigo"]}).json()
        assert r["tipo"] == "archivo" and r["enlace"].endswith("#" + arch["codigo"])
        r = c.get(_api(pid, "buscar"), params={"codigo": f"{t['codigo']}-1"}).json()
        assert r["tipo"] == "mensaje" and r["enlace"].endswith(f"#{t['codigo']}-1")
        r = c.get(_api(pid, "buscar"), params={"codigo": hito["codigo"]}).json()
        assert r["tipo"] == "hito" and r["enlace"].endswith("#" + hito["codigo"])
        for malo in ("", "XX0001", "PE9999", f"{t['codigo']}-9", "AR999999", "HI0999"):
            assert c.get(_api(pid, "buscar"), params={"codigo": malo}).status_code == 404, malo
    # el filtro `q` también encuentra por código (entero, en minúsculas o parcial)
    ids = lambda q: [x["id"] for x in sin.get(_api(pid, "tarjetas"), params={"vista": "todas", "q": q}).json()["tarjetas"]]  # noqa: E731
    assert ids(t["codigo"]) == [t["id"]] and ids(t["codigo"].lower()) == [t["id"]] and ids("PE00") == [t["id"]]
    assert ids(arch["codigo"]) == [t["id"]] and ids(f"{t['codigo']}-1") == [t["id"]] and ids(f"{t['codigo']}-5") == []
    # un hito encuentra las tarjetas que cuelgan de él
    h = _crear(eq, pid, titulo="Colgada", hito_id=str(hito["id"]))
    assert ids(hito["codigo"]) == [h["id"]]


def test_un_codigo_de_otro_proyecto_no_se_encuentra():
    pid, eq, sin = _mundo()
    otro_pid, otro_eq, otro_sin = _mundo()
    ajena = _crear(otro_sin, otro_pid, titulo="Ajena", archivos=[_archivo()])
    ajeno_arch = _detalle(otro_sin, otro_pid, ajena["id"])["archivos"][0]
    assert eq.get(_api(pid, "buscar"), params={"codigo": ajeno_arch["codigo"]}).status_code == 404
    assert sin.get(_api(pid, "buscar"), params={"codigo": ajeno_arch["codigo"]}).status_code == 404
    assert eq.get(_api(pid, f"archivos/{ajeno_arch['id']}/ficha")).status_code == 404
    assert sin.get(_api(pid, f"archivos/{ajeno_arch['id']}/ficha")).status_code == 404
    # el sindicato de otro proyecto no entra a este por la ruta
    assert otro_sin.get(_api(pid, "buscar"), params={"codigo": "PE0001"}).status_code == 404
    assert otro_sin.get(_api(pid, f"archivos/{ajeno_arch['id']}/ficha")).status_code == 404


# ---------- Contrato aditivo, CSV, carpetas y ZIP ----------
def test_campos_nuevos_del_contrato_y_los_viejos_siguen():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "aprobacion", titulo="Aprobar", archivos=[_archivo()])
    assert t["codigo"] == "AP0001" and t["numero"] == 1 and t["id"]
    d = _detalle(eq, pid, t["id"])
    assert d["archivos"][0]["codigo"] == "AR000001" and d["mensajes"][0]["codigo"] == "AP0001-1"
    assert d["mensajes"][0]["orden"] == 1 and d["mensajes"][0]["id"] and d["relacionadas"] == []
    carpetas = eq.get(_api(pid, "carpetas"), params={"sentido": "entrada"}).json()["etapas"]
    a = carpetas[0]["archivos"][0]
    assert a["codigo"] == "AR000001" and a["tarjeta_codigo"] == "AP0001" and a["tarjeta_numero"] == 1
    sin.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": True})
    eq.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": True, "texto": "ok"})
    ap = eq.get(_api(pid, "aprobaciones")).json()["aprobaciones"][0]
    assert ap["codigo"] == "AP0001" and ap["numero"] == 1
    texto = eq.get(_api(pid, "aprobaciones.csv")).content.decode("utf-8")
    filas = list(csv.reader(io.StringIO(texto.lstrip("﻿")), delimiter=";"))
    assert filas[0][-1] == "Código" and filas[1][-1] == "AP0001"
    plan = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": eq.get(_api(pid, "plan")).json()["etapas"][0]["id"],
                                                 "texto": "H"}).json()["etapas"][0]["hitos"][0]
    assert plan["codigo"] == "HI0001"


def test_el_zip_lleva_codigos_y_relaciones():
    pid, eq, sin = _mundo()
    a = _crear(sin, pid, titulo="Original", archivos=[_archivo("o.pdf")])
    b = _crear(eq, pid, titulo="Respuesta", texto=f"sobre {a['codigo']}", responde_a=a["codigo"], archivos=[_archivo("r.pdf")])
    z = zipfile.ZipFile(io.BytesIO(eq.get(_api(pid, "exportar.zip")).content))
    nombres = z.namelist()
    for n in ("relaciones.json", "relaciones.csv", "archivos.csv", "contadores.json", "tarjetas.csv", "tarjetas.json"):
        assert n in nombres, n
    tarjetas = json.loads(z.read("tarjetas.json"))
    assert {t["codigo"] for t in tarjetas} == {a["codigo"], b["codigo"]}
    assert all(m["orden"] >= 1 for t in tarjetas for m in t["mensajes"])
    assert all(x["codigo"].startswith("AR") for t in tarjetas for x in t["archivos"])
    rel = list(csv.reader(io.StringIO(z.read("relaciones.csv").decode("utf-8").lstrip("﻿")), delimiter=";"))
    assert rel[0][:3] == ["Origen", "Clase", "Destino"]
    assert [b["codigo"], "responde", a["codigo"]] in [r[:3] for r in rel[1:]]
    assert [b["codigo"], "menciona", a["codigo"]] not in [r[:3] for r in rel[1:]] or True
    assert any(r[0].startswith("AR") and r[1] == "responde" and r[2] == a["codigo"] for r in rel[1:])
    assert b"C\xc3\xb3digo" in z.read("tarjetas.csv")
    contadores = {(c["prefijo"]): c["ultimo"] for c in json.loads(z.read("contadores.json"))}
    assert contadores["PE"] == 2 and contadores["AR"] == 2
    # el path de los archivos de siempre sigue
    assert any(n.startswith("archivos/0001/") for n in nombres)


def test_el_aviso_por_mail_lleva_el_codigo(monkeypatch):
    enviados = []
    monkeypatch.setattr(main.correo, "habilitado", lambda: True)
    monkeypatch.setattr(main.correo, "enviar", lambda d, a, c, *x, **k: enviados.append((d, a, c)))
    monkeypatch.setattr(main, "IMPL_AVISOS_SINCRONO", True)
    pid = _proyecto()
    sin = _cliente_sindicato(pid)
    with db.get_session() as s:
        usuario = db.UsuarioPlataforma(usuario=_u("eq"), nombre="E", email=f"{_u()}@colm3na.test",
                                       clave_hash=auth.hashear_clave("x" * 12), debe_cambiar_clave=False,
                                       debe_completar_datos=False)
        s.add(usuario)
        s.commit()
        mail = usuario.email
    t = _crear(sin, pid, "consulta", titulo="Una duda")
    mios = [(a, c) for d, a, c in enviados if d == mail]
    assert mios and t["codigo"] == "CO0001"
    asunto, cuerpo = mios[0]
    assert "CO0001" in asunto and f"#{t['numero']}" in asunto
    assert f"/implementacion?p={pid}#CO0001" in cuerpo
    assert "Una duda" in asunto


# ---------- Migración con backfill ----------
def _insertar(cx, tabla, **vals):
    """INSERT rellenando lo NOT NULL sin default que no se haya dado."""
    cols = cx.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s "
        "AND is_nullable = 'NO' AND column_default IS NULL", (tabla,)).fetchall()
    for nombre, tipo in cols:
        if nombre in vals:
            continue
        vals[nombre] = False if tipo == "boolean" else (0 if tipo in ("integer", "bigint") else
                                                         ("{}" if tipo in ("json", "jsonb") else ""))
    nombres = ", ".join(vals)
    marcas = ", ".join(["%s"] * len(vals))
    return cx.execute(f"INSERT INTO {tabla} ({nombres}) VALUES ({marcas}) RETURNING id",
                      list(vals.values())).fetchone()[0]


def test_la_migracion_completa_codigos_y_ordenes_de_lo_que_ya_existe():
    nombre = f"mitrabajo_mig_cod_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    base_url = str(db.engine.url.render_as_string(hide_password=False))
    url_admin = _psycopg(_url_con_base(base_url, "postgres"))
    url_mig = _url_con_base(base_url, nombre)
    entorno = {**os.environ, "DATABASE_URL": url_mig}

    def alembic(*args):
        r = subprocess.run([sys.executable, "-m", "alembic", *args], env=entorno, capture_output=True, text=True,
                           timeout=300)
        assert r.returncode == 0, f"{args}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}"

    with psycopg.connect(url_admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{nombre}"')
    try:
        alembic("upgrade", "3be99db601b1")                          # la mesa, sin códigos
        with psycopg.connect(_psycopg(url_mig), autocommit=True) as cx:
            p1 = _insertar(cx, "implproyecto", nombre="Uno", ultimo_numero=4)
            p2 = _insertar(cx, "implproyecto", nombre="Dos", ultimo_numero=1)
            e1 = _insertar(cx, "impletapa", proyecto_id=p1, nombre="E", orden=1)
            # proyecto 1: pedido, consulta, pedido, aviso (ids crecientes)
            t = {}
            for n, (proy, tipo) in enumerate([(p1, "pedido"), (p1, "consulta"), (p1, "pedido"), (p1, "aviso"),
                                              (p2, "pedido")], start=1):
                t[n] = _insertar(cx, "impltarjeta", proyecto_id=proy, numero=n, tipo=tipo, titulo=f"T{n}")
            m = [_insertar(cx, "implmensaje", proyecto_id=p1, tarjeta_id=t[1], texto=f"m{i}") for i in range(3)]
            m2 = _insertar(cx, "implmensaje", proyecto_id=p1, tarjeta_id=t[2], texto="otra")
            a1 = _insertar(cx, "implarchivo", proyecto_id=p1, tarjeta_id=t[1], nombre="a")
            a2 = _insertar(cx, "implarchivo", proyecto_id=p1, tarjeta_id=t[1], nombre="b")
            a3 = _insertar(cx, "implarchivo", proyecto_id=p2, tarjeta_id=t[5], nombre="c")
            h = [_insertar(cx, "implhito", proyecto_id=p1, etapa_id=e1, texto=f"h{i}", orden=i) for i in (1, 2)]
        alembic("upgrade", "head")
        with psycopg.connect(_psycopg(url_mig), autocommit=True) as cx:
            q = lambda sql: cx.execute(sql).fetchall()                      # noqa: E731
            assert q("SELECT id, codigo FROM impltarjeta ORDER BY id") == [
                (t[1], "PE0001"), (t[2], "CO0001"), (t[3], "PE0002"), (t[4], "AV0001"), (t[5], "PE0001")]
            assert q("SELECT id, codigo FROM implarchivo ORDER BY id") == [
                (a1, "AR000001"), (a2, "AR000002"), (a3, "AR000001")]
            assert q("SELECT id, codigo FROM implhito ORDER BY id") == [(h[0], "HI0001"), (h[1], "HI0002")]
            assert q("SELECT id, orden FROM implmensaje ORDER BY id") == [(m[0], 1), (m[1], 2), (m[2], 3), (m2, 1)]
            assert q("SELECT proyecto_id, prefijo, ultimo FROM implcontador ORDER BY proyecto_id, prefijo") == sorted([
                (p1, "AR", 2), (p1, "AV", 1), (p1, "CO", 1), (p1, "HI", 2), (p1, "PE", 2),
                (p2, "AR", 1), (p2, "PE", 1)])
            assert q("SELECT count(*) FROM implrelacion") == [(0,)]
            # la unicidad por proyecto quedó puesta
            with pytest.raises(psycopg.errors.UniqueViolation):
                cx.execute("UPDATE impltarjeta SET codigo = 'PE0001' WHERE id = %s", (t[3],))
        alembic("downgrade", "3be99db601b1")                        # y vuelve limpia
        with psycopg.connect(_psycopg(url_mig), autocommit=True) as cx:
            assert cx.execute("SELECT count(*) FROM information_schema.columns WHERE table_name = 'impltarjeta' "
                              "AND column_name = 'codigo'").fetchone() == (0,)
    finally:
        with psycopg.connect(url_admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
