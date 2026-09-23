"""Los datos personales de un afiliado tienen UN SOLO dueño: la persona.

Nombre, domicilio, teléfono y mail viven en `CuentaTrabajador` (una fila por
CUIL) y no en `Trabajador` (una fila por sindicato). El cambio es del
2026-09-22 y salió de un problema concreto que Sd encontró en Pruebas: el
mismo CUIL con dos nombres y dos direcciones, y nada que dijera cuál era la
buena.

**Cómo se llegó a eso**, que es lo que este archivo cuida que no vuelva a
pasar: las cuatro puertas por las que entran esos datos no escribían igual.
`/trabajador/registro` copiaba el domicilio a TODOS los empadronamientos del
CUIL y `/api/perfil` lo escribía solo en el del sindicato activo. La misma
persona, editando en dos pantallas, dejaba dos resultados distintos. Y
además `CuentaTrabajador.nombre` existía, no lo leía nadie y solo lo llenaba
el cargador de datos sintéticos: una tercera copia, siempre vieja.

Lo que se prueba acá:

1. Que el empadronamiento no tenga ninguna copia (eso está en
   `test_seccional_geo.py`, junto al bloque compartido con Seccional).
2. Que lo que escribe el admin lo vea el afiliado, y al revés.
3. Que un CUIL en dos sindicatos tenga UN domicilio, lo edite quien lo edite.
4. Que el alta del padrón cree la fila de la persona SIN clave -- que es lo
   que permite que "un solo lugar" valga también para quien todavía no se
   registró, sin abrir una puerta para entrar.
5. Que la pantalla de primer registro pida los MISMOS campos que el perfil.

Correr con: .venv/Scripts/python.exe -m pytest test_datos_personales.py -q
"""
import inspect

import auth
import db
import main
from db import Sindicato, UsuarioSindicato, Trabajador, CuentaTrabajador
from fastapi.testclient import TestClient
from sqlmodel import select

db.crear_tablas()

CLAVE_ADMIN = "admin-demo"
CUIL_DOBLE = "27222222224"      # empadronado en los DOS sindicatos

