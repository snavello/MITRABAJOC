# BITACORA.md — Colm3na

Una línea por bloque de trabajo, en orden cronológico. Es el índice para
saber **qué se hizo, con qué herramienta y dónde buscar el detalle**. No
reemplaza a `HISTORIAL.md` (el porqué técnico) ni a `CLAUDE.md` (el estado
vigente): apunta a ellos.

**Cómo se lee cada línea**

| Columna | Qué va |
|---|---|
| Fecha | Día del bloque (si abarcó varios, el último). |
| Herr. | `Code` (Claude Code), `Chat` (claude.ai), `Cowork`, `Manual` (GitHub web, Render, a mano), o combinación `Chat→Code` (se planificó en Chat y se ejecutó en Code). |
| Módulo | Área funcional o técnica que tocó. |
| Qué se hizo | Una frase. Sin narrativa. |
| Dónde | Commits (`hash` o `hash..hash`), archivos del repo, sección de `HISTORIAL.md`, id corto de chat (los links completos están en `docs/INDICE.md`), artefacto. |
| Quién | Código de persona: SDN, AKG, ARS, DOA, GCF, SCT. |

**Cómo se agrega una línea:** al cerrar cada bloque de trabajo (regla en
`CLAUDE.md`, "Bitácora y cierre de bloque"). Se agrega al final, nunca se
reordena lo anterior. Después: `python generar_bitacora.py` regenera
`recursos/bitacora.html` para la landing `/entornos`.

---

## 2026-07 — Nace el validador

| Fecha | Herr. | Módulo | Qué se hizo | Dónde | Quién |
|---|---|---|---|---|---|
| 2026-07-27 | Chat | Base | Primera versión en GitHub: validador de recibos de un solo sindicato (FastAPI + Jinja2 + SQLite + Claude API), deploy en Render. | `45050bc` | SDN |
| 2026-07-29 | Chat | Plataforma | Versión "Plataforma multi-sindicato": tres roles (plataforma, sindicato, trabajador), aislamiento por `sindicato_id`, arreglos de login y cuenta del trabajador. | `f7e04dd..3c731ca` | SDN |

## 2026-08 — De la app al producto

