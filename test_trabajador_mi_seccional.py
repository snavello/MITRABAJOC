"""El bloque "Mi seccional" del perfil del afiliado, y su domicilio.

Los tres casos que la pantalla tiene que distinguir, porque dos de ellos NO
son errores y no pueden verse como tales:

1. Seccional asignada y georreferenciada: nombre, dirección, horario, mapa y
   los botones de contacto.
2. Seccional asignada pero SIN ubicar: dirección y contacto, sin mapa.
3. Sin seccional asignada: un texto que lo dice, y nada más.

Y la regla de producto que no se negocia: **la seccional la asigna únicamente
el sindicato**. El bloque es de solo lectura, no hay botón ni enlace para
pedir un cambio y no existe ningún trámite para eso.

Correr con: .venv/bin/python -m pytest test_trabajador_mi_seccional.py -q
"""
import auth
import db
import geo
import main
from db import Sindicato, CuentaTrabajador, Trabajador, Seccional
from fastapi.testclient import TestClient
from sqlmodel import select

db.crear_tablas()

CLAVE = "trab-demo"
CUIL_UBICADA = "20111111119"     # seccional con coordenadas
CUIL_SIN_GEO = "20222222227"     # seccional sin coordenadas
CUIL_SIN_SECC = "20333333336"    # sin seccional asignada

DOM = geo.campos_para_guardar(
    {"calle": "San Martín", "numero": "850", "localidad": "Rosario",
     "provincia": "Santa Fe", "codigo_postal": "2000"},
    precision="exacta", lat=-32.947338, lon=-60.636893)

with db.get_session() as s:
    sind = Sindicato(nombre="UOM MiSecc", slug="uom-misecc", color_base="#0f1b2d")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    ubicada = Seccional(sindicato_id=SID, nombre="Rosario", telefono="341 425 0850",
                        whatsapp="3415551234", mail="rosario@uom.org.ar",
                        horario_atencion="Lunes a viernes de 9 a 17", **DOM)
    sin_geo = Seccional(sindicato_id=SID, nombre="Rafaela", telefono="3492 400100",
                        horario_atencion="Lunes a viernes de 8 a 14",
                        **geo.campos_para_guardar(
                            {"calle": "Mitre", "numero": "100", "localidad": "Rafaela",
                             "provincia": "Santa Fe"}, precision="sin_geo"))
    s.add(ubicada); s.add(sin_geo); s.commit()
    s.refresh(ubicada); s.refresh(sin_geo)
    SEC_UBICADA, SEC_SIN_GEO = ubicada.id, sin_geo.id

    for cuil, secc in ((CUIL_UBICADA, SEC_UBICADA), (CUIL_SIN_GEO, SEC_SIN_GEO),
                       (CUIL_SIN_SECC, None)):
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave(CLAVE),
                               nombre="Afiliado"))
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, nombre=f"Afiliado {cuil[-4:]}",
                         registrado=True, seccional_id=secc))
    s.commit()


def _sesion(cuil):
    """Sesión de trabajador armada como en el resto de la suite: la cookie
    firmada directamente, sin pasar por el formulario de login."""
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


# ------------------------------------------------------------- los 3 casos

def test_con_seccional_georreferenciada_se_ve_todo():
    html = _sesion(CUIL_UBICADA).get("/app/inicio").text
    assert "Mi seccional" in html
    assert "Rosario" in html
    assert "San Martín 850, Rosario, Santa Fe (CP 2000)" in html
    assert "Lunes a viernes de 9 a 17" in html
    # El mapa chico, con las coordenadas en data-attributes para el JS.
    assert 'id="secc-mapa"' in html
    assert 'data-lat="-32.947338"' in html
    # Los tres botones.
    assert 'href="tel:341 425 0850"' in html
    assert 'id="secc-wa"' in html
    assert 'id="secc-ir"' in html
    print("OK  test_con_seccional_georreferenciada_se_ve_todo")


