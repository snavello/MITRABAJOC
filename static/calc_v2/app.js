/* Calculadora bancaria v2 (Herramientas de /entornos).

   La misma calculadora que la v1 (templates/calculadora_bancaria.html), con
   los mismos pedidos al servidor (/api/entornos/herramientas/bancaria/*) y
   la misma regla: el cálculo y la comparación los hace el servidor, la
   pantalla solo muestra. Lo nuevo es la interfaz, en Preact como la v2 del
   Panel Sindical: los importes corren de un valor a otro, el ✓ se dibuja,
   las filas entran, el veredicto final compara convenio + otros contra el
   recibo, y lo que toca un "Ajustar al recibo" se ilumina para que se vea
   qué cambió. Convive con la v1 hasta que SDN decida reemplazarla. */
import { render } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import { html } from "calc/html";
import { Numero, Tilde, Luz, pesos } from "calc/piezas";
import { menosMovimiento } from "calc/movimiento";

const API = "/api/entornos/herramientas/bancaria";
const raiz = document.getElementById("calculadora");
const ESTADOS = JSON.parse(raiz.dataset.estados || "[]");
const ISOTIPO = raiz.dataset.isotipo;
const SECCIONES = { haberes: "Haberes remunerativos", no_remunerativos: "No remunerativos", descuentos: "Descuentos" };
const IA_FASES = ["Abriendo el archivo", "Tapando los datos personales", "Leyendo los conceptos con IA", "Ubicando cada renglón en la calculadora"];
const IA_ARO = 414;   // 2·PI·66, el perímetro del círculo del SVG

// "1.234.567,89", "1234567.89" o "1234567,89" -> número; vacío -> null.
function aNumero(s) {
  s = String(s ?? "").trim().replace(/\$|\s/g, "");
  if (!s) return null;
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  else if ((s.match(/\./g) || []).length > 1) s = s.replace(/\./g, "");
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}
const aTexto = (v) => (v === null || v === undefined || v === "" ? "" : String(v).replace(".", ","));

async function pedir(url, cuerpo) {
  const r = await fetch(url, cuerpo === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ("Error " + r.status));
  return d;
}

const CONTROLES_INICIALES = {
  rama: "administrativa", categoria: 0, tramo_roe: 1, cajero: false, falla_me: false, titulo: "", zona: "",
  guarderia: false, conectividad: "", dias_conectividad: 1, dia_bancario: false, afiliado: true,
  cuota_pct: "2", ganancias: "",
};
let siguienteExtra = 1;
const nuevoExtra = (x = {}) => ({ id: siguienteExtra++, concepto: x.concepto || "", seccion: x.seccion || "haberes",
  importe: x.importe != null ? aTexto(x.importe) : "" });

