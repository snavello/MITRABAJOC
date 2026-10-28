"""Asistente de trámites: la llamada a la IA (PLAN_ASISTENTE_TRAMITES.md, D1 y D3).

Dos cosas y nada más:
- `entender(relato)`: lee el relato del sindicato y PROPONE nombre, objetivo,
  respuestas a las preguntas del onboarding, los campos del formulario y lo
  que el relato no aclara. Vuelve por una herramienta con esquema cerrado
  (las respuestas son enumeraciones de asistente_tramites.PREGUNTAS) y
  después pasa IGUAL por `asistente_tramites.sanear_propuesta`: la IA
  propone, el motor decide.

Hasta el 2026-10-18 había también `preguntas_extra` (un segundo cuestionario
sobre casos borde): SDN lo sacó, el asistente pregunta una vez.

Misma receta que asistente.py: cliente inyectable (`usar_cliente`) para
probar el circuito sin gastar créditos, prompt de sistema con caché, el
modelo que eligió plataforma (`db.modelo_ia("asistente_tramites")`, default
MODELO) y `effort: low`. La duración se mide pegada a `messages.create`.
Quien llama registra el `uso` en UsoIA con tipo "herramienta".
"""
import json
import os
import time

import asistente_tramites as at
import validaciones_tramite

# El DEFAULT: plataforma puede elegir otro desde /plataforma (uso
# "asistente_tramites" de precios_ia.USOS).
MODELO = "claude-sonnet-5"
MAX_TOKENS = 4096
OPCIONES_MODELO = {"output_config": {"effort": "low"}}
MIN_RELATO = 40
MAX_RELATO = 6000

_cliente = None


class ErrorModelo(Exception):
    """La API no respondió o respondió algo que no se pudo usar."""


def usar_cliente(cliente) -> None:
    global _cliente
    _cliente = cliente


def cliente():
    global _cliente
    if _cliente is None and os.getenv("ANTHROPIC_API_KEY"):
        from anthropic import Anthropic
        _cliente = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _cliente


def disponible() -> bool:
    return cliente() is not None


# ---------- La herramienta: el esquema cerrado de la propuesta ----------

def _enum(valores, descripcion: str, nulo: bool = True) -> dict:
    base = {"type": "string", "enum": list(valores), "description": descripcion}
    return {"anyOf": [base, {"type": "null"}], "description": descripcion} if nulo else base


def esquema_respuestas() -> dict:
    """Las respuestas del onboarding, una propiedad por pregunta (enum de sus
    opciones, o lista para las múltiples) más los textos libres."""
    props, requeridas = {}, []
    for p in at.PREGUNTAS_TODAS:
        claves = [k for k, _ in p["opciones"]]
        desc = p["titulo"] + " " + " / ".join(f"{k}: {t}" for k, t in p["opciones"])
        if p.get("multiple"):
            props[p["clave"]] = {"type": "array", "items": {"type": "string", "enum": claves},
                                 "description": desc + ". Lista vacía si el relato no lo dice."}
        else:
            props[p["clave"]] = _enum(claves, desc + ". null si el relato no lo dice.")
        requeridas.append(p["clave"])
        for t in ("texto", "texto2"):
            if t in p:
                props[p[t]["clave"]] = {"type": "string", "description": p[t]["rotulo"] + ". Vacío si no se sabe."}
                requeridas.append(p[t]["clave"])
    return {"type": "object", "additionalProperties": False, "required": requeridas, "properties": props}


