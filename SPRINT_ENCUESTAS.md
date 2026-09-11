# SPRINT ENCUESTAS — encuestas anónimas y nominales al padrón

Plan acordado con Sd el 2026-09-11, **antes de tocar código**, decisión por
decisión. Igual que `SPRINT_AREAS_V2.md`: documenta el plan **tal cual se
acordó** y no se actualiza retroactivamente. La fuente de verdad sobre qué
está hecho es "Estado actual" de CLAUDE.md.

## Qué es

Un módulo habilitable para que el sindicato le pregunte cosas a su padrón y
lea las respuestas agregadas. El admin arma la encuesta con un constructor
parecido al de Trámites, elige si es **anónima** o **nominal**, la dirige a
un grupo de afiliados con los criterios que ya existen (CUIL, empresa,
seccional, provincia), la comunica por Notificación y/o Noticia, y sigue los
resultados en un dashboard con gráficos y filtros.

No es un trámite: nadie la responde para pedir algo, no cae en ningún área,
no tiene expediente ni estados. Se cuenta.

## Premisas

1. **Solo esta funcionalidad.** Nada más del backlog entra a esta tanda.
2. **Nada de lo que ya anda se toca.** Trámites, Noticias y Notificaciones
   quedan como están; Encuestas se cuelga de las dos últimas con una
   columna `encuesta_id`, mismo criterio que `formulario_id` (int sin FK).
3. **Opt-in.** `"encuestas"` queda FUERA de `MODULOS_INICIALES`: ningún
   sindicato lo estrena sin pedirlo.
4. **El anonimato es una promesa verificable, no un cartel.** Si no se
   puede demostrar con un test, no se promete.

## Decisiones tomadas

Numeradas igual que las preguntas con las que se acordaron.

### Anonimato

**N1. Los cortes de una anónima los elige el admin, y hay umbral.** Una
encuesta anónima guarda junto a cada respuesta **solo** los atributos que el
admin tildó al crearla (seccional, provincia, empleador). El disclaimer que
ve el afiliado se arma solo con esa lista. El dashboard **oculta todo grupo
con menos de N respuestas** (N=5 por defecto, configurable por plataforma).
Así conviven una encuesta sensible sin ningún corte y una operativa con
todos, en el mismo módulo.

**N2. Padrón y urna, separados y sin vínculo posible.** Dos tablas: una dice
QUIÉN participó, la otra guarda las respuestas sin identidad. Nadie, ni con
acceso a la base, puede unirlas (ver "Cómo se sostiene el anonimato"). Es lo
que permite impedir el voto doble, medir participación real y mandar
recordatorio solo a los que faltan, sin saber qué contestó nadie.

**N2b. El disclaimer dice la verdad.** No se promete "ningún dato personal
será guardado", porque sería falso. Se promete lo que el sistema cumple:
*"Queda registrado que participaste, nunca qué respondiste. Tu respuesta no
se puede vincular con vos ni con tu computadora."* Lo segundo se cumple
solo: la app no guarda IP ni user-agent en ningún lado.

**N4b. En una encuesta anónima no se puede adjuntar archivos.** Una foto
lleva metadatos (modelo de teléfono, a veces GPS) y un PDF lleva autor: es
la forma más fácil de romper el anonimato sin darse cuenta. El tipo de
pregunta "archivo" no existe en las anónimas.

### Modelo y constructor

**N3. Tablas propias, no las de Trámites.** `TipoTramite` arrastra código de
expediente, área destino obligatoria, pases, estados, chat y validaciones,
nada de lo cual aplica; y `RespuestaTramite` cuelga de un `Tramite` que
cuelga de un CUIL, lo que rompería el anonimato en la raíz del modelo. Se
reusan el **vocabulario** de `CampoTramite.tipo_dato`, el criterio de
`retirado` y el **constructor JS con vista previa**, no las tablas. Mismo
criterio explícito que ya rige entre trabajador y empleador: duplicar antes
que compartir.

**N4. Tipos de pregunta.** Los ocho de Trámites (texto, número, fecha,
selección, opción única, múltiple, sí/no, separador) más dos:
- **escala 1–5** tipo Likert, con etiquetas en los extremos; se grafica como
  barra apilada y da un promedio comparable entre preguntas y entre cortes;
