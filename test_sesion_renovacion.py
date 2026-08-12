"""Sesión por inactividad (15 min, sliding window): cada request autenticado
renueva el token; después de 15 min sin uso, expira.

Bug real encontrado al construir esto: el middleware de renovación leía el
token del REQUEST entrante y lo reemitía sobre la respuesta -- si esa misma
respuesta era un login/logout que ya había puesto su propio Set-Cookie
(con el rol nuevo), la renovación lo pisaba con el rol VIEJO por encima,
así que loguearse con un rol distinto en la misma sesión de navegador nunca
"prendía" de verdad.

Correr con: .venv/Scripts/python.exe test_sesion_renovacion.py
"""
import os
import tempfile
import time

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato
import main
from fastapi.testclient import TestClient

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Sesion", slug="test-sesion")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("clave-test"), debe_cambiar_clave=False))
    s.commit()


def test_actividad_reemite_el_token():
    # OJO: si login y el siguiente request caen en el mismo segundo, el token
    # reemitido puede ser BYTE A BYTE igual al anterior (mismo payload, mismo
    # "t" truncado a entero) -- no es un bug, solo hace que comparar por
    # igualdad de string no sirva acá. Lo que importa es que el mecanismo
    # corrió: el response tiene que traer un Set-Cookie para la sesión.
    client = TestClient(main.app)
    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    assert client.cookies.get(main.COOKIE)

    r = client.get("/admin")
    set_cookie = r.headers.get("set-cookie", "")
    assert set_cookie.startswith(f"{main.COOKIE}="), "la renovación tiene que reemitir la cookie de sesión"
    print("OK  test_actividad_reemite_el_token")


def test_login_no_se_pisa_con_la_sesion_vieja():
    """Regresión del bug real: loguearse como plataforma y DESPUÉS como
    sindicato, en el mismo cliente (mismo navegador), tiene que dejar
    activo el rol nuevo -- no el viejo reemitido por encima."""
    client = TestClient(main.app)
    client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})
    r_plataforma = client.get("/plataforma")
    assert "Ingreso" not in r_plataforma.text or "Administración" in r_plataforma.text

    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    payload = auth.leer_sesion(client.cookies.get(main.COOKIE))
    assert payload["rol"] == "sindicato", payload
    r_admin = client.get("/admin")
    assert r_admin.status_code == 200
    assert "Reportes" in r_admin.text  # panel real, no el login
    print("OK  test_login_no_se_pisa_con_la_sesion_vieja")


def test_logout_no_se_revive():
    client = TestClient(main.app)
    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    client.get("/admin/salir", follow_redirects=False)
    payload = auth.leer_sesion(client.cookies.get(main.COOKIE, ""))
    assert payload is None, "logout tiene que dejar la sesión inválida, no reemitida"
    print("OK  test_logout_no_se_revive")


def test_expira_pasados_15_minutos_sin_uso():
    token_viejo = auth.crear_sesion("sindicato", sindicato_id=SID)
    # Firmado hace más de IDLE_TIMEOUT_SEGUNDOS -- construyo el payload a mano
    # con un timestamp viejo para no dormir el test 15 minutos de verdad.
    import base64, json, hmac, hashlib
    payload = {"rol": "sindicato", "uid": 0, "sid": SID,
               "t": int(time.time()) - auth.IDLE_TIMEOUT_SEGUNDOS - 5}
    cuerpo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    firma = hmac.new(auth.SECRETO.encode(), cuerpo.encode(), hashlib.sha256).hexdigest()[:32]
    token_expirado = f"{cuerpo}.{firma}"
    assert auth.leer_sesion(token_expirado) is None
    print("OK  test_expira_pasados_15_minutos_sin_uso")


if __name__ == "__main__":
    test_actividad_reemite_el_token()
    test_login_no_se_pisa_con_la_sesion_vieja()
    test_logout_no_se_revive()
    test_expira_pasados_15_minutos_sin_uso()
    print("\nTodo OK — sesión por inactividad.")
