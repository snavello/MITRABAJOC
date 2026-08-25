# HISTORIAL.md — Mi Trabajo

Detalle técnico completo de cada feature: por qué se hizo así, bugs
encontrados y su causa real, decisiones de UI. **Este archivo NO se carga
automático al iniciar una sesión** (a diferencia de `CLAUDE.md`) — abrilo
puntualmente cuando el trabajo toca una de estas secciones y hace falta el
detalle. `CLAUDE.md` tiene el resumen orientador ("Estado actual") con el
mapa de qué existe; acá está el cómo y el por qué de cada punto de ese mapa,
en el mismo orden cronológico en que se construyó.

## Auth — detalle de los dos fixes de sesión (2026-08-16)

**Cookie de sesión separada por rol**: los tres roles (`sindicato`,
`plataforma`, `trabajador`) usaban una única cookie (`sesion_mitrabajo`)
para los tres. Una cookie es del navegador entero, no de una pestaña:
loguearse con un rol en una pestaña pisaba en silencio la cookie que otra
pestaña, con otro rol, necesitaba -- reportado como "vuelvo a la pestaña de
admin después de un rato y me dice que tengo que loguearme, aunque activo".
**Esta era la causa real** del síntoma que se había atribuido (sin
confirmar) a un corte de conexión de Postgres en Render, ver más abajo.
Fix: `COOKIES_POR_ROL` (main.py) mapea cada rol a su propia cookie
(`sesion_sindicato`/`sesion_plataforma`/`sesion_trabajador`, más
`sesion_empleador` sumada después con el 4to actor); `sesion_actual(request,
rol)` pide el rol explícito y lee solo esa cookie (ya no hay una sesión
"genérica" del navegador); `exigir_sindicato`/`exigir_plataforma` son los
helpers que las rutas usan para exigir sesión de un rol puntual. El
middleware de renovación recorre las cookies y renueva cada una que esté
presente y vigente, así una request de cualquier pestaña mantiene vivas
TODAS las sesiones de rol que el navegador tenga activas a la vez, no solo
la de esa pestaña. Efecto colateral esperado, una sola vez al deployar:
quien tuviera una sesión activa con la cookie vieja quedó desloguead@ (hay
que volver a entrar).

**JSON crudo en pantalla al fallar un POST de página completa** (2 rondas):
los `<form>` de `/admin` y `/plataforma` son POST de página completa, no
fetch. Si la ruta respondía con una excepción -- sesión vencida
(`HTTPException` 403/401) o cualquier otra sin manejar (ej. un 500 por un
hipo transitorio) -- el navegador reemplazaba TODA la pantalla por el JSON
crudo de FastAPI ("error técnico feo en pantalla negra"). Dos manejadores
nuevos en main.py, usando el mismo criterio (`_es_navegacion_de_pagina`:
pide `text/html`, no es una llamada fetch/JS que ya sabe leer el JSON con
`await r.json()`; y `_panel_de(path)`/`_rol_de(path)`, a qué pantalla y rol
corresponden según el prefijo de la ruta):
- `sesion_vencida_o_denegada` (`@app.exception_handler(HTTPException)`):
  con sesión inválida/inexistente del rol que esa pantalla necesita Y
  navegación real, redirige a `/admin` o `/plataforma` (login) en vez del
  JSON. Un 403 legítimo con sesión VÁLIDA del rol correcto (módulo no
  habilitado, CUIL ajeno, etc.) no se toca.
- `error_no_manejado` (`@app.exception_handler(Exception)`, ya existía para
  garantizar JSON siempre): con navegación real, además redirige al panel
  (`/admin?error=guardado` o `/plataforma?error=guardado`, con un aviso "No
  se pudo guardar, probá de nuevo") en vez del JSON crudo.
- **Ojo**: originalmente se sospechaba que el 500 intermitente reportado
  ("se corta a los 2-3 minutos, específicamente al guardar") era Postgres
  en Render cortando conexiones ociosas -- el engine (db.py) usa
  `pool_pre_ping=True` + `pool_recycle=300` + keepalives de TCP por las
  dudas, mitigación que se mantiene por las dudas pero **no era la causa
  real**: un repro concreto del usuario (dos pestañas, roles distintos)
  apuntó a la cookie compartida de arriba. Si vuelve a aparecer un 500 sin
  relación a pestañas/roles, revisar los logs de Render (traceback completo
  con `traceback.print_exc()` en `error_no_manejado`).

## Decisiones tomadas — detalle de implementación

**Tamaño de logos, unificado en 76px (2026-08-14)**: el logo de plataforma
en los 4 logins (`admin_login.html`, `plataforma_login.html`,
`trabajador_login.html`, `elegir_sindicato.html`, clase `.logo-recuadro`) y
el logo del sindicato en el resto de las pantallas (`portada.html` vía
`.enc .logo`/`.enc .logo-fallback` en marca.css, `verificar_credencial.html`)
comparten el mismo tamaño de 76px. En trabajador.html y admin.html, donde el
logo de plataforma y el del sindicato conviven en el mismo header
(`.logo-plataforma-header` + `.sind`), se agrandaron los DOS juntos para que
no queden desparejos entre sí.

**Sin fondo blanco forzado + reducción en mobile (2026-08-15)**: todas las
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

## Rediseño de interfaz
Sistema de diseño nuevo (`.claude/skills/diseno-mi-trabajo/SKILL.md`,
`static/marca.css`): portada del trabajador oscura, todo lo demás claro con
encabezado oscuro. 4 colores por sindicato en vez de 3 (ver "Decisiones
tomadas" en CLAUDE.md).

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
fases todavía no estaban implementadas). Se guarda como
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
  con migración de datos). Cambiar el estado o agregar una nota **desde el
  admin** dispara automáticamente una Notificacion `origen="sistema"` al
  trabajador (Fase 2); una nota **del trabajador** NO se auto-notifica (no
  tiene sentido notificarse a sí mismo) — probado explícitamente en
  `test_tramites.py`. **`terminado` es un estado final**: ni
  `db.cambiar_estado_tramite` ni `db.agregar_nota_tramite` (de cualquiera de
  los dos lados) aceptan más cambios sobre un trámite ya terminado -- ambas
  funciones devuelven `False` (main.py lo traduce a 400 con mensaje
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
  agregado a la sub-pestaña "Ver trámites" de `/admin`.

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
admin.html/trabajador.html, etc.) el tamaño de 76px unificado no cambió.

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

