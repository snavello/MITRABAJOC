/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md, bloque 3): los indicadores.

   Dirección B: los cuatro que más importan en grande sobre la tarjeta oscura
   de la marca, y el resto en una tira debajo. Mismos números, mismos textos y
   mismos ids que la v1 (`v-recibos`, `v-pdif`...): el robot de paridad los
   lee igual en las dos versiones.

   El número corre hasta su valor (D5): sale del que se ve en ese momento, no
   pasa de 600 ms, si llega otro a mitad de camino arranca desde donde está,
   y con prefers-reduced-motion aparece directo. */
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { fmtN, fmtM, fmtPct, deltaRecibos } from "panel/formato";

const DURACION = 600;
const menosMovimiento = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function useCorrer(valor) {
  const [mostrado, setMostrado] = useState(menosMovimiento() ? valor : null);
  const enPantalla = useRef(null);
  useEffect(() => {
    if (valor === null || valor === undefined || menosMovimiento()) {
      enPantalla.current = valor; setMostrado(valor); return undefined;
    }
    const desde = enPantalla.current === null || enPantalla.current === undefined ? 0 : enPantalla.current;
    const t0 = performance.now();
    let raf = 0;
    const paso = (t) => {
      const p = Math.min(1, (t - t0) / DURACION);
      const v = p < 1 ? desde + (valor - desde) * (1 - Math.pow(1 - p, 3)) : valor;
      enPantalla.current = v;
      setMostrado(v);
      if (p < 1) raf = requestAnimationFrame(paso);
    };
    raf = requestAnimationFrame(paso);
    return () => cancelAnimationFrame(raf);
  }, [valor]);
  return mostrado;
}

/* Un decimal mientras corre; el valor final, tal cual lo manda el servidor. */
const unDecimal = (v, final) => (v === final ? v : Math.round(v * 10) / 10);

function Valor({ id, valor, formato, clase = "val num" }) {
  const v = useCorrer(valor);
  const texto = v === null || v === undefined ? "—" : formato(v);
  return html`<div class=${clase} id=${"v-" + id}>${texto}</div>`;
}

export function Kpis({ datos, consultas, error, reintentar }) {
  const a = datos ? datos.actual : {};
  const delta = datos ? deltaRecibos(a.recibos, datos.anterior.recibos) : null;
  const n = (v) => fmtN(Math.round(v));
  const pct = (final) => (v) => fmtPct(unDecimal(v, final));
  const total = a.padron_total;
  const minis = [
    ["enviados", "Enviados al sindicato", a.enviados_sindicato, n],
    ["tramites", "Trámites del período", a.tramites, n],
    ["notif", "Notif. enviadas", a.notif_enviadas, n],
    ["lectura", "Tasa de lectura", a.tasa_lectura, pct(a.tasa_lectura)],
    ["padron", "Afiliados registrados", a.padron_registrados, (v) => n(v) + " / " + fmtN(total)],
  ].concat(consultas ? [["bot", "Consultas al asistente", a.consultas, n]] : []);
  return html`
    ${error && html`<div class="v2-error-kpis">No se pudieron cargar los indicadores.
      <button type="button" onClick=${reintentar}>Reintentar</button></div>`}
    <div class="v2-heroes">
      <div class="v2-hero grande">
        <div class="v2-kicker">Recibos analizados</div>
        <${Valor} id="recibos" valor=${a.recibos} formato=${n} />
        ${delta && html`<div class=${"delta " + delta.clase} id="d-recibos">${delta.texto}</div>`}
      </div>
      <div class="v2-hero"><div class="et">% con diferencias</div>
        <${Valor} id="pdif" valor=${a.pct_con_diferencias} formato=${pct(a.pct_con_diferencias)} /></div>
      <div class="v2-hero ancho-movil"><div class="et">Monto observado</div>
        <${Valor} id="monto" valor=${a.monto_observado} formato=${fmtM} /></div>
      <div class="v2-hero"><div class="et">Trámites sin resolver</div>
        <${Valor} id="tabiertos" valor=${a.tramites_sin_resolver} formato=${n} /></div>
    </div>
    <div class=${"v2-minis" + (minis.length > 5 ? " seis" : "")}>
      ${minis.map(([id, et, valor, formato]) => html`
        <div class="v2-mini"><div class="et">${et}</div>
          <${Valor} id=${id} valor=${valor} formato=${formato} clase="val num" />
          ${id === "padron" && total ? html`<div class="delta neu" id="d-padron">${Math.round(a.padron_registrados / total * 100)}% del padrón</div>` : ""}
        </div>`)}
    </div>`;
}
