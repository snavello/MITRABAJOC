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
nunca estorba al análisis del recibo. Por eso `leer_foto()` no levanta
excepciones y tiene un PRESUPUESTO de tiempo: si no hay OCR (Windows, donde
tesserocr no tiene rueda), si no se libera un lector a tiempo o si Tesseract
se come el resto del presupuesto, devuelve el MOTIVO y quien llama manda el
recibo sin tapar y lo registra.

Variables de entorno:
- `ENMASCARADO_CUPO` (1): lecturas de fotos simultáneas por proceso. UNA,
  porque en Render hay un proceso por núcleo: dos lecturas en el mismo núcleo
  no leen más, se estorban. Medido con 4 núcleos y 4 procesos: una ráfaga de
  10 fotos tapó 10 con 1 lector y 8 con 2; una de 20, 12 contra 2.
- `ENMASCARADO_PRESUPUESTO_MS` (5000): lo máximo que una foto le puede sumar
  a la espera, contando la fila y la lectura (tope de SDN, 2026-09-24).
- `ENMASCARADO_ESPERA_MS` (3000): de ese presupuesto, lo máximo que se espera
  a que se libere un lector. Lo que sobra es para leer (nunca menos de 1 s).
  Sin esta fila, una ráfaga de 10 fotos dejaba 8 sin tapar.
