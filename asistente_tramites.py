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
import validaciones_tramite

# ---------------------------------------------------------------- catálogo
# Lo que el constructor de Trámites tiene hoy. El test lo compara contra
# main.TIPOS_DATO_TRAMITE / ANCHOS_CAMPO_TRAMITE y db.ESTADOS_TRAMITE.
TIPOS = {
    "texto": "Texto", "numero": "Número", "fecha": "Fecha", "archivo": "Archivo",
    "seleccion": "Lista desplegable", "opcion_unica": "Opción única",
    "multiple": "Opción múltiple", "booleano": "Sí / No", "separador": "Separador",
}
ANCHOS = ("completo", "mitad", "tercio")
# El ancho que el asistente propone para cada tipo (lo que mejor queda en el
# teléfono del afiliado); el constructor deja cambiarlo.
ANCHO_POR_TIPO = {
    "texto": "completo", "numero": "tercio", "fecha": "tercio", "archivo": "completo",
    "seleccion": "mitad", "opcion_unica": "mitad", "multiple": "completo",
    "booleano": "mitad", "separador": "completo",
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
CONTROL_BRECHA = {"unico": "duplicados", "depende": "dependencia", "lista": "lista", "formato": "formato"}
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
    "requisitos": {
        "titulo": "Controlar requisitos antes de dejar iniciar", "nivel": "desarrollo", "tam": "mediano",
        "hoy": "Cualquier afiliado puede iniciarlo. El área controla el requisito al revisar y, si no lo cumple, responde y cierra.",
        "rec": "Fase 2 de validaciones del BACKLOG (fuente «sistema»): antigüedad, titularidad y edad calculadas desde el padrón, antes de mostrar los campos.",
        "backlog": "Validaciones de Trámites, fases 2–4 · Fase 2"},
    "familia": {
        "titulo": "Familiares declarados una sola vez", "nivel": "desarrollo", "tam": "grande",
        "hoy": "El formulario pide los datos y documentos del familiar en cada pedido.",
        "rec": "Grupo familiar en el perfil del afiliado, validado una vez y reutilizable por todos los trámites.",
        "backlog": ""},
    "duplicados": {
        "titulo": "Evitar pedidos repetidos", "nivel": "ajuste", "tam": "chico",
        "hoy": "Nada impide presentar dos veces lo mismo. El área lo detecta al revisar.",
        "rec": "Marca «único por afiliado» sobre un campo clave (DNI del familiar, período) que avise o bloquee.",
        "backlog": "Trámites: seis brechas · 6"},
    "dependencia": {
        "titulo": "Una respuesta que depende de otra", "nivel": "ajuste", "tam": "mediano",
        "hoy": "Las reglas entre campos comparan solo números o fechas. Salida: unir las dos preguntas en una lista («Primaria 1.º», «Primaria 2.º»…).",
        "rec": "Opciones dependientes en el constructor, evaluadas también en el servidor.",
        "backlog": "Trámites: seis brechas · 5"},
    "lista": {
        "titulo": "Controlar contra una lista del sindicato", "nivel": "desarrollo", "tam": "mediano",
        "hoy": "El área lo verifica a mano contra su propia base.",
        "rec": "Fase 3 de validaciones del BACKLOG (fuente «lista»): lista cargada por CSV, con límite de intentos.",
        "backlog": "Validaciones de Trámites, fases 2–4 · Fase 3"},
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
PREGUNTAS = [
    {"clave": "quien", "titulo": "¿Quién inicia el pedido?", "ayuda": "La persona que completa el formulario.",
     "opciones": [["afiliado", "El afiliado, desde la app"], ["empresa", "La empresa empleadora"],
                  ["publico", "Alguien que no está en el padrón (un familiar, un no afiliado)"]]},
    {"clave": "frecuencia", "titulo": "¿Cuántas veces lo puede pedir?", "ayuda": "Esto define si hace falta controlar pedidos repetidos.",
     "opciones": [["libre", "Cada vez que lo necesite"], ["periodo", "Una vez por período o campaña"],
                  ["familiar", "Uno por cada familiar"], ["unica", "Una sola vez"]]},
    {"clave": "atiende", "titulo": "¿Quién lo recibe y lo revisa?", "ayuda": "En Colm3na cada área pertenece a una seccional.",
     "opciones": [["seccional", "Un área de la seccional del afiliado"], ["central", "Siempre la misma área central"]],
     "texto": {"clave": "area", "rotulo": "Nombre del área", "ejemplo": "Acción Social"}},
    {"clave": "aprueba", "titulo": "¿Hace falta una aprobación?", "ayuda": "Si aprueba otra área, el trámite se le pasa desde el chat.",
     "opciones": [["misma", "Sí, la misma área que lo revisa"], ["otra", "Sí, otra área"], ["no", "No, solo se responde"]],
     "texto": {"clave": "area_aprueba", "si": "otra", "rotulo": "¿Qué área aprueba?", "ejemplo": "Secretaría General"}},
    {"clave": "segundo", "titulo": "Después de aprobarlo, ¿hay que pedirle datos nuevos?",
     "ayuda": "Un segundo formulario que el área le manda desde el chat, con datos que después se procesan. Por ejemplo, aprobada la plaza de hotel, el registro de pasajeros que se envía al hotel. Para corregir o completar lo ya enviado alcanza con el chat.",
     "cuando": {"clave": "aprueba", "en": ["misma", "otra"]},
     "opciones": [["no", "No, con el chat alcanza"], ["si", "Sí, un segundo formulario"]],
     "texto": {"clave": "enc_nombre", "si": "si", "rotulo": "Nombre del segundo formulario", "ejemplo": "Registro de pasajeros"},
     "texto2": {"clave": "enc_datos", "si": "si", "rotulo": "Qué datos pide, separados por coma",
                "ejemplo": "Apellido y nombre, DNI, fecha de nacimiento, parentesco"}},
    {"clave": "ventana", "titulo": "¿Tiene fecha de apertura y cierre?", "ayuda": "Una campaña con fechas, o un formulario siempre disponible.",
     "opciones": [["si", "Sí, es una campaña con fechas"], ["no", "No, está siempre abierto"]],
     "texto": {"clave": "fechas", "si": "si", "rotulo": "Fechas aproximadas", "ejemplo": "del 1/12 al 31/1"}},
    {"clave": "requisitos", "titulo": "¿Qué tiene que cumplir quien lo pide?", "ayuda": "Marcá todas las que correspondan.",
     "multiple": True, "excluyente": "ninguno",
     "opciones": [["antiguedad", "Una antigüedad mínima como afiliado"], ["titular", "Ser el afiliado titular"],
                  ["familiar", "Tener un familiar a cargo"], ["edad", "Una edad (propia o del familiar)"],
                  ["ninguno", "Ninguna: alcanza con estar afiliado"]]},
    {"clave": "fin", "titulo": "¿Cómo termina?", "ayuda": "Lo último que pasa antes de cerrar el expediente.",
     "opciones": [["entrega", "Se entrega algo en persona"], ["respuesta", "Con una respuesta o un documento por el chat"],
                  ["turno", "Con un turno o una entrevista"], ["pago", "Con un pago o un reintegro"]],
     "texto": {"clave": "lugar", "si": "entrega", "rotulo": "¿Dónde se entrega o retira?", "ejemplo": "Sede, delegación, comisión gremial"}},
    {"clave": "entrega", "titulo": "¿Quién entrega?",
     "ayuda": "Quien da en mano lo que se pidió. Si no usa el panel de Colm3na, el área registra la entrega después.",
     "cuando": {"clave": "fin", "en": ["entrega"]},
     "opciones": [["area", "La misma área que lo atiende"], ["delegado_panel", "Un delegado que usa el panel de Colm3na"],
                  ["delegado", "Un delegado sin acceso al panel"], ["proveedor", "El proveedor lo entrega o lo envía"]],
     "texto": {"clave": "entrega_quien", "si": ["delegado_panel", "delegado"], "rotulo": "¿Cómo se llama ese rol?",
               "ejemplo": "Delegado de la comisión gremial"}},
    {"clave": "cupo", "titulo": "¿La cantidad es limitada?", "ayuda": "Por ejemplo, unidades por seccional.",
     "cuando": {"clave": "fin", "en": ["entrega"]},
     "opciones": [["si", "Sí, hay cupo o stock"], ["no", "No"]]},
    {"clave": "listado", "titulo": "¿Necesitan un listado de los pedidos?", "ayuda": "Para compras, logística o para rendir cuentas.",
     "opciones": [["si", "Sí"], ["no", "No"]]},
    {"clave": "tercero", "titulo": "¿Interviene alguien fuera del sindicato?", "ayuda": "Un proveedor, la obra social, un banco. No usa la app.",
     "opciones": [["no", "No"], ["si", "Sí"]],
     "texto": {"clave": "tercero_nombre", "si": "si", "rotulo": "¿Quién?", "ejemplo": "Proveedor de kits"}},
    {"clave": "actores", "titulo": "¿Están todos los que intervienen?",
     "ayuda": "Cada uno con lo que hace en el circuito. Si falta alguien, agregalo con su acción y el momento en que actúa.",
     "actores": True},
    {"clave": "campos", "titulo": "¿Estos son los datos que se piden?",
     "ayuda": "Revisá, corregí o agregá. El tipo y el control salen del constructor de Colm3na.", "campos": True},
]
PREGUNTAS_POR_CLAVE = {p["clave"]: p for p in PREGUNTAS}
# Las claves que una respuesta puede traer (opciones + textos libres).
CLAVES_RESPUESTA = [p["clave"] for p in PREGUNTAS if not p.get("campos") and not p.get("actores")]
CLAVES_TEXTO = [p[t]["clave"] for p in PREGUNTAS for t in ("texto", "texto2") if t in p]
MAX_TEXTO = {c: 120 for c in CLAVES_TEXTO}
MAX_TEXTO["enc_datos"] = 400

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
    """«pdf,jpg» → «pdf,jpg,jpeg»: hoy el servidor compara la extensión tal
    cual (BACKLOG, brecha 3), así que el asistente propone siempre las dos."""
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
            "opciones": opciones, "control": control}


