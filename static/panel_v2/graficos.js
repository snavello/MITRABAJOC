/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md, bloque 4): los gráficos, el
   semáforo y el mapa.

   Cada panel pinta lo mismo que su par de la v1 (static/dashboard.js), con
   los mismos datos, las mismas etiquetas y los mismos colores, y un clic hace
   el mismo filtrado cruzado: filtra Y lleva el explorador a la pestaña que
   corresponde, en UN solo paso del reductor (D8).

   Lo nuevo son las animaciones de D5, hechas con lo que trae Chart.js:
   - cada gráfico se dibuja CUANDO SU PANEL ENTRA EN PANTALLA, no cuando
     llegan los datos: si no, los de abajo terminaban de animarse sin que
     nadie los viera (`alEntrar` de panel/movimiento);
   - al aparecer, las barras crecen desde la base una detrás de otra (la
     última arranca antes de 900 ms) y la línea se va dibujando de izquierda
     a derecha, en `--mov-datos`, con una curva que reparte el recorrido
     (easeOutCubic): con la de salida fuerte se veía terminado enseguida;
   - al cambiar los filtros, cada gráfico pasa del valor viejo al nuevo en
     `--mov-cambio`;
   - con prefers-reduced-motion no se anima nada y todo se dibuja de una (el
     panel entra con un fundido, en panel.css).

   Chart.js, Leaflet y MapaMT llegan como scripts comunes (las globales
   `Chart`, `L` y `MapaMT`), igual que en la v1. */
