"""Georreferenciación de seccionales: alta, edición, precisiones y aislamiento.

Lo que se verifica:

- Las precisiones que una seccional PUEDE tener (`exacta` y `manual`) se
  guardan como corresponde, y **sin coordenadas válidas ninguna vale**.
- **No se puede guardar sin ubicar, ni con el globo en el centro de la
  localidad** (2026-09-13): la dirección de una seccional va completa y en la
  puerta, porque el afiliado toca "Cómo llegar" y el teléfono lo lleva al
  punto guardado. La vía de escape cuando las APIs no responden no es guardar
  sin ubicar, es marcar el punto a mano (queda `manual`).
- Editar y mover el globo deja la ubicación en `manual`.
- **Aislamiento**: un admin no geocodifica, no ve la ficha ni edita una
  seccional de otro sindicato.
- **El contrato del bloque de domicilio**: `Seccional` y `Trabajador` tienen
  EXACTAMENTE los mismos campos, con los mismos tipos. Es la promesa que hace
  que las dos direcciones de la app se carguen igual, y si alguien le suma un
  campo a una sola tabla, este test lo dice con nombre y apellido.

Correr con: .venv/bin/python -m pytest test_seccional_geo.py -q
"""
import auth
import db
import geo
import main
from db import Sindicato, UsuarioSindicato, Seccional, Trabajador, Area
from fastapi.testclient import TestClient
from sqlmodel import select

db.crear_tablas()

with db.get_session() as s:
    a = Sindicato(nombre="UOM SecGeo", slug="uom-secgeo", color_base="#0f1b2d")
    b = Sindicato(nombre="Fega SecGeo", slug="fega-secgeo", color_base="#0d2027")
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id
    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20111111110", nombre="Admin A",
                           clave_hash=auth.hashear_clave("a-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_B, usuario="20222222220", nombre="Admin B",
                           clave_hash=auth.hashear_clave("b-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    ajena = Seccional(sindicato_id=SID_B, nombre="Ajena")
    s.add(ajena); s.commit(); s.refresh(ajena)
    SEC_AJENA = ajena.id

cliente = TestClient(main.app)
cliente.post("/admin/login", data={"usuario": "20111111110", "clave": "a-demo"})
cliente_b = TestClient(main.app)
cliente_b.post("/admin/login", data={"usuario": "20222222220", "clave": "b-demo"})


# Un domicilio completo y ubicado en la puerta: lo mínimo que el alta acepta.
# Cada test le cambia lo que va a mirar.
VALIDO = {"provincia": "Santa Fe", "localidad": "Rosario", "calle": "San Martín",
          "numero": "850", "piso_depto": "", "codigo_postal": "2000",
          "latitud": "-32.947338", "longitud": "-60.636893", "precision_geo": "exacta"}


def _postear(nombre, **extra):
    datos = dict(VALIDO, nombre=nombre)
    datos.update(extra)
    return cliente.post("/admin/seccional", data=datos, follow_redirects=False)


def _alta(nombre, **extra):
    """Alta que TIENE que entrar. Devuelve la fila guardada."""
    r = _postear(nombre, **extra)
    assert r.status_code == 303, r.text
    with db.get_session() as s:
        sec = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_A,
                                             Seccional.nombre == nombre)).first()
    assert sec is not None, f"no se guardó {nombre}: {r.headers.get('location')}"
    return sec


def _rechazada(nombre, **extra):
    """Alta que NO tiene que entrar. Devuelve el `err=` con el que volvió, que
    es lo que la pantalla usa para decir qué falta."""
    r = _postear(nombre, **extra)
    assert r.status_code == 303, r.text
    destino = r.headers.get("location", "")
    with db.get_session() as s:
        assert s.exec(select(Seccional).where(Seccional.sindicato_id == SID_A,
                                             Seccional.nombre == nombre)).first() is None, \
            f"{nombre} se guardó y no debería"
    return destino


# --------------------------------------------------- el contrato compartido

def test_seccional_y_trabajador_tienen_el_mismo_domicilio():
    """La promesa del sprint: un domicilio es un domicilio, se llame como se
    llame la tabla. Si alguien suma un campo a una sola, esto falla nombrando
    el campo y la tabla."""
    for campo in geo.CAMPOS_DOMICILIO:
        assert campo in Seccional.model_fields, f"falta {campo} en Seccional"
        assert campo in Trabajador.model_fields, f"falta {campo} en Trabajador"
    # Y con el mismo tipo en las dos: un `latitud` float acá y str allá haría
    # que la misma función de guardado escriba cosas distintas.
    for campo in geo.CAMPOS_DOMICILIO:
        t_sec = Seccional.model_fields[campo].annotation
        t_trab = Trabajador.model_fields[campo].annotation
        assert t_sec == t_trab, f"{campo}: {t_sec} en Seccional, {t_trab} en Trabajador"
    print("OK  test_seccional_y_trabajador_tienen_el_mismo_domicilio")


