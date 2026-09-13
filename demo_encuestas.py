"""Las encuestas de la demo: un padrón de verdad y tres tomas en el tiempo.

Lo carga `cargar_demo.py`. Vive aparte porque es lo único de la demo que
necesita generar CIENTOS de filas con una historia adentro, y mezclarlo con
el alta de seccionales y áreas dejaba ese archivo ilegible.

Por qué hace falta tanto dato: el módulo Encuestas no se puede mostrar con
tres afiliados. El **umbral** esconde cualquier grupo con menos de cinco
respuestas (que es lo correcto y lo que hay que mostrar, pero con un padrón
de tres esconde TODO), y la pantalla de **evolución** no existe hasta que
hay dos tomas de la misma encuesta. Una demo donde las dos cosas que más
cuesta explicar aparecen vacías es peor que no tenerlas.

La historia que cuentan los datos es deliberada, no ruido: entre la primera
toma y la tercera el clima mejora, la preocupación se corre del sueldo a la
seguridad, y **Córdoba mejora menos que Rosario** -- para que el filtro por
seccional muestre algo y no tres curvas iguales. Quien abre la demo tiene
que poder contar esa historia en voz alta mirando la pantalla.

Todo pasa por las funciones de `db` (crear, publicar, responder, notificar)
y no por INSERT directo, mismo criterio que el resto de `cargar_demo.py`:
la demo no puede quedar en un estado que la aplicación real no sepa
producir. Lo único que se toca a mano después es la VENTANA de cada toma y
el día de sus respuestas, porque una encuesta cerrada hace cuatro meses no
se puede responder hoy -- y sin historia no hay evolución que mostrar.
"""
import random
from datetime import timedelta

import db
import encuestas
import fechas
import geo

# Bloque de CUIL propio, separado de los de `cargar_lote_sindicato.py`
# (65000000+) y de los escritos a mano en `cargar_demo.py`, para que dos
# cargas no se pisen nunca.
BASE_CUIL = 48000000
CANTIDAD = 96

NOMBRES = ["Juan", "María", "Carlos", "Ana", "Jorge", "Lucía", "Pedro", "Sofía",
           "Miguel", "Valentina", "Ricardo", "Camila", "Héctor", "Julieta", "Oscar",
           "Paula", "Rubén", "Florencia", "Daniel", "Marina", "Néstor", "Silvia",
           "Alberto", "Gabriela", "Mario", "Norma", "Raúl", "Claudia"]
APELLIDOS = ["Gómez", "Fernández", "Rodríguez", "López", "Martínez", "Díaz", "Pérez",
             "Sánchez", "Romero", "Suárez", "Torres", "Álvarez", "Ruiz", "Ramírez",
             "Flores", "Benítez", "Acosta", "Medina", "Herrera", "Aguirre", "Godoy",
             "Cabrera", "Vega", "Quiroga", "Ponce", "Maidana", "Ojeda", "Correa"]

PREGUNTAS = [
    {"etiqueta": "¿Cómo calificás tu situación laboral hoy?", "tipo_dato": "escala",
     "escala_min": 1, "escala_max": 5, "etiqueta_min": "Muy mala", "etiqueta_max": "Muy buena",
     "ancho": "mitad", "obligatorio": True},
    {"etiqueta": "¿Qué es lo que más te preocupa?", "tipo_dato": "opcion_unica",
     "opciones": "El sueldo, Los horarios, La seguridad, El transporte",
     "ancho": "mitad", "obligatorio": True},
    {"etiqueta": "¿Qué querés que el sindicato empuje este año?", "tipo_dato": "multiple",
     "opciones": "Paritaria, Obra social, Capacitación, Ropa de trabajo, Guardería",
     "ancho": "mitad", "obligatorio": False},
    {"etiqueta": "Ordená los reclamos por prioridad", "tipo_dato": "ranking",
     "opciones": "Salario, Condiciones de seguridad, Jornada",
     "ancho": "mitad", "obligatorio": True},
    {"etiqueta": "¿Sentís que el sindicato te representa?", "tipo_dato": "booleano",
     "ancho": "completo", "obligatorio": True},
    {"etiqueta": "¿Algo que quieras agregar?", "tipo_dato": "texto",
     "ancho": "completo", "obligatorio": False},
]

