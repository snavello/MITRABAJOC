# Inventario de la app del afiliado (teléfono) — 5 pantallas

Fuente: `templates/portada.html`, `templates/trabajador.html`, `templates/_encabezado.html`,
`templates/_fondo_interior.html`, `static/pwa.js`, rutas `/app/inicio` y `/app` de `main.py`,
textos del servidor en `semaforo.py`, `validador.py` y `db.py`. Leído el 2026-10-23, sin tocar el repo.

Convenciones:
- Texto entre comillas «…» = literal tal cual está en el código.
- **[JS]** = lo arma el JavaScript (no está en el HTML que manda el servidor).
- **[SRV]** = texto que viene redactado del servidor (API o Python), no de la plantilla.
- **[MÓD x]** = solo existe si el sindicato tiene habilitado el módulo `x`.
- **[COND …]** = depende de un dato o condición.
- Datos de ejemplo: Martín Sosa, CUIL 20-31456789-8 (la app lo muestra SIN guiones: `20314567898`),
  DNI 31456789, Seccional Avellaneda, Unión Obrera Metalúrgica, empleador «Metalúrgica del Sur SA»
  (CUIT 30-71234567-9), período Septiembre 2026.

---

## 0 · Elementos comunes (encabezado, Inicio/Salir, tira de pestañas, perfil, globos)

### 0.1 Encabezado (`_encabezado.html`) — igual en T1 y en /app (T2–T5)
Una sola barra oscura (fondo `--marca-base`), una línea:
1. Izquierda: **logo del sindicato** (imagen `/logo/{id}`, alt = nombre del sindicato, 62 px de alto
   en escritorio / 46 px en móvil, ancho libre).
   - [COND sin logo cargado] en su lugar el **nombre del sindicato en texto**: «Unión Obrera Metalúrgica».
2. Derecha: **logo de Colm3na** (versión para fondo oscuro, alt «Colm3na», 24 px / 19 px en móvil).
- No hay nombre de pantalla, no hay cinta de rol, no hay botón de perfil ni menú en el encabezado.
- En /app el encabezado queda **fijo arriba** al scrollear (`enc_fija`); en la portada (T1) no es fijo.
- [COND entorno local/pruebas] pastilla ámbar fija abajo a la izquierda: «PRUEBAS · v0.46.02» (no en demo/prod).

### 0.2 Botones «Inicio» y «Salir» — DÓNDE están hoy
- Son **dos botones redondos flotantes** (42 px, fondo `--marca-base`, ícono de línea), `position:fixed`,
  **abajo a la derecha, a 84 px del borde inferior** (por encima de la tira de pestañas).
  - **Inicio**: ícono casa (`#ic-home`, trazo color acento), a 68 px del borde derecho. `title`/aria-label «Inicio». Va a `/app/inicio`.
  - **Salir**: ícono X (`#ic-x`, trazo blanco), a 18 px del borde derecho. `title`/aria-label «Salir». Va a `/trabajador/salir` (borra la sesión y vuelve a `/ingresar`).
- Aparecen **en T1 (portada) y en todas las pestañas de /app (T2–T5)**, mismo lugar. No tienen texto visible, solo ícono.
- En /app solo si hay sesión (`cuil`); la ruta demo sin login no los muestra.
- No hay otro "Volver al inicio" ni "Cerrar sesión" en ninguna pantalla. Tampoco hay botón "Cambiar de sindicato" para el afiliado con pluriempleo (el selector aparece solo al entrar).

### 0.3 Barra de identidad (solo /app, T2–T5)
Debajo del encabezado, franja blanca con línea inferior:
- Nombre: «Martín Sosa» (fallback «Trabajador»).
- «CUIL 20314567898».
- Sin foto, sin enlace al perfil.

### 0.4 Tira de pestañas de /app (barra inferior fija, blanca)
Hasta **7** botones, cada uno con ícono de línea dentro de una "píldora" (42×28) + rótulo de 10 px debajo.
La activa: rótulo e ícono en color acento y píldora con fondo acento al 15%. Orden y condición:
| # | Rótulo literal | Ícono | Condición | Globo |
|---|---|---|---|---|
| 1 | «Mis Recibos» | recibo (hoja con renglones) | [MÓD recibos] | — |
| 2 | «Credencial» | carnet | [MÓD credencial] y sindicato con marca | — |
| 3 | «Novedades» | megáfono | [MÓD noticias] | — |
| 4 | «Mis Aportes» | tres barras | [MÓD aportes] | — |
| 5 | «Capacitación» | birrete | [MÓD capacitacion] | — |
| 6 | «Trámites» | hoja con tilde | [MÓD tramites] | **sí**: círculo rojo `#e5484d` con número = trámites con novedad (p. ej. «2»); oculto si 0. Se refresca al volver la app a primer plano [JS]. |
| 7 | «Encuestas» | lista con tilde | [MÓD encuestas] | **sí**: encuestas abiertas sin responder (p. ej. «1») [JS]. |
- La pestaña inicial: la que pide `?tab=` (recibo, credencial, novedades, aportes, capacitacion, tramites, encuestas); si no viene o no existe, la primera habilitada.
- Al cambiar de pestaña se vuelve arriba de todo.
- La pestaña se llama «Mis Recibos» en la tira, pero el CLAUDE.md la llama "Tu Recibo".

### 0.5 Acceso al perfil
- **Solo existe en la portada (T1)**: círculo a la derecha del saludo (foto del afiliado o ícono de persona), aria-label/title «Tu perfil». Abre el modal de perfil (ver T1 §modales). En /app (T2–T5) no hay acceso al perfil.

### 0.6 Globos de notificación (todos)
- Portada: sobre la fila «Notificaciones» (no leídas), sobre «Encuestas» (pendientes), sobre «Trámites» (con novedad). Círculo rojo `#e5484d`, número blanco 13,5 px, borde del color base, posición arriba-derecha **por fuera** de la tarjeta.
- /app: sobre las pestañas «Trámites» y «Encuestas» (ver 0.4).
- Dentro de Trámites: punto de novedad junto al título del trámite y pie «Hay novedades del sindicato» (ver T5).
- Se refrescan solos al volver la app de segundo plano [JS].

