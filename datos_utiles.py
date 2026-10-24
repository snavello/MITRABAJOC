"""Datos útiles de la portada del afiliado: fecha, clima, próximo feriado y
una efeméride del mundo del trabajo (SDN, 2026-10-24).

Dos servicios públicos, gratis y sin clave, consultados SIEMPRE desde el
servidor (como la geocodificación: la CSP no deja salir al navegador, y así se
controla la tasa y se cachea):

- Open-Meteo (api.open-meteo.com): el clima de la localidad. Las coordenadas
  salen redondeadas a un decimal (unos 10 km): alcanza para el clima y no
  identifica un domicilio.
- ArgentinaDatos (api.argentinadatos.com): los feriados nacionales del año,
  con los puentes y los trasladables ya resueltos.

Ninguna falla de esos servicios se le muestra a nadie: si no responden en
`TIEMPO_MAXIMO` segundos, esa línea no aparece y la portada sigue igual. Las
efemérides son una lista propia y fija (`data/efemerides.json`), sin servicio.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import fechas

TIEMPO_MAXIMO = 2.5          # segundos por pedido: la portada no espera más
VIGENCIA_CLIMA = 30 * 60     # el clima se renueva cada media hora
VIGENCIA_FERIADOS = 12 * 3600
DIAS_EFEMERIDE = 21          # una efeméride se anuncia hasta tres semanas antes
USER_AGENT = "Colm3na/1.0 (plataforma sindical; datos de portada)"

_cache: dict = {}
_candado = threading.Lock()

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

# Códigos WMO de Open-Meteo -> (texto, ícono). El ícono es uno de los cinco
# que dibuja la portada.
_TIEMPO = [
    ((0,), "Despejado", "sol"),
    ((1,), "Mayormente despejado", "sol"),
    ((2,), "Parcialmente nublado", "nubes"),
    ((3,), "Nublado", "nubes"),
    ((45, 48), "Niebla", "nubes"),
    ((51, 53, 55, 56, 57), "Llovizna", "lluvia"),
    ((61, 63, 65, 66, 67, 80, 81, 82), "Lluvia", "lluvia"),
    ((71, 73, 75, 77, 85, 86), "Nieve", "nieve"),
    ((95, 96, 99), "Tormenta", "tormenta"),
]


def fecha_texto(d: date) -> str:
    """'viernes 24 de octubre'."""
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def fecha_corta(d: date) -> str:
    """'Lun 9/11': para un renglón del widget."""
    return f"{DIAS[d.weekday()][:3].capitalize()} {d.day}/{d.month}"


def describir_tiempo(codigo) -> tuple[str, str]:
    for codigos, texto, icono in _TIEMPO:
        if codigo in codigos:
            return texto, icono
    return "", "nubes"


def _guardado(clave, vigencia):
    with _candado:
        v = _cache.get(clave)
    # Una falla se recuerda poco: lo justo para no golpear un servicio caído.
    if v and time.monotonic() - v[0] < (vigencia if v[1] is not None else min(vigencia, 300)):
        return True, v[1]
    return False, None


def _guardar(clave, valor):
    with _candado:
        _cache[clave] = (time.monotonic(), valor)
        if len(_cache) > 500:
            _cache.pop(next(iter(_cache)))


def _pedir_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIEMPO_MAXIMO) as r:   # noqa: S310 (URL fija, https)
        return json.loads(r.read().decode("utf-8"))


def clima(latitud, longitud) -> dict | None:
    """{"temp", "max", "min", "texto", "icono"} o None (sin coordenadas o sin
    respuesta). Una respuesta fallida también se recuerda un rato, para no
    golpear un servicio caído en cada portada."""
    try:
        lat, lon = round(float(latitud), 1), round(float(longitud), 1)
    except (TypeError, ValueError):
        return None
    if not (-56 <= lat <= -21 and -74 <= lon <= -53):    # fuera de la Argentina: no se pide
        return None
    clave = ("clima", lat, lon)
    hay, valor = _guardado(clave, VIGENCIA_CLIMA)
    if hay:
        return valor
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1,
        "timezone": "America/Argentina/Buenos_Aires"})
    try:
        d = _pedir_json(f"https://api.open-meteo.com/v1/forecast?{q}")
        actual, dia = d["current"], d["daily"]
        texto, icono = describir_tiempo(actual.get("weather_code"))
        valor = {"temp": round(actual["temperature_2m"]),
                 "max": round(dia["temperature_2m_max"][0]), "min": round(dia["temperature_2m_min"][0]),
                 "texto": texto, "icono": icono}
    except Exception:
        valor = None
    _guardar(clave, valor)
    return valor


def feriados(anio: int) -> list | None:
    clave = ("feriados", anio)
    hay, valor = _guardado(clave, VIGENCIA_FERIADOS)
    if hay:
        return valor
    try:
        d = _pedir_json(f"https://api.argentinadatos.com/v1/feriados/{int(anio)}")
        valor = [{"fecha": f["fecha"], "nombre": f.get("nombre", ""), "tipo": f.get("tipo", "")}
                 for f in d if isinstance(f, dict) and f.get("fecha")]
    except Exception:
        valor = None
    _guardar(clave, valor)
    return valor


def proximo_feriado(hoy: date, lista: list | None) -> dict | None:
    """El primero desde hoy (incluido). Puro: recibe la lista."""
    iso = hoy.isoformat()
    for f in sorted(lista or [], key=lambda x: x["fecha"]):
        if f["fecha"] >= iso:
            d = date.fromisoformat(f["fecha"])
            nombre = "Feriado puente" if f.get("tipo") == "puente" else f["nombre"]
            return {"fecha": f["fecha"], "nombre": nombre, "dias": (d - hoy).days,
                    "cuando": "hoy" if d == hoy else ("mañana" if (d - hoy).days == 1 else fecha_texto(d)),
                    "corto": "Hoy" if d == hoy else ("Mañana" if (d - hoy).days == 1 else fecha_corta(d))}
    return None


def _efemerides() -> list:
    clave = ("efemerides",)
    hay, valor = _guardado(clave, 3600)
    if hay:
        return valor
    ruta = Path(__file__).parent / "data" / "efemerides.json"
    valor = json.loads(ruta.read_text(encoding="utf-8"))["efemerides"]
    _guardar(clave, valor)
    return valor


def efemeride(hoy: date, lista: list | None = None) -> dict | None:
    """La de hoy o la próxima dentro de DIAS_EFEMERIDE días. Puro si se le
    pasa la lista."""
    lista = _efemerides() if lista is None else lista
    mejor = None
    for e in lista:
        mes, dia = (int(x) for x in e["dia"].split("-"))
        for anio in (hoy.year, hoy.year + 1):
            try:
                d = date(anio, mes, dia)
            except ValueError:
                continue
            if hoy <= d <= hoy + timedelta(days=DIAS_EFEMERIDE) and (mejor is None or d < mejor[0]):
                mejor = (d, e)
    if not mejor:
        return None
    d, e = mejor
    return {"nombre": e["nombre"], "es_hoy": d == hoy,
            "cuando": "Hoy" if d == hoy else f"El {d.day} de {MESES[d.month - 1]}",
            "corto": "Hoy" if d == hoy else f"{d.day}/{d.month}"}


def datos_de_portada(latitud=None, longitud=None) -> dict:
    """Todo junto, para `GET /api/portada/datos`. Nunca levanta."""
    hoy = fechas.hoy()
    return {
        "fecha": fecha_texto(hoy),
        "clima": clima(latitud, longitud) if latitud is not None and longitud is not None else None,
        "feriado": proximo_feriado(hoy, (feriados(hoy.year) or []) + (feriados(hoy.year + 1) or []
                                                                      if hoy.month == 12 else [])),
        "efemeride": efemeride(hoy),
    }
