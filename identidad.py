"""Verificación de identidad de un afiliado: motor de la herramienta
«Verificación de identidad» de /entornos → Herramientas.

Qué hace: de una persona que dice ser X (CUIL, DNI, nombre, fecha de
nacimiento, género) y manda una selfie y la foto de su DNI, decide si la
identidad se sostiene. Cada paso corta el camino apenas falla, para no gastar
en los que siguen:

  1. chequeos locales (gratis): el CUIL vale, el DNI es el del CUIL, el
     género es coherente con el prefijo del CUIL;
  2. el documento (Didit id-verification): lo lee, lo compara con lo que la
     persona declaró y detecta foto de pantalla, copia impresa o retrato
     manipulado;
  3. prueba de vida de la selfie (Didit passive-liveness);
  4. la cara de la selfie contra el retrato del DNI (Didit face-match);
  5. los datos y la cara contra RENAPER (Didit database-validation, arg_renaper).

Esta pieza NO es parte de la app del trabajador ni del sindicato: la usa solo
la herramienta de /entornos (local y Pruebas). Cuando llegue el momento de
llevarla al flujo real, el motor se importa tal cual.

Reglas de privacidad (Ley 25.326: la cara y el DNI son datos sensibles):
- Ninguna imagen se guarda acá ni en la base. Salen hacia Didit y vuelven solo
  resultados. `save_api_request=false` (por defecto) le pide a Didit que no
  conserve la sesión ni enrole la cara; `DIDIT_GUARDAR_SESION=1` lo cambia.
- Lo que devuelve este módulo y lo que se guarda como caso NO lleva CUIL,
  nombre, DNI ni fecha de nacimiento: solo estados, puntajes y alertas.
- Sin `DIDIT_API_KEY` el módulo queda apagado en silencio (como correo.py).

Puro salvo `_post`, que es la única que habla con la red; los tests la
reemplazan por un cliente simulado (`cliente=`).
"""
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
import uuid

import cuit
import fechas

HERRAMIENTA = "identidad"
BASE = "https://verification.didit.me/v3"
TIEMPO_MAXIMO_S = 60

# Tope de cada imagen que llega de la pantalla (Didit acepta 5 MB las de cara
# y 10 MB las del documento; se pide lo mismo para no gastar una llamada que
# después rebota).
TOPE_CARA_BYTES = 5 * 1024 * 1024
TOPE_DOCUMENTO_BYTES = 10 * 1024 * 1024

# Pasos, en orden. `gasta` marca los que cuestan plata en el proveedor.
PASOS = (
    ("local", "Chequeos locales", False),
    ("documento", "Documento (lectura y autenticidad)", True),
    ("vida", "Prueba de vida", True),
    ("cara", "Selfie contra el retrato del DNI", True),
    ("renaper", "RENAPER (datos y cara)", True),
)
GENEROS = ("M", "F")


# ------------------------------------------------------------------ config
def clave() -> str:
    return os.getenv("DIDIT_API_KEY", "").strip()


def configurado() -> bool:
    return bool(clave())


def es_sandbox() -> bool:
    """Las claves de prueba de Didit empiezan con `sk_test_` y no procesan nada
    (devuelven una respuesta fija). Es una pista: la fuente de verdad es Didit."""
    return clave().startswith("sk_test_")


def guardar_sesion() -> bool:
    return os.getenv("DIDIT_GUARDAR_SESION", "") == "1"


def tope_intentos() -> int:
    try:
        return max(1, int(os.getenv("IDENTIDAD_TOPE_INTENTOS", "5")))
    except ValueError:
        return 5


# Intentos que gastaron plata, por persona y por hora. En memoria del proceso:
# la herramienta corre en un worker en Pruebas, y esto es un freno de gasto, no
# una barrera de seguridad. La clave es un hash: no se guarda el CUIL.
_INTENTOS: dict = {}
_VENTANA_S = 3600


def _clave_intentos(cuil: str) -> str:
    return hashlib.sha256(cuit.normalizar(cuil).encode()).hexdigest()[:16]


