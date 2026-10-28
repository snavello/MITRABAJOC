# PLAN_ASISTENTE_TRAMITES_V2.md — el Asistente de trámites, segunda vuelta

Fecha: 2026-10-28 · Pedido de SDN · Reemplaza, en lo que cambia, a
`PLAN_ASISTENTE_TRAMITES.md` (D1–D10, 2026-10-16). Lo que ese plan decidió
y acá no se nombra sigue vigente: la IA propone y el motor decide (D1), el
uso de IA propio (D3), el catálogo desde el código y las brechas a mano
(D4), los casos guardados y las brechas acumuladas (D5), Preact sin build
(D8). Este plan documenta lo acordado **tal cual**; el avance va en
`CLAUDE.md` ("Herramientas"), no acá.

## Lo que pidió SDN (2026-10-27)

«La herramienta tiene que permitir tratar y asistir en varios trámites a la
vez, por eso tendrá que tener un "nuevo trámite" y ver los generados. Vamos
a poner un fondo claro, vamos a eliminar las preguntas obvias que estamos
haciendo con la IA: si hay duda se ponen opciones, si no se pide
confirmación cuando sea necesario, o se permite contestar con texto.
Simplificar, no agregar datos ni repetir. Lenguaje llano. El resultado tiene
que concluir 1) si el trámite ya se puede importar al sistema, 2) si se puede
pero es mejor hacerlo de manera manual guiado, 3) si requiere algún
prerrequisito como crear listas con datos para validar, 4) si es necesario
un desarrollo de complejidad alta, media, baja, 5) si es necesario
completar/adjuntar un formulario que ya existe al trámite, 6) si es
necesario construir primero un formulario para que el afiliado adjunte o
presente antes del trámite. Vamos por una herramienta que pueda llegar a
incorporar directamente un formulario al sistema, teniendo en cuenta los
datos de cada sindicato. Podemos usar La Bancaria como prueba.»

Aclaraciones del mismo día: los puntos 5 y 6 hablan de **formularios de
Colm3na** (uno que ya existe en el sindicato, o uno que hay que crear
antes); lo ajeno a Colm3na (un certificado de discapacidad, una constancia)
es un **archivo que se adjunta**, no un formulario. Importar = **crear el
tipo de trámite como borrador** en el sindicato, para revisarlo y publicarlo
desde el constructor. La estética es **la hoja de trabajo A** del
constructor (mesa clara, hoja blanca, riel de pasos, tipografía y colores
de Colm3na).

## Decisiones (2026-10-28)

- **V1 · Varios trámites a la vez.** La herramienta es un espacio de
  trabajo: a la izquierda, «Nuevo trámite» y la lista de los trámites ya
  tratados (los casos guardados, con su estado y su veredicto); al centro,
  el trámite abierto. Un trámite se guarda y se retoma: guardar un caso ya
  guardado lo **actualiza** (`POST /casos/{id}`), no crea otro. El borrador
  que todavía no se guardó vive en el navegador, como hasta ahora.
- **V2 · Cuatro pasos, no cinco, y sin cuestionario.** El relato → Lo que
  entendí → Los datos → El veredicto. Las seis preguntas una por pantalla
  se van: la IA responde las doce (las seis preguntadas y las seis
  inferidas) desde el relato, y «Lo que entendí» las muestra como frases
  cortas, agrupadas (quién lo pide, quién lo atiende, cómo termina, cuántas
  veces, qué tiene que cumplir), cada una con su selector para corregirla.
  Nada se pregunta dos veces y nada se pregunta si el relato ya lo dice.
- **V3 · Las dudas vienen con opciones.** Lo que el relato no aclara llega
  como una **duda con opciones** cuando la IA puede ofrecerlas (y si la duda
  es sobre una de las doce preguntas, las opciones son las de esa pregunta
  y elegir una la responde), o como una pregunta abierta que se contesta
  con texto. Lo contestado con texto va al prompt y al veredicto como
  «aclaración del analista». Una duda se puede dejar sin contestar: queda
  en «A confirmar con el sindicato».
- **V4 · Un formulario previo de Colm3na es un dato más del relato.** La
  inferida `previo` («¿El afiliado tiene que presentar antes otro
  formulario de Colm3na?») con el nombre del formulario. El motor lo busca
  por nombre entre los formularios del sindicato elegido: si existe, es el
  punto 5 del veredicto (se completa o se adjunta ese formulario, y el
  trámite nace con el requisito de haberlo presentado); si no existe, es el
  punto 6 (hay que construirlo primero). Un documento ajeno a Colm3na sigue
  siendo un campo de tipo archivo.
