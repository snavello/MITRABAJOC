"""Prepara un recibo o un comprobante para mandarlo a la IA, tapando los
datos que identifican a la persona (PLAN_ENMASCARADO.md, bloque 3).

Es la capa entre la app y los dos módulos del enmascarado: `lectores.py`
saca las palabras con su posición y `enmascarado.py` decide qué se tapa.
Acá se elige el camino (PDF con texto, PDF escaneado, foto), se arma la
imagen que viaja, se rearma después la identidad en lo que devuelve la IA
y se deja el registro. No importa `db`: quien llama registra.

**Mejor esfuerzo** (CLAUDE.md, decisión del 2026-09-24): el objetivo es el
análisis del recibo; tapar es un agregado. Nada de acá puede frenarlo ni
demorarlo más allá del presupuesto de `lectores`: ante cualquier problema
se manda el documento como hoy y queda el motivo en el registro.

Variable `ENMASCARADO`:
- `apagado` (default): no se hace nada; la app queda exactamente como antes.
- `sombra`: se calcula todo y se registra, pero se manda el original. Da los
  números reales (cuántos se habrían tapado, cuántos no y por qué) sin
  cambiarle nada a nadie. Tampoco corta un recibo ajeno: solo lo anota.
- `activo`: se manda la imagen tapada y se rearma la identidad.
"""
from __future__ import annotations

import base64
import io
import os
import re
import time
from dataclasses import dataclass, field

import enmascarado as E
import lectores
from extractor import preparar_imagen

MODOS = ("apagado", "sombra", "activo")
# Una página de PDF con menos palabras que esto es un escaneo: la lee el OCR.
MINIMO_PALABRAS_PDF = 5
# La IA achica internamente lo que pasa de ~1.600 px; mandar más no suma
# lectura y sí peso (el límite de la API es 5 MB por imagen).
LADO_MAXIMO_ENVIO = 3000


def modo() -> str:
    v = (os.getenv("ENMASCARADO") or "apagado").strip().lower()
    return v if v in MODOS else "apagado"


@dataclass
class Preparado:
    """Lo que sale de `preparar()`.

    `imagen`: el (base64, media_type) a mandar, o None para que el extractor
    prepare el archivo como siempre (modo apagado). `tapado`: si lo que viaja
    tiene zonas tapadas (entonces la IA recibe el aviso y hay que rearmar).
    `pertenece`: True / False / None, como `enmascarado.pertenece`.
    `registro`: sin datos personales, para `db.registrar_enmascarado`."""
    modo: str
    imagen: tuple[str, str] | None = None
    tapado: bool = False
    analisis: E.Analisis | None = None
    pertenece: bool | None = None
    registro: dict = field(default_factory=dict)
    # La página tal como se leyó (PIL, derecha y sin tapar). Solo vive en
    # memoria durante el request: la usa el diagnóstico de Pruebas.
    pagina: object = None


def _codificar(img, content_type: str) -> tuple[str, str]:
    lado = max(img.size)
    if lado > LADO_MAXIMO_ENVIO:
        f = LADO_MAXIMO_ENVIO / lado
        img = img.resize((round(img.width * f), round(img.height * f)))
    buf = io.BytesIO()
    if content_type in ("image/jpeg", "image/jpg"):
        img.save(buf, format="JPEG", quality=90)
        media = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        media = "image/png"
    return base64.standard_b64encode(buf.getvalue()).decode(), media


def _leer(contenido: bytes, content_type: str):
    """(imagen PIL de la página que viaja, palabras, camino, LecturaFoto|None)."""
    if content_type == "application/pdf":
        img = lectores.imagen_pdf(contenido, 0)
        palabras = lectores.palabras_pdf(contenido)[0]
        if len(palabras) >= MINIMO_PALABRAS_PDF:
            return img, palabras, "pdf_texto", None
        lectura = lectores.leer_foto(img)
        return img, lectura.palabras, "pdf_imagen", lectura
    if content_type.startswith("image/"):
        img = lectores.abrir_imagen(contenido)
        lectura = lectores.leer_foto(img)
        return img, lectura.palabras, "foto", lectura
    return None, [], "otro", None


