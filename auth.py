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

def _requerido(nombre: str, ayuda: str) -> str:
    """Una variable de entorno que NO puede faltar ni caer a un default: si
    no está, la app no arranca (mismo criterio que DATABASE_URL en db.py).
    Antes SESSION_SECRET y PLATAFORMA_PASSWORD tenían un default escrito en
    el código (XSK H-0001/H-0002): sin la variable, se firmaba con un secreto
    público y se entraba a plataforma con la clave del repositorio. Ahora
    fallan cerrado. Los valores reales viven en el .env (local) y en Render."""
    valor = os.getenv(nombre, "").strip()
    if not valor:
        raise RuntimeError(
            f"Falta {nombre}: es obligatoria y no tiene valor por defecto.\n"
            f"  - {ayuda}\n"
            "  - Desarrollo local: ponela en el .env (ver .env.example).\n"
            "  - Render: cargala en las variables del servicio.")
    return valor


CLAVE_PLATAFORMA = _requerido(
    "PLATAFORMA_PASSWORD", "Es la clave del panel de plataforma; elegí una fuerte.")
CUIT_PLATAFORMA = os.getenv("PLATAFORMA_CUIT", "20000000000")
SECRETO = _requerido(
    "SESSION_SECRET", "Firma todas las cookies de sesión; usá una cadena larga y aleatoria.")

# Sesión por inactividad (sliding window): cada request autenticado reemite
# el token con la marca de tiempo actual (ver middleware en main.py), así que
# esto es "tiempo sin uso" antes de expirar, no un límite fijo desde el login.
IDLE_TIMEOUT_SEGUNDOS = 15 * 60

# ---------- Hash de contraseñas ----------
# PBKDF2-HMAC-SHA256. El costo (iteraciones) subió de 100.000 a 600.000, la
# guía OWASP 2023 (XSK H-0009). El formato NUEVO incluye el número de
# iteraciones (`sha256$600000$sal$hash`) para poder cambiarlo sin romper las
# claves ya guardadas: un hash VIEJO (`sal$hash`, sin iteraciones) se sigue
# validando a 100.000, y se re-hashea al costo nuevo la próxima vez que la
# persona cambie la clave.
ITERACIONES = 600_000
ITERACIONES_LEGADO = 100_000


def hashear_clave(clave: str) -> str:
    """Devuelve 'sha256$<iter>$sal$hash' usando PBKDF2-HMAC-SHA256."""
    sal = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), ITERACIONES)
    return f"sha256${ITERACIONES}${sal}${dk.hex()}"


def verificar_clave(clave: str, clave_hash: str) -> bool:
    if not clave_hash:
        return False
    partes = clave_hash.split("$")
    if len(partes) == 4 and partes[0] == "sha256":      # formato nuevo con iteraciones
        try:
            iteraciones = int(partes[1])
        except ValueError:
            return False
        sal, guardado = partes[2], partes[3]
    elif len(partes) == 2:                               # formato legado: sal$hash, 100.000
        sal, guardado = partes
        iteraciones = ITERACIONES_LEGADO
    else:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), iteraciones)
    return hmac.compare_digest(dk.hex(), guardado)


def hash_desactualizado(clave_hash: str) -> bool:
    """True si el hash usa un formato o costo viejo y conviene re-hashearlo
    (al próximo login/cambio de clave). Hoy: cualquier hash que no sea el
    formato nuevo con las iteraciones vigentes."""
    partes = (clave_hash or "").split("$")
    return not (len(partes) == 4 and partes[0] == "sha256" and partes[1] == str(ITERACIONES))


# ---------- Sesiones (cookie firmada) ----------
def crear_sesion(rol: str, id_usuario: int = 0, sindicato_id: int = 0, ident: str = "") -> str:
    """Crea un token de sesión firmado con los datos del usuario.

    `ident` es la identidad del trabajador/empleador (CUIL/CUIT) que ANTES
    viajaba en una cookie aparte SIN firmar (`cuil_trab`/`cuit_emp`): el
    servidor le creía y se podía suplantar a otro cambiándola (XSK H-0004).
    Ahora va firmada acá adentro, y las rutas la leen de la sesión, no de la
    cookie plana."""
    payload = {
        "rol": rol, "uid": id_usuario, "sid": sindicato_id, "ident": ident,
        "t": int(time.time()),
    }
    # Sin el padding "=" del base64: un "=" en el valor obliga al navegador (y
    # a http.cookies) a entrecomillar la cookie, y esas comillas rompen la
    # lectura del token. La longitud del payload cambió al sumar `ident`, lo
    # que destapó el problema; quitar el padding lo evita de raíz. Se re-agrega
    # al decodificar (leer_sesion).
    cuerpo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
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
        # Re-agregar el padding "=" que crear_sesion quita (múltiplo de 4).
        relleno = cuerpo + "=" * (-len(cuerpo) % 4)
        payload = json.loads(base64.urlsafe_b64decode(relleno.encode()).decode())
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
