# PLAN — Asistente de consultas sobre el convenio (RAG)

Rama `rag-convenio`, salida de `main` en `90a38f0`. Plan acordado antes de
escribir código. Documenta el plan **tal cual se escribió**; no se actualiza
retroactivamente (mismo criterio que SPRINT_REFORMA.md y SPRINT_AREAS.md).

## Qué es y qué NO es

El trabajador escribe una pregunta en lenguaje natural sobre su convenio
colectivo o sus condiciones de trabajo, y recibe una respuesta redactada a
partir de los documentos que su sindicato cargó, **citando siempre la
fuente**.

**No toca la validación de recibos.** Es una feature aparte, de menor riesgo.

**Es un piloto, y eso cambia cómo se construye.** El objetivo declarado es
aprender el patrón RAG para poder aplicarlo después a algo más crítico.
Volver atrás o a cero es un costo de aprendizaje aceptado. Consecuencia
práctica: se prioriza **llegar rápido a medir la calidad de recuperación**
por sobre pulir la UI. El panel de carga del bloque 2 va a ser
deliberadamente feo — lo que el piloto tiene que enseñar es si el troceo y
el modelo sirven, no si el formulario es lindo.

## Decisiones cerradas

Las nueve que se acordaron una por una antes de escribir esto:

1. **Embeddings LOCALES con runtime ONNX** (sin `torch`). El driver no
   terminó siendo ni el costo ni la confidencialidad — sobre eso, ver
   "Qué NO resuelve esta arquitectura" más abajo — sino que el modelo queda
   **pinneado** (una API puede cambiar su modelo y dejar los vectores
   guardados incomparables con las consultas nuevas) y que **reindexar sale
   gratis**, que en un piloto donde el troceo va a cambiar varias veces vale
   más que la diferencia de calidad.
2. **Todo detrás de `generar_embedding(texto)`**: cambiar de local a API
   tiene que ser cambiar una función, no re-arquitecturar.
3. **El nombre del modelo se guarda en cada fragmento.** Permite detectar un
   estado mezclado en vez de que la búsqueda devuelva basura en silencio, y
   reindexar por lotes.
4. **Medir la recuperación ANTES de construir la UI** (ver bloque 3b).
5. **Un sindicato puede tener VARIOS convenios**, y **el trabajador elige**
   cuál en la interacción. No se infiere del empleador ni de la categoría:
   inferirlo sería frágil y contestar con el convenio equivocado es peor que
   no contestar.
6. **La vigencia la declara el admin sobre el DOCUMENTO**, no sobre cada
   fragmento. Un acta no dice de forma confiable qué artículo modifica, así
   que no se puede calcular. Los fragmentos heredan la vigencia de su
   documento.
7. **Documentos absorbidos**: cuando un texto ordenado ya incorpora actas
   anteriores, el admin marca las viejas como **no vigentes** (quedan
   guardadas, salen de la búsqueda). Revisión periódica como proceso.
8. **Los "datos asociados" del admin SE INDEXAN**, marcados como fuente
   distinta (`observacion`). Suelen estar en lenguaje llano, que se parece
   más a cómo pregunta un trabajador que el articulado formal. La cita tiene
   que aclarar cuándo la respuesta sale de una observación del sindicato.
9. **PDF escaneado: OCR automático, con Claude**, reusando `pdf2image` +
   visión que el proyecto ya tiene en `extractor.py`. Cero dependencias
   nuevas y mejor calidad sobre texto jurídico que un OCR clásico. Cuesta
   por página, una vez por documento: se avisa el costo estimado antes de
   procesar.

## Arquitectura

```
   [Admin]  PDF  ──► extracción de texto ──► troceo ──► generar_embedding()
                     (nativo, u OCR con         │            (ONNX local)
                      Claude si es escaneo)     ▼
                                          pgvector  (mismo Postgres de Render)
                                                │
   [Trabajador]  pregunta ──► generar_embedding() ──► búsqueda por similitud
                                                       filtrando SIEMPRE por
                                                       sindicato_id + convenio
                                                       + vigente
                                                            │
                                                            ▼
                                              Claude redacta la respuesta
                                              con el contexto recuperado
```

**Claude no participa de la búsqueda.** La recuperación la hace pgvector
comparando vectores. Claude entra recién con el contexto ya recuperado, para
redactar y citar.

