"""El reparto de la suite entre los trabajos paralelos del CI
(ci_reparto.py + .github/workflows/ci.yml): ninguna parte se pisa con
otra, entre todas cubren todos los test_*.py, y el workflow declara tantas
partes como el script espera. Sin base de datos.

Correr con: .venv/Scripts/python.exe -m pytest test_ci_reparto.py -q
"""
import re
from pathlib import Path

import pytest

import ci_reparto

RAIZ = Path(__file__).resolve().parent


def _partes_del_workflow() -> tuple[int, list[int]]:
    yml = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    partes = int(re.search(r"^\s+PARTES:\s*\"?(\d+)\"?", yml, re.M).group(1))
    lista = [int(x) for x in re.search(r"^\s+parte:\s*\[([\d,\s]+)\]", yml, re.M).group(1).split(",")]
    return partes, lista


def test_las_partes_cubren_todo_y_no_se_pisan():
    todos = ci_reparto.archivos()
    assert "test_ci_reparto.py" in todos and len(todos) > 50
    partes, _ = _partes_del_workflow()
    vistos = []
    for p in range(partes):
        vistos += ci_reparto.reparto(p, partes)
    assert sorted(vistos) == todos                 # todos, y ninguno dos veces
    print("OK  test_las_partes_cubren_todo_y_no_se_pisan")


def test_el_workflow_declara_las_mismas_partes_que_usa():
    partes, lista = _partes_del_workflow()
    assert lista == list(range(partes)), f"matriz {lista} no coincide con PARTES={partes}"
    print("OK  test_el_workflow_declara_las_mismas_partes_que_usa")


def test_el_reparto_es_determinista_y_valida_el_rango():
    lista = ["test_a.py", "test_b.py", "test_c.py", "test_d.py", "test_e.py"]
    assert ci_reparto.reparto(0, 2, lista) == ["test_a.py", "test_c.py", "test_e.py"]
    assert ci_reparto.reparto(1, 2, lista) == ["test_b.py", "test_d.py"]
    with pytest.raises(ValueError):
        ci_reparto.reparto(2, 2, lista)
    print("OK  test_el_reparto_es_determinista_y_valida_el_rango")
