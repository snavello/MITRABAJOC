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
  "lineas": [{"codigo": null, "descripcion": "", "cantidad": null, "unidad": null, "importe": 0, "tipo": "otro"}],
  "totales_impresos": {"remuneraciones": null, "descuentos": null, "neto": null},
  "contribuciones_patronales": [],
  "costo_laboral_total": null,
  "ultimo_deposito": null,
  "confianza": "alta",
  "observaciones": null
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
  si no figura, dejalo en null. No depende del formato ni de si aparecen contribuciones."""


def _imagen_desde_pdf(contenido: bytes) -> tuple[str, str]:
    from pdf2image import convert_from_bytes
    paginas = convert_from_bytes(contenido, dpi=150)
    buf = io.BytesIO()
    paginas[0].save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/png"


def extraer(contenido: bytes, content_type: str) -> dict:
    if content_type == "application/pdf":
        b64, media = _imagen_desde_pdf(contenido)
    else:
        b64 = base64.standard_b64encode(contenido).decode()
        media = content_type  # image/jpeg, image/png

    msg = client.messages.create(
        model="claude-sonnet-4-6",
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
    return json.loads(texto)


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

Devolvé los 12 meses en orden. Si la imagen no es un comprobante de aportes
de ARCA, poné confianza en "baja"."""


def extraer_aportes(contenido: bytes, content_type: str) -> dict:
    """Lee un comprobante de aportes de ARCA (imagen o PDF) y devuelve el estado mensual."""
    if content_type == "application/pdf":
        b64, media = _imagen_desde_pdf(contenido)
    else:
        b64 = base64.standard_b64encode(contenido).decode()
        media = content_type

    msg = client.messages.create(
        model="claude-sonnet-4-6",
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
    return json.loads(texto)
