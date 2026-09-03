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
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` / `VAPID_CLAIM_EMAIL` | propias | propias (o ninguna: el push queda apagado) | Las suscripciones push son por origen; no se comparten entre URLs. |

`DB_PATH` NO se usa en Render (solo desarrollo local con SQLite).

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
   python cargar_demo.py
   python cargar_lote_sindicato.py --sindicato "UOM"
   python cargar_bancaria.py
   ```
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
python cargar_lote_sindicato.py --sindicato "UOM" --limpiar
python cargar_lote_sindicato.py --sindicato "UOM"
```
(y lo mismo con `cargar_bancaria.py`). Para empezar de cero de verdad:
borrar y recrear `mitrabajo-pruebas-db`, actualizar `DATABASE_URL` y
redeployar; el Pre-Deploy recrea el esquema.

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