function App() {
  const [opciones, setOpciones] = useState(null);
  const [periodo, setPeriodo] = useState("");
  const [c, setC] = useState(CONTROLES_INICIALES);
  const [chequeando, setChequeando] = useState(false);
  const [reales, setReales] = useState({});
  const [totReales, setTotReales] = useState({ bruto: "", descuentos: "", neto: "" });
  const [extras, setExtras] = useState([]);
  const [editarAbierto, setEditarAbierto] = useState(false);
  const [banco, setBanco] = useState("");
  const [nota, setNota] = useState("");
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [resaltados, setResaltados] = useState({});
  const [ia, setIa] = useState({ abierta: false, leyendo: false, segundos: 0, resultado: null });
  const [aviso, setAviso] = useState(null);
  const [vista, setVista] = useState(location.hash === "#casos" ? "casos" : "calcular");
  const [casos, setCasos] = useState([]);
  const archivoRef = useRef(null);
  const iaRef = useRef(null);

  // ---------- la grilla ----------
  async function cargarOpciones(p) {
    const o = await pedir(API + "/opciones" + (p ? "?periodo=" + encodeURIComponent(p) : ""));
    setOpciones(o);
    setPeriodo(o.periodo);
    return o;
  }
  useEffect(() => {
    cargarOpciones().catch((e) => setError("No se pudo cargar la grilla: " + e.message));
    cargarCasos();
  }, []);

  const set = (campo, valor) => setC((v) => ({ ...v, [campo]: valor }));

  // ---------- lo que se manda a calcular ----------
  const entrada = useMemo(() => ({
    periodo, rama: c.rama, categoria: Number(c.categoria), tramo_roe: Number(c.tramo_roe), cajero: c.cajero,
    falla_me: c.falla_me, titulo: c.titulo, zona: c.zona, guarderia: c.guarderia, conectividad: c.conectividad,
    dias_conectividad: Number(c.dias_conectividad || 1), dia_bancario: c.dia_bancario, afiliado: c.afiliado,
    cuota_pct: aNumero(c.cuota_pct) ?? 0, ganancias: aNumero(c.ganancias) ?? 0,
  }), [periodo, c]);
  const real = useMemo(() => {
    const renglones = {};
    for (const [k, v] of Object.entries(reales)) { const n = aNumero(v); if (n !== null && !Number.isNaN(n)) renglones[k] = n; }
    const totales = {};
    for (const k of ["bruto", "descuentos", "neto"]) { const n = aNumero(totReales[k]); if (n !== null && !Number.isNaN(n)) totales[k] = n; }
    const ex = extras.map((e) => ({ concepto: e.concepto, seccion: e.seccion, importe: aNumero(e.importe) }))
      .filter((e) => e.concepto || (e.importe !== null && !Number.isNaN(e.importe)));
    return { renglones, totales, extras: ex };
  }, [reales, totReales, extras]);

  const turno = useRef(0);
  useEffect(() => {
    if (!periodo) return;
    const t = setTimeout(async () => {
      const mio = ++turno.current;
      try {
        const r = await pedir(API + "/calcular", { entrada, real: chequeando ? real : null });
        if (mio === turno.current) { setD(r); setError(""); }
      } catch (e) { if (mio === turno.current) setError(e.message); }
    }, 120);
    return () => clearTimeout(t);
  }, [entrada, real, chequeando]);

  // ---------- ajustar al recibo ----------
  // Lo que se toca se ilumina un momento: la persona ve qué cambió y dónde.
  function resaltar(campos) {
    const marca = Date.now();
    setResaltados((r) => ({ ...r, ...Object.fromEntries(campos.map((k) => [k, marca])) }));
    setTimeout(() => setResaltados((r) => Object.fromEntries(Object.entries(r).filter(([, v]) => v !== marca))), 1600);
  }
  function aplicarAjuste(campos) {
    const nuevos = {};
    for (const [k, v] of Object.entries(campos)) {
      if (!(k in CONTROLES_INICIALES)) continue;
      nuevos[k] = typeof v === "number" && ["cuota_pct", "ganancias"].includes(k) ? aTexto(v) : v;
    }
    setC((v) => ({ ...v, ...nuevos }));
    resaltar(Object.keys(nuevos));
  }
  function ajustarCategoria(rama, i) {
    setC((v) => ({ ...v, rama, categoria: i }));
    resaltar(["rama", "categoria"]);
  }

  // ---------- chequeo ----------
  function alternarManual() {
    const si = !chequeando;
    setChequeando(si);
    if (si) setEditarAbierto(true); else setIa((v) => ({ ...v, abierta: false }));
  }
  function abrirIA() {
    setChequeando(true);
    setEditarAbierto(false);
    setIa((v) => ({ ...v, abierta: true }));
    setTimeout(() => iaRef.current && iaRef.current.scrollIntoView({ behavior: menosMovimiento() ? "auto" : "smooth", block: "start" }), 30);
    if (!ia.leyendo && archivoRef.current) archivoRef.current.click();
  }
  useEffect(() => {
    if (!ia.leyendo) return;
    const t = setInterval(() => setIa((v) => ({ ...v, segundos: v.segundos + 1 })), 1000);
    return () => clearInterval(t);
  }, [ia.leyendo]);

  async function leerArchivo(ev) {
    const f = ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    setIa({ abierta: true, leyendo: true, segundos: 0, resultado: null, archivo: f.name });
    const datos = new FormData(); datos.append("archivo", f);
    try {
      const r = await fetch(API + "/leer", { method: "POST", body: datos });
      const l = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(l.detail || ("Error " + r.status));
      setReales(Object.fromEntries(Object.entries(l.renglones || {}).map(([k, v]) => [k, aTexto(v)])));
      setTotReales({ bruto: aTexto(l.totales?.bruto), descuentos: aTexto(l.totales?.descuentos), neto: aTexto(l.totales?.neto) });
      setExtras((l.extras || []).map(nuevoExtra));
      if (!banco && l.banco) setBanco(l.banco);
      setEditarAbierto(false);
      const items = [`${l.ubicados} renglones ubicados en el recibo esperado.`];
      if (!(l.renglones || {}).BAS) items.push("No se leyó el sueldo básico: elegí la categoría a mano.");
      if ((l.extras || []).length) items.push(`${l.extras.length} renglón(es) que la calculadora no tiene: van a "Otros del recibo".`);
      if (l.reintegros) items.push(`${l.reintegros} reintegro(s) que la calculadora no contempla.`);
      if (l.periodo && l.periodo !== periodo) items.push(`Ojo: el recibo es de ${l.periodo} y la grilla elegida es ${periodo}.`);
      setIa((v) => ({ ...v, leyendo: false, resultado: { ok: !l.mock, items,
        titulo: l.mock ? "LECTURA SIMULADA (MOCK_EXTRACTOR activo en este entorno): los importes no son del recibo."
                       : "Listo: " + f.name + ". Revisá los importes antes de guardar." } }));
    } catch (e) {
      setIa((v) => ({ ...v, leyendo: false, resultado: { ok: false, titulo: e.message, items: [] } }));
    }
  }

  // ---------- guardar ----------
  async function guardar() {
    const malos = [...Object.values(reales), ...Object.values(totReales)].filter((v) => Number.isNaN(aNumero(v)));
    if (malos.length) { setAviso({ ok: false, texto: "Hay importes que no se entienden: " + malos.join(", ") }); return; }
    try {
      const r = await pedir(API + "/casos", { entrada, real, banco, nota });
      setAviso({ ok: true, texto: "Caso #" + r.id + " guardado. Está en «Casos guardados»." });
      setNota("");
      cargarCasos();
    } catch (e) { setAviso({ ok: false, texto: e.message }); }
  }

  // ---------- casos ----------
  async function cargarCasos() {
    try { setCasos((await pedir(API + "/casos")).casos); } catch (e) { /* la pestaña muestra la lista vacía */ }
  }
  async function abrirEnCalculadora(caso) {
    const e = caso.entrada || {};
    if (e.periodo && e.periodo !== periodo) await cargarOpciones(e.periodo);
    setC({ ...CONTROLES_INICIALES, ...Object.fromEntries(Object.entries(e).filter(([k]) => k in CONTROLES_INICIALES)),
      cuota_pct: aTexto(e.cuota_pct ?? 2), ganancias: e.ganancias ? aTexto(e.ganancias) : "" });
    const r = caso.real || {};
    setReales(Object.fromEntries(Object.entries(r.renglones || {}).map(([k, v]) => [k, aTexto(v)])));
    setTotReales({ bruto: aTexto(r.totales?.bruto), descuentos: aTexto(r.totales?.descuentos), neto: aTexto(r.totales?.neto) });
    setExtras((r.extras || []).map(nuevoExtra));
    setBanco(caso.banco || ""); setNota("");
    setChequeando(true); setEditarAbierto(true);
    irA("calcular");
  }
  function irA(v) {
    setVista(v);
    history.replaceState(null, "", v === "casos" ? "#casos" : location.pathname);
    if (v === "casos") cargarCasos();
  }

  if (!opciones) return html`<div class="cargando">${error || "Cargando la grilla…"}</div>`;
  const nuevos = casos.filter((x) => x.estado === "nuevo").length;
  return html`
    <${Pestanas} vista=${vista} irA=${irA} cuenta=${nuevos + " nuevos · " + casos.length} />
    <section hidden=${vista !== "calcular"} class="vista">
      <div class="grid">
        <${Controles} opciones=${opciones} c=${c} set=${set} periodo=${periodo} resaltados=${resaltados}
          reales=${reales} ajustarCategoria=${ajustarCategoria}
          cambiarGrilla=${async (p) => { await cargarOpciones(p); }} />
        <div class="columna">
          <${Recibo} d=${d} error=${error} chequeando=${chequeando} reales=${reales} setReales=${setReales}
            aplicarAjuste=${aplicarAjuste} abrirIA=${abrirIA} alternarManual=${alternarManual} />
          ${ia.abierta && html`<${CajaIA} ia=${ia} iaRef=${iaRef} archivoRef=${archivoRef} d=${d} opciones=${opciones} c=${c}
            reales=${reales} cerrar=${() => setIa((v) => ({ ...v, abierta: false }))} aplicarAjuste=${aplicarAjuste}
            ajustarCategoria=${ajustarCategoria} />`}
          <input type="file" ref=${archivoRef} accept="application/pdf,image/*" hidden onChange=${leerArchivo} />
          ${chequeando && html`<${ReciboReal} abierto=${editarAbierto} setAbierto=${setEditarAbierto} totReales=${totReales}
            setTotReales=${setTotReales} extras=${extras} setExtras=${setExtras} banco=${banco} setBanco=${setBanco}
            nota=${nota} setNota=${setNota} guardar=${guardar} aviso=${aviso} />`}
        </div>
      </div>
    </section>
    <section hidden=${vista !== "casos"} class="vista">
      <${Casos} casos=${casos} recargar=${cargarCasos} abrir=${abrirEnCalculadora} />
    </section>`;
}

