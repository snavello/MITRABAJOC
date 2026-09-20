---
id: DAT-02
eje: DAT
titulo: No debe haber secretos en el repositorio ni en su historial
tipo: estatico
herramienta: git log -p + regex; gitleaks si se instala
entorno: pruebas
destructivo: no
owasp: A05:2021
asvs: V14.3.2
cwe: CWE-540
activo: V8
---

## Objetivo

Que ni el árbol ni el historial de git tengan claves, tokens ni `.env`.

## Cómo se corre

1. `git log --all -p` filtrado por patrones (`SESSION_SECRET=`,
   `ANTHROPIC_API_KEY`, `sk-ant`, `PLATAFORMA_PASSWORD=`, `Bearer `,
   `postgres://`, credenciales de S3).
2. Confirmar que `.env` está en `.gitignore` y nunca se commiteó.
3. Buscar secretos reales pegados en tests, docs o `docs/chat/`.

## Resultado esperado

`paso` si no aparece ningún secreto real. Un secreto en el historial abre
hallazgo Alto (hay que rotarlo, no solo borrarlo).

## Notas

`gitleaks` no está instalado; si se agrega, es la herramienta preferida.
Nota del mapa: `.env` con valores reales está en el disco de SDN (gitignored).
