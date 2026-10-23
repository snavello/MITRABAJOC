# Inventario del panel del sindicato (escritorio) — 5 pantallas

Relevado del código real (versión Admin **0.65.01**) para el rediseño. Fuentes:
`templates/admin_portada.html`, `templates/admin.html`, `templates/_encabezado.html`,
`templates/_fondo_interior.html`, `templates/_entorno.html`, `templates/clave_temporal.html`,
`static/cuit.js`, `geo.py`, `db.py`, `dashboard.py`, `main.py` (rutas `/admin/inicio`, `/admin`,
`/admin/tramite/{id}`, `/admin/reportes/*`).

Convenciones:
- Texto entre comillas «…» = literal de la plantilla (copiar tal cual, con sus tildes y guiones dobles `--`).
- **[JS]** = lo arma el JavaScript embebido en el navegador (no está en el HTML del servidor).
- **[OPC: …]** = depende de un módulo contratado, un permiso o un rol; si no se cumple, no se dibuja.
- `{{ … }}` = dato que pone el servidor.
- Datos de ejemplo: operadora **Laura Méndez · Prensa**, sindicato **Unión Obrera Metalúrgica**,
  seccionales **Sede Central, Avellaneda, Quilmes, Lanús**, afiliados **Martín Sosa 20-31456789-8**
  y **Carla Benítez 27-38912345-0**, empresa **Metalúrgica del Sur SA** (CUIT 30-71234567-9).
  Ojo: el panel guarda y muestra el CUIL **sin guiones** (`20314567898`) en tablas y campos.

---

## E0 · Cromo común (encabezado, tira de pestañas, operador, Inicio/Salir)

### 0.1 Encabezado (`_encabezado.html`, idéntico en E1–E5)
Una sola barra oscura, de una línea. No hay cinta de rol ni nombre de pantalla.
1. **Izquierda:** logo del sindicato (imagen `/logo/{id}?v=…`, alt = «Unión Obrera Metalúrgica»), 62 px de alto, ancho libre.
   - Si el sindicato no tiene logo: el nombre en texto «Unión Obrera Metalúrgica» (`.marca-nombre`).
2. **Derecha:** logo de Colm3na (versión fondo oscuro, alt «Colm3na»), 24 px de alto.
3. Opcionales del parcial que en estas 5 pantallas NO se usan: hueco de fecha (`enc_fecha`, solo Panel Sindical), link «Volver» con chevrón (`enc_volver`, solo pantallas sin tira; sí aparece en la pantalla de **Clave temporal**, ver E2).
4. En `/admin` (E2–E5) la barra lleva además el cromo "Hilo": filo de 5 px en color **acento** a la izquierda, degradé base→primario y grano al 8 %. Es pegajosa (sticky) junto con la tira de pestañas.
5. En la portada (E1) el encabezado NO es fijo.

### 0.2 Distintivo de entorno (`_entorno.html`)
- Solo en local y Pruebas (nunca en demo/prod). Pastilla fija abajo a la izquierda, ámbar `#ffb020`, monoespaciada mayúscula: «PRUEBAS · v0.65.01». No captura clics.

### 0.3 Tira de pestañas (solo en `/admin`, debajo del encabezado; NO existe en la portada)
Pastillas de texto en una fila deslizable horizontal, sobre fondo `color_base`; condensada 13 px mayúscula; **sin íconos** (los SVG están en el HTML pero se ocultan por CSS); la activa en **blanco con texto color base**. Al tocar una, la URL queda con `#ancla`.
Son **16** entradas posibles (no 14: hoy se suman Encuestas, Convenio y Listas; «Panel Sindical» es un link a otra página, las otras 15 abren un panel), en este orden:

| # | Texto literal | Ancla / destino | Condición [OPC] |
|---|---|---|---|
| 1 | «Panel Sindical» | link a `/admin/dashboard` (otra página) | módulo `dashboard` + permiso `dashboard` |
| 2 | «Reportes» | `#reportes` | módulo `recibos` + permiso `reportes` |
| 3 | «Reglas» | `#formulas` | módulo `recibos` + permiso `formulas` |
| 4 | «Conceptos» | `#conceptos` | módulo `recibos` + permiso `conceptos` |
| 5 | «Trabajadores» | `#trabajadores` | permiso `trabajadores` (sin módulo: siempre contratado) |
| 6 | «Aprendizaje» | `#aprendizaje` | módulo `recibos` + permiso `aprendizaje` |
| 7 | «Noticias» | `#noticias` | módulo `noticias` + permiso `noticias` |
| 8 | «Beneficios» | `#beneficios` | módulo `beneficios` + permiso `beneficios` |
| 9 | «Notificaciones» | `#notificaciones` | módulo `notificaciones` + permiso `notificaciones` |
| 10 | «Encuestas» | `#encuestas` | módulo `encuestas` + permiso `encuestas` o `encuestas_resultados` |
| 11 | «Trámites» + globo rojo con número (p. ej. **3**) | `#tramites` | módulo `tramites` + permiso `tramites_recibidos` o `tramites_formularios`. Globo solo si hay trámites en estado «Iniciado» de su alcance; se actualiza solo cada 30 s **[JS]** |
| 12 | «Empleadores» + globo rojo (trámites de empresa nuevos) | `#empleadores` | módulo `empleadores` + alguno de `emp_empresas`, `emp_notificaciones`, `emp_tramites_recibidos`, `emp_tramites_formularios` |
| 13 | «Convenio» | `#convenio` | módulo `convenio` + permiso `convenio` |
| 14 | «Seccionales» | `#seccionales` | permiso `seccionales` |
| 15 | «Listas» | `#listas` | permiso `listas` |
| 16 | «Áreas y Usuarios» | `#administradores` | rol Super Admin **o** Admin de Seccional (`administra_areas`) |

- Sin `#ancla` en la URL **ninguna pestaña queda activa** y la página muestra solo el cromo (estado a tener en cuenta).
- Un usuario de área (p. ej. Prensa) ve solo las pestañas de su perfil: Laura Méndez · Prensa típicamente tendría «Noticias», «Beneficios», «Notificaciones», «Encuestas».

### 0.4 Operador logueado — DÓNDE se ve hoy
- **En `/admin` (E2–E5) no se muestra en ningún lado** quién está logueado (ni nombre, ni rol, ni seccional). Solo el `<title>` dice «Panel de administración — Unión Obrera Metalúrgica».
- **En la portada (E1)** sí: saludo + bajada de rol + círculo de perfil que abre el modal «Tu cuenta» (ver E1).

### 0.5 Botones «Inicio» y «Salir» — DÓNDE están hoy
- **Portada `/admin/inicio`:** un único botón flotante redondo **Salir** (ícono X en color acento, 42 px) fijo **abajo a la derecha** (bottom 84 px, right 18 px), `title`/`aria-label` «Salir» → `/admin/salir`. **No hay botón Inicio** (ya estás en el inicio). El acceso a «Cambiar de sindicato» es un link de texto bajo el saludo (ver E1).
- **Panel `/admin` (E2–E5):** tres botones flotantes redondos de 44 px, fondo `color_base`, fijos **abajo a la derecha**, alineados en fila (bottom 20 px):
  - **Salir** (X blanca) — right 20 px, `title` «Salir» → `/admin/salir`.
  - **Inicio** (casita blanca) — right 74 px, `title` «Inicio» → `/admin/inicio`.
  - **Ayuda** (letra «H») — right 128 px, `title` «Ayuda». **Solo aparece** en Conceptos, Reglas y Trámites › Crear/editar formularios **[JS]**. En E2–E5 no aparece salvo en Trámites › formularios.
