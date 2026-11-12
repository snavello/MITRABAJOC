"""MercadoPago de la Fiesta (mercadopago.py): modos, firma del webhook, mock y
la preferencia con la red simulada. Nada sale a internet.

Correr con: python -m pytest test_mercadopago.py -q
"""
import hashlib
import hmac
import io
import json

import pytest

import mercadopago


@pytest.fixture(autouse=True)
def _sin_variables(monkeypatch):
    for v in ("MP_ACCESS_TOKEN", "MP_WEBHOOK_SECRET", "MP_MOCK"):
        monkeypatch.delenv(v, raising=False)


# ---------- Modos ----------
def test_apagado_sin_variables():
    assert mercadopago.modo() == "apagado"
    assert not mercadopago.habilitado()
    assert mercadopago.crear_preferencia(1, "Fiesta", 1000, "https://x.test") is None
    assert mercadopago.obtener_pago("123") is None
    assert mercadopago.faltantes() == ["MP_ACCESS_TOKEN", "MP_WEBHOOK_SECRET"]


def test_modo_real_con_token(monkeypatch):
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")
    assert mercadopago.modo() == "real" and mercadopago.habilitado()
    assert mercadopago.faltantes() == ["MP_WEBHOOK_SECRET"]


def test_mock_gana_y_no_sale_a_la_red(monkeypatch):
    monkeypatch.setenv("MP_MOCK", "1")
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")
    assert mercadopago.modo() == "mock"

    def _no_red(*a, **k):
        raise AssertionError("el mock no debe usar la red")
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen", _no_red)
    pref = mercadopago.crear_preferencia(77, "Fiesta ×2", 60000, "http://localhost:8000/")
    assert pref == {"id": "MOCK-77", "init_point": "http://localhost:8000/fiesta/mp-simulado/77"}
    assert mercadopago.obtener_pago("MOCK-77-1") is None
    mercadopago.registrar_pago_mock("MOCK-77-1", "approved", 77, 60000)
    p = mercadopago.obtener_pago("MOCK-77-1")
    assert p["status"] == "approved" and p["external_reference"] == "77"
    assert p["transaction_amount"] == 60000.0


# ---------- Firma del webhook ----------
SECRETO = "clave_secreta_de_prueba"


def _firma_manual(data_id, request_id, ts, secreto=SECRETO):
    """Armada a mano con hmac/hashlib, sin pasar por el módulo: es la receta
    de la documentación (id;request-id;ts) calculada por afuera."""
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    return hmac.new(secreto.encode(), manifest.encode(), hashlib.sha256).hexdigest()


def test_firma_de_la_documentacion():
    # Vector fijo, calculado por afuera con la receta documentada (manifest
    # id;request-id;ts): si el módulo cambia el manifest, deja de coincidir.
    v1 = "9164404e371a917c32dd365417fd65d6fb00b635867f13cc6106d46299463416"
    assert _firma_manual("123456", "bb56a2f1-6aae-46ac-982e-9dcd3581d08e", "1742505638683") == v1
    assert mercadopago.validar_firma(f"ts=1742505638683,v1={v1}",
                                     "bb56a2f1-6aae-46ac-982e-9dcd3581d08e", "123456", SECRETO)


def test_firma_valida_y_variantes():
    v1 = _firma_manual("999", "req-1", "1700000000")
    assert mercadopago.validar_firma(f"ts=1700000000,v1={v1}", "req-1", "999", SECRETO)
    assert mercadopago.validar_firma(f"ts=1700000000, v1={v1}", "req-1", "999", SECRETO)   # espacios
    assert mercadopago.firmar("999", "req-1", "1700000000", SECRETO) == f"ts=1700000000,v1={v1}"


def test_firma_invalida_falla_cerrado():
    v1 = _firma_manual("999", "req-1", "1700000000")
    sig = f"ts=1700000000,v1={v1}"
    assert not mercadopago.validar_firma(sig, "req-1", "999", "otro-secreto")
    assert not mercadopago.validar_firma(sig, "req-OTRO", "999", SECRETO)
    assert not mercadopago.validar_firma(sig, "req-1", "1000", SECRETO)
    assert not mercadopago.validar_firma("ts=1700000001,v1=" + v1, "req-1", "999", SECRETO)
    assert not mercadopago.validar_firma("", "req-1", "999", SECRETO)
    assert not mercadopago.validar_firma("basura", "req-1", "999", SECRETO)
    assert not mercadopago.validar_firma(sig, "req-1", "", SECRETO)
    assert not mercadopago.validar_firma(sig, "req-1", "999", "")     # sin secreto configurado


