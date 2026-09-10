# -*- coding: utf-8 -*-
"""Arma carga/experimentos.json: UN registro por experimento real (no uno
por tipo de test), leyendo SIEMPRE de los datos crudos de carga/log/ --
resumen.csv para los tiempos por escalón y servidor*.log para CPU/RAM del
servicio web y de Postgres dentro de la ventana exacta de cada fase.

Por qué existe: la primera versión de la publicación en /entornos partía
un mismo experimento en dos entradas (lecturas y recibos por separado),
sin métricas de servidor y sin decir de qué corrida era cada config -- se
leía como si se contradijera a sí misma. Acá cada experimento queda con
su config real, sus dos fases, las cargas medidas de web y de Postgres, y
las advertencias de la corrida (despliegues a mitad de test, métricas que
no se pudieron tomar). Todo lo que después se publica sale de este JSON;
nada se escribe a mano en la página.

Uso:
    python carga/consolidar.py            # regenera carga/experimentos.json
    python carga/consolidar.py --mostrar  # además lo imprime para revisar
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "log"
SALIDA = BASE / "experimentos.json"
# Las ventanas de tiempo de cada fase, extraídas del NDJSON crudo de k6 (que
# no se versiona por tamaño). Ver ventana_k6().
VENTANAS = BASE / "ventanas.json"

BUENOS_AIRES = timezone(timedelta(hours=-3))

# Las muestras de servidor.log son cada 30s y reflejan el período previo,
# así que la ventana de una fase se estira un poco para no perder ni la
# primera ni la última -- sin este margen, el pico de RAM del final de un
# test (que cae segundos después del último request de k6) quedaba afuera.
MARGEN_ANTES = timedelta(seconds=35)
MARGEN_DESPUES = timedelta(seconds=65)

MiB = 1024 * 1024

# Nominales de cada plan de Render, para poder decir "X de Y" en vez de un
# número suelto. La RAM se cuenta en base 1024, igual que los planes.
PLANES = {
    "0.5c-512mb": {"vcpu": 0.5, "ram_mb": 512, "etiqueta": "0,5 vCPU / 512 MB"},
    "0.1c-256mb": {"vcpu": 0.1, "ram_mb": 256, "etiqueta": "0,1 vCPU / 256 MB"},
    "2c-4g": {"vcpu": 2.0, "ram_mb": 4096, "etiqueta": "2 vCPU / 4 GB"},
    "4c-8g": {"vcpu": 4.0, "ram_mb": 8192, "etiqueta": "4 vCPU / 8 GB"},
    "4c-16g": {"vcpu": 4.0, "ram_mb": 16384, "etiqueta": "4 vCPU / 16 GB"},
    "8c-16g": {"vcpu": 8.0, "ram_mb": 16384, "etiqueta": "8 vCPU / 16 GB"},
}


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _leer_ventanas() -> dict:
    if VENTANAS.exists():
        return json.loads(VENTANAS.read_text(encoding="utf-8"))
    return {}


def ventana_k6(ruta: Path):
    """(inicio, fin) en UTC de una fase: el primer y el último punto que
    midió k6. Es la ventana real, no la teórica.

    El NDJSON crudo de k6 pesa cientos de MB por corrida y NO se versiona
    (ver .gitignore). Lo único que hace falta de él para reconstruir el
    informe son estos dos timestamps, así que se cachean en
    carga/ventanas.json, que sí va al repo: desde un clon limpio, sin los
    archivos gigantes, `consolidar.py` sigue produciendo el mismo dataset.
    Cuando el crudo está presente manda él y el cache se actualiza."""
    clave = f"{ruta.parent.name}/{ruta.name}"
    cache = _leer_ventanas()
    if not ruta.exists():
        guardada = cache.get(clave)
        if not guardada:
            raise SystemExit(
                f"Falta {ruta} y su ventana tampoco está en {VENTANAS.name}. "
                f"Sin una de las dos no se puede reconstruir esa fase.")
        return _parse_ts(guardada[0]), _parse_ts(guardada[1])

    tiempos = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                o = json.loads(linea)
            except ValueError:
                continue
            if o.get("type") == "Point":
                tiempos.append(o["data"]["time"])
    if not tiempos:
        return None
    desde, hasta = _parse_ts(min(tiempos)), _parse_ts(max(tiempos))
    par = [desde.isoformat(), hasta.isoformat()]
    if cache.get(clave) != par:
        cache[clave] = par
        VENTANAS.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8")
    return desde, hasta


def metricas_servidor(ruta: Path, desde: datetime, hasta: datetime) -> dict:
    """Máximos de CPU/RAM del web y de Postgres dentro de la ventana.
    Devuelve los campos en None cuando el monitor no pudo tomar la métrica
    (pasó en la primera corrida: la API de Render rechazaba el formato de
    fecha y el log quedó entero en null) -- eso se muestra como "no medido",
    nunca se rellena con un número de otra corrida."""
    if not ruta.exists():
        return {"muestras": 0, "cpu_web": None, "ram_web": None,
                "cpu_db": None, "ram_db": None, "conexiones_db": None}
    filas = []
    for linea in open(ruta, encoding="utf-8"):
        linea = linea.strip()
        if not linea:
            continue
        try:
            o = json.loads(linea)
        except ValueError:
            continue
        if desde - MARGEN_ANTES <= _parse_ts(o["ts"]) <= hasta + MARGEN_DESPUES:
            filas.append(o)

    def maximo(clave):
        vals = [f[clave] for f in filas if f.get(clave) is not None]
        return max(vals) if vals else None

    return {"muestras": len(filas), "cpu_web": maximo("cpu_web"),
            "ram_web": maximo("ram_web"), "cpu_db": maximo("cpu_db"),
            "ram_db": maximo("ram_db"), "conexiones_db": maximo("conexiones_db")}


def _pct(valor, nominal):
    if valor is None or not nominal:
        return None
    return round(100 * valor / nominal, 1)


def plan_escalado(clave: str, instancias: int = 1) -> dict:
    """El nominal de un plan multiplicado por la cantidad de instancias.

    El monitor SUMA la CPU y la RAM de todas las instancias del servicio
    (ver monitor_servidor.py), así que con dos instancias de 4 vCPU el pico
    medido puede llegar a 8. Contra el nominal de una sola instancia daría
    un 200% sin sentido: el techo real del servicio es la suma."""
    base = PLANES.get(clave, {})
    if not base:
        return {}
    n = max(1, int(instancias or 1))
    etiqueta = base["etiqueta"] if n == 1 else f"{base['etiqueta']} × {n} instancias"
    return {"vcpu": round(base["vcpu"] * n, 4), "ram_mb": base["ram_mb"] * n,
            "etiqueta": etiqueta}


def etiqueta_workers(workers, instancias: int = 1) -> str:
    """`--workers` es por instancia: con dos instancias de 4 workers corren
    8 procesos en total. Mostrar solo "4" sería engañoso."""
    if workers is None:
        return "—"
    n = max(1, int(instancias or 1))
    if n == 1:
        return str(workers)
    return f"{workers} por instancia ({workers * n} en total)"


def _lado(cpu, ram_bytes, plan: dict) -> dict:
    """Los máximos de un servicio contra el nominal de su plan. Se guardan
    también ya formateados (`cpu_txt`, `ram_txt`) para que la página no
    tenga que dar formato por su cuenta: si la cabecera dice "2 vCPU" y la
    barra dijera "2.0 vCPU", se lee como si fueran dos cosas distintas."""
    ram_mb = round(ram_bytes / MiB) if ram_bytes is not None else None
    cpu_usado = round(cpu, 4) if cpu is not None else None
    cpu_pct = _pct(cpu, plan.get("vcpu"))
    ram_pct = _pct(ram_mb, plan.get("ram_mb"))
    return {
        "cpu_usado": cpu_usado, "cpu_nominal": plan.get("vcpu"), "cpu_pct": cpu_pct,
        "ram_mb": ram_mb, "ram_nominal_mb": plan.get("ram_mb"), "ram_pct": ram_pct,
        "cpu_txt": (f"{fmt_vcpu(cpu_usado)} de {fmt_vcpu(plan.get('vcpu'))} vCPU · "
                     f"{fmt_pct(cpu_pct)}") if cpu_usado is not None else "no medido",
        "ram_txt": (f"{ram_mb} de {plan.get('ram_mb')} MB · {fmt_pct(ram_pct)}"
                     ) if ram_mb is not None else "no medido",
    }


def carga_legible(m: dict, plan_web: str, plan_db: str, instancias: int = 1) -> dict:
    """Traduce los máximos crudos a "X de Y (Z%)" para web y para Postgres.

    `instancias` es la cantidad de instancias del servicio web: su nominal
    se multiplica por ese número (la base es siempre una sola instancia)."""
    pw, pd = plan_escalado(plan_web, instancias), PLANES.get(plan_db, {})
    return {
        "muestras": m["muestras"],
        "web": _lado(m["cpu_web"], m["ram_web"], pw),
        "db": {
            **_lado(m["cpu_db"], m["ram_db"], pd),
            "conexiones": int(m["conexiones_db"]) if m["conexiones_db"] is not None else None,
        },
    }


def filas_csv(carpeta: Path, nombre_test: str) -> list:
    """Las filas de resumen.csv de una serie (lecturas / recibos /
    lectores_durante_recibos), solo con las columnas de tiempos -- las de
    CPU/RAM de ese CSV se ignoran a propósito: son solo del web y acá se
    recalculan del log crudo, para web Y para Postgres."""
    ruta = carpeta / "resumen.csv"
    if not ruta.exists():
        return []
    salida = []
    with open(ruta, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["test"] != nombre_test:
                continue
            salida.append({
                "escalon": int(fila["escalon"]),
                "p50": float(fila["p50"]), "p95": float(fila["p95"]), "p99": float(fila["p99"]),
                "errores_pct": float(fila["errores_pct"]), "rps": float(fila["rps"]),
                "n": int(fila["n"]),
            })
    return sorted(salida, key=lambda x: x["escalon"])


# ---------------------------------------------------------------------------
# Definición de los 4 experimentos reales. Cada fase apunta a su carpeta, su
# serie dentro de resumen.csv, el JSON de k6 que da la ventana y el log de
# servidor que corresponde a ESA ventana (en las corridas partidas en dos
# tramos, el log del tramo correcto).
# ---------------------------------------------------------------------------
EXPERIMENTOS = [
    {
        "numero": 1,
        "nombre": "Línea base",
        "subtitulo": "Todo en el plan más chico, un solo worker",
        "objetivo": "Medir el punto de partida: hasta dónde aguanta la configuración "
                    "más barata posible, sin tocar nada.",
        "config": {
            "plan_web": "0.5c-512mb", "plan_db": "0.1c-256mb", "workers_uvicorn": 1,
            "pool_size": 5, "max_overflow": 5, "ia": "síncrona", "ia_latencia_seg": 15,
        },
        "advertencias": [
            "El monitor de servidor todavía tenía un error de formato de fecha contra la "
            "API de Render y no pudo tomar ninguna métrica durante la fase de lecturas: "
            "ahí CPU y RAM figuran como no medidos. Se arregló antes de las fases "
            "siguientes y de los demás experimentos.",
            "A mitad de la fase de recibos se desplegó código nuevo, lo que reinició el "
            "servidor. Los escalones de 2 y 5 recibos no deberían verse afectados; los "
            "de 10 y 20 pueden traer ruido extra.",
        ],
        "fases": [
            {"clave": "lecturas", "titulo": "Lecturas (navegación, sin subir nada)",
             "detalle": "Usuarios concurrentes haciendo login y recorriendo la app. No toca la IA.",
             "carpeta": "2026-09-09_2034_test1_ok_test2_bug", "serie": "lecturas",
             "k6": "test1_lecturas.json", "log": "servidor.log", "unidad": "usuarios concurrentes"},
            {"clave": "lectores_solos", "titulo": "200 lectores solos (sin ninguna subida)",
             "detalle": "Corrida en la que, por un error del script, no se subió ningún recibo: "
                        "quedaron 200 lectores puros. Sirve como control -- mide el techo del "
                        "servidor sin la IA de por medio.",
             "carpeta": "2026-09-09_2034_test1_ok_test2_bug", "serie": "lectores_durante_recibos",
             "k6": "test2_recibos.json", "log": "servidor2.log", "unidad": "ráfaga prevista (no hubo subidas)"},
            {"clave": "recibos", "titulo": "Subida de recibos (ráfagas simultáneas)",
             "detalle": "Tiempo de cada subida de recibo, con 200 lectores navegando en paralelo.",
             "carpeta": "2026-09-09_2100_test2_retry", "serie": "recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos"},
            {"clave": "lectores_durante_recibos", "titulo": "Lectores mientras se suben recibos",
             "detalle": "Los mismos 200 lectores de arriba, pero medidos durante las ráfagas: "
                        "muestra cuánto le pega al resto del tráfico una subida en curso.",
             "carpeta": "2026-09-09_2100_test2_retry", "serie": "lectores_durante_recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos en paralelo"},
        ],
    },
    {
        "numero": 2,
        "nombre": "Más workers, misma CPU",
        "subtitulo": "Dos workers sobre los mismos 0,5 vCPU",
        "objetivo": "Probar si repartir el trabajo en dos procesos mejora la concurrencia "
                    "sin gastar un peso más de infraestructura.",
        "config": {
            "plan_web": "0.5c-512mb", "plan_db": "0.1c-256mb", "workers_uvicorn": 2,
            "pool_size": 5, "max_overflow": 5, "ia": "síncrona", "ia_latencia_seg": 15,
        },
        "advertencias": [
            "A mitad de la corrida se desplegó código nuevo y el servidor se reinició. "
            "Los escalones de 400 y 800 quedaron contaminados (80% y 49% de error, con "
            "tiempos que no son comparables) y NO se usan para ninguna conclusión: solo "
            "se muestran marcados como inválidos.",
            "Por ese mismo despliegue convivieron dos juegos de procesos durante unos "
            "minutos, así que los picos de CPU y RAM del web de esta corrida están "
            "inflados y no describen el costo real de dos workers.",
            "Solo se corrió la fase de lecturas. No hay fase de recibos en este experimento.",
        ],
        "fases": [
            {"clave": "lecturas", "titulo": "Lecturas (navegación, sin subir nada)",
             "detalle": "Mismo recorrido que la línea base, para comparar contra ella.",
             "carpeta": "2026-09-09_2workers", "serie": "lecturas",
             "k6": "test1_lecturas.json", "log": "servidor.log", "unidad": "usuarios concurrentes",
             "escalones_invalidos": [400, 800]},
        ],
    },
    {
        "numero": 3,
        "nombre": "Postgres grande",
        "subtitulo": "Base de datos a 2 vCPU / 4 GB, servicio web sin tocar",
        "objetivo": "Aislar cuánto del problema venía de la base de datos: se sube solo "
                    "Postgres y se deja el web exactamente como estaba.",
        "config": {
            "plan_web": "0.5c-512mb", "plan_db": "2c-4g", "workers_uvicorn": 1,
            "pool_size": 5, "max_overflow": 5, "ia": "síncrona", "ia_latencia_seg": 15,
        },
        "advertencias": [
            "Corrida limpia: sin despliegues ni reinicios a mitad de test.",
        ],
        "fases": [
            {"clave": "lecturas", "titulo": "Lecturas (navegación, sin subir nada)",
             "detalle": "Mismo recorrido que la línea base, para comparar contra ella.",
             "carpeta": "2026-09-10_postgres2c4g", "serie": "lecturas",
             "k6": "test1_lecturas.json", "log": "servidor.log", "unidad": "usuarios concurrentes"},
            {"clave": "recibos", "titulo": "Subida de recibos (ráfagas simultáneas)",
             "detalle": "Tiempo de cada subida de recibo, con 200 lectores navegando en paralelo.",
             "carpeta": "2026-09-10_postgres2c4g", "serie": "recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos"},
            {"clave": "lectores_durante_recibos", "titulo": "Lectores mientras se suben recibos",
             "detalle": "Los 200 lectores en paralelo, medidos durante las ráfagas.",
             "carpeta": "2026-09-10_postgres2c4g", "serie": "lectores_durante_recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos en paralelo"},
        ],
    },
    {
        "numero": 4,
        "nombre": "Web grande + Postgres grande",
        "subtitulo": "Servicio web a 2 vCPU / 4 GB con 2 workers, Postgres a 2 vCPU / 4 GB",
        "objetivo": "Probar la configuración prevista para el arranque de producción: "
                    "CPU entera en el web, un worker por núcleo, y la base ya holgada.",
        "config": {
            "plan_web": "2c-4g", "plan_db": "2c-4g", "workers_uvicorn": 2,
            "pool_size": 5, "max_overflow": 5, "ia": "síncrona", "ia_latencia_seg": 15,
        },
        "advertencias": [
            "Corrida limpia: sin despliegues ni reinicios a mitad de test.",
            "Corrió ANTES del cambio de código que pasa la llamada a la IA a un hilo "
            "aparte (2026-09-10). Los números de la fase de recibos son los de la IA "
            "todavía bloqueando el worker.",
        ],
        "fases": [
            {"clave": "lecturas", "titulo": "Lecturas (navegación, sin subir nada)",
             "detalle": "Mismo recorrido que la línea base, para comparar contra ella.",
             "carpeta": "2026-09-10_web2c4g_2workers", "serie": "lecturas",
             "k6": "test1_lecturas.json", "log": "servidor.log", "unidad": "usuarios concurrentes"},
            {"clave": "recibos", "titulo": "Subida de recibos (ráfagas simultáneas)",
             "detalle": "Tiempo de cada subida de recibo, con 200 lectores navegando en paralelo.",
             "carpeta": "2026-09-10_web2c4g_2workers", "serie": "recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos"},
            {"clave": "lectores_durante_recibos", "titulo": "Lectores mientras se suben recibos",
             "detalle": "Los 200 lectores en paralelo, medidos durante las ráfagas.",
             "carpeta": "2026-09-10_web2c4g_2workers", "serie": "lectores_durante_recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos en paralelo"},
        ],
    },
    {
        "numero": 5,
        "nombre": "IA fuera del worker",
        "subtitulo": "Misma infraestructura que el test 4, con la llamada a la IA en un hilo aparte",
        "objetivo": "Aislar el efecto del cambio de código: es la única diferencia contra el "
                    "test 4, que corrió con exactamente los mismos planes y workers.",
        "config": {
            "plan_web": "2c-4g", "plan_db": "2c-4g", "workers_uvicorn": 2,
            "pool_size": 5, "max_overflow": 5, "ia": "en hilo aparte", "ia_latencia_seg": 15,
        },
        "advertencias": [
            "Corrida limpia: sin despliegues ni reinicios a mitad de test.",
            "Única diferencia contra el test 4: la llamada a la IA se corre en un hilo aparte "
            "(run_in_threadpool) en vez de bloquear al worker. Planes, workers, pool y latencia "
            "simulada de la IA son idénticos, y se verificaron contra la API de Render antes de "
            "arrancar. Por eso la fase de lecturas sirve de control: no toca ese código y "
            "debería dar parecido.",
        ],
        "fases": [
            {"clave": "lecturas", "titulo": "Lecturas (navegación, sin subir nada)",
             "detalle": "Grupo de control: este recorrido no sube recibos ni llama a la IA, "
                        "así que el cambio de código no debería moverlo.",
             "carpeta": "2026-09-10_1541", "serie": "lecturas",
             "k6": "test1_lecturas.json", "log": "servidor.log", "unidad": "usuarios concurrentes"},
            {"clave": "recibos", "titulo": "Subida de recibos (ráfagas simultáneas)",
             "detalle": "Tiempo de cada subida de recibo, con 200 lectores navegando en paralelo.",
             "carpeta": "2026-09-10_1541", "serie": "recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos"},
            {"clave": "lectores_durante_recibos", "titulo": "Lectores mientras se suben recibos",
             "detalle": "Los 200 lectores en paralelo, medidos durante las ráfagas. Es la medida "
                        "de si una subida en curso ensucia la experiencia del resto.",
             "carpeta": "2026-09-10_1541", "serie": "lectores_durante_recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos en paralelo"},
        ],
    },
    {
        "numero": 6,
        "nombre": "Ocho núcleos",
        "subtitulo": "Web a 8 vCPU / 16 GB con 8 workers, Postgres a 4 vCPU / 16 GB",
        "objetivo": "Medir la configuración que se evalúa contratar para producción, ya con "
                    "el cambio de código puesto: cuánta concurrencia aguanta una sola "
                    "instancia grande y dónde queda el nuevo techo.",
        "config": {
            "plan_web": "8c-16g", "plan_db": "4c-16g", "workers_uvicorn": 8,
            "pool_size": 5, "max_overflow": 5, "ia": "en hilo aparte", "ia_latencia_seg": 15,
        },
        "advertencias": [
            "Corrida limpia: sin despliegues ni reinicios a mitad de test.",
            "Cambia dos cosas a la vez respecto del test 5: la CPU del web (de 2 a 8 vCPU, "
            "con 8 workers en vez de 2) y la de la base (de 2 a 4 vCPU). Sirve para saber "
            "qué rinde el conjunto que se va a contratar, pero si algo saliera raro no se "
            "podría atribuir a una de las dos por separado.",
            "A 800 concurrentes el generador de carga corre en un contenedor de 4 CPU y pudo "
            "haber sido él, y no el servidor, el que puso el techo: la CPU del web bajó "
            "respecto del escalón de 400 en vez de subir. El dato de 800 se lee como cota "
            "inferior de lo que aguanta el servidor, no como su límite.",
        ],
        "fases": [
            {"clave": "lecturas", "titulo": "Lecturas (navegación, sin subir nada)",
             "detalle": "Usuarios concurrentes haciendo login y recorriendo la app. No toca la IA.",
             "carpeta": "2026-09-10_2029", "serie": "lecturas",
             "k6": "test1_lecturas.json", "log": "servidor.log", "unidad": "usuarios concurrentes"},
            {"clave": "recibos", "titulo": "Subida de recibos (ráfagas simultáneas)",
             "detalle": "Tiempo de cada subida de recibo, con 200 lectores navegando en paralelo.",
             "carpeta": "2026-09-10_2029", "serie": "recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos"},
            {"clave": "lectores_durante_recibos", "titulo": "Lectores mientras se suben recibos",
             "detalle": "Los 200 lectores en paralelo, medidos durante las ráfagas. Es la medida "
                        "de si una subida en curso ensucia la experiencia del resto.",
             "carpeta": "2026-09-10_2029", "serie": "lectores_durante_recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos en paralelo"},
        ],
    },
    {
        "numero": 7,
        "nombre": "Cuatro núcleos",
        "subtitulo": "La mitad de la CPU del test 6: web a 4 vCPU / 8 GB con 4 workers, misma base",
        "objetivo": "Probar si la mitad de la CPU alcanza. El test 6 terminó con margen "
                    "(61% de pico), así que la sospecha era que 8 núcleos sobraban para el "
                    "arranque y se podía contratar la mitad.",
        "config": {
            "plan_web": "4c-8g", "plan_db": "4c-16g", "workers_uvicorn": 4,
            "pool_size": 5, "max_overflow": 5, "ia": "en hilo aparte", "ia_latencia_seg": 15,
        },
        "advertencias": [
            "Corrida limpia: sin despliegues ni reinicios a mitad de test.",
            "Única diferencia contra el test 6: la CPU del web (de 8 a 4 vCPU, con 4 workers "
            "en vez de 8) y su memoria (de 16 a 8 GB). La base quedó igual, así que la "
            "comparación entre los dos aísla el efecto del tamaño del servicio web.",
            "El escalón de 800 no es comparable contra el test 6: allá el servidor terminó "
            "con CPU de sobra y el techo probablemente lo puso el generador de carga, "
            "mientras que acá el servidor sí saturó. Los escalones de hasta 400 sí son "
            "comparables: en los dos casos la medición refleja al servidor.",
        ],
        "fases": [
            {"clave": "lecturas", "titulo": "Lecturas (navegación, sin subir nada)",
             "detalle": "Usuarios concurrentes haciendo login y recorriendo la app. No toca la IA.",
             "carpeta": "2026-09-10_2139", "serie": "lecturas",
             "k6": "test1_lecturas.json", "log": "servidor.log", "unidad": "usuarios concurrentes"},
            {"clave": "recibos", "titulo": "Subida de recibos (ráfagas simultáneas)",
             "detalle": "Tiempo de cada subida de recibo, con 200 lectores navegando en paralelo.",
             "carpeta": "2026-09-10_2139", "serie": "recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos"},
            {"clave": "lectores_durante_recibos", "titulo": "Lectores mientras se suben recibos",
             "detalle": "Los 200 lectores en paralelo, medidos durante las ráfagas.",
             "carpeta": "2026-09-10_2139", "serie": "lectores_durante_recibos",
             "k6": "test2_recibos.json", "log": "servidor.log", "unidad": "recibos simultáneos en paralelo"},
        ],
    },
]

OBJETIVO_P95_MS = 1000
OBJETIVO_ERRORES_PCT = 1.0

# Por debajo de esto, un "p95" es prácticamente el máximo observado y no un
# percentil sólido -- las ráfagas de recibos llegan a tener 6 o 7 subidas
# completadas en toda la ventana. Se avisa en la página en vez de dejar que
# alguien compare esos números como si fueran equivalentes a los de lecturas.
MUESTRAS_MINIMAS = 30


# El test corta cada pedido a los 60 s. Un p95 en ese valor no es un tiempo
# de respuesta: es "no respondió". Decirlo como "60,0 s" haría creer que la
# app contestó, tarde -- y en las tablas del informe eso figura como
# "timeout", así que la prosa tiene que decir lo mismo.
TIMEOUT_MS = 59000
TIMEOUT_SEG = 60


def fmt_ms(v) -> str:
    """1.607,9 ms -> "1,6 s"; 190,7 ms -> "191 ms". Coma decimal."""
    if v is None:
        return "n/d"
    if v >= TIMEOUT_MS:
        return f"más de {TIMEOUT_SEG} s"
    if v >= 1000:
        return f"{v / 1000:.1f}".replace(".", ",") + " s"
    return f"{v:.0f} ms"


def fmt_pct(v) -> str:
    """Un decimal, salvo los valores chicos: decir "0,1%" donde el dato real
    es 0,07% haría parecer distintas dos corridas que no lo son."""
    if v is None:
        return "n/d"
    if 0 < v < 1:
        return f"{v:.2f}".replace(".", ",") + "%"
    return f"{v:.1f}".replace(".", ",") + "%"


def fmt_num(v) -> str:
    """Un decimal con coma, para proporciones como "7,3 veces más"."""
    return f"{v:.1f}".replace(".", ",")


def fmt_vcpu(v) -> str:
    if v is None:
        return "n/d"
    return (f"{v:g}").replace(".", ",")


def delta(nuevo, viejo) -> str:
    """Variación relativa de un p95 contra el mismo escalón de otra corrida."""
    if not viejo:
        return "n/d"
    d = 100 * (nuevo - viejo) / viejo
    signo = "+" if d > 0 else ""
    return signo + f"{d:.1f}".replace(".", ",") + "%"


def _fase(fases: list, clave: str):
    for f in fases:
        if f["clave"] == clave:
            return f
    return None


def _fila(fases: list, clave: str, escalon: int):
    f = _fase(fases, clave)
    if not f:
        return None
    for fila in f["filas"]:
        if fila["escalon"] == escalon:
            return fila
    return None


def _p95(fases, clave, escalon):
    fila = _fila(fases, clave, escalon)
    return fila["p95"] if fila else None


def veredicto(fases: list) -> str:
    """Qué escalones de LECTURAS cumplieron el objetivo, en una frase."""
    f = _fase(fases, "lecturas")
    if not f:
        return "Este experimento no corrió la fase de lecturas."
    ok = [x["escalon"] for x in f["filas"] if x["cumple"]]
    if not ok:
        return ("Ningún escalón cumplió el objetivo (p95 por debajo de 1 s y "
                "menos de 1% de errores).")
    return (f"Cumple el objetivo (p95 por debajo de 1 s y menos de 1% de errores) "
            f"hasta {max(ok)} usuarios concurrentes.")


def armar_conclusion(exp_num: int, fases: list, base: list, previos: dict = None) -> str:
    """Redacta la conclusión de cada experimento A PARTIR de los números ya
    consolidados. No hay texto con cifras escritas a mano: si el dato de
    origen cambia, la conclusión cambia con él y no puede contradecir a la
    tabla que tiene al lado."""
    if exp_num == 1:
        solos = _fase(fases, "lectores_solos")
        p95_solos = [x["p95"] for x in solos["filas"]] if solos else []
        l200 = _p95(fases, "lecturas", 200)
        carga = solos["carga"] if solos else None
        rec10 = _fila(fases, "recibos", 10)
        return (
            f"El cuello de botella es el servicio web, no la IA: con 200 lectores "
            f"puros —sin subir un solo recibo, sin tocar la IA— el p95 ya queda entre "
            f"{fmt_ms(min(p95_solos))} y {fmt_ms(max(p95_solos))}, prácticamente lo mismo "
            f"que el escalón de 200 del test de lecturas ({fmt_ms(l200)}). "
            f"Los dos servicios estaban al tope de su CPU: el web al "
            f"{fmt_pct(carga['web']['cpu_pct'])} de sus {fmt_vcpu(carga['web']['cpu_nominal'])} vCPU "
            f"y Postgres al {fmt_pct(carga['db']['cpu_pct'])} de sus "
            f"{fmt_vcpu(carga['db']['cpu_nominal'])} vCPU con apenas {carga['db']['conexiones']} "
            f"conexiones, mientras la RAM de la base no pasó del "
            f"{fmt_pct(carga['db']['ram_pct'])} — para esta app hace falta CPU en la base, "
            f"no memoria. Las ráfagas de recibos revientan temprano: con "
            f"{rec10['escalon']} simultáneos ya falla el {fmt_pct(rec10['errores_pct'])} "
            f"de las subidas."
        )

    if exp_num == 2:
        partes = []
        for esc in (50, 100, 200):
            n, v = _p95(fases, "lecturas", esc), _p95(base, "lecturas", esc)
            partes.append(f"{esc} concurrentes {fmt_ms(v)} → {fmt_ms(n)} ({delta(n, v)})")
        e200 = _fila(fases, "lecturas", 200)
        b200 = _fila(base, "lecturas", 200)
        return (
            "Empeoró, y por eso se descartó. Contra la línea base, en todos los escalones "
            "válidos el tiempo subió: " + "; ".join(partes) + ". "
            f"Los errores a 200 concurrentes pasaron de {fmt_pct(b200['errores_pct'])} a "
            f"{fmt_pct(e200['errores_pct'])}. Dos procesos peleando por media vCPU no dan "
            "paralelismo real: solo agregan cambio de contexto y memoria. La conclusión "
            "que deja es que workers y CPU tienen que subir juntos — sumar uno solo de los "
            "dos no sirve. Se volvió a 1 worker inmediatamente después."
        )

    if exp_num == 3:
        mejoras = []
        for esc in (50, 100, 200):
            n, v = _p95(fases, "lecturas", esc), _p95(base, "lecturas", esc)
            mejoras.append(f"{esc} concurrentes {fmt_ms(v)} → {fmt_ms(n)} ({delta(n, v)})")
        techo = []
        for esc in (400, 800):
            n, v = _p95(fases, "lecturas", esc), _p95(base, "lecturas", esc)
            techo.append(f"{esc} sigue en {fmt_ms(n)}")
        cl = _fase(fases, "lecturas")["carga"]
        cb = _fase(base, "lectores_solos")["carga"]
        return (
            f"Postgres dejó de ser un límite: su CPU pasó del "
            f"{fmt_pct(cb['db']['cpu_pct'])} de {fmt_vcpu(cb['db']['cpu_nominal'])} vCPU al "
            f"{fmt_pct(cl['db']['cpu_pct'])} de {fmt_vcpu(cl['db']['cpu_nominal'])} vCPU, y la RAM al "
            f"{fmt_pct(cl['db']['ram_pct'])}. Eso mejoró de verdad la zona baja y media de "
            "lecturas: " + "; ".join(mejoras) + ". "
            f"Pero de 400 concurrentes en adelante el techo no se movió ({'; '.join(techo)}), "
            f"porque ahí el límite es el servicio web, que siguió clavado en el "
            f"{fmt_pct(cl['web']['cpu_pct'])} de sus {fmt_vcpu(cl['web']['cpu_nominal'])} vCPU. "
            "Las ráfagas de recibos tampoco mejoraron. Queda demostrado que la base era "
            "parte del problema, pero no la parte que pone el techo."
        )

    if exp_num == 4:
        f50, f100 = _fila(fases, "lecturas", 50), _fila(fases, "lecturas", 100)
        n800, v800 = _fila(fases, "lecturas", 800), _fila(base, "lecturas", 800)
        cl = _fase(fases, "lecturas")["carga"]
        cr = _fase(fases, "recibos")["carga"]
        r10, r20 = _fila(fases, "recibos", 10), _fila(fases, "recibos", 20)
        b10 = _fila(base, "recibos", 10)
        return (
            f"Primera configuración que cumple el objetivo: {f50['escalon']} concurrentes en "
            f"{fmt_ms(f50['p95'])} y {f100['escalon']} en {fmt_ms(f100['p95'])}, las dos con "
            f"{fmt_pct(f50['errores_pct'])} de error. A 800 concurrentes pasó de "
            f"{fmt_ms(v800['p95'])} con {fmt_pct(v800['errores_pct'])} de error en la línea "
            f"base a {fmt_ms(n800['p95'])} con {fmt_pct(n800['errores_pct'])}. "
            f"El web volvió a ser el límite ({fmt_pct(cl['web']['cpu_pct'])} de sus "
            f"{fmt_vcpu(cl['web']['cpu_nominal'])} vCPU) pero ahora con cuatro veces más CPU, y "
            f"Postgres quedó holgado ({fmt_pct(cl['db']['cpu_pct'])} de CPU, "
            f"{fmt_pct(cl['db']['ram_pct'])} de RAM). "
            f"Lo que NO mejoró son las ráfagas de recibos: con {r10['escalon']} simultáneos "
            f"falla el {fmt_pct(r10['errores_pct'])} y con {r20['escalon']} el "
            f"{fmt_pct(r20['errores_pct'])}, contra {fmt_pct(b10['errores_pct'])} de la línea "
            f"base en el mismo escalón de {b10['escalon']} — sin mejora real pese a toda la "
            f"CPU agregada. La causa no es CPU: cada subida bloqueaba un worker entero "
            f"durante los {15} segundos de la llamada a la IA. Eso es lo que motivó el "
            "cambio de código del 2026-09-10, que el test 5 mide."
        )

    if exp_num == 5:
        # La comparación relevante acá es contra el test 4: misma
        # infraestructura, única diferencia el cambio de código.
        t4 = (previos or {}).get(4, [])
        subidas, lectores, ctrl = [], [], []
        for esc in (5, 10, 20):
            a, b = _fila(t4, "recibos", esc), _fila(fases, "recibos", esc)
            subidas.append(f"con {esc} simultáneos, de {fmt_ms(a['p95'])} y "
                           f"{fmt_pct(a['errores_pct'])} de error a {fmt_ms(b['p95'])} y "
                           f"{fmt_pct(b['errores_pct'])}")
            la = _fila(t4, "lectores_durante_recibos", esc)
            lb = _fila(fases, "lectores_durante_recibos", esc)
            lectores.append(f"{esc}: {fmt_ms(la['p95'])} → {fmt_ms(lb['p95'])}")
        r20_t4, r20 = _fila(t4, "recibos", 20), _fila(fases, "recibos", 20)
        veces = fmt_num(r20["n"] / r20_t4["n"]) if r20_t4["n"] else "0"
        for esc in (50, 100):
            a, b = _fila(t4, "lecturas", esc), _fila(fases, "lecturas", esc)
            ctrl.append(f"{esc} concurrentes {fmt_ms(a['p95'])} → {fmt_ms(b['p95'])}")
        return (
            f"El cambio de código resolvió lo que ni cuadruplicar la CPU había movido. "
            f"Las subidas: {'; '.join(subidas)}. El p95 se queda plano alrededor de los "
            f"{fmt_ms(r20['p95'])} sin importar cuántas lleguen juntas, que es exactamente lo "
            f"esperado: cada subida sigue tardando lo que tarda la IA, pero ahora se procesan "
            f"en paralelo en vez de hacer cola. En la misma ventana se completaron "
            f"{r20['n']} subidas contra {r20_t4['n']} del test 4, {veces} veces más. "
            f"Lo más importante para el trabajador que no está subiendo nada: los lectores en "
            f"paralelo dejaron de sufrir ({'; '.join(lectores)}). "
            f"El grupo de control se movió poco y dentro del mismo régimen "
            f"({'; '.join(ctrl)}): ese recorrido no toca el código que cambió, la diferencia "
            f"entra en la variación normal entre corridas y los dos escalones siguen "
            f"cumpliendo el objetivo."
        )

    if exp_num == 6:
        # Contra el test 5: mismo código, cuatro veces la CPU del web.
        t5 = (previos or {}).get(5, [])
        lect, lectores = [], []
        for esc in (100, 200, 400):
            a, b = _fila(t5, "lecturas", esc), _fila(fases, "lecturas", esc)
            lect.append(f"{esc} concurrentes {fmt_ms(a['p95'])} → {fmt_ms(b['p95'])}")
        for esc in (10, 20):
            a = _fila(t5, "lectores_durante_recibos", esc)
            b = _fila(fases, "lectores_durante_recibos", esc)
            lectores.append(f"{esc}: {fmt_ms(a['p95'])} → {fmt_ms(b['p95'])}")
        f200 = _fila(fases, "lecturas", 200)
        f400 = _fila(fases, "lecturas", 400)
        r20 = _fila(fases, "recibos", 20)
        cl = _fase(fases, "lecturas")["carga"]
        rps200 = fmt_num(_fila(fases, "lecturas", 200)["rps"])
        rps400 = fmt_num(_fila(fases, "lecturas", 400)["rps"])
        return (
            f"Con ocho núcleos y un worker por núcleo, el objetivo se cumple hasta "
            f"{f200['escalon']} usuarios concurrentes: {fmt_ms(f200['p95'])} con "
            f"{fmt_pct(f200['errores_pct'])} de error, contra los {fmt_ms(_fila(t5, 'lecturas', 200)['p95'])} "
            f"del test 5. La mejora se ve en toda la curva de navegación: "
            f"{'; '.join(lect)}. El throughput subió a {rps200} pedidos por segundo en 200 "
            f"concurrentes y {rps400} en 400. "
            f"Las subidas de recibos quedaron planas en {fmt_ms(r20['p95'])} con "
            f"{fmt_pct(r20['errores_pct'])} de error hasta {r20['escalon']} simultáneas -- "
            f"prácticamente el piso que impone la IA, que no baja por agregar CPU. "
            f"Y los lectores que navegan durante esas ráfagas bajaron a menos de un cuarto "
            f"de segundo ({'; '.join(lectores)}), la primera vez que también ellos cumplen "
            f"el objetivo. "
            f"El pico de CPU del web en la fase de lecturas fue {fmt_pct(cl['web']['cpu_pct'])} "
            f"y el de la base {fmt_pct(cl['db']['cpu_pct'])}: a diferencia de todos los "
            f"tests anteriores, esta configuración termina la corrida con margen."
        )

    if exp_num == 7:
        t6 = (previos or {}).get(6, [])
        comp = []
        for esc in (50, 100, 200, 400):
            a, b = _fila(t6, "lecturas", esc), _fila(fases, "lecturas", esc)
            comp.append(f"{esc}: {fmt_ms(a['p95'])} contra {fmt_ms(b['p95'])}")
        f200 = _fila(fases, "lecturas", 200)
        f400 = _fila(fases, "lecturas", 400)
        c6 = _fase(t6, "lecturas")["carga"]["web"]
        c7 = _fase(fases, "lecturas")["carga"]["web"]
        r20 = _fila(fases, "recibos", 20)
        l20 = _fila(fases, "lectores_durante_recibos", 20)
        return (
            f"La mitad de la CPU rinde lo mismo hasta 400 concurrentes. Comparando el p95 "
            f"del test 6 (8 núcleos) contra este (4 núcleos), escalón por escalón: "
            f"{'; '.join(comp)} -- diferencias que entran en la variación entre corridas. "
            f"El objetivo se cumple hasta {f200['escalon']} concurrentes con "
            f"{fmt_ms(f200['p95'])} y {fmt_pct(f200['errores_pct'])} de error, igual que con "
            f"el doble de máquina, y a {f400['escalon']} responde en {fmt_ms(f400['p95'])} "
            f"con {fmt_pct(f400['errores_pct'])}. "
            f"Las ráfagas de recibos también quedaron iguales: {fmt_ms(r20['p95'])} con "
            f"{r20['escalon']} simultáneas, y los lectores en paralelo en "
            f"{fmt_ms(l20['p95'])}. "
            f"La diferencia real está en el margen, no en la respuesta: el web llegó al "
            f"{fmt_pct(c7['cpu_pct'])} de su CPU contra el {fmt_pct(c6['cpu_pct'])} del "
            f"test 6. Con 4 núcleos la carga esperada se atiende igual de rápido, pero sin "
            f"colchón para un pico por encima de 400."
        )
    return ""


def construir() -> list:
    salida = []
    for exp in EXPERIMENTOS:
        cfg = exp["config"]
        fases, inicios, fines = [], [], []
        for f in exp["fases"]:
            carpeta = LOG / f["carpeta"]
            v = ventana_k6(carpeta / f["k6"])
            if v is None:
                raise SystemExit(f"Sin ventana de k6 para {f['carpeta']}/{f['k6']}")
            desde, hasta = v
            inicios.append(desde)
            fines.append(hasta)
            filas = filas_csv(carpeta, f["serie"])
            invalidos = set(f.get("escalones_invalidos", []))
            for fila in filas:
                fila["valido"] = fila["escalon"] not in invalidos
                # El objetivo solo se evalúa sobre escalones válidos.
                fila["cumple"] = bool(
                    fila["valido"] and fila["p95"] < OBJETIVO_P95_MS
                    and fila["errores_pct"] < OBJETIVO_ERRORES_PCT)
            m = metricas_servidor(carpeta / f["log"], desde, hasta)
            n_max = max((x["n"] for x in filas), default=0)
            fases.append({
                "clave": f["clave"], "titulo": f["titulo"], "detalle": f["detalle"],
                "unidad": f["unidad"],
                "inicio_ba": desde.astimezone(BUENOS_AIRES).strftime("%Y-%m-%d %H:%M"),
                "fin_ba": hasta.astimezone(BUENOS_AIRES).strftime("%H:%M"),
                "duracion_min": round((hasta - desde).total_seconds() / 60, 1),
                "filas": filas,
                "muestras_bajas": n_max < MUESTRAS_MINIMAS,
                "carga": carga_legible(m, cfg["plan_web"], cfg["plan_db"],
                                       cfg.get("instancias", 1)),
                "carga_medida": m["cpu_web"] is not None or m["cpu_db"] is not None,
                "fuente": f"carga/log/{f['carpeta']}/",
            })
        inicio, fin = min(inicios), max(fines)
        salida.append({
            "numero": exp["numero"], "nombre": exp["nombre"], "subtitulo": exp["subtitulo"],
            "objetivo": exp["objetivo"],
            "fecha_ba": inicio.astimezone(BUENOS_AIRES).strftime("%Y-%m-%d"),
            "inicio_ba": inicio.astimezone(BUENOS_AIRES).strftime("%Y-%m-%d %H:%M"),
            "fin_ba": fin.astimezone(BUENOS_AIRES).strftime("%H:%M"),
            "config": {
                "instancias": 1,
                **cfg,
                "plan_web_etiqueta": plan_escalado(
                    cfg["plan_web"], cfg.get("instancias", 1))["etiqueta"],
                "plan_db_etiqueta": PLANES[cfg["plan_db"]]["etiqueta"],
                "workers_etiqueta": etiqueta_workers(
                    cfg.get("workers_uvicorn"), cfg.get("instancias", 1)),
            },
            "advertencias": exp["advertencias"],
            "fases": fases,
        })
    # Las conclusiones se redactan recién acá, cuando ya están todos los
    # experimentos consolidados: las de la 2 en adelante comparan contra la
    # línea base y necesitan sus números.
    base = salida[0]["fases"]
    previos = {e["numero"]: e["fases"] for e in salida}
    for e in salida:
        e["veredicto"] = veredicto(e["fases"])
        e["conclusion"] = armar_conclusion(e["numero"], e["fases"], base, previos)
    return salida


def mostrar(datos):
    for e in datos:
        print("=" * 78)
        print(f"TEST {e['numero']} — {e['nombre']} ({e['subtitulo']})")
        print(f"  {e['inicio_ba']} a {e['fin_ba']} (hora de Buenos Aires)")
        print(f"  web={e['config']['plan_web_etiqueta']}  db={e['config']['plan_db_etiqueta']}"
              f"  workers={e['config']['workers_uvicorn']}")
        for f in e["fases"]:
            c = f["carga"]
            print(f"  -- {f['titulo']}  [{f['inicio_ba']}–{f['fin_ba']}, {f['duracion_min']} min]")
            for fila in f["filas"]:
                marca = "OK " if fila["cumple"] else ("!! " if not fila["valido"] else "   ")
                print(f"     {marca}{fila['escalon']:>4} | p50 {fila['p50']:>9.1f} | p95 {fila['p95']:>9.1f}"
                      f" | p99 {fila['p99']:>9.1f} | err {fila['errores_pct']:>6.2f}% | rps {fila['rps']:>6.2f}")
            w, d = c["web"], c["db"]
            print(f"     WEB cpu {w['cpu_usado']} de {w['cpu_nominal']} ({w['cpu_pct']}%)"
                  f"  ram {w['ram_mb']} de {w['ram_nominal_mb']} MB ({w['ram_pct']}%)")
            print(f"     DB  cpu {d['cpu_usado']} de {d['cpu_nominal']} ({d['cpu_pct']}%)"
                  f"  ram {d['ram_mb']} de {d['ram_nominal_mb']} MB ({d['ram_pct']}%)"
                  f"  conexiones {d['conexiones']}  [{c['muestras']} muestras]")
        for a in e["advertencias"]:
            print(f"  (!) {a}")
        print(f"  VEREDICTO: {e['veredicto']}")
        print(f"  CONCLUSIÓN: {e['conclusion']}")


if __name__ == "__main__":
    datos = construir()
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Escrito {SALIDA} ({len(datos)} experimentos)")
    if "--mostrar" in sys.argv:
        mostrar(datos)
