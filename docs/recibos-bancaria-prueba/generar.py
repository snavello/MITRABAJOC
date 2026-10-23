# -*- coding: utf-8 -*-
"""Diez recibos de sueldo bancarios SIMULADOS, en PDF, para probar la lectura.

Todos son del CUIL de prueba 27999999994 (para que la app los acepte como
propios: un recibo de otro CUIL se corta con E-RECIBO-04), período agosto
2026, con los montos de la grilla vigente (`grilla_bancaria.py`). Los bancos
son ficticios y cada hoja dice al pie que es un documento simulado.

Siete están bien liquidados y tres tienen un error a propósito, para ver que
la app lo marque. El detalle de cada uno, en `LEEME.md` de esta carpeta, y
`test_grilla_bancaria.py` verifica con el validador real que cada caso dé el
resultado que se anuncia.

reportlab NO es dependencia del proyecto (ni de desarrollo): para regenerar,
en un entorno aparte,
    pip install reportlab
    python docs/recibos-bancaria-prueba/generar.py
"""
import csv
import os
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)

import cuit  # noqa: E402
import grilla_bancaria as g  # noqa: E402

CARPETA = os.path.dirname(os.path.abspath(__file__))
CUIL = "27999999994"
NOMBRE = "PRUEBA, USUARIA"
PERIODO = "2026-08"
PERIODO_TEXTO = "AGOSTO 2026"
FECHA_PAGO = "04/09/2026"


def _tope_maximo(periodo: str) -> float:
    with open(os.path.join(RAIZ, "data", "topes_ss.csv"), encoding="utf-8") as f:
        for fila in csv.reader(f):
            if fila and fila[0] == periodo:
                return float(fila[1])
    raise SystemExit(f"No hay tope cargado para {periodo} en data/topes_ss.csv")


TOPE = _tope_maximo(PERIODO)

BANCOS = {
    "plata": ("BANCO FICTICIO DEL PLATA S.A.", cuit.corregir("30710000011"),
              "Av. Corrientes 1234, C1043AAZ, Ciudad Autónoma de Buenos Aires", 1),
    "litoral": ("BANCO DE PRUEBAS DEL LITORAL S.A.", cuit.corregir("30710000022"),
                "San Martín 845, S2000, Rosario, Santa Fe", 2),
    "pampa": ("BANCO SIMULADO DE LA PAMPA S.A.", cuit.corregir("30710000033"),
              "Av. Colón 410, X5000, Córdoba", 3),
    "muestra": ("BANCO MUESTRA ARGENTINO S.A.", cuit.corregir("30710000044"),
                "Reconquista 330, C1003, Ciudad Autónoma de Buenos Aires", 5),
    "patagonia": ("BANCO ENSAYO PATAGÓNICO S.A.", cuit.corregir("30710000055"),
                  "San Martín 560, U9000, Comodoro Rivadavia, Chubut", 0),
}


def _escalafon(anios):
    _, coef, basico, conformado = g.fila_de_escala(anios)
    return g.categoria_de(anios), coef, basico, conformado


def _haberes(basico, conformado=None, cajero=False, titulo=None, zona=None):
    lineas = [("0010", "Sueldo básico", basico)]
    if conformado and conformado > basico:
        lineas.append(("0012", "Complemento salario conformado", round(conformado - basico, 2)))
    if cajero:
        lineas.append(("0120", "Adicional función cajero", g.FUNCION_CAJERO))
        lineas.append(("0121", "Falla de caja", g.FALLA_DE_CAJA))
    if titulo:
        lineas.append(("0130", f"Adicional título {titulo}", g.TITULOS[titulo]))
    if zona:
        lineas.append(("0140", "Adicional zona patagónica", g.ZONA_PATAGONICA[zona]))
    return lineas