## Lo que midió el piloto antes de escribir código (2026-08-23)

Se midió con material real: el convenio de AEFIP (74 páginas, 174 artículos)
y 18 preguntas, 16 con artículo esperado y 2 que el convenio NO contesta.

### Resultado

| Modelo | dim | recall@3 | recall@8 | margen positiva-negativa |
|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | 65% | 76% | -0,029 |
| paraphrase-multilingual-mpnet-base-v2 | 768 | 24% | 47% | -0,106 |
| **intfloat/multilingual-e5-large** | **1024** | **82%** | **94%** | **+0,011** |

**Modelo elegido: `intfloat/multilingual-e5-large`, `vector(1024)`.**

### Por qué mpnet perdió siendo el doble de grande que MiniLM

No es tamaño, es **familia**. Los `paraphrase-*` están entrenados para
similitud SIMÉTRICA (¿estas dos frases dicen lo mismo?). RAG es ASIMÉTRICO:
una pregunta corta contra un párrafo largo de otro registro. e5 está
entrenado para recuperación, y por eso usa los prefijos `query:` /
`passage:` — que hay que usar, o se pierde la ventaja.

Regla para el futuro: **elegir por familia antes que por dimensión.**

### El hallazgo que cambia el diseño: la baranda no puede ser un número

El margen de e5 es positivo pero de **0,011**:

| | similitud |
|---|---|
| peor pregunta legítima (donar sangre) | 0,826 |
| **"¿cómo se afecta mi SIPES?"** (el convenio NO lo contesta) | **0,816** |
| "¿cuánto vale el m² en Puerto Madero?" | 0,766 |

La pregunta del SIPES recuperó los artículos 63 y 64 — justificación de
inasistencias — porque la pregunta ES sobre inasistencias. **Los vectores no
distinguen "habla del tema" de "contesta la pregunta"**: esa diferencia es
semántica, no geométrica.

Por lo tanto:

- El umbral de similitud queda como **primer filtro barato** para lo
  evidente (Puerto Madero a 0,766), NO como el control principal.
- **La baranda de "no lo encontré" la aplica Claude** leyendo el material
  recuperado, con instrucción explícita de decir que no lo encontró si lo
  recuperado no contesta la pregunta.
- **Test de aceptación del bloque 3**: preguntar por el SIPES. Si el sistema
  contesta algo sobre el artículo 63, FALLÓ — aunque el recall sea 94%.

### Lo que el convenio real enseñó sobre el troceo

1. **Las notas de acta van FUERA del texto vectorizado.** Son ~116 con
   redacción casi idéntica; adentro harían que el 60% de los artículos se
   parezcan por su boilerplate. Van como metadato de la cita.
2. **Los encabezados de sección van al fragmento SIGUIENTE.** Están escritos
   antes del marcador del artículo al que pertenecen, así que un corte
   ingenuo se los pega al anterior. Caso real: "6) INDEMNIZACIÓN ESPECIAL
   POR JUBILACIÓN" quedaba al final del artículo 23, que habla de
   guarderías.
3. **Sub-trocear los artículos largos.** Van de 67 a 11.812 caracteres; los
   29 que superan el límite del modelo se truncaban EN SILENCIO.

Con esos tres arreglos: 246 fragmentos, mediana 836 caracteres.

### Memoria: la indexación va POR LOTES, y no es opcional

Embeber los 246 fragmentos de una sola vez pidió **738 MB** en un array
(246 × 512 tokens × 768 dims en float64) y reventó el proceso. Con 1024
dims pide ~1 GB.

- Lotes de 8-16 fragmentos al indexar.
- **El pico de memoria al INDEXAR es mayor que el del modelo en reposo**: la
  instancia se dimensiona por el momento de la carga, no por el de la
  consulta.
- Refuerza que **la carga del convenio no puede correr dentro del request
  del admin**: tarda y consume. Tiene que reportar progreso.

### Lo que NO hizo falta

`multilingual-e5-large` pesa 2,1 GB y tarda ~75 s en bajar la primera vez.
El convenio de AEFIP tiene texto nativo (251.356 caracteres): **no hizo
falta OCR**. La rama de OCR sigue en pie para otros sindicatos.

## Esquema de datos (borrador)

