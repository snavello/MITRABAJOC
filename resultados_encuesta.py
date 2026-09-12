"""Los agregados del dashboard de una encuesta (SPRINT_ENCUESTAS.md, Fase 4).

Es a Encuestas lo que `dashboard.py` es al Panel Sindical: TODO agregado se
calcula en SQL, filtrado siempre por `encuesta_id` primero, y nunca se traen
respuestas crudas a Python para contarlas acá.

Las tres reglas que este módulo respeta a rajatabla:

1. **El umbral se aplica en el SERVIDOR, no en la pantalla** (N1, y el
   tercero de los tests de privacidad). Un grupo de una encuesta anónima con
   menos de `umbral_minimo` respuestas no se cuenta, no se grafica y no
   viaja: el endpoint devuelve `oculto: true` y `preguntas: []`. Que la
   pantalla lo esconda no sirve de nada -- el JSON se lee con el inspector.

2. **El umbral es una protección de anonimato, así que solo rige en las
   ANÓNIMAS.** En una nominal el admin puede ver respuesta por respuesta con
   nombre y apellido: es exactamente lo que el afiliado aceptó al responder
   una encuesta que dice "nominal" en la cara, y lo que el CSV nominal
   entrega (N20). Aplicarlo ahí escondería datos que el mismo módulo exporta
   dos clics más allá.

3. **Los filtros se sanean contra los cortes que la encuesta guardó.** Una
   anónima sin corte de seccional no se puede filtrar por seccional, porque
   la urna no tiene ese dato -- y pedirlo por URL no lo inventa.

Dos fuentes distintas, a propósito:

- La **participación** y los **avisos leídos** salen del PADRÓN (quién fue
  invitado, quién respondió, quién leyó), que no es anónimo: es el mismo
  dato con el que el recordatorio le escribe a los que faltan. Sus cortes se
  resuelven contra `Trabajador`, así que usan la seccional de HOY.
- Los **gráficos** salen de la URNA, que guarda sus propios cortes copiados
  al responder (si el afiliado cambia de seccional, su respuesta sigue
  contando donde estaba cuando respondió).

Pueden dar números distintos si alguien se mudó de seccional entre que
respondió y hoy. Es correcto que así sea, y por eso la pantalla dice de
dónde sale cada cosa.
"""
from sqlalchemy import case, func

import db
import encuestas
import fechas

# Tipos que dejan EXACTAMENTE una fila por persona en la urna. Son los que
# sirven de testigo para contar personas (ver `_pregunta_testigo`).
TIPOS_UNA_FILA = ("seleccion", "opcion_unica", "escala", "numero",
                  "booleano", "fecha", "texto")

# Cuántas respuestas de texto libre se devuelven. No se grafican: se leen.
MAX_TEXTOS = 300


def filtros_saneados(e: dict, pedidos: dict, alcance=None) -> dict:
    """Los filtros que de verdad se pueden aplicar a ESTA encuesta.

    `pedidos` es lo que llegó por la URL; se descarta todo corte que la
    encuesta no haya guardado. `alcance` es el de seccional de quien mira
    (db.alcance_seccional): con un set, el filtro de seccional se le IMPONE
    (N18) -- ve la encuesta central recortada a su gente cuando ese corte
    existe, y el total general cuando la anónima no lo guarda.
    """
    salida, fijos = {}, []
    for corte in (e.get("cortes") or []):
        if corte not in encuestas.CORTES:
            continue
        valores = [str(v).strip() for v in (pedidos.get(corte) or []) if str(v).strip()]
        if valores:
            salida[corte] = valores

    if alcance is not None and "seccional" in (e.get("cortes") or []):
        propias = {str(x) for x in alcance}
        pedidas = set(salida.get("seccional") or []) & propias if salida.get("seccional") \
            else propias
        # Sin seccional alcanzada queda una lista vacía a propósito: es el
        # caso defensivo de alcance_seccional, y un filtro vacío no puede
        # significar "todas".
        salida["seccional"] = sorted(pedidas) or ["0"]
        fijos.append("seccional")
    return {"aplicados": salida, "fijos": fijos}


def resultados(encuesta_id: int, sindicato_id: int, pedidos: dict, alcance=None) -> dict:
    """El dashboard entero de una encuesta, ya recortado y con el umbral
    aplicado. Devuelve None si la encuesta no es de este sindicato."""
    e = db.encuesta_por_id(encuesta_id, sindicato_id)
    if not e:
        return None
    f = filtros_saneados(e, pedidos, alcance)
    anonima = e["modo"] == encuestas.ANONIMA
    umbral = e["umbral_minimo"] if anonima else 0

    with db.Session(db.engine) as s:
        testigo = _pregunta_testigo(e["preguntas"])
        respondentes = _respondentes(s, e, f["aplicados"], testigo)
        oculto = anonima and respondentes < umbral
        salida = {
            "encuesta": {
                "id": e["id"], "titulo": e["titulo"], "descripcion": e["descripcion"],
                "modo": e["modo"], "estado": e["estado"], "cortes": e["cortes"],
                "fecha_desde": e["fecha_desde"], "fecha_hasta": e["fecha_hasta"],
                "publicada": e["publicada"], "cerrada_en": e["cerrada_en"],
                "mostrar_resultados": e["mostrar_resultados"],
            },
            "umbral": {"minimo": umbral, "aplica": anonima},
            "filtros": {**f, "disponibles": _valores_de_filtro(s, e)},
            "indicadores": _indicadores(s, e, f["aplicados"], testigo),
            "respondentes": respondentes,
            "oculto": oculto,
            # Con el grupo por debajo del umbral las preguntas NO se calculan:
            # no es que se calculen y no se muestren, es que no salen de acá.
            "preguntas": [] if oculto else _por_pregunta(s, e, f["aplicados"], respondentes),
            "historial": db.eventos_de_encuesta(e["id"]),
        }
    return salida


