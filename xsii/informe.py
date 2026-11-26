"""El tablero de implementación de un sindicato, por consola.

    python -m xsii.informe                       # lista los sindicatos
    python -m xsii.informe "Nombre del sindicato" # imprime el tablero

Es el único «frontend» del bloque 0 (no hay pantalla todavía). Solo lee.
"""

from __future__ import annotations

import sys

from sqlmodel import select

ROTULOS = {
    "hecha": "HECHA", "lista": "SE PUEDE HACER", "en_curso": "EN CURSO",
    "esperando": "ESPERANDO UN DATO", "bloqueada": "BLOQUEADA", "no_aplica": "NO APLICA",
}


def _linea(t, e) -> str:
    marca = ROTULOS[e.estado]
    if e.estado == "hecha":
        if e.a_mano:
            marca += " (a mano)"
        elif e.con_observaciones:
            marca += " (con observaciones)"
    if e.pospuesta:
        marca += " (pospuesta)"
    if e.falta_confirmar:
        marca += " (falta confirmar)"
    c = e.control
    if e.estado == "bloqueada":
        detalle = "frenada por " + ", ".join(e.frenada_por)
    elif e.estado == "esperando":
        detalle = "falta: " + ", ".join(e.insumos_faltantes)
    elif e.estado == "no_aplica":
        d = e.decision or {}
        if e.no_aplica_por == "condicion":
            detalle = f"módulo {t.aplica_si} apagado"
        else:
            detalle = (f"declarada no aplica por {d.get('quien') or '?'}"
                       + (f": {d['motivo']}" if d.get("motivo") else ""))
    elif e.falta_confirmar:
        detalle = "confirmar: " + (e.confirmacion or "")
    else:
        detalle = c.resumen if c else ""
    return f"  {t.codigo}  {t.nombre:<42} {marca:<28} {detalle}"


def texto(nombre: str, tareas, tablero) -> str:
    from xsii.motor import consulta
    from xsii.proyectos.colm3na.catalogo import GRUPOS
    r = consulta.resumen(tablero)
    por = r["por_estado"]
    out = [f"XSII · {nombre}", "=" * 60,
           f"Avance: {r['resueltas']} de {r['aplican']} tareas que aplican ({r['porcentaje']} %)",
           "  " + " · ".join(f"{ROTULOS[k].lower()}: {v}" for k, v in por.items() if v), ""]
    rec = consulta.recomendada(tareas, tablero)
    if rec:
        t = next(x for x in tareas if x.codigo == rec)
        destraba = consulta.que_destraba(tareas, tablero, rec)["transitivo"]
        out.append(f"Siguiente paso recomendado: {rec} · {t.nombre}"
                   + (f" (destraba {len(destraba)})" if destraba else ""))
        alt = consulta.alternativas(tareas, tablero)
        if alt:
            out.append("También se puede hacer: " + ", ".join(alt))
    else:
        out.append("No queda ninguna tarea para hacer ahora.")
    for grupo in GRUPOS:
        del_grupo = [t for t in tareas if t.grupo == grupo]
        if not del_grupo:
            continue
        out += ["", grupo.upper()]
        out += [_linea(t, tablero[t.codigo]) for t in del_grupo]
        for t in del_grupo:
            e = tablero[t.codigo]
            if e.control and e.control.faltan and not e.resuelta:
                out += [f"        {t.codigo} falta: {f}" for f in e.control.faltan[:3]]
    return "\n".join(out)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    import db
    from db import Sindicato
    from xsii.proyectos.colm3na import tablero as tablero_mod

    with db.get_session() as s:
        sindicatos = s.exec(select(Sindicato).order_by(Sindicato.id)).all()
        if not argv:
            print("Sindicatos:")
            for sind in sindicatos:
                print(f"  {sind.id:>4}  {sind.nombre}")
            print('\nUso: python -m xsii.informe "Nombre del sindicato"')
            return 0
        buscado = " ".join(argv).strip().lower()
        coinciden = [x for x in sindicatos if buscado == x.nombre.lower() or buscado == str(x.id)]
        if not coinciden:
            coinciden = [x for x in sindicatos if buscado in x.nombre.lower()]
        if len(coinciden) != 1:
            print("No encontré un único sindicato para " + repr(" ".join(argv)) + ".")
            for sind in coinciden or sindicatos:
                print(f"  {sind.id:>4}  {sind.nombre}")
            return 1
        sind = coinciden[0]
        tareas, tablero = tablero_mod.armar(s, sind.id)
        print(texto(sind.nombre, tareas, tablero))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
