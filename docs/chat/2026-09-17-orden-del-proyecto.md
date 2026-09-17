# Orden del proyecto: diagnóstico y esquema de bitácora
Fecha: 2026-09-17 · Herramienta: Chat · Origen: chat "[MT] Orden — diagnóstico y bitácora" (proyecto Mitrabajo)
Estado: acordado
Quién: SDN

## Problema

Información dispersa entre Chat, Code, Cowork, PC y celular. El repo estaba
bien documentado (`CLAUDE.md`, `HISTORIAL.md`, `FLUJO.md`, planes) pero
nada de lo decidido en Chat/Cowork llegaba al repo con regla, no había una
línea de tiempo, y los chats fuera del proyecto no eran buscables.

## Diagnóstico (resumen)

- Cinco capas sin puente: repo, proyecto Claude, chats, artefactos, Code/Cowork.
- `HISTORIAL.md` ya era la bitácora por bloque (79 secciones fechadas) pero
  sin lo hecho fuera de Code y sin formato de una línea.
- 288 commits con 4 nombres de autor para la misma persona; 19 ramas remotas
  y solo 2 vivas; `demo` 119 commits detrás de `main` (última promoción 5-sep).
- El `INFRAESTRUCTURA.md` del 28-ago no está en el repo (su contenido se
  reescribió en `PLAN_ENTORNOS.md`, `DESPLIEGUE_RENDER.md`, Anexo Servicios).

## Decisiones

| Decisión | Alternativas descartadas | Quién |
|---|---|---|
| El repo manda; espejo de la bitácora en Recursos de `/entornos` **y** en un Claude Doc del proyecto. | Solo repo; solo doc externo. | SDN |
| Una línea de bitácora por bloque de trabajo/sesión. | Por commit; por día. | SDN |
| Nombre canónico para carpetas y títulos: **Colm3na**. | Mi Trabajo; MITRABAJOC. | SDN |
| Commits: autor = la persona; Code firma `Co-authored-by`. | Sin rastro de Code; Code como autor. | SDN |
| Ramas mergeadas/superadas: no tocar por ahora. | Borrar las 17; borrar solo 14. | SDN |
| Documentos de Chat/Cowork → `docs/chat/AAAA-MM-DD-tema.md`; lo publicable se copia a `recursos/`. | Raíz como hoy; todo a `recursos/`. | SDN |
| No se reestructura lo existente en la raíz (mover archivos rompe referencias de los planes). | Carpeta `docs/` con todo. | Claude (propuesto), SDN |

## Entregado

`BITACORA.md` (39 bloques, 27-jul → 17-sep), `docs/INDICE.md`,
`docs/OPERATIVA.md`, `docs/chat/PLANTILLA_CIERRE.md`, bloque para
`CLAUDE.md`, `generar_bitacora.py`, `recursos/bitacora.html` + miniatura,
entrada para `recursos.SEMILLA`, Claude Doc "Bitácora Colm3na".

## Pendiente de SDN

Ver `LEEME_PRIMERO.md` del paquete: aplicar al repo con Code, mover chats
al proyecto, completar los links faltantes en `docs/INDICE.md`.
