---
id: DIS-03
eje: DIS
titulo: Un deploy no debe tumbar el servicio en hora pico
tipo: configuracion
herramienta: revisión de Render + FLUJO.md
entorno: demo
destructivo: no
owasp: A04:2021
asvs: V1.5.1
cwe: CWE-400
activo: V4
---

## Objetivo

Confirmar R8: una hora de tolerancia salvo mantenimiento anunciado fuera de
hora pico. Que el deploy de Pruebas (que sigue `main`) y la promoción a
demo/prod tengan health check y no dejen la app caída.

## Cómo se corre

1. Confirmar `/healthz` como Health Check Path en Pruebas y (al promover) en
   demo/prod — pendiente anotado en `CLAUDE.md` punto 9.
2. Revisar que el Pre-Deploy (Alembic) no bloquee con un lock largo
   (`engine_para_migraciones` con `lock_timeout`).
3. Verificar que un deploy fallido no deje el servicio abajo (rollback).

## Resultado esperado

`paso` si hay health check en cada servicio y el deploy es seguro. Falta de
health check en demo/prod es hallazgo antes de promover.

## Notas

Ligado a INF-04 (que el deploy corra los tests antes).
