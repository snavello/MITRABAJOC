# Mesa de implementación — contrato de la API (bloques 3 y 4)

Contrato entre el agente de backend y el de pantallas. Si uno necesita
cambiarlo, edita este archivo y lo dice en su informe.

Todas las rutas resuelven quién pide con `main._actor_impl(request, pid)`
(equipo = usuario de plataforma; sindicato = `ImplUsuario`, solo su proyecto;
id ajeno → 404; sin sesión → 401). Respuestas JSON. Errores:
`{"detail": "mensaje para la persona", "codigo": "..."}` con el status que
corresponde a `implementacion.ErrorImpl` (403, 409, 400, 410).

## Página

- `GET /implementacion` → la mesa (`templates/impl_mesa.html`). El equipo sin
  proyecto elegido usa `?p={pid}`; con un solo proyecto, entra a ese. El
  sindicato entra siempre al suyo. La plantilla recibe `yo` (lado, nombre),
  `proyecto` (id, nombre), `proyectos` (solo equipo, para el selector),
  `tipos` (catálogo de `implementacion.TIPOS` en orden), `estados`.

## Datos (`/api/implementacion/p/{pid}/…`)

- `GET  resumen` → `{pendientes, esperan_otro, con_fecha, vencidas, plan_pct, etapas:[{id,nombre,orden,total,hechos,pct,tarjetas_abiertas}]}`
- `GET  tarjetas?vista=pendientes|todas&estado=&tipo=&etapa_id=&q=` → `{tarjetas:[Tarjeta]}`
- `POST tarjetas` (multipart: tipo, titulo, texto, etapa_id?, hito_id?, fecha_limite?, archivos[]?, datos_personales?) → `{tarjeta: Tarjeta}`
- `GET  tarjetas/{tid}` → `{tarjeta: Tarjeta, mensajes:[Mensaje], archivos:[Archivo], eventos:[Evento], acciones:{responder, estados:[…], solo_equipo, aprobar, reabrir, subir, reasignar}}`
  (`acciones` dice qué puede hacer ESTE actor ahora: la pantalla no decide.)
- `POST tarjetas/{tid}/responder` (multipart: texto?, estado_nuevo?, solo_equipo?, archivos[]?, datos_personales?) → igual que el GET
- `POST tarjetas/{tid}/aprobacion` (JSON: aprobar bool, texto?) → igual que el GET
- `POST tarjetas/{tid}/leido` (avisos) → `{ok:true}`
- `POST tarjetas/{tid}/reasignar` (JSON: responsable, responsable_lado) → igual que el GET
- `GET  archivos/{aid}` → el archivo (attachment); registra la descarga
- `POST archivos/{aid}/borrar` → `{ok:true}`
- `GET  carpetas?sentido=entrada|salida` → `{etapas:[{etapa, archivos:[Archivo + tarjeta_numero, tarjeta_titulo]}]}`
- `GET  aprobaciones` → `{aprobaciones:[{numero,titulo,estado,pedida_por,pedida_en,resuelta_por,resuelta_en,texto}]}`
- `GET  aprobaciones.csv`
- `GET  plan` → `{etapas:[{id,nombre,orden,pct,hitos:[{id,texto,orden,hecho,hecho_por,hecho_en,tarjetas:[{numero,titulo,estado}]}]}]}`
- `POST plan/hitos` (JSON: etapa_id, texto) — solo equipo
- `POST plan/hitos/{hid}` (JSON: hecho? , texto?, orden?, borrar?) — tildar: los dos lados; el resto solo equipo
- `POST plan/etapas/{eid}` (JSON: nombre) — solo equipo
- `GET  exportar.zip` — solo equipo: tarjetas, hilos, eventos, aprobaciones (JSON + CSV) y archivos

## Formas

