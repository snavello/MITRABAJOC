# Plan de pruebas — implementación de La Bancaria

2026-11-02. Sigue a los 8 tests de carga del 9 y 10 de septiembre
(`carga/INFORME.md`) y al test 3 del Panel (19-09). Desde entonces la app
cambió en cosas que pesan bajo carga o en la exactitud, y ninguna se midió en
conjunto. Este plan las suma con un insumo nuevo: **el lote de recibos
bancarios con variantes** que SDN generó (`datos_prueba/bancaria/`).

## 1. Con qué contamos (no se reconstruye nada)

| Herramienta | Qué mide | Dónde |
|---|---|---|
| k6 test 1 (lecturas) y test 2 (subidas en ráfaga) | techo de navegación y de `/api/leer` con `MOCK_EXTRACTOR=1` | `carga/k6/`, `carga/correr.sh` |
| k6 test 3 (filtro frenético del Panel) | cuelgue por conexiones; 0 respuestas 500 | `carga/k6/test3_panel.js` |
| Informe comparado | consolida corridas en tests numerados | `carga/consolidar.py`, `generar_md.py`, `/entornos/informe` |
| `medir_dashboard.py` | agregados del Panel con 50.000 recibos | raíz |
| `test_grilla_bancaria.py` + 10 PDFs simulados | resultado esperado sin IA (motor real) | `docs/recibos-bancaria-prueba/` |
| Calculadora bancaria v2 | recibo leído contra grilla de agosto 2026 | `/entornos` → Herramientas |
| Laboratorio de modelos | mismo recibo con Claude, GPT, Kimi, Qwen | `/entornos` → Herramientas |
| Registro de enmascarado | qué se tapó, qué salió sin tapar y por qué | `/plataforma` → Uso de IA |
| Robots Playwright | flujos de punta a punta | `e2e/` |
| `cargar_bancaria.py` | sindicato + lote sintético del CCT 18/75 | raíz |

## 2. Qué cambió desde la última medición y por qué obliga a medir de nuevo

1. **Enmascarado activo** (24-09): OCR con Tesseract en el servidor, **antes**
   de la IA, con cupo 1 por proceso y presupuesto de 5 s. Corre **aunque esté
   `MOCK_EXTRACTOR=1`**: es CPU nueva en cada subida y el test 2 nunca la midió.
   Los 20 JPG de `carga/recibos/` no son comparables con un recibo bancario real.
2. **Corte de pertenencia y nivel 3** (`/api/leer`): un recibo de otro CUIL se
   corta con E-RECIBO-04. El lote tiene que estar a nombre del usuario que lo
   sube, si no el test mide rechazos y no lecturas.
3. **Freno por IP en logins y registro** (10 fallos → 60 s). k6 sale de una
   sola IP: subir `LOGIN_MAX_FALLOS` en Pruebas durante la corrida y bajarlo
   al terminar. Captcha apagado (Turnstile no configurado).
4. **Techos del engine y cupo del Panel** (503 con código esperables) y **Panel
   v2** como único panel desde el 25-10: el test 3 no se corrió sobre la v2.
5. **Motor de recibos**: sección de cada línea y reintegros entre los descuentos
   (`repartir_por_zona`), grilla bancaria firmada de agosto 2026 con conformado,
   ROE y tope, `MAX_TOKENS` 8.000, modelos que razonan con `effort: low`.
6. **Alcance de seccional** recortado en la consulta (Panel, padrón, Reportes).
7. **Tu día** (`/api/tu-dia`): la portada del afiliado llama a MET Norway y
   al BCRA con caché. El journey del test 1 no lo pide.
8. **Dos modelos de diseño y fotos en color**: más hojas y una foto más por
   portada; peso de la primera carga, no CPU.
9. **CUIL/CUIT con módulo 11**: los datos de carga nuevos tienen que cumplirlo.

## 3. El insumo: el lote bancario

En `datos_prueba/bancaria/` (`parte1.zip`, `parte2.zip`, `parte3.zip`: los 600 completos).
Datos ficticios, lo dice el pie de cada recibo. Trae su propio `manifest.csv`
(archivo, banco, CUIL leído e impreso, totales, neto correcto e impreso, error
intencional), `empleados.csv` y `bancos.json`.

