/* Panel Sindical v2: el Asistente del Panel (docs/ASISTENTE_PANEL.md).

   El mismo recorrido que la v1 (static/dashboard.js, "Asistente del Panel"):
   - cada pregunta viaja con la foto del estado (`estadoPlano`) y los últimos
     cuatro intercambios; el historial vive SOLO en memoria, nunca en el
     navegador;
   - si el servidor dice "aplicar", los filtros se vuelcan con la misma
     acción que la dirección ("aplicar" del reductor) y el panel se refresca
     detrás, en silencio: primero se lee la respuesta;
   - cada respuesta que filtra dice dónde está el detalle y trae "Ver en el
     explorador" y "Volver" (restaura la foto previa);
   - homónimos: el admin elige el afiliado con un clic y se aplican los
     filtros pendientes SIN volver al modelo (el padrón no viaja);
   - voz con la Web Speech API del navegador (en Firefox no existe y el
     micrófono ni aparece): lo dictado se envía solo tras 4 segundos, con la
     cuenta a la vista; tocar el texto o escribir la cancela;
   - en el celular el cajón es una hoja inferior que se puede achicar a una
     barra con la última respuesta, para ver el panel cambiar.

   La v2 suma la entrada de cada burbuja (D5); con "reducir movimiento" no
   se mueve nada, salvo el vaivén de la colmena (decisión de Sd, como en la
   v1). Nada se escribe con innerHTML: las respuestas del modelo son texto. */
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { estadoPlano, comoParams } from "panel/estado";

const NOMBRE_TAB = { recibos: "Recibos", tramites: "Trámites", notificaciones: "Notificaciones", consultas: "Consultas" };
const VOZ_SEGUNDOS = 4;
const esMovil = () => window.matchMedia("(max-width: 640px)").matches;
const quieto = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const Reconocedor = window.SpeechRecognition || window.webkitSpeechRecognition || null;

/* La pastilla que abre el Asistente: la misma de la v1 (degradé del
   encabezado, letras doradas, la colmena en vaivén). */
export function BotonAsistente({ modo, setModo, colmena }) {
  const clic = () => {
    if (modo === "mini") { setModo("abierto"); return; }
    setModo(modo === "cerrado" ? "abierto" : "cerrado");
  };
  return html`<button type="button" class="btn-asist" id="btn-asist" aria-controls="asist"
      aria-expanded=${modo !== "cerrado"} title="Asistente del Panel" onClick=${clic}>
    <span class="colmena"><img src=${colmena} alt="" /></span><span class="palabra">Asistente</span>
  </button>`;
}

function saludo(catalogo) {
  const s = catalogo && catalogo.seccionales && catalogo.seccionales[0];
  // El ejemplo cita una seccional real del sindicato, para que sea uno que de verdad funciona.
  return s
    ? "Hola. Decime qué querés ver y aplico los filtros del panel. Por ejemplo: «notificaciones sin leer de " +
      s.nombre + " este mes» o «recibos con diferencias del mes pasado»."
    : "Hola. Decime qué querés ver y aplico los filtros del panel. Por ejemplo: «recibos con diferencias del mes pasado».";
}

/* Ficha del afiliado elegido, con lo que ya devuelve el servidor para la
   pastilla: al modelo no le llega nada del padrón, pero el admin ve acá
   nombre, CUIL, seccional y empresa. */
function Ficha({ af }) {
  if (!af || !af.nombre) return null;
  return html`<div class="ficha-af"><b>${af.nombre}</b>${" · " + [af.cuil, af.seccional ? "Seccional " + af.seccional : "",
    af.empresa].filter(Boolean).join(" · ")}</div>`;
}

function Burbuja({ m, verExplorador, volver, elegir }) {
  const clase = "burb " + m.quien + (m.error ? " error" : "");
  return html`<div class=${clase}>${m.texto}
    ${m.ficha && html`<${Ficha} af=${m.ficha} />`}
    ${m.nota && html`<div class="nota-exp">${m.nota}</div>`}
    ${m.candidatos && html`<div class="candidatos">
      ${m.candidatos.lista.map((c) => html`<button type="button" class="af-item" disabled=${m.candidatos.elegido}
          onClick=${() => elegir(m, c)}>${c.nombre}<small>${[c.cuil, c.seccional, c.empresa].filter(Boolean).join(" · ")}</small></button>`)}
    </div>`}
    ${m.aplicado && html`
      <div class="nota-exp">El detalle, caso por caso, está abajo en el explorador de datos, pestaña ${NOMBRE_TAB[m.aplicado.tab] || m.aplicado.tab}.</div>
      <div class="aplicado"><b>Filtros aplicados</b>
        <button type="button" onClick=${verExplorador}>Ver en el explorador</button>
        <button type="button" disabled=${m.aplicado.restaurado} onClick=${() => volver(m)}>${m.aplicado.restaurado ? "Restaurado" : "Volver"}</button>
      </div>`}
  </div>`;
}

