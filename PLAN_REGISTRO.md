# PLAN_REGISTRO.md — Registro y recuperación de cuenta con niveles de fiabilidad

**Estado:** acordado con SDN el 2026-10-11, decisión por decisión, antes de
tocar código. Es la **segunda medida** de la serie para regularizar las
observaciones de XSANDERS (XSK), la que `PLAN_CUIT_MOD11.md` anunciaba como
siguiente: cierra el hallazgo **H-0017** (el alta acredita identidad solo con
el CUIL, que es público) y las decisiones **R2** (niveles de fiabilidad de
registro) y **R3** (recuperación de clave por mail) del relevamiento.

---

## 0. Qué se quiere y por qué

Hoy un trabajador se registra solo si su CUIL está en el padrón de algún
sindicato. Es un control, pero el CUIL es dato público: **el primero que
llega con el CUIL de un afiliado se queda con su cuenta**, y el afiliado real
se encuentra con "ya tenés una cuenta" y sin cómo reclamarla. Un impostor no
accede a datos de otro (la cuenta nace vacía), pero puede usar la app, la
credencial y los trámites a nombre de una persona que no es, y eso es lo que
se quiere evitar.

Lo que se acordó, en una frase: **el registro pasa a confirmarse por mail, el
nivel de confianza de cada cuenta queda como dato visible para el sindicato,
y el mismo mecanismo da la recuperación de clave que hoy no existe.** Más un
captcha y un freno en el registro, para que atacarlo en masa cueste.

Los cuatro niveles son los de R2, sin cambios:

| Nivel | Qué acredita | Cómo se llega |
|---|---|---|
| 1 | El CUIL está en el padrón | Como hoy. Queda solo para las cuentas ya creadas y para cuando el canal de mail está apagado. |
| 2 | Alguien que controla un mail | Código de 6 dígitos. Dos variantes: **mail del padrón** (lo cargó el sindicato) o **mail declarado** (lo dio la persona). |
| 3 | Un recibo propio leído por la IA | Automático: el primer recibo validado cuyo CUIL coincide con el de la sesión. |
| 4 | Una persona del sindicato lo confirmó | Botón del admin en Trabajadores. |

El nivel **sube y no baja**, y **ningún nivel esconde nada en la app**
(decisión de SDN, ver D4): el control es del sindicato, que lo ve en el
padrón y actúa desde ahí.

---

## 1. Lo que dice el código hoy (relevado el 2026-10-11)

- **`POST /trabajador/registro`** (main.py): CUIL con verificador + en el
  padrón (`db.sindicatos_de_cuil`) + clave elegida → cuenta creada y sesión
  abierta en el mismo POST. Pide los mismos campos que el perfil (nombre,
  domicilio, teléfono, mail). **`POST /empresa/registro`** es el espejo con
  CUIT y `CuentaEmpleador`.
- **Sin freno.** `_login_bloqueado`/`_login_fallo` (H-0008) protegen los
  cuatro logins, pero no las dos rutas de registro.
- **Los mensajes revelan afiliación.** `nohabilitado` contra `yaexiste` dice
  si un CUIL figura en algún sindicato. La afiliación es dato sensible (Ley
  25.326, eje LEY): sin freno ni captcha es una enumeración gratis.
- **El mail del formulario se escribe en el padrón**
  (`db.guardar_datos_personales(..., mail=mail)`): si quien se registra es un
  impostor, pisa el contacto de la persona real.
- **El padrón puede tener mail.** `CuentaTrabajador.mail` (una fila por
  CUIL) se carga desde el alta individual y la masiva (columna 9 de
  `/admin/trabajador/masivo`). `Empleador.mail` es por sindicato, no está
  unificado.
- **Reset de clave: solo plataforma**, `POST /plataforma/reset-clave`,
  marcado TRANSITORIO. El admin del sindicato no puede.
- **No hay proveedor de mail ni captcha.** La CSP (`main.CSP`) es
  `script-src 'self' 'unsafe-inline'` sin ningún origen externo;
  `connect-src` ya admite `https:`.
