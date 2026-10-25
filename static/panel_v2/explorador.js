/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md, bloque 5): el explorador de datos
   y el modal "Ver".

   Las mismas pestañas, columnas, textos y reglas que la v1
   (static/dashboard.js, `TABLAS` y el modal de detalle). Lo que cambia es la
   forma: acá no se arma HTML como texto (línea roja 5) — todo lo que viene
   del servidor lo escapa Preact al pintarlo.

   Privacidad: lo que se muestra es lo que manda el servidor. Un recibo que el
   trabajador no envió llega ya anonimizado (`dashboard.anonimizar_detalle`):
   acá no se decide nada sobre eso, solo se avisa en pantalla. */
import { cloneElement } from "preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { fmtN, fmtM, fFecha, fCorta, fCuil } from "panel/formato";
import { useCorrer } from "panel/kpis";

const FORMATO = { nuevo: "Ley 27.802", clasico: "Anterior" };
const TAGS_TRAMITE = { resuelto: ["ok", "Resuelto"], en_proceso: ["proc", "En proceso"], abierto: ["rev", "Abierto"] };

const ver = (abrir, det) => html`<button type="button" class="btn-ver" onClick=${() => abrir(det)}>Ver</button>`;

/* En el teléfono cada fila es una ficha COMPACTA de tres renglones (R4-03):
   arriba lo que se viene a leer (`f-tit`, y a la derecha `f-val`), abajo un
   renglón gris con el resto (`f-meta`, una celda que en escritorio no se
   ve) y el "Ver" estirado sobre toda la ficha, así se toca en cualquier
   parte. Las demás celdas quedan para la tabla de escritorio y para "Ver".
   Lo arma el CSS (panel.css); acá solo se marcan las celdas. */
const meta = (...partes) => html`<td class="f-meta">${partes.filter((x) => x !== null && x !== undefined && x !== "").join(" · ")}</td>`;
const diaCorto = (iso) => (iso ? fCorta(String(iso).slice(0, 10)) : "");