Cuatro tablas. Todo con Alembic, nunca `create_all`.

```
Convenio
  id, sindicato_id, nombre, codigo, activo, creado

DocumentoConvenio
  id, convenio_id, sindicato_id
  tipo               convenio | acta
  titulo, fecha_documento
  archivo_datos (bytes), archivo_mime, archivo_nombre
  observaciones                 <- el campo de "datos asociados"
  observaciones_fecha
  vigente (bool)                <- lo declara el admin
  vigencia_desde, vigencia_hasta (nullable)
  origen_texto       nativo | ocr
  caracteres_extraidos, paginas
  creado

FragmentoConvenio
  id, documento_id, convenio_id, sindicato_id
  orden, texto
  referencia                    <- lo que se cita: "Artículo 47", "Acta 2024-03"
  tipo_fuente        convenio | acta | observacion
  embedding          vector(1024)   <- e5-large, medido
  modelo_embedding                  <- 'fastembed-0.8.0/intfloat/multilingual-e5-large'
  creado

ConsultaConvenio                <- bloque 5
  id, sindicato_id, convenio_id, cuil
  pregunta, hubo_respuesta (bool)
  fragmentos_usados (JSON de ids)
  creado
```

Notas de diseño:

- **`sindicato_id` desnormalizado en Fragmento** a propósito: la búsqueda
  vectorial filtra por él en el camino caliente y no queremos un join ahí.
  Mismo criterio de aislamiento total que el resto de la app.
- **`vigente` y `vigencia_desde/hasta` conviven y no son lo mismo.** El bool
  responde *"¿entra en la búsqueda hoy?"* — es lo que el admin marca. Las
  fechas responden *"¿en qué período rigió?"*, que hace falta para una
  consulta retroactiva ("¿qué decía en 2024?"). Las fechas son baratas de
  agregar ahora e imposibles de reconstruir después.
- **`referencia` es texto libre**, no un número de artículo estructurado.
  Con actas que no siguen un formato fijo, forzar estructura garantiza
  perderla. Lo que importa es que sea legible en la cita.
- **El PDF se guarda en la base** (bytes), siguiendo el patrón del proyecto
  — no hay disco persistente en Render. **Riesgo a vigilar**: un CCT puede
  pesar decenas de MB, bastante más que un logo o un adjunto. Si crece, la
  salida es guardar solo el texto extraído y no el binario.

## Secuencia de bloques

Un bloque por vez. Plan de cada bloque antes de escribir código, verificación
real antes de avanzar al siguiente.

### Bloque 1 — Esquema
- **Cambiar `docker-compose.yml` a `pgvector/pgvector:pg16`** y recrear el
  volumen. Verificado: la imagen `postgres:16` actual **no tiene pgvector**
  (`pg_available_extensions` devuelve 0 filas). Sin esto el bloque 1 no
  arranca.
- Confirmar que el Postgres de Render tiene la extensión disponible.
- ~~Elegir el modelo ONNX y su dimensión~~ **YA MEDIDO**:
  `intfloat/multilingual-e5-large`, `vector(1024)`. Ver la sección de
  medición más arriba.
- Migración Alembic: `CREATE EXTENSION IF NOT EXISTS vector` + las 4 tablas.
- Entrada `convenio` en `modulos.py`, **fuera de `MODULOS_INICIALES`**
  (opt-in por sindicato, el patrón que el proyecto ya usa).

### Bloque 2 — Carga y troceo (admin)
- Subir PDF, extraer texto (nativo; OCR con Claude si no hay texto),
  trocear por artículo/cláusula, generar embeddings, guardar.
- **Vista previa con el texto de los primeros fragmentos**, no solo el
  conteo: un troceo malo pasa el "se detectaron N fragmentos" y arruina todo
  lo que viene después.
- Aviso de costo estimado antes de OCRear.
- Al subir un documento más nuevo que otros del mismo convenio, avisar
  *"hay N documentos anteriores — ¿siguen vigentes?"*. Es el momento en que
  la persona tiene el contexto fresco; más barato que un recordatorio.

### Bloque 3 — Recuperación, y medirla antes de la UI
**3a.** Búsqueda: vectorizar la pregunta, buscar en pgvector filtrando
siempre por `sindicato_id` + convenio elegido + `vigente`.

