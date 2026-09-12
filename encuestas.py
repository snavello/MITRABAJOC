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


# --- Saneo de las preguntas ---------------------------------------------
ANCHOS = ("completo", "mitad", "tercio")
MAX_OPCIONES = 20
MAX_PUNTOS_ESCALA = 10


def opciones_de(texto: str) -> list:
    """"a, b, c" -> ["a", "b", "c"], sin vacías ni repetidas.

    Mismo formato que CampoTramite.opciones (separadas por coma) a
    propósito: el constructor es el mismo y el admin ya lo conoce.
    """
    vistas, salida = set(), []
    for parte in (texto or "").split(","):
        o = parte.strip()
        if o and o.lower() not in vistas:
            vistas.add(o.lower())
            salida.append(o)
    return salida


def preguntas_saneadas(modo: str, preguntas) -> tuple:
    """(preguntas limpias, errores). Una pregunta mal formada NO se guarda.

    Mismo criterio que `validaciones_tramite.validaciones_saneadas`: el
    saneo vive acá, sin base y sin request, y lo usan por igual el alta, la
    edición y los tests. Devolver los errores en vez de tirar una excepción
    permite mostrarlos todos juntos y no de a uno.
    """
    ofrecibles = {t for t, _ in tipos_para(modo)}
    limpias, errores = [], []

    for i, cruda in enumerate(preguntas or [], start=1):
        p = dict(cruda or {})
        tipo = str(p.get("tipo_dato") or "").strip()
        if tipo not in ofrecibles:
            errores.append(f"Pregunta {i}: el tipo «{tipo or 'vacío'}» no existe"
                           + (" en una encuesta anónima." if modo == ANONIMA else "."))
            continue

        etiqueta = str(p.get("etiqueta") or "").strip()
        if not etiqueta and tipo not in TIPOS_SIN_RESPUESTA:
            errores.append(f"Pregunta {i}: falta el texto de la pregunta.")
            continue

        limpia = {
            "etiqueta": etiqueta,
            "tipo_dato": tipo,
            "opciones": "",
            "escala_min": None,
            "escala_max": None,
            "etiqueta_min": str(p.get("etiqueta_min") or "").strip(),
            "etiqueta_max": str(p.get("etiqueta_max") or "").strip(),
            "ancho": p.get("ancho") if p.get("ancho") in ANCHOS else "completo",
            "obligatorio": bool(p.get("obligatorio", True)),
        }

        if tipo in TIPOS_SIN_RESPUESTA:
            # Un separador no se responde: ni ocupa media pantalla ni puede
            # ser obligatorio.
            limpia["ancho"] = "completo"
            limpia["obligatorio"] = False

        if tipo in TIPOS_CON_OPCIONES:
            opciones = opciones_de(p.get("opciones", ""))
            if len(opciones) < 2:
                errores.append(f"Pregunta {i}: hacen falta al menos dos opciones distintas.")
                continue
            if len(opciones) > MAX_OPCIONES:
                errores.append(f"Pregunta {i}: {len(opciones)} opciones es demasiado "
                               f"(máximo {MAX_OPCIONES}); nadie contesta eso en un celular.")
                continue
            limpia["opciones"] = ", ".join(opciones)

        if tipo == "escala":
            minimo = _entero(p.get("escala_min"), ESCALA_MIN_DEFAULT)
            maximo = _entero(p.get("escala_max"), ESCALA_MAX_DEFAULT)
            if maximo <= minimo:
                errores.append(f"Pregunta {i}: el máximo de la escala tiene que ser "
                               "mayor que el mínimo.")
                continue
            if maximo - minimo + 1 > MAX_PUNTOS_ESCALA:
                errores.append(f"Pregunta {i}: una escala de {maximo - minimo + 1} puntos "
                               f"no entra en un celular (máximo {MAX_PUNTOS_ESCALA}).")
                continue
            limpia["escala_min"], limpia["escala_max"] = minimo, maximo

        limpias.append(limpia)

    if not limpias and not errores:
        errores.append("La encuesta no tiene ninguna pregunta.")
    if limpias and all(p["tipo_dato"] in TIPOS_SIN_RESPUESTA for p in limpias):
        errores.append("La encuesta solo tiene separadores: no hay nada para responder.")
    return limpias, errores


def _entero(valor, por_defecto: int) -> int:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return por_defecto


def cambio_estructural(antes: list, despues: list) -> bool:
    """Si entre dos versiones de las preguntas cambió algo MÁS que el texto.

    Es lo que decide si una edición está permitida con respuestas ya
    cargadas (N5): la redacción se puede corregir, la estructura no. Compara
    cantidad, orden, tipo, ancho, obligatoriedad, los extremos de la escala
    y la CANTIDAD de opciones -- cambiarle el texto a una opción es una
    errata; agregar o sacar una cambia el sentido de lo ya respondido,
    porque las respuestas guardan el índice.
    """
    if len(antes) != len(despues):
        return True
    for a, d in zip(antes, despues):
        if (a.get("tipo_dato") != d.get("tipo_dato")
                or bool(a.get("obligatorio")) != bool(d.get("obligatorio"))
                or (a.get("ancho") or "completo") != (d.get("ancho") or "completo")
                or a.get("escala_min") != d.get("escala_min")
                or a.get("escala_max") != d.get("escala_max")
                or len(opciones_de(a.get("opciones", ""))) != len(opciones_de(d.get("opciones", "")))):
            return True
    return False
