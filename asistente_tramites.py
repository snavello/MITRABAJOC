"""Asistente de trámites: el motor PURO (PLAN_ASISTENTE_TRAMITES.md, D1 y D4).

Convierte el relato de un sindicato, ya pasado por las preguntas del
onboarding, en lo que hace falta para implementar el trámite en Colm3na:
el circuito por actor (BPMN simplificado), quién hace qué, qué datos
circulan, la instrucción para crear el formulario, su forma exacta para el
constructor, lo que hay que preparar antes (configurar / ajuste /
desarrollo), las preguntas pendientes y el JSON `colm3na.tramite` v1.

Reglas:
- La IA PROPONE (asistente_tramites_ia.py), este módulo DECIDE: toda
  propuesta entra por `sanear_propuesta`, que descarta lo que no está en el
  catálogo. Nada de lo que la herramienta afirma sobre Colm3na sale del
  modelo.
- No importa `db` ni `main`: lo que sabe de Colm3na es el catálogo de abajo,
  y `test_asistente_tramites.py` lo compara contra las constantes reales
  (fail-closed: un tipo de campo nuevo en el constructor hace fallar el test
  hasta que el asistente sepa qué decir de él).
- `BRECHAS` es la lista CERRADA de lo que Colm3na no hace todavía, con su
  salida provisoria. Cuando una se desarrolla, se saca de acá y deja de
  señalarse (y de contarse en la vista de brechas acumuladas).
- Determinista: la misma entrada da el mismo resultado. Por eso el kit
  escolar de La Bancaria (`docs/chat/2026-10-16-ejemplo-kit-escolar.colm3na.json`)
  es el caso dorado del test.
"""
import re
import unicodedata
from typing import Optional

import fechas
import modulos
import permisos
import listas as listas_mod
import validaciones_tramite

# ---------------------------------------------------------------- catálogo
# Lo que el constructor de Trámites tiene hoy. El test lo compara contra
# main.TIPOS_DATO_TRAMITE / ANCHOS_CAMPO_TRAMITE y db.ESTADOS_TRAMITE.
TIPOS = {
    "texto": "Texto", "numero": "Número", "fecha": "Fecha", "archivo": "Archivo",
    "seleccion": "Lista desplegable", "opcion_unica": "Opción única",
    "multiple": "Opción múltiple", "booleano": "Sí / No", "separador": "Separador",
    # Lo completa el servidor con una fórmula (bloque 3 de Listas y
    # validaciones); el asistente no lo propone, el constructor lo ofrece.
    "calculado": "Calculado (fórmula)",
}
TIPOS_QUE_PROPONE = tuple(t for t in TIPOS if t != "calculado")
ANCHOS = ("completo", "mitad", "tercio")
# El ancho que el asistente propone para cada tipo (lo que mejor queda en el
# teléfono del afiliado); el constructor deja cambiarlo.
ANCHO_POR_TIPO = {
    "texto": "completo", "numero": "tercio", "fecha": "tercio", "archivo": "completo",
    "seleccion": "mitad", "opcion_unica": "mitad", "multiple": "completo",
    "booleano": "mitad", "separador": "completo", "calculado": "tercio",
}
CON_OPCIONES = ("seleccion", "opcion_unica", "multiple")
EXTENSIONES_DEFAULT = "pdf,jpg,jpeg,png"
# Controles que el analista puede pedir sobre un campo. Los cuatro últimos
# NO existen en Colm3na: cada uno apunta a una brecha (CONTROL_BRECHA).
CONTROLES = {
    "": "Ninguno",
    "no_futura": "Fecha no futura",
    "desde_hoy": "Fecha desde hoy",
    "largo_max": "Largo máximo",
    "largo_exacto": "Largo exacto",
    "unico": "No repetir entre pedidos",
    "depende": "Depende de otra respuesta",
    "lista": "Contra una lista del sindicato",
    "formato": "Formato (mail, teléfono)",
}
# "lista" dejó de ser brecha el 2026-10-16: es una validación por función
# contra el grupo familiar (bloque 3 de PLAN_LISTAS_VALIDACIONES.md).
CONTROL_BRECHA = {"unico": "duplicados", "depende": "dependencia", "formato": "formato"}
# Lo que un control sobre un campo exporta como validación real de Colm3na.
LISTA_FAMILIAR = "grupo_familiar"
MESES_ANTIGUEDAD = 6     # el requisito de antigüedad sale con este número; el admin lo ajusta
ESTADOS = {
    "iniciado": "Iniciado", "en_tratamiento": "En tratamiento",
    "espera_info": "A la espera de info", "respondido": "Respondido", "terminado": "Terminado",
}
MODULOS_NOMBRE = {m: modulos.MODULOS[m] for m in ("tramites", "notificaciones", "noticias", "empleadores")}
PERMISO_RECIBE = "tramites_recibidos"
PERMISO_CREA = "tramites_formularios"
SECCIONAL_CENTRAL = "Sede Central"
MAX_CAMPOS = 40

# ---------------------------------------------------------------- brechas
# nivel: "ajuste" (cambio chico, se arranca con la salida provisoria) o
# "desarrollo" (hace falta programar). `tam` es el esfuerzo estimado.
# `hoy` es la salida provisoria; `rec`, la recomendación.
BRECHAS = {
    "ventana": {
        "titulo": "Abrir y cerrar el formulario por fechas", "nivel": "ajuste", "tam": "chico",
        "hoy": "Alguien del sindicato activa el formulario el día de apertura y lo desactiva al cierre. La noticia que lo anuncia sí vence sola.",
        "rec": "Fecha desde / hasta en el tipo de trámite, con el mismo criterio de vigencia que Noticias.",
        "backlog": "Trámites: seis brechas · 1"},
    "familia": {
        "titulo": "Familiares declarados una sola vez", "nivel": "desarrollo", "tam": "grande",
        "hoy": "El formulario pide los datos y documentos del familiar en cada pedido.",
        "rec": "Grupo familiar en el perfil del afiliado, validado una vez y reutilizable por todos los trámites.",
        "backlog": ""},
    "duplicados": {
        "titulo": "Evitar pedidos repetidos por familiar o por período", "nivel": "ajuste", "tam": "mediano",
        "hoy": "«Una sola vez» ya se controla con un requisito (sistema.tramites_de_este_tipo). Por familiar o por período nada lo impide: el área lo detecta al revisar.",
        "rec": "Marca «único por valor de un campo» (DNI del familiar, período) que avise o bloquee.",
        "backlog": "Trámites: seis brechas · 6"},
    "dependencia": {
        "titulo": "Una respuesta que depende de otra", "nivel": "ajuste", "tam": "mediano",
        "hoy": "Las reglas entre campos comparan solo números o fechas. Salida: unir las dos preguntas en una lista («Primaria 1.º», «Primaria 2.º»…).",
        "rec": "Opciones dependientes en el constructor, evaluadas también en el servidor.",
        "backlog": "Trámites: seis brechas · 5"},
    "formato": {
        "titulo": "Validar mail o teléfono", "nivel": "ajuste", "tam": "chico",
        "hoy": "Se carga como texto libre; solo se controla el largo.",
        "rec": "Formatos cerrados (mail, teléfono, CBU/CVU) como validación fija sobre texto.",
        "backlog": ""},
    "cupo": {
        "titulo": "Cupo o stock por seccional", "nivel": "desarrollo", "tam": "mediano",
        "hoy": "El área lleva las unidades en su planilla y avisa por el chat si se agotaron.",
        "rec": "Cupos por formulario y seccional que se descuentan al aprobar y cierran el formulario al llegar a cero.",
        "backlog": ""},
    "exportar": {
        "titulo": "Listado de pedidos con sus respuestas", "nivel": "ajuste", "tam": "mediano",
        "hoy": "El Panel Sindical lista expediente, seccional, estado y días, pero no las respuestas.",
        "rec": "Exportar a CSV los trámites de un formulario con una columna por campo, filtrado por seccional y estado.",
        "backlog": "Trámites: seis brechas · 4"},
    "entrega": {
        "titulo": "Registrar la entrega", "nivel": "ajuste", "tam": "mediano",
        "hoy": "Al entregar, el área pasa el trámite a Terminado con un mensaje. El afiliado se identifica con su credencial digital.",
        "rec": "Cerrar el expediente escaneando el QR de la credencial desde el panel, con fecha, lugar y operador.",
        "backlog": ""},
    "turnos": {
        "titulo": "Turnos con agenda", "nivel": "desarrollo", "tam": "grande",
        "hoy": "El área le manda un formulario «Confirmar turno» con día, hora y lugar.",
        "rec": "Agenda por área y seccional con franjas y cupo, que el afiliado elige en el trámite.",
        "backlog": ""},
    "pago": {
        "titulo": "Pago o reintegro dentro del trámite", "nivel": "desarrollo", "tam": "grande",
        "hoy": "El sindicato paga por su circuito y lo informa por el chat; el afiliado adjunta comprobantes como archivo.",
        "rec": "Evaluar con el sindicato si hace falta: muchas veces el comprobante adjunto alcanza.",
        "backlog": ""},
    "publico": {
        "titulo": "Que lo inicie alguien fuera del padrón", "nivel": "desarrollo", "tam": "grande",
        "hoy": "Solo inician trámites los afiliados del padrón con cuenta.",
        "rec": "Entrada pública con captcha y mail confirmado que abra un expediente sin cuenta.",
        "backlog": ""},
    "previo": {
        "titulo": "Exigir un formulario previo de Colm3na", "nivel": "ajuste", "tam": "mediano",
        "hoy": "El área verifica al revisar que el afiliado haya presentado el formulario previo; la instrucción lo dice y el chat lo pide si falta.",
        "rec": "Dato del sistema «presentó el formulario X» (sistema.afiliado.tramites_de_tipo) para usarlo como requisito para iniciar.",
        "backlog": ""},
    "encadenado": {
        "titulo": "Formularios que solo se mandan desde el chat", "nivel": "ajuste", "tam": "chico",
        "hoy": "Para poder adjuntarse en el chat, el formulario tiene que estar activo, y entonces el afiliado también lo ve en «Iniciar trámite» y puede enviarlo sin pedido previo. Salida: titularlo «(solo si te lo pide el sindicato)».",
        "rec": "Marca «solo encadenado»: se adjunta desde el chat, no se lista para iniciar y el envío exige el trámite de origen.",
        "backlog": "Trámites: seis brechas · 2"},
}

