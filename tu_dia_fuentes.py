"""Los servicios de afuera de «Tu día»: clima, dólar oficial y centroides.

Siempre desde el servidor (la CSP no deja salir al navegador) y con caché en
la base (`db.CacheExterna`: Render corre un proceso por núcleo). Cada pedido
tiene `TIEMPO_MAXIMO` segundos; si un servicio falla o tarda, esa pieza vale
None y el resto sale igual: nunca un 500 por un tercero. Una falla se recuerda
cinco minutos, para no golpear un servicio caído en cada portada.

- Clima: MET Norway (api.met.no, Instituto Meteorológico de Noruega), decisión
  de SDN del 2026-10-24: gratis también para uso comercial, con atribución
  (licencia CC BY 4.0) y un User-Agent que identifique la app. Las coordenadas
  salen redondeadas a dos decimales (~1 km) y nunca llegan al navegador.
- Dólar oficial: Banco Central (api.bcra.gob.ar, estadísticas cambiarias).
- Centroide de una localidad: Georef, vía geo.py.

El proveedor del clima está detrás de `clima()`: cambiarlo es cambiar esta
función y `_icono_met`.
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import db
import fechas
import geo

TIEMPO_MAXIMO = 2.0
USER_AGENT = "Colm3na/1.0 (plataforma sindical; https://github.com/snavello/MITRABAJOC)"
VIGENCIA_CLIMA = 30 * 60
VIGENCIA_FALLA = 5 * 60
VIGENCIA_CENTROIDE = 30 * 24 * 3600
ATRIBUCION_CLIMA = "MET Norway (Instituto Meteorológico de Noruega), licencia CC BY 4.0"
BA = timezone(timedelta(hours=-3))

TEXTO_CLIMA = {"sol": "Despejado", "parcial": "Parcialmente nublado", "nublado": "Nublado",
               "niebla": "Niebla", "lluvia": "Lluvia", "tormenta": "Tormenta", "nieve": "Nieve",
               "viento": "Viento fuerte"}


def _pedir_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIEMPO_MAXIMO) as r:   # noqa: S310 (URLs fijas, https)
        return json.loads(r.read().decode("utf-8"))


def _con_cache(clave: str, vigencia: float, buscar):
    """Lo guardado si está vigente; si no, `buscar()` y se guarda. Una
    excepción de `buscar` vale None (y se recuerda VIGENCIA_FALLA)."""
    ahora = time.time()
    try:
        hay, valor = db.cache_externa_leer(clave, ahora)
    except Exception:
        hay, valor = False, None
    if hay:
        return valor
    try:
        valor = buscar()
    except Exception:
        valor = None
    try:
        db.cache_externa_guardar(clave, valor, ahora + (vigencia if valor is not None else VIGENCIA_FALLA))
    except Exception:
        pass
    return valor


# ---------------------------------------------------------------- clima ----

def _icono_met(simbolo: str, viento: float = 0) -> str:
    """symbol_code de MET Norway ("lightrainshowers_day") -> uno de los
    íconos de la franja."""
    s = (simbolo or "").split("_")[0]
    if "thunder" in s:
        return "tormenta"
    if "snow" in s:
        return "nieve"
    if "rain" in s or "sleet" in s:
        return "lluvia"
    if s == "fog":
        return "niebla"
    if viento >= 10.8:          # ~39 km/h
        return "viento"
    if s == "clearsky":
        return "sol"
    if s in ("fair", "partlycloudy"):
        return "parcial"
    return "nublado"


def _a_ba(texto_utc: str) -> datetime:
    return datetime.fromisoformat(texto_utc.replace("Z", "+00:00")).astimezone(BA).replace(tzinfo=None)


def resumir_met(datos: dict, hoy: date) -> dict | None:
    """Puro: la respuesta de MET Norway -> lo que muestra la franja.
    {"temp", "icono", "texto", "pronostico": [{"dia", "icono", "max"}, ...]}"""
    serie = (datos or {}).get("properties", {}).get("timeseries") or []
    if not serie:
        return None
    ahora = serie[0]["data"]
    det = ahora["instant"]["details"]
    sim = ((ahora.get("next_1_hours") or ahora.get("next_6_hours") or {}).get("summary") or {}).get("symbol_code", "")
    icono = _icono_met(sim, det.get("wind_speed", 0))
    pron = []
    for n in (1, 2):
        dia = hoy + timedelta(days=n)
        horas = [(p, _a_ba(p["time"])) for p in serie]
        del_dia = [(p, t) for p, t in horas if t.date() == dia]
        if not del_dia:
            continue
        maxima = max(p["data"]["instant"]["details"]["air_temperature"] for p, _ in del_dia)
        # El ícono del día: el pronóstico de las seis horas desde el mediodía.
        cerca = min(del_dia, key=lambda pt: abs(pt[1].hour - 12))[0]["data"]
        s = ((cerca.get("next_6_hours") or cerca.get("next_12_hours") or cerca.get("next_1_hours") or {})
             .get("summary") or {}).get("symbol_code", "")
        pron.append({"dia": "mañana" if n == 1 else ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")[dia.weekday()],
                     "icono": _icono_met(s), "max": round(maxima)})
    return {"temp": round(det["air_temperature"]), "icono": icono, "texto": TEXTO_CLIMA[icono],
            "pronostico": pron}


def clima(latitud, longitud) -> dict | None:
    try:
        lat, lon = round(float(latitud), 2), round(float(longitud), 2)
    except (TypeError, ValueError):
        return None
    if not (-56 <= lat <= -21 and -74 <= lon <= -53):     # fuera de la Argentina: no se pide
        return None
    hoy = fechas.hoy()

    def buscar():
        q = urllib.parse.urlencode({"lat": lat, "lon": lon})
        return _pedir_json(f"https://api.met.no/weatherapi/locationforecast/2.0/compact?{q}")
    crudo = _con_cache(f"clima|{lat}|{lon}", VIGENCIA_CLIMA, buscar)
    try:
        return resumir_met(crudo, hoy)
    except Exception:
        return None


# ---------------------------------------------------------------- dólar ----

def resumir_bcra(datos: dict, hoy: date) -> dict | None:
    """Puro: la respuesta del BCRA -> {"fecha", "valor", "anterior"} con el
    último cierre ANTERIOR a hoy (el de hoy todavía no cerró)."""
    filas = []
    for r in (datos or {}).get("results") or []:
        for d in r.get("detalle") or []:
            if d.get("codigoMoneda") == "USD" and d.get("tipoCotizacion"):
                filas.append((r["fecha"], float(d["tipoCotizacion"])))
    filas = sorted(f for f in filas if f[0] < hoy.isoformat())
    if not filas:
        return None
    fecha, valor = filas[-1]
    return {"fecha": fecha, "valor": valor, "anterior": filas[-2][1] if len(filas) > 1 else None}


def dolar_oficial() -> dict | None:
    hoy = fechas.hoy()
    # Vale hasta el día siguiente: el cierre de ayer no cambia en el día.
    falta = (datetime.combine(hoy + timedelta(days=1), datetime.min.time()) - fechas.ahora()).total_seconds()

    def buscar():
        q = urllib.parse.urlencode({"fechadesde": (hoy - timedelta(days=10)).isoformat(), "fechahasta": hoy.isoformat()})
        return resumir_bcra(_pedir_json(f"https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/USD?{q}"), hoy)
    return _con_cache(f"dolar|{hoy.isoformat()}", max(falta, 60), buscar)


# ------------------------------------------------------------ ubicación ----

def centroide(provincia: str, localidad: str):
    """(lat, lon) de una localidad según Georef, o None."""
    if not provincia or not localidad:
        return None
    clave = "centroide|" + geo.clave_cache(provincia, localidad)

    def buscar():
        prov = geo.provincia_canonica(provincia)
        loc = geo._localidad_canonica(prov, localidad) if prov else None
        if loc and geo.coordenadas_validas(loc.get("lat"), loc.get("lon")):
            return {"lat": loc["lat"], "lon": loc["lon"]}
        return None
    v = _con_cache(clave, VIGENCIA_CENTROIDE, buscar)
    return (v["lat"], v["lon"]) if v else None


def ubicacion(perfil: dict | None, seccional: dict | None):
    """(lat, lon, localidad) para el clima, en el orden del pedido: el
    domicilio de la persona, el centroide de su localidad, su seccional. Las
    coordenadas se quedan en el servidor."""
    p = perfil or {}
    if geo.coordenadas_validas(p.get("latitud"), p.get("longitud")):
        return p["latitud"], p["longitud"], p.get("localidad") or ""
    c = centroide(p.get("provincia") or "", p.get("localidad") or "")
    if c:
        return c[0], c[1], p.get("localidad") or ""
    s = seccional or {}
    if geo.coordenadas_validas(s.get("latitud"), s.get("longitud")):
        return s["latitud"], s["longitud"], s.get("localidad") or s.get("nombre") or ""
    return None, None, ""
