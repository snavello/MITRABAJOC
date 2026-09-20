"""Cómo se arma una regla de alerta de Grafana que compara una consulta de
Prometheus contra un umbral. Lo comparten las alertas del monitor de uptime
(aplicar_uptime.py) y las de métricas (aplicar_alertas_metricas.py), para que las
dos digan lo mismo del "sin datos", del error de evaluación y de las etiquetas.

Una regla de Grafana son tres pasos encadenados: A (la consulta), B (reducirla a un
número por serie) y C (compararlo con el umbral). Si la consulta devuelve varias
series (por ejemplo una por servicio), Grafana abre una alerta por serie.
"""

OPERADORES = ("gt", "lt")
SIN_DATOS_VALIDOS = ("OK", "NoData", "Alerting")


def regla_umbral(*, uid: str, titulo: str, grupo: str, carpeta_uid: str, expr: str,
                 operador: str, umbral: float, para_minutos: int, labels: dict,
                 resumen: str, descripcion: str, sin_datos: str,
                 desde_segundos: int = 900) -> dict:
    """`sin_datos` decide qué pasa cuando la consulta no devuelve nada:
    - "NoData": la regla avisa igual. Para lo que vigila el monitor mismo (si el
      monitor de uptime deja de reportar, quedarse ciego sin enterarse es peor que un
      falso aviso).
    - "OK": no avisa. Para lo que depende de un colector: si el colector se muere, lo
      dice SU propia regla, y no hace falta que cada regla de métricas grite lo mismo.
    - "Alerting": ausencia = problema (la regla del colector mismo).
    """
    if operador not in OPERADORES:
        raise ValueError(f"operador inválido: {operador}")
    if sin_datos not in SIN_DATOS_VALIDOS:
        raise ValueError(f"sin_datos inválido: {sin_datos}")
    expr_ds = {"type": "__expr__", "uid": "__expr__"}
    return {
        "uid": uid, "title": titulo, "ruleGroup": grupo, "folderUID": carpeta_uid, "orgID": 1,
        "condition": "C", "for": f"{para_minutos}m",
        "noDataState": sin_datos, "execErrState": "Error", "isPaused": False,
        "labels": labels,
        "annotations": {"summary": resumen, "description": descripcion},
        "data": [
            {"refId": "A", "relativeTimeRange": {"from": desde_segundos, "to": 0},
             "datasourceUid": "grafanacloud-prom",
             "model": {"editorMode": "code", "expr": expr, "instant": True,
                       "intervalMs": 1000, "maxDataPoints": 43200, "refId": "A"}},
            {"refId": "B", "relativeTimeRange": {"from": 0, "to": 0}, "datasourceUid": "__expr__",
             "model": {"type": "reduce", "expression": "A", "reducer": "last", "refId": "B",
                       "settings": {"mode": "dropNN"}, "datasource": expr_ds}},
            {"refId": "C", "relativeTimeRange": {"from": 0, "to": 0}, "datasourceUid": "__expr__",
             "model": {"type": "threshold", "expression": "B", "refId": "C",
                       "conditions": [{"evaluator": {"params": [umbral], "type": operador}}],
                       "datasource": expr_ds}},
        ],
    }


def guardar_regla(g, regla: dict) -> str:
    """Crea o actualiza (por uid) una regla. Devuelve 'creada' o 'actualizada'."""
    estado, _ = g.pedir("GET", f"/api/v1/provisioning/alert-rules/{regla['uid']}")
    if estado == 200:
        estado, resp = g.pedir("PUT", f"/api/v1/provisioning/alert-rules/{regla['uid']}", regla,
                               editable_desde_la_ui=True)
        verbo = "actualizada"
    else:
        estado, resp = g.pedir("POST", "/api/v1/provisioning/alert-rules", regla, editable_desde_la_ui=True)
        verbo = "creada"
    if estado not in (200, 201):
        raise SystemExit(f"No se pudo guardar la regla '{regla['title']}' ({estado}): {resp}")
    return verbo
