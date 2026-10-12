/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md): la forma de escribir plantillas.

   `html` es htm atado a Preact: plantillas en JavaScript común, sin JSX y sin
   paso de build (D1). Se usa así:

     html`<div class="panel">${valor}</div>`

   Preact escapa todo lo que pinta, así que un nombre o un texto que viene
   del servidor nunca se interpreta como HTML (línea roja 5: en la v2 no hay
   innerHTML). Todos los módulos importan `html` de acá, no htm directo. */
import { h } from "preact";
import htm from "htm";

export const html = htm.bind(h);
