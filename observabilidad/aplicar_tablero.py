"""Tablero "Estado general" de Pruebas en Grafana Cloud, como código.

Arriba, el estado general en dos filas de números (¿la app y la base responden?,
¿cuánto CPU/memoria/disco/conexiones se están usando?, ¿el colector de métricas
sigue vivo?). Abajo, el detalle con historia: CPU y memoria de la app y de la base,
pedidos y latencia por código de estado, conexiones y disco de la base, latencia del
monitor de uptime por ubicación.

Los datos salen de dos fuentes, las dos guardadas FUERA de Render: el monitor de
uptime (Synthetic Monitoring, `probe_*`) y el colector de métricas de Render
(`render_*`, observabilidad/colector_render.py). Si la app cae, el tablero sigue
mostrando qué pasó.

    GRAFANA_TOKEN=glsa_... python observabilidad/aplicar_tablero.py
    python observabilidad/aplicar_tablero.py --dry-run   # imprime el JSON, sin red
    python observabilidad/aplicar_tablero.py --json      # solo el JSON del tablero

Idempotente: vuelve a escribir el tablero con el mismo uid. Un cambio hecho a mano
en la interfaz se pisa: el código es la fuente de verdad (para conservar un cambio,
llevarlo a `construir_tablero`).
"""
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import aplicar_grafana as ag
else:
    from . import aplicar_grafana as ag

FUENTE = {"type": "prometheus", "uid": "grafanacloud-prom"}
VERDE, ROJO, AMARILLO = "green", "red", "orange"


def _objetivo(expr: str, leyenda: str = "", ref: str = "A") -> dict:
    return {"refId": ref, "datasource": FUENTE, "expr": expr, "legendFormat": leyenda,
            "instant": False, "range": True}


def _umbrales(*pasos) -> dict:
    """pasos: (valor_desde, color). El primero es la base (valor None)."""
    return {"mode": "absolute",
            "steps": [{"color": c, "value": (None if i == 0 else v)} for i, (v, c) in enumerate(pasos)]}


def estado(id_: int, titulo: str, expr: str, x: int, y: int, w: int, unidad: str = "none",
           umbrales=None, mapeos=None, decimales=None, descripcion: str = "") -> dict:
    """Un número grande con color. Sin datos se ve "Sin datos", nunca un 0 inventado."""
    campo = {"unit": unidad, "thresholds": _umbrales(*(umbrales or [(0, VERDE)])), "mappings": mapeos or []}
    if decimales is not None:
        campo["decimals"] = decimales
    return {"id": id_, "type": "stat", "title": titulo, "description": descripcion,
            "gridPos": {"x": x, "y": y, "w": w, "h": 4}, "datasource": FUENTE,
            "targets": [dict(_objetivo(expr), instant=True, range=False)],
            "fieldConfig": {"defaults": campo, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "background", "graphMode": "none", "textMode": "value",
                        "justifyMode": "center"}}


