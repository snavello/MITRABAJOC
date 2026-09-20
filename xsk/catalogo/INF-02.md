---
id: INF-02
eje: INF
titulo: Los accesos a la infraestructura deben ser mínimos y trazables
tipo: configuracion
herramienta: gh + API de Render + revisión manual
entorno: pruebas
destructivo: no
owasp: A01:2021
asvs: V1.2.1
cwe: CWE-266
activo: V8, V9
---

## Objetivo

Que GitHub, Render, Postgres, S3 y los tokens tengan el mínimo privilegio y
se sepa quién tiene qué (actor A8). Prepara el terreno para el dev y el QA
que se suman.

## Cómo se corre

1. `gh api` para colaboradores del repo, protección de `main`/`demo`,
   secretos de Actions, y confirmar que el repo es privado.
2. Revisar alcance de cada token (Render, Grafana, Sentry, GitHub dispatch):
   ¿solo lo que necesita? ¿vence?
3. Revisar permisos del bucket S3 de backups.

## Resultado esperado

`paso` si cada acceso es mínimo, trazable y con rotación posible. Token con
más permisos que los que usa, o rama sin proteger, abre hallazgo.

## Notas

Cuando se sumen dev y QA, este test define qué se les da. Hoy todo es de SDN.
