"""Autenticación propia de la plataforma multi-sindicato (sin terceros).

Cuatro roles, cada uno con su login y su propia cookie (COOKIES_POR_ROL en
main.py: sesion_plataforma / sesion_sindicato / sesion_trabajador /
sesion_empleador; cada rol lee y renueva SOLO la suya):
  - plataforma : admin de plataforma (CUIT + PLATAFORMA_PASSWORD, variables de entorno)
  - sindicato  : administrador de un sindicato (UsuarioSindicato, CUIT + clave)
  - trabajador : trabajador registrado (CuentaTrabajador, CUIL + clave)
  - empleador  : empresa registrada (CuentaEmpleador, CUIT + clave)

Las claves se guardan hasheadas con PBKDF2-HMAC-SHA256 y sal por usuario
(biblioteca estándar, sin dependencias). Las sesiones son tokens firmados
con HMAC (SESSION_SECRET) que viajan en la cookie: no hay estado de sesión
en el servidor. Vencen por INACTIVIDAD (IDLE_TIMEOUT_SEGUNDOS, 15 minutos):
el middleware `renovar_sesion_por_actividad` de main.py reemite la cookie en
cada request autenticado, así un usuario activo nunca se desloguea solo.
Quién es quién en cada request lo resuelve `sesion_actual(request, rol)`,
en main.py.
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

# Sesión por inactividad (sliding window): cada request autenticado reemite
# el token con la marca de tiempo actual (ver middleware en main.py), así que
# esto es "tiempo sin uso" antes de expirar, no un límite fijo desde el login.
IDLE_TIMEOUT_SEGUNDOS = 15 * 60

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
    if time.time() - payload.get("t", 0) > IDLE_TIMEOUT_SEGUNDOS:
        return None
    return payload


def verificar_plataforma(clave: str, cuit: str = None) -> bool:
    ok_clave = hmac.compare_digest(clave, CLAVE_PLATAFORMA)
    if cuit is None:
        return ok_clave
    import re
    cuit_norm = re.sub(r"[^0-9]", "", cuit or "")
    return ok_clave and hmac.compare_digest(cuit_norm, CUIT_PLATAFORMA)
