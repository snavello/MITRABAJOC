---
proyecto: mitrabajo
etapa: 2
generado: 2026-09-20
commit: 0d41874
metodo: lectura del código con Claude Code (Explore), no de memoria
rutas: 226
publicas: 30
uploads: 20
---

# Etapa 2 — Mapa técnico de la superficie

Generado desde el código en el commit `0d41874` (226 rutas, todas en
`main.py`; no hay `APIRouter`). Lo que dice este archivo son **hechos
observados en el código**, no hallazgos: un hallazgo nace cuando un test de
la etapa 5 lo confirma contra el entorno y se clasifica en la 7. Las
"observaciones" del final son las hipótesis que el mapeo dejó, para que el
modelo de amenazas y el catálogo las tomen.

## 1. Rutas y guardianes

| Guardián | Definición | Rutas |
|---|---|---|
| `exigir_sindicato(request)` | `main.py:1060` — cookie `sesion_sindicato` + `_exigir_permiso_de_ruta` (`PERMISOS_RUTAS`, falla cerrado) | ~95 |
| `exigir_plataforma(request)` | `main.py:1076` — cookie `sesion_plataforma` | 18 |
| `sesion_actual(request, "trabajador")` | `main.py:4562` — **no existe `exigir_trabajador`**; cada ruta lo hace a mano | ~28 |
| `sesion_actual(request, "empleador")` | ídem — **no existe `exigir_empleador`** | ~16 |
| `_exigir_dashboard` / `_exigir_dashboard_detalle` | `main.py:~5030` — `exigir_sindicato` + módulo | 19 |
| `_pase_landing` / `_exigir_pase` / `_exigir_landing` | `main.py:6846-6873` — PIN de entornos (cookie `pase_entornos`, 30 días) o sesión plataforma; `_exigir_landing` además 404 fuera de local/pruebas | 22 |
| `_exigir_planes` / `_exigir_observabilidad` | `main.py:~6488`, `6601` — PIN + `ENTORNO == "pruebas"` | 13 |
| Solo cookie `cuil_trab` / `cuit_emp` (**sin firma**) | ver 1.2 | 8 |
| Ninguno | ver 1.1 | **30** |

Guardianes de alcance dentro de `exigir_sindicato`: `_exigir_super_admin`,
`_exigir_alcance_seccional`, `_exigir_alcance_area`, `_exigir_alcance_tramite`,
`_exigir_alcance_encuesta`, `_exigir_responder_tramite`, `_exigir_modulo`.

### 1.1 Rutas públicas (sin ningún guardián) — 30

| # | Método | Path | Línea | Nota |
|---|---|---|---|---|
| 1 | GET | `/sw.js` | 105 | service worker |
| 2 | GET | `/healthz` | 362 | |
| 3 | GET | `/readyz` | 367 | toca la base (SELECT 1, techo 2 s) |
| 4 | GET | `/logo/{sindicato_id}` | 384 | sirve bytes de la base con el MIME guardado, incl. `image/svg+xml` |
| 5 | GET | `/firma/{sindicato_id}` | 398 | ídem |
| 6 | GET | `/noticia-imagen/{noticia_id}/{n}` | 412 | ídem, enumerable |
| 7 | GET | `/beneficio-imagen/{beneficio_id}` | 430 | ídem, enumerable |
| 8 | GET | `/logo-plataforma` | 444 | ídem |
| 9 | GET | `/logo-plataforma-oscuro` | 460 | ídem |
| 10 | GET | `/` | 547 | |
| 11 | POST | `/admin/login` | 1351 | sin límite de intentos |
| 12 | GET | `/admin/salir` | 1366 | GET que muta estado |
| 13 | GET | `/api/push/clave-publica` | 3551 | clave VAPID pública |
| 14 | POST | `/plataforma/login` | 4648 | sin límite de intentos |
| 15 | GET | `/plataforma/salir` | 4886 | GET mutante |
| 16 | GET | `/ingresar` | 5572 | |
| 17 | POST | `/trabajador/login` | 5585 | sin límite de intentos |
| 18 | POST | `/trabajador/registro` | 5617 | crea cuenta; valida solo que el CUIL esté empadronado |
| 19 | GET | `/app/elegir/{sindicato_id}` | 5943 | fija cookie `sind_elegido` sin validar sesión ni pertenencia |
| 20 | GET | `/app/cambiar` | 5950 | GET mutante |
| 21 | GET | `/v/{token}` | 5992 | verificación de credencial; `k` efímero (`qr.verificar_codigo_efimero`) |
| 22 | GET | `/trabajador/salir` | 6014 | GET mutante |
| 23 | GET | `/ingresar-empresa` | 6028 | |
| 24 | POST | `/empresa/login` | 6035 | sin límite de intentos |
| 25 | POST | `/empresa/registro` | 6054 | |
| 26 | GET | `/empresa/elegir/{sindicato_id}` | 6159 | ídem 19 |
| 27 | GET | `/empresa/cambiar` | 6166 | GET mutante |
| 28 | GET | `/empresa/salir` | 6174 | GET mutante |
| 29 | GET | `/api/version` | 6204 | `Access-Control-Allow-Origin: *` explícito |
| 30 | GET | `/api/entornos/actividad` | 6228 | `ACAO: *`; agregados por sindicato (trámites, recibos, tokens IA, accesos, CPU/RAM) sin auth |

