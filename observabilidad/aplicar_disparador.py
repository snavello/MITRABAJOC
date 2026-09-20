"""Disparador del colector de métricas: Grafana le pide a GitHub que lo corra.

Por qué existe: el cron de GitHub Actions es "best effort". Su documentación admite que
las corridas programadas se demoran o se descartan con mucha carga, y en este repo el
workflow del colector estuvo más de una hora sin dispararse ni una vez (2026-09-19). Un
`workflow_dispatch` en cambio corre al instante. Entonces el reloj lo pone algo puntual:
un check del monitor de uptime de Grafana Cloud (Synthetic Monitoring), que cada 5
minutos hace un POST a la API de GitHub pidiendo correr el workflow.

    Grafana (puntual)  --POST /dispatches-->  GitHub Actions  --corre-->  colector  -->  Grafana

Es independiente de Render y de la app, así que respeta la regla 0. Tampoco reemplaza a
las otras vías (el cron de GitHub y el hilo de la app): es una tercera, y las tres
escriben lo mismo. Si GitHub además corriera el cron, habría corridas de más; el
workflow tiene `concurrency` y las series repetidas las descarta Prometheus.

El token es un token de GitHub de grano fino, limitado a ESTE repositorio y con un solo
permiso (Actions: read and write). Vive en la configuración del check, dentro de Grafana
Cloud. Si vence o se revoca, el check falla y hay una alerta que lo dice.

    GITHUB_DISPATCH_TOKEN=github_pat_... GRAFANA_TOKEN=glsa_... python observabilidad/aplicar_disparador.py
    python observabilidad/aplicar_disparador.py --dry-run     # sin red

Idempotente. Ninguno de los dos tokens va en un archivo.
"""
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import aplicar_grafana as ag
    import aplicar_uptime as up
    import reglas
else:
    from . import aplicar_grafana as ag
    from . import aplicar_uptime as up
    from . import reglas

SEGUNDOS_POR_MES = 30 * 24 * 3600


def validar_disparador(cfg: dict) -> list:
    d = cfg.get("disparador")
    if not isinstance(d, dict):
        return ["falta la sección 'disparador'"]
    errores = []
    for clave in ("job", "repo", "workflow", "ref", "probe", "alerta", "evento"):
        if not d.get(clave):
            errores.append(f"disparador.{clave} está vacío")
    if "/" not in str(d.get("repo", "")):
        errores.append("disparador.repo tiene que ser dueño/repositorio")
    if not isinstance(d.get("frecuencia_s"), int) or not 120 <= d["frecuencia_s"] <= 3600:
        errores.append("disparador.frecuencia_s entre 120 y 3600")
    if not isinstance(d.get("falla_minutos"), int) or d["falla_minutos"] < 1:
        errores.append("disparador.falla_minutos tiene que ser un entero >= 1")
    if not errores:
        total = up.ejecuciones_por_mes(cfg) + ejecuciones_por_mes(cfg)
        if total > cfg["uptime"]["tope_ejecuciones_mes"]:
            errores.append(f"con el disparador las ejecuciones por mes ({total}) pasan del tope "
                           f"({cfg['uptime']['tope_ejecuciones_mes']})")
    return errores


def ejecuciones_por_mes(cfg: dict) -> int:
    return SEGUNDOS_POR_MES // cfg["disparador"]["frecuencia_s"]        # una sola ubicación


def url_de_disparo(cfg: dict) -> str:
    d = cfg["disparador"]
    return f"https://api.github.com/repos/{d['repo']}/actions/workflows/{d['workflow']}/dispatches"