- **ranking**, arrastrar para ordenar opciones por prioridad.

**N5. Con respuestas cargadas, la encuesta se congela.** Se pueden editar
título, descripción, el texto de los avisos, estirar la fecha de cierre y
**corregir erratas de redacción** de una pregunta o una opción. NO se pueden
agregar, borrar ni reordenar preguntas, ni cambiar su tipo ni el juego de
opciones. Como el sistema no puede distinguir una errata de un cambio de
sentido, cada edición de texto **queda registrada con fecha y usuario** y la
pantalla lo avisa: *"esto no cambia las respuestas ya recibidas"*.

**N6. El estado no se guarda, se deriva** de `publicada` + las dos fechas:
borrador → programada → abierta → cerrada, igual que `noticia_vigente()`.
Evita la fila que quedó en "abierta" porque nadie corrió el proceso que la
cerraba.

**N23. Duplicar, con linaje y comparación en el tiempo.** Botón para copiar
la estructura completa y relanzar, guardando de qué encuesta salió cada
copia (`origen_id`). Con eso, la pantalla de **evolución**: la misma
pregunta a lo largo de las tomas sucesivas. Es lo que convierte un dato
suelto en una herramienta de gestión ("esto veníamos midiendo hace un año").

### Ventana, público y respuesta

**N7. Cerrar antes sí, prorrogar sí, reabrir nunca.** Una encuesta que se
reabre después de ver los resultados deja de ser confiable, y en un gremio
con internas eso se discute. Si hace falta más gente, se duplica y se lanza
una segunda ronda, que queda como un hecho separado y auditable. Prórrogas y
cierres anticipados van al historial.

**N8. La hora es la de Buenos Aires.** Cierra a las 23:59 del día de
`fecha_hasta`, inclusive, con zona horaria explícita (`fechas.py`). No se
usa `date.today()` ni `datetime.now()`: el servidor corre en UTC.

**N9. Solo trabajadores.** Las encuestas a empleadores duplicarían el módulo
entero (otra tabla de participantes, otras rutas, otro dashboard) y además
son otro producto: la respuesta de una empresa no es anónima en los hechos.
Queda anotado para más adelante.

**N10. El padrón se fija al publicar.** Se resuelven los CUIL destinatarios
en el momento de publicar y se guardan, igual que hace `Notificacion`. Solo
esa gente responde. Es lo que hace que "respondieron 620 de 1.000" signifique
algo: esos 1.000 son siempre los mismos.

**N11. Nadie edita su respuesta**, ni en nominal ni en anónima. Una sola
regla para los dos modos. En su lugar, **pantalla de revisión antes de
enviar**, que es lo que de verdad evita los arrepentimientos.

**N12. Los resultados al afiliado son un tilde por encuesta.** Si está
tildado, al cerrarse ve los **totales generales solamente** — nunca los
cortes, que es por donde se identifica gente.

### Comunicación

**N13. Paso guiado al publicar, salteable.** Publicar abre un último paso con
la notificación y la noticia ya redactadas y editables. Evita el olvido más
caro: publicar una encuesta y que nadie se entere. **La notificación va
exactamente al padrón fijado de la encuesta**, no a un criterio elegido
aparte: si no, "leídas / no leídas" se mediría contra un universo distinto
al de "respondieron" y los dos números del dashboard no se podrían comparar.
La Noticia es otra cosa: es pública en la portada y se dirige por seccional,
como hoy.

**N14. Recordatorio manual, con freno.** Botón en la ficha, que antes de
mandar avisa a cuánta gente le va a escribir, lleva la cuenta de los ya
enviados y **no deja mandar más de uno por día**. Funciona igual en anónimas
(se le escribe a quien no participó, sin saber qué respondió nadie).

**N15. Una encuesta puede tener varias notificaciones** (lanzamiento y
recordatorios). El dashboard las muestra por separado y sumadas.

### Permisos

**N16. Se habilita con los ejes que ya existen, más un atajo.** Plataforma le
vende el módulo al sindicato; el Super Admin reparte las secciones. El atajo
"Habilitar Encuestas a esta seccional" tilda la sección en las áreas de esa
seccional de un clic, y el detalle por área sigue disponible. Si el
sindicato no tiene el módulo, el atajo **no existe**: ya lo garantiza
`permisos.secciones_de_modulos()`, y `calcular_efectivos()` lo intersecta de
nuevo al final.

