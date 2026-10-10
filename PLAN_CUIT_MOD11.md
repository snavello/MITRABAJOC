# PLAN_CUIT_MOD11.md — Validar CUIL/CUIT con el módulo 11

**Estado:** propuesta del 2026-10-10, **a acordar con SDN decisión por
decisión** antes de tocar código. Es la **primera medida** de la serie para
regularizar las observaciones de XSANDERS (XSK); la que sigue es el alta de
usuarios (H-0017, niveles de fiabilidad de registro). Retoma el pendiente de
`BACKLOG.md` "Validar el módulo 11 (dígito verificador) de CUIL y CUIT".

---

## 0. Qué se quiere y por qué en este orden

Hoy la app solo exige **11 dígitos**, y no en todas las puertas. Nadie mira el
dígito verificador. Empezar a exigirlo deja inválida a la mayoría de lo ya
cargado — **ninguno de los CUIL/CUIT de la demo lo cumple** — así que el orden
es:

1. **Identificar** todo CUIL/CUIT inválido de cada base, sin escribir nada.
2. **Convertir a un número válido solo los creados a mano como prueba**
   (ej. `27999999999`), en TODAS las tablas donde aparecen, de una vez.
   Los **sintéticos** (los que generan los scripts de lote) no se borran ni
   se corrigen en esta etapa; si después resulta fácil, se hace.
3. **Recién entonces exigir** el verificador en las puertas por donde entra
   un número nuevo.

Si se exige antes de convertir, el primero que edite un dato cargado a mano
choca con su propio CUIL.

### El algoritmo (AFIP)

Pesos `5 4 3 2 7 6 5 4 3 2` sobre los diez primeros dígitos;
`r = 11 − (suma mod 11)`; si `r = 11` el verificador es `0`; si `r = 10` ese
prefijo **no tiene verificador posible** y AFIP asigna otro prefijo
(`23` para personas, `33` para empresas) y recalcula.

| Número | Resultado |
|---|---|
| `20202790411` | válido |
| `27999999999` | inválido; con los mismos diez primeros dígitos el verificador es 4 → `27999999994` |
| `20121212127` | inválido y con `r = 10` → cambia el prefijo → `23121212129` |

Ya existe una implementación, `enmascarado.dv_valido()`, que hoy solo se usa
como prueba de lectura y no valida nada. Pasa a ser la única (decisión D1).

---

## 1. Lo que dice el código hoy (relevado el 2026-10-10)

### 1.1 Dónde vive un CUIL o un CUIT

**No hay ninguna clave foránea**: todo se une por texto. Si se cambia un
número en una tabla y no en otra, la relación se corta en silencio. Por eso
la conversión va **en una sola transacción, sobre todas las columnas a la
vez**.

**Persona (CUIL)**

| Tabla.columna | Qué es |
|---|---|
| `cuentatrabajador.cuil` | La persona (**único**). Dueña de nombre, domicilio, foto. |
| `trabajador.cuil` | Cada empadronamiento en un sindicato. |
| `usuariosindicato.usuario` + `.cuil` | Login del operador (hoy = su CUIL) y su identidad; `.cuil` lo vincula al padrón. |
| `usuarioplataforma.cuil` (+ `.dni`) | Datos que completa el usuario nominal de plataforma. |
| `reciboverificado.cuil` + `detalle→empleado→cuil` (JSONB) | Recibos verificados. |
| `enviosindicato.cuil` + `detalle` | Envíos consentidos al sindicato (art. 21 bis). |
| `reporte.cuil` + `detalle` | Reportes. |
| `recibosospechoso.cuil` | Recibos con alerta de adulteración. |
| `usoia.cuil` | Registro de costo de la IA. |
| `tramite.cuil` | Trámites del afiliado. |
| `notificaciondestinatario.cuil` | A quién le llegó cada notificación. |
| `notificacion.criterio_valores` (JSONB) | Lista de CUIL cuando `criterio = 'cuil'`. |
| `encuesta.criterio_valores` (JSONB) | Ídem, cuando el padrón se fijó por CUIL. |
| `encuestaparticipante.cuil` / `respuestanominal.cuil` | Padrón de cada encuesta / vínculo de las nominales. |
| `suscripcionpush.cuil` | Suscripciones Web Push. |
| `consultaconvenio.cuil` | Consultas al bot del convenio. |
| `trabajador.semaforo_datos→cuil` (JSONB) | Lo que leyó la IA del comprobante de ARCA. |

