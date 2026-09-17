# INDICE.md — Dónde está cada cosa de Colm3na

Mapa único de fuentes. Si algo no está acá, no existe o hay que agregarlo.
Se actualiza cuando aparece una fuente nueva (chat, artefacto, documento,
cuenta), no en cada commit.

**Regla de tres niveles** (en este orden):

1. **Repo `snavello/MITRABAJOC`, rama `main`** — la verdad. Código, planes,
   decisiones vigentes, historial técnico, bitácora.
2. **Landing `/entornos` → Recursos** (Pruebas, con PIN) — lo que el equipo
   y el sindicato leen sin abrir GitHub. Todo lo que está acá es una copia
   publicada de algo del repo o subido desde la landing.
3. **Proyecto Claude "Mitrabajo"** — donde se piensa: chats, artefactos,
   memoria. Lo que se decide acá **se baja al repo** (regla de cierre en
   `OPERATIVA.md`); si no se bajó, no cuenta.

---

## 1. Documentos del repo

### Leer primero (en este orden, quien se incorpora)

| Archivo | Qué es | Cuándo leerlo |
|---|---|---|
| `README.md` | Qué es la plataforma, stack, cómo correrla en tu PC. | Día 1. |
| `CLAUDE.md` | Contexto vivo para Claude Code: arquitectura, roles, decisiones vigentes, **"Estado actual"**, pendientes, método, comandos. Se carga en cada sesión de Code. | Día 1 y antes de cada bloque. |
| `FLUJO.md` | Ciclo de una feature: PC → `main` (Pruebas) → `promover_demo.py` (Demo). Las tres reglas que no se rompen. | Antes del primer commit. |
| `BITACORA.md` | Qué se hizo cada día, con qué herramienta y dónde está. | Para ubicar cualquier cosa en el tiempo. |
| `docs/OPERATIVA.md` | Cómo trabajamos con Chat, Code y Cowork; cierre de bloque; commits; chats. | Día 1. |

### Estado y decisiones

| Archivo | Qué es |
|---|---|
| `HISTORIAL.md` | Changelog técnico por bloque (79 secciones fechadas): el porqué de cada decisión, bugs y su causa real. No se carga automático en Code; se abre por sección. |
| `BACKLOG.md` | Hallazgos y pedidos laterales para no desviar el bloque en curso. |
| `ESTADO_DEL_PROYECTO.md` | **Congelado (ago 2026).** Se conserva como historia. |
| `docs/ASISTENTE_PANEL.md` | Ficha rectora del Asistente del Panel Sindical (se actualiza esta ficha, no otra). |
| `docs/DASHBOARD.md` | Especificación funcional y técnica del Panel Sindical. |
| `docs/cct-1875-bancarios.md` | Lo que la simulación usa del CCT 18/75. |

### Planes y sprints (documentan el plan **tal cual se acordó**, no se actualizan; el avance va en `CLAUDE.md`)

| Archivo | Tema | Fecha |
|---|---|---|
| `SPRINT_REFORMA.md` | Reforma laboral (Ley 27.802): Sprints A y B. | 2026-08-05 |
| `PLAN_RAG_CONVENIO.md` | Piloto de consultas sobre el convenio. | 2026-08-23 |
| `GUIA_CODE_REDISENO.md` | Guía para ejecutar el rediseño con Code (prompts en lenguaje natural). | 2026-08 |
| `PLAN_ENTORNOS.md` | Entornos (Desarrollo/Pruebas/Demo/Prod) y traspaso a un equipo. | 2026-09-03 |
| `DESPLIEGUE_RENDER.md` | Los dos servicios de Render, variables, regenerar datos. | 2026-09-03 |
| `SPRINT_AREAS_V2.md` | Áreas, permisos granulares y ruteo de trámites. | 2026-09-11 |
| `SPRINT_ENCUESTAS.md` | Módulo Encuestas. | 2026-09-11 |
| `PLAN_MOTOR_V2.md` | Motor de análisis de recibos v2 (7 bloques, bandera `MOTOR_V2`). Borrador, sin código escrito. | 2026-09-14 |

### Carpetas

