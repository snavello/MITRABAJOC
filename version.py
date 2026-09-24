"""Versión de cada app (Trabajador/Admin/Plataforma), mostrada en el
"Acerca de" discreto de cada pantalla de inicio. Se actualiza en cada deploy
siguiendo la regla 3 de FLUJO.md: solo arreglos, +1 al patch; con
funcionalidad nueva, +1 al minor y el patch vuelve a 01. Solo sube la app que
se tocó. Ante la duda de si un cambio es "funcionalidad nueva", lo decide Sd.
"""

VERSION_TRABAJADOR = "0.41.04"
VERSION_ADMIN = "0.45.01"
VERSION_PLATAFORMA = "0.37.01"

FECHA_VERSION = "2026-09-24 12:10"
