# Desplegar Mi Trabajo en Render (con datos persistentes)

Esta guía publica la app en internet con un link fijo y datos que sobreviven
a los reinicios, usando SQLite sobre un disco persistente. Plan gratuito.

## Requisitos previos
- El proyecto subido a un repositorio de GitHub (público o privado).
- Una cuenta gratuita en render.com.
- Tu clave de la API de Anthropic.

## Paso 1 — Subir el proyecto a GitHub
Si todavía no lo tenés en GitHub, desde la carpeta del proyecto:

    git init
    git add .
    git commit -m "Mi Trabajo - version con SQLite"
    git branch -M main
    git remote add origin https://github.com/TU-USUARIO/mi-trabajo.git
    git push -u origin main

El archivo .gitignore ya evita subir la base de datos, el .env y los temporales.

## Paso 2 — Crear el servicio web en Render
1. En render.com: New → Web Service.
2. Conectá tu repositorio de GitHub.
3. Configurá:
   - Runtime: Python 3
   - Build Command:  pip install -r requirements.txt
   - Start Command:  uvicorn main:app --host 0.0.0.0 --port $PORT
4. Elegí el plan Free.

## Paso 3 — El disco persistente (clave para no perder datos)
Sin esto, SQLite se borra en cada reinicio.

1. En el servicio, sección Disks → Add Disk.
2. Configurá:
   - Name: datos
   - Mount Path:  /var/data
   - Size: 1 GB (alcanza de sobra)

## Paso 4 — Variables de entorno
En Environment → Add Environment Variable, cargá dos:

   ANTHROPIC_API_KEY = tu-clave-real
   DB_PATH = /var/data/validador.db

La segunda le dice a la app que guarde la base en el disco persistente en vez
de la carpeta temporal. Es lo que hace que los datos sobrevivan.

## Paso 5 — Desplegar
Render construye y publica automáticamente. Al terminar te da un link fijo
tipo https://mi-trabajo.onrender.com que funciona desde cualquier lado.

La primera vez que arranca, la base se crea sola y se siembra con los conceptos
y fórmulas de data/seed_aefip.json. A partir de ahí, todo lo que cargues desde
el panel (conceptos, fórmulas, reportes, aprendizaje) queda guardado.

## Nota sobre el plan gratuito
El servicio se suspende tras unos minutos de inactividad y tarda unos 30
segundos en despertar la primera vez que alguien entra. Para una demo, entrá
vos primero para despertarlo. Los datos NO se pierden al suspenderse: están
en el disco persistente.

## Actualizar la app más adelante
Cada vez que hagas git push a la rama main, Render vuelve a desplegar solo.
Los datos del disco persistente se mantienen entre despliegues.
