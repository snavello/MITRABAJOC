# PLAN MOTOR V2 — Lectura y validación de recibos

Plan del motor de análisis de recibos, acordado el 2026-09-04. Igual que el
resto de los planes del proyecto: documenta el plan **tal cual se acordó** y
no se actualiza retroactivamente. La fuente de verdad sobre qué está hecho
es "Estado actual" de CLAUDE.md; el avance ítem por ítem se lleva en el
tablero **Motor v2 · Avance**, que es una página compartida donde el equipo
marca pendiente / en curso / hecho / bloqueado.

**Este archivo se escribió el 2026-09-13 reconstruyendo el plan desde ese
tablero.** Hasta entonces el plan vivía SOLO ahí: el tablero citaba un
`PLAN_MOTOR_V2.md` que no existía en el repositorio. Un tablero no está
versionado, no viaja con el código y no se puede diffear — de ahí este
archivo. El texto funcional de cada ítem viene del tablero; las secciones de
encuadre ("El modo de falla", "Premisas", "Evidencia de campo") se
escribieron acá a partir del código actual y de mediciones reales, y están
marcadas como tales.

**Al 2026-09-13 no empezó ningún bloque.** Lo que corre en producción es el
motor v1.

**Y el plan todavía no está cerrado** (al 2026-09-14): los bloques pueden
cambiar de alcance, de orden o de existencia antes de que se escriba la
primera línea. Esto es un borrador de trabajo versionado, no un contrato.

---

## Qué es y qué NO es

**Es** un cambio en la forma de leer y de juzgar un recibo: cómo se le
pregunta al modelo, qué se verifica antes de juzgar, y cómo se reconoce cada
renglón contra el catálogo del sindicato.

**No es** un cambio de modelo de IA. Un modelo mejor no arregla el modo de
falla de abajo, porque el problema no es la capacidad del modelo sino que el
sistema no tiene forma de saber cuándo leyó mal.

**No entra en esta tanda**: nada del BACKLOG que no esté acá, y ninguna
funcionalidad nueva para el afiliado que no derive de estos bloques.

---

## El modo de falla que ordena todo el plan

*(Encuadre escrito para este archivo, sobre el código de `extractor.py` y
`validador.py` en `main`.)*

Hoy el recorrido de un recibo es: una sola llamada a la IA con la imagen
entera → un JSON con **un único campo `confianza` para todo el recibo** →
si no dice "baja", se valida todo contra las fórmulas del convenio.

Las tres piezas se combinan en una sola falla, y es la que motiva la v2:

1. El modelo lee un renglón con un error.
2. El sistema **no tiene forma de saber que ese renglón puntual está flojo**,
   porque la confianza es del recibo entero.
3. Lo empuja igual a la validación, la cuenta da distinta, y el afiliado ve
   *"tu aporte jubilatorio no coincide"*.

La app no se equivocó al calcular: se equivocó al leer, tres pasos antes, y
no tenía cómo darse cuenta. Todo el plan es, en el fondo, **poner una
compuerta entre leer y juzgar**.

Cuatro límites concretos del v1, cada uno con su bloque:

| Límite de hoy | Dónde está | Lo resuelve |
|---|---|---|
| Se lee solo la primera página; un PDF con texto se convierte a imagen igual | `extractor._imagen_desde_pdf` | 1.1 |
| Una sola confianza para las 17 líneas | el esquema de `extraer()` | 1.3 |
| Si nada matchea, se usa el total impreso como base aproximada | `validador.py`, el fallback de `total_ingresos` | 3b.4 |
| El afiliado decide con un interruptor si un concepto es remunerativo | pantalla del trabajador, viene marcado que sí | 3c.1 |

---

## Premisas

1. **Sin línea de base no se avanza.** El bloque 0 no toca el motor: mide el
   motor actual contra recibos reales anotados a mano. Sin ese número no se
   puede afirmar que la v2 mejora, y "parece que anda mejor" no es un
   criterio.
2. **El motor nuevo y el viejo conviven.** Una variable de entorno decide
   cuál corre. Se prueba en producción con vuelta atrás inmediata, y el
   viejo recién se retira con datos que lo respalden.
