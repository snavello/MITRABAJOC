# Mi Trabajo — Estado del proyecto

> **Documento histórico, congelado en agosto de 2026** (última actualización:
> migración a Postgres completa; rediseño de interfaz en curso en la rama
> `rediseno-ui`, después mergeado). **No se actualiza más.** El estado vigente
> del proyecto está en [`CLAUDE.md`](CLAUDE.md), sección "Estado actual"; la
> narrativa técnica en [`HISTORIAL.md`](HISTORIAL.md); y la descripción
> completa del sistema, generada del código, en
> `recursos/documentacion-tecnica.html` (landing `/entornos` → Recursos).
> Lo que sigue se conserva tal cual quedó.

Fue el documento para retomar sin perder contexto. En un chat nuevo, se subía este archivo
junto con validador-demo.zip y se pedía continuar desde "Próximo paso".

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
- templates/ (9 HTML, incluye portada.html del rediseño), static/ (2 SVG base +
  marca.css, sistema de diseño compartido)
- .claude/skills/diseno-mi-trabajo/ (reglas del sistema de diseño del rediseño)
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
- **Aislamiento entre sindicatos: total.** Marca por sindicato: 4 colores desde el
  rediseño de interfaz (base/primario/acento/secundario, ver más abajo — antes
  eran 3). El semáforo NUNCA toma la marca (colores fijos de estado). Semáforo
  ARCA: el trabajador resuelve el captcha y sube la captura, la IA la lee (no se
  automatiza el captcha). Parser de ARCA hecho y probado.

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

## 7. Rediseño de interfaz (rama `rediseno-ui`, en curso)
Sistema de diseño nuevo: portada del trabajador oscura, todo lo demás claro con
encabezado oscuro. Definido en `.claude/skills/diseno-mi-trabajo/SKILL.md` +
`static/marca.css`. Sindicato pasó de 3 a 4 colores (`color_base` nuevo, es el
único validado como oscuro — `_es_oscuro()` en main.py rechaza el alta/edición si
no lo es).

HECHO en esta rama:
- [x] `templates/portada.html`, ruta nueva `GET /app/inicio` (no reemplaza `/app`
      = Tu Recibo, que sigue intacta). Login/registro/selector redirigen ahí.
- [x] `color_base` en `Sindicato` (migración `04a7e9e26763`) + validación de
      luminosidad en alta/edición desde `/plataforma`.
- [x] `admin.html` y `plataforma.html`: encabezado oscuro pasa a usar
      `color_base` en vez de `color_primario` (que no estaba validado).
- [x] `trabajador.html`: encabezado y credencial usan `color_base`; botón
      principal y pestaña activa usan `color_acento` (antes usaban el color que
      hoy es "apoyo" — alineado con la portada, que ya usaba acento para su
      tarjeta destacada).
- [x] Suite de tests completa (22 archivos) verde, incluye `test_portada.py` y
      `test_color_base_sindicato.py` nuevos.
- [ ] Falta: mergear a `main` (el usuario la va a probar primero — dispara
      redeploy en Render + necesita `alembic upgrade head` por la columna nueva).

## 8. Próximo paso
Probar la rama `rediseno-ui` (local o en un preview de Render) y, si convence,
mergear a `main`. Al mergear: correr `alembic upgrade head` en la Shell de Render
para la columna `color_base`, y cargar el 4to color de cada sindicato real desde
`/plataforma` (si no se carga, cae al default `#0f1b2d`, válido pero no la marca
real del gremio).

Después del rediseño, retomar features pendientes: contenido real de Novedades,
Capacitación y Beneficios (las tres son "próximamente" hoy), endurecer para
producción (sacar la pestaña transitoria "Cambiar clave" del panel de
plataforma), y deep-linking desde la portada a una pestaña específica de `/app`.

### Para retomar en un chat nuevo
Subí este documento y decí: "Seguimos con Mi Trabajo. El rediseño de interfaz
está en la rama rediseno-ui, probado localmente; el próximo paso es [probarlo /
mergearlo a main / seguir con X pantalla]."

**Nota:** las secciones de arriba están desactualizadas — el rediseño de
interfaz, módulos habilitables, notificaciones y trámites ya se mergearon a
`main` hace varias sesiones (ver `CLAUDE.md`, que sí se mantiene al día). No
se reescribió este documento por completo; abajo se suma solo lo último.

## 9. Topes de base imponible (rama `topes-base-imponible`)
Corrige un bug real: el validador calculaba jubilación/INSSJP/obra social
sobre la remuneración completa, sin el tope máximo ni el piso mínimo de la
base imponible de la seguridad social (art. 9 Ley 24.241) — todo trabajador
que superaba el tope recibía discrepancias falsas. Detalle completo en
`CLAUDE.md` → "Topes de base imponible". 4 fases, todas en la rama:
tabla `TopeBaseImponible` (nacional, administrada desde `/plataforma`) +
`Formula.sujeto_a_tope`, lógica en `validador.py`, panel de plataforma y
checkbox en `/admin` → Fórmulas.

**Mantenimiento mensual obligatorio**: ANSES actualiza el tope todos los
meses — hay que cargar el valor nuevo en `/plataforma` → "Topes SS" cada
mes. Ya no quedan valores `SOSPECHOSO` (los 14 de enero 2025–febrero 2026
se corrigieron con datos reales del sindicato el 2026-08-15/16); siguen
`por_verificar` las vigencias previas a 2025, sin inconsistencia detectada.

Pendiente antes de mergear a `main`: verificar contra los 10 recibos de
prueba (5 debajo del tope, 5 por encima, 5 con errores plantados) que pasó
el usuario, con la guía de qué debería detectar cada uno.
