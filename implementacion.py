"""Mesa de implementación: el motor PURO (PLAN_IMPLEMENTACION.md).

No importa `db`: los seis tipos de tarjeta, los estados y sus transiciones,
a quién le toca después de cada acto, la validación de una tarjeta nueva, los
topes y permisos de archivos y notas internas, y las seis fases por defecto.
Se prueba solo y rápido; `db.py` lo usa para decidir y guardar.

Las fechas viajan como texto ("AAAA-MM-DD" para un límite, "AAAA-MM-DD
HH:MM:SS" de Buenos Aires para un sello); la hora la da `fechas.py`, acá no se
llama a `datetime.now()` ni a `date.today()`.
"""
import csv
import io
import json
import re
import unicodedata
from pathlib import Path
from datetime import datetime
from typing import NamedTuple

import fechas
import listas

# ---------- Lados ----------
EQUIPO, SINDICATO = "equipo", "sindicato"
LADOS = (EQUIPO, SINDICATO)

# Todas las tablas del módulo empiezan así (db.py). Las usan las guardas de
# I3: clonar_demo_a_pruebas.py las deja fuera del dump y cargar_demo.py no las
# toca, y un test falla si una tabla Impl nueva se escapa.
PREFIJO_TABLAS = "impl"

# ---------- Estados ----------
ABIERTA, EN_CURSO, RESPONDIDA, CERRADA = "abierta", "en_curso", "respondida", "cerrada"
APROBADA, RECHAZADA = "aprobada", "rechazada"
ESTADOS = (ABIERTA, EN_CURSO, RESPONDIDA, CERRADA, APROBADA, RECHAZADA)
ESTADOS_ABIERTOS = (ABIERTA, EN_CURSO, RESPONDIDA)
ESTADOS_FINALES = (CERRADA, APROBADA, RECHAZADA)
NOMBRES_ESTADO = {
    ABIERTA: "Abierta", EN_CURSO: "En curso", RESPONDIDA: "Respondida",
    CERRADA: "Cerrada", APROBADA: "Aprobada", RECHAZADA: "Rechazada",
}

# Un solo flujo: Abierta -> En curso -> Respondida -> Cerrada, y Reabrir
# (Cerrada -> Abierta). Se puede saltear un paso hacia adelante y volver a
# "en curso" desde Respondida (la respuesta no alcanzó). Aprobada/Rechazada no
# se alcanzan por acá: solo `resolver_aprobacion`, y son inmutables.
TRANSICIONES = {
    ABIERTA: (EN_CURSO, RESPONDIDA, CERRADA),
    EN_CURSO: (RESPONDIDA, CERRADA),
    RESPONDIDA: (EN_CURSO, CERRADA),
    CERRADA: (ABIERTA,),
    APROBADA: (),
    RECHAZADA: (),
}

# ---------- Tipos de tarjeta ----------
PEDIDO, CONSULTA, ENTREGA, APROBACION, ERROR, AVISO = (
    "pedido", "consulta", "entrega", "aprobacion", "error", "aviso")

# Color e ícono FIJOS: no toman la marca de nadie (el plan).
TIPOS = {
    PEDIDO: {"nombre": "Pedido", "color": "#2563EB", "icono": "mano",
             "para": "Algo que un lado necesita del otro",
             "cierra": "Respondida, después Cerrada"},
    CONSULTA: {"nombre": "Consulta", "color": "#7C3AED", "icono": "pregunta",
               "para": "Una pregunta",
               "cierra": "Respondida, después Cerrada"},
    ENTREGA: {"nombre": "Entrega de archivo", "color": "#0D9488", "icono": "archivo",
              "para": "Subir un archivo pedido o enviar uno",
              "cierra": "Cerrada al recibirlo"},
    APROBACION: {"nombre": "Aprobación", "color": "#16A34A", "icono": "sello",
                 "para": "Autorización formal",
                 "cierra": "Aprobada o Rechazada, con quién y cuándo; no se modifica"},
    ERROR: {"nombre": "Error", "color": "#DC2626", "icono": "alerta",
            "para": "Algo que no funciona",
            "cierra": "Respondida, después Cerrada"},
    AVISO: {"nombre": "Aviso", "color": "#D97706", "icono": "campana",
            "para": "Informar, sin esperar respuesta",
            "cierra": "Nace cerrada; registra quién la leyó"},
}
ORDEN_TIPOS = (PEDIDO, CONSULTA, ENTREGA, APROBACION, ERROR, AVISO)