with db.get_session() as s:
    uno = Sindicato(nombre="Gremio Uno", slug="gremio-uno", color_base="#101b2c")
    dos = Sindicato(nombre="Gremio Dos", slug="gremio-dos", color_base="#0d2027")
    s.add(uno); s.add(dos); s.commit(); s.refresh(uno); s.refresh(dos)
    SID_UNO, SID_DOS = uno.id, dos.id
    for sid, usuario in ((SID_UNO, "20111111110"), (SID_DOS, "20222222220")):
        s.add(UsuarioSindicato(sindicato_id=sid, usuario=usuario, nombre="Admin",
                               clave_hash=auth.hashear_clave(CLAVE_ADMIN),
                               debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

admin_uno = TestClient(main.app)
admin_uno.post("/admin/login", data={"usuario": "20111111110", "clave": CLAVE_ADMIN})
admin_dos = TestClient(main.app)
admin_dos.post("/admin/login", data={"usuario": "20222222220", "clave": CLAVE_ADMIN})


def _persona(cuil):
    with db.get_session() as s:
        return s.exec(select(CuentaTrabajador).where(
            CuentaTrabajador.cuil == cuil)).first()


def _sesion_trabajador(cuil, sindicato_id):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR,
                  auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    c.cookies.set("sind_elegido", str(sindicato_id))
    return c


# ------------------------------------------- el alta crea a la persona

def test_el_alta_del_padron_crea_la_persona_sin_clave():
    """La fila existe desde que el CUIL entra al padrón, no desde que se
    registra: si no, el admin necesitaría un segundo lugar donde escribir y
    volveríamos a tener dos copias. Y sin clave NO se puede entrar --
    `auth.verificar_clave` devuelve False con un hash vacío, así que estas
    filas no son cuentas abiertas."""
    admin_uno.post("/admin/trabajador", data={
        "cuil": "20333333336", "nombre": "Recién Cargado",
        "provincia": "Santa Fe", "localidad": "Rosario"})
    p = _persona("20333333336")
    assert p is not None, "el alta tiene que dejar la fila de la persona"
    assert p.nombre == "Recién Cargado"
    assert p.clave_hash == "", "todavía no eligió clave"
    assert not auth.verificar_clave("", p.clave_hash), "una fila sin clave no deja entrar"
    assert _persona("20333333336").localidad == "Rosario"
    print("OK  test_el_alta_del_padron_crea_la_persona_sin_clave")


# ------------------------------- lo que escribe uno lo ve el otro

def test_lo_que_corrige_el_admin_lo_ve_el_afiliado():
    admin_uno.post("/admin/trabajador", data={
        "cuil": "20444444440", "nombre": "Pedro Gómez",
        "provincia": "Córdoba", "localidad": "Córdoba",
        "calle": "Colón", "numero": "1200", "telefono": "3511234567"})
    perfil = db.perfil_trabajador("20444444440", SID_UNO)
    assert perfil["nombre"] == "Pedro Gómez"
    assert perfil["calle"] == "Colón" and perfil["numero"] == "1200"
    assert perfil["telefono"] == "3511234567"
    print("OK  test_lo_que_corrige_el_admin_lo_ve_el_afiliado")


def test_lo_que_edita_el_afiliado_lo_ve_el_admin():
    c = _sesion_trabajador("20444444440", SID_UNO)
    r = c.post("/api/perfil", data={
        "nombre": "Pedro Gómez Ruiz", "provincia": "Santa Fe", "localidad": "Rosario",
        "calle": "San Martín", "numero": "850", "telefono": "3415550000",
        "mail": "pedro@example.com"})
    assert r.status_code == 200, r.text
    p = _persona("20444444440")
    assert p.nombre == "Pedro Gómez Ruiz"
    assert (p.provincia, p.localidad) == ("Santa Fe", "Rosario")
    assert p.mail == "pedro@example.com"
    print("OK  test_lo_que_edita_el_afiliado_lo_ve_el_admin")


# --------------------------------- una persona en dos gremios, un domicilio

def test_el_mismo_cuil_en_dos_gremios_tiene_un_solo_domicilio():
    """El defecto que originó todo esto. Antes: el afiliado editaba su perfil
    con el Gremio Uno activo y el Gremio Dos seguía viendo la dirección
    vieja, para siempre y sin que nada lo indicara."""
    for cliente in (admin_uno, admin_dos):
        cliente.post("/admin/trabajador", data={
            "cuil": CUIL_DOBLE, "nombre": "Ana Multi",
            "provincia": "Buenos Aires", "localidad": "La Plata"})
    with db.get_session() as s:
        empadronamientos = s.exec(select(Trabajador).where(
            Trabajador.cuil == CUIL_DOBLE)).all()
    assert len(empadronamientos) == 2, "el CUIL tiene que estar en los dos gremios"

    # El afiliado corrige su domicilio desde la app, con el Gremio Uno activo.
    c = _sesion_trabajador(CUIL_DOBLE, SID_UNO)
    r = c.post("/api/perfil", data={
        "nombre": "Ana Multi", "provincia": "Mendoza", "localidad": "Godoy Cruz"})
    assert r.status_code == 200, r.text

    # Y los DOS gremios leen lo mismo, porque es el mismo renglón.
    for sid in (SID_UNO, SID_DOS):
        perfil = db.perfil_trabajador(CUIL_DOBLE, sid)
        assert (perfil["provincia"], perfil["localidad"]) == ("Mendoza", "Godoy Cruz"), sid
    print("OK  test_el_mismo_cuil_en_dos_gremios_tiene_un_solo_domicilio")


def test_el_padron_del_admin_muestra_los_datos_de_la_persona():
    """El listado de Trabajadores hace el JOIN en la consulta: si alguna vez
    volviera a leer una columna del empadronamiento, la pantalla mostraría un
    dato que ya no existe -- o peor, uno viejo."""
    with db.get_session() as s:
        filas = {f["cuil"]: f for f in db.padron_del_sindicato(s, SID_DOS)}
    fila = filas[CUIL_DOBLE]
    assert fila["nombre"] == "Ana Multi"
    assert fila["localidad"] == "Godoy Cruz", "el Gremio Dos ve la corrección del afiliado"
    print("OK  test_el_padron_del_admin_muestra_los_datos_de_la_persona")


# -------------------------------- el registro pide lo mismo que el perfil

def test_el_registro_pide_los_mismos_campos_que_el_perfil():
    """Pedido de Sd (2026-09-22): "en la pantalla de primer registro debe
    pedir los mismos datos".

    Se compara contra la FIRMA de las dos rutas y no contra el HTML: es el
    contrato de verdad, y un campo que el formulario muestre pero el servidor
    no reciba se pierde igual sin avisar.

    Las diferencias que quedan son las dos que tienen que quedar: el registro
    pide además el CUIL y la clave (es un alta), y el perfil recibe además el
    globo del mapa, que a propósito no está en el registro -- ubicar un punto
    es una tarea de escritorio y el alta es el momento de menos paciencia de
    toda la app."""
    del_registro = set(inspect.signature(main.trabajador_registro).parameters)
    del_perfil = set(inspect.signature(main.api_actualizar_perfil).parameters)
    solo_del_alta = {"cuil", "clave"}
    solo_del_mapa = {"latitud", "longitud", "precision_geo"}
    assert (del_registro - solo_del_alta) == (del_perfil - solo_del_mapa), (
        "sobran en el registro: %s / faltan en el registro: %s" % (
            sorted((del_registro - solo_del_alta) - (del_perfil - solo_del_mapa)),
            sorted((del_perfil - solo_del_mapa) - (del_registro - solo_del_alta))))
    print("OK  test_el_registro_pide_los_mismos_campos_que_el_perfil")


def test_la_pantalla_de_registro_muestra_esos_campos():
    """Y que estén de verdad en el formulario, con la misma marca de
    obligatorio y opcional que en el perfil."""
    html = TestClient(main.app).get("/ingresar").text
    for campo in ("nombre", "provincia", "localidad", "calle", "numero",
                  "piso_depto", "codigo_postal", "telefono", "mail"):
        assert f'name="{campo}"' in html, campo
    assert 'name="nombre" required' in html, "el nombre es obligatorio, igual que en el perfil"
    for campo in ("Teléfono", "Mail"):
        assert f'{campo} <span class="opc">(opcional)</span>' in html, campo
    print("OK  test_la_pantalla_de_registro_muestra_esos_campos")


def test_el_registro_no_borra_lo_que_el_padron_ya_tenia():
    """El registro no puede mostrar lo que el padrón sabe de un CUIL (lo
    averiguaría cualquiera tipeando CUILes ajenos), así que un campo vacío
    significa "no lo completé" y no "no tengo". En el perfil es al revés: ahí
    se ve lo cargado y borrarlo es una decisión."""
    admin_uno.post("/admin/trabajador", data={
        "cuil": "20555555553", "nombre": "Con Telefono",
        "provincia": "Santa Fe", "localidad": "Rosario",
        "telefono": "3411112222", "mail": "viejo@example.com"})
    r = TestClient(main.app).post("/trabajador/registro", data={
        "cuil": "20555555553", "clave": "secreta", "nombre": "Con Telefono",
        "provincia": "Santa Fe", "localidad": "Rosario",
        "telefono": "", "mail": ""}, follow_redirects=False)
    assert r.status_code == 303 and "error=" not in r.headers["location"]
    p = _persona("20555555553")
    assert p.telefono == "3411112222", "el teléfono del padrón no se borró"
    assert p.mail == "viejo@example.com"
    assert p.clave_hash, "y la clave sí quedó puesta"
    print("OK  test_el_registro_no_borra_lo_que_el_padron_ya_tenia")


if __name__ == "__main__":
    test_el_alta_del_padron_crea_la_persona_sin_clave()
    test_lo_que_corrige_el_admin_lo_ve_el_afiliado()
    test_lo_que_edita_el_afiliado_lo_ve_el_admin()
    test_el_mismo_cuil_en_dos_gremios_tiene_un_solo_domicilio()
    test_el_padron_del_admin_muestra_los_datos_de_la_persona()
    test_el_registro_pide_los_mismos_campos_que_el_perfil()
    test_la_pantalla_de_registro_muestra_esos_campos()
    test_el_registro_no_borra_lo_que_el_padron_ya_tenia()
    print("\nTodo OK — los datos personales tienen un solo dueño.")