# ---------------------------------------------------------------- preguntas
# `cuando` es un dato, no una función: viaja al navegador tal cual.
# `texto` / `texto2`: un campo libre que acompaña a la respuesta
# (`si` = solo con esa opción; sin `si`, siempre).
# Las SEIS preguntas que se le hacen al analista (2026-10-18, pedido de
# SDN: "demasiadas preguntas y opciones ridículas"). Cada una trae una
# RECOMENDADA, que queda puesta si la IA no propuso nada, y admite una
# respuesta libre (`nota_<clave>`) que viaja a la instrucción y al prompt.
# Lo demás que el motor necesita (segundo formulario, ventana, quién
# entrega, cupo, listado, tercero) ya no se pregunta: son INFERIDAS, con su
# valor por defecto, que la IA completa desde el relato y el analista
# puede corregir en "Lo que entendí".
PREGUNTAS = [
    {"clave": "quien", "titulo": "¿Quién inicia el pedido?", "ayuda": "La persona que completa el formulario.",
     "recomendada": "afiliado",
     "opciones": [["afiliado", "El afiliado, desde la app"], ["empresa", "La empresa empleadora"],
                  ["publico", "Alguien que no está en el padrón (un familiar, un no afiliado)"]]},
    {"clave": "atiende", "titulo": "¿Quién lo recibe y lo revisa?", "ayuda": "En Colm3na cada área pertenece a una seccional.",
     "recomendada": "seccional",
     "opciones": [["seccional", "Un área de la seccional del afiliado"], ["central", "Siempre la misma área central"]],
     "texto": {"clave": "area", "rotulo": "Nombre del área", "ejemplo": "Acción Social"}},
    {"clave": "aprueba", "titulo": "¿Hace falta una aprobación?", "ayuda": "Si aprueba otra área, el trámite se le pasa desde el chat.",
     "recomendada": "misma",
     "opciones": [["misma", "Sí, la misma área que lo revisa"], ["otra", "Sí, otra área"], ["no", "No, solo se responde"]],
     "texto": {"clave": "area_aprueba", "si": "otra", "rotulo": "¿Qué área aprueba?", "ejemplo": "Secretaría General"}},
    {"clave": "requisitos", "titulo": "¿Qué tiene que cumplir quien lo pide?", "ayuda": "Marcá todas las que correspondan. Lo que no esté acá, escribilo abajo: el asistente dice con qué función se controla o qué habría que desarrollar.",
     "multiple": True, "excluyente": "ninguno", "recomendada": ["ninguno"],
     "opciones": [["antiguedad", "Una antigüedad mínima como afiliado"], ["titular", "Ser el afiliado titular"],
                  ["familiar", "Tener un familiar a cargo"], ["edad", "Una edad (propia o del familiar)"],
                  ["credencial", "Tener la credencial vigente"],
                  ["ninguno", "Ninguna: alcanza con estar afiliado"]]},
    {"clave": "fin", "titulo": "¿Cómo termina?", "ayuda": "Lo último que pasa antes de cerrar el expediente.",
     "recomendada": "respuesta",
     "opciones": [["entrega", "Se entrega algo en persona"], ["respuesta", "Con una respuesta o un documento por el chat"],
                  ["turno", "Con un turno o una entrevista"], ["pago", "Con un pago o un reintegro"]],
     "texto": {"clave": "lugar", "si": "entrega", "rotulo": "¿Dónde se entrega o retira?", "ejemplo": "Sede, delegación, comisión gremial"}},
    {"clave": "frecuencia", "titulo": "¿Cuántas veces lo puede pedir?", "ayuda": "Define si hace falta controlar pedidos repetidos.",
     "recomendada": "libre",
     "opciones": [["libre", "Cada vez que lo necesite"], ["periodo", "Una vez por período o campaña"],
                  ["familiar", "Uno por cada familiar"], ["unica", "Una sola vez"]]},
]
INFERIDAS = [
    {"clave": "segundo", "titulo": "Después de aprobarlo, ¿hay que pedirle datos nuevos?",
     "ayuda": "Un segundo formulario que el área le manda desde el chat (por ejemplo, el registro de pasajeros de una plaza de hotel). Para corregir lo ya enviado alcanza con el chat.",
     "cuando": {"clave": "aprueba", "en": ["misma", "otra"]}, "recomendada": "no",
     "opciones": [["no", "No, con el chat alcanza"], ["si", "Sí, un segundo formulario"]],
     "texto": {"clave": "enc_nombre", "si": "si", "rotulo": "Nombre del segundo formulario", "ejemplo": "Registro de pasajeros"},
     "texto2": {"clave": "enc_datos", "si": "si", "rotulo": "Qué datos pide, separados por coma",
                "ejemplo": "Apellido y nombre, DNI, fecha de nacimiento, parentesco"}},
    {"clave": "ventana", "titulo": "¿Tiene fecha de apertura y cierre?", "ayuda": "Una campaña con fechas, o un formulario siempre disponible.",
     "recomendada": "no",
     "opciones": [["si", "Sí, es una campaña con fechas"], ["no", "No, está siempre abierto"]],
     "texto": {"clave": "fechas", "si": "si", "rotulo": "Fechas aproximadas", "ejemplo": "del 1/12 al 31/1"}},
    {"clave": "entrega", "titulo": "¿Quién entrega?",
     "ayuda": "Quien da en mano lo que se pidió. Si no usa el panel de Colm3na, el área registra la entrega después.",
     "cuando": {"clave": "fin", "en": ["entrega"]}, "recomendada": "area",
     "opciones": [["area", "La misma área que lo atiende"], ["delegado_panel", "Un delegado que usa el panel de Colm3na"],
                  ["delegado", "Un delegado sin acceso al panel"], ["proveedor", "El proveedor lo entrega o lo envía"]],
     "texto": {"clave": "entrega_quien", "si": ["delegado_panel", "delegado"], "rotulo": "¿Cómo se llama ese rol?",
               "ejemplo": "Delegado de la comisión gremial"}},
    {"clave": "cupo", "titulo": "¿La cantidad es limitada?", "ayuda": "Por ejemplo, unidades por seccional.",
     "cuando": {"clave": "fin", "en": ["entrega"]}, "recomendada": "no",
     "opciones": [["si", "Sí, hay cupo o stock"], ["no", "No"]]},
    {"clave": "listado", "titulo": "¿Necesitan un listado de los pedidos?", "ayuda": "Para compras, logística o para rendir cuentas.",
     "recomendada": "no", "opciones": [["si", "Sí"], ["no", "No"]]},
    {"clave": "tercero", "titulo": "¿Interviene alguien fuera del sindicato?", "ayuda": "Un proveedor, la obra social, un banco. No usa la app.",
     "recomendada": "no", "opciones": [["no", "No"], ["si", "Sí"]],
     "texto": {"clave": "tercero_nombre", "si": "si", "rotulo": "¿Quién?", "ejemplo": "Proveedor de kits"}},
    # 2026-10-28 (V4 de PLAN_ASISTENTE_TRAMITES_V2.md): un formulario de
    # Colm3na que el afiliado presenta ANTES o adjunta a este pedido. Si
    # existe en el sindicato es el punto 5 del veredicto; si no, el 6. Un
    # documento de afuera (certificado, constancia) no es esto: es un
    # campo de tipo archivo.
    {"clave": "previo", "titulo": "¿Tiene que presentar antes otro formulario de Colm3na?",
     "ayuda": "Un formulario del sindicato en Colm3na que el afiliado completa antes o adjunta a este pedido. Un documento de afuera (una constancia, un certificado) no es un formulario: es un archivo que se adjunta.",
     "recomendada": "no",
     "opciones": [["no", "No"], ["si", "Sí, otro formulario de Colm3na"]],
     "texto": {"clave": "previo_nombre", "si": "si", "rotulo": "¿Cómo se llama ese formulario?", "ejemplo": "Declaración de grupo familiar"}},
]
PREGUNTAS_TODAS = PREGUNTAS + INFERIDAS
PREGUNTAS_POR_CLAVE = {p["clave"]: p for p in PREGUNTAS_TODAS}
# Las claves que una respuesta puede traer (opciones + textos libres + la
# respuesta libre de cada pregunta hecha).
CLAVES_RESPUESTA = [p["clave"] for p in PREGUNTAS_TODAS]
CLAVES_NOTA = ["nota_" + p["clave"] for p in PREGUNTAS]
CLAVES_TEXTO = [p[t]["clave"] for p in PREGUNTAS_TODAS for t in ("texto", "texto2") if t in p] + CLAVES_NOTA
MAX_TEXTO = {c: 120 for c in CLAVES_TEXTO}
MAX_TEXTO["enc_datos"] = 400
for _c in CLAVES_NOTA:
    MAX_TEXTO[_c] = 300

# ---------------------------------------------------------------- ejemplo
# El kit escolar de La Bancaria (relevamiento T41): lo que la pantalla carga
# con "Cargar el ejemplo" y el caso dorado del test.
EJEMPLO_RELATO = (
    "En La Bancaria queremos pasar a Colm3na el pedido del kit escolar. Lo pide el afiliado titular, "
    "uno por cada hijo o nieto en edad escolar, entre principios de diciembre y fines de enero. Carga "
    "los datos del chico (apellido y nombre, DNI, fecha de nacimiento y vínculo), el nivel (inicial, "
    "primaria hasta 3.º, primaria de 4.º en adelante, secundaria) y el grado, y sube el DNI del chico, "
    "la partida de nacimiento la primera vez y la constancia de alumno regular. Lo revisa Acción Social "
    "de la seccional del afiliado; si falta algo le pide que lo complete. Cuando lo aprueba, le avisa "
    "dónde y cuándo retirarlo: en la sede, en una delegación o en la comisión gremial del banco. Se "
    "retira mostrando la credencial. Los kits son limitados por seccional y necesitamos el listado por "
    "nivel para la compra al proveedor.")
EJEMPLO_PROPUESTA = {
    "nombre": "Kit escolar 2027", "codigo": "KE27",
    "objetivo": "El afiliado pide un kit escolar por cada hijo o nieto en edad escolar y la seccional le avisa dónde retirarlo.",
    "respuestas": {
        "quien": "afiliado", "frecuencia": "familiar", "atiende": "seccional", "area": "Acción Social",
        "aprueba": "misma", "area_aprueba": "", "segundo": "no", "ventana": "si",
        "fechas": "de principios de diciembre a fines de enero",
        "requisitos": ["titular", "familiar", "edad"], "fin": "entrega",
        "lugar": "Sede, delegación o comisión gremial del banco", "entrega": "delegado",
        "entrega_quien": "Delegado de la comisión gremial", "cupo": "si", "listado": "si",
        "tercero": "si", "tercero_nombre": "Proveedor de kits"},
    "campos": [
        {"etiqueta": "¿Es la primera vez que lo pedís para este chico?", "tipo": "booleano", "obligatorio": True},
        {"etiqueta": "Datos del chico", "tipo": "separador"},
        {"etiqueta": "Apellido y nombre del chico", "tipo": "texto", "obligatorio": True},
        {"etiqueta": "DNI del chico", "tipo": "numero", "obligatorio": True, "control": "unico"},
        {"etiqueta": "Fecha de nacimiento", "tipo": "fecha", "obligatorio": True, "control": "no_futura"},
        {"etiqueta": "Vínculo", "tipo": "seleccion", "obligatorio": True, "opciones": "Hijo/a, Nieto/a"},
        {"etiqueta": "Nivel", "tipo": "seleccion", "obligatorio": True,
         "opciones": "Inicial, Primaria 1.º a 3.º, Primaria 4.º en adelante, Secundaria"},
        {"etiqueta": "Grado o año", "tipo": "seleccion", "obligatorio": True, "control": "depende",
         "opciones": "Sala de 3, Sala de 4, Sala de 5, 1.º, 2.º, 3.º, 4.º, 5.º, 6.º, 7.º"},
        {"etiqueta": "Documentación", "tipo": "separador"},
        {"etiqueta": "DNI del chico, ambas caras", "tipo": "archivo", "obligatorio": True},
        {"etiqueta": "Partida de nacimiento (solo la primera vez)", "tipo": "archivo", "obligatorio": False},
        {"etiqueta": "Constancia de alumno regular", "tipo": "archivo", "obligatorio": True},
        {"etiqueta": "Lugar de retiro", "tipo": "seleccion", "obligatorio": True,
         "opciones": "Sede de la seccional, Delegación, Comisión gremial del banco"}],
    "dudas": ["¿Aprueba la seccional o Acción Social Nacional?", "¿Desde qué grado o año ya no corresponde el kit?"],
}


