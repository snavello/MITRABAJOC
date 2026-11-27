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

---

# Bloque 2: «Preguntame» y reclamar un dato

Decisiones de SDN (2026-11-27): el modelo por defecto es **Sonnet 5.5**
(`claude-sonnet-5-5`, elegible en `/plataforma`) y el bloque incluye
**reclamar un dato en la Mesa** además de la lectura. Sin clave de API el
tablero, los controles y el reclamo siguen andando; solo «Preguntame» se apaga.

## Principios

- **No es un chat** (X10): una pregunta por vez, sin historial, sobre UN punto
  (el paso recomendado, una tarea, el mapa). Cada pedido es independiente.
- **La IA propone, el código decide.** El modelo solo LEE por herramientas y
  puede PROPONER un reclamo; nunca escribe. Lo que se escribe pasa por la ruta
  de reclamo, con confirmación de una persona.
- **Toda cifra sale de una herramienta.** El servidor lo comprueba: un número
  de dos o más cifras en la respuesta que no figure en lo que devolvieron las
  herramientas de ESA consulta (ni en la pregunta) invalida la respuesta.
- **Lo que no pasa la validación recibe un texto fijo del servidor**, no del
  modelo: «No pude responder eso con los datos del tablero. Probá con otra
  pregunta o mirá la ficha de la tarea.»
- Los textos escritos por personas que llegan por herramientas (motivos,
  títulos de tarjetas) son DATOS: el prompt lo dice y no se obedecen.
- Nada del padrón ni de recibos viaja al modelo: las herramientas devuelven
  solo lo que ya devuelve el tablero (tareas, estados, cifras agregadas de los
  controles, insumos, movimientos).

## El asistente (`xsii/asistente.py`, genérico; no importa `db` ni la app)

- Recibe: modelo, texto del sistema, la pregunta ya normalizada, el punto y
  un diccionario de herramientas `{nombre: (esquema, función)}` que le pasa el
  proyecto. Devuelve `{resultado, texto, codigos, propuesta, uso, vueltas}`.
- Llamada con el SDK oficial (`anthropic`), bucle manual de herramientas con
  tope de `MAX_VUELTAS = 6`; `tool_choice` en `auto` (Sonnet 5.5 rechaza la
  herramienta forzada); razonamiento adaptativo por defecto con
  `output_config: {effort: "low"}`; `MAX_TOKENS = 4000`; tiempo máximo 60 s
  por llamada; caché de prompt en el sistema y las herramientas (estables).
  Se devuelve `response.content` entero en cada vuelta. `stop_reason` se mira
  SIEMPRE antes de leer el contenido: `refusal` y `max_tokens` dan el texto
  fijo. Si la versión instalada del SDK lo admite, la llamada lleva el
  respaldo ante rechazos del servidor (`fallbacks: "default"`); si no, se
  informa en el reporte y no se inventa.
- `uso` suma los tokens de TODAS las vueltas (entrada, salida, caché leída y
  escrita): una consulta es una fila de `UsoIA`.
- Modo simulado (sin cliente o con `MOCK_EXTRACTOR=1`): determinista, sin
  llamar a la API; arma la respuesta llamando a las mismas herramientas. Sirve
  para los tests y para ver la pantalla. `disponible` distingue «sin clave»
  (apagado) de «simulado» (prendido, y la pantalla lo avisa).
- Herramientas de Colm3na (`xsii/proyectos/colm3na/herramientas.py`, sobre el
  `Contexto` ya armado: UNA sesión de base por pedido, el tablero se calcula
  una sola vez y las herramientas leen de memoria):
  - `ver_tablero()`: resumen y, por tarea, código, nombre, estado y marcas.
  - `ver_tarea(codigo)`: la ficha (misma forma que la API, sin `acciones`).
  - `que_frena(codigo)`, `que_destraba(codigo)`, `camino_hasta(codigo)`.
  - `ver_registro(codigo?)`: últimos movimientos (hasta 20).
  - `proponer_reclamo(clave, titulo, texto)`: NO escribe. Valida que la clave
    sea un insumo del catálogo que no esté `recibido` y deja la propuesta para
    la pantalla. Como mucho una por consulta.
  Un código o clave inexistente devuelve un error como resultado de la
  herramienta (`is_error`), no una excepción.
