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

**Configuración.** Correr sobre la configuración que se va a contratar para
La Bancaria (el test 7, 4 núcleos, o el 8, dos instancias), subida y bajada
desde la solapa **Planes** de `/entornos`, programada para la ventana de la
corrida. B1 y B2 conviene repetirlos en la configuración base para ver cuánto
pesa el OCR con poca CPU.

### C. Funcionales con datos de La Bancaria (sin carga)

- Robot E2E: un afiliado sube su recibo, ve el resultado y lo envía al
  sindicato; el admin lo ve en Reportes (anonimizado si no fue enviado) y en el
  Panel.
- Admin de Seccional de La Bancaria: repetir la auditoría de alcance
  (`docs/chat/2026-10-17-auditoria-alcance.md`) con el lote cargado.

## 5. Lo que hay que construir (chico)

1. `carga/preparar_bancaria.py`: empadrona los 50 CUIL de `empleados.csv` en
   La Bancaria y escribe `carga/usuarios_bancaria.csv`.
2. `carga/k6/test4_bancaria.js`: el test 2 leyendo manifiesto y usuarios, con
   etiqueta por `formato` y `variante`; ráfaga de 40 y fase "día de cobro".
3. `probar_lote_bancaria.py` (A1/A4): corre el manifiesto contra Pruebas,
   CSV de resultados por variante; pide confirmación porque gasta créditos.
4. `resumen.py` que levante los tests 3 y 4 (hoy no levanta el 3), y
   `consolidar.py` que los numere como tests 9 en adelante en el mismo informe.
5. Sumar `/api/tu-dia` al journey de `test1_lecturas.js`.

## 6. Orden

1. ~~Subir el lote~~ hecho: 600 recibos con su manifiesto.
2. A2 → A1 → A4 (exactitud antes que carga: si lee mal, la carga no importa).
3. B6 → B1 → B2 (decide el cupo del OCR) → B3 → B4 → B5.
4. A5 y C cuando el resto esté en verde.
5. Volcar todo al informe (`consolidar.py` + `generar_md.py`) y una línea en
   `BITACORA.md`.

Al terminar: `MOCK_EXTRACTOR` y `LOGIN_MAX_FALLOS` de Pruebas vuelven a su
valor, el plan baja al de siempre, y los recibos del lote se borran con
`cargar_bancaria.py --borrar-recibos-de <CUIL> --si` si no se van a reusar.
