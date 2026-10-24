"""«Tu día»: la franja de la portada del afiliado (docs/chat/2026-10-24-pedido-tu-dia.md).

Puro: no importa `db` ni sale a la red. Dice qué rubros existen, cómo se guarda
la configuración del sindicato, qué ítem de cada rubro toca hoy y cómo se arma
la lista que rota. Las llamadas a los servicios de afuera (clima, dólar) viven
en `tu_dia_fuentes.py`; la ruta las junta en `main.api_tu_dia`.

Decisiones de SDN (2026-10-24): el clima de MET Norway; los rubros que rotan no
incluyen feriados; de mercados, solo el dólar oficial; y el cumpleaños no es un
ítem de la rotación sino un saludo animado que la persona ve UNA vez, ocho
segundos, el día de su cumpleaños.
"""
import hashlib
import json
from datetime import date
from pathlib import Path

CARPETA = Path(__file__).parent / "data" / "tu_dia"

# El catálogo, en el orden en que se muestran en el panel. "archivo": los
# rubros curados (data/tu_dia/<rubro>.json); mercados sale de un servicio.
RUBROS = {
    "efemerides": {"nombre": "Efemérides nacionales y obreras",
                   "desc": "Una por día: historia del país y del trabajo."},
    "mercados": {"nombre": "Dólar oficial",
                 "desc": "La cotización oficial del Banco Central al cierre del día hábil anterior."},
    "curiosos": {"nombre": "Datos curiosos", "desc": "Historias cortas del país y del trabajo."},
    "ciencia": {"nombre": "Ciencia y técnica", "desc": "CONICET, CONAE, INTI, INTA e INVAP. Sin política."},
    "salud": {"nombre": "Salud", "desc": "Campañas y cuidados del Ministerio de Salud, según el mes."},
    "juego": {"nombre": "Entretenimiento", "desc": "Una pregunta por día, con tres opciones."},
    "consumidor": {"nombre": "Tus derechos como consumidor", "desc": "Un derecho por día, con la norma que lo dice."},
}
INTERVALOS = (6, 10, 15)
POR_DEFECTO = {"rubros": ["efemerides", "salud", "consumidor"], "politicas": False, "intervalo": 6}
CHIPS = {"curiosos": "¿Sabías?", "ciencia": "Ciencia", "salud": "Salud", "juego": "Juego",
         "consumidor": "Derechos", "mercados": "Dólar"}

DIAS_CORTOS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def normalizar_config(config) -> dict:
    """La configuración que se guarda: solo rubros del catálogo (sin
    repetir, en el orden pedido), un intervalo de los ofrecidos y la opción
    de las efemérides con carga política. Lo demás se descarta."""
    c = config if isinstance(config, dict) else {}
    rubros = []
    for r in c.get("rubros") or []:
        if r in RUBROS and r not in rubros:
            rubros.append(r)
    try:
        intervalo = int(c.get("intervalo", POR_DEFECTO["intervalo"]))
    except (TypeError, ValueError):
        intervalo = POR_DEFECTO["intervalo"]
    if intervalo not in INTERVALOS:
        intervalo = POR_DEFECTO["intervalo"]
    return {"rubros": rubros, "politicas": bool(c.get("politicas")), "intervalo": intervalo}


def config_efectiva(guardada) -> dict:
    """NULL en la base = los valores por defecto."""
    if not guardada:
        return dict(POR_DEFECTO, rubros=list(POR_DEFECTO["rubros"]))
    return normalizar_config(guardada)


_archivos: dict = {}


def cargar(rubro: str) -> list:
    """Los ítems de un rubro curado, releídos si el archivo cambió."""
    ruta = CARPETA / f"{rubro}.json"
    if not ruta.exists():
        return []
    marca = ruta.stat().st_mtime
    guardado = _archivos.get(rubro)
    if guardado and guardado[0] == marca:
        return guardado[1]
    items = json.loads(ruta.read_text(encoding="utf-8")).get("items", [])
    _archivos[rubro] = (marca, items)
    return items


def _semilla(fecha: date, rubro: str) -> int:
    """Determinista: todos ven lo mismo el mismo día (no hay azar por pedido)."""
    return int(hashlib.sha256(f"{fecha.isoformat()}|{rubro}".encode()).hexdigest(), 16)