def herramienta() -> dict:
    return {
        "name": "proponer_tramite",
        "description": "Propone cómo implementar en Colm3na el trámite que describe el relato. Solo propone: lo que el relato no dice queda en null, lista vacía o en dudas.",
        "strict": True,
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["nombre", "codigo", "objetivo", "respuestas", "campos", "dudas"],
            "properties": {
                "nombre": {"type": "string", "description": "Nombre corto del trámite, como lo vería el afiliado."},
                "codigo": {"type": "string", "description": "Código corto sin tildes ni espacios (hasta 6), ej. KE27."},
                "objetivo": {"type": "string", "description": "Una oración: qué resuelve el trámite."},
                "respuestas": esquema_respuestas(),
                "campos": {"type": "array", "description": "Las preguntas del formulario que completa quien lo pide, en orden, con separadores para agrupar.",
                           "items": {"type": "object", "additionalProperties": False,
                                     "required": ["etiqueta", "tipo", "obligatorio", "opciones", "control",
                                                  "aclaracion", "regla", "formula", "funcion_nueva"],
                                     "properties": {
                                         "etiqueta": {"type": "string", "description": "Etiqueta corta, como la vería el afiliado."},
                                         "tipo": _enum(at.TIPOS_QUE_PROPONE, " / ".join(f"{k}: {v}" for k, v in at.TIPOS.items() if k in at.TIPOS_QUE_PROPONE) + ". Un documento es archivo; una lista cerrada de opciones es seleccion.", nulo=False),
                                         "obligatorio": {"type": "boolean"},
                                         "opciones": {"type": "string", "description": "Opciones separadas por coma si el tipo las lleva; extensiones si es archivo; vacío si no."},
                                         "control": _enum([k for k in at.CONTROLES if k] + [""], "Solo si el relato lo pide o es evidente: " + " / ".join(f"{k}: {v}" for k, v in at.CONTROLES.items() if k) + ". Vacío si no.", nulo=False),
                                         "aclaracion": {"type": "string", "description": "Una frase que explica el dato a quien arma el formulario, solo si no es obvio (qué es, de dónde sale, por qué se pide). Vacío si es obvio."},
                                         "regla": {"type": "string", "description": "Qué hay que controlar sobre este dato, en una frase, solo si el relato lo pide. Vacío si nada."},
                                         "formula": {"type": "string", "description": "Si la regla se puede escribir con el CATÁLOGO de datos y funciones del sistema (campo.*, lista.*, sistema.*, y/o/no, las funciones listadas), la fórmula exacta. Vacío si no se puede."},
                                         "funcion_nueva": {"type": "string", "description": "Si la regla necesita un dato o una función que NO está en el catálogo: 'nombre_en_minusculas: qué tiene que devolver y de dónde sale'. Vacío si no hace falta."},
                                     }}},
                "dudas": {"type": "array", "description": "Solo lo que el relato NO dice y hace falta saber. Lista vacía si no hay. Nunca preguntes lo que ya respondiste en 'respuestas'.",
                          "items": {"type": "object", "additionalProperties": False, "required": ["pregunta", "sobre", "opciones"],
                                    "properties": {
                                        "pregunta": {"type": "string", "description": "La pregunta, corta y en lenguaje llano."},
                                        "sobre": _enum([p["clave"] for p in at.PREGUNTAS_TODAS] + [""], "Si la duda es sobre una de las preguntas de 'respuestas', su clave: las opciones serán las de esa pregunta. Vacío si no.", nulo=False),
                                        "opciones": {"type": "array", "items": {"type": "string"}, "description": "Si no es sobre una pregunta del catálogo: hasta seis respuestas posibles, cortas, para elegir con un clic. Lista vacía si se contesta con texto."},
                                    }}},
            },
        },
    }


def _catalogo_para_el_prompt() -> str:
    """El catálogo de datos y funciones que una fórmula puede nombrar, tal
    cual lo tiene el código (validaciones_tramite.catalogo_funcion): la IA
    solo puede proponer fórmulas con esto, y lo que no esté acá es una
    función a desarrollar."""
    cat = validaciones_tramite.catalogo_funcion()
    L = ["Datos del sistema (sistema.afiliado.<dato>, del afiliado que inicia el trámite):"]
    L += [f"- {d['nombre']} ({d['devuelve']}): {d['rotulo']}. Ej.: {d['ejemplo']}" for d in cat["sistema"]]
    L.append("Listas que el sindicato carga por CSV (lista.<columna>, la fila del afiliado):")
    L += [f"- {l['nombre']}: " + ", ".join(f"lista.{c['clave']} ({c['tipo']})" for c in l["columnas"]) for l in cat["listas"]]
    L.append("Funciones: " + "; ".join(f"{f['ayuda']} (ej.: {f['ejemplo']})" for f in cat["funciones"]) + ".")
    L.append("Sintaxis: + - * /, comparaciones (<= >= < > == !=), y / o / no, textos entre comillas, fechas AAAA-MM-DD. "
             "Los campos del formulario se nombran campo.<etiqueta en minúsculas, sin tildes, espacios como guion bajo>.")
    return "\n".join(L)


