# XSII, bloque 1: contrato de API y reglas

Contrato entre el servidor y la pantalla del bloque 1 de `PLAN_XSII.md`
(tablas, registro, decisiones, insumos y las tres vistas). Sin IA: estados y
paso recomendado salen del motor. Lo que acá no esté escrito, no existe.

## Puertas

- Todo es **404 en demo** (`_exigir_landing()`), vive en Pruebas (X17).
- **Solo el equipo** (X16, X18): la API usa `_impl_equipo_api(request)` (la
  misma definición de «equipo» que la Mesa: usuario de plataforma nominal,
  activo, sin clave ni datos pendientes). Cualquier rol de plataforma, no solo
  superadmin. 401 sesión vencida, 403 no es del equipo. Devuelve el `Actor`
  (id y nombre) que va a toda traza.
- La página usa `_exigir_pase` (como las Herramientas) y, si no hay usuario
  nominal del equipo, muestra un aviso en vez de la pantalla.
- Se abre **por proyecto de la Mesa**: `pid` es `ImplProyecto.id`
  (`IdImpl`: un id fuera de int4 es 404). Un proyecto que no existe es 404.
  El sindicato sale de `ImplProyecto.sindicato_id`, nunca de un parámetro.

## Cambios en el motor (`xsii/motor`, sigue puro)

1. **Varias decisiones por tarea.** `hechos["decisiones"]` pasa a ser
   `{codigo: [decisión, ...]}` (las ACTIVAS; como mucho una por tipo). Se sigue
   aceptando un dict suelto (se toma como lista de uno). `EstadoTarea` suma
   `decisiones` (la lista) y conserva `decision` = la que determina el estado
   (`no_aplica`, `completada_a_mano` o `confirmada`), o None.
2. Precedencia, sin cambios de fondo: no aplica por condición → `no_aplica`
   declarada → hecha por control (pasa y, si lleva confirmación, tiene
   `confirmada`) → `completada_a_mano` (hecha, `a_mano=True`) → resto.
   `pospuesta` es una marca: no cambia el estado, saca a la tarea de
   recomendada y alternativas. Puede convivir con `confirmada`.
3. **Insumo sin registrar con datos cargados** (pendiente del bloque 0). Un
   insumo sin registrar NO deja la tarea «esperando un dato» si el control ya
   muestra datos: `control.en_curso`, o `control.pasa` en una tarea que no es
   `solo_confirmacion`. En ese caso el estado se calcula como si el insumo
   estuviera, y `EstadoTarea.insumos_sin_registrar` lista esas claves (la
   pantalla avisa «hay datos cargados; el insumo no está registrado»). En una
   `solo_confirmacion` (REC-01, PAD-01) el control no calcula nada: sin insumo
   registrado sigue «esperando».
   **Tampoco está «hecha» por control ni por confirmación** una tarea con
   insumos sin registrar y sin datos cargados: una confirmación previa no la
   da por hecha (sigue «esperando un dato») y `falta_confirmar` es falso si ya
   está confirmada. `completada_a_mano` sigue valiendo sin insumo (válvula de X15).
4. `consulta.a_json` suma por tarea `decisiones` e `insumos_sin_registrar`;
   `resumen` no cambia de forma.

## Catálogo de Colm3na

`xsii/proyectos/colm3na/catalogo.py` suma `INSUMOS = {clave: {"nombre",
"descripcion"}}` para las cuatro claves que usan las tareas
(`lista_seccionales`, `recibos_muestra`, `porcentajes_cuota`,
`planilla_padron`). Un test falla si una tarea nombra un insumo que no está.

## Tablas (prefijo `xsii`, migración de Alembic, `down_revision = f7b1d3e5a9c2`)

Datos reales de Pruebas, como la Mesa: sin claves foráneas hacia el resto,
fuera de `clonar_demo_a_pruebas.py` (patrón `xsii*`) y del borrado de un
sindicato; `db.XSII_TABLAS` + test fail-closed como `IMPL_TABLAS`. Migración
idempotente. Ninguna columna lleva CUIL/CUIT (declararlo en el inventario de
`regularizar_cuit.py` si su test lo pide). JSON con `db.JSON_TIPO`.

- **`XsiiDecision`**: `id`, `proyecto_id` (idx), `codigo`, `tipo`
  (`confirmada` / `completada_a_mano` / `no_aplica` / `pospuesta`), `motivo`,
  `quien_id`, `quien_nombre`, `cuando`, `activa` (bool), `deshecha_por_id`,
  `deshecha_por_nombre`, `deshecha_cuando`, `deshecha_motivo`. Índice único
  parcial `(proyecto_id, codigo, tipo) WHERE activa`. Deshacer NO borra: pone
  `activa=False` con quién y cuándo.
