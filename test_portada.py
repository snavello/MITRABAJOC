"""Portada del trabajador (/app/inicio): pantalla de bienvenida nueva, no
reemplaza /app (Tu Recibo, que sigue intacta) -- misma resolución de
sindicato activo, con la marca correcta y sin romper el selector cuando el
CUIL está en varios sindicatos y todavía no eligió.

Correr con: .venv/Scripts/python.exe -m pytest test_portada.py -q
"""


import db
import auth
import fechas
from db import Sindicato, Trabajador
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Portada Test", slug="uom-portada-test",
                     color_base="#0f1b2d", color_acento="#e8a33d",
                     modulos_habilitados=list(MODULOS_INICIALES))
    fega = Sindicato(nombre="Gastronomica Portada Test", slug="fega-portada-test",
                      color_base="#0d2027", color_acento="#5fd6b4",
                      modulos_habilitados=list(MODULOS_INICIALES))
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20111111119",
                      activo=True, registrado=True))
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="27222222224",
                      activo=True, registrado=True))
    s.add(Trabajador(sindicato_id=SID_FEGA, cuil="27222222224",
                      activo=True, registrado=True))
    # El nombre es de la persona y no del empadronamiento: se escribe UNA vez
    # aunque "Ana Multi" esté en los dos sindicatos (ver CuentaTrabajador).
    db.guardar_datos_personales(s, "20111111119", nombre="Juan Perez")
    db.guardar_datos_personales(s, "27222222224", nombre="Ana Multi")
    s.commit()

client = TestClient(main.app)


