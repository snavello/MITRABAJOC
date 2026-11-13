"""Acceso al Documento integrador por link directo con PIN propio
(/documento-integrador, `INTEGRADOR_PIN`). Quienes lo reciben no tienen
usuario: el PIN les deja un pase que abre SOLO este documento, que deja de
valer si cambia el PIN. Sin la variable, las rutas no existen (404).

Correr con: .venv/Scripts/python.exe -m pytest test_documento_integrador.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"            # antes de importar main
os.environ.pop("INTEGRADOR_PIN", None)

import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()
PIN = "48151623"


def _cliente():
    main._intentos_integrador.clear()
    return TestClient(main.app)


def test_sin_pin_configurado_no_existe(monkeypatch):
    monkeypatch.delenv("INTEGRADOR_PIN", raising=False)
    c = _cliente()
    assert c.get("/documento-integrador").status_code == 404
    assert c.post("/documento-integrador/pin", data={"pin": PIN}).status_code == 404


def test_sin_pase_muestra_la_puerta_y_no_el_documento(monkeypatch):
    monkeypatch.setenv("INTEGRADOR_PIN", PIN)
    r = _cliente().get("/documento-integrador")
    assert r.status_code == 200
    assert "Ingresá el PIN" in r.text
    assert "Uso interno" in r.text
    assert "cap-cab" not in r.text            # nada del documento sin el pase


def test_pin_incorrecto_vuelve_con_aviso(monkeypatch):
    monkeypatch.setenv("INTEGRADOR_PIN", PIN)
    c = _cliente()
    r = c.post("/documento-integrador/pin", data={"pin": "00000000"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("aviso=pin")
    assert main.INTEGRADOR_COOKIE not in r.cookies
    assert "no es correcto" in c.get(r.headers["location"]).text


def test_pin_correcto_abre_el_documento_con_cabeceras_cerradas(monkeypatch):
    monkeypatch.setenv("INTEGRADOR_PIN", PIN)
    c = _cliente()
    r = c.post("/documento-integrador/pin", data={"pin": f" {PIN} "}, follow_redirects=False)
    assert r.status_code == 303 and main.INTEGRADOR_COOKIE in r.cookies
    doc = c.get("/documento-integrador")
    assert doc.status_code == 200
    assert "Uso interno · Reservado" in doc.text          # el sello del documento
    assert doc.headers["content-security-policy"] == main.CSP_INTEGRADOR
    assert "no-store" in doc.headers["cache-control"]
    assert "noindex" in doc.headers["x-robots-tag"]


def test_el_pase_no_vale_si_cambia_el_pin(monkeypatch):
    monkeypatch.setenv("INTEGRADOR_PIN", PIN)
    c = _cliente()
    c.post("/documento-integrador/pin", data={"pin": PIN}, follow_redirects=False)
    monkeypatch.setenv("INTEGRADOR_PIN", "99887766")
    assert "Ingresá el PIN" in c.get("/documento-integrador").text


def test_el_pase_no_abre_entornos_ni_recursos(monkeypatch):
    monkeypatch.setenv("INTEGRADOR_PIN", PIN)
    c = _cliente()
    c.post("/documento-integrador/pin", data={"pin": PIN}, follow_redirects=False)
    assert "cap-cab" not in c.get("/recursos/documento-integrador/archivo").text
    assert "cap-cab" not in c.get("/entornos").text


def test_muchos_intentos_fallidos_hacen_esperar(monkeypatch):
    monkeypatch.setenv("INTEGRADOR_PIN", PIN)
    c = _cliente()
    for _ in range(main.LOGIN_MAX_FALLOS):
        c.post("/documento-integrador/pin", data={"pin": "1"}, follow_redirects=False)
    r = c.post("/documento-integrador/pin", data={"pin": PIN}, follow_redirects=False)
    assert r.headers["location"].endswith("aviso=espera")
    assert main.INTEGRADOR_COOKIE not in r.cookies
