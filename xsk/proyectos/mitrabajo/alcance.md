---
proyecto: mitrabajo
etapa: 3
iteracion: 1
fecha: 2026-09-20
ejes: IDS, AUT, DAT, INF, DIS
ejes_parciales: ENT (solo ENT-01 cabeceras), LEY (solo LEY-01 clasificación)
entornos: pruebas, demo
destructivos_en: pruebas
---

# Etapa 3 — Alcance de la iteración 1

## Qué entra y por qué

El modelo de amenazas (`amenazas.md`, última sección) concentra lo que
amenaza a los activos 1, 2, 3, 6 y 7 en cuatro grupos. La iteración 1 es
esos cuatro grupos, que son los cinco ejes que **bloquean salir con un
sindicato real**:

| Eje | Por qué en la iteración 1 | Amenazas que cubre |
|---|---|---|
| **AUT** Autorización y aislamiento | la identidad del trabajador y del empleador es forjable (O2) y cruza recibos, trámites e identidad; el aislamiento entre sindicatos es la promesa comercial | V1, V5, V6, V7 |
| **IDS** Identidad y sesiones | cuatro logins sin defensa, cookies sin `Secure`, sin revocación, plataforma compartida (O8, O9, O13, O20, R1) | V6, V3 |
| **DAT** Datos y criptografía | secretos con default en el código (O1, O3, O4); logs sin scrubbing (O16) | V8, V6 |
| **INF** Infra y cadena de suministro | dependencias, GitHub, Render, backups nunca restaurados (O18, R7) | V8, V9, V4 |
| **DIS** Disponibilidad y abuso | sin rate limit ni topes, sin perímetro (O11, O12); una hora de tolerancia (R8) | V4 |

Dos tests de ejes de la iteración 2 entran **ahora**, porque son de
configuración y cubren varias amenazas de una:

- **ENT-01 Cabeceras de seguridad** (O7): un middleware que cambia la
  contención de todo XSS, clickjacking y sniffing.
- **LEY-01 Clasificación de datos**: sin el mapa de dónde vive cada dato
  sensible no se puede decidir qué se loguea (DAT-05) ni qué viaja a
  terceros (IA-05, LEY-06).

## Qué queda para la iteración 2

**ENT** (uploads, XSS, CSRF, SQL, redirección, CORS), **IA** (inyección de
prompt vía recibo y vía PDF, conceptos que entran a la base, gasto), **OBS**
(alertas de ataque, registro de acciones, runbook) y **LEY** (consentimiento,
retención, derechos, contrato de encargado, AAIP).

Con una salvedad: **R2 (niveles de fiabilidad de registro) es una decisión
de producto que conviene diseñar antes del primer sindicato**, aunque su
implementación entre en la iteración 2. IDS-06 la deja registrada como
hallazgo con esa nota.

## Reglas de esta iteración

- Tests dinámicos contra **Pruebas** primero; **Demo** solo para confirmar
  que una corrección promovida sigue en pie. Los `destructivo: si` (carga,
  fuerza bruta que bloquee cuentas) **solo en Pruebas**.
- Los tests que gastan créditos de Anthropic (IA) no entran en esta
  iteración; los de DIS que tocan `/api/leer` se hacen con
  `MOCK_EXTRACTOR=1` (Pruebas ya lo tiene).
- Cada eje se corre entero antes de pasar al siguiente, en este orden:
  **AUT → IDS → DAT → INF → DIS**, porque las correcciones de AUT (firmar la
  identidad) cambian cómo se prueban los demás.
- La clasificación (etapa 7) se hace **al cierre de cada eje**, con SDN, de
  a un hallazgo, no al final de los cinco.

## Criterio de cierre de la iteración

El de `METODO.md`: ningún Crítico ni Alto en `abierto`/`en_correccion`
dentro de estos cinco ejes; Medios con dueño y fecha; aceptados firmados;
última corrida de los cinco ejes sin `error`.
