# Observabilidad de Colm3na — ficha rectora

Ficha vigente para quien programa u opera. Versión ilustrada para leer y mostrar:
`recursos/observabilidad.html` (en la landing `/entornos` → Recursos). La historia de cómo se
llegó acá, con los incidentes y las mediciones, está en `docs/chat/2026-09-19-plan-observabilidad.md`
y no se reescribe: **esta ficha es la que se mantiene al día**.

Estado (2026-09-20): **Pruebas completo. Demo y Producción, pendientes** (procedimiento en §6).

## 1. Regla 0

El observador vive **fuera** de lo que observa: si la app, la base o Render se caen, la observación
sigue. La app es la **puerta** (pestaña Observabilidad de `/entornos`), nunca el **motor**. Ninguna
pieza nueva de observabilidad puede depender de que la app esté viva para medir o avisar.

## 2. Piezas y dónde viven

| Frente | Qué hace | Código | Corre en |
|---|---|---|---|
| A. Uptime | `/healthz` (cada 2 min) y `/readyz` (cada 3) desde Ohio y São Paulo; alerta solo si fallan todas las ubicaciones; exige `{"ok": true}` | `aplicar_uptime.py` | Grafana Synthetic Monitoring |
| C. Métricas | Lee la API de Render (CPU, memoria, HTTP, latencia, conexiones, disco) y escribe en Prometheus de Grafana por remote write (protobuf + snappy a mano, stdlib) | `colector_render.py`, `remote_write.py`, `.github/workflows/metricas-render.yml` | Ver "tres vías" |
| C. Tablero y alertas | Tablero `Pruebas · Estado general` y alertas 5xx, CPU, memoria, colector mudo | `aplicar_tablero.py`, `aplicar_alertas_metricas.py` | Grafana Cloud |
| B. Errores | Solo errores NO previstos, sin datos personales, con `ref`, código, ruta, rol, ID de sindicato | `sentry_config.py` (+ `main.error_no_manejado`) | Sentry |
| Mantenimiento | Alertas de disparador caído y de vencimiento de tokens | `aplicar_disparador.py`, `aplicar_vencimientos.py` | Grafana Cloud |
| Puerta | Pestaña Observabilidad: gráficos de Grafana, errores de Sentry con detalle, semáforo, mail y vencimientos | `panel.py`, `metricas_panel.py`, `sentry_panel.py`, `templates/_observabilidad.html` | La app (solo Pruebas) |

**El colector corre por tres vías** que escriben lo mismo (etiqueta `via`): cron de GitHub Actions
(no dispara de forma confiable: hubo más de una hora sin correr), hilo dentro de la app
(`hilo_colector.py`, solo si `ENTORNO` coincide con la config) y **disparador** (un check de Grafana
que le hace `workflow_dispatch` a GitHub cada 5 min). Cada corrida re-manda la última hora (Grafana
acepta puntos atrasados hasta ~1 h; con 2 h rechaza).

## 3. Qué avisa por mail (y nada más)

App no responde (3 min) · base no responde (5 min) · más del 5 % de 5xx en 10 min con ≥ 20 pedidos ·
CPU o memoria > 95 % por más de 30 min · más los tres de mantenimiento: colector mudo (30 min),
disparador falló (15 min) y token por vencer. Anti-ruido: un mail al abrir, uno al resolver, recordatorio
cada 24 h (`alertas.repeat_interval`, configurable desde la pestaña entre 1, 6, 12, 24 y 48 h).
**Sin datos:** las reglas de métricas no avisan por falta de datos (para eso está "colector mudo");
el monitor de uptime sí. En el tablero un dato faltante es "SIN DATOS" en ámbar, nunca verde.

## 4. Reglas de código que hay que respetar

- **Sin secretos en el repo.** Tokens por variable de entorno (`GRAFANA_TOKEN`, `GRAFANA_METRICS_TOKEN`,
  `RENDER_API_KEY`, `GITHUB_DISPATCH_TOKEN`, `SENTRY_*`). Un test lo verifica para el de Sentry.
- **Los scripts `aplicar_*` son idempotentes**, aceptan `--dry-run` y `--config`; la fuente de verdad
  de la configuración es `observabilidad/config.json`. Un cambio hecho a mano en Grafana se pisa.
- **Las consultas de la pestaña salen de `aplicar_tablero.construir_tablero`**, no de una copia: lo
  que se ve en la app y en Grafana no puede diferir (`metricas_panel.TARJETAS` / `GRAFICOS` son ids de
  panel; un test falla si el tablero cambia y ya no existen).
