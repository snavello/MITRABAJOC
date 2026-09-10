# -*- coding: utf-8 -*-
"""Regenera carga/INFORME.md desde carga/experimentos.json, con el mismo
contenido que sirve /entornos/informe (los dos salen de carga/informe.py).

Antes el INFORME.md se editaba a mano después de cada corrida y el HTML
del sitio se editaba aparte: terminaron diciendo cosas distintas. Ahora el
archivo es una salida, no una fuente -- si hay que corregir un número, se
corrige el dato crudo y se vuelve a generar.

Uso:  python carga/generar_md.py
"""
from pathlib import Path

import informe as I

BASE = Path(__file__).resolve().parent
SALIDA = BASE / "INFORME.md"


def tabla(comparativa, exps, encabezado):
    filas = ["| " + encabezado + " | " + " | ".join(
        f"{e['numero']}. {e['nombre']}" for e in exps) + " |",
        "|" + "---|" * (len(exps) + 1)]
    for f in comparativa:
        celdas = []
        for c in f["celdas"]:
            txt = c["texto"]
            if c["hay"] and c["cumple"]:
                txt = f"**{txt}**"
            celdas.append(txt)
        filas.append(f"| {f['escalon']} | " + " | ".join(celdas) + " |")
    return "\n".join(filas)