def sanear_respuestas(crudas) -> tuple:
    """Devuelve (respuestas limpias, claves que venían con un valor válido).
    Un valor fuera de las opciones se descarta: la IA propone, esto decide."""
    r = crudas if isinstance(crudas, dict) else {}
    limpias, con_valor = {"requisitos": []}, []
    for p in PREGUNTAS:
        if p.get("campos") or p.get("actores"):
            continue
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
    return limpias, con_valor


def sanear_extras(crudos) -> list:
    extras = []
    for x in (crudos if isinstance(crudos, list) else [])[:10]:
        if not isinstance(x, dict):
            continue
        extras.append({"nombre": _texto(x.get("nombre"), 80), "hace": _texto(x.get("hace"), 120),
                       "despues": _texto(x.get("despues"), 20) or "rev", "dato": _texto(x.get("dato"), 120),
                       "colm3na": bool(x.get("colm3na"))})
    return extras


def sanear_propuesta(o, de_ia: bool = False, relato: str = "") -> dict:
    """La ENTRADA del motor, saneada. Sirve igual para lo que propone la IA,
    para el ejemplo y para lo que manda el navegador en cada cambio."""
    o = o if isinstance(o, dict) else {}
    nombre = _texto(o.get("nombre"), 120)
    respuestas, con_valor = sanear_respuestas(o.get("respuestas"))
    campos = [c for c in (sanear_campo(x) for x in (o.get("campos") or [])[:MAX_CAMPOS]) if c]
    return {
        "relato": _texto(relato or o.get("relato"), 6000),
        "nombre": nombre,
        "codigo": sigla(o.get("codigo")) or codigo_de(nombre),
        "objetivo": _texto(o.get("objetivo"), 300),
        "respuestas": respuestas,
        "campos": campos,
        "extras": sanear_extras(o.get("extras")),
        "dudas": [_texto(d, 300) for d in (o.get("dudas") or [])[:8] if _texto(d, 300)],
        "de_ia": con_valor if de_ia else [],
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
                       "control": "no_futura" if "nacimiento" in n else ""})
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
    if req:
        add("requisitos", "Requisitos: " + ", ".join(etiqueta_opcion("requisitos", x).lower() for x in req) + ".")
    if r.get("frecuencia") == "familiar" or "familiar" in req:
        add("familia", "Se pide por familiar.")
    if r.get("frecuencia") in ("familiar", "periodo", "unica"):
        add("duplicados", "Tiene límite de pedidos.")
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
        if c["control"] in CONTROL_BRECHA:
            o["x_pendiente"] = CONTROLES[c["control"]]
        salida.append(o)
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
              "campos": campos_colm3na(entrada["campos"]), "reglas_consistencia": []}]
    for i, f in enumerate(c["encadenados"]):
        forms.append({"clave": f"encadenado_{i + 1}", "titulo": f"{f['nombre']} · {entrada['nombre']}",
                      "codigo": f"{(codigo or 'X')[:4]}C{i + 1}", "activo": True, "seccional": None,
                      "x_solo_encadenado": True, "destino": destino, "permite_pase": False, "areas_pase": [],
                      "campos": campos_colm3na(f["campos"]), "reglas_consistencia": []})
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
        lineas.append(linea)
    lineas += ["", f"Destino: «{A}» de cada seccional; por defecto, la de {SECCIONAL_CENTRAL}." if r.get("atiende") == "seccional" else f"Destino: «{A}».",
               f"Pase permitido a {texto_pase(cfg['pase'])}." if cfg["pase"] else "Sin pase."]
    return {"pasos": pasos, "texto": "\n".join(lineas)}