# ---------- Los cuatro indicadores (N22) ----------

def _indicadores(s, e: dict, filtros: dict, testigo) -> dict:
    """Participación, avisos leídos, ritmo y estado.

    Los dos primeros solo sirven juntos: leyeron 82% y respondió 20%
    significa que el problema es la encuesta y un recordatorio no lo
    arregla; leyeron 30% y de esos respondió casi todo significa que el
    problema es el canal, y el recordatorio sí lo resuelve.
    """
    cuils = _cuils_alcanzados(s, e, filtros)
    padron, respondieron = _participacion(s, e["id"], cuils)
    return {
        "participacion": {"respondieron": respondieron, "padron": padron,
                          "porcentaje": _porcentaje(respondieron, padron)},
        "avisos": _avisos(s, e["id"], cuils),
        "ritmo": _ritmo(s, e, filtros, testigo),
        "estado": e["estado"],
    }


def _cuils_alcanzados(s, e: dict, filtros: dict):
    """Los CUIL del padrón que caen dentro del filtro, o None si no hay
    filtro (y entonces no hace falta acotar nada).

    Sale del padrón cruzado con `Trabajador`, no de la urna: es el mismo
    dato con el que el recordatorio le escribe a los que faltan.
    """
    if not filtros:
        return None
    q = (db.select(db.EncuestaParticipante.cuil)
         .join(db.Trabajador, db.Trabajador.cuil == db.EncuestaParticipante.cuil)
         .where(db.EncuestaParticipante.encuesta_id == e["id"],
                db.Trabajador.sindicato_id == e["sindicato_id"]))
    for corte, valores in filtros.items():
        q = q.where(_columna_trabajador(corte).in_(_tipados(corte, valores)))
    return {c for c in s.exec(q).all()}


def _participacion(s, encuesta_id: int, cuils) -> tuple:
    """(padrón, respondieron) del grupo. Del padrón, que sabe quién
    participó pero nunca qué contestó."""
    q = db.select(func.count(),
                  func.coalesce(func.sum(case((db.EncuestaParticipante.respondio, 1),
                                              else_=0)), 0)) \
        .select_from(db.EncuestaParticipante) \
        .where(db.EncuestaParticipante.encuesta_id == encuesta_id)
    if cuils is not None:
        q = q.where(db.EncuestaParticipante.cuil.in_(cuils or ["__ninguno__"]))
    padron, respondieron = s.execute(q).one()
    return int(padron or 0), int(respondieron or 0)


def _avisos(s, encuesta_id: int, cuils) -> dict:
    """Enviados y leídos de TODOS los avisos de la encuesta, y el desglose
    por envío: es lo que dice si el recordatorio sirvió o no (N15)."""
    notifs = s.exec(db.select(db.Notificacion)
                    .where(db.Notificacion.encuesta_id == encuesta_id)
                    .order_by(db.Notificacion.id)).all()
    envios, enviados_total, leidos_total = [], 0, 0
    for n in notifs:
        q = db.select(func.count(),
                      func.coalesce(func.sum(case(
                          (db.NotificacionDestinatario.leida_en.isnot(None), 1),
                          else_=0)), 0)) \
            .select_from(db.NotificacionDestinatario) \
            .where(db.NotificacionDestinatario.notificacion_id == n.id)
        if cuils is not None:
            q = q.where(db.NotificacionDestinatario.cuil.in_(cuils or ["__ninguno__"]))
        enviados, leidos = s.execute(q).one()
        enviados, leidos = int(enviados or 0), int(leidos or 0)
        enviados_total += enviados
        leidos_total += leidos
        envios.append({"id": n.id, "enviado_en": n.enviado_en, "texto": n.texto,
                       "enviados": enviados, "leidos": leidos,
                       "porcentaje": _porcentaje(leidos, enviados)})
    return {"envios": envios, "cantidad": len(envios),
            "enviados": enviados_total, "leidos": leidos_total,
            "porcentaje": _porcentaje(leidos_total, enviados_total)}


def _ritmo(s, e: dict, filtros: dict, testigo) -> list:
    """Respuestas por día, de la URNA.

    Sale del `dia` que guarda la urna y no del padrón, que a propósito no
    anota cuándo respondió cada uno (punto 3 de "cómo se sostiene el
    anonimato"). Se cuenta sobre una PREGUNTA TESTIGO, no sobre todas las
    filas: una múltiple deja varias filas por persona y la curva contaría
    opciones en vez de gente.
    """
    if not testigo:
        return []
    q = db.select(db.RespuestaEncuesta.dia, func.count()) \
        .select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == e["id"],
               db.RespuestaEncuesta.pregunta_id == testigo["id"]) \
        .group_by(db.RespuestaEncuesta.dia) \
        .order_by(db.RespuestaEncuesta.dia)
    q = _con_filtros_urna(q, filtros)
    return [{"dia": dia, "cantidad": int(n)} for dia, n in s.execute(q).all() if dia]