- **`XsiiInsumo`**: `id`, `proyecto_id` (idx), `clave`, `estado` (`pedido` /
  `recibido`), `tarjeta_id` (opcional, `ImplTarjeta.id` del MISMO proyecto),
  `archivo_id` (opcional, `ImplArchivo.id` del mismo proyecto), `nota`,
  `quien_id`, `quien_nombre`, `cuando`, `activa`, `retirado_por_id`,
  `retirado_por_nombre`, `retirado_cuando`. Índice único parcial
  `(proyecto_id, clave) WHERE activa`.
- **`XsiiMovimiento`** (traza, inmutable como `ImplEvento`): `id`,
  `proyecto_id` (idx), `codigo` (tarea, puede ser vacío), `tipo`, `texto`
  (frase armada por el servidor), `cantidades` (JSON, `{}` si no hay),
  `quien_id`, `quien_nombre`, `cuando`. Tipos: `decision`,
  `decision_deshecha`, `insumo_pedido`, `insumo_recibido`, `insumo_retirado`.
  Cada escritura de las otras dos tablas deja su movimiento en la MISMA
  transacción.

Funciones en `db.py` con prefijo `xsii_` (reciben la sesión). Fechas con
`fechas.py`. Textos de persona por `implementacion.limpiar_texto`.

## Reglas de las decisiones (las decide el servidor)

| Tipo | Motivo | Se puede si |
|---|---|---|
| `confirmada` | no se pide | la tarea declara `confirmacion`, aplica, su control pasa y no le falta un insumo sin datos cargados (si no: «Primero registrá que llegó el insumo.») |
| `completada_a_mano` | **obligatorio** | aplica (no «no aplica» por condición ni declarada) y no está hecha por control |
| `no_aplica` | **obligatorio** | no es «no aplica» por condición y no tiene `completada_a_mano` activa |
| `pospuesta` | opcional | no está resuelta (ni hecha ni no aplica) |

- Motivo: de 5 a 500 caracteres ya saneado. Falta o corto → 400 «El motivo es
  obligatorio (al menos 5 caracteres).»
- Ya hay una activa de ese tipo → 409. Condición no cumplida → 409 con la
  frase que explica por qué. Dos pedidos a la vez: las escrituras de una tarea
  se serializan con un candado de transacción (`pg_advisory_xact_lock`) y las
  decisiones activas se releen y revalidan ADENTRO del candado (duplicado y
  exclusión `completada_a_mano` / `no_aplica`): el segundo es 409, nunca 500.
- El largo mínimo del motivo se mide sin espacios ni caracteres invisibles o de
  formato (U+200B, U+FEFF, U+00AD, U+2800…): hecho solo de eso, 400.
- Deshacer: cualquiera activa, por cualquier usuario del equipo; motivo
  opcional (mismo tope). No hay activa → 409.
- Nada de esto cambia lo que el control calcula: la ficha muestra las dos
  cosas (X15).

## Rutas

Base `X = /api/entornos/xsii`. Todas JSON; errores `{"detail": "frase"}`.
Los POST reciben JSON con `Content-Type: application/json`; sin ese
encabezado, o con un cuerpo que no es un objeto → 400.

### `GET X/proyectos`
```json
{"proyectos": [{"id": 1, "nombre": "La Bancaria", "activo": true,
                "sindicato_id": 7, "sindicato_nombre": "La Bancaria"}]}
```
`sindicato_nombre` null si el proyecto no tiene sindicato o ya no existe.

