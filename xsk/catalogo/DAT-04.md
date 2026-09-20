---
id: DAT-04
eje: DAT
titulo: Lo que sale de la app hacia terceros debe ir cifrado y mínimo
tipo: revision
herramienta: security-review (Code)
entorno: pruebas
destructivo: no
owasp: A02:2021
asvs: V9.1.1
cwe: CWE-319
activo: V1, V3, V8
---

## Objetivo

Que toda llamada externa (mapa §4) sea HTTPS, con timeout, y mande lo mínimo.
Foco: el archivo del recibo completo a Anthropic (V1) y el nº de expediente
en el cuerpo del push.

## Cómo se corre

1. Revisar cada cliente externo: esquema (https), timeout, qué viaja.
2. Confirmar que los tokens van en cabecera, nunca en la URL.
3. Revisar que el push no lleve más que lo necesario.

## Resultado esperado

`paso` si todo es HTTPS con timeout y payload mínimo. Un timeout ausente que
permita colgar un worker es hallazgo (cruza con DIS).

## Notas

El envío del recibo a Anthropic es inherente al producto; se registra como
riesgo aceptado del tratamiento (LEY), no como algo a "corregir".