import { render, createContext } from "preact";
import { useContext, useEffect, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { fmtN, fmtM, fFecha, fCorta } from "panel/formato";
import { menosMovimiento, ms, alEntrar } from "panel/movimiento";

const TOPE_ENTRADA = 900;

let PALETA = null;
/* Los colores salen de las variables CSS, como en la v1: la marca del
   sindicato y los de estado, que nunca toman la marca. */
export function colores() {
  if (!PALETA) {
    const css = getComputedStyle(document.documentElement);
    const v = (n) => css.getPropertyValue(n).trim();
    PALETA = { destacado: v("--destacado"), primario: v("--marca-primario"), acento: v("--marca-acento"),
      apoyo: v("--marca-apoyo"), ok: v("--ok"), error: v("--error"), aviso: v("--aviso"),
      gris: v("--gris"), linea: v("--linea"), base: v("--marca-base"), num: v("--fuente-num") };
    estiloTooltips(PALETA);
  }
  return PALETA;
}

/* Los tooltips con el estilo de la casa (una vez por página): fondo con la
   base oscura del sindicato, filo claro, bordes redondeados y la cifra en
   monoespaciada. Entran rápido (`--mov-rapido`): se miran muchas veces. */
function estiloTooltips(C) {
  if (!window.Chart) return;
  const t = window.Chart.defaults.plugins.tooltip;
  Object.assign(t, { backgroundColor: C.base || "#152238", titleColor: "#fff", bodyColor: "#e3e9f1",
    borderColor: "rgba(255,255,255,.14)", borderWidth: 1, cornerRadius: 10, padding: { x: 12, y: 9 },
    caretSize: 6, caretPadding: 6, boxPadding: 5, usePointStyle: true, titleMarginBottom: 5,
    titleFont: { weight: "700", size: 12 }, bodyFont: { size: 12.5, family: C.num || "monospace" } });
  if (t.animation) Object.assign(t.animation, { duration: 160, easing: "easeOutQuart" });
}

/* La manito sobre lo que se puede tocar: en estos gráficos, cada barra o
   segmento filtra el panel. */
const conCursor = (opciones) => Object.assign({ onHover: (e, el) => {
  if (e.native && e.native.target) e.native.target.style.cursor = el.length ? "pointer" : "default";
} }, opciones);

/* hex + blanco (pct = cuánto del color queda): para atenuar lo que no está
   seleccionado. La misma cuenta que la v1. */
export function mezcla(hex, pct) {
  const n = parseInt(String(hex).replace("#", ""), 16);
  const f = (x) => Math.round(x * pct + 255 * (1 - pct));
  return "rgb(" + f(n >> 16) + "," + f((n >> 8) & 255) + "," + f(n & 255) + ")";
}

function animEntrada(paso, porSerie, extra) {
  if (menosMovimiento()) return { animation: false };
  return Object.assign({ animation: { duration: ms("--mov-datos"), easing: "easeOutCubic",
    delay: (c) => (c.type === "data" && c.mode === "default")
      ? Math.min(TOPE_ENTRADA, c.dataIndex * paso + c.datasetIndex * porSerie) : 0 } }, extra || {});
}
/* Un valor que pasa a otro es algo que se MUEVE en pantalla: curva de ida y
   vuelta (acelera y frena), no la de entrada. */
const animCambio = () => (menosMovimiento() ? false : { duration: ms("--mov-cambio"), easing: "easeInOutCubic" });

/* Si el panel ya se ve, y con cuánto escalón entra (lo pone `Panel`). */
const Vista = createContext({ visto: true, retraso: 0, desde: 0 });

const LEYENDA = { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", padding: 12 } };
// Con una sola serie el título ya dice qué es: la muestra de color no agrega nada.
const UNA_SERIE = { displayColors: false };

/* Un gráfico de Chart.js manejado por Preact. Se crea con los primeros datos
   y después se ACTUALIZA, no se recrea: Chart.js anima de lo viejo a lo
   nuevo solo si sigue siendo el mismo gráfico. `deps` dice cuándo volver a
   pintar.

   La entrada espera a que el panel se vea: el gráfico se crea igual apenas
   llegan los datos (quieto, con el panel todavía invisible, así quien lo lea
   —el robot de paridad, por ejemplo— ya lo encuentra), y cuando el panel
   entra en pantalla vuelve a cero y se dibuja (`reset()` + `update()`). */
function useGrafico(tipo, armar, deps) {
  const vista = useContext(Vista);
  const lienzo = useRef(null);
  const ch = useRef(null);
  const pendiente = useRef(null);       // {options, entrada}: la entrada que falta dibujar
  const reloj = useRef(0);

  const dibujarEntrada = () => {
    const c = ch.current, p = pendiente.current;
    if (!c || !p) return;
    pendiente.current = null;
    c.options = Object.assign({}, p.options, p.entrada);
    // Primero se aplican las opciones de la entrada, quieto: `reset()` las
    // lee para saber desde dónde arrancar (la dona, por ejemplo, desde el
    // ángulo cero). Después vuelve a cero y se dibuja.
    c.update("none");
    c.reset();
    c.update();
  };
  // Lo que falta del escalón de este panel (puede que ya haya pasado).
  const programar = () => {
    clearTimeout(reloj.current);
    const falta = Math.max(0, vista.retraso - (performance.now() - vista.desde));
    if (falta) reloj.current = setTimeout(dibujarEntrada, falta); else dibujarEntrada();
  };

  useEffect(() => {
    const a = armar();
    if (!a || !lienzo.current || !window.Chart) return;
    if (!ch.current) {
      if (menosMovimiento()) {
        ch.current = new window.Chart(lienzo.current, { type: tipo, data: a.data, options: Object.assign({}, a.options, a.entrada) });
        return;
      }
      ch.current = new window.Chart(lienzo.current, { type: tipo, data: a.data,
        options: Object.assign({}, a.options, { animation: false }) });
      pendiente.current = { options: a.options, entrada: a.entrada };
      if (vista.visto) programar();
      return;
    }
    const c = ch.current;
    c.data.labels = a.data.labels;
    a.data.datasets.forEach((ds, i) => {
      if (c.data.datasets[i]) Object.assign(c.data.datasets[i], ds); else c.data.datasets.push(ds);
    });
    c.data.datasets.length = a.data.datasets.length;
    if (pendiente.current) {
      // Todavía no se vio: se actualiza quieto y la entrada se dibuja con lo nuevo.
      pendiente.current.options = a.options;
      c.options = Object.assign({}, a.options, { animation: false });
    } else {
      c.options = Object.assign({}, a.options, { animation: animCambio(), animations: {} });
    }
    c.update();
  }, deps);
  useEffect(() => { if (vista.visto && pendiente.current) programar(); }, [vista.visto]);
  useEffect(() => () => {
    clearTimeout(reloj.current);
    if (ch.current) ch.current.destroy();
    ch.current = null;
  }, []);
  return lienzo;
}

/* El marco de cada panel: título, bajada, estado de carga y el error con su
   reintento (DASHBOARD.md §4.6: un panel caído no rompe el resto).

   Entra en escena cuando se lo mira (`visto`, con el escalón que le toca si
   entran varios juntos) y, mientras espera sus primeros datos, muestra un
   esqueleto con un brillo que lo recorre en vez de un hueco. */
export function Panel({ nombre, titulo, sub, clase = "", estado = {}, reintentar, children }) {
  const caja = useRef(null);
  const [vista, setVista] = useState(() => (menosMovimiento() ? { visto: true, retraso: 0, desde: 0 }
    : { visto: false, retraso: 0, desde: 0 }));
  useEffect(() => alEntrar(caja.current, (retraso) => setVista({ visto: true, retraso, desde: performance.now() })), []);
  const conError = estado.error !== undefined && estado.error !== null;
  const esperando = !estado.datos && !conError;
  const cls = "panel " + clase + (estado.cargando ? " cargando" : "") + (conError ? " con-error" : "")
    + (vista.visto ? " visto" : "") + (esperando ? " esperando" : "");
  return html`<div class=${cls} data-panel=${nombre} aria-busy=${!!estado.cargando} ref=${caja}
      style=${{ "--retraso": vista.retraso + "ms" }}>
    <h3>${titulo}</h3>${sub && html`<div class="sub">${sub}</div>`}
    <${Vista.Provider} value=${vista}>${children}<//>
    ${esperando && html`<div class="v2-esqueleto" aria-hidden="true"><i></i><i></i><i></i><i></i></div>`}
    <div class="panel-error"><span>${estado.error || "No se pudo cargar este panel."}</span>
      <button type="button" onClick=${reintentar}>Reintentar</button></div>
  </div>`;
}

/* ---------------- Recibos por día ---------------- */
export function Serie({ datos }) {
  const C = colores();
  const lienzo = useGrafico("line", () => datos && {
    data: { labels: datos.serie.map((p) => fCorta(p.dia)), datasets: [{ data: datos.serie.map((p) => p.cantidad),
      borderColor: C.primario, fill: true, tension: 0.35, borderWidth: 2.5, pointRadius: 0, pointHitRadius: 12,
      pointHoverRadius: 4,
      backgroundColor: (c) => {
        const g = c.chart.ctx.createLinearGradient(0, 0, 0, 220);
        g.addColorStop(0, mezcla(C.primario, 0.25)); g.addColorStop(1, "rgba(255,255,255,0)");
        return g;
      } }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: UNA_SERIE },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 9, maxRotation: 0 } },
        y: { beginAtZero: true, grid: { color: C.linea } } } },
    // La línea sube desde el cero, de izquierda a derecha.
    entrada: animEntrada(4, 0, menosMovimiento() ? {} : { animations: { y: { duration: ms("--mov-datos") * 0.65, easing: "easeOutCubic",
      from: (c) => (c.type === "data" ? c.chart.scales.y.getPixelForValue(0) : undefined),
      // Cada punto arranca un poco después del anterior: en total, la línea
      // tarda TOPE_ENTRADA en recorrer el gráfico de punta a punta.
      delay: (c) => (c.type === "data" && c.mode === "default"
        ? Math.round(c.dataIndex / Math.max(1, c.chart.data.labels.length - 1) * TOPE_ENTRADA) : 0) } } }),
  }, [datos]);
  return html`<div class="c-wrap"><canvas ref=${lienzo}></canvas></div>`;
}

