"""Qué es una tarea de implementación y cómo se valida un catálogo.

Un catálogo es una lista de `Tarea` declarativas. El motor no sabe de qué
sistema son: solo exige que el grafo sea coherente (códigos únicos,
dependencias que existen, sin ciclos, toda tarea con su control). Es lo que
hace que «qué frena a X» o «qué destraba X» tengan siempre respuesta.
"""

from __future__ import annotations

from dataclasses import dataclass

# asistida: la IA prepara y carga (con ensayo y confirmación).
# herramienta / aplicacion: se hace en una pantalla que ya existe; XSII lleva
#   hasta ahí y controla el resultado.
# manual: ocurre fuera del sistema (X2). automatica: la hace el sistema solo.
MODOS = ("asistida", "herramienta", "aplicacion", "manual", "automatica")


@dataclass(frozen=True)
class Tarea:
    """Una tarea del catálogo.

    `necesita` son dependencias DURAS (sin ellas no se puede hacer);
    `mejora_con` son BLANDAS (conviene tenerlas, pero no frenan: avisan).
    `insumos` son claves de datos que entrega el cliente. `aplica_si` es la
    clave de una condición que informa el proyecto (p. ej. un módulo
    contratado); sin ella, la tarea aplica siempre. `control` es el nombre de
    la función que dice si la tarea está hecha: el estado se CALCULA, no se
    declara (principio 1 del plan).
    """
    codigo: str
    nombre: str
    grupo: str
    modo: str
    necesita: tuple = ()
    mejora_con: tuple = ()
    insumos: tuple = ()
    aplica_si: str | None = None
    donde: str | None = None
    control: str = ""
    acciones: tuple = ()
    descripcion: str = ""


def _ciclo(aristas: dict[str, tuple]) -> list[str] | None:
    """Un ciclo del grafo `{nodo: (destinos...)}` como lista de nodos, o None.
    Recorrido iterativo: un catálogo mal armado no debe romper la pila."""
    BLANCO, GRIS, NEGRO = 0, 1, 2
    color = {n: BLANCO for n in aristas}
    for inicio in aristas:
        if color[inicio] != BLANCO:
            continue
        pila = [(inicio, iter(aristas[inicio]))]
        camino = [inicio]
        color[inicio] = GRIS
        while pila:
            nodo, it = pila[-1]
            for sig in it:
                if sig not in color:
                    continue            # dependencia inexistente: la informa otro chequeo
                if color[sig] == GRIS:
                    return camino[camino.index(sig):] + [sig]
                if color[sig] == BLANCO:
                    color[sig] = GRIS
                    camino.append(sig)
                    pila.append((sig, iter(aristas[sig])))
                    break
            else:
                color[nodo] = NEGRO
                camino.pop()
                pila.pop()
    return None


def validar(tareas, grupos) -> list[str]:
    """Los errores del catálogo, en castellano. Lista vacía = es válido.

    Los ciclos de dependencias duras y los de blandas se buscan por
    separado: un ciclo de duras haría imposible resolver cualquier tarea de
    la rueda, y uno de blandas dejaría avisos que se piden unos a otros.
    """
    errores: list[str] = []
    tareas = list(tareas)
    grupos = tuple(grupos)
    vistos: set[str] = set()
    for t in tareas:
        if not t.codigo:
            errores.append(f"Hay una tarea sin código ({t.nombre!r}).")
            continue
        if t.codigo in vistos:
            errores.append(f"{t.codigo}: el código está repetido.")
        vistos.add(t.codigo)
    for t in tareas:
        if t.modo not in MODOS:
            errores.append(f"{t.codigo}: modo inválido {t.modo!r} (válidos: {', '.join(MODOS)}).")
        if t.grupo not in grupos:
            errores.append(f"{t.codigo}: grupo inválido {t.grupo!r}.")
        if not t.control:
            errores.append(f"{t.codigo}: la tarea no tiene control.")
        for dep in t.necesita:
            if dep not in vistos:
                errores.append(f"{t.codigo}: necesita {dep}, que no existe.")
            elif dep == t.codigo:
                errores.append(f"{t.codigo}: se necesita a sí misma.")
        for dep in t.mejora_con:
            if dep not in vistos:
                errores.append(f"{t.codigo}: mejora con {dep}, que no existe.")
            elif dep == t.codigo:
                errores.append(f"{t.codigo}: mejora con sí misma.")
        for dep in set(t.necesita) & set(t.mejora_con):
            errores.append(f"{t.codigo}: {dep} está a la vez en necesita y en mejora_con.")
    duras = {t.codigo: tuple(t.necesita) for t in tareas if t.codigo}
    blandas = {t.codigo: tuple(t.mejora_con) for t in tareas if t.codigo}
    ciclo = _ciclo(duras)
    if ciclo:
        errores.append("Ciclo de dependencias duras: " + " → ".join(ciclo) + ".")
    ciclo = _ciclo(blandas)
    if ciclo:
        errores.append("Ciclo de dependencias blandas: " + " → ".join(ciclo) + ".")
    return errores
