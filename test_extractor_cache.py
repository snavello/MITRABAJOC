"""Caché de prompt del extractor (EXTRACTOR_CACHE) y su costo.

Correr con: python -m pytest test_extractor_cache.py -q
"""
import json
from types import SimpleNamespace

import db
import extractor
import precios_ia

IMG = ("QUJD", "image/png")
JSON_OK = json.dumps({"confianza": "alta"})


def _cliente(monkeypatch, capturas, cache_lectura=0, cache_escritura=0):
    def create(**kw):
        capturas.append(kw)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=JSON_OK)], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50,
                                  cache_read_input_tokens=cache_lectura,
                                  cache_creation_input_tokens=cache_escritura))
    monkeypatch.setattr(extractor, "client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.delenv("MOCK_EXTRACTOR", raising=False)


def test_sin_cache_el_pedido_es_el_de_siempre(monkeypatch):
    cap = []
    _cliente(monkeypatch, cap)
    monkeypatch.setenv("EXTRACTOR_CACHE", "0")
    extractor.extraer(b"", "image/png", "claude-sonnet-5-5", imagen=IMG, aviso_enmascarado=True)
    kw = cap[0]
    assert kw["system"] == extractor.SYSTEM and isinstance(kw["system"], str)
    cont = kw["messages"][0]["content"]
    assert [c["type"] for c in cont] == ["image", "text", "text"]
    assert cont[1]["text"] == extractor.ESQUEMA and cont[2]["text"] == extractor.AVISO_ENMASCARADO
    assert "cache_control" not in json.dumps(kw)


def test_sin_variable_es_como_apagado(monkeypatch):
    cap = []
    _cliente(monkeypatch, cap)
    monkeypatch.delenv("EXTRACTOR_CACHE", raising=False)
    extractor.extraer_aportes(b"", "image/png", "claude-sonnet-5-5", imagen=IMG)
    kw = cap[0]
    assert kw["system"] == extractor.SYSTEM_APORTES
    assert kw["messages"][0]["content"][1]["text"] == extractor.ESQUEMA_APORTES


def test_con_cache_el_esquema_va_al_system(monkeypatch):
    cap = []
    _cliente(monkeypatch, cap)
    monkeypatch.setenv("EXTRACTOR_CACHE", "1")
    extractor.extraer(b"", "image/png", "claude-sonnet-5-5", imagen=IMG, aviso_enmascarado=True)
    kw = cap[0]
    assert kw["system"] == [
        {"type": "text", "text": extractor.SYSTEM},
        {"type": "text", "text": extractor.ESQUEMA, "cache_control": {"type": "ephemeral"}}]
    cont = kw["messages"][0]["content"]
    assert [c["type"] for c in cont] == ["image", "text"]
    assert cont[1]["text"] == extractor.AVISO_ENMASCARADO
    cap.clear()
    extractor.extraer_aportes(b"", "image/png", "claude-sonnet-5-5", imagen=IMG)
    kw = cap[0]
    assert kw["system"][1]["text"] == extractor.ESQUEMA_APORTES
    assert kw["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert [c["type"] for c in kw["messages"][0]["content"]] == ["image"]


def test_el_uso_trae_los_tokens_de_cache(monkeypatch):
    cap = []
    _cliente(monkeypatch, cap, cache_lectura=1900, cache_escritura=0)
    monkeypatch.setenv("EXTRACTOR_CACHE", "1")
    _, uso = extractor.extraer(b"", "image/png", "claude-sonnet-5-5", imagen=IMG)
    assert uso["tokens_cache_lectura"] == 1900 and uso["tokens_cache_escritura"] == 0
    assert uso["tokens_entrada"] == 100


def test_mock_da_cero(monkeypatch):
    monkeypatch.setenv("MOCK_EXTRACTOR", "1")
    monkeypatch.setenv("MOCK_EXTRACTOR_LATENCIA", "0")
    _, uso = extractor.extraer(b"", "image/png")
    assert uso["tokens_cache_lectura"] == 0 and uso["tokens_cache_escritura"] == 0


def test_costo_con_multiplicadores_de_cache():
    # 1M de cada cosa a US$ 3 / 15: 3 + 0,3 + 3,75 + 15
    c = precios_ia.costo(1_000_000, 1_000_000, 3.0, 15.0, 1_000_000, 1_000_000)
    assert abs(c - (3.0 + 0.3 + 3.75 + 15.0)) < 1e-9
    assert precios_ia.costo(1000, 100, 3.0, 15.0) == (1000 * 3 + 100 * 15) / 1e6


def test_registrar_uso_guarda_los_tokens_de_cache():
    db.crear_tablas()
    db.registrar_uso_ia(None, "", "prueba", "claude-sonnet-5-5", 100, 50, 1234, 1900, 0)
    fila = db.uso_ia_listado()[0]
    assert fila["tokens_cache_lectura"] == 1900 and fila["tokens_cache_escritura"] == 0
    p = precios_ia.precios("claude-sonnet-5-5")
    esperado = precios_ia.costo(100, 50, p[0], p[1], 1900, 0)
    assert abs(fila["costo"] - esperado) < 1e-12
