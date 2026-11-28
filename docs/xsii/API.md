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

### Qué hacer y qué se espera (guía clara)

- `Tarea` suma `para_que` (una oración, máx. 160 caracteres: qué queda logrado) y
  `pasos` (de 2 a 5 instrucciones en imperativo, máx. 150 cada una; el primero es
  conseguir el insumo si la tarea lo tiene y el último dice cómo se sabe que quedó).
- Cada insumo suma `tipo` (`"archivo"` o `"dato"`) y `formato` (qué se espera
  recibir, máx. 120 caracteres).
- API: cada tarea de `GET .../p/{pid}/tablero` y de la ficha trae `para_que` (str) y
  `pasos` (lista de str); cada insumo de esas tareas trae `tipo` y `formato`. La
  herramienta `ver_tarea` de «Preguntame» devuelve lo mismo, así explica con el mismo texto.

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

---

# Bloque 3: tareas asistidas (Seccionales y Sede Central desde planilla)

Decisiones de SDN: X19 (primero Seccionales, sin áreas internas, más Sede
Central; fija el protocolo) y, el 2026-11-27, **X21: una fila sin coordenadas
se carga igual, marcada «sin ubicar»** (la tarea EST-02 queda pendiente hasta
ubicarla). Definidas por Code y a confirmar: **X22** una seccional que ya
existe (mismo nombre, sin mirar mayúsculas, acentos ni espacios) no se toca
salvo que se tilde «Actualizar las que ya existen»; nunca se borra nada.
**X23** coordenadas que vienen en la planilla quedan con precisión `manual`
(responde quien relevó). **X24** se acepta CSV (archivo o texto pegado); Excel
no, el modelo se baja desde la pantalla.

## El protocolo de los cuatro momentos (genérico)

Una tarea asistida es un módulo registrado en
`xsii/proyectos/colm3na/asistidas/__init__.py` (`ASISTIDAS = {"EST-01": seccionales}`)
con esta interfaz. El bloque 4 (Padrón, Conceptos) suma módulos, no rutas.

- `describir() -> dict`: `{titulo, que_voy_a_hacer: [str, str], insumo: clave, columnas: [{clave, rotulo, obligatoria, ejemplo, ayuda}], modelo_csv: str, opciones: [{clave, rotulo, ayuda, defecto: bool}]}`.
- `ensayar(s, sid, contenido: bytes, opciones: dict) -> dict`: PURO respecto de la base salvo lecturas. Devuelve
  `{total, validas, dudosas, rechazadas, ya_existen, filas: [{linea, estado, motivos: [str], resumen: {…}}], avisos: [str], muestra: [...], huella}`.
  `estado` es `valida` | `dudosa` | `rechazada` | `ya_existe`. `huella` = SHA-256 del contenido + opciones.
- `cargar(s, sid, contenido, opciones, dejar_afuera: set[int]) -> dict`: vuelve a parsear con la MISMA función del ensayo y escribe con las funciones de la app, sin commit propio (lo hace la ruta, todo o nada). Devuelve `{creadas, actualizadas, sin_tocar, afuera, detalle: [...]}`.

El parseo y la clasificación de filas viven en una función pura
(`seccionales.leer(contenido, existentes, opciones)`), probada sin base.

## Reglas de Seccionales (`asistidas/seccionales.py`)

Columnas (cabecera por clave o rótulo, sin mirar mayúsculas ni acentos; separador coma o punto y coma; UTF-8 o Latin-1):
`nombre` (obligatoria), `sede_central` (sí/no), `provincia`, `localidad`, `calle`, `numero`, `piso_depto`, `codigo_postal`, `latitud`, `longitud`, `telefono`, `whatsapp`, `mail`, `horario`.
Solo `nombre` es obligatoria en la cabecera; una columna que falta vale vacío. Una columna desconocida se ignora y se avisa.

