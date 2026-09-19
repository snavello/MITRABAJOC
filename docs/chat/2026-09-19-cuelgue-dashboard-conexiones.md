# Cuelgue del Panel Sindical: diagnóstico y plan de corrección
Fecha: 2026-09-19 · Herramienta: Cowork · Origen: chat "[MT] Panel Sindical — cuelgue por conexiones y observabilidad" (proyecto Mitrabajo)
Estado: borrador (diagnóstico confirmado: 2.2 y 2.4 por logs, 2.1 por el filtro usado; Code reproduce en la Fase 1)
Quién: SDN

## 1. Qué pasó

El 2026-09-18, en `mitrabajo-pruebas` con la configuración mínima (web
`0.5c-512mb`, base `0.1c-256mb`, 1 worker de uvicorn — la misma "línea
base" de `carga/experimentos.json`), un solo usuario cambió varias veces
filtros del Panel Sindical sin esperar a que terminara de pintar la
selección anterior. La app dejó de responder a **todo**, incluso a un login
desde otra sesión. Reiniciar el web service no cambió nada; reiniciar
Postgres lo destrabó.

Los logs de ese momento y la captura de `pg_stat_activity` **no se
tomaron**. Este documento reconstruye la causa desde el código; la Fase 1
del prompt le pide a Code confirmarla o refutarla con evidencia antes de
tocar nada.

## 2. Diagnóstico desde el código (commit `e7f5811`, 2026-09-17)

Todo lo que sigue está verificado línea por línea en el repo.

### 2.1 Sesiones anidadas: un request del panel puede necesitar dos conexiones a la vez (el defecto)

`dashboard.py`:

- `_cuits_de_empresas()` (l. 225) llama a `catalogo_empresas()` (l. 213),
  que abre **su propia** `db.get_session()` (l. 216).
- `_cuil_de_afiliado()` (l. 235) abre **su propia** `db.get_session()`
  (l. 242).
- Las dos se llaman desde `_sql_recibos` (l. 356 y 375), `_sql_tramites`
  (l. 399), `_sql_notificaciones` (l. 422) y `_sql_consultas`.
- Esos constructores se invocan **mientras el que los llama ya tiene una
  sesión abierta**: `kpis()` (l. 496, y dentro `_kpis_de_rango` dos veces
  + `_cuits_de_empresas` directo en l. 508), `seccionales_geo()` (l. 679 y
  siguientes), `semaforo()`, `serie_recibos()`, `validacion()`,
  `diferencias_empresa()`, `tramites_seccional()`, `notificaciones()`,
  `formato_semana()`, los cuatro `explorador_*`.

Consecuencia: **con el filtro de empresa o de afiliado activo, cada request
de agregados retiene una conexión del pool y pide una segunda.** Si el pool
está lleno de requests que hacen lo mismo, ninguna consigue la segunda y se
esperan mutuamente hasta el `pool_timeout` (deadlock clásico de pool).

### 2.2 Pool chico, sin timeouts

`db.py` l. 105–128: `pool_size=5, max_overflow=5` (10 conexiones), sin
`pool_timeout` (queda el default de SQLAlchemy: **30 s**), sin
`statement_timeout` ni `idle_in_transaction_session_timeout` del lado de
Postgres. Ninguna consulta ni ninguna espera tiene techo.

### 2.3 Cada refresco del panel dispara 12–13 requests en paralelo

`static/dashboard.js`, `refrescar()` (l. 187–219): 10 paneles
(`serie-recibos`, `validacion`, `tramites-seccional`, `notificaciones`,
`diferencias-empresa`, `semaforo`, `seccionales-geo`, `formato-semana`,
`explorador/<tab>`, `kpis`) + un `explorador/<tab>?page_size=1` por cada
pestaña no activa (2 o 3), todo en `Promise.all`. Debounce de 250 ms
(l. 230–231) y `AbortController` (l. 188–190) **existen y funcionan**, pero
el abort solo cancela en el navegador: **el servidor termina cada query
igual**. Cada click que pasa el debounce suma 13 requests al servidor.

### 2.4 Los endpoints son `def` síncronos y comparten el threadpool con toda la app

`main.py` l. 4977–5113: todos los `/admin/dashboard/*` son `def` (no
`async def`). FastAPI los corre en el threadpool de Starlette/anyio, **40
hilos por defecto, compartidos por todos los endpoints síncronos de la app**
(login, app del trabajador, admin, plataforma). Con 1 worker de uvicorn
(`DESPLIEGUE_RENDER.md` l. 29), ese threadpool es la única capacidad de la
app.

### 2.5 Reconstrucción del cuelgue

1. Refresco con filtro de empresa → 13 requests → 10 toman las 10
   conexiones del pool; cada una intenta abrir la segunda (2.1) y **ninguna
   la consigue durante 30 s** (2.2).
2. El usuario sigue cambiando filtros: cada ronda suma 13 hilos más
   esperando el pool.
3. A la tercera ronda los 40 hilos del threadpool están bloqueados (2.4) →
   **la app entera deja de responder, incluida otra sesión.** Esto explica
   el síntoma completo del lado de la app.
4. Por qué reiniciar la app no alcanzó (hipótesis, **no confirmada sin
   logs**): las decenas de agregados que sí llegaron a Postgres siguieron
   ejecutándose después de matar el proceso (Postgres no se entera hasta
   intentar devolver filas). En una base de 0,1 vCPU — que en el test de
   carga del 2026-09-09 ya estaba al 100 % de CPU con 10 conexiones — eso
   la dejó sin CPU; la app nueva arrancó contra esa base y el pool se llenó
   otra vez. Reiniciar Postgres mató esas queries.

### 2.6 Lo que está bien y no se toca

- Índices compuestos del panel: migración `d4a78e3fc144` (`sindicato_id +
  procesado_en/creado/enviado_en`, `trabajador(sindicato_id, cuil)`).
- Agregados en SQL server-side; explorador paginado (regla de
  `docs/DASHBOARD.md`).
- Migraciones en Pre-Deploy, no en el arranque.
- Aislamiento por tenant dentro de los constructores de WHERE.
- Keepalives TCP en `connect_args` (db.py l. 123–126).

## 3. Correcciones

Orden de impacto. Cada una es acotada y tiene su criterio de aceptación.

| # | Corrección | Dónde | Aceptación |
|---|---|---|---|
| C1 | **Una sesión por request.** `_cuits_de_empresas` y `_cuil_de_afiliado` reciben la sesión del que llama, o se resuelven una sola vez en `parsear_filtros()` y viajan en `f` (`f["cuits"]`, `f["cuil_af"]`). Ningún constructor `_sql_*` abre sesión. | `dashboard.py` | Test: durante cualquier endpoint de agregados, `engine.pool.checkedout()` nunca supera 1 por request. |
| C2 | **Engine con techos.** `pool_timeout=5`; `connect_args["options"] = "-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000"`; `lock_timeout=5000` solo para Alembic (`migrations/env.py`). Un `sqlalchemy.exc.TimeoutError` de pool devuelve **503 con JSON `{"detail": "..."}`** vía handler, nunca 500 ni cuelgue. `pool_size`/`max_overflow` pasan a variables de entorno con los defaults actuales. | `db.py`, `main.py`, `migrations/env.py` | Test: con pool de 1 y una conexión retenida, un request devuelve 503 en < 6 s. |
| C3 | **Cupo del panel.** Un `threading.BoundedSemaphore(N)` (N por env, default 4) alrededor de los endpoints de agregados `/admin/dashboard/*` (no los de detalle ni el asistente). Sin cupo en 2 s → **503** `{"detail": "El panel está ocupado, reintentá en unos segundos."}`. El front ya muestra `detail` (dashboard.js l. 148–154). | `main.py` | Test: 20 requests concurrentes al panel → como máximo N ejecutan a la vez, el resto 503 rápido; en paralelo, `/ingresar` responde en < 1 s. |
| C4 | **Front: menos presión.** Cola de a 4 fetches por ronda dentro de `refrescar()`; debounce a 400 ms; los contadores de pestañas inactivas se piden **después** de que terminan los paneles, no en la misma ráfaga. `AbortController` se mantiene. | `static/dashboard.js` | Verificable en Network: nunca más de 4 requests del panel en vuelo. |
| C5 | **Test de regresión.** Nuevo `test_dashboard_concurrencia.py`: engine con `pool_size=2, max_overflow=0`, filtro de empresa, 20 refrescos simultáneos con hilos. Hoy: se cuelga / `TimeoutError`. Después de C1+C2+C3: termina en < 10 s, sin 500, con 200 o 503 solamente. | nuevo | Es la prueba de que el cuelgue no vuelve. |
| C6 | **Health checks separados.** `GET /healthz` → 200 sin tocar la base (liveness). `GET /readyz` → `SELECT 1` con timeout de 2 s (readiness). Render apunta a `/healthz` (hoy no hay ninguno configurado en `DESPLIEGUE_RENDER.md`). | `main.py`, `DESPLIEGUE_RENDER.md` | Test: `/healthz` responde aunque el pool esté agotado. |
| C7 | **Escenario "filtro frenético" en el harness de carga.** `carga/k6/test3_panel.js`: 1 admin, 30 cambios de filtro con empresa en 60 s, abandonando las requests; en paralelo 20 lectores de la app del trabajador. Métrica: p95 de los lectores no se degrada más de 2× y 0 % de errores 500. | `carga/` | Se corre en Pruebas con `MOCK_EXTRACTOR=1`, nunca en demo. |
| C8 | **Runbook.** Sección "Si la app no responde" en `docs/OPERATIVA.md`: primero la pestaña Queries de la base en Render (o la consulta de `pg_stat_activity` de abajo) y `pg_terminate_backend(pid)` de lo que sobra; el reinicio de Postgres es el último recurso. Guardar captura y logs **antes** de reiniciar. | `docs/OPERATIVA.md` | — |

Consulta para el runbook (C8):

```sql
SELECT pid, state, wait_event_type, wait_event,
       now() - query_start AS duracion, left(query, 120) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND state <> 'idle'
ORDER BY query_start;
```

Lectura: muchas filas `active` con SQL del panel = saturación (este caso);
filas `idle in transaction` o `wait_event_type = 'Lock'` = bloqueo (otro
caso, otro arreglo).

## 4. Fuera de alcance de este bloque

- Caché de agregados por `sindicato_id + filtros` (30–60 s). Vale la pena,
  pero después de medir con C5/C7 si sigue haciendo falta.
- Pasar los endpoints del panel a `async` + driver async. Cambio grande;
  C3 resuelve el aislamiento sin eso.
- Subir el plan de la base de Pruebas. Es una decisión de AKG; los datos
  de C7 son el insumo.
- Observabilidad (Sentry, stream de métricas de Render → Grafana Cloud,
  uptime externo): bloque aparte, ya conversado; requiere plan Pro del
  workspace de Render para el stream de métricas.

## 5. Lo que Code tiene que preguntar, no decidir

- Si en Render Pruebas hay algún health check configurado hoy (C6).
- El valor de N para el cupo del panel (C3) — propuesta: 4, para la base
  de 0,1 vCPU.
- Si `statement_timeout=15 s` alcanza para `limites_bruto()`
  (`percentile_cont` sobre todos los recibos del tenant) con 50.000
  recibos; medirlo con `medir_dashboard.py` antes de fijarlo.
- Si el sindicato de la prueba del 18-sep es "La Bancaria de pruebas" y
  cuántos recibos tiene, para reproducir con el mismo volumen. El filtro
  usado fue **empresa**: el test C5 tiene que usar ese filtro.

## 6. Evidencia

### 6.1 Confirmada (logs de `mitrabajo-pruebas`, 2026-09-18)

A las 22:47:18 UTC (19:47 hora Argentina), cinco trazas en 50 ms, todas
desde `starlette/concurrency.py run_in_threadpool` → `dependant.call`
(endpoints `def` síncronos), terminando en:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 5 reached,
connection timed out, timeout 30.00 (Background on this error at:
https://sqlalche.me/e/20/3o7r)
```

Confirma 2.2 (pool de 10 sin `pool_timeout`: cada hilo esperó los 30 s por
defecto) y 2.4 (los hilos bloqueados son del threadpool compartido). Con la
ráfaga de 2.3 explica el cuelgue de la app.

**El filtro que se estaba cambiando era el de empresa** (SDN, 2026-09-19).
Es exactamente el caso de 2.1: con `f["empresas"]` cargado, cada request de
agregados llama a `_cuits_de_empresas()` con su sesión ya abierta y pide
una segunda conexión. Los `TimeoutError` de arriba son ese deadlock
venciendo a los 30 s. Diagnóstico 2.1 + 2.2 + 2.3 + 2.4 confirmado; queda
para la Fase 1 reproducirlo localmente con el test C5.

### 6.2 Pendiente (la aporta SDN)

- Logs entre 22:46:30 y 22:46:50 UTC: es el momento en que el pool se
  llenó (30 s antes del primer `TimeoutError`). Qué requests estaban en
  curso.
- Hora del último `TimeoutError` y si siguieron después de reiniciar el
  web service: confirmaría 2.5 punto 4 (base saturada con queries
  huérfanas).
- Métricas de Render de la base (CPU, conexiones) del 18-sep, ampliando el
  rango del selector: el plan Hobby retiene 7 días.