# ---------------------------------------------------------------- utilidades
def _texto(v, tope: int) -> str:
    return str(v or "").strip()[:tope]


def sigla(s: str) -> str:
    """Letras y números en mayúscula, sin tildes, hasta seis: el código del
    tipo de trámite es el prefijo del número de expediente y viaja por URLs."""
    plano = unicodedata.normalize("NFD", str(s or ""))
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"[^A-Z0-9]", "", plano)[:6]


def codigo_de(nombre: str) -> str:
    """Un código a partir del nombre: inicial de cada palabra larga y los dos
    últimos dígitos de un número ("Kit escolar 2027" → "KE27")."""
    palabras = [w for w in (nombre or "").split() if len(w) > 2 or re.search(r"\d", w)]
    return sigla("".join(w[-2:] if re.search(r"\d", w) else w[0] for w in palabras)) or "NUEVO"


def normalizar_extensiones(s: str) -> str:
    """«pdf,jpg» → «pdf,jpg,jpeg». El servidor ya trata jpg y jpeg como lo
    mismo (main.extensiones_permitidas, 2026-10-16); se escriben las dos
    igual, para que el formulario diga lo que acepta."""
    lista = [x.lstrip(".") for x in re.split(r"[\s,;]+", (s or "").lower()) if x.strip(". ")]
    if not lista:
        lista = EXTENSIONES_DEFAULT.split(",")
    if "jpg" in lista and "jpeg" not in lista:
        lista.append("jpeg")
    if "jpeg" in lista and "jpg" not in lista:
        lista.append("jpg")
    return ",".join(dict.fromkeys(lista))


def pregunta_vigente(p: dict, respuestas: dict) -> bool:
    c = p.get("cuando")
    return not c or respuestas.get(c["clave"]) in c["en"]


def preguntas_vigentes(respuestas: dict) -> list:
    return [p for p in PREGUNTAS if pregunta_vigente(p, respuestas)]


def etiqueta_opcion(clave: str, valor) -> str:
    p = PREGUNTAS_POR_CLAVE.get(clave) or {}
    valores = valor if isinstance(valor, list) else [valor]
    return ", ".join(t for k, t in p.get("opciones", []) if k in valores)


# ---------------------------------------------------------------- saneo
def sanear_campo(c) -> Optional[dict]:
    if not isinstance(c, dict):
        return None
    tipo = c.get("tipo") if c.get("tipo") in TIPOS else "texto"
    control = c.get("control") if c.get("control") in CONTROLES else ""
    opciones = _texto(c.get("opciones"), 500)
    if tipo == "archivo":
        opciones = normalizar_extensiones(opciones)
    elif tipo not in CON_OPCIONES:
        opciones = ""
    return {"etiqueta": _texto(c.get("etiqueta"), 200), "tipo": tipo,
            "obligatorio": bool(c.get("obligatorio", True)) and tipo != "separador",
            "opciones": opciones, "control": control,
            # 2026-10-18: lo que explica el dato (lo ve el que arma el
            # formulario) y lo que hay que controlar: en una frase, como
            # fórmula del catálogo si se puede, o como función a desarrollar.
            "aclaracion": _texto(c.get("aclaracion"), 300),
            "regla": _texto(c.get("regla"), 300),
            "formula": _texto(c.get("formula"), 300),
            "funcion_nueva": _texto(c.get("funcion_nueva"), 200)}


def sanear_respuestas(crudas) -> tuple:
    """Devuelve (respuestas limpias, claves que venían con un valor válido).
    Un valor fuera de las opciones se descarta: la IA propone, esto decide."""
    r = crudas if isinstance(crudas, dict) else {}
    limpias, con_valor, recomendadas = {"requisitos": []}, [], []
    for p in PREGUNTAS_TODAS:
        v = r.get(p["clave"])
        validas = [k for k, _ in p["opciones"]]
        if p.get("multiple"):
            ok = [x for x in (v if isinstance(v, list) else []) if x in validas]
            if p.get("excluyente") in ok and len(ok) > 1:
                ok = [p["excluyente"]]
            limpias[p["clave"]] = ok
            if ok:
                con_valor.append(p["clave"])
        elif v in validas:
            limpias[p["clave"]] = v
            con_valor.append(p["clave"])
        for t in ("texto", "texto2"):
            if t in p and r.get(p[t]["clave"]):
                limpias[p[t]["clave"]] = _texto(r.get(p[t]["clave"]), MAX_TEXTO[p[t]["clave"]])
        if p["clave"] not in con_valor:
            # Sin respuesta, queda la recomendada: siempre hay una, y el
            # analista la confirma con un clic o la cambia.
            limpias[p["clave"]] = list(p["recomendada"]) if p.get("multiple") else p["recomendada"]
            recomendadas.append(p["clave"])
    for nk in CLAVES_NOTA:
        if r.get(nk):
            limpias[nk] = _texto(r.get(nk), MAX_TEXTO[nk])
    return limpias, con_valor, recomendadas


def sanear_extras(crudos) -> list:
    extras = []
    for x in (crudos if isinstance(crudos, list) else [])[:10]:
        if not isinstance(x, dict):
            continue
        extras.append({"nombre": _texto(x.get("nombre"), 80), "hace": _texto(x.get("hace"), 120),
                       "despues": _texto(x.get("despues"), 20) or "rev", "dato": _texto(x.get("dato"), 120),
                       "colm3na": bool(x.get("colm3na"))})
    return extras


MAX_DUDAS = 8
MAX_OPCIONES_DUDA = 6


def sanear_duda(d) -> Optional[dict]:
    """Una duda de la IA (V3): la pregunta, sobre qué pregunta del catálogo
    es (`sobre`, vacío si no es sobre ninguna) y sus opciones. Si es sobre una
    pregunta del catálogo, las opciones son las de ESA pregunta y elegir una
    la responde; si no, las que la IA propuso (hasta seis) o ninguna, y se
    contesta con texto. Un texto suelto (lo viejo) es una duda sin opciones."""
    if isinstance(d, str) or isinstance(d, (int, float)):
        d = {"pregunta": d}
    if not isinstance(d, dict):
        return None
    pregunta = _texto(d.get("pregunta"), 300)
    if not pregunta:
        return None
    sobre = d.get("sobre") if d.get("sobre") in PREGUNTAS_POR_CLAVE else ""
    if sobre:
        opciones = [list(o) for o in PREGUNTAS_POR_CLAVE[sobre]["opciones"]]
    else:
        vistas = []
        for o in (d.get("opciones") if isinstance(d.get("opciones"), list) else [])[:MAX_OPCIONES_DUDA]:
            t = _texto(o, 120)
            if t and t not in vistas:
                vistas.append(t)
        opciones = [[t, t] for t in vistas]
    return {"pregunta": pregunta, "sobre": sobre, "opciones": opciones}


def sanear_aclaraciones(crudas) -> list:
    """Lo que el analista contestó con texto a una duda (V3): viaja al
    prompt y al veredicto como «aclaración del analista»."""
    salida = []
    for a in (crudas if isinstance(crudas, list) else [])[:MAX_DUDAS + 4]:
        if not isinstance(a, dict):
            continue
        pregunta, respuesta = _texto(a.get("pregunta"), 300), _texto(a.get("respuesta"), 300)
        if pregunta and respuesta:
            salida.append({"pregunta": pregunta, "respuesta": respuesta})
    return salida


def sanear_propuesta(o, de_ia: bool = False, relato: str = "") -> dict:
    """La ENTRADA del motor, saneada. Sirve igual para lo que propone la IA,
    para el ejemplo y para lo que manda el navegador en cada cambio."""
    o = o if isinstance(o, dict) else {}
    nombre = _texto(o.get("nombre"), 120)
    respuestas, con_valor, recomendadas = sanear_respuestas(o.get("respuestas"))
    campos = [c for c in (sanear_campo(x) for x in (o.get("campos") or [])[:MAX_CAMPOS]) if c]
    return {
        "relato": _texto(relato or o.get("relato"), 6000),
        "nombre": nombre,
        "codigo": sigla(o.get("codigo")) or codigo_de(nombre),
        "objetivo": _texto(o.get("objetivo"), 300),
        "respuestas": respuestas,
        "campos": campos,
        "extras": sanear_extras(o.get("extras")),
        "dudas": [d for d in (sanear_duda(x) for x in (o.get("dudas") or [])[:MAX_DUDAS]) if d],
        "aclaraciones": sanear_aclaraciones(o.get("aclaraciones")),
        "de_ia": con_valor if de_ia else [],
        "recomendadas": recomendadas,
    }


def datos_a_campos(s: str) -> list:
    """«Apellido y nombre, DNI, fecha de nacimiento» → campos del segundo
    formulario, con el tipo adivinado por lo que dice cada uno."""
    etiquetas = [x.strip() for x in str(s or "").split(",") if x.strip()]
    if not etiquetas:
        return [{"etiqueta": "Datos solicitados", "tipo": "texto", "obligatorio": True, "opciones": "", "control": ""}]
    campos = []
    for e in etiquetas[:30]:
        n = e.lower()
        if re.search(r"fecha|nacimiento|desde|hasta", n):
            tipo = "fecha"
        elif re.match(r"(dni|cuil|cuit|cantidad|edad)\b", n):
            tipo = "numero"
        elif re.search(r"constancia|comprobante|archivo|foto|copia", n):
            tipo = "archivo"
        else:
            tipo = "texto"
        campos.append({"etiqueta": e, "tipo": tipo, "obligatorio": True,
                       "opciones": EXTENSIONES_DEFAULT if tipo == "archivo" else "",
                       "control": "no_futura" if "nacimiento" in n else "",
                       "aclaracion": "", "regla": "", "formula": "", "funcion_nueva": ""})
    return campos


# ---------------------------------------------------------------- circuito
ORDEN_CARRIL = {"af": 0, "at": 1, "ap": 2, "dl": 3, "ex": 4}


def area_atiende(entrada: dict) -> str:
    return (entrada["respuestas"].get("area") or "").strip() or "Área que atiende"


