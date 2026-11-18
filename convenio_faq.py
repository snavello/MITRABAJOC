# -*- coding: utf-8 -*-
"""Preguntas frecuentes del convenio (PLAN_CONVENIO_ESCALAS.md, D31, D35, D36).

Módulo PURO: no importa `db` ni toca la red. Carga y valida
`data/convenios/<convenio>-faq.json` según el contrato del plan:

  {"convenio", "leido", "temas": [{"clave","nombre","orden"}],
   "preguntas": [{"id","tema","orden","pregunta","respuesta","articulos",
                  "segun_ley","normas":[{"norma","articulo","url"}],"estado",
                  "en_corto","por_banco","fuentes_banco":[{"texto","url"}],
                  "nota_curador","inspirada_en"}]}

`en_corto` (la respuesta directa, renglones separados por salto de línea),
`por_banco` (acuerdos de La Bancaria con bancos puntuales) y `fuentes_banco`
son opcionales: si faltan quedan "" / []. Una pregunta es válida si tiene al
menos uno de `respuesta`, `segun_ley` o `por_banco`.

Lo mal formado NO se muestra: se descarta la pregunta y se reporta el motivo
en `descartadas` (id repetido, tema inexistente, artículo que no existe en el
convenio, campos que faltan). Las normas con un enlace que no es https se
guardan sin enlace.

`publico()` es lo que viaja a la pantalla (sin `nota_curador` ni
`inspirada_en`); `curado()` es lo del equipo (con ellas).
"""
import json
import re
import unicodedata
from urllib.parse import urlsplit
from functools import lru_cache
from pathlib import Path

import convenio_fichas

RAIZ = Path(__file__).resolve().parent
CARPETA = RAIZ / "data" / "convenios"
CONVENIO_POR_DEFECTO = convenio_fichas.CONVENIO_POR_DEFECTO
ESTADOS = ("sin_revisar", "revisada")
# Lo que guarda la base además de los dos que ven el afiliado y la IA: una
# retirada no se muestra nunca y puede estar incompleta (PLAN D41).
ESTADOS_CURADO = ESTADOS + ("retirada",)


def _texto(x) -> str:
    return x.strip() if isinstance(x, str) else ""


def _orden(x) -> float:
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else 999


def _articulo_ref(n, convenio: str):
    """{numero, titulo} del artículo `n`, o None si no existe en el convenio."""
    if isinstance(n, bool) or not isinstance(n, (int, str)):
        return None
    a = convenio_fichas.articulo(n, convenio)
    return {"numero": a["numero"], "titulo": a["titulo"]} if a else None


