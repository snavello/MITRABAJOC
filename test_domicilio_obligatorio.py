"""Provincia y localidad son obligatorias en el domicilio del afiliado.

Decisión de Sd el 2026-09-13, con la pregunta planteada así: ¿conviene exigir
la georreferenciación exacta, que hace más difícil el alta a quien no está
acostumbrado, o alcanza con provincia y localidad? La respuesta fue distinta
para cada actor, y de eso se trata este archivo:

- **Al afiliado se le piden DOS campos**: provincia y localidad
  (`geo.OBLIGATORIOS_AFILIADO`). Sin eso el sindicato no puede agrupar a su
  gente ni dirigir nada por zona; con eso alcanza. La calle, la altura, el CP
  y el globo en el mapa quedan OPCIONALES y marcados como tales en pantalla.
- **A la seccional se le exige la dirección completa y el globo en la
  puerta** -- eso se prueba en `test_seccional_geo.py`, no acá.

Y se prueba en las CUATRO puertas por las que entra un domicilio de afiliado,
porque una sola que no valide vuelve inútil a las otras tres: el alta manual
del admin, el alta masiva, el registro del propio afiliado y su perfil.

Lo que este archivo cuida especialmente:

- Que el alta masiva **no rechace el lote entero** por unas líneas incompletas
  y que diga cuántas quedaron afuera (antes las descartaba en silencio: el
  sindicato creía que había cargado 500 y tenía 497).
- Que el registro guarde el domicilio como **un bloque** (reemplaza al
  anterior o no lo toca, nunca lo fusiona campo por campo: así no aparece una
  calle de Rafaela con la localidad de La Plata).
- Que el registro **no geocodifique**: una llamada a un servicio ajeno en el
  camino del alta es el peor lugar para esperar ocho segundos.

Correr con: .venv/bin/python -m pytest test_domicilio_obligatorio.py -q
"""
import auth
import db
import geo
import main
from db import Sindicato, UsuarioSindicato, CuentaTrabajador, Trabajador, Seccional
from fastapi.testclient import TestClient
from sqlmodel import select

db.crear_tablas()

CLAVE_ADMIN = "uom-demo"
CLAVE_TRAB = "trab-demo"

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Domicilio", slug="uom-dom", color_base="#0f1b2d")
    otro = Sindicato(nombre="Fega Domicilio", slug="fega-dom", color_base="#0d2027")
    s.add(uom); s.add(otro); s.commit(); s.refresh(uom); s.refresh(otro)
    SID, SID_OTRO = uom.id, otro.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                           clave_hash=auth.hashear_clave(CLAVE_ADMIN),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(Seccional(sindicato_id=SID, nombre="Rosario", ve_todas=True))
    # Padrón de arranque. El que se va a registrar SIN domicilio cargado, y
    # otro que YA lo tiene puesto por el sindicato (para probar que no se pisa).
    s.add(Trabajador(sindicato_id=SID, cuil="20444444442", nombre="Sin Domicilio"))
    s.add(Trabajador(sindicato_id=SID, cuil="20555555553", nombre="Con Domicilio",
                     **geo.campos_para_guardar(
                         {"calle": "Mitre", "numero": "100", "localidad": "Rafaela",
                          "provincia": "Santa Fe"}, precision="sin_geo")))
    # El MISMO CUIL en dos sindicatos (pluriempleo): el registro completa los
    # dos empadronamientos, no solo uno.
    s.add(Trabajador(sindicato_id=SID_OTRO, cuil="20444444442", nombre="Sin Domicilio"))
    s.add(CuentaTrabajador(cuil="20666666664", clave_hash=auth.hashear_clave(CLAVE_TRAB),
                           nombre="Ya Registrado"))
    s.add(Trabajador(sindicato_id=SID, cuil="20666666664", nombre="Ya Registrado",
                     registrado=True))
    s.commit()

admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": "20111111110", "clave": CLAVE_ADMIN})