- Validación de la respuesta final (pura, con tests): 1 a 900 caracteres,
  sin enlaces ni direcciones de mail, sin marcas de formato (`*`, `#`,
  backticks, tablas), sin caracteres invisibles, los códigos de tarea que
  nombra existen en el catálogo, y la regla de las cifras de arriba.
  `codigos` es la lista de códigos de tarea nombrados (para que la pantalla
  los vuelva enlaces a su ficha).

## Sexto uso de IA

`xsii` en `precios_ia.USOS` (default `claude-sonnet-5-5`), columna
`ConfiguracionPlataforma.modelo_xsii` con su migración, selector en
`/plataforma` → Uso de IA → Modelos, `db.modelo_ia("xsii")` en cada consulta.
Cada consulta queda en `UsoIA` con tipo `herramienta`, a nombre del sindicato
del proyecto, también cuando termina en texto fijo o error (ya se pagó).

## Rutas (misma puerta del equipo, 404 en demo)

### El tablero suma `preguntame`
```json
"preguntame": {"disponible": true, "simulado": false, "motivo": "",
  "largo": {"min": 3, "max": 300},
  "sugeridas": {
    "recomendada": ["¿Por qué este paso y no otro?", "¿Qué pasa si lo salteo?", "¿Cómo estamos en general?"],
    "tarea": ["¿Qué falta para terminarla?", "¿Qué la frena?", "¿Qué se destraba cuando esté hecha?"],
    "mapa": ["¿Qué falta para destrabarla?", "¿Cuál es el camino más corto hasta acá?"]}}
```
`disponible: false` con `motivo` «No hay clave de la API configurada.» apaga
el botón (la pantalla lo deja dibujado y deshabilitado, con ese texto).

### `POST X/p/{pid}/preguntar`
Cuerpo `{"punto": "recomendada" | "tarea" | "mapa", "codigo": "PAD-02", "pregunta": "…"}`.
`codigo` obligatorio en `tarea` y `mapa` (404 si no existe); en `recomendada`
se ignora. `pregunta`: texto de 3 a 300 caracteres medido después de limpiar
(NFKC, sin invisibles ni de control, espacios colapsados); fuera de eso, 400.
Proyecto sin sindicato → 409. Apagado → 409 con el `motivo`.

Respuesta 200:
```json
{"resultado": "respondida" | "fija" | "error",
 "texto": "…",
 "codigos": ["PAD-01", "EST-01"],
 "propuesta": null | {"tipo": "reclamo", "clave": "planilla_padron", "nombre": "Planilla del padrón",
                      "titulo": "…", "texto": "…"},
 "simulado": false}
```
`fija`: el texto es el fijo del servidor. `error`: la API falló (red, saldo,
tiempo); `texto` lo dice en castellano y no es culpa de la pregunta. Nunca 500.
Tope: `XSII_IA_TOPE` consultas por usuario y por hora (default 40) → 429 con
un mensaje que dice cuándo se puede volver a preguntar.

### `GET X/p/{pid}/insumo/{clave}/reclamo`
El borrador que arma el servidor, sin IA:
`{"clave", "nombre", "titulo", "texto", "tarjeta": null | {…forma de tarjeta…},
"modo": "nueva" | "respuesta"}`. `modo: "respuesta"` cuando el insumo ya tiene
una tarjeta de la Mesa enlazada y sigue abierta: el reclamo va como respuesta
en ESA tarjeta. Insumo ya `recibido` → 409.

