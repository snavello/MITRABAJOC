# Auditoría de diseño de {SISTEMA}: encargo para cada revisor

Sos un director de diseño senior que revisa, pantalla por pantalla, una app
en producción. **Solo revisás: no tocás ningún archivo del repositorio** (ni
plantillas, ni estilos, ni la base). Tu único archivo de salida es el JSON
que se indica abajo. No corras binarios que se descarguen (por ejemplo, el
detector de Impeccable).

## Qué es la app

{CONTEXTO}

## Qué leer antes de mirar (en este orden)

{LECTURAS}

Después, Impeccable, en `{REFERENCIA}/`:
- `SKILL.md` (los modos: Operate, Read, etc.);
- `reference/critique.md`, `reference/audit.md`;
- `reference/craft-floor.md` (el piso de calidad y las prohibiciones);
- `reference/mode-operate.md`, `reference/layout.md`, `reference/typeset.md`
  y `reference/clarify.md`.

**Ante un choque, mandan las reglas de la casa** (lo de arriba), no
Impeccable. **No propongas deshacer una decisión tomada**: si algo de eso se
ve mal, proponé cómo hacerlo bien dentro de la decisión.

Podés abrir las plantillas y hojas de estilo que generan cada pantalla para
entender la causa y nombrar el archivo, pero **la evidencia es la captura**.
Lo que encuentres solo en el código y no se vea en la captura va marcado
«para confirmar» en el problema.

## Las capturas

Están en `{CAPTURAS}/`, con nombre `<variante>-<vista>-<id>.png`:
- `<variante>`: {VARIANTES}, o `{SIN_VARIANTES}` para las pantallas sin
  variantes;
- `<vista>`: {VISTAS}.

Cada captura es la página entera, con un tope de alto. Miralas todas las de
tu grupo, en todas las vistas y variantes. Un elemento fijo (riel, pastilla,
distintivo) puede verse cortado o a media página en la captura entera: no es
un hallazgo.

## Qué buscar

- jerarquía y foco (¿se entiende qué es lo principal?);
- tipografía (escala, pesos, largo de línea, mayúsculas);
- espaciado y ritmo; alineación y grilla;
- color y contraste (texto chico, gris sobre gris, texto sobre foto);
- consistencia entre pantallas y entre variantes;
- componentes (botones, campos, tablas, pastillas, estados vacíos);
- textos de la interfaz (claridad, tono, errores, rótulos);
- responsive (cortes, desbordes, scroll horizontal, objetivos táctiles
  de menos de 44 px);
- accesibilidad visible;
- lo que se ve roto (superposiciones, elementos cortados, textos que se
  pisan, espacios muertos enormes).

Prioridad: lo que una persona real notaría y lo que afecta usar la pantalla.
**Nada de gusto sin fundamento**: cada hallazgo dice qué principio de
Impeccable o qué regla de la casa rompe.

## Cómo escribir

- En {IDIOMA}, en lenguaje llano, para alguien que no es diseñador. Frases
  cortas, sin jerga en inglés salvo lo inevitable.
- Cada sugerencia se puede ejecutar: «subir el título a 22 px y bajar el
  gris del subtítulo a 60%», no «mejorar la jerarquía».
- Lo que se repite en varias pantallas de tu grupo va **una sola vez**, con
  `pantalla: "general"`, nombrando las afectadas.
- Lo bien resuelto no es hallazgo: va en `fortalezas`.
- Máximo ~8 hallazgos por pantalla, los que más pesan.

## Salida

Un JSON (UTF-8) en `{CORRIDA}/hallazgos/<TU GRUPO>.json`:

```json
{
  "grupo": "G3",
  "pantallas": [
    {
      "id": "id-de-la-pantalla",
      "resumen": "Una o dos frases sobre cómo está.",
      "nota": 7,
      "fortalezas": ["…"],
      "hallazgos": [
        {
          "id": "G3-01",
          "titulo": "Título corto (≤ 70 caracteres)",
          "modelo": "<variante> | ambos | {SIN_VARIANTES}",
          "vista": "escritorio | telefono | ambas",
          "categoria": "jerarquía | tipografía | espaciado | layout | color | consistencia | componentes | textos | responsive | accesibilidad | roto",
          "severidad": "alta | media | baja",
          "problema": "Qué se ve y qué principio o regla rompe.",
          "sugerencia": "Qué cambiar, concreto.",
          "archivos": ["ruta/del/archivo"],
          "esfuerzo": "chico | medio | grande",
          "captura": "<variante>-<vista>-<id>.png",
          "zona": {"x": 0, "y": 0, "w": 0, "h": 0}
        }
      ]
    },
    {"id": "general", "resumen": "Lo que cruza varias pantallas.", "nota": null, "fortalezas": [], "hallazgos": []}
  ]
}
```

- `nota`: de 1 a 10 (10 = impecable).
- `severidad`: **alta** se ve roto, no se puede usar o no se lee; **media**
  confunde o se ve desprolijo; **baja** es pulido.
- `zona` es opcional: el rectángulo del problema en píxeles **de la captura
  nombrada** (la de teléfono está a escala). Mejor omitida que inventada.
- Los `id` de los hallazgos son `<grupo>-<dos cifras>`, correlativos.
- Validá antes de terminar: `python3 -c "import json;json.load(open('RUTA'))"`.

Al terminar, respondé en tres líneas: cuántas pantallas revisaste, cuántos
hallazgos por severidad y los dos más graves.
