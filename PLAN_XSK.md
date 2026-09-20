# PLAN_XSK.md — XSANDERS Security Kit sobre Colm3na

Plan acordado con SDN el 2026-09-20, pregunta por pregunta, antes de tocar
código. Como los demás `PLAN_*.md`, documenta lo acordado tal cual se acordó y
**no se edita después**: el estado vigente se lleva en `CLAUDE.md` ("Estado
actual") y el avance por iteración en la página `/entornos/xsanders`.

## Qué es XSK

Un método, con sus herramientas, para llevar un sistema a un estado de
seguridad **verificado** antes de ponerlo frente a usuarios reales, y para
mantenerlo ahí. Se construye primero sobre este proyecto (Colm3na) porque es
lo que hace falta ahora, pero se escribe de modo que se pueda extraer a un
repositorio propio y aplicar a otros sistemas.

"Seguridad" acá es amplio a propósito: integridad, confiabilidad,
confidencialidad y disponibilidad de la información; suplantación de
identidad; inyección de código; vulnerabilidades de infraestructura y de la
cadena de suministro; abuso y denegación de servicio; y **protección de
datos personales** (Ley 25.326), porque en este sistema la afiliación
sindical es dato sensible por definición legal.

## Las seis decisiones cerradas

| # | Pregunta | Decisión |
|---|---|---|
| 1 | Dónde vive XSK | **Nace adentro de MITRABAJOC** (`xsk/` + skill `.claude/skills/xsk/`), separado en genérico / específico del proyecto, y se extrae a repo propio cuando el método esté probado. |
| 2 | Quién ejecuta los tests | **Claude Code es el ejecutor**: revisión de código con las mejores skills disponibles, análisis estático, tests dinámicos contra el entorno, configuración de perímetro por API. La página de `/entornos/xsanders` es el **registro y tablero**, no un botón que ataca desde adentro. Lo que Code no puede hacer honestamente (un DDoS real) no se prueba: se delega al perímetro y se verifica que el perímetro esté. |
| 3 | Para quién es el resultado | **(a) Para el equipo**, técnico y sin maquillaje. Pero cada test y cada hallazgo llevan desde el primer día la referencia al estándar (OWASP Top 10 2021, ASVS 4, CWE) para que XSK pueda ser **(c) producto** cuando esté pulido. |
| 4 | Qué se puede tocar de la infra | Plan **Pro de Render como piso**, dominio propio, **Cloudflare si hace falta**, y Pruebas/Demo se pueden subir de plan para los tests de carga. |
| 5 | Alcance legal | **(b)** Seguridad técnica **más un eje de Protección de datos** (Ley 25.326): clasificación, mapa de datos sensibles, retención, derechos del afiliado, y la división de responsabilidades plataforma / sindicato. |
| 6 | Horizonte | **(a) Sindicato real cercano**: la iteración 1 cubre lo que bloquea salir; el resto sigue iterativo con la plataforma en uso. Los tests dinámicos corren contra **Pruebas y Demo** (hoy Demo es copia de Pruebas). |

## Las cuatro piezas que la propuesta original no tenía

1. **Modelo de amenazas explícito** entre mapear (etapa 2) y acotar (etapa
   3): quién atacaría, qué activo busca, por dónde entra. Todo test se
   conecta a un activo; un test que no se conecta a ninguno no existe.
2. **Criterio de salida**: ningún hallazgo Alto o Crítico abierto; los
   Medios con dueño y fecha; los aceptados con motivo y firma.
3. **Regresión**: cada corrección deja un test automático; una
   re-ejecución confirma cerrados y detecta reabiertos.
4. **La seguridad del kit**: XSK maneja credenciales y hallazgos que son un
   manual de ataque hasta que se corrigen. Lo sensible vive en `.env`,
   nunca en los archivos del registro; la página va detrás del PIN de
   Entornos **hasta que ese PIN sea él mismo un hallazgo corregido**.

## Las diez etapas

| Etapa | Nombre | Sale |
|---|---|---|
| 0 | Configuración | qué datos necesita el método y dónde viven (`configuracion.md`) |
| 1 | Relevamiento | objeto del sistema, organización, activos (`relevamiento.md`) |
| 2 | Mapeo + modelo de amenazas | superficie técnica generada del código; amenazas por activo (`mapa.md`, `amenazas.md`) |
| 3 | Alcance | qué ejes entran en esta iteración y por qué (`alcance.md`) |
| 4 | Herramientas | qué skill, qué análisis, qué herramienta por test (en el catálogo) |
| 5 | Ejecución | batería por eje, en pasos; cada corrida deja un archivo (`corridas/`) |
| 6 | Registro | un archivo por hallazgo (`hallazgos/H-NNNN.md`) |
| 7 | Clasificación | probabilidad × daño, complejidad; ranking |
| 8 | Corrección | una rama `fix/xsk-H-NNNN` por hallazgo, con su test de regresión |
| 9 | Registro continuo | página `/entornos/xsanders`: avance, ranking, corridas, cómo seguir |

El detalle de cada etapa, la escala de riesgo y el criterio de salida están
en `xsk/METODO.md` (genérico, es lo que se extrae).

## Los nueve ejes

| Sigla | Eje | Cubre |
|---|---|---|
| IDS | Identidad y sesiones | logins, fuerza bruta, cookies, expiración, cambio de clave, cuenta única de plataforma |
| AUT | Autorización y aislamiento | multi-tenant, los tres roles del sindicato, `PERMISOS_RUTAS`, IDOR |
| ENT | Entradas | inyección SQL/Jinja, XSS, CSRF, archivos subidos y cómo se sirven |
| IA | Superficie de la IA | prompt injection vía documento, costo/abuso de la API, qué viaja a Anthropic |
| DAT | Datos y criptografía | secretos, hashing, backups, qué se loguea, retención |
| DIS | Disponibilidad y abuso | rate limiting, cupos, DoS por CPU (PDF), perímetro |
| INF | Infra y cadena de suministro | Render, GitHub, dependencias, Docker, CI |
| OBS | Detección y respuesta | qué se ve en Sentry/Grafana ante un ataque, runbook de incidente |
| LEY | Protección de datos | Ley 25.326: clasificación, consentimiento, derechos, plataforma vs sindicato |

## Estructura

```
xsk/
  METODO.md              genérico: etapas, escala de riesgo, criterio de salida
  catalogo/              genérico: un archivo por test (id, eje, estándar, cómo se corre)
  motor/                 genérico: leer catálogo y hallazgos, calcular riesgo, armar ranking
  proyectos/mitrabajo/   específico: configuración, relevamiento, amenazas, alcance,
                         hallazgos/, corridas/
.claude/skills/xsk/      la skill que guía a Code por las etapas
```

Todo es Markdown con cabecera `clave: valor` (sin dependencia nueva); la
página de `/entornos/xsanders` es un lector de esa carpeta. Hallazgos y
corridas son **archivos en el repo, no tablas**: versionados, revisables en
un PR, portables cuando XSK se extraiga, sin migraciones.

## Plan de ejecución por bloques

- **Bloque 0 — Cimientos.** Este plan, `xsk/`, `METODO.md`, la skill, la
  etapa 0. Termina con SDN validando el método en papel.
- **Bloque 1 — Relevamiento y mapeo (etapas 1–2).** Preguntas de objeto del
  sistema (de a una), mapa técnico generado del código, modelo de amenazas
  por activo.
- **Bloque 2 — Alcance y herramientas (etapas 3–4) + página.** Catálogo de
  los nueve ejes (aunque la iteración 1 corra cuatro), herramientas
  instaladas, y `/entornos/xsanders` **antes** de correr nada.
- **Bloque 3 — Batería de la iteración 1 (etapas 5–7).** Un eje por
  sub-bloque: IDS, AUT, DAT, INF/DIS. Revisión de código + estático +
  dinámico → hallazgos → clasificación → ranking.
- **Bloque 4 — Correcciones (etapa 8).** Por orden del ranking, una rama
  por hallazgo con su test de regresión; incluye el perímetro (Cloudflare
  delante del dominio propio).
- **Bloque 5 — Cierre de iteración (etapa 9).** Re-ejecución completa,
  verificación de cerrados, informe interno, propuesta de iteración 2
  (ENT, IA, OBS, LEY).

## Hipótesis a verificar en el bloque 1 (no son hallazgos hasta probarse)

- El PIN de `/entornos` tiene su valor por defecto escrito en `entorno.py`.
- La pestaña "Cambiar clave" de plataforma sigue activa (ya figura en
  Pendientes de `CLAUDE.md`).
- Si los tres logins tienen o no límite de intentos.
- Si hay protección CSRF sobre las cookies de sesión.
- Si un SVG subido como logo se sirve inline (XSS almacenado).
- Si el extractor está expuesto a instrucciones escondidas en un recibo.
