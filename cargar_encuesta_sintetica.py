# -*- coding: utf-8 -*-
"""Llena una encuesta YA PUBLICADA con respuestas sintéticas verosímiles.

No crea la encuesta ni toca su estructura: la arma una persona en el panel,
con sus preguntas y sus opciones, y este script le pone adentro la cantidad
de respuestas que haría falta juntar para que las pantallas de resultados se
puedan mostrar. Es la herramienta para preparar una demo sobre una encuesta
de verdad, no para inventar una.

Uso (en la Shell de Render o con la DATABASE_URL del entorno apuntada):

    python cargar_encuesta_sintetica.py --sindicato "La Bancaria"     # ensayo
    python cargar_encuesta_sintetica.py --sindicato "La Bancaria" --si
    python cargar_encuesta_sintetica.py --sindicato "La Bancaria" --si \\
        --respuestas 85 --leidas 90 --encuesta 1

**Sin `--si` no escribe nada**: imprime exactamente lo que haría. Mismo
criterio que `clonar_demo_a_pruebas.py` -- un script que escribe en un
entorno compartido no se corre de memoria.

Cómo se reparten las respuestas (decidido con Sd el 2026-09-12):

- **Pareto, no uniforme.** Una opción dominante (~50-55%), la segunda a la
  mitad, y una cola que cae. Con todo parejo las barras del dashboard quedan
  iguales y la pantalla no muestra nada: una encuesta real nunca da eso.
- **Distinto por seccional.** Cada seccional recibe un sesgo propio y
  estable: una claramente peor, otra claramente mejor, el resto alrededor
  del promedio. Sin esa diferencia el filtro por seccional existe pero al
  usarlo muestra tres curvas iguales.
- **Repartidas en los días ya corridos** de la ventana, con más peso los
  primeros (es cuando llega el aviso). Si entraran todas hoy, el gráfico de
  ritmo sería un punto solo.

Las respuestas se escriben con `db.registrar_respuesta_encuesta`, la misma
función que corre cuando contesta una persona: el script no puede dejar la
base en un estado que la aplicación no sepa producir. Lo único que se toca
después es el DÍA de cada respuesta, que es lo que no se puede simular.
"""
import argparse
import random
import sys
from datetime import date, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlmodel import Session, select

import db
import encuestas
import fechas
from db import (Encuesta, EncuestaParticipante, Notificacion, NotificacionDestinatario,
                RespuestaEncuesta, Seccional, Sindicato, Trabajador)

# Pesos de una Pareto: el primero se lleva la mitad, el segundo la mitad de
# eso, y sigue cayendo. Se recorta a la cantidad de opciones que haya.
PARETO = [50, 25, 12, 6, 4, 3, 2, 1, 1, 1]

# Cuánto corre el "tono" de una seccional respecto del promedio. El orden lo
# fija el id, así que es estable entre corridas: la misma seccional siempre
# es la que está peor.
TONOS = [0.0, -1.0, 0.8, -0.4, 0.4, -0.8, 0.2]


def pesos(cantidad: int, tono: float = 0.0) -> list:
    """Pesos Pareto para `cantidad` opciones, corridos por el tono.

    Un tono positivo empuja el peso hacia las PRIMERAS opciones (que en una
    encuesta bien escrita son las mejores) y uno negativo hacia las últimas.
    Así una seccional descontenta no es ruido: es la misma pregunta con la
    respuesta corrida.
    """
    base = PARETO[:cantidad] or [1]
    if len(base) < cantidad:
        base = base + [1] * (cantidad - len(base))
    corridos = []
    for i, p in enumerate(base):
        # El primero sube con el tono y el último baja, proporcionalmente a
        # dónde está en la lista.
        lugar = 0 if cantidad == 1 else i / (cantidad - 1)
        corridos.append(max(1.0, p * (1 + tono * (0.5 - lugar))))
    return corridos


def _tono_de(seccional_id, orden: list) -> float:
    if seccional_id is None or seccional_id not in orden:
        return 0.0
    return TONOS[orden.index(seccional_id) % len(TONOS)]