# ---------- Los gráficos, uno por pregunta ----------

def _por_pregunta(s, e: dict, filtros: dict, respondentes: int) -> list:
    salida = []
    for p in e["preguntas"]:
        tipo = p["tipo_dato"]
        if tipo in encuestas.TIPOS_SIN_RESPUESTA:
            continue
        d = {"id": p["id"], "etiqueta": p["etiqueta"], "tipo_dato": tipo,
             "ancho": p["ancho"], "obligatorio": p["obligatorio"],
             "respondieron": _cuantos_respondieron(s, e["id"], p, filtros)}
        opciones = encuestas.opciones_de(p.get("opciones", ""))

        if tipo == "escala":
            d["escala"] = _escala(s, e["id"], p, filtros)
        elif tipo == "ranking":
            d["ranking"] = _ranking(s, e["id"], p, opciones, filtros)
        elif tipo == "booleano":
            d["opciones"] = _booleano(s, e["id"], p, filtros, d["respondieron"])
        elif tipo in encuestas.TIPOS_CON_OPCIONES:
            # La base del porcentaje: en una múltiple, la gente que respondió
            # la encuesta (una persona marca varias); en las demás, lo que
            # salga del propio conteo.
            d["opciones"] = _conteo_opciones(s, e["id"], p, opciones, filtros, respondentes)
        elif tipo == "numero":
            d["numero"] = _numero(s, e["id"], p, filtros)
        elif tipo == "fecha":
            d["fechas"] = _conteo_simple(s, e["id"], p, filtros,
                                         db.RespuestaEncuesta.valor_fecha)
        else:
            d["textos"] = _textos(s, e["id"], p, filtros)
        salida.append(d)
    return salida


def _cuantos_respondieron(s, encuesta_id: int, p: dict, filtros: dict) -> int:
    """Cuánta GENTE respondió esta pregunta. En múltiple y ranking hay varias
    filas por persona, así que no alcanza con contar filas."""
    tipo = p["tipo_dato"]
    q = db.select(func.count()).select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"])
    filas = int(s.execute(_con_filtros_urna(q, filtros)).scalar() or 0)
    if tipo == "ranking":
        # El ranking se responde ENTERO: una persona = una fila por opción.
        opciones = len(encuestas.opciones_de(p.get("opciones", "")))
        return filas // opciones if opciones else 0
    if tipo == "multiple":
        # Una múltiple deja entre 1 y N filas por persona: no se puede saber
        # cuánta gente fue sin un vínculo que la urna no tiene. Se informa
        # el total de marcas y la pantalla lo dice así.
        return filas
    return filas


def _escala(s, encuesta_id: int, p: dict, filtros: dict) -> dict:
    """Distribución 1..N y promedio. El promedio es lo que hace comparable
    una escala contra otra pregunta y contra otra toma de la misma (N4)."""
    minimo = p.get("escala_min") or encuestas.ESCALA_MIN_DEFAULT
    maximo = p.get("escala_max") or encuestas.ESCALA_MAX_DEFAULT
    q = db.select(db.RespuestaEncuesta.valor_numero, func.count()) \
        .select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"],
               db.RespuestaEncuesta.valor_numero != None) \
        .group_by(db.RespuestaEncuesta.valor_numero)   # noqa: E711
    por_valor = {int(v): int(n) for v, n in s.execute(_con_filtros_urna(q, filtros)).all()
                 if v is not None}
    total = sum(por_valor.values())
    suma = sum(v * n for v, n in por_valor.items())
    return {
        "min": minimo, "max": maximo,
        "etiqueta_min": p.get("etiqueta_min", ""), "etiqueta_max": p.get("etiqueta_max", ""),
        "promedio": round(suma / total, 2) if total else None,
        "distribucion": [{"valor": v, "cantidad": por_valor.get(v, 0),
                          "porcentaje": _porcentaje(por_valor.get(v, 0), total)}
                         for v in range(minimo, maximo + 1)],
    }


def _ranking(s, encuesta_id: int, p: dict, opciones: list, filtros: dict) -> list:
    """Posición promedio de cada opción (1 = primera prioridad) y cuántas
    veces quedó primera. Ordenado por prioridad, que es lo que se vino a ver."""
    q = db.select(db.RespuestaEncuesta.opcion_indice,
                  func.avg(db.RespuestaEncuesta.posicion),
                  func.coalesce(func.sum(case((db.RespuestaEncuesta.posicion == 1, 1),
                                              else_=0)), 0),
                  func.count()) \
        .select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"]) \
        .group_by(db.RespuestaEncuesta.opcion_indice)
    filas = {int(i): (float(prom), int(primeras), int(n))
             for i, prom, primeras, n in s.execute(_con_filtros_urna(q, filtros)).all()
             if i is not None and prom is not None}
    salida = [{"indice": i, "texto": texto,
               "promedio": round(filas[i][0], 2) if i in filas else None,
               "primeras": filas[i][1] if i in filas else 0,
               "cantidad": filas[i][2] if i in filas else 0}
              for i, texto in enumerate(opciones)]
    salida.sort(key=lambda d: (d["promedio"] is None, d["promedio"] or 0))
    return salida