- **Rechazada**: sin nombre; nombre de más de 120 caracteres; latitud o longitud ilegibles, o una sola de las dos; coordenadas fuera de la Argentina continental (lat −56 a −21, lon −74 a −53); nombre repetido dentro del archivo (se rechaza la segunda); mail con forma inválida.
- **Dudosa** (entra salvo que se la deje afuera): sin coordenadas (queda `sin_geo`); sin provincia o sin localidad; sin calle o altura; más de una fila marcada `sede_central`.
- **Ya existe**: no se toca, o se actualiza domicilio y contacto (nunca `ve_todas` hacia abajo) con la opción `actualizar_existentes`.
- **Sede Central**: `sede_central` = sí → `ve_todas=True`. Si después de la carga ninguna seccional del sindicato vería todas, `avisos` lo dice; si una fila se llama «Sede Central» o «Casa Central» y no está marcada, se avisa y la opción `sede_por_nombre` (defecto: sí) la marca.
- Decimales con coma o punto. Tope: 500 filas y 1 MB; pasado eso, 400.
- El domicilio se escribe con `geo.campos_para_guardar`; el contacto con los mismos recortes que `POST /admin/seccional`. No se geocodifica nada (ningún servicio externo).
- Textos con caracteres de control o invisibles: se limpian; una celda que empieza con `=`, `+`, `-` o `@` se guarda tal cual (no es una planilla de salida).

## Rutas (puerta del equipo, 404 en demo; `X` = `/api/entornos/xsii`)

### `GET X/p/{pid}/tarea/{codigo}/asistida`
`{disponible: bool, motivo, ...describir()}`. `disponible=false` si la tarea no es asistida con módulo (404 si el código no existe), si el proyecto no tiene sindicato, o si la tarea no aplica. Las `necesita` sin resolver NO bloquean el ensayo pero sí la carga (409).

### `GET X/p/{pid}/tarea/{codigo}/asistida/modelo.csv`
El CSV modelo, como descarga.

### `POST X/p/{pid}/tarea/{codigo}/asistida/ensayo`
`multipart/form-data`: `archivo` (CSV) **o** `texto`; `opciones` (JSON). Autoriza antes de leer el cuerpo y usa el mismo `request`. No escribe NADA (ni movimiento). 200 con el resultado de `ensayar`; 400 archivo vacío, ilegible, muy grande o sin la columna obligatoria (`{detail}` en castellano).

### `POST X/p/{pid}/tarea/{codigo}/asistida/carga`
Lo mismo más `huella` (la del ensayo) y `dejar_afuera` (JSON, líneas dudosas que no entran). Si la huella no coincide con lo que se recibe: 409 «El archivo cambió desde el ensayo». Candado por tarea (`pg_advisory_xact_lock`, el mismo de las decisiones) y todo en UNA transacción:
1. `cargar(...)`;
2. movimiento `asistida_carga` con el texto «Cargó N seccionales desde planilla (M actualizadas, K afuera)» y `detalle` con las cantidades;
3. el insumo del módulo queda `recibido` si no lo estaba;
4. corre el control de la tarea.
Respuesta: `{carga: {...}, control: {...}, tarea: tarea_json, destrabo: [{codigo, nombre}], tablero_resumen}`. `destrabo` = tareas que pasaron de bloqueada a otra cosa por esta carga. La carga NO confirma la tarea: la confirmación la hace una persona (X15).
Si no hay nada para escribir (todo rechazado o afuera): 409.

## Pantalla

En la ficha de una tarea con asistida disponible, dentro de «Qué tenés que hacer», el botón principal pasa a ser **«Cargar desde la planilla»** («Ir a la pantalla» queda como secundario). Abre, en la misma ficha, los cuatro momentos como pasos numerados que se ven de a uno:
1. **Qué voy a hacer**: las dos líneas, las columnas con ejemplo, «Descargar el modelo», y elegir archivo o pegar el texto; las opciones.
2. **Ensayo**: cuatro cifras grandes (válidas, dudosas, rechazadas, ya existen), «Nada se guardó todavía» bien visible, avisos, tabla con filtro por estado; cada dudosa con su casilla «dejar afuera»; cada rechazada con su motivo y su línea.
3. **Carga**: botón «Cargar N seccionales» con confirmación que repite las cifras; mientras corre, sin doble envío.
4. **Control**: resultado del control, cifras, qué se destrabó (con enlace a cada ficha) y qué falta (confirmar; ubicar las que quedaron sin ubicar → EST-02).
«Volver a ensayar» siempre a mano. Todo texto del servidor como nodo de texto.

## Notas de implementación (Bloque 3)

- **Forma del `resumen` de una fila**: solo textos con valor, legibles tal cual:
  `nombre`, `direccion`, `sede_central` (`"Sede Central"`, o ausente), `ubicacion` (`"Con ubicación"` /
  `"Sin ubicar"`, ausente en una rechazada) y `accion` (`crear` | `actualizar` | `sin_tocar`, ausente en una rechazada).
  Una rechazada sin nombre no trae `nombre`. Nunca booleanos.
