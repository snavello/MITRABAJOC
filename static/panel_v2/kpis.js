/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md, bloque 3): los indicadores.

   Dirección B: los cuatro que más importan en grande sobre la tarjeta oscura
   de la marca, y el resto en una tira debajo. Mismos números, mismos textos y
   mismos ids que la v1 (`v-recibos`, `v-pdif`...): el robot de paridad los
   lee igual en las dos versiones.

   El número corre hasta su valor (D5): sale del que se ve en ese momento,
   tarda `--mov-correr` (son lo primero que se ve: se bancan un poco más que
   el resto), si llega otro a mitad de camino arranca desde donde está, y con
   prefers-reduced-motion aparece directo. Mientras no llegó el primero, en
   lugar del "—" va un esqueleto con brillo. */
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { fmtN, fmtM, fmtPct, deltaRecibos } from "panel/formato";
import { menosMovimiento, ms } from "panel/movimiento";

export function useCorrer(valor) {
  const [mostrado, setMostrado] = useState(menosMovimiento() ? valor : null);
  const enPantalla = useRef(null);
  useEffect(() => {
    if (valor === null || valor === undefined || menosMovimiento()) {
      enPantalla.current = valor; setMostrado(valor); return undefined;
    }
    const desde = enPantalla.current === null || enPantalla.current === undefined ? 0 : enPantalla.current;
    const t0 = performance.now();
    const duracion = ms("--mov-correr");
    let raf = 0;
    const paso = (t) => {
      const p = Math.min(1, (t - t0) / duracion);
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

function Valor({ id, valor, formato, clase = "val num", esperando }) {
  const v = useCorrer(valor);
  if ((v === null || v === undefined) && esperando) {
    return html`<div class=${clase} id=${"v-" + id}><span class="v2-esq-num" aria-label="Cargando"></span></div>`;
  }
  const texto = v === null || v === undefined ? "—" : formato(v);
  return html`<div class=${clase} id=${"v-" + id}>${texto}</div>`;
}

/* La variación contra el período anterior: la cifra en la tipografía de los
   números y la frase en la del texto (la monoespaciada es para cifras). Con
   "Hoy" no se compara un día a medio andar contra uno entero, que siempre
   daba una caída en rojo: se dice cuántos hubo ayer (G7-09). */
function Delta({ actual, anterior, esHoy }) {
  if (esHoy) {
    return html`<div class="delta neu" id="d-recibos">ayer: <span class="cifra">${fmtN(anterior || 0)}</span></div>`;
  }
  const d = deltaRecibos(actual, anterior);
  const m = /^(\S+ \d+%)(.*)$/.exec(d.texto);
  return html`<div class=${"delta " + d.clase} id="d-recibos">${m
    ? html`<span class="cifra">${m[1]}</span><span class="frase">${m[2]}</span>` : d.texto}</div>`;
}

export function Kpis({ datos, consultas, error, reintentar, esHoy = false }) {
  const a = datos ? datos.actual : {};
  const n = (v) => fmtN(Math.round(v));
  const pct = (final) => (v) => fmtPct(unDecimal(v, final));
  const total = a.padron_total;
  const esperando = !datos && !error;
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
    <div class=${"v2-heroes" + (esperando ? " esperando" : "")}>
      <div class="v2-hero grande">
        <div class="v2-kicker">Recibos analizados</div>
        <${Valor} id="recibos" valor=${a.recibos} formato=${n} esperando=${esperando} />
        ${datos && html`<${Delta} actual=${a.recibos} anterior=${datos.anterior.recibos} esHoy=${esHoy} />`}
      </div>
      <div class="v2-hero"><div class="et">% con diferencias</div>
        <${Valor} id="pdif" valor=${a.pct_con_diferencias} formato=${pct(a.pct_con_diferencias)} esperando=${esperando} /></div>
      <div class="v2-hero ancho-movil"><div class="et">Monto observado</div>
        <${Valor} id="monto" valor=${a.monto_observado} formato=${fmtM} esperando=${esperando} /></div>
      <div class="v2-hero"><div class="et">Trámites sin resolver</div>
        <${Valor} id="tabiertos" valor=${a.tramites_sin_resolver} formato=${n} esperando=${esperando} /></div>
    </div>
    <div class=${"v2-minis" + (minis.length > 5 ? " seis" : "") + (esperando ? " esperando" : "")}>
      ${minis.map(([id, et, valor, formato]) => html`
        <div class="v2-mini"><div class="et">${et}</div>
          <${Valor} id=${id} valor=${valor} formato=${formato} clase="val num" esperando=${esperando} />
          ${id === "padron" && total ? html`<div class="delta neu" id="d-padron">${Math.round(a.padron_registrados / total * 100)}% del padrón</div>` : ""}
        </div>`)}
    </div>`;
}