### `GET X/p/{pid}/tablero`
```json
{
  "proyecto": {"id": 1, "nombre": "…", "sindicato_id": 7, "sindicato_nombre": "…",
               "mesa_url": "/implementacion?p=1"},
  "disponible": true,
  "motivo": "",
  "grupos": ["Base", "Estructura", "…"],
  "rotulos": {"estados": {"hecha": "Hecha", "lista": "Se puede hacer", "en_curso": "En curso",
                          "esperando": "Esperando un dato", "bloqueada": "Bloqueada", "no_aplica": "No aplica"},
              "modos": {"asistida": "Asistida", "herramienta": "Con herramienta",
                        "aplicacion": "Por la aplicación", "manual": "Manual", "automatica": "Automática"},
              "decisiones": {"confirmada": "Confirmada", "completada_a_mano": "Completada a mano",
                             "no_aplica": "No aplica", "pospuesta": "Pospuesta"}},
  "resumen": {"total": 34, "aplican": 30, "resueltas": 9, "porcentaje": 30,
              "por_confirmar": 2, "a_mano": 1, "con_observaciones": 1, "pospuestas": 1,
              "por_estado": {"hecha": 9, "lista": 6, "en_curso": 2, "esperando": 3, "bloqueada": 10, "no_aplica": 4}},
  "recomendada": {"codigo": "EST-01", "por_que": "Es la que más destraba: 14 tareas dependen de esta.",
                  "destraba": 14, "como": "La preparo yo y vos confirmás antes de guardar."},
  "alternativas": ["BAS-02", "COM-02", "REC-06"],
  "demorados": [{"clave": "planilla_padron", "nombre": "Planilla del padrón", "codigo": "PAD-01",
                 "dias": 3, "tarjeta": {"codigo": "PE0007", "titulo": "…"}, "frena": 9}],
  "tareas": [ /* una por tarea, ver abajo, en orden de catálogo */ ],
  "movimientos": [ /* los últimos 8, forma de abajo */ ]
}
```
- `disponible: false` (proyecto sin sindicato, o el sindicato ya no existe):
  `motivo` lo explica y `tareas`, `alternativas`, `demorados` van vacíos,
  `recomendada` null, `resumen` null.
- `recomendada` null si no queda nada para hacer ahora. `por_que` y `como` los
  arma el servidor: en curso → «Ya está empezada: conviene terminarla.»;
  falta confirmar → «Solo falta que la confirmes.»; si no, cuántas destraba.
  `como` depende del modo (asistida: en el bloque 1 todavía no hay asistente,
  así que dice «Se hace en la pantalla de siempre; acá controlo el resultado.»).
- `demorados`: insumos en estado `pedido` (no recibidos) de tareas sin
  resolver, pedidos hace **2 días o más**, con los días desde que se pidió y cuántas tareas frena
  (`que_destraba` transitivo de su tarea + 1). Orden: más días primero.

**Cada tarea**:
```json
{
  "codigo": "PAD-02", "nombre": "Padrón cargado", "grupo": "Padrón", "modo": "asistida",
  "descripcion": "…", "aplica_si": null,
  "estado": "bloqueada", "con_observaciones": false, "a_mano": false, "pospuesta": false,
  "no_aplica_por": "", "falta_confirmar": false, "confirmacion": "La cantidad cargada coincide…",
  "detalle": "Espera a Seccionales y Padrón recibido",
  "necesita": ["EST-01", "PAD-01"], "mejora_con": [], "frenada_por": ["EST-01", "PAD-01"],
  "avisos": [], "camino": ["EST-01", "PAD-01"],
  "necesitada_por": ["PAD-03", "TRA-02", "COM-04", "COM-06", "CIE-01"],
  "destraba": {"directo": ["PAD-03"], "transitivo": ["PAD-03", "TRA-02"]},
  "nivel": 2,
  "donde": {"url": "/admin#trabajadores", "rotulo": "Panel del sindicato · Trabajadores"},
  "control": {"estado": "incompleta", "resumen": "El padrón está vacío.",
              "cifras": [{"clave": "afiliados_activos", "nombre": "Afiliados activos", "valor": 0}],
              "faltan": ["Cargar el padrón"], "en_curso": false},
  "decisiones": [{"tipo": "pospuesta", "motivo": "…", "quien": "snavello", "cuando": "2026-11-26 22:10:05"}],
  "insumos": [{"clave": "planilla_padron", "nombre": "Planilla del padrón", "descripcion": "…",
               "estado": "falta", "sin_registrar": false, "dias": null, "nota": "",
               "quien": "", "cuando": "",
               "tarjeta": null}],
  "acciones": {"confirmar": false, "completar_a_mano": true, "no_aplica": true, "posponer": true,
               "deshacer": []}
}
```
- `detalle`: una línea para la tabla, armada por el servidor: bloqueada →
  «Espera a A y B» (nombres); esperando → «Falta: <insumo>» (+ «pedido hace N
  días (PE0007)»; «pedido hoy», «pedido ayer» o «pedido hace N días»); no aplica → «Módulo X no contratado» o «Declarada no
  aplica: motivo»; falta confirmar → «Falta confirmar: …»; a mano →
  «Completada a mano por X: motivo»; si no, `control.resumen`.
- `control.cifras` es una LISTA (el orden es del servidor) con nombre legible
  (la clave con guiones bajos a espacios y mayúscula inicial).
