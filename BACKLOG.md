# BACKLOG.md — hallazgos y pedidos laterales

Anotaciones para no desviar el bloque de trabajo en curso (ver "Backlog
técnico" en la memoria del proyecto). Cada ítem se tacha o se borra cuando
se hace.

- [ ] **Validar el módulo 11 (dígito verificador) de CUIL y CUIT** (2026-09-24,
  decisión de SDN al construir el enmascarado: "por ahora no lo testeamos,
  lo anotamos para cuando avancemos en ese tema"). Hoy la app no valida el
  verificador en ningún lado, y **ninguno de los CUIL/CUIT de la demo lo
  cumple** (20111111119, 27222222224, 30999888776, 30111222339, los de los
  admins...). Por eso el enmascarado NO depende de él: tapa lo que viene
  con formato de CUIL (`enmascarado.parece_cuil`) y decide que un recibo es
  ajeno por distancia (3 o más dígitos distintos, `distintos_de_verdad`) en
  vez de por verificador. Cuando se valide: (1) sembrar la demo con CUIL y
  CUIT válidos (`cargar_demo.py`, `cargar_lote_*`, `IDENTIDAD_FICTICIA` de
  los sintéticos) -- los tests y los accesos de CLAUDE.md usan esos números;
  (2) validar en el alta y el registro; (3) volver a exigir el verificador
  en `enmascarado.pertenece`, que es más firme que la distancia.

- [ ] **El empleador quedó con el defecto que se le corrigió al trabajador**
  (2026-09-22, al terminar "Una persona, un domicilio" en HISTORIAL.md).
  `Empleador` es una fila POR SINDICATO y ahí viven `razon_social`,
  `domicilio`, `telefono`, `provincia` y `mail`; `/api/empresa/perfil`
  escribe **solo en el sindicato activo**. Es exactamente lo que hacía el
  perfil del trabajador antes de este bloque: un CUIT dado de alta en dos
  gremios puede terminar con dos razones sociales y dos domicilios, y nada
  dice cuál es el bueno. Y peor: su `domicilio` sigue siendo **un texto
  libre**, nunca se migró al bloque estructurado de `geo.CAMPOS_DOMICILIO`,
  así que no se puede agrupar ni ubicar por zona como el del afiliado.

  El arreglo es el mismo y ya está probado: mover el bloque personal a
  `CuentaEmpleador` (una fila por CUIT, creada desde el alta del padrón y
  con `clave_hash` vacío mientras no se registre), con
  `db.guardar_datos_personales` y `db.asegurar_cuenta` como espejo. No se
  hizo en el mismo bloque porque duplicaba su tamaño y el pedido de Sd era
  sobre el trabajador. **Ojo con una diferencia real**: el CUIT y la razón
  social son datos públicos de la empresa, no de una persona, así que la
  regla de "manda quien se registra" puede no aplicar igual -- conviene
  decidirlo antes de escribir la migración.

- [ ] **El código de concepto no es una clave confiable entre empleadores**
  (2026-09-13, dicho por Sd al analizar el primer recibo real en el banco de
  pruebas). **Cada empleador le pone el código que quiere**, así que el
  código solo pesa cuando se están mirando recibos de UN empleador. Hoy
  `validador.matchear` lo prueba primero y cae a la descripción normalizada,
  y existen `Concepto.codigo_generico` y `Concepto.cuit_empleador` justamente
  por esto; la `categoria_universal` que pone la IA es la tercera red.
  Sd lo deja explícitamente **para la V2 del motor, ya evaluada y en
  agenda** -- no se toca antes. Se anota acá porque no está escrito en ningún
  lado y es la clase de supuesto que se vuelve a discutir desde cero si nadie
  lo dejó dicho.

  Corolario práctico para el banco de pruebas: un dígito mal leído en el
  código pesa MENOS de lo que parece (el match cae a la descripción), pero no
  es inocuo -- un código fantasma se propone como concepto nuevo en
  Aprendizaje.

- [ ] **Tres tests fallan en Windows por la codificación de la consola, no por
  el código** (2026-09-13, encontrado al barrer la suite entera archivo por
  archivo en el bloque de costo de IA). En esta PC la codepage por defecto es
  cp1252, y tres tests abren archivos o leen la salida de un subproceso sin
  pasar `encoding="utf-8"`:
  - `test_trabajador_seccionales_cerca.py` → lee `static/mapa.js`
    (`UnicodeDecodeError: byte 0x8d`).
  - `test_cargar_demo_areas.py` → compara contra la salida de `cargar_demo.py`
    y la palabra con acento llega rota (`usuario de área`).
  - `test_experimentos_carga.py` → el subproceso que lanza imprime `→` y
    revienta al escribir en stdout (`UnicodeEncodeError`).

  Los tres pasan o fallan por el entorno, no por lo que prueban, y hoy
  ensucian cualquier barrido completo: cuesta ver una falla de verdad entre
  las tres de siempre. Arreglo: `encoding="utf-8"` explícito en cada `open()`
  de test, y `PYTHONIOENCODING=utf-8` (o `encoding=` en `subprocess.run`) para
  los que lanzan subprocesos. Es la misma trampa que ya obligó a poner
  `sys.stdout.reconfigure(encoding="utf-8")` arriba de `probar_asistente.py`.

- [ ] **Terminar de sacar "Mi Trabajo" de la documentación** (2026-09-13,
  pedido de Sd: "lo haremos después"). De la INTERFAZ ya salió (ver
  HISTORIAL.md, "«Mi Trabajo» sale de la interfaz"). Queda el nombre viejo
  en **67 líneas de 22 archivos**, todo texto, sin riesgo técnico:
  - **Lo que ve alguien de afuera, y por eso va primero**: los documentos
    de `recursos/` que la landing `/entornos` publica —
    `colm3na-plan-maestro.html`, `colm3na-plan-implementacion-sindicato.html`,
    `anexo-servicios-mensuales.html`, `documentacion-tecnica.html` — que hoy
    encabezan "Colm3na · Mi Trabajo".
  - **Documentación del repo**: `README.md`, `CLAUDE.md`, `HISTORIAL.md`,
    `ESTADO_DEL_PROYECTO.md`, `PLAN_ENTORNOS.md`, `DESPLIEGUE_RENDER.md`,
    `GUIA_CODE_REDISENO.md` y la skill `diseno-mi-trabajo`.
  - **Docstrings y comentarios**: `main.py`, `db.py`, `errores.py`,
    `chequeo.py`, `cargar_marca_plataforma.py`, `migrations/env.py`,
    `e2e/conftest.py`, `static/mapa.js`.

  **Lo que NO se toca**, porque son identificadores y no la marca: el archivo
  `static/logo_mitrabajo.svg`, la carpeta de la skill `diseno-mi-trabajo`,
  los servicios de Render (`mitrabajo-pruebas`, `mitrabajo-demo`) y su URL,
  las bases (`mitrabajo_dev`, `mitrabajo_test_*`), `.claude/launch.json`, los
  mockups de `disenos/` y `docs/` (son el registro de lo que se propuso en su
  momento), el comentario de `templates/dashboard.html` que cita el texto
  viejo a propósito, y `e2e/resultados/informe.html`, que se regenera solo.

- [ ] **Tres tests rotos en Windows por encoding** (2026-09-13, hallazgo
  lateral: fallan igual en `main` limpio, no los rompió el encabezado
  normalizado). Los tres son cp1252 contra UTF-8, no lógica:
  - `test_cargar_demo_areas.py::test_la_salida_lista_los_usuarios_nuevos` —
    compara "usuario de área" contra la salida del subproceso, que llega con
    la tilde corrupta.
  - `test_experimentos_carga.py` — `charmap_encode` revienta al imprimir
    unicode desde un subproceso.
  - `test_trabajador_seccionales_cerca.py::test_haversine_del_servidor_y_del_navegador_dan_lo_mismo`
    — `UnicodeDecodeError` leyendo un archivo sin `encoding="utf-8"`.
  Probablemente pasan en Linux (CI), así que es específico de la PC de
  desarrollo: falta `encoding="utf-8"` en las lecturas y
  `PYTHONIOENCODING`/`encoding` en los subprocesos.

- [ ] **Validaciones de Trámites, fases 2–4** (2026-09-01): la Fase 1
  (fuente `fija` + consistencia entre campos) está HECHA y en el código —
  ver "Validaciones en formularios de Trámites" en CLAUDE.md/HISTORIAL.md.
  Decisiones YA CERRADAS con Sd para lo que sigue:
  - **Fase 2 — fuente `sistema`**: catálogo cerrado de funciones sobre
    datos que la app ya tiene (padrón, antigüedad como afiliado calculada
    desde fecha — nunca guardada —, recibos validados, semáforo). Habilita
    los "requisitos para iniciar" a nivel formulario (se chequean ANTES de
    mostrar los campos).
  - **Fase 3 — fuente `lista`**: modelo `ListaDatos`/`FilaListaDatos`
    (clave o clave→valor) con carga CSV desde /admin. En las listas se
    guardan **hechos, no derivados** (fecha de afiliación, no antigüedad).
    Caso de uso real: CUIL de un familiar contra la base de familiares
    declarados del sindicato. Validación en vivo con **límite de intentos
    por sesión** (anti-enumeración del padrón) y respuesta solo con el
    mensaje del admin.
  - **Fase 4 — fuente `externa`**: catálogo de conectores por sindicato
    (credenciales aisladas), contrato interno
    `conector.consultar(funcion, params) → {ok, valor?, mensaje, timestamp}`,
    timeout corto, y modo de falla POR VALIDACIÓN (si la API ajena no
    responde: bloquear o dejar pasar con advertencia; default advertencia).
    El derivado consultado NO se guarda; solo se registra qué devolvió y
    cuándo, para auditar. Ya hay un sindicato que pidió conectar un sistema
    propio (ej. scoring), especificación pendiente.

- [ ] **Número de expediente con tilde** (2026-09-03): la sigla del tipo de
  trámite toma los 4 primeros caracteres alfanuméricos del nombre del
  sindicato, y `Ó` cuenta como alfanumérico — "Unión Obrera Metalúrgica" da
  expedientes como `UNIÓF01-2026-000393`. Encontrado al verificar el entorno
  de Pruebas; **ya pasa en la demo también**, no es de Pruebas. Un
  identificador que viaja por URLs (`/api/tramite/{numero_expediente}`) y
  eventualmente a sistemas de terceros no debería llevar acentos. Arreglo:
  normalizar la sigla en `cargar_lote_sindicato.contexto_lote()` y en el alta
  de tipos de trámite (quitar diacríticos, como hace `slug()` en
  `cargar_demo.py`). Ojo: cambiar el prefijo de un sindicato que ya tiene
  expedientes emitidos parte la serie — decidir si se normaliza solo para los
  nuevos.

## Hecho

- [x] **Mergear `areas-permisos` a `main`** y **Sprint "Admin de Seccional"**
  (2026-09-11): los absorbió `SPRINT_AREAS_V2.md`, hecho en la rama
  `areas-permisos-v2`. La rama vieja quedó 126 commits atrás y se **portó**
  sobre `main` en vez de mergearse (medido: 8 archivos en conflicto y 28
  rutas sin clasificar, no las "5 líneas de PERMISOS_RUTAS" que anotaba este
  backlog — hoy son 73 rutas clasificadas, RAG y dashboard incluidos). De
  las decisiones cerradas del sprint "Admin de Seccional" entraron todas
  menos la 2: la **adhesión obligatoria** a un área troncal
  (`Area.area_madre_id`) se reemplazó por un mapa explícito
  seccional→área por formulario más un destino por defecto obligatorio
  (decisión N6), que resuelve el mismo problema sin la vertical implícita.
  La 5 (noticias/beneficios recortados al alcance) y la 6 (formularios por
  seccional) están hechas y con tests.

- [x] **Colisión de números de expediente entre sindicatos** (2026-08-31):
  el correlativo salía de contar los trámites de UN tipo, y con prefijos
  repetidos entre sindicatos daba números ya usados. Ahora se calcula desde
  el máximo real de ese prefijo+año (`db._proximo_numero_expediente`), para
  trabajador y para empleador.
- [x] **Selectores del dashboard** (2026-08-31): se eliminó "Categoría" y se
  agregó el chip "TODAS" en Seccionales y Empresas, de modo que todo filtro
  queda siempre con su opción vigente marcada en el color destacado (antes
  el estado por defecto quedaba neutro y parecía sin elegir).
- [x] **Badge "NEW" en la tarjeta del Panel Sindical** (2026-08-31): estrella
  + etiqueta "NUEVO" en `/admin/inicio`. **Sacarla a mano** en un deploy
  posterior: no expira sola.