3. **Cada bloque se mide contra la línea de base antes de pasar al
   siguiente.** Si algo empeora, no se sigue hasta entender por qué.
4. **No poner en peligro la demo.** Con la bandera apagada, el
   comportamiento es exactamente el de hoy.

---

## Decisiones tomadas

Las transversales, las que explican por qué los bloques están armados así.

**D1. Tres lecturas cortas en vez de una grande.** Pedirle todo junto a un
modelo es pedirle que no se distraiga en 17 renglones a la vez. Se parte en
encabezado y estructura / renglones / totales y contribuciones, cada una con
su esquema y **salida estructurada** (el modelo responde con datos, no con
texto que después hay que interpretar).

**D2. La confianza es de cada renglón, no del recibo.** Es el cambio
conceptual que habilita todo lo demás: un renglón dudoso se puede señalar,
releer o dejar fuera del cálculo **sin descartar el recibo entero**.

**D3. El cierre aritmético es una compuerta, y no usa IA.** Antes de juzgar
nada: suma de haberes = total de haberes, suma de descuentos = total de
descuentos, haberes − descuentos = neto, y en cada renglón con porcentaje,
base × porcentaje = importe. Tolerancia de **$1**.

**D4. Releer con pista, no "releé de nuevo".** Si un bloque no cierra, se le
dice al modelo exactamente qué no coincide (*"la suma de descuentos da $X y
el total impreso dice $Y"*). Hasta dos veces.

**D5. "Lectura incierta" es un estado, no un error.** Si después de releer
sigue sin cerrar, el recibo **no se valida**: se muestra lo leído, se
señalan los renglones dudosos y se pide una foto mejor. Es la diferencia
entre decirle a alguien "te descontaron mal" y "no pude leer bien tu
recibo". Hoy esas dos situaciones se ven iguales.

**D6. Lo desconocido no entra en la base de cálculo.** Un concepto que el
sindicato todavía no confirmó deja de sumar. Si quedó afuera un haber, las
fórmulas de porcentaje dicen **"no verificable"** en lugar de mostrar una
diferencia que no existe. Desaparece también el atajo del total impreso como
base aproximada. **Consecuencia a comunicar**: al principio habrá más "no
verificable" y menos "diferencias"; es lo correcto, pero un sindicato que ve
caer su número de hallazgos necesita que se lo expliquen antes, no después.

**D7. El enmascarado tiene su lugar reservado desde el primer bloque.** Se
deja una función por la que pasa toda imagen antes de salir hacia la API. En
este plan **no hace nada** — es deliberado: primero el lugar, después la
solución que el equipo acordó. Si el enganche no existe desde el principio,
después hay que salir a buscar todos los lugares por donde sale una imagen.
No confundir con la anonimización que ya existe: esa es del **panel del
sindicato**, que solo ve nombre y CUIL de los recibos que el afiliado envió
explícitamente. Son dos capas distintas y ninguna reemplaza a la otra.

**D8. La IA que reconoce conceptos elige de una lista cerrada.** Nunca
inventa un concepto: elige entre candidatos ya cargados, o el renglón queda
"desconocido" y va a la cola del administrador.

---

## Los ocho bloques, en orden de ejecución

El orden es por dependencia, no por tamaño. Los números de bloque son los
del tablero y no coinciden con el orden: el 4 se ejecuta antes que el 3
porque es chico e independiente, y el 3 es el más grande de todos.

### 1º · Bloque 0 — Golden set y línea de base

Antes de tocar nada, medir con recibos reales cómo lee y valida la versión
actual. **Sin este número no se puede saber si la v2 mejora o empeora.**

- **0.1 Reunir recibos reales.** Al menos **60** de los sindicatos piloto
  (20 del formato nuevo del Decreto 407 y 40 del clásico), incluyendo fotos
  malas, recibos de dos páginas y aguinaldos. Se guardan **fuera del
  repositorio**: tienen datos personales.
  *Code*: prepara la carpeta, el `.gitignore` y las instrucciones.
  *Datos*: pedirlos a los sindicatos piloto con consentimiento y copiarlos.
  **Sin esto no arranca nada.**
- **0.2 Anotar la verdad de campo.** Por cada recibo, qué dice realmente:
  CUIT, CUIL, período, tipo de liquidación, totales, y cada renglón con su
  importe, su tipo y su concepto.
  *Code*: genera un borrador con la lectura actual para que la persona solo
  corrija lo que está mal.
  *Datos*: revisar y corregir, recibo por recibo. **Aproximadamente una
  tarde cada 30 recibos.**
- **0.3 Script de medición.** Lee todo el golden set, compara contra la
  anotación y produce un informe: exactitud de encabezado, calidad de
  líneas, cierre aritmético, reconocimiento de conceptos, costo y tiempo por
  recibo.
  *Code*: lo escribe y lo deja listo para correr en cada bloque.
- **0.4 Línea de base.** Correr la medición con el motor de hoy y guardar el
  resultado.
  *Producto*: aprobar que sirva como línea de base, o pedir más recibos si
  la muestra quedó chica.

### 2º · Bloque 1 — Extractor v2: lectura por bloques

- **1.1 Todas las páginas y el texto del PDF.** Hoy se lee solo la primera
  página y el PDF se convierte a imagen aunque traiga texto. Con esto, un
  recibo de dos carillas se lee completo y los números de un PDF con texto
  se toman exactos.
- **1.2 Punto de enganche del enmascarado.** Ver D7.
  *Dev*: integrar ahí la solución de enmascarado acordada, cuando esté lista.
- **1.3 Tres lecturas con salida estructurada.** Ver D1 y D2. Cada renglón
  trae su nivel de confianza. Los prompts quedan con **versión registrada**.
  *Producto*: leer los prompts (están en castellano) y validar que reflejen
  el vocabulario real de los recibos argentinos.
- **1.4 Control de respuestas cortadas.** Hoy un recibo muy largo puede
  quedar cortado a la mitad sin que nadie se entere. Se detecta, se relee por
  partes y, si aun así no entra, hay un error claro.
- **1.5 Registro de cada lectura.** Versión del prompt, modelo, tokens,
  tiempo, intentos y respuesta cruda. Permite reproducir un caso y comparar
  versiones.
  *Dev*: correr la migración en el Postgres local de Docker y después en
  Render.
- **1.6 Bandera de convivencia `MOTOR_V2`.** Ver premisa 2.
  *Plataforma*: prenderla o apagarla en Render cuando el equipo lo decida.
- **1.7 Medir contra la línea de base.**
  *Producto*: decidir si se avanza al bloque siguiente con esos números.

### 3º · Bloque 2 — Cierre aritmético como compuerta

- **2.1 Reglas de cierre.** Ver D3. Módulo puro con sus tests.
- **2.2 Relectura con pista.** Ver D4. Se guardan los intentos.
- **2.3 Estado "lectura incierta".** Ver D5.
  *Producto*: aprobar los textos que ve el afiliado en ese estado.
- **2.4 El tablero cuenta el estado nuevo.** El Panel Sindical distingue
  "lectura incierta" de "con discrepancias", para no inflar el porcentaje de
  recibos con diferencias.
- **2.5 Revisión de los recibos que cambiaron.** Comparar con la línea de
  base: cuáles pasaron de "con discrepancias" a "lectura incierta" o a "OK".
  *Code*: lista los que cambiaron de estado, con el motivo.
  *Datos*: revisar esa lista uno por uno y confirmar.

### 4º · Bloque 4 — Motor de reglas

Se hace antes del bloque 3 porque es chico e independiente. Cierra un riesgo
de seguridad, evita aplicar fórmulas mensuales a un aguinaldo, ordena los
hallazgos por gravedad y unifica el formato de los importes.

- **4.1 Evaluador seguro de fórmulas.** Hoy las fórmulas del sindicato se
  ejecutan con una función de Python que, con una expresión maliciosa,
  **permitiría ejecutar código en el servidor**. Se reemplaza por un
  evaluador que solo entiende sumas, restas, multiplicaciones, divisiones,
  las variables del motor y tres funciones. La gramática que ve el admin no
  cambia.
  *Dev*: verificar contra las fórmulas reales de **producción** (no solo la
  demo) que todas siguen evaluando igual.
- **4.2 Tipo de liquidación.** El extractor detecta si el recibo es mensual,
  quincenal, aguinaldo, vacaciones o liquidación final. A un aguinaldo no se
  le aplican las fórmulas de aportes con tope (tienen reglas propias que
  esta versión no calcula): se informa **"no verificable"** en vez de una
  diferencia falsa.
- **4.3 Contribuciones patronales (formato nuevo).** En el recibo del
  Decreto 407 se leen las contribuciones del empleador y se verifica solo la
  aritmética. Reportes deja de mostrar un costo laboral estimado con
  porcentajes fijos cuando el recibo trae el real.
- **4.4 Severidad y motivo en cada hallazgo.** Cada hallazgo se clasifica
  como **error**, **advertencia** o **información**, y lleva un código
  estable (`JUB_DIFERENCIA`, `TOTAL_NO_CIERRA`). Es lo que permite ordenar la
  pantalla y, más adelante, hacer estadística por tipo de problema.
  *Producto*: validar el mapeo de severidades con criterio del sindicato.
- **4.5 Formato de importes es-AR.** Hoy la tabla muestra `$345.100,00` y los
  mensajes `$100,063.75`. Todo pasa a formato argentino.

### 5º · Bloque 3 — Catálogo maestro y reconocimiento de conceptos

El corazón del cambio para escalar a muchos sindicatos y empleadores. Es el
bloque más grande y se divide en tres tandas: **3a** el modelo de datos,
**3b** el reconocimiento, **3c** las pantallas.

**Por qué hace falta**: el código de concepto **no es una clave confiable
entre empleadores** — cada empleador le pone el que quiere — así que solo
pesa mirando recibos de uno solo (ver BACKLOG.md, 2026-09-13).

#### 3a · Modelo de datos

- **3a.1 Catálogo maestro de plataforma.** Una lista nacional de conceptos
  canónicos (básico, antigüedad, presentismo, horas extra, aguinaldo,
  jubilación, PAMI, obra social, cuota sindical, Ganancias, anticipos,
  contribuciones…) con sus atributos: si es haber o descuento, si es
  remunerativo, si le aplica tope. La mantiene Colm3na y la usan todos los
  sindicatos. **23 conceptos** en la siembra inicial.
  *Producto*: revisar los 23 y sus atributos con alguien que sepa de
  liquidación de sueldos.
- **3a.2 Conceptos del sindicato vinculados al maestro.** Cada concepto del
  catálogo de un sindicato puede apuntar a un concepto maestro. No cambia
  cómo funcionan las fórmulas.
- **3a.3 Tabla de alias y migración.** Las distintas formas en que cada
  empleador escribe un concepto (`AP. PERS. JUB. ANSES`, `Jubilación 11%`)
  pasan de una lista dentro del concepto a una tabla propia, con el
  empleador, quién lo confirmó y cuántas veces se vio. Los alias de
  conceptos de ley se **comparten entre sindicatos**.
  *Dev*: correr la migración en Docker con datos de demo cargados, revisar
  el resultado, y recién después en Render.
- **3a.4 Vectores semánticos de conceptos.** Cada concepto y alias se
  convierte en un vector para comparar por significado, reutilizando el
  mismo componente que ya usa el bot del convenio. **Sin costo por
  consulta.**
  *Dev*: verificar el tiempo de indexación y que la librería de embeddings
  esté fijada a la versión exacta (ver la regla de `fastembed` en CLAUDE.md).

#### 3b · Reconocimiento

- **3b.1 Normalización de texto y abreviaturas.** Mayúsculas, sin acentos ni
  puntuación, y un diccionario que expande abreviaturas (`ADIC` →
  `ADICIONAL`, `O.S.` → `OBRA SOCIAL`, `AP PERS` → `APORTE PERSONAL`). Es la
  capa más barata y resuelve una parte grande de las variantes.
  *Datos*: alimentar el diccionario con las abreviaturas del golden set y de
  los primeros sindicatos.
- **3b.2 Reconocimiento en seis capas.** Cada renglón pasa por:

  | # | Capa | Acepta |
  |---|---|---|
  | 1 | Coincidencia exacta de código | siempre |
  | 2 | Texto normalizado | siempre |
  | 3 | Alias del sindicato | siempre |
  | 4 | Alias maestro (compartido) | siempre |
  | 5 | Parecido semántico | desde **0,90**; sugiere entre 0,75 y 0,90 |
  | 6 | IA con lista cerrada | desde **0,85** |
  | — | Desconocido | va a la cola del admin |

  Los umbrales son valores con nombre, que se ajustan con el golden set.
- **3b.3 Capa de IA por lote.** Solo para renglones de **descuento** que no
  se resolvieron antes: una única consulta por recibo con la lista cerrada
  de candidatos (D8). Su costo se registra aparte.
  *Plataforma*: mirar el costo de "normalización" en el uso de IA durante el
  piloto.
- **3b.4 Lo desconocido no entra en la base.** Ver D6.
  *Producto*: aceptar explícitamente el cambio de comportamiento.

#### 3c · Pantallas

- **3c.1 App del trabajador sin el interruptor "¿Remunerativo?".** El
  afiliado deja de decidir si un concepto es remunerativo. En su lugar ve
  "conceptos que tu sindicato todavía no cargó", con la sugerencia del
  sistema.
  *Producto*: aprobar los textos nuevos.
- **3c.2 Cola de pendientes del administrador.** En el panel del sindicato,
  cada concepto pendiente muestra la sugerencia (con qué capa y con qué
  confianza) y tres botones: confirmar como sugerido, vincular a otro, o
  crear uno nuevo. **Al confirmar se crea el alias y las próximas lecturas
  del mismo empleador se resuelven solas.**
  *Datos*: probarla de punta a punta con un recibo de un empleador nuevo.
  *Sindicato*: operarla. Alguien en cada sindicato tiene que mirar la cola
  cada tanto (hay un globo en la portada del admin).
- **3c.3 Aprendizaje agrupado por destino.** Subir varios recibos para
  aprender conceptos agrupa las propuestas por a qué concepto apuntan, y
  dice "visto N veces en M empleadores".
- **3c.4 Catálogo maestro en plataforma.** Pantalla para mantener el
  catálogo maestro y **promover a "compartido"** los alias de conceptos de
  ley aprendidos en un empleador.
  *Plataforma*: mantenerlo. Es una tarea periódica de Colm3na, no del
  sindicato.

### 6º · Bloque 7 — Escala salarial por categoría

Primera comprobación contra datos externos. Responde la pregunta *"¿me pagan
la categoría que corresponde?"*.

- **7.1 Tabla de escalas y carga masiva.** Por sindicato: categoría, básico,
  vigencia desde/hasta y fuente. Se carga fila por fila o pegando un CSV; el
  sistema **rechaza tramos superpuestos**. Cada paritaria es un pegado nuevo
  con su fecha.
  *Datos*: conseguir las escalas vigentes del convenio de cada sindicato
  piloto y cargarlas.
  *Sindicato*: mantenerlas al día en cada paritaria.
- **7.2 Alias de categoría.** Cada empleador la escribe a su manera
  ("Vendedor B", "VEND. B", "Cat. B"). Se resuelve con el mismo
  reconocimiento en capas de 3b; lo que no se reconoce va a la cola.
- **7.3 Variables del motor y comparación "mínimo".** Las fórmulas pueden
  usar el básico de la categoría vigente y los años de antigüedad
  (calculados con la fecha de ingreso que ya lee el extractor). Una fórmula
  puede ser de tipo **"mínimo"**: un básico por encima de la escala no es
  error. **Si el dato externo no está para ese período, la fórmula es "no
  verificable"; nunca se usa el valor más cercano.**
  *Producto*: definir con alguien que conozca cada convenio las fórmulas
  reales (antigüedad, presentismo, adicionales) de los sindicatos piloto.
- **7.4 Hallazgos de escala en el resultado y el tablero.** El afiliado ve
  "básico por debajo de la escala del convenio (vigencia, fuente)". El
  tablero guarda el dato para, más adelante, listar empresas que pagan por
  debajo de escala.

### 7º · Bloque 5 — Exposición del resultado

- **5.1 Veredicto y hallazgos.** Primero un veredicto en tres estados (todo
  en orden / encontramos N diferencias por $X / no pudimos leer bien).
  Después cada hallazgo como tarjeta: concepto con nombre legible, esperado,
  figura, diferencia, **la regla del sindicato que lo produjo**, la confianza
  de lectura si es baja, y la explicación posible.
  *Producto*: revisar la maqueta antes de que se codifique la versión final.
- **5.2 Acciones: enviar al sindicato e iniciar reclamo.** Desde cada
  hallazgo se puede enviar el recibo al sindicato o iniciar el trámite
  "Reclamo de aportes" con período, concepto y montos ya cargados.
  *Sindicato*: marcar en el constructor de trámites cuál es su formulario de
  reclamo de aportes.
- **5.3 "Corregí un dato".** El afiliado puede corregir un renglón o un total
  mal leído y reprocesar. **La corrección queda registrada: es la mejor
  señal de qué le cuesta leer al extractor.**
- **5.4 Comparación con el recibo anterior (opcional).** Solo si el afiliado
  ya tiene en su historial un recibo del mismo empleador del período
  anterior: bruto, neto y cada aporte con flechas. No se le pide ningún dato
  nuevo.
- **5.5 Prueba con personas ajenas al equipo.** Dos personas que no conocen
  la app miran tres recibos reales y tienen que poder decir por qué hay una
  diferencia, de qué regla sale y qué hacer.
  *Producto*: organizar la prueba y registrar qué no se entendió.

### 8º · Bloque 6 — Operación

- **6.1 Cola asíncrona de lecturas.** La app ya no espera a la IA con la
  pantalla congelada: crea un trabajo, muestra progreso ("leyendo…
  verificando…") y avisa al terminar. **Hasta 4 lecturas simultáneas por
  proceso**; las que quedan colgadas por un reinicio se marcan con error.
  Mismo patrón que ya usa la indexación del convenio.
  *Dev*: verificar en Render el comportamiento con un solo proceso y sus
  hilos.
- **6.2 Modelo económico y cascada.** Se mide un modelo más barato sobre el
  golden set. **Solo si lee casi igual de bien (dentro de 2 puntos)** se
  activa la cascada: económico primero, y el principal solo si el cierre
  falla. Puede bajar el costo por recibo a un tercio.
  *Producto*: decidir con los números si se activa.
- **6.3 Política de retención.** Cuánto tiempo se guarda cada cosa: la
  respuesta cruda de la IA, el JSON completo con nombre del trabajador, los
  archivos de recibos sospechosos. **Propuesta inicial: 180 días para lo
  identificatorio, 90 para los sospechosos.** Configurable.
  *Legal*: validar la política y reflejarla en el texto de privacidad.
  *Plataforma*: cargar las variables en Render.
- **6.4 Retirar la bandera y documentar.** Cuando el golden set esté en verde
  en los dos últimos bloques y haya **una semana de producción sin más
  errores de lectura**, se retira el motor viejo y se documenta en CLAUDE.md
  e HISTORIAL.md.
  *Dev*: tomar la decisión de retirar la bandera con los datos de la semana.

---

## Qué necesita de las personas

Resumen de todos los `*Rol*` de arriba, por si alguien tiene que planificar
su tiempo.

| Rol | Lo que tiene que aportar |
|---|---|
| **Datos** | Los 60 recibos con consentimiento y **la anotación de la verdad de campo** (≈ una tarde cada 30). Alimentar el diccionario de abreviaturas. Revisar los recibos que cambian de estado. Conseguir las escalas salariales. Es el rol que bloquea el arranque. |
| **Producto** | Aprobar la línea de base. Validar el vocabulario de los prompts. Aprobar los textos de "lectura incierta" y de la pantalla de resultado. Validar el mapeo de severidades. **Aceptar el cambio de "más no verificable, menos diferencias"** y explicárselo a los sindicatos. Definir las fórmulas reales de cada convenio. Decidir si se activa la cascada. |
| **Sindicato** | Operar la cola de conceptos pendientes. Mantener la escala salarial en cada paritaria. Marcar cuál es su formulario de reclamo de aportes. |
| **Dev** | Integrar el enmascarado en su punto de enganche. Correr las migraciones (Docker primero, Render después). Verificar que las fórmulas reales de producción evalúen igual con el evaluador nuevo. Decidir cuándo retirar la bandera. |
| **Legal** | Validar la política de retención y el texto de privacidad. |
| **Plataforma** | Prender y apagar `MOTOR_V2` en Render. Mantener el catálogo maestro. Vigilar el costo de la capa de normalización. Cargar las variables de retención. |

---

## Evidencia de campo (agregado 2026-09-13)

*(Sección escrita al reconstruir este archivo. No estaba en el tablero: son
mediciones reales posteriores al plan, que confirman tres de sus premisas.)*

El banco de pruebas de modelos de `/plataforma` (solapa Uso de IA) permite
leer el MISMO recibo con varios modelos y comparar. Con un recibo real:

1. **El `max_tokens` de 2.000 era una bomba de tiempo — confirma 1.4.** Los
   modelos que funcionaron gastaron 1.790 y 1.744 tokens de salida: el que
   corre en producción pasaba al **89% del tope**. Dos modelos lo cruzaron y
   devolvieron un JSON cortado a la mitad, que llegaba como un
   `JSONDecodeError` críptico. Se subió a 8.000 y se agregó la detección de
   respuesta cortada; el resto de 1.4 (releer por partes) sigue pendiente.
2. **Una categoría universal mal leída pega justo donde duele — confirma la
   necesidad de 3b.** Un modelo etiquetó `38-001 APORTE PERSONAL
   I.N.S.S.J.Y P.` como `jubilacion` en vez de `pami`. `categoria_universal`
   es la red de seguridad de `validador.matchear`: **solo entra en juego
   cuando la línea no matcheó por código ni por descripción**, o sea
   exactamente en el escenario para el que existe. Con un empleador nuevo y
   el catálogo sin curar, el aporte de PAMI (≈3%) se validaría contra la
   fórmula de jubilación (≈11%): una diferencia inventada en la pantalla de
   alguien que no tiene ningún problema.
3. **Los totales pueden coincidir y la lectura ser distinta — confirma D2 y
   D3.** En ese mismo recibo, los cuatro modelos dieron período, CUIL, 17
   líneas, remuneraciones, descuentos y neto **idénticos**, y aun así
   clasificaron distinto tres renglones. Coincidir en el neto no es haber
   leído lo mismo.

También quedó medido, y sirve para 6.2: el costo por recibo de los cuatro
modelos comparados fue de US$ 0,0123 a US$ 0,0695 — un factor de 5,6 entre
el más barato y el más caro — con tiempos de 14,4 a 27,4 segundos. **El
modelo que corre hoy en producción es el más lento de los cuatro y el
segundo más caro.**

---

## Riesgos conocidos

1. **El bloque 0 es el que se saltea.** Es el único que no produce nada
   visible y el que más trabajo manual pide. Saltearlo deja al resto del
   plan sin forma de saber si mejora: la premisa 1 existe para eso.
2. **D6 se va a leer como una regresión.** Menos "diferencias" en el tablero
   de un sindicato parece peor aunque sea mejor. Hay que comunicarlo antes
   de desplegarlo, no después de la primera pregunta.
3. **El bloque 3 es grande y toca el modelo de datos.** Tres migraciones y
   un cambio en cómo se matchea cada renglón. Es el que más conviene medir
   contra la línea de base antes y después.
4. **El enmascarado (1.2) puede llegar tarde.** El plan reserva el lugar
   pero no lo resuelve. Mientras tanto, **la imagen completa del recibo,
   con nombre y CUIL, sigue saliendo hacia la API**. Es una decisión
   consciente, no un olvido, pero conviene que esté dicha en voz alta.
