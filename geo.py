"""Geocodificación de domicilios: Georef (Argentina) + Nominatim (OSM).

Le da coordenadas a las Seccionales del sindicato y al domicilio del
afiliado. Las dos cosas usan el MISMO bloque de campos y la MISMA función,
que es lo que hace que se carguen igual en las tres pantallas que las
piden.

Reglas que no se negocian, y por qué:

**Todo pedido sale del SERVIDOR, nunca del navegador.** Así se controla la
tasa (Nominatim permite 1 pedido por segundo y bloquea por IP al que se
pasa), se cachea, y el día que una de las dos APIs cambie el formato se
arregla en un archivo en vez de en el JS de cuatro pantallas.

**Nunca se autocompleta contra Nominatim.** Se geocodifica solo cuando una
persona aprieta "Buscar". Georef sí se puede consultar tecla a tecla (su
política lo permite y es para eso), y por eso las sugerencias de localidad
salen de ahí y no de OSM.

**Ningún fallo de estas APIs bloquea un alta.** Si Georef o Nominatim no
responden, `normalizar_direccion` devuelve cero candidatos con un aviso
legible y la fila se guarda `sin_geo`. Una seccional sin ubicar es un
estado válido del sistema; una seccional que no se pudo dar de alta porque
un servicio ajeno estaba caído, no.

**Sin claves ni cuentas.** Las dos APIs son públicas y gratuitas. Lo único
que piden es identificarse con un User-Agent real, que es `USER_AGENT`.

La parte de arriba de este archivo (armar el texto, normalizar la clave,
haversine) es PURA y se prueba sin red ni base. La parte de abajo sale a la
red, y toda salida pasa por `_pedir_json`, que es el único punto que los
tests reemplazan.
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

import fechas

# ---------------------------------------------------------------- contrato

# El bloque de domicilio que comparten `Seccional` y `Trabajador`. Es un
# contrato explícito y no un comentario porque `test_seccional_geo.py` lo
# verifica contra las dos tablas: si alguien le suma un campo a una y se
# olvida de la otra, la suite lo dice con nombre y apellido. Las dos
# direcciones de la app se escriben igual para que se carguen igual.
CAMPOS_DOMICILIO = (
    "calle", "numero", "piso_depto", "localidad", "provincia", "codigo_postal",
    "direccion_texto", "latitud", "longitud", "precision_geo", "geo_actualizado",
)

# exacta     = Nominatim resolvió calle Y altura
# aproximada = se ubicó la calle o la localidad, pero no la puerta
# manual     = una persona arrastró el globo hasta donde va
# sin_geo    = todavía no se ubicó (estado inicial y estado de fallback)
PRECISIONES = ("exacta", "aproximada", "manual", "sin_geo")

ETIQUETAS_PRECISION = {
    "exacta": "Dirección exacta",
    "aproximada": "Ubicación aproximada",
    "manual": "Ubicada a mano",
    "sin_geo": "Sin ubicar",
}

# Texto de ayuda del paso 2 del asistente. Vive acá y no en la plantilla
# porque es lo que le explica a una persona qué tan confiable es el globo
# que está viendo, y tiene que decir lo mismo en el alta de seccional y en
# el domicilio del afiliado.
AYUDA_PRECISION = {
    "exacta": "Encontramos la dirección exacta. Si el globo no está en la puerta, arrastralo.",
    "aproximada": "No encontramos la altura exacta: arrastrá el globo hasta la puerta.",
    "manual": "Ubicación puesta a mano. Arrastrá el globo si querés corregirla.",
    "sin_geo": "Todavía sin ubicar.",
}

GEOREF = "https://apis.datos.gob.ar/georef/api"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# Nominatim exige un User-Agent que identifique a la aplicación y permita
# contactar a quien la opera. Un "Mozilla/5.0" acá es motivo de bloqueo.
USER_AGENT = "MiTrabajo/1.0 (plataforma sindical; https://github.com/snavello/MITRABAJOC)"

TTL_CACHE_DIAS = 90
SEGUNDOS_ENTRE_PEDIDOS = 1.0
MAX_CANDIDATOS = 5
TIMEOUT_SEGUNDOS = 8

# Un candidato más lejos que esto del centro de la localidad pedida NO es de
# esa localidad y se descarta. Medido con un caso real: "San Juan 430,
# Córdoba" devuelve calles con ese nombre en Morrison y en Alicia, a 200 km
# de Córdoba capital, porque el parámetro `city` de Nominatim orienta pero no
# acota. Sin este filtro, el admin elige de una lista donde el primer globo
# está en otra ciudad y no tiene forma de darse cuenta.
# 60 km deja pasar un partido grande del conurbano o un ejido municipal
# extenso, y corta lo que ya es otra ciudad.
RADIO_LOCALIDAD_KM = 60

# Las direcciones argentinas se escriben abreviadas, y Nominatim no las
# expande: "Bv. San Juan 430" en Córdoba devuelve CERO resultados y
# "Boulevard San Juan 430" los encuentra. Medido el 2026-09-12. Sin esta
# tabla, media provincia de Córdoba es imposible de geocodificar.
ABREVIATURAS = {
    "av": "Avenida", "av.": "Avenida", "avda": "Avenida", "avda.": "Avenida",
    "bv": "Boulevard", "bv.": "Boulevard", "blv": "Boulevard", "blv.": "Boulevard",
    "bvd": "Boulevard", "bvd.": "Boulevard", "bulevar": "Boulevard",
    "gral": "General", "gral.": "General",
    "cnel": "Coronel", "cnel.": "Coronel",
    "tte": "Teniente", "tte.": "Teniente",
    "pte": "Presidente", "pte.": "Presidente",
    "dr": "Doctor", "dr.": "Doctor", "dra": "Doctora", "dra.": "Doctora",
    "ing": "Ingeniero", "ing.": "Ingeniero",
    "pje": "Pasaje", "pje.": "Pasaje",
    "sgto": "Sargento", "sgto.": "Sargento",
    "almte": "Almirante", "almte.": "Almirante",
    "pdte": "Presidente", "pdte.": "Presidente",
    "mons": "Monseñor", "mons.": "Monseñor",
}

# Tope por actor y por hora. El domicilio del afiliado lo edita el propio
# afiliado, así que este endpoint no es solo de admins: sin tope, un
# sindicato con 5.000 afiliados nos hace bloquear por Nominatim en una
# tarde. 20 alcanza de sobra para cargar una dirección con idas y vueltas.
TOPE_POR_ACTOR = 20
VENTANA_TOPE_SEGUNDOS = 3600


# ------------------------------------------------------- puro (sin red/db)

def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn")


def _norm(texto: str) -> str:
    """Minúsculas, sin tildes, sin espacios de más."""
    return " ".join(_sin_tildes(str(texto or "")).lower().split())


def clave_cache(provincia: str, localidad: str, calle: str = "", numero: str = "") -> str:
    """La clave con la que una dirección se guarda y se busca en GeoCache.

    Normaliza para que "San Martín 850" y "san martin  850" sean la misma
    consulta: si no, la caché no ahorra nada, porque nadie escribe dos veces
    igual."""
    return "|".join(_norm(x) for x in (provincia, localidad, calle, numero))


def armar_direccion_texto(datos: dict) -> str:
    """La dirección como se muestra, armada de los campos estructurados.

    La arma el SERVIDOR y no cada pantalla: es el mismo motivo por el que el
    disclaimer de Encuestas lo arma el servidor. Si la tabla del panel, la
    ficha y la app del trabajador la compusieran cada una a su manera,
    habría tres direcciones distintas para la misma seccional y ninguna
    sería "la" dirección.

    Tolera huecos: con solo localidad y provincia devuelve "Rosario, Santa
    Fe", que es información útil, en vez de una cadena con comas sueltas.
    """
    calle = str(datos.get("calle") or "").strip()
    numero = str(datos.get("numero") or "").strip()
    piso = str(datos.get("piso_depto") or "").strip()
    localidad = str(datos.get("localidad") or "").strip()
    provincia = str(datos.get("provincia") or "").strip()
    cp = str(datos.get("codigo_postal") or "").strip()

    calle_y_altura = " ".join(x for x in (calle, numero) if x)
    if piso:
        calle_y_altura = f"{calle_y_altura}, {piso}" if calle_y_altura else piso
    localidad_y_prov = ", ".join(x for x in (localidad, provincia) if x)
    if cp and localidad_y_prov:
        localidad_y_prov = f"{localidad_y_prov} (CP {cp})"
    elif cp:
        localidad_y_prov = f"CP {cp}"
    return ", ".join(x for x in (calle_y_altura, localidad_y_prov) if x)


def expandir_abreviaturas(calle: str) -> str:
    """"Bv. San Juan" -> "Boulevard San Juan", para que Nominatim la encuentre.

    Se expande solo para CONSULTAR. Lo que se guarda es lo que la persona
    escribió: si el cartel de la esquina dice "Bv. San Juan", la dirección de
    la seccional dice lo mismo. Corregirle la ortografía al usuario en la
    base sería otra decisión, y no es esta."""
    palabras = str(calle or "").split()
    return " ".join(ABREVIATURAS.get(p.lower(), p) for p in palabras)


def normalizar_precision(valor: str) -> str:
    """Cualquier cosa que no sea una de las cuatro precisiones es `sin_geo`.

    Fail-closed: un valor inventado que llegara de un POST armado a mano no
    puede terminar en la base diciendo "exacta"."""
    valor = (valor or "").strip()
    return valor if valor in PRECISIONES else "sin_geo"


def coordenadas_validas(lat, lon) -> bool:
    """True solo si las dos son números dentro del rango del planeta.

    Se chequea antes de guardar: un globo arrastrado llega como texto desde
    el navegador, y un 0/0 (el Golfo de Guinea) o un None son los dos
    valores que más fácil se cuelan cuando el JS falla."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if lat == 0 and lon == 0:
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


