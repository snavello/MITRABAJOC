"""Siembra el plan operativo de La Bancaria en la Mesa de implementación (I7).

Crea el proyecto «La Bancaria» (asociado al sindicato La Bancaria si existe en
la base) con sus seis fases y los hitos de `data/implementacion/hitos_bancaria.json`
(8 por fase, salen del bloque «Hitos propuestos» de docs/implementacion/diferencias.md).

Idempotente: si el proyecto ya existe lo reutiliza, y si ya tiene hitos no los
toca. Sin `--si` solo muestra qué haría.

    python cargar_implementacion_bancaria.py          # ensayo
    python cargar_implementacion_bancaria.py --si     # escribe
    python cargar_implementacion_bancaria.py --fechas [--si]
        # pone las fechas TENTATIVAS de la semilla en el proyecto ya existente,
        # solo en las fases que todavía no tienen fecha (no pisa lo que el
        # equipo ajustó) y sin tocar los hitos. Sin --si, ensayo.

Mismo efecto, desde la pantalla del equipo: POST
/api/entornos/implementacion/proyectos/{id}/hitos-semilla.
"""
import argparse

from sqlmodel import select

import db
import implementacion

NOMBRE_PROYECTO = "La Bancaria"
ACTOR = implementacion.Actor(implementacion.EQUIPO, 0, "Semilla")


def _sindicato_bancaria(s):
    return s.exec(select(db.Sindicato).where(db.Sindicato.nombre.ilike("%bancaria%"))
                  .order_by(db.Sindicato.id)).first()


def _fechas(s, proy, escribir: bool) -> int:
    """Pone las fechas de la semilla en las fases del proyecto que no tienen."""
    semilla = implementacion.fechas_semilla()
    etapas = {e.nombre.strip().lower(): e for e in db.impl_etapas(s, proy.id)}
    a_poner, saltadas = [], []
    for nombre, desde, hasta in semilla:
        e = etapas.get(nombre.strip().lower())
        if e is None:
            saltadas.append(f"{nombre}: el proyecto no tiene esa fase")
        elif e.fecha_desde or e.fecha_hasta:
            saltadas.append(f"{nombre}: ya tiene fechas ({e.fecha_desde} a {e.fecha_hasta}), no se pisan")
        else:
            a_poner.append({"id": e.id, "desde": desde, "hasta": hasta, "nombre": nombre})
    for x in a_poner:
        print(f"  {x['nombre']}: {x['desde']} a {x['hasta']}")
    for t in saltadas:
        print(f"  (salteada) {t}")
    if not a_poner:
        print("No hay fechas para poner.")
        return 0
    if not escribir:
        print(f"Ensayo: se pondrían fechas en {len(a_poner)} fases. Corré con --si para escribir.")
        return 0
    db.impl_fechar_plan(s, proy.id, ACTOR, [{k: x[k] for k in ("id", "desde", "hasta")} for x in a_poner])
    print(f"Listo: fechas tentativas en {len(a_poner)} fases.")
    return 0


def main(escribir: bool, solo_fechas: bool = False) -> int:
    fases = implementacion.cargar_hitos_semilla()
    total = sum(len(h) for _, h in fases)
    with db.get_session() as s:
        sind = _sindicato_bancaria(s)
        proy = s.exec(select(db.ImplProyecto).where(db.ImplProyecto.nombre == NOMBRE_PROYECTO)
                      .order_by(db.ImplProyecto.id)).first()
        print(f"Sindicato asociado: {sind.nombre + f' (id {sind.id})' if sind else 'ninguno (el proyecto nace sin sindicato)'}")
        print(f"Proyecto «{NOMBRE_PROYECTO}»: {'ya existe (id %s)' % proy.id if proy else 'se crearía'}")
        if solo_fechas:
            if not proy:
                print("El proyecto no existe: corré primero sin --fechas.")
                return 1
            return _fechas(s, proy, escribir)
        con_hitos = bool(proy) and bool(db.impl_avance(s, proy.id)) and any(
            e["total"] for e in db.impl_avance(s, proy.id))
        for nombre, hitos in fases:
            print(f"  {nombre}: {len(hitos)} hitos")
        if con_hitos:
            print("El proyecto ya tiene hitos: no se toca nada.")
            return 0
        if not escribir:
            print(f"Ensayo: se cargarían {total} hitos. Corré con --si para escribir.")
            return 0
        if not proy:
            proy = db.impl_crear_proyecto(s, NOMBRE_PROYECTO, ACTOR, sindicato_id=sind.id if sind else None)
        n = db.impl_cargar_hitos_semilla(s, proy.id, ACTOR, fases)
        print(f"Listo: proyecto {proy.id}, {n} hitos cargados.")
        _fechas(s, proy, True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--si", action="store_true", help="escribe en la base (sin esto solo muestra)")
    ap.add_argument("--fechas", action="store_true",
                    help="solo pone las fechas tentativas en las fases sin fecha del proyecto existente")
    a = ap.parse_args()
    raise SystemExit(main(a.si, a.fechas))