// ---------- pestañas: la marca se desliza de una a otra ----------
function Pestanas({ vista, irA, cuenta }) {
  const lista = useRef(null);
  const [marca, setMarca] = useState(null);
  useEffect(() => {
    const b = lista.current && lista.current.querySelector(`[data-vista="${vista}"]`);
    if (b) setMarca({ x: b.offsetLeft, w: b.offsetWidth });
  }, [vista, cuenta]);
  return html`<nav class="pestanas" role="tablist" ref=${lista}>
    <button class="pestana" role="tab" data-vista="calcular" aria-selected=${vista === "calcular"} onClick=${() => irA("calcular")}>Calcular</button>
    <button class="pestana" role="tab" data-vista="casos" aria-selected=${vista === "casos"} onClick=${() => irA("casos")}>
      Casos guardados <span class="cuenta">${cuenta}</span></button>
    ${marca && html`<span class="pestana-marca" style=${{ translate: marca.x + "px 0", width: marca.w + "px" }}></span>`}
  </nav>`;
}

// ---------- la columna de controles ----------
function Controles({ opciones, c, set, periodo, resaltados, reales, ajustarCategoria, cambiarGrilla }) {
  const r = (campo) => (resaltados[campo] ? " resalta" : "");
  const cats = opciones.ramas[c.rama].categorias;
  const opcionesCat = (filtro) => cats.map((x, i) => [x, i]).filter(([x]) => filtro(x)).map(([x, i]) =>
    html`<option value=${i}>${x.nombre} · coef. ${x.coef.toFixed(2).replace(".", ",")}</option>`);
  const mayus = (v) => v[0].toUpperCase() + v.slice(1);
  return html`<form class="tarjeta controles" onSubmit=${(e) => e.preventDefault()} autocomplete="off">
    <${Luz} />
    <label class="campo grilla-sel"><span>Grilla</span>
      <select value=${periodo} onChange=${(e) => cambiarGrilla(e.target.value)}>
        ${opciones.grillas.map((g) => html`<option value=${g.periodo}>${g.nombre}</option>`)}
      </select>
      <small class="fuente">Firmada el ${opciones.firmada.split("-").reverse().join("/")}</small>
    </label>
    <h2>Categoría</h2>
    <div class=${"campo" + r("rama")}><span>Rama</span>
      <div class="segmentos" role="group" aria-label="Rama">
        ${Object.entries(opciones.ramas).map(([k, rama]) => html`<button type="button" aria-pressed=${k === c.rama}
          onClick=${() => { set("rama", k); set("categoria", 0); }}>${rama.nombre}</button>`)}
      </div>
    </div>
    <label class=${"campo" + r("categoria")}><span>Categoría</span>
      <select value=${String(c.categoria)} onChange=${(e) => set("categoria", Number(e.target.value))}>
        <optgroup label="Por antigüedad">${opcionesCat((x) => x.anios !== null)}</optgroup>
        <optgroup label="Por jerarquía">${opcionesCat((x) => x.anios === null)}</optgroup>
      </select>
    </label>
    <${SugerenciaCategoria} opciones=${opciones} c=${c} reales=${reales} ajustarCategoria=${ajustarCategoria} />
    <label class=${"campo" + r("tramo_roe")}><span>ROE del banco (lo publica el BCRA)</span>
      <select value=${String(c.tramo_roe)} onChange=${(e) => set("tramo_roe", Number(e.target.value))}>
        ${opciones.tramos_roe.map((t, i) => html`<option value=${i}>ROE ${t}${i === 0 ? " (no paga)" : ""}</option>`)}
      </select>
    </label>
    <hr class="separa" />
    <h2>Adicionales</h2>
    <label class=${"tilde-campo" + r("cajero")}><input type="checkbox" checked=${c.cajero} onChange=${(e) => set("cajero", e.target.checked)} /> Cajero <small>(función + falla de caja)</small></label>
    <label class=${"tilde-campo" + r("falla_me")}><input type="checkbox" checked=${c.falla_me} onChange=${(e) => set("falla_me", e.target.checked)} /> Falla de caja moneda extranjera</label>
    <label class=${"campo" + r("titulo")}><span>Título</span>
      <select value=${c.titulo} onChange=${(e) => set("titulo", e.target.value)}>
        <option value="">Sin título</option>${opciones.titulos.map((t) => html`<option value=${t}>${mayus(t)}</option>`)}
      </select>
    </label>
    <label class=${"campo" + r("zona")}><span>Zona patagónica</span>
      <select value=${c.zona} onChange=${(e) => set("zona", e.target.value)}>
        <option value="">No corresponde</option>${opciones.zonas.map((t) => html`<option value=${t}>${t}</option>`)}
      </select>
    </label>
    <hr class="separa" />
    <h2>No remunerativos</h2>
    <label class=${"tilde-campo" + r("guarderia")}><input type="checkbox" checked=${c.guarderia} onChange=${(e) => set("guarderia", e.target.checked)} /> Guardería</label>
    <div class=${"campo" + r("conectividad") + r("dias_conectividad")}><span>Conectividad</span>
      <div class="fila2">
        <select value=${c.conectividad} onChange=${(e) => set("conectividad", e.target.value)} aria-label="Conectividad">
          ${Object.entries(opciones.conectividad).map(([k, v]) => html`<option value=${k}>${v}</option>`)}
        </select>
        ${c.conectividad === "diario" && html`<input type="number" min="1" max="4" value=${c.dias_conectividad} aria-label="Días"
          onInput=${(e) => set("dias_conectividad", e.target.value)} />`}
      </div>
    </div>
    <label class=${"tilde-campo" + r("dia_bancario")}><input type="checkbox" checked=${c.dia_bancario} onChange=${(e) => set("dia_bancario", e.target.checked)} /> Día del Bancario <small>(recibo de noviembre)</small></label>
    <hr class="separa" />
    <h2>Descuentos</h2>
    <div class=${"fila2" + r("afiliado") + r("cuota_pct")}>
      <label class="tilde-campo"><input type="checkbox" checked=${c.afiliado} onChange=${(e) => set("afiliado", e.target.checked)} /> Afiliado (cuota sindical)</label>
      <input type="text" inputmode="decimal" value=${c.cuota_pct} disabled=${!c.afiliado} aria-label="Porcentaje de cuota" title="% de cuota sindical"
        onInput=${(e) => set("cuota_pct", e.target.value)} />
    </div>
    <label class=${"campo" + r("ganancias")}><span>Impuesto a las Ganancias (a mano, no se calcula)</span>
      <input type="text" inputmode="decimal" placeholder="0,00" value=${c.ganancias} onInput=${(e) => set("ganancias", e.target.value)} />
    </label>
  </form>`;
}

