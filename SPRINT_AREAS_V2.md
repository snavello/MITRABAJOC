# SPRINT ÁREAS V2 — Perfiles, seccionales y trámites granulares

Plan acordado con el usuario el 2026-09-11, antes de tocar código.
Reemplaza a `SPRINT_AREAS.md`, que queda como registro de la primera tanda
(rama `areas-permisos`, terminada el 2026-08-22 y nunca mergeada). Igual que
aquel: documenta el plan **tal cual se escribió** y no se actualiza
retroactivamente. La fuente de verdad sobre qué está hecho es "Estado
actual" de CLAUDE.md.

## Por qué hay un plan nuevo y no un merge

`areas-permisos` está terminada y probada (6 fases, ~4.340 líneas, 86 tests)
pero quedó **126 commits detrás de `main`**: rama en 0.14.20 del 22-ago,
`main` en 0.29.x del 07-sep. En el medio entraron RAG del convenio,
Asistente del Panel, Dashboard sindical, PWA/push, validaciones de trámites
y la landing de entornos.

Medido, no estimado: el merge da **8 archivos en conflicto** — `db.py` 14
hunks, `main.py` 12, `templates/admin.html` 10 — y deja **28 rutas
`/admin/*` sin clasificar** que, por el fail-closed de la Fase 2, se
rechazarían solas con un error inexplicable (todo `/admin/dashboard*`,
`/admin/convenio*`, `/admin/tramite-tipo/probar`). El BACKLOG anotaba "5
líneas para RAG"; son 28 rutas y tres secciones nuevas del catálogo.

Como además los requerimientos nuevos cambian el modelo de `Area` y el
ruteo de trámites, **se porta sobre `main` en vez de mergear**: la Fase 0 es
exactamente la primera tanda reescrita sobre el código de hoy, y recién
después entran las decisiones nuevas.

## Premisas

1. **Solo esta funcionalidad.** Nada más del backlog entra a esta tanda.
2. **No poner en peligro la demo.** Los administradores de hoy conservan
   exactamente los accesos de hoy: todos migran a Super Admin (= Admin de
   Sede Central). Un sindicato que no configure nada no nota el cambio.

## Decisiones tomadas

Las 14 de `SPRINT_AREAS.md` siguen vigentes salvo donde estas las pisan.

### Estructura y personas

**N1. Identidad vinculada por CUIL.** `UsuarioSindicato` gana `cuil` y un
vínculo opcional a su fila de `Trabajador`. El alta del operador se hace
eligiendo un afiliado del padrón o cargando a alguien de afuera. **Cada
identidad mantiene su login actual** — el panel entra por usuario/clave, el
trabajador por CUIL — pero el sistema sabe que son la misma persona.
Descartado unificar el login: toca el flujo de sesión que está en demo.

**N2. El área pertenece a una seccional.** `Area.seccional_id` obligatorio.
Un área es "Legales de Sede Central" o "Legales de Rosario", no un área
suelta del sindicato. Es el cambio de fondo contra la primera tanda, donde
`Area` colgaba del sindicato.

**N3. Tres roles, no dos.**
- **Admin de Sede Central** (`es_super_admin`): ve todos los módulos que el
  sindicato tiene contratados; crea seccionales; crea áreas en Sede Central
  y también en cualquier seccional; asigna usuarios a área y seccional; y
  crea Admins de Seccional. Es el rol que ya existe — los admins de hoy son
  estos.
- **Admin de Seccional** (`es_admin_seccional`): las mismas atribuciones,
  con alcance **solo local**. Es "el admin grande en chiquito".
- **Usuario de área**: lo que le dan su área y sus permisos individuales.

**N4. Anti-escalada del admin local** (heredado del backlog, decisión
cerrada): no otorga Super Admin ni `ve_todas`, no toca usuarios de otras
seccionales, y **solo puede dar secciones que él mismo tiene**.

**N5. La granularidad se conserva tal cual.** El área trae secciones del
panel y a cada usuario se le puede agregar o bloquear una suelta:
efectivo = (área + agregados) − bloqueados. Sobrevive `permisos.py`
completo, `PermisoArea`, `PermisoUsuario` y la UI de tres estados. Es la
parte más cara de la primera tanda y ya está escrita y probada.

### Trámites

