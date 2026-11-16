# PLAN_CONVENIO_ESCALAS.md — «Convenio y escalas» como Herramienta de `/entornos`

Fecha: 2026-11-15 · Acordado con SDN en Chat (decisiones D1–D12) ·
Origen: `docs/chat/2026-11-15-convenio-escalas-maquetas.html` (maquetas) y el
proyecto de Chat «Mitrabajo» (`claude/propuesta-convenio-escalas-v1.md`).
Leído contra el repo en el commit `af54958`. Este plan documenta lo acordado
**tal cual**; el avance va en `CLAUDE.md` («Herramientas») y en `BITACORA.md`.

## Qué se construye

Una Herramienta de `/entornos` → Herramientas, al lado de la Calculadora
bancaria y del Asistente de trámites, con tres partes:

1. **Escala vigente**: el afiliado elige rama, antigüedad, título y función de
   caja, y ve los valores de la grilla vigente del CCT 18/75, concepto por
   concepto, con su fuente.
2. **Convenio**: el CCT 18/75 como fichas por situación de vida, con buscador
   de texto, sin IA.
3. **Actualización automática de la grilla**: un proceso diario que encuentra
   la grilla nueva en labancaria.org, la lee, la controla y la publica sola si
   pasa todos los controles.

Nace en `/entornos` para validarla. Cuando esté validada pasa a la app del
afiliado: ese pase **no** entra en este plan (D12).

## Decisiones (2026-11-15)

- **D1 · Dónde vive.** `/entornos/herramientas/convenio-escalas`, con la
  misma puerta que las otras herramientas (`_exigir_pase` en la página,
  `_exigir_herramientas` en las API bajo
  `/api/entornos/herramientas/escalas/...`) y su tarjeta en la pestaña
  Herramientas de `templates/entornos.html`. No se toca `/app`, ni Tu recibo,
  ni `/app/convenio`, ni la Calculadora bancaria.
- **D2 · Se ve como la app, no como `/entornos`.** Como su destino es la app
  del afiliado, las pantallas se construyen con los dos modelos de diseño
  (`laguna` y `noticiero`, `PLAN_TEMAS.md`): `data-tema` y `data-paleta` en
  `<html>`, hojas `static/temas/laguna-escalas.css` y
  `noticiero-escalas.css`, encabezado común (`_encabezado.html`). En la
  herramienta hay un selector de modelo y de paleta (Colm3na / La Bancaria)
  para validar las cuatro combinaciones. No lleva la «colmena nocturna» de la
  calculadora. Las maquetas son la referencia de contenido y jerarquía; los
  colores y medidas salen de las variables del modelo, no de la maqueta.
- **D3 · Sin RAG y sin IA de consulta.** No se usa `rag.py` ni el módulo
  `convenio`: requieren infraestructura que ahora no se adquiere. La única
  IA de este plan es la lectura del PDF de la grilla (D9).
- **D4 · Es una consulta, no un control.** No controla el sueldo: le faltan
  datos. Reglas:
  - No hay total ni suma de conceptos, en ningún lado.
  - Texto fijo junto a los valores: «Son valores sueltos de la grilla, no se
    suman: esto no es tu sueldo. Faltan los conceptos de tu banco, los
    descuentos y los retroactivos.»
  - No se usan las palabras del control: «verificar», «verificación»,
    «diferencia», «te corresponde», «deberías cobrar», «control». Sin
    veredicto, sin semáforo, sin historial, sin envío al sindicato.
  - No compara con ningún recibo ni lee datos de `ReciboVerificado`.
  - Una sola salida hacia el control: el bloque «¿Querés controlar lo que te
    pagaron? Eso se hace con tu recibo real» con el enlace «Ir a Tu recibo»
    (en esta etapa, enlace informativo).
- **D5 · Lo cierto se distingue de lo que no.** Cada valor lleva una etiqueta
  visible: **Publicado** (sale de la grilla firmada; muestra período, fecha de
  publicación y enlace al PDF) o **Referencia** (no hay manera de saberlo para
  esa persona). La selección se muestra aparte: «Según lo que elegiste el
  dd/mm/aaaa». Sin simulaciones ni proyecciones en esta versión.
