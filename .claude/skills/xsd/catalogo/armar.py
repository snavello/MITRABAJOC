"""Arma el catálogo de estilos de XSD: cada estilo de `estilos/` vistiendo la portada de ACME, con la página
para marcar cuáles van. Uso:

    python <kit>/catalogo/armar.py [salida.html]

Por defecto escribe `xsd-trabajo/catalogo/index.html` (relativo a donde se corre) y copia `fotos/` al lado,
que es lo que se publica (la página y `fotos/*.jpg` como archivos del artifact).
"""
import glob
import html
import json
import re
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent

FAMILIAS = [
    ("elegidos", "Los que eligió Colm3na", "Los cuatro que quedaron en la app después del concurso y la auditoría.",
     ["electrico-laguna", "noticiero-indigo-claro", "hilo", "hoja-de-trabajo-colm3na"]),
    ("producto", "Claros de producto", "Blancos, aireados y con un solo énfasis por pantalla. El terreno de casi toda app de gestión.",
     ["electrico-configurador", "nordico-sereno", "cercano-paneles", "tonal-primario", "pagos-refinados", "claridad-govuk"]),
    ("claros", "Muy claros", "Casi todo blanco o gris perla: la marca aparece en un detalle y el contenido respira.",
     ["cupertino", "oro-sueco", "vidrio-claro", "sintesis-total"]),
    ("color", "De color", "El color es protagonista: formas, contenedores y bloques en varios tonos.",
     ["pop-color-pleno", "bloque-bauhaus", "expresivo-material", "instructivo"]),
    ("grises", "Grises con uno o dos colores", "Una base neutra de grises o metal y uno o dos colores que señalan solo lo que importa.",
     ["precision", "funcion-rams", "sintetizador", "punto-rojo", "aluminio"]),
    ("editoriales", "Editoriales", "Papel, filetes y tipografía con voz: se leen como un diario o un informe.",
     ["uboard-informe-editorial", "documental-duotono", "uboard-planilla", "tinta-suizo"]),
    ("fotos", "Fotográficos", "La foto manda: a sangre, en blanco y negro o en duotono, con la tipografía encima.",
     ["galeria-fotolibro", "tapa-revista-gigante"]),
    ("objeto", "Con objeto", "La interfaz toma la forma de algo que la gente ya conoce: un mapa de subte, una credencial, un talonario.",
     ["anden-senaletica", "credencial-impresion-seguridad", "talon-recibo-talonario"]),
    ("fluor", "Flúor", "Un color flúor (lima, voltio, amarillo) sobre negro o gris claro, reservado para la acción y la cifra.",
     ["nucleo-verde", "impulso-voltio", "fluor-resaltador", "noticiero-oscuro-fluor", "electrico-sobrio-fluor"]),
    ("oscuros", "Oscuros", "Para tableros, operación de noche o marcas que viven en negro.",
     ["marcador-deportivo", "grafito-pro", "espacial-vidrio"]),
    ("mov-sereno", "Con movimiento sereno", "El movimiento acompaña y se calla: entradas escalonadas, un latido, una línea que se dibuja y queda quieta.",
     ["pulso-minimal", "mosaico-baldosa-calcarea", "vivo-micromovimiento", "movimiento-sereno", "colmena-sutil",
      "sereno-linea-movil", "linea-de-tiempo", "semaforo-lampara", "senaletica-suave", "revista-gremio"]),
    ("mov-energia", "Con movimiento y energía", "El movimiento es parte de la marca: un telón que sube, luces de estadio, un brillo que recorre, una aguja que gira.",
     ["telon", "cine-subtitulo", "estadio-led", "chaleco-reflectivo", "zocalo-noticiero",
      "esfera-relojeria", "cartelera", "hipercoche", "contraluz-medido", "box-carrera"]),
]


