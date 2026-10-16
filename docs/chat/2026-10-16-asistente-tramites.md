# Asistente de trámites: del pedido del sindicato al formulario
Fecha: 2026-10-16 · Herramienta: Chat · Origen: artifact «Piloto de trámites Colm3na» https://claude.ai/artifact/BgZ441HNMwtQw2jFPsALsd (versión 8)
Estado: borrador
Quién: SDN

## Qué es

Un onboarding para el implementador (hoy) y, más adelante, para el personal del sindicato. A partir de un pedido contado en texto libre, devuelve:

- el circuito del trámite como diagrama de flujo por actor;
- quién hace qué y qué datos circulan;
- la instrucción para crear el formulario en Colm3na, con la vista previa del afiliado;
- lo que hay que preparar antes (configuración, ajustes y desarrollo);
- las preguntas pendientes para el sindicato;
- un JSON importable (`colm3na.tramite` v1).

Hoy es un prototipo HTML (`2026-10-16-asistente-tramites-prototipo.html`) que funciona sin servidor. Dentro de claude.ai usa la IA del visitante para leer el relato y sumar preguntas. Fuera de claude.ai, esas dos funciones no aparecen y el resto anda igual. El ejemplo cargado es el kit escolar de La Bancaria (T41 de `docs/bancaria/tramites-bancaria.json`). `2026-10-16-ejemplo-kit-escolar.colm3na.json` es el JSON que genera para ese caso.

## Flujo del onboarding

1. **El pedido.** El analista o el sindicato escribe el relato. Lo escrito manda sobre cualquier otra fuente; una ficha o la foto de un formulario quedan como complemento futuro.
2. **Lo que entendí.** Opcionalmente, la IA lee el relato y propone respuestas y campos. Todavía no saca conclusiones y anota lo que el relato no aclara.
3. **Preguntas, una por pantalla.** Lo propuesto por la IA viene marcado y se confirma con un clic. Las preguntas son:
   - quién inicia el pedido;
   - cuántas veces se puede pedir;
   - quién lo recibe y lo revisa;
   - si hace falta aprobación, y quién la da;
   - si después de aprobar hay que pedirle datos nuevos;
   - si tiene fechas de apertura y cierre;
   - qué requisitos tiene que cumplir quien lo pide (varias respuestas);
   - cómo termina;
   - quién entrega (si termina en una entrega);
   - si la cantidad es limitada;
   - si hace falta un listado de los pedidos;
   - si interviene alguien fuera del sindicato;
   - si están todos los que intervienen (se pueden agregar actores);
   - qué datos se piden (los campos, con tipo y control).
4. **Resultado.**
   - El circuito, en dos vistas: el diagrama de flujo y lo que ve el afiliado en su chat.
   - Quién hace qué.
   - Qué datos circulan.
   - La instrucción para crear el formulario.
   - Así queda el formulario: la misma «Vista del afiliado» del constructor.
   - Antes de crearlo: Configurar, Ajuste o Desarrollo, cada uno con su salida provisoria.
   - Las preguntas pendientes.
   - El JSON para importar.

## Decisiones tomadas en el chat (SDN, 2026-10-16)

- **Asistente y no formulario de configuración.** La primera versión mostraba todo junto y se descartó por demasiado compleja para una funcionalidad que ya existe. Ahora se pregunta primero y se concluye después.
- **Usuario por etapas.** Primero el implementador (DOA, AKG); después, el panel del sindicato.
- **Arranque desde texto libre.** La ficha y la foto de un formulario quedan para más adelante, como complemento.
- **Correcciones por el chat.** Pedir información o una corrección va por el chat del trámite, con adjuntos (el afiliado ya puede responder con un archivo de hasta 10 MB). No se manda un formulario para eso.
- **Formularios encadenados solo para datos nuevos.** Son para pedir información que no estaba, después de la aprobación. Ejemplo: aprobada la plaza de hotel, el «Registro de pasajeros» que se envía al hotel.
- **Notación estándar en el diagrama.** Se usa un BPMN simplificado: carriles por actor, inicio, acción, decisión con Sí y No, fin, y mensaje punteado para lo que pasa fuera de Colm3na. La primera versión, con un dibujo propio, se descartó porque no se entendía sin conocer Colm3na.
- **Actores, acciones y datos explícitos.** Es un requisito general, no solo del ejemplo. Por eso existe la pregunta «¿Quién entrega?»: la misma área, un delegado que usa el panel (va con pase), un delegado sin panel (el área registra la entrega después) o el proveedor.
- **Vista previa fiel al producto.** Después de la instrucción se muestra el formulario tal como lo ve el sindicato al terminar de crearlo: la «Vista del afiliado» del constructor (`admin.html`, `.ttp-*`).
- **Importación como objetivo final.** Cuando el trámite esté afinado y acordado con el sindicato, se importa en Colm3na y no se crea a mano. El contrato está en `2026-10-16-contrato-importacion-tramites.md`. El importador no se construye todavía.

## Hallazgos del código usados por el asistente (verificados el 2026-10-16)

- **Tipos de campo:** texto, número, fecha, archivo, selección, opción única, múltiple, booleano y separador. Anchos completo, mitad y tercio.
- **Validaciones:** las fijas solo sobre número y fecha (con «hoy±N»). Las reglas de consistencia solo comparan número con número o fecha con fecha.
- **Ruteo:** área por defecto obligatoria y mapa por seccional. El pase entre áreas es una lista cerrada; el área que deriva conserva lectura y el afiliado ve el área, nunca la persona.
- **Archivos:** la extensión se compara tal cual, así que «pdf,jpg» rechaza «.jpeg». El asistente propone siempre «pdf,jpg,jpeg,png».
- **Brecha nueva:** un formulario encadenado tiene que estar activo para adjuntarse en el chat, y entonces también aparece en «Iniciar trámite». Propuesta: una marca «solo encadenado».

## Brechas que el asistente puede señalar

Cada una lleva su salida provisoria en el prototipo.

**Ajustes (cambios chicos):**
- Abrir y cerrar el formulario por fechas.
- Evitar pedidos repetidos (marca «único por afiliado»).
- Opciones que dependen de otra respuesta (ej. nivel y grado).
- Validar formato de mail, teléfono y CBU/CVU.
- Exportar a CSV los trámites de un formulario con sus respuestas.
- Registrar la entrega escaneando el QR de la credencial (mediano).
- Marca «solo encadenado».

**Desarrollos:**
- Requisitos para iniciar: es la fase 2 «sistema» del BACKLOG.
- Grupo familiar en el perfil del afiliado.
- Control contra una lista del sindicato: es la fase 3 «lista» del BACKLOG.
- Cupo o stock por seccional.
- Turnos con agenda.
- Entrada pública para quien no está en el padrón.
- Pago dentro del trámite.

## Próximos pasos propuestos

1. Probar el asistente con 2 o 3 trámites reales del kit de inicio de La Bancaria y ajustar las preguntas.
2. Con un trámite acordado con el sindicato, especificar el importador (ver el contrato) siguiendo el flujo de siempre: análisis primero y código después.
3. Evaluar si el asistente se suma como Herramienta en `/entornos`, como la Calculadora bancaria, y más adelante en el panel del sindicato.
