"""Asistente del Panel Sindical (docs/ASISTENTE_PANEL.md).

Traduce una pregunta en lenguaje natural del admin de sindicato ("quiero las
notificaciones no leídas de la sucursal Rosario") a los filtros que el Panel
Sindical YA tiene, los valida con el mismo `dashboard.parsear_filtros` que
usa el frontend, calcula los agregados reales y le pide al modelo un resumen
de una o dos frases.

Reglas de este módulo:
- El modelo NUNCA genera SQL ni ve filas. Recibe el catálogo del sindicato
  (ids y nombres de seccionales y empresas), la pregunta tal cual la escribió
  el admin y totales agregados. Ni CUIL ni nombres de trabajadores.
- La única fuente de verdad de lo filtrable es `dashboard.parsear_filtros`:
  acá no se inventan filtros nuevos. Si el panel no filtra algo, el prompt
  le dice al modelo que lo diga en vez de inventar.
- La herramienta devuelve SIEMPRE el estado completo de filtros, no un
  delta: "sacá el filtro de empresa" funciona sin lógica de merge.
- Los ids que no sean del sindicato se descartan ANTES de consultar
  (además del WHERE por sindicato_id que ya tiene cada agregado).
- El cliente de Anthropic se inyecta (`usar_cliente`) para probar todo el
  circuito sin gastar créditos: ver test_asistente.py.
"""
import json
import os
import re
from datetime import date, timedelta

from starlette.datastructures import QueryParams

import dashboard
import db