- **Pie de `/admin`:** botón de texto chiquito centrado, gris al 45 %, «Acerca de» → modal con «Acerca de» / «Versión» `0.65.01` / «Fecha» `2026-10-23 14:12` / «Entorno» `pruebas` (si hay) / botón «Cerrar».
- **Aviso global** arriba del contenido de `/admin` si la URL trae `?error=guardado`: «No se pudo guardar -- probá de nuevo en un momento. Si se repite, puede ser un problema pasajero de conexión.» + (si hay `ref`) «Código E-INTERNO-00 · ref 7f3a9c21».

### 0.6 Fondo de las pantallas interiores (`/admin`)
`<body class="mesa franja">`: mesa gris frío + retícula de colmena al 6 % + dos halos del acento y el primario del sindicato + franja de marca que baja del encabezado (apagado ≤760 px). El primer título de cada panel (`.titulo-pagina`, condensada 31 px mayúscula) va **en blanco** sobre la franja. Contenedor `.wrap` de 1000 px máx.

---

## E1 · Portada del panel `/admin/inicio` (`admin_portada.html`)

### 1. Estados
- **Estado a dibujar (el más completo):** Super Admin de Sede Central con todos los módulos (13 accesos + hero del Panel Sindical), globo en Trámites (3) y en Empleadores (1), con foto de perfil, que trabaja en dos sindicatos (se ve «Cambiar de sindicato»).
- **Variante de tema:** fondo **oscuro** (degradé radial primario→base, grano oscuro) por defecto; **claro** (papel) si el sindicato tiene `admin_portada_clara`. El saludo cambia de color (blanco / tinta).
- **Usuario de área (Laura Méndez · Prensa):** sin hero (si no tiene permiso `dashboard`), solo las 4–5 tarjetas de su perfil, sin «Áreas y Usuarios».
- **Sin foto:** el círculo muestra el ícono genérico de persona.
- **Modales:** «Tu cuenta» y «Acerca de».

### 2. Elementos obligatorios (en orden de aparición)
1. Encabezado común (E0.1): logo UOM izquierda, Colm3na derecha.
2. Botón flotante **Salir** (X) abajo a la derecha (E0.5).
3. Ambiente decorativo de fondo (`pt-ambiente`): dos manchas de luz (blobs) + retícula; sin contenido.
4. **Saludo:** «Hola, » + nombre en color acento → «Hola, *Laura*» (primer nombre del usuario; si no tiene nombre, «Admin»). Condensada 30 px.
5. **Bajada del saludo:** «{seccional} · {rol}» → «Sede Central · Super Admin». Valores posibles del rol: «Super Admin», «Admin de Seccional», «Usuario de área». Sin seccional: solo el rol.
6. **Link** «Cambiar de sindicato» (subrayado, bajo la bajada) → `/admin/cambiar-sindicato`. [OPC: solo si la persona trabaja en el panel de más de un sindicato.]
7. **Círculo de perfil** (41 px, fondo acento) a la derecha del saludo, `aria-label`/`title` «Tu cuenta». Adentro: foto de la persona (sale de su cuenta de afiliado por CUIL) o ícono de persona.
8. **Hero «Panel Sindical»** (tarjeta grande, `pt-hero pt-hero-chico`) → `/admin/dashboard`. [OPC: módulo `dashboard` + permiso `dashboard`.]
   - Kicker: «Lo primero»
   - Título: «Panel Sindical» + etiqueta «NUEVO» (pastilla acento, 9 px)
   - Texto: «Indicadores y actividad en vivo: recibos, trámites, semáforo por empresa y el mapa de seccionales.»
   - Llamado: «Abrir el panel» + flecha
   - Ícono grande decorativo (cuadrícula de 4 rectángulos).
   - Sin cifras (a propósito).
9. **Grilla de accesos** (`pt-filas pt-tres`: 3 columnas desde 1040 px). Cada fila = pastilla con ícono + título + bajada + flecha. En orden:

| # | Título | Bajada literal | Destino | Condición [OPC] |
|---|---|---|---|---|
| 1 | «Reportes» | «Recibos verificados, enviados y anónimos» | `/admin#reportes` | `recibos` + `reportes` |
| 2 | «Reglas» | «Cálculo de cada aporte» | `/admin#formulas` | `recibos` + `formulas` |
| 3 | «Conceptos» | «Catálogo del recibo» | `/admin#conceptos` | `recibos` + `conceptos` |
| 4 | «Trabajadores» | «Alta, baja y datos de afiliados» | `/admin#trabajadores` | permiso `trabajadores` |
| 5 | «Aprendizaje» | «Corregir sugerencias de la IA» | `/admin#aprendizaje` | `recibos` + `aprendizaje` |
| 6 | «Noticias» | «Novedades para los afiliados» | `/admin#noticias` | `noticias` + `noticias` |
| 7 | «Beneficios» | «Descuentos para afiliados» | `/admin#beneficios` | `beneficios` + `beneficios` |
| 8 | «Notificaciones» | «Mensajes dirigidos a trabajadores» | `/admin#notificaciones` | `notificaciones` + `notificaciones` |
| 9 | «Encuestas» | «Preguntar y leer los resultados» | `/admin#encuestas` | `encuestas` + (`encuestas` o `encuestas_resultados`) |
| 10 | «Trámites» + **globo rojo** «3» arriba a la derecha de la tarjeta | «Formularios y seguimiento» | `/admin#tramites` | `tramites` + (`tramites_recibidos` o `tramites_formularios`); globo solo si hay iniciados (número calculado al cargar, sin refresco en vivo) |
| 11 | «Empleadores» + **globo rojo** «1» | «Empresas, notificaciones y trámites» | `/admin#empleadores` | `empleadores` + algún permiso `emp_*` |
| 12 | «Seccionales» | «Sedes y delegaciones» | `/admin#seccionales` | permiso `seccionales` |
| 13 | «Áreas y Usuarios» | «Quién entra y qué puede tocar» | `/admin#administradores` | **solo Super Admin** (el Admin de Seccional tiene la pestaña en `/admin` pero NO la tarjeta acá — inconsistencia actual) |

   Íconos (SVG de línea): reportes = barras en cuadro; reglas = signo %; conceptos = lista con viñetas; trabajadores = dos personas; aprendizaje = lamparita; noticias = diario; beneficios = etiqueta de precio; notificaciones = campana; encuestas = lista con tilde; trámites = hoja con tilde; empleadores = edificio/valija; seccionales = pin de mapa; áreas = escudo con persona.
   **No hay** tarjetas de «Convenio» ni «Listas» en la portada (sí están en la tira de `/admin`).