def intentos_usados(cuil: str, ahora: float = None) -> int:
    ahora = time.time() if ahora is None else ahora
    k = _clave_intentos(cuil)
    vivos = [t for t in _INTENTOS.get(k, []) if ahora - t < _VENTANA_S]
    _INTENTOS[k] = vivos
    return len(vivos)


def anotar_intento(cuil: str, ahora: float = None) -> None:
    ahora = time.time() if ahora is None else ahora
    intentos_usados(cuil, ahora)
    _INTENTOS[_clave_intentos(cuil)].append(ahora)


def reiniciar_intentos() -> None:
    _INTENTOS.clear()


# ----------------------------------------------------------------- normas
def solo_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def dni_del_cuil(cuil) -> str:
    """Los 8 dígitos del medio del CUIL (20-20279041-1 → 20279041)."""
    d = cuit.normalizar(cuil)
    return d[2:10] if len(d) == 11 else ""


def _sin_acentos(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in t if not unicodedata.combining(c))


def palabras(texto) -> set:
    """Nombre en palabras comparables: sin acentos, en mayúsculas, sin signos."""
    limpio = re.sub(r"[^A-Z ]", " ", _sin_acentos(texto).upper())
    return {p for p in limpio.split() if len(p) > 1}


def mismo_nombre(a, b) -> bool:
    """Dos nombres coinciden si las palabras de uno están todas en el otro
    (el documento trae los dos nombres y la persona puede escribir uno)."""
    pa, pb = palabras(a), palabras(b)
    return bool(pa and pb) and (pa <= pb or pb <= pa)


def fecha_iso(valor) -> str:
    """AAAA-MM-DD a partir de AAAA-MM-DD o DD/MM/AAAA (lo que escribe una
    persona o lo que lee un documento). Vacío si no se entiende."""
    v = str(valor or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        return "%s-%02d-%02d" % (m[1], int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", v)
    if m:
        return "%s-%02d-%02d" % (m[3], int(m[2]), int(m[1]))
    return ""


# ----------------------------------------------------------- paso 1: local
def chequeos_locales(declarado: dict) -> list:
    """Lo que se sabe sin gastar nada. Cada chequeo: {clave, ok, detalle}.
    `declarado`: cuil, dni, nombre, apellido, nacimiento, genero."""
    cuil = cuit.normalizar(declarado.get("cuil"))
    dni = solo_digitos(declarado.get("dni"))
    genero = str(declarado.get("genero") or "").upper()
    salida = []

    def sumar(clave_, ok, detalle):
        salida.append({"clave": clave_, "ok": bool(ok), "detalle": detalle})

    sumar("cuil_valido", cuit.es_valido(cuil), "El CUIL cumple el módulo 11."
          if cuit.es_valido(cuil) else "El CUIL no es válido.")
    esperado = dni_del_cuil(cuil)
    # El DNI de menos de 8 dígitos va con ceros adelante dentro del CUIL.
    coincide = bool(dni) and bool(esperado) and dni.zfill(8) == esperado
    sumar("dni_es_del_cuil", coincide, "El DNI es el que lleva el CUIL."
          if coincide else "El DNI no es el que lleva el CUIL.")
    sumar("genero_dato", genero in GENEROS, "Género informado."
          if genero in GENEROS else "Falta el género (M o F).")
    prefijo = cuil[:2]
    if genero in GENEROS and prefijo in ("20", "27"):
        coherente = (prefijo == "20") == (genero == "M")
        sumar("genero_prefijo", coherente,
              "El género es coherente con el prefijo del CUIL." if coherente
              else "El género no es el que indica el prefijo %s del CUIL." % prefijo)
    nacimiento = fecha_iso(declarado.get("nacimiento"))
    sumar("nacimiento_dato", bool(nacimiento), "Fecha de nacimiento informada."
          if nacimiento else "La fecha de nacimiento no se entiende (AAAA-MM-DD).")
    sumar("nombre_dato", bool(palabras(declarado.get("nombre")) and palabras(declarado.get("apellido"))),
          "Nombre y apellido informados." if palabras(declarado.get("nombre")) and palabras(declarado.get("apellido"))
          else "Faltan el nombre o el apellido.")
    return salida


# --------------------------------------------------------------- Didit: red
class ErrorDidit(Exception):
    def __init__(self, http: int, detalle: str):
        super().__init__("Didit %s: %s" % (http, detalle))
        self.http = http
        self.detalle = detalle


def _cuerpo_multipart(campos: dict, archivos: list):
    """archivos: [(campo, nombre, bytes, mime)]. Devuelve (cuerpo, content_type)."""
    limite = uuid.uuid4().hex
    partes = []
    for nombre, valor in campos.items():
        partes.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                       % (limite, nombre, valor)).encode("utf-8"))
    for campo, nombre, datos, mime in archivos:
        partes.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                       "Content-Type: %s\r\n\r\n" % (limite, campo, nombre, mime)).encode("utf-8"))
        partes.append(datos)
        partes.append(b"\r\n")
    partes.append(("--%s--\r\n" % limite).encode("utf-8"))
    return b"".join(partes), "multipart/form-data; boundary=%s" % limite


