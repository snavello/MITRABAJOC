"""Tests de enmascarado.py (PLAN_ENMASCARADO.md, bloque 1).

Dos partes:

- Casos chicos armados a mano: el dígito verificador, qué es un importe, un
  CUIL partido en tres palabras, dos columnas que no son un número, la
  tabla de conceptos que no tiene rótulos, el recibo ajeno.
- Los datos de prueba de `datos_prueba/enmascarado/`: un recibo digital
  ficticio (texto del PDF) y los 10 recibos sintéticos leídos con OCR. Sobre
  cada uno: todo lo que identifica queda tapado, NINGÚN importe se tapa, y el
  control de fuga da vacío. Con los datos conocidos (recibo del afiliado) y
  sin ellos (aprendizaje del admin).

No necesitan la base, el OCR ni reportlab: las palabras ya están leídas en
los JSON. Para regenerarlos: `python datos_prueba/enmascarado/generar.py`.
"""
import json
from pathlib import Path

import pytest

import enmascarado as E
from enmascarado import Conocidos, Palabra

DATOS = Path(__file__).parent / "datos_prueba" / "enmascarado"


def P(texto, x0, y0, x1=None, y1=None, pagina=0):
    """Palabra con un ancho aproximado por largo del texto si no se da."""
    x1 = x1 if x1 is not None else x0 + 9 * len(texto)
    y1 = y1 if y1 is not None else y0 + 18
    return Palabra(texto, x0, y0, x1, y1, pagina)


def tapados(analisis, pagina=None):
    return [k.texto for k in analisis.cajas if pagina is None or k.pagina == pagina]


# ======================= Piezas =======================


def test_digito_verificador():
    assert E.dv_valido("30444640975")
    assert E.dv_valido("27287654311")
    assert not E.dv_valido("27999999999")      # el CUIL de los sintéticos: verificador inválido
    assert not E.dv_valido("3044464097")       # 10 dígitos
    assert not E.dv_valido("30-44464097-5")    # se valida sin separadores


def test_dni_de_cuil():
    assert E.dni_de_cuil("27-28765431-1") == "28765431"
    assert E.dni_de_cuil("20-05123456-3") == "5123456"
    assert E.dni_de_cuil("123") == ""


@pytest.mark.parametrize("texto", ["$ 1.234,56", "1.250.000,00", "-110.000,00", "345100.00",
                                   "85.000,00", "$1234", "47.323,86-"])
def test_parece_importe(texto):
    assert E.parece_importe(texto)


@pytest.mark.parametrize("texto", ["27-99999999-9", "28.765.431", "045213/07", "1187",
                                   "0070089420000012345678", "01/03/2015", "310590"])
def test_no_parece_importe(texto):
    assert not E.parece_importe(texto)


# ======================= Detección =======================


def test_cuil_partido_en_tres_palabras():
    """Un PDF o un OCR pueden partir el número: se reconoce igual, por frase."""
    pal = [P("CUIL:", 10, 10, 60), P("27-", 64, 10, 90), P("28765431-", 94, 10, 170), P("1", 174, 10, 182)]
    an = E.analizar(pal)
    assert an.cuiles == ["27287654311"]
    assert set(tapados(an)) == {"27-", "28765431-", "1"}


def test_columnas_separadas_no_forman_un_numero():
    """Tres números en columnas lejanas no son un CUIL aunque el verificador
    diera bien: el hueco grande corta la frase."""
    pal = [P("27", 10, 10, 30), P("28765431", 300, 10, 380), P("1", 600, 10, 610)]
    assert E.dv_valido("27287654311")   # juntos SERÍAN un CUIL válido
    an = E.analizar(pal)
    assert an.cajas == [] and an.cuiles == []


def test_once_digitos_sin_verificador_no_se_tapa():
    """Un número de 11 cifras cualquiera (una referencia, un expediente) no se
    tapa si no tiene verificador válido ni está al lado de un rótulo."""
    pal = [P("Expediente", 10, 10), P("20123456780", 120, 10)]
    assert not E.dv_valido("20123456780")
    assert E.analizar(pal).cajas == []


def test_un_importe_nunca_se_tapa_aunque_este_junto_a_un_rotulo():
    pal = [P("Cuenta:", 10, 10, 70), P("1.234.567,89", 76, 10, 190)]
    assert E.analizar(pal).cajas == []