# --------------------------------------------------------- las 4 precisiones

def test_alta_con_geo_exacta():
    sec = _alta("Rosario Exacta", provincia="Santa Fe", localidad="Rosario",
                calle="San Martín", numero="850", codigo_postal="2000",
                latitud="-32.947338", longitud="-60.636893", precision_geo="exacta")
    assert sec.precision_geo == "exacta"
    assert round(sec.latitud, 5) == -32.94734 and round(sec.longitud, 5) == -60.63689
    assert sec.direccion_texto == "San Martín 850, Rosario, Santa Fe (CP 2000)"
    assert sec.geo_actualizado, "con coordenadas tiene que quedar el sello de tiempo"
    print("OK  test_alta_con_geo_exacta")


def test_una_seccional_aproximada_no_se_guarda():
    """`aproximada` es el centro de la localidad, no la puerta. Es el caso que
    más importa de todos: se guardaba sin chistar y el afiliado terminaba a
    quince cuadras siguiendo el "Cómo llegar" de la app. La diferencia con
    `manual` no son los metros, es quién responde por el punto."""
    destino = _rechazada("Salta Aprox", provincia="Salta", localidad="Salta",
                         calle="Caseros", numero="100",
                         latitud="-24.7897", longitud="-65.4116",
                         precision_geo="aproximada")
    assert "err=secsinubicar" in destino, destino
    print("OK  test_una_seccional_aproximada_no_se_guarda")


def test_alta_con_globo_movido_a_mano():
    sec = _alta("Cordoba Manual", provincia="Córdoba", localidad="Córdoba",
                calle="Boulevard San Juan", numero="430",
                latitud="-31.419157", longitud="-64.191904", precision_geo="manual")
    assert sec.precision_geo == "manual"
    print("OK  test_alta_con_globo_movido_a_mano")


def test_alta_sin_ubicar_se_rechaza():
    """Lo contrario de lo que este archivo probaba hasta el 2026-09-13. La
    ubicación dejó de ser opcional: una seccional sin globo no aparece en el
    mapa del Panel Sindical ni en la app del afiliado, o sea que se carga y no
    sirve para nada, y así quedaban."""
    destino = _rechazada("Sin Ubicar", localidad="Rafaela", calle="Mitre", numero="100",
                         latitud="", longitud="", precision_geo="sin_geo")
    assert "err=secsinubicar" in destino, destino
    print("OK  test_alta_sin_ubicar_se_rechaza")


def test_sin_calle_ni_altura_se_rechaza_nombrando_lo_que_falta():
    """El mensaje tiene que decir QUÉ falta: "revisá los datos" obliga a
    adivinar entre siete campos."""
    destino = _rechazada("Sin Calle", calle="", numero="")
    assert "err=secdireccion" in destino, destino
    assert "calle" in destino and "altura" in destino, destino
    print("OK  test_sin_calle_ni_altura_se_rechaza_nombrando_lo_que_falta")


def test_sin_provincia_ni_localidad_se_rechaza():
    destino = _rechazada("Sin Provincia", provincia="", localidad="")
    assert "err=secdireccion" in destino, destino
    assert "provincia" in destino and "localidad" in destino, destino
    print("OK  test_sin_provincia_ni_localidad_se_rechaza")


def test_sin_nombre_se_rechaza():
    """`nombre` llegaba obligatorio por FastAPI pero vacío pasaba, y quedaba
    una seccional sin nombre en la lista."""
    r = _postear("")
    assert "err=secsinnombre" in r.headers.get("location", "")
    with db.get_session() as s:
        assert not s.exec(select(Seccional).where(Seccional.sindicato_id == SID_A,
                                                 Seccional.nombre == "")).first()
    print("OK  test_sin_nombre_se_rechaza")


def test_precision_inventada_no_entra():
    """Un POST armado a mano no puede escribir una precisión que no existe. Y
    ahora tampoco cuela como `manual`: la lista de lo aceptable es cerrada
    (geo.PRECISIONES_SECCIONAL), así que lo que no está en la lista se
    rechaza en vez de guardarse con otro nombre."""
    destino = _rechazada("Precision Trucha", precision_geo="exactisima")
    assert "err=secsinubicar" in destino, destino
    print("OK  test_precision_inventada_no_entra")


