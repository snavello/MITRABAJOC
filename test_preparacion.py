"""Tests de preparacion.py y de su enganche en las rutas (PLAN_ENMASCARADO.md,
bloque 3).

Lo que se prueba es la regla de mejor esfuerzo (CLAUDE.md, 2026-09-24): en
`apagado` todo queda como antes; en `sombra` se registra y no cambia nada;
en `activo` viaja la imagen tapada, la identidad vuelve con lo leído acá y
un recibo ajeno se corta ANTES de pagar la lectura. Y que ningún problema
del enmascarado frena un recibo.

La IA está simulada (no se gastan créditos). Corre en Windows: el PDF
digital no necesita OCR, y una foto sin Tesseract tiene que seguir de largo.

Correr con: .venv/Scripts/python.exe -m pytest test_preparacion.py -q
"""
import base64
import io
import os
from pathlib import Path

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import pytest
from PIL import Image
from sqlmodel import select

import auth
import db
import enmascarado as E
import extractor
import main
import preparacion
from db import RegistroEnmascarado, Sindicato, Trabajador
from fastapi.testclient import TestClient

PDF = (Path(__file__).parent / "datos_prueba" / "enmascarado" / "recibo_digital_ficticio.pdf").read_bytes()
CUIL = "27287654311"            # el del recibo digital ficticio
NOMBRE = "GONZÁLEZ PEÑA, MARÍA JOSÉ"
CONOCIDOS = E.Conocidos(CUIL, NOMBRE)


def _png(ancho=200, alto=100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (ancho, alto), "white").save(buf, format="PNG")
    return buf.getvalue()


# ======================= preparar() =======================


def test_apagado_no_hace_nada(monkeypatch):
    monkeypatch.delenv("ENMASCARADO", raising=False)
    p = preparacion.preparar(PDF, "application/pdf", CONOCIDOS)
    assert p.modo == "apagado" and p.imagen is None and not p.tapado and p.registro == {}


def test_modo_desconocido_es_apagado(monkeypatch):
    monkeypatch.setenv("ENMASCARADO", "prendido")
    assert preparacion.modo() == "apagado"


def test_activo_pdf_digital_tapa_y_sabe_de_quien_es():
    p = preparacion.preparar(PDF, "application/pdf", CONOCIDOS, "activo")
    assert p.tapado and p.pertenece is True
    r = p.registro
    assert r["camino"] == "pdf_texto" and r["motivo"] == "ok" and r["cajas"] > 5 and r["fugas"] == 0
    b64, media = p.imagen
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert media == "image/png" and img.size[0] > 1000


def test_activo_recibo_ajeno_pertenece_false():
    p = preparacion.preparar(PDF, "application/pdf", E.Conocidos("20111111119", "OTRA PERSONA"), "activo")
    assert p.pertenece is False and p.registro["pertenece"] is False


def test_sombra_calcula_pero_no_tapa():
    p = preparacion.preparar(PDF, "application/pdf", CONOCIDOS, "sombra")
    assert not p.tapado and p.registro["cajas"] > 5 and p.registro["tapado"] is False
    # Viaja el original, preparado como siempre (o None si en esta PC no hay
    # poppler: entonces el extractor lo prepara, igual que hoy).
    assert p.imagen is None or p.imagen[1] == "image/png"


def test_foto_sin_ocr_sigue_de_largo(monkeypatch):
    monkeypatch.setattr(preparacion.lectores, "_disponible", False)
    contenido = _png()
    p = preparacion.preparar(contenido, "image/png", CONOCIDOS, "activo")
    assert p.registro["camino"] == "foto" and p.registro["motivo"] == "sin_ocr"
    assert not p.tapado and p.imagen == (base64.standard_b64encode(contenido).decode(), "image/png")


def test_archivo_roto_no_levanta():
    """Un archivo que no es imagen: el enmascarado anota el error y no corta;
    el que falla (con su código de siempre) es el extractor."""
    p = preparacion.preparar(b"esto no es una imagen", "image/png", CONOCIDOS, "activo")
    assert p.registro["motivo"].startswith("error:") and not p.tapado


def test_tipo_no_soportado():
    p = preparacion.preparar(b"x", "text/plain", CONOCIDOS, "activo")
    assert p.registro["motivo"] == "tipo_no_soportado" and not p.tapado


# ======================= Rearmar =======================


def _analisis():
    return preparacion.preparar(PDF, "application/pdf", CONOCIDOS, "activo").analisis


