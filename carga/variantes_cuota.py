# -*- coding: utf-8 -*-
"""¿Cómo etiqueta la IA la cuota sindical cuando el banco la llama distinto?

Prueba de variantes del lote bancario (PLAN_PRUEBAS_BANCARIA.md): arma
recibos ficticios iguales salvo el NOMBRE de la línea de cuota («Cuota
gremial», «Aporte sindical», «Asoc. Bancaria», «Aporte solidario»...) y, en
uno, dos líneas trampa que NO son la cuota (sepelio y préstamo). Los sube a
la app real con la sesión de su dueño (`/api/leer`, solo lectura: no valida
ni guarda el recibo) y lista qué etiqueta (`categoria_universal`) le puso la
IA a cada línea de descuento. **Gasta créditos** (una lectura por recibo).

Uso:
    python carga/variantes_cuota.py generar                     # -> carga/variantes_cuota/
    python carga/variantes_cuota.py enviar --base-url https://mitrabajo-pruebas.onrender.com --si
El dueño de los recibos es el primer CUIL del lote (`--cuil`, default el de
BBVA 20185331424) y su clave sale de `carga/usuarios_bancaria.csv`.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lote_bancaria as L  # noqa: E402

CARPETA = Path(__file__).resolve().parent / "variantes_cuota"
USUARIOS = Path(__file__).resolve().parent / "usuarios_bancaria.csv"
FUENTE = Path(__file__).resolve().parent.parent / "static" / "fonts" / "manrope.woff2"
CUIL = "20185331424"

# (archivo, nombre de la línea de cuota, ¿es la cuota de afiliación?, líneas extra)
VARIANTES = [
    ("v1_cuota_gremial", "Cuota gremial", True, []),
    ("v2_aporte_sindical", "Aporte sindical", True, []),
    ("v3_asoc_bancaria", "Asoc. Bancaria", True, []),
    ("v4_la_bancaria", "La Bancaria 2%", True, []),
    ("v5_cuota_afiliado", "Cuota afiliado AB", True, []),
    ("v6_retencion_gremio", "Retención gremio", True, []),
    ("v7_aporte_solidario", "Aporte solidario CCT 18/75", False, []),
    ("v8_con_trampas", "Cuota sindical", True,
     [("530", "Seguro de sepelio Asoc. Bancaria", 1500.00),
      ("540", "Cuota préstamo personal", 12000.00)]),
]

BASICO, ANTIG = 2500000.00, 250000.00


def _pesos(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generar(carpeta: Path = CARPETA) -> list[dict]:
    from PIL import Image, ImageDraw, ImageFont
    carpeta.mkdir(parents=True, exist_ok=True)
    emp = next(e for e in L.empleados() if L.solo_digitos(e["cuil"]) == CUIL)
    f = ImageFont.truetype(str(FUENTE), 26)
    fb = ImageFont.truetype(str(FUENTE), 34)
    remun = BASICO + ANTIG
    casos = []
    for archivo, cuota, es_cuota, extras in VARIANTES:
        img = Image.new("RGB", (1240, 1754), "white")
        d = ImageDraw.Draw(img)
        y = 80
        d.text((80, y), "BBVA  RECIBO DE HABERES", font=fb, fill="black"); y += 60
        for t in ("Período: Agosto 2026",
                  f"Empleador: {emp['banco']}   CUIT: {emp['cuit_banco']}",
                  f"Apellido y nombre: {emp['nombre']}   CUIL: {emp['cuil']}",
                  f"Legajo: {emp['legajo']}   Categoría: {emp['categoria']} (CCT 18/75)",
                  "Fecha de pago: 01/09/2026"):
            d.text((80, y), t, font=f, fill="black"); y += 42
        y += 30
        d.text((80, y), "Cód.  Concepto", font=f, fill="black")
        d.text((760, y), "Haberes", font=f, fill="black")
        d.text((980, y), "Descuentos", font=f, fill="black"); y += 46
        d.line((80, y, 1160, y), fill="black", width=2); y += 14
        filas = [("001", "Sueldo básico", BASICO, None), ("010", "Antigüedad (5 años)", ANTIG, None),
                 ("501", "Jubilación 11%", None, remun * 0.11), ("502", "Ley 19.032 (PAMI) 3%", None, remun * 0.03),
                 ("503", "Obra social 3%", None, remun * 0.03), ("510", cuota, None, remun * 0.02)]
        filas += [(c, n, None, i) for c, n, i in extras]
        desc = 0.0
        for cod, nom, hab, des in filas:
            d.text((80, y), f"{cod}   {nom}", font=f, fill="black")
            if hab is not None:
                d.text((760, y), _pesos(hab), font=f, fill="black")
            if des is not None:
                d.text((980, y), _pesos(des), font=f, fill="black")
                desc += des
            y += 44
        y += 20
        d.line((80, y, 1160, y), fill="black", width=2); y += 20
        d.text((80, y), f"Total haberes: $ {_pesos(remun)}    Total descuentos: $ {_pesos(desc)}",
               font=f, fill="black"); y += 50
        d.text((80, y), f"NETO A COBRAR: $ {_pesos(remun - desc)}", font=fb, fill="black"); y += 80
        d.text((80, y), "Documento de prueba - datos ficticios.", font=f, fill="gray")
        img.save(carpeta / f"{archivo}.jpg", "JPEG", quality=90)
        casos.append({"archivo": f"{archivo}.jpg", "cuota": cuota, "es_cuota": es_cuota,
                      "trampas": [n for _, n, _ in extras]})
    (carpeta / "casos.json").write_text(json.dumps(casos, ensure_ascii=False, indent=1), encoding="utf-8")
    return casos


def enviar(base: str) -> list[dict]:
    import httpx
    casos = json.loads((CARPETA / "casos.json").read_text(encoding="utf-8"))
    with open(USUARIOS, encoding="utf-8") as f:
        clave = {r["cuil"]: r["clave"] for r in csv.DictReader(f)}[CUIL]
    salida = []
    with httpx.Client(timeout=120) as c:
        c.post(f"{base}/trabajador/login", data={"cuil": CUIL, "clave": clave}, follow_redirects=True)
        for caso in casos:
            t0 = time.monotonic()
            r = c.post(f"{base}/api/leer", files={"archivo": (caso["archivo"],
                       (CARPETA / caso["archivo"]).read_bytes(), "image/jpeg")})
            ms = round((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                salida.append({**caso, "error": r.text[:200], "ms": ms})
                continue
            recibo = r.json()["recibo"]
            if (recibo.get("empleado") or {}).get("apellido_nombre") == "Demo Carga, Trabajador":
                raise SystemExit("El servidor tiene el mock prendido: no hubo lectura real.")
            lineas = [{"descripcion": ln.get("descripcion"), "seccion": ln.get("seccion"),
                       "importe": ln.get("importe"), "categoria": ln.get("categoria_universal")}
                      for ln in recibo.get("lineas", []) if ln.get("seccion") == "descuentos"]
            salida.append({**caso, "lineas": lineas, "recibo": recibo, "ms": ms})
    return salida


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["generar"]:
        for c in generar():
            print(f"  {c['archivo']:28} {c['cuota']}")
    elif args[:1] == ["enviar"] and "--base-url" in args:
        base = args[args.index("--base-url") + 1].rstrip("/")
        if "mitrabajo.onrender.com" in base or "mitrabajo-demo" in base:
            raise SystemExit("Nunca contra la demo.")
        if "--si" not in args:
            print(f"Ensayo: {len(VARIANTES)} lecturas reales contra {base}. Con --si se mandan.")
            sys.exit(0)
        res = enviar(base)
        (CARPETA / "resultado.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        for r in res:
            print(f"== {r['archivo']} ({r['ms']} ms)")
            for ln in r.get("lineas", []):
                print(f"   {str(ln['descripcion']):38} -> {ln['categoria']}")
            if "error" in r:
                print("   ERROR", r["error"])
    else:
        print(__doc__)