def leer_fuentes(texto):
    """«Familia:ejes@t1;t2; Otra:...» → [(familia, ejes, [tupla, ...])]. Un `;` separa tuplas o familias."""
    salida = []
    for trozo in texto.split(";"):
        trozo = trozo.strip()
        if not trozo:
            continue
        if re.match(r"[A-Za-z]", trozo):
            fam, _, resto = trozo.partition(":")
            ejes, _, tupla = resto.partition("@")
            salida.append([fam.strip(), ejes.strip(), [tupla.strip()] if tupla.strip() else []])
        elif salida:
            salida[-1][2].append(trozo)
    return salida


def _num(v):
    return float(v.split("..")[0])


def unir_fuentes(lista):
    """Una entrada css2 por familia: los ejes de la declaración más completa y, por eje, el rango que cubre todo lo pedido."""
    por_fam = {}
    for fam, ejes, tuplas in lista:
        por_fam.setdefault(fam, []).append((ejes, tuplas))
    salida = []
    for fam, decl in sorted(por_fam.items()):
        ejes = max((e for e, _ in decl), key=lambda e: len(e.split(",")) if e else 0)
        if not ejes:
            salida.append(fam)
            continue
        nombres = ejes.split(",")
        tuplas = [t.split(",") for e, ts in decl if e == ejes for t in ts]
        if not tuplas:
            salida.append(fam)
            continue
        if nombres == ["wght"] and not any(".." in t[0] for t in tuplas):
            pesos = sorted({t[0] for t in tuplas}, key=_num)
            salida.append(f"{fam}:wght@{';'.join(pesos)}")
            continue
        grupos = {}
        for t in tuplas:
            clave = t[0] if nombres[0] == "ital" else ""
            grupos.setdefault(clave, []).append(t)
        filas = []
        for clave, ts in sorted(grupos.items()):
            fila = [clave] if clave else []
            for i in range(1 if clave else 0, len(nombres)):
                vals = [v for t in ts for v in t[i].split("..")]
                lo, hi = min(vals, key=float), max(vals, key=float)
                fila.append(lo if lo == hi else f"{lo}..{hi}")
            filas.append(",".join(fila))
        salida.append(f"{fam}:{ejes}@{';'.join(filas)}")
    return salida


def fichas():
    """Nombre, origen y descripción de cada estilo (`estilos.json`)."""
    return json.loads((AQUI / "estilos.json").read_text(encoding="utf-8"))


def origen_txt(e):
    return e.get("origen") or "propuesta", ""