### 0.7 Banner de instalación (PWA) — solo /app, solo en celular y si no está instalada [JS, `pwa.js`]
- Botón fijo abajo a la izquierda (sobre la tira): «Instalar app».
- Banner (por cadencia) sobre la tira, ancho completo: texto «Instalá Colm3na en tu celular para acceder más rápido, como cualquier otra app.» + línea chica «No pide ningún permiso especial.» + botón «Instalar» + cerrar «×».
  - Variante iPhone: «Instalá Colm3na: tocá **Compartir** (el ícono de la flecha hacia arriba) y elegí **"Agregar a inicio"**.» + botón «Entendido».
  - Variante Android sin evento: «Instalá Colm3na desde el menú de Chrome: tocá **⋮** (arriba a la derecha) y elegí **"Instalar app"** (o **"Agregar a pantalla de inicio"**).» + «Entendido».
- Pedido de permiso de notificaciones push: diálogo nativo del navegador al primer toque (no hay UI propia).

### 0.8 Fondo
- T1: fondo oscuro de marca (radial primario→base) o claro (`portada_clara`), con grano, dos manchas de luz (primario y acento) y retícula de colmena (`.pt-ambiente`).
- /app: "mesa" gris frío + retícula al 6% + halos de acento/primario + franja de marca que baja del encabezado (se apaga en ≤760 px, o sea en el teléfono no se ve).

---

## T1 · Portada del afiliado `/app/inicio` (`portada.html`)

### 1. Estados
- **A dibujar (el más completo)**: con recibos verificados, aviso de mail, las 6 filas de acceso con globos, 3 noticias con foto y carrusel con varios beneficios.
- Otros:
  - **Sin recibos todavía**: la tarjeta principal cambia de antetítulo, no muestra número y cambia el texto y el botón (ver ítem 6).
  - **Último recibo con diferencias**: cambia la línea de estado de la tarjeta.
  - **Sin aviso de mail** (cuenta con mail confirmado): la fila de aviso no aparece.
  - **Sin noticias**: texto vacío en el riel. **Sin beneficios**: texto vacío. **Un solo beneficio**: sin flechas, sin barra ni puntos.
  - **Sin foto de perfil**: el círculo muestra ícono de persona.
  - **Credencial no generada**: cambia la bajada de la fila Credencial.
  - **Encuestas pendientes**: cambia la bajada de la fila Encuestas.
  - Layout: en teléfono una columna (acción arriba, novedades/beneficios abajo); ≥1040 px dos columnas (riel de 352 px a la derecha).
  - Pluriempleo sin sindicato elegido: no se muestra la portada sino el selector `elegir_sindicato.html` (fuera de este inventario).

### 2. Elementos obligatorios (en orden)
1. Encabezado (0.1).
2. Botones flotantes Inicio / Salir (0.2).
3. **Saludo**: «Hola, » + nombre en color acento → «Hola, *Martín*» (primer nombre; fallback «Trabajador»). Condensada 30 px.
4. **Bajada del saludo**: «Seccional Avellaneda · Unión Obrera Metalúrgica» ([COND sin seccional] solo «Unión Obrera Metalúrgica»).
5. **Círculo de perfil** a la derecha del saludo (borde acento): foto del afiliado (`/perfil-foto/{cuil}`) o ícono de persona. aria «Tu perfil».
6. [COND cuenta nivel 1 sin mail confirmado] **Fila de aviso** (vidrio), enlace a `/app/confirmar-mail`:
   - pastilla con ícono de sobre;
   - título «Confirmá tu mail para proteger tu cuenta»;
   - bajada «Te mandamos un código y listo: te lleva un minuto.»;
   - flecha a la derecha.
7. [MÓD recibos] **Tarjeta principal (hero)**, enlace a `/app`:
   - antetítulo: «Lo primero» (si ya verificó alguno) / «Empezá por acá» (si no);
   - título: «Mis recibos»;
   - [COND con recibos] número grande + texto chico: «4» «recibos verificados este año» (singular: «recibo verificado este año»);
   - [COND con recibos] línea de estado: «Septiembre 2026 · sin diferencias» o «Septiembre 2026 · con diferencias para revisar»;
   - [COND sin recibos] texto: «Sacale una foto o subí el PDF y te decimos si los aportes están bien calculados.»;
   - botón/CTA con flecha: «Subir un recibo nuevo» (con recibos) / «Subí tu primer recibo» (sin recibos);
   - ícono grande de recibo de fondo (decorativo).
8. **Filas de acceso** (cada una: pastilla con ícono · título · bajada · flecha):
   1. [MÓD aportes] «Mis aportes» / «Semáforo de aportes» → `/app?tab=aportes`.
   2. [MÓD credencial] «Credencial» / «Tu carnet digital» (o «Todavía no generada») → `/app?tab=credencial`.
   3. [MÓD capacitacion] «Capacitación» / «Entendé tu nuevo recibo» → `/app?tab=capacitacion`.
   4. [MÓD notificaciones] «Notificaciones» / «Mensajes de tu sindicato» → `/app/notificaciones` (bandeja, página aparte). **Globo** con no leídas, p. ej. «3».
   5. [MÓD encuestas] «Encuestas» / «Tenés 1 sin responder» (o «Tu opinión al sindicato» si 0) → `/app?tab=encuestas`. **Globo** con pendientes.
   6. [MÓD tramites] «Trámites» / «Formularios y seguimiento» → `/app?tab=tramites`. **Globo** con trámites con novedad, p. ej. «2».
9. **Riel derecho** (`aside`):
   - [MÓD noticias] Título de sección «Novedades» + enlace «Ver todas» (→ `/app?tab=novedades`, solo si hay noticias).
     - Hasta **3 noticias** (botones), la primera marcada "fresca" (filo de acento). Por ítem: miniatura 62 px (foto 1 de la noticia, o ícono de renglones), fecha «28/09 10:15», título, bajada opcional.
       - Ej. 1: «28/09 10:15» · «Paritaria metalúrgica: nuevo acuerdo» · «Cómo impacta en tu recibo de octubre».
       - Ej. 2: «22/09 18:40» · «Jornada de salud en la seccional» · (sin bajada).
     - [COND sin noticias] «Acá vas a ver los mensajes y avisos de tu sindicato. Muy pronto.»
   - [MÓD beneficios] Título «Beneficios».
     - **Carrusel**: diapositivas a ancho completo con imagen de fondo, velo, y texto: chip de rubro (p. ej. «Turismo»), descripción (p. ej. «20% en el Hotel Sindical de Mar del Plata»), «Hasta el 31/12/2026».
     - [COND >1 beneficio] flechas «Anterior»/«Siguiente» (aria), pie con **barra de tiempo** (avanza en 5,4 s) y **puntos** (uno por beneficio, aria «Beneficio 1»…). Avance automático, pausa al pasar el mouse, arrastre con el dedo; sin autoplay con "reducir movimiento".
     - [COND sin beneficios] «Próximamente vas a tener descuentos y beneficios para afiliados.»
