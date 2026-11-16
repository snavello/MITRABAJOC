# -*- coding: utf-8 -*-
"""La fuente de las grillas salariales del CCT 18/75: las notas de
labancaria.org (PLAN_CONVENIO_ESCALAS.md, D9.1).

Dos tipos de nota, las dos por la interfaz de WordPress del sitio:

- «GRILLAS ACTUALIZACIÓN SALARIAL dd-mm-aa»: trae el PDF escaneado de las
  grillas, enlazado dentro de un `<iframe src="...?url=https://.../x.pdf">`.
  A veces trae también otro PDF (el texto del acuerdo): se elige el que dice
  «grilla» en el nombre.
- «ACTUALIZACIÓN SALARIAL <MES> AAAA: x,x%»: el comunicado, con el salario
  inicial, el ROE y el porcentaje en el texto. Es la ANCLA que controla la
  lectura del PDF (escalas_controles.C3). Una grilla va con el comunicado
  publicado el mismo día o antes (el de la nota del 20-10-26 es septiembre,
  el del 11-09-26 es agosto): el período es el MES del comunicado.

Reglas de este módulo:
- **El parseo es puro** (funciones que reciben texto): se prueba con las
  respuestas reales guardadas en `fixtures/escalas/`.
- **Nunca un dato a medias**: si el formato cambió y no se puede leer todo
  con certeza, la función devuelve `None` con el motivo, no un valor parcial.
- **La red nunca levanta hacia el hilo**: `listar_novedades` atrapa todo y
  devuelve `{"ok": False, "motivo": ...}`. Solo `urllib`, sin librerías, con
  un User-Agent genérico (el sitio está detrás de Cloudflare).
- Módulo sin `db`: no sabe de la base.
"""
import html as _html
import json
import re
import urllib.parse
import urllib.request
from datetime import date

BASE = "https://labancaria.org"
API_POSTS = BASE + "/wp-json/wp/v2/posts"
USER_AGENT = "colm3na-escalas/1.0"
TIMEOUT_SEGUNDOS = 20
TOPE_PDF_BYTES = 30 * 1024 * 1024
TOPE_JSON_BYTES = 4 * 1024 * 1024

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}

BUSQUEDAS = ("grillas", "actualización salarial")


# ---------------------------------------------------------------- texto
def _quitar_acentos(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def limpiar_html(contenido: str) -> str:
    """El texto visible de un fragmento de HTML: sin etiquetas, con las
    entidades resueltas, los espacios duros como espacios y todo en una línea.
    El comunicado de septiembre viene partido en un `<span>` por dígito, así
    que las etiquetas se sacan SIN agregar un espacio donde estaban."""
    t = re.sub(r"(?is)<(script|style|iframe).*?</\1>", " ", contenido or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t).replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def a_numero(texto: str) -> float | None:
    """'2.552.560,34' -> 2552560.34. None si no tiene exactamente ese formato
    (puntos de miles y dos decimales con coma): un importe a medias no vale."""
    t = (texto or "").strip()
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}", t):
        return None
    return float(t.replace(".", "").replace(",", "."))


_IMPORTE = r"\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})"


# ---------------------------------------------------------------- títulos
def parsear_titulo_grillas(titulo: str) -> dict | None:
    """«GRILLAS ACTUALIZACIÓN SALARIAL 20-10-26» -> {"fecha": "2026-10-20"}."""
    t = _quitar_acentos(_html.unescape(titulo or "")).upper()
    m = re.match(r"^\s*GRILLAS\s+ACTUALIZACION\s+SALARIAL\s+(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})\s*$", t)
    if not m:
        return None
    d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    a = a + 2000 if a < 100 else a
    try:
        return {"fecha": date(a, mes, d).isoformat()}
    except ValueError:
        return None