**Empresa (CUIT)**

| Tabla.columna | Qué es |
|---|---|
| `cuentaempleador.cuit` | La empresa con login (**único**). |
| `empleador.cuit` | Su alta en cada sindicato. |
| `sindicato.cuit` | El CUIT del gremio (en la demo se guardó **con guiones**: `30-11111111-1`). |
| `trabajador.cuit_empleador` | Empleador de cada empadronamiento. |
| `concepto.cuit_empleador` | Conceptos propios de un empleador. |
| `reciboverificado.cuit_empleador` + `detalle→empleador→cuit` | Recibos. |
| `respuestaencuesta.cuit_empleador` | Corte por empleador de la urna (no identifica a la persona). |
| `tramiteempleador.cuit` / `notificacionempleadordestinatario.cuit` | Trámites y notificaciones de la empresa. |
| `notificacion.criterio_valores` / `encuesta.criterio_valores` | Cuando `criterio = 'cuit_empleador'`. |
| `notificacionempleador.criterio_valores` | Cuando `criterio = 'cuit'`. |

**Lo que NO se reescribe** (ver D5): las bitácoras (`logplataforma`,
`tramitelog`, `tramiteempleadorlog`, `eventoencuesta`, `cambioplan`), los
textos libres (respuestas de formularios, notas del chat) y los archivos
guardados como bytes (la imagen de un recibo muestra el número que muestra).

**Lo que NO depende del número**: el hash de la clave (sal aleatoria), el
token del QR de la credencial (aleatorio) y el código de credencial. Sí
depende la **sesión abierta**, que lleva el CUIL firmado: quien esté adentro
en el momento de la conversión queda con una sesión que no encuentra nada
hasta que vuelve a entrar (como mucho 15 minutos).

### 1.2 Cómo nacen los sintéticos

Todos los generadores son deterministas, así que un número sintético **se
reconoce por su regla** sin tener que marcarlo en la base:

| Generador | CUIL | CUIT |
|---|---|---|
| `cargar_lote_sindicato.py` (y `cargar_bancaria.py`) | `20/27` + `65000000 + (sid % 40)·10⁶ + i` (i < 100) + `(i·7) % 10` | `30` + `base + 900000 + j` + `(j·3) % 10` |
| `cargar_lote_uom.py` | `20/27` + `60000000 + i` + `(i·7) % 10` | `30` + `61000000 + j` + `(j·3) % 10` |
| `demo_encuestas.py` | `20/27` + `48000000 + i` + `(i·7) % 10` | — |
| `carga/preparar_datos.py` (pruebas de carga, **está en Pruebas**) | `20/27` + `90000000 + i` (i < 1000) + `i % 10` | — |
| `medir_dashboard.py` (solo local) | `20900000…9` | `3011111…7` |

Además están los **accesos fijos de la demo** (`cargar_demo.py`,
`cargar_bancaria.py`): los admins `20111111110`, `20222222220`,
`20333444550`, los usuarios de área, los trabajadores `20111111119` y
`27222222224`, las empresas `30999888776` y `30111222339`, y los CUIT de los
sindicatos. Son pocos, están escritos a mano en el script, figuran en
`CLAUDE.md` y los usan los tests. Ninguno es válido. Son una categoría
aparte (D3).

Ninguna regla de los generadores calcula el verificador: por azar sale
válido uno de cada once.

### 1.3 La trampa: corregir el último dígito puede juntar a dos personas

Dos números que difieren solo en el verificador se corrigen al **mismo**
número. Pasa en la demo de hoy:

- `20111111110` (admin de la UOM) → `20111111112`
- `20111111119` (Juan Molina, afiliado) → `20111111112`

