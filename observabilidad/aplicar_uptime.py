"""Monitor de uptime de Pruebas (Synthetic Monitoring de Grafana Cloud) y sus alertas.

Para cada check de observabilidad/config.json ("uptime") crea o actualiza, de forma
idempotente:

1. Un check HTTP que pega desde afuera, cada `frecuencia_s`, a la app de Pruebas
   (`/healthz`: ¿la app vive?; `/readyz`: ¿la base contesta?), desde las ubicaciones
   de `probes`.
2. Una regla de alerta en la carpeta de Pruebas, que avisa por el punto de contacto
   ya configurado (aplicar_grafana.py) SOLO si fallan TODAS las ubicaciones a la
   vez durante `falla_minutos` seguidos: un problema de una sola ubicación no es
   una caída, y un mail por eso es el ruido que se quiere evitar.

Un problema del propio monitor (dejó de reportar) NO se calla: la regla queda en
"NoData" y avisa, porque quedarse ciego sin enterarse es peor que un falso aviso.

    GRAFANA_TOKEN=glsa_... python observabilidad/aplicar_uptime.py
    python observabilidad/aplicar_uptime.py --dry-run      # sin red: qué crearía

El token es una cuenta de servicio de Grafana (rol Admin o Editor). No va en ningún
archivo. Solo usa la biblioteca estándar.
"""
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):                       # `python observabilidad/aplicar_uptime.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import aplicar_grafana as ag
    import reglas
else:                                               # importado como parte del paquete
    from . import aplicar_grafana as ag
    from . import reglas

SEGUNDOS_POR_MES = 30 * 24 * 3600
ETIQUETA_DE_SERVICIO = {"app": "app", "base": "base"}


# ---------- Lo que se puede probar sin red ----------

def validar_uptime(cfg: dict) -> list:
    """Problemas de la sección "uptime"; vacía si está bien."""
    u = cfg.get("uptime")
    if not isinstance(u, dict):
        return ["falta la sección 'uptime'"]
    errores = []
    if not str(u.get("base_url", "")).startswith("https://"):
        errores.append("uptime.base_url tiene que empezar con https://")
    if not u.get("entorno"):
        errores.append("uptime.entorno está vacío")
    if not isinstance(u.get("probes"), list) or not u["probes"]:
        errores.append("uptime.probes tiene que ser una lista no vacía")
    if not isinstance(u.get("tope_ejecuciones_mes"), int) or u["tope_ejecuciones_mes"] <= 0:
        errores.append("uptime.tope_ejecuciones_mes tiene que ser un entero positivo")
    checks = u.get("checks")
    if not isinstance(checks, list) or not checks:
        return errores + ["uptime.checks tiene que ser una lista no vacía"]
    vistos = set()
    for c in checks:
        nombre = c.get("id", "?")
        for clave in ("id", "job", "ruta", "alerta", "evento"):
            if not c.get(clave):
                errores.append(f"check {nombre}: falta '{clave}'")
        if not str(c.get("ruta", "")).startswith("/"):
            errores.append(f"check {nombre}: la ruta tiene que empezar con /")
        if not isinstance(c.get("frecuencia_s"), int) or not 60 <= c["frecuencia_s"] <= 3600:
            errores.append(f"check {nombre}: frecuencia_s entre 60 y 3600")
        if not isinstance(c.get("timeout_s"), int) or not 1 <= c["timeout_s"] <= 10:
            errores.append(f"check {nombre}: timeout_s entre 1 y 10 (el máximo de Synthetic Monitoring para HTTP)")
        if isinstance(c.get("frecuencia_s"), int) and isinstance(c.get("timeout_s"), int) \
                and c["timeout_s"] >= c["frecuencia_s"]:
            errores.append(f"check {nombre}: timeout_s tiene que ser menor que frecuencia_s")
        if not isinstance(c.get("falla_minutos"), int) or c["falla_minutos"] < 1:
            errores.append(f"check {nombre}: falla_minutos tiene que ser un entero >= 1")
        if c.get("id") in vistos or c.get("job") in vistos:
            errores.append(f"check {nombre}: id o job repetido")
        vistos.update({c.get("id"), c.get("job")})
    if not errores and ejecuciones_por_mes(cfg) > u["tope_ejecuciones_mes"]:
        errores.append(f"las ejecuciones por mes ({ejecuciones_por_mes(cfg)}) pasan del tope "
                       f"({u['tope_ejecuciones_mes']}): bajar la frecuencia o las ubicaciones")
    return errores


