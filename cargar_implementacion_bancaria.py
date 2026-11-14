"""Siembra el plan operativo de La Bancaria en la Mesa de implementación (I7).

Crea el proyecto «La Bancaria» (asociado al sindicato La Bancaria si existe en
la base) con sus seis fases y los 48 hitos de `data/implementacion/hitos_bancaria.json`
(8 por fase, salen del bloque «Hitos propuestos» de docs/implementacion/diferencias.md).

Idempotente: si el proyecto ya existe lo reutiliza, y si ya tiene hitos no los
toca. Sin `--si` solo muestra qué haría.

    python cargar_implementacion_bancaria.py          # ensayo
    python cargar_implementacion_bancaria.py --si     # escribe

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


def main(escribir: bool) -> int:
    fases = implementacion.cargar_hitos_semilla()
    total = sum(len(h) for _, h in fases)
    with db.get_session() as s:
        sind = _sindicato_bancaria(s)
        proy = s.exec(select(db.ImplProyecto).where(db.ImplProyecto.nombre == NOMBRE_PROYECTO)
                      .order_by(db.ImplProyecto.id)).first()
        print(f"Sindicato asociado: {sind.nombre + f' (id {sind.id})' if sind else 'ninguno (el proyecto nace sin sindicato)'}")
        print(f"Proyecto «{NOMBRE_PROYECTO}»: {'ya existe (id %s)' % proy.id if proy else 'se crearía'}")
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
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--si", action="store_true", help="escribe en la base (sin esto solo muestra)")
    raise SystemExit(main(ap.parse_args().si))