Y como `usuariosindicato.cuil` vincula al operador con su fila del padrón,
la conversión ciega **fusionaría al admin con el afiliado**: el admin
pasaría a ser "empleado de sindicato" afiliado con los datos de Juan Molina.
`20111111112` además ya aparece como literal válido en los tests. Por eso
**toda colisión frena la conversión de ese número** (D4).

### 1.4 Los tests

94 archivos usan 97 CUIL/CUIT inválidos distintos (~1.040 apariciones).
La mayoría escribe directo en la base y no pasa por ninguna puerta de alta,
así que no se rompen. Se rompen solo los que dan de alta o registran por la
ruta HTTP. `test_enmascarado.py` **no se toca**: mide distancias entre
dígitos y cambiar uno le cambia el resultado. `test_cuil_leer_ajeno.py`
tampoco hace falta tocarlo (escribe directo en la base), y es justamente el
caso real que trae los dos ejemplos de este plan: la sesión de prueba
`27999999999` leyendo el recibo de `20202790411`.

---

## 2. Decisiones propuestas

**D1. Una sola implementación.** Módulo puro `cuit.py` (no importa `db`,
como `fechas.py` o `encuestas.py`): `normalizar`, `digito_verificador`,
`es_valido`, `tipo` (persona/empresa), `corregir` (el número válido más
cercano, regla del §0) y `formatear` (`XX-XXXXXXXX-X`). `enmascarado.dv_valido`
y los `_norm_cuil` duplicados de `main.py` y `validador.py` pasan a usarlo.
Un test recorre los módulos con `ast` y falla si alguien vuelve a calcular el
verificador por su cuenta (el patrón de `test_fechas.py`).

**D2. Se exige donde un número NACE; donde se REFERENCIA uno que ya
existe, se busca tal cual.**

| Exige el verificador (nace un número) | Busca tal cual (referencia) |
|---|---|
| `POST /admin/trabajador` (CUIL y CUIT del empleador) | Los cuatro logins |
| `POST /admin/trabajador/masivo` (por línea: la inválida queda afuera y la pantalla dice cuántas, como el domicilio) | `POST /plataforma/reset-clave` |
| `POST /admin/usuario` | Criterio de notificación por CUIL/CUIT (se valida que exista en el padrón, no el verificador) |
| `POST /admin/empleador` | Filtros y búsquedas del Panel y Reportes |
| `POST /admin/concepto` (CUIT del empleador) | |
| `POST /plataforma/sindicato` y `/editar` | |
| `POST /plataforma/usuario` (primer admin del sindicato) | |
| `POST /plataforma/completar` (CUIL del usuario de plataforma) | |
| `POST /trabajador/registro` y `/empresa/registro` (ver decisión abierta 4) | |

**El login nunca valida el verificador**: si lo hiciera, ningún sintético
podría entrar. Lo que lee la IA (`/api/leer`, `/api/aportes`,
`/admin/aprender`) tampoco se bloquea por el verificador en esta etapa (§3,
etapa 6).

**D3. Tres orígenes, y en esta etapa se convierte uno.** Cada número
inválido se clasifica en:

- `lote` — coincide con la regla de un generador (§1.2). **No se toca.**
- `demo` — está en la lista fija de `cargar_demo.py` / `cargar_bancaria.py`.
  El clasificador **importa esas listas de los scripts**, no las copia, para
  que no se desalineen. **Decisión abierta 1.**
- `manual` — todo lo demás. **Se convierte.**

**D4. El número nuevo conserva los diez primeros dígitos** (y con ellos el
DNI, que la app deriva del CUIL, y el tipo persona/empresa) y lleva el
verificador correcto; si da 10, cambia el prefijo a 23/33. **Si el número
nuevo ya existe en cualquier tabla, o lo reclaman dos números viejos, no se
elige solo**: sale marcado `COLISION` en la planilla y una persona decide
entre **fusionar** (es la misma persona con un dígito mal tipeado) o
**renumerar** (se propone el siguiente DNI libre con verificador válido).

