# CCT 18/75 — Asociación Bancaria: lo que usa la simulación

Resumen del convenio bancario (texto ordenado 1975) y de la **grilla salarial
vigente** para armar recibos sintéticos en `cargar_bancaria.py`. Del CCT se
toma la ESTRUCTURA (categorías, coeficientes, qué adicionales existen); los
MONTOS salen de la grilla firmada con las cámaras, no del convenio.

**Grilla vigente: agosto 2026**, "GRILLAS ACTUALIZACIÓN SALARIAL 11-09-26"
(firmada el 11/09/2026, 8 páginas escaneadas), y el comunicado
"ACTUALIZACIÓN SALARIAL AGOSTO 2026: 1,7%" (acumulado enero–agosto: 21,3%
sobre diciembre 2025). Transcripta a mano de las imágenes el 2026-10-13.

Hasta el 2026-10-13 este documento decía otra cosa, y estaba mal en tres
puntos: tomaba como "sueldo inicial" el **conformado** del comunicado
(que no es el básico), calculaba los adicionales como **% del inicial** (hoy
son montos fijos) y daba el ROE como un solo monto (sale de una tabla).

## Básico y conformado

- **Básico**: el de la categoría, según rama y antigüedad (tablas abajo).
  Hasta cierta antigüedad tiene un piso de **$ 1.642.764,63**; desde ahí sube
  con el coeficiente (≈ coeficiente × $ 1.474.068).
- **Conformado**: lo que la grilla garantiza como remuneración mínima de la
  categoría. Es el "Salario Inicial" que publica el comunicado mensual
  ($ 2.505.061,24 en agosto 2026). **Solo existe hasta los 15 años**: desde
  los 20 el básico ya lo supera. En la rama administrativa sube unos
  $ 3.253 por año desde los 5 años; en maestranza y ordenanza es el mismo
  para todos.
- **Cómo lo imprime un banco: no lo dice la grilla** y no se encontró fuente.
  La simulación lo muestra como una línea propia, **"Complemento salario
  conformado"** = conformado − básico (si es positivo), remunerativa, y
  toma el conformado como piso del BÁSICO, sin contar los adicionales de
  función (cajero, título, zona). Es un supuesto: si se confirma otro nombre
  u otra mecánica, se cambia ahí.
- **Salario inicial + ROE** del comunicado: $ 2.505.061,24 + $ 72.413,50 =
  $ 2.577.474,74.

### Rama administrativa (la que simula el lote)

| Categoría | Coef. | Básico | Conformado |
|---|---|---|---|
| Inicial | 1,00 | $ 1.642.764,63 | $ 2.505.061,24 |
| 1 año | 1,04 | $ 1.642.764,63 | $ 2.505.061,24 |
| 2 años | 1,08 | $ 1.642.764,63 | $ 2.505.061,24 |
| 3 años | 1,11 | $ 1.642.764,63 | $ 2.505.061,24 |
| 4 años | 1,13 | $ 1.665.695,64 | $ 2.505.061,24 |
| 5 años | 1,17 | $ 1.724.658,32 | $ 2.508.315,25 |
| 6 años | 1,20 | $ 1.768.880,32 | $ 2.511.567,97 |
| 7 años | 1,24 | $ 1.827.843,00 | $ 2.514.821,98 |
| 8 años | 1,26 | $ 1.857.324,34 | $ 2.518.074,70 |
| 9 años | 1,30 | $ 1.916.287,02 | $ 2.521.328,70 |
| 10 años | 1,35 | $ 1.989.990,36 | $ 2.524.582,71 |
| 11 años | 1,39 | $ 2.048.953,04 | $ 2.527.836,71 |
| 12 años | 1,43 | $ 2.107.915,72 | $ 2.531.089,44 |
| 13 años | 1,48 | $ 2.181.619,07 | $ 2.534.342,13 |
| 14 años | 1,52 | $ 2.240.581,74 | $ 2.537.595,99 |
| 15 años | 1,63 | $ 2.402.729,11 | $ 2.540.849,85 |
| 20 años | 1,74 | $ 2.564.876,47 | — |
| 25 años | 1,96 | $ 2.889.171,20 | — |
| 30 años | 2,07 | $ 3.051.318,56 | — |
| 35 años | 2,17 | $ 3.198.725,25 | — |
| 2º Jefe Div. de 3a. | 1,96 | $ 2.889.171,20 | — |
| 2º Jefe Div. de 2a. | 2,07 | $ 3.051.318,56 | — |
| 2º Jefe Div. de 1a. | 2,17 | $ 3.198.725,25 | — |
| Jefe Div. de 3a. | 2,28 | $ 3.360.872,62 | — |
| Jefe Div. de 2a. | 2,50 | $ 3.685.167,34 | — |
| Jefe Div. de 1a. | 2,61 | $ 3.847.314,71 | — |
| 2º Jefe Dep. de 3a. | 2,83 | $ 4.171.609,43 | — |
| 2º Jefe Dep. de 2a. | 2,93 | $ 4.319.016,12 | — |
| 2º Jefe Dep. de 1a. | 3,04 | $ 4.481.163,49 | — |
| Jefe Dep. de 3a. | 3,26 | $ 4.805.458,21 | — |
| Jefe Dep. de 2a. | 3,48 | $ 5.129.752,94 | — |
| Jefe Dep. de 1a. | 3,70 | $ 5.454.047,67 | — |
| Jefe Ppal. de Dpto. | 4,02 | $ 5.925.749,09 | — |
| SubGte. Deptal de 3a. | 4,35 | $ 6.412.191,18 | — |
| SubGte. Deptal de 2a. | 4,65 | $ 6.854.411,26 | — |
| SubGte. Deptal de 1a. | 4,89 | $ 7.208.187,32 | — |

