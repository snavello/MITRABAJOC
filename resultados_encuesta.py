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
