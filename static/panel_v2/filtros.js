/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md, bloque 3): los filtros.

   Dirección B, "Sala de mando" (elegida por SDN sobre el mockup de D5): el
   período y los filtros puestos van en una barra arriba de los números, y el
   resto de los filtros en un cajón que se abre con "Filtros". Cada control
   se comporta como su par de la v1 (static/dashboard.js); el estado lo
   cambia SOLO el reductor de panel/estado (D8): acá nada lo toca directo. */
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { fmtN } from "panel/formato";
import { fISO, presetActivo, filtrosActivos } from "panel/estado";

const PRESETS = [["hoy", "Hoy"], ["7", "7 días"], ["30", "30 días"], ["90", "90 días"]];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
  "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

/* ---------------- La barra: período, filtros puestos, Reiniciar ---------------- */

export function BarraFiltros({ estado, despachar, hoy, lim, catalogo, afiliados, abrirCajon }) {
  const p = presetActivo(estado, hoy);
  const puestos = filtrosActivos(estado, { catalogo, lim, afiliados });
  return html`
    <div class="v2-barra">
      <span class="v2-kicker">Período</span>
      <div class="v2-presets" role="group" aria-label="Período rápido">
        ${PRESETS.map(([valor, txt]) => html`
          <button type="button" class=${"v2-chip" + (p === valor ? " act" : "")}
            aria-pressed=${p === valor} onClick=${() => despachar({ tipo: "preset", valor })}>${txt}</button>`)}
      </div>
      <button type="button" class="v2-btn-filtros" onClick=${abrirCajon} aria-haspopup="dialog">
        Filtros${puestos.length ? html` <span class="v2-num" id="num-filtros">${puestos.length}</span>` : ""}
      </button>
      <div class="v2-puestos" aria-live="polite">
        ${puestos.map((f) => html`
          <span class="v2-puesto">${f.txt}
            <button type="button" aria-label=${"Quitar " + f.txt} onClick=${() => despachar(f.accion)}>✕</button>
          </span>`)}
      </div>
      <button type="button" class="v2-reiniciar" onClick=${() => despachar({ tipo: "reiniciar", lim })}>⟳ Reiniciar</button>
    </div>`;
}

/* ---------------- El cajón con el resto de los filtros ---------------- */

