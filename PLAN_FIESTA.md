# PLAN_FIESTA.md — Entradas de la Fiesta de Fin de Año (SUPARA 2026)

Acordado con SDN el 2026-11-12. Es un **subproducto aparte de Colm3na**: un
trabajo chico y gratuito para resolverle a un sindicato la venta de entradas
de un evento masivo, que nos sirve como puerta de entrada. Por ahora vive en
**Herramientas de `/entornos`** (local y Pruebas, 404 en Demo), con dos
apps: la del **afiliado** (reserva, paga por MercadoPago, recibe la entrada
con QR) y la del **sindicato** (configura, carga el padrón, ve reservas,
emite cortesías y escanea en la puerta). **El sindicato nunca maneja
dinero**: la plata va de MercadoPago a la cuenta del sindicato.

Datos del evento de prueba: «Fiesta de Fin de Año SUPARA 2026», «14 noviembre
2026 - Palacio Anchorena», precio $ 30.000 por entrada, hasta 4 por afiliado,
tope general 1.000. Entradas **no nominales**: una reserva es una sola
entrada con N personas.

## Decisiones (SDN, 2026-11-12)

- D1. **El afiliado entra con legajo + DNI**, los dos tienen que coincidir
  con el padrón que cargó el sindicato. Sin clave ni mail.
- D2. **MercadoPago Checkout Pro por redirección**, con las credenciales del
  sindicato (una aplicación de MP propia; para la prueba, la de SDN) en
  variables de entorno: `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`. Con
  `MP_MOCK=1` el pago se simula sin salir (construir con el mock; la
  integración real queda lista para prender con las variables). Colm3na no
  cobra comisión ni es intermediario de fondos.
- D3. **Vencimiento de la reserva sin pagar lo elige el sindicato** en la
  configuración del evento (`minutos_vencimiento`, default 30). Al vencer,
  las entradas vuelven al tope general.
- D4. **El personal del sindicato entra con usuario y clave propios del
  evento**: rol `admin` (todo) y rol `puerta` (solo escanear y registrar
  ingresos). No depende del PIN de `/entornos` ni de las cuentas de Colm3na.
- D5. **Tope por afiliado acumulado** (4 en total aunque reserve dos veces;
  las vencidas y anuladas no cuentan).
- D6. **Entrada virtual con QR firmado y efímero** (mismo mecanismo que la
  credencial: `qr.codigo_efimero` / `verificar_codigo_efimero`, 10 min,
  renovado solo), habilitada `horas_antes` del evento. Formato ticket de
  espectáculo con la filigrana (`filigrana.filigrana_svg`) y el logo del
  sindicato a un solo tono.
- D7. **Cortesías**: el admin emite entradas a nombre de una persona (nombre +
  DNI + cantidad), con la leyenda «Invitado Especial» (editable), y le manda
  el enlace. Son reservas de tipo `cortesia`, descuentan del tope general y
  no pasan por MP.
- D8. **Ingreso alternativo con documento**: en la puerta se busca por DNI o
  legajo (reserva pagada o cortesía) y se marca el ingreso a mano, con motivo
  («perdió el teléfono»), con quién lo hizo y cuándo.
- D9. **Un pago que llega aprobado sobre una reserva ya vencida se toma
  igual** (la persona pagó): la reserva pasa a `pagada` y, si con eso se
  supera el tope general, queda marcada `sobrecupo` para que el sindicato
  lo resuelva. Nunca se pierde un pago.
- D10. **Diseño elegante, de gala**, con todo (colores, tipografías, radios,
  sombras) en tokens CSS: SDN va a elegir un modelo del catálogo XSD y se
  cambia la hoja de tokens, no las plantillas. Fondo festivo hecho con CSS/SVG
  (noche, luces bokeh, oro) y, si el sindicato sube una foto, esa foto con un
  velo encima.

## Arquitectura

- `fiesta.py` — **motor puro** (no importa `db`): reglas de topes y
  disponibilidad, estados de reserva, vencimiento, ventana de habilitación de
  la entrada, armado del contenido del QR, parseo del CSV del padrón, textos
  de las leyendas. Se prueba solo.
