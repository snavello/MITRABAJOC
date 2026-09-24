"""¿Tapar los datos personales empeora la lectura del recibo?
(PLAN_ENMASCARADO.md, bloque 4 -- el criterio: cero diferencias en importes y
en la clasificación de cada línea.)

Lee cada recibo TRES veces con el MISMO modelo: el original y el tapado (modo
activo, sin nada conocido de antemano, como el aprendizaje del admin; y con
la identidad conocida, como el afiliado). Compara con las mismas funciones del
banco de pruebas (`extractor.comparar_lineas` y `resumen_comparable`) y
verifica que la identidad rearmada sea la que leyó la IA en el original.

**Gasta créditos de la API** (3 llamadas por recibo) y no registra nada en la
base: es una herramienta de desarrollo, se corre a mano. Necesita Linux para
las fotos (Tesseract): en Windows, dentro de Docker -- ver LEEME abajo.

    python medicion_enmascarado/medir.py CARPETA_O_PDFS... [--modelo M] [--salida RESULTADO.md]

Para los 10 sintéticos + el digital ficticio, desde Windows:

    docker run --rm -v "$PWD:/app" -v "<carpeta sinteticos>:/sinteticos:ro" -w /app \\
      -e ANTHROPIC_API_KEY python:3.12.8-slim-bookworm bash -c \\
      "pip install -q -r medicion_enmascarado/requisitos.txt && \\
       python medicion_enmascarado/medir.py /sinteticos datos_prueba/enmascarado/recibo_digital_ficticio.pdf"
"""
import argparse
import base64
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import enmascarado as E  # noqa: E402
import extractor  # noqa: E402
import lectores  # noqa: E402
import preparacion  # noqa: E402

# Identidad de los datos de prueba, para el caso "afiliado" (con conocidos).
CONOCIDOS = {
    "recibo_digital_ficticio": E.Conocidos("27287654311", "GONZÁLEZ PEÑA, MARÍA JOSÉ"),
}
SINTETICO = E.Conocidos("27999999999", "NIEVES, JULIA")


def _png(img) -> tuple[str, str]:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/png"


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _letras(v) -> str:
    return E._letras(str(v or ""))


def _leer(contenido, imagen, aviso, modelo):
    t = time.perf_counter()
    datos, uso = extractor.extraer(contenido, "application/pdf", modelo, imagen, aviso_enmascarado=aviso)
    return datos, uso, time.perf_counter() - t


def medir_uno(ruta: Path, modelo: str) -> dict:
    contenido = ruta.read_bytes()
    conocidos = CONOCIDOS.get(ruta.stem, SINTETICO)
    # El original: la primera página a 150 dpi, como la prepara la app hoy.
    original = _png(lectores.imagen_pdf(contenido, 0))
    prep = preparacion.preparar(contenido, "application/pdf", conocidos, "activo")
    prep_sin = preparacion.preparar(contenido, "application/pdf", None, "activo")
    with ThreadPoolExecutor(3) as ex:
        f_orig = ex.submit(_leer, contenido, original, False, modelo)
        f_tap = ex.submit(_leer, contenido, prep.imagen, prep.tapado, modelo)
        f_sin = ex.submit(_leer, contenido, prep_sin.imagen, prep_sin.tapado, modelo)
        d_orig, u_orig, t_orig = f_orig.result()
        d_tap, u_tap, t_tap = f_tap.result()
        d_sin, u_sin, t_sin = f_sin.result()
    preparacion.rearmar_recibo(d_tap, prep.analisis, conocidos)
    preparacion.rearmar_recibo(d_sin, prep_sin.analisis, None)

    comp = extractor.comparar_lineas([("original", d_orig), ("tapado", d_tap), ("tapado sin conocidos", d_sin)])
    tot = lambda d: {k: (d.get("totales_impresos") or {}).get(k) for k in ("remuneraciones", "descuentos", "neto")}
    emp = lambda d: d.get("empleado") or {}
    empr = lambda d: d.get("empleador") or {}
    identidad = {
        "cuil": [_digitos(emp(d).get("cuil")) for d in (d_orig, d_tap, d_sin)],
        "cuit": [_digitos(empr(d).get("cuit")) for d in (d_orig, d_tap, d_sin)],
        "nombre": [emp(d).get("apellido_nombre") for d in (d_orig, d_tap, d_sin)],
        "legajo": [emp(d).get("legajo") for d in (d_orig, d_tap, d_sin)],
        "empleador": [empr(d).get("nombre") for d in (d_orig, d_tap, d_sin)],
    }
    return {
        "archivo": ruta.name,
        "camino": prep.registro.get("camino"), "cajas": prep.registro.get("cajas"),
        "fugas": prep.registro.get("fugas"), "tapado": prep.tapado,
        "totales": [tot(d) for d in (d_orig, d_tap, d_sin)],
        "periodo": [d.get("periodo") for d in (d_orig, d_tap, d_sin)],
        "categoria": [emp(d).get("categoria") for d in (d_orig, d_tap, d_sin)],
        "lineas": [len(d.get("lineas") or []) for d in (d_orig, d_tap, d_sin)],
        "lineas_distintas": comp["distintas"], "lineas_total": comp["total"],
        "filas_distintas": [f for f in comp["filas"] if f["difiere"]],
        "alerta": [(d.get("alerta_adulteracion") or {}).get("detectada") for d in (d_orig, d_tap, d_sin)],
        "identidad": identidad,
        "tokens_entrada": [u_orig["tokens_entrada"], u_tap["tokens_entrada"], u_sin["tokens_entrada"]],
        "segundos": [round(t_orig, 1), round(t_tap, 1), round(t_sin, 1)],
        "json": {"original": d_orig, "tapado": d_tap, "tapado_sin_conocidos": d_sin},
    }