Los coeficientes de la rama administrativa **son los mismos que los del
art. 5 de 1975**; lo que cambió es el monto.

### Rama maestranza

Conformado **$ 2.505.061,24 igual para todas las categorías de 0 a 15 años**
(los básicos de esos años quedan todos debajo).

| Categoría | Coef. | Básico |
|---|---|---|
| Inicial | 1,00 | $ 1.642.764,63 |
| 1 año | 1,03 | $ 1.642.764,63 |
| 2 años | 1,04 | $ 1.642.764,63 |
| 3 años | 1,06 | $ 1.642.764,63 |
| 4 años | 1,08 | $ 1.642.764,63 |
| 5 años | 1,11 | $ 1.642.764,63 |
| 6 años | 1,13 | $ 1.665.695,64 |
| 7 años | 1,14 | $ 1.680.436,31 |
| 8 años | 1,16 | $ 1.709.917,65 |
| 9 años | 1,17 | $ 1.724.658,32 |
| 10 años | 1,22 | $ 1.798.361,66 |
| 11 años | 1,24 | $ 1.827.843,00 |
| 12 años | 1,26 | $ 1.857.324,34 |
| 13 años | 1,29 | $ 1.901.546,35 |
| 14 años | 1,30 | $ 1.916.287,02 |
| 15 años | 1,33 | $ 1.960.509,03 |
| 16 años | 1,35 | $ 1.989.990,36 |
| 17 años | 1,39 | $ 2.048.953,04 |
| 18 años | 1,41 | $ 2.078.434,38 |
| 19 años | 1,44 | $ 2.122.656,39 |
| 20 años | 1,48 | $ 2.181.619,07 |
| 25 años | 1,53 | $ 2.255.322,41 |
| 30 años | 1,62 | $ 2.387.988,44 |
| 35 años | 1,66 | $ 2.446.951,12 |
| Jefe de Equipo de 3º | 1,48 | $ 2.181.619,07 |
| Jefe de Equipo de 2º | 1,53 | $ 2.255.322,41 |
| Jefe de Equipo de 1º | 1,62 | $ 2.387.988,44 |
| Sub-Jefe taller 3º | 1,66 | $ 2.446.951,12 |
| Sub-Jefe taller 2º | 1,67 | $ 2.461.691,78 |
| Sub-Jefe taller 1º | 1,72 | $ 2.535.395,13 |
| Jefe taller de 3º | 1,73 | $ 2.550.135,80 |
| Jefe taller de 2º | 1,77 | $ 2.609.098,48 |
| Jefe taller de 1º | 1,81 | $ 2.668.061,16 |
| Supervisor de taller 3º | 1,84 | $ 2.712.283,16 |
| Supervisor de taller 2º | 1,90 | $ 2.800.727,18 |
| Supervisor de taller 1º | 2,00 | $ 2.948.133,87 |
| Subcapataz Gral. | 2,17 | $ 3.198.725,25 |
| Capataz Gral. | 2,36 | $ 3.478.797,97 |

### Rama ordenanza

Conformado **$ 2.505.061,24 igual para todas las categorías de 0 a 15
años**. El piso del básico figura en esta página como $ 1.642.764,49 (14
centavos menos que en las otras dos ramas; así está impreso).

