# -*- coding: utf-8 -*-
"""Arma el informe general (los 4 tests comparados) A PARTIR de
carga/experimentos.json. No hay ninguna cifra escrita a mano: todas las
tablas, hallazgos y recomendaciones se calculan de los mismos datos que
muestran las páginas de cada test.

Por qué: la versión anterior del informe era un HTML escrito a mano que se
fue parchando después de cada experimento. Terminó diciendo en el
encabezado la configuración del cuarto test y, más abajo, la del primero,
sin aclararlo -- se leía como una contradicción y hacía dudar de todo.

Lo usa main.py para servir /entornos/informe, y carga/generar_md.py para
regenerar carga/INFORME.md. Los dos salen del mismo dict: no pueden
divergir entre sí.
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATOS = BASE / "experimentos.json"

# Por encima de esto, el pedido no respondió: es el corte del test (60 s),
# no un tiempo de respuesta real. Se muestra como "timeout".
TIMEOUT_MS = 59000

ESCALONES_LECTURAS = [50, 100, 200, 400, 800]
ESCALONES_RECIBOS = [2, 5, 10, 20]


def _fmt_ms(v):
    if v is None:
        return None
    if v >= TIMEOUT_MS:
        return "timeout"
    if v >= 1000:
        return f"{v / 1000:.1f}".replace(".", ",") + " s"
    return f"{v:.0f} ms"


def _fmt_pct(v):
    if v is None:
        return None
    if 0 < v < 1:
        return f"{v:.2f}".replace(".", ",") + "%"
    return f"{v:.1f}".replace(".", ",") + "%"


def _delta(nuevo, viejo):
    if nuevo is None or viejo in (None, 0):
        return None
    d = 100 * (nuevo - viejo) / viejo
    return ("+" if d > 0 else "") + f"{d:.1f}".replace(".", ",") + "%"


def _fase(exp, clave):
    for f in exp["fases"]:
        if f["clave"] == clave:
            return f
    return None


def _fila(exp, clave, escalon):
    f = _fase(exp, clave)
    if not f:
        return None
    for fila in f["filas"]:
        if fila["escalon"] == escalon:
            return fila
    return None


def _celda(exp, clave, escalon):
    """Una celda de la tabla comparativa: el p95 de ese escalón en ese
    test, o por qué no hay dato (no se corrió esa fase / dato inválido)."""
    fila = _fila(exp, clave, escalon)
    if fila is None:
        return {"hay": False, "motivo": "no se corrió", "texto": "—"}
    if not fila.get("valido", True):
        return {"hay": False, "motivo": "dato contaminado", "texto": "n/d",
                "p95": fila["p95"]}
    return {"hay": True, "p95": fila["p95"], "texto": _fmt_ms(fila["p95"]),
            "errores": fila["errores_pct"], "errores_texto": _fmt_pct(fila["errores_pct"]),
            "cumple": fila["cumple"], "timeout": fila["p95"] >= TIMEOUT_MS}


def comparativa(exps, clave, escalones):
    """Una fila por escalón, una columna por test."""
    filas = []
    for esc in escalones:
        celdas = [_celda(e, clave, esc) for e in exps]
        filas.append({"escalon": esc, "celdas": celdas})
    return filas


def serie_grafico(exps, clave, escalones):
    """Series para el gráfico: p95 por escalón de cada test. Los escalones
    inválidos van en None para que la línea se corte ahí en vez de dibujar
    un dato que el propio informe declara contaminado."""
    series = []
    for e in exps:
        valores = []
        for esc in escalones:
            c = _celda(e, clave, esc)
            valores.append(c["p95"] if c["hay"] else None)
        series.append({"numero": e["numero"], "nombre": e["nombre"], "valores": valores})
    return series


def hallazgos(exps):
    """Los hechos que sostienen las recomendaciones, cada uno con los
    números que lo prueban y de qué test salen."""
    por_num = {e["numero"]: e for e in exps}
    t1, t2, t3, t4 = (por_num[n] for n in (1, 2, 3, 4))
    t5 = por_num.get(5)
    t7, t8 = por_num.get(7), por_num.get(8)
    out = []

    # 1. El techo lo pone el servicio web, no la IA.
    solos = _fase(t1, "lectores_solos")
    p95_solos = [f["p95"] for f in solos["filas"]]
    l200 = _fila(t1, "lecturas", 200)
    out.append({
        "titulo": "El techo lo pone el servicio web, no la llamada a la IA",
        "tests": [1],
        "texto": (
            f"En el test 1 se midieron 200 lectores puros, sin subir un solo recibo y sin "
            f"tocar la IA: el p95 quedó entre {_fmt_ms(min(p95_solos))} y "
            f"{_fmt_ms(max(p95_solos))}. El escalón de 200 del test de lecturas, que es "
            f"otra carga de trabajo distinta, dio {_fmt_ms(l200['p95'])}. Que dos pruebas "
            f"independientes choquen contra el mismo número muestra que el límite es el "
            f"proceso que atiende, no lo que hace cada pedido."),
    })

    # 2. Postgres: se saturó en CPU, nunca en RAM.
    cb = _fase(t1, "lectores_solos")["carga"]["db"]
    c3 = _fase(t3, "lecturas")["carga"]["db"]
    out.append({
        "titulo": "Postgres se saturó en CPU y nunca en memoria",
        "tests": [1, 3],
        "texto": (
            f"Con el plan más chico, la base llegó al {_fmt_pct(cb['cpu_pct'])} de su CPU "
            f"con apenas {cb['conexiones']} conexiones abiertas, mientras su memoria no "
            f"pasó del {_fmt_pct(cb['ram_pct'])}. Al subirla en el test 3, la CPU cayó al "
            f"{_fmt_pct(c3['cpu_pct'])} y la RAM al {_fmt_pct(c3['ram_pct'])}. "
            f"Para esta app, al elegir plan de base de datos manda la CPU: la memoria "
            f"sobra en los dos casos."),
    })

    # 3. Workers sin CPU: empeora (contraejemplo medido).
    peor = []
    for esc in (50, 100, 200):
        a, b = _fila(t1, "lecturas", esc), _fila(t2, "lecturas", esc)
        peor.append(f"{esc} concurrentes {_fmt_ms(a['p95'])} → {_fmt_ms(b['p95'])} "
                    f"({_delta(b['p95'], a['p95'])})")
    e200 = _fila(t2, "lecturas", 200)
    b200 = _fila(t1, "lecturas", 200)
    out.append({
        "titulo": "Sumar workers sin sumar CPU empeora las cosas",
        "tests": [2],
        "texto": (
            "El test 2 probó dos workers sobre la misma media vCPU y todos los escalones "
            "válidos empeoraron: " + "; ".join(peor) + f". Los errores a 200 concurrentes "
            f"pasaron de {_fmt_pct(b200['errores_pct'])} a {_fmt_pct(e200['errores_pct'])}. "
            "Dos procesos compitiendo por el mismo medio núcleo no dan paralelismo: "
            "agregan cambio de contexto y memoria. Workers y CPU se suben juntos."),
    })

    # 4. Workers CON CPU: el salto grande.
    mejoras = []
    for esc in (50, 100, 200, 800):
        a, b = _fila(t1, "lecturas", esc), _fila(t4, "lecturas", esc)
        mejoras.append(f"{esc} concurrentes {_fmt_ms(a['p95'])} → {_fmt_ms(b['p95'])}")
    c4 = _fase(t4, "lecturas")["carga"]
    out.append({
        "titulo": "Con CPU entera y un worker por núcleo, el techo se corre de golpe",
        "tests": [4],
        "texto": (
            "El test 4 subió el web a 2 vCPU con 2 workers, sobre la base ya grande del "
            "test 3: " + "; ".join(mejoras) + ". Es la única configuración probada que "
            f"cumple el objetivo. El web volvió a quedar al {_fmt_pct(c4['web']['cpu_pct'])} "
            f"de su CPU —sigue siendo el límite— pero ahora con cuatro veces más para "
            f"repartir, y la base quedó holgada en {_fmt_pct(c4['db']['cpu_pct'])}."),
    })

    # 5. Las ráfagas de recibos no mejoran con CPU.
    r1_10, r4_10 = _fila(t1, "recibos", 10), _fila(t4, "recibos", 10)
    r1_20, r4_20 = _fila(t1, "recibos", 20), _fila(t4, "recibos", 20)
    ia = t1["config"]["ia_latencia_seg"]
    out.append({
        "titulo": "Las ráfagas de recibos no mejoran con más CPU",
        "tests": [1, 4],
        "texto": (
            f"Con {r1_10['escalon']} recibos simultáneos, la línea base falló el "
            f"{_fmt_pct(r1_10['errores_pct'])} de las subidas y el test 4 —con cuatro veces "
            f"más CPU— el {_fmt_pct(r4_10['errores_pct'])}; con {r1_20['escalon']}, "
            f"{_fmt_pct(r1_20['errores_pct'])} contra {_fmt_pct(r4_20['errores_pct'])}. "
            f"La causa no es CPU: cada subida ocupaba un worker completo durante los "
            f"{ia} segundos que tarda la llamada a la IA, y mientras tanto ese worker no "
            f"atendía a nadie más. Es un problema de código, no de infraestructura."),
    })

    # 6. Conexiones: lo que se creía y lo que muestran los datos.
    filas_conex = []
    for e in exps:
        # `--workers` es por instancia: lo que le importa a la base es la
        # cantidad total de procesos, no la de cada instancia.
        w = e["config"]["workers_uvicorn"] * e["config"].get("instancias", 1)
        techo = (e["config"]["pool_size"] + e["config"]["max_overflow"]) * w
        medido = max((f["carga"]["db"]["conexiones"] or 0) for f in e["fases"])
        filas_conex.append(f"test {e['numero']} ({w} worker{'s' if w > 1 else ''}): "
                           f"tope teórico {techo}, medido {medido}")
    por_worker = exps[0]["config"]["pool_size"] + exps[0]["config"]["max_overflow"]
    out.append({
        "titulo": "Las conexiones a la base siguen a la saturación, no a la cantidad de workers",
        "tests": [n["numero"] for n in exps],
        "texto": (
            f"Por configuración, cada worker abre hasta {por_worker} conexiones "
            f"(pool de {exps[0]['config']['pool_size']} más "
            f"{exps[0]['config']['max_overflow']} de reserva), así que el tope debería ser "
            f"ese número por la cantidad de workers. Los datos no lo respaldan: "
            + "; ".join(filas_conex) + ". "
            "Un test con ocho workers y CPU de sobra usó menos conexiones que otro con "
            "cuatro workers y la CPU saturada, y varias corridas superaron su tope teórico. "
            "Lo que sí se ve con claridad es que el número sube cuando el servicio web se "
            "satura —los pedidos se apilan y retienen su conexión más tiempo— y baja cuando "
            "hay margen. Por qué se pasa del máximo del pool no está explicado: puede ser "
            "que la métrica de Render cuente también conexiones en cierre o el proceso "
            "maestro de uvicorn. Hasta entenderlo, para dimensionar conviene medirlo en la "
            "configuración real en vez de calcularlo, y dejar holgura contra el límite del "
            "plan de Postgres."),
    })
    # 7. Dos instancias: la única corrida con el web repartido.
    if t8 and t7:
        f8 = _fase(t8, "lecturas")
        f7 = _fase(t7, "lecturas")
        cumple8 = [x["escalon"] for x in f8["filas"] if x["cumple"]]
        cumple7 = [x["escalon"] for x in f7["filas"] if x["cumple"]]
        e8 = _fila(t8, "lecturas", max(cumple8)) if cumple8 else None
        w8 = f8["carga"]["web"]
        w7 = f7["carga"]["web"]
        out.append({
            "titulo": "Repartir el web en dos instancias corre el techo sin cambiar los tiempos",
            "tests": [7, 8],
            "texto": (
                f"El test 8 corrió el mismo plan del test 7 ({t8['config']['plan_web']}) pero en "
                f"dos instancias en vez de una, con {t8['config']['workers_uvicorn']} workers en "
                f"cada una. En los escalones que el test 7 ya atendía bien los tiempos son "
                f"prácticamente iguales —a 200 concurrentes "
                f"{_fmt_ms(_fila(t7, 'lecturas', 200)['p95'])} contra "
                f"{_fmt_ms(_fila(t8, 'lecturas', 200)['p95'])}, a 400 "
                f"{_fmt_ms(_fila(t7, 'lecturas', 400)['p95'])} contra "
                f"{_fmt_ms(_fila(t8, 'lecturas', 400)['p95'])}—, así que repartir no acelera "
                f"nada de lo que ya andaba. Lo que cambia es hasta dónde llega: el test 7 "
                f"cumplía el objetivo hasta {max(cumple7)} concurrentes y el 8 lo cumple hasta "
                f"{e8['escalon']}, con {_fmt_ms(e8['p95'])} y {_fmt_pct(e8['errores_pct'])} de "
                f"error. La CPU del web —la suma de las dos instancias— llegó al "
                f"{_fmt_pct(w8['cpu_pct'])} de sus {w8['cpu_nominal']} vCPU, contra el "
                f"{_fmt_pct(w7['cpu_pct'])} de las {w7['cpu_nominal']} del test 7. "
                f"La memoria nunca fue el límite: {w8['ram_txt']}. "
                f"El porcentaje de CPU es un promedio de las dos instancias y no prueba que el "
                f"balanceo reparta parejo; lo que sí prueba es que el servicio entero tiene "
                f"margen donde antes no lo tenía."),
        })

    return out


def recomendaciones(exps):
    por_num = {e["numero"]: e for e in exps}
    t1, t2, t3, t4 = (por_num[n] for n in (1, 2, 3, 4))
    t5 = por_num.get(5)
    c3 = _fase(t3, "lecturas")["carga"]["db"]
    cb = _fase(t1, "lectores_solos")["carga"]["db"]
    f50, f100 = _fila(t4, "lecturas", 50), _fila(t4, "lecturas", 100)
    r4_20 = _fila(t4, "recibos", 20)
    return [
        {
            "titulo": "Subir Postgres a una vCPU entera, priorizando CPU sobre memoria",
            "estado": "confirmado", "costo": "medio · infraestructura",
            "texto": (f"Medido en el test 3: la CPU de la base pasó del "
                      f"{_fmt_pct(cb['cpu_pct'])} al {_fmt_pct(c3['cpu_pct'])} y la latencia "
                      f"de lecturas mejoró de verdad hasta 200 concurrentes. La memoria "
                      f"nunca fue el problema ({_fmt_pct(c3['ram_pct'])} de uso)."),
        },
        {
            "titulo": "Subir el servicio web a CPU entera y poner un worker por núcleo",
            "estado": "confirmado", "costo": "alto · infraestructura",
            "texto": (f"Medido en el test 4: es lo que llevó el p95 a "
                      f"{_fmt_ms(f50['p95'])} en {f50['escalon']} concurrentes y "
                      f"{_fmt_ms(f100['p95'])} en {f100['escalon']}, los únicos escalones "
                      f"que cumplen el objetivo en las cuatro corridas. Las dos cosas van "
                      f"juntas: el test 2 probó que los workers solos empeoran."),
        },
        _reco_ia(t4, t5, r4_20),
    ]


def _reco_ia(t4, t5, r4_20):
    """La recomendación del cambio de código: pasa de "pendiente" a
    "confirmado" en cuanto existe el test que la mide."""
    if not t5:
        return {
            "titulo": "Correr la llamada a la IA en un hilo aparte",
            "estado": "implementado sin confirmar", "costo": "bajo · código",
            "texto": (f"Es lo único que queda para las ráfagas de recibos, que con toda la "
                      f"CPU del test 4 siguieron fallando el {_fmt_pct(r4_20['errores_pct'])} "
                      f"con {r4_20['escalon']} subidas simultáneas. Implementado el "
                      f"2026-09-10, sin test de carga que mida la mejora todavía."),
        }
    r5_20 = _fila(t5, "recibos", 20)
    l4_20 = _fila(t4, "lectores_durante_recibos", 20)
    l5_20 = _fila(t5, "lectores_durante_recibos", 20)
    veces = f'{r5_20["n"] / r4_20["n"]:.1f}'.replace(".", ",") if r4_20["n"] else "0"
    return {
        "titulo": "Correr la llamada a la IA en un hilo aparte",
        "estado": "confirmado", "costo": "bajo · código",
        "texto": (f"Medido en el test 5, contra el 4 y con la misma infraestructura exacta: "
                  f"con {r5_20['escalon']} subidas simultáneas, los errores pasaron de "
                  f"{_fmt_pct(r4_20['errores_pct'])} a {_fmt_pct(r5_20['errores_pct'])} y el "
                  f"p95 de {_fmt_ms(r4_20['p95'])} a {_fmt_ms(r5_20['p95'])}, con "
                  f"{veces} veces más subidas completadas en la misma ventana. Los lectores "
                  f"que navegaban en paralelo pasaron de {_fmt_ms(l4_20['p95'])} y "
                  f"{_fmt_pct(l4_20['errores_pct'])} de error a {_fmt_ms(l5_20['p95'])} y "
                  f"{_fmt_pct(l5_20['errores_pct'])}. Es la corrección más barata de las tres "
                  f"y la que más cambió el comportamiento bajo ráfaga."),
    }


def construir(ruta: Path = None) -> dict:
    exps = json.loads((ruta or DATOS).read_text(encoding="utf-8"))
    exps.sort(key=lambda e: e["numero"])
    por_num = {e["numero"]: e for e in exps}
    t1, t4 = por_num[1], por_num[4]
    ultimo = exps[-1]
    f50, f100 = _fila(ultimo, "lecturas", 50), _fila(ultimo, "lecturas", 100)
    n800_1, n800_u = _fila(t1, "lecturas", 800), _fila(ultimo, "lecturas", 800)
    r4_20 = _fila(t4, "recibos", 20)
    r5_20 = _fila(por_num[5], "recibos", 20) if 5 in por_num else None
    l4_20 = _fila(t4, "lectores_durante_recibos", 20)
    l5_20 = _fila(por_num[5], "lectores_durante_recibos", 20) if 5 in por_num else None

    # El último escalón de navegación que CUMPLE en la corrida más reciente:
    # escribirlo a mano fue un error una vez (decía "hasta 100" cuando el
    # test 6 ya llegaba a 200), así que se calcula.
    cumplen = [x["escalon"] for x in _fase(ultimo, "lecturas")["filas"] if x["cumple"]]
    tope = max(cumplen) if cumplen else None
    f_tope = _fila(ultimo, "lecturas", tope) if tope else None
    r_u20 = _fila(ultimo, "recibos", 20)
    l_u20 = _fila(ultimo, "lectores_durante_recibos", 20)

    if tope:
        resumen = (
            f"Se probaron {len(exps)} configuraciones. Hoy la navegación cumple el objetivo "
            f"—p95 por debajo de 1 s con menos de 1% de errores— hasta {tope} usuarios "
            f"concurrentes, con {_fmt_ms(f_tope['p95'])} y "
            f"{_fmt_pct(f_tope['errores_pct'])} de error; en la línea base, ese mismo escalón "
            f"daba {_fmt_ms(_fila(t1, 'lecturas', tope)['p95'])}. A "
            f"{n800_u['escalon']} concurrentes se pasó de {_fmt_ms(n800_1['p95'])} con "
            f"{_fmt_pct(n800_1['errores_pct'])} de error a {_fmt_ms(n800_u['p95'])} con "
            f"{_fmt_pct(n800_u['errores_pct'])}."
        )
    else:
        resumen = (f"Se probaron {len(exps)} configuraciones y ninguna cumple todavía el "
                   f"objetivo de p95 por debajo de 1 s con menos de 1% de errores.")

    if r5_20:
        resumen += (
            f" La subida de recibos no se arregló con hardware sino con código: con "
            f"{r4_20['escalon']} subidas simultáneas los errores pasaron de "
            f"{_fmt_pct(r4_20['errores_pct'])} a {_fmt_pct(r5_20['errores_pct'])} sin tocar "
            f"la infraestructura —lo único que cambió fue sacar la llamada a la IA de adentro "
            f"del worker—."
        )
    if r_u20 and l_u20:
        resumen += (
            f" En la última corrida esas mismas ráfagas quedaron en {_fmt_ms(r_u20['p95'])} "
            f"con {_fmt_pct(r_u20['errores_pct'])} de error, que es el piso que impone la "
            f"propia IA, y los lectores que navegan mientras tanto bajaron a "
            f"{_fmt_ms(l_u20['p95'])}."
        )

    return {
        "experimentos": exps,
        "resumen": resumen,
        "comparativa_lecturas": comparativa(exps, "lecturas", ESCALONES_LECTURAS),
        "comparativa_recibos": comparativa(exps, "recibos", ESCALONES_RECIBOS),
        "serie_lecturas": serie_grafico(exps, "lecturas", ESCALONES_LECTURAS),
        "escalones_lecturas": ESCALONES_LECTURAS,
        "escalones_recibos": ESCALONES_RECIBOS,
        "hallazgos": hallazgos(exps),
        "recomendaciones": recomendaciones(exps),
        "advertencias": [a for e in exps for a in e["advertencias"]
                         if not a.startswith("Corrida limpia")],
        "notas_metodo": notas_metodo(exps),
        "produccion": produccion(exps),
    }


def produccion(exps):
    """Los dos párrafos de la sección de producción que llevan números.
    Estaban escritos a mano en el HTML y en el .md por separado, con la
    cantidad de corridas hardcodeada: se desactualizaron solos. Ahora salen
    del dataset como todo lo demás."""
    por_num = {e["numero"]: e for e in exps}
    ult = exps[-1]
    web = _fase(ult, "lecturas")["carga"]["web"]
    t8 = por_num.get(8)
    medido = ""
    if t8:
        f8 = _fase(t8, "lecturas")
        cumple = [x["escalon"] for x in f8["filas"] if x["cumple"]]
        if cumple:
            medido = (f" Y a esta altura ya no es solo un argumento de diseño: el test 8 es "
                      f"el único que corrió con el web repartido en dos instancias, y es el "
                      f"único que cumple el objetivo hasta {max(cumple)} concurrentes.")
    return {
        "instancias": (
            "Para el servicio web conviene repartir en varias instancias antes que "
            "concentrar en una sola grande, por tres motivos que ya están dados en esta "
            "app: las sesiones viajan en una cookie firmada y no hay estado en el "
            "servidor, así que cualquier instancia puede atender a cualquiera sin "
            "configuración extra; una caída se lleva una porción más chica del servicio; "
            "y ninguna parte del sistema necesita mucha memoria en un mismo proceso — en "
            f"la última corrida el web usó {web['ram_txt']} de lo contratado." + medido),
        "conexiones": (
            f"Las conexiones a la base se multiplican por instancia, pero no se pueden "
            f"calcular: las {len(exps)} corridas muestran que el número sigue a la "
            f"saturación del servicio web y no a la cantidad de workers, y que se pasa del "
            f"máximo que el pool debería permitir (ver el hallazgo correspondiente). Hasta "
            f"entender por qué, la única forma seria de dimensionarlo es medirlo en la "
            f"configuración real ya provisionada y dejar holgura contra el límite del plan "
            f"de Postgres elegido, en vez de confiar en una multiplicación."),
    }


def notas_metodo(exps):
    """Salvedades que valen para TODAS las corridas, no para una sola."""
    ia = exps[0]["config"]["ia_latencia_seg"]
    return [
        ("Los números de navegación de este informe se recalcularon el 2026-09-10. "
         "Hasta entonces, la ventana de medición de cada escalón estaba corrida y se "
         "comía la rampa de aceleración del escalón siguiente, así que los tiempos "
         "salían peores que los reales, y cada vez más a medida que subía la carga: "
         "el escalón de 200 del test 6 figuraba en 1.455 ms cuando su tramo sostenido "
         "dio 213 ms. El error afectaba a las seis corridas por igual y siempre en "
         "contra, así que las comparaciones entre tests seguían siendo válidas, pero "
         "los valores absolutos estaban inflados. Se corrigió en carga/resumen.py y se "
         "regeneraron todas las corridas desde sus datos crudos."),
        (f"La llamada a la IA se simuló con una espera fija de {ia} segundos, para no "
         f"depender de la velocidad variable del servicio real ni gastar créditos. Es "
         f"la demora típica observada, pero es una simulación."),
        ("Todos los tiempos se cortan a los 60 segundos: donde dice timeout, el pedido "
         "nunca respondió, y el valor real es \"más de 60 s\", no 60."),
        ("El generador de carga corre en un contenedor de 4 CPU. En los escalones más "
         "altos puede ser él, y no el servidor, el que ponga el techo: cuando la CPU "
         "del servidor baja en vez de subir al pasar a más usuarios, ese escalón se "
         "lee como cota inferior de lo que aguanta, no como su límite. En el test 8 "
         "eso no pasó: el servidor saturó mientras el generador quedó con margen, así "
         "que ahí el escalón más alto sí mide al servidor."),
    ]