### 1.2 Rutas autenticadas SOLO por cookie de texto plano no firmada — 8

`cuil_trab` y `cuit_emp` se emiten como valor plano, sin HMAC
(`main.py:5601, 5682, 6050, 6074`). Estas rutas no consultan el token firmado:

| Método | Path | Línea | Efecto de forjar `cuil_trab` |
|---|---|---|---|
| POST | `/api/leer` | 575 | upload — sube recibo a nombre de otro (gasta IA) |
| POST | `/api/validar` | 625 | escribe `ReciboVerificado` con CUIL ajeno |
| GET | `/api/mis-recibos` | 776 | lee el historial completo de recibos de cualquier CUIL |
| POST | `/api/aportes` | 795 | upload — pisa el semáforo de aportes ajeno |
| POST | `/api/reportar` | 706 | vía `sindicato_activo_trabajador` |
| POST | `/api/enviar-sindicato` | 745 | ídem |
| GET | `/api/noticia/{noticia_id}` | 826 | ídem |
| GET | `/api/beneficio/{beneficio_id}` | 847 | ídem |

`/api/mis-recibos` (`main.py:776-793`): `cuil = request.cookies.get("cuil_trab","")`
→ `select(ReciboVerificado).where(ReciboVerificado.cuil == cuil)`. Sin `sesion_actual`.

Además, en las ~28 rutas que SÍ validan sesión de trabajador:
`auth.crear_sesion("trabajador", id_usuario=cuenta_id, sindicato_id=0)` guarda
`uid`, pero ningún endpoint cruza `uid` contra `cuil_trab` (grep de
`ses.get("uid")` en `main.py`: 3 usos, ninguno de trabajador). Con login
propio válido + `cuil_trab` forjado se accede a datos de otro afiliado
(`/api/mis-notificaciones`, `/perfil-foto/{cuil}`, `/api/tramites/mios`,
`_autorizado_para_tramite` en `main.py:3470-3481`). Mismo patrón para `cuit_emp`.

### 1.3 Rutas con upload (`UploadFile`) — 20

| Método | Path | Línea | Guardián | Validación |
|---|---|---|---|---|
| POST | `/api/leer` | 575 | cookie plana | ninguna (tipo/tamaño) |
| POST | `/api/aportes` | 795 | cookie plana | ninguna |
| POST | `/admin/noticia` (×2 img) | 2133 | `exigir_sindicato` + módulo | `_leer_logo` |
| POST | `/admin/beneficio` | 2194 | ídem | `_leer_logo` |
| POST | `/admin/empleador/importar-cuits` | 2476 | ídem | CSV |
| POST | `/admin/notificacion` | 2522 | ídem | `_leer_adjunto_notificacion` |
| POST | `/admin/notificacion-empresa` | 2638 | ídem | ídem |
| POST | `/api/empresa/perfil/foto` | 2750 | sesión empleador | MIME + 1 MB |
| POST | `/admin/tramite/{id}/nota` | 3396 | `exigir_sindicato` + alcance | `_leer_archivo_tramite` |
| POST | `/api/tramite` | 3768 | sesión trabajador | ext + 10 MB |
| POST | `/api/tramite/{id}/nota` | 3903 | sesión trabajador | `_leer_archivo_tramite` |
| POST | `/admin/tramite-empresa/{id}/nota` | 4026 | `exigir_sindicato` | ídem |
| POST | `/api/empresa/tramite` | 4117 | sesión empleador | ext + 10 MB |
| POST | `/api/empresa/tramite/{id}/nota` | 4234 | sesión empleador | ídem |
| POST | `/admin/convenio/documento` | 4280 | `exigir_sindicato` | `.pdf` + 30 MB |
| POST | `/plataforma/probar-modelos` | 4700 | `exigir_plataforma` | ninguna |
| POST | `/plataforma/marca` | 4862 | `exigir_plataforma` | `_leer_logo` |
| POST | `/plataforma/sindicato` | 4893 | `exigir_plataforma` | `_leer_logo` |
| POST | `/plataforma/sindicato/editar` | 5373 | `exigir_plataforma` | `_leer_logo` |
| POST | `/api/perfil/foto` | 5902 | sesión trabajador | MIME + 1 MB |
| POST | `/recursos` | 6917 | PIN landing | solo tamaño (30 MB) |