def _respuesta(preguntas: list, tono: float, rnd) -> dict:
    """Una respuesta completa a esta encuesta, sea cual sea su estructura.

    Se arma a partir de las preguntas REALES: el script no sabe de antemano
    qué preguntó el sindicato, así que responde por tipo de dato.
    """
    salida = {}
    for p in preguntas:
        tipo = p["tipo_dato"]
        if tipo in encuestas.TIPOS_SIN_RESPUESTA:
            continue
        opciones = encuestas.opciones_de(p.get("opciones", ""))
        pid = str(p["id"])

        if tipo == "escala":
            minimo = p.get("escala_min") or encuestas.ESCALA_MIN_DEFAULT
            maximo = p.get("escala_max") or encuestas.ESCALA_MAX_DEFAULT
            # La escala también va sesgada: el promedio se corre con el tono
            # en vez de quedar clavado en el medio para todas las seccionales.
            centro = minimo + (maximo - minimo) * 0.62 + tono
            salida[pid] = max(minimo, min(maximo, round(rnd.gauss(centro, (maximo - minimo) / 4.5))))

        elif tipo in ("seleccion", "opcion_unica"):
            salida[pid] = rnd.choices(range(len(opciones)), weights=pesos(len(opciones), tono))[0]

        elif tipo == "ranking":
            # El ranking se responde ENTERO. La mayoría coincide en el
            # primer puesto (eso es lo que hace que un ranking signifique
            # algo) y el resto lo mezcla.
            orden = list(range(len(opciones)))
            if rnd.random() < 0.72:
                primero = rnd.choices(orden, weights=pesos(len(opciones), tono))[0]
                resto = [i for i in orden if i != primero]
                rnd.shuffle(resto)
                salida[pid] = [primero] + resto
            else:
                rnd.shuffle(orden)
                salida[pid] = orden

        elif tipo == "multiple":
            marcadas = _multiple(opciones, tono, rnd)
            if marcadas or p.get("obligatorio"):
                salida[pid] = marcadas or [rnd.choices(
                    range(len(opciones)), weights=pesos(len(opciones), tono))[0]]

        elif tipo == "booleano":
            salida[pid] = "si" if rnd.random() < 0.5 + tono / 6 else "no"

        elif tipo == "numero":
            salida[pid] = round(rnd.gauss(10 + tono, 3), 1)

        elif tipo == "fecha":
            salida[pid] = (fechas.hoy() - timedelta(days=rnd.randint(0, 900))).isoformat()

        elif tipo == "texto":
            # El texto libre lo contesta una minoría, salvo que sea
            # obligatorio: ahí lo contesta todo el mundo o no entra nada.
            if not p.get("obligatorio") and rnd.random() > 0.22:
                continue
            salida[pid] = rnd.choice([
                "Hace falta más personal en la línea de cajas.",
                "El aire acondicionado de la sucursal no anda.",
                "Estaría bueno que los cursos sean en horario de trabajo.",
                "La guardia de los sábados se reparte mal.",
                "Se nota la mejora en la obra social este año.",
                "Faltan sillas ergonómicas en el sector de atención.",
            ])
    return salida