| | |
|---|---|
| Recibos | 600: 50 personas × 12 meses (2025-09 a 2026-08) |
| Bancos | BBVA, Galicia, Nación, Industrial (PDF digital) y Santander (foto JPG 1240×1754) |
| CUIL | los 50 cumplen el módulo 11 |
| Errores a propósito | 2: un CUIL impreso con dígito verificador mal (Nación, 2026-05) y un neto impreso con $ 10.000 de más (Industrial, 2026-01) |

Qué implica para las pruebas:
- **Sirve sobre todo para carga** (B1–B3): 480 PDF y 120 fotos, a nombre de
  50 personas, es justo lo que el test 2 no tenía. Cada recibo se sube con la
  sesión de su CUIL; hay que empadronar a los 50 en La Bancaria de Pruebas.
- **Para exactitud alcanza poco**: 2 errores en 600. A1 usa el lote para medir
  que los 598 correctos salgan OK y suma los 10 PDF de `docs/recibos-bancaria-prueba/`
  para los errores.
- **No sigue la grilla del CCT 18/75**: categorías genéricas (Auxiliar,
  Supervisor…), antigüedad como renglón aparte y básicos que no son los de la
  grilla. En la Calculadora (A3) va a dar diferencias que no son defectos de
  la app: A3 se queda con los 10 PDF de la grilla.
- **El CUIL impreso mal** no debe cortar con E-RECIBO-04 (un dígito
  verificador inválido no rechaza un recibo propio): es un caso de A4.

## 4. Pruebas nuevas

### A. Exactitud (IA real, gasta créditos: correr una vez por cambio de motor o modelo)

| # | Prueba | Cómo | Aprueba si |
|---|---|---|---|
| A1 | Golden set bancario | cada recibo del manifiesto por `/api/leer` + `/api/validar`, comparando con `resultado_esperado` (script `probar_lote_bancaria.py`, a mano, nunca en CI) | 100% de los OK salen OK; 100% de los ERROR detectan su diferencia; ningún 500 |
| A2 | Sin IA | los mismos casos armados en el test (como `test_grilla_bancaria.py`) | igual que A1; separa error de lectura de error de motor |
| A3 | Calculadora | recibo leído contra la grilla, casos guardados | diferencias solo donde el manifiesto las espera |
| A4 | Enmascarado | lote completo con `ENMASCARADO=activo` | ningún E-RECIBO-04 falso; % tapado por formato (PDF/foto) |
| A5 | Laboratorio | 15–20 recibos, producción contra 2–3 alternativas | impacto en el sistema "NINGUNO" en al menos el 90%; costo y tiempo por recibo anotados |

A1 es además el **bloque 0 del motor v2** (`PLAN_MOTOR_V2.md`): la línea de
base que hoy falta.

### B. Carga (Pruebas, `MOCK_EXTRACTOR=1`, nunca la demo)

| # | Prueba | Qué cambia respecto de lo ya medido | Aprueba si |
|---|---|---|---|
| B1 | Test 2 con el lote bancario | archivos reales del zip en vez de los 20 JPG, `ENMASCARADO=activo`; ráfagas 2/5/10/20/40 | p95 de subida ≤ latencia del mock + 5 s; errores < 1%; anotar % salido sin tapar por cupo/tiempo |
| B2 | PDF contra foto | la misma ráfaga solo PDF y solo foto | cuantifica cuánto cuesta el OCR de foto; decide `ENMASCARADO_CUPO` |
| B3 | Día de cobro bancario | 400–800 lectores + ráfagas de 20–40 subidas a la vez, journey con `/api/tu-dia` y las dos portadas | lecturas p95 < 1 s; subidas como B1 |
| B4 | Test 3 sobre la v2 | Panel v2 de La Bancaria con 50.000 recibos (`medir_dashboard.py`), un Super Admin y un Admin de Seccional en paralelo | 0 respuestas 500; lectores p95 ≤ 2× la base; el acotado nunca ve otra seccional |
| B5 | Lanzamiento | 500 registros + primeros logins en 10 minutos (freno por IP ajustado) | sin 500; ningún registro duplicado |
| B6 | Archivos al límite | PDF multipágina, foto de 12 MP, archivo que no es recibo, PDF dañado | error con código propio, nunca 500; memoria del proceso estable |

### R. Recursos de Render: cada prueba de carga se corre en varios planes

