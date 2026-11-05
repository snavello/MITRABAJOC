# -*- coding: utf-8 -*-
"""Precios de la API de Anthropic y el costo en dólares de cada llamada.

Módulo PURO: no importa db ni anthropic, así que se prueba solo y rápido.
Los precios viven en data/precios_ia.json.

Dos reglas que explican todo lo demás:

1. **El precio se congela en la fila, el costo se calcula.** `UsoIA` guarda
   los dólares por millón de tokens que regían cuando se hizo la llamada
   (`precio_entrada`/`precio_salida`), no el costo ya multiplicado: el
   precio es un HECHO del momento y el costo un derivado, igual que el
   criterio de guardar la fecha de afiliación y no la antigüedad. Si mañana
   Anthropic cambia la lista, el gasto de ayer sigue diciendo lo mismo.
2. **Un precio sin fecha no se puede auditar.** A diferencia de
   `render_planes.py`, que los lee de la web con un script, acá se copian a
   mano de anthropic.com/pricing -- no hay una página estable que se pueda
   leer sin inventar. Por eso el archivo guarda la fecha de lectura y la
   pantalla la muestra.

Caché de prompt: `costo()` cobra la lectura de caché a 0,1x y la escritura a
1,25x del precio de entrada (MULT_CACHE_*). Lo que NO contempla es Batch
(50%), que ninguno de los usos registrados en UsoIA usa. El Asistente sí
cachea su prompt de sistema pero todavía no registra acá.
"""
import json
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parent / "data" / "precios_ia.json"

# Qué modelo usa cada parte de la app. El `default` es el que está escrito
# como constante en el módulo (extractor.MODELO, rag.MODELO_RESPUESTA,
# asistente.MODELO) y es lo que corre si plataforma nunca eligió nada;
# test_precios_ia.py verifica que no se separen.
USOS = {
    "recibos": {
        "nombre": "Lectura de recibos y comprobantes",
        "detalle": "Lee la foto o el PDF del recibo de sueldo, el comprobante de "
                   "aportes de ARCA y los lotes de Aprendizaje. Es el único uso "
                   "con volumen real: una llamada por cada recibo que sube un "
                   "trabajador.",
        "default": "claude-sonnet-4-6",
    },
    "convenio": {
        "nombre": "Consultas sobre el convenio (bot del trabajador)",
        "detalle": "Responde la pregunta del afiliado con los ocho fragmentos "
                   "del convenio que se recuperaron. Usa el modelo más capaz a "
                   "propósito: la baranda de «no lo encontré» es el prompt y no "
                   "un umbral.",
        "default": "claude-opus-5",
    },
    "asistente": {
        "nombre": "Asistente del Panel Sindical",
        "detalle": "Traduce la pregunta del admin a los filtros del panel. "
                   "Cambiarlo obliga a repetir la prueba de aceptación del "
                   "Asistente: el prompt está medido contra este modelo.",
        "default": "claude-sonnet-5",
    },
    "asistente_tramites": {
        "nombre": "Asistente de trámites (Herramientas de Entornos)",
        "detalle": "Lee el relato de un trámite que cuenta un sindicato y propone "
                   "respuestas, campos y dudas; el circuito y el formulario los "
                   "arma el servidor. Lo usa el implementador, no el afiliado: "
                   "pocas llamadas, una o dos por trámite relevado.",
        "default": "claude-sonnet-5",
    },
}


def catalogo() -> dict:
    """El archivo de precios, o un catálogo vacío si no está (clon viejo).
    Nunca un precio inventado: sin archivo, la pantalla lo dice."""
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fuente": "", "leido": "", "modelos": []}


def modelos() -> list:
    return catalogo().get("modelos", [])


def modelo(modelo_id: str) -> dict | None:
    return next((m for m in modelos() if m["id"] == modelo_id), None)


# extractor.MOCK, repetido acá para no importar extractor (que levanta el
# cliente de Anthropic) desde un módulo puro. Hay un test que los compara.
MOCK = "mock"