| Fecha | Herr. | Módulo | Qué se hizo | Dónde | Quién |
|---|---|---|---|---|---|
| 2026-08-02 | Chat | Plataforma | Sprint de 12 mejoras: CUIT/CUIL como identidad de todos, pestañas navegables, ABM completo de trabajadores, baja lógica, logo por sindicato, fix de aislamiento de fórmulas. | `5cd5c18`; chat `92d657ce` | SDN |
| 2026-08-04 | Chat + Manual | Datos | Migración SQLite → Postgres con Alembic, desplegada en Render; cuatro archivos editados en GitHub web por divergencia local/remoto. | `e67ae96`; chat `3616b140` | SDN |
| 2026-08-05 | Chat→Code | Reforma laboral | Nace `CLAUDE.md`. Sprint A de la reforma (Ley 27.802): extractor bi-formato, tope sindical 2 %, alerta de último depósito. | `4ae501c..0a14313`; `SPRINT_REFORMA.md`; chat `3616b140` | SDN |
| 2026-08-07 | Code | Reforma / Recibo | Sprint B: Capacitación, preview del formato nuevo, envío voluntario al sindicato. Historial de recibos, totales, filtros en Reportes y Trabajadores. | `0f5437a..c3948f8` | SDN |
| 2026-08-10 | Code | Credencial / Conceptos | Credencial v2 (filigrana, vigencia, N°, QR). Conceptos por CUIT de empleador, fórmulas con vigencia histórica, marca de plataforma editable. | `3575752..49df3df` | SDN |
| 2026-08-11 | Code | Motor | La IA identifica aportes de ley por línea (red de seguridad + autoalta); fixes de base remunerativa y códigos genéricos. | `4ef98f8..e743d0a` | SDN |
| 2026-08-12 | Chat→Code | Rediseño / Noticias / IA | Skill `frontend-design` + sistema de diseño de 4 colores (`marca.css`). Módulo Noticias. `UsoIA` registra tokens reales de cada llamada. | `771b2ab..5b8b409`; chat `92d657ce` | SDN |
| 2026-08-13 | Code | Beneficios / Seccionales | Releases 0.02–0.03: carrusel de Beneficios, Seccionales, destino por seccional, alerta de posible adulteración. | `74afd17..22dca60` | SDN |
| 2026-08-14 | Code | Módulos / Notificaciones / Trámites | Fases 1–3: módulos habilitables por sindicato, Notificaciones dirigidas, Trámites con expediente. Release 0.04.02. | `5b034dd..91ceb46`; HISTORIAL "Módulos habilitables", "Notificaciones", "Trámites" | SDN |
| 2026-08-15 | Chat→Code | Rediseño "Nike" / Topes SS | Fases A–D del rediseño (condensada, grano, vidrio). Topes de base imponible Fases 1–4 con datos 2022–2026 (rama `topes-base-imponible`, mergeada). | `dad9455..9ab714b`; HISTORIAL "Topes de base imponible"; chat `92d657ce` (TopeSS_*.md) | SDN |
| 2026-08-16 | Code | Portadas / Auth / Local | Portadas de `/admin` y `/plataforma`; cookie de sesión por rol; Postgres local con Docker; constructor visual de Trámites; perfil del trabajador con foto; ayuda contextual. | `665fd5d..861ad2f`; HISTORIAL "Auth", "Portada", "Constructor visual" | SDN |
| 2026-08-17 | Code | Empleadores | Empleadores Fases 1–5: modelo, CRUD, login de empresa, notificaciones y trámites externos. Pulido visual. | `c42643c..58d9318`; HISTORIAL "Empleadores" | SDN |
| 2026-08-18 | Code + Chat | Empleadores / Beneficios | Fase 6 y merge de `empleadores`; portada `/empresa`. 27 imágenes placeholder de beneficios (9 rubros × 3). | `f7fedc5..5620c3a`; chat `932c0291` | SDN |
| 2026-08-19 | Code | Trámites | Chat de Trámites estilo WhatsApp en trabajador, empresa y admin. | `7ca0364`; HISTORIAL "Chat de Trámites" | SDN |
| 2026-08-22 | Code | Documentación / Áreas v1 | `CLAUDE.md` corto + `HISTORIAL.md` como changelog técnico. Áreas y permisos v1 (rama `areas-permisos`, **no mergeada, superada por V2**). | `5705627..90a38f0`; rama `areas-permisos` | SDN |
| 2026-08-23 | Chat→Code | RAG convenio | Plan del piloto en Chat → bloques 1–4 en Code (pgvector, carga y troceo, consulta con barandas, pantalla). Merge `rag-convenio`. | `a92efbb..85ff789`; `PLAN_RAG_CONVENIO.md`; chat `3616b140` | SDN |
| 2026-08-24 | Code | PWA | App del trabajador instalable: manifest, ícono, banner y link fijo. | `f44acfd..7a26f9b`; HISTORIAL "PWA" | SDN |
| 2026-08-25 | Code | Marca | Ícono oficial de Colm3na y logo de plataforma claro/oscuro. | `777b1f9`, `e6722ff` | SDN |
| 2026-08-26 | Code | Errores | Códigos de error propios (`errores.py`); fix del 500 que mentía. | `b2cfaf2`; HISTORIAL "No pudimos verificar" | SDN |
| 2026-08-27 | Chat | Marca | Logo de La Bancaria a PNG con fondo transparente (blanco y color). | chat `94d57ee7` | SDN |
| 2026-08-28 | Chat | Infra / Costos | Decisiones de infraestructura: 4 entornos separados, HA + PITR en prod desde el día uno, backups a S3, UptimeRobot + Sentry. Doc Word técnico/funcional/financiero con 3 diagramas. **El `INFRAESTRUCTURA.md` de ese chat no está en el repo**; su contenido vive hoy en `PLAN_ENTORNOS.md`, `DESPLIEGUE_RENDER.md` y el Anexo Servicios Mensuales. | chat `5dc043e7` | SDN |
| 2026-08-29 | Chat→Code | Panel Sindical | Spec `DASHBOARD.md` + prompt (Chat) → Fases 1–2 del dashboard en Code, merge `feature/dashboard-sindical`. Lote sintético UOM. Nace `BACKLOG.md`. | `20ddf30..20dd5e1`; `docs/DASHBOARD.md`; chat `19cb5675` | SDN |
| 2026-08-31 | Chat→Code | Panel / E2E / La Bancaria | Ajustes del dashboard; Playwright (`e2e/`) con robots de trámite; lote La Bancaria CCT 18/75 con conceptos universales. v0.20.27. | `a7c9a07..5ce827d`; `e2e/README.md`; chat `38663d96` | SDN |

## 2026-09 — Hacia el primer sindicato

