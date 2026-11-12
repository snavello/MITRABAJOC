"""MercadoPago Checkout Pro para las entradas de la Fiesta (PLAN_FIESTA.md, D2).

Reglas:
- **Sin SDK**: `urllib` y dos llamadas a la API (preferencia y consulta de un
  pago), el mismo patrón de `correo.py`. Las variables se leen en CADA llamada,
  así los tests las simulan:
    MP_ACCESS_TOKEN    token de la aplicación de MercadoPago (del sindicato)
    MP_WEBHOOK_SECRET  clave secreta del webhook (para validar `x-signature`)
    MP_MOCK=1          el pago se simula sin salir a la red
- **Nunca lanza hacia la ruta**: devuelve None / False y deja una línea en el
  log SIN el token, la firma ni datos de personas.
- **Puro**: no importa `db`. El mock guarda en memoria los pagos que simula la
  página de prueba, para que `obtener_pago` los devuelva como lo haría MP.
- La plata va de MercadoPago a la cuenta del sindicato; Colm3na no la toca.
"""
import hashlib
import hmac
import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

API = "https://api.mercadopago.com"
TIMEOUT_SEGUNDOS = 15
_MOCK_PAGOS: dict = {}          # payment_id -> pago simulado


def _token() -> str:
    return os.getenv("MP_ACCESS_TOKEN", "").strip()


def _secreto() -> str:
    return os.getenv("MP_WEBHOOK_SECRET", "").strip()


def _mock_prendido() -> bool:
    return os.getenv("MP_MOCK", "").strip().lower() in ("1", "true", "si", "sí", "on")


def modo() -> str:
    """"mock" (simulado, sin red), "real" (hay token) o "apagado". El mock
    gana: prenderlo es una decisión explícita para probar."""
    if _mock_prendido():
        return "mock"
    return "real" if _token() else "apagado"


def habilitado() -> bool:
    return modo() != "apagado"


def secreto_configurado() -> bool:
    return bool(_secreto())


def faltantes() -> list:
    """Qué variables faltan para cobrar de verdad (para decírselo al admin)."""
    if _mock_prendido():
        return []
    return [v for v, ok in (("MP_ACCESS_TOKEN", bool(_token())),
                            ("MP_WEBHOOK_SECRET", bool(_secreto()))) if not ok]


# ---------- Preferencia ----------
def _post_json(ruta: str, cuerpo: dict):
    pedido = urllib.request.Request(
        API + ruta, data=json.dumps(cuerpo).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEGUNDOS) as r:     # nosec B310: https fijo
        return json.loads(r.read().decode("utf-8"))


def _get_json(ruta: str):
    pedido = urllib.request.Request(API + ruta, method="GET",
                                    headers={"Authorization": f"Bearer {_token()}"})
    with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEGUNDOS) as r:     # nosec B310
        return json.loads(r.read().decode("utf-8"))


def crear_preferencia(reserva_id: int, titulo: str, importe: int, base_url: str,
                      vence_iso: str = "") -> dict | None:
    """Crea el checkout y devuelve {"id", "init_point"}, o None si no se pudo.

    `base_url` es el origen público de la app (en Pruebas, https): a ahí vuelve
    la persona y ahí avisa MercadoPago. Con `MP_MOCK` el `init_point` es la
    página simulada de la propia app y no se sale a la red."""
    base = (base_url or "").rstrip("/")
    m = modo()
    if m == "apagado":
        return None
    if m == "mock":
        return {"id": f"MOCK-{reserva_id}", "init_point": f"{base}/fiesta/mp-simulado/{reserva_id}"}
    vuelta = f"{base}/fiesta/pago/vuelta?reserva={reserva_id}&estado="
    cuerpo = {
        "items": [{"title": (titulo or "Entrada")[:250], "quantity": 1,
                   "unit_price": int(importe), "currency_id": "ARS"}],
        "external_reference": str(reserva_id),
        "notification_url": f"{base}/api/fiesta/mp/webhook",
        "back_urls": {"success": vuelta + "success", "failure": vuelta + "failure",
                      "pending": vuelta + "pending"},
        "statement_descriptor": "FIESTA SUPARA",
    }
    if base.startswith("https://"):
        # MercadoPago rechaza auto_return si las back_urls no son https.
        cuerpo["auto_return"] = "approved"
    if vence_iso:
        cuerpo["expires"] = True
        cuerpo["expiration_date_to"] = vence_iso
    try:
        r = _post_json("/checkout/preferences", cuerpo)
        if r.get("id") and r.get("init_point"):
            return {"id": str(r["id"]), "init_point": r["init_point"]}
        log.warning("mercadopago: la preferencia volvió sin id/init_point")
    except Exception as e:          # red, 4xx/5xx o JSON roto: nunca hacia la ruta
        log.warning("mercadopago: no se pudo crear la preferencia (%s)", type(e).__name__)
    return None