10. Al pie, centrado, botón tenue «Acerca de».

### 2b. Modales que abre la portada
- **Tu perfil** (hoja clara desde abajo; 576 px en escritorio). Encabezado oscuro con filo acento: antetítulo «Unión Obrera Metalúrgica», título «Tu perfil», cerrar X (aria «Cerrar»).
  - Foto 101 px redonda con borde acento (o ícono persona); lápiz «Cambiar foto» (abre cámara/galería: `accept="image/*" capture="environment"`). Tocar la foto la agranda (lightbox, máx. ¼ de pantalla).
  - Campos (rótulo en mayúsculas chicas; «(opcional)» en minúscula al lado):
    1. «CUIL» — deshabilitado, «20314567898».
    2. «Nombre» — «Martín Sosa» (obligatorio).
    3. «Localidad *» — texto con sugerencias en vivo (datalist [JS] de Georef), p. ej. «Avellaneda».
    4. «Provincia *» — select: «—» + las 24 provincias (p. ej. «Buenos Aires»).
    5. Nota: «Tu sindicato usa la provincia y la localidad para agruparte por zona y mandarte lo de tu seccional. El resto del domicilio es opcional.»
    6. «Calle (opcional)» — «Av. Mitre».  7. «Altura (opcional)» — «1450».  8. «Piso (opcional)» — «3° B». (en una fila de 3)
    9. «Código postal (opcional)» — «1870».  10. «Teléfono (opcional)» — «11 5555-1234». (fila de 2)
    11. «Mail (opcional)» — «martin.sosa@mail.com».
    12. «Fecha de nacimiento (opcional)» — selector de fecha, «14/03/1985».
    13. Botón secundario «Ubicar mi domicilio en el mapa» (→ «Buscando…»). [JS] Debajo: nota de geocodificación, mini-mapa 220 px con globo arrastrable y lista de candidatos (botones con la dirección; el elegido con borde acento). Notas posibles: «Encontramos tu dirección. Arrastrá el globo si no está en la puerta.» / «Arrastrá el globo hasta tu casa para ajustarlo.» / «No encontramos ese domicilio. Podés guardar igual.» / «Hiciste muchas búsquedas seguidas. Probá en un rato. Podés guardar igual.» / «No pudimos buscar el domicilio. Podés guardar igual.»
    14. Botón principal «Guardar cambios» (→ «Guardando…»). Mensaje debajo [JS]: «Guardado ✓» / «El nombre no puede estar vacío.» / «Falta tu provincia y tu localidad: tu sindicato las necesita para agruparte por zona.» / «No se pudo guardar. Probá de nuevo.» / «No se pudo subir la foto.» / «No se pudo leer la imagen.»
  - Bloque **«Mi seccional»** (solo lectura):
    - nombre «Seccional Avellaneda»; dirección «Av. Mitre 750, Avellaneda, Buenos Aires»; horario «Lunes a viernes de 9 a 17 h».
    - mini-mapa 220 px (tocar → mapa en pantalla completa; title «Tocá para verlo en pantalla completa»), o aviso «Tu seccional todavía no está ubicada en el mapa.»
    - [COND precisión aproximada] «La ubicación es aproximada: el mapa marca el centro de la localidad, no la puerta.»
    - botones acento: «Llamar» [COND teléfono] · «WhatsApp» [COND whatsapp] · «Cómo llegar» [COND ubicada].
    - botón contorno «Ver otras seccionales cerca».
    - [COND sin seccional] solo «Tu sindicato todavía no te asignó una seccional.»
- **Mapa en pantalla completa**: antetítulo sindicato, título = nombre de la seccional, mapa 62vh con globo y popup (nombre + dirección), cerrar X.
- **Seccionales cerca** [JS]: antetítulo sindicato, título «Seccionales cerca», cerrar X.
  - Paso inicial: «Podemos ordenar las seccionales por cercanía usando la ubicación de tu teléfono. **No se guarda ni se envía a nadie**: se usa en esta pantalla y se descarta.» + botones «Usar mi ubicación» y «Ver la lista sin ubicarme».
  - Esperando GPS: «Buscando tu ubicación…».
  - Con origen: «Distancias medidas desde tu ubicación.» (o «…desde tu domicilio.») + mapa con punto azul y las 5 más cercanas + lista de 5 tarjetas: «2,3 km» (monoespaciada, a la derecha), nombre en negrita, «· tu seccional» si es la propia (borde acento 2 px), dirección, horario, [COND aproximada] «Ubicación aproximada: el punto es el centro de la localidad.», botones «Llamar» / «WhatsApp» / «Cómo llegar».
  - Sin origen: «Sin tu ubicación ni tu domicilio cargado, te mostramos todas las seccionales ordenadas por provincia.» + todas las tarjetas sin km.
  - Vacío: «Tu sindicato todavía no cargó la ubicación de sus seccionales.» Error: «No pudimos traer las seccionales. Probá de nuevo.»
- **Detalle de noticia**: antetítulo sindicato, título [JS] (mientras carga «Cargando…»), bajada, antigüedad («Hoy» / «Ayer» / «Hace 3 días» / «Hace 2 meses»), texto completo con enlaces, hasta 2 imágenes a ancho completo (tocar → ampliada), [COND] ícono redondo 📋 «Completar el formulario» y/o 📊 «Responder la encuesta». Error: «No se pudo cargar la noticia.»
- **Detalle de beneficio**: antetítulo «Beneficio», título = rubro, imagen, descripción, [COND link] «Ver más →», [COND] ícono 📋 «Completar el formulario». Error: «No se pudo cargar el beneficio.»
- **Acerca de** (hoja oscura): «Acerca de» + filas «Versión» «0.46.02», «Fecha» «2026-10-19 18:40», [COND] «Entorno» «pruebas».
- **Imagen ampliada** (fondo oscuro, imagen al centro).
- (Hay un modal «Notificaciones» en el código sin ningún botón que lo abra: quedó muerto desde que la fila lleva a la bandeja `/app/notificaciones`. Textos: «Cargando…», «Todavía no tenés notificaciones.», «No se pudieron cargar las notificaciones.», remitente «Tu sindicato», «📎 Ver adjunto». No hace falta diseñarlo.)

### 3. Opcional en el diseño
Todo lo marcado [MÓD]: recibos (hero), aportes, credencial, capacitacion, notificaciones, encuestas, tramites, noticias, beneficios. Aviso de mail [COND nivel 1]. Seccional en la bajada [COND]. Globos [COND >0].

---

## T2 · Tu Recibo `/app` (pestaña «Mis Recibos»)  [MÓD recibos]

