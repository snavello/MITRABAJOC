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
    # Sin nada conocido, el CUIL (verificador inválido) NO se tapa: no se
    # podría rearmar con certeza (regla de certeza). Queda anotado como leído.
    assert tipos == {"045213/07": "legajo", "NIEVES,JULIA": "nombre"}
    assert an.cuiles == ["27999999999"]
    # Si es el de la sesión, sí: se rearma con el de la sesión.
    an = E.analizar(pal, Conocidos(cuil="27999999999"))
    assert {k.texto: k.tipo for k in an.cajas}["27-99999999-9"] == "cuil"


def test_rotulo_cuil_con_la_n_pegada():
    """Tesseract lee "CUIL N" como "CUILN"; sigue siendo el rótulo."""
    pal = [P("CUILN", 957, 266, 1000, 282), P("2728765431 1", 898, 288, 1007, 305)]
    an = E.analizar(pal)   # 11 dígitos pegados-ish y sin formato: lo tapa el rótulo
    assert [k.tipo for k in an.cajas] == ["cuil"] and an.cuiles == ["27287654311"]


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


def test_un_cuil_mal_leido_no_hace_ajeno_el_recibo():
    """El OCR leyó mal un dígito del CUIL propio: a uno o dos dígitos no es
    prueba de que el recibo sea de otro -- None, no False."""
    mal_leido = E.analizar([P("CUIL:", 10, 10, 60), P("27-28765481-1", 66, 10, 190)])
    assert mal_leido.cuiles == ["27287654811"]              # se tapa igual
    assert E.pertenece(mal_leido, "27287654311") is None
    dos = E.analizar([P("CUIL:", 10, 10, 60), P("27-28765481-7", 66, 10, 190)])
    assert E.pertenece(dos, "27287654311") is None
    tres = E.analizar([P("CUIL:", 10, 10, 60), P("27-28761481-7", 66, 10, 190)])
    assert E.pertenece(tres, "27287654311") is False


def test_cuil_y_cuit_de_la_demo_solo_se_tapan_si_se_conocen():
    """Los CUIL y CUIT de la demo no cumplen el módulo 11. Sin conocerlos no
    se tapan (no se podrían rearmar con certeza); siendo el de la sesión y un
    CUIT conocido del afiliado, sí -- y se rearman con los conocidos."""
    assert not E.dv_valido("20111111119") and not E.dv_valido("30999888776")
    pal = [P("Afiliado", 10, 10, 90), P("20-11111111-9", 400, 10, 520),
           P("Empresa", 10, 60, 90), P("30-99988877-6", 400, 60, 520)]
    assert E.analizar(pal).cajas == []
    an = E.analizar(pal, Conocidos(cuil="20111111119", cuits=("30999888776",)))
    assert an.cuiles == ["20111111119"] and an.cuits == ["30999888776"]
    assert {k.tipo for k in an.cajas} == {"cuil", "cuit"}


def test_un_cuit_mal_leido_se_rearma_con_el_conocido_o_no_se_tapa():
    """El caso real: el OCR leyó 33-69345023-9 como 39-69945023.9. Si ese
    CUIT es conocido, se tapa y vuelve el CONOCIDO; si no, queda a la vista
    (antes se tapaba y el recibo se rearmaba con el CUIT equivocado)."""
    pal = [P("CUIT:", 851, 237, 890, 250), P("39-69945023.9", 894, 229, 1010, 250)]
    assert E.analizar(pal).cajas == []
    an = E.analizar(pal, Conocidos(cuits=("33-69345023-9",)))
    assert an.cuits == ["33693450239"] and [k.tipo for k in an.cajas] == ["cuit"]


def test_cuit_conocido_no_adivina_entre_dos_igual_de_cerca():
    """Con los CUITs de todo un sindicato, dos pueden quedar a la misma
    distancia de una lectura errada: ahí no se elige (sería rearmar el de otro
    empleador), y sin certeza el número queda a la vista."""
    assert E._cuit_conocido("30111111118", ["30111111118", "30111111128"]) == "30111111118"
    assert E._cuit_conocido("30111111138", ["30111111118", "30111111128"]) is None
    assert E._cuit_conocido("30111111138", ["30111111118", "30999999998"]) == "30111111118"


def test_once_cifras_pegadas_sin_verificador_ni_rotulo_no_se_tapan():
    """Sin formato ni verificador ni rótulo, 11 cifras pueden ser un importe."""
    assert E.analizar([P("Total", 10, 10), P("20111111119", 400, 10)]).cajas == []


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
                        "30444640975", "TALLERES", "METALURGICOS", "DEL", "SUR", "SOCIEDAD", "ANONIMA",
                        # Enfoque mixto: en la fila de la cuenta bancaria también se tapa el
                        # código de dependencia. No es de la persona, pero la IA no lo usa:
                        # es el exceso que ese enfoque acepta (docs/ENMASCARADO.md).
                        "B2XX000000"}


