"""Lectores de "palabras con posición" para `enmascarado.py`.

Dos caminos, según el archivo:

- **PDF digital**: el propio PDF trae cada carácter con su caja. No hace falta
  OCR: es exacto y cuesta milisegundos. `pypdfium2` (Apache/BSD) y no
  PyMuPDF, que es AGPL.
- **Foto, escaneo o PDF que es solo una imagen**: Tesseract, vía `tesserocr`,
  cuya rueda de Linux trae la librería adentro -- se instala con pip en el
  Render nativo, sin Docker. ~0,7 s de CPU por página y ~20 MB de modelo por
  proceso (medición en HISTORIAL.md, "el OCR de las fotos es Tesseract").

**Mejor esfuerzo** (CLAUDE.md, decisión del 2026-09-24): leer para tapar
nunca estorba al análisis del recibo. Por eso `leer_foto()` no espera ni
levanta excepciones: si no hay OCR (Windows, donde tesserocr no tiene
rueda), si el cupo está lleno o si Tesseract se pasa de su tiempo máximo,
devuelve el MOTIVO y quien llama manda el recibo sin tapar y lo registra.

Variables de entorno:
- `ENMASCARADO_CUPO` (2): lecturas de fotos simultáneas por proceso. La que
  no entra NO espera turno.
- `ENMASCARADO_OCR_MS` (4000): tiempo máximo de Tesseract por página.
"""
from __future__ import annotations

import io
import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

# Un hilo por lectura: el OCR no le saca el procesador al resto de los
# pedidos. Tiene que estar ANTES de cargar Tesseract (lo lee OpenMP al iniciar).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from enmascarado import Palabra  # noqa: E402

# 150 dpi, lo mismo que usa hoy extractor._imagen_desde_pdf.
DPI = 150
ESCALA = DPI / 72
# Una foto de teléfono (4000 px) se lee achicada: el tiempo de Tesseract
# crece con los píxeles y a este tamaño la letra de un recibo se lee bien.
# Las cajas se devuelven en píxeles de la imagen ORIGINAL.
LADO_MAXIMO_OCR = 2000
TESSDATA = Path(__file__).resolve().parent / "data" / "tessdata"


def _entero(nombre: str, defecto: int) -> int:
    try:
        return max(1, int(os.getenv(nombre, "").strip() or defecto))
    except ValueError:
        return defecto


CUPO = _entero("ENMASCARADO_CUPO", 2)
OCR_MS = _entero("ENMASCARADO_OCR_MS", 4000)


# ======================= PDF digital =======================


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


def abrir_imagen(contenido: bytes):
    """La foto como imagen PIL, DERECHA: un teléfono guarda la rotación en
    el EXIF, y al volver a codificar la imagen tapada ese dato se pierde --
    la IA recibiría la foto acostada."""
    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(io.BytesIO(contenido))).convert("RGB")


# ======================= Foto (Tesseract) =======================


@dataclass
class LecturaFoto:
    """Resultado de leer una foto. `motivo` es "ok" o por qué no se leyó:
    "sin_ocr" (Tesseract no está), "sin_lugar" (cupo lleno), "tiempo" (se
    pasó de OCR_MS) o "error". Solo con "ok" hay palabras."""
    motivo: str
    palabras: list[Palabra] = field(default_factory=list)


_motores: "queue.Queue" = queue.Queue()
_creados = 0
_candado = threading.Lock()
_disponible: bool | None = None


def ocr_disponible() -> bool:
    """¿Se puede leer fotos en este proceso? En Windows no hay rueda de
    tesserocr, y sin el archivo del idioma tampoco: se tapa solo lo que sale
    del PDF digital."""
    global _disponible
    if _disponible is None:
        try:
            import tesserocr  # noqa: F401
            _disponible = (TESSDATA / "spa.traineddata").is_file()
        except ImportError:
            _disponible = False
    return _disponible


def _crear_motor():
    from tesserocr import OEM, PSM, PyTessBaseAPI

    api = PyTessBaseAPI(path=str(TESSDATA), lang="spa", psm=PSM.AUTO, oem=OEM.LSTM_ONLY)
    # Sin buscar texto invertido (blanco sobre negro): un recibo no lo tiene.
    api.SetVariable("tessedit_do_invert", "0")
    return api


def _tomar_motor():
    """Un motor libre, o None si ya hay CUPO lecturas en curso. No espera."""
    global _creados
    try:
        return _motores.get_nowait()
    except queue.Empty:
        pass
    with _candado:
        if _creados >= CUPO:
            return None
        _creados += 1
    try:
        return _crear_motor()
    except Exception:
        with _candado:
            _creados -= 1
        raise


def precargar():
    """Carga un motor al arrancar la app, para que la primera foto del día
    no pague la carga del modelo. Si no hay OCR, no hace nada."""
    if ocr_disponible():
        try:
            m = _tomar_motor()
            if m is not None:
                _motores.put(m)
        except Exception:
            pass


def leer_foto(imagen, ocr_ms: int | None = None) -> LecturaFoto:
    """Palabras de una imagen PIL, en sus píxeles. Nunca espera un lugar ni
    levanta excepciones: ver `LecturaFoto.motivo`."""
    if not ocr_disponible():
        return LecturaFoto("sin_ocr")
    try:
        motor = _tomar_motor()
    except Exception:
        return LecturaFoto("error")
    if motor is None:
        return LecturaFoto("sin_lugar")
    try:
        f = min(1.0, LADO_MAXIMO_OCR / max(imagen.size))
        chica = imagen if f == 1.0 else imagen.resize(
            (round(imagen.width * f), round(imagen.height * f)))
        motor.SetImage(chica)
        if not motor.Recognize(ocr_ms or OCR_MS):
            return LecturaFoto("tiempo")
        from tesserocr import RIL, iterate_level

        palabras = []
        for w in iterate_level(motor.GetIterator(), RIL.WORD):
            texto = (w.GetUTF8Text(RIL.WORD) or "").strip()
            caja = w.BoundingBox(RIL.WORD)
            if texto and caja:
                x0, y0, x1, y1 = caja
                palabras.append(Palabra(texto, x0 / f, y0 / f, x1 / f, y1 / f, 0))
        return LecturaFoto("ok", palabras)
    except Exception:
        return LecturaFoto("error")
    finally:
        try:
            motor.Clear()
        except Exception:
            pass
        _motores.put(motor)
