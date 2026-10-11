"""Captcha de los registros: Cloudflare Turnstile (PLAN_REGISTRO.md, D7).

Reglas:
- **Sin librerías**: `urllib` y un POST a `siteverify`. Las claves
  (`TURNSTILE_SITE_KEY` pública para el widget, `TURNSTILE_SECRET` privada para
  verificar) vienen del entorno y se leen en cada llamada. Sin las dos, el
  canal está apagado y `verificar()` devuelve True: no se exige lo que no está
  configurado (las demos y los tests siguen andando).
- **Prendido, falla CERRADO**: sin token, con respuesta `success: false`, con
  un error de red o con una respuesta rara, devuelve False. Se prefiere un
  minuto sin registros a una puerta sin captcha que nadie ve.
- **Puro**: no importa `db`. Nunca lanza.
"""
import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

URL_VERIFICACION = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SEGUNDOS = 5


def site_key() -> str:
    return os.getenv("TURNSTILE_SITE_KEY", "").strip()


def _secret() -> str:
    return os.getenv("TURNSTILE_SECRET", "").strip()


def habilitado() -> bool:
    return bool(site_key() and _secret())


def verificar(token: str, ip: str) -> bool:
    """¿Comprobó Turnstile que quien manda el formulario es una persona?"""
    if not habilitado():
        return True
    token = (token or "").strip()
    if not token:
        log.info("captcha: pedido sin token")
        return False
    try:
        campos = {"secret": _secret(), "response": token}
        if ip and ip != "?":
            campos["remoteip"] = ip
        pedido = urllib.request.Request(
            URL_VERIFICACION, data=urllib.parse.urlencode(campos).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": "colm3na-captcha/1.0"})
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEGUNDOS) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
    except Exception as e:           # red, timeout, JSON roto: falla cerrado
        log.warning("captcha: no se pudo verificar (%s)", type(e).__name__)
        return False
    if not isinstance(datos, dict):
        log.warning("captcha: respuesta inesperada")
        return False
    if datos.get("success") is True:
        return True
    log.info("captcha: rechazado %s", datos.get("error-codes"))
    return False
