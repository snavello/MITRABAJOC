"""Cómo le fue al servidor en el día, en dos líneas para el resumen de Telegram:
una del servicio web y otra de la base. Pedido de Sd (2026-09-23): "si se
congestionó, si tuvo picos en algún horario, con algún número si hace falta".

Lee las mismas métricas que el colector manda a Grafana
(`colector_render.pedir_render`), pero de las últimas 24 horas y de a cinco
minutos: CPU y memoria contra el límite del plan, pedidos HTTP por código de
estado, latencia p95, conexiones de la base. La lectura está separada del
análisis (`analizar` y `texto` son puros y se prueban con series inventadas).

Criterio de "congestión", el mismo que las alertas del tablero pero mirando el
día entero: CPU al 80 % o más en algún momento, cinco o más respuestas 5xx, o
una latencia p95 de tres segundos o más. Con menos que eso, "sin congestión".

Las horas se dicen en Buenos Aires (`fechas.ZONA`): Render devuelve UTC.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import fechas
from . import aplicar_grafana as ag
from . import colector_render as cr

RESOLUCION_S = 300
VENTANA_H = 24
PAUSA_S = 1.2

METRICAS_WEB = [("cpu", {}), ("cpu-limit", {}), ("memory", {}), ("memory-limit", {}),
                ("http-requests", {}), ("http-latency", {"quantile": "0.95"})]
METRICAS_DB = [("cpu", {}), ("cpu-limit", {}), ("memory", {}), ("memory-limit", {}), ("active-connections", {})]

UMBRAL_CPU_PCT = 80
UMBRAL_5XX = 5
UMBRAL_LATENCIA_S = 3.0


# ---------- lectura ----------

def leer(clave: str, cfg: dict, hasta: datetime = None, pausa: float = PAUSA_S) -> dict:
    """{"web": {metrica: respuesta cruda de Render}, "db": {...}}. Una métrica que
    falla queda en None: el análisis dice "sin dato" en vez de inventar."""
    hasta = hasta or datetime.now(timezone.utc)
    desde = hasta - timedelta(hours=VENTANA_H)
    recursos = cfg["metricas_render"]["recursos"]
    salida = {}
    for servicio, lista in (("web", METRICAS_WEB), ("db", METRICAS_DB)):
        salida[servicio] = {}
        for metrica, extra in lista:
            try:
                salida[servicio][metrica] = cr.pedir_render(clave, metrica, recursos[servicio], desde, hasta,
                                                            RESOLUCION_S, extra)
            except cr.ErrorRender as e:
                print(f"[metricas-dia] {e}")
                salida[servicio][metrica] = None
            time.sleep(pausa)
    return salida


# ---------- análisis (puro) ----------

def _puntos(series) -> list:
    """Todos los (timestamp_ms, valor) de todas las series de una métrica."""
    out = []
    for s in series or []:
        for v in s.get("values") or []:
            if v.get("value") is not None:
                out.append((cr.a_milisegundos(v["timestamp"]), float(v["value"])))
    return out


def _pct_contra_limite(uso, limite) -> list:
    """(timestamp, porcentaje) de uso contra el límite del plan. El límite es
    constante en el día salvo cambio de plan: se toma el máximo visto."""
    lim = max((v for _, v in _puntos(limite)), default=0.0)
    if lim <= 0:
        return []
    return [(t, 100.0 * v / lim) for t, v in _puntos(uso)]


def _pico(puntos) -> tuple:
    """(valor máximo, timestamp) o (None, None)."""
    if not puntos:
        return None, None
    t, v = max(puntos, key=lambda p: p[1])
    return v, t


def _hora_ba(ts_ms) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=fechas.ZONA).strftime("%H:%M") if ts_ms is not None else "—"


def _hora_entera_ba(ts_ms) -> int:
    return datetime.fromtimestamp(ts_ms / 1000, tz=fechas.ZONA).hour


def analizar(datos: dict) -> dict:
    web, db = datos.get("web") or {}, datos.get("db") or {}
    a = {"web": {}, "db": {}}

    cpu = _pct_contra_limite(web.get("cpu"), web.get("cpu-limit"))
    a["web"]["cpu_max"], a["web"]["cpu_max_ts"] = _pico(cpu)
    a["web"]["cpu_prom"] = (sum(v for _, v in cpu) / len(cpu)) if cpu else None
    a["web"]["mem_max"], a["web"]["mem_max_ts"] = _pico(_pct_contra_limite(web.get("memory"), web.get("memory-limit")))

    total, cinco_xx, por_hora = 0, 0, {}
    for s in web.get("http-requests") or []:
        estado = next((str(l.get("value", "")) for l in (s.get("labels") or []) if l.get("field") == "statusCode"), "")
        for t, v in _puntos([s]):
            total += v
            por_hora[_hora_entera_ba(t)] = por_hora.get(_hora_entera_ba(t), 0) + v
            if estado.startswith("5"):
                cinco_xx += v
    a["web"]["pedidos"] = int(round(total)) if web.get("http-requests") is not None else None
    a["web"]["cinco_xx"] = int(round(cinco_xx)) if web.get("http-requests") is not None else None
    if por_hora:
        h, n = max(por_hora.items(), key=lambda kv: kv[1])
        a["web"]["hora_pico"], a["web"]["pedidos_hora_pico"] = h, int(round(n))
    else:
        a["web"]["hora_pico"], a["web"]["pedidos_hora_pico"] = None, None
    a["web"]["lat_max"], a["web"]["lat_max_ts"] = _pico(_puntos(web.get("http-latency")))

    cpu_db = _pct_contra_limite(db.get("cpu"), db.get("cpu-limit"))
    a["db"]["cpu_max"], a["db"]["cpu_max_ts"] = _pico(cpu_db)
    a["db"]["cpu_prom"] = (sum(v for _, v in cpu_db) / len(cpu_db)) if cpu_db else None
    a["db"]["mem_max"], a["db"]["mem_max_ts"] = _pico(_pct_contra_limite(db.get("memory"), db.get("memory-limit")))
    a["db"]["conex_max"], a["db"]["conex_max_ts"] = _pico(_puntos(db.get("active-connections")))

    w = a["web"]
    motivos = []
    if w["cpu_max"] is not None and w["cpu_max"] >= UMBRAL_CPU_PCT:
        motivos.append(f"CPU al {w['cpu_max']:.0f} % a las {_hora_ba(w['cpu_max_ts'])}")
    if (w["cinco_xx"] or 0) >= UMBRAL_5XX:
        motivos.append(f"{w['cinco_xx']} respuestas 5xx")
    if w["lat_max"] is not None and w["lat_max"] >= UMBRAL_LATENCIA_S:
        motivos.append(f"latencia p95 de {w['lat_max']:.1f} s a las {_hora_ba(w['lat_max_ts'])}")
    if a["db"]["cpu_max"] is not None and a["db"]["cpu_max"] >= UMBRAL_CPU_PCT:
        motivos.append(f"base con CPU al {a['db']['cpu_max']:.0f} % a las {_hora_ba(a['db']['cpu_max_ts'])}")
    a["congestion"] = motivos
    return a


def _pct(v) -> str:
    return "—" if v is None else f"{v:.0f} %"


def _num(n) -> str:
    """Miles con punto, a la argentina."""
    return "—" if n is None else f"{int(n):,}".replace(",", ".")


def texto(a: dict) -> list:
    """Las dos líneas del resumen (web y base) más el veredicto."""
    w, d = a["web"], a["db"]
    if w.get("cpu_max") is None and w.get("pedidos") is None:
        return ["🖥 Servidor: sin métricas de Render para hoy."]
    veredicto = ("sin congestión" if not a["congestion"] else "hubo congestión: " + "; ".join(a["congestion"]))
    l_web = (f"🖥 Web: {veredicto}. CPU pico {_pct(w['cpu_max'])} a las {_hora_ba(w['cpu_max_ts'])} "
             f"(promedio {_pct(w['cpu_prom'])}), memoria pico {_pct(w['mem_max'])}")
    if w.get("pedidos") is not None:
        l_web += f"; {_num(w['pedidos'])} pedidos"
        if w.get("hora_pico") is not None:
            l_web += (f", hora más cargada {w['hora_pico']:02d}–{(w['hora_pico'] + 1) % 24:02d} h "
                      f"({_num(w['pedidos_hora_pico'])})")
        l_web += f", {_num(w['cinco_xx'])} con error 5xx"
    if w.get("lat_max") is not None:
        l_web += f"; latencia p95 máx {w['lat_max']:.1f} s"
    l_web += "."
    if d.get("cpu_max") is None and d.get("conex_max") is None:
        l_db = "🗄 Base: sin métricas de Render para hoy."
    else:
        l_db = (f"🗄 Base: CPU pico {_pct(d['cpu_max'])} a las {_hora_ba(d['cpu_max_ts'])} "
                f"(promedio {_pct(d['cpu_prom'])}), memoria pico {_pct(d['mem_max'])}")
        if d.get("conex_max") is not None:
            l_db += f", conexiones máx {d['conex_max']:.0f} a las {_hora_ba(d['conex_max_ts'])}"
        l_db += "."
    return [l_web, l_db]


# ---------- de punta a punta ----------

def lineas_del_dia(hasta: datetime = None) -> list:
    """Lo que el resumen agrega. Sin RENDER_API_KEY, una línea que lo dice; si
    Render falla, otra que lo dice. Nunca lanza."""
    clave = os.getenv("RENDER_API_KEY", "").strip()
    if not clave:
        return ["🖥 Servidor: sin RENDER_API_KEY, no se pudieron leer las métricas del día."]
    try:
        return texto(analizar(leer(clave, ag.cargar_config(), hasta)))
    except Exception as e:
        print(f"[metricas-dia] no se pudo armar el resumen del servidor: {type(e).__name__}: {e}")
        return [f"🖥 Servidor: Render no respondió las métricas del día ({type(e).__name__})."]