def ejecuciones_por_mes(cfg: dict) -> int:
    """Cuántas ejecuciones factura Synthetic Monitoring en un mes de 30 días:
    una por cada check, por cada ubicación, en cada intervalo."""
    u = cfg["uptime"]
    return sum(SEGUNDOS_POR_MES // c["frecuencia_s"] * len(u["probes"]) for c in u["checks"])


def payload_check(cfg: dict, chk: dict, ids_probes: list, existente: dict = None) -> dict:
    u = cfg["uptime"]
    cuerpo = {
        "job": chk["job"],
        "target": u["base_url"].rstrip("/") + chk["ruta"],
        "frequency": chk["frecuencia_s"] * 1000,
        "timeout": chk["timeout_s"] * 1000,
        "enabled": True,
        "alertSensitivity": "none",       # las alertas son las de Grafana, no las nativas de SM
        "basicMetricsOnly": True,
        "probes": ids_probes,
        "labels": [{"name": "entorno", "value": u["entorno"]},
                   {"name": "servicio", "value": ETIQUETA_DE_SERVICIO.get(chk["id"], chk["id"])}],
        "settings": {"http": {
            "method": "GET", "ipVersion": "V4", "noFollowRedirects": False, "failIfNotSSL": False,
            "validStatusCodes": [200],
            # Los dos endpoints devuelven {"ok": true}: un 200 con otro cuerpo (la página
            # de error de un proxy, por ejemplo) no cuenta como "la app vive".
            "failIfBodyNotMatchesRegexp": ['"ok"\\s*:\\s*true'],
        }},
    }
    if existente:
        cuerpo["id"], cuerpo["tenantId"] = existente["id"], existente["tenantId"]
    return cuerpo


def uid_de_regla(cfg: dict, chk: dict) -> str:
    return f"colm3na-{cfg['uptime']['entorno']}-{chk['evento']}"


def payload_regla(cfg: dict, chk: dict) -> dict:
    """Regla de Grafana: dispara si probe_success, tomando el MEJOR resultado entre
    todas las ubicaciones, es menor que 1 durante `falla_minutos` seguidos."""
    u = cfg["uptime"]
    return reglas.regla_umbral(
        uid=uid_de_regla(cfg, chk), titulo=chk["alerta"], grupo="uptime",
        carpeta_uid=cfg["grafana"]["carpeta_uid"],
        expr=f'max by (job) (probe_success{{job="{chk["job"]}"}})',
        operador="lt", umbral=1, para_minutos=chk["falla_minutos"],
        labels={"entorno": u["entorno"], "evento": chk["evento"]},
        resumen=chk["alerta"],
        descripcion=f"{chk['descripcion']} Desde {', '.join(u['probes'])} durante "
                    f"más de {chk['falla_minutos']} minutos.",
        sin_datos="NoData")            # el monitor dejó de reportar: se avisa, no se calla


# ---------- Grafana ----------

def uid_de_synthetic(g) -> str:
    estado, fuentes = g.pedir("GET", "/api/datasources")
    if estado != 200:
        raise SystemExit(f"No se pudieron leer los datasources ({estado}): {fuentes}")
    sm = next((x for x in fuentes if x.get("type") == "synthetic-monitoring-datasource"), None)
    if not sm:
        raise SystemExit("Synthetic Monitoring no está inicializado en este stack "
                         "(Testing & synthetics -> Synthetics -> Initialize).")
    return sm["uid"]


def ids_de_ubicaciones(g, base_sm: str, nombres: list) -> list:
    estado, probes = g.pedir("GET", f"{base_sm}/sm/probe/list")
    if estado != 200:
        raise SystemExit(f"No se pudieron leer las ubicaciones ({estado}): {probes}")
    por_nombre = {p["name"]: p for p in probes}
    faltan = [n for n in nombres if n not in por_nombre or not por_nombre[n].get("online")]
    if faltan:
        disponibles = ", ".join(sorted(n for n, p in por_nombre.items() if p.get("online")))
        raise SystemExit(f"Ubicaciones inexistentes o fuera de línea: {faltan}. Disponibles: {disponibles}")
    return [por_nombre[n]["id"] for n in nombres]


def asegurar_check(g, base_sm: str, cfg: dict, chk: dict, ids: list, dry: bool) -> str:
    estado, checks = g.pedir("GET", f"{base_sm}/sm/check/list")
    if estado != 200:
        raise SystemExit(f"No se pudieron leer los checks ({estado}): {checks}")
    existente = next((c for c in checks if c["job"] == chk["job"]), None)
    cuerpo = payload_check(cfg, chk, ids, existente)
    if dry:
        return f"check {chk['job']}: {'lo actualizaría' if existente else 'lo crearía'} ({cuerpo['target']})"
    ruta = "/sm/check/update" if existente else "/sm/check/add"
    estado, resp = g.pedir("POST", base_sm + ruta, cuerpo)
    if estado not in (200, 201):
        raise SystemExit(f"No se pudo guardar el check {chk['job']} ({estado}): {resp}")
    return f"check {chk['job']}: {'actualizado' if existente else 'creado'} -> {cuerpo['target']}"


def asegurar_regla(g, cfg: dict, chk: dict, dry: bool) -> str:
    cuerpo = payload_regla(cfg, chk)
    estado, existente = g.pedir("GET", f"/api/v1/provisioning/alert-rules/{cuerpo['uid']}")
    if dry:
        return f"regla '{chk['alerta']}': {'la actualizaría' if estado == 200 else 'la crearía'}"
    if estado == 200:
        estado, resp = g.pedir("PUT", f"/api/v1/provisioning/alert-rules/{cuerpo['uid']}", cuerpo,
                               editable_desde_la_ui=True)
        verbo = "actualizada"
    else:
        estado, resp = g.pedir("POST", "/api/v1/provisioning/alert-rules", cuerpo,
                               editable_desde_la_ui=True)
        verbo = "creada"
    if estado not in (200, 201):
        raise SystemExit(f"No se pudo guardar la regla '{chk['alerta']}' ({estado}): {resp}")
    return f"regla '{chk['alerta']}': {verbo} (dispara tras {chk['falla_minutos']} min con todas las ubicaciones fallando)"


def borrar_checks_de_prueba(g, base_sm: str, prefijo: str) -> list:
    """Solo para las verificaciones manuales: borra checks cuyo job empiece con `prefijo`."""
    estado, checks = g.pedir("GET", f"{base_sm}/sm/check/list")
    hechos = []
    for c in checks if estado == 200 else []:
        if c["job"].startswith(prefijo):
            g.pedir("DELETE", f"{base_sm}/sm/check/delete/{c['id']}")
            hechos.append(c["job"])
    return hechos


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="sin red: muestra qué haría")
    ap.add_argument("--config", default=str(ag.CONFIG))
    ap.add_argument("--solo-checks", action="store_true", help="crea los checks pero no las reglas de alerta")
    ap.add_argument("--solo-reglas", action="store_true", help="crea las reglas pero no los checks")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cfg = ag.cargar_config(Path(args.config))
    errores = ag.validar(cfg) + validar_uptime(cfg)
    if errores:
        print("config.json tiene errores, no se toca Grafana:")
        for e in errores:
            print("  -", e)
        return 2
    u = cfg["uptime"]
    print(f"Ejecuciones por mes: {ejecuciones_por_mes(cfg):,} de un tope asumido de {u['tope_ejecuciones_mes']:,}".replace(",", "."))
    token = os.environ.get("GRAFANA_TOKEN", "")
    if args.dry_run and not token:
        for chk in u["checks"]:
            print(" · check:", json.dumps(payload_check(cfg, chk, ["<ids>"]), ensure_ascii=False))
            print(" · regla:", chk["alerta"], "| for", f"{chk['falla_minutos']}m")
        return 0
    if not token:
        print("Falta GRAFANA_TOKEN (una cuenta de servicio de Grafana, glsa_...).")
        return 2
    g = ag.Grafana(os.environ.get("GRAFANA_URL", cfg["grafana"]["url"]), token)
    print(f"Grafana: {g.url}" + ("   [dry-run]" if args.dry_run else ""))
    base_sm = f"/api/datasources/proxy/uid/{uid_de_synthetic(g)}"
    ids = ids_de_ubicaciones(g, base_sm, u["probes"])
    for chk in u["checks"]:
        if not args.solo_reglas:
            print(" ·", asegurar_check(g, base_sm, cfg, chk, ids, args.dry_run))
        if not args.solo_checks:
            print(" ·", asegurar_regla(g, cfg, chk, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