// ---------- la categoría que dice el recibo (se propone, nunca se aplica sola) ----------
function sugerenciaCategoria(opciones, c, reales) {
  const basico = aNumero(reales.BAS);
  if (basico === null || Number.isNaN(basico)) return null;
  const actual = opciones.ramas[c.rama].categorias[Number(c.categoria)];
  if (actual && Math.abs(actual.basico - basico) < 1) return { ok: true, basico };
  const coinciden = [];
  for (const [clave, r] of Object.entries(opciones.ramas))
    r.categorias.forEach((x, i) => { if (Math.abs(x.basico - basico) < 1) coinciden.push({ rama: clave, i, x, nombreRama: r.nombre }); });
  return { ok: false, basico, actual, coinciden };
}
function SugerenciaCategoria({ opciones, c, reales, ajustarCategoria }) {
  const s = sugerenciaCategoria(opciones, c, reales);
  if (!s) return null;
  if (s.ok) return html`<div class="sugerencia ok"><${Tilde} titulo="Coincide" /> La categoría coincide con el básico del recibo (${pesos(s.basico)}).</div>`;
  if (!s.coinciden.length) return html`<div class="sugerencia">El básico del recibo (${pesos(s.basico)}) no coincide con ninguna categoría de la grilla: elegila a mano.</div>`;
  return html`<div class="sugerencia">
    El básico del recibo (${pesos(s.basico)}) no es el de la categoría elegida${s.actual ? " (" + pesos(s.actual.basico) + ")" : ""}.
    Corresponde a${s.coinciden.length > 1 ? " cualquiera de estas (tienen el mismo básico):" : ":"}
    <div class="opciones-cat">${s.coinciden.map((o) => html`<button type="button" class="boton chico"
      onClick=${() => ajustarCategoria(o.rama, o.i)}>Ajustar al recibo: ${o.nombreRama} · ${o.x.nombre}</button>`)}</div>
  </div>`;
}

