# PLAN_XSII.md — XSII, Implementación inteligente

**Estado: BORRADOR para acordar con SDN** (2026-11-26). Las decisiones ya
tomadas están numeradas (X1…); las abiertas están al final y se cierran de a
una. Cuando quede acordado, este archivo no se edita más: lo que cambie va a
HISTORIAL.md.

Maquetas de las tres direcciones de pantalla:
https://claude.ai/artifact/JRQpQ1TxVoe3oFuBkRwNKu

## Qué es

**XSII** («XS Implementación Inteligente») es la tercera pieza de la Suite
XSanders, junto a XSK (seguridad) y XSD (diseño). Es un asistente que conoce
**todas** las tareas que hacen falta para dejar un sistema funcionando en un
cliente, sabe qué necesita cada una y de cuáles depende, dice en cualquier
momento cómo está la implementación y ayuda a hacer las tareas que conviene
automatizar.

El primer uso es Colm3na: llevar un sindicato ya creado en plataforma a una
**primera versión funcional** en días en vez de semanas. Primera versión no
es completa ni cubre los casos complejos.

## Decisiones tomadas

- **X1. Interactivo, no ciego.** No hay un proceso que cargue todo de una
  vez. Se ven todas las tareas desde el primer minuto y se avanza de a una.
- **X2. No todo es asistido.** Cada tarea tiene un modo: *asistida* (la IA
  prepara y carga), *con herramienta* o *por la aplicación* (se hace en una
  pantalla que ya existe; XSII lleva hasta ahí y controla el resultado) o
  *manual* (ocurre fuera del sistema). El asistente las conoce todas.
- **X3. Si una tarea se frena, se sabe con cuáles seguir.** Las dependencias
  son parte del catálogo; el asistente distingue lo que está bloqueado de lo
  que se puede hacer igual.
- **X4. Nivel 2.** En una tarea asistida el asistente explica en breve qué va
  a hacer, muestra datos y cantidades, ejecuta cuando el implementador
  confirma, informa el resultado y deja registro. Nunca escribe sin confirmar.
- **X5. El catálogo se arma desde el sistema, no desde el plan de
  implementación.** Los hitos de la Mesa son texto escrito a mano; si tienen
  un error, no se arrastra. Cada tarea del catálogo apunta a modelos, rutas y
  validaciones reales, y un test falla si deja de coincidir con el código.
- **X6. Lo más importante es el catálogo y sus dependencias; después, el
  asistente.** La pantalla es visual: muestra la tarea en curso y, siempre a
  la vista, el contexto (por hacer, esperando, bloqueadas).
- **X7. Es genérico.** Se construye para usarlo en otros sistemas: el motor
  no sabe nada de sindicatos.
- **X8. Tres vistas: Guía, Tablero y Mapa** (SDN, 2026-11-26, sobre la
  maqueta 2). La **Guía** es la pantalla principal y la única que conduce;
  **Tablero** (todas las tareas agrupadas, con filtros por estado) y **Mapa**
  (las dependencias) son para mirar. Desde cualquiera se abre una tarea y se
  vuelve a la Guía.
- **X9. Un botón grande de Play con el siguiente paso recomendado.** Es lo
  único que destaca en la Guía: nombre del paso, por qué ese y qué destraba.
  Debajo, pocas alternativas que también se pueden hacer. El paso lo elige
  el motor: la tarea en curso o, si no hay, la que más tareas destraba.
- **X10. El asistente no es un chat.** Habla adentro de la tarea: dice qué va
  a hacer, informa, avisa si algo salió mal y da opciones, y propone cómo
  seguir. No hay un cuadro de conversación aparte.
- **X11. «Preguntame» por punto.** Cada bloque que lo amerita (el paso
  recomendado, un ensayo, la ficha de una tarea en el mapa) tiene su botón,
  con preguntas sugeridas sobre ESE punto y lugar para escribir la propia.
- **X12. Poca información a la vez.** En la Guía, el contexto es un panorama
  angosto: el aviso de lo demorado y contadores que se despliegan. La lista
  completa vive en el Tablero.
- **X13. El Mapa ilumina un camino.** Al tocar una tarea se destaca de qué
  depende y qué destraba, y el resto se atenúa. Flechas en ángulo recto,
  como la norma de diagramas del Documento integrador.

## Principios de construcción (propuestos)

