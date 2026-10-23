"""Normalización de las fotos de los modelos de diseño (PLAN_TEMAS.md, D5).

Puro: recibe bytes y devuelve bytes. Toda foto que entra a la biblioteca
sale de acá en escala de grises, con los niveles estirados (el 2% más oscuro
y el 2% más claro se recortan), el brillo medio llevado a un valor fijo y el
lado largo acotado. El COLOR no se guarda en el archivo: lo pone cada modelo
al mostrarla (duotono, velos, fundidos), con su paleta o la del sindicato.
Así dos fotos sacadas con luz muy distinta quedan parejas y ninguna rompe los
efectos difusos o luminosos del diseño.
"""
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

LADO_MAXIMO = 1600      # px del lado largo: alcanza para una portada de escritorio
LADO_MINIMO = 600       # una foto más chica se vería pixelada como fondo
BRILLO_MEDIO = 0.46     # luminancia media buscada (0 a 1), la de las fotos de muestra
RECORTE = 2             # % que se recorta en cada punta del histograma
CALIDAD = 82            # webp
MAX_BYTES = 8 * 1024 * 1024


class FotoInvalida(ValueError):
    """La foto no se puede usar; el mensaje se muestra tal cual."""


def normalizar(datos: bytes) -> dict:
    """Devuelve {"datos", "mime", "ancho", "alto"} de la foto normalizada.

    Lanza FotoInvalida si no es una imagen, es muy chica o muy pesada."""
    if not datos:
        raise FotoInvalida("No llegó ninguna foto.")
    if len(datos) > MAX_BYTES:
        raise FotoInvalida("La foto pesa más de 8 MB.")
    try:
        imagen = Image.open(BytesIO(datos))
        imagen.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise FotoInvalida("No se pudo leer la imagen: subí un JPG, PNG o WEBP.") from e
    # La orientación que guardó el teléfono, antes de cualquier otra cosa.
    imagen = ImageOps.exif_transpose(imagen)
    if max(imagen.size) < LADO_MINIMO:
        raise FotoInvalida(f"La foto es muy chica: el lado largo tiene que medir al menos {LADO_MINIMO} px.")
    gris = imagen.convert("L")
    gris.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.LANCZOS)
    gris = ImageOps.autocontrast(gris, cutoff=RECORTE)
    gris = _llevar_brillo(gris, BRILLO_MEDIO)
    salida = BytesIO()
    gris.save(salida, "WEBP", quality=CALIDAD, method=6)
    return {"datos": salida.getvalue(), "mime": "image/webp", "ancho": gris.width, "alto": gris.height}


def brillo_medio(imagen: Image.Image) -> float:
    """Luminancia media de 0 a 1 (para los tests y la pantalla)."""
    hist = imagen.convert("L").histogram()
    total = sum(hist) or 1
    return sum(i * n for i, n in enumerate(hist)) / total / 255


def _llevar_brillo(gris: Image.Image, objetivo: float) -> Image.Image:
    """Corrección gamma para que la media quede cerca del objetivo, sin
    tocar los extremos (el negro sigue negro y el blanco sigue blanco)."""
    import math
    # Una pasada alcanza en una foto común; con histogramas muy partidos
    # (mucha sombra y mucho cielo) hacen falta dos o tres.
    for _ in range(4):
        media = min(0.95, max(0.05, brillo_medio(gris)))
        if abs(media - objetivo) < 0.02:
            break
        gamma = math.log(objetivo) / math.log(media)
        gris = gris.point([round(255 * ((i / 255) ** gamma)) for i in range(256)])
    return gris
