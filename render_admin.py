"""Cliente mínimo de la API de Render (api.render.com/v1), sin dependencias
nuevas (urllib de la stdlib). Dos usos:

- main.py: la pestaña "Tests" de /entornos lo usa para mostrar CPU/RAM/plan
  del servicio y de la base, y para crear el Job que corre el test.
- carga/correr_job.py: el Job en sí lo usa para muestrear CPU/RAM/
  conexiones del servidor mientras corre (mismo mecanismo que
  carga/monitor_servidor.py, consolidado acá para no duplicar código).

Sin RENDER_API_KEY (o sin RENDER_WEB_SERVICE_ID/RENDER_DB_ID), todas las
funciones devuelven None/error en vez de tirar excepción -- la pestaña
Tests tiene que poder mostrarse igual, con un aviso, si todavía no se
configuraron estas variables."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.render.com/v1"


def configurado() -> bool:
    return bool(os.getenv("RENDER_API_KEY") and os.getenv("RENDER_WEB_SERVICE_ID"))


def _api_key() -> str:
    return os.getenv("RENDER_API_KEY", "")


def _peticion(path: str, metodo: str = "GET", body: dict | list | None = None):
    datos = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=datos, method=metodo,
        headers={"Authorization": f"Bearer {_api_key()}", "Accept": "application/json",
                 **({"Content-Type": "application/json"} if datos else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _ultimo_valor(resource_id: str, endpoint: str, minutos: int = 2):
    if not resource_id:
        return None
    hasta = datetime.now(timezone.utc)
    desde = hasta - timedelta(minutes=minutos)
    fmt = "%Y-%m-%dT%H:%M:%SZ"  # Render exige este formato exacto, sin microsegundos
    qs = urllib.parse.urlencode({
        "resource": resource_id, "startTime": desde.strftime(fmt),
        "endTime": hasta.strftime(fmt), "resolutionSeconds": 30,
    })
    try:
        series = _peticion(f"/metrics/{endpoint}?{qs}")
    except Exception:
        return None
    if not series:
        return None
    total, alguno = 0.0, False
    for serie in series:
        valores = serie.get("values") or []
        if valores:
            total += valores[-1].get("value", 0)
            alguno = True
    return total if alguno else None


def _workers_del_start_command(web_id: str):
    """Lee el Start Command REAL del servicio y le busca "--workers N" --
    nunca hardcodeado, porque es justo el número que estamos ajustando
    para resolver el cuello de botella del informe. Sin la bandera,
    uvicorn arranca con 1 (el default), así que ese es el resultado."""
    try:
        detalle = _peticion(f"/services/{web_id}")
    except Exception:
        return None, None
    cmd = (detalle.get("serviceDetails", {}).get("envSpecificDetails", {})
           .get("startCommand", ""))
    import re
    m = re.search(r"--workers[= ](\d+)", cmd)
    workers = int(m.group(1)) if m else 1
    plan = detalle.get("serviceDetails", {}).get("plan", "")
    return workers, plan


def _plan_postgres(db_id: str):
    try:
        detalle = _peticion(f"/postgres/{db_id}")
    except Exception:
        return None
    return detalle.get("plan", "")


def estado_servidor() -> dict:
    """CPU/RAM actuales del web service y de la base, más la configuración
    real leída de la API (workers del Start Command, plan de cada uno) --
    para el panel de detalle de la pestaña Tests. Los valores en None son
    huecos (sin RENDER_API_KEY o falló la llamada) que la plantilla
    muestra como "no disponible", nunca como cero."""
    web_id = os.getenv("RENDER_WEB_SERVICE_ID", "")
    db_id = os.getenv("RENDER_DB_ID", "")
    workers, plan_web = (_workers_del_start_command(web_id)
                          if (configurado() and web_id) else (None, None))
    return {
        "configurado": configurado(),
        "cpu_web": _ultimo_valor(web_id, "cpu") if configurado() else None,
        "ram_web_bytes": _ultimo_valor(web_id, "memory") if configurado() else None,
        "cpu_db": _ultimo_valor(db_id, "cpu") if (configurado() and db_id) else None,
        "ram_db_bytes": _ultimo_valor(db_id, "memory") if (configurado() and db_id) else None,
        "conexiones_db": _ultimo_valor(db_id, "active-connections") if (configurado() and db_id) else None,
        "workers_uvicorn": workers,
        "plan_web": plan_web,
        "plan_db": _plan_postgres(db_id) if (configurado() and db_id) else None,
        # Esto sí es constante del código (db.py), no de la API.
        "pool_size": 5, "max_overflow": 5,
    }


def crear_job(start_command: str) -> dict:
    """Crea un Job one-off en el propio servicio (mismo código ya
    desplegado, mismas variables de entorno -- incluida DATABASE_URL, así
    que tiene red directa a Postgres sin necesitar nada más). Devuelve
    {"id":..., "status":...} o {"error": "..."} si falta configuración o
    la llamada falla."""
    web_id = os.getenv("RENDER_WEB_SERVICE_ID", "")
    if not configurado() or not web_id:
        return {"error": "Falta RENDER_API_KEY o RENDER_WEB_SERVICE_ID en las variables de entorno."}
    try:
        return _peticion(f"/services/{web_id}/jobs", metodo="POST",
                          body={"startCommand": start_command})
    except urllib.error.HTTPError as e:
        return {"error": f"Render devolvió HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def estado_job(job_id: str) -> dict:
    web_id = os.getenv("RENDER_WEB_SERVICE_ID", "")
    if not configurado() or not web_id or not job_id:
        return {"error": "sin configurar"}
    try:
        return _peticion(f"/services/{web_id}/jobs/{job_id}")
    except Exception as e:
        return {"error": str(e)}


# ===================== Planes: leer y cambiar =====================
# Lo que sigue es lo que usa la solapa "Planes" de /entornos. Dos reglas que
# valen para todo el bloque:
#
# 1. Nunca se manda a la API un plan que no esté en el catálogo
#    (render_planes.py, que sale de la propia página de precios de Render).
#    Un identificador inventado sería un 400 en el mejor caso y un plan
#    equivocado en el peor -- pasó en la sesión del 2026-09-10, cuando pedir
#    "starter" mandó el servicio a un plan viejo distinto del que tenía.
# 2. Cambiar el plan del servicio web lo REINICIA, y cambiar el de Postgres
#    lo deja un minuto sin atender. Eso no se puede evitar, pero sí avisarlo:
#    las funciones devuelven qué se cambió para que la pantalla lo diga.

def _web_id() -> str:
    return os.getenv("RENDER_WEB_SERVICE_ID", "")


def _db_id() -> str:
    return os.getenv("RENDER_DB_ID", "")


def _start_command_con_workers(cmd: str, workers: int) -> str:
    """Reemplaza `--workers N` en el Start Command, o lo agrega si no está.
    Se edita el comando REAL leído de la API en vez de reescribirlo entero:
    así no se pierde ninguna otra bandera que alguien haya puesto a mano."""
    import re
    if re.search(r"--workers[= ]\d+", cmd):
        return re.sub(r"--workers[= ]\d+", f"--workers {workers}", cmd)
    return f"{cmd.rstrip()} --workers {workers}"


def estado_planes() -> dict:
    """Lo que la solapa muestra al entrar: plan actual, si el servicio está
    activo, cuántas instancias y cuántos workers. Cada valor que no se pudo
    leer queda en None y la pantalla lo muestra como "no disponible"."""
    if not configurado():
        return {"configurado": False, "web": None, "db": None,
                "error": "Falta RENDER_API_KEY o RENDER_WEB_SERVICE_ID."}
    web = db = None
    error = ""
    try:
        s = _peticion(f"/services/{_web_id()}")
        det = s.get("serviceDetails", {}) or {}
        import re
        cmd = (det.get("envSpecificDetails", {}) or {}).get("startCommand", "") or ""
        m = re.search(r"--workers[= ](\d+)", cmd)
        web = {
            "id": s.get("id", ""), "nombre": s.get("name", ""),
            "plan": det.get("plan", ""),
            "instancias": det.get("numInstances"),
            "workers": int(m.group(1)) if m else 1,
            "start_command": cmd,
            "suspendido": s.get("suspended") != "not_suspended",
            "activo": s.get("suspended") == "not_suspended",
            "actualizado": s.get("updatedAt", ""),
            "panel": s.get("dashboardUrl", ""),
        }
    except Exception as e:
        error = f"No se pudo leer el servicio web ({type(e).__name__})."
    if _db_id():
        try:
            d = _peticion(f"/postgres/{_db_id()}")
            db = {
                "id": d.get("id", ""), "nombre": d.get("name", ""),
                "plan": d.get("plan", ""),
                "estado": d.get("status", ""),
                # "available" es el único estado en el que la base atiende;
                # durante un cambio de plan pasa por "updating_instance" y
                # la app entera devuelve error 500 mientras tanto.
                "activo": d.get("status") == "available",
                "suspendido": d.get("suspended") != "not_suspended",
                "disco_gb": d.get("diskSizeGB"),
                "version": d.get("version", ""),
                "panel": d.get("dashboardUrl", ""),
            }
        except Exception as e:
            error = (error + " " if error else "") + \
                f"No se pudo leer la base ({type(e).__name__})."
    return {"configurado": True, "web": web, "db": db, "error": error}


def aplicar_plan_web(plan: str, instancias: int = None, workers: int = None) -> dict:
    """Cambia plan / instancias / workers del servicio web.

    ORDEN IMPORTANTE: si el plan baja, los workers se bajan ANTES; si sube,
    DESPUÉS. Dejar muchos workers sobre poca CPU es la peor combinación
    medida (test 2 del informe de carga: peor que la línea base con el doble
    de workers sobre media vCPU), así que el servicio nunca debe pasar por
    ese estado intermedio, ni siquiera unos minutos."""
    import render_planes
    if not configurado() or not _web_id():
        return {"error": "Falta RENDER_API_KEY o RENDER_WEB_SERVICE_ID."}
    destino = render_planes.buscar("web", plan)
    if not destino:
        return {"error": f"El plan '{plan}' no está en el catálogo de Render."}
    try:
        actual = _peticion(f"/services/{_web_id()}")
    except Exception as e:
        return {"error": f"No se pudo leer el estado actual ({type(e).__name__})."}
    det = actual.get("serviceDetails", {}) or {}
    plan_actual = det.get("plan", "")
    cmd = (det.get("envSpecificDetails", {}) or {}).get("startCommand", "") or ""
    vcpu_actual = (render_planes.buscar("web", plan_actual) or {}).get("vcpu", 0)
    baja = destino["vcpu"] < (vcpu_actual or 0)
    hechos = []

    def _poner_workers():
        if workers is None:
            return
        nuevo = _start_command_con_workers(cmd, workers)
        if nuevo == cmd:
            return
        _peticion(f"/services/{_web_id()}", metodo="PATCH", body={
            "serviceDetails": {"envSpecificDetails": {"startCommand": nuevo}}})
        hechos.append(f"workers a {workers}")

    try:
        if baja:
            _poner_workers()
        if plan != plan_actual:
            _peticion(f"/services/{_web_id()}", metodo="PATCH",
                      body={"serviceDetails": {"plan": plan}})
            hechos.append(f"plan a {plan}")
        if instancias is not None and instancias != det.get("numInstances"):
            _peticion(f"/services/{_web_id()}/scale", metodo="POST",
                      body={"numInstances": int(instancias)})
            hechos.append(f"instancias a {instancias}")
        if not baja:
            _poner_workers()
    except urllib.error.HTTPError as e:
        return {"error": f"Render devolvió HTTP {e.code}.", "hechos": hechos}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "hechos": hechos}
    return {"ok": True, "hechos": hechos, "reinicia": bool(hechos)}


def aplicar_plan_db(plan: str) -> dict:
    """Cambia el plan de Postgres. El disco NO se achica nunca (Render no lo
    permite), así que bajar de plan reduce CPU y RAM pero no lo que se paga
    por almacenamiento."""
    import render_planes
    if not configurado() or not _db_id():
        return {"error": "Falta RENDER_API_KEY o RENDER_DB_ID."}
    if not render_planes.buscar("db", plan):
        return {"error": f"El plan '{plan}' no está en el catálogo de Render."}
    try:
        actual = _peticion(f"/postgres/{_db_id()}")
        if actual.get("plan") == plan:
            return {"ok": True, "hechos": [], "reinicia": False}
        _peticion(f"/postgres/{_db_id()}", metodo="PATCH", body={"plan": plan})
    except urllib.error.HTTPError as e:
        return {"error": f"Render devolvió HTTP {e.code}."}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "hechos": [f"plan de la base a {plan}"], "reinicia": True}
