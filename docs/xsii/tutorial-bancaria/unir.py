"""Apila dos capturas (una arriba de la otra) en un solo JPEG: unir.py SALIDA ARRIBA ABAJO. Borra las dos de entrada."""
import os
import sys

from PIL import Image

salida, a, b = sys.argv[1:4]
x, y = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
ancho = max(x.width, y.width)
lienzo = Image.new("RGB", (ancho, x.height + y.height + 8), (255, 255, 255))
lienzo.paste(x, (0, 0))
lienzo.paste(y, (0, x.height + 8))
lienzo.save(salida, "JPEG", quality=70, optimize=True)
os.remove(a)
os.remove(b)
