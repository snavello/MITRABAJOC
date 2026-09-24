"""Arma los datos de prueba del enmascarado (PLAN_ENMASCARADO.md, bloque 1).

Uso (herramienta de desarrollo, no corre en la app ni en la suite):

    python datos_prueba/enmascarado/generar.py [--sinteticos CARPETA] [--revisar CARPETA]

Qué deja en esta carpeta:

- `recibo_digital_ficticio.pdf`: un recibo clásico con capa de texto, dos
  páginas (original y duplicado), con una identidad inventada: nombre con
  acentos y Ñ, CUIL y CUIT con verificador válido, DNI, legajo, CBU. Lo
  dibuja reportlab (dependencia de desarrollo).
- `palabras_digital.json`: las palabras de ese PDF, leídas con
  `lectores.palabras_pdf` (texto del PDF, sin OCR).
- `palabras_sintetico_*.json`: si se pasa `--sinteticos` con la carpeta de
  los 10 recibos sintéticos (`recibos_anonimizados_3/anonimizados`, identidad
  ficticia NIEVES, JULIA), las palabras que leyó Tesseract de cada uno, con
  `lectores.leer_foto` (el mismo lector de la app). Son imágenes sin texto:
  prueban el camino de las fotos. Solo corre en Linux (en Windows, dentro de
  Docker). Los PDF no se versionan (2 MB cada uno); las palabras sí.

`--revisar CARPETA` deja además cada página tapada como PNG, para mirarla.
"""
import argparse
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
sys.path.insert(0, str(RAIZ))

import enmascarado as E  # noqa: E402
import lectores  # noqa: E402

# ---------------- Identidad inventada del recibo digital ----------------


def _con_dv(prefijo: str, medio: str) -> str:
    base = prefijo + medio
    for dv in range(10):
        if E.dv_valido(base + str(dv)):
            return base + str(dv)
    raise ValueError("verificador 10: elegir otro número")


CUIL = _con_dv("27", "28765431")          # 27-28765431-1
CUIT = _con_dv("30", "71234567")          # 30-71234567-1
NOMBRE = "GONZÁLEZ PEÑA, MARÍA JOSÉ"
RAZON = "DISTRIBUIDORA LOS ANDES S.R.L."
DNI = "28.765.431"
LEGAJO = "1187"
CBU = "0070089420000012345678"


def _fmt(once: str) -> str:
    return f"{once[:2]}-{once[2:10]}-{once[10]}"


def dibujar_pdf(destino: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(destino), pagesize=A4)
    _, alto = A4
    for copia in ("ORIGINAL", "DUPLICADO"):
        y = alto - 50
        c.setFont("Helvetica-Bold", 13)
        c.drawString(40, y, RAZON)
        c.setFont("Helvetica", 9)
        c.drawString(40, y - 14, f"CUIT: {_fmt(CUIT)}")
        c.drawString(40, y - 26, "Av. San Martín 450 - Mendoza")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(360, y, "RECIBO DE HABERES Nº 000123")
        c.setFont("Helvetica", 9)
        c.drawString(360, y - 14, "Período: Agosto 2026")
        c.drawString(360, y - 26, "Fecha de pago: 05/09/2026")
        c.drawString(500, y - 40, copia)

        y -= 70
        c.line(40, y + 12, 555, y + 12)
        c.drawString(40, y, f"Apellido y Nombre: {NOMBRE}")
        c.drawString(330, y, f"CUIL: {_fmt(CUIL)}")
        c.drawString(470, y, f"Legajo: {LEGAJO}")
        y -= 14
        c.drawString(40, y, f"DNI: {DNI}")
        c.drawString(160, y, "Categoría: Vendedor B")
        c.drawString(330, y, "Fecha de ingreso: 01/03/2015")
        y -= 14
        c.drawString(40, y, f"CBU: {CBU}")
        c.drawString(330, y, "Banco: Galicia")

        y -= 28
        c.setFont("Helvetica-Bold", 9)
        for x, t in ((40, "Código"), (90, "Concepto"), (300, "Cantidad"),
                     (380, "Haberes"), (470, "Deducciones")):
            c.drawString(x, y, t)
        c.setFont("Helvetica", 9)
        filas = [
            ("0101", "Sueldo básico", "30", "1.250.000,00", ""),
            ("0110", "Antigüedad", "11", "137.500,00", ""),
            ("0120", "Presentismo", "", "104.166,67", ""),
            ("0199", "A cuenta futuros aumentos", "", "85.000,00", ""),
            ("0501", "Jubilación", "11%", "", "173.520,83"),
            ("0502", "Ley 19032", "3%", "", "47.323,86"),
            ("0503", "Obra Social", "3%", "", "47.323,86"),
            ("0510", "Cuota sindical", "2%", "", "31.549,25"),
        ]
        for cod, con, can, hab, ded in filas:
            y -= 14
            c.drawString(40, y, cod)
            c.drawString(90, y, con)
            c.drawString(300, y, can)
            if hab:
                c.drawRightString(440, y, hab)
            if ded:
                c.drawRightString(540, y, ded)
        y -= 20
        c.setFont("Helvetica-Bold", 9)
        c.drawString(90, y, "TOTALES")
        c.drawRightString(440, y, "1.576.666,67")
        c.drawRightString(540, y, "299.717,80")
        y -= 16
        c.drawString(90, y, "NETO A COBRAR: $ 1.276.948,87")
        c.setFont("Helvetica", 8)
        y -= 40
        c.drawString(40, y, "Recibí conforme el importe neto de la presente liquidación.")
        y -= 30
        c.drawString(40, y, "Mendoza, 05/09/2026")
        c.drawString(330, y, NOMBRE)
        c.drawString(330, y - 10, "Firma del empleado")
        c.showPage()
    c.save()


