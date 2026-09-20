---
name: xsk
description: XSANDERS Security Kit — método de evaluación y corrección de seguridad en diez etapas (configuración, relevamiento, mapeo y modelo de amenazas, alcance, herramientas, ejecución, registro, clasificación, corrección, registro continuo). Usar para cualquier trabajo de seguridad del sistema (evaluar, testear, registrar un hallazgo, clasificar riesgos, corregir una brecha, ver el estado) y cuando el usuario diga /xsk.
---

# XSK — cómo guiar cada etapa

Leé primero `xsk/METODO.md` (el método, genérico) y
`xsk/proyectos/<proyecto>/avance.md` (dónde está este proyecto). El proyecto
por defecto en este repositorio es `mitrabajo`. El motor que lee y valida el
registro es `xsk/motor/registro.py`; usalo, no reimplementes el formato.

## Subcomandos

| Pedido | Qué hacer |
|---|---|
| `/xsk estado` | correr `registro.estado_proyecto("mitrabajo")` y resumir: etapa, ranking, qué bloquea producción, última corrida, cómo seguir |
| `/xsk etapa N` | ejecutar la etapa N según METODO.md; al terminar, actualizar `avance.md` |
| `/xsk correr EJE` | etapa 5 sobre un eje: correr cada test del catálogo de ese eje, dejar la corrida en `corridas/`, abrir hallazgos por cada `fallo` |
| `/xsk hallazgo` | registrar un hallazgo nuevo con `registro.proximo_id()`, desde la plantilla |
| `/xsk clasificar` | etapa 7: recorrer los hallazgos sin clasificar **con la persona, de a uno** |
| `/xsk corregir H-NNNN` | etapa 8: rama `fix/xsk-H-NNNN`, corrección, test de regresión, PR, estado `corregido` |
| `/xsk verificar` | re-correr los tests de los hallazgos `corregido`; los que pasan → `verificado`, los que no → `abierto` con la historia anotada |

## Reglas que no se negocian

1. **Preguntas de a una.** En relevamiento y clasificación, una pregunta,
   esperar la respuesta, seguir. Nunca una lista.
2. **Un test se conecta a un activo** de `amenazas.md`. Si no, no se corre.
3. **Entorno**: `configuracion.md` dice contra qué se puede pegar
   (`entornos_dinamicos`) y dónde se puede romper (`entornos_destructivos`).
   Un test `destructivo: si` fuera de esa lista no se corre, aunque lo pidan:
   se avisa y se propone el entorno correcto.
4. **Nada sensible en el registro.** Credenciales, tokens y URLs de bases
   van en `.env`. Un hallazgo cita la variable, no el valor. Antes de
   escribir un archivo de `xsk/`, releerlo buscando secretos.
5. **Cada corrida deja archivo** (`corridas/AAAA-MM-DD-HHMM-EJE.md`) con
   `version_app` y `commit` reales del entorno (`/api/version`). Un test que
   no pudo correr es `error`, nunca `paso`.
6. **Cada corrección deja un test de regresión** en la suite del proyecto
   (`test_*.py` en la raíz, uno por archivo como el resto). Sin test, el
   hallazgo no pasa a `corregido`.
7. **Estándares en todo**: `owasp`, `asvs`, `cwe` en cada test y hallazgo.
8. **Revisión de código** (`tipo: revision`): usar las skills
   `security-review` y `code-review` sobre los archivos que el test nombra,
   más lectura dirigida por el modelo de amenazas. Registrar lo que se
   revisó aunque no se encuentre nada: "revisado, sin hallazgos" es un dato.
9. **Lo que no se puede probar no se afirma.** Si un test del catálogo
   excede lo que Code puede hacer desde una máquina (DDoS real, escaneo
   desde otra red), se marca `no_aplica` con la nota de qué lo reemplaza
   (verificar el perímetro) y se le dice a la persona.
10. **Versión y bitácora como en el resto del proyecto**: la versión sube
    solo si se tocó código de la app (una corrección, la página); un
    bloque de XSK cierra con su línea en `BITACORA.md`.

## Al cerrar cada etapa

Actualizar `avance.md` (estado de la etapa, `etapa_actual`, "Cómo seguir")
y, si cambió lo que el proyecto tiene, `CLAUDE.md` → "Estado actual".
