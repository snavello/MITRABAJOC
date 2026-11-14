# QA de servidor — Mesa de implementación

QA independiente de seguridad y lógica (2026-11-14). Alcance: `implementacion.py`,
el bloque «Mesa de implementación» de `db.py` (modelos `Impl*`, funciones `impl_*`,
migraciones `3be99db601b1` y `c4e7a9b2d6f1`) y las rutas de `main.py` (acceso, API
del equipo, API de la mesa). Contra `PLAN_IMPLEMENTACION.md` (I1–I14) y
`docs/implementacion/API.md`.

Tests: `test_implementacion_qa.py` (25 pasan y fijan lo que resiste; 41 son
`xfail(strict=True)` y fallan hoy por un defecto real — cuando se corrija, el test
pasa y `strict` obliga a sacar la marca). Se corre con
`.venv/bin/python -m pytest test_implementacion_qa.py -q`
(`--runxfail` muestra cada fallo). Los otros `test_implementacion*.py` siguen en verde
(18 + 27 + 20 + 21 + 33) y `test_migraciones.py` también.

Convención: **[T]** = defecto confirmado con test; **[L]** = sospecha por lectura
(no reproducida).

---

## Defectos

### QA-01 · ALTO · [T] El equipo (o el sindicato) se aprueba su propia aprobación tomándola «en curso»
`a_quien_le_toca(EN_CURSO, lado_actor)` devuelve **al mismo lado que respondió**
(`implementacion.py:178`) y `puede_resolver_aprobacion` solo mira que el actor sea el lado al
que «le toca» (`implementacion.py:199`; `db.impl_resolver_aprobacion` ≈ `db.py:10198`).
Pedido que lo reproduce:

1. Equipo: `POST /api/implementacion/p/{pid}/tarjetas` `tipo=aprobacion, titulo=…, texto=…` → `espera: sindicato`.
2. Equipo: `POST …/tarjetas/{tid}/responder` `estado_nuevo=en_curso, texto=la tomo` → ahora `espera: equipo` y `acciones.aprobar: true`.
3. Equipo: `POST …/tarjetas/{tid}/aprobacion` `{"aprobar": true}` → **200, estado aprobada, «resuelta por» el mismo equipo**.

Idéntico del lado del sindicato (crea, toma «en curso», aprueba). Debería: 403. El comentario
del propio código dice «quien la pidió no se la aprueba a sí mismo». Corrección: la regla tiene que
ser `lado_actor != autor_lado` (la resuelve la otra parte), no «a quien le toca».
Test: `test_quien_pidio_una_aprobacion_no_puede_aprobarla_tomandola_en_curso`.

### QA-02 · ALTO · [T] El solicitante aprueba lo que pidió en cuanto la otra parte contesta algo
Mismo origen que QA-01 por otro camino: sindicato crea una aprobación (`espera: equipo`); el
equipo responde con `estado_nuevo=respondida` («¿seguro?») → el turno vuelve al sindicato
(`otro_lado(equipo)`) y `acciones.aprobar` pasa a `true` para **quien la pidió**; `POST …/aprobacion`
→ 200. Debería: 403 y `acciones.aprobar=false`. Cualquier aclaración de la contraparte habilita la
auto-aprobación. Test: `test_el_solicitante_no_aprueba_lo_que_pidio_tras_una_respuesta`.

### QA-03 · MEDIO · [T] Un `Hİ0001` (I mayúscula con punto, U+0130) provoca 500
`_CODIGO_RE` usa `re.IGNORECASE`, que en Python casa `İ`/`ı` con `i` (`implementacion.py:~430`);
`_desde_match` hace `m.group(1).upper()` → `'Hİ'`, que no está en `DIGITOS` → `KeyError`
(`implementacion.py:445`). Pedidos que dan 500 (con equipo y con sindicato, sin privilegios):
`POST tarjetas` con `texto=ver Hİ0001` (o en `titulo`), `POST …/responder texto=Hİ0001`,
`GET …/buscar?codigo=Hİ0001`, `GET …/tarjetas?q=Hİ0001`. Debería: tratarlo como no-código.
Corrección: `re.ASCII` en la regex (también elimina QA-18). Tests: `test_un_codigo_con_i_turca_no_rompe[*]`.