1. **El estado se calcula, no se declara.** «Padrón cargado» sale de contar
   en la base, no de un tilde. Por eso el asistente no puede equivocarse
   sobre el avance y el control de completitud es el mismo dato con el que
   contesta. Lo que no se puede calcular (una decisión, una reunión) se
   *confirma* y queda con quién y cuándo.
2. **La IA propone, el código decide** (misma regla que el Asistente de
   trámites). El modelo no escribe en la base: elige entre acciones
   registradas, cada una con ensayo y confirmación, que pasan por las mismas
   funciones y validaciones que usa el panel.
3. **Motor puro.** El grafo, los estados y la resolución no importan `db`:
   reciben hechos y devuelven el tablero. Se prueban solos.
4. **Privacidad.** El padrón nunca viaja entero a la IA: ve encabezados y
   pocas filas tapadas, propone el mapeo, y la transformación la hace el
   servidor. Los recibos pasan por el enmascarado de siempre.
5. **Todo queda registrado**: cada ensayo, cada carga, cada confirmación y
   cada excepción, con quién, cuándo y cantidades.

## Arquitectura

Mismo reparto que XSK: lo genérico separado de lo de este sistema.

```
xsii/
  motor/            genérico, puro
    catalogo.py     qué es una tarea, validación del catálogo (sin ciclos,
                    dependencias que existen, toda tarea con control)
    estados.py      resolución: de hechos a estado de cada tarea
    consulta.py     «qué puedo hacer ahora», «qué frena a X», «qué destraba X»,
                    «qué falta para llegar a Y» (camino mínimo)
  proyectos/colm3na/
    catalogo.py     las tareas de Colm3na (declarativas)
    controles.py    una función por control; recibe la sesión y el sindicato
    acciones.py     las ayudas asistidas: preparar → ensayo → aplicar
  METODO.md         el método, para llevarlo a otro sistema
```

En la app: tablas `Xsii*` (registro y decisiones; el estado no se guarda),
rutas `/api/entornos/xsii/*` y la pantalla en `/entornos` → Implementación,
junto a la Mesa, con la misma puerta (404 en demo). Se abre **por proyecto
de la Mesa** (`ImplProyecto.sindicato_id` ya vincula proyecto y sindicato).

### Qué declara una tarea

| Campo | Para qué |
|---|---|
| código y nombre | nombrarla (`PAD-02`), como los códigos de la Mesa |
| grupo | Base, Estructura, Recibos, Padrón, Trámites, Comunicación, Cierre |
| modo | asistida / con herramienta / por la aplicación / manual |
| necesita (dura) | tareas sin las cuales no se puede hacer |
| mejora con (blanda) | tareas que conviene tener, pero no frenan: avisa y sigue |
| insumos | datos que entrega el sindicato; se enlazan a su tarjeta de la Mesa |
| aplica si | módulo contratado u otra condición; si no, «no aplica» |
| dónde se hace | enlace directo a la pantalla o herramienta |
| control | función que devuelve: completa / con observaciones / incompleta, con cifras y la lista de lo que falta |
| acciones | solo en las asistidas: qué puede preparar y cargar el asistente |
| mínimo de la primera versión | sí / no: separa lo que hace falta para «funcional» de lo que es completar |

### Estados (calculados en este orden)

1. **No aplica**: la condición no se cumple (módulo apagado) o se declaró con
   motivo.
2. **Hecha**: el control pasa. **Con observaciones**: pasa con avisos (por
   ejemplo, dos seccionales sin ubicar).
3. **Bloqueada**: falta una dependencia dura. Se dice cuál.
4. **Esperando un dato**: falta un insumo. Se muestra la tarjeta de la Mesa
   y hace cuántos días se pidió.
5. **En curso**: hay un ensayo abierto o el control pasa a medias.
6. **Se puede hacer**: nada la frena.

Tres clases de control: **calculado** (consulta a la base), **confirmado**
(lo afirma una persona; queda registrado) y **mixto** (cifra calculada más
una confirmación: «cargados 3.812 de 3.840 que declaró el sindicato;
rechazos revisados»).

Lo flexible: posponer una tarea, declararla «no aplica» con motivo, o darla
por buena con observaciones. Lo sólido: nada de eso cambia lo que el control
calcula; la pantalla muestra las dos cosas.

## Catálogo v0 de Colm3na (relevado del código)

