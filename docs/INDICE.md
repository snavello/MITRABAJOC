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
| `esquema.py` + `templates/esquema.html` | La **Sala de mando**: el esquema físico de toda la solución con los indicadores vivos del entorno, en `/entornos/esquema` (Recursos lo enlaza). Narrativa en `HISTORIAL.md`, "La Sala de mando". |
| `docs/OBSERVABILIDAD.md` | Ficha rectora de la observabilidad (Grafana, Sentry, colector): cómo funciona, reglas de código, claves y vencimientos, y el procedimiento para replicar en Demo y Producción. Versión ilustrada: `recursos/observabilidad.html`. |
| `docs/ASISTENTE_PANEL.md` | Ficha rectora del Asistente del Panel Sindical (se actualiza esta ficha, no otra). |
| `docs/DASHBOARD.md` | Especificación funcional y técnica del Panel Sindical. |
| `docs/cct-1875-bancarios.md` | Lo que la simulación usa del CCT 18/75. |
| `docs/chat/2026-10-16-asistente-tramites.md` + `-contrato-importacion-tramites.md` | **Asistente de trámites** (prototipo de Chat, 2026-10-16): onboarding que convierte el pedido de un sindicato en circuito por actor, instrucción, vista previa del formulario y JSON importable `colm3na.tramite` v1; el segundo es el contrato de ese JSON y las reglas propuestas del importador (no construido). Van con el prototipo `-asistente-tramites-prototipo.html` (se abre solo en el navegador) y el ejemplo `-ejemplo-kit-escolar.colm3na.json`. |

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
| `PLAN_XSK.md` | XSANDERS Security Kit: método de seguridad en diez etapas, seis decisiones cerradas, nueve ejes, plan por bloques. El método genérico vive en `xsk/METODO.md`. | 2026-09-20 |
| `SPRINT_R1.md` | Usuarios de plataforma nominales (sub-sprint de XSK: H-0002/H-0003/H-0016). | 2026-09-20 |
| `PLAN_ENMASCARADO.md` | Paso cero del motor v2: los datos que identifican a la persona se tapan antes de salir hacia la IA. Revisión de `docs/chat/2026-08-28-arquitectura-enmascarado-pii.md`. | 2026-09-24 |
| `xsk/XSANDERS_HERRAMIENTA.md` | Blueprint agnóstico de XSK como herramienta reutilizable: método, herramientas, aprendizajes de la iteración 1 y hoja de ruta del producto. Documento vivo. | 2026-09-21 |
| `PLAN_CUIT_MOD11.md` | Validar CUIL/CUIT con el módulo 11 de AFIP (primera medida de la serie XSK): diagnóstico, conversión de los números cargados a mano y validación en las puertas de alta. Propuesta, a acordar con SDN. | 2026-10-10 |
| `PLAN_REGISTRO.md` | Registro confirmado por mail con niveles de fiabilidad (R2), recuperación de clave (R3), captcha y freno en el registro (segunda medida de la serie XSK, cierra H-0017). Acordado con SDN decisión por decisión. | 2026-10-11 |
| `PLAN_DASHBOARD_V2.md` | Panel Sindical v2 con Preact sin build, en paralelo a la v1 (`/admin/dashboard-v2`, solo local y Pruebas): primer piloto de una capa de componentes, sin tocar el backend. Acordado con SDN decisión por decisión. | 2026-10-12 |
| `PLAN_ASISTENTE_TRAMITES.md` | El Asistente de trámites como Herramienta de `/entornos` (IA que propone, motor que arma con el catálogo real, casos guardados y vista de brechas; el importador queda para después). Acordado con SDN decisión por decisión (D1–D10). | 2026-10-16 |

### Carpetas