def validar_datos(datos, convenio: str = CONVENIO_POR_DEFECTO) -> dict:
    """Valida el contenido ya leído del JSON. Devuelve
    {"convenio","leido","temas":[...ordenados, solo con preguntas],
     "preguntas":{id: pregunta limpia},"descartadas":[{"id","motivo"}]}."""
    descartadas: list = []
    if not isinstance(datos, dict):
        return {"convenio": convenio, "leido": "", "temas": [], "preguntas": {},
                "descartadas": [{"id": "", "motivo": "el archivo no es un objeto"}]}
    temas: dict = {}
    for t in datos.get("temas") or []:
        if not isinstance(t, dict) or not _texto(t.get("clave")) or not _texto(t.get("nombre")):
            descartadas.append({"id": "", "motivo": f"tema mal formado: {t!r}"[:200]})
            continue
        clave = _texto(t["clave"])
        if clave in temas:
            descartadas.append({"id": "", "motivo": f"tema repetido: {clave}"})
            continue
        temas[clave] = {"clave": clave, "nombre": _texto(t["nombre"]), "orden": _orden(t.get("orden"))}
    preguntas: dict = {}
    for p in datos.get("preguntas") or []:
        pid = _texto(p.get("id")) if isinstance(p, dict) else ""
        if not pid:
            descartadas.append({"id": "", "motivo": "pregunta sin id o mal formada"})
            continue
        if pid in preguntas:
            descartadas.append({"id": pid, "motivo": "id repetido"})
            continue
        if _texto(p.get("tema")) not in temas:
            descartadas.append({"id": pid, "motivo": f"tema inexistente: {p.get('tema')!r}"[:200]})
            continue
        if not _texto(p.get("pregunta")):
            descartadas.append({"id": pid, "motivo": "sin texto de pregunta"})
            continue
        crudos = p.get("articulos") if p.get("articulos") is not None else []
        if not isinstance(crudos, list):
            descartadas.append({"id": pid, "motivo": "articulos no es una lista"})
            continue
        arts, malo = [], None
        for n in crudos:
            ref = _articulo_ref(n, convenio)
            if ref is None:
                malo = n
                break
            if ref not in arts:
                arts.append(ref)
        if malo is not None:
            descartadas.append({"id": pid, "motivo": f"el artículo {malo!r} no existe en el convenio"})
            continue
        respuesta, segun_ley = _texto(p.get("respuesta")), _texto(p.get("segun_ley"))
        if respuesta and not arts:
            descartadas.append({"id": pid, "motivo": "responde con el convenio pero no cita ningún artículo"})
            continue
        por_banco = _texto(p.get("por_banco"))
        if not respuesta and not segun_ley and not por_banco:
            descartadas.append({"id": pid, "motivo": "no tiene respuesta, «Según la ley» ni «En tu banco»"})
            continue
        normas = []
        for n in p.get("normas") or []:
            if not isinstance(n, dict) or not _texto(n.get("norma")):
                continue
            url = _texto(n.get("url"))
            normas.append({"norma": _texto(n["norma"]), "articulo": _texto(n.get("articulo")),
                           "url": url if url.lower().startswith("https://") else ""})
        if segun_ley and not normas:
            descartadas.append({"id": pid, "motivo": "«Según la ley» sin norma citada"})
            continue
        fuentes_banco = []
        crudas = p.get("fuentes_banco")
        for f in crudas if isinstance(crudas, list) else []:
            if not isinstance(f, dict) or not _texto(f.get("texto")):
                continue
            url = _texto(f.get("url"))
            fuentes_banco.append({"texto": _texto(f["texto"]),
                                  "url": url if url.lower().startswith("https://") else ""})
        estado = _texto(p.get("estado"))
        inspirada = p.get("inspirada_en")
        preguntas[pid] = {
            "id": pid, "tema": _texto(p["tema"]), "orden": _orden(p.get("orden")),
            "pregunta": _texto(p["pregunta"]), "respuesta": respuesta, "articulos": arts,
            "segun_ley": segun_ley, "normas": normas,
            "en_corto": _texto(p.get("en_corto")), "por_banco": por_banco, "fuentes_banco": fuentes_banco,
            "estado": estado if estado in ESTADOS else "sin_revisar",
            "nota_curador": _texto(p.get("nota_curador")),
            "inspirada_en": [x for x in inspirada if isinstance(x, str)] if isinstance(inspirada, list) else []}
    salida_temas = []
    for t in sorted(temas.values(), key=lambda t: (t["orden"], t["nombre"])):
        propias = sorted((q for q in preguntas.values() if q["tema"] == t["clave"]),
                         key=lambda q: (q["orden"], q["id"]))
        if propias:
            salida_temas.append({**t, "preguntas": propias})
    return {"convenio": convenio, "leido": _texto(datos.get("leido")), "temas": salida_temas,
            "preguntas": preguntas, "descartadas": descartadas}


@lru_cache(maxsize=8)
def _leer(convenio: str) -> dict:
    ruta = CARPETA / f"{convenio}-faq.json"
    if ruta.resolve().parent != CARPETA.resolve() or not ruta.is_file():
        return validar_datos(None, convenio)
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError:
        return {**validar_datos(None, convenio),
                "descartadas": [{"id": "", "motivo": "el archivo no es JSON válido"}]}
    return validar_datos(crudo, convenio)


# Lo que la app registró desde la base (D41), por convenio. Mientras nadie registre
# nada, manda el archivo: este módulo sigue siendo puro, no importa `db`.
_REGISTRADO: dict = {}


