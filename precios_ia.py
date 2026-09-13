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

Lo que estos precios NO contemplan: descuentos de cache (una lectura
cacheada sale ~0,1x) ni Batch (50%). El extractor no usa ninguno de los
dos, así que para lo que hoy se registra en UsoIA el número es el real; el
Asistente sí cachea su prompt de sistema, y el día que entre acá habría que
sumar los tokens de cache a la cuenta.
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
                   "un umbral (ver PLAN_RAG_CONVENIO.md).",
        "default": "claude-opus-5",
    },
    "asistente": {
        "nombre": "Asistente del Panel Sindical",
        "detalle": "Traduce la pregunta del admin a los filtros del panel. "
                   "Cambiarlo obliga a volver a correr el set de aceptación "
                   "(probar_asistente.py): el prompt está medido contra ESTE "
                   "modelo.",
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


def nombre(modelo_id: str) -> str:
    """"claude-sonnet-4-6" -> "Claude Sonnet 4.6". Si no está en el catálogo
    (un modelo viejo que quedó registrado en filas de hace meses), devuelve
    el id crudo en vez de esconderlo."""
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


def costo(tokens_entrada: int, tokens_salida: int,
          usd_entrada: float, usd_salida: float) -> float:
    """Los dólares de UNA llamada, con los precios que se le pasen (los
    congelados en la fila, o los de hoy para estimar una vieja)."""
    return ((tokens_entrada or 0) * (usd_entrada or 0)
            + (tokens_salida or 0) * (usd_salida or 0)) / 1_000_000


def costo_estimado(modelo_id: str, tokens_entrada: int, tokens_salida: int) -> float | None:
    """El costo con los precios de HOY, para las filas registradas antes de
    que se guardara el precio. None si el modelo no está en el catálogo."""
    p = precios(modelo_id)
    return None if p is None else costo(tokens_entrada, tokens_salida, p[0], p[1])


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