// ---------- el recibo esperado y la comparación ----------
function Recibo({ d, error, chequeando, reales, setReales, aplicarAjuste, abrirIA, alternarManual }) {
  if (!d) return html`<div class="tarjeta recibo"><h2>Recibo esperado</h2><p class="fuente">${error || "Calculando…"}</p></div>`;
  const comp = {};
  for (const x of d.comparacion?.renglones || []) comp[x.codigo] = x;
  const otros = d.comparacion?.otros || { renglones: {}, totales: {} };
  const extras = d.comparacion?.extras || [];
  const fuera = (d.comparacion?.renglones || []).filter((x) => x.fuera);
  const conOtros = chequeando && extras.length > 0;
  const t = d.esperado.totales;
  const compT = {};
  for (const x of d.comparacion?.totales || []) compT[x.total] = x;
  let indice = 0;
  const filas = [];
  for (const seccion of Object.keys(SECCIONES)) {
    const propios = d.esperado.renglones.filter((r) => r.seccion === seccion);
    const ajenos = fuera.filter((x) => x.seccion === seccion);
    const suyos = extras.filter((e) => e.seccion === seccion);
    if (!propios.length && !ajenos.length && !suyos.length) continue;
    filas.push(html`<tr class="seccion" key=${"s-" + seccion}><td colspan="5">${SECCIONES[seccion]}</td></tr>`);
    for (const r of propios) filas.push(html`<${Fila} key=${r.codigo} i=${indice++} concepto=${r.concepto} nota=${r.nota}
      supuesto=${r.supuesto} esperado=${r.importe} codigo=${r.codigo} comp=${comp[r.codigo]} otros=${otros.renglones[r.codigo]}
      chequeando=${chequeando} conOtros=${conOtros} reales=${reales} setReales=${setReales} aplicarAjuste=${aplicarAjuste} />`);
    for (const x of ajenos) filas.push(html`<${Fila} key=${"f-" + x.codigo} i=${indice++} concepto=${x.concepto} fuera=${x}
      codigo=${x.codigo} comp=${x} chequeando=${chequeando} conOtros=${conOtros} reales=${reales} setReales=${setReales}
      aplicarAjuste=${aplicarAjuste} />`);
    suyos.forEach((e, j) => filas.push(html`<tr class="fila otro" key=${"o-" + seccion + j} style=${{ "--i": indice++ }}>
      <td>${e.concepto}</td><td class="num">—</td>
      ${chequeando && html`<td class="num">${pesos(e.importe || 0)}</td>`}
      ${conOtros && html`<td class="num otros"><${Numero} valor=${e.importe || 0} /></td>`}
      ${chequeando && html`<td class="num dif sin-chequear" title="No es de convenio: no se compara">sin chequear</td>`}
    </tr>`));
  }
  const total = (nombre, clave, valor, cls, claveOtros) => {
    const x = compT[clave];
    return html`<tr class=${"total-fila " + cls} key=${"t-" + nombre}>
      <td>${nombre}</td><td class="num"><${Numero} valor=${valor} /></td>
      ${chequeando && html`<td class="num">${x ? html`<${Numero} valor=${x.real} destello=${false} />` : ""}</td>`}
      ${conOtros && html`<td class="num otros">${otros.totales[claveOtros || clave] ? html`<${Numero} valor=${otros.totales[claveOtros || clave]} />` : ""}</td>`}
      ${chequeando && html`<${CeldaDif} comp=${x} />`}
    </tr>`;
  };
  return html`<div class=${"tarjeta recibo" + (chequeando ? " chequeando" : "")}>
    <${Luz} />
    <h2>Recibo esperado</h2>
    <p class="aclara">Calcula solo el mes, con la grilla elegida. <b>No contempla</b> retenciones ni reintegros de Ganancias (el importe se carga a mano), ni conceptos de períodos anteriores. Si el recibo trae algo que no es de convenio, va a <b>Otros del recibo</b>: se suma a la par, con sus aportes, sin chequearlo.</p>
    <div class="tabla-scroll">
      <table>
        <thead><tr><th>Concepto</th><th class="num">Convenio</th>
          ${chequeando && html`<th class="num">Recibo leído IA</th>`}
          ${conOtros && html`<th class="num otros">Otros del recibo</th>`}
          ${chequeando && html`<th class="num">Diferencia</th>`}</tr></thead>
        <tbody>
          ${filas}
          ${total("Total remunerativo", "", t.remunerativo, "total", "remunerativo")}
          ${(t.no_remunerativo || otros.totales.no_remunerativo) ? total("Total no remunerativo", "", t.no_remunerativo, "subtotal", "no_remunerativo") : null}
          ${total("Total bruto", "bruto", t.bruto, "total")}
          ${total("Total descuentos", "descuentos", t.descuentos, "subtotal")}
          ${total("Neto a cobrar", "neto", t.neto, "neto")}
        </tbody>
      </table>
    </div>
    ${chequeando && d.comparacion && html`<${Veredicto} comp=${d.comparacion} esperado=${d.esperado} />`}
    <div class="acciones">
      <button type="button" class="boton boton-ia" onClick=${abrirIA}><img src=${ISOTIPO} alt="" width="26" height="26" />Analizar con IA Colm3na</button>
      <button type="button" class="boton suave" aria-pressed=${chequeando} onClick=${alternarManual}>${chequeando ? "Ocultar el recibo real" : "Chequeo manual recibo"}</button>
      ${error && html`<span class="fuente error">${error}</span>`}
    </div>
  </div>`;
}