- **Ensayo**: además del contrato trae `a_escribir` (cuántas filas escribiría la carga) y `opciones` (las normalizadas).
  `muestra` son las primeras 5 filas. Campos del multipart: `archivo` (o `texto`; si el archivo viene vacío vale el texto),
  `opciones` (JSON), y en la carga `huella` y `dejar_afuera` (JSON, lista de enteros).
- **Carga**: `carga` suma `rechazadas` y `avisos`; `detalle` es `[{linea, nombre, accion}]` con `accion`
  `creada` | `actualizada` | `sin_tocar` | `afuera` | `rechazada`. La respuesta trae además `ok: true`. `control` es el
  del `tarea.control` ya recalculado. Una `actualizada` cuenta solo si algo cambió; si no, es `sin_tocar` (por eso cargar
  dos veces lo mismo da 409 «No hay nada para cargar»).
- **Huella**: SHA-256 del archivo más las opciones normalizadas; una huella ausente o distinta es 409 «El archivo cambió desde el ensayo…».
- **`dejar_afuera`**: solo vale para filas dudosas; una línea que no es dudosa se ignora (no es error).
- **`ya_existe` se actualiza con cuidado**: lo vacío de la planilla no pisa lo cargado, `ve_todas` nunca baja, y las
  coordenadas actuales se conservan mientras el domicilio no cambie (si cambió y la planilla no trae coordenadas, queda `sin_geo`).
- **Texto del movimiento**: «Cargó N seccional(es) desde planilla (M actualizada(s), K afuera)»; con 1 va en singular.
  El movimiento es `asistida_carga` (con `codigo` y `clave_insumo`, así sale en el historial de la tarea) y, si el insumo
  no estaba recibido, se suma un `insumo_recibido` en la misma transacción.
- **409 de la carga**: tarea bloqueada («Primero tiene que estar resuelta: …»), no aplica, proyecto sin sindicato,
  huella distinta, o nada para escribir. El ensayo solo da 409 sin sindicato o si no aplica.
- **`disponible=false`** igual trae `describir()` cuando la tarea tiene módulo (la pantalla puede mostrar la guía).
- Sin migración: `XsiiMovimiento.tipo` es texto libre.
- **QA del bloque 3** (`test_xsii_bloque3_qa.py`): (1) el nombre de una fila RECHAZADA ya no «reserva» el nombre: una fila
  corregida más abajo con el mismo nombre entra (antes se rechazaba como «repetido (se carga la primera)» sin que la primera
  se cargara). (2) La carga toma, además del candado por tarea, un candado por sindicato
  (`db.xsii_candado_de_sindicato`, siempre en ese orden): dos proyectos sobre el mismo sindicato cargando a la vez ya no
  duplican las seccionales (la segunda da 409 «No hay nada para cargar»).

---

# Bloque 4a: Padrón desde planilla (PAD-02)

SDN confirmó X22 a X24 el 2026-11-27 («Ok, adelante»). Segunda tarea asistida:
mismo protocolo y mismas cuatro rutas; se suma un módulo
(`asistidas/padron.py`) y tres extensiones GENÉRICAS del protocolo, que
Seccionales no usa pero admite.

Decisiones de Code, a confirmar: **X25** el padrón se carga con las MISMAS
reglas que «Alta masiva» de Trabajadores (una sola implementación, extraída de
la ruta; ver abajo). **X26** una fila cuya seccional no existe entra SIN
seccional y queda dudosa, con el nombre a la vista (hoy la masiva lo hace en
silencio); la opción «Dejar afuera las de seccional desconocida» las excluye.
**X27** hasta 20.000 filas y 5 MB por carga; un padrón más grande se parte en
varias planillas (la pantalla lo dice).

## Extensiones genéricas del protocolo

1. **Mapeo de columnas.** `describir()` puede traer `mapeo: true` y `campos:
   [{clave, rotulo, obligatorio, ayuda}]`. El ensayo devuelve
   `mapeo: {columnas: [{indice, cabecera, campo, muestra: [str, str, str]}], sin_usar: [cabecera], faltan: [clave obligatoria sin columna]}`:
   qué columna de la planilla se tomó para cada campo, detectado por sinónimos
   de la cabecera. La persona lo corrige y vuelve a ensayar mandando
   `opciones.mapeo = {"<indice>": "<clave de campo>" | ""}` (lo que no se
   nombra queda como se detectó; `""` = no usar esa columna). Dos columnas al
   mismo campo: 400. Si `faltan` no está vacío el ensayo responde 200 con
   `total: 0` y `mapeo` para que se pueda corregir (no 400).
