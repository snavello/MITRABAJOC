# XSII, Implementación inteligente — El método

Este archivo es **genérico**: no menciona ningún producto en particular, salvo en la última sección, que dice dónde
está la primera aplicación. Es lo que se extrae cuando XSII pasa a repositorio propio. Lo específico de cada
producto vive en `proyectos/<nombre>/`. El plan acordado está en `PLAN_XSII.md` y el contrato de cada bloque, con
las correcciones de su QA, en `docs/xsii/API.md`.

## Qué es

XSII es un asistente que guía la **primera implementación** de un producto en un cliente. Conoce todas las tareas
que hacen falta para dejarlo funcionando, sabe qué necesita cada una y de cuáles depende, calcula su estado mirando
los datos reales, dice cuál conviene hacer ahora y por qué, qué frena y qué destraba, y en algunas tareas hace el
trabajo con la persona del equipo de implementación: muestra qué va a hacer, lo ensaya sin guardar nada, carga
cuando ella confirma y controla el resultado. La persona decide; el asistente ordena, controla y se acuerda de todo.

Qué **no** es:

- **No es un gestor de tareas que se tilda.** Nadie marca «hecha»: el estado sale de consultar el sistema. Lo que no
  se puede consultar se confirma con nombre y fecha.
- **No es un chat.** Cada consulta es una pregunta sobre un punto, sin historial.
- **No escribe solo.** Todo lo que cambia datos tiene ensayo y confirmación de una persona, y pasa por las mismas
  funciones que usa el producto.
- **No reemplaza a la herramienta de trabajo con el cliente.** Se apoya en ella (pedir datos, recibir archivos,
  marcar hitos) y no la duplica.

## Principios

1. **El estado se calcula, no se declara.** «Está cargado» sale de contar en la base. El motor no guarda el estado:
   lo recalcula en cada pedido desde los controles, las condiciones, los insumos y las decisiones.
2. **El catálogo sale del sistema, no del plan escrito a mano.** Cada tarea apunta a módulos, pantallas y funciones
   que existen, y un test falla si dejan de coincidir con el código.
3. **Lo que no se puede calcular se confirma, con nombre.** Una decisión o una aprobación se afirma con quién y
   cuándo; la tarea no queda hecha sin ella.
4. **Se puede salir del método, y queda a la vista.** Completar a mano, declarar «no aplica» o posponer deja motivo
   y autor, y nunca cambia lo que el control calcula: la pantalla muestra las dos cosas.
5. **La IA propone, el código decide.** El modelo lee por herramientas y a lo sumo propone; lo que se escribe pasa
   por una ruta con ensayo y confirmación.
6. **El ensayo y la carga son el mismo código.** Una función pura parsea una sola vez y la carga exige la huella del
   ensayo: se escribe exactamente lo que se vio.
7. **Una sola implementación de cada regla, compartida con el producto.** Si el producto ya tiene una carga masiva,
   la asistida llama a esa misma lógica (extraída a una función común), no a una copia que pueda diferir.
8. **Todo queda registrado y nada se borra.** Cada decisión, insumo, carga y excepción deja un movimiento inmutable
   con quién, cuándo y cantidades. Deshacer desactiva; no borra.
9. **Datos personales, ni al modelo ni a los registros.** Las herramientas del asistente devuelven solo lo que ya
   muestra el tablero; los movimientos llevan cantidades, nunca contenido.
10. **Lo que no pasa la validación sale como texto fijo.** Si la respuesta del modelo no cumple las reglas, la
    persona recibe un texto del servidor.
11. **Si falta la IA, todo lo demás anda.** Sin clave de la API solo se apagan las consultas y la lectura de
    documentos.
12. **Genérico adentro, concreto afuera.** El motor no sabe de qué producto es el catálogo: es puro, usa solo la
    biblioteca estándar y un test lo vigila.

## Las piezas

### El catálogo de tareas

