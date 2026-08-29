# DASHBOARD.md — Panel Sindical de "Mi Trabajo"

> Especificación funcional y técnica para implementar el dashboard del administrador de organización (sindicato).
> **Referencia visual obligatoria:** `docs/dashboard-sindical.html` (mockup navegable con datos ficticios). Ante cualquier duda de comportamiento o diseño, el mockup manda; ante dudas de datos o arquitectura, este documento manda; si aun así hay ambigüedad, **consultar a Sd antes de decidir** (una pregunta por vez).

---

## 0. Contexto y objetivo

"Mi Trabajo" es una plataforma SaaS multi-tenant (FastAPI + Jinja2 + SQLModel + Alembic + PostgreSQL, hosteada en Render) donde trabajadores validan sus recibos de sueldo contra su convenio colectivo. Este dashboard es **la función estrella para el sindicato**: una vista tipo Tableau/Qlik con filtros interactivos, cross-filtering y detalle de datos, para el rol **administrador de organización**.

El trabajo se divide en **dos fases obligatoriamente secuenciales**:

- **Fase 1 — Adecuación de datos y funciones.** Cerrar los huecos del modelo y de la API para que el dashboard tenga de dónde alimentarse. No se escribe una sola línea del frontend del dashboard hasta terminar y verificar esta fase.
- **Fase 2 — Construcción del dashboard.** Implementar la interfaz replicando el mockup con datos reales.

Restricción global: **cero compromisos de robustez en producción**. Trabajar en branch `feature/dashboard-sindical`, migraciones Alembic reversibles, tests, y smoke test de los tres flujos de login y del aislamiento de tenants antes de mergear.

---

## 1. Supuestos ya validados con Sd (no re-preguntar)

1. **Seccional:** existe en el modelo del **trabajador**. No se agrega a empresa. Toda dimensión "seccional" del dashboard se deriva del trabajador dueño del dato (recibo → trabajador → seccional; ídem trámites, notificaciones, consultas).
2. **Funcionalidades existentes con datos:** trámites con estados, notificaciones con registro leída/no leída, noticias. **El bot de consultas aún no existe**: se deja el contrato de datos y el endpoint preparados detrás de un feature flag, y el panel se oculta hasta que haya datos (ver §4.7).
3. **Privacidad del detalle de recibos:** el sindicato ve el recibo **identificado (nombre y CUIL) únicamente si el trabajador lo envió voluntariamente al sindicato** (flujo de envío voluntario ya existente). Todo otro recibo se muestra **anonimizado**: seccional, empresa, categoría, formato, montos y resultado, sin ningún dato que identifique al trabajador.
4. **Colores:** el dashboard usa los colores de marca que la organización ya tiene configurados (theming por tenant existente). Se agrega **un color nuevo: "color destacado"**, usado exclusivamente para marcar selecciones y filtros activos. Default: fucsia `#E5188F`. Configurable por organización por el admin de plataforma (no por el admin de organización).
5. **Acceso:** rol administrador de organización, dentro de su tenant. El admin de plataforma puede abrir el dashboard de cualquier organización en modo lectura (mismo endpoint con su permiso ya existente de impersonación/selección de organización, si la app lo tiene; si no lo tiene, dejarlo fuera de alcance y anotarlo en el PR).
6. **Stack del frontend:** Jinja2 + JavaScript vanilla + Chart.js **vendoreado** en `static/` (no CDN en producción). Sin frameworks nuevos. Respetar el sistema de diseño existente (`diseno-mi-trabajo/SKILL.md`).

---

## 2. FASE 1 — Adecuación de datos y funciones

Antes de tocar nada, hacer un **relevamiento del modelo real** (los nombres de tablas/campos de abajo son descriptivos; mapearlos a los reales del repo) y presentar a Sd un plan corto con el gap encontrado. Luego implementar:

### 2.1 Verificaciones de modelo (agregar solo lo que falte)

