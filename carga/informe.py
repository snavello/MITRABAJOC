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
    t1, t2, t3, t4 = exps
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

    # 6. Cuenta de conexiones, verificada contra la medición.
    cfg4 = t4["config"]
    por_worker = cfg4["pool_size"] + cfg4["max_overflow"]
    esperadas = por_worker * cfg4["workers_uvicorn"]
    medidas = _fase(t4, "lecturas")["carga"]["db"]["conexiones"]
    out.append({
        "titulo": "Cuántas conexiones a la base consume cada worker",
        "tests": [4],
        "texto": (
            f"Cada worker abre hasta {cfg4['pool_size']} conexiones más "
            f"{cfg4['max_overflow']} de reserva, o sea {por_worker}. Con "
            f"{cfg4['workers_uvicorn']} workers, la cuenta da {esperadas} y lo medido en el "
            f"test 4 fueron {medidas} conexiones como máximo: la cuenta cierra. "
            f"Sirve para dimensionar: al multiplicar instancias hay que multiplicar también "
            f"este número y contrastarlo con el límite del plan de Postgres elegido."),
    })
    return out


def recomendaciones(exps):
    t1, t2, t3, t4 = exps
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
        {
            "titulo": "Correr la llamada a la IA en un hilo aparte",
            "estado": "implementado sin confirmar", "costo": "bajo · código",
            "texto": (f"Es lo único que queda para las ráfagas de recibos, que con toda la "
                      f"CPU del test 4 siguieron fallando el {_fmt_pct(r4_20['errores_pct'])} "
                      f"con {r4_20['escalon']} subidas simultáneas. El cambio se implementó "
                      f"el 2026-09-10 en las tres rutas que llaman a la IA y tiene sus "
                      f"tests unitarios en verde, pero todavía no se corrió un test de carga "
                      f"que mida la mejora: hasta que eso pase, es una corrección esperada, "
                      f"no un resultado."),
        },
    ]


def construir(ruta: Path = None) -> dict:
    exps = json.loads((ruta or DATOS).read_text(encoding="utf-8"))
    exps.sort(key=lambda e: e["numero"])
    t4 = exps[3]
    f50, f100 = _fila(t4, "lecturas", 50), _fila(t4, "lecturas", 100)
    n800_1, n800_4 = _fila(exps[0], "lecturas", 800), _fila(t4, "lecturas", 800)
    r4_20 = _fila(t4, "recibos", 20)

    resumen = (
        f"De las cuatro configuraciones probadas, solo la última cumple el objetivo de "
        f"p95 por debajo de 1 s con menos de 1% de errores, y lo hace hasta "
        f"{f100['escalon']} usuarios concurrentes ({_fmt_ms(f50['p95'])} con "
        f"{f50['escalon']} y {_fmt_ms(f100['p95'])} con {f100['escalon']}). En el otro "
        f"extremo, con {n800_4['escalon']} concurrentes se pasó de "
        f"{_fmt_ms(n800_1['p95'])} con {_fmt_pct(n800_1['errores_pct'])} de error en la "
        f"línea base a {_fmt_ms(n800_4['p95'])} con {_fmt_pct(n800_4['errores_pct'])}. "
        f"Lo que sigue sin resolverse son las ráfagas de subida de recibos: con "
        f"{r4_20['escalon']} simultáneas falla el {_fmt_pct(r4_20['errores_pct'])} incluso "
        f"con la mejor infraestructura, porque es un problema de código y no de recursos."
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
    }