def preparar(contenido: bytes, content_type: str, conocidos: E.Conocidos | None = None,
             modo_: str | None = None) -> Preparado:
    """Nunca levanta excepciones por el enmascarado: un archivo que no se
    puede abrir falla recién en el extractor, igual que hoy."""
    m = modo_ or modo()
    if m == "apagado":
        return Preparado(m)
    inicio = time.perf_counter()
    reg = {"modo": m, "camino": "", "motivo": "ok", "cajas": 0, "fugas": 0,
           "espera_ms": 0, "lectura_ms": 0, "total_ms": 0, "cuil_encontrado": None,
           "pertenece": None, "tapado": False}
    prep = Preparado(m, registro=reg)
    try:
        img, palabras, camino, lectura = _leer(contenido, content_type)
        prep.pagina = img
        reg["camino"] = camino
        if lectura is not None:
            reg.update(motivo=lectura.motivo, espera_ms=lectura.espera_ms,
                       lectura_ms=lectura.lectura_ms)
        if camino == "otro":
            reg["motivo"] = "tipo_no_soportado"
        elif reg["motivo"] == "ok" and not palabras:
            reg["motivo"] = "sin_palabras"
        if palabras:
            an = E.analizar(palabras, conocidos)
            prep.analisis = an
            reg["cajas"] = len(an.cajas)
            reg["fugas"] = len(E.control_de_fuga(palabras, an.cajas, conocidos))
            reg["cuil_encontrado"] = an.cuil_sesion_encontrado
            if conocidos and conocidos.cuil:
                prep.pertenece = E.pertenece(an, conocidos.cuil)
                reg["pertenece"] = prep.pertenece
            if m == "activo" and an.cajas:
                prep.imagen = _codificar(E.tapar(img, an.cajas),
                                         "image/png" if content_type == "application/pdf" else content_type)
                prep.tapado = True
                reg["tapado"] = True
    except Exception as e:
        # Mejor esfuerzo: el recibo sigue como hoy. El tipo de error va al
        # registro (sin el mensaje, que podría traer texto del documento).
        reg["motivo"] = f"error:{type(e).__name__}"[:40]
        prep.imagen, prep.tapado, reg["tapado"] = None, False, False
    reg["total_ms"] = int((time.perf_counter() - inicio) * 1000)
    if prep.imagen is None:
        # Sin tapar (sombra, nada que tapar o un problema): viaja el original,
        # preparado EXACTAMENTE como hoy. Si el archivo está roto, que falle en
        # el extractor con su código de siempre, no acá.
        try:
            prep.imagen = preparar_imagen(contenido, content_type)
        except Exception:
            prep.imagen = None
    return prep


# ======================= Diagnóstico (solo Pruebas) =======================
# Pedido de SDN (2026-09-24), TRANSITORIO: para revisar en Pruebas qué se tapó
# de verdad, se guardan la imagen original y la que se mandó a la IA. La
# original tiene datos personales reales, así que esto:
# - solo existe en `local` y `pruebas` (en demo/prod no guarda aunque alguien
#   cargue la variable: lo decide el entorno, no la variable sola);
# - se prende con ENMASCARADO_GUARDAR_IMAGENES=1;
# - vence a los DIAS_IMAGENES días y se borra entera desde la pantalla.
DIAS_IMAGENES = 7
LADO_IMAGEN_DIAGNOSTICO = 1600


def guardar_imagenes_habilitado() -> bool:
    import entorno
    return (os.getenv("ENMASCARADO_GUARDAR_IMAGENES", "").strip() == "1"
            and entorno.ENTORNO in ("local", "pruebas"))


