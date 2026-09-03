# PLAN_ENTORNOS.md — Entornos y traspaso del proyecto a un equipo

Propuesta escrita 2026-09-03 a partir de seis preguntas cerradas con Sd y
dos ajustes de escenario. Igual que `SPRINT_REFORMA.md` y
`PLAN_RAG_CONVENIO.md`: documenta el plan tal cual se acordó; el avance
real se lleva en CLAUDE.md.

**Cómo leer este documento**: cada etapa tiene la misma estructura. Qué
buscamos, qué vamos a tener al terminar, qué hace Claude (código y
documentos, en PRs sobre el repo), qué hace Sd separado en *técnico*
(clics en GitHub, Render, Anthropic) y en *trámites y contrataciones*
(planes, pagos, altas de gente), y cómo verificamos que quedó.

## El escenario que ordena todo

- **Hoy**: Sd es el único desarrollador, el único que deploya y el único
  con acceso a Render. Un servicio web pago que sigue `main` y redeploya
  con cada push, más un Postgres pago. Esa URL `.onrender.com` es la que ya
  vieron sindicatos e inversor: es demo y pruebas al mismo tiempo, y por
  eso se retienen funcionalidades (`areas-permisos`, "Admin de Seccional",
  fases 2–4 de validaciones).
- **En ~1 mes**: dos desarrolladores más toman el control diario. Sd sigue
  con el mismo acceso que hoy, trabajando en las ideas generales.
- **Al entrar en producción**: al menos USD 600/mes de infraestructura.
- **Mientras tanto**: no hay problema en adelantar presupuesto de
  producción para lo que el traspaso necesite.

El eje del plan es **dejar el proyecto operable por otras dos personas en
cuatro semanas, sin que Sd sea un punto único de falla**. Separar la demo
de las pruebas es la semana 1 de ese camino, no el objetivo.

Decisiones ya cerradas en las preguntas:

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
| **Producción** | Sindicatos reales | `prod` (auto-deploy) | Postgres Pro con recuperación a un punto en el tiempo | reales | promueve un dev, aprueba Sd |

Reglas del modelo:

1. **GitHub es el panel de control.** Un entorno cambia solo por un push a
   su rama; Render obedece. Todo queda con autor e historia.
2. **`demo` solo recibe merges desde `main`**, por Pull Request, con la
   aprobación de Sd. Nadie programa sobre `demo`. Misma regla de `demo` a
   `prod` cuando exista.
3. **`main` siempre va adelante de `demo`**: cuando una versión se
   promueve, sus migraciones ya corrieron en Pruebas.
4. **Migraciones automáticas en el deploy** (Pre-Deploy Command de Render:
   `python -m alembic upgrade head`). Se termina el paso manual en la Shell
   y el incidente del 2026-09-01 no puede repetirse.
5. **Secretos distintos por entorno** y ninguna credencial compartida por
   chat: `SESSION_SECRET`, `PLATAFORMA_PASSWORD`, claves VAPID y una
   `ANTHROPIC_API_KEY` por entorno (un Workspace de Anthropic por entorno:
   gasto separado, tope, revocación independiente).
6. **La app sabe dónde corre** (`ENTORNO=local|pruebas|demo|prod`). Local y
   pruebas muestran un distintivo con entorno y versión; demo y prod, nada.
   Sin la variable, no se muestra nada (así el deploy de la Etapa 0 en el
   servicio actual no cambia lo que ven los sindicatos).
7. **Sd conserva todo**: owner de la organización de GitHub y del
   workspace de Render, único aprobador de `main → demo` y `demo → prod`.

## Roles a partir del traspaso

| Rol | Quién | Qué hace |
|-----|-------|----------|
| Producto y release | Sd | Define qué se construye; aprueba los PR a `demo` y `prod`; indica el número de versión (regla de `version.py`) |
| Desarrollo | los dos devs | PRs a `main`, revisión cruzada, tests en CI, Pruebas |
| Operación | uno de los dos devs, nombrado | Render de Pruebas y Demo (logs, Shell, variables), backups, promoción cuando Sd aprueba, guardia de la demo antes de presentaciones. El otro dev es su suplente. |

---

## Semana 1 · Etapa 0 — Preparar el repo

**Qué buscamos**: que el código y los documentos estén listos para tener
dos entornos, antes de tocar Render.

**Qué vamos a tener al terminar**: la app distingue en qué entorno corre,
existe un comando para promover a demo, la guía de deploy describe dos
servicios, y el seed fantasma de AEFIP ya no aparece en bases nuevas.