### `POST X/p/{pid}/insumo/{clave}/reclamo`
Cuerpo `{"titulo": "…", "texto": "…"}` (título 3 a 120, texto 5 a 1.000, ya
saneados; en `modo: "respuesta"` el título se ignora). Crea en la Mesa del
proyecto una tarjeta de tipo Pedido dirigida al sindicato (o responde en la
enlazada), por las MISMAS funciones que usa la Mesa (`db.impl_*`, con su
aviso por mail si corresponde), deja el insumo en `pedido` enlazado a esa
tarjeta y registra el movimiento `insumo_reclamado` (tipo nuevo), todo en una
transacción. Respuesta `{"ok": true, "insumo": {…}, "tarjeta": {…}}`. Dos
reclamos seguidos del mismo insumo en menos de un minuto → 409.

## Pantalla

«Preguntame» deja de estar apagado (salvo `disponible: false`). Al abrirlo, en
el lugar (no es un panel de conversación): las preguntas sugeridas de ese
punto como botones, un campo para escribir la propia (contador de 300), y la
respuesta debajo. Mientras espera: la forma de la respuesta, no un texto
«cargando». La respuesta entra como texto; los códigos de `codigos` se
vuelven enlaces a la ficha. Una pregunta nueva reemplaza la respuesta
anterior. `fija` y `error` se muestran en su tono, con el texto del servidor.
Con `simulado`, una línea chica lo avisa. Una `propuesta` de reclamo se
muestra como tarjeta con título y texto EDITABLES y los botones «Crear en la
Mesa» y «Descartar»: nada se crea sin el clic.

«Reclamar en la Mesa» (panorama y ficha, en un insumo que falta o está
pedido) abre el mismo formulario con el borrador del servidor, sin IA, y
confirma igual. Después de crear: se vuelve a pedir el tablero y se muestra
el enlace a la tarjeta.

## Notas de implementación del bloque 2 (lo que quedó distinto o más preciso)

- **Orden de las puertas de `preguntar`**: cuerpo (400) → punto y pregunta (400) →
  código de tarea (404) → proyecto (404) → sin sindicato (409) → sin clave y sin
  simulado (409) → tope (429) → recién ahí se llama al modelo. Una pregunta inválida
  no gasta el tope. `codigo` ausente, vacío o no texto en `tarea` y `mapa` es 404.
- **`preguntame` del tablero** lo suma la ruta (`main.api_xsii_tablero`); `vista.tablero_json`
  no cambió. `disponible` es falso solo sin clave (ni cliente ni `MOCK_EXTRACTOR=1`).
- **`ver_registro(codigo)`**: `codigo` es obligatorio en el esquema (vacío = todo el
  proyecto), porque el esquema estricto no admite el campo opcional sin gastar uno de los
  cupos de campos anulables. Es la única diferencia con la lista del contrato.
- **Validación de cifras**: toda cifra de dos o más dígitos se controla, sin tope de largo. Un número
  con separador de miles (punto, coma o espacio fino) o con coma decimal se toma ENTERO: `1.234` es
  1234 o 1,234 (las dos lecturas valen), `12,5` es 12.5, y `07` = `7`; «9.234» no pasa porque exista
  234. Se ignoran los dígitos de los códigos de tarea (`PAD-02`) y vale lo que traiga la pregunta.
- **Códigos de tarea**: se buscan normalizando guiones Unicode a `-` y pasando a mayúsculas, así
  `ZZZ‑07` (guion no separable) o `zzz-07` también cuentan como código inexistente.
- **Enlaces**: cualquier `palabra.tld` con forma de dominio (TLD de 2 a 24 letras en minúscula, o los
  TLD de siempre en cualquier caso) cuenta como enlace; una frase con el punto pegado a una palabra
  con mayúscula («hecha.La siguiente») no. Se rechazan también U+2028 y U+2029.
