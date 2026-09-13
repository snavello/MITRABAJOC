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
- **Repositorio:** `snavello/MITRABAJOC`
  (https://github.com/snavello/MITRABAJOC) es el ÚNICO repo del proyecto:
  todo se lee, se desarrolla y se pushea acá. Ese es el nombre canónico y
  con esas mayúsculas: escrito de otra forma GitHub redirige, el push anda
  igual e imprime un aviso de que el repositorio se movió -- que no es un
  error pero hace dudar cada vez. El repo
  viejo `snavello/MiTrabajo` es un PoC descartado, escrito en **Streamlit**:
  está abandonado, no se lee, no se toca y no se porta NADA de ahí. **Streamlit
  no se usa más en ningún caso** — si algo sugiere Streamlit, está mirando el
  repo equivocado.
- **Backend:** FastAPI + Jinja2.
- **Base de datos: Postgres, siempre.** `DATABASE_URL` es OBLIGATORIA y sin
  ella la app no arranca (db.py levanta un error explicando qué hacer). No
  hay fallback a SQLite: lo hubo hasta el 2026-09-11 y se sacó porque la
  suite entera validaba contra un motor que el proyecto no usa (detalle en
  "Afuera SQLite" de HISTORIAL.md). Producción y pruebas son Render
  gestionado; desarrollo local es el Postgres del `docker-compose.yml`.
- **Migraciones:** Alembic. El esquema lo administra Alembic, NO create_all:
  los cambios de modelo se aplican con `alembic upgrade head` sin borrar
  datos, y en Render corre solo en el Pre-Deploy. `db.crear_tablas()` quedó
  para un solo uso: que la suite arme el esquema de su base descartable.
- **IA:** API de Anthropic, tres modelos con un uso cada uno:
  `claude-sonnet-4-6` lee recibos y comprobantes (`extractor.py`),
  `claude-opus-5` responde las consultas sobre el convenio (`rag.py`) y
  `claude-sonnet-5` es el Asistente del Panel Sindical (`asistente.py`).
  Cada llamada queda registrada en `UsoIA` (tipo, modelo, tokens).
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
- **Deploy:** GitHub + Render, DOS servicios (desde 2026-09; el ciclo de una
  feature en una página está en [`FLUJO.md`](FLUJO.md), la infraestructura en
  `DESPLIEGUE_RENDER.md` y el porqué en `PLAN_ENTORNOS.md`):
  `mitrabajo-pruebas` sigue `main` (cada push redeploya), `mitrabajo-demo`
  sigue `demo` y solo cambia con `python promover_demo.py` (backup + merge +
  tag + push). Alembic corre solo en cada deploy (Pre-Deploy Command). Sobre
  `demo` nunca se programa.

## Archivos principales
- main.py — servidor y todas las rutas.
- db.py — modelos SQLModel, engine dual, acceso a datos, marca_sindicato().
- auth.py — hash de claves y sesiones.
- extractor.py — lee recibos y comprobantes de aportes con IA.
- validador.py — motor de validación de fórmulas.
- semaforo.py — lógica del semáforo de aportes (ARCA).
- geo.py — geocodificación de domicilios: Georef (provincia/localidad) +
  Nominatim (calle y altura). Ver "Georreferenciación" para las reglas.
- dashboard.py — agregados SQL del Panel Sindical (ver sección propia).
- fechas.py — la hora de Buenos Aires, en un solo lugar. En el código de la
  app NO se llama a `datetime.now()` ni a `date.today()`: el servidor de
  Render corre en UTC y toda la app compara fechas como texto. Lo verifica
  `test_fechas.py` recorriendo los archivos con `ast`.
- encuestas.py — catálogo y reglas PURAS del módulo Encuestas (modos,
  cortes, tipos de pregunta, estados, disclaimer, textos de los avisos). No
  importa `db`, así que se prueba solo y rápido.
- resultados_encuesta.py — agregados SQL del dashboard de una encuesta. El
  umbral y los filtros se aplican acá, en la consulta, no en la pantalla.
- demo_encuestas.py — el padrón sintético y las tres tomas de encuesta de
  la demo (lo llama `cargar_demo.py`).
- cargar_encuesta_sintetica.py — llena de respuestas una encuesta YA
  publicada (no la crea: la arma una persona en el panel). Es la
  herramienta para preparar una demo sobre una encuesta de verdad. Sin
  `--si` no escribe nada. Ver "Llenar una encuesta con respuestas
  sintéticas" en DESPLIEGUE_RENDER.md.
- rag.py — piloto de consultas sobre el convenio: extracción de PDF,
  troceo, embeddings locales e indexación en segundo plano.
- validaciones_tramite.py — motor puro de validaciones de formularios de
  Trámites (fija + consistencia; ver sección propia).
- recursos.py — Recursos de la landing `/entornos`: catálogo de la
  documentación del proyecto (los versionados en `recursos/` + los subidos
  a la base), el pase de 30 días que deja el PIN y la clasificación por tipo.
- docs/generador/ — generador de la documentación técnica
  (`recursos/documentacion-tecnica.html`): `extraer.py` lee el código con
  `ast` y deja `datos.json`; `generar.py` arma el HTML con los diagramas SVG
  de `diagramas.py` y los textos de `contenido.py`. Se corre a mano tras
  cambios grandes: `python docs/generador/extraer.py && python
  docs/generador/generar.py`.
- push.py — notificaciones Web Push a la PWA del trabajador (novedades de
  trámites; apagado sin claves VAPID).
- asistente.py — Asistente del Panel Sindical: pregunta en lenguaje
  natural → filtros del panel + resumen (ficha: `docs/ASISTENTE_PANEL.md`).
  `probar_asistente.py` + `medicion_asistente/` = set de aceptación del
  prompt contra la API real (gasta créditos; a mano, nunca en CI).
- cargar_demo.py — carga 2 sindicatos de demo desde cero (sin AEFIP).
- cargar_marca_plataforma.py — siembra el logo y los colores de Colm3na
  (viven en la base, no en el código: sin esto un entorno nuevo arranca con
  el placeholder `static/logo_mitrabajo.svg`). Va primero al poblar.
- promover_demo.py / clonar_demo_a_pruebas.py / pg_cliente.py — operación de
  entornos: promover `main` a la demo, clonar los datos de demo a Pruebas
  (excepción, no rutina) y elegir un cliente de Postgres compatible con el
  servidor. Ver `FLUJO.md`.
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
  static/fonts/ (Barlow Condensed, licencia SIL OFL) + mapa.js (capa fina
  sobre Leaflet y las burbujas de los dos mapas de tablero, compartida por las
  cinco pantallas con mapa) +
  modales.js (arrastre de modales en escritorio, ver "Modales") +
  static/vendor/leaflet/ (Leaflet 1.9.4 vendoreado, jamás CDN).
- data/seed_aefip.json — semilla histórica; ya NO se carga por defecto.
- data/topes_ss.csv — vigencias de topes de la seguridad social (ver
  "Topes de base imponible" en HISTORIAL.md).
- .claude/skills/diseno-mi-trabajo/ — skill con las reglas del sistema de diseño;
  .claude/skills/frontend-design/ — skill oficial de Anthropic para dirección visual general.
- **FLUJO.md** — el ciclo de un cambio en una página: de tu PC a Pruebas y de
  Pruebas a la demo, con los comandos y las tres reglas.
- **HISTORIAL.md** — changelog técnico detallado, no se carga automático.

## Los cuatro roles
1. Admin de plataforma — /plataforma con CUIT + PLATAFORMA_PASSWORD. Da de alta
   sindicatos (con marca y logo) y sus admins. Login → `/plataforma/inicio`
   (portada de tarjetas) → `/plataforma` (panel de siempre).
2. Usuario de sindicato — /admin con CUIT + clave. Gestiona conceptos, fórmulas,
   trabajadores, empleadores y reportes SOLO de su sindicato (aislamiento
   total). Login → `/admin/inicio` (portada) → `/admin` (panel con 15
   entradas en una tira de pestañas deslizable: Panel Sindical, Reportes,
   Fórmulas, Conceptos, Trabajadores, Aprendizaje, Cotizantes, Noticias,
   Beneficios, Notificaciones, Trámites, Empleadores, Convenio, Seccionales
   y Áreas y Usuarios; varias dependen de un módulo). Desde el sprint de
   Áreas V2 no es un rol sino **tres** (ver "Áreas, permisos y ruteo"):
   Super Admin (= Admin de Sede Central, el de siempre, ve las 15),
   Admin de Seccional (lo mismo pero solo sobre SU seccional) y usuario de
   área (solo las secciones que le dé su área, y solo sobre su alcance).
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
- ENTORNO — `local`/`pruebas`/`demo`/`prod` (`entorno.py`). En `local` y
  `pruebas` la app muestra un distintivo fijo con entorno + versión (para
  no confundir pantallas en una presentación); en `demo`/`prod` y sin la
  variable, nada. Va también en el "Acerca de". Donde hay distintivo existe
  además `/entornos`: landing interna con los 8 accesos (4 logins x
  Pruebas/Demo, hosts en `entorno.URLS`) y la versión que corre en cada
  uno, que lee de `/api/version` (público, en todos los entornos). Debajo,
  **Recursos** (`recursos.py`): la documentación del proyecto catalogada
  con miniatura, descripción y fecha -- los versionados en `recursos/`
  (`recursos.SEMILLA`) más los subidos desde la misma landing (tabla
  `Recurso`, bytes en la base). **Toda la landing está detrás de un PIN**
  de ocho dígitos (`PIN_ENTORNOS`, abajo) que se ingresa una vez por
  dispositivo y deja un pase de 30 días (cookie `pase_entornos`, NO es una
  sesión de rol); una sesión de plataforma vigente también entra. Un enlace directo a
  `/recursos/.../archivo` sin pase cae en la puerta y, con el PIN, abre ese
  documento (`?siguiente=`, solo paths `/recursos/`). Detalle en
  HISTORIAL.md, "Recursos en la landing" y "PIN de la landing".
- PIN_ENTORNOS — PIN de ocho dígitos de la landing `/entornos` (`entorno.py`,
  default `09211999`). Cinco intentos fallidos seguidos desde una IP hacen
  esperar un minuto. Cambiarlo en Render no desloguea a nadie: los pases ya
  emitidos siguen valiendo hasta sus 30 días (van firmados con SESSION_SECRET;
  para cortarlos, cambiar ese secreto).
- ANTHROPIC_API_KEY — clave de la API de Anthropic.
- PLATAFORMA_CUIT — CUIT del login de plataforma (default 20000000000).
- PLATAFORMA_PASSWORD — clave del login de plataforma.
- SESSION_SECRET — secreto para firmar cookies de sesión.
- PYTHON_VERSION — 3.12.8 (redundante con .python-version, a propósito).
- DEMO_DATABASE_URL — solo en el `.env` de la PC de quien promueve: External
  Database URL de la base de demo, para el `pg_dump` de `promover_demo.py`.
- VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY / VAPID_CLAIM_EMAIL — Web Push de la
  PWA (push.py); sin las tres, el canal queda apagado en silencio.

## Accesos de la demo
- Plataforma: CUIT 20000000000 + PLATAFORMA_PASSWORD.
- Admin UOM: CUIT 20111111110 / uom-demo (Super Admin).
- Admin Gastronómica: CUIT 20222222220 / fega-demo (Super Admin).
- UOM, Admin de Seccional de Rosario: 20555555553 / rosario-demo.
- UOM, un usuario por área (la lista completa la imprime `cargar_demo.py`
  al terminar). Los dos que muestran el contraste de un vistazo:
  27777777774 / prensa-demo (Prensa de Sede Central, alcanza a todo el
  país) y 20888888887 / prensacba-demo (el mismo perfil, recortado a
  Córdoba). El de Prensa central, además, NO está en el padrón a propósito:
  trabaja en el gremio sin estar afiliado.
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
- **Todo lo que sale de `/static/` va con sello `?v=`, sin excepción.** Esa
  ruta se sirve con `Cache-Control: public, max-age=3600`: sin sello, un
  cambio tarda hasta una hora en llegarle a quien ya visitó la app, y
  mientras tanto ve el HTML NUEVO con el archivo VIEJO — peor que ver la
  versión anterior entera. `marca.css` quedó sin sello y así se rompió el
  modal de noticias en producción (2026-09-03). El sello lo da
  `main._sello_static(nombre)` (global de Jinja, mtime+tamaño del archivo, no
  `version.py`: cambia aunque nadie suba la versión). Un archivo nuevo en
  `/static/` que una plantilla referencie tiene que usarlo.
- **JSON como JSONB:** las columnas JSON del proyecto usan `db.JSON_TIPO`
  (`JSON().with_variant(JSONB, "postgresql")`), que es la misma expresión que
  usan las migraciones. **Una columna JSON nueva va con `JSON_TIPO`, no con
  `JSON` pelado**: si no, el modelo dice `json` donde la migración crea
  `jsonb` y la suite pasa a probar contra un tipo que no es el que corre.
  **No queda ninguna columna en `json`**: las siete históricas (alias de
  Concepto, los tres `detalle`, `fragmentos_usados`, `parametros`, `resumen`)
  se convirtieron en la migración `d2c8f04a6b31`. Medido antes de hacerlo
  sobre una copia de la demo con 15.000 recibos: 1,5 s las siete juntas. El
  `ALTER COLUMN ... TYPE` reescribe la tabla con lock ACCESS EXCLUSIVE, así
  que a esta escala son segundos de espera en el Pre-Deploy; si estas tablas
  llegaran a millones de filas hay que repensarlo (columna nueva, backfill
  por lotes y swap).
  **`test_migraciones.py` compara los dos esquemas** — tablas, columnas, tipos
  y obligatoriedad — levantando uno con `create_all` y otro con `alembic
  upgrade head`. Existía como promesa en `conftest.py` desde que la suite pasó
  a Postgres y se escribió recién el 2026-09-12, cuando encontró 15 columnas
  `json`/`jsonb` desalineadas y 8 que el modelo dejaba nulas y la base no.
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
- **Un solo encabezado para las cuatro apps** (2026-09-13): ninguna
  plantilla escribe el suyo, se arma con `{% include "_encabezado.html" %}`
  (+ `static/encabezado.css`, que el propio parcial carga porque
  `trabajador.html` y `empresa.html` no cargan `marca.css`). Cinta oscura
  con el rol del panel a la izquierda y **Colm3na a la derecha**; debajo, la
  barra del sindicato: logo a 52px de ALTO y ancho libre (38px en mobile) y
  el nombre de la pantalla a la derecha, dicho UNA sola vez. El nombre del
  sindicato en texto solo si no hay logo; el texto "Mi Trabajo" no va en
  ningún encabezado. Fuera del sistema a propósito: los 3 logins standalone
  (logo de plataforma grande, 148/85px) y las herramientas internas
  (`/entornos`, informes de carga). Reglas completas en la skill
  `diseno-mi-trabajo`; el porqué, en HISTORIAL.md.
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
- **Postgres y nada más, en todos lados** (2026-09-11). Desarrollo local
  con el `docker-compose.yml` de la raíz desde 2026-08-16, y desde el
  11-09 también **la suite**: `conftest.py` crea una base Postgres
  descartable por proceso de pytest, le arma el esquema y la borra al
  terminar. El SQLite de los tests se fue porque daba por buenos defectos
  que Postgres no perdona — el mismo día encontró tres, entre ellos una
  clave foránea a un sindicato inexistente y un test del dashboard que
  afirmaba MIN/MAX donde la app real devuelve percentiles. Detalle en
  "Afuera SQLite" de HISTORIAL.md.
- **Aislamiento total entre sistemas de trabajador y empleador**: cuando un
  concepto existe para los dos actores (notificaciones, trámites), se
  duplican tablas y rutas en vez de compartirlas, a costa de más código
  repetido — decisión explícita, no un default del proyecto.
- **Los modales se mueven en escritorio** (`static/modales.js`, 2026-09-13):
  se arrastran del encabezado (o del título si no tiene), quedan siempre
  enteros dentro de la ventana y vuelven a su lugar al cerrarse. Un solo
  archivo compartido, delegado en `document` (los modales se llenan con
  innerHTML, cualquier enganche al abrir se perdería) y apagado en teléfono,
  donde el modal es una hoja pegada al borde. Una FAMILIA nueva de modal tiene
  que sumarse a `CAJAS` de ese archivo y al cursor de marca.css; `test_modales.py`
  verifica que toda plantilla con modales cargue el script.
- **Patrón portada + panel interno**, repetido para los 3 roles con login
  (`/app/inicio`+`/app`, `/admin/inicio`+`/admin`, `/empresa/inicio`+`/empresa`)
  — cualquier rol nuevo que se agregue debería seguir el mismo patrón.
- **La hora de la app es la de Buenos Aires, no la del servidor**
  (`fechas.py`, 2026-09-11). Render corre en UTC: `datetime.now()` da tres
  horas de más y `date.today()` cambia de día a las 21:00 de Argentina, así
  que toda vigencia por fecha terminaba tres horas antes de lo que decía
  (una noticia "hasta el 30" desaparecía a las 21:00 del 30) y los sellos de
  tiempo posteriores a esa hora quedaban con la fecha del día siguiente. En
  el código de la app **no se llama más a `datetime.now()` ni a
  `date.today()`**: se usa `fechas.ahora()/hoy()/hoy_texto()/ahora_texto()`.
  Lo verifica `test_fechas.py`, que recorre los módulos y falla nombrando al
  que se saltee la regla — fail-closed, un archivo nuevo entra solo a la
  lista. Los datos escritos ANTES del fix quedaron en UTC: no se migraron
  (detalle en HISTORIAL.md).

## Estado actual (actualizado 2026-09-11)
Todo lo listado acá está mergeado a `main` y desplegado (Render sigue `main`,
cada push redeploya) **salvo el punto 21**, que vive en la rama
`areas-permisos-v2` y todavía no se mergeó ni se desplegó.

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
17. **Validaciones en formularios de Trámites (Fase 1)** — capa de validaciones por campo (fuente `fija` + consistencia entre campos, bloquea/avisa) con rediseño "Expediente" del constructor y carátula+sello en la pantalla del trabajador — ver sección propia.
18. **Esquema visual "Hilo" en TODA la suite** (2026-09-03): nació en Notificaciones y Trámites del trabajador (bandeja como línea de tiempo, "Necesita tu atención", accesos grandes, barra de progreso; mockups de las 3 propuestas en `disenos/notificaciones-tramites-propuestas.html`) y después se extendió, sin tocar contenido, a las 6 pestañas de `/app`, portada y perfil del trabajador, y a Admin y Plataforma (portadas, cromo de los paneles, chips/modales/subtítulos). Vocabulario: tarjeta oscura con degradé base→primario + grano + filo ámbar, kicker en acento, títulos en condensada, hitos con línea, píldoras de estado, cifras en monoespaciada. En Admin/Plataforma las tablas siguen siendo tablas (decisión explícita). El Panel Sindical conserva su diseño propio — detalle por partes en HISTORIAL.md.

19. **Entornos separados, Etapas 0 y 1 de [`PLAN_ENTORNOS.md`](PLAN_ENTORNOS.md)
    COMPLETAS** (2026-09-03): `mitrabajo-demo` (URL de siempre) sigue la rama
    `demo` y solo cambia al promover; `mitrabajo-pruebas` sigue `main` y
    redeploya con cada push (~90 s), con su propio Postgres. Alembic corre
    solo en el deploy (Pre-Deploy Command). El ciclo entero se estrenó tres
    veces el mismo día. El flujo del día a día, en una página, está en
    [`FLUJO.md`](FLUJO.md). Lo que quedó de código: `cargar_marca_plataforma.py`
    (la marca vivía SOLO en la base de demo, así que todo entorno nuevo nacía
    con el placeholder viejo), `clonar_demo_a_pruebas.py` (excepción, con
    guardas que impiden invertir la dirección) y `pg_cliente.py`.
20. **Landing `/entornos` con PIN, Recursos y documentación técnica generada
    del código** (2026-09-07): la landing entera detrás de un PIN de ocho
    dígitos con pase de 30 días; debajo, Recursos (documentos versionados en
    `recursos/` + subidos a la base, con miniatura y fecha); y la
    documentación técnica reconstruida desde el código por
    `docs/generador/`, catalogada ahí. Mismo día se puso al día README,
    docstrings de db/main/auth y este archivo.
21. **Áreas, permisos granulares y ruteo de trámites (`SPRINT_AREAS_V2.md`)**
    (2026-09-11, rama `areas-permisos-v2`, **sin desplegar**): el panel del
    sindicato deja de ser todo-o-nada. Tres roles (Super Admin = Admin de
    Sede Central, Admin de Seccional, usuario de área), el área colgando de
    una seccional, catálogo de 18 secciones (`permisos.py`) separado de los
    módulos contratados, gateo fail-closed de las 73 rutas `/admin/*`,
    identidad del operador vinculada al padrón por CUIL (marca "empleado de
    sindicato"), trámites ruteados al área que declara el formulario, pase
    entre áreas por lista cerrada con todo el movimiento en el chat del
    trabajador, y responder + cambiar estado como un solo acto. La premisa
    se cumplió: los admins de hoy migran a Super Admin y no pierden nada.
    Siete fases, seis migraciones verificadas en Postgres con datos, 149
    tests nuevos en 10 archivos — ver la sección propia y HISTORIAL.md.

22. **Encabezado normalizado en toda la suite** (2026-09-13): antes cada
    pantalla armaba el suyo — el logo del sindicato salía en cuatro medidas
    distintas (76×76, 76×220, 61×170, 46×46), el orden sindicato/Colm3na se
    daba vuelta entre la portada y el panel, Colm3na aparecía en 6 de 12
    pantallas (y en la portada del afiliado se veía más grande que el
    gremio), y el título de la pantalla se decía dos veces. Ahora hay un
    parcial único (12 pantallas, incluida Resultados de encuesta) — ver la
    regla en "Decisiones tomadas" y el relevamiento en HISTORIAL.md.

**Qué queda pendiente** — ver "Pendientes (features)" más abajo para el
detalle; resumen: (a) capacitación por-sindicato (además de la fija de
plataforma), (b) sacar "Cambiar clave" transitorio de plataforma antes de
producción real, (c) verificar los topes SS previos a 2025, (d) evaluar si
el editor de lienzo libre de Trámites llega a justificarse, (e) las etapas
2 a 4 de PLAN_ENTORNOS.md (organización de GitHub + CI, runbook y accesos,
traspaso), que reemplazan al viejo pendiente de "staging en Render".

**Próximo paso**: mergear `areas-permisos-v2` y desplegarla a pruebas
(punto 21). Después, la Etapa 2 de `PLAN_ENTORNOS.md` (repo en una
organización de GitHub, reglas de rama, CI que corra cada `test_*.py` por
separado, devcontainer). En paralelo sigue vivo lo de
[`BACKLOG.md`](BACKLOG.md): fases 2–4 de validaciones
(sistema/lista/externa). El merge de `areas-permisos` y el sprint "Admin de
Seccional" que figuraban acá los absorbió el punto 21: la rama vieja quedó
126 commits atrás y se portó sobre `main` en vez de mergearse.

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
5. Entornos separados (Pruebas / Demo / Desarrollo en la nube / Prod):
   plan por etapas en [`PLAN_ENTORNOS.md`](PLAN_ENTORNOS.md). **Etapas 0
   (repo) y 1 (Render) HECHAS** el 2026-09-03 (ver punto 19 de "Estado
   actual"). Quedan las etapas 2 a 4: organización de GitHub + CI, runbook
   y accesos, traspaso de la operación diaria a dos devs.
6. **Asistente del Panel Sindical** (construido 2026-09-05, 7 bloques,
   mergeado a `main` el mismo día como Admin 0.29.01):
   chat en lenguaje natural que traduce la pregunta del admin a los filtros
   que el panel ya tiene, los aplica y resume con los números reales, más
   el filtro por afiliado del panel y el dictado por voz. NO es RAG ni el
   bot del convenio. Ficha rectora con contrato, decisiones, privacidad y
   medición: [`docs/ASISTENTE_PANEL.md`](docs/ASISTENTE_PANEL.md). Lo que
   sigue pendiente es la medición periódica del prompt (`probar_asistente.py`).
7. **Módulo Encuestas** (anónimas y nominales al padrón): plan acordado
   decisión por decisión el 2026-09-11, **antes de tocar código**, en
   [`SPRINT_ENCUESTAS.md`](SPRINT_ENCUESTAS.md) — 24 decisiones, modelo de
   datos, seis fases y los cuatro tests de privacidad. **Fases 0 y 1
   HECHAS**: el modelo (padrón y urna separados), el módulo `encuestas`
   opt-in con sus dos secciones de permiso, y el **constructor** en la
   pestaña Encuestas de `/admin` — diez tipos de pregunta (los de
   CampoTramite más escala y ranking; archivo solo en las nominales),
   reordenar arrastrando, vista previa del lado del afiliado y congelado
   con corrección de erratas. **El disclaimer lo arma el servidor**
   (`GET /admin/encuesta/disclaimer`), no el JS: es una promesa sobre qué se
   guarda y no puede haber dos versiones. **Fase 2 HECHA**: publicar (fija
   el padrón, una fila por destinatario, y congela el umbral), cerrar
   anticipado, y la pestaña Encuestas del trabajador — responder con
   revisión previa y una sola vez por persona. En una NOMINAL el vínculo
   respuesta→persona vive en `RespuestaNominal`, tabla aparte y con la
   flecha apuntando a la urna: así `RespuestaEncuesta` sigue sin ninguna
   columna que lleve a alguien y el anonimato de las anónimas no depende de
   acordarse de dejar un campo en NULL. **Fase 3 HECHA**: publicar deja al
   admin en el paso de **avisar** (publicar una encuesta y que nadie se
   entere de que existe es la falla más cara), con la notificación al
   **padrón fijado** —nunca a un criterio elegido aparte, si no "leídas /
   no leídas" se mediría contra otro universo que "respondieron"—, la
   noticia pública con la misma vigencia que la encuesta, y el
   recordatorio, que va **solo a los que faltan** (se sabe del padrón, sin
   mirar la urna: funciona igual en las anónimas) y **uno por día**: cuatro
   recordatorios y el afiliado apaga las notificaciones de la app, y ahí se
   pierde el canal para todo. Los borradores de esos textos los arma el
   servidor (`encuestas.texto_aviso` / `texto_noticia`, vía
   `GET /admin/encuesta/avisos`) por lo mismo que el disclaimer: el
   lanzamiento y el recordatorio tienen que decir lo mismo sobre el
   anonimato. El aviso lleva al afiliado a responder **solo mientras la
   encuesta siga abierta**. **Fase 4 HECHA**: el dashboard de cada encuesta
   (`/admin/encuesta/<id>/resultados`, sección `encuestas_resultados`, con
   los agregados en `resultados_encuesta.py` — es a Encuestas lo que
   `dashboard.py` al Panel Sindical). Abre con los cuatro indicadores
   (participación, avisos leídos, ritmo y estado) y debajo un gráfico por
   pregunta, con filtros por los cortes que ESA encuesta guardó. Tres cosas
   que no son de la pantalla sino del servidor: **el umbral se aplica en el
   SQL** —un grupo anónimo por debajo del mínimo no se calcula ni viaja, y
   solo rige en las anónimas, porque en una nominal el admin ve respuesta
   por respuesta con nombre y apellido (es lo que el CSV nominal entrega)—,
   **el recorte por seccional (N18)** —la seccional ahora VE la encuesta
   central, con el filtro de su seccional impuesto desde la sesión, y
   `_exigir_alcance_encuesta` le frena editarla, publicarla, cerrarla,
   borrarla o duplicarla aunque arme el POST a mano— y **lo que ve el
   afiliado al cerrarse** (N12): totales generales, sin cortes y sin los
   textos libres, que se sacan en el servidor. La curva de ritmo se cuenta
   sobre una PREGUNTA TESTIGO (una obligatoria de las que dejan una sola
   fila por persona): contar filas de la urna contaría opciones, no gente.
   **Fase 5 HECHA**: exportar y evolución. El CSV sale del MODO de la
   encuesta y no de un parámetro (N20): en una **nominal**, una fila por
   persona con nombre, CUIL y respuestas —todo el padrón, con columna
   "Respondió", porque la lista de los que faltan es media razón para
   bajarlo—; en una **anónima**, solo conteos y porcentajes con el umbral
   ya aplicado, nunca fila por respuesta: si saliera crudo, cualquiera
   filtra "Rosario + Empresa X" en la planilla y se queda con dos filas que
   identifican a dos personas. El archivo baja el grupo que se está viendo
   (los filtros lo acompañan) y **cada descarga queda en el historial**
   (quién, cuándo, qué y cuántas filas): si algún día se filtra una
   planilla, es lo único que permite saber de dónde salió. La **evolución**
   (N23) compara las tomas sucesivas del mismo linaje —`duplicar_encuesta`
   aplana el `origen_id` a la raíz, así que la familia sale de una
   consulta—, emparejando preguntas por orden y tipo, con el umbral de cada
   toma: una toma chica no aporta punto en vez de aportar uno que
   identifique gente. La **tarjeta del afiliado** contesta antes de entrar
   las tres preguntas que hacen que una encuesta se postergue —y postergada
   es no respondida—: si es anónima, cuántas preguntas tiene y cuántos
   minutos lleva (`encuestas.minutos_estimados`, redondeando para arriba:
   prometer de menos es peor), más la barra de avance del PERÍODO con los
   días que faltan, contados en el servidor y no con el reloj del teléfono.
   La única tarjeta a todo color es la abierta y sin responder: si todas lo
   fueran, ninguna resaltaría. Y el panel de Encuestas se abre en **dos
   pastillas** (ver/editar y crear, namespace `.enc-subtab` propio como el
   resto de las sub-pestañas): el constructor es largo y dejaba la lista tan
   abajo que parecía otra sección. Arranca en la lista salvo que no haya
   ninguna encuesta todavía. **Fase 6 HECHA, sprint cerrado**:
   `demo_encuestas.py` siembra 96 afiliados sintéticos y **tres tomas de la
   misma encuesta** en el tiempo, con una historia que se puede contar en
   voz alta mirando la pantalla (el clima mejora, la preocupación se corre
   del sueldo a la seguridad, y Córdoba mejora menos que Rosario para que
   el filtro por seccional muestre algo), más una nominal abierta. El
   módulo no se puede mostrar con tres afiliados: el umbral escondería todo
   y la evolución no existiría. En la demo, Prensa Central arma encuestas Y
   lee resultados y Prensa Córdoba SOLO lee, que es lo que muestra que las
   dos secciones de N17 no son la misma cosa.
   **Ampliación del dashboard (2026-09-12, pedido de Sd probando La
   Bancaria)**: los filtros pasaron de desplegables a **pastillas
   multi-selección** (un `<select>` esconde las opciones y no deja combinar)
   con la cantidad de GENTE al lado de cada una —contada sobre la pregunta
   testigo, porque contar filas de la urna decía 125 donde hay 15—, más un
   **calendario** de rango sobre el día que guarda la urna (recorta los
   gráficos y el ritmo, nunca el padrón, que no sabe cuándo respondió cada
   uno). Cada pregunta se puede ver en **barras, torta o tabla** —la tabla
   es la que da los números exactos— y la escala muestra mediana y extremos,
   no solo el promedio. Y lo central: **tocar una respuesta abre el cruce**
   (`/admin/encuesta/cruce`), que dice DÓNDE se concentra comparando contra
   el general ("Algo tenso: 44% en Sede central contra 29% general, +15").
   Contra los cortes siempre; **contra las otras preguntas solo en las
   nominales**, porque eso exige saber que dos respuestas son de la misma
   persona y en una anónima esa unión no existe — la pantalla lo explica en
   vez de disculparse. El umbral y el recorte por seccional (N18) rigen
   también ahí: si el cruce los ignorara, bastaría con tocar una barra para
   saltearlos.
   Y los filtros son **asociativos**: al elegir un empleador que deja 10
   casos, las pastillas de los demás cortes se recalculan contra ese recorte
   ("Córdoba 3 / 11") en vez de seguir mostrando el total, que es un número
   que miente justo cuando se lo está mirando. Cada corte se cuenta con los
   OTROS filtros y no con el suyo —si no, quedaría una sola pastilla y no
   habría con qué cambiar de opinión—, salvo la seccional IMPUESTA por N18,
   que sí se filtra a sí misma para no dejar leer de refilón cuánta gente
   respondió en las otras.
   **Mapa de participación por seccional (2026-09-13)**: las burbujas del
   Panel Sindical, aplicadas a otra pregunta. El tamaño es cuánta gente
   respondió y el color qué porcentaje de SU padrón es eso, con escala fija de
   0 a 100% —una participación del 70% tiene que verse igual de oscura con el
   filtro puesto que sin él—. Sale del **padrón** fijado al publicar y no de
   la urna, porque es el único que sabe a cuántos se les preguntó: sin
   denominador no hay porcentaje (y por eso puede diferir de la pastilla, que
   cuenta respuestas en la urna con la seccional congelada al responder; la
   pantalla lo dice). Tocar una burbuja llama al MISMO `alternar('seccional')`
   que la pastilla, así que no hay dos estados que se desincronicen. Como en
   el Panel, **ignora su propio filtro** (es el selector) pero **no el
   impuesto por N18**, y no existe si la encuesta no guarda el corte de
   seccional.
   **Detalle completo en HISTORIAL.md** ("Módulo Encuestas").
   Lo central: el anonimato se sostiene por la FORMA de las tablas (padrón
   y urna separados, sin vínculo posible), no por un cartel.

## Planes de Render desde la app (solapa "Planes" de `/entornos`)

Sube y baja el plan del servicio web y de Postgres, ahora o en un horario
fijo. Existe porque el tráfico de esta app es muy desparejo (días de
liquidación contra fines de semana con veinte veces menos gente) y Render
prorratea por segundo: tener el plan grande solo las horas que hace falta es
plata real. Antes se hacía a mano en la consola de Render.

**Solo en Pruebas.** Cambiar de plan reinicia el web y deja la base cerca de
un minuto devolviendo error; en Demo la solapa aparece deshabilitada y las
rutas rechazan el intento aunque se las llame a mano.

- `actualizar_planes_render.py` → `data/render_planes.json`: el catálogo con
  precios, leído de render.com/pricing. **Ningún precio está escrito a
  mano**, y el archivo guarda la fecha de lectura, que la pantalla muestra.
  Si Render cambia el maquetado, el script falla y deja el JSON anterior
  intacto en vez de inventar. Para refrescarlo: `python actualizar_planes_render.py`.
- `render_planes.py`: carga ese catálogo y le da formato. `workers_para()`
  traduce plan → `--workers` (uno por núcleo).
- `render_admin.py`: `estado_planes()`, `aplicar_plan_web()`,
  `aplicar_plan_db()`. **Al bajar de plan los workers bajan primero; al
  subir, después** — el estado intermedio "muchos workers sobre poca CPU" es
  la peor combinación medida en todo el informe de carga (test 2).
- `planificador.py`: hilo que aplica las reglas semanales. Corre adentro de
  la app y no en un Cron Job de Render (un servicio más que se factura,
  justo lo que se quiere ahorrar). Contrapartida dicha en la pantalla: si el
  web está caído a esa hora, ese disparo se pierde; hay 10 minutos de
  gracia para cubrir un reinicio. Seguro con varias instancias: el reclamo
  de cada regla es un UPDATE condicional (`db.reclamar_plan_programado`).
- Tablas `PlanProgramado` y `CambioPlan` (migración `c5f1a2d70b39`). La
  bitácora importa: para las bases de datos Render **no expone historial de
  planes**, así que sin ella no habría cómo saber por qué cambió el gasto.
- Tests: `test_planes_render.py` (24, sin tocar la API real).

## Validaciones en formularios de Trámites
Capa de validaciones acordada 2026-09-01, cuatro fuentes: `fija` (valor
prefijado), `lista` (datos del admin), `sistema` (padrón/recibos), `externa`
(API catalogada). **Fase 1 HECHA** (fija + consistencia entre dos campos);
fases 2–4 anotadas en BACKLOG.md con decisiones cerradas. Reglas vigentes:

- **No son tipos de dato**: capa componible sobre el campo (0..N por campo),
  cada una con `bloquea` (frena con mensaje) o `avisa` (pasa y queda en
  `Tramite.advertencias` para el operador).
- **Motor en `validaciones_tramite.py`**, puro y sin DB. Una validación mal
  formada NO se guarda (saneo en el alta, como `error_de_expresion`).
- **`evaluar_envio()` es LA única implementación**: la usan el envío real
  (`/api/tramite` y su espejo de empresa), el banco de pruebas del
  constructor (`POST /admin/tramite-tipo/probar`) y su espejo JS en vivo del
  trabajador (cortesía; el servidor decide).
- **Reglas de consistencia referencian campos POR ORDEN, no por id** (editar
  un tipo reemplaza los campos). En el constructor JS guardan referencias de
  objeto y se convierten a índice al serializar.
- **UI**: constructor con estética "Expediente" (lomo numerado, sellos
  BLOQUEA/AVISA, teléfono del afiliado con banco de pruebas editable);
  trabajador con carátula de marca, progreso, validación on-blur y sello
  "ENVIADO" al presentar. Mockup rector en
  `disenos/constructor-tramites-propuestas.html`.
- En la fase `lista`: se guardan **hechos, no derivados** (fecha de
  afiliación, no "antigüedad").

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
- **El "hoy" del panel lo dice el SERVIDOR** (`data-hoy` en `<main>`,
  2026-09-13), no `new Date()`: todo el rango cuelga de esa constante y el
  servidor valida contra la hora de Buenos Aires, así que un dispositivo
  adelantado pedía "mañana" y el panel quedaba con todo en "—" tras un 422
  mudo. Es la regla de `fechas.py` del lado del cliente. Y como red, **un
  rechazo del servidor se ve**: el `detail` del 422 se muestra en un cartel
  arriba de los KPIs y en cada panel, en vez de morir en un `catch`.
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

## Áreas, permisos y ruteo de trámites (Áreas V2)
Rama `areas-permisos-v2`, **sin desplegar todavía**. Plan completo en
[`SPRINT_AREAS_V2.md`](SPRINT_AREAS_V2.md) (decisiones N1–N11); narrativa en
HISTORIAL.md. Lo esencial:

**Dos ejes que se cruzan.** El **área** dice QUÉ hace un usuario (qué
secciones del panel toca, qué trámites le caen); la **seccional** dice
SOBRE QUIÉNES (qué padrón, qué trámites, a quién puede notificar). Un
usuario y su área tienen que ser de la MISMA seccional — lo fuerzan las
rutas.

**`modulos.py` vs `permisos.py`.** No son lo mismo y es la decisión central:
`modulos.py` dice qué **contrató** el sindicato (lo decide plataforma);
`permisos.py` dice qué puede **tocar** cada usuario dentro de eso (lo decide
el Super Admin). Un módulo abre varias secciones — "recibos" abre seis — por
eso el permiso se guarda por sección, no por módulo. El efectivo es
`((área + agregados) - bloqueados) ∩ secciones_de_modulos`: el bloqueo le
gana al área y también a un agregado individual.

**Gateo fail-closed de las rutas.** `main.PERMISOS_RUTAS` mapea las 73 rutas
`/admin/*` a su sección y se resuelve dentro de `exigir_sindicato()` por
`request.scope["route"].path`. Una ruta que nadie clasificó **se rechaza**:
el olvido se nota, no se filtra. Las únicas exentas están en
`RUTAS_ADMIN_SIN_PERMISO` (login, salir, portada, panel, dashboard).

**Alcance de seccional** (`db.alcance_seccional`): `None` = todas,
`{id}` = esa sola, `set()` = ninguna (defensivo). Una sola regla para los
tres roles, y se aplica **dentro de la consulta**, no filtrando después.

**Ruteo de trámites.** El formulario declara a qué área cae: mapa explícito
por seccional (`DestinoTipoTramite`) y, para las seccionales que nadie
mapeó, un `area_destino_default_id` **obligatorio** — sin él una seccional
nueva dejaría trámites sin dueño y en silencio.

**Pase entre áreas.** Solo si el formulario lo declara (`permite_pase`) y
solo hacia la lista **cerrada** de `PaseTipoTramite`: el circuito se diseña
de antemano y es auditable. El área que derivó conserva LECTURA. Todo pase
va al chat del trabajador nombrando **áreas, nunca personas**.

**Responder y cambiar el estado son un solo acto.** No hay ruta separada de
cambio de estado: `agregar_nota_tramite(..., estado_nuevo=...)` deja UN solo
evento en el chat. Antes, un mismo acto aparecía dos veces.

## Seccionales del sindicato
Modelo `Seccional` (db.py): sindicato_id, nombre, `ve_todas`, **domicilio
estructurado con coordenadas** (ver "Georreferenciación") y contacto
(teléfono, WhatsApp, mail, horario). Alta guiada en `/admin` → Seccionales
(crear y borrar, solo Super Admin; editar y ubicar, también el Admin de
Seccional sobre la suya). `Trabajador.seccional_id` opcional. Noticias y Beneficios pueden dirigirse
por seccional (`destino_seccionales`, lista vacía = todas) — detalle en
HISTORIAL.md.

Desde Áreas V2 dejó de ser un dato descriptivo: la seccional **acota** lo
que un usuario ve (sus trámites, a quién puede notificar, qué padrón toca).
`ve_todas` es la excepción — nace tildada en "Sede Central" y sus usuarios
alcanzan todas las seccionales del sindicato.

## Georreferenciación de Seccionales y domicilios (2026-09-12)
Las Seccionales y el domicilio del afiliado tienen **el mismo bloque de
campos** (`geo.CAMPOS_DOMICILIO`: calle, numero, piso_depto, localidad,
provincia, codigo_postal, direccion_texto, latitud, longitud, precision_geo,
geo_actualizado), la misma carga guiada y la misma función de guardado. Un
test verifica que las dos tablas no se separen. Detalle en HISTORIAL.md.

**Qué se exige de cada uno (2026-09-13, decisión de Sd).** No es lo mismo, y
por eso son dos listas en `geo.py`:
- **Seccional: dirección completa y el globo en la puerta.**
  `OBLIGATORIOS_SECCIONAL` (provincia, localidad, calle, altura) +
  `precision_geo` en `PRECISIONES_SECCIONAL` = `exacta` o `manual`. Son
  pocas, las carga el sindicato y una sola vez, y el afiliado usa ese punto
  para ir: un centroide de localidad lo manda al centro de la ciudad sin
  avisarle. `aproximada` NO alcanza -- la diferencia con `manual` no son los
  metros sino que alguien miró el mapa y responde por el punto. Y `manual` es
  la vía de escape que mantiene en pie la otra regla: si Georef y Nominatim no
  responden, el asistente abre el mapa igual (`geo.CENTRO_ARGENTINA`) y el
  punto se marca tocando, así que **ninguna API de terceros bloquea el alta**.
- **Afiliado: provincia y localidad, nada más** (`OBLIGATORIOS_AFILIADO`). Es
  lo que el sindicato necesita para agrupar y dirigir por zona; exigirle la
  altura y un globo a quien se registra desde el teléfono es perderlo en el
  alta. Lo fino se muestra marcado "(opcional)". Rige en las CUATRO puertas por
  las que entra un domicilio -- alta manual del admin, alta masiva (por línea:
  las incompletas quedan afuera y la pantalla dice cuántas, nunca en silencio),
  registro del afiliado y su perfil --, con `geo.faltan_campos` como única
  implementación. En el registro el domicilio se guarda **como un bloque**:
  reemplaza entero al que hubiera o no toca la fila, nunca se fusiona campo por
  campo (así no aparece una calle de Rafaela con la localidad de La Plata).

- **La geocodificación es SIEMPRE del lado del servidor, con caché.** Nunca
  desde el navegador: así se controla la tasa (Nominatim permite 1 pedido por
  segundo y bloquea por IP al que se pasa), se cachea en `GeoCache` (TTL 90
  días) y el día que una de las dos APIs cambie el formato se arregla en un
  archivo y no en el JS de cuatro pantallas.
- **A Nominatim NO se lo autocompleta tecla a tecla.** Se geocodifica solo
  cuando una persona aprieta "Buscar". Las sugerencias de localidad en vivo
  salen de **Georef**, cuya política lo permite y que existe para eso.
- **Sin claves ni cuentas**: Georef (`apis.datos.gob.ar/georef/api`) y
  Nominatim (OSM) son públicas. Lo único que piden es un User-Agent que
  identifique la app, que es `geo.USER_AGENT`.
- **Ningún fallo de esas APIs bloquea un alta.** Sin respuesta, la fila se
  guarda `sin_geo` con un aviso; el panel la marca como pendiente. Una
  seccional sin ubicar es un estado válido del sistema.
- **Sin coordenadas válidas no hay precisión que valga**: `campos_para_guardar`
  fuerza `sin_geo`. Una fila que dice "exacta" con lat/lon en NULL es peor que
  una que admite no estar ubicada. Las cuatro son `exacta` / `aproximada` /
  `manual` (alguien arrastró el globo) / `sin_geo`.
- **La ubicación del trabajador es EFÍMERA y solo vive en el navegador.** En
  "Seccionales cerca de mí" el permiso se pide al tocar el enlace (nunca al
  abrir la app), la posición se usa para ordenar la lista y se descarta: **no
  viaja al servidor ni se guarda**. La distancia la calcula el cliente
  (haversine en `mapa.js`). Negar el permiso no rompe nada: se mide desde el
  domicilio guardado y, sin domicilio, se ordena por provincia.
- **Leaflet va VENDOREADO** en `static/vendor/leaflet/` (jamás CDN, mismo
  criterio que Chart.js) con el sello `?v=` obligatorio de `/static/`. Las
  **teselas de OSM no se cachean** (su política) y **el service worker sigue
  sin cachear nada**: sin conexión se muestra la dirección en texto.
- El mapa del Panel Sindical (`GET /admin/dashboard/seccionales-geo`) devuelve
  **solo agregados** — seis indicadores por seccional— y **ignora el filtro de
  seccional**, porque el mapa ES el selector. Escala de color fija de la app,
  no la marca del sindicato.
- **Los dos mapas de tablero dibujan la MISMA burbuja** (`MapaMT.burbuja`,
  2026-09-13): el TAMAÑO es una cantidad, el BORDE el color de la escala, el
  RELLENO dice si está seleccionada (el destacado del panel, fucsia por
  default) y adentro va el logo del sindicato en marca de agua. Son `divIcon`
  de Leaflet y no `circleMarker` — un círculo de SVG no lleva una imagen
  adentro sin un `<pattern>` por marcador. La forma, la escala
  (`MapaMT.ESCALA`) y el diámetro (raíz cuadrada: el ojo compara áreas) viven
  en `mapa.js`, y el cromo (`.mapa-panel`, `.mapa-leyenda`, `.mapa-pop`,
  `.mt-burbuja`) en `marca.css`: un mapa nuevo los usa, no los copia.
- El alta masiva de trabajadores **no geocodifica**: cien direcciones a un
  pedido por segundo son cien segundos colgado. Las ubica después el botón
  "Georreferenciar pendientes", en segundo plano, con el avance en la tabla
  `GeoPadron` (en la base y no en memoria: Render corre un worker por núcleo).

## Áreas y Usuarios del sindicato (self-service)
`/admin` → pestaña "Áreas y Usuarios" (antes "Administradores"), con dos
sub-pestañas: **Áreas** (alta, perfil de permisos y activación) y
**Usuarios** (alta/edición/activación de `UsuarioSindicato`, con su rol,
seccional y área). Scopeada siempre al `sindicato_id`, y para un Admin de
Seccional además a SU seccional. Solo la ven los dos roles de administrador
— es la única sección que NO se puede asignar a un área
(`permisos.SECCION_SUPER_ADMIN`, a propósito fuera de `SECCIONES`).
Cambiar la clave de un usuario YA EXISTENTE sigue siendo solo vía
plataforma. No se puede desactivar al último administrador activo —
detalle en HISTORIAL.md.

## Alerta de posible adulteración en recibos
`extractor.extraer()` evalúa señales de edición en totales/CUIL/CUIT/fechas
(alta certeza únicamente). No bloquea al trabajador; guarda el archivo en
`ReciboSospechoso`, visible solo por el admin de **plataforma** en "Recibos
con alerta" — detalle en HISTORIAL.md.

## Versionado
`version.py`: `VERSION_TRABAJADOR`/`VERSION_ADMIN`/`VERSION_PLATAFORMA` +
`FECHA_VERSION`. **La versión se sube sola en el mismo commit** (regla 3 de
`FLUJO.md`, reescrita 2026-09-05): solo arreglos → +1 al patch; funcionalidad
nueva → +1 al minor y el patch vuelve a `01` (ej. 0.28.02 → 0.29.01). Sube
SOLO la app que se tocó (Trabajador, Admin o Plataforma); las otras quedan.
Sd decide solo cuando hay duda de si algo cuenta como funcionalidad nueva.
Antes de escribir el número, `git fetch` y mirar `origin/main:version.py`:
otra rama puede haber movido otra app.
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

## Seed histórico de AEFIP: ya no se siembra solo
`db.init_db()` NO llama más a `cargar_seed_si_vacio()` (arreglado 2026-09-03
en la Etapa 0 de entornos): una base creada desde cero queda vacía hasta
`cargar_demo.py` o un alta desde /plataforma. Antes aparecía un sindicato
"AEFIP" fantasma con id=1, justo el caso de la base nueva de Pruebas. La
función sigue existiendo solo a pedido explícito.

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
- Autodiagnóstico: `python chequeo.py`
- Cargar demo: `python cargar_demo.py` (¡correr alembic upgrade head antes si es Postgres!)
- Migraciones: `alembic upgrade head` (aplicar) / `alembic revision --autogenerate -m "msg"` (crear)
- Promover a la demo: `python promover_demo.py` (o `--solo-pr`). Nunca
  pushear a `demo` a mano.
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
- **Los tests SIEMPRE con pytest**: `python -m pytest test_x.py`, nunca
  `python test_x.py`. Corriendo el archivo directo, el módulo se importa
  como `__main__` ANTES de que pytest cargue `conftest.py`, así que el
  engine queda apuntando a la base del `.env` — la de desarrollo, con datos
  de verdad — y el test la llenaría de basura. `conftest.py` detecta ese
  caso y corta con un mensaje, pero la regla es más simple: pytest siempre.
- Si pytest muere de mala manera quedan bases `mitrabajo_test_*` sueltas:
  `python chequeo.py --limpiar-bases-de-test` las borra.
