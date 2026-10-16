# PLAN_ASISTENTE_TRAMITES.md — el Asistente de trámites como Herramienta de `/entornos`

Fecha: 2026-10-16 · Acordado con SDN decisión por decisión (D1–D10) ·
Origen: prototipo de Chat `docs/chat/2026-10-16-asistente-tramites.md`
y contrato `docs/chat/2026-10-16-contrato-importacion-tramites.md`.
Este plan documenta lo acordado **tal cual**; el avance va en `CLAUDE.md`
("Herramientas" y "Pendientes" 12), no acá.

## Qué se construye

Una Herramienta de `/entornos` → Herramientas, al lado de la Calculadora
bancaria, para asistir la implementación en un sindicato. El analista (AKG,
DOA) cuenta un trámite en texto libre; la IA lee el relato, propone
respuestas y campos y pregunta lo que el relato no aclara; el servidor arma,
con las piezas REALES de Colm3na, el circuito por actor, quién hace qué, qué
datos circulan, la instrucción para crear el formulario, su vista previa, lo
que hay que **configurar** antes, lo que es un **ajuste** chico y lo que es un
**desarrollo** nuevo, y exporta el JSON `colm3na.tramite` v1. Cada caso se
guarda, y una vista acumula las brechas que los sindicatos piden y Colm3na
todavía no tiene.

El método manual (el constructor de la pestaña Trámites) sigue vigente y no
cambia. El importador del JSON **no** entra en este plan (D7): es el bloque
siguiente, con el contrato ya escrito, después de probar la herramienta con
trámites reales.

## Decisiones (2026-10-16)

- **D1 · La IA propone, el código arma.** La IA hace dos cosas: leer el
  relato (respuestas propuestas a las preguntas, campos propuestos, lo que
  el relato no aclara) y generar preguntas extra. El circuito, la
  instrucción, la vista previa, las brechas y el JSON los arma un motor
  determinista en el servidor (`asistente_tramites.py`, puro) a partir del
  catálogo real. Nada de lo que la herramienta afirma sobre Colm3na sale del
  modelo. Una llamada por caso (dos si el analista pide más preguntas).
- **D2 · Entrada: solo texto libre.** La foto o el PDF del formulario actual
  del sindicato queda para una segunda vuelta.
- **D3 · Uso de IA propio.** Cuarto uso `asistente_tramites` en
  `precios_ia.USOS`, default `claude-sonnet-5`, elegible en `/plataforma` →
  Uso de IA → Modelos y leído con `db.modelo_ia("asistente_tramites")` en
  cada llamada. Cada llamada queda en `UsoIA` con tipo `herramienta` (como
  la lectura de la Calculadora), con el sindicato elegido o sin sindicato.
- **D4 · Catálogo desde el código, brechas a mano.** `asistente_tramites.py`
  arma las capacidades desde las constantes reales (`TIPOS_DATO_TRAMITE`,
  `ANCHOS_CAMPO_TRAMITE`, `validaciones_tramite.TIPOS_VALIDABLES` y
  `OPERADORES`, `db.ESTADOS_TRAMITE`, `permisos.SECCIONES`,
  `modulos.MODULOS`, `MAX_ARCHIVO_TRAMITE`) y mantiene a mano `BRECHAS`: la
  lista cerrada de lo que Colm3na no hace, cada una con nivel (`ajuste` /
  `desarrollo`), motivo, salida provisoria y qué respuesta la dispara. Un
  test falla si aparece un tipo de campo o un operador sin texto en el
  asistente. Cuando una brecha se desarrolla, se saca de la lista y deja de
  señalarse.
- **D5 · Los casos se guardan y las brechas se acumulan.** Cada caso va a
  `CasoHerramienta` con `herramienta="asistente_tramites"` (sin migración:
  la tabla es genérica), mismos estados que la Calculadora (nuevo /
  revisado / aplicado / descartado), quién y cuándo, y CSV. Sin nombres de
  personas: el relato es del trámite, no de la gente. Y una vista
  "Brechas" dentro de la herramienta cruza todos los casos y lista cada
  brecha con cuántos trámites la pidieron y de qué sindicatos: el
  inventario de lo que falta desarrollar.