10. Botón de texto «Acerca de» centrado al pie (11 px, opacidad 50 %).

**Modal «Tu cuenta»** (lectura, centrado, X de cierre `aria-label` «Cerrar»). Título «Tu cuenta». Filas clave/valor:
- «Nombre» → «Laura Méndez» (o «—»)
- «Usuario» → «27311223348» (el usuario es el CUIL)
- «CUIL» → «27311223348» (monoespaciada) [OPC: solo si tiene CUIL]
- «Rol» → «Usuario de área»
- «Seccional» → «Sede Central» (o «Todas» si no tiene)
- «Área» → «Prensa» [OPC: solo usuarios de área]
- «Sindicato» → «Unión Obrera Metalúrgica»
- (No hay botón de cambiar clave: es de plataforma.)

**Modal «Acerca de»**: título «Acerca de»; «Versión» `0.65.01`; «Fecha» `2026-10-23 14:12`; «Entorno» `pruebas` [OPC: solo con entorno].

### 3. Qué depende de módulo/permiso/rol
Hero y cada tarjeta según la tabla. «Cambiar de sindicato» solo multi-sindicato. Globos solo con trámites iniciados. Foto solo si la persona está en algún padrón con foto. Tema claro/oscuro por sindicato.

---

## E2 · Trabajadores (padrón) — `/admin#trabajadores`

[OPC entero: permiso `trabajadores`. No depende de módulo.]

### 1. Estados
- **Estado a dibujar:** sub-pestaña «Listado» con 3 filas (una de cada caso: registrada nivel 3 con credencial y empleado del sindicato; sin registrar; dada de baja), filtros vacíos, contador «3 resultados».
- **Sub-pestañas** (pastillas redondeadas, condensada mayúscula; activa en color `color_secundario`): «Listado» (activa por defecto) · «Alta manual» · «Alta masiva».
- **Alta manual — modo edición:** el mismo formulario se reutiliza al tocar «Editar» en una fila (**no hay modal de edición**): se cambia a la sub-pestaña «Alta manual», el CUIL queda **fijo** (fondo gris `#eef0f3`, cursor prohibido, tooltip «El CUIL no se cambia desde una edición: si está mal, pedile a la plataforma que lo corrija.»), el botón pasa a «Guardar cambios» y aparece «Cancelar edición»; si el domicilio ya tenía coordenadas, el mapa se abre solo (sin lista de candidatos) **[JS]**.
- **Vacío:** fila única «No hay trabajadores cargados. Usá "Alta manual" o "Alta masiva".»
- **Avisos de resultado/error** arriba de las sub-pestañas (ver lista).
- **Pantalla aparte «Clave temporal»** después de «Restablecer clave».
- **Acotado** (Admin de Seccional / área de una seccional): la lista ya viene recortada a su seccional; selector de seccional sin «Sin asignar».

### 2. Elementos obligatorios (en orden)
1. Título (`titulo-pagina`, blanco sobre la franja): «Trabajadores ({n} activos)» → «Trabajadores (2 activos)».
2. Bajada 1: «Los trabajadores cargados acá pueden registrarse en la app con su CUIL. Podés darlos de alta de a uno o pegar una lista.»
3. Bajada 2: «El **nombre, el domicilio y el contacto** son datos de la persona: se comparten con su perfil en la app y con los otros sindicatos donde esté afiliada, así que lo que corrijas acá lo ve también el afiliado. La **seccional**, la **credencial** y el **CUIT del empleador** son de este sindicato.»
4. **Avisos posibles** (uno a la vez; rojo `#f8e5e2`/`#b23a2e` salvo los marcados):
   - `err=domicilio`: «No se guardó: falta {campos}. El sindicato necesita al menos la provincia y la localidad de cada afiliado para agruparlo por zona.» (p. ej. «falta la localidad»)
   - `err=datos`: «No se guardó: revisá el CUIL (11 dígitos) y el nombre.»
   - `err=cuil`: «No se guardó: el CUIL no es válido -- revisá los 11 números.» + «Código E-IDENT-01»
   - `err=cuilfijo`: «No se guardó: el CUIL no se cambia desde una edición, porque es la identidad de la persona en todo el sistema (su cuenta, sus recibos, sus trámites). Si está mal, pedile a la plataforma que lo corrija.» + «Código E-IDENT-03»
   - `err=fecha`: «No se guardó: una de las fechas no se entiende. Usá el formato AAAA-MM-DD (o DD/MM/AAAA).»
   - `err=cuitempleador`: «No se guardó: el CUIT del empleador no es válido -- revisá los 11 números.» + «Código E-IDENT-02»
   - `err=sincuenta`: «Esa persona todavía no creó su cuenta en la app: no hay nada que confirmar ni clave que restablecer.»
   - `err=cuentaajena`: «Esta persona creó su cuenta antes de que la cargaras en tu padrón: por seguridad, solo plataforma puede restablecerle la clave o confirmar su identidad.»
   - `aviso=datosajenos` (neutro): «Se guardó el empadronamiento, pero no el nombre, el domicilio, el teléfono ni los mails: esta persona creó su cuenta antes de que la cargaras en tu padrón y esos datos son suyos.»
   - `ok=identidad` (verde): «Identidad confirmada: la cuenta pasó a nivel 4.»
   - `datosajenos=N` tras carga masiva (neutro): «2 líneas de la lista corresponden a personas que ya habían creado su cuenta antes de que las cargaras en tu padrón: se las empadronó, pero no se tocaron su nombre, domicilio, teléfono ni mails.» (singular/plural)
   - **Resultado de carga masiva** (verde, `altas=N`): «48 trabajadores cargados de la lista.» y, debajo, líneas opcionales:
     - «Quedaron afuera 3 líneas: les falta el CUIL, el nombre, la localidad o la provincia, el CUIL ya estaba cargado, o traen una fecha que no se entiende. Por ejemplo: `27389123450, Carla Benítez`»
     - «De esas, 1 traían una seccional que no es la tuya: un administrador de seccional carga solo en la suya.»
     - «5 afiliados que ya estaban en el padrón recibieron el mail del padrón de su línea.»
     - «4 afiliados que ya estaban en el padrón recibieron la fecha de afiliación de su línea.»
     - «Quedaron afuera 2 líneas porque el CUIL no es válido (revisá los 11 números): `20314567890` Código E-IDENT-01»
5. Sub-pestañas: «Listado» · «Alta manual» · «Alta masiva».

#### 2.a Sub-pestaña «Listado»
6. Barra de filtros (inputs redondeados):
   - input texto, placeholder «Buscar por CUIL» (filtra por dígitos, en vivo) **[JS]**
   - input texto, placeholder «Buscar por nombre» (sin tildes ni mayúsculas, en vivo) **[JS]**
   - casilla «Declarados sin recibo», con tooltip «Cuentas cuyo único respaldo es un mail que la propia persona declaró: ni el sindicato lo cargó ni subió un recibo propio.»
   - botón chico «Limpiar»
   - contador «3 resultados» / «1 resultado» (monoespaciada) **[JS]**
   - (El filtro es del lado del navegador sobre las filas ya cargadas: no hay paginado.)
