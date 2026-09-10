# Test de estrés de la app del trabajador — los 6 tests comparados

> **Este archivo se genera solo.** Sale de `carga/experimentos.json`, que a su vez
> se arma con `carga/consolidar.py` desde los datos crudos de cada corrida
> (`carga/log/`). No editar a mano: corregir el dato de origen y volver a correr
> `python carga/consolidar.py && python carga/generar_md.py`. La misma información,
> con gráfico, se sirve en `/entornos/informe` del sitio de Pruebas.

Servicio medido: `mitrabajo-pruebas.onrender.com`. Objetivo fijado para los 6
tests: **p95 por debajo de 1 s con menos de 1% de errores**. Horarios en hora de
Buenos Aires. Los tiempos están en milisegundos salvo donde se indique.

## El resultado, en un párrafo

Se probaron 6 configuraciones. Hoy la navegación cumple el objetivo —p95 por debajo de 1 s con menos de 1% de errores— hasta 200 usuarios concurrentes, con 213 ms y 0,0% de error; en la línea base, ese mismo escalón daba 21,8 s. A 800 concurrentes se pasó de timeout con 69,0% de error a 8,8 s con 0,0%. La subida de recibos no se arregló con hardware sino con código: con 20 subidas simultáneas los errores pasaron de 48,6% a 0,37% sin tocar la infraestructura —lo único que cambió fue sacar la llamada a la IA de adentro del worker—. En la última corrida esas mismas ráfagas quedaron en 15,2 s con 0,0% de error, que es el piso que impone la propia IA, y los lectores que navegan mientras tanto bajaron a 248 ms.

## A. Los 6 tests

Cada uno cambió *una* cosa respecto del anterior, para poder atribuir la mejora o el
empeoramiento a esa cosa y no a una mezcla.

| # | Test | Cuándo | Servicio web | Postgres | Workers | Resultado |
|---|---|---|---|---|---|---|
| 1 | Línea base | 2026-09-09 17:34 a 18:40 | 0,5 vCPU / 512 MB | 0,1 vCPU / 256 MB | 1 | no cumple |
| 2 | Más workers, misma CPU | 2026-09-09 19:46 a 20:07 | 0,5 vCPU / 512 MB | 0,1 vCPU / 256 MB | 2 | no cumple |
| 3 | Postgres grande | 2026-09-09 20:41 a 21:21 | 0,5 vCPU / 512 MB | 2 vCPU / 4 GB | 1 | no cumple |
| 4 | Web grande + Postgres grande | 2026-09-09 21:34 a 22:14 | 2 vCPU / 4 GB | 2 vCPU / 4 GB | 2 | cumple |
| 5 | IA fuera del worker | 2026-09-10 12:42 a 13:21 | 2 vCPU / 4 GB | 2 vCPU / 4 GB | 2 | cumple |
| 6 | Ocho núcleos | 2026-09-10 17:29 a 18:09 | 8 vCPU / 16 GB | 4 vCPU / 16 GB | 8 | cumple |

**Test 1 — Línea base.** Medir el punto de partida: hasta dónde aguanta la configuración más barata posible, sin tocar nada. Ningún escalón cumplió el objetivo (p95 por debajo de 1 s y menos de 1% de errores).

El cuello de botella es el servicio web, no la IA: con 200 lectores puros —sin subir un solo recibo, sin tocar la IA— el p95 ya queda entre 26,7 s y 29,6 s, prácticamente lo mismo que el escalón de 200 del test de lecturas (21,8 s). Los dos servicios estaban al tope de su CPU: el web al 100,0% de sus 0,5 vCPU y Postgres al 100,0% de sus 0,1 vCPU con apenas 10 conexiones, mientras la RAM de la base no pasó del 55,5% — para esta app hace falta CPU en la base, no memoria. Las ráfagas de recibos revientan temprano: con 10 simultáneos ya falla el 27,3% de las subidas.

