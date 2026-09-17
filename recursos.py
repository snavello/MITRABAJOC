"""Recursos del proyecto en la landing /entornos: la documentación (planes,
guías, videos, capturas, enlaces) catalogada en un solo lugar, cada pieza
con miniatura, descripción de una línea y fecha, ordenada de la más nueva
a la más vieja. Pedido de Sd (2026-09-07): los documentos estaban
repartidos entre el celular, la nube y la PC, y eso no escala.

Dos orígenes, una sola lista:

- **Del repositorio** (SEMILLA, abajo): archivos versionados en
  `recursos/` con su miniatura al lado. Viajan con el código a cualquier
  entorno, no hay que sembrarlos y no se pierden si se regenera o se clona
  la base. Se agregan con un commit (y una entrada acá).
- **Subidos desde la landing**: bytes en la base (tabla Recurso de db.py),
  igual que los logos y los adjuntos -- en Render no hay disco persistente.
  La miniatura la arma el navegador al subir (imágenes y videos) o la elige
  quien sube; sin miniatura, la landing dibuja una portada con el título.

Quién ve y quién sube. La landing entera (entornos y recursos) está
detrás del PIN de entorno.PIN_LANDING: son documentos internos (modelo
económico, plan de cuentas) en un host público. El PIN se ingresa una vez
por dispositivo y deja un "pase" firmado en una cookie de 30 días, que es
lo que abrir, subir y quitar recursos exigen. NO es una sesión de rol
(COOKIES_POR_ROL en main.py): no se renueva por actividad ni vence a los
15 minutos, porque no abre ningún panel -- solo esta landing. Una sesión
de plataforma vigente también vale.
"""
import hashlib
import hmac
import mimetypes
import time
from datetime import date
from pathlib import Path

import fechas
import auth

CARPETA = Path(__file__).resolve().parent / "recursos"

# Tope de lo que se sube desde la landing. Un video de difusión pesa 10-15
# MB; el tope deja margen sin que un archivo pueda tumbar el servicio
# (Starlette lo recibe en disco temporal, pero la base lo guarda entero).
TAMANIO_MAX = 30 * 1024 * 1024

COOKIE_PASE = "pase_entornos"
PASE_SEGUNDOS = 30 * 24 * 3600

# Tipos con los que la landing elige ícono, portada y cómo se sirve el
# archivo. "archivo" es el genérico (Word, Excel, zip...).
TIPOS = {
    "html": "Página", "pdf": "PDF", "imagen": "Imagen", "video": "Video",
    "audio": "Audio", "enlace": "Enlace", "archivo": "Archivo",
}