| Necesidad | Qué verificar | Si falta |
|---|---|---|
| Seccional del trabajador | Campo/relación en el modelo trabajador, con catálogo de seccionales por organización | Consultar a Sd (según lo validado, existe) |
| Recibo → trabajador → seccional | Join posible y eficiente | Índice compuesto (ver 2.2) |
| Fecha de procesamiento del recibo | Timestamp de cuándo el validador analizó el recibo (distinto del período liquidado) | Agregar campo `procesado_en` con backfill = fecha de creación |
| Resultado de validación | Estado discreto: `ok` / `con_diferencias` / `en_revision` (o equivalente real) | Normalizar a un enum si hoy es derivado |
| Monto de diferencia detectada | Monto total observado por recibo | Agregar campo calculado persistido si hoy se recalcula al vuelo |
| Envío voluntario al sindicato | Flag + timestamp en el recibo | Debe existir (Sprint B); verificar |
| Formato del recibo | `viejo` / `nuevo` (Ley 27.802), ya requerido por el extractor bi-formato | Verificar que se persista |
| Remuneración bruta | Persistida por recibo (para el filtro por rango salarial) | Verificar |
| Trámite | `organizacion_id`, `trabajador_id`, tipo, estado (`abierto`/`en_proceso`/`resuelto`), `creado_en`, `resuelto_en` | Agregar `resuelto_en` si falta (backfill nulo) |
| Notificación | `organizacion_id`, `trabajador_id`, tipo (`noticia`/`alerta_recibo`/`tramite`/`recordatorio` — mapear a los tipos reales), `enviada_en`, `leida_en` (nullable) | Verificar tipos; agregar `leida_en` si el "leída/no leída" hoy es booleano sin fecha |
| Último depósito de aportes por empresa | Dato para el semáforo (ya previsto en Sprint A: extracción de fecha de último depósito) | Verificar que se agregue por empresa: `MAX(fecha_ultimo_deposito)` sobre recibos de esa empresa en el tenant |
| Consulta al bot (futuro) | No existe | Crear tabla `consulta_asistente` (`organizacion_id`, `trabajador_id`, `tema`, `resuelta_por_bot: bool`, `creada_en`) vacía, lista para cuando llegue el RAG |

### 2.2 Índices (crítico para rendimiento)

Todos los agregados filtran siempre por `organizacion_id` + rango de fechas. Crear (si no existen) índices compuestos que empiecen por `organizacion_id` y sigan por la columna de fecha correspondiente en: recibos (`procesado_en`), trámites (`creado_en`), notificaciones (`enviada_en`), consultas (`creada_en`). Verificar con `EXPLAIN` que las consultas del §3 los usen.

### 2.3 Configuración

- `organizacion.color_destacado` (string hex, default `#E5188F`), editable solo por admin de plataforma, expuesto al template junto a los colores de marca existentes.
- Umbrales del semáforo de aportes a nivel **plataforma** (mismo patrón que el 2% configurable): `semaforo_verde_hasta_dias = 35`, `semaforo_amarillo_hasta_dias = 60`. Rojo = más allá del amarillo.
- Feature flag `dashboard_consultas_bot_habilitado = false` (plataforma).

### 2.4 Criterio de cierre de Fase 1

Fase 1 termina cuando: migraciones aplicadas y reversibles en dev; los endpoints del §3 devuelven datos reales correctos para una organización de prueba; tests de aislamiento de tenant sobre cada endpoint (un admin de la org A jamás recibe datos de la org B, ni por manipulación de query params); y Sd recibió un resumen del gap real encontrado vs. este documento.

---

## 3. Contrato de API (Fase 1)

Prefijo sugerido: `/api/org/dashboard/…` (ajustar al convenio de rutas del repo). Autenticación y scoping de tenant idénticos al resto de la app. **Todos los agregados se calculan en SQL**; jamás se envían registros crudos masivos al navegador.

### 3.1 Parámetros de filtro comunes (query params)

`desde`, `hasta` (ISO date, obligatorios) · `seccionales` (lista de ids, múltiple) · `empresas` (lista de ids, múltiple) · `categoria` (id) · `formato` (`viejo`|`nuevo`) · `sal_min`, `sal_max` (enteros, pesos) · `resultado` (`ok`|`con_diferencias`|`en_revision`) · `estado_tramite` (`abierto`|`en_proceso`|`resuelto`) · `tipo_notif` · `tema` (consultas). Cada endpoint ignora los parámetros que no le aplican. Validar rangos; `hasta` no puede superar hoy; rango máximo 366 días.

### 3.2 Endpoints