"""
from __future__ import annotations

import io
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import imagenes

# Un hilo por lectura: el OCR no le saca el procesador al resto de los
# pedidos. Tiene que estar ANTES de cargar Tesseract (lo lee OpenMP al iniciar).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from enmascarado import Palabra  # noqa: E402

# Tesseract se importa ACÁ, una vez, cuando main carga este módulo al
# arrancar -- en el hilo principal. En Linux, la primera importación de
# tesserocr desde un hilo secundario (las rutas sincrónicas de FastAPI corren
# en un pool de hilos) revienta con "signal only works in main thread": así se
# cayó /plataforma en el CI. En Windows no hay rueda y queda en None.
try:
    import tesserocr as _tesserocr  # noqa: E402
except Exception:
    _tesserocr = None

# 150 dpi, lo mismo que usa hoy extractor._imagen_desde_pdf.
DPI = 150
ESCALA = DPI / 72
# Una foto de teléfono (4000 px) se achica UNA vez, al abrirla (`abrir_imagen`),
# a este lado: el tiempo de Tesseract crece con los píxeles y a este tamaño la
# letra de un recibo se lee bien, la IA no necesita más (achica sola lo que pasa
# de ~1.568 px) y el tapado y lo que viaja usan esa MISMA imagen, así que las
# cajas del OCR caen exactamente sobre lo que se tapa. Una página de PDF más
# grande que esto también se renderiza achicada (`_escala_de`).
LADO_MAXIMO_OCR = imagenes.LADO_MAXIMO_LECTURA


class ImagenDemasiadoGrande(ValueError):
    """La imagen mide más píxeles de los que se pueden abrir sin poner en
    riesgo el servidor. `mensaje` es para mostrar; se mira en la cabecera,
    ANTES de decodificar."""


def exigir_tamano_razonable(contenido: bytes, content_type: str = "") -> None:
    """Levanta ImagenDemasiadoGrande si la imagen pasa del tope de píxeles de
    entrada. Lee solo la cabecera (Pillow no decodifica hasta pedírselo): una
    imagen absurda se rechaza en milisegundos y sin memoria. Un archivo que no
    es una imagen (PDF, basura) no es asunto de acá: lo resuelve quien lo abre."""
    if not (content_type or "image/").startswith("image/"):
        return
    from PIL import Image
    try:
        with Image.open(io.BytesIO(contenido)) as img:
            ancho, alto, formato = img.width, img.height, img.format
    except Exception:
        return
    tope = (imagenes.PIXELES_MAXIMOS_LECTURA_JPEG if formato == "JPEG"
            else imagenes.PIXELES_MAXIMOS_LECTURA)
    if ancho * alto > tope:
        raise ImagenDemasiadoGrande(f"mide {ancho}x{alto} px")
TESSDATA = Path(__file__).resolve().parent / "data" / "tessdata"


def _entero(nombre: str, defecto: int) -> int:
    try:
        return max(1, int(os.getenv(nombre, "").strip() or defecto))
    except ValueError:
        return defecto


CUPO = _entero("ENMASCARADO_CUPO", 1)
PRESUPUESTO_MS = _entero("ENMASCARADO_PRESUPUESTO_MS", 5000)
ESPERA_MS = min(_entero("ENMASCARADO_ESPERA_MS", 3000), PRESUPUESTO_MS - 1000)
LECTURA_MINIMA_MS = 1000


# ======================= PDF digital =======================

# PDFium no admite uso simultáneo desde varios hilos (lo dice pypdfium2), y
# las rutas de lectura corren el enmascarado en el threadpool: dos PDF que
# llegaban juntos al mismo worker lo mataban con "double free or corruption"
# o lo dejaban colgado (encontrado el 2026-11-02 con el lote bancario,
# PLAN_PRUEBAS_BANCARIA.md §7). TODO uso de pypdfium2 -- abrir, leer, dibujar
# y cerrar -- va adentro de este candado, y lo que se crea (página, texto,
# bitmap) se CIERRA adentro: si lo cerrara el recolector de basura, el
# destructor de C correría en cualquier hilo y fuera del candado.
# Reentrante porque `_palabras_pagina` corre adentro de `palabras_pdf`.
# Cuesta poco: un recibo digital se lee y se dibuja en ~30-50 ms.
_candado_pdf = threading.RLock()


def _escala_de(pagina, escala: float | None) -> float:
    """La escala con la que se dibuja una página: 150 dpi, salvo que la página
    sea tan grande que pase de `LADO_MAXIMO_OCR` px de lado (un plano A3 a 150
    dpi son 2.480 px). `palabras_pdf` y `_render` la calculan igual, así las
    cajas siguen cayendo sobre la imagen. Con `escala` explícita se respeta."""
    if escala is not None:
        return escala
    ancho, alto = pagina.get_size()
    return min(ESCALA, LADO_MAXIMO_OCR / max(ancho, alto, 1.0))


def palabras_pdf(contenido: bytes, escala: float | None = None) -> list[list[Palabra]]:
    """Una lista de palabras por página, en píxeles de la imagen que sale de
    renderizar esa página (150 dpi con tope de lado, ver `_escala_de`; origen
    arriba a la izquierda). Una página sin texto (un escaneo metido en un PDF)
    devuelve lista vacía: la tiene que leer el OCR."""
    import pypdfium2 as pdfium

    with _candado_pdf:
        pdf = pdfium.PdfDocument(contenido)
        try:
            salida = []
            for i in range(len(pdf)):
                pagina = pdf[i]
                try:
                    salida.append(_palabras_pagina(pagina, i, _escala_de(pagina, escala)))
                finally:
                    pagina.close()
            return salida
        finally:
            pdf.close()


def _palabras_pagina(pagina, n: int, escala: float) -> list[Palabra]:
    alto_pag = pagina.get_height()
    tp = pagina.get_textpage()
    try:
        return _palabras_de_textos(tp, alto_pag, n, escala)
    finally:
        tp.close()


def _palabras_de_textos(tp, alto_pag: float, n: int, escala: float) -> list[Palabra]:
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
    return palabras


def imagenes_pdf(contenido: bytes, escala: float | None = None) -> list:
    """Cada página como imagen PIL, a la misma escala que `palabras_pdf`."""
    import pypdfium2 as pdfium

    with _candado_pdf:
        pdf = pdfium.PdfDocument(contenido)
        try:
            return [_render(pdf, i, escala) for i in range(len(pdf))]
        finally:
            pdf.close()


def imagen_pdf(contenido: bytes, pagina: int = 0, escala: float | None = None):
    """Una sola página como imagen PIL (la IA hoy recibe solo la primera)."""
    import pypdfium2 as pdfium

    with _candado_pdf:
        pdf = pdfium.PdfDocument(contenido)
        try:
            return _render(pdf, pagina, escala)
        finally:
            pdf.close()


def _render(pdf, n: int, escala: float):
    """La página `n` como imagen PIL propia (`convert` copia los píxeles: no
    queda nada apuntando a la memoria de PDFium). Se llama con el candado
    tomado y cierra el bitmap y la página antes de devolver."""
    pagina = pdf[n]
    try:
        bitmap = pagina.render(scale=_escala_de(pagina, escala))
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
    finally:
        pagina.close()


def abrir_imagen(contenido: bytes):
    """La foto como imagen PIL, DERECHA y ACHICADA a `LADO_MAXIMO_OCR` de lado
    mayor: un teléfono guarda la rotación en el EXIF, y al volver a codificar la
    imagen tapada ese dato se pierde -- la IA recibiría la foto acostada.

    Es la ÚNICA decodificación de la foto en todo el camino de lectura, y está
    hecha para gastar poca memoria: una foto de 12 MP son 36 MB por copia, y
    abrirla entera, transponerla y convertirla dejaba tres copias vivas
    (~110 MB) en un servicio de 512 MB que ya estaba en 356 (OOM de Pruebas,
    2026-11-06). Un JPEG se decodifica YA reducido (`draft`: la librería salta
    bloques al decodificar, sin pasar por el tamaño completo), y la rotación se
    hace sobre la imagen chica y en el lugar. Levanta ImagenDemasiadoGrande si
    la cabecera dice que pasa del tope de píxeles."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(contenido))
    tope = (imagenes.PIXELES_MAXIMOS_LECTURA_JPEG if img.format == "JPEG"
            else imagenes.PIXELES_MAXIMOS_LECTURA)
    if img.width * img.height > tope:
        raise ImagenDemasiadoGrande(f"mide {img.width}x{img.height} px")
    if max(img.size) > LADO_MAXIMO_OCR:
        if img.format == "JPEG":
            # El tamaño EXACTO que se quiere (no el cuadrado de `thumbnail`, que
            # pide el doble y por eso en una foto de 4000 px no reducía nada):
            # libjpeg elige la escala 1/2, 1/4 o 1/8 más grande que lo cubra.
            f = LADO_MAXIMO_OCR / max(img.size)
            img.draft("RGB", (max(1, round(img.width * f)), max(1, round(img.height * f))))
        if max(img.size) > LADO_MAXIMO_OCR:
            img.thumbnail((LADO_MAXIMO_OCR, LADO_MAXIMO_OCR))
    ImageOps.exif_transpose(img, in_place=True)
    return img if img.mode == "RGB" else img.convert("RGB")


