---
id: INF-01
eje: INF
titulo: Las dependencias no deben tener vulnerabilidades conocidas ni versiones abiertas
tipo: estatico
herramienta: pip-audit + revisión de requirements
entorno: pruebas
destructivo: no
owasp: A06:2021
asvs: V14.2.1
cwe: CWE-1104
activo: V8, V4
---

## Objetivo

Que ninguna dependencia tenga CVE conocido y que todas estén pinneadas.
Cubre O18 (`anthropic>=0.69.0` abierta).

## Cómo se corre

1. `python -m pip_audit -r requirements.txt` y sobre el entorno instalado.
2. Confirmar que las 17 estén con `==` (hoy 16/17).
3. Revisar `requirements-dev.txt` aparte.

## Resultado esperado

`paso` si pip-audit no reporta CVE y todo está pinneado. Un CVE con
severidad alta o una versión abierta abre hallazgo.

## Notas

Se corre en cada iteración: aparecen CVE nuevos. Ideal: sumarlo al CI (INF-04).
