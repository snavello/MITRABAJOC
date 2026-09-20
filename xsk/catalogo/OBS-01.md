---
id: OBS-01
eje: OBS
titulo: Un ataque debe dejar rastro visible y disparar aviso; debe haber runbook
tipo: manual
herramienta: revisión de Sentry/Grafana + simulacro
entorno: pruebas
destructivo: no
owasp: A09:2021
asvs: V7.2.1
cwe: CWE-778
activo: V3, V1, V6
---

## Objetivo

Que un intento de fuerza bruta, un IDOR o un pico de gasto de IA se vean en
Grafana/Sentry y avisen. Cubre R9 (guardia en horario regular) y la falta de
registro de acciones de plataforma (R1).

## Cómo se corre

1. Revisar qué alertas existen (mapa §10: 5xx, CPU, memoria, colector mudo).
2. Ver si hay señal para: muchos logins fallidos, muchos 403, pico de
   `/api/leer`.
3. Definir el runbook de incidente: quién avisa al sindicato y en cuánto (R9).

## Resultado esperado

`paso` si un ataque deja rastro y avisa, y hay runbook. Faltan alertas de
abuso y runbook = hallazgo.

## Notas

Iteración 2. Se apoya en la observabilidad ya montada (`CLAUDE.md` punto 25).