def registrar(convenio: str, datos) -> dict:
    """Deja `datos` (la forma del JSON: {leido, temas, preguntas}) como las preguntas
    vigentes del convenio. `None` vuelve a leer el archivo. Devuelve lo validado."""
    if datos is None:
        _REGISTRADO.pop(convenio, None)
        return _leer(convenio)
    r = validar_datos(datos, convenio)
    _REGISTRADO[convenio] = r
    return r


def cargar(convenio: str = CONVENIO_POR_DEFECTO) -> dict:
    """Lo validado: lo registrado desde la base, o el archivo. No lo modifiques."""
    return _REGISTRADO.get(convenio) or _leer(convenio)


@lru_cache(maxsize=8)
def _semilla(convenio: str) -> tuple:
    """(temas, activas, retiradas) crudos de los dos archivos de semilla."""
    def leer(nombre):
        ruta = CARPETA / nombre
        if ruta.resolve().parent != CARPETA.resolve() or not ruta.is_file():
            return {}
        try:
            d = json.loads(ruta.read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return d if isinstance(d, dict) else {}
    act, ret = leer(f"{convenio}-faq.json"), leer(f"{convenio}-faq-retiradas.json")

    def lista(d):
        return tuple(p for p in (d.get("preguntas") or []) if isinstance(p, dict))
    return tuple(act.get("temas") or []), lista(act), lista(ret)


def semilla(convenio: str = CONVENIO_POR_DEFECTO) -> tuple:
    """(activas, retiradas): las preguntas de los archivos, listas para sembrar la base."""
    _, a, r = _semilla(convenio)
    return [dict(p) for p in a], [dict(p) for p in r]


def temas_catalogo(convenio: str = CONVENIO_POR_DEFECTO) -> list:
    """Los temas del catálogo (aunque no tengan preguntas), por orden."""
    out = {}
    for t in _semilla(convenio)[0]:
        if isinstance(t, dict) and _texto(t.get("clave")) and _texto(t.get("nombre")):
            out.setdefault(_texto(t["clave"]), {"clave": _texto(t["clave"]), "nombre": _texto(t["nombre"]),
                                                 "orden": _orden(t.get("orden"))})
    return sorted(out.values(), key=lambda t: (t["orden"], t["nombre"]))


# ---------------------------------------------------------------- validar UNA pregunta (D41)
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVADAS = ("articulos", "reordenar", "estado", "nueva")
MAX = {"id": 60, "pregunta": 300, "en_corto": 1500, "respuesta": 4000, "segun_ley": 4000, "por_banco": 4000,
       "nota_curador": 2000, "motivo_retiro": 300, "detalle_retiro": 2000}
MAX_ARTICULOS, MAX_NORMAS, MAX_FUENTES, MAX_INSPIRADA = 30, 12, 12, 12
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\ud800-\udfff]")


class _Raros:
    """Caracteres de control o invisibles: los de la lista de siempre y, además, cualquier
    carácter de formato (Cf: guion blando, aislantes bidireccionales…), de uso privado
    (Co), suelto (Cs) o sin asignar (Cn). Un guion blando pegado desde Word no se ve y
    después la IA rechaza toda respuesta que lo repita (QA independiente, D41)."""

    def search(self, texto):
        m = _CONTROL_RE.search(texto)
        if m:
            return m
        for i, c in enumerate(texto):
            if unicodedata.category(c) in ("Cf", "Co", "Cs", "Cn", "Zl", "Zp"):
                return (i, c)
        return None


CONTROL = _Raros()
# Importes en pesos o dólares: la vista de escalas es la que los muestra, con su etiqueta.
_IMPORTE = re.compile(r"(\$|\bARS\b|\bUSD\b|U\$S|\d\s*pesos\b|\bpesos\s*\d|\d{1,3}(?:\.\d{3})+,\d{2}\b)", re.I)


def hay_importe(texto: str) -> bool:
    return bool(_IMPORTE.search(texto or ""))