- **Los bloques de texto** de la respuesta del modelo se unen con un espacio, sin duplicarlo.
- **La propuesta de reclamo pasa por las mismas reglas** (forma, cifras, códigos) que la respuesta:
  título (hasta 120) y texto (hasta 1000); si no pasa, `propuesta` es `null` y la respuesta sigue.
- **Tope de consultas**: se MIRA antes de armar el tablero (429 sin calcular nada) y se GASTA recién
  antes de llamar al modelo. La tabla en memoria purga las marcas de más de una hora y, pasada de
  5.000 usuarios, descarta las de actividad más vieja, nunca a quien está al tope.
- **Modo simulado**: reconoce las preguntas sugeridas (en general, salteo, por qué, qué falta, qué
  frena, qué se destraba, camino) y, en una tarea con un insumo que falta o está pedido, ante «qué
  falta» o «qué frena» PROPONE el reclamo con `proponer_reclamo` y el borrador del servidor.
- **Concurrencia en la Mesa**: las funciones `impl_*` que toman un correlativo o una fila con
  `FOR UPDATE` la releen con `populate_existing`; un choque de único en el reclamo da 409, nunca 500.
- **Límites sabidos (no se corrigen)**: las cifras escritas en letras no se controlan; una cifra
  suelta de un dígito no se controla; las direcciones ofuscadas con espacios («ejemplo . com»)
  pasan. La defensa ahí es el texto del sistema y que la persona ve de dónde sale cada dato.
- **Límites propios del bucle**: además de `MAX_VUELTAS = 6`, tope de 120 s en total
  (`TIEMPO_TOTAL_S`) y de 24.000 caracteres por resultado de herramienta. Cualquier parada
  distinta de `end_turn` y `tool_use` (`refusal`, `max_tokens`, `pause_turn`, …) da el texto fijo.
- **Respaldo ante rechazos (`fallbacks`)**: NO se usa. En el SDK instalado (0.120.2) solo
  existe en `client.beta.messages.create` con el encabezado beta `server-side-fallback-*`, y la
  guía lo documenta para el modelo más capaz, no para el de este uso. La llamada va por
  `client.messages.create`; un rechazo es `refusal` y sale el texto fijo.
- **Reclamo, una sola transacción**: `db.xsii_reclamar_insumo` (nueva) llama a
  `impl_crear_tarjeta` / `impl_responder`, que ganaron `commit=True` (con `False` quedan en la
  transacción de quien llama; el resto de la Mesa no cambia). Deja UN movimiento,
  `insumo_reclamado` (no además un `insumo_pedido`), conserva nota y archivo del registro previo.
  El candado es un `pg_advisory_xact_lock` por proyecto e insumo: con pedidos simultáneos pasa
  uno y el resto recibe 409.
- **`GET .../reclamo`**: `tarjeta` es la tarjeta enlazada al insumo aunque esté cerrada (entonces
  `modo` es `nueva`); `modo: "respuesta"` solo si sigue abierta. En ese modo `titulo` es el de la tarjeta.
- **`POST .../reclamo`**: la respuesta suma `modo` (`nueva` o `respuesta`) a `{ok, insumo, tarjeta}`;
  `tarjeta` tiene la forma `{id, codigo, titulo, estado, url}`. Sin sindicato en Colm3na también
  se puede reclamar (un insumo se pide antes del alta). El título solo se valida en `nueva`.
  El aviso por mail va a quien espera la tarjeta (el sindicato) y nunca rompe el reclamo.
- **Registro de uso**: `UsoIA` tipo `herramienta`, a nombre del sindicato del proyecto, con la
  suma de todas las vueltas; también cuando el resultado es `fija`. Si la API falló antes de
  contestar, no hay fila; si falló en una vuelta posterior, se registra lo ya pagado.
- **Uso `xsii` en `/plataforma`**: el selector sale solo del recorrido de `precios_ia.USOS`
  (`templates/plataforma.html` no se tocó). Migración `c7e1a3b5d9f2`.
