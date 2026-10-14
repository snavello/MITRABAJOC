/* Calculadora bancaria v2: el movimiento, en un solo lugar.

   Las duraciones y curvas son las de toda la plataforma (`--mov-*`,
   `--ease-*` de static/movimiento.css, skill `diseno-mi-trabajo` →
   "Movimiento"; referencia, `emil-design-eng`). Este módulo las LEE para lo
   que se anima desde JavaScript: los números que corren de un valor a otro.

   - `menosMovimiento()`: la persona pidió "reducir movimiento"; entonces los
     números saltan directo a su valor y solo quedan fundidos.
   - `ms(token)`: una duración de movimiento.css en milisegundos.
   - `correr(el, desde, hasta, dur, formato)`: anima el texto de un número.
     Es interrumpible: si llega otro valor a mitad de camino, arranca desde
     el que se está mostrando, no desde el anterior. */

export const menosMovimiento = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const DEFECTOS = { "--mov-medio": 320, "--mov-cambio": 800, "--mov-correr": 1600, "--mov-escalon": 120 };

export function ms(token) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  const n = parseFloat(v);
  if (isNaN(n)) return DEFECTOS[token] || 0;
  return v.endsWith("ms") ? n : n * 1000;
}

// La curva de `--ease-mueve` (.65,0,.35,1): un número que pasa de un valor a
// otro se MUEVE, no entra. Es simétrica, así que alcanza con una cúbica.
const mueve = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function correr(el, desde, hasta, dur, formato) {
  if (!el) return () => {};
  if (el._correr) cancelAnimationFrame(el._correr);
  if (menosMovimiento() || !dur || desde === hasta || !isFinite(desde)) {
    el.textContent = formato(hasta);
    el._valor = hasta;
    return () => {};
  }
  const inicio = performance.now();
  const paso = (ahora) => {
    const t = Math.min(1, (ahora - inicio) / dur);
    const v = desde + (hasta - desde) * mueve(t);
    el.textContent = formato(t === 1 ? hasta : v);
    el._valor = v;
    el._correr = t < 1 ? requestAnimationFrame(paso) : null;
  };
  el._correr = requestAnimationFrame(paso);
  return () => { if (el._correr) cancelAnimationFrame(el._correr); };
}