# ---------------- Serialización ----------------


def _a_json(paginas) -> list:
    return [[p.texto, round(p.x0, 1), round(p.y0, 1), round(p.x1, 1), round(p.y1, 1), p.pagina]
            for pag in paginas for p in pag]


def _ocr_pdf(ruta: Path):
    """Palabras de un PDF-imagen con el mismo lector de fotos que usa la app
    (Tesseract, `lectores.leer_foto`). Solo en Linux: en Windows tesserocr no
    tiene rueda y esto se corre dentro de Docker."""
    import dataclasses

    imagenes = lectores.imagenes_pdf(ruta.read_bytes())
    paginas = []
    for n, img in enumerate(imagenes):
        lectura = lectores.leer_foto(img, ocr_ms=60000)
        if lectura.motivo != "ok":
            raise SystemExit(f"{ruta.name}: el OCR no leyó ({lectura.motivo})")
        paginas.append([dataclasses.replace(p, pagina=n) for p in lectura.palabras])
    return paginas, imagenes


def _revisar(nombre: str, imagenes, paginas, conocidos, carpeta: Path):
    todas = [p for pag in paginas for p in pag]
    an = E.analizar(todas, conocidos)
    for n, img in enumerate(imagenes):
        E.tapar(img, [k for k in an.cajas if k.pagina == n]).save(carpeta / f"{nombre}_p{n + 1}.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sinteticos", type=Path)
    ap.add_argument("--revisar", type=Path)
    ap.add_argument("--redibujar", action="store_true",
                    help="volver a dibujar el PDF ficticio (reportlab le pone la fecha adentro)")
    a = ap.parse_args()

    pdf = AQUI / "recibo_digital_ficticio.pdf"
    if a.redibujar or not pdf.exists():
        dibujar_pdf(pdf)
    paginas = lectores.palabras_pdf(pdf.read_bytes())
    (AQUI / "palabras_digital.json").write_text(
        json.dumps({"cuil": CUIL, "cuit": CUIT, "nombre": NOMBRE, "razon": RAZON,
                    "palabras": _a_json(paginas)}, ensure_ascii=False, indent=0),
        encoding="utf-8")
    print(f"digital: {sum(len(p) for p in paginas)} palabras en {len(paginas)} páginas")
    if a.revisar:
        a.revisar.mkdir(parents=True, exist_ok=True)
        _revisar("digital", lectores.imagenes_pdf(pdf.read_bytes()), paginas,
                 E.Conocidos(CUIL, NOMBRE, (RAZON,)), a.revisar)

    if a.sinteticos:
        for ruta in sorted(a.sinteticos.glob("recibo_*.pdf")):
            paginas, imagenes = _ocr_pdf(ruta)
            (AQUI / f"palabras_sintetico_{ruta.stem}.json").write_text(
                json.dumps({"palabras": _a_json(paginas)}, ensure_ascii=False, indent=0),
                encoding="utf-8")
            print(f"{ruta.name}: {sum(len(p) for p in paginas)} palabras")
            if a.revisar:
                _revisar(ruta.stem, imagenes, paginas,
                         E.Conocidos("27999999999", "NIEVES, JULIA",
                                     ("TALLERES METALURGICOS DEL SUR S.A.",)), a.revisar)


if __name__ == "__main__":
    main()