### QA-04 · MEDIO · [T] Un `\x00` en cualquier texto → 500 («text fields cannot contain NUL»)
Ningún campo de texto se sanea. 500 reproducibles (todos con la sesión que corresponde):
`POST tarjetas` (`titulo`/`texto`), `POST …/responder texto`, `GET …/tarjetas?q=`, `POST …/aprobacion {"texto"}`,
`POST …/reasignar {"responsable"}`, `POST plan/hitos {"texto"}`, `POST plan/hitos/{h} {"texto"}`,
`POST plan/etapas/{e} {"nombre"}`, `POST /api/entornos/implementacion/proyectos {"nombre"}`, alta de usuario (`nombre`)
y **`POST /implementacion/ingresar` con `mail=a%00b` — sin sesión, público**. Cada 500 dispara Sentry/Telegram
(ruido y vector de spam de alertas). Debería: 400 con mensaje, o quitar los NUL. Un punto único
(`validar_tarjeta_nueva` + un `_limpio()` en cada ruta de texto, y el login) lo cierra.
Un `\ud800` suelto en un JSON da el mismo 500 (UnicodeEncodeError al enviar a psycopg). Tests: `test_un_nul_en_un_texto_no_da_500[*]`.

### QA-05 · MEDIO · [T] Ids mayores que int4 → 500
`/api/implementacion/p/2147483648/resumen` (equipo), `GET …/tarjetas/2147483648`, `…/archivos/99999999999`, `POST …/plan/hitos/{big}`,
`GET …/tarjetas?etapa_id=99999999999`, `POST tarjetas etapa_id=…|hito_id=…|responde_a=…` con ese valor,
`GET /implementacion?p=…`, `GET /api/entornos/implementacion/proyectos/{big}/usuarios`: 500 en todas (psycopg3 binda int8 contra
columnas int4; los valores `> 2147483647` revientan; el sindicato también, para `tid`/`aid`). Debería: 404 (o 422).
Corrección: tipar los ids con `Path(..., le=2**31-1)` / `Query(le=…)` y `_impl_int` con el mismo tope. Test: `test_ids_gigantes_no_dan_500[*]`.

### QA-06 · MEDIO · [T] Responder no es atómico con sus archivos: un fallo al guardar el adjunto deja el estado cambiado y el mensaje, con 500
`api_impl_responder` (`main.py:~13000`) llama a `db.impl_responder` (commit) y **después** `impl_subir_archivo` por archivo (un commit
cada uno). Un `Content-Type` del archivo con `\x00` (cabecera cruda) hace fallar el `INSERT` del archivo: respuesta 500, pero el
estado pasó a «respondida» y el mensaje quedó guardado, sin el adjunto (el cliente reintenta y duplica). El mismo patrón en
`POST tarjetas` (la tarjeta se crea y puede quedar sin sus archivos si uno falla en la base). El contrato dice «si algo no pasa, NO
se crea la tarjeta». Corrección: sanear `mime` (`[a-z0-9/+.-]`) y envolver mensaje + archivos en una sola transacción.
Test: `test_un_archivo_que_falla_no_deja_el_responder_a_medias`.

### QA-07 · MEDIO · [T] `reasignar` se acepta en tarjetas cerradas y en avisos aunque `acciones.reasignar` sea false
Recorrida la matriz completa (tipo × estado × quién la creó × lado; 792 pedidos reales contra `acciones`), **esta es la única discrepancia**:
`POST …/reasignar` sobre una tarjeta cerrada (cualquier tipo) o un aviso devuelve 200 (`db.impl_reasignar` ≈ `db.py:10177` solo chequea
`es_inmutable`), y escribe un evento «reasignó» en una tarjeta cerrada. `acciones` dice false. Debería: 409 `cerrada`/400 `aviso`. Tests:
`test_reasignar_respeta_acciones[*]` (y `test_acciones_coincide_con_lo_que_el_servidor_acepta`, que pasa, cubre el resto de la matriz).