def distancia_km(lat1, lon1, lat2, lon2) -> Optional[float]:
    """Haversine. Devuelve None si falta o no sirve alguna coordenada.

    El cliente calcula lo mismo en JS para la lista de "cerca de mí" (la
    posición del teléfono no viaja al servidor). Esta copia es para el
    orden por domicilio guardado, que sí se resuelve en el servidor."""
    import math
    if not (coordenadas_validas(lat1, lon1) and coordenadas_validas(lat2, lon2)):
        return None
    lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    radio = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return round(radio * 2 * math.asin(math.sqrt(a)), 2)


def vencido(creado: str, hoy: Optional[datetime] = None) -> bool:
    """True si un sello "AAAA-MM-DD HH:MM" ya pasó el TTL de la caché.

    Un sello ilegible se toma como vencido: ante la duda se vuelve a
    preguntar, que es barato, en vez de servir algo que no se sabe de
    cuándo es."""
    hoy = hoy or fechas.ahora()
    try:
        cuando = datetime.strptime((creado or "").strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return True
    return cuando < hoy - timedelta(days=TTL_CACHE_DIAS)


# --------------------------------------------------------- tasa y cortesía

_candado_red = threading.Lock()
_ultimo_pedido = 0.0

# {actor: [timestamps]} -- en memoria, por proceso. Ver `permitir_a`.
_usos_por_actor: dict[str, list[float]] = {}
_candado_usos = threading.Lock()


def _esperar_turno() -> None:
    """Garantiza al menos `SEGUNDOS_ENTRE_PEDIDOS` entre dos salidas a la red.

    El candado es POR PROCESO. Render corre un worker por núcleo, así que
    con 4 workers el peor caso son 4 pedidos por segundo, no 1. Se acepta a
    ojos abiertos: geocodificar lo dispara una persona apretando "Buscar",
    de a una dirección, y la caché se come los repetidos. Si algún día esto
    no alcanza, el patrón que ya usa el proyecto para coordinar instancias
    es un UPDATE condicional en la base (ver db.reclamar_plan_programado),
    no un candado más grande.
    """
    global _ultimo_pedido
    espera = SEGUNDOS_ENTRE_PEDIDOS - (time.monotonic() - _ultimo_pedido)
    if espera > 0:
        time.sleep(espera)
    _ultimo_pedido = time.monotonic()


def permitir_a(actor: str, tope: int = TOPE_POR_ACTOR) -> bool:
    """¿Este actor puede geocodificar una vez más en esta hora?

    `actor` es el CUIL del afiliado o el id del usuario del panel -- nunca
    la IP, que en un gremio con wifi compartido es la misma para todos.
    En memoria y por proceso a propósito: es cortesía con Nominatim, no
    control de acceso, y una tabla nueva más una escritura por búsqueda no
    se justifican para eso.
    """
    ahora = time.monotonic()
    with _candado_usos:
        usos = [t for t in _usos_por_actor.get(actor, []) if ahora - t < VENTANA_TOPE_SEGUNDOS]
        if len(usos) >= tope:
            _usos_por_actor[actor] = usos
            return False
        usos.append(ahora)
        _usos_por_actor[actor] = usos
        return True


def reiniciar_topes() -> None:
    """Limpia los contadores. Solo para los tests."""
    with _candado_usos:
        _usos_por_actor.clear()


# ------------------------------------------------------------------- red

def _pedir_json(url: str):
    """La ÚNICA salida a la red de este módulo.

    Todo pasa por acá para que los tests reemplacen una sola función y para
    que el User-Agent y el timeout no se puedan olvidar en una llamada
    nueva. Devuelve None ante cualquier problema -- de red, de HTTP o de
    JSON: quien llama tiene que estar preparado para no tener respuesta, y
    un solo camino de fallo es más fácil de sostener que tres.
    """
    try:
        pedido = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "es-AR,es",
        })
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEGUNDOS) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            ValueError, OSError):
        return None


