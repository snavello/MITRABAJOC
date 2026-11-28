/* XSII, bloque 1 (PLAN_XSII.md X8 a X16; contrato en docs/xsii/API.md).
   Una página con tres vistas (Guía, Tablero, Mapa) y una ficha de tarea.
   Reglas: la pantalla NO decide permisos (dibuja lo que `acciones` dice);
   todo texto que viene del servidor entra con nodos de texto, nunca como
   HTML; toda respuesta del servidor pasa por pedirJson(). */
(function () {
  'use strict';

  let DATOS = {};
  try { DATOS = JSON.parse(document.getElementById('xsii-datos').textContent) || {}; } catch (e) { DATOS = {}; }
  const PID = DATOS.pid;
  const BASE = '/api/entornos/xsii/p/' + PID + '/';
  const NS = 'http://www.w3.org/2000/svg';

  const VISTAS = ['guia', 'tablero', 'mapa'];
  const S = {
    D: null, cargando: true, error: '', vista: 'guia', abierta: null, sel: null, filtro: '',
    det: {}, form: null, insForm: null, anim: false, enfocar: null, enviando: false, abiertos: {},
    pm: {}, rc: null, exito: null, paso: null, as: null, asinfo: {}
  };

  // ------------------------------------------------------------ utilidades
  function h(tag, props) {
    const e = document.createElement(tag);
    if (props) Object.keys(props).forEach(function (k) {
      const v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') e.className = v;
      else if (k.slice(0, 2) === 'on' && typeof v === 'function') e.addEventListener(k.slice(2), v);
      else if (v === true) e.setAttribute(k, '');
      else e.setAttribute(k, v);
    });
    for (let i = 2; i < arguments.length; i++) añadir(e, arguments[i]);
    return e;
  }
  function añadir(e, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { añadir(e, x); }); return; }
    e.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
  }
  function sv(tag, props) {
    const e = document.createElementNS(NS, tag);
    if (props) Object.keys(props).forEach(function (k) { if (props[k] !== null && props[k] !== undefined) e.setAttribute(k, props[k]); });
    for (let i = 2; i < arguments.length; i++) if (arguments[i]) e.appendChild(arguments[i].nodeType ? arguments[i] : document.createTextNode(String(arguments[i])));
    return e;
  }
  const $ = function (id) { return document.getElementById(id); };
  const R = function () { return (S.D && S.D.rotulos) || { estados: {}, modos: {}, decisiones: {} }; };
  const nomEstado = function (k) { return R().estados[k] || k; };
  const nomModo = function (k) { return R().modos[k] || k; };
  const nomDec = function (k) { return R().decisiones[k] || k; };
  const tarea = function (c) { return S.D && S.D.tareas.find(function (t) { return t.codigo === c; }); };
  const resuelta = function (t) { return !!t && (t.estado === 'hecha' || t.estado === 'no_aplica'); };
  const num = function (n) { return typeof n === 'number' ? n.toLocaleString('es-AR') : String(n === null || n === undefined ? '' : n); };
  function cuando(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s || '');
    return m ? m[3] + '/' + m[2] + ' ' + m[4] + ':' + m[5] : (s || '');
  }
  function dias(n) { return n === 1 ? '1 día' : n + ' días'; }
  function pedidoTxt(n) { return n === 0 ? 'Pedido hoy' : n === 1 ? 'Pedido ayer' : 'Pedido hace ' + dias(n); }
  const NOM_DESHACER = { pospuesta: 'Retomar', confirmada: 'Deshacer la confirmación', completada_a_mano: 'Deshacer: completada a mano', no_aplica: 'Volver a aplicar' };

  class ErrorX extends Error { constructor(m, st, cuerpo) { super(m); this.status = st; this.cuerpo = cuerpo || null; } }
  function detalle(d) {
    if (!d) return '';
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map(function (x) { return (x && x.msg) || ''; }).filter(Boolean).join(' ');
    return '';
  }
  async function pedirJson(url, opciones) {
    let r;
    try {
      r = await fetch(url, Object.assign({ credentials: 'same-origin', headers: { Accept: 'application/json' } }, opciones || {}));
    } catch (e) {
      if (e && e.name === 'AbortError') throw new ErrorX('El pedido tardó demasiado y se cortó.', 0);
      if (typeof navigator !== 'undefined' && navigator.onLine === false) throw new ErrorX('Sin conexión: tu dispositivo no tiene internet. Revisalo y probá de nuevo.', 0);
      throw new ErrorX('El servidor no respondió. Probá de nuevo en un momento.', 0);
    }
    let cuerpo = null;
    if ((r.headers.get('content-type') || '').indexOf('json') !== -1) {
      try { cuerpo = await r.json(); } catch (e) { cuerpo = null; }
    }
    if (r.status === 401) throw new ErrorX('Tu sesión venció. Entrá de nuevo desde /entornos y volvé a esta pantalla.', 401);
    if (!r.ok) {
      const d = cuerpo && detalle(cuerpo.detail);
      throw new ErrorX(d || (r.status >= 500 ? 'El servidor no respondió (HTTP ' + r.status + '). Probá de nuevo en un momento.' : 'No se pudo completar la acción (HTTP ' + r.status + ').'), r.status, cuerpo);
    }
    if (cuerpo === null) throw new ErrorX('El servidor no respondió como se esperaba (HTTP ' + r.status + ').', r.status);
    return cuerpo;
  }
  const pedir = function (ruta) { return pedirJson(BASE + ruta, { cache: 'no-store' }); };
  const enviar = function (ruta, cuerpo) {
    return pedirJson(BASE + ruta, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
  };

  // Multipart para la carga asistida: el navegador pone el boundary, no se fija Content-Type.
  const enviarForm = function (ruta, fd, senal) {
    return pedirJson(BASE + ruta, { method: 'POST', headers: { Accept: 'application/json' }, body: fd, signal: senal });
  };

  // ------------------------------------------------------------ URL
  function sincronizarUrl() {
    const q = new URLSearchParams();
    q.set('vista', S.vista);
    const t = S.vista === 'mapa' ? S.sel : S.abierta;
    if (t) q.set('tarea', t);
    try { history.replaceState(null, '', location.pathname + '?' + q.toString()); } catch (e) { /* sin historial, no pasa nada */ }
  }
  function leerUrl() {
    const q = new URLSearchParams(location.search);
    const v = q.get('vista');
    if (VISTAS.indexOf(v) !== -1) S.vista = v;
    const t = q.get('tarea');
    if (t) { S.pendiente = t; }
  }

  // ------------------------------------------------------------ carga
  async function cargar(silencioso) {
    if (!silencioso) { S.cargando = true; S.error = ''; dibujar(); }
    try {
      const d = await pedir('tablero');
      S.D = d; S.cargando = false; S.error = '';
      if (S.pendiente) {
        const c = S.pendiente.toUpperCase(); S.pendiente = null;
        if (tarea(c)) { if (S.vista === 'mapa') S.sel = c; else { S.abierta = c; if (S.vista === 'tablero') S.vista = 'guia'; } }
      }
      if (!S.sel && S.D.tareas.length) S.sel = (S.D.recomendada && S.D.recomendada.codigo) || S.D.tareas[0].codigo;
      if (S.abierta && !tarea(S.abierta)) S.abierta = null;
      if (S.paso && !tarea(S.paso)) S.paso = null;
    } catch (e) {
      if (silencioso) { S.errorAccion = e.message; } else { S.cargando = false; S.error = e.message; }
    }
    dibujar();
    if (S.abierta && S.D) cargarHistorial(S.abierta);
  }
  async function cargarHistorial(codigo) {
    const prev = S.det[codigo];
    if (!prev) S.det[codigo] = { cargando: true, historial: [], error: '' };
    try {
      const d = await pedir('tarea/' + encodeURIComponent(codigo));
      S.det[codigo] = { cargando: false, historial: d.historial || [], error: '' };
    } catch (e) {
      S.det[codigo] = { cargando: false, historial: (prev && prev.historial) || [], error: e.message };
    }
    if (S.abierta === codigo) dibujarFicha();
  }

  // ------------------------------------------------------------ acciones
  function abrirFicha(codigo) {
    if (S.as && S.as.codigo !== codigo && !puedeSalirRb(function () { abrirFicha(codigo); })) return;
    S.abierta = codigo; S.paso = codigo; S.vista = 'guia'; S.form = null; S.insForm = null; S.rc = null; S.anim = true; S.errorAccion = '';
    sincronizarUrl(); dibujar(); window.scrollTo({ top: 0 });
    cargarHistorial(codigo);
  }
  // Recorrido: la lista de tareas en el orden del catalogo. S.paso es el paso que se mira.
  function indicePaso(c) { return S.D.tareas.findIndex(function (t) { return t.codigo === c; }); }
  function pasoActual() {
    const D = S.D;
    if (S.paso && tarea(S.paso)) return tarea(S.paso);
    const rec = D.recomendada && tarea(D.recomendada.codigo);
    return rec || D.tareas.find(function (t) { return !resuelta(t); }) || D.tareas[0] || null;
  }
  function moverPaso(delta) {
    if (!S.D || !S.D.disponible || S.vista !== 'guia') return;
    const ts = S.D.tareas, act = S.abierta || (pasoActual() || {}).codigo;
    const i = indicePaso(act) + delta;
    if (i < 0 || i >= ts.length) return;
    const c = ts[i].codigo;
    if (S.abierta && !puedeSalirRb(function () { moverPaso(delta); })) return;
    S.paso = c;
    if (S.abierta) {
      S.abierta = c; S.form = null; S.insForm = null; S.rc = null; S.errorAccion = '';
      sincronizarUrl(); dibujar(); cargarHistorial(c);
    } else { sincronizarUrl(); dibujar(); }
  }
  function volverGuia() { if (!puedeSalirRb(volverGuia)) return; S.abierta = null; S.form = null; S.insForm = null; S.anim = true; sincronizarUrl(); dibujar(); }
  function irVista(v) {
    if (S.vista === v) return;
    if (S.vista === 'guia' && S.abierta && !puedeSalirRb(function () { irVista(v); })) return;
    S.vista = v;
    if (v === 'mapa' && S.abierta) S.sel = S.abierta;
    if (v === 'guia') { S.abierta = null; S.form = null; S.insForm = null; }
    S.anim = true; sincronizarUrl(); dibujar();
  }
  async function decidir(codigo, tipo, motivo) {
    S.enviando = true; if (S.form) S.form.error = ''; dibujarFicha();
    try {
      await enviar('tarea/' + encodeURIComponent(codigo) + '/decision', { tipo: tipo, motivo: motivo || '' });
      S.form = null; S.enviando = false;
      await cargar(true);
    } catch (e) {
      S.enviando = false;
      if (S.form) S.form.error = e.message; else S.errorAccion = e.message;
      dibujarFicha();
    }
  }
  async function deshacer(codigo, tipo) {
    S.enviando = true; S.errorAccion = ''; dibujarFicha();
    try {
      await enviar('tarea/' + encodeURIComponent(codigo) + '/decision/deshacer', { tipo: tipo, motivo: '' });
      S.enviando = false; await cargar(true);
    } catch (e) { S.enviando = false; S.errorAccion = e.message; dibujarFicha(); }
  }
  async function marcarInsumo(codigo, clave, estado, extra) {
    S.enviando = true; if (S.insForm) S.insForm.error = ''; dibujarFicha();
    const cuerpo = { estado: estado };
    if (extra && extra.tarjeta) cuerpo.tarjeta = extra.tarjeta;
    if (extra && extra.nota) cuerpo.nota = extra.nota;
    try {
      await enviar('insumo/' + encodeURIComponent(clave), cuerpo);
      S.insForm = null; S.enviando = false; await cargar(true);
    } catch (e) {
      S.enviando = false;
      if (S.insForm) S.insForm.error = e.message; else S.errorAccion = e.message;
      dibujarFicha();
    }
  }
  async function retirarInsumo(codigo, clave) {
    S.enviando = true; S.errorAccion = ''; dibujarFicha();
    try {
      await enviar('insumo/' + encodeURIComponent(clave) + '/retirar', {});
      S.enviando = false; await cargar(true);
    } catch (e) { S.enviando = false; S.errorAccion = e.message; dibujarFicha(); }
  }

  // ------------------------------------------------------------ piezas
  const PLAY = function () {
    return sv('svg', { viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': 'true' },
      sv('path', { d: 'M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z' }));
  };
  function icono(clase, hijos) {
    return sv.apply(null, ['svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: clase }].concat(hijos));
  }
  const ICO_PREG = function () {
    return icono('ico-pm', [sv('circle', { cx: '12', cy: '12', r: '10' }), sv('path', { d: 'M9.2 9.3a2.9 2.9 0 1 1 4.6 2.3c-.9.7-1.8 1.2-1.8 2.6' }), sv('path', { d: 'M12 17.4h.01' })]);
  };
  const ICO_DOC = function (c) { return icono(c || 'ico-i', [sv('path', { d: 'M7 3h7l4 4v14H7z' }), sv('path', { d: 'M14 3v4h4M9.5 12h5M9.5 15.5h5' })]); };
  const ICO_DATO = function (c) { return icono(c || 'ico-i', [sv('rect', { x: '4', y: '5', width: '16', height: '14', rx: '2' }), sv('path', { d: 'M4 10h16M10 10v9' })]); };
  const icoInsumo = function (i, c) { return i && i.tipo === 'archivo' ? ICO_DOC(c) : ICO_DATO(c); };
  const FLECHA = function (dir) { return icono('ico-f', [sv('path', { d: dir < 0 ? 'M14.5 5.5L8 12l6.5 6.5' : 'M9.5 5.5L16 12l-6.5 6.5' })]); };
  const faltantes = function (t) { return ((t && t.insumos) || []).filter(function (i) { return i.estado !== 'recibido'; }); };
  const tipoInsumo = function (i) { return i.tipo === 'archivo' ? 'Archivo' : i.tipo === 'dato' ? 'Dato' : 'Insumo'; };
  function marcaEspera(t) {
    const f = faltantes(t);
    if (!f.length) return null;
    const arch = f.some(function (i) { return i.tipo === 'archivo'; });
    const txt = arch ? 'Espera un archivo del sindicato' : 'Espera un dato del sindicato';
    return h('span', { class: 'espera-m', title: txt }, arch ? ICO_DOC('ico-m') : ICO_DATO('ico-m'), h('span', { class: 'sr' }, txt));
  }
  function pildora(estado) { return h('span', { class: 'pil ' + estado }, nomEstado(estado)); }
  function marcas(t) {
    const m = [];
    if (t.a_mano) m.push(h('span', { class: 'marca-t mano' }, 'A mano'));
    if (t.pospuesta) m.push(h('span', { class: 'marca-t' }, 'Pospuesta'));
    if (t.falta_confirmar) m.push(h('span', { class: 'marca-t conf' }, 'Falta confirmar'));
    if (t.con_observaciones) m.push(h('span', { class: 'marca-t conf' }, 'Con observaciones'));
    return m.length ? h('span', { class: 'marcas' }, m) : null;
  }
  // ------------------------------------------------------------ Preguntame (bloque 2)
  // Una pregunta por vez, sobre UN punto, en el lugar. Sin historial: una pregunta
  // nueva reemplaza la respuesta. El estado vive en S.pm por punto y codigo, asi un
  // redibujado general no pierde lo escrito ni la respuesta.
  function idSeguro(t) { return String(t).replace(/[^A-Za-z0-9]+/g, '-'); }
  function pmEstado(clave) {
    if (!S.pm[clave]) S.pm[clave] = { abierto: false, texto: '', cargando: false, resp: null, error: '', ultima: '', prop: null, entra: false, abre: false, foco: null };
    return S.pm[clave];
  }
  function escapar(t) { return t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function textoConCodigos(texto, codigos) {
    const frag = document.createDocumentFragment();
    const cods = (codigos || []).filter(function (c) { return tarea(c); });
    if (!cods.length) { frag.appendChild(document.createTextNode(texto)); return frag; }
    const re = new RegExp('(?<![A-Za-z0-9-])(' + cods.map(escapar).join('|') + ')(?![A-Za-z0-9-])', 'g');
    let ultimo = 0, hallado;
    while ((hallado = re.exec(texto)) !== null) {
      if (hallado.index > ultimo) frag.appendChild(document.createTextNode(texto.slice(ultimo, hallado.index)));
      const cod = hallado[1];
      frag.appendChild(h('button', { class: 'pm-cod', type: 'button', title: 'Abrir la ficha de ' + cod, onclick: function () { abrirFicha(cod); } }, cod));
      ultimo = hallado.index + cod.length;
    }
    if (ultimo < texto.length) frag.appendChild(document.createTextNode(texto.slice(ultimo)));
    return frag;
  }
  function pm(punto, codigo) {
    const clave = punto + ':' + (codigo || '');
    const cont = h('div', { class: 'pm', 'data-pm': clave, 'data-punto': punto, 'data-codigo': codigo || '' });
    pintarPm(cont);
    return cont;
  }
  function repintarPm(clave) {
    document.querySelectorAll('[data-pm]').forEach(function (c) { if (c.getAttribute('data-pm') === clave) pintarPm(c); });
  }
  function pintarPm(cont) {
    const clave = cont.getAttribute('data-pm'), punto = cont.getAttribute('data-punto'), codigo = cont.getAttribute('data-codigo');
    const P = S.D && S.D.preguntame;
    const base = 'pm-' + idSeguro(clave);
    const st = pmEstado(clave);
    const activo = document.activeElement && cont.contains(document.activeElement) ? document.activeElement.id : '';
    let contenido;
    if (!P) {
      contenido = [h('button', { type: 'button', class: 'pm-t', disabled: true }, ICO_PREG(), 'Preguntame'), h('span', { class: 'nota' }, 'Llega en el próximo bloque')];
    } else if (!P.disponible) {
      contenido = [h('button', { type: 'button', class: 'pm-t', disabled: true }, ICO_PREG(), 'Preguntame'), h('span', { class: 'nota' }, P.motivo || 'No está disponible por ahora.')];
    } else {
      const largo = P.largo || { min: 3, max: 300 };
      const sug = ((P.sugeridas || {})[punto]) || [];
      const ocupado = st.cargando;
      const preguntar = function (texto) { preguntarPm(clave, punto, codigo, texto); };
      const cuerpo = h('div', { class: 'pm-cuerpo' + (st.abre ? ' pm-abre' : ''), id: base + '-cuerpo' },
        sug.length ? h('div', { class: 'pm-q', role: 'group', 'aria-label': 'Preguntas sugeridas' }, sug.map(function (q, i) {
          return h('button', { type: 'button', id: base + '-s' + i, class: 'pm-sug' + (st.ultima === q ? ' on' : ''), 'aria-disabled': ocupado ? 'true' : null,
            onclick: function () { if (st.cargando) return; st.texto = q; preguntar(q); } }, q);
        })) : null,
        h('form', { class: 'pm-form', onsubmit: function (ev) { ev.preventDefault(); if (st.cargando) return; preguntar(st.texto); } },
          h('label', { class: 'sr', for: base + '-campo' }, 'Tu pregunta'),
          h('input', { id: base + '-campo', type: 'text', class: 'pm-campo', maxlength: String(largo.max), autocomplete: 'off', readonly: ocupado ? 'true' : null,
            placeholder: 'O escribí tu pregunta sobre este punto', value: st.texto,
            oninput: function (e) {
              st.texto = e.target.value;
              const c = document.getElementById(base + '-cont');
              if (c) { c.textContent = st.texto.length + '/' + largo.max; }
            } }),
          h('span', { class: 'pm-cont num', id: base + '-cont' }, st.texto.length + '/' + largo.max),
          h('button', { type: 'submit', id: base + '-ok', class: 'btn p ch', 'aria-disabled': ocupado ? 'true' : null }, ocupado ? 'Preguntando…' : 'Preguntar')),
        h('div', { class: 'pm-resp', 'aria-live': 'polite', 'aria-busy': ocupado ? 'true' : 'false' },
          ocupado ? h('div', { class: 'esq pm-esq' }, h('i'), h('i'), h('i')) : null,
          !ocupado && st.error ? h('p', { class: 'err', role: 'alert' }, st.error) : null,
          !ocupado && st.resp ? respuestaPm(st, clave) : null));
      contenido = [
        h('button', { type: 'button', id: base + '-tog', class: 'pm-t', 'aria-expanded': st.abierto ? 'true' : 'false', 'aria-controls': base + '-cuerpo',
          onclick: function () { st.abierto = !st.abierto; st.abre = st.abierto; if (st.abierto) st.foco = base + '-campo'; repintarPm(clave); } }, ICO_PREG(), 'Preguntame'),
        st.abierto ? cuerpo : null];
    }
    cont.className = 'pm' + (st.abierto && P && P.disponible ? ' abierto' : '');
    cont.onkeydown = function (e) {
      if (e.key === 'Escape' && st.abierto) { e.stopPropagation(); st.abierto = false; st.foco = base + '-tog'; repintarPm(clave); }
    };
    cont.replaceChildren.apply(cont, contenido.filter(Boolean));
    st.abre = false;
    const objetivo = st.foco || activo; st.foco = null;
    if (objetivo) {
      const e = document.getElementById(objetivo);
      if (e) { try { e.focus({ preventScroll: objetivo.slice(-6) !== '-campo' && objetivo.slice(-2) !== '-h' }); } catch (x) { e.focus(); } }
    }
  }
  function respuestaPm(st, clave) {
    const r = st.resp;
    const tono = r.resultado === 'error' ? ' aviso-t' : r.resultado === 'fija' ? ' fija' : '';
    const entra = st.entra ? ' pm-entra' : ''; st.entra = false;
    return h('div', { class: 'pm-r' + tono + entra },
      st.ultima ? h('p', { class: 'pm-pregunta' }, st.ultima) : null,
      h('p', { class: 'pm-texto' }, textoConCodigos(String(r.texto || ''), r.codigos)),
      r.simulado ? h('p', { class: 'nota' }, 'Respuesta simulada: en este entorno no se llama a la IA.') : null,
      st.prop ? propuestaPm(st, clave) : null,
      st.creada ? h('p', { class: 'nota' }, 'Listo: el reclamo se creó en la Mesa.') : null);
  }
  function propuestaPm(st, clave) {
    const f = st.prop;
    return formReclamo(f, {
      cab: 'Propongo pedirlo en la Mesa',
      redib: function () { repintarPm(clave); },
      confirmar: function () {
        confirmarReclamo(f, function (res) {
          st.prop = null; st.creada = true; avisarCreado(res, f);
        }, function () { repintarPm(clave); });
      },
      cancelar: function () { st.prop = null; st.foco = 'pm-' + idSeguro(clave) + '-campo'; repintarPm(clave); }
    });
  }
  async function preguntarPm(clave, punto, codigo, texto) {
    const st = pmEstado(clave);
    if (st.cargando) return;
    const P = S.D && S.D.preguntame, largo = (P && P.largo) || { min: 3, max: 300 };
    const q = String(texto || '').trim();
    if (q.length < largo.min) { st.error = 'Escribí tu pregunta (al menos ' + largo.min + ' caracteres).'; st.resp = null; st.foco = 'pm-' + idSeguro(clave) + '-campo'; repintarPm(clave); return; }
    st.cargando = true; st.error = ''; st.resp = null; st.prop = null; st.creada = false; st.ultima = q;
    repintarPm(clave);
    const cuerpo = { punto: punto, pregunta: q };
    if (punto !== 'recomendada') cuerpo.codigo = codigo;
    try {
      const r = await enviar('preguntar', cuerpo);
      st.resp = r; st.entra = true;
      const p = r && r.propuesta;
      st.prop = p && p.tipo === 'reclamo' ? { id: 'pm-prop-' + idSeguro(clave), clave: p.clave, nombre: p.nombre || p.clave, titulo: p.titulo || '', texto: p.texto || '', modo: 'nueva', tarjeta: null, error: '', enviando: false } : null;
      if (st.prop) st.foco = st.prop.id + '-h';
    } catch (e) {
      st.error = e.message;
    }
    st.cargando = false;
    repintarPm(clave);
  }

  // ------------------------------------------------------------ Reclamar en la Mesa (bloque 2)
  function avisarCreado(res, f) {
    const t = (res && res.tarjeta) || {};
    S.exito = { codigo: t.codigo || '', titulo: t.titulo || '', url: t.url || (S.D && S.D.proyecto.mesa_url) || '', nombre: f.nombre || '', respuesta: f.modo === 'respuesta' };
    S.rc = null;
    cargar(true).then(function () { window.scrollTo({ top: 0 }); });
  }
  async function confirmarReclamo(f, alTerminar, redib) {
    if (f.enviando) return;
    const t = (f.titulo || '').trim(), x = (f.texto || '').trim();
    if (f.modo !== 'respuesta' && (t.length < 3 || t.length > 120)) { f.error = 'El título tiene que tener entre 3 y 120 caracteres.'; S.enfocar = '#' + f.id + '-t'; f.foco = f.id + '-t'; redib(); return; }
    if (x.length < 5 || x.length > 1000) { f.error = 'El texto tiene que tener entre 5 y 1.000 caracteres.'; S.enfocar = '#' + f.id + '-x'; f.foco = f.id + '-x'; redib(); return; }
    f.enviando = true; f.error = ''; redib();
    try {
      const res = await enviar('insumo/' + encodeURIComponent(f.clave) + '/reclamo', { titulo: t, texto: x });
      f.enviando = false; alTerminar(res);
    } catch (e) {
      f.enviando = false; f.error = e.message; redib();
    }
  }
  function formReclamo(f, o) {
    const nueva = f.modo !== 'respuesta';
    const tar = f.tarjeta;
    return h('form', { class: 'form rc', onsubmit: function (ev) { ev.preventDefault(); o.confirmar(); } },
      h('p', { class: 'rot rc-tit', id: f.id + '-h', tabindex: '-1' }, o.cab || 'Reclamar en la Mesa'),
      h('p', { class: 'nota' }, 'Dato: ', h('b', null, f.nombre || f.clave)),
      nueva ? [h('label', { for: f.id + '-t' }, 'Título'),
        h('input', { id: f.id + '-t', type: 'text', maxlength: '120', value: f.titulo || '', oninput: function (e) { f.titulo = e.target.value; } })]
        : h('p', { class: 'nota' }, 'Va como respuesta en la tarjeta ',
          tar && tar.url ? h('a', { href: tar.url, target: '_blank', rel: 'noopener' }, tar.codigo || 'de la Mesa') : (tar && tar.codigo) || 'de la Mesa', '.'),
      h('label', { for: f.id + '-x' }, 'Texto'),
      h('textarea', { id: f.id + '-x', rows: '6', maxlength: '1000', oninput: function (e) { f.texto = e.target.value; } }, f.texto || ''),
      f.error ? h('p', { class: 'err', role: 'alert' }, f.error) : null,
      h('div', { class: 'acc' },
        h('button', { class: 'btn p ch', type: 'submit', 'aria-disabled': f.enviando ? 'true' : null }, nueva ? (f.enviando ? 'Creando…' : 'Crear en la Mesa') : (f.enviando ? 'Enviando…' : 'Responder en la tarjeta')),
        h('button', { class: 'btn ch', type: 'button', onclick: o.cancelar }, 'Descartar')));
  }
  async function abrirReclamo(clave, origen) {
    if (S.rc && S.rc.clave === clave && S.rc.origen === origen) { S.rc = null; dibujar(); return; }
    const f = { id: 'x-rc-' + origen, clave: clave, origen: origen, cargando: true, errorCarga: '', modo: 'nueva', nombre: '', titulo: '', texto: '', tarjeta: null, error: '', enviando: false };
    S.rc = f; dibujar();
    try {
      const b = await pedir('insumo/' + encodeURIComponent(clave) + '/reclamo');
      if (S.rc !== f) return;
      f.cargando = false; f.nombre = b.nombre || clave; f.titulo = b.titulo || ''; f.texto = b.texto || ''; f.tarjeta = b.tarjeta || null; f.modo = b.modo === 'respuesta' ? 'respuesta' : 'nueva';
      S.enfocar = '#' + f.id + (f.modo === 'respuesta' ? '-x' : '-t');
    } catch (e) {
      if (S.rc !== f) return;
      f.cargando = false; f.errorCarga = e.message;
    }
    dibujar();
  }
  function bloqueReclamo(clave, origen) {
    const f = S.rc;
    if (!f || f.clave !== clave || f.origen !== origen) return null;
    if (f.cargando) return h('div', { class: 'esq', 'aria-busy': 'true', 'aria-label': 'Preparando el reclamo' }, h('i', { class: 'm' }), h('i'));
    if (f.errorCarga) return h('div', { class: 'form rc' }, h('p', { class: 'err', role: 'alert' }, f.errorCarga),
      h('div', { class: 'acc' }, h('button', { class: 'btn ch', type: 'button', onclick: function () { S.rc = null; dibujar(); } }, 'Cerrar')));
    return formReclamo(f, {
      cab: f.origen === 'pano' ? 'Reclamar: ' + (f.nombre || clave) : null,
      redib: dibujar,
      confirmar: function () { confirmarReclamo(f, function (res) { avisarCreado(res, f); }, dibujar); },
      cancelar: function () { S.enfocar = '#x-rcb-' + f.origen + '-' + idSeguro(f.clave); S.rc = null; dibujar(); }
    });
  }
  function nodoExito() {
    const x = S.exito;
    if (!x) return null;
    return h('div', { class: 'aviso exito', role: 'status' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, '✓'),
      h('div', null, h('b', null, x.respuesta ? 'Se agregó tu reclamo a la tarjeta' : 'Se creó el reclamo en la Mesa'),
        x.nombre ? 'Dato: ' + x.nombre + '. ' : '', x.codigo ? 'Tarjeta ' : '',
        x.codigo ? h('a', { href: x.url, target: '_blank', rel: 'noopener' }, x.codigo) : h('a', { href: x.url, target: '_blank', rel: 'noopener' }, 'Abrir la Mesa'),
        x.titulo ? ': ' + x.titulo : '',
        h('div', { class: 'acc', style: 'margin-top:8px' }, h('button', { class: 'btn ch', type: 'button', onclick: function () { S.exito = null; dibujar(); } }, 'Cerrar'))));
  }
  function esqueleto() {
    return h('div', { class: 'esq', 'aria-busy': 'true', 'aria-label': 'Cargando' },
      h('i', { class: 'g' }), h('i', { class: 'm' }), h('i', { class: 'm' }), h('i'), h('i'));
  }
  function bloqueError(msg, reintento) {
    return h('div', { class: 'error', role: 'alert' }, h('b', null, 'No se pudo leer el estado.'), h('span', null, msg),
      h('button', { class: 'btn', type: 'button', onclick: reintento }, 'Reintentar'));
  }

  // ------------------------------------------------------------ barra
  function barra() {
    const D = S.D;
    const txt = $('x-av-txt'), pct = $('x-av-pct'), bar = $('x-av-bar'), riel = $('x-av-riel');
    if (D && D.disponible && D.resumen) {
      const r = D.resumen;
      const k = (r.total || r.aplican) - r.aplican;
      txt.replaceChildren(r.resueltas + ' de ' + r.aplican + ' tareas resueltas', k > 0 ? h('small', { class: 'no-ap' }, ' (' + k + ' no aplican)') : null);
      pct.textContent = r.porcentaje + '%';
      bar.style.width = r.porcentaje + '%';
      riel.setAttribute('aria-valuenow', String(r.porcentaje));
    } else {
      txt.textContent = S.cargando ? 'Leyendo el estado…' : 'Sin datos de avance';
      pct.textContent = ''; bar.style.width = '0%'; riel.setAttribute('aria-valuenow', '0');
    }
    document.querySelectorAll('.vistas button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.v === S.vista)); });
  }

  // ------------------------------------------------------------ GUÍA
  function ctlBoton(id, rotulo, dir, deshab, alAprentar) {
    return h('div', { class: 'ctl-i nav-i' },
      h('button', { class: 'nav', id: id, type: 'button', 'aria-label': dir < 0 ? 'Paso anterior' : 'Paso siguiente', disabled: deshab, onclick: alAprentar }, FLECHA(dir)),
      h('span', { class: 'ctl-r' }, rotulo));
  }
  function bloqueHacer(t) {
    const pasos = (t.pasos || []).filter(Boolean);
    if (!pasos.length && !t.descripcion) return null;
    return h('div', { class: 'hacer' }, h('h3', null, 'Qué tenés que hacer'),
      pasos.length ? h('ol', { class: 'pasos' }, pasos.map(function (p) { return h('li', null, h('span', null, p)); })) : h('p', { class: 'hacer-d' }, t.descripcion));
  }
  function esperaResumen(t) {
    const l = faltantes(t);
    if (!l.length) return null;
    return h('div', { class: 'espera res' }, h('p', { class: 'esp-t' }, 'Se espera del sindicato'),
      l.map(function (i) {
        return h('p', { class: 'esp-l' }, icoInsumo(i, 'ico-i'),
          h('span', null, h('b', null, tipoInsumo(i) + ': ' + i.nombre), i.formato ? ' · ' + i.formato : '', ' · ',
            i.estado === 'pedido' ? pedidoTxt(i.dias || 0) + (i.tarjeta ? ' (' + i.tarjeta.codigo + ')' : '') : 'Todavía no se pidió'));
      }));
  }
  function heroe() {
    const D = S.D, rec = D.recomendada;
    const t = (S.paso && tarea(S.paso)) || (rec && tarea(rec.codigo)) || null;
    if (!t) {
      const alguna = pasoActual();
      return [h('div', { class: 'vacio' }, h('p', { class: 'rot' }, 'Siguiente paso'),
        h('h2', { class: 'disp vacio-t' }, 'No queda nada para hacer ahora'),
        h('p', null, 'Todo lo que aplica está resuelto, o lo que queda espera un dato o a otra tarea. Mirá el tablero para ver qué falta.'),
        h('div', { class: 'acc' }, h('button', { class: 'btn', type: 'button', onclick: function () { irVista('tablero'); } }, 'Ver el tablero'),
          alguna ? h('button', { class: 'btn', type: 'button', onclick: function () { S.paso = alguna.codigo; dibujar(); } }, 'Recorrer los pasos') : null))];
    }
    const esRec = !!rec && rec.codigo === t.codigo;
    const i = indicePaso(t.codigo), n = D.tareas.length;
    const otras = (D.alternativas || []).map(tarea).filter(Boolean).slice(0, 3);
    const nPaso = 'Paso ' + (i + 1) + ' de ' + n;
    return [
      h('div', { class: 'heroe' + (S.anim ? ' entra' : '') },
        h('div', { class: 'ctl' },
          ctlBoton('x-atras', 'Atrás', -1, i <= 0, function () { moverPaso(-1); }),
          h('div', { class: 'ctl-i' },
            h('button', { class: 'play', type: 'button', 'aria-label': 'Empezar: ' + t.nombre, onclick: function () { abrirFicha(t.codigo); } }, PLAY()),
            h('span', { class: 'ctl-r' }, 'Empezar')),
          ctlBoton('x-adelante', 'Adelante', 1, i >= n - 1, function () { moverPaso(1); })),
        h('div', { class: 'cuerpo' },
          h('div', { class: 'rot-f' },
            h('p', { class: 'rot' }, esRec ? 'Siguiente paso recomendado' : nPaso),
            esRec ? h('span', { class: 'nota num' }, nPaso) : pildora(t.estado),
            !esRec && rec ? h('button', { class: 'enlace', type: 'button', onclick: function () { S.paso = rec.codigo; dibujar(); } }, 'Volver al recomendado') : null),
          h('h2', { class: 'disp' }, t.nombre),
          esRec ? pm('recomendada', null) : pm('tarea', t.codigo),
          t.para_que ? h('p', { class: 'bajada' }, t.para_que) : null,
          esRec && rec.por_que ? h('p', { class: 'muted por-que' }, rec.por_que) : (!esRec && t.detalle ? h('p', { class: 'muted por-que' }, t.detalle) : null),
          t.asistida ? h('p', { class: 'as-linea' }, ICO_DOC('ico-i'), 'Se carga desde una planilla, con ensayo previo.') : null,
          bloqueHacer(t),
          esperaResumen(t))),
      otras.length ? h('div', null,
        h('p', { class: 'rot', style: 'margin-bottom:8px' }, 'O seguí con otra que ya se puede hacer'),
        h('div', { class: 'otras' }, otras.map(function (o) {
          return h('button', { class: 'otra', type: 'button', onclick: function () { abrirFicha(o.codigo); } },
            h('b', null, o.nombre), h('span', null, o.detalle), h('span', null, nomModo(o.modo)));
        }))) : null];
  }

  function panorama() {
    const D = S.D;
    const grupo = function (clave, titulo, estados) {
      const l = D.tareas.filter(function (t) { return estados.indexOf(t.estado) !== -1; });
      if (!l.length) return null;
      const det = h('details', { 'data-k': clave },
        h('summary', null, h('span', { class: 'pil ' + estados[0] }, titulo), h('b', null, String(l.length))),
        h('ul', null, l.map(function (t) {
          return h('li', null, h('button', { type: 'button', onclick: function () { abrirFicha(t.codigo); } }, h('b', null, t.nombre, marcaEspera(t)), h('small', null, t.detalle)));
        })));
      if (S.abiertos[clave]) det.open = true;
      det.addEventListener('toggle', function () { S.abiertos[clave] = det.open; });
      return det;
    };
    const dem = D.demorados || [];
    return h('aside', { class: 'pano' }, h('p', { class: 'rot' }, 'Panorama'),
      dem.map(function (d) {
        return h('div', { class: 'aviso' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, '!'),
          h('div', null, h('b', null, d.nombre + (d.dias >= 2 ? ': demorado' : ': pedido')),
            pedidoTxt(d.dias)  + (d.tarjeta ? ' (' + d.tarjeta.codigo + ')' : '') + '. Frena ' + d.frena + (d.frena === 1 ? ' tarea.' : ' tareas.'),
            h('div', { class: 'acc', style: 'margin-top:8px' },
              h('button', { class: 'btn ch', type: 'button', 'aria-expanded': String(!!(S.rc && S.rc.clave === d.clave && S.rc.origen === 'pano')), id: 'x-rcb-pano-' + idSeguro(d.clave), onclick: function () { abrirReclamo(d.clave, 'pano'); } }, 'Reclamar en la Mesa'))));
      }),
      h('section', null,
        grupo('lista', 'Se pueden hacer', ['lista']), grupo('en_curso', 'En curso', ['en_curso']),
        grupo('esperando', 'Esperando un dato', ['esperando']), grupo('bloqueada', 'Bloqueadas', ['bloqueada']),
        grupo('hecha', 'Hechas', ['hecha'])),
      h('button', { class: 'btn ch', type: 'button', style: 'align-self:flex-start', onclick: function () { irVista('tablero'); } }, 'Ver todo en el tablero'),
      h('div', null, h('p', { class: 'rot', style: 'margin-bottom:6px' }, 'Últimos movimientos'),
        (D.movimientos || []).length
          ? h('div', { class: 'log' }, D.movimientos.slice(0, 5).map(function (m) { return h('span', null, h('b', null, cuando(m.cuando)), ' · ', m.texto, m.quien ? ' (' + m.quien + ')' : ''); }))
          : h('p', { class: 'nota' }, 'Todavía no hay movimientos.')));
  }

  function guia() {
    return h('div', { class: 'guia' }, h('div', { id: 'x-cond', class: 'cond' }), panorama());
  }


  // ------------------------------------------------------------ Carga asistida (bloque 3)
  // Cuatro momentos de a uno: Qué voy a hacer, Ensayo, Carga, Control. Todo lo que cambia de una
  // tarea asistida a otra (títulos, columnas, opciones) llega de GET .../asistida; acá no hay
  // textos de ninguna tarea puntual. El estado vive en S.as (uno solo, atado a un código).
  const PASOS_AS = ['Qué voy a hacer', 'Ensayo', 'Carga', 'Control'];
  const ESTADOS_AS = { valida: 'Válida', dudosa: 'Dudosa', rechazada: 'Rechazada', ya_existe: 'Ya existe' };
  const CIFRAS_AS = [['valida', 'validas', 'Válidas'], ['dudosa', 'dudosas', 'Dudosas'], ['rechazada', 'rechazadas', 'Rechazadas'], ['ya_existe', 'ya_existen', 'Ya existen']];
  const asDe = function (c) { return S.as && S.as.codigo === c ? S.as : null; };
  const rutaAs = function (c) { return 'tarea/' + encodeURIComponent(c) + '/asistida'; };
  function infoAsistida(t) {
    const k = t.codigo;
    if (!S.asinfo[k]) {
      S.asinfo[k] = { cargando: true, d: null, error: '' };
      pedir(rutaAs(k)).then(function (d) { S.asinfo[k] = { cargando: false, d: d, error: '' }; },
        function (e) { S.asinfo[k] = { cargando: false, d: null, error: e.message }; })
        .then(function () { if (S.abierta === k) dibujarFicha(); });
    }
    return S.asinfo[k];
  }
  function abrirAsistida(t, d) {
    const opc = {};
    (d.opciones || []).forEach(function (o) { opc[o.clave] = o.tipo === 'numero' ? (typeof o.defecto === 'number' ? o.defecto : null) : !!o.defecto; });
    if (S.as && S.as.codigo !== t.codigo && !puedeSalirRb(function () { abrirAsistida(t, d); })) return;
    S.as = { codigo: t.codigo, paso: 1, archivo: null, texto: '', pegar: false, opciones: opc, snap: null, ens: null, filtro: '', afuera: {},
      trabajando: false, error: '', status: 0, confirmando: false, res: null, anim: true,
      mapa: {}, mapaBase: null, mapaEnviado: '{}', mapaAbierto: false, motivo: -1, t0: 0, reloj: null, que: '' };
    if (d.entrada === 'recibos') estadoInicialRb(S.as);
    S.enfocar = d.entrada === 'recibos' ? '#x-rb-archivos' : '#x-as-h'; dibujarFicha();
  }
  function pararReloj(A) { if (A && A.reloj) { clearInterval(A.reloj); A.reloj = null; } }
  function cerrarAsistida(codigo) {
    if (!codigo && !puedeSalirRb(function () { cerrarAsistida(null); })) return;
    pararReloj(S.as); S.as = null; S.enfocar = '#x-as-abrir';
    if (codigo) { delete S.det[codigo]; cargar(true); cargarHistorial(codigo); } else dibujarFicha();
  }
  function irPasoAs(A, n, foco) {
    A.paso = n; A.error = ''; A.status = 0; A.confirmando = false; A.anim = true;
    S.enfocar = foco || '#x-as-h'; dibujarFicha(); window.scrollTo({ top: 0 });
  }
  function lineasAfuera(A) {
    if (!A.ens) return [];
    return (A.ens.filas || []).filter(function (f) { return f.estado === 'dudosa' && A.afuera[f.linea]; }).map(function (f) { return f.linea; });
  }
  function cuentasAs(A) {
    const e = A.ens || {}, afuera = lineasAfuera(A).length;
    const actualiza = !!(A.snap && A.snap.opciones && A.snap.opciones.actualizar_existentes);
    const crear = (e.validas || 0) + (e.dudosas || 0) - afuera;
    // Las que ya existen solo se escriben si algo cambia: lo dice el resumen de cada fila.
    const ya = (e.filas || []).filter(function (f) { return f.estado === 'ya_existe'; });
    let cambian = actualiza ? ya.filter(function (f) { return !f.resumen || f.resumen.accion !== 'sin_tocar'; }).length : 0;
    // Con el listado recortado las filas no alcanzan para contar: manda lo que el servidor dice que escribiría.
    if (e.filas_truncadas && typeof e.a_escribir === 'number') cambian = Math.max(0, e.a_escribir - afuera - crear);
    return { crear: crear, afuera: afuera, rechazadas: e.rechazadas || 0, ya: e.ya_existen || 0, actualiza: actualiza, cambian: cambian, sinCambio: Math.max(0, (e.ya_existen || 0) - cambian), total: crear + cambian };
  }
  // Mapeo de columnas: A.mapa es lo que se ve en los selectores; A.mapaBase, lo que se detectó la primera vez
  // con este archivo. Al servidor solo viaja lo que la persona cambió respecto de lo detectado.
  function diffsMapa(A) {
    const m = {};
    if (!A.mapaBase) return m;
    Object.keys(A.mapa).forEach(function (i) { if ((A.mapa[i] || '') !== (A.mapaBase[i] || '')) m[i] = A.mapa[i] || ''; });
    return m;
  }
  function mapaPendiente(A) { return JSON.stringify(diffsMapa(A)) !== A.mapaEnviado; }
  function opcionesEnvio(A) {
    const o = {};
    Object.keys(A.opciones).forEach(function (k) {
      const v = A.opciones[k];
      if (v === null || v === undefined || v === '' || (typeof v === 'number' && !isFinite(v))) return;
      o[k] = v;
    });
    const m = diffsMapa(A);
    if (Object.keys(m).length) o.mapeo = m;
    return o;
  }
  function tomarMapa(A, r) {
    const cols = r && r.mapeo && r.mapeo.columnas;
    if (!cols) { A.mapa = {}; A.mapaBase = null; return; }
    A.mapa = {};
    cols.forEach(function (c) { A.mapa[String(c.indice)] = c.campo || ''; });
    if (!A.mapaBase) A.mapaBase = Object.assign({}, A.mapa);
  }
  function resetMapa(A) { A.mapa = {}; A.mapaBase = null; A.mapaEnviado = '{}'; }
  function formAs(A, conCarga) {
    const base = conCarga ? A.snap : { archivo: A.archivo, texto: A.texto, opciones: opcionesEnvio(A) };
    const fd = new FormData();
    // Un texto pegado viaja como archivo: el servidor limita a 1 MB un campo de texto de un multipart.
    if (base.archivo) fd.append('archivo', base.archivo, base.archivo.name);
    else fd.append('archivo', new Blob([base.texto], { type: 'text/csv' }), 'planilla-pegada.csv');
    fd.append('opciones', JSON.stringify(base.opciones));
    if (conCarga) { fd.append('huella', A.ens.huella || ''); fd.append('dejar_afuera', JSON.stringify(lineasAfuera(A))); }
    return fd;
  }
  function tiempoAs(ms) {
    const s = Math.floor(ms / 1000);
    return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + String(s % 60).padStart(2, '0') + ' s';
  }
  function iniciarEspera(A, que, foco) {
    pararReloj(A);
    A.trabajando = true; A.error = ''; A.que = que; A.focoRe = foco || null; A.t0 = Date.now();
    A.reloj = setInterval(function () { const e = $('x-as-reloj'); if (e) e.textContent = tiempoAs(Date.now() - A.t0); }, 1000);
    dibujarFicha();
  }
  function finEspera(A) { pararReloj(A); A.trabajando = false; }
  function falloAs(A, e, extra) {
    finEspera(A);
    A.error = e.message + (extra && (!e.status || e.status >= 500) ? ' ' + extra : ''); A.status = e.status || 0;
    S.enfocar = '#x-as-err'; dibujarFicha();
  }
  function reintentable(A) { return !A.trabajando && A.que && (A.status === 0 || A.status >= 500); }
  function botonReintentar(A) {
    if (!reintentable(A)) return null;
    return h('div', { class: 'acc' }, h('button', { class: 'btn', id: 'x-as-reintentar', type: 'button', onclick: function () {
      if (A.que === 'carga') { A.confirmando = true; if (esRb(A)) cargarRb(); else cargarAs(); } else ensayarAs(A.focoRe);
    } }, 'Reintentar'));
  }
  function opcionesFueraDeRango(A) {
    const d = (S.asinfo[A.codigo] || {}).d || {};
    let msg = '';
    (d.opciones || []).forEach(function (o) {
      const v = A.opciones[o.clave];
      if (o.tipo !== 'numero' || v === null || v === undefined || v === '' || msg) return;
      if (!isFinite(v) || (typeof o.minimo === 'number' && v < o.minimo) || (typeof o.maximo === 'number' && v > o.maximo)) {
        const lim = typeof o.minimo === 'number' && typeof o.maximo === 'number' ? ' entre ' + num(o.minimo) + ' y ' + num(o.maximo) : typeof o.minimo === 'number' ? ' desde ' + num(o.minimo) : typeof o.maximo === 'number' ? ' hasta ' + num(o.maximo) : '';
        msg = '«' + (o.rotulo || o.clave) + '»: ingresá un número' + lim + '.';
      }
    });
    return msg;
  }
  async function ensayarAs(foco) {
    const A = S.as;
    if (!A || A.trabajando) return;
    if (!A.archivo && !A.texto.trim()) { A.error = 'Elegí un archivo o pegá el texto de la planilla.'; A.status = 0; A.que = ''; S.enfocar = '#x-as-archivo'; dibujarFicha(); return; }
    const fuera = opcionesFueraDeRango(A);
    if (fuera) { A.error = fuera; A.status = 0; A.que = ''; S.enfocar = '#x-as-err'; dibujarFicha(); return; }
    const env = opcionesEnvio(A), ctl = new AbortController(), tmo = setTimeout(function () { ctl.abort(); }, 180000);
    iniciarEspera(A, 'ensayo', typeof foco === 'string' ? foco : null);
    try {
      const r = await enviarForm(rutaAs(A.codigo) + '/ensayo', formAs(A, false), ctl.signal);
      A.snap = { archivo: A.archivo, texto: A.texto, opciones: env };
      A.ens = r; A.afuera = {}; A.filtro = ''; A.motivo = -1; A.que = '';
      tomarMapa(A, r); A.mapaEnviado = JSON.stringify(env.mapeo || {});
      finEspera(A);
      irPasoAs(A, 2, typeof foco === 'string' ? foco : null);
    } catch (e) {
      falloAs(A, e, 'Si es una planilla muy grande, probá partirla en dos.');
    } finally { clearTimeout(tmo); }
  }
  async function cargarAs() {
    const A = S.as;
    if (!A || A.trabajando) return;
    if (!A.confirmando) { A.confirmando = true; A.error = ''; dibujarFicha(); return; }
    const ctl = new AbortController(), tmo = setTimeout(function () { ctl.abort(); }, 300000);
    iniciarEspera(A, 'carga');
    try {
      const r = await enviarForm(rutaAs(A.codigo) + '/carga', formAs(A, true), ctl.signal);
      A.res = r; A.que = '';
      finEspera(A);
      irPasoAs(A, 4);
      cargar(true);
    } catch (e) {
      A.confirmando = false;
      falloAs(A, e, 'Puede que la carga se haya hecho: mirá la ficha de la tarea antes de reintentar. Si ya se hizo, el reintento va a avisar que no hay nada para cargar.');
    } finally { clearTimeout(tmo); }
  }
  function indicadorAs(A) {
    return h('ol', { class: 'as-pasos', 'aria-label': 'Pasos de la carga' }, (esRb(A) ? PASOS_RB : PASOS_AS).map(function (n, i) {
      const k = i + 1;
      return h('li', { class: k < A.paso ? 'hecho' : k === A.paso ? 'ahora' : '', 'aria-current': k === A.paso ? 'step' : null },
        h('span', { class: 'as-n num', 'aria-hidden': 'true' }, k < A.paso ? '✓' : String(k)), h('span', { class: 'as-nt' }, n));
    }));
  }
  function errorAs(A, extra) {
    if (!A.error) return null;
    return h('div', { class: 'as-err', id: 'x-as-err', tabindex: '-1', role: 'alert' }, h('p', null, A.error), extra || null);
  }
  function pesoArchivo(n) { return n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1).replace('.', ',') + ' MB'; }
  function elegirArchivo(A, f) {
    if (!f) return;
    A.archivo = f; A.texto = ''; A.error = ''; resetMapa(A); dibujarFicha();
  }
  function zonaArchivo(A) {
    const nom = h('span', { class: 'as-arch-n', id: 'x-as-arch-nom' }, A.archivo ? A.archivo.name + ' · ' + pesoArchivo(A.archivo.size) : 'Todavía no elegiste ninguno');
    const zona = h('label', { class: 'as-arch' + (A.archivo ? ' tiene' : ''), for: 'x-as-archivo' },
      h('input', { id: 'x-as-archivo', class: 'sr', type: 'file', accept: '.csv,text/csv,text/plain', onchange: function (e) { elegirArchivo(A, e.target.files && e.target.files[0]); } }),
      h('span', { class: 'as-arch-b' }, A.archivo ? 'Elegir otro archivo' : 'Elegir el archivo de la planilla'),
      h('span', { class: 'as-arch-s' }, 'o soltalo acá'), nom);
    zona.addEventListener('dragover', function (e) { e.preventDefault(); zona.classList.add('suelta'); });
    zona.addEventListener('dragleave', function () { zona.classList.remove('suelta'); });
    zona.addEventListener('drop', function (e) {
      e.preventDefault(); zona.classList.remove('suelta');
      const fs = e.dataTransfer && e.dataTransfer.files;
      if (fs && fs.length) elegirArchivo(A, fs[0]);
    });
    return zona;
  }
  function paso1As(t, A, d) {
    const dets = h('details', { class: 'as-pegar' }, h('summary', null, 'O pegá el texto de la planilla'),
      h('label', { class: 'sr', for: 'x-as-texto' }, 'Texto de la planilla'),
      h('textarea', { id: 'x-as-texto', rows: '6', spellcheck: 'false', placeholder: 'Pegá acá las filas, con la fila de títulos arriba.',
        oninput: function (e) {
          A.texto = e.target.value; resetMapa(A);
          if (A.texto && A.archivo) { A.archivo = null; const n = $('x-as-arch-nom'); if (n) n.textContent = 'Todavía no elegiste ninguno'; }
        } }, A.texto));
    dets.open = A.pegar || !!A.texto;
    dets.addEventListener('toggle', function () { A.pegar = dets.open; });
    const previas = (t.necesita || []).filter(function (c) { const x = tarea(c); return x && !resuelta(x); }).map(function (c) { return tarea(c).nombre; });
    return h('div', { class: 'as-cuerpo' },
      previas.length ? h('div', { class: 'aviso as-previas', id: 'x-as-previas', role: 'status' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, 'i'),
        h('div', null, 'Podés hacer el ensayo, pero la carga todavía no se puede: primero tiene que estar resuelta ' + (previas.length === 1 ? 'la tarea ' : 'las tareas ') + previas.join(', ') + '.')) : null,
      h('div', { class: 'as-que' }, (d.que_voy_a_hacer || []).map(function (p) { return h('p', null, p); })),
      (d.columnas || d.campos || []).length ? h('div', null, h('p', { class: 'rot' }, 'Columnas de la planilla'),
        d.mapeo ? h('p', { class: 'nota' }, 'No hace falta que estén en este orden ni que se llamen igual: el ensayo reconoce las cabeceras y te deja corregir cuál es cuál.') : null,
        h('div', { class: 'as-cols', role: 'table', 'aria-label': 'Columnas de la planilla' },
          h('div', { class: 'as-c cabe', role: 'row' }, h('span', { role: 'columnheader' }, 'Columna'), h('span', { role: 'columnheader' }, 'Cuánto importa'), h('span', { role: 'columnheader' }, 'Ejemplo')),
          (d.columnas || d.campos).map(function (c) {
            const ob = c.obligatoria || c.obligatorio;
            return h('div', { class: 'as-c', role: 'row' },
              h('span', { role: 'cell' }, h('b', null, c.rotulo || c.clave), c.ayuda ? h('small', null, c.ayuda) : null),
              h('span', { role: 'cell', class: ob ? 'ob' : 'op' }, ob ? 'Obligatoria' : 'Opcional'),
              h('span', { role: 'cell' }, c.ejemplo ? h('code', null, c.ejemplo) : ''));
          }))) : null,
      h('div', { class: 'acc' }, h('a', { class: 'btn', id: 'x-as-modelo', href: BASE + rutaAs(t.codigo) + '/modelo.csv', download: '' }, 'Descargar el modelo'),
        h('span', { class: 'nota' }, 'Un archivo de ejemplo con las columnas listas para completar.')),
      zonaArchivo(A), dets,
      (d.opciones || []).length ? h('fieldset', { class: 'as-opc' }, h('legend', { class: 'rot' }, 'Opciones'),
        d.opciones.map(function (o) {
          const id = 'x-as-o-' + idSeguro(o.clave);
          if (o.tipo === 'numero') {
            return h('div', { class: 'as-o as-on' },
              h('label', { for: id }, h('b', null, o.rotulo || o.clave), o.ayuda ? h('small', null, o.ayuda) : null),
              h('input', { id: id, type: 'number', inputmode: 'decimal', step: 'any', min: typeof o.minimo === 'number' ? o.minimo : null, max: typeof o.maximo === 'number' ? o.maximo : null,
                value: typeof A.opciones[o.clave] === 'number' ? A.opciones[o.clave] : '',
                oninput: function (e) { const v = e.target.value.trim(); A.opciones[o.clave] = v === '' ? null : Number(v.replace(',', '.')); } }));
          }
          return h('div', { class: 'as-o' },
            h('input', { id: id, type: 'checkbox', checked: A.opciones[o.clave] ? true : null, onchange: function (e) { A.opciones[o.clave] = e.target.checked; } }),
            h('label', { for: id }, h('b', null, o.rotulo || o.clave), o.ayuda ? h('small', null, o.ayuda) : null));
        })) : null,
      errorAs(A, botonReintentar(A)),
      h('div', { class: 'acc as-bot' },
        h('button', { class: 'btn p', id: 'x-as-ensayar', type: 'button', 'aria-disabled': A.trabajando ? 'true' : null, onclick: function () { ensayarAs(null); } }, A.trabajando ? 'Ensayando…' : 'Ensayar (no guarda nada)'),
        h('button', { class: 'btn', id: 'x-as-cerrar', type: 'button', disabled: A.trabajando, onclick: function () { cerrarAsistida(null); } }, 'Cerrar')),
      A.trabajando ? esperaAs(A, 'Leyendo la planilla y armando el ensayo…') : null);
  }
  // El servidor manda el resumen de cada fila solo con textos (nombre, direccion, sede_central, ubicacion, accion).
  const ACCION_AS = { crear: 'Se crea', actualizar: 'Se actualiza', sin_tocar: 'No se toca' };
  function resumenFila(f) {
    const r = f.resumen || {};
    return r.nombre ? String(r.nombre) : '';
  }
  function detalleFila(f) {
    const r = f.resumen || {};
    return [r.direccion, r.sede_central, r.ubicacion, ACCION_AS[r.accion]].filter(function (x) { return x; }).map(String).join(' · ');
  }
  function esperaAs(A, texto) {
    return h('div', { class: 'as-espera', role: 'status' },
      h('div', { class: 'esq', 'aria-hidden': 'true' }, h('i', { class: 'm' }), h('i')),
      h('p', null, h('b', null, texto), ' ', h('span', { class: 'num', id: 'x-as-reloj', 'aria-hidden': 'true' }, tiempoAs(Date.now() - A.t0))),
      h('p', { class: 'nota' }, 'Una planilla grande puede tardar decenas de segundos. No cierres ni recargues la pestaña.'));
  }
  const campoRot = function (d, clave) { const c = (d.campos || []).find(function (x) { return x.clave === clave; }); return c ? (c.rotulo || c.clave) : clave; };
  function faltanVivo(A, d) {
    const usadas = {};
    Object.keys(A.mapa).forEach(function (i) { if (A.mapa[i]) usadas[A.mapa[i]] = true; });
    return (d.campos || []).filter(function (c) { return c.obligatorio && !usadas[c.clave]; }).map(function (c) { return c.rotulo || c.clave; });
  }
  // Se actualiza en el lugar (sin redibujar la ficha) cada vez que se toca un selector.
  function refrescarMapa(A, d) {
    const cont = $('x-as-mapa');
    if (!cont) return;
    const usadas = {};
    Object.keys(A.mapa).forEach(function (i) { if (A.mapa[i]) usadas[A.mapa[i]] = i; });
    cont.querySelectorAll('select').forEach(function (sel) {
      const k = sel.getAttribute('data-i');
      sel.querySelectorAll('option').forEach(function (o) { o.disabled = !!o.value && usadas[o.value] !== undefined && usadas[o.value] !== k; });
      const fila = sel.closest('.as-mc'); if (fila) fila.classList.toggle('sinuso', !sel.value);
    });
    const cols = (A.ens && A.ens.mapeo && A.ens.mapeo.columnas) || [];
    const sin = cols.filter(function (c) { return !A.mapa[String(c.indice)]; });
    const rs = $('x-as-map-res'); if (rs) rs.textContent = resumenMapa(cols.length - sin.length, sin.length);
    const su = $('x-as-map-sinuso'); if (su) { su.textContent = sin.length ? 'Columnas que no se van a usar: ' + sin.map(function (c) { return c.cabecera; }).join(', ') + '.' : ''; su.hidden = !sin.length; }
    const fv = faltanVivo(A, d), fe = $('x-as-map-falta');
    if (fe) { fe.textContent = fv.length ? 'Todavía falta una columna para: ' + fv.join(', ') + '.' : ''; fe.hidden = !fv.length; }
    const pend = mapaPendiente(A), bt = $('x-as-reensayar-mapa');
    if (bt) bt.setAttribute('aria-disabled', !pend || fv.length || A.trabajando ? 'true' : 'false');
    const nt = $('x-as-map-nota'); if (nt) nt.textContent = pend ? (fv.length ? 'Elegí una columna para cada campo obligatorio.' : 'Cambiaste columnas: volvé a ensayar para ver cómo queda.') : 'Si algo no está bien, cambialo y volvé a ensayar.';
    const sg = $('x-as-seguir'); if (sg && !(A.ens && A.ens.mapeo && (A.ens.mapeo.faltan || []).length)) sg.disabled = cuentasAs(A).total < 1 || pend;
  }
  const resumenMapa = function (rec, sin) {
    return num(rec) + (rec === 1 ? ' columna reconocida' : ' columnas reconocidas') + (sin ? ', ' + num(sin) + ' sin usar' : '');
  };
  function bloqueMapa(A, d, e) {
    const m = e.mapeo;
    if (!m) return null;
    const campos = d.campos || [], cols = m.columnas || [], faltan = m.faltan || [];
    const sin = cols.filter(function (c) { return !A.mapa[String(c.indice)]; });
    const det = h('details', { class: 'as-map' + (faltan.length ? ' falta' : ''), id: 'x-as-mapa' },
      h('summary', { id: 'x-as-mapa-sum' }, h('b', null, 'Columnas de la planilla'),
        h('span', { class: 'as-map-r', id: 'x-as-map-res' }, resumenMapa(cols.length - sin.length, sin.length))),
      h('div', { class: 'as-mapa', role: 'table', 'aria-label': 'Qué campo corresponde a cada columna de la planilla' },
        h('div', { class: 'as-mc cabe', role: 'row' }, h('span', { role: 'columnheader' }, 'Columna de la planilla'), h('span', { role: 'columnheader' }, 'Algunos valores'), h('span', { role: 'columnheader' }, 'Campo')),
        cols.map(function (c) {
          const k = String(c.indice), id = 'x-as-m-' + idSeguro(k);
          const sel = h('select', { id: id, 'data-i': k, 'aria-label': 'Campo para la columna «' + c.cabecera + '»',
            onchange: function (ev) { A.mapa[k] = ev.target.value; refrescarMapa(A, d); } },
            h('option', { value: '', selected: !A.mapa[k] }, 'No usar'),
            campos.map(function (cp) { return h('option', { value: cp.clave, selected: A.mapa[k] === cp.clave }, (cp.rotulo || cp.clave) + (cp.obligatorio ? ' (obligatorio)' : '')); }));
          return h('div', { class: 'as-mc' + (A.mapa[k] ? '' : ' sinuso'), role: 'row' },
            h('span', { role: 'cell', class: 'as-mc-c' }, h('b', null, c.cabecera || '(sin título)')),
            h('span', { role: 'cell', class: 'as-mc-m' }, (c.muestra || []).slice(0, 3).filter(function (x) { return x !== '' && x !== null && x !== undefined; }).map(function (x) { return h('code', null, String(x)); })),
            h('span', { role: 'cell', class: 'as-mc-s' }, sel));
        })),
      h('p', { class: 'as-map-sin', id: 'x-as-map-sinuso', hidden: sin.length ? null : true }, sin.length ? 'Columnas que no se van a usar: ' + sin.map(function (c) { return c.cabecera; }).join(', ') + '.' : ''),
      h('p', { class: 'as-map-falta', id: 'x-as-map-falta', role: 'status', hidden: true }),
      h('div', { class: 'acc' },
        h('button', { class: 'btn' + (faltan.length ? ' p' : ''), id: 'x-as-reensayar-mapa', type: 'button', 'aria-disabled': 'true', onclick: function (ev) {
          if (ev.currentTarget.getAttribute('aria-disabled') === 'true') return; ensayarAs('#x-as-mapa-sum'); } }, 'Volver a ensayar con estas columnas'),
        h('span', { class: 'nota', id: 'x-as-map-nota' }, 'Si algo no está bien, cambialo y volvé a ensayar.')));
    det.open = faltan.length > 0 || A.mapaAbierto;
    det.addEventListener('toggle', function () { if (!faltan.length) A.mapaAbierto = det.open; });
    setTimeout(function () { refrescarMapa(A, d); }, 0);
    return det;
  }
  function listaMotivos(A, e) {
    const ms = e.motivos || [];
    if (!ms.length) return null;
    return h('div', { class: 'as-mot' }, h('p', { class: 'rot' }, 'Por qué quedaron así (tocá uno para ver solo esas filas)'),
      h('ul', { class: 'as-mots' }, ms.map(function (m, i) {
        const on = A.motivo === i, ls = (m.lineas || []).slice(0, 6).map(String);
        return h('li', null, h('button', { type: 'button', class: 'as-mo', id: 'x-as-mo-' + i, 'aria-pressed': String(on),
          onclick: function () { A.motivo = on ? -1 : i; A.filtro = ''; S.enfocar = '#x-as-mo-' + i; dibujarFicha(); } },
          h('span', { class: 'pil ' + m.estado }, ESTADOS_AS[m.estado] || m.estado),
          h('span', { class: 'as-mo-t' }, h('span', null, m.motivo),
            ls.length ? h('small', null, (ls.length === 1 ? 'Línea ' : 'Líneas ') + ls.join(', ') + ((m.cantidad || 0) > ls.length ? '…' : '')) : null),
          h('b', { class: 'as-mo-n num' }, num(m.cantidad || 0))));
      })));
  }
  function paso2As(t, A) {
    const e = A.ens, c = cuentasAs(A), d = (S.asinfo[A.codigo] || {}).d || {};
    const faltan = (e.mapeo && e.mapeo.faltan) || [], pend = mapaPendiente(A);
    const mapa = bloqueMapa(A, d, e);
    const espera = A.trabajando ? esperaAs(A, 'Volviendo a ensayar con las columnas elegidas…') : null;
    if (faltan.length) {
      return h('div', { class: 'as-cuerpo' },
        h('div', { class: 'as-falta', role: 'alert' }, h('b', null, 'Falta una columna para: ' + faltan.map(function (k) { return campoRot(d, k); }).join(', ') + '.'),
          h('span', null, 'No se pudo reconocer en la planilla. Elegí abajo cuál de sus columnas corresponde y volvé a ensayar. Todavía no hay filas para revisar.')),
        mapa, errorAs(A, botonReintentar(A)), espera,
        h('div', { class: 'acc as-bot' },
          h('button', { class: 'btn', id: 'x-as-volver', type: 'button', onclick: function () { irPasoAs(A, 1, '#x-as-ensayar'); } }, 'Volver'),
          h('button', { class: 'btn p', id: 'x-as-seguir', type: 'button', disabled: true }, 'Seguir'),
          h('button', { class: 'btn', id: 'x-as-cerrar', type: 'button', onclick: function () { cerrarAsistida(null); } }, 'Cerrar')));
    }
    const m = A.motivo >= 0 ? (e.motivos || [])[A.motivo] : null;
    let base = e.filas || [];
    const soloMuestra = A.filtro === 'valida' && !base.some(function (f) { return f.estado === 'valida'; }) && (e.muestra || []).length;
    if (soloMuestra) base = e.muestra;
    const filas = base.filter(function (f) {
      return (!A.filtro || f.estado === A.filtro) && (!m || (f.estado === m.estado && (f.motivos || []).indexOf(m.motivo) !== -1));
    });
    const dudosasVisibles = filas.filter(function (f) { return f.estado === 'dudosa'; });
    // Con el listado recortado hay dudosas que no se ven: «dejar afuera todas» solo alcanzaría a las listadas.
    const dudosasSinListar = !!e.filas_truncadas && (e.dudosas || 0) > (e.filas || []).filter(function (f) { return f.estado === 'dudosa'; }).length;
    const todasFuera = dudosasVisibles.length > 0 && dudosasVisibles.every(function (f) { return A.afuera[f.linea]; });
    const titulo = A.filtro ? ESTADOS_AS[A.filtro] + 's: ' + num(filas.length) + (soloMuestra ? ' de ejemplo' : ' de ' + num((e.filas || []).length) + ' filas listadas')
      : m ? 'Con ese motivo: ' + num(filas.length) + ' filas listadas de ' + num(m.cantidad || 0) : 'Filas listadas: ' + num(filas.length);
    return h('div', { class: 'as-cuerpo' },
      h('div', { class: 'as-nada', role: 'status' }, h('b', null, 'Nada se guardó todavía'), h('span', null, 'Esto es solo un ensayo: se leyeron ' + num(e.total || 0) + ' filas y no se escribió nada en el sistema.')),
      h('div', { class: 'as-kpis', role: 'group', 'aria-label': 'Filtrar las filas por resultado del ensayo' }, CIFRAS_AS.map(function (k) {
        return h('button', { type: 'button', class: 'as-k ' + k[0], id: 'x-as-k-' + k[0], 'aria-pressed': String(A.filtro === k[0]),
          onclick: function () { A.filtro = A.filtro === k[0] ? '' : k[0]; A.motivo = -1; dibujarFicha(); } },
          h('b', { class: 'num' }, num(e[k[1]] || 0)), h('span', null, k[2]));
      })),
      (e.avisos || []).map(function (a) { return h('div', { class: 'aviso' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, 'i'), h('div', null, a)); }),
      e.filas_truncadas ? h('div', { class: 'aviso as-trunc', id: 'x-as-trunc' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, 'i'),
        h('div', null, 'Se muestran las primeras ' + num((e.filas || []).length) + ' filas con problema; los totales de arriba cuentan todas.')) : null,
      mapa, listaMotivos(A, e),
      h('div', null, h('div', { class: 'as-fil' }, h('p', { class: 'rot as-fil-t' }, titulo),
        (A.filtro || m) ? h('button', { class: 'enlace', id: 'x-as-sinfiltro', type: 'button', onclick: function () { A.filtro = ''; A.motivo = -1; S.enfocar = '#x-as-k-valida'; dibujarFicha(); } }, 'Ver todas') : null,
        dudosasVisibles.length > 1 && !dudosasSinListar ? h('button', { class: 'enlace', id: 'x-as-afuera-todas', type: 'button', onclick: function () {
          dudosasVisibles.forEach(function (f) { A.afuera[f.linea] = !todasFuera; }); S.enfocar = '#x-as-afuera-todas'; dibujarFicha(); } },
          todasFuera ? 'Volver a incluir estas ' + num(dudosasVisibles.length) + ' dudosas' : 'Dejar afuera estas ' + num(dudosasVisibles.length) + ' dudosas') : null),
        dudosasSinListar && dudosasVisibles.length ? h('p', { class: 'nota', id: 'x-as-sinlistar' }, 'Hay más dudosas de las que se listan (' + num(e.dudosas) + ' en total). Para dejarlas afuera de una vez, usá la opción del paso 1 que corresponda y volvé a ensayar; acá solo podés dejar afuera de a una.') : null,
        soloMuestra ? h('p', { class: 'nota' }, 'Las válidas no se listan una por una: estas son las primeras, como ejemplo.') : null,
        filas.length ? h('div', { class: 'as-tab', role: 'table', 'aria-label': 'Filas del ensayo' },
          h('div', { class: 'as-f cabe', role: 'row' }, h('span', { role: 'columnheader' }, 'Línea'), h('span', { role: 'columnheader' }, 'Fila'), h('span', { role: 'columnheader' }, 'Resultado'), h('span', { role: 'columnheader' }, 'Dudosa')),
          filas.map(function (f) {
            const id = 'x-as-af-' + f.linea, fuera = !!A.afuera[f.linea];
            return h('div', { class: 'as-f ' + f.estado + (fuera ? ' fuera' : ''), role: 'row' },
              h('span', { class: 'as-l num', role: 'cell' }, String(f.linea)),
              h('span', { class: 'as-r', role: 'cell' }, h('b', null, resumenFila(f) || '(sin nombre)'),
                detalleFila(f) ? h('small', { class: 'as-d' }, detalleFila(f)) : null,
                (f.motivos || []).length ? h('ul', { class: 'as-m' }, f.motivos.map(function (mo) { return h('li', null, mo); })) : null),
              h('span', { class: 'as-e', role: 'cell' }, h('span', { class: 'pil ' + f.estado }, ESTADOS_AS[f.estado] || f.estado)),
              h('span', { class: 'as-a', role: 'cell' }, f.estado === 'dudosa' ? h('span', { class: 'as-chk' },
                h('input', { id: id, type: 'checkbox', checked: fuera ? true : null, onchange: function (ev) { A.afuera[f.linea] = ev.target.checked; dibujarFicha(); } }),
                h('label', { for: id }, 'Dejar afuera')) : null));
          })) : h('p', { class: 'muted' }, A.filtro || m ? 'No hay filas con ese filtro entre las que se listan.' : (e.total || 0) < 1 ? 'La planilla no trae filas.' : 'No hay filas con problemas para mostrar.')),
      c.total < 1 ? h('p', { class: 'nota nec' }, 'No queda ninguna fila para cargar. Corregí la planilla y volvé a ensayar.' +
        (c.ya && !c.actualiza ? ' Si querés cambiarles los datos a las que ya existen, tildá «Actualizar las que ya existen» en el paso 1.' : '')) : null,
      errorAs(A, botonReintentar(A)), espera,
      h('div', { class: 'acc as-bot' },
        h('button', { class: 'btn', id: 'x-as-volver', type: 'button', onclick: function () { irPasoAs(A, 1, '#x-as-ensayar'); } }, 'Volver'),
        h('button', { class: 'btn p', id: 'x-as-seguir', type: 'button', disabled: c.total < 1 || pend || A.trabajando, onclick: function () { irPasoAs(A, 3); } }, 'Seguir'),
        h('button', { class: 'btn', id: 'x-as-cerrar', type: 'button', onclick: function () { cerrarAsistida(null); } }, 'Cerrar'),
        h('span', { class: 'nota' }, 'Volver conserva el archivo y las opciones.')));
  }
  function paso3As(t, A) {
    const c = cuentasAs(A);
    const lineas = [];
    lineas.push(h('li', null, h('b', { class: 'num' }, num(c.crear)), ' se van a crear'));
    if (c.cambian) lineas.push(h('li', null, h('b', { class: 'num' }, num(c.cambian)), c.cambian === 1 ? ' ya existe y se va a actualizar' : ' ya existen y se van a actualizar'));
    if (c.sinCambio) lineas.push(h('li', null, h('b', { class: 'num' }, num(c.sinCambio)), (c.sinCambio === 1 ? ' ya existe y no se toca' : ' ya existen y no se tocan') + (c.actualiza ? ' (no cambia nada)' : '')));
    if (c.afuera) lineas.push(h('li', null, h('b', { class: 'num' }, num(c.afuera)), c.afuera === 1 ? ' dudosa queda afuera porque la dejaste afuera' : ' dudosas quedan afuera porque las dejaste afuera'));
    if (c.rechazadas) lineas.push(h('li', null, h('b', { class: 'num' }, num(c.rechazadas)), c.rechazadas === 1 ? ' rechazada no entra' : ' rechazadas no entran'));
    const re = A.error && A.status === 409;
    return h('div', { class: 'as-cuerpo' },
      h('p', { class: 'as-lead' }, 'Esto es lo que va a pasar al cargar. Después no se puede deshacer desde acá.'),
      h('ul', { class: 'as-res' }, lineas),
      errorAs(A, re ? h('div', { class: 'acc' }, h('button', { class: 'btn', id: 'x-as-reensayar', type: 'button', onclick: function () { irPasoAs(A, 1, '#x-as-ensayar'); } }, 'Volver a ensayar')) : botonReintentar(A)),
      A.confirmando && !A.trabajando ? h('p', { class: 'nota nec', role: 'status' }, 'Apretá otra vez para confirmar: se escribe en el sistema.') : null,
      h('div', { class: 'acc as-bot' },
        h('button', { class: 'btn', id: 'x-as-atras3', type: 'button', disabled: A.trabajando, onclick: function () { irPasoAs(A, 2); } }, 'Volver al ensayo'),
        A.confirmando ? null : h('button', { class: 'btn', id: 'x-as-cerrar', type: 'button', disabled: A.trabajando, onclick: function () { cerrarAsistida(null); } }, 'Cerrar'),
        h('button', { class: 'btn p' + (A.confirmando ? ' conf' : ''), id: 'x-as-cargar', type: 'button', 'aria-disabled': A.trabajando || c.total < 1 ? 'true' : null,
          onclick: function () { if (c.total < 1) return; cargarAs(); } }, A.trabajando ? 'Cargando…' : A.confirmando ? 'Confirmar la carga' : 'Cargar ' + num(c.total)),
        A.confirmando && !A.trabajando ? h('button', { class: 'btn', id: 'x-as-nocargar', type: 'button', onclick: function () { A.confirmando = false; dibujarFicha(); } }, 'No cargar') : null,
        null),
      A.trabajando ? esperaAs(A, 'Cargando y corriendo el control…') : null);
  }
  function comparacionAs(cm) {
    if (!cm || typeof cm.declarado !== 'number') return null;
    const dif = typeof cm.diferencia === 'number' ? cm.diferencia : cm.cargado - cm.declarado, cero = dif === 0;
    return h('div', { class: 'as-comp ' + (cero ? 'cero' : 'dif'), id: 'x-as-comp', role: 'group', 'aria-label': 'Lo declarado contra lo que quedó en el sistema' },
      h('div', null, h('span', null, 'Declarado'), h('b', { class: 'num' }, num(cm.declarado))),
      h('div', null, h('span', null, 'En el sistema'), h('b', { class: 'num' }, num(cm.cargado))),
      h('div', { class: 'as-comp-d' }, h('span', null, 'Diferencia'), h('b', { class: 'num' }, (dif > 0 ? '+' : '') + num(dif)),
        h('small', null, cero ? 'Coincide con lo declarado.' : 'No coincide: revisá antes de dar la tarea por hecha.')));
  }
  function paso4As(t, A) {
    const r = A.res || {}, k = r.carga || {}, c = r.control || {}, tr = r.tarea || {};
    const rs = RES[c.estado] || [c.estado || '', ''];
    const destrabo = (r.destrabo || []).filter(function (x) { return x && x.codigo; });
    const sigue = [];
    const cmp = k.comparacion;
    if (cmp && typeof cmp.declarado === 'number' && (typeof cmp.diferencia === 'number' ? cmp.diferencia : cmp.cargado - cmp.declarado) !== 0) sigue.push('Lo cargado no coincide con el total declarado: revisá la diferencia (rechazadas, afuera o filas que faltan) antes de confirmar.');
    if (tr.acciones && tr.acciones.confirmar) sigue.push('El control está en condiciones: falta que una persona confirme la tarea. Cerrá este panel y usá «Confirmar» en «Qué se puede hacer».');
    else if (c.estado && c.estado !== 'completa') sigue.push('El control todavía no da por completa la tarea. Revisá lo que falta y, si hace falta, cargá otra planilla.');
    else if (tr.estado === 'hecha') sigue.push('La tarea quedó resuelta.');
    const escritas = {};
    (k.detalle || []).forEach(function (x) { if (x && (x.accion === 'creada' || x.accion === 'actualizada')) escritas[x.linea] = true; });
    const sinUbicar = ((A.ens && A.ens.filas) || []).filter(function (f) { return escritas[f.linea] && f.resumen && f.resumen.ubicacion === 'Sin ubicar'; }).length;
    if (sinUbicar) sigue.push(num(sinUbicar) + (sinUbicar === 1 ? ' de las cargadas quedó «sin ubicar»: ' : ' de las cargadas quedaron «sin ubicar»: ') + 'hay que ubicarlas en el mapa y el control lo va a seguir avisando hasta entonces.');
    const cifras = [['creadas', 'Creadas'], ['actualizadas', 'Actualizadas'], ['sin_tocar', 'Sin tocar'], ['afuera', 'Afuera'], ['cargados', 'Cargados'], ['repetidos', 'Ya estaban'], ['recibos_leidos', 'Recibos leídos']].filter(function (x) { return typeof k[x[0]] === 'number'; });
    return h('div', { class: 'as-cuerpo' },
      h('div', { class: 'as-ok', role: 'status' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, '✓'), h('b', null, 'La carga se hizo y el control ya corrió.')),
      comparacionAs(k.comparacion),
      cifras.length ? h('div', { class: 'kpis' }, cifras.map(function (x) { return h('div', { class: 'kpi' }, h('b', null, num(k[x[0]])), h('span', null, x[1])); })) : null,
      h('div', { class: 'as-ctl' }, h('p', { class: 'rot' }, 'Lo que dice el control'),
        h('p', null, h('b', { class: rs[1] }, rs[0]), c.resumen ? ' · ' + c.resumen : ''),
        (c.cifras || []).length ? h('div', { class: 'kpis' }, c.cifras.map(function (x) { return h('div', { class: 'kpi' }, h('b', null, num(x.valor)), h('span', null, x.nombre)); })) : null,
        (c.faltan || []).length ? h('div', null, h('p', { class: 'rot' }, 'Falta'), h('ul', { class: 'faltan' }, c.faltan.map(function (x) { return h('li', null, x); }))) : null),
      h('div', null, h('p', { class: 'rot' }, 'Esto destrabó'),
        destrabo.length ? h('div', { class: 'as-dest' }, destrabo.map(function (x) {
          return h('button', { class: 'btn', type: 'button', onclick: function () { S.as = null; abrirFicha(x.codigo); } }, x.nombre || x.codigo);
        })) : h('p', { class: 'muted' }, 'Ninguna otra tarea cambió de estado.')),
      h('div', null, h('p', { class: 'rot' }, 'Qué sigue'),
        sigue.length ? h('ul', { class: 'as-sigue' }, sigue.map(function (x) { return h('li', null, x); })) : null,
        destrabo.length ? h('p', null, 'Ya se puede seguir con: ', destrabo.map(function (x, i) { return [i ? ', ' : '', h('b', null, x.nombre || x.codigo)]; }), '.') : null,
        !sigue.length && !destrabo.length ? h('p', { class: 'muted' }, 'No hay nada más para hacer acá.') : null),
      h('div', { class: 'acc as-bot' }, h('button', { class: 'btn p', id: 'x-as-listo', type: 'button', onclick: function () { cerrarAsistida(t.codigo); } }, 'Listo')));
  }
  function panelAs(t, A, d) {
    const cuerpo = esRb(A) ? cuerpoRb(t, A, d) : A.paso === 1 ? paso1As(t, A, d) : A.paso === 2 ? paso2As(t, A) : A.paso === 3 ? paso3As(t, A) : paso4As(t, A);
    const anim = A.anim ? ' entra' : ''; A.anim = false;
    return h('section', { class: 'as', id: 'x-as', 'aria-labelledby': 'x-as-h', 'aria-busy': A.trabajando ? 'true' : 'false' },
      h('div', { class: 'as-cab' }, h('p', { class: 'rot' }, d.titulo || (d.entrada === 'recibos' ? 'Leer los recibos de muestra' : 'Carga desde la planilla')),
        indicadorAs(A),
        h('h3', { class: 'as-h', id: 'x-as-h', tabindex: '-1' }, 'Paso ' + A.paso + ' de 4: ' + (esRb(A) ? PASOS_RB : PASOS_AS)[A.paso - 1])),
      h('div', { class: 'as-paso' + anim }, cuerpo));
  }
  // El botón de entrada y, si hay panel abierto, el panel. Devuelve { boton, panel, motivo }.
  function asistidaDe(t) {
    if (!t.asistida) return { boton: null, panel: null, nota: null, abierto: false };
    const inf = infoAsistida(t), d = inf.d, A = asDe(t.codigo);
    if (inf.cargando) return { boton: h('button', { class: 'btn p', type: 'button', id: 'x-as-abrir', 'aria-disabled': 'true' }, 'Cargando…'), panel: null, nota: null, abierto: false };
    if (inf.error) return { boton: null, panel: null, abierto: false, nota: h('p', { class: 'nota nec' }, inf.error + ' ',
      h('button', { class: 'enlace', type: 'button', onclick: function () { delete S.asinfo[t.codigo]; dibujarFicha(); } }, 'Reintentar')) };
    if (!d.disponible) return { boton: null, panel: null, abierto: false, nota: h('p', { class: 'nota' }, d.motivo || 'La carga desde planilla no está disponible por ahora.') };
    if (A) return { boton: null, panel: panelAs(t, A, d), nota: null, abierto: true };
    return { boton: h('button', { class: 'btn p', type: 'button', id: 'x-as-abrir', onclick: function () { abrirAsistida(t, d); } }, d.entrada === 'recibos' ? 'Leer los recibos' : 'Cargar desde la planilla'), panel: null, nota: null, abierto: false };
  }

  // ------------------------------------------------------------ Lectura de recibos de muestra (bloque 4b)
  // La misma ficha con otra entrada: en vez de una planilla, varios recibos que se leen de a uno.
  // Cuatro momentos: Qué voy a hacer, Lectura (con las propuestas para revisar), Carga y Control.
  const PASOS_RB = ['Qué voy a hacer', 'Lectura', 'Carga', 'Control'];
  const PARALELO_RB = 2, TOPE_ARCHIVOS_RB = 300, TOPE_CONCEPTOS_RB = 500, ESPERA_RB_MS = 150000;
  const RUBROS_RB = [{ clave: 'haber', rotulo: 'Haber remunerativo' }, { clave: 'no_remunerativo', rotulo: 'Haber no remunerativo' }, { clave: 'descuento', rotulo: 'Descuento' }];
  const CATEGORIAS_RB = [{ clave: '', rotulo: 'Ninguna' }, { clave: 'afiliacion', rotulo: 'Afiliación' }, { clave: 'convenio', rotulo: 'Convenio' }];
  const SEV_RB = { valida: 0, dudosa: 1, rechazada: 2 };
  const esRb = function (A) { return !!A && A.entrada === 'recibos'; };
  const datosRb = function (A) { return (S.asinfo[A.codigo] || {}).d || {}; };
  const pluralRb = function (n, uno, otros) { return num(n) + ' ' + (n === 1 ? uno : otros); };
  function estadoInicialRb(A) {
    A.entrada = 'recibos'; A.items = []; A.claves = {}; A.serieI = 0; A.serieP = 0; A.props = {}; A.activos = 0;
    A.iniciada = false; A.detenido = false; A.pausa = ''; A.nota = ''; A.filtroP = ''; A.listaAbierta = null; A.simulado = false;
    A.enviados = []; A.dibujoPend = false;
  }
  function itemsDe(A, estado) { return A.items.filter(function (x) { return x.estado === estado; }); }
  function propsLista(A) { return Object.keys(A.props).map(function (k) { return A.props[k]; }); }
  function efectivoRb(p) { return p.descartada ? 'descartada' : p.estado; }
  function incluidasRb(A) { return propsLista(A).filter(function (p) { return !p.descartada && p.estado !== 'rechazada'; }); }
  // Hay algo que se perdería si se sale: lecturas en curso o propuestas todavía sin cargar.
  function sinCargarRb() {
    const A = S.as;
    return esRb(A) && A.paso < 4 && (A.activos > 0 || A.items.some(function (x) { return x.estado === 'leido'; }) || propsLista(A).length > 0);
  }
  const AVISO_SALIR_RB = 'Hay conceptos leídos que todavía no se cargaron. Si salís se pierden y volver a leer cuesta.';
  function redibujarRb(A) {
    if (A.dibujoPend) return;
    A.dibujoPend = true;
    requestAnimationFrame(function () { A.dibujoPend = false; if (S.as === A) dibujarFicha(); });
  }

  // --- archivos
  function agregarRb(A, lista) {
    const d = datosRb(A), ar = d.archivos || {}, tope = (ar.tope_mb || 8) * 1048576, fmts = ar.formatos || ['pdf', 'jpg', 'png', 'webp'];
    let dup = 0, mas = 0, nuevos = 0;
    Array.prototype.forEach.call(lista || [], function (f) {
      const k = f.name + '|' + f.size + '|' + f.lastModified;
      if (A.claves[k]) { dup++; return; }
      if (A.items.length >= TOPE_ARCHIVOS_RB) { mas++; return; }
      A.claves[k] = true; nuevos++;
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      const it = { id: ++A.serieI, clave: k, archivo: f, nombre: f.name, estado: 'cola', motivo: '', nuevos: 0, fijo: false };
      const ok = fmts.indexOf(ext) !== -1 || (ext === 'jpeg' && fmts.indexOf('jpg') !== -1);
      if (!ok) { it.estado = 'fallo'; it.fijo = true; it.motivo = 'Solo se leen PDF y fotos (' + fmts.join(', ') + ').'; }
      else if (f.size === 0) { it.estado = 'fallo'; it.fijo = true; it.motivo = 'El archivo está vacío.'; }
      else if (f.size > tope) { it.estado = 'fallo'; it.fijo = true; it.motivo = 'Pesa más de ' + (ar.tope_mb || 8) + ' MB.'; }
      A.items.push(it);
    });
    const avisos = [];
    if (dup) avisos.push(pluralRb(dup, 'recibo ya estaba en la lista', 'recibos ya estaban en la lista') + '.');
    if (mas) avisos.push('Se pueden leer hasta ' + num(TOPE_ARCHIVOS_RB) + ' recibos por vez: ' + pluralRb(mas, 'quedó afuera', 'quedaron afuera') + '.');
    A.nota = avisos.join(' ');
    return nuevos;
  }
  function quitarRb(A, id) {
    const i = A.items.findIndex(function (x) { return x.id === id; });
    if (i === -1 || A.items[i].estado === 'leyendo') return;
    delete A.claves[A.items[i].clave]; A.items.splice(i, 1); A.nota = '';
  }
  function elegirRb(A, lista, foco) {
    const n = agregarRb(A, lista);
    S.enfocar = foco || null;
    if (A.iniciada) { A.detenido = false; A.pausa = ''; dibujarFicha(); bombearRb(A); } else dibujarFicha();
    return n;
  }
  function zonaRb(A, grande) {
    const id = grande ? 'x-rb-archivos' : 'x-rb-mas';
    const entrada = h('input', { id: id, class: 'sr', type: 'file', multiple: true, accept: '.pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/*',
      onchange: function (e) { const fs = Array.prototype.slice.call(e.target.files || []); e.target.value = ''; if (fs.length) elegirRb(A, fs, '#' + id); } });
    if (!grande) return h('label', { class: 'btn', for: id, id: id + '-b' }, 'Sumar más recibos', entrada);
    const zona = h('label', { class: 'as-arch rb-zona' + (A.items.length ? ' tiene' : ''), for: id },
      entrada,
      h('span', { class: 'as-arch-b' }, A.items.length ? 'Sumar más recibos' : 'Elegir los recibos'),
      h('span', { class: 'as-arch-s' }, 'o soltalos acá'));
    zona.addEventListener('dragover', function (e) { e.preventDefault(); zona.classList.add('suelta'); });
    zona.addEventListener('dragleave', function () { zona.classList.remove('suelta'); });
    zona.addEventListener('drop', function (e) {
      e.preventDefault(); zona.classList.remove('suelta');
      const fs = e.dataTransfer && e.dataTransfer.files;
      if (fs && fs.length) elegirRb(A, fs, '#' + id);
    });
    return zona;
  }

  // --- lectura: de a un archivo por pedido, dos a la vez
  function empezarRb(A) {
    if (!itemsDe(A, 'cola').length) return;
    A.iniciada = true; A.detenido = false; A.pausa = ''; A.listaAbierta = null;
    irPasoAs(A, 2, '#x-rb-prog');
    bombearRb(A);
  }
  function bombearRb(A) {
    if (S.as !== A || !A.iniciada) return;
    while (!A.detenido && !A.pausa && A.activos < PARALELO_RB) {
      const it = A.items.find(function (x) { return x.estado === 'cola'; });
      if (!it) break;
      leerRb(A, it);
    }
    redibujarRb(A);
  }
  async function leerRb(A, it) {
    it.estado = 'leyendo'; A.activos++;
    const ctl = new AbortController(), tmo = setTimeout(function () { ctl.abort(); }, ESPERA_RB_MS);
    try {
      const fd = new FormData(); fd.append('archivo', it.archivo, it.archivo.name);
      const r = await enviarForm(rutaAs(A.codigo) + '/ensayo', fd, ctl.signal);
      if (S.as === A) recibirRb(A, it, r);
    } catch (e) {
      if (S.as !== A) return;
      if (e.status === 429 || e.status === 401) { it.estado = 'cola'; A.pausa = e.message; }
      else {
        it.estado = 'fallo'; it.motivo = e.message || 'No se pudo leer.'; it.reintentable = !e.status || e.status >= 500;
        if (!e.status) A.pausa = e.message + ' La lectura quedó en pausa.';
      }
    } finally {
      clearTimeout(tmo); A.activos--;
      if (S.as === A) bombearRb(A);
    }
  }
  function recibirRb(A, it, r) {
    const rec = (r && r.recibo) || {};
    if (rec.simulado) A.simulado = true;
    if (!rec.leido) { it.estado = 'fallo'; it.motivo = rec.motivo || 'No se pudo leer este recibo.'; it.reintentable = true; return; }
    it.estado = 'leido'; it.motivo = ''; it.nuevos = (r.propuestas || []).length;
    mezclarRb(A, r.propuestas || []);
  }
  function detenerRb(A) { A.detenido = true; redibujarRb(A); S.enfocar = '#x-rb-seguir-leyendo'; }
  function seguirLeyendoRb(A) { A.detenido = false; A.pausa = ''; bombearRb(A); S.enfocar = '#x-rb-prog'; }
  function reintentarRb(A, it) { it.estado = 'cola'; it.motivo = ''; A.detenido = false; A.pausa = ''; bombearRb(A); }

  // --- propuestas: se juntan por clave y suman «veces»
  function mezclarRb(A, ps) {
    ps.forEach(function (p) {
      if (!p || !p.clave) return;
      let q = A.props[p.clave];
      if (!q) {
        q = A.props[p.clave] = { n: ++A.serieP, clave: p.clave, codigo: p.codigo || '', cuit: p.cuit_empleador || '', empleador: p.empleador_nombre || '',
          veces: 0, rubros: {}, estado: 'valida', avisos: [], errores: [], similar: null, generico_sugerido: null,
          desc: p.descripcion || '', tocoDesc: false, rubro: '', tocoRubro: false, cat: '', tocoCat: false, generico: '', tocoGen: false, descartada: false, errorSrv: '' };
      }
      q.veces += (typeof p.veces === 'number' && p.veces > 0 ? p.veces : 1);
      q.rubros[p.rubro] = (q.rubros[p.rubro] || 0) + 1;
      if (!q.empleador && p.empleador_nombre) q.empleador = p.empleador_nombre;
      if (!q.tocoDesc && !q.desc && p.descripcion) q.desc = p.descripcion;
      if (!q.similar && p.similar) q.similar = p.similar;
      if (!q.generico_sugerido && p.generico_sugerido) { q.generico_sugerido = p.generico_sugerido; if (!q.tocoGen) q.generico = p.generico_sugerido.codigo || ''; }
      if (p.categoria_sindical && !q.tocoCat && !q.cat) q.cat = p.categoria_sindical;
      if ((SEV_RB[p.estado] || 0) > (SEV_RB[q.estado] || 0)) q.estado = p.estado;
      (p.avisos || []).forEach(function (a) { if (a && q.avisos.indexOf(a) === -1) q.avisos.push(a); });
      (p.errores || []).forEach(function (a) { if (a && q.errores.indexOf(a) === -1) q.errores.push(a); });
      afinarRb(q);
    });
  }
  // Rubro: el que más veces apareció (salvo que la persona lo haya elegido). Si los recibos no coinciden, se avisa.
  function afinarRb(q) {
    const ks = Object.keys(q.rubros).filter(function (k) { return k; });
    if (!q.tocoRubro) {
      let mejor = '', n = 0;
      ks.forEach(function (k) { if (q.rubros[k] > n) { n = q.rubros[k]; mejor = k; } });
      q.rubro = mejor;
    }
    if (q.rubro !== 'descuento') q.cat = '';
    const dif = 'Los recibos no coinciden en el rubro';
    q.avisos = q.avisos.filter(function (a) { return a !== dif; });
    if (ks.length > 1) { q.avisos.push(dif); if (q.estado === 'valida') q.estado = 'dudosa'; }
  }
  function errorFilaRb(p) {
    if (p.descartada || p.estado === 'rechazada') return '';
    if (!p.desc.trim()) return 'Falta la descripción.';
    if (!p.rubro) return 'Elegí el rubro.';
    return p.errorSrv || '';
  }
  function problemasRb(A) {
    const inc = incluidasRb(A), malas = inc.filter(function (p) { return errorFilaRb(p) && !p.errorSrv; });
    if (!inc.length) return { ok: false, texto: 'No hay conceptos para cargar todavía.' };
    if (malas.length) return { ok: false, texto: pluralRb(malas.length, 'concepto necesita', 'conceptos necesitan') + ' una corrección antes de seguir.' };
    if (inc.length > TOPE_CONCEPTOS_RB) return { ok: false, texto: 'Se cargan hasta ' + num(TOPE_CONCEPTOS_RB) + ' conceptos por vez: descartá ' + num(inc.length - TOPE_CONCEPTOS_RB) + ' o más.' };
    const leyendo = A.activos > 0 || (!A.detenido && !A.pausa && itemsDe(A, 'cola').length > 0);
    if (leyendo) return { ok: false, texto: 'Esperá a que termine la lectura o apretá «Detener».' };
    return { ok: true, texto: '' };
  }
  // Un cambio de texto no redibuja (se perdería el clic siguiente): se actualizan a mano el aviso de la fila y el botón.
  function vivoRb(A, p) {
    const e = $('x-rb-' + p.n + '-e'); if (e) { const t = errorFilaRb(p); e.textContent = t; e.hidden = !t; }
    const f = $('x-rb-' + p.n + '-f'); if (f) f.classList.toggle('mal', !!errorFilaRb(p));
    const pr = problemasRb(A), b = $('x-rb-seguir'), n = $('x-rb-nota');
    if (b) b.disabled = !pr.ok; if (n) { n.textContent = pr.texto; n.hidden = !pr.texto; }
  }

  // --- pantalla: momento 1
  function iaRb(d) {
    const ia = d.ia || {};
    if (ia.disponible === false) return h('div', { class: 'as-falta', id: 'x-rb-ia', role: 'alert' }, h('b', null, 'La lectura de recibos no está disponible ahora.'), ia.motivo ? h('span', null, ia.motivo) : null);
    if (ia.simulada) return h('div', { class: 'aviso', id: 'x-rb-ia', role: 'status' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, 'i'), h('div', null, h('b', null, 'Modo de prueba'), 'La lectura es simulada: no usa la IA de verdad.'));
    return null;
  }
  function listaElegidosRb(A) {
    if (!A.items.length) return null;
    const lista = A.items.slice(0, 40);
    return h('div', { class: 'rb-elegidos' },
      h('p', { class: 'rb-n', id: 'x-rb-n' }, h('b', { class: 'num' }, num(itemsDe(A, 'cola').length)), ' para leer', A.items.some(function (x) { return x.estado === 'fallo'; }) ? ' · ' + num(itemsDe(A, 'fallo').length) + ' con problema' : ''),
      h('ul', { class: 'rb-ch' }, lista.map(function (it) {
        return h('li', { class: it.estado === 'fallo' ? 'mal' : '' },
          h('span', { class: 'rb-ch-n' }, it.nombre, it.estado === 'fallo' ? h('small', null, it.motivo) : null),
          h('button', { class: 'rb-x', type: 'button', 'aria-label': 'Quitar ' + it.nombre, onclick: function () { quitarRb(A, it.id); S.enfocar = '#x-rb-archivos'; dibujarFicha(); } }, '×'));
      })),
      A.items.length > lista.length ? h('p', { class: 'nota' }, 'y ' + num(A.items.length - lista.length) + ' más') : null,
      h('button', { class: 'enlace', id: 'x-rb-quitar-todos', type: 'button', onclick: function () { A.items = []; A.claves = {}; A.nota = ''; S.enfocar = '#x-rb-archivos'; dibujarFicha(); } }, 'Quitar todos'));
  }
  function paso1Rb(t, A, d) {
    const ar = d.archivos || {}, ia = d.ia || {}, listos = itemsDe(A, 'cola').length;
    const previas = (t.necesita || []).filter(function (c) { const x = tarea(c); return x && !resuelta(x); }).map(function (c) { return tarea(c).nombre; });
    const que = d.que_voy_a_hacer || [];
    return h('div', { class: 'as-cuerpo' },
      iaRb(d),
      previas.length ? h('div', { class: 'aviso as-previas', id: 'x-as-previas', role: 'status' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, 'i'),
        h('div', null, 'Podés leer los recibos, pero la carga todavía no se puede: primero tiene que estar resuelta ' + (previas.length === 1 ? 'la tarea ' : 'las tareas ') + previas.join(', ') + '.')) : null,
      que.length ? h('div', { class: 'as-que' }, h('p', { class: 'as-lead' }, que[0])) : null,
      que.length > 1 ? h('details', { class: 'as-pegar' }, h('summary', null, 'Más detalle'), h('div', { class: 'as-que' }, que.slice(1).map(function (p) { return h('p', null, p); }))) : null,
      zonaRb(A, true),
      h('p', { class: 'nota' }, 'PDF o foto, hasta ' + (ar.tope_mb || 8) + ' MB cada uno.' + (ar.sugeridos ? ' Conviene sumar ' + ar.sugeridos + '.' : '')),
      A.nota ? h('p', { class: 'nota nec', role: 'status' }, A.nota) : null,
      listaElegidosRb(A),
      errorAs(A, null),
      h('div', { class: 'acc as-bot' },
        h('button', { class: 'btn p rb-gr', id: 'x-rb-leer', type: 'button', disabled: !listos || ia.disponible === false, onclick: function () { empezarRb(A); } },
          listos ? 'Leer ' + pluralRb(listos, 'recibo', 'recibos') : 'Leer los recibos'),
        h('button', { class: 'btn', id: 'x-as-cerrar', type: 'button', onclick: function () { cerrarAsistida(null); } }, 'Cerrar')));
  }

  // --- pantalla: momento 2
  const TXT_ITEM_RB = function (it) {
    return it.estado === 'cola' ? 'En cola' : it.estado === 'leyendo' ? 'Leyendo…' : it.estado === 'leido' ? (it.nuevos === 0 ? 'Leído, sin conceptos nuevos' : 'Leído: ' + pluralRb(it.nuevos, 'concepto', 'conceptos')) : it.motivo || 'No se pudo leer';
  };
  function progresoRb(A) {
    const tot = A.items.filter(function (x) { return !x.fijo; }).length, hechos = A.items.filter(function (x) { return !x.fijo && (x.estado === 'leido' || x.estado === 'fallo'); }).length;
    const pct = tot ? Math.round(hechos * 100 / tot) : 0, leyendo = A.activos > 0, quedan = itemsDe(A, 'cola').length;
    const terminado = !leyendo && !quedan;
    const fallos = A.items.filter(function (x) { return x.estado === 'fallo'; }).length;
    const estado = A.pausa ? 'En pausa' : leyendo ? (A.detenido ? 'Terminando los que ya se estaban leyendo…' : 'Leyendo…') : quedan ? 'Detenido' : fallos ? 'Listo, con ' + pluralRb(fallos, 'recibo que no se pudo leer', 'recibos que no se pudieron leer') : 'Listo';
    return h('div', { class: 'rb-prog' + (terminado ? ' fin' : ''), id: 'x-rb-prog', tabindex: '-1' },
      h('div', { class: 'rb-prog-t' }, h('b', { class: 'num rb-gran', role: 'status' }, num(hechos) + ' de ' + num(tot)), h('span', { class: 'rb-est' }, estado)),
      h('div', { class: 'rb-riel', role: 'progressbar', 'aria-label': 'Recibos leídos', 'aria-valuemin': '0', 'aria-valuemax': String(tot), 'aria-valuenow': String(hechos) }, h('i', { style: 'width:' + pct + '%' })),
      A.pausa ? h('div', { class: 'as-err', role: 'alert' }, h('p', null, A.pausa)) : null,
      h('div', { class: 'acc' },
        leyendo || (quedan && !A.detenido && !A.pausa) ? h('button', { class: 'btn', id: 'x-rb-detener', type: 'button', disabled: A.detenido, onclick: function () { detenerRb(A); } }, 'Detener') : null,
        quedan && (A.detenido || A.pausa) ? h('button', { class: 'btn p', id: 'x-rb-seguir-leyendo', type: 'button', onclick: function () { seguirLeyendoRb(A); } }, 'Seguir leyendo (' + num(quedan) + ')') : null,
        zonaRb(A, false)),
      A.nota ? h('p', { class: 'nota nec', role: 'status' }, A.nota) : null,
      A.simulado ? h('p', { class: 'nota' }, 'Modo de prueba: la lectura es simulada.') : null);
  }
  function listaRecibosRb(A) {
    const hayFallo = A.items.some(function (x) { return x.estado === 'fallo'; });
    const abierto = A.listaAbierta === null ? (A.items.length <= 6 || hayFallo) : A.listaAbierta;
    const det = h('details', { class: 'rb-lista', id: 'x-rb-lista' }, h('summary', null, h('b', null, 'Recibos'), h('span', { class: 'rb-sum' }, num(A.items.length) + (hayFallo ? ' · ' + num(itemsDe(A, 'fallo').length) + ' con problema' : ''))),
      h('ul', { class: 'rb-items' }, A.items.map(function (it) {
        return h('li', { class: 'rb-it ' + it.estado },
          h('span', { class: 'rb-it-n' }, it.nombre),
          h('span', { class: 'rb-it-e' }, TXT_ITEM_RB(it)),
          it.estado === 'fallo' && !it.fijo ? h('button', { class: 'enlace', type: 'button', onclick: function () { reintentarRb(A, it); } }, 'Probar de nuevo') : null);
      })));
    det.open = abierto;
    det.addEventListener('toggle', function () { A.listaAbierta = det.open; });
    return det;
  }
  function selectRb(id, rotulo, opciones, valor, alCambiar, deshab) {
    return h('div', { class: 'rb-c' }, h('label', { for: id }, rotulo),
      h('select', { id: id, disabled: deshab, onchange: function (e) { alCambiar(e.target.value); } },
        opciones.map(function (o) { return h('option', { value: o.clave, selected: o.clave === valor }, o.rotulo); })));
  }
  function filaRb(A, p, d, repetido) {
    const id = 'x-rb-' + p.n, fuera = p.descartada, rech = p.estado === 'rechazada', est = efectivoRb(p);
    const rubros = d.rubros || RUBROS_RB, cats = d.categorias_sindicales || CATEGORIAS_RB, gens = d.genericos || [];
    const err = errorFilaRb(p);
    const parecido = p.similar && !p.avisos.concat(p.errores).some(function (a) { return a.indexOf(p.similar.codigo) !== -1; })
      ? 'Se parece a ' + (p.similar.codigo || '') + (p.similar.nombre ? ' · ' + p.similar.nombre : '') : '';
    const redib = function () { dibujarFicha(); };
    // «La descripción vino vacía» ya lo dice el error de la fila (y deja de valer apenas se escribe una).
    const avisosVis = p.avisos.filter(function (a) { return a.indexOf('descripción vino vacía') === -1; });
    return h('li', { class: 'rb-f ' + est + (err ? ' mal' : ''), id: id + '-f' },
      h('div', { class: 'rb-f-c' },
        h('b', { class: 'num rb-cod' }, p.codigo || '(sin código)'),
        h('span', { class: 'rb-veces num' }, '×' + num(p.veces)),
        h('span', { class: 'pil ' + est }, fuera ? 'Descartada' : ESTADOS_AS[p.estado] || p.estado),
        rech ? null : h('button', { class: 'btn ch rb-descartar', id: id + '-x', type: 'button', onclick: function () { p.descartada = !p.descartada; redib(); } }, fuera ? 'Volver a incluir' : 'Descartar')),
      rech ? h('p', { class: 'rb-dr' }, p.desc || '(sin descripción)') : null,
      rech ? (repetido ? null : h('ul', { class: 'rb-no' }, (p.errores.length ? p.errores : ['No se puede incluir.']).map(function (x) { return h('li', null, x); })))
        : h('div', { class: 'rb-ed' },
          h('div', { class: 'rb-c rb-desc' }, h('label', { for: id + '-d' }, 'Descripción'),
            h('input', { id: id + '-d', type: 'text', maxlength: '120', value: p.desc, disabled: fuera, autocomplete: 'off',
              oninput: function (e) { p.desc = e.target.value; p.tocoDesc = true; p.errorSrv = ''; vivoRb(A, p); } })),
          selectRb(id + '-r', 'Rubro', rubros, p.rubro, function (v) { p.rubro = v; p.tocoRubro = true; p.errorSrv = ''; afinarRb(p); redib(); }, fuera),
          p.rubro === 'descuento' ? selectRb(id + '-c', 'Categoría sindical', cats, p.cat, function (v) { p.cat = v; p.tocoCat = true; }, fuera) : null,
          p.cuit && gens.length ? selectRb(id + '-g', 'Corresponde a', [{ clave: '', rotulo: 'Ninguno' }].concat(gens.map(function (g) { return { clave: g.codigo, rotulo: g.codigo + ' · ' + g.nombre }; })), p.generico,
            function (v) { p.generico = v; p.tocoGen = true; }, fuera) : null),
      parecido ? h('p', { class: 'rb-av' }, parecido) : null,
      avisosVis.length ? h('ul', { class: 'rb-avs' }, avisosVis.map(function (a) { return h('li', null, a); })) : null,
      h('p', { class: 'rb-err', id: id + '-e', role: 'alert', hidden: err ? null : true }, err));
  }
  function gruposRb(A, lista) {
    const g = {}, orden = [];
    lista.forEach(function (p) {
      const k = p.cuit || '';
      if (!g[k]) { g[k] = { cuit: k, nombre: '', ps: [], dudosas: 0 }; orden.push(k); }
      g[k].ps.push(p); if (!g[k].nombre && p.empleador) g[k].nombre = p.empleador;
      if (efectivoRb(p) === 'dudosa') g[k].dudosas++;
    });
    const sev = { dudosa: 0, rechazada: 1, valida: 2, descartada: 3 };
    return orden.map(function (k) { g[k].ps.sort(function (a, b) { return (sev[efectivoRb(a)] - sev[efectivoRb(b)]) || (b.veces - a.veces) || (a.codigo < b.codigo ? -1 : 1); }); return g[k]; })
      .sort(function (a, b) { return (b.dudosas - a.dudosas) || ((a.cuit === '') - (b.cuit === '')) || (a.nombre < b.nombre ? -1 : 1); });
  }
  const FILTROS_RB = [['', 'Todas'], ['dudosa', 'Dudosas'], ['rechazada', 'Rechazadas'], ['descartada', 'Descartadas']];
  function paso2Rb(t, A) {
    const d = datosRb(A), todas = propsLista(A);
    const cuenta = function (k) { return k ? todas.filter(function (p) { return efectivoRb(p) === k; }).length : todas.length; };
    const lista = todas.filter(function (p) { return !A.filtroP || efectivoRb(p) === A.filtroP; });
    const pr = problemasRb(A), inc = incluidasRb(A), grupos = gruposRb(A, lista);
    const terminoSinNada = !A.activos && !itemsDe(A, 'cola').length && !todas.length;
    return h('div', { class: 'as-cuerpo' },
      h('div', { class: 'as-nada', role: 'status' }, h('b', null, 'Nada se guardó todavía'), h('span', null, 'Los conceptos se cargan recién en el paso 3.')),
      progresoRb(A), listaRecibosRb(A),
      todas.length ? h('div', { class: 'rb-props' },
        h('div', { class: 'rb-filtros', id: 'x-rb-filtros', role: 'group', 'aria-label': 'Filtrar los conceptos' }, FILTROS_RB.filter(function (f) { return !f[0] || cuenta(f[0]) > 0 || A.filtroP === f[0]; }).map(function (f) {
          return h('button', { type: 'button', class: 'rb-fil ' + f[0], id: 'x-rb-f-' + (f[0] || 'todas'), 'aria-pressed': String(A.filtroP === f[0]),
            onclick: function () { A.filtroP = A.filtroP === f[0] ? '' : f[0]; S.enfocar = '#x-rb-f-' + (f[0] || 'todas'); dibujarFicha(); } },
            h('b', { class: 'num' }, num(cuenta(f[0]))), h('span', null, f[1]));
        })),
        grupos.length ? grupos.map(function (g) {
          return h('section', { class: 'rb-g', 'aria-label': g.nombre || g.cuit || 'Sin empleador' },
            h('h4', { class: 'rb-g-t' }, h('span', null, g.nombre || (g.cuit ? 'Empleador' : 'Sin empleador')), g.cuit ? h('small', { class: 'num' }, g.cuit) : null, h('small', null, pluralRb(g.ps.length, 'concepto', 'conceptos'))),
            h('ul', { class: 'rb-fs' }, g.ps.map(function (p, i) { return filaRb(A, p, d, i > 0 && efectivoRb(p) === 'rechazada' && efectivoRb(g.ps[i - 1]) === 'rechazada' && p.errores.join('|') === g.ps[i - 1].errores.join('|')); })));
        }) : h('p', { class: 'muted' }, 'No hay conceptos con ese filtro.')) : null,
      terminoSinNada ? h('p', { class: 'muted rb-vacio' }, A.items.some(function (x) { return x.estado === 'leido'; })
        ? 'No apareció ningún concepto nuevo: los de estos recibos ya están en el catálogo.' : 'Ningún recibo se pudo leer. Probá con otros o de nuevo.') : null,
      errorAs(A, null),
      h('div', { class: 'acc as-bot' },
        h('button', { class: 'btn', id: 'x-as-volver', type: 'button', onclick: function () { irPasoAs(A, 1, '#x-rb-archivos'); } }, 'Volver'),
        h('button', { class: 'btn p rb-gr', id: 'x-rb-seguir', type: 'button', disabled: !pr.ok, onclick: function () { A.confirmando = false; irPasoAs(A, 3); } }, 'Seguir con ' + pluralRb(inc.length, 'concepto', 'conceptos')),
        h('button', { class: 'btn', id: 'x-as-cerrar', type: 'button', onclick: function () { cerrarAsistida(null); } }, 'Cerrar'),
        h('span', { class: 'nota nec', id: 'x-rb-nota', hidden: pr.texto ? null : true }, pr.texto)));
  }

  // --- pantalla: momento 3 y carga
  function cargaRb(A) {
    const inc = incluidasRb(A);
    return { conceptos: inc.map(function (p) {
      return { codigo: p.codigo, descripcion: p.desc.trim(), cuit_empleador: p.cuit, rubro: p.rubro,
        categoria_sindical: p.rubro === 'descuento' ? p.cat : '', codigo_generico: p.cuit ? p.generico : '' };
    }), recibos_leidos: itemsDe(A, 'leido').length };
  }
  function detalleErrorRb(A, e) {
    const c = e && e.cuerpo || {};
    let det = c.detalle;
    if (!Array.isArray(det) && c.detail && typeof c.detail === 'object' && !Array.isArray(c.detail)) det = c.detail.detalle;
    if (!Array.isArray(det)) return [];
    const textos = [];
    det.forEach(function (x) {
      let txt = '', p = null;
      if (typeof x === 'string') txt = x;
      else if (x && typeof x === 'object') {
        txt = String(x.mensaje || x.msg || x.error || x.motivo || '');
        if (typeof x.indice === 'number') p = A.enviados[x.indice];
        else if (x.clave) p = A.props[x.clave];
        else if (x.codigo) p = A.enviados.find(function (q) { return q.codigo === x.codigo; });
        if (p && txt) p.errorSrv = txt;
        if (p) txt = (p.codigo || '') + (txt ? ': ' + txt : '');
      }
      if (txt) textos.push(txt);
    });
    return textos.slice(0, 12);
  }
  async function cargarRb() {
    const A = S.as;
    if (!A || A.trabajando) return;
    if (!A.confirmando) { A.confirmando = true; A.error = ''; dibujarFicha(); return; }
    const cuerpo = cargaRb(A);
    A.enviados = incluidasRb(A); A.erroresSrv = [];
    iniciarEspera(A, 'carga');
    try {
      const r = await enviar(rutaAs(A.codigo) + '/carga', cuerpo);
      A.res = r; A.que = '';
      A.items.forEach(function (x) { x.archivo = null; }); A.props = {};
      finEspera(A);
      irPasoAs(A, 4);
      cargar(true);
    } catch (e) {
      A.confirmando = false; A.erroresSrv = e.status === 400 ? detalleErrorRb(A, e) : [];
      falloAs(A, e, 'Puede que la carga se haya hecho: mirá la ficha de la tarea antes de reintentar. Si ya se hizo, el reintento va a avisar que no hay nada para cargar.');
    }
  }
  function paso3Rb(t, A) {
    const inc = incluidasRb(A), todas = propsLista(A);
    const fuera = todas.filter(function (p) { return p.descartada; }).length, rech = todas.filter(function (p) { return p.estado === 'rechazada' && !p.descartada; }).length;
    const porRubro = function (k) { return inc.filter(function (p) { return p.rubro === k; }).length; };
    const rubros = (datosRb(A).rubros || RUBROS_RB).map(function (r) { return [r.rotulo, porRubro(r.clave)]; }).filter(function (x) { return x[1] > 0; });
    const re = A.error && A.status === 409;
    return h('div', { class: 'as-cuerpo' },
      h('p', { class: 'as-lead rb-voy' }, 'Voy a cargar ', h('b', { class: 'num' }, num(inc.length)), inc.length === 1 ? ' concepto' : ' conceptos', fuera ? ' (' + pluralRb(fuera, 'descartado', 'descartados') + ')' : '', '.'),
      rubros.length ? h('div', { class: 'kpis' }, rubros.map(function (x) { return h('div', { class: 'kpi' }, h('b', null, num(x[1])), h('span', null, x[0])); })) : null,
      rech ? h('p', { class: 'nota' }, pluralRb(rech, 'rechazado no entra', 'rechazados no entran') + '.') : null,
      h('p', { class: 'nota' }, 'Entran ya revisados. Después no se puede deshacer desde acá.'),
      errorAs(A, re ? h('div', { class: 'acc' }, h('button', { class: 'btn', id: 'x-as-reensayar', type: 'button', onclick: function () { irPasoAs(A, 2); } }, 'Volver a revisar')) : botonReintentar(A)),
      (A.erroresSrv || []).length ? h('div', { class: 'as-err', role: 'alert' }, h('ul', { class: 'rb-erl' }, A.erroresSrv.map(function (x) { return h('li', null, x); })),
        h('div', { class: 'acc' }, h('button', { class: 'btn', id: 'x-rb-revisar', type: 'button', onclick: function () { irPasoAs(A, 2); } }, 'Volver a revisar'))) : null,
      A.confirmando && !A.trabajando ? h('p', { class: 'nota nec', role: 'status' }, 'Apretá otra vez para confirmar: se escribe en el sistema.') : null,
      h('div', { class: 'acc as-bot' },
        h('button', { class: 'btn', id: 'x-as-atras3', type: 'button', disabled: A.trabajando, onclick: function () { irPasoAs(A, 2); } }, 'Volver a revisar'),
        A.confirmando ? null : h('button', { class: 'btn', id: 'x-as-cerrar', type: 'button', disabled: A.trabajando, onclick: function () { cerrarAsistida(null); } }, 'Cerrar'),
        h('button', { class: 'btn p rb-gr' + (A.confirmando ? ' conf' : ''), id: 'x-as-cargar', type: 'button', 'aria-disabled': A.trabajando || !inc.length ? 'true' : null,
          onclick: function () { if (!inc.length) return; cargarRb(); } }, A.trabajando ? 'Cargando…' : A.confirmando ? 'Confirmar la carga' : 'Cargar ' + num(inc.length)),
        A.confirmando && !A.trabajando ? h('button', { class: 'btn', id: 'x-as-nocargar', type: 'button', onclick: function () { A.confirmando = false; dibujarFicha(); } }, 'No cargar') : null),
      A.trabajando ? esperaAs(A, 'Cargando y corriendo el control…') : null);
  }
  function cuerpoRb(t, A, d) {
    return A.paso === 1 ? paso1Rb(t, A, d) : A.paso === 2 ? paso2Rb(t, A) : A.paso === 3 ? paso3Rb(t, A) : paso4As(t, A);
  }
  // Salir con conceptos sin cargar pide confirmación en la propia pantalla (no hay diálogos del navegador).
  // Solo frena si la ficha está a la vista: si no, no hay dónde preguntar y nada se pierde (el estado queda en memoria).
  function puedeSalirRb(sigue) {
    if (!sinCargarRb() || !$('x-cond') || !S.abierta) return true;
    S.salirRb = sigue || null; S.enfocar = '#x-rb-salir-no'; dibujarFicha();
    return false;
  }
  function salirIgualRb() {
    const sigue = S.salirRb; S.salirRb = null;
    pararReloj(S.as); S.as = null;
    if (sigue) sigue(); else dibujarFicha();
  }
  function avisoSalirRb() {
    if (!S.salirRb) return null;
    return h('div', { class: 'as-err rb-salir', id: 'x-rb-salir', role: 'alert' }, h('p', null, AVISO_SALIR_RB),
      h('div', { class: 'acc' },
        h('button', { class: 'btn p', id: 'x-rb-salir-no', type: 'button', onclick: function () { S.salirRb = null; S.enfocar = '#x-rb-leer, #x-rb-seguir, #x-rb-archivos'; dibujarFicha(); } }, 'Quedarme'),
        h('button', { class: 'btn', id: 'x-rb-salir-si', type: 'button', onclick: salirIgualRb }, 'Salir igual')));
  }
  window.addEventListener('beforeunload', function (e) { if (sinCargarRb()) { e.preventDefault(); e.returnValue = ''; return ''; } });

  // ------------------------------------------------------------ FICHA
  const RES = { completa: ['Completa', 'res-ok'], observaciones: ['Con observaciones', 'res-obs'], incompleta: ['Incompleta', 'res-mal'] };
  function listaTareas(codigos, vacio) {
    if (!codigos.length) return h('p', { class: 'muted' }, vacio);
    return h('ul', { class: 'lis' }, codigos.map(function (c) {
      const t = tarea(c);
      return h('li', null, h('button', { type: 'button', onclick: function () { abrirFicha(c); } },
        h('span', null, t ? t.nombre : c), t ? pildora(t.estado) : null));
    }));
  }
  function seccionInsumos(t) {
    const todos = t.insumos || [];
    if (!todos.length) return null;
    const falta = faltantes(t).length > 0;
    return h('div', { class: 'espera' + (falta ? '' : ' ok') }, h('h3', null, falta ? 'Se espera del sindicato' : 'Insumos'),
      todos.map(function (i) {
        const reg = i.estado !== 'falta';
        const f = S.insForm && S.insForm.clave === i.clave ? S.insForm : null;
        const estadoTxt = i.estado === 'recibido' ? 'Recibido' : i.estado === 'pedido' ? pedidoTxt(i.dias || 0) : 'Todavía no se pidió';
        return h('div', { class: 'ins ' + i.estado },
          h('div', { class: 't' }, h('span', { class: 'ins-n' }, icoInsumo(i, 'ico-i'), h('b', null, tipoInsumo(i) + ': ' + i.nombre)), h('span', { class: 'est' }, estadoTxt)),
          i.formato ? h('p', { class: 'ins-f' }, 'Se espera: ', i.formato) : null,
          i.descripcion ? h('p', { class: 'nota' }, i.descripcion) : null,
          i.sin_registrar ? h('p', { class: 'sr-aviso' }, 'Hay datos cargados, pero el insumo no está registrado.') : null,
          i.tarjeta ? h('p', { class: 'nota' }, 'Tarjeta de la Mesa: ',
            h('a', { href: i.tarjeta.url, target: '_blank', rel: 'noopener' }, i.tarjeta.codigo), ' ', i.tarjeta.titulo || '') : null,
          i.nota ? h('p', { class: 'nota' }, 'Nota: ' + i.nota) : null,
          reg && i.quien ? h('p', { class: 'nota' }, 'Registró ' + i.quien + ' el ' + cuando(i.cuando) + '.') : null,
          f ? formInsumo(t, i, f) : h('div', { class: 'acc' },
            i.estado !== 'recibido' ? h('button', { class: 'btn ch', type: 'button', disabled: S.enviando, onclick: function () { marcarInsumo(t.codigo, i.clave, 'recibido'); } }, 'Marcar recibido') : null,
            i.estado !== 'pedido' ? h('button', { class: 'btn ch', type: 'button', disabled: S.enviando, onclick: function () { S.insForm = { clave: i.clave, tarjeta: '', nota: '', error: '' }; S.enfocar = '#x-ins-tarjeta'; dibujarFicha(); } }, 'Marcar pedido') : null,
            reg && !i.sin_registrar ? h('button', { class: 'btn ch', type: 'button', disabled: S.enviando, onclick: function () { retirarInsumo(t.codigo, i.clave); } }, 'Quitar registro') : null,
            i.estado !== 'recibido' ? h('button', { class: 'btn ch rec', type: 'button', 'aria-expanded': String(!!(S.rc && S.rc.clave === i.clave && S.rc.origen === 'ficha')), id: 'x-rcb-ficha-' + idSeguro(i.clave), onclick: function () { abrirReclamo(i.clave, 'ficha'); } }, 'Reclamar en la Mesa') : null),
          bloqueReclamo(i.clave, 'ficha'));
      }));
  }
  // Un bloque plegado: el estado abierto/cerrado se recuerda entre redibujados (S.abiertos).
  function plegable(clave, titulo, resumen, hijos, porDefecto, extra) {
    const abierto = S.abiertos[clave] !== undefined ? S.abiertos[clave] : !!porDefecto;
    const sum = h('summary', null, h('h3', null, titulo), h('span', { class: 'pr' }, resumen));
    const d = h('details', { class: 'bloque pleg' + (extra ? ' ' + extra : ''), 'data-k': clave }, sum, h('div', { class: 'pleg-c' }, hijos));
    d.open = abierto;
    sum.addEventListener('click', function () { S.abiertos[clave] = !d.open; });
    return d;
  }
  function formInsumo(t, i, f) {
    return h('form', { class: 'form', onsubmit: function (ev) { ev.preventDefault(); marcarInsumo(t.codigo, i.clave, 'pedido', { tarjeta: f.tarjeta.trim(), nota: f.nota.trim() }); } },
      h('label', { for: 'x-ins-tarjeta' }, 'Código de la tarjeta de la Mesa (opcional)'),
      h('input', { id: 'x-ins-tarjeta', type: 'text', maxlength: '20', value: f.tarjeta, placeholder: 'Por ejemplo PE0007', oninput: function (e) { f.tarjeta = e.target.value; } }),
      h('label', { for: 'x-ins-nota' }, 'Nota (opcional)'),
      h('input', { id: 'x-ins-nota', type: 'text', maxlength: '500', value: f.nota, oninput: function (e) { f.nota = e.target.value; } }),
      f.error ? h('p', { class: 'err', role: 'alert' }, f.error) : null,
      h('div', { class: 'acc' },
        h('button', { class: 'btn p ch', type: 'submit', disabled: S.enviando }, 'Marcar como pedido'),
        h('button', { class: 'btn ch', type: 'button', onclick: function () { S.insForm = null; dibujarFicha(); } }, 'Cancelar')));
  }
  function seccionControl(t) {
    const c = t.control;
    if (!c) return null;
    const r = RES[c.estado] || [c.estado || '', ''];
    const na = t.estado === 'no_aplica';
    const rotulo = na ? 'Lo que diría el control (no cuenta: la tarea no aplica)' : t.a_mano ? 'Lo que calcula el control' : 'Lo que dice el control';
    const faltan = c.faltan || [];
    return plegable(t.codigo + ':control', rotulo, h('span', null, h('b', { class: r[1] }, r[0]), c.resumen ? ' · ' + c.resumen : ''),
      [(c.cifras || []).length ? h('div', { class: 'kpis' }, c.cifras.map(function (k) { return h('div', { class: 'kpi' }, h('b', null, num(k.valor)), h('span', null, k.nombre)); })) : null,
        c.resumen ? h('p', null, c.resumen) : null,
        faltan.length ? h('div', null, h('p', { class: 'rot' }, 'Falta'), h('ul', { class: 'faltan' }, faltan.map(function (x) { return h('li', null, x); }))) : null],
      faltan.length > 0 && !na, na ? 'atenuado' : '');
  }
  const REQ = { completada_a_mano: true, no_aplica: true, posponer: false };
  function formDecision(t, f) {
    const oblig = f.tipo === 'completada_a_mano' || f.tipo === 'no_aplica';
    const titulo = { completada_a_mano: 'Completar a mano', no_aplica: 'Declarar que no aplica', pospuesta: 'Posponer' }[f.tipo];
    return h('form', { class: 'form', onsubmit: function (ev) {
      ev.preventDefault();
      const m = f.motivo.trim();
      if (oblig && m.length < 5) { f.error = 'El motivo es obligatorio (al menos 5 caracteres).'; S.enfocar = '#x-motivo'; dibujarFicha(); return; }
      decidir(t.codigo, f.tipo, m);
    } },
      h('label', { for: 'x-motivo' }, titulo + (oblig ? ': motivo (obligatorio)' : ': motivo (opcional)')),
      h('textarea', { id: 'x-motivo', maxlength: '500', 'aria-required': oblig ? 'true' : 'false', oninput: function (e) { f.motivo = e.target.value; } }, f.motivo),
      f.error ? h('p', { class: 'err', role: 'alert' }, f.error) : null,
      h('div', { class: 'acc' },
        h('button', { class: 'btn p ch', type: 'submit', disabled: S.enviando }, S.enviando ? 'Guardando…' : 'Guardar'),
        h('button', { class: 'btn ch', type: 'button', onclick: function () { S.form = null; dibujarFicha(); } }, 'Cancelar')));
  }
  function seccionAcciones(t) {
    const a = t.acciones || {};
    const abrir = function (tipo) { return function () { S.form = { tipo: tipo, motivo: '', error: '' }; S.enfocar = '#x-motivo'; dibujarFicha(); }; };
    const hay = a.confirmar || a.completar_a_mano || a.no_aplica || a.posponer || (a.deshacer || []).length;
    if (!hay) return null;
    return h('div', { class: 'bloque' }, h('h3', null, 'Qué se puede hacer'),
      S.errorAccion ? h('p', { class: 'err', role: 'alert', style: 'color:var(--bloq);font-weight:600' }, S.errorAccion) : null,
      S.form ? formDecision(t, S.form) : h('div', { class: 'acc' },
        a.confirmar ? h('button', { class: 'btn p', type: 'button', disabled: S.enviando, onclick: function () { decidir(t.codigo, 'confirmada', ''); } }, 'Confirmar') : null,
        a.completar_a_mano ? h('button', { class: 'btn', type: 'button', disabled: S.enviando, onclick: abrir('completada_a_mano') }, 'Completar a mano') : null,
        a.no_aplica ? h('button', { class: 'btn', type: 'button', disabled: S.enviando, onclick: abrir('no_aplica') }, 'No aplica') : null,
        a.posponer ? h('button', { class: 'btn', type: 'button', disabled: S.enviando, onclick: abrir('pospuesta') }, 'Posponer') : null,
        (a.deshacer || []).map(function (tipo) {
          return h('button', { class: 'btn', type: 'button', disabled: S.enviando, onclick: function () { deshacer(t.codigo, tipo); } }, NOM_DESHACER[tipo] || ('Deshacer: ' + nomDec(tipo).toLowerCase()));
        })));
  }
  function seccionDecisiones(t) {
    const ds = t.decisiones || [];
    if (!ds.length) return null;
    return plegable(t.codigo + ':decisiones', 'Decisiones activas', ds.length === 1 ? '1 decisión' : ds.length + ' decisiones',
      [ds.map(function (d) {
        return h('div', { class: 'dec' }, h('b', null, nomDec(d.tipo)), ' · ' + (d.quien || '') + ' · ' + cuando(d.cuando),
          d.motivo ? h('div', { class: 'muted' }, d.motivo) : null);
      }),
      t.a_mano ? h('p', { class: 'nota' }, 'Quedó marcada como hecha a mano. El control sigue diciendo lo que ve en el sistema.') : null], false);
  }
  function seccionHistorial(t) {
    const d = S.det[t.codigo];
    const n = d && !d.cargando ? d.historial.length : null;
    return plegable(t.codigo + ':historial', 'Historial de la tarea', n === null ? 'Cargando…' : n === 0 ? 'Sin movimientos' : n === 1 ? '1 movimiento' : n + ' movimientos',
      [!d || d.cargando ? h('div', { class: 'esq' }, h('i'), h('i')) :
        d.error ? h('p', { class: 'err', style: 'color:var(--bloq)' }, d.error) :
          d.historial.length ? h('ul', { class: 'hist' }, d.historial.map(function (m) {
            return h('li', null, m.texto, h('small', null, cuando(m.cuando) + (m.quien ? ' · ' + m.quien : '')));
          })) : h('p', { class: 'muted' }, 'Todavía no hay movimientos en esta tarea.')], false);
  }
  function seccionRelaciones(t) {
    const nec = t.necesita || [], des = (t.destraba && t.destraba.directo) || [];
    return plegable(t.codigo + ':relaciones', 'Necesita y destraba', 'Necesita ' + nec.length + ' · Destraba ' + des.length,
      [h('div', { class: 'dos' },
        h('div', null, h('p', { class: 'rot' }, 'Necesita'), listaTareas(nec, 'No necesita nada antes.')),
        h('div', null, h('p', { class: 'rot' }, 'Destraba'), listaTareas(des, 'No hay otra tarea esperándola.')))], false);
  }
  function botoneraFicha(t) {
    const i = indicePaso(t.codigo), n = S.D.tareas.length;
    return h('div', { class: 'fnav' },
      h('button', { class: 'btn ch', type: 'button', onclick: volverGuia }, 'Volver a la guía'),
      h('div', { class: 'fnav-p', role: 'group', 'aria-label': 'Recorrido de tareas' },
        h('button', { class: 'btn ch fnav-b', id: 'x-f-atras', type: 'button', disabled: i <= 0, onclick: function () { moverPaso(-1); } }, '‹ Atrás'),
        h('span', { class: 'nota num' }, 'Paso ' + (i + 1) + ' de ' + n),
        h('button', { class: 'btn ch fnav-b', id: 'x-f-adelante', type: 'button', disabled: i >= n - 1, onclick: function () { moverPaso(1); } }, 'Adelante ›')));
  }
  function ficha(t) {
    const frenos = (t.camino || []).map(function (c) { const x = tarea(c); return x ? x.nombre : c; });
    const hacer = bloqueHacer(t);
    const as = asistidaDe(t);
    const resto = [
      t.para_que ? h('p', { class: 'bajada' }, t.para_que) : null,
      (t.avisos || []).map(function (a) { return h('div', { class: 'aviso' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, 'i'), h('div', null, a)); }),
      frenos.length && !resuelta(t) ? h('p', { class: 'nota' }, 'Para llegar acá antes hay que resolver, en este orden: ' + frenos.join(', ') + '.') : null,
      hacer || t.donde || as.boton || as.nota ? h('div', { class: 'hacer-c' }, hacer,
        as.nota,
        as.boton || t.donde ? h('div', { class: 'acc' }, as.boton,
          t.donde ? h('a', { class: 'btn donde' + (t.estado === 'no_aplica' || as.boton ? '' : ' p'), href: t.donde.url, target: '_blank', rel: 'noopener' }, 'Ir a la pantalla') : null,
          t.donde ? h('span', { class: 'nota' }, t.donde.rotulo) : null) : null) : null,
      !hacer && t.detalle ? h('p', { class: 'muted' }, t.detalle) : null,
      seccionInsumos(t),
      t.confirmacion ? h('div', { class: 'bloque' }, h('h3', null, 'Lo que hay que confirmar'),
        h('p', null, t.confirmacion), t.falta_confirmar ? h('p', { class: 'nota' }, 'Todavía nadie lo confirmó.') : null,
        !(t.acciones && t.acciones.confirmar) && (t.insumos || []).some(function (i) { return i.estado === 'falta' || i.estado === 'pedido'; })
          ? h('p', { class: 'nota nec' }, 'Primero registrá que llegó el insumo.') : null) : null,
      seccionAcciones(t),
      seccionControl(t),
      seccionRelaciones(t),
      seccionDecisiones(t),
      seccionHistorial(t)];
    return h('div', { class: 'ficha' + (S.anim ? ' entra' : '') },
      botoneraFicha(t),
      h('div', { class: 'cab' },
        h('p', { class: 'rot' }, t.codigo + ' · ' + t.grupo + ' · ' + nomModo(t.modo)),
        h('h2', { class: 'disp' }, t.nombre),
        h('div', { class: 'fila' }, pildora(t.estado), marcas(t)),
        pm('tarea', t.codigo)),
      avisoSalirRb(),
      as.panel,
      as.abierto ? h('div', { class: 'as-resto', inert: true }, h('p', { class: 'nota' }, 'El resto de la ficha vuelve cuando cierres el panel de carga.'), resto) : resto);
  }
  function dibujarFicha() {
    const cont = $('x-cond');
    if (!cont || !S.abierta) return;
    const t = tarea(S.abierta);
    if (!t) return;
    conFoco(function () { cont.replaceChildren(ficha(t)); });
    enfocar();
  }
  // Un redibujado no le saca el foco ni el cursor a quien esta escribiendo.
  function conFoco(fn) {
    const a = document.activeElement, id = a && a.id;
    let ini = null, fin = null;
    try { ini = a.selectionStart; fin = a.selectionEnd; } catch (e) { ini = null; }
    fn();
    if (id && !S.enfocar) {
      const e = document.getElementById(id);
      if (e && e !== document.activeElement) {
        try { e.focus({ preventScroll: true }); if (ini !== null && e.setSelectionRange) e.setSelectionRange(ini, fin); } catch (x) { /* sin foco no pasa nada */ }
      }
    }
  }
  function enfocar() {
    if (!S.enfocar) return;
    const sel = S.enfocar; S.enfocar = null;
    requestAnimationFrame(function () { const e = document.querySelector(sel); if (e) e.focus(); });
  }

  // ------------------------------------------------------------ TABLERO
  const FILTROS_MARCA = [
    ['_mano', 'Completadas a mano', function (t) { return t.a_mano; }],
    ['_pos', 'Pospuestas', function (t) { return t.pospuesta; }],
    ['_conf', 'Falta confirmar', function (t) { return t.falta_confirmar; }],
    ['_obs', 'Con observaciones', function (t) { return t.con_observaciones; }]
  ];
  function pasaFiltro(t) {
    if (!S.filtro) return true;
    const m = FILTROS_MARCA.find(function (f) { return f[0] === S.filtro; });
    return m ? m[2](t) : t.estado === S.filtro;
  }
  function tablero() {
    const D = S.D, ts = D.tareas;
    const orden = ['hecha', 'lista', 'en_curso', 'esperando', 'bloqueada', 'no_aplica'];
    const cuenta = function (e) { return ts.filter(function (t) { return t.estado === e; }).length; };
    const chip = function (clave, texto, n) {
      return h('button', { type: 'button', 'aria-pressed': String(S.filtro === clave), onclick: function () { S.filtro = clave; dibujar(); } }, texto + ' · ' + n);
    };
    const filtros = h('div', { class: 'filtros', role: 'group', 'aria-label': 'Filtrar tareas' },
      chip('', 'Todas', ts.length),
      orden.filter(function (e) { return cuenta(e) > 0; }).map(function (e) { return chip(e, nomEstado(e), cuenta(e)); }),
      h('span', { class: 'sep', 'aria-hidden': 'true' }),
      FILTROS_MARCA.map(function (f) { return chip(f[0], f[1], ts.filter(f[2]).length); }));
    const filas = [];
    D.grupos.forEach(function (g) {
      const l = ts.filter(function (t) { return t.grupo === g && pasaFiltro(t); });
      if (!l.length) return;
      filas.push(h('tr', { class: 'grp' }, h('td', { colspan: '5' }, g)));
      l.forEach(function (t) {
        filas.push(h('tr', { class: 'fila' },
          h('td', { class: 'c-cod' }, h('span', { class: 'cod' }, t.codigo)),
          h('td', { class: 'c-nom' }, h('button', { class: 'tn', type: 'button', onclick: function () { abrirFicha(t.codigo); } }, t.nombre), marcaEspera(t)),
          h('td', { class: 'c-est' }, pildora(t.estado), marcas(t)),
          h('td', { class: 'col-modo' }, nomModo(t.modo)),
          h('td', { class: 'c-det ' + (t.estado === 'bloqueada' ? 'fr' : t.estado === 'esperando' ? 'es' : '') }, t.detalle)));
      });
    });
    return h('div', null, filtros,
      filas.length
        ? h('div', { class: 'tabla' }, h('table', null,
          h('thead', null, h('tr', null, h('th', null, 'Código'), h('th', null, 'Tarea'), h('th', null, 'Estado'), h('th', { class: 'col-modo' }, 'Cómo se hace'), h('th', null, 'Detalle'))),
          h('tbody', null, filas)))
        : h('div', { class: 'vacio' }, h('p', null, 'No hay tareas con ese filtro.')));
  }

  // ------------------------------------------------------------ MAPA
  const GLIFO = { hecha: 'M-4 0 L-1 3 L4 -3', en_curso: 'M-2.5 -4 L4 0 L-2.5 4 Z', lista: 'M-2.5 -4 L4 0 L-2.5 4 Z', esperando: 'M0 -4 V0 L3 2', bloqueada: 'M-3 -3 L3 3 M3 -3 L-3 3', no_aplica: 'M-4 0 H4' };
  function cierre(ts, clave) {
    const por = {}; ts.forEach(function (t) { por[t.codigo] = t; });
    const memo = {};
    const f = function (c) {
      if (memo[c]) return memo[c];
      const s = new Set(); memo[c] = s;
      (clave === 'asc' ? por[c].necesita : por[c].necesitada_por || []).forEach(function (x) {
        if (!por[x]) return; s.add(x); f(x).forEach(function (y) { s.add(y); });
      });
      return s;
    };
    return f;
  }
  function mapa() {
    const D = S.D, ts = D.tareas;
    const por = {}; ts.forEach(function (t) { por[t.codigo] = t; });
    const asc = cierre(ts, 'asc'), desc = cierre(ts, 'desc');
    const cols = [];
    ts.forEach(function (t) { (cols[t.nivel] = cols[t.nivel] || []).push(t); });
    const W = 204, H = 54, GX = 84, GY = 18, top = 46, pos = {}, ord = {};
    cols.forEach(function (c, i) {
      if (!c) return;
      if (i) c.sort(function (a, b) {
        const m = function (t) { return t.necesita.length ? t.necesita.reduce(function (s, d) { return s + (ord[d] || 0); }, 0) / t.necesita.length : 0; };
        return m(a) - m(b);
      });
      c.forEach(function (t, j) { ord[t.codigo] = j; pos[t.codigo] = { x: 16 + i * (W + GX), y: top + j * (H + GY) }; });
    });
    const ncols = cols.length;
    const alto = top + Math.max.apply(null, cols.map(function (c) { return c ? c.length : 0; })) * (H + GY) + 6;
    const ancho = 16 + ncols * (W + GX) - GX + 16;
    const sel = por[S.sel] ? S.sel : ts[0].codigo;
    const A = asc(sel), De = desc(sel);
    const enCamino = function (c) { return c === sel || A.has(c) || De.has(c); };

    const svg = sv('svg', { width: ancho, height: alto, viewBox: '0 0 ' + ancho + ' ' + alto, role: 'group', 'aria-label': 'Mapa de dependencias entre tareas' });
    const defs = sv('defs');
    [['fn', 'var(--na)'], ['fa', 'var(--acento)'], ['fr', 'var(--bloq)']].forEach(function (m) {
      defs.appendChild(sv('marker', { id: m[0], viewBox: '0 0 8 8', refX: '1', refY: '4', markerWidth: '7', markerHeight: '7', orient: 'auto' }, sv('path', { d: 'M0 0 L8 4 L0 8 Z', fill: m[1] })));
    });
    svg.appendChild(defs);
    cols.forEach(function (c, i) { if (c) svg.appendChild(sv('text', { class: 'capa', x: 16 + i * (W + GX), y: 22 }, i ? 'Después · ' + i : 'Sin requisitos')); });
    // Ruteo ortogonal SOLO por pasillos: el vertical entre columnas (GX) y el horizontal
    // entre filas (GY). Nada pasa por dentro de la caja de otra tarea.
    const nfilas = Math.max.apply(null, cols.map(function (c) { return c ? c.length : 0; }));
    const gap0 = function (g) { return 16 + g * (W + GX) + W; };
    const yPasillo = function (k) { return top + k * (H + GY) - GY / 2; };
    const arcos = [], usoGap = {}, usoPas = {};
    ts.forEach(function (t) {
      t.necesita.forEach(function (d) {
        const o = por[d]; if (!o) return;
        const ca = o.nivel, cb = t.nivel, ra = ord[d], rb = ord[t.codigo];
        const arco = { o: d, t: t.codigo, ca: ca, cb: cb, ra: ra, rb: rb, salto: cb - ca > 1 };
        arco.ga = ca; arco.gb = cb - 1;
        (usoGap[arco.ga] = usoGap[arco.ga] || []).push({ arco: arco, lado: 'a' });
        if (arco.salto) {
          const lo = Math.min(ra, rb), hi = Math.max(ra, rb);
          arco.k = lo === hi ? lo : lo + 1 + Math.floor((hi - lo - 1) / 2);
          (usoGap[arco.gb] = usoGap[arco.gb] || []).push({ arco: arco, lado: 'b' });
          (usoPas[arco.k] = usoPas[arco.k] || []).push(arco);
        }
        arcos.push(arco);
      });
    });
    Object.keys(usoGap).forEach(function (g) {
      const l = usoGap[g], n = l.length, paso = n > 1 ? Math.min(10, 60 / (n - 1)) : 0;
      const ini = gap0(+g) + 10 + (60 - paso * (n - 1)) / 2;
      l.forEach(function (u, i) { u.arco['x' + u.lado] = ini + i * paso; });
    });
    Object.keys(usoPas).forEach(function (k) {
      const l = usoPas[k], n = l.length, paso = n > 1 ? Math.min(4, 12 / (n - 1)) : 0;
      l.forEach(function (arco, i) { arco.yc = yPasillo(+k) - paso * (n - 1) / 2 + i * paso; });
    });
    function redondeada(pts) {
      const p = [pts[0]];
      pts.slice(1).forEach(function (q) { const l = p[p.length - 1]; if (q[0] !== l[0] || q[1] !== l[1]) p.push(q); });
      for (let i = p.length - 2; i > 0; i--) {
        if ((p[i - 1][0] === p[i][0] && p[i][0] === p[i + 1][0]) || (p[i - 1][1] === p[i][1] && p[i][1] === p[i + 1][1])) p.splice(i, 1);
      }
      const dist = function (u, v) { return Math.abs(u[0] - v[0]) + Math.abs(u[1] - v[1]); };
      const paso = function (u, v, r) { const l = dist(u, v) || 1; return [u[0] + (v[0] - u[0]) / l * r, u[1] + (v[1] - u[1]) / l * r]; };
      let d = 'M' + p[0][0] + ',' + p[0][1];
      for (let i = 1; i < p.length - 1; i++) {
        const r = Math.min(7, dist(p[i - 1], p[i]) / 2, dist(p[i], p[i + 1]) / 2);
        const e = paso(p[i], p[i - 1], r), f = paso(p[i], p[i + 1], r);
        d += ' L' + e[0] + ',' + e[1] + ' Q' + p[i][0] + ',' + p[i][1] + ' ' + f[0] + ',' + f[1];
      }
      return d + ' L' + p[p.length - 1][0] + ',' + p[p.length - 1][1];
    }
    const trazos = arcos.map(function (arco) {
      const a = pos[arco.o], b = pos[arco.t], t = por[arco.t], o = por[arco.o];
      const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x - 7, y2 = b.y + H / 2;
      const enc = enCamino(arco.o) && enCamino(arco.t) && (arco.o === sel || arco.t === sel || A.has(arco.t) || De.has(arco.o));
      const frena = !resuelta(o);
      let pts;
      if (!arco.salto) pts = [[x1, y1], [arco.xa, y1], [arco.xa, y2], [x2, y2]];
      else pts = [[x1, y1], [arco.xa, y1], [arco.xa, arco.yc], [arco.xb, arco.yc], [arco.xb, y2], [x2, y2]];
      return { enc: enc, nodo: sv('path', { class: 'e' + (frena ? ' frena' : '') + (enc ? ' camino' : ' tenue'), d: redondeada(pts), 'data-o': arco.o, 'data-d': arco.t, 'marker-end': 'url(#' + (enc ? (frena ? 'fr' : 'fa') : 'fn') + ')' }) };
    });
    trazos.filter(function (x) { return !x.enc; }).concat(trazos.filter(function (x) { return x.enc; })).forEach(function (x) { svg.appendChild(x.nodo); });
    ts.forEach(function (t) {
      const p = pos[t.codigo], nom = t.nombre.length > 23 ? t.nombre.slice(0, 22) + '…' : t.nombre;
      const g = sv('g', { class: 'n ' + t.estado + (t.codigo === sel ? ' sel' : '') + (enCamino(t.codigo) ? '' : ' tenue'), tabindex: '0', role: 'button', 'aria-pressed': String(t.codigo === sel), 'aria-label': t.nombre + ': ' + nomEstado(t.estado) });
      g.appendChild(sv('title', null, t.nombre));
      g.appendChild(sv('rect', { class: 'caja', x: p.x, y: p.y, width: W, height: H, rx: 10 }));
      g.appendChild(sv('circle', { class: 'g', cx: p.x + 24, cy: p.y + H / 2, r: 12 }));
      g.appendChild(sv('path', { class: 'gi', transform: 'translate(' + (p.x + 24) + ',' + (p.y + H / 2) + ')', d: GLIFO[t.estado] || GLIFO.no_aplica }));
      g.appendChild(sv('text', { class: 'tit', x: p.x + 46, y: p.y + 23 }, nom));
      g.appendChild(sv('text', { class: 'sub', x: p.x + 46, y: p.y + 39 }, nomEstado(t.estado) + ' · ' + nomModo(t.modo)));
      const elegir = function () { S.sel = t.codigo; S.enfocar = '[data-n="' + t.codigo + '"]'; sincronizarUrl(); dibujar(); };
      g.setAttribute('data-n', t.codigo);
      g.addEventListener('click', elegir);
      g.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); elegir(); } });
      svg.appendChild(g);
    });

    const s = por[sel];
    const selResuelta = s.estado === "hecha" || s.estado === "no_aplica";
    const f = (selResuelta ? [] : (s.camino || [])).map(function (c) { return por[c] ? por[c].nombre : c; });
    const lateral = h('aside', { class: 'mficha' + (S.anim ? ' entra' : '') },
      h('div', null, h('p', { class: 'rot' }, s.codigo + ' · ' + s.grupo + ' · ' + nomModo(s.modo)), h('h2', { class: 'disp' }, s.nombre)),
      h('div', { class: 'fila' }, pildora(s.estado), ' ', marcas(s)),
      h('p', null, f.length ? 'Está frenada por ' + f.join(' y ') + '.' : (s.detalle || 'Sin datos todavía.')),
      h('div', null, h('h3', null, 'Necesita'), s.necesita.length ? h('ul', null, s.necesita.map(function (c) { const x = por[c]; return h('li', null, (x ? x.nombre : c) + ' ', h('span', { class: 'muted' }, '· ' + (x ? nomEstado(x.estado).toLowerCase() : ''))); })) : h('p', { class: 'muted' }, 'Nada.')),
      h('div', null, h('h3', null, 'Destraba'), (s.necesitada_por || []).length ? h('ul', null, s.necesitada_por.map(function (c) { return h('li', null, por[c] ? por[c].nombre : c); })) : h('p', { class: 'muted' }, 'Ninguna otra depende de esta.')),
      h('div', { class: 'acc' }, h('button', { class: 'btn p', type: 'button', onclick: function () { abrirFicha(s.codigo); } }, 'Abrir la ficha')),
      pm('mapa', s.codigo));
    const orden = ['hecha', 'lista', 'en_curso', 'esperando', 'bloqueada', 'no_aplica'];
    return h('div', null,
      h('div', { class: 'ley' }, orden.map(function (e) { return pildora(e); })),
      h('div', { class: 'mapag' },
        h('div', null, h('div', { class: 'lienzo', tabindex: '-1' }, svg),
          h('p', { class: 'nota', style: 'margin-top:8px' }, 'La flecha va de lo que se necesita a lo que lo necesita. Al tocar una tarea se ilumina su camino: de qué depende y qué destraba. Línea roja cortada: todavía frena.')),
        lateral));
  }

  // ------------------------------------------------------------ dibujo general
  function dibujar() { conFoco(dibujarCore); }
  function dibujarCore() {
    barra();
    const cont = $('x-vista');
    if (S.cargando) { cont.replaceChildren(esqueleto()); return; }
    if (S.error) { cont.replaceChildren(bloqueError(S.error, function () { cargar(false); })); return; }
    const D = S.D;
    if (!D.disponible) {
      cont.replaceChildren(h('div', { class: 'vacio' }, h('p', { class: 'rot' }, 'Sin tablero'),
        h('h2', { class: 'disp vacio-t' }, 'Este proyecto todavía no tiene tablero'), h('p', null, D.motivo || 'El proyecto no tiene un sindicato de Colm3na asociado.'),
        h('a', { class: 'btn', href: D.proyecto.mesa_url, target: '_blank', rel: 'noopener' }, 'Abrir la Mesa')));
      return;
    }
    let nodo;
    if (S.vista === 'tablero') nodo = h('div', { class: S.anim ? 'entra' : '' }, tablero());
    else if (S.vista === 'mapa') nodo = h('div', { class: S.anim ? 'entra' : '' }, mapa());
    else {
      nodo = guia();
      const cond = nodo.querySelector('#x-cond');
      if (S.abierta && tarea(S.abierta)) cond.appendChild(ficha(tarea(S.abierta)));
      else cond.append.apply(cond, heroe().filter(Boolean));
      const rcp = S.rc && S.rc.origen === 'pano' ? bloqueReclamo(S.rc.clave, 'pano') : null;
      if (rcp) cond.insertBefore(rcp, cond.firstChild);
    }
    cont.replaceChildren.apply(cont, [nodoExito(), nodo].filter(Boolean));
    S.anim = false;
    enfocar();
  }

  // ------------------------------------------------------------ arranque
  document.querySelectorAll('.vistas button').forEach(function (b) {
    b.addEventListener('click', function () {
      const v = b.dataset.v;
      if (v === 'guia' && S.vista === 'guia') { if (S.abierta) volverGuia(); return; }
      irVista(v);
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    if (S.abierta && asDe(S.abierta)) return;
    const a = e.target;
    if (a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))) return;
    moverPaso(e.key === 'ArrowLeft' ? -1 : 1);
  });
  leerUrl();
  barra();
  cargar(false).then(function () { sincronizarUrl(); });
})();
