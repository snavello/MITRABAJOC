"""La hora de la app es la de Buenos Aires, no la del servidor (fechas.py).

El servidor de Render corre en UTC: tres horas adelante. Mientras la app usó
`datetime.now()` y `date.today()` crudos, toda vigencia por fecha terminaba
tres horas antes de lo que decía -- una noticia "hasta el 30" desaparecía a
las 21:00 del 30 -- y los sellos de tiempo quedaban guardados con la fecha
del día siguiente a partir de esa hora.

El último test es el que importa de acá a un año: recorre los módulos de la
app y falla nombrando al que vuelva a pedirle la hora al servidor. Es
fail-closed a propósito -- un archivo nuevo entra a la lista solo, sin que
nadie se acuerde de agregarlo.

Correr con: .venv/Scripts/python.exe test_fechas.py
"""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import fechas

RAIZ = Path(__file__).resolve().parent

# Lo que NO es la app: la suite, los scripts que corren en la PC del
# desarrollador (ya está en hora de Buenos Aires) y el propio módulo de
# fechas, que es el único que tiene permitido preguntar la hora.
EXCLUIDOS = {"fechas.py", "conftest.py", "promover_demo.py",
             "clonar_demo_a_pruebas.py", "actualizar_planes_render.py",
             "chequeo.py", "version.py"}
PREFIJOS_EXCLUIDOS = ("test_", "cargar_", "medir_", "probar_")


def _modulos_de_la_app() -> list:
    return sorted(p for p in RAIZ.glob("*.py")
                  if p.name not in EXCLUIDOS
                  and not p.name.startswith(PREFIJOS_EXCLUIDOS))


def _hora_del_servidor_en(ruta: Path) -> list:
    """Líneas donde se llama a datetime.now() sin zona o a date.today().

    Se mira el árbol de sintaxis y no el texto: un comentario que las
    nombre (como el de este archivo) no puede hacer fallar el test.
    """
    faltas = []
    for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
            continue
        duenio = getattr(nodo.func.value, "id", "")
        sin_argumentos = not nodo.args and not nodo.keywords
        if duenio == "datetime" and nodo.func.attr == "now" and sin_argumentos:
            faltas.append(nodo.lineno)
        elif duenio == "date" and nodo.func.attr == "today":
            faltas.append(nodo.lineno)
    return faltas


def test_es_la_hora_de_buenos_aires():
    esperado = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).replace(tzinfo=None)
    assert abs(fechas.ahora() - esperado) < timedelta(seconds=2)


def test_no_es_la_hora_del_servidor_en_utc():
    # Argentina no tiene horario de verano: son SIEMPRE tres horas menos que
    # UTC. Este es el test que habría cazado el bug en Render.
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((utc - fechas.ahora()) - timedelta(hours=3)) < timedelta(seconds=2)


def test_ahora_es_naive():
    # Sin tzinfo a propósito: la app guarda fechas como texto y un datetime
    # con zona le metería el offset ("-03:00") a isoformat(), rompiendo el
    # formato de lo que ya está guardado.
    assert fechas.ahora().tzinfo is None
    assert "-03:00" not in fechas.ahora().isoformat()


def test_formatos():
    assert fechas.hoy_texto() == fechas.ahora().strftime("%Y-%m-%d")
    assert fechas.hoy() == fechas.ahora().date()
    assert len(fechas.hoy_texto()) == 10
    assert len(fechas.ahora_texto()) == 16          # AAAA-MM-DD HH:MM
    assert len(fechas.ahora_con_segundos()) == 19   # ...:SS
    # El formato corto es el prefijo del largo (mismo minuto).
    assert fechas.ahora_con_segundos().startswith(fechas.ahora_texto()[:13])


def test_ningun_modulo_de_la_app_le_pide_la_hora_al_servidor():
    culpables = {}
    for ruta in _modulos_de_la_app():
        faltas = _hora_del_servidor_en(ruta)
        if faltas:
            culpables[ruta.name] = faltas
    assert not culpables, (
        "Estos módulos usan la hora del servidor (UTC en Render) en vez de "
        f"fechas.ahora()/fechas.hoy(): {culpables}")


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
