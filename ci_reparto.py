"""Reparte los archivos test_*.py entre los trabajos paralelos del CI.

El CI (.github/workflows/ci.yml) corre cada test_*.py en un proceso
separado, regla del proyecto: los módulos comparten estado de import y se
contaminan si corren juntos. Con 111 archivos en fila eran ~10 minutos, de
los cuales casi la mitad era arranque de proceso. Desde 2026-09-21 la suite
se reparte en PARTES trabajos de GitHub Actions que corren a la vez, cada
uno con su Postgres, y cada archivo sigue corriendo solo.

Uso: `python ci_reparto.py PARTE PARTES` imprime, uno por línea, los
archivos que le tocan a la parte PARTE (0..PARTES-1). El reparto es
determinista (orden alfabético, módulo PARTES) para que dos corridas del
mismo commit repartan igual; `test_ci_reparto.py` verifica que ninguna
parte se pise con otra y que entre todas cubran todos los archivos.
"""
import sys
from pathlib import Path


def archivos(carpeta: Path = None) -> list[str]:
    carpeta = carpeta or Path(__file__).resolve().parent
    return sorted(p.name for p in carpeta.glob("test_*.py"))


def reparto(parte: int, partes: int, lista: list[str] = None) -> list[str]:
    if partes < 1 or not 0 <= parte < partes:
        raise ValueError(f"parte {parte} fuera de rango para {partes} partes")
    lista = archivos() if lista is None else lista
    return [f for i, f in enumerate(lista) if i % partes == parte]


if __name__ == "__main__":
    print("\n".join(reparto(int(sys.argv[1]), int(sys.argv[2]))))
