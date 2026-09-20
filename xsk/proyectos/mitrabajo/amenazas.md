---
proyecto: mitrabajo
etapa: 2
fecha: 2026-09-20
base: relevamiento.md (activos V1-V9, actores A1-A10) + mapa.md (observaciones O1-O20)
metodo: STRIDE por activo
---

# Etapa 2 — Modelo de amenazas

Para cada activo del relevamiento: quién lo atacaría, por dónde, y qué
pasaría. Cada amenaza lleva las **observaciones del mapa** que la hacen
plausible hoy (O-n) y el **eje** del catálogo que la cubre. Una amenaza sin
observación es igual de válida: el mapa solo dice qué se vio en el código.

STRIDE: **S**uplantación, **T**ampering (alteración), **R**epudio,
**I**nformación expuesta, **D**enegación de servicio, **E**levación de
privilegios.

## V1 — Recibos y comprobantes

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| I: leer los recibos de otro afiliado | A1, A2 | forjar la cookie `cuil_trab` (sin firma) y pedir `/api/mis-recibos` | O2 | AUT |
| I: leer recibos de un sindicato entero | A4, A7 | exportaciones y explorador del panel con una sesión de admin robada; sin 2FA ni límite de intentos | O9, O8, O20 | IDS / AUT |
| I: recibos en tránsito o en reposo fuera de la app | A8, A9 | el archivo viaja completo a Anthropic; `ReciboSospechoso` guarda el archivo; backups en Render y S3 | — | DAT / LEY |
| T: escribir un recibo validado a nombre de otro | A1, A2 | `/api/validar` con `cuil_trab` forjado | O2 | AUT |
| I: ver el recibo que la persona decidió NO enviar al sindicato | A4 | fallar el CASE de `enviado_sindicato` en el SQL o en el modal | — (hay test) | AUT |
| D: gastar la IA sin ser nadie | A6 | `/api/leer` con una cookie inventada, sin tope de tamaño ni rate limit | O11 | DIS / IA |

## V2 — Integridad de lo que el sistema afirma

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| T: torcer la lectura de un recibo | A10 (vía A1–A3) | texto impreso en el recibo que instruye al modelo; sin instrucción anti-inyección en `extractor.SYSTEM` | O15 | IA |
| T: sembrar conceptos falsos en el catálogo del sindicato | A10 | los conceptos "nuevos" que devuelve el modelo se dan de alta (`pendiente_revision`) | O15 | IA |
| T: cambiar una fórmula o un tope | A4, A8 | sesión de admin robada; acceso directo a la base | O9, O20 | AUT / INF |
| T: torcer una respuesta del bot del convenio | A4 (PDF), A2 (pregunta) | delimitadores `---` falsificables, sin mitigación | O15 | IA |
| S: credencial de afiliado falsa | A1 | `/v/{token}` con `k` efímero (mitigado); alta de cuenta con CUIL ajeno en nivel 1 | R2 | IDS |
| R: no saber quién cambió qué en plataforma | A8 | cuenta de plataforma compartida, sin registro por persona | O3, R1 | IDS / OBS |

## V3 — Padrón

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| I: exfiltrar el padrón completo | A4, A7 | sesión de admin; sin 2FA, sin límite de intentos, sin revocación; CSV de encuestas nominales y explorador | O9, O20 | IDS / AUT |
| I: padrón de un sindicato desde otro | A5 | fallo de `sindicato_id` en un WHERE; `/api/entornos/actividad` público con agregados por sindicato | O14 | AUT |
| I: salir del alcance de seccional/área | A4 | ruta sin clasificar en `PERMISOS_RUTAS` (mitigado: falla cerrado); consulta que filtra después en vez de en el WHERE | — | AUT |
| I: padrón en logs y en Sentry | A8, A9 | CUIL en el path de `/perfil-foto/{cuil}`; `traceback.print_exc()` sin scrubbing | O16 | DAT / LEY |
| I: sin base legal | sindicato, AAIP | sin disclaimer, sin retención definida, sin contrato de encargado | R4–R6 | LEY |

## V4 — Disponibilidad y crédito de IA

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| D: tirar el web con uploads grandes | A6 | `_leer_logo` sin tope; `/api/leer` sin tope; conversión de PDF en CPU | O12, O11 | DIS |
| D: agotar el pool o el cupo | A6 | muchos requests al panel (mitigado: techos y cupo, medido con k6) | — | DIS |
| D: agotar el saldo de Anthropic | A6, A2 | `/api/leer` y `/api/aportes` sin rate limit ni tope por cuenta | O11 | DIS / IA |
| D: DDoS volumétrico | A6, A7 | no hay perímetro (Cloudflare) delante de Render | — | DIS / INF |
| D: caída en cierre de liquidación por un deploy | A8 | push a `main` redeploya Pruebas; promover a demo/prod sin ventana | — | INF |

