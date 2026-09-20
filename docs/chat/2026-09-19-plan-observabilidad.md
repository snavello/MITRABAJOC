# Plan de observabilidad de Colm3na
Fecha: 2026-09-19 · Herramienta: Code (conversación con SDN, una pregunta por vez) · Estado: **en construcción** (se completa pregunta a pregunta)
Quién: SDN
Origen: el cuelgue de Pruebas del 2026-09-18 (`docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md`): nadie recibió un aviso, los logs se perdieron y Render no guardó la historia de CPU y memoria.

## 1. Regla 0 (la que ordena todo)

**El observador vive fuera del dominio de falla de lo que observa.** Si la app, la base o Render se caen, la observación no puede caerse con ellos. Por eso no se pone Sentry ni Grafana dentro de la app ni de su base, y ni siquiera en otro servicio del mismo Render: una falla de la plataforma se lo llevaría igual.

Consecuencia: la app puede ser la **puerta de entrada** (`/entornos`, ver §6) pero nunca el **motor**. Si la app está caída, el motor sigue midiendo, guardando y avisando por mail.

## 2. Decisiones tomadas

| # | Decisión | Detalle |
|---|---|---|
| D1 | Tres frentes | **A** uptime y alertas, **B** errores con contexto, **C** métricas con historia (CPU/memoria de web y base). |
| D2 | Servicios externos gestionados (SaaS), un proveedor por función, todos fuera de Render | Nada de servidor propio por ahora. |
| D3 | Grafana Cloud para A y C; Sentry para B | SDN ya conoce Grafana; Sentry es nuevo para SDN. |
| D4 | Presupuesto: **todo gratis para empezar** | Se sube de plan si el gratuito queda corto. Los límites vigentes de cada plan gratuito se verifican contra su documentación antes de comprometer el diseño. |
| D5 | Avisos **solo a un mail (SDN)**, `snavello@gmail.com` por ahora | Configurable: `observabilidad/config.json`. |
| D6 | **Objetivo 1: un tablero** con el estado general y el particular. Los avisos son la excepción | Los errores de usuarios se **guardan siempre** para diagnóstico pero **no avisan**. |
| D7 | General = semáforo por entorno (web, base, errores). Particular = detalle por servicio **y por sindicato** | El detalle por sindicato se arma con el ID del sindicato en cada evento, **nunca con datos de personas** (CUIL, nombre). |
| D8 | Alcance inicial: **solo Pruebas**; se replica a Demo cuando esté validado | Producción no existe todavía. |
| D9 | Repetición del recordatorio: **cada 24 h** por ahora (`repeat_interval`) | Es para no agobiar durante Pruebas; configurable. |
| D10 | Todo se maneja desde **`/entornos` de Pruebas**, sin entradas nuevas; con formulario para **ver y configurar** (opción b) | Ver §6. La app es la puerta; el motor sigue afuera. |

## 3. Qué merece un mail (los cuatro eventos)

| # | Evento | Umbral |
|---|---|---|
| 1 | La app no responde (`/healthz` falla, medido desde afuera) | 3 minutos seguidos |
| 2 | La app vive pero la base no (`/readyz` falla) | 5 minutos seguidos |
| 3 | Muchas respuestas 5xx | más del 5 % de los pedidos durante 10 minutos |
| 4 | CPU o memoria, web o base | **por encima del 95 % durante más de 30 minutos** (SDN subió el umbral de 90 %/15 min) |

Todo lo demás no manda mail: queda guardado y visible en el tablero. Los errores de usuarios entrarán a un **resumen diario** por sindicato (a diseñar).

Reglas anti-ruido (ya aplicadas en Grafana): un mail al **abrirse** un problema y uno al **resolverse**; el recordatorio de un problema que sigue abierto cada 24 h (D9); las alertas se agrupan por `alertname` y `entorno` (espera 1 min, agrupa cada 5 min).

## 4. Arquitectura

| Pieza | Herramienta | Dónde vive | Qué cubre |
|---|---|---|---|
| A. Uptime y alertas | Grafana Cloud (Synthetic Monitoring + alertas) | Grafana Cloud | Pega a `/healthz` y `/readyz` desde afuera. |
| C. Métricas con historia | Grafana Cloud (Prometheus) + **un colector externo** que lee la API de Render | Grafana Cloud; el colector, fuera de Render (a definir, probablemente GitHub Actions) | CPU y memoria de web y base con historia (Render no la guarda), más métricas propias de la app. |
| B. Errores | Sentry | Sentry | `E-INTERNO-00` y demás, agrupados, con ruta, versión y sindicato (sin datos personales). |

