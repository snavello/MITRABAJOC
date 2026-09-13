---
name: diseno-mi-trabajo
description: Sistema de diseño de Mi Trabajo (plataforma multi-sindicato). Define la paleta por sindicato, la tipografía fija, los componentes y las reglas de portada oscura + interiores claros. Usar al crear o modificar cualquier pantalla de las apps de trabajador, sindicato o plataforma.
---

# Sistema de diseño — Mi Trabajo

Plataforma multi-sindicato: cada sindicato tiene su marca, pero el formato es
único. La estructura y la tipografía NO cambian entre sindicatos; solo cambian
cuatro colores, inyectados como variables CSS desde la base de datos.

## Regla de oro

Portada del trabajador: **oscura**. Todo el resto: **claro con encabezado oscuro**.
El color de acento da continuidad entre ambas.

## Los cuatro colores por sindicato

Se cargan en el alta del sindicato y se inyectan en `:root` al renderizar.

| Variable | Rol | Dónde se usa |
|---|---|---|
| `--marca-base` | Base oscura | Fondo de la portada, encabezados, barra inferior |
| `--marca-primario` | Color institucional | Identidad: detalles, bordes activos, logo de respaldo |
| `--marca-acento` | Acción | Botón principal, tarjeta destacada, pestaña activa |
| `--marca-apoyo` | Apoyo | Chips, fondos suaves, íconos secundarios |

`--marca-base` debe ser oscuro (luminancia baja) para que el texto blanco
contraste. Si un sindicato carga un color claro, se rechaza en el formulario.

Las superficies intermedias NO se cargan: se derivan de la base con `color-mix`,
así un solo color genera toda la escala oscura.

```css
--sup-1: color-mix(in srgb, var(--marca-base) 88%, white);  /* tarjeta */
--sup-2: color-mix(in srgb, var(--marca-base) 80%, white);  /* borde */
```

## Fijo para todos los sindicatos

Nunca se personaliza:

- **Tipografía**: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`
  para todo el texto. Importes y cifras en `ui-monospace, Consolas, monospace`
  con `font-variant-numeric: tabular-nums`, para que las columnas de números
  se alineen.
- **Escala tipográfica**: 30 / 24 / 20 / 16 / 14 / 12.5 / 11 px.
- **Grises**: `--tinta:#152238` `--gris:#5b6478` `--linea:#e4e7ec` `--papel:#f6f7f9`
- **Colores de estado** (semáforo de aportes, validaciones): verde `#0d7a5f`,
  rojo `#c0392b`, ámbar `#b8860b`. Tienen significado propio: **jamás** toman
  la marca del sindicato.
- **Radios**: 12px tarjetas, 9px botones, 20px chips.
- **Espaciado**: múltiplos de 4. Padding lateral de pantalla: 15px en móvil.

## Estructura de la portada del trabajador

1. **Encabezado de marca**: el parcial común, igual que en todas las
   pantallas (ver "El encabezado" más abajo). El gremio manda, no la app.
2. **Saludo**: "Hola, {nombre}" con el nombre en color de acento, y debajo
   seccional y antigüedad de afiliación.
3. **Tarjetas de acceso** en grilla de 2 columnas: Tu recibo (destacada con
   fondo de acento), Mis aportes, Credencial, Capacitación. Cada una con ícono
   de línea, título y una línea de estado real ("12 de 12 al día", no "Ver más").
4. **Novedades**: hasta 3 items con título y antigüedad, más "Ver todas".
5. **Beneficios**: fila de 3 tarjetas chicas.
6. **Barra inferior**: 4 pestañas con íconos SVG de línea y píldora de fondo
   en la activa.

## Pantallas interiores

Encabezado común (abajo), cuerpo claro, botón principal en color de acento,
pestaña activa marcada con acento.

## El encabezado (2026-09-13): uno solo, para las cuatro apps

**Ninguna pantalla escribe su propio encabezado.** Se arma SIEMPRE con
`{% include "_encabezado.html" %}`, que trae su hoja (`static/encabezado.css`)
y no depende de `marca.css` — `trabajador.html` y `empresa.html` no la cargan.
Son dos franjas y esa separación es el punto:

    CINTA   [ rol del panel ]                          [ Colm3na ]
    BARRA   [ logo del sindicato ]                     [ pantalla ]

- La **cinta** dice quién opera la plataforma: el logo de Colm3na a la
  derecha, siempre 17px de alto. A la izquierda, el rol del panel
  ("Panel de administración", "Panel de empleador"…) — **vacío en la app del
  afiliado**: ahí la plataforma firma con el logo, no con texto.
