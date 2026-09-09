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