def parsear_titulo_comunicado(titulo: str) -> dict | None:
    """«ACTUALIZACIÓN SALARIAL  OCTUBRE 2026: 2,2%» -> {"periodo": "2026-10",
    "porcentaje": 2.2}. Una nota de grillas no es un comunicado."""
    t = _quitar_acentos(_html.unescape(titulo or "")).lower()
    t = re.sub(r"\s+", " ", t).strip()
    m = re.match(r"^actualizacion salarial ([a-z]+) (\d{4})\s*:\s*(\d+(?:,\d+)?)\s*%$", t)
    if not m or m.group(1) not in MESES:
        return None
    return {"periodo": f"{int(m.group(2)):04d}-{MESES[m.group(1)]:02d}",
            "porcentaje": float(m.group(3).replace(",", "."))}


# ---------------------------------------------------------------- contenido
def pdfs_de_contenido(contenido: str) -> list:
    """Las URL de PDF que enlaza el contenido de una nota, sin repetir y en el
    orden en que aparecen: las del `?url=` de un visor embebido y los `href`."""
    t = _html.unescape(contenido or "")
    hallados = []
    # El visor embebido del sitio: <iframe src="https://labancaria.org/?url=<PDF>&title=...">
    for m in re.finditer(r"""[?&]url=(https?://[^"'&\s<>]+?\.pdf)""", t, flags=re.I):
        hallados.append((m.start(), m.group(1)))
    # Un enlace directo al PDF (sin el visor: la URL del visor lleva un «?»).
    for m in re.finditer(r"""(?:href|src)=["'](https?://[^"'?&\s<>]+?\.pdf)["']""", t, flags=re.I):
        hallados.append((m.start(), m.group(1)))
    urls = []
    for _, u in sorted(hallados):
        if u not in urls:
            urls.append(u)
    return urls


def elegir_pdf_grillas(urls: list) -> tuple:
    """(url, motivo). Con una sola URL es esa; con varias, la única cuyo nombre
    dice «grilla». Ante la duda no elige: devuelve (None, motivo)."""
    if not urls:
        return None, "la nota no enlaza ningún PDF"
    nombre = lambda u: _quitar_acentos(urllib.parse.unquote(u.rsplit("/", 1)[-1])).lower()
    con_nombre = [u for u in urls if "grilla" in nombre(u)]
    if len(con_nombre) == 1:
        return con_nombre[0], ""
    if len(con_nombre) > 1:
        return None, "más de un PDF dice «grilla» en el nombre"
    if len(urls) == 1:
        return urls[0], ""
    return None, f"la nota enlaza {len(urls)} PDF y ninguno dice «grilla»"


def parsear_comunicado(contenido: str) -> tuple:
    """(datos, motivo). `datos` = {"inicial", "roe", "total", "dia_bancario_minimo"
    (o None si el texto no lo trae), "mes_texto"}. El inicial y el ROE salen de
    «Salario Inicial + Participación Ganancias (ROE): $ A + $ B = $ C» y se
    aceptan solo si A + B = C al centavo: si un dígito se perdió al partir el
    HTML, la cuenta no cierra y no se devuelve nada. Sin datos: (None, motivo)."""
    t = limpiar_html(contenido)
    m = re.search(r"(?i)ROE\)?\s*:?\s*" + _IMPORTE + r"\s*\+\s*" + _IMPORTE + r"\s*=\s*" + _IMPORTE, t)
    if not m:
        return None, "el comunicado no trae «Salario Inicial + ROE = total» con el formato esperado"
    a, b, c = (a_numero(x) for x in m.groups())
    if None in (a, b, c):
        return None, "los importes del comunicado no tienen el formato esperado"
    if abs(round(a + b, 2) - c) > 0.011:
        return None, f"el comunicado no cierra: {a} + {b} no es {c}"
    datos = {"inicial": a, "roe": b, "total": c, "dia_bancario_minimo": None, "mes_texto": None}
    d = re.search(r"(?i)Monto\s+m[ií]nimo\s*" + _IMPORTE, t)
    if d:
        datos["dia_bancario_minimo"] = a_numero(d.group(1))
    mes = re.search(r"(?i)para el mes de\s+([A-Za-záéíóúñ]+)\s+de\s+(\d{4})", t)
    if mes and _quitar_acentos(mes.group(1)).lower() in MESES:
        datos["mes_texto"] = f"{int(mes.group(2)):04d}-{MESES[_quitar_acentos(mes.group(1)).lower()]:02d}"
    return datos, ""