2. **Opciones con valor.** Una opción puede traer `tipo: "numero"` (además del
   booleano por defecto), con `minimo`, `maximo` y `defecto: null`. Viajan en
   `opciones` y entran en la huella.
3. **Resultados grandes.** El ensayo devuelve `filas` SOLO de las que no son
   válidas, hasta 300, más `filas_truncadas: bool`, y
   `motivos: [{estado, motivo, cantidad, lineas: [primeras 10]}]` con el
   conteo completo por motivo. `muestra` = primeras 5 válidas. `dejar_afuera`
   por línea sigue valiendo; además cada módulo puede ofrecer opciones
   booleanas que dejan afuera un motivo entero.

## Reglas del Padrón

- **Una sola implementación** (X25): la lógica por fila de
  `POST /admin/trabajador/masivo` se extrae a una función compartida (misma
  conducta, mismos contadores, mismos tests de la masiva en verde) que recibe
  filas ya separadas por campo. La ruta del panel la sigue usando con sus
  líneas separadas por coma; la asistida la llama con las filas mapeadas. La
  asistida corre SIN alcance de seccional (la usa el equipo).
- **Campos**: `cuil` y `nombre` obligatorios; `apellido` (si viene aparte se
  une «Apellido, Nombre» → un solo nombre, apellido primero), `calle`,
  `numero`, `piso_depto`, `localidad`, `provincia`, `codigo_postal`,
  `telefono`, `mail`, `seccional`, `fecha_afiliacion`, `fecha_nacimiento`.
  Una columna «domicilio» en un solo texto va a `calle` tal cual.
- **Rechazada**: sin identificación o sin nombre; identificación que no cumple
  el verificador; sin provincia o sin localidad; fecha ilegible; repetida
  dentro de la planilla (la segunda).
- **Ya existe** (la persona ya está en el padrón de ESTE sindicato): no es
  alta; si la fila trae mail o fecha de afiliación se actualizan solo esos dos
  (regla de la masiva, incluido `padron_responde_por`); si no, no se toca.
- **Dudosa**: seccional escrita que no existe (X26); sin seccional habiendo
  seccionales; persona con cuenta previa por la que este padrón no responde
  (entra el empadronamiento, no se tocan sus datos).
- No se geocodifica. Nada de la planilla se guarda fuera de las tablas del
  padrón: el movimiento lleva solo cantidades.
- Opciones: `sin_seccional_desconocida` (bool, defecto no) y
  `total_declarado` (número, opcional): el momento 4 muestra «Declarado N ·
  en el padrón M · diferencia D» y queda en el `detalle` del movimiento.
- La carga exige que las `necesita` estén resueltas (EST-01 y PAD-01), como
  toda asistida. Deja el insumo `planilla_padron` como recibido si no lo estaba.
- Lo que se devuelve del ensayo trae identificación y nombre de las filas con
  problema (lo ve el equipo, que ya tiene la planilla); NADA de eso entra en
  movimientos, en `UsoIA` ni en lo que leen las herramientas de «Preguntame».

## Pantalla (sigue genérica)

- Momento 2 suma, si el ensayo trae `mapeo`, el bloque «Columnas de la
  planilla»: una fila por columna con su cabecera, tres valores de muestra y
  un selector de campo; «Volver a ensayar con estas columnas». Si `faltan`,
  se abre solo ese bloque con el aviso de qué campo obligatorio no tiene columna.
- Opciones `numero` como campo numérico. `motivos` como lista resumida arriba
  de la tabla (cada motivo filtra la tabla); aviso si `filas_truncadas`.
- Momento 4: si la respuesta trae `carga.comparacion: {declarado, cargado, diferencia}` se muestra destacada.

## Notas de implementación (Bloque 4a)

Lo que quedó implementado, con lo que difiere o precisa el contrato de arriba.

### Padrón (PAD-02) y la función compartida

