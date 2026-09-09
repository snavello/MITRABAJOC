# Informe de test de estrés -- app del trabajador (staging real)

Corrido de punta a punta contra `https://mitrabajo-pruebas.onrender.com` el
2026-09-09. Este documento está escrito para leerse sin necesitar el
código al lado: cada término técnico se explica la primera vez que
aparece, y hay un glosario al final por si hace falta volver a algo.

Carpetas de datos crudos, si alguien quiere revisar los números fila por
fila: `carga/log/2026-09-09_2034_test1_ok_test2_bug/` (Test 1 completo +
Test 2 solo lectores) y `carga/log/2026-09-09_2100_test2_retry/` (Test 2
repetido, con las ráfagas de recibos reales).

**Aviso sobre Test 2 (repetido):** a mitad de esa corrida se desplegó una
funcionalidad nueva (la pestaña Tests que se describe al final de este
informe), lo que reinició el proceso del servidor. Los números de los
primeros escalones (2 y 5 recibos simultáneos) no deberían verse
afectados; los de 10 y 20 pueden traer algo de ruido extra por ese
reinicio. Se dejan igual porque son consistentes con el resto de la
evidencia (ver Diagnóstico), pero si en algún momento se necesita el
número exacto para justificar un gasto de infraestructura, conviene
repetir esa corrida sola, sin desplegar nada en el medio.

## Cómo leer este informe

Cada test avanza en **escalones**: un número fijo de usuarios simulados
atacando el sistema al mismo tiempo (por ejemplo, 200), sostenido varios
minutos seguidos con un comportamiento realista (login, mirar páginas,
pausas de unos segundos entre clic y clic), antes de subir al escalón
siguiente. Subir de a escalones deja ver en qué punto EXACTO empieza la
degradación, en vez de solo confirmar si el sistema aguanta o no un
número fijo de golpe.

Para cada escalón se mide, entre otras cosas, el tiempo que tarda el
servidor en responder cada pedido, y se resume en tres números:

- **p50 (la mediana)**: de todos los pedidos de ese escalón, la mitad
  fueron más rápidos que este valor y la mitad más lentos. Es la
  experiencia "típica" de un usuario cualquiera.
- **p95**: el 95% de los pedidos fueron más rápidos que este valor --
  dicho al revés, **1 de cada 20 pedidos fue más lento**. Es el número
  que de verdad define si la app se siente bien, porque un promedio (o
  incluso la mediana) esconde a la gente que peor la pasa: si el p95 es
  malo, 1 de cada 20 clics de cualquier usuario, todo el tiempo, se
  siente lento.
- **p99**: 1 de cada 100 pedidos fue más lento que este valor. Es la cola
  extrema, el peor caso -- útil para saber qué tan mal puede llegar a
  estar alguien con mala suerte en el peor momento.

Por qué importan los tres juntos: si p50 fuera bueno pero p95 malo,
significaría que el sistema anda bien la mayoría del tiempo con "baches"
frecuentes. Lo que se ve en esta corrida es distinto: **p50 y p95 suben
juntos y parejo** a medida que crece la carga. Eso dice que el problema
no son casos raros -- es el sistema entero poniéndose lento parejo,
consistente con que todos los pedidos están haciendo cola detrás de un
único proceso que los atiende de a uno.

También se mide el **% de errores** (pedidos que directamente fallaron o
tardaron tanto que se los dio por caídos) y el **rps** (requests por
segundo que el servidor efectivamente pudo procesar en ese escalón --
cuánto "rinde" en la práctica, más allá de cuánta gente está esperando).

## A. Configuración probada

| Ítem | Valor | Qué significa |
|---|---|---|
| Plan del servicio web | 0,5 vCPU / **512 MB** de RAM, 1 instancia | Media unidad de procesador y medio gigabyte de memoria -- el escalón más chico que ofrece Render para un servicio que atiende tráfico. |
| Plan de Postgres | **0,1 vCPU / 256 MB** | La base de datos. Es la pieza MÁS chica de toda la instalación -- una décima parte de un procesador. |
| Comando de arranque | `uvicorn main:app --host 0.0.0.0 --port $PORT` | Así arranca el servidor. No tiene `--workers`, así que arranca con el valor por defecto: **uno solo**. |
| Workers de uvicorn | **1** | Un "worker" es un proceso independiente del servidor, capaz de atender pedidos en paralelo con los demás workers. Con 1 solo, todo pasa por el mismo proceso, uno atrás del otro. |
| Pool de Postgres | `pool_size=5` + `max_overflow=5` → máx. 10 conexiones **por worker** | Cuántas conversaciones simultáneas con la base puede tener abiertas cada proceso del servidor. Con 1 worker, el límite de la app hoy es 10 conexiones en total. |
| Llamada a la IA (Anthropic) | **Síncrona**, sin threadpool, dentro de una ruta que debería ser asíncrona | La función que lee un recibo con IA bloquea todo el proceso mientras espera la respuesta -- nadie más puede ser atendido en ese rato. |
| Latencia de IA simulada (`MOCK_EXTRACTOR_LATENCIA`) | 15 s | Para no gastar créditos reales ni depender de la velocidad variable de la API, el test usó una espera fija de 15 s en vez de llamar a Anthropic de verdad -- el tiempo típico real de esa llamada. |

