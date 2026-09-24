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

### La explicación del tope se ofrecía también cuando el recibo retenía de MÁS (2026-09-14)

Encontrado por Sd escaneando un recibo sintético de julio 2025: los tres
aportes daban discrepancia y la app cerraba con "puede deberse a que tuviste
más de un recibo este mes y el tope se alcanzó entre los dos". Pero el recibo
retenía **de más**, no de menos, así que esa explicación era imposible.

La causa: la alerta `tope_posible_explicacion` se enganchaba a *cualquier*
discrepancia de una fórmula `sujeto_a_tope`, sin mirar el signo. `dif` ya se
calculaba tres líneas antes y no se usaba para decidir. **Un tope alcanzado
entre dos recibos solo puede hacer que un empleador retenga de MENOS** — la
base se recorta, nunca se agranda. Ofrecerla hacia el otro lado no es un
mensaje inexacto: es tranquilizador justo en el caso en que al trabajador le
descontaron de más y conviene que consulte.

Números del caso, que además muestran que el motor hacía bien su parte: el
tope de julio 2025 es 3.385.490,05 (`data/topes_ss.csv`, Res. ANSES
251/2025), y los "esperado" que mostraba la pantalla eran exactamente su 3%
(101.564,70) y su 11% (372.403,91). O sea **la app topeó y el recibo no**:
calculó los aportes sobre el sueldo completo, 167.759,69 de retención en
exceso.

Lo que se hizo:

- La lista de conceptos con discrepancia se partió en dos por signo
  (`conceptos_tope_retuvo_de_menos` / `..._de_mas`). La nota de pluriempleo
  queda solo para la primera, y el texto arranca ahora "Que figure menos de
  lo esperado en ..." para que sirva igual cuando la línea trae un importe
  bajo y cuando directamente no figura (el `concepto_faltante` retiene 0, que
  también es de menos, y entraba a la misma lista diciendo "La diferencia
  en X" sobre algo que no estaba).
- Alerta nueva `tope_no_aplicado` para el caso contrario, y **solo cuando la
  app efectivamente topeó** (`base_remunerativa > tope_maximo`): ahí no hay
  nada que conjeturar, el tope es público y el exceso es una resta, así que
  se dice el hecho con los dos números. Es accionable frente al sindicato, a
  diferencia del "no se puede confirmar mirando un solo recibo" del otro
  caso. Si la app no topeó (sueldo por debajo del tope, o período sin tope
  cargado), el tope no explica nada y no se dice nada del tope: de ese caso
  ya avisa `tope_no_verificable`.
- Un mismo recibo puede caer en las dos listas (un aporte de menos y otro de
  más) y entonces salen las dos alertas, cada una nombrando solo a los suyos.
- Cuatro tests nuevos en `test_topes_base_imponible.py` (33 en total), uno de
  ellos con los números exactos del recibo que lo destapó. Los que ya estaban
  siguen pasando sin tocarse: el comportamiento solo cambia hacia el lado que
  no tenía ninguna prueba, que es por donde se coló.

Nota sobre el recibo que lo destapó, por si vuelve a aparecer en un golden
set: además **es incoherente consigo mismo**. Obra social (3%) y cuota
sindical (1,5%) salen de 4.615.388 = total 4.767.392 menos el refrigerio, que
es no remunerativo y cierra; pero jubilación y PAMI salen de 4.320.225, que
no es ninguna combinación de las once líneas del recibo (verificado por
fuerza bruta) ni ningún tope del catálogo — es el 93,6% de la otra base, un
factor sin explicación. El generador de esos PDF no vive en este repo.

## El flujo del recibo, encuadrado: cinco pantallas, un solo marco (2026-09-14)

Relevado por Sd mirando la app en escritorio: el recorrido del recibo eran
**cinco pantallas que no parecían de la misma app**. La primera (la guía de
foto) tenía la línea de pasos; "Tu recibo, listo" no la tenía y usaba los
botones redondeados viejos y un emoji de hoja como ícono; el cronómetro
tampoco la tenía; la de confirmar decía "2 de 3" sin línea; y la de resultado
no decía nada. Encima los paneles eran claros sobre el fondo claro de la app,
así que en una pantalla grande no se distinguía dónde empezaba el contenido.

La numeración además estaba mal, y no era un detalle de redacción: la
**lectura** era el paso 2 según la línea de la primera pantalla, pero la
pantalla de **confirmar** también decía "Paso 2 de 3". Un paso no puede ser
dos cosas.

Se armaron tres propuestas en `disenos/recibo-flujo-propuestas.html` (Marco /
Panel oscuro / Cáscara, con el conmutador de paleta de siempre) y Sd eligió
**Marco**. Lo que quedó:

- **Cada momento es un `.rc-panel`**: tarjeta oscura con filo de acento y el
  contenido en una hoja clara insertada (`.rc-hoja`), acciones abajo sobre el
  oscuro (`.rc-acc`). El oscuro despega el panel del fondo; la hoja deja leer
  diecisiete conceptos con importes, que era el argumento contra hacerlo todo
  oscuro (propuesta B).
- **Los bloques de la hoja perdieron su caja**: adentro del marco cada borde
  era un marco más. Los separa un hairline (`.rc-hoja > * + *`), y por eso
  `renderPreview` escribe directo sobre `#preview-contenido`, que ES la hoja
  -- si envolviera, sus bloques dejarían de ser hijos directos y no habría
  separador.
- **Tres pasos: Subí · Revisá · Resultado**, con la línea (`.rc-pasos`) en los
  cinco momentos. **Las dos esperas dejaron de ser huérfanas**: cada
  cronómetro es el estado `curso` del paso al que lleva. Así la lectura y la
  confirmación dejan de pelearse por el número 2.
- **"Tu recibo, listo" desapareció como pantalla**: elegir el archivo es un
  estado del paso 1 (`estadoPaso1()`), con el archivo y "Leer recibo" en el
  mismo panel. `ver()` perdió `'listo'` y acepta `null` para no mostrar
  ninguna, que es lo que se usa mientras la IA trabaja.
- **Un solo marco, una sola implementación**: los dos momentos estáticos
  declaran su estado en el HTML con `data-pasos` y los dos que arma el JS
  usan `panelPaso()`; los dos caminos llaman a `pasosHTML()`. Si hubiera dos
  implementaciones, en tres cambios serían dos marcos distintos.
- **La carátula del recibo pasó de oscura a clara.** Era `.rc-oscura`; un
  bloque oscuro adentro de una hoja blanca adentro de un panel oscuro son
  tres niveles y no manda ninguno. Conserva el filo de acento, que es lo que
  la distingue del resto de la hoja.
- **El veredicto perdió su título** y lo dice el encabezado del panel ("Hay 3
  diferencias"), una sola vez. Adentro quedan el ícono de estado -- que es lo
  que le da el color -- y los hallazgos.
- **`.rc-acc .btn.sec`, no `.rc-panel .btn.sec`.** El secundario sobre el
  oscuro va en blanco, pero adentro de la hoja tiene que seguir siendo el de
  siempre: scopeado al panel entero, "Enviar a mi sindicato" quedaba blanco
  sobre blanco.
- Quedó sin uso y se borró: `.rc-oscura`, `.rc-oscura-tit`, `.ia-leyenda`,
  `.ia-sub` (la leyenda y la bajada de la espera son ahora el título y la
  bajada del panel) y `.archivo`/`.thumb`, que eran de la pantalla que dejó
  de existir.

**Nada de la lógica cambió**: mismos endpoints, mismos datos, mismo
`renderPreview`/`renderResultado` salvo por dónde escriben. La verificación
se hizo renderizando la plantilla con Jinja a un archivo y recorriendo los
cinco momentos en el navegador.

## El recibo ajeno se leía entero antes de frenarse (2026-09-14)

Reportado por Sd: con sesión de un CUIL, subió el recibo de otro. "Leyó todo
y me mostró. Debió fallar antes."

El control existía y funcionaba -- pero en el lugar equivocado del recorrido.
`cuil_no_coincide()` se evaluaba en `/api/validar`, o sea al **confirmar**.
Para entonces `/api/leer` ya había devuelto el recibo completo y la pantalla
de confirmar le había mostrado a quien subió el archivo el nombre, el CUIL,
el empleador y todos los importes de otra persona. El bloqueo llegaba después
de lo único que había que evitar.

El CUIL del recibo recién se conoce **después** de leerlo (está en la
imagen), así que la llamada a la IA no se puede ahorrar y su costo se
registra igual -- si no, el panel de costos dejaría de decir el gasto real.
Lo que no sale de la ruta es el contenido: `/api/leer` corta con
**E-RECIBO-04** apenas compara, y lo hace **antes** de `registrar_recibo_
sospechoso`, porque de un recibo que no es de quien lo sube no se guarda
nada, ni el archivo.

**El mismo agujero estaba en el gemelo, y ahí era peor.** `/api/aportes` lee
el comprobante de ARCA, que también trae CUIL, y nunca lo comparaba: el
comprobante de otra persona no solo se mostraba, se **guardaba como semáforo
propio** (`guardar_semaforo` indexa por el CUIL de la sesión, no por el del
comprobante) y seguía ahí al volver a entrar. Corta con **E-APORTE-03**.

Detalles que valen para la próxima:

- **El chequeo de `/api/validar` NO se sacó.** Esa ruta se puede llamar sola,
  con cualquier payload: el corte de `/api/leer` protege a la persona que usa
  la app, el de `/api/validar` protege al catálogo y al historial de quien
  arma el POST a mano. Son dos cosas distintas.
- **Una sola regla de comparación**: `validador.cuiles_distintos()`, que
  `cuil_no_coincide()` ahora usa por dentro. El comprobante de ARCA trae el
  CUIL suelto y el recibo lo trae adentro de `empleado`; con dos
  implementaciones, en algún momento una de las dos normaliza distinto.
- **Ninguno de los dos afirma nada con datos incompletos**: si el CUIL del
  documento no se pudo leer, o no hay CUIL en la sesión, no se bloquea. Un
  bloqueo por un dato ausente es peor que el caso que evita.
- **Los dos mensajes tienen prohibido hablar de la foto.** El documento se
  leyó perfecto; el problema es de quién es (ver la regla en `errores.py`).
- Tests: `test_cuil_leer_ajeno.py` (9), incluido uno que revisa que **ni un
  dato del recibo ajeno aparezca en el cuerpo de la respuesta**, no solo que
  el status sea 403.

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

## Qué se le exige a cada domicilio, y modales que se mueven (2026-09-13)

Tres cosas en un mismo bloque, las tres pedidas por Sd después de probar la
georreferenciación en La Bancaria. La primera venía de una pregunta suya:
¿conviene exigir la georreferenciación exacta, que hace más difícil el alta a
quien no está acostumbrado, o se tolera provincia y ciudad sin lo fino? Su
respuesta fue que **depende del actor**, y eso es lo que se implementó.

### La seccional va en la puerta

"La dirección de las seccionales sí debiera ser exacta, además es un número
finito y lo carga el sindicato."

Hasta acá una seccional se podía guardar `sin_geo`, y estaba escrito como una
virtud: "que una API de terceros no responda no puede impedir dar de alta una
delegación". Lo que ese razonamiento no miraba es qué hace el afiliado con esa
fila: toca "Cómo llegar" y el teléfono lo lleva **al punto guardado**. Con
`aproximada` —el centroide de la localidad, que es lo que devuelve el
geocodificador cuando no encuentra la altura— eso significa el centro de la
ciudad, sin ningún aviso. Y con `sin_geo` la seccional no aparece ni en el mapa
del Panel ni en la app: se cargaba y no servía para nada.

Así que ahora `POST /admin/seccional` exige provincia, localidad, calle y
altura (`geo.OBLIGATORIOS_SECCIONAL`) **y** un `precision_geo` en
`geo.PRECISIONES_SECCIONAL`, que son exactamente dos: `exacta` y `manual`.

Lo interesante es por qué `manual` sí y `aproximada` no, cuando el error en
metros puede ser parecido: **lo que cambia es quién responde por el punto.**
`aproximada` la puso una API que no encontró la dirección; `manual` la puso una
persona que miró el mapa y arrastró el globo hasta la puerta. Eso convierte a
`manual`, además, en la vía de escape que salva la vieja promesa: si Georef y
Nominatim están caídos, el asistente ahora ofrece "Ubicar a mano en el mapa",
que abre Leaflet en el centro del país (`geo.CENTRO_ARGENTINA`, una constante,
sin llamar a nada) y deja marcar el punto tocando —para eso `mapa.js` sumó
`alTocar`—. Las teselas son un tercer servicio, independiente de los dos
geocodificadores. **Ninguna API de terceros bloquea el alta; lo único que
cambió es que el resultado tiene que ser un punto y no un casillero vacío.**

En la pantalla: se fue el botón "Seguir sin ubicar", "Continuar" nace
deshabilitado y se habilita cuando el punto sirve (`secUbicada()`, espejo de
`geo.ubicacion_precisa`), y "Buscar" avisa qué falta antes de ir a ninguna
parte. La validación está en los dos lados a propósito: el botón deshabilitado
se saltea con un POST armado a mano, y un formulario que deja mandar algo que
el servidor rechaza es una pantalla que miente.

Efecto colateral que valía la pena: las seccionales `aproximada` que ya existen
(las genéricas del lote sintético) ahora avisan en la app del afiliado que el
punto es el centro de la localidad. No se pueden crear más así, pero las que
hay tienen que decir lo que son.

### Del afiliado, provincia y localidad

"Es muy difícil para el sindicato tener info sin esos datos al menos."

`geo.OBLIGATORIOS_AFILIADO` son dos campos y nada más. Con provincia y
localidad el sindicato ya puede agrupar, dirigir noticias por seccional y ver
dónde vive su gente; pedirle la altura y que confirme un globo a alguien que
se está registrando desde el teléfono es la forma más barata de perderlo en la
puerta. Todo lo demás se muestra igual, con "(opcional)" al lado —una
obligatoriedad que no se ve es una trampa, y un campo opcional que parece
obligatorio es abandono—.

Rige en las **cuatro** puertas por las que entra un domicilio, porque una sola
que no valide vuelve inútiles a las otras tres: alta manual del admin, alta
masiva, registro del afiliado y su perfil. Y la pregunta la contesta una sola
función, `geo.faltan_campos`: si cada ruta decidiera por su cuenta, el mismo
domicilio pasaría o no según por dónde se cargó, que es el defecto que el
bloque compartido de campos vino a corregir.

Dos decisiones finas:

- **El alta masiva valida por LÍNEA, no por lote.** Una planilla de 500 filas
  no se rechaza entera porque tres no traigan la provincia: las que faltan
  quedan afuera y la pantalla dice cuántas y muestra tres de ejemplo (casi
  siempre es la misma columna en todas). Esa ruta ya venía descartando en
  silencio las líneas sin CUIL o sin nombre —contaba las altas en una variable
  que después no usaba—, así que el sindicato podía creer que cargó 500 y tener
  497. Ahora el conteo se ve. De paso apareció que `err=datos` del alta
  individual no se mostraba en ninguna parte: el alta fallaba y la pantalla
  volvía igual, sin decir nada.
- **En el registro el domicilio se guarda como un BLOQUE.** La primera versión
  fusionaba campo por campo, conservando lo que el padrón ya tenía, y el
  resultado era peor que cualquiera de las dos fuentes: alguien que declaraba
  vivir en La Plata terminaba con la calle que el padrón tenía de Rafaela, o
  sea una dirección que no existe en ningún lado. **Un domicilio es UN dato, no
  seis.** Así que o reemplaza entero al anterior o no toca la fila, y manda la
  persona: es su dirección, la está declarando ahora, y el perfil ya la deja
  cambiarla un minuto después —pedirle dos campos obligatorios para después
  descartarlos sería un formulario que miente—. Si lo que escribe es idéntico a
  lo que había, la fila no se toca: reescribirla le borraría las coordenadas
  (el alta escribe `sin_geo`, no geocodifica) y la mandaría de nuevo a la cola
  de georreferenciación estando ya ubicada.

Y **en el registro no se llama a ninguna API**, por lo mismo que en el alta
masiva: una espera de ocho segundos contra un servicio ajeno en el camino del
alta es el peor lugar posible. Las filas quedan `sin_geo` **con localidad**,
que es exactamente lo que "Georreferenciar pendientes" procesa después — o
sea que exigir estos dos campos es lo que hace que ese proceso sirva para
algo.

Los tres cargadores de demo pasaron a darle a cada afiliado la localidad y la
provincia **de su seccional** (antes: `cargar_demo.py` no ponía ninguna,
`cargar_lote_sindicato.py` sorteaba la provincia al azar —gente de la seccional
de Rosario viviendo en Córdoba— y `demo_encuestas.py` la tenía escrita a mano).
Un padrón de demo sin esos campos mostraría justo lo que la app ya no permite
cargar. Se verificó sobre una base nueva: 305 afiliados, 0 incompletos, cada
uno en la zona de su seccional.

### Modales que se mueven

"El modal tiene ubicación fija y creo sería útil poder moverlo al menos en
desktop (aplica a todos los modales)."

`static/modales.js`, 130 líneas, cargado por las ocho plantillas que tienen
modales. Las decisiones que importan:

- **Un solo archivo compartido.** El "aplica a todos" es la parte difícil: con
  el arrastre repetido en cada plantilla, se mueven tres modales y el cuarto no,
  y nadie se entera hasta que alguien lo usa en una demo. `test_modales.py`
  recorre las plantillas, se queda con las que tienen una caja de modal y exige
  que todas carguen el script — una plantilla nueva entra sola a la lista.
- **Delegado en `document`**, no enganchado al abrir: los modales de esta app se
  llenan con innerHTML (el detalle de un trámite, el "Ver" del panel), así que
  cualquier enganche por elemento se perdería en el siguiente repintado.
- **El agarre es el encabezado**, nunca la caja entera: si se moviera al
  arrastrar cualquier parte, no se podría seleccionar texto adentro. Los modales
  sin encabezado (el "Acerca de", el "Ver" del Panel Sindical) se agarran del
  título.
- **Entra entero en la ventana.** La primera versión dejaba asomar solo un
  borde, y arrastrándolo a la derecha la X de cerrar quedaba afuera: el modal
  seguía ahí y no había forma de cerrarlo sin volver a traerlo. Se vio en el
  navegador, no razonándolo.
- **La posición se resetea al cerrar** (un `MutationObserver` sobre la clase del
  fondo). Si quedara guardada, quien lo dejó en un costado lo abre la próxima
  vez ahí y no entiende por qué "apareció raro".
- **Solo con mouse y pantalla ancha** (`(min-width: 700px) and (pointer: fine)`,
  la misma condición en el script y en el cursor de marca.css). En un teléfono
  el modal es una hoja pegada al borde inferior: moverla no tiene sentido y
  competiría con el scroll del contenido.
- `.modal-recibo-card` NO está en la lista de cajas y hay un test que lo
  verifica: es una tarjeta de contenido ADENTRO de un modal, y si entrara,
  `closest()` la encontraría primero y el arrastre movería el contenido en vez
  de la ventana.

No toca el HTML de ninguna plantilla: si el archivo no carga, los modales
siguen funcionando como siempre, quietos.

### Verificado

86 archivos de la suite en verde (los 84 de antes más `test_domicilio_obligatorio.py`
y `test_modales.py`), 13 robots de e2e (los 11 de antes más
`e2e/test_robot_modales.py`) y 31 comprobaciones en un Chromium de verdad sobre
la demo cargada desde cero: el asistente de seccional contra Georef y Nominatim
reales (San Martín 850 de Rosario resuelve `exacta`), una dirección inexistente
que cae en `aproximada` y NO deja continuar, el registro de punta a punta con su
domicilio apareciendo después en el perfil, y el arrastre de dos familias de
modal en escritorio y su ausencia en teléfono.

Quedó anotado un defecto **ajeno a este cambio** que apareció corriendo los
robots: `static/dashboard.js` arma el rango de fechas del Panel Sindical con el
reloj del NAVEGADOR (`new Date()`), y el servidor lo valida contra la hora de
Buenos Aires (`dashboard.parsear_filtros` rechaza un `hasta` futuro). Un
dispositivo adelantado respecto de Argentina pide mañana, cada endpoint del
panel devuelve 422 y todos los indicadores quedan en "—" sin ningún aviso. Es
la misma clase de bug que `fechas.py` resolvió en el backend, pero del lado del
cliente.

## Mapa de participación por seccional en Encuestas (2026-09-13)

Pedido de Sd: el mismo mapa que tiene el Panel Sindical, pero en el dashboard
de una encuesta, con burbujas cuyo tamaño sea la cantidad de participantes. Y
un detalle estético propio: que el círculo lleve el logo del sindicato de fondo,
que el BORDE tenga el color de la escala de participación y que al seleccionar
una seccional el RELLENO pase al color de selección del panel (fucsia por
default).

### La burbuja, y por qué cambió también el mapa del Panel

Pidió "la misma estética" que el mapa del Panel **y** el detalle nuevo. Las dos
cosas juntas solo se sostienen de una manera: que la burbuja sea UNA, compartida
por los dos mapas. Si el detalle entrara solo en el mapa nuevo, la frase "la
misma estética" quedaría falsa el mismo día. Así que `MapaMT.burbuja` vive en
`mapa.js`, el CSS en `marca.css`, y el mapa del Panel Sindical pasó a usarla.

Eso obligó a un cambio de fondo en el Panel: sus marcadores eran
`L.circleMarker`, y **un círculo de SVG no puede llevar una imagen adentro** sin
armar un `<pattern>` por marcador. Las burbujas son ahora `divIcon` —HTML, con
el logo como `background-image` en una capa propia para poder atenuarlo—. De
paso se movió lo que el mapa reparte en tres significados:

| | antes (Panel) | ahora (los dos) |
|---|---|---|
| tamaño | cantidad | cantidad |
| **borde** | blanco, o destacado si estaba elegida | **color de la escala** |
| **relleno** | color de la escala | **blanco, o destacado si está elegida** |

El intercambio no es cosmético: el destacado es, por regla del proyecto
(docs/DASHBOARD.md §4.1), EXCLUSIVO de las selecciones activas. Con la escala en
el relleno, el color de un dato y el color de "esto está elegido" competían por
el mismo lugar. Con la escala en el borde, cada cosa tiene el suyo.

Lo que NO cambió: la escala sigue siendo fija de la app (cinco azules) y no la
marca del gremio, el diámetro sigue yendo por raíz cuadrada (lo que el ojo
compara es el área: con tamaño lineal, el doble de gente se ve cuatro veces más
grande) y el mapa sigue siendo el selector.

### De dónde salen los números del mapa nuevo

De la URNA no se puede: guarda los cortes de cada respuesta, así que sabe
cuántas llegaron etiquetadas "Rosario", pero **no a cuántos se les preguntó**.
Sin denominador no hay porcentaje de participación, que es justamente lo que el
color tiene que decir. Así que el mapa sale del **padrón fijado al publicar**
(`EncuestaParticipante`, con su bandera `respondio`), que es la misma fuente del
indicador "Participación" de arriba: los dos números cierran entre sí.

La contra, dicha en la pantalla: el padrón se cruza con `Trabajador`, o sea con
la seccional de HOY, mientras que la urna congela la seccional al responder. Si
alguien se mudó entre una cosa y la otra, la burbuja y la pastilla pueden
diferir en una persona. Es el mismo desfasaje que el encabezado de
`resultados_encuesta.py` ya documenta para todo lo que sale del padrón, y no se
puede evitar sin guardar en el padrón un dato que abriría la puerta a cruzarlo
con la urna -- que es exactamente lo que el módulo no hace.

El color va con escala FIJA de 0 a 100% y no contra el máximo observado (como
sí hace el Panel, donde las métricas son cantidades sin techo natural): una
participación del 70% tiene que verse igual de oscura con el filtro puesto que
sin él.

### Las tres reglas que hereda, sin escribirlas de nuevo

- **Es el selector, así que ignora su propio filtro.** Si lo respetara, tocar
  una burbuja dejaría el mapa con un punto y sin vuelta.
- **Pero NO ignora el filtro impuesto por alcance (N18).** Dejarlo pasar le
  mostraría a un Admin de Seccional, en un mapa, cuánta gente participó en las
  seccionales que no le tocan. Con el recorte impuesto las burbujas además no
  filtran: no hay nada que elegir, igual que la pastilla queda deshabilitada.
- **Tocar una burbuja llama al MISMO `alternar('seccional', ...)` que la
  pastilla.** No hay un segundo estado de selección que se pueda desincronizar:
  se toca la burbuja y se prende la pastilla, porque son la misma cosa.

Y una que no hereda sino que decide: una seccional **sin nadie en el padrón de
esa encuesta no aparece**. Cero de cero no es 0% de participación, es una
encuesta que no le llegó; dibujarla apagada diría algo que no pasó. Las que sí
participaron pero no están ubicadas se nombran abajo del mapa, con sus números,
para que los totales cierren.

### Un solo idioma de selección por pantalla

El dashboard de encuestas usaba el color de APOYO de la marca para las
selecciones (pastillas elegidas, rango del calendario) y el Panel Sindical usa
el destacado. Con el mapa nuevo eso se volvía visible en la misma pantalla: al
tocar una burbuja quedaba fucsia y su pastilla verde, para la misma cosa. Así
que la pantalla de Encuestas pasó a usar el destacado en sus estados de
selección, que es lo que `Sindicato.color_destacado` significa desde que existe
("SOLO selecciones/filtros activos del dashboard"). El cromo suave de la marca
(`--enc-suave`/`--enc-borde`: el aviso de umbral, las notas del cruce) se quedó
donde estaba, con dos variables nuevas (`--sel-suave`/`--sel-borde`) para lo que
sí es selección: un aviso pintado del color de las selecciones diría que está
seleccionado.

### El globo que se iba solo

Primer intento: el globo (popup) se abría al tocar la burbuja. Pero tocar una
burbuja recarga el tablero, y el repintado destruye los marcadores con su globo
adentro: se abría y se cerraba en el mismo clic, justo cuando la persona quería
leer los números de la seccional que acababa de elegir. Ahora el globo se abre
al pasar el mouse, el clic filtra, y cuál está abierto se recuerda entre
repintados. Se encontró mirando la pantalla, no razonándolo.

### Verificado

15 comprobaciones en un Chromium de verdad sobre la demo cargada de cero
(burbujas de tamaños distintos, el logo adentro, los bordes con tres tonos de la
escala, el relleno fucsia al seleccionar, la pastilla que se prende sola, el
tablero que se recalcula, y el mapa del Panel dibujando las mismas burbujas),
10 tests nuevos en `test_encuesta_mapa.py` (participación por seccional,
aislamiento con el mismo CUIL en dos gremios, N18, sin ubicar, sin corte de
seccional, y que el mapa siga viajando cuando el umbral esconde las preguntas)
y dos robots de e2e, el del Panel actualizado a las burbujas nuevas y uno nuevo
para el mapa de la encuesta.

## El Panel Sindical en blanco: la fecha la ponía el navegador (2026-09-13)

Apareció corriendo los robots de e2e, no en producción: `test_humo_dashboard`
fallaba porque `#v-recibos` se quedaba en "—". El robot estaba bien; el panel
estaba mal.

**Qué pasaba.** `static/dashboard.js` armaba su "hoy" con `new Date()` —el
reloj del DISPOSITIVO— y de esa constante cuelga todo el rango del panel: el
período por default, los presets, el tope del calendario y la validación de la
URL. Del otro lado, `dashboard.parsear_filtros` valida contra la hora de
Buenos Aires (`fechas.hoy()`) y **rechaza un `hasta` futuro**. Cualquier
dispositivo adelantado respecto de Argentina pedía "mañana", los nueve
endpoints del panel devolvían **422**, y el JS se comía el error en un `catch`
que solo sacaba la clase "cargando": los indicadores quedaban en "—" para
siempre, sin un cartel, sin nada en pantalla. Parecía que no había datos.

A quién le pasa: a cualquiera con el dispositivo en un huso al este de
Argentina, a quien tenga el reloj mal puesto, y a todos entre las 21 y la
medianoche si el dispositivo está en UTC. Silencioso, que es lo peor: nadie
reporta "me dio 422", reportan "el panel no anda".

**Es el mismo defecto que `fechas.py` arregló en el backend el 2026-09-11**
(Render corre en UTC, `date.today()` cambia de día a las 21:00 de Argentina),
pero del lado del cliente. La regla vale para los dos lados: **la fecha la
decide el servidor**.

### El arreglo

La página ya la renderiza el servidor, así que la fecha viaja con ella:
`data-hoy` en el `<main>` (de `fechas.hoy_texto()`), y `HOY` sale de ahí. Una
sola línea de JS cambia y con ella el rango entero, los presets, el calendario
y la guarda de la URL. Queda un `new Date()` de respaldo por si la plantilla no
manda el dato —ahí vuelve el problema viejo, pero es mejor que un panel que no
arranca—, y un test cuenta los `new Date()` del código (sin comentarios) para
que no se cuele otro.

### Y la red, que importa más que el arreglo

El bug era invisible, y eso es lo que lo hizo durar. Ahora el `detail` que
manda el servidor se lee y se muestra: en un cartel ámbar arriba de los KPIs
—donde están los filtros que hay que corregir— y en el error de cada panel. Se
probó con el caso que el JS SÍ deja pasar: un rango de más de 366 días, que el
servidor rechaza y que antes también dejaba la pantalla muda. Ahora dice "El
rango máximo es de 366 días".

Los KPIs no son un `[data-panel]`, así que su error no se veía en ningún lado:
por eso el cartel es global y no solo por panel.

### Verificado

En un Chromium con el huso horario de **Kiritimati (UTC+14)**, que hoy es un
día más que Buenos Aires: el navegador cree que es el 14 y el servidor dice el
13. Con el arreglo, ningún endpoint rechazado y los indicadores con datos; y
pidiendo a mano lo que el panel viejo habría pedido con ese reloj, el servidor
contesta 422 "'hasta' no puede ser una fecha futura" — o sea que el bug era
exactamente ese. Más dos tests en `test_dashboard.py`: que la página le dé al
navegador la fecha del servidor, y que un rango rechazado diga por qué y la
pantalla tenga dónde decirlo.

## Encabezado normalizado en toda la suite (2026-09-13)

Pedido de Sd: "en todas las pantallas tenemos el logo del sindicato y el de
Colm3na, además en algunas el nombre del sindicato en texto y también en
algunas el título de la pantalla". Antes de proponer nada se relevaron las
doce pantallas leyendo el CSS de cada plantilla, con capturas de la app
corriendo (La Bancaria, con un logo de demo cargado para el relevamiento).
**Ninguna regla se repetía dos veces seguidas:**

- **El orden se daba vuelta**: en las portadas iba sindicato → Colm3na; en
  los paneles internos, Colm3na → sindicato. Dos pantallas seguidas del
  mismo recorrido.
- **Cuatro medidas del mismo logo**: `76×76` (portadas), `76×220` (paneles),
  `61×170` (Panel Sindical), `46×46` (Notificaciones). En la caja cuadrada
  un logo horizontal --el caso típico de un sindicato-- entraba escalado a
  76px de ancho e ilegible; dos pantallas después ocupaba un tercio del
  ancho de la ventana.
- **Colm3na aparecía en 6 de 12 pantallas**, y en la portada del afiliado se
  la veía MÁS GRANDE que el logo del gremio, que es de quien es la app.
- **El nombre del sindicato se decía dos veces**: en las portadas iba en
  texto al lado de un logo que ya lo dice (y el Panel Sindical llegaba a
  poner "La Bancaria · Mi Trabajo" debajo del logo de La Bancaria); en los
  paneles, en cambio, era excluyente (o el logo o el nombre).
- **El título también**: "Panel de administración" y "Notificaciones"
  estaban en el encabezado y otra vez como título del cuerpo.

Se le presentaron a Sd tres opciones, cada una aplicada sobre el DOM real de
cada pantalla (no sobre una maqueta) y fotografiada: **A** una sola franja
con "operado por" a la derecha; **B** encabezado solo del sindicato y
Colm3na al pie; **C** cinta de plataforma + encabezado del sindicato. Eligió
la **C con dos cambios**: la colmena a la DERECHA de la cinta, y el texto
"Mi Trabajo" borrado del encabezado.

**Cómo quedó.** `templates/_encabezado.html` + `static/encabezado.css`:

    CINTA   [ rol del panel ]                          [ Colm3na ]
    BARRA   [ logo del sindicato ]                     [ pantalla ]

- La cinta del **afiliado va sin texto de rol**: ahí la plataforma firma con
  el logo, no con la palabra. En las otras tres apps lleva el rol.
- El logo del sindicato va con **altura fija (52px; 38 en mobile) y ancho
  libre** hasta 300px. Ese es el fix real del logo ilegible: el problema no
  era el tamaño sino la caja cuadrada.
- **El nombre del sindicato en texto solo si no hay logo cargado**, y
  entonces ES el logotipo (condensada sobre un filo de acento, no un
  cuadrito de iniciales).
- El **título de la pantalla se dice una sola vez**: salió el `<h1>`
  "Notificaciones" del cuerpo, el kicker "Panel de administración" de la
  portada del admin, el de empleador y el de plataforma. En los paneles con
  pestañas lo escribe el JS al cambiar de pestaña (verificado a mano en las
  tres: trabajador, admin y plataforma), así el encabezado dice siempre
  dónde estás y no una pestaña fija que dejó de ser cierta.

**Por qué el CSS no fue a `marca.css`.** Primer intento: el bloque adentro
de `marca.css`. La app del trabajador quedó con la colmena a tamaño natural
ocupando la pantalla entera. Causa: **`trabajador.html` y `empresa.html` NO
cargan `marca.css`** (lo dicen en su propio comentario: tienen su CSS
propio; un grep de "marca.css" las listaba igual porque el nombre aparece en
esos comentarios). De ahí `static/encabezado.css`, que carga **el propio
parcial** con un `<link>` en el cuerpo: así una pantalla nueva no puede
quedarse sin el estilo por olvido, y ninguna var() se da por sentada (todas
llevan valor de respaldo, y la condensada se declara también ahí).

**Lo que se conservó:** el cromo "Hilo" de admin/empresa/plataforma (degradé
+ grano + filo ámbar) pasó de `header` a `.marca-barra`, con el filo en
`.marca-enc` para que recorra las dos franjas; el degradé propio del Panel
Sindical y el de Resultados de encuesta, con su ancho de 1280/1180px; la
fecha del rango del Panel Sindical (`enc_fecha`, con los mismos ids que
espera `dashboard.js`); y el "Volver" de Notificaciones, Convenio y
Resultados (`enc_volver`).

**Fuera del sistema, a propósito:** los tres ingresos (ahí el logo grande de
plataforma ES la identidad de la pantalla) y las herramientas internas del
equipo (`/entornos`, su PIN, el informe de carga y el detalle de test): no
tienen sindicato y no son pantallas de la suite.

**Nota de proceso.** El relevamiento y las tres opciones se hicieron sobre
una copia local que estaba **90 commits atrás** de `origin/main` (no se
había traído lo de georreferenciación, encuestas y entornos). Al ir a subir
la versión, `git fetch` lo mostró: `origin/main` tenía Admin 0.41.02 y la
copia local 0.29.06. Se guardó el trabajo en una rama, se actualizó `main` y
el cherry-pick entró limpio --los once bloques de encabezado seguían
idénticos allá--, más `encuesta_resultados.html`, que es la pantalla nueva
que sí pertenece a la suite. Confirma la regla de FLUJO.md de mirar
`origin/main:version.py` ANTES de escribir el número: esta vez avisó de algo
bastante más grande que un número.

## "Mi Trabajo" sale de la interfaz: la plataforma es Colm3na (2026-09-13)

Pedido de Sd el mismo día que el encabezado normalizado, y por el mismo
motivo: el nombre viejo del producto quedaba suelto por todos lados aunque
la marca --logo, manifest de la PWA, ícono del celular-- ya dijera Colm3na.

Qué cambió, todo lo que ve una persona:

- **Los `<title>`**, con el patrón que las pantallas nuevas ya usaban:
  `<pantalla> — {{ sindicato }}` donde hay sindicato ("Revisá tu recibo —
  La Bancaria", "Panel de administración — La Bancaria"), y
  `Colm3na — <pantalla>` donde no lo hay (los tres ingresos, el selector de
  sindicato, plataforma, verificación de credencial). Es la misma regla del
  encabezado: si la pantalla es de un gremio, manda el gremio.
- **La banda MRZ** de los cuatro ingresos: `MITRABAJO<<TRABAJADOR<<ACCESO`
  pasó a `COLM3NA<<...`, con dos `<` más para conservar el largo (es un
  adorno de documento: si se acorta, se nota).
- **`alt="Mi Trabajo"`** en los ocho logos de plataforma → `alt="Colm3na"`.
- **Textos**: "Es la marca de «Mi Trabajo» en sí" y "Logo y colores de Mi
  Trabajo" (panel de plataforma), "Verificado por Mi Trabajo contra los
  datos de {sindicato}" (verificación pública de credencial), el título por
  defecto de una notificación push (`sw.js`) y el título de la app FastAPI
  (que se ve en `/docs`).

**Dos cosas que aparecieron al hacerlo:**

1. **La demo anónima tomaba prestado un sindicato.** `GET /` pasaba
   `db.nombre_sindicato()` --el PRIMERO de la base-- a una pantalla que su
   propio comentario describe como "sin sindicato real". Con el encabezado
   viejo pasaba medio inadvertido; con el nuevo, el nombre de un gremio
   cualquiera quedaba grande en la barra y, desde este cambio, también en la
   pestaña del navegador (en la base local: "ZZZ Medición Dashboard"). Ahora
   va vacío y el encabezado firma con el logo de Colm3na.
2. **Colm3na aparecía dos veces** donde la marca principal ES la plataforma
   (ese mismo `/`, y el panel de plataforma): el logo grande en la barra y
   otra vez chiquito en la cinta. La cinta ya no lo repite ahí, y si además
   no hay rol que mostrar --la demo anónima-- directamente no se dibuja, en
   vez de dejar una franja oscura vacía.

**Logo del sindicato +20%** (pedido de Sd en el mismo bloque): 52→62 px de
alto en escritorio (ancho libre hasta 360) y 38→46 en móvil (hasta 192). El
logotipo tipográfico, el que se usa cuando el sindicato no cargó logo, creció
igual (30→36 y 22→26) para que las dos formas del mismo lugar sigan pesando
lo mismo.

Lo que NO se tocó: `CLAUDE.md`, `README`, docstrings y comentarios de código
siguen diciendo "Mi Trabajo" donde hablan del producto. Es documentación
interna, no interfaz.

## Costo en dólares de cada llamada a la IA, y cambiar de modelo desde el panel (2026-09-13)

Pedido de Sd sobre la solapa "Uso de IA" de `/plataforma`: que cada fila
diga **cuánto costó en dólares** (tokens por el precio de ese modelo), cuánto
**tardó** y a qué hora se hizo; y poder **cambiar de modelo** por uno más caro
o más barato y **hacer pruebas**.

**Lo que había.** `UsoIA` guardaba sindicato, CUIL, tipo, modelo, tokens de
entrada y de salida y la fecha al minuto — y nada más. El comentario de la
tabla decía, textual, "tokens crudos, sin precio -- cambia según el plan/
modelo": el precio se había dejado afuera a propósito. Los modelos eran tres
constantes fijas en tres módulos (`extractor.MODELO`,
`rag.MODELO_RESPUESTA`, `asistente.MODELO`).

**Dos decisiones de Sd, preguntadas antes de escribir código:**

1. **Selector + banco de pruebas**, no uno de los dos. El selector solo dice
   cuánto sale cada modelo; lo que decide si conviene bajar de modelo es
   leer el MISMO recibo con dos modelos y comparar. Un listado de consumo
   nunca puede contestar eso, porque cada fila es un recibo distinto.
2. **El listado sigue con los tres tipos de hoy** (recibo, aportes,
   aprendizaje). Se le ofreció sumar el bot del convenio y el Asistente, que
   hoy no registran en `UsoIA` —y el convenio es el que corre en
   `claude-opus-5`, el más caro por token— y la respuesta fue que no. Queda
   dicho para que no se lea como olvido: **el total de la pantalla es el
   gasto de la lectura de recibos, no el gasto de IA de toda la plataforma.**

### El precio se congela, el costo se deriva

La columna nueva de `UsoIA` no es `costo_usd`: son `precio_entrada` y
`precio_salida`, los dólares por millón de tokens que regían **en el momento
de la llamada**. El costo se calcula al mostrarlo. Es el mismo criterio que
"se guardan hechos, no derivados" de las validaciones de Trámites (fecha de
afiliación, no antigüedad): el precio es un hecho de ese día, el costo es una
multiplicación. La consecuencia práctica es la que importa: **actualizar la
lista de precios no reescribe el gasto de los meses anteriores**, y el número
sigue siendo re-derivable y auditable años después.

El precio lo copia `db.registrar_uso_ia()` adentro, no se lo pasa quien
llama: así ningún punto de registro puede olvidarse de congelarlo.

Las filas anteriores a la migración quedan en 0, que **no es "salió gratis"**:
la pantalla las muestra estimadas con los precios de hoy, en bastardilla y
con asterisco, y el pie de la tabla lo explica. Lo mismo para un modelo que
no está en el catálogo (una fila vieja de un modelo retirado): "—", nunca
"US$ 0,00". La diferencia entre "no sé" y "cero" es la única que importa en
una pantalla de costos.

`precios_ia.py` es el catálogo y las cuentas, módulo puro (no importa `db`),
con los precios en `data/precios_ia.json`. **A diferencia de
`render_planes.py`, estos precios se copian a mano**: no hay una página de
Anthropic que se pueda leer con un script sin inventar. Por eso el archivo
guarda `fuente` y `leido`, y la pantalla muestra la fecha de lectura al pie —
un precio sin fecha no se puede auditar. Al 2026-06-24: Opus 5 US$ 5/25,
Sonnet 4.6 US$ 3/15, Sonnet 5 US$ 2/10, Haiku 4.5 US$ 1/5 por millón.
No contempla descuentos de cache ni Batch: el extractor no usa ninguno de los
dos, así que para lo que hoy se registra el número es el real.

### La duración se mide alrededor de la llamada, no del request

`extractor._uso()` recibe los milisegundos medidos con `perf_counter()`
**pegados al `client.messages.create`** y nada más. Pasar un PDF a imagen
tarda lo mismo con cualquier modelo; metido adentro, comparar dos modelos en
el banco de pruebas diría cualquier cosa.

### Cambiar de modelo

Tres columnas nuevas en `ConfiguracionPlataforma` (`modelo_recibos`,
`modelo_convenio`, `modelo_asistente`). **Vacío significa "el que está
escrito en el módulo"**, no "ninguno": el default sigue viviendo en el
código, en un solo lugar, y la configuración solo existe para apartarse de
él. `db.modelo_ia(uso)` resuelve una cosa o la otra, y se lee **en cada
llamada** — Render corre un worker por núcleo, así que una variable en
memoria quedaría distinta en cada uno.

Cómo llega el modelo a cada módulo, y por qué de dos formas distintas:
`extractor.py` **no importa `db`** (es el único de los tres que no lo hace, y
conviene que siga así), entonces `main` le pasa el modelo como tercer
argumento a `extraer`/`extraer_aportes`. `rag.py` y `asistente.py` ya
importan `db` y lo leen ellos. En el Asistente se resuelve **una vez por
pregunta** y no por vuelta del bucle: cambiar de modelo en el medio tiraría
el cache del prompt de sistema y mezclaría dos modelos en una respuesta.

`db.set_modelos_ia()` **ignora** cualquier id que no esté en el catálogo y
deja el uso como estaba. Un id mal escrito no falla en el panel: falla con un
400 de la API en la pantalla del trabajador que sube el recibo, que es el
peor lugar posible para enterarse.

Dos cosas que quedaron atadas al mismo hilo:
`chequeo.py --api` ahora prueba **el modelo elegido** y no uno fijo (si
alguien elige uno que la cuenta no puede usar, el autodiagnóstico tiene que
enterarse ahí), y `probar_asistente.py` dejó de tener sus propios
`PRECIO_ENTRADA`/`PRECIO_SALIDA` escritos a mano — usa el catálogo, y su
informe nombra el modelo que de verdad corrió. Con dos listas de precios en
el repo, una de las dos envejece sin que nadie lo note.

Lo que **no** cambia con el selector: el OCR de un convenio escaneado
(`rag.py` usa `extractor.MODELO` al indexar) sigue con el modelo de origen.
Es una operación puntual del alta de un convenio, no del uso diario, y la
pantalla lo aclara para que no se lea como un olvido.

### El banco de pruebas

`POST /plataforma/probar-modelos`: un archivo, dos a cuatro modelos, y una
tabla con una columna por modelo — costo, tiempo, tokens, y qué leyó cada
uno. Tres decisiones:

- **En paralelo** (`asyncio.gather` sobre `run_in_threadpool`). Van a la
  misma API y no se estorban; en serie, cuatro modelos serían casi un minuto
  colgado del navegador, con riesgo de corte del proxy.
- **Cada lectura se registra en `UsoIA` con tipo `"prueba"`** y sin
  sindicato. Es gasto real: si no se registrara, el total de la pantalla
  dejaría de ser el gasto real justo por usar la pantalla. Filtrable aparte
  para que no ensucie el consumo de producción.
- **Un modelo que falla no tumba la comparación** (`return_exceptions=True`):
  vuelve con su error al lado de los que sí contestaron, que es justo lo que
  hay que ver. El error va crudo a la vista — lo lee quien administra la
  plataforma, y "modelo inexistente" y "sin cuota" se arreglan de maneras muy
  distintas.

`extractor.resumen_comparable(tipo, datos)` decide QUÉ se compara: período,
formato, CUIL, CUIT del empleador, líneas, aportes, los tres totales
impresos y la confianza (o, en un comprobante de ARCA, CUIL, desde, hasta,
meses leídos y meses con algo impago). Vive en `extractor.py`, al lado de los
dos `ESQUEMA`, porque es conocimiento de la forma de lo que devuelve el
modelo: si mañana cambia un campo del esquema, el resumen que lo compara está
en la misma pantalla. Lo que difiere del primer modelo que contestó sale en
rojo, y el JSON completo de cada lectura queda a un clic — la pantalla dice
que coincidir no prueba que esté bien, prueba que leyeron lo mismo.

### La pantalla

La solapa se abrió en **tres sub-pestañas** con namespace propio
(`.ia-subtab`, mismo criterio que `.enc-subtab`): Consumo y costo, Modelos,
Banco de pruebas.

Los totales (llamadas, costo total, promedio por llamada, tiempo mediano,
tokens) y el **desglose por modelo** se calculan **en el navegador, sobre las
filas visibles**, para que acompañen a los filtros: mirar cuánto sale un
modelo con el filtro de un sindicato puesto y que el total siguiera siendo el
global sería peor que no tenerlo. No hay lógica duplicada: el costo DE CADA
FILA lo calcula el servidor —el único que sabe qué precio tenía congelado esa
llamada— y el JS solo suma números ya hechos. El promedio se divide por las
llamadas **con costo conocido** y no por todas: con las viejas adentro daría
un promedio más bajo que el real.

El desglose por modelo es la tabla que contesta la pregunta del sprint. En la
prueba con datos sintéticos: Sonnet 4.6, US$ 0,0148 y 8,6 s por llamada;
Haiku 4.5, US$ 0,0043 y 5,6 s. Tres veces y media más barato y más rápido —
si lee bien, que es lo que dice el banco de pruebas y no esta tabla.

Las dos tablas (nueve columnas la de detalle) van dentro de `.tabla-ancha`,
que se desliza sola en un teléfono en vez de desbordar la página.

### El mock no cuenta como una llamada (mismo día, apenas desplegado)

Sd probó en Pruebas y avisó: "todos tardaron 15 seg" y "ninguno muestra los
tokens". Era `MOCK_EXTRACTOR=1`, que había quedado prendido en
`mitrabajo-pruebas` desde la campaña de tests de carga (`carga/README.md`
paso 1). Con el mock, `extraer()` no llama a la API: duerme
`MOCK_EXTRACTOR_LATENCIA` (15 s por default) y devuelve cero tokens.

No era un error del panel, pero el panel se prestó: mostraba 15,0 s clavados
en cada fila como si fueran una medición. Tres cambios:
`extractor._uso_mock` devuelve `duracion_ms=0` (el sleep no es una
medición); `db._uso_ia_fila` ignora la duración guardada de cualquier fila
con modelo `mock`, así las que ya están en Pruebas dejan de contaminar el
tiempo mediano sin migrar nada; y el modelo se nombra entero,
"mock — no hubo llamada a la API", para que una fila sin tokens ni costo se
explique sola. El costo ya salía "—" —`mock` no está en el catálogo de
precios a propósito— y los agregados ya ignoraban lo que no tiene costo, así
que el promedio nunca estuvo mal.

### El 502 y el JSON cortado: dos síntomas, una sola causa real

Probando el banco en Pruebas aparecieron dos cosas seguidas. La primera fue
un "el servidor contestó 502", y la primera explicación que di fue **la
equivocada**: supuse que `extraer()` prepara el archivo adentro, así que N
modelos en paralelo lanzaban N conversiones del mismo PDF (poppler a 150
dpi + la imagen en RAM + el base64, todo por N) y tumbaban el worker, que en
Pruebas es medio núcleo y 512 MB.

Los logs de Render lo desmintieron. Cero `SIGKILL`, cero `Out of memory`, y
los cuatro 502 del día (18:30:22, 18:30:32, 18:31:27, 18:31:35 UTC) caen
exactamente sobre dos `Instance ... restarted` a las 18:30:40 y 18:31:41 --
dos de ellos con `responseTimeMS=1` y `260`, o sea que la app no estaba, no
que tardó. Eran los reinicios que dispara **cambiar una variable de
entorno**: Sd estaba sacando `MOCK_EXTRACTOR` justo en esa ventana. Nada que
ver con el código. Queda anotado porque la moraleja es cara: sobre un
entorno desplegado, la hipótesis se confirma con el log antes de contarla
como causa.

El cambio de `preparar_imagen()` quedó igual, pero por lo que de verdad es:
multiplicar por N la única parte cara en CPU y memoria del camino no tiene
sentido. La ruta prepara el archivo una vez y se lo pasa a las N llamadas,
que comparten la MISMA cadena y solo esperan en la red. De paso, un PDF
ilegible falla al prepararlo, antes de gastar un crédito, en vez de fallar N
veces adentro de la API.

**La segunda sí era un defecto, y de los caros.** Con cuatro modelos, Opus 5
y Sonnet 5 volvieron con `JSONDecodeError: Unterminated string`: el JSON
venía cortado a la mitad. Los dos que sí anduvieron gastaron 1.790 y 1.744
tokens de salida contra un `max_tokens` de **2.000** -- el modelo que corre
en producción ya pasaba al 89% del tope, así que un recibo un poco más largo
se cortaba igual, con Sonnet 4.6 y sin que nadie se enterara de por qué.
Opus 5 y Sonnet 5 lo cruzaron primero porque **razonan por default** y ese
razonamiento sale del mismo presupuesto que el JSON.

Cuatro cambios: `MAX_TOKENS` a 8.000 (el tope no se paga, se paga lo
generado); `effort: low` SOLO para los dos que razonan
(`MODELOS_QUE_RAZONAN`), dejando intacta la llamada de los que no -- uno de
ellos es el que hoy corre en producción y no se cambia a ciegas lo que anda;
`_parsear()` mira `stop_reason` y explica que se cortó, en vez de tirar un
`JSONDecodeError` que no dice nada; y `ErrorLectura` se lleva el `uso`
adentro para que **una lectura que falló al interpretarse no pierda lo que
costó** -- esas dos llamadas se pagaron y no figuraban en ninguna tabla, que
es exactamente lo que un panel de costos no puede hacer.

Queda dicho para la próxima: en este proyecto el paralelismo está para
esperar en la red, no para hacer cuentas; y un `max_tokens` que el trabajo
real roza al 89% no es un tope, es una bomba de tiempo.

### Comparar los totales no alcanza: la tabla línea por línea

La primera corrida con los cuatro modelos andando dio el resultado que
justifica todo el módulo. Mismo recibo, en paralelo: período, formato, CUIL,
17 líneas, remuneraciones, descuentos, neto y confianza **idénticos en los
cuatro**. Y una sola celda distinta: "Aportes del trabajador", 4 / 5 / 4 / 6.

Esa celda no es descriptiva. `tipo: "aporte_trabajador"` alimenta
`retencion_sindical` (validador.py), que es la base del tope del 2% del art.
133 --la advertencia de retención en exceso que ve el afiliado-- y del número
que el afiliado le manda al sindicato como prueba de afiliado cotizante (art.
21 bis). Una línea solo mueve ese número si además matchea un concepto con
`categoria_sindical` de convenio o afiliación, así que el impacto es
condicional; pero es una cifra con peso legal, no un contador.

El problema era que la pantalla mostraba el CONTEO y no CUÁLES líneas, así
que para saber quién tenía razón había que abrir dos JSON y leerlos a mano.
`extractor.comparar_lineas()` arma ahora la tabla: una fila por línea
--código, descripción, importe-- y una columna por modelo con cómo clasificó
esa línea, en rojo lo que difiere del primero. Arriba, el número que
importa: "2 de 17 líneas se leyeron distinto". Con un tilde para ver solo
esas.

**Las líneas se emparejan por código (o descripción) normalizado, nunca por
posición.** Si un modelo se saltea una línea, por posición quedaría todo lo
que sigue corrido y la comparación sería un muro de rojo que no dice nada; y
un modelo escribe "JUB." donde otro escribe "JUB". Un código repetido en el
mismo recibo tampoco pisa al anterior.

**Y el CUIT con guiones dejó de ser una diferencia.** En esa misma corrida,
Sonnet 5 devolvió `30-44464097-5` donde los otros tres devolvieron
`30444640975`. Es el mismo CUIT: la app lo normaliza en los cuatro lugares
donde lo usa (`validador.validar` antes de matchear conceptos por empleador,
`cuil_no_coincide`, `dashboard.campos_analiticos` y las rutas de `main`).
Marcarlo en rojo era gritar por algo que no cambia nada, y el rojo pierde
valor si salta por cosmética. Ahora `_dato()` lleva un campo `comparar`
aparte del que se muestra: se compara el número, se muestra lo que devolvió
el modelo.

De la misma corrida, dos datos para el archivo. El costo por recibo fue Opus
5 US$ 0,0695, Sonnet 4.6 US$ 0,0382, Sonnet 5 US$ 0,0295 y Haiku 4.5
US$ 0,0123; los tiempos, 15,7 / 27,4 / 14,4 / 16,5 s, con Sonnet 4.6 y Haiku
repitiendo el mismo número en dos corridas distintas. O sea que **el modelo
que corre en producción es el más lento de los cuatro y el segundo más
caro**, y Sonnet 5 le gana en las dos cosas leyendo igual. Y un detalle que
no se ve en la lista de precios: la MISMA imagen mide 5.458 tokens de
entrada para Opus 5 y Sonnet 5 y 3.596 para Sonnet 4.6 y Haiku --dos
familias de tokenizador--, así que un precio por token más barato no
garantiza una llamada más barata.

### El primer recibo de verdad, y lo que encontró

La tabla línea por línea se estrenó con un recibo real y devolvió tres
divergencias, las tres del mismo modelo:

1. **Un dígito mal leído en el código.** Haiku leyó `128-001` donde los otros
   tres leyeron `126-001` -- misma descripción (puntuada distinto: "TITULO
   UNIV/TERC.LAUDO15/91" contra "TITULO UNIV./TERC LAUDO15/91") y el mismo
   importe, 892. En este proyecto el código es la clave con la que
   `validador.matchear` busca el concepto en el catálogo del sindicato; si no
   da, cae a la descripción normalizada, así que el daño depende de que el
   catálogo tenga el alias. Lo que no depende de nada es el otro efecto: un
   código fantasma se propone como concepto nuevo en Aprendizaje.
   Sd puso el error en escala en el mismo momento: **el código no es una
   clave confiable entre empleadores, porque cada empleador le pone el que
   quiere** -- solo pesa mirando recibos de uno solo. Queda anotado en
   BACKLOG.md para la V2 del motor.
2. **PAMI clasificado como jubilación.** `38-001 APORTE PERSONAL I.N.S.S.J.Y
   P.` es el aporte de la Ley 19.032; los otros tres le pusieron
   `categoria_universal: "pami"` y Haiku, `"jubilacion"`. Esa categoría es la
   RED DE SEGURIDAD de `validador.matchear`: solo entra en juego cuando la
   línea no matcheó por código ni por descripción, y ahí matchea contra el
   concepto genérico. O sea que el error pega exactamente en el escenario
   para el que la red existe --un empleador nuevo, sin catálogo curado-- y el
   resultado sería validar el aporte de PAMI (3%) contra la fórmula de
   jubilación (11%): una discrepancia inventada en la pantalla del afiliado.
3. **Un seguro obligatorio contado como aporte.** `44-001 SEGURO OBLIGATORIO
   - DGI`, $3,80: `otro` para los tres, `aporte_trabajador` para Haiku.

Los otros tres modelos coincidieron en TODO. Con eso, Haiku queda afuera para
recibos --3,1 veces más barato y 40% más rápido no compensa tres errores de
lectura en un solo recibo-- y la elección queda entre Sonnet 4.6 (el actual)
y Sonnet 5, que en la misma corrida salió 23% más barato y 47% más rápido
leyendo igual.

**Y el hallazgo obligó a arreglar la comparación misma**: emparejando solo
por código, la línea 1 salía como DOS filas ("126-001: no la leyó" para
Haiku, "128-001: no la leyó" para los otros tres) y ninguna de las dos
mostraba el problema real, que es el dígito. Ahora el emparejado va en dos
pasadas --código primero, descripción normalizada después sobre lo que
sobró-- y lo que difiere del renglón se nombra en la celda:
"remuneracion · código 128-001". Un código o un importe distinto es tan
diferencia como una clasificación distinta; si no se nombra, la fila parece
coincidir.

**Tests**: `test_precios_ia.py`, 32 casos. Los cuatro que importan: el precio
congelado no se mueve cuando cambia el catálogo; los defaults de
`precios_ia.USOS` son las constantes de los tres módulos (fail-closed: si
alguien mueve una y no la otra, el panel mostraría "el de origen" al lado del
modelo equivocado); el modelo que elige plataforma es el que de verdad viaja
a la API; y el banco de pruebas registra lo que gasta. Se actualizaron cuatro
tests que simulaban `extraer` con dos argumentos.

## El flujo del recibo, rediseñado (2026-09-13)

Pedido de Sd: "la pantalla de recibos es pobre, los componentes están
dispersos y parecieran no tener un orden". Se relevaron los cuatro pasos con
un recibo REAL del padrón de La Bancaria --se alimentaron las mismas
funciones de render con un `ReciboVerificado.detalle` guardado, sin llamar a
la IA-- y se le presentaron tres opciones para el paso 1 y tres para el 2,
aplicadas sobre el DOM real. Eligió **A y A**, con dos cambios de texto
suyos: "Chequeo **de conceptos**" (no "contra el convenio") y la fase
"**Comparando**" a secas, porque no toda comparación es contra el convenio
--algunas son de ley.

**Paso 1 · Subir el recibo.** Antes: dos bloques sueltos, media pantalla
vacía y ninguna indicación de cómo sacar la foto. Ahora: los tres pasos del
recorrido (foto · lectura · chequeo) con el actual marcado, la tarjeta oscura
de acción, y una guía de tres consejos con su porqué. **La guía no es
decorativa**: una foto cortada, torcida o con brillo es una lectura que sale
mal, y no había nada que lo previniera.

**Dos inputs, no uno.** "Sacar foto" lleva `capture="environment"` (abre la
cámara directo en el celular) y "Subir un PDF" abre el selector de archivos.
Antes había un solo input con `capture`, así que el PDF que manda la empresa
quedaba a un rodeo de distancia. Los dos comparten `archivoElegido()` y
`limpiarElegido()` los vacía a ambos.

**Paso 2 · Mientras lee la IA.** Antes: un documento con un haz y una barra
indeterminada, en un verde (`--agua`) que no es de la marca del sindicato, y
sin decir cuánto llevaba esperando el afiliado --lo único que uno quiere
saber mirando esa pantalla. Ahora: **cronómetro real** con los segundos
corriendo en la monoespaciada tabular, aro que da una vuelta cada 45 s (no
promete un final exacto, que no tenemos: solo muestra que el tiempo corre),
la leyenda "Estamos leyendo tu recibo" y las tres fases, con la activa
latiendo. El intervalo **se limpia solo**: cada tic comprueba que el nodo
del reloj siga en el DOM y, si no está --porque la respuesta llegó y se
reemplazó el contenido--, se cancela. Las dos llamadas (leer y verificar)
usan el mismo componente con distinta leyenda.

**Paso 3 · Confirmar lo leído.** Antes, una lista larga sin jerarquía: "¿leyó
bien mi sueldo?" pesaba lo mismo que el último concepto. Ahora arriba va una
carátula con lo que hace falta para decir "sí, es mi recibo" --período en
grande, empresa y neto impreso-- y recién después los datos en grilla y el
detalle completo. `datoCelda()` marca en rojo lo que no se pudo leer, mismo
criterio que `dato()`.

**Paso 4 · Las diferencias.** Antes: "Encontramos 1 cosa(s) para revisar",
los ✓ y ✗ como caracteres sueltos --se veían de distinto tamaño según la
fuente del sistema-- y el hallazgo, lo único que la persona vino a buscar,
en un bloque gris al final. Ahora el veredicto es la primera pieza y **el
hallazgo va adentro**, con el plural resuelto ("Hay 1 diferencia" / "Hay 3
diferencias"), los tildes como SVG de línea (`IC_OK`, `IC_CRUZ`,
`IC_ALERTA`) y los totales en tarjeta propia con `tabular-nums`, para que
las cifras se alineen en columna.

Detalle que se encontró al implementar: el CSS nuevo usaba `var(--verde)`,
que **no existe en `trabajador.html`** (esta plantilla no carga `marca.css`
y define sus propias variables: el verde acá es `--agua`). Los tildes se
veían negros en vez de verdes. Es el mismo tropiezo del encabezado
normalizado, y por el mismo motivo.



## El cuelgue del Panel Sindical en Pruebas: conexiones, techos y cupo (2026-09-19)

Rama `fix/panel-conexiones`, ocho correcciones (C1 a C8), un commit cada una.
Diagnóstico y plan en `docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md`
(Cowork, 2026-09-19); prompt de trabajo en
`docs/chat/2026-09-19-prompt-code-cuelgue-dashboard.md`.

### Qué pasó

El 2026-09-18, en `mitrabajo-pruebas` con la configuración mínima (web
`0.5c-512mb`, base `0.1c-256mb`, un worker), un solo usuario cambió varias
veces el filtro de empresa del Panel Sindical sin esperar a que pintara la
selección anterior. La app dejó de responder a **todo**, incluso a un login
desde otra sesión. Reiniciar el web service no cambió nada; reiniciar
Postgres lo destrabó. Los logs mostraron cinco `QueuePool limit of size 5
overflow 5 reached, connection timed out, timeout 30.00` en 50 ms, todas desde
`run_in_threadpool`.

### La causa real (la auditoría corrigió al diagnóstico)

El documento rector atribuía el cuelgue a helpers que abrían una segunda
sesión (`_cuits_de_empresas`, `_cuil_de_afiliado`) mientras el endpoint ya
tenía una. **Era cierto, pero solo en `kpis()` y `seccionales_geo()`**: los
demás endpoints arman el WHERE antes de abrir su sesión y no anidaban. Lo que
la reproducción local mostró, trazando cada `checkout` del pool, es que había
un anidamiento peor y más general, que no figuraba en el documento:

- **`db.permisos_efectivos` abría una sesión y, con ella tomada, llamaba a
  `modulos_habilitados`, que abría otra.** Corre en **cada** ruta `/admin/*`
  (vía `exigir_sindicato` → `_exigir_permiso_de_ruta` → `tiene_permiso`), así
  que **cada request del panel retenía dos conexiones desde el primer
  instante**, con o sin filtro. Entró con Áreas V2 (2026-09-11). Con un pool
  de 10 alcanzaban cinco requests en vuelo para trabarlo.
- Con el filtro de empresa o de afiliado, `kpis()` y `seccionales_geo()`
  sumaban un tercer anidamiento; `kpis()` además leía `config_dashboard()` con
  su sesión abierta, y `detalle_notificaciones_grupo` abría una sesión extra por
  cada notificación del grupo.
- Nada tenía techo: `pool_timeout` en su default de 30 s, ni `statement_timeout`
  ni `idle_in_transaction_session_timeout`.
- Cada refresco del panel disparaba 12–13 requests juntos, y abortar el fetch
  solo cancela en el navegador: el servidor termina cada consulta igual.
- Los endpoints son `def` síncronos y comparten el threadpool (40 hilos) con
  toda la app: el panel se los comía y el login quedaba sin hilos.

Reproducción (`test_dashboard_concurrencia.py` contra `main` antes de C1): pool
de 2 sin desborde y 20 refrescos simultáneos → 12 respuestas y **228
excepciones `TimeoutError` de pool en 81 s**, con o sin filtro de empresa. Con
un pool de N y N requests, `serie-recibos` sin ningún filtro ya fallaba: eso
fue lo que delató a `permisos_efectivos`.

### Qué se cambió

- **C1 · una conexión por request.** `permisos_efectivos` lee los módulos con
  su propia sesión. `dashboard._resolver(sid, f)` traduce empresas y afiliado a
  CUITs/CUIL **una vez, antes de abrir la sesión del endpoint**, y los `_sql_*`
  solo leen `f["cuits"]` / `f["cuil_af"]` (idempotente, muta `f` en el lugar).
  Los helpers viejos se borraron. `kpis` lee la config antes de abrir su
  sesión; el destino legible de las notificaciones se resuelve con la sesión
  ya cerrada. Test: 42 pedidos (con y sin filtro de empresa y de afiliado, el
  detalle y los guardas) no superan 1 conexión tomada a la vez; contra el
  código anterior los 42 tomaban 2. Se eligió resolver en `_resolver` y no
  pasar la sesión a cada helper porque no cambia ninguna firma pública y
  `parsear_filtros` sigue siendo puro.
- **C2 · techos.** `pool_timeout=5`, `statement_timeout=15 s`,
  `idle_in_transaction_session_timeout=30 s`; pool y timeouts por variable de
  entorno (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`,
  `DB_STATEMENT_TIMEOUT_MS`, `DB_IDLE_TX_TIMEOUT_MS`). Un pool agotado
  responde 503 JSON con `Retry-After` (`E-SERVIDOR-01`); una consulta cortada
  por `statement_timeout` responde 503 (`E-SERVIDOR-02`, sale de manejar el
  `QueryCanceled` de psycopg: sin eso el techo habría vuelto un 500 genérico).
  Alembic usa `db.engine_para_migraciones()`: **sin** los techos de la app (un
  `ALTER COLUMN TYPE` sobre una tabla grande pasa de 15 s) y **con**
  `lock_timeout=5 s`. El valor de 15 s se fijó midiendo: la consulta más pesada
  (`limites_bruto`, `percentile_cont` sobre 50.000 recibos) tarda 28–34 ms con
  CPU completa (105 ms en frío), el peor endpoint 100 ms.
- **C3 · cupo.** `BoundedSemaphore` por proceso (`DASHBOARD_CUPO`, default 4;
  espera `DASHBOARD_CUPO_ESPERA`, default 2 s) alrededor de los endpoints de
  agregados y el explorador. Sin lugar → 503 `E-SERVIDOR-03` con "El panel está
  ocupado, reintentá en unos segundos.". Se toma **después** de la sesión y de
  validar los filtros. Quedan afuera el detalle, `/filtros`, el buscador de
  afiliados y el asistente. Limitación del test: `TestClient` arma un event
  loop (y un threadpool) por cliente, así que no reproduce que los 40 hilos
  sean compartidos; prueba el mecanismo que evita llegar a eso.
- **C4 · front.** `refrescar()` sale en una cola de a 4 (`enCola`,
  `MAX_EN_VUELO`), los contadores de pestañas inactivas se piden **después**
  de los paneles, debounce de 250 → 400 ms, y una tarea que espera turno en
  una ronda abortada no arranca. **Agregado que no estaba en el plan:**
  `pedir()` reintenta hasta dos veces un 503 con espera corta (700 y 1500 ms):
  con el cupo en 4, cambiar filtros rápido choca con las consultas de la ronda
  anterior que el servidor todavía está terminando, y sin reintento eso dejaba
  paneles en error. Verificado en el navegador real con el tenant de 50.000
  recibos: pico de **4** pedidos en vuelo; una ráfaga de 4 cambios dentro del
  debounce es una sola ronda de 12; cinco rondas "frenéticas" seguidas dieron
  60 respuestas 200 y ningún panel en error.
- **C5 · regresión.** El mismo test de la reproducción, parametrizado con y sin
  filtro de empresa: 240 de 240 respuestas 200 en ~4 s (antes, 12 y 228
  excepciones en 81 s).
- **C6 · health checks.** `GET /healthz` (200 sin tocar la base, `async` para
  no usar el threadpool) y `GET /readyz` (`SELECT 1` con techo de 2 s, 503 si
  no responde). El Health Check Path de Render tiene que ser `/healthz`, **no**
  `/readyz`: si Render usara el que consulta la base, una base lenta reiniciaría
  el web service, que no arregla nada y corta a los que sí se estaban atendiendo.
  Hasta hoy no había ninguno configurado.
- **C7 · carga.** `carga/k6/test3_panel.js`: 30 cambios del filtro de empresa en
  60 s con los 12 pedidos abandonados a los 250 ms (el peor caso: sin ayuda del
  front nuevo), más 20 lectores; dos fases de 60 s (base y tormenta). Criterios:
  0 respuestas 500, lectores sin fallas y p95 de la tormenta ≤ 2 × el de la base.
  `correr.sh` lo corre si está `ADMIN_CLAVE`. **No se corrió contra Pruebas**.
- **C8 · runbook.** Sección 9 de `docs/OPERATIVA.md`: evidencia primero,
  `/healthz` vs `/readyz`, la consulta de `pg_stat_activity`,
  `pg_terminate_backend` de lo que sobra y el reinicio de Postgres como último
  recurso.

### Verificación en Pruebas (mismo día, ya desplegado el PR #6)

- **Health Check Path `/healthz`** cargado en `mitrabajo-pruebas` por la API de
  Render y verificado leyéndolo de vuelta. En `mitrabajo-demo` sigue vacío a
  propósito: demo todavía no tiene `/healthz`, y cargarlo antes de promover
  haría fallar sus deploys. Se carga después de `promover_demo.py`.
- **`test3_panel.js` contra Pruebas: APROBADO.** 20 lectores + el admin de UOM
  (13 empresas, 5.000 recibos) con 30 cambios de filtro en 60 s, 360 pedidos del
  panel abandonados a los 250 ms: 0 respuestas 500, lectores sin fallas, p95 de
  los lectores 2379 ms en la base contra 2264 ms en la tormenta (razón 0,95). Los
  ~2,3 s de p95 son latencia de red + servidor chico, no de la tormenta: son
  iguales en las dos fases. Salida en `carga/log/2026-09-19_test3_panel_aprobado/`.
  Límite honesto de la medición: no se contó cuántos de los 360 pedidos alcanzaron
  a contestar antes de abandonarse (los abandonados quedan con status 0), así que
  el cupo del panel casi no llegó a dar 503 y no se lo vio actuar contra el
  servidor real; eso sí lo prueba `test_dashboard_cupo.py`.
- **La primera corrida dio un APROBADO falso** y el error fue del script, no de la
  app: el admin no entró (clave distinta en Pruebas), la tormenta nunca corrió (0
  pedidos del panel) y los lectores solos aprobaron. Ahora `setup()` valida al
  admin antes de arrancar (con clave mala corta en 1,4 s con el motivo) y el
  veredicto exige que la tormenta se haya ejecutado (≥ 90 % de los 360 pedidos).

### Lo que quedó sin resolver

- **Cargar `/healthz` en `mitrabajo-demo` después de promover** (ver arriba).
- Decidir si la base de Pruebas (0,1 vCPU) sube de plan: decisión de AKG; el
  resultado de arriba es un insumo.
- **Hipótesis sin confirmar**: por qué reiniciar el web service no alcanzó
  (consultas huérfanas corriendo en una base de 0,1 vCPU). Los logs y las
  métricas del 18-sep no se guardaron; la Fase 2.5 del documento sigue siendo
  una hipótesis.
- **Scripts de carga masiva** (`cargar_lote_*`, `--limpiar`) que necesiten
  consultas de más de 15 s tienen que correr con `DB_STATEMENT_TIMEOUT_MS=0`
  (queda dicho en `DESPLIEGUE_RENDER.md`).
- Fuera de alcance, como pedía el plan: caché de agregados, endpoints `async`,
  observabilidad (Sentry, métricas de Render).
- Hallazgo aparte, de la bitácora y no de este bloque: `test_fechas.py` falla
  por `generar_bitacora.py` línea 62 (llama a `datetime.now()`).

## La Sala de mando: el esquema físico de la plataforma, vivo (2026-09-21)

Rama `feature/esquema-fisico`. Nació como un boceto a mano en un cuaderno:
Sd dibujó todos los componentes de la solución (PC de desarrollo con Docker,
Claude Code, GitHub, la API de Render, los dos entornos con su web y su
Postgres, la API de Claude en el medio, las cinco puertas de la app,
Cloudflare delante, Grafana y Sentry avisando por mail) y pidió primero que
Code lo descifrara, después que lo mejorara, y al final que fuera **una sola
pantalla viva** para aprender, mostrar y manejar pendientes, renovaciones y
costos.

### Cómo se llegó al diseño

1. **v1, cajitas y flechas** (`docs/esquema-fisico.html`, después
   reemplazado): la lectura del boceto con una tabla "en el papel → en el
   esquema" y las preguntas abiertas. Aclaraciones de Sd: "ADM" es
   `/entornos`, y "porta" bajo la API de Render es la **portación** de
   Pruebas a Demo (`promover_demo.py`).
2. **v2**: siete zonas tintadas, ícono `$` en lo que se paga, primer clic
   amplía la caja, y tres **recorridos con luz de neón** (un recibo de punta a
   punta, un error o anomalía, el camino de un cambio) pensados para que un
   inversor o un comercial entiendan la complejidad sin que sea "científico".
3. **Tres propuestas de dirección visual** (`disenos/esquema-propuestas.html`,
   fuera de git como todos los mockups): A "Sala de mando" (centro de
   operaciones nocturno con barrido de radar), B "Plano de circuito" (chips,
   pistas de cobre, serigrafía) y C "La colmena" (celdas hexagonales, fondo
   claro). Sd eligió A.
4. **v3 sobre A**: franja de color por zona en el lateral de cada caja, las
   cajas reubicadas para que **las flechas sigan el flujo físico** (entrega
   arriba de izquierda a derecha, personas a la izquierda, externos en el
   medio porque los dos entornos los llaman, vigilancia abajo saliendo de
   Pruebas y el aviso volviendo al equipo por el borde), **pelotitas
   circulando** por las líneas punteadas y las de tráfico, KPIs más chicos
   para darle espacio al radar, y **el halo del radar atado al estado
   general** (verde / amarillo / rojo / violeta = sistema caído). Después:
   KPIs de negocio, sin siglas personales, Cloudflare mostrando lo que va a
   hacer (dominio a registrar, DNS, certificado TLS, WAF), GitHub, Grafana y
   Cloudflare marcados como **pagos futuros** (`$` en contorno), zoom al 40%
   y un foco de luz que sigue al puntero, tomado del login de plataforma
   pero más chico y más sutil.

### La versión viva

Decisión de Sd: las cifras salen de Pruebas y "cuando se porte se porta
todo". Por eso el HTML dejó de ser un archivo en `docs/` y pasó a ser una
**página de la app**:

- `esquema.py`: los indicadores en SQL agrupado (recibos totales y de hoy,
  lecturas de IA de hoy con su costo a precio congelado, ingresos por rol en
  los últimos 15 minutos como aproximación honesta a "usuarios en línea",
  trámites abiertos y los que esperan al gremio, sindicatos activos, padrón y
  registrados). Recibe la sesión, no la abre.
- `GET /entornos/esquema` (`templates/esquema.html`) dibuja con los datos ya
  inyectados, y `GET /api/entornos/esquema` los refresca cada minuto sumando
  el **semáforo de Grafana** (`estado_alertas`): verde, amarillo, rojo, o
  gris cuando no hay vigilancia configurada; si el pedido falla, la página
  pasa sola a violeta, que es exactamente "la app no responde". El estado de
  **cada entorno** sale de su propio `/api/version` (público, con CORS,
  como lo hace la landing): responde = en línea con su versión. Hasta que
  Demo tenga esa ruta promovida dice "sin respuesta", y es verdad.
- El vencimiento más próximo sale de `observabilidad/config.json`
  (`panel.renovaciones()`), la seguridad del tablero del XSK
  (`por_resolucion` + cuántos bloquean). Lo único que sigue "a completar" es
  el **gasto mensual**: los planes de Render y el costo de Claude no están
  en ningún archivo todavía.
- Mismo gate que toda la landing (`_exigir_pase`), 404 en la demo.
- Catalogada en Recursos como el primer recurso **de tipo enlace del
  repositorio** (`recursos.SEMILLA` con `url` en vez de `archivo`;
  `del_repositorio` y `del_repositorio_por_clave` lo contemplan).
- Tests: `test_esquema.py` (5). Plataforma 0.34.01.

Pendientes anotados en la propia página: gasto mensual, decidir Telegram
como canal y Cloudflare como perímetro (ver Pendientes de CLAUDE.md).

### Los logos de cada producto (mismo día)

Pedido de Sd: "un mini ícono de cada producto o servicio que usamos, para
mejor identificación". Los íconos de línea dibujados a mano se reemplazaron
por los **logos oficiales** en su color de marca, sobre un círculo claro
(así GitHub, Anthropic, Render y Sentry, que son casi negros, también se
ven). Salen de Simple Icons 16.32.0 (CC0) y van **vendoreados** en
`static/marcas.svg`, un símbolo por marca, con sello `?v=`; jamás CDN. ARCA
no está en ningún catálogo: Sd pasó el isotipo y va como PNG chico
(`static/marcas/arca.png`, 96 px) recortado en círculo. Georef no tiene
marca: lleva un mapita dibujado. Usuarios y equipo, un ícono genérico de
persona. Un test verifica que cada marca declarada en la plantilla tenga su
símbolo en el sprite y que los dos archivos se sirvan. Plataforma 0.34.02.

**Recuperación de la rama.** Los cinco commits de la v3 y de la versión viva
se habían hecho, sin advertirlo, sobre la rama `docs/xsanders-herramienta`
(la copia de trabajo cambió de rama en el medio), así que el PR #42 mergeó
solo la v1 y la v2. Se aplicaron con cherry-pick sobre `main` en la rama
`feature/esquema-logos`, con la bitácora resuelta a mano (la línea de
`main` más la de la Sala de mando).

### Reorganización de `/entornos`: la Sala de mando como pestaña (mismo día)

Pedido de Sd, apenas mergeada la Sala de mando: la pestaña **Actividad se
va** (ya no tenía sentido: sus números están en la Sala, mejor contados) y
**Observabilidad pasa a tener dos pastillas**: "Sala de mando" (este
desarrollo, por defecto) y "Observación técnica" (la solapa de Grafana,
Sentry y avisos tal cual estaba). La Sala va **incrustada en un iframe** a
`/entornos/esquema?embebida=1`: la página sigue existiendo suelta (y
enlazada desde Recursos), con su propio CSS y JS aislados del de la
landing, y en modo embebido solo esconde el enlace "← Entornos". El iframe
**se carga recién cuando se muestra**: abrir la landing no dibuja el esquema
ni pide sus datos si nadie lo va a mirar. La pestaña Observabilidad dejó de
estar deshabilitada fuera de Pruebas, porque la Sala de mando existe en
cualquier entorno con landing; la pastilla técnica sigue diciendo que se
administra desde Pruebas. Se fueron `templates/_actividad.html`, su CSS y
su JS, la ruta `GET /api/entornos/actividad` y la variable
`actividad_local`; `db.actividad_resumen` y `db.registrar_acceso` quedan
(AccesoLog alimenta "usuarios en línea"). Tests: `test_actividad.py`
ajustado (la pestaña y la API ya no existen), `test_esquema.py` (7).
Plataforma 0.35.01.

### El CI en cuatro partes paralelas (mismo día)

Sd preguntó por qué el CI tardaba tanto: 10 minutos por corrida. Medido en
el log: un minuto de preparación, cinco de pytest y **cuatro de arranque de
proceso**, porque los 111 archivos corren uno por uno en su propio proceso
(regla del proyecto, que no se toca). La suite se reparte ahora en **cuatro
trabajos de GitHub Actions que corren a la vez**, cada uno con su Postgres
y con cada archivo todavía en su propio proceso. `ci_reparto.py` decide qué
archivo va a cuál (orden alfabético, módulo cuatro, determinista) y
`test_ci_reparto.py` verifica que las partes no se pisen, cubran todos los
archivos y que la matriz del workflow declare exactamente `PARTES`
trabajos: agregar una quinta parte sin tocar la lista falla en el propio
CI. `fail-fast: false` para que una parte rota no cancele las otras, y la
caché de pip para ahorrarse la descarga de dependencias. Sin código de app.

### El iframe decía "refused to connect" (mismo día)

Sd entró a la pestaña nueva y vio un rectángulo blanco; el enlace de abajo
sí abría. Causa: las cabeceras de seguridad de H-0007 prohíben enmarcar
cualquier página de la app (`X-Frame-Options: DENY` y
`frame-ancestors 'none'`), y el iframe de la landing es exactamente eso.
La ruta `/entornos/esquema` ahora, **solo con `?embebida=1`**, responde
`SAMEORIGIN` y `frame-ancestors 'self'`: se puede enmarcar desde la propia
app y desde ningún otro sitio; suelta, sigue con `DENY`. El middleware usa
`setdefault`, así que lo que pone la ruta manda. Test en `test_esquema.py`
(8). Plataforma 0.35.02. Lección: cuando el CI no verifica una pantalla en
el navegador real, un iframe hay que probarlo servido, no desde un archivo
local (ahí el marco no carga por otro motivo y el error se confunde).

### La Sala de mando a pantalla completa (mismo día)

Sd la vio dentro de la pestaña, recortada entre el título de la landing y
Recursos, y pidió lo contrario: **toda la pantalla, sin títulos ni
Recursos, solo un botón para volver y el logo de Colm3na**. La Sala es
ahora una **capa fija** sobre la landing (`.sala-full`, el iframe ocupa el
viewport entero) con una cápsula flotante arriba a la derecha: el logo de
plataforma y "← Volver a Entornos"; Esc también cierra. Se abre sola al
entrar a Observabilidad (la pastilla por defecto) o al elegir la pastilla,
y al volver queda en la pestaña una tarjeta con "Abrir la Sala de mando"
para reabrirla sin salir. El iframe sigue cargándose recién la primera vez
que se abre. Plataforma 0.35.03.

### Indicadores compactos con burbuja (mismo día)

Los indicadores de arriba crecían con el texto: la lista de sindicatos o el
desglose de ingresos ocupaban tres o cuatro líneas y le robaban espacio al
radar. Ahora cada tarjeta tiene **dos líneas fijas** (etiqueta y cifra en
la primera, un resumen corto en la segunda, cortado con puntos suspensivos)
y **el detalle completo sale en una burbuja al pasar el mouse**: la lista
entera de sindicatos, el desglose por rol de los ingresos con la
explicación de los 15 minutos, cómo renovar el token que vence, los
hallazgos del XSK por estado, qué se paga y qué se pagará. Una sola burbuja
para toda la página, que sigue al puntero y se acomoda para no salirse de la
pantalla. Plataforma 0.35.04.

### Cabecera de una línea y botón circular de volver (mismo día)

Pedido de Sd: la cabecera ocupaba dos renglones con una bajada larga y las
tarjetas desperdiciaban ancho. Ahora la cabecera es **una sola línea**: el
logo de Colm3na y el título a la izquierda, el semáforo de estado general a
la derecha, sin bajada. Las tarjetas se reparten en las columnas que entren
(`auto-fit`, mínimo 168 px) con menos aire lateral, así en una pantalla
ancha van las diez en una fila. Y el volver es un **botón circular flotante
abajo a la derecha**, siempre visible: embebida en la landing le pide al
padre por `postMessage` (mismo origen) que cierre la capa; suelta, va a
`/entornos`. La cápsula que la landing dibujaba arriba a la derecha se fue,
porque la Sala trae su logo y su botón. Plataforma 0.35.05.

### La ficha flota sobre el radar (mismo día)

Sd: el panel de la derecha le quitaba un cuarto del ancho al radar y el
esquema seguía sin verse entero. La ficha ya no es una columna: es un
**panel flotante** que aparece al pasar el mouse por una caja, **del lado
contrario a la caja** para no taparla (a la derecha si la caja está en la
mitad izquierda y viceversa), alineado a su altura, y desaparece al salir.
Con un clic se **fija** (borde ámbar, se pueden usar sus botones) hasta
otro clic en la caja o en el fondo. Mientras corre un recorrido, la
narración va en el mismo panel, fijado a la derecha. Los tres botones de
recorrido pasaron a la cabecera, entre el título y el semáforo, y el
título dice solo "Sala de mando": el logo al lado ya dice Colm3na. El radar
ocupa ahora todo el ancho. Plataforma 0.35.06.

### La Sala entra en la ventana, y "solo radar" a pantalla completa (mismo día)

Sd reportó tres cosas: el botón de volver "desapareció", las tarjetas
flotantes salían cortadas a los costados, y quería un modo de pantalla
completa real (sin barra del navegador ni del sistema, solo el radar) que
se cierre con el mismo botón de volver. Reproducido con la app servida en
local y la Sala dentro del iframe: **la página medía 1.146 px en una
ventana de 900**, así que el tercio inferior del radar quedaba afuera, una
caja ampliada del borde inferior (Telegram) se dibujaba por debajo del
viewport y el botón flotante caía sobre esa zona cortada. La raíz era el
alto: `.marco` es ahora una columna de `100vh` sin scroll (cabecera y
tarjetas miden lo suyo, el radar se queda con el resto y el SVG se escala
para caber entero), así nada queda fuera de la ventana a ningún tamaño.

**Pantalla completa "solo radar"**: un segundo botón redondo (cian, encima
del de volver) pide el fullscreen del navegador. Embebida en la landing lo
pide el padre sobre su capa por `postMessage` (la activación del clic en
el iframe alcanza a los ancestros del mismo origen; el iframe lleva
`allow="fullscreen"` igual) y avisa al iframe cuando entra y sale; suelta,
lo pide la propia página. En ese modo `body.solo-radar` esconde cabecera,
tarjetas y leyenda: queda el radar a toda la pantalla. **El botón de volver
sale de la pantalla completa** si está en ella, y si no, como antes,
cierra la capa o vuelve a `/entornos`. Plataforma 0.35.07.

### Los tres ▶ como botones circulares dentro del radar (mismo día)

Sd: que los tres recorridos sean botones circulares de play, cada uno de su
color, con un rótulo corto (Recibo, Error, Código), y que sigan a mano en
la pantalla completa. Salieron de la cabecera (que en modo "solo radar" se
esconde) y viven ahora **adentro del radar**, abajo a la izquierda:
ámbar, rojo y cian, con el rótulo debajo en condensada; el que está
corriendo queda encendido con un halo de su color hasta que termina o se
detiene. Plataforma 0.35.08.

### Los indicadores se mudan a Observación técnica; la Sala es solo el radar (mismo día)

Última vuelta de Sd tras mirar todo con calma: los indicadores de negocio
pasan a la pastilla **Observación técnica** (sin repetir lo que esa solapa
ya tenía: el semáforo, el uptime y los vencimientos de tokens quedan donde
estaban; se suman recibos leídos, usuarios en línea, trámites abiertos,
sindicatos activos, afiliados registrados y gasto del mes, leídos de
`/api/entornos/esquema` con las tarjetas de siempre de la landing). Con eso
la Sala embebida es **solo el radar**, sin cabecera ni tarjetas, y
**elegirla abre directamente en pantalla completa** del navegador (el clic
en la pastilla es la activación que el navegador exige; al entrar por el
hash de la URL no hay clic y queda la capa sola). **Volver deja abierta la
pastilla Observación técnica**, no el menú principal: sale del fullscreen,
cierra la capa y cambia la pastilla. Suelta (desde Recursos) la Sala
conserva la cabecera y el botón de pantalla completa. Plataforma 0.35.09.

## El video "Panel de Control": la Sala de mando en 20 segundos (2026-09-21/22)

Pedido de Sd: un video dinámico de 15–20 s de la Sala de mando con el tango
electrónico del proyecto. Los play de Recibo y de Código encienden los
circuitos, los clics amplían cajas, un tramo va en vuelo 3D siguiendo el
circuito, hay partes a velocidad normal, aceleradas y en cámara lenta, y los
cambios de imagen caen al ritmo de la música. Arranca con el logo sobre azul
y "Panel de Control / Arquitectura de Desarrollo y Operación", y cierra con
el logo. Está en Recursos (`video-panel-de-control`); las fuentes para
regenerarlo, en `disenos/video-panel-control/` (fuera de git, con su `LEEME.md`).

**La música no sale del video anterior.** `mi-trabajo-recibos-tramites.mp4`
tiene locución encima ("eso no va", Sd), así que Sd pasó el tema limpio
(1:58, 117,5 BPM). Se usa el tramo 90,836 → 110,836 s: arranca en inicio de
frase, trae los cortes secos de 93–97 s y termina con el remate del tema, así
el video termina cuando termina el tango, sin fundido inventado. Sin voz que
cuidar va a volumen pleno: −10,8 LUFS con el pico a −1,1 dB. Se probó
dejarlo en −9,2 LUFS y la compresión AAC lo pasaba de 0 dB (+0,3 dBTP): lo que
HyperFrames bajó al mezclar era justo el margen para no saturar.

**Por qué se filma cuadro por cuadro y no se graba la pantalla.** La Sala
anima con `setTimeout` (los pasos de los recorridos), CSS (el barrido, el
neón) y SMIL (las pelotitas, los LEDs). Nada de eso se puede ubicar en un
instante dado, que es lo que necesita un editor de video, y grabar la
pantalla en vivo da cuadros irregulares y texto borroso. `captura/vt.js` se
inyecta antes que la página y reemplaza el reloj: temporizadores, `Date` y
`performance.now` avanzan solo cuando el filmador lo pide, las animaciones CSS
se pausan y se ubican a mano en cada cuadro, y las SMIL con `setCurrentTime`.
Con eso la cámara lenta y el acelerado son reales (cada cuadro es la página
dibujada en ese instante), y los pasos de cada recorrido se reparten
(`pasos[k].ms`) para que el neón salte exactamente en el golpe de la música.
La cámara (zoom 2D y vuelo 3D con `perspective` sobre el `<svg>`) deja quietos
los botones, la ficha y el cursor, que se dibuja aparte. Cada cuadro se toma a
3840×2160 y se reduce a 1080p, y el desenfoque de movimiento promedia 4 a 6
subcuadros (con 3 se veían copias fantasma). La página se renderiza suelta
desde `templates/esquema.html` de `main`, sin servidor ni login: es el mismo
código que corre en Pruebas.

**El vuelo 3D.** La línea de Desarrollo está en el borde superior del dibujo:
con la cámara mirando hacia adelante sobre ella, medio cuadro quedaba en negro
(más allá del borde no hay nada). Se subió la línea al tercio superior del
cuadro, se bajó la inclinación a 50°, se ocultó el barrido del radar durante
el vuelo (quieto sobre el plano inclinado parecía un triángulo) y se dibujó una
grilla de piso que acompaña al plano hasta el horizonte.

## Una persona, un domicilio (2026-09-22)

Lo reportó Sd así: "he detectado una inconsistencia en la informacion de
personal del trabajador, que puede tener un origen mas complejo que un error
de codigo". Tres síntomas: el alta que hace el sindicato no pide lo mismo que
el afiliado completa después en su perfil; la carga de foto de perfil falla; y
el CUIL 20202790411 parecía tener una dirección en su perfil y otra en la
información del sindicato, "pareciera que hay algo guardado en dos lugares".

Tenía razón en el diagnóstico de fondo, y las tres cosas resultaron ser
problemas distintos.

### La foto: la CSP no dejaba pasar los blob

No era de AEFIP ni de ningún sindicato: estaba roto para todos desde el
2026-09-20, el día que XSK estrenó las cabeceras de seguridad (H-0007).
`main.CSP` declaraba `img-src 'self' data: https:`, sin `blob:`.

Para no subir una foto de 4 MB al servidor, `redimensionarFotoPerfil()`
(portada.html) la achica en un `<canvas>`, y para eso primero tiene que
cargarla en un `<img src="blob:...">` fabricado con
`URL.createObjectURL(archivo)`. Sin `blob:` en `img-src`, el navegador bloquea
esa carga, salta `img.onerror` y la promesa se rechaza con "No se pudo leer la
imagen".

Lo que hace que el bug sea difícil de encontrar desde el servidor: **el
archivo nunca sale de la máquina de la persona**. No hay request, no hay error
4xx, no hay nada en los logs de Render ni en Sentry. Solo un cartel en la
pantalla. Y la foto que Sd ya tenía cargada se seguía viendo, porque era
anterior a la CSP: el síntoma era "no puedo cambiarla", no "no tengo".

Se confirmó levantando un servidor mínimo con esa misma cabecera y un `<img>`
apuntado a un blob: BLOB_BLOQUEADO con la CSP de entonces, BLOB_OK agregando
`blob:`. El mismo defecto afectaba a la foto del empleador
(`empresa_portada.html`) y a las miniaturas y videos de Recursos
(`entornos.html`), que además necesitan `media-src`.

Fix: `img-src 'self' data: blob: https:` y `media-src 'self' data: blob:`. Un
`blob:` no es una fuente externa -- lo fabrica el propio documento a partir de
un archivo que la persona eligió --, así que no abre ninguna puerta que
`data:` no tuviera ya abierta. Regresión en `test_xsk_correcciones.py`, que
hasta ese día no probaba el CONTENIDO de la CSP, solo su presencia.

### Las dos direcciones eran dos entornos

En Pruebas, el CUIL 20202790411 tiene un solo empadronamiento y un solo
domicilio ("pueyrredon 1362, barrio norte"). En Demo, el mismo CUIL tiene "La
rioja 893" con altura "892" y ciudad "Caba" -- la basura típica del formulario
de texto libre de antes. Demo corre la rama `demo`, que quedó en el esquema
viejo (columnas `piso`/`ciudad`, sin CP ni coordenadas): son dos bases
distintas con dos versiones distintas de la app, no dos lugares dentro de una.

### Pero abajo había un problema real, y era el que Sd intuía

`Trabajador` es una fila POR SINDICATO. Nombre, domicilio, teléfono y mail
vivían ahí, así que una persona empadronada en dos gremios tenía **dos
copias** de sus datos personales. Y las cuatro puertas por las que entran esos
datos no escribían igual:

- `/trabajador/registro` copiaba el domicilio a **todos** los
  empadronamientos del CUIL, con el comentario "es una sola persona y vive en
  un solo lugar".
- `/api/perfil` escribía **solo en el sindicato activo**, con el comentario
  "no hay un domicilio único de la persona en este modelo".

Dos rutas del mismo archivo, con dos modelos mentales opuestos y un comentario
cada una explicando el suyo. La misma persona editando en dos pantallas dejaba
dos resultados distintos, y nada indicaba cuál era el bueno. La divergencia ya
existía: un CUIL en Pruebas, uno en Demo y uno en la base local, los tres con
dos nombres y dos direcciones.

Había además una **tercera copia**: `CuentaTrabajador.nombre`, que existía, la
llenaba solo el cargador de datos sintéticos y **no la leía nadie** en toda la
app. La cuenta de Sd la tenía vacía mientras el padrón decía "Sandro Navello".

### La decisión: la persona es la dueña

Sd eligió, entre tres opciones, que el dato sea de la persona y exista una
sola vez. Nombre, domicilio, teléfono y mail se mudaron a `CuentaTrabajador`;
`Trabajador` quedó con lo que de verdad cambia de un gremio a otro: seccional,
credencial, CUIT del empleador, activo, registrado.

**La pieza que hace que "un solo lugar" sea cierto**: la fila de la persona
existe desde que el CUIL entra al PADRÓN, no desde que se registra. Si no, el
alta del admin necesitaría un segundo lugar donde escribir los datos de quien
todavía no tiene cuenta, y volveríamos al problema. Por eso `clave_hash` puede
estar vacío: vacío significa "todavía no eligió clave", no "no existe", y
`auth.verificar_clave` ya devolvía False con un hash vacío, así que ninguna de
esas filas sirve para entrar. Quién se registró lo sigue diciendo
`Trabajador.registrado`, que es por sindicato y alimenta el KPI del panel.

Toda escritura pasa por `db.guardar_datos_personales` (que ignora lo que llega
en `None`, así una pantalla que edita el domicilio no borra el teléfono que
cargó otra) y `db.asegurar_cuenta`. Toda lectura del padrón, por
`db.padron_del_sindicato(s, sid)` -- que recibe la sesión abierta, como manda
la regla de una sola conexión por request -- o por un JOIN explícito por CUIL
en las consultas del Panel Sindical, las encuestas y el ruteo de
notificaciones por provincia.

**Consecuencia buscada, y dicha en pantalla**: lo que corrige el admin de un
gremio lo ven el afiliado y los otros gremios. La pestaña Trabajadores lo
explica en dos renglones, arriba de la tabla, en vez de dejar que se descubra.

**La migración (a7e3f90b5c21) consolida lo que ya diverge** con una regla para
el domicilio y otra para el resto. El domicilio se copia **entero** desde un
solo empadronamiento -- son seis campos que valen como un dato, y fusionarlos
daría una dirección que no existe en ninguna parte, la calle de una ciudad con
la localidad de otra --, eligiendo la fila más completa: primero la que tiene
coordenadas, después la que tiene más campos cargados y, empatando, la del
sindicato más viejo. El nombre, el teléfono y el mail se resuelven **uno por
uno**, con el primer valor no vacío por orden de sindicato: no son parte del
bloque, y atarlos a él haría perder el teléfono que cargó un gremio solo
porque la dirección buena la tenía el otro. Se probó recreando a mano la
divergencia en la base local (un gremio con el teléfono y nada más, el otro
con nombre y domicilio completo con coordenadas) y el resultado tomó de cada
uno lo que correspondía.

`downgrade` devuelve las columnas y copia lo consolidado a todos los
empadronamientos: el esquema vuelve, la divergencia anterior no. Es el punto
del cambio.

**El costo del cambio fueron los tests**: 45 fixtures en 40 archivos creaban
`Trabajador(nombre=..., provincia=...)`. Se reescribieron con un script que
usa `ast` para ubicar cada llamada y sus keywords por posición y hace cirugía
sobre el texto, para no perder formato ni comentarios. Tuvo un bug que vale
anotar: **`ast` cuenta las columnas en bytes UTF-8 y Python corta strings por
caracteres**, así que sobre una línea con una tilde (`provincia="Córdoba"`) el
corte se iba uno de más y se comía un paréntesis.

### Y el registro pasó a pedir lo mismo que el perfil

Era el otro pedido de Sd. El registro pedía CUIL, clave y domicilio; el perfil
pedía además nombre, teléfono y mail. Quien se registraba abría "Tu perfil" un
minuto después y se encontraba con un formulario que no había visto nunca.
Ahora pide los mismos campos, en el mismo orden y con la misma marca de
obligatorio y opcional (teléfono y mail estaban sin marcar en el perfil y en
el alta del admin: se marcaron en los tres).

Dos diferencias que quedan a propósito: el registro pide además CUIL y clave
(es un alta), y el perfil recibe además el globo del mapa, que no está en el
registro porque ubicar un punto es una tarea de escritorio y el alta es el
momento de menos paciencia de toda la app.

Y una regla que tuvo que quedar escrita: **en el registro, un campo vacío no
borra lo que el padrón ya tenía**. El formulario no puede mostrar lo que el
sindicato sabe de un CUIL (lo averiguaría cualquiera tipeando CUILes ajenos),
así que dejar el teléfono en blanco significa "no lo completé". En el perfil
es al revés: ahí se ve lo cargado y borrarlo es una decisión.

`test_datos_personales.py` verifica que las dos pantallas pidan lo mismo
comparando la FIRMA de las dos rutas y no el HTML: es el contrato de verdad, y
un campo que el formulario muestre pero el servidor no reciba se pierde igual
sin avisar.

### Lo que quedó afuera

**El empleador tiene exactamente el mismo problema y no se tocó.** `Empleador`
es una fila por sindicato con `razon_social`, `domicilio`, `telefono`,
`provincia` y `mail`, y `/api/empresa/perfil` escribe solo en el sindicato
activo -- igual que el perfil del trabajador antes de este cambio. Peor
todavía: su `domicilio` sigue siendo un texto libre, nunca se migró al bloque
estructurado de `geo.CAMPOS_DOMICILIO`. Quedó anotado en BACKLOG.md; hacerlo
en el mismo bloque duplicaba el tamaño del cambio y el pedido era sobre el
trabajador.


## La portada del afiliado, esquema "Tablero" (2026-09-23)

El pedido de Sd fue "en escritorio las tarjetas son demasiado largas y queda
mucho espacio, y las letras de los títulos son chicas y difíciles de leer".
La causa no era de gusto y estaba en una línea: **`.pad` no tenía ancho
máximo**. En un monitor de 1920 la grilla de `.tarjetas` (3 columnas arriba
de 700 px) repartía todo el ancho disponible, así que cada tarjeta terminaba
midiendo unos 600 px, con un `min-height: 88px`, el ícono arriba, el texto
abajo y un título de 13 px en el medio de todo ese aire. No era "poca
letra": era una tarjeta que se estiraba sin tope.

**Tres mockups antes de tocar código**, en `disenos/portadas-propuestas.html`
(la carpeta está en `.gitignore`): A "Respiro" (la de hoy, con tope de ancho
y tipografía más grande), B "Tablero" (dos columnas: acción a la izquierda,
novedades a la derecha) y C "Mesa de trabajo" (agrupada por familias, pensada
por el panel del sindicato con sus 15 accesos). Cada propuesta se renderiza
dentro de un `<iframe>` de 1440 y otro de 390 al mismo tiempo, así las media
queries responden al ancho del iframe y no al de la página: lo que se ve en
el panel "Escritorio" es literalmente el CSS a 1440. Sd eligió la B.

### Qué cambió

- **Tope de 1320 px centrado** y dos columnas arriba de 1040 px
  (`minmax(0,1fr) 352px`). Abajo de eso se apila y queda como antes.
- **Los accesos son horizontales**: ícono en una pastilla a la izquierda,
  título y estado a la derecha, flecha al final. Es la forma que llena el
  ancho en vez de dejar hueco, y el título sube de 13 a 19 px.
- **La tarjeta principal dice números reales.** `db.resumen_recibos_trabajador`
  devuelve cuántos recibos verificó en lo que va del año y cómo salió el
  último; la tarjeta muestra "72 · recibos verificados este año" y "Julio
  2026 · con diferencias para revisar". Antes decía "Revisá tus aportes", que
  no le informaba al afiliado nada que él no supiera ya. Sin ningún recibo
  todavía no inventa un cero: cambia el texto e invita a subir el primero.
- **Novedades y Beneficios suben al riel**, donde se ven al entrar, en vez de
  quedar al final de un scroll largo.

### Las dos cosas que Sd pidió conservar

**La foto de la noticia.** En la primera versión de la propuesta B el riel las
había reducido a un hilo de texto. La miniatura ya existía (44 px,
`/noticia-imagen/{id}/1`): ahora sube a 62 px y la más nueva lleva filo de
acento, el mismo recurso que ya usa `.notif-item.no-leida`. La noticia sin
imagen sigue cayendo en el ícono genérico, del mismo tamaño, para que los
títulos queden alineados.

**El carrusel de beneficios**, rehecho como pieza de marketing: imagen a
sangre con velo oscuro de abajo hacia arriba, el rubro como chip en acento,
la descripción en condensada cortada a dos renglones (la escribe el sindicato
y puede ser larga; si no, la tarjeta cambia de alto entre una lámina y la
siguiente) y la vigencia al pie. La fluidez son cinco cosas concretas:
deslizamiento con curva de salida de 620 ms, **zoom lento sobre la lámina
activa** (Ken Burns de 7 s, que es lo que hace que una tarjeta quieta parezca
viva), barra que muestra cuánto falta para la que sigue, arrastre con el dedo
que sigue la mano y decide al soltar, y **pausa al pasar el mouse** -- nadie
quiere que se le mueva lo que está leyendo. Las cinco se apagan con
`prefers-reduced-motion`.

Dos decisiones del carrusel que conviene recordar:

- **Clases propias (`.car-*`) y no las `.carrusel*` de marca.css.** Esas las
  sigue usando la vista previa del panel de admin y no tienen por qué cambiar
  juntas.
- **La imagen pasó de `contain` sobre una tira de 88 px a `cover` sobre
  16/11.** Las imágenes cargadas hasta ahora se van a ver recortadas si son
  verticales: hay que pedirle al sindicato que las suba apaisadas.

### La profundidad, sin un solo color nuevo

Sd trajo como referencia una app de club de pádel hecha con Code. Lo que se
tomó de ahí son cuatro recursos, ninguno de los cuales agrega color: dos
**manchas de luz difuminadas** (que son el primario y el acento del PROPIO
sindicato, al 42% y 16% con blur de 110 px), una **retícula de colmena** muy
tenue de fondo -- el equivalente nuestro a sus líneas de cancha --, la
**trama diagonal más fina** (1 px cada 6) y **radios más grandes** en las
piezas principales. En la portada clara las manchas se apagan: dos blobs
sobre papel se ven como una mancha de impresión.

### Lo que se verificó

Contra el local con Postgres: **La Bancaria** (con logo y con 20 beneficios
sintéticos) en 1440 y en 375, la variante clara forzada por DOM, y el
carrusel medido en vivo -- avanzó solo a la quinta lámina, `carMover(1)`
pasó a la sexta, los puntos siguieron el estado y la barra corrió. Tests:
`test_portada` (12, cuatro nuevos: números reales, el caso sin recibos, la
foto de la noticia y el carrusel), `test_beneficios`, `test_encuestas`,
`test_modulos`, `test_noticias`, `test_notificaciones`, `test_modales`,
`test_fechas`, `test_datos_personales` y `test_codigos_error`.

Dos tests había que tocarlos y valía la pena entender por qué. El de
beneficios afirmaba las clases viejas del carrusel (prueba lo mismo de
siempre: con una sola lámina no hay a dónde ir, así que no se dibujan ni
flechas ni puntos). Y el de encuestas buscaba `class="acceso" href="/app?tab=
encuestas"`; al aflojarlo al href pelado empezó a dar falso negativo, porque
ese mismo href aparece **dentro de un template literal del JS** de
notificaciones. Quedó con la clase nueva.

### Lo que NO cambió

Las portadas del sindicato, la empresa y la plataforma siguen con el esquema
anterior (`.tarjetas` + `.acceso` de marca.css). El pedido era sobre la del
afiliado y llevarlas a las cuatro de una vez es otro bloque.


### El mismo esquema en las otras tres portadas (2026-09-23)

Sd pidió llevarlo a sindicato, plataforma y empresa, en ese orden. Lo que
obligó a pensar antes de copiar fue **dónde poner el CSS**: cuatro copias del
mismo bloque en cuatro `<style>` es exactamente lo que este proyecto ya vivió
con el encabezado. Las cuatro portadas cargan `marca.css`, así que ahí va.

**Y ahí apareció el problema de verdad**: `.fila`, `.filas`, `.pastilla`,
`.mini`, `.txt`, `.nov` y `.sec` **ya existen** en admin.html, dashboard.js,
encuesta_resultados.js, entornos.html y empresa.html. `marca.css` la carga
casi toda la app, así que subir esas clases sin prefijo habría pisado media
docena de pantallas sin que ningún test lo notara (son estilos, no
comportamiento). Por eso todo el bloque quedó prefijado **`pt-`**
(`.pt-fila`, `.pt-pastilla`, `.pt-hero`…), y el renombre se hizo solo sobre
selectores CSS y atributos `class="..."`, nunca sobre texto libre: "una fila
por sindicato" y "dos columnas" son frases que aparecen en los comentarios.

Cada portada quedó con lo suyo:

- **Sindicato**: hero para el Panel Sindical (sin cifra propia -- la portada
  no tiene de dónde sacarla sin pegarle a la base, y el Panel es justo la
  pantalla que las trae todas) y los 14 accesos restantes en **tres
  columnas** (`.pt-tres`, un modificador para las portadas sin riel: en dos
  columnas 15 accesos son una lista larguísima). Se fue la estrella de la
  esquina del módulo nuevo: en una tarjeta chica marcaba algo, sobre el hero
  es ruido. La etiqueta NUEVO queda.
- **Plataforma**: hero para Sindicatos, que es lo que se hace ahí el 90% de
  las veces, y los otros siete accesos en tres columnas.
- **Empresa**: sin hero. Son dos accesos y ninguno es "el principal"; un hero
  ahí sería una jerarquía inventada. De paso se estrenó el globo de novedades
  de Trámites, que **ya se contaba en el contexto y no se mostraba**: un
  expediente con respuesta del sindicato no se veía hasta entrar.

### El círculo de perfil del sindicato

Sd lo pidió "en el mismo lugar" que en la app del afiliado. Es de **lectura**:
abre una ficha con nombre, usuario, CUIL, rol, seccional, área y sindicato.
No edita nada -- cambiar la clave de un usuario del panel sigue siendo cosa
de plataforma, y los permisos los da el Super Admin desde Áreas y Usuarios.

La foto sale de `CuentaTrabajador`, o sea **del CUIL**, no de una copia
guardada en `UsuarioSindicato`: quien trabaja en el gremio y además está
afiliado tiene una sola foto, igual que tiene un solo domicilio. Quien no
está en el padrón -- que es un caso real y no un error, como Elena Vidal de
Prensa en la demo -- simplemente no tiene, y se ve el ícono.

Un detalle que costó encontrar: `.fila-hola` (el flex que pone el saludo y el
círculo en la misma línea) vivía en el `<style>` de portada.html y de
empresa_portada.html. Al llevar el esquema al sindicato, el círculo caía
debajo del saludo. Ahora está en `marca.css` con el resto.

## Avisos por Telegram: errores al instante y el resumen del día (2026-09-23)

Rama `feature/avisos-telegram`. Sd pidió "agregar mi número para que me
lleguen alertas como las de Sentry y un resumen de la actividad del día
tomado de los KPI que ya tenemos: algo simple y que no agregue costos".
Telegram es lo único que cumple las tres: API oficial gratuita, un POST sin
librerías, y un bot que se crea con BotFather. WhatsApp exige cuenta de
empresa aprobada y cobra por conversación; los SMS se pagan uno por uno.

**Lo que se construyó.** `telegram.py` (puro: `enviar`, `avisar_error` con
freno de 10 minutos por código, `texto_resumen`, sin claves en el repo) y
`resumen_diario.py` (hilo en la app, a la hora de `TELEGRAM_RESUMEN_HORA`,
21:00 por defecto porque lo pidió Sd). El handler global manda a Telegram
lo mismo que a Sentry, sin personas, en otro hilo. El resumen reclama el
día con `db.reclamar_aviso_diario` (tabla `avisoenviado`, migración
`b3c7e1d9a4f2`): un INSERT que solo gana un worker. Grafana suma un segundo
punto de contacto (`sdn-telegram`) y una política de dos rutas, solo si el
entorno trae las claves. La pestaña Observación técnica muestra el estado y
tiene dos botones: prueba y "resumen ahora". La Sala de mando dibuja
Telegram como activo cuando está configurado (cierra esa decisión
pendiente). Tests: `test_telegram.py` (11). Plataforma 0.36.01.

**El token pasó por el chat.** Sd pegó el primer token en la conversación
por error de portapapeles; se le pidió revocarlo en BotFather y cargar el
nuevo directo en Render, que es la regla: los secretos no pasan por Code.

### El servidor en el resumen: picos, horarios y congestión (mismo día)

Con el primer resumen ya en el teléfono, Sd pidió "una línea o dos de cómo
funcionó el servicio web, si se congestionó, si tuvo picos en algún horario,
y lo mismo para la base, con algún número si hiciera falta". Las métricas
ya existían: son las que el colector manda a Grafana cada cinco minutos.
`observabilidad/metricas_dia.py` las lee de Render para las últimas 24
horas (CPU y memoria contra el límite del plan, pedidos HTTP por código de
estado, latencia p95, conexiones de la base) y las resume en dos líneas con
las horas en Buenos Aires: pico de CPU y cuándo, promedio, pico de memoria,
cuántos pedidos, la hora más cargada, cuántos 5xx, la latencia máxima; y
para la base CPU, memoria y conexiones máximas. El veredicto "sin
congestión / hubo congestión: …" usa el mismo criterio que las alertas del
tablero pero mirando el día entero (CPU al 80 %, cinco 5xx, p95 de 3 s).
Lectura y análisis separados: el análisis es puro y se prueba con series
inventadas. Sin `RENDER_API_KEY` o con Render caído, el resumen sale igual
con una línea que lo dice. Plataforma 0.36.02.

## Reportes unificados y la cláusula de confidencialidad (2026-09-24)

Pedido de SDN: las dos listas de recibos del panel del sindicato --Reportes
y Cotizantes-- pasan a ser una sola, "Reportes", y se le suman los recibos
que el afiliado verificó y NO envió, sin datos que lo identifiquen a él ni a
su empresa, y solo si el sindicato aceptó por contrato una cláusula de
confidencialidad.

### De dónde salían las dos listas

- **Reportes** leía la tabla `Reporte`: los recibos que el afiliado
  "reportó" por tener diferencias, con un estado (nuevo / en revisión /
  resuelto) que nadie gestionaba.
- **Cotizantes** leía `EnvioSindicato`: los que el afiliado envió. Y como
  `/api/reportar` escribe también un `EnvioSindicato`, **todo lo de
  Reportes ya estaba en Cotizantes**.
- La tabla con TODOS los recibos verificados, enviados o no, ya existía:
  `ReciboVerificado`, con `enviado_sindicato` y `estado` OK /
  CON_DISCREPANCIAS. La lista nueva no pidió datos nuevos, solo otra forma
  de mostrarlos.

`Reporte` y `EnvioSindicato` no se tocaron: se siguen escribiendo y
`EnvioSindicato` sigue siendo la prueba de afiliado cotizante (art. 21 bis
Dto 407/2026). Lo que desapareció es su pestaña.

### Por qué la lista se pide paginada y no viaja en el HTML

Las dos listas viejas se renderizaban enteras dentro de `/admin`, con el
detalle de cada recibo escondido en una fila oculta. Con `ReciboVerificado`
eso son miles de filas (el lote de un sindicato tiene 5.000) en cada carga
del panel. Ahora `/admin/reportes/lista` devuelve de a 50, se pide recién al
abrir la pestaña, y el modal "Ver" pide un solo recibo a
`/admin/reportes/recibo/{id}`. De paso, el HTML del panel ya no lleva
ningún recibo adentro.

### Privacidad: en el SQL, y también en la búsqueda

`dashboard.listado_reportes` saca CUIL, nombre y CUIT del empleador con un
`CASE WHEN r.enviado_sindicato`, igual que el explorador del Panel. Lo que
no era obvio: **la búsqueda por CUIL o por nombre busca SOLO entre los
enviados**. Si buscar "27422222228" trajera la fila anónima de ese CUIL, el
filtro mismo la identificaría. La pantalla lo aclara debajo de los filtros.

El modal usa `dashboard.detalle_recibo`, el mismo del Panel, y la limpieza
del JSON guardado quedó en una sola función, `anonimizar_detalle`: borra
nombre, CUIL, legajo y fecha de ingreso del empleado y **el empleador
entero** (antes el Panel dejaba la empresa). Una sola implementación porque
la primera pantalla que anonimizara a su manera y se olvidara un campo lo
dejaría pasar.

### La compuerta de la cláusula, y qué queda afuera de ella

Decisión de SDN: **los números, conteos y gráficos del Panel cuentan todo**,
enviado o no, como hasta ahora; lo que se ve fila por fila, anonimizado. La
cláusula recorta solo las filas: sin ella, ni Reportes ni el explorador del
Panel muestran recibos no enviados, y el modal responde 404. La lista dice
cuántos quedaron afuera, para que el sindicato sepa que existen y por qué no
los ve.

La cláusula vive en `Sindicato` (`clausula_confidencialidad`, más
`clausula_aceptada_en` y `clausula_aceptada_por`) y solo la marca
plataforma. **Exige el contrato cargado**: un tilde sin el papel firmado no
le da a nadie los recibos. Quién y cuándo se escriben solo al PASAR a
aceptada --volver a guardar la ficha no reescribe la fecha-- y se borran al
desmarcarla; los dos movimientos quedan además en `LogPlataforma`. El
contrato va en bytes en la base (PDF o imagen, hasta 15 MB) y lo sirve
`/plataforma/sindicato/{id}/contrato`, que exige sesión de plataforma: no es
público como el logo.

### Permisos

La sección `cotizantes` salió de `permisos.SECCIONES`. La migración
`c9e4a2f7b815` pasa cada permiso de área y cada ajuste individual
(agregar o bloquear) de `cotizantes` a `reportes`, sin duplicar filas: nadie
gana ni pierde acceso a esos recibos. La lista respeta además el alcance de
seccional (`db.alcance_seccional`) dentro de la consulta, cosa que las dos
listas viejas no hacían.

### Lo que sigue

Próximo sprint: en el primer uso, el afiliado acepta términos y condiciones
que le dicen que sus recibos llegan al sindicato anonimizados, y con nombre
solo si los envía él.

## Enmascarado, bloque 1: qué se tapa (2026-09-24)

Paso cero del motor v2 (`PLAN_ENMASCARADO.md`). El bloque 1 es el módulo que
decide qué se tapa, `enmascarado.py`, puro y sin tocar la app: recibe
"palabras con posición" y devuelve las cajas a tapar, el CUIL y el CUIT
leídos, y la imagen tapada con un rótulo gris ("CUIL OCULTO"). `lectores.py`
trae por ahora solo el PDF digital (`pypdfium2`); el OCR de fotos es el
bloque 2.

### Lo que enseñó el recibo digital ficticio

Se armó con reportlab un recibo con capa de texto (identidad inventada:
nombre con acentos y Ñ, CUIL y CUIT con verificador válido, CBU, dos
páginas) porque los 10 sintéticos son todos imágenes. Encontró dos cosas que
los sintéticos no mostraban:

- **El lector partía los números.** `30-71234567-1` salía como tres
  palabras: la caja de un guion mide un punto de alto y el corte por hueco
  usaba esa altura. Se usa la caja "amplia" de cada carácter
  (`get_charbox(loose=True)`).
- **Palabra por palabra no alcanza.** Aun con el lector arreglado, un PDF
  trae "Apellido y Nombre:" como tres palabras y un OCR puede partir un CUIL
  en tres cajas. El módulo trabaja por **frase**: palabras contiguas de una
  línea, cortadas en los huecos grandes para que dos columnas no formen un
  número.

### Otras decisiones

- **La tabla de conceptos no tiene rótulos**: "A CUENTA DE FUTUROS
  AUMENTOS" no es una cuenta bancaria. La tabla arranca en una FILA de
  títulos de columna (dos o más) y no en cualquier frase que diga "haberes":
  "RECIBO DE HABERES" del encabezado apagaba todos los rótulos.
- **El valor de un rótulo está en la primera fila de abajo, no en la
  segunda**: en el sintético, "Categoria" quedaba más centrada bajo
  "Apellido y nombre" que el nombre mismo.
- **Lo que se tapó por rótulo se aprende** y se busca en el resto del
  documento (el nombre se repite al pie para la firma). Con eso el caso del
  aprendizaje del admin, sin nada conocido de antemano, tapa lo mismo que el
  del afiliado.
- **Un importe nunca se tapa**, venga del detector que venga.
- El verificador de CUIL/CUIT es lo que deja tapar un número de 11 cifras
  sin rótulo; el CUIL de los sintéticos (27-99999999-9) tiene verificador
  inválido y se tapa por el rótulo o por ser el de la sesión.

### Resultado

`test_enmascarado.py`, 53 tests: con y sin datos conocidos, en el digital y
en los 10 sintéticos se tapa **exactamente** la identidad (nombre, CUIL, DNI,
legajo, cuenta, CUIT, razón social), ningún importe ni concepto, y el
control de fuga da vacío. Las palabras de cada recibo están en
`datos_prueba/enmascarado/*.json` (los PDF sintéticos no se versionan: 2 MB
cada uno); se regeneran con `datos_prueba/enmascarado/generar.py`.

### Lo que condiciona al bloque 2

**El OCR completo de una página es lento**: RapidOCR tardó 10 a 16 s por
página en una notebook de 8 núcleos y 35 s con un solo hilo. Detectar dónde
hay texto cuesta 1,3 s; lo caro es LEER las ~136 cajas (el modelo que trae
el paquete es el chino, con más de 6.600 caracteres). Así no entra en los 3 s
del plan. El bloque 2 tiene que leer solo lo necesario (el encabezado, no la
tabla) y/o usar un modelo latino más liviano, y medirlo antes de enchufar
nada. El PDF digital no tiene este problema: sus palabras salen del archivo
en milisegundos.

## Enmascarado: el OCR de las fotos es Tesseract, sin Docker (2026-09-24)

El plan (C2) elegía RapidOCR porque Tesseract "es un programa del sistema y
el Render nativo no deja instalarlo". Medido, RapidOCR no llegaba al límite
de 3 s por foto, y SDN rechazó ajustar el límite apostando a que llegaran
pocas fotos. Se buscó otra solución antes que pasar el servicio a Docker.

**`tesserocr` publica ruedas para Linux que traen Tesseract 5.5.1 adentro**
(`libtesseract` y `libleptonica` empaquetadas, 5,5 MB): se instala con `pip`
en el Render nativo, sin `apt` y sin Docker. Se verificó en un contenedor
`python:3.12.8-slim-bookworm` pelado (Debian 12, lo mismo que el Render
nativo), sin instalar nada del sistema. Le falta solo el idioma:
`spa.traineddata` de `tessdata_fast` (2,3 MB). No hay rueda para Windows:
en una PC de desarrollo con Windows el camino de las fotos se prueba en
Docker.

### La medición (contenedor con `--memory=512m`, 10 sintéticos + el digital)

Los tiempos de reloj en la notebook variaron hasta 4 veces entre corridas
(la máquina estaba ocupada con otras cosas), así que el número que vale es el
**tiempo de CPU por página**, que no depende de qué más corre:

| Motor | CPU por página | Memoria del proceso |
|---|---|---|
| RapidOCR, modelo chino, página entera | ~21 s (notebook, 1 hilo) | — |
| RapidOCR, latino v5, sin leer la tabla | 3,4–3,8 s | 256–305 MB |
| **Tesseract, página entera** | **0,7 s** | ~128 MB |

Con 1 CPU (producción) una foto suma ~0,7 s; con medio núcleo (Pruebas),
~1,4 s. El modelo de Tesseract ocupa ~20 MB por proceso, no los 200 que
estimaba el plan. El modelo latino cuantizado a 8 bits se descartó: más
lento y dejó escapar el nombre. Leer "sin la tabla" (reconocer las filas de
conceptos por geometría y no leerlas) le sirvió a RapidOCR pero no a
Tesseract, que analiza la página dos veces para eso.

### Lo que cambió en el módulo

Tesseract lee "CUIL N" como **"CUILN"**: el rótulo acepta ahora la N pegada.
Con eso, en los 11 recibos se tapa exactamente la identidad y el control de
fuga da 0, con y sin datos conocidos.

### Docker, por si alguna vez hace falta

Se relevó qué implicaría: Render permite cambiar el runtime de un servicio
existente a Docker (conserva URL, variables y base); hay que mantener un
`Dockerfile` (y las actualizaciones del sistema base pasan a ser nuestras),
`render_admin.py` cambia los workers en el "Start Command", que en Docker
es el "Docker Command", y el cambio se hace dos veces (Pruebas y Demo).
Con `tesserocr` no hace falta.

## Enmascarado, bloque 2: los lectores, y el enmascarado pasa a "mejor esfuerzo" (2026-09-24)

### La definición de SDN

Antes de este bloque SDN fijó el objetivo, y cambió dos reglas del plan: el
análisis de recibos tiene que ser lo más preciso, confiable y viable en
tiempo y recursos; tapar los datos personales es un agregado a la
confidencialidad que ya existe, **no una condición**. No debe entorpecer ni
demorar ni ser cuello de botella; se tolera la fuga eventual de un CUIT o un
nombre ("no construimos una jaula de acero": el compromiso es el mejor
esfuerzo), y **un dato que no se pudo tapar no es razón para no analizar el
recibo**: a lo sumo queda un registro. Eso reemplaza la línea roja 2 ("si el
enmascarado no está seguro, el recibo no sale") y el §6 entero del plan
(reintento con imagen mejorada, pedir otra foto, E-RECIBO-05/E-APORTE-04).
Quedó en "Decisiones tomadas" de CLAUDE.md. La verificación de pertenencia
NO se relaja: un CUIL ajeno leído localmente corta como hoy (E-RECIBO-04).

### Lo que se construyó

`lectores.py`: el PDF digital con `pypdfium2` y la foto con Tesseract
(`tesserocr`). La lectura de una foto **nunca espera ni levanta
excepciones**: devuelve el motivo ("sin_ocr", "sin_lugar", "tiempo",
"error") y quien llama manda sin tapar y registra.

- **Cupo que no hace fila** (`ENMASCARADO_CUPO`, 2 por proceso): la foto que
  no entra vuelve al instante con "sin_lugar". Es a propósito distinto del
  cupo del Panel Sindical, que espera 2 s: acá esperar sería demorar el
  análisis por un agregado.
- **Tiempo máximo** (`ENMASCARADO_OCR_MS`, 4000): lo corta Tesseract mismo
  (`Recognize(timeout)`), no un hilo aparte.
- **Un hilo por lectura** (`OMP_THREAD_LIMIT=1`, antes de cargar Tesseract)
  y sin buscar texto invertido.
- **La foto se lee achicada** a 2000 px de lado y las cajas vuelven en
  píxeles de la original. **Y derecha**: `abrir_imagen` aplica la rotación
  del EXIF, porque al volver a codificar la imagen tapada ese dato se pierde
  y la IA recibiría la foto acostada.
- El idioma (`spa.traineddata`, `tessdata_fast`, 2,3 MB) va en
  `data/tessdata/`, versionado. En Windows no hay rueda de tesserocr: el OCR
  queda "sin_ocr" (se tapa solo el PDF digital) y se prueba en Docker.
- Los datos de prueba de los sintéticos se regeneraron con Tesseract (el
  lector de la app, no RapidOCR). El CUIT admite ":" como separador: así lee
  Tesseract a veces el guion.

### La tabla del §5 (contenedor Debian 12, 512 MB)

| | 1 núcleo | ½ núcleo (Pruebas) | Límite |
|---|---|---|---|
| PDF digital, 2 páginas, p95 | 0,14 s | 0,45 s | 0,3 s |
| Foto de 1 página, p95 | 0,80 s | 2,28 s | 3 s |
| Modelo cargado | +9 MB | +9 MB | 250 MB |
| Por lectura | +10 MB | +10 MB | 60 MB |
| Resto de la app durante 10 fotos a la vez, p95 | 3 ms | 47 ms | sin demora |

Con 10 fotos a la vez se leen 2 (el cupo) y 8 vuelven sin tapar en 0 ms.
El PDF de dos páginas con medio núcleo pasa el límite (0,45 s contra 0,3 s:
es pasar dos páginas a imagen); con un núcleo sobra.

Tests: `test_lectores.py` (11; los dos de Tesseract real se saltean en
Windows) y `test_enmascarado.py` (54). En Linux corren los 65.

### Ráfagas: presupuesto de 5 s y un lector por proceso (2026-09-24)

Con el cupo que no esperaba, una ráfaga de 10 fotos dejaba 8 sin tapar: más
que una excepción. SDN extendió el criterio a **5 s por foto** y pidió
mirarlo además en Pruebas. Quedó así:

- **Presupuesto** (`ENMASCARADO_PRESUPUESTO_MS`, 5000): lo máximo que una foto
  suma, fila más lectura. Hasta `ENMASCARADO_ESPERA_MS` (3000) esperando un
  lector libre; lo que queda es para leer (nunca menos de 1 s). Pasado el
  presupuesto, sale sin tapar y se registra.
- **Un lector por proceso** (`ENMASCARADO_CUPO` = 1). Medido en un
  contenedor con 4 núcleos y 4 procesos (la forma de Render: un proceso por
  núcleo): ráfaga de 10, **10 tapadas** en 3,3 s como máximo con 1 lector
  contra 8 con 2; ráfaga de 20, 12 contra 2. Con dos lectores en el mismo
  núcleo cada lectura pasó de 0,8 s a 2,6 s de CPU: no leen más, se estorban.
- La configuración de producción que dejaron las pruebas de estrés (web en
  2 instancias de 4 CPU, 8 procesos) reparte una ráfaga de 20 en 2 o 3 fotos
  por proceso, la misma proporción que la ráfaga de 10 sobre 4 procesos.
- **Lo que queda para Pruebas**: con medio núcleo y un proceso, una ráfaga
  deja fotos sin tapar (por capacidad: ~1,3 fotos por segundo por núcleo).
  Lo mide el modo sombra (bloque 5) con datos reales, y el número de la
  notebook no se usa para proyectar: con todos sus núcleos ocupados la CPU
  por lectura se triplica.

## Enmascarado, bloque 3: el enganche en la app (2026-09-24)

`preparacion.py` es la capa entre las rutas y los dos módulos del
enmascarado: elige el camino (PDF con texto, PDF escaneado, foto), arma la
imagen que viaja, rearma la identidad en lo que devuelve la IA y deja el
registro. Variable `ENMASCARADO`:

- **`apagado`** (default): no se hace nada. La llamada a `extraer()` queda
  idéntica a la de siempre (lo verifica `test_preparacion.py`), así que los
  tests que simulan la IA siguen valiendo tal cual y nada cambia en ningún
  entorno hasta prender la variable.
- **`sombra`**: se calcula todo y se registra, pero viaja el original, y un
  recibo ajeno solo se anota. Es para medir en Pruebas sin tocar a nadie.
- **`activo`**: viaja la imagen tapada, la IA recibe un aviso (las zonas
  grises son intencionales: null en esos campos y no es adulteración) y la
  identidad vuelve con lo leído acá.

Las cuatro salidas hacia la IA: el recibo (`/api/leer`), el comprobante de
ARCA (`/api/aportes`) y el aprendizaje del admin (`/admin/aprender`, sin
nada conocido: patrones y rótulos). El banco de pruebas de plataforma se
toca en el bloque 4.

### Decisiones del bloque

- **El recibo ajeno se corta ANTES de la IA** (E-RECIBO-04 / E-APORTE-03):
  ni se paga la lectura ni sale el documento. Pero solo con un CUIL ajeno de
  **dígito verificador válido** (`enmascarado.pertenece`): un dígito mal
  leído por el OCR no puede rechazarle a nadie su propio recibo. Con "no se
  sabe" el recibo sigue y los chequeos de siempre sobre lo que devuelve la
  IA siguen en pie.
- **La identidad se rearma con lo leído en el documento, no con la base**:
  el CUIL y el CUIT del recibo (con pluriempleo el CUIT guardado puede no ser
  el del recibo, y de ese CUIT dependen los conceptos por empleador); el
  nombre, de `CuentaTrabajador` si se lo encontró en el recibo; la razón
  social, del empleador cargado en el sindicato por ese CUIT o, si no está,
  de lo leído (una sola vez: el logo y la firma repiten texto). Solo se
  completa lo que la IA devolvió vacío o como "OCULTO".
- **Si la IA marca el rótulo gris como adulteración**, esa alerta no vale.
  Una alerta real (otro motivo) sigue en pie.
- **Registro sin datos personales**: tabla `registroenmascarado` (migración
  `e5b2c8d4f1a7`): modo, camino, motivo, si se tapó, cajas, fugas, si se
  encontró el CUIL, pertenencia y tiempos. Nunca levanta: ni una tabla
  faltante puede frenar un recibo.
- **La foto viaja derecha** (EXIF) y con 3000 px de lado como mucho; un PDF
  tapado viaja como PNG de la primera página, igual que hoy.
- El lector de fotos se precarga al arrancar si el modo no es `apagado`.

Tests: `test_preparacion.py` (18: modos, caminos, archivo roto, rearmado, el
aviso, y las rutas de punta a punta con la IA simulada: apagado idéntico,
activo tapa y rearma, ajeno cortado sin llamar a la IA, sombra no cambia
nada, un error del enmascarado no frena el recibo). Probado además el camino
de fotos con Tesseract real en Linux: 17 zonas tapadas, 0 fugas, 1,3 s.
Trabajador 0.42.01, Admin 0.46.01.

### Sin módulo 11, por ahora (2026-09-24)

SDN: por ahora no se valida el dígito verificador de CUIL/CUIT; queda en
BACKLOG.md para cuando se avance. Y ninguno de los CUIL/CUIT de la demo lo
cumple, así que el enmascarado dejó de depender de él en los dos lugares
donde lo usaba:

- **Detectar**: un número con formato de CUIL/CUIT (con separadores y
  prefijo válido) se tapa aunque no cumpla el verificador. Once cifras
  pegadas y sin rótulo siguen necesitándolo: podrían ser un importe
  (`enmascarado.parece_cuil`).
- **Recibo ajeno**: en vez del verificador, el CUIL leído tiene que diferir
  del de la sesión en **3 dígitos o más** (`distintos_de_verdad`). Un error
  del OCR cambia uno, rara vez dos: a esa distancia es el propio mal leído y
  el recibo sigue.

## Enmascarado, bloque 4: tapar no cambia la lectura (2026-09-24)

El criterio del plan era "cero diferencias en importes y en la clasificación
de cada línea, con y sin enmascarado". Se midió con la IA real
(`medicion_enmascarado/medir.py`, resultado en `RESULTADO.md`): cada recibo
leído tres veces con el mismo modelo (claude-sonnet-4-6) -- original, tapado
con la identidad conocida y tapado sin conocidos --, sobre los 10 sintéticos
(fotos: OCR con Tesseract) y el digital ficticio (texto del PDF). 33
llamadas.

- **Totales, cantidad de líneas, período y categoría: iguales en los 11.**
- **Identidad rearmada igual a la que leyó la IA en el original** (CUIL,
  CUIT, nombre, legajo, empleador) en los 11.
- **Ninguna alerta de adulteración** por el rótulo gris.
- **3 líneas distintas, siempre la misma**: "SEGURO OBLIGATORIO - DGI"
  (importe fijo de $380), clasificada a veces como `aporte_trabajador` y a
  veces como `otro`, en los dos sentidos. Control: el **original sin tapar
  leído tres veces** también cambia (`aporte / otro / otro`). Es la
  variación del propio modelo sobre una línea ambigua, no efecto del tapado.

Criterio cumplido: cero diferencias atribuibles al enmascarado.

### El banco de pruebas, con el documento tapado

En `/plataforma` → Uso de IA → Banco de pruebas, la casilla "Comparar
también con el documento tapado": cada modelo lee el archivo dos veces y el
tapado queda en la columna de al lado ("Claude Sonnet 4.6 — tapado"), así la
tabla línea por línea dice si tapar cambió algo. Debajo, **"Así lo recibe la
IA"**: el camino (PDF con texto, PDF escaneado, foto), las zonas, las fugas,
el tiempo del tapado y la imagen tal cual viaja. La versión tapada vuelve
rearmada, como en las rutas de verdad. Plataforma 0.38.01.

### El signo solo ya no es una diferencia

En una prueba real del banco, el original transcribió los descuentos en
positivo (como figuran en la columna Deducciones) y el tapado con signo
menos: la tabla marcaba 4 de 8 líneas en rojo con la misma clasificación.
El validador usa el valor absoluto de cada descuento, así que
`comparar_lineas` ya no cuenta el signo como diferencia -- mismo criterio que
un CUIT con o sin guiones. Afecta también la comparación entre modelos.

Las dos variaciones del modelo (la clasificación de "SEGURO OBLIGATORIO" y
el signo de los descuentos) quedaron en BACKLOG.md para el motor v2: son
exactamente el tipo de imprecisión que la confianza por renglón y el
catálogo maestro tienen que resolver.

## Enmascarado, bloque 5: en Pruebas en modo sombra, y la pantalla de registros (2026-09-24)

PR #66 mergeado a `main`: Pruebas corre el enmascarado en **modo sombra**
(`ENMASCARADO=sombra`, cargada en el servicio `mitrabajo-pruebas` con "Save
only" para que la tomara el deploy del merge). Al arrancar, el log dice
`[enmascarado] modo sombra, OCR listo`: Tesseract se instaló con pip en el
Render nativo, sin Docker, como se había medido. En sombra a la IA le sigue
llegando el original; cada documento queda anotado en `registroenmascarado`.

El CI encontró algo que en la PC no se veía: **su servidor no tiene
poppler**, así que un test que prepara un PDF original con `pdf2image` falla
ahí. Los tests del banco ahora simulan esa preparación.

### La sub-pestaña "Enmascarado" de Uso de IA

En `/plataforma` → Uso de IA → **Enmascarado**: el modo que rige en el
servidor y si hay lector de fotos; indicadores (documentos, porcentaje
tapado --en sombra, "se habría tapado"--, sin tapar, con fugas, recibos
ajenos detectados, tiempo mediano y p95); una tabla por camino (PDF con
texto, PDF escaneado, foto) con su porcentaje tapado, tiempos y espera p95;
**por qué no se tapó**, con lo que significa cada motivo ("lector ocupado"
es capacidad; "se pasó de tiempo", el presupuesto de 5 s); y la lista de
documentos con filtros por tipo, camino y resultado. Como Consumo y costo,
los números acompañan a los filtros y se calculan en la pantalla sobre las
filas que manda el servidor (las últimas 3.000; se listan 300).

El `resultado` lo resuelve el servidor (`db.registros_enmascarado`) porque
en sombra nada viaja tapado: "tapado" (activo), "se habría tapado" (sombra,
se leyó bien y había qué tapar) o "sin tapar". Plataforma 0.39.01.