### QA-08 · MEDIO · [T] Host-header injection en el enlace del mail de aviso
`_impl_preparar_aviso` arma el enlace con `_base_url(request)` (`main.py:12850`, `13348`), que sale del header `Host` del pedido. Un
usuario del sindicato autenticado manda `POST tarjetas` con `Host: evil.example` y el mail que sale a **todo el equipo** dice
`Entrá para verla: http://evil.example/implementacion?p=…#PE0001` desde el remitente de Colm3na (phishing interno). Debería: base URL fija por
entorno (`entorno.URLS`/variable), nunca del request. Test: `test_el_enlace_del_aviso_no_depende_del_header_host`.

### QA-09 · MEDIO · [T] La API del equipo no revisa que el usuario de plataforma esté activo ni sin pendientes
`_actor_impl` rechaza al usuario de plataforma inactivo, con clave transitoria o con datos pendientes, pero `_impl_equipo_api` (`main.py:12597`) solo
usa `_exigir_herramientas` (firma + 15 min de inactividad, que se renuevan con cada pedido). Un usuario dado de baja (`activo=False`),
o con `debe_cambiar_clave`/`debe_completar_datos`, conserva con su cookie **crear proyectos, dar de alta usuarios del sindicato,
restablecer su clave (la respuesta trae la clave nueva en claro) y activar/desactivar usuarios**. Tests:
`test_la_api_del_equipo_rechaza_usuarios_de_plataforma_inactivos_o_pendientes[*]`. (Es una propiedad heredada de las demás Herramientas,
pero acá abre cuentas ajenas.) Con `PIN_ENTORNOS_HABILITADO=1` el pase del PIN abre esta misma API con actor id 0 [L]; apagarlo cierra el caso.

### QA-10 · MEDIO · [T] Textos libres sin tope: `aprobacion.texto`, `reasignar.responsable`, `plan/hitos.texto`
`impl_resolver_aprobacion`, `impl_reasignar` e `impl_agregar_hito`/`impl_editar_hito` no aplican `TOPE_TEXTO`. Se aceptaron 3 MB en cada uno; el
`responsable` viaja en **cada fila del listado** (`GET tarjetas` devolvió 3 MB) y el texto de la aprobación en el detalle y en
`aprobaciones`. Un usuario del sindicato (que puede reasignar y resolver) infla las pantallas de todos; además el regex de códigos corre sobre el texto
completo (2,8 MB de «PE0001 » = 1,45 s de CPU por pedido). Debería: 400 con el mismo tope que `responder` (5.000) y 200 para `responsable`/hito.
Test: `test_los_textos_libres_tienen_tope[*]`.

### QA-11 · MEDIO · [T] `fecha_limite` se guarda tal cual: «2026-1-5» y dígitos de ancho completo pasan `strptime`
`validar_tarjeta_nueva` valida con `strptime` pero guarda el texto original (`implementacion.py:207`, `239`). La app compara fechas como texto
(`vencida`, `impl_resumen`: `fecha_limite < hoy`): «2026-1-5» se ordena después de «2026-01-10», así que la tarjeta no figura vencida. Debería:
normalizar a ISO (`datetime.strptime(...).date().isoformat()`) o rechazar lo que no sea `AAAA-MM-DD` ASCII. Test: `test_fecha_limite_se_normaliza_a_iso[*]`.

