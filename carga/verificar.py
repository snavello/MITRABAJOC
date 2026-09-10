# -*- coding: utf-8 -*-
"""Auditoría de carga/experimentos.json contra los datos crudos.

Existe por un motivo concreto: la primera versión de estos informes se
contradecía a sí misma (el encabezado hablaba de una configuración y la
tabla de más abajo de otra), y eso puede llevar a decidir mal un gasto de
infraestructura. Antes de publicar nada, esto vuelve a leer resumen.csv y
servidor*.log por su cuenta y compara CADA número contra lo consolidado,
además de revisar que las conclusiones no citen ninguna cifra que no salga
de la propia tabla del test.

Chequeos:
  1. Tiempos por escalón (p50/p95/p99/errores/rps/n) iguales al resumen.csv.
  2. CPU/RAM/conexiones de web y Postgres iguales a recalcularlos del log.
  3. Toda cifra que aparece en el veredicto y en la conclusión tiene que
     existir en los datos de ese mismo test (o ser una comparación válida
     contra la línea base). Nada escrito a mano "de memoria".
  4. Coherencia interna: fechas en hora de Buenos Aires, escalones marcados
     como inválidos que no cuenten para el veredicto, y config declarada
     igual a la que usan las conclusiones.

Uso:  python carga/verificar.py    (código de salida != 0 si algo falla)
"""
import json
import re
import sys
from pathlib import Path

import consolidar as C

BASE = Path(__file__).resolve().parent
DATOS = BASE / "experimentos.json"

fallos = []
chequeos = 0
# Cuántas fases se pudieron contrastar contra el NDJSON crudo de k6 y
# cuántas usaron la ventana cacheada en ventanas.json (el crudo pesa
# cientos de MB y no se versiona -- ver .gitignore).
fases_con_crudo = 0
fases_con_cache = 0


def revisar(condicion, mensaje):
    global chequeos
    chequeos += 1
    if not condicion:
        fallos.append(mensaje)


def numeros_del_texto(texto: str) -> list:
    """Las cifras que aparecen en una frase, normalizadas. Antes de
    extraerlas se sacan las fechas (2026-09-10) y las referencias a otro
    test ("el test 6"), que son identificadores y no mediciones."""
    texto = re.sub(r"\d{4}-\d{2}-\d{2}", " ", texto)
    texto = re.sub(r"\btests?\s+\d+", " ", texto, flags=re.IGNORECASE)
    return re.findall(r"\d+(?:,\d+)?", texto)


def vocabulario_de(exp: dict, base: dict, *referencias) -> set:
    """Todas las cifras que este test PUEDE citar: las de sus propias
    tablas y cargas, más las comparaciones válidas contra la línea base y
    contra los tests que su conclusión compara explícitamente (el 5 se
    compara contra el 4, no contra el 1)."""
    ok = set()
    for ref in referencias:
        if ref:
            ok |= vocabulario_de(ref, ref)
            # Proporciones entre corridas ("7.3 veces más subidas").
            for fa in exp["fases"]:
                for fb in ref["fases"]:
                    if fa["clave"] != fb["clave"]:
                        continue
                    for x in fa["filas"]:
                        for y in fb["filas"]:
                            if x["escalon"] == y["escalon"] and y["n"]:
                                ok.add(f'{x["n"] / y["n"]:.1f}'.replace(".", ","))
                                ok.add(C.delta(x["p95"], y["p95"]).lstrip("+-").rstrip("%"))

    def agregar(*vals):
        for v in vals:
            if v is None:
                continue
            ok.add(str(v))
            if isinstance(v, float):
                ok.add(C.fmt_ms(v).replace(" s", "").replace(" ms", ""))
                ok.add(C.fmt_pct(v).rstrip("%"))
                ok.add(C.fmt_vcpu(v))
                ok.add(f"{v:.0f}")
            if isinstance(v, (int, float)):
                ok.add(C.fmt_vcpu(v))

    for fase in exp["fases"]:
        for f in fase["filas"]:
            agregar(f["escalon"], f["p50"], f["p95"], f["p99"], f["errores_pct"], f["rps"], f["n"])
        c = fase["carga"]
        for lado in ("web", "db"):
            d = c[lado]
            agregar(d["cpu_usado"], d["cpu_nominal"], d["cpu_pct"],
                    d["ram_mb"], d["ram_nominal_mb"], d["ram_pct"], d.get("conexiones"))
        agregar(c["muestras"])
    inst = exp["config"].get("instancias", 1)
    agregar(exp["config"].get("ia_latencia_seg"), exp["config"].get("workers_uvicorn"),
            exp["config"].get("pool_size"), exp["config"].get("max_overflow"), inst)
    if exp["config"].get("workers_uvicorn") is not None:
        agregar(exp["config"]["workers_uvicorn"] * inst)

    # Comparaciones contra la línea base: el valor viejo y la variación.
    for fase_b in base["fases"]:
        for f in fase_b["filas"]:
            agregar(f["escalon"], f["p50"], f["p95"], f["p99"], f["errores_pct"])
        for lado in ("web", "db"):
            d = fase_b["carga"][lado]
            agregar(d["cpu_usado"], d["cpu_nominal"], d["cpu_pct"], d["ram_pct"])
    for fase in exp["fases"]:
        for f in fase["filas"]:
            for fase_b in base["fases"]:
                if fase_b["clave"] != fase["clave"]:
                    continue
                for fb in fase_b["filas"]:
                    if fb["escalon"] == f["escalon"] and fb["p95"]:
                        ok.add(C.delta(f["p95"], fb["p95"]).lstrip("+-").rstrip("%"))

    # Constantes del criterio y redondeos de una cifra que el texto usa al
    # hablar en prosa ("cuatro veces más CPU" -> 4, "1 s", "1%"), más el
    # corte del test ("más de 60 s").
    ok |= {"1", "0", "100", "4", "95", "99", "50", "1000", str(C.TIMEOUT_SEG)}
    return ok


