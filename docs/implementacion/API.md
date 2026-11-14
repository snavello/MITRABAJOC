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
- **Página**: `GET /implementacion` suma al contexto `es_equipo` y `api` (`/api/implementacion/p/{pid}`); `proyecto` es `null` si el equipo no tiene proyectos todavía.
