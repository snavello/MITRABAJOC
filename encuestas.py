"""Catálogo y reglas puras del módulo Encuestas (SPRINT_ENCUESTAS.md).

Este archivo es a Encuestas lo que `modulos.py` es al trabajador y
`permisos.py` al panel: el catálogo de lo que existe, más las reglas que se
pueden decidir SIN tocar la base. Nada de acá importa `db`, así que se
prueba solo y rápido -- mismo criterio que `validaciones_tramite.py`.

Lo que vive acá:

- **Los dos modos** (anónima / nominal) y **los cortes** que una anónima
  puede guardar junto a la respuesta (decisión N1).
- **Los tipos de pregunta**, con cuáles están permitidos en una anónima: un
  archivo adjunto lleva metadatos (modelo de teléfono, a veces GPS; un PDF
  lleva autor) y es la forma más fácil de romper el anonimato sin darse
  cuenta, así que en una anónima no existe (N4b).
- **El estado**, que NO se guarda: se deriva de `publicada` y las dos
  fechas, igual que `db.noticia_vigente()` (N6). Una fila nunca queda en
  "abierta" porque nadie corrió el proceso que la cerraba.
- **El disclaimer**, armado a partir del modo y de los cortes tildados
  (N2b). Se arma acá y no en la plantilla para que sea imposible que la
  pantalla prometa algo distinto de lo que el modelo cumple, y para poder
  probar la promesa con un test.
"""

# --- Modos -------------------------------------------------------------
ANONIMA = "anonima"
NOMINAL = "nominal"

MODOS = {
    NOMINAL: "Nominal",
    ANONIMA: "Anónima",
}

# --- Cortes -------------------------------------------------------------
# corte -> (etiqueta, columna de RespuestaEncuesta donde se guarda)
#
# Son los únicos atributos que una encuesta ANÓNIMA puede guardar pegados a
# la respuesta, y solo los que el admin tilda al crearla. En una NOMINAL
# están todos disponibles: ahí la identidad ya es parte del trato.
CORTES = {
    "seccional": ("Seccional", "seccional_id"),
    "provincia": ("Provincia", "provincia"),
    "empleador": ("Empleador", "cuit_empleador"),
}

# Por debajo de esta cantidad de respuestas, un grupo no se muestra ni se
# exporta. Es el default de fábrica; plataforma lo puede cambiar
# (ConfiguracionPlataforma.encuestas_umbral_minimo) y cada encuesta se lleva
# el valor vigente al publicarse, para que cambiarlo después no altere lo
# que una encuesta ya cerrada venía mostrando.
UMBRAL_MINIMO_DEFAULT = 5

# --- Tipos de pregunta --------------------------------------------------
# tipo -> (etiqueta, se_puede_en_anonima)
#
# Los ocho primeros son el mismo vocabulario de CampoTramite.tipo_dato, a
# propósito: el constructor se ve y se comporta igual que el de Trámites.
# "escala" y "ranking" son propios de encuestas (N4). "archivo" existe solo
# en las nominales (N4b).
TIPOS_PREGUNTA = {
    "texto":       ("Texto", True),
    "numero":      ("Número", True),
    "fecha":       ("Fecha", True),
    "seleccion":   ("Lista desplegable", True),
    "opcion_unica": ("Opción única", True),
    "multiple":    ("Opción múltiple", True),
    "booleano":    ("Sí / No", True),
    "separador":   ("Separador", True),
    "escala":      ("Escala 1 a 5", True),
    "ranking":     ("Ordenar por prioridad", True),
    "archivo":     ("Archivo adjunto", False),
}

# Los que no juntan una respuesta: existen solo para dividir el formulario.
TIPOS_SIN_RESPUESTA = {"separador"}

# Los que se responden eligiendo una o más opciones de una lista.
TIPOS_CON_OPCIONES = {"seleccion", "opcion_unica", "multiple", "ranking"}

ESCALA_MIN_DEFAULT = 1
ESCALA_MAX_DEFAULT = 5

# --- Estados ------------------------------------------------------------
BORRADOR = "borrador"
PROGRAMADA = "programada"
ABIERTA = "abierta"
CERRADA = "cerrada"

ETIQUETAS_ESTADO = {
    BORRADOR: "Borrador",
    PROGRAMADA: "Programada",
    ABIERTA: "Abierta",
    CERRADA: "Cerrada",
}