7. **Tabla** (filas alternadas en zebra **[JS]**; las de baja al 50 % de opacidad). Columnas: «CUIL» · «Nombre» · «Ubicación» · «Seccional» · «CUIT empleador» · «Estado» · «Nivel» · «Credencial» · (acciones, sin rótulo).

   | CUIL | Nombre | Ubicación | Seccional | CUIT empleador | Estado | Nivel | Credencial | Acciones |
   |---|---|---|---|---|---|---|---|---|
   | `20314567898` | Martín Sosa | Avellaneda, Buenos Aires · ● «Dirección exacta» | Avellaneda | 30712345679 | ✔ «registrado» · «empleado del sindicato» · «afiliado desde 2019-03-01» | «3 · recibo» | `UNIONK7P2QX9A` / «vence 2027-03-31» | Editar · Regenerar credencial · Confirmé su identidad · Restablecer clave · Baja |
   | `27389123450` | Carla Benítez | Quilmes, Buenos Aires · ● «Sin ubicar» | Quilmes | — | «sin registrar» | «—» | «sin generar» | Editar · Generar credencial · Dar usuario del panel · Baja |
   | `20287654326` | Jorge Ledesma | Lanús, Buenos Aires · ● «Ubicación aproximada» | Lanús | 30712345679 | «baja» (gris) | «2 · mail padrón» | «sin generar» | Editar · Generar credencial · Reactivar |

   Detalle de cada celda:
   - **CUIL:** monoespaciado, sin guiones.
   - **Nombre:** o «—».
   - **Ubicación:** «{localidad}, {provincia}» en gris + debajo (si hay localidad) punto de color + etiqueta de precisión. Valores: «Dirección exacta», «Ubicación aproximada», «Ubicada a mano», «Sin ubicar».
   - **Seccional:** nombre o «—».
   - **CUIT empleador:** o «—».
   - **Estado** (puede apilar hasta 3 cosas): pastilla gris «baja» / pastilla verde «registrado» / texto gris «sin registrar»; + pastilla ámbar «empleado del sindicato» (tooltip «Además opera el panel del sindicato»; solo lectura); + «afiliado desde 2019-03-01» (11 px) si hay fecha de afiliación.
   - **Nivel** (pastillas con tooltip):
     - «—» (sin cuenta) · «—» con tooltip «cuenta creada antes de este empadronamiento» (cuenta que este sindicato no avala)
     - «1 · CUIL» ámbar — «Solo acreditó que su CUIL está en el padrón (el CUIL es un dato público).»
     - «2 · mail padrón» verde — «Confirmó el mail que el sindicato tiene cargado en el padrón.»
     - «2 · mail declarado» ámbar — «Confirmó un mail que declaró ella misma al registrarse: nadie del sindicato lo avala y todavía no verificó ningún recibo.»
     - «3 · recibo» verde — «Subió un recibo propio y la IA leyó su CUIL.»
     - «4 · confirmado» verde — «Una persona del sindicato confirmó su identidad en persona.»
   - **Credencial:** código monoespaciado (5 letras del sindicato + 8 alfanuméricos, p. ej. `UNIONK7P2QX9A`) + «vence 2027-03-31» si hay vigencia; o «sin generar».
   - **Acciones** (botones chicos, a la derecha, sin salto de línea):
     1. «Editar» — siempre.
     2. «Generar credencial» / «Regenerar credencial» — siempre. Confirmación: «¿Generar el código de credencial?» / «¿Regenerar el código de credencial? El anterior deja de ser válido.»
     3. «Confirmé su identidad» — [OPC: tiene cuenta + este sindicato responde por ella + fila dentro del alcance + nivel < 4]. Confirmación: «¿Confirmás que verificaste en persona la identidad de esta persona? La cuenta pasa a nivel 4.»
     4. «Restablecer clave» — [OPC: tiene cuenta + responde + dentro del alcance]. Confirmación: «¿Restablecer la clave de esta persona? La clave actual deja de servir y se muestra una clave temporal UNA sola vez. La clave es una sola por persona: vale para todos los sindicatos donde esté empadronada.»
     5. «Dar usuario del panel» (link con aspecto de botón) — [OPC: quien mira administra usuarios (Super Admin o Admin de Seccional) + afiliado activo + no es ya empleado del sindicato + dentro del alcance]. Lleva a Áreas y Usuarios › Usuarios con CUIL, nombre y seccional precargados.
     6. «Baja» (rojo) si está activo — confirmación «¿Dar de baja a este trabajador? Se puede reactivar después.» / «Reactivar» si está de baja.
   - Fila vacía: «No hay trabajadores cargados. Usá "Alta manual" o "Alta masiva".»

#### 2.b Sub-pestaña «Alta manual» (16 campos visibles + 3 ocultos)
Grilla de 2 columnas. Rótulo + campo; «(opcional)» en gris al lado del rótulo donde se indica.
1. «CUIL *» — texto, obligatorio, placeholder «20123456786». Valida módulo 11 en el navegador: borde rojo + aviso «El CUIL no es válido: revisá los 11 números» **[JS]**.
2. «Nombre *» — texto, obligatorio.
3. «Calle (opcional)»
4. «Número (opcional)»
5. «Piso / Depto (opcional)»
6. «Localidad *» — texto con sugerencias en vivo (Georef, desde 2 letras) **[JS]**, obligatorio.
7. «Provincia *» — select obligatorio: «—» + las 24: Ciudad Autónoma de Buenos Aires, Buenos Aires, Catamarca, Chaco, Chubut, Córdoba, Corrientes, Entre Ríos, Formosa, Jujuy, La Pampa, La Rioja, Mendoza, Misiones, Neuquén, Río Negro, Salta, San Juan, San Luis, Santa Cruz, Santa Fe, Santiago del Estero, Tierra del Fuego, Tucumán.
8. «Código postal (opcional)» (se autocompleta al elegir un candidato del mapa **[JS]**)
9. «Teléfono (opcional)»
10. «Mail (opcional)» — email.
11. «Vigencia de credencial» — fecha.
12. «Fecha de afiliación (opcional)» — fecha (es del sindicato).
13. «Fecha de nacimiento (opcional)» — fecha (es de la persona).
14. «Seccional» — select: «Sin asignar» [OPC: solo alcance total] + Sede Central, Avellaneda, Quilmes, Lanús (solo las visibles para quien mira).
15. «CUIT del empleador» — texto, placeholder «Para notificar por empresa», valida CUIT (aviso «El CUIT no es válido: revisá los 11 números») **[JS]**.
16. Ocultos: latitud, longitud, precisión (arranca «sin_geo»).
17. Botón secundario «Ubicar el domicilio en el mapa» (mientras busca: «Buscando…», deshabilitado) + al lado pastilla de estado con punto de color: «Sin ubicar» / «Dirección exacta» / «Ubicación aproximada» / «Ubicada a mano» **[JS]**.
18. **Caja del mapa** (oculta hasta buscar) **[JS]**:
    - Recuadro de ayuda coloreado según precisión: «Buscando la dirección…» → «Encontramos la dirección exacta. Si el globo no está en la puerta, arrastralo.» / «No encontramos la altura exacta: arrastrá el globo hasta la puerta.» / «Ubicación puesta a mano. Arrastrá el globo si querés corregirla.» / «Todavía sin ubicar.» / error: «No encontramos ese domicilio. Se puede guardar sin ubicar.» / «Hiciste muchas búsquedas seguidas. Probá en un rato. Se puede guardar sin ubicar.» / «No pudimos buscar. Se puede guardar sin ubicar.»
    - Al abrir uno ya guardado (modo edición): «Domicilio ubicado en la dirección exacta. Arrastrá el globo para corregirlo.» / «Ubicación aproximada: el globo no está en la puerta. Arrastralo para ajustarlo.» / «Ubicación puesta a mano. Arrastrá el globo para corregirla.»
    - Mapa Leaflet (teselas OSM) con globo arrastrable + columna a la derecha de **candidatos** (botones): «**Dirección exacta**» o «**Aproximada**» + la dirección, p. ej. «Av. Mitre 1250, Avellaneda, Buenos Aires». El primero queda elegido. En edición, sin columna.
    - Nota: «Arrastrá el globo si el domicilio no quedó bien ubicado.»
