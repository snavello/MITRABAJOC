# -*- coding: utf-8 -*-
"""Generador de carga en Python (asyncio + httpx), pensado para correr
DENTRO de un Job de Render disparado desde la pestaña "Tests" de
/entornos (main.py llama a render_admin.crear_job con
"python carga/correr_job.py <test_id>"). Un Job es un contenedor aparte
del que sirve el tráfico real -- si el generador corriera en el mismo
proceso que se está midiendo, competiría por su propia CPU/red y los
números saldrían falsos.

Es un test RÁPIDO gatillable desde la UI, con params más chicos por
default que la corrida de referencia de carga/k6/ (esa sigue siendo la
forma rigurosa de sacar las barandas -- ver carga/README.md). Este script
no junta datos crudos por request: calcula percentiles al vuelo y persiste
solo el resumen + un snapshot de CPU/RAM/conexiones al cierre de cada
escalón (no el máximo continuo como carga/monitor_servidor.py) --
suficiente para un chequeo rápido de salud, no para las barandas finas.

Todo el avance y el resultado final quedan en la tabla TestCarga (db.py) --
es el único canal hacia la página que lo muestra, corriendo en otro
proceso/contenedor.

Uso: python carga/correr_job.py <test_id>
"""
import asyncio
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

import db
import render_admin

BASE_URL = (os.getenv("RENDER_EXTERNAL_URL")
            or {"pruebas": "https://mitrabajo-pruebas.onrender.com",
                "demo": "https://mitrabajo.onrender.com"}.get(os.getenv("ENTORNO", ""), "")).rstrip("/")


def percentil(valores, p):
    if not valores:
        return None
    valores = sorted(valores)
    k = (len(valores) - 1) * p
    f, c = int(k), min(int(k) + 1, len(valores) - 1)
    return valores[f] if f == c else valores[f] + (valores[c] - valores[f]) * (k - f)


def cargar_usuarios():
    ruta = Path(__file__).resolve().parent / "usuarios.csv"
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        filas = [l.strip().split(",") for l in f.readlines()[1:] if l.strip()]
    return [(c, clave) for c, clave in filas]


async def _paso(cliente, metodo, url, resultados, nombre, **kw):
    t0 = time.monotonic()
    try:
        r = await cliente.request(metodo, url, timeout=65, **kw)
        ok = r.status_code < 400
    except Exception:
        r, ok = None, False
    ms = (time.monotonic() - t0) * 1000
    resultados.append((nombre, ms, ok))
    return r, ok


async def journey_lectura(usuarios, resultados, hasta_ts):
    cuil, clave = random.choice(usuarios)
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=True) as cliente:
        while time.monotonic() < hasta_ts:
            await _paso(cliente, "GET", "/ingresar", resultados, "ingresar")
            await asyncio.sleep(random.uniform(2, 5))
            _, ok = await _paso(cliente, "POST", "/trabajador/login", resultados, "login",
                                 data={"cuil": cuil, "clave": clave})
            if not ok:
                await asyncio.sleep(random.uniform(2, 5))
                continue
            for nombre, ruta in (("home", "/app/inicio"), ("novedades", "/app/notificaciones"),
                                  ("app", "/app"), ("credencial", "/api/credencial/qr")):
                await asyncio.sleep(random.uniform(2, 5))
                await _paso(cliente, "GET", ruta, resultados, nombre)


async def journey_recibo(usuarios, imagen_bytes, resultados, hasta_ts):
    cuil, clave = random.choice(usuarios)
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=True) as cliente:
        while time.monotonic() < hasta_ts:
            _, ok = await _paso(cliente, "POST", "/trabajador/login", resultados, "login",
                                 data={"cuil": cuil, "clave": clave})
            if not ok:
                await asyncio.sleep(2)
                continue
            await _paso(cliente, "POST", "/api/leer", resultados, "subir_recibo",
                        files={"archivo": ("recibo.jpg", imagen_bytes, "image/jpeg")})


