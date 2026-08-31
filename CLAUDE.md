# CLAUDE.md — Mi Trabajo

Contexto del proyecto para Claude Code. Se lee al inicio de cada sesión.
Mantener este archivo actualizado cuando cambien decisiones o el estado.

**Este archivo se mantiene deliberadamente corto** — es lo que se carga
automático en CADA turno de CADA sesión, así que su tamaño es un costo fijo
de latencia. El detalle técnico completo de cada feature (por qué se hizo
así, bugs encontrados y su causa real, decisiones de UI puntuales) vive en
[`HISTORIAL.md`](HISTORIAL.md), que NO se carga automático — abrilo cuando
el trabajo puntual lo necesite. Al sumar una sección nueva acá: si es una
decisión/regla vigente, va en CLAUDE.md corto; si es la narrativa de cómo
se llegó a esa decisión, va en HISTORIAL.md.

## Qué es
App web para que trabajadores sindicalizados argentinos verifiquen si su recibo
de sueldo tiene bien calculados los aportes (jubilación, obra social, cuota
sindical, etc.) según el convenio de su sindicato. El trabajador sube foto/PDF del
recibo, una IA lo lee, y el sistema valida los aportes contra las fórmulas del
convenio. Es una **plataforma multi-sindicato**: la misma app sirve a varios
sindicatos, cada uno con su marca, conceptos y trabajadores, en aislamiento total.
Objetivo comercial: mostrarla a sindicatos y a un inversor como algo escalable.