«Hoy» dice qué existe ya para hacerla. **Negrita** = hace falta desarrollo.

### Base
| Código | Tarea | Modo | Necesita | Control | Hoy |
|---|---|---|---|---|---|
| BAS-01 | Ficha del sindicato | aplicación | — | existe, con nombre y CUIT válido | `/plataforma` |
| BAS-02 | Marca: logo, colores, prueba de lectura | aplicación | BAS-01 | logo cargado; prueba de lectura sin avisos (observación) | `/plataforma`, `temas.prueba_de_lectura` |
| BAS-03 | Módulos contratados | aplicación | BAS-01 | confirmado | ficha del sindicato |
| BAS-04 | Primer administrador con clave propia | aplicación | BAS-01 | al menos un Super Admin activo que ya cambió la clave inicial | `/plataforma/usuario` |
| BAS-05 | Política de registro y canal de mail | aplicación | BAS-01 | confirmado; canal de mail prendido (observación) | ficha del sindicato |
| BAS-06 | Cláusula de confidencialidad y contrato | manual | BAS-01 | contrato cargado y cláusula marcada | ficha del sindicato |

### Estructura
| Código | Tarea | Modo | Necesita | Control | Hoy |
|---|---|---|---|---|---|
| EST-01 | Seccionales | asistida | BAS-01; insumo: lista con domicilios | al menos una; lista confirmada contra la del sindicato | alta de a una. **Carga desde planilla** |
| EST-02 | Seccionales ubicadas en el mapa | asistida | EST-01 | ninguna «sin ubicar» | geocodificación en lote, existe |
| EST-03 | Áreas con permisos | asistida | EST-01, BAS-03 | cada área activa con al menos un permiso | alta de a una. **Plantilla de áreas** |
| EST-04 | Usuarios del panel | asistida | EST-03 | cada área que recibe trámites con un usuario activo; claves iniciales cambiadas (observación) | alta de a una. **Carga desde planilla** |

### Recibos
| Código | Tarea | Modo | Necesita | Control | Hoy |
|---|---|---|---|---|---|
| REC-01 | Recibos de muestra | manual | insumo: 30 a 60 recibos de varios empleadores | cantidad y variedad recibidas | Mesa |
| REC-02 | Aportes de ley | automática | BAS-01 | los tres conceptos y sus reglas presentes | se crean al dar de alta el sindicato |
| REC-03 | Cuota sindical y aporte solidario | asistida | BAS-01; insumo: porcentajes | un concepto de afiliación con su regla | a mano, en Conceptos y Reglas |
| REC-04 | Catálogo de conceptos | asistida | REC-01 | ningún concepto pendiente de revisión | Aprendizaje (lee varios recibos y propone) |
| REC-05 | Reglas de control | asistida | REC-04, REC-03 | toda regla evalúa; tolerancia dentro del aviso; sin vigencias superpuestas | a mano, una por una. **Propuesta de reglas** |
| REC-06 | Topes vigentes para la muestra | aplicación | — | hay tope para cada período de los recibos de muestra | `/plataforma`, global |
| REC-07 | Recibos de control | asistida | REC-05, REC-06 | N recibos de muestra validados y revisados a mano | **No existe** (ver diferencia 1) |
| REC-08 | Escala salarial y convenio | herramienta | BAS-03 | convenio asignado y grilla publicada | solo CCT 18/75; otro convenio es desarrollo |

### Padrón
| Código | Tarea | Modo | Necesita | Control | Hoy |
|---|---|---|---|---|---|
| PAD-01 | Padrón recibido | manual | insumo: planilla | recibido, con total declarado | Mesa |
| PAD-02 | Padrón cargado | asistida | EST-01, PAD-01 | cargados contra el total declarado; rechazos revisados | alta masiva con ensayo. **Mapeo de columnas** |
| PAD-03 | Domicilios ubicados | asistida | PAD-02 | pendientes de ubicar (observación, no frena) | georreferenciar pendientes, existe |
| PAD-04 | Empleadores | asistida | BAS-03; mejora con REC-04 | al menos uno; CUIT de los conceptos importados | importar CUIT de conceptos. **Carga desde planilla** |
| PAD-05 | Listas del sindicato | aplicación | EST-01 | las listas que nombran los formularios están cargadas | CSV con ensayo, existe |