- **Tarjeta**: `{id, numero, tipo, tipo_nombre, color, icono, titulo, estado, estado_nombre, espera (""|"equipo"|"sindicato"), espera_texto, me_toca (bool), etapa_id, etapa_nombre, hito_id, responsable, fecha_limite, vencida, autor_nombre, autor_lado, creada_en, actualizada_en, n_mensajes, n_archivos}`
- **Mensaje**: `{id, autor_nombre, autor_lado, texto, solo_equipo, creado_en, mio}`
- **Archivo**: `{id, nombre, mime, tamano, datos_personales, subido_por, subido_lado, subido_en, mensaje_id, borrado, puede_bajar, puede_borrar}`
- **Evento**: `{quien, lado, cuando, que, texto}` (texto ya legible)

Para el sindicato, lo «solo equipo» no viaja (ni mensajes, ni archivos, ni
eventos) y `acciones.solo_equipo` es false.

## Avisos por mail (I6)

Al crear o responder (no en notas internas), mail a los usuarios activos del
lado al que le toca: asunto con el número y el título, cuerpo con una línea y
el enlace a `/implementacion?p={pid}#t{numero}`. Nunca el texto ni archivos.
Con el canal apagado no falla nada. El equipo recibe en el mail de su
`UsuarioPlataforma` si lo tiene.

## Precisiones de la implementación (backend)

- **Archivos subidos**: el campo multipart se llama `archivos` (también vale `archivos[]`). Hasta 5 por envío, 20 MB cada uno, 40 MB en total; si algo no pasa, NO se crea la tarjeta (413 `archivo_grande`, 400 `archivo`/`archivos`).
- **Errores**: `{"detail", "codigo"}`. 403 `sin_permiso`; 409 `inmutable`, `cerrada`, `transicion`, `con_hitos`; 410 `borrado`; 413 `archivo_grande`; 400 el resto. 401 sin sesión; 404 id ajeno o inexistente. La landing entera es 404 en demo.
- `POST tarjetas` devuelve solo `{tarjeta}`; `responder`, `aprobacion` y `reasignar` devuelven el mismo cuerpo que `GET tarjetas/{tid}`.
- **`acciones.estados`** es `[{id, nombre}]` con los destinos elegibles al responder (sin «abierta»). **Reabrir** (tarjeta cerrada) va por `responder` con `estado_nuevo=abierta` (texto opcional) y se habilita con `acciones.reabrir`; en una cerrada `responder` es false.
- Un **aviso** no se responde ni admite archivos después de nacer: todas sus acciones son false. Su `GET tarjetas/{tid}` suma `lecturas: [{nombre, lado, cuando}]`; se marca leído con `POST .../leido`.
- **Plan**: `POST plan/hitos`, `plan/hitos/{hid}` y `plan/etapas/{eid}` devuelven `{ok, etapas}` (el mismo cuerpo que `GET plan`). `orden` es la posición 1..n dentro de la etapa. Tildar acepta `hecho` solo; texto/orden/borrar son solo del equipo (403 aunque vengan mezclados con `hecho`).
- **Carpetas**: cada grupo es `{etapa, etapa_id, archivos}` (`etapa` = «Sin etapa» si la tarjeta no tiene), los borrados siguen listados como constancia (`borrado: true`).
- **Aprobaciones**: suma `etapa`; `texto` es el mensaje con que se resolvió.
- **Avisos por mail**: también un **aviso** (tipo) al nacer le llega al otro lado, aunque no espere respuesta. Cerrar no avisa a nadie.
- **Equipo**: `POST /api/entornos/implementacion/proyectos/{id}/hitos-semilla` carga los 48 hitos de La Bancaria (`data/implementacion/hitos_bancaria.json`) en un proyecto sin hitos (409 si ya los tiene).
- **Lista de proyectos**: `GET /api/entornos/implementacion/proyectos` suma por proyecto `n_hitos` (int) y `tiene_hitos` (bool), contados en una sola consulta agrupada; la pestaña ofrece «Cargar hitos de La Bancaria» solo si `tiene_hitos` es false.
- **Página**: `GET /implementacion` suma al contexto `es_equipo` y `api` (`/api/implementacion/p/{pid}`); `proyecto` es `null` si el equipo no tiene proyectos todavía.

