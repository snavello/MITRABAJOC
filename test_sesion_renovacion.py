"""Sesión por inactividad (15 min, sliding window): cada request autenticado
renueva el token; después de 15 min sin uso, expira.

Bug real encontrado al construir esto: el middleware de renovación leía el
token del REQUEST entrante y lo reemitía sobre la respuesta -- si esa misma
respuesta era un login/logout que ya había puesto su propio Set-Cookie
(con el rol nuevo), la renovación lo pisaba con el rol VIEJO por encima,
así que loguearse con un rol distinto en la misma sesión de navegador nunca
"prendía" de verdad.

Correr con: .venv/Scripts/python.exe -m pytest test_sesion_renovacion.py -q
"""
import os
import time

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, CuentaTrabajador
import main
from fastapi.testclient import TestClient

db.crear_tablas()
CUIL_TRAB = "20111111119"
with db.get_session() as s:
    sind = Sindicato(nombre="Test Sesion", slug="test-sesion")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("clave-test"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID, cuil=CUIL_TRAB, nombre="Juan Trabajador", activo=True))
    s.add(CuentaTrabajador(cuil=CUIL_TRAB, clave_hash=auth.hashear_clave("demo1234")))
    s.commit()


def test_actividad_reemite_el_token():
    # OJO: si login y el siguiente request caen en el mismo segundo, el token
    # reemitido puede ser BYTE A BYTE igual al anterior (mismo payload, mismo
    # "t" truncado a entero) -- no es un bug, solo hace que comparar por
    # igualdad de string no sirva acá. Lo que importa es que el mecanismo
    # corrió: el response tiene que traer un Set-Cookie para la sesión.
    client = TestClient(main.app)
    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    assert client.cookies.get(main.COOKIE_SINDICATO)

    r = client.get("/admin")
    set_cookie = r.headers.get("set-cookie", "")
    assert set_cookie.startswith(f"{main.COOKIE_SINDICATO}="), "la renovación tiene que reemitir la cookie de sesión"
    print("OK  test_actividad_reemite_el_token")


def test_login_no_se_pisa_con_la_sesion_vieja():
    """Loguearse como plataforma y DESPUÉS como sindicato, en el mismo
    cliente (mismo navegador), tiene que dejar el rol nuevo funcionando --
    y con cookies separadas por rol (ver COOKIES_POR_ROL), la sesión de
    plataforma también sigue viva, no se pisan entre sí."""
    client = TestClient(main.app)
    client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})
    r_plataforma = client.get("/plataforma")
    assert "Ingreso" not in r_plataforma.text or "Administración" in r_plataforma.text

    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    payload = auth.leer_sesion(client.cookies.get(main.COOKIE_SINDICATO))
    assert payload["rol"] == "sindicato", payload
    r_admin = client.get("/admin")
    assert r_admin.status_code == 200
    assert "Reportes" in r_admin.text  # panel real, no el login
    print("OK  test_login_no_se_pisa_con_la_sesion_vieja")


def test_dos_pestanas_sindicato_y_trabajador_conviven():
    """Regresión del bug real reportado: admin de sindicato logueado en una
    pestaña, trabajador logueado en OTRA pestaña del mismo navegador (mismo
    "frasco" de cookies acá). Antes del fix de cookies separadas por rol,
    el segundo login pisaba la única cookie compartida y la pestaña de
    admin quedaba con sesión "perdida" al volver a usarla."""
    client = TestClient(main.app)
    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    r_admin_antes = client.get("/admin")
    assert r_admin_antes.status_code == 200 and "Reportes" in r_admin_antes.text

    client.post("/trabajador/login", data={"cuil": CUIL_TRAB, "clave": "demo1234"},
                follow_redirects=False)
    assert client.cookies.get(main.COOKIE_TRABAJADOR), "el login de trabajador tiene que haber prendido"

    r_admin_despues = client.get("/admin")
    assert r_admin_despues.status_code == 200, r_admin_despues.text
    assert "Reportes" in r_admin_despues.text, "la sesión de sindicato no debería haberse perdido"
    print("OK  test_dos_pestanas_sindicato_y_trabajador_conviven")


def test_dos_pestanas_plataforma_y_trabajador_conviven():
    """Mismo caso reportado, con plataforma en vez de sindicato."""
    client = TestClient(main.app)
    client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})
    r_plat_antes = client.get("/plataforma")
    assert r_plat_antes.status_code == 200
    assert "Ingreso" not in r_plat_antes.text or "Administración" in r_plat_antes.text

    client.post("/trabajador/login", data={"cuil": CUIL_TRAB, "clave": "demo1234"},
                follow_redirects=False)
    assert client.cookies.get(main.COOKIE_TRABAJADOR), "el login de trabajador tiene que haber prendido"

    r_plat_despues = client.get("/plataforma")
    assert r_plat_despues.status_code == 200
    assert "Ingreso" not in r_plat_despues.text or "Administración" in r_plat_despues.text
    print("OK  test_dos_pestanas_plataforma_y_trabajador_conviven")