def armar(caso):
    """Las líneas del recibo de un caso: haberes, ROE y descuentos de ley."""
    haberes = _haberes(caso["basico"], caso.get("conformado"), caso.get("cajero"),
                       caso.get("titulo"), caso.get("zona"))
    bruto_sin_roe = sum(i for _, _, i in haberes)
    roe = g.roe_mensual(bruto_sin_roe, BANCOS[caso["banco"]][3])
    if roe:
        haberes.append(("0200", "Participación en las ganancias (ROE)", roe))
    bruto = round(sum(i for _, _, i in haberes), 2)
    base = min(bruto, TOPE)
    jub = round(base * caso.get("pct_jubilacion", 0.11), 2)
    descuentos = [("0501", "Jubilación SIPA Ley 24.241", jub),
                  ("0502", "Ley 19.032 (INSSJP)", round(base * 0.03, 2))]
    if not caso.get("sin_obra_social"):
        descuentos.append(("0503", "Obra Social OSBA", round(base * 0.03, 2)))
    descuentos.append(("0510", "Cuota sindical Asociación Bancaria", round(bruto * 0.02, 2)))
    if caso.get("reintegro_ganancias"):
        # Impreso ENTRE los descuentos, con signo contrario (validador.repartir_por_zona).
        descuentos.append(("0590", "Devolución Impuesto a las Ganancias",
                           -caso["reintegro_ganancias"]))
    total_desc = round(sum(i for _, _, i in descuentos), 2)
    neto = round(bruto - total_desc - caso.get("neto_de_menos", 0), 2)
    return haberes, descuentos, bruto, total_desc, neto


CASOS = [
    dict(archivo="01-inicial-conformado", banco="plata", anios=0, legajo="10452",
         ingreso="02/03/2026", nota="Ingresante: básico de la grilla + complemento hasta el conformado."),
    dict(archivo="02-cajero-titulo-secundario", banco="litoral", anios=7, legajo="08317",
         ingreso="01/06/2019", cajero=True, titulo="secundario",
         nota="7 años, cajero (función y falla en dos líneas) y título secundario."),
    dict(archivo="03-titulo-universitario-anexo-iii", banco="pampa", anios=12, legajo="05561",
         ingreso="15/04/2014", titulo="universitario", nuevo=True,
         nota="12 años, título universitario, formato nuevo (Anexo III, costo total empleador)."),
    dict(archivo="04-jefe-de-seccion-cajero", banco="muestra", anios=20, legajo="02284",
         ingreso="03/02/2006", cajero=True,
         nota="20 años (Jefe de Sección): el básico ya supera al conformado, no hay complemento."),
    dict(archivo="05-zona-patagonica-sin-roe", banco="patagonia", anios=10, legajo="06790",
         ingreso="01/08/2016", zona="Chubut, Santa Cruz y Tierra del Fuego",
         nota="10 años, zona patagónica (Chubut); su banco está en el tramo de ROE que no paga."),
    dict(archivo="06-jefe-principal-tope", banco="litoral", jerarquia="Jefe Ppal. de Dpto.",
         legajo="00915", ingreso="10/05/1999", titulo="universitario", nuevo=True,
         nota="Jefe Ppal. de Dpto.: el bruto supera el tope y los aportes se calculan sobre el tope."),
    dict(archivo="07-reintegro-ganancias", banco="plata", anios=15, legajo="03842",
         ingreso="01/07/2011", titulo="terciario", reintegro_ganancias=45_320.00,
         nota="15 años, título terciario y una devolución de Ganancias impresa entre los descuentos."),
    dict(archivo="08-ERROR-jubilacion-10", banco="pampa", anios=5, legajo="07123",
         ingreso="01/09/2021", pct_jubilacion=0.10,
         error="Jubilación al 10% en vez del 11%.",
         nota="5 años. ERROR: la jubilación está al 10%."),
    dict(archivo="09-ERROR-sin-obra-social", banco="muestra", anios=3, legajo="09034",
         ingreso="05/05/2023", cajero=True,
         sin_obra_social=True, error="Falta la línea de obra social.",
         nota="3 años, cajero. ERROR: no descuenta obra social."),
    dict(archivo="10-ERROR-neto-mal-sumado", banco="plata", anios=25, legajo="01377",
         ingreso="01/03/2001", titulo="secundario", neto_de_menos=10_000.00,
         error="El neto impreso tiene $ 10.000 menos de lo que da la cuenta.",
         nota="25 años. ERROR: el neto a cobrar está mal sumado."),
]


def _completar(caso):
    if "jerarquia" in caso:
        coef, basico = g.JERARQUIAS[caso["jerarquia"]]
        caso.update(categoria=caso["jerarquia"], coef=coef, basico=basico, conformado=None)
    else:
        categoria, coef, basico, conformado = _escalafon(caso["anios"])
        caso.update(categoria=categoria, coef=coef, basico=basico, conformado=conformado)
    return caso