19. Botones: «Agregar trabajador» (principal, acento) / en edición «Guardar cambios» + «Cancelar edición» (secundario).

#### 2.c Sub-pestaña «Alta masiva»
1. «Pegá una línea por trabajador, con los campos separados por coma, en este orden:»
2. Caja monoespaciada gris: «cuil, nombre, calle, numero, piso, localidad, provincia, telefono, mail, cp, seccional, fecha_afiliacion, fecha_nacimiento»
3. Texto: «Obligatorios: **cuil**, **nombre**, **localidad** y **provincia**; el resto puede ir vacío (pero respetá las comas si querés cargar un campo posterior). Las líneas que no traigan esos cuatro datos quedan afuera y te decimos cuántas. La **seccional** va por nombre, tal como figura en la pestaña Seccionales: si no coincide con ninguna, el trabajador queda sin asignar. Las dos **fechas** van al final, como AAAA-MM-DD o DD/MM/AAAA, y son opcionales; una fecha que no se entiende deja la línea afuera. En un CUIL que ya está cargado, la línea actualiza su mail del padrón y su fecha de afiliación.»
4. Área de texto de 6 renglones, monoespaciada, placeholder de dos líneas: «20123456786, Juan Pérez, Av. Siempreviva, 742, , Rosario, Santa Fe, 341-555-5555, juan@mail.com, 2000, Rosario» / «27987654320, Ana López».
5. Botón «Cargar lista».
6. Tarjeta «Ubicar domicilios en el mapa»:
   - Texto: «Los trabajadores cargados por lista quedan sin ubicación. Este proceso los ubica de a uno, respetando el límite de un pedido por segundo del servicio de mapas: un padrón de 500 personas tarda unos diez minutos. Podés cerrar esta pantalla, sigue corriendo.»
   - Botón secundario «Georreferenciar pendientes» (se deshabilita mientras corre).
   - Estado **[JS]** (se refresca cada 3 s): barra de progreso en acento + «37 de 120 · 31 ubicados · en curso» / «… · terminado»; o «No hay domicilios pendientes de ubicar.»; o «No se pudo iniciar el proceso.»

#### 2.d Pantalla «Clave temporal» (después de «Restablecer clave», página propia)
- Encabezado común **con link «Volver»** (chevrón) a `/admin#trabajadores`; fondo mesa+franja.
- Título «Clave temporal».
- Tarjeta blanca centrada (460 px): «Martín Sosa · `20314567898`»; la clave grande monoespaciada 32 px en recuadro punteado (p. ej. `K7P2-QX9A`); «Dásela a la persona. Al entrar tiene que cambiarla por una propia.»; «La clave es una sola por persona: vale para todos los sindicatos donde esté empadronada.»; en rojo: «Se muestra una sola vez: no se puede volver a ver. Si la perdés, restablecé la clave de nuevo.»; botón «Volver al panel».

### 3. Qué depende de módulo/permiso/rol
- Toda la pestaña: permiso `trabajadores`.
- Alcance: un acotado ve solo su seccional (la consulta ya viene recortada) y no tiene «Sin asignar».
- «Confirmé su identidad» / «Restablecer clave»: cuenta creada + este padrón responde por ella + alcance.
- «Dar usuario del panel»: solo Super Admin o Admin de Seccional.
- Pastilla «empleado del sindicato»: solo si además tiene usuario del panel.
- Columna «Nivel» se muestra siempre, pero vacía («—») cuando no corresponde.

---

## E3 · Noticias — `/admin#noticias`

[OPC entero: módulo `noticias` + permiso `noticias`.]

### 1. Estados
- **Estado a dibujar:** alta en curso con los 3 pasos completos (título, vigencia, destino Avellaneda+Quilmes, una imagen, formulario elegido), vista del afiliado reflejando todo, y tabla con 3 noticias (vigente / próxima / vencida, una «de todo el sindicato» sin acciones).
- **Modo edición** (al tocar «Editar» en la tabla; NO es modal): título «Editar noticia: {título}», los dos botones de guardar dicen «Guardar cambios», aparece «Cancelar edición», el estado del riel dice «Editando · guardada 2026-10-20 09:14» (o «Editando · **sin guardar**» si se tocó) **[JS]**. Las imágenes ya cargadas NO se muestran (los campos de archivo quedan vacíos; si no se elige otra, se conserva la anterior).
- **Vacío de la tabla:** «Todavía no cargaste ninguna noticia.»
- **Acotado con una sola seccional:** el destino es texto fijo «Va a tu seccional: **Avellaneda**».
- **Sin seccionales cargadas:** no aparece el campo Destino.
- **Globos de ayuda «?»**: al pasar el mouse abren un globo; con clic queda fijo **[JS]**.

### 2. Elementos obligatorios (en orden)
1. Título (`titulo-pagina`): «Dar de alta una noticia».
2. **Hoja de trabajo** (tarjeta ancha `ct-ancho`, 3 columnas: riel · hoja sobre área cuadriculada · vista del afiliado).

**Columna izquierda — Riel de pasos** (cada paso es un link a su sección; número en círculo; con lo obligatorio cargado el número se vuelve tilde verde `hecho`; el primer paso pendiente obligatorio se marca `actual`) **[JS]**:
3. Paso «1» «**La noticia**» — subtítulo inicial «título, bajada y texto»; con título cargado muestra el título (p. ej. «Paritarias: se firmó el acuerdo de octubre»).
4. Paso «2» «**Cuándo y a quién**» — inicial «vigencia y destino»; cargado: «20/10 al 31/10/2026 · Avellaneda, Quilmes» (o «· todas las seccionales» / «· tu seccional»).
5. Paso «3» «**Imágenes y formulario**» — inicial «opcional»; luego «1 imagen · con formulario» / «sin imágenes · sin formulario» / «2 imágenes · …».
6. Bloque de estado: «Nueva · **sin guardar**» (o variantes de edición) + botón principal «Guardar noticia» + botón secundario «Ver como el afiliado» (desplaza a la vista previa).

