---
proyecto: mitrabajo
etapa: 1
fecha: 2026-09-20
con: SDN
metodo: seis preguntas de a una, más CLAUDE.md y la documentación del proyecto
---

# Etapa 1 — Relevamiento

## Objeto del sistema

Colm3na es una plataforma web multi-sindicato. Un trabajador afiliado sube su
recibo de sueldo (foto o PDF), una IA lo lee y el sistema verifica que los
aportes (jubilación, obra social, cuota sindical) estén bien calculados
según el convenio de su sindicato. Alrededor de eso: credencial digital,
semáforo de aportes con comprobantes de ARCA, noticias, beneficios,
notificaciones, trámites con el gremio, encuestas, consultas al convenio; y
para el sindicato, un panel con el padrón, los recibos que los afiliados
decidieron compartir, los trámites, y un tablero de gestión. Un cuarto actor,
el empleador, recibe notificaciones y trámites del sindicato.

Objetivo comercial: venderla a sindicatos y mostrarla a un inversor como
algo escalable. Horizonte: **un primer sindicato real cercano**.

## Organización (como va a ser en producción)

| Rol | Persona | Acceso |
|---|---|---|
| Titular | SDN | todo: Render, GitHub, Postgres, Anthropic, Grafana, Sentry, S3, dominio, mail de alertas |
| Desarrollador | a incorporar | GitHub, Render, Postgres |
| QA e implementación | a incorporar | Pruebas y Demo; en producción, el rol de plataforma (alta de sindicatos y sus admins) |
| Admin de sindicato | uno o más por sindicato, tres roles (Super Admin, Admin de Seccional, usuario de área) | solo su sindicato / seccional / área |
| Afiliado | trabajadores del padrón | sus propios datos |
| Empleador | empresas dadas de alta por el sindicato | lo que el sindicato le dirige |

Hoy todas las cuentas están a nombre de SDN. **No hay datos reales todavía**:
Pruebas y Demo tienen datos sintéticos.

## Decisiones que salieron del relevamiento

| # | Tema | Decisión |
|---|---|---|
| R1 | Rol de plataforma en producción | **Usuarios de plataforma nominales** con roles (titular / operador), clave hasheada y registro de acciones (nivel b). Segundo factor TOTP después (nivel c). Deja de existir la cuenta compartida por variable de entorno. |
| R2 | Acreditación de identidad en el alta | **Niveles de fiabilidad de registro**, sin complejizar el alta de inicio: 1 = como hoy (CUIL en el padrón), 2 = mail confirmado, 3 = recibo propio verificado por la IA, 4 = presencial o superior. El nivel es un dato de la cuenta, visible para el sindicato. Consecuencia para el diseño: lo que la app muestra de lo que el sindicato ya sabe de la persona debería depender del nivel. |
| R3 | Recuperación de clave | Por **mail** (hoy no existe autoservicio ni proveedor de mail). |
| R4 | Responsabilidad legal (Ley 25.326) | El **sindicato es el responsable** de la base y **delega la gestión en Colm3na** (encargado del tratamiento). |
| R5 | Retención de datos | **A definir** (recibos, comprobantes, trámites cerrados, cuentas de desafiliados). Queda como hallazgo del eje LEY con dueño SDN. |
| R6 | Consentimiento | Sí: **un disclaimer por sindicato**, a redactar. |
| R7 | Backups | Hay copia diaria de Render y **copia en S3**. Nunca se ensayó una restauración (a verificar en INF). |
| R8 | Tolerancia a caída | **Una hora**, salvo mantenimiento anunciado fuera de hora pico. Pérdida de datos aceptable (RPO): a definir. |
| R9 | Guardia y aviso ante filtración | **Una persona en horario regular** mira Grafana y atiende. Fuera de ese horario, solo las alertas por mail. Quién avisa al sindicato y en cuánto tiempo: a definir (hallazgo OBS/LEY). |

## Activos, en el orden de SDN

