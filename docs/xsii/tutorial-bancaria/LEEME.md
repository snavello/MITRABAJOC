# Tutorial «XSII para implementar La Bancaria» (contenido)

- `paginas.json`: 14 páginas (`id`, `titulo`, `bajada`, `parrafos`, `pasos`, `tips`, `figuras` con `archivo` y `pie`, `palabras`).
- `img/`: 24 capturas reales (1280 px de ancho, escala 1, JPEG calidad 70; las de pantalla larga van recortadas). Los
  círculos numerados de las capturas son los `(1)`, `(2)` de los pies.
- `capturar.js`: filma todo contra un servidor local. Llama a `preparar.py` y ejecuta las acciones de verdad.
- `preparar.py`: arma, sobre la base DESCARTABLE, el sindicato «La Bancaria» (alta y conceptos de `cargar_bancaria.py`, sin
  el lote, sin el administrador de demo y solo con los tres aportes de ley, como un sindicato recién dado de alta), el usuario
  de plataforma «Sofía Demo», el proyecto «La Bancaria» de la Mesa con los 45 hitos semilla y la usuaria del sindicato
  «Carla Demo». Con `subir PID CODIGO ARCHIVO` sube un archivo a una tarjeta como el sindicato.
- `unir.py`: apila dos capturas en una. `servidor_recibos.py`: servidor con lectura simulada (empleadores bancarios
  inventados). `datos/` (planillas de `docs/xsii/ejemplos/`) y `recibos/` (imágenes vacías: solo importa el nombre).

## Rehacer las capturas (una base nueva cada vez: la corrida escribe de verdad)

```
export PGPASSWORD=postgres DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mitrabajo_tutbanc \
  SESSION_SECRET=descartable PLATAFORMA_PASSWORD=descartable ENTORNO=local
psql -h localhost -U postgres -c "CREATE DATABASE mitrabajo_tutbanc"
.venv/bin/python -m alembic upgrade head && .venv/bin/python cargar_marca_plataforma.py
TUTORIAL_LATENCIA=2 .venv/bin/python docs/xsii/tutorial-bancaria/servidor_recibos.py 8766 &   # lectura simulada
NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers PGUSER=postgres PGHOST=localhost \
  XSII_URL=http://localhost:8766 node docs/xsii/tutorial-bancaria/capturar.js     # ~90 s
psql -h localhost -U postgres -c "DROP DATABASE mitrabajo_tutbanc WITH (FORCE)"       # al terminar
```

La corrida imprime `AVISOS: []` si todas las marcas se encontraron. Todo es sintético: ninguna persona real.

## Cosas a saber

- Las capturas muestran la lectura de recibos simulada (`MOCK_EXTRACTOR=1`) y «Preguntame» con respuesta simulada: lo dicen en pantalla.
- Las cifras de los pies (30 filas del padrón, 27 en el sistema, -3 de diferencia, 17 conceptos, 9 seccionales) dependen de
  `datos/` y de `servidor_recibos.py`; si cambian, hay que ajustar `paginas.json`.
- `paginas.json` se generó a mano; cualquier cambio de texto de pantalla (botones) hay que verificarlo contra la pantalla real.

## Armar la página

`python docs/xsii/tutorial-bancaria/armar.py <carpeta>` escribe `xsii-bancaria.html` y copia `img/`. Se publica como artefacto con la base de datos prendida: cada página termina con una caja de opinión que se guarda en la colección `opiniones` (un documento por página, más `general`).