- **Una sola implementación (X25)**: `padron_carga.procesar(s, sid, filas, alcance, ensayo, ...)` es la lógica por fila
  de `POST /admin/trabajador/masivo` extraída tal cual (la ruta es ahora un adaptador: `filas_de_lista` parte cada línea
  por coma). Misma conducta y mismos tests. Dos únicos cambios en la ruta del panel: el mismo CUIL repetido dos veces en
  una lista con mail o fecha (antes un `KeyError`/500) queda afuera como repetido; y `db.asegurar_cuenta` /
  `guardar_datos_personales` aceptan la cuenta ya traída (`cuenta=`), para no hacer una consulta por persona. Se movieron
  `_en_alcance` → `db.en_alcance` y `_fecha_formulario` → `listas.fecha_formulario` (los nombres de `main` delegan).
  `test_cuit_puertas.py` se ajustó: ahora vigila `padron_carga.procesar` como puerta y acepta que la ruta le pase `_cuil_mal`.
- **`describir()`**: además del contrato trae `columnas` (como Seccionales), `tope_filas` (20000) y `tope_bytes` (5 MB).
  Cada opción `booleana` no lleva `tipo`; la numérica trae `tipo: "numero"`, `minimo`, `maximo`, `defecto: null`.
- **Ensayo**: `{total, validas, dudosas, rechazadas, ya_existen, a_escribir, filas, filas_truncadas, motivos, avisos, muestra,
  mapeo, opciones, huella, padron_actual}`. `filas` solo trae las no válidas, hasta 300, en este orden de prioridad:
  dudosas, rechazadas, ya existen. Cada fila: `{linea, estado, motivos: [str], resumen: {identificacion, nombre, seccional, accion}}`
  (`accion` = `crear` | `actualizar` | `sin_tocar`; solo textos con valor). `motivos` (resumen): `[{estado, motivo, cantidad,
  lineas: [primeras 10]}]` ordenado dudosa, rechazada, ya_existe. `muestra` = primeras 5 válidas. `opciones` trae lo normalizado
  (`sin_seccional_desconocida`, `total_declarado`, `mapeo` = lo que la persona corrigió). Con `total_declarado`, `avisos` suma
  «Con esta carga el padrón quedaría en N afiliados; el sindicato declaró M». `padron_actual` = afiliados ya en el padrón.
- **`mapeo`**: `{columnas: [{indice, cabecera, campo, muestra: [hasta 3 valores]}], sin_usar: [cabecera], faltan: [clave]}`.
  `columnas` lista TODAS las columnas (campo `""` = sin usar). Con `faltan` no vacío el ensayo responde 200 con `total: 0`, todas
  las cifras en cero, `filas: []` y un aviso; la carga responde 400. Detección por sinónimos de la cabecera (sin mirar
  mayúsculas, acentos ni signos). **Una columna de DNI/documento no se mapea a la identificación** (aviso aparte); una cabecera
  con «CUIT» de la empresa tampoco. **Si la persona manda `opciones.mapeo` y asigna un campo a una columna, ese campo se le quita
  a cualquier columna que lo hubiera tomado por detección** (no es 400); **dos columnas que ella misma asigna al mismo campo sí
  dan 400**. Un índice de columna que no existe, 400.
- **Estados**: válida; **dudosa** = seccional escrita que no existe (el motivo nombra la seccional, así `motivos` agrupa por
  nombre), sin seccional habiendo seccionales, o persona con cuenta previa por otro sindicato (entra el empadronamiento, no se
  tocan sus datos); **rechazada** = sin identificación, identificación sin 11 números (un DNI) o con verificador que no cierra,
  sin nombre, sin provincia o localidad, fecha ilegible, repetida en la planilla (la primera que se puede cargar entra; una
  rechazada no «reserva» la identificación); **ya_existe** = la persona ya está en el padrón de ESTE sindicato: se actualiza solo
  mail del padrón y/o fecha de afiliación si la fila los trae y son distintos de lo guardado (`accion: actualizar`), si no
  `sin_tocar`.
- **`sin_seccional_desconocida`** deja esas filas **rechazadas** («La seccional «X» no existe en este sindicato.»), no dudosas.
- **Carga**: `carga` = `{creadas, actualizadas, sin_tocar, afuera, rechazadas, detalle, detalle_truncado, avisos, comparacion?}`.
  `detalle` = `[{linea, identificacion, accion}]` solo de actualizadas, afuera y rechazadas, hasta 300. `comparacion` (solo con
  `total_declarado`) = `{declarado, cargado, diferencia}`, con `cargado` = afiliados del sindicato después de la carga y
  `diferencia = cargado − declarado` (negativa = faltan). `dejar_afuera` solo vale para dudosas. Segunda carga de la misma planilla:
  409 «No hay nada para cargar…». Movimiento: «Cargó N afiliados al padrón desde planilla (M actualizados, K afuera)» y en
  `cantidades` solo números (más `declarado`/`cargado`/`diferencia`). Nada de la planilla se guarda fuera de las tablas del padrón.