def es_cumple(fecha_nacimiento, hoy: date) -> bool:
    """El 29 de febrero se festeja el 28 en los años que no son bisiestos."""
    try:
        n = date.fromisoformat(str(fecha_nacimiento)[:10])
    except (TypeError, ValueError):
        return False
    if (n.month, n.day) == (hoy.month, hoy.day):
        return True
    bisiesto = hoy.year % 4 == 0 and (hoy.year % 100 != 0 or hoy.year % 400 == 0)
    return (n.month, n.day) == (2, 29) and not bisiesto and (hoy.month, hoy.day) == (2, 28)


def candidatos(rubro: str, items: list, hoy: date, politicas: bool = False) -> list:
    """Lo que se puede mostrar hoy de un rubro: nunca lo marcado dudoso, las
    efemérides solo de este día (y las de carga política solo si el sindicato
    las prendió), la salud solo en sus meses."""
    lista = [i for i in items if not i.get("dudosa")]
    if rubro == "efemerides":
        mmdd = f"{hoy.month:02d}-{hoy.day:02d}"
        lista = [i for i in lista if i.get("mmdd") == mmdd and (politicas or not i.get("politica"))]
    elif rubro == "salud":
        lista = [i for i in lista if not i.get("meses") or hoy.month in i["meses"]]
    return lista


def item_del_dia(rubro: str, items: list, hoy: date, politicas: bool = False) -> dict | None:
    lista = candidatos(rubro, items, hoy, politicas)
    if not lista:
        return None
    i = lista[_semilla(hoy, rubro) % len(lista)]
    salida = {"rubro": rubro, "chip": i.get("chip") or CHIPS.get(rubro, ""), "linea": i.get("linea", ""),
              "titulo": i.get("titulo", ""), "texto": i.get("texto", ""), "fuente": i.get("fuente", "")}
    if rubro == "juego":
        salida.update(opciones=list(i.get("opciones") or []), correcta=i.get("correcta", 0),
                      explicacion=i.get("explicacion", ""))
    if rubro == "consumidor" and i.get("norma"):
        salida["norma"] = i["norma"]
    return salida


def pesos(valor: float) -> str:
    """1529.5 -> '$ 1.529,50'."""
    entero, dec = f"{valor:,.2f}".split(".")
    return "$ " + entero.replace(",", ".") + "," + dec


def item_dolar(cot: dict | None) -> dict | None:
    """El ítem de mercados a partir de {"fecha", "valor", "anterior"} (BCRA)."""
    if not cot or not cot.get("valor"):
        return None
    d = date.fromisoformat(cot["fecha"])
    linea = f"Oficial {pesos(cot['valor'])}"
    texto = f"Cotización oficial del dólar estadounidense del {d.day}/{d.month}/{d.year}: {pesos(cot['valor'])}."
    if cot.get("anterior"):
        var = (cot["valor"] - cot["anterior"]) / cot["anterior"] * 100
        flecha = "▲" if var > 0.005 else ("▼" if var < -0.005 else "=")
        linea += f" {flecha} {abs(var):.1f}%".replace(".", ",")
        texto += f" El día hábil anterior estaba a {pesos(cot['anterior'])}."
    linea += f", al cierre del {d.day}/{d.month}"
    return {"rubro": "mercados", "chip": "Dólar", "linea": linea, "titulo": "Dólar oficial",
            "texto": texto, "fuente": "Banco Central de la República Argentina, estadísticas cambiarias",
            "tabla": [["Dólar oficial (BCRA)", pesos(cot["valor"])]]}


def armar_items(config: dict, hoy: date, dolar: dict | None = None, cargador=cargar) -> list:
    """La lista que rota, en el orden de la configuración del sindicato.
    Un rubro sin nada para hoy (o un servicio caído) no aparece."""
    items = []
    for rubro in config.get("rubros", []):
        if rubro == "mercados":
            it = item_dolar(dolar)
        else:
            it = item_del_dia(rubro, cargador(rubro), hoy, config.get("politicas", False))
        if it:
            items.append(it)
    return items


def dia_corto(d: date, hoy: date) -> str:
    return "mañana" if (d - hoy).days == 1 else DIAS_CORTOS[d.weekday()]