# ======================= Foto (Tesseract) =======================


@dataclass
class LecturaFoto:
    """Resultado de leer una foto. `motivo` es "ok" o por qué no se leyó:
    "sin_ocr" (Tesseract no está), "sin_lugar" (no se liberó un lector
    dentro de ESPERA_MS), "tiempo" (la lectura se comió el presupuesto) o
    "error". Solo con "ok" hay palabras. `espera_ms` y `lectura_ms` son lo
    que costó cada parte: van al registro del modo sombra."""
    motivo: str
    palabras: list[Palabra] = field(default_factory=list)
    espera_ms: int = 0
    lectura_ms: int = 0


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
        _disponible = _tesserocr is not None and (TESSDATA / "spa.traineddata").is_file()
    return _disponible


def _crear_motor():
    t = _tesserocr
    api = t.PyTessBaseAPI(path=str(TESSDATA), lang="spa", psm=t.PSM.AUTO, oem=t.OEM.LSTM_ONLY)
    # Sin buscar texto invertido (blanco sobre negro): un recibo no lo tiene.
    api.SetVariable("tessedit_do_invert", "0")
    return api


def _tomar_motor(espera_s: float = 0.0):
    """Un motor libre. Si ya hay CUPO lecturas en curso, espera a que se
    libere uno hasta `espera_s` segundos; si no se libera, None."""
    global _creados
    try:
        return _motores.get_nowait()
    except queue.Empty:
        pass
    with _candado:
        if _creados >= CUPO:
            lleno = True
        else:
            lleno = False
            _creados += 1
    if lleno:
        try:
            return _motores.get(timeout=espera_s) if espera_s > 0 else None
        except queue.Empty:
            return None
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


def leer_foto(imagen, presupuesto_ms: int | None = None) -> LecturaFoto:
    """Palabras de una imagen PIL, en sus píxeles. Nunca levanta excepciones
    ni se pasa del presupuesto (PRESUPUESTO_MS, o el que se pase): ver
    `LecturaFoto.motivo`."""
    if not ocr_disponible():
        return LecturaFoto("sin_ocr")
    presupuesto = presupuesto_ms or PRESUPUESTO_MS
    inicio = time.perf_counter()
    try:
        motor = _tomar_motor(min(ESPERA_MS, presupuesto - LECTURA_MINIMA_MS) / 1000)
    except Exception:
        return LecturaFoto("error")
    espera = int((time.perf_counter() - inicio) * 1000)
    if motor is None:
        return LecturaFoto("sin_lugar", espera_ms=espera)
    try:
        f = min(1.0, LADO_MAXIMO_OCR / max(imagen.size))
        chica = imagen if f == 1.0 else imagen.resize(
            (round(imagen.width * f), round(imagen.height * f)))
        motor.SetImage(chica)
        # Lo que quedó del presupuesto después de la fila, y nunca menos del mínimo.
        ok = motor.Recognize(max(LECTURA_MINIMA_MS, presupuesto - espera))
        lectura = int((time.perf_counter() - inicio) * 1000) - espera
        if not ok:
            return LecturaFoto("tiempo", espera_ms=espera, lectura_ms=lectura)
        RIL, iterate_level = _tesserocr.RIL, _tesserocr.iterate_level
        palabras = []
        for w in iterate_level(motor.GetIterator(), RIL.WORD):
            texto = (w.GetUTF8Text(RIL.WORD) or "").strip()
            caja = w.BoundingBox(RIL.WORD)
            if texto and caja:
                x0, y0, x1, y1 = caja
                palabras.append(Palabra(texto, x0 / f, y0 / f, x1 / f, y1 / f, 0))
        return LecturaFoto("ok", palabras, espera, lectura)
    except Exception:
        return LecturaFoto("error", espera_ms=espera)
    finally:
        try:
            motor.Clear()
        except Exception:
            pass
        _motores.put(motor)
