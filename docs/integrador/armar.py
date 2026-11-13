"""Arma el Documento integrador de Colm3na en un HTML autocontenido.

    python docs/integrador/armar.py            # escribe recursos/colm3na-integrador.html
    python docs/integrador/armar.py --pdf      # además mide las páginas A4 y deja
                                               # el PDF y la miniatura (.jpg)

Junta `partes/*.html` en orden de nombre, arma el índice y el riel lateral
desde los `h2`/`h3`, incrusta las capturas de `capturas/` (las que faltan se
omiten), las fuentes y el logo, y arma el glosario con los `*.glosario.json`.
Cómo se escribe una parte: COMPONENTES.md.
"""
import base64
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
sys.path.insert(0, str(RAIZ))

SALIDA = RAIZ / "recursos" / "colm3na-integrador.html"
PDF = RAIZ / "recursos" / "colm3na-integrador.pdf"
MINIATURA = RAIZ / "recursos" / "colm3na-integrador.jpg"


def b64(ruta: Path) -> str:
    return base64.b64encode(ruta.read_bytes()).decode()


def fuentes() -> str:
    r = AQUI / "recursos"
    return (
        "@font-face{font-family:'Barlow Condensed';font-weight:600 800;font-display:swap;"
        f"src:url(data:font/woff2;base64,{b64(r / 'barlow-condensed-bold.woff2')}) format('woff2')}}\n"
        "@font-face{font-family:'Manrope';font-weight:200 800;font-display:swap;"
        f"src:url(data:font/woff2;base64,{b64(r / 'manrope.woff2')}) format('woff2')}}\n"
    )


def manifest() -> dict:
    m = AQUI / "capturas" / "manifest.json"
    return json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}


RE_FIG = re.compile(r'<figure class="fig captura([^"]*)" data-captura="([^"]+)"\s*>(.*?)</figure>', re.S)


def incrustar_capturas(texto: str, man: dict, usadas: list, faltan: list) -> str:
    def poner(m):
        clases, clave, adentro = m.group(1), m.group(2), m.group(3)
        info = man.get(clave) or {}
        archivo = AQUI / "capturas" / info.get("archivo", f"{clave}.webp")
        if info.get("falta") or not archivo.exists():
            faltan.append(clave)
            return ""
        usadas.append(clave)
        tipo = info.get("tipo", "movil" if clave.startswith(("t-", "e-")) else "escritorio")
        cls = clases
        if tipo == "movil" and "movil" not in cls:
            cls += " movil"
        ancho, alto = info.get("ancho"), info.get("alto")
        if tipo == "movil" and ancho and alto and alto > ancho * 2.4 and "entera" not in cls:
            cls += " entera"
        alt = html.escape(info.get("descripcion", clave), quote=True)
        dims = f' width="{ancho}" height="{alto}"' if ancho and alto else ""
        img = f'<img src="data:image/webp;base64,{b64(archivo)}" alt="{alt}"{dims} loading="lazy" decoding="async">'
        return f'<figure class="fig captura{cls}" data-captura="{clave}">{img}{adentro}</figure>'

    texto = RE_FIG.sub(poner, texto)
    # Un par o un lado que quedó sin figuras no deja un hueco.
    texto = re.sub(r'<div class="par-capturas">\s*</div>', "", texto)
    return texto


RE_CAP = re.compile(r'<section class="capitulo([^"]*)" id="([^"]+)"')
RE_H2 = re.compile(r'<span class="cap-num">([^<]+)</span>\s*<h2[^>]*>(.*?)</h2>', re.S)
RE_H3 = re.compile(r'<h3 id="([^"]+)"[^>]*>(.*?)</h3>', re.S)


