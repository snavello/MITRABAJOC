# -*- coding: utf-8 -*-
"""Archivos al límite para `/api/leer` (PLAN_PRUEBAS_BANCARIA.md, B6).

Arma, a partir de recibos del lote bancario, los archivos que un afiliado
puede subir sin querer o a propósito, y (con `--si`) los manda a la app con
la sesión del dueño del recibo. Criterio: **ninguno da 500**; todo lo que no
es 200 trae un código propio (`E-...`).

Uso:
    python carga/lote_bancaria.py extraer
    python carga/archivos_limite.py generar          # -> carga/archivos_limite/
    python carga/archivos_limite.py enviar --base-url https://mitrabajo-pruebas.onrender.com      # ensayo
    python carga/archivos_limite.py enviar --base-url ... --si

Ojo con el mock: con `MOCK_EXTRACTOR=1` el extractor no abre el archivo, así
que un PDF dañado puede dar 200. Con el mock se mide lo que corre antes
(enmascarado, OCR, memoria); los códigos de error de lectura se ven solo con
la IA real (son 9 archivos: unos centavos).
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lote_bancaria as L  # noqa: E402

CARPETA = Path(__file__).resolve().parent / "archivos_limite"
USUARIOS = Path(__file__).resolve().parent / "usuarios_bancaria.csv"


def _base(formato: str) -> dict:
    """El primer recibo correcto del lote en ese formato."""
    return next(f for f in L.manifiesto() if f["formato"] == formato and not f["error_intencional"])


def generar(carpeta: Path = CARPETA) -> list[dict]:
    """Escribe los archivos y devuelve [{archivo, cuil, mime, que_prueba}]."""
    from PIL import Image, ImageEnhance
    from pypdf import PdfReader, PdfWriter

    carpeta.mkdir(parents=True, exist_ok=True)
    pdf, jpg = _base("pdf"), _base("jpg")
    pdf_bytes = (L.DESTINO / pdf["archivo"]).read_bytes()
    foto = Image.open(L.DESTINO / jpg["archivo"]).convert("RGB")
    casos = []

    def guardar(nombre, datos, mime, dueno, que):
        (carpeta / nombre).write_bytes(datos)
        casos.append({"archivo": nombre, "cuil": L.solo_digitos(dueno["cuil"]), "mime": mime,
                      "que_prueba": que})

    def jpeg(img, calidad=88):
        b = io.BytesIO()
        img.save(b, "JPEG", quality=calidad)
        return b.getvalue()

    # Varias páginas: el mismo recibo y dos meses siguientes de la misma persona.
    w = PdfWriter()
    mismos = [f for f in L.manifiesto() if f["cuil"] == pdf["cuil"]][:3]
    for f in mismos:
        for p in PdfReader(L.DESTINO / f["archivo"]).pages:
            w.add_page(p)
    b = io.BytesIO()
    w.write(b)
    guardar("multipagina_3.pdf", b.getvalue(), "application/pdf", pdf, "PDF con tres recibos")
    w = PdfWriter()
    for _ in range(40):
        w.add_page(PdfReader(io.BytesIO(pdf_bytes)).pages[0])
    b = io.BytesIO()
    w.write(b)
    guardar("pdf_40_paginas.pdf", b.getvalue(), "application/pdf", pdf, "PDF largo (40 páginas)")
    guardar("pdf_danado.pdf", pdf_bytes[: len(pdf_bytes) // 2], "application/pdf", pdf,
            "PDF cortado a la mitad")
    guardar("vacio.pdf", b"", "application/pdf", pdf, "archivo de 0 bytes")
    guardar("texto_como_pdf.pdf", "esto no es un pdf\n".encode() * 50, "application/pdf", pdf,
            "texto con extensión .pdf")
    guardar("foto_12mp.jpg", jpeg(foto.resize((3000, 4000))), "image/jpeg", jpg,
            "foto de 12 MP (teléfono)")
    guardar("foto_torcida.jpg", jpeg(foto.rotate(7, expand=True, fillcolor="white")), "image/jpeg",
            jpg, "foto girada 7°")
    guardar("foto_oscura.jpg", jpeg(ImageEnhance.Brightness(foto).enhance(0.35), 60), "image/jpeg",
            jpg, "foto con poca luz y mucha compresión")
    ruido = Image.effect_noise((1240, 1754), 80).convert("RGB")
    guardar("no_es_recibo.jpg", jpeg(ruido), "image/jpeg", jpg, "imagen que no es un recibo")
    (carpeta / "casos.json").write_text(json.dumps(casos, ensure_ascii=False, indent=1), encoding="utf-8")
    return casos


def evaluar(status: int, cuerpo: dict | None) -> str:
    """'ok' | 'codigo' (rechazo con código propio) | 'FALLA'. Puro."""
    if status == 200:
        return "ok"
    if status < 500 or status == 503:
        return "codigo" if (cuerpo or {}).get("codigo", "").startswith("E-") else "FALLA"
    return "FALLA"


def enviar(base: str, escribir: bool) -> list[dict]:
    import httpx
    casos = json.loads((CARPETA / "casos.json").read_text(encoding="utf-8"))
    with open(USUARIOS, encoding="utf-8") as f:
        claves = {r["cuil"]: r["clave"] for r in csv.DictReader(f) if r["clave"]}
    if not escribir:
        for c in casos:
            print(f"  {c['archivo']:24} {c['que_prueba']}")
        print(f"Ensayo: {len(casos)} archivos contra {base}. Con --si se mandan.")
        return []
    salida = []
    for c in casos:
        with httpx.Client(timeout=120) as cli:
            cli.post(f"{base}/trabajador/login", data={"cuil": c["cuil"], "clave": claves[c["cuil"]]},
                     follow_redirects=True)
            datos = (CARPETA / c["archivo"]).read_bytes()
            r = cli.post(f"{base}/api/leer", files={"archivo": (c["archivo"], datos, c["mime"])})
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = None
        res = evaluar(r.status_code, cuerpo)
        salida.append({**c, "status": r.status_code, "codigo": (cuerpo or {}).get("codigo", ""),
                       "resultado": res, "ms": round(r.elapsed.total_seconds() * 1000)})
        print(f"  {c['archivo']:24} {r.status_code} {(cuerpo or {}).get('codigo', ''):14} {res}")
    print("VEREDICTO:", "NO APROBADO" if any(s["resultado"] == "FALLA" for s in salida) else "APROBADO")
    return salida


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["generar"]:
        for c in generar():
            print(f"  {c['archivo']:24} {c['que_prueba']}")
    elif args[:1] == ["enviar"] and "--base-url" in args:
        base = args[args.index("--base-url") + 1].rstrip("/")
        if "mitrabajo.onrender.com" in base or "mitrabajo-demo" in base:
            raise SystemExit("Nunca contra la demo.")
        enviar(base, "--si" in args)
    else:
        print(__doc__)
