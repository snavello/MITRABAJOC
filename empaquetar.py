"""Empaqueta un HTML de Recursos en UN archivo que se abre sin conexión.

Es lo que baja el ícono de descarga de la landing `/entornos` cuando el
recurso es un HTML: la idea es mandarlo por WhatsApp o por mail y que del
otro lado se vea igual, sin depender de internet ni de nuestra app.

Los HTML de `recursos/` ya traen adentro sus estilos, imágenes y scripts;
lo único que salían a buscar afuera eran las tipografías de Google Fonts.
Acá se reemplaza ese `<link>` por un `<style>` con las fuentes embebidas
en base64 (solo el subconjunto `latin`, que cubre todo el castellano: el
resto multiplicaría el peso sin que se use). De yapa, para lo que se sube
a mano: `/static/...` de la app y hojas/scripts de los CDN conocidos
también se meten adentro.

Nunca rompe la descarga: lo que no se puede traer queda como estaba (el
archivo se abre igual, con la letra de reserva del navegador).
Solo se descarga de hosts de una lista cerrada -- nunca de una URL
cualquiera que venga escrita en un HTML subido.
"""
import base64
import mimetypes
import re
from pathlib import Path

import httpx

HOSTS_FUENTES = ("fonts.googleapis.com", "fonts.gstatic.com")
HOSTS_CDN = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com")
# Google Fonts decide el formato por el navegador: con este pide woff2.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CARPETA_STATIC = Path(__file__).parent / "static"
TIMEOUT = 8

_cache_urls: dict[str, bytes] = {}
_cache_paquetes: dict[str, bytes] = {}
_MAX_CACHE = 64


def _host(url: str) -> str:
    m = re.match(r"https://([^/?#]+)", url)
    return m.group(1).lower() if m else ""


def _traer(url: str) -> bytes | None:
    """GET con caché en memoria (las fuentes no cambian). None si falla."""
    if url in _cache_urls:
        return _cache_urls[url]
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT,
                      follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    if len(_cache_urls) >= _MAX_CACHE:
        _cache_urls.pop(next(iter(_cache_urls)))
    _cache_urls[url] = r.content
    return r.content


def _resolver(url: str) -> bytes | None:
    """Los bytes de una referencia, si es de las que se pueden embeber:
    un archivo de `/static/` de la app o un host de la lista cerrada."""
    url = (url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/static/"):
        ruta = (CARPETA_STATIC / url.split("?", 1)[0].split("#", 1)[0][len("/static/"):]).resolve()
        if ruta.is_file() and ruta.is_relative_to(CARPETA_STATIC.resolve()):
            return ruta.read_bytes()
        return None
    if _host(url) in HOSTS_FUENTES + HOSTS_CDN:
        return _traer(url)
    return None


def _data_uri(datos: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(datos).decode('ascii')}"


def _mime(url: str, defecto: str = "application/octet-stream") -> str:
    ruta = url.split("?", 1)[0]
    if ruta.endswith(".woff2"):
        return "font/woff2"
    if ruta.endswith(".woff"):
        return "font/woff"
    return mimetypes.guess_type(ruta)[0] or defecto


def _css_de_google(css: str) -> str | None:
    """Del CSS de Google Fonts deja solo los bloques `latin` y embebe cada
    archivo de fuente. None si alguna fuente no se pudo traer: mejor dejar
    el <link> original que un paquete a medias."""
    bloques = re.findall(r"(/\*\s*([\w-]+)\s*\*/\s*)?(@font-face\s*\{[^}]*\})", css)
    if any(nombre for _, nombre, _ in bloques):
        bloques = [b for b in bloques if b[1] == "latin"]
    salida = []
    for _, _, regla in bloques:
        faltó = False

        def embeber(m):
            nonlocal faltó
            url = m.group(1).strip("'\"")
            datos = _resolver(url)
            if datos is None:
                faltó = True
                return m.group(0)
            return f"url({_data_uri(datos, _mime(url))})"

        regla = re.sub(r"url\(([^)]+)\)", embeber, regla)
        if faltó:
            return None
        salida.append(regla)
    return "\n".join(salida) if salida else None


def _css_embebido(href: str) -> str | None:
    datos = _resolver(href)
    if datos is None:
        return None
    css = datos.decode("utf-8", "replace")
    if _host(href) == "fonts.googleapis.com":
        return _css_de_google(css)
    return css


def _attr(tag: str, nombre: str) -> str:
    m = re.search(rf'\b{nombre}\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))', tag, re.I)
    if not m:
        return ""
    return next(g for g in m.groups()[1:] if g is not None)


def empaquetar(html: str) -> str:
    """El HTML con todo lo externo embebido (lo que se pudo)."""
    def link(m):
        tag = m.group(0)
        rel = _attr(tag, "rel").lower()
        if "preconnect" in rel or "dns-prefetch" in rel:
            return ""                       # sin conexión no sirven de nada
        if "stylesheet" in rel:
            css = _css_embebido(_attr(tag, "href"))
            if css is not None:
                return f"<style>\n{css}\n</style>"
        return tag

    def importar(m):
        css = _css_embebido(m.group(2))
        return css if css is not None else m.group(0)

    def script(m):
        datos = _resolver(_attr(m.group(1), "src"))
        if datos is None:
            return m.group(0)
        abre = re.sub(r'\s+src\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', "", m.group(1), flags=re.I)
        codigo = datos.decode("utf-8", "replace").replace("</script", "<\\/script")
        return f"{abre}{codigo}</script>"

    def imagen(m):
        tag, src = m.group(0), _attr(m.group(0), "src")
        datos = _resolver(src)
        if datos is None:
            return tag
        return tag.replace(src, _data_uri(datos, _mime(src, "image/png")), 1)

    html = re.sub(r"<link\b[^>]*>", link, html, flags=re.I)
    html = re.sub(r"@import\s+url\((['\"]?)([^)'\"]+)\1\)\s*;?", importar, html)
    html = re.sub(r"(<script\b[^>]*\bsrc\s*=[^>]*>)\s*</script>", script, html, flags=re.I)
    html = re.sub(r"<img\b[^>]*>", imagen, html, flags=re.I)
    return html


def empaquetar_bytes(datos: bytes, clave: str) -> bytes:
    """`empaquetar` sobre bytes, con caché por `clave` (que tiene que
    cambiar si cambia el archivo). Un HTML que no es UTF-8 sale tal cual."""
    if clave in _cache_paquetes:
        return _cache_paquetes[clave]
    try:
        texto = datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos
    salida = empaquetar(texto).encode("utf-8")
    if b"fonts.googleapis.com" in salida:
        return salida        # quedó algo sin embeber: no se guarda, reintenta la próxima
    if len(_cache_paquetes) >= _MAX_CACHE:
        _cache_paquetes.pop(next(iter(_cache_paquetes)))
    _cache_paquetes[clave] = salida
    return salida