def main():
    if not DATOS.exists():
        sys.exit("Falta carga/experimentos.json -- correr python carga/consolidar.py")
    datos = json.loads(DATOS.read_text(encoding="utf-8"))
    porcodigo = {e["numero"]: e for e in datos}
    base = porcodigo[1]

    revisar(len(datos) == 7, f"Se esperaban 7 experimentos y hay {len(datos)}.")
    revisar(sorted(porcodigo) == [1, 2, 3, 4, 5, 6, 7],
            f"La numeración tiene que ser 1..7 y es {sorted(porcodigo)}.")

    # Reconstrucción independiente desde las fuentes crudas.
    definiciones = {e["numero"]: e for e in C.EXPERIMENTOS}
    for exp in datos:
        d = definiciones[exp["numero"]]
        etiqueta = f"Test {exp['numero']}"

        revisar(len(exp["fases"]) == len(d["fases"]),
                f"{etiqueta}: {len(exp['fases'])} fases publicadas y {len(d['fases'])} definidas.")

        for fase, fd in zip(exp["fases"], d["fases"]):
            carpeta = C.LOG / fd["carpeta"]
            nombre = f"{etiqueta}/{fase['clave']}"

            # 1. Tiempos contra resumen.csv, leído de nuevo acá.
            crudas = {f["escalon"]: f for f in C.filas_csv(carpeta, fd["serie"])}
            revisar(len(crudas) == len(fase["filas"]),
                    f"{nombre}: {len(fase['filas'])} filas publicadas y {len(crudas)} en el CSV.")
            for f in fase["filas"]:
                c = crudas.get(f["escalon"])
                if not c:
                    fallos.append(f"{nombre}: el escalón {f['escalon']} no está en el CSV.")
                    continue
                for campo in ("p50", "p95", "p99", "errores_pct", "rps", "n"):
                    revisar(f[campo] == c[campo],
                            f"{nombre} escalón {f['escalon']}: {campo} publicado {f[campo]} "
                            f"y en el CSV {c[campo]}.")

            # 2. Cargas de servidor recalculadas desde el log crudo.
            global fases_con_crudo, fases_con_cache
            if (carpeta / fd["k6"]).exists():
                fases_con_crudo += 1
            else:
                fases_con_cache += 1
            v = C.ventana_k6(carpeta / fd["k6"])
            m = C.metricas_servidor(carpeta / fd["log"], v[0], v[1])
            esperada = C.carga_legible(m, d["config"]["plan_web"], d["config"]["plan_db"])
            revisar(fase["carga"] == esperada,
                    f"{nombre}: la carga publicada no coincide con recalcularla del log.")
            revisar(fase["carga_medida"] == (m["cpu_web"] is not None or m["cpu_db"] is not None),
                    f"{nombre}: 'carga_medida' no refleja si había métricas.")

            # 4a. Fechas en hora de Buenos Aires.
            ini = v[0].astimezone(C.BUENOS_AIRES).strftime("%Y-%m-%d %H:%M")
            revisar(fase["inicio_ba"] == ini,
                    f"{nombre}: inicio publicado {fase['inicio_ba']} y el real (BA) es {ini}.")

            # 4b. Un escalón inválido nunca puede figurar como que cumple.
            for f in fase["filas"]:
                revisar(not (f.get("cumple") and not f.get("valido", True)),
                        f"{nombre} escalón {f['escalon']}: marcado como cumplido siendo inválido.")
                esperado = (f.get("valido", True) and f["p95"] < C.OBJETIVO_P95_MS
                            and f["errores_pct"] < C.OBJETIVO_ERRORES_PCT)
                revisar(f["cumple"] == esperado,
                        f"{nombre} escalón {f['escalon']}: 'cumple' dice {f['cumple']} "
                        f"y el criterio da {esperado}.")

        # 4c. El veredicto tiene que salir de la fase de lecturas.
        revisar(exp["veredicto"] == C.veredicto(exp["fases"]),
                f"{etiqueta}: el veredicto no coincide con recalcularlo.")

        # 3. Ninguna cifra inventada en veredicto ni conclusión.
        # El test 5 aísla un cambio de código: compara contra el 4, que
        # corrió con la misma infraestructura, no contra la línea base.
        referencia = porcodigo.get(exp["numero"] - 1) if exp["numero"] in (5, 6, 7) else None
        vocab = vocabulario_de(exp, base, referencia)
        for campo in ("veredicto", "conclusion"):
            for numero in numeros_del_texto(exp[campo]):
                revisar(numero in vocab,
                        f"{etiqueta}: el {campo} cita '{numero}', que no sale de sus datos.")

        # 4d. La config declarada tiene que ser la de la definición.
        for k, esperado in d["config"].items():
            revisar(exp["config"].get(k) == esperado,
                    f"{etiqueta}: config['{k}'] publicada {exp['config'].get(k)!r} "
                    f"y definida {esperado!r}.")

    # 5. El informe general (los 4 tests comparados) y el INFORME.md salen
    # del mismo dict; se revisa que sus tablas repitan exactamente los p95
    # del dataset y que no cite ninguna cifra ajena en sus hallazgos.
    import informe as INF
    inf = INF.construir()
    revisar(len(inf["experimentos"]) == 7, "El informe general no cubre los 7 tests.")
    for clave, comp, escalones in (("lecturas", inf["comparativa_lecturas"], INF.ESCALONES_LECTURAS),
                                   ("recibos", inf["comparativa_recibos"], INF.ESCALONES_RECIBOS)):
        for fila in comp:
            for exp, celda in zip(inf["experimentos"], fila["celdas"]):
                real = None
                for f in exp["fases"]:
                    if f["clave"] != clave:
                        continue
                    for x in f["filas"]:
                        if x["escalon"] == fila["escalon"]:
                            real = x
                if real is None:
                    revisar(not celda["hay"],
                            f"Informe/{clave} {fila['escalon']} test {exp['numero']}: "
                            f"muestra dato donde no hubo corrida.")
                elif not real.get("valido", True):
                    revisar(not celda["hay"],
                            f"Informe/{clave} {fila['escalon']} test {exp['numero']}: "
                            f"usa un dato contaminado como válido.")
                else:
                    revisar(celda.get("p95") == real["p95"],
                            f"Informe/{clave} {fila['escalon']} test {exp['numero']}: "
                            f"p95 {celda.get('p95')} y en el dataset {real['p95']}.")
    # El informe compara entre tests, así que su vocabulario es la unión de
    # todos, incluidas las proporciones de cada uno contra los demás.
    todo_vocab = set()
    for e in datos:
        for otro in datos:
            todo_vocab |= vocabulario_de(e, base, otro if otro is not e else None)
    for h in inf["hallazgos"]:
        for numero in numeros_del_texto(h["texto"]):
            revisar(numero in todo_vocab,
                    f"Informe/hallazgo '{h['titulo'][:38]}...' cita '{numero}', "
                    f"que no sale de los datos.")
    for r in inf["recomendaciones"]:
        for numero in numeros_del_texto(r["texto"]):
            revisar(numero in todo_vocab,
                    f"Informe/recomendación '{r['titulo'][:38]}...' cita '{numero}', "
                    f"que no sale de los datos.")
    for numero in numeros_del_texto(inf["resumen"]):
        revisar(numero in todo_vocab, f"Informe/resumen cita '{numero}', que no sale de los datos.")

    # 6. El INFORME.md del repo tiene que estar regenerado, no editado a mano.
    import generar_md
    md = BASE / "INFORME.md"
    revisar(md.exists() and md.read_text(encoding="utf-8") == generar_md.construir_md(),
            "carga/INFORME.md quedó desactualizado: correr python carga/generar_md.py")

    print(f"{chequeos} chequeos sobre {len(datos)} experimentos.")
    if fases_con_cache:
        print(f"Ventanas de tiempo: {fases_con_crudo} verificadas contra el NDJSON crudo de "
              f"k6 y {fases_con_cache} tomadas de ventanas.json, porque ese NDJSON no está "
              f"en este clon (pesa cientos de MB y no se versiona). Los tiempos por escalón "
              f"y las cargas de CPU/RAM se verifican siempre contra resumen.csv y "
              f"servidor*.log, que sí están versionados.")
    else:
        print(f"Ventanas de tiempo: las {fases_con_crudo} verificadas contra el NDJSON crudo "
              f"de k6, que está presente en este clon.")
    if fallos:
        print(f"\n{len(fallos)} INCONSISTENCIAS:")
        for f in fallos:
            print(f"  - {f}")
        sys.exit(1)
    print("Sin inconsistencias: lo publicado coincide con los datos crudos.")


if __name__ == "__main__":
    main()