def resumen_de(resultados, duracion_seg):
    latencias = [ms for (_, ms, ok) in resultados]
    fallos = sum(1 for (_, _, ok) in resultados if not ok)
    n = len(resultados)
    if n == 0:
        return None
    return {
        "p50": round(percentil(latencias, 0.50), 1),
        "p95": round(percentil(latencias, 0.95), 1),
        "p99": round(percentil(latencias, 0.99), 1),
        "errores_pct": round(100 * fallos / n, 2),
        "rps": round(n / duracion_seg, 2),
        "n": n,
    }


async def correr_escalon(tipo, concurrencia, duracion_seg, usuarios, imagen_bytes=None):
    resultados = []
    hasta_ts = time.monotonic() + duracion_seg
    fabrica = journey_lectura if tipo == "lecturas" else journey_recibo
    args = (usuarios, resultados, hasta_ts) if tipo == "lecturas" else (usuarios, imagen_bytes, resultados, hasta_ts)
    tareas = [asyncio.create_task(fabrica(*args)) for _ in range(concurrencia)]
    await asyncio.gather(*tareas, return_exceptions=True)
    return resumen_de(resultados, duracion_seg)


async def main(test_id: int):
    fila = db.test_carga_por_id(test_id)
    if not fila:
        sys.exit(f"TestCarga {test_id} no existe")
    if not BASE_URL:
        db.actualizar_test_carga(test_id, estado="error",
                                  error_detalle="No se pudo determinar la URL propia (RENDER_EXTERNAL_URL/ENTORNO)")
        sys.exit(1)
    params = fila["parametros"]
    tipo = fila["tipo"]
    escalones = params.get("escalones", [50, 100, 200])
    duracion_seg = int(params.get("duracion_seg", 120))
    usuarios = cargar_usuarios()
    if not usuarios:
        db.actualizar_test_carga(test_id, estado="error",
                                  error_detalle="carga/usuarios.csv no existe -- correr preparar_datos.py primero")
        sys.exit(1)

    imagen_bytes = None
    if tipo == "recibos":
        recibos_dir = Path(__file__).resolve().parent / "recibos"
        archivos = sorted(recibos_dir.glob("*.jpg"))
        if not archivos:
            db.actualizar_test_carga(test_id, estado="error", error_detalle="carga/recibos/ está vacío")
            sys.exit(1)
        imagen_bytes = archivos[0].read_bytes()

    resumen_final = []
    for escalon in escalones:
        db.actualizar_test_carga(test_id, avance=f"Corriendo escalón {escalon} ({duracion_seg}s)...")
        st = await correr_escalon(tipo, escalon, duracion_seg, usuarios, imagen_bytes)
        srv = render_admin.estado_servidor()
        fila_resumen = {
            "escalon": escalon,
            **(st or {"p50": None, "p95": None, "p99": None, "errores_pct": None, "rps": 0, "n": 0}),
            "cpu_max": srv.get("cpu_web"), "ram_max": srv.get("ram_web_bytes"),
            "conexiones_pg_max": srv.get("conexiones_db"),
        }
        resumen_final.append(fila_resumen)
        db.actualizar_test_carga(test_id, resumen=resumen_final,
                                  avance=f"Escalón {escalon} listo: p95={fila_resumen['p95']}ms, "
                                         f"errores={fila_resumen['errores_pct']}%")
        # Si un escalón ya reventó (>50% de error), seguir a escalones más
        # grandes no aporta más información y solo gasta tiempo del Job.
        if (fila_resumen.get("errores_pct") or 0) > 50:
            db.actualizar_test_carga(
                test_id, avance=f"Cortado en escalón {escalon}: {fila_resumen['errores_pct']}% de error.")
            break

    from datetime import datetime
    db.actualizar_test_carga(test_id, estado="listo",
                              terminado_en=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python carga/correr_job.py <test_id>")
    tid = int(sys.argv[1])
    try:
        asyncio.run(main(tid))
    except Exception as e:
        db.actualizar_test_carga(tid, estado="error", error_detalle=f"{type(e).__name__}: {e}")
        raise
