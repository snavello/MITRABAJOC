# PLAN — El Admin de Seccional acotado a su seccional en TODO el panel

Fecha: 2026-10-17. Origen: SDN probó en Pruebas un Admin de Seccional de La
Bancaria (Lomas de Zamora) y lo vio operar sobre todo el sindicato en
Noticias, Trámites y Notificaciones. Este plan sale de una **auditoría con
datos** (lote de La Bancaria: 6 seccionales, 100 afiliados, 2.000 trámites,
200 notificaciones, 30 noticias, 20 beneficios), hecha con un admin de
seccional creado por la ruta real, comparando sección por sección contra el
administrador general. No se tocó código de alcance: solo se midió.

La regla a cumplir ya está escrita (SPRINT_AREAS_V2.md, N3 y N10): el Admin
de Seccional es "el admin grande en chiquito", y **una sola regla de alcance
(`db.alcance_seccional`) vale para escribir Y para ver**. Hoy se cumple en
la mitad del panel y no en la otra mitad.

## 1. Lo que se midió

### Ya recorta bien (no se toca)
| Sección | Qué hace hoy |
|---|---|
| Trámites recibidos | Bandeja, contador y detalle recortados por los CUIL de su seccional (`_recortar_tramites`). 431 de 2.000 trámites; el ajeno da 403. |
| Notificaciones | Historial (89 de 200), destinatarios y envío recortados; un criterio fuera del alcance se descarta. |
| Reportes | Listado y detalle con alcance (389 de 1.597). |
| Encuestas | N18: lista, resultados, cruce, evolución y exportación con la seccional impuesta. |
| Listas | Solo las de su seccional; no carga una "para todo el sindicato". |
| Seccionales | Ve y edita solo la suya; crear, borrar y `ve_todas` son del general. |
| Áreas y Usuarios | Solo su seccional (lo que SDN ya vio bien). |
| Noticias y Beneficios, ALTA | Los destinos se fuerzan a su alcance: lo que publica va solo a su seccional. |
| Trabajadores, acciones sobre una fila ajena | Editar, baja, credencial, confirmar identidad y restablecer clave de un afiliado de otra seccional: rechazados. |

### Ve o puede todo (los agujeros)
| # | Sección | Lo medido | Gravedad |
|---|---|---|---|
| A1 | Trabajadores, listado | Ve el padrón entero (100 de 100), con nombre, domicilio y nivel de cada afiliado de las otras seccionales. | Alta: dato sensible (afiliación sindical, Ley 25.326). |
| A2 | Trabajadores, alta manual | Puede dar de alta un afiliado EN OTRA seccional (quedó en la seccional 9 siendo de la 14). El `<select>` le ofrece todas. | Media. |
| A3 | Trabajadores, carga masiva | Una línea con el nombre de otra seccional entra ahí. | Media. |
| B1 | Noticias y Beneficios, listado | Ve las 30 noticias y los 20 beneficios de todo el sindicato. | Baja (son publicaciones), pero rompe la regla. |
| B2 | Noticias y Beneficios, editar | Edita una publicación de OTRA seccional y, al guardarla, la redirige a la suya (los destinos se reescriben con su alcance). | Alta: altera comunicación ajena. |
| B3 | Noticias y Beneficios, borrar | Borra una publicación de otra seccional o global. | Alta. |
| C1 | Trámites, formularios | Crea un formulario GLOBAL (seccional vacía = sin chequeo). | Alta: le llega a todos los afiliados. |
| C2 | Trámites, formularios | Edita un formulario global (título, campos, destino, mapa). | Alta. |
| C3 | Trámites, formularios | Borra un formulario global sin trámites. | Alta. |
| D1 | Panel Sindical (v1 y v2) | Indicadores, gráficos, explorador, mapa y filtros de TODO el sindicato (5.000 recibos, 2.000 trámites). El Asistente también. | Alta. |
| E | Empleadores, sus notificaciones y trámites | Ve y opera todo. `Empleador` no tiene seccional (N11: quedó fuera de Áreas V2 a propósito). | Decisión pendiente. |
| F | Conceptos, Reglas, Aprendizaje, Convenio | Son el catálogo del sindicato, sin seccional; el admin local los edita. | Decisión pendiente. |