MODELO = "claude-sonnet-5"
MAX_TOKENS = 1024
# Cómo se llama al modelo. El set de aceptación (probar_asistente.py) lo
# cambia para comparar esfuerzo bajo contra thinking desactivado.
OPCIONES_MODELO = {"output_config": {"effort": "low"}}
MAX_PREGUNTA = 500        # caracteres
MAX_HISTORIAL = 4         # intercambios previos que viajan en cada pedido
MAX_VUELTAS = 3           # llamadas al modelo por pregunta (herramienta + texto)
TOPE_DIARIO = 300         # preguntas por sindicato por día (se aplica en el Bloque 3)
PESTANAS = ["recibos", "tramites", "notificaciones", "consultas"]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Pedidos de reinicio total ("limpiá los filtros", "sacá todos los filtros",
# "empezá de nuevo"): se resuelven acá, sin modelo. Sd vio en Pruebas que
# ante ese pedido el modelo contestó "listo" sin llamar la herramienta: el
# panel quedó con la seccional puesta y la búsqueda siguiente la conservó.
# Un pedido parcial ("sacá el filtro de seccional") NO matchea y va al
# modelo, que es quien sabe qué conservar.
_REINICIO = re.compile(
    r"^\s*(?:(?:limpi|borr|sac|quit|reinici|reset|elimin|anul)\w*\s+(?:todos?\s+)?(?:los\s+|las\s+)?filtros?"
    r"|(?:empez|arranc|comenz)\w*\s+de\s+(?:nuevo|cero)|volv\w*\s+al\s+(?:inicio|principio)"
    r"|sin\s+filtros?|filtros?\s+(?:limpios?|a\s+cero))\s*[.!]*\s*$",
    re.IGNORECASE)


def es_reinicio(pregunta: str) -> bool:
    return bool(_REINICIO.match(_texto_limpio(pregunta)))


def estado_inicial(hoy: date) -> dict:
    """Lo mismo que el panel sin filtros, con el período por defecto del
    asistente (últimos 30 días, decisión de Sd) y la pestaña de recibos."""
    return {"desde": (hoy - timedelta(days=29)).isoformat(), "hasta": hoy.isoformat(),
            "seccionales": [], "empresas": [], "formato": "", "resultado": "",
            "estado_tramite": "", "tipo_notif": "", "sal_min": None, "sal_max": None,
            "tema": "", "afiliado": None, "tab": "recibos"}


class ErrorModelo(Exception):
    """La API del modelo no respondió o respondió algo inusable. La ruta lo
    traduce a E-ASISTENTE-01; el detalle va al log del servidor."""


class PersonaNoEncontrada(Exception):
    """El admin nombró a alguien que no está en el padrón. Se le avisa al
    modelo (como resultado, no como error) para que lo diga."""

    def __init__(self, persona: str):
        super().__init__(persona)
        self.persona = persona


class PersonaAmbigua(Exception):
    """Varios afiliados coinciden. Se resuelve en el cajón, con un clic del
    admin, SIN volver al modelo: los candidatos son padrón y el padrón no
    viaja (docs/ASISTENTE_PANEL.md §9)."""

    def __init__(self, persona: str, candidatos: list, filtros: dict):
        super().__init__(persona)
        self.persona, self.candidatos, self.filtros = persona, candidatos, filtros


# ---------- Cliente ----------

_cliente = None


def usar_cliente(cliente) -> None:
    """Inyecta el cliente de Anthropic: el real (main.py al arrancar no hace
    falta, se crea solo con la API key) o uno falso en los tests."""
    global _cliente
    _cliente = cliente


def cliente():
    global _cliente
    if _cliente is None and os.getenv("ANTHROPIC_API_KEY"):
        from anthropic import Anthropic
        _cliente = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _cliente


def disponible() -> bool:
    """Sin API key (ni cliente inyectado) el asistente no existe: el botón no
    se muestra y la ruta responde 503."""
    return cliente() is not None


# ---------- Catálogo y herramienta ----------

def catalogo(sid: int) -> dict:
    """Lo único del sindicato que ve el modelo: nombres e ids."""
    return {
        "sindicato": db.marca_sindicato(sid).get("nombre", ""),
        "seccionales": [{"id": s["id"], "nombre": s["nombre"]}
                        for s in db.seccionales_del_sindicato(sid)],
        "empresas": [{"id": e["id"], "nombre": e["nombre"], "cuit": e["cuit"]}
                     for e in dashboard.catalogo_empresas(sid)],
        "consultas": bool(db.config_dashboard()["consultas_bot_habilitado"]),
    }


def _enum(valores: list, descripcion: str) -> dict:
    return {"type": "string", "enum": valores, "description": descripcion}


_ENTERO_O_NULO = {"anyOf": [{"type": "integer"}, {"type": "null"}]}

HERRAMIENTA = {
    "name": "fijar_filtros",
    "description": (
        "Fija el estado COMPLETO de filtros del Panel Sindical y la pestaña del "
        "explorador. Reemplaza todo el estado anterior: incluí también los "
        "filtros que ya estaban y hay que conservar."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["desde", "hasta", "seccionales", "empresas", "formato",
                     "resultado", "estado_tramite", "tipo_notif", "sal_min",
                     "sal_max", "tema", "persona", "afiliado", "tab", "motivo"],
        "properties": {
            "desde": {"type": "string", "description": "Inicio del período, AAAA-MM-DD."},
            "hasta": {"type": "string", "description": "Fin del período, AAAA-MM-DD, nunca posterior a hoy."},
            "seccionales": {"type": "array", "items": {"type": "integer"},
                            "description": "Ids de seccionales del catálogo. Lista vacía = todas."},
            "empresas": {"type": "array", "items": {"type": "integer"},
                         "description": "Ids de empresas del catálogo. Lista vacía = todas."},
            "formato": _enum(["", "viejo", "nuevo"],
                             "Formato del recibo: '' todos, 'viejo' clásico, 'nuevo' Anexo III."),
            "resultado": _enum(["", "ok", "con_diferencias"],
                               "Resultado de la verificación: '' todos, 'ok' o 'con_diferencias'."),
            "estado_tramite": _enum(["", "abierto", "en_proceso", "resuelto"],
                                    "Estado del trámite: '' todos."),
            "tipo_notif": _enum(["", "manual", "sistema"],
                                "Tipo de notificación: '' todas, 'manual' comunicaciones del "
                                "sindicato, 'sistema' avisos automáticos de trámites."),
            "sal_min": {**_ENTERO_O_NULO, "description": "Sueldo bruto mínimo en pesos, o null."},
            "sal_max": {**_ENTERO_O_NULO, "description": "Sueldo bruto máximo en pesos, o null."},
            # Los textos opcionales van como null, NO como "": con dos strings
            # vacíos consecutivos Sonnet 5 llegó a emitir basura de su propio
            # formato de llamada ("</antml_parameter>...") en esos campos.
            "tema": {"anyOf": [{"type": "string"}, {"type": "null"}],
                     "description": "Tema de consultas al bot del convenio; null si no aplica."},
            "persona": {"anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nombre o CUIL del afiliado por el que pregunta el admin, tal cual lo "
                                       "escribió, sin corregir ni completar; null si no pregunta por una persona."},
            "afiliado": {**_ENTERO_O_NULO,
                         "description": "Id del afiliado YA elegido en el panel (viene en el estado actual), para "
                                        "conservarlo; null si no hay, si pide otra persona (usá persona) o si pide "
                                        "sacar ese filtro. Nunca inventes un id."},
            "tab": _enum(PESTANAS, "Pestaña que muestra el explorador: la del tema de la pregunta."),
            "motivo": {"type": "string", "description": "Una frase: qué pidió el admin y cómo lo tradujiste."},
        },
    },
}


# ---------- Prompt ----------

def prompt_sistema(cat: dict, hoy: date) -> str:
    """Estable por sindicato (va con cache_control): rol, reglas, glosario y
    catálogo. Lo volátil (estado actual del panel, pregunta) va en el mensaje
    del usuario."""
    seccionales = "\n".join(f"- {s['id']}: {s['nombre']}" for s in cat["seccionales"]) or "- (sin seccionales cargadas)"
    empresas = "\n".join(f"- {e['id']}: {e['nombre']} (CUIT {e['cuit']})" for e in cat["empresas"]) or "- (sin empresas cargadas)"
    pestanas = '"recibos", "tramites", "notificaciones"' + (' o "consultas"' if cat["consultas"] else "")
    consultas = ("- consultas: preguntas que los trabajadores le hicieron al bot del convenio, "
                 "contadas por tema. Son anónimas: con un afiliado elegido no aplican.\n"
                 if cat["consultas"] else "")
    return f"""Sos el Asistente del Panel Sindical de {cat['sindicato']}. Ayudás al administrador del sindicato a mirar su tablero: traducís lo que pide a los filtros que el panel ya tiene y resumís los números que te devuelve.

Hoy es {DIAS[hoy.weekday()]} {hoy.isoformat()}.

QUÉ PODÉS HACER
- Llamar a la herramienta fijar_filtros con el estado COMPLETO de filtros: período, seccionales, empresas, formato, resultado, estado de trámite, tipo de notificación, rango de sueldo bruto y pestaña. Reemplaza todo el estado anterior: si el admin pide agregar o sacar un filtro, mantené los demás como estaban.
- Cuando recibas los números, contestar en una o dos frases, en castellano rioplatense, con las cifras tal cual llegaron. Sin listas, sin markdown, sin repetir la pregunta.

QUÉ NO PODÉS HACER
- Decir que aplicaste, sacaste o cambiaste un filtro sin haber llamado a la herramienta en esa misma respuesta: el panel SOLO cambia cuando la llamás. Si te piden sacar o cambiar filtros, llamá la herramienta con el estado completo resultante y recién después contá qué quedó. El estado actual del panel que recibís es la única verdad sobre qué filtros hay puestos; el historial es solo contexto.
- Inventar números o filtros. Si lo que pide no se puede expresar con estos filtros (ver la LISTA de quiénes no leyeron, ordenar o rankear, comparar dos períodos entre sí), decilo en una frase y NO llames a la herramienta.
- Listar personas: el panel no muestra nombres.
- Adivinar ante una ambigüedad real (un nombre que coincide con una seccional y con una empresa, o un período que no queda claro): preguntá en una frase, sin llamar a la herramienta.

REGLAS DE LOS FILTROS
- Fechas AAAA-MM-DD. "hasta" nunca es posterior a hoy. Rango máximo: {dashboard.RANGO_MAXIMO_DIAS} días. Período cuando el admin NO lo menciona: si el panel está en un solo día (desde = hasta = hoy), usá los últimos 30 días (desde = hoy menos 29 días, hasta = hoy) sin preguntar; si el panel ya tiene otro período, conservalo. Si dice "hoy", es hoy. Nunca preguntes por el período ni ofrezcas ampliarlo: aplicá y decí en la respuesta qué período usaste. "Este mes" = del 1 del mes actual a hoy; "el mes pasado" = el mes calendario anterior completo; "esta semana" = del lunes a hoy; "los últimos 30 días" = 30 días hasta hoy.
- seccionales y empresas llevan ids del catálogo de abajo; lista vacía = todas. Aceptá nombres mal escritos, sin tilde o parciales cuando no hay duda de a cuál se refiere.
- formato: "" (todos), "viejo" (recibo clásico) o "nuevo" (Anexo III de la reforma laboral).
- resultado: "" (todos), "ok" (recibos bien liquidados) o "con_diferencias" (recibos con diferencias en los aportes).
- estado_tramite: "" (todos), "abierto", "en_proceso" o "resuelto".
- tipo_notif: "" (todas), "manual" (comunicaciones que mandó el sindicato) o "sistema" (avisos automáticos de trámites).
- sal_min / sal_max: sueldo bruto en pesos enteros, o null si no se filtra. Usá el número redondo que dijo el admin: "mayor a 800 mil" es sal_min 800000 y "menos de 2 millones" es sal_max 2000000, sin sumar ni restar uno.
- tab: qué muestra el explorador: {pestanas}. Elegí la pestaña del tema de la pregunta.
- tema: solo para la pestaña consultas; si no, null.
- persona: nombre o CUIL del afiliado por el que pregunta ("las notificaciones de Pérez", "qué recibos mandó el 20-12345678-9"), tal cual lo escribió el admin, sin corregirlo ni completarlo; null si no pregunta por una persona nueva. Un CUIL (11 dígitos, con o sin guiones) va en persona igual que un nombre: el servidor lo busca en el padrón. No hace falta "identificar" a la persona antes ni pedirle nada al admin: llamá la herramienta con persona y el servidor resuelve. "¿Dónde trabaja Romero?", "¿en qué seccional está?" también son preguntas por persona: llamá la herramienta con persona; el panel muestra su ficha (seccional y empresa) junto a tu respuesta. Si además dice dónde trabaja ("que trabaja en el banco Galicia"), poné esa empresa en empresas: sirve para distinguir homónimos. Si hay varias coincidencias, el admin elige en pantalla.
- afiliado: id del afiliado ya elegido en el panel (lo ves en el estado actual). Mantenelo si la pregunta sigue sobre la misma persona ("y sus trámites?"); null si pide otra persona (con persona) o si pide sacar ese filtro. Nunca inventes un id.

QUÉ MIDE CADA PESTAÑA
- recibos: recibos de sueldo que los trabajadores verificaron con la app: cuántos OK, cuántos con diferencias y el monto de esas diferencias. Con un afiliado elegido se ven SOLO los recibos que esa persona envió al sindicato: los que verificó en privado no existen para el panel, y así hay que decirlo si pregunta.
- tramites: expedientes iniciados por los afiliados, por seccional y estado.
- notificaciones: comunicaciones que el sindicato mandó a los afiliados: enviadas, leídas y sin leer. "Sin leer" (también "no leídas", "pendientes de lectura", "que no abrieron") es una cifra que vas a recibir, no un filtro: para responderlo, filtrá por lo que pida (seccional, período, tipo) con tab "notificaciones" y leé la cifra sin_leer.
{consultas}
GLOSARIO (cómo habla la gente del gremio)
- seccional = sucursal, delegación, filial, regional, sede.
- recibo = boleta, liquidación, recibo de sueldo, recibo de haberes.
- con diferencias = mal liquidados, con errores, con problemas, observados.
- empresa = empleador, patronal, firma, fábrica, establecimiento.
- trámite = expediente, gestión, reclamo, solicitud, pedido.
- notificación = comunicado, aviso, mensaje, circular.
- formato nuevo = Anexo III, recibo de la reforma, recibo nuevo.

CATÁLOGO DE ESTE SINDICATO
Seccionales (id: nombre):
{seccionales}
Empresas (id: nombre, CUIT):
{empresas}"""


# ---------- Estado de filtros ----------

def _a_params(crudo: dict) -> QueryParams:
    """Un dict con las claves del panel (listas incluidas) -> QueryParams, para
    validarlo con EXACTAMENTE la misma función que usa el frontend."""
    pares = []
    for clave, valor in (crudo or {}).items():
        if clave == "tab" or valor is None:
            continue
        if isinstance(valor, (list, tuple, set)):
            pares.extend((clave, str(v)) for v in valor)
        else:
            pares.append((clave, str(valor)))
    return QueryParams(pares)


def _pestana(crudo: dict, cat: dict) -> str:
    tab = str((crudo or {}).get("tab") or "")
    if tab == "consultas" and not cat["consultas"]:
        tab = ""
    return tab if tab in PESTANAS else "recibos"


def _validar(sid: int, entrada: dict, cat: dict, hoy: date) -> tuple:
    """Salida de la herramienta -> (estado crudo para el JS, filtros parseados
    para dashboard.py, pestaña). Lanza ValueError con el mismo mensaje que ve
    el frontend; el modelo lo recibe como error y corrige. `persona` se
    resuelve acá contra el padrón (PersonaNoEncontrada / PersonaAmbigua):
    el modelo nunca ve la lista."""
    ids_secc = {s["id"] for s in cat["seccionales"]}
    ids_emp = {e["id"] for e in cat["empresas"]}
    crudo = {
        "desde": str(entrada.get("desde") or ""),
        "hasta": str(entrada.get("hasta") or ""),
        # Un id ajeno o inexistente se descarta en silencio: no es del tenant.
        "seccionales": [i for i in _enteros(entrada.get("seccionales")) if i in ids_secc],
        "empresas": [i for i in _enteros(entrada.get("empresas")) if i in ids_emp],
        "formato": str(entrada.get("formato") or ""),
        "resultado": str(entrada.get("resultado") or ""),
        "estado_tramite": str(entrada.get("estado_tramite") or ""),
        "tipo_notif": str(entrada.get("tipo_notif") or ""),
        "sal_min": _entero_o_nulo(entrada.get("sal_min")),
        "sal_max": _entero_o_nulo(entrada.get("sal_max")),
        "tema": _texto_limpio(entrada.get("tema")),
        "tab": _pestana(entrada, cat),
    }
    if crudo["tab"] != "consultas":
        crudo["tema"] = ""
    persona = _texto_limpio(entrada.get("persona"))
    afiliado = _entero_o_nulo(entrada.get("afiliado"))
    crudo["afiliado"] = None
    if persona:
        # Las empresas ya filtradas acotan la búsqueda: "Pérez, el del banco
        # Galicia" desempata homónimos sin que el modelo vea el padrón.
        cuits = [e["cuit"] for e in cat["empresas"] if e["id"] in set(crudo["empresas"])] or None
        candidatos = dashboard.buscar_afiliados(sid, persona, cuits=cuits, limite=6)
        if not candidatos:
            raise PersonaNoEncontrada(persona)
        if len(candidatos) > 1:
            raise PersonaAmbigua(persona, candidatos, crudo)
        afiliado = candidatos[0]["id"]
    elif afiliado and not dashboard.afiliado_por_id(sid, afiliado):
        afiliado = None          # id ajeno o inexistente: no es de este sindicato
    crudo["afiliado"] = afiliado
    f = dashboard.parsear_filtros(_a_params(crudo), hoy)
    return crudo, f, crudo["tab"]


def _texto_limpio(v) -> str:
    """Un campo de texto de la herramienta. La salida del modelo no es un
    contrato: Sonnet 5 llegó a emitir basura de su propio formato de llamada
    ("</antml_parameter>\\n<parameter name=...") en dos strings vacíos
    consecutivos, y el servidor salió a buscar a esa "persona". Lo que huela
    a etiqueta de herramienta cuenta como vacío."""
    if not isinstance(v, str):
        return ""
    v = v.strip()
    if "<" in v and ("parameter" in v or "antml" in v):
        return ""
    return v


def _enteros(valores) -> list:
    salida = []
    for v in (valores or []):
        try:
            salida.append(int(v))
        except (TypeError, ValueError):
            continue
    return salida


def _entero_o_nulo(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def describir_filtros(crudo: dict, cat: dict, hoy: date) -> str:
    """El estado actual del panel, en palabras, para el mensaje del usuario."""
    try:
        f = dashboard.parsear_filtros(_a_params(crudo), hoy)
    except ValueError:
        return "período por defecto del panel, sin filtros."
    nombres_secc = {s["id"]: s["nombre"] for s in cat["seccionales"]}
    nombres_emp = {e["id"]: e["nombre"] for e in cat["empresas"]}
    partes = [f"período del {f['desde']} al {f['hasta']} ({f['dias']} días)"]
    secc = [nombres_secc[i] for i in f["seccionales"] if i in nombres_secc]
    emp = [nombres_emp[i] for i in f["empresas"] if i in nombres_emp]
    partes.append("seccionales: " + (", ".join(secc) if secc else "todas"))
    partes.append("empresas: " + (", ".join(emp) if emp else "todas"))
    if f["formato"]:
        partes.append("formato: " + ("viejo" if f["formato"] == "clasico" else "nuevo"))
    if f["resultado"]:
        partes.append("resultado: " + ("ok" if f["resultado"] == "OK" else "con_diferencias"))
    if f["estado_tramite"]:
        partes.append("estado de trámite: " + f["estado_tramite"])
    if f["tipo_notif"]:
        partes.append("tipo de notificación: " + f["tipo_notif"])
    if f["sal_min"] is not None or f["sal_max"] is not None:
        partes.append(f"bruto entre {f['sal_min'] or 'sin mínimo'} y {f['sal_max'] or 'sin máximo'}")
    if f["tema"]:
        partes.append("tema: " + f["tema"])
    if f.get("afiliado"):
        # Solo el id: el nombre es padrón y el padrón no viaja al modelo.
        partes.append(f"afiliado elegido: id {f['afiliado']}")
    partes.append("pestaña: " + _pestana(crudo, cat))
    return "; ".join(partes) + "."


# ---------- Agregados que ve el modelo ----------

def _agregados(sid: int, crudo: dict, f: dict, tab: str, cat: dict) -> dict:
    """Solo números y nombres de seccional/empresa. Nada de personas."""
    nombres_secc = {s["id"]: s["nombre"] for s in cat["seccionales"]}
    nombres_emp = {e["id"]: e["nombre"] for e in cat["empresas"]}
    datos = {
        "filtros_aplicados": {
            "desde": f["desde"], "hasta": f["hasta"], "dias": f["dias"],
            "seccionales": [nombres_secc[i] for i in crudo["seccionales"]] or "todas",
            "empresas": [nombres_emp[i] for i in crudo["empresas"]] or "todas",
            "formato": crudo["formato"] or "todos",
            "resultado": crudo["resultado"] or "todos",
            "estado_tramite": crudo["estado_tramite"] or "todos",
            "tipo_notif": crudo["tipo_notif"] or "todas",
            "bruto_min": crudo["sal_min"], "bruto_max": crudo["sal_max"],
            "afiliado": (f"uno elegido (id {crudo['afiliado']}); de sus recibos se cuentan solo los "
                         "que envió al sindicato. El panel muestra su nombre, CUIL, seccional y empresa "
                         "en una ficha junto a tu respuesta: si preguntan dónde trabaja o en qué "
                         "seccional está, remití a la ficha ('abajo tenés su seccional y su empresa'); "
                         "nunca digas que no podés saberlo" if crudo.get("afiliado") else "ninguno"),
            "pestaña": tab,
        },
        "kpis_del_periodo": dashboard.kpis(sid, f)["actual"],
    }
    if crudo["resultado"]:
        # Con el filtro de resultado puesto, "% con diferencias" se calcula
        # sobre lo filtrado y da 100% o 0% por construcción: el modelo lo
        # citaba como si fuera el porcentaje de la seccional.
        datos["kpis_del_periodo"].pop("pct_con_diferencias", None)
    if tab == "notificaciones":
        datos["notificaciones"] = dashboard.notificaciones(sid, f)
    elif tab == "tramites":
        datos["tramites_por_seccional"] = dashboard.tramites_seccional(sid, f)["seccionales"]
    elif tab == "consultas":
        datos["consultas_por_tema"] = dashboard.consultas_por_tema(sid, f)
    else:
        datos["validacion_de_recibos"] = dashboard.validacion(sid, f)
    return datos


# ---------- Conversación ----------

def _mensajes(pregunta: str, filtros_actuales: dict, historial: list, cat: dict, hoy: date) -> list:
    validos = []
    for previo in (historial or []):
        if not isinstance(previo, dict):
            continue
        p, r = str(previo.get("pregunta") or "").strip(), str(previo.get("respuesta") or "").strip()
        if p and r:
            validos.append((p[:MAX_PREGUNTA], r[:MAX_TOKENS]))
    mensajes = []
    for p, r in validos[-MAX_HISTORIAL:]:
        mensajes.append({"role": "user", "content": p})
        mensajes.append({"role": "assistant", "content": r})
    mensajes.append({"role": "user", "content": (
        f"Estado actual del panel: {describir_filtros(filtros_actuales, cat, hoy)}\n\n"
        f"Pregunta del administrador: {pregunta}")})
    return mensajes


def _llamar(cli, sistema: str, mensajes: list):
    try:
        return cli.messages.create(
            model=MODELO, max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            tools=[HERRAMIENTA],
            # Copia: la lista sigue creciendo en el bucle y cada pedido tiene
            # que quedar tal cual se mandó (los tests lo inspeccionan).
            messages=list(mensajes),
            **OPCIONES_MODELO,
        )
    except Exception as e:  # red, cuota, 4xx/5xx: para el admin es lo mismo
        raise ErrorModelo(f"{type(e).__name__}: {e}") from e


def responder(sid: int, pregunta: str, filtros_actuales: dict, historial: list,
              hoy: date | None = None) -> dict:
    """Una pregunta -> {"respuesta", "filtros" (o None), "aplicar", "uso"}.

    Bucle de a lo sumo MAX_VUELTAS llamadas: el modelo llama la herramienta,
    el servidor valida y calcula, el modelo redacta. Si contesta en texto sin
    llamar la herramienta (repregunta, fuera de alcance), no se aplica nada."""
    cli = cliente()
    if cli is None:
        raise ErrorModelo("sin cliente de Anthropic configurado")
    hoy = hoy or date.today()
    if es_reinicio(pregunta):
        return {"respuesta": "Listo, reinicié los filtros: últimos 30 días, sin seccional, empresa ni afiliado.",
                "filtros": estado_inicial(hoy), "aplicar": True, "afiliado": None,
                "candidatos": [], "filtros_pendientes": None,
                "uso": {"modelo": "", "tokens_entrada": 0, "tokens_salida": 0, "llamadas": 0}}
    cat = catalogo(sid)
    sistema = prompt_sistema(cat, hoy)
    mensajes = _mensajes(pregunta, filtros_actuales, historial, cat, hoy)
    uso = {"modelo": MODELO, "tokens_entrada": 0, "tokens_salida": 0, "llamadas": 0}
    filtros_salida, texto = None, ""

    for _ in range(MAX_VUELTAS):
        msg = _llamar(cli, sistema, mensajes)
        uso["llamadas"] += 1
        uso["tokens_entrada"] += getattr(msg.usage, "input_tokens", 0) or 0
        uso["tokens_salida"] += getattr(msg.usage, "output_tokens", 0) or 0
        texto = "".join(b.text for b in msg.content if b.type == "text").strip()
        usos = [b for b in msg.content if b.type == "tool_use"]
        if not usos:
            break
        # El contenido de la respuesta vuelve tal cual (incluidos los bloques
        # de razonamiento, si los hay): es lo que la API espera recibir.
        mensajes.append({"role": "assistant", "content": msg.content})
        resultados = []
        for u in usos:
            try:
                crudo, f, tab = _validar(sid, u.input or {}, cat, hoy)
                datos = _agregados(sid, crudo, f, tab, cat)
                filtros_salida = crudo
                resultados.append({"type": "tool_result", "tool_use_id": u.id,
                                   "content": json.dumps(datos, ensure_ascii=False, default=str)})
            except PersonaNoEncontrada as e:
                resultados.append({"type": "tool_result", "tool_use_id": u.id,
                                   "content": f"No encontré ningún afiliado del padrón que coincida con "
                                              f"«{e.persona}». No apliqué filtros: decíselo al admin y "
                                              f"pedile que revise el nombre o el CUIL."})
            except PersonaAmbigua as e:
                # Se corta acá: el admin elige en el cajón y el JS aplica
                # filtros_pendientes + afiliado sin volver a llamar al modelo.
                return {"respuesta": f"Encontré {len(e.candidatos)} afiliados que coinciden con "
                                     f"«{e.persona}». Elegí a cuál te referís:",
                        "filtros": None, "aplicar": False, "afiliado": None,
                        "candidatos": e.candidatos, "filtros_pendientes": e.filtros, "uso": uso}
            except ValueError as e:
                resultados.append({"type": "tool_result", "tool_use_id": u.id,
                                   "content": f"Filtros rechazados: {e} Corregí y volvé a llamar.",
                                   "is_error": True})
        mensajes.append({"role": "user", "content": resultados})
        texto = ""

    if not texto:
        texto = ("Apliqué los filtros en el panel." if filtros_salida
                 else "No pude resolver la consulta. Probá con una pregunta más simple.")
    afiliado = None
    if filtros_salida and filtros_salida.get("afiliado"):
        afiliado = dashboard.afiliado_por_id(sid, filtros_salida["afiliado"])   # para el chip
    return {"respuesta": texto, "filtros": filtros_salida, "aplicar": filtros_salida is not None,
            "afiliado": afiliado, "candidatos": [], "filtros_pendientes": None, "uso": uso}
