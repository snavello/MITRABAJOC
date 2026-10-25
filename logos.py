"""Los logos tal como se muestran: sin el margen vacío que traen pegado.

Puro: recibe bytes y devuelve bytes. Muchos logos llegan con un margen
transparente (o de un color liso) alrededor del dibujo: un PNG de 219×148
cuyo dibujo ocupa 42 px de alto se ve, en una caja de 64 px de alto, como un
sello de 18 px. La caja no puede saberlo; el servidor sí. Así que `/logo/{id}`
y los logos de la plataforma se sirven recortados al dibujo, con un margen
chico y parejo, y acotados de tamaño (los enormes, de más de PIXELES_MAXIMOS, pasan tal
cual: no se decodifican). El archivo guardado NO se toca: si el
recorte se equivoca, se arregla acá y vuelve a salir bien para todos.

Un SVG pasa tal cual (no es un mapa de píxeles), y lo que no se pueda leer
también: nunca se deja de mostrar un logo por intentar mejorarlo.
"""
import threading
from collections import OrderedDict
from io import BytesIO

from PIL import Image, ImageChops, UnidentifiedImageError

MARGEN = 0.03           # del lado largo del dibujo, alrededor
LADO_MAXIMO = 1200      # px: el logo más grande de la app mide 320 px de ancho
# Arriba de esto no se toca: decodificar un PNG de 8854×2559 en RGBA son 90 MB,
# y con las copias del recorte pasaba los 512 MB de Pruebas y tumbaba el
# servidor (2026-10-23). El tamaño se lee de la cabecera, sin decodificar.
PIXELES_MAXIMOS = 2_500_000
ALFA_MINIMO = 12        # un píxel casi transparente (sombras, antialias suelto) no es dibujo
TOLERANCIA_FONDO = 18   # diferencia por canal con la esquina para contar como fondo liso
_CACHE_MAX = 64

_cache: OrderedDict = OrderedDict()
# De a uno por proceso: dos recortes a la vez duplican la memoria.
_candado = threading.Lock()