Una lista de tareas declarativas (`xsii/motor/catalogo.py`). Cada una lleva: código y nombre; **grupo**; **modo**
(asistida, herramienta, aplicación, manual o automática: ver abajo); **dependencias duras** (`necesita`, sin ellas
no se puede hacer) y **blandas** (`mejora_con`, avisan y no frenan); **insumos** que entrega el cliente; `aplica_si`
(clave de una condición que informa el proyecto, por ejemplo un módulo contratado); `donde` (la pantalla); `control`
(nombre de la función que dice si está hecha); `confirmacion` y `solo_confirmacion`; `para_que` (una oración) y
`pasos` (de 2 a 5 instrucciones en imperativo). Los modos: en una **asistida** la IA prepara y carga con ensayo; en
**herramienta** y **aplicación** se hace en una pantalla que ya existe y XSII lleva hasta ahí y controla; **manual**
ocurre fuera del sistema; **automática** la hace el sistema solo.

El motor valida el catálogo: códigos únicos, modo y grupo válidos, toda tarea con control, dependencias que existen,
y **sin ciclos** (los de duras y de blandas por separado). Un catálogo inválido no arranca. El campo `acciones`
existe y ninguna aplicación lo usa hoy.

Genérico: la forma de la tarea y la validación. Del producto: las tareas, sus grupos, pasos e insumos con su texto
para la persona (nombre, tipo archivo o dato, formato esperado).

### Los controles

Un control por tarea: una función del producto con el nombre que dice `control`. Recibe una sesión de base ya
abierta y el identificador del cliente, y devuelve un `Control` (`xsii/motor/estados.py`): `completa`,
`observaciones` (pasa con avisos) o `incompleta`, un resumen, cifras con nombre, lo que falta y si hay avance
parcial.

Un control **nunca escribe**, nunca falla por datos raros (si no puede saber, dice que falta algo), usa consultas
agregadas sin columnas pesadas y filtra siempre por el cliente. Hay tres clases: **calculado** (cuenta en la base),
**confirmado** (calcula lo que puede y la tarea declara qué hay que confirmar) y **mixto**. Si un control lanza una
excepción, el tablero no se cae: esa tarea queda incompleta con el motivo.

### Estados y marcas

`resolver` toma los hechos y devuelve el estado de cada tarea, con esta precedencia: **no aplica** (la condición no
se cumple o se declaró con motivo), **hecha** (el control pasa, el insumo está o ya hay datos cargados, y la
confirmación, si la hay; o completada a mano), **bloqueada** (falta una dependencia dura, y dice cuál), **esperando
un dato**, **en curso** (avance parcial o falta confirmar) y **se puede hacer**. «Hecha» se calcula de la realidad
aunque una dependencia no lo esté. Una condición que el proyecto no informa es un error, no un «no aplica»
silencioso.

Las decisiones son cuatro: confirmada, completada a mano, no aplica y pospuesta; como mucho una activa por tipo.
Posponer es una marca que no cambia el estado y saca la tarea de las recomendaciones. Completar a mano y «no aplica»
exigen motivo (de 5 a 500 caracteres sin contar espacios ni invisibles) y se excluyen entre sí. Completada a mano
cuenta como hecha y destraba a las que dependen, pero queda marcada; como cualquiera del equipo puede hacerlo, el
tablero las lista con quién y por qué. Un insumo sin registrar no deja «esperando» a una tarea cuyo control ya
muestra datos: la pantalla avisa que hay datos y el insumo no figura.

La barra de avance cuenta todas las tareas que aplican, no un «mínimo», y redondea hacia abajo: 100 % tiene que
querer decir que no queda nada. El motor admite ensayos abiertos para marcar tareas en curso; la primera aplicación
no lo alimenta, porque su ensayo no guarda nada.

### El paso recomendado y las consultas del grafo

`xsii/motor/consulta.py` responde, con solo las dependencias duras: qué destraba una tarea (directo y transitivo,
sin pasar por lo ya resuelto), qué la frena, el camino hasta una meta en orden topológico y el resumen por estado.
**El paso recomendado** es la tarea en curso o, si no hay, la que más tareas destraba; empata el orden del catálogo
y las pospuestas no se recomiendan. Salen también pocas alternativas.