- **V5 · El veredicto son seis preguntas con respuesta.** `veredicto()` en
  el motor puro, determinista, a partir de la entrada, la configuración, las
  brechas y los datos del sindicato: (1) ¿ya se puede importar?, (2) ¿se
  puede pero conviene hacerlo a mano, guiado?, (3) ¿hace falta un
  prerrequisito (una lista con datos, un área, un módulo)?, (4) ¿hace falta
  desarrollar, y de qué complejidad (alta / media / baja)?, (5) ¿se completa
  o adjunta un formulario que ya existe?, (6) ¿hay que construir antes un
  formulario? Cada una con sí/no y el porqué en una frase, y arriba un
  **titular** con la conclusión principal, en lenguaje llano. Complejidad:
  baja = solo ajustes chicos; media = un ajuste mediano o un desarrollo
  mediano; alta = un desarrollo grande. «Mejor a mano, guiado» cuando hay
  algo que el importador no puede trasladar (un control que no existe, una
  regla que no compila, una función a desarrollar, opciones dependientes) o
  cuando no se eligió sindicato.
- **V6 · Importar crea el tipo de trámite como borrador.** `POST
  /api/entornos/herramientas/asistente/importar` con el sindicato elegido:
  resuelve las áreas **por nombre** (el destino por defecto es el área
  homónima de la seccional con `ve_todas`; el mapa por seccional, el área
  homónima de cada una; lo que no se encuentra queda para completar en el
  constructor), crea primero los encadenados y después el principal, todo
  con `borrador=True` (inactivos, el afiliado no los ve), con los campos
  pasados por `main._campos_tramite_validos(..., borrador=True)`, los
  requisitos por `validaciones_tramite.requisitos_saneados` y el pase por
  nombre. Con `ensayo: true` no escribe nada y devuelve lo mismo que
  haría. Un código que ya existe en el sindicato se renumera (KE27 →
  KE27B). Cada importación queda registrada en el caso (quién, cuándo, qué
  ids) y el caso pasa a `aplicado`. El sindicato no sale de la sesión sino
  del caso: es una herramienta de plataforma, no del panel del sindicato.
  Lo que el contrato marcaba como «no se importa» (claves `x_`) sigue sin
  importarse y el resultado lo lista como pendiente.
- **V7 · Los datos del sindicato, completos.** `_sindicato_para_asistente`
  suma las **listas cargadas** (plantilla, nombre, seccional, filas) y los
  **formularios** existentes (título, código, estado). Con eso el veredicto
  sabe si el grupo familiar está cargado y si un formulario previo existe.
- **V8 · Fondo claro, hoja de trabajo A.** `asistente.css` se reescribe
  para la mesa clara: riel de pasos a la izquierda con la lista de
  trámites, hoja blanca al centro sobre el área cuadriculada, la vista del
  afiliado fija a la derecha, Barlow Condensed para los títulos, tinta y
  agua de la marca de Colm3na, lo propuesto por la IA en fucsia. Mismos
  tokens de movimiento; nada de `innerHTML`.
- **V9 · Lenguaje llano.** Nada de «onboarding», «inferidas», «sanear». La
  pantalla dice «Lo que entendí», «Lo que no quedó claro», «Los datos que
  se piden», «El veredicto», «Importar al sindicato».
- **V10 · La Bancaria como prueba.** El kit escolar sigue siendo el caso
  dorado del motor (el JSON se regenera con las claves nuevas y se anota la
  diferencia), y el test del importador crea un sindicato con la estructura
  de La Bancaria (Acción Social en cada seccional, grupo familiar cargado)
  y verifica el borrador creado, el destino por seccional, el pase y el
  registro.

## Bloques

1. Motor: `previo`, dudas con opciones, aclaraciones, `veredicto`,
   `plan_importacion` (puro: qué se resuelve por nombre y qué falta).
2. IA: esquema de dudas con opciones y `previo`; prompt que pide solo lo
   que falta.
3. Rutas: sindicato completo, actualizar caso, importar (ensayo y real).
4. Pantalla: la hoja de trabajo con la lista de trámites.
5. Docs, versión, bitácora, PR.