function Fila({ i, concepto, nota, supuesto, esperado, codigo, comp, otros, fuera, chequeando, conOtros, reales, setReales, aplicarAjuste }) {
  const estado = comp ? { coincide: "ok", leve: "leve", grave: "mal" }[comp.gravedad] || "mal" : "";
  return html`<tr class=${"fila" + (fuera ? " fuera" : "")} style=${{ "--i": Math.min(i, 14) }}>
    <td>${concepto}
      ${fuera ? html`<span class="nota fuera-nota">Está en el recibo y no en la calculadora.${fuera.ajuste ? "" : " " + fuera.como}</span>`
              : nota && html`<span class=${"nota" + (supuesto ? " supuesto" : "")}>${nota}</span>`}
      ${comp && comp.ajuste && html`<div><button type="button" class="ajustar" title="Ajustar la calculadora al recibo"
        onClick=${() => aplicarAjuste(comp.ajuste.campos)}>↳ ${comp.ajuste.texto}</button></div>`}
    </td>
    <td class="num">${fuera ? "—" : html`<${Numero} valor=${esperado} />`}</td>
    ${chequeando && html`<td class="num"><input type="text" inputmode="decimal" class=${"real " + estado}
      aria-label=${"Recibo leído: " + concepto} value=${reales[codigo] ?? ""}
      onInput=${(e) => { const v = e.target.value; setReales((r) => ({ ...r, [codigo]: v })); }} /></td>`}
    ${conOtros && html`<td class="num otros">${otros ? html`<${Numero} valor=${otros} />` : ""}</td>`}
    ${chequeando && html`<${CeldaDif} comp=${comp} />`}
  </tr>`;
}

// Solo el COLOR de la diferencia: rojo más del 1%, amarillo hasta el 1%
// (grilla_bancaria.gravedad); coincidir sigue siendo menos de $ 1.
function CeldaDif({ comp }) {
  if (!comp) return html`<td class="num dif"></td>`;
  const clase = { coincide: "bien", leve: "leve", grave: "mal" }[comp.gravedad] || "mal";
  const espera = comp.esperado + (comp.otros || 0);
  const pct = espera ? " (" + new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(Math.abs(comp.diferencia / espera) * 100) + "%)" : "";
  return html`<td class=${"num dif " + clase} title=${comp.coincide ? "Coincide (tolerancia $ 1)" : "Diferencia" + pct}>
    ${comp.coincide ? html`<${Tilde} key="ok" />` : html`<${Numero} key="dif" valor=${comp.diferencia} dur="--mov-medio" destello=${false} />`}
  </td>`;
}

// ---------- el veredicto: convenio + otros contra el recibo ----------
function Veredicto({ comp, esperado }) {
  const valores = [...comp.renglones, ...comp.totales];
  if (!valores.length) return null;
  const n = comp.distintos;
  const extras = comp.extras || [];
  const netoReal = comp.totales.find((x) => x.total === "neto");
  const netoEsperado = esperado.totales.neto + (comp.otros?.totales?.neto || 0);
  const todoBien = n === 0;
  const segmentos = [...valores.map((x) => ({ g: x.gravedad || (x.coincide ? "coincide" : "grave") })),
    ...extras.map(() => ({ g: "otro" }))];
  return html`<div class=${"veredicto" + (todoBien ? " todo-bien" : "")} role="status">
    <div class="veredicto-cab">
      <div class="veredicto-titulo">
        ${todoBien ? html`<${Tilde} key="vt" titulo="Todo coincide" />` : html`<span class="marca-mal" aria-hidden="true">!</span>`}
        <b>${todoBien ? `Los ${valores.length} valores coinciden con lo que corresponde` : `${n} de ${valores.length} valores no coinciden`}</b>
        <small>tolerancia $ 1${extras.length ? ` · ${extras.length} sin chequear (no son de convenio)` : ""}</small>
      </div>
      ${netoReal && html`<div class="veredicto-neto">
        <div><span>Neto que corresponde</span><b><${Numero} valor=${netoEsperado} dur="--mov-correr" /></b></div>
        <div><span>Neto del recibo</span><b><${Numero} valor=${netoReal.real} dur="--mov-correr" /></b></div>
        <div class=${"neto-dif " + (netoReal.coincide ? "bien" : netoReal.gravedad === "leve" ? "leve" : "mal")}>
          <span>Diferencia</span><b>${netoReal.coincide ? html`<${Tilde} />` : html`<${Numero} valor=${netoReal.diferencia} dur="--mov-correr" />`}</b>
        </div>
      </div>`}
    </div>
    <div class="barra" aria-hidden="true">
      ${segmentos.map((s, i) => html`<span key=${i} class=${"seg " + s.g} style=${{ "--i": Math.min(i, 20) }}></span>`)}
    </div>
  </div>`;
}

