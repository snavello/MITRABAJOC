"""Los logos se sirven sin el margen vacío que traen (logos.py).

Correr con: python -m pytest test_logos.py -q
"""
from io import BytesIO

from PIL import Image

import logos


def _png(tam, caja, modo="RGBA", fondo=(0, 0, 0, 0), tinta=(200, 30, 40, 255)):
    img = Image.new(modo, tam, fondo if modo == "RGBA" else fondo[:3])
    img.paste(tinta if modo == "RGBA" else tinta[:3], caja)
    b = BytesIO()
    img.save(b, "PNG" if modo == "RGBA" else "JPEG", quality=95)
    return b.getvalue()


def _abrir(datos):
    return Image.open(BytesIO(datos))


def test_recorta_el_margen_transparente():
    # El caso real de Pruebas: 219×148 con el dibujo en (10, 47, 209, 89).
    datos, mime = logos.recortar(_png((219, 148), (10, 47, 209, 89)), "image/png")
    img = _abrir(datos)
    assert mime == "image/png"
    m = round(199 * logos.MARGEN)
    assert img.size == (199 + 2 * m, 42 + 2 * m)
    assert img.getchannel("A").getpixel((m + 3, m + 3)) == 255


def test_recorta_un_fondo_liso_opaco():
    datos, mime = logos.recortar(_png((400, 400), (100, 150, 300, 250), "RGB",
                                      fondo=(255, 255, 255, 255), tinta=(20, 40, 90, 255)), "image/jpeg")
    img = _abrir(datos)
    assert mime == "image/jpeg"
    assert 200 <= img.width <= 220 and 100 <= img.height <= 120


def test_sin_margen_no_se_toca():
    original = _png((120, 60), (0, 0, 120, 60))
    assert logos.recortar(original, "image/png") == (original, "image/png")


def test_esquinas_distintas_no_se_recorta():
    """Sin un fondo claro (cada esquina de un color) no se adivina."""
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    img.paste((0, 0, 0), (0, 0, 10, 10))
    b = BytesIO(); img.save(b, "PNG")
    assert logos.recortar(b.getvalue(), "image/png")[0] == b.getvalue()


def test_lo_enorme_se_achica():
    datos, _ = logos.recortar(_png((5000, 1500), (0, 0, 5000, 1500)), "image/png")
    assert max(_abrir(datos).size) == logos.LADO_MAXIMO


def test_svg_y_basura_pasan_tal_cual():
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    assert logos.recortar(svg, "image/svg+xml") == (svg, "image/svg+xml")
    assert logos.recortar(b"no soy una imagen", "image/png") == (b"no soy una imagen", "image/png")


def test_la_memoria_distingue_un_logo_nuevo():
    a = _png((219, 148), (10, 47, 209, 89))
    b = _png((300, 300), (0, 0, 300, 300))
    ra = logos.recortado(("sindicato", 999), a, "image/png")
    rb = logos.recortado(("sindicato", 999), b, "image/png")
    assert ra != rb and rb[0] == b


def test_las_rutas_sirven_el_recortado():
    import main
    fuente = open("main.py", encoding="utf-8").read()
    for ruta in ("def servir_logo(", "def servir_logo_plataforma(", "def servir_logo_plataforma_oscuro("):
        cuerpo = fuente.split(ruta, 1)[1].split("\n@app.", 1)[0]
        assert "logos.recortado(" in cuerpo, ruta
    assert main.logos is logos
