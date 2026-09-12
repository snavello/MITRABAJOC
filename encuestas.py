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

import fechas

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

# Qué tiene que HACER el afiliado en cada pregunta. Vive acá y no en la
# plantilla por lo mismo que el disclaimer: el constructor y la pantalla del
# trabajador tienen que decir exactamente lo mismo, y una sola frase escrita
# dos veces se desincroniza sola. "Opción única" y "múltiple" se ven casi
# igual (un círculo o un cuadrado), así que sin esta línea nadie sabe si
# puede marcar una o varias hasta que lo intenta.
AYUDA_POR_TIPO = {
    "texto":        "Escribí tu respuesta.",
    "numero":       "Escribí un número.",
    "fecha":        "Elegí una fecha.",
    "seleccion":    "Elegí una opción de la lista.",
    "opcion_unica": "Seleccioná una opción.",
    "multiple":     "Podés seleccionar varias opciones.",
    "booleano":     "Elegí Sí o No.",
    "escala":       "Elegí un número de la escala.",
    "ranking":      "Ordená las opciones arrastrándolas: primero la más importante.",
    "archivo":      "Adjuntá un archivo.",
    "separador":    "",
}


def ayuda_de(tipo: str, obligatorio: bool = True) -> str:
    """La línea de ayuda de una pregunta, con el aviso de opcional si va."""
    base = AYUDA_POR_TIPO.get(tipo, "")
    if not base:
        return ""
    return base if obligatorio else base + " Podés dejarla en blanco."


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
        # Nada. Una encuesta nominal es el caso por defecto -- el afiliado
        # entró con su CUIL y no espera otra cosa --, y un cartel explicando
        # lo obvio le resta peso al que SÍ importa, el de las anónimas. Que
        # se responde una sola vez lo dice el pie de la pantalla, en los dos
        # modos.
        return []

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


def _entero(valor, por_defecto):
    """El entero que trae `valor`, o `por_defecto` si no lo es. El default
    puede ser None: así el que valida distingue "no es un número" de un 0."""
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


# --- Lo que responde el afiliado -----------------------------------------
MAX_TEXTO_RESPUESTA = 2000


def respuestas_saneadas(preguntas: list, crudas: dict) -> tuple:
    """(filas para la urna, errores). Las filas NO llevan identidad.

    `crudas` es {pregunta_id: valor}, con la forma que corresponda al tipo:
    un índice de opción, una lista de índices (múltiple y ranking), un
    número, un texto o una fecha. Se valida contra las PREGUNTAS guardadas,
    nunca contra lo que mande el navegador: el formulario del afiliado es
    una sugerencia y el servidor decide, igual que en Trámites.

    Cada fila sale lista para RespuestaEncuesta menos el día y los cortes,
    que los pone db.registrar_respuesta_encuesta. Una fila por opción
    elegida, así los gráficos se agregan con un GROUP BY y no leyendo JSON.
    """
    filas, errores = [], []
    for p in preguntas:
        tipo = p.get("tipo_dato")
        if tipo in TIPOS_SIN_RESPUESTA:
            continue
        pid = p.get("id")
        valor = crudas.get(str(pid), crudas.get(pid))
        etiqueta = (p.get("etiqueta") or "").strip() or f"pregunta {pid}"
        vacio = valor is None or valor == "" or valor == []
        if vacio:
            if p.get("obligatorio"):
                errores.append(f"Falta responder «{etiqueta}».")
            continue

        opciones = opciones_de(p.get("opciones", ""))
        base = {"pregunta_id": pid, "opcion_indice": None, "posicion": None,
                "valor_texto": "", "valor_numero": None, "valor_fecha": ""}

        if tipo in ("seleccion", "opcion_unica"):
            i = _indice(valor, len(opciones))
            if i is None:
                errores.append(f"«{etiqueta}»: la opción elegida no existe.")
                continue
            filas.append({**base, "opcion_indice": i})

        elif tipo == "multiple":
            indices, malo = [], False
            for v in (valor if isinstance(valor, list) else [valor]):
                i = _indice(v, len(opciones))
                if i is None or i in indices:
                    malo = True
                    break
                indices.append(i)
            if malo:
                errores.append(f"«{etiqueta}»: hay una opción repetida o inexistente.")
                continue
            filas += [{**base, "opcion_indice": i} for i in indices]

        elif tipo == "ranking":
            indices, malo = [], False
            for v in (valor if isinstance(valor, list) else [valor]):
                i = _indice(v, len(opciones))
                if i is None or i in indices:
                    malo = True
                    break
                indices.append(i)
            # El ranking se responde ENTERO o no se responde: un orden
            # parcial no se puede promediar contra los que sí ordenaron todo.
            if malo or len(indices) != len(opciones):
                errores.append(f"«{etiqueta}»: hay que ordenar todas las opciones.")
                continue
            filas += [{**base, "opcion_indice": i, "posicion": n + 1}
                      for n, i in enumerate(indices)]

        elif tipo == "escala":
            minimo = p.get("escala_min") or ESCALA_MIN_DEFAULT
            maximo = p.get("escala_max") or ESCALA_MAX_DEFAULT
            n = _entero(valor, None)
            if n is None or not (minimo <= n <= maximo):
                errores.append(f"«{etiqueta}»: elegí un número entre {minimo} y {maximo}.")
                continue
            filas.append({**base, "valor_numero": float(n)})

        elif tipo == "numero":
            try:
                filas.append({**base, "valor_numero": float(str(valor).replace(",", "."))})
            except (TypeError, ValueError):
                errores.append(f"«{etiqueta}»: tiene que ser un número.")

        elif tipo == "booleano":
            texto = str(valor).strip().lower()
            if texto not in ("si", "sí", "no", "true", "false", "1", "0"):
                errores.append(f"«{etiqueta}»: respondé Sí o No.")
                continue
            filas.append({**base, "valor_numero": 1.0 if texto in ("si", "sí", "true", "1") else 0.0})

        elif tipo == "fecha":
            texto = str(valor).strip()
            if len(texto) != 10 or texto[4] != "-" or texto[7] != "-":
                errores.append(f"«{etiqueta}»: la fecha tiene que ser AAAA-MM-DD.")
                continue
            filas.append({**base, "valor_fecha": texto})

        else:   # texto y cualquier tipo nuevo que se responda escribiendo
            filas.append({**base, "valor_texto": str(valor).strip()[:MAX_TEXTO_RESPUESTA]})

    if not filas and not errores:
        errores.append("No respondiste ninguna pregunta.")
    return filas, errores


