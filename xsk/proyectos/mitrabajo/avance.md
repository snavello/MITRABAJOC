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

**Sub-sprint R1 COMPLETO** (etapas 0-4). Usuarios de plataforma nominales con
login por usuario en /plataforma y /entornos, primer ingreso forzado, gestión
solo-superadmin con bitácora, y transición cerrada: genérico y PIN apagados
por defecto (reversibles por variable). **H-0002, H-0003 y H-0016 →
Solucionado.** Plataforma 0.33.01.

Estado del kit: 8 Solucionado, 2 Parcial, 6 Pendiente, 2 Aceptado; bloquean 1.
El único que bloquea es **H-0008** (rate-limit de login), cuyo cierre robusto
es el **perímetro (INF-05, Cloudflare)** — necesita dominio propio + cuenta.

Frentes que siguen (no dependen de credenciales de SDN): lote **H-0014 (deps
con CVE) + H-0015 (CI)**; carga DIS-01/02; y la iteración 2 (ENT/IA/OBS/LEY).
Nota de operación en la corrida de la etapa 4: antes de producción, snavello
y arsantagati deben haber hecho su primer ingreso.
