# Preact y htm vendoreados (Panel Sindical v2)

Lo usa la v2 del Panel Sindical (`PLAN_DASHBOARD_V2.md`, D1 y D2). Va
vendoreado como Chart.js y Leaflet: la CSP no deja cargar nada de un CDN y el
deploy de Render no tiene Node. Se carga sin build, por el `importmap` que arma
`main._importmap_panel_v2()`, con un sello `?v=` por archivo (D3).

| Paquete | Versión | Licencia | Paquete de npm |
|---|---|---|---|
| preact | 10.29.8 (2026-08-01) | MIT (`LICENSE-preact`) | https://registry.npmjs.org/preact/-/preact-10.29.8.tgz |
| htm | 3.1.1 (2022-04-26) | Apache-2.0 (`LICENSE-htm`) | https://registry.npmjs.org/htm/-/htm-3.1.1.tgz |

Integridad de los paquetes según npm:

- preact: `sha512-ej2aVZ+vZ8WO7tvlQWRM9N63A0KzF9q4mWJfDUHgYaIofWY9hu74QdnQrjoPMmZi2/nZ5gN0bJCQF49xQqx09Q==`
- htm: `sha512-983Vyg8NwUE7JkZ6NmOqpCZ+sh1bKv2iYTlUkzlWmA5JD2acKoxd4KVxbMmxX/85mtfdnDmTFoNKcg5DGAvxNQ==`

De dónde sale cada archivo, sin tocar un byte (bajado el 2026-10-12 con
`npm pack preact@10.29.8 htm@3.1.1`):

- `preact.module.js` y su `.map` ← `preact/dist/`
- `hooks.module.js` y su `.map` ← `preact/hooks/dist/` (importa `"preact"`
  por nombre: lo resuelve el `importmap`)
- `htm.module.js` ← `htm/dist/`

Los `.map` van para que las herramientas del navegador no pidan un archivo
que no existe; la página no los usa.

SHA-256 de cada archivo. `test_dashboard_v2.py` los compara: cambiar la
librería sin actualizar esta lista hace fallar la suite. Para actualizar, se
baja la versión nueva igual que arriba, se reemplazan los archivos y se
reescribe esta ficha entera (versión, fecha, integridad y SHA-256).

```
c30e721ebfdc6e2ad4c18c14d2dfb82667829c8aec27de1207774e3fc16858a8  preact.module.js
a6ee626f2d01570592dd569a792e3f050154aa02890eead8c223fa3ed5aa3d5a  hooks.module.js
ab33dd3f38059b9be4d5f5350128eefb2356639c4e0bbe9d9e8b3ba75847e9e4  htm.module.js
23c9b5e6e405d2883bad8414d9483ad3ecdb85a94be52655db980cfc83460c29  preact.module.js.map
a13936803e904e19f2f154e953541c20dbbd0667c881f446e7aefafcfe487a97  hooks.module.js.map
```
