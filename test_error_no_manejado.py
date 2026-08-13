"""Red de seguridad: cualquier excepción no prevista tiene que devolver JSON
(no el 500 de texto plano de Starlette, que rompe el `await r.json()` del
frontend con "unexpected token"). Encontrado en producción: una foto de mala
calidad generó un recibo con algún campo raro que rompió /api/validar.

Correr con: .venv/Scripts/python.exe test_error_no_manejado.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, Trabajador
import main
from fastapi.testclient import TestClient

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Error", slug="test-error")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan",
                      activo=True, registrado=True))
    s.commit()

client = TestClient(main.app, raise_server_exceptions=False)
client.cookies.set(main.COOKIE, auth.crear_sesion("trabajador", sindicato_id=0))
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
    client_sin_sid.cookies.set(main.COOKIE, auth.crear_sesion("trabajador", sindicato_id=0))
    # sin cuil_trab: sindicato_activo_trabajador() no resuelve nada -> 400 a propósito
    r = client_sin_sid.post("/api/validar", json={"recibo": {}, "conceptos_nuevos": []})
    assert r.status_code == 400
    assert "sindicato" in r.json()["detail"].lower()
    print("OK  test_httpexception_normal_no_se_pisa")


if __name__ == "__main__":
    test_excepcion_no_prevista_devuelve_json_no_texto_plano()
    test_httpexception_normal_no_se_pisa()
    print("\nTodo OK — red de seguridad ante errores no manejados.")
