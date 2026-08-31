# CCT 18/75 — Asociación Bancaria: lo que usa la simulación

Resumen de lo extraído del convenio bancario (texto ordenado 1975) para armar
recibos sintéticos en `cargar_bancaria.py`. **Los porcentajes y coeficientes
siguen siendo la estructura vigente; los importes de 1975 no** — el sueldo
inicial se toma del último acuerdo paritario.

## Las dos reglas que mandan sobre todo lo demás

1. **Casi todos los adicionales son un % del "sueldo inicial"** (Auxiliar
   inicial, art. 5 = coeficiente 1,00), **no** del básico propio del agente
   (arts. 11, 12, 14, 16, 22, 24, 25). Un cajero con 20 años cobra su
   adicional sobre el inicial, no sobre su básico de 1,74.
2. **La antigüedad NO es una línea del recibo**: está embebida en el básico,
   que sube por escala de coeficientes (art. 5) y dispara **promociones
   automáticas** de categoría a los 15/20/25/30/35 años (art. 44). Un rubro
   "Antigüedad" suelto no existe en este convenio.

## Valores vigentes usados (acuerdo con las cámaras, julio 2026)

| Concepto | Monto |
|---|---|
| Sueldo inicial (Auxiliar inicial, coef. 1,00) | $ 2.463.757,68 |
| Participación en las ganancias (ROE) | $ 71.219,54 |
| Día del Bancario (mínimo, a actualizar) | $ 2.196.354,74 |

Acumulado enero–julio 2026: 19,3% sobre diciembre 2025. Paritaria retomada en
la segunda quincena de septiembre de 2026.

## Escala de antigüedad (art. 5) — coeficiente sobre el inicial

0 años 1,00 · 1: 1,04 · 2: 1,08 · 3: 1,11 · 4: 1,13 · 5: 1,17 · 6: 1,20 ·
7: 1,24 · 8: 1,26 · 9: 1,30 · 10: 1,35 · 11: 1,39 · 12: 1,43 · 13: 1,48 ·
14: 1,52 · **15: 1,63** · **20: 1,74** · **25: 1,96** · **30: 2,07** ·
**35: 2,17**

Categoría por antigüedad (promoción automática): Auxiliar → 15 años Ayudante
de firma → 20 Jefe de Sección → 25 2º Jefe de División de 3º → 30 de 2º →
35 de 1º.

## Adicionales que la simulación reproduce

| Rubro | Art. | Regla (% del sueldo inicial) |
|---|---|---|
| Cajero — **función** | 22 | Recibidor 15% · Recibidor y pagador 20% · Pagador 25% |
| Cajero — **falla de caja** | 22 | Recibidor 20% · Recibidor y pagador 30% · Pagador 40% |
| Título habilitante | 10 | Uno solo, el de mayor monto (secundario < intermedio < universitario) |
| Funciones técnicas con título | 11 | Por agrupamiento y letra A–F según antigüedad en la función |
| Computación | 14 | Analista 95,2%…61,9% · Programador · Operador 66,7%…42,9% · etc. |
| Suplemento nocturno (21–6 h) | 15 B | A prorrata del horario nocturno, solo área de computación |
| Máquinas de contabilidad | 24 | 5,7% |
| Portavalores | 39 | Monto fijo mensual |
| Zona desfavorable | 25 | Grupo A 60% · B 50% · C 40% · D 20% |

**Función y falla de caja son DOS líneas distintas** del recibo: un pagador
cobra 25% + 40% en rubros separados.

## Lo que el convenio NO trae (y por eso no se inventa)

- **Ningún porcentaje de aportes de seguridad social** (jubilación, INSSJP,
  obra social): son de la ley general. La simulación usa 11% / 3% / 3%.
- **Ningún porcentaje de cuota sindical mensual.** El único descuento del CCT
  es un aporte solidario **por única vez** (Disposiciones Transitorias II:
  50% del primer aumento, a cargo de afiliados y no afiliados). Por eso la
  cuota sindical se carga como concepto pero **sin fórmula de validación** —
  el sistema no puede reclamar un porcentaje que el convenio no fija.
- **Presentismo**: no existe ningún premio por asistencia en este convenio.
- **Participación en las ganancias**: el art. 42 b) solo prohíbe absorberla si
  el banco ya la pagaba de forma habitual; el monto sale del acuerdo paritario.

## Otras particularidades (no simuladas, útiles para la demo)

- **Día del Bancario, 6 de noviembre** (art. 50), con normas de feriado nacional.
- **Día femenino** (art. 48 f): un día por mes sin justificar, con goce de sueldo.
- **Topes de encasillamiento** (arts. 11, 12, 14, 17): básico + adicional
  técnico no puede superar el mínimo de la jerarquía tope del agrupamiento.
- **Irreductibilidad** (art. 45): retirar una función no baja la remuneración;
  el adicional sigue hasta que lo absorban aumentos futuros.

Fuente: `1875.pdf` (38 páginas, texto ordenado del CCT 18/75) + comunicado de
la Asociación Bancaria del 18/08/2026 con los montos de julio 2026.
