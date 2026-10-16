/* Asistente de trámites (Herramientas de /entornos, PLAN_ASISTENTE_TRAMITES.md).

   Cuatro etapas: el pedido (relato), lo que entendí (la propuesta de la IA
   o del ejemplo), las preguntas una por pantalla, y el resultado. Más dos
   pestañas: los casos guardados y el inventario de brechas.

   La regla de la casa: la IA PROPONE (`/entender`) y el servidor DECIDE
   (`/resolver`, el motor puro). Esta pantalla no sabe qué es una brecha ni
   cómo se arma un circuito: cada cambio de respuesta se manda a `/resolver`
   y se muestra lo que vuelve. Preact escapa todo: acá no hay innerHTML. */
import { render } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import { html } from "asistente/html";
import { Diagrama, Leyenda } from "asistente/circuito";
import { correr, ms, arriba } from "asistente/movimiento";

const API = "/api/entornos/herramientas/asistente";
const raiz = document.getElementById("asistente");
const ISOTIPO = raiz.dataset.isotipo;
const GUARDA = "asistente-tramites-v1";
const ETAPAS = [["inicio", "El pedido"], ["entendi", "Lo que entendí"], ["pregunta", "Preguntas"], ["resultado", "Resultado"]];

async function pedir(url, cuerpo) {
  const r = await fetch(url, cuerpo === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ("Error " + r.status));
  return d;
}

const NUEVO = () => ({ vista: "inicio", qi: 0, relato: "", sindicato_id: "", nombre: "", codigo: "", objetivo: "",
  respuestas: { requisitos: [] }, campos: [], extras: [], dudas: [], de_ia: [], vc: "carriles" });
const clon = (o) => JSON.parse(JSON.stringify(o));
const campoNuevo = (tipo = "texto") => ({ etiqueta: "", tipo, obligatorio: tipo !== "separador", opciones: "", control: "" });

function leerGuardado() {
  try { const g = JSON.parse(localStorage.getItem(GUARDA) || "null"); if (g && g.vista) return Object.assign(NUEVO(), g); } catch (e) { /* sin memoria del navegador */ }
  return NUEVO();
}
function guardar(E) { try { localStorage.setItem(GUARDA, JSON.stringify(E)); } catch (e) { /* idem */ } }

/* La entrada que viaja al motor: lo mismo que el estado, sin lo de pantalla. */
const entradaDe = (E) => ({ relato: E.relato, nombre: E.nombre, codigo: E.codigo, objetivo: E.objetivo,
  respuestas: E.respuestas, campos: E.campos, extras: E.extras, dudas: E.dudas });

const vigente = (p, r) => !p.cuando || p.cuando.en.includes(r[p.cuando.clave]);
const muestraTexto = (t, v) => t && (!t.si || (Array.isArray(t.si) ? t.si.includes(v) : t.si === v));
const etiquetaOp = (p, v) => (Array.isArray(v) ? v : [v]).map((x) => (p.opciones.find((o) => o[0] === x) || [])[1]).filter(Boolean).join(", ");

// ---------------------------------------------------------------- piezas
function Etapas({ vista }) {
  const i = ETAPAS.findIndex((e) => e[0] === vista);
  return html`<div class="etapas">${ETAPAS.map((e, j) => html`<span class=${j < i ? "hecho" : j === i ? "ahora" : ""}>${j + 1} · ${e[1]}</span>`)}</div>`;
}

function Contador({ valor }) {
  const ref = useRef(null);
  useEffect(() => { const el = ref.current; if (!el) return; const desde = typeof el._valor === "number" ? el._valor : 0; correr(el, desde, valor, ms("--mov-cambio")); }, [valor]);
  return html`<span class="n-grande" ref=${ref}>0</span>`;
}

function Sello({ nivel }) {
  return nivel === "ajuste" ? html`<span class="sello s-aj">Ajuste</span>` : nivel === "desarrollo" ? html`<span class="sello s-dv">Desarrollo</span>` : html`<span class="sello s-ok">Configurar</span>`;
}