**Columna central — la hoja** (3 secciones):
7. Sección «1» «La noticia» + marca «obligatorio» + «?» con ayuda: «El **título** y la **bajada** se ven en la portada y en Novedades; el **texto completo** se abre al tocar la noticia. Las URLs se muestran como link.»
   - «Título *» — texto, obligatorio, ancho completo.
   - «Bajada» — texto, placeholder «Resumen corto, se ve en la portada y el listado».
   - «Texto completo» — área de 5 renglones, placeholder «Puede incluir URLs, se muestran como link».
8. Sección «2» «Cuándo y a quién» + «obligatorio» + «?»: «Fuera de la **vigencia** la noticia desaparece de la app (el día de Buenos Aires). El **destino** recorta a qué seccionales les llega: sin marcar ninguna, a todas.»
   - «Vigente desde *» — fecha, obligatoria.
   - «Vigente hasta *» — fecha, obligatoria.
   - «Destino» [OPC: hay seccionales visibles] — casillas, una por seccional visible: ☐ Sede Central ☐ Avellaneda ☐ Quilmes ☐ Lanús. Debajo: «Sin marcar ninguna = todas las seccionales.» (alcance total) / «Sin marcar ninguna = todas las de tu alcance.» (acotado). Con una sola seccional visible y acotado: texto «Va a tu seccional: **Avellaneda**» en vez de casillas.
9. Sección «3» «Imágenes y formulario» + marca «opcional» + «?»: «Hasta dos **imágenes** (la primera es la foto de la portada). El **formulario** le pone a la noticia un ícono que abre ese trámite: escribí en el texto algo como «completá los datos acá».»
   - «Imagen 1» — archivo (png, jpeg, webp, gif).
   - «Imagen 2» — archivo (ídem).
   - «Formulario para iniciar» [OPC: módulo `tramites` + haya formularios cargados + permiso de trámites para que la lista venga] — select: «Sin formulario» + títulos de formularios activos (p. ej. «Solicitud de Reintegro», «Kit escolar 2027»).
10. Pie de la hoja: botón «Guardar noticia» + «Cancelar edición» (solo editando) + nota **[JS]** «Vigente 20/10 al 31/10/2026 · Avellaneda, Quilmes».

**Columna derecha — «Vista del afiliado»** (subtítulo con línea; marco de teléfono) **[JS, se actualiza al escribir]**:
11. Barra del teléfono: «Novedades».
12. Tarjeta: imagen (oculta hasta elegir «Imagen 1»; luego la foto); título (default «Título de la noticia»); bajada (vacía por default); texto (default «El texto completo se muestra al tocar la noticia.»); ícono 📋 con tooltip «Abre el formulario asociado» (solo si hay formulario); vigencia «Vigente del 20/10/2026 al 31/10/2026» (default «Vigencia sin definir»).

**Debajo — tabla**
13. Subtítulo «Noticias cargadas ({n})» → «Noticias cargadas (3)».
14. Columnas: «Título» · «Vigencia» · «Estado» · «Destino» · «Cargada» · (acciones).

    | Título | Vigencia | Estado | Destino | Cargada | Acciones |
    |---|---|---|---|---|---|
    | Paritarias: se firmó el acuerdo de octubre / *Aumento del 6% en dos tramos* | 2026-10-20 → 2026-10-31 | «vigente» (verde) | Avellaneda, Quilmes | 2026-10-20 09:14 | Editar · Borrar |
    | Colonia de verano 2027: inscripción abierta / *Para hijos de 6 a 12 años* | 2026-11-01 → 2026-12-15 | «próxima» (ámbar) | Todas | 2026-10-18 16:40 | «de otra seccional o de todo el sindicato» (gris, sin botones) |
    | Asamblea en Lanús | 2026-09-01 → 2026-09-15 | «vencida» (gris) | Lanús | 2026-08-30 11:02 | Editar · Borrar |

    - Título + bajada gris debajo (si hay).
    - Estados: «vigente» / «próxima» / «vencida» (calculados contra hoy en Buenos Aires).
    - Destino: nombres separados por coma, «?» si la seccional ya no existe, o «Todas».
    - Acciones solo si la noticia cae entera en el alcance de quien mira; «Borrar» (rojo) pide «¿Borrar esta noticia?».
    - No hay miniatura de imagen ni indicador de formulario en la tabla.

### 3. Qué depende de módulo/permiso/rol
- Pestaña: módulo + permiso `noticias`.
- Destino: requiere seccionales; acotado ve solo las suyas.
- Formulario para iniciar: módulo `tramites` y formularios activos.
- Editar/Borrar: solo publicaciones propias del alcance.

---

## E4 · Trámites — `/admin#tramites` (bandeja + detalle; sin constructor)

[OPC entero: módulo `tramites` + permiso `tramites_recibidos` o `tramites_formularios`.]

### 1. Estados
- **Estado a dibujar:** sub-pestaña «Ver trámites» activa con globo «3», tabla con 4 trámites en estados distintos; modal de detalle abierto sobre uno «En tratamiento» con respuestas (una con archivo), avisos del formulario, área a cargo, chat con 4 movimientos, botón «Responder…» y bloque «Pasar a otra área».
- **Sub-pestañas** (pastillas): «Ver trámites» (+ globo) [OPC: `tramites_recibidos`] · «Crear / editar formularios» [OPC: `tramites_formularios`] (fuera de alcance de este inventario; cuando está activa aparece el botón flotante «H» de Ayuda). Si solo tiene `tramites_formularios`, arranca en esa.
- **Vacío:** «Todavía no llegó ningún trámite.»
- **Modal detalle**: cargando («Cargando…»), error («No se pudo cargar el trámite.»), terminado (sin responder), de otra área (solo lectura).
- **Modal «Responder» / «Mensaje»** (segundo modal, encima).
- **Avisos** arriba (del constructor, pueden verse al volver de guardar): `error=campos` «Revisá los campos del formulario: necesita al menos uno con etiqueta y tipo de dato válidos.» · `error=tramitesenviados` «No se puede borrar: ya hay trámites presentados contra este tipo. Desactivalo en su lugar (destildá "Activo" al editarlo).» · `error=sindestino` «Elegí el área que recibe este trámite por defecto. Sin eso, un trámite de una seccional sin mapear no caería en ninguna bandeja.»

### 2. Elementos obligatorios (en orden)

#### 2.a Bandeja «Ver trámites»
1. Sub-pestañas: «Ver trámites» + globo rojo «3» (se refresca cada 30 s **[JS]**) · «Crear / editar formularios».
2. Título (`titulo-pagina`): «Trámites recibidos ({n})» → «Trámites recibidos (4)».
3. Filtros (en vivo, del lado del navegador **[JS]**):
   - input placeholder «Buscar por CUIL»
   - input placeholder «Buscar por N° de expediente»
   - select: «Todos los estados» · «Iniciado» · «En tratamiento» · «Respondido» · «A la espera de información del afiliado» · «Terminado»
   - botón chico «Limpiar»
   - contador «4 resultados» / «1 resultado»