# Recursos que viven en el repositorio. `clave` es la parte de la URL
# (/recursos/{clave}/archivo) y no cambia aunque cambie el título; `fecha`
# es la del documento, no la del commit; `fragmento` es la ancla o pestaña
# con la que conviene abrirlo. El archivo y la miniatura están en CARPETA.
# El MP4 del video de difusión viene de la rama
# claude/recibos-tramites-video-0v4zmo del repo MiTrabajo, donde quedó la
# composición (HyperFrames) para regenerarlo; acá va solo el render. La
# documentación técnica se regenera con docs/generador/ (lee db.py, main.py
# y migrations/); su miniatura es una captura de la portada.
SEMILLA = [
    {
        "clave": "bitacora",
        "titulo": "Bitácora del proyecto",
        "descripcion": "Qué se hizo cada día, con qué herramienta (Chat, Code, Cowork) y "
                       "dónde está el detalle. Se regenera desde BITACORA.md con generar_bitacora.py.",
        "fecha": date(2026, 9, 17),
        "archivo": "bitacora.html",
        "miniatura": "bitacora.jpg",
        "fragmento": "",
    },
    {
        "clave": "motor-recibos",
        "titulo": "Motor de recibos: de la foto al veredicto",
        "descripcion": "Cómo se lee y se valida un recibo hoy, qué falla, y qué cambia con "
                       "el motor v2: tres lecturas, confianza por renglón y enmascarado.",
        "fecha": date(2026, 9, 13),
        "archivo": "motor-recibos.html",
        "miniatura": "motor-recibos.jpg",
        "fragmento": "",
    },
    {
        "clave": "anexo-servicios-mensuales",
        "titulo": "Anexo Servicios Mensuales",
        "descripcion": "Costo mensual aproximado de operar la plataforma: Render, Postgres, "
                       "S3, IA por uso, licencias y operación, con fuentes y titularidad.",
        "fecha": date(2026, 9, 7),
        "archivo": "anexo-servicios-mensuales.html",
        "miniatura": "anexo-servicios-mensuales.jpg",
        "fragmento": "",
    },
    {
        "clave": "documentacion-tecnica",
        "titulo": "Documentación técnica",
        "descripcion": "Funcionalidades por rol, arquitectura con diagramas, componentes y rutas, "
                       "y el modelo de datos completo. Generada del código.",
        "fecha": date(2026, 9, 7),
        "archivo": "documentacion-tecnica.html",
        "miniatura": "documentacion-tecnica.jpg",
        "fragmento": "",
    },
    {
        "clave": "plan-maestro",
        "titulo": "Plan Maestro Colm3na",
        "descripcion": "Quién es quién, hitos con fecha y tareas semana a semana "
                       "de la primera implementación (La Bancaria).",
        "fecha": date(2026, 9, 7),
        "archivo": "colm3na-plan-maestro.html",
        "miniatura": "colm3na-plan-maestro.jpg",
        "fragmento": "",
    },
    {
        "clave": "plan-implementacion-sindicato",
        "titulo": "Plan de implementación en el sindicato",
        "descripcion": "Estrategia, plan por etapas con checklist, formularios de "
                       "relevamiento y registro de decisiones.",
        "fecha": date(2026, 9, 4),
        "archivo": "colm3na-plan-implementacion-sindicato.html",
        "miniatura": "colm3na-plan-implementacion-sindicato.jpg",
        "fragmento": "#estrategia",
    },
    {
        "clave": "video-recibos-tramites",
        "titulo": "Video: tu recibo y tus trámites, en tu bolsillo",
        "descripcion": "Pieza de difusión para afiliados (55 s) sobre la verificación "
                       "del recibo y los trámites on line, en criollo.",
        "fecha": date(2026, 9, 5),
        "archivo": "mi-trabajo-recibos-tramites.mp4",
        "miniatura": "mi-trabajo-recibos-tramites.jpg",
        "fragmento": "",
    },
]


# ---------- Tipo, fechas y tamaños ----------
def tipo_de(mime: str, nombre: str = "", url: str = "") -> str:
    """Clasifica por el MIME que declaró el navegador y, si no alcanza, por
    la extensión. Un enlace sin archivo es "enlace"."""
    if url and not nombre:
        return "enlace"
    mime = (mime or "").split(";")[0].strip().lower()   # sin "; charset=..."
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(nombre or "")[0] or ""
    if mime in ("text/html", "application/xhtml+xml"):
        return "html"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("image/"):
        return "imagen"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "archivo"


def mime_de(mime: str, nombre: str) -> str:
    """MIME para servir el archivo: el declarado, o el de la extensión. Las
    páginas se sirven siempre como text/html con charset (los documentos
    exportados desde Claude son UTF-8)."""
    mime = (mime or "").lower()
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(nombre or "")[0] or "application/octet-stream"
    if mime in ("text/html", "application/xhtml+xml"):
        return "text/html; charset=utf-8"
    return mime


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_legible(d: date) -> str:
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def tamanio_legible(n: int) -> str:
    if not n:
        return ""
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / (1024 * 1024):.1f} MB".replace(".0 MB", " MB")


def leer_fecha(texto: str) -> date:
    """La fecha del formulario (AAAA-MM-DD); vacía o inválida = hoy."""
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return fechas.hoy()


def normalizar_fragmento(texto: str) -> str:
    """"estrategia" o "#estrategia" -> "#estrategia"; vacío queda vacío."""
    texto = (texto or "").strip()
    if not texto:
        return ""
    return texto if texto.startswith("#") else "#" + texto


# ---------- Pase (el PIN de la landing, una vez por dispositivo) ----------
def crear_pase() -> str:
    """Token "vence.firma": el vencimiento absoluto (30 días) firmado con
    SESSION_SECRET. Distinto de auth.crear_sesion a propósito: aquel vence
    por inactividad y se renueva en cada request
    (main.renovar_sesion_por_actividad); este se emite una vez y dura lo
    que dura. Sin base64 para que la cookie no lleve '=' ni comillas."""
    vence = int(time.time()) + PASE_SEGUNDOS
    return f"{vence}.{_firma_pase(vence)}"


