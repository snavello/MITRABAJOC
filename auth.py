"""Autenticación para la plataforma multi-sindicato.

Tres roles:
  - plataforma : admin de plataforma (clave fija en variable de entorno)
  - sindicato  : administrador de un sindicato (UsuarioSindicato)
  - trabajador : trabajador registrado (Trabajador)

Las claves se guardan hasheadas (nunca en texto plano). Se usa hashlib con
sal por usuario, de la biblioteca estándar, para no sumar dependencias.

Las sesiones son tokens firmados guardados en una cookie. En memoria para la
PoC; en producción irían a la base o a un store de sesiones.
"""
import os
import hmac
import hashlib
import secrets
import base64
import json
import time
from dotenv import load_dotenv

load_dotenv()

CLAVE_PLATAFORMA = os.getenv("PLATAFORMA_PASSWORD", "plataforma-demo-2026")
CUIT_PLATAFORMA = os.getenv("PLATAFORMA_CUIT", "20000000000")
SECRETO = os.getenv("SESSION_SECRET", "cambiar-este-secreto-en-produccion")

# ---------- Hash de contraseñas ----------
def hashear_clave(clave: str) -> str:
    """Devuelve 'sal$hash' usando PBKDF2-HMAC-SHA256."""
    sal = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), 100_000)
    return f"{sal}${dk.hex()}"


def verificar_clave(clave: str, clave_hash: str) -> bool:
    if not clave_hash or "$" not in clave_hash:
        return False
    sal, guardado = clave_hash.split("$", 1)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), 100_000)
    return hmac.compare_digest(dk.hex(), guardado)


# ---------- Sesiones (cookie firmada) ----------
def crear_sesion(rol: str, id_usuario: int = 0, sindicato_id: int = 0) -> str:
    """Crea un token de sesión firmado con los datos del usuario."""
    payload = {
        "rol": rol, "uid": id_usuario, "sid": sindicato_id,
        "t": int(time.time()),
    }
    cuerpo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    firma = hmac.new(SECRETO.encode(), cuerpo.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{cuerpo}.{firma}"


def leer_sesion(token: str) -> dict | None:
    """Valida la firma del token y devuelve el payload, o None si es inválido."""
    if not token or "." not in token:
        return None
    cuerpo, firma = token.rsplit(".", 1)
    esperada = hmac.new(SECRETO.encode(), cuerpo.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(firma, esperada):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cuerpo.encode()).decode())
    except Exception:
        return None
    # Expiración: 8 horas
    if time.time() - payload.get("t", 0) > 8 * 3600:
        return None
    return payload


def verificar_plataforma(clave: str, cuit: str = None) -> bool:
    ok_clave = hmac.compare_digest(clave, CLAVE_PLATAFORMA)
    if cuit is None:
        return ok_clave
    import re
    cuit_norm = re.sub(r"[^0-9]", "", cuit or "")
    return ok_clave and hmac.compare_digest(cuit_norm, CUIT_PLATAFORMA)
