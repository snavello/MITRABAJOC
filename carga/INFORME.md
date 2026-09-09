# Informe de test de estrés -- app del trabajador (staging real)

Corrido de punta a punta contra `https://mitrabajo-pruebas.onrender.com` el
2026-09-09. Carpetas de datos crudos: `carga/log/2026-09-09_2034_test1_ok_test2_bug/`
(Test 1 completo + Test 2 solo lectores, sin ráfagas por un bug de script
ya corregido) y `carga/log/2026-09-09_2100_test2_retry/` (Test 2 repetido,
con las ráfagas de recibos reales).

**Aviso sobre Test 2 (retry):** a mitad de esa corrida se pusheó y
redeployó una feature nueva (la pestaña Tests que se describe más abajo),
lo que reinició el proceso del servidor. Los números de los primeros
escalones (2 y 5) no deberían verse afectados; los de 10 y 20 pueden traer
algo de ruido extra por el reinicio. Se dejan igual porque son
consistentes con el resto de la evidencia (ver Diagnóstico), pero por eso
esto no reemplaza una corrida de referencia 100% limpia si se necesita el
número exacto para una decisión de presupuesto.

## A. Configuración probada

| Ítem | Valor | Fuente |
|---|---|---|
| Plan del servicio web | 0,5 vCPU / 512 MB, 1 instancia | API de Render (`srv-dacrg02jnfac73a0mes0`) |
| Plan de Postgres | **0,1 vCPU / 256 MB** | API de Render (`dpg-dacr7psmqu1s739kttq0-a`) |
| Comando de arranque | `uvicorn main:app --host 0.0.0.0 --port $PORT` | API de Render |
| Workers de uvicorn | **1 (default, sin `--workers`)** | ídem |
| Pool de Postgres | `pool_size=5` + `max_overflow=5` → máx. 10 conexiones por proceso | `db.py:60-65` |
| Llamada a Anthropic | **Síncrona**, sin threadpool, en una ruta `async def` | `extractor.py` + `main.py` (`POST /api/leer`) |
| `MOCK_EXTRACTOR_LATENCIA` usado | 15 s (default) | activado en Pruebas para esta corrida |

### El hallazgo que domina todo lo demás

Un solo worker de uvicorn atiende TODO el tráfico en un único event loop.
`POST /api/leer` es `async def` pero llama directo a una función
**síncrona y bloqueante** (el cliente `Anthropic`, sin `await` ni
threadpool): mientras dura esa llamada -- 15 s con el mock, unos segundos
más con la IA real -- **el proceso entero deja de atender cualquier otra
request**: ningún login, ningún `/app/inicio`, ninguna otra subida.

Pero el Test 1 (sin ninguna subida de recibo, solo lecturas) ya muestra
degradación seria a partir de 100 usuarios concurrentes, y el Test 2
reprodujo el mismo techo con 200 lectores solos, sin ninguna ráfaga
encima (p95 de 27,7 s -- ver tabla). **El único worker es el techo real,
no solo la IA síncrona**: cualquier tráfico simultáneo compite por el
mismo y único hilo de ejecución.

## B. Barandas obtenidas

| Baranda pedida | Resultado |
|---|---|
| Máx. usuarios concurrentes con p95 < 1 s y errores < 1% | **Ninguno de los escalones probados la cumple.** Ya a 50 concurrentes el p95 es 4,2 s (más de 4 veces el objetivo), con 0% de error. |
| Máx. concurrentes con errores < 1% (sin el p95) | 200 (0,07% de error; a 400 salta a 25,4%). |
| Máx. recibos simultáneos sin que los lectores superen p95 de 1 s | **Ninguno.** Con 200 lectores solos, sin ninguna subida, el p95 ya es 27,7 s. Con solo 2 subidas simultáneas de recibo encima, sube a 47,4 s. |
| Accesos por día equivalentes | Con el techo real (200 concurrentes, el último escalón con <1% de error): 200 × (60 / 20 min de sesión estimada) × 10 h activas ≈ **6.000 accesos/día**. Muy por debajo de una base de 5.000 usuarios activos si una fracción relevante entra en simultáneo. |
| Logins por minuto máximos | En el escalón de 200 concurrentes, ~12 requests/s totales (6 pasos por iteración: ingresar+login+home+novedades+app+credencial) ⇒ **~120 logins/min** antes de que el error empiece a crecer feo. Bajo carga sostenida real, esperable menos. |

## C. Comparación con la carga esperada

Referencia: 5.000 usuarios activos, pico de notificación ~300 concurrentes
y ~100 logins/min, fin de mes 5-10 recibos simultáneos.

| Escenario esperado | Cobertura actual |
|---|---|
| Pico de notificación: ~300 concurrentes | **No se cubre.** El servicio ya degrada mal a 200 y colapsa a 400 (25% de error) y totalmente a 800 (100%). 300 cae justo en la zona de degradación seria, no de funcionamiento sano. |
| ~100 logins/min | Al límite: el escalón de 200 concurrentes sostiene ~120 logins/min equivalentes, pero ya con p95 de 30 s -- técnicamente "no se cae", pero la experiencia es inutilizable. |
| Fin de mes, 5-10 recibos simultáneos | **No se cubre con margen.** Con 10 recibos simultáneos sobre 200 lectores, el 27% de las subidas falla (timeout) y los lectores tienen 22,6% de error. Con 20, la mitad de todo falla. |
| 5.000 usuarios activos (total, no simultáneos) | No es directamente comparable con estos tests (son de concurrencia, no de usuarios totales por día), pero el techo de accesos/día estimado en B (~6.000) sugiere que ni siquiera esa base total es cómoda si la actividad no está muy repartida en el tiempo. |

