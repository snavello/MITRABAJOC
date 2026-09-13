"""Red de seguridad: cualquier excepción no prevista tiene que devolver JSON
(no el 500 de texto plano de Starlette, que rompe el `await r.json()` del
frontend con "unexpected token"). Encontrado en producción: una foto de mala
calidad generó un recibo con algún campo raro que rompió /api/validar.

Correr con: .venv/Scripts/python.exe -m pytest test_error_no_manejado.py -q
"""


import db
import auth
from db import Sindicato, Trabajador, UsuarioSindicato
import main
from fastapi.testclient import TestClient

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Error", slug="test-error")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan",
                      activo=True, registrado=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("clave-test"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

client = TestClient(main.app, raise_server_exceptions=False)
client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
client.cookies.set("cuil_trab", "20111111119")


def test_excepcion_no_prevista_devuelve_json_no_texto_plano():
    original = main.validar

    def _validar_roto(*a, **kw):
        raise ValueError("importe no numérico, boom")
    main.validar = _validar_roto
    try:
        r = client.post("/api/validar", json={
            "recibo": {"periodo": "2026-08", "empleado": {"cuil": "20111111119"},
                       "empleador": {"nombre": "X", "cuit": None}, "lineas": [],
                       "totales_impresos": {}},
            "conceptos_nuevos": [],
        })
    finally:
        main.validar = original

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json"), r.headers["content-type"]
    body = r.json()  # no debe tirar "unexpected token" -- si esto no explota, ya probamos el punto
    assert "detail" in body and body["detail"]
    print("OK  test_excepcion_no_prevista_devuelve_json_no_texto_plano")


def test_httpexception_normal_no_se_pisa():
    """Una HTTPException a propósito (ej. sindicato no resuelto) tiene que
    seguir devolviendo SU status/detail -- el handler global no se mete."""
    client_sin_sid = TestClient(main.app, raise_server_exceptions=False)
    client_sin_sid.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    # sin cuil_trab: sindicato_activo_trabajador() no resuelve nada -> 400 a propósito
    r = client_sin_sid.post("/api/validar", json={"recibo": {}, "conceptos_nuevos": []})
    assert r.status_code == 400
    assert "sindicato" in r.json()["detail"].lower()
    print("OK  test_httpexception_normal_no_se_pisa")


# ---------- 500 en un POST de página completa (bug real: JSON crudo en pantalla) ----------
# Un <form> de /admin es página completa, no fetch. Si la ruta explota con
# una excepción no prevista (ej. un hipo transitorio de la base), antes se
# veía TODO el JSON crudo en pantalla -- ahora vuelve al panel con un aviso.

def test_500_en_post_de_pagina_completa_redirige_con_aviso():
    admin_client = TestClient(main.app, raise_server_exceptions=False)
    admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})

    original = db.get_session

    def _get_session_roto():
        raise ConnectionError("conexión a la base perdida (simulado)")
    db.get_session = _get_session_roto
    try:
        # El alta valida el domicilio ANTES de tocar la base: sin provincia ni
        # localidad volvería por la validación y no por el error simulado.
        r = admin_client.post("/admin/trabajador",
                               data={"cuil": "20111111119", "nombre": "Juan",
                                     "provincia": "Santa Fe", "localidad": "Rosario"},
                               headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    finally:
        db.get_session = original

    assert r.status_code == 303
    # la referencia (E-INTERNO-00 ref=...) viaja en la URL para que el aviso
    # de la pantalla y el traceback del log se puedan cruzar -- ver errores.py
    destino = r.headers["location"]
    assert destino.startswith("/admin?error=guardado&ref="), destino
    assert len(destino.rsplit("=", 1)[1]) == 8, destino
    print("OK  test_500_en_post_de_pagina_completa_redirige_con_aviso")


def test_500_en_llamada_fetch_sigue_devolviendo_json():
    # Sin Accept: text/html (fetch() sin headers manda "*/*") -- el JS que
    # llama a esto sabe leer el JSON, no hay que redirigirlo a ningún lado.
    admin_client = TestClient(main.app, raise_server_exceptions=False)
    admin_client.post("/admin/login", data={"usuario": "20111111110", "clave": "clave-test"})

    original = db.get_session

    def _get_session_roto():
        raise ConnectionError("conexión a la base perdida (simulado)")
    db.get_session = _get_session_roto
    try:
        r = admin_client.post("/admin/trabajador",
                               data={"cuil": "20111111119", "nombre": "Juan",
                                     "provincia": "Santa Fe", "localidad": "Rosario"},
                               follow_redirects=False)
    finally:
        db.get_session = original

    assert r.status_code == 500
    assert r.json().get("detail")
    print("OK  test_500_en_llamada_fetch_sigue_devolviendo_json")


if __name__ == "__main__":
    test_excepcion_no_prevista_devuelve_json_no_texto_plano()
    test_httpexception_normal_no_se_pisa()
    test_500_en_post_de_pagina_completa_redirige_con_aviso()
    test_500_en_llamada_fetch_sigue_devolviendo_json()
    print("\nTodo OK — red de seguridad ante errores no manejados.")