4. Tabla. Columnas: «Expediente» · «CUIL» · «Tipo» · «Estado» · «Actualizado» · (acción). **No hay columna de nombre del afiliado, ni de área, ni de seccional, ni marca de "nuevo" por fila** (lo nuevo = estado «Iniciado»).

   | Expediente | CUIL | Tipo | Estado | Actualizado | |
   |---|---|---|---|---|---|
   | `UOMR01-2026-000142` | 20314567898 | Solicitud de Reintegro | «Iniciado» (ámbar) | 2026-10-23 10:05 | Ver |
   | `UOMKIT-2026-000087` | 27389123450 | Kit escolar 2027 | «En tratamiento» (ámbar) | 2026-10-22 17:30 | Ver |
   | `UOMR01-2026-000139` | 20287654326 | Solicitud de Reintegro | «A la espera de información del afiliado» (ámbar) | 2026-10-21 12:48 | Ver |
   | `UOMSUB-2026-000051` | 20314567898 | Subsidio por nacimiento | «Terminado» (verde) | 2026-10-15 09:20 | Ver |

   - Estados posibles (5, nombres reales): «Iniciado», «En tratamiento», «Respondido», «A la espera de información del afiliado», «Terminado». Pastilla verde solo «Terminado»; las otras cuatro ámbar.
   - Formato de expediente: `{código del formulario}-{año}-{6 dígitos}`.
   - Orden: más nuevo primero. Sin paginado.
   - Al responder desde el modal, la fila actualiza estado y «Actualizado» sin recargar **[JS]**.

#### 2.b Modal de detalle del trámite **[JS — todo el contenido]**
Caja de 640 px; encabezado oscuro (degradé base→primario, filo acento, condensada 20 px mayúscula) + X «Cerrar». Se mueve arrastrando del encabezado en escritorio.
5. Título: «{expediente} — {tipo}» → «UOMKIT-2026-000087 — Kit escolar 2027» (mientras carga: «Trámite»).
6. Fila «CUIL» → `27389123450`. (No muestra nombre del afiliado.)
7. [OPC: si hay] Recuadro amarillo «AVISOS DEL FORMULARIO» con una línea por aviso, p. ej. «La edad del hijo supera los 12 años.» o «El afiliado corrigió "Fecha de nacimiento" (propuesto: 2015-04-02).»
8. Subtítulo «Respuestas del formulario» + una fila por campo (rótulo gris izquierda · valor derecha):
   - «Nombre del hijo/a» → «Tomás Benítez»
   - «Fecha de nacimiento» → «2016-05-12»
   - «Escuela» → «EP N° 14 Quilmes»
   - «Constancia de alumno regular» → link «📎 constancia.pdf» (abre en pestaña nueva)
   - Vacío: «Sin respuestas.»
9. [OPC: si tiene área] Fila «Área a cargo» → «**Acción Social**».
10. Subtítulo «Conversación» + **hilo tipo chat**, ordenado por fecha. Tipos de ítem:
    - **Movimiento del sistema** (renglón centrado gris): «Trámite presentado por el trabajador (UOMKIT-2026-000087). · 17:02» · «Pasó de Prensa a Acción Social. Motivo: corresponde a beneficios · 09:40» · (estados viejos) «Iniciado → En tratamiento · 10:15».
    - **Burbuja del afiliado** (izquierda, avatar con su foto o ícono): remitente «Trabajador», texto, (si hay) clip de adjunto, hora «18:20».
    - **Burbuja del sindicato** (derecha, avatar = logo del sindicato o iniciales «UOM» sobre color base): remitente «Vos (sindicato)», texto, (si hay) tarjeta «📋 Kit escolar 2027 — Formulario para iniciar» (o «Formulario ya no disponible», o «(desactivado)»), **sello del estado que fijó ese mensaje** (p. ej. «En tratamiento»), hora.
    - Burbuja sin texto con adjunto: «📎 Adjunto».
    - **Trámite encadenado** (burbuja del afiliado con tarjeta): rótulo «Iniciado desde el trámite» o «Trámite iniciado desde este chat» + «⇄ **UOMR01-2026-000130** · Solicitud de Reintegro» + botón «Abrir el trámite».
    - Vacío: «Todavía no hay mensajes en este trámite.»
    - Tocar cualquier burbuja abre el modal «Mensaje».
11. Pie, una de tres:
    - Terminado: «Trámite terminado -- no se puede modificar.»
    - Lo tiene otra área: «Este trámite lo tiene otra área. Podés verlo, no responderlo.»
    - Puede responder: botón ancho «Responder…» y, [OPC: el formulario permite pase y quedan áreas], bloque **«Pasar a otra área»**: select de áreas «Acción Social · Sede Central», «Turismo · Avellaneda»… + input placeholder «Motivo (opcional)» + botón «Pasar» + nota «El área que lo reciba pasa a ser la única que puede responder. Vos vas a poder seguir viéndolo.» Confirmación al pasar: «Al pasarlo, el área que lo reciba queda a cargo y vos ya no vas a poder responderlo. ¿Seguimos?» Error: «No se pudo derivar el trámite.»

#### 2.c Modal «Responder» / «Mensaje» (440 px, encima del detalle) **[JS]**
12. Título: «Responder» (desde el botón) o el remitente «Vos (sindicato)» / «Trabajador» (al tocar una burbuja).
13. Si se abrió desde una burbuja: «Trabajador · 2026-10-22 18:20», el texto completo (respeta saltos), link al adjunto «📎 boleta_inscripcion.jpg», tarjeta de formulario si hay.
14. Si está terminado: «Trámite terminado -- no se puede modificar.» (sin formulario).
15. Formulario de respuesta:
    - Área de texto 3 renglones, placeholder «Escribile una nota o pedile más información…»
    - [OPC: hay formularios activos] select «Adjuntar un formulario para iniciar (opcional)» + «📋 Solicitud de Reintegro», «📋 Kit escolar 2027»…
    - Rótulo «Estado al responder» + select con los 5 estados (preseleccionado el actual).
    - Archivo adjunto (input file, hasta 10 MB) + botón «Enviar».
    - Error: «No se pudo enviar la nota.» Exige texto, adjunto o formulario.
    - Responder y cambiar estado son **un solo acto** (un solo mensaje en el chat, con el sello del estado).

### 3. Qué depende de módulo/permiso/rol
- Bandeja: permiso `tramites_recibidos`; la lista ya viene recortada al área/seccional del usuario.
- Formularios: `tramites_formularios`.
- «Responder…»/«Pasar»: solo el área a cargo; pase solo si el formulario lo permite.
- Selector de formulario en la respuesta: si hay formularios activos.
- (Empleadores tiene su propia bandeja espejo dentro de su pestaña: no es esta pantalla.)

---

## E5 · Reportes — `/admin#reportes`

[OPC entero: módulo `recibos` + permiso `reportes`.] La lista se pide al servidor recién al abrir la pestaña, paginada de a **50**.

