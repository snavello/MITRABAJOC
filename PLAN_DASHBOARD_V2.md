# PLAN_DASHBOARD_V2.md — Panel Sindical v2 con Preact, en paralelo

**Estado:** propuesta del 2026-10-12, **a acordar con SDN decisión por
decisión** antes de tocar código. Sale de la conversación de ese día: se
evaluó React para mejorar la estética y lo que la interfaz puede ofrecer, y se
eligió **Preact sin build** para un primer piloto (§2, D1).

---

## 0. Qué se quiere y qué no

**Qué se quiere.** Probar con una pantalla real si una capa de componentes
mejora la estética y lo que la interfaz puede ofrecer, **sin arriesgar el
panel que hoy se usa en las demos**. La v2 nace en una ruta aparte, convive
con la v1 y solo la reemplaza si demuestra que da lo mismo (o más) con los
mismos números.

**Por qué el Panel Sindical.** Es la pantalla que mejor se presta:
- Tiene página propia (`templates/dashboard.html` + `static/dashboard.js`,
  1.613 líneas).
- Todos sus datos llegan como JSON de `/admin/dashboard/*`. El propio JS lo
  dice: "acá no se calcula nada de negocio, solo se pinta".
- Su complejidad está justo donde los componentes ayudan: filtros cruzados,
  pestañas, modales y una tabla paginada, todo sobre un mismo estado.

**Por qué Preact sin build.**
- Se vendorea en `static/` como Chart.js y Leaflet: nada de Node en el
  deploy, nada de CDN, y la CSP actual alcanza.
- El archivo que corre es el mismo que se lee, así que los tests sobre el
  código y `mapa_funcional.py` siguen viéndolo.
- Pesa unos 5 KB.
- Pasar a React más adelante es barato: es la misma API.

**Fuera de alcance.**
- Cualquier otra pantalla (`admin.html`, `trabajador.html`, Encuestas).
- TypeScript y paso de build.
- Cualquier cambio de backend (§1, línea roja 1).
- Funcionalidad nueva del panel: el piloto prueba la herramienta, no el
  producto.

---

## 1. Líneas rojas

1. **El backend no se toca.** Ni `dashboard.py`, ni los endpoints
   `/admin/dashboard/*`, ni su cupo, ni sus permisos. Si la v2 necesita un dato
   que hoy no viene, se anota y se decide aparte; nunca se agrega de pasada.
2. **La v1 no se toca durante el piloto.** Ni su plantilla, ni su JS, ni su
   ruta. La única excepción es el enlace de D6, y solo si se acuerda. Mientras
   dure el piloto, la v1 recibe solo arreglos (D10).
3. **Mismo contrato con el servidor que la v1.**
   - Los mismos parámetros en la URL: un enlace de la v1 abre igual en la v2
     cambiando solo la ruta.
   - Lo mismo que ya hace la v1: la cola de a 4 pedidos, el reintento ante un
     503, el 403 que lleva a `/admin`, el 422 visible y la fecha de hoy que
     manda el servidor (inventario en §3).
4. **Nada externo.** Todo vendoreado y con sello `?v=`, **también lo que se
   carga por `import`** (D3).
5. **Nada de HTML armado como texto.** Preact escapa todo lo que pinta; en la
   v2 quedan prohibidos `innerHTML` y `dangerouslySetInnerHTML`, y un test lo
   verifica. Es una mejora sobre la v1, que arma HTML con `esc()` y
   `innerHTML`.
6. **Las reglas visuales vigentes no se discuten acá.**
   - La marca del sindicato y `--destacado` solo para lo seleccionado.
   - El encabezado común (`_encabezado.html`), la mesa y la franja.
   - El título con `titulo-pagina`.
   - La skill `diseno-mi-trabajo` manda.

---

## 2. Decisiones a acordar

Cada una con la recomendación. Se cierran con SDN antes del bloque 1.

**D1. Librería: Preact + hooks + htm, sin build.** `htm` permite escribir las
plantillas en JavaScript común (`` html`<div class=${x}>` ``) en lugar de JSX,
así que no hace falta compilar nada.
*Recomendación: sí. Ya conversado.*

**D2. Versiones: Preact 10.29.8 y htm 3.1.1.**
- **Preact 10.29.8:** del 2026-08-01, la última de la rama 10, que es madura.
- **Preact 11:** la 11.0.0 salió el 2026-09-30 y la 11.0.1 el 2026-10-08.
  Es demasiado nueva para estrenar una herramienta; se evalúa al cerrar el
  piloto.