def _conteo_opciones(s, encuesta_id: int, p: dict, opciones: list, filtros: dict,
                     base: int) -> list:
    """Conteo por opción. En una de opción única el porcentaje es sobre las
    respuestas; en una MÚLTIPLE, sobre la gente que respondió la encuesta:
    "el 62% marcó Sueldo" se entiende, "el 25% de las marcas fue Sueldo" no
    dice nada, y encima suma 100% entre opciones que no compiten."""
    q = db.select(db.RespuestaEncuesta.opcion_indice, func.count()) \
        .select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"]) \
        .group_by(db.RespuestaEncuesta.opcion_indice)
    por_indice = {int(i): int(n) for i, n in s.execute(_con_filtros_urna(q, filtros)).all()
                  if i is not None}
    total = (base if p["tipo_dato"] == "multiple" else sum(por_indice.values())) or 1
    return [{"indice": i, "texto": texto, "cantidad": por_indice.get(i, 0),
             "porcentaje": _porcentaje(por_indice.get(i, 0), total)}
            for i, texto in enumerate(opciones)]


def _booleano(s, encuesta_id: int, p: dict, filtros: dict, respondieron: int) -> list:
    q = db.select(db.RespuestaEncuesta.valor_numero, func.count()) \
        .select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"]) \
        .group_by(db.RespuestaEncuesta.valor_numero)
    por_valor = {int(v or 0): int(n) for v, n in s.execute(_con_filtros_urna(q, filtros)).all()}
    total = sum(por_valor.values()) or 1
    return [{"indice": i, "texto": texto, "cantidad": por_valor.get(i, 0),
             "porcentaje": _porcentaje(por_valor.get(i, 0), total)}
            for i, texto in ((1, "Sí"), (0, "No"))]


def _numero(s, encuesta_id: int, p: dict, filtros: dict) -> dict:
    q = db.select(func.avg(db.RespuestaEncuesta.valor_numero),
                  func.min(db.RespuestaEncuesta.valor_numero),
                  func.max(db.RespuestaEncuesta.valor_numero)) \
        .select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"],
               db.RespuestaEncuesta.valor_numero != None)   # noqa: E711
    prom, minimo, maximo = s.execute(_con_filtros_urna(q, filtros)).one()
    return {"promedio": round(float(prom), 2) if prom is not None else None,
            "minimo": float(minimo) if minimo is not None else None,
            "maximo": float(maximo) if maximo is not None else None}


def _conteo_simple(s, encuesta_id: int, p: dict, filtros: dict, columna) -> list:
    q = db.select(columna, func.count()).select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"], columna != "") \
        .group_by(columna).order_by(columna)
    return [{"valor": v, "cantidad": int(n)}
            for v, n in s.execute(_con_filtros_urna(q, filtros)).all()]


def _textos(s, encuesta_id: int, p: dict, filtros: dict) -> list:
    """Las respuestas de texto libre, que no se grafican: se leen.

    Van sin orden de carga -- ordenadas por el texto mismo -- para que el
    listado no reconstruya en qué secuencia entraron las respuestas.
    """
    q = db.select(db.RespuestaEncuesta.valor_texto).select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == encuesta_id,
               db.RespuestaEncuesta.pregunta_id == p["id"],
               db.RespuestaEncuesta.valor_texto != "") \
        .order_by(db.RespuestaEncuesta.valor_texto).limit(MAX_TEXTOS)
    return [t for (t,) in s.execute(_con_filtros_urna(q, filtros)).all()]


# ---------- Andamiaje ----------

def _pregunta_testigo(preguntas: list):
    """La pregunta con la que se cuenta GENTE en la urna.

    Una obligatoria de las que dejan exactamente una fila por persona: como
    una respuesta sin obligatoria se rechaza entera, su cantidad de filas es
    la cantidad de personas, exacta. Si no hay ninguna obligatoria se usa una
    opcional del mismo grupo (cuenta a los que la respondieron), y si la
    encuesta es toda de múltiples o rankings no hay testigo y la curva de
    ritmo queda vacía en vez de mentir contando opciones.
    """
    candidatas = [p for p in preguntas if p["tipo_dato"] in TIPOS_UNA_FILA]
    for p in candidatas:
        if p.get("obligatorio"):
            return p
    return candidatas[0] if candidatas else None