**Claude** (un PR sobre `main`):
- `ENTORNO`: variable leída en `main.py`, pasada a todas las plantillas;
  distintivo visible solo con `local` o `pruebas`; el entorno se muestra
  también en el "Acerca de" junto a la versión. Sin variable, nada.
- `promover_demo.py`: si `DEMO_DATABASE_URL` está en el `.env` local hace
  un `pg_dump` con fecha; mergea `main` en `demo`, crea el tag
  `demo-AAAA-MM-DD-vX.Y.Z` y pushea. Desde la semana 3 abre un PR en vez
  de pushear directo.
- Arreglo de `db.cargar_seed_si_vacio()` (AEFIP fantasma): la base de
  Pruebas nace vacía y es exactamente el caso que lo dispara.
- `DESPLIEGUE_RENDER.md` reescrito: dos servicios, Pre-Deploy Command,
  variables por entorno, flujo de promoción, cómo regenerar Pruebas.
- Tests de lo anterior; CLAUDE.md apunta a este plan.

**Sd, técnico**:
1. En Render, en el servicio actual → Environment: agregar
   `ENTORNO=demo`. Inofensivo: el código de hoy la ignora.
2. Revisar y mergear el PR de Claude a `main`. Redeploya el servicio
   actual con esos cambios (sin efecto visible para los sindicatos).
3. Crear la rama `demo` desde ese `main` ya mergeado, y el primer tag:
   ```
   git fetch origin main
   git checkout -b demo origin/main
   git tag demo-2026-09-XX-v0.27.04
   git push -u origin demo --tags
   ```
   (o autorizar a Claude explícitamente a pushear la rama `demo`).

**Sd, trámites**: ninguno.

**Verificación**: `main` y `demo` apuntan al mismo commit en GitHub; la
demo se ve exactamente igual que antes.

## Semana 1 · Etapa 1 — Congelar la demo y crear Pruebas

**Qué buscamos**: que la URL que conocen los sindicatos deje de recibir
cada push, y que exista un lugar donde `main` corra solo.

**Qué vamos a tener al terminar**: `mitrabajo-demo` (el servicio de hoy,
con sus datos y su URL) siguiendo `demo`; `mitrabajo-pruebas` con base
propia siguiendo `main`; migraciones automáticas en los dos; `main` libre
para mergear lo retenido.

**El orden importa**: primero se cambia la rama del servicio actual (paso
1), después se crea Pruebas, y recién al final se pushea algo nuevo a
`main`.

**Claude**:
- Cuando Pruebas esté arriba: verificación de punta a punta (los cuatro
  logins, subir un recibo, un trámite, el Panel Sindical).
- Mergear `areas-permisos` a `main` con las 5 líneas de `PERMISOS_RUTAS`
  de BACKLOG.md, y verificar que Pruebas lo toma y aplica su migración
  sola. Primer deploy que la demo no ve.

**Sd, técnico, en Render**:
1. Servicio actual → Settings → Build & Deploy: **Branch: `demo`**.
   Dispara un redeploy inocuo (mismo commit).
2. Mismo lugar → **Pre-Deploy Command**: `python -m alembic upgrade head`.
3. Settings → Name: `mitrabajo-demo`. La URL `.onrender.com` no cambia
   por renombrar el servicio (verificar al guardar: Render avisa si
   cambia).
4. New → Postgres: nombre `mitrabajo-pruebas-db`, misma región que el
   actual, plan Basic más chico. Copiar la Internal Database URL.
5. New → Web Service, mismo repo, **Branch: `main`**, Runtime Python 3,
   Build `pip install -r requirements.txt`, Start
   `uvicorn main:app --host 0.0.0.0 --port $PORT`, Pre-Deploy Command
   `python -m alembic upgrade head`, plan Starter, nombre
   `mitrabajo-pruebas`. Variables: `DATABASE_URL` (la del paso 4),
   `ENTORNO=pruebas`, `PYTHON_VERSION=3.12.8`, `PLATAFORMA_CUIT`,
   `PLATAFORMA_PASSWORD` **distinta** de la de demo, `SESSION_SECRET`
   **nuevo** (cualquier cadena larga al azar), `ANTHROPIC_API_KEY` la del
   Workspace "Pruebas" (ver Anthropic abajo). VAPID: por ahora sin claves
   (el push queda apagado en Pruebas; se generan en la semana 3).