**Ningún escenario esperado se cubre hoy con margen (×N).** El más
cercano (100 logins/min) se sostiene solo si se acepta una latencia de
decenas de segundos, no la experiencia normal de la app.

## D. Diagnóstico

**El único worker de uvicorn es el cuello de botella dominante, confirmado
en dos formas independientes:**
1. Test 1 (sin ninguna IA de por medio): p95 ya sube a 13,8 s a 100
   concurrentes y a 29,9 s a 200, con 0% y 0,07% de error respectivamente
   -- el sistema no se cae, pero cada request espera su turno en el mismo
   hilo.
2. Test 2, 200 lectores solos (sin ninguna subida de recibo): p95 de
   27,7 s -- prácticamente el mismo número que el escalón de 200 del Test
   1, con una carga de trabajo distinta. La coincidencia confirma que el
   límite es el proceso, no una ruta en particular.

**La IA síncrona agrava el problema cuando además hay subidas de
recibo:** con 200 lectores + apenas 2 subidas simultáneas (cada una
bloqueando el proceso 15 s), el p95 de los lectores sube a 47,4 s (contra
27,7 s sin ninguna subida). Con 10 o 20 subidas simultáneas, tanto las
subidas como las lecturas superan 60 s (timeout) para una fracción
grande de los pedidos.

**Postgres (0,1 vCPU / 256 MB) no llegó a ser el límite en esta corrida**:
las conexiones activas se mantuvieron en 10-15 (dentro de lo que permite
el pool de la app) y su CPU/RAM no mostraron saturación evidente en los
datos capturados -- pero es la pieza MÁS chica de toda la instalación
(0,1 vCPU) y no se descarta que empiece a pesar apenas se resuelva el
cuello de botella del worker único y la concurrencia real le llegue a la
base. La RAM del servicio web sí llegó a 594 MB en un momento del Test 2
(retry) -- **por encima de los 512 MB del plan**, aunque coincide con la
ventana del redeploy mencionado arriba, así que no se puede afirmar con
certeza que sea 100% orgánico.

## E. Recomendaciones

Ordenadas por costo.

1. **Código -- hacer async la llamada a Anthropic** (o correrla en
   threadpool con `asyncio.to_thread`/`run_in_threadpool` mientras se
   migra al cliente `AsyncAnthropic`). Costo: bajo, cambio acotado a
   `extractor.py` + los dos call-sites en `main.py`. Efecto esperado:
   una subida de recibo deja de trabar el resto del tráfico durante su
   duración -- resuelve el agravante de "recibos simultáneos", no el
   techo de concurrencia general (ver ítem 2).
2. **Configuración -- `--workers N` en el Start Command de Render**, N
   según el plan (probar 2 primero con el plan actual de 0,5 vCPU; más de
   eso probablemente compite por CPU en vez de ayudar). Costo: bajo, un
   cambio de configuración en el dashboard de Render, sin tocar código.
   **Este es el cambio que más impacto va a tener sobre la baranda
   principal** (usuarios concurrentes con latencia sana): reparte el
   tráfico entre procesos en vez de servirlo todo por un único hilo.
   Repetir Test 1 después de este cambio solo (antes de tocar el código
   de la IA) para medir su efecto por separado.
3. **Infraestructura -- subir el plan de Postgres** de 0,1 vCPU / 256 MB
   a uno mayor, en cuanto (1) y (2) permitan que la concurrencia real le
   llegue a la base (con un solo worker, Postgres nunca se puso a prueba
   de verdad). Costo medio, cambio de plan en Render sin tocar código.
4. **Infraestructura -- subir el plan del servicio web** (más vCPU/RAM)
   solo si, después de (1) y (2), sigue sin alcanzar para 300 concurrentes
   con latencia sana. Costo más alto; hacerlo último porque (2) por sí
   solo puede resolver la mayor parte del problema a costo mucho menor.

## Qué repetir después de aplicar cada recomendación

Repetir Test 1 y Test 2 completos (no solo el escalón que falló) después
de cada cambio, EN ESE ORDEN (2 antes que 1, ya que es más barato y
probablemente el de mayor impacto), y comparar contra los números de
este informe. Evitar pushear otros cambios al mismo tiempo que se corre
el test (ver el aviso al principio sobre el redeploy de esta corrida).

---

## Herramienta para repetirlo

Todo lo necesario quedó en el repo, ya usado y validado contra el
servicio real:

- **`carga/`** (k6 + Python): la corrida de referencia rigurosa descripta
  arriba. Ver `carga/README.md`.
- **Pestaña "Tests" en `/entornos`** (nueva, en producción): un botón Run
  con parámetros configurables (tipo de test, escalones, duración) que
  dispara un Job de Render -- corre en un contenedor aparte para no
  falsear los números compitiendo con el propio servidor. Pensada para
  chequeos rápidos entre despliegues, no reemplaza la corrida de
  referencia de `carga/` para sacar barandas finas. Muestra también la
  configuración actual del servidor (workers, pool de Postgres, CPU/RAM
  en vivo). Verificado de punta a punta contra el servicio real: un test
  chico (escalones 5 y 10) corrió y devolvió resultados correctos.
- **Pestaña "Actividad" en `/entornos`** (nueva, en producción): dashboard
  de monitoreo con trámites, recibos verificados, notificaciones,
  tokens de IA consumidos y accesos por rol, por sindicato y totales,
  Pruebas y Demo lado a lado, con CPU/RAM del servidor. Se actualiza sola
  cada 10 minutos. Los accesos se cuentan desde ahora en adelante (no hay
  historial previo a este cambio).