**D5. Se reescribe la identidad y sus copias, no la historia.** Columnas y
JSON de la tabla del §1.1 sí; bitácoras, textos libres y archivos no. La
traza queda en una tabla nueva **`CambioIdentificador`** (número anterior,
nuevo, tipo, origen, entorno, cuándo y quién): así una entrada vieja de la
bitácora con el número anterior se puede seguir hasta la persona. Se
guardan hechos, no derivados.

**D6. La conversión es un script, no una migración de Alembic.** Una
migración corre sola en el Pre-Deploy y sin mirar; esta conversión necesita
que alguien apruebe número por número. Alembic solo crea la tabla
`CambioIdentificador`. El script sigue el patrón de
`cargar_encuesta_sintetica.py`: **sin `--si` no escribe nada**.

**D7. Mensaje de error propio**, `E-IDENT-01`: "El CUIL no es válido:
revisá los 11 números" (y su par para CUIT). No es un error de lectura, así
que no dice "probá con otra foto" (lo verifica el test del catálogo de
`errores.py`). El navegador valida lo mismo al salir del campo, como
cortesía; el servidor decide.

---

## 3. Etapas

### Etapa 1 — Herramienta y diagnóstico (no escribe nada)

- `cuit.py` + `test_cuit.py` (algoritmo, casos de AFIP, prefijos, el caso
  `r = 10`, normalización con guiones y espacios).
- `regularizar_cuit.py diagnostico`: recorre todas las columnas del §1.1 en
  la base de `DATABASE_URL` y deja
  - un **resumen en pantalla**: inválidos por tabla y por origen
    (`manual` / `demo` / `lote`);
  - una **planilla** `regularizacion_cuit_<entorno>.csv` con una fila por
    número inválido: anterior, nuevo propuesto, persona/empresa, origen,
    nombre o razón social para reconocerlo, en qué tablas aparece y cuántas
    filas, `COLISION` si la hay, y una columna `convertir` que llega en `si`
    solo para los `manual` sin colisión.
  - La planilla **no se versiona** (`.gitignore`): aunque sean números de
    prueba, lleva nombres.
- Se corre contra **local, Pruebas y Demo**.
- **Salida de la etapa:** SDN revisó las tres planillas y marcó qué se
  convierte.

### Etapa 2 — Conversión de los números cargados a mano

- Migración: tabla `CambioIdentificador`.
- `regularizar_cuit.py aplicar --planilla X.csv [--si]`:
  1. Vuelve a verificar cada fila contra la base: el número anterior sigue
     estando, el nuevo sigue libre. Si algo cambió desde el diagnóstico,
     frena entero.
  2. Backup previo de la base (`pg_dump` con `pg_cliente.py`, como
     `promover_demo.py`).
  3. **Una transacción**: todas las columnas y JSON del §1.1 (los JSON
     comparando normalizado, porque la IA pudo guardar `27-99999999-9`; el
     dato se reescribe en el mismo formato que tenía) + una fila en
     `CambioIdentificador` por número.
  4. Corre el diagnóstico de nuevo y muestra el antes y el después.
  5. Imprime la lista de personas afectadas con su número nuevo: **tienen
     que enterarse**, porque entran con él.
- Orden: local → Pruebas → Demo, fuera del horario de una presentación.

### Etapa 3 — Accesos fijos de la demo (si se decide convertirlos)

- Números nuevos en `cargar_demo.py` y `cargar_bancaria.py`, elegidos a mano
  para que no colisionen entre sí (el caso del §1.3).
- La misma herramienta los convierte en las bases de Pruebas y Demo
  (origen `demo`).
- Mismo commit: accesos de `CLAUDE.md`, `e2e/`, tests que los usan,
  `README` y la documentación que los nombre.
- Tiene que estar hecho **antes** de la etapa 4 si el registro exige el
  verificador: si no, el registro de las empresas de la demo
  (`30999888776`, `30111222339`) deja de funcionar.

### Etapa 4 — Exigir el verificador en las puertas

- Las puertas de la columna izquierda de D2, con `cuit.es_valido` y
  `E-IDENT-01`.
- Tests nuevos: `test_cuit_puertas.py` (cada puerta rechaza un inválido y
  acepta uno válido; **un sintético sigue pudiendo entrar** por el login).