6. Primer deploy de Pruebas: el Pre-Deploy corre Alembic y crea el
   esquema. Después, en la Shell de `mitrabajo-pruebas`:
   `python cargar_demo.py`, `python cargar_lote_sindicato.py --sindicato "UOM"`,
   `python cargar_bancaria.py`.
7. Projects → New Project "Mi Trabajo" con Environments "Demo" y
   "Pruebas"; mover cada servicio y base al suyo. Es organización, sin
   costo.
8. En la base de demo → Backups: confirmar que el backup diario está
   activo y cuál es la retención del plan.
9. Backup manual de línea de base, desde tu PC con el Docker de
   desarrollo (trae `pg_dump` sin instalar nada):
   ```
   docker compose exec postgres-dev pg_dump "<External Database URL de demo>" -Fc -f /tmp/demo.dump
   docker compose cp postgres-dev:/tmp/demo.dump ./demo-2026-09-XX.dump
   ```
   Guardarlo fuera del repo (`.gitignore` lo cubre si queda en `data/`).

**Sd, técnico, en Anthropic** (console.anthropic.com):
1. Settings → Workspaces: crear "Demo" y "Pruebas". Mover la clave actual
   a "Demo" o crear una nueva ahí y reemplazarla en Render.
2. En "Pruebas": crear una clave y ponerle un tope mensual de gasto
   (Limits). Esa va en `mitrabajo-pruebas`.

**Sd, trámites**: el Postgres y el web nuevos se cobran solos en la
cuenta de Render existente (~USD 13–14/mes). Nada más que contratar.

**Verificación**: un push de prueba a `main` (el merge de
`areas-permisos`) redeploya Pruebas y **no** toca la demo; en la demo
sigue la versión 0.27.04 en el "Acerca de"; en Pruebas aparece el
distintivo "PRUEBAS".

## Semana 2 · Etapa 2 — Lo que los devs necesitan el primer día

**Qué buscamos**: que un desarrollador nuevo pueda clonar, correr, probar
y abrir un PR sin depender de la PC ni de la cuenta personal de Sd, y que
las reglas del modelo sean reglas y no convenciones.

**Qué vamos a tener al terminar**: el repo en una organización de GitHub
con reglas de rama; CI corriendo tests y guardas de Alembic en cada PR;
un entorno de desarrollo reproducible (Codespaces o VS Code + Docker) que
cubre las tres cosas de la pregunta 3; Claude Code web con dependencias
instaladas al abrir.

**Claude** (PRs sobre `main`):
- `.github/workflows/ci.yml`: en cada PR y cada push a `main`, cada
  `test_*.py` por separado (regla de CLAUDE.md), sobre SQLite, con caché
  de `pip`; más `alembic heads` con una sola cabeza y `alembic check`
  para que un cambio de modelo sin migración no llegue a `main`.
- `.devcontainer/` (Python 3.12 + contenedor `pgvector/pgvector:pg16`
  con el `docker-compose.yml` de hoy, `alembic upgrade head` al crear):
  sirve igual en Codespaces y en VS Code local. Port-forwarding de
  `uvicorn` para compartir una rama corriendo.
- `.claude/settings.json` con un `SessionStart` hook que instale
  `requirements.txt`, para que los tests corran también en Claude Code
  web.
- `.github/CODEOWNERS` (Sd dueño de `demo` y `prod` vía reglas, ver
  abajo) y `.github/pull_request_template.md` corto (qué cambia, cómo se
  probó, ¿lleva migración?, ¿sube versión?).

**Sd, técnico, en GitHub**:
1. Crear la organización (nombre a elegir, ej. `mitrabajo-ar`), plan Free
   por ahora.
2. Repo `MITRABAJOC` → Settings → Danger Zone → **Transfer** a la
   organización. GitHub deja redirecciones; el clon local de Sd sigue
   funcionando (conviene igual actualizar el remoto:
   `git remote set-url origin <nueva URL>`).
3. **Render pierde el vínculo con el repo al transferirlo**: en Render →
   Account Settings → GitHub, instalar la GitHub App de Render en la
   organización y dar acceso al repo; en cada servicio verificar que
   Settings → Repository apunte al repo nuevo y hacer un Manual Deploy
   para confirmar que el auto-deploy sigue vivo. Hacer esto el mismo día
   de la transferencia.
4. Subir la organización a **GitHub Team** (Settings → Billing). Es lo que
   habilita reglas de protección en un repo privado.
