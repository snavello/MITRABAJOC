# -*- coding: utf-8 -*-
"""Publica en /entornos → «Tests en Pruebas» las pruebas de exactitud del lote
bancario (PLAN_PRUEBAS_BANCARIA.md), con el tipo `exactitud` de la tabla de
Tests: cada recibo con su tiempo de lectura, su modelo y su costo.

Dos pasos, porque el lote y los resultados crudos viven en la rama del plan y
el costo real vive en la base de Pruebas:

1. **Armar** (en la PC o en una sesión de Code, con el lote extraído):
       python carga/publicar_exactitud.py --exportar
   Lee `carga/exactitud.json` (nombre, objetivo, configuración, causas con su
   origen y conclusión de cada prueba, escritos a mano) y los resultados de
   `carga/log/lote_bancaria/`, y deja todo listo en `carga/exactitud_pagos.json`.
   Lo que la app concluyó en el momento sale del CSV de la corrida; cómo da con
   las correcciones posteriores, de los `*_recalculo_*.csv`.

2. **Publicar adentro de Pruebas** (Shell de Render de `mitrabajo-pruebas`):
       python carga/publicar_exactitud.py --directo [--si]
   Lee `carga/exactitud_pagos.json`, busca en `UsoIA` cada lectura (por CUIL y
   por la ventana de la corrida) y le pone el modelo que corrió de verdad, los
   tokens y el costo con el precio congelado en la fila. Reemplaza en la lista
   las pruebas de exactitud con el mismo nombre. Sin `--si`, solo muestra.
   Se niega con ENTORNO distinto de pruebas.

`--dry-run` muestra qué se armaría sin escribir nada.
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "carga" / "exactitud.json"
PAGOS = RAIZ / "carga" / "exactitud_pagos.json"
# La misma lectura de la IA validada de nuevo con la app (y el catálogo) de hoy.
RECALCULOS = sorted((RAIZ / "carga" / "log" / "lote_bancaria").glob("*_recalculo_*.csv"))
ETIQUETA = {"OK": "OK", "CON_DISCREPANCIAS": "Con diferencias"}
# Margen después del fin anotado de cada corrida para buscar sus lecturas.
MARGEN_MIN = 3

sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "carga"))


def _esp(valor: str) -> str:
    return ETIQUETA.get(valor, valor)


def _seg(ms) -> float | None:
    try:
        return round(float(ms) / 1000, 1)
    except (TypeError, ValueError):
        return None


def _coma(x: float, dec: int = 1) -> str:
    return f"{x:.{dec}f}".replace(".", ",")


# ------------------------------------------------------------ 1. armar ----
def recibos_de_corrida(prueba: dict, recalculo: dict) -> list[dict]:
    """Una fila por recibo. Lo esperado se recalcula con el criterio vigente
    (`lote_bancaria.esperado`, que cuenta el tope de aportes)."""
    import lote_bancaria as L
    man = {f["archivo"]: f for f in L.manifiesto()}
    filas = []
    with open(RAIZ / prueba["csv"], encoding="utf-8") as f:
        for r in csv.DictReader(f):
            esperado = L.esperado(man[r["archivo"]])
            fila = {"archivo": r["archivo"], "cuil": r["cuil"], "lectura": r["archivo"],
                    "esperado": _esp(esperado), "obtenido": _esp(r["obtenido"]),
                    "acierto": r["obtenido"] == esperado, "lectura_ok": r["lectura_ok"] == "True",
                    "segundos": _seg(r["ms_leer"]), "detalle": r.get("discrepancias", "")}
            if r["archivo"] in recalculo and not prueba.get("sin_recalculo"):
                fila["con_correccion"] = recalculo[r["archivo"]] == esperado
            filas.append(fila)
    return filas


def recibos_de_variantes(prueba: dict) -> list[dict]:
    """Una fila por línea que importa: la cuota de cada recibo y las trampas.
    Las de un mismo recibo comparten la lectura (y su tiempo y costo)."""
    filas = []
    for r in json.loads((RAIZ / prueba["variantes"]).read_text(encoding="utf-8")):
        cat = {ln["descripcion"]: ln["categoria"] for ln in r.get("lineas", [])}
        cuil = "".join(ch for ch in (r["recibo"].get("empleado") or {}).get("cuil", "") if ch.isdigit())
        casos = [(r["cuota"], r["es_cuota"])] + [(t, False) for t in r.get("trampas", [])]
        for n, (nombre, es_cuota) in enumerate(casos):
            leido = cat.get(nombre)
            filas.append({"archivo": f"{r['archivo']} · «{nombre}»", "cuil": cuil, "lectura": r["archivo"],
                          "esperado": "Cuota sindical" if es_cuota else "No es cuota",
                          "obtenido": "Cuota sindical" if leido == "cuota_sindical" else "No es cuota",
                          "acierto": (leido == "cuota_sindical") == es_cuota,
                          "lectura_ok": None, "segundos": _seg(r.get("ms")) if n == 0 else None})
    return filas


def totales(prueba: dict, filas: list[dict]) -> dict:
    n = len(filas)
    t = {}
    if "csv" in prueba:
        t["Lectura exacta (IA)"] = f"{sum(1 for f in filas if f['lectura_ok'])} de {n}"
        t["Dieron lo esperado"] = f"{sum(1 for f in filas if f['acierto'])} de {n}"
        if any("con_correccion" in f for f in filas):
            t["Con las correcciones"] = f"{sum(1 for f in filas if f.get('con_correccion'))} de {n}"
    else:
        cuotas = [f for f in filas if f["esperado"] == "Cuota sindical"]
        otras = [f for f in filas if f["esperado"] != "Cuota sindical"]
        t["Cuotas reconocidas"] = f"{sum(f['acierto'] for f in cuotas)} de {len(cuotas)}"
        t["Trampas no confundidas"] = f"{sum(f['acierto'] for f in otras)} de {len(otras)}"
    segs = sorted(f["segundos"] for f in filas if f["segundos"] is not None)
    if segs:
        t["Lectura, mediana"] = f"{_coma(statistics.median(segs))} s"
        t["Lectura, la más lenta"] = f"{_coma(segs[-1])} s"
    if prueba.get("costo"):
        t["Costo"] = prueba["costo"]
    return t


def payload_de(prueba: dict, recalculo: dict) -> dict:
    filas = recibos_de_corrida(prueba, recalculo) if "csv" in prueba else recibos_de_variantes(prueba)
    bien = sum(1 for f in filas if f["acierto"])
    corr = sum(1 for f in filas if f.get("con_correccion"))
    if any("con_correccion" in f for f in filas):
        veredicto = (f"{bien} de {len(filas)} dieron lo esperado en el momento; "
                     f"con las correcciones, {corr} de {len(filas)}.")
        ok = corr == len(filas)
    else:
        veredicto = f"{bien} de {len(filas)} dieron lo esperado."
        ok = bien == len(filas)
    return {"tipo": "exactitud", "nombre": prueba["nombre"], "subtitulo": prueba["subtitulo"],
            "objetivo": prueba["objetivo"], "config": prueba["config"], "advertencias": [],
            "veredicto": veredicto, "veredicto_ok": ok, "conclusion": prueba["conclusion"],
            "inicio_ba": prueba["inicio_ba"], "fin_ba": prueba["fin_ba"],
            "terminado_en": f"{prueba['fin_ba']}:00", "totales": totales(prueba, filas),
            "causas": prueba["causas"], "resumen": filas}


def _recalculo() -> dict:
    """{archivo: estado con las correcciones}; el recálculo más nuevo manda."""
    salida = {}
    for ruta in RECALCULOS:
        with open(ruta, encoding="utf-8") as f:
            salida.update({r["archivo"]: r["con_correccion"] for r in csv.DictReader(f)})
    return salida


def armar() -> list[dict]:
    return [payload_de(p, _recalculo()) for p in json.loads(REGISTRO.read_text(encoding="utf-8"))]


# ------------------------------------------------- 2. costo de UsoIA -----
def asignar_uso(pago: dict, usos: list[dict]) -> bool:
    """Le pone a cada fila el modelo, los tokens y el costo de SU lectura.
    `usos`: filas de UsoIA de la ventana de la corrida, ordenadas por id.
    Cada CUIL subió sus recibos en el orden de las filas, así que la n-ésima
    lectura de un CUIL es su n-ésima fila de UsoIA. Devuelve False (y no toca
    nada) si las cuentas no cierran. Puro."""
    import precios_ia
    por_cuil: dict[str, list] = {}
    for u in usos:
        por_cuil.setdefault(u["cuil"], []).append(u)
    lecturas: dict[str, list] = {}
    for f in pago["resumen"]:
        lista = lecturas.setdefault(f["cuil"], [])
        if f["lectura"] not in lista:
            lista.append(f["lectura"])
    if any(len(lecturas[c]) != len(por_cuil.get(c, [])) for c in lecturas):
        return False
    uso_de = {}
    for c, ls in lecturas.items():
        for lectura, u in zip(ls, por_cuil[c]):
            uso_de[lectura] = u
    vistas, total, modelos = set(), 0.0, set()
    for f in pago["resumen"]:
        u = uso_de[f["lectura"]]
        pe, ps = (u["precio_entrada"], u["precio_salida"]) if u["precio_entrada"] else \
            (precios_ia.precios(u["modelo"]) or (0, 0))
        costo = precios_ia.costo(u["tokens_entrada"], u["tokens_salida"], pe, ps)
        f["modelo"] = precios_ia.nombre(u["modelo"]).replace("Claude ", "")
        modelos.add(f["modelo"])
        if f["lectura"] in vistas:
            f["costo_usd"] = None          # la misma lectura ya contada en otra fila
            continue
        vistas.add(f["lectura"])
        f["costo_usd"] = round(costo, 4)
        f["tokens"] = f"{u['tokens_entrada']:,} / {u['tokens_salida']:,}".replace(",", ".")
        total += costo
    n = len(vistas)
    pago["totales"].pop("Costo", None)
    pago["totales"]["Modelo que leyó"] = ", ".join(sorted(modelos))
    pago["totales"]["Costo total"] = f"US$ {_coma(total, 4)}"
    pago["totales"]["Costo por recibo"] = f"US$ {_coma(total / n, 4)}" if n else "—"
    return True


def _usos_de(s, pago: dict) -> list[dict]:
    from sqlmodel import select
    from db import UsoIA
    desde = pago["inicio_ba"]
    hasta = (datetime.strptime(pago["fin_ba"], "%Y-%m-%d %H:%M")
             + timedelta(minutes=MARGEN_MIN)).strftime("%Y-%m-%d %H:%M")
    cuils = {f["cuil"] for f in pago["resumen"]}
    filas = s.exec(select(UsoIA).where(UsoIA.tipo == "recibo", UsoIA.fecha >= desde,
                                       UsoIA.fecha <= hasta, UsoIA.cuil.in_(cuils))
                   .order_by(UsoIA.id)).all()
    return [{"cuil": u.cuil, "modelo": u.modelo, "tokens_entrada": u.tokens_entrada,
             "tokens_salida": u.tokens_salida, "precio_entrada": u.precio_entrada,
             "precio_salida": u.precio_salida} for u in filas]


def publicar_directo(pagos: list[dict], escribir: bool) -> None:
    import db
    from db import TestCarga
    from sqlmodel import select
    if os.getenv("ENTORNO", "").strip().lower() != "pruebas":
        sys.exit("Solo en Pruebas (ENTORNO=pruebas): la lista de Tests existe solo ahí.")
    with db.get_session() as s:
        for p in pagos:
            ok = asignar_uso(p, _usos_de(s, p))
            print(f"{p['nombre']}: costo {'real' if ok else 'NO encontrado (queda el estimado)'} · "
                  f"{p['totales'].get('Costo total', p['totales'].get('Costo'))}")
        viejos = [t for t in s.exec(select(TestCarga).where(TestCarga.tipo == "exactitud")).all()
                  if (t.parametros or {}).get("nombre") in {p["nombre"] for p in pagos}]
        print(f"Se reemplazan {len(viejos)} pruebas de exactitud ya publicadas con el mismo nombre.")
        if not escribir:
            print("Ensayo: no se escribió nada. Con --si publica.")
            return
        for t in viejos:
            s.delete(t)
        s.commit()
    claves = ("nombre", "subtitulo", "objetivo", "config", "advertencias", "veredicto",
              "veredicto_ok", "conclusion", "inicio_ba", "fin_ba", "totales", "causas")
    for p in pagos:
        tid = db.crear_test_carga("exactitud", {k: p.get(k) for k in claves})
        db.actualizar_test_carga(tid, estado="listo", resumen=p["resumen"],
                                 terminado_en=p["terminado_en"])
        print(f"  Test {tid} — {p['nombre']}: /entornos/tests/{tid}")


def main(argv: list[str]) -> None:
    if "--directo" in argv:
        publicar_directo(json.loads(PAGOS.read_text(encoding="utf-8")), "--si" in argv)
        return
    pagos = armar()
    for p in pagos:
        print(f"{p['nombre']}: {len(p['resumen'])} filas · {p['veredicto']}")
    if "--exportar" in argv:
        PAGOS.write_text(json.dumps(pagos, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Escrito {PAGOS}")


if __name__ == "__main__":
    main(sys.argv[1:])
