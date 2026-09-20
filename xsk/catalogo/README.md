# Catálogo de tests de XSK

Un archivo por test, nombrado por su id (`IDS-01.md`). Genérico: describe
**qué** se verifica y **cómo**, para cualquier sistema; lo que cambia por
proyecto (URLs, cuentas, entorno) sale de `proyectos/<nombre>/configuracion.md`.

Formato en `_plantilla.md`. El motor (`motor/registro.py`) valida cada
archivo y falla nombrando la clave que falta.

## Los nueve ejes

| Sigla | Eje |
|---|---|
| IDS | Identidad y sesiones |
| AUT | Autorización y aislamiento |
| ENT | Entradas |
| IA | Superficie de la IA |
| DAT | Datos y criptografía |
| DIS | Disponibilidad y abuso |
| INF | Infraestructura y cadena de suministro |
| OBS | Detección y respuesta |
| LEY | Protección de datos |

## Tipos de test

| tipo | Qué es | Quién lo corre |
|---|---|---|
| `revision` | lectura del código con criterio de seguridad | Code con `security-review` / `code-review` + la skill `xsk` |
| `estatico` | herramienta sobre el código o las dependencias sin ejecutar nada | Code (`bandit`, `semgrep`, `pip-audit`, `gitleaks`…) |
| `dinamico` | pedidos reales contra el entorno de prueba | Code (`httpx`, Playwright, `k6`) |
| `configuracion` | consulta a la API del hosting / DNS / perímetro | Code (API de Render, Cloudflare, GitHub) |
| `manual` | lo que solo una persona puede verificar | la persona, con Code guiando |

## Reglas

- **`destructivo: si`** marca un test que altera datos o tira el servicio
  (carga, fuerza bruta que bloquea cuentas, borrado). Solo corre en los
  entornos que `configuracion.md` del proyecto autoriza, nunca por defecto.
- Cada test nombra el **activo** que protege. Si no protege ninguno del
  modelo de amenazas del proyecto, no entra al alcance.
- Referencias: OWASP Top 10 2021 (`A01`…`A10`), ASVS 4.0 (`V2.1.1`), CWE
  (`CWE-307`). Si un test no cae en ninguna, `owasp: -` y se explica en el
  cuerpo por qué.
- El catálogo **crece con cada proyecto** y nunca se recorta: un test que
  para este sistema no aplica se marca `no_aplica` en la corrida, no se
  borra del catálogo.