/* ---------------- Resultado de la validación ---------------- */
export function Validacion({ datos, estado, despachar }) {
  const C = colores();
  const valores = ["ok", "con_diferencias"];
  const lienzo = useGrafico("doughnut", () => datos && {
    data: { labels: ["Correctos", "Con diferencias"], datasets: [{ data: [datos.ok, datos.con_diferencias],
      offset: valores.map((v) => (estado.resultado === v ? 14 : 0)),
      borderColor: valores.map((v) => (estado.resultado === v ? C.destacado : "#fff")),
      backgroundColor: valores.map((v, i) => {
        const base = [C.ok, C.error][i];
        return (estado.resultado && estado.resultado !== v) ? mezcla(base, 0.3) : base;
      }), borderWidth: 3, hoverOffset: 8 }] },
    options: conCursor({ responsive: true, maintainAspectRatio: false, cutout: "62%",
      onClick: (e, el) => {
        if (!el.length) return;
        despachar([{ tipo: "alternarValor", campo: "resultado", valor: valores[el[0].index] },
          { tipo: "tab", valor: "recibos" }]);
      },
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", padding: 14 } } } }),
    entrada: menosMovimiento() ? { animation: false }
      : { animation: { duration: ms("--mov-datos") + 300, easing: "easeOutCubic", animateRotate: true, animateScale: true } },
  }, [datos, estado.resultado]);
  return html`<div class="c-wrap"><canvas ref=${lienzo}></canvas></div>`;
}

/* ---------------- Trámites por seccional y estado ---------------- */
const ESTADOS = ["abierto", "en_proceso", "resuelto"];
export function Tramites({ datos, estado, despachar }) {
  const C = colores();
  const filas = datos ? datos.seccionales : [];
  const elegidas = estado.seccionales;
  const lienzo = useGrafico("bar", () => datos && {
    data: { labels: filas.map((f) => f.seccional), datasets: ["Abiertos", "En proceso", "Resueltos"].map((label, i) => {
      const base = [C.aviso, C.apoyo, C.ok][i], est = ESTADOS[i];
      return { label, data: filas.map((f) => f[est]), borderRadius: 4, maxBarThickness: 30, borderWidth: 2,
        backgroundColor: filas.map((f) => {
          const apagado = (elegidas.length > 0 && !(f.seccional_id !== null && elegidas.indexOf(f.seccional_id) >= 0))
            || (estado.estadoTramite && estado.estadoTramite !== est);
          return apagado ? mezcla(base, 0.28) : base;
        }),
        borderColor: filas.map((f) => ((f.seccional_id !== null && elegidas.indexOf(f.seccional_id) >= 0)
          ? C.destacado : "rgba(0,0,0,0)")) };
    }) },
    options: conCursor({ indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, el) => {
        if (!el.length) return;
        const fila = filas[el[0].index];
        despachar([{ tipo: "tramiteSeccional", seccional: fila.seccional_id, estado: ESTADOS[el[0].datasetIndex] },
          { tipo: "tab", valor: "tramites" }]);
      },
      plugins: { legend: Object.assign({}, LEYENDA, { onClick: (e, item) => despachar([
        { tipo: "alternarValor", campo: "estadoTramite", valor: ESTADOS[item.datasetIndex] },
        { tipo: "tab", valor: "tramites" }]) }) },
      scales: { x: { stacked: true, grid: { color: C.linea } }, y: { stacked: true, grid: { display: false } } } }),
    entrada: animEntrada(110, 160),
  }, [datos, elegidas.join(","), estado.estadoTramite]);
  return html`<div class="c-wrap chica"><canvas ref=${lienzo}></canvas></div>`;
}

/* ---------------- Notificaciones leídas y no leídas ---------------- */
export function Notificaciones({ datos, estado, despachar }) {
  const C = colores();
  const tipos = datos ? datos.por_tipo : [];
  const lienzo = useGrafico("bar", () => datos && {
    data: { labels: tipos.map((t) => t.etiqueta), datasets: [
      { label: "Leídas", data: tipos.map((t) => t.leidas), borderRadius: 4, maxBarThickness: 22,
        backgroundColor: tipos.map((t) => (!estado.tipoNotif ? C.primario
          : (t.tipo === estado.tipoNotif ? C.destacado : mezcla(C.primario, 0.25)))) },
      { label: "No leídas", data: tipos.map((t) => t.sin_leer), borderRadius: 4, maxBarThickness: 22,
        backgroundColor: tipos.map((t) => ((estado.tipoNotif && t.tipo !== estado.tipoNotif)
          ? mezcla(C.primario, 0.12) : mezcla(C.primario, 0.35))) }] },
    options: conCursor({ indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, el) => {
        if (!el.length) return;
        despachar([{ tipo: "alternarValor", campo: "tipoNotif", valor: tipos[el[0].index].tipo },
          { tipo: "tab", valor: "notificaciones" }]);
      },
      plugins: { legend: LEYENDA },
      scales: { x: { stacked: true, grid: { color: C.linea } }, y: { stacked: true, grid: { display: false } } } }),
    entrada: animEntrada(120, 180),
  }, [datos, estado.tipoNotif]);
  return html`
    <div class="notif-resumen" id="notif-resumen">${datos && html`
      <div class="notif-caja"><div class="n">${fmtN(datos.enviadas)}</div><div class="t">Enviadas</div></div>
      <div class="notif-caja"><div class="n" style=${{ color: C.primario }}>${fmtN(datos.leidas)}</div><div class="t">Leídas</div></div>
      <div class="notif-caja"><div class="n" style=${{ color: C.error }}>${fmtN(datos.sin_leer)}</div><div class="t">Sin leer</div></div>`}
    </div>
    <div class="c-wrap" style=${{ height: "150px" }}><canvas ref=${lienzo}></canvas></div>`;
}