El *stream* de métricas nativo de Render exigiría el plan Pro del workspace (de pago): con D4 se evita armando el colector propio, que además hace que la historia no dependa de un plan de Render.

## 5. Ya hecho (2026-09-19)

- Cuenta de Grafana Cloud (stack `braveorange1921`, plan gratuito) con una cuenta de servicio `sa-1-ccode` (Admin) para configurar por API. **Los tokens no se guardan en el repo**: van por variable de entorno (`GRAFANA_TOKEN`).
- `observabilidad/config.json` (mail, intervalos) y `observabilidad/aplicar_grafana.py` (idempotente, con `--dry-run` y `--probar-mail`): dejó en Grafana la carpeta `Colm3na · Pruebas`, el punto de contacto `sdn-mail` y la política de notificaciones (D5, D9 y las reglas anti-ruido). Verificado leyéndolo de vuelta y con un mail de prueba real.
- `test_observabilidad_config.py`: 9 tests sin red (la configuración se valida antes de tocar Grafana).
- Hallazgos técnicos: Grafana 13 quitó el endpoint viejo de prueba de contact points (se usa el de `notifications.alerting.grafana.app`, con el nombre del punto en base64 sin relleno); el Python "pelado" de Windows rechaza el certificado de Grafana por una raíz vencida del sistema (el script usa `certifi` cuando está).

## 5b. Monitor de uptime (HECHO 2026-09-19)

`observabilidad/aplicar_uptime.py` (idempotente, config en `config.json` → `uptime`) crea en Synthetic Monitoring dos checks HTTP que pegan desde **afuera** a Pruebas, y sus reglas de alerta en la carpeta `Colm3na · Pruebas`:

| Check | Frecuencia | Alerta (evento de §3) | Dispara tras |
|---|---|---|---|
| `/healthz` | cada 2 min | App no responde (Pruebas) — evento 1 | 3 min |
| `/readyz` | cada 3 min | Base de datos no responde (Pruebas) — evento 2 | 5 min |

- **Ubicaciones:** Ohio (donde está el host de Render) y São Paulo (la más cercana a SDN). La alerta usa `max by (job) (probe_success)`: solo dispara si fallan **las dos** ubicaciones a la vez, así un problema de un solo sitio no manda un mail.
- **Un 200 con otro cuerpo no cuenta como "la app vive"** (la página de error de un proxy, por ejemplo): el check exige `{"ok": true}`.
- **El monitor no se calla si se rompe:** si deja de reportar, la regla pasa a `NoData` y avisa. Quedarse ciego sin enterarse es peor que un falso aviso.
- **Presupuesto:** 72.000 ejecuciones al mes contra un tope gratuito de 100.000 (dato asumido; se verifica en Grafana Cloud → Billing/Usage). `validar_uptime` rechaza una configuración que se pase.
- Los eventos 3 (5xx) y 4 (CPU/memoria) necesitan métricas de la app y de Render: siguen pendientes.

## 5c. Métricas de Render en Grafana, tablero y alertas 3 y 4 (HECHO 2026-09-20)

**Evaluación de la alternativa nativa (Metrics Stream de Render):** existe y sirve, pero exige el plan **Pro del workspace (USD 25/mes; hoy Hobby)**. Su ventaja real es de seguridad: no hay que dejar una API key de Render (que da acceso a todo el workspace, Render no permite claves acotadas) fuera de Render. Con D4 (todo gratis) se eligió el colector propio; el stream queda como mejora futura si se pasa al plan Pro (los nombres de las métricas cambiarían y habría que rehacer el tablero).

**Colector** (`observabilidad/colector_render.py`, stdlib pura): lee de la API de Render y escribe en el Prometheus de Grafana Cloud por remote write (`remote_write.py` codifica protobuf y snappy a mano; el test lo verifica decodificándolo con un lector independiente). Corre por **dos vías que se cubren entre sí** (ver "Incidente del primer día"): **GitHub Actions cada 5 minutos** (`.github/workflows/metricas-render.yml`; el repo es público, sin costo), fuera de Render. y un **hilo dentro de la app** (`observabilidad/hilo_colector.py`, solo Pruebas). Cada corrida re-manda la **última hora**, así una corrida atrasada no deja un hueco: Grafana Cloud acepta puntos atrasados hasta cerca de 1-2 horas (medido: 1 h sí, 2 h no, error `err-mimir-sample-timestamp-too-old`). Juntan del web: CPU, memoria y sus límites (por instancia), pedidos HTTP por código de estado y host, latencia p95, instancias; de la base: CPU, memoria y sus límites, conexiones activas, disco usado y capacidad. Render no expone para este plan: replicación, autoscaling (`*-target`), disco del web.