def _respondentes(s, e: dict, filtros: dict, testigo) -> int:
    """Cuánta gente del grupo filtrado respondió, contada en la URNA.

    Es el número contra el que se compara el umbral, y tiene que salir de la
    urna y no del padrón: el umbral protege a los que están adentro de un
    corte de la encuesta, que es lo que la urna guarda.
    """
    if not testigo:
        # Sin testigo se cuentan filas: es un techo, nunca un piso, así que
        # el umbral nunca se relaja por esta vía.
        q = db.select(func.count()).select_from(db.RespuestaEncuesta) \
            .where(db.RespuestaEncuesta.encuesta_id == e["id"])
        return int(s.execute(_con_filtros_urna(q, filtros)).scalar() or 0)
    q = db.select(func.count()).select_from(db.RespuestaEncuesta) \
        .where(db.RespuestaEncuesta.encuesta_id == e["id"],
               db.RespuestaEncuesta.pregunta_id == testigo["id"])
    return int(s.execute(_con_filtros_urna(q, filtros)).scalar() or 0)


def _valores_de_filtro(s, e: dict) -> dict:
    """Los valores que de verdad hay en la urna para cada corte habilitado,
    con su etiqueta. Salen de la URNA y no del padrón para que el desplegable
    no ofrezca un grupo que no tiene ni una respuesta -- elegirlo daría
    siempre vacío y parecería un error."""
    salida = {}
    for corte in (e.get("cortes") or []):
        if corte not in encuestas.CORTES:
            continue
        columna = _columna_urna(corte)
        filas = s.execute(
            db.select(columna, func.count()).select_from(db.RespuestaEncuesta)
            .where(db.RespuestaEncuesta.encuesta_id == e["id"])
            .group_by(columna)).all()
        valores = [(v, int(n)) for v, n in filas if v not in (None, "")]
        salida[corte] = _con_etiquetas(s, corte, valores, e["sindicato_id"])
    return salida


def _con_etiquetas(s, corte: str, valores: list, sindicato_id: int) -> list:
    """Le pone nombre a cada valor. Seccional y empleador se resuelven contra
    los catálogos del sindicato (chicos); la provincia ya es su propio
    nombre."""
    if corte == "seccional":
        nombres = {x.id: x.nombre for x in s.exec(db.select(db.Seccional).where(
            db.Seccional.sindicato_id == sindicato_id)).all()}
        return sorted(({"valor": str(v), "etiqueta": nombres.get(v, f"Seccional {v}"),
                        "cantidad": n} for v, n in valores),
                      key=lambda d: d["etiqueta"])
    if corte == "empleador":
        nombres = {_solo_digitos(x.cuit): (x.razon_social or x.cuit)
                   for x in s.exec(db.select(db.Empleador).where(
                       db.Empleador.sindicato_id == sindicato_id)).all()}
        return sorted(({"valor": str(v), "etiqueta": nombres.get(_solo_digitos(v), str(v)),
                        "cantidad": n} for v, n in valores),
                      key=lambda d: d["etiqueta"])
    return sorted(({"valor": str(v), "etiqueta": str(v), "cantidad": n} for v, n in valores),
                  key=lambda d: d["etiqueta"])


def _columna_urna(corte: str):
    return getattr(db.RespuestaEncuesta, encuestas.CORTES[corte][1])


def _columna_trabajador(corte: str):
    return getattr(db.Trabajador, encuestas.CORTES[corte][1])


def _tipados(corte: str, valores: list):
    """La seccional es un entero en la base y un string en la URL."""
    if corte != "seccional":
        return valores
    salida = []
    for v in valores:
        try:
            salida.append(int(v))
        except (TypeError, ValueError):
            pass
    return salida or [0]


def _con_filtros_urna(q, filtros: dict):
    """El recorte por cortes, EN LA CONSULTA. Acá es donde el umbral y los
    filtros dejan de ser una promesa de la pantalla."""
    for corte, valores in (filtros or {}).items():
        if corte in encuestas.CORTES:
            q = q.where(_columna_urna(corte).in_(_tipados(corte, valores)))
    return q


def _porcentaje(parte: int, total: int):
    return round(parte * 100 / total, 1) if total else 0.0


def _solo_digitos(texto) -> str:
    return "".join(c for c in str(texto or "") if c.isdigit())


# ---------- Lo que ve el afiliado cuando la encuesta cierra (N12) ----------

def totales_para_afiliado(encuesta_id: int, sindicato_id: int) -> dict:
    """Los totales GENERALES de una encuesta cerrada, sin ningún corte.

    Nunca los cortes: es por ahí por donde se identifica gente, y el
    afiliado no tiene padrón ni filtros con los que contrastar. Devuelve
    None si la encuesta no llegó a ese estado o el tilde está apagado.
    """
    e = db.encuesta_por_id(encuesta_id, sindicato_id)
    if not e or not e["mostrar_resultados"]:
        return None
    # CERRADA y no "ya no acepta respuestas": una programada tampoco las
    # acepta todavía y no tiene nada que mostrar.
    if e["estado"] != encuestas.CERRADA:
        return None
    with db.Session(db.engine) as s:
        testigo = _pregunta_testigo(e["preguntas"])
        respondentes = _respondentes(s, e, {}, testigo)
        if e["modo"] == encuestas.ANONIMA and respondentes < e["umbral_minimo"]:
            return None
        preguntas = _por_pregunta(s, e, {}, respondentes)
    # El texto libre NO se le devuelve al afiliado, y se saca acá y no en la
    # pantalla: una respuesta escrita a mano puede identificar sola a quien
    # la escribió, y esconderla en el JS dejaría igual el dato en el JSON.
    for p in preguntas:
        p.pop("textos", None)
        p.pop("fechas", None)
    return {"titulo": e["titulo"], "respondentes": respondentes, "preguntas": preguntas}


