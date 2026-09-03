# PLAN_ENTORNOS.md — Entornos y traspaso del proyecto a un equipo

Propuesta escrita 2026-09-03 a partir de seis preguntas cerradas con Sd y
un ajuste posterior de escenario. Igual que `SPRINT_REFORMA.md` y
`PLAN_RAG_CONVENIO.md`: documenta el plan tal cual se acordó; el avance
real se lleva en CLAUDE.md.

## El escenario que ordena todo

- **Hoy**: Sd es el único desarrollador, el único que deploya y el único
  con acceso a Render. Un servicio web pago que sigue `main` y redeploya
  con cada push, más un Postgres pago. Esa URL `.onrender.com` es la que
  ya vieron sindicatos e inversor: es demo y pruebas al mismo tiempo, y por
  eso se retienen funcionalidades (`areas-permisos`, "Admin de Seccional",
  fases 2–4 de validaciones).
- **En ~1 mes**: dos desarrolladores más toman el control diario del
  proyecto. Sd sigue con el mismo acceso que hoy, pero trabajando en las
  ideas generales, no en el código de todos los días.
- **Al entrar en producción**: al menos USD 600/mes de infraestructura,
  para que los recursos vayan holgados.
- **Mientras tanto**: hasta ~USD 15/mes adicionales, ampliables a ~USD 30
  si se justifica.

Eso cambia el eje del plan. Ya no es "separar la demo de las pruebas"
(eso es la semana 1); es **dejar el proyecto operable por otras dos
personas en cuatro semanas, sin que Sd sea un punto único de falla**. Todo
lo que sigue está ordenado por esa meta.

Las otras decisiones ya cerradas, que se mantienen:

| # | Pregunta | Respuesta |
|---|----------|-----------|
| 1 | Plan de Render actual | Web y Postgres pagos |
| 3 | "Desarrollo sin mi PC" | Programar desde cualquier lado, ver corriendo lo que hago, base fuera de la PC |
| 4 | Datos de la DEMO | Los que hay hoy en Render, tal cual |
| 5 | Cómo se promueve a DEMO | Rama `demo` que Render sigue |
| 6 | Dominio | Solo `.onrender.com` por ahora |

## Modelo final

| Entorno | Para qué | Rama | Base | Datos | Quién |
|---------|----------|------|------|-------|-------|
| **Desarrollo** | Programar y probar en caliente | rama de feature | Postgres propio de cada dev (Codespace o Docker) | sintéticos, descartables | cada dev |
| **Pruebas** | Lo último de `main` corriendo en Render, migraciones aplicadas | `main` (auto-deploy) | Postgres pago propio | sintéticos por script | los devs, a diario |
| **Demo** | Versión estable para mostrar | `demo` (auto-deploy) | el Postgres actual, sin tocar | los de hoy, backup antes de cada promoción | promueve un dev, **aprueba Sd** |
| **Producción** | Sindicatos reales | `prod` (auto-deploy) | Postgres Pro con PITR | reales | promueve un dev, aprueba Sd |

Reglas del modelo:

1. **GitHub es el panel de control.** Un entorno cambia solo por un push a
   su rama; Render obedece. Todo queda con autor e historia, que es lo que
   un equipo necesita y una persona sola nunca extrañó.
2. **`demo` solo recibe merges desde `main`**, por Pull Request, con la
   aprobación de Sd. Nadie programa sobre `demo`. Misma regla de `demo` a
   `prod` el día que exista.
3. **`main` siempre va adelante de `demo`**: cuando una versión se
   promueve, sus migraciones ya corrieron en Pruebas. Promover nunca es la
   primera ejecución de una migración.