def test_con_seccional_sin_ubicar_hay_direccion_pero_no_mapa():
    html = _sesion(CUIL_SIN_GEO).get("/app/inicio").text
    assert "Rafaela" in html
    assert "Mitre 100, Rafaela, Santa Fe" in html
    assert "Lunes a viernes de 8 a 14" in html
    assert 'id="secc-mapa"' not in html, "sin coordenadas no se dibuja un mapa"
    assert "no está ubicada en el mapa" in html
    # El teléfono sigue estando: no tener mapa no es no tener contacto.
    assert 'href="tel:3492 400100"' in html
    print("OK  test_con_seccional_sin_ubicar_hay_direccion_pero_no_mapa")


def test_sin_seccional_asignada_lo_dice_sin_error():
    html = _sesion(CUIL_SIN_SECC).get("/app/inicio").text
    assert "Tu sindicato todavía no te asignó una seccional" in html
    assert 'id="secc-mapa"' not in html
    print("OK  test_sin_seccional_asignada_lo_dice_sin_error")


# ------------------------------------------ la seccional la asigna el gremio

def test_el_bloque_es_de_solo_lectura():
    """No hay forma de que el afiliado se cambie de seccional ni la pida: la
    decisión es del sindicato, y no se agregó ningún trámite para eso."""
    html = _sesion(CUIL_UBICADA).get("/app/inicio").text
    bloque = html[html.index('class="mi-secc"'):html.index('id="overlay-mapa"')]
    for prohibido in ("<select", "<input", "cambiar de seccional", "pedir cambio",
                      "solicitar"):
        assert prohibido not in bloque.lower(), f"el bloque no puede tener {prohibido}"
    print("OK  test_el_bloque_es_de_solo_lectura")


def test_el_afiliado_no_puede_cambiarse_la_seccional_por_la_api():
    """Ni armando el POST a mano: /api/perfil no toca seccional_id."""
    c = _sesion(CUIL_SIN_SECC)
    r = c.post("/api/perfil", data={
        "nombre": "Afiliado 3336", "calle": "", "numero": "", "piso_depto": "",
        # Provincia y localidad son obligatorias desde 2026-09-13; el resto
        # del domicilio sigue siendo opcional.
        "localidad": "Rosario", "provincia": "Santa Fe", "codigo_postal": "",
        "latitud": "", "longitud": "", "precision_geo": "sin_geo",
        "telefono": "", "mail": "", "seccional_id": str(SEC_UBICADA)})
    assert r.status_code == 200, r.text
    with db.get_session() as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == CUIL_SIN_SECC,
                                           Trabajador.sindicato_id == SID)).first()
        assert t.seccional_id is None, "el afiliado no se asigna seccional a sí mismo"
    print("OK  test_el_afiliado_no_puede_cambiarse_la_seccional_por_la_api")


# ------------------------------------------------- domicilio del afiliado

def test_el_afiliado_guarda_su_domicilio_con_coordenadas():
    c = _sesion(CUIL_UBICADA)
    r = c.post("/api/perfil", data={
        "nombre": "Juan Molina", "calle": "Av. Pellegrini", "numero": "1234",
        "piso_depto": "2 A", "localidad": "Rosario", "provincia": "Santa Fe",
        "codigo_postal": "2000", "latitud": "-32.958000", "longitud": "-60.645000",
        "precision_geo": "exacta", "telefono": "341 555 0000", "mail": "juan@mail.com"})
    assert r.status_code == 200, r.text
    with db.get_session() as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == CUIL_UBICADA,
                                           Trabajador.sindicato_id == SID)).first()
        assert t.localidad == "Rosario" and t.piso_depto == "2 A"
        assert t.codigo_postal == "2000"
        assert t.precision_geo == "exacta"
        assert round(t.latitud, 4) == -32.958
        # El texto lo arma el SERVIDOR, no el cliente.
        assert t.direccion_texto == "Av. Pellegrini 1234, 2 A, Rosario, Santa Fe (CP 2000)"
        assert t.geo_actualizado
    print("OK  test_el_afiliado_guarda_su_domicilio_con_coordenadas")