def test_rearmar_completa_lo_tapado_con_lo_leido_aca():
    recibo = {"empleado": {"cuil": None, "apellido_nombre": "NOMBRE OCULTO", "legajo": None,
                           "categoria": "Vendedor B"},
              "empleador": {"nombre": None, "cuit": "CUIT OCULTO"},
              "alerta_adulteracion": {"detectada": True, "motivo": "el CUIL está OCULTO bajo un rótulo"}}
    preparacion.rearmar_recibo(recibo, _analisis(), CONOCIDOS, lambda cuit: "DISTRIBUIDORA LOS ANDES S.R.L.")
    assert recibo["empleado"]["cuil"] == CUIL
    assert recibo["empleado"]["apellido_nombre"] == NOMBRE
    assert recibo["empleado"]["legajo"] == "1187"
    assert recibo["empleado"]["categoria"] == "Vendedor B"        # lo que no se tapó, no se toca
    assert recibo["empleador"]["cuit"] == "30712345671"
    assert recibo["empleador"]["nombre"] == "DISTRIBUIDORA LOS ANDES S.R.L."
    assert recibo["alerta_adulteracion"] == {"detectada": False, "motivo": None}


def test_rearmar_no_pisa_lo_que_la_ia_leyo():
    recibo = {"empleado": {"cuil": "27-28765431-1", "apellido_nombre": "Gonzalez Peña"},
              "empleador": {"nombre": "Distribuidora", "cuit": "30-71234567-1"},
              "alerta_adulteracion": {"detectada": True, "motivo": "el neto tiene un dígito distinto"}}
    preparacion.rearmar_recibo(recibo, _analisis(), CONOCIDOS)
    assert recibo["empleado"]["apellido_nombre"] == "Gonzalez Peña"
    assert recibo["empleador"]["nombre"] == "Distribuidora"
    assert recibo["alerta_adulteracion"]["detectada"] is True     # una alerta real sigue en pie


def test_rearmar_sin_razon_cargada_usa_la_leida():
    recibo = {"empleado": {}, "empleador": {}}
    preparacion.rearmar_recibo(recibo, _analisis(), None, lambda cuit: None)
    assert "DISTRIBUIDORA" in recibo["empleador"]["nombre"]


def test_rearmar_aportes():
    datos = {"cuil": None, "meses": []}
    preparacion.rearmar_aportes(datos, _analisis(), CONOCIDOS)
    assert datos["cuil"] == CUIL


# ======================= El aviso a la IA =======================


def test_el_aviso_va_solo_si_la_imagen_va_tapada():
    sin = extractor._contenido("b64", "image/png", "ESQUEMA", False)
    con = extractor._contenido("b64", "image/png", "ESQUEMA", True)
    assert len(sin) == 2 and len(con) == 3
    assert "OCULTO" in con[2]["text"] and "adulteración" in con[2]["text"]


# ======================= Las rutas =======================

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Enmascarado", slug="test-enmascarado")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil=CUIL, activo=True, registrado=True))
    db.guardar_datos_personales(s, CUIL, nombre=NOMBRE)
    s.commit()


def _cliente(cuil=CUIL):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=SID, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


class IAFalsa:
    """Reemplaza a extraer(): anota con qué la llamaron y devuelve un recibo
    con los datos personales en null, como pide el aviso."""
    def __init__(self):
        self.llamadas = []

    def __call__(self, contenido, content_type, modelo=None, imagen=None, **kw):
        # El banco pasa la imagen en posición; las rutas, por nombre.
        if imagen is not None:
            kw["imagen"] = imagen
        self.llamadas.append(kw)
        return ({"periodo": "2026-08", "formato": "clasico",
                 "empleado": {"cuil": None, "apellido_nombre": None, "legajo": None},
                 "empleador": {"nombre": None, "cuit": None},
                 "lineas": [{"codigo": "0101", "descripcion": "Sueldo básico", "importe": 1250000,
                             "tipo": "remuneracion"}],
                 "totales_impresos": {"remuneraciones": 1250000, "descuentos": 0, "neto": 1250000},
                 "contribuciones_patronales": [], "confianza": "alta",
                 "alerta_adulteracion": {"detectada": False, "motivo": None}},
                {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1})


@pytest.fixture
def ia(monkeypatch):
    falsa = IAFalsa()
    monkeypatch.setattr(main, "extraer", falsa)
    return falsa


def _registros():
    with db.get_session() as s:
        return s.exec(select(RegistroEnmascarado).where(RegistroEnmascarado.sindicato_id == SID)
                      .order_by(RegistroEnmascarado.id)).all()


def _subir(cliente):
    return cliente.post("/api/leer", files={"archivo": ("recibo.pdf", PDF, "application/pdf")})


def test_ruta_apagado_llama_como_siempre(monkeypatch, ia):
    monkeypatch.delenv("ENMASCARADO", raising=False)
    antes = len(_registros())
    r = _subir(_cliente())
    assert r.status_code == 200, r.text
    assert ia.llamadas == [{}]                 # la misma llamada de siempre, sin argumentos nuevos
    assert len(_registros()) == antes          # y sin registro


