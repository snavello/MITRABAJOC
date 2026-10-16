# PLAN_LISTAS_VALIDACIONES.md — Listas del sindicato y validaciones por función en Trámites

Fecha: 2026-10-16 · Acordado con SDN decisión por decisión (D1–D7) ·
Cierra las fases 2 (`sistema`) y 3 (`lista`) de "Validaciones de Trámites"
del BACKLOG y la brecha 6 ("pedidos repetidos") de la lista del
2026-10-16. Este plan documenta lo acordado **tal cual**; el avance va en
`CLAUDE.md`.

## Qué se construye

Un campo de un formulario de Trámites se puede validar con una **función**:
recibe el CUIL de la sesión (y, si hace falta, otro campo del formulario,
como el DNI de un familiar), busca en una **lista que subió el admin del
sindicato** o en un **dato del sistema**, y devuelve un resultado puro
(existe / no existe, el valor de una columna) o el resultado de una
**fórmula** (sumar, restar, dividir campos y columnas). Con el mismo
contrato se resuelven tres cosas: un **requisito para iniciar** (se evalúa
antes de mostrar el formulario), una **validación de campo** (bloquea o
avisa, como las de hoy) y un **campo calculado** que el afiliado ve ya
completo. Ejemplos que lo motivan: el DNI del chico contra el grupo
familiar del afiliado (kit escolar), y la antigüedad como afiliado para
habilitar un trámite.

## Decisiones (2026-10-16)

- **D1 · Híbrida: tabla genérica por debajo, plantillas tipadas para
  empezar.** Una lista es una tabla por sindicato con columnas declaradas
  (`ListaSindicato` + `FilaLista`, datos en JSONB, dos claves indexadas).
  Lo que ve el admin son **plantillas** con CSV modelo y cabecera fija:
  `grupo_familiar` (cuil, dni, apellido_nombre, vinculo, fecha_nacimiento),
  `datos_afiliado` (cuil, fecha_afiliacion, fecha_nacimiento, categoria) y
  `simple` (cuil). Son cortas, el admin sabe qué actualizar, y una plantilla
  nueva es una entrada en `listas.PLANTILLAS`, no un modelo nuevo. La tabla
  de columnas libres (CSV con cualquier cabecera) queda para después, sobre
  el mismo esquema.
- **D2 · Validar y también calcular.** Tres usos del contrato: (a)
  requisito para iniciar, (b) validación de campo con bloquea/avisa, (c)
  campo calculado de solo lectura (tipo de campo nuevo `calculado`).
- **D3 · Al enviar siempre; en vivo solo si el admin lo tilda.** El
  servidor evalúa todo en `evaluar_envio`. Por validación, el admin puede
  tildar "avisar al salir del campo": una ruta devuelve solo pasa / no pasa
  y el mensaje del admin, nunca la fila, con **tope de 10 intentos por
  sesión y por formulario** (anti-enumeración, regla del BACKLOG). Los
  requisitos se evalúan al abrir el formulario: si no se cumplen, se
  muestra el mensaje en vez de los campos. El campo calculado se completa
  al abrir (si solo usa sistema o lista por CUIL) o al salir de los campos
  que usa.
- **D4 · Listas primero; el perfil suma dos fechas.** La fuente `sistema`
  expone lo que ya existe (está en el padrón, seccional, nivel de
  fiabilidad, cantidad de recibos verificados, estado del semáforo) más dos
  columnas nuevas: `Trabajador.fecha_afiliacion` (del empadronamiento, la
  carga solo el sindicato: alta, edición y carga masiva) y
  `CuentaTrabajador.fecha_nacimiento` (de la persona; la ve y la edita el
  afiliado en su perfil, el sindicato en Trabajadores). Hechos, no
  derivados: se guarda la fecha, nunca la antigüedad ni la edad.
- **D5 · Listas es una pestaña propia de `/admin`, al nivel de Trámites.**
  No cuelga de Trámites: mañana Denuncias o Reclamos las van a usar. Sección
  `listas` en `permisos.SECCIONES` (grupo "Padrón", sin módulo, como
  Trabajadores y Seccionales), la ven los dos roles de administrador y se
  puede dar a un área. Carga por CSV con **ensayo**: la app dice cuántas
  filas entran y cuáles tienen error (CUIL sin módulo 11, fecha ilegible,
  columna que falta) y recién con Confirmar **reemplaza la lista entera**,
  guardando quién, cuándo y el nombre del archivo. Una lista puede
  declararse por seccional: el Admin de Seccional sube y ve solo la suya.
- **D6 · La fórmula se escribe como las Reglas de control, con nombres
  cerrados.** Mismo motor que `validador` (parseo con `ast`, sin `eval`):
  `+ - * /`, comparaciones, `y` / `o`, y funciones chicas (`meses_entre`,
  `anios_entre`, `hoy`, `min`, `max`, `redondear`). Los nombres los ofrece
  el constructor: `campo.<etiqueta_normalizada>`, `lista.<columna>` (de la
  fila encontrada), `sistema.<dato>`. El banco de pruebas del constructor la
  evalúa antes de guardar: una fórmula rota no se guarda.