- **Lo que sí existe y se reutiliza**: `/api/leer` corta un recibo que no es
  del CUIL de la sesión (E-RECIBO-04), así que "recibo propio validado" ya
  es un hecho que el servidor conoce; el freno por IP en memoria; el patrón
  "sin claves, apagado en silencio" de `telegram.py` y `push.py`.

---

## 2. Decisiones acordadas con SDN (2026-10-11)

**D1. Registro en tres pasos, con captcha y freno antes de mirar el padrón.**
(1) CUIL + captcha + freno por IP; recién después se consulta el padrón.
(2) Si el padrón tiene mail para ese CUIL, se manda el código ahí, mostrando
solo una pista (`j***@gmail.com`); confirmado, la cuenta nace **nivel 2, mail
del padrón**. (3) Si no tiene, la persona declara uno, recibe el código y
confirma; la cuenta nace **nivel 2, mail declarado**, marcada así para el
sindicato. El mail declarado se guarda **en una columna aparte** del mail
del padrón: nunca lo pisa.

**D2. La cuenta no se crea hasta confirmar el código.** La clave y los datos
personales se piden en el último paso. El código vence a los 15 minutos,
admite 5 intentos y se guarda hasheado; se pueden pedir a lo sumo 3 códigos
por hora por CUIL (para que nadie use el registro para bombardear el mail de
un afiliado).

**D3. Nivel 3 automático, nivel 4 a mano.** El primer recibo validado por
`/api/validar` cuyo CUIL es el de la sesión sube la cuenta a 3 sin pedirle
nada a la persona. El nivel 4 es un botón "Confirmé su identidad" en la
pestaña Trabajadores, dentro del alcance de seccional del operador.

**D4. Todos los niveles ven todo.** No se esconde la Credencial ni Mis
Aportes al nivel 2 declarado. El control del nivel es del sindicato: lo ve
en Trabajadores y actúa desde ahí. (Se descartó la propuesta de ocultar la
credencial hasta el nivel 3; se puede volver a mirar con un sindicato real.)

**D5. Política por sindicato.** Un interruptor en la ficha del sindicato:
**"acepta mail declarado"** (default: bloquear el registro a quien no tiene
mail cargado mata la adopción) o **"solo mail del padrón"** (para gremios
que cargaron mails). En Trabajadores, columna con el nivel y filtro
"declarados sin recibo verificado".

**D6. Recuperación de clave en el mismo bloque (R3).** Autoservicio por
código **al mail del padrón**, si existe. Si la cuenta solo tiene mail
declarado, la recuperación la hace **el admin del sindicato** desde
Trabajadores (clave temporal que se muestra una vez y se cambia en el primer
ingreso), dentro de su alcance de seccional. Esto es lo que le devuelve la
cuenta al afiliado real cuando un impostor llegó primero. **El reset de
plataforma se mantiene mientras duren las demos**, para emergencias, y se
saca en la implementación en producción (ya figura en Pendientes 2 de
`CLAUDE.md`).

**D7. Captcha: Cloudflare Turnstile.** Gratis, sin rompecabezas, y
Cloudflare ya es la decisión de perímetro (INF-05). Va en los dos registros,
en el pedido de código y en la solicitud de recuperación. Costo asumido: la
CSP suma `https://challenges.cloudflare.com` en `script-src` y `frame-src`,
una **excepción explícita** a la regla de no cargar nada externo. Sin
`TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET` queda apagado en silencio. Los
logins siguen con el freno de hoy.

**D8. Proveedor de mail: Resend**, por el subdominio
**`avisos.colm3na.com.ar`** (dominio ya registrado; `cm3.com.ar` queda como
redirección). El mail humano de la empresa (Google Workspace, cuando
llegue) usa el dominio raíz: separar los dos es lo que impide que un rebote
masivo de códigos manche el correo de la empresa, y al revés. Resend da
3.000 mails por mes gratis (Postmark, 100 y aprobación a mano), y se llama
con un POST HTTPS sin librería, el patrón de `telegram.py`. Variables:
`RESEND_API_KEY` y `MAIL_REMITENTE`.