- **Planilla pegada como texto**: Starlette limita a 1 MB un campo de texto de un multipart; una planilla más grande se manda como
  `archivo` (la pantalla puede armar un `Blob` con el texto).
- **Rendimiento medido** (20.000 filas, 2,1 MB, Postgres local): ensayo 1,6 s, carga 13,8 s (con el conteo de la comparación), re-ensayo
  de lo ya cargado 2,3 s. Cada sentencia queda lejos del `statement_timeout`.

### Extensiones genéricas hechas

- `base.py` ahora tiene la lectura del CSV con topes POR MÓDULO (`leer_csv(contenido, tope_filas, tope_bytes)`), `limpiar`, `plural` y el
  mapeo de columnas COMPARTIDO (`detectar`, `normalizar_mapeo`, `aplicar_mapeo`, `mapeo_json`). Cada módulo declara `TOPE_FILAS` y `TOPE_BYTES`.
- Cada módulo expone `movimiento(carga) -> (texto, cantidades)`: `vista.asistida_cargar` ya no tiene el texto de Seccionales escrito.
- `carga.comparacion` viaja dentro de `carga` (la respuesta de la carga no cambia de forma).
- Las opciones numéricas y `mapeo` entran en la huella (viajan en `opciones` normalizadas).

### Seccionales (EST-01) con el mismo mapeo

- `describir()` suma `mapeo: true` y `campos`; el ensayo trae `mapeo` y acepta `opciones.mapeo`. **Cambia el contrato de Seccionales**:
  una columna desconocida ya no genera un aviso (va a `mapeo.sin_usar`), y una planilla sin columna de nombre responde 200 con
  `mapeo.faltan = ["nombre"]` (la carga da 400), en vez de 400 en el ensayo. Las opciones normalizadas suman `mapeo`.
- Sinónimos: nombre/seccional/delegación/denominación; sede_central = ve_todas/sede central/casa central/central; calle/domicilio/dirección;
  numero/altura/nro/número; piso_depto/piso/depto/oficina; localidad/ciudad; provincia; codigo_postal/cp; latitud/lat; longitud/lon/lng/long;
  precision_geo/precisión; telefono/tel; whatsapp/wsp/celular; mail/email/correo; horario/horario_atencion/atención; responsable/x_responsable/
  secretario/titular/a cargo/delegado.
- **X23 revisada**: nueva columna `precision_geo` (opcional). Con coordenadas válidas se respeta `exacta`, `aproximada` o `manual`; vacío
  u otro valor = `manual`; sin coordenadas = `sin_geo` siempre. Una fila `aproximada` entra y queda **dudosa** («Ubicación aproximada:
  confirmala en el mapa.»). Antes toda coordenada de planilla quedaba `manual`.
- `S/N` o altura vacía = falta la altura (dudosa, no rechazada); «764/68» y similares se guardan tal cual.
- Campo nuevo `responsable` (`Seccional.responsable`, 120 caracteres, migración `d3f5a7b9c1e4`): se carga y, al actualizar una existente,
  lo vacío no pisa lo cargado. En el panel (`POST /admin/seccional`, `responsable`) y en la app del afiliado («Responsable: …», como texto).
- Fixtures: `docs/xsii/ejemplos/padron-ejemplo.csv` (30 filas) y `seccionales-como-viene.csv` (la cabecera real, 10 filas inventadas).

### Correcciones del QA de servidor del bloque 4a (`test_xsii_bloque4_qa.py`)

- **Una carga del padrón a la vez en toda la plataforma**: `padron_carga.procesar` (no el ensayo) toma `pg_advisory_xact_lock('padron-carga')`
  ANTES de leer, y lo suelta al confirmar. Dos cargas que creaban la misma cuenta de persona (el CUIL es único entre sindicatos) o el mismo
  empadronamiento chocaban en el commit con un `IntegrityError` (500); la asistida tenía candados por tarea y por sindicato, pero no frenaba
  a «Alta masiva» del panel. El orden de candados es siempre tarea, sindicato, padrón: sin ciclos. Una espera larga la corta el
  `statement_timeout` (503 `E-SERVIDOR-02`).