COMENTARIOS = [
    "Hace falta más luz en el sector de prensas.",
    "El comedor mejoró bastante este año.",
    "Los vestuarios están muy venidos abajo.",
    "Que se cumpla el descanso entre turnos.",
    "El transporte de la noche llega tarde siempre.",
    "Estaría bueno tener capacitación en máquinas nuevas.",
    "Falta ropa de trabajo en talles grandes.",
    "El delegado de mi turno responde rápido, se agradece.",
]

# Cada toma: (meses atrás, cuánto participa, clima promedio, reparto de la
# preocupación entre sueldo/horarios/seguridad/transporte). El tercero es
# el que sigue abierto.
TOMAS = [
    {"titulo": "Clima laboral", "atras": 210, "participa": .48, "clima": 2.6,
     "preocupa": [58, 22, 14, 6]},
    {"titulo": "Clima laboral (2)", "atras": 105, "participa": .57, "clima": 3.2,
     "preocupa": [46, 24, 24, 6]},
    # Sigue ABIERTA, pero ya lleva dos semanas: si arrancara ayer, la curva
    # de ritmo sería un punto solo y no se entendería para qué está.
    {"titulo": "Clima laboral (3)", "atras": -14, "participa": .64, "clima": 3.9,
     "preocupa": [32, 25, 37, 6]},
]

# Córdoba mejora MENOS: sin esta diferencia el filtro por seccional muestra
# tres curvas iguales y no se entiende para qué está.
AJUSTE_SECCIONAL = {"Córdoba": -0.7, "Rosario": +0.3, "Sede Central": 0.0}

DURACION = 21          # días que dura cada toma


def sembrar(sid: int, secs: dict, cuits: list, usuario_id: int) -> dict:
    """Carga el padrón sintético y las encuestas. Devuelve un resumen."""
    rnd = random.Random(90210 + sid)
    padron = _padron(sid, secs, cuits, rnd)
    # El linaje se aplana a la RAÍZ, igual que lo deja `duplicar_encuesta`:
    # toda copia apunta a la primera toma y no a la anterior, así la familia
    # entera sale de una consulta.
    tomas, raiz = [], None
    for cfg in TOMAS:
        t = _toma(sid, usuario_id, {**cfg, "origen_id": raiz}, padron, rnd)
        raiz = raiz or t["id"]
        tomas.append(t)
    nominal = _nominal(sid, usuario_id, padron, rnd)
    return {"padron": len(padron), "tomas": tomas, "nominal": nominal}


def _padron(sid: int, secs: dict, cuits: list, rnd) -> list:
    """Afiliados sintéticos repartidos entre las seccionales y los
    empleadores. Sin esto, el umbral esconde todo y la demo no muestra nada."""
    nombres_sec = list(secs)
    filas = []
    with db.get_session() as s:
        # La zona del afiliado sale de SU seccional, leída de la base y no de
        # un mapa escrito acá: la provincia estaba hardcodeada y la localidad
        # no estaba, y desde el 2026-09-13 las dos son obligatorias en todas
        # las altas (geo.OBLIGATORIOS_AFILIADO). Un padrón de demo sin ellas
        # mostraría justo lo que la app ya no deja cargar.
        zonas = {sec.id: {"localidad": sec.localidad, "provincia": sec.provincia}
                 for sec in s.exec(db.select(db.Seccional).where(
                     db.Seccional.id.in_(list(secs.values())))).all()}
        for i in range(CANTIDAD):
            cuil = f"{'20' if i % 3 else '27'}{BASE_CUIL + i:08d}{(i * 7) % 10}"
            seccional = nombres_sec[i % len(nombres_sec)]
            cuit = cuits[i % len(cuits)] if cuits else None
            s.add(db.Trabajador(
                sindicato_id=sid, cuil=cuil,
                nombre=f"{rnd.choice(NOMBRES)} {rnd.choice(APELLIDOS)}",
                seccional_id=secs[seccional], cuit_empleador=cuit,
                **geo.campos_para_guardar(zonas.get(secs[seccional], {}),
                                          precision="sin_geo"),
                activo=True, registrado=True))
            filas.append({"cuil": cuil, "seccional": seccional})
        s.commit()
    return filas