### Trámites
| Código | Tarea | Modo | Necesita | Control | Hoy |
|---|---|---|---|---|---|
| TRA-01 | Formularios de trámite | herramienta | EST-03; mejora con PAD-05 | al menos N publicados, con destino y campos; borradores (observación) | Asistente de trámites + constructor |
| TRA-02 | Trámite de prueba | manual guiada | TRA-01, PAD-02, EST-04 | un trámite iniciado, respondido y cerrado | las apps |

### Comunicación
| Código | Tarea | Modo | Necesita | Control | Hoy |
|---|---|---|---|---|---|
| COM-01 | Apariencia: modelo, paleta, foto | aplicación | BAS-02 | confirmado | `/admin` → Apariencia |
| COM-02 | Noticias iniciales | aplicación | — | al menos una vigente | `/admin` → Noticias |
| COM-03 | Beneficios | aplicación | — | al menos uno vigente | `/admin` → Beneficios |
| COM-04 | Notificación de bienvenida | aplicación | PAD-02 | una enviada | `/admin` → Notificaciones |
| COM-05 | Convenio para consultas | aplicación | BAS-03 | un documento vigente e indexado | `/admin` → Convenio |
| COM-06 | Encuestas | aplicación | PAD-02 | no aplica por defecto | `/admin` → Encuestas |

### Cierre
| Código | Tarea | Modo | Necesita | Control | Hoy |
|---|---|---|---|---|---|
| CIE-01 | Afiliado de prueba con recibo propio | manual guiada | PAD-02, REC-05 | una cuenta registrada que leyó y validó un recibo | la app |
| CIE-02 | Recorrido por rol | asistida | CIE-01, TRA-02, EST-04 | el robot entra con cada rol y completa su recorrido | **Robot por sindicato** (hay base en `e2e/`) |
| CIE-03 | Aceptación del sindicato | manual | CIE-02 | tarjeta de Aprobación resuelta | Mesa |

**Mínimo de la primera versión** (propuesto): Base completa, EST-01, EST-03,
EST-04, REC-01 a REC-07, PAD-01, PAD-02, TRA-01 con dos formularios, COM-01,
COM-02 y Cierre. El resto se completa después y el tablero lo muestra aparte.

## Diferencias entre el plan de implementación y el sistema

Encontradas al relevar el código. Son las que el catálogo corrige y las que
conviene llevar también a los hitos de la Mesa.

1. **Los recibos de muestra no se pueden validar como pide el plan.** El hito
   dice «20 recibos reales de 4 bancos con resultado correcto». Leer y
   validar un recibo exige la sesión de un afiliado y que el CUIL del recibo
   sea el suyo: un recibo de otra persona se corta al leerlo. Con recibos de
   terceros hoy solo se puede usar Aprendizaje (propone conceptos, no
   valida). Hace falta una puerta de control para el equipo: validar un lote
   de muestra contra el catálogo y las reglas, sin identidad.
2. **La cuota sindical no nace con el sindicato.** El alta crea los tres
   aportes de ley, pero no la cuota (el porcentaje varía). Sin un concepto de
   afiliación con su regla, cada recibo avisa «cuota faltante». El plan no lo
   nombra como paso.
3. **«Seccionales cargadas desde el archivo» no existe.** Hoy se cargan de a
   una. Con las 53 de La Bancaria, es una ayuda que conviene construir.
4. **El padrón depende de las seccionales, y el plan no lo dice.** La carga
   masiva busca la seccional por nombre; si no existe, la persona queda sin
   seccional y sin aviso fuerte. Las seccionales van antes, con los nombres
   acordados.
5. **La planilla del padrón tiene un formato fijo que no trae el empleador.**
   Trece columnas en orden; el CUIT del empleador no es una de ellas. A
   verificar además a cuál de los tres mails va la columna de mail (el del
   padrón es el que habilita el registro confirmado).
6. **Trámites, notificaciones, empleadores y Panel Sindical nacen apagados.**
   No están entre los módulos iniciales. Un sindicato recién creado no los
   tiene hasta que plataforma los prende; el hito dice solo «módulos».
7. **Un formulario no se publica sin área de destino.** Las áreas son
   dependencia dura de Trámites, y los usuarios de las áreas lo son del
   trámite de prueba. En el plan figuran en la misma fase, sin orden.