- **Un byte nulo (`\x00`) en la lista de «Alta masiva»** se descarta en `filas_de_lista` (Postgres no lo guarda en un texto y la carga caía con un 500).
- **El «Responsable» de la seccional por el panel** se limpia de caracteres de control e invisibles (como en la planilla) antes de recortarlo
  a 120; con un nulo, `POST /admin/seccional` daba 500.
- **Ficha de la seccional** (`/admin`, `verSeccional`): teléfono, WhatsApp, mail y horario se armaban con `innerHTML` sin escapar, y desde XSII
  entran por planilla (el mail admite `<img/src=x/onerror=...>@x.y`). Ahora se escapan igual que el responsable.


---

# Bloque 4b: Conceptos desde los recibos de muestra (REC-04)

Tercera tarea asistida. Decisión de SDN (2026-11-28, **X28**): la IA lee los
recibos de muestra y **propone**; la persona revisa, corrige o descarta cada
concepto y recién ahí se cargan, **ya revisados** (`pendiente_revision =
False`). Nada entra al catálogo sin que alguien lo haya mirado.

## Una sola implementación de las reglas (como el padrón)

`conceptos_carga.py` (nuevo, en la raíz; no importa `main`):

- `proponer(conceptos_actuales, recibos) -> list`: recibe los recibos YA
  leídos (el dict del extractor) y devuelve las propuestas, deduplicadas por
  `(codigo, cuit_empleador)` con `veces`, `similar` y `generico_sugerido`.
  Es lo que hoy hace el cuerpo de `POST /admin/aprender` después de leer.
- `aplicar(s, sid, aprobados) -> {altas, cuit_invalidos, repetidos}`: lo que
  hoy hace `POST /admin/aprender/aplicar`. No hace commit.

`/admin/aprender` y `/admin/aprender/aplicar` pasan a ser adaptadores y
**tienen que dar exactamente lo mismo que antes** (el QA lo compara contra la
lógica anterior congelada en un test). La lectura de UN recibo de muestra
(tapado, `extraer`, rearmado, registro en `UsoIA` como `aprendizaje`, también
cuando falla) queda en un helper de `main.py` que usan las dos puertas.

## El protocolo, con otra entrada

`describir()` suma `entrada`: `"planilla"` (por defecto, las dos de antes) o
`"recibos"`. Con `"recibos"`:

- `archivos`: `{por_envio: 1, tope_mb: 8, formatos: ["pdf","jpg","png","webp"], sugeridos: "30 a 60, de varios empleadores"}`.
- `ia`: `{disponible: bool, simulada: bool, motivo: str}`. Sin
  `ANTHROPIC_API_KEY` no está disponible y la pantalla lo dice; con
  `MOCK_EXTRACTOR=1`, simulada y avisado.
- `rubros`: `[{clave, rotulo}]` = `haber` (Haber remunerativo),
  `no_remunerativo` (Haber no remunerativo), `descuento` (Descuento).
- `categorias_sindicales`: `[{clave: "", rotulo: "Ninguna"}, {clave: "afiliacion", …}, {clave: "convenio", …}]` (solo valen para `descuento`).
- `genericos`: `[{codigo, nombre}]`, los conceptos genéricos del sindicato
  (para «Corresponde a»).
- No hay `modelo_csv`, `mapeo` ni `columnas`.

### `POST X/p/{pid}/tarea/{codigo}/asistida/ensayo` (entrada `recibos`)

Multipart con **un** `archivo` por pedido (la pantalla manda de a uno, dos a
la vez, y muestra el avance; así un recibo que falla no pierde a los demás y
ningún pedido dura más que una lectura). No guarda nada. La llamada a la IA
va FUERA de la sesión de base. Pasa por `_exigir_imagen_manejable` y
`_preparar_para_ia` como toda lectura. Respuesta 200:

```
{"recibo": {"nombre": "<nombre del archivo>", "leido": true|false,
            "motivo": "" | "<por qué no se pudo leer, en castellano>",
            "empleador_cuit": "30…"|"", "empleador_nombre": "", "lineas": 17,
            "simulado": bool},
 "propuestas": [ <propuesta> ]}
```

`<propuesta>`:

```
{"clave": "<codigo>|<cuit_empleador o ''>", "codigo": "", "descripcion": "",
 "cuit_empleador": ""|"30…", "empleador_nombre": "",
 "rubro": "haber"|"no_remunerativo"|"descuento",   # sugerido
 "categoria_sindical": ""|"afiliacion"|"convenio", # sugerida
 "veces": 1,
 "similar": null | {"codigo","nombre","ratio"},
 "generico_sugerido": null | {"codigo","nombre"},
 "estado": "valida"|"dudosa"|"rechazada", "avisos": [""], "errores": [""]}
```