/* Las cinco tablas de la v1: encabezado, fila y el texto del total. */
export const TABLAS = {
  recibos: {
    sub: "Recibos con diferencias · ordenados por monto observado · identificados solo si el trabajador los envió",
    cols: ["Fecha", "Seccional", "Empresa", "Categoría", "Formato", "Bruto", "Dif. detectada", "Enviado", "Trabajador", "CUIL", ""],
    total: (n) => n + " recibos observados",
    fila: (r, abrir) => html`<tr class="ficha">
      <td>${fFecha(r.fecha)}</td><td>${r.seccional}</td><td class="f-tit">${r.empresa}</td><td>${r.categoria}</td>
      <td>${FORMATO[r.formato] || "—"}</td><td class="monto">${fmtM(r.bruto)}</td>
      <td class="monto f-val" style=${{ color: "var(--error)" }}>${fmtM(r.diferencia)}</td>
      <td>${r.enviado ? "✓ Sí" : "—"}</td><td>${r.trabajador_nombre || "Anónimo"}</td>
      <td class="monto">${fCuil(r.trabajador_cuil)}</td>
      <td class="f-ver">${ver(abrir, { tipo: "recibo", ruta: "detalle/recibo/" + r.id, previa: { procesado_en: r.fecha,
        enviado: r.enviado, estado: r.diferencia > 0 ? "con_diferencias" : "ok", trabajador_nombre: r.trabajador_nombre,
        trabajador_cuil: r.trabajador_cuil, empresa: r.empresa, categoria: r.categoria, formato: r.formato, bruto: r.bruto } })}</td>
      ${meta(diaCorto(r.fecha), r.seccional, r.trabajador_nombre || "Anónimo")}</tr>`,
  },
  tramites: {
    sub: "Detalle de trámites del período · respetando seccional y estado seleccionados",
    cols: ["N°", "Fecha inicio", "Seccional", "Tipo de trámite", "Estado", "Días", ""],
    total: (n) => n + " trámites",
    fila: (t, abrir) => {
      const tg = TAGS_TRAMITE[t.estado] || ["rev", t.estado];
      return html`<tr class="ficha">
        <td class="monto">${t.numero}</td><td>${fFecha(t.fecha_inicio)}</td><td>${t.seccional}</td><td class="f-tit">${t.tipo}</td>
        <td class="f-val"><span class=${"tag " + tg[0]}>${tg[1]}</span></td>
        <td class="monto">${t.dias === null ? "—" : t.dias + " d" + (t.sigue ? " y sigue" : "")}</td>
        <td class="f-ver">${ver(abrir, { tipo: "tramite", ruta: "detalle/tramite/" + t.id, previa: { numero_expediente: t.numero,
          tipo_titulo: t.tipo, estado_label: tg[1], seccional: t.seccional, creado: t.fecha_inicio } })}</td>
        ${meta(t.numero, diaCorto(t.fecha_inicio), t.seccional, t.dias === null ? null : t.dias + " d" + (t.sigue ? " y sigue" : ""))}</tr>`;
    },
  },
  consultas: {
    sub: "Consultas de los afiliados al asistente · el tema seleccionado en el gráfico filtra esta lista",
    cols: ["Fecha", "Seccional", "Tema consultado", "Resolución", ""],
    total: (n) => n + " consultas",
    fila: (c, abrir) => html`<tr class="ficha">
      <td>${fFecha(c.fecha)}</td><td>${c.seccional}</td><td class="f-tit">${c.tema}</td>
      <td class="f-val"><span class=${"tag " + (c.resuelta_por_bot ? "ok" : "rev")}>${c.resuelta_por_bot ? "Resuelta por el bot" : "Derivada"}</span></td>
      <td class="f-ver">${ver(abrir, { tipo: "consulta", ruta: "detalle/consulta/" + c.id, previa: { fecha: c.fecha,
        seccional: c.seccional, tema: c.tema, resuelta_por_bot: c.resuelta_por_bot } })}</td>
      ${meta(diaCorto(c.fecha), c.seccional)}</tr>`,
  },
  notificaciones: {
    sub: "Envíos diarios por seccional y tipo · el tipo seleccionado en el gráfico filtra esta lista",
    cols: ["Fecha", "Seccional", "Tipo", "Enviadas", "Leídas", "Sin leer", "Tasa de lectura", ""],
    total: (n) => n + " filas (día × seccional × tipo)",
    fila: (n, abrir) => html`<tr class="ficha">
      <td>${fFecha(n.fecha)}</td><td>${n.seccional}</td><td class="f-tit">${n.etiqueta}</td>
      <td class="monto">${fmtN(n.enviadas)}</td><td class="monto">${fmtN(n.leidas)}</td><td class="monto">${fmtN(n.sin_leer)}</td>
      <td class="f-val"><span class="barra-lectura"><i style=${{ width: n.tasa_lectura + "%" }}></i></span><span class="monto">${String(n.tasa_lectura).replace(".", ",")} %</span></td>
      <td class="f-ver">${ver(abrir, { tipo: "notif", dia: n.fecha, ruta: "detalle/notificaciones?dia=" + encodeURIComponent(n.fecha) +
        "&seccional_id=" + (n.seccional_id || 0) + "&tipo=" + encodeURIComponent(n.tipo) })}</td>
      ${meta(diaCorto(n.fecha), n.seccional, fmtN(n.leidas) + " de " + fmtN(n.enviadas) + " leídas")}</tr>`,
  },
  // Con afiliado elegido el servidor manda una fila por notificación (modo "afiliado").
  notificaciones_afiliado: {
    sub: "Notificaciones que recibió el afiliado elegido · una por fila, con leída o sin leer",
    cols: ["Fecha", "Tipo", "Remitente", "Texto", "Lectura"],
    total: (n) => n + " notificaciones",
    fila: (n) => html`<tr>
      <td>${fFecha(n.fecha)}</td><td>${n.etiqueta}</td><td>${n.remitente || "—"}</td>
      <td style=${{ whiteSpace: "normal", maxWidth: "420px" }} title=${n.texto}>${n.texto.length > 120 ? n.texto.slice(0, 117) + "…" : n.texto}</td>
      <td><span class=${"tag " + (n.leida ? "ok" : "rev")}>${n.leida ? "Leída el " + fFecha(n.leida_en) : "Sin leer"}</span></td></tr>`,
  },
};

