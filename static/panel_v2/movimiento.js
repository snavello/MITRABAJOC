/* Panel Sindical v2: el movimiento, en un solo lugar.

   Caso cero del movimiento de toda la plataforma (skill `diseno-mi-trabajo`,
   sección "Movimiento"; referencia: skill `emil-design-eng`). Las duraciones
   y las curvas viven como variables en panel.css (`--mov-*`, `--ease-*`) y
   este módulo las LEE: el CSS y los gráficos de Chart.js usan los mismos
   números, y cambiar uno es cambiarlo en un solo archivo.

   Lo que vive acá:
   - `menosMovimiento()`: si la persona pidió "reducir movimiento" en su
     sistema. Con eso prendido no se anima nada (marca.css corta todo).
   - `ms(token)`: una duración de panel.css en milisegundos.
   - `alEntrar(el, fn)`: avisa una sola vez cuando el elemento entra en
     pantalla, con el escalón que le toca si entran varios juntos. Es lo que
     hace que un gráfico se dibuje cuando la persona lo mira, y no cuando
     llegan los datos (que suele ser con el panel todavía fuera de vista). */

export const menosMovimiento = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const DEFECTOS = { "--mov-datos": 900, "--mov-cambio": 500, "--mov-correr": 900, "--mov-escalon": 60 };

export function ms(token) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  const n = parseFloat(v);
  if (isNaN(n)) return DEFECTOS[token] || 0;
  return v.endsWith("ms") ? n : n * 1000;
}

/* Un solo observador para todos los paneles: así, si en un mismo paso entran
   varios (los de una misma fila), salen escalonados de izquierda a derecha y
   de arriba abajo, con `--mov-escalon` entre uno y otro. */
const avisos = new Map();
let observador = null;
const TOPE_ESCALON = 4;

function revisar(entradas) {
  const vistas = entradas.filter((e) => e.isIntersecting)
    .sort((a, b) => (a.boundingClientRect.top - b.boundingClientRect.top) || (a.boundingClientRect.left - b.boundingClientRect.left));
  const paso = ms("--mov-escalon");
  vistas.forEach((e, i) => {
    const fn = avisos.get(e.target);
    observador.unobserve(e.target);
    avisos.delete(e.target);
    if (fn) fn(Math.min(i, TOPE_ESCALON) * paso);
  });
}

export function alEntrar(el, fn) {
  if (!el) return () => {};
  if (menosMovimiento() || !("IntersectionObserver" in window)) { fn(0); return () => {}; }
  if (!observador) {
    // Se considera "en pantalla" cuando el borde de arriba ya subió un poco
    // sobre el de abajo de la ventana: verlo asomar no alcanza.
    observador = new IntersectionObserver(revisar, { rootMargin: "0px 0px -10% 0px", threshold: 0 });
  }
  avisos.set(el, fn);
  observador.observe(el);
  return () => { avisos.delete(el); if (observador) observador.unobserve(el); };
}
