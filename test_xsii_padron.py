"""XSII bloque 4a, PAD-02: «Cargar desde la planilla» del padrón
(docs/xsii/API.md, «Bloque 4a»). La detección del mapeo y la lectura se prueban
PURAS; el resto por HTTP con multipart real. Un test de equivalencia compara la
asistida con «Alta masiva» de Trabajadores (misma lógica, `padron_carga`).

Correr con: python -m pytest test_xsii_padron.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
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
import main
from test_xsii_asistida import BASE, _equipo, _mundo, _movs, _estado_insumo, _tarea, _sindicato
from xsii.proyectos.colm3na.asistidas import ErrorAsistida, huella, padron

db.crear_tablas()
P = "PAD-02"
EJEMPLO = pathlib.Path(__file__).parent / "docs" / "xsii" / "ejemplos" / "padron-ejemplo.csv"
_k = itertools.count(1_000_001)


def _cu(prefijo="20"):
    """Un CUIL válido y que no se repite en la corrida (rango 9xxxxxxx)."""
    while True:
        b = f"{prefijo}9{next(_k) + 3_000_000:07d}"
        d = cuit.digito_verificador(b)
        if d is not None:
            return b + str(d)


CAB = "Nro CUIL;Apellido y Nombre;Delegación;Localidad;Provincia;Email;F. Ingreso\n"


def _csv(*filas, cab=CAB):
    return (cab + "\n".join(filas) + "\n").encode("utf-8")


def _fila(cuil=None, nombre="Pérez, Juan", sec="", loc="Rosario", prov="Santa Fe", mail="", fecha=""):
    return f"{_cu() if cuil is None else cuil};{nombre};{sec};{loc};{prov};{mail};{fecha}"


# =================================================================== leer / mapeo (puro)

@pytest.mark.parametrize("cabecera,campo", [
    ("CUIL", "cuil"), ("Nro CUIL", "cuil"), ("C.U.I.L.", "cuil"), ("CUIT", "cuil"), ("Número de CUIL", "cuil"),
    ("Apellido y Nombre", "nombre"), ("Nombre completo", "nombre"), ("Afiliado", "nombre"), ("Nombres", "nombre"),
    ("Apellido", "apellido"), ("Domicilio", "calle"), ("Dirección", "calle"), ("Calle", "calle"),
    ("Altura", "numero"), ("Nro", "numero"), ("Número", "numero"), ("Piso", "piso_depto"), ("Dpto", "piso_depto"),
    ("Ciudad", "localidad"), ("Localidad", "localidad"), ("Provincia", "provincia"), ("CP", "codigo_postal"),
    ("Código Postal", "codigo_postal"), ("Tel", "telefono"), ("Teléfono", "telefono"), ("Celular", "telefono"),
    ("Mail", "mail"), ("E-mail", "mail"), ("Correo", "mail"), ("Delegación", "seccional"), ("Filial", "seccional"),
    ("Seccional", "seccional"), ("Fecha de afiliación", "fecha_afiliacion"), ("F. Ingreso", "fecha_afiliacion"),
    ("Alta", "fecha_afiliacion"), ("Fecha de nacimiento", "fecha_nacimiento"), ("Nacimiento", "fecha_nacimiento"),
])
def test_cada_sinonimo_se_reconoce(cabecera, campo):
    assert padron.detectar([cabecera]) == {0: campo}


def test_un_dni_no_es_una_identificacion_ni_el_cuit_de_la_empresa():
    assert padron.detectar(["DNI", "Documento", "CUIT Empleador", "CUIT empresa"]) == {}
    r = padron.leer(b"DNI;Nombre\n20123456;Ana\n", {})
    assert r["mapeo"]["faltan"] == ["cuil"] and r["total"] == 0 and r["filas"] == []
    assert any("DNI" in a for a in r["avisos"])


def test_las_columnas_en_cualquier_orden_y_lo_que_no_se_usa():
    c = _cu()
    r = padron.leer(f"Obs;Provincia;Email;Apellido y Nombre;Localidad;Nro CUIL\nx;Salta;a@b.com;Gómez, Ana;Salta;{c}\n".encode(), {})
    campos = {col["cabecera"]: col["campo"] for col in r["mapeo"]["columnas"]}
    assert campos == {"Obs": "", "Provincia": "provincia", "Email": "mail", "Apellido y Nombre": "nombre",
                      "Localidad": "localidad", "Nro CUIL": "cuil"}
    assert r["mapeo"]["sin_usar"] == ["Obs"] and r["mapeo"]["faltan"] == []
    assert r["filas"][0][2]["cuil"] == c and r["filas"][0][2]["nombre"] == "Gómez, Ana"
    assert r["mapeo"]["columnas"][0]["muestra"] == ["x"]


def test_apellido_aparte_se_une_al_nombre_y_apellido_y_nombre_no_se_duplica():
    r = padron.leer(f"CUIL;Apellido;Nombres\n{_cu()};Pérez;Juan\n".encode(), {})
    assert r["filas"][0][2]["nombre"] == "Pérez, Juan"
    r = padron.leer(f"CUIL;Apellido;Apellido y Nombre\n{_cu()};Pérez;Pérez, Juan\n".encode(), {})
    assert r["filas"][0][2]["nombre"] == "Pérez, Juan"
    assert r["mapeo"]["sin_usar"] == ["Apellido"]


def test_el_mapeo_corregido_manda_y_dos_columnas_al_mismo_campo_son_400():
    c = _cu()
    contenido = f"A;B;C\n{c};Ana;Salta\n".encode()
    r = padron.leer(contenido, {"mapeo": {"0": "cuil", "1": "nombre", "2": "provincia"}})
    assert r["mapeo"]["faltan"] == [] and r["filas"][0][2]["provincia"] == "Salta"
    # corregir una columna ya detectada: «Nombre» → provincia, y «Provincia» queda sin usar
    r = padron.leer(b"CUIL;Nombre;Provincia\n" + c.encode() + b";Ana;Salta\n", {"mapeo": {"1": "provincia", "2": ""}})
    assert r["mapeo"]["faltan"] == ["nombre"]
    # lo que ella nombra le saca el campo a la columna detectada
    r = padron.leer(b"CUIL;Nombre;Apodo\n" + c.encode() + b";Ana;Anita\n", {"mapeo": {"2": "nombre", "1": ""}})
    assert r["filas"][0][2]["nombre"] == "Anita"
    with pytest.raises(ErrorAsistida) as e:
        padron.leer(contenido, {"mapeo": {"0": "cuil", "1": "nombre", "2": "nombre"}})
    assert e.value.estado == 400 and "dos columnas" in e.value.mensaje.lower()
    for malo in ({"x": "cuil"}, {"0": "no_existe"}, {"9": "cuil"}, [1]):
        with pytest.raises(ErrorAsistida):
            padron.leer(contenido, {"mapeo": malo})


def test_fechas_con_hora_de_excel_y_opciones_invalidas():
    r = padron.leer(f"CUIL;Nombre;F. Ingreso\n{_cu()};Ana;2020-05-06 00:00:00\n".encode(), {})
    assert r["filas"][0][2]["fecha_afiliacion"] == "2020-05-06"
    for malo in ({"sin_seccional_desconocida": "si"}, {"total_declarado": "muchos"}, {"total_declarado": -1},
                 {"total_declarado": 1.5}, {"total_declarado": True}, []):
        with pytest.raises(ErrorAsistida) as e:
            padron.normalizar_opciones(malo)
        assert e.value.estado == 400
    assert padron.normalizar_opciones({"total_declarado": "1200"})["total_declarado"] == 1200
    assert padron.normalizar_opciones(None) == {"sin_seccional_desconocida": False, "total_declarado": None, "mapeo": {}}


def test_la_huella_cambia_con_el_mapeo_y_con_el_numero():
    c = b"a"
    base = padron.normalizar_opciones({})
    assert huella(c, base) == huella(c, padron.normalizar_opciones({}))
    assert huella(c, base) != huella(c, padron.normalizar_opciones({"mapeo": {"0": "cuil"}}))
    assert huella(c, base) != huella(c, padron.normalizar_opciones({"total_declarado": 10}))
    assert huella(c, padron.normalizar_opciones({"total_declarado": 10})) != huella(
        c, padron.normalizar_opciones({"total_declarado": 11}))


def test_describir_trae_mapeo_campos_y_las_dos_opciones():
    d = padron.describir()
    assert d["mapeo"] is True and d["insumo"] == "planilla_padron" and d["modelo_csv"]
    assert [c["clave"] for c in d["campos"] if c["obligatorio"]] == ["cuil", "nombre"]
    ops = {o["clave"]: o for o in d["opciones"]}
    assert ops["sin_seccional_desconocida"]["defecto"] is False
    assert ops["total_declarado"]["tipo"] == "numero" and ops["total_declarado"]["defecto"] is None
    assert d["tope_filas"] == 20000 and d["tope_bytes"] == 5 * 1024 * 1024


# =================================================================== HTTP

def _env(c, pid, que, contenido=None, texto=None, opciones=None, huella_=None, afuera=None):
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
    return c.post(f"{BASE}/p/{pid}/tarea/{P}/asistida/{que}", data=data, files=files)


def _ens(c, pid, contenido, **kw):
    r = _env(c, pid, "ensayo", contenido, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def _car(c, pid, contenido, afuera=None, opciones=None, ens=None):
    ens = ens or _ens(c, pid, contenido, opciones=opciones)
    return _env(c, pid, "carga", contenido, opciones=opciones, huella_=ens["huella"], afuera=afuera)


def _listo(eq, pid, sid, con_seccionales=("Seccional Rosario", "Seccional Córdoba")):
    """Deja resueltas EST-01 y PAD-01 (lo que PAD-02 necesita)."""
    with db.get_session() as s:
        for n in con_seccionales:
            s.add(db.Seccional(sindicato_id=sid, nombre=n))
        s.commit()
    for t in ("EST-01", "PAD-01"):
        r = eq.post(f"{BASE}/p/{pid}/tarea/{t}/decision", json={"tipo": "completada_a_mano", "motivo": "armado del test"})
        assert r.status_code == 200, r.text


def _mundo_listo(**kw):
    pid, sid, eq = _mundo()
    _listo(eq, pid, sid, **kw)
    return pid, sid, eq


def _trabajadores(sid):
    with db.get_session() as s:
        return {t.cuil: t for t in s.exec(select(db.Trabajador).where(db.Trabajador.sindicato_id == sid)).all()}


def _cuenta(cuil):
    with db.get_session() as s:
        return s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == cuil)).first()


def _por_linea(e):
    return {f["linea"]: f for f in e["filas"]}


def test_get_asistida_de_pad02_y_modelo():
    pid, sid, eq = _mundo()
    j = eq.get(f"{BASE}/p/{pid}/tarea/{P}/asistida").json()
    assert j["disponible"] is True and j["mapeo"] is True and j["campos"]
    r = eq.get(f"{BASE}/p/{pid}/tarea/{P}/asistida/modelo.csv")
    assert r.status_code == 200 and "modelo-padron" in r.headers["content-disposition"]
    assert _ens(eq, pid, r.content)["total"] == 2          # el modelo se lee a sí mismo


def test_ensayo_cuenta_motivos_y_no_escribe_nada():
    pid, sid, eq = _mundo_listo()
    rep = _cu()
    filas = [
        _fila(sec="Seccional Rosario"),                        # 2 válida
        _fila(sec="seccional   ROSARIO"),                       # 3 válida (sin mirar mayúsculas)
        _fila(sec="Seccional Bariloche"),                       # 4 dudosa: seccional que no existe
        _fila(),                                                # 5 dudosa: sin seccional
        _fila(cuil="20123456"),                                 # 6 rechazada: un DNI no es identificación
        _fila(cuil="20-33445566-1"),                            # 7 rechazada: verificador
        _fila(cuil=""),                                         # 8 rechazada: sin identificación
        _fila(nombre=""),                                       # 9 rechazada: sin nombre
        _fila(loc=""),                                          # 10 rechazada: sin localidad
        _fila(prov=""),                                         # 11 rechazada: sin provincia
        _fila(fecha="31/02/2020"),                              # 12 rechazada: fecha ilegible
        _fila(cuil=rep, sec="Seccional Rosario"),               # 13 válida
        _fila(cuil=rep, sec="Seccional Rosario"),               # 14 rechazada: repetida
    ]
    e = _ens(eq, pid, _csv(*filas))
    assert (e["total"], e["validas"], e["dudosas"], e["rechazadas"], e["ya_existen"]) == (13, 3, 2, 8, 0)
    assert e["a_escribir"] == 5 and e["huella"] and e["mapeo"]["faltan"] == [] and e["padron_actual"] == 0
    f = _por_linea(e)
    assert f[4]["estado"] == "dudosa" and "Bariloche" in f[4]["motivos"][0]
    assert f[5]["estado"] == "dudosa" and "Sin seccional" in f[5]["motivos"][0]
    assert "no tiene 11 números" in f[6]["motivos"][0] and "verificador" in f[7]["motivos"][0]
    assert "Falta la identificación" in f[8]["motivos"][0] and "Falta el nombre" in f[9]["motivos"][0]
    assert "localidad o la provincia" in f[10]["motivos"][0] and "localidad o la provincia" in f[11]["motivos"][0]
    assert "fechas" in f[12]["motivos"][0] and "Repetida" in f[14]["motivos"][0]
    assert 2 not in f and len(e["muestra"]) == 3 and e["filas_truncadas"] is False
    assert f[4]["resumen"]["seccional"] == "Seccional Bariloche" and f[6]["resumen"]["identificacion"] == "20123456"
    por_motivo = {(m["estado"], m["motivo"]): m for m in e["motivos"]}
    assert por_motivo[("rechazada", "Falta el nombre.")]["lineas"] == [9]
    assert sum(m["cantidad"] for m in e["motivos"] if m["estado"] == "rechazada") == 8
    assert _trabajadores(sid) == {} and _movs(pid, "asistida_carga") == [] and _estado_insumo(pid, "planilla_padron") is None


def test_ya_existe_con_y_sin_mail_o_fecha():
    pid, sid, eq = _mundo_listo()
    a, b, c = _cu(), _cu(), _cu()
    with db.get_session() as s:
        for x in (a, b, c):
            s.add(db.Trabajador(sindicato_id=sid, cuil=x, fecha_afiliacion="2010-01-01"))
            db.guardar_datos_personales(s, x, nombre="Nombre de siempre", mail_padron="viejo@x.org" if x == c else None)
        s.commit()
    e = _ens(eq, pid, _csv(_fila(cuil=a), _fila(cuil=b, mail="nuevo@x.org", nombre="OTRO NOMBRE"),
                           _fila(cuil=c, mail="viejo@x.org", fecha="2010-01-01")))
    assert (e["validas"], e["ya_existen"], e["a_escribir"]) == (0, 3, 1)
    acc = {f["linea"]: f["resumen"]["accion"] for f in e["filas"]}
    assert acc == {2: "sin_tocar", 3: "actualizar", 4: "sin_tocar"}
    r = _car(eq, pid, _csv(_fila(cuil=a), _fila(cuil=b, mail="nuevo@x.org", nombre="OTRO NOMBRE"), _fila(cuil=c)))
    assert r.status_code == 200, r.text
    assert r.json()["carga"]["actualizadas"] == 1
    assert _cuenta(b).mail_padron == "nuevo@x.org" and _cuenta(b).nombre == "Nombre de siempre"   # el nombre no se toca
    assert _cuenta(a).mail_padron in (None, "")


def test_cuenta_previa_por_otro_sindicato_entra_el_empadronamiento_y_no_se_tocan_sus_datos():
    pid, sid, eq = _mundo_listo()
    persona, ya = _cu(), _cu()
    otro = _sindicato()
    with db.get_session() as s:
        s.add(db.Trabajador(sindicato_id=otro, cuil=persona, registrado=True))
        c = db.guardar_datos_personales(s, persona, nombre="Su nombre real", telefono="111", mail="propio@x.org")
        c.clave_hash = auth.hashear_clave("x" * 12)
        s.add(db.Trabajador(sindicato_id=sid, cuil=ya, registrado=False))      # ya en ESTE padrón, sin registrarse acá
        db.guardar_datos_personales(s, ya, nombre="Otro")
        s.commit()
        s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == ya)).first().clave_hash = auth.hashear_clave("y" * 12)
        s.commit()
    csv = _csv(_fila(cuil=persona, nombre="Nombre del sindicato", sec="Seccional Rosario", mail="padron@x.org"),
               _fila(cuil=ya, mail="nuevo@x.org"))
    e = _ens(eq, pid, csv)
    f = _por_linea(e)
    assert f[2]["estado"] == "dudosa" and "otro sindicato" in f[2]["motivos"][0]
    assert f[3]["estado"] == "ya_existe"
    r = _car(eq, pid, csv, ens=e)
    assert r.status_code == 200, r.text
    assert persona in _trabajadores(sid)
    c = _cuenta(persona)
    assert (c.nombre, c.telefono, c.mail, c.mail_padron) == ("Su nombre real", "111", "propio@x.org", None) or c.mail_padron in (None, "")
    assert _cuenta(ya).mail_padron in (None, "")         # este padrón no responde por la cuenta: no se le pone mail


def test_opcion_sin_seccional_desconocida_total_declarado_y_comparacion():
    pid, sid, eq = _mundo_listo()
    csv = _csv(_fila(sec="Seccional Rosario"), _fila(sec="Seccional Rosario"), _fila(sec="Seccional Jujuy"))
    e = _ens(eq, pid, csv, opciones={"sin_seccional_desconocida": True, "total_declarado": 5})
    assert (e["validas"], e["dudosas"], e["rechazadas"]) == (2, 0, 1)
    assert "Jujuy" in e["filas"][0]["motivos"][0] and any("quedaría en 2" in a and "declaró 5" in a for a in e["avisos"])
    r = _car(eq, pid, csv, opciones={"sin_seccional_desconocida": True, "total_declarado": 5}, ens=e)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["carga"]["creadas"] == 2 and j["carga"]["rechazadas"] == 1
    assert j["carga"]["comparacion"] == {"declarado": 5, "cargado": 2, "diferencia": -3}
    mov = _movs(pid, "asistida_carga")[0]
    assert "Cargó 2 afiliados" in mov.texto and mov.cantidades["declarado"] == 5 and mov.cantidades["diferencia"] == -3
    # sin la opción, la de seccional desconocida entra como dudosa y se puede dejar afuera
    pid2, sid2, eq2 = _mundo_listo()
    e2 = _ens(eq2, pid2, csv)
    assert (e2["validas"], e2["dudosas"]) == (2, 1)
    j2 = _car(eq2, pid2, csv, afuera=[4, 2], ens=e2).json()               # la 2 no es dudosa: se ignora
    assert j2["carga"]["creadas"] == 2 and j2["carga"]["afuera"] == 1
    assert "comparacion" not in j2["carga"]


def test_carga_todo_o_nada_idempotencia_y_la_carga_no_confirma():
    pid, sid, eq = _mundo_listo()
    csv = _csv(_fila(sec="Seccional Rosario", mail="a@x.org", fecha="2020-01-02"), _fila(sec="Seccional Córdoba"))
    e = _ens(eq, pid, csv)
    assert _env(eq, pid, "carga", csv, huella_="otra").status_code == 409
    assert _env(eq, pid, "carga", csv).status_code == 409
    assert _trabajadores(sid) == {}
    r = _car(eq, pid, csv, ens=e)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["carga"]["creadas"] == 2 and j["ok"] is True and j["control"]["estado"] in ("completa", "observaciones")
    assert len(_trabajadores(sid)) == 2 and _estado_insumo(pid, "planilla_padron") == "recibido"
    assert len(_movs(pid, "asistida_carga")) == 1
    assert j["tarea"]["decisiones"] == [] or all(d["tipo"] != "confirmada" for d in j["tarea"]["decisiones"])
    assert _tarea(eq, pid, P)["estado"] != "confirmada"
    # la misma planilla otra vez: nada para cargar
    r2 = _car(eq, pid, csv)
    assert r2.status_code == 409 and "nada para cargar" in r2.json()["detail"].lower()
    assert len(_trabajadores(sid)) == 2 and len(_movs(pid, "asistida_carga")) == 1


def test_si_el_registro_del_movimiento_falla_no_queda_nada(monkeypatch):
    pid, sid, eq = _mundo_listo()
    csv = _csv(_fila(sec="Seccional Rosario"))
    e = _ens(eq, pid, csv)

    def falla(*a, **k):
        raise RuntimeError("se cayó")
    monkeypatch.setattr(db, "xsii_registrar_carga_asistida", falla)
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    c.cookies.update(eq.cookies)
    r = _env(c, pid, "carga", csv, huella_=e["huella"])
    assert r.status_code >= 500
    assert _trabajadores(sid) == {}


def test_el_movimiento_no_lleva_nombres_ni_identificaciones():
    pid, sid, eq = _mundo_listo()
    cuil, nombre = _cu(), "Zubiría Ñandú, Belisario"
    assert _car(eq, pid, _csv(_fila(cuil=cuil, nombre=nombre, sec="Seccional Rosario", mail="secreto@x.org"),
                              _fila(cuil="20-33445566-1")), opciones={"total_declarado": 9}).status_code == 200
    with db.get_session() as s:
        todo = json.dumps([(m.texto, m.cantidades) for m in s.exec(select(db.XsiiMovimiento).where(
            db.XsiiMovimiento.proyecto_id == pid)).all()], default=str)
    for sensible in (cuil, "Zubir", "Belisario", "secreto@x.org", "33445566"):
        assert sensible not in todo
    assert "declarado" in todo


def test_faltan_columnas_obligatorias_es_200_y_la_carga_400():
    pid, sid, eq = _mundo_listo()
    csv = b"DNI;Nombre\n20123456;Ana\n"
    e = _ens(eq, pid, csv)
    assert e["total"] == 0 and e["mapeo"]["faltan"] == ["cuil"] and e["huella"]
    r = _env(eq, pid, "carga", csv, huella_=e["huella"])
    assert r.status_code == 400 and "identificación" in r.json()["detail"].lower()
    # corregido por opción: la columna del DNI no es válida, pero el mapeo se acepta
    e2 = _ens(eq, pid, csv, opciones={"mapeo": {"0": "cuil"}})
    assert e2["mapeo"]["faltan"] == [] and e2["rechazadas"] == 1 and e2["huella"] != e["huella"]
    r = _env(eq, pid, "ensayo", csv, opciones={"mapeo": {"0": "cuil", "1": "cuil"}})
    assert r.status_code == 400


def test_topes_de_filas_y_de_tamano():
    pid, sid, eq = _mundo_listo()
    ok = "20123456780;Ana;;Rosario;Santa Fe;;\n" * 20000
    assert _env(eq, pid, "ensayo", (CAB + ok).encode()).status_code == 200
    r = _env(eq, pid, "ensayo", (CAB + ok + "20123456780;Ana;;Rosario;Santa Fe;;\n").encode())
    assert r.status_code == 400 and "20.000" in r.json()["detail"]
    r = _env(eq, pid, "ensayo", b"CUIL;Nombre\n" + b"x" * (5 * 1024 * 1024 + 10))
    assert r.status_code == 400 and "5 MB" in r.json()["detail"]
    assert _env(eq, pid, "ensayo", b"").status_code == 400


def test_pad02_bloqueada_es_409_en_la_carga_pero_el_ensayo_anda():
    pid, sid, eq = _mundo()
    csv = _csv(_fila())
    e = _ens(eq, pid, csv)
    r = _env(eq, pid, "carga", csv, huella_=e["huella"])
    assert r.status_code == 409 and "resuelta" in r.json()["detail"]
    assert _trabajadores(sid) == {}


def test_aislamiento_entre_sindicatos():
    pid, sid, eq = _mundo_listo()
    otro = _sindicato()
    c = _cu()
    with db.get_session() as s:
        s.add(db.Trabajador(sindicato_id=otro, cuil=c, fecha_afiliacion="2001-01-01"))
        db.guardar_datos_personales(s, c, nombre="De otro gremio", mail_padron="otro@x.org")
        s.commit()
    r = _car(eq, pid, _csv(_fila(cuil=c, nombre="Pisado", mail="mio@x.org", fecha="2020-02-02")))
    assert r.status_code == 200, r.text
    assert set(_trabajadores(sid)) == {c}                   # entró a ESTE padrón
    t = _trabajadores(otro)[c]
    assert t.fecha_afiliacion == "2001-01-01"               # el del otro gremio, intacto
    assert _cuenta(c).nombre == "Pisado"                    # sin clave todavía: rige la regla de la masiva (el padrón escribe)


def test_el_control_de_pad02_despues_de_la_carga():
    pid, sid, eq = _mundo_listo()
    assert _tarea(eq, pid, P)["control"]["estado"] == "incompleta"
    _car(eq, pid, _csv(_fila(sec="Seccional Rosario"), _fila()))
    ctrl = _tarea(eq, pid, P)["control"]
    assert ctrl["estado"] == "observaciones"                   # una persona quedó sin seccional
    assert {c["valor"] for c in ctrl["cifras"]} >= {2, 1}


def test_el_ejemplo_del_repo():
    pid, sid, eq = _mundo_listo(con_seccionales=("Sede Central", "Seccional Rosario", "Seccional Córdoba",
                                                 "Seccional Mendoza", "Seccional Tucumán", "Seccional Mar del Plata",
                                                 "Seccional Neuquén", "Seccional Salta"))
    e = _ens(eq, pid, EJEMPLO.read_bytes())
    assert e["total"] == 30 and e["mapeo"]["faltan"] == []
    assert e["mapeo"]["sin_usar"] == ["DNI"]
    assert (e["validas"], e["dudosas"], e["rechazadas"], e["ya_existen"]) == (25, 2, 3, 0)
    estados = {m["motivo"].split(":")[0] for m in e["motivos"]}
    assert any("Bariloche" in m["motivo"] for m in e["motivos"]) and any("Jujuy" in m["motivo"] for m in e["motivos"])
    assert "Repetida en la planilla" in " ".join(m["motivo"] for m in e["motivos"]) and estados


# ------------------------------------------------------------------ equivalencia con «Alta masiva»

def test_la_misma_lista_por_la_masiva_y_por_la_asistida_deja_lo_mismo():
    pid, sid, eq = _mundo_listo()
    sid_m = _sindicato()
    with db.get_session() as s:
        for n in ("Seccional Rosario", "Seccional Córdoba"):
            s.add(db.Seccional(sindicato_id=sid_m, nombre=n))
        usuario = db.UsuarioSindicato(sindicato_id=sid_m, cuil=_cu(), nombre="Admin", rol="super_admin") \
            if hasattr(db.UsuarioSindicato, "rol") else None
        s.commit()
    nuevos = [(_cu(), "Gómez Ana", "Avenida Colón", "650", "2 A", "Córdoba", "Córdoba", "351 555", "ana@x.org", "5000",
               "seccional córdoba", "2018-03-01", "1985-07-12"),
              (_cu("27"), "Ruiz Luis", "", "", "", "Rosario", "Santa Fe", "", "", "", "Seccional Rosario", "01/06/2020", ""),
              (_cu(), "Sin Seccional", "", "", "", "Salta", "Salta", "", "", "", "", "", ""),
              (_cu(), "Sin Localidad", "", "", "", "", "Salta", "", "", "", "", "", ""),
              ("20-33445566-1", "Mala", "", "", "", "Salta", "Salta", "", "", "", "", "", "")]
    # por la asistida: cabecera «como viene» con las trece columnas
    cab = "Nro CUIL;Apellido y Nombre;Calle;Altura;Piso;Localidad;Provincia;Tel;Email;CP;Delegación;Ingreso;Nacimiento\n"
    planilla = (cab + "\n".join(";".join(f) for f in nuevos) + "\n").encode()
    assert _car(eq, pid, planilla).status_code == 200
    # por la masiva: la ruta del panel, con el MISMO contenido separado por coma
    from padron_carga import filas_de_lista, procesar
    lista = "\n".join(",".join(f) for f in nuevos)
    with db.get_session() as s:
        procesar(s, sid_m, filas_de_lista(lista), None, ensayo=False)
        s.commit()

    def foto(sindicato):
        with db.get_session() as s:
            salida = {}
            for t in s.exec(select(db.Trabajador).where(db.Trabajador.sindicato_id == sindicato)).all():
                c = s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == t.cuil)).first()
                sec = s.get(db.Seccional, t.seccional_id).nombre if t.seccional_id else None
                salida[t.cuil] = (sec, t.fecha_afiliacion, c.nombre, c.calle, c.numero, c.piso_depto, c.localidad,
                                  c.provincia, c.codigo_postal, c.telefono, c.mail, c.mail_padron, c.fecha_nacimiento,
                                  c.precision_geo, c.direccion_texto)
            return salida
    # los CUIL se reparten distinto entre sindicatos: los de la asistida se comparan contra los de la masiva por CUIL
    assert foto(sid) == foto(sid_m) and len(foto(sid)) == 3
