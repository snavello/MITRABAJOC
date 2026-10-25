---
name: xsd
description: XSANDERS Design Kit — auditoría de diseño de una app entera con revisores en paralelo, informe interactivo donde la persona decide cada mejora (Aceptar / Dejar como está / Otro cambio), plan, aplicación con agentes y segunda vuelta. Usar cuando pidan revisar o auditar el diseño de un proyecto o de varias pantallas, "pasarle XSD", seguir con las decisiones de un informe de XSD, o una segunda vuelta; y cuando el usuario diga /xsd.
---

# XSD: cómo guiar cada fase

**`<kit>` es la carpeta de esta skill** (la «Base directory» que te da
Claude Code al cargarla): ahí están `METODO.md`, `herramientas/`,
`plantillas/` e `informe/`. Lo que es del proyecto vive en el proyecto, en
`xsd/proyectos/<proyecto>/` (ficha, inventario, contexto, historial), y los
archivos de trabajo en `xsd-trabajo/`, que no se versiona.

Leé primero `<kit>/METODO.md` (el método y las lecciones) y, si existe,
`xsd/proyectos/<proyecto>/historial.md` (qué se hizo antes). Las piezas
mecánicas están en `<kit>/herramientas/xsd.py`: usalas, no reimplementes el
formato del informe ni el de los hallazgos. Si en `xsd/proyectos/` hay una
sola carpeta, ese es el proyecto; si hay varias, preguntá cuál.

**Antes de la fase 1 verificá lo que hace falta**, y si algo falta decí cómo
conseguirlo en vez de seguir a medias:
- la referencia de diseño que nombra la ficha (`referencia`, por defecto la
  skill Impeccable en `.claude/skills/impeccable/`, de
  https://github.com/pbakaus/impeccable, Apache 2.0);
- Python 3 con Pillow, y Node con Playwright y Chromium
  (`XSD_CHROMIUM=/ruta` si el navegador está en otro lugar);
- `xsd-trabajo/` en el `.gitignore` del proyecto.

## Pedidos

| Pedido | Qué hacer |
|---|---|
| `/xsd`, «revisá el diseño con XSD» | Si no hay ficha, fase 0. Después fases 1 a 3: capturas, hoja de contacto, grupos, brief, revisores en paralelo, informe publicado y el link a la persona. |
| `/xsd ficha` | Solo la fase 0: ficha (desde `<kit>/plantillas/ficha.json`), inventario, script de sesiones y contexto. |
| `/xsd seguir`, «ya decidí» | Bajar las decisiones (`ArtifactData list` con `out_dir`), correr `xsd.py decisiones`, armar el plan en unas diez líneas y **esperar el visto bueno** antes de tocar código. |
| `/xsd aplicar` | Con el visto bueno, fase 4: bloques en orden (base → compartido → puntual), agentes en worktrees, integración, tests y PR. |
| `/xsd segunda vuelta` | Fase 5, sobre lo tocado: previos, brief de segunda vuelta, revisores, informe nuevo. |
| `/xsd estado` | Leer `historial.md` y la corrida más nueva de `xsd-trabajo/`: qué fase, qué falta decidir, qué queda por aplicar. |

## Reglas que no se negocian

1. **Nada se toca sin el visto bueno de la persona.** Los revisores solo
   escriben su JSON, y el plan se presenta antes de ejecutarse.
2. **Las reglas de la casa mandan sobre Impeccable**, y las decisiones ya
   tomadas no se proponen deshacer. Las dos van en el contexto del encargo.
3. **Mirar la hoja de contacto antes de lanzar revisores.** Una tanda con
   sesiones vencidas o pestañas repetidas gasta revisores en nada.
4. **«Dejar» no entra al plan y «cambio» reemplaza la sugerencia** por la
   nota de la persona.
5. **Cada agente que captura usa su propio `quien` y su propio puerto**, y
   ninguno mata procesos ajenos.
6. **Preguntas de a una.** En la fase 0 se pregunta solo lo que no se
   deduce del código.
7. **Al cerrar una vuelta**:
   - copiar `consolidado.json` a `xsd/proyectos/<p>/vueltaN-consolidado.json`;
   - sumar una línea a `historial.md`;
   - seguir el cierre de bloque del proyecto (bitácora, versión).
8. **El informe se publica como artifact con `db`**:
   - archivos de `informe/archivos.json`;
   - capabilities `{"db": {}, "user": {}}`;
   - verificar el guardado con un `ArtifactData list` antes de dar el link.

   Cada vuelta es un artifact nuevo.

## Agentes

- **Revisores**: agentes comunes, en segundo plano, todos en el mismo
  mensaje. Cada uno recibe su grupo, la ruta del brief y su salida.
- **Equipo que aplica**: agentes con `isolation: "worktree"`, que reciben
  `<kit>/plantillas/brief_equipo.md` completado con su encargo, sus archivos,
  su puerto y su `quien`.
- **Integración**: la hace la sesión principal, a medida que llegan los
  reportes.
- **Avance**: durante todo el proceso, `xsd.py avance` mantiene al día
  `xsd-trabajo/avance.json`, que muestra la ventana del plugin
  `avance-agentes` si está instalado (es opcional).
