"""Tests de lectores.py (PLAN_ENMASCARADO.md, bloque 2).

El PDF digital y la foto derecha se prueban en cualquier lado. La lectura
de fotos con Tesseract solo donde está (Linux: Render, o Docker en una PC
con Windows); los casos en que NO se lee -- sin OCR, cupo lleno, tiempo
agotado, error -- se prueban con un motor simulado, porque son los que
sostienen la regla de mejor esfuerzo: nunca esperan ni levantan excepción.
"""
import io
import json
import threading
import time
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


# ======================= PDF desde varios hilos =======================

# El guion corre en un proceso APARTE: sin el candado, PDFium muere con
# "double free or corruption" o se cuelga, y eso adentro de pytest se llevaría
# la suite entera en vez de fallar este test.
_GUION_HILOS = r"""
import hashlib, sys, threading
sys.path.insert(0, sys.argv[1])
import lectores

archivos = [open(f, "rb").read() for f in sys.argv[2:]]

def huella(c):
    pal = [(p.texto, round(p.x0, 3), round(p.y0, 3), round(p.x1, 3), round(p.y1, 3), p.pagina)
           for pag in lectores.palabras_pdf(c) for p in pag]
    h = hashlib.sha256(repr(pal).encode())
    for img in [lectores.imagen_pdf(c)] + lectores.imagenes_pdf(c):
        h.update(repr(img.size).encode())
        h.update(img.tobytes())
    return h.hexdigest()

de_a_uno = [huella(c) for c in archivos]
resultados, errores = {}, []

def trabajar(h):
    try:
        for vuelta in range(2):
            for i, c in enumerate(archivos):
                resultados[(h, vuelta, i)] = huella(c)
    except Exception as e:
        errores.append(repr(e))

hilos = [threading.Thread(target=trabajar, args=(h,)) for h in range(8)]
[t.start() for t in hilos]
[t.join() for t in hilos]
assert not errores, errores
assert len(resultados) == 8 * 2 * len(archivos)
distintos = [k for k, v in resultados.items() if v != de_a_uno[k[2]]]
assert not distintos, distintos
print("OK", len(resultados))
"""


def test_pdf_desde_varios_hilos_no_rompe_pdfium_y_lee_lo_mismo():
    """/api/leer y /api/aportes preparan el archivo en el pool de hilos de
    FastAPI: dos PDF juntos en el mismo worker entran a PDFium a la vez, y
    PDFium no es thread-safe (2026-11-02: el proceso moría con "double free or
    corruption" o se colgaba). Ocho hilos leyendo los recibos de prueba tienen
    que terminar y dar exactamente lo mismo que de a uno."""
    import subprocess
    import sys
    raiz = Path(__file__).parent
    pdfs = sorted((raiz / "docs" / "recibos-bancaria-prueba").glob("*.pdf")) + [PDF]
    assert len(pdfs) >= 5
    r = subprocess.run([sys.executable, "-c", _GUION_HILOS, str(raiz), *map(str, pdfs)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.startswith("OK"), (r.returncode, r.stdout, r.stderr[-2000:])


def test_pypdfium2_solo_se_usa_en_lectores():
    """El candado vive en lectores.py: un módulo de la app que importara
    pypdfium2 por su cuenta volvería a abrir la puerta a la caída."""
    import ast
    raiz = Path(__file__).parent
    afuera = []
    for py in raiz.glob("*.py"):
        if py.name == "lectores.py" or py.name.startswith("test_"):
            continue
        for nodo in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            nombres = ([a.name for a in nodo.names] if isinstance(nodo, ast.Import)
                       else [nodo.module or ""] if isinstance(nodo, ast.ImportFrom) else [])
            if any(n.split(".")[0] == "pypdfium2" for n in nombres):
                afuera.append(py.name)
    assert afuera == [], f"usan pypdfium2 sin pasar por el candado de lectores.py: {afuera}"


def test_todo_uso_de_pdfium_en_lectores_va_con_el_candado():
    """Las tres funciones públicas que abren un PDF lo hacen adentro de
    `with _candado_pdf`."""
    import ast
    arbol = ast.parse((Path(__file__).parent / "lectores.py").read_text(encoding="utf-8"))
    for fn in (n for n in arbol.body if isinstance(n, ast.FunctionDef)):
        abre = any(isinstance(n, ast.Attribute) and n.attr == "PdfDocument" for n in ast.walk(fn))
        if not abre:
            continue
        candados = [w for w in ast.walk(fn) if isinstance(w, ast.With)
                    and any(isinstance(i.context_expr, ast.Name) and i.context_expr.id == "_candado_pdf"
                            for i in w.items)]
        assert candados, f"{fn.name} abre un PDF sin el candado"
        assert any(isinstance(n, ast.Attribute) and n.attr == "PdfDocument"
                   for w in candados for n in ast.walk(w)), f"{fn.name} abre el PDF fuera del candado"


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


def test_preguntar_si_hay_ocr_desde_otro_hilo_no_revienta(monkeypatch):
    """Las rutas sincrónicas corren en un pool de hilos. En Linux, importar
    tesserocr por primera vez desde uno revienta ("signal only works in main
    thread"): así se cayó /plataforma en el CI. Tesseract se importa al cargar
    el módulo; preguntar desde un hilo no importa nada."""
    monkeypatch.setattr(lectores, "_disponible", None)
    resultado, errores = [], []

    def preguntar():
        try:
            resultado.append(lectores.ocr_disponible())
        except Exception as e:
            errores.append(e)
    h = threading.Thread(target=preguntar)
    h.start(); h.join()
    assert errores == [] and resultado == [lectores._tesserocr is not None]


def test_sin_ocr_no_lee_y_no_falla(monkeypatch):
    monkeypatch.setattr(lectores, "_disponible", False)
    assert lectores.leer_foto(Image.new("RGB", (50, 50))).motivo == "sin_ocr"


def test_cupo_lleno_espera_hasta_su_tope_y_sale_sin_lugar(ocr_simulado):
    """Con el cupo tomado y nadie que lo libere, la foto espera a lo sumo
    ESPERA_MS y vuelve con "sin_lugar": el recibo sale sin tapar."""
    ocr_simulado.setattr(lectores, "CUPO", 1)
    ocr_simulado.setattr(lectores, "ESPERA_MS", 200)
    ocr_simulado.setattr(lectores, "_crear_motor", lambda: MotorFalso())
    assert lectores._tomar_motor() is not None            # una lectura en curso
    t = time.perf_counter()
    r = lectores.leer_foto(Image.new("RGB", (50, 50)))
    assert r.motivo == "sin_lugar" and 0.15 < time.perf_counter() - t < 1.0


def test_cupo_lleno_toma_el_lector_que_se_libera(ocr_simulado):
    """La fila existe para que una ráfaga no deje casi todo sin tapar: si el
    lector se libera dentro de la espera, la foto se lee."""
    ocr_simulado.setattr(lectores, "CUPO", 1)
    ocr_simulado.setattr(lectores, "ESPERA_MS", 2000)
    ocr_simulado.setattr(lectores, "_crear_motor", lambda: MotorFalso(reconoce=False))
    tomado = lectores._tomar_motor()
    threading.Timer(0.2, lambda: lectores._motores.put(tomado)).start()
    r = lectores.leer_foto(Image.new("RGB", (50, 50)))
    # MotorFalso(reconoce=False) -> "tiempo": lo que importa es que LLEGÓ a leer.
    assert r.motivo == "tiempo" and r.espera_ms >= 150


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
