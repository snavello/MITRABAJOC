---
id: ENT-03
eje: ENT
titulo: Los formularios que mutan estado deben estar protegidos de CSRF
tipo: dinamico
herramienta: httpx desde Code
entorno: pruebas
destructivo: no
owasp: A01:2021
asvs: V4.2.2
cwe: CWE-352
activo: V6, V7
---

## Objetivo

Que un sitio de terceros no pueda hacer acciones en nombre del usuario.
Cubre O10: sin token CSRF; ocho GET que mutan estado (`/…/salir`,
`/…/cambiar`, `/…/elegir/{id}`) que SameSite=Lax no cubre.

## Cómo se corre

1. Listar rutas que mutan estado, separando POST de GET.
2. Probar un request cross-site (sin cabecera de origen propia) contra las
   GET mutantes y los POST sensibles.
3. Evaluar token CSRF y/o pasar las GET mutantes a POST.

## Resultado esperado

`paso` si toda mutación exige método seguro + token o chequeo de Origin.
GET que muta sin protección = hallazgo.

## Notas

Iteración 2.