def _raro_dicho(texto: str) -> str:
    """«un carácter invisible (U+00AD) después de «…»»: para que quien cura lo encuentre."""
    m = CONTROL.search(texto)
    i = m.start() if hasattr(m, "start") else m[0]
    c = texto[i]
    antes = texto[max(0, i - 25):i].strip()
    return (f"un carácter invisible o de control (U+{ord(c):04X})"
            + (f" después de «{antes}»" if antes else " al principio") + ": borralo y volvé a escribir esa parte")


def _t(dato, campo, errores, obligatorio=False, visible=False):
    """El texto del campo, o '' si falta. Un valor que no es texto es un error."""
    v = dato.get(campo)
    if v is None:
        v = ""
    if not isinstance(v, str):
        errores.append({"campo": campo, "mensaje": "tiene que ser un texto"})
        return ""
    v = v.strip()
    if CONTROL.search(v):
        errores.append({"campo": campo, "mensaje": "tiene " + _raro_dicho(v)})
        return ""
    if len(v) > MAX.get(campo, 4000):
        errores.append({"campo": campo, "mensaje": f"es demasiado largo (máximo {MAX.get(campo, 4000)} caracteres)"})
        return ""
    if obligatorio and not v:
        errores.append({"campo": campo, "mensaje": "es obligatorio"})
    if visible and v and hay_importe(v):
        errores.append({"campo": campo, "mensaje": "no puede traer importes en pesos: eso lo muestra la escala"})
    return v


_HOST = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def host_publico(url: str) -> bool:
    """True si la URL https apunta a un sitio con nombre público: sin usuario ni clave
    (`https://bien.gob.ar@malo.com` se lee como el primero y abre el segundo), sin
    barra invertida, sin IP ni `localhost`, sin ángulos ni comillas. Solo ASCII
    (un dominio con tildes va en su forma `xn--`). No toca la red."""
    if not isinstance(url, str) or "\\" in url or any(c in url for c in "<>\"'`") \
            or not url.lower().startswith("https://"):
        return False
    try:
        p = urlsplit(url)
        host, _ = p.hostname, p.port                    # .port levanta si el puerto es basura
    except ValueError:
        return False
    if not host or p.username is not None or p.password is not None or "@" in p.netloc:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    return bool(_HOST.match(host))


def _url(valor, campo, errores):
    if valor is None or valor == "":
        return ""
    if not isinstance(valor, str):
        errores.append({"campo": campo, "mensaje": "el enlace tiene que ser un texto"})
        return ""
    u = valor.strip()
    if not u:
        return ""
    if not u.lower().startswith("https://") or len(u) > 500 or CONTROL.search(u) or re.search(r"\s", u):
        errores.append({"campo": campo, "mensaje": "el enlace tiene que ser https:// y sin espacios (máximo 500 caracteres)"})
        return ""
    if not host_publico(u):
        errores.append({"campo": campo, "mensaje": "el enlace tiene que apuntar a un sitio público (https://sitio.gob.ar/…): "
                                                   "sin usuario ni clave antes del sitio, sin direcciones numéricas ni «localhost»"})
        return ""
    return u


