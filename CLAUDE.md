# CLAUDE.md — Mi Trabajo

Contexto del proyecto para Claude Code. Se lee al inicio de cada sesión.
Mantener este archivo actualizado cuando cambien decisiones o el estado.

**Este archivo se mantiene deliberadamente corto** — es lo que se carga
automático en CADA turno de CADA sesión, así que su tamaño es un costo fijo
de latencia. El detalle técnico completo de cada feature (por qué se hizo
así, bugs encontrados y su causa real, decisiones de UI puntuales) vive en
[`HISTORIAL.md`](HISTORIAL.md), que NO se carga automático — abrilo cuando
el trabajo puntual lo necesite. Al sumar una sección nueva acá: si es una
decisión/regla vigente, va en CLAUDE.md corto; si es la narrativa de cómo
se llegó a esa decisión, va en HISTORIAL.md.

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
- **Base de datos:** Postgres en producción (Render gestionado). El motor se
  elige solo: si existe la variable DATABASE_URL usa Postgres; si no, cae a
  SQLite. Esa lógica está en db.py (variable USANDO_POSTGRES). Desarrollo
  local usa Postgres vía Docker por defecto desde 2026-08-16 (ver "Desarrollo
  local con Postgres" más abajo) — SQLite queda como fallback sin Docker.
- **Migraciones:** Alembic. El esquema lo administra Alembic, NO create_all. En
  Postgres (producción y ahora también desarrollo local), los cambios de
  modelo se aplican con `alembic upgrade head` sin borrar datos. Solo en
  SQLite (fallback sin Docker) db.crear_tablas() sigue creando tablas.
- **IA:** API de Anthropic (claude-sonnet-4-6) para leer recibos y comprobantes.
- **Auth:** propia. Claves PBKDF2, sesiones como cookies firmadas HMAC (auth.py).
  Sesión por INACTIVIDAD, no por tiempo fijo desde el login: 15 minutos sin uso
  (`auth.IDLE_TIMEOUT_SEGUNDOS`). El middleware `renovar_sesion_por_actividad`
  (main.py) reemite la cookie en cada request autenticado; un usuario activo
  nunca se desloguea solo. NO se usa auth de terceros.
  **Cookie separada por rol** (`COOKIES_POR_ROL` en main.py:
  `sesion_sindicato`/`sesion_plataforma`/`sesion_trabajador`/`sesion_empleador`)
  — cada rol lee y renueva SOLO su propia cookie, nunca una genérica
  compartida. Cualquier rol nuevo que se agregue tiene que sumar su cookie acá.
  Regla vigente por un bug real (dos pestañas con roles distintos se pisaban
  la sesión) — detalle completo en HISTORIAL.md, sección "Auth".
  **Excepciones sin manejar en un POST de página completa** (`/admin`,
  `/plataforma`) redirigen al login o al panel con un aviso, en vez de
  mostrar el JSON crudo de FastAPI — `sesion_vencida_o_denegada`/
  `error_no_manejado` en main.py, con `_es_navegacion_de_pagina`/`_panel_de`/
  `_rol_de` como helpers. Detalle en HISTORIAL.md.
- **Python 3.12** fijado con .python-version (3.12.8) + variable PYTHON_VERSION en
  Render. Python 3.14 rompe SQLModel ("Field 'id' requires a type annotation").
- **Deploy:** GitHub + Render. Render sigue la rama main y redeploya con cada push.

## Archivos principales
- main.py — servidor y todas las rutas.
- db.py — modelos SQLModel, engine dual, acceso a datos, marca_sindicato().
- auth.py — hash de claves y sesiones.
- permisos.py — catálogo de secciones del panel y cálculo de permisos
  efectivos (áreas y usuarios del sindicato).
- extractor.py — lee recibos y comprobantes de aportes con IA.
- validador.py — motor de validación de fórmulas.
- semaforo.py — lógica del semáforo de aportes (ARCA).
- cargar_demo.py — carga 2 sindicatos de demo desde cero (sin AEFIP).
- chequeo.py — autodiagnóstico de la instalación.
- migrations/ — Alembic (env.py + versions/).
- alembic.ini — config de Alembic.
- templates/ — HTML de las 4 apps (trabajador, sindicato, plataforma,
  empresa: portada + panel de cada una, logins, selectores, verificación
  pública de credencial).
- static/ — 2 SVG base + marca.css (sistema de diseño compartido) +
  static/fonts/ (Barlow Condensed, licencia SIL OFL).
- data/seed_aefip.json — semilla histórica; ya NO se carga por defecto.
- data/topes_ss.csv — vigencias de topes de la seguridad social (ver
  "Topes de base imponible" en HISTORIAL.md).
- .claude/skills/diseno-mi-trabajo/ — skill con las reglas del sistema de diseño;
  .claude/skills/frontend-design/ — skill oficial de Anthropic para dirección visual general.
- **HISTORIAL.md** — changelog técnico detallado, no se carga automático.
- **BACKLOG.md** — hallazgos técnicos pendientes (bugs pre-existentes
  encontrados al pasar, deudas, ideas evaluadas y pospuestas). No se carga
  automático. Los pendientes de PRODUCTO siguen en "Pendientes (features)"
  más abajo; BACKLOG.md es lo técnico. Al encontrar un bug fuera del
  alcance del bloque en curso, anotarlo ahí en vez de desviar el trabajo.

## Los cuatro roles
1. Admin de plataforma — /plataforma con CUIT + PLATAFORMA_PASSWORD. Da de alta
   sindicatos (con marca y logo) y sus admins. Login → `/plataforma/inicio`
   (portada de tarjetas) → `/plataforma` (panel de siempre).
2. Usuario de sindicato — /admin con CUIT + clave. Dos clases:
   **Super Admin** (todo el panel, incluida la gestión de áreas y usuarios) y
   **usuario de área** (solo las secciones que le da su área). Siempre SOLO
   de su sindicato (aislamiento total). Login → `/admin/inicio` (portada) →
   `/admin` (panel con la tira de pestañas armada según sus permisos).
   Ver "Áreas y permisos" más abajo.
3. Trabajador — /ingresar con CUIL + clave. Identidad única (un CUIL para toda la
   plataforma). Empadronamiento por sindicato: si el CUIL está en varios, elige;
   la app se pinta con la marca del elegido. Login/elección → `/app/inicio`
   (portada) → `/app` ("Tu Recibo", 6 pestañas: Tu Recibo, Credencial,
   Novedades, Mis Aportes/semáforo, Capacitación, Trámites).
4. Empresa (empleador) — /ingresar-empresa con CUIT + clave (autorregistro).
   Identidad única por CUIT, puede estar dado de alta en varios sindicatos
   (mismo criterio que pluriempleo). Login/elección → `/empresa/inicio`
   (portada) → `/empresa` (2 pestañas: Notificaciones, Trámites). Solo existe
   si el sindicato tiene el módulo `"empleadores"` habilitado — ver
   "Empleadores" en HISTORIAL.md.

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
- Usuario de área UOM: CUIT 20111111111 / legal-uom (Secretaría Legal, Rosario).
- Usuario de área Gastronómica: CUIT 20222222221 / tesoreria-fega (Tesorería).
  Entrar con uno de estos y con el admin muestra el mismo panel recortado distinto.
- Trabajador un solo sindicato: CUIL 20111111119 (UOM).
- Trabajador pluriempleo (ambos): CUIL 27222222224.
- Empresa un solo sindicato: CUIT 30999888776 (UOM) — registrarse en `/ingresar-empresa`.
- Empresa multisindicato (ambos): CUIT 30111222339.

## Decisiones tomadas (no rediscutir sin motivo)
- **Motor: Render Postgres** (no Supabase). La app ya tiene auth propia, que es el
  mayor valor de Supabase; el Storage se resolvió guardando logos en la base.
- **Datos desde cero:** la demo arranca limpia, sin AEFIP. En producción los
  sindicatos se dan de alta desde el panel de plataforma.
- **Logos en la base:** columnas logo_datos (bytes) + logo_mime en Sindicato;
  se sirven por /logo/{id}, con `?v={logo_v}` (largo en bytes) como sello de
  versión para romper cache al editar. Mismo patrón para firma del sindicato,
  foto de perfil de trabajador/empleador, imágenes de noticias/beneficios,
  archivos adjuntos de notificaciones/trámites — todo bytes en la base, nunca
  disco (no hay disco persistente en Render).
- **JSON como JSONB en Postgres:** columnas alias (Concepto) y detalle (Reporte)
  son jsonb (indexables). En SQLite quedan JSON común.
- **Aislamiento entre sindicatos: total.** Marca por sindicato: 4 colores
  (`color_base`, `color_primario`, `color_acento`, `color_secundario`), inyectados
  como `--marca-base/primario/acento/apoyo` en cada plantilla. `color_base` es el
  único validado como oscuro (`_es_oscuro()` en main.py, umbral de luminancia
  percibida < 140/255) — es el fondo de la portada del trabajador y de todos los
  encabezados oscuros; si no es oscuro, el alta/edición de sindicato se rechaza.
  El semáforo NUNCA toma la marca (colores fijos de estado: verde=pagado,
  amarillo=parcial, rojo=impago). Mismo criterio de aislamiento total se
  extendió a Empleadores (ver HISTORIAL.md).
- **Semáforo ARCA:** el trabajador va a ARCA con un botón, resuelve el captcha él
  mismo y sube la captura/PDF; la IA la lee. NO se automatiza el captcha (frágil y
  zona gris legal). ARCA cubre jubilación y obra social, NO ART. Estados:
  pagado/parcial/impago/no_presentada/no_declarado/informado (ver
  "Ajustes de recibos, aportes y trámites" en HISTORIAL.md para "INFORMADO").
- **Tamaño de logos, 76px unificado** en toda la app (61px en mobile) salvo
  en los 3 logins standalone, donde el logo de plataforma es más grande a
  propósito (148px desktop / 85px mobile) — detalle en HISTORIAL.md.
- **Logos sin fondo blanco forzado**: un PNG con fondo transparente se ve
  transparente de verdad; si un sindicato quiere fondo de color, lo sube ya
  incluido en el archivo. Excepción: el círculo de iniciales de fallback (sin
  logo cargado) sí conserva fondo, porque no es un logo real.
- **Sistema de módulos habilitables** (`modulos.py`): el admin de plataforma
  elige por sindicato qué funcionalidades tiene activas (catálogo en
  `MODULOS`, los de origen en `MODULOS_INICIALES`). Trabajadores y
  Seccionales quedan SIEMPRE visibles, no dependen de ningún módulo. El
  backend rechaza (403, `_exigir_modulo`) igual que esconde el botón — no
  alcanza con ocultar en el cliente. Cualquier feature grande nueva evalúa
  primero si necesita su propia entrada acá (opt-in, no en
  `MODULOS_INICIALES`) en vez de estar siempre encendida para todos.
- **Desarrollo local con Postgres vía Docker** (no SQLite) desde 2026-08-16
  — paridad con producción para probar migraciones de Alembic antes de
  llegar a Render. `docker-compose.yml` en la raíz. Los tests (`test_*.py`)
  siguen en SQLite temporal, sin cambios — ver "Comandos útiles" y detalle
  en HISTORIAL.md.
- **Aislamiento total entre sistemas de trabajador y empleador**: cuando un
  concepto existe para los dos actores (notificaciones, trámites), se
  duplican tablas y rutas en vez de compartirlas, a costa de más código
  repetido — decisión explícita, no un default del proyecto.
- **Patrón portada + panel interno**, repetido para los 3 roles con login
  (`/app/inicio`+`/app`, `/admin/inicio`+`/admin`, `/empresa/inicio`+`/empresa`)
  — cualquier rol nuevo que se agregue debería seguir el mismo patrón.

## Estado actual (actualizado 2026-08-22)
Todo lo listado acá está mergeado a `main` y desplegado (Render sigue `main`,
cada push redeploya).

**SPRINT_REFORMA.md (adaptación a la Reforma Laboral, Dto 407/2026) —
COMPLETO**, los 5 puntos de los dos sprints originales: extractor bi-formato
(clásico + Anexo III, con `contribuciones_patronales`/`costo_laboral_total`/
`ultimo_deposito`), tope sindical 2% configurable solo por plataforma
(`test_tope_sindical.py`), alerta temprana por fecha de último depósito en
el semáforo, contenido real de Capacitación, y el flujo de envío consentido
al sindicato con disclaimer (`/api/enviar-sindicato`, acredita afiliado
cotizante art. 21 bis Dto 407/2026). El archivo `SPRINT_REFORMA.md` en la
raíz documenta el plan tal cual se escribió — no se actualiza
retroactivamente, esta sección es la fuente de verdad sobre qué ya está hecho.

**Por orden cronológico, todo lo construido DESPUÉS de SPRINT_REFORMA.md**
(pedidos nuevos del usuario, ninguno estaba en el plan original; el detalle
técnico completo de cada uno está en HISTORIAL.md, buscar por el mismo título):
1. Migración a Postgres (Render gestionado).
2. Rediseño de interfaz v1 — portada con tarjetas + sistema de 4 colores.
3. Sistema de módulos habilitables por sindicato.
4. Notificaciones (sindicato → trabajador, dirigidas por CUIL/empresa/seccional/provincia).
5. Trámites (formularios dinámicos, numeración de expediente, 5 estados).
6. Rediseño visual "modelo Nike" — vidrio/grano/tipografía condensada, portada clara/oscura por sindicato.
7. Topes de base imponible (art. 9 Ley 24.241) en jubilación/INSSJP/obra social.
8. **Empleadores** — cuarto actor completo: CRUD, login propio, notificaciones y trámites externos, mirror aislado del sistema de trabajador.
9. Portada de `/empresa` con tarjetas, perfil de empleador editable con foto, globos de notificaciones propagados por los 3 niveles de UI.
10. Ajustes puntuales: recibos reportados también cuentan para el padrón de afiliados cotizantes; estado "INFORMADO" de ARCA; popup de cambio de estado en Trámites (reemplazado por el punto 11).
11. **Chat de Trámites estilo WhatsApp** — reemplaza Notas+Historial por un hilo cronológico único con modal para leer/responder/cambiar estado.
12. **Áreas y permisos del sindicato** (SPRINT_AREAS.md, 6 fases) — Super
    Admin + usuarios de área con permisos por sección, alcance por
    seccional, trámites ruteados por área receptora (trabajador y empresa) y
    notificaciones acotadas. Ver "Áreas y permisos del sindicato" arriba.

**Qué queda pendiente** — ver "Pendientes (features)" más abajo para el
detalle; resumen: (a) capacitación por-sindicato (además de la fija de
plataforma), (b) sacar "Cambiar clave" transitorio de plataforma antes de
producción real, (c) verificar los topes SS previos a 2025, (d) evaluar si
el editor de lienzo libre de Trámites llega a justificarse, (e) staging
real en Render (sin urgencia, tiene costo).

**Ojo con el punto 12**: es lo único de la lista que NO está en `main`
todavía. Vive en la rama `areas-permisos`, con las 6 fases commiteadas
localmente y sin pushear. Todo lo demás sí está desplegado.

**Próximo paso**: pushear `areas-permisos` y mergearla a `main`. Antes de
eso, en Render hay que correr `python -m alembic upgrade head` — el sprint
trae 3 migraciones y dos de ellas MUEVEN DATOS (los usuarios existentes
pasan a Super Admin, se crea "Sede Central"/"Mesa de Entradas" por
sindicato, y los trabajadores sin seccional se reasignan).

Aparte del código: contenido de marketing para el rebranding a "Colm3na"
(documento aparte, no código, sin sección propia acá). El rebranding
todavía NO tocó nada de la app.

## Pendientes (features)
1. Capacitación por-sindicato: hoy solo hay contenido FIJO de plataforma
   ("Entendé tu nuevo recibo de sueldo", vale para todos por igual porque
   es ley nacional). Falta diseñar cómo cada sindicato podría sumar SU
   PROPIO contenido además de eso.
2. Quitar la pestaña transitoria "Cambiar clave" del panel de plataforma antes de
   producción (permite cambiar la clave de cualquier usuario; está marcada con una
   advertencia visible). Es un riesgo de seguridad, sacar antes de usuarios reales.
   Se deja a propósito mientras dure la etapa de demos y pruebas.
3. Los topes de base imponible previos a 2025 siguen marcados
   `por_verificar` (menor urgencia, sin inconsistencia detectada) — ver
   "Topes de base imponible" en HISTORIAL.md.
4. **Editor visual de formularios de Trámites con lienzo libre (drag X/Y)**,
   evaluado y pospuesto: se implementó en su lugar un camino más liviano
   (ancho por campo + reordenar arrastrando en lista + vista previa en
   vivo) que cubre el mismo problema real a menor costo — ver "Constructor
   visual de Trámites" en HISTORIAL.md. Revisar si en algún momento el
   lienzo libre se justifica.
5. Entorno de staging real en Render (rama + servicio + base Postgres
   aparte) para probar deploys completos antes de tocar la demo de
   producción — sin urgencia, tiene costo real (no hay free tier viable).

## Áreas y permisos del sindicato
El sindicato arma sus propios perfiles de acceso, sin pasar por plataforma.
Plan completo y las 14 decisiones en [`SPRINT_AREAS.md`](SPRINT_AREAS.md);
narrativa en HISTORIAL.md. Reglas vigentes:

- **La unidad de permiso es la SECCIÓN del panel, no el módulo**
  (`permisos.py`). Un módulo abre varias secciones: `recibos` abre cinco.
  Los módulos del sindicato FILTRAN qué secciones se pueden ofrecer.
- `Area` (organizativa) es independiente de `Seccional` (geográfica). El
  usuario tiene una de cada una: "Legales de Rosario".
- **La seccional acota lo que se ve**: trámites y notificaciones alcanzan
  solo a trabajadores de la seccional del usuario. `Seccional.ve_todas` es
  la excepción (nace tildada en "Sede Central"). Una sola regla de alcance
  para todo el panel — `db.alcance_seccional()` / `db.cuiles_alcanzados()`.
- **Permisos individuales suman Y restan** sobre los del área; el bloqueo
  gana siempre (`permisos.calcular_efectivos`).
- **Gateo en un solo lugar**: `exigir_sindicato()` resuelve la sección
  mirando la ruta que FastAPI matcheó contra `PERMISOS_RUTAS` (main.py). Una
  ruta `/admin/*` nueva que no se agregue ahí **nace cerrada**;
  `test_areas_rutas.py` recorre `app.routes` y avisa.
- **Los permisos se leen de la base en cada request**, nunca del token: si
  viajaran en la cookie, revocar no tendría efecto hasta que venza la sesión.
- **Esconder la pestaña NO es el control**: `/admin` arma una sola página
  con todos los paneles adentro, así que la ruta tampoco le pasa a la
  plantilla los datos de las secciones que el usuario no tiene.
- **Trámites se rutea por área**: el formulario declara 1..N áreas
  receptoras (obligatorio). Si hay dos, las dos lo ven y la primera que lo
  toma queda a cargo; la otra pasa a solo lectura. Igual en los trámites de
  empresa, con una diferencia a propósito: ahí NO hay recorte por seccional
  (una empresa no pertenece a una seccional).
- El trabajador/la empresa ven el **área** que respondió, nunca el nombre de
  la persona (`_detalle_sin_datos_internos` en main.py). En el panel sí.
- No es un módulo opt-in: es infraestructura del panel, siempre disponible.

## Noticias (sindicato → trabajador)
Modelo `Noticia` (db.py): título, bajada, texto completo (con auto-link de
URLs), vigencia por fecha_desde/fecha_hasta (ambas obligatorias), hasta 2
imágenes. Admin la carga en `/admin` → Noticias. El trabajador la ve en la
portada (hasta 3) y en la pestaña Novedades — detalle en HISTORIAL.md.

## Beneficios (sindicato → trabajador)
Modelo `Beneficio` (db.py): rubro, descripción, link opcional, vigencia
(ambas fechas obligatorias), una imagen. Carrusel en la portada del
trabajador (`.carrusel-wrap`/`.carrusel-track` en marca.css) — detalle en
HISTORIAL.md.

## Seccionales del sindicato
Modelo `Seccional` (db.py): sindicato_id, nombre, dirección. CRUD simple en
`/admin` → Seccionales. `Trabajador.seccional_id` opcional. Noticias y
Beneficios pueden dirigirse por seccional (`destino_seccionales`, lista
vacía = todas) — detalle en HISTORIAL.md.

## Áreas y Usuarios (self-service)
`/admin` → pestaña "Áreas y Usuarios", visible **solo para el Super Admin**.
Dos sub-pestañas: CRUD de áreas con sus permisos, y alta/edición de usuarios
(rol, área, seccional y ajustes individuales). Todo scopeado a su
`sindicato_id`. Cambiar la clave de un usuario YA EXISTENTE sigue siendo
solo vía plataforma. **No se puede desactivar NI DEGRADAR al último Super
Admin activo** — el sindicato quedaría sin nadie que pueda administrarlo.

## Alerta de posible adulteración en recibos
`extractor.extraer()` evalúa señales de edición en totales/CUIL/CUIT/fechas
(alta certeza únicamente). No bloquea al trabajador; guarda el archivo en
`ReciboSospechoso`, visible solo por el admin de **plataforma** en "Recibos
con alerta" — detalle en HISTORIAL.md.

## Versionado
`version.py`: `VERSION_TRABAJADOR`/`VERSION_ADMIN`/`VERSION_PLATAFORMA` +
`FECHA_VERSION`, actualizados a mano en cada deploy (el número lo indica el
usuario). **Regla para incrementar `release.patch`**: solo arreglos → +1 al
patch; arreglos + funcionalidad nueva en el mismo deploy → +1 en los dos
(ej. 0.02.01 → 0.03.01). Acordarse de esto SIN que el usuario lo pida.

## Hallazgo pendiente, no arreglado
`db.cargar_seed_si_vacio()` sigue disparando el seed histórico de AEFIP al
recrear la base local desde cero sin correr `cargar_demo.py` antes —
aparece un sindicato "AEFIP" fantasma con id=1. No afecta producción
(nunca se recrea la base de Render desde cero) — detalle en HISTORIAL.md.

## Método de trabajo
- Por bloques chicos, verificando la lógica de verdad (rutas y funciones), no
  simulada. Preferir cambios quirúrgicos y probar antes de avanzar.
- Sd tiene skills intermedias de Python, trabaja en Argentina, deploya con
  GitHub + Render (push dispara redeploy).
- Preferencia: durante la construcción mostrar poco output intermedio; dar un
  resumen claro al final.
- Sesiones largas acumulan contexto y eso enlentece cada respuesta — para
  bloques de trabajo sin relación entre sí, preferir abrir una sesión nueva
  en vez de seguir apilando todo en la misma conversación.

## Comandos útiles
- Correr local (Postgres vía Docker): `docker compose up -d`,
  después `alembic upgrade head`, después `uvicorn main:app --reload`.
- Correr local (SQLite, sin Docker): `uvicorn main:app --reload`
  (con `DATABASE_URL` comentado/ausente en `.env`).
- Autodiagnóstico: `python chequeo.py`
- Cargar demo: `python cargar_demo.py` (¡correr alembic upgrade head antes si es Postgres!)
- Migraciones: `alembic upgrade head` (aplicar) / `alembic revision --autogenerate -m "msg"` (crear)
- En la Shell de Render, si `alembic` no se encuentra: usar `python -m alembic upgrade head`
- Reset completo de la base local Postgres: `docker compose down -v && docker compose up -d`
  (espera a que el healthcheck pase) `&& alembic upgrade head && python cargar_demo.py`
- Tests: `bash correr_suite.sh` — corre CADA `test_*.py` por separado,
  nunca `pytest -q` batcheado (los módulos comparten estado de import y se
  contaminan entre archivos si corren en el mismo proceso pytest).
  **El chequeo mira `failed|error`, NO `passed`**: un archivo que termina en
  `"13 failed, 1 passed"` contiene la palabra "passed", así que un patrón
  ingenuo lo da por OK y esconde fallas reales. Ya pasó.
