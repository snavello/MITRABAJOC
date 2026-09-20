"""Sentry: los errores no previstos de la app, con contexto y SIN datos personales.

Qué guarda Sentry de cada error: el traceback, la ruta (el patrón), el código y la referencia
que ya ve la persona en pantalla (`E-INTERNO-00 ref=abc12345`), la versión y a qué sindicato le
pasó (el ID numérico y el rol). Qué NO guarda, nunca: cuerpos de pedidos, cookies, encabezados,
direcciones IP, el valor de las variables locales de cada línea del traceback (ahí viven los
recibos enteros, con sueldos), nombres, mails ni claves.

Un CUIL o CUIT SUELTO sí puede aparecer, por ejemplo en el texto de una excepción o en la URL de
`/perfil-foto/{cuil}`: es un dato público sin contexto y saber de qué CUIL falló algo es justo lo
que sirve para diagnosticar (decisión de SDN, 2026-09-20). Lo que se protege es lo que sí tiene
valor y contexto: el sueldo, el recibo, los nombres, las sesiones. El filtrado es por lista de lo
permitido: el evento se reconstruye con lo mínimo en `limpiar_evento`, en vez de quitar lo malo
de un evento completo (que deja pasar lo que no se previó).

Solo se manda lo que la app captura a propósito (`capturar`, desde el manejador de errores no
previstos). Las respuestas de error deliberadas (403, 422, el 503 de "servidor ocupado", los
códigos `E-...`) no son un problema de la app y no viajan: mandarlas llenaría la cuota
gratuita con ruido.

Sin `SENTRY_DSN` no hace nada. Ver docs/chat/2026-09-19-plan-observabilidad.md.
"""
import os
import re
import threading
import time
from collections import deque

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, DEFAULT_PII_DENYLIST, EventScrubber

PATRON_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
FILTRADO = "[filtrado]"

# Nombres de campo que nunca viajan, además de los que el SDK ya filtra (cookie, authorization...).
CAMPOS_PERSONALES = [
    "cuil", "cuit", "dni", "nombre", "apellido", "apellido_nombre", "razon_social", "email", "mail",
    "telefono", "domicilio", "direccion", "clave", "password", "pin", "token", "secret", "legajo",
    "sueldo", "bruto", "neto", "remuneracion", "cbu", "empleado", "empleador",
]

# Tope de eventos por minuto: si algo se rompe en cada pedido (la base caída, por ejemplo) no se
# manda una tormenta que se coma la cuota del mes en minutos. Sentry además agrupa por
# causa, así que lo que se pierde acá es repetición.
MAX_EVENTOS_POR_MINUTO = 20
_recientes = deque()
_candado = threading.Lock()


# ---------- limpieza (pura: se prueba sin red) ----------

def limpiar_texto(texto):
    if not isinstance(texto, str):
        return texto
    return PATRON_EMAIL.sub(FILTRADO, texto)


def _sin_query(url: str) -> str:
    return limpiar_texto(str(url or "").split("?", 1)[0].split("#", 1)[0])