// ---------- el análisis con IA ----------
function CajaIA({ ia, iaRef, archivoRef, d, opciones, c, reales, cerrar, aplicarAjuste, ajustarCategoria }) {
  const s = ia.segundos;
  const fase = s < 2 ? 0 : s < 4 ? 1 : 2;
  const mmss = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  const ajustes = new Map();
  for (const x of d?.comparacion?.renglones || []) if (x.ajuste) ajustes.set(JSON.stringify(x.ajuste.campos), x.ajuste);
  return html`<div class="tarjeta ia-caja" ref=${iaRef}>
    <${Luz} />
    <div class="ia-cab">
      <div><h2>Análisis con IA</h2>
        <p class="fuente">Subí el PDF o una foto del recibo: la IA lo lee y completa los importes del recibo real. Revisalos antes de guardar. Usa créditos de la API (queda en Uso de IA de /plataforma); no se guarda el archivo ni el nombre o CUIL.</p></div>
      ${!ia.leyendo && html`<button type="button" class="boton suave" onClick=${() => archivoRef.current.click()}>${ia.resultado ? "Leer otro recibo" : "Elegir archivo"}</button>`}
      <button type="button" class="cerrar" aria-label="Cerrar el análisis con IA" onClick=${cerrar}>×</button>
    </div>
    ${ia.leyendo && html`<div class="ia-cron">
      <div class="ia-aro">
        <svg viewBox="0 0 148 148" aria-hidden="true"><circle class="pista" cx="74" cy="74" r="66" />
          <circle class="avance" cx="74" cy="74" r="66" style=${{ strokeDashoffset: IA_ARO - IA_ARO * ((s % 45) / 45) }} /></svg>
        <div class="centro"><span class="n">${mmss}</span><span class="et">Segundos</span></div>
      </div>
      <div class="ia-fases">${IA_FASES.map((f, i) => html`<div class=${"ia-fase" + (i === fase ? " activa" : i < fase ? " hecha" : "")}><span class="pt"></span><span>${f}</span></div>`)}</div>
      <p class="fuente">Leyendo ${ia.archivo}… suele tardar menos de un minuto.</p>
    </div>`}
    ${ia.resultado && html`<div class="ia-resultado entra">
      <p class=${"aviso " + (ia.resultado.ok ? "bien" : "mal")}>${ia.resultado.titulo}</p>
      ${ia.resultado.items.length > 0 && html`<ul>${ia.resultado.items.map((t) => html`<li>${t}</li>`)}</ul>`}
      <${SugerenciaCategoria} opciones=${opciones} c=${c} reales=${reales} ajustarCategoria=${ajustarCategoria} />
      ${ajustes.size > 0 && html`<div class="sugerencia">Según el recibo, conviene ajustar en la calculadora:
        <ul>${[...ajustes.values()].map((a) => html`<li>${a.texto}</li>`)}</ul>
        <div class="opciones-cat"><button type="button" class="boton chico"
          onClick=${() => [...ajustes.values()].forEach((a) => aplicarAjuste(a.campos))}>Ajustar todo al recibo</button></div>
      </div>`}
    </div>`}
  </div>`;
}

// ---------- lo que se edita del recibo real y guardar el caso ----------
function ReciboReal({ abierto, setAbierto, totReales, setTotReales, extras, setExtras, banco, setBanco, nota, setNota, guardar, aviso }) {
  const cambiarExtra = (id, campo, valor) => setExtras((xs) => xs.map((x) => (x.id === id ? { ...x, [campo]: valor } : x)));
  return html`<div class="tarjeta chequeo entra">
    <${Luz} />
    <h2>Del recibo real</h2>
    <p class="fuente">Al lado de cada renglón va lo que dice el recibo real: lo completa el análisis con IA o se carga a mano.</p>
    <details class="editar-real" open=${abierto} onToggle=${(e) => setAbierto(e.target.open)}>
      <summary>Editar importes del recibo <small>(totales impresos y renglones que la calculadora no tiene)</small></summary>
      <div class="grupo-t">Totales impresos</div>
      <div class="totales-reales">
        ${[["bruto", "Total bruto"], ["descuentos", "Total descuentos"], ["neto", "Neto"]].map(([k, t]) => html`<label class="campo"><span>${t}</span>
          <input type="text" inputmode="decimal" value=${totReales[k]} onInput=${(e) => { const v = e.target.value; setTotReales((x) => ({ ...x, [k]: v })); }} /></label>`)}
      </div>
      <div class="grupo-t">Renglones que la calculadora no tiene</div>
      ${extras.map((x) => html`<div class="extras-fila entra" key=${x.id}>
        <input type="text" maxlength="120" placeholder="Concepto (como figura en el recibo)" value=${x.concepto} onInput=${(e) => cambiarExtra(x.id, "concepto", e.target.value)} />
        <select value=${x.seccion} onChange=${(e) => cambiarExtra(x.id, "seccion", e.target.value)}>
          ${Object.entries(SECCIONES).map(([k, v]) => html`<option value=${k}>${v}</option>`)}</select>
        <input type="text" inputmode="decimal" placeholder="Importe" value=${x.importe} onInput=${(e) => cambiarExtra(x.id, "importe", e.target.value)} />
        <button type="button" class="quitar" aria-label="Quitar renglón" onClick=${() => setExtras((xs) => xs.filter((y) => y.id !== x.id))}>×</button>
      </div>`)}
      <button type="button" class="boton suave" onClick=${() => setExtras((xs) => [...xs, nuevoExtra()])}>+ Agregar renglón</button>
    </details>
    <hr class="separa" />
    <h2>Guardar caso</h2>
    <label class="campo"><span>Banco (opcional)</span><input type="text" maxlength="120" placeholder="Ej.: Banco Nación" value=${banco} onInput=${(e) => setBanco(e.target.value)} /></label>
    <label class="campo"><span>Nota: qué viste, qué está mal, cómo lo llama el banco</span><textarea rows="3" maxlength="4000" value=${nota} onInput=${(e) => setNota(e.target.value)}></textarea></label>
    <p class="fuente">No pongas nombre ni CUIL: el caso es para revisar la cuenta, no a la persona.</p>
    <div class="acciones"><button type="button" class="boton" onClick=${guardar}>Guardar caso</button></div>
    ${aviso && html`<div class=${"aviso entra " + (aviso.ok ? "bien" : "mal")} role="status" key=${aviso.texto}>${aviso.texto}</div>`}
  </div>`;
}