5. Repo → Settings → Rules → Rulesets, tres reglas:
   - `main`: PR obligatorio, 1 aprobación, status check "CI" requerido,
     sin push directo, sin force-push.
   - `demo` y `prod`: PR obligatorio, aprobación de Sd obligatoria (vía
     CODEOWNERS o "Restrict who can push"), status check "CI" requerido.
   - Bloquear borrado de las tres.
6. Organización → Settings → Codespaces: habilitar para el repo, poner un
   límite de gasto mensual (Billing → Spending limits). En una
   organización Team, la organización paga el uso de Codespaces.
7. Abrir un Codespace sobre `main` y confirmar que la app levanta y un
   test pasa. Ese es el "primer día" que van a vivir los devs.

**Sd, técnico, en Anthropic**: crear el Workspace "Desarrollo" con tope
de gasto bajo. Las claves individuales se crean en la semana 3 cuando
entren los devs.

**Sd, trámites y contrataciones**:
- GitHub Team: ~USD 4 por usuario y mes (3 usuarios, ~USD 12). Se paga
  desde la organización, con tarjeta.
- Codespaces: cobro por uso (una máquina de 2 núcleos ronda USD 0,18 la
  hora; 60 horas al mes por dev son ~USD 11). El límite de gasto del paso
  6 es el tope.
- Pedirles a los dos devs su usuario de GitHub (si no tienen, que lo
  creen con autenticación de dos factores activa: la organización puede
  exigirlo en Settings → Authentication security).

**Verificación**: un PR de prueba sobre `main` muestra el check "CI"
corriendo y no se puede mergear hasta que pasa; un push directo a `main`
es rechazado; el Codespace levanta la app con Postgres.

## Semana 3 · Etapa 3 — Runbook, accesos y primeros PRs acompañados

**Qué buscamos**: que lo que hoy vive en la cabeza de Sd esté escrito, que
cada persona tenga sus propios accesos, y que los devs ya estén haciendo
trabajo real con Sd mirando.

**Qué vamos a tener al terminar**: `RUNBOOK.md` y un README de "primer
día"; los devs con cuenta propia en GitHub, Render y Anthropic; todos los
secretos rotados y en un gestor de contraseñas del equipo; los primeros
PRs de los devs mergeados a `main` y corriendo en Pruebas.

**Claude**:
- `RUNBOOK.md`, dos páginas para humanos: deployar a Pruebas (pushear a
  `main`), promover a demo (`promover_demo.py` + PR + aprobación de Sd),
  revertir (`git revert` en `demo` + push, o "Rollback" a un deploy
  anterior en Render), restaurar un backup de Render, regenerar los datos
  de Pruebas, dar de alta un sindicato, dónde están los secretos, qué
  mirar cuando "la demo no anda" (logs, Metrics, último deploy), a quién
  avisar.
- README reescrito con "primer día": abrir Codespace, `alembic upgrade
  head`, `cargar_demo.py`, correr un test, abrir un PR. La meta es llegar
  a "vi la app corriendo con mi cambio" en la primera mañana.
- `promover_demo.py` pasa a abrir un PR `main → demo` en vez de pushear.
- Generación de claves VAPID para Pruebas documentada (comando en
  `push.py` o en el runbook).
- CLAUDE.md: "Método de trabajo" y la regla de versión adaptados a un
  equipo (la versión la indica Sd en el PR de promoción).
- Revisar junto con Sd los primeros PRs de los devs (comentarios en el
  PR), sobre trabajo real: fases 2–4 de validaciones o el sprint "Admin
  de Seccional", cuyas decisiones ya están cerradas en BACKLOG.md.

**Sd, técnico, en Render**:
1. Workspace → Settings → Members: invitar a los dos devs. Roles: el
   responsable de operación como Admin del Project "Mi Trabajo"; el otro
   como Developer. Ninguno con acceso a facturación.
2. Rotar secretos, en este orden, en Demo y en Pruebas: `SESSION_SECRET`
   nuevo (desloguea a todos los usuarios una vez; hacerlo un día sin
   presentación), `PLATAFORMA_PASSWORD` nueva, `ANTHROPIC_API_KEY` nueva
   (revocar la vieja en Anthropic recién después de confirmar que la
   nueva anda).
3. Generar claves VAPID para Pruebas y cargarlas (`VAPID_PRIVATE_KEY`,
   `VAPID_PUBLIC_KEY`, `VAPID_CLAIM_EMAIL`).

