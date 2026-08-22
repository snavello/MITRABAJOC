# BACKLOG técnico

Cosas encontradas al pasar que no corresponde arreglar en el bloque de
trabajo en curso: bugs pre-existentes, deudas y ideas evaluadas y
pospuestas. Se anotan acá para que no se pierdan ni desvíen el sprint.

**Qué NO va acá:** los pendientes de producto viven en CLAUDE.md, sección
"Pendientes (features)". Este archivo es para hallazgos técnicos, no para
el roadmap.

Formato: cada entrada dice qué es, dónde, por qué importa y cómo se
verifica que quedó arreglado. Lo que se arregla se saca de acá -- el
detalle queda en el commit que lo resolvió.

---

## 1. Rederivar un trámite a otra área

**Estado:** pospuesto a propósito · **Decidido:** 2026-08-22

Al planificar Áreas se evaluó que un trámite ya presentado se pudiera pasar
de un área a otra ("esto es de Tesorería, no de Legales") y se decidió
dejarlo afuera de la primera implementación: el área receptora la fija el
formulario y no se puede cambiar después.

El error de ruteo aparece siempre en el uso real, así que conviene revisar
esto después de que las áreas lleven un tiempo funcionando. Costo estimado:
un botón en el chat del trámite y un registro de quién derivó.

---

## 2. Un 403 por permiso en un POST de página muestra JSON crudo

**Estado:** abierto, de baja prioridad · **Detectado:** 2026-08-22 (Fase 2)

`sesion_vencida_o_denegada` (main.py) redirige al login cuando el 403 viene
de una sesión inválida, pero un 403 con sesión VÁLIDA y permiso faltante
sigue devolviendo el JSON de FastAPI. Si un usuario de área llega igual a
un formulario que no le corresponde, ve `{"detail":"No tenés permiso..."}`
en pantalla completa.

Es el mismo comportamiento que ya tenía `_exigir_modulo`, así que no es una
regresión, y desde la Fase 3 esos formularios ni se renderizan. Queda como
deuda de prolijidad: convendría redirigir al panel con un aviso, como se
hizo con `error_no_manejado`.

---

## 3. El historial de notificaciones no está acotado por seccional

**Estado:** decisión pendiente · **Detectado:** 2026-08-22 (Fase 6)

Desde la Fase 6, un usuario de área solo puede NOTIFICAR a trabajadores de
su alcance de seccional. Pero el listado de notificaciones ya enviadas
(`notificaciones_del_sindicato`) sigue mostrando todas las del sindicato, y
`/admin/notificacion/{id}/destinatarios` devuelve los CUIL de cualquiera --
incluidos trabajadores de otras seccionales.

No se cambió porque no estaba decidido: lo acordado fue acotar a quién se
le puede escribir, no qué historial se ve. Las opciones son (a) dejarlo así
—es el historial del sindicato, no de la persona—, (b) mostrar solo las
notificaciones que mandó su propia área, o (c) mostrarlas todas pero
recortar la lista de destinatarios a su alcance.

Conviene decidirlo antes de que un sindicato con varias seccionales lo use
en serio.

---

## 4. `cargar_demo.py` falla si se re-corre sobre una base con trámites

**Estado:** abierto, pre-existente · **Detectado:** 2026-08-22 (Fase 6)

La limpieza de corridas previas borra conceptos, fórmulas, trabajadores,
empleadores, usuarios (y desde la Fase 6 también áreas y seccionales), pero
NO borra trámites, notificaciones, noticias ni beneficios. Al llegar al
`s.delete(sind)` Postgres rechaza por FK y el script muere a mitad.

Verificado sobre la base local dentro de una transacción revertida: con 6
trámites cargados, `IntegrityError`.

No aparece en el flujo documentado porque el reset borra el volumen entero
antes (`docker compose down -v && ... && cargar_demo.py`), así que el script
siempre corre sobre una base vacía. Salta solo si alguien lo re-corre sobre
una base con uso.

**Arreglo:** completar la limpieza con las tablas que faltan, o cambiar el
enfoque a "borrar el sindicato en cascada". **Verificación:** cargar la
demo, crear un trámite y volver a correr `cargar_demo.py`.