**N6. El destino se mapea seccional por seccional.** El formulario declara,
para cada seccional, qué área lo recibe. **Con un destino por defecto
obligatorio** ("las demás seccionales", típicamente un área de Sede
Central): sin él el formulario no se guarda. Así una seccional nueva
funciona desde el minuto cero y ningún trámite queda sin dueño.

Descartadas: la adhesión obligatoria a un área troncal (`area_madre_id`,
que era lo que el backlog traía cerrado) y el destino central único. Gana
precisión a costa de mantener el mapa, y el destino por defecto es lo que
evita que ese mantenimiento se vuelva eterno.

**N7. Formularios propios de la seccional.** `TipoTramite.seccional_id`
nullable (null = global). El admin local crea SUS formularios y no edita
los globales; el trabajador ve los globales más los de su seccional. Sin
esto el admin local tiene áreas y gente pero no puede armar un trámite
propio, que es justo lo que el rol viene a resolver.

**N8. Pase entre áreas, declarado en el formulario.** El formulario tilda
"permite pase" y **declara la lista cerrada de áreas a las que puede ir**.
Sin ese tilde, el área solo puede contestarle al trabajador.
- El pase **transfiere**: la que recibe queda a cargo y es la única que
  puede responder; la que derivó **conserva lectura** del expediente.
- **Permite cadena**: la nueva área puede volver a derivar dentro de los
  destinos declarados, incluido devolverlo al área anterior.
- **Siempre hay exactamente un área responsable.**
- **Cada movimiento queda en el chat**, visible para el trabajador como
  movimiento del expediente.

**N9. Responder y cambiar estado son UN SOLO ACTO.** Hoy
`/admin/tramite/{id}/estado` y `/admin/tramite/{id}/nota` son dos rutas y
**cada una escribe su propia línea en el chat**: un solo acto real aparece
dos veces. Pasa a haber una sola operación — se escribe la respuesta y se
elige el estado junto — y **la ruta de estado suelto desaparece**. No queda
ninguna forma de mover el estado sin mensaje.

### Alcance

**N10. Una sola regla de alcance, para escribir Y para ver.** Un usuario
alcanza a los trabajadores de su seccional, salvo que su seccional tenga
`ve_todas`. Eso ya regía para trámites y notificaciones; ahora rige también
para **Noticias y Beneficios** (hoy `_destinos_validos` filtra solo por
sindicato) y para **el historial**: cada uno ve las notificaciones de
aquellos a quienes podría escribirles, con la lista de destinatarios
recortada a su alcance.

> Prensa de Sede Central le escribe a todo el país y ve todo el historial.
> Prensa de Córdoba le escribe solo a Córdoba y ve solo eso.

Esto cierra la decisión que quedó pendiente en `BACKLOG.md` (entrada 3). Y
sigue valiendo lo de siempre: para mandar notificaciones, el módulo tiene
que estar contratado — los módulos filtran qué secciones se pueden ofrecer.

**N11. Trámites de empresa quedan afuera de esta tanda.** `Empleador` no
tiene seccional, así que el mapa por seccional no le aplica y mapear
empresa→seccional es un sprint en sí mismo. Siguen como hoy: sin área, sin
pase y con el estado separado de la respuesta. Es lo que el plan original
ya marcaba como "lo único postergable sin dejar el sistema a medias".

## Modelo de datos (deltas contra `main`)

```
Area                      id, sindicato_id, seccional_id, nombre, activo   [NUEVA]
PermisoArea               area_id, seccion                                 [NUEVA]
PermisoUsuario            usuario_id, seccion, tipo ("agregar"|"bloquear") [NUEVA]

Seccional                 + ve_todas: bool = False
UsuarioSindicato          + es_super_admin: bool = False
                          + es_admin_seccional: bool = False
                          + area_id, seccional_id
                          + cuil, trabajador_id (vínculo opcional)

TipoTramite               + seccional_id (nullable = global)
                          + permite_pase: bool = False
                          + area_destino_default_id (obligatorio)
DestinoTipoTramite        tipo_tramite_id, seccional_id, area_id           [NUEVA]
PaseTipoTramite           tipo_tramite_id, area_id                         [NUEVA]

Tramite                   + area_a_cargo_id
PaseTramite               tramite_id, area_origen_id, area_destino_id,
                          usuario_id, creado                               [NUEVA]
NotaTramite               + usuario_sindicato_id
                          + estado_nuevo   (el estado que fijó ESE mensaje)
```

