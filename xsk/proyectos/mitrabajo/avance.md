---
iteracion: 1
etapa_actual: 8
etapa8: en_curso
etapa0: hecha
etapa1: hecha
etapa2: hecha
etapa3: hecha
etapa4: hecha
etapa5: en_curso
etapa6: hecha
etapa7: hecha
etapa9: pendiente
actualizado: 2026-09-20
---

## Cómo seguir

Cerrado el lote INF: H-0014 (deps con CVE, Parcial — multipart/jinja2/dotenv
al día + anthropic pinneado; falta el salto fastapi/starlette) y H-0015 (CI,
Solucionado — .github/workflows/ci.yml corre cada test_*.py + pip-audit).

Estado del kit: 9 Solucionado, 3 Parcial, 4 Pendiente, 2 Aceptado; bloquean 1.
El único que bloquea es H-0008 (rate-limit de login), que cierra con el
**perímetro (INF-05, Cloudflare + dominio propio)** — depende de infra de SDN.

Pendientes que quedan: follow-up de H-0014 (fastapi/starlette 1.x), H-0018
(panel cross-entorno público), H-0010/H-0012 (con un cambio de sesión), carga
DIS-01/02, INF-02/03/05 (accesos, backups, perímetro), y la iteración 2
(ENT/IA/OBS/LEY).
