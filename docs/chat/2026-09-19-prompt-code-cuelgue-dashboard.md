# Prompt para Claude Code: cuelgue del Panel Sindical
Fecha: 2026-09-19 · Herramienta: Cowork · Origen: chat "[MT] Panel Sindical — cuelgue por conexiones y observabilidad" (proyecto Mitrabajo)
Estado: borrador
Quién: SDN

Copiar desde la línea siguiente hasta el final en una sesión nueva de Code.

---

Leé primero, en este orden y completos:

1. `CLAUDE.md` (contexto del proyecto).
2. `docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md` — es el
   documento rector de este bloque: diagnóstico, correcciones C1–C8,
   criterios de aceptación y la lista de lo que tenés que preguntar.
3. `docs/DASHBOARD.md` §2.2, §3 y §5 (reglas del panel que no se rompen:
   agregados en SQL, paginación server-side, privacidad, aislamiento).
4. `db.py` líneas 80–130, `dashboard.py` líneas 190–460,
   `static/dashboard.js` líneas 136–235, `main.py` líneas 4916–5120.

Contexto en una frase: el 2026-09-18 la app de Pruebas se colgó entera con
un solo usuario cambiando filtros del panel; el documento rector reconstruye
la causa desde el código (sesiones anidadas + pool de 10 sin timeout + 13
requests por refresco + threadpool compartido).

## Reglas de trabajo

- El trabajo tiene **DOS FASES estrictamente secuenciales**. No escribas
  una línea de la Fase 2 hasta que yo apruebe el informe de la Fase 1.
- Si algo del documento rector es ambiguo, contradice el código real o
  requiere una decisión que no está tomada (la sección 5 del documento
  lista varias): **no decidas por tu cuenta. Preguntame, de a una
  pregunta por vez.**
- Branch `fix/panel-conexiones`. Commits con mi autoría y vos como
  `Co-authored-by`. No tocás `demo`.
- Nada de lo que hagas puede cambiar un resultado numérico del panel ni
  aflojar privacidad o aislamiento: `test_dashboard.py` tiene que seguir en
  verde tal cual está, sin modificar un solo assert.
- Un archivo de test por proceso (convención de `CLAUDE.md`, "Comandos
  útiles").

## Fase 1 — Auditoría con evidencia (sin cambiar código)

Confirmá o refutá cada punto de la sección 2 del documento rector **contra
el código real**, y devolveme un informe con este formato exacto:

```
### 2.1 Sesiones anidadas — CONFIRMADO | REFUTADO | PARCIAL
Evidencia: <archivo:línea de cada llamada que abre una segunda sesión
mientras otra está abierta>
Endpoints afectados: <lista>
Con qué filtros se dispara: <empresa | afiliado | siempre>
```

Lo mismo para 2.2, 2.3 y 2.4. Además:

1. **Reproducción local.** Escribí (sin commitear todavía) el test C5
   (`test_dashboard_concurrencia.py`: engine con `pool_size=2,
   max_overflow=0`, un sindicato con 3 empresas y recibos, filtro de
   empresa activo, 20 refrescos simultáneos con `threading`). Corrélo
   contra `main` y pegame el resultado tal cual: si se cuelga o da
   `TimeoutError`, el diagnóstico está confirmado; si pasa, decime por
   qué y **parás ahí** hasta que lo veamos juntos.
2. **Medición.** Corré `medir_dashboard.py` y pegame los tiempos de cada
   endpoint, en particular `limites_bruto` (`percentile_cont`) — es el
   insumo para fijar `statement_timeout`.
3. **Inventario de sesiones.** Listá todas las funciones de `dashboard.py`
   que abren `db.get_session()` y desde dónde se llama cada una. Si hay
   más anidamientos que los del documento, sumalos.
4. **Preguntas** de la sección 5 del documento, de a una.

Esperá mi OK sobre el informe.

## Fase 2 — Corrección

Implementá C1 a C8 en este orden, **un commit por corrección**, con su test
en el mismo commit:

- **C1** una sesión por request (la solución que elijas entre "pasar la
  sesión" o "resolver en `parsear_filtros`" me la proponés en la Fase 1;
  no la decidas sola).
- **C2** engine con `pool_timeout`, `statement_timeout`,
  `idle_in_transaction_session_timeout`; handler de
  `sqlalchemy.exc.TimeoutError` → 503 JSON; `lock_timeout` en
  `migrations/env.py`; `pool_size`/`max_overflow` por env.
- **C3** cupo del panel con `BoundedSemaphore`; 503 con `detail`.
- **C4** front: cola de 4, debounce 400 ms, contadores después.
- **C5** el test de concurrencia ya escrito en la Fase 1, ahora en verde.
- **C6** `/healthz` y `/readyz`; actualizar `DESPLIEGUE_RENDER.md`.
- **C7** `carga/k6/test3_panel.js` + su entrada en `carga/correr.sh`. No
  lo corras vos contra Pruebas: dejalo listo y decime el comando.
- **C8** sección "Si la app no responde" en `docs/OPERATIVA.md`.

Al terminar, antes de dar por cerrado:

1. Checklist de aceptación de la tabla de la sección 3 del documento,
   **punto por punto con el resultado de cada uno** (comando + salida).
2. `test_dashboard.py`, `test_dashboard_concurrencia.py`,
   `test_migraciones.py` y `test_error_no_manejado.py` en verde, cada uno
   en su proceso.
3. Sección nueva en `HISTORIAL.md` con la causa real y qué se cambió.
4. Texto para `CLAUDE.md`: en "Decisiones tomadas" la regla "**una sesión
   de base por request; ningún helper abre la suya si recibe una**", y en
   "Estado actual" el cupo del panel y los timeouts con sus variables de
   entorno.
5. Línea para `BITACORA.md` y `python generar_bitacora.py`.
6. PR contra `main` con el resumen; no mergees hasta que yo lo revise.

Empezá por la Fase 1.
