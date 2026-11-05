# -*- coding: utf-8 -*-
"""Compara lectura contra lectura (PLAN_PRUEBAS_BANCARIA.md §4A).

Cada carpeta tiene, por recibo, el JSON que devolvió /api/leer
(`<banco>/<archivo>.json`; si trae la clave `recibo` se compara esa, si no el
JSON entero es el recibo). Compara período, totales impresos, CUIL/CUIT y las
líneas con `extractor.comparar_lineas`. El formato de un número no cuenta
(se compara el valor); un código, importe o tipo distinto, sí.

Uso:
    python carga/comparar_lecturas.py <carpeta_vieja> <carpeta_nueva>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _recibo(j: dict) -> dict:
    return j.get("recibo") if isinstance(j.get("recibo"), dict) else j


def _n(x):
    import validador
    v = validador.a_numero(x)
    return None if v is None else round(abs(v), 2)


def _d(x):
    return "".join(c for c in str(x or "") if c.isdigit())


def diferencias(a: dict, b: dict) -> list[str]:
    """Qué cambia entre dos lecturas del mismo recibo. Vacío = idéntica. Puro."""
    import extractor
    a, b = _recibo(a), _recibo(b)
    out = []
    if (a.get("periodo") or "") != (b.get("periodo") or ""):
        out.append(f"período {a.get('periodo')!r} -> {b.get('periodo')!r}")
    for campo in sorted(set((a.get("totales_impresos") or {}) | (b.get("totales_impresos") or {}))):
        x, y = _n((a.get("totales_impresos") or {}).get(campo)), _n((b.get("totales_impresos") or {}).get(campo))
        if x != y:
            out.append(f"total {campo}: {x} -> {y}")
    for quien, campo in (("empleado", "cuil"), ("empleador", "cuit")):
        x, y = _d((a.get(quien) or {}).get(campo)), _d((b.get(quien) or {}).get(campo))
        if x != y:
            out.append(f"{quien}.{campo}: {x} -> {y}")
    cmp = extractor.comparar_lineas([("vieja", a), ("nueva", b)])
    for f in cmp["filas"]:
        if f["difiere"] and not (f["signo"] and all(c.get("igual") or c.get("signo") for c in f["celdas"])):
            out.append(f"línea {f['codigo']} {f['descripcion']}: " +
                       " | ".join(c["valor"] for c in f["celdas"]))
    return out


def solo_signo(a: dict, b: dict) -> int:
    """Líneas que solo difieren en el signo (se señalan, no cuentan)."""
    import extractor
    cmp = extractor.comparar_lineas([("vieja", _recibo(a)), ("nueva", _recibo(b))])
    return sum(1 for f in cmp["filas"] if f["signo"])


def comparar_carpetas(vieja: Path, nueva: Path) -> str:
    comunes = sorted(str(p.relative_to(nueva)) for p in nueva.rglob("*.json")
                     if (vieja / p.relative_to(nueva)).exists())
    lineas, iguales = [], 0
    for rel in comunes:
        a = json.loads((vieja / rel).read_text(encoding="utf-8"))
        b = json.loads((nueva / rel).read_text(encoding="utf-8"))
        dif = diferencias(a, b)
        sg = solo_signo(a, b)
        if sg and not dif:
            lineas.append(f"{rel}: idéntica ({sg} línea(s) con otro signo)")
            iguales += 1
            continue
        if dif:
            lineas.append(f"{rel}: DIFERENCIAS\n    " + "\n    ".join(dif))
        else:
            iguales += 1
            lineas.append(f"{rel}: idéntica")
    lineas.append(f"\n{iguales} de {len(comunes)} idénticas.")
    return "\n".join(lineas)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(comparar_carpetas(Path(sys.argv[1]), Path(sys.argv[2])))
