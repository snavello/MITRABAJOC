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
    if not destino:
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


def pista(mail: str) -> str:
    """'juan.perez@gmail.com' -> 'j***@gmail.com'. Lo justo para que la persona
    reconozca su mail sin que la pantalla se lo regale a un tercero."""
    mail = (mail or "").strip()
    if not mail:
        return ""
    local, arroba, dominio = mail.partition("@")
    if not arroba or not local:
        return ""
    return f"{local[0]}***@{dominio}"


def texto_codigo_registro(codigo: str, minutos: int) -> tuple[str, str]:
    """(asunto, cuerpo) del mail con el código para crear la cuenta."""
    asunto = f"Tu código de Colm3na: {codigo}"
    cuerpo = (
        f"Tu código para crear tu cuenta en Colm3na es:\n\n"
        f"    {codigo}\n\n"
        f"Ingresalo en la pantalla de registro. Vence en {minutos} minutos.\n\n"
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
        f"Ingresalo en la pantalla de recuperación. Vence en {minutos} minutos.\n\n"
        f"Si no lo pediste vos, ignorá este mensaje: tu clave actual sigue "
        f"siendo la misma.\n\n"
        f"Colm3na"
    )
    return asunto, cuerpo