def tipos_para(modo: str) -> list:
    """[(tipo, etiqueta), ...] ofrecibles en una encuesta de este modo."""
    anonima = modo == ANONIMA
    return [(t, etiqueta) for t, (etiqueta, en_anonima) in TIPOS_PREGUNTA.items()
            if not anonima or en_anonima]


def cortes_saneados(modo: str, cortes) -> list:
    """Los cortes válidos de esta encuesta, en el orden del catálogo.

    Una NOMINAL los tiene todos: guardar la seccional de quien ya firmó con
    nombre y apellido no agrega ninguna exposición. En una ANÓNIMA valen
    solo los que el admin tildó, y cualquier cosa que no esté en el catálogo
    se descarta en vez de guardarse "por las dudas".
    """
    if modo == NOMINAL:
        return list(CORTES)
    pedidos = set(cortes or [])
    return [c for c in CORTES if c in pedidos]


def estado(publicada: bool, fecha_desde: str, fecha_hasta: str,
           hoy: str, cerrada_en: str = "") -> str:
    """El estado de una encuesta, derivado -- nunca guardado (N6).

    `hoy` entra por parámetro (la hora de Buenos Aires la resuelve quien
    llama, con `fechas.hoy_texto()`): así esto se puede probar con
    cualquier fecha sin tocar el reloj. Las fechas se comparan como texto
    "AAAA-MM-DD", igual que db.noticia_vigente().
    """
    if not publicada:
        return BORRADOR
    if cerrada_en:
        return CERRADA
    if fecha_desde and hoy < fecha_desde:
        return PROGRAMADA
    if fecha_hasta and hoy > fecha_hasta:
        return CERRADA
    return ABIERTA


def acepta_respuestas(publicada: bool, fecha_desde: str, fecha_hasta: str,
                      hoy: str, cerrada_en: str = "") -> bool:
    """Si la encuesta está tomando respuestas en este momento.

    Existe como función aparte de `estado()` para que el backend pregunte
    esto y no compare estados con strings sueltos por ahí.
    """
    return estado(publicada, fecha_desde, fecha_hasta, hoy, cerrada_en) == ABIERTA


def disclaimer(modo: str, cortes=None, umbral: int = UMBRAL_MINIMO_DEFAULT) -> list:
    """Las líneas que el afiliado ve antes de responder (N2b).

    Se arma acá, a partir de los mismos datos que usa el backend para
    guardar, para que la pantalla no pueda prometer algo distinto de lo que
    el sistema cumple. Devuelve una lista de párrafos.

    No dice "no se guarda ningún dato personal", porque sería falso: para
    impedir que alguien responda dos veces hay que registrar QUIÉN
    participó. Dice exactamente lo que pasa -- que eso queda en una tabla
    aparte, sin ninguna forma de unirla con las respuestas.
    """
    if modo == NOMINAL:
        return [
            "Esta encuesta es NOMINAL: tus respuestas quedan asociadas a tu "
            "nombre y tu CUIL, y el sindicato las puede ver una por una.",
            "No vas a poder modificar tu respuesta después de enviarla.",
        ]

    lineas = [
        "Esta encuesta es ANÓNIMA. Queda registrado que participaste, nunca "
        "qué respondiste: tu respuesta no se puede vincular con vos ni con "
        "tu computadora.",
    ]
    guardados = [CORTES[c][0].lower() for c in cortes_saneados(ANONIMA, cortes)]
    if guardados:
        lineas.append(
            "Para poder mostrar los resultados por grupo se guarda, junto a "
            "tu respuesta y sin tu identidad: " + _enumerar(guardados) + ".")
        lineas.append(
            f"No se muestran resultados de grupos de menos de {umbral} "
            "personas, para que nadie pueda deducir quién respondió qué.")
    else:
        lineas.append(
            "No se guarda ningún dato tuyo junto a la respuesta: solo se "
            "cuentan las respuestas, todas juntas.")
    lineas.append(
        "No vas a poder modificar tu respuesta después de enviarla: el "
        "sistema no tiene forma de saber cuál fue.")
    return lineas


def _enumerar(items: list) -> str:
    """['a', 'b', 'c'] -> 'a, b y c'."""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]
