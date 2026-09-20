---
id: INF-04
eje: INF
titulo: El pipeline debe correr los tests y escanear antes de desplegar
tipo: configuracion
herramienta: revisión de .github/workflows + propuesta de CI
entorno: pruebas
destructivo: no
owasp: A08:2021
asvs: V14.1.1
cwe: CWE-1104
activo: V2, V8, V4
---

## Objetivo

Que un cambio no llegue a Pruebas (que sigue `main`) sin pasar los tests ni
un escaneo. Cubre O18: hoy el único workflow es el colector de métricas; la
suite corre a mano.

## Cómo se corre

1. Revisar `.github/workflows/`.
2. Confirmar que no hay CI de tests, lint ni escaneo de dependencias/secretos.
3. Proponer un workflow que corra cada `test_*.py` por separado (regla del
   proyecto) + pip-audit + gitleaks en cada push a `main`.

## Resultado esperado

Estado actual = hallazgo (falta CI). Es de la Etapa 2 de PLAN_ENTORNOS.md;
XSK lo registra y aporta el workflow como corrección.

## Notas

Push a `main` redeploya Pruebas sin gate: un test roto llega al entorno.
