"""Memoria del camino de lectura de una foto (OOM de Pruebas, 2026-11-06).

Una foto de celular de 12 MP (4000x3000) abierta entera son 36 MB por copia. El
camino de `/api/leer` la decodificaba, la transponía por el EXIF y la convertía
(tres copias vivas), la achicaba para el OCR, la achicaba otra vez para la IA,
la tapaba (dos copias) y guardaba dos más para el diagnóstico, y la página se
quedaba viva durante toda la llamada a la IA: ~150 MiB de pico sobre un servicio
de 512 MiB que en reposo ya estaba en 356. Un 502 en la cara de SDN.

Lo que fijan estos tests:
- el pico de `preparar` + diagnóstico + payload para la IA con una foto
  sintética de 12 MP, medido en un proceso aparte, queda por debajo de
  `UMBRAL_MIB` (antes del cambio daba ~150; ahora ~40);
- la foto se abre UNA vez, ya reducida y derecha, y lo que se lee, se tapa y se
  manda es la misma imagen (las cajas del OCR caen sobre lo que se tapa);
- una imagen con más píxeles de los que se pueden abrir da 400 (E-IMAGEN-01) en
  `/api/leer` y `/api/aportes` SIN decodificarse;
- una página de PDF grande se dibuja con tope de lado, y un A4 no cambia.

Tesseract no está en Windows y en Linux su memoria propia no se mide acá: el
proceso de medición lo reemplaza por un doble que copia la imagen como lo hace
`SetImage` (es la parte de la memoria que depende de lo que pase por delante).

Correr con: .venv/Scripts/python.exe -m pytest test_memoria_lectura.py -q
"""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

import auth
import db
import imagenes
import lectores
import main
from db import Sindicato, Trabajador
from fastapi.testclient import TestClient

# Umbral del pico (MiB sobre la línea de base). Medido: ~41 con el cambio y ~151
# sin él, con la foto de este archivo. El margen del servicio de Pruebas era de
# ~155 MiB (512 de tope, 356 en reposo) y una lectura real suma además la
# memoria propia de Tesseract; 80 deja a la mitad del margen lo que pasa por
# delante de Tesseract y falla con holgura si vuelve el camino de tres copias.
UMBRAL_MIB = 80

CUIL = "20202790411"
db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Memoria lectura", slug="memoria-lectura")
    s.add(sind); s.commit(); s.refresh(sind)
    s.add(Trabajador(sindicato_id=sind.id, cuil=CUIL, activo=True, registrado=True))
    db.guardar_datos_personales(s, CUIL, nombre="Sdn")
    s.commit()
client = TestClient(main.app, raise_server_exceptions=False)
client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", ident=CUIL))
client.cookies.set("cuil_trab", CUIL)


def foto_de_celular(ancho=4000, alto=3000, orientacion=6) -> bytes:
    """Una foto de celular sintética: fondo con ruido (que no comprime a nada),
    texto de recibo y la orientación EXIF que graba un teléfono en vertical."""
    base = Image.effect_noise((ancho // 10, alto // 10), 60).resize(
        (ancho, alto), Image.BICUBIC).convert("RGB")
    fino = Image.effect_noise((ancho, alto), 12).convert("RGB")
    img = Image.blend(base, fino, 0.35)
    dib = ImageDraw.Draw(img)
    fuente = ImageFont.load_default(size=70)
    for i in range(30):
        dib.text((200, 150 + i * 90), f"{i:03d}  SUELDO BASICO  CUIL: 20-20279041-1  {i * 1234.56:,.2f}",
                 fill=(15, 15, 15), font=fuente)
    exif = Image.Exif()
    if orientacion:
        exif[0x0112] = orientacion
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, exif=exif)
    return buf.getvalue()


# ----------------------------------------------------------------- el pico

