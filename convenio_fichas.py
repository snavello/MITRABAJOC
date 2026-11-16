"""Convenio en fichas (PLAN_CONVENIO_ESCALAS.md, D11): lectura pura del
convenio versionado en `data/convenios/<convenio>.json`.

Módulo PURO: no importa `db` ni toca la red. Solo lee el archivo del repo y
resuelve cosas sobre datos que recibe por parámetro (la grilla, por ejemplo).

- `cargar(convenio)`: el convenio entero (se lee una vez por proceso).
- `articulo(n)`: la ficha de un artículo (número) o de una disposición
  transitoria (número romano, "I" a "VIII").
- `situaciones()` / `indice()`: las entradas «por situación» y el índice
  completo, agrupado.
- `buscar(texto)`: espejo en servidor del buscador de la pantalla, sobre
  títulos y texto literal, sin acentos ni mayúsculas.
- `importe_vigente(articulo, grilla)`: resuelve `importe_grilla` contra el
  contenido de una grilla (lo recibe por parámetro, no la busca). Nunca
  inventa un importe: si algo no resuelve, devuelve None.

Los resúmenes nacen `sin_revisar`; la pantalla lo dice.
"""
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CARPETA = RAIZ / "data" / "convenios"
CONVENIO_POR_DEFECTO = "cct-18-75"

_ROTULOS = {
    "funcion_cajero": "Función de cajero",
    "falla_caja": "Falla de caja",
    "falla_caja_moneda_extranjera": "Falla de caja en moneda extranjera",
    "guarderia": "Guardería",
}


@lru_cache(maxsize=8)
def _leer(convenio: str) -> dict:
    ruta = CARPETA / f"{convenio}.json"
    # El nombre sale de un parámetro: no se deja salir de la carpeta.
    if ruta.resolve().parent != CARPETA.resolve() or not ruta.is_file():
        raise FileNotFoundError(f"No hay un convenio '{convenio}'")
    return json.loads(ruta.read_text(encoding="utf-8"))


def cargar(convenio: str = CONVENIO_POR_DEFECTO) -> dict:
    """El convenio completo. No lo modifiques: se comparte entre llamadas."""
    return _leer(convenio)


def _todas(conv: dict):
    yield from conv["articulos"]
    yield from conv.get("transitorias", [])


def articulo(n, convenio: str = CONVENIO_POR_DEFECTO) -> dict | None:
    """La ficha del artículo `n` (int o "12") o de la disposición transitoria
    `n` ("I" a "VIII"). None si no existe."""
    conv = cargar(convenio)
    clave = str(n).strip().upper()
    for a in _todas(conv):
        if str(a["numero"]).upper() == clave:
            return a
    return None


def situaciones(convenio: str = CONVENIO_POR_DEFECTO) -> list[dict]:
    """Las entradas por situación, cada una con sus artículos ya resueltos."""
    conv = cargar(convenio)
    salida = []
    for s in conv["situaciones"]:
        fichas = [articulo(n, convenio) for n in s["articulos"]]
        salida.append({**s, "fichas": [f for f in fichas if f]})
    return salida


def indice(convenio: str = CONVENIO_POR_DEFECTO) -> list[dict]:
    """El índice completo, por grupos: cada renglón es número y título."""
    conv = cargar(convenio)
    salida = []
    for g in conv["grupos"]:
        renglones = []
        for n in g["articulos"]:
            a = articulo(n, convenio)
            if a:
                renglones.append({"numero": a["numero"], "titulo": a["titulo"]})
        salida.append({"id": g["id"], "titulo": g["titulo"], "articulos": renglones})
    return salida


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, para comparar."""
    sin = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in sin if unicodedata.category(c) != "Mn").lower()


def buscar(texto: str, convenio: str = CONVENIO_POR_DEFECTO) -> list[dict]:
    """Artículos (y transitorias) cuyo título o texto literal contienen todas
    las palabras de `texto`, sin acentos ni mayúsculas. Los que coinciden en
    el título van primero."""
    palabras = normalizar(texto).split()
    if not palabras:
        return []
    en_titulo, en_texto = [], []
    for a in _todas(cargar(convenio)):
        titulo = normalizar(a["titulo"])
        cuerpo = normalizar(a["texto"])
        if all(p in titulo or p in cuerpo for p in palabras):
            (en_titulo if all(p in titulo for p in palabras) else en_texto).append(a)
    return en_titulo + en_texto


def _numero(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _rotulo(clave: str) -> str:
    return _ROTULOS.get(clave) or clave.replace("_", " ").capitalize()


def _resolver(clave: str, grilla: dict) -> list[dict] | None:
    nodo = grilla
    for parte in clave.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            return None
        nodo = nodo[parte]
    if _numero(nodo):
        return [{"rotulo": _rotulo(clave.rsplit(".", 1)[-1]), "importe": nodo}]
    if isinstance(nodo, dict):
        if "categorias" in nodo:
            nodo = nodo["categorias"]
        else:
            filas = [{"rotulo": str(k), "importe": v} for k, v in nodo.items()]
            return filas if filas and all(_numero(f["importe"]) for f in filas) else None
    if isinstance(nodo, list):
        filas = [{"rotulo": c["nombre"], "importe": c["basico"]} for c in nodo
                 if isinstance(c, dict) and "nombre" in c and _numero(c.get("basico"))]
        return filas if filas and len(filas) == len(nodo) else None
    return None


def importe_vigente(articulo_ficha: dict | None, grilla: dict | None) -> list[dict] | None:
    """Los renglones (rótulo, importe) que la grilla dice para el artículo, o
    None si el artículo no tiene importe de grilla o la grilla no lo trae.

    `grilla` es el contenido de un `data/grillas_bancarias/AAAA-MM.json` (o lo
    que la base entregue con esa misma forma). Si CUALQUIERA de las claves del
    artículo no resuelve, no se devuelve nada: un importe a medias no se
    publica.
    """
    if not articulo_ficha or not grilla:
        return None
    claves = articulo_ficha.get("importe_grilla")
    if not claves:
        return None
    if isinstance(claves, str):
        claves = [claves]
    renglones: list[dict] = []
    for c in claves:
        filas = _resolver(c, grilla)
        if filas is None:
            return None
        renglones.extend(filas)
    return renglones or None