# ---------------------------------------------------------------- notas
def _fecha_post(p: dict) -> str:
    return str(p.get("date") or "")[:10]


def _titulo(p: dict) -> str:
    t = p.get("title")
    return (t.get("rendered") if isinstance(t, dict) else t) or ""


def _contenido(p: dict) -> str:
    c = p.get("content")
    return (c.get("rendered") if isinstance(c, dict) else c) or ""


def clasificar_posts(posts: list) -> dict:
    """De la lista de notas que devolvió el sitio, las que son de grillas y las
    que son comunicados, ya parseadas. Lo demás (otras notas del sitio) se
    ignora. Cada elemento lleva `motivo` si no se pudo leer todo."""
    grillas, comunicados, vistos = [], [], set()
    for p in posts or []:
        if not isinstance(p, dict) or p.get("id") in vistos:
            continue
        vistos.add(p.get("id"))
        titulo = _titulo(p)
        base = {"post_id": int(p.get("id") or 0), "titulo": _html.unescape(titulo), "url": p.get("link") or "",
                "publicada": _fecha_post(p)}
        g = parsear_titulo_grillas(titulo)
        if g:
            urls = pdfs_de_contenido(_contenido(p))
            pdf, motivo = elegir_pdf_grillas(urls)
            grillas.append({**base, "fecha": g["fecha"], "pdf_url": pdf or "", "motivo": motivo})
            continue
        c = parsear_titulo_comunicado(titulo)
        if c:
            datos, motivo = parsear_comunicado(_contenido(p))
            item = {**base, "periodo": c["periodo"], "porcentaje": c["porcentaje"], "motivo": motivo}
            if datos:
                item.update(datos)
                # El mes del texto tiene que ser el del título: si no, algo cambió.
                if datos.get("mes_texto") and datos["mes_texto"] != c["periodo"]:
                    item["motivo"] = (f"el título dice {c['periodo']} y el texto {datos['mes_texto']}")
                    for k in ("inicial", "roe", "total"):
                        item.pop(k, None)
            comunicados.append(item)
    grillas.sort(key=lambda g: (g["publicada"], g["post_id"]))
    comunicados.sort(key=lambda c: (c["publicada"], c["post_id"]))
    return {"grillas": grillas, "comunicados": comunicados}


def aparear(grillas: list, comunicados: list, dias_maximos: int = 21) -> list:
    """Cada nota de grillas con SU comunicado: el más nuevo publicado el mismo
    día que la nota o antes, hasta `dias_maximos` antes. Un comunicado no sirve
    a dos notas de grillas (si pasa, las dos quedan sin par: no se adivina).
    Devuelve [{"periodo", "grilla", "comunicado", "motivo"}], de la más vieja a
    la más nueva; `periodo`/`comunicado` son None si no hay par."""
    pares = []
    for g in grillas:
        candidatos = []
        for c in comunicados:
            try:
                dias = (date.fromisoformat(g["publicada"]) - date.fromisoformat(c["publicada"])).days
            except ValueError:
                continue
            if 0 <= dias <= dias_maximos:
                candidatos.append((dias, c))
        if not candidatos:
            pares.append({"periodo": None, "grilla": g, "comunicado": None,
                          "motivo": "todavía no hay un comunicado publicado antes o el mismo día de esta nota"})
            continue
        candidatos.sort(key=lambda x: (x[0], -x[1]["post_id"]))
        pares.append({"periodo": candidatos[0][1]["periodo"], "grilla": g, "comunicado": candidatos[0][1], "motivo": ""})
    usados = {}
    for p in pares:
        if p["comunicado"]:
            usados.setdefault(p["comunicado"]["post_id"], []).append(p)
    for lista in usados.values():
        if len(lista) > 1:
            for p in lista:
                p["periodo"], p["comunicado"] = None, None
                p["motivo"] = "dos notas de grillas apuntan al mismo comunicado: no se adivina cuál es"
    return pares


