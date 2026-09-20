---
iteracion: 1
etapa_actual: 7
etapa0: hecha
etapa1: hecha
etapa2: hecha
etapa3: hecha
etapa4: hecha
etapa5: en_curso
etapa6: hecha
etapa7: en_curso
etapa8: pendiente
etapa9: pendiente
actualizado: 2026-09-20
---

## Cómo seguir

Bloque 3, primera pasada (2026-09-20): **revisión de código + análisis
estático**, sin tocar ningún entorno. 18 hallazgos abiertos (`hallazgos/`):
5 Críticos, 3 Altos, 8 Medios, 2 Bajos; 8 bloquean producción. Corrida en
`corridas/2026-09-20-1700-REVISION.md`. Herramientas: lectura dirigida,
bandit (encontró el `eval` de fórmulas, H-0005), pip-audit (CVE de
dependencias, H-0014), escaneo del historial (sin secretos, DAT-02 pasa).

**Falta y queda pendiente**: NO se corrió el modo destructivo ni ningún
test dinámico contra un entorno (fuerza bruta IDS-01, IDOR AUT-02,
aislamiento AUT-03/04, carga DIS-01/02, backups/perímetro INF-03/05). La
lista completa está en la sección "Pendiente" de la corrida.

Dos cosas antes de seguir:
1. **Clasificación (etapa 7)**: los puntajes probabilidad/daño/complejidad
   de los 18 son la PROPUESTA de Code; falta que SDN los confirme o ajuste.
2. Después: la pasada dinámica contra Pruebas, y el bloque 4 (correcciones)
   por orden del ranking, empezando por los cinco Críticos.
