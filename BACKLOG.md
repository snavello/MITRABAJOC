# BACKLOG.md — hallazgos y pedidos laterales

Anotaciones para no desviar el bloque de trabajo en curso (ver "Backlog
técnico" en la memoria del proyecto). Cada ítem se tacha o se borra cuando
se hace.

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
