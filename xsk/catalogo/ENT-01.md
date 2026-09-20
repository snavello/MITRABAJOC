---
id: ENT-01
eje: ENT
titulo: La app debe emitir las cabeceras de seguridad en toda respuesta
tipo: dinamico
herramienta: httpx desde Code + middleware nuevo
entorno: pruebas
destructivo: no
owasp: A05:2021
asvs: V14.4.1
cwe: CWE-693
activo: V1, V3, V5, V6
---

## Objetivo

Que toda respuesta lleve CSP, HSTS, X-Frame-Options (o `frame-ancestors`),
X-Content-Type-Options, Referrer-Policy y Permissions-Policy. Cubre O7:
hoy no hay ninguna. Entra en la iteración 1 porque un solo middleware
contiene XSS (incluido el del SVG/HTML subido), clickjacking y MIME sniffing.

## Cómo se corre

1. `curl -I` sobre varias rutas (login, panel, `/logo/{id}`) y listar las
   cabeceras de seguridad presentes.
2. Diseñar una CSP que no rompa Chart.js/Leaflet vendoreados ni los SVG
   `|safe` legítimos.
3. Confirmar que `X-Content-Type-Options: nosniff` no rompa el servido de
   imágenes legítimas.

## Resultado esperado

`paso` cuando todas las cabeceras estén y la CSP sea restrictiva sin romper
la app. Ausencia total = hallazgo (corrección: un middleware).

## Notas

La CSP fuerte es además la contención de fondo del XSX de SVG/HTML subido
(ENT-02, iteración 2): por eso conviene primero la cabecera.