## Stack y arquitectura
- **Backend:** FastAPI + Jinja2.
- **Base de datos:** Postgres en producción (Render gestionado). El motor se
  elige solo: si existe la variable DATABASE_URL usa Postgres; si no, cae a
  SQLite. Esa lógica está en db.py (variable USANDO_POSTGRES). Desarrollo
  local usa Postgres vía Docker por defecto desde 2026-08-16 (ver "Desarrollo
  local con Postgres" más abajo) — SQLite queda como fallback sin Docker.
- **Migraciones:** Alembic. El esquema lo administra Alembic, NO create_all. En
  Postgres (producción y ahora también desarrollo local), los cambios de
  modelo se aplican con `alembic upgrade head` sin borrar datos. Solo en
  SQLite (fallback sin Docker) db.crear_tablas() sigue creando tablas.
- **IA:** API de Anthropic (claude-sonnet-4-6) para leer recibos y comprobantes.
- **Auth:** propia. Claves PBKDF2, sesiones como cookies firmadas HMAC (auth.py).
  Sesión por INACTIVIDAD, no por tiempo fijo desde el login: 15 minutos sin uso
  (`auth.IDLE_TIMEOUT_SEGUNDOS`). El middleware `renovar_sesion_por_actividad`
  (main.py) reemite la cookie en cada request autenticado; un usuario activo
  nunca se desloguea solo. NO se usa auth de terceros.
  **Cookie separada por rol** (`COOKIES_POR_ROL` en main.py:
  `sesion_sindicato`/`sesion_plataforma`/`sesion_trabajador`/`sesion_empleador`)
  — cada rol lee y renueva SOLO su propia cookie, nunca una genérica
  compartida. Cualquier rol nuevo que se agregue tiene que sumar su cookie acá.
  Regla vigente por un bug real (dos pestañas con roles distintos se pisaban
  la sesión) — detalle completo en HISTORIAL.md, sección "Auth".
  **Excepciones sin manejar en un POST de página completa** (`/admin`,
  `/plataforma`) redirigen al login o al panel con un aviso, en vez de
  mostrar el JSON crudo de FastAPI — `sesion_vencida_o_denegada`/
  `error_no_manejado` en main.py, con `_es_navegacion_de_pagina`/`_panel_de`/
  `_rol_de` como helpers. Detalle en HISTORIAL.md.
- **Python 3.12** fijado con .python-version (3.12.8) + variable PYTHON_VERSION en
  Render. Python 3.14 rompe SQLModel ("Field 'id' requires a type annotation").
- **Deploy:** GitHub + Render. Render sigue la rama main y redeploya con cada push.

## Archivos principales
- main.py — servidor y todas las rutas.
- db.py — modelos SQLModel, engine dual, acceso a datos, marca_sindicato().
- auth.py — hash de claves y sesiones.
- extractor.py — lee recibos y comprobantes de aportes con IA.
- validador.py — motor de validación de fórmulas.
- semaforo.py — lógica del semáforo de aportes (ARCA).
- dashboard.py — agregados SQL del Panel Sindical (ver sección propia).
- rag.py — piloto de consultas sobre el convenio: extracción de PDF,
  troceo, embeddings locales e indexación en segundo plano.
- cargar_demo.py — carga 2 sindicatos de demo desde cero (sin AEFIP).
- cargar_lote_sindicato.py — lote sintético completo para CUALQUIER sindicato
  existente (`--sindicato "AEFIP"`); `cargar_lote_uom.py` es la versión
  anterior, específica de la UOM. Ver "Lotes de datos sintéticos".
- cargar_bancaria.py — alta de "La Bancaria" con los conceptos del CCT 18/75
  (ver `docs/cct-1875-bancarios.md`) + su lote.
- medir_dashboard.py — mide los endpoints del Panel Sindical con 50.000 recibos.
- e2e/ — robots de QA con Playwright (ver `e2e/README.md`).
- chequeo.py — autodiagnóstico de la instalación.
- migrations/ — Alembic (env.py + versions/).
- alembic.ini — config de Alembic.
- templates/ — HTML de las 4 apps (trabajador, sindicato, plataforma,
  empresa: portada + panel de cada una, logins, selectores, verificación
  pública de credencial).
- static/ — 2 SVG base + marca.css (sistema de diseño compartido) +
  static/fonts/ (Barlow Condensed, licencia SIL OFL).
- data/seed_aefip.json — semilla histórica; ya NO se carga por defecto.
- data/topes_ss.csv — vigencias de topes de la seguridad social (ver
  "Topes de base imponible" en HISTORIAL.md).
- .claude/skills/diseno-mi-trabajo/ — skill con las reglas del sistema de diseño;
  .claude/skills/frontend-design/ — skill oficial de Anthropic para dirección visual general.
- **HISTORIAL.md** — changelog técnico detallado, no se carga automático.

## Los cuatro roles
1. Admin de plataforma — /plataforma con CUIT + PLATAFORMA_PASSWORD. Da de alta
   sindicatos (con marca y logo) y sus admins. Login → `/plataforma/inicio`
   (portada de tarjetas) → `/plataforma` (panel de siempre).
2. Admin de sindicato — /admin con CUIT + clave. Gestiona conceptos, fórmulas,
   trabajadores, empleadores y reportes SOLO de su sindicato (aislamiento
   total). Login → `/admin/inicio` (portada) → `/admin` (panel con 12
   secciones en una tira de pestañas deslizable).
3. Trabajador — /ingresar con CUIL + clave. Identidad única (un CUIL para toda la
   plataforma). Empadronamiento por sindicato: si el CUIL está en varios, elige;
   la app se pinta con la marca del elegido. Login/elección → `/app/inicio`
   (portada) → `/app` ("Tu Recibo", 6 pestañas: Tu Recibo, Credencial,
   Novedades, Mis Aportes/semáforo, Capacitación, Trámites).
4. Empresa (empleador) — /ingresar-empresa con CUIT + clave (autorregistro).
   Identidad única por CUIT, puede estar dado de alta en varios sindicatos
   (mismo criterio que pluriempleo). Login/elección → `/empresa/inicio`
   (portada) → `/empresa` (2 pestañas: Notificaciones, Trámites). Solo existe
   si el sindicato tiene el módulo `"empleadores"` habilitado — ver
   "Empleadores" en HISTORIAL.md.

## Variables de entorno (Render)
- DATABASE_URL — Internal Database URL del Postgres de Render. Si está, usa Postgres.
- ANTHROPIC_API_KEY — clave de la API de Anthropic.
- PLATAFORMA_CUIT — CUIT del login de plataforma (default 20000000000).
- PLATAFORMA_PASSWORD — clave del login de plataforma.
- SESSION_SECRET — secreto para firmar cookies de sesión.
- PYTHON_VERSION — 3.12.8 (redundante con .python-version, a propósito).
- DB_PATH — solo dev local (SQLite). NO se usa en Render.

## Accesos de la demo
- Plataforma: CUIT 20000000000 + PLATAFORMA_PASSWORD.
- Admin UOM: CUIT 20111111110 / uom-demo.
- Admin Gastronómica: CUIT 20222222220 / fega-demo.
- Trabajador un solo sindicato: CUIL 20111111119 (UOM).
- Trabajador pluriempleo (ambos): CUIL 27222222224.
- Empresa un solo sindicato: CUIT 30999888776 (UOM) — registrarse en `/ingresar-empresa`.
- Empresa multisindicato (ambos): CUIT 30111222339.
- Admin La Bancaria: CUIT 20333444550 / bancaria-demo (sindicato con lote
  sintético completo, recibos según CCT 18/75 — ver `cargar_bancaria.py`).

## Decisiones tomadas (no rediscutir sin motivo)
- **Motor: Render Postgres** (no Supabase). La app ya tiene auth propia, que es el
  mayor valor de Supabase; el Storage se resolvió guardando logos en la base.
- **Datos desde cero:** la demo arranca limpia, sin AEFIP. En producción los
  sindicatos se dan de alta desde el panel de plataforma.
- **Logos en la base:** columnas logo_datos (bytes) + logo_mime en Sindicato;
  se sirven por /logo/{id}, con `?v={logo_v}` (largo en bytes) como sello de
  versión para romper cache al editar. Mismo patrón para firma del sindicato,
  foto de perfil de trabajador/empleador, imágenes de noticias/beneficios,
  archivos adjuntos de notificaciones/trámites — todo bytes en la base, nunca
  disco (no hay disco persistente en Render).
- **JSON como JSONB en Postgres:** columnas alias (Concepto) y detalle (Reporte)
  son jsonb (indexables). En SQLite quedan JSON común.
- **Aislamiento entre sindicatos: total.** Marca por sindicato: 4 colores
  (`color_base`, `color_primario`, `color_acento`, `color_secundario`), inyectados
  como `--marca-base/primario/acento/apoyo` en cada plantilla. `color_base` es el
  único validado como oscuro (`_es_oscuro()` en main.py, umbral de luminancia
  percibida < 140/255) — es el fondo de la portada del trabajador y de todos los
  encabezados oscuros; si no es oscuro, el alta/edición de sindicato se rechaza.
  El semáforo NUNCA toma la marca (colores fijos de estado: verde=pagado,
  amarillo=parcial, rojo=impago). Mismo criterio de aislamiento total se
  extendió a Empleadores (ver HISTORIAL.md).
- **Semáforo ARCA:** el trabajador va a ARCA con un botón, resuelve el captcha él
  mismo y sube la captura/PDF; la IA la lee. NO se automatiza el captcha (frágil y
  zona gris legal). ARCA cubre jubilación y obra social, NO ART. Estados:
  pagado/parcial/impago/no_presentada/no_declarado/informado (ver
  "Ajustes de recibos, aportes y trámites" en HISTORIAL.md para "INFORMADO").
- **Tamaño de logos, 76px unificado** en toda la app (61px en mobile) salvo
  en los 3 logins standalone, donde el logo de plataforma es más grande a
  propósito (148px desktop / 85px mobile) — detalle en HISTORIAL.md.
- **Logos sin fondo blanco forzado**: un PNG con fondo transparente se ve
  transparente de verdad; si un sindicato quiere fondo de color, lo sube ya
  incluido en el archivo. Excepción: el círculo de iniciales de fallback (sin
  logo cargado) sí conserva fondo, porque no es un logo real.
- **Sistema de módulos habilitables** (`modulos.py`): el admin de plataforma
  elige por sindicato qué funcionalidades tiene activas (catálogo en
  `MODULOS`, los de origen en `MODULOS_INICIALES`). Trabajadores y
  Seccionales quedan SIEMPRE visibles, no dependen de ningún módulo. El
  backend rechaza (403, `_exigir_modulo`) igual que esconde el botón — no
  alcanza con ocultar en el cliente. Cualquier feature grande nueva evalúa
  primero si necesita su propia entrada acá (opt-in, no en
  `MODULOS_INICIALES`) en vez de estar siempre encendida para todos.
- **Desarrollo local con Postgres vía Docker** (no SQLite) desde 2026-08-16
  — paridad con producción para probar migraciones de Alembic antes de
  llegar a Render. `docker-compose.yml` en la raíz. Los tests (`test_*.py`)
  siguen en SQLite temporal, sin cambios — ver "Comandos útiles" y detalle
  en HISTORIAL.md.
- **Aislamiento total entre sistemas de trabajador y empleador**: cuando un
  concepto existe para los dos actores (notificaciones, trámites), se
  duplican tablas y rutas en vez de compartirlas, a costa de más código
  repetido — decisión explícita, no un default del proyecto.
- **Patrón portada + panel interno**, repetido para los 3 roles con login
  (`/app/inicio`+`/app`, `/admin/inicio`+`/admin`, `/empresa/inicio`+`/empresa`)
  — cualquier rol nuevo que se agregue debería seguir el mismo patrón.

## Estado actual (actualizado 2026-08-31)
Todo lo listado acá está mergeado a `main` y desplegado (Render sigue `main`,
cada push redeploya).

**SPRINT_REFORMA.md (adaptación a la Reforma Laboral, Dto 407/2026) —
COMPLETO**, los 5 puntos de los dos sprints originales: extractor bi-formato
(clásico + Anexo III, con `contribuciones_patronales`/`costo_laboral_total`/
`ultimo_deposito`), tope sindical 2% configurable solo por plataforma
(`test_tope_sindical.py`), alerta temprana por fecha de último depósito en
el semáforo, contenido real de Capacitación, y el flujo de envío consentido
al sindicato con disclaimer (`/api/enviar-sindicato`, acredita afiliado
cotizante art. 21 bis Dto 407/2026). El archivo `SPRINT_REFORMA.md` en la
raíz documenta el plan tal cual se escribió — no se actualiza
retroactivamente, esta sección es la fuente de verdad sobre qué ya está hecho.

**Por orden cronológico, todo lo construido DESPUÉS de SPRINT_REFORMA.md**
(pedidos nuevos del usuario, ninguno estaba en el plan original; el detalle
técnico completo de cada uno está en HISTORIAL.md, buscar por el mismo título):
1. Migración a Postgres (Render gestionado).
2. Rediseño de interfaz v1 — portada con tarjetas + sistema de 4 colores.
3. Sistema de módulos habilitables por sindicato.
4. Notificaciones (sindicato → trabajador, dirigidas por CUIL/empresa/seccional/provincia).
5. Trámites (formularios dinámicos, numeración de expediente, 5 estados).
6. Rediseño visual "modelo Nike" — vidrio/grano/tipografía condensada, portada clara/oscura por sindicato.
7. Topes de base imponible (art. 9 Ley 24.241) en jubilación/INSSJP/obra social.
8. **Empleadores** — cuarto actor completo: CRUD, login propio, notificaciones y trámites externos, mirror aislado del sistema de trabajador.
9. Portada de `/empresa` con tarjetas, perfil de empleador editable con foto, globos de notificaciones propagados por los 3 niveles de UI.
10. Ajustes puntuales: recibos reportados también cuentan para el padrón de afiliados cotizantes; estado "INFORMADO" de ARCA; popup de cambio de estado en Trámites (reemplazado por el punto 11).
11. **Chat de Trámites estilo WhatsApp** — reemplaza Notas+Historial por un hilo cronológico único con modal para leer/responder/cambiar estado.
12. **App del trabajador instalable (PWA)** — manifest + ícono de Colm3na + banner discreto de instalación, con fallback instructivo en iPhone y link fijo independiente de la cadencia — detalle en HISTORIAL.md.
13. **Logo de plataforma en dos versiones** (fondo claro/fondo oscuro) + ícono de la PWA reemplazado por el arte oficial del manual de marca — detalle en HISTORIAL.md.
14. **Panel Sindical (dashboard)** — la función estrella para el admin de sindicato: KPIs, gráficos con cross-filtering, calendario pintable, semáforo por empresa y explorador de datos paginado, con modal "Ver" de detalle por fila; módulo opt-in `"dashboard"` — ver sección propia y HISTORIAL.md.
15. **Lotes de datos sintéticos para demo** (`cargar_lote_sindicato.py`, y su antecesor específico `cargar_lote_uom.py`): pueblan un sindicato con padrón, 5.000 recibos validados por el motor real, trámites con formulario y diálogo, notificaciones, noticias y beneficios — ver sección propia.
16. **Robots E2E con Playwright** (`e2e/`): pruebas de punta a punta contra la app real, con informe visual al final — ver sección propia.

**Qué queda pendiente** — ver "Pendientes (features)" más abajo para el
detalle; resumen: (a) capacitación por-sindicato (además de la fija de
plataforma), (b) sacar "Cambiar clave" transitorio de plataforma antes de
producción real, (c) verificar los topes SS previos a 2025, (d) evaluar si
el editor de lienzo libre de Trámites llega a justificarse, (e) staging
real en Render (sin urgencia, tiene costo).

**Próximo paso**: no hay tarea de código en curso. Todo está en `main` y
desplegado (Admin 0.19.22). Lo anotado para retomar está en
[`BACKLOG.md`](BACKLOG.md) — lo más concreto: los ajustes de selectores del
dashboard que ya pidió Sd (sacar "Categoría", chip "TODOS" en Seccionales y
Empresas, todo filtro siempre marcado con el color destacado) y el badge
"NEW" en la tarjeta del Panel Sindical.

## Pendientes (features)
1. Capacitación por-sindicato: hoy solo hay contenido FIJO de plataforma
   ("Entendé tu nuevo recibo de sueldo", vale para todos por igual porque
   es ley nacional). Falta diseñar cómo cada sindicato podría sumar SU
   PROPIO contenido además de eso.
2. Quitar la pestaña transitoria "Cambiar clave" del panel de plataforma antes de
   producción (permite cambiar la clave de cualquier usuario; está marcada con una
   advertencia visible). Es un riesgo de seguridad, sacar antes de usuarios reales.
   Se deja a propósito mientras dure la etapa de demos y pruebas.
3. Los topes de base imponible previos a 2025 siguen marcados
   `por_verificar` (menor urgencia, sin inconsistencia detectada) — ver
   "Topes de base imponible" en HISTORIAL.md.
4. **Editor visual de formularios de Trámites con lienzo libre (drag X/Y)**,
   evaluado y pospuesto: se implementó en su lugar un camino más liviano
   (ancho por campo + reordenar arrastrando en lista + vista previa en
   vivo) que cubre el mismo problema real a menor costo — ver "Constructor
   visual de Trámites" en HISTORIAL.md. Revisar si en algún momento el
   lienzo libre se justifica.
5. Entorno de staging real en Render (rama + servicio + base Postgres
   aparte) para probar deploys completos antes de tocar la demo de
   producción — sin urgencia, tiene costo real (no hay free tier viable).

## Consultas sobre el convenio (RAG) — piloto
Módulo `convenio`, **opt-in** (fuera de `MODULOS_INICIALES`). El admin carga
el CCT y sus actas en PDF; el trabajador pregunta en lenguaje natural y
recibe una respuesta citando el artículo. Plan y las decisiones en
[`PLAN_RAG_CONVENIO.md`](PLAN_RAG_CONVENIO.md); la medición que eligió el
modelo, en `medicion_rag/`. Reglas vigentes:

- **Embeddings LOCALES** con `fastembed` + ONNX, sin `torch`.
  `intfloat/multilingual-e5-large`, `vector(1024)`. Elegido midiendo tres
  modelos contra el convenio real: 94% de recall@8 contra 76% y 47%.
- **`fastembed` va PINNEADO EXACTO** en requirements. Cambió el pooling de
  ese mismo modelo entre versiones: si cambia la librería, los vectores
  guardados dejan de ser comparables con las consultas nuevas Y NADA FALLA.
  Por eso `db.MODELO_EMBEDDING` guarda librería + modelo, y se escribe en
  cada fragmento.
- **`passage_embed` / `query_embed`, nunca `embed()`**: e5 es asimétrico y
  usa un prefijo distinto para documento y para pregunta.
- **La indexación NO corre en el request**: tarda ~9 minutos por convenio.
  Va en un hilo, de a lotes de 8, dejando el progreso en el documento. Al
  arrancar, todo lo que haya quedado en `procesando` se marca como error —
  ninguna indexación sobrevive a un reinicio.
- **LA BARANDA DE "NO LO ENCONTRÉ" NO ES UN UMBRAL.** Se midió: una pregunta
  que el convenio no contesta pero del mismo tema puntúa 0,816 y la peor
  legítima 0,826 — no hay umbral que las separe. El umbral (0,79) es solo un
  filtro barato para lo evidente. **El control real es el prompt**, y por eso
  RAG usa `claude-opus-5` y no el `claude-sonnet-4-6` del extractor.
- **Aislamiento en el WHERE**, no en un filtro posterior: `sindicato_id` +
  `convenio_id` + documentos vigentes. Así un fragmento ajeno no puede llegar
  a Claude aunque falle el código de arriba.
- **Al trabajador se le muestran solo las fuentes CITADAS**, no las 8 que se
  le pasaron al modelo.
- Un sindicato puede tener **varios convenios** y **el trabajador elige**.
- `/app/convenio` **no figura en el menú** (decisión de producto del piloto).
  No estar listada NO es control de acceso: exige sesión y módulo igual.

**Test de aceptación**: `medicion_rag/test_aceptacion_bloque3.py`. Hay que
volver a correrlo cada vez que se toque el troceo, el modelo o el prompt.

## Panel Sindical (dashboard del admin de sindicato)
Especificación rectora en [`docs/DASHBOARD.md`](docs/DASHBOARD.md) (+ mockup
`docs/dashboard-sindical.html`); branch `feature/dashboard-sindical`. Módulo
habilitable `"dashboard"` (opt-in, fuera de `MODULOS_INICIALES`). Reglas
vigentes:

- **Agregados 100% en SQL** (`dashboard.py`), con índices compuestos que
  empiezan por `sindicato_id` + fecha. Columnas analíticas en
  `ReciboVerificado` (`procesado_en` ordenable, `cuit_empleador`, `bruto`,
  `monto_diferencia`, `formato`, `categoria`, `fecha_ultimo_deposito`) —
  duplican lo que ya está en `detalle` (JSON) porque un JSON no agrega con
  índices; las llena `dashboard.campos_analiticos()` en `/api/validar`.
- **Endpoints** `GET /admin/dashboard/{kpis, serie-recibos, validacion,
  diferencias-empresa, tramites-seccional, notificaciones, formato-semana,
  semaforo, consultas, explorador/{fuente}, filtros}` + los del modal "Ver"
  (`detalle/recibo/{id}`, `detalle/tramite/{id}`, `detalle/notificaciones`,
  `detalle/notificacion/{id}/destinatarios`, `detalle/consulta/{id}`).
  Sesión de admin + módulo; el `sindicato_id` sale SIEMPRE de la cookie,
  jamás de un parámetro.
- **Privacidad (test en `test_dashboard.py`)**: el detalle de recibos
  muestra nombre/CUIL SOLO si `enviado_sindicato=true`; el CASE está en el
  SQL, no en el frontend. En el modal "Ver" de un recibo NO enviado, el
  servidor además BORRA nombre/CUIL/legajo del JSON guardado antes de
  responder (`dashboard.detalle_recibo`).
- **Dos estados de validación** (OK / con diferencias): "en revisión" no
  existe a nivel recibo (decisión de Sd 2026-08-29). Tipos de notificación
  = `origen` real (manual/sistema). KPI "Afiliados registrados" =
  `registrado=True` vs. padrón (foto, sin filtro de fecha).
- **Consultas al bot**: se reutiliza `ConsultaConvenio` del piloto RAG
  (+columna `tema`), todo el carril detrás del flag de plataforma
  `dashboard_consultas_bot_habilitado=false` (apagado → 404, invisible).
- **STD/PRO futuro**: el explorador se gatea con `_exigir_dashboard_detalle`
  (main.py), separado a propósito — cuando existan los módulos STD y PRO
  (excluyentes), se cambia solo ese helper.
- **Config**: `Sindicato.color_destacado` (default `#E5188F`, SOLO
  selecciones/filtros activos del dashboard, editable solo por plataforma) +
  umbrales del semáforo por empresa (`semaforo_verde_hasta_dias=35`,
  `semaforo_amarillo_hasta_dias=60`, en `ConfiguracionPlataforma`).
- **Rendimiento**: `medir_dashboard.py` siembra 50.000 recibos sintéticos en
  el Postgres local y cronometra cada endpoint (criterio < 1 s; medido 80 ms
  el peor). El tenant sintético queda en la base local para desarrollo
  (`--limpiar` lo borra).
- **UI**: página propia `GET /admin/dashboard` (`templates/dashboard.html` +
  `static/dashboard.js`), linkeada desde la tira de /admin y la portada,
  gateada por módulo. Chart.js 4.4.9 VENDOREADO en `static/chart.umd.min.js`
  (jamás CDN); `/static/` sale con `Cache-Control: public, max-age=3600` +
  sello `?v=` (mismo patrón que /logo). Estado de filtros serializado en la
  query string (link compartible). Debounce 250 ms + AbortController, error
  por panel con reintento.

## Lotes de datos sintéticos (para que la demo se luzca)
`cargar_lote_sindicato.py --sindicato "NOMBRE"` puebla cualquier sindicato ya
existente: 6 seccionales, ~12 empresas, 100 trabajadores con cuenta (**clave
= los 5 primeros dígitos del CUIL**), 5.000 recibos, 5 tipos de trámite +
2.000 trámites, 200 notificaciones, 30 noticias y 20 beneficios. Reglas:

- **Los recibos NO se inventan**: se arman con el catálogo real del sindicato
  y se AUTOCORRIGEN contra `validador.validar()` (hasta 4 pasadas, ajustando
  cada aporte al "esperado" del motor) → ~80% OK con cualquier catálogo; los
  errores del 20% se inyectan después, sobre un recibo ya correcto.
- **Todo con contenido de verdad**: formularios temáticos respondidos, ida y
  vuelta sindicato↔afiliado en los trámites que avanzaron, notificaciones de
  sistema citando el expediente real. Nada de registros vacíos que solo
  sirvan para el tablero.
- Determinista por sindicato, idempotente (aborta si el lote ya está) y
  `--limpiar` borra exactamente el lote sin tocar la demo original.
- Le habilita al sindicato los módulos que el lote necesita (dashboard,
  trámites, notificaciones, noticias, beneficios).
- Los códigos de tipo de trámite van prefijados con la sigla del sindicato
  (el `numero_expediente` es único en TODA la plataforma y su prefijo sale
  del código del tipo).
- **Perfiles de recibo por convenio**: un sindicato puede registrar en
  `cargar_lote_sindicato.PERFILES` una función que arma sus líneas de ingreso
  según SU convenio, en vez del armado genérico. `cargar_bancaria.py` es el
  ejemplo: reproduce el CCT 18/75 (adicionales como % del **sueldo inicial**,
  antigüedad embebida en el básico, cajero función + falla de caja como dos
  líneas). Los rasgos estables del trabajador (antigüedad, si es cajero,
  título) salen de `trab["semilla"]`, derivada del CUIL — no se sortean en
  cada recibo.

## Robots E2E (Playwright) — ver `e2e/README.md`
Pruebas de punta a punta contra la app real (servidor + Postgres + JS del
frontend), separadas de la suite unitaria porque necesitan el entorno
levantado. Playwright es dependencia de DESARROLLO (`requirements-dev.txt`),
**jamás** en `requirements.txt`. Reglas vigentes:

- Las páginas se piden con la fixture `nuevo_actor("nombre")`, nunca
  `browser.new_context()` a mano: esa fixture es la que aplica video/traza y
  acomoda las ventanas.
- **Con `--headed` en Windows la ventana se abre DETRÁS y `bring_to_front()`
  no alcanza** (el SO no deja robar el primer plano): se fija TOPMOST y en su
  franja de pantalla, ver `e2e/ventanas.py`. Con dos actores, uno por mitad.
- Cada robot narra lo que hace con `informe.paso()` / `informe.dato()`: al
  final sale un resumen por terminal y la ficha `e2e/resultados/informe.html`
  (se abre sola con `--headed`).
- Los prerequisitos de datos van en fixtures idempotentes con `pytest.skip`
  explicando cómo prepararlos, nunca fallando críptico.
- El flujo de lectura por IA (`/api/leer`) NO se robotiza: gastaría créditos
  de Anthropic en cada corrida.

## Noticias (sindicato → trabajador)
Modelo `Noticia` (db.py): título, bajada, texto completo (con auto-link de
URLs), vigencia por fecha_desde/fecha_hasta (ambas obligatorias), hasta 2
imágenes. Admin la carga en `/admin` → Noticias. El trabajador la ve en la
portada (hasta 3) y en la pestaña Novedades — detalle en HISTORIAL.md.

## Beneficios (sindicato → trabajador)
Modelo `Beneficio` (db.py): rubro, descripción, link opcional, vigencia
(ambas fechas obligatorias), una imagen. Carrusel en la portada del
trabajador (`.carrusel-wrap`/`.carrusel-track` en marca.css) — detalle en
HISTORIAL.md.

## Seccionales del sindicato
Modelo `Seccional` (db.py): sindicato_id, nombre, dirección. CRUD simple en
`/admin` → Seccionales. `Trabajador.seccional_id` opcional. Noticias y
Beneficios pueden dirigirse por seccional (`destino_seccionales`, lista
vacía = todas) — detalle en HISTORIAL.md.

## Administradores del sindicato (self-service)
`/admin` → pestaña "Administradores" (siempre visible) permite al propio
sindicato listar/dar de alta/editar/activar-desactivar sus
`UsuarioSindicato`, scopeado siempre a su `sindicato_id`. Cambiar la clave
de un admin YA EXISTENTE sigue siendo solo vía plataforma. No se puede
desactivar al último administrador activo — detalle en HISTORIAL.md.

## Alerta de posible adulteración en recibos
`extractor.extraer()` evalúa señales de edición en totales/CUIL/CUIT/fechas
(alta certeza únicamente). No bloquea al trabajador; guarda el archivo en
`ReciboSospechoso`, visible solo por el admin de **plataforma** en "Recibos
con alerta" — detalle en HISTORIAL.md.

## Versionado
`version.py`: `VERSION_TRABAJADOR`/`VERSION_ADMIN`/`VERSION_PLATAFORMA` +
`FECHA_VERSION`, actualizados a mano en cada deploy (el número lo indica el
usuario). **Regla para incrementar `release.patch`**: solo arreglos → +1 al
patch; arreglos + funcionalidad nueva en el mismo deploy → +1 en los dos
(ej. 0.02.01 → 0.03.01). Acordarse de esto SIN que el usuario lo pida.
**`FECHA_VERSION`, la hora es real, no inventada**: Claude no tiene reloj
propio — para no repetir el bug de poner "12:00" fijo a mano (encontrado
2026-08-24), correr `date "+%Y-%m-%d %H:%M"` (Bash) y usar ese valor real.

## Datos de la IA y fórmulas: nada se evalúa crudo
Todo importe que llega de `extractor.py` pasa por `validador.a_numero()`
antes de entrar a una cuenta (la salida de un modelo NO es un contrato: un
`null` o un texto reventaban la suma y el trabajador veía el 500 genérico).
Una línea sin importe legible queda AFUERA de los cálculos, con alerta
`importe_ilegible`; nunca vale $0. Una fórmula que no evalúa saltea SU
chequeo con alerta `formula_invalida`, no tumba el recibo. Y `/admin/formula`
prueba la expresión con `validador.error_de_expresion()` antes de guardarla:
una fórmula rota no se guarda, porque si no falla meses después en la
pantalla del trabajador y no en la del admin que la escribió. El mensaje del
handler global (`error_no_manejado`) es genérico a propósito: cubre TODA la
app, no solo recibos. El catálogo del sindicato tampoco se toma como
confiable: códigos y alias se normalizan (`_clave`, `_alias_de`) antes de
matchear. Detalle en HISTORIAL.md, "el 500 genérico que mentía".

## Códigos de error propios (`errores.py`)
Todo error que ve una persona lleva un código (`raise ErrorApp("E-...")`),
que viaja al frontend y se muestra debajo del mensaje. **Solo los errores
reales de lectura pueden decir "probá con otra foto"** (E-RECIBO-01/02,
E-APORTE-01/02) — hay un test que lo verifica sobre todo el catálogo.
`E-INTERNO-00` es el único que admite no saber qué pasó, y por eso lleva un
`ref` de 8 caracteres que se imprime junto al traceback en el log: con eso se
encuentra el error exacto en Render. Un error nuevo se agrega a `MENSAJES`, y
si una ruta puntual merece su propio código ante lo inesperado, va en
`CODIGO_POR_RUTA`.

## Hallazgo pendiente, no arreglado
`db.cargar_seed_si_vacio()` sigue disparando el seed histórico de AEFIP al
recrear la base local desde cero sin correr `cargar_demo.py` antes —
aparece un sindicato "AEFIP" fantasma con id=1. No afecta producción
(nunca se recrea la base de Render desde cero) — detalle en HISTORIAL.md.

## Método de trabajo
- Por bloques chicos, verificando la lógica de verdad (rutas y funciones), no
  simulada. Preferir cambios quirúrgicos y probar antes de avanzar.
- Sd tiene skills intermedias de Python, trabaja en Argentina, deploya con
  GitHub + Render (push dispara redeploy).
- Preferencia: durante la construcción mostrar poco output intermedio; dar un
  resumen claro al final.
- Sesiones largas acumulan contexto y eso enlentece cada respuesta — para
  bloques de trabajo sin relación entre sí, preferir abrir una sesión nueva
  en vez de seguir apilando todo en la misma conversación.

## Comandos útiles
- Correr local (Postgres vía Docker): `docker compose up -d`,
  después `alembic upgrade head`, después `uvicorn main:app --reload`.
- Correr local (SQLite, sin Docker): `uvicorn main:app --reload`
  (con `DATABASE_URL` comentado/ausente en `.env`).
- Autodiagnóstico: `python chequeo.py`
- Cargar demo: `python cargar_demo.py` (¡correr alembic upgrade head antes si es Postgres!)
- Migraciones: `alembic upgrade head` (aplicar) / `alembic revision --autogenerate -m "msg"` (crear)
- En la Shell de Render, si `alembic` no se encuentra: usar `python -m alembic upgrade head`
- Reset completo de la base local Postgres: `docker compose down -v && docker compose up -d`
  (espera a que el healthcheck pase) `&& alembic upgrade head && python cargar_demo.py`
- E2E con Playwright (`e2e/`, navegador real): necesita Docker + uvicorn
  corriendo y el lote UOM cargado. Instalar una vez con
  `pip install -r requirements-dev.txt && playwright install chromium`;
  correr con `.venv/Scripts/python.exe -m pytest e2e/ -q`. Playwright es
  dependencia de DESARROLLO: jamás sumarlo a requirements.txt (Render lo
  instalaría al cuete en cada deploy).
- Tests: correr CADA `test_*.py` por separado (loop por archivo), nunca
  `pytest -q` batcheado — módulos comparten estado de import y se
  contaminan entre archivos si corren en el mismo proceso pytest.
- **Corriendo un test directo con `.venv/Scripts/python.exe test_x.py`
  (sin pytest)**: `conftest.py` (que fuerza SQLite aislado) NO se carga en
  ese modo — con `DATABASE_URL` real en `.env` (desarrollo local con
  Postgres), el test pega contra el Postgres de Docker de verdad, no un
  SQLite temporal. Anteponer `DATABASE_URL=` vacío al comando:
  `DATABASE_URL= .venv/Scripts/python.exe test_x.py`. Detalle en
  HISTORIAL.md, sección del ícono/logo de Colm3na.