def mes_siguiente(periodo: str) -> str:
    a, m = int(periodo[:4]), int(periodo[5:7])
    return f"{a + 1:04d}-01" if m == 12 else f"{a:04d}-{m + 1:02d}"


def nombre_del_periodo(periodo: str) -> str:
    nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
               "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    return f"{nombres[int(periodo[5:7]) - 1]} {int(periodo[:4])}"


# ---------------------------------------------------------------- red
class ErrorFuente(Exception):
    """El sitio no respondió o respondió algo que no se puede usar."""


def _pedir(url: str, tope: int, timeout: int = TIMEOUT_SEGUNDOS) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            datos = r.read(tope + 1)
    except Exception as e:                       # red, 4xx/5xx, SSL: para el hilo es lo mismo
        raise ErrorFuente(f"{type(e).__name__}: {e}") from e
    if len(datos) > tope:
        raise ErrorFuente("la respuesta supera el tope de tamaño")
    return datos


def _get_json(url: str):
    try:
        return json.loads(_pedir(url, TOPE_JSON_BYTES).decode("utf-8"))
    except ValueError as e:
        raise ErrorFuente(f"la respuesta no es JSON: {e}") from e


def descargar_pdf(url: str) -> bytes:
    """El PDF de las grillas. Solo del sitio del sindicato y con extensión .pdf:
    la URL sale de una nota, no se confía en ella para ir a cualquier parte."""
    u = urllib.parse.urlparse(url or "")
    if u.scheme != "https" or u.hostname != "labancaria.org" or not u.path.lower().endswith(".pdf"):
        raise ErrorFuente("el PDF no está en labancaria.org")
    datos = _pedir(url, TOPE_PDF_BYTES, timeout=60)
    if not datos.startswith(b"%PDF"):
        raise ErrorFuente("el archivo no es un PDF")
    return datos


def listar_novedades(get_json=None) -> dict:
    """Busca en el sitio las notas de grillas y los comunicados. Nunca levanta:
    devuelve {"ok": True, "grillas": [...], "comunicados": [...], "pares": [...]}
    o {"ok": False, "motivo": ...}. Una respuesta vacía o sin ninguna nota
    reconocible NO es «no hay novedades»: es un formato que cambió (o el sitio
    caído) y se informa como tal."""
    get = get_json or _get_json
    posts = []
    try:
        for q in BUSQUEDAS:
            url = f"{API_POSTS}?search={urllib.parse.quote(q)}&per_page=30&orderby=date&order=desc"
            lote = get(url)
            if not isinstance(lote, list):
                return {"ok": False, "motivo": "el sitio no devolvió una lista de notas"}
            posts.extend(lote)
    except ErrorFuente as e:
        return {"ok": False, "motivo": f"no se pudo consultar labancaria.org ({e})"}
    except Exception as e:
        return {"ok": False, "motivo": f"error inesperado consultando labancaria.org ({type(e).__name__}: {e})"}
    if not posts:
        return {"ok": False, "motivo": "el sitio devolvió una respuesta vacía"}
    c = clasificar_posts(posts)
    if not c["grillas"] and not c["comunicados"]:
        return {"ok": False, "motivo": "ninguna nota tiene el título esperado: el formato del sitio cambió"}
    return {"ok": True, **c, "pares": aparear(c["grillas"], c["comunicados"])}