// ---------- casos guardados ----------
function Casos({ casos, recargar, abrir }) {
  const [filtro, setFiltro] = useState("");
  const [abierto, setAbierto] = useState(null);
  const [detalle, setDetalle] = useState(null);
  const [aviso, setAviso] = useState("");
  async function alternar(id) {
    if (abierto === id) { setAbierto(null); return; }
    setAbierto(id); setDetalle(null); setAviso("");
    try { setDetalle(await pedir(API + "/casos/" + id)); } catch (e) { setAviso(e.message); }
  }
  async function cambiarEstado(id, estado) {
    try { await pedir(API + "/casos/" + id + "/estado", { estado }); setAviso("Guardado."); recargar(); }
    catch (e) { setAviso(e.message); }
  }
  const lista = casos.filter((x) => !filtro || x.estado === filtro);
  const lineas = (c) => {
    const dif = c.diferencias || {};
    return [...(dif.renglones || []).map((x) => `${x.concepto}: esperado ${pesos(x.esperado)}, real ${pesos(x.real)}` + (x.coincide ? " ✓" : ` → ${pesos(x.diferencia)}`)),
      ...(dif.totales || []).map((x) => `Total ${x.total}: esperado ${pesos(x.esperado)}, real ${pesos(x.real)}` + (x.coincide ? " ✓" : ` → ${pesos(x.diferencia)}`)),
      ...(dif.extras || []).map((e) => `Otro (${SECCIONES[e.seccion]}): ${e.concepto} ${e.importe === null ? "" : pesos(e.importe)}`)].join("\n");
  };
  return html`<div class="tarjeta">
    <${Luz} />
    <div class="acciones arriba">
      <label class="campo"><span>Estado</span>
        <select value=${filtro} onChange=${(e) => setFiltro(e.target.value)}><option value="">Todos</option>
          ${ESTADOS.map((e) => html`<option value=${e}>${e[0].toUpperCase() + e.slice(1)}</option>`)}</select></label>
      <a class="boton suave" href="/entornos/herramientas/bancaria/casos.csv">Descargar CSV</a>
    </div>
    <div class="tabla-scroll"><table>
      <thead><tr><th>#</th><th>Fecha</th><th>Quién</th><th>Grilla</th><th>Banco</th><th>Categoría</th><th class="num">Distintos</th><th>Estado</th></tr></thead>
      <tbody>
        ${lista.map((x, i) => [
          html`<tr class="fila caso" key=${x.id} tabindex="0" style=${{ "--i": Math.min(i, 14) }} onClick=${() => alternar(x.id)}
            onKeyDown=${(e) => { if (e.key === "Enter") alternar(x.id); }}>
            <td class="num">${x.id}</td><td>${x.creado}</td><td>${x.quien}</td><td>${x.grilla}</td><td>${x.banco || "—"}</td>
            <td>${x.categoria}</td><td class=${"num" + (x.distintos ? " dif mal" : "")}>${x.distintos}</td>
            <td><span class=${"estado " + x.estado}>${x.estado}</span></td></tr>`,
          abierto === x.id && html`<tr class="detalle entra" key=${"d" + x.id}><td colspan="8">
            ${!detalle ? html`<p class="fuente">${aviso || "Cargando…"}</p>` : html`<div class="detalle-caja">
              <div><h3>Diferencias</h3><p>${lineas(detalle) || "Sin valores del recibo real."}</p></div>
              <div><h3>Nota</h3><p>${detalle.nota || "—"}</p>
                <h3>Estado</h3>
                <div class="acciones">
                  <select aria-label="Estado del caso" value=${detalle.estado} onChange=${(e) => cambiarEstado(x.id, e.target.value)}>
                    ${ESTADOS.map((e) => html`<option value=${e}>${e[0].toUpperCase() + e.slice(1)}</option>`)}</select>
                  <button type="button" class="boton suave" onClick=${() => abrir(detalle)}>Abrir en la calculadora</button>
                  <span class="fuente">${aviso}</span>
                </div>
                ${detalle.estado_cambiado && html`<p class="fuente">Último cambio: ${detalle.estado_cambiado} (${detalle.estado_quien})</p>`}
              </div></div>`}
          </td></tr>`,
        ])}
      </tbody>
    </table></div>
    ${!lista.length && html`<p class="vacio">Todavía no hay casos guardados.</p>`}
  </div>`;
}

render(html`<${App} />`, raiz);
