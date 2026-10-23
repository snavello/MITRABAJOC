# Contrato de importación de trámites (`colm3na.tramite` v1)
Fecha: 2026-10-16 · Herramienta: Chat · Origen: artifact «Piloto de trámites Colm3na» https://claude.ai/artifact/BgZ441HNMwtQw2jFPsALsd · Proyecto Mitrabajo, `claude/contrato-importacion-tramites-v1.md`
Estado: borrador
Quién: SDN

Este JSON lo genera el Asistente de trámites y lo va a consumir un importador futuro en el panel del sindicato, para no crear a mano un formulario ya acordado con el sindicato. El ejemplo completo está en `2026-10-16-ejemplo-kit-escolar.colm3na.json`.

## Principio

Cada campo tiene la MISMA forma que guarda hoy el constructor (`main._campos_tramite_validos` → `POST /admin/tramite-tipo`). Así el importador reusa el saneo que ya existe: `_campos_tramite_validos`, `validaciones_tramite.validaciones_saneadas` y `reglas_saneadas`. Las claves que empiezan con `x_` todavía no se importan; marcan brechas.

## Estructura

- `formato`: "colm3na.tramite" · `version`: 1 · `generado` (AAAA-MM-DD) · `estado`: borrador | acordado
- `tramite`: { nombre, objetivo, relato }. El relato del analista o del sindicato es la fuente que manda.
- `requisitos_previos`:
  - `modulos`: claves de `modulos.py` (tramites, notificaciones, noticias, empleadores).
  - `areas`: [{ area, en: "cada_seccional" | "sede_central", permisos: ["tramites_recibidos"] }], con las claves de `permisos.SECCIONES`. Incluye el área que atiende, la que aprueba si es otra y la de delegados cuando entregan usando el panel.
- `formularios`: [ { clave ("principal" | "encadenado_N"), titulo, codigo (sin tildes), activo, seccional (null = global),
  destino: { modo: "misma_area_en_cada_seccional" | "una_sola_area", area, por_defecto: {area, seccional} },
  permite_pase, areas_pase: [{area, en}],
  campos: [ { etiqueta, tipo_dato, longitud_maxima, longitud_exacta, decimales, tipos_archivo_permitidos, opciones, ancho, obligatorio, validaciones[], x_pendiente? } ],
  reglas_consistencia: [], requisitos: [ <validación de fuente funcion, ver validaciones_tramite.requisitos_saneados> ], x_solo_encadenado? } ]
  - Los encadenados sirven para pedir DATOS NUEVOS después de la aprobación. Corregir o completar lo ya enviado va por el chat del trámite.
- `circuito`: es una guía para el operador; Colm3na no tiene un objeto «circuito». Usa notación de flujo tipo BPMN:
  - `actores`: [{ actor, usa_colm3na }]
  - `pasos`: [{ id, tipo: inicio | accion | decision | fin, texto, actor, estado }], con el estado del expediente: iniciado, en_tratamiento, espera_info, respondido o terminado.
  - `flujos`: [{ de, a, etiqueta, tipo: secuencia | mensaje_fuera_de_colm3na }]
  - `datos`: [{ dato, de, a, canal }]
- `respuestas`: las del onboarding, para trazabilidad.
- `pendientes`: { brechas: [{clave, nivel: ajuste | desarrollo, motivo, provisorio}], preguntas: [] }

## Reglas del importador (propuesta, sin construir)

1. **Resolver por nombre.** Áreas y seccionales se buscan POR NOMBRE dentro del sindicato de la sesión. Si falta alguna, no se importa nada y se informa la lista: es «adecuación previa».
2. **Mapa por seccional.** `destino.modo = misma_area_en_cada_seccional` se traduce a `destinos_json` = {seccional_id: id del área homónima de esa seccional}. Las seccionales sin esa área caen al destino por defecto; no es error, pero se informa. Lo mismo vale para `areas_pase` con `en: cada_seccional`: una fila de pase por seccional.
3. **Orden y transacción.** Primero los encadenados y después el principal, todo en una transacción.
4. **Ensayo antes de confirmar.** Vista previa y ensayo, con el mismo criterio que `regularizar_cuit.py`.
5. **Permiso y sindicato.** Hace falta el permiso `tramites_formularios`. El `sindicato_id` sale de la sesión, nunca del JSON.
6. **Registro.** Se registra cada importación: quién, cuándo y qué archivo.
7. **El circuito no se importa como configuración.** Se podría guardar como guía del operador del tipo de trámite.