def circuito(entrada: dict) -> dict:
    """El circuito como carriles (actores), nodos, flujos y datos que
    circulan. Es la traducción fiel del prototipo: cada respuesta agrega o
    no un tramo. Los ids de nodo son estables (ini, env, rev, g1, corr, dec,
    g2, rech, pide2, enc, rec, ext2, prov, aviso, va, ent, cierra, tur, conf,
    pagx, fin) y los usan la pantalla y los actores extra ("después de")."""
    r = entrada["respuestas"]
    A = area_atiende(entrada)
    terc = r.get("tercero") == "si"
    L, N, F, D, enc = [], [], [], [], []
    col = [0]

    def lane(k, nombre, sub, colm3na=True):
        if not any(x["k"] == k for x in L):
            L.append({"k": k, "nombre": nombre, "sub": sub, "colm3na": colm3na})
        return k

    def nom(k):
        return next((x["nombre"] for x in L if x["k"] == k), "")

    def nd(id_, ln, tipo, txt, est=""):
        N.append({"id": id_, "carril": ln, "col": col[0], "tipo": tipo, "texto": txt, "estado": est})
        return id_

    def fl(de, a, t="", tipo="seq"):
        F.append({"de": de, "a": a, "etiqueta": t or "", "tipo": tipo})

    def dato(d, de, a, canal):
        D.append({"dato": d, "de": de, "a": a, "canal": canal})

    def mas():
        col[0] += 1

    AF = "Empresa" if r.get("quien") == "empresa" else "Solicitante" if r.get("quien") == "publico" else "Afiliado"
    lane("af", AF, "sin cuenta en la app" if r.get("quien") == "publico" else "desde la app")
    lane("at", A, "área central" if r.get("atiende") == "central" else "de su seccional")

    def TN():
        return lane("ex", (r.get("tercero_nombre") or "Proveedor").strip(), "fuera de Colm3na", False)

    hay_arch = any(c["tipo"] == "archivo" for c in entrada["campos"])
    nd("ini", "af", "inicio", "Necesita el trámite")
    mas(); nd("env", "af", "tarea", "Completa y envía el formulario", "iniciado"); fl("ini", "env")
    dato("Datos del formulario" + (" y documentación adjunta" if hay_arch else ""), AF, A, "Formulario del trámite")
    mas(); nd("rev", "at", "tarea", "Revisa datos y documentación" if hay_arch else "Revisa los datos", "en_tratamiento")
    fl("env", "rev", "envía")
    ult, lbl, dec = "rev", "", "at"
    hay_docs = hay_arch or any(x != "ninguno" for x in r.get("requisitos") or [])
    if hay_docs:
        mas(); nd("g1", "at", "gate", "¿Está completo?"); fl("rev", "g1")
        nd("corr", "af", "tarea", "Responde en el chat y adjunta lo que falta", "espera_info")
        fl("g1", "corr", "No: lo pide por el chat")
        fl("corr", "rev", "", "vuelta")
        dato("Pedido de lo que falta", A, AF, "Chat del trámite")
        dato("Dato o documento faltante", AF, A, "Chat del trámite, con adjunto")
        ult, lbl = "g1", "Sí"
    aprueba = r.get("aprueba") in ("misma", "otra")
    if aprueba:
        if r.get("aprueba") == "otra":
            dec = lane("ap", (r.get("area_aprueba") or "Área que aprueba").strip(), "recibe el pase")
            dato("Trámite completo", A, nom("ap"), "Pase entre áreas")
        mas(); nd("dec", dec, "tarea", "Recibe el pase, evalúa y decide" if r.get("aprueba") == "otra" else "Evalúa y decide")
        fl(ult, "dec", ((lbl + ": pase") if lbl else "pase") if r.get("aprueba") == "otra" else lbl)
        mas(); nd("g2", dec, "gate", "¿Aprobado?"); fl("dec", "g2")
        nd("rech", "af", "fin", "Rechazado", "terminado"); fl("g2", "rech", "No: explica el motivo")
        dato("Motivo del rechazo", nom(dec), AF, "Chat del trámite")
        ult, lbl = "g2", "Sí"
    if r.get("segundo") == "si" and aprueba:
        nombre2 = (r.get("enc_nombre") or "Segundo formulario").strip()
        enc.append({"nombre": nombre2, "campos": datos_a_campos(r.get("enc_datos"))})
        mas(); nd("pide2", dec, "tarea", f"Le manda «{nombre2}» por el chat", "respondido"); fl(ult, "pide2", lbl); lbl = ""
        mas(); nd("enc", "af", "tarea", f"Completa «{nombre2}»"); fl("pide2", "enc")
        dato(nombre2, AF, nom(dec), "Segundo formulario (expediente vinculado)")
        mas(); nd("rec", dec, "tarea", "Recibe los datos", "en_tratamiento"); fl("enc", "rec", "envía")
        ult = "rec"
        if terc:
            TN(); nd("ext2", "ex", "tarea", "Recibe los datos"); fl("rec", "ext2", nombre2, "msg")
            dato(nombre2, nom(dec), nom("ex"), "Fuera de Colm3na (mail, planilla)")
    fin = r.get("fin") or "respuesta"
    if fin == "entrega":
        quien = r.get("entrega") or "area"
        QN = (r.get("entrega_quien") or "Delegado").strip()
        if terc or quien == "proveedor":
            TN(); nd("prov", "ex", "tarea", "Prepara los envíos" if quien == "proveedor" else "Provee lo que se entrega")
            fl(ult, "prov", "listado de pedidos" if r.get("listado") == "si" else "pedido", "msg")
            dato("Listado de pedidos aprobados" if r.get("listado") == "si" else "Pedido de compra",
                 nom(dec), nom("ex"), "Fuera de Colm3na (hoy sin exportación)")
        elif r.get("listado") == "si":
            dato("Listado de pedidos aprobados", nom(dec), "Compras del sindicato", "Planilla (hoy sin exportación)")
        mas(); nd("aviso", dec, "tarea", "Avisa cuándo llega" if quien == "proveedor" else "Avisa dónde y cuándo retirar", "respondido")
        fl(ult, "aviso", lbl); lbl = ""
        dato("Fecha de envío" if quien == "proveedor" else "Lugar y fecha de retiro", nom(dec), AF, "Chat del trámite y aviso en la app")
        if quien == "proveedor":
            mas(); nd("entr", "ex", "tarea", "Entrega o envía al afiliado"); fl("prov", "entr")
            mas(); nd("cierra", dec, "tarea", "Confirma la entrega y cierra", "terminado"); fl("entr", "cierra", "informa la entrega", "msg")
            dato("Constancia de entrega", nom("ex"), nom(dec), "Fuera de Colm3na")
        else:
            mas(); nd("va", "af", "tarea", "Va a retirar con la credencial"); fl("aviso", "va")
            if quien == "area":
                mas(); nd("cierra", dec, "tarea", "Entrega, controla la credencial y cierra", "terminado"); fl("va", "cierra", "muestra la credencial")
                dato("Credencial digital (QR)", AF, nom(dec), "Presencial")
            elif quien == "delegado_panel":
                lane("dl", QN, "usa el panel")
                mas(); nd("cierra", "dl", "tarea", "Entrega, controla la credencial y cierra", "terminado")
                fl("va", "cierra", "muestra la credencial"); fl("aviso", "cierra", "pase del trámite")
                dato("Trámite aprobado", nom(dec), QN, "Pase entre áreas"); dato("Credencial digital (QR)", AF, QN, "Presencial")
            else:
                lane("dl", QN, "sin acceso al panel", False)
                mas(); nd("ent", "dl", "tarea", "Entrega y controla la credencial"); fl("va", "ent", "muestra la credencial")
                fl("aviso", "ent", "lista de entregas", "msg")
                mas(); nd("cierra", dec, "tarea", "Registra la entrega y cierra", "terminado"); fl("ent", "cierra", "informa la entrega", "msg")
                dato("Lista de quiénes retiran", nom(dec), QN, "Fuera de Colm3na (planilla)")
                dato("Credencial digital (QR)", AF, QN, "Presencial")
                dato("Constancia de entrega", QN, nom(dec), "Fuera de Colm3na")
    elif fin == "turno":
        mas(); nd("tur", dec, "tarea", "Propone día, hora y lugar por el chat", "respondido"); fl(ult, "tur", lbl)
        mas(); nd("conf", "af", "tarea", "Confirma o pide otro horario"); fl("tur", "conf")
        mas(); nd("cierra", dec, "tarea", "Atiende y cierra", "terminado"); fl("conf", "cierra", "asiste")
        dato("Propuesta de turno", nom(dec), AF, "Chat del trámite"); dato("Confirmación", AF, nom(dec), "Chat del trámite")
    elif fin == "pago":
        mas(); nd("cierra", dec, "tarea", "Paga o reintegra y cierra", "terminado"); fl(ult, "cierra", lbl)
        dato("Comprobante de pago", nom(dec), AF, "Chat del trámite, con adjunto")
        if terc:
            TN(); nd("pagx", "ex", "tarea", "Acredita el pago"); fl("cierra", "pagx", "orden de pago", "msg")
    else:
        mas(); nd("cierra", dec, "tarea", "Responde por el chat y cierra", "terminado"); fl(ult, "cierra", lbl)
        dato("Respuesta", nom(dec), AF, "Chat del trámite")
    carril_cierre = next(n["carril"] for n in N if n["id"] == "cierra")
    mas(); nd("fin", carril_cierre, "fin", "Fin"); fl("cierra", "fin")
    for i, x in enumerate(entrada.get("extras") or []):
        if not x["nombre"]:
            continue
        k = f"x{i}"
        ref = next((n for n in N if n["id"] == x["despues"]), None) or next(n for n in N if n["id"] == "rev")
        lane(k, x["nombre"], "usa Colm3na" if x["colm3na"] else "fuera de Colm3na", bool(x["colm3na"]))
        N.append({"id": k + "n", "carril": k, "col": ref["col"], "tipo": "tarea", "texto": x["hace"] or "Interviene", "estado": ""})
        fl(ref["id"], k + "n", "", "seq" if x["colm3na"] else "msg")
        if x["dato"]:
            dato(x["dato"], nom(ref["carril"]), x["nombre"], "Colm3na" if x["colm3na"] else "Fuera de Colm3na")
    L.sort(key=lambda l: ORDEN_CARRIL.get(l["k"], 5))
    return {"carriles": L, "nodos": N, "flujos": F, "datos": D, "encadenados": enc, "cols": col[0] + 1}


# ---------------------------------------------------------------- brechas
def brechas_de(entrada: dict, circ: Optional[dict] = None) -> dict:
    """{clave de BRECHAS: [por qué aplica, ...]}, en el orden en que se
    encontraron. Cada brecha se dispara por una respuesta o por el control
    pedido sobre un campo."""
    r = entrada["respuestas"]
    b: dict = {}

    def add(k, por_que):
        b.setdefault(k, []).append(por_que)

    if r.get("ventana") == "si":
        add("ventana", "Es una campaña con fechas.")
    req = [x for x in (r.get("requisitos") or []) if x != "ninguno"]
    if r.get("frecuencia") == "familiar" or "familiar" in req:
        add("familia", "Se pide por familiar.")
    # "unica" ya no es brecha: sale como requisito sobre sistema.tramites_de_este_tipo.
    if r.get("frecuencia") in ("familiar", "periodo"):
        add("duplicados", "Se puede pedir más de una vez (por familiar o por período).")
    if r.get("cupo") == "si":
        add("cupo", "La cantidad es limitada.")
    if r.get("listado") == "si":
        add("exportar", "Piden un listado de los pedidos.")
    if r.get("fin") == "entrega":
        add("entrega", "Termina con una entrega en persona.")
    if r.get("fin") == "turno":
        add("turnos", "Termina con un turno.")
    if r.get("fin") == "pago":
        add("pago", "Termina con un pago o reintegro.")
    if r.get("quien") == "publico":
        add("publico", "Lo inicia alguien fuera del padrón.")
    if r.get("previo") == "si":
        add("previo", f"Tiene que presentar antes «{(r.get('previo_nombre') or 'otro formulario').strip()}».")
    for c in entrada["campos"]:
        k = CONTROL_BRECHA.get(c["control"])
        if k:
            add(k, f"Campo «{c['etiqueta']}»: {CONTROLES[c['control']].lower()}.")
    if (circ or circuito(entrada))["encadenados"]:
        add("encadenado", "Hay formularios que se mandan desde el chat.")
    return b


