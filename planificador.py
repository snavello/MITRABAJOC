# -*- coding: utf-8 -*-
"""Aplica solo, a la hora indicada, los cambios de plan programados en la
solapa "Planes" de /entornos.

Por qué vive adentro de la app y no en un Cron Job de Render: un Cron Job es
un servicio más que se factura, y lo que se quiere ahorrar acá son justamente
unos dólares por día. La contrapartida es honesta y está dicha en la
pantalla: si el servicio web está caído a la hora exacta de una regla, ese
disparo se pierde -- aunque la ventana de gracia de abajo cubre el caso
habitual, que es el reinicio provocado por el cambio de plan anterior.

Tres cosas que hacen que esto sea seguro de correr en varias instancias:

- El reclamo de cada regla es un UPDATE condicional en la base
  (db.reclamar_plan_programado), así que dos instancias no pueden aplicar
  la misma regla.
- La marca de reclamo es la hora PROGRAMADA, no la hora real, así que una
  regla dispara a lo sumo una vez por día por más veces que se reinicie el
  proceso.
- La bitácora se abre antes de llamar a Render y se cierra después, porque
  cambiar el plan del web mata a este mismo proceso.
"""
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import db
import render_admin
import render_planes

BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")
INTERVALO_SEG = 30

# Cuánto después de la hora programada todavía se considera que la regla
# tiene que dispararse. Cubre el arranque tras un reinicio: si a las 08:00
# el proceso estaba levantando, a las 08:04 la aplica igual. Más allá de
# esto se da por perdida en vez de aplicar un cambio a destiempo.
GRACIA = timedelta(minutes=10)


def ahora_ba() -> datetime:
    return datetime.now(BUENOS_AIRES)


def toca(regla: dict, ahora: datetime):
    """Si esta regla corresponde ahora, devuelve la marca de su horario
    programado ("AAAA-MM-DD HH:MM"); si no, None.

    Mira también el día de AYER, porque una regla de las 23:55 con la
    ventana de gracia puede tener que dispararse pasada la medianoche."""
    if not regla.get("activo") or not regla.get("plan"):
        return None
    try:
        hh, mm = (int(x) for x in regla["hora"].split(":"))
    except (ValueError, KeyError):
        return None
    for dias_atras in (0, 1):
        dia = (ahora - timedelta(days=dias_atras)).date()
        if dia.isoweekday() not in regla.get("dias", []):
            continue
        programado = datetime.combine(dia, datetime.min.time(),
                                      tzinfo=BUENOS_AIRES).replace(hour=hh, minute=mm)
        if programado <= ahora <= programado + GRACIA:
            marca = programado.strftime("%Y-%m-%d %H:%M")
            if regla.get("ultimo_disparo") != marca:
                return marca
    return None


def aplicar(regla: dict, marca: str) -> dict:
    """Ejecuta una regla ya reclamada. Devuelve el resultado de Render."""
    estado = render_admin.estado_planes()
    lado = estado.get(regla["destino"]) or {}
    anterior = lado.get("plan", "")
    cambio_id = db.registrar_cambio_plan(
        destino=regla["destino"], plan_anterior=anterior, plan_nuevo=regla["plan"],
        detalle=f"programado para las {marca} (hora de Buenos Aires)",
        ok=False, error="en curso", origen="programado", programado_id=regla["id"])

    if regla["destino"] == "db":
        res = render_admin.aplicar_plan_db(regla["plan"])
    else:
        workers = (render_planes.workers_para(regla["plan"])
                   if regla.get("ajustar_workers") else None)
        res = render_admin.aplicar_plan_web(
            regla["plan"], instancias=regla.get("instancias"), workers=workers)

    hechos = ", ".join(res.get("hechos") or []) or "sin cambios (ya estaba así)"
    db.actualizar_cambio_plan(
        cambio_id, ok=not res.get("error"),
        detalle=f"programado para las {marca}: {hechos}",
        error=res.get("error", ""))
    return res


def tick() -> list:
    """Una pasada. Devuelve las reglas efectivamente aplicadas -- se usa en
    los tests, que la llaman directo en vez de esperar al hilo."""
    ahora = ahora_ba()
    aplicadas = []
    for regla in db.planes_programados():
        marca = toca(regla, ahora)
        if not marca:
            continue
        if not db.reclamar_plan_programado(regla["id"], marca):
            continue  # otra instancia se la llevó
        try:
            res = aplicar(regla, marca)
            aplicadas.append({"regla": regla["id"], "marca": marca, **res})
        except Exception as e:
            db.registrar_cambio_plan(
                destino=regla["destino"], plan_anterior="", plan_nuevo=regla["plan"],
                detalle=f"programado para las {marca}", ok=False,
                error=f"{type(e).__name__}: {e}", origen="programado",
                programado_id=regla["id"])
    return aplicadas


def _bucle():
    while True:
        try:
            for a in tick():
                print(f"[planificador] regla {a['regla']} aplicada "
                      f"({a.get('hechos') or a.get('error')})")
        except Exception as e:
            # Nunca dejar que un error tumbe el hilo: la próxima vuelta
            # reintenta. Un planificador muerto en silencio es peor que uno
            # que falla y lo dice en los logs.
            print(f"[planificador] error en la vuelta ({type(e).__name__}: {e})")
        time.sleep(INTERVALO_SEG)


_hilo = None


def arrancar() -> bool:
    """Lanza el hilo. No hace nada si no hay credenciales de Render (no
    habría cómo aplicar) o si PLANIFICADOR=off."""
    global _hilo
    if os.getenv("PLANIFICADOR", "").lower() in ("off", "0", "no"):
        return False
    if not render_admin.configurado():
        return False
    if _hilo and _hilo.is_alive():
        return True
    _hilo = threading.Thread(target=_bucle, name="planificador-planes", daemon=True)
    _hilo.start()
    return True
