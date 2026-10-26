# Corridas de XSD en Colm3na

Cada corrida deja acá su línea: cuándo fue, qué se miró, qué salió y dónde quedó. Los archivos de trabajo (capturas, hallazgos, informe) no se versionan, porque viven en `xsd-trabajo/`. Lo que queda es lo que hace falta para la próxima vuelta:

- el informe publicado;
- las decisiones;
- `consolidado.json`, que se copia acá al cerrar.

| Fecha | Vuelta | Alcance | Resultado | Informe |
|---|---|---|---|---|
| 2026-10-24 | 1 | 61 pantallas, 8 revisores (G1–G8), Laguna y Noticiero, escritorio y teléfono | 228 hallazgos; SDN decidió 144: 110 aceptar, 18 dejar, 16 cambio | https://claude.ai/artifact/3AjvDVA5Xe3oZHMCMiNiP1 |
| 2026-10-25 | 2 | Lo migrado: ingresos y empresa, plataforma, Panel Sindical v2 y pantallas viejas; 28 pantallas, 4 revisores (R1–R4) | De lo pedido en la vuelta 1: 63 resueltos y 7 parciales. 42 hallazgos nuevos; SDN: 36 aceptar, 1 cambio, 5 dejar | https://claude.ai/artifact/TUWmGHT2R8FwNqhohuzvAu |

Las dos vueltas se aplicaron en los PR #167 a #171. La narrativa completa está en `HISTORIAL.md`, sección «Auditoría de diseño y plan de mejoras».

Desde el 2026-10-25 el kit vive en `snavello/xsanders-design-kit`; la skill de este repositorio es su copia fijada a un commit (`.claude/skills/xsd/ORIGEN.md`).

Catálogo de estilos (2026-10-25/26): de 113 fichas extraídas de los lienzos del concurso y de otras propuestas (`catalogo/fuentes/`) salieron 60 estilos aplicados a la portada de ACME, en tres tandas, todas aprobadas por SDN: 20 iniciales, 20 más (muy claros, de color, grises con uno o dos colores, flúor y fotográficos, con fotos reales CC0) y 20 con movimiento. Preview: https://claude.ai/artifact/L4SMzvqji9vxP7TMupmEHH. Vive en el kit, `catalogo/`.