# ---------- Exportar (N20) ----------
# Dos archivos muy distintos, y la diferencia NO es cosmética:
#
# - En una NOMINAL, una fila por persona con nombre, CUIL y sus respuestas.
#   Es exactamente lo que el afiliado aceptó al responder una encuesta que
#   dice "nominal" en la cara.
# - En una ANÓNIMA, SOLO conteos y porcentajes con el umbral ya aplicado.
#   Nunca fila por respuesta: si no, cualquiera abre la planilla, filtra
#   "Rosario + Empresa X" y se queda con dos filas que identifican a dos
#   personas. El umbral que protege la pantalla no protege nada si el
#   archivo sale crudo.
#
# El separador es ";" y el archivo lleva BOM: es lo que abre bien el Excel
# en español sin pasar por el asistente de importación, que es donde este
# archivo se va a abrir.
SEPARADOR = ";"
BOM = "﻿"


def csv_de_encuesta(encuesta_id: int, sindicato_id: int, pedidos: dict, alcance=None) -> dict:
    """{ok, error, nombre, contenido, filas, tipo}. Los mismos filtros que el
    dashboard, recorte por seccional (N18) incluido: quien no puede ver un
    grupo en pantalla tampoco se lo puede bajar."""
    e = db.encuesta_por_id(encuesta_id, sindicato_id)
    if not e:
        return {"ok": False, "error": "La encuesta no existe."}
    if not e["publicada"]:
        return {"ok": False, "error": "Una encuesta sin publicar no tiene nada que exportar."}
    f = filtros_saneados(e, pedidos, alcance)["aplicados"]
    anonima = e["modo"] == encuestas.ANONIMA

    with db.Session(db.engine) as s:
        testigo = _pregunta_testigo(e["preguntas"])
        respondentes = _respondentes(s, e, f, testigo)
        if anonima and respondentes < e["umbral_minimo"]:
            return {"ok": False, "error":
                    f"Este grupo tiene {respondentes} respuestas y hacen falta "
                    f"{e['umbral_minimo']}. En una encuesta anónima un grupo chico deja de "
                    f"ser anónimo, así que tampoco se exporta."}
        filas = (_csv_agregado(s, e, f, respondentes) if anonima
                 else _csv_nominal(s, e, f))
    salida = BOM + "".join(SEPARADOR.join(_celda(c) for c in fila) + "\r\n" for fila in filas)
    return {"ok": True, "error": "", "contenido": salida,
            "nombre": _nombre_archivo(e, anonima),
            "filas": max(len(filas) - 1, 0),
            "tipo": "agregado" if anonima else "nominal"}


def _csv_nominal(s, e: dict, filtros: dict) -> list:
    """Una fila por persona del padrón, con sus respuestas.

    Va todo el padrón y no solo los que contestaron, con una columna
    "Respondió": la lista de los que faltan es la mitad de para qué se baja
    este archivo. El vínculo respuesta→persona vive en RespuestaNominal,
    que es la tabla que SOLO existe en las nominales.
    """
    preguntas = [p for p in e["preguntas"] if p["tipo_dato"] not in encuestas.TIPOS_SIN_RESPUESTA]
    cuils = _cuils_alcanzados(s, e, filtros)

    q = (db.select(db.EncuestaParticipante.cuil, db.EncuestaParticipante.respondio,
                   db.Trabajador.nombre, db.Trabajador.seccional_id,
                   db.Trabajador.provincia, db.Trabajador.cuit_empleador)
         .join(db.Trabajador, db.Trabajador.cuil == db.EncuestaParticipante.cuil)
         .where(db.EncuestaParticipante.encuesta_id == e["id"],
                db.Trabajador.sindicato_id == e["sindicato_id"])
         .order_by(db.Trabajador.nombre))
    if cuils is not None:
        q = q.where(db.EncuestaParticipante.cuil.in_(cuils or ["__ninguno__"]))
    gente = s.execute(q).all()

    respuestas = _respuestas_por_cuil(s, e["id"])
    nombres_sec = {x.id: x.nombre for x in s.exec(db.select(db.Seccional).where(
        db.Seccional.sindicato_id == e["sindicato_id"])).all()}

    cabecera = ["Nombre", "CUIL", "Seccional", "Provincia", "CUIT empleador", "Respondió"]
    cabecera += [p["etiqueta"] for p in preguntas]
    filas = [cabecera]
    for cuil, respondio, nombre, sec, prov, cuit in gente:
        fila = [nombre, cuil, nombres_sec.get(sec, ""), prov or "", cuit or "",
                "Sí" if respondio else "No"]
        suyas = respuestas.get(cuil, {})
        fila += [_texto_de_respuesta(p, suyas.get(p["id"], [])) for p in preguntas]
        filas.append(fila)
    return filas