Los tests 1–8 mostraron que el plan cambia todo; las pruebas nuevas (B1, B3,
B4) se corren **en cada escalón**, subiendo y bajando desde la solapa
**Planes** de `/entornos` (workers = núcleos, lo ajusta `render_admin`).
Precios de lista de `data/render_planes.json` (USD/mes).

| Escalón | Web | Postgres | Equivale a | Para qué |
|---|---|---|---|---|
| R1 Mínimo | 0,5 vCPU / 512 MB (7) | 0,1 vCPU / 256 MB (6) | test 1 | cuánto pesa el OCR con poca CPU (hoy Pruebas) |
| R2 Intermedio | 2 vCPU / 4 GB (85) | 2 vCPU / 4 GB (75) | test 5 | arranque barato de La Bancaria |
| R3 Producción | 4 vCPU / 8 GB (175) | 4 vCPU / 16 GB (200) | test 7 | lo que se piensa contratar |
| R4 Dos instancias | 4 vCPU / 8 GB × 2 | 4 vCPU / 16 GB | test 8 | pico del día de cobro |

Además de las pruebas de carga, se prueba **el cambio de plan en sí**:
- **Subir y bajar en caliente** con 200 lectores navegando: cuánto dura el
  corte del web (reinicio) y de la base (~1 min), y que los pedidos fallen con
  503 y código, nunca con 500 ni datos a medio escribir.
- **Orden de los workers**: al bajar, primero los workers; al subir, después
  (`render_admin`). Verificar en `CambioPlan` que se respetó.
- **Programado**: una regla del planificador que sube a R3 antes del "día de
  cobro" y baja a R1 después; se verifica que dispare a horario, que quede en la
  bitácora y que la gracia de 10 minutos cubra un reinicio.
- **`ENMASCARADO_CUPO`** se decide por escalón con B2 (1 por proceso hoy).
- **Costo**: Render prorratea por segundo; se anota el gasto de cada corrida
  y cuánto costaría el día de cobro con la regla programada contra R3 fijo.

### C. Funcionales con datos de La Bancaria (sin carga)

- Robot E2E: un afiliado sube su recibo, ve el resultado y lo envía al
  sindicato; el admin lo ve en Reportes (anonimizado si no fue enviado) y en el
  Panel.
- Admin de Seccional de La Bancaria: repetir la auditoría de alcance
  (`docs/chat/2026-10-17-auditoria-alcance.md`) con el lote cargado.

## 5. Recursos listos (2026-11-02; ninguno se corrió contra Pruebas)

| Prueba | Recurso | Qué hace |
|---|---|---|
| todas | `carga/lote_bancaria.py extraer` / `verificar` | zips → `carga/recibos_bancaria/` (fuera de git) + `k6.json`; controla los 600 y sus CUIL |
| todas | `carga/preparar_bancaria.py [--si] [--limpiar --si --con-conceptos]` | empadrona a los 50 en La Bancaria (clave = 5 primeros dígitos del CUIL, sin pisar una clave existente, repartidos por seccional) y escribe `carga/usuarios_bancaria.csv`; `--limpiar` borra lo que dejaron las pruebas. Sin `--si` no escribe |
| A1, A4, modelos | `carga/probar_lote_bancaria.py --base-url … --etiqueta … [--muestra N] [--si]` | cada recibo por `/api/leer` + `/api/validar` con la sesión de su CUIL; CSV por recibo y resumen; sin `--si` dice cuánto costaría. Con DATABASE_URL lee de UsoIA el modelo que corrió, tokens y USD, y marca inválida una corrida con el mock |
| comparar modelos | `probar_lote_bancaria.py --comparar a.csv b.csv` | tabla por corrida (aciertos, lectura exacta, errores detectados, tiempo, USD por recibo) y los recibos donde no coinciden |
| B1, B2 | `k6/test4_bancaria.js` `ESCENARIO=rafagas` (`FORMATO=pdf\|jpg`) | 200 lectores + ráfagas 2/5/10/20/40 con los recibos del lote, cada uno con su dueño |
| B3 | `test4_bancaria.js` `ESCENARIO=cobro` | 400 lectores (con «Tu día») + 20 subidas simultáneas durante 10 min |
| R | `test4_bancaria.js` `ESCENARIO=continuo` + `carga/analizar_corte.py` | lectores navegando mientras se cambia el plan; duración del corte, códigos, si hubo 500, y la bitácora `CambioPlan` de la ventana |
| B4 | `k6/test3_panel.js` con `ADMIN2_CUIT`/`ADMIN2_CLAVE` y `USUARIOS_CSV` | suma un Admin de Seccional con su propia tormenta y falla si su catálogo trae más de una seccional |
| B6 | `carga/archivos_limite.py generar` / `enviar … --si` | 9 archivos (3 y 40 páginas, PDF dañado, vacío, texto como PDF, foto 12 MP, torcida, oscura, no es recibo); falla si alguno da 500 o un error sin código |
| journey | `k6/test1_lecturas.js` con `CON_TU_DIA=1` y `USUARIOS_CSV` | «Tu día» opcional, para no romper la comparación con los tests 1–8 |
| — | `test_lote_bancaria.py` | 13 tests de todo lo anterior (sin red ni IA) |

