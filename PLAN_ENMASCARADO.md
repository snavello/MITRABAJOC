# PLAN_ENMASCARADO.md — Los datos que identifican a la persona no salen hacia la IA

**Estado:** acordado con SDN el 2026-09-24, **sin empezar**. Rama
`feature/enmascarado-pii`. Es el **paso cero del motor v2**: se hace antes
que `PLAN_MOTOR_V2.md` y absorbe su enganche D7 (ítem 1.2) y parte del 1.1
(leer todas las páginas).

**De dónde sale.** De la arquitectura acordada en Chat el 2026-08-28
(`docs/chat/2026-08-28-arquitectura-enmascarado-pii.md`, copiada sin
cambios). Este plan la conserva en lo esencial y la corrige donde el código de
hoy la contradice o donde hay una forma más simple. Cada cambio respecto del
original está marcado con **[cambia]** y su motivo.

Como todo plan acordado, este archivo **no se edita** una vez empezado: el
avance va en "Estado actual" de `CLAUDE.md`, el detalle en `HISTORIAL.md`.

---

## 1. Objetivo y líneas rojas

Hoy la imagen completa del recibo —nombre, CUIL, DNI, legajo, cuenta bancaria,
CUIT y razón social del empleador— se manda tal cual a la API de Anthropic.
Después de este plan, **lo que identifica a la persona se tapa en el servidor
antes de salir**, la IA lee importes, conceptos y estructura como hasta ahora,
y la identidad se vuelve a poner del lado nuestro.

No es una cuestión de costos: es el argumento de confidencialidad ante los
sindicatos ("los datos que te identifican no salen de nuestros servidores"),
y es coherente con la Ley 25.326 —la afiliación sindical es dato sensible— y
con el eje DAT de XSK.

Líneas rojas, que valen para cada bloque:

1. **Cero regresión en la lectura.** Mismos importes, mismas líneas, misma
   clasificación de cada línea, con y sin enmascarado.
2. **Si el enmascarado no está seguro, el recibo no sale.** Nunca "lo mando
   igual por las dudas".
3. **No es un cuello de botella** (números en §5).

---

## 2. Qué se conserva del documento de agosto

- La lectura local sirve **solo para ubicar qué tapar**, nunca para leer el
  recibo. La IA sigue haciendo lo que hace bien.
- No se detecta "cualquier dato personal" con un modelo genérico: alcanza con
  **lo que ya se conoce** (el CUIL de la sesión, el nombre de la persona) más
  los **patrones argentinos** (CUIL/CUIT, DNI).
- La **verificación de pertenencia** se muda al paso local, antes de tapar.
- Nada de modelo local de lectura completa (necesitaría GPU; Render no la
  tiene y se perdería fiabilidad).
- La política de "no lo encontré" es de producto y va explícita (§6).

---

## 3. Qué cambia respecto de agosto, y por qué

**C1. [cambia] Dos caminos según el archivo, no un OCR para todo.**
- **PDF digital** (el que se baja del homebanking o del portal de la empresa):
  el PDF ya trae cada palabra con su posición exacta. No hace falta OCR, el
  tapado es exacto y cuesta milisegundos. El modelo de OCR ni se carga.
- **Foto o escaneo** (o un PDF que es solo una imagen): OCR local.

**C2. [cambia] `pypdfium2` y RapidOCR, no Tesseract ni PyMuPDF.**
- Tesseract es un programa del sistema; el entorno nativo de Render no deja
  instalarlo con `apt`. RapidOCR se instala con `pip` y corre sobre ONNX, lo
  mismo que ya usa `fastembed` en el piloto del convenio.
- PyMuPDF, la opción obvia para PDFs, tiene licencia **AGPL**: descartado para
  un producto comercial. `pypdfium2` (Apache/BSD) da texto con posiciones y,
  además, convierte a imagen: **reemplaza a `pdf2image`**, que depende de
  poppler, otro programa del sistema.
- De paso se leen **todas las páginas**: hoy `extractor._imagen_desde_pdf`
  manda solo la primera.

