"""Versiones clara y oscura de un logo (logos.monocromo) y su ruta."""
from io import BytesIO

from PIL import Image

import logos


def _png(img):
    b = BytesIO(); img.save(b, "PNG"); return b.getvalue()


def _logo_transparente():
    img = Image.new("RGBA", (100, 60), (0, 0, 0, 0))
    for x in range(30, 70):
        for y in range(15, 45):
            img.putpixel((x, y), (250, 250, 250, 255))
    return _png(img)


def test_color_mas_oscuro():
    assert logos.color_mas_oscuro(["#ffffff", "#152238", "#b23a2e"]) == "#152238"
    assert logos.color_mas_oscuro([None, ""]) == "#152238"


def test_silueta_oscura_de_un_logo_blanco():
    datos, mime = logos.monocromo(_logo_transparente(), "image/png", "#152238")
    out = Image.open(BytesIO(datos)).convert("RGBA")
    assert mime == "image/png"
    assert out.getpixel((50, 30)) == (0x15, 0x22, 0x38, 255)
    assert out.getpixel((2, 2))[3] == 0


def test_logo_opaco_con_fondo_liso_saca_la_silueta():
    img = Image.new("RGB", (100, 60), (255, 255, 255))
    for x in range(30, 70):
        for y in range(15, 45):
            img.putpixel((x, y), (200, 30, 30))
    out = Image.open(BytesIO(logos.monocromo(_png(img), "image/png", "#000000")[0])).convert("RGBA")
    assert out.getpixel((50, 30))[3] == 255 and out.getpixel((2, 2))[3] == 0


def test_lo_que_no_se_puede_se_devuelve_igual():
    assert logos.monocromo(b"no es una imagen", "image/png") == (b"no es una imagen", "image/png")
    svg = b"<svg/>"
    assert logos.monocromo(svg, "image/svg+xml") == (svg, "image/svg+xml")
    todo = _png(Image.new("RGB", (40, 40), (10, 200, 10)))   # sin forma distinguible
    assert logos.monocromo(todo, "image/png")[0] == todo
