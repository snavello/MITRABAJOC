"""Ingreso con Google (OpenID Connect, flujo de código de autorización).

**Google solo IDENTIFICA, nunca crea cuentas** (decisión de SDN, 2026-11-06).
Este módulo devuelve un mail verificado por Google; qué cuenta de la
plataforma le corresponde, y si le corresponde alguna, lo decide `db` y lo abre
`main.py` con las mismas funciones que el login con clave. Sin
`GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` el módulo está apagado
(`configurado()` es False): el botón no se muestra y las rutas dan 404, igual
que Telegram o el canal de mail sin claves.

Reglas (mismo patrón que `correo.py`):
- **Sin librerías**: `urllib` y `hashlib` de la biblioteca estándar. Las
  variables se leen en CADA llamada, así un test puede simularlas.
- **Fail-closed**: ninguna función de acá lanza. Ante CUALQUIER duda (red,
  JSON roto, firma que no cierra, `aud` o `iss` ajenos, token vencido, mail sin
  verificar, `nonce` distinto) devuelven `None` y el ingreso no se abre.
- **Puro**: no importa `db` ni `main`.

**Cómo se verifica el id_token** (`mail_verificado`). Se verifica la FIRMA
RS256 contra las claves públicas de Google (`/oauth2/v3/certs`, con caché de una
hora y un solo reintento por minuto si llega un `kid` desconocido) y después
los reclamos: `alg` exactamente RS256 (nunca `none` ni HS256), `iss` de Google,
`aud` igual al client id, `exp` en el futuro, `email_verified` verdadero, `sub`
y `email` presentes y, si se pidió, el `nonce` de la sesión. Se eligió la
firma con las claves públicas y no el endpoint `tokeninfo`: Google desaconseja
`tokeninfo` en producción (limita el ritmo y suma un viaje por cada ingreso) y
la verificación RSA PKCS#1 v1.5 son unas pocas líneas de enteros de Python,
sin dependencias. El token además viene directo del endpoint de tokens por TLS
y con el secreto del cliente, así que la firma es una segunda barrera, no la
única.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKENS = "https://oauth2.googleapis.com/token"
URL_CLAVES = "https://www.googleapis.com/oauth2/v3/certs"
EMISORES = ("https://accounts.google.com", "accounts.google.com")
TIMEOUT_SEGUNDOS = 10
CACHE_CLAVES_SEGUNDOS = 3600
REINTENTO_CLAVES_SEGUNDOS = 60

# DigestInfo de SHA-256 (RFC 8017, sección 9.2): lo que va delante del hash en
# una firma RSASSA-PKCS1-v1_5.
_PREFIJO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def _client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def configurado() -> bool:
    """¿Están las dos variables? Sin ellas el ingreso con Google no existe."""
    return bool(_client_id() and _client_secret())


def url_autorizacion(redirect_uri: str, state: str, nonce: str = "") -> str:
    """La URL de Google a la que se manda a la persona. Pide solo `openid email`
    (nada de perfil ni de contactos) y fuerza el selector de cuenta, para que
    en un aparato compartido no entre sola la última cuenta de Google."""
    parametros = {
        "client_id": _client_id(), "redirect_uri": redirect_uri,
        "response_type": "code", "scope": "openid email",
        "state": state, "prompt": "select_account"}
    if nonce:
        parametros["nonce"] = nonce
    return URL_AUTORIZACION + "?" + urllib.parse.urlencode(parametros)


def _pedir_json(pedido) -> dict | None:
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEGUNDOS) as resp:
            estado = getattr(resp, "status", None) or resp.getcode()
            if not 200 <= int(estado) < 300:
                return None
            datos = json.loads(resp.read().decode("utf-8"))
            return datos if isinstance(datos, dict) else None
    except Exception as e:           # red, 4xx/5xx, JSON roto: todo igual
        # Ni el código ni los tokens van al log.
        log.warning("google_auth: no se pudo hablar con Google (%s)", type(e).__name__)
        return None


def canjear_codigo(code: str, redirect_uri: str) -> dict | None:
    """Cambia el código de autorización por los tokens (POST server-side con el
    secreto del cliente). Devuelve el dict de Google o None; no lanza."""
    if not configurado() or not (code or "").strip():
        return None
    cuerpo = urllib.parse.urlencode({
        "code": code, "client_id": _client_id(), "client_secret": _client_secret(),
        "redirect_uri": redirect_uri, "grant_type": "authorization_code"}).encode()
    pedido = urllib.request.Request(
        URL_TOKENS, data=cuerpo, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "colm3na-google/1.0"})
    tokens = _pedir_json(pedido)
    return tokens if tokens and tokens.get("id_token") else None


# ---------- Claves públicas de Google y firma RS256 ----------
_cache_claves: dict = {"claves": {}, "hasta": 0.0, "ultimo_intento": 0.0}


def _b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _descargar_claves() -> dict:
    """{kid: (n, e)} de las claves RSA vigentes de Google; {} si falla."""
    pedido = urllib.request.Request(URL_CLAVES, headers={"User-Agent": "colm3na-google/1.0"})
    datos = _pedir_json(pedido) or {}
    claves = {}
    for k in datos.get("keys") or []:
        try:
            if k.get("kty") == "RSA" and k.get("kid"):
                claves[k["kid"]] = (int.from_bytes(_b64(k["n"]), "big"),
                                    int.from_bytes(_b64(k["e"]), "big"))
        except Exception:
            continue
    return claves


def _clave_publica(kid: str):
    """(n, e) de la clave `kid`, con caché. Un `kid` desconocido vuelve a pedir
    las claves, pero no más de una vez por minuto (rotación sí, martillar a
    Google con un token inventado no)."""
    ahora = time.time()
    if ahora < _cache_claves["hasta"] and kid in _cache_claves["claves"]:
        return _cache_claves["claves"][kid]
    if ahora - _cache_claves["ultimo_intento"] < REINTENTO_CLAVES_SEGUNDOS \
            and ahora < _cache_claves["hasta"]:
        return _cache_claves["claves"].get(kid)
    _cache_claves["ultimo_intento"] = ahora
    claves = _descargar_claves()
    if claves:
        _cache_claves["claves"] = claves
        _cache_claves["hasta"] = ahora + CACHE_CLAVES_SEGUNDOS
    return claves.get(kid)


def _firma_rs256_valida(mensaje: bytes, firma: bytes, n: int, e: int) -> bool:
    """RSASSA-PKCS1-v1_5 con SHA-256 (RFC 8017, 8.2.2), con enteros de Python."""
    largo = (n.bit_length() + 7) // 8
    if len(firma) != largo or int.from_bytes(firma, "big") >= n:
        return False
    sufijo = _PREFIJO_SHA256 + hashlib.sha256(mensaje).digest()
    relleno = largo - 3 - len(sufijo)
    if relleno < 8:
        return False
    esperado = b"\x00\x01" + b"\xff" * relleno + b"\x00" + sufijo
    obtenido = pow(int.from_bytes(firma, "big"), e, n).to_bytes(largo, "big")
    return hmac.compare_digest(obtenido, esperado)


def mail_verificado(tokens: dict, nonce: str = "") -> tuple[str, str] | None:
    """(mail, sub) del id_token, o None si cualquier verificación falla.
    El mail sale en minúsculas y sin espacios. Ver el docstring del módulo."""
    try:
        id_token = (tokens or {}).get("id_token", "")
        partes = id_token.split(".") if isinstance(id_token, str) else []
        if len(partes) != 3 or not configurado():
            return None
        cabecera = json.loads(_b64(partes[0]))
        reclamos = json.loads(_b64(partes[1]))
        if not isinstance(cabecera, dict) or not isinstance(reclamos, dict):
            return None
        if cabecera.get("alg") != "RS256" or not cabecera.get("kid"):
            return None
        clave = _clave_publica(cabecera["kid"])
        if not clave or not _firma_rs256_valida(
                (partes[0] + "." + partes[1]).encode("ascii"), _b64(partes[2]), *clave):
            return None
        if reclamos.get("iss") not in EMISORES:
            return None
        if not hmac.compare_digest(str(reclamos.get("aud", "")).encode(), _client_id().encode()):
            return None
        if not isinstance(reclamos.get("exp"), (int, float)) or reclamos["exp"] <= time.time():
            return None
        if reclamos.get("email_verified") not in (True, "true"):
            return None
        if nonce and not hmac.compare_digest(str(reclamos.get("nonce", "")).encode(), nonce.encode()):
            return None
        mail = str(reclamos.get("email", "")).strip().lower()
        sub = str(reclamos.get("sub", "")).strip()
        if not sub or mail.count("@") != 1 or any(c.isspace() for c in mail):
            return None
        return mail, sub
    except Exception as e:
        log.warning("google_auth: id_token rechazado (%s)", type(e).__name__)
        return None
