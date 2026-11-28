"""XSII, bloque 6: `xsii/METODO.md`, el método genérico (sin base de datos).

Verifica que el documento existe, que es genérico (las palabras del producto
solo aparecen en «Aplicación de referencia») y que todo archivo o carpeta que
nombra existe. Que el motor genérico no importe nada del producto ya lo
verifican `test_xsii_motor.py` (el motor) y `test_xsii_asistente.py` (el
asistente): no se duplica acá.

Correr con: python -m pytest test_xsii_metodo.py -q
"""
import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).parent
METODO = RAIZ / "xsii" / "METODO.md"
SECCION_FINAL = "## Aplicación de referencia"
PALABRAS_DEL_PRODUCTO = ("colm3na", "sindicato", "afiliado", "padron", "recibo", "bancaria")


def _plano(texto: str) -> str:
    n = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in n if not unicodedata.combining(c))


def _texto() -> str:
    return METODO.read_text(encoding="utf-8")


def _generico() -> str:
    texto = _texto()
    assert SECCION_FINAL in texto, "falta la sección «Aplicación de referencia»"
    return texto.split(SECCION_FINAL, 1)[0]


def test_el_metodo_existe_y_tiene_un_largo_razonable():
    assert METODO.is_file()
    lineas = _texto().count("\n") + 1
    assert 180 <= lineas <= 320, lineas


def test_la_aplicacion_de_referencia_es_la_ultima_seccion():
    texto = _texto()
    resto = texto.split(SECCION_FINAL, 1)[1]
    assert "\n## " not in resto, "después de «Aplicación de referencia» no va otra sección"


def test_fuera_de_la_aplicacion_de_referencia_no_aparece_el_producto():
    plano = _plano(_generico())
    for palabra in PALABRAS_DEL_PRODUCTO:
        assert palabra not in plano, f"«{palabra}» aparece en la parte genérica del método"


def test_no_hay_tablas():
    assert not re.search(r"^\|.*\|\s*$", _texto(), re.M), "el método no usa tablas (como xsk/METODO.md)"


def test_todo_archivo_o_carpeta_nombrado_existe():
    nombrados = [t for t in re.findall(r"`([^`\n]+)`", _texto())
                 if "/" in t and " " not in t and not any(c in t for c in "<>{}*()")
                 and not t.startswith(("/", "http"))]
    assert len(nombrados) >= 10, nombrados
    faltan = [t for t in nombrados
              if not (RAIZ / "xsii" / t).exists() and not (RAIZ / t).exists()]
    assert not faltan, f"el método nombra rutas que no existen: {faltan}"