**D9. Todo junto, y el mail apagado no frena el resto.** Se construye todo
en este bloque. Mientras el dominio y Resend no estén configurados, el
registro **salta el paso del código y la cuenta nace nivel 1**, como hoy,
pero con el nivel visible: las demos siguen andando y el panel dice qué
cuentas no confirmaron nada. `chequeo.py` y la Sala de mando muestran el
canal de mail como apagado; en producción tiene que estar prendido.

**D10. Las cuentas ya registradas quedan en nivel 1** con origen "CUIL en el
padrón (anterior a este plan)". En su próximo ingreso ven un aviso **no
bloqueante** para confirmar su mail y pasar a nivel 2; las que ya tengan un
recibo propio validado suben a 3 en la migración.

**D11. La enumeración queda mitigada, no cerrada.** "Tu CUIL no está
habilitado" es información que la persona necesita (tiene que ir al
sindicato) y con la variante de mail declarado no hay forma de no decirla.
Captcha más freno la vuelven cara; se registra como riesgo residual aceptado
en el XSK (eje LEY), igual que H-0013.

---

## 3. Modelo de datos

Una migración (`alembic revision --autogenerate`), columnas con `JSON_TIPO`
donde haga falta y sellos de tiempo como texto en hora de Buenos Aires
(`fechas.ahora_texto()`), como todo el proyecto.

**`CuentaTrabajador`** (la persona) suma:

| Columna | Qué es |
|---|---|
| `nivel_fiabilidad: int = 1` | 1 a 4 (R2). Sube, no baja (`db.subir_nivel`, única implementación). |
| `nivel_origen: str = ""` | `cuil_padron` / `mail_padron` / `mail_declarado` / `recibo_propio` / `presencial`. Lo que justificó el nivel actual. |
| `nivel_actualizado: str = ""` | Cuándo. |
| `mail_declarado: str = ""` | El que dio la persona al registrarse. **Nunca pisa `mail`**, que sigue siendo del padrón. |
| `mail_declarado_confirmado: str = ""` | Cuándo se confirmó (vacío = no). |
| `clave_temporal: bool = False` | La puso el admin del sindicato; el primer ingreso obliga a cambiarla. |

**`CuentaEmpleador`** suma las mismas seis columnas. El mail del padrón de
una empresa se toma del primer `Empleador.mail` no vacío entre sus altas
(el empleador no está unificado, ver BACKLOG).

**`Sindicato`** suma `acepta_mail_declarado: bool = True` (D5).

**Tabla nueva `CodigoVerificacion`**: `id`, `tipo` (`trabajador` /
`empleador`), `identificador` (CUIL o CUIT), `proposito` (`registro` /
`recuperacion`), `destino` (el mail al que se mandó), `origen_destino`
(`padron` / `declarado`), `codigo_hash`, `creado`, `vence`, `intentos`,
`usado_en`, `ip`. Un código usado o vencido no se borra: es la traza de
quién pidió qué (como `CambioIdentificador`).

**Qué nivel asigna cada camino**

| Camino | Nivel | Origen |
|---|---|---|
| Código al mail del padrón | 2 | `mail_padron` |
| Código a un mail declarado | 2 | `mail_declarado` |
| Canal de mail apagado (D9) | 1 | `cuil_padron` |
| Primer recibo propio validado | 3 | `recibo_propio` |
| Botón del admin | 4 | `presencial` |

---

## 4. Flujo, pantalla por pantalla

### 4.1 Registro del trabajador (`trabajador_login.html`, pestaña Registrarme)

1. **CUIL.** `POST /trabajador/registro/iniciar` con el token del captcha.
   Freno por IP (mismo mecanismo que los logins, tabla aparte). Valida
   verificador y padrón. Si el canal de mail está apagado, responde
   `paso: datos` (va directo al paso 3, nivel 1). Si el padrón tiene mail,
   manda el código y responde `paso: codigo` con la pista. Si no tiene y el
   sindicato acepta declarado, responde `paso: mail`; si no lo acepta,
   mensaje "tu sindicato pide que confirmes con el mail que ellos tienen;
   pedíselo" y fin.