def _caja_del_dibujo(img: Image.Image):
    """(izq, arriba, der, abajo) de lo que no es fondo, o None si no hay
    margen que sacar (o la imagen es toda fondo)."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        alfa = img.convert("RGBA").getchannel("A")
        caja = alfa.point(lambda a: 255 if a >= ALFA_MINIMO else 0).getbbox()
        # Un PNG con canal alfa pero opaco entero cae al caso del fondo liso.
        if caja and caja != (0, 0, img.width, img.height):
            return caja
        if caja is None:
            return None
    rgb = img.convert("RGB")
    esquinas = [rgb.getpixel(p) for p in ((0, 0), (img.width - 1, 0),
                                          (0, img.height - 1), (img.width - 1, img.height - 1))]
    ref = esquinas[0]
    # Solo si las cuatro esquinas son del mismo color: si no, no hay un
    # "fondo" claro y recortar podría comerse el dibujo.
    if any(max(abs(a - b) for a, b in zip(e, ref)) > TOLERANCIA_FONDO for e in esquinas):
        return None
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, ref)).convert("L")
    return diff.point(lambda v: 255 if v > TOLERANCIA_FONDO else 0).getbbox()


def recortar(datos: bytes, mime: str) -> tuple[bytes, str]:
    """(bytes, mime) del logo sin el margen vacío. Si no hay nada que
    recortar ni que achicar, o no se puede leer, devuelve lo mismo."""
    if not datos or "svg" in (mime or "").lower():
        return datos, mime
    try:
        img = Image.open(BytesIO(datos))      # perezoso: todavía no decodifica
        if img.width * img.height > PIXELES_MAXIMOS:
            return datos, mime
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        return datos, mime
    caja = _caja_del_dibujo(img)
    grande = max(img.size) > LADO_MAXIMO
    if not caja and not grande:
        return datos, mime
    con_alfa = img.mode in ("RGBA", "LA", "P")
    img = img.convert("RGBA" if con_alfa else "RGB")
    if caja:
        izq, arr, der, aba = caja
        m = round(max(der - izq, aba - arr) * MARGEN)
        caja = (max(0, izq - m), max(0, arr - m), min(img.width, der + m), min(img.height, aba + m))
        img = img.crop(caja)
    if max(img.size) > LADO_MAXIMO:
        img.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.LANCZOS)
    salida = BytesIO()
    if con_alfa:
        img.save(salida, "PNG", optimize=True)
        return salida.getvalue(), "image/png"
    img.save(salida, "JPEG", quality=92)
    return salida.getvalue(), "image/jpeg"


def recortado(clave, datos: bytes, mime: str, funcion=None) -> tuple[bytes, str]:
    """`recortar` (o `funcion(datos, mime)`) con memoria por proceso. La clave lleva el largo de los
    bytes, el mismo sello `?v=` de las plantillas: un logo nuevo es otra
    clave y nunca se sirve el recorte del anterior."""
    k = (clave, len(datos or b""))
    if k in _cache:
        _cache.move_to_end(k)
        return _cache[k]
    with _candado:
        if k in _cache:
            return _cache[k]
        r = (funcion or recortar)(datos, mime)
    _cache[k] = r
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return r


# ---------------------------------------------------------------------------
# Versiones claras y oscuras de un logo a color (2026-10-25)
#
# Un logo se sube UNA vez, pensado para el fondo oscuro del encabezado, y a
# veces es casi blanco: sobre las burbujas del mapa o un encabezado claro no
# se ve. De la silueta del dibujo (su alfa, o su diferencia con el fondo liso
# si no tiene transparencia) se arma el mismo logo en un solo color: BLANCO
# para fondo oscuro, o el color más oscuro de la marca para fondo claro.
# Si el archivo no deja sacar una silueta (SVG, ilegible, fondo no liso) se
# devuelve tal cual: nunca se deja de mostrar un logo por intentar mejorarlo.
# ---------------------------------------------------------------------------

def _luminancia(hexa: str) -> float:
    h = (hexa or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return 255.0
    return 0.299 * r + 0.587 * g + 0.114 * b


def color_mas_oscuro(colores, por_defecto: str = "#152238") -> str:
    """El más oscuro (por luminancia percibida) de los colores válidos."""
    validos = [c for c in colores if isinstance(c, str) and len(c.lstrip("#")) in (3, 6)
               and _luminancia(c) < 255.0]
    return min(validos, key=_luminancia) if validos else por_defecto


def _silueta(img: Image.Image):
    """Canal alfa (modo L) con la forma del dibujo, o None si no se puede
    distinguir del fondo."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        alfa = img.convert("RGBA").getchannel("A")
        # Un PNG con canal alfa pero opaco entero se trata como fondo liso.
        if alfa.getextrema()[0] < 250:
            return alfa
    rgb = img.convert("RGB")
    esquinas = [rgb.getpixel(p) for p in ((0, 0), (img.width - 1, 0),
                                          (0, img.height - 1), (img.width - 1, img.height - 1))]
    ref = esquinas[0]
    if any(max(abs(a - b) for a, b in zip(e, ref)) > TOLERANCIA_FONDO for e in esquinas):
        return None
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, ref)).convert("L")
    # Rampa suave (no corte duro) para conservar el antialias del borde.
    return diff.point(lambda v: 0 if v <= TOLERANCIA_FONDO else min(255, (v - TOLERANCIA_FONDO) * 6))


def monocromo(datos: bytes, mime: str, color: str = "#ffffff") -> tuple[bytes, str]:
    """El logo como silueta de un solo `color`. Devuelve (datos, mime) del
    PNG; si no se puede, lo mismo que recibió."""
    if not datos or "svg" in (mime or "").lower():
        return datos, mime
    try:
        img = Image.open(BytesIO(datos))
        if img.width * img.height > PIXELES_MAXIMOS:
            return datos, mime
        img.load()
        alfa = _silueta(img)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        return datos, mime
    # Una "silueta" que cubre casi todo (o nada) es un logo sin fondo
    # distinguible: pintarla de un color sería un rectángulo.
    ext = alfa.getextrema() if alfa else None
    if alfa is None or ext[1] < ALFA_MINIMO:
        return datos, mime
    cubierto = sum(alfa.point(lambda a: 255 if a > 128 else 0).histogram()[255:]) / (img.width * img.height)
    if cubierto > 0.92:
        return datos, mime
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        rgb = (255, 255, 255)
    salida_img = Image.new("RGBA", img.size, rgb + (0,))
    salida_img.putalpha(alfa)
    salida = BytesIO()
    salida_img.save(salida, "PNG", optimize=True)
    return salida.getvalue(), "image/png"


def monocromo_recortado(clave, datos: bytes, mime: str, color: str) -> tuple[bytes, str]:
    """`monocromo` sobre el logo ya recortado, con la misma memoria por
    proceso de `recortado` (la clave lleva tono y color)."""
    return recortado((clave, "mono", color), datos, mime, lambda d, m: monocromo(*recortar(d, m), color))