### QA-12 · MEDIO · [T] Los huecos de `orden` (mensajes) y de `AR` (archivos) delatan las notas internas al sindicato
`orden` cuenta todos los mensajes (decisión escrita en API.md), así que el sindicato recibe `PE0001-1`, `PE0001-3`: sabe que hay una nota interna y
cuántas hay entre dos públicas; igual con `AR000001`, `AR000003` para un archivo interno. El contenido, autor, archivo, evento, contador y relaciones **no**
viajan (ver «Resistió»), pero la existencia sí, y `impl_responder` declara como objetivo que «el sindicato no debe notar nada». Es una decisión de diseño que
SDN debería confirmar o revertir: opciones — contador separado para lo interno (`PE0004-i1`, no direccionable por el sindicato), o `orden` contado solo
sobre lo público y lo interno sin número para el sindicato. Tests: `test_el_sindicato_no_nota_huecos_en_la_numeracion_de_mensajes`, `…_en_los_codigos_de_archivo`.

### QA-13 · BAJO · [T] Se puede borrar el adjunto de una aprobación ya resuelta
`impl_borrar_archivo` no mira `es_inmutable` (`db.py:10399`); el sindicato (si lo subió) o el equipo borran el documento que se aprobó. Queda la constancia
(nombre, tamaño, quién) y el evento, pero «inmutable: ni estado ni hilo» (plan) debería incluir los adjuntos. Debería: 409 `inmutable`.
Test: `test_no_se_borra_un_adjunto_de_una_aprobacion_resuelta`.

### QA-14 · BAJO · [T] El freno del login se reinicia con un login exitoso propio
`_login_ok(request, _intentos_impl)` (`main.py:12533`) borra el contador de la IP. Quien tiene una cuenta propia intercala un login válido cada 8 fallos y tantea
la clave de otra cuenta sin que salte nunca la espera (24 intentos sin una sola espera en el test). Es el mismo diseño de los otros logins; el freno también
cae con `X-Forwarded-For` falsificado (H-0008 parcial, ya aceptado). Test: `test_el_freno_no_se_reinicia_con_un_login_propio_exitoso`.

### QA-15 · MEDIO · [T] Una subida de archivos sin sesión se recibe entera antes de autorizar (DoS de disco/ancho de banda)
FastAPI parsea el multipart (`archivos: list[UploadFile]`) **antes** de ejecutar la ruta; `_impl_autorizar` corre recién después (`main.py:12944`).
Starlette no limita el tamaño de las partes de archivo: un anónimo sube cientos de MB (a un SpooledTemporaryFile → disco) y recién entonces recibe 401. El tope de
20 MB/40 MB de `_impl_leer_adjuntos` llega tarde (confirmado: al llegar a `_impl_autorizar` el archivo de 3 MB ya estaba completo). Corrección: dependencia que
autorice antes de declarar los `File(...)`, o middleware que corte por `Content-Length` > 45 MB en `/api/implementacion/*`. Test: `test_una_subida_sin_sesion_no_se_recibe_entera`.

### QA-16 · BAJO · [T, carrera] `orden` duplicado en hitos creados a la vez
`impl_agregar_hito` calcula `max(orden)+1` sin bloquear la etapa (`db.py:9998`); diez altas simultáneas dieron `[1,2,2,2,2,2,2,2,3,3]`. Test (no estricto, es una
carrera): `test_hitos_concurrentes_tienen_orden_unico`.

### QA-17 · BAJO · [T] Un archivo con nombre en blanco se descarta en silencio
`_impl_leer_adjuntos` filtra `(u.filename or "").strip()` (`main.py:12754`): un adjunto con `filename="   "` desaparece y el pedido sale 200 sin avisar.
Test: `test_un_archivo_sin_nombre_no_se_pierde_en_silencio`.

### QA-18 · BAJO · [T parcial] El reconocimiento de códigos acepta dígitos Unicode y letras vecinas no ASCII
`PE٠٠٠٤` (dígitos árabes) se lee como `PE0004`; `PE0004ñ` y `ñPE0004` cuentan como código aunque `XPE0004` no. Cosmético, pero hace que lo que se
ve y lo que se enlaza difieran. Lo cierra la misma corrección de QA-03 (`re.ASCII`).

---

## Sospechas por lectura (no reproducidas)