- `mercadopago.py` — **puro, sin SDK** (`urllib`, patrón de `correo.py`):
  `habilitado()`, `modo()` (`real` / `mock` / `apagado`),
  `crear_preferencia(...)`, `validar_firma(...)`, `obtener_pago(payment_id)`.
  Lee las variables en CADA llamada (los tests las simulan). Nunca lanza
  hacia la ruta: devuelve `None`/`False` y deja log. Un `mock` que no sale a
  la red.
- `db.py` — los modelos (prefijo `Fiesta`) y las funciones de acceso que
  reciben la sesión. **Una sesión por request** (regla del proyecto).
- `main.py` — las rutas (están todas en main.py, como el resto: los tests
  de `ast` las recorren ahí). Las páginas del afiliado y del sindicato
  existen solo donde existe `/entornos` (`_exigir_landing()` → 404 en demo).
- `migrations/versions/<rev>_fiesta.py` — migración escrita a mano, con
  `down_revision` = el head actual (`alembic heads`). `test_migraciones.py`
  compara los dos esquemas: JSON con `JSON_TIPO`, bytes con `LargeBinary`
  (diferidos por `db._diferir_columnas_de_bytes`).
- Templates: `templates/fiesta_afiliado.html` (login + inicio + reserva +
  estado del pago, una sola página con vistas `data-mov-vista`),
  `templates/fiesta_entrada.html` (el ticket), `templates/fiesta_verificar.html`
  (lo que ve un lector de QR cualquiera), `templates/fiesta_mp_simulado.html`
  (el checkout simulado), `templates/fiesta_sindicato.html` (login + app del
  sindicato, pestañas).
- Static: `static/fiesta/fiesta.css` (tokens + componentes compartidos),
  `static/fiesta/afiliado.js`, `static/fiesta/entrada.js`,
  `static/fiesta/sindicato.css`, `static/fiesta/sindicato.js`,
  `static/fiesta/logo_supara_{oro,tinta,blanco}.png` (ya están),
  `static/vendor/jsqr/` (jsQR 1.4.0, MIT, con `ORIGEN.md` y SHA-256),
  fuentes OFL nuevas en `static/fonts/` con su licencia en
  `static/fonts/licencias/`. **Todo lo de `/static/` con sello `?v=`**
  (`sello_static`).

## Modelo de datos (db.py)

```
FiestaEvento        id, nombre, fecha_hora (texto ISO "2026-11-14T21:00"),
                    lugar, leyenda_ticket (texto libre del ticket),
                    precio (int, pesos), tope_por_afiliado (int, 4),
                    tope_general (int, 1000), horas_antes (int, 24),
                    minutos_vencimiento (int, 30), leyenda_cortesia
                    ("Invitado Especial"), activo (bool), creado,
                    foto_datos (LargeBinary, nullable), foto_mime (str)
FiestaPadron        id, evento_id, legajo (str), dni (str, solo dígitos),
                    nombre, mail, activo (bool), creado
                    índice único (evento_id, legajo)
FiestaReserva       id, evento_id, padron_id (nullable), tipo
                    ("afiliado" | "cortesia"), legajo, dni, nombre (copia
                    del padrón o de la cortesía), cantidad, importe (int),
                    estado ("pendiente" | "pagada" | "vencida" | "anulada"),
                    creada, vence (ISO; vacío en cortesías), pagada_en,
                    mp_preference_id, mp_payment_id, mp_estado,
                    sobrecupo (bool), token (str único, opaco, 22+ chars
                    urlsafe), ingresados (int), ultimo_ingreso, nota,
                    leyenda (la de la cortesía), emitida_por (operador)
FiestaIngreso       id, reserva_id, cuando, cantidad, modo ("qr" |
                    "documento"), quien, motivo
FiestaOperador      id, evento_id, usuario (único por evento), nombre,
                    clave_hash (auth.hashear_clave), rol ("admin" |
                    "puerta"), activo, creado, debe_cambiar_clave
FiestaAvisoPago     id, evento_id, mp_payment_id (índice), accion,
                    recibido, cuerpo (JSON_TIPO), procesado (bool),
                    resultado (str)
```

