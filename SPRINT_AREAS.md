# SPRINT ÁREAS Y PERMISOS — Perfiles de acceso del sindicato

Plan acordado con el usuario el 2026-08-22, antes de tocar código.
Documenta el plan **tal cual se escribió**; no se actualiza retroactivamente
(mismo criterio que SPRINT_REFORMA.md). La fuente de verdad sobre qué está
hecho es la sección "Estado actual" de CLAUDE.md.

## El problema

Hoy todo `UsuarioSindicato` es omnipotente sobre los módulos que el
sindicato tenga habilitados. No es lo mismo crear trámites que crear
usuarios o revisar errores en recibos: hace falta que el sindicato pueda
armar sus propios perfiles de acceso, por área, sin pasar por plataforma.

## Decisiones tomadas (las 14 preguntas)

1. **Un área por usuario** — `UsuarioSindicato.area_id`, mismo patrón que
   `Trabajador.seccional_id`.
2. **Área y Seccional son independientes**, pero el usuario tiene las dos:
   se puede expresar "Legales de Rosario".
3. **La seccional filtra de verdad**: el usuario de área ve solo trámites de
   trabajadores de su seccional.
4. **La seccional pasa a ser obligatoria** (usuarios y trabajadores). Los
   `NULL` existentes migran a una seccional "Sede Central".
5. **`Seccional.ve_todas` configurable**: tildado, sus usuarios alcanzan
   todas las seccionales. Nace tildado en Sede Central; el Super Admin lo
   puede tildar en otra (ej. una regional que supervisa varias).
6. **Permisos individuales suman Y restan**: efectivo = (área + agregados)
   − bloqueados. El bloqueo le gana al área.
7. **Granularidad: secciones del panel, no módulos.** Se guarda la sección;
   en pantalla se agrupan bajo el nombre del módulo, con un check en el
   título que tilda el grupo entero.
8. **Notificaciones usa el mismo alcance seccional** que trámites. Una sola
   regla de alcance para todo el panel.
9. **El área receptora se define en el formulario** (`TipoTramite`), 1..N
   áreas. El trabajador no elige. Sin rederivación en esta tanda.
10. **Área obligatoria en el formulario**; los existentes migran a un área
    "Mesa de Entradas" creada por sindicato.
11. **Dos áreas receptoras: las dos ven, una lo toma.** Al tomarlo queda a
    cargo de esa área y la otra pasa a solo lectura, con opción de liberar.
12. **Trámites de empresa en la misma tanda** (espejo completo).
13. **El área se muestra al trabajador, la persona no.** "Respondió
    Secretaría Legal". En el panel sí se ve quién escribió.
14. **Siempre disponible**, no es módulo opt-in: es infraestructura del
    panel. Un sindicato que solo tenga su Super Admin no nota el cambio.

Decidido por defecto, corregible: el área por defecto se llama "Mesa de
Entradas" (para no reusar "Sede Central", que es nombre de seccional), y
todos los `UsuarioSindicato` que ya existen pasan a Super Admin.

## Catálogo de secciones

Cada sección declara qué módulo la habilita. Los módulos del sindicato
**filtran** qué secciones se pueden ofrecer; no son ellos el permiso.

| Sección | Módulo requerido |
|---|---|
| `reportes` | recibos |
| `formulas` | recibos |
| `conceptos` | recibos |
| `aprendizaje` | recibos |
| `cotizantes` | recibos |
| `noticias` | noticias |
| `beneficios` | beneficios |
| `notificaciones` | notificaciones |
| `tramites_recibidos` | tramites |
| `tramites_formularios` | tramites |
| `emp_empresas` | empleadores |
| `emp_notificaciones` | empleadores |
| `emp_tramites_recibidos` | empleadores |
| `emp_tramites_formularios` | empleadores |
| `trabajadores` | — (siempre ofrecible) |
| `seccionales` | — (siempre ofrecible) |

`areas_usuarios` NO es asignable: es exclusiva del Super Admin.

Dos aperturas que no estaban en la conversación y salieron de leer el
panel, porque cambian qué se puede expresar:

- **Trámites se abre en "recibidos" y "crear formularios"** (ya son dos
  subpestañas). Un usuario de área tiene que poder responder trámites sin
  poder diseñar formularios — sobre todo porque el área receptora se define
  ahí: si pudiera editar el formulario, podría autoasignarse trámites.
- **Empleadores se abre en sus 3 subpestañas** (Empresas / Notificaciones /
  Trámites), que hoy viven todas bajo un único módulo.