def construir_md() -> str:
    inf = I.construir()
    exps = inf["experimentos"]
    p = []
    a = p.append

    a(f"# Test de estrés de la app del trabajador — los {len(exps)} tests comparados")
    a("")
    a("> **Este archivo se genera solo.** Sale de `carga/experimentos.json`, que a su vez")
    a("> se arma con `carga/consolidar.py` desde los datos crudos de cada corrida")
    a("> (`carga/log/`). No editar a mano: corregir el dato de origen y volver a correr")
    a("> `python carga/consolidar.py && python carga/generar_md.py`. La misma información,")
    a("> con gráfico, se sirve en `/entornos/informe` del sitio de Pruebas.")
    a("")
    a(f"Servicio medido: `mitrabajo-pruebas.onrender.com`. Objetivo fijado para los {len(exps)}")
    a(f"tests: **p95 por debajo de 1 s con menos de 1% de errores**. Horarios en hora de")
    a("Buenos Aires. Los tiempos están en milisegundos salvo donde se indique.")
    a("")
    a("## El resultado, en un párrafo")
    a("")
    a(inf["resumen"])
    a("")

    a(f"## A. Los {len(exps)} tests")
    a("")
    a("Cada uno cambió *una* cosa respecto del anterior, para poder atribuir la mejora o el")
    a("empeoramiento a esa cosa y no a una mezcla.")
    a("")
    a("| # | Test | Cuándo | Servicio web | Postgres | Workers | Resultado |")
    a("|---|---|---|---|---|---|---|")
    for e in exps:
        cumple = "cumple" if "Cumple" in e["veredicto"] else "no cumple"
        a(f"| {e['numero']} | {e['nombre']} | {e['inicio_ba']} a {e['fin_ba']} | "
          f"{e['config']['plan_web_etiqueta']} | {e['config']['plan_db_etiqueta']} | "
          f"{e['config']['workers_uvicorn']} | {cumple} |")
    a("")
    for e in exps:
        a(f"**Test {e['numero']} — {e['nombre']}.** {e['objetivo']} {e['veredicto']}")
        a("")
        a(f"{e['conclusion']}")
        a("")

    a("## B. Navegación: p95 según cuánta gente hay")
    a("")
    a("La prueba que no sube ningún recibo y no toca la IA: mide el techo puro del servidor.")
    a("En negrita, los escalones que cumplen el objetivo.")
    a("")
    a(tabla(inf["comparativa_lecturas"], exps, "Usuarios concurrentes"))
    a("")
    a("`n/d` son los escalones del test 2 que quedaron contaminados por un despliegue a mitad")
    a("de corrida: se descartan. `timeout` quiere decir que los pedidos no respondieron dentro")
    a("de los 60 segundos que espera el test — el valor real es \"más de 60 s\", no 60.")
    a("")

    a("## C. Subida de recibos")
    a("")
    a("Tiempo de cada subida cuando llegan varias a la vez. El test 2 no corrió esta fase.")
    a("")
    a(tabla(inf["comparativa_recibos"], exps, "Recibos simultáneos"))
    a("")
    a("**Cuidado al leer esta tabla:** cada escalón tiene entre 6 y 37 subidas completadas, así")
    a("que su p95 es prácticamente el peor caso observado y no un percentil sólido. Sirve para")
    a("el orden de magnitud, no para comparar diferencias finas entre escalones. Por eso el test")
    a("3 muestra 20 simultáneos \"mejor\" que 10: es ruido de muestra chica, no una mejora.")
    a("")

    a("## D. Qué mostró cada test")
    a("")
    for h in inf["hallazgos"]:
        tests = " y ".join(str(t) for t in h["tests"])
        a(f"### {h['titulo']}")
        a("")
        a(f"*Medido en {'los tests' if len(h['tests']) > 1 else 'el test'} {tests}.*")
        a("")
        a(h["texto"])
        a("")

    a("## E. Qué hacer")
    a("")
    for i, r in enumerate(inf["recomendaciones"], 1):
        a(f"{i}. **{r['titulo']}** — *{r['estado']}, costo {r['costo']}.* {r['texto']}")
        a("")

    a("## F. Para el arranque en producción")
    a("")
    a("> **Esto es razonamiento, no medición.** Todo lo anterior son números medidos contra el")
    a("> servicio de Pruebas; esta sección extrapola hacia una infraestructura que todavía no se")
    a("> probó. Antes de comprometer el gasto conviene correr el mismo test contra la")
    a("> configuración real ya contratada.")
    a("")
    a("**El hecho técnico que ordena la decisión.** Un proceso de Python usa efectivamente un")
    a("solo núcleo, aunque el código sea asincrónico como el de esta app y aunque la máquina")
    a("tenga más. De ahí las dos mitades de la misma regla, las dos con evidencia acá: comprar")
    a("CPU sin sumar `--workers` deja los núcleos nuevos sin usar, y sumar workers sin CPU real")
    a("empeora las cosas (test 2). Van juntos: un worker por núcleo.")
    a("")
    a("**Muchas instancias chicas o pocas grandes.** Para el servicio web conviene repartir en")
    a("varias instancias: las sesiones viajan en una cookie firmada y no hay estado en el")
    a("servidor, así que cualquier instancia atiende a cualquiera sin configuración extra; una")
    a("caída se lleva una porción más chica; y ningún proceso necesita mucha memoria propia")
    a("(en el test 4 el web usó 638 MB de los 4 GB disponibles).")
    a("")
    a("**Cómo se hace en Render.** Para el servicio web no se crean servicios separados: es un")
    a("solo servicio con su pestaña *Scaling*, donde se fija el número de instancias; cada una")
    a("corre el mismo plan y Render reparte el tráfico con su propio balanceador. El autoscaling")
    a("automático existe pero requiere plan Pro o superior del workspace y escala por métrica de")
    a("CPU/memoria, no por horario.")
    a("")
    a("**Postgres es distinto.** No existen varias instancias que se repartan la escritura: lo")
    a("que Render ofrece son réplicas de lectura (hasta cinco, de solo lectura, con retraso de")
    a("replicación y su propia URL de conexión), lo que obliga a separar en el código qué")
    a("consultas van a cada una. Hoy la app no hace esa separación. Si el objetivo es aguantar")
    a("más carga, la palanca real sigue siendo subir el plan de la única instancia — que es")
    a("justo lo que se midió en el test 3.")
    a("")
    a("**La cuenta que no hay que olvidar.** Las conexiones a la base se multiplican por")
    a("instancia. Cada worker abre hasta 10 conexiones y el test 4 lo confirmó midiendo")
    a("exactamente 20 con 2 workers. Al escalar hay que multiplicar por la cantidad total de")
    a("workers y contrastarlo contra el límite del plan de Postgres elegido.")
    a("")

    a("## G. Lo que hay que tener en cuenta de estas mediciones")
    a("")
    for e in exps:
        for adv in e["advertencias"]:
            if not adv.startswith("Corrida limpia"):
                a(f"- **Test {e['numero']}:** {adv}")
    ia = exps[0]["config"]["ia_latencia_seg"]
    a(f"- La llamada a la IA se simuló con una espera fija de {ia} segundos, para no depender de")
    a("  la velocidad variable del servicio real ni gastar créditos. Es la demora típica")
    a("  observada, pero es una simulación.")
    a("- Todos los tiempos se cortan a los 60 segundos: donde dice `timeout`, el pedido nunca")
    a("  respondió.")
    a("")

    a("## Cómo se reproduce")
    a("")
    a("```")
    a("python carga/consolidar.py            # reconstruye el dataset desde carga/log/")
    a("python carga/verificar.py             # audita cada cifra contra los datos crudos")
    a("python carga/generar_md.py            # regenera este archivo")
    a("PIN_ENTORNOS=... BASE_URL=... python carga/publicar_experimentos.py   # publica en el sitio")
    a("```")
    a("")
    a("Para correr un test nuevo, ver `carga/README.md`.")
    return "\n".join(p) + "\n"


if __name__ == "__main__":
    SALIDA.write_text(construir_md(), encoding="utf-8")
    print(f"Escrito {SALIDA} ({len(SALIDA.read_text(encoding='utf-8').splitlines())} líneas)")