def _respuestas_por_cuil(s, encuesta_id: int) -> dict:
    """{cuil: {pregunta_id: [filas de la urna]}}, vía RespuestaNominal."""
    pares = s.execute(
        db.select(db.RespuestaNominal.cuil, db.RespuestaEncuesta)
        .join(db.RespuestaEncuesta, db.RespuestaEncuesta.id == db.RespuestaNominal.respuesta_id)
        .where(db.RespuestaNominal.encuesta_id == encuesta_id)).all()
    salida = {}
    for cuil, fila in pares:
        salida.setdefault(cuil, {}).setdefault(fila.pregunta_id, []).append(fila)
    return salida


def _texto_de_respuesta(p: dict, filas: list) -> str:
    """Lo que esa persona contestó a esa pregunta, en una celda."""
    if not filas:
        return ""
    tipo = p["tipo_dato"]
    opciones = encuestas.opciones_de(p.get("opciones", ""))

    def opcion(i):
        return opciones[i] if i is not None and 0 <= i < len(opciones) else ""

    if tipo == "ranking":
        ordenadas = sorted(filas, key=lambda f: f.posicion or 0)
        return " > ".join(opcion(f.opcion_indice) for f in ordenadas)
    if tipo == "multiple":
        return ", ".join(sorted(opcion(f.opcion_indice) for f in filas))
    f = filas[0]
    if tipo in ("seleccion", "opcion_unica"):
        return opcion(f.opcion_indice)
    if tipo == "booleano":
        return "Sí" if (f.valor_numero or 0) >= 1 else "No"
    if tipo in ("escala", "numero"):
        return "" if f.valor_numero is None else _numero_ar(f.valor_numero)
    if tipo == "fecha":
        return f.valor_fecha
    return f.valor_texto


def _csv_agregado(s, e: dict, filtros: dict, respondentes: int) -> list:
    """Conteos y porcentajes, nunca una fila por respuesta.

    Lleva arriba de todo qué grupo es: un archivo suelto sin esa línea no se
    puede interpretar tres meses después, y peor, se puede confundir con el
    total general.
    """
    grupo = _describir_grupo(s, e, filtros)
    filas = [["Encuesta", e["titulo"]],
             ["Modo", "Anónima"],
             ["Grupo", grupo],
             ["Personas que respondieron", str(respondentes)],
             ["Umbral mínimo", str(e["umbral_minimo"])],
             [],
             ["Pregunta", "Tipo", "Opción", "Cantidad", "Porcentaje", "Promedio"]]

    for p in _por_pregunta(s, e, filtros, respondentes):
        tipo = p["tipo_dato"]
        if tipo == "escala":
            prom = p["escala"]["promedio"]
            for x in p["escala"]["distribucion"]:
                filas.append([p["etiqueta"], tipo, str(x["valor"]), str(x["cantidad"]),
                              _numero_ar(x["porcentaje"]),
                              _numero_ar(prom) if prom is not None else ""])
        elif tipo == "ranking":
            for x in p["ranking"]:
                filas.append([p["etiqueta"], tipo, x["texto"], str(x["primeras"]), "",
                              _numero_ar(x["promedio"]) if x["promedio"] is not None else ""])
        elif tipo == "numero":
            n = p["numero"]
            filas.append([p["etiqueta"], tipo, "", str(p["respondieron"]), "",
                          _numero_ar(n["promedio"]) if n["promedio"] is not None else ""])
        elif p.get("opciones") is not None:
            for x in p["opciones"]:
                filas.append([p["etiqueta"], tipo, x["texto"], str(x["cantidad"]),
                              _numero_ar(x["porcentaje"]), ""])
        else:
            # Texto libre y fechas: solo cuántos contestaron. El texto crudo
            # de una anónima identifica solo a quien lo escribió, y una
            # planilla circula sin control.
            filas.append([p["etiqueta"], tipo, "", str(p["respondieron"]), "", ""])
    return filas


def _describir_grupo(s, e: dict, filtros: dict) -> str:
    if not filtros:
        return "Todas las respuestas"
    partes = []
    disponibles = _valores_de_filtro(s, e)
    for corte, valores in filtros.items():
        etiquetas = {v["valor"]: v["etiqueta"] for v in disponibles.get(corte, [])}
        nombre = encuestas.CORTES[corte][0]
        partes.append(f"{nombre}: " + ", ".join(etiquetas.get(v, v) for v in valores))
    return " · ".join(partes)


def _nombre_archivo(e: dict, anonima: bool) -> str:
    limpio = "".join(c if c.isalnum() or c in " -_" else "" for c in e["titulo"]).strip()
    limpio = (limpio or "encuesta").replace(" ", "-").lower()[:50]
    return f"{limpio}-{'agregado' if anonima else 'nominal'}-{fechas.hoy_texto()}.csv"