def test_la_tabla_de_conceptos_no_tiene_rotulos():
    """'A CUENTA FUTUROS AUMENTOS' adentro de la tabla no es una cuenta
    bancaria, y su cantidad no se tapa."""
    pal = [
        P("Concepto", 100, 100), P("Cantidad", 400, 100), P("Importe", 600, 100),
        P("Cuenta", 100, 130, 160), P("12345678", 170, 130, 250), P("85.000,00", 600, 130),
        P("TOTALES", 100, 200), P("85.000,00", 600, 200),
    ]
    assert E.analizar(pal).cajas == []


def test_encabezados_en_columnas_con_valores_debajo():
    """Legajo | Apellido y nombre | CUIL con los valores en la fila de abajo,
    no necesariamente centrados bajo su rótulo (así viene el recibo sintético)."""
    pal = [
        P("Legajo", 150, 260, 192, 284), P("Apellido y nombre", 470, 260, 567, 283),
        P("CUIL N", 954, 261, 1000, 282),
        P("045213/07", 127, 284, 208, 304), P("NIEVES,JULIA", 341, 285, 452, 302),
        P("27-99999999-9", 895, 283, 1007, 305),
    ]
    an = E.analizar(pal)
    tipos = {k.texto: k.tipo for k in an.cajas}
    assert tipos == {"045213/07": "legajo", "NIEVES,JULIA": "nombre", "27-99999999-9": "cuil"}
    # El CUIL con verificador inválido cuenta como leído porque está bajo su rótulo.
    assert an.cuiles == ["27999999999"]


def test_rotulo_cuil_con_la_n_pegada():
    """Tesseract lee "CUIL N" como "CUILN"; sigue siendo el rótulo."""
    pal = [P("CUILN", 957, 266, 1000, 282), P("27-99999999-9", 898, 288, 1007, 305)]
    an = E.analizar(pal)
    assert [k.tipo for k in an.cajas] == ["cuil"] and an.cuiles == ["27999999999"]


def test_rotulo_empleador_no_es_empleado():
    pal = [P("EMPLEADOR:", 10, 10, 100), P("ACME", 106, 10, 150)]
    assert [k.tipo for k in E.analizar(pal).cajas] == ["razon_social"]


def test_ley_19032_no_es_libreta_de_enrolamiento():
    pal = [P("LEY 19032", 10, 10, 100), P("12345678", 110, 10, 190)]
    assert E.analizar(pal).cajas == []


def test_nombre_conocido_con_acentos_y_letras_juntas():
    pal = [P("GONZALEZ", 10, 10), P("PEÑA,MARIA", 100, 10), P("Presentismo", 10, 400)]
    an = E.analizar(pal, Conocidos(nombre="González Peña, María José"))
    assert set(tapados(an)) == {"GONZALEZ", "PEÑA,MARIA"}
    assert an.nombre_encontrado


def test_nombre_corto_solo_si_es_la_palabra_entera():
    pal = [P("PAZ", 10, 10), P("PAZOS", 10, 60), P("CAPAZ", 10, 110)]
    an = E.analizar(pal, Conocidos(nombre="Paz, Ana"))
    assert tapados(an) == ["PAZ"]


def test_razon_social_con_forma_juridica_en_la_linea_de_abajo():
    pal = [P("TALLERES METALURGICOS DEL SUR", 480, 99, 763, 116), P("SOCIEDAD ANONIMA", 550, 124, 691, 140)]
    an = E.analizar(pal)
    assert set(tapados(an)) == {"TALLERES METALURGICOS DEL SUR", "SOCIEDAD ANONIMA"}


# ======================= Pertenencia y fuga =======================


def test_pertenece():
    propio = E.analizar([P("CUIL: 27-28765431-1", 10, 10)])
    assert E.pertenece(propio, "27287654311") is True
    assert E.pertenece(propio, "20111111119") is False       # recibo ajeno
    assert E.pertenece(E.analizar([P("Sueldo", 10, 10)]), "27287654311") is None  # no se leyó


def test_control_de_fuga_reclama_lo_que_quedo_a_la_vista():
    pal = [P("CUIL:", 10, 10, 60), P("27-28765431-1", 66, 10, 190)]
    con = Conocidos(cuil="27287654311")
    # Sin tapar: reclama el CUIL, y el DNI que va adentro.
    assert E.control_de_fuga(pal, [], con) == ["página 1: CUIL/CUIT", "página 1: DNI"]
    an = E.analizar(pal, con)
    assert E.control_de_fuga(pal, an.cajas, con) == []


