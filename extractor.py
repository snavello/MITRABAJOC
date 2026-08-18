"""Extrae los datos de un recibo (imagen o PDF) usando la Claude API."""
import os
import io
import json
import base64
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM = (
    "Sos un extractor de datos de recibos de sueldo argentinos. Devolvés "
    "EXCLUSIVAMENTE un objeto JSON válido, sin texto adicional, sin markdown ni "
    "backticks. Transcribí los importes EXACTAMENTE como figuran, con su signo "
    "(los descuentos suelen ser negativos; no cambies signos). No inventes datos: "
    "usá null si algo falta o es ilegible. No calcules nada, solo transcribí lo "
    "impreso. El período va en formato AAAA-MM y el CUIL solo con dígitos. "
    "La fecha_pago es la fecha de cobro o depósito; si no figura, dejala en null. "
    "Incluí siempre CUIL y nombre del empleado, y nombre y CUIT del empleador si figuran. "
    "\n\n"
    "Hay dos formatos de recibo en circulación. El 'clásico' es el tradicional. El "
    "'nuevo' es el Anexo III del Decreto 407/2026 (Ley 27.802) y se reconoce porque "
    "trae una sección separada de 'Costo total empleador' con contribuciones "
    "patronales (ART, Contribución Jubilación, Contribución OO.SS., seguro de vida, "
    "costos derivados del CCT), casi siempre acompañada de un gráfico de torta de "
    "costo total empleador. Si el recibo NO tiene esa sección, es 'clasico'. "
    "\n\n"
    "Distinción crítica, no la confundas: los APORTES DEL TRABAJADOR (jubilación, "
    "obra social, Ley 19.032/PAMI, cuota sindical) se descuentan de SU sueldo bruto y "
    "reducen su neto. Las CONTRIBUCIONES PATRONALES (seguridad social, obra social, "
    "PAMI, ART, seguro de vida, sindical patronal, cámaras) las paga el empleador POR "
    "FUERA del neto del trabajador y nunca se descuentan de su sueldo. Una "
    "contribución patronal jamás va en 'lineas': va exclusivamente en "
    "'contribuciones_patronales'."
)

ESQUEMA = """Extraé los datos con este esquema exacto:
{
  "formato": "clasico",
  "empleado": {"apellido_nombre": null, "cuil": null, "legajo": null, "categoria": null, "fecha_ingreso": null},
  "empleador": {"nombre": null, "cuit": null},
  "periodo": "AAAA-MM",
  "fecha_pago": null,
  "lineas": [{"codigo": null, "descripcion": "", "cantidad": null, "unidad": null, "importe": 0, "tipo": "otro", "categoria_universal": null}],
  "totales_impresos": {"remuneraciones": null, "descuentos": null, "neto": null},
  "contribuciones_patronales": [],
  "costo_laboral_total": null,
  "ultimo_deposito": null,
  "confianza": "alta",
  "observaciones": null,
  "alerta_adulteracion": {"detectada": false, "motivo": null}
}

Reglas para los campos nuevos:
- "formato": "nuevo" SOLO si el recibo trae la sección de contribuciones patronales /
  costo total empleador (Anexo III); en cualquier otro caso, "clasico".
- "lineas[].tipo": para cada línea de haberes o descuentos DEL TRABAJADOR (la sección
  de sueldo bruto y sus descuentos), indicá "remuneracion" (haberes que suman al
  bruto: sueldo básico, presentismo, viáticos, etc.), "aporte_trabajador" (descuentos
  propios del trabajador que reducen su neto: jubilación, obra social, Ley
  19.032/PAMI, cuota sindical) u "otro" (cualquier otra línea: anticipos, embargos,
  ajustes, algo ambiguo).
- "lineas[].categoria_universal": SOLO para líneas con tipo "aporte_trabajador", que
  además reconozcas con confianza como uno de estos 4 aportes de ley (son casi
  iguales en cualquier recibo argentino en blanco, cambia el nombre/código que le
  puso cada empleador, no el concepto):
    "jubilacion"     → aporte jubilatorio / SIPA / Ley 24.241 (normalmente ~11% del
                        básico). Ej: "Jubilación", "Ap. Jubilatorio", "SIPA", "AFJP".
    "pami"           → Ley 19.032 / INSSJP / PAMI (normalmente ~3%). Ej: "Ley 19032",
                        "PAMI", "INSSJP".
    "obra_social"    → aporte a la obra social (normalmente ~3%). Ej: "Obra Social",
                        "Aporte O.S.", "OOSS", el nombre de la obra social del gremio.
    "cuota_sindical" → cuota o aporte al sindicato/gremio. Ej: "Cuota sindical",
                        "Aporte sindical", "Cuota SUTERH", el nombre del gremio.
  Si la línea es un aporte del trabajador pero NO estás seguro de cuál de los 4 es
  (o es un descuento distinto: anticipo, embargo, cuota de préstamo, etc.), dejalo en
  null — mejor no etiquetar que etiquetar mal. Nunca uses estas 4 categorías para una
  contribución patronal (esas van en "contribuciones_patronales", nunca en "lineas").
- "contribuciones_patronales": solo en formato nuevo, una lista de
  {"concepto": null, "base": null, "porcentaje": null, "importe": null} por cada fila
  de la sección "Costo total empleador" (ART, Contribución Jubilación, Contribución
  OO.SS., seguro de vida, costos derivados del CCT, etc.). En esa tabla la columna
  "UNIDAD" es el porcentaje (va en "porcentaje", no en "unidad"). Vacía [] en formato
  clásico. Estos conceptos NUNCA se repiten en "lineas".
- "costo_laboral_total": el total impreso como "Costo total empleador" (formato
  nuevo). null en formato clásico.
- "ultimo_deposito": {"fecha": null, "periodo": null, "banco": null} con la fecha de
  pago de aportes si el recibo la imprime (por ejemplo el campo "F. Pago aportes");
  si no figura, dejalo en null. No depende del formato ni de si aparecen contribuciones.
- "alerta_adulteracion": marcá "detectada": true SOLO si ves señales de edición o
  adulteración física con ALTO grado de certeza (números tachados, corregidos,
  sobreescritos, superpuestos, con typeface/alineación/tamaño inconsistente con el
  resto del documento, borrones, recortes o pegados visibles, etc.) en alguno de
  estos 4 lugares puntuales -- NO revises el resto del recibo:
    1. Los totales (remuneraciones, descuentos, neto).
    2. El CUIL del empleado.
    3. El CUIT del empleador.
    4. Cualquier fecha (período, fecha de pago, fecha de ingreso).
  Si tenés cualquier duda razonable (mala calidad de foto, compresión, reflejo,
  fuente rara pero pareja) NO la marques -- es preferible un falso negativo a
  alarmar sin certeza. Si "detectada" es true, "motivo" es una frase corta y
  concreta de qué campo y qué se ve raro (ej: "el neto tiene un dígito con trazo y
  tamaño distinto al resto del importe"). Si es false, "motivo" queda null."""


