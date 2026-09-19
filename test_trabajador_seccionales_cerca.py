"""GET /api/seccionales — lo que consume "Seccionales cerca de mí".

La regla de privacidad del feature: **la ubicación del teléfono no viaja al
servidor**. El cliente pide la lista de seccionales y calcula la distancia en
el navegador; acá no hay ningún endpoint que reciba una posición, y este test
lo verifica además de lo obvio.

Y las dos reglas de alcance:
- Solo seccionales del **sindicato activo** (un CUIL en dos gremios ve las del
  que eligió, no la suma).
- Ni un dato de otra persona: son datos de la institución.

Correr con: .venv/bin/python -m pytest test_trabajador_seccionales_cerca.py -q
"""
import auth
import db
import geo
import main
from db import Sindicato, CuentaTrabajador, Trabajador, Seccional
from fastapi.testclient import TestClient

db.crear_tablas()

CUIL_UNO = "20111111119"        # un solo sindicato
CUIL_DOS = "27222222224"        # pluriempleo: en los dos


def _dom(calle, numero, localidad, provincia, lat, lon, precision="exacta"):
    return geo.campos_para_guardar(
        {"calle": calle, "numero": numero, "localidad": localidad, "provincia": provincia},
        precision=precision, lat=lat, lon=lon)


with db.get_session() as s:
    a = Sindicato(nombre="UOM Cerca", slug="uom-cerca", color_base="#0f1b2d")
    b = Sindicato(nombre="Fega Cerca", slug="fega-cerca", color_base="#0d2027")
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id

    ros = Seccional(sindicato_id=SID_A, nombre="Rosario", telefono="341 425 0850",
                    whatsapp="3415551234", horario_atencion="9 a 17",
                    **_dom("San Martín", "850", "Rosario", "Santa Fe", -32.947338, -60.636893))
    cba = Seccional(sindicato_id=SID_A, nombre="Córdoba",
                    **_dom("Boulevard San Juan", "430", "Córdoba", "Córdoba",
                           -31.419157, -64.191904, "manual"))
    # Sin coordenadas: no puede salir en una lista que se ordena por distancia.
    rafa = Seccional(sindicato_id=SID_A, nombre="Rafaela",
                     **geo.campos_para_guardar({"localidad": "Rafaela", "provincia": "Santa Fe"},
                                               precision="sin_geo"))
    mdq = Seccional(sindicato_id=SID_B, nombre="Mar del Plata",
                    **_dom("Avenida Luro", "3100", "Mar del Plata", "Buenos Aires",
                           -37.996284, -57.551156))
    s.add(ros); s.add(cba); s.add(rafa); s.add(mdq); s.commit()
    for x in (ros, cba, rafa, mdq):
        s.refresh(x)
    SEC_ROS, SEC_CBA, SEC_MDQ = ros.id, cba.id, mdq.id

    for cuil in (CUIL_UNO, CUIL_DOS):
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave("x"), nombre="A"))
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_UNO, nombre="Juan Solo",
                     registrado=True, seccional_id=SEC_ROS))
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_DOS, nombre="Maria Dos",
                     registrado=True, seccional_id=SEC_CBA))
    s.add(Trabajador(sindicato_id=SID_B, cuil=CUIL_DOS, nombre="Maria Dos",
                     registrado=True, seccional_id=SEC_MDQ))
    # Otro afiliado, para probar que sus datos no salen por ningún lado.
    s.add(Trabajador(sindicato_id=SID_A, cuil="20999999995", nombre="Ajeno Nadiesabe",
                     registrado=True, seccional_id=SEC_ROS))
    s.commit()


def _sesion(cuil, sindicato_elegido=None):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    if sindicato_elegido:
        c.cookies.set("sind_elegido", str(sindicato_elegido))
    return c


def test_solo_las_georreferenciadas_del_sindicato():
    d = _sesion(CUIL_UNO).get("/api/seccionales").json()
    nombres = [s["nombre"] for s in d["seccionales"]]
    assert nombres == ["Córdoba", "Rosario"], nombres   # ordenadas por provincia
    assert "Rafaela" not in nombres, "sin coordenadas no entra en la lista"
    assert "Mar del Plata" not in nombres, "es de otro sindicato"
    assert d["mi_seccional_id"] == SEC_ROS
    print("OK  test_solo_las_georreferenciadas_del_sindicato")


def test_pluriempleo_ve_las_del_sindicato_activo():
    """El mismo CUIL en dos gremios ve las del que eligió, no la suma."""
    en_a = _sesion(CUIL_DOS, SID_A).get("/api/seccionales").json()
    assert [s["nombre"] for s in en_a["seccionales"]] == ["Córdoba", "Rosario"]
    assert en_a["mi_seccional_id"] == SEC_CBA

    en_b = _sesion(CUIL_DOS, SID_B).get("/api/seccionales").json()
    assert [s["nombre"] for s in en_b["seccionales"]] == ["Mar del Plata"]
    assert en_b["mi_seccional_id"] == SEC_MDQ
    print("OK  test_pluriempleo_ve_las_del_sindicato_activo")