def test_el_domicilio_sin_coordenadas_queda_sin_geo():
    c = _sesion(CUIL_SIN_GEO)
    c.post("/api/perfil", data={
        "nombre": "Ana López", "calle": "Mitre", "numero": "50", "piso_depto": "",
        "localidad": "Rafaela", "provincia": "Santa Fe", "codigo_postal": "",
        "latitud": "", "longitud": "", "precision_geo": "exacta",
        "telefono": "", "mail": ""})
    with db.get_session() as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == CUIL_SIN_GEO,
                                           Trabajador.sindicato_id == SID)).first()
        assert t.precision_geo == "sin_geo"
        assert t.latitud is None
        assert t.direccion_texto == "Mitre 50, Rafaela, Santa Fe"
    print("OK  test_el_domicilio_sin_coordenadas_queda_sin_geo")


def test_geocodificar_del_afiliado_exige_sesion():
    r = TestClient(main.app).post("/api/geocodificar",
                                  json={"provincia": "Santa Fe", "localidad": "Rosario"})
    assert r.status_code == 403, r.status_code
    print("OK  test_geocodificar_del_afiliado_exige_sesion")


def test_el_tope_del_afiliado_es_por_cuil(monkeypatch):
    """El domicilio lo edita el propio afiliado, así que este endpoint queda
    expuesto a todo el padrón: sin tope, un sindicato con 5.000 afiliados nos
    hace bloquear por Nominatim. Y el tope es POR PERSONA, no por IP: en un
    gremio con wifi compartido la IP es la misma para todo el edificio."""
    monkeypatch.setattr(geo, "normalizar_direccion",
                        lambda *a, **k: {"candidatos": [], "aviso": "",
                                         "provincia": "", "localidad": ""})
    geo.reiniciar_topes()
    c1, c2 = _sesion(CUIL_UBICADA), _sesion(CUIL_SIN_GEO)
    cuerpo = {"provincia": "Santa Fe", "localidad": "Rosario"}
    for _ in range(geo.TOPE_POR_ACTOR):
        assert c1.post("/api/geocodificar", json=cuerpo).status_code == 200
    assert c1.post("/api/geocodificar", json=cuerpo).status_code == 429
    # El otro afiliado no paga el consumo del primero.
    assert c2.post("/api/geocodificar", json=cuerpo).status_code == 200
    geo.reiniciar_topes()
    print("OK  test_el_tope_del_afiliado_es_por_cuil")


def test_leaflet_se_sirve_local_con_sello():
    """Vendoreado como Chart.js, nunca CDN, y con el sello ?v= obligatorio de
    /static (si no, un cambio tarda hasta una hora en llegar)."""
    html = _sesion(CUIL_UBICADA).get("/app/inicio").text
    assert "/static/vendor/leaflet/leaflet.js?v=" in html
    assert "/static/vendor/leaflet/leaflet.css?v=" in html
    assert "/static/mapa.js?v=" in html
    assert "unpkg.com" not in html and "cdnjs" not in html and "cdn.jsdelivr" not in html
    c = TestClient(main.app)
    for ruta in ("/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css",
                 "/static/vendor/leaflet/images/marker-icon.png", "/static/mapa.js"):
        r = c.get(ruta)
        assert r.status_code == 200, ruta
        assert r.headers.get("cache-control") == "public, max-age=3600", ruta
    print("OK  test_leaflet_se_sirve_local_con_sello")


def test_la_atribucion_de_osm_esta_en_el_codigo():
    """Es obligatoria por la licencia de OSM: no se saca ni se achica."""
    r = TestClient(main.app).get("/static/mapa.js")
    assert "OpenStreetMap" in r.text
    assert "openstreetmap.org/copyright" in r.text
    print("OK  test_la_atribucion_de_osm_esta_en_el_codigo")
