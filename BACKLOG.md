# BACKLOG.md — hallazgos y pedidos laterales

Anotaciones para no desviar el bloque de trabajo en curso (ver "Backlog
técnico" en la memoria del proyecto). Cada ítem se tacha o se borra cuando
se hace.

_(sin pendientes abiertos)_

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