| # | Activo | Dónde vive | Por qué importa |
|---|---|---|---|
| V1 | **Recibos de sueldo** y comprobantes de ARCA | `ReciboVerificado` (JSON `detalle` con líneas e importes), `ReciboSospechoso` (archivo completo), `AporteVerificado`; en tránsito hacia Anthropic | sueldo, CUIL, CUIT del empleador y situación laboral de cada persona; el sindicato queda expuesto frente a las empresas |
| V2 | **Integridad de lo que el sistema afirma** | fórmulas, conceptos, topes, `ReciboVerificado.diferencias`, credencial (`/v/{token}`), estado de trámites | "tu recibo está bien" cuando no, o acreditar como cotizante a quien no lo es |
| V3 | **Padrón** | `Trabajador` (nombre, CUIL, domicilio con coordenadas, seccional, afiliación), `UsuarioSindicato`, `Empleador` | la afiliación sindical es dato **sensible** por ley (art. 2, Ley 25.326) |
| V4 | **Disponibilidad y crédito de IA** | el web de Render, Postgres, `ANTHROPIC_API_KEY` y su saldo | días de liquidación; cada lectura cuesta dólares |
| V5 | **Aislamiento entre sindicatos** | `sindicato_id` en cada tabla y en cada WHERE | la promesa comercial frente al inversor |
| V6 | **Identidad de cada usuario** | cuentas, claves, cookies de sesión y de identidad | un usuario usa el de otro (agregado por SDN) |
| V7 | **Trámites** | `Tramite`, respuestas, adjuntos, chat, y sus espejos de empleador | la situación concreta de una persona frente al gremio o a su empleador, que el padrón no tiene (agregado por SDN) |
| V8 | **Secretos de infraestructura** | `SESSION_SECRET`, `PLATAFORMA_PASSWORD`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, tokens de Render/Grafana/Sentry/GitHub, credenciales de S3 | con uno de estos cae todo lo anterior |
| V9 | **Backups** | Render + S3 | la última línea de V1–V3 y V7 |

## Actores

**Legítimos**: los seis roles de la tabla de organización, más los sistemas
externos que la app llama (Anthropic, Georef, Nominatim, Render, Grafana,
Sentry, GitHub, servicios de push).

**Atacantes plausibles** (los que el modelo de amenazas usa):

| # | Actor | Qué tiene | Qué quiere |
|---|---|---|---|
| A1 | Alguien que conoce el CUIL de un afiliado (ex pareja, compañero, empleador, cualquiera con un recibo viejo) | el CUIL, dato público | registrarse antes que la persona, o entrar como ella |
| A2 | Afiliado con cuenta válida, curioso o malicioso | su sesión | ver recibos, trámites o notificaciones de otro afiliado |
| A3 | Empleador con cuenta | su sesión | ver recibos o trámites de sus empleados o de otras empresas; saber quién reclamó contra él |
| A4 | Admin de sindicato comprometido o malicioso (o usuario de área que escala) | sesión de admin | exfiltrar el padrón, salir de su alcance de seccional/área, plantar contenido malicioso (logo, noticia) que ejecute en otros usuarios |
| A5 | Otro sindicato (competencia o conflicto intersindical) | una cuenta legítima en su propio sindicato | leer datos de otro sindicato |
| A6 | Atacante externo oportunista (bots, scanners) | nada | credenciales reutilizadas, endpoints sin auth, gastar la IA, tirar el servicio |
| A7 | Atacante dirigido (anti-sindical, extorsión, prensa) | tiempo y motivación | robar el padrón y los recibos de un sindicato entero |
| A8 | Interno del equipo, presente o pasado (dev, QA, ex miembro) | accesos a Render/GitHub/DB/secretos | acceso directo a datos o a producción; error no malicioso con el mismo efecto |
| A9 | Cadena de suministro | una dependencia, una acción de GitHub, un proveedor | ejecutar código o leer datos desde adentro |
| A10 | Documento malicioso (recibo, PDF de convenio) subido por A1–A4 | texto que el modelo lee | torcer lo que la IA devuelve o inventar conceptos en el catálogo |

## Faltantes de configuración que dejó el relevamiento

- **Proveedor de mail** (R2 nivel 2, R3): no existe. Hay que elegir uno.
- **Credenciales y ubicación de la copia en S3** (R7): en `.env`, no en el
  registro; verificar que XSK pueda leer el bucket para el test de
  restauración.
- Dominio propio y cuenta de Cloudflare (ya en `configuracion.md`).