def test_precision_exacta_sin_coordenadas_se_rechaza():
    """Una fila que dice "exacta" con lat/lon en NULL es peor que una que
    admite no estar ubicada. Antes se guardaba como `sin_geo` (que es lo que
    sigue haciendo `geo.campos_para_guardar`); ahora ni entra."""
    destino = _rechazada("Miente Exacta", latitud="", longitud="", precision_geo="exacta")
    assert "err=secsinubicar" in destino, destino
    # La regla de abajo sigue en pie, y es la que protege a las OTRAS cinco
    # rutas que escriben un domicilio: sin coordenadas válidas no hay
    # precisión que valga.
    assert geo.campos_para_guardar({"localidad": "Rosario"}, "exacta")["precision_geo"] == "sin_geo"
    print("OK  test_precision_exacta_sin_coordenadas_se_rechaza")


def test_coordenadas_basura_no_entran():
    for lat, lon in [("0", "0"), ("ahi", "-60.6"), ("91", "0"), ("-32.9", "181")]:
        destino = _rechazada(f"Basura {lat} {lon}", latitud=lat, longitud=lon,
                             precision_geo="exacta")
        assert "err=secsinubicar" in destino, f"{lat},{lon}: {destino}"
    print("OK  test_coordenadas_basura_no_entran")


# ------------------------------------------------------------------ edición

def test_editar_mueve_el_globo():
    sec = _alta("Para Mover", provincia="Santa Fe", localidad="Rosario",
                calle="San Martín", numero="850",
                latitud="-32.947338", longitud="-60.636893", precision_geo="exacta")
    r = cliente.post("/admin/seccional", data={
        **VALIDO, "id": str(sec.id), "nombre": "Para Mover",
        "latitud": "-32.950000", "longitud": "-60.640000", "precision_geo": "manual",
    }, follow_redirects=False)
    assert r.status_code == 303
    with db.get_session() as s:
        sec = s.get(Seccional, sec.id)
        assert sec.precision_geo == "manual"
        assert round(sec.latitud, 4) == -32.95
    print("OK  test_editar_mueve_el_globo")


def test_editar_guarda_el_contacto():
    sec = _alta("Con Contacto")
    cliente.post("/admin/seccional", data={
        **VALIDO, "id": str(sec.id), "nombre": "Con Contacto",
        "telefono": "341 425 0850", "whatsapp": "341 555 1234",
        "mail": "rosario@uom.org.ar", "horario_atencion": "Lunes a viernes de 9 a 17",
    })
    with db.get_session() as s:
        sec = s.get(Seccional, sec.id)
        assert sec.telefono == "341 425 0850"
        assert sec.whatsapp == "341 555 1234"
        assert sec.mail == "rosario@uom.org.ar"
        assert sec.horario_atencion == "Lunes a viernes de 9 a 17"
    print("OK  test_editar_guarda_el_contacto")


# --------------------------------------------------------------- aislamiento

def test_no_se_puede_editar_una_seccional_ajena():
    # Con un domicilio VÁLIDO: si el POST fuera inválido, el rechazo vendría
    # de la validación de la dirección y este test pasaría sin haber probado
    # el aislamiento.
    cliente.post("/admin/seccional", data={
        **VALIDO, "id": str(SEC_AJENA), "nombre": "Hackeada",
        "latitud": "-32.94", "longitud": "-60.63", "precision_geo": "manual",
    })
    with db.get_session() as s:
        sec = s.get(Seccional, SEC_AJENA)
        assert sec.nombre == "Ajena"
        assert sec.latitud is None, "no se le pudo poner ubicación a una seccional ajena"
    print("OK  test_no_se_puede_editar_una_seccional_ajena")


def test_la_ficha_de_una_seccional_ajena_da_404():
    """404 y no 403: un 403 confirmaría que ese id existe."""
    r = cliente.get(f"/admin/seccional/{SEC_AJENA}/ficha")
    assert r.status_code == 404, r.status_code
    print("OK  test_la_ficha_de_una_seccional_ajena_da_404")


