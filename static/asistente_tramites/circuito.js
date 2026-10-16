/* Asistente de trámites: el diagrama de flujo por actor (BPMN simplificado).

   Dibuja lo que manda el servidor (`resultado.circuito`: carriles, nodos,
   flujos y columnas) como un SVG: un carril por actor, inicio, acción,
   decisión con Sí y No, fin, y flecha punteada con un punto para lo que pasa
   fuera de Colm3na. Acá no se decide nada del circuito: solo se ubica. */
import { html } from "asistente/html";

const LX = 150, CW = 172, LH = 124, TW = 140, TH = 72, GR = 22, ER = 15;

function partir(texto, max) {
  const lineas = [""];
  String(texto || "").split(" ").forEach((p) => {
    if ((lineas[lineas.length - 1] + " " + p).trim().length > max) lineas.push(p);
    else lineas[lineas.length - 1] = (lineas[lineas.length - 1] + " " + p).trim();
  });
  return lineas.slice(0, 3);
}

export function Diagrama({ circuito, estados }) {
  const { carriles: L, nodos: N, flujos: F, cols } = circuito;
  const W = LX + cols * CW + 12, H = L.length * LH;
  const fila = Object.fromEntries(L.map((l, i) => [l.k, i]));
  const fuera = Object.fromEntries(L.map((l) => [l.k, !l.colm3na]));
  const G = {};
  N.forEach((n) => {
    const cx = LX + n.col * CW + CW / 2, cy = fila[n.carril] * LH + LH / 2;
    const hw = n.tipo === "tarea" ? TW / 2 : n.tipo === "gate" ? GR : ER;
    const hh = n.tipo === "tarea" ? TH / 2 : n.tipo === "gate" ? GR : ER;
    G[n.id] = { n, cx, cy, l: cx - hw, r: cx + hw, t: cy - hh, b: cy + hh };
  });
  const carriles = L.map((l, i) => {
    const y = i * LH, lin = partir(l.nombre, 15);
    return html`<g key=${l.k}>
      <rect class=${i % 2 ? "carril-alt" : "carril-fondo"} x="0" y=${y} width=${W} height=${LH} />
      <rect class="carril-cab" x="0" y=${y} width=${LX - 10} height=${LH} />
      ${lin.map((t, j) => html`<text class="carril-tx" x="12" y=${y + LH / 2 - 6 - (lin.length - 1) * 8 + j * 16}>${t}</text>`)}
      <text class=${"carril-sub" + (l.colm3na ? "" : " fuera")} x="12" y=${y + LH / 2 + 12 + (lin.length - 1) * 8}>${l.sub}</text>
      ${i ? html`<line class="div" x1="0" x2=${W} y1=${y} y2=${y} />` : null}
    </g>`;
  });
  const flechas = F.map((f, i) => {
    const a = G[f.de], b = G[f.a];
    if (!a || !b) return null;
    let d, tx, ty, anc = "middle";
    if (f.tipo === "vuelta") { d = `M${a.l},${a.cy} H${b.cx} V${b.cy > a.cy ? b.t : b.b}`; }
    else if (a.cy === b.cy && b.cx > a.cx) { d = `M${a.r},${a.cy} H${b.l}`; tx = (a.r + b.l) / 2; ty = a.cy - 7; }
    else if (a.cx === b.cx) { const up = b.cy < a.cy; d = `M${a.cx},${up ? a.t : a.b} V${up ? b.b : b.t}`; tx = a.cx + 7; ty = (a.cy + b.cy) / 2 + 4; anc = "start"; }
    else if (b.cx > a.cx) { const mx = Math.round((a.r + b.l) / 2); d = `M${a.r},${a.cy} H${mx} V${b.cy} H${b.l}`; tx = mx + 6; ty = (a.cy + b.cy) / 2 + 4; anc = "start"; }
    else { d = `M${a.cx},${b.cy > a.cy ? a.b : a.t} V${b.cy} H${b.r}`; tx = a.cx + 7; ty = (a.cy + b.cy) / 2; anc = "start"; }
    const msg = f.tipo === "msg";
    return html`<g key=${i}>
      <path class=${"flecha" + (msg ? " msg" : "")} d=${d} marker-end=${msg ? "url(#flm)" : "url(#fl)"} marker-start=${msg ? "url(#om)" : null} />
      ${f.etiqueta ? partir(f.etiqueta, 22).map((t, j) => html`<text class="flecha-tx" x=${tx} y=${ty + j * 13} text-anchor=${anc}>${t}</text>`) : null}
    </g>`;
  });
  const nodos = N.map((n, i) => {
    const g = G[n.id];
    if (n.tipo === "tarea") {
      const l = partir(n.texto, 19);
      const y0 = g.cy + (n.estado ? 12 : 5) - (l.length - 1) * 8;
      return html`<g key=${n.id} style=${`--i:${i}`}>
        <rect class=${"nodo" + (fuera[n.carril] ? " ext" : "") + (n.id === "cierra" ? " cierra" : "")} x=${g.l} y=${g.t} width=${TW} height=${TH} rx="10" style=${`--i:${i}`} />
        ${n.estado ? html`<text class="nodo-est" x=${g.cx} y=${g.t + 14} text-anchor="middle">${estados[n.estado] || n.estado}</text>` : null}
        ${l.map((t, j) => html`<text class="nodo-tx" x=${g.cx} y=${y0 + j * 16} text-anchor="middle">${t}</text>`)}
      </g>`;
    }
    if (n.tipo === "gate") {
      return html`<g key=${n.id}>
        <polygon class="nodo gate" points=${`${g.cx},${g.t} ${g.r},${g.cy} ${g.cx},${g.b} ${g.l},${g.cy}`} style=${`--i:${i}`} />
        <text class="gate-x" x=${g.cx} y=${g.cy + 6} text-anchor="middle">×</text>
        <text class="nodo-tx" x=${g.cx - 10} y=${g.t - 4} text-anchor="end">${n.texto}</text>
      </g>`;
    }
    return html`<g key=${n.id}>
      <circle class=${"evento " + n.tipo} cx=${g.cx} cy=${g.cy} r=${ER} />
      ${partir(n.texto, 16).map((t, j) => html`<text class="evento-tx" x=${g.cx} y=${g.b + 16 + j * 14} text-anchor="middle">${t}</text>`)}
    </g>`;
  });
  return html`<svg xmlns="http://www.w3.org/2000/svg" width=${W} height=${H} viewBox=${`0 0 ${W} ${H}`} role="img" aria-label="Diagrama de flujo del trámite por actor">
    <defs>
      <marker id="fl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path class="punta" d="M0,0 L10,5 L0,10 z" /></marker>
      <marker id="flm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path class="punta-m" d="M1,1 L9,5 L1,9 z" /></marker>
      <marker id="om" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="7" markerHeight="7"><circle class="punta-m" cx="5" cy="5" r="3.5" /></marker>
    </defs>
    ${carriles}
    <line class="div" x1=${LX - 10} x2=${LX - 10} y1="0" y2=${H} />
    ${flechas}
    ${nodos}
  </svg>`;
}

