"""Web Push de trámites: suscripción (CRUD + ruta), clave pública, y que
el gancho sea un no-op inofensivo sin claves VAPID configuradas.

El envío real contra un servicio de push no se prueba acá (necesita un
navegador de verdad); sí se prueba que un endpoint inalcanzable no tumba
nada. Correr con: .venv/Scripts/python.exe -m pytest test_push.py -q
"""


import db
import auth
import push
from db import Sindicato, Trabajador
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient

db.crear_tablas()
with db.get_session() as s:
    uom = Sindicato(nombre="UOM Push", slug="uom-push",
                    modulos_habilitados=list(MODULOS_INICIALES) + ["tramites"])
    s.add(uom); s.commit(); s.refresh(uom)
    SID = uom.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119",
                     activo=True, registrado=True))
    db.guardar_datos_personales(s, "20111111119", nombre="Juan")
    s.commit()


def _trab():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident="20111111119"))
    c.cookies.set("cuil_trab", "20111111119")
    return c


def test_sin_claves_todo_apagado():
    # entorno de test sin VAPID_*: el push está apagado y NADA explota
    assert not push.habilitado()
    push.notificar_tramite("20111111119", "F01-2026-000001", "hola")  # no-op
    r = _trab().get("/api/push/clave-publica")
    assert r.status_code == 200 and r.json()["clave"] == ""
    print("OK  test_sin_claves_todo_apagado")


def test_suscripcion_crud_y_ruta():
    trab = _trab()
    r = trab.post("/api/push/suscribir", json={
        "endpoint": "https://push.example/abc123",
        "keys": {"p256dh": "clave-p", "auth": "clave-a"},
    })
    assert r.status_code == 200
    subs = db.suscripciones_push_de("20111111119")
    assert len(subs) == 1 and subs[0]["endpoint"] == "https://push.example/abc123"

    # idempotente: mismo endpoint no duplica
    trab.post("/api/push/suscribir", json={
        "endpoint": "https://push.example/abc123",
        "keys": {"p256dh": "clave-p2", "auth": "clave-a2"},
    })
    subs = db.suscripciones_push_de("20111111119")
    assert len(subs) == 1 and subs[0]["p256dh"] == "clave-p2"

    # suscripción incompleta: 400
    assert trab.post("/api/push/suscribir", json={"endpoint": "x"}).status_code == 400
    # sin sesión: 403
    assert TestClient(main.app).post("/api/push/suscribir", json={}).status_code == 403

    # desuscribir borra
    trab.post("/api/push/desuscribir", json={"endpoint": "https://push.example/abc123"})
    assert db.suscripciones_push_de("20111111119") == []
    print("OK  test_suscripcion_crud_y_ruta")


def test_envio_con_endpoint_inalcanzable_no_tumba():
    # habilitar con claves reales de prueba y mandar a un endpoint que no
    # existe: el hilo de envío tiene que tragarse el error y seguir.
    from py_vapid import Vapid01, b64urlencode
    v = Vapid01(); v.generate_keys()
    push.VAPID_PRIVATE_KEY = b64urlencode(
        v.private_key.private_numbers().private_value.to_bytes(32, "big"))
    push.VAPID_PUBLIC_KEY = "clave-publica"
    push.VAPID_CLAIM_EMAIL = "test@example.com"
    assert push.habilitado()
    push._enviar_a_suscripciones(
        [{"endpoint": "https://127.0.0.1:1/inexistente", "p256dh": "BOb" + "A" * 84, "auth": "B" * 22}],
        '{"titulo":"x"}')  # síncrono a propósito: si lanzara, el test falla
    push.VAPID_PRIVATE_KEY = push.VAPID_PUBLIC_KEY = push.VAPID_CLAIM_EMAIL = ""
    print("OK  test_envio_con_endpoint_inalcanzable_no_tumba")


if __name__ == "__main__":
    test_sin_claves_todo_apagado()
    test_suscripcion_crud_y_ruta()
    test_envio_con_endpoint_inalcanzable_no_tumba()
    print("\nTodo OK — web push.")
