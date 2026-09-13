"""Extrae los datos de un recibo (imagen o PDF) usando la Claude API.

Modo simulado para pruebas de carga (`carga/`, ver `carga/README.md`):
con MOCK_EXTRACTOR=1 ninguna de las dos funciones públicas llama a la API
de Anthropic ni decodifica el archivo recibido -- esperan
MOCK_EXTRACTOR_LATENCIA segundos (default 15, la demora típica de la
llamada real) y devuelven un recibo/comprobante de demo fijo. Así el test
de carga ejercita todo el resto del camino (auth, Postgres, validador,
render de plantillas) sin gastar créditos de la API real ni depender de
su latencia variable. NUNCA activar esto en `demo` ni en producción -- es
para el servicio de Pruebas exclusivamente, y a propósito no hay ningún
valor por defecto que lo active solo.
"""
import os
import io
import json
import time
import base64
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")) if os.getenv("MOCK_EXTRACTOR") != "1" else None


def _mock_activo() -> bool:
    return os.getenv("MOCK_EXTRACTOR") == "1"


def _mock_latencia() -> float:
    try:
        return float(os.getenv("MOCK_EXTRACTOR_LATENCIA", "15"))
    except ValueError:
        return 15.0


# Recibo "clásico" de demo, con datos plausibles y autoconsistentes (un
# jubilatorio real haría fallar el validador contra CUALQUIER catálogo real
# si los números no cierran ni remotamente) -- alcanza para ejercitar todo
# el camino de /api/leer sin que la respuesta sea obviamente basura.
_RECIBO_MOCK = {
    "formato": "clasico",
    "empleado": {"apellido_nombre": "Demo Carga, Trabajador", "cuil": None,
                 "legajo": "0000", "categoria": "Administrativo", "fecha_ingreso": "2020-01-01"},
    "empleador": {"nombre": "Empleador de Prueba SA", "cuit": "30000000000"},
    "periodo": "2026-08",
    "fecha_pago": "2026-09-01",
    "lineas": [
        {"codigo": "1", "descripcion": "Sueldo básico", "cantidad": None, "unidad": None,
         "importe": 1000000, "tipo": "remuneracion", "categoria_universal": None},
        {"codigo": "2", "descripcion": "Jubilación", "cantidad": None, "unidad": None,
         "importe": -110000, "tipo": "aporte_trabajador", "categoria_universal": "jubilacion"},
        {"codigo": "3", "descripcion": "Ley 19032/PAMI", "cantidad": None, "unidad": None,
         "importe": -30000, "tipo": "aporte_trabajador", "categoria_universal": "pami"},
        {"codigo": "4", "descripcion": "Obra Social", "cantidad": None, "unidad": None,
         "importe": -30000, "tipo": "aporte_trabajador", "categoria_universal": "obra_social"},
        {"codigo": "5", "descripcion": "Cuota sindical", "cantidad": None, "unidad": None,
         "importe": -20000, "tipo": "aporte_trabajador", "categoria_universal": "cuota_sindical"},
    ],
    "totales_impresos": {"remuneraciones": 1000000, "descuentos": -190000, "neto": 810000},
    "contribuciones_patronales": [],
    "costo_laboral_total": None,
    "ultimo_deposito": {"fecha": "2026-09-05", "periodo": "2026-08", "banco": "Banco de Prueba"},
    "confianza": "alta",
    "observaciones": None,
    "alerta_adulteracion": {"detectada": False, "motivo": None},
}

_APORTES_MOCK = {
    "cuil": None,
    "desde": "10/2025",
    "hasta": "09/2026",
    "meses": [{"periodo": f"{m:02d}/2026" if m <= 9 else f"{m - 9:02d}/2025",
               "jubilacion": "pagado", "obra_social": "pagado"} for m in range(1, 13)],
    "confianza": "alta",
}

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


def _uso(msg, modelo: str, ms: int) -> dict:
    """Tokens de entrada/salida que devuelve la propia respuesta de la API
    (msg.usage) y lo que tardó el pedido, para medir costo real -- no un
    estimado.

    La duración se mide alrededor de la llamada y de nada más: pasar el PDF a
    imagen tarda lo mismo con cualquier modelo, y meterlo adentro haría que
    comparar dos modelos en el banco de pruebas diga cualquier cosa."""
    return {
        "modelo": modelo,
        "tokens_entrada": msg.usage.input_tokens,
        "tokens_salida": msg.usage.output_tokens,
        "duracion_ms": ms,
    }


# Lo que se registra como "modelo" cuando corrió el mock y no la API. No está
# en el catálogo de precios a propósito: una fila así no tiene costo que
# calcular porque no hubo llamada.
MOCK = "mock"

# El modelo por defecto. Plataforma puede elegir otro (db.modelo_ia("recibos"))
# y main se lo pasa a estas dos funciones; el default vive acá, en el código,
# en un solo lugar -- ver precios_ia.USOS.
MODELO = "claude-sonnet-4-6"


