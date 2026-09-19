# OPERATIVA.md — Cómo trabajamos en Colm3na

Instrucción operativa para quien construye código o documentación junto a
SDN. Vale para SDN, ARS, AKG y quien se sume después. Complementa a
`FLUJO.md` (qué pasa con el código) y a `CLAUDE.md` (qué sabe Claude Code).
Esto es sobre **cómo usamos las herramientas y cómo no se pierde nada**.

## 0. El problema que esto resuelve

El proyecto se construye con tres herramientas de Claude (Chat, Code,
Cowork), desde la PC y desde el celular. Cada una guarda lo suyo en un lugar
distinto y ninguna ve a las otras. Sin una regla, lo decidido en Chat no
llega al repo, lo construido en Code no se ve desde Chat, y a las dos
semanas nadie sabe dónde quedó el PIN, el prompt o la decisión.

La regla es una sola: **el repo manda**. Lo que no está en el repo (o en
`docs/INDICE.md` apuntando a dónde está) no existe para el equipo.

## 1. Día 1 de quien se incorpora

Accesos que pide a SDN (y que SDN registra en el inventario del Anexo
Interno):

1. **GitHub**: acceso al repo `MITRABAJOC` (org de XP cuando se transfiera).
2. **Claude Team**: acceso al proyecto **"Mitrabajo"** (conocimiento, chats
   compartidos, Claude Doc de la bitácora) y a Claude Code.
3. **Render**: acceso al servicio de Pruebas (Demo solo lectura hasta que
   SDN lo decida).
4. **PIN de `/entornos`**: se pide en persona o por canal privado. Nunca por
   chat de Claude ni por documento.

Qué lee, en este orden, antes de tocar nada: `README.md` → `CLAUDE.md`
(entero, una vez) → `FLUJO.md` → `BITACORA.md` (el último mes) → este
archivo. Luego levanta el proyecto en su PC siguiendo `README.md` y corre
`python chequeo.py`.

## 2. Qué herramienta para qué

| Herramienta | Para qué se usa | Dónde queda lo que produce |
|---|---|---|
| **Claude Code** | Todo lo que toca código, tests, migraciones y la documentación del repo. Siempre desde una rama. | Commits en el repo. `CLAUDE.md`, `HISTORIAL.md`, `BITACORA.md` actualizados por Code al cerrar. |
| **Chat (claude.ai, proyecto Mitrabajo)** | Pensar antes de construir: especificaciones, planes, informes, prompts para Code, análisis, documentos para el sindicato, presentaciones. | Un archivo en `docs/chat/` + una línea en `BITACORA.md`. Si es un plan para Code, además en la raíz (`PLAN_*.md` / `SPRINT_*.md`). |
| **Cowork** | Trabajo sobre documentos y artefactos de gestión (planes de implementación, contratos, tableros). | Igual que Chat: `docs/chat/` + bitácora. Los artefactos vivos se enlazan desde `docs/INDICE.md`. |
| **Manual** (GitHub web, Render, consola) | Excepciones: hotfix urgente, variable de entorno, rollback. | Una línea en `BITACORA.md` con herramienta `Manual`. |

**Desde el celular** se puede usar Chat y Cowork con normalidad; lo que se
produzca se baja al repo en la próxima sesión de Code (o desde la PC) usando
la plantilla de cierre. Un chat que se abrió desde el celular fuera del
proyecto se **mueve al proyecto** apenas se pueda.

## 3. La regla de cierre de bloque

Un *bloque* es una unidad de trabajo con sentido propio: una fase de un
sprint, un fix con su test, un informe, una decisión de producto. Dura desde
media hora hasta un día. **Todo bloque se cierra igual, en cualquier
herramienta:**

1. **Lo producido va al repo** (código commiteado; documento en
   `docs/chat/AAAA-MM-DD-tema.md`; plan en la raíz).
2. **Una línea en `BITACORA.md`**, al final, con el formato de la tabla:
   `| fecha | herramienta | módulo | qué se hizo | dónde | quién |`.
3. **Si cambió el estado del proyecto**, se actualiza "Estado actual" de
   `CLAUDE.md` (Code lo hace solo; desde Chat se le pide a Code en la
   próxima sesión).
4. **Si el documento tiene que verlo el equipo o el sindicato**, se copia
   además a `recursos/` y se registra en `recursos.SEMILLA`.
5. `python generar_bitacora.py` regenera `recursos/bitacora.html` (Code lo
   corre solo al cerrar; se commitea junto con la línea).

En **Code** esto está en `CLAUDE.md` ("Bitácora y cierre de bloque") y Code
lo hace sin que se lo pidan. En **Chat y Cowork** se usa la plantilla de
`docs/chat/PLANTILLA_CIERRE.md`: se pega al final de la conversación y
Claude devuelve el archivo y la línea listos.

## 4. Commits y ramas

- **Una rama por bloque**, desde `main`: `feature/<tema>`, `fix/<tema>`,
  `sprint/<tema>`. Nombres en minúscula, sin fechas. Se borra al mergear.
- **Sobre `demo` no se programa nunca** (regla 1 de `FLUJO.md`). Solo SDN
  promueve con `promover_demo.py`.
- **El autor del commit es la persona**, con su nombre y mail configurados
  en git (`git config user.name "Nombre Apellido"`). Cuando el código lo
  escribió Claude Code, el commit lleva al pie:

  ```
  Co-authored-by: Claude <noreply@anthropic.com>
  ```

  Así el `git log` dice quién decidió y quién tecleó. Code lo agrega solo
  (regla en `CLAUDE.md`). Un commit con autor "Claude" a secas es un error a
  corregir antes de mergear.
- **Mensaje de commit**: qué cambia y para quién, en una línea, en
  castellano, como los que ya hay (`El recibo ajeno se leía entero antes de
  frenarse`). La versión se sube en el mismo commit (regla 3 de `FLUJO.md`).
- **Pull request** cuando el bloque toca más de un módulo, una migración,
  o cuando lo hizo alguien que no es SDN. Revisa SDN (o ARS a partir de
  S9, según el Plan Maestro).

## 5. Chats: cómo se ordenan

- **Todos los chats de Colm3na viven en el proyecto "Mitrabajo".** Si uno
  quedó afuera (celular, apuro), se mueve.
- **Título con convención:** `[MT] <módulo> — <tema>`. Ejemplos:
  `[MT] Motor v2 — bloque 1 extractor`, `[MT] Contrato — revisión v3`.
  Claude no titula así solo: se renombra al abrir o al cerrar.
- **Un chat por tema.** Cuando el tema cambia, se abre otro (también evita
  que Code y Chat se vuelvan lentos por contexto acumulado).
- **Al cerrar, plantilla de cierre.** Un chat sin línea en la bitácora es
  un chat que nadie va a encontrar.
- Los **artefactos vivos** (tableros, planes con checklist) se listan en
  `docs/INDICE.md` con su link; su contenido no se copia al repo salvo que
  se congele una versión.

## 6. Documentos de Chat y Cowork en el repo (`docs/chat/`)

- Nombre: `AAAA-MM-DD-tema-corto.md` (fecha del bloque, no de hoy).
- Primeras líneas: título, fecha, herramienta, link al chat o artefacto de
  origen, estado (`borrador` / `acordado` / `superado por …`).
- Lo que se **publica** (informes, planes para el sindicato) se convierte a
  HTML y se copia a `recursos/` con su miniatura, y se registra en
  `recursos.SEMILLA`. El `.md` de `docs/chat/` sigue siendo la fuente.
- Un **prompt para Code** también va a `docs/chat/` (fecha + `prompt-tema`)
  aunque el plan resultante viva en la raíz: así se sabe de dónde salió.

## 7. Qué no se hace

- No se guardan **claves, PIN, tokens ni URLs de base** en ningún archivo
  del repo ni en chats. Van en Render (variables) y en el gestor de
  contraseñas de XP.
- No se documenta el estado en dos lugares: el estado vigente está en
  `CLAUDE.md`, el porqué en `HISTORIAL.md`, el cuándo en `BITACORA.md`. Un
  plan (`PLAN_*.md`, `SPRINT_*.md`) **no se edita** después de acordado.
- No se pega en Chat el contenido completo de `HISTORIAL.md` para "poner al
  día" a Claude: se le indica la sección, o se le pasa `CLAUDE.md`.
- No se corre `pytest -q` batcheado ni `python test_x.py` (ver `CLAUDE.md`).

## 8. Tareas diferidas (decididas el 2026-09-17, no urgentes)

- **Ramas remotas**: hay 17 mergeadas o superadas (`areas-permisos`,
  `migracion-postgres`, `claude/gracious-brown-orywe0` y 14 más). Decisión:
  no tocar por ahora. Cuando se limpien, solo quedan `main` y `demo`.
- **Autores del historial**: los commits anteriores a esta fecha tienen
  cuatro nombres de autor para la misma persona (`snavello`, `Claude`,
  `Sn`, `Sd`). No se reescribe la historia; desde ahora rige la regla de
  la sección 4.
- **Chats fuera del proyecto**: mover los que se encuentren y completar la
  tabla de `docs/INDICE.md`.
- **Titularidad de cuentas** a XP: según el Plan Maestro, por pasos, nunca
  en semana de cierre.
- **Demo atrasada**: `demo` está 119 commits detrás de `main` (última
  promoción 2026-09-05). Decide SDN cuándo promover.

## 9. Si la app no responde

Origen: cuelgue de Pruebas del 2026-09-18, en el que la app entera dejó de
responder (incluso un login desde otra sesión), reiniciar el web service no
alcanzó y solo reiniciar Postgres lo destrabó. Reconstrucción y correcciones
en `docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md`. Aplica a Pruebas y a
Demo. **El orden importa: primero se junta evidencia, después se destraba, y
reiniciar la base es el último recurso.**

### 9.1 Antes de tocar nada (2 minutos)

Un reinicio borra las pruebas. Guardar, con la hora a la vista:

1. **Captura de la pestaña Metrics** del web service y de la base en Render
   (CPU, memoria, conexiones). El plan Hobby retiene 7 días: si pasó más
   tiempo, ya no está.
2. **Los logs del web service** de la ventana del problema, sin filtrar. Buscar
   `QueuePool`, `TimeoutError`, `too many connections` y los códigos
   `E-SERVIDOR-01`, `-02` y `-03` (tabla de abajo).
3. **Qué se estaba haciendo** en el momento (qué pantalla, qué filtro) y quién.

### 9.2 ¿Está viva la app o la base?

Desde el navegador, sin sesión:

| URL | Qué pregunta | Si responde 200 | Si no responde o da 503 |
|---|---|---|---|
| `/healthz` | ¿el proceso está vivo? (no toca la base) | El web service vive: mirar la base. | El proceso está caído o sin CPU: reiniciar el web service. |
| `/readyz` | ¿la base contesta un `SELECT 1` en 2 s? | La base responde: el problema es de la app (cupo, hilos). | La base no responde a tiempo: pasar a 9.3. |

Lo que ve la gente cuando la app se defiende (503 en vez de colgarse):

| Código | Qué pasó | Qué hacer |
|---|---|---|
| `E-SERVIDOR-01` | El pool de conexiones se agotó (5 s sin conexión libre). | Ver 9.3: alguien está reteniendo conexiones. |
| `E-SERVIDOR-02` | Postgres cortó una consulta por pasar de 15 s (`statement_timeout`). | Una consulta es lenta: ver cuál en 9.3. Pedir un rango más corto. |
| `E-SERVIDOR-03` | El panel está ocupado (cupo de 4 endpoints a la vez). | Normal bajo ráfaga; si es constante, ver 9.3. |

### 9.3 Ver qué está pasando en la base

En Render: la base → **Connect** / **Queries**, o `psql` con la External
Database URL. Esta consulta lista lo que está corriendo ahora:

```sql
SELECT pid, state, wait_event_type, wait_event,
       now() - query_start AS duracion, left(query, 120) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND state <> 'idle'
ORDER BY query_start;
```

Cómo leerla:

- **Muchas filas `active` con SQL del panel** (`reciboverificado`,
  `notificaciondestinatario`, `tramite`...) = **saturación**: la base no da
  abasto. Es el caso del 2026-09-18.
- **Filas `idle in transaction`, o `wait_event_type = 'Lock'`** = **bloqueo**:
  alguien retiene una transacción o un lock y los demás hacen cola. Otro caso,
  otro arreglo: mirar qué migración o proceso largo está corriendo.

### 9.4 Destrabar, de menos a más

1. **Cortar lo que sobra, sin reiniciar nada.** Consultas de más de 15 s y
   transacciones abandonadas (no toca las conexiones sanas):

   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE datname = current_database() AND pid <> pg_backend_pid()
     AND ((state = 'active' AND now() - query_start > interval '15 seconds')
       OR (state = 'idle in transaction' AND now() - state_change > interval '30 seconds'));
   ```

   Con los techos de la app (`DB_STATEMENT_TIMEOUT_MS`, `DB_IDLE_TX_TIMEOUT_MS`)
   esto debería resolverse solo; si hay que hacerlo a mano, es una señal.
2. **Reiniciar el web service** si `/healthz` no responde o si tras cortar
   las consultas la app sigue trabada.
3. **Reiniciar Postgres, solo como último recurso.** Corta a todos y deja la
   base cerca de un minuto sin responder.

### 9.5 Después

- Agregar una línea a `BITACORA.md` (herramienta `Manual`) y, si la causa
  fue nueva, una sección en `HISTORIAL.md` con lo que se vio en 9.1 y 9.3.
- Si el problema fue de capacidad y no de un defecto, la decisión de subir el
  plan de la base es de AKG; el insumo es el resultado de
  `carga/k6/test3_panel.js` (ver `carga/README.md`).
- Las variables `DB_POOL_*`, `DB_STATEMENT_TIMEOUT_MS`, `DASHBOARD_CUPO*` se
  documentan en `DESPLIEGUE_RENDER.md`. El Health Check Path de Render tiene
  que ser `/healthz`, nunca `/readyz`.

## 10. Resumen en una tarjeta

```
Rama por bloque → Code construye y testea → commit (autor = vos, Co-authored-by Claude)
→ merge a main (Pruebas se despliega sola) → cierre: BITACORA.md + CLAUDE.md
→ generar_bitacora.py → SDN promueve a demo cuando corresponde.
Chat/Cowork producen → docs/chat/<fecha>-tema.md + línea en BITACORA.md
→ si es público, recursos/ + SEMILLA.
Cualquier cosa nueva que no entre en lo anterior → docs/INDICE.md.
```