- **QA-19 · MEDIO [L] · `clonar_demo_a_pruebas.py` y `alembic_version`.** El dump excluye `impl*` pero **no** `alembic_version`. Si la Demo está
  atrás de Pruebas en migraciones (hoy: no tiene `3be99db601b1`/`c4e7a9b2d6f1`), `pg_restore --clean` deja en Pruebas el `alembic_version` viejo con las tablas
  `impl*` ya creadas; el siguiente `alembic upgrade head` (Pre-Deploy de Render) intenta `create_table implproyecto…` → `DuplicateTable` y el deploy de Pruebas
  falla. El script dice «no debería hacer nada» sin mirar la versión. Conviene excluir `alembic_version` o abortar si el origen no está en el mismo `head`.
- **QA-20 · BAJO [L] · Sin límite de frecuencia al crear tarjetas/respuestas.** Cada tarjeta nueva o respuesta del sindicato manda un mail a **todos** los usuarios de
  plataforma con mail (y viceversa). Un usuario del sindicato puede generar mails (y filas) sin tope: cuota de Resend y spam interno.
- **QA-21 · BAJO [L] · GET con efectos.** `GET archivos/{aid}` registra descarga/evento y `GET exportar.zip` registra evento; con `SameSite=Lax` una navegación
  cross-site de nivel superior los dispara. Solo ensucia la traza (no hay lectura cruzada: la respuesta no llega al atacante).
- **QA-22 · BAJO [L] · `/exportar.zip` se vuelve inexportable.** Si los archivos vigentes superan 400 MB la exportación (resguardo de I3) responde 413 y no hay camino
  alternativo; tampoco exporta los usuarios (`ImplUsuario`) del sindicato, que hacen falta para «mudarla».
- **QA-23 · BAJO [L] · Aviso de las tarjetas del sindicato incluye el título libre** en el asunto y cuerpo (hasta 100 caracteres, colapsado a una línea, sin CR/LF —no hay
  inyección de cabeceras—). Es el contenido que el plan permite, pero es texto de un tercero en un mail de Colm3na (ver QA-08).
- **QA-24 · BAJO [L] · `entrega` no cierra «al recibirlo».** El plan (tabla de tipos) dice «Cerrada al recibirlo»; el servidor trata la entrega como un pedido
  más (`abierta` → … → `cerrada` a mano) aunque se suba el archivo. Confirmar si es intencional.
- **QA-25 · BAJO [L] · Sin invalidación de sesión al salir / al cambiar la clave.** `impl_salir` solo borra la cookie del navegador; las sesiones son tokens sin estado
  (15 min deslizantes). Quedan cubiertos los casos que importan (baja, clave restablecida, proyecto desactivado → 401 en el pedido siguiente, probado), no un token robado.
- **QA-26 · BAJO [L] · Parciales en `POST plan/hitos/{id}`.** Si el equipo manda `hecho` junto con un `texto` inválido, el tildado ya se confirmó cuando llega el 400 del texto.

---

## Qué se atacó y resistió (con test que lo fija)

1. **Aislamiento entre proyectos.** Cada ruta con `{tid}`, `{aid}`, `{hid}`, `{eid}`, `{pid}`, `etapa_id`, `hito_id`, `responde_a` (id y código), `buscar`, `q` (por título, texto,
   código de tarjeta/archivo/hito/mensaje), `carpetas`, `aprobaciones`, `plan`, `resumen`, ZIP y CSV, con id de **otro proyecto vs. id inexistente**, desde sindicato y equipo:
   status y cuerpo **idénticos** (404 «No existe.» / 400 con el mismo mensaje); ninguna lista trae datos ajenos. Los usuarios (`restablecer-clave`, `estado`) también filtran por proyecto.
   `test_ids_de_otro_proyecto_son_indistinguibles_de_un_id_inexistente`, `test_usuarios_del_equipo_api_filtran_por_proyecto`.