def _uso_mock(inicio: float) -> dict:
    """En modo mock no corrió ningún modelo: se registra "mock" y no el que
    se pidió, para que una fila de desarrollo nunca se confunda con gasto
    real (el catálogo no tiene precio para "mock", así que la pantalla
    muestra "—" y no "US$ 0,00").

    La duración va en 0 por lo mismo: lo que tardó es
    MOCK_EXTRACTOR_LATENCIA, un sleep configurado, no una medición. Con el
    mock prendido en Pruebas (ver carga/README.md), registrarla dejaba todas
    las filas en 15,0 s clavados y el tiempo mediano del panel dejaba de
    querer decir algo."""
    return {"modelo": MOCK, "tokens_entrada": 0, "tokens_salida": 0, "duracion_ms": 0}


def extraer(contenido: bytes, content_type: str, modelo: str | None = None) -> tuple[dict, dict]:
    """Devuelve (datos_del_recibo, uso) -- uso trae modelo/tokens_entrada/
    tokens_salida/duracion_ms de esta llamada puntual, para registrar el costo
    real. `modelo` lo decide quien llama; sin él, MODELO."""
    if _mock_activo():
        inicio = time.perf_counter()
        time.sleep(_mock_latencia())
        return json.loads(json.dumps(_RECIBO_MOCK)), _uso_mock(inicio)
    modelo = modelo or MODELO
    if content_type == "application/pdf":
        b64, media = _imagen_desde_pdf(contenido)
    else:
        b64 = base64.standard_b64encode(contenido).decode()
        media = content_type  # image/jpeg, image/png

    inicio = time.perf_counter()
    msg = client.messages.create(
        model=modelo,
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
    return json.loads(texto), _uso(msg, modelo, int((time.perf_counter() - inicio) * 1000))


# ============ Comparar la misma lectura hecha por dos modelos ============
# Vive acá, al lado de los dos ESQUEMA, porque es conocimiento de la FORMA de
# lo que devuelve el modelo: si mañana cambia un campo del esquema, el resumen
# que compara dos lecturas está en la misma pantalla y se actualiza junto.
def _num(x) -> str:
    """1234.5 -> "1.234,50". Devuelve "—" si no hay número: un campo que el
    modelo no leyó no es un cero."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _txt(x) -> str:
    return str(x).strip() if x not in (None, "") else "—"


def resumen_comparable(tipo: str, datos: dict) -> list:
    """[(etiqueta, valor)] con los pocos campos que deciden si dos modelos
    leyeron LO MISMO. No es el recibo entero a propósito: la comparación se
    tiene que poder hacer de un vistazo, y el JSON completo está a un clic en
    el banco de pruebas para cuando dos resúmenes coinciden pero algo huele
    mal."""
    if tipo == "aportes":
        meses = datos.get("meses") or []
        con_problema = sum(1 for m in meses
                           if (m.get("jubilacion") != "pagado" or m.get("obra_social") != "pagado"))
        return [
            ("CUIL", _txt(datos.get("cuil"))),
            ("Desde", _txt(datos.get("desde"))),
            ("Hasta", _txt(datos.get("hasta"))),
            ("Meses leídos", str(len(meses))),
            ("Meses con algo impago", str(con_problema)),
            ("Confianza", _txt(datos.get("confianza"))),
        ]
    empleado = datos.get("empleado") or {}
    empleador = datos.get("empleador") or {}
    totales = datos.get("totales_impresos") or {}
    lineas = datos.get("lineas") or []
    return [
        ("Período", _txt(datos.get("periodo"))),
        ("Formato", _txt(datos.get("formato"))),
        ("CUIL", _txt(empleado.get("cuil"))),
        ("CUIT del empleador", _txt(empleador.get("cuit"))),
        ("Líneas leídas", str(len(lineas))),
        ("Aportes del trabajador", str(sum(1 for l in lineas if l.get("tipo") == "aporte_trabajador"))),
        ("Remuneraciones", _num(totales.get("remuneraciones"))),
        ("Descuentos", _num(totales.get("descuentos"))),
        ("Neto", _num(totales.get("neto"))),
        ("Confianza", _txt(datos.get("confianza"))),
    ]


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


def extraer_aportes(contenido: bytes, content_type: str,
                    modelo: str | None = None) -> tuple[dict, dict]:
    """Lee un comprobante de aportes de ARCA (imagen o PDF) y devuelve
    (estado_mensual, uso) -- mismo criterio que extraer()."""
    if _mock_activo():
        inicio = time.perf_counter()
        time.sleep(_mock_latencia())
        return json.loads(json.dumps(_APORTES_MOCK)), _uso_mock(inicio)
    modelo = modelo or MODELO
    if content_type == "application/pdf":
        b64, media = _imagen_desde_pdf(contenido)
    else:
        b64 = base64.standard_b64encode(contenido).decode()
        media = content_type

    inicio = time.perf_counter()
    msg = client.messages.create(
        model=modelo,
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
    return json.loads(texto), _uso(msg, modelo, int((time.perf_counter() - inicio) * 1000))
