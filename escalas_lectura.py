# -*- coding: utf-8 -*-
"""La lectura de la grilla salarial: PDF escaneado -> imágenes -> la IA ->
el JSON con el formato EXACTO de `data/grillas_bancarias/AAAA-MM.json`
(PLAN_CONVENIO_ESCALAS.md, D9.2 y D18).

Cómo se arma (decisiones de este módulo, ver el reporte del bloque 5):

- **Una llamada por sección, con TODAS las páginas**: las tres ramas
  (administrativa, maestranza, ordenanza) y «el resto» (adicionales,
  conectividad, ROE, Día del Bancario y el período impreso). Una grilla son 8
  páginas de cifras: pedirla entera en una sola llamada mide ~6.000 tokens de
  salida y mezcla tablas parecidas (las del Día del Bancario repiten las
  mismas categorías y coeficientes con otros importes); por sección la salida
  es chica y cada llamada tiene una sola tarea. El costo en tokens de
  entrada, ~25.000 por llamada, es de centavos.
- **Se lee DOS veces**, en llamadas independientes (ninguna ve a la otra); que
  las dos coincidan celda por celda es el control C2.
- **La IA recibe la grilla vigente como plantilla de ESTRUCTURA, sin sus
  importes**: solo los nombres de las categorías en orden y las claves de los
  adicionales, para que escriba cada nombre igual que el sistema. Los
  coeficientes y los importes los lee del documento: nunca se le dan.
- **Nunca completa un importe que no leyó**: el esquema acepta `null` en cada
  celda y el prompt lo pide ante la duda; un valor que no es número se
  convierte en `null` y queda anotado.
- Salida estructurada por una herramienta de esquema cerrado (mismo patrón
  que `asistente_tramites_ia`), el modelo de `db.modelo_ia("grilla_salarial")`
  (default `MODELO`, elegible en /plataforma), `effort: low` si razona
  (`extractor.MODELOS_QUE_RAZONAN`), tope de salida `MAX_TOKENS`.
- Cliente inyectable (`usar_cliente`) para probarlo sin gastar créditos; con
  `MOCK_EXTRACTOR=1` NO llama a la API (`disponible()` lo dice).
- Sin `db`: quien llama registra el consumo (`usos`, un dict por llamada).
"""
import base64
import copy
import io
import os
import time

import extractor
import lectores

# El DEFAULT del uso de IA «grilla_salarial» (precios_ia.USOS). Plataforma
# puede elegir otro en /plataforma → Uso de IA → Modelos.
MODELO = "claude-sonnet-5-5"
MAX_TOKENS = 8000
TIMEOUT_LLAMADA_S = 180
SECCIONES = ("administrativa", "maestranza", "ordenanza", "resto")

_cliente = None


class ErrorLectura(Exception):
    """La lectura no se pudo hacer o no se pudo interpretar. Lleva en `usos` lo
    que ya se gastó (esas llamadas se pagaron aunque fallen)."""

    def __init__(self, mensaje: str, usos: list | None = None):
        super().__init__(mensaje)
        self.usos = usos or []


def usar_cliente(cliente) -> None:
    global _cliente
    _cliente = cliente


def cliente():
    global _cliente
    if _cliente is None and os.getenv("ANTHROPIC_API_KEY"):
        from anthropic import Anthropic
        _cliente = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _cliente


def disponible() -> tuple:
    """(se puede leer, motivo si no). Con MOCK_EXTRACTOR=1 no se llama a la API
    y no se inventa una lectura."""
    if os.getenv("MOCK_EXTRACTOR") == "1":
        return False, "MOCK_EXTRACTOR=1: no se llama a la API de Anthropic"
    if cliente() is None:
        return False, "no hay ANTHROPIC_API_KEY ni cliente configurado"
    return True, ""


