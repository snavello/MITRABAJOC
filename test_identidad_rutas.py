"""Verificación de identidad (Herramientas de /entornos): las rutas. La red a
Didit se reemplaza por una respuesta simulada; el motor se prueba aparte en
test_identidad.py.

Correr con: python -m pytest test_identidad_rutas.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient

import auth
import db
import entorno
import identidad
import main

db.crear_tablas()
API = "/api/entornos/herramientas/identidad"
PAGINA = "/entornos/herramientas/identidad"
JPG = b"\xff\xd8\xff\xe0fake"

DATOS = {"cuil": "20-20279041-1", "dni": "20279041", "nombre": "Juan Pablo", "apellido": "Pérez",
         "nacimiento": "1990-01-15", "genero": "M"}


def _con_plataforma(usuario="snavello"):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident=usuario))
    return c


def _archivos(con_dorso=False, tipo="image/jpeg"):
    f = {"selfie": ("s.jpg", JPG, "image/jpeg"), "frente": ("f.jpg", JPG, tipo)}
    if con_dorso:
        f["dorso"] = ("d.jpg", JPG, "image/jpeg")
    return f


def _didit_simulado(ruta, campos, archivos):
    if ruta == "/id-verification/":
        return {"id_verification": {"status": "Approved", "document_number": "20279041", "first_name": "JUAN PABLO",
                                    "last_name": "PEREZ", "date_of_birth": "1990-01-15", "expiration_date": "2099-01-01",
                                    "warnings": []}}
    if ruta == "/passive-liveness/":
        return {"liveness": {"status": "Approved", "score": 98, "warnings": []}}
    if ruta == "/face-match/":
        return {"face_match": {"status": "Approved", "score": 90, "warnings": []}}
    if ruta == "/database-validation/":
        return {"database_validation": {"status": "Approved", "match_type": "full_match", "match_score": 100,
                                        "validations": {"identification_number": "full_match"}, "warnings": []}}
    raise AssertionError(ruta)


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setenv("DIDIT_API_KEY", "sk_test_prueba")
    monkeypatch.delenv("IDENTIDAD_TOPE_INTENTOS", raising=False)
    monkeypatch.setattr(identidad, "_post", _didit_simulado)
    identidad.reiniciar_intentos()
    yield
    identidad.reiniciar_intentos()


def test_sin_pase_no_se_ve():
    c = TestClient(main.app)
    assert c.get(API + "/estado").status_code == 403
    assert c.get(API + "/casos").status_code == 403
    assert c.post(API + "/verificar", data=DATOS, files=_archivos()).status_code == 403
    r = c.get(PAGINA, headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = _con_plataforma()
    for ruta in (PAGINA, API + "/estado", API + "/casos"):
        assert c.get(ruta).status_code == 404
    assert c.post(API + "/verificar", data=DATOS, files=_archivos()).status_code == 404


def test_la_pagina_y_el_estado():
    c = _con_plataforma()
    assert c.get(PAGINA).status_code == 200
    e = c.get(API + "/estado").json()
    assert e["configurado"] and e["sandbox"] and e["tope_intentos"] == 5
    assert [p["clave"] for p in e["pasos"]] == ["local", "documento", "vida", "cara", "renaper"]


def test_sin_clave_no_verifica(monkeypatch):
    monkeypatch.delenv("DIDIT_API_KEY", raising=False)
    r = _con_plataforma().post(API + "/verificar", data=DATOS, files=_archivos())
    assert r.status_code == 422 and "DIDIT_API_KEY" in r.json()["detail"]


def test_verificar_aprueba_y_guarda_el_caso_sin_datos_personales():
    c = _con_plataforma()
    r = c.post(API + "/verificar", data={**DATOS, "nota": "selfie con luz"}, files=_archivos(con_dorso=True))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["veredicto"]["resultado"] == "aprobable" and d["llamadas_pagas"] == 4 and d["sandbox"] is True
    assert d["intentos"] == {"usados": 1, "tope": 5}
    caso = db.caso_herramienta("identidad", d["id"])
    assert caso and caso.quien == "snavello" and caso.grilla == "sandbox" and caso.nota == "selfie con luz"
    guardado = repr((caso.entrada, caso.real, caso.nota))
    for secreto in ("20279041", "Pérez", "PEREZ", "Juan", "JUAN", "1990-01-15"):
        assert secreto not in guardado, secreto
    lista = c.get(API + "/casos").json()["casos"]
    assert lista[0]["id"] == d["id"] and lista[0]["veredicto"] == "aprobable"


def test_un_dni_que_no_es_del_cuil_rechaza_sin_gastar(monkeypatch):
    llamadas = []
    monkeypatch.setattr(identidad, "_post", lambda *a: llamadas.append(a))
    r = _con_plataforma().post(API + "/verificar", data={**DATOS, "dni": "11111111"}, files=_archivos())
    assert r.status_code == 200 and r.json()["veredicto"]["resultado"] == "rechazar"
    assert llamadas == [] and r.json()["llamadas_pagas"] == 0
    assert r.json()["intentos"]["usados"] == 0


def test_tope_de_intentos(monkeypatch):
    monkeypatch.setenv("IDENTIDAD_TOPE_INTENTOS", "1")
    c = _con_plataforma()
    assert c.post(API + "/verificar", data=DATOS, files=_archivos()).status_code == 200
    r = c.post(API + "/verificar", data=DATOS, files=_archivos())
    assert r.status_code == 429


def test_archivos_invalidos():
    c = _con_plataforma()
    assert c.post(API + "/verificar", data=DATOS, files={"selfie": ("s.jpg", JPG, "image/jpeg")}).status_code == 422
    r = c.post(API + "/verificar", data=DATOS, files={"selfie": ("s.gif", JPG, "image/gif"),
                                                       "frente": ("f.jpg", JPG, "image/jpeg")})
    assert r.status_code == 422 and "formato" in r.json()["detail"]
    grande = b"x" * (identidad.TOPE_CARA_BYTES + 1)
    r = c.post(API + "/verificar", data=DATOS, files={"selfie": ("s.jpg", grande, "image/jpeg"),
                                                       "frente": ("f.jpg", JPG, "image/jpeg")})
    assert r.status_code == 422 and "pesa" in r.json()["detail"]


def test_pasos_pedidos_y_cambio_de_estado():
    c = _con_plataforma()
    r = c.post(API + "/verificar", data={**DATOS, "pasos": ["vida"]}, files=_archivos())
    d = r.json()
    assert r.status_code == 200 and d["llamadas_pagas"] == 1
    assert c.post(f"{API}/casos/{d['id']}/estado", json={"estado": "revisado"}).status_code == 200
    assert c.post(f"{API}/casos/{d['id']}/estado", json={"estado": "raro"}).status_code == 422
    assert c.post(f"{API}/casos/999999/estado", json={"estado": "revisado"}).status_code == 404
