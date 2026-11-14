"""QA de seguridad y lógica de la Mesa de implementación (independiente).

Cada defecto del informe (docs/implementacion/QA-servidor.md) quedó corregido y su
test es un test normal. Las únicas excepciones son los dos de QA-12 (huecos de
numeración que delatan una nota interna), `xfail` NO estricto: es una decisión de
SDN pendiente, no un defecto a corregir sin su palabra.

Correr con: python -m pytest test_implementacion_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import io
import json
import threading
import time
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

import auth
import db
import entorno
import implementacion as im
import main

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
DEFINITIVA = "definitiva-2026"


@pytest.fixture(autouse=True)
def _sin_freno(monkeypatch):
    main._intentos_impl.clear()
    main._impl_ritmo.clear()
    # El freno de ritmo (QA-20) no es lo que se prueba en el resto: arriba de lo que usa un test.
    monkeypatch.setattr(main, "IMPL_RITMO_MAX", 10 ** 6)
    yield
    main._intentos_impl.clear()
    main._impl_ritmo.clear()


def _u(prefijo="x"):
    return f"{prefijo}{uuid.uuid4().hex[:8]}"


def _proyecto(nombre=None):
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, nombre or _u("Proy "), EQ).id


def _cliente_sindicato(pid, nombre="Carla Sindicato", raise_exc=False):
    mail = f"{_u()}@sindicato.test"
    with db.get_session() as s:
        u = db.impl_usuario_alta(s, pid, nombre, mail, "transitoria1", EQ)
        db.impl_usuario_cambiar_clave(s, u.id, "transitoria1", DEFINITIVA)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=raise_exc)
    r = c.post("/implementacion/ingresar", data={"mail": mail, "clave": DEFINITIVA})
    assert r.headers["location"] == "/implementacion", r.headers
    c.uid, c.mail = uid, mail
    return c


def _cliente_equipo(raise_exc=False, **campos):
    usuario = _u("eq")
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario, email=campos.pop("email", ""),
                                 clave_hash=auth.hashear_clave("x" * 12),
                                 debe_cambiar_clave=campos.pop("debe_cambiar_clave", False),
                                 debe_completar_datos=campos.pop("debe_completar_datos", False),
                                 activo=campos.pop("activo", True))
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=raise_exc)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    c.uid = uid
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


def _resp(c, pid, tid, files=None, **datos):
    return c.post(_api(pid, f"tarjetas/{tid}/responder"), data=datos, files=files)


def _det(c, pid, tid):
    r = c.get(_api(pid, f"tarjetas/{tid}"))
    assert r.status_code == 200, r.text
    return r.json()


def _pdf(nombre="a.pdf", datos=b"%PDF-1.4 x", mime="application/pdf"):
    return [("archivos", (nombre, datos, mime))]


def _id_inexistente():
    return 2_000_000_000


def _eq_url(ruta=""):
    return f"/api/entornos/implementacion/{ruta}".rstrip("/")


def _llevar(pid, eq, sin, tipo, creador, estado):
    """Una tarjeta del tipo creada por `creador` y llevada a `estado`."""
    c, otro = (eq, sin) if creador == "equipo" else (sin, eq)
    tid = _crear(c, pid, tipo, f"{tipo} {estado}", "texto")["id"]
    if estado in ("en_curso", "respondida", "cerrada") and tipo != "aviso":
        assert _resp(otro, pid, tid, estado_nuevo=estado, texto="paso").status_code == 200
    if estado in ("aprobada", "rechazada"):
        assert otro.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": estado == "aprobada"}).status_code == 200
    return tid


# =====================================================================
# 1. Aislamiento entre proyectos (RESISTE)
# =====================================================================
def test_ids_de_otro_proyecto_son_indistinguibles_de_un_id_inexistente():
    p1, e1, s1 = _mundo()
    p2, e2, s2 = _mundo()
    t2 = _crear(s2, p2, "pedido", "SECRETO-P2", "SECRETO-P2-TEXTO", archivos=_pdf("ajeno.pdf"))
    d2 = _det(e2, p2, t2["id"])
    aid2, acod2 = d2["archivos"][0]["id"], d2["archivos"][0]["codigo"]
    etapa2 = e2.get(_api(p2, "plan")).json()["etapas"][0]["id"]
    e2.post(_api(p2, "plan/hitos"), json={"etapa_id": etapa2, "texto": "hito p2"})
    hito2 = e2.get(_api(p2, "plan")).json()["etapas"][0]["hitos"][0]
    ap2 = _crear(s2, p2, "aprobacion", "ap2", "x")["id"]
    av2 = _crear(e2, p2, "aviso", "av2", "x")["id"]
    NE = _id_inexistente()
    diferencias = []

    def par(nombre, f):
        for cn, c in (("sind", s1), ("equipo", e1)):
            a = f(c, dict(t=t2["id"], a=aid2, h=hito2["id"], e=etapa2, ap=ap2, av=av2))
            b = f(c, dict(t=NE, a=NE, h=NE, e=NE, ap=NE, av=NE))
            if (a.status_code, a.text) != (b.status_code, b.text):
                diferencias.append((nombre, cn, a.status_code, a.text[:100], b.status_code, b.text[:100]))

    par("GET tarjeta", lambda c, i: c.get(_api(p1, f"tarjetas/{i['t']}")))
    par("responder", lambda c, i: _resp(c, p1, i["t"], texto="hola", files=_pdf()))
    par("responder estado", lambda c, i: _resp(c, p1, i["t"], estado_nuevo="cerrada"))
    par("aprobacion", lambda c, i: c.post(_api(p1, f"tarjetas/{i['ap']}/aprobacion"), json={"aprobar": True}))
    par("leido", lambda c, i: c.post(_api(p1, f"tarjetas/{i['av']}/leido")))
    par("reasignar", lambda c, i: c.post(_api(p1, f"tarjetas/{i['t']}/reasignar"),
                                         json={"responsable": "x", "responsable_lado": "equipo"}))
    par("GET archivo", lambda c, i: c.get(_api(p1, f"archivos/{i['a']}")))
    par("ficha", lambda c, i: c.get(_api(p1, f"archivos/{i['a']}/ficha")))
    par("borrar archivo", lambda c, i: c.post(_api(p1, f"archivos/{i['a']}/borrar")))
    for clave, cuerpo in (("tildar", {"hecho": True}), ("editar", {"texto": "zzz"}),
                          ("borrar", {"borrar": True}), ("orden", {"orden": 1})):
        par("hito " + clave, lambda c, i, cuerpo=cuerpo: c.post(_api(p1, f"plan/hitos/{i['h']}"), json=cuerpo))
    par("etapa", lambda c, i: c.post(_api(p1, f"plan/etapas/{i['e']}"), json={"nombre": "zzz"}))
    par("hito nuevo", lambda c, i: c.post(_api(p1, "plan/hitos"), json={"etapa_id": i["e"], "texto": "zzz"}))
    par("crear con etapa ajena", lambda c, i: c.post(_api(p1, "tarjetas"), data={
        "tipo": "pedido", "titulo": "t", "texto": "t", "etapa_id": i["e"]}))
    par("crear con hito ajeno", lambda c, i: c.post(_api(p1, "tarjetas"), data={
        "tipo": "pedido", "titulo": "t", "texto": "t", "hito_id": i["h"]}))
    par("crear responde_a ajeno", lambda c, i: c.post(_api(p1, "tarjetas"), data={
        "tipo": "pedido", "titulo": "t", "texto": "t", "responde_a": i["t"]}))
    assert diferencias == []
    # por código (tarjeta, archivo, hito, mensaje): buscar / responde_a / q devuelven lo mismo que un código inexistente
    for cod in (t2["codigo"], acod2, hito2["codigo"], t2["codigo"] + "-1"):
        for c in (s1, e1):
            assert c.get(_api(p1, "buscar"), params={"codigo": cod}).status_code == 404
            assert c.post(_api(p1, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t",
                                                      "responde_a": cod}).status_code == 400
            assert c.get(_api(p1, "tarjetas"), params={"vista": "todas", "q": cod}).json()["tarjetas"] == []
    for q in ("SECRETO-P2", "ajeno.pdf"):
        for c in (s1, e1):
            assert c.get(_api(p1, "tarjetas"), params={"vista": "todas", "q": q}).json()["tarjetas"] == []
    for c in (s1, e1):
        for ruta in ("carpetas?sentido=entrada", "carpetas?sentido=salida", "aprobaciones", "plan", "resumen"):
            txt = c.get(_api(p1, ruta)).text
            assert "SECRETO" not in txt and "ajeno.pdf" not in txt and "hito p2" not in txt, ruta
    # el sindicato de p1 no ve nada de p2 ni confirma que exista
    assert s1.get(_api(p2, "tarjetas")).text == s1.get(_api(_id_inexistente(), "tarjetas")).text
    assert s1.get(_api(p2, "exportar.zip")).status_code in (403, 404)


def test_usuarios_del_equipo_api_filtran_por_proyecto():
    p1, e1, _ = _mundo()
    p2 = _proyecto()
    s2 = _cliente_sindicato(p2)
    for ruta in ("restablecer-clave", "estado"):
        r = e1.post(_eq_url(f"proyectos/{p1}/usuarios/{s2.uid}/{ruta}"), json={"activo": False})
        assert r.status_code == 404, ruta        # usuario de p2 por la ruta de p1


# =====================================================================
# 2. Notas internas (I8) (RESISTE salvo el hueco de `orden`)
# =====================================================================
def _mundo_con_nota_interna():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "pedido", "Pedido base", "texto publico")
    otra = _crear(eq, pid, "pedido", "Otra", "otra")
    r = _resp(eq, pid, t["id"], texto=f"NOTA-SECRETA menciona {otra['codigo']}", solo_equipo="1",
              files=_pdf("interno-secreto.pdf", b"%PDF secreto"), datos_personales="1")
    assert r.status_code == 200
    d = _det(eq, pid, t["id"])
    arch = [a for a in d["archivos"] if a["nombre"] == "interno-secreto.pdf"][0]
    msg = [m for m in d["mensajes"] if m["solo_equipo"]][0]
    assert _resp(eq, pid, t["id"], texto="respuesta publica", estado_nuevo="respondida").status_code == 200
    return pid, eq, sin, t, otra, arch, msg


def test_la_nota_interna_no_llega_al_sindicato_por_ninguna_ruta():
    pid, eq, sin, t, otra, arch, msg = _mundo_con_nota_interna()
    ds = _det(sin, pid, t["id"])
    txt = json.dumps(ds)
    assert "NOTA-SECRETA" not in txt and "interno-secreto" not in txt and arch["codigo"] not in txt
    assert ds["tarjeta"]["n_mensajes"] == 2 and ds["tarjeta"]["n_archivos"] == 0
    assert ds["relacionadas"] == []
    assert [e["que"] for e in ds["eventos"]] == ["crear", "responder"]
    assert _det(sin, pid, otra["id"])["relacionadas"] == []          # la mención interna no se ve en la otra punta
    for ruta in (f"archivos/{arch['id']}", f"archivos/{arch['id']}/ficha"):
        assert sin.get(_api(pid, ruta)).status_code == 404
    assert sin.post(_api(pid, f"archivos/{arch['id']}/borrar")).status_code == 404
    for cod in (arch["codigo"], msg["codigo"]):
        assert sin.get(_api(pid, "buscar"), params={"codigo": cod}).status_code == 404
        assert sin.get(_api(pid, "tarjetas"), params={"vista": "todas", "q": cod}).json()["tarjetas"] == []
    assert sin.get(_api(pid, "tarjetas"), params={"vista": "todas", "q": "NOTA-SECRETA"}).json()["tarjetas"] == []
    for sentido in ("entrada", "salida"):
        assert "interno-secreto" not in sin.get(_api(pid, f"carpetas?sentido={sentido}")).text
    lista = sin.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"]
    assert {x["codigo"]: x["n_mensajes"] for x in lista}[t["codigo"]] == 2
    # el sindicato no puede mandar una nota interna, ni siquiera mezclada con un cambio de estado
    for extra in ({}, {"estado_nuevo": "cerrada"}):
        assert _resp(sin, pid, t["id"], texto="intento", solo_equipo="true", **extra).status_code == 403
    # y mencionar un código interno no lo revela ni deja una relación visible
    assert _resp(sin, pid, t["id"], texto=f"ver {msg['codigo']} y {arch['codigo']}").status_code == 200
    ds = _det(sin, pid, t["id"])
    refs = [m["refs"] for m in ds["mensajes"] if m["texto"].startswith("ver ")][0]
    assert all(r["existe"] is False and r["enlace"] == "" for r in refs)
    assert ds["relacionadas"] == []


def test_la_exportacion_es_solo_del_equipo():
    pid, eq, sin, *_ = _mundo_con_nota_interna()
    assert sin.get(_api(pid, "exportar.zip")).status_code == 403
    z = zipfile.ZipFile(io.BytesIO(eq.get(_api(pid, "exportar.zip")).content))
    assert any("NOTA-SECRETA" in z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".json"))


@pytest.mark.xfail(strict=False, reason="QA-12: decisión de SDN pendiente (el hueco de `orden` delata una nota interna)")
def test_el_sindicato_no_nota_huecos_en_la_numeracion_de_mensajes():
    pid, eq, sin, t, *_ = _mundo_con_nota_interna()
    ordenes = [m["orden"] for m in _det(sin, pid, t["id"])["mensajes"]]
    assert ordenes == list(range(1, len(ordenes) + 1)), ordenes     # hoy: [1, 3]


@pytest.mark.xfail(strict=False, reason="QA-12: decisión de SDN pendiente (el hueco del contador AR delata un archivo interno)")
def test_el_sindicato_no_nota_huecos_en_los_codigos_de_archivo():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, archivos=_pdf("publico1.pdf"))
    _resp(eq, pid, t["id"], texto="nota", solo_equipo="1", files=_pdf("interno.pdf"))
    _resp(eq, pid, t["id"], texto="publico", files=_pdf("publico2.pdf"))
    nums = sorted(int(a["codigo"][2:]) for a in _det(sin, pid, t["id"])["archivos"])
    assert nums == list(range(nums[0], nums[0] + len(nums))), nums    # hoy: [1, 3]


# =====================================================================
# 3. Archivos (I5)
# =====================================================================
def test_archivos_con_datos_personales_descarga_registrada_y_borrado_con_constancia():
    pid, eq, sin = _mundo()
    sin2 = _cliente_sindicato(pid, "Otro Usuario")
    t = _crear(sin, pid)
    assert _resp(sin, pid, t["id"], texto="dp", files=_pdf("dni.pdf", b"%PDF dni"), datos_personales="1").status_code == 200
    a = [x for x in _det(eq, pid, t["id"])["archivos"] if x["nombre"] == "dni.pdf"][0]
    assert sin2.get(_api(pid, f"archivos/{a['id']}")).status_code == 403            # otro del mismo sindicato
    assert sin.get(_api(pid, f"archivos/{a['id']}")).status_code == 200             # quien lo subió
    assert eq.get(_api(pid, f"archivos/{a['id']}")).status_code == 200              # el equipo
    assert sin2.post(_api(pid, f"archivos/{a['id']}/borrar")).status_code == 403
    with db.get_session() as s:
        assert len(db.impl_descargas(s, pid, a["id"])) == 2
    assert sin.post(_api(pid, f"archivos/{a['id']}/borrar")).status_code == 200
    assert eq.get(_api(pid, f"archivos/{a['id']}")).status_code == 410
    assert sin.post(_api(pid, f"archivos/{a['id']}/borrar")).status_code == 410
    with db.get_session() as s:
        assert s.exec(db.select(db.ImplArchivo.datos).where(db.ImplArchivo.id == a["id"])).first() is None
        assert s.get(db.ImplArchivo, a["id"]).nombre == "dni.pdf"                   # la constancia queda
    z = zipfile.ZipFile(io.BytesIO(eq.get(_api(pid, "exportar.zip")).content))
    assert not [n for n in z.namelist() if n.startswith("archivos/") and n.endswith("dni.pdf")]
    assert "dni.pdf" in z.read("archivos.csv").decode("utf-8")


def test_nombres_y_mimes_maliciosos_no_inyectan_cabeceras_ni_se_sirven_en_linea():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    nombres = ["../../etc/passwd", 'a"; filename="b.exe', "ñandú é中文.pdf", "..", "con;punto.pdf", "x" * 500 + ".pdf"]
    for n in nombres:
        assert _resp(sin, pid, t["id"], texto="adj", files=[("archivos", (n, b"d", "text/plain"))]).status_code == 200
    for mime in ("text/html", "image/svg+xml", "application/xhtml+xml", "TEXT/HTML", "application/javascript"):
        assert _resp(sin, pid, t["id"], texto="m", files=[("archivos", ("m.bin", b"<script>1</script>", mime))]).status_code == 200
    for a in _det(eq, pid, t["id"])["archivos"]:
        r = eq.get(_api(pid, f"archivos/{a['id']}"))
        cd = r.headers["content-disposition"]
        assert cd.startswith("attachment;") and "\r" not in cd and "\n" not in cd
        assert "/" not in a["nombre"] and len(a["nombre"]) <= 200
        assert r.headers["x-content-type-options"] == "nosniff" and "sandbox" in r.headers["content-security-policy"]
        ct = r.headers["content-type"].lower()
        assert "html" not in ct and "svg" not in ct and "xml" not in ct and "javascript" not in ct
    assert im.nombre_seguro("a\r\nSet-Cookie: x") == "aSet-Cookie: x"


def test_topes_de_archivos():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    assert _resp(sin, pid, t["id"], texto="v", files=[("archivos", ("v.pdf", b"", "application/pdf"))]).status_code == 400
    r = _resp(sin, pid, t["id"], texto="g", files=[("archivos", ("g.bin", b"0" * (20 * 1024 * 1024 + 1), "application/octet-stream"))])
    assert r.status_code == 413
    r = _resp(sin, pid, t["id"], texto="g", files=[("archivos", (f"g{i}.bin", b"0" * (14 * 1024 * 1024), "application/octet-stream")) for i in range(3)])
    assert r.status_code == 413
    r = _resp(sin, pid, t["id"], texto="g", files=[("archivos", (f"g{i}.bin", b"0" * 10, "application/octet-stream")) for i in range(6)])
    assert r.status_code == 400
    antes = len(eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"])
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t"},
                 files=[("archivos", ("v.pdf", b"", "application/pdf"))])
    assert r.status_code == 400
    assert len(eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"]) == antes   # no se crea la tarjeta


def test_exportar_zip_sin_zip_slip_ni_formulas_en_los_csv():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "pedido", '=HYPERLINK("http://x")', "x")
    for n in ("../../../etc/passwd", "..\\..\\evil.exe", "=cmd|' /C calc'!A0.csv"):
        assert _resp(sin, pid, t["id"], texto="adj", files=[("archivos", (n, b"d", "text/plain"))]).status_code == 200
    z = zipfile.ZipFile(io.BytesIO(eq.get(_api(pid, "exportar.zip")).content))
    for n in z.namelist():
        assert not n.startswith("/") and ".." not in n.split("/") and "\\" not in n, n
    for csvn in ("tarjetas.csv", "archivos.csv"):
        for linea in z.read(csvn).decode("utf-8-sig").splitlines()[1:]:
            for celda in linea.split(";"):
                assert celda[:1] not in ("=", "+", "@") and not celda.startswith('"='), (csvn, celda)
    ap = _crear(sin, pid, "aprobacion", "=1+1", "x")
    assert "'=1+1" in sin.get(_api(pid, "aprobaciones.csv")).content.decode("utf-8")


def test_una_subida_sin_sesion_no_se_recibe_entera(monkeypatch):
    pid, eq, sin = _mundo()
    visto = {}
    original = main._impl_autorizar

    def espia(request, pid_):
        form = getattr(request, "_form", None)
        visto["size"] = form.getlist("archivos")[0].size if form and form.getlist("archivos") else None
        return original(request, pid_)
    monkeypatch.setattr(main, "_impl_autorizar", espia)
    anon = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    r = anon.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t"},
                  files=[("archivos", ("g.bin", b"0" * (3 * 1024 * 1024), "application/octet-stream"))])
    assert r.status_code == 401
    assert not visto.get("size")          # hoy: 3145728 (ya estaba toda en disco/memoria)


def test_un_archivo_que_falla_no_deja_el_responder_a_medias():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    cuerpo = (b"--abc\r\nContent-Disposition: form-data; name=\"texto\"\r\n\r\nhola\r\n--abc\r\n"
              b"Content-Disposition: form-data; name=\"estado_nuevo\"\r\n\r\nrespondida\r\n--abc\r\n"
              b"Content-Disposition: form-data; name=\"archivos\"; filename=\"a.pdf\"\r\n"
              b"Content-Type: te\x00xt/plain\r\n\r\ndatos\r\n--abc--\r\n")
    r = eq.post(_api(pid, f"tarjetas/{t['id']}/responder"), content=cuerpo,
                headers={"content-type": "multipart/form-data; boundary=abc"})
    d = _det(eq, pid, t["id"])
    assert r.status_code < 500
    assert (d["tarjeta"]["estado"], len(d["mensajes"]), len(d["archivos"])) in (("abierta", 1, 0), ("respondida", 2, 1))


def test_un_archivo_sin_nombre_no_se_pierde_en_silencio():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    r = _resp(sin, pid, t["id"], texto="con adjunto", files=[("archivos", ("   ", b"datos", "text/plain"))])
    assert r.status_code != 200 or len(_det(eq, pid, t["id"])["archivos"]) == 1


# =====================================================================
# 4. Aprobaciones
# =====================================================================
def test_doble_resolucion_concurrente_deja_una_sola_resolucion():
    pid, eq, sin = _mundo()
    tid = _crear(sin, pid, "aprobacion", "Aprobar A", "x")["id"]
    res = []

    def go(aprobar):
        c = _cliente_equipo()
        res.append(c.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": aprobar, "texto": "t"}).status_code)
    ths = [threading.Thread(target=go, args=(i % 2 == 0,)) for i in range(6)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    assert sorted(res) == [200, 409, 409, 409, 409, 409]
    d = _det(eq, pid, tid)
    assert len([e for e in d["eventos"] if e["que"] == "resolver"]) == 1 and len(d["mensajes"]) == 2


def test_una_aprobacion_resuelta_no_se_toca_por_ninguna_ruta_de_hilo():
    pid, eq, sin = _mundo()
    tid = _crear(sin, pid, "aprobacion", "A", "x")["id"]
    assert eq.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": True}).status_code == 200
    assert _resp(eq, pid, tid, texto="x").status_code == 409
    assert _resp(sin, pid, tid, estado_nuevo="abierta").status_code == 409
    assert _resp(eq, pid, tid, texto="x", files=_pdf()).status_code == 409
    assert eq.post(_api(pid, f"tarjetas/{tid}/reasignar"), json={"responsable": "x", "responsable_lado": "equipo"}).status_code == 409
    assert eq.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": False}).status_code == 409
    p = _crear(sin, pid)
    assert eq.post(_api(pid, f"tarjetas/{p['id']}/aprobacion"), json={"aprobar": True}).status_code == 400   # no es aprobación
    ap = _crear(sin, pid, "aprobacion", "B", "x")
    for body in ({"aprobar": "true"}, {"aprobar": 1}, {}, {"aprobar": None}):
        assert eq.post(_api(pid, f"tarjetas/{ap['id']}/aprobacion"), json=body).status_code == 400


def test_quien_pidio_una_aprobacion_no_puede_aprobarla_tomandola_en_curso():
    pid, eq, sin = _mundo()
    tid = _crear(eq, pid, "aprobacion", "Aprobar X", "texto")["id"]
    assert _resp(eq, pid, tid, estado_nuevo="en_curso", texto="la tomo").status_code == 200
    r = eq.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": True})
    assert r.status_code == 403, (r.status_code, "el solicitante se aprobó a sí mismo")


def test_el_solicitante_no_aprueba_lo_que_pidio_tras_una_respuesta():
    pid, eq, sin = _mundo()
    tid = _crear(sin, pid, "aprobacion", "Aprobar Y", "texto")["id"]
    assert _resp(eq, pid, tid, estado_nuevo="respondida", texto="¿seguro?").status_code == 200
    ac = _det(sin, pid, tid)["acciones"]
    r = sin.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": True})
    assert not ac["aprobar"] and r.status_code == 403, (ac["aprobar"], r.status_code)


def test_no_se_borra_un_adjunto_de_una_aprobacion_resuelta():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, "aprobacion", "A", "x", archivos=_pdf("contrato.pdf"))
    aid = _det(eq, pid, t["id"])["archivos"][0]["id"]
    assert eq.post(_api(pid, f"tarjetas/{t['id']}/aprobacion"), json={"aprobar": True}).status_code == 200
    assert sin.post(_api(pid, f"archivos/{aid}/borrar")).status_code == 409


# =====================================================================
# 5. Estados, turnos y `acciones`
# =====================================================================
def test_acciones_coincide_con_lo_que_el_servidor_acepta():
    """Matriz tipo x estado x creador x lado. Todo POST se compara con `acciones`.
    (`reasignar` tiene su propio test: es la única discrepancia hallada.)"""
    pid, eq, sin = _mundo()
    estados_por_tipo = {"pedido": ["abierta", "en_curso", "respondida", "cerrada"],
                        "aprobacion": ["abierta", "en_curso", "respondida", "aprobada", "rechazada"],
                        "aviso": ["cerrada"]}
    discrepancias = []
    for tipo, estados in estados_por_tipo.items():
        for est in estados:
            for creador in ("equipo", "sindicato"):
                for lado in ("equipo", "sindicato"):
                    actor = eq if lado == "equipo" else sin

                    def probar(nombre, esperado, hacer):
                        t2 = _llevar(pid, eq, sin, tipo, creador, est)
                        r = hacer(actor, t2)
                        if (r.status_code == 200) != esperado:
                            discrepancias.append((tipo, est, creador, lado, nombre, esperado, r.status_code))
                    ac = _det(actor, pid, _llevar(pid, eq, sin, tipo, creador, est))["acciones"]
                    probar("responder", ac["responder"], lambda c, t: _resp(c, pid, t, texto="hola"))
                    for e in ("en_curso", "respondida", "cerrada", "abierta"):
                        esp = e in [x["id"] for x in ac["estados"]] or (e == "abierta" and ac["reabrir"])
                        probar("estado:" + e, esp, lambda c, t, e=e: _resp(c, pid, t, estado_nuevo=e))
                    probar("nota", ac["solo_equipo"], lambda c, t: _resp(c, pid, t, texto="n", solo_equipo="1"))
                    probar("aprobar", ac["aprobar"], lambda c, t: c.post(_api(pid, f"tarjetas/{t}/aprobacion"), json={"aprobar": True}))
                    probar("subir", ac["subir"], lambda c, t: _resp(c, pid, t, texto="a", files=_pdf()))
    assert discrepancias == []


@pytest.mark.parametrize("tipo,estado", [("pedido", "cerrada"), ("aviso", "cerrada")])
def test_reasignar_respeta_acciones(tipo, estado):
    pid, eq, sin = _mundo()
    tid = _llevar(pid, eq, sin, tipo, "sindicato", estado)
    assert _det(sin, pid, tid)["acciones"]["reasignar"] is False
    r = sin.post(_api(pid, f"tarjetas/{tid}/reasignar"), json={"responsable": "X", "responsable_lado": "sindicato"})
    assert r.status_code != 200


def test_transiciones_invalidas_y_estados_inventados():
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    for estado in ("aprobada", "rechazada", "foo", "ABIERTA"):
        assert _resp(eq, pid, t["id"], estado_nuevo=estado).status_code == 409
    assert _resp(eq, pid, t["id"], estado_nuevo="abierta").status_code == 400      # ya está abierta y no hay texto
    assert _resp(eq, pid, t["id"], estado_nuevo="cerrada").status_code == 200
    assert _resp(eq, pid, t["id"], texto="más").status_code == 409                     # responder sobre cerrada
    assert _resp(eq, pid, t["id"], estado_nuevo="en_curso").status_code == 409
    assert _resp(sin, pid, t["id"], estado_nuevo="abierta").status_code == 200         # reabrir
    av = _crear(eq, pid, "aviso", "av", "x")
    assert _resp(sin, pid, av["id"], texto="no se responde").status_code == 400


# =====================================================================
# 6. Acceso
# =====================================================================
def test_sesiones_de_usuarios_dados_de_baja_o_con_clave_restablecida_dejan_de_valer():
    pid = _proyecto()
    sin = _cliente_sindicato(pid)
    assert sin.get(_api(pid, "tarjetas")).status_code == 200
    with db.get_session() as s:
        db.impl_usuario_activar(s, pid, sin.uid, False, EQ)
    assert sin.get(_api(pid, "tarjetas")).status_code == 401
    with db.get_session() as s:
        db.impl_usuario_activar(s, pid, sin.uid, True, EQ)
    assert sin.get(_api(pid, "tarjetas")).status_code == 200
    with db.get_session() as s:
        db.impl_usuario_restablecer(s, pid, sin.uid, EQ)
    assert sin.get(_api(pid, "tarjetas")).status_code == 401           # clave transitoria: la cookie vieja no sirve
    sin2 = _cliente_sindicato(pid)
    with db.get_session() as s:
        p = s.get(db.ImplProyecto, pid)
        p.activo = False
        s.add(p)
        s.commit()
    assert sin2.get(_api(pid, "tarjetas")).status_code == 401
    r = sin2.post("/implementacion/ingresar", data={"mail": sin2.mail, "clave": DEFINITIVA})
    assert r.headers["location"] == "/implementacion/ingresar?error=login"


def test_cookies_falsificadas_o_de_otro_rol_no_abren_nada():
    pid, p2 = _proyecto(), _proyecto()
    sin, s2 = _cliente_sindicato(pid), _cliente_sindicato(p2)
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    for token in (auth.crear_sesion("sindicato", sin.uid, pid), auth.crear_sesion("implementacion", sin.uid, pid + 999),
                  auth.crear_sesion("implementacion", s2.uid, pid), "basura.basura", ""):
        c.cookies.set("sesion_implementacion", token)
        assert c.get(_api(pid, "tarjetas")).status_code == 401
    # el equipo gana si trae las dos; y el sindicato no puede usar la API del equipo
    eq = _cliente_equipo()
    eq.cookies.set("sesion_implementacion", sin.cookies.get("sesion_implementacion"))
    assert eq.get(_api(p2, "tarjetas")).status_code == 200
    assert sin.get(_eq_url("proyectos")).status_code == 403
    assert sin.post(_eq_url(f"proyectos/{pid}/usuarios/{sin.uid}/restablecer-clave")).status_code == 403
    assert sin.post(_eq_url(f"proyectos/{pid}/hitos-semilla")).status_code == 403


def test_login_no_distingue_mail_existente_ni_cuenta_inactiva_y_tiene_freno():
    pid = _proyecto()
    sin = _cliente_sindicato(pid)
    c = TestClient(main.app, follow_redirects=False)
    a = c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": "mala"})
    b = c.post("/implementacion/ingresar", data={"mail": "no@existe.com", "clave": "mala"})
    assert (a.status_code, a.headers["location"]) == (b.status_code, b.headers["location"])
    with db.get_session() as s:
        db.impl_usuario_activar(s, pid, sin.uid, False, EQ)
    d = c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": DEFINITIVA})
    assert d.headers["location"] == a.headers["location"]
    with db.get_session() as s:
        db.impl_usuario_activar(s, pid, sin.uid, True, EQ)
    main._intentos_impl.clear()
    locs = [c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": f"mala{i}"}).headers["location"]
            for i in range(12)]
    assert locs[-1].endswith("error=espera")
    assert c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": DEFINITIVA}).headers["location"].endswith("error=espera")


def test_el_freno_no_se_reinicia_con_un_login_propio_exitoso():
    pid = _proyecto()
    victima, atacante = _cliente_sindicato(pid), _cliente_sindicato(pid)
    c = TestClient(main.app, follow_redirects=False)
    main._intentos_impl.clear()
    vistos = []
    for ronda in range(3):
        for i in range(8):
            vistos.append(c.post("/implementacion/ingresar", data={"mail": victima.mail, "clave": f"x{ronda}{i}"}).headers["location"])
        c.post("/implementacion/ingresar", data={"mail": atacante.mail, "clave": DEFINITIVA})
    assert any(v.endswith("error=espera") for v in vistos)       # hoy: 24 intentos sin una sola espera


@pytest.mark.parametrize("kw", [{"activo": False}, {"debe_cambiar_clave": True}, {"debe_completar_datos": True}])
def test_la_api_del_equipo_rechaza_usuarios_de_plataforma_inactivos_o_pendientes(kw):
    c = _cliente_equipo(**kw)
    assert c.get(_api(_proyecto(), "tarjetas")).status_code == 401           # la mesa los rechaza
    assert c.get(_eq_url("proyectos")).status_code in (401, 403)             # hoy: 200


def test_en_demo_todo_es_404(monkeypatch):
    pid, eq, sin = _mundo()
    rutas = [(r.path, sorted(r.methods - {"HEAD", "OPTIONS"})) for r in main.app.routes
             if hasattr(r, "methods") and "implementacion" in r.path]
    assert len(rutas) >= 30
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    anon = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    for path, mets in rutas:
        url = (path.replace("{pid}", str(pid)).replace("{proyecto_id}", str(pid)).replace("{tid}", "1")
               .replace("{aid}", "1").replace("{hid}", "1").replace("{eid}", "1").replace("{usuario_id}", "1"))
        for m in mets:
            for c in (eq, sin, anon):
                assert c.request(m, url, json={} if m == "POST" else None).status_code == 404, (m, path)
    r = eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t"}, files=_pdf())
    assert r.status_code == 404


def test_cookies_de_la_mesa_son_httponly_y_samesite():
    pid = _proyecto()
    c = _cliente_sindicato(pid)
    r = TestClient(main.app, follow_redirects=False).post("/implementacion/ingresar", data={"mail": c.mail, "clave": DEFINITIVA})
    cab = r.headers["set-cookie"].lower()
    assert "httponly" in cab and "samesite=lax" in cab


def test_el_enlace_del_aviso_no_depende_del_header_host(monkeypatch):
    enviados = []
    monkeypatch.setattr(main.correo, "habilitado", lambda: True)
    monkeypatch.setattr(main.correo, "enviar", lambda d, a, t: enviados.append((d, a, t)) or True)
    monkeypatch.setattr(main, "IMPL_AVISOS_SINCRONO", True)
    mail_eq = f"{_u('eq')}@colm3na.test"
    _cliente_equipo(email=mail_eq)
    pid = _proyecto()
    sin = _cliente_sindicato(pid)
    sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "Hola", "texto": "x"}, headers={"host": "evil.example"})
    cuerpos = [c for d, a, c in enviados if d == mail_eq]
    assert cuerpos and all("evil.example" not in c for c in cuerpos)


# =====================================================================
# 7. Códigos y relaciones
# =====================================================================
def test_reconocimiento_de_codigos():
    ex = im.extraer_codigos
    assert ex("pe0004 PE0004-3 ar000123 hi0001") == ["PE0004", "PE0004-3", "AR000123", "HI0001"]
    for malo in ("PE00041", "XPE0004", "PE0004x", "PE_0004", "PE 0004", "PE0000", "AR0001", "HI0001-2", "PE0004-0"):
        assert ex(malo) == [] or malo == "PE0004-0", malo
    assert ex("PE0004-03") == ["PE0004-3"] and ex("(PE0004).") == ["PE0004"]
    assert ex("PE0004 " * 1000) == ["PE0004"]


@pytest.mark.parametrize("donde", ["crear_texto", "crear_titulo", "buscar", "q", "responder"])
def test_un_codigo_con_i_turca_no_rompe(donde):
    pid, eq, sin = _mundo()
    t = _crear(eq, pid)
    v = "ver Hİ0001"
    r = {"crear_texto": lambda: eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": v}),
         "crear_titulo": lambda: eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": v, "texto": "t"}),
         "buscar": lambda: eq.get(_api(pid, "buscar"), params={"codigo": "Hİ0001"}),
         "q": lambda: eq.get(_api(pid, "tarjetas"), params={"q": "Hİ0001"}),
         "responder": lambda: _resp(eq, pid, t["id"], texto=v)}[donde]()
    assert r.status_code < 500


def test_relacion_interna_pasa_a_publica_al_mencionarse_en_publico_y_la_autorreferencia_se_ignora():
    pid, eq, sin = _mundo()
    a, b = _crear(sin, pid, "pedido", "A", "x"), _crear(sin, pid, "pedido", "B", "x")
    _resp(eq, pid, a["id"], texto=f"nota {b['codigo']}", solo_equipo="1")
    assert _det(sin, pid, a["id"])["relacionadas"] == [] and _det(sin, pid, b["id"])["relacionadas"] == []
    _resp(eq, pid, a["id"], texto=f"ahora publico {b['codigo']}")
    assert [x["codigo"] for x in _det(sin, pid, a["id"])["relacionadas"]] == [b["codigo"]]
    _resp(eq, pid, a["id"], texto=f"yo mismo {a['codigo']} y {a['codigo']}-1")
    assert [x["codigo"] for x in _det(eq, pid, a["id"])["relacionadas"]] == [b["codigo"]]


def test_hito_borrado_no_libera_su_codigo_ni_se_encuentra():
    pid, eq, sin = _mundo()
    etapa = eq.get(_api(pid, "plan")).json()["etapas"][0]["id"]
    h = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": "H1"}).json()["etapas"][0]["hitos"][0]
    c = _crear(sin, pid, "pedido", "con hito", "x", hito_id=h["id"])
    assert eq.post(_api(pid, f"plan/hitos/{h['id']}"), json={"borrar": True}).status_code == 200
    assert eq.get(_api(pid, "buscar"), params={"codigo": h["codigo"]}).status_code == 404
    assert _det(eq, pid, c["id"])["tarjeta"]["hito_id"] is None
    nuevo = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": "H2"}).json()["etapas"][0]["hitos"]
    assert [x["codigo"] for x in nuevo] == ["HI0002"]


def test_creacion_concurrente_no_repite_numeros_ni_codigos():
    pid, eq, sin = _mundo()
    res = []

    def go(i):
        res.append(_cliente_equipo().post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": f"t{i}", "texto": "x"},
                                          files=_pdf()).status_code)
    ths = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    assert res == [200] * 8
    ts = eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"]
    assert sorted(t["numero"] for t in ts) == list(range(1, 9)) and len({t["codigo"] for t in ts}) == 8


def test_hitos_concurrentes_tienen_orden_unico():
    pid, eq, _ = _mundo()
    etapa = eq.get(_api(pid, "plan")).json()["etapas"][0]["id"]

    def go(i):
        _cliente_equipo().post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": f"h{i}"})
    ths = [threading.Thread(target=go, args=(i,)) for i in range(10)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    ordenes = [h["orden"] for h in eq.get(_api(pid, "plan")).json()["etapas"][0]["hitos"]]
    assert sorted(ordenes) == list(range(1, 11)), ordenes


# =====================================================================
# 8. Reglas del proyecto: entradas raras -> nunca un 500
# =====================================================================
def _lanzadores(pid, eq, sin, t, ap, etapa, hito):
    """{nombre: f(valor) -> response} para cada campo de texto de cada POST/GET."""
    return {
        "crear.titulo": lambda v: eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": v, "texto": "t"}),
        "crear.texto": lambda v: eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": v}),
        "responder.texto": lambda v: _resp(eq, pid, t, texto=v),
        "lista.q": lambda v: eq.get(_api(pid, "tarjetas"), params={"q": v}),
        "aprobacion.texto": lambda v: eq.post(_api(pid, f"tarjetas/{ap}/aprobacion"), json={"aprobar": True, "texto": v}),
        "reasignar.responsable": lambda v: eq.post(_api(pid, f"tarjetas/{t}/reasignar"), json={"responsable": v, "responsable_lado": "equipo"}),
        "plan.hito.texto": lambda v: eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": v}),
        "plan.hito.editar": lambda v: eq.post(_api(pid, f"plan/hitos/{hito}"), json={"texto": v}),
        "plan.etapa": lambda v: eq.post(_api(pid, f"plan/etapas/{etapa}"), json={"nombre": v}),
        "login.mail": lambda v: TestClient(main.app, follow_redirects=False, raise_server_exceptions=False).post(
            "/implementacion/ingresar", data={"mail": v, "clave": "x"}),
        "equipo.proyecto": lambda v: eq.post(_eq_url("proyectos"), json={"nombre": v}),
        "equipo.usuario": lambda v: eq.post(_eq_url(f"proyectos/{pid}/usuarios"), json={"nombre": v, "mail": f"{_u()}@a.com", "clave_inicial": "abcdef"}),
    }


def _entorno_fuzz():
    pid = _proyecto()
    eq = _cliente_equipo()
    sin = _cliente_sindicato(pid)
    t = _crear(sin, pid)["id"]
    ap = _crear(sin, pid, "aprobacion", "ap", "x")["id"]
    etapa = eq.get(_api(pid, "plan")).json()["etapas"][0]["id"]
    hito = eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": "H"}).json()["etapas"][0]["hitos"][0]["id"]
    return pid, eq, sin, t, ap, etapa, hito


NUL_RUTAS = ["crear.titulo", "crear.texto", "responder.texto", "lista.q", "aprobacion.texto", "reasignar.responsable",
             "plan.hito.texto", "plan.hito.editar", "plan.etapa", "login.mail", "equipo.proyecto", "equipo.usuario"]


@pytest.mark.parametrize("ruta", NUL_RUTAS)
def test_un_nul_en_un_texto_no_da_500(ruta):
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    assert _lanzadores(pid, eq, sin, t, ap, etapa, hito)[ruta]("a\x00b").status_code < 500


def test_textos_raros_no_dan_500():
    """Emoji, comodines de LIKE, comillas, saltos de línea, 1 MB de texto donde no hay tope."""
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    lanz = _lanzadores(pid, eq, sin, t, ap, etapa, hito)
    for nombre, f in lanz.items():
        for v in ("😀" * 50, "%", "_", "\\", "'; DROP TABLE impltarjeta;--", "<script>alert(1)</script>", "\r\n", "ñ" * 50):
            r = f(v)
            assert r.status_code < 500, (nombre, repr(v), r.status_code)


BIG = ["2147483648", "99999999999", str(10 ** 30)]


@pytest.mark.parametrize("big", BIG)
def test_ids_gigantes_no_dan_500(big):
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    resp = [
        eq.get(_api(pid, f"tarjetas/{big}")), sin.get(_api(pid, f"tarjetas/{big}")),
        _resp(eq, pid, int(big), texto="x"), eq.get(_api(pid, f"archivos/{big}")),
        eq.post(_api(pid, f"archivos/{big}/borrar")), eq.post(_api(pid, f"plan/hitos/{big}"), json={"hecho": True}),
        eq.get(_api(pid, "tarjetas"), params={"etapa_id": big}),
        eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t", "etapa_id": big}),
        eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t", "responde_a": big}),
        eq.get(f"/api/implementacion/p/{big}/resumen"), eq.get(f"/implementacion?p={big}"),
    ]
    assert [r.status_code for r in resp if r.status_code >= 500] == []


def test_json_y_multipart_malformados_no_dan_500():
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    for body in (b"", b"null", b"[]", b'"x"', b"{", b"123", b"\xff\xfe"):
        for ruta in (f"tarjetas/{ap}/aprobacion", f"tarjetas/{t}/reasignar", "plan/hitos", f"plan/hitos/{hito}", f"plan/etapas/{etapa}"):
            r = eq.post(_api(pid, ruta), content=body, headers={"content-type": "application/json"})
            assert r.status_code < 500, (ruta, body, r.status_code)
        assert eq.post(_eq_url("proyectos"), content=body, headers={"content-type": "application/json"}).status_code < 500
    for ct, body in (("multipart/form-data", b"x"), ("multipart/form-data; boundary=", b"x"),
                     ("multipart/form-data; boundary=abc", b"--abc\r\nContent-Disposition: form-data; name=\"archivos\"; filename=\"a\"\r\n\r\ndatos"),
                     ("multipart/form-data; boundary=abc", b"--abc\r\nContent-Disposition: form-data; name=\"archivos\"\r\n\r\ntexto\r\n--abc--\r\n"),
                     ("application/x-www-form-urlencoded", b"%ff%fe=%80")):
        for ruta in ("tarjetas", f"tarjetas/{t}/responder"):
            assert eq.post(_api(pid, ruta), content=body, headers={"content-type": ct}).status_code < 500, (ct, ruta)


@pytest.mark.parametrize("ruta", ["aprobacion", "reasignar", "hito"])
def test_los_textos_libres_tienen_tope(ruta):
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    big = "A" * 200_000
    r = {"aprobacion": lambda: sin.post(_api(pid, f"tarjetas/{_crear(eq, pid, 'aprobacion', 'b', 'x')['id']}/aprobacion"),
                                        json={"aprobar": True, "texto": big}),
         "reasignar": lambda: sin.post(_api(pid, f"tarjetas/{t}/reasignar"), json={"responsable": big, "responsable_lado": "sindicato"}),
         "hito": lambda: eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": big})}[ruta]()
    assert r.status_code == 400


@pytest.mark.parametrize("fecha,iso", [("2026-1-5", "2026-01-05"), ("２０２６-01-01", "2026-01-01")])
def test_fecha_limite_se_normaliza_a_iso(fecha, iso):
    pid, eq, sin = _mundo()
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t", "fecha_limite": fecha})
    assert r.status_code == 400 or r.json()["tarjeta"]["fecha_limite"] == iso


def test_vencida_compara_bien_con_iso():
    assert im.vencida("2026-01-05", "abierta", "2026-01-10") is True
    assert im.vencida("2026-01-05", "cerrada", "2026-01-10") is False
    assert im.vencida("", "abierta", "2026-01-10") is False


# =====================================================================
# 9. Resguardos de I3
# =====================================================================
def test_las_guardas_de_i3_cubren_todas_las_tablas_impl():
    import clonar_demo_a_pruebas as clon
    patrones = clon.tablas_excluidas()
    assert "impl*" in patrones
    assert set(db.IMPL_TABLAS) == {t for t in db.SQLModel.metadata.tables if t.startswith("impl")}
    ajenas = [t for t in db.SQLModel.metadata.tables if t.startswith("impl") and t not in db.IMPL_TABLAS]
    assert ajenas == []
    with open("cargar_demo.py", encoding="utf-8") as f:
        assert "PREFIJO_TABLAS" in f.read()


# =====================================================================
# 10. Correcciones de la segunda vuelta (tests que fijan lo corregido)
# =====================================================================
def test_la_regla_de_aprobacion_vale_para_los_dos_lados_y_acciones_lo_dice():
    """QA-01 / QA-02, desde el sindicato y desde el equipo, en todos los estados abiertos."""
    pid, eq, sin = _mundo()
    for creador, otro in ((eq, sin), (sin, eq)):
        for estado in (None, "en_curso", "respondida"):
            tid = _crear(creador, pid, "aprobacion", "Aprobar", "texto")["id"]
            if estado:
                assert _resp(creador, pid, tid, estado_nuevo=estado, texto="la tomo").status_code == 200
            assert _det(creador, pid, tid)["acciones"]["aprobar"] is False
            assert creador.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": True}).status_code == 403
            assert _det(otro, pid, tid)["acciones"]["aprobar"] is True       # la otra parte sí, aunque no le toque el turno
            assert otro.post(_api(pid, f"tarjetas/{tid}/aprobacion"), json={"aprobar": True}).status_code == 200


def test_codigos_solo_ascii():
    """QA-03 / QA-18."""
    assert im.extraer_codigos("Hİ0001 ñPE0004 PE0004ñ PE٠٠٠٤ ıPE0004") == []
    assert im.parsear_codigo("Hİ0001") is None
    assert im.extraer_codigos("(pe0004), AR000123.") == ["PE0004", "AR000123"]


def test_el_saneo_unico_de_texto():
    """QA-04: sin NUL ni sustitutos sueltos, en NFC y recortado."""
    assert im.limpiar_texto("  a\x00b\ud800c  ") == "abc"
    assert im.limpiar_texto("e\u0301") == "\u00e9"
    assert im.limpiar_texto(None) == "" and im.limpiar_texto(12) == "12"


def test_un_sustituto_suelto_en_un_json_no_da_500():
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    for ruta, cuerpo in ((f"tarjetas/{t}/reasignar", {"responsable": "a\ud800b", "responsable_lado": "equipo"}),
                         ("plan/hitos", {"etapa_id": etapa, "texto": "h\ud800"}),
                         (f"tarjetas/{ap}/aprobacion", {"aprobar": True, "texto": "x\ud800\x00"})):
        r = eq.post(_api(pid, ruta), content=json.dumps(cuerpo).encode("ascii"),
                    headers={"content-type": "application/json"})
        assert r.status_code < 500, (ruta, r.status_code)
    assert "\ud800" not in eq.get(_api(pid, f"tarjetas/{t}")).text


def test_ids_fuera_de_int4_son_404_y_en_un_campo_400():
    """QA-05."""
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    for c in (eq, sin):
        assert c.get(_api(pid, "tarjetas/2147483648")).status_code == 404
        assert c.get("/api/implementacion/p/2147483648/resumen").status_code == 404
        assert c.get(_api(pid, "archivos/99999999999")).status_code == 404
    assert eq.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t",
                                                  "etapa_id": "99999999999"}).status_code == 400
    assert eq.post(_eq_url("proyectos"), json={"nombre": "X", "sindicato_id": 10 ** 20}).status_code == 400
    assert eq.get(_eq_url(f"proyectos/{10 ** 12}/usuarios")).status_code == 404
    # un dígito Unicode no-ASCII tampoco rompe la búsqueda por número
    assert eq.get(_api(pid, "tarjetas"), params={"q": "²"}).status_code == 200
    assert eq.get(_api(pid, "tarjetas"), params={"q": "#99999999999"}).status_code == 200


def test_mime_saneado_y_responder_atomico_con_archivo_fallido():
    """QA-06: el mime se sanea (un NUL ya no rompe el INSERT) y, si un adjunto igual falla
    (un archivo ya borrado de la lista, p. ej.), no cambia nada: ni mensaje, ni estado, ni archivos."""
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    assert im.mime_seguro("te\x00xt/plain") == "text/plain"
    assert im.mime_seguro("text/html; charset=\x00") == "text/html"
    assert im.mime_seguro("???") == "application/octet-stream"
    antes = _det(eq, pid, t["id"])
    with db.get_session() as s:
        with pytest.raises(im.ErrorImpl):
            db.impl_responder(s, pid, t["id"], EQ, texto="hola", estado_nuevo="respondida",
                              adjuntos=[("ok.pdf", "application/pdf", b"%PDF"), ("vacio.pdf", "application/pdf", b"")])
    despues = _det(eq, pid, t["id"])
    assert despues["tarjeta"]["estado"] == antes["tarjeta"]["estado"] == "abierta"
    assert len(despues["mensajes"]) == len(antes["mensajes"]) == 1
    assert despues["archivos"] == antes["archivos"] == []
    assert len(despues["eventos"]) == len(antes["eventos"])
    # y en la creación: si un archivo falla no queda la tarjeta
    n = len(eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"])
    with db.get_session() as s:
        with pytest.raises(im.ErrorImpl):
            db.impl_crear_tarjeta(s, pid, EQ, "pedido", "t", "t", adjuntos=[("v.pdf", "x/y", b"")])
    assert len(eq.get(_api(pid, "tarjetas"), params={"vista": "todas"}).json()["tarjetas"]) == n


def test_reasignar_sobre_cerrada_aviso_y_aprobacion_resuelta_es_409_o_400():
    """QA-07, con los códigos."""
    pid, eq, sin = _mundo()
    cuerpo = {"responsable": "X", "responsable_lado": "sindicato"}
    cerrada = _llevar(pid, eq, sin, "pedido", "sindicato", "cerrada")
    assert sin.post(_api(pid, f"tarjetas/{cerrada}/reasignar"), json=cuerpo).status_code == 409
    aviso = _crear(eq, pid, "aviso", "av", "x")["id"]
    assert eq.post(_api(pid, f"tarjetas/{aviso}/reasignar"), json=cuerpo).status_code == 400
    ap = _llevar(pid, eq, sin, "aprobacion", "sindicato", "aprobada")
    assert eq.post(_api(pid, f"tarjetas/{ap}/reasignar"), json=cuerpo).status_code == 409


def test_el_enlace_del_aviso_usa_la_url_publica_del_entorno(monkeypatch):
    """QA-08: se arma con entorno.URLS (aquí, pruebas), no con el Host."""
    enviados = []
    monkeypatch.setattr(main.correo, "habilitado", lambda: True)
    monkeypatch.setattr(main.correo, "enviar", lambda d, a, t: enviados.append((d, a, t)) or True)
    monkeypatch.setattr(main, "IMPL_AVISOS_SINCRONO", True)
    mail_eq = f"{_u('eq')}@colm3na.test"
    _cliente_equipo(email=mail_eq)
    pid = _proyecto()
    sin = _cliente_sindicato(pid)
    sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "Hola", "texto": "x"}, headers={"host": "evil.example"})
    cuerpos = [c for d, a, c in enviados if d == mail_eq]
    assert cuerpos and all(entorno.URLS["pruebas"] + "/implementacion?p=" in c for c in cuerpos)
    # sin URL pública (local): sin enlace absoluto
    enviados.clear()
    monkeypatch.setattr(entorno, "ENTORNO", "local")
    sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "Hola 2", "texto": "x"}, headers={"host": "evil.example"})
    cuerpos = [c for d, a, c in enviados if d == mail_eq]
    assert cuerpos and all("evil.example" not in c and "http" not in c for c in cuerpos)


def test_la_api_del_equipo_pide_lo_mismo_que_la_mesa():
    """QA-09: activo, sin clave ni datos pendientes; sin sesión 403; baja de una sesión vigente 401."""
    ok = _cliente_equipo()
    assert ok.get(_eq_url("proyectos")).status_code == 200
    anon = TestClient(main.app, follow_redirects=False)
    assert anon.get(_eq_url("proyectos")).status_code == 403
    baja = _cliente_equipo()
    with db.get_session() as s:
        u = s.get(db.UsuarioPlataforma, baja.uid)
        u.activo = False
        s.add(u)
        s.commit()
    assert baja.get(_eq_url("proyectos")).status_code == 401
    assert baja.post(_eq_url("proyectos"), json={"nombre": "no"}).status_code == 401


def test_topes_de_largo_de_los_textos_libres():
    """QA-10: los mensajes son claros y el límite exacto entra."""
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    r = eq.post(_api(pid, f"tarjetas/{t}/reasignar"), json={"responsable": "A" * 201, "responsable_lado": "equipo"})
    assert r.status_code == 400 and "200" in r.json()["detail"]
    assert eq.post(_api(pid, f"tarjetas/{t}/reasignar"), json={"responsable": "A" * 200, "responsable_lado": "equipo"}).status_code == 200
    assert eq.post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": "B" * 200}).status_code == 200
    assert eq.post(_api(pid, f"plan/hitos/{hito}"), json={"texto": "B" * 201}).status_code == 400
    assert eq.post(_eq_url("proyectos"), json={"nombre": "N" * 121}).status_code == 400
    r = eq.post(_api(pid, f"tarjetas/{ap}/aprobacion"), json={"aprobar": True, "texto": "T" * 5001})
    assert r.status_code == 400 and "5000" in r.json()["detail"]


def test_fecha_limite_invalida_se_rechaza_y_la_ar_se_normaliza():
    """QA-11: mismo parseo que las fechas del padrón."""
    pid, eq, sin = _mundo()
    for mala in ("2026-13-45", "mañana", "2026/01/05"):
        assert sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t", "fecha_limite": mala}).status_code == 400
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "t", "texto": "t", "fecha_limite": "5/1/2030"})
    assert r.status_code == 200 and r.json()["tarjeta"]["fecha_limite"] == "2030-01-05"


def test_el_freno_del_login_cuenta_fallos_en_ventana_y_se_vence(monkeypatch):
    """QA-14: sin reinicio por un login propio; los fallos viejos no cuentan."""
    pid = _proyecto()
    sin = _cliente_sindicato(pid)
    c = TestClient(main.app, follow_redirects=False)
    main._intentos_impl.clear()
    for i in range(9):
        c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": f"mala{i}"})
    # un ingreso correcto NO borra los 9 fallos: el décimo ya bloquea
    c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": DEFINITIVA})
    r = c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": "otra"})
    r2 = c.post("/implementacion/ingresar", data={"mail": sin.mail, "clave": DEFINITIVA})
    assert r2.headers["location"].endswith("error=espera"), (r.headers, r2.headers)
    # los fallos fuera de la ventana no cuentan
    main._intentos_impl.clear()
    import time
    est = {"fallos": [time.time() - main.IMPL_LOGIN_VENTANA_S - 5] * 50, "hasta": 0.0}
    main._intentos_impl["testclient"] = est
    assert main._impl_login_bloqueado(type("R", (), {"headers": {}, "client": type("C", (), {"host": "testclient"})()})()) is False


def test_una_subida_anonima_se_corta_por_content_length(monkeypatch):
    """QA-15: sin sesión, 401 sin parsear; con sesión, arriba del tope total 413 sin leerla."""
    pid, eq, sin = _mundo()
    anon = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    r = anon.post(_api(pid, "tarjetas"), content=b"x" * 100, headers={
        "content-type": "multipart/form-data; boundary=abc", "content-length": str(500 * 1024 * 1024)})
    assert r.status_code == 401
    for ruta in ("tarjetas", f"tarjetas/{_crear(sin, pid)['id']}/responder"):
        r = sin.post(_api(pid, ruta), content=b"x" * 100, headers={
            "content-type": "multipart/form-data; boundary=abc", "content-length": str(500 * 1024 * 1024)})
        assert r.status_code == 413


def test_hitos_concurrentes_con_orden_unico_y_bloqueo_de_etapa():
    """QA-16 (la carrera ya no se da con el bloqueo de la etapa)."""
    pid, eq, _ = _mundo()
    etapa = eq.get(_api(pid, "plan")).json()["etapas"][0]["id"]

    def go(i):
        _cliente_equipo().post(_api(pid, "plan/hitos"), json={"etapa_id": etapa, "texto": f"h{i}"})
    ths = [threading.Thread(target=go, args=(i,)) for i in range(10)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    ordenes = [h["orden"] for h in eq.get(_api(pid, "plan")).json()["etapas"][0]["hitos"]]
    assert sorted(ordenes) == list(range(1, 11)), ordenes


def test_un_archivo_sin_nombre_entra_como_archivo_y_uno_vacio_se_ignora():
    """QA-17."""
    pid, eq, sin = _mundo()
    t = _crear(sin, pid)
    assert _resp(sin, pid, t["id"], texto="a", files=[("archivos", ("   ", b"datos", "text/plain"))]).status_code == 200
    assert [a["nombre"] for a in _det(eq, pid, t["id"])["archivos"]] == ["archivo"]
    assert _resp(sin, pid, t["id"], texto="b", files=[("archivos", ("", b"", "application/octet-stream"))]).status_code == 200
    assert len(_det(eq, pid, t["id"])["archivos"]) == 1


def test_las_migraciones_de_la_mesa_son_idempotentes():
    """QA-19: `clonar_demo_a_pruebas.py` restaura sobre Pruebas un dump SIN las tablas impl* pero CON
    `alembic_version` de la demo (más vieja): el siguiente `alembic upgrade head` no puede chocar con
    las tablas y columnas de la mesa que ya están, ni duplicar sus contadores."""
    import subprocess
    import sys
    import psycopg
    from test_migraciones import _psycopg, _url_con_base
    nombre = f"mitrabajo_mig_idem_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    base_url = str(db.engine.url.render_as_string(hide_password=False))
    admin, url_mig = _psycopg(_url_con_base(base_url, "postgres")), _url_con_base(base_url, nombre)
    env = {**os.environ, "DATABASE_URL": url_mig}

    def alembic():
        return subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env,
                              capture_output=True, text=True, timeout=300)
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{nombre}"')
    try:
        r = alembic()
        assert r.returncode == 0, r.stderr[-1500:]
        with psycopg.connect(_psycopg(url_mig), autocommit=True) as c:
            cabeza = c.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            c.execute("INSERT INTO implproyecto (nombre, activo, ultimo_numero, creado) VALUES ('P', true, 1, '2026-01-01')")
            c.execute("INSERT INTO implcontador (proyecto_id, prefijo, ultimo) "
                      "SELECT id, 'PE', 1 FROM implproyecto LIMIT 1")
            # lo que deja el restore de la demo: alembic_version anterior a la mesa, tablas impl* intactas
            c.execute("UPDATE alembic_version SET version_num = 'e8b2d4f6a1c3'")
        r = alembic()
        assert r.returncode == 0, ("alembic upgrade head chocó con lo que la mesa ya tenía:\n" + r.stderr[-1500:])
        with psycopg.connect(_psycopg(url_mig)) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == cabeza
            assert c.execute("SELECT count(*) FROM implcontador").fetchone()[0] == 1       # no se duplicó nada
            assert c.execute("SELECT count(*) FROM implproyecto").fetchone()[0] == 1
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def test_freno_de_ritmo_por_usuario_del_sindicato(monkeypatch):
    """QA-20: 429 con mensaje al pasar el tope; no es del equipo ni de otro usuario; se vence."""
    pid, eq, sin = _mundo()
    otro = _cliente_sindicato(pid, "Otra persona")
    monkeypatch.setattr(main, "IMPL_RITMO_MAX", 3)
    main._impl_ritmo.clear()
    t = _crear(eq, pid)["id"]
    codigos = [sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": f"t{i}", "texto": "x"}).status_code
               for i in range(2)]
    codigos.append(_resp(sin, pid, t, texto="una más").status_code)
    assert codigos == [200, 200, 200]
    r = sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "tope", "texto": "x"})
    assert r.status_code == 429 and "Esperá" in r.json()["detail"]
    assert _resp(sin, pid, t, texto="también frenada").status_code == 429
    assert otro.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "otra", "texto": "x"}).status_code == 200
    for _ in range(5):                                                     # el equipo no se frena
        assert _resp(eq, pid, t, texto="equipo").status_code == 200
    monkeypatch.setattr(main, "IMPL_RITMO_VENTANA_S", 0)                  # ventana vencida: vuelve a andar
    assert sin.post(_api(pid, "tarjetas"), data={"tipo": "pedido", "titulo": "ya", "texto": "x"}).status_code == 200


def test_descarga_y_exportacion_rechazan_un_pedido_de_otro_sitio():
    """QA-21: GET con efecto -> 403 si el navegador declara Sec-Fetch-Site: cross-site."""
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, archivos=_pdf("a.pdf"))
    aid = _det(eq, pid, t["id"])["archivos"][0]["id"]
    cruz = {"sec-fetch-site": "cross-site"}
    assert sin.get(_api(pid, f"archivos/{aid}"), headers=cruz).status_code == 403
    assert eq.get(_api(pid, "exportar.zip"), headers=cruz).status_code == 403
    with db.get_session() as s:
        assert len(db.impl_descargas(s, pid, aid)) == 0                       # no quedó registrada
    for sitio in ("same-origin", "same-site", "none"):
        assert sin.get(_api(pid, f"archivos/{aid}"), headers={"sec-fetch-site": sitio}).status_code == 200
    assert sin.get(_api(pid, f"archivos/{aid}")).status_code == 200            # sin cabecera (curl, tests)


def test_la_exportacion_incluye_usuarios_sin_clave_y_avisa_si_no_entra(monkeypatch):
    """QA-22."""
    pid, eq, sin = _mundo()
    t = _crear(sin, pid, archivos=_pdf("a.pdf", b"%PDF " + b"x" * 3000))
    z = zipfile.ZipFile(io.BytesIO(eq.get(_api(pid, "exportar.zip")).content))
    usuarios = json.loads(z.read("usuarios.json"))
    assert [u["mail"] for u in usuarios] == [sin.mail]
    assert all("clave_hash" not in u for u in usuarios) and "clave_hash" not in z.read("usuarios.json").decode()
    monkeypatch.setattr(main, "IMPL_TOPE_EXPORTACION", 1000)
    r = eq.get(_api(pid, "exportar.zip"))
    assert r.status_code == 413 and "sin_archivos" in r.json()["detail"] and "MB" in r.json()["detail"]
    z = zipfile.ZipFile(io.BytesIO(eq.get(_api(pid, "exportar.zip?sin_archivos=1")).content))
    assert "usuarios.json" in z.namelist() and not [n for n in z.namelist() if n.startswith("archivos/")]
    assert "a.pdf" in z.read("archivos.csv").decode("utf-8")


def test_el_hito_valida_todo_antes_de_escribir():
    """QA-26: un texto inválido junto a `hecho` no deja el tildado hecho."""
    pid, eq, sin, t, ap, etapa, hito = _entorno_fuzz()
    for malo in ({"hecho": True, "texto": "   "}, {"hecho": True, "texto": "x" * 500}, {"hecho": True, "orden": "abc"}):
        assert eq.post(_api(pid, f"plan/hitos/{hito}"), json=malo).status_code == 400
        h = [x for x in eq.get(_api(pid, "plan")).json()["etapas"][0]["hitos"] if x["id"] == hito][0]
        assert h["hecho"] is False, malo
    r = eq.post(_api(pid, f"plan/hitos/{hito}"), json={"hecho": True, "texto": "Nuevo texto", "orden": 1})
    assert r.status_code == 200
    h = [x for x in r.json()["etapas"][0]["hitos"] if x["id"] == hito][0]
    assert (h["hecho"], h["texto"]) == (True, "Nuevo texto")