**N17. Dos secciones**, mismo criterio que Trámites:
- `encuestas` — crear, publicar y comunicar;
- `encuestas_resultados` — ver el dashboard y exportar.

**N18. La seccional ve las encuestas centrales recortadas a su gente.** Un
Admin de Seccional con permiso ve la encuesta nacional con los resultados
filtrados a su propia seccional cuando ese corte existe, y el total general
cuando la anónima no lo guarda. El umbral N se le aplica igual que a
cualquiera. Crear y dirigir ya vienen recortados por `alcance_seccional`
(N10 de Áreas V2): Prensa de Córdoba no le puede escribir a Rosario.

### Pantallas y datos

**N19. Estética propia, por forma y por color.** Diferenciar solo por color
es frágil (brillo bajo, luz de sol, daltonismo). Trámites es "Expediente"
—lomo numerado, sellos, carátula—; Encuestas es lo opuesto: **tarjeta limpia
con barra de avance**, una pregunta por bloque, y cierre con el conteo de
participación en vez de un sello. El color sale de la marca del sindicato,
usando `color_acento` y `color_secundario` (Trámites usa los oscuros).

**N22. El dashboard abre con cuatro indicadores**, antes de cualquier
gráfico: **participación** (620 de 1.000), **avisos leídos** (820 de 1.000),
**ritmo** (curva de respuestas por día) y **estado**. Los dos primeros solo
sirven juntos: leyeron 82% y respondió 20% significa que el problema es la
encuesta y un recordatorio no lo arregla; leyeron 30% y de esos respondió
casi todo significa que el problema es el canal y el recordatorio lo
resuelve. Debajo, los gráficos por pregunta con filtros por seccional,
empresa y provincia.

**N20. Exportar: nominal completo, anónima agregada, y queda registrado.**
En las nominales, CSV con una fila por persona (nombre, CUIL, respuestas):
es lo que el afiliado aceptó al responder una encuesta que dice "nominal" en
la cara. En las anónimas, **solo conteos y porcentajes con el umbral ya
aplicado**, nunca fila por respuesta — si no, cualquiera abre la planilla,
filtra "Rosario + Empresa X" y se queda con dos filas que identifican a dos
personas: el umbral que protege la pantalla no protege nada si el archivo
sale crudo. **Cada descarga se registra** (quién, cuándo, qué encuesta,
cuántas filas) y se ve en el historial de la encuesta, para poder
diagnosticar cualquier fuga.

**N21. Cuatro tests de privacidad** (ver más abajo).

## Cómo se sostiene el anonimato

Lo que hace que padrón y urna no se puedan cruzar no es una promesa, es la
forma de las tablas:

1. **Las filas del padrón se crean al PUBLICAR**, una por destinatario, y
   responder solo prende un booleano. Su orden de `id` es el del padrón, no
   el de las respuestas.
2. **La urna no guarda hora, solo el día.** Sin timestamp fino no hay forma
   de ordenar las respuestas en el tiempo para alinearlas con nada.
3. **El padrón no guarda cuándo respondió cada uno.** La curva de ritmo del
   dashboard sale del día que guarda la urna, no del padrón.
4. **La urna no tiene ninguna columna que apunte a una persona**: ni CUIL,
   ni id de participante, ni sesión.
5. Los atributos de corte que la urna sí guarda son los que el admin
   habilitó, y el umbral N los protege en pantalla y en el CSV.

## Modelo de datos

Tablas nuevas (nombres tentativos, se cierran en la Fase 0):

- **`Encuesta`** — sindicato_id, titulo, descripcion, `modo`
  ("anonima"|"nominal"), `cortes` (JSON: subconjunto de seccional /
  provincia / empleador), `umbral_minimo` (default de plataforma),
  fecha_desde, fecha_hasta, `publicada`, `cerrada_en`, `mostrar_resultados`,
  criterio + criterio_valores (a quién se dirigió), cantidad_destinatarios,
  usuario_id, seccional_id (de quien la creó), `origen_id` (linaje), creada.
- **`PreguntaEncuesta`** — encuesta_id, orden, etiqueta, tipo_dato,
  opciones, escala_min/escala_max + etiquetas de los extremos, ancho,
  obligatorio.
