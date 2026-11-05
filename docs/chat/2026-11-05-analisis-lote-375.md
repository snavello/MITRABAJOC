# Análisis del lote bancario de 400 recibos (Sonnet 5.5, 375 leídos) — 2026-11-05

Fuente: `carga/log/lote_bancaria/2026-11-05_0045_sonnet-5-5-400.{csv,json}`. Los últimos 25 (Santander JPG, `E-RECIBO-01`) fallaron por el tope de gasto de la cuenta de IA y no cuentan.
El JSON de la corrida trae solo el resumen: **no quedó guardada la lectura de la IA por recibo**. Las conclusiones sobre «qué leyó» salen de las columnas `dif_*` y `discrepancias` del CSV; lo que dependa de la lectura real está marcado como hipótesis.

## Conteo

Se leyeron 374 con `lectura_ok=True` de 375 con respuesta (el 375 es el BBVA del caso 6, `lectura_ok=False`). Aciertos del lote: 370 de 375.

| banco / formato | leídos | dieron lo esperado |
|---|---|---|
| BBVA pdf | 120 | 120 (119 con lectura exacta + el caso 6) |
| Galicia pdf | 120 | 117 (fallan 3) |
| Nación pdf | 120 | 118 (fallan 2) |
| Santander jpg | 15 (de 40) | 15; 25 cortados por el tope de gasto |
| Industrial | 0 (no entró en la muestra de 400) | — |

## Casos 1 a 5: esperado «con diferencias», la app dijo OK

Ninguno trae error a propósito (`error_intencional` vacío): el lote los espera con diferencias porque `lote_bancaria.esperado` / `supera_tope` marca que el generador calculó los aportes sobre el sueldo completo, sin el tope de la seguridad social. Son los 5 recibos de menor exceso sobre el tope **en su mes** (los demás recibos del mismo mes, con más exceso, sí se marcaron).

| archivo | exceso sobre el tope | Jubilación impresa vs. con tope |
|---|---|---|
| galicia/27425555478_2025-09 | $ 3.298,65 | 385.990,00 vs 385.627,15 (dif 362,85) |
| galicia/27425555478_2025-10 | $ 4.062,46 | dif 446,87 |
| galicia/20444641607_2026-02 | $ 9.360,13 | dif 1.029,61 |
| nacion/27267339177_2025-12 | $ 9.950,29 | dif 1.094,53 |
| nacion/20292831545_2026-03 | $ 266.676,45 | dif 29.334,41 |

**Reproducción sin IA** (`test_zz_qa375.py` local, no commiteado: texto del PDF → líneas con sección y categoría universal como las da el extractor → `_validar_como_la_app` con el catálogo de `cargar_bancaria.crear_sindicato()`, topes de `data/topes_ss.csv`): **los 5 dan `CON_DISCREPANCIAS`** con `formula:JUBILACION/PAMI/OBRASOCIAL` y alerta `tope_no_aplicado`. Es decir, el motor del repo, con tolerancia $ 1 y el tope del CSV, los marca. Que en Pruebas dieran OK exige que `esperado == impreso`, o sea que el tope aplicado fuera ≥ la base impresa del recibo, o que la fórmula no lo topeara.

Qué se descartó:
- Tolerancia del motor: es $ 1 por fórmula; además no ordena (Nación 2026-03 con dif $ 29.334 pasó y Galicia 2026-01 con dif $ 6.188 se marcó).
- Concepto sin controlar, alias de la cuota, tope que tapa: no; los tres aportes de ley se controlan y la cuota no entra en estas fórmulas.
- `*_recalculo_*.csv`: no incluyen estos 5.

**Hipótesis mejor sostenida (no verificable desde acá): la tabla de topes de Pruebas no coincide con `data/topes_ss.csv`.** Es solo-si-vacío (`db.sembrar_topes_si_vacio`) y editable en `/plataforma`. Los datos dicen que en Pruebas el tope de cada uno de esos meses está dentro de estos rangos (piso = base impresa del recibo sin marcar, techo = recibo más cercano que sí se marcó): 2025-09 [3.509.000; ~3.616.000), 2025-10 [3.575.671; ~3.684.000), 2025-12 [3.741.162; ~3.873.000), 2026-02 [3.941.699; ~4.236.000), 2026-03 [4.312.267; ~4.873.000). El del CSV es menor en los cinco (3.505.701 / 3.571.609 / 3.731.212 / 3.932.339 / 4.045.590). Alternativa menos probable: la IA devolvió algo distinto de lo que reconstruí (cosa que solo se ve con el JSON de la lectura o con `ReciboVerificado.detalle` de Pruebas).

