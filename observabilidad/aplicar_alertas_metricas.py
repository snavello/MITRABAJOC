"""Alertas sobre las métricas de Render (los eventos 3 y 4 del plan) y sobre el propio
colector, como código.

Las reglas salen de `metricas_render.alertas` de observabilidad/config.json:

  errores-5xx   más del 5 % de los pedidos con error del servidor, en una ventana de
                10 minutos (evento 3). Con un mínimo de pedidos: un 1 de 10 no es un 10 %.
  cpu-al-limite     CPU por encima del 95 % del plan durante más de 30 minutos, en la app
                    o en la base (evento 4).
  memoria-al-limite Ídem con la memoria (evento 4).
  colector-mudo     el colector de métricas no corre hace más de 30 minutos: los tableros y
                    las tres alertas de arriba estarían mirando datos viejos.

Las tres primeras no avisan cuando "no hay datos" (`sin_datos: OK`): si el colector se
muere lo dice la cuarta, y no tiene sentido que las cuatro manden un mail por lo mismo.
La cuarta sí avisa por la falta de datos: que el colector no haya corrido nunca es un
problema.

    GRAFANA_TOKEN=glsa_... python observabilidad/aplicar_alertas_metricas.py
    python observabilidad/aplicar_alertas_metricas.py --dry-run     # sin red

Idempotente (cada regla tiene un uid estable). El token no va en ningún archivo.
"""
import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import aplicar_grafana as ag
    import reglas
else:
    from . import aplicar_grafana as ag
    from . import reglas

MARCA_ENTORNO = "__ENTORNO__"


def validar_alertas(cfg: dict) -> list:
    m = cfg.get("metricas_render", {})
    alertas = m.get("alertas")
    if not isinstance(alertas, list) or not alertas:
        return ["metricas_render.alertas tiene que ser una lista no vacía"]
    errores, vistos = [], set()
    for a in alertas:
        n = a.get("id", "?")
        for clave in ("id", "evento", "titulo", "expr", "descripcion"):
            if not a.get(clave):
                errores.append(f"alerta {n}: falta '{clave}'")
        if a.get("operador") not in reglas.OPERADORES:
            errores.append(f"alerta {n}: operador tiene que ser gt o lt")
        if not isinstance(a.get("umbral"), (int, float)):
            errores.append(f"alerta {n}: umbral tiene que ser un número")
        if not isinstance(a.get("para_min"), int) or a["para_min"] < 0:
            errores.append(f"alerta {n}: para_min tiene que ser un entero >= 0")
        if a.get("sin_datos") not in reglas.SIN_DATOS_VALIDOS:
            errores.append(f"alerta {n}: sin_datos tiene que ser {', '.join(reglas.SIN_DATOS_VALIDOS)}")
        if MARCA_ENTORNO not in str(a.get("expr", "")):
            errores.append(f"alerta {n}: la consulta tiene que filtrar por entorno ({MARCA_ENTORNO})")
        if a.get("id") in vistos or a.get("evento") in vistos:
            errores.append(f"alerta {n}: id o evento repetido")
        vistos.update({a.get("id"), a.get("evento")})
    return errores


def uid_de_regla(cfg: dict, alerta: dict) -> str:
    return f"colm3na-{cfg['metricas_render']['entorno']}-{alerta['evento']}"


def payload_regla(cfg: dict, alerta: dict) -> dict:
    ent = cfg["metricas_render"]["entorno"]
    return reglas.regla_umbral(
        uid=uid_de_regla(cfg, alerta), titulo=alerta["titulo"], grupo="metricas",
        carpeta_uid=cfg["grafana"]["carpeta_uid"],
        expr=alerta["expr"].replace(MARCA_ENTORNO, ent),
        operador=alerta["operador"], umbral=alerta["umbral"], para_minutos=alerta["para_min"],
        labels={"entorno": ent, "evento": alerta["evento"]},
        resumen=alerta["titulo"], descripcion=alerta["descripcion"], sin_datos=alerta["sin_datos"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(ag.CONFIG))
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = ag.cargar_config(Path(args.config))
    errores = ag.validar(cfg) + validar_alertas(cfg)
    if errores:
        print("config.json tiene errores, no se toca Grafana:")
        for e in errores:
            print("  -", e)
        return 2
    alertas = cfg["metricas_render"]["alertas"]
    if args.dry_run:
        for a in alertas:
            print(f" · {a['titulo']}: {payload_regla(cfg, a)['data'][0]['model']['expr']}  "
                  f"({a['operador']} {a['umbral']}, {a['para_min']} min, sin datos: {a['sin_datos']})")
        return 0
    token = os.environ.get("GRAFANA_TOKEN", "")
    if not token:
        print("Falta GRAFANA_TOKEN (una cuenta de servicio de Grafana, glsa_...).")
        return 2
    g = ag.Grafana(os.environ.get("GRAFANA_URL", cfg["grafana"]["url"]), token)
    print(f"Grafana: {g.url}")
    for a in alertas:
        print(f" · regla '{a['titulo']}': {reglas.guardar_regla(g, payload_regla(cfg, a))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
