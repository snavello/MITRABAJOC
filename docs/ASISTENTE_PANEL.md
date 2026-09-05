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
- **Voz con la Web Speech API del navegador**, costo cero. Lo dictado cae
  en la caja y **se envía solo tras una pausa de 4 segundos**, con cuenta
  regresiva a la vista; tocar el texto o escribir la cancela (Sd, tras
  probar en el celular, 2026-09-05: antes había que tocar "enviar" a
  mano). Sin transcripción en servidor en v1. Botón oculto donde no hay
  `SpeechRecognition` (Firefox).
- **Período cuando la pregunta no lo menciona** (Sd, 2026-09-05): si el
  panel está en "Hoy" (su arranque), el asistente se va solo a los últimos
  30 días y lo dice en la respuesta; nunca pregunta ni ofrece ampliar. Si
  el panel ya tiene otro período, lo conserva. "Hoy" explícito es hoy.
  Regla en el prompt, cubierta por tres frases del set de aceptación.
- **En el celular el cajón es una hoja inferior** (56% de alto, el panel
  queda a la vista arriba) que **se achica sola a una barra** con la última
  respuesta cuando aplica filtros, y también con "Ver en el explorador",
  "Volver" o el botón de achicar; tocar la barra la vuelve a abrir. Sd
  probó la versión anterior en vertical y el cajón tapaba todo: no se veía
  el panel cambiar y los botones parecían no hacer nada.
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
`persona`, `afiliado`, `tab`, `motivo` (una frase, para el registro).
Espejo exacto de `parsear_filtros` + la pestaña + la búsqueda de persona
(§9).

**Los textos opcionales de la herramienta van como `null`, nunca como
`""`.** Visto en la prueba real del Bloque 4: con `tema` y `persona` como
dos strings vacíos consecutivos, Sonnet 5 emitió basura de su propio
formato de llamada (`</antml_parameter>\n<parameter name="persona">`) en
esos campos, el servidor salió a buscar a esa "persona" y agotó las tres
vueltas. Dos defensas: los campos admiten `null` en el esquema y el prompt
lo pide así, y `asistente._texto_limpio()` descarta cualquier texto que
huela a etiqueta de herramienta (la salida del modelo no es un contrato,
misma regla que con el extractor). Test:
`test_basura_del_modelo_en_textos_cuenta_como_vacio`.

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
- Cada respuesta con filtros aplicados muestra un chip "Filtros aplicados",
  una nota fija "El detalle está abajo en el explorador de datos, pestaña
  X", un botón "Ver en el explorador" que baja hasta ahí y "Volver" al
  estado anterior. La nota va en el JS, no en el prompt: no depende de que
  el modelo se acuerde (pedido de Sd, 2026-09-05).

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
   **Observación** (resuelta en el Bloque 8): el panel arranca en "Hoy",
   así que la primera pregunta sin período daba 0 y el modelo ofrecía
   ampliar. Sd decidió que se vaya solo a 30 días (ver §1).
3. Filtro por afiliado en el panel (§9): vocabulario de filtros, reglas de
   privacidad, buscador, tabla de notificaciones por persona, 5 tests.
   **HECHO 2026-09-05**, verificado en el navegador (buscar "rosar", elegir
   a Juan Rosarino, chip + URL + KPIs + explorador por persona).
4. Asistente con `persona`: resolución en el servidor, candidatos en el
   cajón, prompt. **HECHO 2026-09-05**, 6 tests nuevos (19 en total) y
   verificado con la API real: "mostrame los recibos de juan rosarino" →
   dos candidatos en el cajón con CUIL, seccional y empresa; un clic aplica
   el filtro sin volver al modelo; "y sus notificaciones?" conserva al
   afiliado por id y contesta "2 enviadas, 1 sin leer". El set de frases
   con preguntas por persona queda para el Bloque 7.
5. Registro + tope diario + migración Alembic. **HECHO 2026-09-05**:
   tabla `consultaasistente` (`db.ConsultaAsistente`,
   `registrar_consulta_asistente`, `consultas_asistente_hoy`), tope en la
   ruta (429 antes de gastar una llamada), migración `b7c3d9e1f204`
   escrita a mano porque Docker estaba apagado: validada en modo offline
   (`alembic upgrade a9d4e7f2c831:b7c3d9e1f204 --sql` genera el DDL de
   Postgres con JSONB e índices) y después, con Docker levantado, corrida
   contra el Postgres local en las dos direcciones (`upgrade head`,
   `downgrade -1`, `upgrade head`): OK, 2026-09-05.