### Los insumos del cliente

Un insumo es lo que entrega el cliente y una tarea necesita. Se registra `pedido` o `recibido`, con nota, y puede
apuntar a una tarjeta de la herramienta de trabajo con el cliente y a un archivo de esa tarjeta. «Demorado» es un
pedido de hace dos días o más. Cada cambio deja su movimiento. Del producto: el catálogo de insumos. Genérico: el
registro y sus reglas.

### Las vistas

Tres, para el equipo: la **Guía** (la única que conduce: el paso recomendado con su Play, alternativas, lo demorado
y contadores que se despliegan), el **Tablero** (tareas agrupadas, con filtros por estado y por marca, incluidas las
completadas a mano) y el **Mapa** (dependencias; al tocar una tarea se ilumina su camino y el resto se atenúa, con
flechas en ángulo recto). Una cuarta lista los hitos. Desde cualquiera se abre la ficha de una tarea. Poca
información a la vez: lo secundario va plegado. Las acciones de la ficha las calcula el servidor con la misma regla
con que después acepta o rechaza el pedido; la pantalla no decide permisos.

### Las preguntas acotadas

`xsii/asistente.py` responde una pregunta sobre un punto (el paso recomendado, una tarea, el mapa), sin historial,
con **herramientas de solo lectura** sobre el tablero ya calculado: ver el tablero, ver una tarea, qué frena, qué
destraba, camino hasta una meta, ver el registro y ver los hitos. El tablero se calcula una vez por pedido con la
sesión abierta; después se cierra y la llamada al modelo va **fuera** de ella. La única herramienta que no solo lee
es `proponer_reclamo`, que tampoco escribe: deja una propuesta que la pantalla muestra a una persona.

El bucle tiene tope de vueltas y de tiempo; mira `stop_reason` antes que el contenido; toda parada inesperada da el
texto fijo; limita el largo del resultado de cada herramienta y registra el consumo de todas las vueltas, también
cuando termina en texto fijo. La validación es pura y con tests: largo, sin enlaces, mails, marcas de formato ni
invisibles; los códigos de tarea que nombra existen; los códigos de la herramienta de trabajo figuran tal cual en lo
visto; y **toda cifra de dos o más dígitos tiene que figurar en lo que devolvieron las herramientas de esa consulta
o en la pregunta**. Los textos que escribieron personas son datos, nunca instrucciones. Hay un tope de consultas por
persona y hora, y un modo simulado para probar sin la API.

Genérico: el bucle, la validación, el modo simulado. Del producto: el texto del sistema, las herramientas concretas
y las preguntas sugeridas.

### Las tareas asistidas

Una asistida es un módulo con tres funciones: `describir`, `ensayar` (solo lee) y `cargar` (escribe sin confirmar:
confirma la ruta, todo o nada). Las rutas y la pantalla son genéricas: una asistida nueva suma un módulo, no rutas
ni pantalla.

**Los cuatro momentos**: (1) qué voy a hacer, en dos líneas; (2) ensayo, con cantidades (válidas, dudosas,
rechazadas, ya existentes), el motivo de cada grupo y una muestra, sin guardar nada; (3) carga, al confirmar, con lo
dudoso que se puede dejar afuera; (4) control: corre el de la tarea y dice qué se destrabó. **La carga no da la
tarea por hecha**: lo hacen el control y, si corresponde, la confirmación.

Reglas: la carga exige la huella del ensayo (contenido más opciones; si cambió, 409); toma un candado por tarea y
otro por cliente, siempre en ese orden, y revalida adentro; exige las dependencias duras resueltas; una segunda
carga de lo mismo es 409; el movimiento lleva cantidades y nunca contenido.

Hay dos entradas. **Planilla**: CSV subido o pegado, con topes de filas y bytes por módulo, rechazo por firma de lo
que no es una planilla, **reconocimiento de columnas** por sinónimos (la persona corrige el mapeo y vuelve a
ensayar), opciones booleanas y numéricas dentro de la huella y resultados grandes resumidos por motivo.
**Documentos**: la IA lee uno por pedido y propone; la persona revisa, corrige o descarta cada ítem, y recién ahí se
cargan, ya revisados, por un JSON validado todo o nada con errores por ítem. Genérico: el protocolo, la huella, el
mapeo. Del producto: cada módulo con sus columnas, clasificación y escritura.

