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

## 6. Pedido de SDN: manejarlo todo desde `/entornos` de Pruebas

SDN no quiere entradas nuevas: los accesos y la configuración de observabilidad se manejan desde la landing `/entornos` (la de los 8 accesos, Recursos y Planes), con una pestaña "Observabilidad" en el mismo estilo que "Planes". **Es posible y respeta la Regla 0** si se separan dos cosas:

- **En `/entornos` (la puerta):** los enlaces a Grafana y Sentry, el estado general (semáforo por entorno, leído de Grafana), y un formulario para cambiar el mail y el intervalo de repetición. Guarda en la configuración y la aplica a Grafana por API.
- **Fuera de la app (el motor):** las mediciones, las alertas y los mails. Si `/entornos` está caído, los avisos siguen saliendo, y el tablero se abre directo desde Grafana.

Detalles a resolver: el token de Grafana que use la app va como variable de entorno del servicio (con el rol mínimo, no Admin) y el estado se lee de Grafana con un token de solo lectura. Diseño pendiente de la próxima pregunta.

## 7. Pendiente (se cierra pregunta a pregunta)

1. Diseño de la pestaña Observabilidad en `/entornos` (§6).
2. Activar Synthetic Monitoring en Grafana y crear los checks de `/healthz` y `/readyz` de Pruebas.
3. Colector externo de métricas de Render (dónde corre, cada cuánto, retención según plan gratuito) y segundo token de Grafana (solo escritura de métricas).
4. Cuenta y proyecto de Sentry; qué se envía y qué se filtra (nada de datos personales); integración en `main.py`.
5. Reglas de alerta de los cuatro eventos de §3.
6. Tablero: semáforo general por entorno y detalle por servicio y por sindicato.
7. Resumen diario de errores de usuarios por sindicato.
8. Métricas propias de la app: conexiones del pool, cupo del panel, latencia por ruta (sin datos personales).
9. Replicar a Demo.