_MEDIDOR = r'''
import ctypes, gc, io, json, os, sys, threading, time, types
sys.path.insert(0, os.getcwd())
os.environ["ENMASCARADO"] = "activo"
os.environ["ANTHROPIC_API_KEY"] = "x"
os.environ["MOCK_EXTRACTOR"] = "0"

if sys.platform == "win32":
    from ctypes import wintypes
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    _k = ctypes.windll.kernel32
    _k.GetCurrentProcess.restype = wintypes.HANDLE
    _h = _k.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    def rss():
        p = PMC(); p.cb = ctypes.sizeof(p)
        ctypes.windll.psapi.GetProcessMemoryInfo(_h, ctypes.pointer(p), p.cb)
        return p.WorkingSetSize / 2**20
else:
    def rss():
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20

pico = [0.0]; corre = [True]
def muestrear():
    while corre[0]:
        pico[0] = max(pico[0], rss()); time.sleep(0.001)
threading.Thread(target=muestrear, daemon=True).start()

# Tesseract simulado: copia la imagen como SetImage y "lee" un CUIL.
class _P:
    def __init__(s, t, c): s.t, s.caja = t, c
    def GetUTF8Text(s, _): return s.t
    def BoundingBox(s, _): return s.caja
class _API:
    def __init__(s, *a, **k): s.size = (1, 1)
    def SetVariable(s, *a): pass
    def SetImage(s, img): s._c = img.tobytes(); s.size = img.size
    def Recognize(s, ms): return True
    def GetIterator(s): return s
    def Clear(s): s._c = None
def _it(it, n):
    w, h = it.size
    return [_P("CUIL:", (int(w*.05), int(h*.05), int(w*.12), int(h*.07))),
            _P("20-20279041-1", (int(w*.13), int(h*.05), int(w*.30), int(h*.07)))]
fake = types.SimpleNamespace(PyTessBaseAPI=_API, PSM=types.SimpleNamespace(AUTO=0),
                             OEM=types.SimpleNamespace(LSTM_ONLY=0), RIL=types.SimpleNamespace(WORD=0),
                             iterate_level=_it)
sys.modules["tesserocr"] = fake
import lectores, preparacion, extractor, enmascarado as E
lectores._tesserocr = fake; lectores._disponible = True

class _Msg:
    content = [types.SimpleNamespace(text="{}")]; stop_reason = "end_turn"
    usage = types.SimpleNamespace(input_tokens=1, output_tokens=1)
enviado = {}
class _Cli:
    class messages:
        @staticmethod
        def create(**kw):
            enviado["b64"] = kw["messages"][0]["content"][0]["source"]["data"]; return _Msg()
extractor.client = _Cli()

conocidos = E.Conocidos(cuil="20202790411", nombre="Sdn")
contenido = open(sys.argv[1], "rb").read()
from PIL import Image
chica = io.BytesIO(); Image.new("RGB", (300, 200), "white").save(chica, "JPEG")
preparacion.preparar(chica.getvalue(), "image/jpeg", conocidos)       # calentamiento
gc.collect(); time.sleep(0.1)
base = rss(); pico[0] = base

prep = preparacion.preparar(contenido, "image/jpeg", conocidos)
preparacion.imagenes_diagnostico(prep, contenido, "image/jpeg")
prep.pagina = None                    # lo que hace main._preparar_para_ia
try:
    extractor.extraer(contenido, "image/jpeg", "claude-sonnet-4-6", imagen=prep.imagen,
                      aviso_enmascarado=prep.tapado)
except Exception:
    pass                              # la respuesta simulada no se interpreta; el pedido ya salió
time.sleep(0.01)
corre[0] = False
dim = Image.open(io.BytesIO(__import__("base64").b64decode(enviado["b64"]))).size
print(json.dumps({"base": base, "pico": pico[0] - base, "tapado": prep.tapado, "enviada": list(dim)}))
'''


def test_el_pico_de_leer_una_foto_de_12_mp_queda_bajo_el_umbral():
    with tempfile.TemporaryDirectory() as d:
        foto = Path(d) / "foto.jpg"
        foto.write_bytes(foto_de_celular())
        medidor = Path(d) / "medidor.py"
        medidor.write_text(_MEDIDOR, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(medidor), str(foto)], cwd=str(Path.cwd()),
                           capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    m = json.loads(r.stdout.strip().splitlines()[-1])
    print(f"base {m['base']:.0f} MiB, pico +{m['pico']:.1f} MiB (umbral {UMBRAL_MIB})")
    assert m["tapado"], "el doble de Tesseract encontró el CUIL: tiene que haberse tapado"
    assert m["pico"] > 5, f"el medidor no midió nada: {m}"
    assert m["pico"] < UMBRAL_MIB, f"el camino de lectura vuelve a pasarse: {m}"
    # Lo que viaja a la IA es la foto derecha (vertical, por el EXIF) y achicada.
    assert m["enviada"] == [1500, 2000], m
    print("OK  test_el_pico_de_leer_una_foto_de_12_mp_queda_bajo_el_umbral")


# ----------------------------------------------------- una sola imagen, derecha

def test_la_foto_se_abre_una_vez_derecha_y_achicada():
    img = lectores.abrir_imagen(foto_de_celular(4000, 3000, orientacion=6))
    assert img.mode == "RGB"
    assert img.size == (1500, 2000), img.size          # horizontal con EXIF 6 = vertical
    assert max(img.size) == lectores.LADO_MAXIMO_OCR == imagenes.LADO_MAXIMO_LECTURA
    # Una foto chica no se agranda ni se toca.
    chica = lectores.abrir_imagen(foto_de_celular(1200, 900, orientacion=0))
    assert chica.size == (1200, 900)
    print("OK  test_la_foto_se_abre_una_vez_derecha_y_achicada")


