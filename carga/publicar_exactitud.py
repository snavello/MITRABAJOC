# -*- coding: utf-8 -*-
"""Publica en /entornos → «Tests en Pruebas» las pruebas de exactitud del lote
bancario (PLAN_PRUEBAS_BANCARIA.md), con el tipo `exactitud` de
`POST /entornos/tests/publicar`.

Qué se publica sale de `carga/exactitud.json` (una entrada por prueba: nombre,
objetivo, configuración, causas con su origen y conclusión, escritos a mano) y
de los resultados crudos de cada corrida en `carga/log/lote_bancaria/`. Lo que
la app concluyó en el momento sale del CSV de la corrida; cómo da con las
correcciones posteriores, de `*_recalculo_con_correcciones.csv` (la misma
lectura de la IA, validada de nuevo con la app de hoy).

Uso:
    python carga/publicar_exactitud.py --dry-run            # muestra qué publicaría
    PIN_ENTORNOS=xxxxxxxx BASE_URL=https://mitrabajo-pruebas.onrender.com \\
        python carga/publicar_exactitud.py [--solo piloto-10]
No borra nada de la lista: agrega una entrada por prueba (correrlo dos veces
las duplica).
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "carga" / "exactitud.json"
RECALCULO = RAIZ / "carga" / "log" / "lote_bancaria" / "2026-11-04_recalculo_con_correcciones.csv"
ETIQUETA = {"OK": "OK", "CON_DISCREPANCIAS": "Con diferencias"}

sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "carga"))


def _esp(valor: str) -> str:
    return ETIQUETA.get(valor, valor)


def _pesos_seg(ms) -> float | None:
    try:
        return round(float(ms) / 1000, 1)
    except (TypeError, ValueError):
        return None


def recibos_de_corrida(prueba: dict, recalculo: dict) -> list[dict]:
    """Una fila por recibo. Lo esperado se recalcula con el criterio vigente
    (`lote_bancaria.esperado`, que cuenta el tope de aportes)."""
    import lote_bancaria as L
    man = {f["archivo"]: f for f in L.manifiesto()} if L.MANIFIESTO.exists() else {}
    filas = []
    with open(RAIZ / prueba["csv"], encoding="utf-8") as f:
        for r in csv.DictReader(f):
            esperado = L.esperado(man[r["archivo"]]) if r["archivo"] in man else r["esperado"]
            fila = {"archivo": r["archivo"], "esperado": _esp(esperado), "obtenido": _esp(r["obtenido"]),
                    "acierto": r["obtenido"] == esperado, "lectura_ok": r["lectura_ok"] == "True",
                    "segundos": _pesos_seg(r["ms_leer"]), "detalle": r.get("discrepancias", "")}
            if r["archivo"] in recalculo:
                fila["con_correccion"] = recalculo[r["archivo"]] == esperado
            filas.append(fila)
    return filas


def recibos_de_variantes(prueba: dict) -> list[dict]:
    """Una fila por línea que importa: la cuota de cada recibo y las trampas."""
    filas = []
    for r in json.loads((RAIZ / prueba["variantes"]).read_text(encoding="utf-8")):
        cat = {ln["descripcion"]: ln["categoria"] for ln in r.get("lineas", [])}
        casos = [(r["cuota"], r["es_cuota"])] + [(t, False) for t in r.get("trampas", [])]
        for nombre, es_cuota in casos:
            leido = cat.get(nombre)
            filas.append({"archivo": f"{r['archivo']} · «{nombre}»",
                          "esperado": "Cuota sindical" if es_cuota else "No es cuota",
                          "obtenido": "Cuota sindical" if leido == "cuota_sindical" else "No es cuota",
                          "acierto": (leido == "cuota_sindical") == es_cuota,
                          "lectura_ok": None, "segundos": _pesos_seg(r.get("ms"))})
    return filas


def totales(prueba: dict, filas: list[dict]) -> dict:
    n = len(filas)
    t = {}
    if "csv" in prueba:
        segs = sorted(f["segundos"] for f in filas if f["segundos"] is not None)
        t["Lectura exacta (IA)"] = f"{sum(1 for f in filas if f['lectura_ok'])} de {n}"
        t["Dieron lo esperado"] = f"{sum(1 for f in filas if f['acierto'])} de {n}"
        if any("con_correccion" in f for f in filas):
            t["Con las correcciones"] = f"{sum(1 for f in filas if f.get('con_correccion'))} de {n}"
        if segs:
            t["Lectura, mediana"] = f"{statistics.median(segs):.1f} s".replace(".", ",")
            t["Lectura, la más lenta"] = f"{segs[-1]:.1f} s".replace(".", ",")
    else:
        cuotas = [f for f in filas if f["esperado"] == "Cuota sindical"]
        otras = [f for f in filas if f["esperado"] != "Cuota sindical"]
        t["Cuotas reconocidas"] = f"{sum(f['acierto'] for f in cuotas)} de {len(cuotas)}"
        t["Trampas no confundidas"] = f"{sum(f['acierto'] for f in otras)} de {len(otras)}"
    if prueba.get("costo"):
        t["Costo"] = prueba["costo"]
    return t


def payload_de(prueba: dict, recalculo: dict) -> dict:
    filas = recibos_de_corrida(prueba, recalculo) if "csv" in prueba else recibos_de_variantes(prueba)
    tot = totales(prueba, filas)
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
            "terminado_en": f"{prueba['fin_ba']}:00", "totales": tot, "causas": prueba["causas"],
            "resumen": filas}


def _recalculo() -> dict:
    if not RECALCULO.exists():
        return {}
    with open(RECALCULO, encoding="utf-8") as f:
        return {r["archivo"]: r["con_correccion"] for r in csv.DictReader(f)}


def _pedir(base_url: str, pin: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/entornos/tests/publicar", data=json.dumps(payload).encode(),
        method="POST", headers={"Content-Type": "application/json", "X-Pin-Entornos": pin})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main(argv: list[str]) -> None:
    pruebas = json.loads(REGISTRO.read_text(encoding="utf-8"))
    if "--solo" in argv:
        pruebas = [p for p in pruebas if p["clave"] == argv[argv.index("--solo") + 1]]
    rec = _recalculo()
    pagos = [payload_de(p, rec) for p in pruebas]
    if "--dry-run" in argv:
        for p in pagos:
            print(f"{p['nombre']}: {len(p['resumen'])} filas · {p['veredicto']} · {p['totales']}")
        return
    pin, base_url = os.getenv("PIN_ENTORNOS", ""), os.getenv("BASE_URL", "")
    if not pin or not base_url:
        sys.exit("Faltan PIN_ENTORNOS y/o BASE_URL.")
    if "pruebas" not in base_url:
        sys.exit(f"BASE_URL no parece ser el servicio de Pruebas ({base_url}). Abortado.")
    try:
        for p in pagos:
            r = _pedir(base_url, pin, p)
            print(f"  Test {r['id']} — {p['nombre']}: {base_url.rstrip('/')}/entornos/tests/{r['id']}")
    except urllib.error.HTTPError as e:
        sys.exit(f"Error {e.code}: {e.read().decode()[:400]}")


if __name__ == "__main__":
    main(sys.argv[1:])