| Endpoint | Devuelve |
|---|---|
| `GET …/kpis` | Los 10 KPIs del §4.2 en un solo JSON, más los mismos valores del período inmediato anterior de igual longitud (para los deltas) |
| `GET …/serie-recibos` | Recibos procesados por día del rango (rellenar días sin datos con 0) |
| `GET …/validacion` | Conteo por resultado (ok / con diferencias / en revisión) |
| `GET …/diferencias-empresa` | Top 6 empresas por monto total de diferencias del período |
| `GET …/tramites-seccional` | Matriz seccional × estado con conteos |
| `GET …/notificaciones` | Totales enviadas/leídas y desglose por tipo (leídas / no leídas) |
| `GET …/formato-semana` | Recibos por formato agrupados por semana |
| `GET …/semaforo` | Por empresa del tenant: fecha de último depósito, días transcurridos y estado (verde/amarillo/rojo según umbrales de plataforma) |
| `GET …/consultas` | Conteo por tema (detrás del feature flag; si está apagado, 404) |
| `GET …/explorador/{fuente}` | Detalle paginado; ver 3.3 |

### 3.3 Explorador de datos — `GET …/explorador/{fuente}`

`fuente ∈ {recibos, tramites, consultas, notificaciones}`. Paginación **server-side**: `page`, `page_size` (default 10, máx 50), respuesta con `total`. Ordenamientos por defecto: recibos por monto de diferencia desc (solo incluye `con_diferencias` y `en_revision`); trámites, consultas y notificaciones por fecha desc.

Columnas por fuente (ver mockup):
- **recibos:** fecha, seccional, empresa, categoría, formato, bruto, diferencia, resultado, enviado al sindicato — y, **solo si `enviado = true`**, nombre y CUIL del trabajador (regla de privacidad §1.3; aplicar del lado del servidor, nunca en el frontend).
- **tramites:** número, fecha de inicio, seccional, tipo, estado, días transcurridos (para resueltos: `resuelto_en - creado_en`; para pendientes: `hoy - creado_en`, marcado "y sigue").
- **notificaciones:** agregado diario por seccional y tipo: enviadas, leídas, sin leer, tasa de lectura.
- **consultas:** fecha, seccional, tema, resuelta por el bot / derivada (tras el flag).

---

## 4. FASE 2 — Construcción del dashboard

Ruta: nueva página del panel del admin de organización (ej. `/org/dashboard`), integrada a la navegación existente. Template Jinja2 + un JS propio del dashboard + Chart.js vendoreado. Replicar el mockup `docs/dashboard-sindical.html` en estructura, jerarquía y comportamiento, con estas precisiones:

### 4.1 Theming

- Reemplazar la paleta "verde sindical" del mockup por las **variables de marca del tenant** ya existentes (primario, primario oscuro/claro, acento). El selector de tema del mockup **no se implementa**: era solo demostrativo.
- El **color destacado** (`organizacion.color_destacado`, default fucsia) se inyecta como variable CSS `--destacado` y se usa **únicamente** para: presets activos, días pintados del calendario, chips de selección múltiple activos, chips de filtros aplicados, contador de filtros, borde/resalte de segmentos y barras seleccionados en los gráficos, slider modificado, pestaña activa del explorador y botón Reiniciar. Nada más se pinta con ese color, para que "destacado = seleccionado" sea una regla visual absoluta.

### 4.2 KPIs (10 tarjetas)

Recibos analizados · % con diferencias · Monto observado ($) · Enviados al sindicato · Trámites del período · Trámites sin resolver · Notificaciones enviadas · Tasa de lectura (%) · Usuarios activos · Consultas al asistente (oculto tras el flag). Cada KPI reacciona a todos los filtros que le apliquen. "Recibos analizados" muestra delta % contra el período anterior de igual longitud. Números con formato `es-AR`.

### 4.3 Filtros

- **Período:** presets Hoy / 7 / 30 / 90 días + **calendario pintable** (click en día inicial, click en día final, rango pintado en color destacado, días futuros deshabilitados, navegación por mes). Vista inicial: **Hoy**.
- **Seccionales:** chips de selección múltiple (catálogo del tenant).
- **Empresas:** chips de selección múltiple. Si el tenant tiene más de ~12 empresas, degradar a un multiselect con buscador (decidir según datos reales; consultar a Sd si hay dudas).
- **Categoría (CCT):** select simple.
- **Formato de recibo:** segmentado Todos / Anterior / Ley 27.802.
- **Remuneración bruta:** slider de doble manija; límites min/max calculados del tenant (percentiles 1 y 99 redondeados), no hardcodeados.
- **Chips de filtros activos** removibles uno a uno + **botón Reiniciar** que vuelve todo al estado inicial (Hoy, sin filtros, pestaña Recibos).

