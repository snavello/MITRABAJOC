---
id: LEY-01
eje: LEY
titulo: Debe existir un mapa de datos personales y sensibles, con su base legal
tipo: manual
herramienta: revisión de modelos (db.py) + decisión de SDN
entorno: pruebas
destructivo: no
owasp: -
asvs: V8.3.1
cwe: CWE-359
activo: V3, V1, V7
---

## Objetivo

Clasificar qué datos personales y sensibles (Ley 25.326) guarda el sistema,
dónde, por cuánto tiempo y con qué base legal. Sin este mapa no se puede
decidir qué se loguea (DAT-03) ni qué retención aplicar (R5).

## Cómo se corre

1. Recorrer `db.py`: por cada tabla, marcar datos personales y los
   **sensibles** (afiliación sindical, sobre todo).
2. Anotar responsable (sindicato) y encargado (Colm3na) por dato — R4.
3. Listar lo que falta: disclaimer por sindicato (R6), retención (R5),
   contrato de encargado, procedimiento de acceso/supresión del afiliado.

## Resultado esperado

Sale el mapa de datos (documento). Los faltantes (R5, R6, contrato) son
hallazgos del eje LEY con dueño SDN.

## Notas

`owasp: -` (OWASP Top 10 no cubre cumplimiento). Base: Ley 25.326, la
afiliación es dato sensible por art. 2.