- **D6 · La selección la hace la persona.** El sistema no tiene rama,
  categoría ni fecha de ingreso (`Trabajador` solo guarda
  `fecha_afiliacion`). Campos: rama (Administrativa, Maestranza, Ordenanza),
  años de antigüedad o cargo jerárquico, título (sin, secundario, terciario,
  universitario), función de caja (sí/no). Tilde «Recordar mi selección»: la
  guarda con su fecha y se cambia con «Cambiar». Sin tilde no se guarda nada.
  En esta etapa se recuerda en el navegador (no hay cuenta de afiliado en
  `/entornos`); dónde vive al pasar a la app es parte de D12.
- **D7 · Evolución acotada.** Una tabla mes a mes de UN valor de grilla (el
  conformado, o el básico si la categoría no tiene conformado) para la
  categoría elegida, solo con los meses que tengan grilla publicada, con el
  porcentaje respecto del mes anterior. Texto fijo: «Es el valor de grilla de
  esta categoría, no lo que cobraste. No incluye retroactivos, aguinaldo,
  adicionales personales ni acuerdos de tu banco.» Nunca un gráfico de
  «sueldo».
- **D8 · Las grillas pasan a la base.** Hoy son archivos
  (`data/grillas_bancarias/AAAA-MM.json`, solo `2026-08`) y cada mes exige un
  despliegue. Tabla nueva con período, estado (`publicada`, `retenida`,
  `reemplazada`), contenido (el mismo JSON de hoy), fuente (URL de la nota y
  del PDF), fecha de publicación del sindicato, origen (`semilla`,
  `automatica`, `manual`), y el resultado de cada control. Los archivos de
  `data/` quedan como semilla. `grilla_bancaria.py` sigue **puro** (no importa
  `db`): recibe las grillas publicadas desde afuera. La Calculadora bancaria
  no puede cambiar de resultado: sus tests siguen en verde sin tocarlos.
- **D9 · Actualización automática.** Proceso diario dentro de la app (patrón
  de `resumen_diario.py` y `planificador.py`: hilo propio, reclamo con UPDATE
  condicional para que dos instancias no hagan lo mismo, nunca tumba el
  arranque). Prendido por variable de entorno; en este plan solo en Pruebas.
  1. **Buscar**: interfaz de WordPress de labancaria.org
     (`/wp-json/wp/v2/posts?search=grillas`): notas tituladas «GRILLAS
     ACTUALIZACIÓN SALARIAL dd-mm-aa», con el PDF de las grillas enlazado en el
     contenido; y la nota «ACTUALIZACIÓN SALARIAL <MES> AAAA: x,x%», que trae
     en texto el inicial, el ROE y el porcentaje. Con `urllib`, sin librerías
     nuevas (patrón de `correo.py`). Comprobado abierto el 2026-11-15.
  2. **Leer**: el PDF es escaneado (la de agosto se transcribió a mano de 8
     páginas). Páginas a imagen con `lectores.imagenes_pdf` y lectura con un
     **uso de IA propio** en `precios_ia.USOS`, elegible en `/plataforma` →
     Uso de IA y registrado con `db.registrar_uso_ia`. Salida: el JSON del
     formato actual. Se lee **dos veces**, en llamadas independientes.
  3. **Controlar** (módulo puro, sin `db` ni red):
     - C1 Estructura: las mismas ramas, categorías, jerarquías y adicionales
       que la grilla vigente; nada falta ni sobra.
     - C2 Doble lectura: las dos lecturas coinciden celda por celda.
     - C3 Anclas: el inicial y el ROE de la grilla leída son los del texto del
       comunicado, al centavo.
     - C4 Factor único: el factor implícito (valor nuevo / valor vigente) es
       el mismo en todos los importes, dentro de una tolerancia, y redondea al
       porcentaje publicado. Ojo: el porcentaje del comunicado está redondeado
       (agosto → septiembre de 2026 da 1,01896 y se publicó «1,9 %»), así que
       NO se controla contra `anterior × 1,019` exacto. La tolerancia se
       calibra con grillas reales en el bloque 6.
     - C5 Coherencia interna: básico = max(base × coeficiente, básico mínimo);
       escalafón no decreciente con la antigüedad.
     - C6 Período: es el mes siguiente al vigente; si hay un salto, retiene.
  4. **Publicar**: si pasan TODOS, se publica sola y avisa por Telegram
     (`telegram.enviar_en_segundo_plano`). Si falla alguno, queda `retenida`
     con el detalle del control, avisa, y la vigente sigue siendo la anterior.
     Una retenida se resuelve a mano desde la vista de estado (corregir y
     publicar, o descartar), con registro de quién y cuándo.
  5. **Si no encuentra nada** o cambió el formato del sitio: no inventa.
     Después de la fecha esperada (el comunicado sale entre el 11 y el 20),
     avisa una vez que no encontró la grilla del mes.
  6. **En la consulta**: mientras hay un comunicado nuevo sin grilla
     publicada, se muestra la vigente con su fecha y el cartel «Hay una
     actualización publicada el dd/mm. La estamos cargando.»