def validar_pregunta(dato, convenio: str = CONVENIO_POR_DEFECTO, parcial: bool = False):
    """Valida el contenido de UNA pregunta con las mismas reglas del archivo.
    Devuelve (limpio, errores): `limpio` en la forma del JSON (artículos como
    números) y `errores` una lista de {"campo","mensaje"} (vacía si está bien).
    `parcial=True` es para una retirada: solo exige id, tema y pregunta, y no la
    consistencia entre respuesta, artículos y ley. Nunca levanta."""
    errores: list = []
    if not isinstance(dato, dict):
        return {}, [{"campo": "", "mensaje": "el cuerpo tiene que ser un objeto"}]
    pid = _t(dato, "id", errores, obligatorio=True)
    if pid and (not SLUG.match(pid) or pid in RESERVADAS):
        errores.append({"campo": "id", "mensaje": f"«{pid[:40]}» está reservado" if pid in RESERVADAS else
                        "tiene que ser un identificador en minúsculas, números y guiones (ej. vac-dias)"})
    tema = _t(dato, "tema", errores, obligatorio=True)
    if tema and tema not in {t["clave"] for t in temas_catalogo(convenio)}:
        errores.append({"campo": "tema", "mensaje": f"el tema «{tema[:60]}» no existe"})
    orden = dato.get("orden")
    if orden is None:
        orden = 999
    elif isinstance(orden, bool) or not isinstance(orden, (int, float)) or orden != orden or abs(orden) > 100000:
        errores.append({"campo": "orden", "mensaje": "tiene que ser un número"})
        orden = 999
    pregunta = _t(dato, "pregunta", errores, obligatorio=True, visible=True)
    en_corto = _t(dato, "en_corto", errores, obligatorio=not parcial, visible=True)
    respuesta = _t(dato, "respuesta", errores, visible=True)
    segun_ley = _t(dato, "segun_ley", errores, visible=True)
    por_banco = _t(dato, "por_banco", errores, visible=True)
    nota = _t(dato, "nota_curador", errores)
    arts: list = []
    crudos = dato.get("articulos")
    if crudos is None:
        crudos = []
    if not isinstance(crudos, list) or len(crudos) > MAX_ARTICULOS:
        errores.append({"campo": "articulos", "mensaje": f"tiene que ser una lista de hasta {MAX_ARTICULOS} números de artículo"})
    else:
        for n in crudos:
            ref = _articulo_ref(n, convenio)
            if ref is None:
                errores.append({"campo": "articulos", "mensaje": f"el artículo {str(n)[:30]!r} no existe en el convenio"})
            elif ref["numero"] not in arts:
                arts.append(ref["numero"])
    normas: list = []
    crudas = dato.get("normas")
    if crudas is None:
        crudas = []
    if not isinstance(crudas, list) or len(crudas) > MAX_NORMAS:
        errores.append({"campo": "normas", "mensaje": f"tiene que ser una lista de hasta {MAX_NORMAS} normas"})
    else:
        for i, n in enumerate(crudas, 1):
            if not isinstance(n, dict) or not isinstance(n.get("norma"), str) or not n["norma"].strip():
                errores.append({"campo": "normas", "mensaje": f"la norma {i} necesita el nombre de la norma"})
                continue
            nom, art = n["norma"].strip(), n.get("articulo")
            art = art.strip() if isinstance(art, str) else ("" if art is None else None)
            if art is None or len(nom) > 200 or len(art) > 60 or CONTROL.search(nom + art):
                errores.append({"campo": "normas", "mensaje": f"la norma {i} tiene un dato inválido (texto, máximo 200 y 60 caracteres)"})
                continue
            normas.append({"norma": nom, "articulo": art, "url": _url(n.get("url"), "normas", errores)})
    fuentes: list = []
    crudas = dato.get("fuentes_banco")
    if crudas is None:
        crudas = []
    if not isinstance(crudas, list) or len(crudas) > MAX_FUENTES:
        errores.append({"campo": "fuentes_banco", "mensaje": f"tiene que ser una lista de hasta {MAX_FUENTES} fuentes"})
    else:
        for i, f in enumerate(crudas, 1):
            if not isinstance(f, dict) or not isinstance(f.get("texto"), str) or not f["texto"].strip() \
                    or len(f["texto"].strip()) > 300 or CONTROL.search(f["texto"]):
                errores.append({"campo": "fuentes_banco", "mensaje": f"la fuente {i} necesita un texto (máximo 300 caracteres)"})
                continue
            fuentes.append({"texto": f["texto"].strip(), "url": _url(f.get("url"), "fuentes_banco", errores)})
    insp: list = []
    crudas = dato.get("inspirada_en")
    if crudas is None:
        crudas = []
    if not isinstance(crudas, list) or len(crudas) > MAX_INSPIRADA \
            or any(not isinstance(x, str) or len(x) > 300 or CONTROL.search(x) for x in crudas):
        errores.append({"campo": "inspirada_en", "mensaje": f"tiene que ser una lista de hasta {MAX_INSPIRADA} textos cortos"})
    else:
        insp = [x.strip() for x in crudas if x.strip()]
    if not parcial:
        if respuesta and not arts:
            errores.append({"campo": "articulos", "mensaje": "si responde con el convenio tiene que citar al menos un artículo"})
        if arts and not respuesta:
            errores.append({"campo": "respuesta", "mensaje": "hay artículos citados pero la respuesta del convenio está vacía"})
        if segun_ley and not normas:
            errores.append({"campo": "normas", "mensaje": "«Según la ley» necesita al menos una norma citada"})
        if not respuesta and not segun_ley:
            errores.append({"campo": "respuesta", "mensaje": "falta la respuesta del convenio o «Según la ley» (al menos una)"})
    limpio = {"id": pid, "tema": tema, "orden": orden, "pregunta": pregunta, "en_corto": en_corto,
              "respuesta": respuesta, "articulos": arts, "segun_ley": segun_ley, "normas": normas,
              "por_banco": por_banco, "fuentes_banco": fuentes, "nota_curador": nota, "inspirada_en": insp}
    return limpio, errores