**Test 2 — Más workers, misma CPU.** Probar si repartir el trabajo en dos procesos mejora la concurrencia sin gastar un peso más de infraestructura. Ningún escalón cumplió el objetivo (p95 por debajo de 1 s y menos de 1% de errores).

Empeoró, y por eso se descartó. Contra la línea base, en todos los escalones válidos el tiempo subió: 50 concurrentes 3,6 s → 4,6 s (+27,5%); 100 concurrentes 11,6 s → 16,6 s (+43,0%); 200 concurrentes 21,8 s → 33,6 s (+54,2%). Los errores a 200 concurrentes pasaron de 0,0% a 0,67%. Dos procesos peleando por media vCPU no dan paralelismo real: solo agregan cambio de contexto y memoria. La conclusión que deja es que workers y CPU tienen que subir juntos — sumar uno solo de los dos no sirve. Se volvió a 1 worker inmediatamente después.

**Test 3 — Postgres grande.** Aislar cuánto del problema venía de la base de datos: se sube solo Postgres y se deja el web exactamente como estaba. Ningún escalón cumplió el objetivo (p95 por debajo de 1 s y menos de 1% de errores).

Postgres dejó de ser un límite: su CPU pasó del 100,0% de 0,1 vCPU al 8,1% de 2 vCPU, y la RAM al 2,8%. Eso mejoró de verdad la zona baja y media de lecturas: 50 concurrentes 3,6 s → 1,0 s (-71,5%); 100 concurrentes 11,6 s → 6,9 s (-40,1%); 200 concurrentes 21,8 s → 12,9 s (-40,8%). Pero de 400 concurrentes en adelante el techo no se movió (400 sigue en 26,0 s; 800 sigue en más de 60 s), porque ahí el límite es el servicio web, que siguió clavado en el 100,0% de sus 0,5 vCPU. Las ráfagas de recibos tampoco mejoraron. Queda demostrado que la base era parte del problema, pero no la parte que pone el techo.

**Test 4 — Web grande + Postgres grande.** Probar la configuración prevista para el arranque de producción: CPU entera en el web, un worker por núcleo, y la base ya holgada. Cumple el objetivo (p95 por debajo de 1 s y menos de 1% de errores) hasta 100 usuarios concurrentes.

Primera configuración que cumple el objetivo: 50 concurrentes en 190 ms y 100 en 198 ms, las dos con 0,0% de error. A 800 concurrentes pasó de más de 60 s con 69,0% de error en la línea base a 18,2 s con 0,01%. El web volvió a ser el límite (100,0% de sus 2 vCPU) pero ahora con cuatro veces más CPU, y Postgres quedó holgado (29,3% de CPU, 4,0% de RAM). Lo que NO mejoró son las ráfagas de recibos: con 10 simultáneos falla el 15,4% y con 20 el 48,6%, contra 27,3% de la línea base en el mismo escalón de 10 — sin mejora real pese a toda la CPU agregada. La causa no es CPU: cada subida bloqueaba un worker entero durante los 15 segundos de la llamada a la IA. Eso es lo que motivó el cambio de código del 2026-09-10, que el test 5 mide.

**Test 5 — IA fuera del worker.** Aislar el efecto del cambio de código: es la única diferencia contra el test 4, que corrió con exactamente los mismos planes y workers. Cumple el objetivo (p95 por debajo de 1 s y menos de 1% de errores) hasta 100 usuarios concurrentes.

