---
id: DAT-03
eje: DAT
titulo: Los datos personales no deben terminar en logs sin querer
tipo: revision
herramienta: security-review + grep (Code)
entorno: pruebas
destructivo: no
owasp: A09:2021
asvs: V7.1.1
cwe: CWE-532
activo: V3, V1
---

## Objetivo

Que el stdout de Render y Sentry no acumulen datos sensibles. Cubre O16:
`traceback.print_exc()` sin scrubbing, y el CUIL en el path de
`/perfil-foto/{cuil}` que Sentry no recorta (`_sin_query` no toca el path).

## Cómo se corre

1. Revisar `main.py:195` (`traceback.print_exc`) y los `print` del handler.
2. Revisar `sentry_config.limpiar_evento`: confirmar el allow-list y que el
   path con CUIL sí puede salir.
3. Listar qué rutas llevan un dato personal en el path.

## Resultado esperado

`paso` si nada sensible llega a stdout y el path se recorta antes de Sentry.
El CUIL en el path es hallazgo (decisión documentada de SDN: puede quedar,
pero se registra para el eje LEY).

## Notas

Ligado a LEY-01 (clasificación): qué es "sensible" sale de ahí.