2. **Mail declarado** (solo si hace falta). `POST /trabajador/registro/mail`
   manda el código a ese mail. Cupo de 3 por hora por CUIL.
3. **Código + clave + datos.** `POST /trabajador/registro` recibe el código,
   la clave y los mismos campos que el perfil, de hoy. Verifica el código
   (hash, vencimiento, intentos), crea la cuenta con el nivel que
   corresponda, marca los empadronamientos como registrados y abre la sesión
   firmada, como ahora. El mail declarado va a `mail_declarado`; el campo
   `mail` del formulario desaparece (ya no tiene sentido pedirlo dos veces).

El estado entre pasos viaja en un **token firmado** (HMAC con
`SESSION_SECRET`, `auth.py`), con el CUIL, el id del código y la hora:
nada en la cookie plana, igual que la identidad de sesión (H-0004).

### 4.2 Registro de la empresa (`empresa_login.html`)

El espejo exacto, con CUIT, `CuentaEmpleador` y `Empleador.mail`. Tablas y
rutas separadas (aislamiento total trabajador/empleador, decisión vigente).

### 4.3 Recuperación de clave (`/ingresar/recuperar`, `/ingresar-empresa/recuperar`)

Enlace "Olvidé mi clave" en los dos logins. CUIL + captcha → si la cuenta
tiene mail del padrón, código ahí → clave nueva. Si solo tiene mail
declarado o ninguno: "pedile al sindicato que te la restablezca", sin decir
cuál es el caso. Mismo freno y mismo cupo que el registro.

### 4.4 Pestaña Trabajadores (`admin.html`)

- Columna **Nivel** con etiqueta corta (1 · CUIL, 2 · mail padrón, 2 · mail
  declarado, 3 · recibo, 4 · confirmado) y filtro "declarados sin recibo
  verificado".
- Botón **"Confirmé su identidad"** → `POST /admin/trabajador/confirmar-identidad`
  (nivel 4, dentro del alcance de seccional, sección `trabajadores` en
  `PERMISOS_RUTAS`).
- Botón **"Restablecer clave"** → `POST /admin/trabajador/restablecer-clave`:
  genera una clave temporal, la muestra una sola vez, marca
  `clave_temporal`; el próximo login del afiliado obliga a cambiarla.
- Lo mismo en Empleadores para las cuentas de empresa.

### 4.5 Ficha del sindicato (plataforma)

Interruptor "Acepta registro con mail declarado" junto a la cláusula de
confidencialidad. Lo edita plataforma, como el resto de la configuración del
sindicato (ver decisión abierta 1).

### 4.6 Aviso a las cuentas viejas (D10)

En `/app/inicio`, una tarjeta no bloqueante "Confirmá tu mail" para nivel 1
con mail en el padrón o sin mail. Lleva a un flujo de dos pasos (código →
listo) que sube a nivel 2.

### 4.7 Módulos nuevos

- **`correo.py`**: `enviar(destino, asunto, texto)` por POST a la API de
  Resend con `urllib`, sin librería; `habilitado()` dice si están las dos
  variables; apagado en silencio sin ellas. Textos de los mails en el mismo
  módulo (código de registro, código de recuperación), en castellano, sin
  nombre de la persona (el mail del padrón puede estar desactualizado y
  llegarle a otro).
- **`captcha.py`**: `verificar(token, ip)` contra
  `challenges.cloudflare.com/turnstile/v0/siteverify`; `habilitado()`. El
  parcial `templates/_captcha.html` pone el widget solo si está habilitado.
- **`db.py`**: `subir_nivel(s, cuenta, nivel, origen)`, `crear_codigo`,
  `verificar_codigo`, `mail_padron_de(cuil)`, `mail_padron_de_empresa(cuit)`.