# ---------------------------------------------------------------- formulario
def campos_colm3na(campos: list) -> list:
    """Cada campo con la forma EXACTA que acepta main._campos_tramite_validos
    (el test lo verifica pasándolos por esa función). `x_pendiente` marca un
    control que Colm3na no tiene: el importador lo va a ignorar."""
    salida = []
    for c in campos:
        if not c["etiqueta"] and c["tipo"] != "separador":
            continue
        o = {"etiqueta": c["etiqueta"], "tipo_dato": c["tipo"], "longitud_maxima": None,
             "longitud_exacta": None, "decimales": 0 if c["tipo"] == "numero" else None,
             "tipos_archivo_permitidos": normalizar_extensiones(c["opciones"]) if c["tipo"] == "archivo" else "",
             "opciones": ",".join(x.strip() for x in c["opciones"].split(",") if x.strip()) if c["tipo"] in CON_OPCIONES else "",
             "ancho": ANCHO_POR_TIPO[c["tipo"]],
             "obligatorio": False if c["tipo"] == "separador" else bool(c["obligatorio"]),
             "validaciones": []}
        if c["control"] == "no_futura" and c["tipo"] == "fecha":
            o["validaciones"].append({"fuente": "fija", "operador": "<=", "valor": "hoy",
                                      "mensaje": "No puede ser una fecha futura.", "bloquea": True})
        if c["control"] == "desde_hoy" and c["tipo"] == "fecha":
            o["validaciones"].append({"fuente": "fija", "operador": ">=", "valor": "hoy",
                                      "mensaje": "Tiene que ser desde hoy en adelante.", "bloquea": True})
        if c["control"] == "lista" and c["tipo"] in ("texto", "numero"):
            # Validación por función real (bloque 3): el dato tiene que estar
            # en el grupo familiar que cargó el sindicato, buscado por el CUIL
            # de la sesión y por este mismo campo (su índice en la lista que
            # se exporta), con aviso al salir del campo.
            o["validaciones"].append({"fuente": "funcion", "origen": "lista", "lista": LISTA_FAMILIAR,
                                      "clave2": len(salida), "trae": "existe", "formula": None,
                                      "operador": "==", "valor": "si",
                                      "mensaje": "Tiene que figurar en tu grupo familiar cargado por el sindicato.",
                                      "bloquea": True, "en_vivo": True})
        if c["control"] in CONTROL_BRECHA:
            o["x_pendiente"] = CONTROLES[c["control"]]
        if c.get("aclaracion"):
            o["x_aclaracion"] = c["aclaracion"]
        if c.get("funcion_nueva"):
            o["x_funcion_nueva"] = c["funcion_nueva"]
        o["_regla"], o["_formula"] = c.get("regla") or "", c.get("formula") or ""
        salida.append(o)
    # Segunda pasada: una fórmula escrita con el catálogo (campo.*, lista.*,
    # sistema.*) se exporta como validación por función REAL si compila
    # contra los nombres de este formulario; si no, queda como regla
    # pendiente y el prompt lo dice. Va después porque `campo.<nombre>`
    # necesita la lista entera.
    for i, o in enumerate(salida):
        regla, formula = o.pop("_regla"), o.pop("_formula")
        if formula and o["tipo_dato"] in validaciones_tramite.TIPOS_CON_FUNCION:
            es_lista = "lista." in formula
            error = validaciones_tramite.error_de_formula(formula, salida, LISTA_FAMILIAR if es_lista else None)
            if not error:
                o["validaciones"].append({"fuente": "funcion", "origen": "lista" if es_lista else "sistema",
                                          "lista": LISTA_FAMILIAR if es_lista else None,
                                          "clave2": i if es_lista else None, "trae": "", "formula": formula,
                                          "operador": None, "valor": "",
                                          "mensaje": regla or f"No cumple: {formula}.", "bloquea": True,
                                          "en_vivo": es_lista})
                continue
            o["x_regla"] = (regla or formula) + f" (la fórmula no se pudo guardar: {error})"
        elif regla:
            o["x_regla"] = regla
    return salida


def requisitos_colm3na(respuestas: dict) -> list:
    """Los requisitos para iniciar (TipoTramite.requisitos) que salen de las
    respuestas, con la forma que acepta validaciones_tramite.requisitos_saneados.
    Lo que mira al familiar (tener uno, su edad) no es un requisito del tipo
    sino una validación sobre el campo del DNI: la instrucción lo dice."""
    r = respuestas
    req = [x for x in (r.get("requisitos") or []) if x != "ninguno"]
    salida = []
    if "antiguedad" in req:
        salida.append({"origen": "sistema", "formula": f"meses_entre(sistema.fecha_afiliacion, hoy()) >= {MESES_ANTIGUEDAD}",
                       "mensaje": f"Necesitás {MESES_ANTIGUEDAD} meses de antigüedad como afiliado para pedirlo.", "bloquea": True})
    if "titular" in req:
        salida.append({"origen": "sistema", "trae": "en_padron", "operador": "==", "valor": "si",
                       "mensaje": "Tenés que estar en el padrón del sindicato como titular.", "bloquea": True})
    if "credencial" in req:
        salida.append({"origen": "sistema", "trae": "credencial_vigente", "operador": "==", "valor": "si",
                       "mensaje": "Necesitás tener la credencial vigente.", "bloquea": True})
    if r.get("frecuencia") == "unica":
        salida.append({"origen": "sistema", "trae": "tramites_de_este_tipo", "operador": "==", "valor": "0",
                       "mensaje": "Este trámite se pide una sola vez, y ya lo pediste.", "bloquea": True})
    return salida


def configuracion(entrada: dict, circ: Optional[dict] = None) -> dict:
    """Módulos, áreas, pase y los formularios (principal + encadenados) con
    la forma del contrato colm3na.tramite v1."""
    r = entrada["respuestas"]
    A = area_atiende(entrada)
    c = circ or circuito(entrada)
    mods = ["tramites"]
    if r.get("ventana") == "si":
        mods += ["notificaciones", "noticias"]
    if r.get("quien") == "empresa":
        mods.append("empleadores")
    en_secc = "cada_seccional" if r.get("atiende") == "seccional" else "sede_central"
    areas = [{"area": A, "en": en_secc, "permisos": [PERMISO_RECIBE], "para": "recibe y revisa"}]
    pase = []
    if r.get("aprueba") == "otra" and (r.get("area_aprueba") or "").strip():
        ap = r["area_aprueba"].strip()
        pase.append({"area": ap, "en": "sede_central"})
        areas.append({"area": ap, "en": "sede_central", "permisos": [PERMISO_RECIBE], "para": "aprueba"})
    if r.get("fin") == "entrega" and r.get("entrega") == "delegado_panel":
        q = (r.get("entrega_quien") or "Delegados").strip()
        pase.append({"area": q, "en": en_secc})
        areas.append({"area": q, "en": en_secc, "permisos": [PERMISO_RECIBE], "para": "entrega y cierra"})
    destino = {"modo": "misma_area_en_cada_seccional" if r.get("atiende") == "seccional" else "una_sola_area",
               "area": A, "por_defecto": {"area": A, "seccional": SECCIONAL_CENTRAL}}
    codigo = entrada["codigo"] or codigo_de(entrada["nombre"])
    forms = [{"clave": "principal", "titulo": entrada["nombre"], "codigo": codigo, "activo": True, "seccional": None,
              "destino": destino, "permite_pase": bool(pase), "areas_pase": pase,
              "campos": campos_colm3na(entrada["campos"]), "reglas_consistencia": [],
              "requisitos": requisitos_colm3na(r)}]
    for i, f in enumerate(c["encadenados"]):
        forms.append({"clave": f"encadenado_{i + 1}", "titulo": f"{f['nombre']} · {entrada['nombre']}",
                      "codigo": f"{(codigo or 'X')[:4]}C{i + 1}", "activo": True, "seccional": None,
                      "x_solo_encadenado": True, "destino": destino, "permite_pase": False, "areas_pase": [],
                      "campos": campos_colm3na(f["campos"]), "reglas_consistencia": [], "requisitos": []})
    return {"modulos": list(dict.fromkeys(mods)), "formularios": forms, "pase": pase, "areas": areas, "circuito": c}


def texto_pase(pase: list) -> str:
    return " y ".join(f"«{p['area']}»" + (" (la de cada seccional)" if p["en"] == "cada_seccional" else "") for p in pase)


# ---------------------------------------------------------------- lectura
def necesita(carril: dict, entrada: dict, cfg: dict) -> str:
    r = entrada["respuestas"]
    if carril["k"] == "af":
        if r.get("quien") == "publico":
            return "Entrada pública (hoy no existe)"
        if r.get("quien") == "empresa":
            return "Estar dada de alta como empleador, con cuenta"
        return "Estar en el padrón, con cuenta en la app"
    if not carril["colm3na"]:
        return "Acordar el canal fuera de Colm3na"
    a = next((x for x in cfg["areas"] if x["area"] == carril["nombre"]), None)
    if a:
        en_pase = any(p["area"] == a["area"] for p in cfg["pase"])
        return (f"Área «{a['area']}»" + (" en cada seccional" if a["en"] == "cada_seccional" else "")
                + " con «Trámites recibidos»" + ("; en la lista de pase" if en_pase else ""))
    return "Usuario en Colm3na con el permiso que corresponda"


def quien_hace_que(entrada: dict, cfg: dict) -> list:
    c = cfg["circuito"]
    return [{"actor": l["nombre"], "usa_colm3na": l["colm3na"], "sub": l["sub"],
             "hace": " · ".join(n["texto"] for n in c["nodos"] if n["carril"] == l["k"] and n["tipo"] == "tarea"),
             "necesita": necesita(l, entrada, cfg)} for l in c["carriles"]]


def mensajes_estados(entrada: dict, cfg: dict) -> list:
    """Lo que ve el afiliado en el chat de su trámite, estado por estado:
    solo los estados que el circuito usa (sin el rechazo)."""
    r = entrada["respuestas"]
    A = area_atiende(entrada)
    cod = entrada["codigo"] or "COD"
    usados = {n["estado"] for n in cfg["circuito"]["nodos"] if n["id"] != "rech" and n["estado"]}
    if r.get("segundo") == "si" and r.get("aprueba") != "no":
        respondido = f"Tu pedido fue aprobado. Para seguir, completá «{(r.get('enc_nombre') or 'el formulario').strip()}» que te mandamos acá."
    elif r.get("fin") == "turno":
        respondido = "Te proponemos el martes a las 10 en la sede. Confirmanos por acá o pedinos otro horario."
    elif r.get("aprueba") == "no":
        respondido = "Te respondimos."
    else:
        respondido = "Tu pedido fue aprobado." + (f" Retiralo en {r.get('lugar') or 'el lugar indicado'} con tu credencial." if r.get("fin") == "entrega" else "")
    msg = {"iniciado": f"Recibimos tu pedido. Expediente {cod}-AAAA-000001.",
           "en_tratamiento": f"{A} está revisando tu pedido.",
           "espera_info": "Nos falta la constancia de alumno regular. Respondenos por acá y adjuntala.",
           "respondido": respondido,
           "terminado": "Entregado. Cerramos el trámite." if r.get("fin") == "entrega" else "Trámite terminado."}
    return [{"estado": k, "nombre": ESTADOS[k] + (" · puede repetirse" if k == "espera_info" else ""),
             "de": A, "mensaje": msg[k]} for k in ESTADOS if k in usados]