**Sobre "ve todos los trámites" en Pruebas.** En el código la bandeja SÍ
recorta. Si en Pruebas ese usuario ve todos, hay que mirar dos cosas en el
panel de La Bancaria: si la seccional Lomas de Zamora tiene tildado "ve
todas" (en Seccionales), que es la excepción prevista y le da alcance total,
o si el usuario quedó como administrador general. Las dos se corrigen desde
el panel, sin código. Lo que sí está roto por código es la tabla de arriba.

## 2. Principios para no romper nada

1. **Una sola regla**: `db.alcance_seccional(uid)` (None = todo, `{id}` =
   esa, `set()` = nada). No se inventa una segunda. Los bloques solo la
   APLICAN donde falta, con los dos helpers que ya existen: `_alcance_de` /
   `_en_alcance` para leer y `_exigir_alcance_seccional` para escribir.
2. **El recorte va en la consulta**, nunca en la plantilla (el HTML viaja
   entero y se lee con Ver código fuente). Es lo que ya hacen Encuestas,
   Listas y Usuarios.
3. **Fail-closed**: una fila SIN seccional (noticia "a todas", formulario
   global, afiliado sin seccional) la alcanza solo quien tiene alcance
   total. Un admin local la VE si le llega (una noticia a todas le llega) y
   NO la toca. Es la regla de `_en_alcance` tal cual está.
4. **El administrador general y las seccionales con `ve_todas` no cambian
   en nada.** Cada bloque lleva el test "el general sigue viendo todo"
   junto al "el local ve solo lo suyo". Es el contrapeso de
   `test_areas_seccional.py`.
5. **El usuario de área recibe lo mismo**: usa la misma regla, así que hoy
   también ve el padrón entero si su área tiene Trabajadores. Se arregla
   solo con estos bloques.
6. **Sin migraciones**: ningún bloque cambia el modelo. Solo consultas,
   rutas y plantilla. Por eso se puede ir bloque por bloque, cada uno un
   PR con sus tests, y volver atrás uno sin tocar los otros.
7. **Un test que no deje volver a abrir el agujero**: un registro
   `ALCANCE_RUTAS` en los tests, con cada ruta `/admin/*` clasificada
   (recorta por seccional / es del sindicato entero / no aplica), que falla
   si aparece una ruta nueva sin clasificar. Mismo patrón fail-closed que
   `PERMISOS_RUTAS` y `test_cuit_puertas.py`.

## 3. Bloques, en orden

### Bloque 0 — La red: `test_alcance_seccional_panel.py`
Un solo archivo con una fixture chica (un sindicato, dos seccionales, un
general, un local, dos afiliados, una noticia por seccional y una global, un
formulario global y uno local, recibos y trámites de cada uno) y el registro
`ALCANCE_RUTAS`. Arranca con los agujeros marcados `xfail` y cada bloque
los va pasando a verde. Así el avance se mide y el final se ve. Además el
script de la auditoría se guarda en `docs/chat/2026-10-17-auditoria-alcance.md`
con los números de hoy, para repetirlo contra el lote al terminar.

### Bloque 1 — Trabajadores (A1, A2, A3). Admin 0.57.x
- `db.padron_del_sindicato(s, sid, alcance=None)`: el `WHERE` suma
  `seccional_id IN alcance` cuando hay alcance; `set()` devuelve vacío. Es
  la única lectura del padrón, así que recorta la pantalla, el "Dar usuario
  del panel" y lo que la use mañana. Plataforma (`/plataforma/trabajadores`)
  sigue llamando sin alcance.
- Alta manual: la seccional elegida pasa por `_exigir_alcance_seccional`;
  para un admin local, seccional vacía = **la suya** (no puede crear "sin
  seccional": nadie acotado la alcanzaría). El `<select>` del formulario
  muestra `seccionales_visibles` en vez de `seccionales`.
- Carga masiva: una línea cuya seccional cae fuera del alcance queda
  OMITIDA y se informa con su línea (como las incompletas); sin seccional,
  la suya. "Georreferenciar pendientes" sigue siendo del sindicato: corre
  en segundo plano y no muestra filas.
- Lo que NO cambia: editar/baja/credencial/confirmar/restablecer ya están.
- Tests: local ve N de M; no crea fuera; masiva omite y dice cuántas; el
  general sigue igual; usuario de área con Trabajadores ve solo su seccional.

### Bloque 2 — Noticias y Beneficios (B1, B2, B3). Admin 0.58.x
- Lectura: `noticias_del_sindicato(sid, alcance)` /
  `beneficios_del_sindicato(sid, alcance)`: una publicación se ve si va "a
  todas" o si alguno de sus destinos cae en el alcance (misma regla que el
  historial de Notificaciones: ve lo que le llega a su gente).