def _sesion(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


def test_tarjetas_linkean_con_tab_para_deeplink():
    c = _sesion("20111111119")
    r = c.get("/app/inicio")
    assert 'href="/app?tab=aportes"' in r.text
    assert 'href="/app?tab=credencial"' in r.text
    assert 'href="/app?tab=capacitacion"' in r.text
    print("OK  test_tarjetas_linkean_con_tab_para_deeplink")


def test_perfil_muestra_datos_reales_del_trabajador():
    with db.get_session() as s:
        # El domicilio es de la PERSONA, no del empadronamiento (2026-09-22).
        db.guardar_datos_personales(
            s, "20111111119",
            domicilio={"localidad": "Rosario", "provincia": "Santa Fe"})
        s.commit()
    c = _sesion("20111111119")
    r = c.get("/app/inicio")
    assert "Juan Perez" in r.text
    assert "Rosario" in r.text and "Santa Fe" in r.text
    print("OK  test_perfil_muestra_datos_reales_del_trabajador")


def test_sin_sesion_redirige_a_ingresar():
    r = client.get("/app/inicio", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ingresar"
    print("OK  test_sin_sesion_redirige_a_ingresar")


def test_un_solo_sindicato_pinta_su_marca():
    c = _sesion("20111111119")
    r = c.get("/app/inicio")
    assert r.status_code == 200
    assert "UOM Portada Test" in r.text
    assert "#e8a33d" in r.text  # su acento, no el de otro sindicato
    assert "Todavía no generada" in r.text  # sin credencial generada en el test
    print("OK  test_un_solo_sindicato_pinta_su_marca")


def test_pluriempleo_sin_elegir_muestra_selector():
    c = _sesion("27222222224")
    r = c.get("/app/inicio")
    assert r.status_code == 200
    assert "UOM Portada Test" in r.text and "Gastronomica Portada Test" in r.text
    # No debe haber resuelto ninguna marca todavía -- es el selector, no la portada.
    assert "Hola," not in r.text
    print("OK  test_pluriempleo_sin_elegir_muestra_selector")


def test_pluriempleo_con_eleccion_pinta_la_elegida():
    c = _sesion("27222222224")
    c.cookies.set("sind_elegido", str(SID_FEGA))
    r = c.get("/app/inicio")
    assert r.status_code == 200
    assert "Gastronomica Portada Test" in r.text
    assert "#5fd6b4" in r.text
    print("OK  test_pluriempleo_con_eleccion_pinta_la_elegida")


def test_app_tu_recibo_sigue_intacta():
    """La portada es una ruta nueva -- /app (Tu Recibo) no debe haber cambiado."""
    c = _sesion("20111111119")
    r = c.get("/app")
    assert r.status_code == 200
    assert "Revisá tu recibo" in r.text or "recibo" in r.text.lower()
    print("OK  test_app_tu_recibo_sigue_intacta")


def test_login_redirige_a_inicio_no_a_app():
    with db.get_session() as s:
        # La fila de la persona ya existe (la crea el alta del padrón): lo
        # que convierte ese CUIL en una cuenta con la que se entra es la
        # clave, no la fila.
        db.asegurar_cuenta(s, "20111111119").clave_hash = auth.hashear_clave("demo1234")
        s.commit()
    r = client.post("/trabajador/login", data={"cuil": "20111111119", "clave": "demo1234"},
                     follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/app/inicio"
    print("OK  test_login_redirige_a_inicio_no_a_app")


def test_tarjeta_principal_dice_numeros_reales():
    """La tarjeta grande dice cuántos recibos verificó ESTE AÑO y cómo salió
    el último. Antes decía "Revisá tus aportes", que no le informaba nada al
    afiliado que él no supiera ya."""
    anio = fechas.hoy_texto()[:4]
    with db.get_session() as s:
        s.add(db.ReciboVerificado(sindicato_id=SID_UOM, cuil="20111111119",
                                  periodo=anio + "-03", estado="OK"))
        s.add(db.ReciboVerificado(sindicato_id=SID_UOM, cuil="20111111119",
                                  periodo=anio + "-04", estado="CON_DISCREPANCIAS"))
        # De otro año: NO entra en el contador, pero tampoco es el último.
        s.add(db.ReciboVerificado(sindicato_id=SID_UOM, cuil="20111111119",
                                  periodo="2019-11", estado="OK"))
        # De OTRO trabajador del mismo sindicato: no es asunto de este.
        s.add(db.ReciboVerificado(sindicato_id=SID_UOM, cuil="27222222224",
                                  periodo=anio + "-04", estado="OK"))
        s.commit()

    resumen = db.resumen_recibos_trabajador("20111111119", SID_UOM)
    assert resumen["anio"] == 2, resumen
    assert resumen["ultimo_periodo"] == anio + "-04", resumen
    assert resumen["ultimo_estado"] == "CON_DISCREPANCIAS", resumen

    r = _sesion("20111111119").get("/app/inicio")
    assert r.status_code == 200
    assert "recibos verificados este año" in r.text
    assert "con diferencias para revisar" in r.text
    print("OK  test_tarjeta_principal_dice_numeros_reales")


def test_sin_recibos_la_tarjeta_invita_en_vez_de_mentir():
    """Cero recibos no es lo mismo que un recibo en cero: sin ninguno, la
    tarjeta no muestra el contador, invita a subir el primero."""
    resumen = db.resumen_recibos_trabajador("27222222224", SID_FEGA)
    assert resumen == {"anio": 0, "ultimo_periodo": "", "ultimo_estado": ""}, resumen

    c = _sesion("27222222224")
    c.cookies.set("sind_elegido", str(SID_FEGA))
    r = c.get("/app/inicio")
    assert r.status_code == 200
    assert "Subí tu primer recibo" in r.text
    assert "recibos verificados este año" not in r.text
    print("OK  test_sin_recibos_la_tarjeta_invita_en_vez_de_mentir")


def test_la_noticia_conserva_su_foto():
    """La miniatura de la noticia es lo que la hace leerse como una novedad y
    no como un renglón de sistema. El rediseño la agranda, no la saca."""
    with db.get_session() as s:
        s.add(db.Noticia(sindicato_id=SID_UOM, titulo="Paritaria homologada",
                         bajada="Se liquida con los haberes del mes",
                         fecha_desde="2000-01-01", fecha_hasta="2999-12-31",
                         imagen1_datos=b"fake", imagen1_mime="image/png"))
        s.commit()
    r = _sesion("20111111119").get("/app/inicio")
    assert 'class="pt-mini"' in r.text
    assert "/noticia-imagen/" in r.text
    print("OK  test_la_noticia_conserva_su_foto")


def test_el_carrusel_de_beneficios_sigue_existiendo():
    """El carrusel se rehízo, no se sacó: con más de un beneficio tiene que
    salir con su pista, sus puntos y su barra de tiempo."""
    with db.get_session() as s:
        for i, rubro in enumerate(("Salud", "Turismo")):
            s.add(db.Beneficio(sindicato_id=SID_UOM, rubro=rubro,
                               descripcion="Descuento " + str(i),
                               fecha_desde="2000-01-01", fecha_hasta="2999-12-31"))
        s.commit()
    r = _sesion("20111111119").get("/app/inicio")
    assert 'id="car-pista"' in r.text
    assert 'class="car-punto' in r.text
    assert 'id="car-barra"' in r.text
    print("OK  test_el_carrusel_de_beneficios_sigue_existiendo")


if __name__ == "__main__":
    test_tarjetas_linkean_con_tab_para_deeplink()
    test_perfil_muestra_datos_reales_del_trabajador()
    test_sin_sesion_redirige_a_ingresar()
    test_un_solo_sindicato_pinta_su_marca()
    test_pluriempleo_sin_elegir_muestra_selector()
    test_pluriempleo_con_eleccion_pinta_la_elegida()
    test_app_tu_recibo_sigue_intacta()
    test_login_redirige_a_inicio_no_a_app()
    test_tarjeta_principal_dice_numeros_reales()
    test_sin_recibos_la_tarjeta_invita_en_vez_de_mentir()
    test_la_noticia_conserva_su_foto()
    test_el_carrusel_de_beneficios_sigue_existiendo()
    print("\nTodo OK — portada del trabajador (/app/inicio).")