def instruccion(entrada: dict, cfg: dict) -> dict:
    """Los pasos para crear el formulario a mano en el constructor, y el
    mismo contenido como texto para copiar."""
    r = entrada["respuestas"]
    A = area_atiende(entrada)
    p = cfg["formularios"][0]
    enc = cfg["formularios"][1:]
    n_campos = sum(1 for c in p["campos"] if c["tipo_dato"] != "separador")
    pasos = []
    if enc:
        pasos.append({"clave": "encadenados",
                      "texto": "Crear primero " + " y ".join(f"«{f['titulo']}»" for f in enc)
                               + ", cada uno con " + " y ".join(str(len(f["campos"])) for f in enc)
                               + " campos (están en el JSON), mismo destino que el principal. Dejarlos activos: se adjuntan desde el chat."})
    pasos.append({"clave": "crear", "ruta": "Trámites → Crear formularios",
                  "texto": f"Crear «{p['titulo'] or '…'}» con código {p['codigo']}, para todo el sindicato, con {n_campos} preguntas."})
    if r.get("atiende") == "seccional":
        destino = (f"Que caiga a «{A}» de la seccional de cada afiliado: en el mapa por seccional, cada seccional "
                   f"apunta a su propia «{A}». Destino por defecto: «{A}» de {SECCIONAL_CENTRAL}.")
    else:
        destino = f"Que caiga siempre a «{A}». Destino por defecto: esa misma área."
    pasos.append({"clave": "destino", "texto": destino})
    pasos.append({"clave": "pase", "texto": f"Tildar «Permite pase» y agregar a la lista {texto_pase(cfg['pase'])}." if cfg["pase"] else "Sin pase entre áreas."})
    req = [x for x in (r.get("requisitos") or []) if x != "ninguno"]
    if p.get("requisitos") or "familiar" in req or "edad" in req:
        partes = []
        if p.get("requisitos"):
            partes.append("en «Requisitos para iniciar», " + " y ".join(f"«{q['mensaje']}»" for q in p["requisitos"])
                          + (f" (ajustar los {MESES_ANTIGUEDAD} meses de antigüedad al valor real)" if "antiguedad" in req else ""))
        if "familiar" in req or "edad" in req:
            partes.append("sobre el campo del DNI del familiar, una validación «contra una lista o el padrón» del grupo familiar"
                          + (" y una fórmula con la edad (anios_entre(lista.fecha_nacimiento, hoy()))" if "edad" in req else "")
                          + "; el sindicato carga antes el grupo familiar en la pestaña Listas")
        pasos.append({"clave": "requisitos", "texto": "Requisitos: " + "; ".join(partes) + "."})
    pasos.append({"clave": "probar", "texto": "Probar con el banco de pruebas del constructor y con un pedido de punta a punta en Pruebas."})
    if r.get("ventana") == "si":
        pasos.append({"clave": "anunciar",
                      "texto": "Anunciarlo con una Noticia con el formulario para iniciar"
                               + (f" ({r['fechas']})" if r.get("fechas") else "")
                               + ", y una Notificación a las seccionales. Activar el formulario al abrir y desactivarlo al cerrar."})
    lineas = [f"Trámite: {entrada['nombre']} (código {p['codigo']})", entrada["objetivo"], "",
              "Antes: habilitar módulos " + ", ".join(cfg["modulos"])
              + f"; crear el área «{A}»" + (" en cada seccional" if r.get("atiende") == "seccional" else "")
              + " con permiso «Trámites recibidos»."]
    if enc:
        lineas.append("Crear primero: " + ", ".join(f["titulo"] for f in enc) + ".")
    lineas += ["", "Campos:"]
    for i, c in enumerate(p["campos"]):
        linea = f"{i + 1}. {c['etiqueta'] or '(separador)'} — {TIPOS[c['tipo_dato']]}"
        if c["tipo_dato"] != "separador":
            linea += ", obligatorio" if c["obligatorio"] else ", opcional"
        if c["opciones"]:
            linea += " — " + c["opciones"]
        if c["tipos_archivo_permitidos"]:
            linea += " — " + c["tipos_archivo_permitidos"]
        if c.get("x_pendiente"):
            linea += " — pendiente: " + c["x_pendiente"]
        if c.get("x_aclaracion"):
            linea += " — " + c["x_aclaracion"]
        for v in c.get("validaciones") or []:
            linea += " — validación: " + (v.get("formula") or v.get("mensaje") or "")
        if c.get("x_regla"):
            linea += " — a controlar (sin función todavía): " + c["x_regla"]
        if c.get("x_funcion_nueva"):
            linea += " — desarrollar: " + c["x_funcion_nueva"]
        lineas.append(linea)
    lineas += ["", f"Destino: «{A}» de cada seccional; por defecto, la de {SECCIONAL_CENTRAL}." if r.get("atiende") == "seccional" else f"Destino: «{A}».",
               f"Pase permitido a {texto_pase(cfg['pase'])}." if cfg["pase"] else "Sin pase."]
    return {"pasos": pasos, "texto": "\n".join(lineas)}


def preguntas_pendientes(entrada: dict, brechas: dict) -> list:
    """Solo lo que el relato no aclaró (las dudas de la IA, cada una con sus
    opciones si las tiene). Hasta el 2026-10-18 sumaba las preguntas sin
    responder y una por brecha: era un segundo cuestionario después del
    primero, y SDN lo sacó. Las brechas van en el prompt, con su salida
    provisoria."""
    return list(entrada["dudas"])


def prompt_para_code(entrada: dict, cfg: dict, brechas: dict, sindicato: Optional[dict] = None) -> str:
    """El resultado como instrucción para Code (o para quien arma el
    formulario): qué configurar, qué validar con qué función existente y
    qué función habría que desarrollar. Es texto para copiar."""
    r = entrada["respuestas"]
    p = cfg["formularios"][0]
    A = area_atiende(entrada)
    nombre_sind = (sindicato or {}).get("nombre") or "el sindicato"
    L = [f"# Trámite «{entrada['nombre'] or '…'}» (código {p['codigo']}) para {nombre_sind}",
         entrada["objetivo"] or "", "",
         "## Configurar en el panel de Colm3na (sin programar)",
         "- Módulos habilitados: " + ", ".join(MODULOS_NOMBRE.get(m, m) for m in cfg["modulos"]) + ".",
         "- Áreas: " + "; ".join(f"«{a['area']}» en {'cada seccional' if a['en'] == 'cada_seccional' else SECCIONAL_CENTRAL} ({a['para']})" for a in cfg["areas"]) + ".",
         f"- Formulario «{p['titulo']}» en Trámites → Crear formularios, destino «{A}»"
         + (" de la seccional de cada afiliado" if r.get("atiende") == "seccional" else "")
         + (f", con pase a {texto_pase(cfg['pase'])}" if cfg["pase"] else "") + "."]
    for f in cfg["formularios"][1:]:
        L.append(f"- Segundo formulario «{f['titulo']}» (se manda desde el chat), mismo destino.")
    L += ["", "## Campos del formulario"]
    for i, c in enumerate(p["campos"]):
        if c["tipo_dato"] == "separador":
            L.append(f"{i + 1}. — {c['etiqueta'] or 'separador'} —")
            continue
        linea = f"{i + 1}. {c['etiqueta']} · {TIPOS[c['tipo_dato']]}" + (", obligatorio" if c["obligatorio"] else ", opcional")
        if c["opciones"]:
            linea += f" · opciones: {c['opciones']}"
        if c["tipos_archivo_permitidos"]:
            linea += f" · archivos: {c['tipos_archivo_permitidos']}"
        if c.get("x_aclaracion"):
            linea += f"\n   Aclaración: {c['x_aclaracion']}"
        L.append(linea)
    usar, desarrollar, a_mano = [], [], []
    for i, c in enumerate(p["campos"]):
        for v in c.get("validaciones") or []:
            if v["fuente"] == "fija":
                usar.append(f"«{c['etiqueta']}»: validación fija {v['operador']} {v['valor']} → «{v['mensaje']}».")
            elif v.get("formula"):
                usar.append(f"«{c['etiqueta']}»: validación «contra una lista o el padrón», fórmula `{v['formula']}`"
                            + (f" (lista {listas_mod.PLANTILLAS[v['lista']]['nombre']}, buscada por este campo)" if v.get("origen") == "lista" else "")
                            + f" → «{v['mensaje']}»" + (", en vivo" if v.get("en_vivo") else "") + ".")
            else:
                usar.append(f"«{c['etiqueta']}»: {('tiene que estar en la lista ' + listas_mod.PLANTILLAS[v['lista']]['nombre']) if v.get('trae') == 'existe' else v['mensaje']}"
                            + (", en vivo" if v.get("en_vivo") else "") + ".")
        if c.get("x_regla"):
            a_mano.append(f"«{c['etiqueta']}»: {c['x_regla']}")
        if c.get("x_funcion_nueva"):
            desarrollar.append(f"Para «{c['etiqueta']}»: {c['x_funcion_nueva']}")
        if c.get("x_pendiente"):
            a_mano.append(f"«{c['etiqueta']}»: {c['x_pendiente']} (hoy no existe en el constructor).")
    for q in p.get("requisitos") or []:
        usar.append("Requisito para iniciar: " + (f"`{q['formula']}`" if q.get("formula") else f"`sistema.{q['trae']} {q['operador']} {q['valor']}`") + f" → «{q['mensaje']}».")
    req = [x for x in (r.get("requisitos") or []) if x != "ninguno"]
    if "familiar" in req or "edad" in req:
        a_mano.append("Sobre el campo del DNI del familiar: validación contra la lista Grupo familiar"
                      + (" y fórmula `anios_entre(lista.fecha_nacimiento, hoy()) <= N`" if "edad" in req else "")
                      + "; el sindicato carga antes el grupo familiar en Listas.")
    L += ["", "## Validaciones: usar lo que existe"]
    L += [f"- {x}" for x in usar] or ["- Ninguna además de los obligatorios."]
    if a_mano:
        L += ["", "## A controlar sin función todavía (revisa el área, o se expresa con el catálogo)"] + [f"- {x}" for x in a_mano]
    L += ["", "## Funciones a desarrollar"]
    L += [f"- {x}" for x in desarrollar] or ["- Ninguna: todo lo que se controla se puede hacer con el catálogo actual."]
    notas = [(PREGUNTAS_POR_CLAVE[k[5:]]["titulo"], r[k]) for k in CLAVES_NOTA if r.get(k)]
    if entrada.get("aclaraciones"):
        L += ["", "## Aclaraciones del analista"]
        L += [f"- {a['pregunta']} {a['respuesta']}" for a in entrada["aclaraciones"]]
    if notas or entrada["dudas"]:
        L += ["", "## A confirmar con el sindicato"]
        L += [f"- {t} {v}" for t, v in notas] + [f"- {d['pregunta']}" for d in entrada["dudas"]]
    if brechas:
        L += ["", "## Lo que Colm3na todavía no tiene (se arranca con la salida provisoria)"]
        L += [f"- {BRECHAS[k]['titulo']}: {' '.join(w)} Mientras tanto: {BRECHAS[k]['hoy']}" for k, w in brechas.items()]
    L += ["", "Catálogo de datos y funciones para las fórmulas: en el constructor, «Nombres y funciones para las fórmulas»."]
    return "\n".join(L)


# ---------------------------------------------------------------- preparar
def _norm(s: str) -> str:
    plano = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in plano if unicodedata.category(c) != "Mn").strip()


