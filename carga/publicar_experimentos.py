# -*- coding: utf-8 -*-
"""Publica en /entornos#tests-pruebas los 4 experimentos de
carga/experimentos.json, en orden, después de vaciar la lista -- así el
test 1 de la página es el primer experimento, el 2 el segundo, y así.

Es idempotente por diseño: siempre borra y vuelve a publicar los cuatro
desde el JSON consolidado, en vez de ir parchando entradas sueltas. Si un
número del informe cambia, se corre `python carga/consolidar.py` y después
esto, y la página queda igual al dato crudo.

Uso:
    PIN_ENTORNOS=xxxxxxxx BASE_URL=https://mitrabajo-pruebas.onrender.com \
    python carga/publicar_experimentos.py
    # --dry-run muestra qué publicaría, sin tocar nada
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATOS = BASE / "experimentos.json"


def _pedir(base_url: str, pin: str, ruta: str, payload=None) -> dict:
    datos = json.dumps(payload).encode() if payload is not None else b"{}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{ruta}", data=datos, method="POST",
        headers={"Content-Type": "application/json", "X-Pin-Entornos": pin})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def payload_de(exp: dict) -> dict:
    """El experimento entero como una sola entrada: las fases van en
    `resumen` (cada una con sus escalones y su carga de web y Postgres) y
    el resto -- config, advertencias, veredicto, conclusión -- en los
    parámetros. La página de detalle no calcula nada: solo muestra esto."""
    return {
        "tipo": "experimento",
        "numero": exp["numero"], "nombre": exp["nombre"], "subtitulo": exp["subtitulo"],
        "objetivo": exp["objetivo"], "config": exp["config"],
        "advertencias": exp["advertencias"], "veredicto": exp["veredicto"],
        "conclusion": exp["conclusion"],
        "inicio_ba": exp["inicio_ba"], "fin_ba": exp["fin_ba"],
        "terminado_en": f"{exp['fecha_ba']} {exp['fin_ba']}",
        "resumen": exp["fases"],
    }


if __name__ == "__main__":
    if not DATOS.exists():
        sys.exit(f"Falta {DATOS} -- correr primero: python carga/consolidar.py")
    experimentos = json.loads(DATOS.read_text(encoding="utf-8"))
    experimentos.sort(key=lambda e: e["numero"])

    if "--dry-run" in sys.argv:
        for e in experimentos:
            p = payload_de(e)
            print(f"Test {e['numero']}: {e['nombre']} — {len(p['resumen'])} fases, "
                  f"{sum(len(f['filas']) for f in p['resumen'])} filas, "
                  f"{e['inicio_ba']} a {e['fin_ba']}")
        sys.exit(0)

    pin = os.getenv("PIN_ENTORNOS", "")
    base_url = os.getenv("BASE_URL", "")
    if not pin or not base_url:
        sys.exit("Faltan PIN_ENTORNOS y/o BASE_URL.")
    if "pruebas" not in base_url:
        sys.exit(f"BASE_URL no parece ser el servicio de Pruebas ({base_url}). Abortado.")

    try:
        borrados = _pedir(base_url, pin, "/entornos/tests/borrar-todo")["borrados"]
        print(f"Lista vaciada ({borrados} entradas borradas), numeración reiniciada.")
        for e in experimentos:
            r = _pedir(base_url, pin, "/entornos/tests/publicar", payload_de(e))
            print(f"  Test {r['id']} — {e['nombre']}: {base_url}/entornos/tests/{r['id']}")
            if r["id"] != e["numero"]:
                print(f"  AVISO: quedó con id {r['id']} y se esperaba {e['numero']}.")
    except urllib.error.HTTPError as e:
        sys.exit(f"Error {e.code}: {e.read().decode()[:400]}")