Estructura: un **panel oscuro de marco** (`rc-panel`) con antetítulo (kicker), título en condensada 31 px mayúsculas, bajada, **línea de 3 pasos**, una **hoja clara** adentro y los **botones sobre el oscuro, fuera de la hoja**. Debajo de todo, siempre, la nota legal.

**Línea de pasos** (se repite en todos los estados; [JS]): tres pasos con círculo (número o tilde), rótulo y detalle:
«1 · Subí · foto o PDF», «2 · Revisá · lo que leímos», «3 · Resultado · tus aportes». Estados de cada paso: pendiente / actual / hecho (tilde) / en curso (animado).

**Nota legal fija al pie de la pestaña** (todos los estados): «Es una verificación orientativa, no un dictamen legal. Tu recibo se procesa para esta revisión; no lo compartimos con terceros.»

### 1. Estados (todos en la misma pestaña, se reemplazan uno a otro)
| Estado | Kicker | Título | Bajada | Pasos |
|---|---|---|---|---|
| P1a Sin archivo | «Paso 1 de 3» | «Subí tu recibo» | «Sacale una foto o subí el PDF que te manda la empresa.» | 1 actual |
| P1b Archivo elegido | «Paso 1 de 3» | «Subí tu recibo» | «Ya tenemos el archivo. Cuando quieras, lo leemos.» | 1 actual |
| Leyendo (espera IA) [JS] | «Paso 2 de 3 · en curso» | «Leyendo tu recibo» | «No cierres la app: suele tardar menos de un minuto.» | 1 hecho, 2 en curso |
| P2 Confirmar [JS] | «Paso 2 de 3» | «Confirmá los datos» | «Esto es lo que leímos del recibo. Si está bien, seguimos con la verificación.» | 1 hecho, 2 actual |
| Verificando (espera) [JS] | «Paso 3 de 3 · en curso» | «Verificando los aportes» | «Un momento: estamos haciendo las cuentas.» | 1-2 hechos, 3 en curso |
| P3 Resultado OK [JS] | «Paso 3 de 3» | «Todo en orden» | «septiembre 2026» | 1-2 hechos, 3 actual |
| P3 Resultado con diferencias [JS] | «Paso 3 de 3» | «Hay 1 diferencia» / «Hay 3 diferencias» | «septiembre 2026» | ídem |
| P3 Recibo ajeno [JS] | «Paso 3 de 3» | «Este recibo no es tuyo» | — | ídem |
| Error (lectura o verificación) [JS] | «Verificación detenida» | «No pudimos seguir» | — | según en qué paso falló |
| Historial | (sin marco oscuro) | «Mis recibos verificados» | ver abajo | — |
- **Dibujar**: P2 Confirmar y P3 Resultado con diferencias (son los más cargados) + P1a.
- Ojo: el período en el resultado sale en minúscula («septiembre 2026», `fmtPeriodo` del JS) mientras la portada dice «Septiembre 2026».

### 2. Elementos obligatorios

**P1a · Subí tu recibo (sin archivo)**
1. Kicker «Paso 1 de 3», título «Subí tu recibo», bajada (ver tabla), línea de pasos.
2. Hoja clara con la guía **«Para que salga bien»** (ícono tilde) y 3 consejos (ícono de línea + título en negrita + texto chico):
   - «Que entre completo» — «Las cuatro esquinas dentro de la foto, incluido el pie con los totales.» (ícono esquinas de encuadre)
   - «Luz pareja, sin sombras» — «Evitá el flash de frente: el brillo tapa los números.» (ícono sol)
   - «Apoyado y derecho» — «Sobre una mesa, sin dobleces y de frente, no en diagonal.» (ícono renglones)
3. Botones (sobre el oscuro): principal «Sacar foto» (ícono cámara; abre la cámara directo, `capture="environment"`) y secundario «Subir un PDF» (ícono hoja; acepta imagen o PDF).
4. Pie del panel (botón ancho): ícono reloj + «Ver mis recibos verificados» + etiqueta «Historial privado».

**P1b · archivo elegido** (mismo panel; cambia):
- Bajada «Ya tenemos el archivo. Cuando quieras, lo leemos.»
- En la hoja, arriba de la guía: tarjeta de archivo con ícono de hoja + nombre «recibo_sept_2026.pdf» + meta «412 KB · listo para leer».
- Botones: principal «Leer recibo» (ícono tilde) y secundario «Elegir otro».
- El pie «Ver mis recibos verificados» sigue.

**Espera (Leyendo / Verificando)** [JS]
- Kicker/título/bajada según tabla; línea de pasos.
- **Cronómetro**: aro circular que da una vuelta cada 45 s, en el centro «00:17» (monoespaciado) y rótulo «Segundos».
- **Tres fases** con punto, la activa animada y las anteriores marcadas hechas: «Abriendo el archivo» (0–6 s), «Reconociendo los conceptos» (6–16 s), «Comparando» (16 s+).
- Sin botones.

**P2 · Confirmá los datos** [JS] — dentro de la hoja, en este orden:
1. [COND alerta de adulteración] cartel: «**Atención:** algunos datos podrían estar alterados. Podés seguir igual — guardamos una copia del archivo para revisión.»
2. **Carátula "Lo que leímos"**: antetítulo «Lo que leímos», período «septiembre 2026» (o «Sin período»), empresa «Metalúrgica del Sur SA» (o «Empresa no reconocida»), [COND] línea «Neto impreso» «$1.284.530,00».
3. [COND recibo formato nuevo] etiqueta: «Formato nuevo · reforma laboral (Dto 407/2026)».
4. Tarjeta **«Datos del recibo»** (ícono hoja), grilla de 4 celdas rótulo/valor; si falta, el valor dice «no se leyó» (marcado como faltante):
   - «Empleado» «SOSA MARTIN»; «CUIL» «20-31456789-8»; «CUIT de la empresa» «30-71234567-9»; «Fecha de cobro» «03/10/2026».
5. Tarjeta **«Conceptos leídos (14)»**: una fila por línea (descripción o código a la izquierda, importe a la derecha; negativos en color de descuento). Ejemplos:
   - «Sueldo básico» «$1.250.000,00» · «Antigüedad» «$62.500,00» · «Presentismo» «$109.375,00» · «Jubilación» «-$156.406,25» · «Ley 19.032» «-$42.656,25» · «Obra social» «-$42.656,25» · «Cuota sindical UOM» «-$35.546,88».
   - Totales (bloque aparte, cifras en columna): «Total ingresos» «$1.421.875,00» · «Total descuentos» «$277.265,63» · [COND] «Reintegros» «$12.000,00» · «Total neto» «$1.144.609,37».