**Quedan sin recurso propio** (se resuelven en el plan de ejecución): B5
(registro masivo: el registro tiene captcha y código por mail), C (robot E2E
con La Bancaria), y volcar los tests 3 y 4 al informe comparado
(`consolidar.py` hoy solo entiende los tests 1 y 2; el 3 y el 4 dejan su
propio JSON con veredicto).

## 6. Modelos de lectura

Para empezar, **Sonnet 5.5**; **Haiku 5.5** como alternativa a comparar (los dos
en el catálogo de precios y con `effort: low`). El modelo no lo elige ningún
script: se cambia en `/plataforma` → Uso de IA → Modelos → Lectura de recibos,
y cada corrida lleva su etiqueta.

- **Exactitud**: la misma muestra (`--muestra` es determinista) con cada
  modelo, y `--comparar`. Mismo criterio que el Laboratorio: coincidir en el
  neto no alcanza, cuenta la lectura exacta de los tres totales y el período.
- **Carga**: con el mock, el modelo no corre. Lo que cambia entre modelos es
  cuánto tarda: `MOCK_EXTRACTOR_LATENCIA` se fija con el p50 de lectura que dé
  A1 para el modelo elegido (hoy 15 s, la de septiembre).
- El Laboratorio de modelos sigue sirviendo para mirar un recibo puntual lado
  a lado.

## 7. Hallazgo de la prueba local: la app se cae con dos PDF a la vez

Probando los recursos contra un servidor local (`MOCK_EXTRACTOR=1`,
`ENMASCARADO=activo`), el proceso murió dos veces con `double free or
corruption` al recibir varias subidas de PDF juntas. Aislado: 8 hilos leyendo
PDF con `lectores.palabras_pdf` / `imagen_pdf` → una corrida colgada y dos
caídas en tres; de a uno, sin problema. **PDFium (`pypdfium2`) no admite uso
simultáneo desde varios hilos**, y `/api/leer` y `/api/aportes` corren el
enmascarado en el threadpool sin candado. Pruebas y Demo tienen el
enmascarado activo: dos afiliados que suben un PDF en el mismo momento al
mismo worker pueden tumbarlo (y cortar todo lo que ese worker atendía). El
test 2 no lo vio porque subía solo fotos. **Corregido el mismo día** (Trabajador
0.57.02): un candado alrededor de todo uso de PDFium en `lectores.py`
(`_candado_pdf`), con su test en `test_lectores.py`. Verificado: 320 lecturas
en 8 hilos sin caída (~33 ms cada una) y 5 corridas de 60 recibos con 8 en
paralelo contra el servidor local, 300 subidas sin un error. Antes de B1 tiene
que estar desplegado en Pruebas.

## 8. Para el plan de ejecución (a decidir)

1. Qué escalones de Render tienen sentido (R1 probablemente no) y en qué orden.
2. El recibo con el CUIL impreso mal: hoy se rechaza con E-RECIBO-04. ¿Se
   acepta con alerta cuando solo difiere el dígito verificador?
3. Volumen del Panel para B4: el lote sintético de La Bancaria trae 5.000
   recibos; llegar a 50.000 pide otro sembrado.
4. Cuántos recibos de A1 por modelo (60 de muestra ≈ US$ 2 con Sonnet 5.5,
   estimado) y si se corre una vez con los 600.
5. B5 y C: si se construyen o se sacan del plan.
6. Al terminar: `MOCK_EXTRACTOR` y `LOGIN_MAX_FALLOS` de Pruebas vuelven a su
   valor, los planes bajan al de siempre (y se borra la regla programada), y
   `preparar_bancaria.py --limpiar --si --con-conceptos`.
