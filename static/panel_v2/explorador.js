/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md, bloque 5): el explorador de datos
   y el modal "Ver".

   Las mismas pestañas, columnas, textos y reglas que la v1
   (static/dashboard.js, `TABLAS` y el modal de detalle). Lo que cambia es la
   forma: acá no se arma HTML como texto (línea roja 5) — todo lo que viene
   del servidor lo escapa Preact al pintarlo.

   Privacidad: lo que se muestra es lo que manda el servidor. Un recibo que el
   trabajador no envió llega ya anonimizado (`dashboard.anonimizar_detalle`):
   acá no se decide nada sobre eso, solo se avisa en pantalla. */
import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { fmtN, fmtM, fFecha } from "panel/formato";

const FORMATO = { nuevo: "Ley 27.802", clasico: "Anterior" };
const TAGS_TRAMITE = { resuelto: ["ok", "Resuelto"], en_proceso: ["proc", "En proceso"], abierto: ["rev", "Abierto"] };

const ver = (abrir, det) => html`<button type="button" class="btn-ver" onClick=${() => abrir(det)}>Ver</button>`;

/* Las cinco tablas de la v1: encabezado, fila y el texto del total. */
export const TABLAS = {
  recibos: {
    sub: "Recibos con diferencias · ordenados por monto observado · identificados solo si el trabajador los envió",
    cols: ["Fecha", "Seccional", "Empresa", "Categoría", "Formato", "Bruto", "Dif. detectada", "Enviado", "Trabajador", "CUIL", ""],
    total: (n) => n + " recibos observados",
    fila: (r, abrir) => html`<tr>
      <td>${fFecha(r.fecha)}</td><td>${r.seccional}</td><td>${r.empresa}</td><td>${r.categoria}</td>
      <td>${FORMATO[r.formato] || "—"}</td><td class="monto">${fmtM(r.bruto)}</td>
      <td class="monto" style=${{ color: "var(--error)" }}>${fmtM(r.diferencia)}</td>
      <td>${r.enviado ? "✓ Sí" : "—"}</td><td>${r.trabajador_nombre || "Anónimo"}</td>
      <td class="monto">${r.trabajador_cuil || "—"}</td>
      <td>${ver(abrir, { tipo: "recibo", ruta: "detalle/recibo/" + r.id })}</td></tr>`,
  },
  tramites: {
    sub: "Detalle de trámites del período · respetando seccional y estado seleccionados",
    cols: ["N°", "Fecha inicio", "Seccional", "Tipo de trámite", "Estado", "Días", ""],
    total: (n) => n + " trámites",
    fila: (t, abrir) => {
      const tg = TAGS_TRAMITE[t.estado] || ["rev", t.estado];
      return html`<tr>
        <td class="monto">${t.numero}</td><td>${fFecha(t.fecha_inicio)}</td><td>${t.seccional}</td><td>${t.tipo}</td>
        <td><span class=${"tag " + tg[0]}>${tg[1]}</span></td>
        <td class="monto">${t.dias === null ? "—" : t.dias + " d" + (t.sigue ? " y sigue" : "")}</td>
        <td>${ver(abrir, { tipo: "tramite", ruta: "detalle/tramite/" + t.id })}</td></tr>`;
    },
  },
  consultas: {
    sub: "Consultas de los afiliados al asistente · el tema seleccionado en el gráfico filtra esta lista",
    cols: ["Fecha", "Seccional", "Tema consultado", "Resolución", ""],
    total: (n) => n + " consultas",
    fila: (c, abrir) => html`<tr>
      <td>${fFecha(c.fecha)}</td><td>${c.seccional}</td><td>${c.tema}</td>
      <td><span class=${"tag " + (c.resuelta_por_bot ? "ok" : "rev")}>${c.resuelta_por_bot ? "Resuelta por el bot" : "Derivada"}</span></td>
      <td>${ver(abrir, { tipo: "consulta", ruta: "detalle/consulta/" + c.id })}</td></tr>`,
  },
  notificaciones: {
    sub: "Envíos diarios por seccional y tipo · el tipo seleccionado en el gráfico filtra esta lista",
    cols: ["Fecha", "Seccional", "Tipo", "Enviadas", "Leídas", "Sin leer", "Tasa de lectura", ""],
    total: (n) => n + " filas (día × seccional × tipo)",
    fila: (n, abrir) => html`<tr>
      <td>${fFecha(n.fecha)}</td><td>${n.seccional}</td><td>${n.etiqueta}</td>
      <td class="monto">${fmtN(n.enviadas)}</td><td class="monto">${fmtN(n.leidas)}</td><td class="monto">${fmtN(n.sin_leer)}</td>
      <td><span class="barra-lectura"><i style=${{ width: n.tasa_lectura + "%" }}></i></span><span class="monto">${n.tasa_lectura} %</span></td>
      <td>${ver(abrir, { tipo: "notif", dia: n.fecha, ruta: "detalle/notificaciones?dia=" + encodeURIComponent(n.fecha) +
        "&seccional_id=" + (n.seccional_id || 0) + "&tipo=" + encodeURIComponent(n.tipo) })}</td></tr>`,
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

function subDe(def, estado) {
  if (!estado.afiliado) return def.sub;
  if (estado.tab === "recibos") return "Todos los recibos que el afiliado envió al sindicato · los que verificó en privado no se muestran ni se cuentan";
  if (estado.tab === "consultas") return "Las consultas al bot son anónimas: el filtro por afiliado no aplica acá";
  return def.sub;
}

/* `datos`: {items, total, modo} con TODAS las filas pedidas hasta ahora (la
   página 1 más los "Ver más"). `contadores`: el total de cada pestaña. */
export function Explorador({ datos, estado, despachar, tabs, contadores, abrirDetalle }) {
  let def = TABLAS[estado.tab] || TABLAS.recibos;
  if (estado.tab === "notificaciones" && datos && datos.modo === "afiliado") def = TABLAS.notificaciones_afiliado;
  const items = datos ? datos.items : [];
  const total = datos ? datos.total : 0;
  return html`
    <div class="sub" id="tabla-sub">${datos ? subDe(def, estado) : "El detalle responde a todos los filtros. Al tocar un gráfico, la pestaña correspondiente se abre sola."}</div>
    <div class="tabs-datos" id="tabs-datos" role="tablist">
      ${tabs.map((t) => html`
        <button type="button" role="tab" aria-selected=${estado.tab === t} class=${"tab-d" + (estado.tab === t ? " act" : "")} data-t=${t}
          onClick=${() => despachar({ tipo: "tab", valor: t })}>${NOMBRE_TAB[t]}
          <span class="cnt" id=${"cnt-" + t}>${contadores[t] === undefined ? "0" : fmtN(contadores[t])}</span></button>`)}
    </div>
    <div class="tabla-scroll">
      <table class="tabla-exp">
        <thead id="tabla-head"><tr>${def.cols.map((c) => html`<th>${c}</th>`)}</tr></thead>
        <tbody id="tabla-body">
          ${items.length ? items.map((it) => def.fila(it, abrirDetalle))
            : html`<tr><td colspan=${def.cols.length} class="vacio-exp">Sin registros para los filtros actuales. Probá ampliar el período o quitar filtros.</td></tr>`}
        </tbody>
      </table>
    </div>
    <div class="pie-tabla">
      <span id="tabla-total">${datos ? "Mostrando " + fmtN(items.length) + " de " + fmtN(total) + " · " + def.total(fmtN(total)) : ""}</span>
      <button type="button" id="ver-mas" style=${{ visibility: items.length < total ? "visible" : "hidden" }}
        onClick=${() => despachar({ tipo: "verMas" })}>Ver más</button>
    </div>`;
}

/* ---------------- El modal "Ver" ----------------
   El fondo es `.overlay-det` y la caja `.modal-det`, las mismas clases que la
   v1: así `modales.js` la deja arrastrar en escritorio y la vuelve a su
   lugar al cerrar. Abre con un fundido y una escala corta (D5), animando
   `opacity` y `scale` y nunca `transform`, que es lo que usa el arrastre. */
export function Detalle({ pedido, cerrar }) {
  const [contenido, setContenido] = useState(null);   // {ok, datos} cuando llega
  const cerrarRef = useRef(null);
  // Al cerrar, el contenido sigue a la vista mientras el modal se desvanece.
  const ultimo = useRef(null);
  if (pedido) ultimo.current = pedido;
  useEffect(() => {
    if (!pedido) return undefined;
    setContenido(null);
    let vivo = true;
    fetch("/admin/dashboard/" + pedido.ruta)
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d) => { if (vivo) setContenido({ ok: true, datos: d }); })
      .catch(() => { if (vivo) setContenido({ ok: false }); });
    return () => { vivo = false; };
  }, [pedido]);
  const abierto = !!(pedido && contenido);
  useEffect(() => {
    if (!abierto) return undefined;
    if (cerrarRef.current) cerrarRef.current.focus();
    const tecla = (e) => { if (e.key === "Escape") cerrar(); };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [abierto]);
  let cuerpo = null;
  if (contenido && !contenido.ok) {
    cuerpo = html`<h3>No se pudo cargar el detalle</h3><div class="det-sub">Probá de nuevo en un momento.</div>`;
  } else if (contenido && ultimo.current) {
    const d = contenido.datos, p = ultimo.current;
    cuerpo = { recibo: () => html`<${DetRecibo} d=${d} />`, tramite: () => html`<${DetTramite} d=${d} />`,
      consulta: () => html`<${DetConsulta} d=${d} />`, notif: () => html`<${DetNotifs} d=${d} dia=${p.dia} />` }[p.tipo]();
  }
  return html`<div class=${"overlay-det v2-anim" + (abierto ? " abierto" : "")} id="overlay-det"
      onClick=${(e) => { if (e.target === e.currentTarget) cerrar(); }}>
    <div class="modal-det" role="dialog" aria-modal="true" aria-hidden=${!abierto}>
      <button type="button" class="modal-det-cerrar" id="det-cerrar" ref=${cerrarRef} aria-label="Cerrar" onClick=${cerrar}>✕</button>
      <div id="det-contenido">${cuerpo}</div>
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
    <h3>Recibo verificado</h3>
    <div class="det-sub">${fFecha(d.procesado_en)} · período ${d.periodo || "—"}</div>
    ${!d.enviado && html`<div class="det-anonimo">Recibo anonimizado: el trabajador no lo envió al sindicato, así que no se muestra ningún dato que lo identifique.</div>`}
    <${Fila} k="Resultado"><span class=${"tag " + (d.estado === "ok" ? "ok" : "dif")}>${d.estado === "ok" ? "Sin diferencias" : "Con diferencias"}</span><//>
    ${d.trabajador_nombre && html`<${Fila} k="Trabajador">${d.trabajador_nombre} · CUIL ${d.trabajador_cuil}<//>`}
    <${Fila} k="Empresa">${d.empresa}<//>
    <${Fila} k="Categoría">${d.categoria}<//>
    <${Fila} k="Formato">${d.formato === "nuevo" ? "Ley 27.802 (Anexo III)" : "Anterior"}<//>
    <${Fila} k="Remuneración bruta"><span class="monto">${fmtM(d.bruto)}</span><//>
    ${lineas.length > 0 && html`<div class="det-sec">Conceptos del recibo (${lineas.length})</div>
      ${lineas.map((l) => {
        const imp = typeof l.importe === "number" ? l.importe : null;
        return html`<div class="det-linea"><span>${l.descripcion || l.codigo || "—"}</span>
          <span class=${"imp" + (imp !== null && imp < 0 ? " neg" : "")}>${imp === null ? "—" : fmtM(imp)}</span></div>`;
      })}`}
    ${tot && html`<div class="det-sec">Totales</div>
      <${Fila} k="Ingresos"><span class="monto">${fmtM(tot.ingresos)}</span><//>
      <${Fila} k="Descuentos"><span class="monto">${fmtM(tot.descuentos)}</span><//>
      ${tot.reintegros ? html`<${Fila} k="Reintegros"><span class="monto">${fmtM(tot.reintegros)}</span><//>` : ""}
      <${Fila} k="Neto"><span class="monto">${fmtM(tot.neto)}</span><//>`}
    ${disc.length > 0 && html`<div class="det-sec" style=${{ color: "var(--error)" }}>Discrepancias detectadas (${disc.length})</div>
      <ul class="det-lista">${disc.map((x) => html`<li>${x.detalle}</li>`)}</ul>`}
    ${alertas.length > 0 && html`<div class="det-sec" style=${{ color: "var(--aviso)" }}>Alertas</div>
      <ul class="det-lista">${alertas.map((x) => html`<li>${x.detalle}</li>`)}</ul>`}`;
}

const ESCUDO = html`<path d="M12 3l7 3v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6z"/><circle cx="12" cy="10" r="2.3"/>`;
const PERSONA = html`<circle cx="12" cy="8" r="3.4"/><path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7"/>`;

function DetTramite({ d }) {
  const notas = d.notas || [];
  return html`
    <h3>${d.numero_expediente}</h3>
    <div class="det-sub">${d.tipo_titulo}</div>
    <${Fila} k="Estado">${d.estado_label}<//>
    <${Fila} k="Trabajador">${d.trabajador_nombre || "—"} · CUIL ${d.cuil}<//>
    <${Fila} k="Seccional">${d.seccional}<//>
    <${Fila} k="Iniciado">${fFecha(d.creado)}<//>
    <${Fila} k="Última actualización">${fFecha(d.actualizado)}<//>
    ${(d.respuestas || []).length > 0 && html`<div class="det-sec">Formulario presentado</div>
      ${d.respuestas.map((r) => html`<${Fila} k=${r.etiqueta}>${r.valor_texto || (r.tiene_archivo ? "📎 " + (r.archivo_nombre || "archivo") : "—")}<//>`)}`}
    <div class="det-sec">Conversación${notas.length ? " (" + notas.length + ")" : ""}</div>
    ${!notas.length ? html`<div class="tram-chat-vacio">Todavía no hay mensajes en este trámite.</div>` : html`
      <div class="tram-chat">${notas.map((n) => {
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
      })}</div>`}
    ${(d.log || []).length > 0 && html`<div class="det-sec">Historial</div>
      <ul class="det-lista">${d.log.map((l) => html`<li>${fFecha(l.creado)} — ${l.detalle}</li>`)}</ul>`}`;
}

function DetConsulta({ d }) {
  return html`
    <h3>Consulta al asistente</h3>
    <div class="det-sub">${fFecha(d.fecha)} · ${d.seccional}</div>
    <${Fila} k="Tema">${d.tema}<//>
    <${Fila} k="Resolución"><span class=${"tag " + (d.resuelta_por_bot ? "ok" : "rev")}>${d.resuelta_por_bot ? "Resuelta por el bot" : "Derivada"}</span><//>
    <div class="det-sec">Pregunta</div><div style=${{ fontSize: "13px" }}>${d.pregunta || "—"}</div>`;
}

function DetNotifs({ d, dia }) {
  const lista = d.notificaciones || [];
  return html`
    <h3>Notificaciones del ${fFecha(dia)}</h3>
    <div class="det-sub">${lista.length} envío${lista.length === 1 ? "" : "s"} en esta fila del explorador</div>
    ${!lista.length ? html`<div class="det-sub">Sin notificaciones.</div>` : lista.map((n) => html`<${Envio} n=${n} />`)}`;
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
          <span>${p.nombre} <span style=${{ color: "var(--gris)" }}>· ${p.cuil} · ${p.seccional}</span></span>
          <span class="imp" style=${{ color: p.leida_en ? "var(--ok)" : "var(--gris)" }}>${p.leida_en ? "✓ Leída " + fFecha(p.leida_en) : "Sin leer"}</span></div>`)
          : html`<div class="det-sub">Sin destinatarios.</div>`}
        ${dest.recortado && html`<div class="det-sub" style=${{ marginTop: "6px" }}>Mostrando ${dest.items.length} de ${fmtN(dest.total)} destinatarios.</div>`}`}
    </div>
  </div>`;
}
