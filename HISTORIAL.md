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


## "No pudimos verificar este recibo": el 500 genérico que mentía (2026-08-26)

**Síntoma reportado**: un recibo se leía bien (la IA devolvía todos los datos
y el preview los mostraba), y al tocar "Verificar" salía *"No pudimos
verificar este recibo. Probá con una foto más nítida o el PDF."* — hablando
de la foto, con un PDF nítido de una sola página. El mismo recibo había
validado bien un rato antes; entre medio, el admin del sindicato había
cargado el concepto de la cuota sindical que faltaba, más su fórmula.

**Qué era ese mensaje**: no era el lector de recibos. Era el `detail` del
handler global de excepciones (`error_no_manejado` en main.py), o sea el
texto que sale ante CUALQUIER excepción no manejada, en CUALQUIER ruta de la
app que responda por fetch. El frontend (`trabajador.html`) muestra el
`detail` tal cual. `/api/leer` había andado perfecto; lo que reventaba era
`/api/validar`, con un error de Python.

**Las dos causas posibles, las dos reproducidas con TestClient**:

1. **Un importe que la IA no pudo leer.** El extractor tiene instrucción de
   poner `null` en lo ilegible, y `validador.validar()` sumaba eso directo:
   `sum(m["importe"] for m in ingresos)` -> `TypeError: unsupported operand
   type(s) for +: 'int' and 'NoneType'`. Lo mismo con un importe que venga
   como texto, o si falta la clave `lineas`.

2. **Una fórmula mal escrita.** `_evaluar()` corre `eval(expr)` sin red. Una
   fórmula guardada como `0,015 * base_remunerativa` (coma decimal),
   `1.5% * base_remunerativa` (el signo %) o con una variable inventada tira
   SyntaxError/NameError/TypeError y tumba la verificación entera.

**Por qué apareció justo después de cargar el concepto** (vale para las dos
causas, y es lo que explica el "antes andaba"): una línea del recibo solo
entra en las sumas si matchea contra el catálogo, y una fórmula solo se
evalúa si su concepto está en el recibo (`if codigo not in importe_por_codigo:
continue`). Mientras el concepto sindical no existía, esa línea era
"desconocida" (iba a `avisos`, sin tocar ninguna cuenta) y la fórmula ni
existía. Al cargar el concepto, la línea pasó a matchear y la fórmula a
evaluarse: recién ahí el dato sucio o la expresión rota llegaron a ejecutarse.
Un dato malo puede quedar dormido meses y detonar el día que alguien carga un
concepto, que es el peor momento y en la pantalla equivocada — la del
trabajador, no la del admin que lo cargó.

**Lo que se arregló (v0.17.21 / 0.16.21)**:

- `validador.a_numero()`: TODO importe que entra al motor pasa por ahí.
  Convierte números y texto ("$ 1.234,56", "(1500)"), y ante cualquier
  ambigüedad devuelve None en vez de arriesgar un número equivocado — un
  importe mal leído en silencio es peor que uno declarado ilegible.
- `validador.lineas_legibles()`: las líneas sin importe numérico quedan
  AFUERA de los cálculos (no valen $0, que inventaría discrepancias falsas) y
  se informan en una alerta nueva, `importe_ilegible`. Los totales impresos
  ilegibles se saltean, igual que cuando el recibo no los trae.
- El `_evaluar()` de cada fórmula va dentro de un try: si la expresión está
  rota se saltea ESE chequeo con una alerta `formula_invalida` y el resto del
  recibo se verifica igual. También se blindaron `tolerancia`, los valores del
  tope y `tope_sindical_pct` contra un None en la base.
