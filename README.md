# Mi Trabajo — plataforma multi-sindicato

App web para que trabajadores sindicalizados argentinos verifiquen si su
recibo de sueldo tiene bien calculados los aportes (jubilación, obra social,
cuota sindical, etc.) según el convenio de su sindicato. El trabajador sube
una foto o un PDF, una IA lo lee y el sistema valida los aportes contra las
fórmulas del convenio. La misma app sirve a varios sindicatos, cada uno con
su marca, su catálogo y sus trabajadores, en aislamiento total.

Alrededor de esa función central hay cuatro aplicaciones, una por rol:

| Rol | Entra por | Qué hace |
|-----|-----------|----------|
| Trabajador | `/ingresar` → `/app` | Tu recibo, Mis aportes (semáforo ARCA), Credencial con QR, Capacitación, Novedades, Trámites, Notificaciones, consultas sobre el convenio. Instalable como PWA. |
| Sindicato | `/admin` | Panel de quince pestañas: padrón, conceptos y fórmulas, aprendizaje, cotizantes, noticias, beneficios, notificaciones, trámites, empleadores, convenio, seccionales, administradores y el Panel Sindical con Asistente. |
| Empresa | `/ingresar-empresa` → `/empresa` | Notificaciones y trámites con el sindicato (solo si el sindicato tiene el módulo Empleadores). |
| Plataforma | `/plataforma` | Alta de sindicatos con marca y logo, módulos habilitados por sindicato, topes, configuración. |

Qué ve cada sindicato se decide por **módulos habilitables** (`modulos.py`).
El detalle de cada decisión vigente está en [`CLAUDE.md`](CLAUDE.md); la
narrativa de cómo se llegó a cada una, en [`HISTORIAL.md`](HISTORIAL.md).

## Stack

- **Backend:** FastAPI + Jinja2, Python 3.12 (`.python-version`).
- **Datos:** SQLModel sobre **Postgres** (Render), esquema administrado por
  **Alembic** (`migrations/`). Sin `DATABASE_URL` la app cae a SQLite, que
  se usa para los tests y como fallback sin Docker. Todo binario (logos,
  fotos, adjuntos, PDF) vive en la base, nunca en disco.
- **IA:** API de Anthropic. Tres modelos con un uso cada uno:
  `claude-sonnet-4-6` lee recibos y comprobantes (`extractor.py`),
  `claude-opus-5` responde las consultas sobre el convenio (`rag.py`) y
  `claude-sonnet-5` es el Asistente del Panel Sindical (`asistente.py`).
  Los embeddings del convenio son locales (`fastembed` + `pgvector`).
- **Auth propia:** claves con PBKDF2, sesiones como cookies firmadas, una
  cookie por rol, vencimiento por inactividad (`auth.py`).
- **Frontend:** plantillas Jinja2 + `static/marca.css` (sistema de diseño
  compartido), PWA con Web Push para el trabajador.

## Correr en tu PC

Requisitos: Python 3.12, Docker (para el Postgres local) y `poppler` para
leer PDFs (`brew install poppler` / `apt install poppler-utils`; en Windows,
agregar su carpeta `bin` al PATH).

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env              # y completar ANTHROPIC_API_KEY, SESSION_SECRET, PLATAFORMA_PASSWORD
docker compose up -d              # Postgres local (esperar el healthcheck)
alembic upgrade head              # crea o actualiza el esquema
python cargar_marca_plataforma.py # logo y colores de la plataforma (viven en la base)
python cargar_demo.py             # dos sindicatos de demo con sus accesos
uvicorn main:app --reload
```

- Trabajador: http://localhost:8000/ingresar · Sindicato: /admin · Empresa:
  /ingresar-empresa · Plataforma: /plataforma · Landing interna: /entornos.
- `python chequeo.py` revisa la instalación (`--api` prueba la clave de
  Anthropic; gasta créditos).
- Sin Docker: dejá `DATABASE_URL` vacío o comentado en `.env` y la app usa
  SQLite en `DB_PATH`. Sirve para mirar, no para probar migraciones.
- Para poblar un sindicato con datos sintéticos realistas (padrón, 5.000
  recibos, trámites, notificaciones): `python cargar_lote_sindicato.py
  --sindicato "NOMBRE"`. Ver "Lotes de datos sintéticos" en `CLAUDE.md`.
- Reset completo de la base local: `docker compose down -v && docker compose
  up -d && alembic upgrade head && python cargar_demo.py`.

Los accesos de la demo (CUIT y claves de cada rol) están en `CLAUDE.md`,
"Accesos de la demo".

## Tests

Dependencias de desarrollo (pytest, Playwright): `pip install -r
requirements-dev.txt`. Nunca van a `requirements.txt`: Render instala ese
archivo en cada deploy.

- **Suite unitaria**: los `test_*.py` de la raíz corren contra un SQLite
  temporal, sin nada levantado. **Cada archivo en su propio proceso**: los
  módulos comparten estado de import y se contaminan si corren juntos.

  ```
  for f in test_*.py; do python -m pytest -q "$f" || break; done      # bash
  Get-ChildItem test_*.py | ForEach-Object { python -m pytest -q $_.Name }   # PowerShell
  ```

  Corriendo un test como script (`python test_x.py`) no se carga
  `conftest.py`: con `DATABASE_URL` real en `.env` pega contra el Postgres
  de Docker. Anteponer `DATABASE_URL=` vacío.
- **Robots E2E** (`e2e/`, Playwright contra la app real): necesitan Docker,
  `uvicorn` corriendo y un lote cargado. Ver [`e2e/README.md`](e2e/README.md).
- Los sets que gastan créditos de la API (`probar_asistente.py`,
  `medicion_rag/`) se corren a mano, nunca en CI.

## Entornos y deploy

| Dónde | Qué corre | Cómo cambia |
|-------|-----------|-------------|
| Tu PC | tu rama, tu Postgres de Docker | cada vez que guardás |
| **Pruebas** — mitrabajo-pruebas.onrender.com | rama `main` | cada push a `main` redeploya (~90 s) |
| **Demo** — mitrabajo.onrender.com | rama `demo` | solo con `python promover_demo.py` |

Cada entorno tiene su propio Postgres; Alembic corre solo en cada deploy
(Pre-Deploy Command). El ciclo de un cambio, en una página, está en
[`FLUJO.md`](FLUJO.md); la infraestructura en
[`DESPLIEGUE_RENDER.md`](DESPLIEGUE_RENDER.md); el porqué del modelo en
[`PLAN_ENTORNOS.md`](PLAN_ENTORNOS.md).

En local y en Pruebas existe **`/entornos`**: una landing interna, detrás de
un PIN de ocho dígitos (`PIN_ENTORNOS`), con los ocho accesos (cuatro roles
× Pruebas/Demo), la versión que corre en cada uno y **Recursos**: la
documentación del proyecto catalogada con miniatura y fecha. Los documentos
que viajan con el código van en `recursos/` (`recursos.SEMILLA`); el resto se
sube desde la misma landing y queda en la base.

Variables de entorno: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SESSION_SECRET`,
`PLATAFORMA_CUIT`, `PLATAFORMA_PASSWORD`, `ENTORNO`, `PIN_ENTORNOS`,
`VAPID_*` (Web Push). El detalle, en `CLAUDE.md`, "Variables de entorno".

