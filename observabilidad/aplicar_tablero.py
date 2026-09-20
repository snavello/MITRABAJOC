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

La fila "En vivo" (abajo) NO usa el colector: consulta la API de Render directamente,
cada vez que se abre o se refresca el tablero, con una fuente Infinity que guarda la
clave de Render (`render-vivo`). Sirve para ver el dato de ESTE instante; no guarda
historia (eso lo hace el colector). Para crear la fuente hay que pasar RENDER_API_KEY
la primera vez. Ojo: esa clave da acceso a todo el workspace de Render y queda guardada
en Grafana Cloud (cifrada); si se rota la clave hay que volver a correr este script.

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
FUENTE_VIVO = {"type": "yesoreyeram-infinity-datasource", "uid": "render-vivo"}
# Cuánto hacia atrás muestran los paneles "En vivo": los últimos 10 minutos, a un punto por minuto.
VENTANA_VIVO = "10m"
# La serie con el dato MÁS RECIENTE. Durante un deploy Render devuelve dos instancias (la vieja
# queda sin datos nuevos): sin esto un panel podía mostrar la instancia que ya no existe.
MAS_RECIENTE = "$sort($, function($a,$b){ $a.values[-1].timestamp > $b.values[-1].timestamp })[-1].values"
URL_ACTUALIZAR_GITHUB = "https://github.com/snavello/MITRABAJOC/actions/workflows/metricas-render.yml"
VERDE, ROJO, AMARILLO = "green", "red", "orange"
# Cuánto hacia atrás se busca el último dato de los números de "ahora". El colector
# corre cada 5 minutos pero GitHub retrasa las corridas programadas; con la
# búsqueda normal de Prometheus (5 minutos) un atraso dejaba los números en
# "No data" y, con el color base verde, se veían verdes (pasó a las 21:38 del
# 2026-09-19). Con 30 minutos aguantan un atraso normal, y el número de "Colector"
# dice cuánto es.
BUSQUEDA = "30m"
SIN_DATOS = {"type": "special", "options": {"match": "null+nan",
                                            "result": {"text": "SIN DATOS", "color": "orange", "index": 99}}}


def _objetivo(expr: str, leyenda: str = "", ref: str = "A") -> dict:
    return {"refId": ref, "datasource": FUENTE, "expr": expr, "legendFormat": leyenda,
            "instant": False, "range": True}


def _umbrales(*pasos) -> dict:
    """pasos: (valor_desde, color). El primero es la base (valor None)."""
    return {"mode": "absolute",
            "steps": [{"color": c, "value": (None if i == 0 else v)} for i, (v, c) in enumerate(pasos)]}


def estado(id_: int, titulo: str, expr: str, x: int, y: int, w: int, unidad: str = "none",
           umbrales=None, mapeos=None, decimales=None, descripcion: str = "") -> dict:
    """Un número grande con color. Sin datos se ve "SIN DATOS" en ámbar: nunca un 0
    inventado y, sobre todo, nunca en verde (el color base de los umbrales es verde y
    sin este mapeo un "No data" se veía como buena noticia)."""
    campo = {"unit": unidad, "thresholds": _umbrales(*(umbrales or [(0, VERDE)])),
             "mappings": list(mapeos or []) + [SIN_DATOS], "noValue": "SIN DATOS"}
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


def _consulta_vivo(ref: str, recurso: str, metrica: str, nombre: str) -> dict:
    """Una consulta directa a la API de Render (fuente Infinity). Los límites de tiempo son
    los del panel (`timeFrom`), no los del tablero, así que siempre trae "ahora"."""
    params = [("resource", recurso), ("startTime", "${__from:date:iso}"), ("endTime", "${__to:date:iso}"),
              ("resolutionSeconds", "60")]
    return {"refId": ref, "datasource": FUENTE_VIVO, "type": "json", "source": "url", "format": "table",
            "parser": "backend", "url": f"https://api.render.com/v1/metrics/{metrica}",
            "root_selector": MAS_RECIENTE,
            "columns": [{"selector": "timestamp", "text": "time", "type": "timestamp"},
                        {"selector": "value", "text": nombre, "type": "number"}],
            "url_options": {"method": "GET", "data": "",
                            "params": [{"key": k, "value": v} for k, v in params]}}


