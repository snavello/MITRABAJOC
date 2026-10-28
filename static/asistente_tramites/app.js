/* Asistente de trámites (Herramientas de /entornos, PLAN_ASISTENTE_TRAMITES_V2.md).

   Una hoja de trabajo, como el constructor de Trámites: a la izquierda el
   riel con «Nuevo trámite», los cuatro pasos del trámite abierto y la lista
   de los trámites ya tratados; al centro la hoja del paso; a la derecha,
   fija, la vista del afiliado. Cuatro pasos: el relato, lo que entendí (las
   doce respuestas como frases con su selector, y lo que no quedó claro como
   dudas con opciones o con texto), los datos y el veredicto (las seis
   preguntas con respuesta, importar al sindicato como borrador, guardar).

   La regla de la casa: la IA PROPONE (`/entender`) y el servidor DECIDE
   (`/resolver`, el motor puro; `/importar`, el importador). Esta pantalla no
   sabe qué es una brecha ni cómo se arma un circuito ni un veredicto: cada
   cambio se manda a `/resolver` y se muestra lo que vuelve. Preact escapa
   todo: acá no hay innerHTML. */
import { render } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import { html } from "asistente/html";
import { Diagrama, Leyenda } from "asistente/circuito";
import { correr, ms, arriba } from "asistente/movimiento";

const API = "/api/entornos/herramientas/asistente";
const raiz = document.getElementById("asistente");
const ISOTIPO = raiz.dataset.isotipo;
const GUARDA = "asistente-tramites-v2";
const PASOS = [["relato", "El relato", "Cómo lo contó el sindicato"], ["entendi", "Lo que entendí", "Confirmar o corregir"],
  ["datos", "Los datos", "Las preguntas del formulario"], ["veredicto", "El veredicto", "Importar o preparar"]];
const MIN_RELATO = 40;

async function pedir(url, cuerpo) {
  const r = await fetch(url, cuerpo === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ("Error " + r.status));
  return d;
}

const NUEVO = () => ({ vista: "relato", caso_id: null, relato: "", sindicato_id: "", nombre: "", codigo: "", objetivo: "",
  respuestas: { requisitos: [] }, campos: [], extras: [], dudas: [], aclaraciones: [], de_ia: [], recomendadas: [], vc: "carriles", nota: "" });
const clon = (o) => JSON.parse(JSON.stringify(o));
const campoNuevo = (tipo = "texto") => ({ etiqueta: "", tipo, obligatorio: tipo !== "separador", opciones: "", control: "", aclaracion: "", regla: "", formula: "", funcion_nueva: "" });

function leerGuardado() {
  try { const g = JSON.parse(localStorage.getItem(GUARDA) || "null"); if (g && g.vista) return Object.assign(NUEVO(), g); } catch (e) { /* sin memoria del navegador */ }
  return NUEVO();
}
function guardar(E) { try { localStorage.setItem(GUARDA, JSON.stringify(E)); } catch (e) { /* idem */ } }

/* La entrada que viaja al motor: lo mismo que el estado, sin lo de pantalla. */
const entradaDe = (E) => ({ relato: E.relato, nombre: E.nombre, codigo: E.codigo, objetivo: E.objetivo,
  respuestas: E.respuestas, campos: E.campos, extras: E.extras, dudas: E.dudas, aclaraciones: E.aclaraciones });

const vigente = (p, r) => !p.cuando || p.cuando.en.includes(r[p.cuando.clave]);
const muestraTexto = (t, v) => t && (!t.si || (Array.isArray(t.si) ? t.si.includes(v) : t.si === v));
const etiquetaOp = (p, v) => (Array.isArray(v) ? v : [v]).map((x) => (p.opciones.find((o) => o[0] === x) || [])[1]).filter(Boolean).join(", ");
const nPreguntas = (campos) => campos.filter((c) => c.tipo !== "separador" && (c.etiqueta || "").trim()).length;

/* Qué pasos ya están hechos, para el riel. */
function estadoPasos(E) {
  return { relato: E.relato.trim().length >= MIN_RELATO, entendi: !!E.nombre.trim(), datos: nPreguntas(E.campos) > 0, veredicto: !!E.caso_id };
}

// ---------------------------------------------------------------- piezas
function Contador({ valor }) {
  const ref = useRef(null);
  useEffect(() => { const el = ref.current; if (!el) return; const desde = typeof el._valor === "number" ? el._valor : 0; correr(el, desde, valor, ms("--mov-cambio")); }, [valor]);
  return html`<span class="n-grande" ref=${ref}>0</span>`;
}

function Sello({ nivel }) {
  return nivel === "ajuste" ? html`<span class="sello s-aj">Ajuste</span>` : nivel === "desarrollo" ? html`<span class="sello s-dv">Desarrollo</span>` : html`<span class="sello s-ok">Configurar</span>`;
}

function Ayuda({ texto }) {
  return html`<span class="ayuda-g" tabindex="0" role="note" aria-label=${texto}><i>?</i><span class="ayuda-globo">${texto}</span></span>`;
}

const VEREDICTO_ROTULO = { importar: "Se puede importar", manual: "A mano, guiado", prerrequisito: "Falta preparar", desarrollo: "Necesita desarrollo",
  formulario_nuevo: "Otro formulario antes", sin_sindicato: "Sin sindicato", sin_campos: "Sin preguntas" };

/* La vista previa: el teléfono del afiliado, como la "Vista del afiliado" del constructor. */
function Telefono({ f, i }) {
  const campo = (c, k) => {
    if (c.tipo_dato === "separador") return html`<hr class="vp-sep" key=${k} />`;
    const et = html`${c.etiqueta}${c.obligatorio ? " *" : ""}${c.x_pendiente ? html`<span class="vp-pend">pendiente</span>` : null}`;
    const cls = "vp-campo vp-" + (c.ancho || "completo");
    if (c.tipo_dato === "booleano") return html`<div class=${cls} key=${k}><div class="vp-bool"><i></i> ${et}</div></div>`;
    // Extraído del padrón (el nombre y el CUIL de quien lo pide): viene completo.
    if (c.tipo_dato === "calculado") { const ing = (c.validaciones || []).find((v) => v.ingreso) || {}; return html`<div class=${cls} key=${k}><label>${et}</label><div class="vp-in vp-calc">${ing.trae === "nombre" ? "Pérez, Juan" : ing.trae === "cuil" ? "20111111112" : "se completa solo"}</div></div>`; }
    const ops = (c.opciones || "").split(",").map((o) => o.trim()).filter(Boolean);
    let x;
    if (c.tipo_dato === "opcion_unica" || c.tipo_dato === "multiple") x = (ops.length ? ops : ["(sin opciones cargadas)"]).map((o) => html`<div class="vp-op"><i class=${c.tipo_dato === "multiple" ? "c" : "r"}></i> ${o}</div>`);
    else if (c.tipo_dato === "seleccion") x = html`<div class="vp-in ph">${ops.length ? "Elegí una opción" : "(sin opciones cargadas)"} ▾</div>`;
    else if (c.tipo_dato === "fecha") x = html`<div class="vp-in ph">dd/mm/aaaa</div>`;
    else if (c.tipo_dato === "archivo") x = html`<span class="vp-arch">📎 Elegir archivo</span>`;
    else if (c.tipo_dato === "numero") x = html`<div class="vp-in ph">Ej: 1234</div>`;
    else x = html`<div class="vp-in ph">Texto</div>`;
    return html`<div class=${cls} key=${k}><label>${et}</label>${x}</div>`;
  };
  return html`<div class="vp-col">
    <div class="vp-rot">${i ? "Segundo formulario · se manda desde el chat" : "Así lo ve el afiliado"}</div>
    <div class="vp-marco" role="img" aria-label=${"Vista del afiliado de " + (f.titulo || "")}><div class="vp-pant">
      <div class="vp-car"><div class="tit">${f.titulo || "Trámite"}</div><div class="meta"><span class="cod">${f.codigo || "—"}</span><span class="exp">EXP — se numera al enviar</span></div></div>
      <div class="vp-cuerpo"><div class="vp-grid">${f.campos.length ? f.campos.map(campo) : html`<p class="vp-vacio">Las preguntas aparecen acá a medida que se cargan.</p>`}</div>
        <button type="button" class="vp-probar" tabindex="-1" aria-hidden="true">Enviar</button></div>
    </div></div>
  </div>`;
}