**Pulido posterior (2026-08-17)**: el degradé de `.caja` pasó de
`#a8ada8 → #8d928c` a `#bfc3bf → #9ea29d` -- se calculó aclarando el punto
medio del degradé un 20% hacia blanco y agrandando un 20% la distancia
entre los dos extremos respecto a ese punto medio (no un simple +20% por
canal), para que el pedido "20% más claro" y "20% más de contraste" fueran
cambios independientes y no se cancelaran entre sí.

**Logo el doble de grande en mobile, +50% en desktop (2026-08-25)**:
`.logo-recuadro` pasó de 148px→222px en desktop y de 85px→170px en mobile,
en las 4 pantallas de login reales (`admin_login.html`,
`empresa_login.html`, `plataforma_login.html`, `trabajador_login.html`) --
**no** en `elegir_sindicato.html`/`elegir_sindicato_empresa.html`, que no
son logins (son el selector de sindicato/empresa post-login en pluriempleo)
y quedaron en su tamaño propio (76px/61px, el unificado del resto de la
app). Verificado que 222px entra sin desbordar dentro de `.caja`
(`max-width:380px`, padding 30px por lado → ~320px de ancho interno).

## Constructor visual de Trámites (2026-08-16)
El pedido original era un editor de lienzo libre (drag X/Y) para maquetar
el formulario antes de publicarlo -- se evaluó y se descartó por costo
(ver "Pendientes" en CLAUDE.md, punto 4). En su lugar, tres piezas más
livianas que resuelven el mismo problema real (un campo SI/NO no debería
ocupar todo el ancho de la pantalla):

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
  tipo de trámite (el prefijo del número de expediente) es texto libre a
  propósito -- no se agregó validación de formato, solo la explicación de
  qué hace ese campo en la ayuda.
- **Overlay compartido**: `#overlay-ayuda`/`#overlay-ayuda-contenido`,
  reutilizado por cualquier `abrirAyuda(clave)` -- no hay un overlay por
  cada ayuda, uno solo que cambia de contenido.
- Quedan afuera, evaluadas y descartadas a propósito: las ayudas largas de
  varias pantallas de `/plataforma` (marca de la plataforma, tokens de IA,
  recibos con alerta, Topes SS) -- el patrón ya generalizado hace que
  sumarlas sea barato cuando se pida, pero no se tocó esa pantalla en esta
  pasada (el pedido fue puntual sobre admin.html).

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
Cuarto actor de la plataforma. Se construyó en rama `empleadores` (6 fases,
un commit por fase) y está mergeada a `main`. Hasta ahora el empleador era
solo un dato suelto (`Concepto.cuit_empleador`, `Trabajador.cuit_empleador`);
esta rama le dio identidad propia: CRUD desde `/admin`, login/autorregistro
propio, mensajería sindicato→empresa y formularios/trámites "externos" —
completamente separados de los sistemas homólogos del trabajador
(aislamiento total, mismo criterio que ya usa el resto de la plataforma
entre sindicatos).

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
  deliberadamente distintos de los del trabajador, mismo motivo que
  "Cookie de sesión separada por rol": las dos sesiones tienen que convivir
  sin pisarse en el mismo navegador). Con el CUIT en varios sindicatos,
  `elegir_sindicato_empresa.html` deja elegir; con uno solo, entra directo.