Una cortesía es una `FiestaReserva` con `tipo="cortesia"`, `estado="pagada"`,
`importe=0`, `padron_id=None`.

**Disponibilidad** (`fiesta.disponibles(tope_general, reservas)`):
`tope_general - sum(cantidad de pendientes no vencidas + pagadas)`. Las
vencidas y anuladas no cuentan. **Tope por afiliado**: lo mismo sobre las
reservas de ese `padron_id`. El vencimiento se aplica **perezoso**: antes de
contar o de listar, `db.fiesta_vencer_pendientes(s, evento_id)` pasa a
`vencida` toda pendiente con `vence < ahora`. La creación de una reserva
cuenta y descuenta **en la misma transacción** con `SELECT ... FOR UPDATE`
sobre el evento (dos personas reservando las últimas entradas a la vez).

## Sesiones y cookies

Dos cookies NUEVAS en `COOKIES_POR_ROL` de main.py: `sesion_fiesta`
(afiliado, ident = padron_id) y `sesion_fiesta_op` (operador, ident =
operador_id). Firmadas con `auth` como las demás, 15 min de inactividad
renovados por el middleware. Freno por IP en los dos logins (el mismo helper
de los cuatro logins de la app). El operador con `debe_cambiar_clave` cambia
la clave en el primer ingreso (como el panel: clave actual + nueva + repetir).

## Rutas

Todas con `_exigir_landing()` (404 en demo). Las del afiliado y el webhook
son **públicas** (sin PIN): el afiliado y MercadoPago no tienen el pase. La
app del sindicato tiene su propio login. La tarjeta de la pestaña
Herramientas de `/entornos` (con pase) muestra los dos enlaces, el estado
(evento, modo de MP, reservas) y el **arranque**: crear el evento y el
primer operador admin cuando todavía no hay ninguno.

### Afiliado (`/fiesta`)
```
GET  /fiesta                                 página (login o inicio según sesión)
POST /api/fiesta/entrar          {legajo, dni} → 200 {ok} | 401 E-FIESTA-01
POST /api/fiesta/salir
GET  /api/fiesta/estado          → {evento:{nombre, fecha_hora, lugar, precio,
                                   tope_por_afiliado, horas_antes, foto:bool},
                                   afiliado:{nombre, legajo},
                                   disponibles_generales, disponibles_mias,
                                   reservas:[{id, cantidad, importe, estado,
                                   creada, vence, pagada_en, entrada_habilitada,
                                   entrada_desde, ingresados, url_entrada}],
                                   mp_modo}
POST /api/fiesta/reservar        {cantidad} → {reserva_id, init_point}
                                   (crea pendiente, descuenta, crea preferencia;
                                   errores E-FIESTA-02 sin cupo general,
                                   E-FIESTA-03 pasa tu tope, E-FIESTA-04 MP no
                                   respondió → la reserva se anula)
GET  /api/fiesta/reserva/{id}    → la misma fila (para el polling del pago)
POST /api/fiesta/reserva/{id}/anular   solo si está pendiente
GET  /fiesta/pago/vuelta?reserva=ID&estado=  back_url de MP → redirige a
                                   /fiesta#reserva-ID (la pantalla hace polling)
GET  /fiesta/entrada/{id}        el ticket (sesión del afiliado o ?t=token de
                                   la reserva para las cortesías); si no está
                                   habilitada, el ticket "en espera" con la
                                   fecha desde la que se habilita
GET  /api/fiesta/entrada/{id}/qr → {svg, vence_en} renovación del QR
GET  /fiesta/e/{token}?k=codigo  verificación pública (lo que abre cualquier
                                   lector): estado, cantidad, nombre, evento;
                                   sin k o vencido no muestra nada
GET  /fiesta/foto/{evento_id}    la foto de fondo (octet_length para saber si hay)
GET  /fiesta/mp-simulado/{reserva_id}   SOLO con MP_MOCK=1: página con
                                   "Aprobar" / "Rechazar" / "Dejar pendiente"
POST /api/fiesta/mp-simulado/{reserva_id}   idem: aplica el resultado por el
                                   MISMO camino que el webhook
POST /api/fiesta/mp/webhook      el webhook de MercadoPago (ver abajo)
```