def en_vivo(id_: int, titulo: str, consultas: list, x: int, y: int, w: int, unidad: str = "none",
            decimales: int = None, descripcion: str = "") -> dict:
    """Gráfico que consulta a Render en el momento (últimos 10 minutos). `consultas`:
    lista de (recurso, métrica de Render, nombre de la línea)."""
    campo = {"unit": unidad, "custom": {"lineWidth": 2, "fillOpacity": 8, "showPoints": "auto", "spanNulls": True},
             "thresholds": _umbrales((0, VERDE))}
    if decimales is not None:
        campo["decimals"] = decimales
    return {"id": id_, "type": "timeseries", "title": titulo, "description": descripcion,
            "timeFrom": VENTANA_VIVO, "gridPos": {"x": x, "y": y, "w": w, "h": 8}, "datasource": FUENTE_VIVO,
            "targets": [_consulta_vivo(chr(ord("A") + i), r, m, n) for i, (r, m, n) in enumerate(consultas)],
            "fieldConfig": {"defaults": campo, "overrides": []},
            "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True,
                                   "calcs": ["lastNotNull", "max"]},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def fila(id_: int, titulo: str, y: int) -> dict:
    return {"id": id_, "type": "row", "title": titulo, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def texto(id_: int, titulo: str, markdown: str, x: int, y: int, w: int, h: int = 4) -> dict:
    return {"id": id_, "type": "text", "title": titulo, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"mode": "markdown", "content": markdown}}


def construir_tablero(cfg: dict) -> dict:
    u = cfg["uptime"]
    ent = cfg["metricas_render"]["entorno"]
    app, base = (c["job"] for c in u["checks"][:2])
    web, db = cfg["metricas_render"]["recursos"]["web"], cfg["metricas_render"]["recursos"]["db"]
    E = f'entorno="{ent}"'
    OK_CAIDA = [{"type": "value", "options": {"1": {"text": "OK", "color": VERDE},
                                               "0": {"text": "CAÍDA", "color": ROJO}}}]

    def pct(m, lim, servicio):
        return (f'100 * max(last_over_time({m}{{{E},servicio="{servicio}"}}[{BUSQUEDA}]) / '
                f'last_over_time({lim}{{{E},servicio="{servicio}"}}[{BUSQUEDA}]))')

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
        estado(9, "Conexiones a la base", f'max(last_over_time(render_db_active_connections{{{E}}}[{BUSQUEDA}]))', 16, 4, 4, decimales=0,
               descripcion="Conexiones activas ahora. El pool de la app es de 10 por proceso."),
        estado(10, "Disco de la base",
               f'100 * max(last_over_time(render_disk_usage_bytes{{{E}}}[{BUSQUEDA}]) / last_over_time(render_disk_capacity_bytes{{{E}}}[{BUSQUEDA}]))', 20, 4, 4,
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
        # ---- En vivo: consulta directa a Render, sin pasar por el colector ----
        fila(21, "En vivo: consulta directa a Render en este momento (últimos 10 minutos, sin historia)", 48),
        en_vivo(22, "CPU de la app: uso y límite del plan (núcleos)",
                [(web, "cpu", "uso"), (web, "cpu-limit", "límite")], 0, 49, 12, decimales=3,
                descripcion="Directo de Render. Para tener historia, el colector."),
        en_vivo(23, "Memoria de la app: uso y límite del plan",
                [(web, "memory", "uso"), (web, "memory-limit", "límite")], 12, 49, 12, unidad="bytes"),
        en_vivo(24, "CPU de la base: uso y límite del plan (núcleos)",
                [(db, "cpu", "uso"), (db, "cpu-limit", "límite")], 0, 57, 12, decimales=3),
        en_vivo(25, "Memoria de la base: uso y límite del plan",
                [(db, "memory", "uso"), (db, "memory-limit", "límite")], 12, 57, 12, unidad="bytes"),
        en_vivo(26, "Conexiones activas a la base", [(db, "active-connections", "conexiones")], 0, 65, 12, decimales=0),
        en_vivo(27, "Disco de la base: usado y capacidad",
                [(db, "disk-usage", "usado"), (db, "disk-capacity", "capacidad")], 12, 65, 12, unidad="bytes"),
    ]
    return {
        "uid": cfg["grafana"]["tablero_uid"], "title": cfg["grafana"]["tablero_titulo"],
        "tags": ["colm3na", ent, "estado"], "timezone": "browser", "schemaVersion": 39, "version": 0,
        "refresh": "1m", "time": {"from": "now-6h", "to": "now"}, "editable": True,
        "annotations": {"list": []}, "templating": {"list": []}, "panels": paneles,
        # Actualizar los datos del colector a pedido. Los dos caminos son independientes: el de
        # GitHub sirve aunque la app esté caída; el de Entornos es más cómodo cuando anda.
        "links": [
            {"title": "Actualizar datos de Render ahora (GitHub: Run workflow)", "type": "link",
             "url": URL_ACTUALIZAR_GITHUB, "targetBlank": True, "icon": "bolt",
             "tooltip": "Abre el workflow en GitHub: tocá 'Run workflow'. En ~30 s el tablero tiene datos nuevos. No depende de la app."},
            {"title": "Actualizar desde Entornos (botón en la app)", "type": "link",
             "url": cfg["uptime"]["base_url"].rstrip("/") + "/entornos#observabilidad", "targetBlank": True,
             "icon": "external-link-alt",
             "tooltip": "Botón 'Actualizar métricas ahora' de la pestaña Observabilidad. Necesita que la app esté viva y el PIN."},
        ],
    }