### 1. Estados
- **Estado a dibujar:** lista con filas enviadas y anónimas mezcladas, contador «1.248 recibos», paginado «Página 1 de 25», sin aviso de cláusula (cláusula firmada).
- **Sin cláusula firmada y con recibos no enviados:** aparece el aviso amarillo (ver abajo) y la lista trae solo los enviados.
- **Cargando:** fila única «Cargando…».
- **Error:** «No se pudo cargar la lista. » + botón «Reintentar».
- **Sin resultados:** «No hay recibos con esos filtros.»
- **Una sola página:** no se dibuja el paginado.
- **Modal «Ver»**: cargando, enviado (identificado), no enviado (anonimizado), error.

### 2. Elementos obligatorios (en orden)
1. Título (`titulo-pagina`): «Reportes».
2. Bajada: «Todos los recibos que verificaron los afiliados. Los que el afiliado **envió** al sindicato se ven con sus datos; los que verificó y **no envió** se ven anonimizados, sin nombre, CUIL ni empresa.»
3. [OPC, **JS**] Aviso de cláusula (solo sin cláusula y con no enviados): «Hay 312 recibos que los afiliados verificaron sin enviar. Se van a ver acá, anonimizados, cuando el sindicato firme la cláusula de confidencialidad con Colm3na.»
4. Filtros (los de texto con espera de 300 ms; el resto al cambiar) **[JS]**:
   - input placeholder «Buscar por CUIL»
   - input placeholder «Buscar por nombre»
   - fecha, tooltip «Desde»
   - fecha, tooltip «Hasta»
   - select resultado: «Con y sin diferencias» · «Con diferencias» · «Sin diferencias»
   - select envío: «Enviados y no enviados» · «Enviados» · «No enviados»
   - botón chico «Limpiar»
   - contador «1.248 recibos» / «1 recibo» (monoespaciada)
5. Nota chica: «La búsqueda por CUIL o por nombre encuentra solo recibos enviados: los otros no llevan datos de la persona.»
6. Tabla (zebra). Columnas: «Fecha» · «CUIL» · «Nombre» · «Empresa» · «Período» · «Diferencias» (centrada) · «Enviado» · (acción).

   | Fecha | CUIL | Nombre | Empresa | Período | Diferencias | Enviado | |
   |---|---|---|---|---|---|---|---|
   | 22/10/2026 18:42 | 20314567898 | Martín Sosa | Metalúrgica del Sur SA | 2026-09 | ✓ (círculo verde, tooltip «Sin diferencias») | «Sí» (verde) | Ver |
   | 22/10/2026 11:15 | *anónimo* | *anónimo* | *anónimo* | 2026-09 | ✗ (círculo rojo, tooltip «Con diferencias») | «No» (ámbar) | Ver |
   | 21/10/2026 09:03 | 27389123450 | Carla Benítez | Metalúrgica del Sur SA | 2026-08 | ✗ | «Sí» | Ver |

   - «anónimo» en itálica gris, en las tres columnas de identidad, para los no enviados.
   - Empresa: nombre de la empresa si está en el catálogo; si no, el CUIT; o «—».
   - Período o «—»; Nombre o «—».
   - Orden: más nuevo primero.
7. Paginado (a la derecha, solo si hay más de una página): «‹ Anterior» · «Página 1 de 25» · «Siguiente ›» (deshabilitados en los extremos).

#### Modal «Ver» (detalle del recibo) **[JS]**
Mismo marco que el modal de trámite (encabezado oscuro, X).
8. Título: enviado → «Recibo de Martín Sosa — 2026-09»; no enviado → «Recibo anonimizado — 2026-09»; cargando → «Recibo».
9. Filas:
   - «Estado» → pastilla «Sin diferencias» (verde) / «Con diferencias» (ámbar)
   - «Enviado al sindicato» → «Sí» / «No — recibo anonimizado»
   - «Período» → «2026-09»
   - [solo enviados] «Trabajador» → «Martín Sosa (CUIL 20314567898)»
   - [solo enviados] «Empleador» → «Metalúrgica del Sur SA»
   - [si hay] «Fecha de cobro» → «05/10/2026»
10. Subtítulo «Conceptos del recibo (12)» + una línea por concepto: descripción · importe (los negativos en rojo): «Sueldo básico $ 1185000.00», «Antigüedad $ 94800.00», «Jubilación -$130378.00», «Ley 19032 -$35557.64», «Obra social -$35557.64», «Cuota sindical UOM -$29630.00»… (formato actual `$1234.56`, sin separador de miles).
11. Totales (negrita): «Total ingresos», «Total descuentos» (rojo), «Reintegros» [solo si hay], «Total neto»; y gris «Total remunerativo: $1185000.00».
12. Diferencias: subtítulo «Diferencias detectadas (2)» + lista, p. ej. «Cuota sindical: esperado $35,550.00, figura $29,630.00 (diferencia $-5,920.00).», «El recibo no incluye 'Seguro de vida'.», «Suma de descuentos ($231,123.28) no coincide con el impreso ($231,500.00). Puede ser un error de lectura; conviene revisar la foto antes de reportar.»; o, sin diferencias, «✓ Todos los aportes coinciden con lo esperado.»
13. [si hay] «⚠ Alertas legales» (marrón) + lista.
14. [si hay] «Avisos» + lista.
15. Error: «No se pudo cargar el recibo.»

### 3. Qué depende de módulo/permiso/rol
- Pestaña: módulo `recibos` + permiso `reportes`.
- Filas anónimas: solo si plataforma marcó la **cláusula de confidencialidad** del sindicato; si no, aviso y solo enviados.
- Acotado: solo recibos de afiliados de su seccional (en la consulta).
- Identidad (CUIL/nombre/empresa) solo en enviados; la anonimización la hace el servidor.

---

## Lo que más fácil se olvida (lista de control)
1. La tira tiene **16 entradas** (15 paneles + el link a Panel Sindical), no 14: Encuestas, Convenio y Listas también existen.
2. Sin `#ancla` en `/admin` ninguna pestaña está activa.
3. En `/admin` **no se ve quién está logueado**; Inicio/Salir/Ayuda son círculos flotantes **abajo a la derecha**, y el «H» de Ayuda aparece solo en 3 lugares.
4. «Editar» trabajador **no es un modal**: reutiliza «Alta manual» con el CUIL bloqueado y el mapa abierto.
5. «Clave temporal» es una **pantalla aparte** con «Volver».
6. Los avisos `?err=`/`?ok=` de Trabajadores (12 variantes) y el resultado de la carga masiva (hasta 6 líneas).
7. La casilla «Declarados sin recibo» y la tarjeta «Georreferenciar pendientes» con su barra de progreso.
8. Noticias: los **«?» con globo** de cada paso, el estado del riel, el destino fijo «Va a tu seccional», y que la tabla tiene acciones solo para las propias.
9. Trámites: la bandeja **no muestra nombre** del afiliado; el modal tiene **dos niveles** (detalle + «Responder/Mensaje»), los sellos de estado pegados a cada burbuja, las tarjetas de trámite encadenado y el bloque «Pasar a otra área».
10. Reportes: el aviso de la cláusula, la nota de que la búsqueda solo encuentra enviados, y que el paginado solo aparece con más de 50.
11. Portada: «Áreas y Usuarios» solo para Super Admin (la pestaña la ve también el Admin de Seccional); no hay tarjetas de Convenio ni Listas.
