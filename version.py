"""Versión de cada app (Trabajador/Admin/Plataforma), mostrada en el
"Acerca de" discreto de cada pantalla de inicio. Se actualiza en cada deploy
siguiendo la regla 3 de FLUJO.md: solo arreglos, +1 al patch; con
funcionalidad nueva, +1 al minor y el patch vuelve a 01. Solo sube la app que
se tocó. Ante la duda de si un cambio es "funcionalidad nueva", lo decide Sd.
"""

VERSION_TRABAJADOR = "0.39.03"
VERSION_ADMIN = "0.42.04"
VERSION_PLATAFORMA = "0.35.04"

FECHA_VERSION = "2026-09-21 16:30"
