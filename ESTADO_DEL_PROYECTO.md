# Mi Trabajo — Estado del proyecto

Documento para retomar sin perder contexto. En un chat nuevo, subí este archivo
junto con validador-demo.zip y pediá continuar desde "Próximo paso".

_Última actualización: migración a Postgres COMPLETA (rama migracion-postgres),
verificada sobre Postgres real. Pendiente: desplegar en Render y mergear a main._

---

## 1. Qué es Mi Trabajo
App web para que trabajadores sindicalizados argentinos verifiquen si su recibo
tiene bien calculados los aportes según el convenio de su sindicato. Suben foto/PDF,
una IA lo lee y el sistema valida contra las fórmulas del convenio. Es una
**plataforma multi-sindicato**: misma app, varios sindicatos con su marca,
conceptos y trabajadores, en aislamiento total. Objetivo comercial: mostrarla a
sindicatos y a un inversor como algo escalable.

## 2. Arquitectura y stack
- **Backend:** FastAPI + Jinja2.
- **Base de datos:** SQLModel sobre **Postgres** en producción (Render gestionado);
  SQLite solo en desarrollo local. El motor se elige solo: si hay DATABASE_URL usa
  Postgres, si no cae a SQLite. Una línea en db.py, el resto de la app no cambia.
- **Migraciones de esquema:** **Alembic**. El esquema ya no se crea con create_all
  en producción; lo administra Alembic (alembic upgrade head). Esto permite
  evolucionar el modelo SIN borrar la base (antes había que borrar y recargar).
- **IA:** API de Anthropic (claude-sonnet-4-6) para leer recibos y comprobantes.
- **Auth:** claves PBKDF2, sesiones como cookies firmadas HMAC. Auth propia
  (no se usa auth de terceros). Módulo auth.py.
- **Python 3.12 fijado** (.python-version + variable PYTHON_VERSION en Render).
- **Despliegue:** GitHub + Render.

### Archivos (dentro de validador-demo.zip)
- main.py, db.py, auth.py, extractor.py, validador.py, semaforo.py
- cargar_demo.py (2 sindicatos demo, desde cero, sin AEFIP)
- chequeo.py (autodiagnóstico)
- migrations/ (Alembic: env.py + versions/ con esquema inicial y logo)
- alembic.ini
- templates/ (7 HTML), static/ (2 SVG base)
- data/seed_aefip.json (semilla histórica; ya NO se carga por defecto)

## 3. Los tres roles
1. **Admin de plataforma** — /plataforma con CUIT + PLATAFORMA_PASSWORD. Da de alta
   sindicatos (con marca y logo) y sus admins.
2. **Admin de sindicato** — /admin con CUIT + clave. Gestiona conceptos, fórmulas,
   trabajadores y reportes SOLO de su sindicato (aislamiento verificado).
3. **Trabajador** — /ingresar con CUIL + clave. Identidad única (un CUIL para toda
   la plataforma). Empadronamiento por sindicato: si el CUIL está en varios, elige;
   la app se pinta con la marca del elegido.

### Accesos de la demo
- Plataforma: CUIT 20000000000 + PLATAFORMA_PASSWORD
- Admin UOM: CUIT 20111111110 / uom-demo
- Admin Gastronómica: CUIT 20222222220 / fega-demo
- Trabajador un solo sindicato: CUIL 20111111119 (UOM)
- Trabajador pluriempleo (ambos): CUIL 27222222224

## 4. Decisiones tomadas (para no rediscutir)
- **Motor:** Render Postgres (no Supabase). Razón: la app ya tiene auth propia, que
  es el mayor valor de Supabase; Storage se resolvió guardando logos en la base.
  Migrar a Supabase después sería barato (Postgres a Postgres, pg_dump/restore,
  solo cambia DATABASE_URL). Elegir Render ahora NO encierra.
- **Datos desde cero:** la demo arranca limpia, sin AEFIP. En producción los
  sindicatos se dan de alta desde el panel.
- **Logos en la base (Opción B):** columnas logo_datos (bytes) + logo_mime en
  Sindicato; se sirven por la ruta /logo/{id}. Elimina la necesidad del disco
  persistente: todo el estado vive en Postgres y se respalda con la base.
- **JSON como JSONB en Postgres:** columnas alias (Concepto) y detalle (Reporte)
  son jsonb, indexables y consultables. En SQLite quedan JSON común.
- **Aislamiento entre sindicatos: total.** Marca por sindicato (primario obligatorio;
  secundario/acento opcionales). El semáforo NUNCA toma la marca (colores fijos de
  estado). Semáforo ARCA: el trabajador resuelve el captcha y sube la captura, la
  IA la lee (no se automatiza el captcha). Parser de ARCA hecho y probado.

## 5. Estado de la migración a Postgres (rama migracion-postgres)
HECHO y verificado sobre Postgres real:
- [x] Engine dual SQLite/Postgres con pool (pool_pre_ping, reciclado 5 min).
- [x] Driver psycopg[binary] en requirements.
- [x] Alembic funcionando en ambos motores (render_as_batch para SQLite).
- [x] Migración inicial (7 tablas, FKs, índices) + JSONB en Postgres.
- [x] Migración incremental de logo (probada: agrega columnas sin borrar datos).
- [x] Demo desde cero sin AEFIP.
- [x] Logos en base + ruta /logo/{id}. Carpeta static/logos eliminada.
- [x] Trampas resueltas: secuencias tras id explícito, orden de FK en seed
      (SQLite lo perdonaba, Postgres no), NOT NULL con server_default, import de
      sqlmodel en migraciones.
- [x] Verificado: 3 logins, aislamiento, pluriempleo, 4 pestañas, alta de sindicato
      nuevo sin choque de id, JSONB, logo sube/guarda/sirve. SQLite dev intacto.

## 6. Cómo trabajamos (método)
- Por bloques, verificando la lógica de verdad (rutas y funciones), no simulada.
- Cada sesión larga produce ZIP + este documento actualizado para continuidad.
- Nota de entorno de desarrollo: curl no puede hacer POST al server local (proxy),
  se usa TestClient de FastAPI. Postgres real se levanta en el contenedor para
  probar el modo producción.

## 7. Próximo paso
**Desplegar la rama migracion-postgres en Render** siguiendo DESPLIEGUE_RENDER.md:
1. Crear Postgres en Render, copiar Internal Database URL.
2. Cargar variables (DATABASE_URL, ANTHROPIC_API_KEY, PLATAFORMA_CUIT,
   PLATAFORMA_PASSWORD, SESSION_SECRET, PYTHON_VERSION).
3. En la Shell: alembic upgrade head, luego python cargar_demo.py.
4. Prueba de humo: 3 logins + aislamiento + registro de trabajador.
5. Eliminar el disco persistente /var/data (ya no se usa).
6. Si todo anda: mergear migracion-postgres a main.

Después de la migración, retomar features pendientes: contenido real de Novedades
y Capacitación, y endurecer para producción (sacar la pestaña transitoria
"Cambiar clave" del panel de plataforma).

### Para retomar en un chat nuevo
Subí validador-demo.zip y este documento, y decí:
"Seguimos con Mi Trabajo. La migración a Postgres está hecha en la rama
migracion-postgres; el próximo paso es desplegarla en Render / mergear."
