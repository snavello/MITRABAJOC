---
id: DIS-04
eje: DIS
titulo: Los endpoints públicos no deben filtrar más de lo necesario ni abusar del CORS
tipo: dinamico
herramienta: httpx desde Code
entorno: pruebas
destructivo: no
owasp: A01:2021
asvs: V13.1.1
cwe: CWE-213
activo: V5, V3
---

## Objetivo

Que las 30 rutas públicas (mapa §1.1) no expongan de más. Foco: O14,
`/api/entornos/actividad` con `ACAO: *` devuelve agregados por sindicato y
CPU/RAM del servidor sin auth.

## Cómo se corre

1. Recorrer las 30 rutas públicas y ver qué devuelven sin sesión.
2. Medir `/api/entornos/actividad`: ¿qué agregados por sindicato salen? ¿es
   aceptable que sean públicos?
3. Revisar el `ACAO: *` de `/api/version` y `/api/actividad`.

## Resultado esperado

`paso` si lo público es inofensivo. Agregados por sindicato accesibles a
cualquier origen abren hallazgo (acotar a datos no sensibles o exigir pase).

## Notas

`/api/version` público es esperado (lo usa la landing). El de actividad es
el que hay que mirar.
