---
iteracion: 1
etapa_actual: 5
etapa0: hecha
etapa1: hecha
etapa2: hecha
etapa3: hecha
etapa4: hecha
etapa5: pendiente
etapa6: pendiente
etapa7: pendiente
etapa8: pendiente
etapa9: pendiente
actualizado: 2026-09-20
---

## Cómo seguir

Bloque 2 cerrado (2026-09-20): alcance de la iteración 1 (`alcance.md`:
AUT → IDS → DAT → INF → DIS, más ENT-01 cabeceras y LEY-01 clasificación),
catálogo de 30 tests en los nueve ejes (`xsk/catalogo/`) con su herramienta
y estándar, y la página `/entornos/xsanders` (solapa "Seguridad", lectora
del registro; Plataforma 0.29.01).

Sigue el bloque 3: correr la batería de la iteración 1, un eje por vez
(`/xsk correr AUT`), dejando la corrida en `corridas/` y abriendo un
hallazgo por cada `fallo`. Empieza por AUT porque su corrección (firmar la
identidad) cambia cómo se prueban los demás ejes.