def _georef(recurso: str, **params):
    url = f"{GEOREF}/{recurso}?" + urllib.parse.urlencode(params)
    return _pedir_json(url)


def provincia_canonica(nombre: str) -> Optional[dict]:
    """Valida una provincia contra Georef y devuelve su nombre oficial + centroide.

    Sirve de red de seguridad del `<select>`: el nombre que llega de un
    formulario se confirma contra el organismo que las define, no contra una
    lista nuestra que puede quedar vieja."""
    if not (nombre or "").strip():
        return None
    datos = _georef("provincias", nombre=nombre, campos="id,nombre,centroide")
    if not datos:
        return None
    for p in datos.get("provincias") or []:
        return {"id": p.get("id", ""), "nombre": p.get("nombre", ""),
                "lat": (p.get("centroide") or {}).get("lat"),
                "lon": (p.get("centroide") or {}).get("lon")}
    return None


def sugerir_localidades(provincia: str, texto: str, maximo: int = 8) -> list:
    """Localidades de Georef que matchean lo tipeado, para el autocompletar.

    Esto SÍ puede correr tecla a tecla: es Georef, cuya política lo permite
    y que existe justamente para esto. Nominatim no se toca acá."""
    texto = (texto or "").strip()
    if len(texto) < 2:
        return []
    params = {"nombre": texto, "max": max(1, min(maximo, 20)),
              "campos": "id,nombre,centroide,provincia"}
    prov = provincia_canonica(provincia) if (provincia or "").strip() else None
    if prov and prov.get("id"):
        params["provincia"] = prov["id"]
    datos = _georef("localidades", **params)
    if not datos:
        return []
    salida = []
    for loc in datos.get("localidades") or []:
        centro = loc.get("centroide") or {}
        salida.append({
            "nombre": loc.get("nombre", ""),
            "provincia": (loc.get("provincia") or {}).get("nombre", ""),
            "lat": centro.get("lat"), "lon": centro.get("lon"),
        })
    return salida