def test_ruta_activo_manda_tapado_y_rearma(monkeypatch, ia):
    monkeypatch.setenv("ENMASCARADO", "activo")
    r = _subir(_cliente())
    assert r.status_code == 200, r.text
    kw = ia.llamadas[-1]
    assert kw["aviso_enmascarado"] is True and kw["imagen"][1] == "image/png"
    recibo = r.json()["recibo"]
    assert recibo["empleado"]["cuil"] == CUIL and recibo["empleado"]["apellido_nombre"] == NOMBRE
    assert recibo["empleador"]["cuit"] == "30712345671"
    reg = _registros()[-1]
    assert (reg.tipo, reg.modo, reg.camino, reg.motivo, reg.tapado, reg.pertenece) == \
           ("recibo", "activo", "pdf_texto", "ok", True, True)
    assert reg.fugas == 0 and reg.cajas > 5


def test_ruta_activo_recibo_ajeno_se_corta_sin_llamar_a_la_ia(monkeypatch, ia):
    monkeypatch.setenv("ENMASCARADO", "activo")
    ajeno = "20111111119"
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID, cuil=ajeno, activo=True, registrado=True))
        s.commit()
    r = _subir(_cliente(ajeno))
    assert r.status_code == 403 and r.json()["codigo"] == "E-RECIBO-04"
    assert ia.llamadas == []                   # ni se pagó la lectura ni salió el documento
    assert _registros()[-1].pertenece is False


def test_ruta_sombra_no_cambia_nada_y_registra(monkeypatch, ia):
    monkeypatch.setenv("ENMASCARADO", "sombra")
    r = _subir(_cliente())
    assert r.status_code == 200, r.text
    assert ia.llamadas[-1].get("aviso_enmascarado", False) is False
    reg = _registros()[-1]
    assert reg.modo == "sombra" and reg.tapado is False and reg.cajas > 5


def test_ruta_un_error_del_enmascarado_no_frena_el_recibo(monkeypatch, ia):
    monkeypatch.setenv("ENMASCARADO", "activo")

    def revienta(*a, **k):
        raise RuntimeError("se rompió todo")
    monkeypatch.setattr(preparacion, "_leer", revienta)
    r = _subir(_cliente())
    assert r.status_code == 200, r.text
    assert _registros()[-1].motivo == "error:RuntimeError"


# ======================= El banco de pruebas =======================

plataforma = TestClient(main.app)
plataforma.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


@pytest.fixture
def sin_poppler(monkeypatch):
    """El banco prepara el original con pdf2image, que necesita poppler (un
    programa del sistema): está en Render y en una PC con la app, pero no en
    el servidor del CI. El original no es lo que se prueba acá."""
    png = base64.standard_b64encode(_png(1240, 1754)).decode()
    monkeypatch.setattr(main, "preparar_imagen", lambda contenido, content_type: (png, "image/png"))


def _banco(ia, **extra):
    return plataforma.post("/plataforma/probar-modelos",
                           data={"tipo": "recibo", "modelos": ["claude-sonnet-4-6"], **extra},
                           files={"archivo": ("recibo.pdf", PDF, "application/pdf")})


def test_banco_sin_tapado_queda_como_siempre(ia, sin_poppler):
    r = _banco(ia)
    assert r.status_code == 200, r.text
    assert len(ia.llamadas) == 1 and "aviso_enmascarado" not in ia.llamadas[0]
    assert r.json()["enmascarado"] is None


def test_banco_con_tapado_lee_dos_veces_y_muestra_la_imagen(ia, sin_poppler):
    """Mismo modelo, original y tapado en columnas vecinas: la tabla línea
    por línea dice si tapar cambió algo. Y la imagen que recibe la IA."""
    r = _banco(ia, tapado="1")
    assert r.status_code == 200, r.text
    assert len(ia.llamadas) == 2
    assert [k.get("aviso_enmascarado", False) for k in ia.llamadas] == [False, True]
    d = r.json()
    assert d["modelos_leidos"] == ["Claude Sonnet 4.6", "Claude Sonnet 4.6 — tapado"]
    assert d["lineas"]["distintas"] == 0
    e = d["enmascarado"]
    assert e["tapado"] and e["camino"] == "pdf_texto" and e["fugas"] == 0
    assert e["imagen"].startswith("data:image/png;base64,")
    # La versión tapada vuelve rearmada, como en las rutas de verdad.
    tapada = next(m for m in d["modelos"] if m["tapado"])
    assert "30712345671" in tapada["json"]
