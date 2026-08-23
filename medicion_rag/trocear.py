"""Troceo del convenio por artículo. Script de MEDICIÓN, no del proyecto.

Tres decisiones que salieron de mirar el convenio real de AEFIP:

1. La nota "(Ex - Artículo N ... Acta Acuerdo ...)" se saca del texto que se
   vectoriza y se guarda aparte: son ~116 notas de redacción casi idéntica y
   dentro del embedding harían que el 60% de los artículos se parezcan por su
   boilerplate en vez de por su contenido.

2. Los encabezados de sección ("6) INDEMNIZACION ESPECIAL POR JUBILACION...")
   están escritos ANTES del marcador del artículo al que pertenecen, así que
   un corte ingenuo se los pega al final del artículo anterior. Resultado
   real: el fragmento con más palabras sobre jubilación era el del artículo
   23, que habla de guarderías. Se mueven al fragmento siguiente.

3. Los artículos largos se sub-trocean. Van de 67 a 11.812 caracteres; sin
   sub-trocear, los 29 que superan el límite del modelo se truncan EN
   SILENCIO y se pierde el final sin que nada avise.
"""
import re, json, pathlib
from pypdf import PdfReader

PDF = r"C:\Users\notebook1\Downloads\TEXTO_AFIP_AEFIP.pdf"
SALIDA = pathlib.Path(__file__).parent / "fragmentos.json"

NOTA = re.compile(r"\(Ex\s*-?\s*Art[ií]culo[^)]{0,400}\)", re.S)
ART = re.compile(r"ART[IÍ]CULO\s+(\d+)\s*[:\.]", re.I)
TITULO = re.compile(r"^\s*(TITULO\s+[IVXL]+\s*.*)$", re.M)
# Encabezado en MAYÚSCULAS al final de un bloque: pertenece al artículo que sigue.
COLA_ENCABEZADO = re.compile(r"(?:\d+\s*\)\s*)?[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 ,/\-]{14,}\s*$")

MAX = 1800   # caracteres por fragmento; deja margen bajo el límite del modelo


def limpiar(t):
    t = t.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", t)).strip()


def subtrocear(texto, ref):
    """Parte por párrafo/oración sin cortar a la mitad de una frase."""
    if len(texto) <= MAX:
        return [(ref, texto)]
    piezas, actual = [], ""
    for oracion in re.split(r"(?<=[.;])\s+", texto):
        if len(actual) + len(oracion) + 1 > MAX and actual:
            piezas.append(actual.strip())
            actual = oracion
        else:
            actual = f"{actual} {oracion}".strip()
    if actual.strip():
        piezas.append(actual.strip())
    return [(f"{ref} ({i+1}/{len(piezas)})" if len(piezas) > 1 else ref, p)
            for i, p in enumerate(piezas)]


def trocear():
    r = PdfReader(PDF)
    texto = "\n".join((p.extract_text() or "") for p in r.pages)
    titulos = [(m.start(), " ".join(m.group(1).split())) for m in TITULO.finditer(texto)]

    def titulo_en(pos):
        actual = ""
        for p, t in titulos:
            if p <= pos:
                actual = t
            else:
                break
        return actual

    marcas = list(ART.finditer(texto))
    crudos = []
    for i, m in enumerate(marcas):
        ini = m.start()
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        crudos.append({"num": m.group(1), "pos": ini, "crudo": texto[ini:fin]})

    # (2) mover el encabezado colgado al fragmento siguiente
    for i in range(len(crudos) - 1):
        cuerpo = NOTA.sub("", crudos[i]["crudo"]).rstrip()
        m = COLA_ENCABEZADO.search(cuerpo)
        if m and len(m.group(0).strip()) < 120:
            encabezado = m.group(0).strip()
            crudos[i]["crudo"] = crudos[i]["crudo"].replace(encabezado, "")
            crudos[i + 1]["encabezado"] = encabezado

    frags = []
    for c in crudos:
        notas = [" ".join(n.split()) for n in NOTA.findall(c["crudo"])]
        cuerpo = limpiar(NOTA.sub("", c["crudo"]))
        if c.get("encabezado"):
            cuerpo = f"{c['encabezado']}\n{cuerpo}"
        if len(cuerpo) < 40:
            continue
        for ref, pieza in subtrocear(cuerpo, f"Artículo {c['num']}"):
            frags.append({
                "referencia": ref,
                "articulo": int(c["num"]),
                "titulo": titulo_en(c["pos"]),
                "texto": pieza,
                "notas_acta": notas,
            })
    return frags


if __name__ == "__main__":
    f = trocear()
    SALIDA.write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
    largos = sorted(len(x["texto"]) for x in f)
    print(f"fragmentos: {len(f)}")
    print(f"largo: min {largos[0]}  mediana {largos[len(largos)//2]}  max {largos[-1]}")
    print(f"por encima de {MAX}: {sum(1 for l in largos if l > MAX)}")
    a24 = [x for x in f if x["articulo"] == 24][0]
    print(f"\ncontrol del arreglo (2) -- inicio del Artículo 24:")
    print("  ", " ".join(a24["texto"].split())[:120])
