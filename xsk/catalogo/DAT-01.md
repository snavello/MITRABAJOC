---
id: DAT-01
eje: DAT
titulo: Ningún secreto debe tener un valor por defecto usable escrito en el código
tipo: revision
herramienta: security-review + grep dirigido (Code)
entorno: pruebas
destructivo: no
owasp: A05:2021
asvs: V6.4.1
cwe: CWE-798
activo: V8, V6
---

## Objetivo

Que ningún secreto arranque con un default que sirva para entrar o firmar.
Cubre O1 (`SESSION_SECRET`), O3 (`PLATAFORMA_PASSWORD`, `PLATAFORMA_CUIT`) y
O4 (`PIN_ENTORNOS`, duplicado). Sin la variable, la app debería negarse a
arrancar (como `DATABASE_URL`), no caer a un valor público.

## Cómo se corre

1. Revisar cada `os.getenv` con default (mapa §5).
2. Para los que son secreto (firma, clave, PIN), confirmar si el default es
   usable. Un default usable en el código = hallazgo.
3. Verificar en Render que las variables reales estén cargadas en Pruebas y
   Demo (que el default nunca se use en un entorno real).

## Resultado esperado

`paso` si los secretos fallan cerrado sin su variable, o el default es
inofensivo (no permite firmar ni entrar). `SESSION_SECRET` y
`PLATAFORMA_PASSWORD` con default usable son Crítico.

## Notas

La corrección típica: `os.environ["X"]` que levante `RuntimeError` si falta,
con un mensaje que explique qué poner (patrón de `db.py` con `DATABASE_URL`).