## V5 — Aislamiento entre sindicatos

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| I/T: cruzar el tenant por un id en la URL | A5, A2 | rutas por id (`/noticia-imagen/{id}`, `/tramite-*/{id}`) que no chequeen el sindicato de la sesión | — | AUT |
| I: trabajador pluriempleo viendo el sindicato equivocado | A2 | `/app/elegir/{sindicato_id}` fija `sind_elegido` sin validar pertenencia | O2 (1.1 #19) | AUT |
| I: contenido de un sindicato ejecutando en otro | A4 | SVG con script en `/logo/{id}`, público y sin CSP: un logo malicioso de un sindicato corre en el origen compartido | O5, O7 | ENT |

## V6 — Identidad de cada usuario

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| S: registrarse como otro | A1 | alta nivel 1: solo CUIL en el padrón | R2 | IDS |
| S: forjar cualquier sesión | A6, A8 | `SESSION_SECRET` con default en el código; si falta la variable en un entorno, se firma con el default público | O1 | DAT / IDS |
| S: entrar a plataforma con la clave del código | A6 | `PLATAFORMA_PASSWORD` con default | O3 | IDS |
| S: fuerza bruta o credential stuffing | A6 | cuatro logins sin límite; claves de la demo = 5 primeros dígitos del CUIL en los lotes | O9 | IDS |
| S: robo de cookie en tránsito | A6 | cookies sin `Secure`; sin HSTS | O8, O7 | IDS |
| S: CSRF de logout / cambio de sindicato | A6 | GET que mutan estado; sin token | O10 | ENT |
| S: sesión que sobrevive al logout o al cambio de clave | A2, A8 | sesiones stateless sin revocación | O20, O13 | IDS |
| E: cambiar la clave de cualquiera desde plataforma | A8 | `/plataforma/reset-clave` transitorio | O13 | IDS |
| S: recuperación de clave por mail | A1 | sin proveedor ni flujo todavía; cuando exista, token predecible o sin vencimiento | R3 | IDS |

## V7 — Trámites

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| I: leer el trámite de otro | A2, A3 | `_autorizado_para_tramite` compara contra `cuil_trab` forjable | O2 | AUT |
| I: adjuntos por id | A2, A3 | `/tramite-nota-adjunto/{id}` con id enumerable si la autorización falla | O2 | AUT |
| I: un área lee trámites que no le tocan | A4 | pase entre áreas fuera de la lista cerrada; lectura del área que derivó (por diseño) | — | AUT |
| T/E: adjunto malicioso servido inline | A2, A3 | HTML/SVG en un adjunto de trámite servido `inline` sin `nosniff` ni CSP | O5, O7 | ENT |
| I: nº de expediente en un push | A9 | el cuerpo de la notificación push lleva el expediente; los servicios de push lo ven | — | LEY |

## V8 — Secretos de infraestructura

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| I: secreto en el repositorio | A8, A9 | defaults en `auth.py` y `entorno.py`; `.env` en el disco de SDN; historial de git | O1, O3, O4 | DAT / INF |
| I: secreto en un tercero | A9 | `RENDER_API_KEY` guardada en Grafana (aceptado); tokens con permisos más amplios que lo necesario | — | INF |
| I: secreto que no vence ni rota | A8 | `SENTRY_AUTH_TOKEN` sin vencimiento; ex miembro del equipo con la clave de plataforma compartida | R1 | INF |
| E: acción de GitHub o dependencia comprometida | A9 | `anthropic>=` sin pinnear; sin escaneo; actions por tag mayor | O18 | INF |

## V9 — Backups

| Amenaza | Actor | Vector | Obs. | Eje |
|---|---|---|---|---|
| D: backup que no restaura | — | nunca se ensayó | R7 | INF |
| I: backup accesible | A8, A9 | bucket de S3 con permisos amplios; dump sin cifrar en la PC de quien promueve | R7 | DAT / INF |
| D: pérdida de datos por encima de lo aceptable | — | RPO no definido; backup diario vs. un día de liquidación | R8 | INF |

## Lo que este modelo dice sobre el alcance

Ordenando por el peso que SDN le dio a los activos (V1 > V2 > V3 > V4 > V5,
más V6 y V7), las amenazas que más se repiten son cuatro, y las cuatro caen
en los ejes de la **iteración 1**:

1. **Identidad forjable** (O2, O1, O3): cookie sin firma y secretos con
   default — cruza V1, V6, V7 y V5. Eje AUT / DAT / IDS.
2. **Logins sin defensa** (O9, O8, O20, R1): fuerza bruta, cookies sin
   `Secure`, sin revocación, cuenta compartida de plataforma. Eje IDS.
3. **Sin perímetro ni cabeceras** (O7, O11, O12): DoS barato y XSS sin
   contención. Eje DIS / ENT (las cabeceras entran en la iteración 1 aunque
   ENT sea de la 2, porque son un cambio de configuración que cubre varias
   amenazas de una).
4. **Secretos y cadena de suministro** (O1, O3, O4, O18, R7): eje DAT / INF.

Quedan para la **iteración 2**: la superficie de la IA (O15, V2), las
entradas (O5, O6, O10), detección y respuesta (R9), y protección de datos
(R4–R6, O16, O19) — con la salvedad de que **R2 (niveles de registro) es
una decisión de producto que conviene diseñar antes del primer sindicato**,
aunque su implementación entre después.
