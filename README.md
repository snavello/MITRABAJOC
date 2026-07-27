# Validador de recibos — PoC (versión demo)

Prototipo que permite a un trabajador escanear su recibo de sueldo desde el
celular, interpretarlo con IA y verificar que los aportes (sindical, obra
social, jubilación, PAMI) estén bien calculados según las fórmulas del convenio.

Esta es la **versión demo**: sin base de datos. Los datos de referencia viven en
`data/seed_aefip.json` y los reportes de los trabajadores se guardan en
`data/reportes.json`. Pensada para mostrar funcionalidades; el proyecto en serio
se rehace después con arquitectura robusta.

## Qué hay en cada archivo

- `chequeo.py` — autodiagnóstico de la instalación.
- `main.py` — el servidor y las rutas web (app del trabajador + panel admin).
- `extractor.py` — le pasa el recibo a la Claude API y recibe el JSON.
- `validador.py` — motor que matchea conceptos y evalúa las fórmulas.
- `data/seed_aefip.json` — conceptos y fórmulas del sindicato (editable a mano).
- `data/reportes.json` — reportes que elevan los trabajadores.
- `templates/trabajador.html` — pantalla móvil del empleado.
- `templates/admin.html` — panel del sindicato.

## Dónde se ejecuta todo

En **tu computadora**, en una terminal (PowerShell en Windows; Terminal en Mac/Linux).

---

## Paso 1 — Python
`python --version` (o `python3 --version`). Necesitás 3.11+. Si no está,
instalalo de python.org (en Windows tildá "Add Python to PATH").

## Paso 2 — Entorno e instalación
    cd validador-demo
    python -m venv .venv
    # Windows:
    .venv\Scripts\activate
    # Mac/Linux:
    source .venv/bin/activate
    pip install -r requirements.txt

Para leer PDFs hace falta poppler:
- Mac:    brew install poppler
- Ubuntu: sudo apt install poppler-utils
- Windows: descargar poppler y agregar su carpeta bin al PATH
  (o, para la demo, usar fotos JPG en vez de PDF y saltear poppler).

## Paso 2.5 — Verificar la instalación
    python chequeo.py

Revisa que todo esté en su lugar y te dice qué falta. Para probar también
la conexión con la API (consume créditos):  python chequeo.py --api

## Paso 3 — API key
    cp .env.example .env      # Windows: copy .env.example .env
Editá `.env` y pegá tu ANTHROPIC_API_KEY (se saca en console.anthropic.com).

## Paso 4 — Arrancar
    uvicorn main:app --reload

- App del trabajador:  http://localhost:8000
- Panel del sindicato: http://localhost:8000/admin

## Paso 5 — Ver la versión móvil sin celular
Abrí la app en Chrome, apretá F12, y activá el ícono de celular/tablet
(arriba a la izquierda del panel). Elegí "iPhone" o "Galaxy".

---

## Objetivo A — Que esté disponible en internet (para la demo en el sindicato)

La app corre en tu PC; un "túnel" la expone con un link público. En OTRA
terminal (dejá `uvicorn` corriendo en la primera):

    # Mac: brew install cloudflared
    # Windows: descargar cloudflared.exe de la web de Cloudflare
    cloudflared tunnel --url http://localhost:8000

Te imprime un link https://algo.trycloudflare.com que funciona desde cualquier
lado, con HTTPS (necesario para que la cámara del celular funcione).

El link cambia cada vez que reiniciás el túnel: generalo poco antes de la demo.
Todo el tráfico pasa por tu PC, así que necesitás buena conexión ese día.

Alternativa sin depender de tu conexión: subir el repo a GitHub y desplegar en
render.com (Web Service, comando `uvicorn main:app --host 0.0.0.0 --port $PORT`,
variable ANTHROPIC_API_KEY). Da un link .onrender.com fijo. Contra: en el plan
gratis la app "duerme" y tarda ~30s en despertar la primera vez, y el
reportes.json se reinicia (no persiste). Para una demo controlada, manejable.

