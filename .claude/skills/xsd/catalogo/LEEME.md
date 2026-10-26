# Catálogo de estilos de XSD

Son 60 estilos de interfaz, cada uno aplicado a la misma portada de teléfono de **ACME**, una red de
servicios inventada. Sirven para elegir una dirección de diseño mirando opciones reales, antes de
pedir un mockup o un plan para rehacer un sistema.

Los estilos salen de un concurso de diseño de diez rondas y de otras propuestas hechas para Colm3na,
113 en total, agrupadas por familia. Se eligieron 60 en tres tandas, todas aprobadas.

## Las familias

| Familia | Estilos |
|---|---|
| Los que eligió Colm3na | 4 |
| Claros de producto | 6 |
| Muy claros | 4 |
| De color | 4 |
| Grises con uno o dos colores | 5 |
| Editoriales | 4 |
| Fotográficos | 2 |
| Con objeto | 3 |
| Flúor | 5 |
| Oscuros | 3 |
| Con movimiento sereno | 10 |
| Con movimiento y energía | 10 |

## Qué hay acá

```
armar.py        arma la página: python armar.py [salida.html] (por defecto xsd-trabajo/catalogo/index.html)
pagina.html     el cascarón de la página, con la estética del informe de XSD
molde.html      la portada de ACME (360 × 740) que visten todos los estilos
base.css        la base neutra y los tokens que pisa cada estilo
estilos/        un <id>.css por estilo (más <id>.heroe.html si el héroe cambia de estructura)
estilos.json    nombre, origen, carácter, firma y cuidados de cada estilo
acme.json       la organización inventada y el contenido de las cuatro pantallas
fotos/          siete fotos de ejemplo de StockSnap con licencia CC0 (créditos en fotos/creditos.json)
captura.cjs     capturas con Playwright: node captura.cjs <pagina.html> <carpeta> [ids] (ESPERA=ms)
encargos/       las consignas que siguieron los agentes: extracción, estilo y movimiento
```

## Reglas de cada estilo

- La primera línea es `/* fuentes: … */`, con la sintaxis de Google Fonts css2. `armar.py` junta todas las
  familias en un solo enlace.
- La segunda línea, si hay fotos, es `/* foto: héroe; novedad */`.
- Todo va bajo `.e-<id>`.
- Las animaciones de entrada van bajo `.e-<id>.en-vista`. La página pone esa clase cuando la portada entra
  en pantalla y el botón «Repetir la animación» la vuelve a poner.
- Todas tienen su bloque `prefers-reduced-motion`.
- Solo CSS: el catálogo no ejecuta JavaScript por estilo.

## Cómo se publica

Se publica como artifact de claude.ai, con la página y `fotos/*.jpg` como archivos, y con las capacidades
`{"db": {}, "user": {}}`. Lo que la persona marca (Va, No va, Va con cambios) queda en la colección
`preview` del artifact.

## Lo que sigue

Hoy el catálogo muestra solo la portada. La segunda etapa suma:
- las otras tres pantallas de ACME para cada estilo (operación, listado y tablero; el contenido ya está
  en `acme.json`);
- los pedidos que salen del catálogo: un mockup del sistema de la persona en el estilo elegido, sugerencias
  de cambio y un plan para rehacer parte o todo.
