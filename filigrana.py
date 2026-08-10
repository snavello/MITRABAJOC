"""Filigrana (guilloche) de fondo para la credencial sindical.

Sin dependencias externas ni almacenamiento: un SVG inline generado a partir
de una semilla determinística por sindicato. La curva es un rosetón de dos
frecuencias superpuestas (la base matemática de las filigranas de billetes y
títulos). El entramado sale de la INTERFERENCIA entre capas rotadas del mismo
tamaño, no de anidar círculos concéntricos — anidar deja un núcleo denso que
tapa el texto.
"""
import hashlib
from math import cos, sin, pi, gcd


def _semilla(texto: str) -> int:
    return int(hashlib.sha256((texto or "").encode("utf-8")).hexdigest()[:8], 16)


def _coprimo_de(n: int, desde: int) -> int:
    k = desde
    while gcd(k, n) != 1:
        k += 1
    return k


def _guilloche(a: int, b: int, amp_a: float, amp_b: float, radio: float,
               puntos: int = 900, fase: float = 0.0) -> str:
    pts = []
    for i in range(puntos + 1):
        t = 2 * pi * i / puntos
        x = radio * (amp_a * cos(a * t) + amp_b * cos(b * t + fase))
        y = radio * (amp_a * sin(a * t) - amp_b * sin(b * t + fase))
        pts.append(f"{x:.2f},{y:.2f}")
    return "M" + "L".join(pts) + "Z"


def filigrana_svg(nombre_sindicato: str, color_secundario: str, color_acento: str,
                   ancho: int = 380, alto: int = 240) -> str:
    """SVG de fondo (sin <svg> width/height fijo: se estira con CSS), tenue y
    determinístico por sindicato. Pensado como fondo detrás de la credencial."""
    s = _semilla(nombre_sindicato)
    a = 3 + (s % 4)                         # 3..6  pétalos base
    b = _coprimo_de(a, 7 + ((s >> 3) % 6))  # coprimo con a -> entramado denso
    amp_b = 0.30 + ((s >> 6) % 4) * 0.06
    radio = alto * 0.80                     # desborda a propósito, se recorta

    capas = []
    for color, giro, opacidad in [
        (color_secundario, 0, 0.16),
        (color_acento, 360 / (a * 3), 0.13),
        (color_secundario, 360 / (a * 1.6), 0.10),
    ]:
        path = _guilloche(a, b, 1 - amp_b, amp_b, radio, fase=giro)
        capas.append(
            f'<g transform="rotate({giro:.1f})">'
            f'<path d="{path}" fill="none" stroke="{color}" '
            f'stroke-width="0.6" opacity="{opacidad}"/></g>'
        )

    return (
        f'<svg viewBox="{-ancho/2} {-alto/2} {ancho} {alto}" '
        f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice" '
        f'aria-hidden="true">{"".join(capas)}</svg>'
    )
