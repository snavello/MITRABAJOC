# De dónde sale esta skill

`SKILL.md` y `LICENSE` son copia **textual** de la skill `emil-design-eng` de
Emil Kowalski (diseñador e ingeniero, Vercel y Linear; autor de Sonner y
Vaul). No se editan acá: si algo no aplica al proyecto, se dice en la skill
propia (`diseno-mi-trabajo`, sección "Movimiento"), que es la que manda.

- Repositorio: https://github.com/emilkowalski/skills
- Archivo: `skills/emil-design-eng/SKILL.md`
- Commit: `2d228630ba1446365f614a108cb8252f1feda202` (2026-10-11)
- Licencia: MIT (copia en `LICENSE`)
- Copiada el 2026-10-12, leída entera antes de instalarla (674 líneas, solo
  consejos de diseño y animación; ninguna instrucción fuera de eso).
- SHA-256 de la copia:
  - `SKILL.md`: `ffbe68e6007fb42cb8149f089b400a1ca007d59ba23e8948e2be4476f3175939`
  - `LICENSE`: `4ff5bdb7887ec1435c9cab0e8d1a7caee704d894d65c2a008ccc68b1cc2f260b`

## Cómo se usa en este proyecto

Como referencia y revisora del movimiento de la interfaz: qué animar, con qué
curva y cuánto tiempo. Ante un choque con las reglas del proyecto, mandan las
del proyecto:

- **Nada desde CDN y sin paso de compilación**: los ejemplos con Framer Motion
  o `useSpring` no aplican; acá se anima con CSS (transiciones y keyframes) y
  con lo que traen Chart.js y Leaflet.
- **La tipografía, los colores y el encabezado** son los de `diseno-mi-trabajo`.
- **Las duraciones de la v2 del Panel son de presentación** (SDN, 2026-10-13):
  más largas que los ~300 ms que recomienda la skill, con una curva que
  reparte el recorrido para lo que tiene que verse entrar.
- **`prefers-reduced-motion`**: la v2 y los modales de toda la plataforma
  (`static/movimiento.css`) siguen a la skill y dejan fundidos suaves. El
  resto de la app todavía corta todo vía `marca.css`, hasta que el
  movimiento se lleve pantalla por pantalla.

## Para actualizarla

Volver a copiar el archivo desde el repositorio, leer el diff entero, y
actualizar commit y SHA-256 de esta ficha en el mismo commit. Las otras skills
del repositorio (`review-animations`, `improve-animations`,
`animation-performance`) no están instaladas.
