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

- [ ] **Mergear `areas-permisos` a `main`** (2026-09-01): el sprint está
  terminado y probado; no se mergeó por la demo inminente. Al mergear,
  acordarse de las **5 líneas de `PERMISOS_RUTAS`** para las rutas de RAG
  (`/admin/convenio*`) que llegaron a `main` después — sin eso el panel de
  carga del convenio se rechaza con un error inexplicable (avisado en
  PLAN_RAG_CONVENIO.md, "Interacción con la rama areas-permisos").

- [ ] **Sprint "Admin de Seccional"** (2026-09-01): rol intermedio de máxima
  autonomía para las delegaciones, encima de `areas-permisos` (requiere el
  merge de arriba primero). Decisiones YA CERRADAS con Sd, no re-preguntar:
  1. **El admin local ve TODA su seccional** (todas las áreas, no solo la
     suya) — es "el admin grande en chiquito".
  2. **Áreas locales con ADHESIÓN OBLIGATORIA (opción B)**: el admin local
     puede crear áreas, pero el alta exige colgarlas de un **área troncal**
     del Super Admin (`Area.area_madre_id` + `Area.seccional_id`). El nombre
     local es libre ("Jurídica" puede colgar de "Legales"): **la vertical
     viaja por la FK, nunca por el nombre**. Sin islas: no existen áreas
     locales sin madre (eso sería la opción C, descartada; si algún día hace
     falta, es soltar la obligatoriedad, no rediseñar).
  3. Alcance vertical: "Legales central" (seccional con `ve_todas`) ve su
     área troncal ∪ todas sus hijas, en todas las seccionales. Un solo
     nivel, sin anidamiento.
  4. **Anti-escalada**: el admin local no otorga super admin ni `ve_todas`,
     no toca usuarios de otras seccionales, y solo puede dar secciones que
     él mismo tiene.
  5. Noticias/beneficios del admin local: destino recortado a su alcance
     (misma regla que Notificaciones, Fase 6 de areas-permisos; hoy
     `_destinos_validos` solo filtra por sindicato).
  6. **Formularios de trámite por seccional**: `TipoTramite.seccional_id`
     nullable (null = global); el trabajador ve globales + los de su
     seccional; el admin local crea solo locales y no edita globales.
  7. **Trámites de empresa quedan centrales**: `Empleador` no tiene
     seccional; mapear empresa→seccional sería otro sprint.
  8. El flag `es_admin_seccional` arranca en `False` para todos — opt-in,
     un sindicato centralizado ni se entera.
  Costo estimado: ~4 fases (la mitad del sprint areas-permisos original).

## Hecho

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