def test_estan_los_diez_sinteticos():
    assert len(SINTETICOS) == 10


@pytest.mark.parametrize("con_conocidos", [True, False], ids=["afiliado", "aprendizaje"])
@pytest.mark.parametrize("archivo", SINTETICOS, ids=lambda p: p.stem.replace("palabras_sintetico_", ""))
def test_recibo_sintetico(archivo, con_conocidos):
    """Exactamente la identidad: ni un dato menos (quedaría a la vista) ni
    una palabra más (se le taparía a la IA algo que necesita leer)."""
    _, pal = _cargar(archivo.name)
    con = NIEVES if con_conocidos else None
    an = E.analizar(pal, con)
    # Sin conocidos, el CUIL ficticio (verificador inválido) no se tapa: no se
    # podría rearmar con certeza. Con la sesión, sí.
    esperado = IDENTIDAD_SINTETICOS if con_conocidos else IDENTIDAD_SINTETICOS - {"27999999999"}
    assert {E._alnum(k.texto) for k in an.cajas} - {""} == esperado
    assert E.control_de_fuga(pal, an.cajas, con) == []
    assert an.cuiles == ["27999999999"] and an.cuits == ["30444640975"]
    assert E.pertenece(an, "27999999999") is True
    # Para otra sesión es ajeno, aunque el CUIL ficticio no cumpla el módulo
    # 11 (por ahora no se valida): difiere en más de dos dígitos.
    assert E.pertenece(an, "20111111119") is False


# ======================= Casos de una foto real (AEFIP, 2026-09-24) =======================
# Datos ficticios con la MISMA forma que la foto de SDN: logos de agua encima
# del encabezado, foto apenas torcida y el OCR leyendo con errores.

FICTICIO = Conocidos("20111222334", "GOMEZ ALBERTO RICARDO")


def test_rotulo_cuil_sin_la_i():
    """Tesseract leyó "CUIL Nº" como "CUL"."""
    pal = [P("CUL", 934, 301, 986, 313), P("20111222334", 906, 328, 1024, 352)]
    assert [k.tipo for k in E.analizar(pal, FICTICIO).cajas] == ["cuil"]


def test_cuil_propio_con_un_digito_mal_leido_se_tapa():
    """El logo de agua encima hizo leer "...4" donde decía "...3"."""
    pal = [P("20111222344", 906, 328, 1024, 352)]
    an = E.analizar(pal, FICTICIO)
    assert tapados(an) == ["20111222344"]
    assert an.cuil_sesion_encontrado and E.pertenece(an, FICTICIO.cuil) is True
    assert E.control_de_fuga(pal, [], FICTICIO) == ["página 1: CUIL/CUIT"]


def test_parte_del_nombre_con_una_letra_mal_leida():
    pal = [P("GOMEZ,", 306, 331, 400, 354), P("ALBERT0", 414, 335, 500, 355), P("RICARDO.", 508, 332, 581, 354)]
    assert len(E.analizar(pal, FICTICIO).cajas) == 3


def test_un_mes_no_es_un_nombre_parecido():
    """Con 5 letras, JULIA y JULIO serían "casi iguales": el mes del período
    no se tapa, y tampoco el año que lo acompaña."""
    pal = [P("PERIODO:", 600, 100, 700, 120), P("JULIO", 710, 100, 770, 120), P("2025", 780, 100, 830, 120)]
    assert E.analizar(pal, Conocidos(nombre="NIEVES, JULIA")).cajas == []


def test_signo_suelto_despues_del_rotulo_no_es_el_valor():
    """El OCR leyó un ">" al lado de "Nro. Cuenta": el valor está abajo."""
    pal = [P("Sucursal - Nro. Cuenta", 272, 456, 430, 472), P(">", 436, 456, 446, 470),
           P("18 - 30269198", 264, 486, 380, 502)]
    assert [k.tipo for k in E.analizar(pal).cajas] == ["cuenta"]


def test_una_caja_alta_no_une_dos_filas():
    """Una caja de ruido del logo, alta, entre dos filas: cada fila sigue
    siendo su propia línea (antes "Datos de la Cuenta" y "Sucursal - Nro.
    Cuenta" salían entremezcladas y el rótulo no encontraba su valor)."""
    pal = [P("Datos", 158, 428, 200, 443), P("Bancaria", 294, 432, 350, 447),
           P("TE", 397, 420, 430, 470),                     # la caja alta
           P("Sucursal", 272, 456, 330, 471), P("Nro.", 351, 458, 380, 471), P("Cuenta", 386, 459, 430, 472),
           P("18-30269198", 264, 486, 380, 502)]
    assert [k.tipo for k in E.analizar(pal).cajas] == ["cuenta"]


