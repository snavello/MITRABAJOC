---
id: LEY-02
eje: LEY
titulo: Debe haber consentimiento, retención y contrato de encargado
tipo: manual
herramienta: revisión + decisión de SDN
entorno: pruebas
destructivo: no
owasp: -
asvs: V8.1.1
cwe: CWE-359
activo: V3, V1, V7
---

## Objetivo

Cerrar los faltantes legales que dejó el relevamiento: disclaimer de
consentimiento por sindicato (R6), política de retención (R5), contrato de
encargado del tratamiento entre sindicato y Colm3na (R4), y el procedimiento
de acceso/supresión del afiliado.

## Cómo se corre

1. Partir del mapa de datos de LEY-01.
2. Redactar (con SDN) el disclaimer por sindicato y la política de retención.
3. Definir el flujo de derecho de acceso/supresión y el contrato de encargado.

## Resultado esperado

Cada faltante cerrado o con dueño y fecha. Son hallazgos LEY con dueño SDN.

## Notas

Iteración 2. `owasp: -`. Es más redacción y decisión que código.