def test_tapar_cubre_solo_la_caja():
    from PIL import Image

    img = Image.new("RGB", (400, 100), "white")
    caja = E.Caja(100, 40, 200, 60, 0, "cuil", "27-...", "conocido")
    out = E.tapar(img, [caja])
    assert out.size == img.size and img.getpixel((150, 50)) == (255, 255, 255)  # el original no cambia
    assert out.getpixel((10, 10)) == (255, 255, 255)                            # afuera, igual
    zona = out.crop((100, 40, 200, 60))
    assert set(zona.tobytes()) != {255}                                         # adentro, tapado


# ======================= Recibo digital ficticio =======================


def _cargar(nombre):
    d = json.loads((DATOS / nombre).read_text(encoding="utf-8"))
    return d, [Palabra(*x) for x in d["palabras"]]


def _es_importe_o_concepto(texto):
    return E.parece_importe(texto) or E._alnum(texto) in {
        "SUELDOBASICO", "ANTIGUEDAD", "PRESENTISMO", "JUBILACION", "OBRASOCIAL", "CUOTA", "SINDICAL"}


@pytest.mark.parametrize("con_conocidos", [True, False], ids=["afiliado", "aprendizaje"])
def test_recibo_digital(con_conocidos):
    d, pal = _cargar("palabras_digital.json")
    con = Conocidos(d["cuil"], d["nombre"], (d["razon"],))
    an = E.analizar(pal, con if con_conocidos else None)
    for pag in (0, 1):   # original y duplicado
        t = " ".join(tapados(an, pag))
        for dato in ("GONZÁLEZ", "PEÑA,", "MARÍA", "JOSÉ", "27-28765431-1", "28.765.431",
                     "1187", "0070089420000012345678", "30-71234567-1",
                     "DISTRIBUIDORA", "LOS", "ANDES", "S.R.L."):
            assert dato in t, f"página {pag + 1}: quedó a la vista {dato!r}"
    assert not [k.texto for k in an.cajas if _es_importe_o_concepto(k.texto)]
    # Lo que NO identifica sigue a la vista: período, categoría, fecha de ingreso, banco.
    for libre in ("Agosto", "Vendedor", "01/03/2015", "Galicia", "Mendoza,"):
        assert libre not in tapados(an)
    assert E.control_de_fuga(pal, an.cajas, con) == []
    assert an.cuiles == [d["cuil"]] and an.cuits == [d["cuit"]]
    if con_conocidos:
        assert an.cuil_sesion_encontrado and an.nombre_encontrado


# ======================= Los 10 recibos sintéticos (OCR) =======================

SINTETICOS = sorted(DATOS.glob("palabras_sintetico_*.json"))
NIEVES = Conocidos("27999999999", "NIEVES, JULIA", ("TALLERES METALURGICOS DEL SUR S.A.",))
# Lo que identifica en estos recibos, palabra por palabra como lo lee
# Tesseract, normalizado (el OCR varía un signo entre recibos: "ANONIMA." o
# "30-44464097:5"). El guion suelto de "22 - 41837529" también se tapa.
IDENTIDAD_SINTETICOS = {"NIEVES", "JULIA", "27999999999", "99999999", "04521307", "22", "41837529",
                        "30444640975", "TALLERES", "METALURGICOS", "DEL", "SUR", "SOCIEDAD", "ANONIMA"}


def test_estan_los_diez_sinteticos():
    assert len(SINTETICOS) == 10


@pytest.mark.parametrize("con_conocidos", [True, False], ids=["afiliado", "aprendizaje"])
@pytest.mark.parametrize("archivo", SINTETICOS, ids=lambda p: p.stem.replace("palabras_sintetico_", ""))
def test_recibo_sintetico(archivo, con_conocidos):
    """Exactamente la identidad: ni un dato menos (quedaría a la vista) ni
    una palabra más (se le taparía a la IA algo que necesita leer)."""
    _, pal = _cargar(archivo.name)
    an = E.analizar(pal, NIEVES if con_conocidos else None)
    assert {E._alnum(k.texto) for k in an.cajas} - {""} == IDENTIDAD_SINTETICOS
    assert E.control_de_fuga(pal, an.cajas, NIEVES) == []
    assert an.cuiles == ["27999999999"] and an.cuits == ["30444640975"]
    assert E.pertenece(an, "27999999999") is True
    assert E.pertenece(an, "20111111119") is False