6. Voz (Web Speech API). **HECHO 2026-09-05**: botón de micrófono en el
   cajón (`initVoz` en `dashboard.js`), oculto donde no existe
   `SpeechRecognition`, `es-AR`, lo dictado cae en la caja y se confirma
   con Enter; rojo latiendo mientras escucha; aviso si el navegador negó
   el micrófono. En el navegador embebido se verificó que el botón aparece
   y cambia de estado; el dictado real hay que probarlo en Chrome con
   micrófono (pendiente de Sd).
7. Set de frases con la API real. **HECHO 2026-09-05**:
   `medicion_asistente/frases.json` (25 frases, con tipeo descuidado,
   sinónimos del gremio, períodos relativos, quitar/mantener filtros,
   personas, homónimos, CUIL, fuera de alcance) + `probar_asistente.py`
   (corre sobre el sindicato sintético de `test_asistente.py`, en
   paralelo, y compara con lo esperado; `--sin-thinking`, `--solo`,
   `--hilos`). Primera corrida 24/25: el modelo se negaba a buscar por
   CUIL ("primero necesito identificar a esa persona"); se aclaró en el
   prompt que un CUIL va en `persona` como un nombre. Después, 25/25 en
   las dos configuraciones. Registro de cada corrida en
   `medicion_asistente/corrida_*.json` (la última va a
   `ultima_corrida.json`, ignorado por git).

   | Configuración | Aciertos | Mediana | Máximo | Costo por pregunta |
   |---|---|---|---|---|
   | Esfuerzo bajo, thinking adaptativo (la real) | 25/25 | 6,8 s | 8,8 s | US$ 0,0065 |
   | Thinking desactivado | 25/25 | 7,0 s | 19,1 s | US$ 0,0066 |

   **Decisión: queda esfuerzo bajo.** Mismos aciertos y costo, máximo más
   parejo, y evita los modos de falla conocidos del thinking desactivado
   (la llamada a la herramienta escrita como texto). Los 25 s de la prueba
   de humo del Bloque 1 fueron un arranque en frío, no la latencia normal.
   Cierre con Docker levantado (2026-09-05): migración en las dos
   direcciones sobre el Postgres local, y una pregunta real contra los
   datos de demo de la UOM ("recibos con diferencias de la seccional
   Avellaneda en los ultimos 30 dias" → 26 recibos, $446.253 observados,
   8,7 s), registrada en `consultaasistente` y leída con `filtros->>'tab'`
   (JSONB). `buscar_afiliados("juan")` sobre el padrón real devuelve
   Juan Díaz, Juan Ruiz, Juan Gómez con seccional y empresa. Un ajuste
   salió de ahí: con el filtro de resultado puesto, el "% con diferencias"
   no viaja al modelo (da 100 por construcción y lo citaba como si fuera
   de la seccional). Mergeado a `main` y desplegado en Pruebas el
   2026-09-05 como Admin 0.29.01.
8. Ajustes tras la prueba de Sd en el celular, sobre Pruebas (2026-09-05,
   Admin 0.29.02): período por defecto de 30 días cuando la pregunta no lo
   menciona y el panel está en "Hoy" (antes preguntaba); lo dictado se
   envía solo tras 4 segundos de pausa, con cuenta regresiva cancelable;
   en el celular el cajón es una hoja inferior que se achica a una barra al
   aplicar filtros, y "Ver en el explorador" y "Volver" la achican antes de
   actuar (antes tapaba todo y parecían no hacer nada). Verificado en el
   navegador con viewport de celular contra el Postgres local con la UOM:
   "notificaciones sin leer de avellaneda" con el panel en Hoy → 30 días,
   Avellaneda, Notificaciones, hoja achicada con la respuesta en la barra.
   Set de frases ampliado a 28 (tres sobre el período por defecto); el
   prompt también fija que "mayor a 800 mil" es 800000 y no 800001, que
   fue la única falla de la primera corrida.

Cada bloque se verifica en local (Docker + uvicorn + lote UOM) y se
commitea por separado, preguntando antes.

## 7. Costo medido

Sonnet 5, esfuerzo bajo: **US$ 0,0065 por pregunta** medido sobre las 25
frases del set (46 llamadas, 24.340 tokens de entrada y 11.378 de salida
en total). Con 20 preguntas por día, unos US$ 4 por mes por sindicato. Voz:
US$ 0. El tope diario de 300 acota el peor caso a menos de US$ 2 por día.

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
