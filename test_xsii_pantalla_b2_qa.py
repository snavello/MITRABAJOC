"""QA independiente de la pantalla del bloque 2 de XSII (estaticos; sin navegador)."""
import re
from pathlib import Path

CSS = Path("static/xsii/xsii.css").read_text(encoding="utf-8")
JS = Path("static/xsii/xsii.js").read_text(encoding="utf-8")


def _regla(selector: str) -> str:
    m = re.search(r"(?m)^" + re.escape(selector) + r"\{([^}]*)\}", CSS)
    assert m, selector
    return m.group(1)


def test_el_play_no_baja_cuando_preguntame_se_abre():
    # Con el cuadro de Preguntame abierto el heroe crece; centrado en vertical el Play queda a mitad del bloque.
    assert "align-items:center" not in _regla(".heroe")


def test_el_cuerpo_de_preguntame_no_se_reanima_en_cada_repintado():
    # replaceChildren recrea .pm-cuerpo en cada cambio de estado: con animation propia parpadea (opacidad 0) en
    # cada pregunta, espera y respuesta. La entrada tendria que aplicarse solo al abrir.
    assert "animation" not in _regla(".pm-cuerpo")


def test_el_reclamo_en_modo_respuesta_no_dice_crear():
    # En modo respuesta no se crea nada: se agrega un mensaje a una tarjeta existente.
    assert "Responder en la tarjeta" in JS or "Agregar a la tarjeta" in JS