### El hallazgo que domina todo lo demás

Un solo worker de uvicorn atiende **todo** el tráfico, uno por vez, en un
único hilo de ejecución. Cuando llega la subida de un recibo,
`POST /api/leer` bloquea ese único proceso durante toda la espera de la
IA (15 s con la simulación, unos segundos menos con la real) -- mientras
tanto, ningún otro pedido se atiende: ni un login, ni un `/app/inicio`,
ni otra subida.

Pero acá está el punto más importante de todo este informe: **el Test 1,
que no sube ningún recibo y no toca la IA para nada, ya muestra
degradación seria a partir de 100 usuarios concurrentes**. Y el Test 2
reprodujo el mismo techo con 200 lectores solos, sin ninguna subida de
recibo encima: el p95 dio prácticamente el mismo número (27,7 s) que el
escalón equivalente del Test 1 (29,9 s), con una carga de trabajo
completamente distinta.

**Esa coincidencia es la prueba de que el límite real es el único
worker, no la IA síncrona.** La IA agrava el problema cuando además hay
subidas de recibo (lo empeora bastante, como se ve en la sección de
Diagnóstico), pero el techo de cuántos usuarios puede atender bien el
sistema ya está puesto por tener un solo proceso sirviendo todo, aun sin
IA de por medio.

## B. Barandas obtenidas

| Baranda pedida | Resultado |
|---|---|
| Máx. usuarios concurrentes con p95 < 1 s y errores < 1% | **Ninguno de los escalones probados la cumple.** Ya a 50 concurrentes el p95 es 4,2 s (más de 4 veces el objetivo), aunque con 0% de error. |
| Máx. concurrentes con errores < 1% (sin exigir el p95) | 200 (0,07% de error; a 400 salta a 25,4%). Es decir, el sistema "no se cae" hasta 200, pero tarda muchísimo en responder. |
| Máx. recibos simultáneos sin que los lectores superen p95 de 1 s | **Ninguno.** Con 200 lectores solos, sin ninguna subida, el p95 ya es 27,7 s. Con apenas 2 subidas de recibo simultáneas encima, sube a 47,4 s. |
| Accesos por día equivalentes | Usando el techo real (200 concurrentes, el último escalón con menos de 1% de error) con la fórmula pedida (concurrencia × 60/duración de sesión × horas activas): 200 × (60 / 20 min de sesión estimada) × 10 h activas ≈ **6.000 accesos por día**. Muy por debajo de lo cómodo para una base de 5.000 usuarios activos si una fracción relevante entra en simultáneo (un feriado de pago, por ejemplo). |
| Logins por minuto máximos | En el escalón de 200 concurrentes, el servidor sostuvo unos 12 pedidos por segundo en total (cada usuario simulado hace 6 pasos por vuelta: entrar, loguearse, home, novedades, recibo, credencial) ⇒ aproximadamente **120 logins por minuto** antes de que el error empiece a crecer feo. Bajo una carga sostenida real (no un test de laboratorio), es esperable que aguante menos. |

## C. Comparación con la carga esperada

Referencia dada: 5.000 usuarios activos, pico de notificación de ~300
concurrentes y ~100 logins/min, fin de mes con 5 a 10 recibos
simultáneos.

| Escenario esperado | Cobertura actual |
|---|---|
| Pico de notificación: ~300 concurrentes | **No se cubre.** El servicio ya degrada mal a 200 y colapsa parcialmente a 400 (25% de error) y totalmente a 800 (100%). 300 cae justo en la zona de degradación seria, no de funcionamiento sano. |
| ~100 logins/min | Al límite: el escalón de 200 concurrentes sostiene el equivalente a ~120 logins/min, pero ya con una latencia de decenas de segundos -- técnicamente "no se cae", pero la app se siente rota. |
| Fin de mes, 5-10 recibos simultáneos | **No se cubre con margen.** Con 10 recibos simultáneos sobre 200 lectores, el 27% de esas subidas falla (se agota el tiempo de espera) y los lectores tienen 22,6% de error. Con 20 recibos simultáneos, la mitad de todo falla. |
| 5.000 usuarios activos (base total) | No es directamente comparable con estos tests (miden concurrencia, no usuarios totales por día), pero el techo de accesos/día estimado arriba (~6.000) sugiere que ni siquiera esa base total es cómoda si la actividad no está bien repartida en el tiempo. |

