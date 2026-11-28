"""XSII bloque 4b, REC-04: «Conceptos desde los recibos de muestra»
(docs/xsii/API.md, «Bloque 4b»).

Tres cosas:
- Equivalencia: `conceptos_carga` (proponer y aplicar) da EXACTAMENTE lo que daba la
  lógica que vivía adentro de `/admin/aprender` y `/admin/aprender/aplicar`, que
  acá está copiada tal cual estaba (`_viejo_*`).
- El motor de propuestas y la validación de la carga, sin red.
- Las rutas de la asistida por HTTP real (multipart el ensayo, JSON la carga), con la
  lectura simulada (`MOCK_EXTRACTOR=1`) o con `main.extraer` reemplazado.

Correr con: python -m pytest test_xsii_conceptos.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"
os.environ["MOCK_EXTRACTOR"] = "1"
os.environ["MOCK_EXTRACTOR_LATENCIA"] = "0"
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import copy
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import auth
import conceptos_carga
import cuit
import db
import entorno
import extractor
import main
import validador
from test_xsii_asistida import BASE, EQ, _equipo, _mundo, _movs, _sindicato, _tarea
from xsii.proyectos.colm3na.asistidas import ASISTIDAS, ErrorAsistida, conceptos as asist

db.crear_tablas()
C = "REC-04"
CUIT_A = "30712345671"            # válido por módulo 11 (lo usan otros tests de CUIT)
CUIT_B = cuit.corregir("30700000011")
USO = {"modelo": "claude-sonnet-4-6", "tokens_entrada": 100, "tokens_salida": 50, "duracion_ms": 900,
       "tokens_cache_lectura": 0, "tokens_cache_escritura": 0}


def _linea(codigo, descripcion, importe, tipo="remuneracion", seccion="haberes", categoria=None):
    return {"codigo": codigo, "descripcion": descripcion, "cantidad": None, "unidad": None, "importe": importe,
            "tipo": tipo, "seccion": seccion, "categoria_universal": categoria}


def _recibo(cuit_emp, lineas, nombre="Empleador SA"):
    return {"formato": "clasico", "periodo": "2026-08",
            "empleado": {"apellido_nombre": "Persona Real", "cuil": "20111111119", "legajo": "9"},
            "empleador": {"nombre": nombre, "cuit": cuit_emp}, "lineas": lineas,
            "totales_impresos": {}, "contribuciones_patronales": [], "confianza": "alta"}


def _catalogo():
    """Un catálogo de ejemplo: los tres genéricos de ley, uno de convenio y uno por empleador."""
    return [
        {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)", "tipo": "descuento", "remunerativo": False,
         "alias": ["Jubilación"], "pendiente_revision": False, "categoria_sindical": "", "cuit_empleador": None,
         "codigo_generico": None},
        {"codigo": "CUOTA", "nombre": "Cuota sindical", "tipo": "descuento", "remunerativo": False,
         "alias": [], "pendiente_revision": False, "categoria_sindical": "afiliacion", "cuit_empleador": None,
         "codigo_generico": None},
        {"codigo": "BASICO", "nombre": "Sueldo básico", "tipo": "ingreso", "remunerativo": True,
         "alias": [], "pendiente_revision": False, "categoria_sindical": "", "cuit_empleador": None,
         "codigo_generico": None},
    ]


ESCENARIOS = {
    "uno_generico": [_recibo(None, [_linea("X1", "Premio por productividad", 5000),
                                    _linea("BASICO", "Sueldo básico", 100000)])],
    "con_empleador_y_universal": [_recibo(CUIT_A, [
        _linea("AB12", "Retención previsional Art.11", -110000, "aporte_trabajador", "descuentos", "jubilacion"),
        _linea("AB13", "Aporte solidario gremial", -2000, "aporte_trabajador", "descuentos", "cuota_sindical"),
        _linea("AB14", "Viático sin aportes", 3000, "remuneracion", "no_remunerativos")])],
    "mismo_codigo_dos_empleadores": [
        _recibo(CUIT_A, [_linea("77", "Premio asistencia", 1000)]),
        _recibo(CUIT_B, [_linea("77", "Premio asistencia", 1000)]),
        _recibo(CUIT_A, [_linea("77", "Premio asistencia", 1200), _linea("78", "Cuota seguro", -300,
                                                                       "otro", "descuentos")])],
    "parecidos_y_reintegro": [_recibo(CUIT_A, [
        _linea("Z9", "Cuota sindical extra", -1500, "otro", "descuentos"),
        _linea("R1", "Reintegro Ganancias", 800, "otro", "descuentos"),
        _linea("", "Antigüedad (16 años)", 7000), _linea("", "Antigüedad (24 años)", 9000)])],
    "sin_nada_nuevo": [_recibo(None, [_linea("BASICO", "Sueldo básico", 100000)])],
    "cuit_ilegible": [_recibo("30-12345678-9", [_linea("Q1", "Concepto raro", 10)]),
                      _recibo("abc", [_linea("Q2", "Otro raro", 10)])],
}


# ---------------------------------------------------------------- la lógica ANTERIOR, congelada
def _viejo_proponer(conceptos_actuales, recibos):
    """El cuerpo de `POST /admin/aprender` antes de `conceptos_carga` (sin la lectura)."""
    genericos_actuales = [c for c in conceptos_actuales if not c.get("cuit_empleador")]
    acumulados = {}
    for recibo in recibos:
        cuit_empleador = cuit.normalizar((recibo.get("empleador") or {}).get("cuit")) or None
        for n in validador.detectar_nuevos(conceptos_actuales, recibo["lineas"], cuit_empleador):
            clave = (n["codigo"], cuit_empleador or "")
            if clave in acumulados:
                acumulados[clave]["veces"] += 1
            else:
                acumulados[clave] = {**n, "veces": 1, "cuit_empleador": cuit_empleador}
    for p in acumulados.values():
        similar = validador.buscar_similar(p["descripcion"], conceptos_actuales)
        p["similar"] = {
            "codigo": similar["concepto"]["codigo"],
            "nombre": similar["concepto"]["nombre"],
            "ratio": similar["ratio"],
        } if similar else None
        p["generico_sugerido"] = None
        if p["cuit_empleador"]:
            generico_universal = validador.generico_de_categoria(p.get("categoria_universal"), genericos_actuales)
            if generico_universal:
                p["generico_sugerido"] = {"codigo": generico_universal["codigo"],
                                          "nombre": generico_universal["nombre"]}
            else:
                similar_generico = validador.buscar_similar(p["descripcion"], genericos_actuales)
                if similar_generico:
                    p["generico_sugerido"] = {"codigo": similar_generico["concepto"]["codigo"],
                                              "nombre": similar_generico["concepto"]["nombre"]}
    return sorted(acumulados.values(), key=lambda x: -x["veces"])


def _viejo_aplicar(sid, aprobados):
    """El cuerpo de `POST /admin/aprender/aplicar` antes de `conceptos_carga`."""
    altas = 0
    cuit_invalidos = []
    with db.get_session() as s:
        existentes = {(c.codigo, c.cuit_empleador or "") for c in s.exec(select(db.Concepto).where(
            db.Concepto.sindicato_id == sid)).all()}
        for c in aprobados:
            if main._cuit_mal(c.get("cuit_empleador", ""), opcional=True):
                cuit_invalidos.append(c.get("codigo", ""))
                continue
            cuit_empleador = main._norm_cuil(c.get("cuit_empleador", "")) or None
            clave = (c["codigo"], cuit_empleador or "")
            if clave not in existentes:
                s.add(db.Concepto(
                    sindicato_id=sid,
                    codigo=c["codigo"], nombre=c["descripcion"], tipo=c["tipo"],
                    remunerativo=c.get("remunerativo", True),
                    alias=[c["descripcion"]], pendiente_revision=False,
                    cuit_empleador=cuit_empleador,
                    codigo_generico=(c.get("codigo_generico") or "").strip() or None,
                ))
                existentes.add(clave)
                altas += 1
        s.commit()
    return {"ok": True, "altas": altas, "cuit_invalidos": cuit_invalidos}


# ================================================================== equivalencia con Aprendizaje

@pytest.mark.parametrize("nombre", sorted(ESCENARIOS))
def test_proponer_da_lo_mismo_que_la_logica_anterior(nombre):
    recibos = ESCENARIOS[nombre]
    actuales = _catalogo()
    esperado = _viejo_proponer(copy.deepcopy(actuales), copy.deepcopy(recibos))
    obtenido = conceptos_carga.proponer(copy.deepcopy(actuales), copy.deepcopy(recibos))
    assert obtenido == esperado
    assert json.dumps(obtenido, sort_keys=True) == json.dumps(esperado, sort_keys=True)


def test_los_escenarios_cubren_lo_que_importa():
    todo = {n: conceptos_carga.proponer(_catalogo(), r) for n, r in ESCENARIOS.items()}
    assert todo["sin_nada_nuevo"] == []
    assert any(p["generico_sugerido"] for p in todo["con_empleador_y_universal"])
    assert any(p["similar"] for p in todo["parecidos_y_reintegro"])
    assert any(p["veces"] > 1 for p in todo["mismo_codigo_dos_empleadores"])
    assert len({(p["codigo"], p["cuit_empleador"]) for p in todo["mismo_codigo_dos_empleadores"]}) >= 3


def test_el_detalle_solo_suma_dos_campos_y_no_cambia_lo_demas():
    recibos = ESCENARIOS["con_empleador_y_universal"]
    sin = conceptos_carga.proponer(_catalogo(), copy.deepcopy(recibos))
    con = conceptos_carga.proponer(_catalogo(), copy.deepcopy(recibos), detalle=True)
    assert [{k: v for k, v in p.items() if k not in ("seccion_leida", "tipo_leido")} for p in con] == sin
    assert {p["codigo"]: (p["seccion_leida"], p["tipo_leido"]) for p in con}["AB14"] == ("no_remunerativos", "remuneracion")


@pytest.mark.parametrize("aprobados", [
    [{"codigo": "AP-1", "descripcion": "Uno", "tipo": "ingreso"},
     {"codigo": "AP-2", "descripcion": "Dos", "tipo": "descuento", "remunerativo": False,
      "cuit_empleador": "30-71234567-1", "codigo_generico": " JUBILACION "},
     {"codigo": "AP-3", "descripcion": "Mal CUIT", "tipo": "ingreso", "cuit_empleador": "30123456789"},
     {"codigo": "AP-4", "descripcion": "Letras", "tipo": "ingreso", "cuit_empleador": "abc"},
     {"codigo": "AP-1", "descripcion": "Repetido", "tipo": "ingreso"},
     {"codigo": "AP-2", "descripcion": "Mismo código otro empleador", "tipo": "ingreso",
      "cuit_empleador": CUIT_B}],
    [],
])
def test_aplicar_da_lo_mismo_que_la_logica_anterior(aprobados):
    sid_a, sid_b = _sindicato(), _sindicato()
    esperado = _viejo_aplicar(sid_a, copy.deepcopy(aprobados))
    with db.get_session() as s:
        r = conceptos_carga.aplicar(s, sid_b, copy.deepcopy(aprobados))
        s.commit()
    assert {"ok": True, "altas": r["altas"], "cuit_invalidos": r["cuit_invalidos"]} == esperado

    def filas(sid):
        with db.get_session() as s:
            return sorted((c.codigo, c.nombre, c.tipo, c.remunerativo, tuple(c.alias), c.pendiente_revision,
                           c.cuit_empleador, c.codigo_generico, c.categoria_sindical)
                          for c in s.exec(select(db.Concepto).where(db.Concepto.sindicato_id == sid)).all())
    assert filas(sid_a) == filas(sid_b)
    if aprobados:
        assert r["repetidos"] == 1                       # el segundo AP-1


def _admin_de(sid):
    usuario = cuit.corregir(f"20{uuid.uuid4().int % 10 ** 8:08d}0")        # único aunque dos sindicatos terminen igual
    with Session(db.engine) as s:
        s.add(db.UsuarioSindicato(sindicato_id=sid, usuario=usuario, nombre="Admin",
                                  clave_hash=auth.hashear_clave("clave-test"), debe_cambiar_clave=False,
                                  es_super_admin=True))
        s.commit()
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": "clave-test"}, follow_redirects=False)
    assert r.status_code in (200, 303), r.text
    return c


def test_las_dos_rutas_del_panel_siguen_dando_lo_mismo(monkeypatch):
    sid = _sindicato()
    c = _admin_de(sid)
    por_contenido = {b"r1": ESCENARIOS["con_empleador_y_universal"][0], b"r2": ESCENARIOS["uno_generico"][0],
                     b"r3": ESCENARIOS["con_empleador_y_universal"][0]}

    def leer(contenido, tipo, modelo=None, **kw):
        if contenido == b"roto":
            raise RuntimeError("la API se cayó")
        return copy.deepcopy(por_contenido[contenido]), dict(USO)
    monkeypatch.setattr(main, "extraer", leer)
    files = [("archivos", (f"{k.decode()}.png", k, "image/png")) for k in (b"r1", b"r2", b"roto", b"r3")]
    r = c.post("/admin/aprender", files=files)
    assert r.status_code == 200, r.text
    actuales = db.conceptos_como_dicts(sid)
    recibos = [por_contenido[b"r1"], por_contenido[b"r2"], por_contenido[b"r3"]]
    esperado = {"leidos": 3, "fallidos": 1, "propuestas": _viejo_proponer(actuales, copy.deepcopy(recibos))}
    assert r.json() == json.loads(json.dumps(esperado))
    # lo leído se registró como aprendizaje (3 filas del modelo de la lectura)
    with db.get_session() as s:
        filas = s.exec(select(db.UsoIA).where(db.UsoIA.sindicato_id == sid, db.UsoIA.tipo == "aprendizaje")).all()
    assert len(filas) == 3

    aprobados = [{"codigo": "RUT-1", "descripcion": "Uno", "tipo": "ingreso", "cuit_empleador": "30-71234567-1"},
                 {"codigo": "RUT-2", "descripcion": "Dos", "tipo": "ingreso", "cuit_empleador": "30123456789"}]
    r = c.post("/admin/aprender/aplicar", json={"aprobados": aprobados})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "altas": 1, "cuit_invalidos": ["RUT-2"]}


# ================================================================== el motor de la asistida (puro)

def test_describir_de_recibos_tiene_la_forma_del_contrato():
    d = asist.describir()
    assert d["entrada"] == "recibos" and len(d["que_voy_a_hacer"]) == 2
    assert d["archivos"] == {"por_envio": 1, "tope_mb": 8, "formatos": ["pdf", "jpg", "png", "webp"],
                             "sugeridos": "30 a 60, de varios empleadores"}
    assert set(d["ia"]) == {"disponible", "simulada", "motivo"}
    assert [r["clave"] for r in d["rubros"]] == ["haber", "no_remunerativo", "descuento"]
    assert [c["clave"] for c in d["categorias_sindicales"]] == ["", "afiliacion", "convenio"]
    assert "modelo_csv" not in d and "mapeo" not in d and "columnas" not in d
    assert ASISTIDAS[C] is asist


def test_el_ensayo_arma_rubros_estados_y_avisos():
    actuales = _catalogo()
    recibo = _recibo(CUIT_A, [
        _linea("N1", "Premio por presentismo", 5000),                                     # haber
        _linea("N2", "Viático sin aportes", 3000, seccion="no_remunerativos"),            # no remunerativo
        _linea("N3", "Seguro de sepelio", -800, "otro", "descuentos"),                    # descuento
        _linea("N4", "Retención previsional Art.11", -110000, "aporte_trabajador", "descuentos", "jubilacion"),
        _linea("N5", "Cuota sindical extra", -900, "otro", "descuentos"),             # parecido: dudosa
        _linea("N6", "Raro", 100, "aporte_trabajador", "haberes"),                        # sección y tipo no coinciden
        _linea("N7", "Reintegro de gastos", 700, "otro", "descuentos"),
        _linea("N8", "", 10)])                                                            # sin descripción
    e = asist.armar_ensayo(actuales, recibo, "r1.pdf")
    assert e["recibo"] == {"nombre": "r1.pdf", "leido": True, "motivo": "", "empleador_cuit": CUIT_A,
                           "empleador_nombre": "Empleador SA", "lineas": 8, "simulado": True}
    p = {x["codigo"]: x for x in e["propuestas"]}
    assert p["N1"]["rubro"] == "haber" and p["N1"]["estado"] == "valida" and p["N1"]["clave"] == f"N1|{CUIT_A}"
    assert p["N2"]["rubro"] == "no_remunerativo" and p["N3"]["rubro"] == "descuento"
    assert p["N4"]["generico_sugerido"] == {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)"}
    assert p["N5"]["estado"] == "dudosa" and p["N5"]["similar"]["codigo"] == "CUOTA"
    assert p["N5"]["generico_sugerido"]["codigo"] == "CUOTA" and p["N5"]["categoria_sindical"] == "afiliacion"
    assert p["N6"]["estado"] == "dudosa" and any("no coinciden" in a for a in p["N6"]["avisos"])
    assert p["N7"]["estado"] == "dudosa"
    assert p["N8"]["descripcion"] == "" and p["N8"]["estado"] == "dudosa"
    for x in e["propuestas"]:
        assert set(x) == {"clave", "codigo", "descripcion", "cuit_empleador", "empleador_nombre", "rubro",
                          "categoria_sindical", "veces", "similar", "generico_sugerido", "estado", "avisos",
                          "errores"}
    # nada de importes ni de la persona en lo que vuelve
    texto = json.dumps(e, ensure_ascii=False)
    assert "Persona Real" not in texto and "20111111119" not in texto and "110000" not in texto


def test_un_cuit_mal_leido_o_un_codigo_largo_rechazan_la_propuesta():
    e = asist.armar_ensayo(_catalogo(), _recibo("30123456789", [_linea("Q1", "Concepto", 1),
                                                                _linea("X" * 41, "Largo", 1)]), "r.png")
    estados = {p["codigo"]: p for p in e["propuestas"]}
    assert estados["Q1"]["estado"] == "rechazada" and "verificador" in estados["Q1"]["errores"][0]
    assert estados["X" * 41]["estado"] == "rechazada"
    d = asist.armar_ensayo(_catalogo(), _recibo(None, [_linea("L1", "d" * 200, 1)]), "r.png")
    assert d["propuestas"][0]["estado"] == "valida" and len(d["propuestas"][0]["descripcion"]) == 120
    assert any("recortó" in a for a in d["propuestas"][0]["avisos"])


def test_recibo_ilegible_no_propone_nada():
    e = asist.armar_ensayo(_catalogo(), None, "malo.jpg", "No pude leer.")
    assert e["recibo"]["leido"] is False and e["recibo"]["motivo"] == "No pude leer." and e["propuestas"] == []


def _item(**kw):
    return {"codigo": "C1", "descripcion": "Concepto uno", "cuit_empleador": "", "rubro": "haber",
            "categoria_sindical": "", "codigo_generico": "", **kw}


def test_validar_carga_acepta_y_traduce_el_rubro():
    aprobados, leidos = asist.validar_carga({"conceptos": [
        _item(), _item(codigo="C2", rubro="no_remunerativo"),
        _item(codigo="C3", rubro="descuento", categoria_sindical="afiliacion", cuit_empleador="30-71234567-1",
              codigo_generico="JUBILACION")], "recibos_leidos": 37}, {"JUBILACION"})
    assert leidos == 37
    assert [(a["tipo"], a["remunerativo"]) for a in aprobados] == [("ingreso", True), ("ingreso", False),
                                                                    ("descuento", False)]
    assert aprobados[2]["cuit_empleador"] == "30712345671" and aprobados[2]["categoria_sindical"] == "afiliacion"


@pytest.mark.parametrize("cuerpo", [
    None, [], "x", {}, {"conceptos": []}, {"conceptos": "x"}, {"conceptos": [{"codigo": "A"}] * 501},
    {"conceptos": [_item()], "recibos_leidos": -1}, {"conceptos": [_item()], "recibos_leidos": 5001},
    {"conceptos": [_item()], "recibos_leidos": "3"}, {"conceptos": [_item()], "recibos_leidos": True},
    {"conceptos": [_item()], "recibos_leidos": 1.5},
])
def test_validar_carga_rechaza_un_cuerpo_mal_formado(cuerpo):
    with pytest.raises(ErrorAsistida) as e:
        asist.validar_carga(cuerpo, set())
    assert e.value.estado == 400


@pytest.mark.parametrize("malo,campo", [
    (_item(codigo=""), "codigo"), (_item(codigo="X" * 41), "codigo"), (_item(codigo="A\x00B"), "codigo"),
    (_item(codigo="A\nB"), "codigo"), (_item(codigo=5), "codigo"), (_item(descripcion=""), "descripcion"),
    (_item(descripcion="d" * 121), "descripcion"), (_item(descripcion="a​b"), "descripcion"),
    (_item(cuit_empleador="30123456789"), "cuit_empleador"), (_item(cuit_empleador="abc"), "cuit_empleador"),
    (_item(rubro="otro"), "rubro"), (_item(rubro=None), "rubro"),
    (_item(categoria_sindical="afiliacion"), "categoria_sindical"),           # solo vale para un descuento
    (_item(rubro="descuento", categoria_sindical="raro"), "categoria_sindical"),
    (_item(codigo_generico="JUBILACION"), "codigo_generico"),                 # sin empleador
    (_item(cuit_empleador=CUIT_A, codigo_generico="NOEXISTE"), "codigo_generico"),
])
def test_validar_carga_cada_item_mal_formado_dice_donde(malo, campo):
    with pytest.raises(ErrorAsistida) as e:
        asist.validar_carga({"conceptos": [_item(codigo="OK"), malo]}, {"JUBILACION"})
    assert e.value.estado == 400
    assert [(d["indice"], d["campo"]) for d in e.value.detalle] == [(1, campo)]


def test_validar_carga_repetido_es_error_y_el_mismo_codigo_de_otro_empleador_no():
    with pytest.raises(ErrorAsistida) as e:
        asist.validar_carga({"conceptos": [_item(), _item(cuit_empleador="30-71234567-1"), _item()]}, set())
    assert [d["indice"] for d in e.value.detalle] == [2]
    asist.validar_carga({"conceptos": [_item(), _item(cuit_empleador=CUIT_A)]}, set())


# ================================================================== las rutas

def _url(pid, que="", codigo=C):
    return f"{BASE}/p/{pid}/tarea/{codigo}/asistida" + (f"/{que}" if que else "")


def _listo(eq, pid):
    """REC-01 resuelta, que es lo que REC-04 necesita."""
    r = eq.post(f"{BASE}/p/{pid}/tarea/REC-01/decision", json={"tipo": "completada_a_mano", "motivo": "armado del test"})
    assert r.status_code == 200, r.text


def _mundo_listo():
    pid, sid, eq = _mundo()
    _listo(eq, pid)
    return pid, sid, eq


def _leer(eq, pid, contenido=b"recibo-mock", nombre="recibo1.png", tipo="image/png"):
    return eq.post(_url(pid, "ensayo"), files={"archivo": (nombre, contenido, tipo)})


def _conceptos(sid):
    with db.get_session() as s:
        return list(s.exec(select(db.Concepto).where(db.Concepto.sindicato_id == sid)).all())


def _propios(sid):
    return [c for c in _conceptos(sid) if c.codigo not in ("JUBILACION", "PAMI", "OBRASOCIAL")]


def _usos(sid, tipo="aprendizaje"):
    with db.get_session() as s:
        return list(s.exec(select(db.UsoIA).where(db.UsoIA.sindicato_id == sid, db.UsoIA.tipo == tipo)).all())


def test_get_asistida_de_conceptos_y_las_otras_dos_dicen_planilla():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Concepto(sindicato_id=sid, codigo="BASICO", nombre="Sueldo básico", tipo="ingreso"))
        s.add(db.Concepto(sindicato_id=sid, codigo="X-EMP", nombre="De un empleador", tipo="ingreso",
                          cuit_empleador=CUIT_A))
        s.commit()
    j = eq.get(_url(pid)).json()
    assert j["disponible"] is True and j["entrada"] == "recibos" and j["ia"]["simulada"] is True
    codigos = {g["codigo"] for g in j["genericos"]}
    assert {"JUBILACION", "PAMI", "OBRASOCIAL", "BASICO"} <= codigos and "X-EMP" not in codigos
    assert eq.get(_url(pid, codigo="EST-01")).json()["entrada"] == "planilla"
    assert eq.get(_url(pid, codigo="PAD-02")).json()["entrada"] == "planilla"
    assert eq.get(_url(pid, "modelo.csv")).status_code == 404
    assert eq.get(_url(pid, "modelo.csv", "EST-01")).status_code == 200


def test_get_asistida_sin_clave_dice_que_la_ia_no_esta(monkeypatch):
    pid, sid, eq = _mundo()
    monkeypatch.delenv("MOCK_EXTRACTOR")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    j = eq.get(_url(pid)).json()
    assert j["ia"]["disponible"] is False and "clave" in j["ia"]["motivo"]
    r = _leer(eq, pid)
    assert r.status_code == 409 and "clave" in r.json()["detail"]


def test_ensayo_con_la_lectura_simulada_propone_y_no_escribe_nada():
    pid, sid, eq = _mundo_listo()
    antes = len(_conceptos(sid))
    r = _leer(eq, pid)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["recibo"]["leido"] is True and j["recibo"]["simulado"] is True and j["recibo"]["nombre"] == "recibo1.png"
    assert j["recibo"]["empleador_cuit"] == "30000000007" and j["recibo"]["lineas"] == 5
    por = {p["codigo"]: p for p in j["propuestas"]}
    assert set(por) == {"1", "3", "5"}                 # jubilación y obra social ya están en el catálogo
    assert all(p["estado"] != "rechazada" for p in por.values())            # el CUIT del mock cumple el módulo 11
    assert por["1"]["rubro"] == "haber" and por["3"]["rubro"] == "descuento"
    texto = json.dumps(j, ensure_ascii=False)
    assert "Demo Carga" not in texto and "1000000" not in texto and "110000" not in texto
    assert len(_conceptos(sid)) == antes and _movs(pid, "asistida_carga") == []
    assert len(_usos(sid)) == 1                                              # el gasto de la lectura se registra
    assert _tarea(eq, pid, C)["control"]["estado"] == "incompleta"


def test_ensayo_no_retiene_conexion_mientras_lee(monkeypatch):
    """La lectura corre sin sesión de base abierta: se mide con el pool."""
    pid, sid, eq = _mundo_listo()
    visto = {}

    def leer(contenido, tipo, modelo=None, **kw):
        visto["en_uso"] = db.engine.pool.checkedout()
        return copy.deepcopy(ESCENARIOS["uno_generico"][0]), dict(USO)
    monkeypatch.setattr(main, "extraer", leer)
    base = db.engine.pool.checkedout()
    assert _leer(eq, pid).status_code == 200
    assert visto["en_uso"] <= base


def test_ensayo_con_un_recibo_de_verdad_propone_lo_que_falta(monkeypatch):
    pid, sid, eq = _mundo_listo()
    recibo = _recibo(CUIT_A, [_linea("PRE", "Premio por presentismo", 5000),
                              _linea("VIA", "Viático sin aportes", 3000, seccion="no_remunerativos"),
                              _linea("SEP", "Seguro de sepelio", -800, "otro", "descuentos"),
                              _linea("AB12", "Retención previsional Art.11", -110000, "aporte_trabajador",
                                     "descuentos", "jubilacion")])
    monkeypatch.setattr(main, "extraer", lambda c, t, modelo=None, **kw: (copy.deepcopy(recibo), dict(USO)))
    j = _leer(eq, pid, nombre="Recibo julio.PDF", tipo="application/octet-stream").json()
    assert j["recibo"]["nombre"] == "Recibo julio.PDF"
    por = {p["codigo"]: p for p in j["propuestas"]}
    assert por["PRE"]["estado"] == "valida" and por["PRE"]["rubro"] == "haber"
    assert por["VIA"]["rubro"] == "no_remunerativo" and por["SEP"]["rubro"] == "descuento"
    assert por["AB12"]["generico_sugerido"]["codigo"] == "JUBILACION"
    # lo que ya está en el catálogo no se propone: después de cargar uno, no vuelve
    _cargar_uno(eq, pid)
    j2 = _leer(eq, pid).json()
    assert "PRE" not in {p["codigo"] for p in j2["propuestas"]}


def _cargar_uno(eq, pid, codigo="PRE"):
    r = eq.post(_url(pid, "carga"), json={"conceptos": [_item(codigo=codigo, descripcion="Premio por presentismo",
                                                              cuit_empleador=CUIT_A)], "recibos_leidos": 1})
    assert r.status_code == 200, r.text
    return r.json()


def test_un_recibo_que_la_ia_no_puede_leer_es_200_y_se_registra_el_gasto(monkeypatch):
    pid, sid, eq = _mundo_listo()

    def leer(contenido, tipo, modelo=None, **kw):
        raise extractor.ErrorLectura("respuesta cortada", dict(USO))
    monkeypatch.setattr(main, "extraer", leer)
    r = _leer(eq, pid, nombre="borroso.jpg", tipo="image/jpeg")
    assert r.status_code == 200
    j = r.json()
    assert j["recibo"]["leido"] is False and j["recibo"]["motivo"] and j["propuestas"] == []
    assert len(_usos(sid)) == 1
    monkeypatch.setattr(main, "extraer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin red")))
    assert _leer(eq, pid).json()["recibo"]["leido"] is False


def test_el_ensayo_rechaza_un_pedido_que_no_sirve():
    pid, sid, eq = _mundo_listo()
    assert eq.post(_url(pid, "ensayo"), data={"x": "1"}).status_code == 400            # sin archivo
    assert _leer(eq, pid, contenido=b"").status_code == 400
    assert _leer(eq, pid, nombre="cosa.exe", tipo="application/x-msdownload").status_code == 400
    assert _leer(eq, pid, contenido=b"x" * (8 * 1024 * 1024 + 1)).status_code == 400
    assert eq.post(_url(pid, "ensayo"), json={}).status_code == 400                    # no es multipart
    assert _usos(sid) == []


def test_el_tope_de_lecturas_por_usuario_da_429(monkeypatch):
    pid, sid, eq = _mundo_listo()
    monkeypatch.setenv("XSII_RECIBOS_TOPE", "2")
    main._xsii_recibos_marcas.clear()
    assert _leer(eq, pid).status_code == 200 and _leer(eq, pid).status_code == 200
    r = _leer(eq, pid)
    assert r.status_code == 429 and "recibos" in r.json()["detail"]
    assert len(_usos(sid)) == 2                                                     # el tercero no gastó
    otro = _equipo()                                                               # el tope es por usuario
    assert _leer(otro, pid).status_code == 200
    main._xsii_recibos_marcas.clear()


def test_proyecto_sin_sindicato_inexistente_demo_y_sin_sesion(monkeypatch):
    pid, _sid, eq = _mundo(con_sindicato=False)
    r = _leer(eq, pid)
    assert r.status_code == 409 and "sindicato" in r.json()["detail"]
    r = eq.post(_url(pid, "carga"), json={"conceptos": [_item()]})
    assert r.status_code == 409
    for n in (pid + 100000, 0, 2 ** 31):
        assert _leer(eq, n).status_code == 404
        assert eq.post(_url(n, "carga"), json={"conceptos": [_item()]}).status_code == 404
    pid2, _s, eq2 = _mundo_listo()
    anonimo = TestClient(main.app, follow_redirects=False)
    assert anonimo.post(_url(pid2, "ensayo"), files={"archivo": ("r.png", b"x", "image/png")}).status_code == 403
    assert anonimo.post(_url(pid2, "carga"), json={"conceptos": [_item()]}).status_code == 403
    baja = _equipo(activo=False)
    assert _leer(baja, pid2).status_code == 401
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    assert _leer(eq2, pid2).status_code == 404
    assert eq2.post(_url(pid2, "carga"), json={"conceptos": [_item()]}).status_code == 404
    assert eq2.get(_url(pid2)).status_code == 404


def test_la_carga_escribe_revisado_deja_un_movimiento_de_numeros_y_no_confirma():
    pid, sid, eq = _mundo_listo()
    antes_ctrl = _tarea(eq, pid, C)
    assert antes_ctrl["control"]["estado"] == "incompleta" and "REC-05" in {
        t["codigo"] for t in eq.get(f"{BASE}/p/{pid}/tablero").json()["tareas"]}
    with db.get_session() as s:
        s.add(db.Concepto(sindicato_id=sid, codigo="CUOTA", nombre="Cuota sindical", tipo="descuento",
                          categoria_sindical="afiliacion"))
        s.add(db.Concepto(sindicato_id=sid, codigo="YA", nombre="Ya estaba", tipo="ingreso"))
        s.commit()
    cuerpo = {"conceptos": [
        _item(codigo="PRE", descripcion="Premio por presentismo", cuit_empleador=CUIT_A),
        _item(codigo="VIA", descripcion="Viático", rubro="no_remunerativo"),
        _item(codigo="SEP", descripcion="Cuota mutual", rubro="descuento", categoria_sindical="afiliacion",
              cuit_empleador="30-71234567-1", codigo_generico="CUOTA"),
        _item(codigo="YA", descripcion="Ya estaba otra vez")], "recibos_leidos": 37}
    r = eq.post(_url(pid, "carga"), json=cuerpo)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["carga"] == {"cargados": 3, "repetidos": 1, "recibos_leidos": 37}
    assert set(j) >= {"control", "destrabo", "carga"} and j["tarea"]["codigo"] == C
    por = {c.codigo: c for c in _conceptos(sid)}
    assert por["PRE"].tipo == "ingreso" and por["PRE"].remunerativo is True and por["PRE"].pendiente_revision is False
    assert por["PRE"].cuit_empleador == CUIT_A
    assert por["VIA"].remunerativo is False and por["VIA"].tipo == "ingreso" and por["VIA"].cuit_empleador is None
    assert (por["SEP"].tipo, por["SEP"].categoria_sindical, por["SEP"].codigo_generico) == ("descuento", "afiliacion", "CUOTA")
    assert por["YA"].nombre == "Ya estaba"                                       # no se tocó
    # el movimiento lleva solo números
    (m,) = _movs(pid, "asistida_carga")
    assert m.codigo == C and m.clave_insumo == ""
    assert m.cantidades == {"cargados": 3, "repetidos": 1, "recibos_leidos": 37}
    assert "37" in m.texto and "3 conceptos" in m.texto
    for palabra in ("PRE", "VIA", "SEP", "Premio", CUIT_A, "Viático"):
        assert palabra not in m.texto and palabra not in json.dumps(m.cantidades)
    # no confirma la tarea ni marca un insumo
    with db.get_session() as s:
        assert [i for i in db.xsii_insumos_activos(s, pid) if i != "recibos_muestra"] == []
        assert not [d for d in db.xsii_decisiones_activas(s, pid).get(C, [])]


def test_despues_de_cargar_el_control_de_rec04_pasa():
    pid, sid, eq = _mundo_listo()
    assert _tarea(eq, pid, C)["control"]["estado"] == "incompleta"
    _cargar_uno(eq, pid)
    ctrl = _tarea(eq, pid, C)["control"]
    assert ctrl["estado"] == "completa", ctrl
    assert {c["valor"] for c in ctrl["cifras"]} >= {1, 0}


def test_la_carga_es_todo_o_nada_y_dice_cual_item_fallo():
    pid, sid, eq = _mundo_listo()
    antes = len(_conceptos(sid))
    r = eq.post(_url(pid, "carga"), json={"conceptos": [
        _item(codigo="BIEN1"), _item(codigo="MAL", cuit_empleador="30123456789"), _item(codigo="BIEN2"),
        _item(codigo="MAL2", rubro="regalo")]})
    assert r.status_code == 400
    j = r.json()
    assert "2 conceptos" in j["detail"]
    assert [(d["indice"], d["campo"]) for d in j["detalle"]] == [(1, "cuit_empleador"), (3, "rubro")]
    assert all(d["mensaje"] for d in j["detalle"])
    assert len(_conceptos(sid)) == antes and _movs(pid, "asistida_carga") == []
    for malo in ({"conceptos": []}, {}, {"conceptos": [_item()], "recibos_leidos": "x"}):
        assert eq.post(_url(pid, "carga"), json=malo).status_code == 400
    assert eq.post(_url(pid, "carga"), content=b"no es json",
                   headers={"content-type": "application/json"}).status_code == 400
    assert eq.post(_url(pid, "carga"), content=b"{}", headers={"content-type": "text/plain"}).status_code == 400


def test_si_todos_ya_existian_no_hay_nada_que_cargar():
    pid, sid, eq = _mundo_listo()
    _cargar_uno(eq, pid)
    r = eq.post(_url(pid, "carga"), json={"conceptos": [_item(codigo="PRE", cuit_empleador=CUIT_A)]})
    assert r.status_code == 409 and "ya existían" in r.json()["detail"]
    assert len(_movs(pid, "asistida_carga")) == 1


def test_con_la_tarea_bloqueada_la_carga_es_409_pero_el_ensayo_anda():
    pid, sid, eq = _mundo()                      # REC-01 sin resolver: REC-04 está bloqueada
    assert _leer(eq, pid).status_code == 200
    r = eq.post(_url(pid, "carga"), json={"conceptos": [_item()]})
    assert r.status_code == 409 and "resuelta" in r.json()["detail"]
    assert _propios(sid) == []


def test_aislamiento_un_generico_ajeno_no_vale_y_no_se_toca_el_otro_sindicato():
    pid, sid, eq = _mundo_listo()
    ajeno = _sindicato()
    with db.get_session() as s:
        s.add(db.Concepto(sindicato_id=ajeno, codigo="SOLO-AJENO", nombre="Ajeno", tipo="ingreso"))
        s.commit()
    r = eq.post(_url(pid, "carga"), json={"conceptos": [_item(cuit_empleador=CUIT_A, codigo_generico="SOLO-AJENO")]})
    assert r.status_code == 400 and r.json()["detalle"][0]["campo"] == "codigo_generico"
    _cargar_uno(eq, pid)
    assert [c.codigo for c in _propios(ajeno)] == ["SOLO-AJENO"]
    assert [c.codigo for c in _propios(sid)] == ["PRE"]


def test_el_catalogo_apunta_a_leer_los_recibos_de_muestra():
    from xsii.proyectos.colm3na import catalogo
    t = next(x for x in catalogo.TAREAS if x.codigo == C)
    assert any("Leer los recibos de muestra" in p for p in t.pasos)
    assert not any("/admin" in p or "Aprendizaje" in p for p in t.pasos)


def test_las_cargas_en_paralelo_de_un_mismo_sindicato_no_duplican():
    """Dos proyectos apuntan al mismo sindicato: el candado por sindicato serializa."""
    import threading
    pid, sid, eq = _mundo_listo()
    with db.get_session() as s:
        otro = db.impl_crear_proyecto(s, "Otro proyecto " + str(sid), EQ, sindicato_id=sid).id
    _listo(eq, otro)
    resultados = []

    def cargar(p):
        resultados.append(eq.post(_url(p, "carga"), json={"conceptos": [_item(codigo="CARRERA")]}).status_code)
    hilos = [threading.Thread(target=cargar, args=(p,)) for p in (pid, otro)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(resultados) == [200, 409]
    assert len([c for c in _conceptos(sid) if c.codigo == "CARRERA"]) == 1