6. [COND formato nuevo con contribuciones] Tarjeta **«Contribuciones patronales»**, bajada «Las paga tu empleador. No se descuentan de tu sueldo ni bajan tu neto.»; filas «Seguridad social (16%)» «$227.500,00»…; última fila en negrita «Costo laboral total» «$1.763.125,00».
7. [COND conceptos nuevos] Bloque **«Conceptos nuevos detectados»**, texto: «Estos conceptos no estaban registrados. En los haberes, marcá si cada uno es remunerativo (si suma para calcular los aportes). Al continuar se agregan y quedan marcados para que el sindicato los revise.»
   - Por concepto: chip con descripción «Bono paz social», etiqueta de tipo «ingreso» / «descuento» / «reintegro», importe «$80.000,00».
   - [COND ingreso] debajo: «¿Remunerativo?» + conmutador **«Sí» / «No»** (uno activo).
   - [COND reintegro] debajo: «Plata que te devuelven: no suma a tu remuneración ni lleva aportes.»
8. Botones (sobre el oscuro): principal «Continuar con la verificación», secundario «Volver a empezar».

**P3 · Resultado** [JS]
1. Kicker «Paso 3 de 3», título («Todo en orden» / «Hay N diferencias»), bajada = período, línea de pasos.
2. **Veredicto** (caja verde si OK, roja si no): ícono tilde o triángulo de alerta + «Chequeamos 6 conceptos de tu recibo.» (singular «1 concepto»). Debajo, un renglón por cada:
   - diferencia [SRV], p. ej. «Cuota sindical UOM: esperado $35.546,88, figura $42.656,25 (diferencia $7.109,37).»; «El recibo no incluye 'Seguro de vida obligatorio'.»; «Suma de descuentos ($277.265,63) no coincide con el impreso ($279.000,00). Puede ser un error de lectura; conviene revisar la foto antes de reportar.»
   - alerta (estilo aviso) [SRV], p. ej. «No pudimos leer el importe de 1 línea(s) del recibo (Horas extra 50%), así que quedaron afuera de los cálculos. Si el resultado no te cierra, probá con una foto más nítida o con el PDF original.» / «No pudimos chequear Cuota sindical: la fórmula que cargó tu sindicato tiene un error de escritura. El resto del recibo se verificó igual. Conviene avisarle al sindicato.»
3. Tarjeta **«Lo que chequeamos»** (ícono renglones): una fila por concepto chequeado: ícono tilde (ok) o cruz (mal) + descripción + [COND] etiqueta «chequeo automático» (con tooltip «Este empleador todavía no tiene sus conceptos cargados en el sindicato: se identificó y chequeó automáticamente por tratarse de un aporte de ley.») + importe del recibo. Ej.: ✓ «Jubilación 11%» «$156.406,25»; ✓ «Ley 19.032 (PAMI) 3%» «$42.656,25»; ✗ «Cuota sindical UOM 2,5%» «$42.656,25».
4. Totales (mismo bloque que P2: Total ingresos / Total descuentos / [Reintegros] / Total neto).
5. [COND base aproximada] cartel ámbar: «El sindicato todavía no tiene cargado ningún concepto de haberes para este empleador, así que el remunerativo usado para los cálculos de arriba se tomó del total impreso en el recibo, no de conceptos verificados uno por uno.»
6. [COND resultado OK] cartel verde con texto + botón:
   - con retención: «**Retención de cuota sindical: $35.546,88.** Si querés, podés enviarle estos datos a tu sindicato para que te acredite como afiliado cotizante. Al enviarlo, compartís los datos de este recibo con tu sindicato — no se anonimiza.»
   - sin retención: «Si querés, podés enviarle los datos de este recibo a tu sindicato. Al enviarlo, compartís los datos de este recibo con tu sindicato — no se anonimiza.»
   - botón secundario «Enviar a mi sindicato» → «Enviando…» → «✓ Enviado a tu sindicato» (o «No se pudo enviar, probá de nuevo»).
7. Botones (sobre el oscuro): [COND con diferencias] principal «Reportar al sindicato» (→ «Enviando…» → se reemplaza por un **check animado** con «Enviado — el sindicato va a revisar tu caso»; si falla, cartel «No se pudo enviar el reporte. Probá de nuevo.») + secundario «Verificar otro recibo».

**P3 · Recibo ajeno**: veredicto rojo con [SRV] «Este recibo pertenece al CUIL 27-22222222-8, pero iniciaste sesión con el CUIL 20314567898. No se hizo ningún chequeo: subí tu propio recibo para verificarlo.» + botón «Volver a intentar».

**Error**: cartel rojo con el mensaje del servidor (p. ej. «No pudimos leer el recibo. Probá con una foto más nítida o subí el PDF original.») y, en chico debajo, «Código E-RECIBO-01» (o «Código E-INTERNO-00 · ref a1b2c3d4») + botón secundario «Volver a intentar». Mensaje genérico de respaldo: «No se pudo completar la operación.»

**Historial · Mis recibos verificados** (reemplaza a P1; sin marco oscuro)
1. Título de página «Mis recibos verificados».
2. Bajada «Historial privado: todo lo que verificaste, lo hayas enviado a tu sindicato o no.»
3. Cargando: spinner. Error: cartel «No pudimos cargar tu historial.» Vacío: «Todavía no verificaste ningún recibo.»
4. Lista [JS], una fila por recibo (tocable): título «septiembre 2026 · Unión Obrera Metalúrgica», fecha «2026-10-05 14:32», etiquetas: «Todo en orden» (verde) o «Con discrepancias» (rojo) + [COND] «Enviado» (verde) + [COND formato nuevo] «reforma» (violeta). Ej. 2: «agosto 2026 · Unión Obrera Metalúrgica» «2026-09-04 09:10» «Con discrepancias».
5. Botón secundario «Volver».
6. **Modal de detalle** (hoja): título «septiembre 2026 — Unión Obrera Metalúrgica», cerrar X; cuerpo: chips por línea (descripción + importe, los negativos en rojo), totales, diferencias y alertas del resultado.

### 3. Opcional / condicional
Toda la pestaña [MÓD recibos]. Condicionales: alerta de adulteración, formato nuevo (etiqueta + contribuciones), conceptos nuevos, reintegros, base aproximada, retención sindical, chequeo automático, «Enviado»/«reforma» en historial.

---

## T3 · Credencial `/app?tab=credencial`  [MÓD credencial]