- La **barra** es del sindicato: su logo a 62px de alto (46 en móvil) y
  **ancho libre** (un logo horizontal no se aplasta en una caja cuadrada) y,
  a la derecha, el nombre de la pantalla. En los paneles con pestañas lo
  actualiza el JS al cambiar de pestaña.
- Donde la marca principal ES la plataforma (panel de plataforma, demo
  anónima), la barra lleva el logo de Colm3na y **la cinta no lo repite**;
  si además no hay rol que mostrar, la cinta no se dibuja.
- **El nombre del sindicato en texto solo aparece si NO hay logo cargado**
  (entonces es el logotipo, en condensada sobre un filo de acento). Con logo,
  escribirlo al lado es decir dos veces lo mismo.
- **El título de la pantalla se dice una sola vez**: si está en el
  encabezado, no va también como `<h1>` del cuerpo.
- **La plataforma se llama Colm3na**: "Mi Trabajo" no va en ninguna
  pantalla. Los `<title>` siguen el mismo criterio que el encabezado:
  `<pantalla> — {{ sindicato }}` donde hay sindicato, `Colm3na — <pantalla>`
  donde no lo hay.
- Variables del parcial: `enc_rol`, `enc_pantalla`, `enc_volver`, `enc_fecha`,
  `enc_fija`, `enc_plataforma`. Una pantalla nueva se encabeza con eso.
- Fuera del sistema, a propósito: los tres ingresos (el logo grande de
  plataforma es la identidad de esa pantalla) y las herramientas internas del
  equipo (`/entornos`, informes de carga).

## Mapas

Leaflet vendoreado, teselas de OpenStreetMap con su atribución. Una seccional
en un mapa de tablero es una **burbuja** (`MapaMT.burbuja`): el tamaño es una
cantidad, el borde el color de la escala cuantitativa —fija de la app, cinco
azules, nunca la marca del gremio—, el relleno dice si está seleccionada
(color destacado) y adentro va el logo del sindicato en marca de agua.

Un mapa de tablero **es el selector**: tocar una burbuja filtra el tablero y
el mapa NO se filtra a sí mismo, o sería un camino sin vuelta.

## Modales

Hoja que entra desde abajo, encabezado en `--marca-base` con el nombre del
sindicato arriba del título, cuerpo claro. Máximo 82vh con scroll propio.

**En escritorio se arrastran del encabezado** (`static/modales.js`, un archivo
compartido por todas las pantallas). Al crear una familia nueva de modal hay
que sumar su caja a `CAJAS` de ese archivo y su encabezado a la regla del
cursor en `marca.css`, o ese modal va a ser el único que no se mueve. En
teléfono no se arrastran: ahí el modal ocupa el ancho completo y no hay nada
atrás que destapar.

## El flujo del recibo (2026-09-13)

Los cuatro pasos comparten vocabulario y están en `trabajador.html`
(`.rc-*` para la estructura, `.ia-*` para la espera):

- **Kicker** en primario + **título en condensada** (`.rc-h1`) en cada paso,
  y el paso numerado ("Paso 1 de 3") cuando corresponde.
- La **acción** vive en la tarjeta oscura con filo de acento (`.rc-oscura`);
  el resto de la pantalla es claro.
- **Los tildes son SVG de línea, nunca `✓` ni `✗` de texto**: como
  caracteres se ven de distinto tamaño según la fuente del sistema.
- **Toda cifra va en `--fuente-num` con `tabular-nums`**, para que las
  columnas de importes se alineen.
- **La espera muestra el tiempo real**, no una barra indeterminada: el
  cronómetro cuenta los segundos y las fases dicen qué está pasando.
- **Una pantalla que pide una foto explica cómo sacarla.** Que entre
  completo, luz pareja, apoyado y derecho: de eso depende que la lectura
  salga bien.
- Ojo con las variables: `trabajador.html` y `empresa.html` **no cargan
  `marca.css`** y definen las suyas. Ahí el verde es `--agua`, no
  `--verde`; un `var()` inexistente no falla, hereda y se ve mal.

## Íconos

SVG de línea, `stroke-width:1.7`, `fill:none`, 22px en la barra, 26px en
tarjetas. Nunca emojis.

## Escritura de la interfaz

Voz en segunda persona y rioplatense: "Revisá tu recibo", "Subí el PDF".
Los botones dicen la acción exacta que ejecutan. Los estados vacíos invitan a
actuar, no se disculpan. Los errores explican qué pasó y cómo seguir.

## Al construir

Trabajar sobre `templates/` (Jinja2) y el CSS de cada plantilla. No introducir
frameworks: el sistema es CSS propio con variables. Verificar contraste del
texto sobre `--marca-base` y probar con al menos dos paletas distintas antes de
dar por buena una pantalla.