2. **Notas internas (I8).** Con una nota «solo equipo» con archivo (marcado datos personales) y una mención: el sindicato no recibe texto, autor, archivo, evento, relación, ref ni
   código por detalle, listas, `n_mensajes`/`n_archivos`, `actualizada_en`, carpetas, ficha/descarga/borrado por id (404), `buscar` ni `q` (ni por texto ni por código del archivo o del mensaje);
   no puede mandar `solo_equipo` (403, tampoco mezclado con un cambio de estado); mencionar un código interno devuelve `existe:false` y no deja relación visible; la mención interna
   tampoco se ve desde la otra tarjeta. Una relación interna pasa a pública al mencionarse en público. Excepción: QA-12.
3. **Archivos (I5).** Con datos personales solo bajan el equipo y quien lo subió (otro usuario del mismo sindicato: 403; ficha y carpetas muestran metadatos con `puede_bajar:false`);
   toda descarga queda registrada; borrar deja los bytes en NULL y la constancia, y el segundo borrado/descarga da 410; nombres con `../`, comillas, `;`, unicode, 500 caracteres: `nombre_seguro` +
   `Content-Disposition` seguros (sin CR/LF, con `filename*`); mimes html/svg/xhtml/javascript se sirven como `application/octet-stream` + `nosniff` + `CSP: sandbox`; vacío 400, 21 MB 413,
   3×14 MB 413, 6 archivos 400, y el tope se mira leyendo `TOPE+1` (no carga todo); un archivo inválido **no** crea la tarjeta. ZIP: sin zip-slip (`archivos/NNNN/{id}-{nombre_seguro}`), CSV con
   fórmulas neutralizadas (`=`, `+`, `-`, `@`) en títulos y nombres.
4. **Aprobaciones.** Doble resolución concurrente (6 hilos): un solo 200, cinco 409, un solo evento «resolver» (FOR UPDATE). Resuelta, ninguna ruta de hilo la toca (responder, estado, adjuntos,
   reasignar, segunda resolución); resolver algo que no es aprobación 400; cuerpos `aprobar` no booleanos 400. (Excepciones: QA-01, QA-02, QA-13.)
5. **Estados y turnos.** Transiciones inválidas, estados inventados, responder sobre cerrada y sobre aviso, reabrir: correctos. La **matriz completa de `acciones`** (792 pedidos) coincide con el servidor salvo QA-07.
6. **Acceso.** Usuario inactivo, clave restablecida (transitoria) y proyecto desactivado con cookie vieja: 401 en el pedido siguiente; login idéntico exista o no el mail, esté o no activo (misma
   redirección, tiempos iguales: hash de relleno); freno por IP funciona (12 fallos → espera, también con la clave buena); cookies falsificadas, de otro rol, con `sid`/`uid` cruzados: 401; con las dos
   cookies manda el equipo; el sindicato recibe 403 en toda la API del equipo (incluida la semilla y restablecer-clave); el token de `cambiar-clave` es de un solo uso (10 min), exige la transitoria,
   rechaza claves < 8 / en blanco / iguales; los parámetros `error` y `token` no se reflejan sin escapar; cookies `HttpOnly; SameSite=Lax` (y `Secure` en demo/prod); **ENTORNO sin distintivo (demo): las 33 rutas
   (páginas, API de la mesa, API del equipo) son 404 para equipo, sindicato y anónimo**, también el multipart. CSRF: SameSite=Lax cubre los POST cross-site; no hay verificación de `Origin` y un JSON sin
   `Content-Type` se acepta (defensa en profundidad faltante, no explotable con Lax).
7. **Códigos y relaciones.** Minúsculas, ceros de más (`PE00041`), dentro de otra palabra (`XPE0004`, `PE0004x`), `PE0004-0`, 1000 repeticiones, auto-mención, hito borrado (404, no libera `HI0001`,
   quita su relación), creación concurrente (8 hilos: números 1..8 y códigos únicos), 450 códigos de mensaje en un texto (0,3 s por pedido, 0,14 s por detalle: costo aceptable). Excepciones: QA-03, QA-18.
