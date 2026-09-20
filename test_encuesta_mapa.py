# -*- coding: utf-8 -*-
"""El mapa de burbujas del dashboard de una encuesta (pedido de Sd, 2026-09-13).

Cada seccional es una burbuja: el tamaño es cuánta gente respondió y el color
qué porcentaje de SU padrón es eso. Es el mismo mapa que el del Panel Sindical
--misma forma, misma escala, mismo `MapaMT.burbuja`-- aplicado a otra pregunta.

Lo que se verifica acá es lo que no se ve en la pantalla:

- **De dónde salen los números.** Del PADRÓN fijado al publicar, que es el
  único que sabe a cuántos se les preguntó: sin denominador no hay porcentaje
  de participación. Las pastillas, en cambio, cuentan respuestas en la urna.
  Son dos fuentes distintas a propósito y la pantalla lo dice.
- **Que el mapa IGNORE su propio filtro** (es el selector: si lo respetara,
  tocar una burbuja lo dejaría con un punto y sin vuelta) **pero NO ignore el
  filtro impuesto por alcance** (N18): dejarlo pasar le mostraría a una
  seccional cuánta gente participó en las otras.
- **Aislamiento**: ni una seccional ni un afiliado de otro sindicato entran,
  ni siquiera con el mismo CUIL empadronado en los dos (pluriempleo).
- Que no exista cuando la encuesta no guarda el corte de seccional: sin ese
  dato no hay nada que ubicar.

Correr con: .venv/bin/python -m pytest test_encuesta_mapa.py -q
"""
import json
from datetime import timedelta

import auth
import db
import fechas
import main
import modulos
from fastapi.testclient import TestClient

db.crear_tablas()

cliente = TestClient(main.app)

PREGUNTAS = [
    {"etiqueta": "¿Conforme?", "tipo_dato": "escala", "escala_min": 1, "escala_max": 5,
     "etiqueta_min": "Nada", "etiqueta_max": "Mucho", "ancho": "completo",
     "obligatorio": True},
]

# Rosario y Córdoba, con coordenadas de verdad; Rafaela queda sin ubicar.
ROSARIO = {"calle": "San Martín", "numero": "850", "localidad": "Rosario",
           "provincia": "Santa Fe", "lat": -32.947338, "lon": -60.636893}
CORDOBA = {"calle": "Bv. San Juan", "numero": "430", "localidad": "Córdoba",
           "provincia": "Córdoba", "lat": -31.419157, "lon": -64.191904}


def _sindicato(slug: str) -> tuple:
    with db.get_session() as s:
        sind = db.Sindicato(nombre=slug.upper(), slug=slug, color_base="#0f1b2d",
                            modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["encuestas"])
        s.add(sind); s.commit(); s.refresh(sind)
        u = db.UsuarioSindicato(sindicato_id=sind.id, usuario=f"20{sind.id:09d}",
                                nombre="Admin", clave_hash=auth.hashear_clave("x"),
                                debe_cambiar_clave=False, es_super_admin=True)
        s.add(u); s.commit(); s.refresh(u)
        return sind.id, u.id


def _seccional(sid: int, nombre: str, geo_datos=None) -> int:
    """Una seccional con o sin coordenadas. Con `geo_datos` queda ubicada a
    mano (`manual`), que es como las deja el asistente del panel."""
    import geo
    campos = geo.campos_para_guardar(
        {k: v for k, v in (geo_datos or {}).items() if k not in ("lat", "lon")},
        precision="manual" if geo_datos else "sin_geo",
        lat=(geo_datos or {}).get("lat"), lon=(geo_datos or {}).get("lon"))
    with db.get_session() as s:
        x = db.Seccional(sindicato_id=sid, nombre=nombre, **campos)
        s.add(x); s.commit(); s.refresh(x)
        return x.id


def _padron(sid: int, cuils: list, seccional_id=None, provincia="Santa Fe"):
    with db.get_session() as s:
        for c in cuils:
            s.add(db.Trabajador(sindicato_id=sid, cuil=c, nombre="T " + c, activo=True,
                                registrado=True, seccional_id=seccional_id,
                                provincia=provincia, cuit_empleador="30999888776"))
        s.commit()


def _sesion(sid: int, uid: int):
    cliente.cookies.clear()
    cliente.cookies.set("sesion_sindicato", auth.crear_sesion("sindicato", uid, sid))


def _admin_de_seccional(sid: int, seccional_id: int) -> int:
    with db.get_session() as s:
        u = db.UsuarioSindicato(sindicato_id=sid, usuario=f"27{seccional_id:09d}",
                                nombre="Admin local", clave_hash=auth.hashear_clave("x"),
                                debe_cambiar_clave=False, es_admin_seccional=True,
                                seccional_id=seccional_id)
        s.add(u); s.commit(); s.refresh(u)
        return u.id