def _post(ruta: str, campos: dict, archivos: list) -> dict:
    """La única función que sale a la red. Devuelve el JSON de la respuesta o
    levanta ErrorDidit con el HTTP y un detalle corto (nunca el cuerpo
    entero: puede traer datos personales)."""
    cuerpo, tipo = _cuerpo_multipart(campos, archivos)
    req = urllib.request.Request(BASE + ruta, data=cuerpo, method="POST",
                                 headers={"x-api-key": clave(), "Content-Type": tipo})
    try:
        with urllib.request.urlopen(req, timeout=TIEMPO_MAXIMO_S) as r:
            texto = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "replace")
        try:
            detalle = str(json.loads(texto).get("detail") or json.loads(texto).get("error") or "")
        except (ValueError, AttributeError):
            detalle = ""
        raise ErrorDidit(e.code, detalle[:200] or "sin detalle")
    except urllib.error.URLError as e:
        raise ErrorDidit(0, "no se pudo conectar (%s)" % e.reason)
    try:
        return json.loads(texto)
    except ValueError:
        raise ErrorDidit(200, "la respuesta no es JSON")


def _alertas(lista) -> list:
    return [w.get("risk") for w in (lista or []) if isinstance(w, dict) and w.get("risk")]


def _guardar_flag() -> str:
    return "true" if guardar_sesion() else "false"


class Didit:
    """Los cuatro servicios, ya normalizados: cada método devuelve un dict
    chico con `estado` y lo que sirve para decidir, sin datos personales
    de más. Una clase para poder reemplazarla entera en los tests."""

    def documento(self, frente: tuple, dorso: tuple = None) -> dict:
        archivos = [("front_image",) + frente]
        if dorso:
            archivos.append(("back_image",) + dorso)
        r = _post("/id-verification/", {"save_api_request": _guardar_flag(),
                                        "perform_document_liveness": "true"}, archivos)
        d = r.get("id_verification") or {}
        return {"estado": d.get("status"), "alertas": _alertas(d.get("warnings")),
                "leido": {"dni": solo_digitos(d.get("document_number") or d.get("personal_number")),
                          "nombre": d.get("first_name") or "", "apellido": d.get("last_name") or "",
                          "nacimiento": fecha_iso(d.get("date_of_birth")),
                          "genero": str(d.get("gender") or "")[:1].upper(),
                          "vencimiento": fecha_iso(d.get("expiration_date")),
                          "pais": d.get("issuing_state") or ""}}

    def vida(self, selfie: tuple) -> dict:
        r = _post("/passive-liveness/", {"save_api_request": _guardar_flag()},
                  [("user_image",) + selfie])
        d = r.get("liveness") or {}
        return {"estado": d.get("status"), "puntaje": d.get("score"), "alertas": _alertas(d.get("warnings"))}

    def cara(self, selfie: tuple, retrato: tuple) -> dict:
        r = _post("/face-match/", {"save_api_request": _guardar_flag()},
                  [("user_image",) + selfie, ("ref_image",) + retrato])
        d = r.get("face_match") or {}
        return {"estado": d.get("status"), "puntaje": d.get("score"), "alertas": _alertas(d.get("warnings"))}

    def renaper(self, declarado: dict, selfie: tuple) -> dict:
        campos = {"issuing_state": "ARG", "services": json.dumps(["arg_renaper"]), "consent": "true",
                  "identification_number": solo_digitos(declarado.get("dni")),
                  "first_name": declarado.get("nombre"), "last_name": declarado.get("apellido"),
                  "date_of_birth": fecha_iso(declarado.get("nacimiento")),
                  "gender": str(declarado.get("genero")).upper()}
        r = _post("/database-validation/", campos, [("selfie",) + selfie])
        d = r.get("database_validation") or {}
        return {"estado": d.get("status"), "coincidencia": d.get("match_type"),
                "puntaje": d.get("match_score"), "campos": d.get("validations"),
                "alertas": _alertas(d.get("warnings"))}


