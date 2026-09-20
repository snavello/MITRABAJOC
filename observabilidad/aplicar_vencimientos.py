"""Alertas de vencimiento de tokens: un mail ANTES de que venza, no después.

Cada token de config.json > `renovaciones` tiene su fecha de vencimiento. Este script crea,
por cada uno, una regla de alerta en Grafana que compara esa fecha contra el reloj de
Prometheus (`time()`) y dispara cuando faltan `aviso_dias` o menos. La política de
notificaciones ya configurada hace el resto: UN mail al abrirse y el recordatorio cada 24 h
mientras no se renueve, así que no hay que acordarse de nada.

Por qué una alerta y no un recordatorio en un calendario o en este chat: tiene que llegar
aunque nadie se acuerde, y tiene que seguir llegando mientras el token no se renueve. Si
igual se pasa la fecha, el disparador del colector (aplicar_disparador.py) tiene su propia
alerta cuando el token de GitHub deja de andar.

Al renovar un token: actualizar `vence` en config.json y volver a correr este script (la
regla se actualiza, no se duplica).

    GRAFANA_TOKEN=glsa_... python observabilidad/aplicar_vencimientos.py
    python observabilidad/aplicar_vencimientos.py --dry-run      # sin red

Solo usa la biblioteca estándar. El token de Grafana no va en ningún archivo.
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import aplicar_grafana as ag
    import reglas
else:
    from . import aplicar_grafana as ag
    from . import reglas

BUENOS_AIRES = timezone(timedelta(hours=-3))


def validar_renovaciones(cfg: dict) -> list:
    lista = cfg.get("renovaciones")
    if not isinstance(lista, list) or not lista:
        return ["renovaciones tiene que ser una lista no vacía"]
    errores, vistos = [], set()
    for r in lista:
        n = r.get("id", "?")
        for clave in ("id", "nombre", "vence", "como"):
            if not r.get(clave):
                errores.append(f"renovación {n}: falta '{clave}'")
        try:
            date.fromisoformat(str(r.get("vence", "")))
        except ValueError:
            errores.append(f"renovación {n}: 'vence' tiene que ser AAAA-MM-DD")
        if not isinstance(r.get("aviso_dias"), int) or not 1 <= r["aviso_dias"] <= 90:
            errores.append(f"renovación {n}: aviso_dias entre 1 y 90")
        if r.get("id") in vistos:
            errores.append(f"renovación {n}: id repetido")
        vistos.add(r.get("id"))
    return errores


def epoch_de_vencimiento(vence: str) -> int:
    """El token sirve durante TODO el día de su fecha: vence al terminar ese día, hora de Buenos Aires."""
    fin = datetime.fromisoformat(vence).replace(tzinfo=BUENOS_AIRES) + timedelta(days=1)
    return int(fin.timestamp())


def payload_regla(cfg: dict, r: dict) -> dict:
    entorno = cfg["uptime"]["entorno"]
    return reglas.regla_umbral(
        uid=f"colm3na-{entorno}-vence-{r['id']}",
        titulo=f"Renovar: {r['nombre']} (vence {r['vence']})", grupo="vencimientos",
        carpeta_uid=cfg["grafana"]["carpeta_uid"],
        expr=f"({epoch_de_vencimiento(r['vence'])} - time()) / 86400",
        operador="lt", umbral=r["aviso_dias"], para_minutos=0,
        labels={"entorno": entorno, "evento": f"vencimiento-{r['id']}"},
        resumen=f"Renovar: {r['nombre']}",
        descripcion=f"Vence el {r['vence']}. Cómo renovarlo: {r['como']} Después actualizar `vence` en "
                    f"observabilidad/config.json y volver a correr observabilidad/aplicar_vencimientos.py.",
        sin_datos="OK")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(ag.CONFIG))
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = ag.cargar_config(Path(args.config))
    errores = ag.validar(cfg) + validar_renovaciones(cfg)
    if errores:
        print("config.json tiene errores, no se toca Grafana:")
        for e in errores:
            print("  -", e)
        return 2
    if args.dry_run:
        for r in cfg["renovaciones"]:
            print(f" · {r['nombre']}: vence {r['vence']}, avisa {r['aviso_dias']} días antes")
        return 0
    token = os.environ.get("GRAFANA_TOKEN", "")
    if not token:
        print("Falta GRAFANA_TOKEN (una cuenta de servicio de Grafana, glsa_...).")
        return 2
    g = ag.Grafana(os.environ.get("GRAFANA_URL", cfg["grafana"]["url"]), token)
    for r in cfg["renovaciones"]:
        print(f" · regla 'Renovar: {r['nombre']}': {reglas.guardar_regla(g, payload_regla(cfg, r))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
