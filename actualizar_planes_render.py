# -*- coding: utf-8 -*-
"""Baja el catálogo de planes de Render desde su propia página de precios y
lo deja en data/render_planes.json.

Los precios de un proveedor cambian, y un número escrito a mano en el código
envejece sin que nadie lo note -- es el mismo problema que tuvimos con el
informe de carga. Así que acá no hay ni un precio escrito a mano: se leen de
render.com/pricing, que publica las mismas tablas con los MISMOS
identificadores de plan que devuelve la API (`0.5c-512mb`, `4c-8g`, ...), y
el archivo guarda la fecha en que se leyó para que la pantalla pueda decirlo.

Si Render cambia el maquetado de esa página, este script NO inventa nada:
falla con un mensaje y deja el JSON anterior intacto. Un catálogo viejo con
su fecha a la vista es honesto; uno a medio parsear, no.

Uso:  python actualizar_planes_render.py
"""
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://render.com/pricing"
SALIDA = Path(__file__).resolve().parent / "data" / "render_planes.json"

# Cuántos planes esperamos como mínimo de cada tipo. Es la red de seguridad
# contra un parseo que "anda" pero devuelve tres filas: mejor fallar.
MINIMO_WEB, MINIMO_DB = 8, 10


def _celdas(tr: str) -> list:
    out = []
    for td in re.findall(r"<t[dh]\b.*?</t[dh]>", tr, re.S):
        txt = html.unescape(re.sub(r"<[^>]+>", " ", td))
        out.append(re.sub(r"\s+", " ", txt).strip())
    return out


def _precio(txt: str):
    """"$175/month" -> 175.0 ; "$0/month" -> 0.0 ; otra cosa -> None."""
    m = re.match(r"^\$([\d,]+(?:\.\d+)?)/month$", txt.strip())
    return float(m.group(1).replace(",", "")) if m else None


def _ram_mb(txt: str):
    m = re.match(r"^([\d.]+)\s*(MB|GB)\b", txt.strip(), re.I)
    if not m:
        return None
    valor = float(m.group(1))
    return int(valor * 1024) if m.group(2).upper() == "GB" else int(valor)


def _vcpu(slug: str):
    """El identificador ya trae la CPU: "4c-8g" -> 4, "0.5c-512mb" -> 0,5.
    Se saca de ahí y no de la columna de texto ("Less than 1 CPU" no es un
    número), así que coincide exactamente con lo que cobra Render."""
    m = re.match(r"^([\d.]+)c-", slug)
    return float(m.group(1)) if m else None


def _conexiones(txt: str):
    m = re.match(r"^(\d+)\s+connections$", txt.strip())
    return int(m.group(1)) if m else None


def descargar(url: str = URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parsear(pagina: str) -> dict:
    """Las tablas de precios mensuales de la página. Las filas de web
    (4 columnas) y las de Postgres (5, la extra es el límite de conexiones)
    se distinguen solas por su forma, así que no hay que adivinar cuál tabla
    es cuál por su posición en el HTML.

    Ojo: la página también trae tablas de precios POR MINUTO y POR HORA para
    los mismos planes. Se descartan porque _precio() solo acepta "/month" --
    si algún día quisiéramos el precio por hora, hay que pedirlo explícito."""
    web, dbs = {}, {}
    for tr in re.findall(r"<tr\b.*?</tr>", pagina, re.S):
        c = _celdas(tr)
        if len(c) not in (4, 5):
            continue
        slug = c[-1]
        if not re.fullmatch(r"[\d.]+c-[\w]+", slug):
            continue  # "free" y encabezados quedan afuera a propósito
        precio, ram = _precio(c[1]), _ram_mb(c[2])
        if precio is None or ram is None:
            continue
        fila = {"id": slug, "vcpu": _vcpu(slug), "ram_mb": ram,
                "usd_mes": precio}
        if len(c) == 5:
            con = _conexiones(c[3])
            if con is None:
                continue
            dbs[slug] = {**fila, "conexiones_max": con}
        else:
            web[slug] = fila
    return {"web": web, "db": dbs}


def construir() -> dict:
    cat = parsear(descargar())
    if len(cat["web"]) < MINIMO_WEB or len(cat["db"]) < MINIMO_DB:
        sys.exit(f"Solo se pudieron leer {len(cat['web'])} planes web y "
                 f"{len(cat['db'])} de base de {URL}. Cambió el maquetado: "
                 f"revisar el parseo. No se toca data/render_planes.json.")
    orden = lambda d: sorted(d.values(), key=lambda p: (p["usd_mes"], p["vcpu"]))
    return {
        "fuente": URL,
        "leido_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "moneda": "USD",
        "web": orden(cat["web"]),
        "db": orden(cat["db"]),
    }


if __name__ == "__main__":
    datos = construir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Escrito {SALIDA}: {len(datos['web'])} planes web y "
          f"{len(datos['db'])} de base, leídos el {datos['leido_utc']} UTC.")
