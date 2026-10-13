# -*- coding: utf-8 -*-
"""Grilla salarial bancaria vigente (CCT 18/75), en un solo lugar.

Puro: no importa `db`. Lo usan `cargar_bancaria.py` (el lote sintético), el
generador de recibos PDF de prueba (`docs/recibos-bancaria-prueba/`) y
`test_grilla_bancaria.py`. La transcripción completa —las tres ramas, el Día
del Bancario y las fuentes— está en `docs/cct-1875-bancarios.md`; acá va
solo lo que la simulación usa (rama administrativa). Cuando sale una grilla
nueva se cambian los números de este archivo y el documento, juntos.
"""

GRILLA = "agosto 2026 (firmada 11/09/2026)"

# Rama administrativa: (años de antigüedad desde, coeficiente, básico,
# conformado). El básico tiene un piso de $ 1.642.764,63 hasta los 3 años. El
# conformado es la remuneración mínima garantizada y existe solo hasta los 15
# años: desde los 20 el básico ya lo supera.
ESCALA_ADMINISTRATIVA = [
    (0, 1.00, 1_642_764.63, 2_505_061.24), (1, 1.04, 1_642_764.63, 2_505_061.24),
    (2, 1.08, 1_642_764.63, 2_505_061.24), (3, 1.11, 1_642_764.63, 2_505_061.24),
    (4, 1.13, 1_665_695.64, 2_505_061.24), (5, 1.17, 1_724_658.32, 2_508_315.25),
    (6, 1.20, 1_768_880.32, 2_511_567.97), (7, 1.24, 1_827_843.00, 2_514_821.98),
    (8, 1.26, 1_857_324.34, 2_518_074.70), (9, 1.30, 1_916_287.02, 2_521_328.70),
    (10, 1.35, 1_989_990.36, 2_524_582.71), (11, 1.39, 2_048_953.04, 2_527_836.71),
    (12, 1.43, 2_107_915.72, 2_531_089.44), (13, 1.48, 2_181_619.07, 2_534_342.13),
    (14, 1.52, 2_240_581.74, 2_537_595.99), (15, 1.63, 2_402_729.11, 2_540_849.85),
    (20, 1.74, 2_564_876.47, None), (25, 1.96, 2_889_171.20, None),
    (30, 2.07, 3_051_318.56, None), (35, 2.17, 3_198_725.25, None),
]
# Jerarquías que no salen de la antigüedad (algunas, para los recibos de prueba).
JERARQUIAS = {
    "Jefe Div. de 3a.": (2.28, 3_360_872.62),
    "Jefe Dep. de 3a.": (3.26, 4_805_458.21),
    "Jefe Ppal. de Dpto.": (4.02, 5_925_749.09),
}
# Art. 44: la categoría también la da la antigüedad (promociones automáticas).
CATEGORIA_POR_ANTIGUEDAD = [
    (35, "2º Jefe de División de 1º"), (30, "2º Jefe de División de 2º"),
    (25, "2º Jefe de División de 3º"), (20, "Jefe de Sección"),
    (15, "Ayudante de firma"), (0, "Auxiliar"),
]

# Adicionales: montos fijos por mes, iguales para toda categoría (el texto de
# 1975 los daba como % del inicial; la grilla vigente, no).
FUNCION_CAJERO = 163_963.06
FALLA_DE_CAJA = 287_355.05
FALLA_DE_CAJA_MONEDA_EXTRANJERA = 82_261.33
TITULOS = {"secundario": 27_979.69, "terciario": 65_069.99, "universitario": 97_604.47}
ZONA_PATAGONICA = {"La Pampa": 455_489.91,
                   "Patagones, Río Negro y Neuquén": 498_870.24,
                   "Chubut, Santa Cruz y Tierra del Fuego": 585_630.91}
GUARDERIA = 416_341.95

# ROE: (tope del tramo de sueldo bruto, [montos ANUALES por tramo de ROE del
# banco]). Se cobra 1/12 por mes. Columnas en TRAMOS_ROE.
TRAMOS_ROE = ["0% a 3,5%", "3,5% a 8,75%", "8,75% a 14,5%", "14,5% a 19,75%",
              "19,75% a 25%", "más de 25%"]
ROE_TABLA = [
    (3_275_626, [0, 868_962.01, 1_086_228.18, 1_357_708.22, 1_493_550.92, 1_642_844.40]),
    (4_242_954, [0, 1_629_290.94, 2_036_613.67, 2_545_792.76, 2_800_330.96, 3_080_333.26]),
    (5_091_586, [0, 2_389_619.86, 2_986_999.16, 3_733_774.62, 4_107_213.69, 4_517_924.79]),
    (None, [0, 2_824_049.53, 3_530_164.59, 4_412_680.07, 4_853_989.15, 5_339_346.99]),
]

# Día del Bancario (6 de noviembre): suma fija + coeficiente × monto, con mínimo.
DIA_BANCARIO_SUMA_FIJA = 1_973_675.85
DIA_BANCARIO_POR_COEFICIENTE = 259_499.59
DIA_BANCARIO_MINIMO = 2_233_175.44


def fila_de_escala(anios: int) -> tuple:
    """(desde, coeficiente, básico, conformado) del tramo cumplido más alto."""
    fila = ESCALA_ADMINISTRATIVA[0]
    for f in ESCALA_ADMINISTRATIVA:
        if anios >= f[0]:
            fila = f
    return fila


def categoria_de(anios: int) -> str:
    for desde, nombre in CATEGORIA_POR_ANTIGUEDAD:
        if anios >= desde:
            return nombre
    return "Auxiliar"


def roe_mensual(bruto: float, tramo_roe: int) -> float:
    """El ROE del mes: la fila la elige el sueldo bruto (sin el ROE), la
    columna el ROE del banco; la tabla es anual."""
    for tope, montos in ROE_TABLA:
        if tope is None or bruto <= tope:
            return round(montos[tramo_roe] / 12, 2)
    return 0.0


def dia_del_bancario(coeficiente: float) -> float:
    return round(max(DIA_BANCARIO_MINIMO,
                     DIA_BANCARIO_SUMA_FIJA + coeficiente * DIA_BANCARIO_POR_COEFICIENTE), 2)