# ---------- Topes ----------
TOPE_ARCHIVO = 20 * 1024 * 1024        # 20 MB (I5)
TOPE_TITULO = 140
TOPE_TEXTO = 5000
TOPE_NOMBRE_ARCHIVO = 200
TOPE_RESPONSABLE = 200
TOPE_HITO = 200
TOPE_NOMBRE = 120                      # proyecto, usuario
TOPE_MAIL = 254
TOPE_CLAVE = 128
TOPE_FORMULARIO = 41 * 1024 * 1024     # el cuerpo entero de un envío: 40 MB de archivos + el texto
MAX_ID = 2 ** 31 - 1                   # un id que no entra en int4 no existe (404), nunca 500


# ---------- Saneo ÚNICO del texto de entrada (QA-04) ----------
def limpiar_texto(valor) -> str:
    """Todo texto que entra a la mesa (formularios, JSON, query, login) pasa por
    acá antes de usarse: sin NUL ni sustitutos sueltos (Postgres y el encoder
    de UTF-8 los rechazan y salía un 500), en NFC y recortado. Nunca falla."""
    if valor is None:
        return ""
    texto = valor if isinstance(valor, str) else str(valor)
    texto = texto.replace("\x00", "").encode("utf-8", "ignore").decode("utf-8")
    return unicodedata.normalize("NFC", texto).strip()


def exigir_largo(texto: str, tope: int, campo: str) -> str:
    """El texto, o ErrorImpl 400 con un mensaje claro si pasa del tope."""
    if len(texto) > tope:
        raise ErrorImpl("texto", f"{campo} admite hasta {tope} caracteres.")
    return texto


def id_valido(numero) -> bool:
    """Un id que cabe en int4 (las columnas de la mesa)."""
    return isinstance(numero, int) and not isinstance(numero, bool) and -MAX_ID <= numero <= MAX_ID


_MIME_RE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


def mime_seguro(mime) -> str:
    """El tipo del archivo reducido a `tipo/subtipo` con caracteres de token;
    lo que no lo es (parámetros, NUL, cabeceras raras) queda como binario."""
    base = limpiar_texto(mime).lower().split(";")[0].strip()
    return base[:120] if _MIME_RE.match(base) else "application/octet-stream"

# ---------- Fases por defecto (I7: el plan v0.2 de La Bancaria) ----------
FASES_POR_DEFECTO = (
    ("Preparar", "Armar el equipo, los accesos y el proyecto."),
    ("Acordar", "Cerrar con el sindicato el alcance, los roles y las fechas."),
    ("Relevar", "Recibir el padrón, los convenios, los trámites y los recibos de muestra."),
    ("Configurar", "Cargar conceptos, reglas, trámites, áreas y usuarios."),
    ("Piloto", "Probar con un grupo chico y corregir."),
    ("Implementación total", "Abrir la plataforma a todos los afiliados y acompañar."),
)

ACCIONES = (
    "crear_proyecto", "crear", "responder", "reasignar", "resolver", "subir",
    "bajar", "borrar_archivo", "hito", "hito_nuevo", "leer_aviso",
    # Entrega de archivo (I16): quien la recibe la da por recibida o avisa un problema.
    "recibido", "problema",
    # Usuarios del sindicato en la herramienta (bloque 2): solo las ve el equipo.
    "usuario_alta", "usuario_clave", "usuario_estado",
    # Plan operativo y exportación (bloque 3/4).
    "hito_editar", "hito_borrar", "etapa_renombrar", "hitos_semilla", "exportar",
)

# Claves de los usuarios del sindicato (I2). La que escribe el equipo es
# transitoria y se cambia en el primer ingreso; la que elige la persona es
# más larga (mismo piso que el panel del sindicato).
CLAVE_INICIAL_MINIMA = 6
CLAVE_MINIMA = 8


class ErrorImpl(Exception):
    """Una regla de la mesa que no se cumple. `codigo` es corto y estable (las
    rutas lo mapean a 400/403/404/409); `mensaje` es lo que lee la persona."""

    def __init__(self, codigo: str, mensaje: str = ""):
        super().__init__(mensaje or codigo)
        self.codigo = codigo
        self.mensaje = mensaje or codigo


class Actor(NamedTuple):
    """Quien hace un acto: o un usuario de plataforma (lado equipo) o un
    usuario Impl (lado sindicato). El nombre se copia: la traza no depende de
    que la cuenta exista después."""
    lado: str
    id: int
    nombre: str


