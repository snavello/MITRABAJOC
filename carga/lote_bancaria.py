# -*- coding: utf-8 -*-
"""El lote de 600 recibos bancarios de prueba (PLAN_PRUEBAS_BANCARIA.md, §3).

Los recibos viven comprimidos en `datos_prueba/bancaria/parte{1,2,3}.zip`
(datos ficticios, lo dice el pie de cada uno). Este módulo es lo único que
sabe dónde están y cómo se leen: lo usan `preparar_bancaria.py`,
`probar_lote_bancaria.py`, `archivos_limite.py` y, a través de la carpeta
extraída, `k6/test4_bancaria.js`.

Uso:
    python carga/lote_bancaria.py extraer     # zips -> carga/recibos_bancaria/
    python carga/lote_bancaria.py verificar   # cuenta, archivos y CUIL

No toca ninguna base ni ningún servidor.
"""
from __future__ import annotations

import csv
import sys
import zipfile
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ZIPS = sorted((RAIZ / "datos_prueba" / "bancaria").glob("parte*.zip"))
DESTINO = Path(__file__).resolve().parent / "recibos_bancaria"
MANIFIESTO = DESTINO / "manifest.csv"
EMPLEADOS = DESTINO / "empleados.csv"

# Los errores que el lote trae a propósito y lo que se espera de la app hoy.
# CUIL_DV_INVALIDO: el recibo imprime el CUIL con el dígito verificador mal.
# El enmascarado no lo corta (un DV inválido no es "otra persona"), pero el
# chequeo después de la IA compara texto contra la sesión y SÍ lo corta con
# E-RECIBO-04. Si eso es lo que se quiere es una decisión pendiente del plan
# de ejecución; mientras tanto se espera lo que la app hace.
ESPERADO_POR_ERROR = {
    "": "OK",
    "NETO_INCORRECTO": "CON_DISCREPANCIAS",
    "CUIL_DV_INVALIDO": "E-RECIBO-04",
}

MIME = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png"}


def extraer(destino: Path = DESTINO) -> int:
    """Descomprime los tres zips en `destino`. Idempotente. Devuelve cuántos
    archivos quedaron. Rechaza rutas que salgan de la carpeta (zip slip)."""
    if not ZIPS:
        raise SystemExit("No hay zips en datos_prueba/bancaria/.")
    destino.mkdir(parents=True, exist_ok=True)
    base = destino.resolve()
    n = 0
    for z in ZIPS:
        with zipfile.ZipFile(z) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                final = (destino / info.filename).resolve()
                if base not in final.parents:
                    raise SystemExit(f"{z.name}: ruta fuera de la carpeta: {info.filename}")
                final.parent.mkdir(parents=True, exist_ok=True)
                final.write_bytes(zf.read(info))
                n += 1
    escribir_k6(destino)
    return n


def escribir_k6(destino: Path = DESTINO) -> Path:
    """`k6.json`: lo que `k6/test4_bancaria.js` necesita de cada recibo, sin
    parsear CSV en JavaScript (los nombres llevan comas)."""
    import json
    filas = _leer_csv(destino / "manifest.csv")
    datos = [{"archivo": f["archivo"], "cuil": solo_digitos(f["cuil"]),
              "formato": f["formato"], "banco": f["archivo"].split("/")[0],
              "error": f.get("error_intencional") or ""} for f in filas]
    ruta = destino / "k6.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return ruta


def _leer_csv(ruta: Path) -> list[dict]:
    if not ruta.exists():
        raise SystemExit(f"Falta {ruta}. Correr antes: python carga/lote_bancaria.py extraer")
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def manifiesto() -> list[dict]:
    return _leer_csv(MANIFIESTO)


def empleados() -> list[dict]:
    return _leer_csv(EMPLEADOS)


def solo_digitos(cuil: str) -> str:
    return "".join(c for c in (cuil or "") if c.isdigit())


# Lo que el lote paga como no remunerativo: $ 120.000 en los 600 recibos
# (verificado leyendo los 480 PDF el 2026-11-03).
NO_REMUNERATIVO = 120000.0