const NOMBRE_TAB = { recibos: "Recibos", tramites: "Trámites", consultas: "Consultas", notificaciones: "Notificaciones" };
// En el teléfono, el rótulo corto (R4-03): "Notificacio" cortada no decía que había más.
const CORTO_TAB = { consultas: "Consultas", notificaciones: "Notif." };
const rotuloTab = (t) => (CORTO_TAB[t] && CORTO_TAB[t] !== NOMBRE_TAB[t]
  ? html`<span class="t-largo">${NOMBRE_TAB[t]}</span><span class="t-corto">${CORTO_TAB[t]}</span>`
  : NOMBRE_TAB[t]);

function subDe(def, estado) {
  if (!estado.afiliado) return def.sub;
  if (estado.tab === "recibos") return "Todos los recibos que el afiliado envió al sindicato · los que verificó en privado no se muestran ni se cuentan";
  if (estado.tab === "consultas") return "Las consultas al bot son anónimas: el filtro por afiliado no aplica acá";
  return def.sub;
}

const SIN_FILAS = [];
// La clase que trae la fila (la ficha del teléfono) más la de su entrada.
const con = (tr, clase) => [tr.props.class, clase].filter(Boolean).join(" ");

/* El total de una pestaña corre hasta su número, como los indicadores. */
function Cuenta({ valor }) {
  const v = useCorrer(valor);
  return v === null || v === undefined ? "0" : fmtN(Math.round(v));
}

/* La marca de la pestaña elegida se DESLIZA de una pestaña a otra (D5): es
   una pastilla aparte, debajo de los botones, que se mide contra el botón
   activo. La primera vez se pone en su lugar sin moverse. */
function useIndicador(caja, deps) {
  const [ind, setInd] = useState(null);
  useLayoutEffect(() => {
    const medir = () => {
      const b = caja.current && caja.current.querySelector(".tab-d.act");
      if (!b) return;
      setInd((v) => ({ x: b.offsetLeft, w: b.offsetWidth, listo: v !== null }));
    };
    medir();
    window.addEventListener("resize", medir);
    return () => window.removeEventListener("resize", medir);
  }, deps);
  return ind;
}

/* `datos`: {items, total, modo} con TODAS las filas pedidas hasta ahora (la
   página 1 más los "Ver más"). `contadores`: el total de cada pestaña. */
