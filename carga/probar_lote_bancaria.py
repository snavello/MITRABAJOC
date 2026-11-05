# -*- coding: utf-8 -*-
"""Exactitud con el lote bancario y comparación entre modelos
(PLAN_PRUEBAS_BANCARIA.md, A1 y A4).

Sube cada recibo del lote a la app REAL (`/api/leer` + `/api/validar`), con la
sesión de su propio CUIL, y compara lo que la app leyó y concluyó contra el
manifiesto. **Gasta créditos de la IA**: sin `--si` solo muestra qué haría y
cuánto costaría. A mano, nunca en CI, nunca contra la demo.

El modelo NO se elige acá: es el que tenga puesto la app en `/plataforma` →
Uso de IA → Modelos → "Lectura de recibos". La corrida lleva una `--etiqueta`
(ej. `sonnet-5-5`) para poder comparar después; además
se lee de UsoIA qué modelo corrió de verdad, los tokens y el costo, si se da
`USO_IA_DATABASE_URL` (la base del entorno medido, no la local). Si el
servidor responde con el mock (`MOCK_EXTRACTOR=1`) la corrida se corta.

Uso:
    python carga/lote_bancaria.py extraer
    python carga/probar_lote_bancaria.py --base-url https://mitrabajo-pruebas.onrender.com \
        --etiqueta sonnet-5-5 --muestra 60                   # ensayo: plan y costo estimado
    ... --si                                               # corre
    python carga/probar_lote_bancaria.py --comparar carga/log/lote_bancaria/*.csv

Opciones: --muestra N (repartida por banco y mes, siempre la misma; 0 = los
600), --banco bbva, --solo-errores, --paralelo K (default 2), --sin-validar
(solo lectura), --modelo-estimado claude-haiku-5-5 (para el costo del ensayo).

Cada corrida deja `carga/log/lote_bancaria/AAAA-MM-DD_HHMM_<etiqueta>.csv`
(una fila por recibo) y un `.json` con el resumen. Lo que escribe en
Pruebas (recibos verificados, conceptos pendientes) se borra con
`preparar_bancaria.py --limpiar --si`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lote_bancaria as L  # noqa: E402

SALIDA = Path(__file__).resolve().parent / "log" / "lote_bancaria"
USUARIOS = Path(__file__).resolve().parent / "usuarios_bancaria.csv"
TOLERANCIA = 1.0          # pesos, como la de los totales de la app
HOSTS_PROHIBIDOS = ("mitrabajo.onrender.com", "mitrabajo-demo")
# Tokens por recibo para el costo del ENSAYO (orden de magnitud: imagen +
# prompt de entrada, JSON de ~17 líneas de salida). El costo real sale de UsoIA.
TOKENS_ESTIMADOS = (5000, 2200)

# El nombre que devuelve extractor._RECIBO_MOCK: si aparece, no hubo lectura real.
MOCK_NOMBRE = "Demo Carga, Trabajador"


PERMITIR_MOCK = False     # --permitir-mock: solo para probar el script contra un servidor local


class CorrioElMock(Exception):
    """El servidor tiene MOCK_EXTRACTOR=1: la corrida no mide nada."""


CAMPOS = ["archivo", "banco", "formato", "cuil", "periodo", "error_intencional",
          "esperado", "obtenido", "acierto", "lectura_ok", "dif_haberes",
          "dif_descuentos", "dif_neto", "periodo_ok", "cuil_leido",
          "discrepancias", "ms_leer", "ms_validar", "http_leer", "etiqueta",
          "tokens_entrada", "tokens_salida", "tokens_cache_lectura", "tokens_cache_escritura"]


# ---------------------------------------------------------------- puro ----
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _dif(leido, esperado):
    a, b = _num(leido), _num(esperado)
    return None if a is None or b is None else round(abs(a) - abs(b), 2)


def clasificar(fila: dict, leer: dict | None, codigo_error: str | None,
               validar: dict | None) -> dict:
    """Una fila del resultado a partir de lo que devolvió la app. Puro.

    `obtenido` es el estado de `/api/validar` (OK / CON_DISCREPANCIAS) o el
    código de error de `/api/leer`. `lectura_ok`: los tres totales impresos que
    la app sumó de las líneas coinciden con el manifiesto (±$1) y el período
    también: separa "leyó mal" de "validó mal"."""
    esperado = L.esperado(fila)
    r = {"archivo": fila["archivo"], "banco": fila["archivo"].split("/")[0],
         "formato": fila["formato"], "cuil": L.solo_digitos(fila["cuil"]),
         "periodo": fila["periodo"], "error_intencional": fila.get("error_intencional", ""),
         "esperado": esperado}
    if codigo_error:
        r.update(obtenido=codigo_error, lectura_ok=False)
    else:
        recibo = (leer or {}).get("recibo") or {}
        tot = (leer or {}).get("totales_leidos") or {}
        impresos = recibo.get("totales_impresos") or {}
        # Para el neto manda el IMPRESO (es lo que trae el error a propósito);
        # haberes y descuentos, la suma de las líneas.
        r["dif_haberes"] = _dif(tot.get("ingresos"), fila["total_haberes"])
        r["dif_descuentos"] = _dif(tot.get("descuentos"), fila["total_descuentos"])
        r["dif_neto"] = _dif(impresos.get("neto"), fila["neto_impreso"])
        r["periodo_ok"] = (recibo.get("periodo") or "") == fila["periodo"]
        r["cuil_leido"] = L.solo_digitos((recibo.get("empleado") or {}).get("cuil") or "")
        difs = [r["dif_haberes"], r["dif_descuentos"], r["dif_neto"]]
        r["lectura_ok"] = r["periodo_ok"] and all(d is not None and abs(d) <= TOLERANCIA for d in difs)
        if validar is not None:
            r["obtenido"] = validar.get("estado", "")
            r["discrepancias"] = "|".join(sorted({d.get("tipo", "") for d in
                                                  validar.get("discrepancias") or []}))
        else:
            r["obtenido"] = "LEIDO"
    r["acierto"] = r["obtenido"] == esperado or (r["obtenido"] == "LEIDO" and esperado != "E-RECIBO-04")
    return r


def resumir(filas: list[dict]) -> dict:
    """Los números de una corrida. Puro."""
    n = len(filas)
    if not n:
        return {"recibos": 0}
    tiempos = sorted(f["ms_leer"] for f in filas if f.get("ms_leer"))

    def pct(p):
        return tiempos[min(len(tiempos) - 1, int(p * len(tiempos)))] if tiempos else None
    leidos = [f for f in filas if f["obtenido"] not in ("", None) and not str(f["obtenido"]).startswith("E-")]
    errores_lote = [f for f in filas if f.get("error_intencional")]
    por = {}
    for clave in ("banco", "formato"):
        por[clave] = {}
        for f in filas:
            g = por[clave].setdefault(f[clave], {"recibos": 0, "aciertos": 0, "lectura_ok": 0})
            g["recibos"] += 1
            g["aciertos"] += bool(f["acierto"])
            g["lectura_ok"] += bool(f.get("lectura_ok"))
    return {
        "recibos": n,
        "aciertos": sum(bool(f["acierto"]) for f in filas),
        "leidos": len(leidos),
        "lectura_ok": sum(bool(f.get("lectura_ok")) for f in filas),
        "errores_app": {c: sum(1 for f in filas if f["obtenido"] == c)
                        for c in sorted({f["obtenido"] for f in filas if str(f["obtenido"]).startswith("E-")})},
        "errores_lote_detectados": sum(bool(f["acierto"]) for f in errores_lote),
        "errores_lote": len(errores_lote),
        "ms_leer_p50": statistics.median(tiempos) if tiempos else None,
        "ms_leer_p95": pct(0.95),
        "por": por,
    }


def costo_estimado(n: int, modelo: str) -> float | None:
    import precios_ia
    c = precios_ia.costo_estimado(modelo, *TOKENS_ESTIMADOS)
    return None if c is None else round(c * n, 2)


# --------------------------------------------------------------- red ------
def _login(cliente, base, cuil, clave):
    r = cliente.post(f"{base}/trabajador/login", data={"cuil": cuil, "clave": clave},
                     follow_redirects=True)
    return "/app" in str(r.url)


def probar_uno(base: str, fila: dict, clave: str, validar: bool) -> dict:
    import httpx
    ruta = L.DESTINO / fila["archivo"]
    ext = ruta.suffix.lstrip(".").lower()
    with httpx.Client(timeout=120) as c:
        if not _login(c, base, L.solo_digitos(fila["cuil"]), clave):
            r = clasificar(fila, None, "LOGIN", None)
            r.update(ms_leer=None, http_leer=None)
            return r
        t0 = time.monotonic()
        rl = c.post(f"{base}/api/leer",
                    files={"archivo": (ruta.name, ruta.read_bytes(), L.MIME.get(ext, "application/octet-stream"))})
        ms_leer = round((time.monotonic() - t0) * 1000)
        if rl.status_code != 200:
            try:
                codigo = rl.json().get("codigo") or f"HTTP-{rl.status_code}"
            except ValueError:
                codigo = f"HTTP-{rl.status_code}"
            r = clasificar(fila, None, codigo, None)
            r.update(ms_leer=ms_leer, http_leer=rl.status_code)
            return r
        leido = rl.json()
        if (not PERMITIR_MOCK and
                ((leido.get("recibo") or {}).get("empleado") or {}).get("apellido_nombre") == MOCK_NOMBRE):
            raise CorrioElMock()
        res_val, ms_val = None, None
        if validar:
            t1 = time.monotonic()
            rv = c.post(f"{base}/api/validar", json={
                "recibo": leido["recibo"], "conceptos_nuevos": leido.get("conceptos_nuevos", [])})
            ms_val = round((time.monotonic() - t1) * 1000)
            res_val = rv.json() if rv.status_code == 200 else {"estado": f"HTTP-{rv.status_code}"}
        r = clasificar(fila, leido, None, res_val)
        r.update(ms_leer=ms_leer, ms_validar=ms_val, http_leer=200, _lectura=leido,
                 _t0=t0)
        return r


def _filas_uso_db(inicio: str, cuils: set) -> list | None:
    """Filas de UsoIA (tipo recibo) desde `inicio`, como dicts. Solo con
    `USO_IA_DATABASE_URL` (la base del entorno MEDIDO): el DATABASE_URL de la
    PC o del contenedor es la base local, que no registró nada de esta corrida.
    Sin ella, las filas se pueden traer con un Job de Render y pasarlas en
    `--uso-ia-json` (lista de dicts con las mismas claves)."""
    url = os.getenv("USO_IA_DATABASE_URL")
    if not url:
        return None
    os.environ["DATABASE_URL"] = url
    from sqlmodel import select
    import db
    from db import UsoIA
    with db.get_session() as s:
        filas = s.exec(select(UsoIA).where(UsoIA.tipo == "recibo", UsoIA.fecha >= inicio,
                                           UsoIA.cuil.in_(cuils)).order_by(UsoIA.id)).all()
    return [{"id": u.id, "cuil": u.cuil, "modelo": u.modelo, "tokens_entrada": u.tokens_entrada,
             "tokens_salida": u.tokens_salida, "tokens_cache_lectura": u.tokens_cache_lectura,
             "tokens_cache_escritura": u.tokens_cache_escritura, "precio_entrada": u.precio_entrada,
             "precio_salida": u.precio_salida, "duracion_ms": u.duracion_ms} for u in filas]


def aplicar_uso(resultados: list[dict], filas_uso: list[dict]) -> None:
    """Pone en cada resultado los tokens (con los de caché) de SU llamada: por
    CUIL y en el orden en que se lanzaron. Puro."""
    por_cuil = {}
    for u in sorted(filas_uso, key=lambda u: u.get("id", 0)):
        por_cuil.setdefault(u["cuil"], []).append(u)
    for cuil, rs in _agrupar(resultados).items():
        for r, u in zip(sorted(rs, key=lambda r: r.get("_t0") or 0), por_cuil.get(cuil, [])):
            for k in ("tokens_entrada", "tokens_salida", "tokens_cache_lectura", "tokens_cache_escritura"):
                r[k] = u.get(k, 0)


def _agrupar(resultados):
    g = {}
    for r in resultados:
        g.setdefault(r["cuil"], []).append(r)
    return g


def resumen_uso(filas_uso: list[dict]) -> dict:
    """Por modelo: llamadas, tokens, costo REAL (con caché) y el que habría
    sido SIN caché (todo lo de entrada a precio de entrada)."""
    import precios_ia
    modelos = {}
    for u in filas_uso:
        m = modelos.setdefault(u["modelo"], {"llamadas": 0, "tokens_entrada": 0, "tokens_salida": 0,
                                             "tokens_cache_lectura": 0, "tokens_cache_escritura": 0,
                                             "usd": 0.0, "usd_sin_cache": 0.0, "duracion_ms": []})
        pe, ps = ((u["precio_entrada"], u["precio_salida"]) if u.get("precio_entrada")
                  else (precios_ia.precios(u["modelo"]) or (0, 0)))
        cl, ce = u.get("tokens_cache_lectura", 0) or 0, u.get("tokens_cache_escritura", 0) or 0
        m["llamadas"] += 1
        m["tokens_entrada"] += u["tokens_entrada"]
        m["tokens_salida"] += u["tokens_salida"]
        m["tokens_cache_lectura"] += cl
        m["tokens_cache_escritura"] += ce
        m["usd"] += precios_ia.costo(u["tokens_entrada"], u["tokens_salida"], pe, ps, cl, ce)
        m["usd_sin_cache"] += precios_ia.costo(u["tokens_entrada"] + cl + ce, u["tokens_salida"], pe, ps)
        m["duracion_ms"].append(u["duracion_ms"])
    for m in modelos.values():
        d = m.pop("duracion_ms")
        n = m["llamadas"]
        m["duracion_ms_p50"] = statistics.median(d) if d else None
        m["usd_por_recibo"] = round(m["usd"] / n, 5) if n else None
        m["usd_sin_cache_por_recibo"] = round(m["usd_sin_cache"] / n, 5) if n else None
        m["cache_lectura_por_recibo"] = round(m["tokens_cache_lectura"] / n) if n else None
        m["usd"] = round(m["usd"], 4)
        m["usd_sin_cache"] = round(m["usd_sin_cache"], 4)
    return modelos


def uso_ia_desde(inicio: str, cuils: set) -> dict | None:
    filas = _filas_uso_db(inicio, cuils)
    return None if filas is None else resumen_uso(filas)


# ------------------------------------------------- lecturas crudas -------
def guardar_lectura(etiqueta: str, archivo: str, leido: dict) -> Path:
    """La lectura cruda de la IA (lo que devolvió /api/leer) de un recibo, en
    carga/log/lote_bancaria/<etiqueta>/<banco>/<archivo>.json."""
    ruta = SALIDA / etiqueta / (archivo + ".json")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(leido, ensure_ascii=False, indent=1), encoding="utf-8")
    return ruta


def comparar_lecturas(vieja: Path, nueva: Path) -> str:
    """Lectura contra lectura de los recibos que están en las dos carpetas:
    totales impresos, período, CUIT/CUIL y líneas (extractor.comparar_lineas).
    Un formato de número distinto no cuenta; un código o importe distinto sí."""
    import comparar_lecturas as C
    return C.comparar_carpetas(Path(vieja), Path(nueva))


# ---------------------------------------------------------- comparar ------
def comparar(rutas: list[str]) -> str:
    """Tabla por etiqueta + los recibos en que las corridas no coinciden."""
    corridas = {}
    for ruta in rutas:
        with open(ruta, encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        for f in filas:
            f["acierto"] = f["acierto"] == "True"
            f["lectura_ok"] = f["lectura_ok"] == "True"
            f["ms_leer"] = _num(f["ms_leer"])
        etiqueta = filas[0]["etiqueta"] if filas else Path(ruta).stem
        corridas[etiqueta] = filas
        extra = Path(ruta).with_suffix(".json")
        if extra.exists():
            corridas[etiqueta + "__json"] = json.loads(extra.read_text(encoding="utf-8"))
    lineas = ["| Corrida | Recibos | Aciertos | Lectura exacta | Errores del lote detectados | "
              "Lectura p50 / p95 | USD por recibo | Modelo (UsoIA) |", "|---|---|---|---|---|---|---|---|"]
    etiquetas = [e for e in corridas if not e.endswith("__json")]
    for e in etiquetas:
        r = resumir(corridas[e])
        uso = (corridas.get(e + "__json") or {}).get("uso_ia") or {}
        usd = "; ".join(f"{v['usd_por_recibo']}" for v in uso.values()) or "—"
        mods = ", ".join(uso) or "—"
        lineas.append(f"| {e} | {r['recibos']} | {r['aciertos']} | {r['lectura_ok']} | "
                      f"{r['errores_lote_detectados']}/{r['errores_lote']} | "
                      f"{r['ms_leer_p50']} / {r['ms_leer_p95']} ms | {usd} | {mods} |")
    if len(etiquetas) > 1:
        por_archivo = {}
        for e in etiquetas:
            for f in corridas[e]:
                por_archivo.setdefault(f["archivo"], {})[e] = f["obtenido"] + ("" if f["lectura_ok"] else " (lectura≠)")
        distintos = {a: v for a, v in por_archivo.items() if len(set(v.values())) > 1}
        lineas.append(f"\nRecibos en que las corridas no coinciden: {len(distintos)}")
        for a, v in sorted(distintos.items())[:40]:
            lineas.append(f"- {a}: " + "; ".join(f"{e} = {x}" for e, x in v.items()))
    return "\n".join(lineas)


# -------------------------------------------------------------- main ------
def _claves() -> dict:
    if not USUARIOS.exists():
        raise SystemExit(f"Falta {USUARIOS}: correr antes preparar_bancaria.py --si")
    with open(USUARIOS, encoding="utf-8") as f:
        return {r["cuil"]: r["clave"] for r in csv.DictReader(f) if r["clave"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url")
    ap.add_argument("--etiqueta")
    ap.add_argument("--muestra", type=int, default=60)
    ap.add_argument("--azar", type=int, default=0, help="N recibos al azar (con --semilla)")
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--banco")
    ap.add_argument("--desde", type=int, default=None, help="corte del manifiesto: primer índice (con --hasta)")
    ap.add_argument("--hasta", type=int, default=None, help="corte del manifiesto: índice final (excluido)")
    ap.add_argument("--solo-errores", action="store_true")
    ap.add_argument("--paralelo", type=int, default=2)
    ap.add_argument("--sin-validar", action="store_true")
    ap.add_argument("--modelo-estimado", default="claude-sonnet-5-5")
    ap.add_argument("--si", action="store_true")
    ap.add_argument("--permitir-mock", action="store_true", help="solo para probar el script")
    ap.add_argument("--comparar", nargs="+")
    ap.add_argument("--comparar-lecturas", nargs=2, metavar=("VIEJA", "NUEVA"),
                    help="compara las lecturas crudas guardadas en dos carpetas")
    ap.add_argument("--lista", help="archivo de texto con un recibo del manifiesto por línea "
                                    "(ej. bbva/27350006171_2025-09.pdf): corre exactamente esos")
    ap.add_argument("--uso-ia-json", help="filas de UsoIA traídas con un Job (para los tokens por recibo)")
    a = ap.parse_args(argv)
    if a.comparar:
        print(comparar(a.comparar))
        return
    if a.comparar_lecturas:
        print(comparar_lecturas(*a.comparar_lecturas))
        return
    global PERMITIR_MOCK
    PERMITIR_MOCK = a.permitir_mock
    if not a.base_url or not a.etiqueta:
        ap.error("--base-url y --etiqueta son obligatorios")
    base = a.base_url.rstrip("/")
    if any(h in base for h in HOSTS_PROHIBIDOS):
        raise SystemExit("Nunca contra la demo.")
    filas = L.manifiesto()
    if a.banco:
        filas = [f for f in filas if f["archivo"].startswith(a.banco + "/")]
    if a.solo_errores:
        filas = [f for f in filas if f.get("error_intencional")]
    if a.lista:
        pedidos = [l.strip() for l in Path(a.lista).read_text(encoding="utf-8").splitlines() if l.strip()]
        por_archivo = {f["archivo"]: f for f in filas}
        faltan = [p_ for p_ in pedidos if p_ not in por_archivo]
        if faltan:
            raise SystemExit(f"No están en el manifiesto: {faltan[:5]}")
        filas = [por_archivo[p_] for p_ in pedidos]
    elif a.desde is not None or a.hasta is not None:
        # Corte determinista sobre el orden del manifiesto (sin muestreo).
        filas = filas[a.desde or 0:a.hasta]
    else:
        filas = L.muestra_azar(filas, a.azar, a.semilla) if a.azar else L.muestra(filas, a.muestra)
    claves = _claves()
    sin_clave = [f for f in filas if L.solo_digitos(f["cuil"]) not in claves]
    filas = [f for f in filas if L.solo_digitos(f["cuil"]) in claves]
    est = costo_estimado(len(filas), a.modelo_estimado)
    print(f"{len(filas)} recibos contra {base} (etiqueta {a.etiqueta}); "
          f"{len(sin_clave)} sin clave se saltean. Costo estimado con {a.modelo_estimado}: "
          f"US$ {est if est is not None else '?'} (orden de magnitud).")
    if not a.si:
        print("Ensayo: no se subió nada. Con --si corre.")
        return
    import fechas
    inicio = fechas.ahora().strftime("%Y-%m-%d %H:%M")
    try:
        with ThreadPoolExecutor(max_workers=max(1, a.paralelo)) as ex:
            resultados = list(ex.map(
                lambda f: probar_uno(base, f, claves[L.solo_digitos(f["cuil"])], not a.sin_validar), filas))
    except CorrioElMock:
        raise SystemExit("El servidor respondió con el mock (MOCK_EXTRACTOR=1): no hubo lectura "
                         "real. Apagarlo en Render y volver a correr.")
    for r in resultados:
        r["etiqueta"] = a.etiqueta
        lectura = r.pop("_lectura", None)
        if lectura is not None:
            guardar_lectura(a.etiqueta, r["archivo"], lectura)
    filas_uso = _filas_uso_db(inicio, {r["cuil"] for r in resultados})
    if filas_uso is None and a.uso_ia_json:
        filas_uso = json.loads(Path(a.uso_ia_json).read_text(encoding="utf-8"))
    if filas_uso:
        aplicar_uso(resultados, filas_uso)
    for r in resultados:
        r.pop("_t0", None)
    SALIDA.mkdir(parents=True, exist_ok=True)
    nombre = f"{inicio.replace(' ', '_').replace(':', '')}_{a.etiqueta}"
    with open(SALIDA / f"{nombre}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        w.writeheader()
        w.writerows(resultados)
    resumen = resumir(resultados)
    resumen["uso_ia"] = resumen_uso(filas_uso) if filas_uso else None
    resumen.update(etiqueta=a.etiqueta, base_url=base, inicio=inicio)
    if resumen["uso_ia"] and "mock" in resumen["uso_ia"]:
        resumen["invalida"] = "corrió el mock (MOCK_EXTRACTOR=1): no hubo lectura real"
    (SALIDA / f"{nombre}.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(json.dumps({k: v for k, v in resumen.items() if k != "por"}, ensure_ascii=False, indent=1))
    print(f"Resultados en {SALIDA / nombre}.csv")


if __name__ == "__main__":
    main()