**3b. Re-medir sobre la base real.** La medición ya se hizo en memoria
(94% recall@8); acá se repite contra pgvector para confirmar que la búsqueda
en base da lo mismo que el cálculo directo. Si difiere, el problema está en
el índice o en el filtro, no en el modelo.

**3c.** Prompt a Claude con lo recuperado y las barandas.

### Bloque 4 — El link oculto y la activación
Ruta del trabajador **no listada en el menú**, activada por el módulo.

### Bloque 5 — Registro de consultas
**Se adelanta si es posible**: las preguntas que la gente hace son el único
dato que dice si el troceo funciona. Si el bloque 3 sale sin registro, se
pierde justo la evidencia que el piloto tiene que producir.

## Barandas de la respuesta (no negociables)

- **Citar siempre** de qué documento y artículo/acta sale la respuesta, y
  aclarar cuándo sale de una observación del sindicato y no del convenio.
- **Si no hay nada relevante indexado, decirlo**: "no lo encontré, consultá
  con tu sindicato". Nunca inventar.
- **Disclaimer fijo**: no es asesoramiento legal.

Cómo se verifica que las barandas funcionan: **la pregunta del SIPES**
("¿cómo se afecta mi SIPES si tengo inasistencias?"). El convenio no lo
contesta, pero la búsqueda devuelve los artículos 63 y 64 con similitud
altísima (0,816) porque son sobre inasistencias. Si el sistema redacta algo
sobre el artículo 63, FALLÓ. Es el test de aceptación del bloque 3, y la
razón por la que la baranda vive en el prompt y no en un umbral.

## Qué NO resuelve esta arquitectura

Vale dejarlo escrito para no confundirse después: **los embeddings locales
no protegen la pregunta del trabajador.** La pregunta es el dato sensible
—revela su situación personal— y para redactar la respuesta **igual va a
Claude**. Lo que se gana con local es un proveedor menos y un modelo estable,
no confidencialidad del contenido. El texto de los convenios, por su parte,
es público (se registra y publica en el Ministerio de Trabajo), así que no
había nada que proteger de ese lado.

## Riesgos y decisiones abiertas

- ~~Calidad de recuperación en español jurídico~~ **RESUELTO**: 94%
  recall@8 medido con material real. Dejó de ser un riesgo.
- **Riesgo nuevo, el principal ahora: que Claude conteste igual cuando no
  debería.** El margen entre una pregunta legítima y una que el convenio no
  contesta es de 0,011 — indistinguible por umbral. Todo el peso cae en el
  prompt del bloque 3c.
- **Memoria al indexar** (ver la sección de medición): la instancia se
  dimensiona por el pico de carga, no por el de consulta.
- **Nombre del convenio en el selector**: es lo único que va a guiar al
  trabajador. "CCT 260/75" no le dice nada a nadie. Hay que empujar al admin
  a poner un nombre entendible.
- **Costo del OCR** con un CCT largo. Se acota avisando antes de procesar.
- **Peso de los PDF en la base** (ver notas del esquema).

## Interacción con la rama `areas-permisos` (importante)

`areas-permisos` (el sprint de Áreas y permisos, ya terminado y sin mergear)
exige que **toda ruta `/admin/*` esté declarada en `PERMISOS_RUTAS`**, y una
ruta sin clasificar **se rechaza** — falla cerrado, por diseño.

Si RAG llega a `main` primero, al mergear `areas-permisos` **el panel de
carga del convenio va a dejar de funcionar** y el error va a parecer
inexplicable.

El arreglo son cinco líneas: sumar la sección nueva a `permisos.py` y las
rutas de RAG a `PERMISOS_RUTAS`. **Pero hay que acordarse.** Queda anotado
acá y en BACKLOG.md.

## Método

- Un bloque por vez; plan de cada bloque antes de escribir código.
- Verificación con pruebas reales, no simuladas.
- Tests uno por archivo (`bash correr_suite.sh` — está en `areas-permisos`;
  si RAG avanza primero conviene traerlo). **Nunca `pytest -q` batcheado.**
- Al cerrar cada bloque: HISTORIAL.md con el detalle técnico, CLAUDE.md con
  el resumen corto si corresponde.
- **No se arranca el bloque 2 hasta que el esquema del bloque 1 esté
  confirmado.**