| Carpeta | Qué hay |
|---|---|
| `docs/chat/` | Documentos que salen de Chat y Cowork, con prefijo de fecha (`AAAA-MM-DD-tema.md`). Ver `OPERATIVA.md`. |
| `docs/prompts/` | Prompts reutilizables para aplicar en OTROS proyectos con Claude Code, con lo aprendido acá. Primero: `MAPA_FUNCIONAL.md` (mapa app → funcionalidad → código, datos y servicios), publicado también como Recurso de `/entornos`. |
| `docs/generador/` | Genera `recursos/documentacion-tecnica.html` desde el código. |
| `docs/bancaria/` | Documentos de la implementación en La Bancaria: plan resumido (4 hojas A4), hoja guía de la reunión con autoridades y catálogo de trámites (`tramites-bancaria.json` con las 86 gestiones verificadas → `tramites-bancaria.html` con `generar_tramites.py`, y → `tramites-bancaria.docx` (completo) y `tramites-bancaria-resumen.docx` (6 páginas) con `generar_tramites_docx.js`). Fuente de los artifacts y de los PDF. Versiones Word para corregir (con control de cambios) generadas por `generar_docx.js`. |
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
| Instructivo de montaje: cuentas y entornos a nombre de XP | `recursos/colm3na-instructivo-montaje.html` y `.pdf` (A4, 39 páginas) ← artifact `PdD98igB` (versión 5, con la hoja C de certificados). **Interno del equipo.** |
| Plan de implementación en La Bancaria (seis fases, v0.2) | `recursos/colm3na-plan-implementacion-bancaria.html`, `.pdf` (4 hojas A4) y `-v0.2.docx` (Word editable) ← `docs/bancaria/plan-implementacion-bancaria.html` |
| Guía de la reunión con las autoridades de La Bancaria (v0.2) | `recursos/colm3na-guia-reunion-autoridades-bancaria.html`, `.pdf` (1 hoja A4) y `-v0.2.docx` (Word editable) ← `docs/bancaria/guia-reunion-autoridades-bancaria.html` |
| Trámites de La Bancaria en Colm3na: resumen (6 páginas) y catálogo completo, en Word | `recursos/colm3na-tramites-bancaria-resumen.docx` y `-completo.docx` (con miniatura) ← `docs/bancaria/generar_tramites_docx.js` ← `tramites-bancaria.json` |
| Bitácora del proyecto | `recursos/bitacora.html` ← `generar_bitacora.py` ← `BITACORA.md` |
| Motor de recibos: de la foto al veredicto | `recursos/motor-recibos.html` |
| Anatomía del análisis inteligente (caso Marina) | `recursos/anatomia-analisis-inteligente.html` ← `docs/chat/2026-09-26-anatomia-analisis-inteligente.md` |
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
| Plan de implementación La Bancaria (resumido) | Borrador v0.1, 4 hojas A4: seis fases, hitos, responsables, datos, indicadores y riesgos. Fuente: `docs/bancaria/plan-implementacion-bancaria.html`; la v0.2 está en Recursos. | https://claude.ai/artifact/JMGWcmEMgiJWQB7n3c8eNb |
| Guía de reunión La Bancaria | Hoja de una página para la reunión con las autoridades. Fuente: `docs/bancaria/guia-reunion-autoridades-bancaria.html`; la v0.2 está en Recursos. | https://claude.ai/artifact/BQoR9L61oWHGEHd6X5ttTg |
| Trámites de La Bancaria en Colm3na | Versión 2: 81 gestiones del afiliado verificadas una por una (cómo se hacen hoy, cómo las resuelve Colm3na, qué validar con el sindicato) y la propuesta de kit de inicio. Datos en `docs/bancaria/tramites-bancaria.json`; se regenera con `generar_tramites.py`. | https://claude.ai/artifact/8LPgWSNEf5swpqqmsoNfru |
| Instructivo de montaje Colm3na | Paso a paso para rearmar las cuentas y entornos a nombre de XP (AKG titular; SDN, ARS y GCF invitados). Copia en Recursos (`recursos/colm3na-instructivo-montaje.html` y `.pdf`): si cambia el artifact, volver a copiarla. **Interno del equipo.** | https://claude.ai/artifact/PdD98igBPewGzzZRCUBiKb |
| Piloto de trámites Colm3na (Asistente de trámites) | Prototipo del onboarding: relato → preguntas guiadas → circuito, instrucción, vista previa y JSON `colm3na.tramite` v1 (versión 8). Fuente en el repo: `docs/chat/2026-10-16-asistente-tramites-prototipo.html` y los tres documentos del mismo día. | https://claude.ai/artifact/BgZ441HNMwtQw2jFPsALsd |

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
