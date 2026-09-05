# Asistente del Panel Sindical

**Ficha rectora, vigente al 2026-09-05.** Diseño acordado con Sd para el
asistente en lenguaje natural del Panel Sindical. Cuando algo de acá cambie,
se actualiza ESTA ficha (no se anota en otro lado); la narrativa de cómo se
construyó va a `HISTORIAL.md`. Rama: `feature/asistente-panel`.

## 0. Qué es y qué no es

Un cajón de chat dentro de `/admin/dashboard` donde el admin de sindicato
pregunta como habla ("quiero las notificaciones no leídas de la sucursal
Rosario") y el asistente:

1. traduce la pregunta a los filtros que el panel YA tiene,
2. los aplica (el tablero entero cambia y el explorador muestra los casos),
3. contesta en una o dos frases con los números reales del panel.

- **No es RAG**: no lee documentos, no usa embeddings ni el módulo
  `convenio`. Solo necesita la API de Anthropic, la misma del extractor.
- **No es el bot del convenio del trabajador** (`ConsultaConvenio`, panel
  "Consultas al bot" del dashboard): son cosas distintas, no comparten
  tabla ni código. Por eso se llama "Asistente del Panel", nunca "bot".
- **No genera SQL y no ve filas.** Al modelo le llegan nombres de
  seccionales y empresas, la pregunta tal cual la escribió el admin y
  totales agregados. Nunca CUIL ni nombres de trabajadores.
- **La sintaxis cerrada está en la salida, no en la entrada.** El admin
  escribe (o dicta) libre; el modelo resuelve sinónimos, errores de tipeo
  y fechas relativas. Lo único rígido es lo que el panel puede filtrar.

## 1. Decisiones tomadas (no re-preguntar)

- **Modelo `claude-sonnet-5`** (Sd, 2026-09-05). Es más barato que el
  `claude-sonnet-4-6` del extractor. Thinking adaptativo con
  `output_config={"effort": "low"}`, `max_tokens` 1024.
- **Sin módulo nuevo: es una mejora del Panel Sindical** (Sd, 2026-09-05).
  Todo sindicato con `"dashboard"` lo tiene. Gate en el backend con
  `_exigir_dashboard_detalle`, el mismo del explorador: cuando exista la
  diferenciación STD/PRO, el Asistente queda del lado PRO cambiando solo ese
  helper.
- **La única fuente de verdad de lo que se puede filtrar es
  `dashboard.parsear_filtros`.** El asistente no agrega filtros nuevos al
  panel. Si el panel no filtra algo, lo dice ("eso el tablero no lo filtra")
  y no inventa. Misma lección que la baranda del RAG: el control real es el
  prompt, no un umbral.
- **La herramienta devuelve SIEMPRE el estado completo**, nunca un delta:
  así "sacá el filtro de empresa" o "ahora solo agosto" funcionan sin
  lógica de merge en el servidor.
- **Historial corto**: los últimos 4 intercambios viajan en cada pedido,
  en memoria del navegador (no `localStorage`).
- **Tope de 300 preguntas por sindicato por día**, constante en v1
  (`asistente.TOPE_DIARIO`); pasa a `ConfiguracionPlataforma` solo si hace
  falta.
- **Voz con la Web Speech API del navegador**, costo cero. El texto
  reconocido se muestra en la caja y el admin confirma con Enter (el
  dictado se equivoca con nombres propios). Sin transcripción en servidor
  en v1. Botón oculto donde no hay `SpeechRecognition` (Firefox).
- **La API key es la misma `ANTHROPIC_API_KEY`.** Sin clave, el botón no
  aparece y el endpoint responde 503.

## 2. Contrato del endpoint

`POST /admin/dashboard/asistente` — sesión de admin de sindicato + módulos
`dashboard` y `dashboard_asistente`. El `sindicato_id` sale de la cookie,
jamás del body.

Pedido (JSON):

```json
{
  "pregunta": "notificaciones no leidas de rosario",
  "filtros": {"desde": "2026-08-06", "hasta": "2026-09-05", "seccionales": [],
              "empresas": [], "formato": "", "resultado": "", "estado_tramite": "",
              "tipo_notif": "", "sal_min": null, "sal_max": null, "tema": "",
              "tab": "recibos"},
  "historial": [{"pregunta": "...", "respuesta": "...", "filtros": {"...": "..."}}]
}
```

`filtros` es el estado actual del panel, con las mismas claves que
serializa `paramsDeEstado()` en `dashboard.js` más `tab`. `historial` lleva
hasta 4 intercambios previos.

Respuesta (JSON):

```json
{
  "respuesta": "Rosario tiene 37 notificaciones sin leer de 210 enviadas en el período.",
  "filtros": {"desde": "2026-08-06", "hasta": "2026-09-05", "seccionales": [4],
              "empresas": [], "formato": "", "resultado": "", "estado_tramite": "",
              "tipo_notif": "", "sal_min": null, "sal_max": null, "tema": "",
              "tab": "notificaciones"},
  "aplicar": true
}
```

`aplicar=false` y `filtros=null` cuando el asistente repregunta (ambigüedad)
o dice que no puede.

Errores: 403 sesión/módulo; 422 pregunta vacía o de más de 500 caracteres;
429 tope diario (Bloque 3); 503 sin API key; `E-ASISTENTE-01` (502, en
`errores.py`) si la API de Anthropic no responde. El detalle real de la
excepción va al log del servidor, nunca al admin.

## 3. Cómo se arma la llamada (`asistente.py`, módulo nuevo)

**System prompt**, estable por sindicato, con `cache_control` ephemeral:

- Rol y reglas: castellano rioplatense, 1 o 2 frases, sin listar personas,
  no inventar. Si la pregunta no se puede expresar con los filtros, decirlo
  y NO llamar la herramienta. Si es ambigua (ej. "Rosario" es una seccional
  y también parte del nombre de una empresa), repreguntar.
- Fecha de hoy, `RANGO_MAXIMO_DIAS`, regla de que "hasta" no es futuro.
- Catálogo del sindicato: seccionales (id, nombre), empresas (id, nombre,
  CUIT), valores fijos de cada filtro.
- Glosario del gremio: seccional = sucursal / delegación / filial;
  sin leer = no leídas / pendientes de lectura; recibo = boleta /
  liquidación / recibo de sueldo; empresa = empleador / patronal / firma;
  con diferencias = mal liquidados / con errores; formato nuevo = Anexo III
  / reforma; trámite = expediente / gestión / reclamo.
- Qué mide cada pestaña y qué NO se puede: "no leídas" es una métrica
  (columna "sin leer" del explorador de Notificaciones), no un filtro; no
  hay filtro por persona ni por CUIL.

**Herramienta `fijar_filtros`** (`strict: true`, `additionalProperties:
false`): `desde`, `hasta`, `seccionales[]`, `empresas[]`, `formato`,
`resultado`, `estado_tramite`, `tipo_notif`, `sal_min`, `sal_max`, `tema`,
`tab`, `motivo` (una frase, para el registro). Espejo exacto de
`parsear_filtros` + la pestaña.

**Bucle** (máximo 3 vueltas):

1. Llamada con `tools=[fijar_filtros]`, `tool_choice` auto.
2. Si hay `tool_use`: los ids que no estén en el catálogo del sindicato se
   descartan (aislamiento, además del `WHERE` por `sindicato_id` que ya
   existe); se valida con `parsear_filtros`. Si falla, `tool_result` con
   `is_error` y el MISMO mensaje que ve el JS, y el modelo corrige.
3. Si valida: se calculan `kpis()` + el agregado de la pestaña
   (`notificaciones()` / `validacion()` / `tramites_seccional()` /
   `consultas_por_tema()`) y se devuelven como `tool_result` (solo números y
   nombres de seccional/empresa).
4. El texto final del modelo es la `respuesta`.

**Registro** en la tabla `consulta_asistente`: id, sindicato_id, usuario_id,
pregunta, respuesta, filtros (JSON/JSONB), tab, aplicado, modelo,
tokens_entrada, tokens_salida, creado_en. Índice `(sindicato_id,
creado_en)`. Sirve para el tope diario, para auditar y para armar el set de
frases de prueba con preguntas reales.

## 4. Frontend (`templates/dashboard.html` + `static/dashboard.js`)

- Botón "Asistente" en la barra del panel, solo si `ASISTENTE_ON` (módulo
  habilitado + API key presente), mismo patrón que `CONSULTAS_ON`.
- Cajón lateral con estética del panel: burbujas, caja de texto, botón
  enviar, botón micrófono (oculto sin `SpeechRecognition`), estado
  "pensando".
- `estadoDeUrl()` se parte en `estadoDeParams(q)` para reutilizarlo con los
  filtros de la respuesta; después `urlCompartible()` + la ronda de fetches
  de siempre + cambio de pestaña del explorador. El link compartible sale
  gratis.
- Cada respuesta con filtros aplicados muestra un chip "filtros aplicados"
  con "volver" al estado anterior.

## 5. Pruebas

- `test_asistente.py` (SQLite, sin API): cliente de Anthropic falso
  inyectado. Casos: `tool_use` válido → filtros + respuesta + fila en la
  tabla; fecha futura → reintento con `is_error`; id de seccional ajena →
  descartado; sin módulo → 403; tope → 429; pregunta vacía → 422.
- **Set de aceptación del prompt**: `medicion_asistente/frases.json` (25
  frases con filtros esperados, escritas como habla un dirigente, con
  errores de tipeo incluidos) + `probar_asistente.py`, que las corre contra
  la API real y muestra esperado vs obtenido. Gasta créditos: se corre a
  mano cada vez que se toque el prompt o el modelo, nunca en CI.
- E2E: no se robotiza (mismo criterio que `/api/leer`).

## 6. Bloques de construcción

0. Esta ficha + corrección de CLAUDE.md. **HECHO 2026-09-05.**
1. Backend: `asistente.py`, endpoint `POST /admin/dashboard/asistente`,
   `E-ASISTENTE-01`, `test_asistente.py` con cliente falso (13 casos).
   **HECHO 2026-09-05.** Prueba de humo con la API real sobre la base del
   test: "quiero las notificaciones no leidas de la sucursal rosario" →
   seccional Rosario + pestaña Notificaciones + "se enviaron 3 y quedaron 2
   sin leer". 2 llamadas, 1.232 tokens de entrada y 518 de salida (menos de
   un centavo de dólar), **25 segundos**: la latencia es el punto a medir en
   el Bloque 5 (comparar `effort: low` contra thinking desactivado; objetivo
   menos de 8 s).