export function Explorador({ datos, estado, despachar, tabs, contadores, abrirDetalle }) {
  let def = TABLAS[estado.tab] || TABLAS.recibos;
  if (estado.tab === "notificaciones" && datos && datos.modo === "afiliado") def = TABLAS.notificaciones_afiliado;
  const items = datos ? datos.items : SIN_FILAS;
  const total = datos ? datos.total : 0;
  const pestanas = useRef(null);
  const cuerpo = useRef(null);
  const ind = useIndicador(pestanas, [estado.tab, tabs.map((t) => contadores[t]).join(",")]);
  /* Qué filas son nuevas. "Ver más" suma filas a las que ya estaban (las
     primeras son LOS MISMOS objetos), y esas entran escalonadas. Cualquier
     otro cambio reemplaza la tabla, que se renueva con un fundido corto: un
     filtro se cambia muchas veces seguidas y no tiene que hacerse esperar. */
  const memo = useRef({ items: null, desde: -1, version: 0 });
  if (items !== memo.current.items) {
    const ant = memo.current.items || SIN_FILAS;
    const suma = ant.length > 0 && items.length > ant.length && items[0] === ant[0];
    memo.current = { items, desde: suma ? ant.length : -1, version: memo.current.version + (suma ? 0 : 1) };
  }
  const { desde, version } = memo.current;
  /* La tabla se ARMA fila por fila cada vez que se renueva (pestaña, filtros)
     y las que suma "Ver más" entran igual, a continuación. */
  const fila = (it, i) => {
    const tr = def.fila(it, abrirDetalle);
    if (desde >= 0) {
      return i >= desde
        ? cloneElement(tr, { class: con(tr, "v2-fila-nueva"), style: { animationDelay: Math.min((i - desde) * 45, 450) + "ms" } })
        : tr;
    }
    return cloneElement(tr, { class: con(tr, "v2-fila-arma"), style: { animationDelay: Math.min(i * 45, 450) + "ms" } });
  };
  /* En el teléfono cada fila es una ficha (G7-04): cada celda lleva el
     nombre de su columna para dibujarlo encima del valor. Se pone sobre el
     DOM ya pintado (un atributo, nunca HTML): las filas las arman las cinco
     tablas de arriba y así ninguna tiene que repetir sus encabezados. */
  useLayoutEffect(() => {
    if (!cuerpo.current) return;
    cuerpo.current.querySelectorAll("tr").forEach((tr) => {
      Array.prototype.forEach.call(tr.children, (td, i) => {
        if (def.cols[i]) td.setAttribute("data-et", def.cols[i]); else td.removeAttribute("data-et");
      });
    });
  });
  return html`
    <div class="sub" id="tabla-sub">${datos ? subDe(def, estado) : "El detalle responde a todos los filtros. Al tocar un gráfico, la pestaña correspondiente se abre sola."}</div>
    <div class="tabs-datos v2-tabs" id="tabs-datos" role="tablist" ref=${pestanas}>
      ${ind && html`<span class=${"v2-indicador" + (ind.listo ? " listo" : "")} aria-hidden="true"
        style=${{ translate: ind.x + "px 0", width: ind.w + "px" }}></span>`}
      ${tabs.map((t) => html`
        <button type="button" role="tab" aria-selected=${estado.tab === t} class=${"tab-d" + (estado.tab === t ? " act" : "")} data-t=${t}
          onClick=${() => despachar({ tipo: "tab", valor: t })}>${rotuloTab(t)}
          <span class="cnt" id=${"cnt-" + t}><${Cuenta} valor=${contadores[t]} /></span></button>`)}
    </div>
    ${items.length || !datos ? html`<div class="tabla-scroll">
      <table class="tabla-exp">
        <thead id="tabla-head"><tr>${def.cols.map((c) => html`<th>${c}</th>`)}</tr></thead>
        <tbody id="tabla-body" key=${version} ref=${cuerpo}>${items.map(fila)}</tbody>
      </table>
    </div>` : html`<p class="vacio-exp" id="tabla-vacia">Sin registros para los filtros actuales. Probá ampliar el período o quitar filtros.</p>`}
    <div class="pie-tabla">
      <span id="tabla-total">${datos ? "Mostrando " + fmtN(items.length) + " de " + fmtN(total) + " · " + def.total(fmtN(total)) : ""}</span>
      <button type="button" id="ver-mas" style=${{ visibility: items.length < total ? "visible" : "hidden" }}
        onClick=${() => despachar({ tipo: "verMas" })}>Ver más</button>
    </div>`;
}

/* ---------------- El modal "Ver" ----------------
   El fondo es `.overlay-det` y la caja `.modal-det`, las mismas clases que la
   v1: así `modales.js` la deja arrastrar en escritorio y la vuelve a su
   lugar al cerrar. Anima `opacity`, `scale` y `translate`, nunca
   `transform`, que es lo que usa el arrastre.

   Abre EN EL MOMENTO del clic y se ARMA a la vista: con lo que la fila ya
   sabe (`previa`: título, fecha, empresa...) arranca a construirse pieza por
   pieza mientras el resto viaja, y lo que llega del servidor se suma debajo,
   también en cascada, mientras la caja crece de a poco hasta su alto (sin
   saltar). Nada de una pantalla gris de espera: se ve la ficha formándose.
   Entra en `--mov-lento` y sale más rápido, en `--mov-medio`. */
