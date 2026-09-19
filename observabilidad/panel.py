"""Lo que la pestaña "Observabilidad" de /entornos le pide a Grafana.

La app es la PUERTA, no el motor (docs/chat/2026-09-19-plan-observabilidad.md,
regla 0): las mediciones, las alertas y los mails viven en Grafana Cloud. Si la
app se cae, los avisos siguen saliendo. Este módulo solo lee el estado para
mostrarlo y guarda los dos ajustes que se pueden cambiar desde la pantalla (a
qué mail se avisa y cada cuánto se repite el recordatorio).

Variables de entorno (Render, solo en Pruebas por ahora):
- GRAFANA_URL             https://<stack>.grafana.net
- GRAFANA_TOKEN_LECTURA   cuenta de servicio con rol Viewer: puede leer, no escribir.
- GRAFANA_TOKEN_CONFIG    cuenta de servicio con rol Editor: puede cambiar el mail
                          y el intervalo. Es el único token con permiso de
                          escritura que vive en la app, y no es Admin.
- SENTRY_URL              (opcional) enlace al proyecto de Sentry, cuando exista.

Sin ellas la pestaña dice qué falta en vez de fallar. Un Grafana que no responde
tampoco rompe la pantalla: cada parte informa su propio error.
"""
import os
import threading
import time

from . import aplicar_grafana as ag

TIMEOUT_SEGUNDOS = 10
# Los únicos intervalos que se pueden elegir desde la pantalla. Una lista y no un
# campo libre: escribir "1m" por error mandaría un mail por minuto.
INTERVALOS = ("1h", "6h", "12h", "24h", "48h")
ESPERA_ENTRE_PRUEBAS = 60        # segundos: un mail de prueba por minuto, no más

_ultima_prueba = -ESPERA_ENTRE_PRUEBAS      # la primera prueba no espera
_candado = threading.Lock()


class ErrorObservabilidad(Exception):
    """Algo que la persona tiene que leer (falta una variable, Grafana no
    contestó...). El mensaje ya viene en castellano y sin datos sensibles."""


def _url() -> str:
    return os.getenv("GRAFANA_URL", "").strip().rstrip("/")


def _cliente(variable_token: str) -> "ag.Grafana":
    url, token = _url(), os.getenv(variable_token, "").strip()
    if not url or not token:
        raise ErrorObservabilidad(f"Falta {'GRAFANA_URL' if not url else variable_token} en este servicio.")
    return ag.Grafana(url, token, timeout=TIMEOUT_SEGUNDOS)


def configurado() -> bool:
    return bool(_url() and os.getenv("GRAFANA_TOKEN_LECTURA", "").strip())


def estado() -> dict:
    """Todo lo que la pestaña necesita, en una sola llamada. Cada parte que no
    se pudo leer queda en None con su motivo en `errores`: la pantalla muestra
    lo que hay y dice lo que falta, no se cae entera."""
    cfg_repo = ag.cargar_config()
    url = _url()
    out = {
        "configurado": configurado(),
        "grafana_url": url,
        "tablero_url": f"{url}/dashboards/f/{cfg_repo['grafana']['carpeta_uid']}" if url else "",
        "sentry_url": os.getenv("SENTRY_URL", "").strip(),
        "puede_configurar": bool(os.getenv("GRAFANA_TOKEN_CONFIG", "").strip()),
        "intervalos": list(INTERVALOS),
        "alertas": None, "config": None, "errores": [],
    }
    if not out["configurado"]:
        out["errores"].append("Falta GRAFANA_URL o GRAFANA_TOKEN_LECTURA en este servicio.")
        return out
    g = _cliente("GRAFANA_TOKEN_LECTURA")
    for clave, leer in (("alertas", ag.estado_alertas), ("config", ag.leer_configuracion)):
        try:
            out[clave] = leer(g)
        except Exception as e:                  # Grafana caído, token vencido, red...
            out["errores"].append(f"{'Estado de las alertas' if clave == 'alertas' else 'Configuración de avisos'}: "
                                  f"{e if isinstance(e, RuntimeError) else 'Grafana no respondió (' + type(e).__name__ + ')'}")
    return out


def guardar(email: str, repeat_interval: str, avisar_al_resolverse: bool) -> dict:
    """Cambia el mail y el intervalo de repetición. Lo demás de la política
    (agrupado, esperas) se conserva tal como está HOY en Grafana. Se valida antes
    de escribir: un mail mal escrito no puede dejar la política apuntando a la nada."""
    email = (email or "").strip()
    if repeat_interval not in INTERVALOS:
        raise ValueError(f"El intervalo tiene que ser uno de: {', '.join(INTERVALOS)}.")
    lectura = _cliente("GRAFANA_TOKEN_LECTURA")
    actual = ag.leer_configuracion(lectura)
    cfg = ag.cargar_config()
    cfg["grafana"]["url"] = _url()
    cfg["alertas"].update({
        "contact_point": actual["contact_point"] or cfg["alertas"]["contact_point"],
        "email": email, "repeat_interval": repeat_interval,
        "avisar_al_resolverse": bool(avisar_al_resolverse),
        "group_by": actual["group_by"] or cfg["alertas"]["group_by"],
        "group_wait": actual["group_wait"] or cfg["alertas"]["group_wait"],
        "group_interval": actual["group_interval"] or cfg["alertas"]["group_interval"],
    })
    problemas = ag.validar(cfg)
    if problemas:
        raise ValueError("; ".join(problemas))
    hechos = ag.aplicar_config(_cliente("GRAFANA_TOKEN_CONFIG"), cfg)
    print(f"[observabilidad] configuración cambiada desde /entornos: {email}, repite cada {repeat_interval}")
    return {"hechos": hechos, "config": ag.leer_configuracion(lectura)}


def probar_mail() -> str:
    """Un mail de prueba al punto de contacto vigente, para comprobar que llega."""
    global _ultima_prueba
    with _candado:
        falta = ESPERA_ENTRE_PRUEBAS - (time.monotonic() - _ultima_prueba)
        if falta > 0:
            raise ValueError(f"Ya se mandó una prueba hace poco: esperá {int(falta) + 1} s.")
        _ultima_prueba = time.monotonic()
    lectura = _cliente("GRAFANA_TOKEN_LECTURA")
    actual = ag.leer_configuracion(lectura)
    cfg = ag.cargar_config()
    cfg["alertas"]["contact_point"] = actual["contact_point"]
    cfg["alertas"]["email"] = actual["email"]
    texto = ag.probar_mail(_cliente("GRAFANA_TOKEN_CONFIG"), cfg)
    if "HTTP 200" not in texto:
        raise ErrorObservabilidad(texto)
    return texto
