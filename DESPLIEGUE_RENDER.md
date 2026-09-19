# Desplegar Mi Trabajo en Render — dos servicios: Pruebas y Demo

Desde 2026-09 la app corre en **dos servicios web de Render con su propio
Postgres cada uno**, según [`PLAN_ENTORNOS.md`](PLAN_ENTORNOS.md):

| Servicio | Rama que sigue | Base | Para qué |
|----------|----------------|------|----------|
| `mitrabajo-demo` (el original, misma URL de siempre) | `demo` | `mitrabajo-db` (la original) | Versión estable para mostrar. Solo cambia cuando alguien la promueve. |
| `mitrabajo-pruebas` | `main` | `mitrabajo-pruebas-db` | Lo último de `main`, redeploy con cada push. Datos sintéticos, descartables. |

Las dos comparten la misma configuración salvo la rama, la base, los
secretos y la variable `ENTORNO`. **El esquema lo administra Alembic y
corre solo en cada deploy** (Pre-Deploy Command), ya no a mano.

## Requisitos previos
- El repositorio en GitHub, con las ramas `main` y `demo`.
- Cuenta en render.com con la GitHub App de Render autorizada sobre el repo.
- Claves de la API de Anthropic: una por entorno (Workspaces "Demo" y
  "Pruebas" en console.anthropic.com, con tope de gasto cada una).

## Configuración común a los dos servicios web
- Runtime: Python 3
- Build Command: `pip install -r requirements.txt`
- **Pre-Deploy Command: `python -m alembic upgrade head`** — corre después
  del build y antes de que la instancia nueva reciba tráfico. Si la
  migración falla, el deploy se cancela y sigue sirviendo la versión
  anterior. (Se usa `python -m alembic` y no `alembic` porque en la Shell
  de Render el ejecutable no siempre está en el PATH.)
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path: `/healthz`** (Settings → Health & Alerts). Es la
  pregunta "¿el proceso está vivo?": responde 200 sin tocar la base y sin
  usar el threadpool, así contesta aun con la app saturada. Hasta el
  2026-09-19 no había ninguno configurado. **No apuntarlo a `/readyz`**: esa
  ruta sí consulta la base (`SELECT 1`, techo de 2 s) y sirve para mirar a mano
  o desde un monitor externo; si Render la usara, una base lenta reiniciaría el
  web service, que no arregla nada y corta a los que sí estaban siendo
  atendidos.
- Auto-Deploy: encendido (cada servicio sobre SU rama).

## Variables de entorno