Origen: **la configuración** (topes de Pruebas) con confianza media; si no es eso, sería la app (lectura). **No es de los recibos de prueba**: el manifiesto espera con razón.
Qué cambiar:
- Verificar en `/plataforma` → Topes los cinco meses y alinearlos al CSV (o corregir el CSV si lo del CSV está mal: SDN decide cuál es el valor real; `tope_ss` del lote y del motor deben leer el mismo número). Después repetir esos 5 recibos.
- `carga/probar_lote_bancaria.py` debería guardar también las `alertas` y el detalle de la lectura (líneas) en el JSON/CSV: hoy una diferencia así no se puede diagnosticar sin acceso a la base de Pruebas.
- Un test que compare la tabla de topes del entorno contra el CSV (chequeo de entorno, p. ej. en `chequeo.py`), para que un desvío no pase inadvertido.

## Caso 6: bbva/20209792630_2025-10.pdf

Esperado `CON_DISCREPANCIAS` (exceso sobre el tope $ 1.494.299), obtenido `CON_DISCREPANCIAS` (`formula`), `lectura_ok=False`: `dif_haberes +972.900`, `dif_descuentos −972.900`, neto bien.

Causa: **no es un reintegro ni una línea con signo raro.** 972.900,00 es exactamente el total de descuentos impreso (560.450 + 152.850 + 152.850 + 101.900 + 4.850). El PDF no tiene ningún reintegro; los descuentos están en la columna «Descuentos» como números positivos, en una tabla única de columnas Haberes/Descuentos (sin encabezados de sección). La IA transcribió las cinco líneas con importe positivo y una sección distinta de `descuentos` (haberes, no remunerativos o null): `validador.totales_leidos` las pone en la zona ingresos (`_zona_leida`: sección, y solo si es null, el signo) y por eso ingresos = 6.187.900 y descuentos = 0 (reproducido localmente: da exactamente eso).
`/api/validar` no se ve afectado: los conceptos 501/502/503/510/520 están en el catálogo como descuentos y, al estar en conflicto con la sección impresa, manda el catálogo (`mal_clasificados` solo cambia a la sección si el catálogo no cierra los totales y la sección sí). La validación da `formula` por el tope, que es lo correcto; el `acierto=True` es por la razón buena. Lo que queda mal es lo que ve el afiliado en la pantalla de confirmar (ingresos/descuentos de `totales_leidos`) y la métrica `lectura_ok`.
Origen: **la app** (lectura/extractor: sección mal dicha en un layout de columnas; el motor no la corrige en `_zona_leida`).
Qué cambiar: en `validador._zona_leida` (y/o en el prompt de `extractor.py` para `seccion`), si la línea trae `tipo = aporte_trabajador` y la sección no es `descuentos`, tratarla como descuento; y agregar el caso al prompt (tabla con columnas Haberes/Descuentos: la sección es la columna). Test con este recibo reconstruido.

## `CUIL_DV_INVALIDO`

`nacion/27340709107_2026-05.pdf`: el recibo imprime `27-34070910-0` (el verificador correcto es 7). Esperado OK, obtenido OK, lectura exacta. Es lo que el lote espera: `ESPERADO_POR_ERROR["CUIL_DV_INVALIDO"] = "OK"`, y el PR del aviso (a564418) mantiene el recibo aceptado y agrega la alerta `cuil_impreso_invalido`. Dos pendientes: (1) el comentario de `carga/lote_bancaria.py` (líneas 28-35) dice que la app no avisa y está desactualizado; (2) el CSV no guarda las alertas, así que esta corrida no prueba que el aviso salió (no se sabe si Pruebas ya tenía ese PR desplegado: el PR es del 04-nov 20:14; la corrida, del 05-nov 00:45). Conviene que `clasificar` guarde `alertas` y que el lote espere `cuil_impreso_invalido` para esa fila.