### Sindicato (`/fiesta/sindicato`)
```
GET  /fiesta/sindicato                       página (login o app)
POST /api/fiesta/sindicato/entrar   {usuario, clave} → {ok, rol, debe_cambiar_clave}
POST /api/fiesta/sindicato/salir
POST /api/fiesta/sindicato/clave    {actual, nueva, repetir}
GET  /api/fiesta/sindicato/resumen  → {evento, contadores:{tope_general,
                                      reservadas, pagadas, pendientes, vencidas,
                                      cortesias, personas_pagadas, ingresadas,
                                      disponibles, recaudado}, mp_modo, rol}
GET  /api/fiesta/sindicato/reservas?estado=&tipo=&q=&ingreso=  (q: nombre,
                                      legajo o DNI; ingreso: todas|si|no)
POST /api/fiesta/sindicato/reserva/{id}/anular     (pendiente o cortesía)
POST /api/fiesta/sindicato/reserva/{id}/nota
GET  /api/fiesta/sindicato/padron?q=
POST /api/fiesta/sindicato/padron          {legajo, dni, nombre, mail}
POST /api/fiesta/sindicato/padron/csv      archivo (legajo;dni;nombre;mail,
                                      con o sin cabecera; ensayo si no viene
                                      confirmar=1; filas con error listadas)
POST /api/fiesta/sindicato/padron/{id}/activo   {activo}
POST /api/fiesta/sindicato/cortesia        {nombre, dni, cantidad, leyenda,
                                      mail?} → {reserva_id, url_entrada};
                                      si hay mail y correo.habilitado(), manda
                                      el enlace
GET  /api/fiesta/sindicato/configuracion
POST /api/fiesta/sindicato/configuracion   (todos los campos del evento)
POST /api/fiesta/sindicato/foto            UploadFile (imagenes.achicar
                                      "publicacion") / {quitar:1}
GET  /api/fiesta/sindicato/operadores
POST /api/fiesta/sindicato/operador        {usuario, nombre, rol, clave_inicial}
POST /api/fiesta/sindicato/operador/{id}/activo
POST /api/fiesta/sindicato/operador/{id}/restablecer  → clave transitoria
POST /api/fiesta/sindicato/ingreso/qr      {token, k, cantidad?} → {ok, reserva,
                                      ya_ingresados, faltan} | 409 ya ingresó
                                      todo | 403 código vencido | 404
POST /api/fiesta/sindicato/ingreso/documento {reserva_id, cantidad, motivo}
GET  /api/fiesta/sindicato/buscar?q=        para la puerta: reservas pagadas y
                                      cortesías por DNI, legajo o nombre
GET  /fiesta/sindicato/reservas.csv?...     lo filtrado, una fila por reserva
```
El rol `puerta` solo puede: resumen, buscar, ingreso/qr, ingreso/documento,
salir y clave. Todo lo demás → 403.

### Arranque (Herramientas de `/entornos`, con pase)
```
GET  /api/entornos/herramientas/fiesta/estado  → {hay_evento, hay_admin,
                                                 evento, mp_modo, contadores}
POST /api/entornos/herramientas/fiesta/arranque {nombre, fecha_hora, lugar,
                                                 precio, tope_por_afiliado,
                                                 tope_general, usuario, nombre_op,
                                                 clave_inicial}
```

## MercadoPago (D2)

- **Preferencia** (`POST https://api.mercadopago.com/checkout/preferences`,
  `Authorization: Bearer MP_ACCESS_TOKEN`): `items[{title: "<evento> ×N",
  quantity: 1, unit_price: importe, currency_id: "ARS"}]`,
  `external_reference: str(reserva_id)`, `notification_url:
  <base>/api/fiesta/mp/webhook`, `back_urls: {success|failure|pending:
  <base>/fiesta/pago/vuelta?reserva=ID&estado=...}`, `auto_return:
  "approved"`, `expires: true`, `expiration_date_to` = `vence` de la reserva
  (ISO con zona -03:00), `statement_descriptor` corto. Respuesta: `id`,
  `init_point`. `base` sale de `request.base_url` (en Pruebas, https).
