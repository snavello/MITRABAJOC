"""Colector de métricas de Render -> Grafana Cloud.

Render no guarda historia de CPU y memoria más allá de lo que muestra su panel, y
el 2026-09-18 eso dejó al cuelgue de Pruebas sin datos para analizar. Este script
lee las métricas de la API de Render y las escribe en el Prometheus de Grafana
Cloud, que las conserva. Corre FUERA de Render (GitHub Actions, cada 5 minutos:
.github/workflows/metricas-render.yml), así que si la app o la plataforma se caen,
la historia igual se acumula (regla 0 de docs/chat/2026-09-19-plan-observabilidad.md).

Qué junta, del servicio web y de la base de Pruebas:
  web: CPU y memoria (con sus límites, por instancia), pedidos HTTP por código de
       estado, latencia p95, cantidad de instancias.
  db:  CPU y memoria (con sus límites), conexiones activas, disco usado y capacidad.
Todas salen como `render_*` con las etiquetas `entorno`, `servicio` (web/db) y
`recurso`. Los pedidos HTTP traen además `status_code` y `host`.

Cada corrida vuelve a mandar una ventana de los últimos `ventana_min` minutos (60), no
solo lo último: así una corrida atrasada o perdida (GitHub retrasa las programadas)
no deja un hueco. Grafana Cloud acepta puntos atrasados hasta cerca de 1-2 horas (probado:
1 h sí, 2 h no; error `err-mimir-sample-timestamp-too-old`), así que la corrida siguiente
rellena lo que la anterior no llegó a mandar, siempre que el atraso sea menor que eso. Los
puntos repetidos los descarta Prometheus.

Hay dos vías que corren este mismo código y se cubren entre sí: GitHub Actions y un hilo
dentro de la app (observabilidad/hilo_colector.py).

    RENDER_API_KEY=rnd_... GRAFANA_METRICS_TOKEN=glc_... python observabilidad/colector_render.py
    python observabilidad/colector_render.py --dry-run      # lee de Render, no escribe

Los tokens salen del entorno, nunca de un archivo. Solo usa la biblioteca estándar.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import aplicar_grafana as ag
    import remote_write as rw
else:
    from . import aplicar_grafana as ag
    from . import remote_write as rw

API_RENDER = "https://api.render.com/v1/metrics"

# (métrica de Render, nombre en Prometheus, parámetros extra). Un solo lugar: para
# sumar una métrica se agrega una línea acá, y `render_planes.py`/tableros no cambian.
WEB = [
    ("cpu", "render_cpu_cores", {}),
    ("cpu-limit", "render_cpu_limit_cores", {}),
    ("memory", "render_memory_bytes", {}),
    ("memory-limit", "render_memory_limit_bytes", {}),
    ("http-requests", "render_http_requests", {}),
    ("http-latency", "render_http_latency_p95_seconds", {"quantile": "0.95"}),
    ("instance-count", "render_instance_count", {}),
]
DB = [
    ("cpu", "render_cpu_cores", {}),
    ("cpu-limit", "render_cpu_limit_cores", {}),
    ("memory", "render_memory_bytes", {}),
    ("memory-limit", "render_memory_limit_bytes", {}),
    ("instance-count", "render_instance_count", {}),
    ("active-connections", "render_db_active_connections", {}),
    ("disk-usage", "render_disk_usage_bytes", {}),
    ("disk-capacity", "render_disk_capacity_bytes", {}),
]
METRICAS_POR_SERVICIO = {"web": WEB, "db": DB}
# Etiquetas de Render que pasan a Prometheus con otro nombre; el resto se descarta
# (`resource` y `service` repetirían lo que ya dice `recurso`).
RENOMBRAR = {"statusCode": "status_code", "host": "host", "instance": "instance"}


class ErrorRender(Exception):
    pass


# ---------- Lo que se puede probar sin red ----------

def a_milisegundos(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def convertir(nombre_prometheus: str, series_render: list, base: dict) -> list:
    """De la respuesta de Render (lista de series con `labels` y `values`) a
    series de remote write: [(etiquetas, [(timestamp_ms, valor)])]. Una serie sin
    puntos no se manda. Un valor nulo se descarta en vez de mandarse como 0: un
    cero inventado se confunde con "el CPU está en cero"."""
    salida = []
    for s in series_render or []:
        etiquetas = dict(base, __name__=nombre_prometheus)
        for l in s.get("labels") or []:
            if l.get("field") in RENOMBRAR:
                etiquetas[RENOMBRAR[l["field"]]] = str(l.get("value", ""))
        puntos = [(a_milisegundos(v["timestamp"]), float(v["value"]))
                  for v in (s.get("values") or []) if v.get("value") is not None]
        if puntos:
            salida.append((etiquetas, puntos))
    return salida


def validar_config(cfg: dict) -> list:
    m = cfg.get("metricas_render")
    if not isinstance(m, dict):
        return ["falta la sección 'metricas_render'"]
    errores = []
    if not m.get("entorno"):
        errores.append("metricas_render.entorno está vacío")
    for servicio in ("web", "db"):
        if not str(m.get("recursos", {}).get(servicio, "")).startswith(("srv-", "dpg-")):
            errores.append(f"metricas_render.recursos.{servicio} tiene que ser un id de Render (srv-... o dpg-...)")
    rw_cfg = m.get("remote_write", {})
    if not str(rw_cfg.get("url", "")).startswith("https://") or not rw_cfg.get("usuario"):
        errores.append("metricas_render.remote_write necesita url https:// y usuario")
    if not isinstance(m.get("ventana_min"), int) or not 5 <= m["ventana_min"] <= 120:
        errores.append("metricas_render.ventana_min entre 5 y 120 (minutos)")
    if not isinstance(m.get("resolucion_s"), int) or m["resolucion_s"] < 30:
        errores.append("metricas_render.resolucion_s tiene que ser >= 30")
    return errores


# ---------- Render ----------

def pedir_render(clave: str, metrica: str, recurso: str, inicio: datetime, fin: datetime,
                 resolucion_s: int, extra: dict) -> list:
    """Una métrica de Render. Render limita las consultas (429): se espera y se
    reintenta, en vez de perder la corrida entera por un límite pasajero."""
    q = {"resource": recurso, "resolutionSeconds": str(resolucion_s),
         "startTime": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"), "endTime": fin.strftime("%Y-%m-%dT%H:%M:%SZ")}
    q.update(extra)
    url = f"{API_RENDER}/{metrica}?" + urllib.parse.urlencode(q)
    for intento in range(4):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {clave}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30, context=ag._contexto_tls()) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento < 3:
                time.sleep(min(int(e.headers.get("Retry-After", "15") or 15), 60))
                continue
            raise ErrorRender(f"{metrica} de {recurso}: HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError) as e:
            if intento < 3:
                time.sleep(5)
                continue
            raise ErrorRender(f"{metrica} de {recurso}: {type(e).__name__}")
    raise ErrorRender(f"{metrica} de {recurso}: sin respuesta")


def recolectar(cfg: dict, clave_render: str, ahora: datetime = None, pausa: float = 1.2) -> tuple:
    """Devuelve (series, resumen). Una métrica que falla no tira las demás: queda
    anotada en `resumen['errores']` y el resto se manda igual."""
    m = cfg["metricas_render"]
    ahora = ahora or datetime.now(timezone.utc)
    inicio = ahora - timedelta(minutes=m["ventana_min"])
    series, errores, por_metrica = [], [], {}
    for servicio, lista in METRICAS_POR_SERVICIO.items():
        recurso = m["recursos"][servicio]
        base = {"entorno": m["entorno"], "servicio": servicio, "recurso": recurso}
        for metrica, nombre, extra in lista:
            try:
                crudo = pedir_render(clave_render, metrica, recurso, inicio, ahora, m["resolucion_s"], extra)
                convertidas = convertir(nombre, crudo, base)
                series += convertidas
                por_metrica[f"{servicio}/{metrica}"] = len(convertidas)
            except ErrorRender as e:
                errores.append(str(e))
            time.sleep(pausa)
    return series, {"errores": errores, "series_por_metrica": por_metrica}


def series_de_salud(cfg: dict, ahora: datetime, resumen: dict, via: str = "manual") -> list:
    """Dos series del propio colector. `render_colector_ultima_corrida_segundos`
    permite alertar si el colector se muere (un colector mudo deja los tableros
    congelados sin que nadie lo note: es el mismo problema que se quiere resolver)."""
    m = cfg["metricas_render"]
    t = int(ahora.timestamp() * 1000)
    # `via` dice QUIÉN corrió: "github" (Actions), "app" (el hilo de la app) o "manual".
    # Con dos vías que se cubren, hay que poder ver que las DOS están vivas.
    base = {"entorno": m["entorno"], "via": via}
    return [
        (dict(base, __name__="render_colector_ultima_corrida_segundos"), [(t, ahora.timestamp())]),
        (dict(base, __name__="render_colector_errores"), [(t, float(len(resumen["errores"])))]),
    ]


# Mensajes de Grafana que NO indican un problema con lo que se mandó: puntos repetidos o
# demasiado viejos para la ventana (los demás de la misma tanda sí se guardan).
BENIGNOS = ("out of order", "out-of-order", "duplicate", "too far behind", "too-old", "too old")


def escritura_aceptable(estado: int, texto: str) -> bool:
    return estado < 400 or any(b in texto.lower() for b in BENIGNOS)


def ejecutar(cfg: dict, clave: str, token: str, dry_run: bool = False,
             ahora: datetime = None, pausa: float = 1.2, via: str = "manual") -> dict:
    """Una pasada completa: lee de Render, escribe en Grafana. Lo usan este script y el
    hilo de la app. `ok` es False si Render falló en TODAS las métricas o si Grafana
    rechazó lo escrito por una razón que no es benigna."""
    ahora = ahora or datetime.now(timezone.utc)
    series, resumen = recolectar(cfg, clave, ahora, pausa)
    series += series_de_salud(cfg, ahora, resumen, via)
    r = {"series": len(series), "puntos": sum(len(m) for _, m in series),
         "errores": resumen["errores"], "por_metrica": resumen["series_por_metrica"],
         "estado_http": None, "texto": "", "ok": bool(resumen["series_por_metrica"])}
    if dry_run:
        return r
    rwc = cfg["metricas_render"]["remote_write"]
    r["estado_http"], r["texto"] = rw.escribir(rwc["url"], rwc["usuario"], token, series)
    r["ok"] = r["ok"] and escritura_aceptable(r["estado_http"], r["texto"])
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="lee de Render pero no escribe en Grafana")
    ap.add_argument("--config", default=str(ag.CONFIG))
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cfg = ag.cargar_config(Path(args.config))
    errores = validar_config(cfg)
    if errores:
        print("config.json tiene errores:")
        for e in errores:
            print("  -", e)
        return 2
    clave = os.environ.get("RENDER_API_KEY", "")
    token = os.environ.get("GRAFANA_METRICS_TOKEN", "")
    if not clave or (not token and not args.dry_run):
        print("Faltan RENDER_API_KEY y/o GRAFANA_METRICS_TOKEN.")
        return 2
    r = ejecutar(cfg, clave, token, dry_run=args.dry_run,
                 via="github" if os.environ.get("GITHUB_ACTIONS") else "manual")
    print(f"Render: {r['series']} series, {r['puntos']} puntos, {len(r['errores'])} error(es).")
    for e in r["errores"]:
        print("  ! ", e)
    if args.dry_run:
        for k, v in sorted(r["por_metrica"].items()):
            print(f"   {k}: {v} serie(s)")
        return 0
    print(f"Grafana: HTTP {r['estado_http']} {r['texto']}".rstrip())
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
