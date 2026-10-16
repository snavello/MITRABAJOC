"""Asistente de trámites: la llamada a la IA (PLAN_ASISTENTE_TRAMITES.md, D1 y D3).

Dos cosas y nada más:
- `entender(relato)`: lee el relato del sindicato y PROPONE nombre, objetivo,
  respuestas a las preguntas del onboarding, los campos del formulario y lo
  que el relato no aclara. Vuelve por una herramienta con esquema cerrado
  (las respuestas son enumeraciones de asistente_tramites.PREGUNTAS) y
  después pasa IGUAL por `asistente_tramites.sanear_propuesta`: la IA
  propone, el motor decide.
- `preguntas_extra(instruccion, ya_listadas)`: entre 4 y 8 preguntas nuevas
  para el sindicato sobre casos borde, en texto.

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
    for p in at.PREGUNTAS:
        if p.get("campos") or p.get("actores"):
            continue
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
                                     "required": ["etiqueta", "tipo", "obligatorio", "opciones", "control"],
                                     "properties": {
                                         "etiqueta": {"type": "string", "description": "Etiqueta corta, como la vería el afiliado."},
                                         "tipo": _enum(at.TIPOS_QUE_PROPONE, " / ".join(f"{k}: {v}" for k, v in at.TIPOS.items() if k in at.TIPOS_QUE_PROPONE) + ". Un documento es archivo; una lista cerrada de opciones es seleccion.", nulo=False),
                                         "obligatorio": {"type": "boolean"},
                                         "opciones": {"type": "string", "description": "Opciones separadas por coma si el tipo las lleva; extensiones si es archivo; vacío si no."},
                                         "control": _enum([k for k in at.CONTROLES if k] + [""], "Solo si el relato lo pide o es evidente: " + " / ".join(f"{k}: {v}" for k, v in at.CONTROLES.items() if k) + ". Vacío si no.", nulo=False),
                                     }}},
                "dudas": {"type": "array", "items": {"type": "string"},
                          "description": "Preguntas cortas sobre lo que el relato no aclara. Lista vacía si no hay."},
            },
        },
    }


PROMPT_SISTEMA = """Sos analista funcional de Colm3na, la plataforma para sindicatos argentinos donde el afiliado inicia trámites desde su app, un área del sindicato los atiende por un chat con estados (iniciado, en tratamiento, a la espera de info, respondido, terminado) y los formularios los arma el sindicato en un constructor.
Vas a leer el relato de un trámite y llamar a la herramienta proponer_tramite UNA vez.
Reglas:
- Solo proponés. Si el relato no lo dice con claridad, poné null (o lista vacía) y sumá la pregunta a "dudas". No inventes requisitos, áreas ni documentos.
- Usá únicamente los valores permitidos de cada enumeración.
- "campos": las preguntas del formulario que completa quien lo pide, en orden, con separadores para agrupar. Los documentos son tipo "archivo". Una lista cerrada de opciones es "seleccion".
- "control": elegí uno solo si el relato lo pide o es evidente (fecha de nacimiento → no_futura; un dato que no puede repetirse → unico; una opción que depende de otra → depende; un dato a cotejar con una base del sindicato → lista).
- Castellano rioplatense, etiquetas cortas como las vería el afiliado. Nada de nombres de personas."""


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


def preguntas_extra(instruccion: str, ya_listadas: list, modelo: str) -> tuple:
    """Entre 4 y 8 preguntas nuevas para el sindicato (texto, una por
    línea). Devuelve (lista de preguntas, uso)."""
    cli = cliente()
    if cli is None:
        raise ErrorModelo("sin cliente de Anthropic configurado")
    sistema = ("Sos implementador de Colm3na en un sindicato argentino. Con el trámite que te paso, escribí "
               "entre 4 y 8 preguntas NUEVAS para el sindicato sobre casos borde (rechazos, plazos, excepciones, "
               "qué pasa si…). No repitas las ya listadas. Una por línea, numeradas, sin introducción, en "
               "castellano rioplatense.")
    cuerpo = instruccion.strip()[:8000] + "\n\nYa listadas:\n" + ("\n".join(f"- {p}" for p in ya_listadas[:40]) or "(ninguna)")
    msg, ms = _llamar(cli, sistema, [{"role": "user", "content": cuerpo}], modelo)
    texto = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    preguntas = []
    for linea in texto.splitlines():
        limpia = linea.strip().lstrip("-•*0123456789.) ").strip()
        if limpia.endswith("?") or limpia.startswith("¿"):
            preguntas.append(limpia[:300])
    return preguntas[:8], _uso(msg, modelo, ms)


class ErrorModelo(ErrorModelo):  # noqa: F811 -- misma clase, con el uso adentro
    """Como extractor.ErrorLectura: si la API contestó pero no sirvió, el
    `uso` viaja en la excepción para que igual se registre (ya se pagó)."""

    def __init__(self, mensaje: str, uso: dict | None = None):
        super().__init__(mensaje)
        self.uso = uso


def a_json(o) -> str:
    return json.dumps(o, ensure_ascii=False)