8. **Reglas del proyecto.** Una sesión de base por request: las rutas nuevas abren una sola (`_impl_actor_de(request, pid, s)`; `_impl_autorizar` y `_impl_equipo_api` abren y cierran la suya **antes**, nunca anidada); ninguna lista trae
   `datos` (`_sin_bytes` + `octet_length`); `fechas.py` (sin `datetime.now`; `test_fechas.py` verde); `JSON_TIPO` en `ImplEvento.detalle`; mails sin contenido (ni texto ni archivos; el título y el enlace
   solamente) y sin inyección de cabeceras; migración y modelo alineados (`test_migraciones.py` verde). Errores con mensaje para la persona en toda entrada razonable; los 500 listados están todos en QA-03/04/05/06.
9. **Resguardos de I3.** `clonar_demo_a_pruebas.tablas_excluidas()` incluye `impl*` y `cargar_demo` salta las tablas `impl*`; `IMPL_TABLAS` coincide exactamente con las tablas `impl*` del metadato.
   Pendiente: QA-19.

## Orden sugerido de corrección

1. QA-01 y QA-02 (una sola regla: «resuelve el lado que no la pidió»).
2. QA-15 (autorizar antes de parsear el multipart) y QA-09 (misma puerta que `_actor_impl` en la API del equipo).
3. QA-03 + QA-04 + QA-05 (los 500: `re.ASCII`, un saneador de NUL en todas las entradas de texto y tope de ids) y QA-06 (transacción única para responder + archivos).
4. QA-08 (base URL fija), QA-07, QA-10, QA-11, QA-13.
5. Decisión de SDN sobre QA-12 (huecos de numeración) y QA-24 (entrega).

---

## Correcciones (segunda vuelta, 2026-11-14)

Todo corregido sale con su test normal en `test_implementacion_qa.py` (84 pasan; quedan 2 `xfail` NO estrictos, los de QA-12). Cambios de contrato en `API.md` → «Correcciones del QA».