- **`main.py`**: las rutas de 4.1 a 4.4; el enganche de nivel 3 en
  `/api/validar`; el freno de registro reutilizando el mecanismo de H-0008
  con su propia tabla; `frame-src` y `script-src` en `CSP`.
- **`mapa_funcional.FUNCIONALIDADES`**: regla para los prefijos nuevos
  (`/trabajador/registro/`, `/ingresar/recuperar`, etc.), si no caen en
  "Sin clasificar".

---

## 5. Etapas

**Prerrequisitos externos (SDN, en paralelo con la etapa 1):**
1. Delegar `colm3na.com.ar` a los nameservers de Cloudflare desde NIC
   Argentina.
2. En Resend, dar de alta el dominio `avisos.colm3na.com.ar`; cargar en
   Cloudflare los registros DNS que devuelve (DKIM, SPF, rebotes) y esperar la
   verificación.
3. En Cloudflare, crear el sitio de Turnstile para los hosts de Pruebas y
   Demo (modo "managed", sin interacción salvo sospecha).
4. En Render (Pruebas primero): `RESEND_API_KEY`, `MAIL_REMITENTE`
   (`Colm3na <no-responder@avisos.colm3na.com.ar>`), `TURNSTILE_SITE_KEY`,
   `TURNSTILE_SECRET`. Documentar en `DESPLIEGUE_RENDER.md`.

### Etapa 1 — Freno y captcha en el registro (no depende de nada externo)

Freno por IP en `/trabajador/registro` y `/empresa/registro`; `captcha.py` y
el parcial; CSP. Con las claves apagadas el comportamiento es el de hoy más
el freno. Cierra la mitad barata de D11. Tests: freno; captcha rechazado;
captcha apagado deja pasar; la CSP incluye el origen solo cuando está
habilitado (o siempre: decisión abierta 2).

### Etapa 2 — Modelo, mail y registro en tres pasos

Migración (§3), `correo.py`, los tres pasos del trabajador y de la empresa,
el token firmado entre pasos, fallback a nivel 1 con el canal apagado (D9),
`chequeo.py` reporta el canal. Tests (`test_registro.py`, con `correo.enviar`
mockeado): la cuenta no existe antes del código; código vencido, agotado,
ajeno; mail declarado no pisa el del padrón; política "solo padrón" rechaza
el declarado; cupo de 3 por hora; canal apagado → nivel 1 con origen
`cuil_padron`; el espejo de empresa.

### Etapa 3 — Niveles 3 y 4, panel y política

Enganche en `/api/validar`; `subir_nivel` nunca baja; botón de confirmación
con alcance de seccional; columna y filtro en Trabajadores y Empleadores;
interruptor en la ficha del sindicato; aviso a cuentas viejas (D10) y el
backfill a nivel 3 de las que ya tienen recibo propio. Tests: un recibo de
OTRO CUIL no sube nada (E-RECIBO-04 sigue antes); un Admin de Seccional no
confirma fuera de su seccional; nivel 4 no baja a 3 con un recibo posterior.

### Etapa 4 — Recuperación de clave

Autoservicio por mail del padrón; restablecer desde el panel con clave
temporal y cambio obligatorio en el primer ingreso; el reset de plataforma
queda como está, con su advertencia. Tests: con mail declarado solamente no
sale código; la clave temporal no sirve dos veces; el mensaje es el mismo
haya o no cuenta (no revelar).

### Etapa 5 — Cierre

- XSK: **H-0017 → Solucionado**, test IDS-04 corrido en Pruebas (registro con
  CUIL ajeno sin acceso al mail → no se crea), riesgo residual de D11
  registrado, R2 y R3 marcadas en `relevamiento.md`, `correo.py` y Turnstile
  en el mapa técnico. Corrida en `xsk/proyectos/mitrabajo/corridas/`.