**Secretos** (GitHub → Settings → Secrets → Actions): `RENDER_API_KEY` y `GRAFANA_METRICS_TOKEN` (token de Grafana Cloud con **solo** `metrics:write`). Nunca en el repo.

**Tablero** `Pruebas · Estado general` (`aplicar_tablero.py`): arriba, ¿la app y la base responden?, latencia, y minutos desde la última corrida del colector; debajo, CPU, memoria, conexiones y disco. Después la historia: CPU y memoria (con la línea del 95 %), pedidos y latencia por código, % de 5xx (0 % cuando está sano, no "sin datos"), disco, conexiones, latencia del monitor por ubicación, instancias. El detalle por sindicato queda pendiente (necesita métricas propias de la app).

**Alertas** (`aplicar_alertas_metricas.py`): evento 3 (más del 5 % de 5xx en 10 minutos, con un mínimo de 20 pedidos: uno de diez no es un 10 %), evento 4 (CPU y memoria por encima del 95 % más de 30 minutos, en la app o en la base) y una regla del propio colector (más de 30 minutos sin correr). Las tres de métricas **no** avisan cuando faltan datos (`sin_datos: OK`): si el colector se muere lo dice la suya, y no tiene sentido que cuatro reglas manden mail por lo mismo; la del colector sí avisa por la falta de datos. Las de CPU/memoria toleran huecos de hasta 15 minutos (`last_over_time`), porque el colector corre cada 5 y GitHub retrasa.

**Incidente del primer día (2026-09-19, 21:38):** los números del tablero pasaron a "No data" y se veían **verdes**. Causa: el cron de GitHub tardó más de 15 minutos en correr por primera vez, y los números de "ahora" usaban la búsqueda normal de Prometheus (5 minutos). Arreglo, en tres capas: (1) el tablero muestra "SIN DATOS" en ámbar en vez de verde (el color base de los umbrales es verde y un "No data" se veía como buena noticia) y sus números de "ahora" toleran un colector atrasado (`last_over_time[30m]`); (2) la ventana del colector pasó de 20 a 60 minutos, para rellenar huecos; (3) lo que SDN pidió que no se repita, que el colector no corra: **una segunda vía independiente**.

| Vía | Corre si... | No corre si... |
|---|---|---|
| GitHub Actions | la app está caída | GitHub se atrasa |
| Hilo en la app (`hilo_colector.py`) | GitHub se atrasa | la app está caída |

Escriben las mismas series con las mismas marcas de tiempo (Prometheus descarta los repetidos) y se identifican con la etiqueta `via` (`github`, `app`, `manual`) para poder ver que las dos están vivas. El hilo no cambia la regla 0: es un respaldo, nunca el motor. No suma exposición de claves: la app de Pruebas ya guardaba `RENDER_API_KEY` para la pestaña Planes; solo suma `GRAFANA_METRICS_TOKEN` (solo escritura de métricas). Si ambas fallan, la alerta "colector mudo" avisa a los 30 minutos.

**Actualizar a pedido y ver "en vivo" (pedido de SDN, 2026-09-20).** Tres caminos, con sus riesgos dichos:

| | Qué es | Depende de |
|---|---|---|
| **A. Enlace en el tablero → GitHub** | "Actualizar datos de Render ahora": abre el workflow y se toca *Run workflow*; en ~30 s hay datos nuevos. | Solo GitHub: **sirve con la app caída**. |
| **B. Botón en la pestaña Observabilidad** | "Actualizar métricas ahora": corre el colector una vez (~10 s), una vez por minuto como máximo. | La app viva y el PIN. |
| **C. Fila "En vivo" del tablero** | Seis gráficos (CPU, memoria, conexiones, disco: uso junto a su límite) que consultan la **API de Render directamente** cada vez que se abre o refresca el tablero, últimos 10 minutos, sin historia. Fuente Infinity `render-vivo`. | Que la API de Render responda. |

