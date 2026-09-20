"""Sesión, login/registro y selector multisindicato del empleador -- mismo
patrón que el trabajador (CuentaEmpleador/Empleador, cuit_emp/
sind_elegido_emp), con su propia cookie de rol para que las dos sesiones
convivan en el mismo navegador sin pisarse.

Correr con: .venv/Scripts/python.exe -m pytest test_empresa_sesion.py -q
"""


import db
import auth
from db import Sindicato, Empleador, CuentaEmpleador
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Empresa Sesion", slug="uom-empresa-sesion",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    fega = Sindicato(nombre="Fega Empresa Sesion", slug="fega-empresa-sesion",
                      modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id

    # CUIT multisindicato (dado de alta en ambos, activo).
    s.add(Empleador(sindicato_id=SID_UOM, cuit="30700000001", razon_social="Constructora Demo"))
    s.add(Empleador(sindicato_id=SID_FEGA, cuit="30700000001", razon_social="Constructora Demo"))
    # CUIT en un solo sindicato.
    s.add(Empleador(sindicato_id=SID_UOM, cuit="30700000002", razon_social="Metalúrgica Sur"))
    # CUIT dado de baja (inactivo) -- no debería habilitar registro ni login.
    s.add(Empleador(sindicato_id=SID_UOM, cuit="30700000003", razon_social="De baja SA", activo=False))
    s.commit()


def _cliente():
    return TestClient(main.app)


def test_registro_rechazado_si_cuit_no_es_empleador_de_ningun_sindicato():
    c = _cliente()
    r = c.post("/empresa/registro", data={"cuit": "30799999999", "clave": "clave123"}, follow_redirects=False)
    assert r.status_code == 303
    assert "error=nohabilitado" in r.headers["location"]
    with Session(db.engine) as s:
        cuenta = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == "30799999999")).first()
        assert cuenta is None
    print("OK  test_registro_rechazado_si_cuit_no_es_empleador_de_ningun_sindicato")


def test_registro_ok_marca_empleador_registrado_true():
    c = _cliente()
    r = c.post("/empresa/registro", data={"cuit": "30700000002", "clave": "clave123"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/empresa/inicio"
    with Session(db.engine) as s:
        cuenta = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == "30700000002")).first()
        assert cuenta is not None
        e = s.exec(select(Empleador).where(
            Empleador.sindicato_id == SID_UOM, Empleador.cuit == "30700000002")).first()
        assert e.registrado is True
    print("OK  test_registro_ok_marca_empleador_registrado_true")


def test_login_clave_incorrecta_rechazada():
    c = _cliente()
    r = c.post("/empresa/login", data={"cuit": "30700000002", "clave": "clave-mala"}, follow_redirects=False)
    assert r.status_code == 303
    assert "error=login" in r.headers["location"]
    print("OK  test_login_clave_incorrecta_rechazada")


def test_login_ok_redirige_a_empresa_y_un_solo_sindicato_entra_directo():
    c = _cliente()
    r = c.post("/empresa/login", data={"cuit": "30700000002", "clave": "clave123"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/empresa/inicio"
    r2 = c.get("/empresa/inicio")
    assert r2.status_code == 200
    assert "Metalúrgica Sur" in r2.text
    assert "UOM Empresa Sesion" in r2.text
    print("OK  test_login_ok_redirige_a_empresa_y_un_solo_sindicato_entra_directo")


def test_empleador_inactivo_no_puede_registrarse():
    c = _cliente()
    r = c.post("/empresa/registro", data={"cuit": "30700000003", "clave": "clave123"}, follow_redirects=False)
    assert "error=nohabilitado" in r.headers["location"]
    print("OK  test_empleador_inactivo_no_puede_registrarse")


def test_multisindicato_muestra_selector_y_elegir_fija_cookie():
    c = _cliente()
    c.post("/empresa/registro", data={"cuit": "30700000001", "clave": "clave123"})
    r = c.get("/empresa")
    assert r.status_code == 200
    assert "UOM Empresa Sesion" in r.text and "Fega Empresa Sesion" in r.text
    assert "elegí el sindicato" in r.text.lower() or "elegir" in r.text.lower() or "Estás dado de alta" in r.text

    r2 = c.get(f"/empresa/elegir/{SID_UOM}", follow_redirects=False)
    assert r2.status_code == 303
    r3 = c.get("/empresa")
    assert "Constructora Demo" in r3.text
    assert "Elegí el sindicato" not in r3.text
    print("OK  test_multisindicato_muestra_selector_y_elegir_fija_cookie")


def test_sesion_empleador_no_pisa_sesion_trabajador_en_el_mismo_navegador():
    """Mismo bug que motivó 'Cookie de sesión separada por rol' -- acá con
    un rol nuevo (empleador), verificado directo: las dos cookies conviven."""
    with db.get_session() as s:
        from db import Trabajador
        s.add(Trabajador(sindicato_id=SID_UOM, cuil="20111111119", nombre="Juan", activo=True))
        s.commit()
    c = _cliente()
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident="20111111119"))
    c.cookies.set("cuil_trab", "20111111119")
    c.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0, ident="30700000002"))
    c.cookies.set("cuit_emp", "30700000002")

    r_app = c.get("/app", follow_redirects=False)
    assert r_app.status_code == 200, "la sesión de trabajador no debería haberse perdido"
    r_empresa = c.get("/empresa", follow_redirects=False)
    assert r_empresa.status_code == 200, "la sesión de empleador no debería haberse perdido"
    print("OK  test_sesion_empleador_no_pisa_sesion_trabajador_en_el_mismo_navegador")


def test_redirect_al_login_correcto_segun_prefijo():
    c = _cliente()
    r1 = c.get("/empresa", follow_redirects=False)
    assert r1.status_code == 303
    assert r1.headers["location"] == "/ingresar-empresa"

    r2 = c.get("/app", follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"] == "/ingresar"
    print("OK  test_redirect_al_login_correcto_segun_prefijo")


if __name__ == "__main__":
    test_registro_rechazado_si_cuit_no_es_empleador_de_ningun_sindicato()
    test_registro_ok_marca_empleador_registrado_true()
    test_login_clave_incorrecta_rechazada()
    test_login_ok_redirige_a_empresa_y_un_solo_sindicato_entra_directo()
    test_empleador_inactivo_no_puede_registrarse()
    test_multisindicato_muestra_selector_y_elegir_fija_cookie()
    test_sesion_empleador_no_pisa_sesion_trabajador_en_el_mismo_navegador()
    test_redirect_al_login_correcto_segun_prefijo()
    print("\nTodo OK — sesión del empleador.")