`estado_nuevo` en la nota es lo que hace que N9 no se pueda desincronizar:
el estado no vive en una tabla aparte del mensaje que lo cambió, así que no
hay forma de que el chat muestre una cosa y el expediente otra.

## Fases

Bloques chicos, verificando de verdad contra Postgres y la app real, commit
local por fase y push al final. **Nada se deploya a Demo hasta cerrar el
sprint** (premisa 2).

### Fase 0 — Portar `areas-permisos` sobre `main`
Sin funcionalidad nueva: el panel tiene que quedar idéntico para un Super
Admin. Es la fase más cara y la que más hay que verificar.
- `permisos.py`, modelos, `permisos_efectivos()`, `alcance_seccional()`.
- Gateo dentro de `exigir_sindicato()` vía `PERMISOS_RUTAS`.
- **Clasificar las 78 rutas `/admin`** (eran 56). Secciones nuevas en el
  catálogo: `dashboard`, `convenio`, `asistente`.
- UI de "Áreas y Usuarios", con el recorte de consultas por permiso (no
  alcanza con esconder la pestaña: los datos viajan en el HTML).
- Traer `correr_suite.sh`, que no está en `main`.
- Migración con grandfathering: usuarios existentes → Super Admin, "Sede
  Central" (`ve_todas`) y "Mesa de Entradas" por sindicato, trabajadores
  sin seccional → Sede Central.
- Reparar las fixtures de test (36 en 23 archivos la vez pasada).

### Fase 1 — Áreas por seccional y el rol de Admin de Seccional
`Area.seccional_id`, `es_admin_seccional`, las reglas anti-escalada (N4), y
el CRUD de áreas que el admin local puede usar dentro de su seccional.
Migración: las áreas que la Fase 0 creó quedan en Sede Central.

### Fase 2 — Identidad del empleado de sindicato
`cuil` + vínculo a `Trabajador` en el alta y la edición del operador, con
las dos formas de alta (elegir del padrón / cargar de afuera).

### Fase 3 — Ruteo de trámites
Mapa seccional→área en el alta del formulario, destino por defecto
obligatorio, `TipoTramite.seccional_id`, y la bandeja filtrada por los dos
ejes (área ∩ alcance seccional). Migración: los tipos existentes quedan con
destino por defecto = Mesa de Entradas de su sindicato.

### Fase 4 — Pase entre áreas
Lista de destinos en el formulario, botón de pase en el chat, transferencia
con cadena, lectura para el área que derivó, y el movimiento reflejado en
el chat del trabajador.

### Fase 5 — Responder y estado en un solo acto
Fusión de las dos rutas, `NotaTramite.estado_nuevo`, y el chat mostrando un
movimiento por acto real. Baja de `/admin/tramite/{id}/estado`.

### Fase 6 — Alcance único, demo y documentación
Noticias/Beneficios recortados, historial de notificaciones acotado (N10),
el 403 por permiso dejando de mostrar JSON crudo, `cargar_demo.py` con
seccionales/áreas/usuarios de ejemplo, CLAUDE.md + HISTORIAL.md + versión.

## Riesgos conocidos

- **La Fase 0 es el sprint entero otra vez.** Portar no es mergear: hay que
  releer cada hunk contra código que cambió abajo. Si algo se recorta, se
  recorta de las fases 4-6, nunca de la 0.
- **Una ruta nueva sin clasificar nace cerrada.** Es lo correcto, pero
  mientras dure el port va a aparecer como "el panel me rechaza sin
  motivo". El test que recorre `app.routes` es lo que lo convierte en un
  error de test y no en un bug de producción.
- **Las fixtures se rompen en cada fase**, cada vez que un campo pasa a ser
  obligatorio. Revisarlas al principio de cada fase, no al final.
- **El mapa por seccional es superficie de mantenimiento.** El destino por
  defecto obligatorio es la red; si en el uso real el mapa termina siendo
  siempre el default, conviene revisar la decisión N6.
- **Migración sobre la base de Demo.** Probar el ciclo completo
  (upgrade → downgrade → upgrade con datos) en el Postgres local antes de
  tocar nada desplegado. La vez pasada eso destapó que el downgrade perdía
  `ve_todas` en silencio.