4. **Migraciones automáticas en el deploy** (Pre-Deploy Command de Render:
   `python -m alembic upgrade head`). Se termina el paso manual en la Shell
   y el incidente del 2026-09-01 (tres migraciones sin aplicar, "no pudimos
   cargar tus trámites") no puede repetirse.
5. **Secretos distintos por entorno**, y con el equipo, **ninguna
   credencial compartida por chat**: `SESSION_SECRET`,
   `PLATAFORMA_PASSWORD`, claves VAPID, y una `ANTHROPIC_API_KEY` por
   entorno (Workspaces de la consola de Anthropic: gasto separado, tope
   por workspace, revocación sin tumbar los demás).
6. **La app sabe dónde corre** (`ENTORNO=local|pruebas|demo|prod`).
   Local y pruebas muestran un distintivo visible con versión y entorno;
   demo y prod, nada. La pestaña "Cambiar clave" de plataforma (pendiente
   #2 de CLAUDE.md) queda gateada a `ENTORNO != prod` hasta eliminarla.
7. **Sd conserva todo**: owner de la organización de GitHub, owner del
   workspace de Render, el único que aprueba `main → demo` y `demo →
   prod`. Los devs tienen todo lo demás.

## Roles a partir del traspaso

| Rol | Quién | Qué hace |
|-----|-------|----------|
| Producto y release | Sd | Define qué se construye; aprueba los PR a `demo` y `prod`; indica el número de versión (regla vigente de `version.py`) |
| Desarrollo | los dos devs | PRs a `main`, revisión cruzada entre ellos, tests en CI, Pruebas |
| Operación | uno de los dos devs, nombrado | Render de Pruebas y Demo (logs, Shell, variables), backups, promoción cuando Sd aprueba, on-call de la demo antes de presentaciones |

Un solo "responsable de operación" nombrado evita el clásico "pensé que lo
hacías vos". El otro dev es su reemplazo.

## Etapas (cuatro semanas hasta el traspaso)

### Semana 1 — Congelar la demo y liberar `main`

**Etapa 0, en el repo (medio día, sin costo):**

- Rama `demo` **desde el commit hoy desplegado** (`1b79cd8`, v0.27.04) y
  tag `demo-2026-09-03`. Cada promoción lleva su tag fecha + versión.
- `ENTORNO` + distintivo en las cuatro apps (solo `local`/`pruebas`) y
  el entorno en el "Acerca de".
- `promover_demo.py`: `pg_dump` de la base de demo si `DEMO_DATABASE_URL`
  está definida, abre el PR `main → demo` (o mergea y pushea mientras Sd
  sea el único), crea el tag. Un solo comando; en la semana 3 lo van a
  correr los devs.
- Arreglar el hallazgo pendiente de `db.cargar_seed_si_vacio()` (AEFIP
  fantasma): la base de Pruebas nace vacía y es exactamente el caso que lo
  dispara.
- `DESPLIEGUE_RENDER.md` reescrito para dos servicios, con Pre-Deploy
  Command y flujo de promoción.

**Etapa 1, en Render (+~USD 14/mes):**

1. Servicio actual: Settings → Branch `demo`; Pre-Deploy Command
   `python -m alembic upgrade head`; renombrar a `mitrabajo-demo`. Auto
   deploy sigue encendido. El redeploy que dispara el cambio de rama es
   inocuo: `demo` y `main` son el mismo commit. **La base no se toca**:
   ya tiene los datos que Sd quiere y conserva la URL que conocen los
   sindicatos. Cero migración de datos, cero riesgo.
2. Postgres `mitrabajo-pruebas-db` (Basic, ~USD 6) + web
   `mitrabajo-pruebas` (Starter, ~USD 7) siguiendo `main`, con Pre-Deploy
   Command, `ENTORNO=pruebas`, `PYTHON_VERSION=3.12.8` y secretos propios.
   Agrupar todo en un Project de Render con Environments "Demo" y
   "Pruebas" (organización, sin costo).
3. Datos de Pruebas: Alembic corre solo en el primer deploy; después
   `cargar_demo.py` + `cargar_lote_sindicato.py` + `cargar_bancaria.py`
   desde la Shell. Pruebas se ensucia y se regenera; nunca se restaura
   desde demo como rutina.
4. Verificar Pruebas de punta a punta (los cuatro logins, un recibo, un
   trámite). Recién ahí mergear `areas-permisos` a `main` (con las 5
   líneas de `PERMISOS_RUTAS` de BACKLOG.md) y seguir con lo retenido.
5. Activar backup diario de Render en la base de demo (incluido en planes
   pagos; verificar retención) y hacer un `pg_dump` manual ahora, como
   línea de base.

**El orden importa: primero se cambia la rama del servicio actual,
después se pushea cualquier cosa nueva a `main`.**

### Semana 2 — Lo que los devs necesitan el primer día

Con Sd programando solo, esto era "mediano plazo". Con dos personas
entrando, es prerequisito: cada hora invertida acá se cobra en cada
onboarding y en cada PR.

- **Organización de GitHub** (gratis) con el repo transferido; Sd owner,
  devs miembros con permiso de escritura. Mover el repo de una cuenta
  personal a una organización es lo que permite que Sd se corra sin que el
  proyecto dependa de su cuenta.
- **GitHub Team** (~USD 4 por usuario, ~USD 12/mes por tres). Es lo que
  habilita reglas de protección en un repo privado: `main` solo por PR con
  CI verde y una aprobación; `demo` y `prod` solo por PR aprobado por Sd
  (CODEOWNERS sobre esas ramas). Sin esto, todo lo de arriba es
  convención, y las convenciones no sobreviven al segundo desarrollador.
- **CI con GitHub Actions**: en cada PR y cada push a `main`, cada
  `test_*.py` por separado (regla de CLAUDE.md), sobre SQLite como hoy;
  más `alembic heads` con una sola cabeza y `alembic check` para que un
  cambio de modelo sin migración no llegue a `main`. Entra en la cuota
  gratuita si se cachea `pip`.
- **`.devcontainer/`** con Python 3.12 y el contenedor
  `pgvector/pgvector:pg16` al lado (mismo `docker-compose.yml` de hoy).
  Sirve para GitHub Codespaces y para VS Code local con Docker: los dos
  devs y Sd trabajan en el mismo entorno, sin el `.venv/Scripts/python.exe`
  de Windows ni los "en mi máquina anda". Cubre las tres cosas de la
  pregunta 3: programar desde el navegador, URL compartible por
  port-forwarding para ver corriendo una rama, y la base viviendo en el
  Codespace. Cuota gratuita de Codespaces por cuenta personal; en una
  organización Team la organización paga y puede poner tope.
- **Claude Code para los tres**: CLAUDE.md, HISTORIAL.md, BACKLOG.md y las
  skills de diseño ya son el mejor onboarding que tiene el proyecto, con
  la ventaja de que un dev que usa Claude Code hereda las reglas
  automáticamente. Sumar un `SessionStart` hook que instale
  `requirements.txt` para que los tests corran también en Claude Code web.

### Semana 3 — Runbook, secretos y primeros PRs acompañados

- **`RUNBOOK.md`** (dos páginas, para humanos, no para Claude): cómo
  deployar a Pruebas (pushear a `main`), cómo promover a demo, cómo
  revertir (`git revert` en `demo` + push, o redeployar un commit anterior
  desde Render), cómo restaurar un backup, cómo dar de alta un sindicato,
  cómo regenerar los datos de Pruebas, dónde están los secretos, a quién
  llamar. Es el documento que hoy vive en la cabeza de Sd.
- **README "primer día"**: clonar, abrir Codespace, `alembic upgrade
  head`, `cargar_demo.py`, correr un test, abrir un PR. Un dev nuevo tiene
  que llegar a "vi la app corriendo con mi cambio" en su primera mañana.
- **Render con asientos** (plan Professional, ~USD 19 por usuario;
  verificar precio vigente): al menos uno para el responsable de operación.
  Compartir el login de Sd con quien opera a diario es la peor práctica
  posible: sin auditoría y sin poder revocar. Si el presupuesto de
  transición no llega para dos asientos, el segundo dev opera vía GitHub
  (Pruebas se deploya sola, las migraciones corren solas) hasta
  producción.
- **Rotar todos los secretos** al momento del traspaso y guardarlos en un
  gestor de contraseñas del equipo (Bitwarden tiene plan gratuito de dos
  usuarios; el de equipo cuesta poco). Sd deja de ser el único que los
  conoce.
- **Anthropic**: workspace "desarrollo" con tope de gasto y una clave por
  dev, separado de los workspaces de demo y pruebas.
- Los devs abren sus primeros PRs a `main` sobre trabajo real (por
  ejemplo, fases 2–4 de validaciones de trámites o el sprint "Admin de
  Seccional", cuyas decisiones ya están cerradas en BACKLOG.md), con Sd
  revisando. La revisión es el traspaso.

### Semana 4 — Traspaso

- Un dev corre `promover_demo.py` por primera vez, Sd aprueba el PR.
  Desde ese día, Sd no vuelve a ser el único que deploya.
- Sd deja de revisar cada PR a `main` (revisan los devs entre ellos) y se
  queda solo con `demo`/`prod`.
- Revisar CLAUDE.md: la regla "el número de versión lo indica el usuario"
  pasa a "lo indica Sd en el PR de promoción"; el "Método de trabajo" deja
  de hablar de una sola persona.

### Producción (cuando haya sindicato real; ~USD 600/mes)

Con ese presupuesto no hay motivo para irse de Render ni para inventar
infraestructura: se compra holgura y resiliencia dentro del mismo esquema.
Reparto orientativo (precios a verificar en el momento):

| Rubro | Qué | ~USD/mes |
|-------|-----|----------|
| Web prod | Pro (4 GB) o 2 instancias Standard para redundancia | 85–170 |
| Postgres prod | plan Pro con point-in-time recovery y alta disponibilidad | 100–200 |
| Asientos Render | 3 usuarios Professional | 57 |
| GitHub Team | 3 usuarios | 12 |
| Observabilidad | Sentry Team + monitor de disponibilidad | 30–50 |
| Backups fuera de Render | Cron Job + bucket (B2/S3) | 5–10 |
| Dominio y email transaccional | dominio + Resend/Postmark (recuperar clave, avisos) | 15–25 |
| Pruebas + Demo | como hoy | 30 |
| **Total** | | **~330–550** |

Sobra margen para Render Preview Environments (un entorno por PR, útil
con dos devs revisándose) y para subir Demo a 2 GB si el módulo RAG
lo pide. **La API de Anthropic no entra acá**: es costo variable por
recibo leído y por consulta al convenio, y va presupuestado aparte según
volumen de trabajadores.

Qué exige producción además del dinero:

- Servicio `mitrabajo-prod` + Postgres Pro, rama `prod` que solo recibe de
  `demo` (mismo script, un parámetro). Camino `main → demo → prod`: cada
  versión se mostró antes de venderse.
- **Dominio propio** con subdominios `app.`, `demo.`, `pruebas.`; la URL
  `.onrender.com` de hoy queda como alias de demo.
- **Antes de correr 2 instancias, un cambio de código**: la indexación
  RAG marca como error "todo lo que quedó en `procesando`" al arrancar
  (regla vigente en CLAUDE.md). Con dos instancias, el reinicio de una
  marcaría como error la indexación viva de la otra. Hay que asociar la
  indexación a la instancia que la corre, o mover la indexación a un
  Background Worker de Render. Las sesiones no tienen este problema:
  son cookies firmadas, sin estado en el servidor.
- **Disciplina expand/contract** en migraciones: el Pre-Deploy corre
  mientras la instancia vieja sigue sirviendo; un `DROP COLUMN` va en el
  deploy siguiente al que dejó de usarla.
- Eliminar "Cambiar clave" de plataforma, rotar secretos, y ampliar el
  runbook con restauración desde PITR y el procedimiento de incidente.

## Presupuesto de transición: 15, 30 o más

| Concepto | ~USD/mes | Cuándo |
|----------|----------|--------|
| Pruebas (web + Postgres) | 14 | Semana 1, imprescindible |
| GitHub Team (3 usuarios) | 12 | Semana 2, fuertemente recomendado |
| Render Professional, 1 asiento | 19 | Semana 3, recomendado |
| Render Professional, 2.º asiento | 19 | Cuando el 2.º dev opere Render |
| Demo a 2 GB (Standard) | +18 | Solo si Metrics → Memory lo muestra |
| Preview Environments | variable | Producción |

Con el tope de 15 se hace la semana 1. Con 30 entra GitHub Team, que es
lo que convierte las reglas en reglas. Los asientos de Render (~USD 45
acumulados) son el punto donde el presupuesto de transición se queda
corto: recomendación honesta, adelantar del presupuesto de producción el
primer asiento en la semana 3, porque es el precio de que Sd deje de ser
el único que puede entrar a ver por qué se cayó la demo.

## Opiniones (por qué así y no de otra forma)

- **Convertir el servicio actual en demo, en vez de crear una demo nueva.**
  Conserva la URL, no mueve datos y son dos cambios en Settings. La
  alternativa es más trabajo y más riesgo justo en el entorno que no puede
  fallar.
- **Rama `demo` por PR, no por push directo.** Con una persona un push
  alcanzaba; con tres, el PR es donde Sd aprueba sin tener que estar en el
  código. Los tags se crean igual, como registro.
- **Pre-Deploy Command es el mejor costo/beneficio de todo el plan**: una
  línea elimina la causa del único incidente de producción documentado, y
  es lo que permite que Pruebas se opere sin entrar a Render.
- **Codespaces y GitHub Team suben de "mediano plazo" a "semana 2"** solo
  por el traspaso: son inversiones que se amortizan por desarrollador, y
  ahora hay tres.
- **Ninguna base de desarrollo compartida.** Cada dev prueba sus
  migraciones contra su propia base; una compartida se rompe con la
  primera migración a medias.
- **Pruebas descartable, demo intocable.** Pruebas se regenera con los
  scripts de lotes (idempotentes, ya existen). Demo tiene backup antes de
  cada promoción.
- **Sin rama `develop`.** `main` + `demo` (+ `prod`) alcanza para tres
  personas con PRs y CI; una rama permanente más solo agrega merges.
- **El mayor riesgo del traspaso no es técnico, es el conocimiento
  tácito**: por qué el semáforo no toma la marca, por qué `fastembed` va
  pinneado, por qué las cookies son por rol. Casi todo eso ya está
  escrito en CLAUDE.md y HISTORIAL.md; el runbook y el "primer día" son
  lo que falta. Que los devs usen Claude Code con esos archivos es la
  forma más barata de que hereden las reglas sin leer 150 KB de
  historial.

## Qué se hace primero

Etapa 0 entera en la rama `claude/entornos-deploy-strategy-jyb558` (rama
`demo` + tag, `ENTORNO` con distintivo, `promover_demo.py`, docs, arreglo
del seed de AEFIP), y después los cambios de la Etapa 1 en el dashboard
de Render, que los hace Sd con la guía actualizada. La semana 2 arranca
con la organización de GitHub, que conviene crear antes de que entren los
devs y no después.