El cambio de código resolvió lo que ni cuadruplicar la CPU había movido. Las subidas: con 5 simultáneos, de 40,7 s y 0,0% de error a 15,8 s y 0,0%; con 10 simultáneos, de más de 60 s y 15,4% de error a 16,1 s y 0,0%; con 20 simultáneos, de más de 60 s y 48,6% de error a 16,3 s y 0,37%. El p95 se queda plano alrededor de los 16,3 s sin importar cuántas lleguen juntas, que es exactamente lo esperado: cada subida sigue tardando lo que tarda la IA, pero ahora se procesan en paralelo en vez de hacer cola. En la misma ventana se completaron 270 subidas contra 37 del test 4, 7,3 veces más. Lo más importante para el trabajador que no está subiendo nada: los lectores en paralelo dejaron de sufrir (5: 37,6 s → 2,1 s; 10: más de 60 s → 2,3 s; 20: más de 60 s → 2,4 s). El grupo de control se movió poco y dentro del mismo régimen (50 concurrentes 190 ms → 326 ms; 100 concurrentes 198 ms → 324 ms): ese recorrido no toca el código que cambió, la diferencia entra en la variación normal entre corridas y los dos escalones siguen cumpliendo el objetivo.

**Test 6 — Ocho núcleos.** Medir la configuración que se evalúa contratar para producción, ya con el cambio de código puesto: cuánta concurrencia aguanta una sola instancia grande y dónde queda el nuevo techo. Cumple el objetivo (p95 por debajo de 1 s y menos de 1% de errores) hasta 200 usuarios concurrentes.

Con ocho núcleos y un worker por núcleo, el objetivo se cumple hasta 200 usuarios concurrentes: 213 ms con 0,0% de error, contra los 1,4 s del test 5. La mejora se ve en toda la curva de navegación: 100 concurrentes 324 ms → 203 ms; 200 concurrentes 1,4 s → 213 ms; 400 concurrentes 8,2 s → 2,1 s. El throughput subió a 76,1 pedidos por segundo en 200 concurrentes y 120,1 en 400. Las subidas de recibos quedaron planas en 15,2 s con 0,0% de error hasta 20 simultáneas -- prácticamente el piso que impone la IA, que no baja por agregar CPU. Y los lectores que navegan durante esas ráfagas bajaron a menos de un cuarto de segundo (10: 2,3 s → 245 ms; 20: 2,4 s → 248 ms), la primera vez que también ellos cumplen el objetivo. El pico de CPU del web en la fase de lecturas fue 60,8% y el de la base 25,4%: a diferencia de todos los tests anteriores, esta configuración termina la corrida con margen.

## B. Navegación: p95 según cuánta gente hay

La prueba que no sube ningún recibo y no toca la IA: mide el techo puro del servidor.
En negrita, los escalones que cumplen el objetivo.

| Usuarios concurrentes | 1. Línea base | 2. Más workers, misma CPU | 3. Postgres grande | 4. Web grande + Postgres grande | 5. IA fuera del worker | 6. Ocho núcleos |
|---|---|---|---|---|---|---|
| 50 | 3,6 s | 4,6 s | 1,0 s | **190 ms** | **326 ms** | **202 ms** |
| 100 | 11,6 s | 16,6 s | 6,9 s | **198 ms** | **324 ms** | **203 ms** |
| 200 | 21,8 s | 33,6 s | 12,9 s | 1,0 s | 1,4 s | **213 ms** |
| 400 | 43,0 s | n/d | 26,0 s | 7,2 s | 8,2 s | 2,1 s |
| 800 | timeout | n/d | timeout | 18,2 s | 17,2 s | 8,8 s |

`n/d` son los escalones del test 2 que quedaron contaminados por un despliegue a mitad
de corrida: se descartan. `timeout` quiere decir que los pedidos no respondieron dentro
de los 60 segundos que espera el test — el valor real es "más de 60 s", no 60.

## C. Subida de recibos

Tiempo de cada subida cuando llegan varias a la vez. El test 2 no corrió esta fase.

