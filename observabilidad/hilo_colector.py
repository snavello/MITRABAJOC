"""Segunda vía del colector de métricas: un hilo dentro de la app de Pruebas.

La primera vía es GitHub Actions (.github/workflows/metricas-render.yml). Es la
que sobrevive a que la app se caiga, pero GitHub retrasa las corridas programadas:
la primera de un workflow nuevo tardó más de 20 minutos y el tablero se quedó en
"No data" (2026-09-19, 21:38). Un colector que a veces no corre es justo el problema
que se quiere resolver, así que hay DOS vías que hacen lo mismo y se cubren entre sí:

    vía                    corre si...                         no corre si...
    GitHub Actions         la app está caída                   GitHub se atrasa
    este hilo (en la app)  GitHub se atrasa                    la app está caída

Escriben las mismas series con las mismas marcas de tiempo, así que Prometheus
descarta los repetidos y no hay nada que coordinar. Cuando una falla, la otra
rellena el hueco en su siguiente corrida (cada una re-manda la última hora).

Esto NO cambia la regla 0 (docs/chat/2026-09-19-plan-observabilidad.md): el
observador sigue estando afuera. Este hilo es un respaldo, nunca el motor: si la app
es lo que falla, la vía de GitHub sigue juntando la historia.

No necesita claves nuevas: la app de Pruebas ya guarda RENDER_API_KEY (la usa la
pestaña "Planes"). Solo suma GRAFANA_METRICS_TOKEN, que puede escribir métricas y
nada más. Sin esas variables, o con COLECTOR_METRICAS=off, no arranca.
"""
import os
import threading
import time
import traceback
from datetime import datetime, timezone

from . import aplicar_grafana as ag
from . import colector_render as cr

INTERVALO_SEGUNDOS = 300
ESPERA_INICIAL = 90          # que el arranque de la app termine antes de la primera corrida
PISO_ESPERA = 30             # nunca menos de esto entre corridas, por más que una se demore
REINICIO_ESPERA = 60         # si el bucle muere por algo imprevisto, cuánto espera antes de revivir

_hilo = None
_candado = threading.Lock()
estado = {"corridas": 0, "ultima_utc": None, "ultimo_resultado": "todavía no corrió"}


def debe_correr(entorno_actual: str, cfg: dict, entorno_env: dict = None) -> tuple:
    """(si_arranca, motivo). Un solo lugar para las condiciones, así el test las cubre."""
    env = os.environ if entorno_env is None else entorno_env
    if env.get("COLECTOR_METRICAS", "").strip().lower() == "off":
        return False, "apagado con COLECTOR_METRICAS=off"
    if entorno_actual != cfg["metricas_render"]["entorno"]:
        return False, f"este es el entorno '{entorno_actual}', el colector es de '{cfg['metricas_render']['entorno']}'"
    faltan = [v for v in ("RENDER_API_KEY", "GRAFANA_METRICS_TOKEN") if not env.get(v, "").strip()]
    if faltan:
        return False, "falta " + ", ".join(faltan)
    return True, "ok"


def una_corrida(cfg: dict, clave: str, token: str) -> str:
    """Una pasada completa. Nunca lanza: devuelve un texto corto para el log."""
    try:
        r = cr.ejecutar(cfg, clave, token, ahora=datetime.now(timezone.utc), via="app")
        return (f"{r['series']} series, {r['puntos']} puntos, {len(r['errores'])} error(es) de Render, "
                f"Grafana HTTP {r['estado_http']}" + ("" if r["ok"] else " -> FALLÓ"))
    except Exception as e:                          # nada de acá puede tumbar la app
        return f"error inesperado: {type(e).__name__}: {e}"


def _bucle(cfg: dict, intervalo: int, espera_inicial: int):
    time.sleep(espera_inicial)
    while True:
        inicio = time.monotonic()
        texto = una_corrida(cfg, os.environ["RENDER_API_KEY"].strip(), os.environ["GRAFANA_METRICS_TOKEN"].strip())
        estado.update(corridas=estado["corridas"] + 1, ultimo_resultado=texto,
                      ultima_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        print(f"[colector-metricas] {texto}")
        time.sleep(max(PISO_ESPERA, intervalo - (time.monotonic() - inicio)))


def arrancar(entorno_actual: str, intervalo: int = INTERVALO_SEGUNDOS,
             espera_inicial: int = ESPERA_INICIAL) -> bool:
    """Lanza el hilo una sola vez. Devuelve True si arrancó."""
    global _hilo
    cfg = ag.cargar_config()
    ok, motivo = debe_correr(entorno_actual, cfg)
    if not ok:
        print(f"[colector-metricas] no arranca: {motivo}")
        return False
    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return False
        _hilo = threading.Thread(target=_bucle_seguro, args=(cfg, intervalo, espera_inicial),
                                 name="colector-metricas", daemon=True)
        _hilo.start()
    return True


def _bucle_seguro(cfg, intervalo, espera_inicial):
    """Si el bucle muriera por algo imprevisto, se reinicia solo: un colector que se
    queda callado por un error raro es el problema que este hilo existe para evitar."""
    while True:
        try:
            _bucle(cfg, intervalo, espera_inicial)
        except Exception:
            traceback.print_exc()
            time.sleep(REINICIO_ESPERA)
            espera_inicial = 0