**Conclusión de esta sección: ningún escenario esperado se cubre hoy con
margen.** El más cercano (100 logins/min) se sostiene solo si se acepta
una latencia de decenas de segundos, muy lejos de lo que un trabajador
esperaría al abrir la app.

## D. Diagnóstico

**El único worker de uvicorn es el cuello de botella dominante,
confirmado de dos formas independientes:**

1. El Test 1 (sin ninguna IA de por medio) ya muestra el p95 subiendo a
   13,8 s a 100 concurrentes y a 29,9 s a 200, con 0% y 0,07% de error
   respectivamente -- el sistema no se cae, pero cada pedido espera su
   turno detrás de todos los anteriores en el mismo hilo.
2. El Test 2, con 200 lectores solos y sin ninguna subida de recibo, dio
   un p95 de 27,7 s -- prácticamente el mismo número que el escalón de
   200 del Test 1, con una carga de trabajo distinta. Esa coincidencia
   confirma que el límite es el proceso entero, no una ruta puntual.

**La IA síncrona agrava el problema en cuanto hay subidas de recibo
encima:** con 200 lectores + apenas 2 subidas simultáneas (cada una
bloqueando el único proceso 15 s), el p95 de los LECTORES (que no
subieron ningún recibo) sube de 27,7 s a 47,4 s solo por la presencia de
esas 2 subidas. Con 10 o 20 subidas simultáneas, tanto las subidas como
las lecturas superan el minuto de espera para una fracción grande de los
pedidos.

**Postgres (0,1 vCPU / 256 MB) no fue el límite GENERAL de esta corrida
-- pero en su propia CPU sí llegó al techo, y con evidencia real, no
solo razonamiento.** Cruzando las muestras de `servidor.log` de las dos
corridas con métricas de servidor:

| Corrida | CPU máxima de Postgres | RAM máxima de Postgres |
|---|---|---|
| Test 2 (primera) | **0,10 de 0,10 vCPU → 100%** | 142 MB de 256 MB → 55% |
| Test 2 (repetido) | **0,10 de 0,10 vCPU → 100%** | 162 MB de 256 MB → 63% |

La CPU tocó el techo de su asignación en las dos corridas, con apenas
10 a 15 conexiones activas -- bastante antes de que la concurrencia real
le llegara a la base, porque el cuello de botella del único worker web
frenaba el tráfico mucho antes. La RAM, en cambio, nunca pasó de dos
tercios de sus 256 MB. Esto tiene sentido con el tipo de trabajo que
hace esta base: consultas cortas y simples (filtros por `sindicato_id`,
inserts, algún `GROUP BY` en Actividad), no consultas que necesiten
mucha memoria de trabajo por conexión -- lo que sí cuesta es el volumen
de conexiones abriéndose, cerrándose y ejecutando esas consultas cortas
una tras otra en una sola décima parte de un núcleo.

**Conclusión para elegir plan de Postgres: prioridad a la CPU, no a la
RAM.** Los planes de Render suben las dos juntas (no se puede pedir más
CPU sin más RAM), así que en la práctica esto se traduce en no quedarse
en un plan asumiendo que la RAM alcanza -- la CPU es la que se va a
quedar corta primero, y ya lo hizo con una fracción chica de la
concurrencia real. Es esperable que esto pese más apenas se resuelva el
cuello de botella del worker único y la concurrencia real le empiece a
llegar de verdad a la base (ver la sección de escalado más abajo).

La RAM del servicio **web** (no la de Postgres) sí llegó a 594 MB en un
momento del Test 2 repetido -- por encima de los 512 MB del plan actual
-- aunque coincide con la ventana del reinicio mencionado arriba, así
que no se puede afirmar con certeza que sea 100% producto de la carga.

## E. Recomendaciones para HOY (plan actual, sin gastar más)

Ordenadas por costo, para la instalación actual de Pruebas:

1. **Código -- hacer asíncrona la llamada a Anthropic** (o correrla en un
   "threadpool" -- un grupo de hilos aparte del principal -- mientras se
   migra al cliente async de Anthropic). Costo bajo, cambio acotado a
   `extractor.py` y sus dos puntos de uso en `main.py`. Efecto esperado:
   una subida de recibo deja de trabar el resto del tráfico mientras
   dura -- resuelve el agravante de "recibos simultáneos", no el techo
   general de concurrencia (ver el punto 2).
2. **Configuración -- sumar `--workers N` al comando de arranque en
   Render** (probar con N=2 primero, dado el 0,5 vCPU actual). Costo
   bajo: es un cambio de configuración en el dashboard de Render, sin
   tocar una línea de código. **Este es el cambio de mayor impacto sobre
   la baranda principal** (usuarios concurrentes con latencia sana):
   reparte el tráfico entre procesos en vez de servirlo todo por un solo
   hilo. Conviene repetir el Test 1 con este cambio solo, antes de tocar
   el código de la IA, para medir su efecto por separado.
3. **Infraestructura -- subir el plan de Postgres**, en cuanto los dos
   puntos anteriores permitan que la concurrencia real le llegue a la
   base. Ya con apenas 10-15 conexiones su CPU tocó el 100% de su
   asignación (0,1 vCPU) -- la RAM, en cambio, se quedó en 55-63% de
   sus 256 MB (ver Diagnóstico). **Al elegir el próximo plan, priorizar
   CPU sobre RAM.** Costo medio: cambio de plan en Render, sin tocar
   código.
4. **Infraestructura -- subir el plan del servicio web**, solo si
   después de 1 y 2 sigue sin alcanzar para 300 concurrentes con latencia
   sana. Costo más alto; conviene dejarlo último porque el punto 2, solo,
   puede resolver la mayor parte del problema a un costo mucho menor.

## F. Extrapolación para producción: ¿pocas instancias grandes o muchas chicas?

Este apartado responde a la pregunta concreta para cuando arranque
producción: un presupuesto de 3 a 5 instancias de 1 vCPU / 2 GB (plan de
USD 25/mes cada una) más 1 o 2 instancias de 2 vCPU / 4 GB (USD 85/mes)
si hiciera falta. Es una extrapolación razonada a partir de lo medido acá,
no una medición directa -- al final de esta sección se explica cómo
confirmarla antes de comprometer el gasto.

### El hecho técnico que ordena la decisión

Un proceso de Python -- aunque use `async`, como esta app -- usa
efectivamente **un solo núcleo de procesador**, sin importar cuántos
tenga la máquina donde corre. Esto tiene una consecuencia directa y poco
intuitiva: **comprar una instancia con más CPU, sin cambiar nada más, no
mejora en nada la concurrencia**. Si se contrata una instancia de 2 vCPU
pero se la sigue arrancando con 1 solo worker (como corre Pruebas hoy),
la segunda CPU queda sin usar -- el cuello de botella descripto en el
Diagnóstico sigue exactamente igual. Hace falta sumar `--workers N` para
que la instancia reparta el trabajo entre varios procesos y aproveche esa
CPU de más.

Dicho esto, la pregunta deja de ser "más CPU por máquina" contra "más
máquinas" en el sentido de la potencia bruta -- los dos caminos necesitan
ajustar `--workers` igual. La diferencia real está en otro lado:

- **Muchas instancias chicas** (las 3 a 5 de 1 vCPU/2GB del plan
  propuesto): Render las reparte solo, con su propio balanceador de
  carga. Y como esta app guarda la sesión de cada usuario en una cookie
  firmada, **sin ningún estado guardado en el servidor** (confirmado en
  el código, `auth.py`), no hay ningún problema de "pegajosidad" --
  cualquier instancia puede atender a cualquier usuario en cualquier
  momento, sin coordinación especial. Se gana redundancia real: si una
  instancia se cae o se reinicia (como pasó, sin querer, durante este
  mismo test), las demás siguen sirviendo tráfico sin que nadie lo note.
  Es también el camino más simple de operar: activar más instancias es
  un control en el dashboard de Render, no una decisión de ingeniería.
- **Pocas instancias grandes** (1 o 2 de 2 vCPU/4GB): mismo total
  aproximado de CPU, pero si una se cae, se pierde una porción mucho más
  grande de la capacidad de golpe. Tiene sentido cuando una carga
  necesita mucha memoria en un solo proceso -- no es el caso de esta app:
  la RAM nunca fue el factor limitante en esta corrida, salvo un pico
  puntual que coincide con el reinicio ya mencionado.

### Recomendación concreta con el presupuesto propuesto