- Escritura: helper `_exigir_alcance_publicacion(request, fila)`: editar o
  borrar solo si TODOS sus destinos caen en el alcance. Una global o una de
  otra seccional no se toca (fail-closed). La plantilla no dibuja Editar ni
  Borrar fuera del alcance (el servidor rechaza igual).
- Tests: ve las suyas y las globales; no ve las de otra; no edita ni borra
  una global ni una ajena; editar la suya no la "escapa" del alcance; el
  general igual que hoy.

### Bloque 3 — Formularios de trámite (C1, C2, C3). Admin 0.59.x
- Alta: para un admin local la seccional es obligatoria y es la suya (vacía
  = la suya; otra = 403). Hoy el chequeo solo corre si vino seccional.
- Editar y borrar: `_exigir_alcance_seccional(request, tipo["seccional_id"])`
  SIEMPRE, también cuando es `None` (global): con `_en_alcance` un `None`
  solo lo pasa el alcance total, que es lo que N7 dice ("no edita los
  globales"). Hoy `/admin/tramite-tipo/borrar` no chequea nada.
- Listado: el admin local sigue VIENDO los globales (necesita saber qué
  formularios tiene su gente), pero sin Editar/Borrar; los de otras
  seccionales no viajan (`tipos_tramite_del_sindicato` con alcance).
- Tests: crea solo de la suya; no edita ni borra un global; ve globales +
  propios; el general igual.

### Bloque 4 — Panel Sindical (D1). Admin 0.60.x
Es el bloque más grande y el más sensible, por eso va después de los
simples y con el robot de paridad v1/v2 ya existente como red.
- `_filtros_dashboard(request)` impone el alcance como hace Encuestas
  (N18) y Reportes (`listado_reportes(sid, filtros, alcance)`): si el
  alcance es un set, `f["seccionales"]` pasa a ser `pedido ∩ alcance`, o el
  alcance entero si no pidió nada; `set()` vacío = consulta sin filas. Un
  solo lugar: los 11 endpoints de agregados, el explorador y los filtros
  lo heredan sin tocarlos uno por uno.
- `/admin/dashboard/filtros`: devuelve solo las seccionales del alcance (el
  cajón del panel no ofrece las otras).
- Mapa de seccionales: "ignora el filtro de seccional porque el mapa ES el
  selector"; el alcance IMPUESTO no es un filtro, así que el mapa dibuja
  solo las burbujas del alcance (misma distinción que hace Encuestas).
- Modal "Ver" (detalle de recibo, trámite, notificación, consulta): 403 si
  la fila es de un afiliado fuera del alcance (`_en_alcance` sobre la
  seccional del trabajador, como `puede_ver_tramite`).
- Asistente: sus filtros pasan por el mismo `_filtros_dashboard`, así que
  no puede pedir más que el panel. Se verifica con `probar_asistente` en
  modo simulado.
- v2 (Preact) usa los MISMOS endpoints: queda cubierta sola; el robot
  `test_paridad_v1_v2` se corre con un admin local además del general.
- Tests: KPIs del local = KPIs del general filtrado por su seccional (se
  calcula de las dos formas y se compara); explorador y detalle ajeno 403;
  filtros sin las otras seccionales; el general sin cambios; k6 `test3_panel`
  no se degrada (el filtro de seccional ya tiene índice compuesto).

### Bloque 5 — Decisiones de SDN (E y F), antes de tocar
- **Empleadores (E)**: `Empleador` no tiene seccional. Tres salidas: (a) un
  admin local no ve Empleadores ni sus notificaciones/trámites (se le
  bloquean las cuatro secciones `emp_*`; las mantiene el general), (b) se
  agrega `Empleador.seccional_id` y se recorta como el padrón (sprint
  propio, con migración), (c) queda como hoy, a sabiendas. Propuesta: (a)
  ahora, (b) cuando un sindicato con seccionales lo pida.
- **Catálogo (F)**: Conceptos, Reglas, Aprendizaje y Convenio son del
  sindicato entero. Propuesta: el admin local los ve en solo lectura (los
  necesita para entender un recibo de su gente) y no los edita; editarlos
  es del general. Alternativa: dejarlo como hoy. Es una decisión de
  producto, no de código.

### Bloque 6 — Cierre
Repetir la auditoría contra el lote de La Bancaria y guardar los números
nuevos al lado de los de hoy; CLAUDE.md, HISTORIAL, BITACORA; versión.

## 4. Lo que puede romperse y cómo se cuida
- **Un general que de pronto ve menos**: imposible por construcción si
  `alcance_seccional` devuelve `None` para él; cada bloque lo testea.
- **Un afiliado sin seccional que desaparece del padrón del general**: no,
  el general no recorta. Para un local nunca estuvo "bien" verlo.
- **Noticias "a todas" que un local deja de ver**: la regla de lectura las
  incluye a propósito (le llegan a su gente).
- **El Panel más lento**: el filtro de seccional ya existe y está indexado
  (`sindicato_id` + fecha, join a trabajador por seccional); imponerlo no
  agrega un camino nuevo. Se mide con `medir_dashboard.py` antes y después.
- **Demo**: Rosario (20555555556) es el admin local de la UOM; los robots
  de `e2e/` que entran con él se vuelven a correr al final de cada bloque.

## 5. Segunda vuelta (2026-10-17, tarde) — Bloque 7: lo que la auditoría no midió

SDN entró en Pruebas con el Admin de Seccional de Lomas de Zamora
(23010101018) después de los seis bloques y lo vio **elegir otras
seccionales como destino** en Noticias, Beneficios, Notificaciones y
Encuestas. La auditoría del bloque 6 midió lo que el servidor DEVUELVE y
lo que ACEPTA, no lo que la pantalla OFRECE: ese fue el agujero del
método, y por eso este bloque arranca por la pantalla.

### Lo medido en Pruebas con 23010101018 (Admin 0.60.01)
| # | Dónde | Lo que ofrece la pantalla | Lo que hace el servidor |
|---|---|---|---|
| G1 | Encuestas → "Publicar la noticia" | — | **Agujero real**: `db.noticia_de_encuesta` crea la `Noticia` sin `destino_seccionales`, o sea "a todas": la noticia de una encuesta de Lomas de Zamora sale a todo el sindicato. |
| G2 | Noticias y Beneficios, alta y edición | Las 7 seccionales como casillas de destino (`seccionales`, no `seccionales_visibles`) y el texto "Sin marcar ninguna = todas las seccionales". | Recorta (`_destinos_de_publicacion`): lo tildado fuera del alcance se descarta y vacío = su seccional. |
| G3 | Notificaciones | Criterio "Por seccional" con las 7 casillas; "Por provincia" con las 24. | Recorta (`resolver_destinatarios` con `usuario_id`): Rosario = 0, Lomas = 1, Santa Fe = 0, Buenos Aires = 1. |
| G4 | Encuestas → Publicar | "A todo el padrón", "Por seccional" con las 7 casillas, provincia, CUIT, CUIL. | Recorta igual que G3 (`publicar_encuesta` pasa `usuario_id`). |
| G5 | Seccionales | El aviso "N seccionales sin ubicación" cuenta las del sindicato entero. | Solo lectura; la tabla ya muestra las visibles. |
| G6 | Trámites | Formularios: seccional, área por defecto, áreas de pase y mapa por seccional ya recortados (verificado: solo "Secretaria General · Lomas de Zamora"). La bandeja recorta. | Nada que corregir en el servidor; QA lo vuelve a recorrer con el robot por si SDN vio otra cosa. |

### Regla que se agrega a los principios
8. **La pantalla no ofrece lo que el servidor va a descartar.** Ya estaba
   escrito en el código del catálogo de permisos ("ofrecérselo en pantalla
   para después descartarlo en el POST sería mentirle") y no se aplicó a
   los destinos. Para alguien acotado, todo selector de seccional dibuja
   `seccionales_visibles`; si el alcance es UNA seccional, no hay nada que
   elegir y se dice en texto ("Va a tu seccional: Lomas de Zamora"). El
   recorte del servidor se queda igual: la pantalla es cortesía.

### Bloque 7 — Destinos acotados en pantalla y la noticia de la encuesta. Admin 0.60.02
Sin migraciones. Dos frentes que se pueden hacer en paralelo:

**7a, servidor (G1).** `db.noticia_de_encuesta` escribe
`destino_seccionales = [e["seccional_id"]]` cuando la encuesta tiene
seccional (la creó un acotado, N18) y `[]` (todas) cuando no la tiene (la
creó el general). La encuesta ya guarda su seccional, así que no hace falta
mirar el alcance del que publica: la noticia hereda el alcance de la
encuesta. Tests en `test_alcance_seccional_panel.py`: la noticia de una
encuesta del local sale con destino su seccional y el local de la OTRA
seccional no la ve en su lista; la del general sale a todas; y el
recordatorio/lanzamiento de la encuesta del local alcanzan solo a su
padrón (ya era así: queda fijado).

**7b, pantalla (G2–G5), en `templates/admin.html`**, usando las variables
que `admin()` ya manda (`alcance_propio`, `seccionales_visibles`):
- Noticias y Beneficios: las casillas de destino iteran
  `seccionales_visibles`. Con `alcance_propio` no nulo y una sola visible,
  en lugar de casillas va una línea fija "Va a tu seccional: X" (sin
  input: el servidor ya fuerza el destino). El texto "Sin marcar ninguna =
  todas las seccionales" solo para el alcance total; para el acotado con
  varias visibles: "Sin marcar ninguna = todas las de tu alcance".
- Notificaciones: la opción "Por seccional" existe solo si hay más de una
  visible; sus casillas iteran las visibles. Para el acotado, una línea
  arriba del criterio: "Las notificaciones llegan solo a afiliados de tu
  seccional (X); los demás criterios se aplican dentro de ella". Provincia,
  CUIT y CUIL siguen (son filtros dentro del alcance y el preview dice el
  número real).
- Encuestas → Publicar: "A todo el padrón" pasa a "A todo el padrón de tu
  seccional" para el acotado; "Por seccional" y sus casillas con la misma
  regla que Notificaciones.
- Seccionales: el aviso de "sin ubicación" cuenta `seccionales_visibles`.
- Ningún cambio en `main.py` salvo que haga falta una variable nueva; no se
  toca ninguna ruta.
- Tests nuevos en `test_alcance_seccional_pantalla.py`: se pide `/admin`
  con el local y con el general y se parsea el HTML. Para el local: ningún
  `destino_seccionales` ni casilla de `#notif-check-seccionales` ni de
  `#pub-seccionales` con un id fuera de su alcance, no aparece "Por
  seccional" en los dos `<select>` de criterio, y el nombre de la otra
  seccional no aparece en esos bloques. Para el general: las casillas
  siguen siendo todas y las opciones siguen (contrapeso). Fail-closed: el
  test recorre TODOS los `<input name="destino_seccionales">` y
  `.check-seccionales` del HTML, no solo los que conocemos hoy.

**QA (dos personas, independientes del desarrollo):**
- QA de código: corre `test_alcance_seccional_panel.py`,
  `test_alcance_seccional_pantalla.py`, `test_encuestas*.py`,
  `test_notificaciones*.py`, `test_noticias*.py`, `test_areas_*.py`,
  `test_modales.py`, `ruff`; revisa el diff contra esta sección punto por
  punto y busca en el HTML servido al local cualquier otra mención de las
  otras seccionales.
- QA de uso: Playwright contra uvicorn local con la demo cargada
  (`cargar_demo.py`), entra como Rosario (20555555556 / rosario-demo) y
  recorre Noticias, Beneficios, Notificaciones, Encuestas (crea, publica,
  manda la noticia) y Trámites, con captura de cada formulario; después lo
  mismo como el general (20111111120 / uom-demo) para ver que no cambió.

**Aprobación final** (Code, independiente de los dos equipos): revisión del
diff, corrida de la suite tocada, y después del deploy la misma
verificación en Pruebas con 23010101018 que destapó esto.