/* ---------------- Empresas con más diferencias ---------------- */
export function Empresas({ datos, estado, despachar }) {
  const C = colores();
  const filas = datos ? datos.empresas : [];
  const elegidas = estado.empresas;
  const lienzo = useGrafico("bar", () => datos && {
    data: { labels: filas.map((e) => e.nombre), datasets: [{ data: filas.map((e) => e.monto), borderRadius: 6,
      maxBarThickness: 26, backgroundColor: filas.map((e) => (!elegidas.length ? C.error
        : ((e.empresa_id !== null && elegidas.indexOf(e.empresa_id) >= 0) ? C.destacado : mezcla(C.error, 0.25)))) }] },
    options: conCursor({ indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, el) => {
        if (!el.length) return;
        const emp = filas[el[0].index];
        if (!emp || emp.empresa_id === null) return;   // CUIT fuera del catálogo: no hay filtro posible
        despachar([{ tipo: "alternar", campo: "empresas", id: emp.empresa_id }, { tipo: "tab", valor: "recibos" }]);
      },
      plugins: { legend: { display: false }, tooltip: Object.assign({ callbacks: { label: (c) => fmtM(c.raw) } }, UNA_SERIE) },
      scales: { x: { grid: { color: C.linea }, ticks: { callback: (v) => (v >= 1e6
        ? "$" + (v / 1e6).toLocaleString("es-AR", { maximumFractionDigits: 1 }) + "M" : "$" + Math.round(v / 1000) + "k") } },
        y: { grid: { display: false } } } }),
    entrada: animEntrada(110, 0),
  }, [datos, elegidas.join(",")]);
  return html`<div class="c-wrap chica"><canvas ref=${lienzo}></canvas></div>`;
}

