# CLAUDE.md — Mi Trabajo

Contexto del proyecto para Claude Code. Se lee al inicio de cada sesión.
Mantener este archivo actualizado cuando cambien decisiones o el estado.

## Qué es
App web para que trabajadores sindicalizados argentinos verifiquen si su recibo
de sueldo tiene bien calculados los aportes (jubilación, obra social, cuota
sindical, etc.) según el convenio de su sindicato. El trabajador sube foto/PDF del
recibo, una IA lo lee, y el sistema valida los aportes contra las fórmulas del
convenio. Es una **plataforma multi-sindicato**: la misma app sirve a varios
sindicatos, cada uno con su marca, conceptos y trabajadores, en aislamiento total.
Objetivo comercial: mostrarla a sindicatos y a un inversor como algo escalable.

## Stack y arquitectura
- **Backend:** FastAPI + Jinja2.
- **Base de datos:** Postgres en producción (Render gestionado). SQLite solo en
  desarrollo local. El motor se elige solo: si existe la variable DATABASE_URL usa
  Postgres; si no, cae a SQLite. Esa lógica está en db.py (variable USANDO_POSTGRES).
- **Migraciones:** Alembic. El esquema lo administra Alembic, NO create_all. En
  Postgres, los cambios de modelo se aplican con `alembic upgrade head` sin borrar
  datos. En SQLite dev, db.crear_tablas() sigue creando tablas.
- **IA:** API de Anthropic (claude-sonnet-4-6) para leer recibos y comprobantes.
- **Auth:** propia. Claves PBKDF2, sesiones como cookies firmadas HMAC (auth.py).
  NO se usa auth de terceros.
- **Python 3.12** fijado con .python-version (3.12.8) + variable PYTHON_VERSION en
  Render. Python 3.14 rompe SQLModel ("Field 'id' requires a type annotation").
- **Deploy:** GitHub + Render. Render sigue la rama main y redeploya con cada push.

## Archivos principales
- main.py — servidor y todas las rutas.
- db.py — modelos SQLModel, engine dual, acceso a datos, marca_sindicato().
- auth.py — hash de claves y sesiones.
- extractor.py — lee recibos y comprobantes de aportes con IA.
- validador.py — motor de validación de fórmulas.
- semaforo.py — lógica del semáforo de aportes (ARCA).
- cargar_demo.py — carga 2 sindicatos de demo desde cero (sin AEFIP).
- chequeo.py — autodiagnóstico de la instalación.
- migrations/ — Alembic (env.py + versions/: esquema inicial y logo).
- alembic.ini — config de Alembic.
- templates/ — 7 HTML (trabajador, admin, plataforma, sus logins, selector).
- static/ — 2 SVG base. (Ya NO existe static/logos/: los logos van en la base.)
- data/seed_aefip.json — semilla histórica; ya NO se carga por defecto.

## Los tres roles
1. Admin de plataforma — /plataforma con CUIT + PLATAFORMA_PASSWORD. Da de alta
   sindicatos (con marca y logo) y sus admins.
2. Admin de sindicato — /admin con CUIT + clave. Gestiona conceptos, fórmulas,
   trabajadores y reportes SOLO de su sindicato (aislamiento total).
3. Trabajador — /ingresar con CUIL + clave. Identidad única (un CUIL para toda la
   plataforma). Empadronamiento por sindicato: si el CUIL está en varios, elige;
   la app se pinta con la marca del elegido. 4 pestañas: Tu Recibo (default),
   Novedades, Mis Aportes (semáforo), Capacitación.

## Variables de entorno (Render)
- DATABASE_URL — Internal Database URL del Postgres de Render. Si está, usa Postgres.
- ANTHROPIC_API_KEY — clave de la API de Anthropic.
- PLATAFORMA_CUIT — CUIT del login de plataforma (default 20000000000).
- PLATAFORMA_PASSWORD — clave del login de plataforma.
- SESSION_SECRET — secreto para firmar cookies de sesión.
- PYTHON_VERSION — 3.12.8 (redundante con .python-version, a propósito).
- DB_PATH — solo dev local (SQLite). NO se usa en Render.