| # | Estado | Cómo |
|---|---|---|
| QA-01 | corregido | Una sola regla en `implementacion.puede_resolver_aprobacion(tipo, estado, autor_lado, lado_actor)`: resuelve el lado que no la pidió, en cualquier estado abierto. `db.impl_resolver_aprobacion` pasa `t.autor_lado`. |
| QA-02 | corregido | Misma regla; `acciones_de(..., autor_lado)` (que el servidor arma en `_impl_detalle`) dice lo mismo que se acepta. Se ajustaron `test_implementacion.py`, `test_implementacion_api.py` y `test_implementacion_codigos.py`, que asumían la regla vieja. |
| QA-03 | corregido | `_CODIGO_RE` sin `IGNORECASE`: prefijos `[Pp][Ee]…`, dígitos `[0-9]`; `_desde_match` devuelve `None` ante un prefijo desconocido (nunca `KeyError`). |
| QA-04 | corregido | `implementacion.limpiar_texto` (sin `\x00`, sin sustitutos sueltos, NFC, recortado) en todas las puertas de texto: en `db.py` (`_L`) y en `main` (formularios, JSON, `q`, `codigo`, login y cambio de clave). |
| QA-05 | corregido | Tipos `IdImpl`/`IdImplOpt` (404 si el id no entra en int4) en todas las rutas de la mesa y del equipo; `_impl_int` y `sindicato_id` dan 400; `impl_tarjeta_por_codigo_o_id` y la búsqueda por número tampoco revientan (`² `, números enormes). |
| QA-06 | corregido | `mime_seguro` (token `tipo/subtipo`) y mensaje + estado + archivos en UNA transacción: `db.impl_responder(..., adjuntos=)` e `impl_crear_tarjeta(..., adjuntos=)` usan `_impl_guardar_archivo` sin commit. |
| QA-07 | corregido | `impl_reasignar`: 409 `cerrada` y 400 `aviso`, coherente con `acciones.reasignar`. |
| QA-08 | corregido | El enlace sale de `entorno.URLS[entorno.ENTORNO]`; sin URL pública (local), el mail no lleva enlace absoluto. |
| QA-09 | corregido | `_impl_equipo_de_sesion` es la única definición de «equipo» y la usan `_actor_impl` y `_impl_equipo_api` (sin pase del PIN). |
| QA-10 | corregido | Constantes `TOPE_*` en `implementacion.py` y `exigir_largo` (400 con mensaje) en aprobación, responsable, hitos, proyecto, usuario, mail y clave. |
| QA-11 | corregido | `validar_tarjeta_nueva` usa `listas.normalizar_fecha` (la de las fechas del padrón) y guarda ISO o rechaza. |
| QA-12 | pendiente de decisión | Sin cambios: el test queda `xfail` no estricto («decisión de SDN pendiente»). Opciones en el defecto. |
| QA-13 | corregido | `impl_borrar_archivo` → 409 `inmutable` si la tarjeta es una aprobación resuelta. |
| QA-14 | corregido | Freno propio de la mesa (`_impl_login_bloqueado/_fallo`): fallos por IP en ventana de 10 min, un ingreso correcto no reinicia el contador. Los otros logins no se tocaron. |
| QA-15 | corregido | Las dos rutas con archivos ya no declaran `File`/`Form`: autorizan primero y leen el cuerpo con `_impl_formulario` (corta por `Content-Length` y por bytes recibidos arriba de 41 MB); un anónimo recibe 401 sin que se parsee nada. |
| QA-16 | corregido | `impl_agregar_hito` (y el reordenado) bloquean la etapa con `FOR UPDATE`; test sin `xfail`. |
| QA-17 | corregido | Un archivo con contenido y sin nombre entra como «archivo»; solo se ignora el campo vacío (sin nombre y sin bytes, lo que manda un navegador sin archivo elegido). |
| QA-18 | corregido | Lo cierra la corrección de QA-03. |
| QA-19 | corregido | El riesgo era real (`alembic_version` viene del dump de la demo, las tablas `impl*` no). Las migraciones `3be99db601b1` y `c4e7a9b2d6f1` son idempotentes (no crean lo que existe; el backfill no se repite). Test: `test_las_migraciones_de_la_mesa_son_idempotentes` (levanta una base, la deja con `alembic_version` viejo y vuelve a correr `upgrade head`). |
| QA-20 | corregido | `_impl_frenar_ritmo`: 30 por 10 min por usuario del sindicato (429 `demasiados`), en memoria del proceso; el equipo no se frena. Variables `IMPL_RITMO_MAX`, `IMPL_RITMO_VENTANA_S`. |
| QA-21 | corregido (parcial a propósito) | Siguen siendo GET (navegación del propio usuario con `SameSite=Lax`); se agrega el rechazo (403) cuando el navegador manda `Sec-Fetch-Site: cross-site`. Un navegador sin esa cabecera sigue como antes: solo ensucia la traza, la respuesta no llega al atacante. |
| QA-22 | corregido | `usuarios.json` (sin `clave_hash`) en el ZIP, mensaje claro al pasar el tope y `?sin_archivos=1` como camino alternativo. |
| QA-23 | aceptado | El título libre en el asunto y el cuerpo del mail es el contenido que el plan permite; no hay inyección de cabeceras (una sola línea, 100 caracteres) y el enlace ya no sale del `Host` (QA-08). |
| QA-24 | pendiente de decisión | Sin cambios (la entrega se cierra a mano); SDN confirma si «cerrada al recibirlo» es obligatorio. |
| QA-25 | aceptado | Sesiones sin estado de 15 min deslizantes; el pedido siguiente ya corta bajas, claves restablecidas y proyectos desactivados. |
| QA-26 | corregido | `plan/hitos/{hid}` valida existencia, texto y orden antes de escribir y escribe tildado + edición en una sola transacción (`commit=False` en `impl_tildar_hito`/`impl_editar_hito`). |