def preguntas_pendientes(entrada: dict, brechas: dict) -> list:
    """Las dudas del relato, las preguntas sin responder y, por cada brecha,
    si el sindicato acepta arrancar con la salida provisoria."""
    r = entrada["respuestas"]
    pend = list(entrada["dudas"])
    for p in preguntas_vigentes(r):
        if p.get("actores"):
            continue
        v = len(entrada["campos"]) if p.get("campos") else len(r.get(p["clave"]) or []) if p.get("multiple") else r.get(p["clave"])
        if not v:
            pend.append(p["titulo"])
    for k in brechas:
        pend.append(f"¿Aceptan arrancar así mientras tanto? {BRECHAS[k]['titulo']}: {BRECHAS[k]['hoy']}")
    return pend


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
                       "preguntas": pendientes},
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
    return {
        "nombre": entrada["nombre"], "codigo": cfg["formularios"][0]["codigo"], "objetivo": entrada["objetivo"],
        "circuito": {k: circ[k] for k in ("carriles", "nodos", "flujos", "datos", "cols")},
        "estados": mensajes_estados(entrada, cfg),
        "quien_hace_que": quien_hace_que(entrada, cfg),
        "datos": circ["datos"],
        "instruccion": instruccion(entrada, cfg),
        "formularios": cfg["formularios"],
        "preparar": preparar(entrada, cfg, b, sindicato),
        "pendientes": pend,
        "brechas": list(b),
        "json": exportar(entrada, cfg, b, pend, hoy.isoformat()),
    }


def catalogo() -> dict:
    """Lo que la pantalla necesita para andar sin IA: preguntas, tipos,
    controles, brechas, estados y el ejemplo."""
    return {"preguntas": PREGUNTAS, "tipos": TIPOS, "anchos": ANCHO_POR_TIPO, "con_opciones": list(CON_OPCIONES),
            "extensiones_default": EXTENSIONES_DEFAULT, "controles": CONTROLES, "control_brecha": CONTROL_BRECHA,
            "estados": ESTADOS, "brechas": BRECHAS, "max_campos": MAX_CAMPOS,
            "ejemplo": {"relato": EJEMPLO_RELATO, "propuesta": EJEMPLO_PROPUESTA}}


def _todo_conocido() -> None:
    """Fail-closed interno: cada control con brecha apunta a una brecha que
    existe, y cada permiso o módulo que el asistente nombra está en su catálogo."""
    assert set(CONTROL_BRECHA.values()) <= set(BRECHAS)
    assert {PERMISO_RECIBE, PERMISO_CREA} <= set(permisos.SECCIONES)
    assert set(MODULOS_NOMBRE) <= set(modulos.MODULOS)
    assert set(validaciones_tramite.TIPOS_VALIDABLES) <= set(TIPOS)


_todo_conocido()
