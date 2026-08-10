"""QR de verificación de la credencial sindical. Solo `segno` (Python puro,
sin Pillow): genera el SVG como texto para embeber inline en la página.
"""
import io
import segno


def qr_svg(datos: str, escala: int = 4) -> str:
    """SVG <svg>...</svg> como string, listo para insertar con |safe."""
    qr = segno.make(datos, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", xmldecl=False, svgns=True, scale=escala,
             dark="#152238", light=None)
    return buf.getvalue().decode("utf-8")


def url_verificacion(base_url: str, token: str, nombre: str, cuil: str, codigo_credencial: str) -> str:
    """URL que va adentro del QR. Doble propósito, a propósito:
    - Escaneada con conexión: /v/{token} muestra los datos verificados por
      el servidor (el token es lo único que se usa para buscar; los query
      params NO son de fiar, son solo el respaldo legible sin conexión).
    - Leída como texto plano (sin abrir el link, ej. desde la vista previa
      de cualquier lector de QR): ya deja ver nombre/CUIL/N° de credencial.
    A propósito NO lleva el DNI: una foto de la credencial no debe filtrarlo.
    """
    from urllib.parse import urlencode
    base = base_url.rstrip("/")
    query = urlencode({"n": nombre or "", "c": cuil or "", "num": codigo_credencial or ""})
    return f"{base}/v/{token}?{query}"