def _localidad_canonica(prov: Optional[dict], localidad: str) -> Optional[dict]:
    """La localidad oficial dentro de esa provincia, con su centroide.

    El centroide es el que se usa cuando Nominatim no encuentra la calle:
    es el fallback `aproximada`."""
    if not (localidad or "").strip():
        return None
    params = {"nombre": localidad, "max": 5, "campos": "id,nombre,centroide,provincia"}
    if prov and prov.get("id"):
        params["provincia"] = prov["id"]
    datos = _georef("localidades", **params)
    if not datos:
        return None
    candidatas = datos.get("localidades") or []
    if not candidatas:
        return None
    # Preferir el match exacto de nombre antes que el primero que devuelva
    # Georef: buscando "Rosario" en Santa Fe, el primero podría ser
    # "Rosario del Tala" si alguna vez cambia el orden del ranking.
    buscada = _norm(localidad)
    elegida = next((l for l in candidatas if _norm(l.get("nombre", "")) == buscada), candidatas[0])
    centro = elegida.get("centroide") or {}
    return {"nombre": elegida.get("nombre", ""),
            "provincia": (elegida.get("provincia") or {}).get("nombre", ""),
            "lat": centro.get("lat"), "lon": centro.get("lon")}


def _es_puerta(item: dict) -> bool:
    """¿Este resultado de Nominatim es una altura concreta y no una calle entera?

    `place_rank` 30 es el nivel de "casa/edificio" de Nominatim; los tipos
    son por si algún día cambia el ranking. Sin esto, una calle de veinte
    cuadras se guardaría como `exacta` apuntando al medio de la calle."""
    if item.get("addresstype") in ("house", "building") or item.get("type") in ("house", "building"):
        return True
    try:
        return int(item.get("place_rank") or 0) >= 30
    except (TypeError, ValueError):
        return False