- **D10 · ROE como referencia.** No hay manera de saber la banda del banco de
  la persona: se muestra el valor mensual que publica el sindicato, etiquetado
  **Referencia**, con «El monto real depende de tu banco».
- **D11 · Convenio en fichas, sin IA.** Datos en un archivo versionado
  (`data/convenios/`), armado desde el texto del CCT 18/75 (62 artículos más
  disposiciones transitorias; PDF con texto extraíble en
  `labancaria.org/wp-content/uploads/2023/07/1875.pdf`; ver también
  `docs/cct-1875-bancarios.md`). Cada artículo con su texto **literal**.
  Entradas por situación («Voy a ser madre o padre», «Me caso», «Estudio o me
  recibí», «Trabajo en caja», «Trabajo en zona alejada», «Falleció un
  familiar») que llevan a sus artículos, e índice completo. Buscador de texto
  en el navegador sobre títulos y texto literal. Cada ficha: resumen «en
  simple», importe vigente cuando el artículo tiene un valor en la grilla
  (etiqueta Publicado), y texto literal. Los resúmenes nacen `sin_revisar` y
  la pantalla lo dice («Resumen sin revisar por el sindicato»); pasan a
  `revisado` con quién y cuándo. El botón «Hacer una consulta gremial» en esta
  etapa solo muestra adónde iría (trámite), no crea nada.
- **D12 · Fuera de este plan.** El pase a la app del afiliado (ruta, módulo
  habilitable, dónde se guarda la selección en la cuenta, entrada en el menú);
  las consultas en lenguaje libre; cualquier cruce con Tu recibo o con el
  motor v2; otros convenios y sindicatos (el diseño de datos no debe
  impedirlos, pero solo se construye bancarios); notificar a afiliados cuando
  hay grilla nueva.

## Bloques

Code planifica y coordina; desarrollo y QA van a agentes (Sonnet 5.5), en
paralelo donde se indica. Quien hace QA de un bloque no es quien lo
desarrolló. Cada bloque: rama propia, tests del área, versión de Plataforma,
bitácora, PR y merge con el CI en verde.

0. **Lectura y brechas (Code, sin código).** Leer este plan, las maquetas,
   `CLAUDE.md` («Herramientas», «Método de trabajo»), `PLAN_TEMAS.md`,
   `grilla_bancaria.py`, `resumen_diario.py`, `lectores.py`, `precios_ia.py`,
   `templates/convenio.html` y `static/temas/laguna-convenio.css`. Presentar
   brechas y resolver los «Abiertos» de a UNA pregunta. Recién con el visto
   bueno de SDN se pasa al bloque 1.
