# Informe de test de estrés -- app del trabajador (staging)

**Estado: herramientas listas y validadas: código, faltan tres accesos para
ejecutar contra `mitrabajo-pruebas.onrender.com` de verdad.** Ver
"Qué falta y por qué" al final -- es la sección más importante de este
documento por ahora.

## A. Configuración probada

Relevado del código (`main.py`, `db.py`, `extractor.py`,
`DESPLIEGUE_RENDER.md`) el 2026-09-09. Pendiente de confirmar en el
dashboard de Render lo que el repo no fija (marcado abajo).

| Ítem | Valor | Fuente |
|---|---|---|
| Comando de arranque | `uvicorn main:app --host 0.0.0.0 --port $PORT` | `DESPLIEGUE_RENDER.md` |
| Workers de uvicorn | **1 (default, sin `--workers` en el comando)** | ídem |
| Pool de Postgres | `pool_size=5`, `max_overflow=5` → máx. 10 conexiones por proceso | `db.py:60-65` |
| Plan del servicio web | Starter (confirmar CPU/RAM exactos en Render) | `DESPLIEGUE_RENDER.md` |
| Plan de Postgres | Basic, el más chico (confirmar tamaño exacto en Render) | `DESPLIEGUE_RENDER.md` |
| Llamada a Anthropic | **Síncrona** (`anthropic.Anthropic().messages.create`, sin `await`) | `extractor.py` |
| Ruta que la llama | `POST /api/leer` (`async def`) llama a `extraer()` **sin threadpool** | `main.py:405-410` |

### El hallazgo que domina todo lo demás

`POST /api/leer` es una ruta `async def` de FastAPI que llama directo a
`extraer()`, una función **síncrona y bloqueante** (el cliente `Anthropic`
no es el async). En un único worker de uvicorn (el caso actual, por
default), esa llamada **bloquea el único event loop del proceso durante
toda la duración de la respuesta de la API** -- típicamente unos segundos
con una imagen real, y exactamente `MOCK_EXTRACTOR_LATENCIA` con el mock.
Mientras dura, **ninguna otra request async se atiende**: ni un login, ni
un `/app/inicio`, ni otra subida de recibo. Con `pool_size=5 +
max_overflow=5` (10 conexiones), el techo de Postgres importa mucho menos
que este bloqueo del único proceso -- es esperable que el Test 2 muestre
este síntoma antes de que la base o la CPU se acerquen a su límite. Ver
"Recomendaciones", ítem 1.

### Ajustes que este informe recomienda (no aplicados -- necesitan acceso a Render, ver el cierre)

- Sumar `--workers 2` (o el que el plan de CPU soporte) al Start Command,
  como paliativo inmediato mientras se corrige el código (ítem 1 de
  Recomendaciones). Con Starter (0.5 vCPU típico) más de 2 workers
  probablemente compite por CPU en vez de ayudar -- confirmarlo con el
  Test 1 corrido primero con 1 worker y después con 2.
- El pool de 10 conexiones alcanza sobrado para 1-2 workers; si se sube el
  número de workers, subir `max_overflow` en la misma proporción (`db.py`).

## B. Barandas obtenidas

**Pendiente de la corrida real.** `carga/resumen.py` completa esta tabla
automáticamente después de `carga/correr.sh` -- acá va el resultado real,
no estimado.

| Baranda | Valor |
|---|---|
| Máx. usuarios concurrentes con p95 < 1s y errores < 1% | — |
| Máx. recibos simultáneos sin que los lectores superen p95 de 1s | — |
| Accesos por día equivalentes | — |
| Logins por minuto máximos | — |

## C. Comparación con la carga esperada

**Pendiente de B.** Referencia: 5.000 usuarios activos, pico de
notificación ~300 concurrentes / ~100 logins/min, fin de mes 5-10 recibos
simultáneos.

## D. Diagnóstico

