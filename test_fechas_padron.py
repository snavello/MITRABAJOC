"""Las dos fechas del padrón (PLAN_LISTAS_VALIDACIONES.md, D4, bloque 2):
`Trabajador.fecha_afiliacion` (del empadronamiento, la carga solo el
sindicato) y `CuentaTrabajador.fecha_nacimiento` (de la persona).

Entran por cinco puertas -- alta manual, edición, alta masiva, perfil del
afiliado y registro -- y en las cinco una fecha ilegible se rechaza en la
puerta en vez de guardarse como texto. Hechos, no derivados: se guarda la
fecha, nunca la antigüedad ni la edad.

Correr con: python -m pytest test_fechas_padron.py -q
"""
import auth
import cuit
import db
import main
from db import CuentaTrabajador, Sindicato, Trabajador, UsuarioSindicato
from fastapi.testclient import TestClient
from sqlmodel import select

db.crear_tablas()

CLAVE_ADMIN = "admin-demo"
ADMIN = cuit.corregir("20191919190")
DOM = {"provincia": "Santa Fe", "localidad": "Rosario"}

with db.get_session() as s:
    sind = Sindicato(nombre="Gremio Fechas", slug="gremio-fechas", color_base="#101b2c")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=ADMIN, nombre="Admin Fechas",
                           clave_hash=auth.hashear_clave(CLAVE_ADMIN),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": ADMIN, "clave": CLAVE_ADMIN})


def _cuil(semilla: str) -> str:
    return cuit.corregir(semilla)


def _persona(cuil):
    with db.get_session() as s:
        return s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()


def _empadronamiento(cuil):
    with db.get_session() as s:
        return s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == SID)).first()


def _fila_padron(cuil):
    with db.get_session() as s:
        return next(f for f in db.padron_del_sindicato(s, SID) if f["cuil"] == cuil)


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    c.cookies.set("sind_elegido", str(SID))
    return c


# ------------------------------------------------------------ alta manual

