"""Los logos tal como se muestran: sin el margen vacío que traen pegado.

Puro: recibe bytes y devuelve bytes. Muchos logos llegan con un margen
transparente (o de un color liso) alrededor del dibujo: un PNG de 219×148
cuyo dibujo ocupa 42 px de alto se ve, en una caja de 64 px de alto, como un
sello de 18 px. La caja no puede saberlo; el servidor sí. Así que `/logo/{id}`
y los logos de la plataforma se sirven recortados al dibujo, con un margen
chico y parejo, y acotados de tamaño. El archivo guardado NO se toca: si el
recorte se equivoca, se arregla acá y vuelve a salir bien para todos.

Un SVG pasa tal cual (no es un mapa de píxeles), y lo que no se pueda leer
también: nunca se deja de mostrar un logo por intentar mejorarlo.
"""
from collections import OrderedDict
from io import BytesIO

from PIL import Image, ImageChops, UnidentifiedImageError

MARGEN = 0.03           # del lado largo del dibujo, alrededor
LADO_MAXIMO = 1200      # px: el logo más grande de la app mide 320 px de ancho
ALFA_MINIMO = 12        # un píxel casi transparente (sombras, antialias suelto) no es dibujo
TOLERANCIA_FONDO = 18   # diferencia por canal con la esquina para contar como fondo liso
_CACHE_MAX = 64

_cache: OrderedDict = OrderedDict()


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
        img = Image.open(BytesIO(datos))
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


def recortado(clave, datos: bytes, mime: str) -> tuple[bytes, str]:
    """`recortar` con memoria por proceso. La clave lleva el largo de los
    bytes, el mismo sello `?v=` de las plantillas: un logo nuevo es otra
    clave y nunca se sirve el recorte del anterior."""
    k = (clave, len(datos or b""))
    if k in _cache:
        _cache.move_to_end(k)
        return _cache[k]
    r = recortar(datos, mime)
    _cache[k] = r
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return r