# ---------------------------------------------------------------- imágenes
def paginas_a_imagenes(pdf: bytes) -> list:
    """Cada página del PDF como [(base64, media_type)], con el tope de 2.000 px
    de lado de `lectores.imagenes_pdf`. Se prepara UNA vez y las ocho llamadas
    comparten las mismas cadenas."""
    salida = []
    for im in lectores.imagenes_pdf(pdf):
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        salida.append((base64.standard_b64encode(buf.getbuffer()).decode(), "image/png"))
    if not salida:
        raise ErrorLectura("el PDF no tiene páginas")
    return salida


# ---------------------------------------------------------------- esquemas
def _numero() -> dict:
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _entero() -> dict:
    return {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def _objeto(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def herramienta_rama(nombre_rama: str) -> dict:
    cat = _objeto({
        "nombre": {"type": "string", "description": "Nombre de la categoría, escrito como en la lista esperada."},
        "anios": {**_entero(), "description": "Años de antigüedad de la categoría (0 para Inicial); null en una jerarquía."},
        "coef": {**_numero(), "description": "Columna Coef (por ejemplo 1,04 -> 1.04)."},
        "basico": {**_numero(), "description": "Columna Básico del mes (1.673.913,51 -> 1673913.51)."},
        "conformado": {**_numero(), "description": "Columna Conformado del mes; null si la categoría no tiene."},
    })
    return {
        "name": "registrar_rama",
        "description": f"Registra la tabla de la rama {nombre_rama}: una fila por categoría, en el orden del documento.",
        "strict": True,
        "input_schema": _objeto({
            "categorias": {"type": "array", "items": cat},
            "notas": {"type": "array", "items": {"type": "string"},
                      "description": "Diferencias con la lista esperada (una categoría que falta o sobra, algo ilegible). Vacío si no hay."},
        }),
    }


def herramienta_resto(plantilla: dict) -> dict:
    adic = plantilla["adicionales"]
    adic_props = {k: _numero() for k, v in adic.items() if not isinstance(v, dict)}
    for k, v in adic.items():
        if isinstance(v, dict):
            adic_props[k] = _objeto({k2: _numero() for k2 in v})
    n_tramos = len(plantilla["roe"]["tramos"])
    return {
        "name": "registrar_resto",
        "description": "Registra los adicionales, la conectividad, el ROE, el Día del Bancario y el período impreso.",
        "strict": True,
        "input_schema": _objeto({
            "periodo_impreso": {"anyOf": [{"type": "string"}, {"type": "null"}],
                                "description": "Mes y año que dicen los encabezados de las tablas, como AAAA-MM (Septiembre 2026 -> 2026-09); null si no se lee."},
            "adicionales": _objeto(adic_props),
            "conectividad": {"type": "array", "items": _objeto({
                "meses": {"type": "array", "items": {"type": "string"}, "description": "Los meses que cubre, como AAAA-MM."},
                "diario": _numero(), "mas_de_4_dias": _numero(), "mensual": _numero()})},
            "roe": _objeto({
                "tramos": {"type": "array", "items": {"type": "string"},
                           "description": f"Los {n_tramos} tramos de ROE del banco, como figuran en el encabezado."},
                "filas": {"type": "array", "items": _objeto({
                    "hasta": {**_numero(), "description": "Tope del tramo de sueldo bruto de la fila; null en la última («más de»)."},
                    "anual": {"type": "array", "items": _numero(), "description": "Un monto ANUAL por tramo de ROE, en orden; 0 en el primero."}})}}),
            "dia_bancario": _objeto({
                "suma_fija": {**_numero(), "description": "Columna Suma Fija (igual en todas las filas)."},
                "por_coeficiente": {**_numero(), "description": "Columna Monto Coeficiente de la fila Inicial (coef 1,00)."},
                "minimo": {**_numero(), "description": "Columna Total de la fila Inicial (coef 1,00)."}}),
            "notas": {"type": "array", "items": {"type": "string"},
                      "description": "Diferencias con lo esperado o algo ilegible. Vacío si no hay."},
        }),
    }


# ---------------------------------------------------------------- prompts
SISTEMA = (
    "Sos un transcriptor de tablas salariales escaneadas de la Asociación Bancaria (CCT 18/75, Argentina). "
    "Recibís las páginas escaneadas de las GRILLAS SALARIALES de un mes y llamás a la herramienta indicada UNA vez. "
    "Transcribí EXACTAMENTE lo impreso, dígito por dígito: los importes están en formato argentino "
    "('$ 1.673.913,51' es 1673913.51; '1,04' es 1.04). No calcules, no promedies, no corrijas, no estimes. "
    "Hay firmas, sellos y manchas encima de algunas filas: si un número no se lee con certeza, devolvé null en esa "
    "celda; NUNCA lo completes por deducción ni por parecido con otra fila. "
    "Las tablas del «Día del Bancario» repiten las mismas categorías y coeficientes con otros importes (suma fija, "
    "monto por coeficiente, total): NO son básicos ni conformados."
)


def prompt_rama(clave: str, plantilla: dict) -> str:
    r = plantilla["ramas"][clave]
    filas = "\n".join(f"{i + 1}. {c['nombre']} (años: {c.get('anios') if c.get('anios') is not None else 'jerarquía, null'})"
                      for i, c in enumerate(r["categorias"]))
    return (f"Transcribí SOLO la rama {r['nombre'].upper()}: la tabla con las columnas Coef, Básico y Conformado del mes "
            f"(ignorá las tablas del Día del Bancario). Una fila por categoría, en este orden y con estos nombres exactos "
            f"(en el documento pueden estar abreviados o con otra ortografía; usá el nombre de la lista):\n{filas}\n\n"
            "Si el documento trae una categoría que no está en la lista, o falta una de la lista, no la inventes ni la "
            "completes: agregala u omitila y describilo en notas. El Conformado solo existe en algunas categorías: "
            "donde la celda está vacía, null.")


def prompt_resto(plantilla: dict) -> str:
    adic = plantilla["adicionales"]
    lista = []
    for k, v in adic.items():
        lista.append(f"- {k}" + (f": " + ", ".join(v) if isinstance(v, dict) else ""))
    tramos = "; ".join(plantilla["roe"]["tramos"])
    return ("Transcribí, de las mismas páginas: (1) el mes y año que dicen los encabezados de las tablas; "
            "(2) los ADICIONALES, importes mensuales fijos:\n" + "\n".join(lista) + "\n"
            "(3) la CONECTIVIDAD: una entrada por trimestre con sus meses (AAAA-MM), importe diario, más de 4 días y mensual; "
            f"(4) el ROE: una fila por tramo de sueldo bruto (con su tope «hasta»; null en la última) y, por cada tramo de "
            f"ROE del banco ({tramos}), el monto ANUAL; el primer tramo es 0; "
            "(5) el DÍA DEL BANCARIO: la suma fija, el monto por coeficiente y el total de la fila Inicial (coef 1,00). "
            "Si algo de esta lista no aparece en el documento, null (o lista vacía), y anotalo en notas.")


# ---------------------------------------------------------------- llamada
def _llamar(cli, modelo: str, imagenes: list, instruccion: str, herramienta: dict):
    contenido = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for d, m in imagenes]
    # La herramienta NO se fuerza con tool_choice "any"/"tool": Sonnet 5.5 (el
    # default), Opus 5.5 y Fable 5.x lo rechazan con un 400. Va "auto" + esquema
    # estricto + la instrucción de llamarla; si el modelo contesta en texto, la
    # lectura falla ("no devolvió la tabla") y no se toma nada.
    contenido.append({"type": "text", "text": instruccion + (
        f"\n\nDevolvé el resultado llamando a la herramienta `{herramienta['name']}`, una sola vez. "
        "No respondas en texto.")})
    opciones = extractor._opciones(modelo)
    inicio = time.perf_counter()
    try:
        msg = cli.messages.create(
            model=modelo, max_tokens=MAX_TOKENS, system=SISTEMA, timeout=TIMEOUT_LLAMADA_S,
            tools=[herramienta], tool_choice={"type": "auto"}, **opciones,
            messages=[{"role": "user", "content": contenido}])
    except Exception as e:                      # red, cuota, 4xx/5xx: se informa, no se esconde
        raise ErrorLectura(f"la API de Anthropic falló ({type(e).__name__}: {e})") from e
    ms = int((time.perf_counter() - inicio) * 1000)
    u = getattr(msg, "usage", None)
    uso = {"modelo": modelo, "tokens_entrada": extractor._entero(getattr(u, "input_tokens", 0)),
           "tokens_salida": extractor._entero(getattr(u, "output_tokens", 0)),
           "tokens_cache_lectura": extractor._entero(getattr(u, "cache_read_input_tokens", 0)),
           "tokens_cache_escritura": extractor._entero(getattr(u, "cache_creation_input_tokens", 0)),
           "duracion_ms": ms}
    parada = getattr(msg, "stop_reason", None)
    if parada == "refusal":
        raise ErrorLectura("el modelo declinó leer el documento", [uso])
    if parada == "max_tokens":
        raise ErrorLectura(f"la respuesta se cortó en el tope de {MAX_TOKENS} tokens de salida", [uso])
    bloques = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
    if not bloques or not isinstance(bloques[0].input, dict):
        raise ErrorLectura("el modelo no devolvió la tabla", [uso])
    return bloques[0].input, uso


# ---------------------------------------------------------------- saneo
def _n(x, notas: list, donde: str):
    """Un número redondeado a centavos, o None (y una nota) si no es número."""
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        notas.append(f"valor no numérico en {donde}: {x!r}")
        return None
    return round(float(x), 2)


def _entero_o_none(x, notas, donde):
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or int(x) != x:
        notas.append(f"valor no entero en {donde}: {x!r}")
        return None
    return int(x)


def sanear_rama(crudo: dict, clave: str, plantilla: dict, notas: list) -> dict:
    r = plantilla["ramas"][clave]
    cats = []
    for i, c in enumerate(crudo.get("categorias") or []):
        if not isinstance(c, dict):
            notas.append(f"{clave}: fila {i + 1} ilegible")
            continue
        et = f"{clave}/{c.get('nombre')}"
        cats.append({"nombre": str(c.get("nombre") or "").strip(), "anios": _entero_o_none(c.get("anios"), notas, et),
                     "coef": _n(c.get("coef"), notas, et), "basico": _n(c.get("basico"), notas, et),
                     "conformado": _n(c.get("conformado"), notas, et)})
    notas.extend(str(n) for n in (crudo.get("notas") or []))
    return {"nombre": r["nombre"], "categorias": cats}


def sanear_resto(crudo: dict, notas: list) -> dict:
    adic_crudo = crudo.get("adicionales") or {}
    adic = {}
    for k, v in adic_crudo.items():
        adic[k] = ({k2: _n(v2, notas, f"adicionales/{k}/{k2}") for k2, v2 in v.items()}
                   if isinstance(v, dict) else _n(v, notas, f"adicionales/{k}"))
    conect = []
    for c in crudo.get("conectividad") or []:
        conect.append({"meses": [str(m) for m in (c.get("meses") or [])],
                       "diario": _n(c.get("diario"), notas, "conectividad"),
                       "mas_de_4_dias": _n(c.get("mas_de_4_dias"), notas, "conectividad"),
                       "mensual": _n(c.get("mensual"), notas, "conectividad")})
    roe_c = crudo.get("roe") or {}
    roe = {"tramos": [str(t) for t in (roe_c.get("tramos") or [])],
           "filas": [{"hasta": (None if f.get("hasta") is None else int(_n(f.get("hasta"), notas, "roe/hasta") or 0) or None),
                      "anual": [_n(x, notas, "roe/anual") for x in (f.get("anual") or [])]}
                     for f in (roe_c.get("filas") or []) if isinstance(f, dict)]}
    db_c = crudo.get("dia_bancario") or {}
    dia = {k: _n(db_c.get(k), notas, f"dia_bancario/{k}") for k in ("suma_fija", "por_coeficiente", "minimo")}
    notas.extend(str(n) for n in (crudo.get("notas") or []))
    periodo = crudo.get("periodo_impreso")
    return {"adicionales": adic, "conectividad": conect, "roe": roe, "dia_bancario": dia,
            "periodo_impreso": periodo if isinstance(periodo, str) and len(periodo) == 7 else None}


# ---------------------------------------------------------------- lectura
def leer_una_vez(imagenes: list, plantilla: dict, modelo: str, secciones: tuple = SECCIONES) -> dict:
    """UNA lectura completa del documento (una llamada por sección). Devuelve
    {"contenido": {ramas, adicionales, conectividad, roe, dia_bancario},
    "notas": [...], "periodo_impreso": ..., "usos": [...]} o levanta
    ErrorLectura con lo gastado hasta el momento."""
    cli = cliente()
    if cli is None:
        raise ErrorLectura("no hay cliente de Anthropic configurado")
    plantilla = copy.deepcopy(plantilla)
    usos, notas = [], []
    ramas, resto = {}, None
    for sec in secciones:
        try:
            if sec == "resto":
                crudo, uso = _llamar(cli, modelo, imagenes, prompt_resto(plantilla), herramienta_resto(plantilla))
                usos.append(uso)
                resto = sanear_resto(crudo, notas)
            else:
                crudo, uso = _llamar(cli, modelo, imagenes, prompt_rama(sec, plantilla),
                                     herramienta_rama(plantilla["ramas"][sec]["nombre"]))
                usos.append(uso)
                ramas[sec] = sanear_rama(crudo, sec, plantilla, notas)
        except ErrorLectura as e:
            raise ErrorLectura(f"{sec}: {e}", usos + e.usos) from e
        except Exception as e:                   # tipos raros en lo que contestó la API: ya se pagó, el gasto no se pierde
            raise ErrorLectura(f"{sec}: la respuesta del modelo no tiene la forma esperada ({type(e).__name__}: {e})", usos) from e
    if resto is None:
        raise ErrorLectura("faltó la sección «resto»", usos)
    periodo_impreso = resto.pop("periodo_impreso")
    contenido = {"ramas": {k: ramas[k] for k in plantilla["ramas"] if k in ramas}, **resto}
    return {"contenido": contenido, "notas": notas, "periodo_impreso": periodo_impreso, "usos": usos}


def leer(pdf: bytes, plantilla: dict, modelo: str, veces: int = 2) -> list:
    """`veces` lecturas independientes del mismo PDF (default dos, para C2). Las
    imágenes se preparan una vez. Si una falla, levanta ErrorLectura con el
    consumo de TODAS las llamadas hechas hasta ahí."""
    imagenes = paginas_a_imagenes(pdf)
    lecturas, gastado = [], []
    for _ in range(veces):
        try:
            l = leer_una_vez(imagenes, plantilla, modelo)
        except ErrorLectura as e:
            raise ErrorLectura(str(e), gastado + e.usos) from e
        gastado.extend(l["usos"])
        lecturas.append(l)
    return lecturas


def plantilla_sin_importes(vigente: dict) -> dict:
    """De la grilla vigente, solo la estructura: nombres de ramas y categorías
    (con sus años), claves de los adicionales y tramos de ROE. Ningún importe ni
    coeficiente: lo que se le da a la IA como plantilla es lo que ella copiaría."""
    ramas = {}
    for k, r in vigente["ramas"].items():
        ramas[k] = {"nombre": r["nombre"],
                    "categorias": [{"nombre": c["nombre"], "anios": c.get("anios")} for c in r["categorias"]]}
    adic = {k: ({k2: None for k2 in v} if isinstance(v, dict) else None) for k, v in vigente["adicionales"].items()}
    return {"ramas": ramas, "adicionales": adic, "roe": {"tramos": list(vigente["roe"]["tramos"])}}