## Mapa del repositorio

| Archivo | Qué es |
|---------|--------|
| `main.py` | servidor y todas las rutas, agrupadas por actor |
| `db.py` | modelos SQLModel, motor dual, acceso a datos |
| `auth.py` | hash de claves y sesiones firmadas |
| `extractor.py` / `validador.py` / `semaforo.py` | lectura del recibo con IA, motor de fórmulas, semáforo de aportes |
| `dashboard.py` / `asistente.py` | Panel Sindical (agregados SQL) y su Asistente |
| `rag.py` | consultas sobre el convenio: PDF → fragmentos → embeddings → respuesta |
| `validaciones_tramite.py` | validaciones de los formularios de Trámites |
| `push.py` / `recursos.py` / `entorno.py` / `modulos.py` / `errores.py` / `version.py` | Web Push, Recursos de la landing, entorno y distintivo, módulos, códigos de error, versiones |
| `migrations/` | Alembic |
| `templates/` · `static/` | HTML de las cuatro apps · CSS, JS, fuentes, íconos |
| `recursos/` | documentos versionados que muestra la landing |
| `docs/generador/` | genera `recursos/documentacion-tecnica.html` leyendo el código |
| `e2e/` | robots de QA con Playwright |
| `cargar_*.py`, `promover_demo.py`, `clonar_demo_a_pruebas.py`, `pg_cliente.py`, `medir_dashboard.py` | operación: cargas, promoción a la demo, clonado de datos, mediciones |

## Documentación

- [`CLAUDE.md`](CLAUDE.md) — contexto, reglas y estado actual. Se lee al
  inicio de cada sesión de Claude Code; corto a propósito.
- [`HISTORIAL.md`](HISTORIAL.md) — changelog técnico detallado: por qué se
  hizo cada cosa, bugs y su causa.
- **Documentación técnica generada del código** —
  `recursos/documentacion-tecnica.html` (funcionalidades por rol,
  arquitectura con diagramas, componentes y rutas, modelo de datos). Se ve
  en `/entornos` → Recursos y se regenera con
  `python docs/generador/extraer.py && python docs/generador/generar.py`.
- Planes y fichas: [`FLUJO.md`](FLUJO.md), [`DESPLIEGUE_RENDER.md`](DESPLIEGUE_RENDER.md),
  [`PLAN_ENTORNOS.md`](PLAN_ENTORNOS.md), [`PLAN_RAG_CONVENIO.md`](PLAN_RAG_CONVENIO.md),
  [`BACKLOG.md`](BACKLOG.md), [`docs/DASHBOARD.md`](docs/DASHBOARD.md),
  [`docs/ASISTENTE_PANEL.md`](docs/ASISTENTE_PANEL.md),
  [`docs/cct-1875-bancarios.md`](docs/cct-1875-bancarios.md).
- Históricos, congelados: [`SPRINT_REFORMA.md`](SPRINT_REFORMA.md) (plan de
  la Reforma Laboral tal como se escribió; ya está completo) y
  [`ESTADO_DEL_PROYECTO.md`](ESTADO_DEL_PROYECTO.md) (estado a la migración
  a Postgres).