def test_el_alta_guarda_las_dos_fechas_cada_una_en_su_dueno():
    cuil = _cuil("20100000010")
    r = admin.post("/admin/trabajador", data={
        "cuil": cuil, "nombre": "Con Fechas", **DOM,
        "fecha_afiliacion": "2019-05-02", "fecha_nacimiento": "15/07/1988"},
        follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"]
    assert _empadronamiento(cuil).fecha_afiliacion == "2019-05-02"
    assert _persona(cuil).fecha_nacimiento == "1988-07-15", "DD/MM/AAAA se guarda ISO"
    fila = _fila_padron(cuil)
    assert fila["fecha_afiliacion"] == "2019-05-02" and fila["fecha_nacimiento"] == "1988-07-15"


def test_una_fecha_ilegible_frena_el_alta_sin_escribir_nada():
    cuil = _cuil("20100000020")
    r = admin.post("/admin/trabajador", data={
        "cuil": cuil, "nombre": "Mal Fechado", **DOM, "fecha_afiliacion": "ayer"},
        follow_redirects=False)
    assert r.headers["location"] == "/admin?err=fecha#trabajadores"
    assert _empadronamiento(cuil) is None and _persona(cuil) is None


def test_sin_fechas_el_alta_sigue_igual():
    cuil = _cuil("20100000030")
    admin.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Sin Fechas", **DOM})
    assert _empadronamiento(cuil).fecha_afiliacion is None
    assert _persona(cuil).fecha_nacimiento is None


# ---------------------------------------------------------------- edición

def test_la_edicion_cambia_la_afiliacion_y_en_blanco_borra_el_nacimiento():
    cuil = _cuil("20100000040")
    admin.post("/admin/trabajador", data={
        "cuil": cuil, "nombre": "Editable", **DOM,
        "fecha_afiliacion": "2020-01-01", "fecha_nacimiento": "1990-02-03"})
    t = _empadronamiento(cuil)
    r = admin.post("/admin/trabajador", data={
        "id": t.id, "cuil": cuil, "nombre": "Editable", **DOM,
        "fecha_afiliacion": "2021-06-30", "fecha_nacimiento": ""}, follow_redirects=False)
    assert "err=" not in r.headers["location"]
    assert _empadronamiento(cuil).fecha_afiliacion == "2021-06-30"
    assert _persona(cuil).fecha_nacimiento is None, "el admin la vio y la dejó en blanco: borra"


def test_la_pantalla_del_admin_tiene_los_dos_campos_y_los_precarga():
    html = admin.get("/admin").text
    assert 'name="fecha_afiliacion" id="trab-fecha-afiliacion" type="date"' in html
    assert 'name="fecha_nacimiento" id="trab-fecha-nacimiento" type="date"' in html
    assert '"fecha_afiliacion":' in html and '"fecha_nacimiento":' in html, "el botón Editar las lleva"
    # Al mostrar, en dd/mm/aaaa (auditoría de diseño G4-35); se guarda ISO.
    assert "afiliado desde 30/06/2021" in html
    assert "fecha_afiliacion, fecha_nacimiento</p>" in html, "el orden del alta masiva las nombra"


# ------------------------------------------------------ cuenta de otro gremio

def test_una_cuenta_que_no_es_de_este_padron_recibe_la_afiliacion_pero_no_el_nacimiento():
    """La fecha de afiliación es del empadronamiento (siempre de este gremio);
    la de nacimiento es de la persona y sigue la regla de `padron_responde_por`."""
    cuil = _cuil("20100000050")
    with db.get_session() as s:
        db.asegurar_cuenta(s, cuil).clave_hash = auth.hashear_clave("clave-larga-123")
        s.commit()
    r = admin.post("/admin/trabajador", data={
        "cuil": cuil, "nombre": "Ajena", **DOM,
        "fecha_afiliacion": "2022-03-03", "fecha_nacimiento": "1980-01-01"}, follow_redirects=False)
    assert "aviso=datosajenos" in r.headers["location"]
    assert _empadronamiento(cuil).fecha_afiliacion == "2022-03-03"
    assert _persona(cuil).fecha_nacimiento is None


# ------------------------------------------------------------ alta masiva

def test_el_alta_masiva_lee_las_fechas_al_final_y_rechaza_las_ilegibles():
    nuevo = _cuil("20100000060")
    otro = _cuil("20100000070")
    existente = _cuil("20100000040")           # cargado más arriba
    lista = "\n".join([
        f"{nuevo}, Masivo Uno, , , , Rosario, Santa Fe, , , , , 2018-09-01, 01/12/1992",
        f"{otro}, Masivo Dos, , , , Rosario, Santa Fe, , , , , de ayer",
        f"{existente}, Editable, , , , Rosario, Santa Fe, , , , , 2017-04-04",
    ])
    r = admin.post("/admin/trabajador/masivo", data={"lista": lista}, follow_redirects=False)
    destino = r.headers["location"]
    assert "altas=1" in destino and "omitidas=1" in destino and "fechasactualizadas=1" in destino, destino
    assert _empadronamiento(nuevo).fecha_afiliacion == "2018-09-01"
    assert _persona(nuevo).fecha_nacimiento == "1992-12-01"
    assert _empadronamiento(otro) is None, "una fecha ilegible deja la línea afuera"
    assert _empadronamiento(existente).fecha_afiliacion == "2017-04-04"
    html = admin.get("/admin" + destino[len("/admin"):].split("#")[0]).text
    assert "la fecha de afiliación de su línea" in html


def test_una_planilla_vieja_sin_las_fechas_entra_igual():
    cuil = _cuil("20100000080")
    r = admin.post("/admin/trabajador/masivo",
                   data={"lista": f"{cuil}, Planilla Vieja, , , , Rosario, Santa Fe"},
                   follow_redirects=False)
    assert "altas=1" in r.headers["location"]
    assert _empadronamiento(cuil).fecha_afiliacion is None


# ----------------------------------------------------------------- perfil

def test_el_perfil_guarda_y_borra_la_fecha_de_nacimiento():
    cuil = _cuil("20100000090")
    admin.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Perfil", **DOM})
    with db.get_session() as s:
        db.asegurar_cuenta(s, cuil).clave_hash = auth.hashear_clave("clave-larga-123")
        s.commit()
    c = _sesion_trabajador(cuil)
    base = {"nombre": "Perfil", **DOM}
    r = c.post("/api/perfil", data={**base, "fecha_nacimiento": "1995-01-30"})
    assert r.status_code == 200, r.text
    assert db.perfil_trabajador(cuil, SID)["fecha_nacimiento"] == "1995-01-30"
    r = c.post("/api/perfil", data={**base, "fecha_nacimiento": "30-01-1995"})
    assert r.status_code == 400 and "fecha" in r.json()["detail"].lower()
    assert db.perfil_trabajador(cuil, SID)["fecha_nacimiento"] == "1995-01-30", "el 400 no escribe"
    r = c.post("/api/perfil", data={**base, "fecha_nacimiento": ""})
    assert r.status_code == 200
    assert db.perfil_trabajador(cuil, SID)["fecha_nacimiento"] is None, "en el perfil, en blanco borra"


# --------------------------------------------------------------- registro

def test_el_registro_guarda_la_fecha_y_en_blanco_no_toca_la_del_padron():
    cuil = _cuil("20100000100")
    admin.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Registro", **DOM,
                                          "fecha_nacimiento": "1970-05-05"})
    r = TestClient(main.app).post("/trabajador/registro", data={
        "cuil": cuil, "clave": "clave-larga-123", "nombre": "Registro", **DOM,
        "fecha_nacimiento": ""}, follow_redirects=False)
    assert r.status_code == 303 and "error=" not in r.headers["location"]
    assert _persona(cuil).fecha_nacimiento == "1970-05-05", "en blanco = no lo completé"

    cuil2 = _cuil("20100000110")
    admin.post("/admin/trabajador", data={"cuil": cuil2, "nombre": "Registro Dos", **DOM})
    r = TestClient(main.app).post("/trabajador/registro", data={
        "cuil": cuil2, "clave": "clave-larga-123", "nombre": "Registro Dos", **DOM,
        "fecha_nacimiento": "31/02/1990"}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=fecha"
    assert not _persona(cuil2).clave_hash, "la cuenta no se creó"
    r = TestClient(main.app).post("/trabajador/registro", data={
        "cuil": cuil2, "clave": "clave-larga-123", "nombre": "Registro Dos", **DOM,
        "fecha_nacimiento": "1990-02-28"}, follow_redirects=False)
    assert "error=" not in r.headers["location"]
    assert _persona(cuil2).fecha_nacimiento == "1990-02-28"


def test_la_pantalla_de_registro_y_el_perfil_tienen_el_campo():
    html = TestClient(main.app).get("/ingresar").text
    assert 'name="fecha_nacimiento" type="date"' in html
    assert "Fecha de nacimiento <span class=\"opc\">(opcional)</span>" in html
    portada = open("templates/portada.html", encoding="utf-8").read()
    assert "fecha_nacimiento: document.getElementById('pf-fecha-nacimiento')" in portada
    # Y la portada real la precarga desde la persona.
    cuil = _cuil("20100000090")
    html = _sesion_trabajador(cuil).get("/app/inicio").text
    assert 'id="pf-fecha-nacimiento" value=""' in html
    with db.get_session() as s:
        db.guardar_datos_personales(s, cuil, fecha_nacimiento="1995-01-30"); s.commit()
    html = _sesion_trabajador(cuil).get("/app/inicio").text
    assert 'id="pf-fecha-nacimiento" value="1995-01-30"' in html