def test_pluriempleo_sin_elegir_no_devuelve_nada():
    """Sin sindicato activo no hay padrón del que hablar: 403, no la unión de
    los dos (que sería filtrar de un gremio al otro)."""
    r = _sesion(CUIL_DOS).get("/api/seccionales")
    assert r.status_code == 403, r.status_code
    print("OK  test_pluriempleo_sin_elegir_no_devuelve_nada")


def test_no_sale_ni_un_dato_de_otra_persona():
    crudo = _sesion(CUIL_UNO).get("/api/seccionales").text
    for prohibido in ("Ajeno", "Nadiesabe", "20999999995", "Juan Solo", "Maria Dos"):
        assert prohibido not in crudo, f"se filtró {prohibido}"
    print("OK  test_no_sale_ni_un_dato_de_otra_persona")


def test_las_claves_son_solo_datos_de_la_institucion():
    for s in _sesion(CUIL_UNO).get("/api/seccionales").json()["seccionales"]:
        assert set(s) == {"id", "nombre", "ve_todas", "calle", "numero", "piso_depto",
                          "localidad", "provincia", "codigo_postal", "direccion_texto",
                          "latitud", "longitud", "precision_geo", "geo_actualizado",
                          "telefono", "whatsapp", "mail", "horario_atencion"}
    print("OK  test_las_claves_son_solo_datos_de_la_institucion")


def test_trae_lo_que_la_lista_necesita_para_los_botones():
    ros = next(s for s in _sesion(CUIL_UNO).get("/api/seccionales").json()["seccionales"]
               if s["nombre"] == "Rosario")
    assert ros["telefono"] == "341 425 0850"
    assert ros["whatsapp"] == "3415551234"
    assert ros["horario_atencion"] == "9 a 17"
    assert ros["latitud"] and ros["longitud"]
    print("OK  test_trae_lo_que_la_lista_necesita_para_los_botones")


def test_exige_sesion_de_trabajador():
    r = TestClient(main.app).get("/api/seccionales")
    assert r.status_code == 403, r.status_code
    # Una sesión de OTRO rol no sirve: cada rol lee solo su propia cookie.
    c = TestClient(main.app)
    c.cookies.set("sesion_sindicato", auth.crear_sesion("sindicato", sindicato_id=SID_A))
    assert c.get("/api/seccionales").status_code == 403
    print("OK  test_exige_sesion_de_trabajador")


def test_no_existe_ningun_endpoint_que_reciba_la_ubicacion():
    """La posición del teléfono se usa en el navegador y se descarta. Si algún
    día alguien agrega una ruta que la reciba, este test lo va a decir: es la
    promesa que la pantalla le hace al afiliado antes de pedirle el permiso."""
    sospechosas = []
    for ruta in main.app.routes:
        path = getattr(ruta, "path", "")
        if any(p in path.lower() for p in ("ubicacion", "posicion", "geoloc", "mi-posicion")):
            sospechosas.append(path)
    assert not sospechosas, f"rutas que recibirían la ubicación: {sospechosas}"

    # Y /api/seccionales no acepta lat/lon: manda la lista completa igual.
    c = _sesion(CUIL_UNO)
    sin = c.get("/api/seccionales").json()
    con = c.get("/api/seccionales", params={"lat": "-32.9", "lon": "-60.6"}).json()
    assert sin == con, "la respuesta no puede depender de una posición"
    print("OK  test_no_existe_ningun_endpoint_que_reciba_la_ubicacion")


def test_el_orden_es_estable_y_por_provincia():
    """Sin ubicación el cliente muestra la lista tal como viene: si el orden
    del servidor fuera arbitrario, la lista bailaría entre recargas."""
    c = _sesion(CUIL_UNO)
    uno = [s["id"] for s in c.get("/api/seccionales").json()["seccionales"]]
    dos = [s["id"] for s in c.get("/api/seccionales").json()["seccionales"]]
    assert uno == dos
    print("OK  test_el_orden_es_estable_y_por_provincia")


def test_haversine_del_servidor_y_del_navegador_dan_lo_mismo():
    """El cliente calcula la distancia en JS (la posición no viaja) y el
    servidor tiene su propia copia para ordenar por domicilio guardado. Las
    dos tienen que dar lo mismo o la misma seccional estaría a distinta
    distancia según qué camino se use."""
    # Rosario -> Córdoba, con las coordenadas reales de las dos seccionales.
    km = geo.distancia_km(-32.947338, -60.636893, -31.419157, -64.191904)
    # 375 km en LÍNEA RECTA. Por ruta son unos 400, y esa diferencia es
    # esperable: haversine mide sobre la esfera, no por la autopista.
    assert 370 < km < 380, km
    js = open("static/mapa.js", encoding="utf-8").read()
    assert "6371" in js, "el radio de la Tierra tiene que ser el mismo en las dos"
    assert "Math.asin(Math.sqrt(a))" in js, "y la misma fórmula de haversine"
    print("OK  test_haversine_del_servidor_y_del_navegador_dan_lo_mismo")
