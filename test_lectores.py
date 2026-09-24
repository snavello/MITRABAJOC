"""Tests de lectores.py (PLAN_ENMASCARADO.md, bloque 2).

El PDF digital y la foto derecha se prueban en cualquier lado. La lectura
de fotos con Tesseract solo donde está (Linux: Render, o Docker en una PC
con Windows); los casos en que NO se lee -- sin OCR, cupo lleno, tiempo
agotado, error -- se prueban con un motor simulado, porque son los que
sostienen la regla de mejor esfuerzo: nunca esperan ni levantan excepción.
"""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

import enmascarado as E
import lectores

DATOS = Path(__file__).parent / "datos_prueba" / "enmascarado"
PDF = DATOS / "recibo_digital_ficticio.pdf"


# ======================= PDF digital =======================


def test_pdf_digital_trae_las_palabras_y_sus_cajas():
    paginas = lectores.palabras_pdf(PDF.read_bytes())
    assert len(paginas) == 2
    textos = [p.texto for p in paginas[0]]
    # El CUIL sale como UNA palabra (antes el guion lo partía en tres).
    assert "27-28765431-1" in textos and "30-71234567-1" in textos
    assert all(p.pagina == 1 for p in paginas[1])
    img = lectores.imagenes_pdf(PDF.read_bytes())[0]
    assert all(0 <= p.x0 < p.x1 <= img.width and 0 <= p.y0 < p.y1 <= img.height for p in paginas[0])


def test_pdf_digital_coincide_con_los_datos_de_prueba():
    """Las palabras de los datos de prueba son las que da este lector hoy."""
    d = json.loads((DATOS / "palabras_digital.json").read_text(encoding="utf-8"))
    leidas = [p.texto for pag in lectores.palabras_pdf(PDF.read_bytes()) for p in pag]
    assert leidas == [x[0] for x in d["palabras"]]


def test_pdf_escaneado_no_trae_texto():
    """Un PDF que es solo una imagen devuelve páginas vacías: lo lee el OCR."""
    buf = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(buf, format="PDF")
    assert lectores.palabras_pdf(buf.getvalue()) == [[]]


# ======================= Foto derecha =======================


def test_abrir_imagen_endereza_por_exif():
    """Un teléfono guarda la rotación en el EXIF; la imagen tapada se vuelve a
    codificar sin ese dato, así que hay que enderezarla antes."""
    img = Image.new("RGB", (300, 100), "white")
    exif = Image.Exif()
    exif[0x0112] = 6   # "rotar 90° a la derecha para ver"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    assert lectores.abrir_imagen(buf.getvalue()).size == (100, 300)


# ======================= Foto: mejor esfuerzo =======================


class MotorFalso:
    def __init__(self, reconoce=True, revienta=False):
        self.reconoce, self.revienta, self.limpiado = reconoce, revienta, False

    def SetImage(self, img):
        if self.revienta:
            raise RuntimeError("Tesseract se cayó")

    def Recognize(self, ms):
        return self.reconoce

    def GetIterator(self):
        return None

    def Clear(self):
        self.limpiado = True


@pytest.fixture
def ocr_simulado(monkeypatch):
    """Tesseract 'disponible' con motores falsos y un pool vacío."""
    import queue
    monkeypatch.setattr(lectores, "_disponible", True)
    monkeypatch.setattr(lectores, "_motores", queue.Queue())
    monkeypatch.setattr(lectores, "_creados", 0)
    return monkeypatch


def test_sin_ocr_no_lee_y_no_falla(monkeypatch):
    monkeypatch.setattr(lectores, "_disponible", False)
    assert lectores.leer_foto(Image.new("RGB", (50, 50))).motivo == "sin_ocr"


def test_cupo_lleno_no_espera(ocr_simulado):
    """Con el cupo tomado, la foto siguiente NO hace fila: vuelve enseguida
    con "sin_lugar" y el recibo sale sin tapar."""
    ocr_simulado.setattr(lectores, "CUPO", 1)
    ocr_simulado.setattr(lectores, "_crear_motor", lambda: MotorFalso())
    tomado = lectores._tomar_motor()            # una lectura en curso
    assert tomado is not None
    assert lectores.leer_foto(Image.new("RGB", (50, 50))).motivo == "sin_lugar"


def test_tiempo_agotado(ocr_simulado):
    motor = MotorFalso(reconoce=False)
    ocr_simulado.setattr(lectores, "_crear_motor", lambda: motor)
    assert lectores.leer_foto(Image.new("RGB", (50, 50))).motivo == "tiempo"
    assert motor.limpiado and lectores._motores.qsize() == 1   # el motor vuelve al pool


def test_error_de_tesseract_no_levanta_y_devuelve_el_motor(ocr_simulado):
    motor = MotorFalso(revienta=True)
    ocr_simulado.setattr(lectores, "_crear_motor", lambda: motor)
    assert lectores.leer_foto(Image.new("RGB", (50, 50))).motivo == "error"
    assert lectores._motores.qsize() == 1


def test_no_poder_crear_el_motor_no_levanta(ocr_simulado):
    def rompe():
        raise OSError("falta el idioma")
    ocr_simulado.setattr(lectores, "_crear_motor", rompe)
    assert lectores.leer_foto(Image.new("RGB", (50, 50))).motivo == "error"
    assert lectores._creados == 0    # no quedó un lugar del cupo perdido


# ======================= Foto: Tesseract de verdad =======================

con_ocr = pytest.mark.skipif(not lectores.ocr_disponible(),
                             reason="Tesseract no está (Windows): correr en Linux o Docker")


@con_ocr
def test_tesseract_lee_el_recibo_y_se_tapa_la_identidad():
    """La página del recibo digital, como IMAGEN (una foto perfecta): el OCR
    la lee y el enmascarado tapa lo mismo que con el texto del PDF."""
    img = lectores.imagenes_pdf(PDF.read_bytes())[0]
    lectura = lectores.leer_foto(img)
    assert lectura.motivo == "ok"
    con = E.Conocidos("27287654311", "GONZÁLEZ PEÑA, MARÍA JOSÉ", ("DISTRIBUIDORA LOS ANDES S.R.L.",))
    an = E.analizar(lectura.palabras, con)
    assert an.cuiles == ["27287654311"] and an.cuits == ["30712345671"]
    assert E.control_de_fuga(lectura.palabras, an.cajas, con) == []


@con_ocr
def test_tesseract_foto_grande_devuelve_cajas_en_pixeles_originales():
    img = lectores.imagenes_pdf(PDF.read_bytes(), escala=400 / 72)[0]   # ~3300 px de alto
    assert max(img.size) > lectores.LADO_MAXIMO_OCR
    lectura = lectores.leer_foto(img)
    assert lectura.motivo == "ok"
    assert max(p.y1 for p in lectura.palabras) > lectores.LADO_MAXIMO_OCR * 0.6