1. **Grillas en la base.** Tabla y migración, semilla desde `data/`,
   `grilla_bancaria.py` puro recibiendo las publicadas. QA: la calculadora da
   lo mismo que antes.
2. **Motor de la consulta** (puro): dada una selección y un período, devuelve
   los conceptos con importe, etiqueta, nota y fuente, y la evolución. API.
   *En paralelo con 4 y 5.*
3. **Pantallas Escala vigente y Selección**, en los dos modelos y las dos
   paletas. *Después del 2.*
4. **Convenio en fichas**: archivo de datos, pantalla y buscador.
5. **Actualización automática**: búsqueda, lectura, controles, publicación,
   hilo diario, avisos y vista de estado de las grillas en la herramienta.
6. **Prueba real.** Dos corridas con el propio proceso:
   - **Agosto de 2026** (nota «GRILLAS ACTUALIZACIÓN SALARIAL 11-09-26»): la
     lectura automática tiene que dar celda por celda lo mismo que
     `data/grillas_bancarias/2026-08.json`, transcripta a mano. Es la medida
     de cuánto se puede confiar en la lectura.
   - **Septiembre de 2026** (nota «20-10-26»): primera grilla nueva de punta a
     punta, contra agosto como vigente. Con eso se calibra C4.
   Octubre entra sola cuando el sindicato la publique. Se reporta control por
   control; si una queda retenida, se reporta por qué antes de tocar nada.
7. **QA transversal** (agentes de QA):
   - Un test que falla si en las pantallas aparece una palabra de control
     (D4) o cualquier total o suma de conceptos.
   - Toda cifra visible tiene su etiqueta (D5).
   - Tests de cada control con grillas adulteradas a propósito: una celda
     cambiada, una categoría faltante, un porcentaje distinto en un adicional,
     un mes salteado, dos lecturas que no coinciden.
   - El proceso diario con la fuente caída, con respuesta vacía y con el
     formato cambiado: no publica y avisa.
   - Dos instancias a la vez no publican dos veces.
   - Revisión de diseño con XSD y las reglas de `diseno-mi-trabajo`, en
     teléfono y escritorio, en las cuatro combinaciones de modelo y paleta.
   - Cada error se clasifica por origen (la app, los datos, la configuración)
     antes de tocar código.
8. **Cierre.** `CLAUDE.md`, `BITACORA.md`, `docs/INDICE.md`, entrada en
   Recursos si corresponde, y una guía corta para quien valide.

## Abiertos (Code los pregunta de a uno, con opciones y recomendación)

1. Nombre y forma de la tabla de grillas: solo bancaria o genérica por
   sindicato y convenio desde ahora.
2. Modelo por defecto del uso de IA que lee la grilla.
3. Tolerancia de C4 y qué hacer cuando un acuerdo cambia la estructura (suma
   fija, concepto nuevo): hoy queda retenida y se resuelve a mano.
4. Hora del chequeo diario y a partir de qué día avisa que no encontró la
   grilla del mes.
5. Quién redacta los resúmenes «en simple» de las fichas (agentes, desde el
   texto literal) y quién los marca como revisados.
6. Cargo jerárquico en la selección: lista de jerarquías de la grilla o fuera
   de la primera versión.
7. Si la vista de estado de las grillas va dentro de la herramienta o en
   `/plataforma`.

## Criterios de aceptación

- La Calculadora bancaria (v1 y v2) da exactamente lo mismo que antes.
- Con la selección «Administrativa, 6 años, universitario, sin caja» y la
  grilla de agosto de 2026, los valores coinciden al centavo con
  `data/grillas_bancarias/2026-08.json`.
- Ninguna pantalla muestra un total ni una palabra de control.
- La lectura automática de agosto de 2026 coincide con la transcripta a mano,
  o las celdas distintas están listadas.
- Septiembre de 2026 quedó cargada por el proceso, con cada control
  informado; o retenida con el motivo a la vista.
- Una grilla adulterada nunca se publica.
- Las pantallas pasan la revisión de diseño en los dos modelos.