def _trab(cuil, sindicato_id=None):
    with db.get_session() as s:
        return s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == (sindicato_id or SID),
            Trabajador.cuil == cuil)).first()


def _sesion(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


# --------------------------------------------------- la regla, sin la app

def test_la_regla_se_escribe_una_sola_vez():
    """Las cuatro rutas preguntan lo mismo a la misma función. Si cada una
    decidiera por su cuenta, el mismo domicilio pasaría o no según por dónde
    se cargó -- y eso es exactamente lo que el bloque compartido de campos
    vino a corregir."""
    assert geo.faltan_campos({"provincia": "Santa Fe", "localidad": "Rosario"}) == []
    assert geo.faltan_campos({"provincia": "Santa Fe"}) == ["localidad"]
    assert geo.faltan_campos({"provincia": "   ", "localidad": "  "}) == ["provincia", "localidad"]
    # Lo que se le exige al afiliado es un SUBCONJUNTO de lo que se le exige a
    # la seccional: al revés sería más fácil cargar una delegación que una
    # persona.
    assert set(geo.OBLIGATORIOS_AFILIADO) <= set(geo.OBLIGATORIOS_SECCIONAL)
    print("OK  test_la_regla_se_escribe_una_sola_vez")


# ------------------------------------------------- 1. alta manual del admin

def test_el_alta_sin_provincia_ni_localidad_no_entra():
    r = admin.post("/admin/trabajador", data={"cuil": "27111111114", "nombre": "Sin Zona"},
                    follow_redirects=False)
    assert r.status_code == 303
    destino = r.headers["location"]
    assert "err=domicilio" in destino, destino
    # El mensaje NOMBRA lo que falta: "revisá los datos" obliga a adivinar.
    assert "provincia" in destino and "localidad" in destino, destino
    assert _trab("27111111114") is None, "no se creó la fila a medias"
    print("OK  test_el_alta_sin_provincia_ni_localidad_no_entra")


def test_el_alta_con_provincia_y_localidad_entra_sin_nada_mas():
    """Lo que hace que la decisión sea la decisión: el domicilio fino NO es
    obligatorio. Sin esto, el admin que carga mil personas inventa alturas."""
    r = admin.post("/admin/trabajador", data={
        "cuil": "27222222224", "nombre": "Con Zona",
        "provincia": "Santa Fe", "localidad": "Rosario"}, follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"]
    t = _trab("27222222224")
    assert t is not None
    assert (t.provincia, t.localidad) == ("Santa Fe", "Rosario")
    assert t.calle == "" and t.numero == ""
    assert t.precision_geo == "sin_geo", "nadie se geocodifica en el alta"
    assert t.direccion_texto == "Rosario, Santa Fe"
    print("OK  test_el_alta_con_provincia_y_localidad_entra_sin_nada_mas")


def test_editar_no_puede_vaciar_la_provincia():
    """El borde que se olvida: la obligatoriedad también tiene que valer en la
    edición, o el dato se carga una vez y se borra en el segundo guardado."""
    t = _trab("27222222224")
    r = admin.post("/admin/trabajador", data={
        "id": str(t.id), "cuil": t.cuil, "nombre": t.nombre,
        "provincia": "", "localidad": "Rosario"}, follow_redirects=False)
    assert "err=domicilio" in r.headers["location"]
    assert _trab("27222222224").provincia == "Santa Fe", "la fila quedó como estaba"
    print("OK  test_editar_no_puede_vaciar_la_provincia")


# ------------------------------------------------------- 2. alta masiva

def test_la_masiva_carga_las_lineas_completas_y_avisa_de_las_otras():
    lista = "\n".join([
        "20777777771, Completo Uno, San Martín, 850, , Rosario, Santa Fe",
        "20777777772, Sin Provincia, Mitre, 100, , Rafaela, ",
        "20777777773, Completo Dos, , , , Córdoba, Córdoba",
        "20777777774, Sin Localidad, , , , , Santa Fe",
    ])
    r = admin.post("/admin/trabajador/masivo", data={"lista": lista}, follow_redirects=False)
    destino = r.headers["location"]
    # Las dos completas entran; las otras dos quedan afuera SIN tumbar el lote.
    assert "altas=2" in destino, destino
    assert "omitidas=2" in destino, destino
    # Y se ve un ejemplo, que en la práctica es lo que revela el patrón (casi
    # siempre falta la misma columna en todas).
    assert "muestra=" in destino, destino
    assert _trab("20777777771") is not None and _trab("20777777773") is not None
    assert _trab("20777777772") is None and _trab("20777777774") is None
    print("OK  test_la_masiva_carga_las_lineas_completas_y_avisa_de_las_otras")


def test_la_masiva_deja_las_filas_listas_para_georreferenciar_despues():
    """Sin localidad, "Georreferenciar pendientes" no puede hacer nada: exigir
    provincia y localidad en el alta es lo que hace que ese proceso sirva."""
    t = _trab("20777777771")
    assert t.precision_geo == "sin_geo" and t.localidad == "Rosario"
    pendientes = db.trabajadores_sin_geo(SID, None)
    assert any(tid == t.id for tid, _ in pendientes)
    print("OK  test_la_masiva_deja_las_filas_listas_para_georreferenciar_despues")


# --------------------------------------------------- 3. registro del afiliado

def test_el_registro_sin_provincia_no_crea_la_cuenta():
    r = TestClient(main.app).post("/trabajador/registro", data={
        "cuil": "20444444442", "clave": "secreta", "provincia": "", "localidad": "Rosario"},
        follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=domicilio", r.headers["location"]
    with db.get_session() as s:
        assert not s.exec(select(CuentaTrabajador).where(
            CuentaTrabajador.cuil == "20444444442")).first(), \
            "la cuenta no puede quedar creada a medias"
    print("OK  test_el_registro_sin_provincia_no_crea_la_cuenta")


def test_el_registro_guarda_el_domicilio_en_todos_sus_empadronamientos():
    """Una persona, un domicilio. `Trabajador` es por sindicato (pluriempleo),
    así que el domicilio que carga en el alta tiene que quedar en los dos."""
    r = TestClient(main.app).post("/trabajador/registro", data={
        "cuil": "20444444442", "clave": "secreta", "provincia": "Córdoba",
        "localidad": "Córdoba", "calle": "Boulevard San Juan", "numero": "430"},
        follow_redirects=False)
    assert r.status_code == 303 and "error=" not in r.headers["location"]
    for sid in (SID, SID_OTRO):
        t = _trab("20444444442", sid)
        assert t.registrado is True
        assert (t.provincia, t.localidad) == ("Córdoba", "Córdoba")
        assert t.calle == "Boulevard San Juan" and t.numero == "430"
        # El texto lo arma el servidor, igual que en las otras tres puertas.
        assert t.direccion_texto == "Boulevard San Juan 430, Córdoba"
        # Y NO se geocodifica: el alta no espera a un servicio ajeno.
        assert t.precision_geo == "sin_geo" and t.latitud is None
    print("OK  test_el_registro_guarda_el_domicilio_en_todos_sus_empadronamientos")


def test_el_registro_reemplaza_el_domicilio_entero_y_no_lo_fusiona():
    """El padrón tenía "Mitre 100, Rafaela, Santa Fe" y la persona declara que
    vive en La Plata. Lo que NO puede quedar es "Mitre 100, La Plata": una
    calle de un pueblo con la localidad de otro es una dirección que no existe
    en ninguna de las dos fuentes. Un domicilio es UN dato, no seis.

    Y manda la persona: es su dirección y la está declarando ahora. El perfil
    ya se lo permite un minuto después, así que pedirle dos campos
    obligatorios para descartarlos sería un formulario que miente."""
    r = TestClient(main.app).post("/trabajador/registro", data={
        "cuil": "20555555553", "clave": "secreta", "provincia": "Buenos Aires",
        "localidad": "La Plata"}, follow_redirects=False)
    assert r.status_code == 303 and "error=" not in r.headers["location"]
    t = _trab("20555555553")
    assert t.registrado is True
    assert (t.provincia, t.localidad) == ("Buenos Aires", "La Plata")
    assert t.calle == "" and t.numero == "", "no quedó la calle del domicilio viejo"
    assert t.direccion_texto == "La Plata, Buenos Aires"
    print("OK  test_el_registro_reemplaza_el_domicilio_entero_y_no_lo_fusiona")


def test_un_domicilio_identico_no_toca_la_fila():
    """El borde que justifica comparar antes de escribir: si el afiliado tipea
    exactamente lo que el padrón ya tenía, reescribirlo le borraría las
    coordenadas (el alta escribe `sin_geo`) y lo mandaría de nuevo a la cola de
    georreferenciación estando ya ubicado."""
    with db.get_session() as s:
        t = s.exec(select(Trabajador).where(Trabajador.sindicato_id == SID,
                                            Trabajador.cuil == "20777777771")).first()
        for campo, valor in geo.campos_para_guardar(
                {"calle": "San Martín", "numero": "850", "localidad": "Rosario",
                 "provincia": "Santa Fe"},
                precision="exacta", lat=-32.947338, lon=-60.636893).items():
            setattr(t, campo, valor)
        s.add(t); s.commit()
    TestClient(main.app).post("/trabajador/registro", data={
        "cuil": "20777777771", "clave": "secreta", "provincia": "Santa Fe",
        "localidad": "Rosario", "calle": "San Martín", "numero": "850"},
        follow_redirects=False)
    t = _trab("20777777771")
    assert t.precision_geo == "exacta", "la ubicación que ya tenía no se perdió"
    assert t.latitud is not None
    print("OK  test_un_domicilio_identico_no_toca_la_fila")


# ------------------------------------------------------ 4. perfil del afiliado

def test_el_perfil_no_se_guarda_sin_localidad():
    r = _sesion("20666666664").post("/api/perfil", data={
        "nombre": "Ya Registrado", "provincia": "Santa Fe", "localidad": ""})
    assert r.status_code == 400
    # En singular y bien escrito: un "Falta localidad: las necesita" se lee
    # como un error del sistema y no como algo que la persona puede corregir.
    assert r.json()["detail"] == ("Falta la localidad: tu sindicato la necesita "
                                  "para agruparte por zona."), r.json()
    print("OK  test_el_perfil_no_se_guarda_sin_localidad")


def test_el_perfil_se_guarda_con_las_dos_y_nada_mas():
    c = _sesion("20666666664")
    r = c.post("/api/perfil", data={"nombre": "Ya Registrado", "provincia": "Santa Fe",
                                    "localidad": "Rosario"})
    assert r.status_code == 200, r.text
    t = _trab("20666666664")
    assert (t.provincia, t.localidad) == ("Santa Fe", "Rosario")
    print("OK  test_el_perfil_se_guarda_con_las_dos_y_nada_mas")


def test_el_formulario_marca_lo_obligatorio_y_lo_opcional():
    """La regla del servidor tiene que estar DICHA en la pantalla: un campo
    que se rechaza sin estar marcado es una trampa."""
    html = _sesion("20666666664").get("/app/inicio").text
    assert "Localidad *" in html and "Provincia *" in html
    for campo in ("Calle", "Altura", "Piso", "Código postal"):
        assert f"{campo} <span class=\"opc\">(opcional)</span>" in html, campo
    print("OK  test_el_formulario_marca_lo_obligatorio_y_lo_opcional")


def test_el_registro_tambien_pide_las_dos_en_pantalla():
    html = TestClient(main.app).get("/ingresar").text
    assert 'name="provincia" required' in html
    assert 'name="localidad" required' in html
    assert "Buenos Aires" in html, "la provincia es una lista canónica, no texto libre"
    for campo in ("Calle", "Altura", "Piso / depto", "Código postal"):
        assert f"{campo} <span class=\"opc\">(opcional)</span>" in html, campo
    print("OK  test_el_registro_tambien_pide_las_dos_en_pantalla")
