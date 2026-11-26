"""Preguntas sobre el tablero: qué hacer ahora, qué frena, qué destraba y
qué falta para llegar a una meta. Puro: recibe el catálogo y el tablero que
devolvió `estados.resolver`.

Solo las dependencias DURAS cuentan acá; las blandas son avisos.
"""

from __future__ import annotations



def _por_codigo(tareas) -> dict:
    return {t.codigo: t for t in tareas}


def _dependientes(tareas) -> dict[str, list[str]]:
    """{codigo: [tareas que lo necesitan]}, en orden de catálogo."""
    inversa: dict[str, list[str]] = {t.codigo: [] for t in tareas}
    for t in tareas:
        for dep in t.necesita:
            if dep in inversa:
                inversa[dep].append(t.codigo)
    return inversa


def _sin_resolver(tablero, codigo) -> bool:
    return not tablero[codigo].resuelta


def resumen(tablero) -> dict:
    """Conteos por estado y avance. La barra cuenta todas las tareas que
    aplican (X14): `porcentaje` = hechas sobre las que aplican."""
    por_estado = {e: 0 for e in ("hecha", "lista", "en_curso", "esperando", "bloqueada", "no_aplica")}
    a_mano = obs = pospuestas = por_confirmar = 0
    for e in tablero.values():
        por_estado[e.estado] += 1
        por_confirmar += e.falta_confirmar
        a_mano += e.a_mano
        obs += e.con_observaciones
        pospuestas += e.pospuesta
    total = len(tablero)
    aplican = total - por_estado["no_aplica"]
    resueltas = por_estado["hecha"]
    return {
        "total": total, "aplican": aplican, "resueltas": resueltas,
        # Hacia abajo: un 100 % tiene que querer decir que no queda nada.
        "porcentaje": (100 * resueltas) // aplican if aplican else 0,
        "por_confirmar": por_confirmar,
        "por_estado": por_estado, "a_mano": a_mano,
        "con_observaciones": obs, "pospuestas": pospuestas,
    }


def _exigir_codigo(tareas, codigo) -> None:
    """Las tres consultas por código se portan igual ante uno desconocido."""
    if codigo not in {t.codigo for t in tareas}:
        raise ValueError(f"No existe la tarea {codigo!r} en el catálogo.")


def que_destraba(tareas, tablero, codigo) -> dict:
    """Lo que depende de `codigo` y todavía no está resuelto: {"directo":
    [...], "transitivo": [...]}. El transitivo incluye al directo y sigue
    solo por tareas sin resolver (una ya hecha no espera a nadie)."""
    _exigir_codigo(tareas, codigo)
    inversa = _dependientes(tareas)
    directo = [c for c in inversa.get(codigo, []) if _sin_resolver(tablero, c)]
    visto: set[str] = set()
    pila = list(directo)
    while pila:
        c = pila.pop()
        if c in visto:
            continue
        visto.add(c)
        pila.extend(x for x in inversa[c] if _sin_resolver(tablero, x) and x not in visto)
    orden = [t.codigo for t in tareas]
    return {"directo": directo, "transitivo": [c for c in orden if c in visto]}


def que_frena(tareas, tablero, codigo) -> list[str]:
    """La cadena transitiva de lo NO resuelto de lo que `codigo` necesita,
    de la raíz a lo más cercano (el orden en que habría que hacerlo)."""
    return camino_hasta(tareas, tablero, codigo)


def camino_hasta(tareas, tablero, codigo) -> list[str]:
    """Las tareas no resueltas necesarias para poder hacer `codigo`, en orden
    topológico (las que no dependen de nadie primero; empate: orden del
    catálogo). No incluye a `codigo`. Una dependencia ya resuelta corta la
    rama: lo que hay detrás ya no hace falta."""
    _exigir_codigo(tareas, codigo)
    por_codigo = _por_codigo(tareas)
    necesarias: set[str] = set()
    pila = [codigo]
    while pila:
        c = pila.pop()
        for dep in por_codigo[c].necesita:
            if dep in por_codigo and _sin_resolver(tablero, dep) and dep not in necesarias:
                necesarias.add(dep)
                pila.append(dep)
    # Kahn con el orden del catálogo como desempate.
    orden = [t.codigo for t in tareas if t.codigo in necesarias]
    pendientes = {c: {d for d in por_codigo[c].necesita if d in necesarias} for c in orden}
    salida: list[str] = []
    while pendientes:
        listo = next((c for c in orden if c in pendientes and not pendientes[c]), None)
        if listo is None:       # ciclo: el catálogo no pasó `validar`
            raise ValueError("El catálogo tiene un ciclo de dependencias duras.")
        salida.append(listo)
        del pendientes[listo]
        for fal in pendientes.values():
            fal.discard(listo)
    return salida


def _candidatas(tareas, tablero):
    """Las que se pueden hacer ya, ordenadas: en curso primero y después las
    `lista` no pospuestas por cuántas tareas destraban (transitivo); el
    empate lo resuelve el orden del catálogo (sort estable)."""
    en_curso = [t.codigo for t in tareas
                if tablero[t.codigo].estado == "en_curso" and not tablero[t.codigo].pospuesta]
    listas = [t.codigo for t in tareas
              if tablero[t.codigo].estado == "lista" and not tablero[t.codigo].pospuesta]
    listas.sort(key=lambda c: -len(que_destraba(tareas, tablero, c)["transitivo"]))
    return en_curso + listas


def recomendada(tareas, tablero) -> str | None:
    """El próximo paso (X9): la tarea en curso o, si no hay, la que más
    tareas destraba. None si no queda nada para hacer ya."""
    c = _candidatas(tareas, tablero)
    return c[0] if c else None


def alternativas(tareas, tablero, cuantas: int = 3) -> list[str]:
    """Otras tareas que también se pueden hacer ahora, sin la recomendada."""
    return _candidatas(tareas, tablero)[1:1 + cuantas]


def _control_json(c) -> dict | None:
    if c is None:
        return None
    return {"estado": c.estado, "resumen": c.resumen, "cifras": dict(c.cifras),
            "faltan": list(c.faltan), "en_curso": c.en_curso}


def a_json(tareas, tablero) -> dict:
    """Todo lo que una pantalla o una API necesita, listo para serializar."""
    items = []
    for t in tareas:
        e = tablero[t.codigo]
        items.append({
            "codigo": t.codigo, "nombre": t.nombre, "grupo": t.grupo, "modo": t.modo,
            "necesita": list(t.necesita), "mejora_con": list(t.mejora_con),
            "insumos": list(t.insumos), "aplica_si": t.aplica_si, "donde": t.donde,
            "descripcion": t.descripcion,
            "estado": e.estado, "con_observaciones": e.con_observaciones,
            "a_mano": e.a_mano, "pospuesta": e.pospuesta,
            "confirmacion": t.confirmacion, "falta_confirmar": e.falta_confirmar,
            "no_aplica_por": e.no_aplica_por,
            "frenada_por": list(e.frenada_por),
            "insumos_faltantes": list(e.insumos_faltantes),
            "avisos": list(e.avisos),
            "control": _control_json(e.control),
            "decision": dict(e.decision) if e.decision else None,
        })
    return {"resumen": resumen(tablero), "recomendada": recomendada(tareas, tablero),
            "alternativas": alternativas(tareas, tablero), "tareas": items}