export function Asistente({ modo, setModo, estado, lim, despachar, catalogo, registrarAfiliado }) {
  const [mensajes, setMensajes] = useState([]);
  const [texto, setTexto] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [cuenta, setCuenta] = useState(null);         // segundos para el envío solo, o null
  const [grabando, setGrabando] = useState(false);
  const hist = useRef([]);                            // últimos intercambios, en memoria
  const proximo = useRef(1);
  const caja = useRef(null);
  const hilo = useRef(null);
  const rec = useRef(null);
  // Lo que las funciones de abajo leen en el momento, no en el render que las armó.
  const vivo = useRef({});
  vivo.current = { estado, lim, texto, ocupado };

  const agregar = (m) => setMensajes((l) => l.concat([Object.assign({ id: proximo.current++ }, m)]));
  const cambiar = (id, cambios) => setMensajes((l) => l.map((m) => (m.id === id ? Object.assign({}, m, cambios) : m)));
  const aplicar = (filtros) => despachar({ tipo: "aplicar", params: comoParams(filtros), lim: vivo.current.lim });
  const foto = () => estadoPlano(vivo.current.estado, vivo.current.lim);

  const abierto = modo !== "cerrado";
  // En el celular no se enfoca la caja al abrir: el teclado taparía la hoja.
  useEffect(() => {
    if (modo !== "abierto" || esMovil()) return undefined;
    const id = setTimeout(() => caja.current && caja.current.focus(), 80);
    return () => clearTimeout(id);
  }, [modo]);
  // El hilo baja solo con cada burbuja nueva.
  useEffect(() => { if (hilo.current) hilo.current.scrollTop = hilo.current.scrollHeight; }, [mensajes, ocupado]);
  // La caja crece con el texto, hasta cuatro renglones.
  useLayoutEffect(() => {
    const c = caja.current;
    if (!c) return;
    c.style.height = "auto";
    c.style.height = Math.min(c.scrollHeight, 96) + "px";
  }, [texto]);

  const cancelarCuenta = () => setCuenta(null);

  function preguntar() {
    const pregunta = vivo.current.texto.trim();
    if (!pregunta || vivo.current.ocupado) return;
    cancelarCuenta();
    setTexto("");
    agregar({ quien: "yo", texto: pregunta });
    setOcupado(true);
    vivo.current.ocupado = true;
    const previo = foto();     // para "Volver"
    fetch("/admin/dashboard/asistente", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pregunta, filtros: previo, historial: hist.current.slice(-4) }),
    })
      .then((r) => {
        if (r.status === 403) { location.href = "/admin"; throw new Error("sesion"); }
        return r.json().then((d) => ({ ok: r.ok, d }));
      })
      .then(({ ok, d }) => {
        if (!ok) {
          const detalle = typeof d.detail === "string" ? d.detail : "No pude responder.";
          agregar({ quien: "bot", error: true, texto: detalle + (d.codigo ? "  " + d.codigo : "") });
          return;
        }
        hist.current.push({ pregunta, respuesta: d.respuesta, filtros: d.filtros });
        if (d.candidatos && d.candidatos.length) {
          agregar({ quien: "bot", texto: d.respuesta,
            candidatos: { lista: d.candidatos, pendientes: d.filtros_pendientes || {}, pregunta, elegido: false } });
          return;
        }
        if (d.aplicar && d.filtros) {
          if (d.afiliado) registrarAfiliado(d.afiliado);
          aplicar(d.filtros);
          agregar({ quien: "bot", texto: d.respuesta, ficha: d.afiliado || null,
            aplicado: { tab: d.filtros.tab, previo, restaurado: false } });
        } else {
          // Que se note cuando una respuesta NO tocó el panel.
          agregar({ quien: "bot", texto: d.respuesta, nota: "El panel quedó como estaba." });
        }
      })
      .catch((e) => {
        if (e.message === "sesion") return;
        agregar({ quien: "bot", error: true, texto: "No pude conectarme con el servidor. Probá de nuevo." });
      })
      .then(() => {
        setOcupado(false);
        vivo.current.ocupado = false;
        if (caja.current) caja.current.focus();
      });
  }
  const preguntarRef = useRef(preguntar);
  preguntarRef.current = preguntar;

  // La cuenta regresiva del envío solo, después de dictar.
  useEffect(() => {
    if (cuenta === null) return undefined;
    if (cuenta <= 0) { setCuenta(null); preguntarRef.current(); return undefined; }
    const id = setTimeout(() => setCuenta((c) => (c === null ? null : c - 1)), 1000);
    return () => clearTimeout(id);
  }, [cuenta]);

  const elegir = (m, c) => {
    cambiar(m.id, { candidatos: Object.assign({}, m.candidatos, { elegido: true }) });
    const previo = foto();
    registrarAfiliado(c);
    const filtros = Object.assign({}, m.candidatos.pendientes, { afiliado: c.id });
    aplicar(filtros);
    agregar({ quien: "bot", texto: "Listo, filtré por " + c.nombre + ".", ficha: c,
      aplicado: { tab: filtros.tab, previo, restaurado: false } });
    // En el historial queda solo el id: el nombre no vuelve al modelo.
    hist.current.push({ pregunta: m.candidatos.pregunta,
      respuesta: "Filtré por el afiliado elegido (id " + c.id + ").", filtros });
  };
  const volver = (m) => {
    cambiar(m.id, { aplicado: Object.assign({}, m.aplicado, { restaurado: true }) });
    aplicar(m.aplicado.previo);
  };
  const verExplorador = () => {
    if (esMovil()) setModo("mini");   // si no, la hoja tapa lo que se quiere mostrar
    const p = document.querySelector('[data-panel="explorador"]');
    if (p) p.scrollIntoView({ behavior: quieto() ? "auto" : "smooth", block: "start" });
  };

  const dictar = () => {
    cancelarCuenta();
    if (rec.current) { rec.current.stop(); return; }
    const r = new Reconocedor();
    r.lang = "es-AR"; r.interimResults = false; r.maxAlternatives = 1;
    r.onresult = (e) => {
      const dicho = (e.results[0] && e.results[0][0] ? e.results[0][0].transcript : "").trim();
      if (!dicho) return;
      const previo = vivo.current.texto.trim();
      setTexto((previo ? previo + " " : "") + dicho);   // sin focus(): en el celular abriría el teclado
      setCuenta(VOZ_SEGUNDOS);
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        agregar({ quien: "bot", error: true,
          texto: "El navegador no dejó usar el micrófono. Revisá el permiso en la barra de direcciones." });
      }
    };
    r.onend = () => { rec.current = null; setGrabando(false); };
    rec.current = r;
    setGrabando(true);
    try { r.start(); } catch (err) { rec.current = null; setGrabando(false); }
  };

  // La barra chica del celular muestra la última respuesta.
  const bots = mensajes.filter((m) => m.quien === "bot");
  const ultima = bots.length ? bots[bots.length - 1].texto : saludo(catalogo);
  const clase = "asist v2-asist" + (abierto ? " abierto" : "") + (modo === "mini" ? " mini" : "");

  return html`<aside class=${clase} id="asist" aria-hidden=${!abierto} inert=${!abierto} aria-label="Asistente del Panel">
    <div class="asist-cab">
      <div class="kicker">Asistente del Panel</div>
      <h2>Preguntá como hablás</h2>
      <p>Traduzco tu pregunta a los filtros del panel y te resumo los números.</p>
      <button type="button" class="asist-min" id="asist-min" aria-label="Achicar para ver el panel" title="Achicar"
        onClick=${() => { if (esMovil()) setModo("mini"); }}>
        <svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
      </button>
      <button type="button" class="asist-cerrar" id="asist-cerrar" aria-label="Cerrar" onClick=${() => setModo("cerrado")}>✕</button>
    </div>
    <button type="button" class="asist-mini-bar" id="asist-mini-bar" aria-label="Abrir el asistente" onClick=${() => setModo("abierto")}>
      <span class="kicker">Asistente</span>
      <span id="asist-mini-texto">${(ultima || "").trim() || "Tocá para abrir"}</span>
      <svg viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg>
    </button>
    <div class="asist-hilo" id="asist-hilo" ref=${hilo} aria-live="polite">
      <div class="burb bot" id="asist-hola">${saludo(catalogo)}</div>
      ${mensajes.map((m) => html`<${Burbuja} key=${m.id} m=${m} verExplorador=${verExplorador} volver=${volver} elegir=${elegir} />`)}
      ${ocupado && html`<div class="burb bot pensando" aria-label="Pensando"><span></span><span></span><span></span></div>`}
    </div>
    <div class="asist-pie">
      <form class="asist-form" id="asist-form" onSubmit=${(e) => { e.preventDefault(); preguntar(); }}>
        <textarea id="asist-caja" ref=${caja} rows="1" placeholder="Escribí tu pregunta…" maxlength="500" aria-label="Pregunta"
          value=${texto}
          onInput=${(e) => { cancelarCuenta(); setTexto(e.currentTarget.value); }}
          onClick=${cancelarCuenta}
          onKeyDown=${(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); preguntar(); } }}></textarea>
        ${Reconocedor && html`<button type="button" class=${"asist-btn mic" + (grabando ? " grabando" : "")} id="asist-mic"
            aria-label=${grabando ? "Escuchando, tocá para parar" : "Dictar"} title="Dictar la pregunta" onClick=${dictar}>
          <svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/><path d="M8.5 21h7"/></svg>
        </button>`}
        <button type="submit" class="asist-btn" id="asist-enviar" aria-label="Enviar" disabled=${ocupado}>
          <svg viewBox="0 0 24 24"><path d="M4 12h15"/><path d="M13 6l6 6-6 6"/></svg>
        </button>
      </form>
      <div class="asist-ayuda" id="asist-ayuda">Enter envía · Shift+Enter agrega un renglón${Reconocedor ? " · Lo dictado se envía solo tras una pausa" : ""}</div>
      ${cuenta !== null && cuenta > 0 && html`<div class="asist-ayuda asist-cuenta" id="asist-cuenta">Enviando en ${cuenta} s… tocá el texto para corregir</div>`}
    </div>
  </aside>`;
}