def sin_etiquetas(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def indice(cuerpo: str):
    caps = []
    for trozo in re.split(r'(?=<section class="capitulo)', cuerpo):
        mc = RE_CAP.match(trozo)
        if not mc:
            continue
        m2 = RE_H2.search(trozo)
        if m2 and "continua" not in mc.group(1):
            caps.append({"id": mc.group(2), "num": m2.group(1).strip(), "titulo": sin_etiquetas(m2.group(2)), "secs": []})
        if not caps:
            continue
        for m3 in RE_H3.finditer(trozo):
            n = re.search(r'<span class="n">([^<]+)</span>', m3.group(2))
            titulo = sin_etiquetas(re.sub(r'<span class="n">[^<]+</span>', "", m3.group(2)))
            caps[-1]["secs"].append({"id": m3.group(1), "n": n.group(1) if n else "", "titulo": titulo})
    return caps


def html_indice(caps) -> str:
    filas = []
    for c in caps:
        secs = " · ".join(f'<a href="#{s["id"]}">{html.escape(s["n"] + " " + s["titulo"]).strip()}</a>' for s in c["secs"])
        filas.append(
            f'<li><a class="i1" href="#{c["id"]}"><span>{html.escape(c["num"])}</span>{html.escape(c["titulo"])}</a>'
            + (f'<span class="i2">{secs}</span>' if secs else "") + "</li>"
        )
    return '<nav class="indice" id="indice"><h2>Índice</h2><ol>' + "".join(filas) + "</ol></nav>"


def html_riel(caps) -> str:
    out = ['<aside class="riel no-imprimir" aria-label="Navegación"><b>Contenido</b>', '<a href="#indice">Índice</a>']
    for c in caps:
        out.append(f'<a href="#{c["id"]}">{html.escape(c["num"])} · {html.escape(c["titulo"])}</a>')
        for s in c["secs"]:
            out.append(f'<a class="n2" href="#{s["id"]}">{html.escape((s["n"] + " " + s["titulo"]).strip())}</a>')
    out.append("</aside>")
    return "\n".join(out)


def clave_orden(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def glosario() -> str:
    terminos = {}
    for f in sorted((AQUI / "partes").glob("*.glosario.json")):
        try:
            lista = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"  ! glosario ilegible {f.name}: {e}")
            continue
        for t in lista:
            termino, definicion = (t.get("termino") or "").strip(), (t.get("definicion") or "").strip()
            if termino and definicion and clave_orden(termino) not in terminos:
                terminos[clave_orden(termino)] = (termino, definicion)
    if not terminos:
        return ""
    filas = "".join(
        f"<div class=\"glo\"><dt>{html.escape(t)}</dt><dd>{html.escape(d)}</dd></div>" for _, (t, d) in sorted(terminos.items())
    )
    return (
        '<section class="capitulo" id="glosario"><header class="cap-cab"><span class="cap-num">A</span>'
        '<h2>Glosario</h2><p class="cap-bajada">Los términos propios y técnicos que aparecen en el documento, '
        "en orden alfabético.</p></header>"
        f'<dl class="glosario">{filas}</dl></section>'
    )


RIEL_JS = """<script>
(()=>{const ls=[...document.querySelectorAll('.riel a')];if(!ls.length)return;
const m=new Map(ls.map(a=>[a.getAttribute('href').slice(1),a]));
const io=new IntersectionObserver(es=>{for(const e of es){if(e.isIntersecting){ls.forEach(a=>a.classList.remove('on'));
const a=m.get(e.target.id);if(a){a.classList.add('on');a.scrollIntoView({block:'nearest'});}}}},{rootMargin:'0px 0px -75% 0px'});
m.forEach((a,id)=>{const el=document.getElementById(id);if(el)io.observe(el);});})();
</script>"""


def armar() -> dict:
    import version
    from fechas import hoy

    partes = sorted(p for p in (AQUI / "partes").glob("*.html"))
    cuerpo = "\n".join(p.read_text(encoding="utf-8") for p in partes if not p.name.startswith("00-"))
    portada_p = AQUI / "partes" / "00-portada.html"
    portada = portada_p.read_text(encoding="utf-8") if portada_p.exists() else ""

    man = manifest()
    usadas, faltan = [], []
    cuerpo = incrustar_capturas(cuerpo, man, usadas, faltan)
    cuerpo += "\n" + glosario()
    caps = indice(cuerpo)

    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
    d = hoy()
    reemplazos = {
        "{{LOGO}}": f"data:image/webp;base64,{b64(AQUI / 'recursos' / 'logo-claro.webp')}",
        "{{FECHA}}": f"{d.day} de {meses[d.month - 1]} de {d.year}",
        "{{V_TRABAJADOR}}": version.VERSION_TRABAJADOR,
        "{{V_ADMIN}}": version.VERSION_ADMIN,
        "{{V_PLATAFORMA}}": version.VERSION_PLATAFORMA,
        "{{INDICE}}": html_indice(caps),
    }
    for k, v in reemplazos.items():
        portada = portada.replace(k, v)

    css = fuentes() + (AQUI / "estilo.css").read_text(encoding="utf-8")
    pagina = (
        '<!doctype html><html lang="es-AR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Colm3na — Documento integrador</title>"
        '<meta name="description" content="Qué es Colm3na, cómo funciona, sus aplicaciones y módulos, '
        'el modelo técnico, la seguridad y la implementación, para quien se suma al equipo.">'
        f"<style>{css}</style></head><body>"
        + '<div class="sello-reservado" aria-hidden="true"><span>Uso interno · Reservado</span></div>'
        + html_riel(caps)
        + '<main class="doc">' + portada + '<div class="cuerpo">' + cuerpo + "</div>"
        + '<footer class="pie"><b>Uso interno · Reservado.</b> Colm3na · Documento integrador · '
        + reemplazos["{{FECHA}}"]
        + f" · Trabajador {version.VERSION_TRABAJADOR}, Admin {version.VERSION_ADMIN}, "
        + f"Plataforma {version.VERSION_PLATAFORMA}. Se regenera con <code>python docs/integrador/armar.py</code>.</footer>"
        + "</main>" + RIEL_JS + "</body></html>"
    )
    SALIDA.write_text(pagina, encoding="utf-8")
    palabras = len(sin_etiquetas(re.sub(r"<svg.*?</svg>|<img[^>]+>", " ", cuerpo, flags=re.S)).split())
    return {
        "archivo": str(SALIDA.relative_to(RAIZ)),
        "kb": round(SALIDA.stat().st_size / 1024),
        "palabras": palabras,
        "capitulos": len(caps),
        "diagramas": cuerpo.count('class="fig diagrama"'),
        "capturas": len(usadas),
        "faltan": sorted(set(faltan)),
    }


def medir_pdf() -> int:
    import subprocess

    subprocess.run(["node", str(AQUI / "pdf.js"), str(SALIDA), str(PDF), str(MINIATURA)], check=True)
    from pypdfium2 import PdfDocument

    return len(PdfDocument(str(PDF)))


if __name__ == "__main__":
    r = armar()
    for k, v in r.items():
        print(f"{k}: {v}")
    if "--pdf" in sys.argv:
        print(f"páginas A4: {medir_pdf()}  ({PDF.relative_to(RAIZ)}, {round(PDF.stat().st_size / 1024)} KB)")