def nombre(modelo_id: str) -> str:
    """"claude-sonnet-4-6" -> "Claude Sonnet 4.6". Si no está en el catálogo
    (un modelo viejo que quedó registrado en filas de hace meses), devuelve
    el id crudo en vez de esconderlo.

    El mock se nombra entero: una fila sin tokens y sin costo tiene que
    explicarse sola en la tabla. Es lo que pasa en Pruebas, que quedó con
    MOCK_EXTRACTOR=1 de los tests de carga (carga/README.md)."""
    if modelo_id == MOCK:
        return "mock — no hubo llamada a la API"
    m = modelo(modelo_id)
    return m["nombre"] if m else (modelo_id or "—")


def precios(modelo_id: str) -> tuple[float, float] | None:
    """(usd por millón de tokens de entrada, ídem de salida). None si el
    modelo no está en el catálogo -- lo que significa que no se puede saber
    cuánto costó, y eso se muestra como «—», nunca como cero."""
    m = modelo(modelo_id)
    if not m:
        return None
    return float(m["entrada"]), float(m["salida"])


# Multiplicadores de la API para la caché de prompt de 5 minutos, sobre el
# precio de entrada del modelo (no hay precios por modelo aparte): leer de la
# caché sale 0,1x y escribirla 1,25x. `usage.input_tokens` de la API NO
# incluye los tokens de caché: son tres cantidades disjuntas.
MULT_CACHE_LECTURA = 0.1
MULT_CACHE_ESCRITURA = 1.25


def costo(tokens_entrada: int, tokens_salida: int,
          usd_entrada: float, usd_salida: float,
          tokens_cache_lectura: int = 0, tokens_cache_escritura: int = 0) -> float:
    """Los dólares de UNA llamada, con los precios que se le pasen (los
    congelados en la fila, o los de hoy para estimar una vieja). La entrada
    normal, la leída de caché (0,1x) y la escrita en caché (1,25x) se cobran
    cada una a lo suyo."""
    e = usd_entrada or 0
    return ((tokens_entrada or 0) * e
            + (tokens_cache_lectura or 0) * e * MULT_CACHE_LECTURA
            + (tokens_cache_escritura or 0) * e * MULT_CACHE_ESCRITURA
            + (tokens_salida or 0) * (usd_salida or 0)) / 1_000_000


def costo_estimado(modelo_id: str, tokens_entrada: int, tokens_salida: int,
                   tokens_cache_lectura: int = 0, tokens_cache_escritura: int = 0) -> float | None:
    """El costo con los precios de HOY, para las filas registradas antes de
    que se guardara el precio. None si el modelo no está en el catálogo."""
    p = precios(modelo_id)
    return None if p is None else costo(tokens_entrada, tokens_salida, p[0], p[1],
                                         tokens_cache_lectura, tokens_cache_escritura)


def modelo_valido(modelo_id: str) -> bool:
    return any(m["id"] == modelo_id for m in modelos())


def default_de(uso: str) -> str:
    return USOS.get(uso, {}).get("default", "")


# ---------- formato (para no hacer cuentas en la plantilla) ----------
def _es(x: float, decimales: int) -> str:
    """Número con separadores castellanos: 1234.5 -> "1.234,50"."""
    return f"{x:,.{decimales}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def usd(x: float | None, decimales: int = 4) -> str:
    """Una llamada suelta cuesta centavos, así que el default son 4 decimales
    -- con 2 todas las filas dirían "US$ 0,02" y la comparación entre modelos,
    que es para lo que existe la columna, se perdería."""
    return "—" if x is None else f"US$ {_es(x, decimales)}"


def precio_txt(m: dict) -> str:
    """"US$ 3 / 15 por millón de tokens" -- entrada y salida, en ese orden."""
    def n(x):
        x = float(x)
        return _es(x, 0) if x == int(x) else _es(x, 2)
    return f"US$ {n(m['entrada'])} / {n(m['salida'])} por millón de tokens"


def catalogo_pantalla() -> dict:
    """El catálogo con los precios ya escritos, para no hacer formato en la
    plantilla. Si el archivo no está, `modelos` viene vacío y la pantalla lo
    dice en vez de mostrar un cero."""
    cat = catalogo()
    return {
        "fuente": cat.get("fuente", ""),
        "leido": cat.get("leido", ""),
        "modelos": [dict(m, precio_txt=precio_txt(m)) for m in cat.get("modelos", [])],
    }


def segundos(ms: int | None) -> str:
    return "—" if not ms else f"{_es(ms / 1000, 1)} s"