- `CLAUDE.md`: decisión nueva ("el registro se confirma por mail y el nivel
  de fiabilidad es dato de la cuenta; ningún nivel esconde nada"), variables
  de entorno, "Estado actual". `HISTORIAL.md`, `BITACORA.md`,
  `DESPLIEGUE_RENDER.md`, `docs/INDICE.md`.
- Sala de mando (`esquema.py` / `esquema.html`): Resend como servicio
  externo, Turnstile dentro de Cloudflare; el canal de mail en el radar.
- `docs/generador` y `mapa_funcional.py` regenerados.
- Versiones: Trabajador y Admin suben el minor (funcionalidad nueva);
  Plataforma, el patch por el interruptor.

Las etapas 1 y 2 van en el mismo PR; 3 y 4 pueden ir en uno o dos más.

---

## 6. Riesgos

- **El freno por IP es parcial a propósito** (`X-Forwarded-For` falsificable),
  como H-0008: el freno de verdad es el perímetro de Cloudflare, que ahora
  se vuelve prerrequisito de dos cosas a la vez.
- **Mail del padrón desactualizado.** Si el sindicato tiene un mail viejo, la
  persona no puede registrarse ni recuperar la clave por su cuenta: tiene que
  pedirle al sindicato que lo corrija. Es deliberado: si se permitiera caer al
  mail declarado cuando el padrón ya tiene uno, el camino fuerte se
  saltearía con solo decir "ese mail no es más mío". La pantalla lo explica.
- **Entrega a Hotmail/Yahoo** sin reputación de dominio: las primeras semanas
  pueden caer en spam. Mitigación: texto corto, sin enlaces, DKIM alineado, y
  la pantalla dice "revisá correo no deseado". Se mide con los rebotes que
  devuelve Resend.
- **Turnstile caído** con las claves puestas: la verificación falla cerrada
  ("intentá en un minuto") y se avisa por Telegram con freno de 10 minutos,
  como los errores no previstos. Nadie se registra durante la caída; se
  prefiere a dejar la puerta sin captcha sin que nadie lo sepa (decisión
  abierta 2).
- **Impostores ya registrados antes del deploy** quedan en nivel 1 y
  visibles con ese nivel: el sindicato puede pedirles que confirmen o
  restablecer la clave para que la recupere el afiliado real.
- **El cupo de códigos por CUIL** impide bombardear a un afiliado, pero un
  atacante con muchos CUIL del padrón puede gastar el cupo mensual de Resend
  (3.000): el captcha es lo que lo encarece; si pasa, el canal se apaga solo
  y el registro cae a nivel 1 (D9), nunca a un 500.

---

## 7. Cierre

- Un CUIL del padrón **no se puede registrar sin acceso al mail** (del padrón
  o uno declarado y confirmado), salvo con el canal apagado, y en ese caso el
  nivel 1 queda a la vista del sindicato.
- El sindicato ve el nivel de cada afiliado, puede confirmarlo a mano y puede
  restablecerle la clave dentro de su alcance.
- El afiliado recupera su clave solo, si el padrón tiene su mail.
- H-0017 Solucionado; R2 y R3 cumplidas; la suite pasa archivo por archivo y
  el CI en verde.

---

## 8. Decisiones abiertas (menores, para SDN)

1. **Dónde vive el interruptor de D5.** *Propuesta:* en la ficha del
   sindicato de plataforma, como la cláusula de confidencialidad. Si un
   gremio pide manejarlo solo, se expone después al Super Admin.
2. **Captcha caído: ¿falla cerrado o abierto?** *Propuesta:* cerrado, con
   aviso a Telegram. Un minuto sin registros es mejor que una puerta abierta
   que nadie ve.
3. **Cambiar el mail declarado desde el perfil.** *Propuesta:* se puede, pero
   vuelve a `mail_declarado_confirmado` vacío y pide código de nuevo; el
   nivel no cambia (ya es 2 o más).
4. **Teléfono como segundo canal** (WhatsApp o SMS) para gremios que tienen
   teléfonos y no mails. *Propuesta:* fuera de este plan; se anota en
   `BACKLOG.md` con lo relevado (es el único otro dato del padrón que sirve
   como secreto compartido).