def supera_tope(fila: dict) -> bool:
    """¿El remunerativo de este recibo pasa el tope de la seguridad social?
    El generador del lote calculó los aportes sobre el sueldo completo
    siempre, así que en esos recibos la app marca, con razón, que se retuvo de
    más (alerta `tope_no_aplicado` + diferencias en las fórmulas). Son 271 de
    los 600: prueba piloto del 2026-11-03."""
    import grilla_bancaria
    t = grilla_bancaria.tope_ss(fila["periodo"])
    return bool(t) and float(fila["total_haberes"]) - NO_REMUNERATIVO > float(t["maximo"])


def esperado(fila: dict) -> str:
    """Lo que la app debería concluir de este recibo. Un recibo que supera el
    tope tiene un error real (aportes sin tope) aunque el manifiesto no lo
    marque como error a propósito."""
    error = fila.get("error_intencional") or ""
    if not error and supera_tope(fila):
        return "CON_DISCREPANCIAS"
    return ESPERADO_POR_ERROR.get(error, "CON_DISCREPANCIAS")


def muestra(filas: list[dict], n: int, incluir_errores: bool = True) -> list[dict]:
    """`n` recibos repartidos parejo por banco y por mes, siempre los mismos
    (determinista: se puede repetir la corrida con otro modelo y comparar
    recibo por recibo). Los que traen un error a propósito entran siempre."""
    if n <= 0 or n >= len(filas):
        return list(filas)
    errores = [f for f in filas if f.get("error_intencional")] if incluir_errores else []
    resto = [f for f in filas if f not in errores]
    por_banco: dict[str, list] = {}
    for f in sorted(resto, key=lambda f: (f["periodo"], f["archivo"])):
        por_banco.setdefault(f["archivo"].split("/")[0], []).append(f)
    elegidos = list(errores)
    i = 0
    while len(elegidos) < n and any(por_banco.values()):
        for banco in sorted(por_banco):
            if por_banco[banco] and len(elegidos) < n:
                # Paso largo para recorrer personas y meses distintos.
                lista = por_banco[banco]
                elegidos.append(lista.pop((i * 7) % len(lista)))
        i += 1
    return sorted(elegidos, key=lambda f: f["archivo"])


def muestra_azar(filas: list[dict], n: int, semilla: int) -> list[dict]:
    """`n` recibos al azar, repetibles con la misma `semilla` (así el alta de
    sus dueños y la corrida eligen exactamente los mismos)."""
    import random
    return sorted(random.Random(semilla).sample(list(filas), min(n, len(filas))),
                  key=lambda f: f["archivo"])


def verificar() -> list[str]:
    """Problemas del lote extraído; lista vacía = está todo."""
    import cuit
    problemas = []
    filas = manifiesto()
    faltan = [f["archivo"] for f in filas if not (DESTINO / f["archivo"]).exists()]
    if faltan:
        problemas.append(f"{len(faltan)} archivos del manifiesto no están (ej. {faltan[0]})")
    malos = {f["cuil"] for f in filas if not cuit.es_valido(solo_digitos(f["cuil"]))}
    if malos:
        problemas.append(f"CUIL que no cumplen el módulo 11: {sorted(malos)}")
    sin_empleado = {f["cuil"] for f in filas} - {e["cuil"] for e in empleados()}
    if sin_empleado:
        problemas.append(f"CUIL del manifiesto que no están en empleados.csv: {sorted(sin_empleado)}")
    return problemas


def _resumen():
    filas = manifiesto()
    c = Counter
    print(f"{len(filas)} recibos, {len({f['cuil'] for f in filas})} personas")
    print("por banco:  ", dict(c(f["archivo"].split("/")[0] for f in filas)))
    print("por formato:", dict(c(f["formato"] for f in filas)))
    print("errores:    ", dict(c(f["error_intencional"] or "ninguno" for f in filas)))


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ))
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    if orden == "extraer":
        print(f"{extraer()} archivos en {DESTINO}")
        _resumen()
    elif orden == "verificar":
        p = verificar()
        _resumen()
        print("\n".join(p) if p else "OK: el lote está completo.")
        sys.exit(1 if p else 0)
    else:
        print(__doc__)