## Accesos de la demo
- Plataforma: CUIT 20000000000 + PLATAFORMA_PASSWORD.
- Admin UOM: CUIT 20111111110 / uom-demo.
- Admin Gastronómica: CUIT 20222222220 / fega-demo.
- Trabajador un solo sindicato: CUIL 20111111119 (UOM).
- Trabajador pluriempleo (ambos): CUIL 27222222224.

## Decisiones tomadas (no rediscutir sin motivo)
- **Motor: Render Postgres** (no Supabase). La app ya tiene auth propia, que es el
  mayor valor de Supabase; el Storage se resolvió guardando logos en la base.
  Migrar a Supabase después sería barato (pg_dump/restore, solo cambia DATABASE_URL).
- **Datos desde cero:** la demo arranca limpia, sin AEFIP. En producción los
  sindicatos se dan de alta desde el panel de plataforma.
- **Logos en la base (Opción B):** columnas logo_datos (bytes) + logo_mime en
  Sindicato; se sirven por la ruta /logo/{id}. Eliminó la necesidad del disco
  persistente (ya se borró el disco de Render). El campo `logo` es un flag no vacío.
  La URL del logo lleva ?v={tamaño} como sello de versión para romper cache al
  editar, y la ruta responde con Cache-Control no-cache.
- **JSON como JSONB en Postgres:** columnas alias (Concepto) y detalle (Reporte)
  son jsonb (indexables). En SQLite quedan JSON común.
- **Aislamiento entre sindicatos: total.** Marca por sindicato: color primario
  obligatorio (header/footer); secundario opcional (fondo de botones); acento
  opcional (reservado). El semáforo NUNCA toma la marca (colores fijos de estado:
  verde=pagado, amarillo=parcial, rojo=impago).
- **Semáforo ARCA:** el trabajador va a ARCA con un botón, resuelve el captcha él
  mismo y sube la captura/PDF; la IA la lee. NO se automatiza el captcha (frágil y
  zona gris legal). ARCA cubre jubilación y obra social, NO ART. Parser hecho y
  probado (estados pagado/parcial/impago/no_presentada/no_declarado).

## Estado actual
Migración a Postgres COMPLETA y desplegada en Render, mergeada a main. Verificado
en producción: 3 logins, aislamiento, pluriempleo, 4 pestañas, alta/edición de
sindicato, logos en base (con fix de cache aplicado). Disco persistente eliminado.

## Pendientes (features)
1. Novedades — hoy es estructura vacía con cartel "próximamente". Falta contenido
   real: mensajes/anuncios del sindicato al trabajador.
2. Capacitación — ídem, "próximamente". Falta contenido: índice de documentos y
   links de formación.
3. Quitar la pestaña transitoria "Cambiar clave" del panel de plataforma antes de
   producción (permite cambiar la clave de cualquier usuario; está marcada con una
   advertencia visible). Es un riesgo de seguridad, sacar antes de usuarios reales.

## Método de trabajo
- Por bloques chicos, verificando la lógica de verdad (rutas y funciones), no
  simulada. Preferir cambios quirúrgicos y probar antes de avanzar.
- Sd tiene skills intermedias de Python, trabaja en Argentina, deploya con
  GitHub + Render (push dispara redeploy).
- Preferencia: durante la construcción mostrar poco output intermedio; dar un
  resumen claro al final.

## Comandos útiles
- Correr local (SQLite): `uvicorn main:app --reload`
- Autodiagnóstico: `python chequeo.py`
- Cargar demo: `python cargar_demo.py` (¡correr alembic upgrade head antes si es Postgres!)
- Migraciones: `alembic upgrade head` (aplicar) / `alembic revision --autogenerate -m "msg"` (crear)
- En la Shell de Render, si `alembic` no se encuentra: usar `python -m alembic upgrade head`