def test_data_id_alfanumerico_va_en_minusculas():
    v1 = _firma_manual("abc123", "r", "5")
    assert mercadopago.validar_firma(f"ts=5,v1={v1}", "r", "ABC123", SECRETO)


# ---------- Preferencia con la red simulada ----------
class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_preferencia_real_arma_el_pedido(monkeypatch):
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-secreto-token")
    visto = {}

    def _urlopen(pedido, timeout=0):
        visto["url"] = pedido.full_url
        visto["auth"] = pedido.get_header("Authorization")
        visto["cuerpo"] = json.loads(pedido.data.decode())
        return _Respuesta(json.dumps({"id": "pref-1", "init_point": "https://mp.test/checkout/pref-1"}).encode())
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen", _urlopen)
    pref = mercadopago.crear_preferencia(42, "Fiesta ×3", 90000, "https://pruebas.test/",
                                         "2026-11-12T20:30:00.000-03:00")
    assert pref == {"id": "pref-1", "init_point": "https://mp.test/checkout/pref-1"}
    assert visto["url"] == "https://api.mercadopago.com/checkout/preferences"
    assert visto["auth"] == "Bearer TEST-secreto-token"
    c = visto["cuerpo"]
    assert c["items"] == [{"title": "Fiesta ×3", "quantity": 1, "unit_price": 90000, "currency_id": "ARS"}]
    assert c["external_reference"] == "42"
    assert c["notification_url"] == "https://pruebas.test/api/fiesta/mp/webhook"
    assert c["back_urls"]["success"] == "https://pruebas.test/fiesta/pago/vuelta?reserva=42&estado=success"
    assert c["auto_return"] == "approved" and c["expires"] is True
    assert c["expiration_date_to"] == "2026-11-12T20:30:00.000-03:00"


def test_preferencia_http_sin_auto_return(monkeypatch):
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")
    visto = {}

    def _urlopen(pedido, timeout=0):
        visto["cuerpo"] = json.loads(pedido.data.decode())
        return _Respuesta(json.dumps({"id": "p", "init_point": "https://mp.test/p"}).encode())
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen", _urlopen)
    assert mercadopago.crear_preferencia(1, "F", 10, "http://localhost:8000")
    assert "auto_return" not in visto["cuerpo"]


def test_preferencia_nunca_lanza(monkeypatch, caplog):
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-secreto-token")

    def _falla(*a, **k):
        raise OSError("sin red")
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen", _falla)
    assert mercadopago.crear_preferencia(1, "F", 10, "https://x.test") is None
    assert mercadopago.obtener_pago("123") is None
    assert "TEST-secreto-token" not in caplog.text            # el token nunca va al log
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen",
                        lambda *a, **k: _Respuesta(b"no es json"))
    assert mercadopago.crear_preferencia(1, "F", 10, "https://x.test") is None
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen",
                        lambda *a, **k: _Respuesta(b'{"id": "x"}'))
    assert mercadopago.crear_preferencia(1, "F", 10, "https://x.test") is None


def test_obtener_pago_real(monkeypatch):
    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-token")
    visto = {}

    def _urlopen(pedido, timeout=0):
        visto["url"] = pedido.full_url
        return _Respuesta(json.dumps({"id": 555, "status": "approved", "external_reference": "42",
                                      "transaction_amount": 30000.0}).encode())
    monkeypatch.setattr(mercadopago.urllib.request, "urlopen", _urlopen)
    assert mercadopago.obtener_pago("555") == {"id": "555", "status": "approved",
                                               "external_reference": "42", "transaction_amount": 30000.0}
    assert visto["url"] == "https://api.mercadopago.com/v1/payments/555"
    assert mercadopago.obtener_pago("../etc") is None          # el id viaja en la ruta
