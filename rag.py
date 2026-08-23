"""Piloto de consultas sobre el convenio: extracción, troceo y embeddings.

Todo lo que convierte un PDF en fragmentos indexables vive acá. La búsqueda
y la redacción de la respuesta son del bloque 3.

Ver PLAN_RAG_CONVENIO.md para el porqué de cada decisión. Lo que más importa
tener presente al tocar este archivo:

- El modelo y la librería juntos son la identidad del vector. fastembed
  cambió el pooling de e5-large entre versiones: si cambia cualquiera de los
  dos, los vectores guardados dejan de ser comparables con las consultas
  nuevas Y NADA FALLA -- la búsqueda simplemente devuelve cualquier cosa. Por
  eso `db.MODELO_EMBEDDING` incluye la versión de la librería y se guarda en
  cada fragmento.
- Indexar un convenio tarda ~9 minutos (medido). Nada de esto puede correr
  dentro de un request.
"""
import io
import re
import threading

import db

# ---------- Modelo de embeddings ----------
# Se carga UNA vez y queda residente: son ~2,1 GB y 3,3 s de carga. El lock
# evita que dos cargas simultáneas (dos admins subiendo a la vez) dupliquen
# el modelo en memoria, que sería 4,2 GB y muerte por OOM.
_modelo = None
_lock_modelo = threading.Lock()

# e5 se entrenó con estos prefijos y sin ellos pierde calidad de forma
# medible. fastembed los aplica solo si se usan passage_embed/query_embed --
# no `embed()`, que es el error fácil de cometer.
NOMBRE_MODELO = "intfloat/multilingual-e5-large"


def _obtener_modelo():
    global _modelo
    if _modelo is None:
        with _lock_modelo:
            if _modelo is None:            # otro hilo pudo cargarlo mientras esperábamos
                from fastembed import TextEmbedding
                _modelo = TextEmbedding(NOMBRE_MODELO)
    return _modelo


# Lotes chicos a propósito: embeber 246 fragmentos de una sola vez pide
# ~1 GB en un único array y tumba el proceso (medido). El pico de memoria al
# INDEXAR es mayor que el del modelo en reposo.
LOTE = 8


def generar_embeddings(textos: list) -> list:
    """Vectoriza fragmentos de DOCUMENTO (no preguntas). Devuelve listas de
    float, listas para guardar en la columna `vector`."""
    if not textos:
        return []
    m = _obtener_modelo()
    return [v.tolist() for v in m.passage_embed(textos, batch_size=LOTE)]


def generar_embedding_consulta(pregunta: str) -> list:
    """Vectoriza una PREGUNTA. Va por un camino distinto que los documentos:
    e5 es un modelo asimétrico y usa un prefijo diferente para cada lado."""
    m = _obtener_modelo()
    return list(m.query_embed([pregunta]))[0].tolist()


# ---------- Extracción de texto ----------

# Debajo de esto se asume que el PDF es un escaneo y no tiene texto real.
# Un PDF nativo de convenio da miles de caracteres por página (el de AEFIP
# da 3.400); un escaneo da cero o un puñado de basura del encabezado.
MIN_CARACTERES_POR_PAGINA = 200


def extraer_texto(contenido: bytes) -> tuple:
    """Devuelve (texto, paginas, origen). `origen` es "nativo" o "escaneo".

    NO hace OCR: solo detecta que hace falta. Quien llama decide, porque
    OCRear cuesta plata y el admin tiene que poder enterarse antes."""
    from pypdf import PdfReader
    lector = PdfReader(io.BytesIO(contenido))
    paginas = len(lector.pages)
    texto = "\n".join((p.extract_text() or "") for p in lector.pages)
    if paginas and len(texto) / paginas < MIN_CARACTERES_POR_PAGINA:
        return texto, paginas, "escaneo"
    return texto, paginas, "nativo"


# ---------- Troceo ----------
# Los tres arreglos de abajo no son teóricos: salieron de trocear el convenio
# real de AEFIP y ver qué rompía. Ver medicion_rag/.

NOTA_ACTA = re.compile(r"\(Ex\s*-?\s*Art[ií]culo[^)]{0,400}\)", re.S)
MARCA_ARTICULO = re.compile(r"ART[IÍ]CULO\s+(\d+)\s*[:\.]", re.I)
MARCA_TITULO = re.compile(r"^\s*(TITULO\s+[IVXL]+\s*.*)$", re.M)
# Encabezado en mayúsculas al final de un bloque: pertenece al artículo que
# SIGUE, no al que lo precede.
COLA_ENCABEZADO = re.compile(r"(?:\d+\s*\)\s*)?[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 ,/\-]{14,}\s*$")

MAX_FRAGMENTO = 1800   # caracteres; deja margen bajo el límite de tokens


def _normalizar_titulo(t: str) -> str:
    """"TITULO IESTATUTO" -> "TITULO I - ESTATUTO".

    La extracción del PDF pega el número romano con el nombre de la sección
    cuando no hay espacio en el original. Queda feo en la vista previa y, peor,
    entra al texto que se vectoriza como un token basura."""
    t = " ".join(t.split())
    return re.sub(r"^(TITULO\s+[IVXL]+)\s*[-–]?\s*(?=[A-ZÁÉÍÓÚÑ])", r"\g<1> - ", t)