**Sd, técnico, en GitHub**: invitar a los dos devs a la organización como
miembros con permiso Write en el repo. Sd queda como único Owner.

**Sd, técnico, en Anthropic**: invitar a los devs a la organización de la
consola con rol Developer, acotados al Workspace "Desarrollo"; cada uno
crea su propia clave ahí. Las claves de Demo y Pruebas no se comparten:
viven solo en Render.

**Sd, trámites y contrataciones**:
- Render: pasar el workspace a plan **Professional** (~USD 19 por usuario
  y mes; con tres usuarios, ~USD 57; verificar precio vigente al
  contratar). Es lo que permite invitar miembros con roles.
- Gestor de contraseñas del equipo (Bitwarden Teams o 1Password Teams,
  ~USD 4–8 por usuario): ahí van `PLATAFORMA_PASSWORD` de cada entorno,
  la External Database URL de cada base y los accesos de demo. Nada por
  WhatsApp ni por mail.
- Anthropic: dejar definido quién paga la consola (hoy Sd) y el tope de
  cada Workspace.
- Los devs firman lo que corresponda (confidencialidad: los recibos son
  datos personales sensibles) antes de recibir accesos.

**Verificación**: cada dev entra a Render con su usuario y ve logs de
Pruebas; un dev regenera los datos de Pruebas siguiendo solo el runbook,
sin preguntar; los secretos viejos ya no funcionan.

## Semana 4 · Etapa 4 — Traspaso

**Qué buscamos**: que la operación diaria pase de manos de verdad, con Sd
aprobando y no ejecutando.

**Qué vamos a tener al terminar**: la primera promoción a demo hecha por
un dev y aprobada por Sd; los devs revisándose entre ellos los PRs a
`main`; un responsable de operación nombrado con suplente; los documentos
del proyecto hablando de un equipo y no de una persona.

**Claude**:
- Acompañar la primera promoción (revisar el PR `main → demo`, confirmar
  que el tag y el backup quedaron).
- Actualizar CLAUDE.md, ESTADO_DEL_PROYECTO.md y este plan con el estado
  real; mover a HISTORIAL.md lo que ya sea narrativa.

**Sd, técnico**:
1. Nombrar por escrito (en el runbook) al responsable de operación y a su
   suplente.
2. Aprobar el primer PR `main → demo` que abra un dev. Desde ese día, Sd
   no vuelve a ser quien deploya.
3. Dejar de revisar cada PR a `main`: los devs se aprueban entre ellos; Sd
   queda solo con `demo` y `prod`.
4. Acordar la cadencia de promoción (por ejemplo: a demo cuando Sd lo
   pide antes de una presentación, o los viernes si no hay pedidos).

**Sd, trámites**: ninguno nuevo. Revisar la primera factura de Render y
GitHub contra la tabla de presupuesto.

**Verificación**: una semana entera sin que Sd toque Render ni haga un
push, y la demo y Pruebas siguen andando.

---

## Producción (cuando haya sindicato real; ~USD 600/mes)

**Qué buscamos**: un entorno para sindicatos reales con holgura,
recuperación ante fallas y trazabilidad, sin cambiar de proveedor ni de
esquema. Con ese presupuesto no hay motivo para irse de Render.

**Qué vamos a tener al terminar**: `mitrabajo-prod` con Postgres Pro,
rama `prod` que solo recibe de `demo`, dominio propio con subdominios,
backups fuera de Render, monitoreo de errores y disponibilidad, y un
runbook de incidentes.

**Claude**:
- Cambio de código previo a correr 2 instancias: la indexación RAG marca
  como error "todo lo que quedó en `procesando`" al arrancar (regla de
  CLAUDE.md); con dos instancias, el reinicio de una mataría la
  indexación viva de la otra. Asociar cada indexación a la instancia que
  la corre, o moverla a un Background Worker de Render. Las sesiones no
  tienen este problema (cookies firmadas, sin estado en el servidor).
- `promover_prod.py` (o un parámetro de `promover_demo.py`) para
  `demo → prod`.
- Integrar Sentry: que `E-INTERNO-00` lleve el `ref` de 8 caracteres al
  evento de Sentry.
- Eliminar la pestaña "Cambiar clave" de plataforma (pendiente #2 de
  CLAUDE.md) y gatear cualquier resto a `ENTORNO != prod`.