8. **Las escalas son por convenio, no por sindicato.** Solo existe el CCT
   18/75 y se actualiza solo. Para otro sindicato, «escalas con vigencia
   cargadas» es un desarrollo, no una configuración.
9. **Los topes son de plataforma.** No se cargan por sindicato; lo que hay
   que controlar es que exista tope vigente para los períodos de los recibos
   de muestra (los anteriores a 2025 siguen «por verificar»).
10. **Los hitos se tildan a mano.** Nada los vincula con lo cargado. XSII
    puede calcular los de la fase Configurar y proponerlos como hechos.

Lo anterior salió de un relevamiento del código por un agente; antes de
escribir cada control se confirma contra la función real y queda un test.

## El asistente

**Protocolo de una tarea asistida** (los cuatro momentos de la maqueta):

1. **Qué voy a hacer**: dos líneas, con qué insumo y qué va a tocar.
2. **Ensayo**: cantidades (leídos, válidos, rechazados y por qué), una
   muestra de filas y lo dudoso separado. Nada se guardó.
3. **Carga**: al confirmar, por las funciones del panel, en una transacción.
   Lo dudoso se puede dejar afuera y resolver después.
4. **Control**: corre el control de la tarea, muestra el resultado y dice qué
   se destrabó.

**Preguntame (X10, X11).** No hay conversación libre: cada «Preguntame» abre
una consulta acotada a su punto. El modelo tiene herramientas de lectura (tablero, ficha de
una tarea, qué frena, qué destraba, camino hasta una meta, registro) y las
acciones registradas de la tarea abierta. Toda cifra que dice sale de una
herramienta, nunca de su memoria. Preguntas tipo: «¿cómo estamos?», «¿qué
puedo hacer ahora?», «¿qué falta para probar un recibo?», «reclamá el padrón»
(crea la tarjeta en la Mesa, con confirmación).

**Uso de IA**: sexto uso (`xsii`), elegible en `/plataforma`, registrado en
`UsoIA`. Sin clave de API, el tablero y los controles funcionan igual.

## Ayudas asistidas a desarrollar (por valor)

1. **Recibos de control** (REC-07): validar el lote de muestra sin identidad
   y mostrar cuáles cierran. Es además el banco de prueba de las reglas.
2. **Propuesta de reglas** (REC-05, REC-03): desde una plantilla de reglas
   tipo más el convenio, probadas contra el lote de muestra.
3. **Mapeo del padrón** (PAD-02): de la planilla como venga al formato de la
   carga masiva, con informe de rechazos.
4. **Catálogo de conceptos en lote** (REC-04): Aprendizaje sobre toda la
   muestra, con lo claro y lo dudoso separados.
5. **Estructura desde planilla** (EST-01, EST-03, EST-04): seccionales, áreas
   tipo y usuarios.
6. **Empleadores desde planilla** (PAD-04).
7. **Robot de recorrido por sindicato** (CIE-02).

## Bloques

0. **Catálogo y motor**: `xsii/motor` puro con sus tests; catálogo de Colm3na
   y un control por tarea, cada uno confirmado contra el código. Sin
   pantalla: sale un informe por consola para un sindicato. Es el bloque que
   más vale y no necesita IA.
1. **Tablero**: la pantalla elegida, solo lectura, con enlaces a cada
   pantalla y a la Mesa; confirmaciones y excepciones; registro.
2. **Asistente de lectura**: la conversación con las herramientas de estado.
3. **Primera tarea asistida de punta a punta** (propuesta: padrón), para
   fijar el protocolo de cuatro momentos.
4. **Resto de las ayudas**, en el orden de arriba.
5. **Vuelta a la Mesa**: insumos enlazados a tarjetas, hitos propuestos.
6. **Método**: `xsii/METODO.md` y la extracción a repo propio cuando madure.

Cada bloque con desarrollo y QA independiente por agentes, como los
anteriores.

## Abiertas (se cierran de a una)

1. ~~Dirección de la pantalla~~: cerrada, X8 a X13.
2. Mínimo de la primera versión: confirmar o corregir la lista propuesta.
3. Qué puede dar por buena una persona contra el control (excepciones).
4. Entorno: Pruebas, como la Mesa, o también donde corra el piloto.
5. Quién lo usa: solo el equipo, o también el sindicato en modo lectura.
6. Primera tarea asistida a construir.