def limpiar_valor(valor, profundidad: int = 0):
    """Recorre lo que sea y limpia los textos. Nada se conserva por no saber qué es."""
    if profundidad > 8:
        return FILTRADO
    if isinstance(valor, str):
        return limpiar_texto(valor)
    if isinstance(valor, dict):
        return {k: (FILTRADO if str(k).lower() in CAMPOS_PERSONALES else limpiar_valor(v, profundidad + 1))
                for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [limpiar_valor(v, profundidad + 1) for v in valor]
    return valor


def limpiar_evento(evento: dict, pista=None):
    """Reconstruye el evento con lo mínimo. Devuelve None (no se manda) si se pasó el tope."""
    ahora = time.monotonic()
    with _candado:
        while _recientes and ahora - _recientes[0] > 60:
            _recientes.popleft()
        if len(_recientes) >= MAX_EVENTOS_POR_MINUTO:
            return None
        _recientes.append(ahora)

    req = evento.get("request") or {}
    # De la petición queda solo el método y la ruta, sin parámetros, sin cuerpo, sin encabezados,
    # sin cookies y sin variables de entorno.
    evento["request"] = {"method": req.get("method"), "url": _sin_query(req.get("url"))}
    evento.pop("user", None)
    evento.pop("server_name", None)
    evento["transaction"] = limpiar_texto(evento.get("transaction") or "")
    for clave in ("contexts", "extra", "modules"):
        evento.pop(clave, None)

    for exc in (evento.get("exception") or {}).get("values", []) or []:
        exc["value"] = limpiar_texto(exc.get("value") or "")
        for cuadro in (exc.get("stacktrace") or {}).get("frames", []) or []:
            cuadro.pop("vars", None)                    # las variables locales son donde vive el dato de la persona
            cuadro["filename"] = limpiar_texto(cuadro.get("filename") or "")
            for c in ("context_line", "pre_context", "post_context"):
                cuadro[c] = limpiar_valor(cuadro.get(c)) if cuadro.get(c) else cuadro.get(c)
    if evento.get("message"):
        evento["message"] = limpiar_texto(evento["message"])
    evento["logentry"] = limpiar_valor(evento.get("logentry")) if evento.get("logentry") else None
    if evento["logentry"] is None:
        evento.pop("logentry")

    # Las migas de pan (lo que pasó antes) se quedan sin datos: solo categoría y mensaje limpios.
    migas = (evento.get("breadcrumbs") or {}).get("values", []) or []
    evento["breadcrumbs"] = {"values": [
        {"category": m.get("category"), "level": m.get("level"), "message": limpiar_texto(m.get("message") or ""),
         "timestamp": m.get("timestamp")} for m in migas[-10:]]}
    evento["tags"] = {k: limpiar_texto(str(v)) for k, v in (evento.get("tags") or {}).items()}
    return evento


def limpiar_miga(miga: dict, pista=None):
    """Los pedidos HTTP salientes (Render, Grafana, Anthropic) llevan URLs y no aportan al diagnóstico."""
    if miga.get("category") in ("httplib", "http", "subprocess"):
        return None
    return miga


# ---------- puesta en marcha ----------

def iniciar(dsn: str, entorno: str, release: str = "", transport=None) -> bool:
    """Prende Sentry. Devuelve False (y no hace nada) si no hay DSN."""
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn, environment=entorno, release=release or None,
        send_default_pii=False,                 # sin IP, sin cookies, sin usuario
        include_local_variables=False,          # sin el valor de las variables de cada línea
        traces_sample_rate=0.0, profiles_sample_rate=0.0,      # solo errores: rendimiento ya lo mide Grafana
        max_breadcrumbs=10, attach_stacktrace=False, shutdown_timeout=2,
        # Un HTTPException (403, 422, 503 de "ocupado") no es un error de la app: no viaja.
        integrations=[FastApiIntegration(failed_request_status_codes=set()),
                      StarletteIntegration(failed_request_status_codes=set())],
        event_scrubber=EventScrubber(denylist=list(DEFAULT_DENYLIST) + CAMPOS_PERSONALES,
                                     pii_denylist=list(DEFAULT_PII_DENYLIST), recursive=True),
        before_send=limpiar_evento, before_breadcrumb=limpiar_miga,
        transport=transport,
    )
    return True


def capturar(exc: BaseException, *, ruta: str = "", rol: str = "", sindicato_id=None,
             ref: str = "", codigo: str = "") -> None:
    """Manda un error no previsto con sus etiquetas. Nunca lanza: observar no puede romper la app."""
    try:
        if not sentry_sdk.is_initialized():
            return
        # El middleware de sesión envuelve lo que explota en una ruta en un ExceptionGroup de un solo
        # elemento; el error real es el de adentro y es el que hay que ver en Sentry.
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("ruta", limpiar_texto(ruta or "")[:120])
            if rol:
                scope.set_tag("rol", rol)
            if sindicato_id not in (None, "", 0):
                scope.set_tag("sindicato_id", str(int(sindicato_id)))
            if ref:
                scope.set_tag("ref", ref)                   # el que ve la persona en pantalla
            if codigo:
                scope.set_tag("codigo", codigo)
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def iniciar_desde_el_entorno(entorno: str) -> bool:
    return iniciar(os.getenv("SENTRY_DSN", "").strip(), entorno,
                   release=(os.getenv("RENDER_GIT_COMMIT", "") or "")[:7] or "local")