def _limpiar(t: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", t.replace("\xa0", " "))).strip()


def _subtrocear(texto: str, ref: str) -> list:
    """Parte los artículos largos sin cortar a la mitad de una oración.

    Sin esto, los artículos que superan el límite del modelo se truncan EN
    SILENCIO: el final se pierde y nada avisa. En el convenio de AEFIP eran
    29 de 174, y el más largo tenía 11.812 caracteres."""
    if len(texto) <= MAX_FRAGMENTO:
        return [(ref, texto)]
    piezas, actual = [], ""
    for oracion in re.split(r"(?<=[.;])\s+", texto):
        if len(actual) + len(oracion) + 1 > MAX_FRAGMENTO and actual:
            piezas.append(actual.strip())
            actual = oracion
        else:
            actual = f"{actual} {oracion}".strip()
    if actual.strip():
        piezas.append(actual.strip())
    return [(f"{ref} ({i+1}/{len(piezas)})" if len(piezas) > 1 else ref, p)
            for i, p in enumerate(piezas)]


def trocear(texto: str) -> list:
    """Parte el convenio en fragmentos por artículo.

    Devuelve dicts con: referencia, seccion, texto, notas_acta.

    Si el texto no tiene marcadores de artículo reconocibles (un acta suelta,
    por ejemplo), cae a un troceo por tamaño -- vale más un troceo tosco que
    ningún fragmento."""
    titulos = [(m.start(), _normalizar_titulo(m.group(1))) for m in MARCA_TITULO.finditer(texto)]

    def seccion_en(pos):
        actual = ""
        for p, t in titulos:
            if p <= pos:
                actual = t
            else:
                break
        return actual

    marcas = list(MARCA_ARTICULO.finditer(texto))
    if not marcas:
        return _trocear_sin_articulos(texto)

    crudos = []
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        crudos.append({"num": m.group(1), "pos": m.start(), "crudo": texto[m.start():fin]})

    # Encabezado colgado -> al fragmento siguiente. Caso real: "6)
    # INDEMNIZACIÓN ESPECIAL POR JUBILACIÓN" quedaba al final del artículo 23,
    # que habla de guarderías, y la búsqueda de jubilación traía ese.
    for i in range(len(crudos) - 1):
        cuerpo = NOTA_ACTA.sub("", crudos[i]["crudo"]).rstrip()
        m = COLA_ENCABEZADO.search(cuerpo)
        if m and len(m.group(0).strip()) < 120:
            encabezado = m.group(0).strip()
            crudos[i]["crudo"] = crudos[i]["crudo"].replace(encabezado, "")
            crudos[i + 1]["encabezado"] = encabezado

    frags = []
    for c in crudos:
        # Las notas de acta salen del texto que se vectoriza: son ~116 con
        # redacción casi idéntica y adentro harían que el 60% de los
        # artículos se parezcan por su boilerplate en vez de su contenido.
        notas = " | ".join(" ".join(n.split()) for n in NOTA_ACTA.findall(c["crudo"]))
        cuerpo = _limpiar(NOTA_ACTA.sub("", c["crudo"]))
        if c.get("encabezado"):
            cuerpo = f"{c['encabezado']}\n{cuerpo}"
        if len(cuerpo) < 40:               # marcas sueltas, referencias cruzadas
            continue
        for ref, pieza in _subtrocear(cuerpo, f"Artículo {c['num']}"):
            frags.append({"referencia": ref, "seccion": seccion_en(c["pos"]),
                          "texto": pieza, "notas_acta": notas})
    return frags


def _trocear_sin_articulos(texto: str) -> list:
    limpio = _limpiar(texto)
    piezas = _subtrocear(limpio, "Fragmento") if limpio else []
    return [{"referencia": f"Fragmento {i+1}", "seccion": "", "texto": p, "notas_acta": ""}
            for i, (_, p) in enumerate(piezas)]


def texto_a_embeber(fragmento: dict) -> str:
    """Lo que efectivamente se vectoriza. La sección da contexto -- un
    artículo suelto no dice si habla de licencias o de retribuciones."""
    seccion = fragmento.get("seccion") or ""
    return f"{seccion}\n{fragmento['texto']}".strip()


# ---------- Costo estimado del OCR ----------
# El OCR reusa pdf2image + visión de extractor.py, así que cuesta por página.
# El admin tiene que poder enterarse ANTES de disparar el proceso.
COSTO_APROX_POR_PAGINA_USD = 0.012


def costo_ocr_estimado(paginas: int) -> float:
    return round(paginas * COSTO_APROX_POR_PAGINA_USD, 2)


# ---------- Indexación en segundo plano ----------
# Indexar un convenio tarda ~9 minutos. No corre en el request: corre en un
# hilo que va dejando el progreso en el documento, y el panel lo consulta.

# Un solo lote de indexación a la vez por proceso. Dos convenios en paralelo
# duplican el pico de memoria (que ya es ~1 GB) y compiten por la misma CPU:
# tardarían el doble cada uno sin ganar nada.
_lock_indexacion = threading.Lock()


def _ocr_con_claude(contenido: bytes, paginas: int) -> str:
    """OCR reusando pdf2image + visión, que el proyecto ya tiene funcionando
    en extractor.py. Es más caro que un OCR clásico pero mucho mejor sobre
    texto jurídico, y no suma dependencias de sistema al despliegue."""
    from pdf2image import convert_from_bytes
    import base64
    from extractor import client, MODELO

    partes = []
    imagenes = convert_from_bytes(contenido, dpi=200)
    for i, img in enumerate(imagenes):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode()
        msg = client.messages.create(
            model=MODELO, max_tokens=8000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png", "data": b64}},
                {"type": "text", "text":
                 "Transcribí TODO el texto de esta página tal cual está, sin resumir, "
                 "sin corregir y sin agregar comentarios. Respetá los números de "
                 "artículo y la numeración. Si la página está en blanco, respondé vacío."},
            ]}])
        partes.append("".join(b.text for b in msg.content if b.type == "text"))
    return "\n".join(partes)


