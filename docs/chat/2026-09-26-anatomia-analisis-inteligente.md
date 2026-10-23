# Anatomía del análisis inteligente — IA · Aprendizaje · Reglas (caso Marina)
Fecha: 2026-09-26 · Herramienta: Cowork · Origen: sesión "[MT] Recibos — escala salarial y estimador" (proyecto Mitrabajo; propuesta en `claude/propuesta-motor-estimador-v1.md`)
Estado: acordado (recurso publicado; el flujo que describe es el del motor v2 más las ideas del 26/09, que están en propuesta)
Quién: SDN

## Qué es

Recurso educativo, publicado en `/entornos` → Recursos como
`recursos/anatomia-analisis-inteligente.html`. Muestra el recorrido de un
recibo desde que se sube hasta el veredicto, en nueve bloques (0 a 8), con
un diagrama animado: la cinta de bloques avanza sola, el bloque activo se
agranda y abajo se despliega la tarjeta con **qué hace**, **qué datos
maneja**, **los datos del ejemplo en ese punto** y **qué pasa si falla**.
Play/pausa, anterior/siguiente, reiniciar, velocidad (7/12/20 s), teclado.

Portada: el recibo de Marina renderizado como un recibo clásico (empleador,
datos del empleado, líneas con código/concepto/unidad/cantidad/haberes/
descuentos, totales, neto, pie), con los mismos números que después usa el
recorrido.

## El caso

Marina, administrativa bancaria (CCT 18/75), 10 años de antigüedad, título
universitario, recibo de agosto 2026. Importes tomados de la grilla oficial
de La Bancaria de agosto 2026 (`GRILLAS-AGOSTO-2026.pdf`, escaneado, leído
a mano el 25/09): básico 10 años = base 1.474.066,93 × coef 1,35 =
1.989.990,36; conformado 10 años 2.524.582,71 (adicional 534.592,35); ROE
mensual 72.413,50 (banda 3,5–8,75 % del primer tramo ÷ 12); título
universitario 97.604,47. Descuentos: 11 % + 3 % + 3 % sobre remunerativo,
cuota sindical 2 % (porcentaje bancario real no verificado). El empleador,
el legajo, el número de lectura y las métricas son inventados.

## Los nueve bloques

0. Antes de subir: kit del convenio, escala vigente, catálogo maestro,
   perfiles de lectura (familia de formato y CUIT).
1. Marina sube la foto: preproceso, enmascarado (mejor esfuerzo),
   registro de lectura, perfil del CUIT si existe.
2. Llamada 1, encabezado y estructura: transcribe; huella de formato sin
   llamada extra.
3. Llamadas 2 y 3, líneas y totales, con sufijo de contexto estructurado
   (alias candidatos, columnas, ejemplo en texto); confianza por línea.
4. Compuerta: cierre aritmético; relectura del bloque que falla (≤ 2);
   "lectura incierta" sin evaluar fórmulas.
5. Normalización en cascada: alias CUIT → normalizado → alias sindicato →
   maestro → semántico → modelo entre candidatos → desconocida.
6. Juzgar: escala vigente para el período (nunca la más cercana),
   evaluador seguro, severidad y motivo, "no verificable" con causa.
7. Resultado: veredicto, cobertura declarada, verificado / no verificable,
   acciones.
8. Después, solo: métricas por lectura, perfiles que se refuerzan o se
   apagan, cola del sindicato con sugerencias.

Etiqueta de quién actúa en cada bloque: trabajador, modelo de IA
(transcribe, no decide), código de Colm3na (decide), sindicato/plataforma.

## Qué describe que todavía es propuesta (no código)

- Perfiles de lectura por familia de formato y por CUIT, inyectados como
  sufijo del prompt base (26/09).
- Kit de arranque por convenio (26/09).
- Cobertura declarada y grados de verificabilidad A–E (26/09).
- Lo demás (tres llamadas, cierre como compuerta, cascada, severidad,
  evaluador seguro) es el plan del motor v2 (`PLAN_MOTOR_V2.md`), en
  parte ya hecho (evaluador seguro, enmascarado) y en parte pendiente.

## Cómo se regenera la miniatura

Captura de la portada a 1280×720 con Chromium (Playwright), inyectando la
Barlow Condensed de `static/fonts/` para que el título salga con la
tipografía del sistema aunque no haya red.

## Para CLAUDE.md

Nada: no cambia una regla vigente. Solo suma un recurso a `SEMILLA`.
