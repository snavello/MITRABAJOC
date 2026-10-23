/* Calculadora bancaria v2: las piezas chicas que se repiten.

   - <Numero>: un importe que corre de su valor anterior al nuevo. El texto
     lo escribe `correr` directo en el nodo (no Preact en cada cuadro), y una
     luz breve marca que cambió: así se ve QUÉ movió el último control.
   - <Tilde>: el ✓ de "coincide", dibujado con trazo cuando aparece.
   - <Luz>: el brillo que sigue al mouse sobre una tarjeta (solo con mouse y
     sin "reducir movimiento"). Se mueve con `transform` en su propio nodo:
     cambiar una variable CSS en la tarjeta recalcularía toda la tabla. */
import { useRef, useLayoutEffect, useEffect } from "preact/hooks";
import { html } from "calc/html";
import { correr, ms, menosMovimiento } from "calc/movimiento";

const fmt = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const pesos = (n) => (n < 0 ? "−$ " : "$ ") + fmt.format(Math.abs(n));
export const porcentaje = (n) => fmt.format(n) + "%";

export function Numero({ valor, formato = pesos, clase = "", dur = "--mov-cambio", destello = true }) {
  const ref = useRef(null);
  const primera = useRef(true);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (primera.current) {
      primera.current = false;
      el.textContent = formato(valor);
      el._valor = valor;
      return;
    }
    const desde = typeof el._valor === "number" ? el._valor : valor;
    if (Math.abs(desde - valor) < 0.005) { el.textContent = formato(valor); return; }
    const cortar = correr(el, desde, valor, ms(dur), formato);
    if (destello && !menosMovimiento() && el.animate) {
      el.animate([{ backgroundColor: "rgba(255,176,32,.20)" }, { backgroundColor: "rgba(255,176,32,0)" }],
        { duration: ms("--mov-cambio") + 400, easing: "cubic-bezier(.23,1,.32,1)" });
    }
    return cortar;
  }, [valor]);
  return html`<span class=${"numero " + clase} ref=${ref}></span>`;
}

export function Tilde({ titulo = "Coincide (tolerancia $ 1)" }) {
  return html`<svg class="tilde" viewBox="0 0 24 24" width="20" height="20" role="img" aria-label=${titulo}>
    <title>${titulo}</title>
    <circle class="tilde-aro" cx="12" cy="12" r="10" />
    <path class="tilde-marca" d="M7 12.5l3.2 3.2L17 9" />
  </svg>`;
}

export function Luz() {
  const ref = useRef(null);
  useEffect(() => {
    const luz = ref.current;
    const tarjeta = luz && luz.parentElement;
    if (!tarjeta || menosMovimiento() || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    let pedido = null;
    const mover = (e) => {
      const r = tarjeta.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      if (pedido) cancelAnimationFrame(pedido);
      pedido = requestAnimationFrame(() => { luz.style.transform = `translate(${x - 260}px, ${y - 260}px)`; });
    };
    const entrar = () => luz.classList.add("prendida");
    const salir = () => luz.classList.remove("prendida");
    tarjeta.addEventListener("pointermove", mover);
    tarjeta.addEventListener("pointerenter", entrar);
    tarjeta.addEventListener("pointerleave", salir);
    return () => {
      tarjeta.removeEventListener("pointermove", mover);
      tarjeta.removeEventListener("pointerenter", entrar);
      tarjeta.removeEventListener("pointerleave", salir);
    };
  }, []);
  return html`<div class="luz" ref=${ref} aria-hidden="true"></div>`;
}
