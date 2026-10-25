"""XSD (XSANDERS Design Kit): las piezas mecánicas de la auditoría de diseño.

El método está en `METODO.md`, en la carpeta de la skill; esto solo hace lo que no requiere
criterio: capturar, armar la hoja de contacto, renderizar los encargos,
armar el informe, consolidar las decisiones y preparar los encargos de la
siguiente vuelta. El criterio (agrupar, revisar, planificar) lo pone Claude.

Uso (desde la raíz del proyecto):

    python <kit>/herramientas/xsd.py capturar   --ficha F --corrida C [--variantes a,b] [--solo id1,id2] [--quien Q]
    python <kit>/herramientas/xsd.py hoja       --ficha F --corrida C
    python <kit>/herramientas/xsd.py brief      --ficha F --corrida C [--vuelta 2]
    python <kit>/herramientas/xsd.py informe    --ficha F --corrida C [--vuelta 2] [--titulo T]
    python <kit>/herramientas/xsd.py decisiones --ficha F --corrida C --desde DIR
    python <kit>/herramientas/xsd.py previos    --ficha F --corrida C --consolidado X.json
    python <kit>/herramientas/xsd.py encargos   --ficha F --corrida C
    python <kit>/herramientas/xsd.py avance     [--titulo T] [--nota N] [--bloque id=estado:nombre|detalle ...]

Una corrida es una carpeta `<trabajo>/<corrida>/` (la ficha dice dónde está
`trabajo`; no se versiona). Adentro:

    capturas/*.png           lo que sacó capturar.cjs
    grupos.json              {"G1": {"titulo": "...", "pantallas": ["id", ...]}}  (lo escribe Claude)
    hallazgos/<grupo>.json   lo que escribe cada revisor
    previos/<grupo>.json     segunda vuelta: lo que se pidió antes, por grupo
    informe/                 index.html + datos.json + img/ (lo que se publica)
    decisiones/              lo que baja ArtifactData list con out_dir
    consolidado.json         hallazgos + decisión de la persona
    encargos/<grupo>.json    lo aceptado, para el equipo que aplica
"""
import argparse
import glob
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
XSD = AQUI.parent
SEVERIDAD = {"alta": 0, "media": 1, "baja": 2}


# ---------------------------------------------------------------- utilidades
def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _escribir(ruta, datos):
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def _ficha(args):
    ficha = _leer(args.ficha)
    ficha.setdefault("variantes", {"con_variantes": [], "sin_variantes": "base"})
    return ficha


def _corrida(ficha, nombre) -> Path:
    c = Path(ficha["trabajo"]) / nombre
    c.mkdir(parents=True, exist_ok=True)
    return c


def _pantallas(ficha):
    return _leer(ficha["pantallas"])


def _sesiones(ficha, variante, quien, destino: Path) -> Path:
    cmd = ficha["sesiones"]["comando"].format(variante=variante, quien=quien)
    salida = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=False)
    if salida.returncode:
        sys.exit(f"Las sesiones fallaron ({cmd}):\n{salida.stderr}")
    json.loads(salida.stdout)                     # que sea JSON, o que falle acá
    destino.write_text(salida.stdout, encoding="utf-8")
    if salida.stderr.strip():
        print(salida.stderr.strip())
    return destino


# ------------------------------------------------------------------ capturar
def capturar(args):
    ficha = _ficha(args)
    c = _corrida(ficha, args.corrida)
    var = ficha["variantes"]
    variantes = args.variantes.split(",") if args.variantes else var.get("con_variantes", []) + [var["sin_variantes"]]
    nodo = os.environ.get("XSD_NODE", "node")
    for v in variantes:
        ses = _sesiones(ficha, v, args.quien, c / f"sesiones-{args.quien}.json")
        cmd = [nodo, str(AQUI / "capturar.cjs"), args.ficha, v, str(ses), str(c)]
        if args.solo:
            cmd.append(args.solo)
        subprocess.run(cmd, check=True)
        errores = _leer(c / f"errores-{v}.json")
        for e in errores:
            print(f"  ! {v} {e.get('vista')} {e.get('id')}: {e.get('error')}")
    print(f"xsd: capturas en {c / 'capturas'}. Mirá la hoja de contacto antes de seguir (xsd.py hoja).")


