"""Canal de mail de la plataforma: los códigos de registro y de recuperación
de clave (PLAN_REGISTRO.md, D8).

Reglas:
- **Sin librerías**: `urllib` y un POST a la API de Resend, el mismo patrón de
  `telegram.py`. Las claves (`RESEND_API_KEY`, `MAIL_REMITENTE`) vienen del
  entorno y se leen en CADA llamada, así un test puede simularlas. Sin las dos,
  `habilitado()` es False y `enviar()` no hace nada, en silencio: igual que
  Telegram y Web Push. El registro sabe qué hacer con el canal apagado (D9).
- **Nunca lanza**: `enviar()` atrapa todo, lo deja en el log y devuelve False.
  Quien llama decide qué le dice a la persona.
- **Puro**: no importa `db`. Los textos de los mails viven acá y NO llevan el
  nombre de la persona (el mail del padrón puede estar desactualizado y
  llegarle a otro) ni enlaces (reputación de entrega, y un enlace en un mail de
  códigos es lo primero que imita un phishing).
- El remitente es `MAIL_REMITENTE` tal cual, por ejemplo
  `Colm3na <no-responder@avisos.colm3na.com.ar>`.
"""
import json
import re
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

API = "https://api.resend.com/emails"
TIMEOUT_SEGUNDOS = 10


def _clave() -> str:
    return os.getenv("RESEND_API_KEY", "").strip()


def _remitente() -> str:
    return os.getenv("MAIL_REMITENTE", "").strip()


def habilitado() -> bool:
    """¿Están las dos variables? Sin ellas el canal está apagado."""
    return bool(_clave() and _remitente())


def enviar(destino: str, asunto: str, texto: str) -> bool:
    """Manda un mail de texto plano. True si Resend contestó 2xx; False en
    cualquier otro caso (canal apagado, error de red, 4xx/5xx). No lanza."""
    if not habilitado():
        return False
    destino = (destino or "").strip()
    if not destino_valido(destino):
        # Un destino con coma, punto y coma, "<", saltos de línea o dos arrobas
        # no sale nunca: el mail declarado lo escribe la persona (o un
        # atacante), y un código de registro no puede llegar a un tercero.
        log.info("correo: destino inválido, no se envía")
        return False
    try:
        cuerpo = json.dumps({"from": _remitente(), "to": [destino],
                             "subject": asunto, "text": texto}).encode("utf-8")
        pedido = urllib.request.Request(
            API, data=cuerpo, method="POST",
            headers={"Authorization": f"Bearer {_clave()}",
                     "Content-Type": "application/json",
                     # Cloudflare, que está delante de Resend, rechaza el
                     # User-Agent por defecto de urllib.
                     "User-Agent": "colm3na-correo/1.0"})
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEGUNDOS) as resp:
            estado = getattr(resp, "status", None) or resp.getcode()
            if 200 <= int(estado) < 300:
                return True
            log.warning("correo: Resend contestó %s", estado)
            return False
    except Exception as e:           # red, 4xx/5xx (HTTPError), lo que sea
        # Ni el destino ni el cuerpo van al log: es el mail de una persona.
        log.warning("correo: no se pudo enviar (%s)", type(e).__name__)
        return False


# Un mail "razonable": una sola arroba, sin espacios ni separadores de lista
# ni los caracteres con que se arma una cabecera, y un dominio con punto.
# No pretende validar RFC 5322: pretende que lo que se le pasa a Resend sea
# UNA dirección y no dos, ni una cabecera.
_MAIL_RE = re.compile(r"^[^@\s,;<>\"'()\[\]\\]{1,64}@[^@\s,;<>\"'()\[\]\\]+\.[^@\s,;<>\"'()\[\]\\.]{2,}$")
LARGO_MAX_MAIL = 254


def destino_valido(mail: str) -> bool:
    mail = (mail or "").strip()
    return 0 < len(mail) <= LARGO_MAX_MAIL and bool(_MAIL_RE.match(mail))


def pista(mail: str) -> str:
    """'juan.perez@gmail.com' -> 'j***@gmail.com'. Lo justo para que la persona
    reconozca su mail sin que la pantalla se lo regale a un tercero. Un mail
    que no es válido no tiene pista (""), y una parte local de una sola letra
    se tapa entera: 'j@x.com' -> '***@x.com'."""
    mail = (mail or "").strip()
    if not destino_valido(mail):
        return ""
    local, _, dominio = mail.partition("@")
    if len(local) == 1:
        return f"***@{dominio}"
    return f"{local[0]}***@{dominio}"


def _minutos(n: int) -> str:
    return "1 minuto" if int(n) == 1 else f"{n} minutos"


def texto_codigo_registro(codigo: str, minutos: int) -> tuple[str, str]:
    """(asunto, cuerpo) del mail con el código para crear la cuenta."""
    asunto = f"Tu código de Colm3na: {codigo}"
    cuerpo = (
        f"Tu código para crear tu cuenta en Colm3na es:\n\n"
        f"    {codigo}\n\n"
        f"Ingresalo en la pantalla de registro. Vence en {_minutos(minutos)}.\n\n"
        f"Si no lo pediste vos, ignorá este mensaje: no se crea ninguna cuenta "
        f"y nadie accede a tus datos.\n\n"
        f"Colm3na"
    )
    return asunto, cuerpo


def texto_codigo_recuperacion(codigo: str, minutos: int) -> tuple[str, str]:
    """(asunto, cuerpo) del mail con el código para elegir una clave nueva."""
    asunto = f"Tu código para recuperar la clave de Colm3na: {codigo}"
    cuerpo = (
        f"Tu código para elegir una clave nueva en Colm3na es:\n\n"
        f"    {codigo}\n\n"
        f"Ingresalo en la pantalla de recuperación. Vence en {_minutos(minutos)}.\n\n"
        f"Si no lo pediste vos, ignorá este mensaje: tu clave actual sigue "
        f"siendo la misma.\n\n"
        f"Colm3na"
    )
    return asunto, cuerpo