def pesos(x: float) -> str:
    texto = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{texto}" if x < 0 else texto


def dibujar(caso, ruta):
    # reportlab se importa acá: los casos y sus cuentas (`armar`) los usa
    # también test_grilla_bancaria.py, que corre sin reportlab.
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    haberes, descuentos, bruto, total_desc, neto = armar(caso)
    razon, cuit_banco, domicilio, tramo = BANCOS[caso["banco"]]
    c = canvas.Canvas(ruta, pagesize=A4)
    c.setTitle(f"Recibo de haberes {PERIODO_TEXTO} - {NOMBRE} (simulado)")
    ancho, alto = A4
    x0, x1 = 15 * mm, ancho - 15 * mm
    y = alto - 18 * mm

    # Empleador
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x0, y, razon)
    c.setFont("Helvetica", 9)
    c.drawString(x0, y - 5 * mm, f"CUIT {cuit.formatear(cuit_banco)}")
    c.drawString(x0, y - 9.5 * mm, domicilio)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x1, y, "RECIBO DE HABERES")
    c.setFont("Helvetica", 8.5)
    c.drawRightString(x1, y - 5 * mm, "Art. 140 Ley 20.744 · ORIGINAL")
    c.drawRightString(x1, y - 9.5 * mm, "Convenio Colectivo de Trabajo 18/75")

    # Empleado
    y -= 16 * mm
    c.rect(x0, y - 22 * mm, x1 - x0, 22 * mm)
    filas = [
        ("Apellido y nombre", NOMBRE, "CUIL", cuit.formatear(CUIL)),
        ("Legajo", caso["legajo"], "Fecha de ingreso", caso["ingreso"]),
        ("Categoría", f"{caso['categoria']} (coef. {caso['coef']:.2f})".replace(".", ","),
         "Rama", "Administrativa"),
        ("Período liquidado", PERIODO_TEXTO, "Fecha de pago", FECHA_PAGO),
    ]
    for i, (e1, v1, e2, v2) in enumerate(filas):
        yy = y - (5 + i * 5) * mm
        c.setFont("Helvetica", 7.5)
        c.drawString(x0 + 2 * mm, yy, e1.upper())
        c.drawString(x0 + 105 * mm, yy, e2.upper())
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(x0 + 33 * mm, yy, v1)
        c.drawString(x0 + 135 * mm, yy, v2)
    y -= 28 * mm

    # Tabla de conceptos
    cols = [x0, x0 + 14 * mm, x0 + 90 * mm, x0 + 120 * mm, x0 + 150 * mm, x1]
    titulos = ["Cód.", "Concepto", "Remunerativo", "No remunerativo", "Descuentos"]
    c.setFillGray(0.88)
    c.rect(x0, y - 6 * mm, x1 - x0, 6 * mm, fill=1, stroke=1)
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 8.5)
    for i, t in enumerate(titulos):
        if i < 2:
            c.drawString(cols[i] + 1.5 * mm, y - 4.2 * mm, t)
        else:
            c.drawRightString(cols[i + 1] - 1.5 * mm, y - 4.2 * mm, t)
    y -= 6 * mm
    renglones = [(cod, desc, imp, None) for cod, desc, imp in haberes] + \
                [(cod, desc, None, imp) for cod, desc, imp in descuentos]
    alto_tabla = (len(renglones) + 2) * 6 * mm
    c.rect(x0, y - alto_tabla, x1 - x0, alto_tabla)
    for cx in cols[1:-1]:
        c.line(cx, y, cx, y - alto_tabla)
    c.setFont("Helvetica", 9)
    for cod, desc, haber, desc_imp in renglones:
        y -= 6 * mm
        c.drawString(cols[0] + 1.5 * mm, y + 1.8 * mm, cod)
        c.drawString(cols[1] + 1.5 * mm, y + 1.8 * mm, desc)
        if haber is not None:
            c.drawRightString(cols[3] - 1.5 * mm, y + 1.8 * mm, pesos(haber))
        if desc_imp is not None:
            c.drawRightString(cols[5] - 1.5 * mm, y + 1.8 * mm, pesos(desc_imp))
    y -= 12 * mm
    c.line(x0, y + 6 * mm, x1, y + 6 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(cols[1] + 1.5 * mm, y + 1.8 * mm, "TOTALES")
    c.drawRightString(cols[3] - 1.5 * mm, y + 1.8 * mm, pesos(bruto))
    c.drawRightString(cols[4] - 1.5 * mm, y + 1.8 * mm, "0,00")
    c.drawRightString(cols[5] - 1.5 * mm, y + 1.8 * mm, pesos(total_desc))

    # Neto
    y -= 10 * mm
    c.setFillGray(0.92)
    c.rect(x1 - 75 * mm, y - 2 * mm, 75 * mm, 9 * mm, fill=1, stroke=1)
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x1 - 73 * mm, y + 1 * mm, "NETO A COBRAR")
    c.drawRightString(x1 - 2 * mm, y + 1 * mm, f"$ {pesos(neto)}")
    c.setFont("Helvetica", 8.5)
    c.drawString(x0, y + 1 * mm, f"Acreditado en cuenta sueldo {razon}")

    # Último depósito de aportes (Ley 17.250)
    y -= 10 * mm
    c.setFont("Helvetica", 8.5)
    c.drawString(x0, y, "Último depósito de aportes y contribuciones: período 07/2026 · "
                        f"fecha 07/08/2026 · {razon}")
    c.drawString(x0, y - 4.5 * mm, f"Tramo ROE de la entidad: {g.TRAMOS_ROE[tramo]} "
                                   f"(tabla ROE {g.GRILLA}).")

    # Formato nuevo: costo total empleador (Anexo III, Dto. 407/2026)
    if caso.get("nuevo"):
        y -= 12 * mm
        contribs = [("Contribución Jubilación (SIPA)", "10,77", 0.1077),
                    ("Contribución INSSJP", "1,59", 0.0159),
                    ("Asignaciones familiares", "4,70", 0.047),
                    ("Fondo Nacional de Empleo", "0,94", 0.0094),
                    ("Contribución OO.SS.", "6,00", 0.06),
                    ("ART", "2,50", 0.025)]
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(x0, y, "COSTO TOTAL EMPLEADOR — Anexo III Decreto 407/2026")
        y -= 5 * mm
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x0 + 2 * mm, y, "CONCEPTO")
        c.drawRightString(x0 + 110 * mm, y, "BASE")
        c.drawRightString(x0 + 135 * mm, y, "UNIDAD")
        c.drawRightString(x1 - 2 * mm, y, "IMPORTE")
        c.setFont("Helvetica", 8.5)
        total_contrib = 0.0
        for concepto, pct_txt, pct in contribs:
            y -= 4.5 * mm
            importe = round(bruto * pct, 2)
            total_contrib += importe
            c.drawString(x0 + 2 * mm, y, concepto)
            c.drawRightString(x0 + 110 * mm, y, pesos(bruto))
            c.drawRightString(x0 + 135 * mm, y, f"{pct_txt}%")
            c.drawRightString(x1 - 2 * mm, y, pesos(importe))
        y -= 4.5 * mm
        c.drawString(x0 + 2 * mm, y, "Seguro de vida obligatorio")
        c.drawRightString(x1 - 2 * mm, y, pesos(1_850.00))
        total_contrib += 1_850.00
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(x0 + 2 * mm, y, "Costo total empleador")
        c.drawRightString(x1 - 2 * mm, y, f"$ {pesos(round(bruto + total_contrib, 2))}")

    # Firmas
    y -= 22 * mm
    c.line(x0, y, x0 + 65 * mm, y)
    c.line(x1 - 65 * mm, y, x1, y)
    c.setFont("Helvetica", 8)
    c.drawString(x0, y - 4 * mm, "Firma del empleador")
    c.drawString(x1 - 65 * mm, y - 4 * mm, "Recibí conforme — firma del empleado")

    c.setFont("Helvetica-Oblique", 7.5)
    c.drawCentredString(ancho / 2, 10 * mm, "Documento SIMULADO para pruebas de Colm3na. "
                        "Banco y persona ficticios; sin validez legal.")
    c.showPage()
    c.save()
    return bruto, total_desc, neto


if __name__ == "__main__":
    for caso in CASOS:
        _completar(caso)
        ruta = os.path.join(CARPETA, caso["archivo"] + ".pdf")
        bruto, desc, neto = dibujar(caso, ruta)
        print(f"{caso['archivo']}.pdf  bruto {pesos(bruto)}  descuentos {pesos(desc)}  "
              f"neto {pesos(neto)}")