- **htm 3.1.1:** es estable desde 2022.
- Licencia MIT las dos.
- Se vendorean los módulos ES oficiales de cada paquete (`preact.module.js`,
  `hooks.module.js`, `htm.module.js`), **no** el `htm/preact/standalone`: ese
  trae adentro una copia vieja de Preact.

*Recomendación: esas versiones, fijas.*

**D3. Cómo se cargan los módulos: un `importmap` armado por el servidor, con
sello por archivo.**

El problema es la regla del sello. Un `import "./filtros.js"` sale sin `?v=`
y queda cacheado una hora: la pantalla vería el módulo viejo con el nuevo.

La solución:
- El código de la v2 importa por nombre (`import ... from "panel/filtros"`).
- La plantilla emite un `<script type="importmap">` que traduce cada nombre a
  `/static/panel_v2/filtros.js?v=<sello>`.
- Un helper de `main.py` arma el mapa **recorriendo la carpeta**: un archivo
  nuevo entra solo y no hay lista que olvidar.
- Un test exige que todo `import` de `static/panel_v2/` resuelva a una
  entrada del mapa.

Funciona con la CSP de hoy (`script-src 'self' 'unsafe-inline'`). Los
`importmap` andan en todos los navegadores actuales, desde Safari 16.4 de
2023.

*Recomendación: sí.*

**D4. Dónde vive y quién la ve: `/admin/dashboard-v2`, solo en local y en
Pruebas durante el piloto.**
- Mismo control de acceso que la v1: sesión de sindicato, módulo `dashboard`
  y permiso de la sección `dashboard`.
- En demo y prod responde **404**, con la misma regla que `/entornos`
  (`entorno.muestra_distintivo`).
- Se suma a `RUTAS_ADMIN_SIN_PERMISO` por la misma razón que `/admin/dashboard`:
  es una pantalla que valida sola y no expone datos, porque los datos salen de
  los endpoints, que ya tienen su control. `test_areas_rutas.py` fija ese
  conjunto exacto y se actualiza con el motivo escrito.

*Recomendación: sí.*

**D5. Estética: ¿copia exacta o se mejora?**
- **Paridad obligatoria de DATOS y COMPORTAMIENTO:** los mismos números para
  los mismos filtros y las mismas reglas de §3.
- **La estética puede mejorar a partir del bloque 3,** dentro del sistema de
  diseño.
- Antes del bloque 3 se arma **un mockup** de la dirección visual en
  `disenos/` (fuera de git, como los demás) y se acuerda con SDN. Si no, las
  mejoras se improvisan pantalla por pantalla.

*Recomendación: así.* Si el piloto solo replicara la v1, no respondería la
pregunta de fondo: si esto mejora la interfaz.

**D6. Enlace entre versiones, solo en Pruebas.**
- La v1 muestra un enlace chico, "Probar la versión nueva", que lleva los
  mismos filtros.
- La v2 muestra "Volver a la versión actual".

Es el único cambio a la v1: una línea de plantilla, condicionada al
distintivo de entorno.

*Recomendación: sí.* Es lo que hace cómoda la comparación. La alternativa es
cambiar la ruta a mano en la barra del navegador.

**D7. CSS: una copia propia, no compartida.**
- Los estilos del panel viven hoy en un `<style>` de unas 380 líneas dentro
  de `dashboard.html`.
- La v2 arranca con una **copia** en `static/panel_v2/panel.css`, con sello.
  Así mejorar la v2 no mueve la v1.
- Si la v2 reemplaza a la v1, la copia queda como la única.

*Recomendación: sí.*

**D8. Estado: un solo `useReducer` con el mismo objeto que la v1.**
- Es el objeto `S` de `dashboard.js`, con las mismas reglas de saneo de
  `estadoDeParams`.
- Sin Signals ni librerías de estado.
- Espera antes de pedir (debounce): **400 ms, como hace hoy el código**.
  `docs/DASHBOARD.md` dice 250, pero se subió en el arreglo del cuelgue del
  2026-09-18; manda el código.

*Recomendación: sí.*

**D9. Cuándo la v2 reemplaza a la v1.**