| Recibos simultáneos | 1. Línea base | 2. Más workers, misma CPU | 3. Postgres grande | 4. Web grande + Postgres grande | 5. IA fuera del worker | 6. Ocho núcleos |
|---|---|---|---|---|---|---|
| 2 | 15,7 s | — | 15,6 s | 15,2 s | 16,1 s | 15,2 s |
| 5 | 45,4 s | — | 40,0 s | 40,7 s | 15,8 s | 15,2 s |
| 10 | timeout | — | timeout | timeout | 16,1 s | 15,2 s |
| 20 | timeout | — | 45,4 s | timeout | 16,3 s | 15,2 s |

**Cuidado al leer esta tabla:** cada escalón tiene entre 6 y 37 subidas completadas, así
que su p95 es prácticamente el peor caso observado y no un percentil sólido. Sirve para
el orden de magnitud, no para comparar diferencias finas entre escalones. Por eso el test
3 muestra 20 simultáneos "mejor" que 10: es ruido de muestra chica, no una mejora.

## D. Qué mostró cada test

### El techo lo pone el servicio web, no la llamada a la IA

*Medido en el test 1.*

En el test 1 se midieron 200 lectores puros, sin subir un solo recibo y sin tocar la IA: el p95 quedó entre 26,7 s y 29,6 s. El escalón de 200 del test de lecturas, que es otra carga de trabajo distinta, dio 21,8 s. Que dos pruebas independientes choquen contra el mismo número muestra que el límite es el proceso que atiende, no lo que hace cada pedido.

### Postgres se saturó en CPU y nunca en memoria

*Medido en los tests 1 y 3.*

Con el plan más chico, la base llegó al 100,0% de su CPU con apenas 10 conexiones abiertas, mientras su memoria no pasó del 55,5%. Al subirla en el test 3, la CPU cayó al 8,1% y la RAM al 2,8%. Para esta app, al elegir plan de base de datos manda la CPU: la memoria sobra en los dos casos.

### Sumar workers sin sumar CPU empeora las cosas

*Medido en el test 2.*

El test 2 probó dos workers sobre la misma media vCPU y todos los escalones válidos empeoraron: 50 concurrentes 3,6 s → 4,6 s (+27,5%); 100 concurrentes 11,6 s → 16,6 s (+43,0%); 200 concurrentes 21,8 s → 33,6 s (+54,2%). Los errores a 200 concurrentes pasaron de 0,0% a 0,67%. Dos procesos compitiendo por el mismo medio núcleo no dan paralelismo: agregan cambio de contexto y memoria. Workers y CPU se suben juntos.

### Con CPU entera y un worker por núcleo, el techo se corre de golpe

*Medido en el test 4.*

El test 4 subió el web a 2 vCPU con 2 workers, sobre la base ya grande del test 3: 50 concurrentes 3,6 s → 190 ms; 100 concurrentes 11,6 s → 198 ms; 200 concurrentes 21,8 s → 1,0 s; 800 concurrentes timeout → 18,2 s. Es la única configuración probada que cumple el objetivo. El web volvió a quedar al 100,0% de su CPU —sigue siendo el límite— pero ahora con cuatro veces más para repartir, y la base quedó holgada en 29,3%.

### Las ráfagas de recibos no mejoran con más CPU

*Medido en los tests 1 y 4.*

Con 10 recibos simultáneos, la línea base falló el 27,3% de las subidas y el test 4 —con cuatro veces más CPU— el 15,4%; con 20, 50,0% contra 48,6%. La causa no es CPU: cada subida ocupaba un worker completo durante los 15 segundos que tarda la llamada a la IA, y mientras tanto ese worker no atendía a nadie más. Es un problema de código, no de infraestructura.

### Cuántas conexiones a la base consume cada worker

*Medido en el test 4.*

Cada worker abre hasta 5 conexiones más 5 de reserva, o sea 10. Con 2 workers, la cuenta da 20 y lo medido en el test 4 fueron 20 conexiones como máximo: la cuenta cierra. Sirve para dimensionar: al multiplicar instancias hay que multiplicar también este número y contrastarlo con el límite del plan de Postgres elegido.

