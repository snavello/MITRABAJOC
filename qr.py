"""QR de verificación de la credencial sindical. Solo `segno` (Python puro,
sin Pillow): genera el SVG como texto para embeber inline en la página.

El QR es EFÍMERO: lo que va adentro no es solo el token permanente del
trabajador, sino ese token más un código firmado que vence a los 10 minutos.
Cada vez que el trabajador abre la credencial se emite uno nuevo, y la app lo
renueva sola antes de que venza. Así una captura de pantalla del QR deja de
verificar apenas pasa la ventana: sirve para mostrarlo en el momento, no para
reenviarlo por mensaje.
"""
import hashlib
import hmac
import io
import re
import time
import segno

import auth

# Ventana de validez del código que viaja en el QR. Diez minutos: alcanza para
# mostrar la credencial en una guardia o en la puerta de una obra, y es poco
# para que la captura le sirva a otro.
TTL_QR_SEGUNDOS = 600


def qr_svg(datos: str, escala: int = 4) -> str:
    """SVG <svg>...</svg> como string, listo para insertar con |safe.

    segno no le pone `viewBox` al <svg>, solo `width`/`height` fijos. Sin
    viewBox, el CSS que lo reescala a otro tamaño (`.cred-qr svg { width:64px;
    height:64px }`) no lo escala: el navegador lo RECORTA a esas dimensiones,
    mostrando el QR cortado (así se vio en la credencial). Se le agrega el
    viewBox con las mismas dimensiones que declaró segno para que el QR
    completo escale proporcionalmente a cualquier tamaño que le pida el CSS.
    """
    qr = segno.make(datos, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", xmldecl=False, svgns=True, scale=escala,
             dark="#152238", light=None)
    svg = buf.getvalue().decode("utf-8")
    m = re.search(r'width="(\d+)"\s+height="(\d+)"', svg)
    if m and "viewBox" not in svg:
        w, h = m.group(1), m.group(2)
        svg = svg.replace(f'width="{w}" height="{h}"',
                           f'width="{w}" height="{h}" viewBox="0 0 {w} {h}"', 1)
    return svg


def codigo_efimero(token: str, ttl: int = TTL_QR_SEGUNDOS, ahora: float = None) -> tuple:
    """Devuelve (codigo, segundos_de_vida) para meter en la URL del QR.

    El código es `{vencimiento}.{firma}`, firmado con el mismo secreto de
    sesión (auth.SECRETO). No se guarda nada: el servidor lo revalida
    recalculando la firma, así que no hace falta tabla ni limpieza de códigos
    viejos, y un reinicio no invalida las credenciales.
    """
    ahora = time.time() if ahora is None else ahora
    vence = int(ahora) + ttl
    return f"{vence}.{_firma(token, vence)}", ttl


def verificar_codigo_efimero(token: str, codigo: str, ahora: float = None) -> bool:
    """True solo si el código está bien firmado para ese token y no venció."""
    if not token or not codigo or "." not in codigo:
        return False
    vence_txt, firma = codigo.split(".", 1)
    if not vence_txt.isdigit():
        return False
    vence = int(vence_txt)
    if vence < (time.time() if ahora is None else ahora):
        return False
    return hmac.compare_digest(firma, _firma(token, vence))


def _firma(token: str, vence: int) -> str:
    return hmac.new(auth.SECRETO.encode(), f"{token}.{vence}".encode(),
                    hashlib.sha256).hexdigest()[:16]


def url_verificacion(base_url: str, token: str, nombre: str, cuil: str,
                      codigo_credencial: str, codigo: str = "") -> str:
    """URL que va adentro del QR. Doble propósito, a propósito:
    - Escaneada con conexión: /v/{token} muestra los datos verificados por
      el servidor (el token es lo único que se usa para buscar; los query
      params NO son de fiar, son solo el respaldo legible sin conexión).
      El parámetro `k` es la excepción: no aporta datos, es el código
      efímero firmado y sin él (o vencido) la página no muestra nada.
    - Leída como texto plano (sin abrir el link, ej. desde la vista previa
      de cualquier lector de QR): ya deja ver nombre/CUIL/N° de credencial.
    A propósito NO lleva el DNI: una foto de la credencial no debe filtrarlo.
    """
    from urllib.parse import urlencode
    base = base_url.rstrip("/")
    query = urlencode({"n": nombre or "", "c": cuil or "",
                        "num": codigo_credencial or "", "k": codigo or ""})
    return f"{base}/v/{token}?{query}"