2. Frontend: cajón, aplicar estado, resumen, volver. **HECHO 2026-09-05.**
   Botón "Asistente" en el encabezado del panel + cajón lateral
   (`templates/dashboard.html`), `estadoDeUrl()` partido en
   `estadoDeParams(q)` + `aplicarEstado()` + `estadoPlano()` en
   `static/dashboard.js`. Verificado en el navegador contra la API real
   (servidor sobre la base SQLite de `test_asistente.py`, Docker apagado):
   diálogo de dos turnos ("notificaciones no leidas de la sucursal rosario"
   → Rosario + Notificaciones + "hoy: 0"; "si, ampliá a los últimos 30
   días" → mismo Rosario, 30 días, "3 enviadas, 2 sin leer"), chip
   "Filtros aplicados", "Volver" restaura el estado anterior y la URL
   compartible acompaña cada cambio. Sin errores de consola.
   **Observación para el Bloque 5**: el panel arranca en "Hoy", así que la
   primera pregunta sin período suele dar 0 y el modelo ofrece ampliar.
   Decidir si, con el panel en "Hoy" y sin período en la pregunta, el
   prompt debe ampliar solo a 30 días o seguir respetando el panel.
3. Filtro por afiliado en el panel (§9): vocabulario de filtros, reglas de
   privacidad, buscador, tabla de notificaciones por persona, 5 tests.
   **HECHO 2026-09-05**, verificado en el navegador (buscar "rosar", elegir
   a Juan Rosarino, chip + URL + KPIs + explorador por persona).
4. Asistente con `persona`: resolución en el servidor, candidatos en el
   cajón, prompt y set de frases con preguntas por persona.
5. Registro + tope diario + migración Alembic.
6. Voz (Web Speech API).
7. Set de frases con la API real, ajustes de prompt, versión,
   `HISTORIAL.md`, promover a demo.

Cada bloque se verifica en local (Docker + uvicorn + lote UOM) y se
commitea por separado, preguntando antes.

## 7. Costo estimado

Sonnet 5, catálogo cacheado: menos de US$ 0,01 por pregunta. Con 20
preguntas por día, entre US$ 3 y 6 por mes. Voz: US$ 0.

## 8. Fuera de alcance (v1)

- Preguntas de ranking ("qué empresa tiene más diferencias"): requiere
  pasarle al modelo el top-N de cada panel. Fácil de sumar después.
- Listar QUIÉNES no leyeron una notificación (personas): sigue siendo el
  modal "Ver" → destinatarios del explorador, no un filtro. Lo que sí hay
  desde el Bloque 3 es el camino inverso: elegir una persona y ver sus
  notificaciones (§9).
- Transcripción de voz en servidor (Firefox, calidad) y respuesta por voz.
- Permiso por usuario admin (llega con `areas-permisos`).

## 9. Filtro por afiliado (acordado con Sd, 2026-09-05)

Sd quiere preguntar "las notificaciones del afiliado Juan José Galmarini" o
"los recibos de Juan Pablo Pérez que trabaja en el banco Galicia". Para eso
el panel gana un filtro por persona y el Asistente lo usa. Reglas:

- **`afiliado=<id de Trabajador>`** en el vocabulario de filtros
  (`parsear_filtros`), nunca el CUIL: así la URL compartible no lo lleva.
  Un id ajeno o inexistente no matchea NADA (`_cuil_de_afiliado`, mismo
  criterio que `_cuits_de_empresas`).
- **Recibos: solo los que esa persona envió al sindicato**, también en
  totales, KPIs y semáforo (`_SOLO_ENVIADOS_DEL_AFILIADO`). Si el total
  incluyera los que verificó en privado, el KPI revelaría lo que la fila
  esconde. Con afiliado se listan TODOS sus enviados, no solo los
  observados: la pregunta es "qué mandó", no "qué está mal". Test:
  `test_afiliado_recibos_solo_los_enviados`.
- **Consultas al bot del convenio: el filtro no aplica** (son anónimas a
  propósito, sin CUIL ni nombre en explorador y detalle). Con afiliado, la
  fuente devuelve vacío y el KPI es `None`, no 0: un 0 afirmaría "esta
  persona no consultó". Test: `test_afiliado_no_aplica_a_consultas`.
- **Trámites y notificaciones sí aplican**: son datos que el sindicato
  generó o que el afiliado le inició. El explorador de notificaciones
  cambia de modo (`modo: "afiliado"`): una fila por notificación con
  leída/sin leer, en vez del agregado diario.
- **Buscador** `GET /admin/dashboard/afiliados?q=` (nombre o CUIL,
  tolerante a tildes, mayúsculas y orden de las palabras; `?id=` para
  etiquetar el chip de un link con `?afiliado=`). Gate del explorador:
  mirar a una persona es detalle. El matcheo fino va en Python sobre el
  padrón activo del tenant, porque un LIKE no ignora tildes ni en SQLite ni
  en Postgres sin extensiones; si un padrón enorme lo justifica, el paso
  siguiente es una columna `nombre_normalizado` indexada.
- **El padrón nunca viaja al modelo.** El nombre que escribe el admin sí,
  porque es su pregunta. El modelo entrega `persona` tal cual y, si la
  nombra, la empresa; el servidor resuelve con `buscar_afiliados(...,
  cuits=...)`: 0 → "no encontré"; 1 → aplica; varios → el cajón muestra
  los candidatos con seccional y empresa y el admin elige con un clic, sin
  pasar por el modelo (Bloque 4).
- **Bug encontrado de paso (corregido)**: `dashboard.js` se referenciaba
  con `?v={{ version }}` y no con `sello_static`, así que el navegador
  servía el JS viejo hasta una hora después de cada cambio, justo la regla
  de CLAUDE.md sobre `/static/`. Se notó porque el buscador nuevo "no
  respondía": el handler no existía en el archivo cacheado.