def _misma_identidad(r) -> dict:
    """¿El rearmado devolvió lo mismo que leyó la IA en el original?"""
    i = r["identidad"]
    return {
        "cuil": i["cuil"][0] == i["cuil"][1],
        "cuit": i["cuit"][0] == i["cuit"][1] == i["cuit"][2],
        "nombre": _letras(i["nombre"][0]) == _letras(i["nombre"][1]),
    }


def informe(res: list, modelo: str) -> str:
    l = [f"# Medición del enmascarado — {time.strftime('%Y-%m-%d %H:%M')}", "",
         f"Modelo: `{modelo}`. Cada recibo se leyó tres veces: **original**, **tapado** "
         "(con la identidad conocida, como el afiliado) y **tapado sin conocidos** "
         "(como el aprendizaje del admin). Criterio del plan: cero diferencias en "
         "importes y en la clasificación de cada línea.", "",
         "| Recibo | Camino | Zonas | Fugas | Totales iguales | Líneas (orig/tap/sin) | Líneas distintas | Período y categoría | Identidad rearmada (CUIL/CUIT/nombre) | Alerta adulteración |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        if "error" in r:
            l.append(f"| {r['archivo']} | — | — | — | error: {r['error']} | | | | | |")
            continue
        tot_ok = r["totales"][0] == r["totales"][1] == r["totales"][2]
        pc_ok = (len(set(map(str, r["periodo"]))) == 1 and len({_letras(c) for c in r["categoria"]}) == 1)
        mi = _misma_identidad(r)
        l.append(f"| {r['archivo']} | {r['camino']} | {r['cajas']} | {r['fugas']} | "
                 f"{'sí' if tot_ok else 'NO ' + json.dumps(r['totales'])} | {'/'.join(map(str, r['lineas']))} | "
                 f"{r['lineas_distintas']} de {r['lineas_total']} | {'sí' if pc_ok else 'NO'} | "
                 f"{'/'.join('sí' if v else 'NO' for v in mi.values())} | {'/'.join(str(a) for a in r['alerta'])} |")
    l += ["", "## Líneas que difieren", ""]
    hubo = False
    for r in res:
        for f in r.get("filas_distintas", []):
            hubo = True
            celdas = " · ".join(f"{n}: {c['valor']}" for n, c in zip(("original", "tapado", "sin conocidos"), f["celdas"]))
            l.append(f"- **{r['archivo']}** `{f['codigo']}` {f['descripcion']} ({f['importe']}): {celdas}")
    if not hubo:
        l.append("Ninguna.")
    l += ["", "## Identidad leída y rearmada", ""]
    for r in res:
        if "identidad" in r:
            l.append(f"- **{r['archivo']}**: " + "; ".join(
                f"{k}: {' / '.join(str(x) for x in v)}" for k, v in r["identidad"].items()))
    return "\n".join(l) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rutas", nargs="+", type=Path)
    ap.add_argument("--modelo", default=extractor.MODELO)
    ap.add_argument("--salida", type=Path, default=Path(__file__).parent / "RESULTADO.md")
    a = ap.parse_args()
    archivos = []
    for r in a.rutas:
        archivos += sorted(r.glob("*.pdf")) if r.is_dir() else [r]
    res = []
    for ruta in archivos:
        try:
            r = medir_uno(ruta, a.modelo)
        except Exception as e:
            r = {"archivo": ruta.name, "error": f"{type(e).__name__}: {e}"[:200]}
        res.append(r)
        print(f"{ruta.name}: " + (r.get("error") or
              f"líneas distintas {r['lineas_distintas']}/{r['lineas_total']}, totales "
              f"{'iguales' if r['totales'][0] == r['totales'][1] == r['totales'][2] else 'DISTINTOS'}"), flush=True)
    a.salida.write_text(informe(res, a.modelo), encoding="utf-8")
    (a.salida.with_suffix(".json")).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"informe: {a.salida}")


if __name__ == "__main__":
    main()