### 1. Estados
- **A dibujar**: credencial generada, con foto, firma, QR y pie de contacto.
- **Pendiente** (el sindicato no generó el código): «N° credencial» dice «Pendiente», no hay QR ni contador, cambia la nota de abajo.
- **Sin foto**: no hay retrato de fondo. **Sin logo / sin firma / sin autoridad / sin dirección**: esos elementos no aparecen.
- **QR**: se renueva solo cada ~10 min; mientras se renueva queda translúcido; sin conexión puede pasar a «QR vencido» (en rojo).

### 2. Elementos obligatorios (en orden)
1. Título de página «Credencial».
2. **Tarjeta de credencial** (blanca, sombra, tres capas):
   - **Retrato de fondo**: la foto del afiliado en un círculo grande al centro, desaturada al 30% y con bordes difuminados [COND foto].
   - **Filigrana** (guilloche SVG del sindicato, colores apoyo/acento) por encima de la foto.
   - **Cabecera** (fondo `--marca-base`): logo del sindicato (máx. 46 px alto) [COND logo] + antetítulo «Credencial digital» + «Unión Obrera Metalúrgica».
   - **Cuerpo**:
     - «Afiliado» → «Martín Sosa» (o «—»).
     - «N° credencial» → «UNIONK7Q2M9XA» (5 letras del sindicato + 8 al azar) o «Pendiente».
     - Datos: «CUIL» «20314567898» · [COND] «DNI» «31456789» · [COND] «Vigencia» «31/12/2026».
   - **Parte inferior**:
     - Firma: imagen de la firma [COND firma] + línea + nombre de la autoridad «Juan Carlos Pérez» + cargo «Secretario General».
     - [COND credencial generada] **QR** (100×100, title «Escaneá para verificar esta credencial») + debajo [JS] «Se renueva en 9:42» (cuenta regresiva) / «QR vencido».
   - [COND dirección o teléfonos] **Pie**: «Alsina 485, CABA · (011) 4384-1111».
3. Nota centrada debajo:
   - generada: «Credencial digital emitida por Unión Obrera Metalúrgica. El QR se renueva solo: una captura de pantalla deja de verificar a los pocos minutos.»
   - pendiente: «Tu sindicato todavía no generó el código de tu credencial. El QR de verificación aparecerá cuando esté generado.»

### 3. Opcional
Pestaña entera [MÓD credencial] y solo con sindicato activo. Foto, logo, firma, autoridad/cargo, DNI, vigencia, pie de contacto y QR son condicionales.

---

## T4 · Mis Aportes (semáforo ARCA) `/app?tab=aportes`  [MÓD aportes]

### 1. Estados
- **A dibujar**: semáforo con datos (rojo o amarillo, que muestran todo: global + dos barras de 12 meses + leyenda).
- **Todavía no consultado** (nunca subió comprobante): luz gris, instrucciones y los dos accesos.
- **Todavía no consultado + señal temprana**: igual, con un cartel extra si el último recibo leído declara un depósito atrasado.
- **Leyendo el comprobante**: spinner + «Leyendo tu comprobante…».
- **Error**: cartel rojo con el mensaje (+ código) y botón «Volver a intentar».
- Colores globales posibles: **verde / amarillo / rojo / gris**.

### 2. Elementos obligatorios (en orden)
1. Título de página «Mis aportes».
2. Tarjeta blanca con cabecera:
   - antetítulo «Semáforo»; título «Estado de tus aportes»; bajada «Jubilación y obra social · últimos 12 meses».
3. **Estado "Todavía no consultado"** [JS]:
   - Luz gris con «—» + título «Todavía no consultado» + texto «Verificá en ARCA si tu empleador depositó tus aportes.»
   - [COND señal temprana del recibo] cartel: «**Señal temprana (no reemplaza a ARCA):** El recibo declara último depósito de aportes en 05/2026 (4 meses antes del período 09/2026). Puede indicar un atraso del empleador: conviene confirmarlo en ARCA.» [SRV]
   - Instrucción: «**Cómo funciona:** abrí ARCA, resolvé el "no soy un robot" y guardá la captura de la tabla. Después subila acá y armamos tu semáforo.»
   - Dos accesos grandes (tiles):
     - principal «1 · Consultar en ARCA ↗» (ícono flecha a externo; abre `serviciossegsoc.afip.gob.ar/MisAportes/...` en otra pestaña);
     - «2 · Subir captura de ARCA» (ícono subir; abre selector imagen/PDF con cámara).
4. **Estado con datos** [JS]:
   - **Global**: luz de color con símbolo (verde «✓», amarillo «~», rojo «!») + título y descripción [SRV]:
     - verde: «Todo al día» — «Tu empleador depositó jubilación y obra social todos los meses.»
     - amarillo: «Hay pagos parciales» — «Algunos meses figuran como pago parcial. Conviene revisarlo.»
     - rojo: «Hay meses sin aportar» — «Faltan aportes en algunos meses. Podés reportarlo al sindicato.»
     - gris: «Sin datos» — «Subí tu comprobante de ARCA para ver el estado.»
   - **Rubro «Jubilación»** + contador a la derecha «10/12 al día» + barra de 12 celdas (una por mes, con el número de mes adentro, p. ej. «10», «11», «12», «01»…«09»; tooltip con el período «09/2026»).
   - **Rubro «Obra social»** + «11/12 al día» + barra de 12 celdas.
   - Colores de celda: **pagado** verde `#2fa88f` · **parcial** amarillo `#e8b84b` · **impago / no_presentada / no_declarado** rojo `#d9685c` · sin dato gris `#eceae3`. («INFORMADO» de ARCA se registra como pagado; «NO INFORMADO» como impago.)
   - **Leyenda**: puntos «Pagado» · «Parcial» · «Impago / No presentada».
   - Fuente: «Datos de ARCA · consultado el 12/10/2026».
   - Botón secundario ancho «Actualizar con otra captura» (abre selector imagen/PDF).
5. Leyendo: spinner + «Leyendo tu comprobante…». Error: cartel con, p. ej., «Este comprobante es de otro CUIL…» + «Código E-APORTE-03» + botón «Volver a intentar».

### 3. Opcional
Pestaña entera [MÓD aportes]. Señal temprana [COND recibo leído con depósito atrasado ≥3 meses]. El semáforo NUNCA toma los colores del sindicato: verde/amarillo/rojo fijos.

---

## T5 · Trámites `/app?tab=tramites`  [MÓD tramites]

Cuatro vistas que se reemplazan dentro de la pestaña: **Inicio (bandeja)**, **Elegir tipo**, **Formulario**, **Detalle con chat**. Más el modal de mensaje/respuesta.