## E. Qué hacer

1. **Subir Postgres a una vCPU entera, priorizando CPU sobre memoria** — *confirmado, costo medio · infraestructura.* Medido en el test 3: la CPU de la base pasó del 100,0% al 8,1% y la latencia de lecturas mejoró de verdad hasta 200 concurrentes. La memoria nunca fue el problema (2,8% de uso).

2. **Subir el servicio web a CPU entera y poner un worker por núcleo** — *confirmado, costo alto · infraestructura.* Medido en el test 4: es lo que llevó el p95 a 190 ms en 50 concurrentes y 198 ms en 100, los únicos escalones que cumplen el objetivo en las cuatro corridas. Las dos cosas van juntas: el test 2 probó que los workers solos empeoran.

3. **Correr la llamada a la IA en un hilo aparte** — *confirmado, costo bajo · código.* Medido en el test 5, contra el 4 y con la misma infraestructura exacta: con 20 subidas simultáneas, los errores pasaron de 48,6% a 0,37% y el p95 de timeout a 16,3 s, con 7,3 veces más subidas completadas en la misma ventana. Los lectores que navegaban en paralelo pasaron de timeout y 28,8% de error a 2,4 s y 0,12%. Es la corrección más barata de las tres y la que más cambió el comportamiento bajo ráfaga.

## F. Para el arranque en producción

> **Esto es razonamiento, no medición.** Todo lo anterior son números medidos contra el
> servicio de Pruebas; esta sección extrapola hacia una infraestructura que todavía no se
> probó. Antes de comprometer el gasto conviene correr el mismo test contra la
> configuración real ya contratada.

**El hecho técnico que ordena la decisión.** Un proceso de Python usa efectivamente un
solo núcleo, aunque el código sea asincrónico como el de esta app y aunque la máquina
tenga más. De ahí las dos mitades de la misma regla, las dos con evidencia acá: comprar
CPU sin sumar `--workers` deja los núcleos nuevos sin usar, y sumar workers sin CPU real
empeora las cosas (test 2). Van juntos: un worker por núcleo.

**Muchas instancias chicas o pocas grandes.** Para el servicio web conviene repartir en
varias instancias: las sesiones viajan en una cookie firmada y no hay estado en el
servidor, así que cualquier instancia atiende a cualquiera sin configuración extra; una
caída se lleva una porción más chica; y ningún proceso necesita mucha memoria propia
(en el test 4 el web usó 638 MB de los 4 GB disponibles).

**Cómo se hace en Render.** Para el servicio web no se crean servicios separados: es un
solo servicio con su pestaña *Scaling*, donde se fija el número de instancias; cada una
corre el mismo plan y Render reparte el tráfico con su propio balanceador. El autoscaling
automático existe pero requiere plan Pro o superior del workspace y escala por métrica de
CPU/memoria, no por horario.

**Postgres es distinto.** No existen varias instancias que se repartan la escritura: lo
que Render ofrece son réplicas de lectura (hasta cinco, de solo lectura, con retraso de
replicación y su propia URL de conexión), lo que obliga a separar en el código qué
consultas van a cada una. Hoy la app no hace esa separación. Si el objetivo es aguantar
más carga, la palanca real sigue siendo subir el plan de la única instancia — que es
justo lo que se midió en el test 3.

**La cuenta que no hay que olvidar.** Las conexiones a la base se multiplican por
instancia. Cada worker abre hasta 10 conexiones y el test 4 lo confirmó midiendo
exactamente 20 con 2 workers. Al escalar hay que multiplicar por la cantidad total de
workers y contrastarlo contra el límite del plan de Postgres elegido.

## G. Lo que hay que tener en cuenta de estas mediciones