Tienen que darse las cuatro condiciones:
1. El robot de paridad (bloque 0) da los mismos números en todas sus
   combinaciones de filtros.
2. Los tests de la v2 y los de siempre están en verde.
3. SDN la usó en Pruebas y la aprueba.
4. No es más lenta ni más pesada que la v1: tiempo hasta ver los KPIs y peso
   del JS transferido.

Los resultados posibles son tres:
- **Reemplazar** (§5, bloque 7).
- **Seguir conviviendo.**
- **Descartar:** se borran la ruta, la plantilla y `static/panel_v2/` sin
  dejar rastro.

**D10. Durante el piloto, la v1 recibe solo arreglos.**
- La funcionalidad nueva del Panel espera o va directo a la v2.
- Si hace falta en la v1 (por una demo), va a las dos en el mismo PR.

Dos versiones que se separan en silencio es el riesgo más caro del piloto.

*Recomendación: sí.*

---

## 3. Lo que hay que portar (inventario de la v1)

### 3.1 Las reglas que no se ven

Son las que costaron un incidente cada una. Todas tienen que estar en la v2,
y cada una con su test.

| Regla | Dónde está en la v1 | Por qué existe |
|---|---|---|
| La fecha de hoy la dice el servidor (`data-hoy`), nunca `new Date()` | `HOY` | Un dispositivo adelantado pedía "mañana" y recibía un 422 sin aviso (2026-09-13) |
| A lo sumo 4 pedidos a la vez; los contadores de las pestañas inactivas, después | `enCola`, `MAX_EN_VUELO`, `refrescar` | El cuelgue de Pruebas del 2026-09-18; el cupo del servidor es de 4 |
| Un 503 se reintenta dos veces (700 y 1.500 ms) | `pedir`, `ESPERA_503_MS` | El servidor dice "estoy ocupado", no que el pedido esté mal |
| Un 403 lleva a `/admin` | `pedir` | Sesión vencida o permiso quitado |
| El motivo de un 422 se muestra arriba de los KPIs y en cada panel | `avisoDeError`, `cargarPanel` | Antes el panel quedaba en "—" sin decir por qué |
| Cada ronda tiene su `AbortController`; una tarea en espera no arranca si la ronda ya se abortó | `refrescar`, `cargarEnCola` | No gastar un lugar del servidor en algo que nadie va a ver |
| Espera de 400 ms antes de pedir | `cambio` | Ráfagas de filtros |
| URL compartible con los mismos parámetros; el saneo descarta fechas futuras, `desde` mayor que `hasta` y valores fuera de lista | `paramsDeEstado`, `estadoDeParams` | Enlaces entre dirigentes; una URL editada a mano no puede romper el panel |
| Salario en miles; `sal_min`/`sal_max` viajan solo si difieren de los límites | `paramsDeEstado`, `LIM` | Contrato de `dashboard.parsear_filtros` |
| El afiliado viaja por id, nunca por CUIL; su búsqueda tiene su propio abort | `S.afiliado`, `initAfiliado` | Privacidad |
| Consultas al bot y Asistente existen solo si el servidor los manda (`data-consultas`, `data-asistente`) | `CONSULTAS_ON`, `ASISTENTE_ON` | La bandera la decide el servidor |
| El historial del Asistente vive en memoria, nunca en `localStorage` | `ASIST_HIST` | Privacidad |
| Se respeta `prefers-reduced-motion` | `REDUCIR` | Accesibilidad |
| `--destacado` solo para lo seleccionado | CSS + `C` | DASHBOARD.md §4.1, regla visual absoluta |
| Tocar un gráfico filtra y cambia la pestaña del explorador a su fuente | `irATab` y cada `pintar*` | DASHBOARD.md §4.4 |
| El mapa ignora su propio filtro de seccional y la burbuja es el selector; usa `MapaMT.burbuja` y `MapaMT.ESCALA` | `pintarMapa`, `alternarSeccional` | Los dos mapas de tablero dibujan la misma burbuja |
| Los modales se arrastran (`modales.js`, familia `modal-det`) | `abrirModal` | `test_modales.py` |

### 3.2 Las piezas: de funciones de la v1 a componentes de la v2