def _indice(valor, cantidad: int):
    """El índice de una opción, o None si no es válido."""
    i = _entero(valor, None)
    return i if i is not None and 0 <= i < cantidad else None


# --- Lo que la tarjeta del afiliado le dice antes de entrar --------------
# Segundos que lleva contestar una pregunta, promediando las cortas (sí/no,
# una opción) con las que hacen pensar (escala, ranking, texto libre). No
# pretende ser exacto: pretende que "dos minutos" no sea una sorpresa de
# quince. Se redondea siempre PARA ARRIBA -- prometer de menos es peor.
SEGUNDOS_POR_PREGUNTA = 20


def preguntas_reales(preguntas: list) -> int:
    """Cuántas hay que responder de verdad. Un separador es un título en el
    medio del formulario, no una pregunta, y contarlo hace que la tarjeta
    prometa más trabajo del que hay."""
    return sum(1 for p in preguntas
               if (p.get("tipo_dato") or p.get("tipo")) not in TIPOS_SIN_RESPUESTA)


def minutos_estimados(preguntas: list) -> int:
    """Cuánto lleva responderla, en minutos enteros y nunca menos de uno."""
    segundos = preguntas_reales(preguntas) * SEGUNDOS_POR_PREGUNTA
    return max(1, -(-segundos // 60))


# --- Los textos de los avisos -------------------------------------------
LANZAMIENTO = "lanzamiento"
RECORDATORIO = "recordatorio"


def texto_aviso(titulo: str, fecha_hasta: str, modo: str, tipo: str = LANZAMIENTO) -> str:
    """El texto sugerido de la notificación que anuncia una encuesta.

    Es un BORRADOR editable, no un cartel del sistema: el admin lo cambia
    antes de mandarlo. Vive acá y no en la plantilla por lo mismo que el
    disclaimer -- el lanzamiento y el recordatorio tienen que decir lo
    mismo sobre el anonimato, y dos textos escritos en dos lugares se
    desincronizan solos.
    """
    anonima = ("Es anónima: no se puede saber quién respondió qué. "
               if modo == ANONIMA else "")
    hasta = fechas.dia_legible(fecha_hasta)
    if tipo == RECORDATORIO:
        return (f"Todavía estás a tiempo de responder «{titulo}». "
                f"{anonima}Se cierra el {hasta} y lleva un par de minutos.")
    return (f"Tu sindicato quiere saber tu opinión: «{titulo}». "
            f"{anonima}Se puede responder hasta el {hasta} y lleva un par de minutos.")


def texto_noticia(titulo: str, fecha_hasta: str, modo: str) -> dict:
    """El borrador de la noticia que anuncia una encuesta (título y bajada)."""
    return {
        "titulo": f"Encuesta: {titulo}",
        "bajada": ("Tu opinión cuenta. Es anónima y lleva un par de minutos."
                   if modo == ANONIMA else "Tu opinión cuenta y lleva un par de minutos."),
        "texto": (f"Está abierta la encuesta «{titulo}», hasta el "
                  f"{fechas.dia_legible(fecha_hasta)}. "
                  + ("Es anónima: el sindicato ve los resultados en conjunto, nunca quién "
                     "respondió qué. " if modo == ANONIMA else "")
                  + "Entrá a Encuestas desde la app y dejanos tu respuesta."),
    }