- **Webhook**: MP hace POST con query `data.id` y `type=payment` y cabeceras
  `x-signature` (`ts=...,v1=...`) y `x-request-id`. Validación: manifest
  `id:{data.id};request-id:{x-request-id};ts:{ts};` (si `data.id` es
  alfanumérico va en minúsculas), HMAC-SHA256 con `MP_WEBHOOK_SECRET`,
  comparar con `v1` en tiempo constante. Firma inválida → 401. Otro `type` →
  200 y nada. Siempre responder rápido (< 22 s). Después: `GET
  /v1/payments/{id}` → `status`, `external_reference`,
  `transaction_amount`. Se procesa con `db.fiesta_aplicar_pago(s, evento,
  reserva_id, payment)`: `approved` → `pagada` (+ `pagada_en`,
  `mp_payment_id`, `mp_estado`; D9 si estaba vencida); `rejected`/`cancelled`
  → se deja pendiente hasta que venza (la persona puede volver a intentar
  desde el mismo `init_point`); el monto tiene que coincidir con `importe`,
  si no se registra y NO se marca pagada. **Idempotente**: cada aviso queda
  en `FiestaAvisoPago`; el mismo `payment_id` ya procesado no hace nada.
- **Mock** (`MP_MOCK=1`): `crear_preferencia` devuelve `init_point =
  <base>/fiesta/mp-simulado/{reserva_id}` y un id `MOCK-<id>`; la página
  simulada ofrece aprobar / rechazar / pendiente y llama a
  `fiesta_aplicar_pago` con un pago inventado (`payment_id = "MOCK-<id>-<n>"`).
  `obtener_pago` en mock devuelve lo que la página simuló.
- **Apagado** (sin token y sin mock): `reservar` responde E-FIESTA-05 «el
  cobro no está configurado» y el admin lo ve en la configuración.
- Documentación para SDN en `docs/FIESTA.md`: crear la aplicación en MP,
  copiar credenciales de prueba, cargar las variables en Render, configurar
  el webhook en el panel de MP con la URL de Pruebas, tarjetas de prueba
  (titular APRO/OTHE/CONT, DNI 12345678), y qué cambia para pasar a
  producción con la cuenta del sindicato.

## El ticket (D6)

Contenido del QR: `<base>/fiesta/e/{token}?k={codigo}` con `codigo =
qr.codigo_efimero(token)`. La app del sindicato lee ese texto, saca `token` y
`k` y llama a `ingreso/qr`. `verificar_codigo_efimero` decide; un QR
capturado deja de servir a los 10 min. El ticket:

- Formato de entrada de espectáculo, apaisada en escritorio y vertical en
  teléfono, con **talón perforado** (línea de puntos + muescas) donde va el
  QR, y el cuerpo con: logo del sindicato a un tono, «Fiesta de Fin de Año
  SUPARA 2026» en la tipografía de display, «14 noviembre 2026 - Palacio
  Anchorena», nombre de la persona, «ADMITE N PERSONAS» grande, número de
  reserva, y en las cortesías la leyenda «INVITADO ESPECIAL» en una banda.
- Filigrana `filigrana_svg("SUPARA", oro_oscuro, oro_claro)` encima del fondo
  y debajo del contenido, como la credencial.
- El QR se renueva solo antes de vencer (`entrada.js`, mismo patrón que
  `cred-qr` de trabajador.html), con un aro o cuenta regresiva discreta.
- Estados: **en espera** (todavía no se habilitó: se ve el ticket con un velo
  y «Se habilita el 13/11 a las 21:00»), **habilitada**, **ingresó** (sello
  INGRESÓ con la hora; si entraron menos personas que las admitidas, dice
  cuántas faltan), **vencida/anulada** (no se muestra el ticket).
- Botón «Agregar a la pantalla de inicio» no hace falta; sí «Compartir
  enlace» (navigator.share si existe) para las cortesías.