| Pieza | Funciones de la v1 | Componente de la v2 |
|---|---|---|
| Período: atajos y calendario pintable | `pintarCalendario`, `setPreset`, `presetActivo` | `<Periodo>` |
| Seccionales y empresas (selección múltiple) | `pintarMultiChips` | `<Pastillas>` |
| Formato de recibo, salario (control de dos extremos) | `pintarSlider`, `pintarControles` | `<Segmentado>`, `<RangoSalario>` |
| Afiliado (buscador) | `initAfiliado`, `elegirAfiliado`, `etiquetarAfiliado` | `<BuscadorAfiliado>` |
| Filtros activos y Reiniciar | `pintarChips`, `reiniciar` | `<FiltrosActivos>` |
| 10 KPIs | `pintarKPIs`, `setKpi` | `<Kpi>` ×10 |
| 7 gráficos | `crearCharts`, `pintarLinea`, `pintarDona`, `pintarTramites`, `pintarNotif`, `pintarEmpresas`, `pintarBot`, `pintarFormato` | `<Grafico>` (envuelve Chart.js) + uno por panel |
| Semáforo por empresa | `pintarSemaforo` | `<Semaforo>` |
| Mapa de seccionales | `initMapa`, `pintarMapa`, `popupMapa`, `pintarLeyendaMapa`, `pintarSinUbicar` | `<MapaSeccionales>` (envuelve Leaflet + `MapaMT`) |
| Explorador: pestañas, tabla, "Ver más", contadores | `TABLAS`, `pintarTabla`, `irATab`, `verMas` | `<Explorador>` |
| Modal "Ver": recibo, trámite, notificaciones, destinatarios, consulta | `abrirModal`, `htmlRecibo`, `htmlTramite`, `htmlNotifs`, `verDestinatarios`, `htmlConsulta`, `verDetalle` | `<Detalle>` |
| Asistente y dictado por voz | `asist*`, `initAsistente`, `initVoz`, `voz*` | `<Asistente>` |
| Panel con carga, error y reintento | `cargarPanel`, `panelDe` | `<Panel>`: un solo lugar para los tres estados |

Chart.js, Leaflet, `mapa.js` y `modales.js` se reusan **tal cual**, como
scripts comunes que dejan sus globales. `<Grafico>` y `<MapaSeccionales>`
crean la instancia al montarse y la destruyen al desmontarse.

---

## 4. Archivos

```
templates/dashboard_v2.html      cáscara: encabezado común, mesa, data-*, importmap, <div id="panel">
static/panel_v2/panel.css        copia de los estilos de la v1 (D7)
static/panel_v2/app.js           raíz: arma el árbol y lo monta
static/panel_v2/estado.js        PURO: estado inicial, reducer, desde/hacia la URL
static/panel_v2/api.js           pedir (403/422/503), cola de a 4, espera abortable
static/panel_v2/filtros.js       Periodo, Pastillas, Segmentado, RangoSalario, BuscadorAfiliado, FiltrosActivos
static/panel_v2/kpis.js
static/panel_v2/graficos.js      Grafico + los siete paneles
static/panel_v2/mapa_secc.js     (no "mapa.js": ya existe static/mapa.js)
static/panel_v2/explorador.js
static/panel_v2/detalle.js
static/panel_v2/asistente.js
static/vendor/preact/            preact.module.js, hooks.module.js, htm.module.js, LICENSE, ORIGEN.md
```

`ORIGEN.md` de la carpeta vendoreada dice versión, URL de descarga, fecha y
el SHA-256 de cada archivo. Un test compara los SHA-256, así que reemplazar
la librería sin dejar registro hace fallar la suite.

`estado.js` y `api.js` no tocan el DOM, así que **Node los importa y los
prueba de verdad**. Hoy `test_dashboard_cola_front.py` tiene que extraer
`enCola` con una expresión regular, porque la v1 es una función que se
ejecuta sola y no se puede importar. Node 22 está en las sesiones de Code en
la nube y en los runners de GitHub; sin Node el test se saltea, como hoy.

---

## 5. Bloques

Cada bloque va en su propia rama y su propio PR, y se puede mergear solo:
la v2 es invisible en demo, así que mergear un bloque a medias no expone
nada. Admin sube de versión según la regla 3 de `FLUJO.md`.

**Bloque 0 — Línea de base. Sin código de la v2. Chico.**
- §3 pasa a ser la lista de verificación del piloto.
- Un robot de Playwright (`e2e/test_paridad_dashboard.py`) abre la v1 con
  6 combinaciones de filtros sobre el lote UOM y anota KPIs, contadores del
  explorador y totales de cada panel.
