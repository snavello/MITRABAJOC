"""Lo que la pestaña "Observabilidad" de /entornos muestra de Sentry: si la conexión está viva,
cuántos errores hubo, cuáles son y de dónde vienen.

Sentry guarda los errores no previstos de la app (sentry_config.py). Acá se LEEN, con un token
personal de solo lectura (variable SENTRY_AUTH_TOKEN, con permisos Read en Project, Issue &
Event y Organization: no puede borrar ni cambiar nada). Sin el token la pestaña dice qué falta y
el resto sigue funcionando.

Solo se cuentan los errores del ENTORNO de la app (`environment:pruebas`): los eventos de prueba
de conexión llevan otro entorno (`prueba-de-conexion`) y no ensucian el reporte; se muestran aparte
para comprobar que el camino funciona de punta a punta.

Las respuestas se guardan 45 segundos: abrir la pestaña varias veces seguidas no multiplica las
consultas a Sentry.
"""
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import sentry_sdk

import entorno
import errores
import sentry_config

from . import aplicar_grafana as ag

API = "https://sentry.io/api/0"
TIMEOUT_SEGUNDOS = 10
VIGENCIA_CACHE = 45
ESPERA_ENTRE_PRUEBAS = 60
ENTORNO_DE_PRUEBA = "prueba-de-conexion"
CAMPOS_EVENTO = ["timestamp", "title", "issue", "codigo", "ref", "rol", "sindicato_id", "ruta"]

_cache = {"hasta": 0.0, "datos": None}
_ultima_prueba = -ESPERA_ENTRE_PRUEBAS
_candado = threading.Lock()


class ErrorSentry(Exception):
    """Algo que la persona tiene que leer. El mensaje va en castellano y sin datos sensibles."""


def _cfg() -> dict:
    return ag.cargar_config()["sentry"]


def _token() -> str:
    return os.getenv("SENTRY_AUTH_TOKEN", "").strip()


def _url_todos() -> str:
    """Todos los errores del entorno, sin resolver, de las últimas dos semanas (no el evento de
    prueba de una línea al que llevaba el enlace anterior)."""
    c = _cfg()
    q = urllib.parse.urlencode({"project": c["proyecto_id"], "environment": entorno.ENTORNO,
                                "query": "is:unresolved", "statsPeriod": "14d"})
    return f"https://{c['org']}.sentry.io/issues/?{q}"


def _pedir(ruta: str, params: list) -> dict:
    """GET a la API de Sentry. `params`: lista de (clave, valor) porque `field` se repite."""
    token = _token()
    if not token:
        raise ErrorSentry("Falta SENTRY_AUTH_TOKEN en este servicio.")
    url = f"{API}{ruta}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS, context=ag._contexto_tls()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ErrorSentry("Sentry rechazó el token de lectura (vencido, revocado o sin permisos).")
        raise ErrorSentry(f"Sentry respondió HTTP {e.code}.")
    except Exception as e:
        raise ErrorSentry(f"No se pudo consultar a Sentry ({type(e).__name__}).")


def _discover(campos: list, consulta: str, periodo: str, orden: str = "", limite: int = 10) -> list:
    c = _cfg()
    params = [("dataset", "errors"), ("project", c["proyecto_id"]), ("statsPeriod", periodo),
              ("per_page", str(limite)), ("query", consulta)]
    if orden:
        params.append(("sort", orden))
    params += [("field", f) for f in campos]
    return _pedir(f"/organizations/{c['org']}/events/", params).get("data", [])


def _cantidad(consulta: str, periodo: str, campo: str = "count()") -> int:
    filas = _discover([campo], consulta, periodo, limite=1)
    return int(filas[0][campo]) if filas else 0


def descripcion_del_codigo(codigo: str) -> str:
    """Qué significa un código `E-...`, en una frase, desde el catálogo de errores.py."""
    if codigo in errores.MENSAJES:
        return errores.MENSAJES[codigo][1].split(". ")[0].rstrip(".")
    return ""


def gravedad(codigo: str) -> str:
    """`inesperado` = no sabíamos que podía pasar (E-INTERNO-00 o sin código): es lo que hay que
    mirar primero. `conocido` = un error con código propio que la app ya sabe nombrar."""
    return "inesperado" if codigo in ("", "E-INTERNO-00") else "conocido"