/* ---------------- Consultas al asistente (solo con el carril prendido) ---------------- */
export function Consultas({ datos, estado, despachar }) {
  const C = colores();
  const temas = datos ? datos.temas : [];
  const lienzo = useGrafico("bar", () => datos && {
    data: { labels: temas.map((t) => t.tema), datasets: [{ data: temas.map((t) => t.cantidad), borderRadius: 6,
      maxBarThickness: 26, backgroundColor: temas.map((t) => (!estado.tema ? C.primario
        : (t.tema === estado.tema ? C.destacado : mezcla(C.primario, 0.25)))) }] },
    options: conCursor({ indexAxis: "y", responsive: true, maintainAspectRatio: false,
      onClick: (e, el) => {
        if (!el.length) return;
        despachar([{ tipo: "alternarValor", campo: "tema", valor: temas[el[0].index].tema },
          { tipo: "tab", valor: "consultas" }]);
      },
      plugins: { legend: { display: false }, tooltip: UNA_SERIE },
      scales: { x: { grid: { color: C.linea } }, y: { grid: { display: false } } } }),
    entrada: animEntrada(110, 0),
  }, [datos, estado.tema]);
  return html`<div class="c-wrap chica"><canvas ref=${lienzo}></canvas></div>`;
}

/* ---------------- Adopción del nuevo formato ---------------- */
export function Formato({ datos }) {
  const C = colores();
  const semanas = datos ? datos.semanas : [];
  const lienzo = useGrafico("bar", () => datos && {
    data: { labels: semanas.map((s) => fCorta(s.semana)), datasets: [
      { label: "Formato anterior", data: semanas.map((s) => s.clasico), backgroundColor: "#b9c0cc", borderRadius: 5, maxBarThickness: 30 },
      { label: "Nuevo (Ley 27.802)", data: semanas.map((s) => s.nuevo), backgroundColor: C.acento, borderRadius: 5, maxBarThickness: 30 }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", padding: 14 } } },
      scales: { x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        y: { stacked: true, grid: { color: C.linea } } } },
    entrada: animEntrada(70, 120),
  }, [datos]);
  return html`<div class="c-wrap chica"><canvas ref=${lienzo}></canvas></div>`;
}

/* ---------------- Semáforo de aportes ---------------- */
const ESTADO_SEM = { verde: ["--ok", "al día", "Al día"], amarillo: ["--aviso", "demoradas", "Demorado"],
  rojo: ["--error", "críticas", "Crítico"] };
export function Semaforo({ datos }) {
  // Las filas entran escalonadas recién cuando el panel se ve.
  const vista = useContext(Vista);
  if (!datos) return html`<div class="sem-resumen" id="sem-resumen"></div><div class="sem-lista" id="sem-lista"></div>`;
  return html`
    <div class="sem-resumen" id="sem-resumen">${["verde", "amarillo", "rojo"].map((k) => html`
      <span><i class="punto" style=${{ background: "var(" + ESTADO_SEM[k][0] + ")" }}></i>${datos.resumen[k]} ${ESTADO_SEM[k][1]}</span>`)}
    </div>
    <div class="sem-lista" id="sem-lista">${datos.empresas.length ? datos.empresas.map((e, i) => html`
      <div class=${"sem-item" + (vista.visto ? " v2-aparece" : "")}
        style=${{ "--lc": "var(" + ESTADO_SEM[e.estado][0] + ")", animationDelay: vista.retraso + Math.min(i * 70, 700) + "ms" }}>
        <span class="luz"></span>
        <div><div class="emp">${e.nombre}</div>
          <div class="dep">Último depósito: ${fFecha(e.ultimo_deposito)} · ${ESTADO_SEM[e.estado][2]}</div></div>
        <span class="dias">${e.dias} d</span>
      </div>`)
      : html`<div style=${{ color: "var(--gris)", fontSize: "12.5px", padding: "14px 0" }}>Sin datos de depósitos para los filtros actuales.</div>`}
    </div>`;
}

/* ---------------- Mapa de seccionales ----------------
   Es también un SELECTOR: tocar una burbuja filtra el panel por esa
   seccional, y por eso el endpoint ignora el filtro de seccional. Leaflet se
   crea UNA vez y después solo se cambia la capa de burbujas: recrearlo
   pediría de nuevo todas las teselas a OSM. */
const METRICAS = {
  afiliados: { etiqueta: "Afiliados", pct: false },
  pct_ingresaron: { etiqueta: "% que ingresó", pct: true },
  recibos: { etiqueta: "Recibos validados", pct: false },
  pct_con_diferencias: { etiqueta: "% con diferencias", pct: true },
  tramites_abiertos: { etiqueta: "Trámites abiertos", pct: false },
};

function Popup({ s }) {
  const pct = (v) => (v === null || v === undefined ? "—" : v + "%");
  const filas = [["Afiliados", fmtN(s.afiliados)], ["Ingresó al menos una vez", fmtN(s.ingresaron) + " · " + pct(s.pct_ingresaron)],
    ["Recibos validados", fmtN(s.recibos)], ["Con diferencias", fmtN(s.con_diferencias) + " · " + pct(s.pct_con_diferencias)],
    ["Trámites abiertos", fmtN(s.tramites_abiertos)], ["Notificaciones leídas", pct(s.tasa_lectura)]];
  return html`<div class="mapa-pop"><b>${s.nombre}</b>
    ${s.direccion_texto && html`<div style=${{ fontSize: "11.5px", color: "#5b6478" }}>${s.direccion_texto}</div>`}
    <table>${filas.map(([k, v]) => html`<tr><td>${k}</td><td>${v}</td></tr>`)}</table></div>`;
}

export function MapaSeccionales({ datos, estado, despachar, logo }) {
  const C = colores();
  const caja = useRef(null);
  const mapa = useRef(null);
  const capa = useRef(null);
  const [metrica, setMetrica] = useState("afiliados");
  const lista = datos ? datos.seccionales || [] : [];
  const maximo = Math.max(0, ...lista.map((s) => s[metrica] || 0));
  useEffect(() => {
    if (!datos || !window.L || !window.MapaMT || !caja.current) return;
    if (!mapa.current) mapa.current = window.MapaMT.crear(caja.current, { rueda: false });
    if (!mapa.current) return;
    if (capa.current) mapa.current.mapa.removeLayer(capa.current);
    capa.current = window.L.layerGroup().addTo(mapa.current.mapa);
    const maxAf = Math.max(1, ...lista.map((s) => s.afiliados || 0));
    const puntos = [];
    lista.forEach((s) => {
      const elegida = estado.seccionales.indexOf(s.id) >= 0;
      const marcador = window.MapaMT.burbuja(s.lat, s.lon, {
        diametro: window.MapaMT.diametroBurbuja(s.afiliados, maxAf),
        borde: window.MapaMT.colorEscala(s[metrica], maximo),
        relleno: elegida ? C.destacado : "#ffffff", seleccionada: elegida, logo });
      // El globo se arma con Preact sobre un nodo propio: nada de HTML como texto.
      const globo = document.createElement("div");
      render(html`<${Popup} s=${s} />`, globo);
      marcador.bindPopup(globo, { maxWidth: 280 });
      marcador.on("click", () => despachar({ tipo: "alternar", campo: "seccionales", id: s.id }));
      marcador.addTo(capa.current);
      puntos.push([s.lat, s.lon]);
    });
    mapa.current.refrescar();
    // Se encuadra solo la primera vez: después le movería el mapa a quien está mirando una zona.
    if (!mapa.current._encuadrado && puntos.length) { mapa.current.encuadrar(puntos); mapa.current._encuadrado = true; }
  }, [datos, metrica, estado.seccionales.join(",")]);
  useEffect(() => () => { if (mapa.current) mapa.current.mapa.remove(); }, []);
  const meta = METRICAS[metrica];
  const sufijo = meta.pct ? "%" : "";
  const faltan = datos ? datos.sin_ubicar || [] : [];
  return html`
    <div class="mapa-controles">
      <label for="mapa-metrica">Colorear por</label>
      <select id="mapa-metrica" value=${metrica} onChange=${(e) => setMetrica(e.target.value)}>
        ${Object.keys(METRICAS).map((k) => html`<option value=${k}>${METRICAS[k].etiqueta}</option>`)}
      </select>
      <div class="mapa-leyenda" id="mapa-leyenda">
        <span>0${sufijo}</span>
        ${(window.MapaMT ? window.MapaMT.ESCALA : []).map((c) => html`<i style=${{ background: c }}></i>`)}
        <span>${fmtN(Math.round(maximo))}${sufijo}</span>
        <span style=${{ marginLeft: "10px" }}>el tamaño es la cantidad de afiliados</span>
      </div>
    </div>
    <div class="mapa-panel" id="mapa-seccionales" ref=${caja}></div>
    <div class=${"mapa-sin-ubicar" + (faltan.length ? " hay" : "")} id="mapa-sin-ubicar">${faltan.length ? html`
      ${faltan.length} ${faltan.length > 1 ? "seccionales sin ubicación, no se muestran en el mapa" : "seccional sin ubicación, no se muestra en el mapa"}: ${faltan.map((s) => s.nombre).join(", ")}.
      ${" "}${datos.puede_georreferenciar ? html`<a href="/admin#seccionales">Georreferenciarlas</a>`
        : "Pedile al administrador del sindicato que las ubique."}` : ""}</div>`;
}