def test_legajo_sin_rotulo_en_la_fila_de_la_identidad():
    """El rótulo "Legajo" se leyó como "2": el número de la fila del nombre y
    del CUIL se tapa igual. Una fecha o un año en esa fila, no."""
    pal = [P("032949/91", 160, 323, 255, 355), P("GOMEZ,", 306, 331, 400, 354),
           P("28/07/1994", 600, 330, 700, 352), P("20111222334", 906, 328, 1024, 352)]
    an = E.analizar(pal, FICTICIO)
    assert {k.texto: k.tipo for k in an.cajas} == {"032949/91": "dato", "GOMEZ,": "nombre",
                                                    "20111222334": "cuil"}


def test_tapar_une_cajas_aunque_vengan_desordenadas():
    """En una foto torcida la segunda palabra del nombre está un poco más
    abajo; el rótulo tiene que cubrir las tres, no solo la última."""
    from PIL import Image
    cajas = [E.Caja(306, 331, 400, 354, 0, "nombre", "GOMEZ", "conocido"),
             E.Caja(508, 332, 581, 354, 0, "nombre", "RICARDO", "conocido"),
             E.Caja(414, 335, 500, 355, 0, "nombre", "ALBERTO", "conocido")]
    unidas = E._unir(cajas)
    assert len(unidas) == 1 and (unidas[0].x0, unidas[0].x1) == (306, 581)
    out = E.tapar(Image.new("RGB", (700, 400), "white"), cajas)
    assert set(out.crop((420, 338, 495, 352)).tobytes()) != {255}   # ALBERTO tapado


# ======================= Enfoque mixto: tapar alrededor de lo encontrado =======================


def test_la_parte_ilegible_del_nombre_se_tapa_por_estar_en_su_frase():
    """Dos partes del nombre reconocidas: la del medio, que el OCR leyó
    irreconocible por el logo de agua, se tapa igual. El rótulo, no."""
    pal = [P("Apellido", 40, 330, 110, 350), P("y", 114, 330, 122, 350), P("nombre:", 126, 330, 190, 350),
           P("GOMEZ,", 196, 330, 260, 350), P("A1b3rf", 266, 330, 320, 350), P("RICARDO", 326, 330, 400, 350)]
    an = E.analizar(pal, FICTICIO)
    assert set(tapados(an)) == {"GOMEZ,", "A1b3rf", "RICARDO"}


def test_la_lista_blanca_de_la_fila_de_identidad():
    """En la fila del nombre, lo que la IA necesita para evaluar se queda:
    fecha de ingreso, período, año, importe. El legajo se tapa."""
    pal = [P("032949/91", 40, 330, 130, 350), P("GOMEZ,", 196, 330, 260, 350),
           P("28/07/1994", 300, 330, 400, 350), P("07/2025", 420, 330, 490, 350),
           P("2025", 500, 330, 540, 350), P("1.234,56", 560, 330, 640, 350)]
    an = E.analizar(pal, FICTICIO)
    assert set(tapados(an)) == {"032949/91", "GOMEZ,"}


def test_el_tapon_es_mas_grande_que_la_palabra_y_toma_el_color(monkeypatch):
    from PIL import Image
    caja = E.Caja(100, 40, 200, 60, 0, "cuil", "27-...", "conocido")    # 20 px de alto
    blanco = Image.new("RGB", (400, 120), "white")
    monkeypatch.setenv("ENMASCARADO_COLOR", "rojo")
    out = E.tapar(blanco, [caja])
    assert out.getpixel((93, 34)) != (255, 255, 255)       # margen: 10 px a los costados, 7 arriba
    assert out.getpixel((150, 43))[0] > 150 and out.getpixel((150, 43))[1] < 80   # rojo
    monkeypatch.setenv("ENMASCARADO_COLOR", "violeta")      # desconocido -> gris
    assert E.color_tapon() == "gris"
    # Sin la variable: rojo donde se revisan las imágenes, gris en demo/prod.
    import entorno
    monkeypatch.delenv("ENMASCARADO_COLOR")
    for ent, esperado in (("pruebas", "rojo"), ("local", "rojo"), ("demo", "gris"), ("prod", "gris")):
        monkeypatch.setattr(entorno, "ENTORNO", ent)
        assert E.color_tapon() == esperado, ent