def _buscar_calle(prov_nombre: str, localidad: str, calle: str, numero: str) -> list:
    """Nominatim con consulta ESTRUCTURADA, acotada al país y a la localidad.

    Estructurada y no texto libre: mandar todo junto en `q` hace que una
    localidad homónima de otra provincia gane por popularidad. Con `state` y
    `city` separados, el resultado cae donde tiene que caer."""
    calle_y_altura = " ".join(x for x in (str(numero or "").strip(),
                                          expandir_abreviaturas(calle).strip()) if x)
    if not calle_y_altura:
        return []
    params = {
        "format": "jsonv2", "addressdetails": 1, "countrycodes": "ar",
        "limit": MAX_CANDIDATOS, "street": calle_y_altura,
    }
    if (localidad or "").strip():
        params["city"] = localidad.strip()
    if (prov_nombre or "").strip():
        params["state"] = prov_nombre.strip()
    _esperar_turno()
    datos = _pedir_json(f"{NOMINATIM}?" + urllib.parse.urlencode(params))
    return datos if isinstance(datos, list) else []


# ------------------------------------------------------------------ caché

def _de_cache(clave: str) -> Optional[list]:
    """La respuesta guardada para esa clave, si existe y no venció.

    `db` se importa acá dentro y no arriba a propósito: la mitad pura de
    este módulo se prueba sin base, y un import de db en el encabezado
    obligaría a tener Postgres levantado para probar un haversine."""
    import db
    fila = db.geocache_leer(clave)
    if not fila:
        return None
    if vencido(fila.get("creado", "")):
        return None
    respuesta = fila.get("respuesta_json")
    return respuesta if isinstance(respuesta, list) else None


def _a_cache(clave: str, candidatos: list) -> None:
    import db
    db.geocache_guardar(clave, candidatos)


# --------------------------------------------------------------- fachada

