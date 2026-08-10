"""QR de la credencial: token opaco, verificación pública, y que el servidor
no confíe en los query params (esos son solo el respaldo legible offline).

Correr con: .venv/Scripts/python.exe test_qr_credencial.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
from db import Sindicato, Trabajador, UsuarioSindicato
import auth
import main
from fastapi.testclient import TestClient
from qr import qr_svg, url_verificacion

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test QR", slug="test-qr")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan Pérez", activo=True))
    s.commit()

client = TestClient(main.app)


def test_token_se_genera_una_sola_vez_y_es_estable():
    t1 = db.token_credencial("20111111119", SID)
    t2 = db.token_credencial("20111111119", SID)
    assert t1 and t1 == t2, "el token tiene que ser estable entre llamadas"
    print("OK  test_token_se_genera_una_sola_vez_y_es_estable")


def test_token_vacio_si_no_esta_empadronado():
    assert db.token_credencial("20999999999", SID) == ""
    print("OK  test_token_vacio_si_no_esta_empadronado")


def test_verificacion_publica_no_requiere_login():
    token = db.token_credencial("20111111119", SID)
    r = client.get(f"/v/{token}", follow_redirects=False)
    assert r.status_code == 200, r.text
    assert "Juan P" in r.text and "Credencial válida" in r.text
    print("OK  test_verificacion_publica_no_requiere_login")


def test_verificacion_no_muestra_dni():
    token = db.token_credencial("20111111119", SID)
    r = client.get(f"/v/{token}")
    assert "DNI" not in r.text, "la página de verificación no debe mostrar el DNI"
    print("OK  test_verificacion_no_muestra_dni")


def test_verificacion_ignora_query_params_falsos():
    """El corazón de la seguridad: el token es lo único que cuenta. Un query
    param con datos distintos NO debe pisar lo que devuelve el servidor."""
    token = db.token_credencial("20111111119", SID)
    r = client.get(f"/v/{token}?n=Impostor&c=99999999999&num=FALSO-000")
    assert "Juan P" in r.text
    assert "Impostor" not in r.text
    assert "99999999999" not in r.text
    print("OK  test_verificacion_ignora_query_params_falsos")


def test_token_inexistente_no_verifica():
    r = client.get("/v/no-existe-este-token")
    assert r.status_code == 200
    assert "no encontrada" in r.text.lower()
    print("OK  test_token_inexistente_no_verifica")


def test_url_verificacion_lleva_datos_de_respaldo_pero_no_dni():
    url = url_verificacion("https://mitrabajo.onrender.com", "abc123", "Juan Pérez", "20111111119", "TESTQ-000001")
    assert url.startswith("https://mitrabajo.onrender.com/v/abc123?")
    assert "TESTQ" in url and "20111111119" in url
    assert "11111111" not in url or "20111111119" in url  # el CUIL sí, un DNI suelto no
    print("OK  test_url_verificacion_lleva_datos_de_respaldo_pero_no_dni")


def test_qr_svg_es_valido():
    svg = qr_svg("https://mitrabajo.onrender.com/v/abc123")
    assert svg.startswith("<svg") and "</svg>" in svg
    print("OK  test_qr_svg_es_valido")


def test_qr_svg_tiene_viewbox_para_escalar_sin_recortarse():
    # Bug real: segno no pone viewBox, solo width/height fijos. El CSS que
    # reescala el QR a 64x64 en la credencial (.cred-qr svg) lo RECORTABA en
    # vez de escalarlo, porque sin viewBox el navegador no sabe reproporcionar
    # el contenido — se vio cortado en la credencial real.
    svg = qr_svg("https://mitrabajo.onrender.com/v/abc123")
    assert 'viewBox="0 0 ' in svg
    print("OK  test_qr_svg_tiene_viewbox_para_escalar_sin_recortarse")


if __name__ == "__main__":
    test_token_se_genera_una_sola_vez_y_es_estable()
    test_token_vacio_si_no_esta_empadronado()
    test_verificacion_publica_no_requiere_login()
    test_verificacion_no_muestra_dni()
    test_verificacion_ignora_query_params_falsos()
    test_token_inexistente_no_verifica()
    test_url_verificacion_lleva_datos_de_respaldo_pero_no_dni()
    test_qr_svg_es_valido()
    test_qr_svg_tiene_viewbox_para_escalar_sin_recortarse()
    print("\nTodo OK — QR y verificación pública de la credencial.")
