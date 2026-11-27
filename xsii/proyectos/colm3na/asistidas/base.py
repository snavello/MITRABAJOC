"""Lo común de las tareas asistidas (docs/xsii/API.md, «Bloque 3»)."""

from __future__ import annotations

import hashlib
import json


class ErrorAsistida(Exception):
    """Un rechazo de una tarea asistida: `estado` es el código HTTP (400 el
    archivo no sirve, 409 conflicto) y `mensaje` la frase para la persona."""

    def __init__(self, estado: int, mensaje: str):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


def huella(contenido: bytes, opciones: dict) -> str:
    """SHA-256 del contenido más las opciones ya normalizadas: lo que el
    ensayo vio es EXACTAMENTE lo que la carga recibe."""
    h = hashlib.sha256()
    h.update(contenido or b"")
    h.update(b"\x00")
    h.update(json.dumps(opciones, sort_keys=True, ensure_ascii=True).encode("ascii"))
    return h.hexdigest()