## La app del afiliado

Una sola página, vistas con `data-mov-vista`. Fondo de gala (D10). Flujo:
1. **Ingreso**: legajo + DNI, botón «Entrar». Error claro si no coincide
   (E-FIESTA-01, sin decir cuál de los dos está mal).
2. **Inicio**: tarjeta del evento (nombre, fecha, lugar, precio, cuántas
   quedan en general si quedan pocas), «Tus entradas» con cada reserva y su
   estado (pendiente con cuenta regresiva hasta `vence` y botón «Pagar
   ahora» que vuelve al `init_point`; pagada con «Ver tu entrada»; vencida
   atenuada) y el bloque **Reservar**: selector de cantidad 1..disponibles
   propias, total calculado, botón «Reservar y pagar $ 120.000».
3. **Pago**: al volver de MP (o del simulado) la pantalla muestra la reserva
   con «Confirmando el pago…» y hace polling a `/api/fiesta/reserva/{id}`
   cada 3 s hasta 2 min; al pasar a pagada, lo celebra (movimiento sobrio) y
   ofrece «Ver tu entrada». Si sigue pendiente, lo dice y deja «Pagar ahora».
4. **Entrada**: `/fiesta/entrada/{id}`.
Importes en formato argentino (`formato_ar` / `numeros_ar.js`). Fechas en
castellano («viernes 14 de noviembre, 21:00»).

## La app del sindicato

Una sola página con login propio y pestañas (`data-mov-vista`), móvil
primero porque la puerta se maneja desde el teléfono:
- **Panel**: contadores grandes (vendidas / pagadas / pendientes /
  disponibles / ingresadas / recaudado) y la lista de reservas con filtros
  (estado, tipo, ingreso, búsqueda) y «Descargar CSV». Cada fila: nombre,
  legajo, DNI, cantidad, estado con fecha, ingresos, acciones (anular una
  pendiente o cortesía, nota, abrir la entrada).
- **Puerta**: el escáner (cámara trasera, `getUserMedia` + jsQR vendoreado
  sobre un `<canvas>`; si el navegador trae `BarcodeDetector`, usarlo
  primero), con el resultado en grande y en color: VERDE «Pasa · 4 personas
  · Juan Pérez», con botón para registrar menos personas que las admitidas;
  ÁMBAR «Ya ingresaron 2 de 4»; ROJO «Ya ingresó todo» / «Código vencido,
  que renueve la pantalla» / «No existe». Vibración si `navigator.vibrate`.
  Debajo, **ingreso con documento**: buscador por DNI, legajo o nombre, la
  reserva encontrada con su estado, cantidad e ingresos, y «Registrar
  ingreso» con cantidad y motivo obligatorio.
- **Padrón**: subir CSV (ensayo con lo que se va a cargar y las filas con
  error; después confirmar), alta de a uno, lista con búsqueda y activar/
  desactivar.
- **Cortesías**: nombre, DNI, cantidad, leyenda (default «Invitado
  Especial»), mail opcional; al emitir muestra el enlace de la entrada para
  copiar/compartir y si hay mail avisa que se mandó.
- **Configuración** (solo admin): los campos del evento, la foto de fondo
  (subir / quitar, con vista previa), estado de MercadoPago (modo real /
  simulado / apagado, solo lectura, con el texto de qué variables faltan), y
  **Operadores**: lista, alta (usuario, nombre, rol, clave inicial),
  activar/desactivar, restablecer clave (muestra la transitoria una vez).
- El rol `puerta` ve solo la pestaña Puerta y «Salir».

## Diseño (D10)