### 4.4 Gráficos y cross-filtering

Igual que el mockup: línea de recibos por día; dona de resultado de validación (click en segmento filtra por resultado); barras apiladas de trámites por seccional × estado (click en segmento filtra seccional **y** estado a la vez; click en leyenda filtra solo estado; lo no seleccionado se atenúa y lo seleccionado lleva borde destacado); barras de notificaciones leídas/no leídas por tipo con 3 tarjetas resumen (click filtra tipo); top 6 empresas por diferencias (click suma/quita empresa al filtro); consultas por tema (tras el flag); barras apiladas de adopción de formato por semana; semáforo de aportes con resumen verde/amarillo/rojo y lista por empresa.

Cada interacción de cross-filtering: actualiza **todos** los KPIs, gráficos y el explorador; agrega su chip removible; y **cambia automáticamente la pestaña del explorador** a la fuente correspondiente (dona/empresas → Recibos; trámites → Trámites; bot → Consultas; notificaciones → Notificaciones).

### 4.5 Explorador de datos

Pestañas Recibos / Trámites / Consultas / Notificaciones con contador de registros en vivo, tabla server-side paginada (botón "Ver más" que pide la página siguiente), columnas del §3.3, estados vacíos con mensaje accionable ("Sin registros para los filtros actuales. Probá ampliar el período o quitar filtros."). La pestaña Consultas no se renderiza si el flag está apagado.

### 4.6 Comportamiento técnico del frontend

- Un único objeto de estado de filtros; cada cambio dispara **una** ronda de fetches en paralelo (kpis + gráficos afectados + explorador) con **debounce de 250 ms** y cancelación de requests en vuelo (AbortController).
- Indicador de carga sutil por panel (atenuar el valor mientras llega el nuevo, como el "flash" del mockup); nunca bloquear toda la página.
- Manejo de errores por panel: mensaje breve + botón reintentar; un panel caído no rompe el resto.
- Responsive hasta móvil (el mockup ya lo es); foco visible en teclado; respetar `prefers-reduced-motion`.
- Estado de filtros serializado en la query string de la página, para que un enlace al dashboard filtrado sea compartible entre dirigentes.

### 4.7 Consultas al bot

Todo el carril de consultas (tabla, endpoint, panel, KPI, pestaña) se implementa completo pero **condicionado al feature flag**. Con el flag apagado no aparece nada en la UI. Así, cuando el RAG entre en producción, habilitar el panel es cambiar un booleano.

---

## 5. Criterios de aceptación (checklist del PR)

1. Fase 1 cerrada según §2.4 antes de cualquier commit de Fase 2.
2. Con la organización demo: el dashboard abre en "Hoy", y cambiar cualquier filtro o tocar cualquier gráfico actualiza KPIs, gráficos, chips y explorador de forma coherente entre sí (los totales cruzados cierran).
3. El calendario pinta rangos correctamente, incluyendo rangos que cruzan meses, y no permite fechas futuras.
4. Reiniciar deja el tablero idéntico al estado inicial.
5. Regla de privacidad verificada por test: un recibo no enviado jamás expone nombre/CUIL en ninguna respuesta de API.
6. Test de aislamiento de tenant en todos los endpoints nuevos.
7. Todos los endpoints de agregados responden en menos de 1 s con un tenant de 50.000 recibos (sembrar datos sintéticos en dev para medirlo; documentar el resultado en el PR).
8. Sin Chart.js por CDN: assets vendoreados, con `Cache-Control` versionado como se hizo con los logos.
9. Colores: marca del tenant + `--destacado` según §4.1; nada del mockup verde hardcodeado.
10. Documentación: actualizar `CLAUDE.md` con las rutas, endpoints y flags nuevos.

## 6. Fuera de alcance (no implementar ahora)

Exportación a PDF/Excel · alertas automáticas del semáforo · comparativa entre organizaciones · vista para el admin de plataforma más allá de lo dicho en §1.5 · edición del color destacado por el admin de organización.