# ------------------------------------------------------------- comparación
def comparar_documento(leido: dict, declarado: dict) -> list:
    """Lo que el documento dice contra lo que la persona declaró. Cada
    chequeo {clave, ok, detalle}. Un campo que el documento no trae no cuenta
    como diferencia: se anota como «no leído»."""
    salida = []

    def sumar(clave_, ok, detalle):
        salida.append({"clave": clave_, "ok": ok, "detalle": detalle})

    if leido.get("dni"):
        ok = leido["dni"].zfill(8) == solo_digitos(declarado.get("dni")).zfill(8)
        sumar("doc_dni", ok, "El DNI del documento coincide." if ok else "El DNI del documento es otro.")
    else:
        sumar("doc_dni", None, "El documento no trajo el número (no leído).")
    if leido.get("apellido") or leido.get("nombre"):
        ok = (mismo_nombre(leido.get("apellido"), declarado.get("apellido"))
              and mismo_nombre(leido.get("nombre"), declarado.get("nombre")))
        sumar("doc_nombre", ok, "El nombre del documento coincide." if ok else "El nombre del documento es otro.")
    else:
        sumar("doc_nombre", None, "El documento no trajo el nombre (no leído).")
    if leido.get("nacimiento"):
        ok = leido["nacimiento"] == fecha_iso(declarado.get("nacimiento"))
        sumar("doc_nacimiento", ok, "La fecha de nacimiento coincide." if ok
              else "La fecha de nacimiento del documento es otra.")
    else:
        sumar("doc_nacimiento", None, "El documento no trajo la fecha de nacimiento (no leída).")
    if leido.get("vencimiento"):
        ok = leido["vencimiento"] >= fechas.hoy_texto()
        sumar("doc_vigente", ok, "El documento está vigente." if ok else "El documento está vencido.")
    return salida


# ---------------------------------------------------------------- veredicto
APROBABLE, REVISAR, RECHAZAR = "aprobable", "revisar", "rechazar"


def _estado_paso(paso: dict) -> str:
    """aprobado / revisar / rechazado / sin_correr / error, a partir de lo que
    devolvió un paso. Un error de red o de saldo NO es un rechazo de la
    persona: queda aparte para no culparla de un problema nuestro."""
    if paso.get("error"):
        return "error"
    if paso.get("omitido"):
        return "sin_correr"
    chequeos = paso.get("chequeos") or []
    if any(c["ok"] is False for c in chequeos) and paso.get("clave") == "local":
        return "rechazado"
    estado = str(paso.get("estado") or "").lower()
    if paso.get("clave") == "renaper":
        co = str(paso.get("coincidencia") or "").lower()
        if co == "no_match" or estado == "declined":
            return "rechazado"
        if co == "partial_match" or estado == "in review":
            return "revisar"
        return "aprobado" if co == "full_match" or estado == "approved" else "revisar"
    if estado == "declined":
        return "rechazado"
    if estado == "in review":
        return "revisar"
    if any(c["ok"] is False for c in chequeos):
        return "revisar"          # el documento dice otra cosa: lo mira una persona
    return "aprobado" if estado == "approved" or paso.get("clave") == "local" else "revisar"