| Variable | Demo | Pruebas | Notas |
|----------|------|---------|-------|
| `DATABASE_URL` | Internal URL de `mitrabajo-db` | Internal URL de `mitrabajo-pruebas-db` | Si está, la app usa Postgres. |
| `ENTORNO` | `demo` | `pruebas` | En `pruebas` la app muestra un distintivo fijo con entorno y versión; en `demo` no muestra nada. Sin la variable tampoco muestra nada. Ver `entorno.py`. |
| `ANTHROPIC_API_KEY` | clave del Workspace "Demo" | clave del Workspace "Pruebas" | Nunca la misma en los dos. |
| `PLATAFORMA_CUIT` | `20000000000` | `20000000000` | |
| `PLATAFORMA_PASSWORD` | propia | **distinta** de la de demo | |
| `SESSION_SECRET` | propio | **distinto** | Cambiarlo desloguea a todos los usuarios de ese entorno. |
| `PYTHON_VERSION` | `3.12.8` | `3.12.8` | Redundante con `.python-version` a propósito: evita que Render tome 3.14, que rompe SQLModel. |
| `GRAFANA_URL` / `GRAFANA_TOKEN_LECTURA` / `GRAFANA_TOKEN_CONFIG` | — | URL del stack de Grafana Cloud y dos tokens de cuenta de servicio | Solo Pruebas por ahora. Los usa la pestaña Observabilidad de `/entornos` (`observabilidad/panel.py`). `_LECTURA` es rol **Viewer** (lee estado y configuración); `_CONFIG` es rol **Editor** (cambia el mail y el intervalo de aviso), nunca Admin. Vencen al año: renovarlos en Grafana (Administration → Service accounts) y actualizar la variable. Sin ellas la pestaña dice qué falta. |
| `SENTRY_URL` | — | (opcional) enlace al proyecto de Sentry | Solo agrega el botón "Abrir errores en Sentry" a esa pestaña. |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` / `VAPID_CLAIM_EMAIL` | propias | propias (o ninguna: el push queda apagado) | Las suscripciones push son por origen; no se comparten entre URLs. |

`DATABASE_URL` es obligatoria en los dos servicios: la app no tiene otro motor.

### Ajustes de conexiones y del Panel Sindical (opcionales)

Todas tienen un default razonable y no hace falta cargarlas; existen para
poder mover un techo sin tocar código (cuelgue de Pruebas del 2026-09-18,
`docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md`). Van por proceso: con
`--workers N` cada worker tiene su propio pool y su propio cupo.

| Variable | Default | Qué hace |
|----------|---------|----------|
| `DB_POOL_SIZE` | `5` | Conexiones fijas del pool. |
| `DB_MAX_OVERFLOW` | `5` | Conexiones extra que el pool abre en un pico. |
| `DB_POOL_TIMEOUT` | `5` | Segundos que un request espera una conexión libre antes de rendirse con un 503 (`E-SERVIDOR-01`). |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | Postgres corta cualquier consulta que pase de esto (503, `E-SERVIDOR-02`). `0` lo apaga; las migraciones nunca lo llevan. |
| `DB_IDLE_TX_TIMEOUT_MS` | `30000` | Postgres cierra una transacción abierta sin actividad. `0` lo apaga. |
| `DASHBOARD_CUPO` | `4` | Endpoints de agregados del Panel Sindical que corren a la vez en el proceso; el resto recibe un 503 (`E-SERVIDOR-03`). |
| `DASHBOARD_CUPO_ESPERA` | `2` | Segundos que un pedido espera un lugar del cupo antes del 503. |

La suma de `DB_POOL_SIZE + DB_MAX_OVERFLOW`, por cantidad de workers, tiene
que entrar en el límite de conexiones del plan de Postgres; con el cupo en 4 y
un solo worker no se llega ni a la mitad de un pool de 10. Si un script de
carga masiva (`cargar_lote_*`, `--limpiar`) necesita consultas de más de 15 s,
correrlo con `DB_STATEMENT_TIMEOUT_MS=0`.

## Paso a paso — crear Pruebas (una vez)

1. **New → Postgres**: nombre `mitrabajo-pruebas-db`, misma región que la
   base de demo, plan Basic más chico. Copiar la Internal Database URL.
2. **New → Web Service**, mismo repo, Branch `main`, nombre
   `mitrabajo-pruebas`, plan Starter, con la configuración común de arriba
   y las variables de la columna "Pruebas".
3. El primer deploy corre `alembic upgrade head` solo (Pre-Deploy) y deja
   el esquema creado, vacío. **No aparece ningún sindicato fantasma**: el
   seed histórico de AEFIP ya no se siembra solo.
4. Datos, desde la **Shell** del servicio `mitrabajo-pruebas`:
   ```
   python cargar_marca_plataforma.py
   python cargar_demo.py
   python cargar_lote_sindicato.py --sindicato "Obrera"
   python cargar_bancaria.py
   ```
   `cargar_marca_plataforma.py` va PRIMERO y no es opcional: el logo y los
   colores de Colm3na viven en la base, no en el repo, así que sin él todas
   las pantallas caen al placeholder `static/logo_mitrabajo.svg` y el
   entorno no se ve como la demo.
5. Projects → New Project "Mi Trabajo" → Environments "Demo" y "Pruebas";
   mover cada servicio y base al suyo (solo organización).

## Paso a paso — convertir el servicio original en Demo (una vez)

Hacerlo **antes** de pushear a `main` algo que no deba llegar a la demo.

1. Settings → Build & Deploy → **Branch: `demo`**. Dispara un redeploy;
   es inocuo si `demo` y `main` apuntan al mismo commit en ese momento.
2. Mismo lugar → **Pre-Deploy Command**: `python -m alembic upgrade head`.
3. Environment → agregar `ENTORNO=demo`.
4. Settings → Name: `mitrabajo-demo` (la URL `.onrender.com` no cambia al
   renombrar; Render avisa si fuera a cambiar).
5. Base de demo → Backups: confirmar que el backup diario está activo y
   anotar la retención del plan.

## Promover una versión a la demo

Todo lo que se pushea a `main` va a Pruebas solo. A la demo llega
únicamente con:

```
python promover_demo.py
```

Hace backup de la base de demo (`pg_dump`, necesita `DEMO_DATABASE_URL` =
External Database URL de `mitrabajo-db` en el `.env` local), mergea `main`
en `demo`, crea el tag `demo-AAAA-MM-DD-vX.Y.Z` y pushea; Render redeploya
la demo. `--solo-pr` imprime el link del Pull Request `main → demo` en vez
de mergear (flujo con aprobación); `--sin-backup` para promover sin copia
(no recomendado). Los dumps quedan en `backups/` (gitignored).

**Regla**: sobre `demo` nunca se programa; solo recibe merges de `main`.
Un arreglo urgente para la demo se hace en una rama desde `demo`, se
mergea a `demo` y enseguida `demo → main`.

## Revertir la demo
- Rápido, sin código: en Render, Deploys → el deploy anterior → **Rollback**.
- Con código: `git revert` del merge en `demo` + push (Render redeploya).
  Si la versión revertida traía una migración, la base conserva la columna
  nueva sin uso; no pasa nada, y se la lleva la próxima promoción.

## Regenerar los datos de Pruebas
Pruebas se ensucia y se regenera, nunca se restaura desde demo como
rutina. En la Shell de `mitrabajo-pruebas`:
```
python cargar_lote_sindicato.py --sindicato "Obrera" --limpiar
python cargar_lote_sindicato.py --sindicato "Obrera"
```
(y lo mismo con `cargar_bancaria.py`). Para empezar de cero de verdad:
borrar y recrear `mitrabajo-pruebas-db`, actualizar `DATABASE_URL` y
redeployar; el Pre-Deploy recrea el esquema. En ese caso volver a correr
también `python cargar_marca_plataforma.py`, que es lo único que repone la
marca de Colm3na.

### Llenar una encuesta con respuestas sintéticas
Para mostrar el módulo Encuestas hace falta volumen: con cinco respuestas
el umbral esconde los cortes y el dashboard queda vacío. El script NO crea
la encuesta —esa la arma una persona en el panel, con sus preguntas— sino
que le pone adentro las respuestas. En la Shell de `mitrabajo-pruebas`:
```
python cargar_encuesta_sintetica.py --sindicato "La Bancaria"        # ensayo
python cargar_encuesta_sintetica.py --sindicato "La Bancaria" --si
```
**Sin `--si` no escribe nada**: imprime el padrón, cuántos van a responder,
cuántos avisos se marcan leídos y qué seccional va a quedar más
disconforme. Opciones: `--respuestas 85` (total de personas que tienen que
quedar con la encuesta respondida, contando las que ya respondieron),
`--leidas 90` (porcentaje de los avisos que queda leído), `--encuesta 12`
(si el sindicato tiene más de una publicada) y `--semilla`.

Las respuestas se reparten **Pareto** (una opción dominante y una cola que
cae, que es lo que devuelve una encuesta real) y **distinto por seccional**
—una queda claramente peor y otra claramente mejor—, para que el filtro por
seccional del dashboard muestre algo y no tres curvas iguales. Se escriben
con la misma función que corre cuando contesta una persona, así que no
dejan la base en un estado que la app no sepa producir; lo único que se
ajusta después es el DÍA, repartido entre los ya corridos de la ventana
para que la curva de ritmo no sea un punto solo.

### Copiar los datos de la demo a Pruebas (excepción)
Cuando la demo tiene datos y usuarios que los scripts todavía no saben
reproducir, se puede clonar entera. **Es la excepción, no la rutina**: lo
normal es regenerar con los lotes, que no dependen de que otra base esté
sana. Desde la PC, con `DEMO_DATABASE_URL` y `PRUEBAS_DATABASE_URL` en el
`.env`:
```
python clonar_demo_a_pruebas.py                      # ensayo, no toca nada
python clonar_demo_a_pruebas.py --si-borrar-pruebas  # lo hace
```
Lee la demo (solo lectura), guarda el dump en `backups/` y lo restaura
sobre Pruebas. Después, `python -m alembic upgrade head` en la Shell de
`mitrabajo-pruebas` por si la demo venía de una versión anterior.

El script **solo copia demo → Pruebas y no se puede invertir**: el destino
tiene que decir "pruebas" en su URL, el origen no, las dos tienen que ser
distintas y hay que pasar `--si-borrar-pruebas` a propósito. Escribir un
dump sobre la demo sería el peor accidente posible del proyecto y ninguna
de esas guardas se saltea con un flag.

**Antes de usarlo, mirar qué hay en la demo**: hoy son datos sintéticos. Con
trabajadores reales, copiarlos a un entorno con otros secretos y más gente
con acceso deja de ser inocuo — los recibos son datos personales.

## Backup manual de la base de demo
Desde la PC de desarrollo, con el Docker local levantado (trae `pg_dump`
sin instalar nada):
```
docker compose exec -T postgres-dev pg_dump "<External Database URL de mitrabajo-db>" -Fc > backups/demo-AAAA-MM-DD.dump
```
Restaurar en una base descartable: `pg_restore -d "<URL destino>" --clean --if-exists archivo.dump`.

## Accesos de la demo
- Plataforma:  /plataforma  → CUIT 20000000000 + `PLATAFORMA_PASSWORD` del entorno
- UOM:         /admin        → CUIT 20111111110 / uom-demo
- Gastronómica:/admin        → CUIT 20222222220 / fega-demo
- La Bancaria: /admin        → CUIT 20333444550 / bancaria-demo
- Trabajador:  /ingresar     → CUIL 20111111119 (UOM); pluriempleo 27222222224
- Empresa:     /ingresar-empresa → CUIT 30999888776 (UOM); multisindicato 30111222339

## Inspeccionar la base con SQL
Con la External Database URL de cada base, cualquier cliente Postgres
(DBeaver recomendado). La de demo, con cuidado: es la que ven los
sindicatos.

## Migrar a otro Postgres en el futuro
`pg_dump` + `pg_restore` y cambiar solo `DATABASE_URL`. El código no se
toca; Alembic deja el esquema versionado y portable.