def indexar_documento(documento_id: int, permitir_ocr: bool = True) -> dict:
    """Extrae, trocea, vectoriza y guarda. Devuelve un resumen.

    Pensada para correr en un hilo. Deja el estado en el documento pase lo
    que pase: si revienta a la mitad, el admin tiene que ver "error" y el
    motivo, no un documento en "procesando" para siempre."""
    doc = db.documento_para_indexar(documento_id)
    if not doc:
        return {"ok": False, "error": "documento inexistente"}

    with _lock_indexacion:
        try:
            db.set_estado_documento(documento_id, "procesando", fragmentos=0, error="")
            # Reindexar es rehacer: si había fragmentos de una corrida previa
            # se borran, o quedarían duplicados con los nuevos.
            db.borrar_fragmentos_de_documento(documento_id)

            texto, paginas, origen = extraer_texto(doc["archivo_datos"])
            if origen == "escaneo":
                if not permitir_ocr:
                    db.set_estado_documento(
                        documento_id, "error", paginas=paginas, caracteres=len(texto),
                        origen_texto="escaneo",
                        error="El PDF no tiene texto extraíble (parece un escaneo). "
                              "Hay que confirmar el OCR para procesarlo.")
                    return {"ok": False, "error": "escaneo sin OCR confirmado",
                            "paginas": paginas}
                texto = _ocr_con_claude(doc["archivo_datos"], paginas)
                origen = "ocr"

            fragmentos = trocear(texto)

            # Las observaciones del admin se indexan como fuente propia: están
            # en lenguaje llano, más parecido a cómo pregunta un trabajador
            # que el articulado formal.
            observacion = None
            if (doc.get("observaciones") or "").strip():
                observacion = {
                    "referencia": f"Observación del sindicato — {doc['titulo'] or doc['tipo']}",
                    "seccion": "", "texto": doc["observaciones"].strip(), "notas_acta": "",
                }

            if not fragmentos and not observacion:
                db.set_estado_documento(
                    documento_id, "error", paginas=paginas, caracteres=len(texto),
                    origen_texto=origen,
                    error="No se pudo extraer ningún fragmento del documento.")
                return {"ok": False, "error": "sin fragmentos"}

            db.set_estado_documento(documento_id, "procesando", paginas=paginas,
                                    caracteres=len(texto), origen_texto=origen)

            # De a lotes, guardando después de cada uno: si el proceso se cae
            # a los 7 minutos no se pierde todo, y el admin ve avanzar el
            # contador en vez de un cartel congelado.
            guardados = 0
            for i in range(0, len(fragmentos), LOTE):
                lote = fragmentos[i:i + LOTE]
                vectores = generar_embeddings([texto_a_embeber(f) for f in lote])
                guardados += db.guardar_fragmentos(
                    documento_id, doc["convenio_id"], doc["sindicato_id"],
                    lote, vectores, tipo_fuente=doc["tipo"], desde_orden=guardados)
                db.set_estado_documento(documento_id, "procesando", fragmentos=guardados)

            if observacion:
                vec = generar_embeddings([observacion["texto"]])
                guardados += db.guardar_fragmentos(
                    documento_id, doc["convenio_id"], doc["sindicato_id"],
                    [observacion], vec, tipo_fuente="observacion", desde_orden=guardados)

            db.set_estado_documento(documento_id, "listo", fragmentos=guardados, error="")
            return {"ok": True, "fragmentos": guardados, "origen": origen, "paginas": paginas}

        except Exception as e:            # el hilo no puede propagar: se deja el motivo
            db.set_estado_documento(documento_id, "error", error=f"{type(e).__name__}: {e}")
            return {"ok": False, "error": str(e)}


def indexar_en_segundo_plano(documento_id: int, permitir_ocr: bool = True) -> None:
    """Dispara la indexación y vuelve enseguida. daemon=True para que un
    reinicio del servidor no quede esperando al hilo."""
    threading.Thread(target=indexar_documento, args=(documento_id, permitir_ocr),
                     daemon=True).start()
