# Tutorial paso a paso de XSII (decisión X20)

Fuente de `recursos/xsii-tutorial.html` (Recursos de `/entornos`).

- `pasos.json`: todo el texto (intro, pasos, preguntas, «qué viene») y qué captura va en cada paso.
- `capturas/`: las capturas reales (JPEG, 1280 px de ancho de pantalla a doble densidad).
- `preparar.py`: limpia los restos de XSII en la base LOCAL, crea el usuario «Sofía Demo» y el proyecto
  «UOM · Primera versión» con tres tarjetas de la Mesa. Solo para la base de desarrollo.
- `capturar.js`: levanta Playwright, ejecuta las acciones de verdad contra un servidor local
  (`ENTORNO=local`, demo cargada, puerto 8765) y deja las capturas con los círculos numerados.
- `preparar_mesa.py` + `capturar_mesa.js`: filman SOLO el bloque 5 (ver abajo).
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
- El Mapa se captura tal cual, sin parches (el error de `xsii.js` que lo dejaba en blanco ya no existe).
- Versión del bloque 2: «Preguntame» se filma con el servidor en modo simulado (`MOCK_EXTRACTOR=1`): las
  respuestas son simuladas y el tutorial lo dice. Con IA real el texto cambia, no el uso.
- `capturar.js` espera 65 s antes del segundo reclamo del mismo insumo (el servidor frena dos reclamos
  seguidos en menos de un minuto): la corrida entera dura unos dos minutos y medio.
- El pedido a mano se filma sobre «Recibos de muestra» (REC-01) y el reclamo con el asistente sobre «Padrón
  recibido» (PAD-01), para que cada insumo tenga su historia limpia. El peso del HTML va por `ANCHOS` y la
  calidad JPEG de `armar.py` (tope 6 MB).
- Sin fuentes ni scripts externos: la CSP de la app solo permite lo propio.
- Rediseño de la pantalla (2026-11-27): «Preguntame» es un botón amarillo arriba (héroe y cabecera de la ficha), la
  Guía tiene Atrás/Adelante (`#x-atras`, `#x-adelante`) y la ficha la botonera `.fnav`; el insumo vive en la banda
  «Se espera del sindicato» (se llama «Insumos» solo cuando todos llegaron). Los bloques «Lo que dice el control»,
  «Decisiones activas», «Historial de la tarea» y «Necesita y destraba» van plegados (`details.pleg`): `capturar.js`
  los abre con `abrirBloque(page, 'título')` antes de fotografiarlos. Las marcas aceptan `dx`/`dy` para correr el
  círculo cuando taparía el texto. Paso nuevo «Moverse entre los pasos» (captura `36-guia-atras-adelante`).
  Ahora son 20 pasos y 37 figuras; el HTML pesa ~5,4 MB (ancho `full` 1200 y JPEG 68 en `armar.py`).
- Bloque 3 (2026-11-27): paso nuevo «Cargar las seccionales desde la planilla» (capturas `37` a `43`, tramo «3b» de
  `capturar.js`), con la planilla propia `seccionales-tutorial.csv` (dos filas que ya existen, dos válidas, una rechazada
  por latitud sin signo y dos dudosas sin coordenadas: una se deja afuera y la otra se carga «sin ubicar»). La UOM de la
  demo ya trae once seccionales, por eso `preparar.py` borra las cinco que la planilla crea (`NUEVAS_DEL_TUTORIAL`, solo si
  ningún afiliado las usa) para poder filmar otra vez. La carga se filma antes de «Pedir un dato a mano»: deja EST-01 «En
  curso, falta confirmar» y el insumo «Lista de seccionales» recibido, y el resto del tutorial sigue coherente (PAD-02
  sigue frenada por Seccionales y Padrón recibido). Ahora son 21 pasos y 44 figuras; JPEG a calidad 62 para quedar
  bajo 6 MB (5,7 MB). Pendiente fuera de esta carpeta: `recursos.py` dice «Versión del bloque 2» en la descripción.