| Fecha | Herr. | Módulo | Qué se hizo | Dónde | Quién |
|---|---|---|---|---|---|
| 2026-09-01 | Code | Trámites | Validaciones Fase 1 (fija + consistencia), formulario adjunto en el chat, "para iniciar" en Noticias/Beneficios/Notificaciones, trámites encadenados. v0.21–0.25. | `03ed284..a204048`; HISTORIAL 2026-09-01 (5 secciones) | SDN |
| 2026-09-02 | Chat + Code | Logins / Push / Estrategia | Rediseño de los 4 logins (credencial viva); bandeja de notificaciones; Web Push a la PWA (v0.26). Informe "Del afiliado al trabajador del rubro" v1 (programa Puerta Abierta). | `4137226..debe7ae`; proyecto `claude_estrategia-no-afiliados-v1.md` | SDN |
| 2026-09-03 | Chat→Code | Hilo / Entornos / Motor | Esquema "Hilo" en toda la suite (v0.27). `PLAN_ENTORNOS.md` + Etapa 0: `promover_demo.py`, `FLUJO.md`, distintivo de entorno, Pruebas y Demo separados. **Primera promoción a demo** (tags `demo-2026-09-03-v0.28.0x`). Informe "El motor de análisis de recibos" v1.1. | `8f0eb63..8a56baa`; `FLUJO.md`; proyecto `claude_motor-recibos-evaluacion-v1.md` | SDN |
| 2026-09-04 | Cowork | Implementación | Contrato firmado con La Bancaria. Artefactos "Implementación La Bancaria" (5 etapas, 66 tareas, F1–F10) y "Anexo Interno Colm3na" (áreas A–H, cuentas, costos). | artefactos `57838682`, `efc4f3f3`; proyecto `claude_plan-implementacion-v1.md` | SDN |
| 2026-09-05 | Code | Credencial / Asistente | QR efímero de 10 min; Asistente del Panel Sindical Bloques 1–7 (v0.29). **Última promoción a demo hasta hoy** (`b2f2dd0`). | `b44e7fb..cefea10`; `docs/ASISTENTE_PANEL.md` | SDN |
| 2026-09-06 | Cowork | Plan Maestro | Artefacto "Plan Maestro Colm3na" v1.2: equipo con RACI, 11 hitos (11-sep → 11-dic), transición SDN → ARS, titularidad de cuentas a XP por pasos. | artefacto `2ef044ec`; proyecto `claude_plan-maestro-v1.md`; `recursos/colm3na-plan-maestro.html` | SDN |
| 2026-09-07 | Code | /entornos / Recursos | Landing `/entornos` con PIN, 8 accesos y `/api/version`; Recursos (catálogo con miniaturas); documentación técnica generada del código; Anexo Servicios Mensuales; docs al día. | `15b70bf..b532995`; `recursos/`, `recursos.py` | SDN |
| 2026-09-10 | Chat→Code | Estrés | Plan de estrés (Chat) → `MOCK_EXTRACTOR`, `carga/`, pestañas Tests y Actividad en `/entornos`, 8 experimentos con informe, llamada a la IA en hilo aparte. | `8e9f496..7802f37`; `carga/INFORME.md`; chat `09ce0f5c` | SDN |
| 2026-09-11 | Code | Planes Render / Áreas V2 / Hora / Encuestas | Solapa Planes (subir/bajar planes de Render). Áreas V2 Fases 0–6 (portado sobre main, merge). Hora de Buenos Aires en toda la app. Plan y Fase 0 de Encuestas. Docs: MITRABAJOC repo único. | `2a69e90..6404fdb`; `SPRINT_AREAS_V2.md`, `SPRINT_ENCUESTAS.md`; HISTORIAL "Áreas V2", "La hora de Buenos Aires" | SDN |
| 2026-09-12 | Chat→Code | Encuestas / Georef / Suite / Contrato | Encuestas Fases 1–6 + filtros asociativos. Suite de tests a Postgres. Prompt de georreferenciación (Chat) → `geo.py`, alta guiada, mapa del panel, "cerca de mí" (PR #2, #3). 15 columnas json → jsonb. Propuesta de contrato SaaS v2 + informe de control (Chat). Plugin Claude Security evaluado. | `ed9f682..a908023`; HISTORIAL "Encuestas", "Georreferenciación"; chats `d5a67b41`, `e0522e2b`, `b2591fc2` | SDN |
| 2026-09-13 | Code | Panel / Encabezado / Costo IA / Motor | El panel dice lo que un rol no puede (PR fix/panel-avisos). Mapa de burbujas en Encuestas (PR #4). Fecha del panel por el servidor (PR #5). Encabezado único de las 4 apps. **"Mi Trabajo" sale de la interfaz: la plataforma es Colm3na.** Costo USD por llamada + modelo desde el panel. Banco de pruebas línea por línea. Informe del motor a Recursos. Flujo del recibo rediseñado. | `7000052..1fea926`; HISTORIAL 2026-09-13 (7 secciones) | SDN |
| 2026-09-14 | Chat→Code | Motor v2 / Recibo | `PLAN_MOTOR_V2.md` entra al repo (borrador, sin código) y a pendientes de `CLAUDE.md`. Tablero "Motor v2 · Avance" (artefacto, 46 ítems). Fix del signo en topes; flujo del recibo encuadrado; recibo ajeno frena antes de leerse. | `54c82d6..3e203a5`; `PLAN_MOTOR_V2.md`; proyecto `claude_plan-motor-v2.md` | SDN |
| 2026-09-15 | Chat→Code | Presentación | Presentación Colm3na para sindicatos, versión 3 (Encuestas, Trámites ampliado, permisos, credencial, flujo del recibo): 41 capturas tomadas por Code en Pruebas. | chat `95f6a9ef`; artefacto "Colm3na · Mi Trabajo" | SDN |
| 2026-09-17 | Chat | Orden del proyecto | Diagnóstico de fuentes dispersas y plan de orden: nace esta bitácora, `docs/INDICE.md`, `docs/OPERATIVA.md`, `docs/chat/` y `generar_bitacora.py`. Decisiones: repo manda, una línea por bloque, nombre canónico Colm3na, commits con Co-authored-by, ramas sin tocar por ahora. | este bloque; `docs/OPERATIVA.md` | SDN |
| 2026-09-17 | Code | Orden del proyecto | Merge a `main` del bundle con la bitácora y la documentación de orden, verificado antes de traerlo. | `c6c5628`; `CLAUDE.md` "Bitácora y cierre de bloque" | SDN |
| 2026-09-19 | Cowork | Panel Sindical / Infra | Cuelgue de Pruebas del 18-sep reconstruido desde el código: sesiones anidadas en `dashboard.py` (dos conexiones por request con filtro de empresa/afiliado) + pool de 10 sin timeout + 13 requests por refresco + threadpool compartido. Plan de 8 correcciones (C1–C8) con criterios de aceptación y prompt para Code en dos fases. Observabilidad queda como bloque aparte. | docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md; docs/chat/2026-09-19-prompt-code-cuelgue-dashboard.md | SDN |
| 2026-09-19 | Code | Panel Sindical / Infra | Cuelgue de Pruebas del 18-sep corregido en la rama `fix/panel-conexiones`: una conexión por request (`permisos_efectivos` anidaba dos en cada ruta `/admin/*`, hallazgo nuevo de la auditoría), techos del engine y 503 en vez de cuelgue, cupo de 4 del panel, front en cola de a 4, test de regresión (240/240 en 200; antes 228 excepciones), `/healthz` y `/readyz`, escenario k6 `test3_panel.js` (sin correr) y runbook. Falta cargar `/healthz` como Health Check Path en Render y correr el test 3. | 87d836e..6b1cdb0; db.py, dashboard.py, main.py, static/dashboard.js, errores.py, migrations/env.py, carga/k6/test3_panel.js; HISTORIAL.md "El cuelgue del Panel Sindical en Pruebas"; docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md | SDN |
| 2026-09-19 | Code | Panel Sindical / Infra | PR #6 mergeado y desplegado en Pruebas. `/healthz` cargado como Health Check Path en Pruebas por la API de Render (demo queda para después de promover). Test k6 `test3_panel.js` corrido contra Pruebas: APROBADO (360 pedidos del panel, 0 respuestas 500, p95 tormenta/base 0,95). La primera corrida dio un APROBADO falso por un defecto del script (admin sin login, tormenta no ejecutada): corregido. Instalados `gh` y `k6`. | 1dc34de..; carga/k6/test3_panel.js, carga/log/2026-09-19_test3_panel_aprobado/; HISTORIAL "Verificación en Pruebas" | SDN |
| 2026-09-19 | Code | Observabilidad | Plan de observabilidad acordado con SDN pregunta a pregunta (regla 0: el observador vive fuera de la app y de Render; A uptime, B errores con Sentry, C métricas con historia; todo gratis; avisos solo al mail de SDN, repetición cada 24 h en Pruebas). Grafana Cloud configurado por API: carpeta, punto de contacto y política anti-ruido, con `observabilidad/config.json` + `aplicar_grafana.py`. Pestaña **Observabilidad en `/entornos`** (solo Pruebas): semáforo, enlaces y formulario para cambiar el mail y el intervalo, con tokens acotados (Viewer y Editor) como variables de Render; verificada contra el Grafana real (encontró que Grafana guarda 24h como 1d). **Monitor de uptime** en Grafana (Synthetic Monitoring): `/healthz` y `/readyz` de Pruebas desde Ohio y São Paulo, con sus dos alertas (caída de app a los 3 min, de base a los 5 min; solo si fallan todas las ubicaciones), como código en `aplicar_uptime.py`; camino de aviso probado con una caída simulada (pending → firing). En curso. Arreglados los 4 tests que ya fallaban en `main` (PR #8). | PR #8; observabilidad/; docs/chat/2026-09-19-plan-observabilidad.md | SDN |
