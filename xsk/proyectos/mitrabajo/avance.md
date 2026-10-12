---
iteracion: 1
etapa_actual: 8
etapa8: en_curso
etapa0: hecha
etapa1: hecha
etapa2: hecha
etapa3: hecha
etapa4: hecha
etapa5: en_curso
etapa6: hecha
etapa7: hecha
etapa9: pendiente
actualizado: 2026-10-12
---

## Cómo seguir

Cerrado el lote INF: H-0014 (deps con CVE, Parcial — multipart/jinja2/dotenv
al día + anthropic pinneado; falta el salto fastapi/starlette) y H-0015 (CI,
Solucionado — .github/workflows/ci.yml corre cada test_*.py + pip-audit).

Estado del kit: 9 Solucionado, 3 Parcial, 5 Pendiente, 2 Aceptado; bloquean 1.

2026-09-23, durante la portación a la demo: **H-0019 abierto** — las claves
semilla de los dos superadmin de plataforma están en el repositorio, que es
público, y `arsantagati` todavía no hizo su primer ingreso ni en Pruebas ni
en Demo, así que esa clave sirve hoy. SDN decidió dejarlo anotado sin tocar
los usuarios.

2026-10-10: arranca la serie para regularizar las observaciones, con el
CUIL/CUIT (`PLAN_CUIT_MOD11.md`): test **IDS-06** nuevo en el catálogo,
**H-0020** en corrección (las altas ya exigen el módulo 11; falta correr
`regularizar_cuit.py` en Pruebas y Demo) y **H-0021** abierto (reportar y
enviar al sindicato toman el CUIL y el recibo del cuerpo del pedido: IDOR
dentro del sindicato). La medida que sigue es el alta de usuarios (H-0017).

2026-10-11: **análisis estático continuo en el CI** (job `auditoria`).
Frenan el PR, por decisión de SDN: `ruff` (errores de Python, `ruff.toml`) y
`bandit` de **severidad alta**. Los de **severidad media** no frenan: quedan
informados en el CI y van a una **revisión grupal de código**, pendiente de
programar: los 63 de la línea de base (8 `B310` de `urlopen`, 55 `B608` de SQL
armado con texto; detalle en `corridas/2026-10-11-2040-ENT.md`) se miran uno
por uno en equipo, se marcan `# nosec` con su motivo los que estén bien y se
abre hallazgo por los que no. Es el cierre manual de ENT-04 y entra en la
iteración 2 (ver `alcance.md`).

El único que bloquea es H-0008 (rate-limit de login), que cierra con el
**perímetro (INF-05, Cloudflare + dominio propio)** — depende de infra de SDN.

Pendientes que quedan: H-0019 (claves semilla públicas), follow-up de H-0014
(fastapi/starlette 1.x), H-0018 (panel cross-entorno público), H-0010/H-0012 (con un cambio de sesión), carga
DIS-01/02, INF-02/03/05 (accesos, backups, perímetro), y la iteración 2
(ENT/IA/OBS/LEY).

2026-10-11: **segunda medida de la serie, el registro** (`PLAN_REGISTRO.md`,
PR #93): registro confirmado por mail con niveles de fiabilidad 1-4 como dato
de la cuenta, recuperacion de clave, clave temporal con cambio obligatorio,
Turnstile y freno en el registro. **H-0017 en correccion** (codigo completo;
Solucionado cuando Resend y Turnstile esten configurados en Pruebas) y
**H-0022 abierto y aceptado** (enumeracion inherente al diseno, D11). El QA
del sprint encontro cinco defectos de seguridad que se cerraron antes del
merge (detalle en `corridas/2026-10-11-2300-IDS.md`). Metodo nuevo que vale
registrar: desarrollo por agentes en olas con QA adversarial por bloque, y
los hallazgos del QA quedan como tests `test_qa_*.py` que pasan de rojo a
verde con el arreglo.


2026-10-12: **entra una dependencia de JavaScript vendoreada**, Preact
10.29.8 + htm 3.1.1, solo para la v2 del Panel Sindical
(`PLAN_DASHBOARD_V2.md`, bloque 1). No pasa por pip-audit: su control es
`static/vendor/preact/ORIGEN.md` (versión, integridad de npm y SHA-256 de cada
archivo), que `test_dashboard_v2.py` compara byte a byte. Queda anotado para
INF en la iteración 2: los vendoreados de JavaScript (Chart.js 4.4.9, Leaflet
1.9.4, vis-network, Preact, htm) no tienen hoy ninguna auditoría automática de
CVE. La v2 además prohíbe por test armar HTML como texto (`innerHTML` y
afines), que en la v1 es la única barrera contra XSS en lo que pinta el panel.

2026-10-12: **verificación** (`corridas/2026-10-12-2215-VERIFICACION.md`). Se
re-corrieron sobre `main` los tests de regresión de todo lo `corregido`:
H-0001, H-0002, H-0003, H-0005, H-0006, H-0009, H-0015, H-0016 y H-0021 pasan
a `verificado` (H-0004 ya lo estaba). Siguen igual, mirado en vivo: H-0017
(captcha y mail apagados en Pruebas), H-0020 (la Demo sigue en 0.40.01 sin
regularizar), H-0014 (fastapi 0.115.5), H-0018, H-0010 y H-0012. La solapa
Seguridad de `/entornos` dejó de mostrar esta sección (pedido de SDN): lo
pendiente se lee en "Estado de resolución".

Estado del kit: 10 Solucionado (todos verificados), 5 Parcial, 4 Pendiente,
3 Aceptado; bloquean producción 3: **H-0019** (claves semilla públicas: que
`arsantagati` entre o se le resetee la clave en Pruebas y Demo), **H-0008**
(cierra con el perímetro INF-05) y **H-0020** (regularizar la Demo en la
próxima promoción).
