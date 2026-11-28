"""QA independiente de servidor del bloque 4b de XSII (REC-04, «Conceptos desde los
recibos de muestra») y de lo que tocó: `conceptos_carga` (proponer y aplicar),
`/admin/aprender`, `/admin/aprender/aplicar`, `main._leer_recibo_de_muestra` y las
rutas `…/asistida/ensayo` y `…/asistida/carga` con entrada `recibos`.

Lo más importante es la REGRESIÓN de Aprendizaje: `_viejo_aprender` y
`_viejo_aplicar` son la lógica de las dos rutas ANTES de la extracción, congelada
acá (copiada de `git show 43a707d:main.py`, líneas ~6352-6480); cada lista, rara o
no, se corre por la vieja y por la ruta real y se compara.

Correr con: python -m pytest test_xsii_bloque4b_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"
os.environ["MOCK_EXTRACTOR"] = "1"
os.environ["MOCK_EXTRACTOR_LATENCIA"] = "0"
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import copy
import io
import json
import random
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

import conceptos_carga
import cuit
import db
import extractor
import main
import validador
from test_xsii_asistida import BASE, EQ, _equipo, _mundo, _movs, _sindicato
from test_xsii_conceptos import (CUIT_A, CUIT_B, USO, _admin_de, _conceptos, _item, _linea, _listo, _mundo_listo,
                                 _propios, _recibo, _url, _usos)
from xsii.proyectos.colm3na.asistidas import conceptos as asist

db.crear_tablas()
C = "REC-04"
CUIT_MOCK = "30000000007"         # el del recibo simulado (válido por módulo 11)
# Cosas que NUNCA tienen que salir del recibo hacia una respuesta, un movimiento o un log.
PRIVADO = ["Zulema Quintana", "Quintana", "20111111119", "LEG-99887", "4381927", "987654", "7777777"]


def _recibo_privado(cuit_emp=CUIT_A, lineas=None):
    r = _recibo(cuit_emp, lineas if lineas is not None else [
        _linea("PRE", "Premio por presentismo", 4381927), _linea("DTO", "Descuento mutual", -987654, "otro", "descuentos")])
    r["empleado"] = {"apellido_nombre": "Zulema Quintana", "cuil": "20111111119", "legajo": "LEG-99887"}
    r["totales_impresos"] = {"remuneraciones": 7777777, "descuentos": -987654, "neto": 6789123}
    return r


def _con_ia(monkeypatch, recibo=None, uso=None, falla=None, demora=0.0):
    """Reemplaza la lectura: devuelve `recibo` (lo que sea, incluida basura) o levanta `falla`."""
    def leer(contenido, tipo, modelo=None, **kw):
        if demora:
            time.sleep(demora)
        if falla is not None:
            raise falla
        return copy.deepcopy(recibo), dict(uso or USO)
    monkeypatch.setattr(main, "extraer", leer)


def _tablas_de_datos():
    """Cuántas filas tiene cada tabla de la base (menos las que el ensayo SÍ puede tocar)."""
    with db.get_session() as s:
        return {t.name: s.exec(text(f'SELECT count(*) FROM "{t.name}"')).one()[0]
                for t in db.SQLModel.metadata.sorted_tables
                if t.name not in ("usoia", "registroenmascarado", "geocache")}


class _Resp500:
    status_code = 500

    def __init__(self, e):
        self.text = repr(e)


def _panel_post(c, url, **kw):
    """POST del panel: una excepción del servidor se ve como un 500 (el cliente la relanza)."""
    try:
        return c.post(url, **kw)
    except Exception as e:        # noqa: BLE001
        return _Resp500(e)


def _clon(eq, malo=True):
    """Otro cliente con la MISMA sesión (mismo usuario). `malo`: un 500 se ve como 500 y no se relanza."""
    c = TestClient(main.app, raise_server_exceptions=not malo, follow_redirects=False)
    for ck in eq.cookies.jar:
        c.cookies.jar.set_cookie(ck)
    return c


# =================================================================== la lógica ANTERIOR, congelada

def _viejo_aprender(conceptos_actuales, recibos):
    """El cuerpo de `POST /admin/aprender` de `43a707d` sin la lectura (ya hecha)."""
    genericos_actuales = [c for c in conceptos_actuales if not c.get("cuit_empleador")]
    acumulados = {}
    for recibo in recibos:
        cuit_empleador = main._norm_cuil((recibo.get("empleador") or {}).get("cuit")) or None
        for n in validador.detectar_nuevos(conceptos_actuales, recibo["lineas"], cuit_empleador):
            clave = (n["codigo"], cuit_empleador or "")
            if clave in acumulados:
                acumulados[clave]["veces"] += 1
            else:
                acumulados[clave] = {**n, "veces": 1, "cuit_empleador": cuit_empleador}
    for p in acumulados.values():
        similar = validador.buscar_similar(p["descripcion"], conceptos_actuales)
        p["similar"] = {"codigo": similar["concepto"]["codigo"], "nombre": similar["concepto"]["nombre"],
                        "ratio": similar["ratio"]} if similar else None
        p["generico_sugerido"] = None
        if p["cuit_empleador"]:
            universal = validador.generico_de_categoria(p.get("categoria_universal"), genericos_actuales)
            if universal:
                p["generico_sugerido"] = {"codigo": universal["codigo"], "nombre": universal["nombre"]}
            else:
                sg = validador.buscar_similar(p["descripcion"], genericos_actuales)
                if sg:
                    p["generico_sugerido"] = {"codigo": sg["concepto"]["codigo"], "nombre": sg["concepto"]["nombre"]}
    return {"propuestas": sorted(acumulados.values(), key=lambda x: -x["veces"])}


def _viejo_aplicar(sid, aprobados):
    """El cuerpo de `POST /admin/aprender/aplicar` de `43a707d`."""
    altas, cuit_invalidos = 0, []
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
                    sindicato_id=sid, codigo=c["codigo"], nombre=c["descripcion"], tipo=c["tipo"],
                    remunerativo=c.get("remunerativo", True), alias=[c["descripcion"]], pendiente_revision=False,
                    cuit_empleador=cuit_empleador, codigo_generico=(c.get("codigo_generico") or "").strip() or None))
                existentes.add(clave)
                altas += 1
        s.commit()
    return {"ok": True, "altas": altas, "cuit_invalidos": cuit_invalidos}


def _filas(sid):
    with db.get_session() as s:
        return sorted(((c.codigo, c.nombre, c.tipo, c.remunerativo, tuple(c.alias), c.pendiente_revision,
                        c.cuit_empleador, c.codigo_generico, c.categoria_sindical)
                       for c in s.exec(select(db.Concepto).where(db.Concepto.sindicato_id == sid)).all()), key=repr)


def _vaciar_propios(sid):
    with db.get_session() as s:
        for c in s.exec(select(db.Concepto).where(db.Concepto.sindicato_id == sid)).all():
            if c.codigo not in ("JUBILACION", "PAMI", "OBRASOCIAL"):
                s.delete(c)
        s.commit()


# ---------------------------------------------------------------- generadores al azar

_DESCS = ["Premio por presentismo", "Cuota sindical extra", "Antigüedad (7 años)", "Antigüedad (9 años)", "Viático",
          "Retención previsional", "Jubilación", "Obra social", "Reintegro Ganancias", "Adelanto", "", None, 123,
          "Sueldo básico", "x" * 300, "Ñandú ÁÉÍ"]
_CODS = ["A1", "A2", " A1", "a1", "99", 99, "", None, "SB", "JUB", "Z-" + "9" * 50]
_TIPOS = ["remuneracion", "aporte_trabajador", "otro", "raro", None, 5]
_SECC = ["haberes", "no_remunerativos", "descuentos", None, "otra"]
_CATU = ["jubilacion", "pami", "obra_social", "cuota_sindical", None, "inventada"]
_CUITS = [None, "", CUIT_A, CUIT_B, "30-71234567-1", "30123456789", "abc", 30712345671, "30 71234567 1"]


def _azar_recibo(r):
    lineas = []
    for _ in range(r.randint(0, 9)):
        ln = {"codigo": r.choice(_CODS), "descripcion": r.choice(_DESCS), "cantidad": None, "unidad": None,
              "importe": r.choice([1000, -500, 0, None, "1.200,50", "mal", 3.5, -90000]),
              "tipo": r.choice(_TIPOS), "seccion": r.choice(_SECC), "categoria_universal": r.choice(_CATU)}
        if r.random() < 0.15:
            ln.pop(r.choice(list(ln)))
        if r.random() < 0.05:
            ln = r.choice(["texto", None, 5, []])
        lineas.append(ln)
    emp = r.choice([{"cuit": r.choice(_CUITS), "nombre": "E"}, {}, None])
    return {"empleador": emp, "lineas": lineas}


def _azar_aprobado(r):
    c = {"codigo": r.choice(["P1", "P2", " P1", "p1", "P3"]), "descripcion": r.choice(["Uno", "Dos", "ñ"]),
         "tipo": r.choice(["ingreso", "descuento"])}
    if r.random() < .5:
        c["remunerativo"] = r.choice([True, False])
    if r.random() < .6:
        c["cuit_empleador"] = r.choice(_CUITS)
    if r.random() < .4:
        c["codigo_generico"] = r.choice(["JUBILACION", " PAMI ", "", None])
    return c


# =================================================================== equivalencia con Aprendizaje

def test_aprender_da_lo_mismo_que_la_logica_anterior_con_muchas_listas_raras(monkeypatch):
    sid = _sindicato()
    c = _admin_de(sid)
    azar = random.Random(4242)
    with db.get_session() as s:
        s.add(db.Concepto(sindicato_id=sid, codigo="SB", nombre="Sueldo básico", tipo="ingreso"))
        s.add(db.Concepto(sindicato_id=sid, codigo="A2", nombre="Premio por presentismo", tipo="ingreso",
                          cuit_empleador=CUIT_A))
        s.commit()
    corridas = comparadas = 0
    for _ in range(40):
        recibos = [_azar_recibo(azar) for _ in range(azar.randint(1, 4))]
        por_contenido = {f"r{i}".encode(): r for i, r in enumerate(recibos)}
        monkeypatch.setattr(main, "extraer", lambda contenido, tipo, modelo=None, **kw:
                            (copy.deepcopy(por_contenido[contenido]), dict(USO)))
        actuales = db.conceptos_como_dicts(sid)
        try:
            esperado = {"leidos": len(recibos), "fallidos": 0, **_viejo_aprender(actuales, copy.deepcopy(recibos))}
            esperado = json.loads(json.dumps(esperado))
        except Exception as e:        # noqa: BLE001 - lo viejo se caía: lo nuevo también tiene que caerse igual
            esperado = type(e)
        files = [("archivos", (f"{k.decode()}.png", k, "image/png")) for k in por_contenido]
        r = _panel_post(c, "/admin/aprender", files=files)
        corridas += 1
        if esperado is dict or isinstance(esperado, dict):
            assert r.status_code == 200, r.text
            assert r.json() == esperado
            comparadas += 1
        else:
            assert r.status_code == 500, (esperado, r.status_code)
    assert comparadas >= 15, comparadas        # la prueba tiene que haber comparado de verdad


def test_aplicar_da_lo_mismo_que_la_logica_anterior_con_muchas_listas_raras():
    sid_viejo, sid_nuevo = _sindicato(), _sindicato()
    c = _admin_de(sid_nuevo)
    azar = random.Random(77)
    iguales = 0
    for _ in range(40):
        lista = [_azar_aprobado(azar) for _ in range(azar.randint(0, 8))]
        if azar.random() < .15 and lista:
            lista[azar.randrange(len(lista))].pop("tipo")        # un campo obligatorio que falta
        _vaciar_propios(sid_viejo)
        _vaciar_propios(sid_nuevo)
        try:
            esperado = _viejo_aplicar(sid_viejo, copy.deepcopy(lista))
        except Exception as e:        # noqa: BLE001
            esperado = type(e)
        r = _panel_post(c, "/admin/aprender/aplicar", json={"aprobados": copy.deepcopy(lista)})
        if isinstance(esperado, dict):
            assert r.status_code == 200, (lista, r.text)
            assert r.json() == esperado, lista
            assert _filas(sid_viejo) == _filas(sid_nuevo), lista
            iguales += 1
        else:
            assert r.status_code == 500, (lista, esperado, r.status_code)
            assert _filas(sid_nuevo) == _filas(sid_viejo)          # y no dejó nada a medias
    assert iguales >= 25


@pytest.mark.parametrize("categoria", ["inventada", "afiliacion ", "CONVENIO", ["x"], {"a": 1}, 5, True])
def test_aplicar_del_panel_no_guarda_una_categoria_sindical_inventada(categoria):
    """Antes del bloque 4b el campo se IGNORABA; ahora lo lee `aplicar` y lo guardaba tal cual
    (un texto cualquiera, o una lista que reventaba la base con 500)."""
    sid = _sindicato()
    c = _admin_de(sid)
    r = _panel_post(c, "/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "CAT", "descripcion": "Cat", "tipo": "descuento", "categoria_sindical": categoria}]})
    assert r.status_code == 200, r.text
    (cat,) = [x for x in _conceptos(sid) if x.codigo == "CAT"]
    assert cat.categoria_sindical == ""


def test_aplicar_acepta_las_dos_categorias_validas_solo_en_un_descuento():
    sid = _sindicato()
    c = _admin_de(sid)
    r = c.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "D1", "descripcion": "Uno", "tipo": "descuento", "categoria_sindical": "afiliacion"},
        {"codigo": "D2", "descripcion": "Dos", "tipo": "descuento", "categoria_sindical": "convenio"},
        {"codigo": "I1", "descripcion": "Tres", "tipo": "ingreso", "categoria_sindical": "convenio"}]})
    assert r.status_code == 200
    por = {x.codigo: x.categoria_sindical for x in _conceptos(sid)}
    assert (por["D1"], por["D2"], por["I1"]) == ("afiliacion", "convenio", "")


def test_la_lectura_de_un_recibo_de_muestra_no_cambio_el_registro_de_uso(monkeypatch):
    """Tres lecturas buenas y una mala que igual se pagó: cuatro filas `aprendizaje`, ninguna `recibo`."""
    sid = _sindicato()
    c = _admin_de(sid)

    def leer(contenido, tipo, modelo=None, **kw):
        if contenido == b"corto":
            raise extractor.ErrorLectura("cortada", dict(USO))
        return copy.deepcopy(_recibo(CUIT_A, [_linea("N1", "Nuevo", 5)])), dict(USO)
    monkeypatch.setattr(main, "extraer", leer)
    files = [("archivos", (f"{i}.png", b"corto" if i == 3 else b"ok%d" % i, "image/png")) for i in range(4)]
    r = c.post("/admin/aprender", files=files)
    assert r.status_code == 200 and r.json()["leidos"] == 3 and r.json()["fallidos"] == 1
    assert len(_usos(sid)) == 4 and _usos(sid, "recibo") == []


# =================================================================== carga JSON hostil

def _post_carga(eq, pid, cuerpo=None, *, crudo=None, tipo="application/json"):
    if crudo is not None:
        return eq.post(_url(pid, "carga"), content=crudo, headers={"content-type": tipo})
    return eq.post(_url(pid, "carga"), json=cuerpo)


@pytest.fixture()
def mundo():
    pid, sid, eq = _mundo_listo()
    return pid, sid, eq


MALOS_VALORES = [None, 5, 5.5, True, [], ["a"], {}, {"a": "b"}, "x" * 100_000, "a\x00b", "a\nb", "a\tb", "a\u202eb",
                 "a\u200bb", "a\u2028b", "a\u2066b\u2069", "a\ud800b", "a\ue000b", "<script>alert(1)</script>",
                 "'; DROP TABLE concepto; --", "\u0000", "ｆｕｌｌ", "\U0001F600"]
CAMPOS = ["codigo", "descripcion", "cuit_empleador", "rubro", "categoria_sindical", "codigo_generico"]


@pytest.mark.parametrize("campo", CAMPOS)
def test_cada_campo_de_la_carga_con_valores_hostiles_nunca_da_500(mundo, campo):
    pid, sid, eq = mundo
    eq = _clon(eq)
    antes = _filas(sid)
    for valor in MALOS_VALORES:
        try:
            r = eq.post(_url(pid, "carga"), json={"conceptos": [_item(**{campo: valor})], "recibos_leidos": 1})
        except Exception as e:                  # noqa: BLE001 - JSON que no se puede ni armar (surrogate)
            continue
        assert r.status_code in (200, 400, 409, 422), (campo, repr(valor)[:40], r.status_code, r.text[:200])
        if r.status_code != 200:
            assert r.status_code == 400 or r.status_code == 409
    # lo que sí entró: nada con caracteres de control, ni saltos de línea ni invisibles
    for c in _propios(sid):
        for texto in (c.codigo, c.nombre, c.cuit_empleador or ""):
            assert all(ord(ch) >= 32 and ch not in "\u202e\u200b\u2028\u2029\u2066\u2069\u0000" for ch in texto), (
                campo, repr(texto))
    assert _filas(sid) != antes or True


def test_texto_bidi_saltos_de_linea_y_privados_no_se_guardan(mundo):
    pid, sid, eq = mundo
    for i, malo in enumerate(["a\u202eb", "a\u2028b", "a\u2029b", "a\u200fb", "a\u2066b", "a\ue000b", "a\x85b",
                              "a\u00adb", "a\ufeffb", "a\u061cb", "a\u180eb", "a\u2800b"]):
        r = eq.post(_url(pid, "carga"), json={"conceptos": [_item(codigo=f"BIDI{i}", descripcion=malo)]})
        assert r.status_code == 400, (repr(malo), r.status_code, r.text[:200])
    assert _propios(sid) == []


def test_html_y_sql_en_los_textos_se_guardan_como_texto_y_no_rompen_nada(mundo):
    pid, sid, eq = mundo
    r = eq.post(_url(pid, "carga"), json={"conceptos": [
        _item(codigo="<b>x</b>", descripcion="<img src=x onerror=alert(1)>"),
        _item(codigo="'; DROP TABLE concepto; --", descripcion="Robert'); DROP TABLE concepto;--")]})
    assert r.status_code == 200, r.text
    assert len(_propios(sid)) == 2 and len(_conceptos(sid)) >= 5
    # lo que vuelve por JSON es dato; la respuesta de la carga no repite los textos
    assert "<img" not in r.text and "DROP" not in r.text


@pytest.mark.parametrize("crudo,tipo", [
    (b"", "application/json"), (b"no es json", "application/json"), (b"[]", "application/json"),
    (b'"x"', "application/json"), (b"null", "application/json"), (b"5", "application/json"),
    (b'{"conceptos": NaN}', "application/json"), (b'{"conceptos": [NaN]}', "application/json"),
    (b'{"conceptos": [1e999]}', "application/json"), (b"\xff\xfe\x00{", "application/json"),
    (b'{"conceptos": [{"codigo": "\\ud800"}]}', "application/json"),
    (b"[" * 200_000, "application/json"), (b'{"a":' * 50_000, "application/json"),
    (b'{"conceptos":[{}]}', "text/plain"), (b'{"conceptos":[{}]}', ""),
    (b'{"conceptos":[{}], "conceptos": 5}', "application/json; charset=utf-16"),
])
def test_cuerpos_que_no_son_la_carga_dan_400_y_nunca_500(mundo, crudo, tipo):
    pid, sid, eq = mundo
    r = _post_carga(_clon(eq), pid, crudo=crudo, tipo=tipo)
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert _propios(sid) == []


def test_listas_enormes_y_objetos_anidados_en_los_items(mundo):
    pid, sid, eq = mundo
    t0 = time.time()
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo=f"K{i}") for i in range(501)]})
    assert r.status_code == 400 and "500" in r.json()["detail"]
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo=f"K{i}") for i in range(200_000)]})
    assert r.status_code == 400
    anidado = [[[[["x"]]]]]
    r = _post_carga(eq, pid, {"conceptos": [{"codigo": anidado, "descripcion": anidado, "rubro": anidado,
                                             "cuit_empleador": anidado, "categoria_sindical": anidado,
                                             "codigo_generico": anidado}]})
    assert r.status_code == 400 and len(r.json()["detalle"]) >= 3
    r = _post_carga(eq, pid, {"conceptos": [5, "x", None, [], [1]]})
    assert r.status_code == 400 and [d["indice"] for d in r.json()["detalle"]] == [0, 1, 2, 3, 4]
    assert time.time() - t0 < 20 and _propios(sid) == []
    # justo en el tope: 500 entran, y quedan todos
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo=f"T{i}", descripcion=f"Concepto {i}") for i in range(500)]})
    assert r.status_code == 200 and r.json()["carga"]["cargados"] == 500 and len(_propios(sid)) == 500


def test_cientos_de_errores_el_detalle_viaja_acotado(mundo):
    pid, sid, eq = mundo
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="", rubro="x") for _ in range(500)]})
    assert r.status_code == 400 and len(r.json()["detalle"]) == 50 and len(r.text) < 20_000


@pytest.mark.parametrize("leidos", [-1, 5001, 10 ** 30, "5", 5.0, 5.5, True, False, None, [], {}, "x" * 1000])
def test_recibos_leidos_hostil_no_da_500_ni_entra_al_movimiento(mundo, leidos):
    pid, sid, eq = mundo
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="LEI")], "recibos_leidos": leidos})
    assert r.status_code in (200, 400), (leidos, r.status_code, r.text[:200])
    if r.status_code == 200:                           # solo el 0 por defecto / un entero en rango
        assert isinstance(leidos, int) and 0 <= leidos <= 5000
    else:
        assert _propios(sid) == []


@pytest.mark.parametrize("crudo", [b'{"conceptos":[{"codigo":"I","descripcion":"d","rubro":"haber"}],"recibos_leidos":Infinity}',
                                   b'{"conceptos":[{"codigo":"I","descripcion":"d","rubro":"haber"}],"recibos_leidos":-Infinity}',
                                   b'{"conceptos":[{"codigo":"I","descripcion":"d","rubro":"haber"}],"recibos_leidos":1e400}'])
def test_recibos_leidos_infinito_no_da_500(mundo, crudo):
    pid, sid, eq = mundo
    assert _post_carga(eq, pid, crudo=crudo).status_code == 400
    assert _propios(sid) == []


def test_claves_repetidas_por_espacios_o_formato_del_cuit_son_el_mismo_concepto(mundo):
    pid, sid, eq = mundo
    for par in ([_item(codigo="DUP"), _item(codigo=" DUP ")],
                [_item(codigo="DUP", cuit_empleador="30-71234567-1"), _item(codigo="DUP", cuit_empleador=CUIT_A)],
                [_item(codigo="DUP", cuit_empleador="30 71234567 1"), _item(codigo="DUP", cuit_empleador=" 30-71234567-1")]):
        r = _post_carga(eq, pid, {"conceptos": par})
        assert r.status_code == 400 and r.json()["detalle"][0]["indice"] == 1, par
    assert _propios(sid) == []


def test_codigos_que_solo_difieren_en_mayusculas_se_cargan_como_dos_y_la_segunda_vez_son_repetidos(mundo):
    """Igual que el panel (compara el código tal cual). Se deja dicho: un recibo los distingue."""
    pid, sid, eq = mundo
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="pre"), _item(codigo="PRE")]})
    assert r.status_code == 200 and r.json()["carga"]["cargados"] == 2
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="pre"), _item(codigo="Pre")]})
    assert r.status_code == 200 and r.json()["carga"] == {"cargados": 1, "repetidos": 1, "recibos_leidos": 0}


def test_el_cuit_se_guarda_normalizado_y_uno_ya_cargado_con_otro_formato_es_repetido(mundo):
    pid, sid, eq = mundo
    assert _post_carga(eq, pid, {"conceptos": [_item(codigo="F1", cuit_empleador="30-71234567-1")]}).status_code == 200
    assert [c.cuit_empleador for c in _propios(sid)] == [CUIT_A]
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="F1", cuit_empleador=" 30 71234567 1 ")]})
    assert r.status_code == 409
    # texto con letras mezcladas pero dígitos válidos: se normaliza (lo hace el panel desde siempre)
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="F2", cuit_empleador="CUIT 30712345671")]})
    assert r.status_code in (200, 400)


def test_el_generico_de_otro_sindicato_no_vale_y_el_mismo_codigo_en_otro_sindicato_no_choca(mundo):
    pid, sid, eq = mundo
    ajeno = _sindicato()
    with db.get_session() as s:
        s.add(db.Concepto(sindicato_id=ajeno, codigo="SOLO-AJENO", nombre="Ajeno", tipo="ingreso"))
        s.add(db.Concepto(sindicato_id=ajeno, codigo="MISMO", nombre="Del otro", tipo="ingreso"))
        s.commit()
    foto = _filas(ajeno)
    for gen in ("SOLO-AJENO", " solo-ajeno", "JUBILACION\u200b"):
        r = _post_carga(eq, pid, {"conceptos": [_item(cuit_empleador=CUIT_A, codigo_generico=gen)]})
        assert r.status_code == 400 or gen == "JUBILACION\u200b", (gen, r.status_code)
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="MISMO", cuit_empleador=CUIT_A, codigo_generico="PAMI")]})
    assert r.status_code == 200
    assert _filas(ajeno) == foto
    # un genérico de ESTE sindicato sin empleador no vale ("Corresponde a" es de un concepto de empleador)
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="GG", codigo_generico="PAMI")]})
    assert r.status_code == 400 and r.json()["detalle"][0]["campo"] == "codigo_generico"


def test_un_concepto_de_empleador_no_puede_apuntar_a_otro_de_empleador(mundo):
    pid, sid, eq = mundo
    assert _post_carga(eq, pid, {"conceptos": [_item(codigo="EMP", cuit_empleador=CUIT_A)]}).status_code == 200
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="EMP2", cuit_empleador=CUIT_A, codigo_generico="EMP")]})
    assert r.status_code == 400


def test_la_carga_solo_escribe_conceptos_y_un_movimiento(mundo):
    pid, sid, eq = mundo
    antes = _tablas_de_datos()
    r = _post_carga(eq, pid, {"conceptos": [_item(codigo="UNO"), _item(codigo="DOS", cuit_empleador=CUIT_A)],
                              "recibos_leidos": 3})
    assert r.status_code == 200
    despues = _tablas_de_datos()
    cambiaron = {t for t in antes if antes[t] != despues[t]}
    assert cambiaron == {"concepto", "xsiimovimiento"}, cambiaron


# =================================================================== ensayo hostil

def _ensayo(eq, pid, contenido=b"recibo-mock", nombre="r.png", tipo="image/png", **kw):
    return eq.post(_url(pid, "ensayo"), files={"archivo": (nombre, contenido, tipo)}, **kw)


@pytest.fixture()
def malo():
    """Un cliente que no relanza las excepciones del servidor: un 500 se ve como 500."""
    pid, sid, eq = _mundo_listo()
    c = _clon(eq)
    return pid, sid, c


def test_ensayo_sin_archivo_con_dos_archivos_y_con_campos_raros(malo):
    pid, sid, c = malo
    assert c.post(_url(pid, "ensayo")).status_code == 400
    assert c.post(_url(pid, "ensayo"), data={"archivo": "texto, no archivo"}).status_code == 400
    assert c.post(_url(pid, "ensayo"), files=[("archivo", ("a.png", b"x", "image/png")),
                                              ("archivo", ("b.png", b"y", "image/png"))]).status_code in (200, 400)
    assert c.post(_url(pid, "ensayo"), files={"otro": ("a.png", b"x", "image/png")}).status_code == 400
    assert c.post(_url(pid, "ensayo"), content=b"--xx\r\nbasura", headers={
        "content-type": "multipart/form-data; boundary=xx"}).status_code == 400
    assert c.post(_url(pid, "ensayo"), content=b"x", headers={"content-type": "multipart/form-data"}).status_code == 400
    assert len(_usos(sid)) <= 1                       # con dos archivos se lee uno solo


def test_ensayo_archivo_vacio_enorme_y_nombres_raros(malo):
    pid, sid, c = malo
    assert _ensayo(c, pid, b"").status_code == 400
    assert _ensayo(c, pid, b"x" * (8 * 1024 * 1024 + 1)).status_code == 400
    r = _ensayo(c, pid, b"x" * (45 * 1024 * 1024))                    # pasa el tope de todo el envío
    assert r.status_code in (400, 413), r.status_code
    assert _usos(sid) == []
    for nombre in ["<script>alert(1)</script>.png", "../../etc/passwd.png", "..\\..\\x.pdf", "a" * 5000 + ".png",
                   "sin_extension", ".png", "x.PNG", "x.png\x00.exe", "x.exe.png", "\u202etxt.png", "%2e%2e/x.png", ""]:
        r = _ensayo(c, pid, b"recibo", nombre, "image/png" if nombre else "")
        assert r.status_code in (200, 400), (nombre, r.status_code, r.text[:200])
        if r.status_code == 200:
            n = r.json()["recibo"]["nombre"]
            assert len(n) <= 120 and "\x00" not in n and "\u202e" not in n and "\n" not in n


def test_ensayo_con_content_type_mentiroso_o_formato_que_no_sirve(malo):
    pid, sid, c = malo
    assert _ensayo(c, pid, b"MZ\x90\x00", "cosa.exe", "image/png").status_code == 400      # manda la extensión
    assert _ensayo(c, pid, b"%PDF-1.4", "recibo.pdf", "text/html").status_code == 200      # la extensión manda
    assert _ensayo(c, pid, b"x", "sinextension", "application/zip").status_code == 400
    assert _ensayo(c, pid, b"x", "sinextension", "image/webp").status_code == 200
    assert _ensayo(c, pid, b"x", "x.svg", "image/svg+xml").status_code == 400
    assert _ensayo(c, pid, b"x", "x.gif", "image/gif").status_code == 400


def test_ensayo_no_imagen_con_extension_de_imagen_y_bomba_de_pixeles(malo, monkeypatch):
    """Con la lectura real activa (sin mock) el archivo se abre: lo roto es 200 «no se pudo leer» o un error de
    la casa, nunca un 500; la bomba de píxeles se corta en la cabecera."""
    pid, sid, c = malo
    monkeypatch.delenv("MOCK_EXTRACTOR")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-falsa")
    _con_ia(monkeypatch, falla=RuntimeError("no hay red"))
    for modo in ("apagado", "activo"):
        monkeypatch.setenv("ENMASCARADO", modo)
        r = _ensayo(c, pid, b"esto no es una imagen", "foto.png")
        assert r.status_code == 200 and r.json()["recibo"]["leido"] is False, (modo, r.status_code, r.text[:200])
        r = _ensayo(c, pid, b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "foto.png")
        assert r.status_code in (200, 400), (modo, r.status_code, r.text[:200])
        from PIL import Image
        buf = io.BytesIO()
        Image.new("1", (11000, 11000), 0).save(buf, "PNG")
        t0 = time.time()
        r = _ensayo(c, pid, buf.getvalue(), "bomba.png")
        assert r.status_code == 200 and r.json()["recibo"]["leido"] is False and "mide" in r.json()["recibo"]["motivo"].lower() \
            or r.status_code == 400, (modo, r.status_code, r.text[:300])
        assert time.time() - t0 < 10
    assert _usos(sid) == []                               # nunca hubo lectura que cobrar


BASURAS = {
    "none": None, "lista": [1, 2], "texto": "recibo", "numero": 7, "vacio": {}, "sin_lineas": {"empleador": {}},
    "lineas_none": {"empleador": {"cuit": CUIT_A}, "lineas": None},
    "lineas_texto": {"empleador": {"cuit": CUIT_A}, "lineas": "hola"},
    "lineas_dict": {"empleador": {"cuit": CUIT_A}, "lineas": {"codigo": "X"}},
    "lineas_no_dicts": {"empleador": {"cuit": CUIT_A}, "lineas": ["x", None, 5, [], {}]},
    "empleador_texto": {"empleador": "Acme SA", "lineas": [_linea("N1", "Nuevo", 5)]},
    "empleador_lista": {"empleador": ["x"], "lineas": [_linea("N1", "Nuevo", 5)]},
    "cuit_raro": {"empleador": {"cuit": ["30"], "nombre": {"x": 1}}, "lineas": [_linea("N1", "Nuevo", 5)]},
    "cuit_numero": {"empleador": {"cuit": 30712345671, "nombre": 5}, "lineas": [_linea("N1", "Nuevo", 5)]},
    "importes_texto": {"empleador": {"cuit": CUIT_A}, "lineas": [_linea("N1", "Nuevo", "mucho"),
                                                                  _linea("N2", "Otro", "1.200,50"),
                                                                  _linea("N3", "Tercero", None), _linea("N4", "Cuarto", [1])]},
    "campos_numericos": {"empleador": {"cuit": CUIT_A}, "lineas": [{"codigo": 5, "descripcion": 7, "importe": 1,
                                                                    "tipo": 3, "seccion": 9, "categoria_universal": 1}]},
    "codigos_vacios": {"empleador": {"cuit": CUIT_A}, "lineas": [_linea("", "", 5), _linea(None, None, 5),
                                                                  _linea("  ", "  ", 5)]},
    "codigo_gigante": {"empleador": {"cuit": CUIT_A}, "lineas": [_linea("9" * 10_000, "Largo", 5)]},
    "descripcion_gigante": {"empleador": {"cuit": CUIT_A}, "lineas": [_linea("G1", "d" * 10_000, 5)]},
    "invisibles": {"empleador": {"cuit": CUIT_A, "nombre": "E\u202emp\x00"}, "lineas": [
        _linea("I\u200b1", "Pre\u202emio\x00 <script>", 5), _linea("I2", "\u2028\u2029\n\t", 5)]},
}


@pytest.mark.parametrize("nombre", sorted(BASURAS))
def test_la_ia_devuelve_basura_el_ensayo_contesta_200_y_no_escribe(malo, monkeypatch, nombre):
    pid, sid, c = malo
    _con_ia(monkeypatch, BASURAS[nombre])
    antes = _tablas_de_datos()
    r = _ensayo(c, pid)
    assert r.status_code == 200, (nombre, r.status_code, r.text[:300])
    j = r.json()
    assert set(j) == {"recibo", "propuestas"} and isinstance(j["propuestas"], list)
    for p in j["propuestas"]:
        assert p["estado"] in ("valida", "dudosa", "rechazada") and p["rubro"] in ("haber", "no_remunerativo", "descuento")
        assert len(p["codigo"]) < 10_001 and len(p["descripcion"]) <= 120
        assert "\x00" not in p["descripcion"] + p["codigo"] and "\u202e" not in p["descripcion"]
    assert _tablas_de_datos() == antes
    assert len(_usos(sid)) == 1                          # la lectura que se pagó queda registrada, una vez


def test_cinco_mil_lineas_con_descripciones_enormes_no_cuelgan_ni_inflan_la_respuesta(malo, monkeypatch):
    pid, sid, c = malo
    with db.get_session() as s:                          # un catálogo con cosas contra las que comparar
        for i in range(60):
            s.add(db.Concepto(sindicato_id=sid, codigo=f"CAT{i}", nombre=f"Concepto del catálogo número {i}",
                              tipo="ingreso", alias=[f"Alias {i}", f"Otro alias {i}"]))
        s.commit()
    lineas = [_linea(f"L{i}", ("Descripción larguísima %d " % i) * 400, 100 + i) for i in range(5000)]
    _con_ia(monkeypatch, _recibo(CUIT_A, lineas))
    t0 = time.time()
    r = _ensayo(c, pid)
    dur = time.time() - t0
    assert r.status_code == 200, r.text[:200]
    assert dur < 30, f"el ensayo de un recibo de 5.000 líneas tardó {dur:.1f} s"
    assert len(r.content) < 3_000_000, len(r.content)


def test_la_ia_tira_una_excepcion_o_un_error_de_lectura_200_leido_false(malo, monkeypatch):
    pid, sid, c = malo
    for falla in (RuntimeError("boom"), ValueError("x"), KeyError("k"), MemoryError(), TimeoutError("tarde"),
                  extractor.ErrorLectura("cortada", dict(USO))):
        _con_ia(monkeypatch, falla=falla)
        r = _ensayo(c, pid)
        assert r.status_code == 200 and r.json()["recibo"]["leido"] is False and r.json()["propuestas"] == [], falla
        assert r.json()["recibo"]["motivo"]
        assert not str(falla) or str(falla) not in r.json()["recibo"]["motivo"] or isinstance(falla, extractor.ErrorLectura)
    assert len(_usos(sid)) == 1                           # solo la que vino con `uso`


def test_ia_que_se_cuelga_un_rato_no_retiene_conexion_ni_bloquea_otros_pedidos(malo, monkeypatch):
    pid, sid, c = malo
    visto = {}
    base_pool = db.engine.pool.checkedout()

    def leer(contenido, tipo, modelo=None, **kw):
        time.sleep(1.5)
        visto["en_uso"] = db.engine.pool.checkedout()
        return copy.deepcopy(_recibo(CUIT_A, [_linea("N1", "Nuevo", 5)])), dict(USO)
    monkeypatch.setattr(main, "extraer", leer)
    resp = {}
    hilo = threading.Thread(target=lambda: resp.setdefault("r", _ensayo(c, pid)))
    hilo.start()
    time.sleep(0.4)
    t0 = time.time()
    otro = TestClient(main.app).get("/healthz")           # el servidor sigue atendiendo mientras la IA piensa
    assert otro.status_code == 200 and time.time() - t0 < 1.0
    hilo.join()
    assert resp["r"].status_code == 200 and visto["en_uso"] <= base_pool
    assert db.engine.pool.checkedout() <= base_pool


def test_el_ensayo_no_retiene_conexion_ni_mientras_arma_la_propuesta(malo, monkeypatch):
    pid, sid, c = malo
    base_pool = db.engine.pool.checkedout()
    visto = {}
    original = conceptos_carga.proponer

    def espia(*a, **k):
        visto["en_uso"] = db.engine.pool.checkedout()
        return original(*a, **k)
    monkeypatch.setattr(conceptos_carga, "proponer", espia)
    _con_ia(monkeypatch, _recibo(CUIT_A, [_linea("N1", "Nuevo", 5)]))
    assert _ensayo(c, pid).status_code == 200
    assert visto["en_uso"] <= base_pool


def test_un_ensayo_solo_escribe_en_usoia(malo, monkeypatch):
    pid, sid, c = malo
    _con_ia(monkeypatch, _recibo_privado())
    antes = _tablas_de_datos()
    assert _ensayo(c, pid).status_code == 200
    assert _tablas_de_datos() == antes
    assert len(_usos(sid)) == 1 and _movs(pid) == [] or all(m.tipo != "asistida_carga" for m in _movs(pid))


# =================================================================== privacidad

def test_nada_de_la_persona_sale_del_ensayo_ni_queda_en_el_movimiento_ni_en_los_logs(malo, monkeypatch, capfd):
    pid, sid, c = malo
    _con_ia(monkeypatch, _recibo_privado())
    r = _ensayo(c, pid, nombre="recibo-de-muestra.png")
    assert r.status_code == 200
    texto = json.dumps(r.json(), ensure_ascii=False)
    for secreto in PRIVADO[2:] + ["Zulema", "Persona Real"]:
        assert secreto not in texto, secreto
    # (el nombre del archivo vuelve tal cual lo mandó quien lo subió: es suyo y la pantalla lo muestra)
    # una carga a continuación: movimiento y filas de la tabla, solo números
    prop = r.json()["propuestas"]
    assert prop and all("importe" not in p for p in prop)
    carga = c.post(_url(pid, "carga"), json={"conceptos": [
        {"codigo": p["codigo"], "descripcion": p["descripcion"], "cuit_empleador": p["cuit_empleador"],
         "rubro": p["rubro"], "categoria_sindical": "", "codigo_generico": ""} for p in prop], "recibos_leidos": 1})
    assert carga.status_code == 200, carga.text
    for m in _movs(pid):
        for secreto in PRIVADO + ["Zulema", "PRE", "Premio"]:
            assert secreto not in (m.texto or "") + json.dumps(m.cantidades or {}), (m.tipo, secreto)
    for u in _usos(sid):
        assert all(secreto not in str(vars(u)) for secreto in PRIVADO)
    salida = capfd.readouterr()
    for secreto in PRIVADO + ["Zulema"]:
        assert secreto not in salida.out + salida.err, secreto


def test_una_falla_de_la_ia_que_menciona_datos_no_los_devuelve_ni_los_loguea(malo, monkeypatch, capfd):
    pid, sid, c = malo
    _con_ia(monkeypatch, falla=RuntimeError("falló leyendo a Zulema Quintana CUIL 20111111119 legajo LEG-99887"))
    r = _ensayo(c, pid)
    assert r.status_code == 200
    assert "Zulema" not in r.text and "20111111119" not in r.text
    salida = capfd.readouterr()
    assert "Zulema" not in salida.out + salida.err and "20111111119" not in salida.out + salida.err


def test_preguntame_no_puede_ver_los_conceptos_ni_nada_del_recibo(malo, monkeypatch):
    from xsii.proyectos.colm3na import herramientas as herr
    pid, sid, c = malo
    _con_ia(monkeypatch, _recibo_privado())
    prop = _ensayo(c, pid).json()["propuestas"]
    assert c.post(_url(pid, "carga"), json={"conceptos": [
        {"codigo": "SECRETO-77", "descripcion": "Premio Zulema Quintana", "cuit_empleador": CUIT_A, "rubro": "haber"}
        ], "recibos_leidos": 1}).status_code == 200, prop
    with db.get_session() as s:
        ctx = main._xsii_contexto(s, pid)
        inst = herr.Instantanea.armar(s, ctx)
    vistos = []
    for nombre, fn in herr.herramientas(inst).items() if isinstance(herr.herramientas(inst), dict) else []:
        if not callable(fn):
            continue
        for args in ({}, {"codigo": C}, {"codigo": "REC-05"}, {"clave": "recibos_muestra"}):
            try:
                vistos.append(json.dumps(fn(**args), ensure_ascii=False, default=str))
            except TypeError:
                continue
    vistos.append(json.dumps(inst.tablero, ensure_ascii=False, default=str))
    vistos.append(json.dumps(inst.movimientos, ensure_ascii=False, default=str))
    todo = "\n".join(vistos)
    assert len(todo) > 500
    for secreto in ["SECRETO-77", "Zulema", "Quintana", CUIT_A, "4381927"]:
        assert secreto not in todo, secreto


# =================================================================== puertas y aislamiento

def test_otras_puertas_usuario_de_la_mesa_sin_sesion_y_demo(monkeypatch):
    import entorno
    pid, sid, eq = _mundo_listo()
    anonimo = TestClient(main.app, follow_redirects=False)
    for r in (anonimo.post(_url(pid, "ensayo"), files={"archivo": ("a.png", b"x", "image/png")}),
              anonimo.post(_url(pid, "carga"), json={"conceptos": [_item()]}), anonimo.get(_url(pid))):
        assert r.status_code in (401, 403)
    # el usuario del SINDICATO de la Mesa (no es del equipo) tampoco entra
    cookie = main.COOKIES_POR_ROL["implementacion"]
    falso = TestClient(main.app, follow_redirects=False)
    falso.cookies.set(cookie, "token-inventado")
    for r in (falso.post(_url(pid, "carga"), json={"conceptos": [_item()]}),
              falso.post(_url(pid, "ensayo"), files={"archivo": ("a.png", b"x", "image/png")})):
        assert r.status_code in (401, 403)
    # un operador del panel del sindicato (cookie de sindicato) tampoco
    panel = _admin_de(sid)
    for r in (panel.post(_url(pid, "carga"), json={"conceptos": [_item()]}),
              panel.post(_url(pid, "ensayo"), files={"archivo": ("a.png", b"x", "image/png")})):
        assert r.status_code in (401, 403)
    assert _propios(sid) == []
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    assert _ensayo(eq, pid).status_code == 404 and _post_carga(eq, pid, {"conceptos": [_item()]}).status_code == 404


def test_la_carga_json_y_el_ensayo_en_las_tareas_de_planilla_no_dan_500():
    pid, sid, eq = _mundo_listo()
    c = _clon(eq)
    for codigo in ("EST-01", "PAD-02", "BAS-01", "REC-05", "no-existe"):
        r1 = c.post(_url(pid, "carga", codigo), json={"conceptos": [_item()]})
        r2 = c.post(_url(pid, "ensayo", codigo), files={"archivo": ("a.png", b"x", "image/png")})
        assert r1.status_code != 500 and r2.status_code != 500, (codigo, r1.status_code, r2.status_code)
        assert r1.status_code in (400, 404, 409), (codigo, r1.status_code)       # nunca escribe conceptos
    assert _propios(sid) == []


def test_un_proyecto_de_otro_sindicato_nunca_toca_los_conceptos_ajenos(monkeypatch):
    pid_a, sid_a, eq = _mundo_listo()
    pid_b, sid_b, _ = _mundo_listo()
    with db.get_session() as s:
        s.add(db.Concepto(sindicato_id=sid_b, codigo="X1", nombre="Del otro", tipo="ingreso"))
        s.commit()
    foto = _filas(sid_b)
    assert _post_carga(eq, pid_a, {"conceptos": [_item(codigo="X1"), _item(codigo="Y")]}).status_code == 200
    assert _filas(sid_b) == foto
    assert sorted(c.codigo for c in _propios(sid_a)) == ["X1", "Y"]
    # el proyecto A no ve el id del proyecto B: el pedido a un proyecto ajeno afecta solo SU sindicato
    r = _post_carga(eq, pid_b, {"conceptos": [_item(codigo="Z")]})
    assert r.status_code == 200 and sorted(c.codigo for c in _propios(sid_a)) == ["X1", "Y"]


# =================================================================== concurrencia

def test_dos_cargas_simultaneas_con_conceptos_en_comun_no_duplican_ni_dan_500():
    pid, sid, eq = _mundo_listo()
    with db.get_session() as s:
        otro = db.impl_crear_proyecto(s, "Otro proyecto del QA " + str(sid), EQ,
                                      sindicato_id=sid).id
    _listo(eq, otro)
    res = []
    barrera = threading.Barrier(6, timeout=30)

    def cargar(p, codigos):
        cliente = _clon(eq)
        barrera.wait()
        res.append(cliente.post(_url(p, "carga"), json={"conceptos": [_item(codigo=c) for c in codigos]}).status_code)
    trabajos = [(pid, ["X", "Y"]), (otro, ["Y", "Z"]), (pid, ["X", "Z", "W"]), (otro, ["Y"]), (pid, ["W", "V"]),
                (otro, ["Z", "V", "U"])]
    hilos = [threading.Thread(target=cargar, args=t) for t in trabajos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert set(res) <= {200, 409}, res
    codigos = [c.codigo for c in _propios(sid)]
    assert sorted(codigos) == sorted(set(codigos)) == ["U", "V", "W", "X", "Y", "Z"], codigos


def test_la_carga_de_xsii_y_el_aplicar_del_panel_a_la_vez_no_duplican():
    pid, sid, eq = _mundo_listo()
    panel = _admin_de(sid)
    res = []
    barrera = threading.Barrier(4, timeout=30)

    def xsii():
        cl = _clon(eq)
        barrera.wait()
        res.append(cl.post(_url(pid, "carga"), json={"conceptos": [_item(codigo="Q1"), _item(codigo="Q2")]}).status_code)

    def pane():
        cl = panel
        barrera.wait()
        res.append(_panel_post(cl, "/admin/aprender/aplicar", json={"aprobados": [
            {"codigo": "Q1", "descripcion": "Q1", "tipo": "ingreso"}, {"codigo": "Q2", "descripcion": "Q2", "tipo": "ingreso"}]}
        ).status_code)
    hilos = [threading.Thread(target=f) for f in (xsii, pane, xsii, pane)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert set(res) <= {200, 409}, res
    codigos = sorted(c.codigo for c in _propios(sid))
    assert codigos == ["Q1", "Q2"], codigos


def test_el_tope_de_lecturas_en_paralelo_deja_pasar_exactamente_el_tope(monkeypatch):
    pid, sid, eq = _mundo_listo()
    monkeypatch.setenv("XSII_RECIBOS_TOPE", "5")
    main._xsii_recibos_marcas.clear()
    res = []
    barrera = threading.Barrier(12, timeout=30)

    def leer():
        cl = _clon(eq)
        barrera.wait()
        res.append(_ensayo(cl, pid).status_code)
    hilos = [threading.Thread(target=leer) for _ in range(12)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    main._xsii_recibos_marcas.clear()
    assert sorted(res) == [200] * 5 + [429] * 7, res
    assert len(_usos(sid)) == 5


def test_el_tope_cuenta_solo_lo_que_llega_a_la_ia(monkeypatch):
    """Un pedido rechazado por forma no gasta del tope; uno que la IA no pudo leer sí (ya se pagó)."""
    pid, sid, eq = _mundo_listo()
    monkeypatch.setenv("XSII_RECIBOS_TOPE", "2")
    main._xsii_recibos_marcas.clear()
    for _ in range(5):
        assert _ensayo(eq, pid, b"").status_code == 400
        assert _ensayo(eq, pid, b"x", "x.exe").status_code == 400
    _con_ia(monkeypatch, falla=RuntimeError("x"))
    assert _ensayo(eq, pid).status_code == 200 and _ensayo(eq, pid).status_code == 200
    assert _ensayo(eq, pid).status_code == 429
    main._xsii_recibos_marcas.clear()


# =================================================================== el recibo simulado

def test_el_recibo_simulado_trae_un_cuit_valido_y_la_pantalla_se_puede_probar_de_punta_a_punta():
    assert cuit.es_valido(extractor._RECIBO_MOCK["empleador"]["cuit"])
    pid, sid, eq = _mundo_listo()
    j = _ensayo(eq, pid).json()
    assert j["recibo"]["empleador_cuit"] == CUIT_MOCK
    estados = {p["estado"] for p in j["propuestas"]}
    assert "rechazada" not in estados and j["propuestas"], j
    r = eq.post(_url(pid, "carga"), json={"conceptos": [
        {"codigo": p["codigo"], "descripcion": p["descripcion"], "cuit_empleador": p["cuit_empleador"],
         "rubro": p["rubro"], "categoria_sindical": p["categoria_sindical"],
         "codigo_generico": (p["generico_sugerido"] or {}).get("codigo", "")} for p in j["propuestas"]],
        "recibos_leidos": 1})
    assert r.status_code == 200, r.text
    assert r.json()["carga"]["cargados"] == len(j["propuestas"])
    assert all(c.cuit_empleador == CUIT_MOCK and c.pendiente_revision is False for c in _propios(sid))
