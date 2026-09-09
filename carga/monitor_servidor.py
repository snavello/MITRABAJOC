# -*- coding: utf-8 -*-
"""Muestrea cada 30s, durante un test de carga, CPU/RAM del servicio web y
CPU/RAM/conexiones activas del Postgres de mitrabajo-pruebas, vía la API de
Render (api.render.com/v1/metrics/{cpu,memory,active-connections}, ver
https://api-docs.render.com/reference/get-cpu y hermanos), y los va
agregando a carga/log/<carpeta-del-test>/servidor.log (una línea JSON por
muestra).

Si no hay RENDER_API_KEY (o la cuenta no tiene el plan que expone /metrics),
el script AVISA y sigue escribiendo filas con los campos en null -- así
carga/INFORME.md puede marcar el hueco pedido en la consigna ("pedime
capturas de la pestaña Metrics") en vez de fallar en silencio.

Uso (se lanza en paralelo al test, se lo mata con Ctrl+C o SIGTERM cuando
termina -- carga/correr.sh ya lo orquesta):
    RENDER_API_KEY=rnd_xxx \
    RENDER_WEB_SERVICE_ID=srv-xxx \
    RENDER_DB_ID=dpg-xxx \
    python carga/monitor_servidor.py carga/log/2026-09-09_1200/servidor.log
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

API = "https://api.render.com/v1"
INTERVALO_SEGUNDOS = 30


def _get(path: str, api_key: str):
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bearer {api_key}", "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _ultimo_valor(api_key: str, resource_id: str, endpoint: str):
    """Pide el último punto de una métrica (endpoint: cpu, memory,
    active-connections) en la ventana de los últimos 2 minutos.
    Formato de respuesta real: [{"labels": [...], "values": [{"timestamp",
    "value"}], "unit": "..."}] -- una serie por resource/instance."""
    hasta = datetime.now(timezone.utc)
    desde = hasta - timedelta(minutes=2)
    qs = (f"resource={resource_id}&startTime={desde.isoformat()}"
          f"&endTime={hasta.isoformat()}&resolutionSeconds=30")
    try:
        series = _get(f"/metrics/{endpoint}?{qs}", api_key)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)
    if not series:
        return None, "sin datos"
    # Con varias instancias (>1 worker/réplica) sumamos el último valor de
    # cada serie -- para CPU/RAM totales del servicio, no el promedio.
    total, alguno = 0.0, False
    for serie in series:
        valores = serie.get("values") or []
        if valores:
            total += valores[-1].get("value", 0)
            alguno = True
    return (total if alguno else None), (None if alguno else "sin datos")


def muestra(api_key: str, web_id: str, db_id: str) -> dict:
    fila = {"ts": datetime.now(timezone.utc).isoformat(), "cpu_web": None,
            "ram_web": None, "cpu_db": None, "ram_db": None, "conexiones_db": None,
            "nota": None}
    if not api_key:
        fila["nota"] = "sin RENDER_API_KEY: hueco para completar con capturas de Metrics"
        return fila
    errores = []
    if web_id:
        v, err = _ultimo_valor(api_key, web_id, "cpu")
        fila["cpu_web"] = v
        if err:
            errores.append(f"cpu_web:{err}")
        v, err = _ultimo_valor(api_key, web_id, "memory")
        fila["ram_web"] = v
        if err:
            errores.append(f"ram_web:{err}")
    if db_id:
        v, err = _ultimo_valor(api_key, db_id, "cpu")
        fila["cpu_db"] = v
        if err:
            errores.append(f"cpu_db:{err}")
        v, err = _ultimo_valor(api_key, db_id, "memory")
        fila["ram_db"] = v
        if err:
            errores.append(f"ram_db:{err}")
        v, err = _ultimo_valor(api_key, db_id, "active-connections")
        fila["conexiones_db"] = v
        if err:
            errores.append(f"conexiones_db:{err}")
    if errores:
        fila["nota"] = "; ".join(errores)
    return fila


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python carga/monitor_servidor.py <ruta/servidor.log>")
    destino = sys.argv[1]
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    api_key = os.environ.get("RENDER_API_KEY", "")
    web_id = os.environ.get("RENDER_WEB_SERVICE_ID", "")
    db_id = os.environ.get("RENDER_DB_ID", "")
    if not api_key:
        print("AVISO: sin RENDER_API_KEY -- servidor.log queda con los campos en null. "
              "Pedir capturas de la pestaña Metrics de mitrabajo-pruebas y de "
              "mitrabajo-pruebas-db (CPU, RAM, conexiones) para completar el informe.",
              file=sys.stderr)
    print(f"Muestreando cada {INTERVALO_SEGUNDOS}s -> {destino} (Ctrl+C para cortar)")
    with open(destino, "a", encoding="utf-8") as f:
        try:
            while True:
                fila = muestra(api_key, web_id, db_id)
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
                f.flush()
                time.sleep(INTERVALO_SEGUNDOS)
        except KeyboardInterrupt:
            print("Cortado.")