- **Sentry se reconstruye con lo mínimo**: `sentry_config.limpiar_evento` arma un evento nuevo, no
  filtra uno completo. `send_default_pii=False`, sin variables locales, `failed_request_status_codes`
  vacío, tope de 20 eventos por minuto. Un CUIL/CUIT suelto **sí** puede salir (decisión de SDN).
  Los eventos de prueba (`prueba=True`) van al entorno `prueba-de-conexion` y no ensucian el reporte.
- **La pestaña no inicia sesión en nadie**: lee con tokens acotados (Grafana Viewer, Sentry solo
  lectura) y dibuja. **No se publican enlaces abiertos** (se descartó un enlace público del tablero).
  Acceso del equipo a Grafana/Sentry = invitar con su usuario, nunca compartir credenciales.
- Solo Pruebas: `_exigir_observabilidad` exige PIN y `ENTORNO == "pruebas"` (en Demo, 400).
- Los tests se corren **un archivo por proceso** (`test_observabilidad_*.py`, `test_sentry*.py`,
  `test_metricas_panel.py`, `test_entornos_observabilidad.py`, `test_hilo_colector.py`,
  `test_error_no_manejado.py`). Nunca patchear `time.sleep` global (usar un `time` propio del módulo).
- Python del sistema en Windows rechaza el certificado de Grafana: usar `ag._contexto_tls()` (certifi).

## 5. Claves y vencimientos

| Clave | Dónde vive | Vence | Renovar |
|---|---|---|---|
| GitHub, disparador (grano fino, solo Actions del repo) | dentro del check de Grafana | **2026-10-18** (alerta 7 d antes) | token nuevo + `aplicar_disparador.py` |
| Grafana de la app: Viewer / Editor | Render: `GRAFANA_TOKEN_LECTURA` / `_CONFIG` | 2027-09-19 (alerta 30 d antes) | tokens nuevos, dos variables |
| Grafana `metrics:write` | secreto de GitHub y Render: `GRAFANA_METRICS_TOKEN` | **a confirmar** | token nuevo, dos lugares |
| API key de Render | secreto de GitHub, Render, fuente `render-vivo` de Grafana | no vence | rotar en 4 lugares; `aplicar_tablero.py` con la nueva |
| Sentry DSN (solo envía) | Render: `SENTRY_DSN` | no vence | regenerar y actualizar |
| Sentry token personal (lectura) | Render: `SENTRY_AUTH_TOKEN` | no vence | revocar si no se usa; permisos Read: Project, Issue & Event, Organization |
| Cuenta de servicio Admin de Grafana | se usó para configurar | no vence | **revocar** |

Pendiente de higiene: revocar la cuenta Admin de Grafana, la API key de Render usada y el token de
Sentry que se pegaron en conversaciones durante la construcción.

## 6. Replicar en Demo y en Producción (procedimiento, sin ejecutar todavía)

**Antes de empezar**
1. `observabilidad/config.json` describe **un solo entorno** (Pruebas). Cada entorno nuevo tiene su
   archivo (`config.demo.json`) y se aplica con `--config`. Grafana, el mail y la política de avisos
   son compartidos.
2. **El presupuesto del uptime es de todo el stack**: ejecuciones/mes = 2.592.000 ÷ frecuencia (s) por
   ubicación por check. Pruebas usa ~80.600 de un tope gratuito asumido de 100.000 (**sin verificar**:
   Grafana Cloud → Billing/Usage). Demo con la misma frecuencia lo pasa: bajar frecuencia o ubicaciones
   (una sola ubicación alcanza para la alerta) o pasar a un plan pago. `validar_uptime` solo controla su
   propia config, no la suma.
3. La pestaña Observabilidad es solo de Pruebas; verlos ahí exige un selector de entorno (código).

**Pasos**
0. Requisitos: `ENTORNO` correcto en el servicio; IDs del web (`srv-…`) y la base (`dpg-…`); **en Demo,
   Health Check Path `/healthz` recién después de promover** (antes rompe sus deploys).
1. `cp observabilidad/config.json observabilidad/config.demo.json` y cambiar: `grafana.carpeta_uid/titulo`
   y `tablero_uid/titulo`; `uptime.entorno`, `base_url`, `job`s y nombres de alerta; frecuencias/ubicaciones
   según presupuesto; `metricas_render.entorno` y `recursos`; títulos de las 4 alertas de métricas;
   `disparador` (job, evento, alerta); `sentry.proyecto` y `proyecto_id`. **Quitar `renovaciones`**
   (ya las avisa Pruebas; se duplicarían los mails).