# ---------- Webhook ----------
def _partes_firma(x_signature: str) -> dict:
    partes = {}
    for trozo in (x_signature or "").split(","):
        k, _, v = trozo.strip().partition("=")
        if k:
            partes[k.strip()] = v.strip()
    return partes


def validar_firma(x_signature: str, x_request_id: str, data_id: str, secreto: str) -> bool:
    """Valida el `x-signature` del webhook como lo documenta MercadoPago:
    manifest `id:{data.id};request-id:{x-request-id};ts:{ts};`, HMAC-SHA256
    con la clave secreta, comparado en tiempo constante contra `v1`. Si
    `data.id` es alfanumérico va en minúsculas. Falla cerrado ante cualquier
    dato que falte."""
    if not (x_signature and secreto and data_id):
        return False
    partes = _partes_firma(x_signature)
    ts, v1 = partes.get("ts", ""), partes.get("v1", "")
    if not ts or not v1:
        return False
    did = str(data_id)
    if did.isalnum():
        did = did.lower()
    manifest = f"id:{did};request-id:{x_request_id or ''};ts:{ts};"
    esperada = hmac.new(secreto.encode("utf-8"), manifest.encode("utf-8"),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada.encode("utf-8"), v1.lower().encode("utf-8"))


def firmar(data_id: str, x_request_id: str, ts: str, secreto: str) -> str:
    """El `x-signature` que armaría MercadoPago (lo usan los tests y la página
    simulada para ejercitar el mismo camino del webhook)."""
    did = str(data_id).lower() if str(data_id).isalnum() else str(data_id)
    manifest = f"id:{did};request-id:{x_request_id};ts:{ts};"
    v1 = hmac.new(secreto.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


# ---------- Pagos ----------
def registrar_pago_mock(payment_id: str, status: str, external_reference: str,
                        importe) -> dict:
    """La página simulada deja acá el pago que 'hizo' la persona."""
    pago = {"id": str(payment_id), "status": status,
            "external_reference": str(external_reference),
            "transaction_amount": float(importe)}
    _MOCK_PAGOS[str(payment_id)] = pago
    return pago


def obtener_pago(payment_id) -> dict | None:
    """El pago tal cual lo conoce MercadoPago: {"id", "status",
    "external_reference", "transaction_amount"}. None si no se pudo consultar."""
    m = modo()
    pid = str(payment_id or "").strip()
    if m == "apagado" or not pid:
        return None
    if m == "mock":
        return _MOCK_PAGOS.get(pid)
    if not pid.isalnum():
        return None             # el id viaja en la ruta: nada de caracteres raros
    try:
        r = _get_json(f"/v1/payments/{pid}")
        return {"id": str(r.get("id", pid)), "status": str(r.get("status", "")),
                "external_reference": str(r.get("external_reference") or ""),
                "transaction_amount": float(r.get("transaction_amount") or 0)}
    except Exception as e:
        log.warning("mercadopago: no se pudo consultar el pago (%s)", type(e).__name__)
        return None