| Carpeta | Qué hay |
|---|---|
| `docs/chat/` | Documentos que salen de Chat y Cowork, con prefijo de fecha (`AAAA-MM-DD-tema.md`). Ver `OPERATIVA.md`. |
| `docs/generador/` | Genera `recursos/documentacion-tecnica.html` desde el código. |
| `docs/capturas-georef/` | Capturas de las pantallas de georreferenciación. |
| `recursos/` | Documentos publicados en `/entornos` (HTML + miniatura), registrados en `recursos.SEMILLA`. |
| `carga/` | Test de estrés: `INFORME.md`, experimentos, scripts. |
| `e2e/` | Robots Playwright (`README.md`). |
| `migrations/` | Alembic. |
| `.claude/skills/` | `diseno-mi-trabajo` (sistema de diseño) y `frontend-design`. |

## 2. Recursos publicados en `/entornos` (Pruebas, con PIN)

`https://mitrabajo-pruebas.onrender.com/entornos#recursos`. El PIN está en
la variable `PIN_ENTORNOS` de Render (Pruebas); quien lo necesite lo pide
a SDN. **No se escribe en ningún documento.**

| Recurso | Origen |
|---|---|
| Bitácora del proyecto | `recursos/bitacora.html` ← `generar_bitacora.py` ← `BITACORA.md` |
| Motor de recibos: de la foto al veredicto | `recursos/motor-recibos.html` |
| Anexo Servicios Mensuales | `recursos/anexo-servicios-mensuales.html` |
| Documentación técnica (generada del código) | `recursos/documentacion-tecnica.html` |
| Plan Maestro Colm3na | `recursos/colm3na-plan-maestro.html` |
| Plan de implementación en el sindicato | `recursos/colm3na-plan-implementacion-sindicato.html` |
| Video "Recibos y Trámites" | `recursos/mi-trabajo-recibos-tramites.mp4` |

## 3. Proyecto Claude "Mitrabajo"

### Conocimiento del proyecto (archivos cargados)

| Archivo | Qué es | Espejo en el repo |
|---|---|---|
| `claude_estrategia-no-afiliados-v1.md` | Informe "Del afiliado al trabajador del rubro" v1 (2026-09-02). | pendiente → `docs/chat/2026-09-02-estrategia-no-afiliados.md` |
| `claude_motor-recibos-evaluacion-v1.md` | Evaluación del motor de recibos v1.1 (2026-09-03). | `recursos/motor-recibos.html` |
| `claude_plan-implementacion-v1.md` | Resumen del plan de implementación (2026-09-04). | `recursos/colm3na-plan-implementacion-sindicato.html` |
| `claude_plan-maestro-v1.md` | Resumen del Plan Maestro v1.2 (2026-09-06). | `recursos/colm3na-plan-maestro.html` |
| `claude_plan-motor-v2.md` | Plan del motor v2 (2026-09-14). | `PLAN_MOTOR_V2.md` |

### Artefactos vivos (con estado compartido)

| Artefacto | Para qué | Link |
|---|---|---|
| Implementación La Bancaria | Plan en 5 etapas, 66 tareas, formularios F1–F10. Compartible con el sindicato. | https://claude.ai/code/artifact/57838682-9097-4fee-ba39-14bd563d1553 |
| Anexo Interno Colm3na | Áreas A–H, cuentas, costos. **NO compartir fuera del equipo.** | https://claude.ai/code/artifact/efc4f3f3-839a-4d04-837c-6551dbe92e36 |
| Plan Maestro Colm3na | RACI, 11 hitos, transición SDN → ARS. Se itera sobre la misma página. | https://claude.ai/code/artifact/2ef044ec-74a6-4835-9d3b-3b3423a2bc43 |
| Motor v2 · Avance | Tablero de los 46 ítems del plan con checklist. | *(completar link)* |
| Colm3na · Mi Trabajo (presentación v3) | Presentación HTML para sindicatos. | *(completar link)* |
| Bitácora Colm3na (Claude Doc) | Espejo de `BITACORA.md` para leer desde Claude. | https://claude.ai/code/artifact/d5f13de8-bbd4-4f3b-93a0-7f32b5772c33 |

### Chats del proyecto (por fecha; el id corto es el que cita `BITACORA.md`)