def _multiple(opciones: list, tono: float, rnd) -> list:
    """Marcas de una pregunta múltiple, con Pareto y una opción excluyente.

    Si hay una opción tipo "ninguno", se comporta como corresponde: el que
    la marca no marca nada más. Sin eso, el gráfico muestra gente que no usó
    ningún servicio y además usó tres.
    """
    excluyente = next((i for i, o in enumerate(opciones)
                       if o.strip().lower() in ("ninguno", "ninguna", "ninguno de estos",
                                                "no uso ninguno", "nada")), None)
    if excluyente is not None and rnd.random() < 0.18:
        return [excluyente]
    candidatas = [i for i in range(len(opciones)) if i != excluyente]
    if not candidatas:
        return []
    w = pesos(len(opciones), tono)
    # Cuántas marca: depende de CUÁNTAS OPCIONES hay, y no es un detalle.
    # Una múltiple de tres opciones casi siempre es una escala de grados
    # ("totalmente / parcialmente / nada") aunque esté cargada como
    # múltiple, y marcar dos deja gente totalmente y nada representada a la
    # vez -- que en la pantalla se lee como un error del sistema. Una de
    # seis suele ser una lista de servicios, donde marcar varios es lo
    # normal. La regla es del largo de la lista, no del texto: adivinar por
    # las palabras fallaría con el primer sindicato que las escriba distinto.
    techo = 1 if len(opciones) <= 3 else min(3, len(opciones) // 2)
    cuantas = min(len(candidatas), max(1, min(techo, int(rnd.paretovariate(2.2)))))
    marcadas = []
    while len(marcadas) < cuantas:
        elegida = rnd.choices(candidatas, weights=[w[i] for i in candidatas])[0]
        if elegida not in marcadas:
            marcadas.append(elegida)
    return sorted(marcadas)


def _dia(desde: date, hoy: date, rnd) -> str:
    """Un día dentro de lo que YA CORRIÓ de la ventana, con más peso los
    primeros: es cuando llega el aviso."""
    corridos = max(0, (hoy - desde).days)
    if corridos == 0:
        return hoy.isoformat()
    tirada = rnd.random()
    if tirada < 0.55:
        dia = rnd.randint(0, min(3, corridos))
    elif tirada < 0.75:
        dia = corridos
    else:
        dia = rnd.randint(0, corridos)
    return (desde + timedelta(days=dia)).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sindicato", required=True, help='parte del nombre, ej: "La Bancaria"')
    ap.add_argument("--encuesta", type=int, default=0,
                    help="id; por defecto, la única publicada del sindicato")
    ap.add_argument("--respuestas", type=int, default=85,
                    help="TOTAL de personas que tienen que quedar con la encuesta respondida")
    ap.add_argument("--leidas", type=int, default=90,
                    help="porcentaje de los avisos de la encuesta que queda como leído")
    ap.add_argument("--semilla", type=int, default=2026)
    ap.add_argument("--si", action="store_true", help="escribir de verdad (si no, ensayo)")
    args = ap.parse_args()
    rnd = random.Random(args.semilla)

    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(
            Sindicato.nombre.ilike(f"%{args.sindicato}%"))).first()
        if not sind:
            print(f"✗ No encontré ningún sindicato que contenga «{args.sindicato}».")
            return 1
        sid = sind.id
        q = select(Encuesta).where(Encuesta.sindicato_id == sid, Encuesta.publicada == True)  # noqa: E712
        if args.encuesta:
            q = q.where(Encuesta.id == args.encuesta)
        publicadas = s.exec(q.order_by(Encuesta.id)).all()
        if not publicadas:
            print(f"✗ {sind.nombre} no tiene ninguna encuesta publicada.")
            return 1
        if len(publicadas) > 1:
            print("✗ Hay más de una encuesta publicada. Elegí con --encuesta:")
            for e in publicadas:
                print(f"    #{e.id}  «{e.titulo}»  ({e.modo}, {e.fecha_desde}→{e.fecha_hasta})")
            return 1
        enc = publicadas[0]

    e = db.encuesta_por_id(enc.id, sid)
    if e["estado"] != encuestas.ABIERTA:
        print(f"✗ «{e['titulo']}» está {e['estado']}: una encuesta que no acepta respuestas "
              f"no se puede llenar (y hace bien en no dejarse).")
        return 1

    with Session(db.engine) as s:
        padron = s.exec(select(EncuestaParticipante).where(
            EncuestaParticipante.encuesta_id == enc.id)).all()
        faltan = [p.cuil for p in padron if not p.respondio]
        ya = len(padron) - len(faltan)
        trabajadores = {t.cuil: t for t in s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sid,
            Trabajador.cuil.in_([p.cuil for p in padron]))).all()} if padron else {}
        nombres_sec = {x.id: x.nombre for x in s.exec(select(Seccional).where(
            Seccional.sindicato_id == sid)).all()}
        notifs = s.exec(select(Notificacion).where(Notificacion.encuesta_id == enc.id)).all()
        destinatarios = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id.in_([n.id for n in notifs]))
        ).all() if notifs else []

    objetivo = min(args.respuestas, len(padron))
    a_responder = max(0, objetivo - ya)
    sin_leer = [d for d in destinatarios if not d.leida_en]
    a_marcar = max(0, round(len(destinatarios) * args.leidas / 100)
                   - (len(destinatarios) - len(sin_leer)))

    # El tono de cada seccional se fija por id, así una corrida repetida no
    # cambia cuál es la seccional descontenta.
    orden_sec = sorted({t.seccional_id for t in trabajadores.values() if t.seccional_id})
    reparto = {}
    for cuil in faltan:
        t = trabajadores.get(cuil)
        reparto.setdefault(t.seccional_id if t else None, []).append(cuil)

    print(f"\n  Sindicato : {sind.nombre} (#{sid})")
    print(f"  Encuesta  : #{enc.id} «{e['titulo']}» · {e['modo']} · {e['estado']} · "
          f"{e['fecha_desde']} → {e['fecha_hasta']}")
    print(f"  Preguntas : {len(e['preguntas'])} "
          f"({', '.join(p['tipo_dato'] for p in e['preguntas'])})")
    print(f"  Padrón    : {len(padron)} · ya respondieron {ya} · faltan {len(faltan)}")
    print(f"  Van a responder {a_responder} más, para llegar a {objetivo}.")
    print(f"  Avisos    : {len(destinatarios)} destinatarios · "
          f"{len(destinatarios) - len(sin_leer)} leídos · se marcan {a_marcar} más "
          f"({args.leidas}%)")
    print("  Por seccional (los que faltan):")
    for sec, gente in sorted(reparto.items(), key=lambda x: -len(x[1])):
        tono = _tono_de(sec, orden_sec)
        print(f"    {nombres_sec.get(sec, 'sin seccional'):<20} {len(gente):>4}  "
              f"tono {tono:+.1f}" + ("   ← la más disconforme" if tono <= -0.9 else
                                     "   ← la más conforme" if tono >= 0.8 else ""))
    if not args.si:
        print("\n  ENSAYO: no se escribió nada. Repetí con --si para hacerlo.\n")
        return 0

    # --- Escribir -------------------------------------------------------
    elegidos = []
    for sec, gente in reparto.items():
        elegidos += [(c, _tono_de(sec, orden_sec)) for c in gente]
    rnd.shuffle(elegidos)
    elegidos = elegidos[:a_responder]

    hechas, fallidas = 0, {}
    for cuil, tono in elegidos:
        r = db.registrar_respuesta_encuesta(
            enc.id, cuil, sid, _respuesta(e["preguntas"], tono, rnd))
        if r["ok"]:
            hechas += 1
        else:
            fallidas[r["error"]] = fallidas.get(r["error"], 0) + 1

    # El día: lo único que no se puede simular respondiendo, porque la urna
    # lo pone en hoy. Sin esto el gráfico de ritmo es un punto solo.
    desde = date.fromisoformat(e["fecha_desde"])
    hoy = fechas.hoy()
    movidas = 0
    with Session(db.engine) as s:
        for fila in s.exec(select(RespuestaEncuesta).where(
                RespuestaEncuesta.encuesta_id == enc.id,
                RespuestaEncuesta.dia == hoy.isoformat())).all():
            fila.dia = _dia(desde, hoy, rnd)
            s.add(fila)
            movidas += 1
        s.commit()

    leidas = 0
    for d in sin_leer[:a_marcar]:
        if db.marcar_notificacion_leida(d.notificacion_id, d.cuil):
            leidas += 1

    print(f"\n✓ {hechas} respuestas cargadas"
          + (f" ({len(elegidos) - hechas} rechazadas)" if hechas < len(elegidos) else ""))
    for motivo, n in fallidas.items():
        print(f"    {n} × {motivo}")
    print(f"✓ {leidas} avisos marcados como leídos")
    print(f"✓ {movidas} respuestas repartidas entre el {e['fecha_desde']} y hoy")

    d = db.encuestas_del_sindicato(sid)
    fila = next(x for x in d if x["id"] == enc.id)
    print(f"\n  Queda: {fila['respuestas']} de {fila['cantidad_destinatarios']} respondieron.")
    print(f"  Resultados: /admin/encuesta/{enc.id}/resultados\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