def _toma(sid: int, usuario_id: int, cfg: dict, padron: list, rnd) -> dict:
    """Una toma completa: se crea ABIERTA (si no, la app rechaza las
    respuestas -- y hace bien), se responde, se avisa, y recién después se
    le corre la ventana hacia atrás para que tenga historia."""
    hoy = fechas.hoy()
    eid = db.crear_encuesta(sid, usuario_id, None, {
        "titulo": cfg["titulo"],
        "descripcion": "Tres minutos. Es anónima y nos dice por dónde pelear este año.",
        "modo": "anonima", "cortes": ["seccional", "empleador"],
        "fecha_desde": (hoy - timedelta(days=1)).isoformat(),
        "fecha_hasta": (hoy + timedelta(days=DURACION)).isoformat(),
        "mostrar_resultados": True,
        "origen_id": cfg.get("origen_id"),
    }, PREGUNTAS)
    db.publicar_encuesta(eid, sid, "todos", [], usuario_id=usuario_id)

    preguntas = db.encuesta_por_id(eid)["preguntas"]
    respondieron = 0
    for persona in padron:
        if rnd.random() > cfg["participa"]:
            continue
        if db.registrar_respuesta_encuesta(
                eid, persona["cuil"], sid,
                _respuesta(preguntas, cfg, persona["seccional"], rnd))["ok"]:
            respondieron += 1

    _avisar(eid, sid, usuario_id, cfg, rnd)
    _correr_al_pasado(eid, cfg["atras"], rnd)
    return {"id": eid, "titulo": cfg["titulo"], "respondieron": respondieron}


def _respuesta(preguntas: list, cfg: dict, seccional: str, rnd) -> dict:
    por_tipo = {p["tipo_dato"]: p for p in preguntas}
    clima = cfg["clima"] + AJUSTE_SECCIONAL.get(seccional, 0)
    valor = max(1, min(5, round(rnd.gauss(clima, 1.0))))
    salida = {
        str(por_tipo["escala"]["id"]): valor,
        str(por_tipo["opcion_unica"]["id"]): rnd.choices([0, 1, 2, 3],
                                                         weights=cfg["preocupa"])[0],
        # El ranking se responde ENTERO o no cuenta: acá se mezcla con un
        # sesgo hacia el salario, que es lo que una lista real devuelve.
        str(por_tipo["ranking"]["id"]): rnd.sample([0, 1, 2], 3) if rnd.random() < .35
        else [0, 1, 2],
        # Quien está peor tiende a sentirse menos representado: sin esa
        # correlación los dos gráficos no se explican uno al otro.
        str(por_tipo["booleano"]["id"]): "si" if rnd.random() < (valor / 6 + .25) else "no",
    }
    if rnd.random() < .4:
        salida[str(por_tipo["multiple"]["id"])] = rnd.sample(
            [0, 1, 2, 3, 4], rnd.randint(1, 3))
    if rnd.random() < .18:
        salida[str(por_tipo["texto"]["id"])] = rnd.choice(COMENTARIOS)
    return salida


def _avisar(eid: int, sid: int, usuario_id: int, cfg: dict, rnd) -> None:
    """El aviso de lanzamiento, con parte leído. Sin esto el KPI de "avisos
    leídos" queda en cero y el par participación/lectura --que es de donde
    sale la decisión de mandar o no un recordatorio-- no se puede leer."""
    e = db.encuesta_por_id(eid)
    r = db.notificar_encuesta(
        eid, sid, usuario_id,
        encuestas.texto_aviso(e["titulo"], e["fecha_hasta"], e["modo"]),
        "Comisión Directiva")
    if not r["ok"]:
        return
    with db.get_session() as s:
        notifs = s.exec(db.select(db.Notificacion).where(
            db.Notificacion.encuesta_id == eid)).all()
        for n in notifs:
            for d in s.exec(db.select(db.NotificacionDestinatario).where(
                    db.NotificacionDestinatario.notificacion_id == n.id)).all():
                if rnd.random() < cfg["participa"] + .18:
                    d.leida_en = fechas.ahora_texto()
                    s.add(d)
        s.commit()