- En el bloque 7 el mismo robot abre la v2 y compara.
- Capturas de la v1 para el mockup de D5.

**Bloque 1 — Andamio. Chico.**
- Vendorear Preact y htm con su `ORIGEN.md`.
- El helper del `importmap` (D3).
- La ruta `/admin/dashboard-v2` con su control de acceso y 404 en demo (D4).
- La plantilla con encabezado, mesa y marca, y un panel vacío que muestra la
  fecha de hoy recibida del servidor: prueba de punta a punta de que el
  andamio funciona.
- `mapa_funcional.py` aprende a seguir el `importmap` (hoy solo sigue
  `<script src>`).
- Tests:
  - Ruta: sin sesión va al login; sin módulo o sin permiso, a `/admin`; en
    demo, 404.
  - `importmap` completo y todo con sello.
  - Prohibición de `innerHTML`.
  - SHA-256 de los archivos vendoreados.
  - `test_areas_rutas.py`, `test_mapa_funcional.py` y `test_modales.py`
    actualizados con el motivo.

**Bloque 2 — Núcleo sin pantalla. Medio.**
- `estado.js` y `api.js`.
- Tests con Node:
  - Ida y vuelta por la URL contra los mismos parámetros que arma la v1.
  - El saneo de §3.1.
  - La cola nunca pasa de 4.
  - El 503 se reintenta y el 403 redirige.
  - Una ronda abortada no lanza tareas.

**Mockup de D5, antes del bloque 3.** Se acuerda con SDN.

**Bloque 3 — Filtros y KPIs. Medio. Primer resultado visible.**
- Período con calendario, pastillas, formato, salario, afiliado, filtros
  activos y Reiniciar, más los 10 KPIs.
- **Punto de control:** SDN lo mira en Pruebas y decide si el piloto sigue.
  Hasta acá el costo es chico y ya se ve cómo se escribe y cómo se ve.

**Bloque 4 — Gráficos, filtrado cruzado y mapa. Grande.**
- `<Grafico>` sobre Chart.js y los siete paneles.
- El clic que filtra y cambia la pestaña.
- El semáforo y el mapa con `MapaMT`.

**Bloque 5 — Explorador y modal "Ver". Medio.**

**Bloque 6 — Asistente y voz. Medio.**

**Bloque 7 — Paridad y decisión (D9). Chico, más el reemplazo si toca.**
- Robot de paridad completo sobre la v2.
- Medición de peso y tiempo contra la v1.
- Uso de SDN en Pruebas.

Si la decisión es **reemplazar**:
- `/admin/dashboard` sirve la v2.
- La v1 queda 30 días en `/admin/dashboard-v1` como salida de emergencia y
  después se borra.
- `test_dashboard_cola_front.py` se reescribe sobre los módulos.
- Se actualizan `docs/DASHBOARD.md` (§4) y `CLAUDE.md`.
- La v2 llega a la demo con la siguiente promoción.

---

## 6. Riesgos y cómo se cubren

| Riesgo | Cobertura |
|---|---|
| La v2 muestra números distintos a la v1 | Mismos endpoints sin cambios (línea roja 1) + robot de paridad (bloques 0 y 7) |
| La v2 satura el servidor como en septiembre | `api.js` con la misma cola y el mismo reintento, probados con Node (bloque 2) |
| Pantalla nueva con módulo viejo en caché | `importmap` con sello por archivo y test (D3) |
| Alguien cambia la librería vendoreada sin decirlo | `ORIGEN.md` + test de SHA-256; se registra en XSK, eje ENT |
| Las dos versiones se separan | D10: la v1 solo recibe arreglos |
| El piloto no convence | Punto de control en el bloque 3; descartar es borrar una ruta y una carpeta |
| Un error de plantilla aparece recién al abrir la página (no hay compilación) | Robot e2e que abre la v2 en cada bloque; con build se detectaría antes, y es parte de lo que el piloto mide |

---

## 7. Documentación al cerrar cada bloque

- Lo de siempre: una línea en `BITACORA.md` + `generar_bitacora.py`,
  "Estado actual" de `CLAUDE.md` y la narrativa en `HISTORIAL.md`
  ("Panel Sindical v2").
- `docs/DASHBOARD.md` se toca recién al reemplazar: mientras conviven, la
  especificación de la v1 sigue siendo la vigente.
