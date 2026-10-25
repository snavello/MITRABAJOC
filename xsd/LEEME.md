# XSD, XSANDERS Design Kit

XSD es una auditoría de diseño con revisores en paralelo. Se encarga de:
- la ficha del proyecto;
- las capturas;
- los revisores;
- el informe interactivo con las decisiones;
- el plan y su aplicación con agentes;
- la segunda vuelta.

Se le pide a Claude Code con **«revisá el diseño de este proyecto con XSD»**
o con `/xsd`. El método completo está en `METODO.md`.

## Qué hay acá

```
xsd/
  METODO.md                  el método, fase por fase, y las lecciones
  LEEME.md                   este archivo
  plantillas/                ficha.json, brief_revisor.md, brief_segunda_vuelta.md, brief_equipo.md
  herramientas/xsd.py        capturar · hoja · brief · informe · decisiones · previos · encargos · avance
  herramientas/capturar.cjs  el capturador (Playwright)
  informe/index.html         la página del informe (sin librerías)
  mod/avance-agentes/        ventana de avance del plan y de los agentes (mod de Claude Code)
  proyectos/mitrabajo/       Colm3na: la ficha, el inventario, las sesiones, el contexto y el historial
.claude/skills/xsd/SKILL.md  la skill: cuándo y cómo la usa Claude
```

## Llevarlo a otro proyecto

1. Copiar `xsd/` sin `proyectos/mitrabajo/`, y `.claude/skills/xsd/`.
2. Tener la skill **Impeccable** en `.claude/skills/impeccable/`. Es de Paul
   Bakaus, con licencia Apache 2.0 (impeccable.style). La de este repositorio
   está fijada a un commit, en `ORIGEN.md`, y se puede copiar tal cual. Si el
   proyecto tiene reglas de diseño propias, se nombran en `lecturas` de la
   ficha: ante un choque, mandan esas.
3. Instalar lo que hace falta:
   - Python 3 con **Pillow**, para el informe y la hoja de contacto.
   - Node con **Playwright** y Chromium, para las capturas. Si el navegador
     está en otro lugar, `XSD_CHROMIUM=/ruta/al/chromium`.
4. Agregar `xsd-trabajo/` al `.gitignore`.
5. Decirle a Claude «revisá el diseño de este proyecto con XSD». La primera
   vez arma la ficha, el inventario y el script de sesiones, y pregunta solo
   lo que no puede deducir.

Más adelante XSD se va a mudar a un repo propio, como plugin de Claude Code,
para instalarlo con `/plugin install` y actualizarlo en un solo lugar.
Mientras tanto vive acá, igual que `xsk/`.

## La ventana de avance (opcional)

`mod/avance-agentes` es un mod de Claude Code. Abre una ventana con:
- los bloques del plan, que escribe `xsd.py avance` en
  `xsd-trabajo/avance.json`;
- lo que está haciendo cada agente.

Para cargarlo en una sesión:
- `claude --plugin-dir xsd/mod/avance-agentes`, o
- copiarlo a la carpeta de mods de la sesión.

Después, `/avance` la abre.

## Lo que el informe necesita

Se publica como **artifact de claude.ai** con la capacidad `db`. Las
decisiones quedan en la base del propio informe, colección `decisiones`, y
Claude las lee con `ArtifactData`.

Sin claude.ai, el `index.html` local funciona igual: guarda en el navegador
y ofrece copiar las decisiones para pegarlas en la conversación.