**Costo de C, que SDN aceptó:** la fuente `render-vivo` guarda la **API key de Render dentro de Grafana Cloud** (cifrada, y la fuente solo puede hablar con `api.render.com`). Esa clave da acceso a todo el workspace de Render, así que es un lugar más donde vive. Si se rota la clave hay que volver a correr `aplicar_tablero.py` con `RENDER_API_KEY` (y ya son cuatro lugares: secreto de GitHub, variable de la app, fuente de Grafana y la propia Render). Render limita las consultas (429): la fila hace ~10 por refresco de un minuto. Durante un deploy Render devuelve dos instancias; los gráficos toman la que tiene el dato más reciente (`$sort` en el selector).

Ninguna es "tiempo real": entre tocar y ver pasan unos 30 segundos (A y B); C es lo más cercano.

**Límite conocido:** la frescura es de entre 5 y 15 minutos, y GitHub puede atrasarse bastante más. Sirve para tablero y para las alertas sostenidas (30 minutos), no para detectar algo en segundos: eso lo hace el monitor de uptime (§5b).

## 6. Pestaña Observabilidad de `/entornos` (HECHO 2026-09-19)

SDN no quiere entradas nuevas: los accesos y la configuración de observabilidad se manejan desde la landing `/entornos` (la de los 8 accesos, Recursos y Planes), con una pestaña "Observabilidad" en el mismo estilo que "Planes". **Es posible y respeta la Regla 0** si se separan dos cosas:

- **En `/entornos` (la puerta):** los enlaces a Grafana y Sentry, el estado general (semáforo por entorno, leído de Grafana), y un formulario para cambiar el mail y el intervalo de repetición. Guarda en la configuración y la aplica a Grafana por API.
- **Fuera de la app (el motor):** las mediciones, las alertas y los mails. Si `/entornos` está caído, los avisos siguen saliendo, y el tablero se abre directo desde Grafana.

**Cómo quedó** (`observabilidad/panel.py`, `templates/_observabilidad.html`, rutas `/api/entornos/observabilidad`, `/entornos/observabilidad/config` y `/probar-mail`): mismo PIN y misma regla que "Planes" (solo Pruebas; en Demo la pestaña aparece deshabilitada y las rutas rechazan). Muestra el semáforo leído de las reglas de Grafana (**gris** mientras no haya reglas: un verde sin reglas mentiría), los enlaces al tablero y a Sentry, y el formulario del mail y el intervalo (24 h por defecto, elegible entre 1, 6, 12, 24 y 48 h; nunca un campo libre, para que un "1m" no mande un mail por minuto). La **fuente de verdad en ejecución es Grafana**, no `config.json`: la pantalla lee de ahí y guarda ahí, conservando lo que no edita.

**Tokens** (variables de entorno de Render, nunca en el repo): `GRAFANA_TOKEN_LECTURA` con rol Viewer (probado: lee, recibe 403 al escribir) y `GRAFANA_TOKEN_CONFIG` con rol Editor (escribe; nunca Admin), ambos con vencimiento a un año. Un mail de prueba por minuto como máximo.

**Verificación real:** contra el Grafana verdadero, con la app local y los mismos tokens acotados. Encontró un error que los tests no vieron: Grafana guarda "24 h" como `1d`, el selector solo conocía `24h` y mostraba 1 h (un Guardar sin tocar nada habría cambiado el recordatorio a cada hora). Ahora las duraciones se normalizan al leerlas (`normalizar_duracion`) y hay test.

## 7. Pendiente (se cierra pregunta a pregunta)

1. ~~Pestaña Observabilidad en `/entornos` (§6).~~ Hecho.
2. ~~Synthetic Monitoring y checks de `/healthz` y `/readyz` (§5b).~~ Hecho. Falta probar el camino completo (una caída simulada que llegue al mail).
3. ~~Colector externo de métricas de Render y segundo token de Grafana (§5c).~~ Hecho.
4. Cuenta y proyecto de Sentry; qué se envía y qué se filtra (nada de datos personales); integración en `main.py`.
5. ~~Reglas de alerta de los cuatro eventos de §3.~~ Hecho (uptime en §5b, métricas en §5c).
6. Tablero: hecho el estado general y el detalle por servicio (§5c); falta el detalle por sindicato.
7. Resumen diario de errores de usuarios por sindicato.
8. Métricas propias de la app: conexiones del pool, cupo del panel, latencia por ruta (sin datos personales).
9. Replicar a Demo.
