"""XSII bloque 3, tareas asistidas: «Cargar desde la planilla» de EST-01
(docs/xsii/API.md, «Bloque 3»). `leer` se prueba PURA y el resto por HTTP:
el ensayo no escribe nada, la carga es todo o nada, la huella ata el ensayo a
la carga, es idempotente, aísla por sindicato y no confirma la tarea.

Correr con: python -m pytest test_xsii_asistida.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import itertools
import json
import pathlib
import uuid

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
from xsii.proyectos.colm3na import catalogo
from xsii.proyectos.colm3na.asistidas import ASISTIDAS, ErrorAsistida, huella, seccionales as sec

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
BASE = "/api/entornos/xsii"
_n = itertools.count(1)
CAB = "nombre;sede_central;provincia;localidad;calle;numero;latitud;longitud;mail\n"
EJEMPLO = pathlib.Path(__file__).parent / "docs" / "xsii" / "ejemplos" / "seccionales-ejemplo.csv"


def _csv(*filas, cab=CAB):
    return (cab + "\n".join(filas) + "\n").encode("utf-8")


FILA_OK = "Seccional Rosario;no;Santa Fe;Rosario;Córdoba;1234;-32,9468;-60,6393;"


# =================================================================== leer (pura)

def _leer(contenido, existentes=(), **opciones):
    return sec.leer(contenido, list(existentes), opciones)


def _estados(r):
    return [f["estado"] for f in r["filas"]]


def test_una_fila_completa_es_valida_y_trae_el_resumen():
    r = _leer(_csv(FILA_OK))
    f = r["filas"][0]
    assert f["linea"] == 2 and f["estado"] == "valida" and f["motivos"] == []
    assert f["resumen"] == {"nombre": "Seccional Rosario", "direccion": "Córdoba 1234, Rosario, Santa Fe",
                            "ubicacion": "Con ubicación", "accion": "crear"}
    assert f["datos"]["latitud"] == pytest.approx(-32.9468)     # coma decimal


def test_cabecera_por_clave_o_por_rotulo_sin_mirar_mayusculas_ni_acentos():
    cab = "NOMBRE;Es Sede Central;PROVINCIA;Localidad;Calle;Número;Latitud;LONGITUD;Mail\n"
    r = _leer(_csv(FILA_OK, cab=cab))
    assert _estados(r) == ["valida"]
    assert _leer(b"Nombre\nSolo nombre\n")["filas"][0]["datos"]["nombre"] == "Solo nombre"


@pytest.mark.parametrize("sep", [";", ",", "\t"])
def test_separadores(sep):
    filas = ["nombre", "provincia", "localidad", "calle", "numero"], ["A", "Salta", "Salta", "Balcarce", "10"]
    texto = "\n".join(sep.join(x) for x in filas) + "\n"
    r = _leer(texto.encode())
    assert r["filas"][0]["datos"]["calle"] == "Balcarce" and r["filas"][0]["estado"] == "dudosa"   # sin coordenadas


def test_latin1_y_utf8_con_bom():
    texto = "nombre;provincia;localidad;calle;numero\nSeccional Tucumán;Tucumán;Tucumán;Mate de Luna;1\n"
    for crudo in (texto.encode("latin-1"), b"\xef\xbb\xbf" + texto.encode("utf-8")):
        assert _leer(crudo)["filas"][0]["datos"]["nombre"] == "Seccional Tucumán"


def test_decimales_con_punto_o_coma_y_coordenadas_en_comillas():
    for lat, lon in (("-32.9468", "-60.6393"), ("-32,9468", "-60,6393"), ("+-32.9", "-60.6")):
        r = _leer(_csv(f"A;no;Santa Fe;Rosario;Córdoba;1;{lat};{lon};"))
        assert r["filas"][0]["estado"] == ("rechazada" if lat.startswith("+-") else "valida"), lat
    r = _leer(b'nombre,latitud,longitud\nA,"-32,9468","-60,6393"\n')
    assert r["filas"][0]["datos"]["latitud"] == pytest.approx(-32.9468)


def test_una_columna_desconocida_se_ignora_y_va_a_sin_usar():
    r = _leer(b"nombre;secreto;otra\nA;x;y\n")
    assert _estados(r)[0] in ("valida", "dudosa")
    assert r["mapeo"]["sin_usar"] == ["secreto", "otra"]
    assert not any("secreto" in a for a in r["avisos"])        # sin ruido: viaja en `mapeo.sin_usar`


def test_sin_columna_nombre_no_es_400_y_dice_que_falta():
    r = _leer(b"provincia;calle\nSalta;Balcarce\n")
    assert r["total"] == 0 and r["mapeo"]["faltan"] == ["nombre"] and r["avisos"]


def test_archivo_inservible_es_400():
    for crudo in (b"", b"   \n\n", b"PK\x03\x04xx", b"a\x00b;c\n1;2\n"):
        with pytest.raises(ErrorAsistida) as e:
            _leer(crudo)
        assert e.value.estado == 400 and e.value.mensaje


def test_topes_de_filas_y_de_tamano():
    filas = [f"S{i};no;Salta;Salta;Balcarce;{i};-24,78;-65,41;" for i in range(500)]
    assert _leer(_csv(*filas))["total"] == 500
    with pytest.raises(ErrorAsistida) as e:
        _leer(_csv(*filas, "otra;no;Salta;Salta;Balcarce;1;-24,78;-65,41;"))
    assert e.value.estado == 400 and "500" in e.value.mensaje
    with pytest.raises(ErrorAsistida) as e:
        _leer(b"nombre\n" + b"x" * (1024 * 1024))
    assert e.value.estado == 400 and "1 MB" in e.value.mensaje


@pytest.mark.parametrize("fila,motivo", [
    (";no;Salta;Salta;Balcarce;1;-24,78;-65,41;", "nombre"),
    ("N" * 121 + ";no;Salta;Salta;Balcarce;1;-24,78;-65,41;", "120"),
    ("A;no;Salta;Salta;Balcarce;1;-24,78;;", "las dos"),
    ("A;no;Salta;Salta;Balcarce;1;;-65,41;", "las dos"),
    ("A;no;Salta;Salta;Balcarce;1;abc;-65,41;", "no se entienden"),
    ("A;no;Salta;Salta;Balcarce;1;-24,78;-65,41,3;", "no se entienden"),
    ("A;no;Salta;Salta;Balcarce;1;40,7;-74,0;", "Argentina"),               # Nueva York
    ("A;no;Salta;Salta;Balcarce;1;-24,78;-80;", "Argentina"),
    ("A;no;Salta;Salta;Balcarce;1;-60;-65;", "Argentina"),
    ("A;no;Salta;Salta;Balcarce;1;0;0;", "Argentina"),
    ("A;no;Salta;Salta;Balcarce;1;-24,78;-65,41;sin-arroba", "mail"),
    ("---;no;Salta;Salta;Balcarce;1;-24,78;-65,41;", "letras"),
])
def test_cada_motivo_de_rechazo(fila, motivo):
    f = _leer(_csv(fila))["filas"][0]
    assert f["estado"] == "rechazada", f
    assert any(motivo in m for m in f["motivos"]), f["motivos"]


def test_nombre_repetido_en_el_archivo_rechaza_la_segunda_sin_mirar_acentos_ni_mayusculas():
    r = _leer(_csv(FILA_OK, FILA_OK.replace("Seccional Rosario", "  SECCIONAL   rosário ")))
    assert _estados(r) == ["valida", "rechazada"]
    assert "repetido" in r["filas"][1]["motivos"][0]


@pytest.mark.parametrize("fila,motivo", [
    ("A;no;Salta;Salta;Balcarce;1;;;", "Sin coordenadas"),
    ("A;no;;Salta;Balcarce;1;-24,78;-65,41;", "provincia o la localidad"),
    ("A;no;Salta;;Balcarce;1;-24,78;-65,41;", "provincia o la localidad"),
    ("A;no;Salta;Salta;;1;-24,78;-65,41;", "calle o la altura"),
    ("A;no;Salta;Salta;Balcarce;;-24,78;-65,41;", "calle o la altura"),
    ("A;quizás;Salta;Salta;Balcarce;1;-24,78;-65,41;", "Sede Central"),
])
def test_cada_motivo_de_duda(fila, motivo):
    f = _leer(_csv(fila))["filas"][0]
    assert f["estado"] == "dudosa" and any(motivo in m for m in f["motivos"]), f


def test_mas_de_una_sede_central_vuelve_dudosas_a_todas_las_marcadas():
    r = _leer(_csv("A;sí;Salta;Salta;Balcarce;1;-24,78;-65,41;", "B;si;Salta;Salta;Balcarce;2;-24,78;-65,41;",
                   "C;no;Salta;Salta;Balcarce;3;-24,78;-65,41;"))
    assert _estados(r) == ["dudosa", "dudosa", "valida"]
    assert "más de una" in r["filas"][0]["motivos"][-1]


def test_sede_central_por_nombre_con_la_opcion_prendida_y_apagada():
    fila = "Sede Central;;CABA;CABA;Av. de Mayo;1;-34,6;-58,4;"
    r = _leer(_csv(fila))
    f = r["filas"][0]
    assert f["datos"]["sede"] is True and any("Sede Central" in m for m in f["motivos"]) and f["estado"] == "dudosa"
    assert _leer(_csv(fila), sede_por_nombre=False)["filas"][0]["datos"]["sede"] is False
    # lo marcado a mano como «no» se respeta
    assert _leer(_csv(fila.replace(";;CABA", ";no;CABA")))["filas"][0]["datos"]["sede"] is False


def test_aviso_si_ninguna_vería_todas():
    r = _leer(_csv(FILA_OK))
    assert any("Ninguna seccional vería todas" in a for a in r["avisos"])
    assert not _leer(_csv(FILA_OK), [{"nombre": "Otra", "ve_todas": True}])["avisos"]
    assert not _leer(_csv("Sede;sí;Salta;Salta;Balcarce;1;-24,78;-65,41;"))["avisos"]


def test_limpia_invisibles_y_deja_pasar_formulas_tal_cual():
    r = _leer(_csv("Se\u200bcci\u202eón\x07  Norte;no;Salta;Salta;Balcarce;1;-24,78;-65,41;"))
    assert r["filas"][0]["datos"]["nombre"] == "Sección Norte"
    r = _leer(_csv("=Seccional;no;Salta;Salta;=Balcarce;1;-24,78;-65,41;"))
    assert r["filas"][0]["datos"]["nombre"] == "=Seccional" and r["filas"][0]["datos"]["calle"] == "=Balcarce"


def test_opciones_que_no_son_verdadero_o_falso_dan_400():
    for malas in ({"actualizar_existentes": "si"}, {"sede_por_nombre": 1}):
        with pytest.raises(ErrorAsistida) as e:
            sec.leer(_csv(FILA_OK), [], malas)
        assert e.value.estado == 400
    with pytest.raises(ErrorAsistida):
        sec.leer(_csv(FILA_OK), [], ["x"])
    assert sec.normalizar_opciones(None) == {"actualizar_existentes": False, "sede_por_nombre": True, "mapeo": {}}
    assert sec.normalizar_opciones({"zzz": 1})["sede_por_nombre"] is True


def _existente(**campos):
    base = {"id": 1, "nombre": "Seccional Rosario", "ve_todas": True, "calle": "Mitre", "numero": "10",
            "piso_depto": "", "localidad": "Rosario", "provincia": "Santa Fe", "codigo_postal": "2000",
            "direccion_texto": "Mitre 10, Rosario, Santa Fe (CP 2000)", "latitud": -32.9, "longitud": -60.6, "precision_geo": "exacta",
            "telefono": "341 1", "whatsapp": "", "mail": "", "horario_atencion": "Todo el día"}
    return {**base, **campos}


def test_una_que_ya_existe_no_se_toca_salvo_que_se_pida():
    e = _existente()
    f = _leer(_csv(FILA_OK), [e])["filas"][0]
    assert f["estado"] == "ya_existe" and f["cambios"] == {} and f["resumen"]["accion"] == "sin_tocar"
    f = _leer(_csv(FILA_OK), [e], actualizar_existentes=True)["filas"][0]
    assert f["estado"] == "ya_existe" and f["resumen"]["accion"] == "actualizar"
    assert f["cambios"]["calle"] == "Córdoba" and f["cambios"]["numero"] == "1234"
    assert f["cambios"]["precision_geo"] == "manual" and f["cambios"]["latitud"] == pytest.approx(-32.9468)


def test_actualizar_nunca_baja_ve_todas_ni_pisa_con_vacios_ni_pierde_las_coordenadas():
    e = _existente()
    fila = "seccional rosario;no;;;;;;;"            # todo vacío salvo el nombre
    f = _leer(_csv(fila), [e], actualizar_existentes=True)["filas"][0]
    assert f["estado"] == "ya_existe" and f["cambios"] == {}              # nada que cambiar
    f = _leer(_csv("seccional rosario;no;;;Mitre;10;;;"), [e], actualizar_existentes=True)["filas"][0]
    assert f["cambios"] == {}                      # mismo domicilio, sin coordenadas en la planilla: se conservan
    f = _leer(_csv("seccional rosario;no;;;Mitre;99;;;"), [e], actualizar_existentes=True)["filas"][0]
    assert f["cambios"]["numero"] == "99" and f["cambios"]["latitud"] is None      # se mudó: sin ubicar
    assert f["cambios"]["precision_geo"] == "sin_geo"
    assert "ve_todas" not in _leer(_csv(fila), [e], actualizar_existentes=True)["filas"][0]["cambios"]
    f = _leer(_csv("seccional rosario;sí;;;;;;;"), [_existente(ve_todas=False)], actualizar_existentes=True)["filas"][0]
    assert f["cambios"] == {"ve_todas": True}


def test_una_rechazada_gana_aunque_ya_exista():
    f = _leer(_csv("Seccional Rosario;no;;;;;40;-70;"), [_existente()], actualizar_existentes=True)["filas"][0]
    assert f["estado"] == "rechazada"


def test_el_ejemplo_de_la_documentacion_se_lee_como_dice_el_enunciado():
    r = _leer(EJEMPLO.read_bytes())
    assert r["total"] == 8 and r["avisos"] == []
    assert _estados(r) == ["valida"] * 6 + ["dudosa"] * 2
    assert [f["resumen"]["ubicacion"] for f in r["filas"]].count("Sin ubicar") == 2
    assert r["filas"][0]["datos"]["sede"] is True and r["filas"][0]["resumen"]["sede_central"] == "Sede Central"
    assert "calle o la altura" in " ".join(r["filas"][7]["motivos"])


def test_el_modelo_csv_se_lee_solo():
    r = _leer(sec.describir()["modelo_csv"].encode("utf-8"))
    assert _estados(r) == ["dudosa", "valida"] or _estados(r) == ["valida", "valida"]
    assert r["filas"][0]["datos"]["sede"] is True


def test_describir_tiene_la_forma_del_contrato():
    d = sec.describir()
    assert set(d) == {"titulo", "que_voy_a_hacer", "insumo", "mapeo", "campos", "columnas", "modelo_csv",
                      "opciones"}
    assert len(d["que_voy_a_hacer"]) == 2 and d["insumo"] in catalogo.INSUMOS
    assert {c["clave"] for c in d["columnas"]} >= {"nombre", "sede_central", "latitud", "longitud", "horario"}
    assert [c["clave"] for c in d["columnas"] if c["obligatoria"]] == ["nombre"]
    for c in d["columnas"]:
        assert set(c) == {"clave", "rotulo", "obligatoria", "ejemplo", "ayuda"}
    assert {o["clave"]: o["defecto"] for o in d["opciones"]} == {"actualizar_existentes": False, "sede_por_nombre": True}
    assert set(ASISTIDAS) == {"EST-01", "PAD-02"}


def test_la_huella_depende_del_contenido_y_de_las_opciones():
    o = sec.normalizar_opciones({})
    assert huella(b"a", o) == huella(b"a", dict(o)) != huella(b"b", o)
    assert huella(b"a", o) != huella(b"a", {**o, "actualizar_existentes": True})


# =================================================================== HTTP

def _sindicato(nombre=None):
    n = next(_n)
    with db.get_session() as s:
        sind = db.Sindicato(nombre=nombre or f"Sindicato Asistida {n} {uuid.uuid4().hex[:4]}",
                            slug=f"xsii-asist-{n}-{uuid.uuid4().hex[:4]}", cuit=cuit.corregir("30700000000"),
                            modulos_habilitados=list(modulos.MODULOS_INICIALES))
        s.add(sind); s.commit(); s.refresh(sind)
        sid = sind.id
    db.crear_conceptos_universales(sid)
    return sid


def _proyecto(con_sindicato=True):
    sid = _sindicato() if con_sindicato else None
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, "XSII " + uuid.uuid4().hex[:8], EQ, sindicato_id=sid).id, sid


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
    pid, sid = _proyecto(con_sindicato)
    return pid, sid, _equipo()


def _url(pid, que, codigo="EST-01"):
    return f"{BASE}/p/{pid}/tarea/{codigo}/asistida" + (f"/{que}" if que else "")


def _enviar(c, pid, que, contenido=None, texto=None, opciones=None, huella_=None, afuera=None, codigo="EST-01"):
    data = {}
    if opciones is not None:
        data["opciones"] = json.dumps(opciones)
    if huella_ is not None:
        data["huella"] = huella_
    if afuera is not None:
        data["dejar_afuera"] = json.dumps(afuera)
    if texto is not None:
        data["texto"] = texto
    files = {"archivo": ("planilla.csv", contenido, "text/csv")} if contenido is not None else None
    return c.post(_url(pid, que, codigo), data=data, files=files)


def _ensayo(c, pid, contenido, **kw):
    r = _enviar(c, pid, "ensayo", contenido, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def _carga(c, pid, contenido, afuera=None, opciones=None, ens=None):
    ens = ens or _ensayo(c, pid, contenido, opciones=opciones)
    return _enviar(c, pid, "carga", contenido, opciones=opciones, huella_=ens["huella"], afuera=afuera)


def _seccionales(sid):
    with db.get_session() as s:
        return list(s.exec(select(db.Seccional).where(db.Seccional.sindicato_id == sid).order_by(db.Seccional.id)).all())


def _movs(pid, tipo=None):
    with db.get_session() as s:
        m = list(s.exec(select(db.XsiiMovimiento).where(db.XsiiMovimiento.proyecto_id == pid)).all())
    return [x for x in m if tipo is None or x.tipo == tipo]


def _estado_insumo(pid, clave="lista_seccionales"):
    with db.get_session() as s:
        i = db.xsii_insumos_activos(s, pid).get(clave)
        return i.estado if i else None


def _tarea(c, pid, codigo="EST-01"):
    return c.get(f"{BASE}/p/{pid}/tarea/{codigo}").json()["tarea"]


# ---------------------------------------------------------------- GET asistida

def test_get_asistida_describe_y_dice_si_esta_disponible():
    pid, sid, eq = _mundo()
    r = eq.get(_url(pid, ""))
    assert r.status_code == 200
    j = r.json()
    assert j["disponible"] is True and j["motivo"] == ""
    assert {"titulo", "que_voy_a_hacer", "insumo", "columnas", "modelo_csv", "opciones"} <= set(j)
    assert j["insumo"] == "lista_seccionales" and j["columnas"][0]["clave"] == "nombre"


def test_get_asistida_de_una_tarea_sin_modulo_y_de_una_que_no_existe():
    pid, sid, eq = _mundo()
    j = eq.get(_url(pid, "", "BAS-01")).json()
    assert j["disponible"] is False and j["motivo"] and "columnas" not in j
    assert eq.get(_url(pid, "", "ZZZ-99")).status_code == 404


def test_proyecto_sin_sindicato_no_esta_disponible_y_la_carga_se_rechaza():
    pid, sid, eq = _mundo(con_sindicato=False)
    j = eq.get(_url(pid, "")).json()
    assert j["disponible"] is False and "sindicato" in j["motivo"] and j["columnas"]
    assert _enviar(eq, pid, "carga", _csv(FILA_OK), huella_="x").status_code == 409
    assert _enviar(eq, pid, "ensayo", _csv(FILA_OK)).status_code == 409


def test_tarea_que_no_aplica_no_esta_disponible():
    pid, sid, eq = _mundo()
    assert eq.post(f"{BASE}/p/{pid}/tarea/EST-01/decision",
                   json={"tipo": "no_aplica", "motivo": "no tiene seccionales"}).status_code == 200
    j = eq.get(_url(pid, "")).json()
    assert j["disponible"] is False and "no aplica" in j["motivo"]
    assert _enviar(eq, pid, "carga", _csv(FILA_OK), huella_="x").status_code == 409


def test_modelo_csv_se_baja_como_descarga_y_se_lee():
    pid, sid, eq = _mundo()
    r = eq.get(_url(pid, "modelo.csv"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and "modelo-seccionales" in r.headers["content-disposition"]
    assert r.content.startswith("﻿nombre;".encode("utf-8"))
    assert _ensayo(eq, pid, r.content)["total"] == 2
    assert eq.get(_url(pid, "modelo.csv", "BAS-01")).status_code == 404
    assert eq.get(_url(pid + 100000, "modelo.csv")).status_code == 404


# ---------------------------------------------------------------- ensayo

def test_el_ensayo_cuenta_y_no_escribe_nada():
    pid, sid, eq = _mundo()
    e = _ensayo(eq, pid, EJEMPLO.read_bytes())
    assert (e["total"], e["validas"], e["dudosas"], e["rechazadas"], e["ya_existen"]) == (8, 6, 2, 0, 0)
    assert len(e["filas"]) == 8 and e["muestra"] and e["huella"] and isinstance(e["avisos"], list)
    assert set(e["filas"][0]) == {"linea", "estado", "motivos", "resumen"}
    assert _seccionales(sid) == [] and _movs(pid) == [] and _estado_insumo(pid) is None
    assert _tarea(eq, pid)["control"]["cifras"][0]["valor"] == 0


def test_el_ensayo_no_pide_las_tareas_que_necesita_resueltas():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.get(db.Sindicato, sid).cuit = ""         # BAS-01 pasa a no resuelta -> EST-01 bloqueada
        s.commit()
    assert _tarea(eq, pid)["estado"] == "bloqueada"
    assert _enviar(eq, pid, "ensayo", _csv(FILA_OK)).status_code == 200
    r = _enviar(eq, pid, "carga", _csv(FILA_OK), huella_=_ensayo(eq, pid, _csv(FILA_OK))["huella"])
    assert r.status_code == 409 and "resuelta" in r.json()["detail"]
    assert _seccionales(sid) == []


def test_el_ensayo_acepta_texto_pegado_y_archivo_con_prioridad():
    pid, sid, eq = _mundo()
    assert _ensayo(eq, pid, None, texto=_csv(FILA_OK).decode())["total"] == 1
    assert _ensayo(eq, pid, _csv(FILA_OK, FILA_OK.replace("Rosario", "Salta")), texto="nombre\nX\n")["total"] == 2
    assert _ensayo(eq, pid, b"", texto="nombre\nX\nY\n")["total"] == 2        # archivo vacío: vale el texto


def test_el_ensayo_con_archivos_malos_es_400_en_castellano():
    pid, sid, eq = _mundo()
    for malo in (b"", b"PK\x03\x04", b"a\x00b"):
        r = _enviar(eq, pid, "ensayo", malo)
        assert r.status_code == 400 and r.json()["detail"], malo
    assert _enviar(eq, pid, "ensayo", None).status_code == 400
    assert _enviar(eq, pid, "ensayo", b"x" * (1024 * 1024 + 10)).status_code == 400
    assert _enviar(eq, pid, "ensayo", _csv(FILA_OK), opciones={"actualizar_existentes": "si"}).status_code == 400
    r = eq.post(_url(pid, "ensayo"), data={"opciones": "no es json"}, files={"archivo": ("a.csv", _csv(FILA_OK))})
    assert r.status_code == 400
    r = eq.post(_url(pid, "ensayo"), data={"dejar_afuera": '["a"]'}, files={"archivo": ("a.csv", _csv(FILA_OK))})
    assert r.status_code == 400
    r = eq.post(_url(pid, "ensayo"), json={"x": 1})                     # no es multipart
    assert r.status_code == 400


# ---------------------------------------------------------------- carga

def test_carga_completa_escribe_registra_recibe_el_insumo_y_no_confirma():
    pid, sid, eq = _mundo()
    assert _estado_insumo(pid) is None
    r = _carga(eq, pid, EJEMPLO.read_bytes())
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) >= {"ok", "carga", "control", "tarea", "destrabo", "tablero_resumen"} and j["ok"] is True
    assert (j["carga"]["creadas"], j["carga"]["actualizadas"], j["carga"]["sin_tocar"], j["carga"]["afuera"]) == (8, 0, 0, 0)
    assert len(j["carga"]["detalle"]) == 8 and j["carga"]["detalle"][0]["accion"] == "creada"
    filas = _seccionales(sid)
    assert [x.nombre for x in filas][0] == "Sede Central" and len(filas) == 8
    assert filas[0].ve_todas is True and all(not x.ve_todas for x in filas[1:])
    rosario = filas[1]
    assert (rosario.latitud, rosario.precision_geo) == (-32.9468, "manual")
    assert rosario.direccion_texto.startswith("Córdoba 1452") and rosario.mail.endswith("@sindicato-ejemplo.org.ar")
    sin = [x for x in filas if x.precision_geo == "sin_geo"]
    assert len(sin) == 2 and all(x.latitud is None for x in sin)
    # el movimiento, con el texto del contrato
    m = _movs(pid, "asistida_carga")
    assert len(m) == 1 and m[0].codigo == "EST-01" and m[0].clave_insumo == "lista_seccionales"
    assert m[0].texto == "Cargó 8 seccionales desde planilla (0 actualizadas, 0 afuera)"
    assert m[0].cantidades["creadas"] == 8
    assert _estado_insumo(pid) == "recibido"
    # control y confirmación
    assert j["control"]["estado"] == "completa" and j["tarea"]["falta_confirmar"] is True
    assert j["tarea"]["estado"] != "hecha" and j["tarea"]["asistida"] is True
    assert not any(d["tipo"] == "confirmada" for d in j["tarea"]["decisiones"])
    assert j["tablero_resumen"]
    # el historial de la tarea lo muestra
    hist = eq.get(f"{BASE}/p/{pid}/tarea/EST-01").json()["historial"]
    assert any(h["tipo"] == "asistida_carga" for h in hist)
    assert eq.get(f"{BASE}/p/{pid}/movimientos").json()["movimientos"][0]["tipo"] in ("asistida_carga", "insumo_recibido")


def test_una_carga_de_una_sola_seccional_dice_seccional_en_singular():
    pid, sid, eq = _mundo()
    assert _carga(eq, pid, _csv(FILA_OK)).status_code == 200
    assert _movs(pid, "asistida_carga")[0].texto == "Cargó 1 seccional desde planilla (0 actualizadas, 0 afuera)"


def test_carga_con_el_insumo_ya_recibido_no_lo_registra_de_nuevo():
    pid, sid, eq = _mundo()
    assert eq.post(f"{BASE}/p/{pid}/insumo/lista_seccionales", json={"estado": "recibido"}).status_code == 200
    antes = len(_movs(pid, "insumo_recibido"))
    assert _carga(eq, pid, _csv(FILA_OK)).status_code == 200
    assert len(_movs(pid, "insumo_recibido")) == antes


def test_destrabo_lista_lo_que_deja_de_estar_bloqueado():
    pid, sid, eq = _mundo()
    # una sola seccional ubicada: EST-02 (que necesita EST-01) pasa de bloqueada a hecha
    j = _carga(eq, pid, _csv(FILA_OK)).json()
    assert j["destrabo"] == [{"codigo": "EST-02", "nombre": "Seccionales ubicadas en el mapa"}]
    # con dos sin ubicar, EST-02 queda pendiente (en curso) pero ya no bloqueada o sigue bloqueada: nunca se repite
    pid1, sid1, eq1 = _mundo()
    j = _carga(eq1, pid1, EJEMPLO.read_bytes()).json()
    assert all(d["codigo"] != "EST-01" for d in j["destrabo"])
    # Con EST-01 completada a mano, EST-02 ya no está bloqueada: una carga posterior no la «destraba» dos veces
    pid2, sid2, eq2 = _mundo()
    with db.get_session() as s:
        s.get(db.Sindicato, sid2).cuit = ""
        s.commit()
    assert _tarea(eq2, pid2)["estado"] == "bloqueada"
    from xsii.proyectos.colm3na import vista
    with db.get_session() as s:
        antes = vista.Contexto(s, pid2)
        with db.get_session() as s2:
            s2.get(db.Sindicato, sid2).cuit = cuit.corregir("30700000000")
            s2.commit()
        despues = vista.Contexto(s, pid2)
        r = vista.asistida_resultado(antes, despues, "EST-01", {"creadas": 0})
    assert "EST-01" in [d["codigo"] for d in r["destrabo"]]
    assert set(r["destrabo"][0]) == {"codigo", "nombre"}


def test_el_control_de_est_01_queda_completo_despues_de_cargar():
    pid, sid, eq = _mundo()
    assert _tarea(eq, pid)["control"]["estado"] == "incompleta"
    _carga(eq, pid, EJEMPLO.read_bytes())
    c = _tarea(eq, pid)["control"]
    assert c["estado"] == "completa" and "8 seccionales" in c["resumen"]
    est2 = _tarea(eq, pid, "EST-02")["control"]
    assert est2["estado"] == "incompleta" and "2 de 8" in est2["resumen"]       # las sin ubicar quedan para EST-02


def test_la_huella_que_no_coincide_es_409_y_no_se_escribe_nada():
    pid, sid, eq = _mundo()
    ens = _ensayo(eq, pid, _csv(FILA_OK))
    otro = _csv(FILA_OK, FILA_OK.replace("Rosario", "Salta"))
    for h in (ens["huella"], "", "x" * 64):
        r = _enviar(eq, pid, "carga", otro, huella_=h)
        assert r.status_code == 409 and "cambió desde el ensayo" in r.json()["detail"]
    assert _enviar(eq, pid, "carga", _csv(FILA_OK)).status_code == 409           # sin huella
    # las opciones también entran en la huella
    r = _enviar(eq, pid, "carga", _csv(FILA_OK), opciones={"actualizar_existentes": True}, huella_=ens["huella"])
    assert r.status_code == 409
    assert _seccionales(sid) == [] and _movs(pid) == []


def test_dejar_afuera_saca_solo_dudosas_e_ignora_lo_demas():
    pid, sid, eq = _mundo()
    c = EJEMPLO.read_bytes()
    ens = _ensayo(eq, pid, c)
    dudosas = [f["linea"] for f in ens["filas"] if f["estado"] == "dudosa"]
    valida = next(f["linea"] for f in ens["filas"] if f["estado"] == "valida")
    r = _carga(eq, pid, c, afuera=dudosas + [valida, 999], ens=ens)
    j = r.json()
    assert r.status_code == 200
    assert j["carga"]["afuera"] == 2 and j["carga"]["creadas"] == 6       # la válida «afuera» no se ignora ni se saca
    assert len(_seccionales(sid)) == 6
    assert _movs(pid, "asistida_carga")[0].texto == "Cargó 6 seccionales desde planilla (0 actualizadas, 2 afuera)"


def test_cargar_dos_veces_lo_mismo_no_duplica_y_la_segunda_es_409():
    pid, sid, eq = _mundo()
    c = EJEMPLO.read_bytes()
    assert _carga(eq, pid, c).status_code == 200
    r = _carga(eq, pid, c)
    assert r.status_code == 409 and "nada para cargar" in r.json()["detail"]
    assert len(_seccionales(sid)) == 8 and len(_movs(pid, "asistida_carga")) == 1
    e = _ensayo(eq, pid, c)
    assert (e["ya_existen"], e["validas"], e["dudosas"], e["a_escribir"]) == (8, 0, 0, 0)
    # con «actualizar» y nada cambiado, tampoco hay nada para escribir
    o = {"actualizar_existentes": True}
    assert _ensayo(eq, pid, c, opciones=o)["a_escribir"] == 0
    assert _carga(eq, pid, c, opciones=o).status_code == 409
    assert len(_movs(pid, "asistida_carga")) == 1


def test_todo_rechazado_es_409_sin_escribir():
    pid, sid, eq = _mundo()
    r = _carga(eq, pid, _csv(";no;Salta;Salta;Balcarce;1;-24,78;-65,41;", "B;no;Salta;Salta;Balcarce;1;99;99;"))
    assert r.status_code == 409
    assert _seccionales(sid) == [] and _movs(pid) == []
    # y todo dudoso dejado afuera
    c = _csv("A;no;Salta;Salta;Balcarce;1;;;")
    ens = _ensayo(eq, pid, c)
    assert _carga(eq, pid, c, afuera=[2], ens=ens).status_code == 409
    assert _seccionales(sid) == [] and _estado_insumo(pid) is None


def test_actualizar_existentes_cambia_domicilio_y_contacto_sin_bajar_ve_todas():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=True, calle="Vieja", numero="1",
                           localidad="CABA", provincia="Ciudad Autónoma de Buenos Aires",
                           latitud=-34.6, longitud=-58.4, precision_geo="exacta", telefono="11 1"))
        s.add(db.Seccional(sindicato_id=sid, nombre="Seccional Rosario", ve_todas=False, calle="Mitre", numero="10",
                           localidad="Rosario", provincia="Santa Fe", latitud=-32.9, longitud=-60.6,
                           precision_geo="exacta"))
        s.commit()
    c = _csv("sede central;no;;;Avenida de Mayo;1370;;;;", FILA_OK, "Seccional Nueva;no;Salta;Salta;Balcarce;1;-24,78;-65,41;")
    e = _ensayo(eq, pid, c, opciones={"actualizar_existentes": True})
    assert (e["ya_existen"], e["validas"], e["a_escribir"]) == (2, 1, 3)
    r = _carga(eq, pid, c, opciones={"actualizar_existentes": True})
    assert r.status_code == 200, r.text
    carga = r.json()["carga"]
    assert (carga["creadas"], carga["actualizadas"], carga["sin_tocar"]) == (1, 2, 0)
    por = {x.nombre: x for x in _seccionales(sid)}
    sede = por["Sede Central"]
    assert sede.ve_todas is True                       # «no» en la planilla no la baja
    assert (sede.calle, sede.numero, sede.telefono) == ("Avenida de Mayo", "1370", "11 1")
    assert sede.latitud is None and sede.precision_geo == "sin_geo"       # se mudó y la planilla no trae coordenadas
    ros = por["Seccional Rosario"]
    assert (ros.calle, ros.numero, ros.latitud, ros.precision_geo) == ("Córdoba", "1234", -32.9468, "manual")
    assert "Seccional Nueva" in por
    m = _movs(pid, "asistida_carga")[0]
    assert m.texto == "Cargó 1 seccional desde planilla (2 actualizadas, 0 afuera)"


def test_sin_actualizar_las_existentes_quedan_como_estaban():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Seccional Rosario", calle="Mitre", numero="10",
                           localidad="Rosario", provincia="Santa Fe"))
        s.commit()
    r = _carga(eq, pid, _csv(FILA_OK, "Seccional Nueva;no;Salta;Salta;Balcarce;1;-24,78;-65,41;"))
    assert r.status_code == 200 and r.json()["carga"]["sin_tocar"] == 1
    por = {x.nombre: x for x in _seccionales(sid)}
    assert por["Seccional Rosario"].calle == "Mitre" and "Seccional Nueva" in por


# ---------------------------------------------------------------- todo o nada

def test_si_algo_falla_en_el_medio_no_queda_nada(monkeypatch):
    pid, sid, eq = _mundo()

    def roto(*a, **k):
        raise RuntimeError("se cayó")
    monkeypatch.setattr(db, "xsii_registrar_carga_asistida", roto)
    eq2 = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    eq2.cookies.update(eq.cookies)
    r = _carga(eq2, pid, _csv(FILA_OK))
    assert r.status_code == 500
    assert _seccionales(sid) == [] and _movs(pid) == [] and _estado_insumo(pid) is None


# ---------------------------------------------------------------- aislamiento y puertas

def test_no_toca_las_seccionales_de_otro_sindicato():
    pid, sid, eq = _mundo()
    ajeno = _sindicato()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=ajeno, nombre="Seccional Rosario", ve_todas=False, calle="Ajena", numero="1"))
        s.commit()
    r = _carga(eq, pid, _csv(FILA_OK), opciones={"actualizar_existentes": True})
    assert r.status_code == 200 and r.json()["carga"]["creadas"] == 1          # para este sindicato no existía
    assert [x.calle for x in _seccionales(ajeno)] == ["Ajena"]
    assert [x.nombre for x in _seccionales(sid)] == ["Seccional Rosario"]


def test_proyecto_inexistente_es_404_y_sin_sesion_es_403_y_baja_es_401():
    pid, sid, eq = _mundo()
    c = _csv(FILA_OK)
    for n in (pid + 100000, 0, 2 ** 31):
        assert eq.get(_url(n, "")).status_code == 404
        assert _enviar(eq, n, "ensayo", c).status_code == 404
        assert _enviar(eq, n, "carga", c, huella_="x").status_code == 404
    anonimo = TestClient(main.app, follow_redirects=False)
    assert anonimo.get(_url(pid, "")).status_code == 403
    assert anonimo.get(_url(pid, "modelo.csv")).status_code == 403
    assert _enviar(anonimo, pid, "ensayo", c).status_code == 403
    assert _enviar(anonimo, pid, "carga", c, huella_="x").status_code == 403
    baja = _equipo(activo=False)
    assert baja.get(_url(pid, "")).status_code == 401
    assert _enviar(baja, pid, "ensayo", c).status_code == 401
    assert _enviar(baja, pid, "carga", c, huella_="x").status_code == 401
    assert _seccionales(sid) == []


def test_en_demo_todo_es_404(monkeypatch):
    pid, sid, eq = _mundo()
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    assert eq.get(_url(pid, "")).status_code == 404
    assert eq.get(_url(pid, "modelo.csv")).status_code == 404
    assert _enviar(eq, pid, "ensayo", _csv(FILA_OK)).status_code == 404
    assert _enviar(eq, pid, "carga", _csv(FILA_OK), huella_="x").status_code == 404


def test_la_puerta_se_resuelve_antes_de_leer_el_cuerpo():
    """Un anónimo recibe 403 aunque mande un cuerpo que no es un formulario."""
    pid, sid, eq = _mundo()
    anonimo = TestClient(main.app, follow_redirects=False)
    r = anonimo.post(_url(pid, "ensayo"), content=b"basura", headers={"content-type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 403
    r = eq.post(_url(pid, "ensayo"), content=b"basura", headers={"content-type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 400


def test_tarea_sin_modulo_no_tiene_ensayo_ni_carga():
    pid, sid, eq = _mundo()
    assert _enviar(eq, pid, "ensayo", _csv(FILA_OK), codigo="BAS-01").status_code == 404
    assert _enviar(eq, pid, "carga", _csv(FILA_OK), huella_="x", codigo="BAS-01").status_code == 404


# ---------------------------------------------------------------- tablero y catálogo

def test_el_tablero_dice_que_tareas_son_asistidas():
    pid, sid, eq = _mundo()
    tareas = {t["codigo"]: t for t in eq.get(f"{BASE}/p/{pid}/tablero").json()["tareas"]}
    assert tareas["EST-01"]["asistida"] is True
    assert [c for c, t in tareas.items() if t["asistida"]] == ["EST-01", "PAD-02"]
    assert eq.get(f"{BASE}/p/{pid}/tarea/EST-01").json()["tarea"]["asistida"] is True


def test_los_pasos_de_est_01_prometen_la_carga_desde_la_planilla():
    est = next(t for t in catalogo.TAREAS if t.codigo == "EST-01")
    assert any("Cargar desde la planilla" in p for p in est.pasos)
    assert 2 <= len(est.pasos) <= 5 and all(len(p) <= 150 for p in est.pasos)
    assert "Pedile" in est.pasos[0]


def test_el_resumen_solo_tiene_textos_con_valor():
    r = _leer(_csv(";no;Salta;Salta;Balcarce;1;-24,78;-65,41;"))
    res = r["filas"][0]["resumen"]
    assert r["filas"][0]["estado"] == "rechazada" and "nombre" not in res
    assert all(isinstance(v, str) and v for v in res.values()), res
    for f in _leer(EJEMPLO.read_bytes())["filas"]:
        assert all(isinstance(v, str) and v for v in f["resumen"].values()), f["resumen"]


# =================================================================== mapeo flexible, precision y responsable (EST-01)

COMO_VIENE = pathlib.Path(__file__).parent / "docs" / "xsii" / "ejemplos" / "seccionales-como-viene.csv"


@pytest.mark.parametrize("cabecera,campo", [
    ("Seccional", "nombre"), ("Delegación", "nombre"), ("Denominación", "nombre"),
    ("ve_todas", "sede_central"), ("Ve todas", "sede_central"), ("Sede Central", "sede_central"),
    ("Casa Central", "sede_central"), ("Central", "sede_central"), ("Dirección", "calle"), ("Domicilio", "calle"),
    ("Altura", "numero"), ("Nro", "numero"), ("Oficina", "piso_depto"), ("Depto", "piso_depto"), ("Ciudad", "localidad"),
    ("CP", "codigo_postal"), ("Lat", "latitud"), ("Lon", "longitud"), ("Lng", "longitud"), ("Long", "longitud"),
    ("Precisión", "precision_geo"), ("Precisión geo", "precision_geo"), ("Tel", "telefono"), ("WSP", "whatsapp"),
    ("Celular", "whatsapp"), ("Email", "mail"), ("Correo", "mail"), ("Horario de atención", "horario"),
    ("Atención", "horario"), ("x_responsable", "responsable"), ("Secretario general", "responsable"),
    ("Titular", "responsable"), ("A cargo", "responsable"), ("Delegado", "responsable"),
])
def test_sinonimos_de_seccionales(cabecera, campo):
    assert sec.detectar([cabecera]) == {0: campo}


def test_el_archivo_como_viene_se_reconoce_entero_y_las_x_quedan_sin_usar():
    r = sec.leer(COMO_VIENE.read_bytes(), [], {})
    campos = {c["cabecera"]: c["campo"] for c in r["mapeo"]["columnas"]}
    assert campos["ve_todas"] == "sede_central" and campos["horario_atencion"] == "horario"
    assert campos["x_responsable"] == "responsable" and campos["precision_geo"] == "precision_geo"
    assert all(campos[k] == k for k in ("nombre", "calle", "numero", "piso_depto", "localidad", "provincia",
                                        "codigo_postal", "latitud", "longitud", "telefono", "whatsapp", "mail"))
    assert r["mapeo"]["sin_usar"] == ["x_tipo", "x_observaciones", "x_geo_metodo", "x_geo_nota",
                                      "x_geo_distancia_centro_km", "x_fuente"]
    assert r["mapeo"]["faltan"] == [] and r["avisos"] == [] and r["total"] == 10
    d = {f["datos"]["nombre"]: f for f in r["filas"]}
    assert d["Seccional Rosario"]["datos"]["numero"] == "764/68" and d["Seccional Rosario"]["estado"] == "valida"
    assert d["Seccional Córdoba"]["datos"]["numero"] == "2892/94"
    assert d["Seccional Tierra del Fuego"]["datos"]["provincia"] == "Tierra del Fuego, Antártida e Islas del Atlántico Sur"
    assert d["Casa del Gremio; Anexo Tucumán"]["datos"]["nombre"] == "Casa del Gremio; Anexo Tucumán"
    assert d["Sede Central"]["datos"]["telefono"] == "011 4131-4291/4311" and d["Sede Central"]["datos"]["sede"] is True
    assert sum(1 for f in r["filas"] if f["datos"]["sede"]) == 1
    # S/N y vacío = falta la altura: dudosa, no rechazada
    assert d["Delegación Ruta 40"]["estado"] == "dudosa" and "Falta la calle o la altura." in d["Delegación Ruta 40"]["motivos"]
    assert d["Seccional Salta"]["estado"] == "dudosa"
    # aproximada: entra y queda dudosa con su motivo
    assert "Ubicación aproximada: confirmala en el mapa." in d["Seccional Neuquén"]["motivos"]
    assert d["Seccional Neuquén"]["datos"]["precision"] == "aproximada"
    assert d["Seccional Mar del Plata"]["datos"]["precision"] == "manual"        # vacía con coordenadas
    assert d["Seccional Mar del Plata"]["datos"]["sede"] is False and d["Seccional Rosario"]["datos"]["responsable"] == "Raúl Benítez"


@pytest.mark.parametrize("valor,esperado", [("si", True), ("sí", True), ("SÍ", True), ("x", True), ("1", True),
                                            ("true", True), ("no", False), ("0", False), ("", False)])
def test_ve_todas_acepta_los_valores_de_siempre(valor, esperado):
    r = _leer(f"nombre;ve_todas\nA;{valor}\n".encode())
    assert r["filas"][0]["datos"]["sede"] is esperado and r["filas"][0]["estado"] != "rechazada"


def test_la_precision_se_respeta_con_coordenadas_y_sin_coordenadas_es_sin_geo():
    cab = "nombre;calle;numero;provincia;localidad;latitud;longitud;precision_geo\n"
    filas = ["E;C;1;Salta;Salta;-24,78;-65,41;exacta", "A;C;1;Salta;Salta;-24,78;-65,41;aproximada",
             "M;C;1;Salta;Salta;-24,78;-65,41;manual", "V;C;1;Salta;Salta;-24,78;-65,41;", "R;C;1;Salta;Salta;-24,78;-65,41;rara",
             "S;C;1;Salta;Salta;;;exacta"]
    r = _leer((cab + "\n".join(filas) + "\n").encode())
    por = {f["datos"]["nombre"]: f for f in r["filas"]}
    assert [por[k]["datos"]["precision"] for k in "EAMVR"] == ["exacta", "aproximada", "manual", "manual", "manual"]
    assert por["A"]["estado"] == "dudosa" and por["E"]["estado"] == "valida" and por["S"]["estado"] == "dudosa"
    assert sec._a_escribir(por["A"]["datos"], None)["precision_geo"] == "aproximada"
    assert sec._a_escribir(por["S"]["datos"], None)["precision_geo"] == "sin_geo"
    assert sec._a_escribir(por["R"]["datos"], None)["precision_geo"] == "manual"


def test_el_mapeo_de_seccionales_se_corrige_por_opcion_y_falta_nombre_es_200():
    r = _leer(b"A;B\nx;Seccional X\n", mapeo={"1": "nombre", "0": ""})
    assert r["mapeo"]["faltan"] == [] and r["filas"][0]["datos"]["nombre"] == "Seccional X"
    with pytest.raises(ErrorAsistida):
        _leer(b"nombre;otro\nA;B\n", mapeo={"0": "nombre", "1": "nombre"})
    assert _leer(b"x;y\n1;2\n")["mapeo"]["faltan"] == ["nombre"]


def test_como_viene_por_http_ensayo_y_carga_con_precisiones_y_responsable():
    pid, sid, eq = _mundo()
    contenido = COMO_VIENE.read_bytes()
    e = _ensayo(eq, pid, contenido)
    assert (e["total"], e["validas"], e["dudosas"], e["rechazadas"]) == (10, 7, 3, 0)
    assert e["mapeo"]["faltan"] == [] and len(e["mapeo"]["sin_usar"]) == 6 and e["avisos"] == []
    assert _seccionales(sid) == []
    assert _carga(eq, pid, contenido, ens=e).status_code == 200
    s_ = {x.nombre: x for x in _seccionales(sid)}
    assert len(s_) == 10
    assert s_["Sede Central"].ve_todas is True and sum(1 for x in s_.values() if x.ve_todas) == 1
    assert s_["Seccional Rosario"].numero == "764/68" and s_["Seccional Rosario"].precision_geo == "exacta"
    assert s_["Seccional Neuquén"].precision_geo == "aproximada" and s_["Seccional Mar del Plata"].precision_geo == "manual"
    assert s_["Seccional Salta"].precision_geo == "sin_geo" and s_["Delegación Ruta 40"].numero == "S/N"
    assert s_["Seccional Tierra del Fuego"].provincia.startswith("Tierra del Fuego, Antártida")
    assert s_["Seccional Rosario"].responsable == "Raúl Benítez" and s_["Sede Central"].telefono == "011 4131-4291/4311"


def test_el_responsable_se_actualiza_y_lo_vacio_no_pisa():
    pid, sid, eq = _mundo()
    cab = "nombre;calle;numero;provincia;localidad;latitud;longitud;responsable\n"
    uno = (cab + "A;C;1;Salta;Salta;-24,78;-65,41;Ana Paz\nB;C;1;Salta;Salta;-24,79;-65,42;Beto Gil\n").encode()
    assert _carga(eq, pid, uno).status_code == 200
    dos = (cab + "A;C;1;Salta;Salta;-24,78;-65,41;Carla Sosa\nB;C;1;Salta;Salta;-24,79;-65,42;\n").encode()
    op = {"actualizar_existentes": True}
    assert _carga(eq, pid, dos, opciones=op).status_code == 200
    s_ = {x.nombre: x for x in _seccionales(sid)}
    assert s_["A"].responsable == "Carla Sosa" and s_["B"].responsable == "Beto Gil"


def test_el_ejemplo_viejo_da_lo_mismo_que_antes():
    r = _leer(EJEMPLO.read_bytes())
    assert [f["estado"] for f in r["filas"]].count("valida") == 6 and [f["estado"] for f in r["filas"]].count("dudosa") == 2
    assert r["mapeo"]["sin_usar"] == [] and r["mapeo"]["faltan"] == []