export function Detalle({ pedido, cerrar }) {
  const [contenido, setContenido] = useState(null);   // {para, ok, datos} cuando llega
  const cerrarRef = useRef(null);
  // Al cerrar, el contenido sigue a la vista mientras el modal se desvanece.
  const ultimo = useRef(null);
  if (pedido) ultimo.current = pedido;
  useEffect(() => {
    if (!pedido) return undefined;
    let vivo = true;
    fetch("/admin/dashboard/" + pedido.ruta)
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d) => { if (vivo) setContenido({ para: pedido, ok: true, datos: d }); })
      .catch(() => { if (vivo) setContenido({ para: pedido, ok: false }); });
    return () => { vivo = false; };
  }, [pedido]);
  const abierto = !!pedido;
  // Solo se muestra lo que llegó para ESTE pedido: el de la vez anterior no.
  const listo = contenido && contenido.para === ultimo.current ? contenido : null;
  // Cada pedido nuevo arma su ficha desde cero (y su cascada desde la primera pieza).
  const vez = useRef({ pedido: null, n: 0 });
  if (pedido && pedido !== vez.current.pedido) vez.current = { pedido, n: vez.current.n + 1 };
  const interior = useRef(null);
  const [alto, setAlto] = useState(null);
  /* La cascada: cada pieza que aparece (las de la fila al abrir, las del
     servidor al llegar) entra un poco después de la anterior. Se marca a
     mano porque son hijos de componentes distintos. */
  useLayoutEffect(() => {
    const el = interior.current;
    if (!el) return;
    let k = 0;
    Array.from(el.children).forEach((n) => {
      if (n.dataset.armado) return;
      n.dataset.armado = "1";
      n.style.animationDelay = Math.min(k++ * 45, 600) + "ms";
    });
  });
  // La caja crece de a poco hasta el alto de lo que tiene adentro.
  useEffect(() => {
    const el = interior.current;
    if (!el || !window.ResizeObserver) return undefined;
    const ro = new ResizeObserver(() => setAlto(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [vez.current.n]);
  useEffect(() => {
    if (!abierto) return undefined;
    if (cerrarRef.current) cerrarRef.current.focus();
    const tecla = (e) => { if (e.key === "Escape") cerrar(); };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [abierto]);
  let cuerpo = null;
  if (listo && !listo.ok) {
    cuerpo = html`<h3 key="error">No se pudo cargar el detalle</h3><div class="det-sub" key="error-sub">Probá de nuevo en un momento.</div>`;
  } else if (ultimo.current) {
    const p = ultimo.current, d = listo ? listo.datos : (p.previa || {});
    cuerpo = html`${{ recibo: () => html`<${DetRecibo} d=${d} />`, tramite: () => html`<${DetTramite} d=${d} />`,
      consulta: () => html`<${DetConsulta} d=${d} />`, notif: () => html`<${DetNotifs} d=${d} dia=${p.dia} />` }[p.tipo]()}
      ${!listo && html`<div class="v2-det-cargando" key="cargando" aria-label="Cargando el detalle"><span>Trayendo el detalle</span><i></i></div>`}`;
  }
  return html`<div class=${"overlay-det v2-anim" + (abierto ? " abierto" : "")} id="overlay-det"
      onClick=${(e) => { if (e.target === e.currentTarget) cerrar(); }}>
    <div class="modal-det" role="dialog" aria-modal="true" aria-hidden=${!abierto}>
      <button type="button" class="modal-det-cerrar" id="det-cerrar" ref=${cerrarRef} aria-label="Cerrar" onClick=${cerrar}>✕</button>
      <div id="det-contenido" class="v2-alto" style=${alto === null ? {} : { height: alto + "px" }}>
        <div class="v2-construye" key=${vez.current.n} ref=${interior}>${cuerpo}</div></div>
    </div>
  </div>`;
}

const Fila = ({ k, children }) => html`<div class="det-fila"><span class="k">${k}</span><span class="v">${children}</span></div>`;

function DetRecibo({ d }) {
  const lineas = (d.recibo && d.recibo.lineas) || [];
  const tot = (d.resultado && d.resultado.totales) || null;
  const disc = (d.resultado && d.resultado.discrepancias) || [];
  const alertas = (d.resultado && d.resultado.alertas) || [];
  return html`
    <h3 key="titulo">Recibo verificado</h3>
    <div class="det-sub" key="sub">${fFecha(d.procesado_en)}${d.periodo ? " · período " + d.periodo : ""}</div>
    ${!d.enviado && html`<div class="det-anonimo" key="anonimo">Recibo anonimizado: el trabajador no lo envió al sindicato, así que no se muestra ningún dato que lo identifique.</div>`}
    <${Fila} key="resultado" k="Resultado"><span class=${"tag " + (d.estado === "ok" ? "ok" : "dif")}>${d.estado === "ok" ? "Sin diferencias" : "Con diferencias"}</span><//>
    ${d.trabajador_nombre && html`<${Fila} key="trabajador" k="Trabajador">${d.trabajador_nombre} · CUIL ${fCuil(d.trabajador_cuil)}<//>`}
    <${Fila} key="empresa" k="Empresa">${d.empresa}<//>
    <${Fila} key="categoria" k="Categoría">${d.categoria}<//>
    <${Fila} key="formato" k="Formato">${d.formato === "nuevo" ? "Ley 27.802 (Anexo III)" : "Anterior"}<//>
    <${Fila} key="bruto" k="Remuneración bruta"><span class="monto">${fmtM(d.bruto)}</span><//>
    ${lineas.length > 0 && html`<div class="det-sec" key="conceptos">Conceptos del recibo (${lineas.length})</div>
      ${lineas.map((l, i) => {
        const imp = typeof l.importe === "number" ? l.importe : null;
        return html`<div class="det-linea" key=${"linea-" + i}><span>${l.descripcion || l.codigo || "—"}</span>
          <span class=${"imp" + (imp !== null && imp < 0 ? " neg" : "")}>${imp === null ? "—" : fmtM(imp)}</span></div>`;
      })}`}
    ${tot && html`<div class="det-sec" key="totales">Totales</div>
      <${Fila} key="ingresos" k="Ingresos"><span class="monto">${fmtM(tot.ingresos)}</span><//>
      <${Fila} key="descuentos" k="Descuentos"><span class="monto">${fmtM(tot.descuentos)}</span><//>
      ${tot.reintegros ? html`<${Fila} key="reintegros" k="Reintegros"><span class="monto">${fmtM(tot.reintegros)}</span><//>` : ""}
      <${Fila} key="neto" k="Neto"><span class="monto">${fmtM(tot.neto)}</span><//>`}
    ${disc.length > 0 && html`<div class="det-sec" key="disc" style=${{ color: "var(--error)" }}>Discrepancias detectadas (${disc.length})</div>
      <ul class="det-lista" key="disc-lista">${disc.map((x) => html`<li>${x.detalle}</li>`)}</ul>`}
    ${alertas.length > 0 && html`<div class="det-sec" key="alertas" style=${{ color: "var(--aviso)" }}>Alertas</div>
      <ul class="det-lista" key="alertas-lista">${alertas.map((x) => html`<li>${x.detalle}</li>`)}</ul>`}`;
}

const ESCUDO = html`<path d="M12 3l7 3v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6z"/><circle cx="12" cy="10" r="2.3"/>`;
const PERSONA = html`<circle cx="12" cy="8" r="3.4"/><path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7"/>`;

function DetTramite({ d }) {
  const notas = d.notas || [];
  return html`
    <h3 key="titulo">${d.numero_expediente}</h3>
    <div class="det-sub" key="sub">${d.tipo_titulo}</div>
    <${Fila} key="estado" k="Estado">${d.estado_label}<//>
    ${d.cuil !== undefined && html`<${Fila} key="trabajador" k="Trabajador">${d.trabajador_nombre || "—"} · CUIL ${fCuil(d.cuil)}<//>`}
    <${Fila} key="seccional" k="Seccional">${d.seccional}<//>
    <${Fila} key="iniciado" k="Iniciado">${fFecha(d.creado)}<//>
    ${d.actualizado !== undefined && html`<${Fila} key="actualizado" k="Última actualización">${fFecha(d.actualizado)}<//>`}
    ${(d.respuestas || []).length > 0 && html`<div class="det-sec" key="formulario">Formulario presentado</div>
      ${d.respuestas.map((r, i) => html`<${Fila} key=${"resp-" + i} k=${r.etiqueta}>${r.valor_texto || (r.tiene_archivo ? "📎 " + (r.archivo_nombre || "archivo") : "—")}<//>`)}`}
    ${d.notas !== undefined && html`<div class="det-sec" key="conversacion">Conversación${notas.length ? " (" + notas.length + ")" : ""}</div>
    ${!notas.length ? html`<div class="tram-chat-vacio" key="chat">Todavía no hay mensajes en este trámite.</div>` : html`
      <div class="tram-chat" key="chat">${notas.map((n) => {
        const propio = n.autor === "admin";
        return html`<div class=${"tram-chat-fila " + (propio ? "propio" : "ajeno")}>
          <span class="tram-chat-avatar-fallback"><svg viewBox="0 0 24 24">${propio ? ESCUDO : PERSONA}</svg></span>
          <div class="tram-chat-burbuja">
            <div class="tram-chat-remitente">${propio ? "Sindicato" : "Afiliado"}</div>
            <div class="tram-chat-texto">${n.texto}</div>
            <div class="tram-chat-meta">
              ${n.tiene_adjunto && html`<span>📎 ${n.adjunto_nombre || "adjunto"}</span>`}
              <span>${fFecha(n.creado)} ${(n.creado || "").slice(11, 16)}</span>
            </div>
          </div></div>`;
      })}</div>`}`}
    ${(d.log || []).length > 0 && html`<div class="det-sec" key="historial">Historial</div>
      <ul class="det-lista" key="historial-lista">${d.log.map((l) => html`<li>${fFecha(l.creado)} — ${l.detalle}</li>`)}</ul>`}`;
}

function DetConsulta({ d }) {
  return html`
    <h3 key="titulo">Consulta al asistente</h3>
    <div class="det-sub" key="sub">${fFecha(d.fecha)} · ${d.seccional}</div>
    <${Fila} key="tema" k="Tema">${d.tema}<//>
    <${Fila} key="resolucion" k="Resolución"><span class=${"tag " + (d.resuelta_por_bot ? "ok" : "rev")}>${d.resuelta_por_bot ? "Resuelta por el bot" : "Derivada"}</span><//>
    ${"pregunta" in d && html`<div class="det-sec" key="pregunta">Pregunta</div><div key="pregunta-texto" style=${{ fontSize: "13px" }}>${d.pregunta || "—"}</div>`}`;
}

function DetNotifs({ d, dia }) {
  const lista = d.notificaciones || [];
  return html`
    <h3 key="titulo">Notificaciones del ${fFecha(dia)}</h3>
    ${d.notificaciones !== undefined && html`<div class="det-sub" key="sub">${lista.length} envío${lista.length === 1 ? "" : "s"} en esta fila del explorador</div>
    ${!lista.length ? html`<div class="det-sub" key="vacio">Sin notificaciones.</div>` : lista.map((n) => html`<${Envio} key=${"envio-" + n.id} n=${n} />`)}`}`;
}

/* Un envío, con sus destinatarios a pedido: el primer toque los pide, los
   siguientes solo los muestran u ocultan (como la v1). */
function Envio({ n }) {
  const [dest, setDest] = useState(null);       // null | "cargando" | {items...} | "error"
  const [visible, setVisible] = useState(true);
  const pedir = () => {
    if (dest && dest !== "error" && dest !== "cargando") { setVisible(!visible); return; }
    setDest("cargando");
    fetch("/admin/dashboard/detalle/notificacion/" + n.id + "/destinatarios")
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d) => { setDest(d); setVisible(true); })
      .catch(() => setDest("error"));
  };
  return html`<div class="det-nota admin" style=${{ maxWidth: "100%", marginLeft: 0 }}>
    <div class="quien">${n.remitente || "—"} · ${n.etiqueta} · ${fFecha(n.enviado_en)}</div>
    <div class="quien" style=${{ textTransform: "none" }}>Destino: ${n.destino} · ${fmtN(n.total_leidas)}/${fmtN(n.total_enviadas)} leídas en total${n.total_enviadas !== n.enviadas ? " (" + fmtN(n.leidas) + "/" + fmtN(n.enviadas) + " en esta seccional)" : ""}</div>
    <div style=${{ margin: "4px 0 6px" }}>${n.texto}</div>
    ${n.tiene_adjunto && html`<div class="quien" style=${{ textTransform: "none" }}>📎 ${n.adjunto_nombre || "adjunto"}</div>`}
    <button type="button" class="btn-ver" disabled=${dest === "cargando"} onClick=${pedir}>Destinatarios (${fmtN(n.total_enviadas)})</button>
    <div class="det-destinatarios" style=${{ display: visible ? "block" : "none" }}>
      ${dest === "error" && html`<div class="det-sub">No se pudo cargar el listado.</div>`}
      ${dest && typeof dest === "object" && html`
        ${dest.items.length ? dest.items.map((p) => html`<div class="det-linea">
          <span>${p.nombre} <span style=${{ color: "var(--gris)" }}>· ${fCuil(p.cuil)} · ${p.seccional}</span></span>
          <span class="imp" style=${{ color: p.leida_en ? "var(--ok)" : "var(--gris)" }}>${p.leida_en ? "✓ Leída " + fFecha(p.leida_en) : "Sin leer"}</span></div>`)
          : html`<div class="det-sub">Sin destinatarios.</div>`}
        ${dest.recortado && html`<div class="det-sub" style=${{ marginTop: "6px" }}>Mostrando ${dest.items.length} de ${fmtN(dest.total)} destinatarios.</div>`}`}
    </div>
  </div>`;
}