- **`RespuestaEncuesta`** (la urna) — encuesta_id, pregunta_id,
  opcion_indice, posicion (ranking), valor_texto/valor_numero/valor_fecha,
  `dia`, y los atributos de corte habilitados. **Sin identidad, sin hora.**
- **`EncuestaParticipante`** (el padrón) — encuesta_id, cuil, `respondio`.
  Creado al publicar.
- **`EventoEncuesta`** (el historial) — encuesta_id, usuario_id, evento
  (edicion | prorroga | cierre | recordatorio | descarga), detalle, fecha.

Cambios chicos en lo existente:

- `Noticia.encuesta_id` y `Notificacion.encuesta_id` (int sin FK, mismo
  criterio que `formulario_id`).
- `modulos.MODULOS["encuestas"] = "Encuestas"`, fuera de `MODULOS_INICIALES`.
- `permisos.SECCIONES`: `encuestas` y `encuestas_resultados`, grupo
  "Comunicación", módulo requerido `encuestas`.
- `main.PERMISOS_RUTAS`: todas las rutas nuevas, clasificadas. El gateo es
  fail-closed: una ruta que nadie clasifique se rechaza sola.

## Fases

Bloques chicos, cada uno probado de verdad antes de seguir.

**Fase 0 — Cimientos.** Modelo, migración de Alembic, módulo, las dos
secciones de permisos y las rutas declaradas. Nada visible todavía.
*Tests:* modelo y migración; que el módulo apagado esconda y rechace; que
ninguna ruta nueva quede sin clasificar.

**Fase 1 — Constructor.** Pestaña Encuestas en `/admin`, alta y edición, los
diez tipos de pregunta, vista previa en vivo, congelado con erratas.
*Tests:* alta y edición, congelado, registro de erratas.

**Fase 2 — Responder.** Pantalla del trabajador con la estética propia,
disclaimer armado según los cortes, revisión antes de enviar, padrón y urna,
una sola vez por persona.
*Tests:* privacidad 1 y 2; una sola respuesta; ventana de fechas.

**Fase 3 — Publicar y comunicar.** Paso guiado, notificación al padrón
fijado, noticia, recordatorio con freno, cierre anticipado y prórroga.
*Tests:* el padrón de la notificación es el de la encuesta; el freno del
recordatorio; nadie fuera del padrón puede responder.

**Fase 4 — Dashboard.** Los cuatro indicadores, gráficos por pregunta
(Chart.js ya vendoreado), filtros por seccional, empresa y provincia,
umbral aplicado en el SQL, recorte por seccional (N18).
*Tests:* privacidad 3; agregados correctos; aislamiento entre sindicatos.

**Fase 5 — Exportar, duplicar, evolución.** CSV nominal y agregado con su
registro de descargas, duplicado con linaje y pantalla de comparación entre
tomas.
*Tests:* privacidad 4; el linaje; la comparación.

**Fase 6 — Demo y cierre.** Serie de tres tomas sintéticas en
`cargar_demo.py` para que la evolución se vea funcionando desde el día uno,
versión en `version.py`, CLAUDE.md e HISTORIAL.md.

## Los cuatro tests de privacidad (N21)

1. **Ninguna ruta de una encuesta anónima devuelve un CUIL**, ni anidado en
   un JSON. Se recorren todos los endpoints del módulo.
2. **Padrón y urna no se pueden unir**: la urna no tiene ninguna columna que
   lleve a un participante, y el orden de inserción no alcanza para
   reconstruir quién contestó qué.
3. **El umbral se aplica en el SQL, no en el frontend**: se pide el endpoint
   con un corte de 3 respuestas y tiene que venir vacío del servidor.
4. **El CSV de una anónima nunca trae filas individuales**, aunque se lo
   pida a mano con los parámetros cambiados.

Es el mismo criterio que ya rige en `test_dashboard.py`, donde el CASE que
esconde nombre y CUIL está en el SQL y no en la pantalla.

## Lo que NO entra en esta tanda

- Encuestas a **empleadores** (N9).
- **NPS** y preguntas **matriz** (N4).
- **Reabrir** una encuesta cerrada (N7).
- **Agregar preguntas** a una encuesta con respuestas (N5).
- Un **toggle de módulo por seccional** como tercer eje (N16).