- `camino`: lo no resuelto que hay que hacer antes, en orden (`que_frena`);
  vacío (igual que `frenada_por`) si la tarea está hecha o no aplica.
  `necesitada_por`: TODAS las que la necesitan directo (para el mapa);
  `destraba`: solo las no resueltas.
- `nivel`: 0 si no necesita a nadie; si no, 1 + el mayor nivel de lo que
  necesita (columnas del mapa).
- `donde`: null si la tarea no tiene pantalla. `rotulo` legible
  (`/plataforma` → «Plataforma»; `/admin#x` → «Panel del sindicato · X»;
  `/entornos/herramientas/x` → «Herramientas · X»; `/app` → «App del
  afiliado»; `/implementacion` → «Mesa de implementación», con `?p=pid`).
- `insumos[].estado`: `recibido`, `pedido` o `falta`. `tarjeta`: null o
  `{"id", "codigo", "titulo", "estado", "url"}` (`url` = la Mesa del
  proyecto). `dias`: días desde que se pidió (solo `pedido`).
  `sin_registrar: true` cuando no está registrado pero el control ya muestra
  datos (regla 3 del motor).
- `acciones`: lo que este usuario puede hacer AHORA según la tabla de reglas;
  `deshacer` es la lista de tipos activos que se pueden deshacer. La pantalla
  no decide permisos.

### `GET X/p/{pid}/tarea/{codigo}`
`{"tarea": {…misma forma…}, "historial": [movimientos de esa tarea y de sus
insumos, del más nuevo al más viejo, hasta 50]}`. Código inexistente → 404.

### `POST X/p/{pid}/tarea/{codigo}/decision`
Cuerpo `{"tipo": "completada_a_mano", "motivo": "…"}`. Respuesta
`{"ok": true, "tarea": {…}, "resumen": {…}}`. Tipo desconocido → 400.

### `POST X/p/{pid}/tarea/{codigo}/decision/deshacer`
Cuerpo `{"tipo": "pospuesta", "motivo": ""}`. Misma respuesta.

### `POST X/p/{pid}/insumo/{clave}`
Cuerpo `{"estado": "recibido" | "pedido", "tarjeta": "PE0007", "nota": "…"}`.
`tarjeta` opcional: código (o id, hasta 20 caracteres) de una tarjeta de ESE
proyecto (`db.impl_tarjeta_por_codigo_o_id`); no existe en el proyecto o es
más larga → 400 «No
encontré esa tarjeta en la Mesa de este proyecto.» `nota` hasta 500. Reemplaza
el registro activo (el anterior queda inactivo; pasar de `pedido` a
`recibido` conserva la tarjeta si no se manda otra). Clave fuera de
`INSUMOS` → 404. Respuesta `{"ok": true, "insumo": {…forma de insumos[]…}}`.

### `POST X/p/{pid}/insumo/{clave}/retirar`
Saca el registro activo (queda la traza). Sin activo → 409.

### `GET X/p/{pid}/movimientos?codigo=&limite=`
`{"movimientos": [{"id": 9, "codigo": "PAD-02", "tipo": "decision",
"texto": "Completó a mano Padrón cargado: se carga en la segunda etapa",
"cantidades": {}, "quien": "snavello", "cuando": "2026-11-26 22:10:05"}]}`.
Del más nuevo al más viejo; `limite` 1 a 200 (50 por defecto). `codigo` se
sanea; si no es una tarea del catálogo, `{"movimientos": []}` (200).

## Página

`GET /entornos/xsii` → sin pantalla propia: con un solo proyecto redirige (303)
a él; con varios o ninguno, a `/entornos#implementacion` (la pestaña lista los
proyectos).
`GET /entornos/xsii/{pid}` (el `pid` llega como texto y se valida después de la
puerta de demo: en demo siempre 404; no numérico o inexistente, 404) → `templates/xsii.html` con el contexto
`{"request", "pid", "proyecto_nombre", "es_equipo": bool, "entorno"…}`; la
pantalla pide el tablero por la API. Estáticos en `static/xsii/` (`xsii.css`,
`xsii.js`) con `sello_static`. Vista inicial por `?vista=guia|tablero|mapa` y
tarea abierta por `?tarea=PAD-02` (la pantalla mantiene la URL con
`history.replaceState`). La pestaña Implementación de `/entornos` suma, por
proyecto, el botón «Abrir XSII».

## Qué NO entra en el bloque 1

IA y «Preguntame» (el botón se dibuja deshabilitado, con «Llega en el
próximo bloque»), acciones asistidas y ensayos, crear tarjetas de la Mesa
desde XSII («Reclamar en la Mesa» es un enlace a la Mesa), hitos propuestos.
