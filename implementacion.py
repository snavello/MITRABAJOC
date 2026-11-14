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
from datetime import datetime
from typing import NamedTuple

import fechas

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
)


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


def puede_resolver_aprobacion(tipo: str, estado: str, lado_que_espera: str, lado_actor: str) -> bool:
    """Resuelve la aprobación el lado al que le toca (quien la pidió no se la
    aprueba a sí mismo)."""
    return (tipo == APROBACION and estado in ESTADOS_ABIERTOS
            and lado_actor in LADOS and lado_actor == lado_que_espera)


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
    tipo = (tipo or "").strip()
    titulo = (titulo or "").strip()
    texto = (texto or "").strip()
    fecha_limite = (fecha_limite or "").strip()
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
    if fecha_limite and not fecha_valida(fecha_limite):
        errores["fecha_limite"] = "La fecha límite no se entiende."
    return {"ok": not errores, "errores": errores,
            "datos": {"tipo": tipo, "titulo": titulo, "texto": texto, "fecha_limite": fecha_limite}}


def vencida(fecha_limite: str, estado: str, hoy: str = None) -> bool:
    """Con fecha límite pasada y todavía sin cerrar."""
    if not fecha_limite or estado in ESTADOS_FINALES:
        return False
    return fecha_limite < (hoy or fechas.hoy_texto())


# ---------- Archivos ----------
def validar_archivo(nombre: str, tamano: int) -> str:
    """"" si sirve; si no, el motivo."""
    if not (nombre or "").strip():
        return "El archivo no tiene nombre."
    if tamano <= 0:
        return "El archivo está vacío."
    if tamano > TOPE_ARCHIVO:
        return f"El archivo pesa más de {TOPE_ARCHIVO // (1024 * 1024)} MB."
    return ""


def nombre_seguro(nombre: str) -> str:
    """Sin ruta ni caracteres de control, con tope de largo."""
    base = (nombre or "").replace("\\", "/").split("/")[-1]
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
ENCABEZADO_APROBACIONES = ("Número", "Título", "Estado", "Pidió", "Resolvió", "Cuándo", "Etapa")


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
                    f.get("resuelta_en", ""), _celda(f.get("etapa", ""))])
    return "﻿" + sal.getvalue()


def _celda(valor) -> str:
    """Neutraliza una fórmula de planilla (=, +, -, @) al abrir el CSV."""
    texto = str(valor if valor is not None else "")
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto
