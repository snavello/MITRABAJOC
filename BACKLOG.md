# BACKLOG.md — hallazgos y pedidos laterales

Anotaciones para no desviar el bloque de trabajo en curso (ver "Backlog
técnico" en la memoria del proyecto). Cada ítem se tacha o se borra cuando
se hace.

- [ ] **Trámites: seis brechas verificadas contra el código** (2026-10-16,
  Parte 2 del cierre del Asistente de trámites, aprobadas por SDN; las
  mismas seis viven en `BRECHAS` de `asistente_tramites.py` cuando exista,
  `PLAN_ASISTENTE_TRAMITES.md` D10). Confirmadas una por una con archivo y
  función:
  1. **Ventana por fechas** (chico): `TipoTramite` solo tiene `activo`
     (db.py); el afiliado lo lista con `db.tipos_tramite_del_sindicato(
     solo_activos=True)` y `/api/tramite` solo chequea `tipo["activo"]`.
     Dos columnas `fecha_desde`/`fecha_hasta` (patrón de `Noticia`),
     migración, el WHERE de esa función, el chequeo del envío, dos inputs
     en el constructor y el espejo en `TipoTramiteEmpleador`.
  2. **Marca «solo encadenado»** (chico): para adjuntarse en una nota el
     formulario tiene que estar activo (`main._formulario_para_chat`,
     `db.formulario_activo_de`) y entonces también sale en "Iniciar
     trámite" (`/api/tramites/tipos`). Peor: `origen_tramite_id` es
     opcional en `/api/tramite`, así que un encadenado se puede enviar
     SIN trámite de origen ni aprobación previa. Una marca en el tipo,
     excluirla del listado del afiliado y exigir origen válido al enviar.
  3. ~~**Extensiones jpg/jpeg**~~ **HECHO el 2026-10-16** (Trabajador
     0.45.06, Admin 0.53.06): `main.extensiones_permitidas` suma la
     equivalente de cada una (jpg↔jpeg, tif↔tiff) al comparar en las dos
     rutas de envío y al armar el `accept` del navegador, sin tocar lo
     guardado; la ayuda del constructor lo dice.
  4. **Exportar trámites con sus respuestas** (mediano): no hay CSV de
     trámites; `dashboard.explorador_tramites` devuelve expediente, fecha,
     seccional, tipo, estado y días, y las respuestas solo se ven de a
     una en el modal "Ver". Una ruta por tipo con una columna por campo,
     dentro del alcance de seccional y área del operador, registrando
     cada descarga como hace Encuestas (nombres y DNI de familiares son
     dato sensible).
  5. **Opciones que dependen de otra respuesta** (mediano, prioridad
     baja): `validaciones_tramite.TIPOS_VALIDABLES = ("numero", "fecha")`
     y `reglas_saneadas` descarta una regla si los dos campos no son del
     mismo tipo; no existe nada de opciones dependientes. Modelo en el
     campo (opciones por valor del padre), constructor, JS de afiliado y
     empresa, y validación en el servidor del subconjunto. Provisorio:
     unir las dos listas en una ("Primaria 1.º", "Primaria 2.º"…).
  6. **Pedidos repetidos**: "uno por afiliado por formulario" **HECHO el
     2026-10-16** como requisito sobre `sistema.tramites_de_este_tipo`
     (bloque 5 de `PLAN_LISTAS_VALIDACIONES.md`). Queda "único por valor
     de un campo" (el mismo DNI del chico en dos pedidos): mediano, una
     marca «único» sobre el campo y una consulta a las respuestas de los
     trámites del tipo antes de crear, con `bloquea`/`avisa`.

- [ ] **Panel Sindical: una dirección con solo `sal_max` pierde ese filtro**
  (2026-10-12, encontrado al portar el estado a la v2, `PLAN_DASHBOARD_V2.md`
  bloque 2). En `initCatalogo` de `static/dashboard.js`, si la dirección no
  trae `sal_min`, el salario se vuelve a los dos límites y el `sal_max` que
  venía se descarta: un enlace compartido con "hasta $2.000.000" abre sin ese
  filtro. La v2 copia la rareza a propósito (`estado.conLimites`), porque
  tiene que pedir exactamente lo mismo que la v1. Por D10 se arregla en las
  DOS en el mismo PR; `test_dashboard_v2_nucleo.py` compara las dos y lo va a
  exigir.

- [ ] **Para el motor v2: dos variaciones del modelo con el MISMO recibo**
  (2026-09-24, medición del enmascarado, `medicion_enmascarado/RESULTADO.md`).
  (1) "SEGURO OBLIGATORIO - DGI" ($380 fijo) sale `aporte_trabajador` en una
  lectura y `otro` en la siguiente, sin cambiar nada: leído tres veces el
  mismo original dio `aporte / otro / otro`. Como `tipo` alimenta la
  retención sindical y el tope del 2%, una línea ambigua cambia el resultado
  entre dos lecturas del mismo recibo. Es el caso de manual para el catálogo
  maestro (D8: elegir de una lista cerrada) y la confianza por renglón. (2)
  El signo de los descuentos: a veces como figura en la columna (positivo),
  a veces negativo. Hoy no rompe nada (el validador usa `abs()` y el banco ya
  no lo marca), pero el motor v2 debería normalizarlo en un solo lugar.

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
  **Plan propuesto el 2026-10-10: [`PLAN_CUIT_MOD11.md`](PLAN_CUIT_MOD11.md)**
  (diagnóstico, conversión de los números cargados a mano y recién después
  exigir el verificador en las puertas de alta). **Hechos (1) y (2) el
  2026-10-10** (CLAUDE.md, "Estado actual" 31). Queda (3), el verificador en
  `enmascarado.pertenece`, y convertir los lotes sintéticos (etapa 5 del
  plan, opcional).

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
  **Fases 2 y 3 HECHAS el 2026-10-16 como una sola fuente `funcion`**
  (`PLAN_LISTAS_VALIDACIONES.md`, cinco bloques): listas tipadas por CSV,
  datos del padrón, fórmulas con nombres cerrados, requisitos para iniciar,
  campo calculado, en vivo con tope de intentos. Queda la Fase 4.
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

- [ ] **Sesiones que sobreviven al cambio de clave** (2026-10-12, QR-1 de la
  revisión de QA del registro): huella de `clave_hash` en el token de sesión y
  chequeo en `sesion_actual`; hoy un impostor activo sigue adentro tras una
  recuperación. Cuesta una consulta por request. Test que lo mide:
  `test_qa_recuperacion_clave.py::test_rojo_qr1_...` (`xfail(strict=True)`: al
  arreglarlo hay que sacarle la marca).
- [ ] **Un tercero puede invalidar el código vivo** (2026-10-12, QR-4): pedir
  otro código vence el anterior ("un solo código vivo"), así que quien resuelve
  el captcha le pisa el código a la persona. Reusar el código vivo si tiene
  menos de N minutos en vez de vencerlo. Tensión con el diseño actual, hay que
  decidirla. Test: `test_qa_recuperacion_clave.py::test_rojo_qr4_...`
  (`xfail(strict=True)`).
- [ ] **Verificar el código en el paso 2 del registro** (2026-10-12, QA-REG-08b):
  `POST /registro/verificar`, para que un error de tipeo no devuelva al paso 1
  ni gaste cupo y captcha. Hoy el código recién se comprueba en el paso 3.
- [ ] **El freno por IP toma el primer `X-Forwarded-For`** (2026-10-12, QA-REG-05,
  ya es H-0008): lo escribe el cliente. Con Cloudflare, usar la IP que firma el
  perímetro. Test: `test_qa_registro_flujo.py::test_el_freno_por_ip_no_se_evade_...`
  (`xfail(strict=True)`).

- [ ] **Calculadora bancaria: horas extras, averiguar antes de construir**
  (2026-10-13, decisión de SDN: "no construir en falso"). El CCT 18/75 no las
  regula (solo las nombra en el art. 43) y la grilla de agosto 2026 no trae
  valor hora: rige la LCT, art. 201 (50% días comunes, 100% sábados después
  de las 13, domingos y feriados). Falta saber, con el sindicato o con
  recibos reales: (1) el divisor del valor hora (cuántas horas por mes toma
  la banca) y (2) qué conceptos entran en la base (básico solo, o también
  conformado, ROE y adicionales). Hasta entonces la calculadora no las
  contempla; un recibo real que las traiga las deja en "renglones que la
  calculadora no tiene".

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
- [ ] **Bitácora de acciones del panel del sindicato** (2026-10-11, QD-7 de la revisión de QA del registro): quién restableció una clave o confirmó una identidad, cuándo y sobre quién. Hoy solo queda una línea en el log (`mitrabajo.panel`), sin tabla ni pantalla.
