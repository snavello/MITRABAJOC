"""Normalización de las fotos de los modelos de diseño (PLAN_TEMAS.md, D5).

Puro: recibe bytes y devuelve bytes. Toda foto que entra a la biblioteca
sale de acá en DOS versiones del mismo tamaño: la **normalizada**, en escala
de grises, con los niveles estirados (el 2% más oscuro y el 2% más claro se
recortan), el brillo medio llevado a un valor fijo y el lado largo acotado;
y la **original en color**, tal cual vino (solo orientada y acotada al mismo
lado largo). Con la normalizada el color lo pone cada modelo al mostrarla
(duotono, velos, fundidos), con su paleta o la del sindicato: así dos fotos
sacadas con luz muy distinta quedan parejas y ninguna rompe los efectos
difusos o luminosos del diseño. La de color existe porque los sindicatos
pidieron verlas a veces en color (2026-10-29): cada uno elige, por modelo,
cuánto color mostrar (`SATURACIONES`), y la pantalla funde la de color sobre
la normalizada con esa opacidad. Nunca se elige por foto: es un ajuste del
sindicato que vale para la foto que tenga de portada.
"""
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

LADO_MAXIMO = 1600      # px del lado largo: alcanza para una portada de escritorio
LADO_MINIMO = 600       # una foto más chica se vería pixelada como fondo
BRILLO_MEDIO = 0.46     # luminancia media buscada (0 a 1), la de las fotos de muestra
RECORTE = 2             # % que se recorta en cada punta del histograma
CALIDAD = 82            # webp de la normalizada
CALIDAD_COLOR = 85      # webp de la original en color (se ve sin velo: un poco más)
MAX_BYTES = 8 * 1024 * 1024

# Cuánto color muestra el sindicato sobre la normalizada: 0 = la normalizada
# sola (la de siempre, teñida por el modelo), 100 = la original a todo color,
# y en el medio la de color fundida con esa opacidad sobre la normalizada,
# así el tinte del modelo sigue abajo. Se guarda el número; la etiqueta es
# de la pantalla.
SATURACIONES = (
    (0, "Normalizada"),
    (25, "25 % de color"),
    (50, "50 % de color"),
    (75, "75 % de color"),
    (100, "Full color"),
)
SATURACION_DEFECTO = 0


class FotoInvalida(ValueError):
    """La foto no se puede usar; el mensaje se muestra tal cual."""


def saturacion_valida(valor):
    """El nivel del catálogo que nombra `valor` (texto o número), o None."""
    try:
        n = int(str(valor).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return None
    return n if n in {nivel for nivel, _ in SATURACIONES} else None


def normalizar(datos: bytes) -> dict:
    """Devuelve {"datos", "mime", "ancho", "alto", "datos_color", "mime_color"}:
    la foto normalizada (gris) y la original en color, las dos del mismo
    tamaño y con la misma orientación, así una se funde sobre la otra.

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
    # Un solo achique para las dos versiones: así miden exactamente lo mismo
    # y el punto de interés vale para ambas.
    color = imagen.convert("RGB")
    color.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.LANCZOS)
    gris = color.convert("L")
    gris = ImageOps.autocontrast(gris, cutoff=RECORTE)
    gris = _llevar_brillo(gris, BRILLO_MEDIO)
    salida = BytesIO()
    gris.save(salida, "WEBP", quality=CALIDAD, method=6)
    salida_color = BytesIO()
    color.save(salida_color, "WEBP", quality=CALIDAD_COLOR, method=6)
    return {"datos": salida.getvalue(), "mime": "image/webp", "ancho": gris.width, "alto": gris.height,
            "datos_color": salida_color.getvalue(), "mime_color": "image/webp"}


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
