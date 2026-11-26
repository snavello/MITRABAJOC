"""Arma el tablero de implementación de UN sindicato de Colm3na: corre cada
control, informa las condiciones (módulos contratados) y llama al motor.

No escribe nada. Recibe una sesión abierta (regla del proyecto: una sesión
por request) y devuelve `(tareas, tablero)`, donde `tablero` es lo que
resuelve `xsii.motor.estados.resolver`.
"""

from __future__ import annotations

from sqlmodel import select

import modulos
from db import Sindicato
from xsii.motor import estados
from xsii.motor.estados import Control

from . import controles
from .catalogo import TAREAS


def condiciones(s, sindicato_id: int) -> dict:
    """{módulo: bool}: una condición por cada módulo del catálogo de la app.
    Un `aplica_si` del catálogo es siempre el nombre de un módulo."""
    habilitados = s.exec(select(Sindicato.modulos_habilitados).where(
        Sindicato.id == sindicato_id)).first()
    # Es JSON: puede traer cualquier cosa. Se toman solo los textos que son
    # módulos reales; lo demás se ignora sin tumbar el tablero.
    if not isinstance(habilitados, (list, tuple)):
        habilitados = []
    habilitados = {m for m in habilitados if isinstance(m, str) and m in modulos.MODULOS}
    return {m: m in habilitados for m in modulos.MODULOS}


def correr_controles(s, sindicato_id: int) -> dict:
    """{codigo: Control}. Un control que falla no tumba el tablero: queda
    como incompleta con el motivo (y el error se ve, no se traga)."""
    salida = {}
    for t in TAREAS:
        funcion = getattr(controles, t.control)
        try:
            salida[t.codigo] = funcion(s, sindicato_id)
        except Exception as e:      # noqa: BLE001 - un control no tira el resto
            s.rollback()
            salida[t.codigo] = Control(
                "incompleta", "No se pudo calcular este control.",
                faltan=[f"Error al calcular: {type(e).__name__}"])
    return salida


def armar(s, sindicato_id: int, decisiones: dict | None = None,
          insumos: dict | None = None, ensayos_abiertos=None):
    """`(tareas, tablero)` del sindicato. `decisiones` {codigo: {tipo, quien,
    cuando, motivo}} e `insumos` {clave: recibido} llegan de afuera (en el
    bloque 1, de las tablas de registro); sin ellos, ninguna tarea está
    esperando un dato ni dada por completada a mano."""
    # La ficha del sindicato se lee una vez para todos los controles.
    s.info["xsii_sindicato"] = (sindicato_id, controles._leer_sindicato(s, sindicato_id))
    try:
        controles_calculados = correr_controles(s, sindicato_id)
    finally:
        s.info.pop("xsii_sindicato", None)
    hechos = {
        "controles": controles_calculados,
        "aplica": condiciones(s, sindicato_id),
        "insumos": insumos or {},
        "decisiones": decisiones or {},
        "ensayos_abiertos": set(ensayos_abiertos or ()),
    }
    return list(TAREAS), estados.resolver(TAREAS, hechos)