def test_las_cajas_del_ocr_caen_sobre_la_imagen_que_se_tapa(monkeypatch):
    # El OCR lee la imagen ya reducida (factor 1) y el tapado se hace sobre la
    # misma: la caja que devuelve el lector está en píxeles de esa imagen.
    recibido = {}

    def lector_falso(imagen, presupuesto_ms=None):
        recibido["tam"] = imagen.size
        w, h = imagen.size
        return lectores.LecturaFoto("ok", [
            lectores.Palabra("CUIL:", w * .05, h * .05, w * .12, h * .07, 0),
            lectores.Palabra("20-20279041-1", w * .13, h * .05, w * .30, h * .07, 0)])

    import preparacion
    import enmascarado as E
    monkeypatch.setattr(lectores, "leer_foto", lector_falso)
    prep = preparacion.preparar(foto_de_celular(), "image/jpeg",
                                E.Conocidos(cuil=CUIL, nombre="Sdn"), "activo")
    assert prep.tapado and prep.pagina is not None
    assert recibido["tam"] == prep.pagina.size == (1500, 2000)
    assert all(0 <= k.x0 < k.x1 <= prep.pagina.width and 0 <= k.y0 < k.y1 <= prep.pagina.height
               for k in prep.analisis.cajas)
    enviada = Image.open(io.BytesIO(__import__("base64").b64decode(prep.imagen[0])))
    assert enviada.size == prep.pagina.size
    print("OK  test_las_cajas_del_ocr_caen_sobre_la_imagen_que_se_tapa")


# ------------------------------------------------------------ el tope de entrada

def _png_gris(ancho, alto) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (ancho, alto), 128).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _jpeg_gris(ancho, alto) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (ancho, alto), 128).save(buf, "JPEG", quality=50)
    return buf.getvalue()


@pytest.mark.parametrize("ruta", ["/api/leer", "/api/aportes"])
@pytest.mark.parametrize("nombre,tipo", [("png_de_25_mp", "image/png"), ("jpeg_de_42_mp", "image/jpeg")])
def test_una_imagen_absurda_da_400_sin_decodificarse(monkeypatch, ruta, nombre, tipo):
    import preparacion
    datos = _png_gris(5000, 5000) if tipo == "image/png" else _jpeg_gris(7000, 6000)

    def prohibido(*a, **k):
        raise AssertionError("se intentó decodificar o preparar una imagen que pasa del tope")

    monkeypatch.setattr(Image.Image, "load", prohibido)
    monkeypatch.setattr(lectores, "abrir_imagen", prohibido)
    monkeypatch.setattr(preparacion, "preparar", prohibido)
    monkeypatch.setattr(main, "extraer", prohibido)
    monkeypatch.setattr(main, "extraer_aportes", prohibido)
    monkeypatch.setenv("ENMASCARADO", "activo")
    r = client.post(ruta, files={"archivo": (nombre, datos, tipo)})
    assert r.status_code == 400, (r.status_code, r.text[:200])
    j = r.json()
    assert j["codigo"] == "E-IMAGEN-01", j
    assert "foto" not in j["detail"].lower()          # no es un error de lectura
    print(f"OK  test_una_imagen_absurda_da_400_sin_decodificarse[{ruta},{nombre}]")


def test_el_tope_tambien_rige_con_el_enmascarado_apagado(monkeypatch):
    monkeypatch.setenv("ENMASCARADO", "apagado")
    r = client.post("/api/leer", files={"archivo": ("x.png", _png_gris(5000, 5000), "image/png")})
    assert r.status_code == 400 and r.json()["codigo"] == "E-IMAGEN-01", r.text[:200]
    print("OK  test_el_tope_tambien_rige_con_el_enmascarado_apagado")


def test_una_foto_normal_de_12_mp_pasa_el_tope():
    lectores.exigir_tamano_razonable(foto_de_celular(), "image/jpeg")       # no levanta
    lectores.exigir_tamano_razonable(b"%PDF-1.4 basura", "application/pdf")  # no es imagen
    lectores.exigir_tamano_razonable(b"no es una imagen", "image/jpeg")      # lo resuelve quien la abre
    print("OK  test_una_foto_normal_de_12_mp_pasa_el_tope")


# -------------------------------------------------------------------- el PDF

def _pdf(ancho_pt, alto_pt) -> bytes:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(ancho_pt, alto_pt)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def test_una_pagina_de_pdf_grande_se_dibuja_con_tope_de_lado_y_un_a4_no_cambia():
    a4 = lectores.imagen_pdf(_pdf(595, 842))
    assert abs(a4.width - 595 * lectores.ESCALA) <= 1 and abs(a4.height - 842 * lectores.ESCALA) <= 1, a4.size
    plano = lectores.imagen_pdf(_pdf(2000, 3000))            # un A0 apaisado, aprox.
    assert max(plano.size) <= lectores.LADO_MAXIMO_OCR + 1, plano.size
    assert plano.size[0] < plano.size[1]
    print("OK  test_una_pagina_de_pdf_grande_se_dibuja_con_tope_de_lado_y_un_a4_no_cambia")
