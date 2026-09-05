"""Set de aceptación del prompt del Asistente del Panel (docs/ASISTENTE_PANEL.md §5).

Corre las frases de medicion_asistente/frases.json contra la API REAL de
Anthropic, sobre el sindicato sintético de test_asistente.py (SQLite
temporal, Docker no hace falta), y compara lo que el modelo aplicó con lo
esperado. GASTA CRÉDITOS (unos centavos por corrida): se corre a mano cada
vez que se toque el prompt, el modelo o el esquema de la herramienta,
nunca en CI.

  .venv/Scripts/python.exe probar_asistente.py                 # config real: esfuerzo bajo
  .venv/Scripts/python.exe probar_asistente.py --sin-thinking  # para comparar latencia
  .venv/Scripts/python.exe probar_asistente.py --solo 16,20    # frases puntuales (1-based)
  .venv/Scripts/python.exe probar_asistente.py --hilos 1       # de a una, para leer con calma

Deja el detalle en medicion_asistente/ultima_corrida.json.
"""
import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.dirname(os.path.abspath(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(RAIZ, ".env"))      # la ANTHROPIC_API_KEY real
os.environ["DATABASE_URL"] = ""              # SQLite temporal, no el Postgres local
os.chdir(RAIZ)
sys.path.insert(0, RAIZ)

import test_asistente as fx                  # noqa: E402  (arma el sindicato sintético)
import asistente                             # noqa: E402
import dashboard                             # noqa: E402

HOY = date.today()
PRECIO_ENTRADA, PRECIO_SALIDA = 2.0 / 1e6, 10.0 / 1e6   # USD por token, claude-sonnet-5


def periodo_esperado(clave: str) -> list:
    """(desde, hasta) esperados; para 'ultimos_N' se aceptan las dos lecturas
    (N días contando hoy, o N días hacia atrás)."""
    if clave == "conservar":
        return [(fx.ESTADO_BASE["desde"], fx.ESTADO_BASE["hasta"])]
    if clave == "hoy":
        return [(HOY.isoformat(), HOY.isoformat())]
    if clave == "este_mes":
        return [(HOY.replace(day=1).isoformat(), HOY.isoformat())]
    if clave == "mes_pasado":
        fin = HOY.replace(day=1) - timedelta(days=1)
        return [(fin.replace(day=1).isoformat(), fin.isoformat())]
    if clave == "esta_semana":
        return [((HOY - timedelta(days=HOY.weekday())).isoformat(), HOY.isoformat())]
    if clave.startswith("ultimos_"):
        n = int(clave.split("_")[1])
        return [((HOY - timedelta(days=n - 1)).isoformat(), HOY.isoformat()),
                ((HOY - timedelta(days=n)).isoformat(), HOY.isoformat())]
    raise ValueError(f"periodo desconocido: {clave}")


def _ids(cat: dict, clave: str, nombres: list) -> list:
    por_nombre = {x["nombre"]: x["id"] for x in cat[clave]}
    return sorted(por_nombre[n] for n in nombres)


def _id_afiliado(nombre: str, empresa: str = "") -> int:
    cuits = None
    if empresa:
        cuits = [e["cuit"] for e in dashboard.catalogo_empresas(fx.SID_A) if e["nombre"] == empresa]
    candidatos = [c for c in dashboard.buscar_afiliados(fx.SID_A, nombre, cuits=cuits) if c["nombre"] == nombre]
    assert len(candidatos) == 1, (nombre, empresa, candidatos)
    return candidatos[0]["id"]


def armar_estado(cat: dict, cambios: dict) -> dict:
    estado = dict(fx.ESTADO_BASE)
    for clave, valor in (cambios or {}).items():
        if clave in ("seccionales", "empresas"):
            estado[clave] = _ids(cat, clave, valor)
        elif clave == "afiliado":
            estado["afiliado"] = _id_afiliado(valor)
        elif clave == "periodo":
            estado["desde"], estado["hasta"] = periodo_esperado(valor)[0]
        else:
            estado[clave] = valor
    return estado


def comparar(cat: dict, espera: dict, salida: dict) -> list:
    fallas = []
    if "aplicar" in espera and salida["aplicar"] != espera["aplicar"]:
        fallas.append(f"aplicar: esperado {espera['aplicar']}, obtenido {salida['aplicar']}")
    if "candidatos" in espera and len(salida["candidatos"]) != espera["candidatos"]:
        fallas.append(f"candidatos: esperados {espera['candidatos']}, obtenidos {len(salida['candidatos'])}")
    if espera.get("aplicar") is False or "candidatos" in espera:
        return fallas
    if not salida["aplicar"]:
        return fallas + ["no aplicó filtros: " + salida["respuesta"][:100]]
    f = salida["filtros"]
    for clave in ("formato", "resultado", "estado_tramite", "tipo_notif", "tab", "sal_min", "sal_max"):
        if clave in espera and f.get(clave) != espera[clave]:
            fallas.append(f"{clave}: esperado {espera[clave]!r}, obtenido {f.get(clave)!r}")
    for clave in ("seccionales", "empresas"):
        if clave in espera and sorted(f.get(clave) or []) != _ids(cat, clave, espera[clave]):
            fallas.append(f"{clave}: esperado {espera[clave]}, obtenido ids {f.get(clave)}")
    if "periodo" in espera and (f["desde"], f["hasta"]) not in periodo_esperado(espera["periodo"]):
        fallas.append(f"periodo: esperado {espera['periodo']} {periodo_esperado(espera['periodo'])[0]}, "
                      f"obtenido {f['desde']}..{f['hasta']}")
    if "afiliado" in espera:
        esperado = _id_afiliado(espera["afiliado"], espera.get("afiliado_empresa", ""))
        if f.get("afiliado") != esperado:
            fallas.append(f"afiliado: esperado {espera['afiliado']} (id {esperado}), obtenido {f.get('afiliado')}")
    return fallas


def correr(cat: dict, numero: int, frase: dict) -> dict:
    estado = armar_estado(cat, frase.get("estado"))
    t0 = time.time()
    try:
        salida = asistente.responder(fx.SID_A, frase["pregunta"], estado, frase.get("historial", []))
    except asistente.ErrorModelo as e:
        return {"n": numero, "pregunta": frase["pregunta"], "ok": False,
                "fallas": [f"error del modelo: {e}"], "seg": round(time.time() - t0, 1), "uso": {}}
    fallas = comparar(cat, frase["espera"], salida)
    return {"n": numero, "pregunta": frase["pregunta"], "ok": not fallas, "fallas": fallas,
            "seg": round(time.time() - t0, 1), "uso": salida["uso"],
            "respuesta": salida["respuesta"], "filtros": salida["filtros"],
            "candidatos": len(salida["candidatos"])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sin-thinking", action="store_true", help="thinking desactivado en vez de esfuerzo bajo")
    ap.add_argument("--solo", default="", help="números de frase (1-based) separados por coma")
    ap.add_argument("--hilos", type=int, default=4)
    args = ap.parse_args()

    if args.sin_thinking:
        asistente.OPCIONES_MODELO = {"thinking": {"type": "disabled"}}
    config = "sin thinking" if args.sin_thinking else "esfuerzo bajo (adaptativo)"
    asistente.usar_cliente(None)             # cliente real desde la API key
    if not asistente.disponible():
        print("Falta ANTHROPIC_API_KEY en .env"); return 2

    with open(os.path.join(RAIZ, "medicion_asistente", "frases.json"), encoding="utf-8") as fh:
        frases = json.load(fh)["frases"]
    elegidas = [int(x) for x in args.solo.split(",") if x.strip()] or list(range(1, len(frases) + 1))
    cat = asistente.catalogo(fx.SID_A)
    print(f"Asistente del Panel · set de aceptación · {len(elegidas)} frases · "
          f"{asistente.MODELO} · {config} · hoy {HOY.isoformat()}\n")

    with ThreadPoolExecutor(max_workers=max(1, args.hilos)) as pool:
        resultados = list(pool.map(lambda n: correr(cat, n, frases[n - 1]), elegidas))

    for r in resultados:
        marca = "OK   " if r["ok"] else "FALLA"
        print(f"{marca} #{r['n']:>2}  {r['pregunta'][:58]:<58}  {r['seg']:>5.1f} s")
        for falla in r["fallas"]:
            print(f"         - {falla}")
        if not r["ok"] and r.get("respuesta"):
            print(f"         · dijo: {r['respuesta'][:110]}")

    aciertos = sum(1 for r in resultados if r["ok"])
    tiempos = [r["seg"] for r in resultados]
    entrada = sum(r["uso"].get("tokens_entrada", 0) for r in resultados)
    salida = sum(r["uso"].get("tokens_salida", 0) for r in resultados)
    llamadas = sum(r["uso"].get("llamadas", 0) for r in resultados)
    costo = entrada * PRECIO_ENTRADA + salida * PRECIO_SALIDA
    print(f"\nAciertos: {aciertos}/{len(resultados)}   ·   tiempo por pregunta: mediana "
          f"{statistics.median(tiempos):.1f} s, máximo {max(tiempos):.1f} s   ·   "
          f"{llamadas} llamadas, {entrada} tokens de entrada y {salida} de salida "
          f"(≈ US$ {costo:.3f} la corrida, {costo / len(resultados):.4f} por pregunta)")

    with open(os.path.join(RAIZ, "medicion_asistente", "ultima_corrida.json"), "w", encoding="utf-8") as fh:
        json.dump({"fecha": HOY.isoformat(), "modelo": asistente.MODELO, "config": config,
                   "aciertos": aciertos, "total": len(resultados),
                   "mediana_seg": statistics.median(tiempos), "max_seg": max(tiempos),
                   "tokens_entrada": entrada, "tokens_salida": salida, "costo_usd": round(costo, 4),
                   "resultados": resultados}, fh, ensure_ascii=False, indent=1, default=str)
    return 0 if aciertos == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
