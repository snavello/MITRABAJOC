# De dónde sale esta skill

Esta carpeta es copia **textual** de la skill `impeccable` de Paul Bakaus
(impeccable.style): "design guidance for AI coding agents", una skill con 24
comandos (`/impeccable audit|critique|polish|animate|typeset|layout|...`),
cuatro subagentes (en `.claude/agents/impeccable-*.md`) y un detector de
anti-patrones de diseño que corre en un binario aparte. No se edita acá: si
algo no aplica al proyecto, se dice en la skill propia (`diseno-mi-trabajo`),
que es la que manda.

- Repositorio: https://github.com/pbakaus/impeccable
- Carpetas copiadas: `.claude/skills/impeccable/` (SKILL.md, `reference/`,
  `scripts/`) y `.claude/agents/impeccable-*.md`, tal como el repo las
  distribuye para Claude Code (opción "Copy from Repository" del README).
- Commit: `0665bd812ae0908fcab17b96fd4f840defb882d9` (2026-10-19)
- Versión de la skill: 4.6.0; motor (`scripts/VERSION`): 0.1.15
- Licencia: Apache 2.0 (copia en `LICENSE`; `NOTICE.md` nombra lo que la
  skill toma de terceros: las referencias de iOS y Android)
- Copiada el 2026-10-19. Leídos enteros antes de instalarla: `SKILL.md`,
  los cuatro subagentes y `reference/craft-floor.md` (el que la skill carga
  antes de cada edición de interfaz); las 42 referencias restantes se
  recorrieron buscando cualquier instrucción que no fuera de diseño: no
  hay. Lo único que toca el sistema es el modo `live` (levanta un servidor
  local en el puerto 8400 y pide ensanchar la CSP del proyecto para
  cargarlo): **no se usa acá** (ver abajo).
- SHA-256 de la copia:
  - `SKILL.md`: `8270bfd275adbfece4c2fb90acdf92b1b0781b37e981ac2bc34d4e0c51eb705b`
  - `scripts/impeccable`: `f5d9fcd37559ed6af782306f71b7688ad1ec5e1a4f8ae1ef4d3168f42523b1b1`
  - `LICENSE`: `02bb8c3b4e70190e3986c0404ad2fd8d639b4f534252d82379cc1b502b6d1812`

## Cómo se usa en este proyecto

Es la caja de herramientas de la revisión de diseño pantalla por pantalla
(desde 2026-10-20): `/impeccable critique <pantalla>` para la lectura de
jerarquía y claridad, `/impeccable audit` para accesibilidad y responsive,
`/impeccable polish` para la pasada final, `/impeccable typeset|layout|
colorize|animate|clarify|distill|quieter` para un eje puntual. Sin argumento
ofrece el menú. Las tres skills de diseño conviven y se ordenan así:

1. **`diseno-mi-trabajo` manda.** Es el sistema de diseño de Colm3na: los
   cuatro colores de marca de cada sindicato, la tipografía fija, el
   encabezado único, la mesa, el título de pantalla, los modales, el
   movimiento. Donde `impeccable` diga otra cosa, gana el proyecto.
   Choques conocidos de su `craft-floor.md`: prohíbe el *kicker* (la
   etiqueta chica arriba de un título) y los números de sección, y acá el
   esquema "Hilo" lleva kicker en acento y el formulario guía del
   constructor numera sus pasos: los dos se quedan. Y sus consejos sobre
   fuentes propias no aplican: la tipografía es la de la skill del proyecto
   (Barlow Condensed + system-ui) y no se cambia por sindicato.
2. **`emil-design-eng`** es la referencia de movimiento (qué animar, con qué
   curva, cuánto tiempo); `impeccable animate` se lee con esa a la par.
3. **`frontend-design`** (Anthropic) queda como dirección visual general.

**Lo que NO se instaló, a propósito:**

- **Los hooks del detector** (`.claude/settings.json` del repo de origen:
  corre el motor tras cada Edit/Write y al terminar el turno). El motor es
  un binario que el lanzador `scripts/impeccable` descarga de GitHub Releases
  en el primer uso (`~/.impeccable/bin/`, con verificación SHA-256). En una
  sesión de Code en la nube ese binario no persiste entre sesiones y
  ejecutar un binario bajado no siempre está permitido, así que no se ata a
  cada edición. La skill prevé esa situación: si el lanzador falla, lee
  `PRODUCT.md` y `DESIGN.md` directo y sigue (sección "Launcher unavailable"
  de `SKILL.md`). Quien quiera el detector en su PC lo prende con
  `/impeccable hooks on` (escribe en `.claude/settings.local.json`, que no
  se versiona).
- **El modo `live`** (servidor local + CSP ensanchada): la CSP de la app es
  una decisión de seguridad (XSK H-0007) y no se abre para una herramienta
  de diseño.
- **`PRODUCT.md` y `DESIGN.md`** todavía no existen: los escribe
  `/impeccable init` (contexto durable del producto, con entrevista) y
  `/impeccable document` (el sistema visual leído del código). Son el
  primer paso de la revisión de diseño, no de la instalación.

## Para actualizarla

Volver a copiar `.claude/skills/impeccable/` y `.claude/agents/impeccable-*`
desde el repositorio (o `npx impeccable update` en una PC), leer el diff
entero, y actualizar commit, versión y SHA-256 de esta ficha en el mismo
commit. La `LICENSE` y el `NOTICE.md` se copian de la raíz del repo de
origen.
