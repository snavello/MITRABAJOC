# Norma de diagramas del documento integrador

Todos los diagramas del documento se dibujan con este mismo sistema. La
meta es que se vean como de UN solo autor, sobrios y profesionales: un
lector frío tiene que ver el mecanismo (por dónde pasan los datos, quién
habla con quién, qué cambia entre dos estados) sin leer párrafos dentro
de las cajas. Si una frase lo dice más rápido, va en el texto o en el pie,
no en el dibujo.

Antes de dibujar, mirá el diagrama de referencia
`partes/_referencia_diagrama.svg` (abrilo con Read tras convertirlo, o
leé su código): es el patrón a imitar.

## Principios

1. **Un diagrama, una idea.** Lo que el diagrama afirma va en el
   `<figcaption>` y en el `aria-label`. Nada de títulos adentro del SVG.
2. **Dibujar el mecanismo, no su nombre.** Cajas con una etiqueta corta
   (1 a 3 palabras) y, como mucho, una línea secundaria corta. Las
   explicaciones van al pie. **Máximo 2 líneas de texto por caja** (título
   + una línea), 3 solo en casos excepcionales.
3. **Flechas con nombre.** Toda flecha que no sea obvia lleva una etiqueta
   corta (`lee`, `envía`, `si no coincide`), en minúscula.
4. **Casi sin color.** El gris hace el trabajo; el color marca UNA cosa.
5. **Grilla.** Todo alineado: mismas alturas y anchos en una fila,
   separaciones iguales, coordenadas múltiplos de 4.

## Tokens (usar exactamente estos valores)

Lienzo: `viewBox="0 0 860 H"` (H justo al contenido, margen 16). El fondo
lo pone la figura: el SVG no dibuja fondo.

| Uso | Valor |
|---|---|
| Caja normal | `fill="#ffffff" stroke="#b8c3d1" stroke-width="1.25" rx="8"` |
| Caja destacada (lo que la figura quiere mostrar; 1 o 2 por figura) | `fill="#fff8ec" stroke="#e0951a" stroke-width="1.75" rx="8"` |
| Caja central/sistema (solo si hay un núcleo, p. ej. «Colm3na») | `fill="#0a1421" stroke="none" rx="8"`, textos en `#ffffff` y secundario `#aeb9c8` |
| Zona o grupo | `fill="#eef2f6" stroke="none" rx="12"`; rótulo arriba a la izquierda, ver abajo |
| Zona punteada (algo futuro o externo) | `fill="none" stroke="#b8c3d1" stroke-width="1.25" stroke-dasharray="5 4" rx="12"` |
| Título de caja | `font-family="Barlow Condensed" font-weight="700" font-size="16" fill="#0a1421"` |
| Línea secundaria | `font-size="12" fill="#5b6778"` |
| Rótulo de zona | `font-size="11" font-weight="700" letter-spacing="1.2" fill="#5b6778"` en MAYÚSCULAS |
| Etiqueta de flecha | `font-size="11.5" fill="#5b6778"` con halo: `paint-order="stroke" stroke="#f8fafc" stroke-width="4" stroke-linejoin="round"` |
| Flecha | `stroke="#7a8799" stroke-width="1.5" fill="none"` con `marker-end="url(#<prefijo>-fl)"` |
| Flecha destacada | `stroke="#e0951a"` y su propio marker del mismo color |
| Flecha "opcional / a veces" | igual con `stroke-dasharray="4 4"` |
| Número de paso | `<circle r="11" fill="#0a1421"/>` + número `font-size="12" font-weight="700" fill="#ffffff" text-anchor="middle"` |
| Estado OK / error / aviso | SOLO en una marca chica (punto `r=4`, tilde o cruz de trazo) o en el borde de una caja de resultado: verde `#0d7a5f`, rojo `#c0392b`, ámbar `#b8860b`. Nunca como relleno fuerte. |

Marker (uno por figura, ids con prefijo único por figura, p. ej. `f5a`):

```svg
<defs>
  <marker id="f5a-fl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,1 L9,5 L0,9 z" fill="#7a8799"/>
  </marker>
</defs>
```

**Prohibido**: colores fuera de esta tabla (nada de violeta, azul o verde
de relleno para distinguir cajas "porque sí"; si hace falta distinguir
grupos, usar zonas grises con rótulo); barras negras de título; sombras;
degradés; emojis; texto de menos de 11 px; texto en diagonal; flechas
cruzadas cuando se pueden evitar; cajas de distinto alto en la misma fila.

## Medidas y alineación

- Alto de caja: 52 (una línea) o 64 (título + secundaria). Ancho mínimo:
  el del texto más largo + 32 de aire (calculá ~7,2 px por carácter a 12 px
  y ~7,6 px por carácter a 16 px condensada, para estar seguro).
- Texto centrado en la caja: título en `y = top + 26` (caja de 52) o
  `top + 27` y secundaria en `top + 45` (caja de 64), `text-anchor="middle"`.
- Separación entre cajas de una fila: 24 o 32, la misma en toda la fila.
- Flechas ortogonales (`polyline`/`path` con tramos horizontales y
  verticales) antes que diagonales. Una flecha arranca y termina en el
  BORDE de la caja, con 2 px de aire.
- Una etiqueta de flecha va arriba del tramo horizontal (y − 6) o al
  costado del vertical, nunca encima de una caja.

## Verificación obligatoria

1. `node docs/integrador/revisar_diagramas.js docs/integrador/partes/<tu archivo>.html`
   revisa cada diagrama y lista: textos que se salen de su caja, textos
   encimados, textos fuera del lienzo, tamaños de letra chicos y colores
   fuera de la paleta. Tiene que terminar en **0 problemas**.
2. El mismo comando deja `/tmp/claude-0/-home-user-MITRABAJOC/164c3e45-fe4e-5e22-9d1c-3e1986620d33/scratchpad/diagramas/<archivo>-NN.png`: mirá CADA
   imagen con Read y corregí lo que se vea mal (desalineado, apretado,
   flechas que no llegan, desequilibrio).