| Fecha | Id | Tema | Link |
|---|---|---|---|
| 2026-08-15 | `92d657ce` | Sprint de 12 mejoras, rediseño (3 direcciones), topes SS, tokens reales, PWA/biometría. | https://claude.ai/chat/92d657ce-a50c-4612-91ab-821522475258 |
| 2026-08-18 | `932c0291` | Imágenes placeholder de Beneficios. | https://claude.ai/chat/932c0291-77b6-42b8-84c8-6f3bc770c02e |
| 2026-08-27 | `94d57ee7` | Logo La Bancaria a PNG transparente. | https://claude.ai/chat/94d57ee7-d5ff-46c9-aac6-3c8b4c679a43 |
| 2026-08-28 | `3616b140` | Migración Postgres, `CLAUDE.md` inicial, reforma laboral (Sprint A/B), RAG, costos. | https://claude.ai/chat/3616b140-25ca-4931-92ab-8ffdbd9802ce |
| 2026-08-29 | `5dc043e7` | Infraestructura: 4 entornos, HA+PITR, S3, monitoreo, doc Word. | https://claude.ai/chat/5dc043e7-8a48-4698-8a06-53a37bdb4c5b |
| 2026-08-29 | `19cb5675` | Panel Sindical: maquetas y `DASHBOARD.md`. | https://claude.ai/chat/19cb5675-5b59-486a-bbcf-339566dae509 |
| 2026-08-31 | `38663d96` | Playwright: justificación y prompt para Code. | https://claude.ai/chat/38663d96-e9f4-45be-8923-1a86021a1123 |
| 2026-09-06 | `0d713bb2` | Skills instalados en el proyecto. | https://claude.ai/chat/0d713bb2-4b26-49fe-89a2-91ad968bebd8 |
| 2026-09-09 | `09ce0f5c` | Plan de pruebas de estrés; límites de la API. | https://claude.ai/chat/09ce0f5c-c93e-4517-9290-2af841c04187 |
| 2026-09-12 | `b2591fc2` | Plugin Claude Security. | https://claude.ai/chat/b2591fc2-4ae7-499b-bd94-59e5d1f4bd42 |
| 2026-09-12 | `e0522e2b` | Contrato SaaS ATS–sindicato: auditoría, propuesta v2, informe de control. | https://claude.ai/chat/e0522e2b-49c1-4b64-82ff-685dab4fb37e |
| 2026-09-12 | `d5a67b41` | Georreferenciación de seccionales: prompt para Code. | https://claude.ai/chat/d5a67b41-22e3-4ccb-9510-99e34ee9d8e1 |
| 2026-09-15 | `95f6a9ef` | Presentación Colm3na v3 (41 capturas) + proyecto ajeno (licitaciones). | https://claude.ai/chat/95f6a9ef-5ba2-4f61-b3ea-a953b56b44c0 |
| 2026-09-17 | *(este)* | Diagnóstico y plan de orden del proyecto. | *(completar link)* |

**Chats que no aparecen acá** (informe motor v1, estrategia no afiliados,
plan motor v2, sesiones de Cowork del 4 y 6 de septiembre) se hicieron fuera
del proyecto o en Cowork. Cuando se encuentren, se **mueven al proyecto** y
se agregan a esta tabla.

## 4. Entornos y cuentas (sin secretos)

| Qué | Dónde | Detalle |
|---|---|---|
| Pruebas | `mitrabajo-pruebas.onrender.com` (sigue `main`) | `DESPLIEGUE_RENDER.md` |
| Demo | `mitrabajo.onrender.com` (sigue `demo`) | `FLUJO.md`; se promueve con `promover_demo.py` |
| Accesos de demo y prueba | `/entornos` (con PIN) y `CLAUDE.md` "Accesos de la demo" | — |
| Inventario de cuentas (GitHub, Render, Anthropic, dominio) y su titularidad | Artefacto "Anexo Interno Colm3na", área A; Plan Maestro "Titularidad de cuentas" | Plan por pasos hacia XP (Teams) |
| Variables de entorno de Render | `CLAUDE.md` "Variables de entorno"; valores solo en Render | Nunca en documentos |

## 5. Memoria del proyecto Claude

Claude (Chat y Cowork) guarda fichas del proyecto: estado de la suite,
implementación del primer sindicato, principios técnicos, forma de trabajo.
Son notas para Claude, no documentación: **si algo importa, va al repo.**