- Tests existentes: se corrigen **solo** los que dan de alta por HTTP, con
  números elegidos para no colisionar. Cada `test_*.py` por separado, como
  siempre.
- Versión: Admin, Plataforma y Trabajador suben el minor (funcionalidad
  nueva en las tres).

### Etapa 5 — Sintéticos (opcional, "si es fácil")

- Los generadores pasan a calcular el verificador; si da 10, **se salta al
  DNI siguiente** en vez de cambiar el prefijo, para no romper la regla de
  los lotes "clave = 5 primeros dígitos del CUIL".
- Los lotes ya cargados se convierten con la misma herramienta (origen
  `lote`). Hay que mantener `--limpiar`, que encuentra el lote por su lista
  de CUIL.
- Estimación: media. Solo vale la pena si los sintéticos se muestran a un
  sindicato o si molestan en la etapa 6.

### Etapa 6 — Lo que habilita (después)

- `enmascarado.pertenece` vuelve a exigir el verificador, que es más firme
  que la distancia de 3 dígitos (punto 3 del pendiente de `BACKLOG.md`).
- Un CUIL leído por la IA con verificador inválido se marca como lectura
  dudosa en vez de compararse.
- **H-0017, alta de usuarios** (la siguiente medida de la serie).

---

## 4. Riesgos

| Riesgo | Cómo se cubre |
|---|---|
| Fusionar dos personas por una colisión | D4: toda colisión frena y decide una persona. |
| Cortar una relación (una tabla con el número viejo) | Sin claves foráneas, la única defensa es una transacción sobre la lista completa del §1.1 y el diagnóstico de después en cero. Un test compara esa lista contra los modelos de `db.py` y falla si aparece una columna `cuil`/`cuit` nueva que la herramienta no conoce. |
| La persona no sabe con qué número entrar | Lista impresa al final de la etapa 2; para la demo, `CLAUDE.md`. |
| Sesiones abiertas durante la conversión | Duran como mucho 15 minutos; se corre en horario tranquilo. |
| Romper el anonimato de las encuestas | `respuestaencuesta` no tiene CUIL; solo se reescribe su `cuit_empleador`. No se agrega ningún vínculo. |
| Tiempo y bloqueos | Los `UPDATE` van por columnas indexadas y afectan pocas filas; el más pesado es el JSON de `reciboverificado`, filtrado por `cuil`. Segundos. |

---

## 5. Cierre

- El diagnóstico da **cero inválidos de origen `manual`** en local, Pruebas
  y Demo.
- Las puertas de D2 exigen el verificador; la suite pasa archivo por archivo.
- XSK: se abre un hallazgo para la validación de entrada del CUIL/CUIT
  (eje IDS) y se cierra con esta serie.
- `CLAUDE.md` (decisión nueva: "el CUIL/CUIT se valida con módulo 11 donde
  nace"), `HISTORIAL.md`, `BITACORA.md`, y el pendiente de `BACKLOG.md`
  marcado.

---

## 6. Decisiones abiertas (para SDN)

1. **Accesos fijos de la demo** (`20111111119`, `30999888776`, los admins…):
   ¿se tratan como manuales y se convierten (etapa 3) o como sintéticos y
   quedan? *Propuesta:* convertirlos en la etapa 3. Son pocos, son los que
   ve un sindicato en una presentación, y si el registro exige el
   verificador el registro de empresa de la demo deja de andar.
2. **Colisiones:** ¿la propuesta por defecto es renumerar (siguiente DNI
   libre)? *Propuesta:* sí, y fusionar solo si una persona confirma que es
   la misma.
3. **Bitácoras:** ¿se confirma que no se reescriben y que la traza queda en
   `CambioIdentificador`?
4. **Registro del afiliado y de la empresa:** el número ya está en el
   padrón, así que técnicamente es una referencia. ¿Se exige igual el
   verificador? *Propuesta:* sí. Es la puerta de H-0017, y un número que no
   pasa el verificador no es de nadie.
5. **Prefijos 25 y 26:** `enmascarado.PREFIJOS_PERSONA` los acepta junto a
   20, 23, 24 y 27. ¿Se mantienen?
