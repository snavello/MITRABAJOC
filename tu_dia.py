"""«Tu día»: la franja de la portada del afiliado (docs/chat/2026-10-24-pedido-tu-dia.md).

Puro: no importa `db` ni sale a la red. Dice qué rubros existen, cómo se guarda
la configuración del sindicato, qué ítem de cada rubro toca hoy y cómo se arma
la lista que rota. Las llamadas a los servicios de afuera (clima, dólar) viven
en `tu_dia_fuentes.py`; la ruta las junta en `main.api_tu_dia`.

Decisiones de SDN (2026-10-24): el clima de MET Norway; los rubros que rotan no
incluyen feriados; de mercados, solo el dólar oficial; y el cumpleaños no es un
ítem de la rotación sino un saludo animado que la persona ve UNA vez, ocho
segundos, el día de su cumpleaños.

Desde el 2026-11-10 (pedido de SDN) la hoja de detalle es un artículo corto:
título, tres o cuatro párrafos (`parrafos`) y el enlace a la fuente (`url`),
en TODOS los rubros; y Entretenimiento es una **trivia diaria de diez
preguntas** con puntaje de 0 a 10 (`trivia_del_dia`): el kit se renueva solo
con la fecha de Buenos Aires, a la madrugada o con el primero que entra, sin
tarea programada ni estado en la base (es determinista por fecha), y en una
tanda de N/10 días ninguna pregunta se repite.
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
    "juego": {"nombre": "Entretenimiento",
              "desc": "La trivia del día: diez preguntas con puntaje, un kit nuevo cada madrugada."},
    "consumidor": {"nombre": "Tus derechos como consumidor", "desc": "Un derecho por día, con la norma que lo dice."},
}
INTERVALOS = (6, 10, 15)
POR_DEFECTO = {"rubros": ["efemerides", "salud", "consumidor"], "politicas": False, "intervalo": 6}
CHIPS = {"curiosos": "¿Sabías?", "ciencia": "Ciencia", "salud": "Salud", "juego": "Trivia",
         "consumidor": "Derechos", "mercados": "Dólar"}

# La trivia diaria (2026-11-10): cuántas preguntas por día, el orden de los
# niveles dentro del kit (de fácil a difícil) y el comentario de cada puntaje:
# aliento hasta 4, elogio creciente de 5 en adelante (pedido de SDN).
TRIVIA_PREGUNTAS = 10
TRIVIA_SEGUNDOS = 30          # por pregunta; se acaba = cuenta como no respondida
NIVELES = ("facil", "media", "dificil")
COMENTARIOS_PUNTAJE = (
    ("Hoy no fue.", "No pasa nada: mañana a la madrugada hay diez preguntas nuevas. Leé las respuestas, "
                    "que ahí está la gracia, y la próxima te sorprendés."),
    ("Una bien: por algo se empieza.", "Mañana vuelve la trivia con otras diez. Un rato con las explicaciones "
                                       "de hoy y la próxima suma."),
    ("Dos bien. Esto recién arranca.", "Las de hoy estaban bravas, y mañana hay revancha. Mirá las que te "
                                       "faltaron: la próxima vez son puntos seguros."),
    ("Tres bien. Vas tomando ritmo.", "La trivia se renueva cada madrugada: con las respuestas de hoy ya tenés "
                                      "con qué sorprender mañana."),
    ("Cuatro bien. A una del aprobado.", "Casi, casi. Mañana, con diez preguntas nuevas, la das vuelta. Repasá "
                                         "las explicaciones: ahí está la diferencia."),
    ("¡Aprobado!", "Cinco de diez, la mitad justa y sin ayuda. Con un par de repasos mañana pasás a notable."),
    ("¡Muy bien! Seis de diez.", "Sabés más de lo que creías. Mañana hay otras diez para seguir subiendo."),
    ("¡Excelente! Siete de diez.", "Un gran puntaje: ya estás entre los que saben. Mañana, a defender el título."),
    ("¡Impresionante! Ocho de diez.", "Eso es dominar el tema. Las dos que faltaron son de las bravas: mañana "
                                      "vas por más."),
    ("¡Brillante! Nueve de diez.", "Casi perfecto. Te faltó una sola y seguro fue la más tramposa. Mañana tenés "
                                   "revancha por la última."),
    ("¡Diez de diez! Impecable.", "Nadie lo hizo mejor que vos hoy. Ojo que mañana el kit se renueva y hay que "
                                  "volver a demostrarlo."),
)

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


def parrafos_de(item: dict) -> list:
    """El artículo de la hoja: los `parrafos` del ítem y, si no los tiene
    todavía, su `texto` como único párrafo (nunca una hoja vacía)."""
    lista = [str(p).strip() for p in (item.get("parrafos") or []) if str(p).strip()]
    if lista:
        return lista
    texto = str(item.get("texto") or "").strip()
    return [texto] if texto else []


def url_de(item: dict) -> str:
    """El enlace a la fuente, solo si es https (lo que viaja al navegador se
    dibuja como enlace: nada que no sea una URL web)."""
    u = str(item.get("url") or "").strip()
    return u if u.startswith("https://") else ""


def item_del_dia(rubro: str, items: list, hoy: date, politicas: bool = False) -> dict | None:
    lista = candidatos(rubro, items, hoy, politicas)
    if not lista:
        return None
    i = lista[_semilla(hoy, rubro) % len(lista)]
    salida = {"rubro": rubro, "chip": i.get("chip") or CHIPS.get(rubro, ""), "linea": i.get("linea", ""),
              "titulo": i.get("titulo", ""), "texto": i.get("texto", ""), "fuente": i.get("fuente", ""),
              "parrafos": parrafos_de(i), "url": url_de(i)}
    if rubro == "consumidor" and i.get("norma"):
        salida["norma"] = i["norma"]
    return salida


# ---------------------------------------------------------------- trivia ----

def _mezcla(tanda: int, id_: str) -> str:
    return hashlib.sha256(f"trivia|{tanda}|{id_}".encode()).hexdigest()


def trivia_del_dia(items: list, hoy: date, cuantas: int = TRIVIA_PREGUNTAS) -> list:
    """Las preguntas de hoy, de fácil a difícil. El banco se baraja de forma
    determinista por TANDA (una tanda dura len(banco) // cuantas días) y cada
    día toma su tajada: en una tanda ninguna pregunta se repite, y todos ven
    el mismo kit el mismo día. Como depende solo de la fecha de Buenos Aires,
    se renueva a la medianoche con el primer pedido que llega, sin tarea
    programada ni fila en la base. Lo marcado `dudosa` no entra nunca."""
    banco = [i for i in items if not i.get("dudosa") and len(i.get("opciones") or []) == 3]
    if not banco:
        return []
    n = min(cuantas, len(banco))
    por_tanda = len(banco) // n
    tanda, posicion = divmod(hoy.toordinal(), por_tanda)
    orden = sorted(banco, key=lambda i: _mezcla(tanda, i["id"]))
    kit = orden[posicion * n:(posicion + 1) * n]
    kit.sort(key=lambda i: NIVELES.index(i["nivel"]) if i.get("nivel") in NIVELES else 1)
    return [{"id": i["id"], "titulo": i.get("titulo") or i.get("linea", ""), "opciones": list(i["opciones"]),
             "correcta": int(i.get("correcta", 0)), "explicacion": i.get("explicacion", ""),
             "fuente": i.get("fuente", ""), "url": url_de(i), "nivel": i.get("nivel", "media"),
             "tema": i.get("tema", "")} for i in kit]


def comentario_puntaje(aciertos: int, total: int = TRIVIA_PREGUNTAS) -> dict:
    """{"titulo", "texto"} para un puntaje: aliento por debajo de la mitad,
    elogio creciente desde la mitad. Un total distinto de diez se escala."""
    if total <= 0:
        return {"titulo": COMENTARIOS_PUNTAJE[0][0], "texto": COMENTARIOS_PUNTAJE[0][1]}
    n = max(0, min(total, int(aciertos)))
    indice = round(n * TRIVIA_PREGUNTAS / total)
    titulo, texto = COMENTARIOS_PUNTAJE[indice]
    return {"titulo": titulo, "texto": texto}


def item_trivia(items: list, hoy: date) -> dict | None:
    """El ítem de Entretenimiento: el kit de hoy entero, con el comentario de
    cada puntaje posible (así el navegador no inventa textos)."""
    preguntas = trivia_del_dia(items, hoy)
    if not preguntas:
        return None
    total = len(preguntas)
    return {"rubro": "juego", "chip": CHIPS["juego"],
            "linea": f"La trivia de hoy: {total} preguntas, ¿cuántas sacás?",
            "titulo": "La trivia de hoy",
            "texto": f"{total} preguntas, {TRIVIA_SEGUNDOS} segundos cada una, un punto por acierto. Mañana hay otras {total}.",
            "parrafos": [f"{total} preguntas, {TRIVIA_SEGUNDOS} segundos cada una, un punto por acierto. "
                         f"Mañana hay otras {total}."],
            "fuente": "", "url": "", "preguntas": preguntas, "segundos": TRIVIA_SEGUNDOS,
            "comentarios": [comentario_puntaje(n, total) for n in range(total + 1)]}


URL_BCRA = "https://www.bcra.gob.ar/PublicacionesEstadisticas/Cotizaciones_por_fecha_2.asp"


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
    parrafos = [texto,
                "Es la cotización de referencia que publica el Banco Central con las estadísticas cambiarias, "
                "al cierre de cada día hábil: no es el precio de ninguna casa de cambio ni del mercado informal.",
                "Sirve de referencia para contratos, tarifas y para seguir cómo se mueve el tipo de cambio oficial "
                "a lo largo del mes. La franja la actualiza una vez por día, con el cierre del día hábil anterior."]
    return {"rubro": "mercados", "chip": "Dólar", "linea": linea, "titulo": "Dólar oficial",
            "texto": texto, "parrafos": parrafos,
            "fuente": "Banco Central de la República Argentina, estadísticas cambiarias",
            "url": URL_BCRA, "tabla": [["Dólar oficial (BCRA)", pesos(cot["valor"])]]}


def armar_items(config: dict, hoy: date, dolar: dict | None = None, cargador=cargar) -> list:
    """La lista que rota, en el orden de la configuración del sindicato.
    Un rubro sin nada para hoy (o un servicio caído) no aparece."""
    items = []
    for rubro in config.get("rubros", []):
        if rubro == "mercados":
            it = item_dolar(dolar)
        elif rubro == "juego":
            it = item_trivia(cargador(rubro), hoy)
        else:
            it = item_del_dia(rubro, cargador(rubro), hoy, config.get("politicas", False))
        if it:
            items.append(it)
    return items


def dia_corto(d: date, hoy: date) -> str:
    return "mañana" if (d - hoy).days == 1 else DIAS_CORTOS[d.weekday()]