### El vínculo con la herramienta de trabajo con el cliente

XSII no pide datos por su cuenta: usa la herramienta donde el cliente ya colabora.

- **Pedir un dato.** Un insumo faltante se **reclama**: el servidor arma un borrador (o el asistente lo propone), la
  persona lo edita y confirma, y se crea una tarjeta o se responde en la ya abierta, en una sola transacción.
- **Usar lo que el cliente entregó.** La ficha lista los archivos de la tarjeta del insumo; la persona fija uno y la
  asistida lo lee directamente. Cada uso queda registrado como descarga de esa persona, y cambiar la tarjeta suelta
  el archivo fijado.
- **Proponer hitos.** Los hitos son texto libre; el vínculo con las tareas se guarda aparte. Un hito se **propone**
  como cumplido cuando todas sus tareas asociadas que aplican están hechas (y hay al menos una); alguien del equipo
  lo acepta y lo marca a su nombre, con revalidación adentro de la transacción. XSII nunca marca un hito solo: una
  persona responde por él ante el cliente.

## Cómo aplicarlo a un producto nuevo

1. **Relevá las tareas reales desde el sistema.** Recorré código y pantallas: qué hay que cargar o configurar para
   que funcione en un cliente y en qué orden lo exige el sistema (una pantalla que rechaza algo si falta otra cosa
   marca una dependencia dura). Los módulos opcionales llevan `aplica_si`. Contrastá con el plan escrito a mano y
   anotá las diferencias: son las que el catálogo corrige.
2. **Escribí el catálogo.** Una tarea por cosa que se controla, con grupo, modo, dependencias, insumos, `para_que` y
   `pasos` verificados contra los rótulos reales. Tests: el catálogo valida, todo `aplica_si` es una condición que
   el producto informa, todo `donde` es una ruta que existe, toda tarea tiene su control, todo insumo está en el
   catálogo de insumos.
3. **Un control por tarea.** Siempre por cliente, agregados, sin escribir. Probalo con un cliente recién creado (el
   tablero tiene que ser coherente) y con datos de otro cliente (no deben cambiarlo).
4. **Decidí qué se calcula y qué se confirma.** Si hay un dato que lo prueba, se calcula; si es una decisión, una
   reunión o una aprobación, es `confirmacion`; una cifra más una aprobación, mixto.
5. **Elegí las primeras asistidas** por valor: lo que hoy se hace de a una y conviene cargar en lote, empezando por
   la de menos riesgo, que fija el protocolo. Antes de escribirla, extraé a una función compartida la lógica que el
   producto ya tiene.
6. **Definí tablas y puertas.** Tres tablas de registro (decisiones, insumos, movimientos) y una de vínculos de
   hitos, sin claves foráneas hacia el resto, con índice único parcial por lo activo y fuera de todo clonado o
   borrado del cliente. Una puerta del equipo distinta de la del cliente; el identificador del cliente sale del
   proyecto, nunca de un parámetro.
7. **Construí en este orden**, un bloque por vez:
   - **Bloque 0, catálogo y motor:** motor puro con tests, catálogo y un control por tarea, con informe por consola.
     Es el que más vale y no necesita IA.
   - **Bloque 1, tablero:** las tres vistas, el registro, las decisiones y los insumos.
   - **Bloque 2, preguntas acotadas:** herramientas de lectura, uso de IA propio y reclamo de un dato.
   - **Bloque 3, la primera asistida:** fija el protocolo de los cuatro momentos.
   - **Bloque 4, el resto de las asistidas:** planilla con mapeo y documentos leídos por IA, sin tocar rutas ni
     pantalla.
   - **Bloque 5, la vuelta a la herramienta de trabajo:** insumos con tarjetas y archivos, hitos propuestos. Un
     tutorial con capturas reales crece con cada bloque.