def _imagen_desde_pdf(contenido: bytes) -> tuple[str, str]:
    from pdf2image import convert_from_bytes
    paginas = convert_from_bytes(contenido, dpi=150)
    buf = io.BytesIO()
    paginas[0].save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/png"


def _uso(msg, modelo: str) -> dict:
    """Tokens de entrada/salida que devuelve la propia respuesta de la API
    (msg.usage), para medir costo real -- no un estimado."""
    return {
        "modelo": modelo,
        "tokens_entrada": msg.usage.input_tokens,
        "tokens_salida": msg.usage.output_tokens,
    }


MODELO = "claude-sonnet-4-6"


def extraer(contenido: bytes, content_type: str) -> tuple[dict, dict]:
    """Devuelve (datos_del_recibo, uso) -- uso trae modelo/tokens_entrada/
    tokens_salida de esta llamada puntual, para registrar el costo real."""
    if content_type == "application/pdf":
        b64, media = _imagen_desde_pdf(contenido)
    else:
        b64 = base64.standard_b64encode(contenido).decode()
        media = content_type  # image/jpeg, image/png

    msg = client.messages.create(
        model=MODELO,
        max_tokens=2000,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
                {"type": "text", "text": ESQUEMA},
            ],
        }],
    )
    texto = "".join(b.text for b in msg.content if b.type == "text").strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1].removeprefix("json").strip()
    return json.loads(texto), _uso(msg, MODELO)


# ==================== Comprobante de aportes de ARCA ====================
SYSTEM_APORTES = (
    "Sos un extractor de datos del comprobante 'Mis Aportes' de ARCA (ex AFIP) "
    "de Argentina. El comprobante muestra una tabla con el estado de aportes de "
    "los últimos 12 meses. Devolvés EXCLUSIVAMENTE un objeto JSON válido, sin "
    "texto adicional, sin markdown ni backticks. No inventes datos: usá null si "
    "algo falta o es ilegible."
)

ESQUEMA_APORTES = """Extraé el estado de aportes con este esquema exacto:
{
  "cuil": "solo dígitos o con guiones, como figure",
  "desde": "MM/AAAA del primer período",
  "hasta": "MM/AAAA del último período",
  "meses": [
    {"periodo": "MM/AAAA", "jubilacion": "estado", "obra_social": "estado"}
  ],
  "confianza": "alta|media|baja"
}

Para cada mes, el estado de "jubilacion" (aportes de seguridad social) y
"obra_social" (aportes de obra social) debe ser uno de estos valores exactos:
  "pagado"        → si figura PAGO o está en verde
  "parcial"       → si figura PAGO PARCIAL o está en amarillo
  "impago"        → si figura IMPAGO o está en rojo
  "no_presentada" → si figura NO PRESENTADA (el empleador no presentó la DDJJ)
  "no_declarado"  → si figura NO DECLARADO

Algunos comprobantes muestran "INFORMADO" en vez de PAGO -- significa que el
aporte está en regla pero se realiza a una Caja previsional u organismo
provincial en lugar de ARCA (pasa, por ejemplo, con empleados públicos de la
Provincia de Buenos Aires). Si figura "INFORMADO", usá "pagado". Si figura
"NO INFORMADO", usá "impago".

Devolvé los 12 meses en orden. Si la imagen no es un comprobante de aportes
de ARCA, poné confianza en "baja"."""


def extraer_aportes(contenido: bytes, content_type: str) -> tuple[dict, dict]:
    """Lee un comprobante de aportes de ARCA (imagen o PDF) y devuelve
    (estado_mensual, uso) -- mismo criterio que extraer()."""
    if content_type == "application/pdf":
        b64, media = _imagen_desde_pdf(contenido)
    else:
        b64 = base64.standard_b64encode(contenido).decode()
        media = content_type

    msg = client.messages.create(
        model=MODELO,
        max_tokens=2000,
        system=SYSTEM_APORTES,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
                {"type": "text", "text": ESQUEMA_APORTES},
            ],
        }],
    )
    texto = "".join(b.text for b in msg.content if b.type == "text").strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1].removeprefix("json").strip()
    return json.loads(texto), _uso(msg, MODELO)