## Objetivo B — App del trabajador optimizada para móvil

Ya resuelto en `templates/trabajador.html`: viewport sin zoom accidental, altura
correcta con la barra del navegador (100dvh), respeto del notch y la barra de
gestos (safe-area), botones de 52px cómodos para el dedo, cámara trasera directa,
y etiquetas para "Agregar a pantalla de inicio" (se instala como app).

---


## Poner el logo del sindicato

El encabezado de la app muestra, a la derecha, el logo del sindicato. Por
defecto hay un placeholder. Para poner el logo real:

1. Guardá la imagen del logo en la carpeta `static/`.
2. Renombrala a `logo_sindicato.svg` (o .png), reemplazando el placeholder.
3. Si es PNG en vez de SVG, editá `templates/trabajador.html` y cambiá
   `logo_sindicato.svg` por `logo_sindicato.png` en la línea del encabezado.

Formato ideal: horizontal, fondo transparente, alto de unos 40 px.

## El flujo del trabajador (dos pasos)

1. Elige el recibo y toca "Leer recibo" → la IA lo interpreta.
2. Ve un **preview** con los datos detectados (empleado, CUIL, empresa, CUIT,
   período, fecha de cobro y los conceptos con importes). Si el recibo trae
   conceptos que no están en el catálogo, se muestran aparte como "nuevos".
3. Toca "Continuar" → los conceptos nuevos se dan de alta como pendientes de
   revisión (no afectan el cálculo) y corre la verificación de fórmulas.

Los conceptos pendientes aparecen destacados en el panel `/admin` para que el
sindicato les asigne tipo y remunerativo.

## CHECKLIST DEL DÍA DE LA DEMO

### La noche anterior
- [ ] Corré la app y validá un recibo de prueba de punta a punta (que dé "Todo en orden").
- [ ] Probá también un recibo con un dato cambiado, para mostrar el caso rojo con reporte.
- [ ] Verificá que te queda saldo/créditos en la cuenta de Anthropic.
- [ ] Cargá bien la batería de la notebook y del celular.
- [ ] Anonimizá los recibos de prueba (tapá CUIL y nombre) si los vas a mostrar.

### 15 minutos antes
- [ ] Conectá la notebook a internet (probá que la conexión del sindicato ande, o usá tu datos móviles).
- [ ] Terminal 1: `uvicorn main:app --host 0.0.0.0 --port 8000`
- [ ] Terminal 2: `cloudflared tunnel --url http://localhost:8000`
- [ ] Copiá el link https que aparece y abrilo en tu celular. Confirmá que carga.
- [ ] Sacale una foto a un recibo desde el celular y verificá que valida bien.
- [ ] Abrí también /admin en la notebook para mostrar el panel del sindicato.

### Durante la demo
- [ ] Mostrá primero la pantalla del trabajador en el celular (es la estrella).
- [ ] Escaneá un recibo en vivo → mostrá el resultado "Todo en orden".
- [ ] Escaneá el recibo con el error → mostrá la discrepancia y tocá "Reportar al sindicato".
- [ ] Pasá a la notebook y mostrá el reporte recién llegado en /admin.
- [ ] Mostrá en /admin las tablas de conceptos y fórmulas (el "cerebro" configurable).

### Si algo falla
- [ ] La cámara no abre → asegurate de estar entrando por el link https (no http).
- [ ] "No pudimos leer el recibo" → probá con mejor luz o con el PDF en vez de la foto.
- [ ] El link no carga → reiniciá el túnel (Terminal 2) y usá el link nuevo.
- [ ] Todo se traba → tené a mano capturas de las pantallas como plan B.

### Después
- [ ] Cerrá el túnel (Ctrl+C en Terminal 2) para que el link deje de estar activo.
- [ ] Revisá data/reportes.json: quedaron guardados los reportes de la demo.