- El rubro sugerido sale de la **sección** donde está impresa la línea
  (`validador.repartir_por_zona` manda sobre el signo) y, si no hay sección,
  del `tipo` leído.
- `dudosa`: se parece a un concepto que ya está (`similar`), o la sección y el
  tipo leídos no coinciden, o la descripción vino vacía.
- `rechazada`: el CUIT del empleador no cumple el módulo 11 (no se puede
  cargar; se carga a mano con el CUIT correcto) o el código vino vacío.
- Un recibo ilegible devuelve 200 con `leido: false` y `propuestas: []` (no
  es un error del pedido). El gasto de IA de un intento fallido se registra.
- Nada del recibo se guarda ni se devuelve: ni nombre, ni CUIL, ni importes.
- Tope `XSII_RECIBOS_TOPE` (120 recibos por usuario y hora): 429 con mensaje.
- Los conceptos que ya están en el catálogo no se proponen (así se puede
  repetir con más recibos otro día: el estado es el catálogo).

La pantalla junta las propuestas de todos los recibos por `clave`, sumando
`veces` (si difieren en rubro, queda el de más veces y la propuesta pasa a
`dudosa` con el aviso «Los recibos no coinciden en el rubro»).

### `POST X/p/{pid}/tarea/{codigo}/asistida/carga` (entrada `recibos`)

JSON (no multipart, no hay huella: lo que se carga es lo que la persona
revisó):

```
{"conceptos": [{"codigo","descripcion","cuit_empleador","rubro",
                "categoria_sindical","codigo_generico"}],
 "recibos_leidos": 37}
```

Validación estricta, todo o nada (400 con `detalle` por ítem si algo no
pasa): de 1 a 500 conceptos; `codigo` 1 a 40 y `descripcion` 1 a 120
caracteres, sin bytes nulos ni caracteres de control; `rubro` del catálogo;
`categoria_sindical` solo con `descuento`; `cuit_empleador` vacío o válido por
módulo 11; `codigo_generico` vacío o un genérico que existe en ESE sindicato y
solo si hay `cuit_empleador`; sin `clave` repetida. `recibos_leidos` es un
entero de 0 a 5.000 y solo va al movimiento.

Mismo cierre que las otras: una transacción con el candado por tarea y por
sindicato, `conceptos_carga.aplicar`, movimiento `asistida_carga` (solo
números: conceptos cargados, ya existentes, recibos leídos), corre el control
y devuelve `destrabo`. **No confirma la tarea** (X15). Un concepto que ya
existe con esa clave no se toca y se cuenta en `repetidos`. No hay insumo que
marcar (`recibos_muestra` es de REC-01).

Respuesta: `{"ok": true, "carga": {"cargados", "repetidos", "recibos_leidos"}, "control": …, "destrabo": …}` con la forma de las otras asistidas.

## Pantalla (momentos)

1. **Qué voy a hacer**: el texto de `describir()`, el estado de la IA, y la
   zona para elegir varios recibos (o arrastrarlos).
2. **Lectura** (el ensayo): lista de recibos con su estado (en cola, leyendo,
   leído con N conceptos nuevos, no se pudo leer + motivo), barra de avance
   «12 de 37», «Detener» y «Sumar más recibos». Debajo, las **propuestas**
   agrupadas por empleador: cada una con código, descripción editable, veces,
   selector de rubro, categoría sindical (solo en descuentos), «Corresponde a»
   (genérico; solo si tiene empleador), sus avisos y «Descartar» / «Volver a
   incluir». Las dudosas arriba, con filtro. Las rechazadas se ven y no se
   pueden incluir.
3. **Carga**: resumen «Voy a cargar N conceptos (M descartados)» y confirmar.
4. **Control**: resultado y qué destrabó, como las otras.

Si la persona sale de la ficha con propuestas sin cargar, la pantalla avisa
(se perderían: volver a leer cuesta). Todo texto del servidor va como texto,
nunca como HTML.

## Catálogo

Los `pasos` de REC-04 pasan a apuntar a «Leer los recibos de muestra» de XSII
(la pestaña Aprendizaje del panel sigue existiendo y da lo mismo).