## Códigos y relaciones (I12, I13, I14)

Todo cambio es **aditivo**: `numero`, `id` y el viejo `#t{numero}` siguen valiendo.

**Códigos.** Tarjetas `PE` pedido, `CO` consulta, `EN` entrega, `AP` aprobación, `ER` error, `AV` aviso (4 dígitos: `PE0004`); archivos `AR` + 6 dígitos (`AR000123`); hitos `HI` + 4 (`HI0001`); mensajes `código de la tarjeta-orden` (`PE0004-3`). Un contador por proyecto y prefijo; nace con la cosa y no cambia nunca (un hito borrado no libera el suyo). Las etapas se nombran por su nombre. En un texto un código vale como palabra completa, en mayúsculas o minúsculas (`pe0004`, `PE0004-3`); `PE00041` o `XPE0004` no.

**Campos nuevos en las formas existentes**
- Tarjeta: `codigo`. En `GET tarjetas/{tid}` suma además `tarjeta.refs` (los códigos que nombra el título).
- Archivo: `codigo` (en el detalle, y en `carpetas`).
- Mensaje: `codigo` (`PE0004-3`; una nota interna `PE0004-N1`, ver «I15 e I16»; "" si es un mensaje anterior sin orden), `orden` (1..n **en su serie**, no en la tarjeta entera) y `refs`.
- `carpetas`: cada archivo suma `codigo` y `tarjeta_codigo`. `aprobaciones`: suma `codigo`. `plan`: cada hito suma `codigo` y cada tarjeta colgada de un hito suma `codigo`.
- `aprobaciones.csv`: una columna más al final, «Código».

**`refs` (por mensaje y en `tarjeta`)**: `[{codigo, tipo (tarjeta|archivo|hito|mensaje), enlace, existe}]`, un elemento por cada código distinto que nombra el texto, en orden. NO viaja HTML: la pantalla arma el enlace con DOM. `existe` es lo que ESTE lector puede ver. Un código inexistente, de otro proyecto o interno (para el sindicato) sale con `existe: false` y `enlace: ""`; para el sindicato las tres cosas son indistinguibles.

**`relacionadas` en `GET tarjetas/{tid}`** (también en el cuerpo de `responder`, `aprobacion` y `reasignar`, que devuelven lo mismo): `[{id, clase (menciona|responde), sentido (sale|entra), texto, tipo (tarjeta|archivo|hito|mensaje), codigo, titulo, estado, enlace, via}]`.
- `texto`: «responde a» / «respondida con» / «menciona» / «mencionada en» (`sale` = esta tarjeta es el origen, `entra` = es el destino).
- `titulo`/`estado` son los de la otra punta (archivo: nombre y `vigente|borrado`; hito: texto y `pendiente|hecho`; mensaje: título y estado de su tarjeta).
- `via`: si la relación pasa por un mensaje de ESTA tarjeta (p. ej. otra tarjeta mencionó `PE0004-2`), el código de ese mensaje; si no, "".
- El sindicato NO recibe relaciones nacidas de una nota interna ni las que apuntan a un archivo o mensaje interno.

**Rutas nuevas** (todas bajo `/api/implementacion/p/{pid}/`)
- `GET archivos/{aid}/ficha` → `{archivo: Archivo, tarjeta: {id, numero, codigo, titulo, estado}, relacionadas: [...]}`. Sin bytes y sin registrar descarga. 404 si es de otro proyecto o de una nota interna y pide el sindicato.
- `GET buscar?codigo=PE0004` → `{tipo, codigo, enlace, id, tarjeta_id, titulo}` (`tarjeta_id` es null para un hito; para un mensaje o archivo es la tarjeta que lo contiene) o **404**. El 404 es el mismo si no existe, es de otro proyecto, no es un código, o es interno y pide el sindicato.
- No se aceptan códigos donde va `{tid}`/`{aid}`: el buscador resuelve el código y la pantalla usa el id.