def veredicto(pasos: list) -> dict:
    """Junta los pasos en uno de tres resultados. «Aprobable» NO es aprobado:
    es lo que pasa a la mesa del sindicato con todo en verde."""
    estados = {p["clave"]: _estado_paso(p) for p in pasos}
    motivos = []
    for p in pasos:
        e = estados[p["clave"]]
        nombre = dict((c, n) for c, n, _ in PASOS)[p["clave"]]
        if e == "rechazado":
            motivos.append("%s: rechazado." % nombre)
        elif e == "revisar":
            motivos.append("%s: pide revisión de una persona." % nombre)
        elif e == "error":
            motivos.append("%s: no se pudo consultar (%s)." % (nombre, p.get("error")))
    valores = set(estados.values())
    if "rechazado" in valores:
        resultado = RECHAZAR
    elif "revisar" in valores or "error" in valores or "sin_correr" in valores:
        resultado = REVISAR
    else:
        resultado = APROBABLE
    return {"resultado": resultado, "motivos": motivos, "estados": estados}


# ---------------------------------------------------------------- el flujo
def correr(declarado: dict, selfie: tuple, frente: tuple, dorso: tuple = None,
           cliente=None, pasos_pedidos=None) -> dict:
    """Corre los pasos en orden y corta apenas uno rechaza. Las imágenes son
    tuplas (nombre, bytes, mime). `pasos_pedidos` limita cuáles gastan (para
    probar de a uno); None = todos. Devuelve {pasos, veredicto, ms}. Sin CUIL,
    nombre ni DNI en la salida."""
    cliente = cliente or Didit()
    pedidos = set(pasos_pedidos or [c for c, _, _ in PASOS])
    t0 = time.perf_counter()
    pasos = []

    def sumar(clave_, **datos):
        pasos.append({"clave": clave_, **datos})

    def corte():
        return any(_estado_paso(p) == "rechazado" for p in pasos)

    def correr_paso(clave_, fn):
        if clave_ not in pedidos or corte():
            sumar(clave_, omitido=True, motivo="cortado por un rechazo anterior" if corte() else "no pedido")
            return None
        t = time.perf_counter()
        try:
            r = fn()
        except ErrorDidit as e:
            sumar(clave_, error="HTTP %s %s" % (e.http, e.detalle), ms=int((time.perf_counter() - t) * 1000))
            return None
        r["ms"] = int((time.perf_counter() - t) * 1000)
        sumar(clave_, **r)
        return r

    sumar("local", chequeos=chequeos_locales(declarado), ms=0)

    def _documento():
        r = cliente.documento(frente, dorso)
        # Lo leído se compara con lo declarado y se descarta: en la salida solo
        # quedan los chequeos, nunca el DNI, el nombre ni la fecha leídos.
        r["chequeos"] = comparar_documento(r.pop("leido", {}), declarado)
        return r

    correr_paso("documento", _documento)
    correr_paso("vida", lambda: cliente.vida(selfie))
    correr_paso("cara", lambda: cliente.cara(selfie, frente))
    correr_paso("renaper", lambda: cliente.renaper(declarado, selfie))
    return {"pasos": pasos, "veredicto": veredicto(pasos),
            "ms": int((time.perf_counter() - t0) * 1000)}


def gasto_estimado(pasos: list) -> int:
    """Cuántas llamadas pagas se hicieron (las que no son locales, no se
    omitieron y no dieron error de red antes de cobrar)."""
    return sum(1 for p in pasos if p["clave"] != "local" and not p.get("omitido"))
