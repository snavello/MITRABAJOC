/* Asistente de trámites: el movimiento que se anima desde JavaScript, en un
   solo lugar. Las duraciones y curvas son las de toda la plataforma
   (`--mov-*`, `--ease-*` de static/movimiento.css, skill `diseno-mi-trabajo`
   → "Movimiento"); este módulo las LEE, no las define. */

export const menosMovimiento = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const DEFECTOS = { "--mov-rapido": 160, "--mov-medio": 320, "--mov-lento": 650, "--mov-cambio": 800, "--mov-escalon": 120 };

export function ms(token) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  const n = parseFloat(v);
  if (isNaN(n)) return DEFECTOS[token] || 0;
  return v.endsWith("ms") ? n : n * 1000;
}

/* Un número que corre de un valor a otro (el contador de preguntas, la
   cuenta de brechas). Interrumpible: si llega otro valor a mitad de camino,
   arranca desde el que se está mostrando. */
const mueve = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function correr(el, desde, hasta, dur, formato = String) {
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
    el.textContent = formato(t === 1 ? hasta : Math.round(v));
    el._valor = v;
    el._correr = t < 1 ? requestAnimationFrame(paso) : null;
  };
  el._correr = requestAnimationFrame(paso);
  return () => { if (el._correr) cancelAnimationFrame(el._correr); };
}

/* Subir al principio al cambiar de pantalla: suave, salvo con "reducir
   movimiento". */
export function arriba() {
  window.scrollTo({ top: 0, behavior: menosMovimiento() ? "auto" : "smooth" });
}