## 2. Autenticación y sesión (`auth.py`)

**Firma de cookies** (`auth.py:57-79`): payload `{rol, uid, sid, t}` en
base64url (legible, no cifrado) + HMAC-SHA256 con `SESSION_SECRET`,
hexdigest **truncado a 32 caracteres (128 bits)**. Verificación con
`hmac.compare_digest`. Expiración por inactividad `IDLE_TIMEOUT_SEGUNDOS = 900`,
renovada por `renovar_sesion_por_actividad` (`main.py:292-337`). Sesiones
stateless: **no hay revocación del lado del servidor**.

**Flags de cookie**

| Cookie | HttpOnly | Secure | SameSite | Path | Max-Age |
|---|---|---|---|---|---|
| `sesion_sindicato` / `sesion_plataforma` / `sesion_trabajador` / `sesion_empleador` | sí | **no se setea** | default Lax de Starlette | `/` | 900 s |
| `cuil_trab`, `cuit_emp`, `sind_elegido`, `sind_elegido_emp` | sí | no | Lax (default) | `/` | 900 s |
| `pase_entornos` | sí | no | `lax` explícito (`main.py:6352`) | `/` | 30 días |

Ninguna de las 20 llamadas a `set_cookie` pasa `secure=True`; solo la del PIN
pasa `samesite`.

**Hash de claves** (`auth.py:42-46`): PBKDF2-HMAC-SHA256, 100.000
iteraciones, sal aleatoria de 16 bytes por usuario, `compare_digest`. OWASP
2023 recomienda 600.000 para PBKDF2-SHA256. La clave de plataforma no se
hashea: `verificar_plataforma` compara en claro contra `PLATAFORMA_PASSWORD`
(`auth.py:82-89`).

**Límite de intentos**: no existe para ningún login. El único rate limit del
proyecto es el del PIN (`main.py:6301-6330`: 5 fallos, 60 s, dict en memoria
por IP de `X-Forwarded-For`, se vacía entero a las 5.000 entradas).

**CSRF**: sin tokens, sin chequeo de `Origin`/`Referer`, sin middleware. La
única defensa es SameSite=Lax implícito, que **no cubre los GET que mutan**:
`/admin/salir`, `/plataforma/salir`, `/trabajador/salir`, `/empresa/salir`,
`/app/cambiar`, `/empresa/cambiar`, `/app/elegir/{id}`, `/empresa/elegir/{id}`.

**Logout**: `delete_cookie` (`main.py:1369, 4889, 6017-6019, 6177-6179`). Un
token robado sigue valiendo hasta 15 min después.

**Cambio de clave**: no hay autoservicio. Solo `POST /plataforma/reset-clave`
(`main.py:5462`), autodeclarado transitorio, fija la clave de cualquier
`UsuarioSindicato` o `CuentaTrabajador` sin conocer la anterior.
`debe_cambiar_clave=True` se setea al alta (`main.py:1659, 5363`) pero solo se
muestra como etiqueta (`admin.html:2871`); ningún guardián lo fuerza. Al
cambiar clave no se invalidan sesiones.

## 3. Archivos subidos