**Pendiente de la corrida.** Hipótesis fundada en el código (a confirmar):
el Test 2 va a mostrar el event loop bloqueado (workers=1 + llamada
síncrona) como cuello de botella antes que CPU, RAM o conexiones de
Postgres -- ver "El hallazgo que domina todo lo demás" arriba.

## E. Recomendaciones

Ordenadas por costo. Los efectos esperados son hipótesis a confirmar con
la corrida real; se van a ajustar con los números.

1. **Código -- hacer async la llamada a Anthropic** (o correrla en
   threadpool con `asyncio.to_thread`/`run_in_threadpool` mientras se
   migra al cliente `AsyncAnthropic`). Costo: bajo, un cambio acotado a
   `extractor.py` + los dos call-sites en `main.py`. Efecto esperado: con
   un solo worker, cada subida de recibo deja de trabar el resto del
   tráfico durante toda su duración -- el techo de "recibos simultáneos
   sin degradar lectores" debería subir varias veces.
2. **Configuración -- `--workers N` en el Start Command de Render** (N
   según CPU del plan). Costo: bajo, un cambio de settings en Render, sin
   tocar código. Efecto esperado: paliativo inmediato incluso sin el
   cambio de (1) -- varios procesos en paralelo, cada uno bloqueable pero
   no todos a la vez.
3. **Infraestructura -- subir el plan de Render/Postgres.** Solo si (1) y
   (2) no alcanzan: los números de B lo van a mostrar (CPU o conexiones
   saturadas incluso con la IA async y varios workers).

## Qué repetir después de aplicar cada recomendación

Repetir Test 1 y Test 2 completos (no solo el escalón que falló) después
de cada cambio, y comparar contra este mismo `resumen.csv` -- así queda
registrado si la baranda realmente subió o si el cuello de botella se
movió a otro lado.

---

## Qué falta y por qué

Esta sesión corre en un entorno aislado con salida a internet **solo por
HTTPS** (un proxy que tunela TLS). Eso alcanza para hablar con
`https://mitrabajo-pruebas.onrender.com` (el test de carga en sí), pero
**no** para conectarse directo a Postgres por su protocolo nativo (puerto
5432, no es HTTP) ni para nada que no sea HTTPS. No es un problema de
usuario/contraseña: ninguna librería de Postgres (psycopg, libpq) sabe
hablarle a un proxy HTTP para ese protocolo. Tres cosas quedaron
bloqueadas por esto y por accesos que todavía no tengo:

1. **`MOCK_EXTRACTOR=1` en Render**: variable de entorno + redeploy del
   servicio `mitrabajo-pruebas`, exclusivamente en el dashboard/API de
   Render.
2. **Sembrar los 1.000 trabajadores** (`carga/preparar_datos.py`): el
   script está listo y probado (sintaxis + lógica), pero necesita
   conectarse por Postgres nativo a `mitrabajo-pruebas-db`, algo que esta
   sesión no puede hacer. Se puede correr:
   - desde la Shell del servicio `mitrabajo-pruebas` en Render (ya tiene
     `DATABASE_URL` seteada ahí), o
   - desde cualquier máquina con salida normal a internet, con
     `DATABASE_URL=<External Database URL de mitrabajo-pruebas-db>`.
3. **CPU/RAM/conexiones del servidor durante el test**: `monitor_servidor.py`
   ya está escrito contra los endpoints reales de la API de Render
   (`api.render.com/v1/metrics/{cpu,memory,active-connections}`, verificados
   contra `api-docs.render.com`) y listo para correr desde esta sesión en
   cuanto haya una `RENDER_API_KEY` (Render → Account Settings → API Keys)
   y los IDs de `mitrabajo-pruebas` (`srv-...`) y `mitrabajo-pruebas-db`
   (`dpg-...`).

Con (1) resuelto en Render y (2) corrido por quien tenga acceso normal a
la base, más (3) (la API key), esta sesión puede correr `carga/correr.sh`
de punta a punta contra el staging real y completar las secciones B-D de
este informe con números, no estimaciones.