PROMPT_SISTEMA = """Sos analista funcional de Colm3na, la plataforma para sindicatos argentinos donde el afiliado inicia trámites desde su app, un área del sindicato los atiende por un chat con estados (iniciado, en tratamiento, a la espera de info, respondido, terminado) y los formularios los arma el sindicato en un constructor.
Vas a leer el relato de un trámite y llamar a la herramienta proponer_tramite UNA vez.
Reglas:
- Proponé con criterio y lo mínimo: pocas preguntas al afiliado, sin repetir lo que el sindicato ya sabe del padrón (nombre, CUIL, seccional, empleador, credencial), y separadores solo si hay más de seis campos.
- Respondé TODAS las preguntas de "respuestas" con tu mejor lectura del relato. Si el relato no lo dice, elegí la opción más común para ese tipo de trámite y, si de verdad hace falta confirmarlo, sumá UNA duda corta a "dudas" con "sobre" apuntando a esa pregunta. No inventes requisitos, áreas ni documentos.
- "dudas": solo lo que el relato no dice Y cambia el formulario o el circuito. Nada obvio, nada que ya respondiste. Si una duda admite respuestas típicas, dalas en "opciones" (cortas, hasta seis) para que se elija con un clic; si no, dejá "opciones" vacía y se contesta con texto. Pocas: dos o tres como mucho.
- "previo": solo si el relato dice que el afiliado tiene que haber completado o adjuntar OTRO FORMULARIO DE COLM3NA (del sindicato, en la app). Un certificado, una constancia o cualquier documento de afuera NO es un formulario: es un campo de tipo archivo.
- Usá únicamente los valores permitidos de cada enumeración.
- "campos": las preguntas del formulario que completa quien lo pide, en orden. Los documentos son tipo "archivo". Una lista cerrada de opciones es "seleccion".
- "control": solo si el relato lo pide o es evidente (fecha de nacimiento → no_futura; un dato que no puede repetirse → unico; una opción que depende de otra → depende; un dato a cotejar con el grupo familiar del sindicato → lista).
- "regla" / "formula" / "funcion_nueva": cuando el relato pide controlar algo sobre un dato, decí qué (regla) y, si se puede escribir con el catálogo de abajo, la fórmula exacta; si el control necesita un dato que el catálogo no tiene, proponé la función nueva con nombre y qué devuelve. Nunca inventes datos del sistema que no estén en el catálogo.
- Castellano rioplatense, etiquetas cortas como las vería el afiliado. Nada de nombres de personas.

CATÁLOGO DE DATOS Y FUNCIONES PARA LAS FÓRMULAS
""" + _catalogo_para_el_prompt()


def _llamar(cli, sistema: str, mensajes: list, modelo: str, tools=None):
    inicio = time.perf_counter()
    try:
        extra = {"tools": tools, "tool_choice": {"type": "any"}} if tools else {}
        msg = cli.messages.create(
            model=modelo, max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=list(mensajes), **extra, **OPCIONES_MODELO)
    except Exception as e:  # red, cuota, 4xx/5xx: para el analista es lo mismo
        raise ErrorModelo(f"{type(e).__name__}: {e}") from e
    return msg, int((time.perf_counter() - inicio) * 1000)


def _uso(msg, modelo: str, ms: int) -> dict:
    return {"modelo": modelo, "tokens_entrada": getattr(msg.usage, "input_tokens", 0) or 0,
            "tokens_salida": getattr(msg.usage, "output_tokens", 0) or 0, "duracion_ms": ms}


def entender(relato: str, modelo: str) -> tuple:
    """(propuesta saneada, uso). La propuesta ya pasó por sanear_propuesta:
    lo que no está en el catálogo se descartó y `de_ia` dice qué preguntas
    vienen con un valor propuesto."""
    cli = cliente()
    if cli is None:
        raise ErrorModelo("sin cliente de Anthropic configurado")
    relato = (relato or "").strip()[:MAX_RELATO]
    if len(relato) < MIN_RELATO:
        raise ValueError("Contá un poco más: quién lo pide, qué datos y cómo termina.")
    mensajes = [{"role": "user", "content": f'Relato del sindicato:\n"""{relato}"""'}]
    msg, ms = _llamar(cli, PROMPT_SISTEMA, mensajes, modelo, tools=[herramienta()])
    uso = _uso(msg, modelo, ms)
    usos = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
    if not usos:
        raise ErrorModelo("el modelo no devolvió una propuesta", uso)
    crudo = usos[0].input if isinstance(usos[0].input, dict) else {}
    return at.sanear_propuesta(crudo, de_ia=True, relato=relato), uso


class ErrorModelo(ErrorModelo):  # noqa: F811 -- misma clase, con el uso adentro
    """Como extractor.ErrorLectura: si la API contestó pero no sirvió, el
    `uso` viaja en la excepción para que igual se registre (ya se pagó)."""

    def __init__(self, mensaje: str, uso: dict | None = None):
        super().__init__(mensaje)
        self.uso = uso


def a_json(o) -> str:
    return json.dumps(o, ensure_ascii=False)
