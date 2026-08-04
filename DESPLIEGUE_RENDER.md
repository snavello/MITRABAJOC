# Desplegar Mi Trabajo en Render (con Postgres gestionado)

Esta guía publica la app usando **Postgres gestionado de Render** como base de
datos. Reemplaza al esquema anterior de SQLite sobre disco persistente. Ya no
hace falta disco: todo el estado (incluidos los logos) vive en Postgres.

## Requisitos previos
- El proyecto en un repositorio de GitHub.
- Cuenta en render.com.
- Tu clave de la API de Anthropic.

## Paso 1 — Crear la base Postgres en Render
1. En render.com: New -> Postgres.
2. Elegí nombre (ej. mitrabajo-db), región y plan.
3. Al crearse, Render te da varias URLs. Copiá la **Internal Database URL**
   (empieza con postgres://): esa usa tu app porque vive en la misma red que el
   servicio web (más rápida y no expone la base a internet).
4. Guardá también la **External Database URL** para conectarte desde tu máquina
   con DBeaver / pgAdmin / psql cuando necesites inspeccionar la base.

## Paso 2 — Crear el servicio web
1. New -> Web Service, conectá tu repositorio.
2. Configurá:
   - Runtime: Python 3
   - Build Command:  pip install -r requirements.txt
   - Start Command:  uvicorn main:app --host 0.0.0.0 --port $PORT
3. Elegí el plan que prefieras.

## Paso 3 — Variables de entorno
En Environment -> Add Environment Variable:

    DATABASE_URL        = (la Internal Database URL del Paso 1)
    ANTHROPIC_API_KEY   = tu-clave-real
    PLATAFORMA_CUIT     = 20000000000
    PLATAFORMA_PASSWORD = una-clave-de-plataforma
    SESSION_SECRET      = una-cadena-larga-y-secreta
    PYTHON_VERSION      = 3.12.8

Notas:
- **Si DATABASE_URL está definida, la app usa Postgres automáticamente.** Si no,
  cae a SQLite (solo para desarrollo local). Ya NO se usa DB_PATH en Render.
- PYTHON_VERSION es redundante con .python-version a propósito: fuerza 3.12 y
  evita que Render agarre 3.14, que rompe SQLModel.

## Paso 4 — Aplicar el esquema con Alembic (una vez)
El esquema lo administra Alembic, no la app. Tras el primer deploy, abrí la
**Shell** del servicio web en Render y corré:

    alembic upgrade head

Crea todas las tablas en Postgres. Si más adelante cambia el modelo, se genera
una nueva migración y se vuelve a correr alembic upgrade head, **sin borrar la
base**. Ese es el cambio grande respecto de antes.

## Paso 5 — Cargar datos de demostración (opcional, una vez)
Para los dos sindicatos de demo (UOM y Gastronómica), en la misma Shell:

    python cargar_demo.py

Arranca desde cero: solo esos dos sindicatos, sin AEFIP. Para producción real,
los sindicatos se dan de alta desde el panel de plataforma.

## Paso 6 — Ya no hace falta disco persistente
Con Postgres y los logos en la base, **el disco de /var/data se puede eliminar**.
Si venías del esquema anterior, quitalo en Disks -> Delete para dejar de pagarlo.

## Accesos de la demo
- Plataforma:  /plataforma  -> CUIT 20000000000 + PLATAFORMA_PASSWORD
- UOM:         /admin        -> CUIT 20111111110 / uom-demo
- Gastronómica:/admin        -> CUIT 20222222220 / fega-demo
- Trabajador:  /ingresar     -> registrarse con un CUIL habilitado
- Pluriempleo: CUIL 27222222224 está en ambos sindicatos

## Inspeccionar la base con SQL (pruebas)
Con la External Database URL, conectá cualquier cliente Postgres (DBeaver
recomendado, gratuito) y usá SQL normal: SELECT, UPDATE, ALTER TABLE, etc. El
explorador web de Render sirve para un vistazo rápido; el trabajo serio se hace
desde el cliente de escritorio.

## Migrar a Supabase en el futuro (si hiciera falta)
Como los dos son Postgres: pg_dump desde Render + pg_restore a Supabase, y
cambiar solo DATABASE_URL. El código no se toca. Alembic deja el esquema
versionado y portable.