2. Ensayo: cada script con `--dry-run --config observabilidad/config.demo.json`.
3. Grafana (con `GRAFANA_TOKEN`), en orden y con `--config`: `aplicar_grafana.py`, `aplicar_uptime.py`,
   `aplicar_alertas_metricas.py`, `aplicar_tablero.py`.
4. Colector: hoy el workflow llama a `colector_render.py` sin opciones (config de Pruebas). O un segundo
   workflow con `--config …demo.json`, o **(recomendado)** que el colector recorra todas las configs en
   una corrida (cambio chico) y alcance **un solo disparador**. Los secretos de GitHub ya sirven (mismo
   workspace de Render). Si hay segundo workflow: `aplicar_disparador.py --config …demo.json` (el token
   de GitHub existente sirve, mismo repo) y contar sus 8.640 ejecuciones/mes en el presupuesto.
5. Sentry: proyecto propio (`colm3na-demo`, Python), cargar su DSN como `SENTRY_DSN` en el servicio.
   Revisar en Sentry → Alerts que no haya regla por defecto que mande mail por cada error nuevo.
   La cuota gratuita es de la organización (compartida entre proyectos).
6. Verificar (~15 min): checks en verde en Synthetic Monitoring; tablero sin "SIN DATOS" y colector
   < 15 min; mail de prueba; error de prueba en el entorno correcto (desde la consola de Render con
   `sentry_config.capturar(..., prueba=True)`). El simulacro de caída solo en Pruebas.
7. Registrar: `config.demo.json` al repo, línea en `BITACORA.md`, "Estado actual" de `CLAUDE.md`,
   variables nuevas en `DESPLIEGUE_RENDER.md`, y la tabla de claves de esta ficha.

**Producción, además (decisiones que Pruebas postergó):** más de un destinatario y un canal que despierte a
alguien (no solo mail); recordatorio más corto (p. ej. 1 h); plan pago si el uptime o la cuota de errores
no alcanzan; cuentas y claves a nombre de la organización, con cuenta de servicio nueva y con
vencimiento; revisar umbrales con carga real y el criterio de privacidad (la afiliación sindical es dato
sensible, Ley 25.326).

## 6 bis. Telegram: los avisos al teléfono (2026-09-23)

Pedido de Sd: "mi número, alertas como las de Sentry y un resumen del día, simple
y sin costo". Telegram cumple las tres condiciones: API oficial gratuita, un POST
sin librerías (`telegram.py`), y un bot que se crea en dos minutos con BotFather.
WhatsApp exige cuenta de empresa aprobada y cobra por conversación; los SMS se
pagan uno por uno.

Tres canales, un solo bot (`Colm3na_bot`):

- **Alertas de Grafana**: `aplicar_grafana.py` crea un segundo punto de contacto
  (`sdn-telegram`) y una política con dos rutas (Telegram con `continue`, después
  el mail), **solo si el entorno donde corre trae `TELEGRAM_BOT_TOKEN` y
  `TELEGRAM_CHAT_ID`**. Sin ellas, todo sigue saliendo solo por mail. Este canal
  cumple la regla 0: avisa aunque la app esté caída.
- **Errores al instante**: el handler global (`main._capturar_en_sentry`) manda
  a Telegram lo mismo que a Sentry —código, referencia, patrón de ruta, rol y ID
  del sindicato; nunca una persona— con un freno de un aviso cada 10 minutos por
  código. Sale en un hilo aparte para no demorar el request.
- **Resumen del día**: `resumen_diario.py`, un hilo dentro de la app, a las 21:00
  de Buenos Aires (`TELEGRAM_RESUMEN_HORA`). Antes de mandar reclama el día con un
  INSERT en `avisoenviado` que solo puede ganar un worker. El texto lo arma
  `telegram.texto_resumen` con los indicadores de `esquema.py`, los errores de
  Sentry y el semáforo de Grafana; lo que no se pueda leer dice "sin dato".

Pruebas desde la pestaña Observación técnica: "Enviar prueba a Telegram" y
"Mandar el resumen del día ahora". Para rotar el token: BotFather → `/mybots` →
API Token → Revoke, y actualizar la variable en Render (y volver a correr
`aplicar_grafana.py` para el punto de contacto).

## 7. Pendiente

Resumen diario de errores por sindicato · métricas propias de la app (pool, cupo del panel, latencia por
ruta; permitiría el detalle por sindicato) · replicar a Demo y Producción (§6) · Sentry "Prevent Storing
of IP Addresses" (prioridad baja) · renovar el token de GitHub antes del 2026-10-18, confirmar el del
`metrics:write` y revocar las credenciales de la construcción.
