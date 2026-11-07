"""Toda imagen que se sube a la app se achica en el servidor, con un tope por
tipo (plan de SDN, 2026-11-05).

Puro: recibe bytes y devuelve bytes, no importa `db` ni `main`. El navegador
puede achicar antes de subir (la foto de perfil lo hace), pero el servidor no
confía en eso: lo que se guarda en la base sale siempre de acá.

- Siempre webp, con canal alfa si la original lo tiene (un PNG transparente
  sigue transparente: regla «Logos sin fondo blanco forzado»).
- Respeta la orientación EXIF y NUNCA agranda: una imagen que ya es más chica
  que el tope solo se recomprime.
- Un GIF animado queda como imagen fija del primer cuadro.
- SVG solo en el perfil `logo`, tal cual, si pesa poco y es un SVG de verdad.
- No toca las fotos de portada de los modelos (`fotos_tema`), que tienen su
  propio tratamiento, ni los documentos que lee la IA (recibos, comprobantes).
"""
import re
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

TOPE_ENTRADA = 8 * 1024 * 1024   # más que esto se rechaza sin abrir la imagen
TOPE_SVG = 200 * 1024
PIXELES_MAXIMOS = 40_000_000     # 40 MP: un PNG liso de 11000x11000 pesa 100 KB y ocupa 600 MB al abrirlo

# --- Lo que lee la IA (recibos y comprobantes) -------------------------------
# El lado mayor con el que se trabaja una foto o una página de PDF, y se toma
# UNA sola vez, al abrirla: el OCR, el tapado y lo que viaja a la IA usan la
# MISMA imagen reducida, así las cajas del OCR siguen cayendo sobre lo que se
# tapa. La IA achica por su cuenta lo que pasa de ~1.568 px de lado, así que
# más no suma lectura; y una foto de celular de 12 MP (4000x3000) abierta
# entera son 36 MB por copia, con tres copias vivas pasaba los 150 MB en un
# servicio de 512 MB que ya estaba en 356 (Pruebas, 2026-11-06, OOM).
LADO_MAXIMO_LECTURA = 2000
# Tope de píxeles de ENTRADA, mirado en la cabecera ANTES de decodificar. Un
# JPEG se abre ya reducido (decodificación a escala), así que admite más; el
# resto (PNG, WEBP...) se decodifica entero y se acota más.
PIXELES_MAXIMOS_LECTURA_JPEG = 40_000_000
PIXELES_MAXIMOS_LECTURA = 16_000_000

# lado: tope del lado mayor en px; calidad: webp; svg: si admite SVG.
PERFILES = {
    "logo":        {"lado": 512,  "calidad": 85, "svg": True},
    "firma":       {"lado": 800,  "calidad": 85, "svg": False},
    "perfil":      {"lado": 512,  "calidad": 80, "svg": False},
    "publicacion": {"lado": 1600, "calidad": 80, "svg": False},
    "adjunto":     {"lado": 1600, "calidad": 80, "svg": False},
}

MIME_WEBP = "image/webp"
MIME_SVG = "image/svg+xml"


class ImagenInvalida(Exception):
    """La imagen no se puede usar; el mensaje se muestra tal cual."""


def _tam(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


_MAGIA_RASTER = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"BM")


def _es_raster(datos: bytes) -> bool:
    return datos.startswith(_MAGIA_RASTER) or (datos[:4] == b"RIFF" and datos[8:12] == b"WEBP")


def _es_svg(datos: bytes, nombre: str) -> bool:
    if _es_raster(datos):
        # Un PNG con metadatos C2PA/XMP puede traer un "<svg" adentro (el logo
        # de La Bancaria): por la firma del archivo, es una imagen de píxeles.
        return False
    if nombre.lower().endswith(".svg"):
        return True
    return b"<svg" in datos[:4096].lower()


def _svg_valido(datos: bytes) -> bool:
    """XML bien formado con raíz `svg`. Sin entidades ni DTD: un SVG que las
    declara no se acepta (evita la expansión de entidades), ni scripts, manejadores `on*=` o `javascript:`."""
    import xml.etree.ElementTree as ET
    if b"<!ENTITY" in datos or b"<!DOCTYPE" in datos.upper():
        return False
    bajo = datos.lower()
    if b"<script" in bajo or b"javascript:" in bajo or re.search(rb"\son[a-z]+\s*=", bajo):
        return False
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError:
        return False
    return raiz.tag.split("}")[-1].lower() == "svg"


def achicar(datos: bytes, perfil: str, nombre: str = "") -> dict:
    """Devuelve {"datos", "mime", "ancho", "alto", "bytes_original"}.
    Lanza ImagenInvalida si el archivo no sirve."""
    cfg = PERFILES[perfil]
    if not datos:
        raise ImagenInvalida("El archivo está vacío.")
    original = len(datos)
    if original > TOPE_ENTRADA:
        raise ImagenInvalida(
            f"La imagen pesa {_tam(original)}; el máximo es {_tam(TOPE_ENTRADA)}.")
    if _es_svg(datos, nombre):
        if not cfg["svg"]:
            raise ImagenInvalida("Este tipo de imagen no admite SVG: subí un JPG, PNG o WEBP.")
        if original > TOPE_SVG:
            raise ImagenInvalida(f"El SVG supera {_tam(TOPE_SVG)}.")
        if not _svg_valido(datos):
            raise ImagenInvalida("El archivo no es un SVG válido.")
        return {"datos": datos, "mime": MIME_SVG, "ancho": 0, "alto": 0,
                "bytes_original": original}
    try:
        imagen = Image.open(BytesIO(datos))
        if imagen.width * imagen.height > PIXELES_MAXIMOS:
            raise ImagenInvalida(
                f"La imagen mide {imagen.width}x{imagen.height} px; el máximo es "
                f"{PIXELES_MAXIMOS // 1_000_000} millones de píxeles.")
        imagen.seek(0)       # GIF o WEBP animado: el primer cuadro
        imagen.load()
    except (UnidentifiedImageError, OSError, ValueError, EOFError,
            Image.DecompressionBombError) as e:
        raise ImagenInvalida("El archivo no es una imagen: subí un JPG, PNG o WEBP.") from e
    imagen = ImageOps.exif_transpose(imagen)
    tiene_alfa = imagen.mode in ("RGBA", "LA") or "transparency" in imagen.info
    imagen = imagen.convert("RGBA" if tiene_alfa else "RGB")
    lado = cfg["lado"]
    if max(imagen.size) > lado:     # nunca agranda
        imagen.thumbnail((lado, lado), Image.LANCZOS)
    salida = BytesIO()
    imagen.save(salida, "WEBP", quality=cfg["calidad"], method=6)
    return {"datos": salida.getvalue(), "mime": MIME_WEBP, "ancho": imagen.width,
            "alto": imagen.height, "bytes_original": original}