def _firma_pase(vence: int) -> str:
    return hmac.new(auth.SECRETO.encode(), f"recursos:{vence}".encode(), hashlib.sha256).hexdigest()[:32]


def pase_valido(token: str) -> bool:
    if not token or "." not in token:
        return False
    vence, firma = token.split(".", 1)
    if not vence.isdigit() or not hmac.compare_digest(firma, _firma_pase(int(vence))):
        return False
    return time.time() < int(vence)


# ---------- Catálogo ----------
def _sello(ruta: Path) -> str:
    """Mismo criterio que main._sello_static: mtime + tamaño, para que la
    miniatura cacheada se renueve si el archivo cambia."""
    try:
        st = ruta.stat()
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return "0"


def del_repositorio() -> list[dict]:
    """Los recursos versionados, con el mismo formato que los de la base."""
    lista = []
    for item in SEMILLA:
        ruta = CARPETA / item["archivo"]
        mini = CARPETA / item["miniatura"] if item.get("miniatura") else None
        tamanio = ruta.stat().st_size if ruta.exists() else 0
        lista.append(_ficha(
            ref=item["clave"], origen="repo", titulo=item["titulo"],
            descripcion=item["descripcion"], fecha=item["fecha"],
            tipo=tipo_de("", item["archivo"]), url="", nombre_archivo=item["archivo"],
            tamanio=tamanio, fragmento=item.get("fragmento", ""),
            miniatura_url=(f"/recursos/{item['clave']}/miniatura?v={_sello(mini)}"
                           if mini and mini.exists() else ""),
        ))
    return lista


def del_repositorio_por_clave(clave: str) -> dict | None:
    """Ruta del archivo y de la miniatura de un recurso del repositorio."""
    for item in SEMILLA:
        if item["clave"] == clave:
            return {
                "ruta": CARPETA / item["archivo"],
                "nombre_archivo": item["archivo"],
                "mime": mime_de("", item["archivo"]),
                "miniatura": (CARPETA / item["miniatura"]) if item.get("miniatura") else None,
            }
    return None


def texto_portada(tipo: str, url: str, nombre_archivo: str) -> str:
    """Lo que la tarjeta escribe grande cuando no hay miniatura: el host de
    un enlace, la extensión de un archivo, o el tipo. El título ya va
    debajo, repetirlo en la portada era ruido."""
    if url and not nombre_archivo:
        try:
            return url.split("//", 1)[1].split("/", 1)[0].removeprefix("www.")
        except IndexError:
            return "enlace"
    ext = Path(nombre_archivo).suffix.lstrip(".").upper() if nombre_archivo else ""
    return ext or TIPOS.get(tipo, "Archivo").upper()


def _ficha(ref, origen, titulo, descripcion, fecha, tipo, url, nombre_archivo,
           tamanio, fragmento, miniatura_url) -> dict:
    return {
        "portada": texto_portada(tipo, url, nombre_archivo),
        "ref": ref, "origen": origen, "titulo": titulo, "descripcion": descripcion,
        "fecha": fecha, "fecha_legible": fecha_legible(fecha), "fecha_iso": fecha.isoformat(),
        "tipo": tipo, "tipo_nombre": TIPOS.get(tipo, "Archivo"), "url": url,
        "nombre_archivo": nombre_archivo, "tamanio": tamanio,
        "tamanio_legible": tamanio_legible(tamanio), "fragmento": fragmento,
        "href": f"/recursos/{ref}/archivo{fragmento}", "miniatura_url": miniatura_url,
    }


def catalogo() -> list[dict]:
    """Repositorio + base, de la fecha más nueva a la más vieja; a igual
    fecha, lo subido último va primero y lo del repositorio al final."""
    import db
    lista = del_repositorio()
    for r in db.listar_recursos():
        lista.append(_ficha(
            ref=str(r["id"]), origen="base", titulo=r["titulo"], descripcion=r["descripcion"],
            fecha=r["fecha"], tipo=r["tipo"], url=r["url"], nombre_archivo=r["nombre_archivo"],
            tamanio=r["tamanio"], fragmento=r["fragmento"],
            miniatura_url=f"/recursos/{r['id']}/miniatura" if r["miniatura_mime"] else "",
        ))
    # Los del repositorio no tienen id: 0 los deja detrás de los subidos con
    # la misma fecha.
    lista.sort(key=lambda x: (x["fecha"], int(x["ref"]) if x["ref"].isdigit() else 0), reverse=True)
    return lista