| Helper | Línea | Tipos | Tamaño | Magic bytes |
|---|---|---|---|---|
| `_leer_logo` | 5330 | por extensión: png/jpg/jpeg/webp/gif/**svg** | **sin tope** | no |
| `_leer_adjunto_notificacion` | 2488 | por extensión: png/jpg/jpeg/webp/gif/pdf/doc/docx | 5 MB | no |
| `_leer_archivo_tramite` | 2801 | `ARCHIVO_MIMES_TRAMITE` (mismos 8) | 10 MB | no |
| foto perfil | 5898-5899 | `content_type` declarado ∈ {jpeg,png,webp} | 1 MB | no |
| convenio | 4299-4305 | `.pdf` por sufijo | 30 MB | no |
| `/recursos` | 6917 | ninguno | 30 MB | no |

Ningún camino valida magic bytes; el MIME servido sale de la **extensión
del nombre que mandó el cliente**. Todo se guarda en Postgres como `bytea`.

**Cómo se sirven**

| Ruta | Content-Type | Content-Disposition | Auth |
|---|---|---|---|
| `/logo/{id}`, `/firma/{id}`, `/noticia-imagen/..`, `/beneficio-imagen/..`, `/logo-plataforma[-oscuro]` | el MIME guardado | ninguno → inline | pública |
| `/notificacion-adjunto/{id}` (2556), `/notificacion-empresa-adjunto/{id}` (2671) | `adjunto_mime` | `inline` | sesión destinatario |
| `/tramite-respuesta-archivo/{id}` (3439), `/tramite-nota-adjunto/{id}` (3454), `/tramite-empresa-*` (4054, 4069) | ídem | `inline` | `_autorizado_para_tramite[_empleador]` |
| `/perfil-foto/{cuil}` (5921), `/perfil-empleador-foto/{cuit}` (2769) | `foto["mime"]` | ninguno | sesión propia o admin |
| `/plataforma/recibos-sospechosos/{id}/archivo` (4633) | `archivo_mime` | ninguno | plataforma |
| `/recursos/{ref}/archivo` (6988) | `recursos.mime_de()` → `text/html` para HTML | `inline` (`_bytes_con_rango`, 6892) | PIN |
| `/admin/encuesta/exportar` (3251) | csv | `attachment` | sindicato |

**Un SVG se sirve inline, sin autenticación y sin CSP**: `_leer_logo` acepta
`.svg → image/svg+xml` y `/logo/{sindicato_id}` lo devuelve tal cual. Lo mismo
para imágenes de noticias y beneficios. Y `/recursos` sirve HTML subido como
`text/html` inline, detrás del PIN.

## 4. Llamadas externas

| Destino | Archivo:línea | Cliente | Qué viaja | Timeout |
|---|---|---|---|---|
| Anthropic (recibos) | `extractor.py:305, 533` | SDK | imagen/PDF completo en base64 | sin timeout explícito (SDK: 600 s) |
| Anthropic (OCR convenio) | `rag.py:246` | SDK | páginas del PDF | sin timeout |
| Anthropic (RAG) | `rag.py:458` | SDK | fragmentos + pregunta del trabajador | sin timeout |
| Anthropic (asistente) | `asistente.py:452` | SDK | catálogo de seccionales/empresas + pregunta + agregados (sin CUIL/nombres) | sin timeout |
| Georef | `geo.py:139, 402-409` | `urllib` | domicilio del afiliado | 8 s |
| Nominatim | `geo.py:140` | `urllib` | dirección completa; UA `MiTrabajo/1.0` | 8 s |
| Render API | `render_admin.py:34-38`; `observabilidad/colector_render.py:139`; `carga/monitor_servidor.py:35` | `urllib` | `Bearer RENDER_API_KEY` | 20 / 30 / 15 s |
| Grafana Cloud | `observabilidad/aplicar_grafana.py:112-122`, `panel.py:56`, `remote_write.py:89` | `urllib` | tokens de Grafana, config, métricas | config |
| Sentry | `sentry_config.py:143`; `observabilidad/sentry_panel.py:76` | SDK / `urllib` | ver §10 | 2 s / config |
| Web Push | `push.py:41-56` | `pywebpush` | título + cuerpo con nº de expediente | sin timeout |
| GitHub dispatch | `observabilidad/aplicar_disparador.py:137` | webhook de Grafana | `GITHUB_DISPATCH_TOKEN` | — |
| Render pricing (scraping) | `actualizar_planes_render.py:70` | `urllib` | UA `Mozilla/5.0` | 30 s |

Cloudflare: solo en `.env.example`, sin código.

## 5. Secretos y configuración

| Variable | Archivo:línea | Default | Observación |
|---|---|---|---|
| `PLATAFORMA_PASSWORD` | `auth.py:32` | **`"plataforma-demo-2026"`** | clave del admin de plataforma escrita en el código |
| `SESSION_SECRET` | `auth.py:34` | **`"cambiar-este-secreto-en-produccion"`** | clave de firma de TODAS las sesiones y del pase de entornos |
| `PLATAFORMA_CUIT` | `auth.py:33` | `"20000000000"` | segundo factor del login de plataforma |
| `PIN_ENTORNOS` | `entorno.py:54` y `disenos/presentacion-2026-fuentes/subir_recurso.py:6` | **`"09211999"`** | duplicado |
| `POSTGRES_PASSWORD` | `docker-compose.yml:12` | `mitrabajo-dev-local` | solo dev |
| `DATABASE_URL` | `db.py:89` | `""` → `RuntimeError` | falla cerrado |
| `ANTHROPIC_API_KEY`, `SENTRY_*`, `RENDER_*`, `GRAFANA_*`, `GITHUB_DISPATCH_TOKEN`, `VAPID_*`, `DEMO/PRUEBAS_DATABASE_URL` | varios | vacío / `None` | sin default |
| `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (5), `DB_POOL_TIMEOUT` (5), `DB_STATEMENT_TIMEOUT_MS` (15000), `DB_IDLE_TX_TIMEOUT_MS` (30000) | `db.py:108-134` | | |
| `DASHBOARD_CUPO` (4), `DASHBOARD_CUPO_ESPERA` (2) | `main.py:5050` | | |
| `MOCK_EXTRACTOR`, `MOCK_EXTRACTOR_LATENCIA` | `extractor.py:25-34` | off / 15 | prendido en Pruebas por los tests de carga |

`.env` con valores reales existe en el árbol de trabajo (gitignored, `.gitignore:1`).

## 6. SQL y plantillas

- **SQL**: un solo `text(f"...")` (`dashboard.py:1108`), que interpola
  condiciones armadas con literales del código; los valores van bindeados.
  No inyectable. El resto (18 en `db.py`, 16 en `dashboard.py`, 7 en
  `main.py`) usa parámetros nombrados. Sin `.format()` en SQL.
- **Jinja2**: `Jinja2Templates(directory="templates")` (`main.py:487`),
  autoescape activo. Dos `|safe`, ambos SVG generados en el servidor
  (`trabajador.html:1192` filigrana, `:1228` QR). Sin `Markup`.
- **`innerHTML` con datos del servidor**: `trabajador.html:2090`,
  `portada.html:904`, `notificaciones.html:225`, `empresa.html:503` reciben
  `texto_html` de `_texto_con_links` (`main.py:5557-5569`), que
  **escapa primero** y linkifica después (`https?://`, `rel="noopener"`).
  `convenio.html:142-144` escapa antes. `dashboard.js` usa `esc()` en ~40
  interpolaciones y `textContent` en el asistente. `admin.html` usa `escHtml()`.

## 7. Cabeceras y perímetro

- Middlewares: `sin_cache_en_paneles` (`main.py:276`) y
  `renovar_sesion_por_actividad` (`:292`). `StaticFiles` en `/static`.
- **Cabeceras de seguridad: ninguna.** Cero resultados para CSP, HSTS,
  X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- CORS: sin `CORSMiddleware`; `ACAO: *` manual en `/api/version` (`:6210`) y
  `/api/entornos/actividad` (`:6245`), sin `Allow-Credentials`.
- Rate limiting: solo el PIN. Nada para logins, `/api/leer`, `/api/aportes`.
- Cupo del panel: `BoundedSemaphore(4)`, espera 2 s → 503 `E-SERVIDOR-03`
  (`main.py:5050-5068`); `/detalle/*` y el asistente quedan fuera.
- Engine (`db.py:122-172`): `pool_size=5`, `max_overflow=5`, `pool_timeout=5`,
  `pool_pre_ping`, `pool_recycle=300`, keepalives, `statement_timeout=15000`,
  `idle_in_transaction_session_timeout=30000`. Handlers: `PoolTimeoutError` →
  503 + `Retry-After` (`:210`); `QueryCanceled` → 503 (`:223`).

## 8. Dependencias (`requirements.txt`)

16 de 17 pinneadas con `==`; `anthropic>=0.69.0` es la única abierta. Sin
lock file ni hashes. `fastembed==0.8.0` y `sentry-sdk==2.69.2` pinneadas a
propósito. `requirements-dev.txt` aparte.

## 9. IA

- **`extractor.py`**: `system=SYSTEM` + mensaje de usuario con el documento
  como bloque `image` nativo y el `ESQUEMA` como texto (`:305-312`,
  `:533-540`). No concatena texto del usuario, pero **no hay instrucción
  anti-inyección**: un recibo con texto impreso que instruya al modelo
  compite con `SYSTEM`. Salida: `json.loads` estricto (`_parsear`, `:244-258`),
  nunca `eval`. Después, `main.py:575-624` aplica `cuil_no_coincide`,
  `confianza == "baja"` y `detectar_nuevos`; **los conceptos nuevos que
  devuelve el modelo se dan de alta en la base** (`main.py:641-680`,
  `pendiente_revision=True`). El JSON crudo va a `ReciboVerificado.detalle` y
  se renderiza con `esc()`. `MAX_TOKENS=8000`, `effort: low` para opus-5/sonnet-5.
- **`rag.py`**: `INSTRUCCIONES` (`:377-398`) con grounding fuerte. Mensaje
  (`:457-459`): `FRAGMENTOS DEL CONVENIO:\n\n{contexto}\n\nPREGUNTA DEL
  TRABAJADOR:\n{pregunta}`. `_armar_contexto` (`:422-434`) delimita con
  `--- {referencia} | {seccion} ---`, adivinable y sin escapado: un PDF puede
  falsificar una fuente. La pregunta va sin delimitar. Sin instrucción de
  ignorar órdenes dentro de los fragmentos. OCR (`:230-253`) sin `system`.
  La baranda es `"NO_ENCONTRADO" not in texto.upper()` (`:462`). El texto se
  escapa en `convenio.html` antes de `innerHTML`.
- **`asistente.py`**: el modelo no genera SQL ni ve filas (docstring `:1-23`).
  Herramienta con schema cerrado, salida validada por
  `dashboard.parsear_filtros` (el mismo parser del front), ids ajenos
  descartados antes de consultar, `MAX_VUELTAS=3`, `TOPE_DIARIO=300`,
  `MAX_PREGUNTA=500`. Render con `textContent`.

## 10. Logs y observabilidad

- Sin `logging` configurado; `print()` a stdout. Ningún `print` con CUIL,
  nombre, mail o clave. Pero el **path** puede llevar CUIL
  (`/perfil-foto/20123456789`) y `traceback.print_exc()` (`main.py:195`)
  imprime el traceback completo **sin scrubbing** (a diferencia de Sentry).
- Datos personales persistidos como registro: `ConsultaConvenio` (CUIL +
  pregunta literal, `db.py:1905-1916`), `ConsultaAsistente` (uid + pregunta +
  respuesta), `UsoIA` (CUIL por cada llamada a la IA, `main.py:590, 807`),
  `ReciboSospechoso` (archivo completo + CUIL, `main.py:610-616`).
  `AccesoLog` guarda rol + sindicato, sin CUIL.
- Sentry (`sentry_config.py`): allow-list (`limpiar_evento`, `:80-120`);
  sin `request.data`/headers/cookies/env/user/vars; mails redactados;
  26 nombres de campo personales → `[filtrado]`; 20 eventos/min. Decisión
  documentada (`:8-11`): un CUIL suelto en un path o en el texto de una
  excepción sí puede salir.

## 11. Infra

- **Sin `render.yaml`, `Dockerfile` ni `Procfile`**: el deploy está
  documentado a mano en `DESPLIEGUE_RENDER.md`; las variables se fijan en el
  dashboard de Render.
- `docker-compose.yml`: `pgvector/pgvector:pg16`, puerto 5432 publicado al
  host, credenciales de dev.
- `.github/workflows/metricas-render.yml` (único workflow): cron cada 5 min
  + `workflow_dispatch`, `permissions: contents: read`, gateado al repo
  `snavello/MITRABAJOC`, secretos `RENDER_API_KEY` y `GRAFANA_METRICS_TOKEN`
  solo como `env` del step. **No hay CI de tests, lint ni escaneo de
  dependencias o secretos**; la suite (~180 `test_*.py`) corre a mano.

## Observaciones que deja el mapeo (hipótesis para el catálogo, no hallazgos)

| # | Observación | Ubicación | Eje |
|---|---|---|---|
| O1 | `SESSION_SECRET` con default escrito en el código: sin la variable, cualquiera forja sesión de cualquier rol y el pase de entornos | `auth.py:34` | DAT / IDS |
| O2 | Identidad del trabajador/empleador en cookie **no firmada** (`cuil_trab`, `cuit_emp`), nunca cruzada contra el `uid` de la sesión; 8 rutas sin otra verificación | `main.py:5601, 6050, 776` | AUT |
| O3 | `PLATAFORMA_PASSWORD` y `PLATAFORMA_CUIT` con default en el código; la clave de plataforma no se hashea | `auth.py:32-33, 82-89` | IDS / DAT |
| O4 | `PIN_ENTORNOS` con default en dos archivos | `entorno.py:54`, `disenos/.../subir_recurso.py:6` | DAT |
| O5 | SVG aceptado en logos/noticias/beneficios y servido inline, público, sin CSP | `main.py:5338-5346, 384-475` | ENT |
| O6 | `/recursos` sin allow-list de tipo; HTML servido `text/html` inline tras el PIN | `main.py:6917`, `recursos.py:163-171` | ENT |
| O7 | Cero cabeceras de seguridad | `main.py` | ENT / DIS |
| O8 | Cookies sin `Secure` ni `SameSite` explícito | 20 × `set_cookie` | IDS |
| O9 | Sin límite de intentos en los cuatro logins | `main.py:1351, 4648, 5585, 6035` | IDS |
| O10 | Sin CSRF; 8 rutas GET que mutan estado | `/…/salir`, `/…/cambiar`, `/…/elegir/{id}` | ENT |
| O11 | `/api/leer` y `/api/aportes` gastan IA sin autenticación real, sin tope de tamaño ni rate limit | `main.py:575, 795` | IA / DIS |
| O12 | `_leer_logo` sin tope de tamaño | `main.py:5330-5350` | DIS |
| O13 | `/plataforma/reset-clave` transitorio; `debe_cambiar_clave` no se aplica; sesiones no se invalidan al cambiar clave | `main.py:5462`, `admin.html:2871` | IDS |
| O14 | `/api/entornos/actividad` público con `ACAO: *` | `main.py:6228` | AUT |
| O15 | Inyección de prompt en `rag.py` (PDF del sindicato + pregunta, delimitadores falsificables, sin mitigación); `extractor.py` sin instrucción anti-inyección y sus conceptos nuevos van a la base | `rag.py:422-459`, `extractor.py:305`, `main.py:641-680` | IA |
| O16 | `traceback.print_exc()` a stdout sin scrubbing | `main.py:195` | DAT / LEY |
| O17 | Firma HMAC truncada a 128 bits; PBKDF2 a 100.000 iteraciones | `auth.py:42-72` | DAT |
| O18 | `anthropic>=0.69.0` sin pinnear; sin CI de tests ni escaneo de dependencias/secretos; sin IaC del deploy | `requirements.txt:5`, `.github/workflows/` | INF |
| O19 | Registros con CUIL que no hacen falta para operar (`UsoIA`, `ConsultaConvenio`), sin política de retención | `db.py`, `main.py:590, 807` | LEY |
| O20 | Sesiones stateless sin revocación: un token robado vale 15 min tras el logout | `auth.py` | IDS |

**Lo que el mapeo encontró bien resuelto** (también se registra): `PERMISOS_RUTAS`
falla cerrado y `test_areas_rutas.py` recorre `app.routes`; autoescape de
Jinja con dos `|safe` sobre SVG del servidor; SQL 100% parametrizado; Sentry
con allow-list; techos del engine y cupo del panel; `DATABASE_URL`
obligatoria; `esc()`/`escHtml()` consistentes en el JS; `asistente.py` con el
modelo sin acceso a SQL ni a filas; el chequeo de CUIL ajeno apenas se lee
un documento.
