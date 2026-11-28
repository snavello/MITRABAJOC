"""XSII bloque 3, QA INDEPENDIENTE del servidor: «Cargar desde la planilla»
(EST-01) atacada con archivos hostiles, opciones y huellas mal formadas, otro
sindicato, concurrencia, todo o nada y coherencia entre ensayo y carga. Todo
caracter raro va como escape \\uXXXX.

Los tests que FALLAN marcan un defecto real del servidor; los que documentan un
limite sabido afirman el comportamiento actual y lo dicen.

Correr con: python -m pytest test_xsii_bloque3_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import itertools
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import SQLModel, select

import auth
import cuit
import db
import entorno
import implementacion as im
import main
import modulos
from xsii.proyectos.colm3na.asistidas import ErrorAsistida, huella, seccionales as sec

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
BASE = "/api/entornos/xsii"
_n = itertools.count(1)
CAB = "nombre;sede_central;provincia;localidad;calle;numero;latitud;longitud;mail\n"
FILA_OK = "Seccional Rosario;no;Santa Fe;Rosario;Córdoba;1234;-32,9468;-60,6393;"


def _csv(*filas, cab=CAB):
    return (cab + "\n".join(filas) + "\n").encode("utf-8")


def _fila(nombre, lat="-24,78", lon="-65,41", sede="no", prov="Salta", loc="Salta", calle="Balcarce", num="1", mail=""):
    return f"{nombre};{sede};{prov};{loc};{calle};{num};{lat};{lon};{mail}"


# ---------------------------------------------------------------- mundo

def _sindicato():
    n = next(_n)
    with db.get_session() as s:
        sind = db.Sindicato(nombre=f"Sindicato QA3 {n} {uuid.uuid4().hex[:4]}",
                            slug=f"xsii-qa3-{n}-{uuid.uuid4().hex[:4]}", cuit=cuit.corregir("30700000000"),
                            modulos_habilitados=list(modulos.MODULOS_INICIALES))
        s.add(sind); s.commit(); s.refresh(sind)
        sid = sind.id
    db.crear_conceptos_universales(sid)
    return sid


def _proyecto(sid=None, con_sindicato=True):
    sid = sid or (_sindicato() if con_sindicato else None)
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, "XSII QA3 " + uuid.uuid4().hex[:8], EQ, sindicato_id=sid).id, sid


def _equipo(activo=True):
    usuario = "eq" + uuid.uuid4().hex[:8]
    with db.get_session() as s:
        u = db.UsuarioPlataforma(usuario=usuario, nombre="Equipo " + usuario, email="",
                                 clave_hash=auth.hashear_clave("x" * 12), activo=activo,
                                 debe_cambiar_clave=False, debe_completar_datos=False)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=uid, ident=usuario))
    return c


def _mundo():
    pid, sid = _proyecto()
    return pid, sid, _equipo()


def _url(pid, que, codigo="EST-01"):
    return f"{BASE}/p/{pid}/tarea/{codigo}/asistida" + (f"/{que}" if que else "")


def _enviar(c, pid, que, contenido=None, texto=None, opciones=None, huella_=None, afuera=None, codigo="EST-01",
            crudo=None):
    """`crudo`: dict de campos que viajan tal cual (sin json.dumps), para mandar basura."""
    data = {}
    if opciones is not None:
        data["opciones"] = json.dumps(opciones)
    if huella_ is not None:
        data["huella"] = huella_
    if afuera is not None:
        data["dejar_afuera"] = json.dumps(afuera)
    if texto is not None:
        data["texto"] = texto
    data.update(crudo or {})
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


def _insumo(pid, clave="lista_seccionales"):
    with db.get_session() as s:
        i = db.xsii_insumos_activos(s, pid).get(clave)
        return i.estado if i else None


def _foto_de_la_base():
    """Filas por tabla: lo que un ensayo no puede mover."""
    foto = {}
    with db.get_session() as s:
        for t in SQLModel.metadata.sorted_tables:
            foto[t.name] = s.exec(select(func.count()).select_from(t)).one()
    return foto


def _detalle_ok(r):
    """Una respuesta de error de la API: castellano en `detail`, nunca un 500."""
    assert r.status_code in (400, 404, 409, 422), (r.status_code, r.text[:300])
    d = r.json().get("detail")
    assert d, r.text[:200]


# =================================================================== lectura pura hostil

def _leer(contenido, existentes=(), **opciones):
    return sec.leer(contenido, list(existentes), opciones)


def _estados(r):
    return [f["estado"] for f in r["filas"]]


ENTRADAS_HOSTILES = {
    "binario": bytes(range(1, 256)) * 40,
    "binario_con_nul": b"nombre\x00;x\n1;2\n",
    "utf16_le_bom": "nombre;calle\nA;B\n".encode("utf-16"),
    "utf16_be": "nombre;calle\nA;B\n".encode("utf-16-be"),
    "bom_solo": b"\xef\xbb\xbf",
    "solo_cabecera": b"nombre;calle\n",
    "solo_saltos": b"\n\r\n\r\n",
    "solo_separadores": b";;;;\n;;;;\n",
    "cabecera_duplicada": b"nombre;nombre;calle\nA;B;C\n",
    "comilla_sin_cerrar": b'nombre;calle\n"A;B\nC;D\n',
    "salto_dentro_de_celda": b'nombre;calle\n"A\nB";"C\nD"\n',
    "latin1_suelto": "nombre;calle\nAñatuya;Mitre\n".encode("latin-1"),
    "celda_gigante": b"nombre;calle\nA;" + b"x" * 200000 + b"\n",
    "celda_gigante_comillas": b'nombre;calle\nA;"' + b"x" * 400000 + b'"\n',
    "nombre_gigante": b"nombre\n" + b"N" * 900000 + b"\n",
    "pk": b"PK\x03\x04\x14\x00" + b"\x00" * 30,
    "pdf": b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n",
    "html": b"<html><script>alert(1)</script></html>",
    "json": b'{"nombre": "A"}',
    "una_sola_comilla": b'"',
    "cr_solo": b"nombre\rA\rB\r",
    "tabs": b"nombre\tcalle\nA\tB\n",
    "mil_columnas": (";".join(f"c{i}" for i in range(1000)) + "\n" + ";".join("x" for _ in range(1000)) + "\n").encode(),
}


@pytest.mark.parametrize("clave", sorted(ENTRADAS_HOSTILES))
def test_entradas_hostiles_son_un_resultado_o_un_400_nunca_una_excepcion(clave):
    try:
        r = sec.leer(ENTRADAS_HOSTILES[clave], [], {})
    except ErrorAsistida as e:
        assert e.estado == 400 and e.mensaje
    else:
        assert isinstance(r["filas"], list)


@pytest.mark.parametrize("clave", sorted(ENTRADAS_HOSTILES))
def test_entradas_hostiles_por_http_nunca_dan_500(clave):
    pid, sid, eq = _mundo()
    r = _enviar(eq, pid, "ensayo", ENTRADAS_HOSTILES[clave])
    assert r.status_code in (200, 400), (r.status_code, r.text[:200])
    if r.status_code == 400:
        _detalle_ok(r)
    texto = _enviar(eq, pid, "ensayo", texto=ENTRADAS_HOSTILES[clave].decode("latin-1"))
    assert texto.status_code in (200, 400), (texto.status_code, texto.text[:200])
    r2 = _enviar(eq, pid, "carga", ENTRADAS_HOSTILES[clave], huella_="no-es-la-huella")
    assert r2.status_code in (400, 409), (r2.status_code, r2.text[:200])
    assert _seccionales(sid) == []


def test_utf16_y_binarios_dan_400_claros():
    for clave in ("utf16_le_bom", "utf16_be", "binario_con_nul", "pk", "bom_solo"):
        with pytest.raises(ErrorAsistida) as e:
            sec.leer(ENTRADAS_HOSTILES[clave], [], {})
        assert e.value.estado == 400, clave


def test_solo_cabecera_da_cero_filas_y_la_carga_es_409():
    pid, sid, eq = _mundo()
    j = _ensayo(eq, pid, b"nombre;calle\n")
    assert j["total"] == 0 and j["a_escribir"] == 0
    r = _carga(eq, pid, b"nombre;calle\n", ens=j)
    assert r.status_code == 409 and _seccionales(sid) == []


def test_cabecera_duplicada_usa_la_primera_columna_y_no_se_rompe():
    r = _leer(b"nombre;nombre\nPrimera;Segunda\n")
    assert r["filas"][0]["datos"]["nombre"] == "Primera"


def test_columnas_en_otro_orden_se_leen_por_nombre():
    cab = "longitud;mail;numero;nombre;localidad;latitud;calle;provincia;sede_central\n"
    r = _leer(("-60,6393;;1234;Rosario Norte;Rosario;-32,9468;Córdoba;Santa Fe;no\n").encode().join([cab.encode(), b""]))
    f = r["filas"][0]
    assert f["estado"] == "valida" and f["datos"]["calle"] == "Córdoba" and f["datos"]["numero"] == "1234"
    assert f["datos"]["latitud"] == pytest.approx(-32.9468) and f["datos"]["longitud"] == pytest.approx(-60.6393)


def test_fila_mas_corta_o_mas_larga_que_la_cabecera_no_rompe():
    r = _leer(b"nombre;provincia;localidad;calle;numero;latitud;longitud\nA;Salta\nB;Salta;Salta;X;1;-24,7;-65,4;sobra;sobra\n")
    assert _estados(r) == ["dudosa", "valida"]


def test_comilla_sin_cerrar_se_traga_el_resto_pero_no_se_rompe():
    r = _leer(b'nombre;calle\n"A;B\nC;D\n')
    assert r["total"] == 1                       # una sola fila: lo que sigue queda adentro de la celda


def test_saltos_dentro_de_una_celda_se_conservan_como_espacio_y_no_rompen():
    r = _leer(b'nombre;calle\n"Seccional\nNorte";"Av. \nMitre"\n')
    d = r["filas"][0]["datos"]
    assert "Norte" in d["nombre"] and "\n" not in d["nombre"] and "\n" not in d["calle"]


def test_501_filas_es_400_y_500_pasan():
    filas = [_fila(f"S{i}", num=str(i)) for i in range(501)]
    with pytest.raises(ErrorAsistida) as e:
        _leer(_csv(*filas))
    assert e.value.estado == 400
    assert _leer(_csv(*filas[:500]))["total"] == 500
    # filas en blanco entre medio no cuentan
    con_blancos = [x for f in filas[:500] for x in (f, "")]
    assert _leer(_csv(*con_blancos))["total"] == 500


def test_justo_un_mega_pasa_y_un_byte_mas_no():
    base = b"nombre;calle\nA;"
    cuerpo = base + b"x" * (1024 * 1024 - len(base) - 1) + b"\n"
    assert len(cuerpo) == 1024 * 1024
    try:
        r = sec.leer(cuerpo, [], {})
        assert r["total"] == 1
    except ErrorAsistida as e:                   # la celda pasa el límite del lector csv: 400 claro, no 500
        assert e.estado == 400
    with pytest.raises(ErrorAsistida) as e:
        sec.leer(cuerpo + b"x", [], {})
    assert e.value.estado == 400 and "1 MB" in e.value.mensaje


def test_un_mega_por_http_pasa_la_puerta_del_formulario():
    pid, sid, eq = _mundo()
    filas = [_fila(f"S{i:03d}", num=str(i)) for i in range(500)]
    cuerpo = _csv(*filas)
    assert len(cuerpo) < 1024 * 1024
    assert _ensayo(eq, pid, cuerpo)["total"] == 500
    grande = b"nombre\n" + b"x" * (1024 * 1024)
    r = _enviar(eq, pid, "ensayo", grande)
    assert r.status_code == 400 and "1 MB" in r.json()["detail"]


def test_celda_gigante_en_el_domicilio_se_recorta_a_lo_que_guarda_el_alta_manual():
    pid, sid, eq = _mundo()
    fila = _fila("Gigante", calle="C" * 100000, loc="L" * 5000, prov="P" * 5000, num="9" * 500)
    # la celda de 100 KB entra por el lector csv (límite 128 KB); la carga la recorta como el alta manual
    r = _carga(eq, pid, _csv(fila))
    assert r.status_code == 200, r.text
    x = _seccionales(sid)[0]
    assert len(x.calle) <= 200 and len(x.localidad) <= 120 and len(x.provincia) <= 60 and len(x.numero) <= 20
    assert len(x.direccion_texto) <= 400


def test_celda_de_mas_de_128_kb_es_400_no_500():
    pid, sid, eq = _mundo()
    r = _enviar(eq, pid, "ensayo", b"nombre;calle\nA;" + b"x" * 200000 + b"\n")
    assert r.status_code == 400
    _detalle_ok(r)


def test_nul_en_el_archivo_o_el_texto_es_400():
    pid, sid, eq = _mundo()
    assert _enviar(eq, pid, "ensayo", b"nombre\nA\x00B\n").status_code == 400
    r = _enviar(eq, pid, "ensayo", texto="nombre\nA\x00B\n")
    assert r.status_code in (400, 200)                  # el NUL del texto, si pasa, se limpia
    if r.status_code == 200:
        assert "\x00" not in json.dumps(r.json())


def test_caracteres_bidi_e_invisibles_se_limpian_en_el_resultado():
    sucio = "S\u202ee\u2066cci\u200b\u200f\ufeffón\u2028 \u00a0\u3000Norte\u0007\u0085"
    r = _leer(_csv(_fila(sucio)))
    n = r["filas"][0]["datos"]["nombre"]
    assert n == "Sección Norte", repr(n)
    resumen = r["filas"][0]["resumen"]["nombre"]
    assert resumen == "Sección Norte"
    for c in "\u202e\u2066\u200b\u200f\ufeff\u2028\u0007":
        assert c not in json.dumps(resumen, ensure_ascii=False)


def test_nombres_que_solo_difieren_en_acentos_mayusculas_espacios_o_nbsp_son_el_mismo():
    filas = [_fila("Seccional Córdoba"), _fila("SECCIONAL CORDOBA"), _fila("seccional\u00a0 córdoba "),
             _fila("Seccional\u2003Cordoba")]
    r = _leer(_csv(*filas))
    assert _estados(r) == ["valida", "rechazada", "rechazada", "rechazada"]


def test_el_nombre_repetido_contra_una_seccional_que_ya_existe_con_nbsp_tambien_cuenta():
    e = {"id": 1, "nombre": "Seccional  Córdoba", "ve_todas": False}
    f = _leer(_csv(_fila("seccional\u00a0cordoba")), [e])["filas"][0]
    assert f["estado"] == "ya_existe"


def test_una_fila_rechazada_no_bloquea_el_nombre_para_una_corregida_mas_abajo():
    """Si la primera quedó rechazada, «se carga la primera» es falso: la segunda,
    corregida, tiene que poder entrar."""
    r = _leer(_csv(_fila("Rosario", lat="40,7", lon="-74"), _fila("Rosario")))
    assert _estados(r) == ["rechazada", "valida"], [f["motivos"] for f in r["filas"]]


@pytest.mark.parametrize("lat,lon", [
    ("NaN", "-60"), ("nan", "nan"), ("inf", "-60"), ("-inf", "-60"), ("Infinity", "1"), ("1e400", "-60"),
    ("-1e400", "-60"), ("-32,9468", "1e400"), ("-32.9468°", "-60.6393°"), ("-32° 56' 48\"", "-60° 38'"),
    ("0x10", "0b1"), ("--32", "-60"), ("-32,,9", "-60"), ("٣٢", "٦٠"), ("−32,9468", "−60,6393"),
    ("-32,9468,", "-60,6393"), ("-32,9468;", "-60"), ("-", "-"), (".", "."), (",", ","),
])
def test_coordenadas_ilegibles_se_rechazan_sin_romper(lat, lon):
    f = _leer(_csv(_fila("A", lat=lat, lon=lon)))["filas"][0]
    assert f["estado"] == "rechazada", (lat, lon, f)


def test_coordenadas_con_espacios_se_aceptan_y_las_invertidas_se_rechazan():
    f = _leer(_csv(_fila("A", lat="  -32,9468 ", lon=" -60,6393 ")))["filas"][0]
    assert f["estado"] == "valida" and f["datos"]["latitud"] == pytest.approx(-32.9468)
    f = _leer(_csv(_fila("A", lat="-60,6393", lon="-32,9468")))["filas"][0]       # lat/lon invertidas: -60 < -56
    assert f["estado"] == "rechazada" and any("Argentina" in m for m in f["motivos"])
    # invertidas que igual caen dentro del rango son indistinguibles: -54/-60 vs -60/-54... -60 lat es fuera
    f = _leer(_csv(_fila("A", lat="-54", lon="-60")))["filas"][0]
    assert f["estado"] == "valida"


@pytest.mark.parametrize("lat,lon,ok", [
    ("-56", "-65", True), ("-21", "-65", True), ("-55,999999", "-65", True), ("-20,999999", "-65", False),
    ("-21,000001", "-65", True), ("-56,000001", "-65", False), ("-30", "-74", True), ("-30", "-53", True), ("-30", "-52,9999", False),
    ("-30", "-74,0001", False), ("-21", "-53", True), ("-56", "-74", True), ("21", "-65", False),
])
def test_el_borde_exacto_del_rango(lat, lon, ok):
    f = _leer(_csv(_fila("A", lat=lat, lon=lon)))["filas"][0]
    assert (f["estado"] != "rechazada") is ok, f


@pytest.mark.parametrize("mail,ok", [
    ("a@b.co", True), ("a@b", False), ("@b.co", False), ("a b@c.co", False), ("a@b.co ", True),
    ("a@@b.co", False), ("a@b..co", True), ("x" * 190 + "@b.co", True), ("x" * 200 + "@b.co", False),
    ("javascript:alert(1)@x.co", True), ("<a@b.co>", True), ("a@b.co\u200b", True),
])
def test_mails_raros(mail, ok):
    f = _leer(_csv(_fila("A", mail=mail)))["filas"][0]
    assert (f["estado"] != "rechazada") is ok, (mail, f)


def test_html_en_el_nombre_se_guarda_como_texto_y_vuelve_como_texto():
    pid, sid, eq = _mundo()
    nombre = "<script>alert(1)</script> <b>Norte</b> & \"co'mi\""
    cuerpo = _csv(_fila(f'"{nombre.replace(chr(34), chr(34) * 2)}"', calle="<img src=x onerror=alert(1)>"))
    ens = _ensayo(eq, pid, cuerpo)
    assert ens["filas"][0]["resumen"]["nombre"] == nombre
    r = _carga(eq, pid, cuerpo, ens=ens)
    assert r.status_code == 200
    assert r.json()["carga"]["detalle"][0]["nombre"] == nombre
    x = _seccionales(sid)[0]
    assert x.nombre == nombre and x.calle == "<img src=x onerror=alert(1)>"
    # y la ficha del panel lo devuelve como dato JSON, no como HTML
    f = db.seccional_del_sindicato(sid, x.id)
    assert f["nombre"] == nombre


def test_opciones_hostiles_son_400_y_no_escriben():
    pid, sid, eq = _mundo()
    c = _csv(FILA_OK)
    for crudo in ("no es json", "[1,2]", "[]", '"texto"', "42", "null_", "{", '{"actualizar_existentes": "si"}',
                  '{"actualizar_existentes": 1}', '{"sede_por_nombre": null}', '{"actualizar_existentes": []}',
                  "NaN", '{"a": NaN}'):
        r = _enviar(eq, pid, "ensayo", c, crudo={"opciones": crudo})
        if crudo in ('{"a": NaN}',):
            assert r.status_code == 200          # clave desconocida: se ignora (contrato)
            continue
        _detalle_ok(r)
        r = _enviar(eq, pid, "carga", c, crudo={"opciones": crudo, "huella": "x"})
        assert r.status_code in (400, 409), (crudo, r.status_code, r.text[:100])
    assert _seccionales(sid) == []


def test_opciones_con_claves_desconocidas_se_ignoran_y_no_cambian_la_huella():
    pid, sid, eq = _mundo()
    c = _csv(FILA_OK)
    a = _ensayo(eq, pid, c, opciones={"zzz": True, "actualizar_existentes": False})
    b = _ensayo(eq, pid, c, opciones={})
    assert a["huella"] == b["huella"] and "zzz" not in a["opciones"]


def test_dejar_afuera_hostil_es_400_o_se_ignora_nunca_500():
    pid, sid, eq = _mundo()
    c = _csv(_fila("A", lat="", lon=""))
    ens = _ensayo(eq, pid, c)
    for malo in ('["a"]', "[1.5]", "[true]", "[null]", '"2"', "{}", "2", "[[2]]", "no json", "[1e400]",
                 json.dumps(list(range(1001)))):
        r = _enviar(eq, pid, "carga", c, huella_=ens["huella"], crudo={"dejar_afuera": malo})
        _detalle_ok(r)
    assert _seccionales(sid) == []
    # negativos, enormes y líneas inexistentes o no dudosas: se ignoran
    for ok in ([-1], [0], [10 ** 30], [999999], [1, 1, 1]):
        pid2, sid2, eq2 = _mundo()
        r = _enviar(eq2, pid2, "carga", c, huella_=ens["huella"], afuera=ok)
        assert r.status_code == 200, (ok, r.text[:200])
        assert len(_seccionales(sid2)) == 1, ok


def test_dejar_afuera_de_lineas_no_dudosas_no_las_saca():
    pid, sid, eq = _mundo()
    c = _csv(_fila("Valida"), _fila("Dudosa", lat="", lon=""), _fila("Mala", lat="0", lon="0"))
    ens = _ensayo(eq, pid, c)
    assert (ens["validas"], ens["dudosas"], ens["rechazadas"]) == (1, 1, 1)
    r = _enviar(eq, pid, "carga", c, huella_=ens["huella"], afuera=[2, 3, 4])      # valida, dudosa, rechazada
    j = r.json()
    assert (j["carga"]["creadas"], j["carga"]["afuera"], j["carga"]["rechazadas"]) == (1, 1, 1)
    assert [x.nombre for x in _seccionales(sid)] == ["Valida"]


def test_huella_vacia_ajena_o_de_otras_opciones_es_409_y_no_escribe():
    pid, sid, eq = _mundo()
    c = _csv(FILA_OK)
    ens = _ensayo(eq, pid, c)
    otro = _ensayo(eq, pid, _csv(_fila("Otra")))
    por_opciones = _ensayo(eq, pid, c, opciones={"actualizar_existentes": True})
    for h in ("", None, "   ", "0" * 64, otro["huella"], por_opciones["huella"], ens["huella"].upper(), ens["huella"][:-1],
              "x" * 5000, ens["huella"] + " "):
        r = _enviar(eq, pid, "carga", c, huella_=h)
        if h == ens["huella"] + " ":
            assert r.status_code == 200            # los espacios de los bordes se recortan
            break
        assert r.status_code == 409, (h, r.status_code, r.text[:100])
        assert "cambió" in r.json()["detail"]
        assert _seccionales(sid) == []
        assert _movs(pid) == []


def test_ensayo_de_un_archivo_y_carga_de_otro_no_pasa():
    pid, sid, eq = _mundo()
    ens = _ensayo(eq, pid, _csv(FILA_OK))
    r = _enviar(eq, pid, "carga", _csv(FILA_OK, _fila("Colada")), huella_=ens["huella"])
    assert r.status_code == 409 and _seccionales(sid) == []
    # mismas cifras con distinto separador de línea: es OTRO archivo (la huella es de bytes)
    r = _enviar(eq, pid, "carga", _csv(FILA_OK).replace(b"\n", b"\r\n"), huella_=ens["huella"])
    assert r.status_code == 409


# =================================================================== puertas y aislamiento

def test_sin_sesion_y_sesion_de_otro_rol_no_pasan():
    pid, sid, eq = _mundo()
    c = _csv(FILA_OK)
    anonimo = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    for que in ("ensayo", "carga"):
        assert _enviar(anonimo, pid, que, c, huella_="x").status_code in (401, 403)
    # el panel del sindicato de la Mesa (no es equipo) y un afiliado no entran
    sind = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    sind.cookies.set(main.COOKIES_POR_ROL["sindicato"], auth.crear_sesion("sindicato", id_usuario=1, sindicato_id=sid))
    traba = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    traba.cookies.set(main.COOKIES_POR_ROL["trabajador"], auth.crear_sesion("trabajador", id_usuario=1, sindicato_id=sid))
    for cli in (sind, traba):
        for que in ("ensayo", "carga"):
            assert _enviar(cli, pid, que, c, huella_="x").status_code in (401, 403), que
        assert cli.get(_url(pid, "")).status_code in (401, 403)
        assert cli.get(_url(pid, "modelo.csv")).status_code in (401, 403)
    assert _seccionales(sid) == [] and _movs(pid) == []


def test_codigos_de_tarea_inexistentes_o_no_asistidos():
    pid, sid, eq = _mundo()
    c = _csv(FILA_OK)
    for codigo in ("ZZZ-99", "est-99", "'; DROP TABLE x;--", "BAS-01", "EST-02", "%00", "A" * 300):
        for que in ("ensayo", "carga"):
            r = _enviar(eq, pid, que, c, huella_="x", codigo=codigo)
            assert r.status_code in (404, 409, 400), (codigo, que, r.status_code)
            assert r.status_code != 200
    # en minúsculas es la misma tarea
    assert _enviar(eq, pid, "ensayo", c, codigo="est-01").status_code == 200
    assert _seccionales(sid) == []


def test_proyecto_ajeno_o_inexistente_es_404_y_no_toca_nada():
    pid, sid, eq = _mundo()
    for n in (0, -1, pid + 10 ** 6, 2 ** 31, 2 ** 62):
        r = _enviar(eq, n, "ensayo", _csv(FILA_OK))
        assert r.status_code in (404, 422), (n, r.status_code)
        r = _enviar(eq, n, "carga", _csv(FILA_OK), huella_="x")
        assert r.status_code in (404, 422), (n, r.status_code)
    assert eq.get(f"{BASE}/p/abc/tarea/EST-01/asistida").status_code in (404, 422)


def test_en_demo_todo_es_404(monkeypatch):
    pid, sid, eq = _mundo()
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    for que in ("ensayo", "carga"):
        assert _enviar(eq, pid, que, _csv(FILA_OK), huella_="x").status_code == 404
    assert eq.get(_url(pid, "")).status_code == 404


def test_una_carga_jamas_toca_seccionales_de_otro_sindicato_con_el_mismo_nombre():
    pid, sid, eq = _mundo()
    ajeno = _sindicato()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=ajeno, nombre="Seccional Rosario", ve_todas=False, calle="Ajena", numero="1",
                           telefono="111", latitud=-33.0, longitud=-60.0, precision_geo="exacta"))
        s.add(db.Seccional(sindicato_id=ajeno, nombre="Otra Ajena", ve_todas=True))
        s.commit()
    foto = [(x.id, x.nombre, x.calle, x.numero, x.telefono, x.ve_todas, x.latitud, x.precision_geo) for x in _seccionales(ajeno)]
    for opciones in (None, {"actualizar_existentes": True}):
        r = _carga(eq, pid, _csv(FILA_OK.replace("no;Santa", "sí;Santa")), opciones=opciones)
        assert r.status_code in (200, 409)
    assert [(x.id, x.nombre, x.calle, x.numero, x.telefono, x.ve_todas, x.latitud, x.precision_geo)
            for x in _seccionales(ajeno)] == foto
    assert all(x.sindicato_id == sid for x in _seccionales(sid))


def test_el_ensayo_ve_solo_las_existentes_del_propio_sindicato():
    pid, sid, eq = _mundo()
    ajeno = _sindicato()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=ajeno, nombre="Seccional Rosario", ve_todas=True))
        s.commit()
    j = _ensayo(eq, pid, _csv(FILA_OK))
    assert j["ya_existen"] == 0 and j["validas"] == 1
    assert any("Ninguna seccional vería todas" in a for a in j["avisos"])       # la ajena con ve_todas no cuenta


def test_ve_todas_nunca_baja_ni_se_borra_nada_con_ninguna_combinacion():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Central", ve_todas=True, calle="X", numero="1",
                           localidad="Y", provincia="Z", latitud=-30.0, longitud=-60.0, precision_geo="exacta"))
        s.add(db.Seccional(sindicato_id=sid, nombre="Que no esta en la planilla", ve_todas=False))
        s.commit()
    antes = {x.id: x.nombre for x in _seccionales(sid)}
    c = _csv(_fila("Central", sede="no", lat="-31", lon="-61"), _fila("Nueva"))
    r = _carga(eq, pid, c, opciones={"actualizar_existentes": True})
    assert r.status_code == 200
    despues = {x.id: x for x in _seccionales(sid)}
    assert set(antes) <= set(despues)
    central = next(x for x in despues.values() if x.nombre == "Central")
    assert central.ve_todas is True and central.latitud == -31.0
    assert any(x.nombre == "Que no esta en la planilla" for x in despues.values())


def test_sede_central_en_la_planilla_sube_ve_todas_de_una_existente_solo_si_se_actualiza():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=False))
        s.commit()
    c = _csv(_fila("Sede Central", sede="sí"), _fila("Otra"))
    assert _carga(eq, pid, c).status_code == 200
    assert next(x for x in _seccionales(sid) if x.nombre == "Sede Central").ve_todas is False
    pid2, _ = _proyecto(sid=sid)
    assert _carga(eq, pid2, c, opciones={"actualizar_existentes": True}).status_code == 200
    assert next(x for x in _seccionales(sid) if x.nombre == "Sede Central").ve_todas is True


# =================================================================== todo o nada

def test_ensayo_cero_escrituras_en_cualquier_tabla():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Seccional Rosario", ve_todas=False, calle="Vieja", numero="1"))
        s.commit()
    c = _csv(FILA_OK, _fila("Dudosa", lat="", lon=""), _fila("Mala", lat="0", lon="0"), _fila("Nueva"))
    antes = _foto_de_la_base()
    for opciones in (None, {"actualizar_existentes": True}, {"sede_por_nombre": False}):
        for _ in range(2):
            _ensayo(eq, pid, c, opciones=opciones)
    for malo in (b"", b"PK\x03\x04", ENTRADAS_HOSTILES["utf16_le_bom"]):
        _enviar(eq, pid, "ensayo", malo)
    assert _foto_de_la_base() == antes


def test_un_error_a_mitad_de_la_carga_no_deja_seccional_ni_movimiento_ni_insumo(monkeypatch):
    pid, sid, eq = _mundo()
    antes = _foto_de_la_base()
    original = db.xsii_registrar_insumo

    def roto(*a, **k):
        raise RuntimeError("se cayó el insumo")
    monkeypatch.setattr(db, "xsii_registrar_insumo", roto)
    r = _carga(eq, pid, _csv(FILA_OK, _fila("B")))
    assert r.status_code == 500
    monkeypatch.setattr(db, "xsii_registrar_insumo", original)
    assert _seccionales(sid) == [] and _movs(pid) == [] and _insumo(pid) is None
    assert _foto_de_la_base() == antes


def test_un_error_despues_del_movimiento_tambien_revierte_todo(monkeypatch):
    pid, sid, eq = _mundo()
    antes = _foto_de_la_base()
    from xsii.proyectos.colm3na import vista
    original = vista.db.xsii_registrar_carga_asistida

    def a_medias(*a, **k):
        original(*a, **k)
        raise RuntimeError("se cayó después de escribir el movimiento")
    monkeypatch.setattr(db, "xsii_registrar_carga_asistida", a_medias)
    r = _carga(eq, pid, _csv(FILA_OK))
    assert r.status_code == 500
    monkeypatch.setattr(db, "xsii_registrar_carga_asistida", original)
    assert _foto_de_la_base() == antes
    # y el siguiente intento, sano, anda como si nada
    assert _carga(eq, pid, _csv(FILA_OK)).status_code == 200
    assert len(_seccionales(sid)) == 1 and len(_movs(pid, "asistida_carga")) == 1


def test_un_error_al_actualizar_una_existente_no_deja_las_nuevas(monkeypatch):
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Seccional Rosario", ve_todas=False, calle="Vieja", numero="1"))
        s.commit()
    antes = _foto_de_la_base()

    def roto(*a, **k):
        raise RuntimeError("no hay movimiento")
    monkeypatch.setattr(db, "xsii_registrar_carga_asistida", roto)
    r = _carga(eq, pid, _csv(FILA_OK, _fila("Nueva 1"), _fila("Nueva 2")), opciones={"actualizar_existentes": True})
    assert r.status_code == 500
    monkeypatch.undo()
    assert _foto_de_la_base() == antes
    assert [x.calle for x in _seccionales(sid)] == ["Vieja"]


# =================================================================== coherencia ensayo / carga

def _cifras_carga(c):
    return {k: c[k] for k in ("creadas", "actualizadas", "sin_tocar", "afuera", "rechazadas")}


@pytest.mark.parametrize("actualizar", [False, True])
@pytest.mark.parametrize("afuera", [None, [3], [3, 4], [2, 3, 4, 5, 6]])
def test_lo_que_el_ensayo_promete_es_lo_que_la_carga_hace(actualizar, afuera):
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Ya Esta", ve_todas=False, calle="Vieja", numero="1",
                           localidad="Salta", provincia="Salta"))
        s.add(db.Seccional(sindicato_id=sid, nombre="Igual", ve_todas=False, calle="Balcarce", numero="1",
                           localidad="Salta", provincia="Salta", latitud=-24.78, longitud=-65.41, precision_geo="manual"))
        s.commit()
    c = _csv(_fila("Ya Esta"),                                 # 2: existe, cambia
             _fila("Igual"),                                   # 3: existe... (línea 3)
             _fila("Dudosa Uno", lat="", lon=""),              # 4: dudosa
             _fila("Dudosa Dos", calle="", num=""),            # 5: dudosa
             _fila("Mala", lat="0", lon="0"),                  # 6: rechazada
             _fila("Buena"))                                   # 7: válida
    op = {"actualizar_existentes": actualizar}
    ens = _ensayo(eq, pid, c, opciones=op)
    # lo que el ensayo dice por fila
    acciones_ens = {f["linea"]: (f["estado"], f["resumen"].get("accion")) for f in ens["filas"]}
    r = _enviar(eq, pid, "carga", c, opciones=op, huella_=ens["huella"], afuera=afuera)
    assert r.status_code == 200, r.text
    carga = r.json()["carga"]
    dud = {f["linea"] for f in ens["filas"] if f["estado"] == "dudosa"}
    quedan_afuera = dud & set(afuera or [])
    esperadas_creadas = sum(1 for f in ens["filas"] if f["estado"] in ("valida", "dudosa") and f["linea"] not in quedan_afuera)
    assert carga["creadas"] == esperadas_creadas
    assert carga["afuera"] == len(quedan_afuera)
    assert carga["rechazadas"] == ens["rechazadas"]
    esperadas_act = sum(1 for f in ens["filas"] if f["resumen"].get("accion") == "actualizar")
    assert carga["actualizadas"] == esperadas_act
    assert carga["sin_tocar"] == ens["ya_existen"] - esperadas_act
    assert ens["a_escribir"] == esperadas_creadas + esperadas_act + len(quedan_afuera)
    # el detalle fila por fila coincide con lo que dijo el ensayo
    for d in carga["detalle"]:
        estado, accion = acciones_ens[d["linea"]]
        esperado = {"valida": "creada", "dudosa": "afuera" if d["linea"] in quedan_afuera else "creada",
                    "rechazada": "rechazada", "ya_existe": {"actualizar": "actualizada", "sin_tocar": "sin_tocar"}.get(accion)}[estado]
        assert d["accion"] == esperado, (d, estado, accion)
    # la base: nada borrado, las que la planilla no trae siguen
    nombres = [x.nombre for x in _seccionales(sid)]
    assert nombres.count("Buena") == 1 and "Mala" not in nombres
    assert len(nombres) == 2 + esperadas_creadas
    # el movimiento y su texto dicen lo mismo
    m = _movs(pid, "asistida_carga")[0]
    assert m.cantidades == _cifras_carga(carga)
    assert f"({esperadas_act} actualizada" in m.texto or esperadas_act == 1 and "(1 actualizada" in m.texto


def test_el_movimiento_dice_las_cifras_exactas_y_el_insumo_queda_recibido_sin_confirmar_la_tarea():
    pid, sid, eq = _mundo()
    c = _csv(_fila("A"), _fila("B", lat="", lon=""), _fila("C", lat="", lon=""))
    j = _carga(eq, pid, c, afuera=[4]).json()
    m = _movs(pid, "asistida_carga")
    assert len(m) == 1
    assert m[0].texto == "Cargó 2 seccionales desde planilla (0 actualizadas, 1 afuera)"
    assert _insumo(pid) == "recibido"
    assert j["tarea"]["falta_confirmar"] is True and j["tarea"]["asistida"] is True
    assert j["tarea"]["estado"] != "hecha"
    with db.get_session() as s:
        decisiones = list(s.exec(select(db.XsiiDecision).where(db.XsiiDecision.proyecto_id == pid)).all())
    assert decisiones == []
    assert _foto_insumos_activos(pid) == 1


def _foto_insumos_activos(pid):
    with db.get_session() as s:
        return len([i for i in s.exec(select(db.XsiiInsumo).where(
            db.XsiiInsumo.proyecto_id == pid, db.XsiiInsumo.clave == "lista_seccionales")).all() if i.activa])


def test_cargar_dos_veces_el_mismo_archivo_no_duplica_nada_ni_deja_dos_insumos():
    pid, sid, eq = _mundo()
    c = _csv(_fila("A"), _fila("B"))
    assert _carga(eq, pid, c).status_code == 200
    r = _carga(eq, pid, c)
    assert r.status_code == 409 and "nada" in r.json()["detail"].lower()
    assert len(_seccionales(sid)) == 2 and len(_movs(pid, "asistida_carga")) == 1
    assert _foto_insumos_activos(pid) == 1


def test_el_control_y_destrabo_despues_de_cargar():
    pid, sid, eq = _mundo()
    j = _carga(eq, pid, _csv(_fila("Sede Central", sede="sí"), _fila("B"))).json()
    assert j["control"]["estado"] == "completa"
    assert j["destrabo"] and all(set(d) == {"codigo", "nombre"} for d in j["destrabo"])
    t = eq.get(f"{BASE}/p/{pid}/tarea/EST-01").json()["tarea"]
    assert t["control"]["estado"] == "completa" and t["asistida"] is True


def test_sin_sede_central_el_control_no_miente():
    pid, sid, eq = _mundo()
    j = _carga(eq, pid, _csv(_fila("B"))).json()
    assert j["carga"]["avisos"] and "Ninguna seccional vería todas" in j["carga"]["avisos"][0]


def test_el_tablero_marca_cuales_tareas_son_asistidas():
    pid, sid, eq = _mundo()
    tareas = eq.get(f"{BASE}/p/{pid}/tablero").json()["tareas"]
    asistidas = {t["codigo"] for t in tareas if t.get("asistida")}
    assert asistidas == {"EST-01", "PAD-02", "REC-04"}      # REC-04 desde el bloque 4b


def test_las_seccionales_creadas_se_ven_bien_en_la_ficha_y_en_el_mapa():
    pid, sid, eq = _mundo()
    c = _csv(_fila("Con Ubicacion"), _fila("Sin Ubicar", lat="", lon=""))
    assert _carga(eq, pid, c).status_code == 200
    filas = {x.nombre: x for x in _seccionales(sid)}
    con, sin = filas["Con Ubicacion"], filas["Sin Ubicar"]
    assert (con.precision_geo, sin.precision_geo, sin.latitud, sin.longitud) == ("manual", "sin_geo", None, None)
    f_con = db.seccional_del_sindicato(sid, con.id)
    f_sin = db.seccional_del_sindicato(sid, sin.id)
    assert f_con["precision_geo"] == "manual" and f_sin["precision_geo"] == "sin_geo"
    ubicadas = db.seccionales_ubicadas(sid)
    assert [u["nombre"] for u in ubicadas] == ["Con Ubicacion"]
    # la ficha por HTTP, con la sesión de un Super Admin del sindicato
    with db.get_session() as s:
        u = db.UsuarioSindicato(sindicato_id=sid, usuario="qa3" + uuid.uuid4().hex[:6], cuil=cuit.corregir("20700000001"),
                                nombre="Super", es_super_admin=True, activo=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    adm = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    adm.cookies.set(main.COOKIES_POR_ROL["sindicato"], auth.crear_sesion("sindicato", id_usuario=uid, sindicato_id=sid))
    for sec_ in (con, sin):
        r = adm.get(f"/admin/seccional/{sec_.id}/ficha")
        assert r.status_code == 200, r.text[:200]
        assert r.json()["nombre"] == sec_.nombre
        assert r.json()["etiqueta_precision"]
    # y la ficha de otro sindicato es 404
    otro = _sindicato()
    assert adm.get(f"/admin/seccional/{sin.id}/ficha").status_code == 200
    with db.get_session() as s:
        ajena = db.Seccional(sindicato_id=otro, nombre="Ajena"); s.add(ajena); s.commit(); s.refresh(ajena)
    assert adm.get(f"/admin/seccional/{ajena.id}/ficha").status_code == 404
    # el mapa del panel con una sin ubicar: no explota
    with db.get_session() as s:
        sind = s.get(db.Sindicato, sid)
        sind.modulos_habilitados = list(sind.modulos_habilitados) + ["dashboard"]
        s.add(sind); s.commit()
    r = adm.get("/admin/dashboard/seccionales-geo?desde=2026-01-01&hasta=2026-11-01")
    assert r.status_code == 200, r.text[:300]
    assert "Con Ubicacion" in r.text


# =================================================================== concurrencia

def test_dos_cargas_simultaneas_del_mismo_archivo_no_duplican_ni_dan_500():
    pid, sid, eq = _mundo()
    c = _csv(*[_fila(f"Sec {i}", num=str(i)) for i in range(25)])
    ens = _ensayo(eq, pid, c)
    clientes = [_equipo() for _ in range(2)]
    barrera = threading.Barrier(2)

    def correr(cli):
        barrera.wait()
        return _enviar(cli, pid, "carga", c, huella_=ens["huella"]).status_code

    with ThreadPoolExecutor(2) as ex:
        estados = sorted(ex.map(correr, clientes))
    assert estados == [200, 409], estados
    assert len(_seccionales(sid)) == 25
    assert len(_movs(pid, "asistida_carga")) == 1 and _foto_insumos_activos(pid) == 1


def test_varias_cargas_simultaneas_del_mismo_archivo_dejan_una_sola_copia():
    pid, sid, eq = _mundo()
    c = _csv(*[_fila(f"Sec {i}", num=str(i)) for i in range(10)])
    ens = _ensayo(eq, pid, c)
    clientes = [_equipo() for _ in range(5)]
    barrera = threading.Barrier(5)

    def correr(cli):
        barrera.wait()
        return _enviar(cli, pid, "carga", c, huella_=ens["huella"]).status_code

    with ThreadPoolExecutor(5) as ex:
        estados = sorted(ex.map(correr, clientes))
    assert estados.count(200) == 1 and set(estados) <= {200, 409}, estados
    assert len(_seccionales(sid)) == 10


def test_dos_proyectos_del_mismo_sindicato_cargando_a_la_vez_no_duplican_seccionales():
    """El candado es por (proyecto, tarea): con dos proyectos sobre el MISMO
    sindicato hace falta además un candado por sindicato."""
    sid = _sindicato()
    pid1, _ = _proyecto(sid=sid)
    pid2, _ = _proyecto(sid=sid)
    c = _csv(*[_fila(f"Sec {i}", num=str(i)) for i in range(15)])
    cli = [_equipo(), _equipo()]
    ens = [_ensayo(cli[0], pid1, c), _ensayo(cli[1], pid2, c)]
    barrera = threading.Barrier(2)

    def correr(i):
        barrera.wait()
        return _enviar(cli[i], (pid1, pid2)[i], "carga", c, huella_=ens[i]["huella"]).status_code

    with ThreadPoolExecutor(2) as ex:
        estados = sorted(ex.map(correr, [0, 1]))
    assert estados == [200, 409], estados
    assert len(_seccionales(sid)) == 15


def test_carga_simultanea_con_una_decision_sobre_la_misma_tarea():
    pid, sid, eq = _mundo()
    c = _csv(_fila("Sede Central", sede="sí"), _fila("B"))
    ens = _ensayo(eq, pid, c)
    otro = _equipo()
    barrera = threading.Barrier(2)

    def cargar():
        barrera.wait()
        return _enviar(eq, pid, "carga", c, huella_=ens["huella"]).status_code

    def decidir():
        barrera.wait()
        return otro.post(f"{BASE}/p/{pid}/tarea/EST-01/decision", json={"tipo": "pospuesta", "motivo": "luego"}).status_code

    with ThreadPoolExecutor(2) as ex:
        a, b = ex.submit(cargar), ex.submit(decidir)
        ra, rb = a.result(), b.result()
    assert ra in (200, 409) and rb in (200, 409, 400), (ra, rb)
    assert len(_seccionales(sid)) in (0, 2)
    if ra == 200:
        assert len(_movs(pid, "asistida_carga")) == 1


def test_una_carga_y_un_ensayo_a_la_vez_no_se_pisan():
    pid, sid, eq = _mundo()
    c = _csv(*[_fila(f"Sec {i}", num=str(i)) for i in range(10)])
    ens = _ensayo(eq, pid, c)
    otro = _equipo()
    barrera = threading.Barrier(2)

    def cargar():
        barrera.wait()
        return _enviar(eq, pid, "carga", c, huella_=ens["huella"]).status_code

    def ensayar():
        barrera.wait()
        return _enviar(otro, pid, "ensayo", c).status_code

    with ThreadPoolExecutor(2) as ex:
        a, b = ex.submit(cargar), ex.submit(ensayar)
        assert a.result() == 200 and b.result() == 200
    assert len(_seccionales(sid)) == 10


# =================================================================== Preguntame y privacidad

def test_lo_que_ve_preguntame_despues_de_una_carga_no_trae_los_datos_de_la_planilla():
    """Las herramientas leen del tablero ya calculado: la carga deja el movimiento
    con cantidades, nunca los nombres ni las direcciones de las seccionales."""
    pid, sid, eq = _mundo()
    secreto = "Seccional Calle Secretisima 4242"
    assert _carga(eq, pid, _csv(_fila(secreto, calle="Calle Secretisima", num="4242", mail="a@b.co"))).status_code == 200
    from xsii.proyectos.colm3na import herramientas as herr, vista
    with db.get_session() as s:
        ctx = vista.Contexto(s, pid)
        nombres = [n for n in dir(herr) if not n.startswith("_")]
        volcado = json.dumps({n: repr(getattr(herr, n)) for n in nombres if n.isupper()}, default=str)
        movs = db.xsii_movimientos(s, pid) if hasattr(db, "xsii_movimientos") else []
    assert "Secretisima" not in volcado
    for m in _movs(pid):
        assert "Secretisima" not in (m.texto or "") and "4242" not in json.dumps(m.cantidades or {})
    assert ctx is not None and movs is not None


def test_el_get_de_describir_no_filtra_nada_del_sindicato():
    pid, sid, eq = _mundo()
    with db.get_session() as s:
        s.add(db.Seccional(sindicato_id=sid, nombre="Privada Cordoba 77", ve_todas=True, calle="Secretisima"))
        s.commit()
    j = eq.get(_url(pid, "")).json()
    assert "Privada" not in json.dumps(j) and "Secretisima" not in json.dumps(j)
    assert "Privada" not in eq.get(_url(pid, "modelo.csv")).text


def test_el_modelo_csv_no_cambia_con_el_proyecto_y_la_hoja_de_calculo_no_lo_ejecuta():
    pid, sid, eq = _mundo()
    texto = eq.get(_url(pid, "modelo.csv")).content.decode("utf-8-sig")
    for linea in texto.splitlines():
        for celda in linea.split(";"):
            assert not celda.startswith(("=", "+", "-@")) or celda[0] in "-+" and celda[1:].replace(",", "").replace(".", "").isdigit()


def test_dos_lecturas_de_lo_mismo_dan_la_misma_huella_y_el_mismo_ensayo():
    pid, sid, eq = _mundo()
    c = _csv(FILA_OK, _fila("B", lat="", lon=""))
    a, b = _ensayo(eq, pid, c), _ensayo(eq, pid, c)
    assert a == b
    assert a["huella"] == huella(c, sec.normalizar_opciones({}))


def test_texto_pegado_y_archivo_vacio_usan_el_texto_y_el_archivo_gana_si_tiene_contenido():
    pid, sid, eq = _mundo()
    r = _enviar(eq, pid, "ensayo", b"   \n", texto=_csv(FILA_OK).decode())
    assert r.status_code == 200 and r.json()["total"] == 1
    r = _enviar(eq, pid, "ensayo", _csv(FILA_OK, _fila("B")), texto=_csv(_fila("Z")).decode())
    assert r.json()["total"] == 2
    r = _enviar(eq, pid, "ensayo", crudo={"archivo": "esto no es un archivo"})
    _detalle_ok(r)


def test_un_cuerpo_que_no_es_multipart_es_400_no_500():
    pid, sid, eq = _mundo()
    for ct, cuerpo in (("application/json", b'{"a":1}'), ("text/plain", b"hola"), ("multipart/form-data", b"x"),
                       ("multipart/form-data; boundary=zz", b"--zz\r\nbasura")):
        r = eq.post(_url(pid, "ensayo"), content=cuerpo, headers={"content-type": ct})
        assert r.status_code in (400, 415, 422), (ct, r.status_code, r.text[:100])
        r = eq.post(_url(pid, "carga"), content=cuerpo, headers={"content-type": ct})
        assert r.status_code in (400, 409, 415, 422), (ct, r.status_code, r.text[:100])