def test_logout_no_se_revive():
    client = TestClient(main.app)
    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    client.get("/admin/salir", follow_redirects=False)
    payload = auth.leer_sesion(client.cookies.get(main.COOKIE_SINDICATO, ""))
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


# ---------- Pantalla fea al vencer la sesión (bug real, ver main.py:sesion_vencida_o_denegada) ----------
# Un <form> de admin.html/plataforma.html es POST de página completa, no
# fetch. Con la sesión vencida, la ruta tira 403 y el navegador reemplazaba
# TODA la pantalla por el JSON crudo -- solo se arreglaba reingresando a
# mano. El fix: con sesión inválida + navegación real (Accept: text/html),
# redirigir a la pantalla de login en vez de devolver el JSON.

def test_form_post_con_sesion_vencida_redirige_a_login_admin():
    client = TestClient(main.app)  # sin login -- simula sesión ya vencida/inexistente
    r = client.post("/admin/trabajador", data={"cuil": "20111111119", "nombre": "Juan"},
                     headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"
    print("OK  test_form_post_con_sesion_vencida_redirige_a_login_admin")


def test_form_post_con_sesion_vencida_redirige_a_login_plataforma():
    client = TestClient(main.app)
    r = client.post("/plataforma/config", data={"tope_sindical_pct": "2.0"},
                     headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/plataforma"
    print("OK  test_form_post_con_sesion_vencida_redirige_a_login_plataforma")


def test_llamada_fetch_con_sesion_vencida_sigue_devolviendo_json():
    # Sin Accept: text/html (fetch() sin headers manda "*/*" por default) --
    # el JS que llama a esto sabe leer JSON, no hay que redirigirlo.
    client = TestClient(main.app)
    r = client.post("/admin/trabajador", data={"cuil": "20111111119", "nombre": "Juan"},
                     follow_redirects=False)
    assert r.status_code == 403
    assert r.json().get("detail")
    print("OK  test_llamada_fetch_con_sesion_vencida_sigue_devolviendo_json")


def test_403_legitimo_con_sesion_valida_no_redirige():
    """Sesión VÁLIDA pero acción no permitida: el redirect de sesión vencida
    no puede tragarse un 403 real.

    El discriminador es si la petición es una NAVEGACIÓN DE PÁGINA o una
    llamada de JS, no el status. Una llamada fetch tiene que seguir viendo
    el JSON: quien la lee es código, no una persona.

    (Antes este test usaba una navegación de página, y desde el sistema de
    Áreas ese caso cambió a propósito -- ver el test de abajo. El sindicato
    de la fixture no tiene módulos, así que su 403 viene del gateo por
    permiso y ya no es distinguible de "le falta el permiso".)"""
    client = TestClient(main.app)
    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    r = client.post("/admin/noticia", data={
        "titulo": "Aviso", "bajada": "", "texto_completo": "",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
    }, headers={"accept": "application/json", "x-requested-with": "fetch"},
       follow_redirects=False)
    assert r.status_code == 403
    assert r.json().get("detail")
    print("OK  test_403_legitimo_con_sesion_valida_no_redirige")


def test_falta_de_permiso_en_navegacion_vuelve_al_panel_con_aviso():
    """Entrada 2 del BACKLOG, cerrada por la Fase 6 de SPRINT_AREAS_V2.md.

    Un POST de página completa rechazado por falta de PERMISO devolvía el
    JSON de FastAPI a pantalla completa. Con muchos más usuarios acotados,
    la chance de que alguien llegue a un formulario que no le corresponde
    subió bastante, y comerse el JSON crudo es la peor forma de enterarse."""
    client = TestClient(main.app)
    client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})
    r = client.post("/admin/noticia", data={
        "titulo": "Aviso", "bajada": "", "texto_completo": "",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
    }, headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    assert r.status_code == 303
    assert "err=sinpermiso" in r.headers.get("location", "")
    print("OK  test_falta_de_permiso_en_navegacion_vuelve_al_panel_con_aviso")


if __name__ == "__main__":
    test_actividad_reemite_el_token()
    test_login_no_se_pisa_con_la_sesion_vieja()
    test_dos_pestanas_sindicato_y_trabajador_conviven()
    test_dos_pestanas_plataforma_y_trabajador_conviven()
    test_logout_no_se_revive()
    test_expira_pasados_15_minutos_sin_uso()
    test_form_post_con_sesion_vencida_redirige_a_login_admin()
    test_form_post_con_sesion_vencida_redirige_a_login_plataforma()
    test_llamada_fetch_con_sesion_vencida_sigue_devolviendo_json()
    test_403_legitimo_con_sesion_valida_no_redirige()
    test_falta_de_permiso_en_navegacion_vuelve_al_panel_con_aviso()
    print("\nTodo OK — sesión por inactividad.")
