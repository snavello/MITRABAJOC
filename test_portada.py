"""Portada del trabajador (/app/inicio): pantalla de bienvenida nueva, no
reemplaza /app (Tu Recibo, que sigue intacta) -- misma resolución de
sindicato activo, con la marca correcta y sin romper el selector cuando el
CUIL está en varios sindicatos y todavía no eligió.

Correr con: .venv/Scripts/python.exe -m pytest test_portada.py -q
"""


import db
import auth
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
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20111111119", nombre="Juan Perez",
                      activo=True, registrado=True))
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="27222222224", nombre="Ana Multi",
                      activo=True, registrado=True))
    s.add(Trabajador(sindicato_id=SID_FEGA, cuil="27222222224", nombre="Ana Multi",
                      activo=True, registrado=True))
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
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "20111111119",
                                             Trabajador.sindicato_id == SID_UOM)).first()
        t.localidad = "Rosario"       # antes `ciudad`; se renombró para que el
        t.provincia = "Santa Fe"      # domicilio se llame igual que el de la seccional
        s.add(t); s.commit()
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
        from db import CuentaTrabajador
        s.add(CuentaTrabajador(cuil="20111111119", clave_hash=auth.hashear_clave("demo1234")))
        s.commit()
    r = client.post("/trabajador/login", data={"cuil": "20111111119", "clave": "demo1234"},
                     follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/app/inicio"
    print("OK  test_login_redirige_a_inicio_no_a_app")


if __name__ == "__main__":
    test_tarjetas_linkean_con_tab_para_deeplink()
    test_perfil_muestra_datos_reales_del_trabajador()
    test_sin_sesion_redirige_a_ingresar()
    test_un_solo_sindicato_pinta_su_marca()
    test_pluriempleo_sin_elegir_muestra_selector()
    test_pluriempleo_con_eleccion_pinta_la_elegida()
    test_app_tu_recibo_sigue_intacta()
    test_login_redirige_a_inicio_no_a_app()
    print("\nTodo OK — portada del trabajador (/app/inicio).")
