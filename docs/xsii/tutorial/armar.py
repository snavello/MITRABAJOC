"""Arma recursos/xsii-tutorial.html desde pasos.json + capturas/*.jpg.
Uso (desde la raíz del repo):  .venv/bin/python docs/xsii/tutorial/armar.py
Un solo HTML autocontenido: CSS adentro, imágenes en base64 (JPEG reducido). Sin CDN."""
import base64
import html
import io
import json
import re
from pathlib import Path

from PIL import Image

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SALIDA = RAIZ / "recursos" / "xsii-tutorial.html"
# Ancho máximo de lo que se embebe, por tamaño de figura (el original queda en capturas/).
ANCHOS = {"full": 1200, "med": 900, "chica": 640}
CLASES = {"full": "f-full", "med": "f-med", "chica": "f-chica"}


def esc(t):
    return html.escape(t, quote=False)


def b64(nombre, ancho):
    im = Image.open(AQUI / "capturas" / f"{nombre}.jpg").convert("RGB")
    if im.width > ancho:
        im = im.resize((ancho, round(im.height * ancho / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=68, optimize=True, progressive=True)
    return base64.b64encode(buf.getvalue()).decode(), im.size


CSS = """
:root{--tinta:#131c2e;--gris:#566175;--linea:#d9dfe8;--acento:#2447d8;--acento-s:#e8edfd;--naranja:#e8590c;--fondo:#eef1f6}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--fondo);color:var(--tinta);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.hoja{max-width:860px;margin:0 auto;background:#fff;padding:48px 56px 64px;border-left:1px solid var(--linea);border-right:1px solid var(--linea)}
.sup{font-size:12px;letter-spacing:.8px;text-transform:uppercase;color:var(--gris);font-weight:600;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}
.marca{font:700 28px/1 "Barlow Condensed","Arial Narrow",sans-serif;letter-spacing:1px;color:var(--tinta)}
.marca i{font-style:normal;color:var(--acento)}
h1{font:700 40px/1.05 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;text-transform:uppercase;letter-spacing:.4px;margin:22px 0 10px}
.bajada{font-size:19px;color:var(--gris);margin:0 0 18px}
.fecha{font-size:13px;color:var(--gris)}
h2{font:700 27px/1.1 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;text-transform:uppercase;letter-spacing:.3px;margin:0 0 10px}
.paso{margin-top:46px;padding-top:26px;border-top:2px solid var(--linea);break-inside:auto}
.paso h2{display:flex;gap:12px;align-items:center}
.num{flex:none;width:36px;height:36px;border-radius:50%;background:var(--acento);color:#fff;font:700 18px/36px system-ui,sans-serif;text-align:center}
p{margin:0 0 12px}
b{font-weight:650}
.indice{background:var(--acento-s);border-radius:12px;padding:16px 22px;margin:26px 0}
.indice h2{font-size:20px}
.indice ol{margin:8px 0 0;padding-left:22px;columns:2;column-gap:32px}
.indice li{margin:3px 0;break-inside:avoid}
.indice a{color:var(--acento);text-decoration:none}
.aviso{border-left:4px solid var(--naranja);background:#fff4ec;border-radius:0 10px 10px 0;padding:10px 16px;margin:18px 0}
.recuadro{border:1px solid var(--linea);background:#f6f8fb;border-radius:10px;padding:10px 16px;margin:14px 0}
.recuadro b{display:block;font-size:13px;letter-spacing:.7px;text-transform:uppercase;color:var(--gris)}
figure{margin:18px auto;break-inside:avoid}
figure img{display:block;width:100%;height:auto;border:1px solid var(--linea);border-radius:8px}
figcaption{font-size:13.5px;color:var(--gris);margin-top:6px;text-align:center}
.f-full{width:100%}.f-med{width:78%}.f-chica{width:48%}
details{border:1px solid var(--linea);border-radius:10px;padding:10px 16px;margin:10px 0;break-inside:avoid}
summary{font-weight:650;cursor:pointer}
details[open] summary{margin-bottom:6px}
details p{margin:0;color:var(--gris)}
.viene li{margin:8px 0}
.pie{margin-top:44px;font-size:12.5px;color:var(--gris);border-top:1px solid var(--linea);padding-top:14px}
@media (max-width:700px){.hoja{padding:24px 18px 40px}h1{font-size:32px}.indice ol{columns:1}.f-med{width:100%}.f-chica{width:80%}}
@media print{
  @page{size:A4;margin:16mm 14mm}
  body{background:#fff;font-size:11pt;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .hoja{max-width:none;border:0;padding:0}
  .paso{break-before:auto}
  h2,figcaption{break-after:avoid}
  figure{break-inside:avoid}.f-med{width:58%}.f-chica{width:40%}
  details{border:0;padding:0;margin:8px 0}
  details summary{list-style:none}
  details p{color:var(--tinta)}
  details[open]>summary{margin-bottom:2px}
  a{color:inherit;text-decoration:none}
}
"""


def main():
    d = json.loads((AQUI / "pasos.json").read_text(encoding="utf-8"))
    o = []
    o.append('<!doctype html><html lang="es"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width, initial-scale=1">'
             '<meta name="robots" content="noindex, nofollow">'
             '<title>XSII · Tutorial paso a paso</title><style>' + CSS + '</style></head><body><div class="hoja">')
    o.append('<header><div class="sup"><span class="marca">XS<i>II</i></span><span>' + esc(d["encabezado"]) + '</span></div>')
    o.append('<h1>' + esc(d["titulo"]) + '</h1><p class="bajada">' + esc(d["bajada"]) + '</p><div class="fecha">Actualizado el ' + esc(d["fecha"]) + '</div></header>')
    o.append('<section>' + ''.join('<p>' + esc(p) + '</p>' for p in d["intro"]) + '<div class="aviso"><b>Qué cubre esta versión.</b> ' + esc(d["alcance"]) + '</div></section>')
    o.append('<nav class="indice"><h2>Índice</h2><ol>' + ''.join(
        f'<li><a href="#{p["id"]}">{esc(p["titulo"])}</a></li>' for p in d["pasos"]) +
        '<li><a href="#preguntas">Preguntas frecuentes</a></li><li><a href="#viene">Qué viene</a></li></ol></nav>')
    figs = 0
    for i, p in enumerate(d["pasos"], 1):
        o.append(f'<section class="paso" id="{p["id"]}"><h2><span class="num">{i}</span>{esc(p["titulo"])}</h2>')
        # el texto admite <b> y nada más
        for t in p["texto"]:
            o.append('<p>' + re.sub(r'&lt;(/?)b&gt;', r'<\1b>', esc(t)) + '</p>')
        if p.get("recuadro"):
            o.append(f'<div class="recuadro"><b>{esc(p["recuadro"][0])}</b>{esc(p["recuadro"][1])}</div>')
        for f in p.get("figuras", []):
            datos, (w, h) = b64(f["archivo"], ANCHOS[f["ancho"]])
            figs += 1
            o.append(f'<figure class="{CLASES[f["ancho"]]}"><img alt="{esc(f["epigrafe"])}" width="{w}" height="{h}" '
                     f'src="data:image/jpeg;base64,{datos}"><figcaption>{esc(f["epigrafe"])}</figcaption></figure>')
        o.append('</section>')
    o.append('<section class="paso" id="preguntas"><h2>Preguntas frecuentes</h2>' + ''.join(
        f'<details><summary>{esc(q)}</summary><p>{esc(r)}</p></details>' for q, r in d["preguntas"]) + '</section>')
    o.append('<section class="paso viene" id="viene"><h2>Qué viene</h2><ul>' + ''.join(
        f'<li><b>{esc(t)}.</b> {esc(r)}</li>' for t, r in d["viene"]) + '</ul></section>')
    o.append('<p class="pie">Suite XSanders · XSII. Las pantallas son capturas reales de XSII con datos simulados de la demo. '
             'Se regenera con docs/xsii/tutorial/armar.py.</p></div></body></html>')
    SALIDA.write_text(''.join(o), encoding="utf-8")
    print(f"{SALIDA.name}: {len(d['pasos'])} pasos, {figs} figuras, {SALIDA.stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