- **D7 · Trabajador primero; empresa en una segunda vuelta.** Los
  formularios de empresa (`TipoTramiteEmpleador`, espejo aislado por
  decisión) reciben lo mismo en un bloque aparte, cuando el primero esté
  probado con el kit escolar.

## El contrato (una validación de fuente `funcion`)

```
{ "fuente": "funcion",
  "origen": "lista" | "sistema",
  "lista": "grupo_familiar" | "datos_afiliado" | "simple" | null,
  "clave2": <índice del campo del formulario que aporta la segunda clave> | null,
  "trae": "existe" | "<columna de la lista o dato del sistema>",
  "formula": "<expresión sobre campo.*, lista.*, sistema.*>" | null,
  "operador": "<=|>=|<|>|==|!=" | null, "valor": "<constante o 'hoy±N'>" | null,
  "mensaje": "<lo único que ve el afiliado>", "bloquea": true | false,
  "en_vivo": true | false }
```

- El CUIL de la sesión es SIEMPRE la primera clave; nunca viene del
  formulario (misma regla que `/api/reportar`).
- `trae: "existe"` sin fórmula es la validación de lista pura ("el DNI está
  en el grupo familiar"). `trae: "<columna>"` + `operador`/`valor` es la
  comparación simple ("fecha_afiliacion <= hoy-365"). `formula` con
  `operador`/`valor` es la general; en un campo `calculado`, `formula` sin
  operador es lo que se muestra.
- Fila no encontrada: la validación **no pasa** (con su mensaje) salvo que
  `trae` sea `existe` negado por el operador; un campo calculado queda
  vacío con el mensaje.
- Lo que se evalúa queda en `Tramite.advertencias` solo si `avisa`; el
  valor de la fila no se guarda nunca (hechos, no derivados).
- Los requisitos para iniciar son una lista de estas mismas validaciones en
  `TipoTramite.requisitos` (JSONB), todas `bloquea`, sin `clave2`.

## Modelo

- `ListaSindicato`: id, sindicato_id, plantilla, nombre, seccional_id
  (null = todo el sindicato), columnas (JSONB: [{clave, tipo, rotulo}]),
  filas, archivo, cargada_en, cargada_por.
- `FilaLista`: id, lista_id, clave1 (CUIL normalizado), clave2 (texto,
  normalizado), datos (JSONB). Índice (lista_id, clave1, clave2). Unicidad
  por (lista_id, clave1, clave2) salvo en `simple`, donde clave2 es "".
- `Trabajador.fecha_afiliacion` y `CuentaTrabajador.fecha_nacimiento`
  (texto ISO, como todas las fechas del proyecto).
- `TipoTramite.requisitos` (JSONB) y `CampoTramite.tipo_dato = "calculado"`
  con su `formula` en `validaciones[0]`.
- Permiso `listas`; sin módulo nuevo.

## Rutas

| Ruta | Qué hace |
|---|---|
| `GET /admin/listas` · `POST /admin/lista/ensayar` · `POST /admin/lista/confirmar` · `POST /admin/lista/borrar` · `GET /admin/lista/{id}/modelo.csv` | La pestaña Listas: plantillas, ensayo, reemplazo entero, descarga del CSV modelo y de lo cargado. |
| `POST /admin/tramite-tipo/probar` | El banco de pruebas de hoy, que pasa a evaluar también las de fuente `funcion` con el CUIL que el admin elija del padrón. |
| `POST /api/tramite/validar-campo` | En vivo (D3): `{tipo_tramite_id, indice_campo, valor, valores}` → `{pasa, mensaje}`; 10 intentos por sesión y formulario; 429 después. |
| `GET /api/tramite/requisitos/{tipo_tramite_id}` | Al abrir: `{cumple, mensajes, calculados: {indice: valor}}`. |

## Bloques

| # | Qué | Sale con |
|---|---|---|
| 0 | Este plan. | PR de documentación. |
| 1 | `listas.py` (plantillas, parseo y validación del CSV, normalización de claves; puro), modelo + migración, carga con ensayo y reemplazo, pestaña Listas, permiso `listas`, `test_listas.py`. | Admin +minor. |
| 2 | Las dos fechas del padrón en alta, edición, carga masiva, perfil del afiliado y Trabajadores; migración. | Admin +patch, Trabajador +patch. |
| 3 | Motor: fuente `funcion` en `validaciones_tramite` (nombres cerrados, `validador` para la fórmula), requisitos, campo `calculado`, `evaluar_envio`, constructor (UI + banco de pruebas) y el formulario del afiliado. `test_validaciones_funcion.py`. | Admin +minor, Trabajador +minor. |
| 4 | En vivo con tope de intentos, y requisitos al abrir. | Trabajador +patch. |
| 5 | El Asistente de trámites deja de marcar como brecha `duplicados`, `lista` y `requisitos`; BACKLOG, CLAUDE.md, HISTORIAL, bitácora. | Cierre. |

Fuera de este plan: la tabla de columnas libres, la carga incremental fila
por fila, la fuente `externa` (fase 4) y el espejo de empresa.

## Qué NO cambia

- Las validaciones `fija` y las reglas de consistencia de hoy, y la regla
  de que una validación mal formada no se guarda.
- Un CUIL se busca tal cual (sin exigir módulo 11) donde se REFERENCIA; en
  la carga de una lista SÍ se exige, porque ahí nace.
