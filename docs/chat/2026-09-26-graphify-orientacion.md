# graphify como orientación secundaria
Fecha: 2026-09-26 · Herramienta: Code · Origen: sesión de Claude Code (rama chore/graphify-orientacion)
Estado: superado por docs/chat/2026-09-30-mapa-funcional.md
Quién: SDN

## Qué es y para qué

[graphify](https://github.com/Graphify-Labs/graphify) arma un grafo del código
(funciones, clases, llamadas, imports) leyendo el árbol de sintaxis con
tree-sitter. Se instala como **orientación secundaria**: una ayuda para
ubicarse en un proyecto que ya es grande, nunca una fuente de verdad. Siguen
mandando CLAUDE.md, HISTORIAL.md, BITACORA.md, las fichas de `docs/` y, por
encima de todo, el código.

## Decisiones (SDN)

- **Sin automatismos.** NO se corrieron `graphify claude install` (hook
  PreToolUse que empuja a consultar el grafo antes de leer archivos) ni
  `graphify hook install` (hooks de git que regeneran el grafo en cada commit
  y checkout, más un merge driver). El grafo se regenera a mano cuando hace
  falta.
- **Solo código, solo local.** `graphify extract . --code-only`: sin red, sin
  IA, sin telemetría (verificado en el código de graphify: no lee `.env` y en
  el entorno no había claves de API). El informe se genera con
  `graphify cluster-only . --no-label --no-viz`: `--no-label` evita que
  nombre las comunidades con una IA (lo haría con la clave que encuentre) y
  `--no-viz` no escribe el `graph.html` de varios MB.
- **Qué se versiona.** Solo `graphify-out/GRAPH_REPORT.md` (83 KB).
  `graph.json` pesa 7,3 MB y cada regeneración sumaría otra copia al
  historial: se genera local, en segundos y sin costo, cuando haga falta
  consultarlo (`.gitignore`: `graphify-out/*` + una excepción; ignorar la
  carpeta entera no sirve porque git no deja re-incluir archivos de una
  carpeta ignorada).
- **`.claudeignore` no existe en Claude Code**: en su lugar,
  `.claude/settings.json` le niega a Claude la lectura de `graph.html`,
  `wiki/`, `obsidian/` y `cache/`. El informe y el grafo siguen legibles.
- **`.graphifyignore`** excluye Chart.js y Leaflet vendoreados: eran 805 de
  6.505 nodos, minificados y sin sentido (`tn`, `ai()`, `at()`).
- Instalación: `uv` con winget; `uv tool install graphifyy` (0.9.69). El
  registro del skill `/graphify` (`graphify install`, escribe en la
  configuración de Claude del perfil) lo corre SDN a mano.

## Lo que mostró el primer grafo (commit 5cf1d03)

5.700 nodos, 14.206 relaciones, 264 comunidades; 96% EXTRACTED, 4% INFERRED,
sin ciclos de imports.

- **Nodos centrales reales**: `get_session()` (250), `Sindicato`,
  `UsuarioSindicato`, `Trabajador`, `exigir_sindicato()`, `Seccional`,
  `sesion_actual()`, `validar()`. Coincide con lo que CLAUDE.md ya dice.
- **Falsos positivos marcados EXTRACTED con confianza 1.0**: `_get()` y
  `_post()` aparecen 3.º y 4.º, pero son dos helpers de `carga/`
  (`monitor_servidor.py`, `publicar.py`); graphify les atribuye los
  decoradores `@app.get` / `@app.post` de `main.py` (≈245 aristas). **La
  etiqueta EXTRACTED no garantiza que la relación sea cierta.**
- **Comunidades**: siguen los archivos grandes (`db.py` modelos, `main.py`
  en 3–4 grupos por tema, `dashboard.js`, `enmascarado.py`, `xsk/`), con
  cohesión baja (0,02–0,03) porque `main.py` y `db.py` mezclan todo. Sin
  nombres (quedan "Community N"): hay que abrir la lista de nodos.
- **"Conexiones sorprendentes"**: tests que usan modelos de `db.py`. Nada que
  no se supiera.

## Regla de uso

Aprobada por SDN y escrita en CLAUDE.md ("Archivos principales",
`graphify-out/`): el grafo es orientación inicial, manda el código, toda
relación se verifica antes de actuar (INFERRED siempre, EXTRACTED también) y
es una foto del commit que dice el informe.

## Cómo regenerar

```
graphify extract . --code-only
graphify cluster-only . --no-label --no-viz
```

El informe dice de qué commit salió ("Graph Freshness"); si no es el HEAD,
el grafo está viejo.
