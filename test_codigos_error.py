"""Cada error que ve una persona viaja con su código propio, y el mensaje de
"probá con otra foto" es SOLO de los dos errores reales de lectura.

Contexto (2026-08-26): antes, cualquier excepción de cualquier ruta salía con
el mismo texto ("No pudimos verificar este recibo. Probá con una foto más
nítida o el PDF"), así que era imposible saber qué había pasado sin leer el
log del servidor -- y encima mandaba a sacar la foto de nuevo por errores que
no tenían nada que ver con la foto.

Correr con: .venv/Scripts/python.exe -m pytest test_codigos_error.py -q
"""


import db
from db import Sindicato, Trabajador
import errores
import main
import auth
from fastapi.testclient import TestClient

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Codigos", slug="test-codigos")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119"))
    db.guardar_datos_personales(s, "20111111119", nombre="Tester")
    s.commit()

client = TestClient(main.app, raise_server_exceptions=False)
client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", ident="20111111119"))
client.cookies.set("cuil_trab", "20111111119")

RECIBO = {"empleado": {"cuil": "20111111119"}, "periodo": "2025-04",
          "lineas": [], "totales_impresos": {}}


def test_catalogo_es_coherente():
    for codigo, (status, mensaje) in errores.MENSAJES.items():
        assert codigo.startswith("E-"), codigo
        assert 400 <= status <= 599, (codigo, status)
        assert len(mensaje) > 20, codigo
    print("OK  test_catalogo_es_coherente")


def test_la_foto_solo_la_mencionan_los_errores_de_lectura():
    # La regla que originó todo esto: ningún otro error puede mandar a sacar
    # otra foto o subir otro archivo.
    con_foto = {c for c, (_, m) in errores.MENSAJES.items()
                if "foto" in m.lower() or "captura" in m.lower()}
    lectura = {"E-RECIBO-01", "E-RECIBO-02", "E-APORTE-01", "E-APORTE-02"}
    assert con_foto and con_foto <= lectura, con_foto
    print("OK  test_la_foto_solo_la_mencionan_los_errores_de_lectura")


def test_error_de_lectura_devuelve_su_codigo(monkeypatch=None):
    original = main.extraer
    main.extraer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("IA caída"))
    try:
        r = client.post("/api/leer", files={"archivo": ("r.pdf", b"%PDF-x", "application/pdf")})
    finally:
        main.extraer = original
    assert r.status_code == 422, r.status_code
    assert r.json()["codigo"] == "E-RECIBO-01", r.json()
    print("OK  test_error_de_lectura_devuelve_su_codigo")


def test_error_inesperado_al_verificar_no_habla_de_la_foto():
    original = main.validar
    main.validar = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("lo que sea"))
    try:
        r = client.post("/api/validar", json={"recibo": RECIBO, "conceptos_nuevos": []})
    finally:
        main.validar = original
    cuerpo = r.json()
    assert r.status_code == 500, r.status_code
    # el recibo YA se había leído bien: mandar a sacar otra foto sería mentira
    assert cuerpo["codigo"] == "E-RECIBO-03", cuerpo
    assert "foto" not in cuerpo["detail"].lower(), cuerpo
    assert len(cuerpo["ref"]) == 8, cuerpo   # referencia para buscar en el log
    print("OK  test_error_inesperado_al_verificar_no_habla_de_la_foto")


def test_error_inesperado_en_otra_ruta_cae_en_e_interno():
    original = db.recibos_verificados_de if hasattr(db, "recibos_verificados_de") else None
    r = client.post("/api/notificacion/999999/leer")
    # esa notificación no existe: la ruta responde con su propio HTTPException,
    # no con el genérico -- lo que importa es que el cuerpo tenga la clave
    # "codigo" siempre, aunque valga null.
    assert "codigo" in r.json(), r.json()
    assert errores.codigo_de_ruta("/api/lo-que-sea") == "E-INTERNO-00"
    print("OK  test_error_inesperado_en_otra_ruta_cae_en_e_interno")


def test_error_app_toma_status_y_mensaje_del_catalogo():
    e = errores.ErrorApp("E-SESION-01")
    assert e.status_code == 400 and e.codigo == "E-SESION-01"
    assert "sindicato" in e.detail.lower()
    print("OK  test_error_app_toma_status_y_mensaje_del_catalogo")


if __name__ == "__main__":
    test_catalogo_es_coherente()
    test_la_foto_solo_la_mencionan_los_errores_de_lectura()
    test_error_de_lectura_devuelve_su_codigo()
    test_error_inesperado_al_verificar_no_habla_de_la_foto()
    test_error_inesperado_en_otra_ruta_cae_en_e_interno()
    test_error_app_toma_status_y_mensaje_del_catalogo()
    print("\nTodo OK — cada error tiene código y solo los de lectura hablan de la foto.")