export function Leyenda() {
  return html`<div class="leyenda" aria-label="Referencias del diagrama">
    <span><svg width="22" height="22" viewBox="0 0 22 22"><circle class="evento inicio" cx="11" cy="11" r="8" /></svg>Inicio</span>
    <span><svg width="30" height="20" viewBox="0 0 30 20"><rect class="nodo" x="1" y="2" width="28" height="16" rx="4" /></svg>Acción en Colm3na</span>
    <span><svg width="30" height="20" viewBox="0 0 30 20"><rect class="nodo ext" x="1" y="2" width="28" height="16" rx="4" /></svg>Acción fuera de Colm3na</span>
    <span><svg width="22" height="22" viewBox="0 0 22 22"><polygon class="nodo gate" points="11,2 20,11 11,20 2,11" /></svg>Decisión</span>
    <span><svg width="22" height="22" viewBox="0 0 22 22"><circle class="evento fin" cx="11" cy="11" r="8" /></svg>Fin</span>
    <span><svg width="34" height="12" viewBox="0 0 34 12"><path class="flecha" d="M1,6 H30" marker-end="url(#fl)" /></svg>Sigue el flujo</span>
    <span><svg width="34" height="12" viewBox="0 0 34 12"><path class="flecha msg" d="M4,6 H30" /></svg>Mensaje o dato fuera de Colm3na</span>
  </div>`;
}
