# PLAN_ENTORNOS.md — Desarrollo, Pruebas, Demo y Producción

Propuesta de arquitectura de entornos para Mi Trabajo, escrita 2026-09-03 a
partir de seis preguntas cerradas con Sd. Igual que `SPRINT_REFORMA.md` y
`PLAN_RAG_CONVENIO.md`: documenta el plan tal cual se acordó; el estado de
avance real se lleva en CLAUDE.md.

## Punto de partida (2026-09-03)

- Un único servicio web en Render (plan pago) que sigue `main` y redeploya
  con cada push, más un Postgres gestionado (plan pago). Esa URL
  `.onrender.com` es la que ya vieron sindicatos y el inversor: **hoy es
  demo y pruebas al mismo tiempo**, y por eso se están reteniendo
  funcionalidades (`areas-permisos`, sprint "Admin de Seccional", fases 2–4
  de validaciones).
- Migraciones de Alembic aplicadas **a mano** desde la Shell de Render
  después de cada deploy. Ya produjo un incidente real (HISTORIAL.md,
  2026-09-01: tres migraciones sin aplicar → "no pudimos cargar tus
  trámites" en producción).
- Sin CI: no hay `.github/`. Los tests corren solo en la PC de Sd.
- Desarrollo local: Docker + Postgres (pgvector) + uvicorn en la PC de Sd.
- `version.py` a mano en cada deploy; sin tags en git.
- Equipo: Sd solo hoy; cuatro personas en breve.

## Decisiones cerradas en las preguntas

| # | Pregunta | Respuesta |
|---|----------|-----------|
| 1 | Plan de Render actual | Web y Postgres pagos |
| 2 | Presupuesto adicional | Hasta ~USD 15/mes; ampliable a ~USD 30 si se justifica |
| 3 | "Desarrollo sin mi PC" | Las tres cosas: programar desde cualquier lado, ver corriendo lo que hago, base fuera de la PC (mediano plazo) |
| 4 | Datos de la DEMO | Los que hay hoy en la base de Render, tal cual |
| 5 | Cómo se promueve a DEMO | Rama `demo` que Render sigue |
| 6 | Dominio y equipo | Solo `.onrender.com`; solo Sd hoy, cuatro personas en breve |

## Modelo final (a donde vamos)

| Entorno | Para qué | Rama | Base de datos | Datos | Quién lo toca |
|---------|----------|------|---------------|-------|---------------|
| **Desarrollo** | Programar y probar en caliente | rama de feature | Postgres propio de cada desarrollador (Codespace o Docker) | sintéticos, se destruyen sin culpa | cada desarrollador |
| **Pruebas** | Integración: lo último de `main` corriendo en Render, con migraciones aplicadas | `main` (auto-deploy) | Postgres pago propio | sintéticos + copia ocasional de demo | todo el equipo |
| **Demo** | Versión estable para mostrar; nada llega sin decisión explícita | `demo` (auto-deploy) | el Postgres pago actual, sin tocar | los de hoy, con backup antes de cada promoción | Sd (promueve) |
| **Producción** | Sindicatos reales (futuro) | `prod` o tag | Postgres pago, plan con backups | reales | Sd + operador |

Reglas del modelo:

1. **GitHub es el único panel de control.** Todo lo que cambia un entorno
   pasa por un push a una rama; Render solo obedece. Así el equipo de
   cuatro no necesita cuentas en Render (sumar usuarios allí puede exigir
   el plan por asiento — verificar), y todo queda con historia y autor.
2. **`demo` solo recibe merges desde `main`** (o hotfixes, ver abajo).
   Nunca se programa sobre `demo`. Promover = `git merge main` + push.
3. **`main` siempre va adelante de `demo`.** Consecuencia buena: cuando
   una versión llega a demo, sus migraciones **ya corrieron en Pruebas**.
   La promoción nunca es la primera vez que se ejecuta una migración.
4. **Migraciones automáticas en el deploy** (Pre-Deploy Command de Render,
   `python -m alembic upgrade head`). Se termina el paso manual en la
   Shell y el incidente del 09-01 no puede repetirse.
5. **Secretos distintos por entorno**: `SESSION_SECRET`,
   `PLATAFORMA_PASSWORD`, `ANTHROPIC_API_KEY` (una clave por entorno en la
   consola de Anthropic, para ver el gasto de cada uno y poder revocar sin
   tumbar los demás), claves VAPID (las suscripciones push son por origen,
   no se comparten entre URLs).
6. **La app sabe en qué entorno corre** (`ENTORNO=local|pruebas|demo|prod`).
   Pruebas y local muestran un distintivo visible ("PRUEBAS" con la
   versión) para que nadie confunda una pantalla en una presentación;
   demo y prod, nada. La pestaña transitoria "Cambiar clave" de plataforma
   (pendiente #2 de CLAUDE.md) queda gateada a `ENTORNO != prod` hasta
   que se elimine.

## Etapas

### Etapa 0 — Preparar el repo (medio día, sin costo)

Todo en código, sin tocar Render todavía. Es el paso que hace posible el
resto.

- Crear la rama `demo` **desde el commit que hoy está desplegado**
  (`1b79cd8`, v0.27.04) y el tag `demo-2026-09-03`. A partir de acá cada
  promoción lleva su tag con fecha + versión: historia gratis de qué se
  mostró cuándo.
- `ENTORNO` como variable de entorno + distintivo en las cuatro apps
  (solo `local`/`pruebas`), y el entorno en el "Acerca de" junto a la
  versión.
- Script `promover_demo.py` (o sección en el README): hace un `pg_dump`
  de la base de demo si `DEMO_DATABASE_URL` está definida localmente,
  mergea `main` en `demo`, crea el tag y pushea. Un solo comando, un
  solo lugar donde equivocarse.
- Actualizar `DESPLIEGUE_RENDER.md` con los dos servicios, el Pre-Deploy
  Command y el flujo de promoción; CLAUDE.md apunta a este plan.
- Arreglar de paso el hallazgo pendiente de `db.cargar_seed_si_vacio()`
  (AEFIP fantasma): la base de Pruebas va a nacer vacía y es exactamente
  el caso que lo dispara.

### Etapa 1 — Congelar la demo y liberar `main` (esta semana, +~USD 14/mes)

El orden importa: **primero se cambia la rama del servicio actual, después
se pushea cualquier cosa nueva a `main`**.

1. En Render, en el servicio actual: Settings → Branch: `demo`;
   Pre-Deploy Command: `python -m alembic upgrade head`; renombrarlo
   `mitrabajo-demo`. Auto-deploy queda encendido (sobre `demo`). El
   redeploy que dispara el cambio de rama es inocuo: `demo` y `main` son
   el mismo commit en ese momento. La base no se toca: **la demo ya tiene
   los datos que Sd quiere (pregunta 4) y conserva la URL que conocen los
   sindicatos**. Cero migración de datos, cero riesgo.
2. Crear el Postgres `mitrabajo-pruebas-db` (Basic, ~USD 6/mes) y el web
   `mitrabajo-pruebas` (Starter, ~USD 7/mes) siguiendo `main`, con el
   mismo Build/Start Command, Pre-Deploy Command, `ENTORNO=pruebas`,
   `PYTHON_VERSION=3.12.8` y secretos propios. Agrupar los cuatro
   servicios en un Project de Render con Environments "Demo" y "Pruebas"
   (es solo organización, no cuesta).
3. Datos de Pruebas: `alembic` corre solo en el primer deploy; después,
   desde la Shell, `python cargar_demo.py` + `cargar_lote_sindicato.py`
   + `cargar_bancaria.py`. Si hace falta reproducir un dato puntual de la
   demo, `pg_dump` de la External URL de demo y `pg_restore` en pruebas
   (una vez, no como rutina: Pruebas se ensucia y se regenera).
4. Verificar Pruebas de punta a punta (login de los cuatro roles, subir un
   recibo, un trámite). Recién ahí: mergear `areas-permisos` a `main` (con
   las 5 líneas de `PERMISOS_RUTAS` que anota BACKLOG.md) y seguir con lo
   retenido. La demo no se entera.
5. Activar el backup diario de Render en `mitrabajo-db` (incluido en los
   planes pagos; verificar retención del plan) y anotarse el `pg_dump`
   manual antes de cada promoción como regla, no como sugerencia.

Costo total agregado: ~USD 13–14/mes, dentro del tope de 15.

### Etapa 2 — Red de seguridad para promover (2–3 semanas, sin costo)

- **GitHub Actions**: en cada PR y en cada push a `main`, correr cada
  `test_*.py` por separado (regla de CLAUDE.md: nunca batcheados), sobre
  SQLite como hoy; y dos guardas baratas sobre migraciones: `alembic
  heads` con una sola cabeza, y `alembic check` para que un cambio de
  modelo sin migración no llegue a `main`. Con repo privado alcanza la
  cuota gratuita (2.000 min/mes) si se cachea `pip`.
- **Reglas de rama**: `main` solo por PR con CI verde; `demo` solo
  recibe pushes de Sd (después, del rol "release"). Verificar plan de
  GitHub: las reglas de protección en repo privado requieren Pro/Team; si
  no se quiere pagar, la disciplina del script `promover_demo.py` + CI
  cubre el 90% y se anota el resto como convención.
- **Hotfix en demo**: rama desde `demo`, PR contra `demo`, y de inmediato
  `demo` → `main` para que no se pierda. Es la única excepción a la regla
  "demo solo recibe de main".
- **`render.yaml` (Blueprint)**: describir los dos servicios y las dos
  bases en el repo, para que el cuarto entorno (prod) sea copiar un
  bloque y no repetir clics. Se puede posponer si Render sigue siendo de
  una sola persona; se vuelve obligatorio cuando haya operador.

### Etapa 3 — Desarrollo fuera de la PC (1–2 meses, sin costo dentro de cuotas)

Cubre las tres cosas de la pregunta 3 sin gastar un dólar más, porque la
base de desarrollo vive **dentro** del entorno de cada desarrollador, no
en Render.

- **`.devcontainer/`** con Python 3.12 y un contenedor
  `pgvector/pgvector:pg16` al lado (el mismo `docker-compose.yml` de hoy).
  Sirve igual para GitHub Codespaces y para VS Code local con Docker.
  Codespaces regala 120 horas-núcleo/mes por cuenta personal: alcanza para
  un desarrollador de medio tiempo; con cuatro personas se evalúa el plan
  Team de GitHub o que cada uno use su propia cuota.
  - *Programar desde cualquier lado*: Codespace desde el navegador o desde
    VS Code, con Claude Code instalado en la imagen.
  - *Ver corriendo lo que hago*: el port-forwarding de Codespaces da una
    URL compartible de `uvicorn --reload` sin subir nada a Render.
  - *Base fuera de la PC*: el Postgres corre en el Codespace y persiste
    mientras el Codespace exista.
- **Claude Code en la web** (este mismo tipo de sesión) es la otra pata:
  un `SessionStart` hook que instale `requirements.txt` y deje los tests
  corriendo en SQLite. Sin Postgres, pero suficiente para el trabajo de
  lógica; lo pesado se hace en el Codespace.
- **Onboarding del equipo**: README con "primer día" (clonar, abrir
  Codespace, `alembic upgrade head`, `cargar_demo.py`, correr un test) y
  la convención de ramas de arriba. Es el momento de mover el repo a una
  organización de GitHub (gratis) en vez de una cuenta personal.
- **Descartado por ahora**: Render Preview Environments (un entorno por
  PR). Es el "ver corriendo" ideal para revisar el PR de otro, pero cobra
  cada preview prorrateado y exige Blueprint. Se retoma en la etapa 4 si
  el equipo lo pide y el presupuesto crece.

### Etapa 4 — Producción real (cuando haya un sindicato real, +~USD 25/mes)

- Servicio `mitrabajo-prod` + Postgres en un plan con backups y
  point-in-time recovery; rama `prod` que solo recibe de `demo` (el mismo
  script, un parámetro más). Así el camino es `main → demo → prod` y
  cada versión se mostró antes de venderse.
- **Dominio propio** con subdominios: `app.` (prod), `demo.`, `pruebas.`.
  La URL `.onrender.com` de hoy queda como alias de demo.
- **Backups fuera de Render**: un Cron Job de Render o un workflow
  programado que haga `pg_dump` cifrado a un bucket (B2/S3), semanal. Los
  logos, firmas, fotos y adjuntos están en la base (decisión vigente),
  así que un dump es la copia completa.
- **Observabilidad**: Sentry (plan gratuito) enganchado a `E-INTERNO-00`
  para que el `ref` de 8 caracteres lleve al traceback sin abrir logs;
  un monitor de disponibilidad externo (UptimeRobot / Better Stack).
- **Disciplina de migraciones expand/contract** en prod: como el
  Pre-Deploy corre mientras la instancia vieja sigue sirviendo, un
  `DROP COLUMN` va en el deploy siguiente al que dejó de usarla.
- Eliminar "Cambiar clave" de plataforma (pendiente #2), rotar todos los
  secretos, y un runbook de dos páginas: cómo promover, cómo revertir
  (`git revert` en `demo`/`prod` + push; Render también permite
  redeployar un commit anterior desde el dashboard), cómo restaurar un
  backup.

## Segundo tramo de presupuesto (de 15 a 30): cuándo sí y cuándo no

Sd aclaró que el tope puede subir a ~USD 30/mes si se justifica. Opinión:
**hoy no**. Las etapas 0 a 3 cierran con los ~14 del primer tramo, y los
otros 15 gastados ahora comprarían cosas que todavía no duelen. Los
disparadores concretos para usar el segundo tramo, en orden de
probabilidad:

1. **Cuando el equipo sea de cuatro y el repo siga privado**: GitHub Team
   (~USD 4 por usuario, ~USD 16/mes) para tener reglas de protección de
   rama de verdad sobre `main` y `demo`, en vez de convención. Es el uso
   más probable y el más barato por lo que da.
2. **Si la demo se queda corta de memoria**: el plan Starter de Render
   tiene 512 MB. El módulo RAG del convenio carga
   `multilingual-e5-large` en ONNX dentro del proceso web; si se muestra
   ese módulo en una presentación y el servicio reinicia por memoria, la
   respuesta es subir solo la demo a Standard (2 GB, ~USD 25/mes, +18
   sobre lo actual). Se detecta mirando Metrics → Memory en Render antes
   de gastar, no por las dudas.
3. **Si el equipo pide revisar PRs corriendo**: Render Preview
   Environments (un entorno efímero por PR, prorrateado por hora). Recién
   cuando haya PRs de otras personas que revisar; con una sola persona
   no aporta.

Lo que **no** compraría con ese tramo: un Postgres de desarrollo compartido
en Render (ver Opiniones) ni un cuarto entorno antes de tener un sindicato
real.

## Opiniones (por qué así y no de otra forma)

- **Convertir el servicio actual en demo, en vez de crear una demo nueva.**
  Conserva la URL que ya circuló, no mueve un byte de datos y se hace con
  dos cambios en Settings. La alternativa (demo nueva con copia de la
  base) es más trabajo y más riesgo justo en el entorno que no puede
  fallar.
- **Rama `demo` antes que tags**: se ve en GitHub, la entiende cualquiera
  del equipo y revertir es un `git revert`. Los tags igual se crean en
  cada promoción, pero como registro, no como mecanismo.
- **Pre-Deploy Command es el cambio con mejor relación costo/beneficio de
  todo el plan.** Una línea en Render elimina la causa del único incidente
  de producción documentado.
- **No compartir un Postgres de desarrollo entre cuatro personas.** Cada
  uno prueba sus migraciones contra su base; una base compartida se
  rompe con la primera migración a medias. Por eso la base de desarrollo
  va dentro del Codespace y no en Render.
- **Pruebas es descartable por diseño.** Si se ensucia, se regenera con los
  scripts de lotes (que ya existen y son idempotentes). Demo es lo
  contrario: intocable, con backup antes de cada promoción.
- **`main` sigue siendo la rama de integración**, no se crea una `develop`.
  Con cuatro personas y PRs con CI, `main` + `demo` alcanza; una tercera
  rama permanente solo agrega merges.

## Qué se hace primero

Etapa 0 entera en la rama `claude/entornos-deploy-strategy-jyb558` (rama
`demo` + tag, `ENTORNO` con distintivo, `promover_demo.py`, docs, arreglo
del seed de AEFIP), y después los pasos 1 y 2 de la Etapa 1 en el
dashboard de Render, que los hace Sd con la guía actualizada.
