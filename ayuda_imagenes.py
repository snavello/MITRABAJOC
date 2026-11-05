"""Imágenes REALES chicas para los tests que suben fotos (el servidor ahora
las abre y las achica: bytes inventados dan 400). Se generan con Pillow."""
from io import BytesIO

from PIL import Image


def imagen_real(formato="PNG", tamano=(40, 30), color=(30, 120, 200)) -> bytes:
    salida = BytesIO()
    Image.new("RGB", tamano, color).save(salida, formato)
    return salida.getvalue()