// ---------------------------------------------------------------- la app
function App() {
  const [cat, setCat] = useState(null);
  const [error, setError] = useState("");
  const [panel, setPanel] = useState(location.hash === "#brechas" ? "brechas" : "tramite");
  const [E, setEstado] = useState(leerGuardado);
  const [res, setRes] = useState(null);        // lo que devolvió /resolver
  const [sind, setSind] = useState(null);
  const [estadoIA, setEstadoIA] = useState({ texto: "", clase: "" });
  const [aviso, setAviso] = useState("");
  const [casos, setCasos] = useState(null);
  const [inventario, setInventario] = useState(null);
  const [importacion, setImportacion] = useState(null);   // el ensayo o el resultado de importar
  const debounce = useRef(null);

  const set = (cambios) => setEstado((e) => { const n = typeof cambios === "function" ? cambios(e) : { ...e, ...cambios }; guardar(n); return n; });

  useEffect(() => { pedir(API + "/catalogo").then(setCat).catch((e) => setError(e.message)); cargarCasos(); }, []);
  useEffect(() => { const h = () => setPanel(location.hash === "#brechas" ? "brechas" : "tramite"); addEventListener("hashchange", h); return () => removeEventListener("hashchange", h); }, []);

  // Cada cambio va al motor (250 ms después del último): el servidor arma
  // el circuito, las brechas y el veredicto; la pantalla solo muestra.
  useEffect(() => {
    if (!cat) return;
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      pedir(API + "/resolver", { entrada: entradaDe(E), sindicato_id: E.sindicato_id })
        .then((d) => { setRes(d.resultado); setSind(d.sindicato); })
        .catch((e) => setError(e.message));
    }, 250);
  }, [cat, E.relato, E.nombre, E.codigo, E.objetivo, E.respuestas, E.campos, E.extras, E.dudas, E.aclaraciones, E.sindicato_id]);

  useEffect(() => { if (panel === "brechas") pedir(API + "/brechas").then(setInventario).catch((e) => setError(e.message)); }, [panel]);

  const cargarCasos = () => pedir(API + "/casos").then((d) => setCasos(d.casos)).catch((e) => setError(e.message));
  const ir = (vista) => { set({ vista }); setImportacion(null); arriba(); };
  const abrirTramite = () => { location.hash = ""; setPanel("tramite"); };

  /* La IA propone, el motor decide: lo que vuelve ya está saneado por el servidor. */
  const aplicarPropuesta = (p, deIA) => set((e) => ({ ...e, nombre: p.nombre, codigo: p.codigo, objetivo: p.objetivo,
    respuestas: p.respuestas, campos: p.campos, dudas: p.dudas, aclaraciones: [], de_ia: deIA ? p.de_ia : [], recomendadas: p.recomendadas || [],
    extras: [], vista: "entendi" }));

  const analizar = async () => {
    setEstadoIA({ texto: "Leyendo el relato…", clase: "" });
    try {
      const d = await pedir(API + "/entender", { relato: E.relato, sindicato_id: E.sindicato_id });
      if (!d.disponible) { setEstadoIA({ texto: "La IA no está configurada en este entorno. Seguí sin IA.", clase: "mal" }); return; }
      aplicarPropuesta(d.propuesta, true);
      setEstadoIA({ texto: "", clase: "" });
      arriba();
    } catch (e) { setEstadoIA({ texto: e.message, clase: "mal" }); }
  };
  const sinIA = () => {
    if (E.relato.trim() === cat.ejemplo.relato.trim()) {
      pedir(API + "/resolver", { entrada: { ...cat.ejemplo.propuesta, relato: E.relato }, sindicato_id: E.sindicato_id })
        .then((d) => aplicarPropuesta({ ...d.entrada, de_ia: [] }, false)).catch((e) => setError(e.message));
    } else if (!E.nombre) {
      // Sin propuesta, el motor igual contesta con las recomendadas: se piden saneadas.
      pedir(API + "/resolver", { entrada: { nombre: "", respuestas: {}, campos: [campoNuevo()] }, sindicato_id: E.sindicato_id })
        .then((d) => aplicarPropuesta({ ...d.entrada, de_ia: [] }, false)).catch((e) => setError(e.message));
    } else ir("entendi");
    arriba();
  };
  const guardarCaso = async () => {
    setAviso("Guardando…");
    try {
      const cuerpo = { entrada: entradaDe(E), sindicato_id: E.sindicato_id, nota: E.nota };
      const d = E.caso_id ? await pedir(API + `/casos/${E.caso_id}`, cuerpo) : await pedir(API + "/casos", cuerpo);
      set({ caso_id: d.id });
      setAviso(E.caso_id ? "Guardado." : `Guardado como trámite ${d.id}.`);
      cargarCasos();
      return d.id;
    } catch (e) { setAviso(e.message); return null; }
  };
  const importar = async (ensayo) => {
    setImportacion({ cargando: true });
    try {
      let caso_id = E.caso_id;
      if (!ensayo && !caso_id) caso_id = await guardarCaso();
      const d = await pedir(API + "/importar", { entrada: entradaDe(E), sindicato_id: E.sindicato_id, ensayo, caso_id });
      setImportacion(d);
      if (!ensayo) { setAviso("Importado como borrador."); cargarCasos(); }
    } catch (e) { setImportacion({ error: e.message }); }
  };
  const copiar = async (texto, ok) => {
    try { await navigator.clipboard.writeText(texto); setAviso(ok); } catch (e) { setAviso("No se pudo copiar: seleccioná el texto y usá Ctrl+C."); }
  };
  const descargar = () => {
    const blob = new Blob([JSON.stringify(res.json, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `tramite-${(E.codigo || "nuevo").toLowerCase()}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  const abrirCaso = async (id) => {
    try {
      const d = await pedir(API + `/casos/${id}`);
      const en = d.entrada;
      set(() => ({ ...NUEVO(), caso_id: d.id, relato: en.relato, nombre: en.nombre, codigo: en.codigo, objetivo: en.objetivo, respuestas: en.respuestas,
        campos: en.campos, extras: en.extras || [], dudas: en.dudas || [], aclaraciones: en.aclaraciones || [], recomendadas: en.recomendadas || [],
        sindicato_id: en.sindicato ? String(en.sindicato.id) : "", nota: d.nota || "", vista: "veredicto" }));
      setImportacion(null); setAviso(""); abrirTramite(); arriba();
    } catch (e) { setError(e.message); }
  };
  const nuevo = () => { setAviso(""); setImportacion(null); set(NUEVO()); abrirTramite(); arriba(); };
  const cambiarEstado = async (id, estado) => {
    try { await pedir(API + `/casos/${id}/estado`, { estado }); cargarCasos(); } catch (e) { setError(e.message); }
  };

  if (error && !cat) return html`<p class="cargando">${error}</p>`;
  if (!cat) return html`<p class="cargando">Cargando el asistente…</p>`;

  const hechos = estadoPasos(E);
  const principal = res && res.formularios[0];
  const vistas = { relato: Relato, entendi: Entendi, datos: Datos, veredicto: Veredicto };
  const Vista = vistas[E.vista] || Relato;
  const indicePaso = Math.max(0, PASOS.findIndex((p) => p[0] === E.vista));

  return html`<div class="hoja-layout">
    <aside class="riel">
      <button class="boton nuevo" type="button" onClick=${nuevo}>+ Nuevo trámite</button>
      <nav class="riel-pasos" aria-label="Pasos">
        ${PASOS.map(([k, t, sub], j) => html`<button type="button" class=${"riel-paso" + (panel === "tramite" && E.vista === k ? " actual" : "") + (hechos[k] ? " hecho" : "")}
          onClick=${() => { abrirTramite(); ir(k); }} aria-current=${panel === "tramite" && E.vista === k ? "step" : null}>
          <span class="num">${j + 1}</span><span><b>${t}</b><small>${sub}</small></span></button>`)}
      </nav>
      <div class="riel-tramites">
        <div class="riel-tit"><b>Trámites tratados</b>${casos ? html`<span class="cuenta">${casos.length}</span>` : null}</div>
        ${!casos ? html`<p class="nota">Cargando…</p>` : !casos.length ? html`<p class="nota">Todavía ninguno. El primero se guarda desde el veredicto.</p>`
          : html`<ul class="lista-tramites">${casos.map((c) => html`<li key=${c.id}>
            <button type="button" class=${"tramite-item" + (E.caso_id === c.id ? " abierto" : "")} onClick=${() => abrirCaso(c.id)}>
              <b>${c.nombre || "(sin nombre)"}</b>
              <small>${c.sindicato || "sin sindicato"}${c.importaciones && c.importaciones.length ? " · importado" : ""}</small>
              <span class=${"v-chip v-" + (c.veredicto || "sin")}>${VEREDICTO_ROTULO[c.veredicto] || c.estado}</span>
            </button></li>`)}</ul>`}
        <div class="riel-pie">
          <a href="#brechas" class=${"boton-link" + (panel === "brechas" ? " activo" : "")} onClick=${(ev) => { ev.preventDefault(); location.hash = "#brechas"; setPanel("brechas"); }}>Lo que Colm3na no tiene todavía</a>
          <a href="/entornos/herramientas/asistente/casos.csv" class="boton-link">Descargar CSV</a>
        </div>
      </div>
    </aside>
    <div class="ct-area">
      ${error ? html`<p class="estado-ia mal">${error}</p>` : null}
      ${panel === "brechas" ? html`<${Brechas} inv=${inventario} />`
        : html`<div class="hoja" key=${E.vista}>
          <div class="hoja-cab"><span class="contador">Paso ${indicePaso + 1} de ${PASOS.length}</span>${E.caso_id ? html`<span class="contador suave">Trámite ${E.caso_id}</span>` : null}${sind ? html`<span class="contador suave">${sind.nombre}</span>` : null}</div>
          <${Vista} E=${E} set=${set} ir=${ir} cat=${cat} res=${res} sind=${sind} estadoIA=${estadoIA} analizar=${analizar} sinIA=${sinIA}
            guardarCaso=${guardarCaso} aviso=${aviso} copiar=${copiar} descargar=${descargar} importar=${importar} importacion=${importacion}
            cambiarEstado=${cambiarEstado} casos=${casos} />
        </div>`}
    </div>
    <aside class="ct-der">
      ${principal ? html`<${Telefono} f=${principal} i=${0} />` : html`<p class="nota">La vista del afiliado aparece acá.</p>`}
      ${res && res.formularios.length > 1 ? res.formularios.slice(1).map((f, k) => html`<${Telefono} f=${f} i=${k + 1} key=${f.clave} />`) : null}
      ${res && res.veredicto && E.vista !== "veredicto" ? html`<div class="der-veredicto">
        <div class="riel-tit"><b>Hasta ahora</b></div>
        <p class=${"v-titular v-" + res.veredicto.conclusion}>${res.veredicto.titular}</p>
        <button type="button" class="boton-link" onClick=${() => ir("veredicto")}>Ver el veredicto</button></div>` : null}
    </aside>
  </div>`;
}

// ---------------------------------------------------------------- paso 1: el relato
function Relato({ E, set, cat, estadoIA, analizar, sinIA }) {
  const corto = E.relato.trim().length < MIN_RELATO;
  return html`<section class="paso">
    <h2>Contá el trámite como te lo contó el sindicato</h2>
    <p class="ayuda">Qué quieren resolver, quién lo pide, qué datos y papeles piden, quién lo revisa y cómo termina. Sin nombres de personas. Lo que escribís acá manda sobre cualquier otra fuente.</p>
    <div class="dos">
      <label class="campo"><span>Sindicato <${Ayuda} texto="Con el sindicato elegido, el asistente verifica qué áreas, módulos, listas y formularios ya existen, y puede importar el trámite." /></span>
        <select value=${E.sindicato_id} onChange=${(e) => set({ sindicato_id: e.target.value })}>
          <option value="">Todavía no está en Colm3na</option>
          ${cat.sindicatos.map((s) => html`<option value=${String(s.id)}>${s.nombre}</option>`)}
        </select>
      </label>
      <label class="campo"><span>El relato</span>
        <textarea value=${E.relato} onInput=${(e) => set({ relato: e.target.value })} placeholder="Ej.: Queremos que el afiliado pida la ayuda por nacimiento. Manda la partida y el DNI del bebé, lo revisa Acción Social de su seccional y se paga por transferencia…"></textarea>
      </label>
    </div>
    <div class="acciones">
      <button class="boton-link" type="button" onClick=${() => set({ relato: cat.ejemplo.relato })}>Cargar el ejemplo del kit escolar</button>
      <div class="der">
        <span class="estado-ia ${estadoIA.clase}" role="status">${estadoIA.texto}</span>
        <button class="boton suave" type="button" onClick=${sinIA}>Seguir sin IA</button>
        ${cat.ia ? html`<button class="boton boton-ia" type="button" disabled=${corto || estadoIA.texto === "Leyendo el relato…"} onClick=${analizar}><img src=${ISOTIPO} width="24" height="24" alt="" />Leer con IA</button>` : null}
      </div>
    </div>
  </section>`;
}

// ---------------------------------------------------------------- paso 2: lo que entendí
/* Las doce respuestas, agrupadas en frases cortas con su selector. */
const GRUPOS = [
  ["Quién lo pide", ["quien", "requisitos"]],
  ["Quién lo atiende", ["atiende", "aprueba", "segundo"]],
  ["Cómo termina", ["fin", "pago_colm3na", "entrega", "cupo", "tercero", "listado"]],
  ["Cuántas veces y cuándo", ["frecuencia", "ventana"]],
  ["Antes de este trámite", ["previo"]],
];

function Entendi({ E, set, ir, cat }) {
  const r = E.respuestas;
  const todas = cat.preguntas.concat(cat.inferidas);
  const p = (k) => todas.find((x) => x.clave === k);
  const marcar = (clave) => (e) => ({ ...e, de_ia: e.de_ia.filter((k) => k !== clave), recomendadas: e.recomendadas.filter((k) => k !== clave) });
  const responder = (clave, valor) => set((e) => marcar(clave)({ ...e, respuestas: { ...e.respuestas, [clave]: valor } }));
  const texto = (clave, valor) => set((e) => ({ ...e, respuestas: { ...e.respuestas, [clave]: valor } }));
  const origen = (k) => (E.de_ia.includes(k) ? html`<span class="marca-ia" title="Propuesto por la IA desde el relato">IA</span>` : E.recomendadas.includes(k) ? html`<span class="marca-rec" title="Lo más común; cambialo si no es así">supuesto</span>` : null);
  const multi = (q) => {
    const sel = new Set(r[q.clave] || []);
    const toggle = (k) => {
      let v = new Set(sel);
      v.has(k) ? v.delete(k) : v.add(k);
      if (q.excluyente) { if (k === q.excluyente && v.has(k)) v = new Set([q.excluyente]); else if (v.has(k)) v.delete(q.excluyente); }
      responder(q.clave, [...v]);
    };
    return html`<div class="chips-op" role="group" aria-label=${q.titulo}>${q.opciones.map(([k, t]) => html`<button type="button" class=${"chip-op" + (sel.has(k) ? " sel" : "")} aria-pressed=${sel.has(k)} onClick=${() => toggle(k)}>${t}</button>`)}</div>`;
  };
  const fila = (clave) => {
    const q = p(clave);
    if (!q || !vigente(q, r)) return null;
    return html`<div class="frase" key=${clave}>
      <div class="frase-q"><span>${q.titulo}</span>${origen(clave)}<${Ayuda} texto=${q.ayuda} /></div>
      <div class="frase-r">
        ${q.multiple ? multi(q) : html`<select aria-label=${q.titulo} value=${r[clave] || ""} onChange=${(e) => responder(clave, e.target.value)}>${q.opciones.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select>`}
        ${muestraTexto(q.texto, r[clave]) ? html`<input type="text" value=${r[q.texto.clave] || ""} placeholder=${q.texto.ejemplo} aria-label=${q.texto.rotulo} onInput=${(e) => texto(q.texto.clave, e.target.value)} />` : null}
        ${muestraTexto(q.texto2, r[clave]) ? html`<input type="text" value=${r[q.texto2.clave] || ""} placeholder=${q.texto2.ejemplo} aria-label=${q.texto2.rotulo} onInput=${(e) => texto(q.texto2.clave, e.target.value)} />` : null}
      </div>
    </div>`;
  };
  const deIA = E.de_ia.length > 0;
  return html`<section class="paso">
    <h2>${E.nombre ? "Esto entendí" : "Arrancamos de cero"}</h2>
    <p class="ayuda">${deIA ? "Lo marcado con IA salió del relato; lo marcado como supuesto es lo más común y queda así salvo que lo cambies. Nada se pregunta dos veces." : "Cada frase trae lo más común. Corregí lo que no sea así."}</p>
    <div class="dos nombre">
      <label class="campo"><span>Nombre del trámite, como lo ve el afiliado</span>
        <input type="text" value=${E.nombre} placeholder="Kit escolar 2027" onInput=${(e) => set({ nombre: e.target.value, codigo: "" })} /></label>
      <label class="campo"><span>Para qué sirve, en una frase</span>
        <input type="text" value=${E.objetivo} placeholder="El afiliado pide un kit por cada hijo en edad escolar." onInput=${(e) => set({ objetivo: e.target.value })} /></label>
    </div>
    <${Dudas} E=${E} set=${set} cat=${cat} />
    ${GRUPOS.map(([tit, claves]) => { const filas = claves.map(fila).filter(Boolean); return filas.length ? html`<div class="grupo-frases" key=${tit}><h3>${tit}</h3>${filas}</div>` : null; })}
    <div class="acciones"><button class="boton suave" type="button" onClick=${() => ir("relato")}>← El relato</button>
      <button class="boton" type="button" onClick=${() => { if (!E.campos.length) set({ campos: [campoNuevo()] }); ir("datos"); }}>Los datos →</button></div>
  </section>`;
}

/* Lo que el relato no aclaró: cada duda con opciones (un clic la contesta)
   o con texto. Una duda sobre una pregunta del catálogo la responde al
   elegir; una libre queda como aclaración del analista. Sin contestar,
   queda «a confirmar con el sindicato». */
function Dudas({ E, set, cat }) {
  const [textos, setTextos] = useState({});
  if (!E.dudas.length && !E.aclaraciones.length) return null;
  const quitarDuda = (i, e) => ({ ...e, dudas: e.dudas.filter((_, j) => j !== i) });
  const elegir = (i, d, k, t) => set((e) => {
    if (d.sobre) return quitarDuda(i, { ...e, respuestas: { ...e.respuestas, [d.sobre]: k }, de_ia: e.de_ia.filter((x) => x !== d.sobre), recomendadas: e.recomendadas.filter((x) => x !== d.sobre) });
    return quitarDuda(i, { ...e, aclaraciones: [...e.aclaraciones, { pregunta: d.pregunta, respuesta: t }] });
  });
  const contestar = (i, d) => { const t = (textos[i] || "").trim(); if (!t) return; set((e) => quitarDuda(i, { ...e, aclaraciones: [...e.aclaraciones, { pregunta: d.pregunta, respuesta: t }] })); setTextos({ ...textos, [i]: "" }); };
  return html`<div class="dudas-caja">
    ${E.dudas.length ? html`<h3>Lo que no quedó claro <small>${E.dudas.length === 1 ? "una duda" : E.dudas.length + " dudas"} · si no sabés, dejala: queda para confirmar con el sindicato</small></h3>` : null}
    ${E.dudas.map((d, i) => html`<div class="duda" key=${d.pregunta} style=${`--i:${i}`}>
      <p>${d.pregunta}</p>
      ${d.opciones.length ? html`<div class="chips-op">${d.opciones.map(([k, t]) => html`<button type="button" class="chip-op" onClick=${() => elegir(i, d, k, t)}>${t}</button>`)}</div>` : null}
      <div class="duda-texto"><input type="text" value=${textos[i] || ""} placeholder="O contestá con tus palabras" aria-label=${"Respuesta a: " + d.pregunta}
        onInput=${(e) => setTextos({ ...textos, [i]: e.target.value })} onKeyDown=${(e) => { if (e.key === "Enter") contestar(i, d); }} />
        <button type="button" class="boton suave chico" onClick=${() => contestar(i, d)}>Responder</button></div>
    </div>`)}
    ${E.aclaraciones.length ? html`<div class="aclaraciones"><b>Lo que aclaraste</b>
      ${E.aclaraciones.map((a, i) => html`<div class="aclaracion" key=${i}><span><i>${a.pregunta}</i> ${a.respuesta}</span><button type="button" class="quitar" aria-label="Quitar" onClick=${() => set((e) => ({ ...e, aclaraciones: e.aclaraciones.filter((_, j) => j !== i) }))}>✕</button></div>`)}
    </div>` : null}
  </div>`;
}

// ---------------------------------------------------------------- paso 3: los datos
function Datos({ E, set, ir, cat, res }) {
  return html`<section class="paso">
    <h2>Los datos que se le piden</h2>
    <p class="ayuda">Revisá, corregí o agregá. Lo que el sindicato ya sabe del padrón (nombre, CUIL, seccional) no se pide. En «Aclaración y validación» de cada dato: qué es si no es obvio y qué hay que controlar.</p>
    <${Campos} E=${E} set=${set} cat=${cat} />
    <details class="grupo"><summary><b>Alguien más interviene en el circuito</b></summary><${Actores} E=${E} set=${set} res=${res} /></details>
    <div class="acciones"><button class="boton suave" type="button" onClick=${() => ir("entendi")}>← Lo que entendí</button>
      <button class="boton" type="button" onClick=${() => ir("veredicto")}>El veredicto →</button></div>
  </section>`;
}

function Actores({ E, set, res }) {
  const c = res && res.circuito;
  const tareas = c ? c.nodos.filter((n) => n.tipo === "tarea" && !/^x\d/.test(n.carril)) : [];
  const base = c ? c.carriles.filter((l) => !/^x\d/.test(l.k)) : [];
  const extra = (i, f, v) => set((e) => { const ex = clon(e.extras); ex[i][f] = v; return { ...e, extras: ex }; });
  return html`
    <div class="tabla-wrap"><table><thead><tr><th>Quién</th><th>Qué hace</th><th>Usa Colm3na</th></tr></thead><tbody>
      ${base.map((l, i) => html`<tr class="fila" style=${`--i:${i}`}><td><b>${l.nombre}</b></td><td>${c.nodos.filter((n) => n.carril === l.k && n.tipo === "tarea").map((n) => n.texto).join(" · ")}</td><td>${l.colm3na ? "Sí" : "No"}</td></tr>`)}
    </tbody></table></div>
    <p class="nota">Salen de lo que entendí. Para cambiarlos, volvé al paso 2.</p>
    ${E.extras.length ? html`<div class="tabla-wrap"><table><thead><tr><th>Quién</th><th>Qué hace</th><th>Después de</th><th>Dato que recibe</th><th>Usa Colm3na</th><th></th></tr></thead><tbody>
      ${E.extras.map((x, i) => html`<tr key=${i}>
        <td style="min-width:150px"><input type="text" aria-label="Actor" value=${x.nombre} placeholder="Auditoría" onInput=${(e) => extra(i, "nombre", e.target.value)} /></td>
        <td style="min-width:170px"><input type="text" aria-label="Qué hace" value=${x.hace} placeholder="Controla el padrón" onInput=${(e) => extra(i, "hace", e.target.value)} /></td>
        <td style="min-width:170px"><select aria-label="Después de" value=${x.despues} onChange=${(e) => extra(i, "despues", e.target.value)}>${tareas.map((n) => html`<option value=${n.id}>${n.texto}</option>`)}</select></td>
        <td style="min-width:150px"><input type="text" aria-label="Dato que recibe" value=${x.dato} placeholder="opcional" onInput=${(e) => extra(i, "dato", e.target.value)} /></td>
        <td><input type="checkbox" aria-label="Usa Colm3na" checked=${x.colm3na} onChange=${(e) => extra(i, "colm3na", e.target.checked)} /></td>
        <td><button class="quitar" type="button" aria-label="Quitar" onClick=${() => set((e) => ({ ...e, extras: e.extras.filter((_, j) => j !== i) }))}>✕</button></td></tr>`)}
    </tbody></table></div>` : null}
    <div><button class="boton suave chico" type="button" onClick=${() => set((e) => ({ ...e, extras: [...e.extras, { nombre: "", hace: "", despues: "rev", dato: "", colm3na: false }] }))}>Agregar a alguien</button></div>`;
}

function Campos({ E, set, cat }) {
  /* Cada dato es una tarjeta: la pregunta grande, abajo tipo / control /
     opciones / obligatorio, y un renglón plegado "Aclaración y validación"
     que resume lo escrito en chips y, abierto, muestra los cuatro campos
     con su rótulo. Nada se pierde: lo plegado se lee en los chips. */
  const conOpc = cat.con_opciones;
  const [abiertos, setAbiertos] = useState({});
  const [verCat, setVerCat] = useState(false);
  const cambiar = (i, f, v) => set((e) => {
    const cs = clon(e.campos); const c = cs[i]; c[f] = v;
    if (f === "tipo") { if (c.tipo === "archivo" && !c.opciones) c.opciones = cat.extensiones_default; if (!conOpc.includes(c.tipo) && c.tipo !== "archivo") c.opciones = ""; if (c.tipo === "separador") c.obligatorio = false; }
    return { ...e, campos: cs };
  });
  const mover = (i, d) => set((e) => { const cs = clon(e.campos); const j = i + d; if (j < 0 || j >= cs.length) return e; [cs[i], cs[j]] = [cs[j], cs[i]]; return { ...e, campos: cs }; });
  const nombres = (cat.funciones || { sistema: [], listas: [], funciones: [] });
  const sugerencias = [...nombres.sistema.map((d) => d.nombre || "sistema." + d.clave), ...nombres.listas.flatMap((l) => l.columnas.map((x) => "lista." + x.clave)), ...nombres.funciones.map((f) => f.nombre + "(")];
  const DETALLE = [["aclaracion", "Aclaración", "Qué es, de dónde sale, por qué se pide"], ["regla", "Validar", "Qué hay que controlar sobre este dato, en palabras"],
    ["formula", "Validar con fórmula", "Con el catálogo, si se puede"], ["funcion_nueva", "Función a desarrollar", "Si hace falta: nombre y qué devuelve"]];
  const abrirCatalogo = () => { setVerCat(true); requestAnimationFrame(() => { const el = document.getElementById("at-catalogo"); if (el) el.scrollIntoView({ block: "start", behavior: "smooth" }); }); };
  return html`
    <datalist id="at-nombres">${sugerencias.map((x) => html`<option value=${x} />`)}</datalist>
    <div class="cps">
      ${E.campos.map((c, i) => {
        const sep = c.tipo === "separador"; const ab = !!abiertos[i];
        const lleno = DETALLE.filter(([k]) => (c[k] || "").trim());
        return html`<div key=${i} class=${"cp" + (sep ? " sep" : "")} style=${`--i:${i}`}>
          <div class="cp-n"><span>${String(i + 1).padStart(2, "0")}</span><button type="button" class="cp-mover" aria-label="Subir" disabled=${i === 0} onClick=${() => mover(i, -1)}>▲</button><button type="button" class="cp-mover" aria-label="Bajar" disabled=${i === E.campos.length - 1} onClick=${() => mover(i, 1)}>▼</button></div>
          <div class="cp-cuerpo">
            <div class="cp-fila">
              <input class="cp-etq" type="text" aria-label=${"Pregunta " + (i + 1)} value=${c.etiqueta} placeholder=${sep ? "Título del separador" : "La pregunta, como la ve el afiliado"} onInput=${(e) => cambiar(i, "etiqueta", e.target.value)} />
              <button class="quitar" type="button" aria-label="Quitar" onClick=${() => set((e) => ({ ...e, campos: e.campos.filter((_, j) => j !== i) }))}>✕</button>
            </div>
            <div class="cp-fila ctls">
              <label class="cp-ctl"><span>Tipo</span><select aria-label="Tipo" value=${c.tipo} onChange=${(e) => cambiar(i, "tipo", e.target.value)}>${Object.entries(cat.tipos).map(([k, v]) => html`<option value=${k}>${v}</option>`)}</select></label>
              ${sep ? null : html`<label class="cp-ctl"><span>Control</span><select aria-label="Control" value=${c.control} onChange=${(e) => cambiar(i, "control", e.target.value)}>${Object.entries(cat.controles).map(([k, v]) => html`<option value=${k}>${v}${cat.control_brecha[k] ? " · hoy no existe" : ""}</option>`)}</select></label>`}
              ${conOpc.includes(c.tipo) || c.tipo === "archivo" ? html`<label class="cp-ctl crece"><span>${c.tipo === "archivo" ? "Archivos permitidos" : "Opciones, separadas por coma"}</span><input type="text" aria-label="Opciones" value=${c.opciones} placeholder=${c.tipo === "archivo" ? cat.extensiones_default : "Una, otra, otra"} onInput=${(e) => cambiar(i, "opciones", e.target.value)} /></label>` : null}
              ${sep ? null : html`<label class="cp-oblig"><input type="checkbox" aria-label="Obligatorio" checked=${c.obligatorio} onChange=${(e) => cambiar(i, "obligatorio", e.target.checked)} /> Obligatorio</label>`}
            </div>
            ${sep ? null : html`<div class="cp-det">
              <button type="button" class="cp-det-cab" aria-expanded=${ab} onClick=${() => setAbiertos({ ...abiertos, [i]: !ab })}>
                <svg class="cp-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
                <span class="cp-det-tit">Aclaración y validación</span>
                ${ab ? null : lleno.length ? lleno.map(([k, rot]) => html`<span class="cp-chip" title=${c[k]}><b>${rot}</b>${c[k]}</span>`) : html`<span class="cp-det-vacio">opcional</span>`}
              </button>
              ${ab ? html`<div class="cp-det-cuerpo">
                ${DETALLE.map(([k, rot, ayuda]) => html`<label class="cp-ctl" key=${k}><span>${rot} <i>· ${ayuda}</i></span>
                  <input type="text" class=${k === "formula" ? "mono" : ""} list=${k === "formula" ? "at-nombres" : null} placeholder=${k === "formula" ? "anios_entre(lista.fecha_nacimiento, hoy()) <= 12" : ""} aria-label=${rot} value=${c[k] || ""} onInput=${(e) => cambiar(i, k, e.target.value)} /></label>`)}
                <p class="cp-det-pie">La fórmula nombra <code>campo.…</code>, <code>lista.…</code> y <code>sistema.afiliado.…</code>. <button type="button" class="boton-link" onClick=${abrirCatalogo}>Ver los datos y las funciones, con ejemplos</button></p>
              </div>` : null}
            </div>`}
          </div>
        </div>`; })}
    </div>
    <div class="acciones"><div class="der izq"><button class="boton suave chico" type="button" disabled=${E.campos.length >= cat.max_campos} onClick=${() => set((e) => ({ ...e, campos: [...e.campos, campoNuevo()] }))}>+ Agregar pregunta</button>
      <button class="boton suave chico" type="button" onClick=${() => set((e) => ({ ...e, campos: [...e.campos, campoNuevo("separador")] }))}>+ Separador</button></div>
      <button class="boton suave chico" type="button" aria-pressed=${verCat} onClick=${() => setVerCat(!verCat)}>${verCat ? "Ocultar el catálogo" : "Datos y funciones"}</button></div>
    ${verCat ? html`<${Catalogo} cat=${nombres} />` : null}`;
}

/* El catálogo de datos y funciones, con qué devuelve cada uno y un ejemplo:
   sale del código (validaciones_tramite.catalogo_funcion), acá solo se
   dibuja y se filtra. */
function Catalogo({ cat }) {
  const [q, setQ] = useState("");
  const t = q.trim().toLowerCase();
  const pasa = (...xs) => !t || xs.join(" ").toLowerCase().includes(t);
  const comparar = cat.comparar || {};
  const grupos = (cat.grupos || []).map((g) => ({ ...g, items: cat.sistema.filter((d) => d.grupo === g.clave && pasa(d.nombre || "sistema." + d.clave, d.rotulo, d.devuelve, d.ejemplo, d.significa)) })).filter((g) => g.items.length);
  const listas = cat.listas.map((l) => ({ ...l, columnas: l.columnas.filter((x) => pasa("lista." + x.clave, x.rotulo, x.tipo, l.nombre)) })).filter((l) => l.columnas.length);
  const funciones = cat.funciones.filter((f) => pasa(f.nombre, f.ayuda, f.ejemplo, f.significa));
  const tipos = [["booleano", "sí / no"], ["numero", "número"], ["texto", "texto"], ["fecha", "fecha"]].filter(([k, n]) => pasa(k, n, comparar[k]));
  const nada = !grupos.length && !listas.length && !funciones.length && !tipos.length;
  return html`<section class="cat" id="at-catalogo" style="--i:1">
    <div class="cat-cab"><h3>Datos y funciones</h3><input type="search" class="cat-buscar" aria-label="Buscar en el catálogo" placeholder="Buscar: credencial, recibo, fecha, edad…" value=${q} onInput=${(e) => setQ(e.target.value)} /></div>
    <p class="nota">Se escriben como las Reglas de control: <code>+ - * /</code>, comparaciones (<code>${"<= >= < > == !="}</code>), <code>y</code> / <code>o</code> / <code>no</code>, textos entre comillas y fechas AAAA-MM-DD. Los campos del formulario se nombran <code>${"campo.<etiqueta en minúsculas, sin tildes, con guion bajo>"}</code>. Un dato que falta no vale 0: la validación no pasa.</p>
    ${tipos.length ? html`<div class="cat-grupo"><h4>Cómo se compara cada tipo</h4>${tipos.map(([k, n]) => html`<div class="cat-item" key=${k}><code>${n}</code><p>${comparar[k]}</p></div>`)}</div>` : null}
    ${grupos.map((g) => html`<div class="cat-grupo" key=${g.clave}><h4>Sistema · Afiliado · ${g.nombre}</h4>${g.items.map((d) => html`<div class="cat-item" key=${d.clave}><code>${d.nombre || "sistema." + d.clave}</code><span class="cat-tipo">${d.devuelve}</span><p>${d.rotulo}</p><small>Ej.: <code>${d.ejemplo}</code> → ${d.significa}</small></div>`)}</div>`)}
    ${listas.map((l) => html`<div class="cat-grupo" key=${l.clave}><h4>Lista «${l.nombre}» · la fila del afiliado</h4>${l.columnas.map((x) => html`<div class="cat-item" key=${x.clave}><code>lista.${x.clave}</code><span class="cat-tipo">${x.tipo}${x.busqueda ? " · clave" : ""}</span><p>${x.rotulo}</p></div>`)}</div>`)}
    ${funciones.length ? html`<div class="cat-grupo"><h4>Funciones</h4>${funciones.map((f) => html`<div class="cat-item" key=${f.nombre}><code>${f.ayuda}</code><small>Ej.: <code>${f.ejemplo}</code> → ${f.significa}</small></div>`)}</div>` : null}
    ${nada ? html`<p class="vacio">Nada coincide con la búsqueda.</p>` : null}
  </section>`;
}

// ---------------------------------------------------------------- paso 4: el veredicto
function Veredicto({ E, set, ir, cat, res, sind, guardarCaso, aviso, copiar, descargar, importar, importacion, cambiarEstado, casos }) {
  const [abierto, setAbierto] = useState({});
  const [confirmar, setConfirmar] = useState(false);
  if (!res) return html`<p class="cargando">Armando el veredicto…</p>`;
  const v = res.veredicto;
  const principal = res.formularios[0];
  const prep = res.preparar;
  const vc = E.vc || "carriles";
  const caso = casos && E.caso_id ? casos.find((c) => c.id === E.caso_id) : null;
  const puedeImportar = !!sind && nPreguntas(E.campos) > 0;
  const seccion = (clave, titulo, cuerpo, extra) => html`<section class="secc">
    <button type="button" class="secc-cab" aria-expanded=${!!abierto[clave]} onClick=${() => setAbierto({ ...abierto, [clave]: !abierto[clave] })}>
      <svg class="cp-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg><h3>${titulo}</h3>${extra || null}</button>
    ${abierto[clave] ? html`<div class="secc-cuerpo">${cuerpo}</div>` : null}
  </section>`;
  const itemB = (b, k) => html`<div class=${"item " + (b.nivel === "ajuste" ? "aj" : "dv")} key=${b.clave} style=${`--i:${k}`}>
    <b>${b.titulo}<span class="tam">· ${b.tam}</span></b>
    <p><b>Por qué:</b> ${b.por_que}</p><p><b>Mientras tanto:</b> ${b.provisorio}</p><p><b>Recomendación:</b> ${b.recomendacion}</p></div>`;
  const icono = (si) => (si === true ? html`<i class="v-si" aria-label="Sí">✓</i>` : si === false ? html`<i class="v-no" aria-label="No">—</i>` : html`<i class="v-duda" aria-label="Sin verificar">?</i>`);
  return html`<section class="paso">
    <div class="v-cab"><div><h2>${v.titular}</h2><p class="ayuda">${v.resumen}</p></div>
      <div class=${"v-compl v-" + v.complejidad}><small>Desarrollo</small><b>${v.complejidad === "ninguna" ? "no hace falta" : "complejidad " + v.complejidad}</b></div></div>
    <ol class="v-puntos">${v.puntos.map((p, k) => html`<li key=${p.clave} style=${`--i:${k}`}>${icono(p.si)}<div><b>${k + 1}. ${p.pregunta}</b><p>${p.detalle}</p></div></li>`)}</ol>

    <div class="v-acciones">
      <div class="v-importar">
        ${puedeImportar ? html`<button class="boton" type="button" disabled=${importacion && importacion.cargando} onClick=${() => { setConfirmar(false); importar(true); }}>Importar a ${sind.nombre}…</button>`
          : html`<span class="nota">${sind ? "Para importar, el formulario necesita al menos una pregunta." : "Para importar, elegí el sindicato en el paso 1."}</span>`}
        <button class="boton suave" type="button" onClick=${() => setConfirmar(true)}>${E.caso_id ? "Guardar cambios" : "Guardar trámite"}</button>
        <span class="estado-ia" role="status">${aviso}</span>
      </div>
      ${caso ? html`<label class="campo chico"><span>Estado del trámite</span><select value=${caso.estado} onChange=${(e) => cambiarEstado(caso.id, e.target.value)}>${cat.estados_caso.map((s) => html`<option value=${s}>${s}</option>`)}</select></label>` : null}
      <p class="nota v-que-hace"><b>Importar</b> crea el formulario en el panel de ${sind ? sind.nombre : "ese sindicato"} como borrador: antes muestra qué va a crear y pide confirmación. <b>Guardar</b> lo deja en la lista de la izquierda, con relato, respuestas, datos y veredicto, para retomarlo o importarlo después; no toca el sindicato.</p>
    </div>
    ${confirmar ? html`<div class="imp confirmar">
      <h3>${E.caso_id ? "¿Guardar los cambios de este trámite?" : "¿Guardar este trámite?"}</h3>
      <p class="nota">${E.caso_id ? `Se reemplaza lo guardado del trámite ${E.caso_id} con lo que está en pantalla (relato, respuestas, datos y veredicto). ` : "Queda en la lista «Trámites tratados» de la izquierda, para retomarlo, compartirlo o importarlo después. "}No crea nada en el sindicato: eso lo hace «Importar», que pide su propia confirmación.</p>
      <div class="acciones"><button class="boton suave" type="button" onClick=${() => setConfirmar(false)}>Cancelar</button><div class="der"><button class="boton" type="button" onClick=${() => { setConfirmar(false); guardarCaso(); }}>Sí, guardar</button></div></div>
    </div>` : null}
    <label class="campo"><span>Nota para quien lo retome (opcional)</span><input type="text" value=${E.nota} placeholder="Qué falta acordar con el sindicato, qué se probó…" onInput=${(e) => set({ nota: e.target.value })} /></label>
    ${importacion ? html`<${Importacion} imp=${importacion} confirmar=${() => importar(false)} sind=${sind} />` : null}
    ${caso && caso.importaciones.length ? html`<div class="importado-ya"><b>Ya importado</b>${caso.importaciones.map((x, k) => html`<p key=${k}>${x.cuando.slice(0, 16)} por ${x.quien} a ${x.sindicato}: ${x.tipos.map((t) => `«${t.titulo}» (${t.codigo})`).join(", ")}.</p>`)}</div>` : null}

    <div class="secciones">
    ${seccion("circuito", "El circuito", html`
      <div class="segmentos" role="group" aria-label="Vista del circuito">
        <button type="button" aria-pressed=${vc !== "estados"} onClick=${() => set({ vc: "carriles" })}>Diagrama</button>
        <button type="button" aria-pressed=${vc === "estados"} onClick=${() => set({ vc: "estados" })}>Lo que ve el afiliado</button></div>
      ${vc === "estados" ? html`<div class="estados">${res.estados.map((e, k) => html`<div class=${"est" + (e.estado === "terminado" ? " fin" : "")} style=${`--i:${k}`}><div class="pto"><b></b><i></i></div>
          <div class="cuerpo"><div class="nom">${e.nombre}</div><div class="burbuja"><small>${e.de} · en el chat del trámite</small>${e.mensaje}</div></div></div>`)}</div>`
      : html`<div class="diagrama"><${Diagrama} circuito=${res.circuito} estados=${cat.estados} /></div><${Leyenda} />`}
      <div class="tabla-wrap"><table><thead><tr><th>Quién</th><th>Usa Colm3na</th><th>Qué hace</th><th>Qué necesita</th></tr></thead><tbody>
        ${res.quien_hace_que.map((q, k) => html`<tr class="fila" style=${`--i:${k}`}><td><b>${q.actor}</b></td><td>${q.usa_colm3na ? "Sí" : "No"}</td><td>${q.hace}</td><td>${q.necesita}</td></tr>`)}</tbody></table></div>
      <div class="tabla-wrap"><table><thead><tr><th>Dato</th><th>De</th><th>A</th><th>Por dónde</th></tr></thead><tbody>
        ${res.datos.map((d, k) => html`<tr class="fila" style=${`--i:${k}`}><td>${d.dato}</td><td>${d.de}</td><td>${d.a}</td><td>${d.canal}</td></tr>`)}</tbody></table></div>`)}

    ${seccion("preparar", "Antes de publicarlo", html`
      <div class="grupo"><h4><span class="sello s-ok">Configurar</span> Sin programar${sind ? "" : " · elegí el sindicato para verificar qué existe"}</h4>
        ${prep.configurar.map((x, k) => html`<div class=${"item ok " + x.estado} key=${k} style=${`--i:${k}`}><b>${x.titulo}${x.estado !== "sin_verificar" ? html`<span class=${"estado-cfg " + x.estado}>${x.estado === "existe" ? "ya existe" : "falta"}</span>` : null}</b><p>${x.detalle}</p></div>`)}</div>
      ${prep.ajuste.length ? html`<div class="grupo"><h4><span class="sello s-aj">Ajuste</span> Se arranca igual con una salida provisoria</h4>${prep.ajuste.map(itemB)}</div>` : null}
      ${prep.desarrollo.length ? html`<div class="grupo"><h4><span class="sello s-dv">Desarrollo</span> Se arranca con la salida provisoria; lo definitivo requiere programar</h4>${prep.desarrollo.map(itemB)}</div>` : null}`,
      html`<span class="secc-n">${prep.ajuste.length + prep.desarrollo.length ? (prep.ajuste.length + prep.desarrollo.length) + " pendientes" : "todo existe"}</span>`)}

    ${seccion("instruccion", "Para hacerlo a mano en el constructor", html`<ol class="instr">
      ${res.instruccion.pasos.map((p) => html`<li key=${p.clave}>${p.ruta ? html`En <span class="ruta">${p.ruta}</span>, ` : null}${p.texto}
        ${p.clave === "crear" ? html`<div class="tabla-wrap" style="margin-top:8px"><table><thead><tr><th>#</th><th>Pregunta</th><th>Tipo</th><th>Oblig.</th><th>Opciones / archivos</th><th>Control</th></tr></thead><tbody>
          ${principal.campos.map((c, k) => html`<tr class="fila" style=${`--i:${k}`}><td class="mono">${k + 1}</td><td>${c.etiqueta || "(raya)"}${c.x_aclaracion ? html`<span class="nota"> · ${c.x_aclaracion}</span>` : null}</td><td>${cat.tipos[c.tipo_dato]}</td><td>${c.tipo_dato === "separador" ? "—" : c.obligatorio ? "Sí" : "No"}</td><td class="mono">${c.opciones || c.tipos_archivo_permitidos || "—"}</td>
            <td>${c.validaciones.length ? c.validaciones.map((v) => v.formula || v.mensaje).join(" · ") : null}${c.x_pendiente ? html` <span class="sello s-aj">Pendiente</span> ${c.x_pendiente}` : null}${c.x_regla ? html` <span class="sello s-aj">A controlar</span> ${c.x_regla}` : null}${c.x_funcion_nueva ? html` <span class="sello s-dv">Desarrollar</span> ${c.x_funcion_nueva}` : null}${!c.validaciones.length && !c.x_pendiente && !c.x_regla && !c.x_funcion_nueva ? "—" : null}</td></tr>`)}</tbody></table></div>` : null}</li>`)}
      </ol>
      <div class="acciones"><span></span><div class="der"><button class="boton suave chico" type="button" onClick=${() => copiar(res.instruccion.texto, "Instrucción copiada.")}>Copiar instrucción</button></div></div>`)}

    ${seccion("prompt", "Prompt para Code", html`
      <p class="nota">Qué configurar en el panel, qué validar con las funciones que existen y qué función habría que desarrollar. Para pegar en Claude Code o pasarle a quien arma el formulario.</p>
      <pre class="json prompt">${res.prompt}</pre>
      <div class="acciones"><span></span><div class="der"><button class="boton suave chico" type="button" onClick=${() => copiar(res.prompt, "Prompt copiado.")}>Copiar prompt</button></div></div>`)}

    ${seccion("json", "El JSON colm3na.tramite", html`
      <p class="nota">Formato <span class="mono">colm3na.tramite v1</span>: lo mismo que importa el botón de arriba, para guardarlo aparte o llevarlo a otro entorno.</p>
      <pre class="json">${JSON.stringify(res.json, null, 2)}</pre>
      <div class="acciones"><span></span><div class="der"><button class="boton suave chico" type="button" onClick=${() => copiar(JSON.stringify(res.json, null, 2), "JSON copiado.")}>Copiar JSON</button>
        <button class="boton suave chico" type="button" onClick=${descargar}>Descargar JSON</button></div></div>`)}
    </div>
    <div class="acciones"><button class="boton suave" type="button" onClick=${() => ir("datos")}>← Los datos</button></div>
  </section>`;
}

/* El ensayo de la importación (qué haría) y el resultado (qué hizo). */
function Importacion({ imp, confirmar, sind }) {
  if (imp.cargando) return html`<div class="imp"><p class="nota">Preparando la importación…</p></div>`;
  if (imp.error) return html`<div class="imp mal"><p class="estado-ia mal">${imp.error}</p></div>`;
  return html`<div class=${"imp" + (imp.ensayo ? "" : " hecho")}>
    <h3>${imp.ensayo ? `Esto se va a crear en ${sind.nombre}, como borrador` : `Importado a ${sind.nombre} como borrador`}</h3>
    <div class="tabla-wrap"><table><thead><tr><th>Formulario</th><th>Código</th><th>Preguntas</th><th>Destino</th><th>Por seccional</th><th>Pase</th></tr></thead><tbody>
      ${imp.creados.map((c, k) => html`<tr class="fila" key=${c.clave} style=${`--i:${k}`}><td><b>${c.titulo}</b>${c.solo_encadenado ? html`<span class="nota"> · se manda desde el chat</span>` : null}${c.id ? html`<span class="nota"> · id ${c.id}</span>` : null}</td><td class="mono">${c.codigo}</td><td class="mono">${c.preguntas}</td>
        <td>${c.destino.existe ? `${c.destino.area} de ${c.destino.seccional}` : html`<span class="falta">sin destino: falta «${c.destino.area}» en ${c.destino.seccional}</span>`}</td><td class="mono">${c.mapa || "—"}</td><td class="mono">${c.pase || "—"}</td></tr>`)}
    </tbody></table></div>
    ${imp.pendientes.length ? html`<div class="grupo"><b>Queda para terminar en el constructor</b><ul class="pend">${imp.pendientes.map((p) => html`<li>${p}</li>`)}</ul></div>` : html`<p class="nota">No queda nada pendiente: se revisa y se publica desde Trámites.</p>`}
    ${imp.ensayo ? html`<div class="acciones"><span class="nota">Nace inactivo: el afiliado no lo ve hasta que el Super Admin lo publique desde el constructor.</span><div class="der"><button class="boton" type="button" onClick=${confirmar}>Confirmar la importación</button></div></div>`
      : html`<p class="nota">El Super Admin de ${sind.nombre} lo encuentra en Trámites → Crear formularios, marcado «borrador».</p>`}
  </div>`;
}

// ---------------------------------------------------------------- brechas
function Brechas({ inv }) {
  if (!inv) return html`<p class="cargando">Contando las brechas…</p>`;
  const max = Math.max(1, ...inv.brechas.map((b) => b.casos));
  return html`<div class="hoja"><section class="paso">
    <div class="sec-cab"><h2>Lo que los sindicatos piden y Colm3na no tiene</h2><span class="nota"><${Contador} valor=${inv.casos} /> trámites tratados</span></div>
    <p class="ayuda">Cada brecha del catálogo del asistente, con cuántos trámites la pidieron (sin los descartados) y de qué sindicatos. Cuando una se desarrolla, se saca del catálogo y deja de aparecer acá.</p>
    <div class="tabla-wrap"><table><thead><tr><th>Brecha</th><th>Nivel</th><th>Esfuerzo</th><th>Trámites</th><th></th><th>Sindicatos</th><th>Último</th><th>BACKLOG</th></tr></thead><tbody>
      ${inv.brechas.map((b, k) => html`<tr class="fila" key=${b.clave} style=${`--i:${k}`}>
        <td><b>${b.titulo}</b>${b.tramites.length ? html`<span class="nota">${b.tramites.map((t) => t.nombre + (t.sindicato ? " (" + t.sindicato + ")" : "")).join(" · ")}</span>` : null}</td>
        <td><${Sello} nivel=${b.nivel} /></td><td class="mono">${b.tam}</td><td class="mono">${b.casos}</td>
        <td><div class="inv-barra"><i class=${b.nivel === "desarrollo" ? "dv" : "aj"} style=${`scale:${b.casos / max} 1`}></i></div></td>
        <td>${b.sindicatos.join(", ") || "—"}</td><td class="mono">${b.ultimo ? b.ultimo.slice(0, 10) : "—"}</td><td class="nota">${b.backlog || "—"}</td></tr>`)}
    </tbody></table></div>
    ${inv.resueltas.length ? html`<p class="nota">Ya resueltas (siguen en trámites viejos): ${inv.resueltas.map((r) => `${r.clave} (${r.casos})`).join(", ")}.</p>` : null}
  </section></div>`;
}

render(html`<${App} />`, raiz);
