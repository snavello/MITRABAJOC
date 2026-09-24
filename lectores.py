"""Lectores de "palabras con posición" para `enmascarado.py`.

Por ahora solo el PDF digital: el propio PDF trae cada carácter con su caja,
así que no hace falta OCR -- es exacto y cuesta milisegundos. El lector de
fotos (OCR) se suma en el bloque 2 de PLAN_ENMASCARADO.md, con su medición de
tiempo y memoria.

`pypdfium2` (Apache/BSD) y no PyMuPDF, que es AGPL.
"""
from __future__ import annotations

from enmascarado import Palabra

# 150 dpi, lo mismo que usa hoy extractor._imagen_desde_pdf.
DPI = 150
ESCALA = DPI / 72


def palabras_pdf(contenido: bytes, escala: float = ESCALA) -> list[list[Palabra]]:
    """Una lista de palabras por página, en píxeles de la imagen que sale de
    renderizar esa página a `escala` (origen arriba a la izquierda). Una
    página sin texto (un escaneo metido en un PDF) devuelve lista vacía: la
    tiene que leer el OCR."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(contenido)
    try:
        return [_palabras_pagina(pdf[i], i, escala) for i in range(len(pdf))]
    finally:
        pdf.close()


def _palabras_pagina(pagina, n: int, escala: float) -> list[Palabra]:
    alto_pag = pagina.get_height()
    tp = pagina.get_textpage()
    palabras: list[Palabra] = []
    actual: list[tuple[str, tuple]] = []

    def cerrar():
        if actual:
            texto = "".join(c for c, _ in actual)
            x0 = min(b[0] for _, b in actual)
            x1 = max(b[2] for _, b in actual)
            y_abajo = min(b[1] for _, b in actual)
            y_arriba = max(b[3] for _, b in actual)
            palabras.append(Palabra(texto, x0 * escala, (alto_pag - y_arriba) * escala,
                                    x1 * escala, (alto_pag - y_abajo) * escala, n))
            actual.clear()

    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        if not ch or ch.isspace():
            cerrar()
            continue
        # (izquierda, abajo, derecha, arriba) en puntos. `loose`: la caja de la
        # LÍNEA de la fuente, no la del trazo -- la de un guion o un punto mide
        # un punto de alto, y con ella cualquier espacio partía "30-71234567-1".
        caja = tp.get_charbox(i, loose=True)
        if actual:
            _, prev = actual[-1]
            alto = max(1.0, max(b[3] - b[1] for _, b in actual))
            # Otra línea, o un hueco grande en la misma línea: palabra nueva.
            if abs(caja[1] - prev[1]) > 0.5 * alto or caja[0] - prev[2] > 0.25 * alto:
                cerrar()
        actual.append((ch, caja))
    cerrar()
    tp.close()
    return palabras


def imagenes_pdf(contenido: bytes, escala: float = ESCALA) -> list:
    """Cada página como imagen PIL, a la misma escala que `palabras_pdf`."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(contenido)
    try:
        return [pdf[i].render(scale=escala).to_pil().convert("RGB") for i in range(len(pdf))]
    finally:
        pdf.close()