- `validador.error_de_expresion()` + POST `/admin/formula`: la expresión se
  prueba con valores de juguete ANTES de guardarla y, si no evalúa, no se
  guarda: vuelve al panel con el motivo en castellano ("el decimal se escribe
  con punto", "no existe la variable 'X'"). El error lo ve ahora el admin que
  la escribe, en el momento en que la escribe.
- El mensaje del handler global dejó de hablar de recibos y fotos: cubre toda
  la app (trámites, notificaciones, aportes), así que ahora dice que hubo un
  error inesperado. La excepción se sigue logueando completa.

**Tests**: `test_validador_robusto.py` (datos sucios de la IA + fórmulas
rotas) y `test_formula_expresion_ruta.py` (la ruta no guarda lo que no
evalúa).

**Detalle de datos que salió a la luz de paso**: la fórmula cargada tenía
target `288-01` mientras la línea del recibo trae `288-001`. Con un código
que no matchea, la fórmula no valida nada: reporta "el recibo no incluye
ese concepto" aunque el concepto esté. El panel ya marca con un chip
"⚠ código inexistente" las fórmulas cuyo target no existe en el catálogo,
pero no puede detectar un código que existe y está mal tipeado.

### Códigos de error propios (misma tanda)

Pedido directo del usuario a partir de este bug: *"quiero saber si en
cualquier caso de error no va a decir que no pudo leer el recibo... sugiero
usar una lista de códigos de Error Propio que sepamos exactamente qué es"*.

`errores.py` es el catálogo: código -> (status HTTP, mensaje). Se lanza con
`raise ErrorApp("E-...")`, y el código viaja al frontend junto al mensaje;
la pantalla lo muestra en chiquito debajo (`.cod-error`). Reglas:

- **"Probá con otra foto" es exclusivo de los errores REALES de lectura**
  (E-RECIBO-01/02 y E-APORTE-01/02). Ningún otro error puede sugerirlo.
  Hay un test que lo verifica sobre el catálogo entero, así que un mensaje
  nuevo mal redactado lo rompe.
- **E-INTERNO-00 es el único que admite no saber qué pasó** y por eso es el
  único que lleva `ref`: 8 caracteres que se imprimen junto al traceback en
  el log (`[E-INTERNO-00 ref=xxxxxxxx] POST /ruta`) y se le muestran a la
  persona. Con ese `ref` se encuentra el traceback exacto en Render sin
  adivinar el horario. Los POST de página completa (`/admin`, `/plataforma`)
  lo reciben en la URL del redirect y lo muestran en el aviso.
- **`CODIGO_POR_RUTA`** permite que una excepción no prevista en una ruta
  puntual diga algo cierto igual: `/api/validar` -> E-RECIBO-03 ("el recibo
  se leyó bien, falló la verificación"), porque ahí mandar a sacar otra foto
  sería mentira -- la lectura ya había pasado, en `/api/leer`.

**El catálogo del sindicato también dejó de tomarse como confiable** (lo
planteó el usuario: "quizá también haya que chequear el concepto y todos los
datos, alias, códigos etc"). `_clave()` pasa todo código a texto y le saca
espacios (un `"288-001 "` con un espacio al final no matcheaba NADA y no
había forma de darse cuenta mirando la pantalla); `_alias_de()` aguanta que
la columna JSON tenga un texto suelto en vez de una lista -- antes eso se
iteraba LETRA POR LETRA y metía entradas de un caracter en el índice de
matcheo, que es peor que fallar: hacía matchear líneas contra el concepto
equivocado, en silencio. `normalizar()` acepta cualquier tipo, y las líneas
que no son diccionario se ignoran.

**Tests**: `test_codigos_error.py`.

## Panel Sindical — dashboard del admin de organización (2026-08-29)

Especificación rectora: `docs/DASHBOARD.md` + mockup navegable
`docs/dashboard-sindical.html` (datos ficticios, paleta demostrativa).
Branch `feature/dashboard-sindical`, dos fases estrictamente secuenciales.

**Decisiones cerradas con Sd antes de codificar** (una pregunta por vez):
1. Consultas del bot: se REUTILIZA `ConsultaConvenio` del piloto RAG
   (+columna `tema`, NULL en lo ya registrado) en vez de crear la tabla
   nueva que pedía el documento — el doc decía "el bot no existe" pero el
   piloto ya registraba cada pregunta.
2. Resultado de validación: DOS estados (OK / con diferencias). "En
   revisión" no existe a nivel recibo (lo más parecido, `Reporte`, no tiene
   FK al recibo) y se descartó en vez de inventarlo.
3. Tipos de notificación: los reales (`origen` manual="Comunicaciones" /
   sistema="Trámites"), no los 4 del mockup; siempre desglosado leídas vs.
   no leídas (dato real en `NotificacionDestinatario.leida_en`).
4. KPI "Usuarios activos" del mockup → "Afiliados registrados":
   `registrado=True` sobre el padrón total. Es una foto (sin filtro de
   fecha); seccional y empresa sí lo recortan.
5. Módulo `"dashboard"` opt-in. A futuro habrá STD (KPIs+gráficos) y PRO
   (además el explorador), EXCLUYENTES: por eso el explorador se gatea con
   `_exigir_dashboard_detalle` (helper propio) — la diferenciación futura
   es cambiar solo ese helper.

**Fase 1 — datos.** El hueco grande era `ReciboVerificado`: todo lo
analítico vivía adentro del JSON `detalle`, y `fecha` se guardaba como
"dd/mm/AAAA HH:MM" (no ordenable — no se puede filtrar un rango con eso).
Columnas nuevas backfilleadas parseando `detalle`: `procesado_en`
(ordenable), `cuit_empleador` (normalizado a dígitos con
`validador._norm_cuil`), `categoria` (texto libre del recibo, NO hay
catálogo CCT: el filtro es por valor y el select se puebla con los
distintos del tenant), `formato`, `bruto`, `monto_diferencia` (suma de
|diferencia| de las fórmulas que no dieron — las discrepancias de texto no
traen monto), `fecha_ultimo_deposito` (con eso el semáforo por empresa es
`MAX()` por CUIT). `Tramite.resuelto_en` con backfill EXACTO desde
`actualizado` (un trámite terminado queda bloqueado, su `actualizado`
congelado ES la fecha de terminación). Estados del dashboard: iniciado →
abierto; en_tratamiento/respondido/espera_info → en proceso; terminado →
resuelto (CASE portable en SQL). 4 migraciones reversibles verificadas
up/down/up. Índices compuestos `(sindicato_id, fecha)` en recibos/trámites/
notificaciones/consultas + `(sindicato_id, cuil)` en trabajador (el join a
seccional está en casi todo).

**dashboard.py**: agregados 100% en SQL portable (SQLite para tests,
Postgres real), fechas como strings ordenables comparadas por rango (usa el
índice en los dos motores), `substr(col,1,10)` para agrupar por día,
semanas plegadas en Python (≤366 filas). Aislamiento EN el WHERE: el
`sindicato_id` sale siempre de la cookie; un id de seccional/empresa ajeno
filtra a NADA (los ids de empresa se resuelven a CUITs DENTRO del tenant,
y una lista que no resuelve mete un valor imposible, nunca "sin filtro").
Privacidad en el CASE del SQL: `CASE WHEN enviado_sindicato THEN nombre
ELSE NULL` — el dato de un recibo no enviado ni sale de la base.

**Medición (criterio <1 s con 50.000 recibos)**: `medir_dashboard.py`
siembra un tenant sintético en el Postgres local y mide por HTTP real.
Peor endpoint: 80 ms. DOS bugs del propio script en el camino: (a) el
usuario admin sintético era no-numérico y el login de /admin normaliza a
dígitos → nunca matcheaba; (b) medir recién sembrado dio 5,7 s en UN
endpoint porque el planificador no tenía estadísticas (autovacuum no había
corrido) — con `ANALYZE` explícito, 40 ms. El EXPLAIN muestra el índice
compuesto en rangos selectivos; con rangos que matchean ~76% del tenant el
planificador elige seq scan y ahí ES la elección correcta.

**Fase 2 — interfaz.** `templates/dashboard.html` + `static/dashboard.js`
+ Chart.js 4.4.9 VENDOREADO en `static/chart.umd.min.js` (nada de CDN;
`Cache-Control: public, max-age=3600` para `/static/` vía el middleware
existente + sello `?v=` en la URL, mismo patrón que /logo). Página propia
`/admin/dashboard` (patrón: link en la tira de pestañas de /admin y
tarjeta en /admin/inicio, gateados por módulo). Tipografía del sistema de
diseño (system-ui + Barlow Condensed para cifras grandes, ui-monospace
tabular para números), colores de marca del tenant, estados con los
colores fijos, y `--destacado` (default #E5188F, editable por sindicato
SOLO desde plataforma) EXCLUSIVAMENTE para selecciones/filtros activos.
Un solo objeto de estado; cada cambio = UNA ronda de fetches en paralelo
con debounce de 250 ms y AbortController; error por panel con "Reintentar"
sin tumbar el resto; estado serializado en la query string (link
compartible entre dirigentes, restaura filtros/pestaña/rango al abrirlo);
carril de consultas decidido en el SERVIDOR (flag apagado → ni el KPI ni
el panel ni la pestaña llegan al HTML). Contadores de pestañas del
explorador: la activa con su página completa, las demás con `page_size=1`
(solo el total). Cross-filtering igual al mockup, con dos adaptaciones:
la dona tiene 2 segmentos, y la fila "Sin seccional" de trámites solo
filtra estado (no hay valor de filtro para NULL).

**Verificación en navegador** (server real + tenant de 50.000): vista
inicial Hoy, presets, calendario pintando rangos que cruzan meses y
futuros deshabilitados, cross-filtering de los 4 gráficos actualizando
KPIs+chips+explorador+URL coherentes, "Ver más" paginando en servidor,
quitar chips de a uno, Reiniciar dejando todo idéntico al estado inicial,
estado vacío accionable, sin scroll horizontal en angosto y cero errores
de consola. Detalle del entorno: con el panel del navegador oculto no
corre requestAnimationFrame, así que Chart.js no anima y su hit-testing
interno queda congelado — los clicks de canvas se verificaron invocando
los handlers `onClick` como los llama la librería (con la página visible
anima normal).

**Tests**: `test_dashboard.py` (32) — privacidad y aislamiento
innegociables (incluye manipulación de query params y barrido crudo del
JSON de cada respuesta), validación de rangos, flag del bot (404 +
invisible en HTML), paginación, agregados, config de plataforma, página y
navegación gateadas, Chart.js vendoreado con cache.

## Ajustes del Panel Sindical, lotes de datos y robots E2E (2026-08-31)

Todo esto salió DESPUÉS de que el Panel Sindical ya estaba en producción,
como pedidos sucesivos de Sd mientras lo usaba con datos reales.

**Ajustes del tablero.** (a) La zona de filtros se confundía con los paneles
de datos: ahora tiene fondo gris suave con trama de puntos, y dejó de
solaparse con el encabezado (antes montaba 44px sobre él). (b) El semáforo de
aportes NO se eliminó (primera reacción de Sd fue sacarlo por poco fiable):
se aclaró en su subtítulo que se basa en la fecha de último depósito que solo
imprimen los recibos del formato nuevo, todavía pocos en relación al total.

**Modal "Ver" por fila del explorador.** El explorador mostraba filas pero no
dejaba ver el caso. Endpoints nuevos (`detalle/recibo/{id}`,
`detalle/tramite/{id}`, `detalle/notificaciones`,
`detalle/notificacion/{id}/destinatarios`, `detalle/consulta/{id}`), todos
detrás de `_exigir_dashboard_detalle` (el mismo gate que separará STD/PRO).
Lo importante: **la privacidad se aplica también acá y en el servidor** — el
detalle guardado de un recibo tiene la identidad adentro del JSON, así que
`dashboard.detalle_recibo` borra nombre/CUIL/legajo antes de responder cuando
el recibo no fue enviado voluntariamente; hay un test que planta esos datos en
el JSON y verifica que no salen.

El modal de notificaciones necesitó DOS rondas: la primera mostraba remitente
y conteos, y Sd lo rechazó ("así no sirve") porque faltaba lo esencial — a
quién se dirigió y qué decía. Quedó: destino legible (seccionales/CUILes/
empresas resueltos a nombres), el mensaje completo, lecturas del envío total
más la porción de esa seccional, y un último nivel "Destinatarios (N)" que
lista persona por persona con su fecha de lectura.

**Lotes de datos sintéticos.** Primero `cargar_lote_uom.py` (específico), y
después `cargar_lote_sindicato.py` (cualquier sindicato, `--sindicato`). La
decisión de diseño que los hace útiles: los recibos no se fabrican con
números inventados, se arman con el catálogo real y se AUTOCORRIGEN contra el
validador — se valida, se ajusta cada aporte al "esperado" que devolvió el
motor, y se repite hasta 4 veces (por si una fórmula referencia a otra). Así
el 80% "OK" sale OK con cualquier catálogo, y los errores del 20% se inyectan
después sobre un recibo ya correcto. Medido contra AEFIP real (17 conceptos,
4 fórmulas): 79,9% OK / 20,1% con discrepancias, sin tocar nada.

La segunda ronda del lote fue por otro rechazo de Sd: los trámites tenían
título pero formularios vacíos y ningún diálogo, así que servían para el
tablero pero no para mostrar contenido. Ahora los 5 tipos tienen campos
temáticos, respuestas coherentes con el tema, y el ida y vuelta
sindicato↔afiliado según cuánto avanzó el trámite.

**Bug latente encontrado acá** (anotado en BACKLOG, no arreglado): el
`numero_expediente` es único en TODA la plataforma pero su prefijo sale del
código del TipoTramite y el correlativo se cuenta por tipo — dos sindicatos
que usen el mismo código ("F01") chocan y `db.crear_tramite` agota sus 25
reintentos y revienta. El lote lo esquiva prefijando la sigla del sindicato.

**Robots E2E con Playwright** (`e2e/`, ver su README). Tres peleas con el
entorno, todas documentadas porque son del tipo que se vuelve a olvidar:

1. *No se generaban video ni traza.* Los contextos creados a mano con
   `browser.new_context()` (necesarios para simular dos personas) no heredan
   la grabación que pytest-playwright arma para la fixture `page`. Fix: la
   fixture `nuevo_actor`, que lee los flags y graba por actor.
2. *"No veo nada en vivo".* Con `--headed` la ventana se abre DETRÁS y
   `page.bring_to_front()` no alcanza: Windows impide que un proceso le robe
   el primer plano a otro (ForegroundLockTimeout). Verificado midiendo
   `GetForegroundWindow` durante una corrida. Fix: no pelear por el foco —
   `e2e/ventanas.py` marca cada ventana TOPMOST y la ubica en su franja; con
   dos actores, cada uno ocupa media pantalla y se ve el ida y vuelta.
3. *El resultado era ilegible* ("4 passed" y nada más). Fix: fixture
   `informe` con `paso()`/`dato()`, resumen por terminal y ficha
   `e2e/resultados/informe.html` que se abre sola con `--headed`. El resumen
   fuerza UTF-8 porque en cp1252 cada acento salía "?".

**Robot vivo**: `test_robot_tramite_guarderia.py`, el ciclo completo de un
trámite con dos actores (el trabajador lo presenta, el admin responde y lo
cierra, el trabajador ve la respuesta) contra el lote de AEFIP.

## Validaciones en formularios de Trámites — Fase 1: fija + consistencia (2026-09-01)

Primera fase de la capa de validaciones acordada con Sd: hasta acá un campo
de trámite aceptaba cualquier valor que pasara el tipo de dato (180 días o
9.000 días daban lo mismo). El diseño completo contempla cuatro FUENTES de
validación — `fija` (contra un valor prefijado), `lista` (datos cargados por
el admin), `sistema` (padrón/recibos/semáforo) y `externa` (API catalogada de
un sistema del sindicato) — y esta fase implementa `fija` + las reglas de
consistencia entre dos campos. Las fases siguientes están anotadas en
BACKLOG.md con sus decisiones ya cerradas.

### Decisiones de diseño (cerradas con Sd, no rediscutir)

- **Las validaciones NO son tipos de dato** (la idea original DATA/APIDATA
  se descartó): son una capa componible sobre el campo — un campo puede
  tener N validaciones de fuentes distintas a la vez.
- **`bloquea` vs `avisa`**: una validación bloqueante frena el envío con el
  mensaje del admin; una de "avisa" deja pasar y guarda el mensaje en
  `Tramite.advertencias`, visible para el operador en el modal del trámite
  (caja ámbar "Avisos del formulario"). No todo control debe frenar al
  trabajador: frenar de más lo empuja al teléfono, que es lo que Trámites
  vino a evitar.
- **En las listas se guardan hechos, no derivados** (regla para la fase
  `lista`): fecha de afiliación y no "antigüedad", que se pudre sola.
- **Validar tan cerca de la carga como se pueda**, pero el servidor decide:
  el on-blur del cliente es cortesía; `/api/tramite` re-evalúa todo.

### Dónde vive cada cosa

- **`validaciones_tramite.py`** — motor puro, sin base de datos:
  `validaciones_saneadas()` / `reglas_saneadas()` (saneo al GUARDAR: una
  validación mal formada se descarta ahí, mismo criterio que
  `error_de_expresion` con las fórmulas — no explota meses después en la
  pantalla del trabajador) y `evaluar_envio()` (la única implementación de
  la evaluación). Operadores en ASCII (`<=`, `>=`, `<`, `>`, `==`, `!=`);
  solo campos `numero`/`fecha` son validables en esta fase; mensajes por
  defecto generados al guardar si el admin no escribe uno.
- **Modelo**: `CampoTramite.validaciones` (JSON, lista de
  `{fuente, operador, valor, mensaje, bloquea}`),
  `TipoTramite.reglas_consistencia` (JSON) y `Tramite.advertencias` (JSON)
  + los tres espejos de empleador. Migración `a1f5c2d94b18`.
- **Las reglas referencian campos POR ORDEN, no por id**: editar un tipo
  REEMPLAZA sus campos (ids nuevos en cada edición, ver
  `db.editar_tipo_tramite`) y una referencia por id quedaría colgada. En el
  constructor JS las reglas guardan REFERENCIAS DE OBJETO a los campos y se
  convierten a índice recién al serializar: sobreviven a reordenar y borrar
  sin remapear nada.
- **`POST /admin/tramite-tipo/probar`** — el banco de pruebas del
  constructor ejecuta `evaluar_envio()`, LA MISMA función del envío real
  (el criterio de `resolver_destinatarios` en Notificaciones: si el preview
  y el envío validaran distinto, nadie los compara y el error es
  silencioso). Sirve a los dos constructores; acepta módulo `tramites` o
  `empleadores`.
- **422 con `errores_campos`**: el envío rechazado devuelve, además de la
  lista de errores, un mapa `{campo_id: mensaje}` para pintar el error
  debajo del campo exacto.

### Rediseño del constructor (estética "Expediente")

Elegida por Sd entre 3 propuestas (mockup en
`disenos/constructor-tramites-propuestas.html`, pestañas "Definitiva" y
"Trabajador"): ficha con **lomo numerado** (el número es el orden real y es
el agarre del drag), sellos BLOQUEA/AVISA, secciones en condensada, y a la
derecha **el teléfono del afiliado** con el banco de pruebas integrado: los
campos de la vista previa son EDITABLES con datos de prueba y "Probar el
formulario" sella el veredicto sobre la pantalla del celular (rojo "No se
puede enviar" con el primer error / verde "Listo para enviar", avisos en
ámbar debajo). Se quitó el `pointer-events:none` que hacía inertes los
inputs de la vista previa. Los dos constructores (trabajador y empresa)
siguen en namespaces JS separados (decisión ya tomada); las funciones
NUEVAS que solo renderizan (`htmlValidacionesCampo`, `htmlCampoPreview`)
sí se comparten parametrizadas por sufijo, como el chat por `familia`.

### Rediseño de la pantalla del trabajador

Pedido explícito de Sd ("que no parezca un formulario sin diseño") +
aplicar el sello. Dentro del lenguaje del trabajador (encabezado oscuro de
marca, interior claro):

- **Carátula**: gradiente base→primario con el grano del rediseño Nike,
  título en condensada mayúscula, código como chip mono y "EXP — se numera
  al enviar".
- **Progreso vivo**: "Completaste N de M" con barra en acento (separador y
  booleano no cuentan: el booleano siempre "está respondido" e inflaría).
- **Validación al salir del campo**: espejo JS de `evaluar_envio` (fija +
  consistencia), tilde verde con pop o el mensaje del sindicato en rojo;
  los "avisa" se muestran en ámbar sin frenar. Enviar con errores sacude el
  botón y scrollea al primer campo mal.
- **El sello**: al enviar OK cae "ENVIADO · EXP … · fecha" sobre el
  formulario (animación con `prefers-reduced-motion` contemplado) y el
  número queda grabado en la carátula; después se abre el detalle.

### Verificación

`test_validaciones_tramite.py` (9 tests: motor puro, saneo, rutas de alta,
envío 422 con `errores_campos`, advertencias persistidas, banco de pruebas,
espejo empleador). Regresiones: `test_tramites.py`,
`test_tramites_empresa.py`, `test_dashboard.py`, `test_modulos.py`,
`test_codigos_error.py`, `test_notificaciones_empresa.py`,
`test_cargar_demo_empleadores.py` — todos verdes. E2E `pytest e2e/ -q`:
4/4, el robot completó el ciclo entero del trámite de guardería contra el
formulario rediseñado. Flujo manual verificado en el navegador con el tipo
"F07 UOM · Licencia por cuidado de familiar" sembrado en el Postgres local
(validación en vivo, envío bloqueado, aviso ámbar, sello, advertencia en el
modal del admin).

## Validaciones de Trámites — ajustes post-estreno (2026-09-01, tarde)

Reportados por Sd probando la Fase 1 recién desplegada:

- **El 500 al editar un tipo con trámites presentados (E-INTERNO-00) era un
  bug PREEXISTENTE de Trámites**, no de la Fase 1: `editar_tipo_tramite`
  borraba y recreaba los campos, y con trámites ya enviados
  `RespuestaTramite.campo_tramite_id` los referencia — Postgres rechaza el
  DELETE por FK. Nunca se vio porque los tests corren en SQLite (que no
  exige FKs sin PRAGMA) y nadie había editado un tipo con trámites. El fix:
  la edición **sincroniza por id** (el campo que vuelve con su id se
  actualiza en el lugar y conserva sus respuestas; el nuevo se crea), y un
  campo quitado que ya tiene respuestas se marca **`retirado`** (columna
  nueva, migración `b7e3d1a5c942`) en vez de borrarse: sale del formulario
  pero el detalle de los trámites viejos conserva su etiqueta. El
  constructor ya mandaba el id de cada campo; `_campos_tramite_validos`
  ahora lo deja pasar (saneado como entero). Espejo completo en
  empleadores. Test: `test_editar_tipo_con_tramites_no_rompe_fk`.
- **Límite dinámico "hoy" en validaciones de fecha**: además de una fecha
  fija, el límite puede ser el DÍA DEL ENVÍO con margen — se guarda como
  `hoy` / `hoy+N` / `hoy-N` y se resuelve AL EVALUAR
  (`_limite_comparable`), nunca al guardar (un "hoy" resuelto al guardar se
  pudre solo). UI del constructor: selector "una fecha / el día del envío /
  días después / días antes" + días. Casos: "Fecha desde ≥ el día del
  envío" = no antedatar; "≥ 10 días después del envío" = anticipación
  mínima. El espejo JS del trabajador resuelve la fecha en hora LOCAL
  (nunca `toISOString`, que es UTC y de noche ya es "mañana"); el servidor
  usa `date.today()` — en Render eso es UTC, con la ventana 21:00–00:00
  argentina corriendo un día: mismo criterio que todo `datetime.now()` de
  la app, anotado y aceptado.
- **✗ roja simétrica al tilde**: en el formulario del trabajador el campo
  inválido muestra la ✗ en el mismo lugar y con el mismo pop que la ✓; el
  banco de pruebas del constructor también marca ✓/✗ por campo tras
  "Probar".
- **"Crear formularios" → "Crear / editar formularios"** (subtabs de los
  dos constructores + título de la ayuda, que además ganó secciones sobre
  validaciones y el banco de pruebas). El intercalado de filas subió de 5%
  a 9% del primario para que se note.

## Dashboard: filtro OK en el explorador + vista del afiliado en Comunicación (2026-09-01)

- **Elegir "OK" en la dona dejaba el explorador vacío**: `explorador_recibos`
  tenía clavado `r.estado != 'OK'` (el detalle nació como "recibos con
  diferencias", §3.3) y el filtro de resultado agregaba `r.estado = 'OK'` —
  contradicción, cero filas. Ahora el recorte aplica SOLO cuando no hay
  filtro de resultado: sin filtro el default sigue siendo el detalle
  accionable (con diferencias), con filtro responde lo elegido. Test:
  `test_explorador_recibos_filtrando_ok`; verificado contra el lote UOM
  (3.971 OK + 1.029 con diferencias = 5.000).
- **La estética del constructor de Trámites llegó a Noticias, Beneficios y
  Notificaciones**: títulos de sección en condensada (`.ct-secc`) y layout
  de dos columnas con **el teléfono del afiliado a la derecha** (`.vap-*`),
  que refleja EN VIVO lo que el admin escribe — la noticia como se ve en
  Novedades (con la imagen elegida vía FileReader), el beneficio como
  tarjeta de carrusel con el rubro sobre la imagen, y la notificación como
  le llega al trabajador (remitente, mensaje, chip de adjunto). Es solo
  cómo se VE (no valida nada); editar/cancelar refrescan el teléfono. Las
  imágenes ya guardadas no se cargan al editar (solo las recién elegidas) —
  simplificación aceptada.

## Formulario adjunto en el chat de Trámites (2026-09-01)

Pedido de Sd: el sindicato aprueba una reserva de turismo y quiere mandarle
al afiliado el formulario "Registro de pasajeros" desde el mismo chat, sin
decirle "andá a Trámites y buscalo".

- **`NotaTramite.formulario_id` (+ espejo empleador)**, migración
  `c9a2e4f7d581`. Int SIN FK a propósito: un tipo se puede borrar y el chat
  muestra "ya no disponible" en vez de impedir el borrado. El detalle
  resuelve `formulario_titulo`/`formulario_activo` en el momento.
- **Solo el admin adjunta**: en el modal de responder aparece un selector
  con los tipos ACTIVOS de la familia (trabajador o empresa). El saneo
  (`_formulario_para_chat` en main.py) descarta en silencio un id ajeno,
  inactivo o basura — mismo criterio que `_destinos_validos`. Una nota
  puede ir SOLO con el formulario (sin texto ni adjunto).
- **La tarjeta en el chat**: el trabajador/la empresa ven "📋 Título +
  botón Iniciar este trámite" que abre ese formulario directo (busca el
  tipo en su endpoint de tipos activos — un id ajeno simplemente no está).
  En el chat del admin la tarjeta queda como constancia de qué se mandó.
  La notificación del sistema avisa "te mandó un formulario".
- **Deep link** `/app?tab=tramites&formulario=<id>`: abre el formulario
  directo (sesión + módulo + tipo activo del sindicato mediante). Botón
  "Link" en la tabla de tipos del constructor para copiarlo — pensado para
  pegar en una notificación o una noticia. (Solo trabajador; en empresa la
  tarjeta del chat cubre el caso.)
- Test `test_formulario_adjunto_en_chat` en test_tramites.py (alta, nota
  solo-formulario, saneo de ids inválidos, tipo desactivado).

Nota de entorno del mismo día: Docker Desktop local entró en un loop de
"socket fantasma" (todo archivo de socket Unix creado queda imborrable:
`dockerInference`, `engine.sock`, etc. — driver afunix de Windows trabado).
Workaround: renombrar las carpetas `run`/`docker-secrets-engine` rotas; la
solución real es reiniciar Windows. No afecta producción.

## Formulario "para iniciar" en Noticias, Beneficios y Notificaciones (2026-09-01)

Extensión del formulario adjunto del chat a los tres canales de
comunicación (pedido de Sd: una noticia que abre una inscripción, un
beneficio con reserva, una notificación que exige completar datos). El
admin asocia un formulario y quien lo recibe ve **solo un ícono** (📋 en
círculo de acento) — el "completá los datos haciendo click acá" lo escribe
el admin en el propio texto, decisión explícita: sin campo de etiqueta.

- `formulario_id` en Noticia/Beneficio/Notificacion/NotificacionEmpleador
  (migración `d5b8c3e9f214`), int sin FK como en el chat. El saneo del alta
  reusa `_formulario_para_chat`; `db.formulario_activo_de()` decide si el
  ícono se muestra (tipo borrado/desactivado → desaparece, resuelto en cada
  lectura, no al guardar).
- Selector "Formulario para iniciar (opcional)" en los 4 formularios de
  admin (noticia/beneficio/notificación/notificación-empresa, cada familia
  con sus tipos) y el ícono visible en el teléfono del afiliado en vivo.
- Render del ícono: overlay de noticia (portada Y pestaña Novedades),
  overlay de beneficio, notificaciones del trabajador (modal de portada,
  vía deep link `/app?tab=tramites&formulario=`) y notificaciones de la
  empresa (apertura in-app con la maquinaria del chat).
- Tests: `test_formulario_para_iniciar_en_noticia` /
  `..._en_notificacion` (alta por ruta, exposición en API, tipo
  desactivado → ícono afuera, id basura → sin referencia).
- Verificado en vivo con el lote UOM: chat (adjuntar desde el modal →
  tarjeta → botón abre F07), noticia con ícono → deep link → formulario.

## Trámites encadenados por chat (2026-09-01, noche)

Pedido de Sd: si un trámite se SIGUE con otro formulario (aprueban la
vacante de hotel → mandan "Registro de pasajeros" por el chat), los dos
trámites tienen que verse vinculados en ambos chats, entre por el que
entre — y tanto el trabajador como el sindicato. Un formulario INICIADO
desde noticia/beneficio/notificación NO vincula (decisión explícita).

- `Tramite.origen_tramite_id` (+ espejo empleador), migración
  `e6c1d8f4a327`. Solo se setea cuando el formulario se abrió desde el
  formulario adjunto en el CHAT de otro trámite; el servidor valida que el
  origen sea un trámite del MISMO cuil/cuit y sindicato (cualquier otra
  cosa se ignora).
- El detalle expone `origen_tramite` y `derivados` (id, expediente,
  título, creado) y los cuatro chats (trabajador/empresa × usuario/admin)
  los insertan CRONOLÓGICAMENTE en el hilo como píldoras clickeables
  "⇄ Iniciado desde: EXP…" / "⇄ Desde este chat se inició: EXP…" que
  abren el otro trámite.
- **Bug encontrado al verificar**: el onclick inline de la tarjeta del
  chat referenciaba `tramitePanelActual` (un `let` del módulo) — los
  handlers inline evalúan en scope GLOBAL y tiraba ReferenceError. El id
  del trámite ahora viaja como literal en el render (variante nueva del
  hallazgo ya anotado sobre JS init y scopes).
- Se eliminaron los textos instructivos de los previews del admin ("Editá
  los datos de prueba…", "Así se va a ver en…") a pedido de Sd.
- Test `test_tramite_encadenado_desde_chat` (vínculo en ambos detalles +
  origen ajeno ignorado). Verificado en vivo: envío encadenado real desde
  el chat del F07, píldoras en las dos puntas y navegación entre ambos.

## Rediseño de los logins: credencial viva sobre colmena nocturna (2026-09-02)

Los 4 logins (trabajador, sindicato, empresa y plataforma) eran la cara de
la suite y habían quedado atrás del resto de la UI. Sd eligió entre 4
propuestas (mockup en `disenos/logins-propuestas.html`): la **credencial
viva** (opción 4) sobre el **fondo de colmena nocturna** (opción 1).

- **Fondo**: gradiente oscuro de la marca de plataforma con respiro verde
  agua, grano, y el panal de Colm3na respirando (opacity 9s) en dos
  esquinas. **Credencial**: banda superior miel→agua, logo real
  (`/logo-plataforma-oscuro` con la cadena de fallback estándar), chip de
  rol en condensada dorada, inputs oscuros con foco miel, botón ámbar en
  condensada, tira MRZ en monoespaciada y pie con claims por rol.
- **La miel (`#f0a01e`) es constante de Colm3na, NO el acento
  configurable**: es el ámbar del panal del logo (contenido fijo — Sd pasó
  el arte de referencia), y banda/chip/botón deben armonizar con él. El
  acento configurable de plataforma queda para los errores. Tinta y agua
  sí salen de la marca configurable.
- **Tilt 3D + brillo especular** que siguen al mouse: máx 2.5°/3°
  (CLAMP a [0,1] — sin él, el mouse lejos de la tarjeta la giraba 45°,
  encontrado al verificar), solo con `hover:hover` y sin
  `prefers-reduced-motion`; en mobile la credencial queda quieta. Entrada
  con fade+lift una sola vez.
- Los 4 archivos comparten el esqueleto (generado desde
  trabajador_login.html); forms, names y bloques de error se preservaron
  intactos — E2E 4/4 entrando por el login nuevo, y login real verificado
  a mano en los 4 roles. `plataforma_login.html` también entró en el
  rediseño aunque el pedido eran "las tres": dejarlo viejo desentonaba.

## Logo de Colm3na en el encabezado de la portada del trabajador (2026-09-02)

Pedido de Sd: la firma de la plataforma en la portada. Va a la DERECHA del
encabezado, discreta (24px desktop / 19px mobile, `.enc .logo-colmena` en
marca.css) — el gremio sigue mandando a la izquierda. SIEMPRE la versión
del logo para fondo oscuro: el encabezado es oscuro aunque la portada del
sindicato sea clara (probado con las dos variantes; el conditional por
portada_clara fue un primer intento y mostraba el logo de texto oscuro
invisible sobre el encabezado).

El mismo día: "no pudimos cargar tus trámites" en producción con el
usuario de prueba 27999999999 NO fue un bug de código — localmente la
carga anda perfecta — sino las 3 migraciones de los deploys del 09-01
(`c9a2e4f7d581`/`d5b8c3e9f214`/`e6c1d8f4a327`) sin aplicar en Render: el
modelo consulta columnas que la base de producción aún no tenía. Se
resuelve con `python -m alembic upgrade head` en la Shell de Render.

## Vínculo de trámites encadenados, rediseñado (2026-09-02)

Feedback de Sd sobre la primera versión (la píldora gris centrada): "muy
chico, muy insignificante" y sin respetar la regla del chat de que cada
mensaje muestra el avatar de quien lo produjo. Ahora el vínculo es una
BURBUJA del hilo: la presenta quien inició el trámite (el trabajador/la
empresa, de su lado y con su avatar; en el chat del admin, del lado de la
contraparte), y adentro va LA MISMA tarjeta del formulario adjunto
(blanca, filo de acento, rótulo arriba, botón ámbar "Abrir el trámite") —
concordancia gráfica por reutilización, con el expediente en monoespaciada.
Al armarla salió un TDZ real en renderChatTramiteAdmin: `etiquetaOtro` se
declaraba dentro del map después de mi uso — se subió al inicio de la
función.

**Adenda del mismo día — el logo gigante en mobile de producción**: el
tamaño de `.logo-colmena` vivía solo en marca.css, que se sirve con
`Cache-Control: max-age=3600` y SIN sello `?v=` — el navegador del celular
usó la hoja cacheada vieja (sin la regla) y la imagen quedó a tamaño
natural. El tamaño base ahora va INLINE en la plantilla (que no se cachea);
la regla de marca.css queda como refinamiento (19px en mobile). Ojo a
futuro: cualquier feature cuyo CSS nuevo viva solo en marca.css tiene esta
ventana de 1 hora — o se inline-a lo crítico, o se agrega sello de versión
al link (pendiente de decidir como patrón general).

## Bandeja de notificaciones + globo propio de Trámites (2026-09-02)

Dos cambios funcionales pedidos por Sd:

**1. La bandeja** (`/app/notificaciones`, `templates/notificaciones.html`):
reemplaza al modal de la portada por una página completa estilo casilla de
correo — agrupadas por día (Hoy/Ayer/fecha, encabezados en condensada),
no leídas destacadas (filo de acento, remitente en negrita, hora en
acento) y leídas atenuadas, filtros Todas/No leídas/Leídas + buscador por
texto o remitente. Expandir una fila la marca leída (optimista + POST al
endpoint de siempre); adjuntos y el ícono de formulario asociado se
conservan. Los datos salen del mismo /api/mis-notificaciones. La tarjeta
de la portada ahora es un link a la página; el modal viejo queda sin uso.
La empresa sigue con su pestaña ("eventualmente" migra, dijo Sd).

**2. Las novedades de un trámite ya no generan Notificacion**: el aviso va
en un globo PROPIO de Trámites (tarjeta de portada, pestaña de /app y
pestaña de /empresa) + punto de novedad en la fila del listado.
Implementación: `Tramite.visto_trabajador_en` / `visto_empresa_en`
(migración `f2a7b9c4d156`, backfill = visto). Semántica DETERMINISTA:
**NULL = hay novedad** — un cambio del sindicato (estado o nota) lo pone
en NULL; abrir el detalle o escribir una nota propia lo sella. Se descartó
comparar `actualizado > visto`: `actualizado` tiene granularidad de
MINUTO y dos eventos del mismo minuto se confunden (lo detectaron los
tests). `_notificar_cambio_tramite(_empleador)` quedan como no-op
documentado: son el gancho donde un canal push futuro se reconecta.
Tests de trámites/empresa adaptados al criterio nuevo.

## Notificaciones push a la PWA (2026-09-02)

Canal Web Push para las novedades de trámites: "Novedad en tu trámite
XXX — Tu sindicato actualizó el estado / te escribió en el chat". El click
abre el detalle directo (deep link nuevo `?tramite=EXP` en /app).

- **`push.py`**: módulo del canal. Se configura con 3 variables de entorno
  (VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY/VAPID_CLAIM_EMAIL); SIN ellas es un
  no-op silencioso (mismo criterio que ANTHROPIC_API_KEY ausente). El envío
  corre EN UN HILO (pywebpush es HTTP sincrónico, ~100-300 ms por
  suscripción, no puede colgar el request del admin) y una suscripción
  muerta (404/410) se borra sola. `pywebpush==2.5.0` en requirements.
- **`SuscripcionPush`** (migración `a9d4e7f2c831`): cuil + endpoint único +
  claves; un CUIL puede tener varias (teléfono y compu). Rutas
  `/api/push/clave-publica|suscribir|desuscribir`.
- **El gancho es `_notificar_cambio_tramite`**: el mismo punto que antes
  creaba Notificacion y quedó como no-op documentado esta mañana — ahora
  dispara el push. Solo trabajador; el espejo de empresa sigue no-op.
- **El service worker YA EXISTÍA** (instalabilidad de la PWA, /sw.js con
  scope /app y registro en static/pwa.js): se le sumaron los handlers de
  push y notificationclick sin tocar su decisión de NO cachear nada.
- **Política de permiso (acordada con Sd)**: si está sin decidir, se pide
  UNA vez cada 30 días, y siempre atado al PRIMER TOQUE en la página (iOS
  y Chrome exigen gesto). Si el usuario lo bloqueó: silencio total (el
  navegador tampoco permite re-preguntar). Con permiso dado, cada visita
  re-sincroniza la suscripción (idempotente). iPhone: solo iOS 16.4+ y con
  la PWA instalada; Android: instalada o en el navegador.
- **Otra vez el cache de 1 hora**: `pwa.js` cacheado sin la función nueva
  tiró ReferenceError en la llamada inline. Doble fix: sello `?v=2` en el
  include Y llamada con guarda `if (window.initPushTramites)` — regla
  aprendida: toda función nueva de un .js estático que se llama inline
  desde un template se llama CON GUARDA.
- test_push.py (apagado sin claves, CRUD de suscripción por ruta,
  endpoint inalcanzable no tumba el hilo).

**Adenda del globo de Trámites (2026-09-02, noche)**: Sd reportó que el
globito no aparecía en el teléfono tras probar el push. La lógica estaba
bien (verificado local: render inicial con el globo puesto). Eran dos
efectos de ciclo de vida: (a) tocar la notificación push abre el detalle
por el deep link y eso CONSUME la novedad — comportamiento correcto; y
(b) la PWA que vuelve del background no recarga, y los globos eran solo
server-rendered. Fix de (b): al volver la página a primer plano
(visibilitychange/pageshow) los globos de la portada (trámites +
notificaciones) y el de la pestaña de /app se refrescan solos.

## Rediseño "Hilo" de Notificaciones y Trámites del trabajador (2026-09-03)

Pedido de Sd: seguir la línea visual de los logins y el dashboard en las
dos pantallas que faltaban. Se hicieron 3 mockups en
`disenos/notificaciones-tramites-propuestas.html` (Casilla del gremio /
Expediente / Hilo, con conmutador UOM–La Bancaria) y Sd eligió **Hilo**,
la más "app" y la que mejor conversa con el push recién encendido.

**Bandeja (`templates/notificaciones.html`, `/app/notificaciones`)**:
franja oscura de marca bajo el encabezado con el título en condensada,
"N sin leer de M" y el link "Marcar todas como leídas"; chips Todas / No
leídas / Con adjunto + lupa que despliega el buscador. La lista es una
línea de tiempo: riel vertical, los días como hitos hexagonales (guiño a
la colmena) y cada aviso como burbuja con avatar del remitente
(iniciales + color estable derivado del nombre, saltea "de"/"la"). Las no
leídas laten con un punto de acento sobre el avatar. Expandir sigue
marcando leída (optimista + POST de siempre); adjunto y formulario
asociado van como acciones dentro de la burbuja. El filtro "Leídas" se
reemplazó por "Con adjunto" (más útil para buscar el PDF de la paritaria
que para ver lo ya leído).

- **Nuevo `POST /api/notificaciones/leer-todas`** →
  `db.marcar_todas_notificaciones_leidas(cuil, sid)`: solo las copias de
  ESE cuil y solo notificaciones de ESE sindicato (pluriempleo: las del
  otro gremio no se tocan). Test en `test_notificaciones.py`.

**Inicio de Trámites (`#tram-inicio` en `templates/trabajador.html`)**:
primero la tarjeta oscura **"Necesita tu atención"** con el trámite con
novedad más reciente: tipo en condensada, expediente + estado, el último
mensaje del sindicato (o "Cambió el estado a X" si lo último no fue un
mensaje) y los botones Responder / Abrir el trámite. "Responder" abre el
detalle y, ya cargado, el compositor del chat
(`responderTramiteDesdeInicio`). Después dos accesos grandes (Iniciar un
trámite, con la cantidad real de formularios; Buscar expediente, que
despliega el buscador de siempre — **`#tram-buscar-input`/`#tram-buscar-btn`
conservan sus ids**, el robot E2E solo suma el click al
`#tram-buscar-toggle`), chips Todos / En curso / Terminados con
cantidades, y la lista con barra de progreso de 4 tramos por trámite
(iniciado → en tratamiento → respondido → terminado; "esperan tu
respuesta" es el tramo 2 en color de alerta) y un pie con lo último que
pasó ("Tu sindicato: …", "Hay novedades", "Esperan tu respuesta").

- **`/api/tramites/mios` ahora trae `ultimo_mensaje`** (autor, texto,
  creado, tiene_adjunto, formulario_id) o null: `tramites_de_trabajador`
  resuelve las últimas notas de TODA la lista en una sola consulta y se
  las pasa a `_tramite_resumen` (parámetro opcional, el espejo de empresa
  no cambia). Test extendido en `test_tramites.py`.
- Prefijo `th-` en todo el CSS nuevo del inicio, para no pisar el detalle,
  el formulario ni el chat, que siguen iguales.
- Colores de estado siguen siendo los fijos de `ESTADO_TAG_COLOR` (nunca
  la marca); la etiqueta larga "A la espera de información del afiliado"
  se muestra corta ("Esperan tu respuesta") solo en el inicio.

Verificado a mano con el lote UOM (Lucía Gómez, 32 notificaciones / 18
trámites): hilo completo, expandir → POST leer, contadores, Responder →
modal con textarea, buscador plegado, filtros, y el globo de la pestaña
se apaga al abrir el detalle. Tests: notificaciones 16/16, trámites
16/16, espejos de empresa sin cambios (12/12 y 10/10).

**Adenda del mismo día — Tu Recibo y Credencial, al mismo esquema, sin
tocar contenido.** Pedido de Sd para dejar la app uniforme. En Tu Recibo,
la zona punteada con emoji se convirtió en la misma tarjeta oscura del
inicio de Trámites (kicker "Tu recibo", el texto "Foto o PDF de tu último
recibo" en condensada y el botón ámbar "Elegir recibo", que sigue siendo
el `<label for="archivo">` de siempre); "Ver mis recibos verificados" es
un acceso grande de una columna; el historial usa las filas `th-r`
(período · sindicato, fecha en monoespaciada y las mismas etiquetas de
siempre, ahora en una línea propia debajo para que el título no se
aplaste cuando hay tres). En Credencial se sumó el título "Credencial"
(las otras pestañas ya lo tenían) y el encabezado de la tarjeta toma el
degradé base→primario, el grano, el filo ámbar y el nombre del sindicato
en condensada, con el kicker "Credencial digital"; datos, filigrana, firma
y QR quedan idénticos. Preview, resultado de la verificación y el detalle
en modal no cambian.

**Segunda adenda (v0.27.02) — Mis Aportes y Capacitación.** Encabezado
oscuro compartido `.th-head` (degradé base→primario, grano, filo ámbar,
kicker en acento y título en condensada) sobre la tarjeta del semáforo
("Semáforo / Estado de tus aportes") y sobre la guía ("Guía / Entendé tu
nuevo recibo de sueldo", con el mismo párrafo introductorio como
subtítulo). Los dos pasos del semáforo apagado ("1 · Consultar en ARCA ↗"
y "2 · Subir captura de ARCA") son ahora los dos accesos grandes en fila,
con los mismos textos, el mismo link a ARCA y el mismo `<label
for="arca-file">`. Los subtítulos de la guía toman el estilo de los hitos
del hilo (condensada, tracking, línea) y las 4 secciones siguen como filas
numeradas. Colores del semáforo (verde/amarillo/rojo/gris), barras por
mes, leyenda y fuente: sin cambios. Título de pestaña "Mis aportes" /
"Capacitación" sumado como en Credencial.

**Tercera adenda (v0.27.03) — Novedades, portada y perfil.** La pestaña
Novedades de /app es ahora el mismo hilo que la bandeja: riel, un hito
hexagonal por día (agrupado en Jinja por `fecha_hora[:5]`, que viene como
"DD/MM HH:MM") y una burbuja por noticia con la imagen 1 como avatar (o el
ícono de novedades si no tiene), título, hora en monoespaciada y bajada;
mismo `abrirNoticia(id)` de siempre. En la portada se respetan el vidrio
y la variante clara/oscura: los títulos de las tarjetas de acceso pasan a
condensada en mayúsculas, los encabezados de sección ("Novedades",
"Beneficios") toman el estilo de hito con línea, y la fecha de cada
noticia va en monoespaciada color acento. El modal de perfil toma el
encabezado del esquema (degradé, grano, filo ámbar, el nombre del
sindicato como kicker y "Tu perfil" en condensada), etiquetas de campo en
mayúsculas con tracking y el botón "Guardar cambios" en condensada; los
campos, la foto, el lightbox y `/api/perfil` no cambian. El mismo
`.modal-notif-enc` lo hereda el modal viejo de notificaciones (sin uso).

## Esquema "Hilo" en Admin y Plataforma — parte 1 y 2 (2026-09-03, tarde)

Pedido de Sd: llevar el mismo esquema a todo Admin y Plataforma, por partes.

**Parte 1 — portadas** (`admin_portada.html`, `plataforma_portada.html`):
títulos de las tarjetas de acceso en condensada mayúscula, y un kicker en
acento ("Panel de administración" / "Panel de plataforma") arriba del
saludo. Vidrio, variante clara/oscura y la estrella "NUEVO" del Panel
Sindical quedan iguales.

**Parte 2 — cromo común de `/admin` y `/plataforma`** (CSS agregado al
final del `<style>` de cada plantilla, sin tocar el marcado de las
secciones): encabezado con degradé base→primario, grano y filo ámbar
(en admin suma el kicker "Panel de administración" a la derecha); tira
de pestañas oscura con pestañas en condensada y la activa en acento;
títulos `h2` de sección como hitos (condensada + línea, sin el subrayado
de tinta); sub-pestañas en condensada tipo píldora; cabeceras de tabla en
tracking; **botón principal en acento con texto en condensada** (los
`.mini`, `.sec`, pestañas y el botón de ayuda quedan como estaban -- el
selector los excluye explícitamente). Versiones: Admin 0.26.02 → 0.27.01,
Plataforma 0.19.01 → 0.20.01.

**Parte 3 — secciones (Admin 0.27.02 / Plataforma 0.20.02).** Decisión
tomada al mirar las secciones con listas (Reportes, Trámites,
Notificaciones, Noticias, Beneficios, Empleadores, Sindicatos, Recibos
con alerta): **las tablas siguen siendo tablas**. El admin es una
herramienta de escritorio con datos densos y filtros por columna; pasar
esas filas a tarjetas del hilo (como en la app del trabajador) las haría
más largas y menos comparables. Lo que se unifica es el vocabulario, otra
vez solo con CSS: etiquetas de estado como píldoras (`.tag`, `.badge`,
`.chip-estado`), subtítulos de sección y de tarjeta como hitos (`.ct-secc`,
`.card h3`, `.rep-sub`), encabezado del modal de trámite/recibo con el
degradé + grano + filo ámbar y título en condensada, la caja de ayuda con
el mismo título, inputs de filtro como píldoras, y expediente/CUIL/cantidades
en monoespaciada. Los `<details>` de plataforma llevan el resumen en
condensada.

## Esquema "Hilo" en la app de Empresa + dos arreglos (2026-09-03, v0.27.04)

**Arreglo real encontrado de paso: `/app` y `/empresa` NO cargan
marca.css** (tienen su propio CSS), así que `var(--fuente-display)` era
inválida ahí y todos los títulos "en condensada" del esquema -- y los del
`.tram-box` de la Fase D anterior -- caían a system-ui sin que nada
fallara. Ahora las dos plantillas declaran el `@font-face` de Barlow
Condensed y las tres variables de fuente (`--fuente`, `--fuente-num`,
`--fuente-display`) al inicio de su `:root`. Lección: una variable CSS
inexistente no rompe nada visible, hay que verificar la fuente computada.

**Arreglo menor pedido por Sd**: en la portada del trabajador, una noticia
sin imagen quedaba desalineada respecto de las que sí tienen; ahora lleva
un ícono genérico (`.miniatura-ico`, mismo tamaño que la miniatura, fondo
primario).

**Empresa, solo esquema (decisión de Sd: la pestaña Notificaciones se
queda dentro de `/empresa`, sin bandeja propia por ahora)**:
- Portada: títulos de acceso en condensada, kicker "Panel de empleador",
  modal de perfil con el encabezado del esquema (kicker con el nombre del
  sindicato, título en condensada, etiquetas en mayúsculas, botón en
  condensada).
- Panel: encabezado con degradé + grano + filo ámbar; Notificaciones como
  hilo (hito por día, burbuja con avatar de iniciales; el toggle
  `toggleNotificacionEmpresa` no cambia porque conserva las clases
  `notif-item`/`no-leida`/`expandido`); inicio de Trámites espejo del
  trabajador con nombres propios (`tx-*`, `renderTramitesTrx`): "Necesita
  tu atención" (sin último mensaje, porque el resumen de empresa no lo
  trae -- muestra "tu sindicato actualizó este trámite"), accesos grandes,
  buscador plegado detrás de `#trx-buscar-toggle`, chips por estado y barra
  de progreso. El tinte de marca en las filas (`.tramx-item`) se conserva:
  un trámite de empresa se sigue distinguiendo a simple vista.

## Entornos separados, Etapa 0 (2026-09-03)

Plan completo en `PLAN_ENTORNOS.md` (seis preguntas cerradas con Sd:
servicio actual pasa a seguir la rama `demo`, se crea Pruebas sobre
`main`, traspaso de la operación a dos devs en cuatro semanas). Lo que
entró en el código en esta etapa:

- **`entorno.py` + `templates/_entorno.html`**: `ENTORNO` se lee una vez al
  importar y se inyecta como global de Jinja (`entorno`,
  `distintivo_entorno`), sin tocar cada `TemplateResponse`. El include va
  justo después del `<body>` de las 18 plantillas. El distintivo es una
  píldora ámbar fija abajo a la izquierda, `pointer-events:none` (no
  interfiere con la UI ni con los robots E2E), y muestra la versión de la
  app cuando la página la tiene en contexto. **Solo en `local` y
  `pruebas`**; en `demo`/`prod` nada, y sin la variable tampoco: el default
  silencioso es deliberado para que el deploy de esta feature al servicio
  actual no cambie lo que ven los sindicatos. Un valor desconocido se
  trata como vacío (un typo no puede pintar un distintivo raro en la
  demo). Fila "Entorno" en el "Acerca de" de admin, plataforma y portada
  del trabajador, solo si está definido.
- **`promover_demo.py`**: exige árbol limpio, trae `origin/main` y
  `origin/demo`, lista los commits que van a la demo, hace `pg_dump` de la
  base de demo (`DEMO_DATABASE_URL` del `.env`; `pg_dump` local o el del
  Docker de desarrollo), mergea, etiqueta `demo-AAAA-MM-DD-vX.Y.Z` con la
  versión de `version.py` del commit promovido, y pushea rama + tag.
  `--solo-pr` imprime el link del PR en vez de mergear (para cuando las
  reglas de rama exijan aprobación). Sin `DEMO_DATABASE_URL` aborta salvo
  `--sin-backup`: nadie promueve sin copia por accidente.
- **Seed de AEFIP apagado**: `db.init_db()` ya no llama a
  `cargar_seed_si_vacio()`. El hallazgo pendiente desde 2026-08 (sindicato
  fantasma id=1 en toda base creada desde cero) era exactamente el caso de
  la base nueva de Pruebas. La función queda para uso explícito.
- `DESPLIEGUE_RENDER.md` reescrito para dos servicios (Pre-Deploy Command,
  variables por entorno, promoción, rollback, regenerar Pruebas, backup
  manual). `backups/` en `.gitignore`.
- Versiones 0.28.01 / 0.28.01 / 0.21.01 (funcionalidad nueva → sube el
  minor y el patch vuelve a 01).

## Entornos separados: Pruebas y Demo (2026-09-03)

Etapas 0 y 1 de `PLAN_ENTORNOS.md`, completas el mismo día. El resultado
operativo está en `FLUJO.md`; acá va lo que se aprendió haciéndolo.

**Lo que se montó**: el servicio original pasó a seguir la rama `demo`
(conserva su URL, `mitrabajo.onrender.com`) y se creó `mitrabajo-pruebas`
siguiendo `main`, con su propio Postgres. Alembic corre en el Pre-Deploy de
los dos. Un push a `main` llega a Pruebas en ~90 s medidos y la demo no se
entera; se verificó comparando un archivo estático servido por cada uno
(200 en Pruebas, 404 en demo). El ciclo completo se estrenó tres veces.

**La marca de la plataforma vivía SOLO en la base de demo.** El logo y los
colores de Colm3na se cargan a mano desde `/plataforma` (patrón "Opción B",
bytes en la base) y ningún script los reponía: Pruebas nació con el
placeholder `static/logo_mitrabajo.svg` -- el maletín gris original del
proyecto, de agosto -- y a Producción le iba a pasar igual. Se bajó el arte
de la demo a `static/marca/` (versionado) y `cargar_marca_plataforma.py` lo
siembra. Los colores tampoco eran los defaults: `#0a1421 / #a0030b /
#7776a7`. Lección que excede al logo: **hay configuración que solo existe
como filas en una base**, y conviene barrer `ConfiguracionPlataforma` entera
con esa pregunta antes de armar Producción.

**pg_dump no puede volcar un servidor más nuevo que él.** Las bases de
Render son Postgres 18 y el contenedor de desarrollo es pg16: el dump aborta
con "server version mismatch" a mitad de la operación. Apareció al clonar
demo → Pruebas y `promover_demo.py` tenía exactamente el mismo bug, latente:
la primera promoción real se habría abortado sin mergear. Por eso la lógica
quedó en `pg_cliente.py`, compartida por los dos scripts, y usa la imagen
oficial `postgres:<version>` de Docker cuando el cliente local no alcanza
(Render sube de versión por su cuenta; exigir el cliente justo instalado en
cada PC no era sostenible).

**El clonado demo → Pruebas no se puede invertir.** `clonar_demo_a_pruebas.py`
existe para la carga inicial, no como rutina: lo normal es regenerar Pruebas
con los lotes, que no dependen de que otra base esté sana. Escribir un dump
sobre la demo sería el peor accidente posible del proyecto, así que hay tres
guardas que no se saltean con ningún flag (el destino tiene que decir
"pruebas" en su URL, el origen no, y las dos tienen que ser distintas) más
un `--si-borrar-pruebas` explícito. Probadas todas, incluido el caso de las
variables invertidas en el `.env`. Al clonar, se verificó que la extensión
`pgvector` sobrevive al `--clean` (si no, el RAG quedaría roto en silencio).

**La base de demo se cayó sola**: el plan free de Postgres en Render vence a
los 30 días. El síntoma fue `E-INTERNO-00` en todas las rutas con el
servicio web vivo (`/static/` respondía 200) y `SSL connection has been
closed unexpectedly` al conectar por fuera. No era autenticación ni DNS. Se
resolvió pasando la base a plan pago.

**El sello de `/static/` faltaba en `marca.css`, y eso rompió el modal de
noticias en producción.** Ver la sección propia más abajo.

## El modal de noticias que se rompió por caché (2026-09-03)

Noticias y Beneficios eran los dos últimos modales con la estética vieja
(`.modal-hoja`, la hoja oscura pegada al borde inferior, fotos en
miniaturas de 70px). Se pasaron al patrón claro con encabezado de marca que
ya tenían Notificaciones y Perfil. Verificado en local y en Pruebas, se
promovió a la demo... y en el teléfono se veía roto: encabezado sin fondo,
título blanco invisible, kicker "en el aire" y fotos gigantes.

**La causa no era el modal: era la caché.** `/static/` sale con
`Cache-Control: public, max-age=3600` y los 8 templates referenciaban
`marca.css` SIN sello `?v=`, contra lo que el propio CLAUDE.md decía que
había que hacer. Después del deploy, un navegador que ya había visitado la
app servía el **HTML nuevo con la hoja vieja**: las clases `.modal-articulo`
no existían todavía ahí, así que no había ni fondo ni tamaños. En desktop se
veía bien solo porque ahí el CSS no estaba cacheado. El arreglo es
`main._sello_static()`, un global de Jinja con mtime+tamaño del archivo --
sale del archivo y no de `version.py`, así cambia aunque alguien toque el
CSS sin subir la versión, y en desarrollo se refresca sin reiniciar.

**Un segundo defecto, propio del modal nuevo**: `.modal-articulo-enc` copió
el degradé de `.modal-notif-enc` pero NO su capa de `background` sólido. El
original tiene dos capas por una razón: si el `background-image` no se pinta
(`color-mix` sin soporte, o el repaint del sticky en algunos navegadores
mobile), sin color sólido el encabezado queda transparente. Regla: **el
color sólido va siempre además del degradé, nunca solo el degradé.**

**Sobre cómo se verifica**: las capturas del navegador emulado no
reprodujeron nada de esto, porque ahí el CSS nunca estuvo cacheado. Lo que
sí lo detectó fue medir el estilo computado (`backgroundColor` pasó de
`rgba(0, 0, 0, 0)` a `rgb(15, 27, 45)`, y la foto de 307px a 246px). Para un
bug de CSS, medir vale más que mirar.

Detalle menor: `trabajador.html` no carga `marca.css` (tiene su propio CSS),
así que las reglas del modal están duplicadas en los dos lados con un
comentario cruzado. Si se tocan en uno, hay que tocarlas en el otro o la
noticia se ve distinta según se abra desde la portada o desde Novedades.

## Credencial: QR efímero de 10 minutos y retrato bajo la filigrana (2026-09-05)

Dos cambios sobre la misma pantalla (`/app`, pestaña Credencial), pedidos
juntos: que la credencial no se pueda "prestar" con una captura de pantalla,
y que el retrato del afiliado esté en la tarjeta como marca de agua.

### El QR vence a los 10 minutos

Antes el QR encodeaba `/v/{token}` con el token permanente del trabajador.
Era estable: una foto del QR servía para siempre y desde cualquier teléfono,
así que alcanzaba con mandarla por mensaje para que otro se hiciera pasar por
el afiliado en un control. Ahora la URL lleva además `k`, un código firmado
con vencimiento (`qr.codigo_efimero` / `qr.verificar_codigo_efimero`).

Decisiones:

- **Firmado, no guardado.** El código es `{vencimiento}.{hmac(SESSION_SECRET,
  token.vencimiento)[:16]}`. El servidor lo revalida recalculando la firma:
  no hace falta tabla de códigos vivos ni limpieza de vencidos, y un reinicio
  de Render no invalida ninguna credencial. La firma cubre el vencimiento, así
  que correrlo a futuro no sirve (hay test).
- **Diez minutos** (`qr.TTL_QR_SEGUNDOS`). Alcanza para mostrar la credencial
  en una guardia o en la puerta de una obra; es poco para que la captura le
  sirva a otro.
- **Sin `k` tampoco verifica.** El link pelado `/v/{token}` ahora cae en el
  estado "código vencido". Si siguiera funcionando, copiar la URL del QR una
  sola vez daría un pase permanente — que es exactamente el agujero que se
  venía a cerrar. Esto CAMBIA el comportamiento de `/v/{token}`: los tests de
  `test_qr_credencial.py` que verificaban con el link pelado se actualizaron
  para emitir un código vigente.
- **El token permanente sigue siendo lo único que identifica.** `k` no aporta
  ningún dato: solo habilita o no la página. Los query params `n`/`c`/`num`
  siguen siendo respaldo legible sin conexión y el servidor los sigue
  ignorando (test de siempre).
- La página pública distingue ahora tres estados: válida, **código vencido**
  (con la explicación de por qué y qué hacer) y no encontrada.

En la app, `/api/credencial/qr` emite uno nuevo y el JS de `trabajador.html`
lo pide 20 segundos antes de cada vencimiento, más al volver a la pestaña.
Se renueva **solo con la credencial a la vista** (pestaña activa y documento
visible): desde otra pestaña de la app no hace falta un QR fresco, y cada
llamada renovaría además la sesión por inactividad, que se cuenta desde el
último uso real. Debajo del QR hay un contador ("Se renueva en 9:59") para que
el afiliado entienda que lo que ve es momentáneo. Sin conexión no se borra el
QR en pantalla: puede seguir siendo válido hasta su vencimiento.

### El retrato va debajo de la filigrana

La foto de perfil (la misma de `/perfil-foto/{cuil}`, no una nueva) se pinta
centrada en la tarjeta, en círculo, desaturada y al 30% de opacidad, con una
máscara radial que difumina el borde. **La filigrana pasa por encima**, que es
el punto: igual que el guilloche sobre el retrato de un billete, el entramado
queda impreso sobre la cara y un recorte de la foto no se puede reusar limpio.

El apilado son tres capas en `.cred` (`position:relative`): `.cred-retrato`
(z-index 0) → `.cred-fondo` con la filigrana (z-index 1) → contenido (z-index
2). La filigrana va con `mix-blend-mode:multiply` para que sus líneas oscurezcan
sobre la foto sin ensuciar el blanco del resto de la tarjeta.

Valores calibrados mirando la credencial renderizada, no a ojo en el código:
`saturate(.38)` — se pidió baja saturación, no blanco y negro, y con `.15` la
foto quedaba gris muerta — y opacidad `.30`, que deja el CUIL y el DNI
perfectamente legibles por encima. Si el afiliado no cargó foto, la tarjeta
queda como estaba (la filigrana sola).

## Asistente del Panel Sindical (2026-09-05)

Pedido de Sd: un bot dentro del Panel Sindical, limitado a los datos y
funciones del panel, que entienda lenguaje natural ("quiero las
notificaciones no leídas de la sucursal Rosario"), aplique los filtros para
que el tablero cambie y el explorador muestre los casos, y conteste
resumido. Las decisiones vigentes viven en la ficha rectora
`docs/ASISTENTE_PANEL.md` (contrato, prompt, privacidad, filtro por
afiliado, medición). Acá, lo que se aprendió construyéndolo, en 7 bloques
y un día, sobre la rama `feature/asistente-panel`.

- **No es RAG ni el bot del convenio del trabajador**: no lee documentos,
  no usa embeddings; solo la API de Anthropic (`claude-sonnet-5`, esfuerzo
  bajo). Por eso se llama "Asistente del Panel" y nunca "bot": en el
  dashboard "Consultas al bot" ya significa otra cosa.
- **La pieza clave ya existía**: el estado de filtros del panel vive en la
  query string con un vocabulario cerrado validado por
  `dashboard.parsear_filtros`. El modelo traduce la pregunta a ese estado
  con una herramienta estricta (`fijar_filtros`, siempre el estado
  completo, nunca un delta), el servidor valida con la MISMA función que
  usa el JS, calcula los agregados reales y el modelo redacta una o dos
  frases. Nunca ve filas ni genera SQL; al modelo llegan nombres de
  seccionales y empresas, la pregunta tal cual y totales.
- **Filtro por afiliado en el panel**: nació de este pedido ("las
  notificaciones del afiliado Galmarini"). Tres reglas que costaron
  decidir: de los recibos cuentan SOLO los que la persona envió al
  sindicato, también en los totales (si no, el KPI revela lo que la fila
  esconde); las consultas al bot del convenio quedan afuera (son anónimas
  a propósito, y el KPI da None, no 0); el padrón nunca viaja al modelo:
  el servidor resuelve el nombre o CUIL, y los homónimos se eligen en el
  cajón con un clic, sin volver al modelo.
- **Bugs y hallazgos reales, por orden de aparición**:
  1. `dashboard.js` se referenciaba con `?v={{ version }}` y no con
     `sello_static`: el navegador servía el JS viejo hasta una hora
     después de cada cambio. Es exactamente la regla de CLAUDE.md sobre
     `/static/`; se notó porque el buscador nuevo "no respondía".
  2. Con dos strings vacíos consecutivos en la herramienta (`tema` y
     `persona`), Sonnet 5 emitió basura de su propio formato de llamada
     (`</antml_parameter>\n<parameter name="persona">`) y el servidor
     salió a buscar a esa "persona" tres veces. Los textos opcionales
     pasaron a `null` y `asistente._texto_limpio()` descarta lo que huela
     a etiqueta de herramienta. Hay un test que reproduce el caso.
  3. El modelo se negaba a buscar por CUIL ("primero necesito identificar
     a esa persona") hasta que el prompt dijo, con todas las letras, que
     un CUIL va en `persona` igual que un nombre.
  4. `load_dotenv()` sin ruta busca el `.env` desde la carpeta del script
     que lo llama: un script de prueba fuera del repo no cargaba la clave
     y la API devolvía 401 "invalid x-api-key".
- **Medición** (`probar_asistente.py`, 25 frases): 25/25 tanto con
  esfuerzo bajo como sin thinking; mediana 6,8 s, máximo 8,8 s contra
  19,1 s sin thinking; US$ 0,0065 por pregunta. Queda esfuerzo bajo. Los
  25 segundos de la primera prueba de humo fueron un arranque en frío.
- **Pendiente al cerrar la rama**: correr la migración `b7c3d9e1f204`
  contra un Postgres real (Docker estaba apagado; se validó en modo
  offline), probar el dictado en Chrome con micrófono, y decidir si con el
  panel en "Hoy" el asistente amplía solo el período cuando la pregunta no
  lo menciona.

## Landing de entornos: /entornos (2026-09-07)

Pedido de Sd: con Pruebas y Demo idénticas a la vista es fácil entrar al
login equivocado en una presentación. Una página interna con los 8 accesos
(Trabajador, Sindicato, Empresa y Plataforma, en cada entorno), íconos
grandes, los dos entornos distinguidos de forma inconfundible y la versión
que corre en cada uno. URL: `mitrabajo-pruebas.onrender.com/entornos`.

- **Solo existe donde se muestra el distintivo** (`entorno.MUESTRA_DISTINTIVO`,
  local/pruebas): en la demo la ruta responde 404 aunque el código llegue
  promovido. Es una herramienta del equipo: no se enlaza desde ningún lado
  y lleva `noindex`. El chequeo se hace por request, no al importar, para
  poder simular la demo en el test.
- **Los colores son fijos y no se comparten con nada de la suite**: el ámbar
  de Pruebas es exactamente el del distintivo de `_entorno.html` (así el
  acceso y la pantalla que abre se reconocen iguales) y lleva rayas de obra
  en la franja superior; la demo va en verde agua, lisa, con escudo, porque
  es la que "no se rompe". Fondo, panal y grano son los de los logins
  ("colmena nocturna"). Cuatro íconos de línea distintos, uno por rol.
- **La versión sale de cada entorno, no de este servidor**: `/api/version`
  (nuevo, público, `Access-Control-Allow-Origin: *`, `no-store`) devuelve
  las tres versiones de `version.py` + `FECHA_VERSION` + entorno, y el JS
  de la landing se lo pide a los dos hosts (`entorno.URLS`). Las del propio
  servicio vienen prellenadas en el HTML. Hasta la próxima promoción la
  demo no publica el endpoint y esos chips dicen "sin dato": el HTML de
  otro origen no se puede leer desde el navegador y el "Acerca de" está
  detrás del login, por eso hizo falta el endpoint y no un scraping.
- **Empresa no tiene versión propia** en `version.py` (solo Trabajador,
  Admin y Plataforma) y la landing lo dice en lugar de inventarle un número.
- Test: `test_entornos.py`. Versión: Plataforma 0.21.02 → 0.22.01 (se tomó
  como funcionalidad nueva de la app de plataforma, por ser una herramienta
  transversal de administración; Sd puede reasignarlo).

## Recursos en la landing: /entornos#recursos (2026-09-07)

Pedido de Sd: los documentos del proyecto (planes en HTML exportados de
Claude, videos, capturas, enlaces) estaban repartidos entre el celular, la
nube y la PC, y eso no escala. La landing de entornos, que ya era el punto
de entrada del equipo, suma debajo un título **Recursos** con la
documentación catalogada: miniatura, título, descripción de una línea,
fecha y tipo, de la más nueva a la más vieja, y un formulario para subir
un archivo (o pegar un enlace) desde ahí mismo. Módulo `recursos.py`,
rutas `/recursos/*` en main.py, tabla `Recurso` en db.py, plantilla
`entornos.html`.

- **Dos orígenes, una lista.** Los documentos que tienen que viajar con el
  código van versionados en `recursos/` (archivo + miniatura JPG 640x400)
  y se declaran en `recursos.SEMILLA` con clave, título, descripción,
  fecha y ancla: no se siembran, no se pierden al regenerar o clonar la
  base y se cambian con un commit. Lo demás se sube desde la landing y va
  a la base como bytes (tabla `Recurso`, migración `9c4e2f7a1b3d`), igual
  que logos y adjuntos: en Render no hay disco persistente. El catálogo los
  mezcla ordenados por `fecha` (la del documento, no la de subida) y, a
  igual fecha, lo subido último primero. Los primeros dos son el **Plan
  Maestro Colm3na** (7 sep) y el **Plan de implementación en el
  sindicato** (4 sep, se abre en `#estrategia`): son los artifacts
  publicados desde Claude Code, guardados tal cual se exportan (el
  `window.claude` de la página compartida no existe acá y el propio
  documento cae solo a "guardado solo en este navegador"). Las miniaturas
  se hicieron con una captura de Playwright a 1280x800 reducida a 640x400.
- **Pase por dispositivo, no sesión.** Estos archivos son documentación
  interna (modelo económico, plan de cuentas) en un host público, así que
  abrir, subir y quitar exigen el pase que deja el PIN de la landing (ver
  "PIN de la landing", más abajo): cookie `pase_entornos` (`vence.firma`,
  HMAC con `SESSION_SECRET`, 30 días, `SameSite=Lax` para que un POST desde
  otro sitio no la mande). No entra en `COOKIES_POR_ROL`: no se renueva por
  actividad ni vence a los 15 minutos porque no abre ningún panel. Una
  sesión de plataforma vigente también sirve. Sin pase, un clic sobre un
  recurso vuelve a la landing, que muestra la puerta del PIN (redirección
  solo si es navegación de página, `_es_navegacion_de_pagina`; un fetch
  recibe 403). La primera versión pedía la clave de plataforma solo para
  los recursos y dejaba el resto de la landing abierta; el PIN la
  reemplazó el mismo día.
- **Miniatura en el navegador.** Al elegir un archivo, el JS de la landing
  prellena título (del nombre) y fecha (`lastModified`) y arma la
  miniatura en un canvas de 640x400 con recorte "cover": para imágenes,
  la imagen; para videos, el fotograma del segundo 1 (o el 10 % de la
  duración). Viaja como `miniatura` en el mismo POST multipart. Para PDF,
  HTML y el resto no hay cómo rasterizar en el navegador sin librerías y
  en Render no hay Chromium: quien sube puede adjuntar una captura, y si
  no, la tarjeta dibuja una portada sobre el fondo de marca con el ícono
  del tipo y el host del enlace o la extensión del archivo (el título ya
  va debajo; repetirlo era ruido). El alta va por fetch para mostrar el error al lado del
  botón sin perder lo escrito (el servidor devuelve JSON con `ir` cuando
  no es navegación de página, y redirige al `<form>` sin JS); la URL de
  vuelta lleva `&n={id}` para que dos altas seguidas no queden en la misma
  URL con solo el ancla distinta (eso no recarga).
- **Servir desde la base con `Range`.** `_bytes_con_rango` responde 206 a
  un rango simple, que es lo que manda el reproductor del navegador para
  adelantar un video o un audio; sin eso se reproduce pero no se puede
  saltar. Los archivos del repositorio van por `FileResponse`, que ya lo
  hace. Las páginas se sirven siempre `text/html; charset=utf-8`. Tope de
  subida `recursos.TAMANIO_MAX` (30 MB); miniatura hasta 2 MB y solo
  imagen.
- **La lista no carga los bytes** (`db.listar_recursos` selecciona
  columnas): un video de 13 MB no tiene que pasar por memoria para dibujar
  su tarjeta. `clonar_demo_a_pruebas.py` excluye la tabla `recurso` del
  dump para que la clonación no pise el catálogo de Pruebas (la demo no
  tiene nada ahí: la landing no existe en la demo, y sus rutas tampoco).
- **Estilo.** Misma colmena nocturna de la landing; la sección es neutra
  (blanco sobre el fondo de marca) a propósito, porque el ámbar y el verde
  agua identifican a los entornos y no se comparten. Íconos de línea por
  tipo (página, PDF, imagen, video, audio, enlace, archivo), chip de tipo
  sobre la miniatura, candado sobre las tarjetas cuando no hay pase.
- Tests: `test_recursos.py` (catálogo y orden, pase y sesión de
  plataforma, alta con miniatura y ancla, enlace, rangos, validaciones,
  404 en la demo). Versión: Plataforma 0.22.01 → 0.23.01.

## PIN de la landing: /entornos detrás de un código (2026-09-07)

Pedido de Sd: "una mínima seguridad a la landing", ocho dígitos alcanzan
por ahora. Sin el pase, `GET /entornos` devuelve `entornos_pin.html`: la
misma colmena nocturna reducida a un campo numérico, y nada de la landing
real viaja en ese HTML (ni los hosts de los entornos ni un solo `/recursos/`).
`POST /entornos/pin` compara solo los dígitos de lo tecleado
(`entorno.verificar_pin`, `compare_digest`) contra `entorno.PIN_LANDING`,
que sale de la variable `PIN_ENTORNOS` con default `09211999`, y deja la
cookie `pase_entornos` de 30 días (`recursos.crear_pase`); es el mismo pase
que exigen los recursos y sus miniaturas. Una sesión de plataforma vigente
entra sin PIN.

- **Cinco fallos seguidos desde una IP hacen esperar un minuto**
  (`_intentos_pin` en main.py, en memoria del proceso; la IP sale de
  `X-Forwarded-For`, que es lo que pone Render). No es un cerrojo serio (se
  reinicia con cada deploy y hay un solo proceso), pero vuelve inútil el
  tanteo a mano y le da sentido a un PIN corto. Aviso `espera` en la puerta.
- **Cambiar el PIN no corta los pases ya emitidos**: van firmados con
  `SESSION_SECRET`, no con el PIN. Para invalidarlos, cambiar ese secreto
  (que además desloguea a todos, como siempre).
- `/api/version` sigue público: la landing de Pruebas se lo pide a la demo
  desde el navegador y no cuenta nada que el "Acerca de" no muestre.
- Tests: `test_entornos.py` (puerta, PIN con guiones, espera tras cinco
  fallos, 404 en la demo) y `test_recursos.py` (todo exige el pase, incluida
  la miniatura). Versión: Plataforma 0.23.01 → 0.23.02.

## PIN de la landing (2026-09-07)

Pedido de Sd: una seguridad mínima para `/entornos`. Sin pase, la ruta
devuelve solo la puerta (`entornos_pin.html`): un campo numérico en la
misma colmena nocturna, sin un solo host ni `/recursos/` en el HTML.
`POST /entornos/pin` compara los dígitos contra `entorno.PIN_LANDING`
(variable `PIN_ENTORNOS`, default `09211999`) en tiempo constante y deja
el mismo pase de 30 días que ya usaban los recursos (cookie
`pase_entornos`). El PIN reemplazó a la clave de plataforma que pedía solo
la sección Recursos: una única puerta para toda la página, miniaturas
incluidas. Cinco fallos seguidos desde una IP (`X-Forwarded-For` en
Render) hacen esperar un minuto, en memoria del proceso: no es un cerrojo
serio, pero vuelve inútil el tanteo a mano. Cambiar el PIN no invalida los
pases ya emitidos; para cortarlos hay que cambiar `SESSION_SECRET`. Una
sesión de plataforma vigente entra sin PIN. Tests en `test_entornos.py` y
`test_recursos.py`. Versión: Plataforma 0.23.01 → 0.23.02.

## Documentación técnica generada del código (2026-09-07)

Pedido de Sd: el artifact «Mi Trabajo — Documentación técnica» del 14 de
agosto (v0.03) servía pero estaba viejo, y quería los gráficos con la
estética actual. Se reemplazó por una página generada desde el código,
para que no vuelva a quedar desactualizada por escribirla a mano.

- **Tres scripts en `docs/generador/`.** `extraer.py` lee con `ast` los
  modelos de `db.py` (tablas, columnas, FK, índices, JSON, bytes, vector),
  las revisiones de `migrations/versions/` (id, padre, fecha, título,
  tablas creadas) y las rutas de `main.py` (método, path, docstring), y deja
  `datos.json`. `diagramas.py` dibuja los SVG inline (vista general, flujo
  del recibo, multi-sindicato, RAG, Asistente, entornos, DER por áreas,
  tira de migraciones, roles). `generar.py` arma
  `recursos/documentacion-tecnica.html` con `contenido.py` (las
  descripciones que no salen solas del código: qué es cada tabla, qué hace
  cada ruta y con qué rol, módulos, scripts, plantillas) y `estilos.css`.
  Regenerar: `python docs/generador/extraer.py && python
  docs/generador/generar.py`; después actualizar `FECHA_DOC` y `COMMIT` en
  `generar.py`, y la miniatura si cambió la portada.
- **Misma familia visual que los planes** (Plan Maestro, Implementación):
  encabezado oscuro con panal, pestañas pegadas, panel lateral con índice,
  Barlow Condensed y Barlow, claro y oscuro. Los diagramas son SVG a mano
  con `currentColor` y tres acentos con significado: miel para lo que
  cruza a la IA, agua para la frontera del tenant, verde para persistencia.
  El DER agrupa las 41 tablas por área del código y resume las 25 FK a
  `sindicato` en un hexágono en vez de dibujar 25 líneas convergentes; las
  relaciones por valor (CUIL, CUIT, `formula.target`) van punteadas.
- **Cuatro pestañas**: Funcionalidades (los cuatro roles con sus pestañas,
  módulos, transversal, qué cambió desde agosto), Arquitectura (stack,
  vista general, flujo del recibo, auth, multi-sindicato, los tres modelos
  de IA, RAG, Asistente, entornos, decisiones vigentes), Componentes
  (módulos, scripts, las 172 rutas agrupadas y plegables, plantillas,
  estáticos, tests, docs) y Modelo de datos (DER, relaciones por valor,
  las 41 tablas columna por columna, las 49 migraciones con tira de tiempo,
  la capa de datos).
- Publicada sobre el mismo artifact de agosto (misma URL) y catalogada en
  Recursos como `documentacion-tecnica` con miniatura de la portada.
- **Lo que el relevamiento encontró desactualizado** y queda para
  corregir aparte: `README.md` describe la PoC sin base de datos; los
  docstrings de `db.py`, `main.py` y `auth.py` hablan de SQLite, de tres
  roles y de sesiones en memoria; CLAUDE.md dice «12 secciones» en `/admin`
  (son 15) y nombra un solo modelo de IA (son tres); `pytest` no está en
  ningún requirements; la tarjeta Capacitación de la portada dice
  «Próximamente» con la pestaña ya llena.

## Enlaces directos a un recurso, con solo el PIN (2026-09-07)

Sd quería abrir la documentación desde la landing con el PIN y nada más
(los enlaces a claude.ai piden sesión de Claude). Los recursos ya se servían
así, pero un enlace directo a `/recursos/<ref>/archivo` sin pase caía en la
puerta del PIN y, después del PIN, en la landing: había que volver a buscar
el documento. Ahora la puerta se acuerda del destino.

- `_exigir_pase` redirige a `/entornos?siguiente=<path>` cuando la
  navegación es un GET; un POST sin pase (subir, quitar) sigue yendo a la
  landing a secas porque no se puede reanudar. La puerta lleva el destino
  en un campo oculto, lo conserva si el PIN falla y `POST /entornos/pin`
  redirige ahí con el pase puesto.
- `_siguiente_seguro`: solo paths que empiecen con `/recursos/` (sin
  esquema, host ni `//`), para que la puerta no sirva de redirección
  abierta hacia otro sitio. Cualquier otro destino equivale a "sin destino".
- El `#fragmento` (p. ej. `#estrategia`) no viaja al servidor, así que se
  pierde en la vuelta si se entra por enlace directo sin pase; con pase el
  enlace abre directo y el fragmento sí funciona.
- Plataforma 0.23.03.

## Documentación puesta al día (2026-09-07)

Al generar la documentación técnica desde el código quedó a la vista lo que
la documentación escrita a mano ya no contaba. Sd pidió corregirla. Qué se
hizo, archivo por archivo:

- **`README.md`**, reescrito entero. Describía la prueba de concepto de
  agosto (sin base de datos, `data/reportes.json`, un túnel de Cloudflare
  para la demo, checklist del día de la demo). Ahora cuenta la plataforma
  actual: los cuatro roles, el stack, cómo correrla en la PC con el
  Postgres de Docker, cómo correr los tests (un archivo por proceso), los
  tres entornos y el mapa del repo y de la documentación. Sin los accesos
  de la demo (siguen en CLAUDE.md, un solo lugar).
- **Docstrings de `db.py`, `main.py` y `auth.py`**. Decían "SQLite", "tres
  roles" y "sesiones en memoria para la PoC". Ahora: motor dual con Alembic,
  las áreas de tablas, la convención de bytes en la base; los grupos de
  rutas por actor con puntero a la documentación generada para el listado
  completo; los cuatro roles con su cookie, PBKDF2 y sesiones firmadas sin
  estado en el servidor, vencimiento por inactividad.
- **`CLAUDE.md`**: el panel de `/admin` tiene 15 entradas, no 12 (se
  listan); la IA son tres modelos con un uso cada uno, no uno; el Asistente
  figura mergeado (decía "pendiente de mergear" y "mergeado" en el mismo
  punto); "Estado actual" al 2026-09-07 con el punto 20 (landing con PIN,
  Recursos y documentación generada).
- **`requirements-dev.txt`**: `pytest==9.1.1`. No estaba en ningún
  requirements aunque toda la suite lo usa (y los `test_*.py` lo importan
  en su `__main__`).
- **Tarjeta Capacitación de la portada del trabajador**: decía
  «Próximamente» desde antes del SPRINT_REFORMA, con la pestaña ya llena
  con la guía del recibo nuevo. Ahora dice «Entendé tu nuevo recibo», como
  las demás tarjetas describen lo que hay adentro. Trabajador 0.29.02.
- **`ESTADO_DEL_PROYECTO.md`**: se conserva como documento histórico con
  un aviso arriba que lo declara congelado (agosto de 2026) y manda a
  CLAUDE.md "Estado actual", HISTORIAL.md y la documentación generada. No
  se reescribió: la fuente de verdad del estado es CLAUDE.md.
- **`docs/generador/generar.py`**: la fecha de la edición y el commit se
  toman solos (hoy y `git rev-parse --short HEAD`) en vez de editarse a
  mano, que era exactamente el mecanismo por el que la doc anterior quedó
  vieja. La miniatura se rehizo con la portada nueva.

Queda como estaba, a propósito: `SPRINT_REFORMA.md` (plan tal cual se
escribió; CLAUDE.md dice qué se hizo) y los planes (`PLAN_*.md`), que
documentan decisiones y no estado.

## Anexo Servicios Mensuales (2026-09-07)

Pedido de Sd: rehacer la evaluación de costos mensuales (Render, Postgres,
S3, API de Claude con 10.000 recibos, GitHub Team, Claude Team) contra los
precios vigentes de cada proveedor, recordar lo que faltaba y dejarlo como
anexo en el formato HTML de los planes. Las decisiones se tomaron de a una
(alcance, instancias, Postgres, S3, volumen de IA, asientos, faltantes,
moneda, formato, titularidad) y quedan en la pestaña "Supuestos".

- `recursos/anexo-servicios-mensuales.html` (+ miniatura), catalogado en
  `recursos.SEMILLA`. Cuatro pestañas: Resumen, Detalle por rubro, IA por
  uso, Supuestos y fuentes. Dos escenarios: arranque USD 1.031 (2 web
  Standard + worker Pro para el RAG, Postgres Pro con alta disponibilidad,
  Pruebas y Demo, 4 asientos) y tope USD 1.125 (5 instancias, correo Pro,
  Codespaces). La IA va a tope de contrato (10.000 recibos × USD 0,028).
- Lo que faltaba en la lista original: Pruebas y Demo, el tamaño de
  instancia que exige la indexación del convenio (~1 GB, Standard mínimo),
  S3 solo como backup (la app no lo usa), dominio, correo transaccional,
  monitoreo, la consola de la API aparte de los asientos de Claude Team,
  impuestos sobre servicios del exterior.
- Hallazgos de precios: Render pasó a tarifa plana por workspace (USD 25)
  en abril de 2026, ya no USD 19 por usuario como decía PLAN_ENTORNOS; el
  Pro-4gb de Postgres figura a USD 55 en una fuente y 97 en otra (se
  confirma al contratar); GitHub muestra "USD 4 los primeros 12 meses".
- El Anexo Interno de la landing (subido a la base) se reemplazó por una
  copia con un panel "Resumen" que enlaza a este anexo, un renglón GitHub
  Team en su tabla de costos y los valores precargados (total 1.031, sigue
  editable y guardado en el navegador).
- Este documento se armó con `scratchpad/anexo/armar.py` (fuera del repo):
  los montos se calculan de una lista de rubros, no a mano. Para rehacerlo
  con precios nuevos conviene volver a partir de esa lista.

## Áreas, permisos granulares y ruteo de trámites — Áreas V2 (2026-09-11)

Rama `areas-permisos-v2`. Plan previo en `SPRINT_AREAS_V2.md` (decisiones
N1–N11, escritas antes de tocar código y no actualizadas retroactivamente).
Siete fases, seis migraciones, 149 tests nuevos en 10 archivos.

### Por qué se portó en vez de mergear

La primera tanda (`areas-permisos`, agosto) estaba terminada y probada pero
había quedado **126 commits detrás de `main`**: 0.14.20 del 22-ago contra
0.29.x del 07-sep, con RAG del convenio, Asistente, Panel Sindical, PWA,
validaciones de trámites y la landing de entornos en el medio.

No se estimó, se midió: el merge daba **8 archivos en conflicto** (`db.py`
14 hunks, `main.py` 12, `templates/admin.html` 10) y dejaba **28 rutas
`/admin/*` sin clasificar** que el fail-closed de la Fase 2 habría
rechazado con un error inexplicable — todo `/admin/dashboard*`,
`/admin/convenio*`, `/admin/tramite-tipo/probar`. El BACKLOG anotaba "5
líneas de `PERMISOS_RUTAS` para RAG"; eran 28 rutas y tres secciones nuevas
del catálogo. Como además los requerimientos nuevos cambiaban el modelo de
`Area` (pasa a colgar de una seccional) y el ruteo de trámites, la Fase 0
es la primera tanda **reescrita sobre el código de hoy**, y recién después
entran las decisiones nuevas.

### La premisa que ordenó todo el sprint

"Los administradores de hoy conservan exactamente los accesos de hoy". No
es una nota al pie: es lo que decidió que `es_super_admin` naciera en
`True` para todos los `UsuarioSindicato` existentes (migración
`c1a7d40be913`), que la sección "Áreas y Usuarios" quedara **fuera** de
`SECCIONES` para que nadie pueda asignarla, y que `es_admin_seccional`
arranque en `False` — un sindicato centralizado ni se entera de que el rol
existe. Un sindicato que no configura nada no nota el cambio.

### Los dos ejes, y por qué el área cuelga de la seccional

El **área** dice QUÉ hace un usuario; la **seccional**, SOBRE QUIÉNES. En
la primera tanda `Area` colgaba del sindicato y los dos ejes eran
independientes; en V2 el área vive DENTRO de una seccional (`N2`), que es
lo que permite que cada delegación arme su estructura sin pisarle el nombre
a otra: puede haber una "Legales" por seccional y son áreas distintas. De
ahí sale la regla de coherencia que fuerzan las rutas: **un usuario y su
área tienen que ser de la misma seccional**. Si no, "Legales de Rosario"
con alcance Córdoba sería un usuario del que nadie sabe qué ve.

El alcance es un solo concepto (`db.alcance_seccional`) con tres valores:
`None` = todas, `{id}` = esa sola, `set()` = ninguna (defensivo, para el
usuario sin seccional). Se aplica **dentro de la consulta**, no filtrando
después: `areas_del_sindicato(sid, alcance)`,
`usuarios_del_sindicato(sid, alcance)`, `_recortar_tramites`. Filtrar
después es la forma de que un camino nuevo se olvide.

### `modulos.py` no es `permisos.py`

La distinción es la decisión central y se repite en el código porque cuesta
retenerla: `modulos.py` dice qué **contrató** el sindicato (lo decide
plataforma), `permisos.py` qué puede **tocar** cada usuario dentro de eso
(lo decide el Super Admin). Un módulo abre varias secciones — "recibos"
abre seis — así que el permiso se guarda por sección: si la unidad fuera el
módulo, no habría forma de decir "mirá los reportes pero no toques las
fórmulas", que es el caso que motivó todo esto.

El efectivo es `((área + agregados) - bloqueados) ∩ secciones_de_modulos`.
El bloqueo le gana al área **y** a un agregado individual: es el único
orden en que "bloqueado" significa algo. La intersección final con los
módulos es la red de seguridad — si plataforma apaga un módulo, los
permisos viejos dejan de valer solos, sin salir a limpiar filas.

En la UI eso se pintó como una tabla de **tres estados** con dos columnas
de checkbox (hereda / agregado / bloqueado) en vez de un checkbox simple:
con uno solo no se puede distinguir "no lo tiene porque el área no se lo
da" de "no lo tiene porque se lo bloquearon a él".

### Gateo fail-closed de las 73 rutas

`main.PERMISOS_RUTAS` mapea cada ruta `/admin/*` a su sección, y se resuelve
**dentro de `exigir_sindicato()`** usando `request.scope["route"].path` —
no en cada handler, que es donde se olvidan. Una ruta que nadie clasificó
**se rechaza**: el olvido se nota en la primera prueba en vez de filtrarse
en silencio. Las únicas exentas están en `RUTAS_ADMIN_SIN_PERMISO` (login,
salir, portada, panel, dashboard); las 22 rutas del dashboard entran por
`_exigir_dashboard`.

Medido después de la Fase 0b, para confirmar que el recorte era real y no
solo visual: el panel pesa **229,7 KB** para un Super Admin y **146,6 KB**
para un usuario de área, y de los 14 paneles solo 2 le llegan al usuario de
área. El dato importa porque el `{% if %}` en la plantilla no es cosmético
— lo que no se renderiza no viaja.

### Identidad: el operador del panel y el afiliado son la misma persona

`UsuarioSindicato` gana `cuil` (QUIÉN ES) separado de `usuario` (con lo que
INICIA SESIÓN). Si se guardara uno solo, habilitar mañana el login por mail
borraría la identidad de la persona.

`sincronizar_empleado(usuario_id)` hace tres cosas de una porque separarlas
es lo que las desincroniza: vincula por CUIL contra el padrón, prende
`Trabajador.es_empleado_sindicato`, y apaga la marca de la fila anterior
**solo si ningún otro usuario activo sigue apuntando ahí** — sin ese
chequeo, dar de baja a uno de dos empleados con el mismo CUIL (dos altas,
un typo) apagaba la marca del que sigue trabajando.
`sincronizar_por_cuil(sid, cuil)` es el camino inverso, porque las dos
altas pueden venir en cualquier orden.

Trabajar en el gremio **sin estar afiliado a él** es un caso real: el
vínculo queda en NULL y no es un error. La demo lo muestra a propósito
(Elena Vidal, Prensa, no está en el padrón).

### Ruteo de trámites y pase entre áreas

El formulario declara a qué área cae el trámite: mapa explícito
seccional→área (`DestinoTipoTramite`, decisión N6) y, para las seccionales
que nadie mapeó, un `area_destino_default_id` **obligatorio**. El default
es lo que evita que el mantenimiento del mapa se vuelva obligatorio: una
seccional nueva funciona igual. Sin él, dejaría trámites sin dueño y el
error sería silencioso — nadie los vería en ninguna bandeja.

Esto reemplazó a la decisión 2 del viejo sprint "Admin de Seccional"
(adhesión obligatoria a un área troncal vía `Area.area_madre_id`):
resuelve el mismo problema sin una vertical implícita que hay que
mantener.

El **pase** solo existe si el formulario lo declara (`permite_pase`) y solo
hacia la lista **cerrada** de `PaseTipoTramite`: el circuito queda diseñado
de antemano y es auditable. Si el formulario no lo declara, el área que
recibe el trámite solo puede contestarle al trabajador. El área que derivó
conserva **lectura** (`areas_que_vieron`) pero no escritura — por eso
`puede_ver_tramite` y `puede_responder_tramite` están partidos. Todos los
chequeos viven dentro de `pasar_tramite()` y no en la ruta, a propósito: es
una operación que cambia quién puede responder, y dejar la mitad de las
condiciones en el llamador es la forma de que un camino nuevo se olvide de
alguna. El movimiento va al chat nombrando **áreas, nunca personas**, misma
regla que las respuestas.

### Responder y cambiar el estado, un solo acto

Pedido textual del usuario: "en el chat del trabajador un solo acto está
reflejado dos veces". Se **borró** la ruta `/admin/tramite/{id}/estado` y el
estado pasó a ser un parámetro de la nota:
`agregar_nota_tramite(..., estado_nuevo="")` deja UN evento en el log, con
el cambio de estado adosado al detalle. Borrar la ruta (en vez de dejarla
"por compatibilidad") es lo que garantiza que no vuelva a haber dos
caminos.

### Bugs encontrados, y su causa real

- **`loop.parent` no existe en Jinja2** (es de Django). La plantilla
  *compilaba* y explotaba recién al renderizar: 11 archivos de test en rojo
  de golpe. Se arregló con `{% set gidx = loop.index %}`. La lección quedó
  en el commit: **compilar una plantilla no es probarla**.
- **`bool(activo)` sobre un checkbox**: `activo="no"` es truthy, así que
  desactivar un área la activaba. Se normaliza con
  `(activo or "").strip().lower() in ("1","true","on","si","sí")`.
- **Las guardas de JS había que EXTENDERLAS, no agregarlas.** Los bloques
  de Aprendizaje, Convenio y el polling de empresas ya estaban guardados
  por módulo; ahora el panel puede faltar además **por permiso**. Los
  cuatro chequean las dos cosas.
- **`.subtab-au` con colores inventados**: texto blanco sobre blanco, la
  sub-pestaña "Usuarios" se veía vacía. El mismo error que había cometido
  el sprint de agosto con los checkboxes. Se arregló copiando el patrón de
  tokens que el proyecto ya tiene.
- **El pase no llegaba al chat.** El log lo tenía, `tramite_detalle` lo
  devolvía, pero el filtro del lado del cliente solo dejaba pasar
  `'creado'` y `'cambio_estado'`. El requerimiento del usuario ("todas las
  derivaciones van al chat") quedaba incumplido y **ningún test de base lo
  podía atrapar**: el bug vivía en el renderizado. Se arregló en las tres
  plantillas (`admin.html`, `trabajador.html`, `empresa.html`) y se sumó un
  test **de plantilla**, que es la categoría que faltaba.
- **El 403 por permiso mostraba JSON crudo.** El primer arreglo redirigía
  todo 403 al panel, lo que rompía las respuestas de API. Se acotó con un
  marcador (`e.codigo = "sinpermiso"`) y, sobre todo, se reescribió el test
  alrededor del discriminador real: **navegación de página vs fetch**. El
  test original fallaba porque su sindicato de fixture no tiene módulos, así
  que su 403 también venía del gate de permisos.
- **El hilo se leía al revés dentro del mismo minuto.** Apareció recién al
  armar la demo: el sindicato contesta y deriva seguido — el caso normal —
  y las dos cosas caen en el mismo minuto, que es la granularidad con la
  que el chat guarda las fechas. Con solo la fecha, el empate lo rompía el
  orden en que el cliente concatena las listas, así que **el pase salía
  siempre después de todas las respuestas**. Es anterior al sprint (ya
  pasaba entre "creado" y las notas), pero el pase lo volvió visible. Arreglo
  sin tocar el formato de las fechas ni agregar columnas: la tabla de log
  ya es una secuencia global — toda nota escribe su fila — así que
  `db._orden_de_notas` devuelve, para cada nota, el id de su fila de log, y
  el `.sort` del cliente desempata por ahí. Vale igual para el mirror de
  empleadores. Con test de base (un pase entre dos respuestas del mismo
  minuto) y de plantilla (que el `.sort` no vuelva a mirar solo la fecha).
- **Un test propio indexaba usuarios por CUIL** en un dict, justo después de
  otro test que crea dos usuarios con el mismo CUIL a propósito. Reindexado
  por id.

### Mutation testing: el agujero estaba en mis tests

Se corrió mutación sobre las guardas de cada fase. En la Fase 3 encontró
algo real: los tests de ruteo comparaban a Ana (Rosario) contra Beto
(Córdoba), así que **el filtro de seccional solo ya los separaba** —
quitar el filtro de área seguía pasando. Se agregó
`test_dos_areas_de_la_MISMA_seccional_no_se_ven_entre_si`, que es el caso
que de verdad prueba el eje del área.

### Migraciones

Seis, todas verificadas en Postgres real con datos y con el ciclo completo
downgrade/upgrade: `c1a7d40be913` (áreas y permisos, portada, con el fix
del `UPDATE` de `ve_todas` que la versión de agosto tenía mal en el
downgrade), `d4f18a2c7b30` (áreas por seccional + admin local),
`e7b2c9d41f85` (identidad del empleado), `f8a3d05e2c17` (ruteo por área),
`a2e6f1b83d40` (pase entre áreas), `b5c8e30a91f6` (estado dentro del
mensaje). Disciplina de siempre: nullable → backfill → NOT NULL.

### `cargar_demo.py`: la estructura completa, y un bug viejo que salió a la luz

La demo pasó a cargar seccionales, áreas con **perfiles distintos** (si
todas heredan lo mismo, la pantalla de permisos parece decorativa), un
Admin de Seccional en una delegación (uno de Sede Central sería
indistinguible del Super Admin), usuarios de área, la marca de empleado de
sindicato y formularios ruteados —con y sin pase, para que se vea el
contraste en el chat. Los dos sindicatos quedaron deliberadamente
distintos: la UOM federada (3 seccionales, 7 áreas, pase entre áreas) y la
Gastronómica centralizada (1 seccional, 1 área, sin Admin de Seccional),
porque sin el contraste no se ve que el rol es opt-in.

Al correrlo contra el Postgres de desarrollo apareció un bug que estaba
desde antes y que este sprint destapó: la limpieza de sindicatos previos
**enumeraba las tablas a mano** y se quedaba corta cada vez que el esquema
crecía. Se podía correr dos veces solo si nadie había *usado* la demo; con
un trámite presentado, Postgres rechazaba el DELETE por FK y el script
moría a mitad de camino, dejando la demo cargada a medias — justo lo que el
resto del archivo se cuida de evitar. Ahora el orden **no se escribe, se
deduce**: `SQLModel.metadata.sorted_tables` viene ordenado por dependencia,
así que una pasada hacia adelante marca todo lo que cuelga del sindicato
(cuando llega el turno de una tabla, sus padres ya están marcados) y la
pasada inversa lo borra de hijo a padre. Una tabla nueva con su FK entra
sola. Verificado corriendo el script tres veces seguidas contra Postgres.


## La hora de Buenos Aires en toda la app (2026-09-11)

El servidor de Render corre en UTC. Apareció medido ese mismo día probando
los planes de Render de punta a punta: **la regla decía 22:02 y la bitácora
01:02**. Se arregló ahí nomás para esas dos tablas (`PlanProgramado` y
`CambioPlan`) con un helper local, `db._ahora_ba()`, y quedó anotado que el
resto de la app seguía igual.

El resto de la app era 54 llamadas a `datetime.now()` y `date.today()`
repartidas en `db.py` (39), `main.py` (8), `dashboard.py` (4),
`asistente.py`, `recursos.py` y `validaciones_tramite.py`. Como toda la app
compara fechas **como texto** ("AAAA-MM-DD"), esas tres horas se traducían
en bugs silenciosos de vigencia:

- una `Noticia` vigente "hasta el 30" dejaba de mostrarse a las 21:00 del
  30, no a medianoche; lo mismo `Beneficio` y cualquier `fecha_hasta`;
- una notificación enviada a las 22:30 quedaba guardada con la fecha del día
  siguiente, y lo mismo los sellos de trámites y el `procesado_en` de
  recibos que alimenta las series del dashboard.

Se notaba poco porque solo ocurre entre las 21:00 y la medianoche.

**El fix.** Un módulo nuevo, `fechas.py`, con `ahora()`, `hoy()`,
`hoy_texto()`, `ahora_texto()` y `ahora_con_segundos()`, y el reemplazo
mecánico de las 54 llamadas. `db._ahora_ba()` se borró: sus dos usos apuntan
ahora a `fechas.ahora_con_segundos()`, y el porqué de aquella primera
corrección quedó como comentario donde estaba la función.

**`ahora()` devuelve un datetime SIN zona (naive) con la hora de Buenos
Aires**, decisión explícita. Un datetime con `tzinfo` arrastraría el offset
a `isoformat()` ("...-03:00") y rompería el formato de los valores ya
escritos en la base con ese método (`Recurso.creado`), además de reventar
cualquier comparación contra un datetime naive parseado de la base. La zona
acá es un dato de entrada para saber qué hora es, no algo que viaje con el
valor.

**Los datos viejos no se migraron.** Todo lo escrito antes del fix está en
UTC y ahí queda: reescribir a mano columnas de texto con formatos distintos,
en tablas donde algunas filas (las de planes de Render) ya estaban
corregidas, es bastante más riesgoso que convivir con un salto de tres horas
en los registros anteriores a esta fecha. En la práctica solo se nota
mirando sellos viejos de hora.

**El test que importa** no es ninguno de los que comprueban el helper, sino
`test_fechas.test_ningun_modulo_de_la_app_le_pide_la_hora_al_servidor`:
recorre los `.py` de la raíz —excluyendo la suite, los scripts que corren en
la PC del desarrollador y el propio `fechas.py`— y falla nombrando archivo y
línea del que vuelva a usar la hora del servidor. Es **fail-closed**, igual
que `PERMISOS_RUTAS`: un módulo nuevo entra a la lista solo, sin que nadie
se acuerde de agregarlo. Mira el árbol de sintaxis y no el texto, así un
comentario que nombre `datetime.now()` no lo hace fallar, y no toca
`datetime.now(ZONA)` ni `datetime.now(timezone.utc)`, que son usos
legítimos y explícitos (`planificador.py`, `render_admin.py`).


## Afuera SQLite: la suite pasa a Postgres (2026-09-11)

Hasta este día el proyecto tenía dos motores: Postgres en Render y en el
desarrollo local con Docker, y SQLite como fallback -- sin `DATABASE_URL`,
`db.py` caía a un archivo en `DB_PATH`. La suite entera vivía ahí:
`conftest.py` forzaba `DATABASE_URL=""` y cada uno de los 64 `test_*.py`
armaba su propio SQLite temporal. Era rápido y no necesitaba nada levantado.

**El problema es que validaba un motor que el proyecto no usa**, y eso no es
una objeción teórica: el mismo día en que se revisó, la suite estaba dando
por buenos tres defectos y afirmando un comportamiento inexistente.

**Lo que SQLite tapaba.** Los tres primeros aparecieron en los tests de
Encuestas Fase 0, recién escritos, al correrlos contra Postgres:

1. **Claves foráneas sin validar.** Los tests creaban encuestas con
   `sindicato_id=1`, un sindicato que no existía. SQLite no valida FK por
   defecto y el INSERT pasaba; Postgres lo rechaza con
   `ForeignKeyViolation`, que es lo que hubiera pasado en producción.
2. **Suponer la base recién nacida.** El test del umbral daba por hecho que
   no había fila de `ConfiguracionPlataforma`. Cierto en un archivo nuevo de
   SQLite, falso en cualquier base que viva más de una corrida.
3. **Consultas sin acotar.** Un participante se buscaba por CUIL en TODAS
   las encuestas: `MultipleResultsFound` en la segunda corrida.

El cuarto es el más interesante, porque no era un test flojo sino un test
que afirmaba **lo contrario de lo que hace la app**. `dashboard.limites_bruto`
calcula los extremos del slider de remuneración con `percentile_cont(0.01)` y
`(0.99)`, y tenía una rama para SQLite que caía a `MIN/MAX` con el comentario
"para bases chicas es lo mismo". No es lo mismo: con brutos de 500.000,
700.000 y 900.000, los percentiles dan **504.000 y 896.000**. El test
afirmaba 500.000 y 900.000 -- verde durante meses, describiendo un
comportamiento que la app no tiene en ningún entorno real.

**Lo que se hizo.**

- `conftest.py` crea una base **Postgres** descartable por proceso de pytest
  (`mitrabajo_test_<pid>_<azar>`), le instala la extensión `vector` y le
  arma el esquema con `create_all`; al terminar la borra. El nombre lleva el
  PID porque la convención es un archivo por proceso: dos corriendo a la vez
  nunca comparten base, igual que antes no compartían archivo.
- El esquema de la base de test sale de `create_all` y no de Alembic: correr
  59 migraciones por archivo multiplicaría por diez lo que tarda la suite.
- `db.py` **exige** `DATABASE_URL` y levanta un error explicando qué hacer.
  Desaparecieron `USANDO_POSTGRES`, `DB_PATH` y todas las ramas por motor
  (el `sqlite_sequence` de `testcarga`, el `return` temprano de
  `_sincronizar_secuencias`, el `create_all` de `init_db`, la rama MIN/MAX
  del dashboard, las guardas de `cargar_demo.py`, `medir_dashboard.py` y
  `carga/preparar_datos.py`).
- Los 64 `test_*.py` perdieron el preámbulo de tempfile/DB_PATH (y 98
  imports que quedaron sin uso).
- `crear_tablas()` sobrevive con un solo propósito, documentado: armar el
  esquema de la base de test.

**La trampa que quedó, y su red.** Varios `test_*.py` terminan con
`if __name__ == "__main__": pytest.main([__file__])`. Corridos así, el módulo
se importa como `__main__` **antes** de que pytest cargue `conftest.py`: el
engine queda apuntando a la base del `.env` -- la de desarrollo, con datos de
verdad -- y el test la llenaría de basura. `conftest.py` detecta que `db` ya
estaba importado y corta con un mensaje. La regla, igual, es más simple:
los tests se corren con `python -m pytest`.

Si pytest muere de mala manera quedan bases `mitrabajo_test_*` sueltas:
`python chequeo.py --limpiar-bases-de-test` las borra.

**Costo real de la mudanza**: 3 archivos de test con arreglos de fondo
(`test_cargar_demo_areas`, `test_cargar_demo_empleadores` -- los dos
forzaban `DATABASE_URL=""` en el subproceso -- y `test_dashboard`, con la
afirmación corregida), más uno de regalo: el bloque `__main__` de
`test_tests_carga.py` llamaba a una función renombrada hacía tiempo y nadie
se había enterado, porque bajo pytest ese bloque no corre. La suite quedó en
**725 tests, 77 archivos, todo en verde contra Postgres 16**.

## Módulo Encuestas (2026-09-11/12) — el anonimato en la forma de las tablas

Plan acordado decisión por decisión **antes de tocar código**, en
[`SPRINT_ENCUESTAS.md`](SPRINT_ENCUESTAS.md): 24 decisiones, modelo de
datos, seis fases y cuatro tests de privacidad. Este archivo cuenta cómo
salió.

### La premisa: si no se puede demostrar con un test, no se promete

El módulo le pregunta cosas al padrón y muestra los resultados agregados.
La mitad del valor está en que el afiliado conteste con franqueza, y eso
depende de una promesa: *"queda registrado que participaste, nunca qué
respondiste"*. Una promesa así no se sostiene con un cartel en la pantalla.

**Lo que la sostiene es la forma de las tablas**, y son cuatro cosas que
solo sirven juntas:

1. Las filas del **padrón** (`EncuestaParticipante`) se crean AL PUBLICAR,
   una por destinatario, y responder solo prende un booleano. Su orden de
   `id` es el del padrón, no el de las respuestas.
2. La **urna** (`RespuestaEncuesta`) guarda el DÍA, nunca la hora. Sin
   timestamp fino no hay forma de ordenar las respuestas en el tiempo para
   alinearlas con nada.
3. El padrón NO guarda cuándo respondió cada uno. La curva de ritmo del
   dashboard sale del día que guarda la urna.
4. La urna no tiene ninguna columna que apunte a una persona: ni CUIL, ni
   id de participante, ni sesión.

Sacá una sola de las cuatro y el orden de inserción alcanza para
reconstruir quién contestó qué. Hay un test por cada una, y **miran la
forma de las tablas, no el comportamiento de una ruta**: si alguien le suma
a la urna una columna que lleve a una persona, fallan aunque la app siga
andando — que es exactamente para lo que están.

En una encuesta **nominal** el vínculo sí existe, pero vive en su propia
tabla (`RespuestaNominal`) y **con la flecha apuntando a la urna**, no al
revés. Así `RespuestaEncuesta` sigue sin ninguna columna que lleve a
alguien, y el anonimato de las anónimas no depende de que alguien se
acuerde de dejar un campo en NULL.

### Tablas propias, no las de Trámites

`TipoTramite` arrastra código de expediente, área destino obligatoria,
pases, estados, chat y validaciones, nada de lo cual aplica. Y
`RespuestaTramite` cuelga de un `Tramite` que cuelga de un CUIL, lo que
rompería el anonimato **en la raíz del modelo**. Se reusó el vocabulario de
`CampoTramite.tipo_dato` y el constructor con vista previa; las tablas, no.
Mismo criterio explícito que ya rige entre trabajador y empleador: duplicar
antes que compartir.

### Todo lo que es una promesa lo arma el servidor

El disclaimer que ve el afiliado, los borradores de los avisos y el texto
del recordatorio **no están en el JS**. Salen de `encuestas.py`
(`disclaimer()`, `texto_aviso()`, `texto_noticia()`) y la pantalla los
pide. El motivo es siempre el mismo: el disclaimer es una promesa sobre qué
se guarda y no puede haber dos versiones; el lanzamiento y el recordatorio
tienen que decir lo mismo sobre el anonimato, y dos textos escritos en dos
lugares se desincronizan solos.

### El umbral vive en el SQL

Un grupo de una encuesta anónima con menos de N respuestas (5 por defecto,
configurable por plataforma) **no se calcula, no se cuenta y no viaja**: el
endpoint devuelve `oculto: true` y `preguntas: []`. Esconderlo en la
pantalla no sería ninguna protección — el JSON se lee con el inspector, y
ese es el tercero de los cuatro tests de privacidad.

El umbral se congela **al publicar**: si plataforma lo cambia después, una
encuesta ya cerrada no empieza a mostrar u ocultar cosas distintas.

**Y solo rige en las anónimas.** En una nominal el admin ve respuesta por
respuesta con nombre y apellido: es lo que el afiliado aceptó al responder
una encuesta que dice "nominal" en la cara, y lo que el CSV nominal
entrega. Aplicarlo ahí escondería en pantalla datos que el mismo módulo
exporta dos clics más allá.

### Cosas que se aprendieron construyéndolo

**La participación no se cuenta con `COUNT(*)` de la urna.** Una pregunta
múltiple deja varias filas por persona y un ranking deja una por opción: la
lista del panel informaba "391 de 106", que parece un error del sistema.
Hoy la lista cuenta gente (del padrón) y el dashboard cuenta personas con
una **pregunta testigo** — una obligatoria de las que dejan exactamente una
fila por persona, porque una respuesta sin obligatoria se rechaza entera y
entonces su cantidad de filas ES la cantidad de personas. Apareció con la
demo, que fue la primera vez que hubo volumen suficiente para que se notara.

**Chart.js se va al infinito** con `maintainAspectRatio: false` si el
contenedor crece con el canvas: paneles de 14.000px de alto. La altura la
fija siempre un envoltorio posicionado, nunca el atributo `height` del
`<canvas>`.

**El ranking no se grafica crudo.** "1" es la prioridad más alta, así que
una barra corta leyéndose como "lo más importante" es al revés de lo que el
ojo espera. Se grafica la prioridad —`(n+1)` menos la posición promedio—,
que arranca en cero y se lee sola; la posición real va en el tooltip.

**Una fecha ISO en un texto que lee una persona se lee como un mensaje del
sistema.** "Se puede responder hasta el 2026-10-12". De ahí salió
`fechas.dia_legible()` y el filtro `|dia` de las plantillas.

**El paso de avisar no es un lujo.** Publicar una encuesta y que nadie se
entere de que existe es la falla más común y la más cara, así que publicar
deja al admin en el paso de comunicación con los textos ya escritos. Y la
notificación va SIEMPRE al padrón fijado de la encuesta, nunca a un
criterio elegido aparte: si no, "leídas / no leídas" se mediría contra un
universo distinto al de "respondieron" y los dos números del dashboard no
se podrían comparar.

**El recordatorio lleva freno: uno por día.** Cuatro recordatorios y el
afiliado apaga las notificaciones de la app — y ahí se pierde el canal para
todo, no solo para encuestas. Va solo a los que faltan, que se sabe del
padrón sin mirar la urna, así que funciona igual en las anónimas.

**La seccional ve la encuesta central, y eso obligó a un freno nuevo.**
Hasta la Fase 4 una seccional no veía las encuestas de sede central, así
que esconder los botones alcanzaba. Desde N18 las ve (con los resultados
recortados a su gente, impuesto desde la sesión y no desde un parámetro),
y entonces hizo falta `_exigir_alcance_encuesta`: sin él, un admin de
seccional arma el POST a mano y edita, publica, cierra o borra la nacional.

### La demo tuvo que crecer

El módulo no se puede mostrar con tres afiliados: el umbral escondería
absolutamente todo y la evolución no existiría. `demo_encuestas.py` siembra
96 afiliados sintéticos repartidos entre las tres seccionales de la UOM y
**tres tomas de la misma encuesta** en el tiempo, con una historia adentro
que se puede contar en voz alta mirando la pantalla: el clima mejora, la
preocupación se corre del sueldo a la seguridad, y **Córdoba mejora menos
que Rosario** — para que el filtro por seccional muestre algo y no tres
curvas iguales. Más una nominal abierta, que es la que muestra el CSV con
nombre y apellido.

Todo pasa por las funciones de `db` y no por INSERT directo, mismo criterio
que el resto de `cargar_demo.py`: la demo no puede quedar en un estado que
la aplicación real no sepa producir. Lo único que se toca a mano después es
la ventana de cada toma, el día de sus respuestas y la fecha de su
historial — porque una encuesta que cerró hace cuatro meses no se puede
responder hoy, y sin historia no hay evolución que mostrar.

### Lo que quedó afuera, a propósito

Encuestas a **empleadores** (duplicarían el módulo entero y además la
respuesta de una empresa no es anónima en los hechos), **NPS** y preguntas
**matriz**, **reabrir** una encuesta cerrada (se duplica y se lanza otra
ronda, que queda como un hecho separado y auditable) y **agregar
preguntas** a una encuesta que ya tiene respuestas.

## Georreferenciación de Seccionales y domicilios (2026-09-12)

Pedido de Sd, acordado decisión por decisión ANTES de tocar código (las
preguntas fueron de a una y las respuestas cambiaron tres veces el alcance
del sprint). Le da ubicación geográfica a las Seccionales y la usa en cinco
lugares: alta guiada, ficha de consulta, "Mi seccional" del afiliado, mapa
del Panel Sindical y "Seccionales cerca de mí".

### El alcance creció en la conversación, no en el código

El prompt original hablaba solo de seccionales. Al preguntar por la
duplicación entre `Seccional.direccion` (texto libre) y el `direccion_texto`
que el plan pedía, Sd contestó dos cosas: que el texto viejo era provisorio y
no importaba perderlo, y que **el domicilio del trabajador se iba a cargar
igual que el de la seccional, con las mismas especificaciones**. Sobre eso
salió la pregunta de si el domicilio del afiliado también se geocodifica: la
respuesta fue sí, con coordenadas exactas y confirmación en el mapa.

Eso convirtió una feature de seccionales en una de **domicilios**, y de ahí
sale la decisión que ordena todo el sprint: `Seccional` y `Trabajador`
comparten el MISMO bloque de once campos, con los mismos nombres y los mismos
tipos (`geo.CAMPOS_DOMICILIO`), y `test_seccional_geo.py` lo verifica contra
las dos tablas. Antes eran parecidos pero no iguales — en el trabajador
`piso` y `ciudad`, en la seccional nada —, y dos nombres para lo mismo es
exactamente lo que hace que cada pantalla arme la dirección a su manera. Se
renombraron a `piso_depto` y `localidad`: un rename conserva los datos.

No se usó un mixin de SQLModel para compartir los campos aunque sería más
DRY. El contrato se verifica con un test, que es la forma que el proyecto ya
usa para las promesas que no se pueden dejar libradas a la memoria
(`test_fechas.py` recorre módulos con `ast` por la misma razón), y así los
modelos siguen leyéndose explícitos como el resto de `db.py`.

### Tres defectos que aparecieron probando contra las APIs de verdad

Los tests con respuestas simuladas pasaban. Los tres salieron al llamar a
Georef y Nominatim de verdad, y los tres habrían llegado a la demo:

1. **`Bv. San Juan 430` en Córdoba devuelve CERO resultados** y `Boulevard
   San Juan 430` la encuentra. Nominatim no expande abreviaturas, y las
   direcciones argentinas están llenas de "Av.", "Bv.", "Gral.", "Pte.". Se
   expanden para CONSULTAR y se guarda lo que la persona escribió: si el
   cartel de la esquina dice "Bv. San Juan", la dirección de la seccional
   dice lo mismo.

2. **El parámetro `city` de Nominatim orienta pero NO acota.** "San Juan 430,
   Córdoba" devuelve esa calle en Morrison y en Alicia, a 200 km de Córdoba
   capital, y las devuelve PRIMERO. Sin corte, el admin elegía de una lista
   donde el primer globo estaba en otra ciudad y no tenía forma de darse
   cuenta. Ahora se descarta todo lo que caiga a más de 60 km del centroide
   de la localidad pedida y se ordena por cercanía a ese centro.

3. **En CABA no hay "localidades".** Georef modela los 49 BARRIOS
   (Constitución, Retiro, Recoleta…) como localidades de la Ciudad, así que
   nadie que escriba una dirección porteña va a tipear una localidad que
   resuelva — y sin embargo Nominatim encuentra "Av. Independencia 1200"
   perfectamente. La primera versión cortaba con un error y dejaba **toda la
   Capital imposible de georreferenciar**. Ahora una localidad que Georef no
   reconoce no es un error: se busca la calle igual y, si hace falta un
   centroide de respaldo, se cae al de la provincia.

Un cuarto lo encontró un test: una respuesta de Nominatim con `lat` ilegible
reventaba el alta entera. Se descarta ese candidato y se sigue — misma regla
que `validador.a_numero` con lo que devuelve la IA: la salida de un tercero
no es un contrato.

### SQLModel acepta una columna que ya no existe y la tira en silencio

El más caro, y no lo mostró ningún test: `Seccional(direccion="Av. Falsa
123")` sobre un modelo que ya no tiene esa columna **no falla**. Pydantic la
descarta y el objeto se guarda sin dirección. Los cinco cargadores
(`cargar_demo`, los dos lotes, `medir_dashboard`, `carga/preparar_datos`)
seguían pasando el kwarg viejo y perdían el dato sin un solo error. Apareció
al correr `cargar_demo.py` contra una base limpia y mirar la tabla, que es
justamente lo que la suite no hace.

La lección práctica: después de un rename de columna, **correr los
cargadores de verdad**, no solo la suite.

### Qué decide el servidor y qué el navegador

- **La dirección que se muestra la arma el SERVIDOR** (`armar_direccion_texto`),
  por el mismo motivo que el disclaimer de Encuestas: si la tabla del panel,
  la ficha y la app del afiliado la compusieran cada una a su manera, habría
  tres direcciones distintas para la misma seccional y ninguna sería "la"
  dirección. Ahí apareció un detalle que solo se ve con datos: en CABA la
  localidad y la provincia son el mismo nombre, y toda dirección porteña lo
  escribía dos veces.
- **La ubicación del teléfono NO viaja al servidor.** El permiso se pide al
  tocar el enlace (nunca al abrir la app) y con el texto que explica para qué;
  la posición se usa para ordenar la lista y se descarta. Por eso la distancia
  se calcula en el navegador. Hay un test que recorre las rutas de la app
  buscando alguna que pudiera recibirla, y que verifica que `/api/seccionales`
  devuelva lo mismo con o sin `lat`/`lon`: es la promesa que la pantalla le
  hace al afiliado antes de pedirle el permiso, y tenía que ser demostrable.
- **La tasa y la caché son del servidor.** Nominatim permite un pedido por
  segundo y bloquea por IP al que se pasa. El candado es POR PROCESO y Render
  corre un worker por núcleo, así que el peor caso son N pedidos por segundo:
  se acepta a ojos abiertos porque geocodificar lo dispara una persona
  apretando "Buscar", de a una dirección, y `GeoCache` se come los repetidos.
  Si algún día no alcanza, el patrón que el proyecto ya usa para coordinar
  instancias es un UPDATE condicional (`db.reclamar_plan_programado`).
- **`GeoCache` no tiene `sindicato_id`**, única excepción consciente al
  aislamiento total. Guarda la respuesta de una API pública a una dirección
  normalizada ("santa fe|rosario|san martin|850"), que no es dato de nadie;
  ponérselo mataría el reuso —dos gremios con seccional en la misma cuadra
  pedirían dos veces, gastando el mismo presupuesto de 1/s— sin proteger nada,
  porque ninguna pantalla lee esa tabla.
- **El domicilio del afiliado lo edita el afiliado**, así que el endpoint de
  geocodificación no es solo de admins: queda expuesto a todo el padrón. De
  ahí el tope de 20 por hora **por CUIL**, y no por IP — en un gremio con wifi
  compartido la IP es la misma para todo el edificio y un tope por IP
  castigaría a los cien que no hicieron nada.

### El mapa del Panel es un selector, y por eso ignora su propio filtro

Tocar un marcador aplica el filtro por esa seccional al resto del tablero,
con el mismo mecanismo que los gráficos (el chip de filtro activo se prende
igual). Si el endpoint respetara el filtro de seccional, tocar un marcador
dejaría el mapa con un solo punto y no habría forma de volver: es el mismo
criterio con el que `diferencias_empresa` ignora el filtro de resultado
porque ese gráfico ES de los que tienen diferencias.

Los agregados reusan los tres constructores de WHERE que ya existían
(`_sql_recibos` / `_sql_tramites` / `_sql_notificaciones` con `forzar_join`)
agrupando por `seccional_id`, así el aislamiento por `sindicato_id` viaja
adentro de esos WHERE y no se puede olvidar en la consulta nueva. Dos de los
seis indicadores (afiliados y "ingresó al menos una vez") son una foto del
padrón y no se mueven con el período, igual que el KPI "Afiliados
registrados"; la pantalla lo dice para que no parezca un error. Medido con la
demo cargada: 29 ms, contra el criterio de 1 s del panel.

La escala de color es FIJA de la app y no la marca del sindicato: es
cuantitativa, y con el acento de cada gremio la misma intensidad significaría
otra cosa en cada tenant. El `--destacado` queda reservado, como en todo el
panel, para la seccional seleccionada. El radio del círculo va por **raíz
cuadrada** de los afiliados: el ojo compara áreas, y con radio lineal el doble
de afiliados se ve cuatro veces más grande.

Las seccionales sin coordenadas no van al mapa pero tampoco desaparecen: se
listan en un aviso. El enlace para ir a ubicarlas aparece SOLO si esa persona
tiene la sección "seccionales" — ver el mapa y cargar una dirección son
permisos distintos, y ofrecer un botón que va a dar 403 es peor que no
ofrecerlo.

### El alta masiva y el proceso en segundo plano

Cien direcciones a un pedido por segundo son cien segundos con el navegador
colgado, y Nominatim bloqueando de paso. Así que la masiva suma seccional
(por NOMBRE, sin distinguir mayúsculas ni tildes: a una planilla se pega
"Rosario", no el id 7) y CP, y guarda todo `sin_geo`. El botón
"Georreferenciar pendientes" los ubica después, de a uno, en un hilo —mismo
criterio que la indexación del convenio en `rag.py`—, y cada fila se guarda
apenas se resuelve: si el proceso se corta a la mitad (un redeploy de Render,
que pasa seguido), lo hecho queda hecho y la próxima corrida sigue desde ahí.

El avance vive en la tabla `GeoPadron` y no en memoria del proceso, porque
Render corre un worker por núcleo: el hilo que trabaja está en uno y la
pantalla que pregunta el avance puede caer en otro. Con un diccionario en
memoria, la barra de progreso mostraría cero para siempre. Y una corrida que
no da señales por 15 minutos se da por muerta, para que un proceso caído no
deje el flag en "corriendo" bloqueando a todos.

### Lo que encontró el robot E2E

Dos cosas que ninguna prueba de servidor podía ver:

- **"Cancelar edición" quedaba inalcanzable.** El botón vivía dentro del paso
  1 del asistente, y editar una seccional abre en el paso 2 (con el globo ya
  puesto, que es lo que uno viene a corregir). Pasó a vivir junto a la tira de
  pasos, visible en los tres.
- **El rediseño "Hilo" pintaba los candidatos de ámbar.** La regla
  `button:not(.sec):not(.mini)…` de `admin.html` alcanza a todo botón que no
  esté en su lista de excepciones, así que las tarjetas de candidato —que son
  `<button>`— salían con el fondo de acento y la tipografía condensada en
  mayúsculas, en vez de la tarjeta clara que corresponde. Se sumó `.geo-cand`
  a la lista, que es como el proyecto ya resuelve esto.

Un tercer hallazgo es del entorno y no de la app, pero vale anotarlo: en la
portada del trabajador el evento `load` no llega nunca si las teselas de OSM
no resuelven (quedan colgadas), así que los robots esperan la navegación con
`wait_until="commit"` y no la carga completa. Lo correcto igual: lo que
interesa es haber entrado, no que haya terminado de dibujarse un mapa de un
tercero.

### La demo

Los tres sindicatos quedan con cuatro o más seccionales georreferenciadas en
provincias distintas y con trabajadores y recibos repartidos. La Gastronómica
pasó de UNA seccional a cuatro y ahora se le corre el lote, que antes no se
le corría; **sigue siendo el sindicato centralizado de la demo** —sin Admin
de Seccional ni áreas por delegación—, porque ese contraste con la UOM es lo
que muestra que el rol es opt-in. Tener delegaciones y tener un rol de
delegación son dos cosas distintas.

Las direcciones son ficticias pero verosímiles: no se conocen con certeza los
domicilios reales de esos gremios y no se inventan como si lo fueran. Las
coordenadas SÍ son reales para esa esquina —se geocodificaron una vez, a
mano— y se guardan como `manual` justamente para no dar a entender que son
domicilios verificados del sindicato. Las seccionales genéricas del lote (las
que recibe La Bancaria, que no tiene propias) llevan el centroide real de su
ciudad y van como `aproximada`, que es exactamente lo que son: el centro de
la localidad, no la puerta.

## El esquema de la suite no era el de producción (2026-09-12)

Salió de una comparación que se hizo al pasar, verificando la migración de
georreferenciación: `create_all` (los modelos, que es como la suite arma su
base) producía `json` donde Alembic produce `jsonb`. **Quince columnas**, en
trece tablas: `modulos_habilitados`, `semaforo_datos`, los dos
`destino_seccionales`, los tres `criterio_valores`, los dos
`reglas_consistencia`, los dos `validaciones`, los dos `advertencias`,
`filtros` y `cortes`.

Las migraciones venían usando `sa.JSON().with_variant(postgresql.JSONB(),
"postgresql")` desde el principio; los modelos, `Column(JSON)` pelado. Nunca
falló nada, y ese es justamente el problema: para leer y escribir un dict
entero los dos tipos se comportan igual. La diferencia aparece en lo que
`json` NO tiene — operador de igualdad, contención (`@>`), índices GIN —, así
que la primera consulta que usara cualquiera de esas cosas habría andado en
la suite y roto en producción.

Es el mismo defecto que motivó sacar SQLite el 2026-09-11 ("la suite entera
validaba contra un motor que el proyecto no usa"), pero adentro del mismo
motor, y por eso invisible hasta que alguien compara los dos esquemas columna
por columna.

### Lo que se arregló y lo que no

Los modelos pasaron a declarar `db.JSON_TIPO`, la misma expresión de las
migraciones. **No hizo falta ninguna migración**: producción ya tenía `jsonb`;
el que mentía era el modelo, y con él la base de la suite.

Quedaron siete columnas en `json` —`alias` de Concepto, los tres `detalle`,
`fragmentos_usados`, `parametros`, `resumen`— porque sus migraciones son
anteriores a la variante y la base LAS TIENE así. El modelo dice lo que la
base tiene, que es el invariante que importa. Pasarlas a `jsonb` sería mejor
(indexables, comparables) pero exige un `ALTER COLUMN ... TYPE jsonb` que
reescribe tablas con datos: es otro cambio, con su propia decisión.

De paso quedó corregido CLAUDE.md, que afirmaba que `alias` y `detalle` ya
eran jsonb. No lo eran.

### El test que faltaba desde julio

`conftest.py` prometía `test_migraciones.py` desde que la suite pasó a
Postgres ("que el esquema de las migraciones coincida con el de los modelos
es otra cosa, y se verifica aparte") y ese archivo **no existía**. Ahora sí:
levanta una base con `alembic upgrade head` y la compara contra la de
`create_all` en tablas, columnas, tipos y obligatoriedad. Tarda 1,7 segundos
porque las migraciones enteras corren en 1,4.

Alembic va en un SUBPROCESO y no con `command.upgrade` en el mismo proceso:
`migrations/env.py` usa `db.engine` directamente —a propósito, para leer
DATABASE_URL igual que la app— e ignora la URL de `alembic.ini`, así que
llamarlo desde el test levantaba las migraciones sobre la base de la suite,
que `create_all` ya había llenado, y reventaba con "relation already exists".
Con el subproceso se corre igual que lo corre una persona.

Y encontró algo más en la primera corrida: **ocho columnas JSON que el modelo
dejaba nulas y la base declara NOT NULL**. `sa_column=Column(...)` pisa al
`Field`, y un `Column` sin `nullable` nace nullable: un test podía guardar
`None` en `modulos_habilitados` y pasar, donde producción lo rechaza. También
se alinearon hacia lo que corre.


### Y las últimas siete (mismo día)

Con los modelos ya alineados, quedaban siete columnas que eran `json` en los
dos lados --consistentes, pero no lo que CLAUDE.md decía--: `alias` de
Concepto, los tres `detalle` (Reporte, ReciboVerificado, EnvioSindicato),
`fragmentos_usados`, `parametros` y `resumen`. Se convirtieron todas
(`d2c8f04a6b31`), así que **el proyecto ya no tiene ninguna columna `json`**.

El riesgo se midió ANTES de escribir la migración, no después:

- **Orden de las claves.** `jsonb` normaliza el orden de los objetos pero
  CONSERVA el de los arrays. Se revisó qué recorre el código en orden:
  `discrepancias`, `alertas`, `log`, `respuestas`, `alias` -- todos arrays.
  Nada itera claves de objeto para mostrar.
- **Tiempo de la reescritura.** Sobre una copia de la demo con 15.000 recibos
  (25 MB en `reciboverificado`), las siete conversiones tardaron 1,5
  segundos; a las 50.000 del banco de pruebas del panel serían unos 5. En
  Render esto corre en el Pre-Deploy con la versión anterior sirviendo, así
  que son segundos de espera en un momento que ya iba a tener un reinicio. A
  millones de filas habría que hacerlo de otra forma (columna nueva, backfill
  por lotes, swap); a esta escala no se justifica.
- **Datos que no castean.** `jsonb` rechaza la secuencia de escape de NUL
  dentro de una cadena y `json` la acepta: es el único modo de falla real. No
  hay ninguna en las 21.000 filas de las tres tablas de la demo. Si apareciera
  en producción, el cast aborta, la migración revierte entera y el deploy se
  corta con la versión vieja intacta -- falla del lado seguro. El docstring de
  la migración deja el síntoma y la consulta para encontrarla.

Verificado además sobre la base de demo REAL y no una sintética: 2,4 segundos
de punta a punta, y los 15.000 recibos con su `detalle` entero después.

### Dos ajustes de uso, probando con datos reales (2026-09-12, noche)

Pedidos de Sd después de usarlo en Pruebas:

- **El modal de perfil, 20% más ancho en desktop** (480 -> 576px). La regla va
  scopeada a `#overlay-perfil` y dentro de `@media (min-width: 700px)`:
  `.modal-notif-caja` la comparten CUATRO overlays --perfil, notificaciones,
  mapa en pantalla completa y "cerca de mí"-- así que ensanchar la clase los
  movía a todos. En teléfono no cambia nada, ahí ya ocupa el ancho completo.
- **Al consultar o editar un trabajador ya ubicado, el mapa se abre solo.**
  Quien abre la ficha de un afiliado viene a ver dónde vive o a corregirlo:
  obligarlo a apretar "Ubicar en el mapa" para ver algo que ya existe es un
  clic de más sobre información que ya está. Sin coordenadas no se dibuja
  nada, que es lo correcto. Como en ese caso no hay entre qué elegir, la
  columna de candidatos se esconde y el mapa toma el ancho completo (`.geo-con-
  lista.sin-lista`); volver a apretar "Ubicar" la trae de nuevo.

Y algo que apareció mirando la pantalla: el texto de ayuda decía "**Encontramos**
la dirección exacta" sobre un domicilio guardado la semana pasada, donde no se
acababa de buscar nada. Son dos momentos distintos y no pueden compartir el
texto, así que `geo.py` suma `AYUDA_GUARDADA` al lado de `AYUDA_PRECISION`
--los textos los sigue armando el servidor, por lo mismo de siempre-- y lo usan
tanto el domicilio del afiliado como la edición de una seccional ya ubicada,
que tenía el mismo desajuste.