def normalizar_direccion(provincia: str, localidad: str, calle: str = "",
                         numero: str = "", usar_cache: bool = True) -> dict:
    """Resuelve una dirección argentina a una lista de candidatos ubicables.

    El camino es: Georef valida provincia y localidad (y da el centroide),
    después Nominatim busca la calle y la altura DENTRO de esa localidad. Si
    Nominatim no la encuentra, se devuelve el centroide de la localidad con
    precisión `aproximada` -- tener el barrio es mejor que no tener nada, y
    el paso 2 del asistente le pide a la persona que arrastre el globo.

    Devuelve siempre un dict con la misma forma:
        {"candidatos": [...], "aviso": str, "provincia": str, "localidad": str}

    `aviso` en "" significa que salió bien. Con cualquier problema -- APIs
    caídas, provincia que no existe, localidad que no existe -- devuelve
    cero candidatos y un aviso legible, NUNCA una excepción: quien llama
    tiene que poder seguir guardando la fila como `sin_geo`.
    """
    clave = clave_cache(provincia, localidad, calle, numero)
    if usar_cache:
        guardado = _de_cache(clave)
        if guardado is not None:
            return {"candidatos": guardado, "aviso": "",
                    "provincia": (guardado[0]["provincia"] if guardado else provincia),
                    "localidad": (guardado[0]["localidad"] if guardado else localidad),
                    "de_cache": True}

    prov = provincia_canonica(provincia)
    if not prov:
        return {"candidatos": [], "provincia": provincia, "localidad": localidad,
                "aviso": ("No pudimos verificar la provincia. Podés guardar igual y "
                          "ubicar la seccional en el mapa más tarde.")}

    # Una localidad que Georef no reconoce NO es un error. El caso que lo
    # obligó es CABA: ahí las "localidades" de Georef son los 49 BARRIOS
    # (Constitución, Retiro, Recoleta...), así que nadie que escriba una
    # dirección porteña va a tipear una localidad que resuelva -- y sin
    # embargo Nominatim encuentra "Av. Independencia 1200" perfectamente.
    # Si esto cortara, toda la Capital quedaría imposible de georreferenciar.
    # Lo que se pierde sin localidad canónica es el centroide, o sea el
    # fallback fino; se cae al de la provincia, que es peor pero sirve.
    loc = _localidad_canonica(prov, localidad)
    centro_loc = loc if loc and coordenadas_validas(loc.get("lat"), loc.get("lon")) else None

    candidatos = []
    for item in _buscar_calle(prov["nombre"], loc["nombre"] if loc else "", calle, numero):
        if not isinstance(item, dict):
            continue
        # La salida de Nominatim NO es un contrato. Un item con forma válida
        # pero lat/lon ilegibles (o nulas) se DESCARTA en vez de reventar la
        # pantalla: misma regla que validador.a_numero con lo que devuelve la
        # IA. Sin esto, un solo resultado raro tumbaba el alta entera.
        if not coordenadas_validas(item.get("lat"), item.get("lon")):
            continue
        lat, lon = float(item["lat"]), float(item["lon"])
        # ¿Cae de verdad en la localidad pedida? `city` de Nominatim orienta
        # pero no acota (ver RADIO_LOCALIDAD_KM): un homónimo a 200 km llega
        # en la misma lista y, sin este corte, primero.
        lejania = distancia_km(lat, lon, centro_loc["lat"], centro_loc["lon"]) if centro_loc else None
        if lejania is not None and lejania > RADIO_LOCALIDAD_KM:
            continue
        direccion = (item.get("address") or {})
        cp = str(direccion.get("postcode") or "").strip()
        datos = {
            "calle": (calle or "").strip(), "numero": (numero or "").strip(),
            "piso_depto": "",
            "localidad": loc["nombre"] if loc else str(
                direccion.get("city") or direccion.get("town") or localidad or "").strip(),
            "provincia": prov["nombre"], "codigo_postal": cp,
        }
        candidatos.append({
            "direccion_texto": armar_direccion_texto(datos),
            "lat": lat, "lon": lon,
            "precision": "exacta" if _es_puerta(item) else "aproximada",
            "etiqueta": str(item.get("display_name") or "")[:160],
            "localidad": datos["localidad"], "provincia": prov["nombre"],
            "codigo_postal": cp,
            # Solo para ordenar; no se guarda ni viaja como dato del domicilio.
            "_km": lejania if lejania is not None else 0.0,
        })

    # El más cercano al centro de la localidad primero: con varios homónimos
    # dentro del radio, el que está en el centro de la ciudad es el que la
    # persona buscaba nueve de cada diez veces.
    candidatos.sort(key=lambda c: c["_km"])
    for c in candidatos:
        c.pop("_km", None)
    candidatos = candidatos[:MAX_CANDIDATOS]

    aviso = ""
    if not candidatos:
        # Fallback al centroide de la localidad. Es la diferencia entre "no
        # sabemos nada" y "sabemos en qué ciudad está": con esto el mapa
        # abre en el lugar correcto y arrastrar el globo es un gesto, no una
        # búsqueda a mano por todo el país.
        # Sin localidad canónica (el caso CABA) cae al centro de la
        # provincia, que para una jurisdicción chica es tan útil como el de
        # la localidad, y para una grande al menos abre el mapa en el país
        # correcto.
        centro = centro_loc or prov
        donde = (loc["nombre"] if loc else (localidad or "").strip())
        if coordenadas_validas(centro.get("lat"), centro.get("lon")):
            datos = {"calle": (calle or "").strip(), "numero": (numero or "").strip(),
                     "localidad": donde,
                     "provincia": prov["nombre"], "codigo_postal": ""}
            candidatos = [{
                "direccion_texto": armar_direccion_texto(datos),
                "lat": float(centro["lat"]), "lon": float(centro["lon"]),
                "precision": "aproximada",
                "etiqueta": (f"Centro de {donde}, {prov['nombre']}" if centro_loc
                             else f"Centro de {prov['nombre']}"),
                "localidad": donde,
                "provincia": prov["nombre"], "codigo_postal": "",
            }]
            aviso = ("No encontramos la altura exacta. El globo quedó en el centro de "
                     + ("la localidad" if centro_loc else "la provincia")
                     + ": arrastralo hasta la puerta.")
        else:
            aviso = ("No pudimos ubicar la dirección. Podés guardar igual y ubicarla "
                     "en el mapa más tarde.")

    if usar_cache and candidatos:
        _a_cache(clave, candidatos)
    return {"candidatos": candidatos, "aviso": aviso,
            "provincia": prov["nombre"],
            "localidad": loc["nombre"] if loc else (localidad or "").strip()}