def test_la_ficha_propia_trae_lo_que_muestra_la_pantalla():
    sec = _alta("Ficha Propia", provincia="Santa Fe", localidad="Rosario",
                calle="San Martín", numero="850",
                latitud="-32.947338", longitud="-60.636893", precision_geo="exacta",
                telefono="341 425 0850", horario_atencion="9 a 17")
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID_A, cuil="20888888884", nombre="Uno",
                         seccional_id=sec.id))
        s.commit()
    ficha = cliente.get(f"/admin/seccional/{sec.id}/ficha").json()
    assert ficha["nombre"] == "Ficha Propia"
    assert ficha["etiqueta_precision"] == geo.ETIQUETAS_PRECISION["exacta"]
    assert ficha["afiliados"] == 1
    assert ficha["telefono"] == "341 425 0850"
    print("OK  test_la_ficha_propia_trae_lo_que_muestra_la_pantalla")


def test_geocodificar_exige_sesion_y_permiso():
    # Sin sesión.
    r = TestClient(main.app).post("/admin/seccionales/geocodificar",
                                  json={"provincia": "Santa Fe", "localidad": "Rosario"},
                                  follow_redirects=False)
    assert r.status_code in (303, 403), r.status_code

    # Con sesión pero sin la sección "seccionales": el gateo de rutas es
    # fail-closed, así que tiene que rechazar aunque la ruta exista.
    with db.get_session() as s:
        sec = s.exec(select(Seccional).where(Seccional.sindicato_id == SID_A)).first()
        area = Area(sindicato_id=SID_A, seccional_id=sec.id, nombre="Sin Seccionales")
        s.add(area); s.commit(); s.refresh(area)
        db.set_permisos_area(area.id, ["trabajadores"], SID_A)
        s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20999999998", nombre="Limitado",
                               clave_hash=auth.hashear_clave("l-demo"), debe_cambiar_clave=False,
                               es_super_admin=False, seccional_id=sec.id, area_id=area.id))
        s.commit()
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": "20999999998", "clave": "l-demo"})
    r = c.post("/admin/seccionales/geocodificar",
               json={"provincia": "Santa Fe", "localidad": "Rosario"})
    assert r.status_code == 403, r.status_code
    print("OK  test_geocodificar_exige_sesion_y_permiso")


def test_geocodificar_no_lleva_la_direccion_en_la_url(monkeypatch):
    """Va por POST con el cuerpo en JSON aunque sea una lectura: una dirección
    en la query string termina en el log de acceso de Render y en el historial
    del navegador."""
    llamadas = {}
    monkeypatch.setattr(geo, "normalizar_direccion",
                        lambda *a, **k: llamadas.setdefault("args", (a, k)) or
                        {"candidatos": [], "aviso": "", "provincia": "", "localidad": ""})
    geo.reiniciar_topes()
    r = cliente.post("/admin/seccionales/geocodificar", json={
        "provincia": "Santa Fe", "localidad": "Rosario", "calle": "San Martín",
        "numero": "850"})
    assert r.status_code == 200
    assert llamadas["args"][0] == ("Santa Fe", "Rosario", "San Martín", "850")
    # La ruta no acepta GET: no hay forma de pedirla dejando rastro en la URL.
    assert cliente.get("/admin/seccionales/geocodificar").status_code == 405
    print("OK  test_geocodificar_no_lleva_la_direccion_en_la_url")


def test_el_tope_por_hora_frena_al_que_insiste(monkeypatch):
    monkeypatch.setattr(geo, "normalizar_direccion",
                        lambda *a, **k: {"candidatos": [], "aviso": "",
                                         "provincia": "", "localidad": ""})
    geo.reiniciar_topes()
    cuerpo = {"provincia": "Santa Fe", "localidad": "Rosario"}
    for _ in range(geo.TOPE_POR_ACTOR):
        assert cliente.post("/admin/seccionales/geocodificar", json=cuerpo).status_code == 200
    r = cliente.post("/admin/seccionales/geocodificar", json=cuerpo)
    assert r.status_code == 429, r.status_code
    geo.reiniciar_topes()
    print("OK  test_el_tope_por_hora_frena_al_que_insiste")


def test_borrar_una_seccional_ubicada_sigue_dejando_a_su_gente_sin_seccional():
    """El comportamiento de siempre no cambió por sumarle coordenadas."""
    sec = _alta("Para Borrar", provincia="Santa Fe", localidad="Rosario",
                latitud="-32.94", longitud="-60.63", precision_geo="manual")
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID_A, cuil="20777777773", nombre="Queda Suelto",
                         seccional_id=sec.id))
        s.commit()
    cliente.post("/admin/seccional/borrar", data={"id": sec.id})
    with db.get_session() as s:
        assert s.get(Seccional, sec.id) is None
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "20777777773")).first()
        assert t.seccional_id is None
    print("OK  test_borrar_una_seccional_ubicada_sigue_dejando_a_su_gente_sin_seccional")
