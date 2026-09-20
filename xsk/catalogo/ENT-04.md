---
id: ENT-04
eje: ENT
titulo: Las entradas no deben permitir inyección (SQL, plantilla, redirección)
tipo: estatico
herramienta: bandit + semgrep + revisión
entorno: pruebas
destructivo: no
owasp: A03:2021
asvs: V5.3.4
cwe: CWE-89
activo: V1, V2, V3
---

## Objetivo

Confirmar lo que el mapa vio bien (SQL parametrizado, autoescape de Jinja) y
buscar lo que un escáner encuentre: `text(f...)`, `.format` en SQL, `|safe`
nuevos, redirecciones abiertas.

## Cómo se corre

1. `bandit -r .` (excluyendo tests) y revisar los hallazgos reales.
2. Revisar el único `text(f...)` (`dashboard.py:1108`) y los `|safe`.
3. Confirmar `_siguiente_seguro` (redirección solo a `/recursos/`).

## Resultado esperado

`paso` si no hay inyección real. El mapa ya lo dio como bien resuelto; este
test lo confirma con herramienta y queda de línea de base.

## Notas

Iteración 2. bandit ya está instalado.