- Cron Job de Render (o workflow programado) con `pg_dump` cifrado a un
  bucket, semanal, con prueba de restauración documentada.
- Disciplina expand/contract en migraciones, documentada en el runbook:
  el Pre-Deploy corre mientras la instancia vieja sigue sirviendo; un
  `DROP COLUMN` va en el deploy siguiente al que dejó de usarla.
- Runbook ampliado: restauración desde recuperación a un punto en el
  tiempo, procedimiento de incidente, rotación de secretos.

**Sd, técnico**:
- Render: Postgres plan Pro con alta disponibilidad y recuperación a un
  punto en el tiempo; web `mitrabajo-prod` en Pro (4 GB) o 2 instancias
  Standard; rama `prod`; Environment "Producción" en el Project;
  variables y secretos propios; Workspace "Producción" en Anthropic con
  clave y tope propios.
- Dominio: comprar el dominio (Sd, en NIC Argentina si es `.com.ar`, o
  un registrador para `.com`), y en Render → Custom Domains configurar
  `app.` (prod), `demo.` y `pruebas.`. La URL `.onrender.com` de hoy queda
  como alias de demo.
- Sentry y monitor de disponibilidad: crear cuentas, invitar a los devs,
  cargar el DSN en Render.
- Email transaccional (Resend o Postmark): dominio verificado, clave en
  Render. Hoy la app no manda mails; hace falta antes de tener usuarios
  reales que olviden la clave.

**Sd, trámites y contrataciones**, reparto orientativo (precios a
verificar al contratar):

| Rubro | Qué | ~USD/mes |
|-------|-----|----------|
| Web prod | Pro (4 GB) o 2 instancias Standard para redundancia | 85–170 |
| Postgres prod | plan Pro con recuperación a un punto en el tiempo y alta disponibilidad | 100–200 |
| Asientos Render | 3 usuarios Professional (ya contratados en semana 3) | 57 |
| GitHub Team | 3 usuarios (ya contratado en semana 2) | 12 |
| Observabilidad | Sentry Team + monitor de disponibilidad | 30–50 |
| Backups fuera de Render | Cron Job + bucket (B2/S3) | 5–10 |
| Dominio y email transaccional | dominio + Resend/Postmark | 15–25 |
| Pruebas + Demo | como hoy | 30 |
| **Total** | | **~330–550** |

Sobra margen para Render Preview Environments (un entorno efímero por
PR, útil con dos devs revisándose) y para subir Demo a 2 GB si el módulo
RAG lo pide. **La API de Anthropic no entra acá**: es costo variable por
recibo leído y por consulta al convenio; va presupuestado aparte según
volumen de trabajadores.

**Verificación**: simulacro de restauración de un backup en una base
descartable, antes del primer sindicato real; y un deploy a prod con
migración, hecho por un dev y aprobado por Sd, sin intervención manual.

---

## Presupuesto de transición (semanas 1 a 4)

| Concepto | ~USD/mes | Semana |
|----------|----------|--------|
| Pruebas (web Starter + Postgres Basic) | 14 | 1 |
| GitHub Team, 3 usuarios | 12 | 2 |
| Codespaces (por uso, con tope) | 10–30 | 2 |
| Render Professional, 3 usuarios | 57 | 3 |
| Gestor de contraseñas, 3 usuarios | 12–24 | 3 |
| **Total al terminar la semana 3** | **~105–140** | |

Todo sale del presupuesto de producción adelantado, como Sd indicó. Lo
único que se pospone a producción son Preview Environments y la memoria
extra de la demo (solo si Metrics → Memory en Render lo muestra).

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
- **Codespaces y GitHub Team en la semana 2 y no "más adelante"** solo
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
  pinneado, por qué las cookies son por rol. Casi todo eso ya está escrito
  en CLAUDE.md y HISTORIAL.md; el runbook y el "primer día" son lo que
  falta. Que los devs usen Claude Code con esos archivos es la forma más
  barata de que hereden las reglas sin leer 150 KB de historial.

## Qué se hace primero

La Etapa 0 entera, en la rama `claude/entornos-deploy-strategy-jyb558`
(`ENTORNO` con distintivo, `promover_demo.py`, arreglo del seed de AEFIP,
`DESPLIEGUE_RENDER.md`). Mientras Claude la codifica, Sd hace el paso 1
de "Sd, técnico" de esa etapa (agregar `ENTORNO=demo` en Render) y crea
los dos Workspaces de Anthropic, que no dependen de nada.