def _correr_al_pasado(eid: int, atras: int, rnd) -> None:
    """Le corre la ventana --y el día de cada respuesta-- `atras` días.

    `atras` negativo deja la encuesta ABIERTA: son los días que le QUEDAN,
    así que del período ya corrió el resto -- y eso es lo que hace que la
    toma en curso tenga curva de ritmo en vez de un punto solo.

    Es lo único que se toca a mano: una encuesta que cerró hace cuatro
    meses no se puede responder hoy, y sin historia no hay evolución. Las
    respuestas se reparten con más peso al principio y otro pico al final,
    que es la forma real de una curva: se contesta cuando llega el aviso, y
    otra vez cuando se acerca el cierre.
    """
    with db.get_session() as s:
        e = s.get(db.Encuesta, eid)
        desde = fechas.hoy() - timedelta(days=atras + DURACION)
        # Una encuesta abierta no puede tener respuestas con fecha futura:
        # el último día que se pudo responder es HOY.
        corridos = DURACION if atras >= 0 else DURACION + atras
        e.fecha_desde = desde.isoformat()
        e.fecha_hasta = (desde + timedelta(days=DURACION)).isoformat()
        e.publicada_en = f"{e.fecha_desde} 09:00"
        s.add(e)
        for fila in s.exec(db.select(db.RespuestaEncuesta).where(
                db.RespuestaEncuesta.encuesta_id == eid)).all():
            fila.dia = (desde + timedelta(days=_dia_de_respuesta(rnd, corridos))).isoformat()
            s.add(fila)
        for n in s.exec(db.select(db.Notificacion).where(
                db.Notificacion.encuesta_id == eid)).all():
            n.enviado_en = f"{e.fecha_desde} 09:05"
            s.add(n)
        # El historial también: si dice que la encuesta se publicó hoy y la
        # ventana dice febrero, el primero que mira la demo pregunta por qué
        # -- y tiene razón.
        for v in s.exec(db.select(db.EventoEncuesta).where(
                db.EventoEncuesta.encuesta_id == eid)).all():
            v.fecha = f"{e.fecha_desde} 09:0{0 if v.evento == 'publicada' else 5}"
            s.add(v)
        s.commit()


def _dia_de_respuesta(rnd, corridos: int) -> int:
    """Día dentro de lo que YA PASÓ del período: mucho al principio (llegó
    el aviso), un repunte al final si el período ya terminó, poco en el
    medio."""
    if corridos <= 2:
        return rnd.randint(0, max(0, corridos))
    tirada = rnd.random()
    if tirada < .55:
        return rnd.randint(0, 3)
    if tirada < .75:
        return corridos - rnd.randint(0, 2)
    return rnd.randint(4, max(4, corridos - 3))


def _nominal(sid: int, usuario_id: int, padron: list, rnd) -> dict:
    """Una encuesta NOMINAL abierta, para que la demo muestre las dos caras.

    Sin una nominal no se ve el CSV con nombre y apellido --que es lo que un
    sindicato pide primero-- ni se entiende que el umbral es una protección
    del anonimato y no una limitación del módulo.
    """
    hoy = fechas.hoy()
    eid = db.crear_encuesta(sid, usuario_id, None, {
        "titulo": "¿En qué te querés capacitar?",
        "descripcion": "Con tu nombre, para poder anotarte en el curso que elijas.",
        "modo": "nominal", "cortes": ["seccional", "empleador", "provincia"],
        "fecha_desde": (hoy - timedelta(days=3)).isoformat(),
        "fecha_hasta": (hoy + timedelta(days=11)).isoformat(),
        "mostrar_resultados": False,
    }, [
        {"etiqueta": "¿Qué curso te interesa?", "tipo_dato": "opcion_unica",
         "opciones": "Soldadura, Control numérico, Seguridad e higiene, Oficios eléctricos",
         "ancho": "mitad", "obligatorio": True},
        {"etiqueta": "¿En qué turno podrías?", "tipo_dato": "seleccion",
         "opciones": "Mañana, Tarde, Noche, Sábados", "ancho": "mitad", "obligatorio": True},
        {"etiqueta": "¿Tenés experiencia previa?", "tipo_dato": "booleano",
         "ancho": "completo", "obligatorio": True},
    ])
    db.publicar_encuesta(eid, sid, "todos", [], usuario_id=usuario_id)
    preguntas = db.encuesta_por_id(eid)["preguntas"]
    respondieron = 0
    for persona in padron:
        if rnd.random() > .38:
            continue
        if db.registrar_respuesta_encuesta(eid, persona["cuil"], sid, {
                str(preguntas[0]["id"]): rnd.choices([0, 1, 2, 3], weights=[35, 20, 30, 15])[0],
                str(preguntas[1]["id"]): rnd.choices([0, 1, 2, 3], weights=[40, 25, 15, 20])[0],
                str(preguntas[2]["id"]): "si" if rnd.random() < .4 else "no",
        })["ok"]:
            respondieron += 1
    _avisar(eid, sid, usuario_id, {"participa": .38}, rnd)
    return {"id": eid, "titulo": "¿En qué te querés capacitar?", "respondieron": respondieron}