Tokens en `static/fiesta/fiesta.css`, `:root`:
```
--f-noche:#0b0f1f  --f-noche-2:#161436  --f-tinta:#121828  --f-papel:#f7f3ea
--f-oro:#d6b876    --f-oro-claro:#efdfb4  --f-oro-oscuro:#9a7d3e
--f-texto:#f4efe4  --f-texto-suave:rgba(244,239,228,.72)
--f-ok:#3fb47c     --f-aviso:#e0b23a  --f-error:#d9534f  --f-info:#5fa8d3
--f-display:'Cinzel', 'Playfair Display', Georgia, serif   (títulos y ticket)
--f-texto-fuente:'Manrope', system-ui, sans-serif
--f-mono:'Archivo', ui-monospace, monospace                 (números, códigos)
--f-radio:14px  --f-radio-chico:8px
--f-sombra:0 18px 50px rgba(0,0,0,.45)
--f-velo:linear-gradient(180deg, rgba(11,15,31,.55), rgba(11,15,31,.92))
```
Fuentes: bajar de Google Fonts **Cinzel** (700) y **Playfair Display** (400 y
700 itálica) en woff2 con su licencia OFL a `static/fonts/` y
`static/fonts/licencias/`; Manrope y Archivo ya están. Fondo: capa de noche
con degradé, luces bokeh (círculos borrosos en oro con `filter: blur`,
animación lentísima, apagada con `prefers-reduced-motion`), grano sutil; si
hay foto del evento, va debajo con `--f-velo` encima. Tarjetas en vidrio
oscuro (fondo `rgba(18,24,40,.72)`, `backdrop-filter: blur(14px)`, filo de 1px
en oro al 25 %). Movimiento con los tokens de `static/movimiento.css`
(cargarla antes). Botón primario en oro con texto en tinta; secundario con
borde en oro. Los avisos de error en rojo fijo. En la app del sindicato, la
misma noche pero más sobria, con tablas legibles (texto claro sobre tinta,
filas con separador al 10 %) y, en Puerta, los resultados en bloques de color
pleno que se ven a dos metros. Sin librerías de UI. Sin `innerHTML` con
texto de personas: `textContent` siempre.

## Errores (`errores.py`)

`E-FIESTA-01` legajo o DNI no coinciden · `02` no quedan entradas · `03`
pasa tu tope · `04` MercadoPago no respondió (la reserva se anuló, probá de
nuevo) · `05` el cobro no está configurado · `06` la entrada todavía no está
habilitada · `07` código del QR vencido · `08` ya ingresaron todas las
personas · `09` reserva no pagada · `10` usuario o clave incorrectos ·
`11` padrón: fila inválida.

## Qué NO se hace ahora

Entradas nominales, varios eventos a la vez en la misma pantalla (la tabla lo
permite, la app muestra el activo), devoluciones por MP, mail al afiliado
cuando paga (solo si `correo.habilitado()`, y es opcional), app instalable.

## Tests

- `test_fiesta.py`: motor puro (disponibilidad, topes acumulados,
  vencimiento, ventana de habilitación, CSV), rutas con `TestClient`
  (login, reservar descuenta y respeta topes, concurrencia de las últimas
  entradas, vencimiento perezoso devuelve cupo, webhook firmado/no firmado,
  idempotencia, D9 sobrecupo, monto distinto no marca pagada, cortesía,
  ingreso por QR y por documento, rol puerta 403, `sesion_fiesta_op` no abre
  `/admin` ni al revés, 404 en demo, el QR vencido no entra).
- `test_mercadopago.py`: firma (vector real de la documentación), mock,
  apagado, preferencia con `urlopen` simulado.
- `test_fiesta_pantallas.py`: las plantillas cargan sus static con sello,
  todos los `fetch`/`action` apuntan a rutas que existen, nada de
  `innerHTML` con datos, `data-mov-vista` en las vistas, el vendor con su
  `ORIGEN.md` y SHA-256.
- Los de siempre que la pieza toca: `test_migraciones.py`, `test_fechas.py`,
  `test_imagenes.py`, `test_paginas_sin_bytes.py`, `test_mapa_funcional.py`,
  `test_modales.py`, `test_cuit_puertas.py`, `ruff check .`, `bandit -lll`.
- E2E con Playwright (`e2e/test_robot_fiesta.py`): afiliado reserva, paga en
  el simulado, ve la entrada; operador escanea (se inyecta el texto del QR)
  y la persona queda ingresada; segundo escaneo rechazado; ingreso con
  documento. Capturas de cada pantalla en escritorio y teléfono.
