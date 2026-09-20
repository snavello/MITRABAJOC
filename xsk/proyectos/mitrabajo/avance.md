---
iteracion: 1
etapa_actual: 8
etapa0: hecha
etapa1: hecha
etapa2: hecha
etapa3: hecha
etapa4: hecha
etapa5: en_curso
etapa6: hecha
etapa7: hecha
etapa8: pendiente
etapa9: pendiente
actualizado: 2026-09-20
---

## Cómo seguir

Etapa 7 (clasificación) cerrada con SDN uno a uno (2026-09-20). Ranking
final: **3 Críticos, 4 Altos, 6 Medios, 4 Bajos; 7 bloquean producción**;
1 aceptado (H-0011, herramienta de pruebas que no va a producción). Ajustes
de SDN sobre la propuesta: H-0004 subió a P5 (riesgo 25); H-0003 subió a D4
y su corrección pasó a usuario+contraseña como plataforma (la landing ya
guarda el registro de XSK); H-0005 y H-0007 bajaron; H-0017 y H-0013
bajaron; H-0011 aceptado; H-0012 a Bajo.

Los tres Críticos y los cuatro Altos, por orden del ranking:
1. H-0004 (25) identidad en cookie sin firma — AUT, C3
2. H-0001 (20) SESSION_SECRET default — DAT, C1
3. H-0002 (20) clave de plataforma default/sin hash — IDS, C2
4. H-0006 (12) cookies sin Secure — IDS, C1
5. H-0008 (12) logins sin límite de intentos — IDS, C2
6. H-0003 (12) landing: PIN default → usuario+contraseña — DAT, C3
7. H-0005 (10) eval evadible en fórmulas — AUT, C3

Sigue el bloque 4 (correcciones, etapa 8): por el ranking, una rama
`fix/xsk-H-NNNN` por hallazgo con su test de regresión. Los de complejidad
baja (H-0001, H-0006) se cierran rápido. En paralelo queda pendiente la
pasada dinámica/destructiva contra Pruebas (AUT-02, IDS-01, DIS-01/02, etc.).