| Categoría | Coef. | Básico |
|---|---|---|
| Inicial | 1,00 | $ 1.642.764,49 |
| 1 año | 1,02 | $ 1.642.764,49 |
| 2 años | 1,03 | $ 1.642.764,49 |
| 3 años | 1,04 | $ 1.642.764,49 |
| 4 años | 1,06 | $ 1.642.764,49 |
| 5 años | 1,09 | $ 1.642.764,49 |
| 6 años | 1,10 | $ 1.642.764,49 |
| 7 años | 1,11 | $ 1.642.764,49 |
| 8 años | 1,13 | $ 1.665.694,65 |
| 9 años | 1,14 | $ 1.680.434,59 |
| 10 años | 1,19 | $ 1.754.139,22 |
| 11 años | 1,20 | $ 1.768.880,39 |
| 12 años | 1,22 | $ 1.798.361,66 |
| 13 años | 1,24 | $ 1.827.843,00 |
| 14 años | 1,27 | $ 1.872.065,01 |
| 15 años | 1,30 | $ 1.916.287,02 |
| 16 años | 1,32 | $ 1.945.768,36 |
| 17 años | 1,35 | $ 1.989.990,36 |
| 18 años | 1,38 | $ 2.034.212,37 |
| 19 años | 1,40 | $ 2.063.693,71 |
| 20 años | 1,42 | $ 2.093.175,05 |
| 25 años | 1,44 | $ 2.122.656,39 |
| 30 años | 1,46 | $ 2.152.137,73 |
| 35 años | 1,48 | $ 2.181.619,07 |
| Subjefe serv. 3ª | 1,42 | $ 2.093.175,05 |
| Subjefe serv. 2ª | 1,44 | $ 2.122.656,39 |
| Subjefe serv. 1ª | 1,46 | $ 2.152.137,73 |
| Jefe serv. 3ª | 1,48 | $ 2.181.619,07 |
| Jefe serv. 2ª | 1,50 | $ 2.211.100,41 |
| Jefe serv. 1ª | 1,53 | $ 2.255.322,41 |
| Superv. Serv. 3ª | 1,55 | $ 2.284.803,75 |
| Superv. Serv. 2ª | 1,59 | $ 2.343.766,43 |
| Superv. Serv. 1ª | 1,62 | $ 2.387.988,44 |
| Submay. Espec. 3ª | 1,67 | $ 2.461.691,78 |
| Submay. Espec. 2ª | 1,72 | $ 2.535.395,13 |
| Submay. Espec. 1ª | 1,81 | $ 2.668.061,16 |
| Submayordomo Gral. | 2,17 | $ 3.198.725,25 |
| Mayordomo Gral. | 2,54 | $ 3.744.130,02 |

**La antigüedad NO es una línea del recibo**: está embebida en el básico
(sube por la escala de cada rama) y dispara **promociones automáticas** de
categoría (art. 44). En la rama administrativa: Auxiliar → 15 años Ayudante
de firma → 20 Jefe de Sección → 25 2º Jefe de División de 3º (coef. 1,96) →
30 de 2º (2,07) → 35 de 1º (2,17).

## Adicionales: montos fijos por mes (agosto 2026)

El CCT de 1975 los define como % del sueldo inicial; **hoy la grilla los
publica como montos fijos**, iguales para todas las categorías.

| Adicional | Monto mensual |
|---|---|
| Función cajero (art. 22) | $ 163.963,06 |
| Falla de caja (art. 22) | $ 287.355,05 |
| Falla de caja moneda extranjera | $ 82.261,33 |
| Título secundario (art. 10) | $ 27.979,69 |
| Título terciario | $ 65.069,99 |
| Título universitario | $ 97.604,47 |
| Zona Patagónica: La Pampa | $ 455.489,91 |
| Zona Patagónica: Partido de Patagones (Bs. As.), Río Negro y Neuquén | $ 498.870,24 |
| Zona Patagónica: Chubut, Santa Cruz, Tierra del Fuego, Antártida e Islas del Atlántico Sur | $ 585.630,91 |
| Guardería | $ 416.341,95 |

- La grilla ya **no distingue recibidor / pagador**: hay un solo monto de
  función y uno de falla. **Función y falla son DOS líneas** del recibo.
- Título: uno solo, el de mayor monto.
- La "zona desfavorable" por grupos A–D del art. 25 hoy se publica como
  **Zona Patagónica** en tres tramos.
- Computación (art. 14), funciones técnicas (art. 11), máquinas de
  contabilidad (art. 24), portavalores (art. 39) y suplemento nocturno
  (art. 15 B) **no figuran en la grilla**: no hay monto vigente publicado, y
  la simulación no los inventa (los conceptos siguen en el catálogo).

**Mayores gastos de conectividad** (teletrabajo), por trimestre:

