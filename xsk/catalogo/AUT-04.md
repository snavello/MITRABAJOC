---
id: AUT-04
eje: AUT
titulo: Las rutas de admin deben seguir fallando cerrado (permiso por sección y alcance)
tipo: dinamico
herramienta: httpx desde Code + pytest existente
entorno: pruebas
destructivo: no
owasp: A01:2021
asvs: V4.1.3
cwe: CWE-862
activo: V3, V5
---

## Objetivo

Confirmar que `PERMISOS_RUTAS` y los guardianes de alcance
(`_exigir_alcance_seccional/area/tramite/encuesta`) frenan a un usuario de
área o a un Admin de Seccional fuera de su alcance, incluso armando el POST
a mano.

## Cómo se corre

1. Correr `test_areas_rutas.py` y confirmar que recorre `app.routes` y que
   ninguna ruta `/admin/*` quedó sin clasificar.
2. Login como usuario de área con permisos mínimos (Prensa Córdoba).
   Intentar rutas de otra sección y de otra seccional; esperar 403.
3. Intentar editar/publicar/borrar una encuesta central desde una seccional
   (debe frenar `_exigir_alcance_encuesta`).

## Resultado esperado

`paso` si todo lo fuera de alcance da 403 y no hay ruta sin clasificar. Es
el control que el mapa marcó como bien resuelto: el test lo confirma y queda
como línea de base.

## Notas

Áreas V2 está en rama sin desplegar (`CLAUDE.md` punto 21). Este test corre
contra lo que esté en Pruebas; si Áreas V2 aún no está, se marca `no_aplica`
con la nota y se reprograma para cuando se despliegue.
