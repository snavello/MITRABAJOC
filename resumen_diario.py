"""El resumen del día por Telegram: un hilo dentro de la app que, a la hora
fija de Buenos Aires que dice `telegram.hora_resumen()` (21:00 por defecto,
pedido de Sd 2026-09-23), manda UN mensaje con los indicadores del entorno.

Corre adentro de la app y no en un Cron Job de Render por lo mismo que el
planificador de planes: un servicio más que se factura. Contrapartida: si el
web está caído a esa hora, el resumen de ese día no sale (y de que esté caído
avisa Grafana por su lado). Seguro con varios workers: antes de mandar, cada
proceso reclama el día con un INSERT que solo puede ganar uno
(`db.reclamar_aviso_diario`, tabla `avisoenviado`), así que aunque dos
instancias despierten en el mismo minuto sale un solo mensaje.

El contenido lo arma `telegram.texto_resumen` con lo que ya calcula
`esquema.kpis` (recibos, lecturas de IA y costo, ingresos por rol, trámites,
afiliados), más los errores de Sentry que la pestaña técnica ya lee, el
semáforo de Grafana y dos líneas sobre cómo le fue al servidor web y a la
base (`observabilidad/metricas_dia.py`: picos de CPU y memoria con su hora,
pedidos, 5xx, latencia, conexiones). Cada parte que no se pueda leer queda como "sin dato":
el resumen sale igual.
"""
import threading
import time
import traceback

import db
import esquema
import fechas
import telegram

CLAVE = "resumen-telegram"
INTERVALO_SEGUNDOS = 60

_hilo = None
_candado = threading.Lock()


def debe_correr(entorno_actual: str) -> tuple[bool, str]:
    if entorno_actual != "pruebas":
        return False, f"solo corre en Pruebas (esto es {entorno_actual or 'sin entorno'})"
    if not telegram.configurado():
        return False, "faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID"
    return True, ""


def toca_ahora(ahora, hora_objetivo: str = None) -> bool:
    """True desde la hora objetivo hasta fin del día; el reclamo por fecha
    garantiza que igual sale una sola vez."""
    return ahora.strftime("%H:%M") >= (hora_objetivo or telegram.hora_resumen())


def armar_texto(ahora=None) -> str:
    ahora = ahora or fechas.ahora()
    with db.get_session() as s:
        kpis = esquema.kpis(s, ahora=ahora)
    errores, semaforo = None, None
    try:
        from observabilidad import sentry_panel
        est = sentry_panel.estado()
        errores = est.get("kpis") or None
    except Exception as e:
        print(f"[resumen-diario] sin errores de Sentry: {type(e).__name__}: {e}")
    try:
        from observabilidad import panel as obs_panel
        if obs_panel.configurado():
            semaforo = obs_panel.ag.estado_alertas(obs_panel._cliente("GRAFANA_TOKEN_LECTURA"))["semaforo"]
    except Exception as e:
        print(f"[resumen-diario] sin semáforo de Grafana: {type(e).__name__}: {e}")
    servidor = []
    try:
        from observabilidad import metricas_dia
        servidor = metricas_dia.lineas_del_dia()
    except Exception as e:
        print(f"[resumen-diario] sin métricas del servidor: {type(e).__name__}: {e}")
    import entorno
    return telegram.texto_resumen(kpis, errores, semaforo, entorno.ENTORNO, ahora.strftime("%d/%m/%Y"),
                                  servidor=servidor)


def enviar_ahora() -> bool:
    """Manda el resumen ya, sin reclamar el día (botón de la pestaña técnica)."""
    return telegram.enviar(armar_texto())


def intentar(ahora=None) -> bool:
    """Un ciclo del hilo: si ya es la hora y nadie mandó el de hoy, lo manda."""
    ahora = ahora or fechas.ahora()
    if not toca_ahora(ahora):
        return False
    if not db.reclamar_aviso_diario(CLAVE, ahora.strftime("%Y-%m-%d")):
        return False
    ok = telegram.enviar(armar_texto(ahora))
    print(f"[resumen-diario] {'enviado' if ok else 'NO se pudo mandar'} el resumen del {ahora.strftime('%Y-%m-%d')}")
    return ok


def _bucle(intervalo: int) -> None:
    while True:
        try:
            intentar()
        except Exception:
            traceback.print_exc()
        time.sleep(intervalo)


def arrancar(entorno_actual: str, intervalo: int = INTERVALO_SEGUNDOS) -> bool:
    """Lanza el hilo una sola vez. Devuelve True si arrancó."""
    global _hilo
    ok, motivo = debe_correr(entorno_actual)
    if not ok:
        print(f"[resumen-diario] no arranca: {motivo}")
        return False
    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return False
        _hilo = threading.Thread(target=_bucle, args=(intervalo,), name="resumen-diario", daemon=True)
        _hilo.start()
    print(f"[resumen-diario] hilo en marcha: resumen a las {telegram.hora_resumen()} de Buenos Aires")
    return True