# ---------- Lados ----------
def otro_lado(lado: str) -> str:
    return SINDICATO if lado == EQUIPO else EQUIPO


def nombre_lado(lado: str) -> str:
    return {EQUIPO: "Colm3na", SINDICATO: "el sindicato"}.get(lado, "")


def texto_espera(lado_que_espera: str) -> str:
    """«espera al sindicato» / «espera a Colm3na»; vacío si nadie espera."""
    if lado_que_espera == SINDICATO:
        return "espera al sindicato"
    if lado_que_espera == EQUIPO:
        return "espera a Colm3na"
    return ""


# ---------- Estados ----------
def estado_inicial(tipo: str) -> str:
    """Un aviso nace cerrado; el resto, abierto."""
    return CERRADA if tipo == AVISO else ABIERTA


def puede_transicionar(tipo: str, desde: str, hasta: str) -> bool:
    if tipo not in TIPOS or desde not in TRANSICIONES or hasta not in ESTADOS:
        return False
    if tipo == AVISO:
        return False               # no espera respuesta: nace cerrado y se queda así
    if tipo == APROBACION and hasta == CERRADA:
        return False               # una aprobación se resuelve, no se "cierra"
    if tipo == APROBACION and desde == CERRADA:
        return False
    if tipo == ENTREGA and hasta == CERRADA:
        return False               # una entrega la cierra quien la recibe con «recibido» (I16)
    return hasta in TRANSICIONES[desde]


def es_final(estado: str) -> bool:
    return estado in ESTADOS_FINALES


def es_inmutable(tipo: str, estado: str) -> bool:
    """Una aprobación resuelta no se toca más: ni estado ni hilo."""
    return tipo == APROBACION and estado in (APROBADA, RECHAZADA)


def a_quien_le_toca(estado: str, lado_actor: str) -> str:
    """A quién le toca DESPUÉS de que `lado_actor` hizo un acto que dejó la
    tarjeta en `estado`. Vacío = a nadie (está cerrada o resuelta).

    - cerrada / aprobada / rechazada: a nadie.
    - en curso: a quien la tomó (está trabajando en ella).
    - abierta / respondida: al otro lado (le toca contestar o cerrar)."""
    if estado in ESTADOS_FINALES:
        return ""
    if estado == EN_CURSO:
        return lado_actor
    return otro_lado(lado_actor)


def lado_inicial(tipo: str, lado_autor: str) -> str:
    """Al crear: le toca al otro lado; un aviso no espera a nadie."""
    if tipo == AVISO:
        return ""
    return otro_lado(lado_autor)


def puede_resolver_aprobacion(tipo: str, estado: str, autor_lado: str, lado_actor: str) -> bool:
    """UNA sola regla: una aprobación abierta la resuelve SOLO el lado que no la
    pidió, en cualquier estado y sin importar a quién le toque el turno. Quien
    la pidió (`autor_lado`) nunca se la aprueba a sí mismo, ni tomándola «en
    curso» ni porque la otra parte contestó algo. Sin autor conocido, nadie."""
    return (tipo == APROBACION and estado in ESTADOS_ABIERTOS
            and autor_lado in LADOS and lado_actor in LADOS and lado_actor != autor_lado)


