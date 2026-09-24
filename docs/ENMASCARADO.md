# Enmascarado de datos personales antes de la IA — ficha rectora

Qué es, qué se decidió, cómo se mide y qué está abierto. El plan original
está en `PLAN_ENMASCARADO.md` (no se edita); la narrativa, en HISTORIAL.md
("Enmascarado, bloque 1" en adelante). Esta ficha es lo vigente.

## La regla que manda

**El objetivo del análisis de recibos es ser preciso, confiable y viable
en tiempo y recursos. El enmascarado es un agregado de mejor esfuerzo**
(SDN, 2026-09-24, en CLAUDE.md "Decisiones tomadas"): nunca frena, demora
ni rechaza un recibo; si algo no se tapa, el recibo se analiza igual y
queda registrado. Por eso **tapar de más es más peligroso que tapar de
menos**: un dato a la vista es una fuga que ya existía antes de este
proyecto; un dato que la IA necesitaba y no vio es una evaluación peor.

## Qué necesita la IA de fuera de la tabla de conceptos

Sale del esquema del extractor (`extractor.ESQUEMA`):

| Para qué | Campos | ¿Se puede tapar? |
|---|---|---|
| Evaluar el recibo | período, fecha de pago, formato (clásico / Anexo III), totales impresos, contribuciones patronales, costo laboral, último depósito | **Nunca** |
| Motor v2 (escala, antigüedad) | categoría, fecha de ingreso | **Nunca** |
| Identidad | CUIL, nombre, legajo, DNI, cuenta, CUIT y razón social del empleador | Sí: se rearman con lo leído localmente (`preparacion.rearmar_recibo`) |

## Tres estrategias, y la que está en prueba

1. **Detectar la identidad** (bloques 1–4): lo conocido (CUIL, DNI y
   nombre de la sesión), patrones (CUIL/CUIT con formato) y rótulos
   ("CUIL", "Apellido y nombre", "Legajo", "Cuenta"...). Seguro para la
   evaluación, frágil ante formatos nuevos: cada formato trae rótulos y
   diseños distintos.
2. **Tapar por defecto** todo lo que está fuera de la tabla, salvo una lista
   blanca. General y más protector, pero **si el límite de la tabla se
   detecta mal, se tapan conceptos**: el error más caro. Descartada por
   ahora (SDN: "más efectiva pero más peligrosa para el objetivo principal").
3. **Mixto — EN PRUEBA desde 2026-09-24**: la 1, más **tapar alrededor de lo
   encontrado** (`enmascarado.analizar`, paso 3b):
   - **la frase del nombre**, entera menos su rótulo: si se reconocieron dos
     partes del nombre, la del medio también se tapa aunque el OCR la haya
     leído irreconocible;
   - **la fila de la identidad**: en la línea donde apareció el nombre, el
     CUIL, el DNI o la cuenta, un número de 4+ cifras se tapa como "DATO
     OCULTO" (el legajo casi siempre, a veces un código interno);
   - **lista blanca** (`_es_lista_blanca`), lo que nunca se tapa ahí: fechas,
     períodos, años, importes. Y nada dentro de la tabla de conceptos.

   Acepta tapar de más *solo en la vecindad de la identidad* (un código de
   dependencia, por ejemplo), que es donde lo que se tapa casi nunca le sirve
   a la IA.

## Cómo se mide (no se opina)

`medicion_enmascarado/medir.py` lee cada recibo tres veces con el mismo
modelo (original, tapado con la identidad conocida, tapado sin conocidos) y
compara con las funciones del banco de pruebas. Acepta PDF y fotos; los
recibos reales se pasan con `--conocidos-archivo` y **ni ellos ni su
resultado se versionan**. Dos números por recibo:

- **Protección**: qué quedó tapado y si el control de fuga vio algo.
- **Evaluación**: totales, líneas, clasificación de cada línea, período,
  categoría. **Criterio: cero cambios atribuibles al tapado.** Una diferencia
  se atribuye al tapado solo si el original leído varias veces no la tiene
  (el modelo varía solo en líneas ambiguas).

En Pruebas, la sub-pestaña Uso de IA → Enmascarado muestra cada documento y,
con el diagnóstico transitorio, la imagen original y la enviada ("Ver").

## Resultado del mixto (2026-09-24, claude-sonnet-4-6, tapones rojos)

10 sintéticos + digital ficticio + una foto real de AEFIP:
- Totales, cantidad de líneas, período y categoría **iguales en los 12**;
  identidad rearmada igual; **ninguna alerta de adulteración** con tapones
  rojos; foto real: 11 zonas, 0 fugas, 19/19 líneas iguales.
- **"SEGURO OBLIGATORIO - DGI"**: varía aporte/otro también en el original:
  es el modelo.

### Abierto: una línea ambigua varía más en el tapado

**"A cuenta futuros aumentos"** (recibo digital): el original leído 4 veces
dio siempre `remuneracion`; tapado, 3/4 en rojo y 2/4 en gris. No es el
color. La muestra es chica, pero es exactamente el riesgo que importa: esa
clasificación decide si la línea suma a la base remunerativa. **Antes de
llevar el enmascarado a la demo hay que medirlo sobre un conjunto variado
de recibos reales** y, si se confirma, ver si viene del aviso a la IA o de la
imagen. El motor v2 (confianza por renglón, catálogo maestro, cierre
aritmético) es la defensa de fondo contra este tipo de línea.

## Tapones

Rótulo que dice qué había ("CUIL OCULTO", "DATO OCULTO"), con un margen
proporcional al alto de la letra (35 % arriba y abajo, 50 % a los costados:
en una foto torcida la caja del OCR es recta y la letra no). Color con
`ENMASCARADO_COLOR` = `gris` / `negro` / `rojo`; sin la variable, **rojo en
local y Pruebas** (se ve mejor al revisar) y gris en demo y producción. La IA recibe el aviso de que son intencionales.

## Variables

| Variable | Valores | Pruebas hoy |
|---|---|---|
| `ENMASCARADO` | apagado / sombra / activo | activo |
| `ENMASCARADO_COLOR` | gris / negro / rojo (sin cargar: rojo en local/pruebas, gris en demo/prod) | sin cargar → rojo |
| `ENMASCARADO_CUPO` | lectores de OCR por proceso (1) | 1 |
| `ENMASCARADO_PRESUPUESTO_MS` | fila + lectura por foto (5000) | 5000 |
| `ENMASCARADO_GUARDAR_IMAGENES` | 1 = diagnóstico transitorio (solo local/pruebas) | 1 |

## Pendientes

- Conjunto variado de recibos reales (formatos, empleadores, PDF y foto)
  para medir protección y evaluación de las tres estrategias.
- Confirmar o descartar la variación de "A cuenta futuros aumentos".
- Sacar el diagnóstico con imágenes cuando SDN cierre la etapa.
- Módulo 11 de CUIL/CUIT (BACKLOG.md).
