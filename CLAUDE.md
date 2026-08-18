# CLAUDE.md — Mi Trabajo

Contexto del proyecto para Claude Code. Se lee al inicio de cada sesión.
Mantener este archivo actualizado cuando cambien decisiones o el estado.

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
  nunca se desloguea solo.
  NO se usa auth de terceros.
  **Cookie de sesión separada por rol (fix 2026-08-16)**: los tres roles
  (`sindicato`, `plataforma`, `trabajador`) usaban una única cookie
  (`sesion_mitrabajo`) para los tres. Una cookie es del navegador entero, no
  de una pestaña: loguearse con un rol en una pestaña pisaba en silencio la
  cookie que otra pestaña, con otro rol, necesitaba -- reportado como "vuelvo
  a la pestaña de admin después de un rato y me dice que tengo que loguearme,
  aunque activo". **Esta era la causa real** del síntoma que se había
  atribuido (sin confirmar) a un corte de conexión de Postgres en Render, ver
  más abajo. Fix: `COOKIES_POR_ROL` (main.py) mapea cada rol a su propia
  cookie (`sesion_sindicato`/`sesion_plataforma`/`sesion_trabajador`);
  `sesion_actual(request, rol)` pide el rol explícito y lee solo esa cookie
  (ya no hay una sesión "genérica" del navegador); `exigir_sindicato`/
  `exigir_plataforma` son los helpers que las rutas usan para exigir sesión
  de un rol puntual. El middleware de renovación recorre las tres cookies y
  renueva cada una que esté presente y vigente, así una request de cualquier
  pestaña mantiene vivas TODAS las sesiones de rol que el navegador tenga
  activas a la vez, no solo la de esa pestaña. Efecto colateral esperado,
  una sola vez al deployar: quien tuviera una sesión activa con la cookie
  vieja queda desloguead@ (hay que volver a entrar).
  **JSON crudo en pantalla al fallar un POST de página completa (fix
  2026-08-16, 2 rondas)**: los `<form>` de `/admin` y `/plataforma` son POST
  de página completa, no fetch. Si la ruta respondía con una excepción --
  sesión vencida (`HTTPException` 403/401) o cualquier otra sin manejar (ej.
  un 500 por un hipo transitorio) -- el navegador reemplazaba TODA la
  pantalla por el JSON crudo de FastAPI ("error técnico feo en pantalla
  negra"). Dos manejadores nuevos en main.py, usando el mismo criterio
  (`_es_navegacion_de_pagina`: pide `text/html`, no es una llamada fetch/JS
  que ya sabe leer el JSON con `await r.json()`; y `_panel_de(path)`/
  `_rol_de(path)`, a qué pantalla y rol corresponden según el prefijo de la
  ruta):
  - `sesion_vencida_o_denegada` (`@app.exception_handler(HTTPException)`):
    con sesión inválida/inexistente del rol que esa pantalla necesita Y
    navegación real, redirige a `/admin` o `/plataforma` (login) en vez del
    JSON. Un 403 legítimo con sesión VÁLIDA del rol correcto (módulo no
    habilitado, CUIL ajeno, etc.) no se toca.
  - `error_no_manejado` (`@app.exception_handler(Exception)`, ya existía
    para garantizar JSON siempre): con navegación real, además redirige al
    panel (`/admin?error=guardado` o `/plataforma?error=guardado`, con un
    aviso "No se pudo guardar, probá de nuevo") en vez del JSON crudo.
  - **Ojo**: originalmente se sospechaba que el 500 intermitente reportado
    ("se corta a los 2-3 minutos, específicamente al guardar") era Postgres
    en Render cortando conexiones ociosas -- el engine (db.py) usa
    `pool_pre_ping=True` + `pool_recycle=300` + keepalives de TCP por las
    dudas, mitigación que se mantiene por las dudas pero **no era la causa
    real**: un repro concreto del usuario (dos pestañas, roles distintos)
    apuntó a la cookie compartida de arriba. Si vuelve a aparecer un 500 sin
    relación a pestañas/roles, revisar los logs de Render (traceback
    completo con `traceback.print_exc()` en `error_no_manejado`).
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
- cargar_demo.py — carga 2 sindicatos de demo desde cero (sin AEFIP).
- chequeo.py — autodiagnóstico de la instalación.
- migrations/ — Alembic (env.py + versions/: esquema inicial y logo).
- alembic.ini — config de Alembic.
- templates/ — 9 HTML (trabajador, portada, admin, plataforma, sus logins, selector,
  verificación pública de credencial).
- static/ — 2 SVG base + marca.css (sistema de diseño compartido, ver más abajo).
  (Ya NO existe static/logos/: los logos van en la base.)
- data/seed_aefip.json — semilla histórica; ya NO se carga por defecto.
- .claude/skills/diseno-mi-trabajo/ — skill con las reglas del sistema de diseño
  (paleta, tipografía, portada oscura/interiores claros); .claude/skills/frontend-design/
  — skill oficial de Anthropic para dirección visual general.

## Los tres roles
1. Admin de plataforma — /plataforma con CUIT + PLATAFORMA_PASSWORD. Da de alta
   sindicatos (con marca y logo) y sus admins.
2. Admin de sindicato — /admin con CUIT + clave. Gestiona conceptos, fórmulas,
   trabajadores y reportes SOLO de su sindicato (aislamiento total). El login
   redirige a /admin/inicio, una portada de tarjetas (ver "Rediseño de
   interfaz" más abajo); desde ahí se entra a /admin, que sigue siendo el
   panel de siempre con sus 11 secciones.
3. Trabajador — /ingresar con CUIL + clave. Identidad única (un CUIL para toda la
   plataforma). Empadronamiento por sindicato: si el CUIL está en varios, elige;
   la app se pinta con la marca del elegido. Después de elegir (o directo, si
   está en uno solo) entra a /app/inicio, la portada (ver "Rediseño de interfaz"
   más abajo). Desde ahí navega a /app, que sigue siendo Tu Recibo con sus 5
   pestañas (Tu Recibo default, Credencial si hay marca activa, Novedades, Mis
   Aportes/semáforo, Capacitación).

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
- Empresa multisindicato (ambos): CUIT 30111222339 — ver "Empleadores" más abajo.

## Decisiones tomadas (no rediscutir sin motivo)
- **Motor: Render Postgres** (no Supabase). La app ya tiene auth propia, que es el
  mayor valor de Supabase; el Storage se resolvió guardando logos en la base.
  Migrar a Supabase después sería barato (pg_dump/restore, solo cambia DATABASE_URL).
- **Datos desde cero:** la demo arranca limpia, sin AEFIP. En producción los
  sindicatos se dan de alta desde el panel de plataforma.
- **Logos en la base (Opción B):** columnas logo_datos (bytes) + logo_mime en
  Sindicato; se sirven por la ruta /logo/{id}. Eliminó la necesidad del disco
  persistente (ya se borró el disco de Render). El campo `logo` es un flag no vacío.
  La URL del logo lleva ?v={tamaño} como sello de versión para romper cache al
  editar, y la ruta responde con Cache-Control no-cache.
- **JSON como JSONB en Postgres:** columnas alias (Concepto) y detalle (Reporte)
  son jsonb (indexables). En SQLite quedan JSON común.
- **Aislamiento entre sindicatos: total.** Marca por sindicato: 4 colores
  (`color_base`, `color_primario`, `color_acento`, `color_secundario`), inyectados
  como `--marca-base/primario/acento/apoyo` en cada plantilla. `color_base` es el
  único validado como oscuro (`_es_oscuro()` en main.py, umbral de luminancia
  percibida < 140/255) — es el fondo de la portada del trabajador y de todos los
  encabezados oscuros; si no es oscuro, el alta/edición de sindicato se rechaza.
  El semáforo NUNCA toma la marca (colores fijos de estado: verde=pagado,
  amarillo=parcial, rojo=impago).
- **Semáforo ARCA:** el trabajador va a ARCA con un botón, resuelve el captcha él
  mismo y sube la captura/PDF; la IA la lee. NO se automatiza el captcha (frágil y
  zona gris legal). ARCA cubre jubilación y obra social, NO ART. Parser hecho y
  probado (estados pagado/parcial/impago/no_presentada/no_declarado).
- **Tamaño de logos, unificado en 76px (2026-08-14):** el logo de plataforma
  en los 4 logins (`admin_login.html`, `plataforma_login.html`,
  `trabajador_login.html`, `elegir_sindicato.html`, clase `.logo-recuadro`)
  y el logo del sindicato en el resto de las pantallas (`portada.html` vía
  `.enc .logo`/`.enc .logo-fallback` en marca.css, `verificar_credencial.html`)
  comparten el mismo tamaño de 76px. En trabajador.html y admin.html, donde
  el logo de plataforma y el del sindicato conviven en el mismo header
  (`.logo-plataforma-header` + `.sind`), se agrandaron los DOS juntos para
  que no queden desparejos entre sí.
- **Sin fondo blanco forzado + reducción en mobile (2026-08-15):** todas las
  clases de logo de plataforma/sindicato (`.logo-recuadro`, `.enc .logo`,
  `.logo-plataforma-header`, `.sind`/`.sind-wrap img.sind`, `.cred-logo`,
  `.head img` de `verificar_credencial.html`, `header img` de
  `plataforma.html`) perdieron el `background:#fff`/`border-radius`/`padding`
  que traían — un PNG con fondo transparente ahora se ve transparente de
  verdad. Si un sindicato quiere que su logo tenga un fondo de color, lo tiene
  que subir ya con ese fondo incluido en el archivo. Excepción a propósito:
  `.enc .logo-fallback` (el círculo con iniciales que se muestra cuando NO hay
  logo cargado) conserva su fondo — no es un logo real, es un placeholder.
  También se agregó `@media (max-width:600px)` a las clases que forman parte
  del set de 76px (no a `.cred-logo` ni a `header img` de `plataforma.html`,
  que quedaron fuera de esa unificación): en mobile bajan a 61px (76×0.8).

## Estado actual
Migración a Postgres COMPLETA y desplegada en Render, mergeada a main. Verificado
en producción: 3 logins, aislamiento, pluriempleo, 4 pestañas, alta/edición de
sindicato, logos en base (con fix de cache aplicado). Disco persistente eliminado.

Rediseño de interfaz COMPLETO y mergeado a main: portada nueva + sistema de 4
colores. Ver sección siguiente.

Sistema de módulos habilitables (Fase 1 de "Módulos + Notificaciones +
Trámites") COMPLETO y en main. Ver sección dedicada más abajo.

Notificaciones (Fase 2 del mismo plan) COMPLETO y en main. Ver sección
dedicada más abajo.

Trámites (Fase 3, última del plan) COMPLETO y en main. Ver sección dedicada
más abajo. Las 3 fases de "Módulos + Notificaciones + Trámites" están
terminadas.

## Rediseño de interfaz
Sistema de diseño nuevo (`.claude/skills/diseno-mi-trabajo/SKILL.md`,
`static/marca.css`): portada del trabajador oscura, todo lo demás claro con
encabezado oscuro. 4 colores por sindicato en vez de 3 (ver "Decisiones tomadas").

- **Portada nueva**: `templates/portada.html`, ruta `GET /app/inicio`. Login,
  registro y el selector de sindicato (`/app/elegir/{id}`, `/app/cambiar`) ahora
  redirigen ahí en vez de a `/app`. `/app` (Tu Recibo) NO cambió — sigue siendo
  la misma pantalla con sus 5 pestañas, la portada es una pantalla previa nueva,
  no un reemplazo. Tarjetas: Tu recibo, Mis aportes, Credencial (estado real,
  no placeholder — ya existe la feature), Capacitación ("próximamente").
  Sección Novedades (noticias del sindicato) y Beneficios (carrusel de
  descuentos) — ver secciones dedicadas más abajo, ninguna es ya placeholder.
- **Limitación conocida v1**: las tarjetas de la portada que no son "Tu recibo"
  linkean a `/app` sin saltar directo a la pestaña correspondiente (no hay
  deep-linking por URL a un tab de `trabajador.html` todavía).
- **admin.html y plataforma.html**: encabezado oscuro ahora usa `color_base`
  (antes usaba `color_primario`, que no estaba validado como oscuro). El resto
  de cada panel (tablas, formularios, tabs) sigue claro, sin cambios de fondo.
- Sin tocar: `validador.py`, `semaforo.py`, ninguna lógica de cálculo — el
  rediseño es 100% presentación + la columna `color_base`.

## Portada de /admin y /plataforma (2026-08-16)
Mismo patrón aplicado a los tres logins: una landing con tarjetas (vidrio +
grano + tipografía condensada, colores de marca) antes de entrar al panel
de siempre, que a su vez cambia su barra de pestañas por una tira
horizontal deslizable con ícono + texto chico. Ninguno de los paneles en
sí (los `<div class="panel">`/`<div class="ppanel">` y su lógica) cambió
de comportamiento — es 100% navegación + presentación, igual que el
rediseño del trabajador.

- **`/admin`** — `templates/admin_portada.html`, ruta `GET /admin/inicio`.
  Las 11 secciones (Reportes, Fórmulas, Conceptos, Trabajadores,
  Aprendizaje, Afiliados cotizantes, Noticias, Beneficios, Notificaciones,
  Trámites, Seccionales) ya no entraban en una sola línea de pestañas. El
  login de `/admin` redirige acá primero; tarjetas filtradas por `modulos`
  (mismo criterio que ya usaba la barra), Trabajadores y Seccionales
  siempre visibles, cada una linkea a `/admin#<panel>` reusando el
  deep-link por hash que ya existía en `admin.html` (`abrirDesdeHash()`).
  Encabezado "Hola, {{ primer_nombre }}" con el nombre del `UsuarioSindicato`
  logueado (no del sindicato, que ya está arriba en el `.enc`) — mismo
  patrón que la portada del trabajador. La tarjeta Trámites suma un globo
  rojo (`.badge-noleidas`, mismo componente que Notificaciones en la
  portada del trabajador) con `db.contar_tramites_nuevos()`: cuenta los
  trámites en estado `enviado` (recién presentados, el admin todavía no
  los tocó) de ese sindicato. Dentro de `/admin`, la barra de pestañas
  pasa a `.nav-strip` (una sola línea deslizable) + botón flotante
  "Inicio" al lado del "Salir" que ya existía. Los `RedirectResponse
  ("/admin#...")` de las rutas POST de cada acción no cambian — solo el
  login inicial cambió de destino.
- **`/plataforma`** — `templates/plataforma_portada.html`, ruta
  `GET /plataforma/inicio`, mismos colores que la marca de la plataforma
  (`color_primario` como base, sin un color_base aparte validado como
  oscuro: es una única instancia, no multi-tenant, no hace falta esa red
  de seguridad). 7 tarjetas: "Sindicatos" agrupa las 3 pestañas de alta/
  gestión (Sindicatos, Nuevo sindicato, Nuevo administrador — quedan
  dentro, en la tira de pestañas, pero comparten una sola tarjeta en la
  portada porque son todas gestión de sindicatos), más Cambiar clave,
  Marca de la plataforma, Configuración legal, Uso de IA, Recibos con
  alerta, Topes SS. Sin saludo por nombre (el login de plataforma es una
  clave compartida, no hay un usuario individual con nombre propio como
  en `UsuarioSindicato`). **Bug encontrado y corregido de paso**:
  `plataforma.html` NO tenía un `abrirDesdeHash()` genérico como
  `admin.html` — solo un caso especial para `#topes` (agregado durante la
  feature de Topes SS) — así que las tarjetas nuevas no abrían la pestaña
  correcta. Se generalizó ese bloque a cualquier `data-pp`, conservando el
  caso especial de los errores de topes.
- **Portadas independientes por rol**: `Sindicato.portada_clara`
  (trabajador) y `Sindicato.admin_portada_clara` (admin) son dos columnas
  separadas — un sindicato puede tener, por ejemplo, portada oscura para
  el trabajador y clara para el admin. Las dos se eligen desde `/plataforma`
  → "Sindicatos" (dos checkboxes independientes en el alta/edición).
  `ConfiguracionPlataforma.portada_clara` es una tercera, para la portada
  de `/plataforma` misma, elegida desde `/plataforma` → "Marca de la
  plataforma".

## Rediseño visual "modelo Nike" (COMPLETO)
Segunda vuelta de dirección visual, explorada primero en un Artifact fuera
del repo ("Portada en Dos Tonos") y aprobada por el usuario. Traduce algunos
principios de Nike (contraste tipográfico extremo, disciplina geométrica, una
sola idea de profundidad) a este contexto — **no** son elementos tomados
literalmente de Nike: vidrio/degradé en vez de fotografía, tipografía
condensada, grano sutil (guiño a imprenta/afiche gremial, no al modelo Nike).
Las 4 fases del plan, en main:

- **Fase A**: cimientos puramente aditivos en `static/marca.css` — fuente
  `Barlow Condensed` Bold alojada en `static/fonts/` (licencia SIL OFL, sin
  CDN externo, token `--fuente-display`, solo para títulos/encabezados — el
  cuerpo sigue en `system-ui`), clases de grano (`.grano-osc`/`.grano-clara`,
  SVG `feTurbulence` inline) y variantes vidrio (`.vidrio`/`.vidrio-claro`).
  De paso: `mimetypes.add_type("font/woff2", ".woff2")` en `main.py` —
  algunos Windows no traen ese tipo registrado y `StaticFiles` lo servía
  como `text/plain`.
- **Fase B**: `Sindicato.portada_clara` (bool, default `False`) — la portada
  del trabajador pasa a poder ser oscura (default, sin cambios) o clara,
  elegida por el admin de **plataforma** al dar de alta/editar un sindicato
  (checkbox "Portada clara" en `plataforma.html`, junto al grupo de
  módulos). El encabezado (`.enc`) sigue oscuro en las dos variantes — lo
  que cambia es el fondo del cuerpo y las tarjetas. **No** toca
  `_es_oscuro()`: `--marca-base` sigue siendo obligatoriamente oscuro
  siempre, en las dos variantes de portada.
- **Fase C**: `portada.html` — fondo con degradé radial (oscura) o papel
  (clara, según `marca.portada_clara`), vidrio en tarjetas/noticia-card,
  grano en `<body>`, condensada en el saludo y encabezados de sección.
  `.enc`/`.pad` suman `position:relative; z-index:1;` en `marca.css` para
  quedar por encima del grano (el pseudo-elemento del grano pinta encima
  del contenido estático si no se le da una capa propia).
- **Fase D**: pestaña Trámites de `trabajador.html` (listado "Mis trámites",
  selección de tipo, formulario dinámico, detalle) — mismo tratamiento:
  `.tram-box`/`.tram-box-enc` con vidrio + grano + condensada, clase nueva
  `.tram-item` (capa aparte de `.card`, que es compartida por otras
  pantallas de Tu Recibo — no se tocó `.card` en general).

El sun/moon toggle de modo claro/oscuro en tiempo real para el trabajador
quedó explícitamente pospuesto (no es parte de este plan) — lo que sí es
real es que la portada clara/oscura ahora es una decisión por sindicato,
tomada por plataforma, no un toggle del trabajador.

## Módulos habilitables por sindicato (Fase 1 de "Módulos + Notificaciones + Trámites")
El admin de **plataforma** elige, por sindicato, qué funcionalidades tiene
habilitadas — pensado para modelos comerciales distintos (no todos los
sindicatos van a adoptar todo). Catálogo fijo en `modulos.py` (`MODULOS`
dict + `MODULOS_INICIALES`, los 6 que ya existían antes de este sistema:
recibos, aportes, credencial, capacitacion, noticias, beneficios — más
`notificaciones` y `tramites`, agregados al catálogo ya mismo aunque sus
fases todavía no están implementadas). Se guarda como
`Sindicato.modulos_habilitados` (lista JSON, mismo patrón que
`Concepto.alias`).

- **Alta/edición de sindicato** (`/plataforma`): grupo de checkboxes
  (`.check-modulos`/`.chk-modulo` en plataforma.html), todos los
  `MODULOS_INICIALES` tildados por default en el alta. `editarSind()` los
  puebla con los datos reales del sindicato.
- **Qué controla**: en `portada.html` y en la tabbar de `trabajador.html`
  (`/app`), cada tarjeta/pestaña se envuelve en `{% if 'clave' in modulos %}`
  (contexto armado por `main._modulos_de(sid)`). En `admin.html`, cada
  `tab-btn` + su `panel-*` igual — **Trabajadores y Seccionales quedan
  SIEMPRE visibles**, no dependen de ningún módulo (son la base que usan
  los demás). Si "recibos" está apagado, `trabajador.html` ya no asume que
  esa es la pestaña default: el JS activa la primera pestaña habilitada que
  encuentra en el DOM.
- **El backend rechaza igual, no solo esconde el botón**: `main._exigir_modulo(sid, "clave")`
  (403) al principio de las rutas de Noticias, Beneficios y Aprendizaje —
  mismo criterio que ya usa `_destinos_validos` para seccionales ajenas.
- **Grandfathering**: la migración (`7c7be1978d90`) hace un `UPDATE` que le
  carga `MODULOS_INICIALES` a TODOS los sindicatos que ya existían — nadie
  perdió nada el día del deploy. El default de Python (`Field(default=[])`)
  es vacío a propósito: solo importa para sindicatos creados fuera del flujo
  normal de alta (tests, scripts) — `cargar_demo.py` y los tests pasan
  `modulos_habilitados=list(MODULOS_INICIALES)` explícito.
- Notificaciones y Trámites (Fases 2 y 3 del mismo plan) están completas —
  ver sus secciones dedicadas más abajo.

## Notificaciones (Fase 2 de "Módulos + Notificaciones + Trámites")
Mensajería dirigida del sindicato a un grupo de trabajadores. Modelos
`Notificacion` (mensaje + criterio + snapshot de cantidad) y
`NotificacionDestinatario` (una fila por CUIL, con `leida_en` — la lista de
destinatarios se FIJA al enviar, no se recalcula después). Se agregó
`Trabajador.cuit_empleador` (opcional, lo carga el admin) para poder
targetear "por empresa".

- **Criterios de destinatarios**: `cuil` (lista literal), `cuit_empleador`,
  `seccional` (solo aparece si el sindicato tiene seccionales cargadas), o
  `provincia`. `db.resolver_destinatarios(sindicato_id, criterio, valores)`
  es la única función que resuelve — la usan tanto el preview como el envío
  real, y solo matchea trabajadores ACTIVOS de ESE sindicato.
- **Flujo de envío en admin** (`/admin` → pestaña Notificaciones, solo si el
  módulo está habilitado): el botón "Vista previa" pega a
  `POST /admin/notificacion/preview` (no persiste, solo cuenta) y recién ahí
  aparece "Confirmar y enviar (N)" — el submit real (`POST /admin/notificacion`)
  incluye un adjunto opcional (imagen/PDF/Word, tope `MAX_ADJUNTO_NOTIFICACION`
  = 5 MB, `main._leer_adjunto_notificacion`). El listado de enviadas muestra
  leídos/total por fila; "Ver" abre el detalle de destinatarios (reusa el
  `#modal-recibo-overlay` compartido con Reportes/Afiliados cotizantes,
  poblado por fetch en vez de copiar un `<tr>` oculto).
- **UI trabajador** (`portada.html`): tarjeta "Notificaciones" con
  `#badge-notif` (rojo, oculto si no hay pendientes) — el conteo inicial
  viene server-side (`db.contar_notificaciones_no_leidas`, evita el flash de
  "0"). El click abre un modal (`abrirNotificaciones()`) que trae la lista
  vía `GET /api/mis-notificaciones`; cada card es un acordeón simple —
  expandirla (`toggleNotificacion`) marca leída en el momento
  (`POST /api/notificacion/{id}/leer`) y decrementa el badge en vivo, sin
  recargar. **Estética propia (2026-08-14)**: a diferencia de los demás
  modales de la portada (perfil/noticia/beneficio/acerca, que se quedan con
  el estilo oscuro compartido `.modal-hoja` de marca.css porque conviven con
  el fondo oscuro de la portada), el de Notificaciones usa clases propias
  (`.modal-notif-caja`/`.modal-notif-enc`/`.modal-cerrar-clara`, definidas
  en el `<style>` de portada.html): fondo blanco para el contenido, encabezado
  y acentos (remitente sin leer, links, "Ver adjunto") con los colores de
  marca del sindicato (`var(--marca-base)`/`var(--marca-primario)`/
  `var(--marca-acento)`) en vez de los tokens oscuros `--sup-1`/`--sobre-base`.
  El texto pasa por `_texto_con_links` (mismo autolink+escape que
  Noticia/Beneficio) antes de inyectarse como HTML.
- **Aislamiento**: `marcar_notificacion_leida` solo toca la fila
  `(notificacion_id, cuil)` exacta — el CUIL sale de la cookie de sesión del
  trabajador, nunca de un parámetro que pueda falsearse. Un trabajador en
  pluriempleo solo ve las notificaciones del sindicato que tiene activo en
  ese momento (mismo filtro `sindicato_id` que ya usan Noticias/Beneficios).
- **Adjunto**: no es público como el logo — `GET /notificacion-adjunto/{id}`
  chequea que quien pide sea el admin del sindicato que la mandó, o un
  trabajador que sea destinatario real (403 para cualquier otro).
- Trámites (Fase 3) reusa `db.crear_notificacion(..., origen="sistema")`
  directo (`main._notificar_cambio_tramite`) para avisar automáticamente
  cuando un trámite cambia de estado — el campo `Notificacion.usuario_id` es
  `Optional` a propósito para ese caso (no hay un admin humano detrás). No
  hizo falta una función `_enviar_notificacion_sistema` aparte, como se
  había anticipado al cerrar la Fase 2 — `crear_notificacion` ya admite
  criterio="cuil" con un único destinatario sin cambios.

## Trámites (Fase 3 de "Módulos + Notificaciones + Trámites")
Formularios dinámicos que el sindicato define y el trabajador completa, con
seguimiento por número de expediente. 6 tablas nuevas: `TipoTramite` (con
sus `CampoTramite`, orden + tipo_dato texto/numero/fecha/archivo + reglas de
longitud/decimales/tipos de archivo/obligatoriedad), `Tramite`,
`RespuestaTramite` (lo que cargó el trabajador, un `CampoTramite` = una
fila), `NotaTramite` (ida y vuelta admin↔trabajador, con adjunto opcional
de cada lado), `TramiteLog` (tabla de log explícita — decisión tomada en el
plan, no una vista derivada; `db._log_tramite()` es el único punto que
escribe ahí, llamado desde alta/cambio de estado/cada nota).

- **Número de expediente**: `{código sin espacios}-{año}-{secuencial de 6
  dígitos}`, correlativo por `tipo_tramite_id` (NO se reinicia por año
  aunque el año quede impreso) — se genera y persiste en la misma
  transacción que crea el `Tramite`, con reintento ante colisión (mismo
  patrón que `db.generar_codigo_credencial`).
- **Constructor de tipos de trámite** (`/admin` → pestaña Trámites → sub-
  pestaña "Tipos de formulario"): el admin arma los campos en un builder
  client-side (agregar/quitar/subir/bajar, cada uno con su `tipo_dato` y
  reglas propias) que serializa a `campos_json` (un solo POST a
  `/admin/tramite-tipo` da de alta el tipo Y todos sus campos). Editar un
  tipo **reemplaza** sus campos enteros (no hace merge campo por campo) —
  es el mismo modelo mental que editar un formulario de Google. Borrar un
  tipo con trámites ya presentados está bloqueado (`db.borrar_tipo_tramite`
  devuelve False); la alternativa es desactivarlo (`activo=False`) desde el
  mismo form de edición.
- **Envío del trabajador** (`POST /api/tramite`): los campos vienen con
  nombre dinámico (`campo_{id}` / `archivo_{id}`, uno por `CampoTramite`
  del tipo elegido), así que la ruta lee `await request.form()` crudo en
  vez de declarar parámetros fijos — no hay otra forma de aceptar un
  esquema que varía por tipo de trámite. Valida obligatorios, longitud
  exacta/máxima, formato numérico y extensión de archivo permitida
  server-side ANTES de persistir (el formulario del cliente valida lo
  mismo, pero eso es solo UX — la ruta es la que realmente decide).
- **Estados**: `iniciado → en_tratamiento → respondido → espera_info →
  terminado` (`db.ESTADOS_TRAMITE`/`ESTADOS_TRAMITE_LABEL` -- el primer
  estado se llamaba "enviado" hasta el 2026-08-16, renombrado a "iniciado"
  con migración de datos, ver más abajo). Cambiar el estado o agregar una
  nota **desde el admin** dispara automáticamente una Notificacion
  `origen="sistema"` al trabajador (Fase 2); una nota **del trabajador**
  NO se auto-notifica (no tiene sentido notificarse a sí mismo) — probado
  explícitamente en `test_tramites.py`. **`terminado` es un estado final**:
  ni `db.cambiar_estado_tramite` ni `db.agregar_nota_tramite` (de cualquiera
  de los dos lados) aceptan más cambios sobre un trámite ya terminado --
  ambas funciones devuelven `False` (main.py lo traduce a 400 con mensaje
  explícito); la UI (admin.html y trabajador.html) oculta el selector de
  estado y la caja de notas cuando `estado === 'terminado'`, en vez de
  dejarlos habilitados para que el servidor los rechace igual.
- **UI trabajador** (`trabajador.html`, 6ta pestaña "Trámites", + tarjeta en
  `portada.html`): landing con "Mis trámites" + consulta por número de
  expediente → elegir tipo → formulario dinámico (un input por campo, según
  `tipo_dato`) → al enviar, salta directo al detalle del trámite recién
  creado (no a una pantalla de "gracias" genérica). El detalle es el mismo
  para "Mis trámites" y para la consulta por expediente: estado, respuestas
  presentadas, thread de notas con caja de respuesta, historial. La
  consulta por expediente NO es pública — pide sesión de trabajador y el
  CUIL de la sesión tiene que coincidir con el dueño del trámite
  (`GET /api/tramite/{numero}`).
- **UI admin**: sub-pestaña "Ver trámites" (primera, antes "Trámites
  recibidos" iba segunda -- reordenado el 2026-08-16 porque es la que se
  usa en el día a día; "Crear formularios", antes "Tipos de formulario",
  quedó segunda) con filtro por CUIL/N° de expediente/estado (JS propio, no
  reusa `aplicarFiltro` porque ese helper no compone bien con un filtro por
  `<select>` además de los de texto) y un modal de detalle que permite
  cambiar el estado y agregar notas sin salir de la pestaña — al confirmar,
  refresca el modal Y la fila de la tabla en el mismo re-render
  (`refrescarTramiteDetalle`), sin recargar la página. La pestaña "Ver
  trámites" lleva el mismo globo rojo (`.badge-noleidas`) que ya usaba la
  tarjeta de la portada de admin, contando `db.contar_tramites_nuevos` (
  estado `iniciado`, el admin todavía no lo tocó).
- **Quirk de implementación evitado a propósito**: las sub-pestañas de
  Trámites usan sus propias clases CSS (`.tramite-subtab`/`.tramite-
  subpanel`), NO las mismas `.subtab`/`.subpanel` que ya usa Trabajadores
  — ese listener es global (`querySelectorAll('.subtab')` sin scope), así
  que compartir la clase habría hecho que cambiar de sub-pestaña en
  Trámites también desactivara la sub-pestaña activa de Trabajadores.
  Mismo cuidado en el `<script>`: cualquier inicialización a nivel de
  módulo que toque un elemento del panel de Trámites está guardada con un
  chequeo `if (document.getElementById(...))`, porque el panel entero no
  existe en el DOM cuando el sindicato no tiene el módulo habilitado — un
  acceso sin guardar ahí rompe TODO el `<script>` de admin.html a partir de
  esa línea, no solo la función de Trámites.
- **Bug real encontrado y corregido (2026-08-14)**: los campos tipo
  "archivo" del formulario dinámico de trabajador.html se guardaban bien
  del lado del admin, pero el trabajador no veía ninguna forma de subir el
  archivo — solo la etiqueta. Causa: `input[type=file] { display:none; }`
  es una regla GLOBAL de trabajador.html (pensada para el flujo de Tu
  Recibo, que dispara el input oculto con un `<label class="btn" for=...>`
  estilizado) y también ocultaba, sin querer, los inputs de archivo
  generados dinámicamente para Trámites. Se arregló agregando el mismo
  patrón label+input oculto (con nombre de archivo mostrado aparte) tanto
  al campo tipo "archivo" del formulario como al adjunto de la respuesta
  del trabajador a una nota.
- **Rediseño "recuadro" (2026-08-14)**: las pantallas de Trámites en
  trabajador.html (elegir tipo, formulario dinámico, detalle/consulta) se
  reorganizaron en un componente `.tram-box` — encabezado con
  `var(--marca-base)` (mismo criterio que el resto de la app: header oscuro
  con el color del sindicato) y cuerpo de fondo claro, con los campos/filas
  ocupando el ancho completo del recuadro de forma consistente. Los inputs
  de texto/número/fecha comparten la clase `.tram-input` (antes no tenían
  `width:100%` explícito y quedaban angostos).
- **Tipo de campo "Selección fija" (2026-08-16)**: `CampoTramite.opciones`
  (columna nueva, string, valores separados por coma) además de
  `tipo_dato="seleccion"`. El admin las carga en el mismo input que ya
  usaba "Tipos de archivo" en el constructor de campos (reusa el slot en
  vez de sumar una columna más a una fila ya densa de 9-10 campos --
  `admin.html::renderCamposTramite` cambia el placeholder/target según el
  `tipo_dato` elegido). El trabajador ve un `<select>` con esas opciones
  (`trabajador.html::campoInputHtml`). Validación server-side en
  `main.api_enviar_tramite`: el valor recibido tiene que estar en la lista
  de opciones (si hay opciones cargadas), igual que hoy se valida longitud/
  tipo de archivo para los otros `tipo_dato`.
- **Cebra en el historial (2026-08-16)**: `.tramite-log-item` (admin.html)
  y `.tram-log-list .fila` (trabajador.html) alternan un tinte muy leve
  (`color-mix(... 6%, transparent)`) entre dos colores de marca del
  sindicato en vez de un fondo plano, para separar cada paso del historial
  de un vistazo. El punto del timeline (`::before`) no se movió: el tinte
  se logró con padding, no con margin, así el marcador circular sigue
  centrado en la línea vertical.
- **Globo del badge cortado por el borde de la tarjeta (fix 2026-08-16)**:
  `.badge-noleidas` (notificaciones en portada.html, trámites en
  admin_portada.html) se posicionaba `absolute` DENTRO de `.acceso`, que
  tiene `overflow:hidden` (necesario para el brillo/vidrio de la tarjeta)
  — el globo quedaba recortado en el borde en vez de sobresalir. Fix: un
  `<div class="acceso-badge-wrap">` (sin `overflow:hidden`) envuelve la
  tarjeta, y el badge pasa a ser hermano de `.acceso` dentro de ese wrap,
  no hijo. De paso, 30% más grande (antes 19px/10.5px de fuente, ahora
  25px/13.5px) en los dos lugares donde aparece, más el mismo globo nuevo
  agregado a la sub-pestaña "Ver trámites" de `/admin` (ver más arriba).

## Fondo de los logins (2026-08-16, vidrio agregado 2026-08-17)
Los 3 logins (`admin_login.html`, `plataforma_login.html`,
`trabajador_login.html` -- NO `elegir_sindicato.html` ni
`verificar_credencial.html`, que no son pantallas de login) cambiaron el
fondo de `.caja` de blanco liso a gris medio (`#9ea39e`) con la misma
textura de grano inline (`feTurbulence` en un `::before`, `.caja > *` con
`z-index:1` para quedar por encima) que ya usa `marca.css` en la portada
-- acá va inline porque estas 3 pantallas son standalone, no importan
`marca.css`. El logo de plataforma (`.logo-recuadro`) se agrandó un 40%
(76px→106px) **solo en estas 3 pantallas**, y el 2026-08-17 se le sumó
otro +40% en desktop (106px→148px, mobile se queda en 85px) -- en el
login es lo único que hay para mirar. En el resto de la app (headers de
admin.html/trabajador.html, etc.) el tamaño de 76px unificado (ver
"Decisiones tomadas") no cambió.

**Vidrio (2026-08-17)**: `.caja` pasó de fondo plano a degradé
(`linear-gradient(155deg, #a8ada8, #8d928c)`) + brillo diagonal
(`::after`, mismo patrón que `.vidrio` de marca.css) -- "vidrio sutil",
la opción que el usuario eligió entre tres mockups mostrados antes de
implementar (los otros dos teñían el gris con el color del sindicato o
usaban un degradé más oscuro/dramático; se descartaron). El grano
(`::before`) y el degradé/brillo (`::after`) comparten `z-index:0`, el
contenido real queda en `z-index:1` (`.caja > *`) -- mismo criterio que ya
usa `.grano` en marca.css para que el contenido no quede tapado. Se sumó
además `@font-face` de Barlow Condensed (la misma fuente condensada que ya
usa la portada, referenciada por URL server-relativa ya que estas 3
pantallas no importan marca.css) para el `<h1>` de `plataforma_login.html`
(único de los 3 que tiene título) -- queda centrado y en la fuente
condensada. `admin_login.html`/`trabajador_login.html` no tienen `<h1>` y
no se les agregó uno (no era parte del pedido, solo centrar el que ya
existiera).

## Constructor visual de Trámites (2026-08-16)
El pedido original era un editor de lienzo libre (drag X/Y) para maquetar
el formulario antes de publicarlo -- se evaluó y se descartó por costo
(ver "Pendientes", punto 5). En su lugar, tres piezas más livianas que
resuelven el mismo problema real (un campo SI/NO no debería ocupar todo
el ancho de la pantalla):

- **`CampoTramite.ancho`** (columna nueva: `completo`|`mitad`|`tercio`,
  default `completo`). El formulario del trabajador (`trabajador.html`)
  y la vista previa de admin usan la MISMA grilla CSS de 12 columnas
  (`#tram-form-campos`/`.tram-preview-grid { grid-template-columns:repeat(12,1fr) }`,
  clases `.tp-completo/.tp-mitad/.tp-tercio` con `grid-column:span
  12/6/4`) -- dos campos "mitad" seguidos quedan uno al lado del otro
  solos, sin que el admin tenga que calcular nada. En mobile (`max-width:
  600px`) mitad/tercio colapsan a ancho completo -- no tiene sentido un
  campo angosto en una pantalla de celular.
- **Reordenar arrastrando** (`admin.html::renderCamposTramite`): cada fila
  del constructor es `draggable="true"` con handlers HTML5 nativos
  (`dragstart`/`dragover`/`drop`/`dragend`, sin librería externa, mismo
  criterio del proyecto de no depender de CDNs) -- clases `.arrastrando`/
  `.sobre-drop` dan feedback visual. Los botones ↑/↓ de antes se
  mantuvieron como fallback accesible (teclado/lector de pantalla), no se
  sacaron.
- **Vista previa en vivo** (`#tt-vista-previa`, `renderVistaPreviaTramite()`):
  reproduce con inputs deshabilitados (`pointer-events:none`) exactamente
  cómo va a verse el formulario real -- misma función de mapeo tipo_dato→
  HTML que usa el trabajador, no una aproximación aparte. Se re-renderiza
  en cada cambio (agregar/quitar/reordenar/editar un campo).

**Cuatro tipos de campo nuevos** (`CampoTramite.tipo_dato`), sumados a los
que ya había (texto/numero/fecha/archivo/seleccion):
- `separador`: raya horizontal (`<hr>`), pseudo-campo sin respuesta -- es
  el único `tipo_dato` sin etiqueta obligatoria (`main._campos_tramite_validos`
  la exceptúa explícitamente) y `main.api_enviar_tramite` lo salta al
  principio del loop, antes de cualquier otro chequeo.
- `booleano`: checkbox Sí/No. **Nunca bloquea por obligatorio** -- un
  checkbox sin marcar es una respuesta válida ("No"), no un campo vacío;
  el value que persiste es literalmente el string `"Sí"`/`"No"`.
- `opcion_unica`: radio buttons, una sola opción -- misma validación
  server-side que `seleccion` (el valor tiene que estar en `opciones`),
  solo cambia el widget (radio en vez de `<select>`).
- `multiple`: checkboxes, cero o más opciones -- el form manda varias
  entradas con el mismo `campo_{id}`, `main.py` las lee con
  `form.getlist()` (no `form.get()`) y valida cada una contra `opciones`;
  se persisten unidas con `", "` en un solo `RespuestaTramite.valor_texto`
  (no una fila por opción marcada -- simplifica el modelo, ya alcanza para
  mostrar y para el historial).
- `opcion_unica`/`multiple`/`seleccion` comparten la columna `CampoTramite
  .opciones` (mismo formato: separadas por coma) -- en el constructor de
  admin, el mismo input reutiliza el slot que antes solo mostraba "Tipos
  de archivo" (`TIENE_OPCIONES_TRAMITE` decide qué placeholder/campo
  destino usar), no se agregó una columna nueva al layout ya denso del
  constructor.
- **Globo del "Ver trámites" en vivo (2026-08-17)**: antes se calculaba
  server-side solo al renderizar `/admin` -- si el panel quedaba abierto y
  llegaba un trámite nuevo, el globo se quedaba desactualizado hasta
  recargar. `GET /admin/tramites-nuevos-cantidad` (payload mínimo: un
  número) + `setInterval` cada 30s en admin.html actualizan el globo sin
  recargar la página. Solo corre si el sindicato tiene el módulo
  `tramites` habilitado (`{% if 'tramites' in modulos %}` envuelve el
  `setInterval`, no tiene sentido pedir el endpoint si el panel de
  Trámites ni siquiera existe). `actualizarBadgeTramitesNuevos()` crea o
  saca el `<span class="badge-noleidas">` del DOM según haga falta (el
  span ni existe si `tramites_nuevos` era 0 al renderizar la página, así
  que no alcanza con actualizar texto -- hay que poder crear el elemento
  también). Alcance a propósito acotado a `/admin` (no a la portada de
  admin ni a otras pantallas): es la pantalla que el pedido describía como
  la que se queda abierta.

## Ayuda contextual (ícono "H")
Patrón para textos de ayuda largos (varias oraciones explicando qué
significa cada campo de un formulario) que antes vivían como un
`<p class="muted">` metido en el medio de la pantalla, ensuciándola. Se
sacan del flujo normal y se mueven a un overlay que se abre con un botón
flotante -- mismo lenguaje visual que `.btn-cerrar`/`.btn-home` (círculo
oscuro, ícono/glifo blanco), agregado como `.btn-ayuda` (`right:128px` en
admin.html, 54px a la izquierda de `.btn-home` que está en `right:74px`).
El glifo es la letra "H" en `--fuente-display`, no un ícono SVG dibujado a
mano.

- **Un solo botón, generalizado (2026-08-17)**: originalmente
  `#btn-ayuda-tramites` era un botón fijo, exclusivo de Trámites. Se
  generalizó a un único `#btn-ayuda` reutilizado por cualquier pestaña/
  sub-pestaña con ayuda larga -- `contextoAyudaActual()` mira qué
  `.tab-btn` está activo (y, si es Trámites, qué `.tramite-subtab`) y
  devuelve la clave de `AYUDA_CONTENIDO` que corresponde (o `null` si esa
  pantalla no tiene ayuda); `actualizarBtnAyuda()` aplica esa clave al
  botón (mostrar/ocultar + qué `abrirAyuda()` dispara el click) y se llama
  desde los dos ejes de navegación que existen (el handler de `.tab-btn` y
  `cambiarSubTramite()`). Sumar una ayuda nueva en otra pantalla es
  agregar una clave a `AYUDA_CONTENIDO` + una rama en
  `contextoAyudaActual()` -- ya no hace falta un botón/id nuevo por
  pantalla.
- **Contenido con secciones, no un párrafo único (2026-08-17)**: cada
  entrada de `AYUDA_CONTENIDO` tiene `titulo` + `secciones` (lista de
  `{titulo, texto}`), y `abrirAyuda()` arma el overlay como un `<h3>`
  (título general) seguido de un `<h4>`/`<p>` por sección -- mejora sobre
  la primera versión (Trámites), que era un único párrafo largo sin
  subdivisiones, con redacción más telegráfica. Tres pantallas cargadas
  hoy: `conceptos` (genérico vs. por empleador -- el texto que antes vivía
  como `<p class="muted">` en la pestaña Conceptos, ahora solo en la
  ayuda), `formulas` (vigencia por período + "Sujeto a tope" -- los dos
  párrafos largos que antes vivían sueltos arriba de la tabla de
  Fórmulas), y `tramites-tipos` (Código/Longitud exacta/Tipos de archivo
  y Opciones/Orden y ancho -- la explicación del constructor de Trámites,
  reescrita con las mismas secciones separadas). El campo "Código" de un
  tipo de trámite (el prefijo del número de expediente, ver sección
  "Trámites") es texto libre a propósito -- no se agregó validación de
  formato, solo la explicación de qué hace ese campo en la ayuda.
- **Overlay compartido**: `#overlay-ayuda`/`#overlay-ayuda-contenido`,
  reutilizado por cualquier `abrirAyuda(clave)` -- no hay un overlay por
  cada ayuda, uno solo que cambia de contenido.
- Quedan afuera de esta pasada, evaluadas y descartadas a propósito: las
  ayudas largas de varias pantallas de `/plataforma` (marca de la
  plataforma, tokens de IA, recibos con alerta, Topes SS) -- el patrón ya
  generalizado hace que sumarlas sea barato cuando se pida, pero no se
  tocó esa pantalla en esta pasada (el pedido fue puntual sobre admin.html).

## Logo y firma del sindicato: preview al editar + cache-busting (2026-08-17)
Bug real reportado: al editar un sindicato desde `/plataforma` → "Sindicatos",
el form no mostraba el logo ni la firma ya cargados -- no había forma de saber,
parado en el form de edición, si el sindicato ya tenía uno o si el archivo que
se acababa de subir había reemplazado al anterior. Además, a veces la imagen
nueva no se veía reflejada en el resto de la app después de guardar.

- **Preview faltante**: se agregaron dos bloques (`#sind-logo-preview`/
  `#sind-firma-preview` en `plataforma.html`, ocultos por default) con la
  imagen actual + una leyenda ("Logo actual -- subí uno nuevo para
  reemplazarlo"), justo arriba de cada `<input type=file>`. `editarSind()`
  los puebla y los muestra solo si `s.logo`/`s.firma` están tildados (el
  payload de cada fila, `i.s | tojson`, ahora incluye esos dos flags);
  `resetSindForm()` los vuelve a ocultar al pasar a modo "alta". El `src`
  usa `Date.now()` como sello de cache (no el tamaño del archivo): fuerza
  a pedirle la imagen al servidor cada vez que se abre el form de edición,
  así siempre se ve la versión actual, no una vieja cacheada por el
  navegador.
- **La imagen a veces no se actualizaba en el resto de la app -- causa
  real**: `/logo/{id}` y `/firma/{id}` (main.py) devuelven
  `Cache-Control: public, max-age=3600`, pero la URL era SIEMPRE la misma
  (`/logo/{id}`) antes y después de reemplazar el archivo -- el navegador
  seguía sirviendo la imagen vieja desde su caché hasta que expiraba sola,
  sin importar que el admin acabara de subir una nueva. Fix: `db.marca_sindicato()`
  ahora devuelve `logo_v`/`firma_v` (el largo en bytes del binario
  guardado) y cada `<img>` que pinta el logo/firma de un sindicato
  (`admin.html`, `admin_portada.html`, `portada.html`, `trabajador.html`
  x3, `verificar_credencial.html`, más el ícono chico del listado de
  `/plataforma`) le suma `?v={{ marca.logo_v }}` a la URL -- al cambiar el
  archivo cambia el largo, cambia la URL, y el navegador la trata como una
  imagen distinta en vez de reusar la cacheada. No se tocó el
  `Cache-Control` de las rutas (sigue siendo válido: como la URL ya es
  única por versión, cachear cada una por una hora no tiene contra).
- Mismo patrón (`Cache-Control:max-age=3600` sin sello de versión en la
  URL) existe también en `/logo-plataforma`, `/noticia-imagen/...` y
  `/beneficio-imagen/...` -- no se tocaron en esta pasada porque no hubo
  reporte de bug ahí, pero valdría aplicarles el mismo fix si aparece el
  mismo síntoma.

## Pulido visual: barra fija, QR, login, vista previa de Trámites (2026-08-17)
Cinco ajustes puntuales de usabilidad reportados juntos, sin relación
funcional entre sí.

- **Barra de pestañas fija (`/admin`, `/plataforma`)**: `header` ya era
  `position:sticky; top:0`, pero `.nav-strip` (la tira de pestañas debajo)
  no lo era -- al scrollear el contenido, la tira de navegación
  desaparecía de la pantalla junto con el resto. Fix: un wrapper nuevo
  `.app-bar-fija` (`position:sticky; top:0`) engloba `<header>` +
  `<nav class="nav-strip">` (más los botones flotantes y el overlay de
  ayuda que quedan en el medio en el HTML, todos con `position:fixed` así
  que no les afecta estar anidados adentro) -- así los dos se pegan juntos
  como un solo bloque, sin tener que calcular a mano la altura del header
  (que varía por breakpoint). `header` perdió su `position:sticky` propio,
  ahora lo hereda del wrapper. Mismo patrón en los dos templates.
- **QR de la credencial +25% (`trabajador.html`)**: `.cred-qr svg` pasó de
  64px a 80px -- se reportó difícil de leer/escanear al tamaño anterior.
  Sin cambios en el layout de `.cred-inferior` (flex con `flex-shrink:0`
  en el QR), el espacio ya alcanzaba.
- **Fondo de los logins más claro y con más contraste**: el degradé de
  `.caja` (los 3 `*_login.html`) pasó de `#a8ada8 → #8d928c` a
  `#bfc3bf → #9ea29d` -- se calculó aclarando el punto medio del degradé
  un 20% hacia blanco y agrandando un 20% la distancia entre los dos
  extremos respecto a ese punto medio (no un simple +20% por canal), para
  que el pedido "20% más claro" y "20% más de contraste" fueran cambios
  independientes y no se cancelaran entre sí.
- **Vista previa de Trámites prolija (`admin.html`)**: la vista previa
  vivía con su propio set de clases (`.tp-campo`, inputs con
  `color:var(--gris)` y padding/font-size más chicos) que se había ido
  desalineando de cómo se ve el formulario real en `trabajador.html`
  (`.tram-input`/`.campo-tram`/`.campo-tram-opcion`/`.campo-tram-bool`) --
  de ahí que "en producción se ve bien" pero la vista previa no. Fix: la
  vista previa pasa a usar EXACTAMENTE las mismas clases que
  `trabajador.html` (duplicadas en el `<style>` de `admin.html`, que no
  importa el de trabajador), incluyendo la grilla `gap:0 12px` +
  `margin-bottom` por campo en vez de un `gap` uniforme. Los inputs siguen
  con `disabled` (no interactivos) pero con `:disabled { opacity:1; ... }`
  para que no se vean grisados por el estilo nativo del navegador -- si
  no, aunque las clases coincidieran, se seguirían viendo "apagados"
  respecto a la versión real.
- **Referencia visual al arrastrar un campo + cabecera de columnas
  (`admin.html`)**: dos mejoras de descubribilidad para el constructor de
  campos, que ya tenía ancho (mitad/tercio) y reordenar arrastrando pero
  no era obvio ni qué columna hacía qué ni dónde iba a caer una fila
  soltada. (1) `.campo-tramite-fila.arrastrando` ahora se "levanta" con
  sombra + `scale(.99)` en vez de solo bajar opacidad, y
  `.sobre-drop` (la fila sobre la que se está por soltar) pasa de un
  borde de 2px casi invisible a 3px en el color de acento del sindicato +
  sombra -- referencia gráfica de dónde va a caer. (2)
  `.campos-tramite-cabecera` es una fila de etiquetas chicas (Etiqueta /
  Tipo / Long. máx. / Long. exacta / Decimales / Opciones o archivo /
  Ancho) alineada con las mismas columnas flex que usa cada
  `.campo-tramite-fila`, oculta cuando la lista está vacía
  (`renderCamposTramite()` la muestra/oculta) -- así la columna "Ancho"
  (que ya elegía mitad/tercio) queda identificada todo el tiempo, no solo
  cuando se abre el `<select>`.

## Topes de base imponible (jubilación, INSSJP, obra social)
El validador aplicaba el % de cada aporte sobre la base remunerativa
completa del recibo, sin el tope máximo ni el piso mínimo de la base
imponible de la seguridad social (art. 9 Ley 24.241) — todo trabajador que
superaba el tope recibía discrepancias falsas. Corregido en la rama
`topes-base-imponible` (4 fases).

- **Modelo**: tabla nueva `TopeBaseImponible` (db.py) — **nacional, sin
  `sindicato_id`**, un solo valor rige para toda la plataforma, administrada
  desde `/plataforma` → pestaña "Topes SS". Campos: `vigencia_desde`
  ("AAAA-MM", sin fecha_hasta — cada fila rige hasta que empieza la
  siguiente), `tope_maximo`, `base_minima`, `estado`
  (`verificado`/`derivado`/`por_verificar`/`SOSPECHOSO`) y `fuente`. Se
  siembra desde `data/topes_ss.csv` (78 vigencias, enero 2015 a agosto
  2026 — 2022/2023/2024 con cobertura mensual completa desde 2026-08-16,
  antes eran filas sueltas de muestra) vía `db.sembrar_topes_si_vacio()`,
  llamada desde `init_db()` —
  mismo criterio que el seed histórico de AEFIP, corre en cada arranque
  tanto en SQLite local como en Postgres/Render.
- **`Formula.sujeto_a_tope`** (bool, default `False`): marca por fórmula
  si está sujeta al tope, editable por el admin del sindicato en `/admin`
  → Fórmulas. Por defecto `True` solo en jubilación/INSSJP/obra social al
  autocargarse (`db.crear_conceptos_universales`); la migración también
  marcó `sujeto_a_tope=true` en las fórmulas de esos 3 códigos que ya
  existían en sindicatos previos a este cambio (grandfathering — sin eso
  el fix no corregía nada para nadie hasta tildar el checkbox a mano).
- **Motor** (`validador.py`): `tope_vigente_en()` busca, entre los topes
  con `vigencia_desde <= período del recibo`, el de vigencia más reciente
  (sin fallback al más cercano si no hay ninguno). Para las fórmulas
  `sujeto_a_tope`, se evalúa con `base_remunerativa` recortada a
  `min(max(base, base_minima), tope_maximo)`; el resto sigue con la base
  completa. Sin tope cargado para el período, o con el tope `SOSPECHOSO`,
  se evalúa igual (no se salta el chequeo) y se agrega una `alerta`
  avisando que el resultado puede no ser confiable. Cuando una fórmula
  `sujeto_a_tope` termina en discrepancia, el `detalle` suma en lenguaje
  llano la aclaración de que puede deberse a liquidaciones múltiples/
  pluriempleo en el mismo mes (la app analiza un recibo a la vez, no puede
  descartarlo) y, si se aplicó el piso mínimo, también la de jornada
  parcial/mes incompleto (no se toca `extractor.py`: sin campo de días
  trabajados en lo que ya extrae la IA, esta aclaración se agrega siempre
  que se dé la condición, no se intenta proporcionar el mínimo).
- **Validación al guardar un tope**: si el valor es menor al del período
  anterior (no debería pasar, los topes solo suben), el panel de
  plataforma pide confirmación explícita antes de guardar — chequeado en
  el cliente (JS) y de nuevo en el servidor (`/plataforma/tope`).
- **Formato de los montos, a propósito distinto del resto de la app
  (2026-08-16)**: `tope_maximo`/`base_minima` en el panel "Topes SS" se
  escriben **sin punto de separador de miles, con coma para los
  decimales** (ej. `4594798,23`) — convención argentina. El campo es
  `type="text"` (no `type="number"`: el input nativo del navegador no
  acepta coma como decimal, por eso al principio "no dejaba cargar" un
  valor). `main._parse_numero_tope()` es quien valida/convierte del lado
  del servidor — un punto en el texto se rechaza (`?error=topeformato`)
  en vez de adivinar si era separador de miles o decimal. El listado
  también se muestra en ese formato (no con `'{:,.2f}'`, que da al revés:
  coma de miles y punto decimal).
- **Orden del listado (2026-08-16)**: simple, por `vigencia_desde`
  descendente (el más nuevo primero) — no hay reordenamiento por
  prioridad; cuáles conviene revisar se ve por el chip de color del
  estado, no por la posición en la tabla.

**Mantenimiento mensual obligatorio**: ANSES actualiza el tope y la base
mínima todos los meses (Decreto 274/2024, movilidad/IPC) — hay que cargar
el valor nuevo en `/plataforma` → "Topes SS" cada mes para que el chequeo
de ese período funcione. **Ya no quedan valores `SOSPECHOSO`**: los 14
que la discontinuidad original (detectada en el CSV entre febrero y marzo
2026) había dejado marcados, de enero 2025 a febrero 2026, se corrigieron
en dos tandas con datos reales aportados por el sindicato (2026-08-15,
2026-08-16) y quedaron `verificado`. Siguen habiendo vigencias
`por_verificar` (las más antiguas, previas a 2025) — menor urgencia porque
no hay ninguna inconsistencia detectada en ellas, a diferencia de las que
eran `SOSPECHOSO`.

## Empleadores (CRUD, login propio, notificaciones y trámites externos)
Cuarto actor de la plataforma, en rama `empleadores` (NO mergeada a `main`
todavía — se pide aprobación explícita antes de mergear). Hasta ahora el
empleador era solo un dato suelto (`Concepto.cuit_empleador`,
`Trabajador.cuit_empleador`); esta rama le da identidad propia: CRUD desde
`/admin`, login/autorregistro propio, mensajería sindicato→empresa y
formularios/trámites "externos" — completamente separados de los sistemas
homólogos del trabajador (aislamiento total, mismo criterio que ya usa el
resto de la plataforma entre sindicatos).

- **Identidad en dos niveles**, mismo patrón que
  `CuentaTrabajador`/`Trabajador`: `CuentaEmpleador` (CUIT + clave, global,
  funciona en cualquier sindicato) + `Empleador` (fila por sindicato: Cuit,
  Razón Social, Domicilio, Teléfono, Provincia, Mail, `activo`,
  `registrado`). Un mismo CUIT puede estar dado de alta en varios
  sindicatos (multisindicato), igual que un CUIL en pluriempleo.
- **Módulo `"empleadores"`** en `modulos.py` (en `MODULOS`, NO en
  `MODULOS_INICIALES` — opt-in, ningún sindicato lo trae tildado por
  default) gatea TODO lo de esta sección: CRUD, notificaciones y trámites
  externos juntos, un solo interruptor.
- **CRUD** (`/admin` → pestaña "Empleadores" → sub-tab "Empresas"): alta/
  edición/baja lógica, aislado por sindicato como el resto del panel. Botón
  "Importar CUITs de conceptos" (`db.importar_cuits_de_conceptos`, también
  corrido una vez como migración de grandfathering al desplegar) crea
  filas `Empleador` mínimas a partir de los CUIT que ya aparecen en
  `Concepto.cuit_empleador` de ese sindicato — idempotente, reutilizable
  cuando aparecen CUIT nuevos más adelante.
- **Login: autorregistro**, igual que el trabajador — `/ingresar-empresa`,
  CUIT + clave propia la primera vez. El CUIT tiene que existir ya como
  `Empleador` activo en al menos un sindicato (mismo gate que
  `trabajador_registro` contra `Trabajador`). Cookies propias
  (`sesion_empleador`, `cuit_emp`, `sind_elegido_emp` — nombres
  deliberadamente distintos de los del trabajador, mismo motivo que el fix
  "Cookie de sesión separada por rol" descripto en "Auth" más arriba: las
  dos sesiones tienen que convivir sin pisarse en el mismo navegador).
  Con el CUIT en varios sindicatos, `elegir_sindicato_empresa.html` deja
  elegir; con uno solo, entra directo.
- **App del empleador: `/empresa/inicio` (portada con tarjetas) +
  `/empresa` (tabbar de 2 pestañas, Notificaciones y Trámites)** — mismo
  patrón de dos capas que admin/trabajador (`/admin/inicio` + `/admin`,
  `/app/inicio` + `/app`). Al principio de esta rama `/empresa` era la
  única pantalla ("con solo 2 funcionalidades no hace falta esa capa
  extra"); se agregó la portada después, ver "Portada de /empresa, perfil
  del empleador y globos propagados" más abajo, para el círculo de perfil
  y el formato de tarjetas.
- **Notificaciones a empleadores**: tablas propias
  (`NotificacionEmpleador`/`NotificacionEmpleadorDestinatario`), mismas
  columnas y mismo flujo preview→confirmar→enviar que ya existe para
  trabajador (Fase 2 de "Módulos + Notificaciones + Trámites"), pero
  **completamente separadas** — nunca comparten fila con las notificaciones
  al trabajador, ni siquiera cuando el mismo número de identidad es CUIL de
  un trabajador y CUIT de un empleador a la vez (verificado con test
  explícito). Criterios de destinatarios: CUIT puntual, "todos los
  empleadores activos", o por provincia — sin seccional ni cuit_empleador
  (no aplican del lado empleador). UI del lado admin en la sub-tab
  "Notificaciones" de "Empleadores"; del lado empleador, la pestaña
  Notificaciones de `/empresa` es directamente la lista con acordeón (sin
  modal, a diferencia del trabajador — acá la pestaña ya es el contenido).
- **Trámites externos**: mirror completo del sistema de Trámites del
  trabajador (Fase 3 de "Módulos + Notificaciones + Trámites") sobre 6
  tablas propias (`TipoTramiteEmpleador`, `CampoTramiteEmpleador`,
  `TramiteEmpleador`, `RespuestaTramiteEmpleador`, `NotaTramiteEmpleador`,
  `TramiteEmpleadorLog`) — mismos tipos de campo, mismo ancho
  completo/mitad/tercio, mismo constructor con arrastrar para reordenar y
  vista previa en vivo, misma numeración de expediente con reintento ante
  colisión, mismos 5 estados (`iniciado → en_tratamiento → respondido →
  espera_info → terminado`, con `terminado` bloqueando cambios de
  cualquier lado). El constructor vive en `/admin` → "Empleadores" →
  sub-tab "Trámites", con sus propios 2 sub-sub-tabs ("Ver trámites"/"Crear
  formularios", namespace `.emptram-subtab`/`cambiarSubEmpresaTramite`,
  SIN compartir funciones ni listeners con el constructor de trabajador).
  Cambiar el estado o agregar una nota **desde el admin** dispara
  automáticamente una notificación al empleador (mismo criterio que
  `_notificar_cambio_tramite` para trabajador); una nota de la empresa NO
  se autonotifica.
  - **Tratamiento visual "más intenso" a propósito**: tanto la vista
    previa del constructor en admin como el formulario real en
    `/empresa` usan clases propias (`.tramx-*`, no `.campo-tram`/
    `.tram-input` que usa trabajador) con el fondo casi blanco
    reemplazado por un `color-mix` con `--marca-primario` — se nota la
    diferencia de un vistazo entre un trámite de trabajador y uno de
    empresa, sin salirse de la paleta de marca del sindicato.
- **Constantes reusadas sin duplicar**: `ESTADOS_TRAMITE`/
  `ESTADOS_TRAMITE_LABEL` (db.py) y `TIPOS_DATO_TRAMITE`/
  `ANCHOS_CAMPO_TRAMITE`/`ARCHIVO_MIMES_TRAMITE`/`_campos_tramite_validos`/
  `_leer_archivo_tramite` (main.py) son datos/validación sin estado propio
  de ningún rol — la duplicación deliberada de esta rama es de tablas y
  rutas, no de esas constantes.
- **Rutas bajo prefijo `/empresa`/`/api/empresa`** (no sufijo) — `_panel_de`/
  `_rol_de` (main.py) resuelven el login correcto por prefijo de path para
  los manejadores de excepción; si las rutas de API fueran sufijo,
  caerían en la rama genérica `/api` → rol "trabajador" y un 403 de
  empleador redirigiría al login equivocado.
- **Datos de prueba** (`cargar_demo.py`): UOM tiene 2 empleadores
  ("Constructora Ejemplo SA" CUIT 30111222339, "Metalúrgica del Sur SRL"
  CUIT 30999888776); Gastronómica tiene el mismo CUIT 30111222339
  ("Constructora Ejemplo SA") — mismo criterio que el CUIL de pluriempleo
  27222222224, para poder probar el selector multisindicato del lado
  empleador de una. El script NO precrea `CuentaEmpleador` (el
  autorregistro es el flujo real) — solo imprime el CUIT a usar en
  `/ingresar-empresa`. Los 2 sindicatos de demo traen el módulo
  `"empleadores"` habilitado de una.

## Portada de /empresa, perfil del empleador y globos propagados (2026-08-18)
Construido directo en `main` sin plan formal, sobre la rama `empleadores`
ya mergeada.

- **`/empresa/inicio`** (`templates/empresa_portada.html`, nueva) — mismo
  patrón de portada con tarjetas que ya usan `/admin/inicio` y `/app/inicio`
  (reusa `static/marca.css`: `.enc`/`.pad`/`.hola`/`.tarjetas .acceso`/
  `.acceso-badge-wrap`/`.badge-noleidas`/`.circulo-acento`/`.overlay`/
  `.btn-flotante`, en vez de reinventar CSS como hace `empresa.html`, que
  es standalone). Login/registro/`elegir`/`cambiar` del empleador ahora
  redirigen acá (antes iban directo a `/empresa`, que sigue existiendo sin
  cambios como la pantalla funcional con las 2 pestañas de siempre --
  mismo criterio que `/admin/inicio` → `/admin`). Tarjetas: Notificaciones
  (con `badge-noleidas` = no leídas) y Trámites -- ambas siempre visibles,
  no hay gating por módulo propio del lado empleador (ya está gateado por
  tener `empleadores` habilitado en el sindicato, condición para que
  exista la fila `Empleador` en primer lugar). `empresa.html` suma
  `abrirDesdeHash()` (mismo patrón que `admin.html`) para que las tarjetas
  salten directo a la pestaña `#notificaciones`/`#tramites`, más un botón
  flotante "Inicio" (`.btn-home`, `right:68px`) al lado del "Salir" que ya
  existía.
- **Perfil del empleador editable, con foto** -- mirror exacto de "Perfil
  del trabajador" (ver esa sección más abajo), adaptado a los campos que
  ya tiene `Empleador` (razón social, domicilio como campo único --no
  separado en calle/número/piso como `Trabajador`--, provincia, teléfono,
  mail; el CUIT nunca se toca). Foto en `CuentaEmpleador.foto_datos`/
  `foto_mime` (nueva, migración `bd0236c61d6c`) -- una sola por CUIT, no
  por sindicato, mismo criterio que `CuentaTrabajador.foto_datos`. Rutas
  `POST /api/empresa/perfil`, `POST /api/empresa/perfil/foto`,
  `GET /perfil-empleador-foto/{cuit}` (auth: sesión de empleador Y que el
  CUIT de la sesión coincida con el de la URL, igual que el trabajador).
  El redimensionado a baja resolución (160×160 JPEG) lo hace el cliente
  con el mismo `redimensionarFotoPerfil()` copiado tal cual.
- **Globos de notificaciones, propagados por la rama** -- hasta ahora el
  globo de "Ver trámites" (trabajador y empleadores) solo vivía en la
  sub-pestaña más profunda de `/admin`; no llegaba ni a la pestaña
  principal del nav-strip ni a la tarjeta de la portada. Ahora se propaga
  en cadena, mismo número en los tres niveles:
  - Sub-pestaña "Ver trámites" (ya existía).
  - `tab-btn` del nav-strip en `/admin` (`data-panel="tramites"` y
    `data-panel="empleadores"`, nuevo) -- ambos con `position:relative`
    inline para anclar el `badge-noleidas` como hijo directo, mismo truco
    que ya usaba la sub-pestaña.
  - Tarjeta de `/admin/inicio` (la de Trámites ya lo tenía; la de
    Empleadores lo suma ahora, con `tramites_empresa_nuevos` agregado al
    contexto de `admin_inicio()`).
  El polling en vivo (cada 30s, ya existía) ahora actualiza los tres
  lugares con una sola función helper (`_actualizarBadgeEn(selector,
  idBadge, cantidad)`) en vez de tener la lógica de crear/actualizar/sacar
  el `<span>` repetida -- **ojo**: el globo de la tarjeta de portada NO
  tiene este polling (es una pantalla server-side aparte, sin JS de
  actualización en vivo, mismo criterio que el resto de esa pantalla). Del
  lado empleador, el nivel más alto es la tarjeta "Notificaciones" de
  `/empresa/inicio` -- no hace falta propagar más porque ahí ya está el
  número agregado de no leídas.

## Ajustes de recibos, aportes y trámites (2026-08-18)
Tres cambios chicos, construidos directo en `main` sin plan formal.

- **Recibos reportados también cuentan como afiliado cotizante**: antes,
  al padrón/listado de "Afiliados cotizantes" (`EnvioSindicato`, ver art.
  21 bis Dto 407/2026) solo llegaban los recibos SIN discrepancias
  (enviados con el botón "Enviar a mi sindicato",
  `POST /api/enviar-sindicato`) -- un recibo reportado con inconsistencias
  (`POST /api/reportar`) solo quedaba en "Reportes", nunca en el padrón,
  aunque el descuento de cuota sindical se haya hecho igual. Ahora
  `api_reportar` (main.py), además del `Reporte` de siempre (para que el
  sindicato lo revise), registra TAMBIÉN un `EnvioSindicato` -- mismo
  padrón, no lo reemplaza -- y marca `ReciboVerificado.enviado_sindicato`,
  igual que ya hacía el envío sin discrepancias.
- **Estado "INFORMADO" del comprobante de aportes de ARCA**: además de
  pagado/parcial/impago/no_presentada/no_declarado, algunos comprobantes
  muestran "INFORMADO" -- el aporte está en regla pero se hizo a una Caja
  previsional u organismo provincial en vez de ARCA directamente (pasa con
  empleados públicos de la Provincia de Buenos Aires, caso real
  reportado). No es un estado nuevo del semáforo: `ESQUEMA_APORTES`
  (extractor.py) le aclara a la IA que "INFORMADO" mapea a "pagado"
  (semáforo verde) y "NO INFORMADO" a "impago" (rojo) -- sin tocar
  `semaforo.py`.
- **Trámites: popup para elegir estado después de responder**: mandar una
  nota (`agregar_nota_tramite`/`agregar_nota_tramite_empleador`) nunca
  cambió el estado del trámite por sí solo -- pero como responder suele
  implicar avanzarlo, ahora `admin.html` muestra un popup
  (`#overlay-estado-tramite`, compartido entre Trámites de trabajador y de
  empresa) justo después de enviar la nota, con el estado actual
  preseleccionado, para que el admin lo confirme o lo cambie ahí mismo en
  vez de tener que acordarse de ir a tocar el selector de Estado aparte;
  "Dejar como está" lo cierra sin tocar nada. **Ojo con dónde vive en el
  HTML**: tiene que estar FUERA de `.app-bar-fija` (position:sticky +
  z-index:21) -- un z-index más alto puesto en un descendiente de ese
  contenedor queda atrapado comparándose solo contra otros descendientes
  de `.app-bar-fija`, así que nunca le gana en pantalla al modal de
  detalle de trámite (z-index:250), que vive afuera. Se descubrió armando
  esta misma feature: el popup quedaba tapado detrás del modal.

## Pendientes (features)
1. Capacitación — "próximamente". Falta contenido: índice de documentos y
   links de formación.
2. Quitar la pestaña transitoria "Cambiar clave" del panel de plataforma antes de
   producción (permite cambiar la clave de cualquier usuario; está marcada con una
   advertencia visible). Es un riesgo de seguridad, sacar antes de usuarios reales.
   Se deja a propósito mientras dure la etapa de demos y pruebas (2026-08-05).
3. Los topes de base imponible previos a 2025 siguen marcados
   `por_verificar` (menor urgencia, sin inconsistencia detectada) — ver
   sección "Topes de base imponible" más arriba.
4. ~~Causa real de los 500 intermitentes al guardar/enviar~~ — **resuelto
   2026-08-16**: no era Postgres, era la cookie de sesión compartida entre
   roles (ver "Auth" más arriba, "Cookie de sesión separada por rol"). Un
   repro concreto del usuario (sindicato en una pestaña, trabajador en
   otra) confirmó la causa real. La mitigación de keepalives TCP en `db.py`
   se mantiene (es una mejora real e independiente), pero ya no es la
   sospecha principal de este síntoma puntual.
5. **Editor visual de formularios de Trámites con lienzo libre (drag X/Y),
   pospuesto (2026-08-16)**: el pedido original era una etapa de diseño
   previa a publicar, con las "cajas" de cada campo arrastrables a
   cualquier posición del lienzo (fondo/encabezados fijos, campos libres).
   Se descartó por ahora por el costo real: hay que guardar coordenadas
   (no solo orden), construir un editor de arrastre libre nuevo, y sobre
   todo resolver cómo esa posición libre se traduce a la pantalla angosta
   del celular del trabajador, donde hoy todo va apilado a lo ancho
   completo a propósito. **Se implementó en su lugar** un camino más
   liviano que cubre el mismo problema real (un campo SI/NO no debería
   ocupar el ancho completo): ancho elegible por campo (completo/mitad/
   tercio) + reordenar arrastrando en una lista (no en un lienzo) + vista
   previa en vivo — ver sección "Constructor visual de Trámites" más abajo.
   Revisar si en algún momento el lienzo libre justifica el costo extra.

## Noticias (sindicato → trabajador)
Reemplaza el placeholder "próximamente" de Novedades. Modelo `Noticia`
(db.py): título, bajada, texto completo (URLs se auto-enlazan al mostrarse,
`main.py::_texto_con_links`), vigencia por fecha_desde/fecha_hasta (las dos
obligatorias — a diferencia de Formula, acá es un período cerrado), hasta 2
imágenes (bytes en la base, mismo patrón que el logo del sindicato). El
admin las carga desde `/admin` → pestaña Noticias. El trabajador las ve en
la portada (hasta 3, "Ver todas" → `/app?tab=novedades`, deep-link por query
param) y en la pestaña Novedades (lista completa); un click abre un overlay
con el detalle completo vía `GET /api/noticia/{id}` (aísla por sindicato
activo).

## Beneficios (sindicato → trabajador)
Carrusel de descuentos en la portada, mismo patrón de datos que Noticias.
Modelo `Beneficio` (db.py): rubro (título corto que se superpone a la
imagen), descripción (URLs se auto-enlazan igual que en Noticias), link
opcional, vigencia por fecha_desde/fecha_hasta (las dos obligatorias, período
cerrado), una sola imagen (a diferencia de Noticia que admite 2 — acá es la
que se expone en el carrusel). El admin lo carga desde `/admin` → pestaña
Beneficios. El trabajador ve los vigentes como carrusel en la portada
(`.carrusel-wrap`/`.carrusel-track` en `static/marca.css`): track flex con
`transform: translateX(...)` y transición CSS (desliza, no crossfade),
avanza solo cada 5s, con flechas manuales a los costados si hay más de uno
vigente; el alto está topeado a 88px (igual que las tarjetas de acceso)
porque es secundario, el ancho está topeado a 480px y centrado (si no, en
desktop se estira a lo ancho de toda la pantalla y queda muy chato). Las
imágenes usan `object-fit: contain` (se ven enteras, con relleno `--sup-2`
a los costados si no calzan) en vez de `cover` (recortaba). Un click abre
un overlay con el detalle completo vía `GET /api/beneficio/{id}` (aísla por
sindicato activo, mismo criterio que noticias).

## Seccionales del sindicato
Modelo `Seccional` (db.py): sindicato_id, nombre, dirección. CRUD simple en
`/admin` → pestaña Seccionales (sin vigencia, sin imágenes — es solo un dato
descriptivo). `Trabajador.seccional_id` (FK opcional, nullable): se elige de
un `<select>` en el alta/edición manual de trabajador; NO está en el alta
masiva. Borrar una seccional no está bloqueado por tener trabajadores
asignados — los deja con `seccional_id = NULL` (`borrar_seccional` en
main.py nullifica antes de borrar). No afecta validación de recibos.

**Destino por seccional en Noticias y Beneficios**: ambos modelos tienen
`destino_seccionales` (JSON, lista de `Seccional.id`). Lista vacía (default)
= todas las seccionales, incluidos los trabajadores sin seccional asignada;
si no está vacía, SOLO la ven los trabajadores con esa(s) seccional(es) —
uno sin seccional no ve contenido dirigido. El form de alta/edición en
`/admin` muestra un grupo de checkboxes (uno por seccional del sindicato,
`.check-seccionales` en el `<style>` de admin.html) solo si el sindicato
tiene seccionales cargadas; sin marcar ninguna = todas. `db.visible_para_seccional()`
es el filtro; `db.noticias_vigentes()`/`db.beneficios_vigentes()` ahora
piden `seccional_id` (la del trabajador, resuelta con
`db.seccional_de_trabajador(cuil, sindicato_id)`). El admin puede targetear
solo seccionales de SU sindicato — `main._destinos_validos()` descarta las
ajenas o inventadas en silencio, mismo criterio que `seccional_id` del alta
de trabajador.

## Administradores del sindicato (self-service, 2026-08-16)
Antes solo plataforma podía dar de alta o ver los `UsuarioSindicato` de un
sindicato (`POST /plataforma/usuario`, `GET /plataforma/admins/{id}`) — un
sindicato no tenía forma de listar ni sumar administradores propios sin
pedírselo a plataforma. Ahora `/admin` → pestaña "Administradores" (siempre
visible, no depende de ningún módulo, mismo criterio que Trabajadores y
Seccionales) permite, scopeado SIEMPRE al `sindicato_id` de la sesión (nunca
un campo del form): listar, dar de alta (con clave inicial —
`debe_cambiar_clave=True`, mismo patrón que ya usa plataforma), editar el
nombre, y activar/desactivar. Alcance elegido a propósito: **cambiarle la
clave a un administrador YA EXISTENTE sigue siendo solo vía plataforma** —
no se amplía ese flujo transitorio (ver "Pendientes"). Bloqueo real:
`admin_usuario_baja` no deja desactivar al último administrador activo del
sindicato (si no, un sindicato podría quedarse sin nadie que pueda entrar a
`/admin`, y solo plataforma podría reactivarlo a mano).

## Confirmar concepto pendiente de revisión
`Concepto.pendiente_revision` ya se limpiaba como efecto secundario de
editar y guardar un concepto (no era evidente en la UI). Ahora también hay
un botón "Confirmar" dedicado (`POST /admin/concepto/confirmar`) que solo
saca la marca, sin tocar los demás datos del concepto.

## Alerta de posible adulteración en recibos
La IA que lee el recibo (`extractor.extraer()`) también evalúa, con alto
grado de certeza únicamente, si hay señales de edición/adulteración en 4
lugares puntuales: los totales, el CUIL del trabajador, el CUIT del
empleador y cualquier fecha — NO revisa el resto del recibo. Devuelve
`alerta_adulteracion: {"detectada": bool, "motivo": str|null}` en el JSON.
Si `detectada` es true, `/api/leer` (main.py) **no bloquea el proceso** —
el trabajador sigue normalmente — pero: (1) devuelve la alerta en la
respuesta para que `trabajador.html` muestre un aviso no bloqueante
("Algunos datos podrían estar alterados...", reusa `.alerta-legal`) y (2)
guarda el archivo original (imagen o PDF, bytes en la base, mismo patrón
que el logo del sindicato) en la tabla nueva `ReciboSospechoso` —
`db.registrar_recibo_sospechoso()`. Es a modo de prueba: el trabajador
todavía NO puede enviarlo al sindicato desde acá (queda para una etapa
siguiente, por su propia voluntad). Solo el admin de **plataforma** (no el
del sindicato) puede ver esos archivos, en una pestaña nueva "Recibos con
alerta" en `/plataforma` — listado (`db.recibos_sospechosos_listado()`) +
`GET /plataforma/recibos-sospechosos/{id}/archivo` para abrir el archivo
(chequea `rol == "plataforma"`, 403 para cualquier otro). El control NO
aplica al comprobante de aportes de ARCA (`extraer_aportes()`), a
propósito: es una captura de un sitio oficial, no un documento que la
empresa emite y podría alterar.

## Detalle de recibo en modal (no inline)
Los 3 listados que mostraban el detalle de un recibo expandiendo una fila
DEBAJO en la misma tabla (poco práctico) ahora abren un modal centrado:
encabezado con fondo `var(--marca-base)` y el título, cuerpo blanco con el
detalle en una tarjeta levemente destacada (`#faf9f6` en admin.html,
`var(--papel)` en trabajador.html). Afecta:
- `admin.html` → Reportes (`verReporte`) y Afiliados cotizantes (`verEnvio`):
  el HTML del detalle se sigue renderizando server-side en una `<tr>` oculta
  (igual que antes), pero ahora un componente `#modal-recibo-overlay`
  compartido copia su `innerHTML` al abrir en vez de mostrar esa fila.
- `trabajador.html` → "Ver mis recibos verificados" (`toggleHistorialItem`):
  el detalle se arma client-side igual que antes (`renderHistorialDetalle`),
  pero se inyecta en el mismo tipo de modal en vez de expandir un `<div>`
  bajo la fila.
**Bug real encontrado y corregido**: los botones "Ver" de Reportes/Afiliados
cotizantes pasan `{{ r.cuil|tojson }}`/`{{ r.periodo|tojson }}` como
argumentos al `onclick` -- `tojson` genera comillas dobles, y el atributo
`onclick="..."` también usaba comillas dobles, así que el HTML se cortaba en
la primera comilla del cuil (`onclick="verReporte(1, "` truncado, resto
descartado). Mismo patrón que ya usan `editarNoticia`/`editarBeneficio` en
este archivo: cuando un `onclick` recibe un valor con `|tojson`, el atributo
tiene que ir con comillas simples (`onclick='...'`).

## Perfil del trabajador (editable, con foto -- 2026-08-17)
El modal "Tu perfil" (portada.html, botón `.circulo-acento`) pasó de ser
solo lectura a editable, y pasó del `.modal-hoja` oscuro compartido (con
noticia/beneficio/acerca) al mismo criterio claro+encabezado de marca que
ya usa Notificaciones -- reusa directamente sus clases (`.modal-notif-caja`/
`.modal-notif-enc`/`.modal-cerrar-clara`), no se duplicó CSS.

- **Qué se edita**: todo menos el CUIL (identidad, no se toca). Nombre,
  domicilio (calle/número/piso), localidad (ciudad/provincia -- mismo
  `db.PROVINCIAS_AR` que ya usa el alta de trabajador en `/admin`),
  teléfono, mail. `POST /api/perfil` → `db.actualizar_perfil_trabajador`.
  **Ojo con el alcance**: `Trabajador` es por sindicato (pluriempleo, ver
  "Decisiones tomadas"), así que esto edita el empadronamiento del
  sindicato ACTIVO nada más -- no existe un domicilio único de la persona
  en este modelo, no se tocó esa arquitectura para esta feature.
- **Foto de perfil**: una sola por CUIL (no por sindicato -- se ve igual
  sin importar qué sindicato esté activo), vive en
  `CuentaTrabajador.foto_datos`/`foto_mime` (la identidad global, no
  `Trabajador`). El achicado a **muy baja resolución** lo hace el
  CLIENTE antes de subir: `redimensionarFotoPerfil()` dibuja la imagen en
  un `<canvas>` recortada a cuadrado (cover, centrado) y la exporta a JPEG
  160×160 calidad .75 (unos pocos KB) -- el servidor (`POST
  /api/perfil/foto`) solo valida tipo (jpeg/png/webp) y tamaño (tope 1 MB,
  de sobra), no reprocesa la imagen de nuevo. `GET /perfil-foto/{cuil}` la
  sirve -- no es pública como el logo del sindicato, exige sesión de
  trabajador Y que el CUIL de la sesión coincida con el de la URL (403
  para cualquier otro, ver test_perfil_trabajador.py).
- **Círculo de la portada** (`.circulo-acento`, arriba a la derecha de
  "Hola, {nombre}"): muestra la foto si existe (`tiene_foto_perfil`,
  calculado server-side), si no el ícono de silueta de siempre -- sin
  cambios de comportamiento para quien no cargó foto.
- **Tamaño y borde (2026-08-17)**: los dos círculos (`.circulo-acento` en
  la portada y `.perfil-foto-circulo` dentro del modal) se agrandaron un
  20% (34px→41px y 84px→101px) y suman un borde de 2px color acento de la
  marca del sindicato (antes `.circulo-acento` no tenía borde propio --
  el fondo ya era del mismo acento así que no se notaba sin foto -- y el
  del modal usaba `var(--linea)`, un gris neutro). Con una foto cargada,
  el borde enmarca la imagen; sin foto, se sigue viendo igual que antes
  (mismo color que el fondo/silueta).
- **Lightbox al hacer clic en la foto DENTRO del modal**: `.overlay-foto-
  grande`, `max-width:25vw; max-height:25vh` -- tope explícito a un cuarto
  de pantalla, a propósito (pedido así): la foto ya es de muy baja
  resolución, no tiene sentido agrandarla más que eso.
- **Actualización en vivo sin recargar**: guardar el nombre actualiza
  "Hola, {primer_nombre}" en el momento (la respuesta de `/api/perfil` ya
  trae el nombre recalculado); subir una foto la muestra al instante con
  un blob URL local (más rápido que esperar el round-trip de volver a
  pedir `/perfil-foto/...`), que la seguridad de sesión de esa ruta no
  necesita para la propia sesión.

## Versionado
`version.py`: constantes `VERSION_TRABAJADOR`/`VERSION_ADMIN`/
`VERSION_PLATAFORMA` (arrancan las tres en "0.01.00") + `FECHA_VERSION`. Se
actualizan a mano en cada deploy — el número lo indica el usuario en el
prompt de cambio, no hay automatismo. Regla para incrementar `release.patch`:
solo arreglos → +1 al patch; arreglos + funcionalidad nueva en el mismo
deploy → +1 en los dos (ej. 0.02.01 → 0.03.01). Cada pantalla de inicio (portada,
`/admin`, `/plataforma`) tiene un link discreto "Acerca de" al pie que abre
un overlay mostrando la versión de ESA app puntual (no las tres) + fecha del
despliegue.

## Semáforo de aportes persistente
`Trabajador.semaforo_datos`/`semaforo_actualizado` (JSON) guardan el último
resultado de `calcular_semaforo()`. `POST /api/aportes` lo persiste;
`GET /app` lo pre-pinta con `semRender()` si existe (antes se perdía al
navegar o recargar — arrancaba siempre en blanco). "Actualizar con otra
captura" sigue disponible debajo del semáforo ya pintado.

## Uso de la API de IA (costo real)
`UsoIA` (db.py): una fila por cada llamada real a la API de Anthropic —
sindicato_id, cuil, tipo ("recibo" | "aportes" | "aprendizaje"), modelo,
tokens_entrada/tokens_salida (los que devuelve la propia respuesta,
`msg.usage`, no un estimado). Se registra en el mismo request que hace la
llamada (`extractor.extraer()`/`extraer_aportes()` devuelven `(datos, uso)`),
así el conteo no depende de que el trabajador confirme el recibo ni lo
reporte al sindicato — es el costo real, se use o no. Listado filtrable
(sindicato/modelo/tipo) en `/plataforma` → pestaña "Uso de IA". Guarda tokens
crudos, no un costo en $ (los precios de Anthropic cambian).

## Hallazgo pendiente, no arreglado (fuera de alcance de esta sesión)
`db.cargar_seed_si_vacio()` sigue disparando el seed histórico de AEFIP
(`data/seed_aefip.json`) apenas la tabla `Concepto` está vacía, aunque
"Decisiones tomadas" dice que la demo arranca sin AEFIP. Se nota al recrear
la base local desde cero (`db.crear_tablas()` sin `cargar_demo.py` corrido
antes): aparece un sindicato "AEFIP" fantasma con id=1, corriendo los ids de
los sindicatos de demo. No afecta producción real (nunca se recrea la base
de Render desde cero), pero conviene revisarlo antes de confiar en ids fijos
en scripts de diagnóstico.

## Método de trabajo
- Por bloques chicos, verificando la lógica de verdad (rutas y funciones), no
  simulada. Preferir cambios quirúrgicos y probar antes de avanzar.
- Sd tiene skills intermedias de Python, trabaja en Argentina, deploya con
  GitHub + Render (push dispara redeploy).
- Preferencia: durante la construcción mostrar poco output intermedio; dar un
  resumen claro al final.

## Comandos útiles
- Correr local (Postgres vía Docker — ver sección de abajo): `docker compose up -d`,
  después `alembic upgrade head`, después `uvicorn main:app --reload`.
- Correr local (SQLite, sin Docker — ver sección de abajo): `uvicorn main:app --reload`
  (con `DATABASE_URL` comentado/ausente en `.env`).
- Autodiagnóstico: `python chequeo.py`
- Cargar demo: `python cargar_demo.py` (¡correr alembic upgrade head antes si es Postgres!)
- Migraciones: `alembic upgrade head` (aplicar) / `alembic revision --autogenerate -m "msg"` (crear)
- En la Shell de Render, si `alembic` no se encuentra: usar `python -m alembic upgrade head`
- Reset completo de la base local Postgres: `docker compose down -v && docker compose up -d`
  (espera a que el healthcheck pase) `&& alembic upgrade head && python cargar_demo.py`

## Desarrollo local con Postgres (2026-08-16)
**Decisión tomada**: desarrollo local pasa a usar Postgres (vía Docker) como
motor por defecto, no SQLite. Motivo: la app veía cada vez más divergencia
entre SQLite local (sin Alembic, `db.crear_tablas()` recreando todo desde
los modelos actuales) y Postgres en producción (con Alembic real) — las
migraciones nunca se probaban contra un Postgres de verdad antes de llegar
a Render. `docker-compose.yml` (raíz del repo) levanta un Postgres 16 en
`localhost:5432`, con usuario/base `mitrabajo`/`mitrabajo_dev` (credenciales
de desarrollo, sin ningún secreto real). Con `DATABASE_URL` descomentado en
`.env` (ver ese archivo), `db.py` detecta Postgres solo (misma lógica que
ya elegía el motor en producción, sin cambios de código) y el flujo local
pasa a ser IDÉNTICO al de producción: `alembic upgrade head` crea el
esquema (no `crear_tablas()`), después `cargar_demo.py` siembra los 2
sindicatos de demo.

- **Bug real encontrado al hacer esto** (y la razón de por qué vale la
  pena el cambio): `db.py` nunca llamaba a `load_dotenv()` — solo lo hacía
  `auth.py`. Corriendo la app completa (`uvicorn main:app`) funcionaba por
  el orden de imports, pero `python -m alembic upgrade head` importa
  `db.py` directo desde `migrations/env.py`, sin pasar por nada que cargue
  el `.env` antes — así que `DATABASE_URL` quedaba vacío y Alembic corría
  contra SQLite en silencio. En Render nunca se notó porque ahí
  `DATABASE_URL` es una variable de entorno real, no un `.env`. Fix: `db.py`
  ahora llama a `load_dotenv()` él mismo, antes de leer `DATABASE_URL`.
- Ese fix por sí solo hubiera roto el aislamiento de los tests (con
  `DATABASE_URL` real en `.env`, cualquier `test_*.py` que hiciera
  `import db` habría terminado apuntando al Postgres de Docker en vez de
  su SQLite temporal). `conftest.py` (nuevo, raíz del repo) fuerza
  `DATABASE_URL=""` ANTES de que pytest importe ningún `test_*.py` —
  un solo archivo nuevo en vez de tocar los ~40 existentes.
- SQLite sigue funcionando como fallback (sin Docker: comentar/borrar
  `DATABASE_URL` en `.env`) para quien no tenga Docker instalado, pero deja
  de ser el flujo recomendado.
- Los tests (`test_*.py`) **NO cambian de motor**: siguen usando SQLite en
  un archivo temporal por proceso (rápido, aislado, sin depender de que el
  contenedor esté corriendo) — el objetivo de este cambio es la paridad del
  *loop de desarrollo interactivo* con producción, no la suite de tests.
- Confirmado corriendo `alembic upgrade head` contra el Postgres de Docker
  desde cero (revisión `cbe17211376d` hasta la última): las 26 migraciones
  de la historia completa del proyecto aplican limpio.
- **Pendiente, para más adelante** (no urgente, no bloquea nada): un
  entorno de staging real (rama `desarrollo` + servicio + base Postgres
  aparte en Render) para probar el deploy completo — networking, variables
  de entorno de Render — antes de tocar la demo de producción. Tiene costo
  real (no free tier: la base gratis de Render expira a los 30 días y el
  servicio gratis se duerme), así que se decide cuándo tenga sentido el
  gasto, no ahora.