def _publicar(sid: int, uid: int, cortes=("seccional",), modo="anonima") -> int:
    _sesion(sid, uid)
    hoy = fechas.hoy()
    cliente.post("/admin/encuesta", data={
        "titulo": "Clima", "descripcion": "Corta", "modo": modo, "cortes": list(cortes),
        "fecha_desde": (hoy - timedelta(days=1)).isoformat(),
        "fecha_hasta": (hoy + timedelta(days=30)).isoformat(),
        "mostrar_resultados": "1", "preguntas_json": json.dumps(PREGUNTAS),
    }, follow_redirects=False)
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    r = cliente.post("/admin/encuesta/publicar",
                     data={"id": eid, "criterio": "todos"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return eid


def _responden(eid: int, sid: int, cuils: list):
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in cuils:
        cliente.cookies.clear()
        cliente.cookies.set("sesion_trabajador", auth.crear_sesion("trabajador", ident=c))
        cliente.cookies.set("cuil_trab", c)
        cliente.cookies.set("sind_elegido", str(sid))
        r = cliente.post(f"/api/encuesta/{eid}", json={"respuestas": {str(pids[0]): 4}})
        assert r.status_code == 200, r.text


def _mapa(eid: int, **params):
    r = cliente.get("/admin/encuesta/resultados", params={"id": eid, **params})
    assert r.status_code == 200, r.text
    return r.json()["mapa"]


def _por_nombre(mapa: dict, nombre: str):
    for x in mapa["seccionales"]:
        if x["nombre"] == nombre:
            return x
    return None


# ----------------------------------------------------------- el caso base

def test_una_burbuja_por_seccional_con_su_participacion():
    sid, uid = _sindicato("mapa-base")
    rosario = _seccional(sid, "Rosario", ROSARIO)
    cordoba = _seccional(sid, "Córdoba", CORDOBA)
    en_rosario = [f"20{sid:05d}{n:04d}" for n in range(5)]
    en_cordoba = [f"27{sid:05d}{n:04d}" for n in range(4)]
    _padron(sid, en_rosario, seccional_id=rosario)
    _padron(sid, en_cordoba, seccional_id=cordoba, provincia="Córdoba")
    eid = _publicar(sid, uid)
    _responden(eid, sid, en_rosario[:4] + en_cordoba[:1])

    _sesion(sid, uid)
    mapa = _mapa(eid)
    r, c = _por_nombre(mapa, "Rosario"), _por_nombre(mapa, "Córdoba")
    assert (r["convocados"], r["respondieron"], r["porcentaje"]) == (5, 4, 80.0)
    assert (c["convocados"], c["respondieron"], c["porcentaje"]) == (4, 1, 25.0)
    # Las coordenadas viajan para poder dibujarlas, y el domicilio armado por
    # el servidor para el popup.
    assert round(r["lat"], 4) == -32.9473 and round(r["lon"], 4) == -60.6369
    assert r["direccion_texto"] == "San Martín 850, Rosario, Santa Fe"
    assert mapa["sin_ubicar"] == [] and mapa["impuesto"] is False
    print("OK  test_una_burbuja_por_seccional_con_su_participacion")


def test_el_mapa_no_existe_sin_el_corte_de_seccional():
    """Una anónima que no guarda seccional no tiene ese dato en la urna ni
    razón para ubicar a nadie: el mapa no viaja y la pantalla lo esconde."""
    sid, uid = _sindicato("mapa-sin-corte")
    sec = _seccional(sid, "Rosario", ROSARIO)
    cuils = [f"20{sid:05d}{n:04d}" for n in range(3)]
    _padron(sid, cuils, seccional_id=sec)
    eid = _publicar(sid, uid, cortes=())
    _sesion(sid, uid)
    assert _mapa(eid) is None
    print("OK  test_el_mapa_no_existe_sin_el_corte_de_seccional")


def test_una_seccional_sin_coordenadas_se_nombra_aparte():
    """No se la puede dibujar, pero participó: esconderla haría que los
    números del mapa no cierren con los del tablero."""
    sid, uid = _sindicato("mapa-sin-geo")
    ubicada = _seccional(sid, "Rosario", ROSARIO)
    sin_geo = _seccional(sid, "Rafaela")          # sin coordenadas
    a = [f"20{sid:05d}{n:04d}" for n in range(3)]
    b = [f"27{sid:05d}{n:04d}" for n in range(2)]
    _padron(sid, a, seccional_id=ubicada)
    _padron(sid, b, seccional_id=sin_geo)
    eid = _publicar(sid, uid)
    _responden(eid, sid, a[:2] + b[:1])

    _sesion(sid, uid)
    mapa = _mapa(eid)
    assert [x["nombre"] for x in mapa["seccionales"]] == ["Rosario"]
    assert [x["nombre"] for x in mapa["sin_ubicar"]] == ["Rafaela"]
    assert mapa["sin_ubicar"][0]["respondieron"] == 1
    print("OK  test_una_seccional_sin_coordenadas_se_nombra_aparte")


def test_una_seccional_que_no_entro_en_el_padron_no_aparece():
    """Cero de cero no es 0% de participación: es una encuesta que no le
    llegó. Dibujarla en el mapa diría algo que no pasó."""
    sid, uid = _sindicato("mapa-ajena-al-padron")
    con_gente = _seccional(sid, "Rosario", ROSARIO)
    _seccional(sid, "Córdoba", CORDOBA)            # nadie de acá en el padrón
    cuils = [f"20{sid:05d}{n:04d}" for n in range(3)]
    _padron(sid, cuils, seccional_id=con_gente)
    eid = _publicar(sid, uid)
    _sesion(sid, uid)
    assert [x["nombre"] for x in _mapa(eid)["seccionales"]] == ["Rosario"]
    print("OK  test_una_seccional_que_no_entro_en_el_padron_no_aparece")


# ------------------------------------------------ el mapa ES el selector

def test_el_mapa_ignora_el_filtro_de_seccional_elegido():
    """Si lo respetara, tocar una burbuja dejaría el mapa con un solo punto y
    no habría forma de volver. Los gráficos SÍ se filtran."""
    sid, uid = _sindicato("mapa-selector")
    rosario = _seccional(sid, "Rosario", ROSARIO)
    cordoba = _seccional(sid, "Córdoba", CORDOBA)
    a = [f"20{sid:05d}{n:04d}" for n in range(4)]
    b = [f"27{sid:05d}{n:04d}" for n in range(4)]
    _padron(sid, a, seccional_id=rosario)
    _padron(sid, b, seccional_id=cordoba, provincia="Córdoba")
    eid = _publicar(sid, uid)
    _responden(eid, sid, a + b)

    _sesion(sid, uid)
    r = cliente.get("/admin/encuesta/resultados",
                    params={"id": eid, "seccional": rosario}).json()
    assert r["respondentes"] == 4, "el tablero sí se filtra"
    nombres = [x["nombre"] for x in r["mapa"]["seccionales"]]
    assert sorted(nombres) == ["Córdoba", "Rosario"], "el mapa se queda entero"
    # Y con el filtro puesto los números del mapa no cambian: es una foto de
    # la participación, no del recorte.
    assert _por_nombre(r["mapa"], "Córdoba")["respondieron"] == 4
    print("OK  test_el_mapa_ignora_el_filtro_de_seccional_elegido")


def test_los_otros_cortes_si_recortan_el_mapa():
    """Provincia y empleador no son el selector del mapa, así que aplican:
    con un empleador elegido, las burbujas muestran su gente."""
    sid, uid = _sindicato("mapa-otros-cortes")
    rosario = _seccional(sid, "Rosario", ROSARIO)
    a = [f"20{sid:05d}{n:04d}" for n in range(3)]
    b = [f"27{sid:05d}{n:04d}" for n in range(2)]
    _padron(sid, a, seccional_id=rosario, provincia="Santa Fe")
    _padron(sid, b, seccional_id=rosario, provincia="Córdoba")
    eid = _publicar(sid, uid, cortes=("seccional", "provincia"))
    _responden(eid, sid, a[:2] + b[:1])

    _sesion(sid, uid)
    entero = _por_nombre(_mapa(eid), "Rosario")
    assert (entero["convocados"], entero["respondieron"]) == (5, 3)
    recortado = _por_nombre(_mapa(eid, provincia="Córdoba"), "Rosario")
    assert (recortado["convocados"], recortado["respondieron"]) == (2, 1)
    print("OK  test_los_otros_cortes_si_recortan_el_mapa")


def test_el_alcance_de_seccional_si_recorta_el_mapa():
    """N18: el recorte impuesto no es una elección de quien mira. Si el mapa
    lo ignorara como ignora el filtro elegido, un Admin de Seccional vería en
    un mapa cuánta gente participó en las seccionales que no le tocan."""
    sid, uid = _sindicato("mapa-n18")
    mia = _seccional(sid, "Rosario", ROSARIO)
    otra = _seccional(sid, "Córdoba", CORDOBA)
    mios = [f"20{sid:05d}{n:04d}" for n in range(5)]
    ajenos = [f"27{sid:05d}{n:04d}" for n in range(5)]
    _padron(sid, mios, seccional_id=mia)
    _padron(sid, ajenos, seccional_id=otra, provincia="Córdoba")
    eid = _publicar(sid, uid)
    _responden(eid, sid, mios[:3] + ajenos[:5])

    _sesion(sid, _admin_de_seccional(sid, mia))
    mapa = _mapa(eid)
    assert [x["nombre"] for x in mapa["seccionales"]] == ["Rosario"]
    assert mapa["impuesto"] is True, "con el recorte impuesto las burbujas no filtran"
    assert _por_nombre(mapa, "Rosario")["respondieron"] == 3
    # Y pedir la otra a mano no la trae: el filtro queda en la lista vacía
    # defensiva de `filtros_saneados` y el mapa sale sin ninguna burbuja, igual
    # que el resto del tablero sale en cero (el test de N18 de
    # test_encuestas.py verifica esa parte). Es fail-closed: pedir algo fuera
    # del alcance no devuelve algo distinto, devuelve nada. Por la pantalla no
    # se puede llegar -- con el recorte impuesto las pastillas están
    # deshabilitadas y las burbujas no filtran.
    assert _mapa(eid, seccional=otra)["seccionales"] == []
    print("OK  test_el_alcance_de_seccional_si_recorta_el_mapa")


# ------------------------------------------------------------ aislamiento

def test_ni_una_seccional_ni_un_afiliado_de_otro_sindicato():
    """Incluido el caso de pluriempleo: el MISMO CUIL empadronado en los dos
    gremios. Sin el `sindicato_id` adentro del WHERE, su fila del otro
    sindicato sumaría en este mapa."""
    sid_a, uid_a = _sindicato("mapa-aisl-a")
    sid_b, uid_b = _sindicato("mapa-aisl-b")
    sec_a = _seccional(sid_a, "Rosario", ROSARIO)
    sec_b = _seccional(sid_b, "Córdoba Ajena", CORDOBA)
    compartidos = [f"20{sid_a:05d}{n:04d}" for n in range(3)]
    _padron(sid_a, compartidos, seccional_id=sec_a)
    # La misma persona, en el otro gremio y en otra seccional.
    _padron(sid_b, compartidos, seccional_id=sec_b, provincia="Córdoba")

    eid = _publicar(sid_a, uid_a)
    _sesion(sid_a, uid_a)
    mapa = _mapa(eid)
    assert [x["nombre"] for x in mapa["seccionales"]] == ["Rosario"]
    assert _por_nombre(mapa, "Rosario")["convocados"] == 3, \
        "la fila del otro sindicato no puede duplicar el padrón"
    print("OK  test_ni_una_seccional_ni_un_afiliado_de_otro_sindicato")


def test_con_el_grupo_bajo_el_umbral_el_mapa_sigue_viajando():
    """El umbral esconde QUÉ contestaron, no cuánta gente participó: es el
    mismo criterio de las pastillas, que también siguen mostrando su número.
    Si el mapa desapareciera, el admin no tendría con qué sacar el filtro."""
    sid, uid = _sindicato("mapa-umbral")
    rosario = _seccional(sid, "Rosario", ROSARIO)
    cordoba = _seccional(sid, "Córdoba", CORDOBA)
    a = [f"20{sid:05d}{n:04d}" for n in range(8)]
    b = [f"27{sid:05d}{n:04d}" for n in range(8)]
    _padron(sid, a, seccional_id=rosario)
    _padron(sid, b, seccional_id=cordoba, provincia="Córdoba")
    eid = _publicar(sid, uid)
    _responden(eid, sid, a + b[:1])        # Córdoba queda con una sola

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/resultados",
                    params={"id": eid, "seccional": cordoba}).json()
    assert d["oculto"] is True and d["preguntas"] == []
    assert d["mapa"] is not None and len(d["mapa"]["seccionales"]) == 2
    print("OK  test_con_el_grupo_bajo_el_umbral_el_mapa_sigue_viajando")


# ------------------------------------------------------------- la pantalla

def test_la_pantalla_trae_el_mapa_con_leaflet_vendoreado():
    """Leaflet y mapa.js con el sello `?v=` de /static/, y el contenedor con
    el logo del sindicato para la marca de agua de las burbujas."""
    sid, uid = _sindicato("mapa-pantalla")
    sec = _seccional(sid, "Rosario", ROSARIO)
    cuils = [f"20{sid:05d}{n:04d}" for n in range(3)]
    _padron(sid, cuils, seccional_id=sec)
    eid = _publicar(sid, uid)
    _sesion(sid, uid)
    html = cliente.get(f"/admin/encuesta/{eid}/resultados").text
    assert "/static/vendor/leaflet/leaflet.js?v=" in html
    assert "/static/vendor/leaflet/leaflet.css?v=" in html
    assert "/static/mapa.js?v=" in html
    assert 'id="mapa-seccionales"' in html and 'id="mapa-seccion"' in html
    assert "data-logo=" in html
    # El color de selección de las burbujas es el del panel, no el de la marca.
    assert "--destacado:" in html
    print("OK  test_la_pantalla_trae_el_mapa_con_leaflet_vendoreado")
