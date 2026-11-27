"""Tareas asistidas de XSII: «Cargar desde la planilla» (docs/xsii/API.md,
«Bloque 3»). Un módulo por tarea, registrado acá; el protocolo de los cuatro
momentos (describir, ensayar, cargar, control) es el mismo para todos:

- `describir() -> dict`
- `ensayar(s, sid, contenido, opciones) -> dict` (lee la base, no escribe)
- `cargar(s, sid, contenido, opciones, dejar_afuera) -> dict` (sin commit)

El bloque 4 (Padrón, Conceptos) suma módulos a `ASISTIDAS`, no rutas.
"""

from . import seccionales
from .base import ErrorAsistida, huella

ASISTIDAS = {"EST-01": seccionales}

__all__ = ["ASISTIDAS", "ErrorAsistida", "huella"]