**Los 5 estados reales** (`db.ESTADOS_TRAMITE_LABEL`) y su pastilla:
| Clave | Nombre en pantalla | Colores (fondo / texto) | Barra de progreso (4 tramos) |
|---|---|---|---|
| iniciado | «Iniciado» | `#fdf3e7` / `#8a5a1a` (naranja) | ▶ · · · |
| en_tratamiento | «En tratamiento» | `#e8def5` / `#5b3d8a` (violeta) | ■ ▶ · · |
| espera_info | «A la espera de información del afiliado» (en la lista se acorta a «Esperan tu respuesta») | `#f8e5e2` / alerta (rojo) | ■ ⚠ · · (tramo 2 en color alerta) |
| respondido | «Respondido» | `#e3f2ee` / verde agua | ■ ■ ▶ · |
| terminado | «Terminado» | `#e3f2ee` / verde agua | ■ ■ ■ ■ |

### 1. Estados
- **Inicio**: cargando (spinner) / con trámites (con o sin tarjeta "Necesita tu atención") / vacío / error / filtro sin resultados / buscador abierto.
- **Elegir tipo**: cargando / lista / vacío / error.
- **Formulario**: normal / con errores por campo / con avisos / requisitos no cumplidos (sin campos) / enviando / sellado «Enviado».
- **Detalle**: cargando / con chat / terminado (sin responder) / no encontrado / error.
- **A dibujar**: Inicio con tarjeta de atención y 3 trámites; Formulario a medio completar con un error; Detalle con chat de 4–5 burbujas.

### 2. Elementos obligatorios

**Vista Inicio (bandeja)**
1. Título de página «Trámites».
2. Bajada «Formularios de tu sindicato y seguimiento de tus expedientes.»
3. [COND algún trámite con novedad] **Tarjeta "Necesita tu atención"** (oscura de marca, grano) [JS]:
   - antetítulo con punto: «Necesita tu atención»;
   - título del tipo «Subsidio por nacimiento»;
   - «UOMSN-2026-000042 · A la espera de información del afiliado»;
   - mensaje con avatar (ícono trámite): «Tu sindicato · hoy 07:40» + texto del último mensaje («Necesitamos la partida de nacimiento.»; o «Te mandó un formulario para iniciar.» / «Te mandó un adjunto.»), o si fue un cambio de estado: «Tu sindicato · ayer 16:20» + «Cambió el estado del trámite a "En tratamiento".»;
   - botones: «Responder» (principal, no si está terminado) y «Abrir el trámite».
4. Dos accesos grandes (tiles):
   - principal «Iniciar un trámite» (ícono +) con bajada [JS] «3 formularios disponibles» / «1 formulario disponible» / «Sin formularios por ahora» (mientras carga: «Elegí el formulario»);
   - «Buscar expediente» (ícono lupa) con bajada «Por número de expediente».
5. [COND buscador abierto] campo de texto, placeholder «Ej: F01AEFIP-2026-000123» + botón «Buscar» (Enter también) + línea de error (vacía por defecto).
6. **Filtros** (chips con contador) [JS, solo si hay trámites]: «Todos 5» · «En curso 3» · «Terminados 2» (uno activo).
7. **Lista** [JS], una tarjeta por trámite (tocable → detalle):
   - [COND novedad] punto de novedad antes del título; título del tipo; número de expediente debajo;
   - pastilla de estado a la derecha (tabla de arriba);
   - barra de progreso de 4 tramos;
   - pie: a la izquierda «**Hay novedades del sindicato**» / «**Esperan tu respuesta**» / «**Tu sindicato:** Ya recibimos tu pedido.» / «**Vos:** Adjunto la partida.» / «Presentado» / «Cerrado»; a la derecha «hoy 07:40» / «ayer 16:20» / «26/08».
   - Ej.: «Subsidio por nacimiento» · «UOMSN-2026-000042» · «Esperan tu respuesta» · pie «Hay novedades del sindicato» · «hoy 07:40».
   - Ej.: «Kit escolar 2027» · «UOMKE-2026-000318» · «Iniciado» · «Presentado» · «03/10».
   - Ej.: «Reintegro por anteojos» · «UOMRA-2026-000101» · «Terminado» · «**Tu sindicato:** Aprobado, se acredita con el sueldo.» · «12/09».
8. Cargando: spinner. Vacío: «Todavía no presentaste ningún trámite.» Filtro vacío: «Nada que mostrar con este filtro.» Error: «No pudimos cargar tus trámites.»

**Vista Elegir tipo**
1. Caja con cabecera: título «Iniciar un trámite», bajada «Elegí qué tipo de trámite querés presentar.»
2. Lista [JS] de tarjetas: título en negrita «Subsidio por nacimiento» + código chico «UOMSN»; «Kit escolar 2027» / «UOMKE»; «Reintegro por anteojos» / «UOMRA».
3. Vacío: «Tu sindicato todavía no cargó ningún tipo de trámite.» Error: «No pudimos cargar los tipos de trámite.»
4. Botón secundario «Volver».

**Vista Formulario**
1. **Carátula de marca**: título del tipo «Subsidio por nacimiento»; meta: código «UOMSN» + «EXP — se numera al enviar» (al enviar pasa a «EXP UOMSN-2026-000043»).
2. [COND error general] cartel rojo: «Completá: DNI del bebé, Partida de nacimiento» / errores del servidor uno por línea / «No se pudo enviar el trámite. Probá de nuevo.»
3. [COND requisitos no cumplidos] caja: «**Por ahora no podés iniciar este trámite:**» + lista de mensajes del sindicato (p. ej. «Tenés que tener al menos 6 meses de antigüedad en el padrón.», «Ya pediste este subsidio.»). En ese caso no se muestran campos, progreso ni botón Enviar.
4. **Progreso**: «Completaste **3 de 7**» + barra que se llena.
5. **Campos** [JS] (grilla de 12 columnas; ancho «completo» / «mitad» / «tercio»; en teléfono todos a ancho completo). Por campo: rótulo + « *» si es obligatorio, control, tilde «✓» (o «✗») a la derecha cuando valida, línea de error (rojo) y línea de aviso (ámbar). Los 10 tipos de control:
   - **texto**: input; placeholder vacío o «8 caracteres» si tiene longitud exacta; tope de caracteres.
   - **numero**: input decimal, placeholder «Ej: 1234» o «Ej: 1234.56».
   - **fecha**: selector de fecha.
   - **seleccion**: select con «Elegí una opción» + opciones.
   - **opcion_unica**: radios, una por opción.
   - **multiple**: casillas, una por opción.
   - **booleano**: una casilla con el rótulo al lado (sin rótulo arriba).
   - **archivo**: botón «📎 Elegir archivo» + nombre del archivo elegido debajo; acepta las extensiones que fija el sindicato.
   - **calculado / extraído**: input prellenado por el sistema, placeholder «Se completa solo»; debajo una nota: «Este dato está registrado en tu perfil. Si lo cambiás acá, se actualiza en el sistema.» o «Este valor lo calcula el sistema. Si lo cambiás, queda anotado en el trámite para que lo revisen.» o «Este dato lo tiene registrado el sindicato. Si lo cambiás, queda anotado en el trámite para que lo revisen.» (se resalta al tocarlo).
   - **separador**: línea horizontal.
   - Ejemplo de formulario: «Nombre del bebé *» (texto) · «Fecha de nacimiento *» (fecha) · «DNI del bebé *» (número, mitad) · «Parentesco *» (selección: Padre / Madre / Tutor) · «Edad del afiliado» (calculado: «41») · «Partida de nacimiento *» (archivo) · «Declaro que los datos son verdaderos» (booleano).
   - Mensajes de error/aviso: los escribe el sindicato (p. ej. «La fecha no puede ser posterior a hoy.»); en vivo, el servidor puede responder «Revisá este dato.».
