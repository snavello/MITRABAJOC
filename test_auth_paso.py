"""`auth.firmar_paso` / `auth.leer_paso`: el token que lleva el estado entre
pasos del registro, la recuperación de clave y la confirmación de mail.
No es una sesión y una sesión no lo reemplaza."""
import time

import auth


def test_ida_y_vuelta():
    tok = auth.firmar_paso({"cuil": "20111111112", "codigo_id": 7}, minutos=5, proposito="registro")
    assert auth.leer_paso(tok, "registro") == {"cuil": "20111111112", "codigo_id": 7}


def test_el_proposito_tiene_que_coincidir():
    tok = auth.firmar_paso({"cuil": "1"}, proposito="registro")
    assert auth.leer_paso(tok, "recuperacion") is None
    assert auth.leer_paso(tok, "") is None


def test_una_sesion_no_es_un_token_de_paso_ni_al_reves():
    ses = auth.crear_sesion("trabajador", ident="20111111112")
    assert auth.leer_paso(ses, "") is None
    tok = auth.firmar_paso({"cuil": "20111111112"}, proposito="registro")
    assert auth.leer_sesion(tok) is None


def test_firma_alterada_y_basura():
    tok = auth.firmar_paso({"cuil": "1"}, proposito="x")
    cuerpo, firma = tok.rsplit(".", 1)
    assert auth.leer_paso(cuerpo + "." + ("0" if firma[0] != "0" else "1") + firma[1:], "x") is None
    assert auth.leer_paso("", "x") is None
    assert auth.leer_paso("sin-punto", "x") is None
    assert auth.leer_paso("a.b", "x") is None


def test_vence(monkeypatch):
    tok = auth.firmar_paso({"cuil": "1"}, minutos=1, proposito="x")
    ahora = time.time()
    monkeypatch.setattr(time, "time", lambda: ahora + 61)
    assert auth.leer_paso(tok, "x") is None


def test_firmar_paso_exige_un_dict():
    """Los datos se leen como dict o no se leen: firmar otra cosa es un error de
    programación y tiene que saltar acá, no meses después al leerlo."""
    import pytest
    for raro in (["a"], "texto", 5, None):
        with pytest.raises(TypeError):
            auth.firmar_paso(raro, proposito="x")


def test_leer_paso_exige_el_proposito():
    """Sin default: quien lee tiene que decir qué flujo espera."""
    import pytest
    tok = auth.firmar_paso({"a": 1}, proposito="registro")
    with pytest.raises(TypeError):
        auth.leer_paso(tok)
    assert auth.leer_paso(tok, "registro") == {"a": 1}