**Cambios en rutas existentes**
- `POST tarjetas` acepta `responde_a` (campo multipart opcional: código —`PE0004`, también `PE0004-3`— o id de una tarjeta DEL MISMO proyecto). Crea la relación `responde` (nueva → original) y los archivos subidos en esa tarjeta quedan ligados a la original (`responde`, archivo → tarjeta). Un `responde_a` inexistente o de otro proyecto es 400 `responde_a` y no se crea nada.
- `GET tarjetas?q=`: además del título, número y texto, encuentra por código (entero o parcial, mayúsculas/minúsculas): `PE0004`, `PE00`, el de un mensaje (`PE0004-3`), un archivo (`AR000123`) o un hito (`HI0001`, trae las tarjetas que cuelgan de él). El sindicato no encuentra una tarjeta por el código de algo interno.

**Menciones.** Al crear una tarjeta (título y texto) y al responder o resolver una aprobación (texto), los códigos que EXISTEN en el proyecto quedan como relación `menciona` desde la tarjeta (los de otro proyecto o inexistentes se ignoran en silencio; una tarjeta no se menciona a sí misma). Una mención escrita en una nota interna, o hacia algo que el sindicato no ve, es `solo_equipo`. Si la misma pareja se menciona después en público, deja de ser interna.

**Enlaces**: `/implementacion?p={pid}#PE0004`, `#PE0004-3`, `#AR000123`, `#HI0001`. El mail de aviso lleva el código en el asunto (`Mesa de implementación · PE0004 · #4 título`) y este enlace.

**Exportación (`exportar.zip`)**: `relaciones.json`/`relaciones.csv` (origen, clase y destino con sus códigos), `archivos.csv`, `contadores.json`; `tarjetas.csv` suma «Código» al final y los `.json` traen `codigo`/`orden`. La ruta de los archivos dentro del ZIP no cambió.

## Correcciones del QA (2026-11-14): cambios al contrato

Detalle por defecto en `QA-servidor.md` → «Correcciones». Lo que cambia para quien consume la API:

- **Aprobaciones (QA-01/02).** Una aprobación abierta la resuelve **solo el lado que NO la pidió** (`tarjeta.autor_lado`), en cualquier estado abierto y sin importar a quién le toque el turno. `acciones.aprobar` dice lo mismo que acepta el servidor (antes dependía del turno). `implementacion.puede_resolver_aprobacion(tipo, estado, autor_lado, lado_actor)` y `acciones_de(..., autor_lado)` cambiaron de firma.
- **Texto de entrada (QA-04/10).** Todo texto se sanea (sin NUL ni sustitutos sueltos, NFC, recortado) y nunca da 500. Topes (400 con mensaje): título 140, texto y `aprobacion.texto` 5.000, `responsable` y texto de hito 200, nombre de proyecto/usuario 120, mail 254, clave 128.
- **Ids (QA-05).** Un id de ruta o de `etapa_id`/`?p=` que no entra en int4 es **404**; en un campo de formulario/JSON (`etapa_id`, `hito_id`, `sindicato_id`) es **400**.
- **Envíos con archivos (QA-06/15/17).** `POST tarjetas` y `POST tarjetas/{tid}/responder` autorizan **antes** de leer el cuerpo; el cuerpo entero tiene tope de 41 MB (413 por `Content-Length` o por los bytes que llegan). Mensaje + estado + archivos se guardan en **una** transacción (si un adjunto no pasa, no cambia nada). El `mime` se reduce a `tipo/subtipo` (si no, `application/octet-stream`). Un archivo sin nombre entra como «archivo»; un campo de archivo vacío (sin nombre y sin bytes) se ignora.
- **Reasignar (QA-07).** Sobre una tarjeta cerrada es 409 `cerrada`; sobre un aviso, 400 `aviso`.
- **Fechas (QA-11).** `fecha_limite` pasa por el parseo de fechas de formulario (`AAAA-MM-DD` o `DD/MM/AAAA`) y se **guarda ISO**; si no se entiende, 400.
- **Adjuntos de una aprobación resuelta (QA-13).** No se borran: 409 `inmutable`.
- **Ritmo (QA-20).** Un usuario del **sindicato** puede crear tarjetas y responder hasta 30 veces por 10 minutos (`IMPL_RITMO_MAX`, `IMPL_RITMO_VENTANA_S`); después **429** `demasiados`. El equipo no se frena.
- **Plan (QA-26).** `plan/hitos/{hid}` valida todo (existencia, texto, orden) antes de escribir y escribe en una sola transacción.
- **Descarga y exportación (QA-21/22).** `GET archivos/{aid}` y `GET exportar.zip` siguen siendo GET (son la navegación del propio usuario con cookie `SameSite=Lax`) pero responden **403** si el navegador declara `Sec-Fetch-Site: cross-site`. La exportación suma `usuarios.json` (sin `clave_hash`); pasados los 400 MB de archivos vigentes da 413 con un mensaje que explica la salida: `exportar.zip?sin_archivos=1` baja todo menos los bytes.
- **Login del sindicato (QA-14).** El freno por IP cuenta los fallos en una ventana de 10 minutos (`IMPL_LOGIN_VENTANA_S`) y un ingreso correcto ya **no** reinicia el contador.
- **API del equipo (QA-09).** `/api/entornos/implementacion/*` exige lo mismo que la mesa: usuario de plataforma **activo**, sin clave ni datos pendientes (401 si la sesión existe y ya no vale; 403 si no es del equipo). El pase del PIN ya no la abre.
- **Mails (QA-08).** El enlace sale de la URL pública del entorno (`entorno.URLS`), nunca del header `Host`; en local no hay enlace absoluto.
- **Códigos (QA-03/18).** Se reconocen solo en ASCII, con bordes de palabra que no aceptan letras ni dígitos Unicode pegados.

## I15 e I16 (2026-11-14): lo «solo equipo» se numera aparte, y la entrega la cierra quien la recibe

Aditivo salvo lo que se marca. Los dos puntos reemplazan lo dicho antes sobre `orden` y sobre cerrar una entrega.

### I15 · Dos series, sin saltos para el sindicato

- **Mensajes.** Dentro de cada tarjeta hay dos series independientes: los públicos `orden` 1, 2, 3… con código `PE0001-3`; las notas internas (`solo_equipo`) su propia serie con código `PE0001-N1`, `PE0001-N2`. La serie pública no tiene saltos nunca. Un mensaje no pasa de público a interno (no hay ruta que lo haga), así que su código es inmutable. **Cambio de contrato:** `orden` ya no cuenta las notas internas; para el equipo hay dos mensajes con `orden: 1` (uno público y uno interno), y lo que los distingue es `solo_equipo` y el `codigo`. Se guarda sin columna nueva: `(tarjeta_id, solo_equipo, orden)`; el `orden` de cada serie se calcula con la tarjeta bloqueada.
- **Archivos.** Los subidos en una nota interna toman el contador `AI` (`AI000001`, seis dígitos); los demás, `AR`. El sindicato ve los `AR` corridos. Un archivo no cambia de serie.
- **Códigos.** `implementacion.parsear_codigo` / `extraer_codigos` / `formatear_codigo` reconocen `PE0001-N2` y `AI000001` (ASCII, mayúsculas o minúsculas; `PE0001-N0`, `PE0001-N` y `AI000001-2` no son códigos). `parsear_codigo` suma `interno: true` para esos dos casos. `implementacion.codigo_mensaje(codigo_tarjeta, orden, interno)` arma el de un mensaje.
- **El sindicato no distingue un código interno de uno inexistente**, en todas las rutas: `refs` con `existe:false` y `enlace:""`; `GET buscar?codigo=PE0001-N1` o `AI000001` da el mismo 404 que uno inventado; `GET tarjetas?q=` no los encuentra; `GET archivos/{aid}` y `.../ficha` de un `AI` dan 404; ninguna relación visible. Una mención de un código interno desde un mensaje público queda anotada como `solo_equipo` (solo el equipo la ve) y no enlaza para nadie más. El equipo los encuentra y los enlaza igual que a los demás (`#PE0001-N1`, `#AI000001`).
- **Migración** `c4e7a9b2d6f1` (ajustada en lugar de crear otra, nada estaba desplegado; sigue siendo idempotente): el backfill numera los mensajes por `(tarjeta, solo_equipo)` y da `AI` a los archivos adjuntos a una nota interna. No cambia el esquema (sin columnas ni tablas nuevas respecto de la versión anterior de esta migración).
- `exportar.zip`: `relaciones.csv` usa los códigos nuevos (`PE0001-N2`); los `.json` traen `codigo` y `orden` tal cual están guardados.