def preparar(entrada: dict, cfg: dict, brechas: dict, sindicato: Optional[dict] = None) -> dict:
    """Configurar (sin programar), ajuste y desarrollo. Con los datos del
    sindicato elegido (D6: módulos encendidos, áreas con su seccional,
    seccionales) cada ítem de "configurar" dice si YA existe o falta;
    sin sindicato, queda "sin verificar"."""
    c = cfg["circuito"]
    conocido = bool(sindicato)
    mods_on = set(sindicato.get("modulos") or []) if conocido else set()
    areas_sind = [(_norm(a.get("nombre")), _norm(a.get("seccional"))) for a in (sindicato or {}).get("areas") or []]
    # Normalizadas para comparar, originales para nombrarlas en pantalla.
    seccionales = {_norm(s): str(s) for s in (sindicato or {}).get("seccionales") or []}

    def estado(ok: Optional[bool]):
        return "sin_verificar" if ok is None else "existe" if ok else "falta"

    configurar = []
    faltan = [m for m in cfg["modulos"] if m not in mods_on] if conocido else []
    configurar.append({"clave": "modulos", "titulo": "Módulos del sindicato: " + ", ".join(MODULOS_NOMBRE[m] for m in cfg["modulos"]),
                       "detalle": ("Los habilita el admin de plataforma. Faltan: " + ", ".join(MODULOS_NOMBRE[m] for m in faltan) + ".") if faltan
                       else "Los habilita el admin de plataforma si faltan." if not conocido else "Ya están habilitados.",
                       "estado": estado(None if not conocido else not faltan)})
    for a in cfg["areas"]:
        if conocido:
            nombre = _norm(a["area"])
            if a["en"] == "cada_seccional":
                con_area = {sec for n, sec in areas_sind if n == nombre}
                sin_area = [orig for n, orig in seccionales.items() if n not in con_area]
                ok = bool(seccionales) and not sin_area
                detalle = ("Existe en todas las seccionales." if ok else
                           "Falta en: " + ", ".join(sin_area) + "." if con_area else "No existe en ninguna seccional.")
            else:
                ok = any(n == nombre for n, _ in areas_sind)
                detalle = "Ya existe." if ok else "No existe todavía."
        else:
            ok, detalle = None, ""
        configurar.append({"clave": "area", "titulo": f"Área «{a['area']}»" + (" en cada seccional" if a["en"] == "cada_seccional" else " en " + SECCIONAL_CENTRAL) + f" · {a['para']}",
                           "detalle": (detalle + " " if detalle else "") + "En Áreas y Usuarios, con el permiso «Trámites recibidos» y sus usuarios asignados.",
                           "estado": estado(ok)})
    configurar.append({"clave": "constructor", "titulo": "Quien arma el formulario",
                       "detalle": "Necesita el permiso «Crear formularios». Conviene alguien de Sede Central, porque elige a qué área cae cada pedido.",
                       "estado": "sin_verificar"})
    for l in c["carriles"]:
        if not l["colm3na"]:
            datos = ", ".join(d["dato"].lower() for d in c["datos"] if d["a"] == l["nombre"] or d["de"] == l["nombre"])
            configurar.append({"clave": "canal", "titulo": f"Acordar el canal con {l['nombre']}",
                               "detalle": f"Actúa fuera de Colm3na: definir cómo recibe y devuelve los datos ({datos}).",
                               "estado": "sin_verificar"})

    def item(k):
        b = BRECHAS[k]
        return {"clave": k, "titulo": b["titulo"], "nivel": b["nivel"], "tam": b["tam"],
                "por_que": " ".join(brechas[k]), "provisorio": b["hoy"], "recomendacion": b["rec"], "backlog": b["backlog"]}

    return {"configurar": configurar,
            "ajuste": [item(k) for k in brechas if BRECHAS[k]["nivel"] == "ajuste"],
            "desarrollo": [item(k) for k in brechas if BRECHAS[k]["nivel"] == "desarrollo"]}


# ---------------------------------------------------------------- importar
def _area_id(sindicato: Optional[dict], nombre: str, seccional: str) -> Optional[int]:
    for a in (sindicato or {}).get("areas") or []:
        if _norm(a.get("nombre")) == _norm(nombre) and _norm(a.get("seccional")) == _norm(seccional):
            return a.get("id")
    return None


def _area_existe(sindicato: Optional[dict], nombre: str, seccional: str) -> bool:
    return any(_norm(a.get("nombre")) == _norm(nombre) and _norm(a.get("seccional")) == _norm(seccional)
               for a in (sindicato or {}).get("areas") or [])


def seccional_central(sindicato: Optional[dict]) -> str:
    """La seccional con `ve_todas` (Sede Central en casi todos): ahí vive el
    destino por defecto. Sin dato, el nombre de siempre."""
    for s in (sindicato or {}).get("seccionales_detalle") or []:
        if s.get("ve_todas"):
            return s.get("nombre") or SECCIONAL_CENTRAL
    return SECCIONAL_CENTRAL


def plan_importacion(cfg: dict, sindicato: Optional[dict] = None) -> dict:
    """Qué se resuelve POR NOMBRE en el sindicato elegido y qué falta (V6):
    el destino por defecto (el área homónima de la seccional central), el
    mapa por seccional (el área homónima de cada una) y las áreas de pase.
    Puro: con los ids que traiga el sindicato, el importador de main.py
    escribe; sin sindicato, todo queda «sin resolver»."""
    conocido = bool(sindicato)
    central = seccional_central(sindicato)
    seccionales = [str(s) for s in (sindicato or {}).get("seccionales") or []]
    faltan = []
    forms = []
    for f in cfg["formularios"]:
        d = f["destino"]
        A = d["area"]
        existe_def = _area_existe(sindicato, A, central) if conocido else None
        destino = {"area": A, "seccional": central, "existe": existe_def,
                   "area_id": _area_id(sindicato, A, central) if conocido else None}
        mapa = []
        if d["modo"] == "misma_area_en_cada_seccional" and conocido:
            for s in seccionales:
                ok = _area_existe(sindicato, A, s)
                mapa.append({"seccional": s, "area": A, "existe": ok, "area_id": _area_id(sindicato, A, s)})
        pase = []
        for p in f["areas_pase"]:
            secs = seccionales if (p["en"] == "cada_seccional" and conocido) else [central]
            for s in secs:
                ok = _area_existe(sindicato, p["area"], s) if conocido else None
                pase.append({"area": p["area"], "seccional": s, "existe": ok,
                             "area_id": _area_id(sindicato, p["area"], s) if conocido else None})
        forms.append({"clave": f["clave"], "titulo": f["titulo"], "codigo": f["codigo"],
                      "destino": destino, "mapa": mapa, "pase": pase})
    if conocido:
        p = forms[0]
        if not p["destino"]["existe"]:
            faltan.append(f"Área «{p['destino']['area']}» en {central} (el destino por defecto)")
        for m in p["mapa"]:
            if not m["existe"] and m["seccional"] != central:
                faltan.append(f"Área «{m['area']}» en {m['seccional']}")
        for x in p["pase"]:
            if not x["existe"]:
                faltan.append(f"Área «{x['area']}» en {x['seccional']} (para el pase)")
    mods_on = set((sindicato or {}).get("modulos") or [])
    modulos_faltan = [m for m in cfg["modulos"] if m not in mods_on] if conocido else []
    return {"conocido": conocido, "central": central, "formularios": forms,
            "faltan": list(dict.fromkeys(faltan)), "modulos_faltan": modulos_faltan}


# ---------------------------------------------------------------- veredicto
# Las seis preguntas que SDN pidió que el resultado conteste (V5), en este
# orden y con estas claves. `si` es True / False / None (sin verificar).
PUNTOS_VEREDICTO = [
    ("importar", "¿Ya se puede importar al sindicato?"),
    ("manual", "¿Conviene terminarlo a mano, guiado, en el constructor?"),
    ("prerrequisito", "¿Hace falta preparar algo antes?"),
    ("desarrollo", "¿Hace falta desarrollar algo?"),
    ("formulario_existente", "¿Se completa o adjunta un formulario que ya existe?"),
    ("formulario_nuevo", "¿Hay que construir antes otro formulario?"),
]
COMPLEJIDAD_NOMBRE = {"alta": "alta", "media": "media", "baja": "baja", "ninguna": "ninguna"}


def formulario_existente(sindicato: Optional[dict], nombre: str) -> Optional[dict]:
    """El formulario del sindicato que se llama (más o menos) así: por
    nombre normalizado, entero o contenido."""
    n = _norm(nombre)
    if not n:
        return None
    forms = (sindicato or {}).get("formularios") or []
    for f in forms:
        if _norm(f.get("titulo")) == n or _norm(f.get("codigo")) == n:
            return f
    for f in forms:
        t = _norm(f.get("titulo"))
        if t and (n in t or t in n):
            return f
    return None


def lista_cargada(sindicato: Optional[dict], plantilla: str) -> bool:
    return any(l.get("plantilla") == plantilla and (l.get("filas") or 0) > 0
               for l in (sindicato or {}).get("listas") or [])


def necesita_lista(cfg: dict, respuestas: dict) -> Optional[str]:
    """La plantilla de lista que el formulario consulta (hoy, el grupo
    familiar: por el control «contra una lista» o por los requisitos de
    familiar / edad), o None."""
    for f in cfg["formularios"]:
        for c in f["campos"]:
            for v in c.get("validaciones") or []:
                if v.get("origen") == "lista" and v.get("lista"):
                    return v["lista"]
    req = [x for x in (respuestas.get("requisitos") or []) if x != "ninguno"]
    if "familiar" in req or "edad" in req:
        return LISTA_FAMILIAR
    return None


def complejidad_de(brechas: dict) -> str:
    """baja = solo ajustes chicos; media = un ajuste mediano o un desarrollo
    mediano; alta = un desarrollo grande; ninguna = sin brechas."""
    if not brechas:
        return "ninguna"
    tams = [(BRECHAS[k]["nivel"], BRECHAS[k]["tam"]) for k in brechas]
    if any(t == "grande" for _, t in tams):
        return "alta"
    if any(t == "mediano" for _, t in tams):
        return "media"
    return "baja"