- **App del empleador: `/empresa/inicio` (portada con tarjetas) +
  `/empresa` (tabbar de 2 pestañas, Notificaciones y Trámites)** — mismo
  patrón de dos capas que admin/trabajador (`/admin/inicio` + `/admin`,
  `/app/inicio` + `/app`). Al principio de esta rama `/empresa` era la
  única pantalla ("con solo 2 funcionalidades no hace falta esa capa
  extra"); se agregó la portada después, ver "Portada de /empresa..." más
  abajo, para el círculo de perfil y el formato de tarjetas.
- **Notificaciones a empleadores**: tablas propias
  (`NotificacionEmpleador`/`NotificacionEmpleadorDestinatario`), mismas
  columnas y mismo flujo preview→confirmar→enviar que ya existe para
  trabajador, pero **completamente separadas** — nunca comparten fila con
  las notificaciones al trabajador, ni siquiera cuando el mismo número de
  identidad es CUIL de un trabajador y CUIT de un empleador a la vez
  (verificado con test explícito). Criterios de destinatarios: CUIT
  puntual, "todos los empleadores activos", o por provincia — sin
  seccional ni cuit_empleador (no aplican del lado empleador). UI del lado
  admin en la sub-tab "Notificaciones" de "Empleadores"; del lado
  empleador, la pestaña Notificaciones de `/empresa` es directamente la
  lista con acordeón (sin modal, a diferencia del trabajador — acá la
  pestaña ya es el contenido).
- **Trámites externos**: mirror completo del sistema de Trámites del
  trabajador sobre 6 tablas propias (`TipoTramiteEmpleador`,
  `CampoTramiteEmpleador`, `TramiteEmpleador`, `RespuestaTramiteEmpleador`,
  `NotaTramiteEmpleador`, `TramiteEmpleadorLog`) — mismos tipos de campo,
  mismo ancho completo/mitad/tercio, mismo constructor con arrastrar para
  reordenar y vista previa en vivo, misma numeración de expediente con
  reintento ante colisión, mismos 5 estados (`iniciado → en_tratamiento →
  respondido → espera_info → terminado`, con `terminado` bloqueando
  cambios de cualquier lado). El constructor vive en `/admin` →
  "Empleadores" → sub-tab "Trámites", con sus propios 2 sub-sub-tabs ("Ver
  trámites"/"Crear formularios", namespace `.emptram-subtab`/
  `cambiarSubEmpresaTramite`, SIN compartir funciones ni listeners con el
  constructor de trabajador). Cambiar el estado o agregar una nota **desde
  el admin** dispara automáticamente una notificación al empleador (mismo
  criterio que `_notificar_cambio_tramite` para trabajador); una nota de la
  empresa NO se autonotifica.
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
  `foto_mime` (migración `bd0236c61d6c`) -- una sola por CUIT, no por
  sindicato, mismo criterio que `CuentaTrabajador.foto_datos`. Rutas
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
- **Trámites: popup para elegir estado después de responder** (2026-08-18,
  luego reemplazado por el chat estilo WhatsApp del 2026-08-19, ver más
  abajo -- se deja documentado por el bug de z-index que enseñó, útil para
  cualquier overlay/modal futuro): mandar una nota nunca cambió el estado
  del trámite por sí solo -- pero como responder suele implicar avanzarlo,
  se agregó un popup (`#overlay-estado-tramite`) justo después de enviar
  la nota, con el estado actual preseleccionado. **Ojo con dónde vive en
  el HTML**: tiene que estar FUERA de `.app-bar-fija` (position:sticky +
  z-index:21) -- un z-index más alto puesto en un descendiente de ese
  contenedor queda atrapado comparándose solo contra otros descendientes
  de `.app-bar-fija`, así que nunca le gana en pantalla a un modal que
  vive afuera. Se descubrió armando esta misma feature: el popup quedaba
  tapado detrás del modal de detalle de trámite.

## Chat de Trámites estilo WhatsApp (2026-08-19)
Rediseño visual de las 4 pantallas que muestran el detalle de un trámite
(trabajador.html, empresa.html, y las dos ramas del modal de admin.html) --
reemplaza la lista de "Notas" + el "Historial" aparte (mostraban casi la
misma información dos veces, el segundo era prácticamente un eco del
primero) por un solo hilo cronológico tipo chat: mensajes propios a la
derecha, de la contraparte a la izquierda, avatar chico (foto de perfil o
logo del sindicato) para identificar de un vistazo, texto recortado a 2
líneas + ícono de clip si hay adjunto. Los cambios de estado (`log`,
filtrado a solo `creado`/`cambio_estado` -- las entradas `nota_admin`/
`nota_trabajador`/`nota_empresa` se descartan porque ya se ven como
burbujas) quedan como píldoras de sistema centradas, intercaladas en el
mismo hilo por fecha.

- **Un solo modal para leer + responder + cambiar estado**: clickear
  cualquier burbuja (o el botón "Responder"/"Responder o cambiar estado…"
  al pie del chat cuando no hay nada para clickear todavía) abre un modal
  con el mensaje completo, la caja de respuesta, y -- solo del lado admin
  -- el selector de Estado + "Actualizar estado", todo junto. Esto
  **reemplazó** el popup "¿Este trámite cambia de estado?" del punto
  anterior: ya no hace falta, la decisión de estado vive en el mismo lugar
  que la respuesta en vez de en un paso aparte.
- **Avatar por foto de perfil**: trabajador.html usa `/perfil-foto/{cuil}`
  (la propia, si `tiene_foto_perfil`) para sus propios mensajes y el logo
  del sindicato (`/logo/{id}`, ya público) para los del sindicato; mismo
  criterio invertido en empresa.html con `/perfil-empleador-foto/{cuit}`.
  admin.html necesita ver la foto de la CONTRAPARTE (trabajador o
  empleador), que antes solo la veía su propio dueño -- `GET /perfil-foto/
  {cuil}` y `GET /perfil-empleador-foto/{cuit}` (main.py) ahora ADEMÁS
  autorizan al admin de un sindicato donde ese CUIL/CUIT esté empadronado/
  dado de alta (mismo criterio que ya usa `_autorizado_para_tramite` para
  los adjuntos). Sin foto (403/404 o una imagen no decodificable), el
  `<img onerror="...">` cae a un ícono/iniciales de respaldo -- no hace
  falta un flag "tiene_foto" por mensaje, el fallback es puramente client-
  side.
- **Bug real encontrado y corregido armando esto**: las funciones
  `async function` declaradas DENTRO de un bloque `if (...) { }` (como el
  `if (document.getElementById('tp-tramites')) {...}` que envuelve todo el
  JS de Trámites en trabajador.html/empresa.html) NO se filtran al scope
  global por semántica Annex B del motor de JS -- a diferencia de las
  `function` comunes, que sí lo hacen. Como el formulario de respuesta usa
  `onsubmit="return enviarNotaTramiteTrab(event)"` (un atributo HTML
  inline, que resuelve el nombre contra `window`), la función no se
  encontraba y el formulario hacía un submit real de página completa en
  vez de llamarla. Se corrigió asignando explícitamente
  `window.enviarNotaTramiteTrab = async function (ev) {...}` -- mismo
  patrón que el código ya usaba para `window.abrirTramiteDetalleTrab`.
  Las funciones sync (`abrirMensajeTramiteTrab`, etc.) no tienen este
  problema, sólo las `async`.

## Piloto de RAG sobre el convenio (2026-08-23)

Rama `rag-convenio`, 4 bloques. Plan en `PLAN_RAG_CONVENIO.md`, medición en
`medicion_rag/`. Objetivo declarado: **aprender el patrón RAG** en algo de
bajo riesgo antes de aplicarlo a algo crítico.

### Lo que se midió ANTES de escribir código

La dimensión del vector queda fijada en la columna y cambiarla es migración
más reindexado completo, así que el modelo se eligió con evidencia. Se midió
con el convenio real de AEFIP (74 páginas, 174 artículos) y 18 preguntas —
16 con artículo esperado y 2 que el convenio NO contesta:

| Modelo | dim | recall@8 | margen |
|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | 76% | -0,029 |
| paraphrase-multilingual-mpnet-base-v2 | 768 | 47% | -0,106 |
| **intfloat/multilingual-e5-large** | **1024** | **94%** | **+0,011** |

**mpnet perdió siendo el doble de grande que MiniLM.** No es tamaño, es
familia: los `paraphrase-*` son de similitud SIMÉTRICA y RAG es asimétrico
(pregunta corta contra párrafo largo). Regla para el futuro: elegir por
familia antes que por dimensión.

### El hallazgo central: la baranda no puede ser un número

El margen de e5 es positivo pero de 0,011. La pregunta *"¿cómo se afecta mi
SIPES si tengo inasistencias?"* — que el convenio no contesta — puntúa 0,816
y recupera los artículos 63 y 64, porque la pregunta ES sobre inasistencias.
La peor pregunta legítima puntúa 0,826.

**Los vectores no distinguen "habla del tema" de "contesta la pregunta"**:
esa diferencia es semántica, no geométrica. Así que el umbral quedó como
filtro barato para lo evidente (Puerto Madero, 0,766) y la baranda real vive
en el prompt, con el caso de las inasistencias escrito como ejemplo. Por lo
mismo RAG usa `claude-opus-5`: acá el juicio del modelo ES la baranda.

En el test de aceptación el sistema rechazó las dos negativas, incluida la
difícil. 8 de 8.

### Lo que el convenio real enseñó sobre el troceo

Ninguno de los tres se hubiera visto con un documento de juguete:

1. **Las notas de acta fuera del texto vectorizado.** Son ~116 con redacción
   casi idéntica: adentro hacían que el 60% de los artículos se parecieran
   por su boilerplate en vez de por su contenido.
2. **Los encabezados de sección van al fragmento SIGUIENTE.** Están escritos
   antes del marcador del artículo al que pertenecen. Caso real: "6)
   INDEMNIZACIÓN ESPECIAL POR JUBILACIÓN" quedaba al final del artículo 23,
   que habla de guarderías — y la búsqueda de jubilación traía ese.
3. **Sub-trocear los artículos largos.** Van de 67 a 11.812 caracteres; los
   29 que superaban el límite del modelo se truncaban EN SILENCIO.

### Bugs encontrados al probar, y su causa real

- **Un documento podía quedar en "procesando" para siempre.** Apareció al
  cortarse el proceso a mitad de un reindexado. El manejo de excepciones no
  cubre esto: no hay excepción, hay muerte del proceso — y en Render pasa con
  CADA deploy que ocurra mientras alguien indexa. El arreglo aprovecha una
  certeza: la indexación corre en un hilo de ESE proceso, así que ninguna
  sobrevive a un reinicio; al arrancar, todo lo que esté en "procesando"
  está muerto por definición.
- **Memoria al indexar.** Embeber 246 fragmentos de una sola vez pide ~1 GB
  en un array y tumba el proceso. De ahí los lotes de 8. **El pico al
  INDEXAR supera al del modelo en reposo**: la instancia se dimensiona por la
  carga, no por la consulta.
- **"TITULO IESTATUTO".** La extracción pega el número romano con el nombre
  de la sección; esa cadena entraba al texto vectorizado como token basura.
- **"De dónde sale" mentía.** El pie listaba los 8 fragmentos que se le
  pasaron al modelo, no los que citó. Se filtra por número de artículo
  presente en la respuesta — justo la parte que tiene que dar confianza.

### Números para dimensionar

| | |
|---|---|
| Indexar un convenio de 74 páginas | ~9 min 15 s (247 fragmentos) |
| Carga del modelo, ya descargado | 3,3 s |
| Modelo en disco / RAM | 2,1 GB |
| Una consulta del trabajador | 88 ms + la llamada al modelo |

Para desplegar en Render hace falta **4 GB de RAM** y **pre-descargar el
modelo en el Build Command** — el filesystem es efímero y bajar 2,1 GB en el
primer request deja el servicio colgado ~75 s después de cada deploy.

### Lo que quedó afuera y por qué

- **Índice HNSW**: con pocos miles de fragmentos el escaneo secuencial gana,
  y uno construido sobre tabla vacía hay que reconstruirlo igual.
- **Gobernar la indexación desde plataforma** (ejecutarla fuera de horario
  pico o agendada), para que los 9 minutos de CPU no degraden la app. Idea
  acordada, sin implementar.
- **El sub-troceo parte las tablas.** Lo detectó el propio modelo al
  responder sobre el adicional técnico: avisó que su fragmento del cuadro de
  porcentajes estaba cortado. No rompe nada — avisa honestamente — pero es el
  próximo lugar donde mirar para mejorar calidad.

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
no se amplía ese flujo transitorio. Bloqueo real: `admin_usuario_baja` no
deja desactivar al último administrador activo del sindicato (si no, un
sindicato podría quedarse sin nadie que pueda entrar a `/admin`, y solo
plataforma podría reactivarlo a mano).

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
  **Ojo con el alcance**: `Trabajador` es por sindicato (pluriempleo), así
  que esto edita el empadronamiento del sindicato ACTIVO nada más -- no
  existe un domicilio único de la persona en este modelo, no se tocó esa
  arquitectura para esta feature.
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

## Versionado — detalle
`version.py`: constantes `VERSION_TRABAJADOR`/`VERSION_ADMIN`/
`VERSION_PLATAFORMA` (arrancan las tres en "0.01.00") + `FECHA_VERSION`. Se
actualizan a mano en cada deploy — el número lo indica el usuario en el
prompt de cambio, no hay automatismo. La regla de incremento está en
CLAUDE.md, sección "Método de trabajo". Cada pantalla de inicio (portada,
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

## Hallazgo pendiente, no arreglado
`db.cargar_seed_si_vacio()` sigue disparando el seed histórico de AEFIP
(`data/seed_aefip.json`) apenas la tabla `Concepto` está vacía, aunque
"Decisiones tomadas" (CLAUDE.md) dice que la demo arranca sin AEFIP. Se
nota al recrear la base local desde cero (`db.crear_tablas()` sin
`cargar_demo.py` corrido antes): aparece un sindicato "AEFIP" fantasma con
id=1, corriendo los ids de los sindicatos de demo. No afecta producción
real (nunca se recrea la base de Render desde cero), pero conviene
revisarlo antes de confiar en ids fijos en scripts de diagnóstico.

## Desarrollo local con Postgres — detalle (2026-08-16)
`docker-compose.yml` (raíz del repo) levanta un Postgres 16 en
`localhost:5432`, con usuario/base `mitrabajo`/`mitrabajo_dev` (credenciales
de desarrollo, sin ningún secreto real). Con `DATABASE_URL` descomentado en
`.env`, `db.py` detecta Postgres solo (misma lógica que ya elegía el motor
en producción, sin cambios de código) y el flujo local pasa a ser IDÉNTICO
al de producción: `alembic upgrade head` crea el esquema (no
`crear_tablas()`), después `cargar_demo.py` siembra los 2 sindicatos de
demo.

- **Bug real encontrado al hacer esto** (y la razón de por qué valió la
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
  su SQLite temporal). `conftest.py` (raíz del repo) fuerza
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

## App del trabajador instalable (PWA) — 2026-08-24
Pedido explícito del usuario, evaluado antes de construir (bajo riesgo,
aditivo: manifest + íconos + JS de banner + un service worker mínimo, sin
tocar rutas ni lógica existente). Alcance a propósito acotado a la app del
**trabajador** (`/app/inicio` + `/app`, `scope` del manifest = `/app`) — no
toca `/admin`, `/plataforma` ni `/empresa`.

- **Ícono, Variante A**: hexágono central+derecho en línea blanca, hexágono
  izquierdo relleno color miel, sobre fondo azul oscuro (`#152238`) — mockup
  que pasó el usuario (dos variantes, A y B). Se previsualizaron ambas como
  ícono recortado a distintos tamaños reales (40-56px) antes de elegir: la
  B (las 3 solo con línea) perdía nitidez a tamaño chico, la A se mantenía
  legible. El usuario confirmó la A.
- **Generación de los PNG, sin librería de SVG disponible**: este entorno
  de desarrollo no tiene Node.js, cairosvg, rsvg-convert ni Inkscape
  instalados -- se generaron los 5 archivos (`static/icons/icon-192.png`,
  `icon-512.png`, `icon-512-maskable.png`, `apple-touch-icon.png` 180px,
  `favicon-64.png`) con un script Python de un solo uso (Pillow, ya
  instalado en el Python del sistema) que dibuja los mismos polígonos
  exactos del mockup aprobado -- NO una aproximación nueva, los mismos
  puntos que se usaron en la vista previa que el usuario vio y confirmó.
  El script vive solo en el scratchpad de la sesión, no en el repo (los
  PNG resultantes sí se commitean, son el artefacto final).
- **¿Por qué el ícono de Colm3na antes de terminar el rebranding
  completo?**: el usuario está en pleno rebranding a "Colm3na" pero el
  resto de la app (títulos, textos) todavía dice "Mi Trabajo" en todos
  lados. Se usó igual el ícono/nombre "Colm3na" en el manifest y en
  `apple-mobile-web-app-title` porque el usuario lo pidió explícitamente
  ("todavía estamos en un entorno controlado, sabemos qué teléfonos
  instalamos") -- transitorio, sabiendo que en Android el ícono se
  actualiza solo cuando esté el definitivo, pero en iPhone cada usuario que
  ya lo instaló va a tener que reinstalar a mano para ver el ícono nuevo
  (limitación real de "Agregar a pantalla de inicio" de Safari, sin
  solución del lado del servidor). Si en algún momento se define el ícono
  definitivo de Colm3na, hay que avisarle a los usuarios de iPhone que
  reinstalen -- no hay forma de forzarlo.
- **`manifest.json`** (`static/manifest.json`): `name`/`short_name`
  "Colm3na", `start_url` `/app/inicio` (la portada, entrada natural),
  `scope` `/app`, `display` `standalone`, `background_color`/`theme_color`
  fijos en `#152238` (el fondo del ícono) -- **no** toma el color de marca
  del sindicato activo, a propósito: es un solo ícono/nombre para toda la
  plataforma (decisión explícita del usuario sobre la alternativa de un
  ícono por sindicato, que hubiera exigido generar el manifest de forma
  dinámica según sesión -- mucho más complejo, con casos borde como qué
  ícono mostrar en pluriempleo antes de elegir sindicato).
- **Bug real encontrado armando esto: el service worker no podía pedir
  scope `/app`**: un service worker registrado desde `/static/sw.js` tiene
  como scope máximo permitido la carpeta donde vive el archivo
  (`/static/`) -- pedir `{scope: "/app"}` desde ahí lo rechaza
  (`SecurityError`, la promesa de `register()` rechaza sin caer a ningún
  scope por default). Fix: ruta nueva `GET /sw.js` (main.py, servida desde
  la raíz) que devuelve el mismo archivo `static/sw.js` con el header
  `Service-Worker-Allowed: /app` -- `pwa.js` registra contra `/sw.js`, no
  `/static/sw.js`. Confirmado con `navigator.serviceWorker.getRegistrations()`
  en el navegador: `scope: ".../app", active: true`.
- **El service worker NO cachea nada, a propósito**: solo existe para
  cumplir el requisito de instalabilidad de Chrome/Android (manifest +
  HTTPS + service worker registrado). Cada `fetch` hace pass-through
  directo a la red (`event.respondWith(fetch(event.request))`). Se decidió
  así porque Render redespliega con cada push -- un service worker que
  cacheara el HTML/JS de la app dejaría a un trabajador "pegado" en una
  versión vieja sin que se note, silenciosamente. Si en el futuro se
  quiere soporte offline real, hay que diseñar la invalidación de cache
  atada a la versión de deploy (`version.py`), no antes.
- **Banner de instalación, discreto y con cadencia** (`static/pwa.js`,
  cargado solo en `trabajador.html` -- la portada solo registra el service
  worker, no muestra el banner, decisión explícita del usuario: "que ya
  vio la app funcionando antes de que le pidan instalarla"):
  - **Android/Chrome**: captura `beforeinstallprompt` (`e.preventDefault()`
    + se guarda el evento), muestra a los 1.5s una barra fija angosta
    arriba de la tabbar (`bottom:calc(76px + env(safe-area-inset-bottom))`
    -- el primer intento la superponía a la tabbar, corregido) con texto +
    botón "Instalar" (dispara `e.prompt()` real) + botón cerrar. Si el
    usuario instala (`outcome === "accepted"`), no se cuenta como
    descarte; si cierra o el prompt nativo se descarta, sí.
  - **iPhone/Safari**: no existe `beforeinstallprompt` en iOS -- se
    detecta por `navigator.userAgent` (`/iPhone|iPad|iPod/`) y se muestra
    la misma barra pero con instrucciones manuales ("tocá Compartir y
    elegí 'Agregar a inicio'") en vez de un botón que instale de verdad --
    no hay forma de automatizar esa parte desde JS en Safari.
  - **Cadencia**: `localStorage` (clave `colm3na_pwa_instalar`, sin tocar
    la base de datos -- es puramente del lado del cliente, por diseño, no
    hace falta que sobreviva a un cambio de dispositivo). Se vuelve a
    mostrar recién a los 7 días del último aviso, y deja de mostrarse
    después de 5 descartes en total (decisión del usuario: "cada semana,
    con tope"). Si la app ya está instalada
    (`matchMedia('(display-mode: standalone)')` o `navigator.standalone`
    en iOS) no se muestra nunca, sin importar la cadencia.
  - Solo corre en `/Android|iPhone|iPad|iPod/` -- en desktop no se ofrece
    instalar (el pedido fue específicamente sobre el teléfono).
- **Verificado en el navegador** (no simulado): registro real del service
  worker con el scope correcto, `beforeinstallprompt` disparado a mano
  (evento sintético con `prompt`/`userChoice` mockeados) mostrando el
  banner de Android y confirmando que "Instalar" + descartar incrementa
  `descartes`/actualiza `ultimoAviso` en `localStorage`; user-agent de
  iPhone simulado mostrando la tarjeta instructiva; tope de 5 descartes
  probado subiendo el contador a mano -- confirmado que a partir de ahí
  no se vuelve a mostrar aunque se dispare el evento de nuevo.
- **Test automatizado** (`test_pwa.py`): `/sw.js` responde 200 con el
  header `Service-Worker-Allowed: /app` y content-type de JavaScript;
  `manifest.json` es JSON válido con `scope`/`start_url` correctos; los 3
  íconos que declara el manifest existen y responden 200.

### Ajuste post-deploy (mismo día): cadencia más generosa + link fijo
El usuario probó en un Android real: el banner apareció, tocó "Instalar",
el diálogo nativo se cerró sin confirmar (probablemente sin querer) y el
banner no volvió a aparecer -- comportamiento esperado del código original
(7 días de enfriamiento desde el primer descarte), pero demasiado
agresivo para un descarte accidental tan temprano.

- **Cadencia en dos fases**: los primeros `PWA_TOPE_RAPIDO` (5) descartes
  reintentan al día siguiente (`PWA_DIAS_RAPIDO`); de ahí en más pasa a
  `PWA_DIAS_SEMANAL` (7 días), hasta un tope total `PWA_TOPE_DESCARTES` (8)
  -- ya no cuesta una semana entera errarle al primer intento.
- **Link fijo, independiente de la cadencia** (`#pwa-link-fijo`,
  `_pwaCrearLinkFijo()`): pastilla chica y discreta, abajo a la izquierda
  (simétrica a los botones flotantes de Inicio/Salir que ya viven abajo a
  la derecha, sin superponerse), que NO depende de `localStorage` ni de la
  cadencia -- una vez que Chrome dispara `beforeinstallprompt` (o siempre,
  en iOS, que no tiene ese evento) queda ahí de forma permanente hasta que
  la app se instala. Pedido explícito del usuario ("que le quede el link
  por si le pasa lo mismo"): si el banner grande se cierra por error, el
  trabajador conserva una forma de reintentar sin esperar la cadencia.
  Reusa el mismo evento `beforeinstallprompt` guardado (`_pwaDeferredEvento`,
  variable de módulo) que ya capturó el listener del banner automático --
  no hace falta que el navegador lo dispare dos veces.
- Verificado en el navegador: se cierra el banner grande (mismo flujo que
  reportó el usuario) y se confirma que el link fijo sigue en pantalla y
  que tocarlo dispara `prompt()` de nuevo sobre el mismo evento guardado.
- **Versión**: solo `VERSION_TRABAJADOR` se incrementó (0.14.20 → 0.15.20)
  -- es la única de las tres apps que tocó esta feature; `VERSION_ADMIN`/
  `VERSION_PLATAFORMA` quedaron sin cambios a propósito, a diferencia de
  otras veces que las tres se movieron juntas por coincidir en el mismo
  deploy.

**Límite real descubierto después de este deploy, con fix**: probando en
un Android real, después del primer descarte del diálogo nativo, ni el
banner ni el link fijo volvieron a aparecer -- con la versión nueva ya
confirmada desplegada (`0.15.20` visible en "Acerca de") y la app
efectivamente NO instalada. Causa: **Chrome tiene su propio enfriamiento
interno para `beforeinstallprompt`**, separado por completo de la
cadencia que maneja `pwa.js` -- después de que el usuario descarta el
diálogo nativo de instalación, Chrome puede dejar de disparar ese evento
en el origen por un tiempo (protección propia contra el spam de prompts),
y además no lo dispara necesariamente apenas carga la página: en otra
prueba del usuario apareció recién al navegar a "Ver mis recibos
verificados", varios segundos después de entrar -- Chrome exige cierto
"engagement" antes de decidir ofrecerlo, no es instantáneo. El bug real
de diseño (no solo del navegador): tanto el banner como el link fijo
dependían los dos de que ese evento se disparara -- si Chrome no lo
dispara nunca en la sesión, el link quedaba mudo (invisible), sin ninguna
forma de instalar.

**Fix**: `_pwaCrearLinkFijo()` ahora se llama SIEMPRE al principio de
`initBannerInstalar()` (mobile + no instalada), sin esperar ningún
evento -- ya no vive adentro del listener de `beforeinstallprompt`. Su
acción (`_pwaAccionLinkFijo()`) resuelve en tres pasos: iOS → instrucción
de Compartir de siempre; Android con evento ya capturado
(`_pwaDeferredEvento`) → dispara el diálogo nativo directo; Android SIN
evento capturado (Chrome no lo disparó todavía, o nunca) → instrucción
manual nueva ("tocá ⋮ y elegí 'Instalar app'"), que siempre funciona
porque ese menú de Chrome no depende de `beforeinstallprompt` -- es la
vía de instalación nativa del navegador, presente en cualquier sitio que
cumpla los requisitos de instalabilidad (manifest + service worker +
HTTPS), dispare o no el evento. Verificado en el navegador: el link
aparece de inmediato al cargar la página SIN disparar el evento, y
clickearlo sin evento capturado muestra la instrucción manual (antes,
en ese mismo escenario, no pasaba nada -- el link ni siquiera existía en
el DOM).

## Ícono oficial de Colm3na + logo de plataforma en dos versiones (2026-08-25)
El usuario pasó el manual de marca real (`MANUAL DE MARCA COLM3NA.pdf`):
paleta cerrada (`#001b3d` azul marino, `#ffffff` blanco, `#ffa100` naranja,
"usar con alto contraste y sin degradados") y el logo principal (3
hexágonos en naranja con nodos/líneas tipo circuito + wordmark "Colm3na",
la "3" siempre en naranja) en dos usos permitidos: sobre blanco (texto
navy) y sobre navy (texto blanco). Dos pedidos en uno: (1) reemplazar el
ícono transitorio de la PWA por el oficial, y (2) que el logo de la
plataforma pueda tener DOS versiones -- una para fondo claro, una para
fondo oscuro -- según dónde se muestre.

- **Extracción del arte real, no una aproximación a mano**: el logo del
  PDF es más detallado que el mockup transitorio anterior (nodos
  circulares + líneas conectando los hexágonos, sombreado sutil) --
  reconstruirlo a mano con Pillow hubiera sido impreciso. Se usó
  `pdftoppm -r 600` (poppler, ya instalado en el sistema) para renderizar
  la página del manual a 600dpi, y un recorte programático con Pillow/
  numpy: detección de la línea horizontal bajo cada título (para no
  incluir el título en el recorte), bbox del contenido no blanco para el
  logo sobre fondo claro, y chroma-key exacto del `#001b3d` (con
  tolerancia de 30 en distancia de color, para no comerse los bordes
  antialiaseados) para volver transparente el recuadro navy y quedarse
  solo con el ícono + texto blanco. Confirmado visualmente componiendo el
  resultado de vuelta sobre navy sólido -- sin flequillo de color raro en
  los bordes del texto blanco.
- **Ícono de la PWA**: mismo set de 5 tamaños de siempre
  (`static/icons/icon-192.png`, `icon-512.png`, `icon-512-maskable.png`,
  `apple-touch-icon.png`, `favicon-64.png`), ahora generados recortando
  SOLO el glifo de hexágonos (sin el wordmark) del arte oficial extraído y
  centrándolo en un cuadrado con fondo `#001b3d` -- reemplaza el ícono
  transitorio "Variante A" hecho a mano en la sesión anterior. `manifest.json`
  no cambió (mismos nombres de archivo, mismo `name`/`short_name` "Colm3na").
- **Logo de plataforma, dos variantes** (`ConfiguracionPlataforma` en
  db.py, migración `958e950a78f0`): se agregaron `logo_oscuro`/
  `logo_datos_oscuro`/`logo_mime_oscuro` -- **sin renombrar** los campos
  existentes (`logo`/`logo_datos`/`logo_mime`), que pasan a significar
  implícitamente "para fondo claro". Menos riesgoso que una migración de
  rename, y compatible con lo que ya hubiera cargado un sindicato antes de
  esta feature. Ruta nueva `GET /logo-plataforma-oscuro` (mismo patrón que
  la ya existente `GET /logo-plataforma`). `POST /plataforma/marca` ahora
  acepta un segundo archivo (`logo_oscuro`), sin afectar al primero si no
  se sube uno nuevo (`test_subir_logo_oscuro_no_toca_el_claro`).
- **Dónde va cada variante, decidido por el fondo REAL de cada lugar, no
  por conveniencia**: los 3 colores de encabezado en marca.css (`.enc`,
  `header` de admin/plataforma) son siempre `var(--marca-base)`, que para
  la plataforma es `color_primario` sin validar como oscuro pero
  default `#152238` (dark) -- en la práctica siempre oscuro. Los 6 logins
  (`admin_login.html`, `trabajador_login.html`, `empresa_login.html`,
  `plataforma_login.html`, `elegir_sindicato.html`,
  `elegir_sindicato_empresa.html`) comparten el mismo `.caja` con degradé
  gris medio (`#bfc3bf → #9ea29d`), con luminancia percibida por encima
  del umbral de "oscuro" que ya usa `_es_oscuro()` en main.py (140/255) --
  se tratan como fondo claro. Resultado: 5 lugares con encabezado oscuro
  (`admin.html`, `trabajador.html`, `empresa.html`, `plataforma.html`,
  `plataforma_portada.html`) piden `/logo-plataforma-oscuro` con fallback
  en cadena (oscuro → claro → SVG estático, para no romper nada si todavía
  no se cargó la variante oscura); los 6 logins siguen pidiendo
  `/logo-plataforma` sin cambios.
- **Panel de plataforma** (`/plataforma` → "Marca de la plataforma"): dos
  campos de carga separados, cada uno con su propia vista previa (la del
  logo oscuro se previsualiza sobre una miniatura de fondo navy, no blanco,
  para que se vea legible de entrada).
- **Bug de metodología de tests redescubierto armando esto (no es nuevo,
  pero no estaba documentado)**: correr un `test_*.py` con
  `.venv/Scripts/python.exe test_x.py` DIRECTO (sin pytest) NO pasa por
  `conftest.py` -- ese archivo solo se carga cuando pytest hace la
  recolección de tests. Como este entorno tiene `DATABASE_URL` real
  apuntando al Postgres de Docker en `.env` (ver "Desarrollo local con
  Postgres" más abajo), y `db.py` carga `.env` él mismo, correr un test
  directo así termina pegándole al Postgres de desarrollo real, no a un
  SQLite temporal aislado -- se nota con tests que asumen un estado
  "recién creado" (ej. `test_marca_por_defecto_sin_configurar`), que fallan
  la segunda vez que se corren si una corrida anterior ya escribió datos
  reales. Mitigación puntual (no un fix de código): anteponer
  `DATABASE_URL=` (vacío) al comando cuando se corre un test directo así:
  `DATABASE_URL= .venv/Scripts/python.exe test_x.py`. El `.venv` de este
  proyecto tampoco tiene `pytest` instalado (sí lo tiene el Python del
  sistema) -- por eso no alcanza con simplemente correr `pytest` en vez de
  `python` para esquivar el problema.