### I16 · Una entrega de archivo la cierra quien la recibe

- **Quién recibe**: el lado que NO creó la tarjeta (`tarjeta.autor_lado`). Quien la mandó puede seguir respondiendo y adjuntando otra versión, pero no darla por recibida.
- **`acciones`** suma `recibido` y `problema` (bool, iguales entre sí): true solo para el lado receptor en una entrega abierta (abierta, en curso o respondida); false para todo lo demás. El servidor acepta exactamente eso.
- **El selector de estado ya no cierra una entrega** (cambio de contrato, para los dos lados): `acciones.estados` de una entrega nunca incluye `cerrada` y `responder` con `estado_nuevo=cerrada` es 409 `transicion`. La entrega se cierra solo con `recibido`. Reabrir una cerrada sigue yendo por `responder` con `estado_nuevo=abierta` y borra el sello de recibida (la traza conserva el evento).
- **`POST tarjetas/{tid}/entrega`** (JSON `{recibido: bool, texto?}`) → mismo cuerpo que `GET tarjetas/{tid}`.
  - `recibido: true`: cierra (`estado: cerrada`, a nadie le toca), deja quién y cuándo y un evento `recibido` («dio la entrega por recibida»). `texto` opcional: si viene, queda como mensaje público.
  - `recibido: false` («hay un problema»): `texto` obligatorio (400 si falta); queda como mensaje público y un evento `problema`; la tarjeta pasa a `abierta` (desde abierta, en curso o respondida) y le toca a quien la mandó (`espera` = su lado). Pasa a abierta y no a «en curso» a propósito: en el flujo existente el turno de «en curso» se queda con quien responde, y la próxima respuesta de quien la mandó no le devolvería el turno al receptor.
  - Errores: 400 si `recibido` no es booleano, si `texto` no es texto o pasa de 5.000, si la tarjeta no es una entrega; 403 `sin_permiso` para quien la mandó; 409 `cerrada` si ya estaba cerrada; 404 de otro proyecto o inexistente (igual); 401 sin sesión; 404 en demo.
- **Mail**: solo en «problema», a quien la mandó (asunto con el código, sin el texto del problema); «recibido» no avisa a nadie, como todo cierre.
- **Registro**: `GET tarjetas/{tid}` de una entrega suma en `tarjeta` `recibida_por` y `recibida_en` ("" mientras no esté recibida o si se reabrió). Se guardan en las columnas `resuelta_por_*` / `resuelta_en` que ya usa una aprobación (sin migración).
- **Carpetas**: cada archivo de `GET carpetas` suma `tarjeta_tipo`, `recibida_por` y `recibida_en` (de la tarjeta que lo contiene; "" si no es de una entrega o no fue recibida).
- **Pantalla**: el panel «Recibido, está bien» / «Hay un problema» se dibuja solo si `acciones.recibido` / `acciones.problema`; cerrada por recepción muestra el sello «Recibida · por quién · cuándo».