6. Botón principal «Enviar trámite» (→ «Enviando…» → «Enviado ✓»; tiembla si hay errores y lleva al primer campo con error).
7. **Sello** al enviar, sobre el formulario: «Enviado» + «EXP UOMSN-2026-000043 · 23/10/2026»; a los 2,2 s abre el detalle.
8. Botón secundario «Cancelar».
- Errores de apertura (alert del navegador): «Ese formulario ya no está disponible. Consultale a tu sindicato.» / «No se pudo abrir el formulario. Probá de nuevo.»

**Vista Detalle**
1. Caja con cabecera: título = número de expediente «UOMSN-2026-000042», bajada = tipo «Subsidio por nacimiento».
2. Fila «Estado» + pastilla con el nombre completo («A la espera de información del afiliado»).
3. Sección «DATOS PRESENTADOS» (rótulo en mayúsculas): una fila por respuesta, rótulo gris a la izquierda y valor a la derecha («Nombre del bebé» «Lucía Sosa»; «Fecha de nacimiento» «2026-09-30»; archivos como enlace «📎 archivo»).
4. Sección «CONVERSACIÓN» — **chat estilo WhatsApp**, cronológico [JS]:
   - **Burbuja del sindicato** (izquierda): avatar = logo del sindicato (o círculo con iniciales «UOM» en color base); remitente «Tu sindicato»; texto; [COND] tarjeta de formulario: rótulo «Formulario para iniciar» + «📋 Declaración jurada de convivencia» + botón «Iniciar este trámite» (o, si se dio de baja, «📋 Formulario ya no disponible»); [COND el mensaje cambió el estado] línea «En tratamiento»; meta: clip si tiene adjunto + hora «07:40».
   - **Burbuja propia** (derecha): avatar = foto del afiliado (o ícono persona); remitente «Vos»; texto o «📎 Adjunto»; hora.
   - **Línea de sistema** (centrada): «Trámite presentado por el trabajador (UOMSN-2026-000042). · 10:02»; pase entre áreas: «Pasó de Mesa de entradas a Acción Social. Motivo: corresponde a subsidios · 11:15».
   - **Tarjeta de trámite encadenado** (como burbuja propia): rótulo «Iniciado desde el trámite» o «Trámite iniciado desde este chat» + «⇄ **UOMDJ-2026-000007** · Declaración jurada de convivencia» + botón «Abrir el trámite».
   - Vacío: «Todavía no hay mensajes en este trámite.»
   - Ejemplo de hilo: sistema «Trámite presentado…· 10:02» → sindicato «Recibimos tu pedido, lo estamos revisando.» + «En tratamiento» · 15:30 → sindicato «Necesitamos la partida de nacimiento.» + «A la espera de información del afiliado» · 07:40 → vos «Adjunto la partida.» 📎 · 08:12.
5. Pie: botón ancho «Escribir una respuesta a tu sindicato…»; o, si está terminado, «Trámite terminado -- no se pueden agregar más mensajes.»
6. Botón secundario «Volver».
7. No encontrado: «No encontramos un trámite tuyo con ese número.» Error: «No pudimos cargar el trámite.»

**Modal de mensaje / respuesta** (comparte la hoja del modal de recibos)
- Título: «Tu sindicato» / «Vos» (al tocar una burbuja) o «Responder»; cerrar X.
- [COND abierto desde una burbuja] remitente + fecha completa «Tu sindicato · 2026-10-23 07:40», texto completo, [COND] enlace adjunto «📎 partida.pdf», [COND] tarjeta de formulario.
- Compositor (si no está terminado): textarea 3 renglones, placeholder «Responder a tu sindicato…»; botón «📎 Adjuntar» + nombre del archivo; botón principal «Enviar». Error: alert «No se pudo enviar la nota.»
- Terminado: «Trámite terminado -- no se pueden agregar más mensajes.»

**Entradas desde afuera**: `?tab=tramites&formulario=<id>` abre el formulario directo (desde una notificación, noticia o beneficio); `?tramite=<EXP>` abre el detalle (desde la notificación push «Novedad en tu trámite…»).

### 3. Opcional / condicional
Pestaña entera [MÓD tramites]. Tarjeta de atención [COND novedad]; buscador [plegado por defecto]; filtros [COND ≥1 trámite]; requisitos [COND el formulario los tiene]; campos calculados [COND]; tarjeta de formulario en el chat [COND el sindicato la mandó]; pases y encadenados [COND]; compositor [COND no terminado].

---

## Anexo · Pestañas de /app que no son de estas 5 (para que la tira esté completa)
- **Novedades** [MÓD noticias]: título «Novedades», hilo con un hito por día («28/09», ícono hexágono) y por noticia: avatar (foto o ícono megáfono), título, hora «10:15», bajada; tocar → modal de noticia. Vacío: ícono grande + «Novedades» + «Acá vas a ver los mensajes y avisos de tu sindicato.<br>Muy pronto.»
- **Capacitación** [MÓD capacitacion]: título «Capacitación», tarjeta «Guía» / «Entendé tu nuevo recibo de sueldo» + texto fijo de la ley (4 secciones, aporte vs. contribución, qué mirar).
- **Encuestas** [MÓD encuestas]: tarjetas de encuesta, formulario, revisión y «¡Gracias por participar!».