## Cómo se construye cada bloque

1. **El contrato, escrito primero**: rutas, formas, reglas y qué no entra. Lo que no esté escrito no existe. El plan
   acordado no se edita: lo que cambia va al historial.
2. **Servidor y pantalla en paralelo**, contra el mismo contrato; si quedó corto, va una nota.
3. **QA independiente de cada uno**, por quien no lo escribió: el servidor se ataca por HTTP con entradas hostiles y
   concurrencia; la pantalla se maneja en un navegador real contra el servidor real. Cada hallazgo se clasifica por
   origen (la app, los datos de prueba o la configuración) antes de tocar código y se corrige antes del merge.
4. **Tutorial con capturas reales** y resultados simulados, con errores y una tarea completada a mano.
5. **Cierre**: contrato con sus notas, historial y estado del proyecto.

Las decisiones de diseño se consultan a la persona **de a una**, con opciones cerradas, marcando cuál se recomienda
y por qué en una línea; con la respuesta se pasa a la siguiente y cada una queda numerada en el plan. Lo que se
decide solo al construir se anota como «a confirmar».

## Lecciones del QA

Defectos que se repitieron bloque tras bloque, y la regla que evita cada uno (de las correcciones de QA de
`docs/xsii/API.md`).

- **Carreras entre dos pedidos.** Dos cargas que creaban lo mismo, dos reclamos con el mismo número, un hito marcado
  a la vez: 500 al confirmar. Regla: candado por tarea y por cliente (y uno global si otra puerta hace la misma
  carga), siempre en el mismo orden, con revalidación adentro; el segundo recibe 409, nunca 500, y la fila bloqueada
  se relee.
- **Lo que devuelve la IA tomado como confiable.** Una lista donde iba un documento, líneas en `None`, textos
  enormes que colgaban una comparación cuadrática. Regla: acotar la salida del modelo antes de usarla (tipos,
  cantidad, largo) y correr lo costoso aparte.
- **Entradas hostiles que daban 500.** Campos con el tipo equivocado, bytes nulos, separadores Unicode, invisibles,
  un PDF usado como planilla. Regla: validar el tipo de todo cuerpo, limpiar los textos y rechazar un archivo por
  firma y extensión antes de leerlo; siempre 400 con una frase.
- **Datos de planilla dibujados sin escape.** Un mail con una etiqueta llegaba al HTML de otra pantalla. Regla:
  cuando una puerta nueva mete datos a una tabla, se revisan todas las pantallas que la muestran, y todo texto de
  una persona se dibuja como texto.
- **El dato de otro proyecto o de otra tarjeta.** Heredar el archivo fijado de la tarjeta anterior, aceptar uno de
  otra tarjeta. Regla: todo identificador se verifica contra el proyecto y la tarjeta del insumo, y uno ajeno da
  404.
- **Una validación con huecos.** Cifras de muchos dígitos, miles validados por pedazos, dominios poco comunes,
  códigos de la herramienta inventados, guiones Unicode. Regla: validar sobre texto normalizado y exigir los códigos
  tal cual en lo visto; lo que no se controla (cifras en letras, de un dígito) se declara como límite.
- **El archivo simulado que no deja probar la pantalla.** El documento de ejemplo traía un identificador inválido y
  toda propuesta salía rechazada. Regla: el modo simulado recorre el camino feliz y los de error de verdad.
- **Dos puertas a la misma lógica que se desvían.** Al extraer la lógica de una pantalla cambió en detalles, y un
  campo nuevo aceptó valores inventados. Regla: probar la extracción contra la lógica anterior congelada, con datos
  al azar, y validar todo campo nuevo contra un catálogo cerrado.
- **Textos con jerga.** «Enlazar», códigos internos, el nombre de una herramienta interna en lo que ve el cliente.
  Regla: los textos para personas los revisa quien no escribió el código y el vocabulario se fija en el contrato.

## Límites conocidos y qué falta para extraerlo

Límites del método tal como está construido:

- Las cifras en letras y las de un dígito no se controlan en las respuestas del modelo, ni una dirección ofuscada
  con espacios. La defensa es el texto del sistema y que la persona ve de dónde sale cada dato.
- El respaldo ante rechazos del servidor de la API no está activado (en el SDK usado solo existe por un camino beta
  que no se pudo probar): un rechazo da el texto fijo.
- Una sugerencia de hito a veces cubre solo parte de lo que dice su texto, y quien acepta responde por el resto.
  Reclamar desde un proyecto sin cliente asociado lo admite el servidor y no lo ofrece la pantalla. La primera
  consulta con la API real hay que mirarla en el entorno donde corre.

Para llevarlo a un repositorio propio, mirando los `import` reales:

- **Listo hoy:** `xsii/motor/` (solo biblioteca estándar) y `xsii/asistente.py` (más el SDK de la API, cargado de
  forma perezosa). Un test vigila cada uno.
- **Genérico por contenido, pero acoplado:** la base de las asistidas (lectura del CSV, huella, mapeo de columnas)
  usa tres funciones privadas del módulo de listas del producto (decodificar, detectar el separador, normalizar
  cabeceras): hay que traerlas. Las reglas de decisiones y las acciones de la ficha están escritas sobre el contexto
  del producto, y el informe por consola importa su base y su catálogo.
- **Mezclado con el producto:** las tablas de registro, sus funciones y las rutas viven en los módulos centrales de
  la aplicación; el contexto de un pedido lee la base y la herramienta de trabajo directamente; los hitos leen su
  archivo de la carpeta de datos; la pantalla usa el diseño del producto y su script nombra al producto en unas
  pocas cadenas.
- **Qué hay que hacer:** (1) mover el registro a un módulo que reciba la sesión y una identidad de actor, con su
  migración; (2) llevar las reglas de decisión al motor sobre un contexto mínimo; (3) definir como interfaz lo que
  se usa de la herramienta de trabajo (crear o responder tarjeta, listar y bajar archivos, tildar hito); (4) traer a
  la base de las asistidas lo que toma prestado; (5) parametrizar la pantalla por el catálogo, sin cadenas del
  producto; (6) llevar los tests que hoy usan la base del producto. Nada de esto está hecho.

## Aplicación de referencia

La primera aplicación es la plataforma de la que salió el método: llevar un sindicato dado de alta a una primera
versión funcional. Vive en `proyectos/colm3na/` y es el ejemplo de qué escribir para un producto nuevo:

- `proyectos/colm3na/catalogo.py`: las 34 tareas en siete grupos y los insumos.
- `proyectos/colm3na/controles.py`: un control por tarea.
- `proyectos/colm3na/tablero.py`: corre los controles, informa los módulos y llama al motor.
- `proyectos/colm3na/vista.py`: el contexto de un pedido, las reglas de decisión y el JSON.
- `proyectos/colm3na/herramientas.py`: herramientas de lectura, texto del sistema y preguntas sugeridas de las
  preguntas acotadas (en el plan, «Preguntame»).
- `proyectos/colm3na/asistidas/`: las tres asistidas (seccionales, padrón y conceptos desde recibos de muestra) y su
  `base.py`.
- `proyectos/colm3na/hitos.py`: los hitos de la Mesa de implementación, con las sugerencias de
  `data/xsii/hitos_sugeridos.json`.
- En la aplicación: tablas `Xsii*` y funciones `xsii_*` en `db.py`, rutas en `main.py`, pantalla en
  `templates/xsii.html` y `static/xsii/`.

Las decisiones X1 a X20 están en `PLAN_XSII.md`; X21 a X29 (seccional sin ubicar, actualizar lo existente,
coordenadas de planilla, CSV y no Excel, mismas reglas que la carga masiva, seccional desconocida, topes, la IA
propone y la persona revisa, los hitos se proponen) están en `HISTORIAL.md` y `docs/xsii/API.md`. El tutorial es
`recursos/xsii-tutorial.html`, con fuentes en `docs/xsii/tutorial/`. El modelo de forma de este documento es
`xsk/METODO.md`.
