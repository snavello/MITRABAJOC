# Tutorial paso a paso de XSII (decisión X20)

Fuente de `recursos/xsii-tutorial.html` (Recursos de `/entornos`).

- `pasos.json`: todo el texto (intro, pasos, preguntas, «qué viene») y qué captura va en cada paso.
- `capturas/`: las capturas reales (JPEG, 1280 px de ancho de pantalla a doble densidad).
- `preparar.py`: limpia los restos de XSII en la base LOCAL, crea el usuario «Sofía Demo» y el proyecto
  «UOM · Primera versión» con tres tarjetas de la Mesa. Solo para la base de desarrollo.
- `capturar.js`: levanta Playwright, ejecuta las acciones de verdad contra un servidor local
  (`ENTORNO=local`, demo cargada, puerto 8765) y deja las capturas con los círculos numerados.
- `armar.py`: arma el HTML autocontenido (imágenes reducidas en base64, CSS adentro, imprimible en A4).

## Regenerar

```
NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
  node docs/xsii/tutorial/capturar.js          # vuelve a filmar (llama a preparar.py)
.venv/bin/python docs/xsii/tutorial/armar.py   # rearma recursos/xsii-tutorial.html
```

La miniatura `recursos/xsii-tutorial.jpg` (640x400) es una captura de la portada del HTML.

## Agregar pasos en los bloques que vienen

1. En `capturar.js`, sumar los tramos nuevos (`foto(page, 'NN-nombre', { sel, marcas })`; las marcas son
   `{css|h3|btn|txt, n}`).
2. En `pasos.json`, sumar el paso con su texto y sus figuras (`ancho`: `full`, `med` o `chica`) y
   actualizar `alcance` y `viene`.
3. Correr los dos comandos y revisar el HTML.

## Cosas a saber

- Los datos son de la demo: lo «simulado» se dice en el texto (por ejemplo, la demora del pedido se
  fabrica atrasando la fecha por SQL).
- `capturar.js` corrige en el vuelo un error de `static/xsii/xsii.js` en la vista Mapa (una constante
  `resuelta` repetida deja la vista en blanco). Sacar ese parche cuando se arregle el archivo.
- Sin fuentes ni scripts externos: la CSP de la app solo permite lo propio.
