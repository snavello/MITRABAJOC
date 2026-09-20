---
id: INF-03
eje: INF
titulo: El backup debe existir, estar cifrado y restaurar de verdad
tipo: configuracion
herramienta: pg_restore en una base descartable + revisión de S3
entorno: pruebas
destructivo: no
owasp: A08:2021
asvs: V1.5.1
cwe: CWE-1188
activo: V9, V1, V3
---

## Objetivo

Confirmar R7/R8: hay copia diaria de Render y copia en S3, pero nunca se
ensayó restaurarla. Un backup que no restaura no es un backup.

## Cómo se corre

1. Bajar el backup más reciente de S3 y restaurarlo en una base Postgres
   descartable local; contar filas de tablas clave.
2. Confirmar que el dump está cifrado en reposo y en tránsito.
3. Medir cuánto tarda la restauración (define el RTO real frente a R8: una hora).
4. Documentar el RPO (cada cuánto se respalda vs. cuántos datos se pierden).

## Resultado esperado

`paso` si la restauración funciona, está cifrada, y RTO/RPO están dentro de
lo aceptable (R8). Si nunca se probó y falla, o el RPO no está definido,
hallazgo.

## Notas

`destructivo: no` (restaura en base descartable, no toca Pruebas). Necesita
las credenciales de S3 (falta en `configuracion.md`).