def veredicto(entrada: dict, cfg: dict, brechas: dict, sindicato: Optional[dict] = None,
              plan: Optional[dict] = None) -> dict:
    """Las seis respuestas (V5), cada una con sí / no / sin verificar y el
    porqué en una frase, más el titular con la conclusión principal. Puro y
    determinista: lo mismo que el analista lee, lo lee el importador."""
    r = entrada["respuestas"]
    conocido = bool(sindicato)
    plan = plan or plan_importacion(cfg, sindicato)
    p = cfg["formularios"][0]
    nombre_sind = (sindicato or {}).get("nombre") or "el sindicato"
    campos_reales = [c for c in p["campos"] if c["tipo_dato"] != "separador" and c["etiqueta"]]

    # 6 y 5: el formulario previo de Colm3na.
    previo_nombre = (r.get("previo_nombre") or "").strip()
    previo = r.get("previo") == "si"
    existente = formulario_existente(sindicato, previo_nombre) if (previo and conocido) else None
    p5 = {"si": bool(existente) if (previo and conocido) else (None if previo else False)}
    p6 = {"si": (previo and conocido and not existente) if (previo and conocido) else (None if previo else False)}
    if not previo:
        p5["detalle"] = p6["detalle"] = "No: el relato no nombra otro formulario de Colm3na."
    elif not conocido:
        p5["detalle"] = p6["detalle"] = f"El relato nombra «{previo_nombre or 'otro formulario'}»: elegí el sindicato para saber si ya existe."
    elif existente:
        p5["detalle"] = (f"Sí: «{existente.get('titulo')}» ({existente.get('codigo')}) ya existe en {nombre_sind}"
                         + (", como borrador" if existente.get("borrador") else "" if existente.get("activo") else ", pero está inactivo")
                         + ". Como requisito no se puede exigir todavía: el área lo verifica al revisar.")
        p6["detalle"] = "No: el formulario previo ya existe."
    else:
        p5["detalle"] = f"No: «{previo_nombre or 'el formulario previo'}» no está entre los formularios de {nombre_sind}."
        p6["detalle"] = f"Sí: hay que construir primero «{previo_nombre or 'el formulario previo'}» (otro relato en este asistente, o el constructor)."

    # 3: prerrequisitos (área, módulo, lista con datos).
    prereq = []
    if conocido:
        prereq += plan["faltan"]
        prereq += [f"Habilitar el módulo {MODULOS_NOMBRE.get(m, m)} (lo hace plataforma)" for m in plan["modulos_faltan"]]
    lista = necesita_lista(cfg, r)
    lista_ok = None
    if lista:
        lista_ok = lista_cargada(sindicato, lista) if conocido else None
        if conocido and not lista_ok:
            prereq.append(f"Cargar la lista «{listas_mod.PLANTILLAS[lista]['nombre']}» en Listas, con los datos del sindicato")
    if not conocido:
        p3 = {"si": None, "detalle": "Elegí el sindicato para verificar áreas, módulos y listas."
              + (f" Este trámite consulta la lista «{listas_mod.PLANTILLAS[lista]['nombre']}»." if lista else "")}
    elif prereq:
        p3 = {"si": True, "detalle": "Sí: " + "; ".join(prereq) + "."}
    else:
        p3 = {"si": False, "detalle": "No: las áreas y los módulos existen"
              + (f" y la lista «{listas_mod.PLANTILLAS[lista]['nombre']}» está cargada" if lista else "") + "."}

    # 4: desarrollo y complejidad.
    comp = complejidad_de(brechas)
    desarrollos = [BRECHAS[k]["titulo"] for k in brechas if BRECHAS[k]["nivel"] == "desarrollo"]
    ajustes = [BRECHAS[k]["titulo"] for k in brechas if BRECHAS[k]["nivel"] == "ajuste"]
    if comp == "ninguna":
        p4 = {"si": False, "detalle": "No: todo lo que pide existe en Colm3na."}
    else:
        partes = []
        if desarrollos:
            partes.append("desarrollar: " + "; ".join(desarrollos))
        if ajustes:
            partes.append("ajustar: " + "; ".join(ajustes))
        p4 = {"si": True, "detalle": f"Sí, de complejidad {comp}: " + "; ".join(partes)
              + ". Se puede arrancar con la salida provisoria de cada una."}

    # 2: mejor a mano, guiado.
    manual = []
    for c in campos_reales:
        if c.get("x_pendiente"):
            manual.append(f"«{c['etiqueta']}»: {c['x_pendiente'].lower()} no existe en el constructor")
        if c.get("x_regla"):
            manual.append(f"«{c['etiqueta']}»: una regla que no se pudo escribir como fórmula")
        if c.get("x_funcion_nueva"):
            manual.append(f"«{c['etiqueta']}»: necesita una función nueva")
    if "dependencia" in brechas:
        manual.append("hay opciones que dependen de otra respuesta: unirlas en una sola lista")
    if not campos_reales:
        manual.append("el formulario no tiene preguntas todavía")
    if not conocido:
        p2 = {"si": None, "detalle": "Sin sindicato elegido no hay dónde importar: el constructor es el camino."
              + (" Además: " + "; ".join(manual) + "." if manual else "")}
    elif manual:
        p2 = {"si": True, "detalle": "Sí: se importa como borrador, pero hay que terminar a mano " + "; ".join(manual) + "."}
    else:
        p2 = {"si": False, "detalle": "No hace falta: el importador traslada todo lo que el relato pide."}

    # 1: ya se puede importar.
    if not conocido:
        p1 = {"si": None, "detalle": "Elegí el sindicato."}
    elif not campos_reales:
        p1 = {"si": False, "detalle": "Todavía no: el formulario no tiene preguntas."}
    elif p6["si"]:
        p1 = {"si": False, "detalle": f"Todavía no: primero el formulario «{previo_nombre}»."}
    elif prereq:
        p1 = {"si": False, "detalle": "Se puede importar como borrador, pero no publicar: falta lo del punto 3. El constructor lo marca al publicar."}
    elif manual:
        p1 = {"si": True, "detalle": "Sí, como borrador; lo del punto 2 se termina en el constructor antes de publicar."}
    else:
        p1 = {"si": True, "detalle": f"Sí: se importa como borrador en {nombre_sind}, con {len(campos_reales)} preguntas, y se publica desde el constructor."}

    puntos = []
    for (clave, pregunta), x in zip(PUNTOS_VEREDICTO, (p1, p2, p3, p4, p5, p6)):
        puntos.append({"clave": clave, "pregunta": pregunta, "si": x["si"], "detalle": x["detalle"]})

    # El titular: lo más bloqueante primero.
    if not conocido:
        conclusion, titular = "sin_sindicato", "Elegí el sindicato para saber si se puede importar"
    elif not campos_reales:
        conclusion, titular = "sin_campos", "Faltan las preguntas del formulario"
    elif p6["si"]:
        conclusion, titular = "formulario_nuevo", f"Primero hay que construir «{previo_nombre}»"
    elif prereq:
        conclusion, titular = "prerrequisito", "Antes hay que preparar algo en el sindicato"
    elif comp == "alta":
        conclusion, titular = "desarrollo", "Se puede arrancar, pero necesita un desarrollo de complejidad alta"
    elif manual:
        conclusion, titular = "manual", "Se importa como borrador y se termina a mano en el constructor"
    else:
        conclusion, titular = "importar", "Ya se puede importar como borrador"
    resumen = {
        "sin_sindicato": "Con el sindicato elegido, el asistente verifica áreas, módulos, listas y formularios, y puede importar.",
        "sin_campos": "Agregá en «Los datos» las preguntas que completa quien lo pide.",
        "formulario_nuevo": "Relevalo con este mismo asistente e importalo; después, este trámite.",
        "prerrequisito": "Importar crea el borrador igual; publicar va a esperar a que esté preparado lo del punto 3.",
        "desarrollo": "Importar crea el borrador con la salida provisoria; el desarrollo va al inventario de brechas.",
        "manual": "El importador traslada el formulario; lo marcado en el punto 2 lo termina quien lo publica.",
        "importar": "Lo revisa y lo publica el Super Admin desde Trámites, en el constructor.",
    }[conclusion]
    if conclusion in ("manual", "importar", "prerrequisito", "desarrollo") and p5["si"]:
        resumen += f" El área va a verificar que haya presentado «{existente.get('titulo')}»."
    return {"conclusion": conclusion, "titular": titular, "resumen": resumen, "complejidad": comp,
            "puntos": puntos, "lista": lista, "lista_cargada": lista_ok,
            "previo": {"nombre": previo_nombre, "existe": existente} if previo else None}


# ---------------------------------------------------------------- JSON v1
TIPO_PASO = {"inicio": "inicio", "tarea": "accion", "gate": "decision", "fin": "fin"}
TIPO_FLUJO = {"seq": "secuencia", "vuelta": "secuencia", "msg": "mensaje_fuera_de_colm3na"}


def exportar(entrada: dict, cfg: dict, brechas: dict, pendientes: list, generado: str) -> dict:
    """El JSON `colm3na.tramite` v1 (docs/chat/2026-10-16-contrato-importacion-tramites.md)."""
    c = cfg["circuito"]
    nombre_carril = {l["k"]: l["nombre"] for l in c["carriles"]}
    return {
        "formato": "colm3na.tramite", "version": 1, "generado": generado, "estado": "borrador",
        "tramite": {"nombre": entrada["nombre"], "objetivo": entrada["objetivo"], "relato": entrada["relato"]},
        "requisitos_previos": {"modulos": cfg["modulos"],
                               "areas": [{"area": a["area"], "en": a["en"], "permisos": a["permisos"]} for a in cfg["areas"]]},
        "formularios": cfg["formularios"],
        "circuito": {
            "actores": [{"actor": l["nombre"], "usa_colm3na": l["colm3na"]} for l in c["carriles"]],
            "pasos": [{"id": n["id"], "tipo": TIPO_PASO[n["tipo"]], "texto": n["texto"],
                       "actor": nombre_carril[n["carril"]], "estado": n["estado"] or None} for n in c["nodos"]],
            "flujos": [{"de": f["de"], "a": f["a"], "etiqueta": f["etiqueta"] or None, "tipo": TIPO_FLUJO[f["tipo"]]} for f in c["flujos"]],
            "datos": list(c["datos"]),
        },
        "respuestas": entrada["respuestas"],
        "pendientes": {"brechas": [{"clave": k, "nivel": BRECHAS[k]["nivel"], "motivo": " ".join(w), "provisorio": BRECHAS[k]["hoy"]}
                                   for k, w in brechas.items()],
                       "preguntas": [d["pregunta"] for d in pendientes],
                       "aclaraciones": list(entrada.get("aclaraciones") or [])},
    }


# ---------------------------------------------------------------- resolver
def resolver(entrada: dict, sindicato: Optional[dict] = None, hoy=None) -> dict:
    """Todo lo que la pantalla muestra en "Resultado", a partir de una entrada
    YA saneada (sanear_propuesta). Puro y determinista."""
    hoy = hoy or fechas.hoy()
    circ = circuito(entrada)
    cfg = configuracion(entrada, circ)
    b = brechas_de(entrada, circ)
    pend = preguntas_pendientes(entrada, b)
    plan = plan_importacion(cfg, sindicato)
    return {
        "nombre": entrada["nombre"], "codigo": cfg["formularios"][0]["codigo"], "objetivo": entrada["objetivo"],
        "veredicto": veredicto(entrada, cfg, b, sindicato, plan),
        "importacion": plan,
        "circuito": {k: circ[k] for k in ("carriles", "nodos", "flujos", "datos", "cols")},
        "estados": mensajes_estados(entrada, cfg),
        "quien_hace_que": quien_hace_que(entrada, cfg),
        "datos": circ["datos"],
        "instruccion": instruccion(entrada, cfg),
        "formularios": cfg["formularios"],
        "preparar": preparar(entrada, cfg, b, sindicato),
        "pendientes": pend,
        "brechas": list(b),
        "prompt": prompt_para_code(entrada, cfg, b, sindicato),
        "json": exportar(entrada, cfg, b, pend, hoy.isoformat()),
    }


def catalogo() -> dict:
    """Lo que la pantalla necesita para andar sin IA: preguntas, tipos,
    controles, brechas, estados y el ejemplo."""
    return {"preguntas": PREGUNTAS, "inferidas": INFERIDAS, "funciones": validaciones_tramite.catalogo_funcion(),
            "tipos": TIPOS, "anchos": ANCHO_POR_TIPO, "con_opciones": list(CON_OPCIONES),
            "extensiones_default": EXTENSIONES_DEFAULT, "controles": CONTROLES, "control_brecha": CONTROL_BRECHA,
            "estados": ESTADOS, "brechas": BRECHAS, "max_campos": MAX_CAMPOS,
            "puntos_veredicto": [{"clave": k, "pregunta": t} for k, t in PUNTOS_VEREDICTO],
            "ejemplo": {"relato": EJEMPLO_RELATO, "propuesta": EJEMPLO_PROPUESTA}}


def _todo_conocido() -> None:
    """Fail-closed interno: cada control con brecha apunta a una brecha que
    existe, y cada permiso o módulo que el asistente nombra está en su catálogo."""
    assert set(CONTROL_BRECHA.values()) <= set(BRECHAS)
    assert {PERMISO_RECIBE, PERMISO_CREA} <= set(permisos.SECCIONES)
    assert set(MODULOS_NOMBRE) <= set(modulos.MODULOS)
    assert set(validaciones_tramite.TIPOS_VALIDABLES) <= set(TIPOS)


_todo_conocido()