def _numero_ar(valor) -> str:
    """Coma decimal: es lo que el Excel en español interpreta como número.
    Con punto lo toma como texto y no se puede ni sumar una columna.

    Un entero sale sin decimales: un 4 en una escala de 1 a 5 es "4", no
    "4,0" -- la columna se lee de un vistazo y no parece una medición."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).replace(".", ",")


def _celda(valor) -> str:
    """Escapa una celda de CSV. El ; y el salto de línea obligan a comillar,
    y una comilla adentro se duplica."""
    texto = "" if valor is None else str(valor)
    if any(c in texto for c in (SEPARADOR, '"', "\n", "\r")):
        return '"' + texto.replace('"', '""') + '"'
    return texto


# ---------- Evolución entre tomas (N23) ----------

def linaje(encuesta_id: int, sindicato_id: int) -> list:
    """Las tomas sucesivas de la misma encuesta, de la más vieja a la más
    nueva. `duplicar_encuesta` aplana el linaje --toda copia apunta a la
    RAÍZ, no a la copia anterior--, así que la familia entera sale de una
    consulta y no de recorrer una cadena."""
    with db.Session(db.engine) as s:
        e = s.get(db.Encuesta, encuesta_id)
        if not e or e.sindicato_id != sindicato_id:
            return []
        raiz = e.origen_id or e.id
        filas = s.exec(db.select(db.Encuesta).where(
            db.Encuesta.sindicato_id == sindicato_id,
            db.or_(db.Encuesta.id == raiz, db.Encuesta.origen_id == raiz))
            .order_by(db.Encuesta.id)).all()
        hoy = fechas.hoy_texto()
        return [{"id": x.id, "titulo": x.titulo, "publicada": x.publicada,
                 "fecha_desde": x.fecha_desde, "fecha_hasta": x.fecha_hasta,
                 "modo": x.modo, "umbral_minimo": x.umbral_minimo,
                 "estado": encuestas.estado(x.publicada, x.fecha_desde, x.fecha_hasta,
                                            hoy, x.cerrada_en)}
                for x in filas if x.publicada]


def evolucion(encuesta_id: int, sindicato_id: int, alcance=None) -> dict:
    """La misma pregunta a lo largo de las tomas sucesivas (N23).

    Es lo que convierte un dato suelto en una herramienta de gestión: "esto
    veníamos midiendo hace un año". Las preguntas se emparejan por ORDEN y
    tipo, que es lo que `duplicar_encuesta` preserva; una toma a la que le
    corrigieron la redacción sigue emparejando, y una que cambió el tipo de
    pregunta deja de hacerlo --que es lo correcto, porque ya no mide lo
    mismo.

    Cada toma se calcula con su PROPIO umbral (el que se congeló al
    publicarla): una toma chica no aporta punto en vez de aportar uno que
    identifica gente.
    """
    tomas = linaje(encuesta_id, sindicato_id)
    if len(tomas) < 2:
        return {"tomas": [], "preguntas": []}

    calculadas = []
    for t in tomas:
        e = db.encuesta_por_id(t["id"], sindicato_id)
        f = filtros_saneados(e, {}, alcance)["aplicados"]
        with db.Session(db.engine) as s:
            testigo = _pregunta_testigo(e["preguntas"])
            respondentes = _respondentes(s, e, f, testigo)
            oculto = e["modo"] == encuestas.ANONIMA and respondentes < e["umbral_minimo"]
            calculadas.append({
                "toma": {**t, "respondentes": respondentes, "oculto": oculto},
                "preguntas": {} if oculto else {
                    (i, p["tipo_dato"]): p
                    for i, p in enumerate(_por_pregunta(s, e, f, respondentes))},
            })

    # La última toma manda, porque es la que tiene la redacción vigente --
    # pero la última CON DATOS: si la toma más nueva quedó por debajo del
    # umbral, sin este detalle la evolución entera desaparecía justo cuando
    # más sirve (hay historia y la última ronda salió floja).
    referencia = next((c["preguntas"] for c in reversed(calculadas) if c["preguntas"]), {})
    salida = []
    for clave, p in referencia.items():
        if p["tipo_dato"] not in ("escala", "seleccion", "opcion_unica", "multiple",
                                  "booleano", "ranking"):
            continue
        serie = _serie_de(clave, p, calculadas)
        if serie:
            salida.append({"etiqueta": p["etiqueta"], "tipo_dato": p["tipo_dato"],
                           "lineas": serie})
    return {"tomas": [c["toma"] for c in calculadas], "preguntas": salida}


def _serie_de(clave, referencia: dict, calculadas: list) -> list:
    """Una línea por opción (o una sola, en la escala), con un valor por
    toma. None donde la toma no aporta -- por umbral o porque la pregunta
    no existía todavía."""
    if referencia["tipo_dato"] == "escala":
        return [{"nombre": "Promedio",
                 "valores": [_valor_escala(c["preguntas"].get(clave)) for c in calculadas]}]
    if referencia["tipo_dato"] == "ranking":
        opciones = sorted(referencia["ranking"], key=lambda x: x["indice"])
        return [{"nombre": o["texto"],
                 "valores": [_valor_ranking(c["preguntas"].get(clave), o["indice"])
                             for c in calculadas]}
                for o in opciones]
    return [{"nombre": o["texto"],
             "valores": [_valor_opcion(c["preguntas"].get(clave), o["indice"])
                         for c in calculadas]}
            for o in referencia.get("opciones", [])]


def _valor_escala(p):
    return p["escala"]["promedio"] if p else None


def _valor_ranking(p, indice):
    if not p:
        return None
    for x in p["ranking"]:
        if x["indice"] == indice:
            return x["promedio"]
    return None


def _valor_opcion(p, indice):
    if not p:
        return None
    for x in p.get("opciones", []):
        if x["indice"] == indice:
            return x["porcentaje"]
    return None
