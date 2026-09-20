---
id: DIS-02
eje: DIS
titulo: El agotamiento del pool o de las consultas debe degradar con 503, no colgar
tipo: dinamico
herramienta: k6 (carga/k6) + revisión
entorno: pruebas
destructivo: si
owasp: A04:2021
asvs: V12.1.1
cwe: CWE-400
activo: V4
---

## Objetivo

Confirmar que los techos del engine y el cupo del panel (ya implementados,
`CLAUDE.md` punto 24) siguen convirtiendo la saturación en 503 con
`Retry-After`, no en cuelgue. Es el control que ya se corrigió; acá se
verifica que no haya regresado.

## Cómo se corre

1. Correr `carga/k6/test3_panel.js` contra Pruebas (ya dio APROBADO el
   2026-09-19).
2. Confirmar 0 respuestas 500 y que los 503 traen `Retry-After`.
3. Revisar que `/detalle/*` y el asistente (fuera del cupo) no sean una vía
   de agotar el pool.

## Resultado esperado

`paso` si se mantiene el APROBADO. Es línea de base: si algún cambio lo
rompe, hallazgo.

## Notas

`destructivo: si`: tormenta de carga. Solo Pruebas. Subir el plan de Render
para la prueba, como prevé el alcance.
