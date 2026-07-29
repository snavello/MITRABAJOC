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
    "Incluí siempre CUIL y nombre del empleado, y nombre y CUIT del empleador si figuran."
)

ESQUEMA = """Extraé los datos con este esquema exacto:
{
  "empleado": {"apellido_nombre": null, "cuil": null, "legajo": null, "categoria": null, "fecha_ingreso": null},
  "empleador": {"nombre": null, "cuit": null},
  "periodo": "AAAA-MM",
  "fecha_pago": null,
  "lineas": [{"codigo": null, "descripcion": "", "cantidad": null, "unidad": null, "importe": 0}],
  "totales_impresos": {"remuneraciones": null, "descuentos": null, "neto": null},
  "confianza": "alta",
  "observaciones": null
}"""


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