**C3. [cambia] Tapar anclado a rótulos, no solo a valores.** Además de buscar
el CUIL conocido, se tapa el valor que acompaña a los rótulos típicos
("CUIL", "Apellido y Nombre", "Legajo", "DNI", "CBU", "Cuenta", "Razón
social"). Así no depende de que el OCR lea bien una Ñ o un acento. Los
patrones de CUIL/CUIT se confirman con el **dígito verificador**, para no
tapar nunca un importe que tenga 11 cifras.

**C4. [cambia] Se tapa con un rótulo, no con un rectángulo negro.** Una
etiqueta visible ("CUIL OCULTO", "NOMBRE OCULTO") y una línea en el prompt
que dice que esas zonas son intencionales. Un rectángulo negro dispararía la
**alerta de adulteración** (que justamente busca tachaduras) y deja al modelo
"completando" un campo vacío.

**C5. [cambia] La identidad se rearma de la lectura local; la base confirma.**
El documento de agosto la tomaba de la base, pero eso choca con el
pluriempleo: `Trabajador.cuit_empleador` puede no ser el del recibo, y los
conceptos por empleador dependen de ese CUIT. Entonces:
- **CUIL** y **CUIT**: los lee el paso local (patrón + dígito verificador).
- **Nombre**: `CuentaTrabajador` de la sesión.
- **Razón social**: la tabla de empleadores por ese CUIT; si no está, el texto
  de la línea del CUIT leído localmente; si tampoco, queda vacío.
- **Efecto a favor**: un **recibo ajeno se corta antes de llamar a la IA**
  (E-RECIBO-04 / E-APORTE-03). Hoy se paga la lectura y el recibo de otra
  persona sale igual hacia Anthropic.

**C6. [cambia] Tres modos, no un interruptor:** variable `ENMASCARADO` =
`apagado` / `sombra` / `activo`.
- **sombra**: se calcula todo el tapado y se registra si se encontró todo y
  cuánto tardó, pero se sigue mandando como hoy. Da números reales de
  cobertura sin molestar a nadie, y con ellos se decide §6.
- Arranca `apagado` en todos lados; `sombra` en Pruebas en el bloque 5.

**C7. [nuevo] Control de fuga.** Sobre lo que se va a mandar se verifica que
no quede ningún CUIL/CUIT válido ni el apellido de la sesión a la vista (con
las palabras ya ubicadas, sin volver a leer). Si queda algo, el recibo no sale.

**C8. [cambia] Sin Background Worker de entrada.** Corre donde corre hoy la
preparación de la imagen (`run_in_threadpool`), con cupo propio (§5). Un
servicio aparte solo si la medición del bloque 2 lo pide.

---

## 4. El recorrido

```
archivo ──► palabras con posición ──► verificación de pertenencia ──► qué tapar ──► tapar con rótulo ──► control de fuga ──► IA ──► rearmar identidad ──► (flujo de hoy)
            PDF digital: pypdfium2    CUIL leído vs. sesión            patrones+DV     imagen por página    si falla: no sale
            foto/escaneo: RapidOCR    (ajeno: se corta acá)            conocidos
                                                                       rótulos
```

- El enganche es **uno solo**: `extractor.preparar_imagen()`, por donde ya
  pasan las cuatro salidas hacia la IA: recibo (`/api/leer`), comprobante de
  ARCA (`/api/aportes`), aprendizaje del admin (`/admin/aprender`) y el banco
  de pruebas de plataforma.
- **Aprendizaje**: no hay CUIL de sesión (el admin sube recibos de otros). Se
  tapa solo por patrones y rótulos, sin verificación de pertenencia.
- **Comprobante de ARCA**: CUIL y nombre en el encabezado; mismo mecanismo.
- **Recibo de formato nuevo (Anexo III)**: formato único, así que el
  encabezado se puede tapar por zona. Es una optimización para después del
  bloque 4, no un requisito.
- El OCR del **convenio escaneado** (`rag.py`) queda afuera: no tiene datos
  personales.

---

## 5. Memoria y tiempo: lo que tiene que dar

**Memoria.** El modelo de OCR (~200 MB) se carga **una vez por proceso**, al
arrancar, y lo comparten todos los recibos; **no se carga por recibo**. Un
PDF digital no lo usa nunca. Por recibo solo se suma la imagen de la página y
la memoria de trabajo del OCR, y se libera al terminar. El multiplicador real
es la cantidad de procesos: `render_planes.workers_para()` levanta uno por
núcleo, y cada uno tiene su copia del modelo. Si eso resulta caro, el OCR pasa
a un servicio aparte con una sola copia (decisión del bloque 2, con números).

**Cuello de botella.** Cupo por proceso, igual que `DASHBOARD_CUPO` del Panel
Sindical: como máximo 2 lecturas locales a la vez (`ENMASCARADO_CUPO`), el
resto espera su turno. El OCR corre con **un solo hilo** de CPU para no dejar
sin procesador al resto de los pedidos, y trabaja la foto achicada al tamaño
que necesita, no a la resolución del teléfono.

**Tiempo.** Hoy la espera la pone la IA (15–30 s). Esta capa no la estira.

**Criterios del bloque 2** — si alguno no da, se frena y se replantea:

| Qué se mide | Límite |
|---|---|
| Memoria fija por proceso (modelo cargado) | ≤ 250 MB |
| Memoria extra por recibo en curso | ≤ 60 MB |
| Tiempo agregado, PDF digital (p95) | ≤ 0,3 s |
| Tiempo agregado, foto de una página (p95) | ≤ 3 s |
| 10 subidas simultáneas (`carga/`, con `MOCK_EXTRACTOR=1`) | sin 503 ni caídas por memoria; el resto de la app sin demora visible |

Se mide con las condiciones de Pruebas (medio núcleo, 512 MB). Subir el plan
de Pruebas está autorizado por SDN si hace falta; el de producción se decide
con estos números y su costo mensual a la vista.

---

## 6. Política cuando no se encuentra lo que hay que tapar

Caso: en modo `activo`, el paso local no ubica el CUIL de la sesión en el
recibo (foto borrosa, recorte, escaneo malo) o el control de fuga falla.

1. Reintento local con la imagen mejorada (contraste, enderezado, más
   resolución).
2. Si sigue fallando: no se manda, y la persona ve un mensaje claro para que
   saque una foto más nítida. Código nuevo `E-RECIBO-05` / `E-APORTE-04`
   ("para proteger tus datos necesitamos una foto más nítida del
   encabezado"). Entra en la lista de códigos que sí pueden decir "probá con
   otra foto" (ver `errores.py`).
3. Mandar sin tapar, con aviso: **existe como configuración pero apagada**, y
   no se prende sin decisión explícita de SDN.

**Se decide con los números del modo sombra**: si la cobertura en fotos reales
es baja, hay que trabajar la lectura antes de pasar a `activo`, no pedirle a
media base que saque otra foto.

---

## 7. Bloques

Un bloque por vez; no se avanza sin cumplir el criterio del anterior. Tests
con pytest, un archivo por vez. La versión sube según `FLUJO.md` (la de
Plataforma por el banco de pruebas; la de Trabajador cuando cambie lo que ve
el afiliado).

| # | Bloque | Criterio para seguir |
|---|---|---|
| 0 | Rama, este plan y el documento de agosto en el repo. | Aprobado por SDN. ✔ |
| 1 | **`enmascarado.py`, puro y aislado** (no importa `db` ni toca la app): de "palabras con posición" a "qué tapar" (patrones con dígito verificador, datos conocidos, rótulos), imagen tapada con rótulo, control de fuga. `test_enmascarado.py`. | Con los 10 recibos sintéticos (`recibos_anonimizados_3`, identidad ficticia NIEVES, JULIA / 27-99999999-9) y al menos un PDF digital: CUIL, nombre, DNI, legajo, cuenta y CUIT tapados en todos; **ningún importe tapado**; imágenes revisadas a ojo. |
| 2 | **Lectores**: PDF digital con `pypdfium2`; fotos con RapidOCR (modelo cargado al arrancar, un hilo). Reemplazo de `pdf2image`. Medición. | Tabla de §5 cumplida. Si no, se frena y se replantea (servicio aparte / plan). |
| 3 | **Enganche**: `preparar_imagen` con `ENMASCARADO`, cupo, prompt ajustado (zonas ocultas y alerta de adulteración), verificación de pertenencia local antes de llamar a la IA, rearmado de identidad, en las cuatro salidas. Códigos de error nuevos. | Suite verde; E-RECIBO-04 se dispara **sin** llamar a la IA; con `apagado` todo igual que hoy. |
| 4 | **Banco de pruebas "con y sin enmascarado"** en `/plataforma` → Uso de IA, reutilizando `comparar_lineas`, y vista de la imagen tal como la recibe la IA. | Cero diferencias de importes y de clasificación de líneas sobre los 10 recibos. |
| 5 | **Sombra en Pruebas**: cobertura (encontrado / no encontrado / fuga), tiempo y camino (PDF / foto) visibles en Uso de IA. | Números para decidir §6 y pasar a `activo`. |
| 6 | **`activo`** en Pruebas y después en demo (con `promover_demo.py`). Hallazgo registrado en XSK (ejes IA/DAT), `CLAUDE.md` (decisión vigente + estado), `HISTORIAL.md`, bitácora; actualizar el informe `recursos/motor-recibos.html`. | — |

---

## 8. Riesgos

- **Memoria en Pruebas** (512 MB): lo mide el bloque 2 antes de comprometerse.
- **OCR y nombres**: el modelo de RapidOCR está entrenado sobre todo en
  inglés/chino; los números los lee bien, una Ñ o un acento no siempre. Por eso
  C3 (rótulos) y el nombre se busca de forma aproximada, no exacta.
- **Recibos raros**: un empleador con un diseño sin rótulos claros. Lo detecta
  el modo sombra, antes de afectar a nadie.
- **La alerta de adulteración deja de cubrir CUIL y CUIT**: están tapados. Se
  dice en `HISTORIAL.md` y en el prompt; totales y fechas se siguen cubriendo.

## 9. Fuera del alcance (y de Code)

- **Lo contractual**, para Legal y SDN: la API de Anthropic no entrena con los
  datos que recibe y ofrece acuerdos de retención cero; el mismo modelo está en
  AWS Bedrock y Google Vertex. El mensaje completo al sindicato es técnico
  ("los datos que te identifican no salen de nuestros servidores") más
  contractual ("lo que sale se procesa sin retención").
- El **bot del convenio** y el **Asistente del Panel** no mandan recibos a la
  IA; no se tocan.
