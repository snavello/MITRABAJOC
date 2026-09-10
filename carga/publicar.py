# -*- coding: utf-8 -*-
"""Publica en /entornos#tests-pruebas (tabla TestCarga) un test corrido
AFUERA de la app -- carga/correr.sh con k6, a diferencia del botón
"Correr" que ya publica solo porque dispara un Job que escribe directo
en la base (ver main.py, "Tests: pestaña de test de estrés").

Sin esto, una corrida de correr.sh queda solo en carga/log/ y en el
informe -- no aparece en la lista de la app. Pedido explícito de Sd
(2026-09-10): que TODO test corrido termine publicado ahí, sea cual sea
la herramienta.

Uso (lo llama correr.sh automáticamente al final; también se puede a mano):
    PIN_ENTORNOS=xxxxxxxx BASE_URL=https://mitrabajo-pruebas.onrender.com \
    python carga/publicar.py carga/log/2026-09-10_web2c4g_2workers/ \
        --config '{"workers_uvicorn": 2, "plan_web": "2c-4g", "plan_db": "2c-4g"}'

Sin PIN_ENTORNOS no publica -- se avisa por stdout y se sigue sin cortar
correr.sh (el resumen.csv y el informe local no dependen de esto).
"""
import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# offset_fin - offset_inicio de cada escalón en k6/test1_lecturas.js y
# test2_recibos.js (ver resumen.py, ESCALONES_TEST1/2) -- la ventana
# sostenida que se mide, no el archivo entero.
DURACION_LECTURAS = 240
DURACION_RECIBOS = 240


def _post(base_url: str, pin: str, payload: dict) -> dict:
    datos = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/entornos/tests/publicar", data=datos, method="POST",
        headers={"Content-Type": "application/json", "X-Pin-Entornos": pin})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _filas(carpeta: Path, test: str) -> list:
    ruta = carpeta / "resumen.csv"
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        return [
            {"escalon": int(row["escalon"]), "p50": float(row["p50"]), "p95": float(row["p95"]),
             "p99": float(row["p99"]), "errores_pct": float(row["errores_pct"]), "rps": float(row["rps"])}
            for row in csv.DictReader(f) if row["test"] == test
        ]


def publicar(carpeta: Path, base_url: str, pin: str, config: dict, terminado_en: str | None = None):
    resultados = []
    lecturas = _filas(carpeta, "lecturas")
    if lecturas:
        r = _post(base_url, pin, {"tipo": "lecturas", "duracion_seg": DURACION_LECTURAS,
                                   "config": config, "resumen": lecturas, "terminado_en": terminado_en})
        resultados.append(("lecturas", r))
    # "recibos" es la métrica de subida en sí -- lectores_durante_recibos
    # (el impacto en el resto del tráfico) queda solo en resumen.csv/informe,
    # el mismo criterio que ya usa carga/correr_job.py para este tipo.
    recibos = _filas(carpeta, "recibos")
    if recibos:
        r = _post(base_url, pin, {"tipo": "recibos", "duracion_seg": DURACION_RECIBOS,
                                   "config": config, "resumen": recibos, "terminado_en": terminado_en})
        resultados.append(("recibos", r))
    return resultados


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta", type=Path, help="carga/log/AAAA-MM-DD_HHMM/ con resumen.csv adentro")
    ap.add_argument("--config", default="{}", help='JSON, ej: {"workers_uvicorn": 2, "plan_web": "2c-4g"}')
    ap.add_argument("--terminado-en", default=None, help="YYYY-MM-DD HH:MM:SS, default ahora")
    args = ap.parse_args()

    pin = os.getenv("PIN_ENTORNOS", "")
    base_url = os.getenv("BASE_URL", "")
    if not pin:
        print("PIN_ENTORNOS no está seteada -- no se publica en la app "
              "(el resumen.csv y el informe local quedan igual).")
        sys.exit(0)
    try:
        resultados = publicar(args.carpeta, base_url, pin, json.loads(args.config), args.terminado_en)
        for tipo, r in resultados:
            print(f"Publicado {tipo}: {base_url}/entornos/tests/{r['id']}")
        if not resultados:
            print("No había resumen.csv (o vino vacío) -- nada para publicar.")
    except urllib.error.HTTPError as e:
        print(f"No se pudo publicar: {e.code} {e.read().decode()[:300]}", file=sys.stderr)