def validar_tablero(cfg: dict) -> list:
    g = cfg.get("grafana", {})
    errores = [f"grafana.{k} está vacío" for k in ("tablero_uid", "tablero_titulo") if not g.get(k)]
    return errores + ag.validar(cfg)


def payload_fuente_render(clave: str) -> dict:
    """La fuente que consulta la API de Render. Solo puede hablar con api.render.com."""
    return {"name": "Render (API en vivo)", "uid": "render-vivo", "type": "yesoreyeram-infinity-datasource",
            "access": "proxy", "isDefault": False,
            "jsonData": {"auth_method": "bearerToken", "allowedHosts": ["https://api.render.com"],
                         "timeoutInSeconds": 30},
            "secureJsonData": {"bearerToken": clave}}


def asegurar_fuente_render(g, clave: str) -> str:
    estado, actual = g.pedir("GET", "/api/datasources/uid/render-vivo")
    cuerpo = payload_fuente_render(clave)
    if estado == 200:
        estado, resp = g.pedir("PUT", "/api/datasources/uid/render-vivo", dict(cuerpo, id=actual["id"], version=actual.get("version", 1)))
        verbo = "actualizada"
    else:
        estado, resp = g.pedir("POST", "/api/datasources", cuerpo)
        verbo = "creada"
    if estado != 200:
        raise SystemExit(f"No se pudo guardar la fuente de Render ({estado}): {resp}")
    return f"fuente 'Render (API en vivo)': {verbo}"


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
    g = ag.Grafana(os.environ.get("GRAFANA_URL", cfg["grafana"]["url"]), token)
    clave_render = os.environ.get("RENDER_API_KEY", "")
    if clave_render:
        print(asegurar_fuente_render(g, clave_render))
    elif g.pedir("GET", "/api/datasources/uid/render-vivo")[0] != 200:
        print("AVISO: no existe la fuente 'render-vivo'; los paneles \"En vivo\" no van a mostrar datos. "
              "Correr con RENDER_API_KEY para crearla.")
    print(aplicar(g, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