- **D6 · Sindicato de la lista, con texto libre como alternativa.** Se elige
  entre los sindicatos del entorno, y el motor lee sus áreas, seccionales y
  módulos reales para decir qué falta crear o encender ("configurar
  antes"). Si el sindicato no existe todavía, se escribe el nombre y lo de
  áreas queda como pendiente.
- **D7 · Esta vuelta exporta; el importador es el bloque siguiente.** El
  JSON se genera, se guarda en el caso y se descarga o copia. El importador
  se especifica y construye después de probar con uno o dos trámites reales
  de La Bancaria, siguiendo `2026-10-16-contrato-importacion-tramites.md`.
- **D8 · Preact sin build**, como la Calculadora v2 y el Panel v2: módulos
  en `static/asistente_tramites/`, importmap `asistente/<nombre>` con sello,
  tokens de `movimiento.css`, nada de `innerHTML`.
- **D9 · Este plan, corto, y después bloques.** Con el OK de SDN sobre este
  archivo arranca el bloque 1.
- **D10 · Las seis brechas verificadas contra el código van a BACKLOG** y a
  `BRECHAS` del asistente, para que digan lo mismo. La de extensiones
  jpg/jpeg se arregla aparte, en su propia rama, porque es un bug de uso.

## Dónde vive y quién entra

- Página `GET /entornos/herramientas/asistente-tramites`
  (`templates/asistente_tramites.html`), presentada en la pestaña
  Herramientas de `/entornos`. Misma puerta que la Calculadora:
  `_exigir_landing` (404 en Demo) y `_exigir_pase` (PIN o sesión de
  plataforma); las rutas de la API con `_exigir_herramientas`, que además
  dice quién es para el caso guardado.
- Nada de esto va en las apps de sindicato ni de trabajador.

## Rutas (todas bajo `/api/entornos/herramientas/asistente`)

| Ruta | Qué hace |
|---|---|
| `GET /catalogo` | Sindicatos del entorno (id, nombre, áreas con su seccional, seccionales, módulos encendidos), las preguntas del onboarding con sus opciones, las capacidades y la lista de brechas. Todo lo que la pantalla necesita para andar sin IA. |
| `POST /entender` | `{relato, sindicato_id?, sindicato_nombre?}` → una llamada a la IA → `{respuestas_propuestas, campos_propuestos, sin_aclarar, preguntas_extra}`, validado contra el catálogo antes de devolverse (una respuesta fuera de las opciones se descarta, no explota). Registra `UsoIA`. Si la IA no está configurada o falla, devuelve `{disponible: false}` y la pantalla sigue a mano, como el prototipo fuera de claude.ai. |
| `POST /resolver` | `{relato, sindicato, respuestas, actores, campos}` → el motor puro → `{circuito, quien_hace_que, datos, instruccion, formulario, preparar: {configurar, ajuste, desarrollo}, pendientes, json}`. Sin IA, sin base salvo para leer el sindicato elegido. Es lo que se recalcula en cada cambio de respuesta. |
| `POST /casos` · `GET /casos` · `GET /casos/{id}` · `POST /casos/{id}/estado` · `GET /casos.csv` | Igual que la Calculadora. Al guardar, el resultado y el JSON se RECALCULAN con la entrada en el servidor: no se guarda lo que mande el navegador. |
| `GET /brechas` | Agregado por brecha sobre los casos guardados: cuántos casos, qué sindicatos, el último. Alimenta la vista "Brechas" (D5). |

## El motor (`asistente_tramites.py`, puro)

- `PREGUNTAS`: las catorce del prototipo, en el mismo orden, con sus
  opciones y textos (quién inicia, frecuencia, quién atiende, aprobación,
  datos nuevos después, ventana de fechas, requisitos, cómo termina, quién
  entrega, cupo, listado, tercero, actores, campos).
- `capacidades()`: lo que Colm3na hace, leído del código (D4).
- `BRECHAS`: lo que no hace, con su salida provisoria. Arranca con las del
  prototipo (ajustes: ventana por fechas, único por afiliado, opciones
  dependientes, formato de mail/teléfono/CBU, exportar CSV, registrar
  entrega con el QR, solo encadenado; desarrollos: requisitos para iniciar,
  grupo familiar, lista del sindicato, cupo por seccional, turnos, entrada
  pública, pago) y el hallazgo de la verificación del 2026-10-16: un
  formulario encadenado se puede enviar sin trámite de origen.
- `resolver(entrada, sindicato)` → el resultado completo. Determinista: la
  misma entrada da el mismo resultado, y por eso se puede testear con el
  kit escolar de La Bancaria como caso dorado
  (`2026-10-16-ejemplo-kit-escolar.colm3na.json`): el JSON que genera el
  motor tiene que coincidir con el del prototipo salvo donde el motor
  corrige al prototipo (se anota cada diferencia en el test).
- El JSON sigue el contrato v1: cada campo con la forma exacta que acepta
  `main._campos_tramite_validos` y se sanea con él y con
  `validaciones_tramite.validaciones_saneadas` / `reglas_saneadas` antes de
  salir, así lo que se exporta ya es importable.

## La llamada a la IA (`asistente_tramites_ia.py`, o el mismo módulo con el cliente separado)

- Misma receta que `asistente.py`: cliente inyectable (`usar_cliente`),
  prompt de sistema con caché, **una herramienta con esquema cerrado** para
  la salida (las respuestas son enumeraciones de `PREGUNTAS`, los campos
  son `tipo_dato` del catálogo), `effort: low`, `MAX_TOKENS` holgado.
- El prompt lleva el catálogo (preguntas con opciones, tipos de campo) y la
  regla de la casa: no concluir, solo proponer; anotar lo que el relato no
  dice; no inventar requisitos.
- Lo que vuelve se valida en el servidor contra el catálogo (`_validar`,
  como en `asistente.py`): un valor fuera de lista se descarta y se dice.
- Registro: `db.registrar_uso_ia(sindicato_id o None, "", "herramienta",
  modelo, tokens, duracion_ms)`, medido pegado a `messages.create`.
- Privacidad: la pantalla pide que el relato no nombre personas; se guarda
  tal cual en el caso. Un CUIL que aparezca no se tapa (dato público, H-0013).

## Pantalla (`static/asistente_tramites/`, Preact)

Las mismas cuatro etapas del prototipo: **el pedido** (sindicato + relato +
"Leer con IA"), **lo que entendí** (propuestas marcadas, se confirman con un
clic), **preguntas una por pantalla** (con las propuestas pre-marcadas), y
**resultado** (circuito en diagrama BPMN simplificado y en vista del chat
del afiliado, quién hace qué, datos, instrucción, vista previa con las
clases `.ttp-*` del constructor, preparar antes, pendientes, JSON para
descargar o copiar, guardar caso). Más dos pastillas: **Casos** y
**Brechas**. Estética de Herramientas (la de la Calculadora v2), tokens de
movimiento, lo que espera una acción en fucsia.

## Bloques

| # | Qué | Sale con |
|---|---|---|
| 0 | Este plan + BACKLOG (D10). | PR de documentación. |
| 1 | `asistente_tramites.py`: preguntas, capacidades, brechas, motor, JSON v1 con saneo. `test_asistente_tramites.py` con el kit escolar como caso dorado y el test fail-closed del catálogo. | Sin rutas ni pantalla. |
| 2 | Uso `asistente_tramites` en `precios_ia.USOS` + Modelos de `/plataforma`; la llamada a la IA con cliente simulado en tests; rutas `/catalogo`, `/entender`, `/resolver`. | Plataforma +minor (funcionalidad nueva). |
| 3 | Pantalla Preact, plantilla, importmap, tarjeta en la pestaña Herramientas. `test_asistente_tramites_v2.py` (puertas, importmap, sin `innerHTML`, movimiento por tokens). | Se puede usar en Pruebas. |
| 4 | Casos (guardar, listar, estado, CSV) y la vista Brechas con `/brechas`. | |
| 5 | Robot E2E con la IA simulada; CLAUDE.md (Herramientas + Pendientes 12), HISTORIAL, bitácora; `docs/INDICE.md`. | Cierre del bloque. |

Fuera de este plan, en orden: el importador (contrato v1, con ensayo y
registro), la entrada por foto o PDF del formulario actual, y el uso desde el
panel del sindicato.

## Qué NO cambia

- El constructor manual de Trámites y sus rutas `/admin/tramite-tipo`.
- `TipoTramite` y su esquema: ninguna migración en este plan.
- Las apps de trabajador y empresa.
