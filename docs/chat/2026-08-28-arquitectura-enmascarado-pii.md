<!--
Origen: Chat, proyecto "Mitrabajo", conversación 3616b140 ("Continuar trabajo
en chat anterior"), mensajes 215-218 del 2026-08-28. El archivo se generó en
Chat como ARQ_ENMASCARADO_PII.md y nunca se había bajado al repo: por eso
PLAN_MOTOR_V2.md (D7) habla de "la solución que el equipo acordó" sin
nombrarla. Se copia sin cambios el 2026-09-24. La versión revisada para
ejecutar es PLAN_ENMASCARADO.md, en la raíz.
-->

# Arquitectura: enmascarado local de datos identificatorios antes de la API

Documento de diseño para debatir con el equipo. Una vez acordado, sirve como
especificación para Claude Code (rama nueva, no mezclar con trabajo en curso).

## Objetivo

Que los datos identificatorios del recibo (CUIL, apellido y nombre del
trabajador, CUIT y razón social del empleador, DNI) **no salgan del servidor**
al procesar un recibo con la API de IA. La API debe recibir el recibo con esas
zonas enmascaradas y devolver montos, conceptos y estructura como hasta ahora.

No es una cuestión de costos: es un argumento de confidencialidad frente a
sindicatos y empresas clientes ("los identificatorios nunca salen de nuestra
infraestructura").

Restricciones duras:
- NO perder fiabilidad de extracción respecto al flujo actual.
- NO degradar la performance de forma perceptible (hoy ~30s, dominados por la
  generación de la API; el paso local debe sumar segundos, no decenas).

## La clave del diseño (que lo hace simple)

**La aplicación ya conoce los datos que hay que ocultar antes de procesar.**
El trabajador entra con su CUIL; su nombre está en la base desde el registro;
el CUIT del empleador está o estará registrado (pluriempleo). Por lo tanto:

- NO se necesita un OCR que "descubra" cualquier PII en cualquier documento
  (problema abierto, frágil).
- SÍ se necesita ubicar en el recibo **cadenas ya conocidas** (el CUIL exacto
  del usuario logueado, su apellido) más **patrones triviales** (CUIT/CUIL:
  11 dígitos con formato XX-XXXXXXXX-X; DNI: 7-8 dígitos junto a su etiqueta).
  Buscar texto conocido es mucho más confiable que reconocer texto desconocido.
- La "reinserción" del resultado es un merge trivial: el JSON vuelve anónimo y
  la app le adjunta la identidad que ya tenía en la base. No hay que
  reconstruir nada desde la respuesta de la API.

## Pipeline propuesto

1. **OCR local liviano** (Tesseract u otro OCR CPU, sin GPU) sobre la imagen
   del recibo. Propósito: obtener texto + posiciones (bounding boxes). NO se
   usa para extraer los datos del recibo — solo para ubicar qué tapar.
2. **Verificación de pertenencia (local, ANTES de enmascarar):** confirmar que
   el CUIL del recibo coincide con el del usuario logueado. Este chequeo hoy
   ocurre con ayuda de la API; DEBE mudarse acá, porque después del enmascarado
   la API ya no puede hacerlo.
3. **Enmascarado dirigido:** pintar rectángulos opacos sobre: el CUIL del
   usuario (dondequiera que aparezca), su apellido/nombre, todo patrón
   CUIT/CUIL/DNI detectado, y la razón social del empleador si está registrada.
4. **Enviar la imagen enmascarada** a la API de Anthropic, igual que hoy.
   Montos, conceptos y estructura quedan intactos: es lo que la IA necesita.
5. **Merge local:** al JSON devuelto se le adjunta la identidad desde la base.
   El resto del flujo (validador, semáforo, reporte) no cambia.

### Optimización para el formato nuevo (Anexo III, Decreto 407/2026)

El recibo nuevo tiene formato único obligatorio: los datos identificatorios
están siempre en la misma zona. Para recibos detectados como formato nuevo,
se puede tapar la zona del encabezado **por coordenadas**, casi sin depender
del OCR. Para el formato clásico (heterogéneo) se usa el enmascarado dirigido
completo. El extractor ya distingue ambos formatos (`formato` en su JSON).

## Política de fallback (decisión de producto, tomarla explícita)

Caso crítico: **el OCR local NO logra ubicar el CUIL conocido en el recibo**
(foto borrosa, escaneo malo). Ese es justamente el caso en el que NO
corresponde "mandar todo a la API como está", porque no se sabe qué se está
dejando pasar. Orden de acciones propuesto:

1. Reintento local con la imagen preprocesada (contraste, deskew, mayor DPI).
2. Si sigue fallando: pedir al usuario una foto mejor (mensaje claro).
3. Como última opción, y solo si el producto lo decide: enviar sin enmascarar
   CON AVISO explícito al usuario y registro del hecho.

El punto 3 queda deshabilitado por defecto hasta que se debata.

## Dónde corre (Render)

- El OCR liviano por CPU procesa una página en segundos con poca RAM: Render
  lo soporta sin cambio de plan del web service.
- Recomendación: correrlo en un **Background Worker** (~US$25/mes, ya
  contemplado como opcional en la estimación de costos) con una cola simple,
  para que una ráfaga de recibos no bloquee el proceso web. Si en el prototipo
  el tiempo por página resulta ínfimo, puede evaluarse dejarlo en el proceso
  web como primera iteración y mover a worker después.

## Qué NO hacer (por ahora)

- NO reemplazar la API por un modelo local completo de visión/extracción:
  para igualar la fiabilidad actual harían falta modelos grandes con GPU, y
  Render no está pensado para GPU. Se perdería fiabilidad, que es línea roja.
  El OCR local se usa SOLO para enmascarar.
- NO intentar detectar "cualquier PII" genérica con NER/ML: alcanza con las
  cadenas conocidas + patrones de documento argentinos.

## Complemento no técnico (fuera del alcance de Code, pero parte del argumento)

Averiguar y documentar las opciones contractuales del proveedor (retención de
datos, acuerdos comerciales; disponibilidad del mismo modelo vía AWS Bedrock /
Google Vertex). El discurso completo ante un cliente es: técnico ("los
identificatorios nunca salen de nuestro servidor") + contractual ("lo que
sale se procesa bajo acuerdo de no retención").

## Bloques de implementación para Code

Rama nueva: `enmascarado-pii`. Antes de codear: leer CLAUDE.md, HISTORIAL.md
y este documento; escribir el plan del bloque 1 y frenar para revisión.

1. **Prototipo de OCR + búsqueda dirigida** (sin tocar el flujo productivo):
   script que recibe una imagen/PDF de recibo + CUIL/apellido conocidos, y
   devuelve las bounding boxes encontradas. Probar con los 10 recibos
   sintéticos anonimizados (carpeta de pruebas) y con al menos un recibo de
   formato nuevo. Criterio de aceptación: ubica el CUIL y el apellido en
   los 10; reporta claramente cuando no encuentra.
2. **Enmascarado:** dada la imagen y las boxes, producir la imagen tapada.
   Verificar visualmente que montos y conceptos quedan intactos.
3. **Verificación de pertenencia local** (CUIL del recibo vs. usuario
   logueado) con sus casos de error definidos.
4. **Integración al flujo:** el extractor recibe la imagen enmascarada; merge
   de identidad desde la base al JSON resultante. Feature flag para poder
   activar/desactivar el enmascarado por configuración (arranque apagado en
   producción hasta validar fiabilidad).
5. **Fallback:** implementar los pasos 1 y 2 de la política (reintento
   preprocesado, pedir mejor foto). El paso 3 queda como configuración
   deshabilitada.
6. **Medición:** comparar sobre los 10 recibos de prueba la extracción con y
   sin enmascarado (mismos montos, mismos conceptos, misma clasificación).
   Criterio de aceptación global: cero regresión en la extracción de montos.

## Método (el de siempre)

Un bloque por vez; plan antes de codear; verificación con pruebas reales; un
test por archivo (no pytest batcheado); commit por bloque; actualizar
HISTORIAL.md al cerrar cada bloque y CLAUDE.md si cambia algo estructural.
No avanzar al bloque siguiente sin cumplir el criterio de aceptación del
anterior.