Usar las 3 a 5 instancias chicas para el **servicio web**, cada una con
1 a 2 workers según su CPU -- entre 6 y 10 procesos sirviendo en paralelo
con redundancia real, contra el proceso único de hoy: un salto de 6 a 10
veces la capacidad de servir tráfico en paralelo. Reservar la instancia
de 2 vCPU/4GB (o las dos) para **Postgres**, no para más web: hoy la base
corre con 0,1 vCPU, la pieza más chica de toda la instalación, y ya tocó
el 100% de esa CPU con apenas 10-15 conexiones (ver Diagnóstico) -- va a
empezar a sentir la concurrencia real mucho antes de lo que parece, en
cuanto se resuelva el cuello de botella del worker único. Al elegir ese
plan, priorizar CPU sobre RAM: en los datos capturados, la CPU de
Postgres se saturó mientras su RAM todavía tenía margen (55-63% de uso).

**Un detalle que se acopla directo a esta decisión**: cada worker abre
hasta 10 conexiones a Postgres (`pool_size=5` + `max_overflow=5`). Con 6
a 10 workers en total, eso son entre 60 y 100 conexiones simultáneas
posibles -- hay que confirmar que el plan de Postgres elegido las
soporte (se ve en el panel de Render, "Max Connections"), o bajar ese
número por worker si no.

### Cómo confirmarlo antes de gastar

Esto es una extrapolación razonada a partir de una sola causa raíz clara
(un solo proceso sirviendo todo), no una medición de la configuración
real de producción. Antes de comprometer el gasto mensual, lo más
honesto es aprovechar la pestaña **Tests** que quedó funcionando en
`/entornos` (ver más abajo) para correr el mismo test de estrés contra
la configuración real, una vez provisionada -- con las instancias y los
workers ya configurados como se piensa dejarlos en producción.

## Qué repetir después de aplicar cada recomendación

Repetir Test 1 y Test 2 completos (no solo el escalón que falló) después
de cada cambio, en este orden: primero el punto 2 de la sección E (sumar
workers, más barato y de mayor impacto), después el punto 1 (IA
asíncrona), y recién después cualquier cambio de plan. Comparar cada
corrida contra los números de este informe. Evitar desplegar otros
cambios mientras corre el test (ver el aviso al principio sobre el
reinicio de esta misma corrida).

---

## Herramientas para repetirlo, ya en el repo y probadas contra el servicio real

- **`carga/`** (k6 + Python): la corrida de referencia rigurosa descripta
  en todo este informe. Ver `carga/README.md` para los pasos.
- **Pestaña "Tests" en `/entornos`** (nueva, en producción): un botón Run
  con parámetros configurables (tipo de test, escalones, duración) que
  dispara un test en un contenedor aparte de Render (para no falsear los
  números compitiendo por CPU con el propio servidor que se está
  midiendo). Pensada para chequeos rápidos entre despliegues -- no
  reemplaza la corrida de referencia de `carga/` para sacar barandas
  finas, pero es justamente la herramienta para confirmar la
  extrapolación de la sección F contra una configuración real. Muestra
  también la configuración actual del servidor: workers, pool de
  Postgres, CPU y RAM en vivo. Verificada de punta a punta contra el
  servicio real.
- **Pestaña "Actividad" en `/entornos`** (nueva, en producción): panel de
  monitoreo con trámites, recibos verificados, notificaciones, tokens de
  IA consumidos y accesos, por sindicato y totales, Pruebas y Demo lado a
  lado, con CPU y RAM del servidor. Se actualiza sola cada 10 minutos.
  Los accesos se cuentan desde ahora en adelante (no hay historial previo
  a este cambio).

## Glosario

- **Escalón**: un nivel de carga sostenido varios minutos (cuántos
  usuarios simulados atacan el sistema al mismo tiempo) antes de subir al
  siguiente.
- **p50 / p95 / p99**: ver "Cómo leer este informe" al principio.
- **rps**: pedidos por segundo que el servidor efectivamente procesó en
  ese escalón.
- **Worker**: un proceso independiente del servidor, capaz de atender
  pedidos en paralelo con los demás workers del mismo servicio.
- **Pool de conexiones**: cuántas conversaciones simultáneas con la base
  de datos puede tener abiertas cada worker a la vez.
- **MOCK_EXTRACTOR**: modo de prueba que evita llamar a la IA real
  durante el test (para no gastar créditos ni depender de su velocidad
  variable), simulando su demora típica con una espera fija.
- **vCPU**: "CPU virtual" -- la unidad con la que Render mide cuánto
  procesador tiene contratado un servicio (0,5 vCPU es media unidad).