/* La vista previa: el teléfono del afiliado, como la "Vista del afiliado" del constructor. */
function Telefono({ f, i, tipos }) {
  const campo = (c, k) => {
    if (c.tipo_dato === "separador") return html`<hr class="vp-sep" key=${k} />`;
    const et = html`${c.etiqueta}${c.obligatorio ? " *" : ""}${c.x_pendiente ? html`<span class="vp-pend">pendiente</span>` : null}`;
    const cls = "vp-campo vp-" + (c.ancho || "completo");
    if (c.tipo_dato === "booleano") return html`<div class=${cls} key=${k}><div class="vp-bool"><i></i> ${et}</div></div>`;
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
    <div class="vp-rot">${i ? "Segundo formulario · se manda desde el chat" : "Formulario principal"}</div>
    <div class="vp-marco" role="img" aria-label=${"Vista del afiliado de " + (f.titulo || "")}><div class="vp-pant">
      <div class="vp-car"><div class="tit">${f.titulo || "Trámite"}</div><div class="meta"><span class="cod">${f.codigo || "—"}</span><span class="exp">EXP — se numera al enviar</span></div></div>
      <div class="vp-cuerpo"><div class="vp-grid">${f.campos.length ? f.campos.map(campo) : html`<p style="font-size:12px;color:#5b6478;grid-column:1/-1">Agregá campos para ver la vista previa.</p>`}</div>
        <button type="button" class="vp-probar" tabindex="-1" aria-hidden="true">Probar el formulario</button></div>
    </div></div>
  </div>`;
}

// ---------------------------------------------------------------- la app
function App() {
  const [cat, setCat] = useState(null);
  const [error, setError] = useState("");
  const [pestana, setPestana] = useState(location.hash === "#casos" ? "casos" : location.hash === "#brechas" ? "brechas" : "asistente");
  const [E, setEstado] = useState(leerGuardado);
  const [res, setRes] = useState(null);        // lo que devolvió /resolver
  const [sind, setSind] = useState(null);
  const [estadoIA, setEstadoIA] = useState({ texto: "", clase: "" });
  const [extraIA, setExtraIA] = useState([]);
  const [nota, setNota] = useState("");
  const [guardado, setGuardado] = useState("");
  const [casos, setCasos] = useState(null);
  const [casoAbierto, setCasoAbierto] = useState(null);
  const [inventario, setInventario] = useState(null);
  const debounce = useRef(null);

  const set = (cambios) => setEstado((e) => { const n = typeof cambios === "function" ? cambios(e) : { ...e, ...cambios }; guardar(n); return n; });

  useEffect(() => { pedir(API + "/catalogo").then(setCat).catch((e) => setError(e.message)); }, []);
  useEffect(() => { const h = () => setPestana(location.hash === "#casos" ? "casos" : location.hash === "#brechas" ? "brechas" : "asistente"); addEventListener("hashchange", h); return () => removeEventListener("hashchange", h); }, []);

  // Cada cambio de respuesta va al motor (250 ms después del último): el
  // servidor arma el circuito y las brechas; la pantalla solo muestra.
  useEffect(() => {
    if (!cat) return;
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      pedir(API + "/resolver", { entrada: entradaDe(E), sindicato_id: E.sindicato_id })
        .then((d) => { setRes(d.resultado); setSind(d.sindicato); })
        .catch((e) => setError(e.message));
    }, 250);
  }, [cat, E.relato, E.nombre, E.codigo, E.objetivo, E.respuestas, E.campos, E.extras, E.dudas, E.sindicato_id]);

  useEffect(() => { if (pestana === "casos") cargarCasos(); if (pestana === "brechas") pedir(API + "/brechas").then(setInventario).catch((e) => setError(e.message)); }, [pestana]);

  const cargarCasos = () => pedir(API + "/casos").then((d) => setCasos(d.casos)).catch((e) => setError(e.message));
  const ir = (vista, qi) => { set((e) => ({ ...e, vista, qi: qi === undefined ? e.qi : qi })); arriba(); };
  const preguntas = useMemo(() => (cat ? cat.preguntas.filter((p) => vigente(p, E.respuestas)) : []), [cat, E.respuestas]);

  /* La IA propone, el motor decide: lo que vuelve ya está saneado por el servidor. */
  const aplicarPropuesta = (p, deIA) => set((e) => ({ ...e, nombre: p.nombre, codigo: p.codigo, objetivo: p.objetivo,
    respuestas: p.respuestas, campos: p.campos, dudas: p.dudas, de_ia: deIA ? p.de_ia : [], extras: [], vista: "entendi" }));

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
    } else if (!E.nombre) aplicarPropuesta({ nombre: "", codigo: "", objetivo: "", respuestas: { requisitos: [] }, campos: [campoNuevo()], dudas: [], de_ia: [] }, false);
    else ir("entendi");
    arriba();
  };
  const sumarPreguntas = async () => {
    setEstadoIA({ texto: "Pensando…", clase: "" });
    try {
      const d = await pedir(API + "/preguntas-extra", { entrada: entradaDe(E), sindicato_id: E.sindicato_id });
      if (!d.disponible) { setEstadoIA({ texto: "La IA no está configurada en este entorno.", clase: "mal" }); return; }
      setExtraIA(d.preguntas); setEstadoIA({ texto: d.preguntas.length ? "" : "No sumó preguntas nuevas.", clase: "" });
    } catch (e) { setEstadoIA({ texto: e.message, clase: "mal" }); }
  };
  const guardarCaso = async () => {
    setGuardado("Guardando…");
    try {
      const d = await pedir(API + "/casos", { entrada: entradaDe(E), sindicato_id: E.sindicato_id, nota });
      setGuardado(`Caso ${d.id} guardado.`); setNota("");
    } catch (e) { setGuardado(e.message); }
  };
  const copiar = async (texto, ok) => {
    try { await navigator.clipboard.writeText(texto); setGuardado(ok); } catch (e) { setGuardado("No se pudo copiar: seleccioná el texto y usá Ctrl+C."); }
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
      setCasoAbierto(d);
    } catch (e) { setError(e.message); }
  };
  const retomarCaso = (d) => {
    const en = d.entrada;
    set((e) => ({ ...NUEVO(), relato: en.relato, nombre: en.nombre, codigo: en.codigo, objetivo: en.objetivo, respuestas: en.respuestas,
      campos: en.campos, extras: en.extras || [], dudas: en.dudas || [], sindicato_id: en.sindicato ? String(en.sindicato.id) : "", vista: "resultado" }));
    location.hash = ""; setPestana("asistente"); arriba();
  };
  const cambiarEstado = async (id, estado) => {
    try { await pedir(API + `/casos/${id}/estado`, { estado }); cargarCasos(); if (casoAbierto && casoAbierto.id === id) setCasoAbierto({ ...casoAbierto, estado }); } catch (e) { setError(e.message); }
  };

  if (error && !cat) return html`<p class="cargando">${error}</p>`;
  if (!cat) return html`<p class="cargando">Cargando el asistente…</p>`;

  // ---------- pestañas ----------
  const pestanas = [["asistente", "Asistente"], ["casos", "Casos"], ["brechas", "Brechas"]];
  const cabecera = html`<div class="pestanas" role="tablist">
    ${pestanas.map(([k, t]) => html`<button class="pestana" role="tab" aria-selected=${pestana === k} onClick=${() => { location.hash = k === "asistente" ? "" : "#" + k; setPestana(k); }}>${t}${k === "casos" && casos ? html`<span class="cuenta">${casos.length}</span>` : null}</button>`)}
    <${Marca} indice=${pestanas.findIndex(([k]) => k === pestana)} />
  </div>
  ${error ? html`<p class="estado-ia mal">${error}</p>` : null}`;

  if (pestana === "casos") return html`${cabecera}<${Casos} casos=${casos} abierto=${casoAbierto} abrir=${abrirCaso} cerrar=${() => setCasoAbierto(null)} retomar=${retomarCaso} cambiar=${cambiarEstado} estados=${cat.estados_caso} brechas=${cat.brechas} />`;
  if (pestana === "brechas") return html`${cabecera}<${Brechas} inv=${inventario} catalogo=${cat.brechas} />`;

  // ---------- el asistente ----------
  const vistas = { inicio: Inicio, entendi: Entendi, pregunta: Pregunta, resultado: Resultado };
  const Vista = vistas[E.vista] || Inicio;
  return html`${cabecera}<${Etapas} vista=${E.vista} />
    <div class="vista" key=${E.vista + E.qi}>
      <${Vista} E=${E} set=${set} ir=${ir} cat=${cat} res=${res} sind=${sind} preguntas=${preguntas} estadoIA=${estadoIA}
        analizar=${analizar} sinIA=${sinIA} sumarPreguntas=${sumarPreguntas} extraIA=${extraIA}
        nota=${nota} setNota=${setNota} guardarCaso=${guardarCaso} guardado=${guardado} copiar=${copiar} descargar=${descargar}
        nuevo=${() => { setExtraIA([]); setGuardado(""); set(NUEVO()); arriba(); }} />
    </div>`;
}

/* La marca de la pestaña activa se desliza por debajo. */
function Marca({ indice }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const botones = el.parentElement.querySelectorAll(".pestana"); const b = botones[indice]; if (!b) return;
    el.style.width = b.offsetWidth + "px"; el.style.translate = b.offsetLeft + "px 0";
  }, [indice]);
  return html`<i class="pestana-marca" ref=${ref}></i>`;
}

// ---------------------------------------------------------------- etapa 1: el pedido
function Inicio({ E, set, cat, estadoIA, analizar, sinIA }) {
  const corto = E.relato.trim().length < 40;
  return html`<section class="tarjeta">
    <div class="contador">Paso 1</div>
    <h2>Contá qué necesita el sindicato</h2>
    <p class="ayuda">Escribilo como te lo contaron: qué quieren resolver, quién lo pide, qué datos y papeles piden, quién lo revisa y cómo termina. Sin nombres de personas. Lo que escribís acá manda sobre cualquier otra fuente.</p>
    <div class="dos">
      <label class="campo"><span>Sindicato</span>
        <select value=${E.sindicato_id} onChange=${(e) => set({ sindicato_id: e.target.value })}>
          <option value="">Todavía no está en Colm3na</option>
          ${cat.sindicatos.map((s) => html`<option value=${String(s.id)}>${s.nombre}</option>`)}
        </select>
        <span class="nota">Con el sindicato elegido, el asistente dice qué módulos y áreas ya existen y cuáles faltan.</span>
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
        ${cat.ia ? html`<button class="boton boton-ia" type="button" disabled=${corto || estadoIA.texto === "Leyendo el relato…"} onClick=${analizar}><img src=${ISOTIPO} width="26" height="26" alt="" />Analizar con IA Colm3na</button>` : null}
      </div>
    </div>
  </section>`;
}

// ---------------------------------------------------------------- etapa 2: lo que entendí
function Entendi({ E, set, ir, cat, preguntas }) {
  const r = E.respuestas;
  const p = (k) => cat.preguntas.find((x) => x.clave === k);
  const et = (k) => { const v = r[k]; if (!v || (Array.isArray(v) && !v.length)) return ""; return etiquetaOp(p(k), v); };
  const fila = (t, v, i) => html`<div style=${`--i:${i}`}><dt>${t}</dt><dd class=${v ? "" : "vacio"}>${v || "Lo vemos en las preguntas"}</dd></div>`;
  const deIA = E.de_ia.length > 0;
  return html`<section class="tarjeta">
    <div class="contador">Paso 2 · ${deIA ? "Propuesta de la IA" : E.nombre ? "Propuesta de ejemplo" : "Sin propuesta"}</div>
    <h2>${E.nombre ? "Esto entendí" : "Arrancamos de cero"}</h2>
    <p class="ayuda">${E.nombre ? "Todavía no es una conclusión. Ahora vienen las preguntas: lo que ya está propuesto aparece marcado y se confirma con un clic." : "No hay propuesta previa. Las preguntas arman el trámite paso a paso."}</p>
    <label class="campo"><span>Nombre del trámite, como lo va a ver el afiliado</span>
      <input type="text" value=${E.nombre} placeholder="Kit escolar 2027" onInput=${(e) => set({ nombre: e.target.value, codigo: "" })} /></label>
    ${E.nombre ? html`<dl class="entendi">
      ${fila("Para qué sirve", E.objetivo, 0)}
      ${fila("Quién lo pide", et("quien"), 1)}
      ${fila("Quién lo revisa", [et("atiende"), r.area].filter(Boolean).join(" · "), 2)}
      ${fila("Cómo termina", [et("fin"), r.lugar].filter(Boolean).join(" · "), 3)}
      ${fila("Datos que se piden", E.campos.length ? `${E.campos.filter((c) => c.tipo !== "separador").length} preguntas, ${E.campos.filter((c) => c.tipo === "archivo").length} de documentación` : "", 4)}
    </dl>` : null}
    ${E.dudas.length ? html`<div class="grupo"><b>Lo que no quedó claro en el relato</b><ul class="dudas">${E.dudas.map((d) => html`<li>${d}</li>`)}</ul><p class="nota">Va a quedar en las preguntas pendientes del final.</p></div>` : null}
    <div class="acciones"><button class="boton suave" type="button" onClick=${() => ir("inicio")}>← Volver al relato</button>
      <button class="boton" type="button" onClick=${() => { if (!E.campos.length) set({ campos: [campoNuevo()] }); ir("pregunta", 0); }}>Empezar las preguntas (${preguntas.length}) →</button></div>
  </section>`;
}

// ---------------------------------------------------------------- etapa 3: una pregunta por pantalla
function Pregunta({ E, set, ir, cat, res, preguntas }) {
  const qi = Math.min(E.qi, preguntas.length - 1);
  const p = preguntas[qi];
  if (!p) return null;
  const r = E.respuestas;
  const deIA = E.de_ia.includes(p.clave);
  const responder = (valor) => set((e) => {
    const rr = { ...e.respuestas };
    if (p.multiple) {
      let v = new Set(rr[p.clave] || []);
      v.has(valor) ? v.delete(valor) : v.add(valor);
      if (p.excluyente) { if (valor === p.excluyente && v.has(valor)) v = new Set([p.excluyente]); else if (v.has(valor)) v.delete(p.excluyente); }
      rr[p.clave] = [...v];
    } else rr[p.clave] = valor;
    return { ...e, respuestas: rr, de_ia: e.de_ia.filter((k) => k !== p.clave) };
  });
  const texto = (clave, valor) => set((e) => ({ ...e, respuestas: { ...e.respuestas, [clave]: valor } }));
  let cuerpo;
  if (p.actores) cuerpo = html`<${Actores} E=${E} set=${set} res=${res} />`;
  else if (p.campos) cuerpo = html`<${Campos} E=${E} set=${set} cat=${cat} />`;
  else {
    const sel = (v) => (p.multiple ? (r[p.clave] || []).includes(v) : r[p.clave] === v);
    const nMarc = p.multiple ? (r[p.clave] || []).filter((x) => x !== p.excluyente).length : 0;
    cuerpo = html`
      ${p.multiple ? html`<div class="multi-nota"><b>VARIAS RESPUESTAS</b><span>${nMarc ? nMarc + (nMarc === 1 ? " marcada" : " marcadas") : "Ninguna marcada todavía"}</span>${p.excluyente ? html`<span>«${(p.opciones.find((o) => o[0] === p.excluyente) || ["", ""])[1].split(":")[0]}» desmarca las demás.</span>` : null}</div>` : null}
      <div class="opciones" role=${p.multiple ? "group" : "radiogroup"} aria-label=${p.titulo}>
        ${p.opciones.map(([k, t], j) => html`<label class=${"op" + (sel(k) ? " sel" : "") + (p.excluyente === k ? " excl" : "")} style=${`--i:${j}`}>
          <input type=${p.multiple ? "checkbox" : "radio"} name="op" value=${k} checked=${sel(k)} onChange=${() => responder(k)} />
          <span class="t">${t}</span>${deIA && sel(k) ? html`<span class="marca-ia">Propuesto</span>` : null}</label>`)}
      </div>
      ${muestraTexto(p.texto, r[p.clave]) ? html`<label class="campo"><span>${p.texto.rotulo}</span><input type="text" value=${r[p.texto.clave] || ""} placeholder=${p.texto.ejemplo} onInput=${(e) => texto(p.texto.clave, e.target.value)} /></label>` : null}
      ${muestraTexto(p.texto2, r[p.clave]) ? html`<label class="campo"><span>${p.texto2.rotulo}</span><input type="text" value=${r[p.texto2.clave] || ""} placeholder=${p.texto2.ejemplo} onInput=${(e) => texto(p.texto2.clave, e.target.value)} /></label>` : null}`;
  }
  const respondida = p.actores ? true : p.campos ? E.campos.some((c) => c.etiqueta.trim()) : p.multiple ? (r[p.clave] || []).length : !!r[p.clave];
  return html`<section class="tarjeta">
    <div class="contador">Pregunta ${qi + 1} de ${preguntas.length}${deIA ? " · la IA propuso una respuesta" : ""}</div>
    <div class="barra"><i style=${`scale:${(qi + 1) / preguntas.length} 1`}></i></div>
    <h2>${p.titulo}</h2><p class="ayuda">${p.ayuda}</p>
    ${cuerpo}
    <div class="acciones"><button class="boton suave" type="button" onClick=${() => (qi ? ir("pregunta", qi - 1) : ir("entendi"))}>← ${qi ? "Anterior" : "Lo que entendí"}</button>
      <div class="der">${respondida ? null : html`<span class="estado-ia">Sin responder: queda como pendiente</span>`}
        <button class="boton" type="button" onClick=${() => (qi < preguntas.length - 1 ? ir("pregunta", qi + 1) : ir("resultado"))}>${qi === preguntas.length - 1 ? "Ver el resultado →" : "Siguiente →"}</button></div></div>
  </section>`;
}

function Actores({ E, set, res }) {
  const c = res && res.circuito;
  const tareas = c ? c.nodos.filter((n) => n.tipo === "tarea" && !/^x\d/.test(n.carril)) : [];
  const base = c ? c.carriles.filter((l) => !/^x\d/.test(l.k)) : [];
  const extra = (i, f, v) => set((e) => { const ex = clon(e.extras); ex[i][f] = v; return { ...e, extras: ex }; });
  return html`
    <div class="tabla-wrap"><table><thead><tr><th>Actor</th><th>Qué hace</th><th>Usa Colm3na</th></tr></thead><tbody>
      ${base.map((l, i) => html`<tr class="fila" style=${`--i:${i}`}><td><b>${l.nombre}</b></td><td>${c.nodos.filter((n) => n.carril === l.k && n.tipo === "tarea").map((n) => n.texto).join(" · ")}</td><td>${l.colm3na ? "Sí" : "No"}</td></tr>`)}
    </tbody></table></div>
    <p class="nota">Salen de tus respuestas. Para cambiarlos, volvé a la pregunta que corresponde.</p>
    <b>Agregar a alguien que falta</b>
    ${E.extras.length ? html`<div class="tabla-wrap"><table><thead><tr><th>Actor</th><th>Qué hace</th><th>Después de</th><th>Dato que recibe</th><th>Usa Colm3na</th><th></th></tr></thead><tbody>
      ${E.extras.map((x, i) => html`<tr key=${i}>
        <td style="min-width:150px"><input type="text" aria-label="Actor" value=${x.nombre} placeholder="Auditoría" onInput=${(e) => extra(i, "nombre", e.target.value)} /></td>
        <td style="min-width:170px"><input type="text" aria-label="Qué hace" value=${x.hace} placeholder="Controla el padrón" onInput=${(e) => extra(i, "hace", e.target.value)} /></td>
        <td style="min-width:170px"><select aria-label="Después de" value=${x.despues} onChange=${(e) => extra(i, "despues", e.target.value)}>${tareas.map((n) => html`<option value=${n.id}>${n.texto}</option>`)}</select></td>
        <td style="min-width:150px"><input type="text" aria-label="Dato que recibe" value=${x.dato} placeholder="opcional" onInput=${(e) => extra(i, "dato", e.target.value)} /></td>
        <td><input type="checkbox" aria-label="Usa Colm3na" checked=${x.colm3na} onChange=${(e) => extra(i, "colm3na", e.target.checked)} /></td>
        <td><button class="quitar" type="button" aria-label="Quitar" onClick=${() => set((e) => ({ ...e, extras: e.extras.filter((_, j) => j !== i) }))}>✕</button></td></tr>`)}
    </tbody></table></div>` : null}
    <div><button class="boton suave chico" type="button" onClick=${() => set((e) => ({ ...e, extras: [...e.extras, { nombre: "", hace: "", despues: "rev", dato: "", colm3na: false }] }))}>Agregar actor</button></div>`;
}

function Campos({ E, set, cat }) {
  const conOpc = cat.con_opciones;
  const cambiar = (i, f, v) => set((e) => {
    const cs = clon(e.campos); const c = cs[i]; c[f] = v;
    if (f === "tipo") { if (c.tipo === "archivo" && !c.opciones) c.opciones = cat.extensiones_default; if (!conOpc.includes(c.tipo) && c.tipo !== "archivo") c.opciones = ""; if (c.tipo === "separador") c.obligatorio = false; }
    return { ...e, campos: cs };
  });
  return html`
    <div class="tabla-wrap"><table><thead><tr><th>Pregunta</th><th>Tipo</th><th>Oblig.</th><th>Opciones o archivos</th><th>Control</th><th></th></tr></thead><tbody>
      ${E.campos.map((c, i) => html`<tr key=${i} class="fila" style=${`--i:${i}`}>
        <td style="min-width:200px"><input type="text" aria-label=${"Pregunta " + (i + 1)} value=${c.etiqueta} onInput=${(e) => cambiar(i, "etiqueta", e.target.value)} /></td>
        <td style="min-width:150px"><select aria-label="Tipo" value=${c.tipo} onChange=${(e) => cambiar(i, "tipo", e.target.value)}>${Object.entries(cat.tipos).map(([k, v]) => html`<option value=${k}>${v}</option>`)}</select></td>
        <td><input type="checkbox" aria-label="Obligatorio" checked=${c.obligatorio} disabled=${c.tipo === "separador"} onChange=${(e) => cambiar(i, "obligatorio", e.target.checked)} /></td>
        <td style="min-width:170px"><input type="text" aria-label="Opciones" value=${c.opciones} placeholder=${conOpc.includes(c.tipo) ? "separadas por coma" : c.tipo === "archivo" ? cat.extensiones_default : "—"} disabled=${!(conOpc.includes(c.tipo) || c.tipo === "archivo")} onInput=${(e) => cambiar(i, "opciones", e.target.value)} /></td>
        <td style="min-width:170px"><select aria-label="Control" value=${c.control} onChange=${(e) => cambiar(i, "control", e.target.value)}>${Object.entries(cat.controles).map(([k, v]) => html`<option value=${k}>${v}${cat.control_brecha[k] ? " · hoy no existe" : ""}</option>`)}</select></td>
        <td><button class="quitar" type="button" aria-label="Quitar" onClick=${() => set((e) => ({ ...e, campos: e.campos.filter((_, j) => j !== i) }))}>✕</button></td></tr>`)}
    </tbody></table></div>
    <div><button class="boton suave chico" type="button" disabled=${E.campos.length >= cat.max_campos} onClick=${() => set((e) => ({ ...e, campos: [...e.campos, campoNuevo()] }))}>Agregar pregunta</button></div>`;
}

// ---------------------------------------------------------------- etapa 4: el resultado
function Resultado({ E, set, ir, cat, res, sind, sumarPreguntas, extraIA, estadoIA, nota, setNota, guardarCaso, guardado, copiar, descargar, nuevo }) {
  if (!res) return html`<p class="cargando">Armando el resultado…</p>`;
  const principal = res.formularios[0];
  const nCampos = principal.campos.filter((c) => c.tipo_dato !== "separador").length;
  const prep = res.preparar;
  const vc = E.vc || "carriles";
  let i = 0;
  const sec = (titulo, cuerpo, cab) => html`<section class="tarjeta" style=${`--i:${i++}`}>${cab || html`<h3>${titulo}</h3>`}${cuerpo}</section>`;
  const itemB = (b, k) => html`<div class=${"item " + (b.nivel === "ajuste" ? "aj" : "dv")} key=${b.clave} style=${`--i:${k}`}>
    <b>${b.titulo}<span class="tam">· ${b.tam}</span></b>
    <p><b>Por qué:</b> ${b.por_que}</p><p><b>Mientras tanto:</b> ${b.provisorio}</p><p><b>Recomendación:</b> ${b.recomendacion}</p></div>`;
  return html`<div class="res">
    <section class="tarjeta res-cab" style="--i:0"><div class="contador">Resultado${sind ? " · " + sind.nombre : ""}</div><h2>${res.nombre || "Trámite sin nombre"}</h2><p class="ayuda" style="margin:0">${res.objetivo}</p></section>

    ${sec("El circuito", html`
      ${vc === "estados" ? html`<div class="estados">${res.estados.map((e, k) => html`<div class=${"est" + (e.estado === "terminado" ? " fin" : "")} style=${`--i:${k}`}><div class="pto"><b></b><i></i></div>
          <div class="cuerpo"><div class="nom">${e.nombre}</div><div class="burbuja"><small>${e.de} · en el chat del trámite</small>${e.mensaje}</div></div></div>`)}</div>
        <p class="nota">Así lo ve el afiliado en el chat de su trámite. Cada cambio de estado va con un mensaje, en un solo acto.</p>`
      : html`<p class="nota">Un carril por actor. Se lee de izquierda a derecha, del inicio al fin. Arriba de cada acción, el estado en que queda el expediente.</p>
        <div class="diagrama"><${Diagrama} circuito=${res.circuito} estados=${cat.estados} /></div><${Leyenda} />`}`,
      html`<div class="sec-cab"><h3>El circuito</h3><div class="segmentos" role="group" aria-label="Vista del circuito">
        <button type="button" aria-pressed=${vc !== "estados"} onClick=${() => set({ vc: "carriles" })}>Diagrama de flujo</button>
        <button type="button" aria-pressed=${vc === "estados"} onClick=${() => set({ vc: "estados" })}>Lo que ve el afiliado</button></div></div>`)}

    ${sec("Quién hace qué", html`<div class="tabla-wrap"><table><thead><tr><th>Actor</th><th>Usa Colm3na</th><th>Qué hace</th><th>Qué necesita</th></tr></thead><tbody>
      ${res.quien_hace_que.map((q, k) => html`<tr class="fila" style=${`--i:${k}`}><td><b>${q.actor}</b></td><td>${q.usa_colm3na ? "Sí" : "No"}</td><td>${q.hace}</td><td>${q.necesita}</td></tr>`)}</tbody></table></div>`)}

    ${sec("Qué datos circulan", html`<div class="tabla-wrap"><table><thead><tr><th>Dato</th><th>De</th><th>A</th><th>Por dónde</th></tr></thead><tbody>
      ${res.datos.map((d, k) => html`<tr class="fila" style=${`--i:${k}`}><td>${d.dato}</td><td>${d.de}</td><td>${d.a}</td><td>${d.canal}</td></tr>`)}</tbody></table></div>
      <p class="nota">Lo que va «fuera de Colm3na» queda sin registro en el expediente: conviene acordar el canal con el sindicato.</p>`)}

    ${sec("Instrucción para crear el formulario", html`<ol class="instr">
      ${res.instruccion.pasos.map((p) => html`<li key=${p.clave}>${p.ruta ? html`En <span class="ruta">${p.ruta}</span>, ` : null}${p.texto}
        ${p.clave === "crear" ? html`<div class="tabla-wrap" style="margin-top:8px"><table><thead><tr><th>#</th><th>Pregunta</th><th>Tipo</th><th>Oblig.</th><th>Opciones / archivos</th><th>Control</th></tr></thead><tbody>
          ${principal.campos.map((c, k) => html`<tr class="fila" style=${`--i:${k}`}><td class="mono">${k + 1}</td><td>${c.etiqueta || "(raya)"}</td><td>${cat.tipos[c.tipo_dato]}</td><td>${c.tipo_dato === "separador" ? "—" : c.obligatorio ? "Sí" : "No"}</td><td class="mono">${c.opciones || c.tipos_archivo_permitidos || "—"}</td>
            <td>${c.validaciones.length ? c.validaciones.map((v) => v.mensaje).join(" ") : c.x_pendiente ? html`<span class="sello s-aj">Pendiente</span> ${c.x_pendiente}` : "—"}</td></tr>`)}</tbody></table></div>` : null}</li>`)}
      </ol>
      <div class="acciones"><span class="nota">${nCampos} preguntas en el formulario principal.</span><div class="der"><button class="boton suave chico" type="button" onClick=${() => copiar(res.instruccion.texto, "Instrucción copiada.")}>Copiar instrucción</button></div></div>`)}

    ${sec("Así queda el formulario", html`<p class="nota">La misma «Vista del afiliado» que muestra el constructor de Trámites al terminar de crearlo. En cada sindicato toma su marca. La etiqueta <span class="vp-pend">pendiente</span> marca un control que todavía no existe; no aparece en el formulario real.</p>
      <div class="vp-fila">${res.formularios.map((f, k) => html`<${Telefono} f=${f} i=${k} tipos=${cat.tipos} key=${f.clave} />`)}</div>`)}

    ${sec("Antes de crearlo", html`
      <div class="grupo"><h4><span class="sello s-ok">Configurar</span> Sin programar${sind ? "" : " · elegí el sindicato para verificar qué existe"}</h4>
        ${prep.configurar.map((x, k) => html`<div class=${"item ok " + x.estado} key=${k} style=${`--i:${k}`}><b>${x.titulo}${x.estado !== "sin_verificar" ? html`<span class=${"estado-cfg " + x.estado}>${x.estado === "existe" ? "ya existe" : "falta"}</span>` : null}</b><p>${x.detalle}</p></div>`)}</div>
      ${prep.ajuste.length ? html`<div class="grupo"><h4><span class="sello s-aj">Ajuste</span> Se arranca igual con una salida provisoria</h4>${prep.ajuste.map(itemB)}</div>` : null}
      ${prep.desarrollo.length ? html`<div class="grupo"><h4><span class="sello s-dv">Desarrollo</span> Se arranca con la salida provisoria; la solución definitiva requiere programar</h4>${prep.desarrollo.map(itemB)}</div>` : null}`)}

    ${sec("Preguntas pendientes para el sindicato", html`
      ${res.pendientes.length || extraIA.length ? html`<ol class="preguntas">${res.pendientes.map((p, k) => html`<li key=${k}>${p}</li>`)}${extraIA.map((p, k) => html`<li class="extra" key=${"x" + k}>${p}</li>`)}</ol>` : html`<p class="nota">No quedaron preguntas abiertas.</p>`}
      ${cat.ia ? html`<div class="acciones"><span class="nota">¿Querés que la IA sume preguntas sobre casos borde?</span><div class="der"><span class="estado-ia ${estadoIA.clase}" role="status">${estadoIA.texto}</span><button class="boton suave chico" type="button" onClick=${sumarPreguntas}>Sumar preguntas con IA</button></div></div>` : null}`)}

    ${sec("Para importar en Colm3na", html`
      <p class="nota">Formato <span class="mono">colm3na.tramite v1</span>. Cada campo tiene la misma forma que guarda hoy el constructor. Las áreas van por nombre: el importador las busca en el sindicato y, si falta alguna, no importa y la informa. Lo marcado con <span class="mono">x_</span> no se importa todavía.</p>
      <pre class="json">${JSON.stringify(res.json, null, 2)}</pre>
      <label class="campo"><span>Nota para el caso (opcional)</span><input type="text" value=${nota} placeholder="Qué falta acordar con el sindicato, qué se probó…" onInput=${(e) => setNota(e.target.value)} /></label>
      <div class="acciones"><button class="boton suave" type="button" onClick=${() => ir("pregunta", 0)}>← Volver a las preguntas</button>
        <div class="der"><span class="estado-ia" role="status">${guardado}</span>
          <button class="boton suave" type="button" onClick=${() => copiar(JSON.stringify(res.json, null, 2), "JSON copiado.")}>Copiar JSON</button>
          <button class="boton suave" type="button" onClick=${descargar}>Descargar JSON</button>
          <button class="boton" type="button" onClick=${guardarCaso}>Guardar caso</button></div></div>`)}
    <div class="acciones"><span></span><button class="boton-link" type="button" onClick=${nuevo}>Relevar otro trámite</button></div>
  </div>`;
}

// ---------------------------------------------------------------- casos
function Casos({ casos, abierto, abrir, cerrar, retomar, cambiar, estados, brechas }) {
  if (!casos) return html`<p class="cargando">Cargando los casos…</p>`;
  return html`<section class="tarjeta vista">
    <div class="sec-cab"><h3>Casos guardados</h3><a class="boton suave chico" href="/entornos/herramientas/asistente/casos.csv">Descargar CSV</a></div>
    ${casos.length ? html`<div class="tabla-wrap"><table><thead><tr><th>#</th><th>Creado</th><th>Trámite</th><th>Sindicato</th><th>Brechas</th><th>Estado</th><th>Quién</th></tr></thead><tbody>
      ${casos.map((c, k) => html`<tr class="caso fila" key=${c.id} style=${`--i:${k}`} onClick=${() => abrir(c.id)}>
        <td class="mono">${c.id}</td><td class="mono">${c.creado}</td><td><b>${c.nombre || "(sin nombre)"}</b>${c.nota ? html`<span class="nota"> · ${c.nota}</span>` : null}</td><td>${c.sindicato || "—"}</td>
        <td><div class="chips">${c.brechas.map((b) => html`<span class=${"chip " + (brechas[b] && brechas[b].nivel === "desarrollo" ? "dv" : "aj")}>${brechas[b] ? brechas[b].titulo : b}</span>`)}</div></td>
        <td><span class=${"estado " + c.estado}>${c.estado}</span></td><td>${c.quien}</td></tr>`)}
    </tbody></table></div>` : html`<p class="vacio">Todavía no hay casos guardados.</p>`}
    ${abierto ? html`<div class="grupo item" style="--i:0">
      <div class="sec-cab"><b>Caso ${abierto.id} · ${abierto.nombre}</b><div class="der">
        <select value=${abierto.estado} onChange=${(e) => cambiar(abierto.id, e.target.value)}>${estados.map((s) => html`<option value=${s}>${s}</option>`)}</select>
        <button class="boton chico" type="button" onClick=${() => retomar(abierto)}>Abrir en el asistente</button>
        <button class="boton suave chico" type="button" onClick=${cerrar}>Cerrar</button></div></div>
      <p class="nota">${abierto.entrada.relato}</p>
      <pre class="json">${JSON.stringify(abierto.resultado.json, null, 2)}</pre>
    </div>` : null}
  </section>`;
}

// ---------------------------------------------------------------- brechas
function Brechas({ inv, catalogo }) {
  if (!inv) return html`<p class="cargando">Contando las brechas…</p>`;
  const max = Math.max(1, ...inv.brechas.map((b) => b.casos));
  return html`<section class="tarjeta vista">
    <div class="sec-cab"><h3>Lo que los sindicatos piden y Colm3na no tiene</h3><span class="nota"><${Contador} valor=${inv.casos} /> casos relevados</span></div>
    <p class="nota">Cada brecha del catálogo del asistente, con cuántos trámites relevados la pidieron (sin los descartados) y de qué sindicatos. Cuando una se desarrolla, se saca del catálogo y deja de aparecer acá.</p>
    <div class="tabla-wrap"><table><thead><tr><th>Brecha</th><th>Nivel</th><th>Esfuerzo</th><th>Trámites</th><th></th><th>Sindicatos</th><th>Último</th><th>BACKLOG</th></tr></thead><tbody>
      ${inv.brechas.map((b, k) => html`<tr class="fila" key=${b.clave} style=${`--i:${k}`}>
        <td><b>${b.titulo}</b>${b.tramites.length ? html`<span class="nota">${b.tramites.map((t) => t.nombre + (t.sindicato ? " (" + t.sindicato + ")" : "")).join(" · ")}</span>` : null}</td>
        <td><${Sello} nivel=${b.nivel} /></td><td class="mono">${b.tam}</td><td class="mono">${b.casos}</td>
        <td><div class="inv-barra"><i class=${b.nivel === "desarrollo" ? "dv" : "aj"} style=${`scale:${b.casos / max} 1`}></i></div></td>
        <td>${b.sindicatos.join(", ") || "—"}</td><td class="mono">${b.ultimo ? b.ultimo.slice(0, 10) : "—"}</td><td class="nota">${b.backlog || "—"}</td></tr>`)}
    </tbody></table></div>
    ${inv.resueltas.length ? html`<p class="nota">Ya resueltas (siguen en casos viejos): ${inv.resueltas.map((r) => `${r.clave} (${r.casos})`).join(", ")}.</p>` : null}
  </section>`;
}

render(html`<${App} />`, raiz);
