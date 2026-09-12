"""Landing interna de entornos (GET /entornos) y la versión pública de cada
servicio (GET /api/version): los 8 accesos (4 logins x Pruebas/Demo) con su
versión, visible solo en local/pruebas (mismo criterio que el distintivo de
entorno.py), nunca en la demo. La landing entera está detrás de un PIN de
ocho dígitos (entorno.PIN_LANDING) que deja un pase de 30 días.

Correr con: .venv/Scripts/python.exe -m pytest test_entornos.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "24681357"   # antes de importar entorno

import entorno
import recursos
import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)
# El pase, una vez: el resto de los tests ven la landing entera.
assert client.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False).status_code == 303
assert recursos.COOKIE_PASE in client.cookies

LOGINS = ("/ingresar", "/admin", "/ingresar-empresa", "/plataforma")


def test_sin_pin_solo_se_ve_la_puerta():
    c = TestClient(main.app)
    r = c.get("/entornos")
    assert r.status_code == 200
    assert 'action="/entornos/pin"' in r.text and 'inputmode="numeric"' in r.text
    assert 'name="robots" content="noindex' in r.text
    assert 'id="distintivo-entorno"' in r.text
    # Nada de la landing real: ni un login ni un recurso.
    for base in entorno.URLS.values():
        assert base not in r.text
    assert "/recursos/" not in r.text
    # PIN equivocado: vuelve a la puerta con el aviso y sin cookie. Con
    # espacios o guiones, el correcto igual entra.
    r = c.post("/entornos/pin", data={"pin": "00000000"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entornos?aviso=pin"
    assert recursos.COOKIE_PASE not in r.cookies
    assert "Ese no es el código" in c.get("/entornos?aviso=pin").text
    r = c.post("/entornos/pin", data={"pin": "2468-1357"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entornos"
    assert recursos.COOKIE_PASE in r.cookies
    assert entorno.URLS["demo"] in c.get("/entornos").text
    print("OK  test_sin_pin_solo_se_ve_la_puerta")


def test_enlace_directo_pide_el_pin_y_despues_abre_ese_documento():
    # Compartir https://.../recursos/plan-maestro/archivo con alguien que
    # tiene el PIN: el clic cae en la puerta, que recuerda el destino, y el
    # PIN correcto abre el documento en vez de la landing.
    c = TestClient(main.app)
    navegador = {"Accept": "text/html,application/xhtml+xml"}
    r = c.get("/recursos/plan-maestro/archivo", headers=navegador, follow_redirects=False)
    assert r.status_code == 303
    puerta = r.headers["location"]
    assert puerta == "/entornos?siguiente=%2Frecursos%2Fplan-maestro%2Farchivo"
    r = c.get(puerta)
    assert r.status_code == 200
    assert 'name="siguiente" value="/recursos/plan-maestro/archivo"' in r.text
    assert "Después se abre el documento que pediste" in r.text
    # PIN equivocado: vuelve a la puerta y NO pierde el destino.
    r = c.post("/entornos/pin", data={"pin": "00000000", "siguiente": "/recursos/plan-maestro/archivo"},
               follow_redirects=False)
    assert r.headers["location"] == "/entornos?aviso=pin&siguiente=%2Frecursos%2Fplan-maestro%2Farchivo"
    assert 'name="siguiente" value="/recursos/plan-maestro/archivo"' in c.get(r.headers["location"]).text
    # PIN correcto: pase puesto y directo al documento.
    r = c.post("/entornos/pin", data={"pin": "24681357", "siguiente": "/recursos/plan-maestro/archivo"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/recursos/plan-maestro/archivo"
    assert recursos.COOKIE_PASE in r.cookies
    assert c.get("/recursos/plan-maestro/archivo").status_code == 200
    # La puerta no es una redirección abierta: solo /recursos/... de esta
    # app; cualquier otro destino se ignora y se va a la landing.
    for raro in ("https://otro.sitio/x", "//otro.sitio/x", "/recursos//otro.sitio", "/plataforma", "recursos/1/archivo"):
        c2 = TestClient(main.app)
        assert 'name="siguiente"' not in c2.get("/entornos", params={"siguiente": raro}).text, raro
        r = c2.post("/entornos/pin", data={"pin": "24681357", "siguiente": raro}, follow_redirects=False)
        assert r.headers["location"] == "/entornos", raro
    print("OK  test_enlace_directo_pide_el_pin_y_despues_abre_ese_documento")


def test_cinco_fallos_seguidos_hacen_esperar(monkeypatch):
    main._intentos_pin.clear()
    c = TestClient(main.app)
    for _ in range(main.PIN_MAX_FALLOS):
        r = c.post("/entornos/pin", data={"pin": "11111111"}, follow_redirects=False)
        assert r.headers["location"] == "/entornos?aviso=pin"
    # El sexto, aunque sea el correcto, espera.
    r = c.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False)
    assert r.headers["location"] == "/entornos?aviso=espera"
    assert recursos.COOKIE_PASE not in r.cookies
    assert "Demasiados intentos" in c.get("/entornos?aviso=espera").text
    # Pasado el minuto, entra.
    import time
    ahora = time.time()
    monkeypatch.setattr(time, "time", lambda: ahora + 10 ** 9)
    r = c.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False)
    assert r.headers["location"] == "/entornos" and recursos.COOKIE_PASE in r.cookies
    main._intentos_pin.clear()
    print("OK  test_cinco_fallos_seguidos_hacen_esperar")


def test_landing_con_los_ocho_accesos():
    r = client.get("/entornos")
    assert r.status_code == 200
    for base in entorno.URLS.values():
        for ruta in LOGINS:
            assert f'href="{base}{ruta}"' in r.text, (base, ruta)
    # Los dos entornos se anuncian con su nombre y su host, y nada de esto
    # tiene que terminar indexado por un buscador.
    assert "mitrabajo-pruebas.onrender.com" in r.text
    assert "mitrabajo.onrender.com" in r.text
    assert 'name="robots" content="noindex' in r.text
    assert 'id="distintivo-entorno"' in r.text      # es una página más de Pruebas
    print("OK  test_landing_con_los_ocho_accesos")


def test_landing_prellena_la_version_del_propio_entorno():
    # Servida desde Pruebas, las versiones de Pruebas salen en el HTML (sin
    # esperar al JS); las de la demo quedan para que el JS las pida.
    r = client.get("/entornos")
    assert f'data-version="pruebas:trabajador">v{main.VERSION_TRABAJADOR}<' in r.text
    assert f'data-version="pruebas:admin">v{main.VERSION_ADMIN}<' in r.text
    assert f'data-version="pruebas:plataforma">v{main.VERSION_PLATAFORMA}<' in r.text
    assert 'data-version="demo:trabajador">…<' in r.text
    # Empresa no tiene versión propia en version.py: se dice, no se inventa.
    assert 'data-version="pruebas:empresa"' in r.text and "sin versión propia" in r.text
    print("OK  test_landing_prellena_la_version_del_propio_entorno")


def test_api_version_es_publica_y_con_cors():
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"   # la lee el otro origen
    assert "no-store" in r.headers["cache-control"]
    v = r.json()
    assert v["entorno"] == "pruebas"
    assert v["trabajador"] == main.VERSION_TRABAJADOR
    assert v["admin"] == main.VERSION_ADMIN
    assert v["plataforma"] == main.VERSION_PLATAFORMA
    assert v["fecha"] == main.FECHA_VERSION
    print("OK  test_api_version_es_publica_y_con_cors")


def test_en_la_demo_la_landing_no_existe_pero_la_version_si(monkeypatch):
    # Mismo criterio que el distintivo: donde no se muestra, no hay landing.
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    monkeypatch.setattr(entorno, "ENTORNO", "demo")
    assert client.get("/entornos").status_code == 404
    assert client.post("/entornos/pin", data={"pin": "24681357"}).status_code == 404
    r = client.get("/api/version")               # esta sí: la landing de Pruebas la necesita
    assert r.status_code == 200 and r.json()["entorno"] == "demo"
    print("OK  test_en_la_demo_la_landing_no_existe_pero_la_version_si")


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