# ---------- Validación ----------
def fecha_valida(texto: str) -> bool:
    try:
        datetime.strptime((texto or "").strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validar_tarjeta_nueva(tipo, titulo, texto, fecha_limite="") -> dict:
    """Devuelve {"ok": bool, "errores": {campo: mensaje}, "datos": {...}} con
    los textos ya recortados. Pide tres cosas: tipo, título y texto."""
    errores = {}
    tipo = limpiar_texto(tipo)
    titulo = limpiar_texto(titulo)
    texto = limpiar_texto(texto)
    fecha_limite = limpiar_texto(fecha_limite)
    if tipo not in TIPOS:
        errores["tipo"] = "Elegí qué tipo de tarjeta es."
    if not titulo:
        errores["titulo"] = "Ponele un título."
    elif len(titulo) > TOPE_TITULO:
        errores["titulo"] = f"El título admite hasta {TOPE_TITULO} caracteres."
    if not texto:
        errores["texto"] = "Contá de qué se trata."
    elif len(texto) > TOPE_TEXTO:
        errores["texto"] = f"El texto admite hasta {TOPE_TEXTO} caracteres."
    if fecha_limite:
        # El mismo parseo de fecha de formulario del proyecto: se guarda ISO
        # (la app compara fechas como texto) o se rechaza.
        iso = listas.normalizar_fecha(fecha_limite)
        if iso is None:
            errores["fecha_limite"] = "La fecha límite no se entiende."
        else:
            fecha_limite = iso
    return {"ok": not errores, "errores": errores,
            "datos": {"tipo": tipo, "titulo": titulo, "texto": texto, "fecha_limite": fecha_limite}}


def vencida(fecha_limite: str, estado: str, hoy: str = None) -> bool:
    """Con fecha límite pasada y todavía sin cerrar."""
    if not fecha_limite or estado in ESTADOS_FINALES:
        return False
    return fecha_limite < (hoy or fechas.hoy_texto())


# ---------- Archivos ----------
def validar_archivo(nombre: str, tamano: int) -> str:
    """"" si sirve; si no, el motivo. Las rutas le pasan `nombre_seguro(...)`:
    un nombre en blanco entra como «archivo», no se descarta."""
    if not (nombre or "").strip():
        return "El archivo no tiene nombre."
    if tamano <= 0:
        return "El archivo está vacío."
    if tamano > TOPE_ARCHIVO:
        return f"El archivo pesa más de {TOPE_ARCHIVO // (1024 * 1024)} MB."
    return ""


def nombre_seguro(nombre: str) -> str:
    """Sin ruta ni caracteres de control, con tope de largo."""
    base = limpiar_texto(nombre).replace("\\", "/").split("/")[-1]
    base = "".join(c for c in base if c.isprintable()).strip()
    return base[:TOPE_NOMBRE_ARCHIVO] or "archivo"


def puede_bajar_archivo(lado_actor: str, actor_id: int, datos_personales: bool,
                        subido_por_lado: str, subido_por_id: int, borrado: bool = False) -> bool:
    """Un archivo sin datos personales lo baja cualquiera del proyecto; con
    datos personales, el equipo y quien lo subió (I5). Uno borrado, nadie."""
    if borrado or lado_actor not in LADOS:
        return False
    if not datos_personales:
        return True
    if lado_actor == EQUIPO:
        return True
    return lado_actor == subido_por_lado and actor_id == subido_por_id


def puede_borrar_archivo(lado_actor: str, actor_id: int, subido_por_lado: str, subido_por_id: int) -> bool:
    """Lo borra el equipo o quien lo subió."""
    if lado_actor == EQUIPO:
        return True
    return lado_actor == subido_por_lado and actor_id == subido_por_id


# ---------- Notas internas ----------
def puede_ver_nota_interna(lado: str) -> bool:
    """Las notas «solo equipo» las ve únicamente el equipo (I8)."""
    return lado == EQUIPO


def puede_escribir_nota_interna(lado: str) -> bool:
    return lado == EQUIPO


# ---------- Avance ----------
def porcentaje(hechos: int, total: int) -> int:
    return int(round(100 * hechos / total)) if total else 0


# ---------- Registro de aprobaciones (CSV) ----------
ENCABEZADO_APROBACIONES = ("Número", "Título", "Estado", "Pidió", "Resolvió", "Cuándo", "Etapa", "Código")


def aprobaciones_csv(filas: list) -> str:
    """El registro de aprobaciones como CSV (separador `;`, BOM para Excel).
    Cada fila es un dict con numero, titulo, estado, autor, resuelta_por,
    resuelta_en, etapa."""
    sal = io.StringIO()
    w = csv.writer(sal, delimiter=";", lineterminator="\r\n")
    w.writerow(ENCABEZADO_APROBACIONES)
    for f in filas:
        w.writerow([_celda(f.get("numero", "")), _celda(f.get("titulo", "")),
                    NOMBRES_ESTADO.get(f.get("estado"), f.get("estado", "")),
                    _celda(f.get("autor", "")), _celda(f.get("resuelta_por", "")),
                    f.get("resuelta_en", ""), _celda(f.get("etapa", "")), _celda(f.get("codigo", ""))])
    return "﻿" + sal.getvalue()


def _celda(valor) -> str:
    """Neutraliza una fórmula de planilla (=, +, -, @) al abrir el CSV."""
    texto = str(valor if valor is not None else "")
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


# ---------- Qué puede hacer este actor ahora (lo calcula el servidor) ----------
def puede_dar_entrega(tipo: str, estado: str, autor_lado: str, lado_actor: str) -> bool:
    """UNA sola regla (I16): una entrega abierta la da por recibida, o avisa un
    problema, SOLO el lado que NO la creó; quien la mandó nunca la recibe."""
    return (tipo == ENTREGA and estado in ESTADOS_ABIERTOS
            and autor_lado in LADOS and lado_actor in LADOS and lado_actor != autor_lado)


def acciones_de(tipo: str, estado: str, lado_que_espera: str, lado_actor: str, autor_lado: str = "") -> dict:
    """Las acciones disponibles para `lado_actor` sobre una tarjeta. La pantalla
    no decide nada: dibuja lo que esto dice. `estados` son los destinos que se
    pueden elegir al responder (id + nombre); reabrir va aparte. `autor_lado` es
    quien creó la tarjeta: una aprobación la resuelve el otro lado, y una
    entrega la cierra el otro lado con `recibido` (nunca por el selector)."""
    vacio = {"responder": False, "estados": [], "solo_equipo": False, "aprobar": False,
             "reabrir": False, "subir": False, "reasignar": False, "recibido": False, "problema": False}
    if tipo not in TIPOS or estado not in TRANSICIONES or lado_actor not in LADOS:
        return vacio
    if es_inmutable(tipo, estado):
        return vacio
    abierta = estado in ESTADOS_ABIERTOS
    if tipo == AVISO:
        return vacio
    destinos = [e for e in (EN_CURSO, RESPONDIDA, CERRADA) if puede_transicionar(tipo, estado, e)]
    entrega = puede_dar_entrega(tipo, estado, autor_lado, lado_actor)
    return {
        "responder": abierta,
        "estados": [{"id": e, "nombre": NOMBRES_ESTADO[e]} for e in destinos] if abierta else [],
        "solo_equipo": abierta and puede_escribir_nota_interna(lado_actor),
        "aprobar": puede_resolver_aprobacion(tipo, estado, autor_lado, lado_actor),
        "reabrir": estado == CERRADA and puede_transicionar(tipo, estado, ABIERTA),
        "subir": abierta,
        "reasignar": abierta,
        "recibido": entrega,
        "problema": entrega,
    }


# ---------- La traza, en castellano ----------
def texto_evento(accion: str, detalle: dict) -> str:
    """La frase del evento (sin el nombre de quien lo hizo). Nunca incluye el
    texto de un mensaje: solo nombres de archivo, estados y títulos de hitos."""
    d = detalle or {}
    nombre = d.get("nombre") or ""
    if accion == "crear":
        return f"creó la tarjeta #{d.get('numero', '')}".strip()
    if accion == "responder":
        nuevo, ant = d.get("estado_nuevo"), d.get("estado_anterior")
        if nuevo and nuevo != ant:
            if ant == CERRADA and nuevo == ABIERTA:
                return "reabrió la tarjeta"
            return f"respondió y la pasó a {NOMBRES_ESTADO.get(nuevo, nuevo)}" if d.get("mensaje_id") \
                else f"cambió el estado a {NOMBRES_ESTADO.get(nuevo, nuevo)}"
        return "respondió"
    if accion == "resolver":
        return "aprobó" if d.get("resultado") == APROBADA else "rechazó"
    if accion == "recibido":
        return "dio la entrega por recibida"
    if accion == "problema":
        return "avisó un problema con la entrega"
    if accion == "reasignar":
        quien = (d.get("despues") or {}).get("responsable") or "nadie"
        return f"reasignó la tarjeta a {quien}"
    if accion == "subir":
        return f"subió {nombre}" + (" (con datos personales)" if d.get("datos_personales") else "")
    if accion == "bajar":
        return f"bajó {nombre}"
    if accion == "borrar_archivo":
        return f"borró {nombre}"
    if accion == "leer_aviso":
        return "leyó el aviso"
    if accion == "hito":
        return ("tildó " if d.get("hecho") else "destildó ") + f"el hito «{d.get('texto', '')}»"
    if accion == "hito_nuevo":
        return f"sumó el hito «{d.get('texto', '')}»"
    if accion == "hito_editar":
        return f"editó el hito «{d.get('texto', '')}»"
    if accion == "hito_borrar":
        return f"quitó el hito «{d.get('texto', '')}»"
    if accion == "etapa_renombrar":
        return f"renombró la etapa «{d.get('antes', '')}» a «{d.get('despues', '')}»"
    if accion == "hitos_semilla":
        return f"cargó {d.get('cantidad', 0)} hitos iniciales"
    if accion == "exportar":
        return "exportó el proyecto"
    return accion


# ---------- Códigos y relaciones (I12, I13, I14, I15) ----------
# Todo lo que se genera tiene un código para nombrarlo: PE0001 (tarjeta, por
# tipo), AR000123 (archivo), HI0001 (hito) y PE0004-3 (el mensaje 3 de esa
# tarjeta). Un contador por proyecto y prefijo; el código nace con la cosa y
# no cambia nunca. Lo «solo equipo» (I15) lleva su propia serie, aparte de la
# que ve el sindicato, para que esa serie quede corrida sin saltos: las notas
# internas son PE0004-N1, PE0004-N2 y los archivos subidos en una nota interna
# AI000001 (contador AI). Un mensaje no pasa nunca de público a interno, así
# que su código es inmutable. Acá solo el formato y el reconocimiento en un texto.
PREFIJOS_TARJETA = {PEDIDO: "PE", CONSULTA: "CO", ENTREGA: "EN", APROBACION: "AP", ERROR: "ER", AVISO: "AV"}
PREFIJO_ARCHIVO, PREFIJO_HITO = "AR", "HI"
PREFIJO_ARCHIVO_INTERNO = "AI"
PREFIJOS_INTERNOS = (PREFIJO_ARCHIVO_INTERNO,)
DIGITOS = {**{p: 4 for p in PREFIJOS_TARJETA.values()}, PREFIJO_ARCHIVO: 6, PREFIJO_ARCHIVO_INTERNO: 6,
           PREFIJO_HITO: 4}
TIPO_DE_PREFIJO = {**{p: "tarjeta" for p in PREFIJOS_TARJETA.values()},
                   PREFIJO_ARCHIVO: "archivo", PREFIJO_ARCHIVO_INTERNO: "archivo", PREFIJO_HITO: "hito"}
REL_TARJETA, REL_ARCHIVO, REL_HITO, REL_MENSAJE = "tarjeta", "archivo", "hito", "mensaje"
TIPOS_REL = (REL_TARJETA, REL_ARCHIVO, REL_HITO, REL_MENSAJE)
MENCIONA, RESPONDE = "menciona", "responde"
CLASES_REL = (MENCIONA, RESPONDE)
# «sale» = la cosa de la que hablamos es el origen; «entra» = es el destino.
TEXTOS_REL = {
    (RESPONDE, "sale"): "responde a", (RESPONDE, "entra"): "respondida con",
    (MENCIONA, "sale"): "menciona", (MENCIONA, "entra"): "mencionada en",
}

# Solo ASCII (QA-03, QA-18): el prefijo sin distinguir mayúsculas a mano, para que
# «İ» o «ı» no casen con «i» ni un dígito árabe cuente como cifra; y palabra
# completa en el sentido Unicode: ni letra, ni dígito, ni guion bajo pegados
# antes o después, tampoco una «ñ». El sufijo `-N2` es una nota interna (I15).
_PREFIJOS_RE = "|".join("".join(f"[{c.upper()}{c.lower()}]" for c in p)
                        for p in sorted(DIGITOS, key=len, reverse=True))
_CODIGO_RE = re.compile(
    r"(?<!\w)(" + _PREFIJOS_RE + r")([0-9]{4,6})(?:-([Nn]?)([0-9]{1,5}))?(?!\w)")


def prefijo_de_tipo(tipo: str) -> str:
    """El prefijo de una tarjeta según su tipo («PE» si el tipo no se conoce)."""
    return PREFIJOS_TARJETA.get(tipo, "PE")


def prefijo_de_archivo(interno: bool = False) -> str:
    """AR para lo que ve el sindicato, AI para lo subido en una nota interna."""
    return PREFIJO_ARCHIVO_INTERNO if interno else PREFIJO_ARCHIVO


def formatear_codigo(prefijo: str, numero: int, orden: int = None, interno: bool = False) -> str:
    """PE + 4 -> PE0004; AR + 123 -> AR000123; con `orden`, el mensaje:
    PE0004-3, y con `interno` el de una nota interna: PE0004-N3. Un número que
    no entra en los dígitos crece (no se trunca)."""
    prefijo = (prefijo or "").upper()
    if prefijo not in DIGITOS:
        raise ValueError(f"Prefijo desconocido: {prefijo!r}")
    if int(numero) < 1:
        raise ValueError("El número de un código empieza en 1.")
    codigo = f"{prefijo}{int(numero):0{DIGITOS[prefijo]}d}"
    if orden is not None:
        if prefijo not in PREFIJOS_TARJETA.values() or int(orden) < 1:
            raise ValueError("Solo un mensaje de una tarjeta lleva orden.")
        codigo += f"-{'N' if interno else ''}{int(orden)}"
    elif interno:
        raise ValueError("Lo interno sin orden no lleva sufijo.")
    return codigo


def codigo_mensaje(codigo_tarjeta: str, orden: int, interno: bool = False) -> str:
    """El código de un mensaje a partir del de su tarjeta: PE0004 + 3 -> PE0004-3
    (PE0004-N3 si es una nota interna)."""
    return formatear_codigo(codigo_tarjeta[:2], int(codigo_tarjeta[2:]), orden, interno)


def _desde_match(m):
    prefijo, digitos, marca, orden = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
    if prefijo not in DIGITOS:
        return None
    ancho = DIGITOS[prefijo]
    if len(digitos) < ancho or (len(digitos) > ancho and digitos[0] == "0"):
        return None                       # PE00041 no es un código; PE12345 sí (el contador creció)
    numero = int(digitos)
    if numero < 1:
        return None
    interno_msg = bool(marca)
    if orden is not None:
        if TIPO_DE_PREFIJO[prefijo] != "tarjeta" or int(orden) < 1:
            return None
        orden = int(orden)
    tipo = "mensaje" if orden is not None else TIPO_DE_PREFIJO[prefijo]
    interno = interno_msg or prefijo in PREFIJOS_INTERNOS
    return {"tipo": tipo, "prefijo": prefijo, "numero": numero, "orden": orden, "interno": interno,
            "codigo": formatear_codigo(prefijo, numero, orden, interno_msg),
            "base": formatear_codigo(prefijo, numero)}


def parsear_codigo(texto: str):
    """Un código SOLO (sin otra cosa alrededor, mayúsculas o minúsculas) a
    {tipo (tarjeta|archivo|hito|mensaje), prefijo, numero, orden, interno,
    codigo, base}; None si no es un código. `interno` es un archivo AI o un
    mensaje -N: el sindicato lo trata como si no existiera."""
    m = _CODIGO_RE.fullmatch((texto or "").strip())
    return _desde_match(m) if m else None


def extraer_codigos(texto: str) -> list:
    """Los códigos que aparecen en un texto, como palabra completa, en su forma
    canónica, en orden de aparición y sin repetir. «pe0004», «PE0004-3»,
    «PE0004-N2», «AR000123», «AI000001», «HI0001»; no «XPE0004», ni «PE00041»,
    ni «PE0004x»."""
    vistos, salida = set(), []
    for m in _CODIGO_RE.finditer(texto or ""):
        d = _desde_match(m)
        if d and d["codigo"] not in vistos:
            vistos.add(d["codigo"])
            salida.append(d["codigo"])
    return salida


def enlace_codigo(proyecto_id: int, codigo: str) -> str:
    """El enlace a la mesa que lleva a esa cosa (el viejo #t{numero} sigue
    valiendo en la pantalla)."""
    return f"/implementacion?p={int(proyecto_id)}#{codigo}"


def texto_relacion(clase: str, sentido: str) -> str:
    return TEXTOS_REL.get((clase, sentido), clase)


# ---------- Semilla del plan operativo (I7) ----------
RUTA_HITOS_BANCARIA = Path(__file__).resolve().parent / "data" / "implementacion" / "hitos_bancaria.json"


def cargar_hitos_semilla(ruta=None) -> list:
    """[(nombre de etapa, [texto de hito, ...]), ...] desde el JSON de la
    semilla, validado: textos no vacíos y sin repetir dentro de la etapa."""
    datos = json.loads(Path(ruta or RUTA_HITOS_BANCARIA).read_text(encoding="utf-8"))
    salida = []
    for fase in datos.get("fases", []):
        textos = [str(h.get("texto", "")).strip() for h in fase.get("hitos", [])]
        if not str(fase.get("etapa", "")).strip() or not textos or not all(textos):
            raise ValueError("La semilla de hitos está mal formada.")
        salida.append((str(fase["etapa"]).strip(), textos))
    return salida
