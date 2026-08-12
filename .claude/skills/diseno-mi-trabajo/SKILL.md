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

1. **Encabezado de marca**: logo del sindicato (42px) + nombre completo del
   sindicato + "Mi Trabajo" como subtítulo chico. El gremio manda, no la app.
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

Encabezado oscuro compacto (logo chico + título de sección + usuario), cuerpo
claro, botón principal en color de acento, pestaña activa marcada con acento.

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