def main():
    F = fichas()
    molde = (AQUI / "molde.html").read_text(encoding="utf-8")
    art = molde.split("<!-- El héroe por defecto")[0].split("-->", 1)[1].strip()
    heroe_base = re.search(r'<template id="heroe-base">(.*?)</template>', molde, re.S).group(1).strip()
    def foto(nombre):
        return f'<img class="m-foto" src="fotos/{nombre}.jpg" alt="" decoding="async">'
    base_css = (AQUI / "base.css").read_text(encoding="utf-8")
    familias_fuente = []
    css_estilos, tarjetas_por_familia, faltan = [], {}, []
    datos = []
    for fam_id, fam_nom, fam_txt, ids in FAMILIAS:
        tarjetas = []
        for i in ids:
            css_p = AQUI / "estilos" / f"{i}.css"
            e = F.get(i, {"id": i, "nombre": i})
            if not css_p.exists():
                faltan.append(i)
                continue
            css = css_p.read_text(encoding="utf-8")
            m = re.search(r"/\*\s*fuentes:\s*(.*?)\*/", css)
            if m:
                familias_fuente.extend(leer_fuentes(m.group(1)))
            css_estilos.append(css)
            heroe_p = AQUI / "estilos" / f"{i}.heroe.html"
            heroe = heroe_p.read_text(encoding="utf-8") if heroe_p.exists() else heroe_base
            mf = re.search(r"/\*\s*foto:\s*([a-z]+)\s*(?:;\s*([a-z]+))?\s*\*/", css)
            f_heroe, f_nov = (mf.group(1), mf.group(2) or "calle") if mf else ("tecnico", "calle")
            pieza = (art.replace("{{HEROE}}", heroe).replace("{{FOTO_NOV}}", foto(f_nov))
                     .replace("{{FOTO}}", foto(f_heroe)).replace("{{ID}}", i))
            pieza = pieza.replace('class="m"', f'class="m e-{i}"', 1)
            ori, lienzo = origen_txt(e)
            datos.append({"id": i, "nombre": e.get("nombre", i), "familia": fam_nom})
            tarjetas.append(f"""
<article class="est" id="{i}" data-id="{i}">
  <button class="marco" type="button" aria-label="Ver {html.escape(e.get('nombre', i))} en grande"><div class="escala">{pieza}</div></button>
  <div class="est-txt">
    <h3>{html.escape(e.get('nombre', i))}</h3>{'<button type="button" class="repetir">Repetir la animación</button>' if fam_id.startswith('mov') else ''}
    <p class="ori">{html.escape(ori)} · {html.escape(e.get('claro_u_oscuro') or '')}</p>
    <p>{html.escape(e.get('caracter') or '')}</p>
    <p class="firma"><span class="lbl">Firma</span>{html.escape(e.get('firma') or '')}</p>
    <p class="cuidado"><span class="lbl">Cuidado</span>{html.escape(e.get('cuidado') or '')}</p>
    <div class="decide" data-id="{i}">
      <button type="button" data-e="va">Va</button>
      <button type="button" data-e="no">No va</button>
      <button type="button" data-e="cambio">Va con cambios</button>
      <span class="estado"></span>
      <div class="cambio-caja" hidden><label>Qué cambiarías<textarea placeholder="Por ejemplo: menos fluor, títulos más chicos…"></textarea></label><button type="button" class="guardar-nota">Guardar</button></div>
    </div>
  </div>
</article>""")
        tarjetas_por_familia[fam_id] = (fam_nom, fam_txt, tarjetas)

    secciones = "".join(f"""
<section class="familia" id="f-{fid}">
  <h2>{html.escape(nom)} <small>{len(t)}</small></h2>
  <p class="fam-txt">{html.escape(txt)}</p>
  <div class="grilla">{''.join(t)}</div>
</section>""" for fid, (nom, txt, t) in tarjetas_por_familia.items())

    fuentes_link = ""
    familias_fuente += leer_fuentes("Barlow Condensed:wght@600;700; Barlow:wght@400;500;600; IBM Plex Mono:wght@400;500")
    fams = unir_fuentes(familias_fuente)
    if fams:
        q = "&".join("family=" + f.replace(" ", "+") for f in fams)
        fuentes_link = f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{q}&display=swap">'

    pagina = (AQUI / "pagina.html").read_text(encoding="utf-8")
    pagina = (pagina.replace("{{FUENTES}}", fuentes_link)
              .replace("{{CSS_BASE}}", base_css)
              .replace("{{CSS_ESTILOS}}", "\n".join(css_estilos))
              .replace("{{SECCIONES}}", secciones)
              .replace("{{TOTAL}}", str(len(datos)))
              .replace("{{INDICE}}", "".join(f'<a class="chip" href="#f-{fid}">{html.escape(nom)}</a>' for fid, (nom, _, t) in tarjetas_por_familia.items() if t))
              .replace("{{CREDITOS}}", " · ".join(f"{k}: {v['autor']}" for k, v in json.loads((AQUI / "fotos" / "creditos.json").read_text(encoding="utf-8")).items()))
              .replace("{{DATOS}}", json.dumps(datos, ensure_ascii=False)))
    salida = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("xsd-trabajo/catalogo/index.html")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(pagina, encoding="utf-8")
    if salida.parent.resolve() != AQUI.resolve():
        shutil.copytree(AQUI / "fotos", salida.parent / "fotos", dirs_exist_ok=True)
    print(f"{salida}: {len(datos)} estilos" + (f"; faltan {', '.join(faltan)}" if faltan else ""))


if __name__ == "__main__":
    main()
