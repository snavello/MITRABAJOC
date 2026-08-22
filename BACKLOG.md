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

## 3. El alta de usuarios del sindicato sigue creando Super Admins

**Estado:** transitorio, se cierra en la Fase 3 de SPRINT_AREAS.md

`main.py` (`/admin/usuario`) crea `UsuarioSindicato` con
`es_super_admin=True` explícito, para no cambiar el comportamiento de hoy
mientras el sistema de Áreas está a medio construir. En la Fase 3 ese
formulario pasa a pedir área + permisos y deja de crear Super Admins por
default.

Si la Fase 3 se posterga, esto queda como una puerta abierta: cualquier
Super Admin puede crear otro Super Admin sin pasar por plataforma.
