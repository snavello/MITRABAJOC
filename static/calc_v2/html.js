/* Calculadora bancaria v2: la forma de escribir plantillas (igual que la v2
   del Panel, static/panel_v2/html.js). htm atado a Preact, sin JSX y sin
   paso de build. Preact escapa todo lo que pinta: un concepto o una nota que
   viene del servidor nunca se interpreta como HTML (en la v2 no hay
   innerHTML). */
import { h } from "preact";
import htm from "htm";

export const html = htm.bind(h);