def _evento(fila: dict) -> dict:
    codigo = fila.get("codigo") or ""
    c = _cfg()
    incidencia = fila.get("issue") or ""
    return {
        "cuando": fila.get("timestamp"), "titulo": (fila.get("title") or "")[:160],
        "codigo": codigo, "descripcion": descripcion_del_codigo(codigo), "gravedad": gravedad(codigo),
        "ruta": fila.get("ruta") or "", "rol": fila.get("rol") or "",
        "sindicato_id": fila.get("sindicato_id") or "", "ref": fila.get("ref") or "",
        "incidencia": incidencia,
        "url": f"https://{c['org']}.sentry.io/issues/{fila.get('issue.id')}/" if fila.get("issue.id") else "",
    }


def _leer() -> dict:
    """Todo el reporte, con cuatro consultas a Sentry."""
    q = f"environment:{entorno.ENTORNO}"
    recientes = [_evento(f) for f in _discover(CAMPOS_EVENTO + ["issue.id"], q, "14d", "-timestamp", 12)]
    por_codigo = [{"codigo": f.get("codigo") or "(sin código)", "cantidad": int(f["count()"]),
                   "descripcion": descripcion_del_codigo(f.get("codigo") or ""),
                   "gravedad": gravedad(f.get("codigo") or "")}
                  for f in _discover(["codigo", "count()"], q, "14d", "-count()", 8)]
    prueba = _discover(["timestamp", "ref"], f"environment:{ENTORNO_DE_PRUEBA}", "14d", "-timestamp", 1)
    return {
        "kpis": {"errores_24h": _cantidad(q, "24h"), "errores_7d": _cantidad(q, "7d"),
                 "tipos_distintos": _cantidad(q, "14d", "count_unique(issue)"),
                 "ultimo": recientes[0]["cuando"] if recientes else None},
        "por_codigo": por_codigo, "recientes": recientes,
        "prueba": {"cuando": prueba[0]["timestamp"], "ref": prueba[0].get("ref") or ""} if prueba else None,
    }


def estado(forzar: bool = False) -> dict:
    """El reporte completo para la pestaña. Nunca lanza: cada falla queda en `errores`."""
    c = _cfg()
    salida = {
        "sdk_activo": sentry_config.activo(), "dsn_configurado": bool(os.getenv("SENTRY_DSN", "").strip()),
        "token_configurado": bool(_token()), "entorno": entorno.ENTORNO, "url_todos": _url_todos(),
        "proyecto": c["proyecto"], "kpis": None, "por_codigo": [], "recientes": [], "prueba": None, "errores": [],
    }
    if not salida["token_configurado"]:
        salida["errores"].append("Falta SENTRY_AUTH_TOKEN: sin él se puede mandar errores a Sentry pero no leerlos acá.")
        return salida
    with _candado:
        if not forzar and _cache["datos"] is not None and time.monotonic() < _cache["hasta"]:
            return dict(salida, **_cache["datos"])
    try:
        datos = _leer()
    except ErrorSentry as e:
        salida["errores"].append(str(e))
        return salida
    with _candado:
        _cache.update(hasta=time.monotonic() + VIGENCIA_CACHE, datos=datos)
    return dict(salida, **datos)


def mandar_prueba() -> dict:
    """Manda UN error de prueba a Sentry y espera a verlo llegar (unos segundos). El evento lleva otro
    entorno, así que no aparece en el reporte de errores reales."""
    global _ultima_prueba
    with _candado:
        falta = ESPERA_ENTRE_PRUEBAS - (time.monotonic() - _ultima_prueba)
        if falta > 0:
            raise ValueError(f"Ya se mandó una prueba hace poco: esperá {int(falta) + 1} s.")
        _ultima_prueba = time.monotonic()
    if not sentry_config.activo():
        raise ErrorSentry("Sentry está apagado en este servicio: falta SENTRY_DSN.")
    ref = "p" + secrets.token_hex(3)
    try:
        raise RuntimeError("Error de PRUEBA mandado desde la pestaña Observabilidad. No es un error real.")
    except RuntimeError as e:
        sentry_config.capturar(e, ruta="/entornos/observabilidad", rol="plataforma", ref=ref,
                               codigo="E-PRUEBA-00", prueba=True)
    sentry_sdk.flush(timeout=5)
    llego = False
    if _token():
        for _ in range(6):                                     # hasta ~12 s: Sentry tarda unos segundos en indexar
            time.sleep(2)
            try:
                if _discover(["ref"], f"environment:{ENTORNO_DE_PRUEBA} ref:{ref}", "24h", limite=1):
                    llego = True
                    break
            except ErrorSentry:
                break
        with _candado:
            _cache["hasta"] = 0.0                              # que el reporte siguiente vea la prueba
    return {"ref": ref, "llego": llego, "verificable": bool(_token())}
