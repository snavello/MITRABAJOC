# -*- coding: utf-8 -*-
"""Arma carga/log/<carpeta>/resumen.csv a partir de la salida cruda de k6
(--out json=...) de test1 y test2, cruzada con servidor.log (CPU/RAM/
conexiones de Postgres, o null si no hubo RENDER_API_KEY).

Uso:
    python carga/resumen.py carga/log/2026-09-09_1200/
Espera encontrar ahí test1_lecturas.json, test2_recibos.json y
servidor.log (los que falten se saltean, no cortan el resumen del resto).
"""
import json
import statistics
import sys
from pathlib import Path

# Ventanas de medición "en régimen" de cada escalón de k6/test1_lecturas.js:
# por escalón hay 30s de rampa y 3m30s de sostén, y se mide SOLO el sostén.
#
# Se derivan de las etapas en vez de escribirse a mano porque escritas a mano
# estuvieron mal hasta el 2026-09-10: cada ventana empezaba y terminaba 30s
# más tarde que la anterior, así que se iba corriendo y terminaba metiendo la
# RAMPA DEL ESCALÓN SIGUIENTE adentro de la medición. El efecto era grande y
# siempre en contra: el escalón de 200 del test 6 figuraba con p95 de
# 1.455 ms cuando su sostén real dio 213 ms, y el de 400 con 7.766 ms cuando
# fueron 2.124 ms. Si se cambian las etapas del script, cambiar acá también.
RAMPA_SEG, SOSTEN_SEG = 30, 210
_CICLO = RAMPA_SEG + SOSTEN_SEG
ESCALONES_TEST1 = [
    (esc, i * _CICLO + RAMPA_SEG, (i + 1) * _CICLO)
    for i, esc in enumerate([50, 100, 200, 400, 800])
]
# Ráfagas de test2_recibos.js: (tamaño, offset_inicio_seg, offset_fin_seg) --
# constant-vus, sin rampa, toda la ventana de 4 min es válida.
ESCALONES_TEST2 = [(2, 0, 240), (5, 240, 480), (10, 480, 720), (20, 720, 960)]


