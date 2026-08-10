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


def _tono(color_hex: str, factor: float) -> str:
    """Variación SUTIL de tonalidad: factor>0 aclara (mezcla con blanco),
    factor<0 oscurece (escala hacia negro). Pensado para +-0.15 como máximo."""
    h = (color_hex or "#000000").lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if factor >= 0:
        r, g, b = (r + (255 - r) * factor, g + (255 - g) * factor, b + (255 - b) * factor)
    else:
        r, g, b = (r * (1 + factor), g * (1 + factor), b * (1 + factor))
    return f"#{round(max(0, min(255, r))):02x}{round(max(0, min(255, g))):02x}{round(max(0, min(255, b))):02x}"


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
    determinístico por sindicato. Pensado como fondo detrás de la credencial.

    Son 3 rosetones (no 1), cada uno con su propio centro (desplazado del de
    los otros) y su propio tono (variación leve sobre secundario/acento) —
    estética de "capas" como en las filigranas de billetes/títulos reales,
    donde se nota que hay más de un patrón superpuesto. Todo sale de la MISMA
    semilla por sindicato: determinístico, sin estado ni dependencias.
    """
    s = _semilla(nombre_sindicato)
    a = 3 + (s % 4)                         # 3..6  pétalos base, compartido por los 3 rosetones
    b = _coprimo_de(a, 7 + ((s >> 3) % 6))  # coprimo con a -> entramado denso
    amp_b = 0.30 + ((s >> 6) % 4) * 0.06
    radio = min(ancho, alto) * 0.62         # más chico que antes: ahora son 3, no 1 solo

    colores_base = [color_secundario, color_acento, color_secundario]
    capas = []
    for i, color_base in enumerate(colores_base):
        h = (s >> (i * 13)) & 0xFFFFFFFF    # porción distinta de la semilla por capa
        angulo = h % 360
        distancia = (0.10 + (h >> 8) % 5 * 0.045) * min(ancho, alto)
        dx = distancia * cos(angulo * pi / 180)
        dy = distancia * sin(angulo * pi / 180)
        giro = (h >> 16) % 360
        tono = ((h >> 24) % 7 - 3) * 0.05   # -0.15..+0.15, leve
        color = _tono(color_base, tono)
        opacidad = 0.15 - i * 0.02
        path = _guilloche(a, b, 1 - amp_b, amp_b, radio, fase=giro)
        capas.append(
            f'<g transform="translate({dx:.1f},{dy:.1f}) rotate({giro})">'
            f'<path d="{path}" fill="none" stroke="{color}" '
            f'stroke-width="0.6" opacity="{opacidad:.2f}"/></g>'
        )

    return (
        f'<svg viewBox="{-ancho/2} {-alto/2} {ancho} {alto}" '
        f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice" '
        f'aria-hidden="true">{"".join(capas)}</svg>'
    )
