"""Aplica a Grafana Cloud la configuración de alertas de observabilidad/config.json.

Idempotente: se puede correr todas las veces que haga falta; crea lo que falta
y deja igual lo que ya está. Crea la carpeta de los tableros de Pruebas, el
punto de contacto (el mail) y la política de notificaciones con las reglas
anti-ruido: un aviso al abrirse un problema, uno al resolverse y el recordatorio
cada `repeat_interval` (24 h por ahora) mientras siga abierto.

El token NO va en ningún archivo: se pasa por variable de entorno.

    GRAFANA_TOKEN=glsa_... python observabilidad/aplicar_grafana.py
    GRAFANA_TOKEN=glsa_... python observabilidad/aplicar_grafana.py --probar-mail
    python observabilidad/aplicar_grafana.py --dry-run     # solo muestra qué haría

Para cambiar el mail o el intervalo de repetición: editar config.json y volver a
correrlo. La política de notificaciones que este script deja es la RAÍZ del
árbol de Grafana y reemplaza a la anterior (en un stack nuevo, la de fábrica).

Solo usa la biblioteca estándar: se corre igual desde la PC o desde CI.
"""
import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "config.json"
DURACION = re.compile(r"^\d+(s|m|h)$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- Lo que se puede probar sin red ----------

def cargar_config(ruta: Path = CONFIG) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def validar(cfg: dict) -> list:
    """Lista de problemas de la configuración; vacía si está bien. Se valida
    ANTES de tocar Grafana: un mail mal escrito no debe dejar la política de
    notificaciones apuntando a un destino que no existe."""
    errores = []
    g, a = cfg.get("grafana", {}), cfg.get("alertas", {})
    if not str(g.get("url", "")).startswith("https://"):
        errores.append("grafana.url tiene que empezar con https://")
    for clave in ("carpeta_uid", "carpeta_titulo"):
        if not g.get(clave):
            errores.append(f"grafana.{clave} está vacío")
    if not a.get("contact_point"):
        errores.append("alertas.contact_point está vacío")
    if not EMAIL.match(str(a.get("email", ""))):
        errores.append("alertas.email no parece un mail")
    for clave in ("group_wait", "group_interval", "repeat_interval"):
        if not DURACION.match(str(a.get(clave, ""))):
            errores.append(f"alertas.{clave} tiene que ser como 30s, 5m o 24h")
    if not isinstance(a.get("group_by"), list) or not a["group_by"]:
        errores.append("alertas.group_by tiene que ser una lista no vacía")
    if not isinstance(a.get("avisar_al_resolverse"), bool):
        errores.append("alertas.avisar_al_resolverse tiene que ser true o false")
    return errores


def payload_contact_point(cfg: dict) -> dict:
    a = cfg["alertas"]
    return {
        "name": a["contact_point"],
        "type": "email",
        # singleEmail: un solo mail con todos los destinatarios, no uno por cada uno.
        "settings": {"addresses": a["email"], "singleEmail": True},
        "disableResolveMessage": not a["avisar_al_resolverse"],
    }


def payload_politica(cfg: dict) -> dict:
    a = cfg["alertas"]
    return {
        "receiver": a["contact_point"],
        "group_by": a["group_by"],
        "group_wait": a["group_wait"],
        "group_interval": a["group_interval"],
        "repeat_interval": a["repeat_interval"],
        "routes": [],
    }


# ---------- Grafana ----------

def _contexto_tls():
    """Con `certifi` (viene con httpx, que el proyecto ya usa) los certificados
    se validan contra un juego de raíces al día. El Python "pelado" de Windows usa
    el almacén del sistema, que puede tener una raíz vencida y rechazar un sitio
    perfectamente válido ("certificate has expired"). Sin certifi, se usa el
    almacén del sistema como siempre: nunca se desactiva la verificación."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


class Grafana:
    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    def pedir(self, metodo: str, ruta: str, cuerpo=None, editable_desde_la_ui=False):
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(self.url + ruta, data=datos, method=metodo)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")
        if datos is not None:
            req.add_header("Content-Type", "application/json")
        if editable_desde_la_ui:
            # Sin esto, lo creado por la API queda "provisionado" y bloqueado en
            # la interfaz: no se podría tocar a mano en una urgencia.
            req.add_header("X-Disable-Provenance", "true")
        try:
            with urllib.request.urlopen(req, timeout=30, context=_contexto_tls()) as r:
                texto = r.read().decode("utf-8")
                return r.status, (json.loads(texto) if texto else None)
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(texto)
            except ValueError:
                return e.code, {"message": texto[:300]}


def asegurar_carpeta(g: Grafana, cfg: dict, dry: bool) -> str:
    uid, titulo = cfg["grafana"]["carpeta_uid"], cfg["grafana"]["carpeta_titulo"]
    estado, _ = g.pedir("GET", f"/api/folders/{uid}")
    if estado == 200:
        return f"carpeta '{titulo}': ya existía"
    if dry:
        return f"carpeta '{titulo}': la crearía"
    estado, resp = g.pedir("POST", "/api/folders", {"uid": uid, "title": titulo})
    if estado not in (200, 201):
        raise SystemExit(f"No se pudo crear la carpeta ({estado}): {resp}")
    return f"carpeta '{titulo}': creada"


def asegurar_contact_point(g: Grafana, cfg: dict, dry: bool) -> str:
    cuerpo = payload_contact_point(cfg)
    estado, actuales = g.pedir("GET", "/api/v1/provisioning/contact-points")
    if estado != 200:
        raise SystemExit(f"No se pudieron leer los puntos de contacto ({estado}): {actuales}")
    existente = next((c for c in actuales if c["name"] == cuerpo["name"]), None)
    if dry:
        return f"punto de contacto '{cuerpo['name']}': {'lo actualizaría' if existente else 'lo crearía'}"
    if existente:
        estado, resp = g.pedir("PUT", f"/api/v1/provisioning/contact-points/{existente['uid']}",
                               cuerpo, editable_desde_la_ui=True)
        verbo = "actualizado"
    else:
        estado, resp = g.pedir("POST", "/api/v1/provisioning/contact-points",
                               cuerpo, editable_desde_la_ui=True)
        verbo = "creado"
    if estado not in (200, 201, 202):
        raise SystemExit(f"No se pudo guardar el punto de contacto ({estado}): {resp}")
    return f"punto de contacto '{cuerpo['name']}' ({cfg['alertas']['email']}): {verbo}"


def aplicar_politica(g: Grafana, cfg: dict, dry: bool) -> str:
    cuerpo = payload_politica(cfg)
    if dry:
        return f"política de notificaciones: la fijaría así: {json.dumps(cuerpo, ensure_ascii=False)}"
    estado, resp = g.pedir("PUT", "/api/v1/provisioning/policies", cuerpo, editable_desde_la_ui=True)
    if estado not in (200, 201, 202):
        raise SystemExit(f"No se pudo fijar la política de notificaciones ({estado}): {resp}")
    a = cfg["alertas"]
    return (f"política de notificaciones: fijada (espera {a['group_wait']}, agrupa cada "
            f"{a['group_interval']}, repite cada {a['repeat_interval']})")


def nombre_de_recurso(nombre: str) -> str:
    """Cómo llama la API nueva de Grafana (13+) a un punto de contacto: su nombre
    en base64 url-safe, sin el relleno `=`. 'sdn-mail' -> 'c2RuLW1haWw'."""
    return base64.urlsafe_b64encode(nombre.encode("utf-8")).decode("ascii").rstrip("=")


def probar_mail(g: Grafana, cfg: dict) -> str:
    """Manda UN mail de prueba al punto de contacto, para comprobar que llega.
    El endpoint viejo (`/api/alertmanager/.../receivers/test`) lo quitó Grafana 13."""
    estado, ajustes = g.pedir("GET", "/api/frontend/settings")
    namespace = (ajustes or {}).get("namespace") if estado == 200 else None
    if not namespace:
        return f"mail de prueba: no pude averiguar el namespace del stack (HTTP {estado})"
    estado, cps = g.pedir("GET", "/api/v1/provisioning/contact-points")
    c = payload_contact_point(cfg)
    existente = next((x for x in (cps or []) if x["name"] == c["name"]), None)
    if not existente:
        return f"mail de prueba: el punto de contacto '{c['name']}' no existe todavía (correr sin --probar-mail primero)"
    cuerpo = {"integration": {"uid": existente["uid"], "type": "email", "version": "v1",
                              "settings": c["settings"]}}
    ruta = (f"/apis/notifications.alerting.grafana.app/v1beta1/namespaces/{namespace}"
            f"/receivers/{nombre_de_recurso(c['name'])}/test")
    estado, resp = g.pedir("POST", ruta, cuerpo)
    return f"mail de prueba a {c['settings']['addresses']}: HTTP {estado} {json.dumps(resp, ensure_ascii=False)[:200]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="muestra qué haría, sin escribir nada")
    ap.add_argument("--probar-mail", action="store_true", help="manda un mail de prueba")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")     # Windows imprime cp1252 por defecto

    cfg = cargar_config(Path(args.config))
    errores = validar(cfg)
    if errores:
        print("config.json tiene errores, no se toca Grafana:")
        for e in errores:
            print("  -", e)
        return 2
    token = os.environ.get("GRAFANA_TOKEN", "")
    if not token and not args.dry_run:
        print("Falta GRAFANA_TOKEN (un token de cuenta de servicio de Grafana, glsa_...).")
        return 2
    g = Grafana(os.environ.get("GRAFANA_URL", cfg["grafana"]["url"]), token)
    print(f"Grafana: {g.url}" + ("   [dry-run]" if args.dry_run else ""))
    if args.dry_run and not token:
        # Sin token no hay forma de leer qué existe: se muestra solo lo que se enviaría.
        print(" · punto de contacto:", json.dumps(payload_contact_point(cfg), ensure_ascii=False))
        print(" · política:", json.dumps(payload_politica(cfg), ensure_ascii=False))
        return 0
    for paso in (asegurar_carpeta, asegurar_contact_point, aplicar_politica):
        print(" ·", paso(g, cfg, args.dry_run))
    if args.probar_mail and not args.dry_run:
        print(" ·", probar_mail(g, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