def serie(id_: int, titulo: str, objetivos: list, x: int, y: int, w: int, unidad: str = "none",
          linea_umbral=None, minimo=None, maximo=None, apilado: bool = False, descripcion: str = "") -> dict:
    campo = {"unit": unidad, "custom": {"lineWidth": 2, "fillOpacity": 18 if apilado else 8,
                                          "showPoints": "never", "spanNulls": False,
                                          "stacking": {"mode": "normal" if apilado else "none"},
                                          "thresholdsStyle": {"mode": "line" if linea_umbral else "off"}},
             "thresholds": _umbrales((0, VERDE), (linea_umbral, ROJO)) if linea_umbral else _umbrales((0, VERDE))}
    if minimo is not None:
        campo["min"] = minimo
    if maximo is not None:
        campo["max"] = maximo
    return {"id": id_, "type": "timeseries", "title": titulo, "description": descripcion,
            "gridPos": {"x": x, "y": y, "w": w, "h": 8}, "datasource": FUENTE,
            "targets": [_objetivo(e, l, chr(ord("A") + i)) for i, (e, l) in enumerate(objetivos)],
            "fieldConfig": {"defaults": campo, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def texto(id_: int, titulo: str, markdown: str, x: int, y: int, w: int, h: int = 4) -> dict:
    return {"id": id_, "type": "text", "title": titulo, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"mode": "markdown", "content": markdown}}


def construir_tablero(cfg: dict) -> dict:
    u = cfg["uptime"]
    ent = cfg["metricas_render"]["entorno"]
    app, base = (c["job"] for c in u["checks"][:2])
    E = f'entorno="{ent}"'
    OK_CAIDA = [{"type": "value", "options": {"1": {"text": "OK", "color": VERDE},
                                               "0": {"text": "CAÍDA", "color": ROJO}}}]

    def pct(m, lim, servicio):
        return f'100 * max({m}{{{E},servicio="{servicio}"}} / {lim}{{{E},servicio="{servicio}"}})'

    paneles = [
        # ---- Fila 1: ¿responden? y ¿el colector vive? ----
        estado(1, "App (¿responde?)", f'max(probe_success{{job="{app}"}})', 0, 0, 6, mapeos=OK_CAIDA,
               umbrales=[(0, ROJO), (1, VERDE)], descripcion="/healthz visto desde afuera. OK si alguna ubicación lo ve."),
        estado(2, "Base (¿responde?)", f'max(probe_success{{job="{base}"}})', 6, 0, 6, mapeos=OK_CAIDA,
               umbrales=[(0, ROJO), (1, VERDE)], descripcion="/readyz: un SELECT 1 a la base, con techo de 2 s."),
        estado(3, "Latencia de la app", f'avg(probe_duration_seconds{{job="{app}"}})', 12, 0, 6, unidad="s",
               umbrales=[(0, VERDE), (1, AMARILLO), (3, ROJO)], decimales=2,
               descripcion="Tiempo de /healthz, promedio entre ubicaciones."),
        estado(4, "Colector de métricas (minutos desde su última corrida)",
               f'(time() - max(last_over_time(render_colector_ultima_corrida_segundos{{{E}}}[6h]))) / 60', 18, 0, 6, unidad="m",
               umbrales=[(0, VERDE), (15, AMARILLO), (30, ROJO)], decimales=0,
               descripcion="Si sube de 30, el tablero de abajo está congelado: el colector dejó de correr."),
        # ---- Fila 2: cuánto se usa ----
        estado(5, "CPU de la app", pct("render_cpu_cores", "render_cpu_limit_cores", "web"), 0, 4, 4, unidad="percent",
               umbrales=[(0, VERDE), (70, AMARILLO), (95, ROJO)], decimales=0),
        estado(6, "Memoria de la app", pct("render_memory_bytes", "render_memory_limit_bytes", "web"), 4, 4, 4,
               unidad="percent", umbrales=[(0, VERDE), (70, AMARILLO), (95, ROJO)], decimales=0),
        estado(7, "CPU de la base", pct("render_cpu_cores", "render_cpu_limit_cores", "db"), 8, 4, 4, unidad="percent",
               umbrales=[(0, VERDE), (70, AMARILLO), (95, ROJO)], decimales=0),
        estado(8, "Memoria de la base", pct("render_memory_bytes", "render_memory_limit_bytes", "db"), 12, 4, 4,
               unidad="percent", umbrales=[(0, VERDE), (70, AMARILLO), (95, ROJO)], decimales=0),
        estado(9, "Conexiones a la base", f'max(render_db_active_connections{{{E}}})', 16, 4, 4, decimales=0,
               descripcion="Conexiones activas ahora. El pool de la app es de 10 por proceso."),
        estado(10, "Disco de la base",
               f'100 * max(render_disk_usage_bytes{{{E}}} / render_disk_capacity_bytes{{{E}}})', 20, 4, 4,
               unidad="percent", umbrales=[(0, VERDE), (70, AMARILLO), (85, ROJO)], decimales=1),
        # ---- Detalle con historia ----
        serie(11, "CPU (% del límite del plan)",
              [(f'100 * max by (servicio) (render_cpu_cores{{{E}}} / render_cpu_limit_cores{{{E}}})', "{{servicio}}")],
              0, 8, 12, unidad="percent", linea_umbral=95, minimo=0,
              descripcion="La línea roja es el 95 %, el umbral de alerta (sostenido más de 30 minutos)."),
        serie(12, "Memoria (% del límite del plan)",
              [(f'100 * max by (servicio) (render_memory_bytes{{{E}}} / render_memory_limit_bytes{{{E}}})', "{{servicio}}")],
              12, 8, 12, unidad="percent", linea_umbral=95, minimo=0),
        serie(13, "Pedidos por minuto, por código de estado",
              [(f'sum by (status_code) (render_http_requests{{{E}}})', "{{status_code}}")],
              0, 16, 12, apilado=True, descripcion="Cada punto es lo que Render contó en ese minuto."),
        serie(14, "Latencia p95 por código de estado",
              [(f'max by (status_code) (render_http_latency_p95_seconds{{{E}}})', "{{status_code}}")],
              12, 16, 12, unidad="s", minimo=0),
        serie(15, "% de respuestas con error del servidor (5xx)",
              [(f'100 * (sum(render_http_requests{{{E},status_code=~"5.."}}) or vector(0)) / sum(render_http_requests{{{E}}})', "5xx")],
              0, 24, 12, unidad="percent", linea_umbral=5, minimo=0,
              descripcion="0 % si no hubo errores. Sin pedidos en el minuto no hay porcentaje. La línea roja es el 5 %."),
        serie(16, "Conexiones activas a la base",
              [(f'max(render_db_active_connections{{{E}}})', "conexiones")], 12, 24, 12, minimo=0),
        serie(17, "Disco de la base",
              [(f'max(render_disk_usage_bytes{{{E}}})', "usado"), (f'max(render_disk_capacity_bytes{{{E}}})', "capacidad")],
              0, 32, 12, unidad="bytes", minimo=0),
        serie(18, "Latencia del monitor de uptime, por ubicación y check",
              [('avg by (job, probe) (probe_duration_seconds{job=~"colm3na-%s-.*"})' % ent, "{{job}} · {{probe}}")],
              12, 32, 12, unidad="s", minimo=0,
              descripcion="Lo que ve el monitor desde afuera; no depende de la app."),
        serie(19, "Instancias del servicio web y de la base",
              [(f'max by (servicio) (render_instance_count{{{E}}})', "{{servicio}}")], 0, 40, 12, minimo=0),
        texto(20, "Detalle por sindicato",
              "Pendiente: requiere métricas propias de la app (con el ID del sindicato, nunca datos de personas). "
              "Ver `docs/chat/2026-09-19-plan-observabilidad.md`, pendiente 8.", 12, 40, 12, h=8),
    ]
    return {
        "uid": cfg["grafana"]["tablero_uid"], "title": cfg["grafana"]["tablero_titulo"],
        "tags": ["colm3na", ent, "estado"], "timezone": "browser", "schemaVersion": 39, "version": 0,
        "refresh": "1m", "time": {"from": "now-6h", "to": "now"}, "editable": True,
        "annotations": {"list": []}, "templating": {"list": []}, "panels": paneles,
    }


def validar_tablero(cfg: dict) -> list:
    g = cfg.get("grafana", {})
    errores = [f"grafana.{k} está vacío" for k in ("tablero_uid", "tablero_titulo") if not g.get(k)]
    return errores + ag.validar(cfg)


def aplicar(g, cfg: dict) -> str:
    tablero = construir_tablero(cfg)
    estado_http, resp = g.pedir("POST", "/api/dashboards/db", {
        "dashboard": tablero, "folderUid": cfg["grafana"]["carpeta_uid"], "overwrite": True,
        "message": "aplicar_tablero.py (el código es la fuente de verdad)"})
    if estado_http != 200:
        raise SystemExit(f"No se pudo guardar el tablero ({estado_http}): {resp}")
    return f"tablero '{tablero['title']}': guardado -> {g.url}{resp.get('url', '')}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="imprime el JSON del tablero y sale")
    ap.add_argument("--config", default=str(ag.CONFIG))
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = ag.cargar_config(Path(args.config))
    errores = validar_tablero(cfg)
    if errores:
        print("config.json tiene errores, no se toca Grafana:")
        for e in errores:
            print("  -", e)
        return 2
    if args.json:
        print(json.dumps(construir_tablero(cfg), indent=2, ensure_ascii=False))
        return 0
    n = len(construir_tablero(cfg)["panels"])
    if args.dry_run:
        print(f"Tablero '{cfg['grafana']['tablero_titulo']}': {n} paneles (dry-run, no se escribe).")
        return 0
    token = os.environ.get("GRAFANA_TOKEN", "")
    if not token:
        print("Falta GRAFANA_TOKEN (una cuenta de servicio de Grafana, glsa_...).")
        return 2
    print(aplicar(ag.Grafana(os.environ.get("GRAFANA_URL", cfg["grafana"]["url"]), token), cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