# ---------------------------------------------------------------------- hoja
def hoja(args):
    """Todas las miniaturas en una imagen por variante y vista: se ve de un
    vistazo si alguna salió con el login, repetida o en blanco."""
    from PIL import Image, ImageDraw
    ficha = _ficha(args)
    c = _corrida(ficha, args.corrida)
    grupos = {}
    for f in sorted(glob.glob(str(c / "capturas" / "*.png"))):
        variante, vista, _ = Path(f).stem.split("-", 2)
        grupos.setdefault((variante, vista), []).append(f)
    for (variante, vista), archivos in grupos.items():
        ancho, alto, cols = (240, 300, 6) if vista == "d" else (120, 260, 10)
        filas = (len(archivos) + cols - 1) // cols
        lienzo = Image.new("RGB", (cols * ancho, filas * (alto + 18)), "white")
        dib = ImageDraw.Draw(lienzo)
        for i, f in enumerate(archivos):
            im = Image.open(f).convert("RGB")
            im = im.resize((ancho, round(im.height * ancho / im.width))).crop((0, 0, ancho, alto))
            x, y = (i % cols) * ancho, (i // cols) * (alto + 18)
            lienzo.paste(im, (x, y + 18))
            dib.text((x + 3, y + 3), Path(f).stem.split("-", 2)[2][:30], fill="black")
        destino = c / f"hoja-{variante}-{vista}.jpg"
        lienzo.save(destino, "JPEG", quality=70)
        print(f"xsd: {destino} ({len(archivos)} capturas)")


# --------------------------------------------------------------------- brief
def brief(args):
    """Renderiza el encargo de los revisores con los datos de la ficha. Lo que
    queda entre <…> lo completa Claude a mano (pocas cosas)."""
    ficha = _ficha(args)
    c = _corrida(ficha, args.corrida)
    plantilla = XSD / "plantillas" / ("brief_segunda_vuelta.md" if args.vuelta == 2 else "brief_revisor.md")
    contexto = Path(ficha["contexto"]).read_text(encoding="utf-8") if ficha.get("contexto") else "<Qué es la app>"
    var = ficha["variantes"]
    lecturas = "\n".join(f"{i}. `{x}`" for i, x in enumerate(ficha.get("lecturas", []), 1))
    texto = plantilla.read_text(encoding="utf-8")
    for clave, valor in {
        "{SISTEMA}": ficha.get("nombre", ficha["proyecto"]),
        "{CONTEXTO}": contexto.strip(),
        "{LECTURAS}": lecturas or "1. <Reglas de diseño de la casa>",
        "{REFERENCIA}": ficha.get("referencia", ".claude/skills/impeccable"),
        "{CAPTURAS}": str((c / "capturas").resolve()),
        "{CORRIDA}": str(c.resolve()),
        "{IDIOMA}": ficha.get("idioma", "castellano"),
        "{VARIANTES}": ", ".join(var.get("con_variantes", [])) or "no hay",
        "{SIN_VARIANTES}": var.get("sin_variantes", "base"),
        "{VISTAS}": ", ".join(f"{k} = {v['ancho']} px{' a ' + str(v['escala']) + 'x' if v.get('escala') else ''}"
                              for k, v in ficha["vistas"].items()),
        "{BRIEF_ORIGINAL}": str((c / "brief.md").resolve()),
    }.items():
        texto = texto.replace(clave, valor)
    destino = c / ("brief_segunda_vuelta.md" if args.vuelta == 2 else "brief.md")
    destino.write_text(texto, encoding="utf-8")
    print(f"xsd: encargo en {destino}")


# ------------------------------------------------------------------- informe
def _imagenes(c: Path, ids: set) -> dict:
    from PIL import Image
    caps = {}
    (c / "informe" / "img").mkdir(parents=True, exist_ok=True)
    for f in sorted(glob.glob(str(c / "capturas" / "*.png"))):
        nombre = Path(f).stem
        if nombre.split("-", 2)[2] not in ids:
            continue
        im = Image.open(f).convert("RGB")
        ow, oh = im.size
        ancho = 1100 if "-d-" in nombre else 420
        alto = round(oh * ancho / ow)
        im.resize((ancho, alto), Image.LANCZOS).save(c / "informe" / "img" / f"{nombre}.jpg", "JPEG",
                                                     quality=72, optimize=True, progressive=True)
        caps[nombre] = {"archivo": nombre + ".jpg", "ancho": ancho, "alto": alto, "origAncho": ow, "origAlto": oh}
    return caps


def _capturas_de(caps, pid, variantes):
    return [{"modelo": m, "vista": v, **caps[k]} for m in variantes for v in ("d", "m")
            if (k := f"{m}-{v}-{pid}") in caps]


def informe(args):
    ficha = _ficha(args)
    c = _corrida(ficha, args.corrida)
    grupos = _leer(c / "grupos.json")
    todas = {p["id"]: p for p in _pantallas(ficha)}
    ids = [i for g in grupos.values() for i in g["pantallas"]]
    caps = _imagenes(c, set(ids))
    var = ficha["variantes"]
    pantallas, por_id, generales, faltan, cuenta_v = [], {}, [], [], {}
    viejos = {}
    if args.vuelta == 2:
        for f in glob.glob(str(c / "previos" / "*.json")):
            for h in _leer(f).get("hallazgos_anteriores", []):
                viejos[h["id"]] = h
    for pid in ids:
        p = todas[pid]
        variantes = var.get("con_variantes", []) if p.get("temas") else [var["sin_variantes"]]
        q = {"id": pid, "app": p["app"], "nombre": p["nombre"], "url": p["url"],
             "capturas": _capturas_de(caps, pid, variantes),
             "resumen": "", "nota": None, "fortalezas": [], "hallazgos": [], "verificacion": []}
        pantallas.append(q)
        por_id[pid] = q
    for g, info in grupos.items():
        ruta = c / "hallazgos" / f"{g}.json"
        if not ruta.exists():
            faltan.append(g)
            continue
        d = _leer(ruta)
        gen = {"id": "general-" + g.lower(), "app": "Transversales", "nombre": f"{info.get('titulo', g)} ({g})",
               "url": "", "capturas": [], "resumen": "", "nota": None, "fortalezas": [], "hallazgos": [],
               "verificacion": []}
        for pr in d.get("pantallas", []):
            hs = pr.get("hallazgos", [])
            for h in hs:
                cap = (h.get("captura") or "").replace(".png", "")
                h["capturaJpg"] = cap + ".jpg" if cap in caps else None
                z = h.get("zona")
                if z and not (all(isinstance(z.get(k), (int, float)) for k in "xywh") and z.get("w", 0) > 0):
                    h["zona"] = None
            if pr["id"] == "general":
                gen["resumen"] = pr.get("resumen", "")
                for h in hs:
                    cap = (h.get("captura") or "").replace(".png", "")
                    if cap in caps and all(x["archivo"] != caps[cap]["archivo"] for x in gen["capturas"]):
                        m, v = cap.split("-")[0], cap.split("-")[1]
                        gen["capturas"].append({"modelo": m, "vista": v, **caps[cap]})
                gen["hallazgos"].extend(hs)
            elif pr["id"] in por_id:
                q = por_id[pr["id"]]
                q.update(resumen=pr.get("resumen", ""), nota=pr.get("nota"), fortalezas=pr.get("fortalezas", []))
                q["hallazgos"].extend(hs)
            else:
                print(f"  ! {g}: pantalla desconocida {pr['id']}")
        for v in d.get("verificacion", []):
            viejo = viejos.get(v.get("id"), {})
            v["titulo"] = viejo.get("titulo", "")
            res = (v.get("resultado") or "").split(" ")[0]
            cuenta_v[res] = cuenta_v.get(res, 0) + 1
            (por_id.get(viejo.get("pantalla")) or gen)["verificacion"].append(v)
        if gen["hallazgos"] or gen["verificacion"]:
            generales.append(gen)
    for q in pantallas + generales:
        q["hallazgos"].sort(key=lambda h: SEVERIDAD.get(h.get("severidad"), 3))
    total = sum(len(q["hallazgos"]) for q in pantallas + generales)
    nombres = {m: m.capitalize() for m in var.get("con_variantes", [])}
    nombres[var["sin_variantes"]] = "Sin variante"
    nombres["ambos"] = "Todas las variantes"
    sistema = ficha.get("nombre", ficha["proyecto"])
    intro = args.intro or (
        ("Segunda vuelta: en cada pantalla, arriba, está lo que se había pedido y si quedó resuelto; abajo, lo nuevo. "
         if args.vuelta == 2 else "") +
        f"Cada revisor miró sus pantallas de {sistema} en escritorio y teléfono"
        + (f", en {', '.join(nombres[m] for m in var.get('con_variantes', []))}" if var.get("con_variantes") else "")
        + ", contra Impeccable y las reglas de diseño de la casa. Cada hallazgo trae qué pasa, por qué es un problema "
          "y una sugerencia concreta. Para cada uno elegí Aceptar, Dejar como está o Sugerir otro cambio.")
    datos = {"titulo": args.titulo or f"Auditoría de diseño{' · segunda vuelta' if args.vuelta == 2 else ''}",
             "sistema": sistema, "clave": f"xsd-{ficha['proyecto']}-{args.corrida}",
             "subtitulo": args.subtitulo or "escritorio y teléfono · revisado contra Impeccable y las reglas de la casa",
             "variantes": nombres, "intro": intro, "aviso_capturas": ficha.get("aviso_capturas", ""),
             "pantallas": pantallas + generales}
    _escribir(c / "informe" / "datos.json", datos)
    shutil.copy(XSD / "informe" / "index.html", c / "informe" / "index.html")
    archivos = [{"path": "datos.json"}] + [{"path": "img/" + x["archivo"]} for x in caps.values()]
    _escribir(c / "informe" / "archivos.json", archivos)
    print(f"xsd: {len(pantallas)} pantallas, {len(generales)} transversales, {total} hallazgos"
          + (f", verificación {cuenta_v}" if cuenta_v else "") + (f". FALTAN los grupos {faltan}" if faltan else ""))
    print(f"xsd: publicar {c / 'informe' / 'index.html'} con root {c / 'informe'}, files = {c / 'informe' / 'archivos.json'}"
          f" ({len(archivos)} archivos) y capabilities {{\"db\": {{}}, \"user\": {{}}}}")


# ---------------------------------------------------------------- decisiones
def decisiones(args):
    """Junta los hallazgos con lo que decidió la persona en el informe."""
    ficha = _ficha(args)
    c = _corrida(ficha, args.corrida)
    dec = {}
    for f in glob.glob(str(Path(args.desde) / "**" / "*.json"), recursive=True):
        d = _leer(f)
        dec[d.get("id") or Path(f).stem] = d.get("data", d)
    salida, cuenta = [], {}
    for f in sorted(glob.glob(str(c / "hallazgos" / "*.json"))):
        for pr in _leer(f).get("pantallas", []):
            for h in pr.get("hallazgos", []):
                d = dec.get(h["id"], {})
                estado = d.get("estado", "pendiente")
                cuenta[estado] = cuenta.get(estado, 0) + 1
                salida.append({**{k: v for k, v in h.items() if k != "capturaJpg"}, "pantalla": pr["id"],
                               "grupo": Path(f).stem, "estado": estado, "nota": d.get("nota")})
    _escribir(c / "consolidado.json", salida)
    print(f"xsd: {len(salida)} hallazgos en {c / 'consolidado.json'}: {cuenta}")
    for h in salida:
        if h["estado"] == "cambio":
            print(f"  cambio {h['id']} ({h['pantalla']}): {h['nota']}")


# ------------------------------------------------------------------- previos
def previos(args):
    """Segunda vuelta: por grupo, las pantallas y lo que se dijo de ellas
    antes (con la decisión), para que el revisor verifique y no repita."""
    ficha = _ficha(args)
    c = _corrida(ficha, args.corrida)
    grupos = _leer(c / "grupos.json")
    viejos = _leer(args.consolidado)
    todas = {p["id"]: p for p in _pantallas(ficha)}
    for g, info in grupos.items():
        ids = set(info["pantallas"])
        hs = [h for h in viejos if h.get("pantalla") in ids
              or (str(h.get("pantalla", "")).startswith("general") and any(i in json.dumps(h, ensure_ascii=False) for i in ids))]
        _escribir(c / "previos" / f"{g}.json", {"pantallas": [todas[i] for i in info["pantallas"] if i in todas],
                                                 "hallazgos_anteriores": hs})
        print(f"xsd: {g}: {len(ids)} pantallas, {len(hs)} hallazgos anteriores")


# ------------------------------------------------------------------ encargos
def encargos(args):
    """Lo que hay que hacer, por grupo de aplicación: los aceptados y los
    «cambio» (con la nota de la persona), más los parciales de la
    verificación si es una segunda vuelta. Los grupos los define Claude en
    `aplicar.json`: {"empresa": {"hallazgos": ["R1-"], "parciales": ["G1-18"]}}
    (prefijos o ids)."""
    ficha = _ficha(args)
    c = _corrida(ficha, args.corrida)
    plan = _leer(c / "aplicar.json")
    cons = _leer(c / "consolidado.json")
    parciales = {}
    for f in glob.glob(str(c / "hallazgos" / "*.json")):
        for v in _leer(f).get("verificacion", []):
            if not (v.get("resultado") or "").startswith("resuelto"):
                parciales[v["id"]] = v
    for nombre, regla in plan.items():
        hs = [h for h in cons if h["estado"] in ("aceptar", "cambio")
              and any(h["id"].startswith(p) for p in regla.get("hallazgos", []))]
        ps = [parciales[i] for i in regla.get("parciales", []) if i in parciales]
        _escribir(c / "encargos" / f"{nombre}.json", {"hallazgos": hs, "parciales_de_la_vuelta_anterior": ps})
        print(f"xsd: {nombre}: {len(hs)} hallazgos, {len(ps)} parciales")


# -------------------------------------------------------------------- avance
def avance(args):
    """Escribe `xsd-trabajo/avance.json`, que muestra el mod avance-agentes."""
    ruta = Path("xsd-trabajo") / "avance.json"
    datos = _leer(ruta) if ruta.exists() else {"titulo": "XSD", "bloques": []}
    if args.titulo:
        datos["titulo"] = args.titulo
    if args.nota is not None:
        datos["nota"] = args.nota
    for b in args.bloque or []:
        bid, resto = b.split("=", 1)
        estado, _, texto = resto.partition(":")
        nombre, _, detalle = texto.partition("|")
        actual = next((x for x in datos["bloques"] if x["id"] == bid), None)
        if not actual:
            actual = {"id": bid, "nombre": nombre or bid, "estado": "pendiente", "detalle": ""}
            datos["bloques"].append(actual)
        actual["estado"] = estado or actual["estado"]
        if nombre:
            actual["nombre"] = nombre
        if detalle:
            actual["detalle"] = detalle
    datos["actualizado"] = time.strftime("%H:%M")
    _escribir(ruta, datos)
    print(f"xsd: avance en {ruta}")


def main():
    ap = argparse.ArgumentParser(description="XSANDERS Design Kit")
    sub = ap.add_subparsers(dest="orden", required=True)

    def con_ficha(nombre, fn, ayuda):
        p = sub.add_parser(nombre, help=ayuda)
        p.add_argument("--ficha", required=True)
        p.add_argument("--corrida", required=True)
        p.set_defaults(fn=fn)
        return p

    p = con_ficha("capturar", capturar, "sesiones nuevas y capturas de cada variante")
    p.add_argument("--variantes")
    p.add_argument("--solo")
    p.add_argument("--quien", default="principal")
    con_ficha("hoja", hoja, "hoja de contacto de las capturas")
    p = con_ficha("brief", brief, "renderiza el encargo de los revisores")
    p.add_argument("--vuelta", type=int, default=1)
    p = con_ficha("informe", informe, "arma el informe interactivo")
    p.add_argument("--vuelta", type=int, default=1)
    p.add_argument("--titulo")
    p.add_argument("--subtitulo")
    p.add_argument("--intro")
    p = con_ficha("decisiones", decisiones, "junta hallazgos y decisiones")
    p.add_argument("--desde", required=True)
    p = con_ficha("previos", previos, "antecedentes por grupo para la segunda vuelta")
    p.add_argument("--consolidado", required=True)
    con_ficha("encargos", encargos, "encargos para el equipo que aplica")
    p = sub.add_parser("avance", help="actualiza el panel de avance")
    p.add_argument("--titulo")
    p.add_argument("--nota")
    p.add_argument("--bloque", action="append")
    p.set_defaults(fn=avance)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