def leer_puntos(ruta_json: Path):
    """Lee el NDJSON de k6 y devuelve (por_metrica, t0_absoluto) donde
    por_metrica es {metrica: [(t_seg_desde_inicio, valor, tags)]} y t0 es el
    timestamp Unix del primer punto -- para poder ubicar servidor.log
    (timestamps absolutos) en la misma línea de tiempo relativa."""
    if not ruta_json.exists():
        return None, None
    filas = []
    with open(ruta_json, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                obj = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "Point":
                continue
            filas.append(obj)
    if not filas:
        return None, None
    t0 = min(_ts(o) for o in filas)
    por_metrica = {}
    for o in filas:
        m = obj_metrica(o)
        por_metrica.setdefault(m, []).append(
            (_ts(o) - t0, o["data"]["value"], o["data"].get("tags", {})))
    return por_metrica, t0


def _ts(obj):
    from datetime import datetime
    return datetime.fromisoformat(obj["data"]["time"].replace("Z", "+00:00")).timestamp()


def obj_metrica(obj):
    return obj.get("metric", "")


def percentil(valores, p):
    if not valores:
        return None
    valores = sorted(valores)
    k = (len(valores) - 1) * p
    f, c = int(k), min(int(k) + 1, len(valores) - 1)
    if f == c:
        return valores[f]
    return valores[f] + (valores[c] - valores[f]) * (k - f)


def stats_ventana(por_metrica, desde, hasta, filtro_tags=None):
    duraciones = [v for (t, v, tags) in por_metrica.get("http_req_duration", [])
                  if desde <= t < hasta and (not filtro_tags or filtro_tags(tags))]
    fallos = [v for (t, v, tags) in por_metrica.get("http_req_failed", [])
              if desde <= t < hasta and (not filtro_tags or filtro_tags(tags))]
    errores_app = [v for (t, v, tags) in por_metrica.get("errores_app", [])
                   if desde <= t < hasta]
    errores_recibo = [v for (t, v, tags) in por_metrica.get("errores_recibo", [])
                       if desde <= t < hasta]
    n = len(duraciones)
    if n == 0:
        return None
    tasa_error = None
    base_error = fallos or errores_app or errores_recibo
    if base_error:
        tasa_error = 100 * sum(1 for x in base_error if x) / len(base_error)
    return {
        "p50": round(percentil(duraciones, 0.50), 1),
        "p95": round(percentil(duraciones, 0.95), 1),
        "p99": round(percentil(duraciones, 0.99), 1),
        "errores_pct": round(tasa_error, 2) if tasa_error is not None else "",
        "rps": round(n / (hasta - desde), 2),
        "n": n,
    }


def servidor_max(servidor_log: Path, t0: float, desde_rel: float, hasta_rel: float):
    """Máximo de cada métrica del servidor dentro de [desde_rel, hasta_rel)
    segundos desde el arranque del test (t0 = timestamp Unix del primer
    punto de ese test's JSON, para ubicar las filas absolutas de
    servidor.log en esa misma ventana relativa)."""
    if not servidor_log.exists() or t0 is None:
        return {"cpu_max": "", "ram_max": "", "conexiones_pg_max": ""}
    from datetime import datetime
    cpu, ram, con = [], [], []
    with open(servidor_log, encoding="utf-8") as f:
        for linea in f:
            try:
                fila = json.loads(linea)
            except json.JSONDecodeError:
                continue
            ts_str = fila.get("ts")
            if not ts_str:
                continue
            t_rel = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp() - t0
            if not (desde_rel <= t_rel < hasta_rel):
                continue
            for campo, dst in (("cpu_web", cpu), ("cpu_db", cpu),
                                ("ram_web", ram), ("ram_db", ram),
                                ("conexiones_db", con)):
                if fila.get(campo) is not None:
                    dst.append(fila[campo])
    return {
        "cpu_max": round(max(cpu), 3) if cpu else "",
        "ram_max": round(max(ram), 3) if ram else "",
        "conexiones_pg_max": max(con) if con else "",
    }


def filas_test1(carpeta: Path):
    datos, t0 = leer_puntos(carpeta / "test1_lecturas.json")
    if not datos:
        print("test1_lecturas.json no encontrado o vacío -- se salteó.")
        return []
    filas = []
    for escalon, desde, hasta in ESCALONES_TEST1:
        st = stats_ventana(datos, desde, hasta)
        if not st:
            continue
        srv = servidor_max(carpeta / "servidor.log", t0, desde, hasta)
        filas.append({"test": "lecturas", "escalon": escalon, **st, **srv})
    return filas


def filas_test2(carpeta: Path):
    datos, t0 = leer_puntos(carpeta / "test2_recibos.json")
    if not datos:
        print("test2_recibos.json no encontrado o vacío -- se salteó.")
        return []
    filas = []
    for tam, desde, hasta in ESCALONES_TEST2:
        srv = servidor_max(carpeta / "servidor.log", t0, desde, hasta)
        st_recibo = stats_ventana(datos, desde, hasta, lambda tg: tg.get("paso") == "subir_recibo")
        if st_recibo:
            filas.append({"test": "recibos", "escalon": tam, **st_recibo, **srv})
        st_lector = stats_ventana(
            datos, desde, hasta,
            lambda tg: tg.get("paso") in ("home", "novedades", "app"))
        if st_lector:
            filas.append({"test": "lectores_durante_recibos", "escalon": tam, **st_lector, **srv})
    return filas


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python carga/resumen.py <carpeta carga/log/AAAA-MM-DD_HHMM/>")
    carpeta = Path(sys.argv[1])
    filas = filas_test1(carpeta) + filas_test2(carpeta)
    if not filas:
        sys.exit("No se encontró ningún JSON crudo en esa carpeta -- nada para resumir.")
    columnas = ["test", "escalon", "p50", "p95", "p99", "errores_pct", "rps", "n",
                "cpu_max", "ram_max", "conexiones_pg_max"]
    import csv
    destino = carpeta / "resumen.csv"
    with open(destino, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)
    print(f"Escrito {destino} con {len(filas)} filas")