export function Cajon({ abierto, cerrar, estado, despachar, hoy, lim, catalogo, alElegirAfiliado }) {
  const cerrarRef = useRef(null);
  useEffect(() => {
    if (!abierto) return undefined;
    if (cerrarRef.current) cerrarRef.current.focus();
    const tecla = (e) => { if (e.key === "Escape") cerrar(); };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [abierto]);
  return html`
    <div class=${"v2-cajon-fondo" + (abierto ? " abierto" : "")} onClick=${cerrar}></div>
    <aside class=${"v2-cajon" + (abierto ? " abierto" : "")} role="dialog" aria-modal="true"
      aria-label="Filtros del panel" aria-hidden=${!abierto} inert=${!abierto}>
      <div class="v2-cajon-enc">
        <h2>Filtros</h2>
        <button type="button" class="v2-cerrar" ref=${cerrarRef} onClick=${cerrar} aria-label="Cerrar">✕</button>
      </div>
      <div class="v2-cajon-cuerpo">
        <section><span class="f-label">Calendario · pintá el rango</span>
          ${abierto && html`<${Calendario} desde=${estado.desde} hasta=${estado.hasta} hoy=${hoy}
            alElegir=${(desde, hasta) => despachar({ tipo: "rango", desde, hasta })} />`}
        </section>
        <section><span class="f-label">Formato de recibo</span>
          <div class="seg" role="group" aria-label="Formato de recibo">
            ${[["", "Todos"], ["viejo", "Anterior"], ["nuevo", "Ley 27.802"]].map(([v, txt]) => html`
              <button type="button" class=${estado.formato === v ? "act" : ""} aria-pressed=${estado.formato === v}
                onClick=${() => despachar({ tipo: "poner", campo: "formato", valor: v })}>${txt}</button>`)}
          </div>
        </section>
        <section><span class="f-label">Seccionales · múltiple</span>
          <${Pastillas} items=${catalogo.seccionales || []} elegidos=${estado.seccionales} campo="seccionales" despachar=${despachar} />
        </section>
        <section><span class="f-label">Empresas · selección múltiple</span>
          <${Pastillas} items=${catalogo.empresas || []} elegidos=${estado.empresas} campo="empresas" despachar=${despachar} />
        </section>
        ${lim.min !== null && html`<section><span class="f-label">Remuneración bruta (miles $)</span>
          <${RangoSalario} lim=${lim} salMin=${estado.salMin} salMax=${estado.salMax}
            alCambiar=${(min, max) => despachar({ tipo: "salario", min, max })} />
        </section>`}
        <section><span class="f-label">Afiliado</span>
          <${BuscadorAfiliado} alElegir=${alElegirAfiliado} />
        </section>
      </div>
      <div class="v2-cajon-pie"><button type="button" class="v2-listo" onClick=${cerrar}>Ver el panel</button></div>
    </aside>`;
}

/* Selección múltiple con "TODAS" explícito: la lista vacía ya significa
   todas, pero sin esa pastilla el estado de origen no se ve elegido. */
function Pastillas({ items, elegidos, campo, despachar }) {
  return html`<div class="multi-chips">
    <button type="button" class=${"m-chip" + (elegidos.length ? "" : " act")}
      onClick=${() => despachar({ tipo: "poner", campo, valor: [] })}>TODAS</button>
    ${items.map((it) => html`
      <button type="button" class=${"m-chip" + (elegidos.indexOf(it.id) >= 0 ? " act" : "")}
        aria-pressed=${elegidos.indexOf(it.id) >= 0}
        onClick=${() => despachar({ tipo: "alternar", campo, id: it.id })}>${it.nombre}</button>`)}
  </div>`;
}

/* El calendario pintable de la v1: un toque marca el día inicial (y ya
   filtra ese día), el segundo el final; si el segundo es anterior, se dan
   vuelta. Los días futuros no se pueden elegir. */
function Calendario({ desde, hasta, hoy, alElegir }) {
  const [vista, setVista] = useState(() => hasta.slice(0, 7) + "-01");
  const [eligiendo, setEligiendo] = useState(false);
  const [a, m] = vista.split("-").map(Number);
  const primero = new Date(a, m - 1, 1);
  const dow = (primero.getDay() + 6) % 7;
  const dias = [];
  for (let i = 0; i < 42; i++) dias.push(fISO(new Date(a, m - 1, 1 - dow + i)));
  const unSolo = desde === hasta;
  const mover = (n) => setVista(fISO(new Date(a, m - 1 + n, 1)));
  const tocar = (f) => {
    if (!eligiendo) { alElegir(f, f); setEligiendo(true); }
    else { alElegir(f < desde ? f : desde, f < desde ? desde : f); setEligiendo(false); }
  };
  return html`<div class="cal">
    <div class="cal-nav">
      <button type="button" onClick=${() => mover(-1)} aria-label="Mes anterior">‹</button>
      <b>${MESES[m - 1]} ${a}</b>
      <button type="button" onClick=${() => mover(1)} aria-label="Mes siguiente">›</button>
    </div>
    <div class="cal-grid">
      ${["L", "M", "M", "J", "V", "S", "D"].map((d) => html`<span class="cal-dow">${d}</span>`)}
      ${dias.map((f) => {
        const enRango = f >= desde && f <= hasta && !unSolo;
        let cls = "cal-dia";
        if (Number(f.slice(5, 7)) !== m) cls += " fuera";
        if (f === hoy) cls += " hoyd";
        if (enRango && f !== desde && f !== hasta) cls += " rango";
        if (f === desde) cls += " extremo " + (unSolo ? "solo" : "ini");
        if (f === hasta && !unSolo) cls += " extremo fin";
        return html`<button type="button" class=${cls} disabled=${f > hoy}
          onClick=${() => tocar(f)}>${Number(f.slice(8, 10))}</button>`;
      })}
    </div>
    <div class="cal-ayuda">${eligiendo
      ? html`Ahora tocá el día <b>final</b>`
      : html`Tocá el día <b>inicial</b> y luego el <b>final</b>`}</div>
  </div>`;
}

/* Dos manijas sobre la misma pista. Mientras se arrastra se mueve solo la
   pantalla; el filtro cambia al soltar, como en la v1. */
function RangoSalario({ lim, salMin, salMax, alCambiar }) {
  const [vivo, setVivo] = useState(null);
  const min = vivo ? vivo[0] : (salMin === null ? lim.min : salMin);
  const max = vivo ? vivo[1] : (salMax === null ? lim.max : salMax);
  const pct = (v) => (v - lim.min) / Math.max(1, lim.max - lim.min) * 100;
  const activo = min > lim.min || max < lim.max;
  const leer = (el) => {
    const otro = el.parentNode.querySelector(el.dataset.lado === "min" ? '[data-lado="max"]' : '[data-lado="min"]');
    const x = +el.value, y = +otro.value;
    return [Math.min(x, y), Math.max(x, y)];
  };
  return html`<div class="slider-wrap">
    <div class=${"slider-vals" + (activo ? " act" : "")}><span>${fmtN(min)}</span><span>${fmtN(max)}</span></div>
    <div class=${"rango" + (activo ? " act" : "")}>
      <div class="pista"></div>
      <div class="relleno" style=${{ left: pct(min) + "%", width: (pct(max) - pct(min)) + "%" }}></div>
      ${[["min", min, "mínima"], ["max", max, "máxima"]].map(([lado, valor, txt]) => html`
        <input type="range" data-lado=${lado} min=${lim.min} max=${lim.max} step="50" value=${valor}
          aria-label=${"Remuneración bruta " + txt}
          onInput=${(e) => setVivo(leer(e.target))}
          onChange=${(e) => { const [a, b] = leer(e.target); setVivo(null); alCambiar(a, b); }} />`)}
    </div>
  </div>`;
}

/* Buscar un afiliado por nombre o CUIL: desde dos letras, con una espera de
   250 ms y cancelando la búsqueda anterior (como la v1). El filtro viaja por
   id, nunca por CUIL. */
function BuscadorAfiliado({ alElegir }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState(null);
  const abort = useRef(null);
  useEffect(() => {
    const texto = q.trim();
    if (texto.length < 2) { setItems(null); return undefined; }
    const id = setTimeout(() => {
      if (abort.current) abort.current.abort();
      abort.current = new AbortController();
      fetch("/admin/dashboard/afiliados?q=" + encodeURIComponent(texto), { signal: abort.current.signal })
        .then((r) => (r.ok ? r.json() : { items: [] }))
        .then((d) => setItems(d.items))
        .catch(() => {});
    }, 250);
    return () => clearTimeout(id);
  }, [q]);
  const elegir = (it) => { alElegir(it); setQ(""); setItems(null); };
  return html`<div class="af-wrap">
    <input type="search" placeholder="Nombre o CUIL" autocomplete="off" aria-label="Buscar afiliado"
      value=${q} onInput=${(e) => setQ(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Escape") { e.stopPropagation(); setItems(null); } }} />
    ${items && html`<div class="af-lista">
      ${items.length ? items.map((it) => html`
        <button type="button" class="af-item" onClick=${() => elegir(it)}>${it.nombre}
          <small>${[it.cuil, it.seccional, it.empresa].filter(Boolean).join(" · ")}</small></button>`)
        : html`<div class="af-vacio">No encontré a nadie con ese nombre o CUIL.</div>`}
    </div>`}
  </div>`;
}
