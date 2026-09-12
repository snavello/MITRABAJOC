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
from datetime import date

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

# Debajo de esta cantidad de respuestas, un grupo del cruce se muestra pero
# NO se lee como una tendencia: "el 100% de este empleador" con una sola
# persona encabezaba la lista como si fuera un hallazgo. No es el umbral de
# anonimato --ese esconde el grupo entero y solo rige en las anónimas--,
# es una cuestión de precisión: un porcentaje sobre uno no compara nada.
MINIMO_PARA_COMPARAR = 5


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

    # El rango de fechas corre sobre el DÍA que guarda la urna, así que
    # recorta los gráficos y el ritmo pero NO el padrón, que no sabe cuándo
    # respondió cada uno (y a propósito: es el punto 3 del anonimato). Se
    # acota a la ventana de la encuesta -- pedir marzo de una encuesta de
    # septiembre devolvería vacío y parecería un error.
    desde, hasta = _dia_pedido(pedidos.get("desde")), _dia_pedido(pedidos.get("hasta"))
    if desde or hasta:
        desde = max(desde or e["fecha_desde"], e["fecha_desde"])
        hasta = min(hasta or e["fecha_hasta"], e["fecha_hasta"])
        if desde <= hasta:
            salida["_dias"] = [desde, hasta]

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
            "filtros": {**f, "disponibles": _valores_de_filtro(s, e, testigo),
                        # El rango sale aparte del resto: la pantalla lo
                        # dibuja con un calendario, no con pastillas.
                        "dias": f["aplicados"].get("_dias", []),
                        "ventana": [e["fecha_desde"], e["fecha_hasta"]]},
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
    cortes = {k: v for k, v in (filtros or {}).items() if k in encuestas.CORTES}
    if not cortes:
        return None
    q = (db.select(db.EncuestaParticipante.cuil)
         .join(db.Trabajador, db.Trabajador.cuil == db.EncuestaParticipante.cuil)
         .where(db.EncuestaParticipante.encuesta_id == e["id"],
                db.Trabajador.sindicato_id == e["sindicato_id"]))
    for corte, valores in cortes.items():
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
    # Promedio solo miente cuando la distribución es de dos jorobas: 5 y 5
    # da lo mismo que 1 y 9. La MEDIANA y los dos extremos ("cuántos están
    # en los dos valores más bajos / más altos") son los que dicen si el
    # promedio se puede creer.
    ancho = maximo - minimo + 1
    bajos = sum(por_valor.get(v, 0) for v in range(minimo, minimo + max(1, ancho // 5)))
    altos = sum(por_valor.get(v, 0) for v in range(maximo - max(0, ancho // 5 - 1), maximo + 1))
    return {
        "min": minimo, "max": maximo,
        "etiqueta_min": p.get("etiqueta_min", ""), "etiqueta_max": p.get("etiqueta_max", ""),
        "promedio": round(suma / total, 2) if total else None,
        "mediana": _mediana(por_valor, total),
        "respuestas": total,
        "bajos": {"cantidad": bajos, "porcentaje": _porcentaje(bajos, total)},
        "altos": {"cantidad": altos, "porcentaje": _porcentaje(altos, total)},
        "distribucion": [{"valor": v, "cantidad": por_valor.get(v, 0),
                          "porcentaje": _porcentaje(por_valor.get(v, 0), total)}
                         for v in range(minimo, maximo + 1)],
    }


def _mediana(por_valor: dict, total: int):
    """El valor que parte la muestra al medio. Se calcula del conteo por
    valor y no ordenando una lista: la urna puede tener miles de filas."""
    if not total:
        return None
    mitad, acumulado = total / 2, 0
    for v in sorted(por_valor):
        acumulado += por_valor[v]
        if acumulado >= mitad:
            return v
    return None


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


def _valores_de_filtro(s, e: dict, testigo=None) -> dict:
    """Los valores que de verdad hay en la urna para cada corte habilitado,
    con su etiqueta y CUÁNTA GENTE hay en cada uno.

    Salen de la URNA y no del padrón para que la pastilla no ofrezca un
    grupo sin ni una respuesta -- elegirlo daría siempre vacío y parecería
    un error.

    El conteo va sobre la PREGUNTA TESTIGO y no sobre todas las filas: una
    encuesta de cinco preguntas con una múltiple deja ocho filas por
    persona, y la pastilla decía "125" donde hay quince personas. Un número
    al lado de un filtro que no es el que después aparece en pantalla es
    peor que no tener número.
    """
    salida = {}
    for corte in (e.get("cortes") or []):
        if corte not in encuestas.CORTES:
            continue
        columna = _columna_urna(corte)
        q = db.select(columna, func.count()).select_from(db.RespuestaEncuesta) \
            .where(db.RespuestaEncuesta.encuesta_id == e["id"]).group_by(columna)
        if testigo:
            q = q.where(db.RespuestaEncuesta.pregunta_id == testigo["id"])
        filas = s.execute(q).all()
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


def _dia_pedido(valor) -> str:
    """"2026-09-15" o nada. Cualquier otra cosa se descarta: un filtro que
    llega roto por la URL no puede devolver un recorte al azar."""
    texto = str(valor or "").strip()
    if len(texto) == 10 and texto[4] == "-" and texto[7] == "-":
        try:
            date.fromisoformat(texto)
            return texto
        except ValueError:
            pass
    return ""


def _con_filtros_urna(q, filtros: dict):
    """El recorte por cortes y por fecha, EN LA CONSULTA. Acá es donde el
    umbral y los filtros dejan de ser una promesa de la pantalla."""
    for corte, valores in (filtros or {}).items():
        if corte in encuestas.CORTES:
            q = q.where(_columna_urna(corte).in_(_tipados(corte, valores)))
    dias = (filtros or {}).get("_dias")
    if dias:
        # El día se guarda como texto AAAA-MM-DD: ordenable y comparable
        # como string, igual que el resto de las fechas del proyecto.
        q = q.where(db.RespuestaEncuesta.dia >= dias[0], db.RespuestaEncuesta.dia <= dias[1])
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
    respuestas = _respuestas_por_cuil(s, e["id"], filtros)
    # Con un rango de fechas puesto, el archivo tiene que decir lo mismo que
    # la pantalla: solo la gente que respondió DENTRO del rango. Antes se
    # ignoraba en silencio y el CSV traía a todo el padrón.
    if filtros.get("_dias"):
        con_respuesta = set(respuestas)
        cuils = (cuils & con_respuesta) if cuils is not None else con_respuesta

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


def _respuestas_por_cuil(s, encuesta_id: int, filtros: dict = None) -> dict:
    """{cuil: {pregunta_id: [filas de la urna]}}, vía RespuestaNominal."""
    q = (db.select(db.RespuestaNominal.cuil, db.RespuestaEncuesta)
         .join(db.RespuestaEncuesta, db.RespuestaEncuesta.id == db.RespuestaNominal.respuesta_id)
         .where(db.RespuestaNominal.encuesta_id == encuesta_id))
    pares = s.execute(_con_filtros_urna(q, filtros or {})).all()
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
        if corte == "_dias":
            partes.append(f"Respondidas entre el {fechas.dia_legible(valores[0])} y el "
                          f"{fechas.dia_legible(valores[1])}")
            continue
        if corte not in encuestas.CORTES:
            continue
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


# ---------- El cruce: tocar una opción y ver dónde se concentra ----------
#
# Es la pregunta que un sindicato hace de verdad mirando un gráfico: "el
# 30% dijo que el ambiente está tenso... ¿tenso DÓNDE?". Un total no se
# puede accionar; "el 62% de la sucursal Centro" sí.
#
# Qué se puede cruzar, y por qué no es una limitación arbitraria:
#
# - **Contra los CORTES (seccional, provincia, empleador): SIEMPRE.** Cada
#   fila de la urna guarda sus propios cortes, así que agrupar "los que
#   eligieron esta opción" por empleador es un GROUP BY sobre la misma fila.
#   No hace falta saber quién respondió.
# - **Contra OTRAS PREGUNTAS: solo en las NOMINALES.** Eso exige saber que
#   la respuesta A y la respuesta B son de la misma persona, y en una
#   anónima esa unión no existe -- es exactamente la garantía del módulo, no
#   un agujero. En una nominal el vínculo está en `RespuestaNominal` y el
#   afiliado respondió sabiéndolo.
#
# El número que se muestra no es el conteo pelado sino la COMPARACIÓN: "en
# este empleador el 62% eligió esta opción, contra el 29% general". Un
# conteo no dice si algo se concentra; la diferencia contra el general, sí.

def cruce(encuesta_id: int, sindicato_id: int, pregunta_id: int, opcion: str,
          pedidos: dict, alcance=None) -> dict:
    """Dónde se concentra una opción. Devuelve None si la encuesta no es de
    este sindicato o la pregunta no es de esta encuesta."""
    e = db.encuesta_por_id(encuesta_id, sindicato_id)
    if not e:
        return None
    pregunta = next((p for p in e["preguntas"] if p["id"] == pregunta_id), None)
    if not pregunta:
        return None
    f = filtros_saneados(e, pedidos, alcance)["aplicados"]
    anonima = e["modo"] == encuestas.ANONIMA
    umbral = e["umbral_minimo"] if anonima else 0
    condicion = _condicion_de_opcion(pregunta, opcion)
    if condicion is None:
        return None

    with db.Session(db.engine) as s:
        # El universo: cuánta gente contestó ESTA pregunta con el filtro
        # vigente, y cuánta eligió esta opción.
        total = _cuenta_pregunta(s, encuesta_id, pregunta, f, None)
        elegidos = _cuenta_pregunta(s, encuesta_id, pregunta, f, condicion)
        if anonima and elegidos < umbral:
            return {"encuesta": e["id"], "pregunta": pregunta["etiqueta"],
                    "opcion": _texto_de_opcion(pregunta, opcion), "total": total,
                    "elegidos": elegidos, "oculto": True, "umbral": umbral,
                    "cortes": {}, "preguntas": [], "puede_cruzar_preguntas": not anonima}

        cortes = {}
        for corte in (e.get("cortes") or []):
            if corte not in encuestas.CORTES:
                continue
            cortes[corte] = _cruce_por_corte(s, e, pregunta, condicion, f, corte, umbral)

        # El cruce contra las otras preguntas necesita saber de quién es
        # cada respuesta: solo existe en las nominales.
        otras = _cruce_por_pregunta(s, e, pregunta, condicion, f) if not anonima else []

    return {
        "encuesta": e["id"], "pregunta": pregunta["etiqueta"],
        "pregunta_id": pregunta["id"], "opcion": _texto_de_opcion(pregunta, opcion),
        "total": total, "elegidos": elegidos,
        "porcentaje": _porcentaje(elegidos, total),
        "oculto": False, "umbral": umbral,
        "cortes": cortes, "preguntas": otras,
        "puede_cruzar_preguntas": not anonima,
    }


def _condicion_de_opcion(pregunta: dict, opcion: str):
    """La condición SQL que aísla "los que eligieron esta opción".

    Una escala y un número se cruzan por su VALOR (elegí el 7), una opción
    por su índice, un sí/no por 1 ó 0. Devuelve None si la opción no existe:
    un índice inventado por la URL no puede devolver un recorte al azar.
    """
    tipo = pregunta["tipo_dato"]
    if tipo in ("escala", "numero", "booleano"):
        try:
            return db.RespuestaEncuesta.valor_numero == float(opcion)
        except (TypeError, ValueError):
            return None
    if tipo == "fecha":
        return db.RespuestaEncuesta.valor_fecha == str(opcion) if opcion else None
    opciones = encuestas.opciones_de(pregunta.get("opciones", ""))
    try:
        i = int(opcion)
    except (TypeError, ValueError):
        return None
    if not (0 <= i < len(opciones)):
        return None
    return db.RespuestaEncuesta.opcion_indice == i


def _texto_de_opcion(pregunta: dict, opcion: str) -> str:
    tipo = pregunta["tipo_dato"]
    if tipo == "booleano":
        return "Sí" if str(opcion) in ("1", "1.0") else "No"
    if tipo in ("escala", "numero", "fecha"):
        return _numero_ar(float(opcion)) if tipo != "fecha" else fechas.dia_legible(opcion)
    opciones = encuestas.opciones_de(pregunta.get("opciones", ""))
    i = int(opcion)
    return opciones[i] if 0 <= i < len(opciones) else str(opcion)


def _cuenta_pregunta(s, encuesta_id: int, pregunta: dict, filtros: dict, condicion) -> int:
    """Cuánta GENTE hay detrás de esas filas.

    En un ranking cada persona deja una fila por opción, así que contar
    filas contaría opciones. Con una condición puesta (una opción concreta)
    el ranking deja una sola fila por persona y el problema desaparece.
    """
    q = db.select(func.count()).select_from(db.RespuestaEncuesta).where(
        db.RespuestaEncuesta.encuesta_id == encuesta_id,
        db.RespuestaEncuesta.pregunta_id == pregunta["id"])
    if condicion is not None:
        q = q.where(condicion)
    filas = int(s.execute(_con_filtros_urna(q, filtros)).scalar() or 0)
    if condicion is None and pregunta["tipo_dato"] == "ranking":
        opciones = len(encuestas.opciones_de(pregunta.get("opciones", ""))) or 1
        return filas // opciones
    return filas


def _cruce_por_corte(s, e: dict, pregunta: dict, condicion, filtros: dict,
                     corte: str, umbral: int) -> dict:
    """Por cada valor del corte: cuántos eligieron la opción, cuántos
    respondieron la pregunta ahí, y la comparación contra el general.

    `dentro` es el número que se lee solo: "en este empleador, el 62%
    eligió esta opción". `del_grupo` dice de dónde sale el volumen: "el 38%
    de todos los que la eligieron están acá".
    """
    columna = _columna_urna(corte)
    base = db.select(columna, func.count()).select_from(db.RespuestaEncuesta).where(
        db.RespuestaEncuesta.encuesta_id == e["id"],
        db.RespuestaEncuesta.pregunta_id == pregunta["id"]).group_by(columna)

    # Denominador por bucket: cuánta gente respondió la pregunta ahí.
    totales = {v: int(n) for v, n in s.execute(_con_filtros_urna(base, filtros)).all()
               if v not in (None, "")}
    if pregunta["tipo_dato"] == "ranking":
        opciones = len(encuestas.opciones_de(pregunta.get("opciones", ""))) or 1
        totales = {v: n // opciones for v, n in totales.items()}

    elegidos = {v: int(n) for v, n in s.execute(
        _con_filtros_urna(base.where(condicion), filtros)).all() if v not in (None, "")}

    general = _porcentaje(sum(elegidos.values()), sum(totales.values()))
    crudo = []
    for valor, total_bucket in totales.items():
        cuantos = elegidos.get(valor, 0)
        # El umbral se aplica al BUCKET, no al total: un grupo chico no se
        # muestra ni siquiera para decir que eligió poco.
        if umbral and total_bucket < umbral:
            continue
        crudo.append({"valor": valor, "cantidad": cuantos, "base": total_bucket,
                      "dentro": _porcentaje(cuantos, total_bucket),
                      "del_grupo": _porcentaje(cuantos, sum(elegidos.values())),
                      # `poco` no esconde nada: avisa que ese porcentaje sale
                      # de tan pocas respuestas que no se puede leer como
                      # una tendencia.
                      "poco": total_bucket < MINIMO_PARA_COMPARAR})
    con_nombre = _con_etiquetas(s, corte, [(x["valor"], x["cantidad"]) for x in crudo],
                                e["sindicato_id"])
    etiquetas = {x["valor"]: x["etiqueta"] for x in con_nombre}
    for x in crudo:
        x["etiqueta"] = etiquetas.get(str(x["valor"]), str(x["valor"]))
        x["valor"] = str(x["valor"])
        # Cuánto se despega del promedio: es lo que hace que un número
        # sirva para decidir a dónde ir.
        x["diferencia"] = round(x["dentro"] - general, 1)
    # Los grupos chicos van al final: arriba tiene que estar lo que de
    # verdad se despega, no el 100% de una persona sola.
    crudo.sort(key=lambda x: (x["poco"], -x["dentro"]))
    return {"general": general, "filas": crudo,
            "minimo_para_comparar": MINIMO_PARA_COMPARAR,
            "escondidos": len(totales) - len(crudo)}


def _cruce_por_pregunta(s, e: dict, pregunta: dict, condicion, filtros: dict) -> list:
    """Cómo respondió ESE MISMO grupo las demás preguntas. Solo nominales.

    Se resuelve por `RespuestaNominal`: de las respuestas que cumplen la
    condición saco los CUIL, y con esos CUIL miro sus otras respuestas. En
    una anónima esta función no se llama -- no hay tabla que unir.
    """
    q = db.select(db.RespuestaNominal.cuil).join(
        db.RespuestaEncuesta, db.RespuestaEncuesta.id == db.RespuestaNominal.respuesta_id).where(
        db.RespuestaNominal.encuesta_id == e["id"],
        db.RespuestaEncuesta.pregunta_id == pregunta["id"], condicion)
    cuils = {c for c in s.execute(_con_filtros_urna(q, filtros)).scalars().all()}
    if not cuils:
        return []

    salida = []
    for otra in e["preguntas"]:
        if otra["id"] == pregunta["id"] or otra["tipo_dato"] in encuestas.TIPOS_SIN_RESPUESTA:
            continue
        if otra["tipo_dato"] not in ("seleccion", "opcion_unica", "multiple",
                                     "booleano", "escala"):
            continue
        filas = s.execute(
            db.select(db.RespuestaEncuesta.opcion_indice, db.RespuestaEncuesta.valor_numero)
            .join(db.RespuestaNominal,
                  db.RespuestaNominal.respuesta_id == db.RespuestaEncuesta.id)
            .where(db.RespuestaEncuesta.encuesta_id == e["id"],
                   db.RespuestaEncuesta.pregunta_id == otra["id"],
                   db.RespuestaNominal.cuil.in_(cuils))).all()
        if not filas:
            continue
        salida.append(_resumen_cruzado(otra, filas, len(cuils)))
    return salida


def _resumen_cruzado(pregunta: dict, filas: list, personas: int) -> dict:
    """Lo que ese grupo contestó en otra pregunta, comparable de un vistazo."""
    tipo = pregunta["tipo_dato"]
    if tipo == "escala":
        valores = [v for _, v in filas if v is not None]
        return {"id": pregunta["id"], "etiqueta": pregunta["etiqueta"], "tipo_dato": tipo,
                "personas": personas,
                "promedio": round(sum(valores) / len(valores), 2) if valores else None,
                "opciones": []}
    if tipo == "booleano":
        si = sum(1 for _, v in filas if (v or 0) >= 1)
        opciones = [{"texto": "Sí", "cantidad": si, "porcentaje": _porcentaje(si, personas)},
                    {"texto": "No", "cantidad": len(filas) - si,
                     "porcentaje": _porcentaje(len(filas) - si, personas)}]
    else:
        textos = encuestas.opciones_de(pregunta.get("opciones", ""))
        conteo = {}
        for i, _ in filas:
            if i is not None:
                conteo[int(i)] = conteo.get(int(i), 0) + 1
        opciones = [{"texto": t, "cantidad": conteo.get(n, 0),
                     "porcentaje": _porcentaje(conteo.get(n, 0), personas)}
                    for n, t in enumerate(textos)]
        opciones.sort(key=lambda x: -x["cantidad"])
    return {"id": pregunta["id"], "etiqueta": pregunta["etiqueta"], "tipo_dato": tipo,
            "personas": personas, "promedio": None, "opciones": opciones}
