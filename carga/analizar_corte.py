# -*- coding: utf-8 -*-
"""Cuánto duró el corte al cambiar de plan en Render (PLAN_PRUEBAS_BANCARIA.md, R).

Lee el NDJSON que deja `k6 run --out json=...` (típicamente el escenario
`continuo` de `k6/test4_bancaria.js`, con lectores navegando mientras se sube
o baja el plan desde /entornos → Planes) y arma la línea de tiempo segundo a
segundo: pedidos, fallas y con qué código. Un **corte** es una racha de
segundos con más de la mitad de los pedidos fallando (status 0 = sin
respuesta, o 5xx).

Criterio del plan: durante un corte se acepta 503 o "sin respuesta"; un 500
no se acepta nunca. Con DATABASE_URL, además lista los cambios de plan de la
bitácora (`CambioPlan`) en la ventana de la corrida, para ver que el orden de
los workers se respetó (al bajar, primero los workers; al subir, después).

Uso:
    python carga/analizar_corte.py carga/log/<carpeta>/test4.ndjson [--json salida.json]
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BA = ZoneInfo("America/Argentina/Buenos_Aires")
UMBRAL_CORTE = 0.5


def _segundo(iso: str) -> datetime:
    # k6 escribe "2026-11-03T15:04:05.123456789-03:00": se recorta a segundos.
    base, _, resto = iso.partition(".")
    tz = ""
    for sep in ("+", "-", "Z"):
        if sep in resto:
            tz = resto[resto.index(sep):]
            break
    return datetime.fromisoformat(base + (tz.replace("Z", "+00:00") or "+00:00")).astimezone(BA)


def linea_de_tiempo(lineas) -> dict:
    """{segundo: Counter(status)} con los puntos de http_reqs. Puro."""
    por_seg: dict = defaultdict(Counter)
    for l in lineas:
        l = l.strip()
        if not l:
            continue
        try:
            p = json.loads(l)
        except ValueError:
            continue
        if p.get("type") != "Point" or p.get("metric") != "http_reqs":
            continue
        d = p["data"]
        por_seg[_segundo(d["time"])][str((d.get("tags") or {}).get("status", "0"))] += 1
    return dict(sorted(por_seg.items()))


def _falla(status: str) -> bool:
    return status == "0" or status.startswith("5")


def cortes(tl: dict, umbral: float = UMBRAL_CORTE) -> list[dict]:
    """Rachas de segundos en los que fallan más del `umbral` de los pedidos. Puro."""
    resultado, actual = [], None
    for seg, c in tl.items():
        total = sum(c.values())
        fallas = sum(n for s, n in c.items() if _falla(s))
        malo = total and fallas / total > umbral
        if malo:
            if actual is None:
                actual = {"desde": seg, "hasta": seg, "codigos": Counter()}
            actual["hasta"] = seg
            actual["codigos"].update({s: n for s, n in c.items() if _falla(s)})
        elif actual is not None:
            resultado.append(actual)
            actual = None
    if actual is not None:
        resultado.append(actual)
    for r in resultado:
        r["segundos"] = int((r["hasta"] - r["desde"]).total_seconds()) + 1
        r["hubo_500"] = r["codigos"].get("500", 0) > 0
        r["codigos"] = dict(r["codigos"])
        r["desde"] = r["desde"].strftime("%Y-%m-%d %H:%M:%S")
        r["hasta"] = r["hasta"].strftime("%Y-%m-%d %H:%M:%S")
    return resultado


def cambios_de_plan(desde: str, hasta: str) -> list[dict] | None:
    if not os.getenv("DATABASE_URL"):
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sqlmodel import select
    import db
    from db import CambioPlan
    with db.get_session() as s:
        filas = s.exec(select(CambioPlan).where(CambioPlan.cuando >= desde, CambioPlan.cuando <= hasta)
                       .order_by(CambioPlan.cuando)).all()
    return [{"cuando": f.cuando, "origen": f.origen, "destino": f.destino,
             "de": f.plan_anterior, "a": f.plan_nuevo, "ok": f.ok, "detalle": f.detalle,
             "error": f.error} for f in filas]


def main(argv):
    if not argv:
        print(__doc__)
        return
    with open(argv[0], encoding="utf-8") as f:
        tl = linea_de_tiempo(f)
    if not tl:
        raise SystemExit("El archivo no tiene puntos de http_reqs (¿se corrió con --out json=...?).")
    segs = list(tl)
    total = Counter()
    for c in tl.values():
        total.update(c)
    rs = cortes(tl)
    inicio, fin = segs[0].strftime("%Y-%m-%d %H:%M:%S"), segs[-1].strftime("%Y-%m-%d %H:%M:%S")
    salida = {"desde": inicio, "hasta": fin, "pedidos": sum(total.values()),
              "por_status": dict(total), "cortes": rs,
              "hubo_500": any(r["hubo_500"] for r in rs) or total.get("500", 0) > 0,
              "cambios_de_plan": cambios_de_plan(inicio, fin)}
    print(f"Corrida {inicio} a {fin} (hora de Buenos Aires): {salida['pedidos']} pedidos")
    print("Por status:", dict(total))
    if not rs:
        print("Sin cortes (ningún segundo con más de la mitad de los pedidos fallando).")
    for r in rs:
        print(f"Corte {r['desde']} → {r['hasta']}: {r['segundos']} s, códigos {r['codigos']}"
              + ("  ← HUBO 500" if r["hubo_500"] else ""))
    for c in salida["cambios_de_plan"] or []:
        print(f"  plan {c['cuando']} {c['origen']:10} {c['destino']:8} {c['de']} → {c['a']} "
              f"{'ok' if c['ok'] else 'ERROR ' + c['error']} {c['detalle']}")
    print("VEREDICTO:", "NO APROBADO (hubo 500)" if salida["hubo_500"] else "sin 500")
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(
            json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