def _jpeg(img) -> bytes:
    img = img.convert("RGB")
    lado = max(img.size)
    if lado > LADO_IMAGEN_DIAGNOSTICO:
        f = LADO_IMAGEN_DIAGNOSTICO / lado
        img = img.resize((round(img.width * f), round(img.height * f)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def imagenes_diagnostico(prep: Preparado, contenido: bytes, content_type: str):
    """(original, enviada) en JPEG, o None. La original es la página tal como
    la vio el lector; la enviada, lo que efectivamente recibió la IA (tapado
    en activo, el original en sombra). Nunca levanta: es diagnóstico."""
    from PIL import Image
    try:
        original = prep.pagina
        if original is None:
            original = (lectores.imagen_pdf(contenido, 0) if content_type == "application/pdf"
                        else lectores.abrir_imagen(contenido))
        if prep.imagen is not None:
            enviada = Image.open(io.BytesIO(base64.b64decode(prep.imagen[0])))
        else:
            enviada = original
        return _jpeg(original), _jpeg(enviada)
    except Exception:
        return None


# ======================= Rearmar la identidad =======================

_OCULTO = re.compile(r"OCULT", re.I)


def _vacio(v) -> bool:
    return v is None or not str(v).strip() or bool(_OCULTO.search(str(v)))


def _textos(an: E.Analisis, tipo: str) -> str:
    """El texto tapado de un tipo, UNA vez: el nombre se repite al pie para
    la firma y la razón social en el logo. Se arma línea por línea y se
    descarta la línea que ya está contenida en otra ("TALLERES METALURGICOS"
    del logo, dentro de "TALLERES METALURGICOS DEL SUR")."""
    lineas: list[list] = []
    for k in an.cajas:                      # ya vienen en orden de lectura
        if k.tipo != tipo:
            continue
        if lineas and lineas[-1][-1].pagina == k.pagina and E._misma_linea(lineas[-1][-1], k):
            lineas[-1].append(k)
        else:
            lineas.append([k])
    textos = [" ".join(k.texto for k in ln).strip(" ,:") for ln in lineas]
    claves = [E._alnum(t) for t in textos]
    quedan = []
    for i, (t, c) in enumerate(zip(textos, claves)):
        if not c or c in claves[:i]:
            continue
        if any(c != o and c in o for o in claves):
            continue
        quedan.append(t)
    return " ".join(quedan).strip(" ,:")


def _cuil_propio_o_valido(an: E.Analisis, conocidos: E.Conocidos | None):
    if conocidos and conocidos.cuil and an.cuil_sesion_encontrado:
        return re.sub(r"\D", "", conocidos.cuil)
    # El primer CUIL de persona leído (sin exigir el módulo 11, que por ahora
    # no se valida: los de la demo no lo cumplen).
    personas = [c for c in an.cuiles if c[:2] in E.PREFIJOS_PERSONA]
    return personas[0] if personas else None


def rearmar_recibo(recibo: dict, an: E.Analisis, conocidos: E.Conocidos | None,
                   razon_por_cuit=None) -> dict:
    """Vuelve a poner en lo que devolvió la IA lo que se le tapó, con lo que
    se leyó ACÁ (el CUIL y el CUIT del documento, no los de la base: con
    pluriempleo el CUIT del empleador guardado puede no ser el del recibo).
    Solo completa campos vacíos o que dicen "OCULTO": lo que la IA leyó bien
    no se toca."""
    emp = recibo.get("empleado")
    if not isinstance(emp, dict):
        emp = recibo["empleado"] = {}
    if _vacio(emp.get("cuil")):
        emp["cuil"] = _cuil_propio_o_valido(an, conocidos)
    if _vacio(emp.get("apellido_nombre")):
        if conocidos and conocidos.nombre and an.nombre_encontrado:
            emp["apellido_nombre"] = conocidos.nombre
        else:
            emp["apellido_nombre"] = _textos(an, "nombre") or None
    if _vacio(emp.get("legajo")):
        emp["legajo"] = _textos(an, "legajo") or None
    empr = recibo.get("empleador")
    if not isinstance(empr, dict):
        empr = recibo["empleador"] = {}
    if _vacio(empr.get("cuit")):
        empr["cuit"] = an.cuits[0] if an.cuits else None
    if _vacio(empr.get("nombre")):
        razon = razon_por_cuit(empr["cuit"]) if (razon_por_cuit and empr.get("cuit")) else None
        empr["nombre"] = razon or _textos(an, "razon_social") or None
    # El rótulo no es una tachadura: si la IA lo marcó como tal, no vale.
    alerta = recibo.get("alerta_adulteracion") or {}
    if alerta.get("detectada") and _OCULTO.search(str(alerta.get("motivo") or "")):
        recibo["alerta_adulteracion"] = {"detectada": False, "motivo": None}
    return recibo


def rearmar_aportes(datos: dict, an: E.Analisis, conocidos: E.Conocidos | None) -> dict:
    if _vacio(datos.get("cuil")):
        datos["cuil"] = _cuil_propio_o_valido(an, conocidos)
    return datos