def campos_para_guardar(datos: dict, precision: str, lat=None, lon=None) -> dict:
    """El bloque de domicilio listo para escribir en Seccional o Trabajador.

    Un solo lugar que decide qué se guarda, para que el alta de seccional,
    su edición, el alta de trabajador, el alta masiva y el perfil del
    afiliado no puedan diferir. Y una sola regla sobre la precisión: **sin
    coordenadas válidas no hay precisión que valga** -- se fuerza `sin_geo`,
    porque una fila que dice "exacta" con lat/lon en NULL es peor que una
    que admite no estar ubicada.
    """
    salida = {
        "calle": str(datos.get("calle") or "").strip()[:200],
        "numero": str(datos.get("numero") or "").strip()[:20],
        "piso_depto": str(datos.get("piso_depto") or "").strip()[:40],
        "localidad": str(datos.get("localidad") or "").strip()[:120],
        "provincia": str(datos.get("provincia") or "").strip()[:60],
        "codigo_postal": str(datos.get("codigo_postal") or "").strip()[:12],
    }
    salida["direccion_texto"] = armar_direccion_texto(salida)[:400]
    if coordenadas_validas(lat, lon):
        salida["latitud"], salida["longitud"] = float(lat), float(lon)
        salida["precision_geo"] = normalizar_precision(precision)
        if salida["precision_geo"] == "sin_geo":
            # Llegaron coordenadas pero sin una precisión que las explique:
            # se toma como puestas a mano, que es lo que efectivamente son.
            salida["precision_geo"] = "manual"
        salida["geo_actualizado"] = fechas.ahora_texto()
    else:
        salida["latitud"], salida["longitud"] = None, None
        salida["precision_geo"] = "sin_geo"
        salida["geo_actualizado"] = ""
    return salida
