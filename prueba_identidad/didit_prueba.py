"""Prueba aparte de Didit: prueba de vida y validación contra RENAPER.

NO es parte de la app: ninguna ruta lo importa. Sirve para medir, con la key de
SANDBOX primero y la de producción después, qué devuelve cada servicio, cuánto
tarda y cómo reacciona a fotos buenas y malas (poca luz, torcida, de una
pantalla, de otra persona).

Key: variable de entorno DIDIT_API_KEY o línea DIDIT_API_KEY=... del .env local.
Nunca se imprime ni se escribe en ningún archivo.

Uso (desde la carpeta del proyecto):

    python prueba_identidad/didit_prueba.py vida --selfie foto.jpg

    python prueba_identidad/didit_prueba.py renaper --selfie foto.jpg ^
        --dni 12345678 --nombre Juan --apellido Perez ^
        --nacimiento 1990-01-15 --genero M

Con la key de sandbox Didit no procesa nada: devuelve una respuesta fija
"Approved" (sirve para probar la conexión, no la calidad). Para medir de verdad
hace falta la key real con crédito (el plan Free trae uno).
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "https://verification.didit.me/v3"
TOPE_SELFIE_RENAPER = 2 * 1024 * 1024   # 2 MB para database-validation
TOPE_SELFIE_VIDA = 5 * 1024 * 1024      # 5 MB para passive-liveness


def _leer_key() -> str:
    key = os.environ.get("DIDIT_API_KEY", "").strip()
    if key:
        return key
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if linea.startswith("DIDIT_API_KEY="):
                return linea.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("Falta DIDIT_API_KEY (variable de entorno o .env local).")


def _multipart(campos: dict, archivo: tuple):
    """campos: texto; archivo: (nombre_del_campo, ruta). Devuelve (cuerpo, content_type)."""
    limite = uuid.uuid4().hex
    partes = []
    for nombre, valor in campos.items():
        partes.append(
            ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
             % (limite, nombre, valor)).encode("utf-8"))
    campo, ruta = archivo
    ruta = Path(ruta)
    tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
    partes.append(
        ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
         "Content-Type: %s\r\n\r\n" % (limite, campo, ruta.name, tipo)).encode("utf-8"))
    partes.append(ruta.read_bytes())
    partes.append(("\r\n--%s--\r\n" % limite).encode("utf-8"))
    return b"".join(partes), "multipart/form-data; boundary=%s" % limite


def _llamar(ruta_api: str, campos: dict, archivo: tuple) -> dict:
    cuerpo, tipo = _multipart(campos, archivo)
    req = urllib.request.Request(
        BASE + ruta_api, data=cuerpo, method="POST",
        headers={"x-api-key": _leer_key(), "Content-Type": tipo})
    t0 = time.perf_counter()
    estado, texto = 0, ""
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            estado, texto = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        estado, texto = e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        sys.exit("No se pudo conectar: %s" % e.reason)
    seg = time.perf_counter() - t0
    try:
        cuerpo_json = json.loads(texto)
    except ValueError:
        cuerpo_json = {"respuesta_cruda": texto[:500]}
    return {"http": estado, "segundos": round(seg, 2), "cuerpo": cuerpo_json}


def _selfie(ruta: str, tope: int) -> str:
    p = Path(ruta)
    if not p.is_file():
        sys.exit("No existe la selfie: %s" % ruta)
    if p.stat().st_size > tope:
        sys.exit("La selfie pesa %.1f MB y el tope es %d MB." % (
            p.stat().st_size / 1048576, tope // 1048576))
    return str(p)


def vida(a) -> dict:
    """Prueba de vida pasiva (una selfie, sin interacción)."""
    r = _llamar("/passive-liveness/",
                {"save_api_request": "false"},   # no guarda sesión ni enrola la cara
                ("user_image", _selfie(a.selfie, TOPE_SELFIE_VIDA)))
    liv = (r["cuerpo"] or {}).get("liveness") or {}
    r["resumen"] = {
        "estado": liv.get("status"),
        "puntaje_vida": liv.get("score"),
        "calidad_cara": liv.get("face_quality"),
        "luminosidad": liv.get("face_luminance"),
        "alertas": [w.get("risk") for w in liv.get("warnings", [])],
    }
    return r


def renaper(a) -> dict:
    """Validación de datos + coincidencia facial contra RENAPER."""
    campos = {
        "issuing_state": "ARG",
        "identification_number": a.dni,
        "first_name": a.nombre,
        "last_name": a.apellido,
        "date_of_birth": a.nacimiento,
        "gender": a.genero,
        "services": json.dumps(["arg_renaper"]),
        "consent": "true",
    }
    r = _llamar("/database-validation/", campos,
                ("selfie", _selfie(a.selfie, TOPE_SELFIE_RENAPER)))
    dv = (r["cuerpo"] or {}).get("database_validation") or {}
    # La forma de "validations" no está del todo documentada: se muestra tal
    # cual viene (dict, lista o lista de textos) y no se asume nada.
    r["resumen"] = {
        "coincidencia": dv.get("match_type"),
        "puntaje": dv.get("match_score"),
        "estado": dv.get("status"),
        "validaciones": dv.get("validations"),
        "alertas": dv.get("warnings"),
    }
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vida", help="prueba de vida pasiva")
    v.add_argument("--selfie", required=True)
    r = sub.add_parser("renaper", help="datos + cara contra RENAPER")
    r.add_argument("--selfie", required=True)
    r.add_argument("--dni", required=True)
    r.add_argument("--nombre", required=True)
    r.add_argument("--apellido", required=True)
    r.add_argument("--nacimiento", required=True, help="AAAA-MM-DD")
    r.add_argument("--genero", required=True, help="M o F (a confirmar con el sandbox)")
    a = ap.parse_args()
    salida = vida(a) if a.cmd == "vida" else renaper(a)
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
