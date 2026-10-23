/* Asistente de trámites: la forma de escribir plantillas (igual que la v2
   del Panel y la Calculadora v2). htm atado a Preact, sin JSX y sin paso de
   build. Preact escapa todo lo que pinta: un relato, una etiqueta o una
   nota que viene del servidor nunca se interpreta como HTML (acá no hay
   innerHTML). */
import { h } from "preact";
import htm from "htm";

export const html = htm.bind(h);