Los módulos `aportes`, `credencial` y `capacitacion` no generan ninguna
sección: son solo del lado del trabajador.

## Modelo de datos

```
Area                     id, sindicato_id, nombre, activo
PermisoArea              id, area_id, seccion
PermisoUsuario           id, usuario_id, seccion, tipo ("agregar"|"bloquear")
AreaTipoTramite          tipo_tramite_id, area_id
AreaTipoTramiteEmpleador tipo_tramite_id, area_id

Seccional                + ve_todas: bool = False
UsuarioSindicato         + es_super_admin: bool, area_id, seccional_id
TipoTramite              (áreas vía AreaTipoTramite, obligatorio >= 1)
Tramite                  + area_a_cargo_id (nullable = nadie lo tomó)
TramiteEmpleador         + area_a_cargo_id
NotaTramite              + usuario_sindicato_id (hoy solo guarda "admin")
NotaTramiteEmpleador     + usuario_sindicato_id
```

## Fases

Bloques chicos, verificando de verdad, commit local por fase y push al final.

### Fase 1 — Modelo y cálculo de permisos (sin UI)
- Migración Alembic con todo el modelo de arriba.
- Grandfathering: `UsuarioSindicato` existentes → `es_super_admin=True`.
- Por sindicato: crear Seccional "Sede Central" (`ve_todas=True`) y Área
  "Mesa de Entradas". Trabajadores con `seccional_id` NULL → Sede Central.
- `permisos.py` con el catálogo SECCIONES y su módulo requerido.
- `db.permisos_efectivos(usuario_id)` y `db.alcance_seccional(usuario_id)`.
- Tests: suma/resta, filtrado por módulos del sindicato, grandfathering.

### Fase 2 — Gateo del backend (50 rutas `/admin/*`)
- `_exigir_permiso(request, seccion)` y `_exigir_super_admin(request)`,
  mismo criterio defensivo que `_exigir_modulo`.
- Clasificar las 50 rutas. **Los permisos se leen de la base en cada
  request, nunca del token**: si van en la cookie, revocar no tiene efecto
  hasta que venza la sesión.
- Arreglar el guard del último admin: hoy cuenta cualquier usuario activo,
  y con usuarios de área permitiría desactivar al último Super Admin. Pasa
  a contar Super Admins, y cubre también el caso de degradar al último.
- Test que recorre `app.routes` y falla si alguna ruta `/admin/*` no
  declara sección: es la única forma de que no se escape ninguna de 50.

### Fase 3 — UI de Áreas y Usuarios
- Pestaña "Administradores" → "Áreas y Usuarios", solo Super Admin.
- CRUD de Áreas y CRUD de permisos por área.
- Alta/edición de usuario: área + seccional + permisos tri-estado
  (hereda / agregado / bloqueado), agrupados por módulo.
- Check `ve_todas` en el CRUD de Seccionales.
- La tira de pestañas se arma con los permisos efectivos.

### Fase 4 — Trámites por área (trabajador)
- Áreas receptoras en el alta de `TipoTramite`, obligatorio.
- `area_a_cargo_id` + botones tomar / liberar en el chat.
- Bandeja filtrada por área + alcance seccional.
- `NotaTramite.usuario_sindicato_id`; el trabajador ve el área, no la
  persona; el panel ve las dos.

### Fase 5 — Espejo en trámites de empresa
Lo mismo de la Fase 4 sobre `TipoTramiteEmpleador` / `TramiteEmpleador`.

### Fase 6 — Notificaciones, demo y documentación
- Destinatarios recortados por alcance seccional (trabajador y empresa).
- `cargar_demo.py`: áreas, permisos y un usuario de área de ejemplo.
- CLAUDE.md + HISTORIAL.md + `version.py` (arreglos + funcionalidad nueva:
  +1 en release y en patch).

## Riesgos conocidos

- **Los tests existentes se van a romper.** Ya pasó al sumar módulos: las
  fixtures crean `UsuarioSindicato` sin los campos nuevos, y con seccional
  obligatoria también las que crean `Trabajador`. Hay que revisarlas en la
  Fase 1, no descubrirlo en la 4.
- **Migración destructiva de seccionales.** Pasar los NULL a Sede Central
  se corre sobre la base de producción de Render. Probar primero en el
  Postgres local vía Docker, que para eso está.
- **50 rutas es la parte cara**, no el modelo de datos. Si hay que recortar
  alcance, la Fase 5 (espejo de empresa) es lo único postergable sin dejar
  el sistema a medias.