- Bloque 4 (2026-11-27): el paso de Seccionales se rehízo con la planilla `seccionales-tutorial.csv` con cabeceras «a su manera»
  (Delegación, Sede, Altura, CP, Secretario, Precisión, y «Fuente» sin usar): ahora muestra «Columnas de la planilla» (captura
  `44-as-columnas`) y una fila de ubicación «aproximada» (Bahía Blanca, junto a las dos sin coordenadas). Paso nuevo «Cargar el
  padrón desde la planilla» (capturas `45` a `49`, tramo «5d» de `capturar.js`, después de «Confirmar una tarea») con la planilla
  `padron-tutorial.csv` (13 personas inventadas de CUIL 2096xxxxxx válidos: 9 válidas, 2 dudosas por «Seccional Bariloche», 1
  rechazada por localidad en blanco y 1 por verificador inválido; la columna «Contacto» se corrige a mano a «Mail»; total declarado
  2.990). La carga exige EST-01 y PAD-01 resueltas, por eso el tramo confirma EST-01 antes. `preparar.py` borra también las 13
  personas del tutorial (solo si no tienen trámites) para poder filmar de nuevo. El total «en el sistema» (2.987) depende de la base
  de demo local (2.976 afiliados de la UOM antes de cargar): si esa base cambia, cambia la cifra y hay que ajustar el texto del
  paso (y el total declarado de `capturar.js`). Ahora son 22 pasos y 50 figuras; ancho `full` 1100, `med` 820 y JPEG 58 en
  `armar.py` para quedar bajo 6 MB (5,6 MB). Pendiente fuera de esta carpeta: `recursos.py` dice «Versión del bloque 2».
- Bloque 4b (2026-11-28): dos pasos nuevos, «Leer los recibos de muestra» y «Revisar y cargar los conceptos» (capturas `50` a `56`,
  tramo 12 de `capturar.js`, AL FINAL del guion para no mover el estado de los pasos de arriba; en `pasos.json` van después de
  «Cargar el padrón»). El tramo confirma REC-01 (la carga de REC-04 la necesita) y lee cinco recibos de ejemplo
  (`recibos-ejemplo/*.png`, imágenes vacías: solo importa el nombre; uno de ellos es «ilegible» a propósito). **El servidor se levanta con
  `servidor_recibos.py`** y no con uvicorn a secas: corre con `MOCK_EXTRACTOR=1` pero reemplaza `main.extraer` para que cada archivo
  devuelva conceptos distintos (el simulado de siempre devuelve el mismo recibo para cualquier archivo y la revisión quedaba pobre).
  Empleadores y conceptos inventados, con CUIT válidos 30700001004/012/020; `preparar.py` borra los conceptos de esos tres CUIT para
  poder filmar otra vez. Latencia simulada `TUTORIAL_LATENCIA` (3 s) para poder fotografiar el avance «2 de 5».
  Comando: `MOCK_EXTRACTOR=1 ENTORNO=local .venv/bin/python docs/xsii/tutorial/servidor_recibos.py 8765` y después el `capturar.js` de arriba.
  Al refilmar no se pisaron las capturas 01 a 49 (dependen de la base de la demo; solo se sumaron las nuevas). Ahora son 24 pasos y 57
  figuras; HTML ~5,8 MB (JPEG a calidad 52 en `armar.py`). La miniatura no se regeneró (la portada no cambió salvo el encabezado).
- Bloque 5 (2026-11-28): dos pasos nuevos, «El sindicato sube la planilla en la Mesa y XSII la usa» (capturas `57` a `60`, después de
  «Cargar las seccionales») y «Los hitos de la Mesa» (capturas `62` a `65`, al final). Se filmaron con un guion APARTE, `capturar_mesa.js`, que
  llama a `preparar_mesa.py` (usa `preparar.py` y suma los hitos semilla de La Bancaria al proyecto y una usuaria del sindicato en la Mesa,
  «Carla Demo»; con `subir` sube un archivo a una tarjeta como el sindicato). No pisa las capturas `01` a `56`: se corre sobre una base
  descartable (`createdb -T mitrabajo mitrabajo_tut5`, `alembic upgrade head`) con `DATABASE_URL` apuntando a ella y el servidor normal
  (`MOCK_EXTRACTOR=1 ENTORNO=local uvicorn main:app --port 8765`). Sobre un proyecto nuevo: pide la lista de seccionales (EST-01) enlazada a
  PE0001, el sindicato sube `seccionales-tutorial.csv`, se muestran el aviso, la lista, «Usar este archivo» y el botón de la carga; después
  se confirma REC-01 y en Hitos salen para marcar HI0021 (REC-01) y HI0026 (REC-04 y REC-05, que ya estaban hechas en la demo). La figura `61`
  (ensayo) se filmó y se descartó. Ahora son 26 pasos y 65 figuras; JPEG a calidad 50 y las figuras 58 y 63 a 65 en ancho `med` para quedar
  bajo 6 MB (5,96 MB). Borrar la base descartable al terminar. La miniatura no se regeneró.