def payload_check(cfg: dict, token: str, id_probe: int, existente: dict = None) -> dict:
    d = cfg["disparador"]
    cuerpo = {
        "job": d["job"], "target": url_de_disparo(cfg),
        "frequency": d["frecuencia_s"] * 1000, "timeout": 10000, "enabled": True,
        "alertSensitivity": "none", "basicMetricsOnly": True, "probes": [id_probe],
        "labels": [{"name": "entorno", "value": cfg["uptime"]["entorno"]}, {"name": "servicio", "value": "disparador"}],
        "settings": {"http": {
            "method": "POST", "ipVersion": "V4", "noFollowRedirects": False, "failIfNotSSL": True,
            "validStatusCodes": [204],                       # GitHub contesta 204 sin cuerpo al aceptar el pedido
            "body": json.dumps({"ref": d["ref"]}),
            "headers": [{"name": "Accept", "value": "application/vnd.github+json"},
                        {"name": "Authorization", "value": f"Bearer {token}"},
                        {"name": "X-GitHub-Api-Version", "value": "2022-11-28"},
                        {"name": "Content-Type", "value": "application/json"}],
        }},
    }
    if existente:
        cuerpo["id"], cuerpo["tenantId"] = existente["id"], existente["tenantId"]
    return cuerpo


def payload_regla(cfg: dict) -> dict:
    d = cfg["disparador"]
    return reglas.regla_umbral(
        uid=f"colm3na-{cfg['uptime']['entorno']}-{d['evento']}", titulo=d["alerta"], grupo="disparador",
        carpeta_uid=cfg["grafana"]["carpeta_uid"],
        expr=f'max by (job) (probe_success{{job="{d["job"]}"}})',
        operador="lt", umbral=1, para_minutos=d["falla_minutos"],
        labels={"entorno": cfg["uptime"]["entorno"], "evento": d["evento"]},
        resumen=d["alerta"],
        descripcion=("Grafana no logra pedirle a GitHub que corra el colector de métricas: el token de GitHub "
                     "venció o fue revocado, o el workflow cambió de nombre. Sin este disparador el colector "
                     "depende del cron de GitHub, que se atrasa. Crear un token nuevo y volver a correr "
                     "observabilidad/aplicar_disparador.py."),
        sin_datos="NoData")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(ag.CONFIG))
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = ag.cargar_config(Path(args.config))
    errores = ag.validar(cfg) + up.validar_uptime(cfg) + validar_disparador(cfg)
    if errores:
        print("config.json tiene errores, no se toca Grafana:")
        for e in errores:
            print("  -", e)
        return 2
    d = cfg["disparador"]
    total = up.ejecuciones_por_mes(cfg) + ejecuciones_por_mes(cfg)
    print(f"Ejecuciones por mes con el disparador: {total:,} de {cfg['uptime']['tope_ejecuciones_mes']:,}".replace(",", "."))
    if args.dry_run:
        print(f" · check {d['job']}: POST {url_de_disparo(cfg)} cada {d['frecuencia_s']} s desde {d['probe']}")
        print(f" · regla '{d['alerta']}': dispara tras {d['falla_minutos']} min de fallas")
        return 0
    gt, gh_token = os.environ.get("GRAFANA_TOKEN", ""), os.environ.get("GITHUB_DISPATCH_TOKEN", "")
    if not gt or not gh_token:
        print("Faltan GRAFANA_TOKEN y/o GITHUB_DISPATCH_TOKEN.")
        return 2
    g = ag.Grafana(os.environ.get("GRAFANA_URL", cfg["grafana"]["url"]), gt)
    base_sm = f"/api/datasources/proxy/uid/{up.uid_de_synthetic(g)}"
    (id_probe,) = up.ids_de_ubicaciones(g, base_sm, [d["probe"]])
    estado, checks = g.pedir("GET", f"{base_sm}/sm/check/list")
    existente = next((c for c in (checks if estado == 200 else []) if c["job"] == d["job"]), None)
    estado, resp = g.pedir("POST", f"{base_sm}/sm/check/{'update' if existente else 'add'}",
                           payload_check(cfg, gh_token, id_probe, existente))
    if estado not in (200, 201):
        raise SystemExit(f"No se pudo guardar el check ({estado}): {resp}")
    print(f" · check {d['job']}: {'actualizado' if existente else 'creado'}")
    print(f" · regla '{d['alerta']}': {reglas.guardar_regla(g, payload_regla(cfg))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
