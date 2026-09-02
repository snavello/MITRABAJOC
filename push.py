"""Notificaciones Web Push a la PWA del trabajador (2026-09-02).

Canal para las novedades de trámites: cuando el sindicato cambia el estado
o escribe en el chat, el teléfono recibe "Novedad en tu trámite XXX...".
Reconecta el gancho que quedó documentado en main._notificar_cambio_tramite
cuando esas novedades dejaron de generar Notificacion.

Configuración por variables de entorno (las tres o nada):
- VAPID_PRIVATE_KEY  clave privada (base64url crudo, generada una vez)
- VAPID_PUBLIC_KEY   clave pública correspondiente (va al navegador)
- VAPID_CLAIM_EMAIL  mail de contacto exigido por el protocolo

Sin configurar, TODO este módulo es un no-op silencioso: la app funciona
igual que antes (mismo criterio que ANTHROPIC_API_KEY ausente en dev).

El envío corre EN UN HILO: pywebpush hace HTTP sincrónico contra el
servicio de push de cada navegador (~100-300 ms por suscripción) y no
puede colgar el request del admin que disparó la novedad. Una suscripción
muerta (404/410: el usuario desinstaló la PWA o revocó el permiso) se
borra sola.
"""

import json
import os
import threading

import db

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", "")


def habilitado() -> bool:
    return bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY and VAPID_CLAIM_EMAIL)


def _enviar_a_suscripciones(suscripciones: list, payload: str) -> None:
    """Cuerpo del hilo: intenta cada suscripción y limpia las muertas."""
    from pywebpush import webpush, WebPushException
    for sus in suscripciones:
        try:
            webpush(
                subscription_info={
                    "endpoint": sus["endpoint"],
                    "keys": {"p256dh": sus["p256dh"], "auth": sus["auth"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
                ttl=60 * 60 * 24,
            )
        except WebPushException as e:
            codigo = getattr(getattr(e, "response", None), "status_code", None)
            if codigo in (404, 410):
                db.borrar_suscripcion_push(sus["endpoint"])
            else:
                print(f"[push] fallo al enviar ({codigo}): {e}")
        except Exception as e:  # nunca tumbar el hilo por una suscripción
            print(f"[push] error inesperado: {type(e).__name__}: {e}")


def notificar_tramite(cuil: str, numero_expediente: str, cuerpo: str) -> None:
    """Push a todas las suscripciones del CUIL. El click abre el detalle
    del trámite directo (deep link ?tramite=)."""
    if not habilitado():
        return
    suscripciones = db.suscripciones_push_de(cuil)
    if not suscripciones:
        return
    payload = json.dumps({
        "titulo": f"Novedad en tu trámite {numero_expediente}",
        "cuerpo": cuerpo,
        "url": f"/app?tab=tramites&tramite={numero_expediente}",
    })
    threading.Thread(target=_enviar_a_suscripciones,
                     args=(suscripciones, payload), daemon=True).start()