| | Jun–Jul–Ago 2026 | Sep–Oct–Nov 2026 |
|---|---|---|
| Diario | $ 2.890 | $ 3.055 |
| Más de 4 días | $ 26.011 | $ 27.493 |
| Mensual | $ 63.571 | $ 67.193 |

## Participación en las ganancias (ROE)

No es un % del inicial: sale de cruzar el **sueldo bruto** del agente con el
**ROE del banco** (el que publica el BCRA). La tabla da montos **anuales**;
se cobra **1/12 por mes**. Ejemplo: el inicial ($ 2.505.061,24) en un banco
con ROE entre 3,5% y 8,75% cobra $ 868.962,01 / 12 = **$ 72.413,50**, que es
el monto del comunicado.

| Sueldo bruto | 0% a 3,5% | >3,5% a 8,75% | >8,75% a 14,5% | >14,5% a 19,75% | >19,75% a 25% | >25% |
|---|---|---|---|---|---|---|
| $ 1 a $ 3.275.626 | $ 0 | $ 868.962,01 | $ 1.086.228,18 | $ 1.357.708,22 | $ 1.493.550,92 | $ 1.642.844,40 |
| $ 3.275.627 a $ 4.242.954 | $ 0 | $ 1.629.290,94 | $ 2.036.613,67 | $ 2.545.792,76 | $ 2.800.330,96 | $ 3.080.333,26 |
| $ 4.242.955 a $ 5.091.586 | $ 0 | $ 2.389.619,86 | $ 2.986.999,16 | $ 3.733.774,62 | $ 4.107.213,69 | $ 4.517.924,79 |
| Más de $ 5.091.586 | $ 0 | $ 2.824.049,53 | $ 3.530.164,59 | $ 4.412.680,07 | $ 4.853.989,15 | $ 5.339.346,99 |

En la simulación cada banco tiene un tramo de ROE fijo (uno de ellos, el
tramo de 0% a 3,5%, que no paga), y el sueldo bruto que elige la fila es el
del mes sin el ROE.

## Día del Bancario (6 de noviembre, art. 50)

**Total = suma fija $ 1.973.675,85 + coeficiente de la categoría ×
$ 259.499,59**. Mínimo (inicial): **$ 2.233.175,44**, "a corregir por
futuras actualizaciones". La grilla trae la tabla por rama (páginas 6 a 8);
por ejemplo, rama administrativa: 10 años (1,35) $ 2.324.000,30; 20 años
(1,74) $ 2.425.205,15; SubGte. Deptal de 1a. (4,89) $ 3.242.628,87. Los
totales impresos difieren en un centavo de la fórmula por redondeo.

El acta de 2020 lo pactó como **compensación extraordinaria no
remunerativa**; no se encontró cómo se trata hoy. **No se simula**: el lote
cubre 120 días hacia atrás y no llega a un noviembre.

## Lo que el convenio NO trae (y por eso no se inventa)

- **Ningún porcentaje de aportes de seguridad social** (jubilación, INSSJP,
  obra social): son de la ley general. La simulación usa 11% / 3% / 3%.
- **Ningún porcentaje de cuota sindical mensual.** El único descuento del CCT
  es un aporte solidario **por única vez** (Disposiciones Transitorias II).
  Por eso la cuota sindical se carga como concepto pero **sin fórmula de
  validación**: el sistema no puede reclamar un porcentaje que el convenio
  no fija.
- **Presentismo**: no existe en este convenio.

## Otras particularidades (no simuladas, útiles para la demo)

- **Día femenino** (art. 48 f): un día por mes sin justificar, con goce de sueldo.
- **Topes de encasillamiento** (arts. 11, 12, 14, 17): básico + adicional
  técnico no puede superar el mínimo de la jerarquía tope del agrupamiento.
- **Irreductibilidad** (art. 45): retirar una función no baja la remuneración;
  el adicional sigue hasta que lo absorban aumentos futuros.

## Fuentes

- `1875.pdf` (38 páginas, texto ordenado del CCT 18/75).
- Grilla: https://labancaria.org/grillas-actualizacion-salarial-11-09-26/
  (PDF `GRILLAS-AGOSTO-2026.pdf`, 8 páginas escaneadas sin texto; páginas
  1–3 básico y conformado por rama, 4 adicionales y conectividad, 5 ROE, 6–8
  Día del Bancario por rama).
- Comunicado: https://labancaria.org/actualizacion-salarial-agosto-2026-17/
  (PDF `Actualizacion-AGOSTO.pdf`, con texto).
- Día del Bancario como no remunerativo: acta de 2020,
  https://labancaria.org/wp-content/uploads/2020/10/Dia-del-bancario1.pdf