- **Test 1:** El monitor de servidor todavía tenía un error de formato de fecha contra la API de Render y no pudo tomar ninguna métrica durante la fase de lecturas: ahí CPU y RAM figuran como no medidos. Se arregló antes de las fases siguientes y de los demás experimentos.
- **Test 1:** A mitad de la fase de recibos se desplegó código nuevo, lo que reinició el servidor. Los escalones de 2 y 5 recibos no deberían verse afectados; los de 10 y 20 pueden traer ruido extra.
- **Test 2:** A mitad de la corrida se desplegó código nuevo y el servidor se reinició. Los escalones de 400 y 800 quedaron contaminados (80% y 49% de error, con tiempos que no son comparables) y NO se usan para ninguna conclusión: solo se muestran marcados como inválidos.
- **Test 2:** Por ese mismo despliegue convivieron dos juegos de procesos durante unos minutos, así que los picos de CPU y RAM del web de esta corrida están inflados y no describen el costo real de dos workers.
- **Test 2:** Solo se corrió la fase de lecturas. No hay fase de recibos en este experimento.
- **Test 4:** Corrió ANTES del cambio de código que pasa la llamada a la IA a un hilo aparte (2026-09-10). Los números de la fase de recibos son los de la IA todavía bloqueando el worker.
- **Test 5:** Única diferencia contra el test 4: la llamada a la IA se corre en un hilo aparte (run_in_threadpool) en vez de bloquear al worker. Planes, workers, pool y latencia simulada de la IA son idénticos, y se verificaron contra la API de Render antes de arrancar. Por eso la fase de lecturas sirve de control: no toca ese código y debería dar parecido.
- **Test 6:** Cambia dos cosas a la vez respecto del test 5: la CPU del web (de 2 a 8 vCPU, con 8 workers en vez de 2) y la de la base (de 2 a 4 vCPU). Sirve para saber qué rinde el conjunto que se va a contratar, pero si algo saliera raro no se podría atribuir a una de las dos por separado.
- **Test 6:** A 800 concurrentes el generador de carga corre en un contenedor de 4 CPU y pudo haber sido él, y no el servidor, el que puso el techo: la CPU del web bajó respecto del escalón de 400 en vez de subir. El dato de 800 se lee como cota inferior de lo que aguanta el servidor, no como su límite.
- **Todas las corridas:** Los números de navegación de este informe se recalcularon el 2026-09-10. Hasta entonces, la ventana de medición de cada escalón estaba corrida y se comía la rampa de aceleración del escalón siguiente, así que los tiempos salían peores que los reales, y cada vez más a medida que subía la carga: el escalón de 200 del test 6 figuraba en 1.455 ms cuando su tramo sostenido dio 213 ms. El error afectaba a las seis corridas por igual y siempre en contra, así que las comparaciones entre tests seguían siendo válidas, pero los valores absolutos estaban inflados. Se corrigió en carga/resumen.py y se regeneraron todas las corridas desde sus datos crudos.
- **Todas las corridas:** La llamada a la IA se simuló con una espera fija de 15 segundos, para no depender de la velocidad variable del servicio real ni gastar créditos. Es la demora típica observada, pero es una simulación.
- **Todas las corridas:** Todos los tiempos se cortan a los 60 segundos: donde dice timeout, el pedido nunca respondió, y el valor real es "más de 60 s", no 60.
- **Todas las corridas:** El generador de carga corre en un contenedor de 4 CPU. En los escalones más altos puede ser él, y no el servidor, el que ponga el techo: cuando la CPU del servidor baja en vez de subir al pasar a más usuarios, ese escalón se lee como cota inferior de lo que aguanta, no como su límite.

## Cómo se reproduce

```
python carga/consolidar.py            # reconstruye el dataset desde carga/log/
python carga/verificar.py             # audita cada cifra contra los datos crudos
python carga/generar_md.py            # regenera este archivo
PIN_ENTORNOS=... BASE_URL=... python carga/publicar_experimentos.py   # publica en el sitio
```

Para correr un test nuevo, ver `carga/README.md`.