# ---------------------------------------------------------------- cuánto cabe en el prompt de la IA
# Las preguntas vigentes viajan enteras en el prompt de `consulta_convenio_ia` (junto al texto del
# convenio, ~60.000 caracteres). Con los topes de cada campo una sola pregunta puede pesar 14.000
# caracteres y 200 de ellas pasan el contexto del modelo: TODA consulta fallaría (QA D41). El tope
# es el conjunto: hoy las 119 vigentes pesan ~120.000 caracteres (~35.000 tokens).
TOPE_PROMPT_CARACTERES = 200_000
TOPE_PREGUNTAS = 400
_CAMPOS_PROMPT = ("pregunta", "en_corto", "respuesta", "segun_ley", "por_banco")


def peso_prompt(q) -> int:
    """Caracteres que una pregunta suma al prompt de la IA (con lo que le pone alrededor)."""
    if not isinstance(q, dict):
        return 0
    return 120 + sum(len(q.get(k) or "") for k in _CAMPOS_PROMPT if isinstance(q.get(k), str))


def existe(pid, convenio: str = CONVENIO_POR_DEFECTO) -> bool:
    return isinstance(pid, str) and pid in cargar(convenio)["preguntas"]


def pregunta(pid, convenio: str = CONVENIO_POR_DEFECTO) -> dict | None:
    return cargar(convenio)["preguntas"].get(pid) if isinstance(pid, str) else None


def _vista(q: dict, con_curador: bool) -> dict:
    v = {k: q[k] for k in ("id", "pregunta", "en_corto", "respuesta", "segun_ley", "por_banco", "estado")}
    v["fuentes_banco"] = [dict(f) for f in q["fuentes_banco"]]
    v["articulos"] = [dict(a) for a in q["articulos"]]
    v["normas"] = [dict(n) for n in q["normas"]]
    if con_curador:
        v["nota_curador"] = q["nota_curador"]
        v["inspirada_en"] = list(q["inspirada_en"])
    return v


def _temas(convenio: str, con_curador: bool) -> list:
    return [{"clave": t["clave"], "nombre": t["nombre"],
             "preguntas": [_vista(q, con_curador) for q in t["preguntas"]]}
            for t in cargar(convenio)["temas"]]


def publico(convenio: str = CONVENIO_POR_DEFECTO) -> dict:
    """Lo que ve el afiliado: temas con sus preguntas, sin notas del curador."""
    return {"leido": cargar(convenio)["leido"], "temas": _temas(convenio, False)}


def curado(convenio: str = CONVENIO_POR_DEFECTO) -> dict:
    """Lo que ve el equipo: lo mismo, con `nota_curador` e `inspirada_en`, y lo
    descartado por estar mal formado."""
    c = cargar(convenio)
    return {"leido": c["leido"], "temas": _temas(convenio, True), "descartadas": list(c["descartadas"])}
