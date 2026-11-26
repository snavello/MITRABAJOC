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
    det: {}, form: null, insForm: null, anim: false, enfocar: null, enviando: false, abiertos: {}
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

  class ErrorX extends Error { constructor(m, st) { super(m); this.status = st; } }
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
      throw new ErrorX(d || (r.status >= 500 ? 'El servidor no respondió (HTTP ' + r.status + '). Probá de nuevo en un momento.' : 'No se pudo completar la acción (HTTP ' + r.status + ').'), r.status);
    }
    if (cuerpo === null) throw new ErrorX('El servidor no respondió como se esperaba (HTTP ' + r.status + ').', r.status);
    return cuerpo;
  }
  const pedir = function (ruta) { return pedirJson(BASE + ruta, { cache: 'no-store' }); };
  const enviar = function (ruta, cuerpo) {
    return pedirJson(BASE + ruta, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
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
    S.abierta = codigo; S.vista = 'guia'; S.form = null; S.insForm = null; S.anim = true; S.errorAccion = '';
    sincronizarUrl(); dibujar(); window.scrollTo({ top: 0 });
    cargarHistorial(codigo);
  }
  function volverGuia() { S.abierta = null; S.form = null; S.insForm = null; S.anim = true; sincronizarUrl(); dibujar(); }
  function irVista(v) {
    if (S.vista === v) return;
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
  function pildora(estado) { return h('span', { class: 'pil ' + estado }, nomEstado(estado)); }
  function marcas(t) {
    const m = [];
    if (t.a_mano) m.push(h('span', { class: 'marca-t mano' }, 'A mano'));
    if (t.pospuesta) m.push(h('span', { class: 'marca-t' }, 'Pospuesta'));
    if (t.falta_confirmar) m.push(h('span', { class: 'marca-t conf' }, 'Falta confirmar'));
    if (t.con_observaciones) m.push(h('span', { class: 'marca-t conf' }, 'Con observaciones'));
    return m.length ? h('span', { class: 'marcas' }, m) : null;
  }
  function preguntame() {
    return h('div', { class: 'pm' },
      h('button', { type: 'button', disabled: true }, 'Preguntame'),
      h('span', null, 'Llega en el próximo bloque'));
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
  function heroe() {
    const D = S.D, rec = D.recomendada;
    if (!rec) {
      return [h('div', { class: 'vacio' }, h('p', { class: 'rot' }, 'Siguiente paso'),
        h('h2', { class: 'disp vacio-t' }, 'No queda nada para hacer ahora'),
        h('p', null, 'Todo lo que aplica está resuelto, o lo que queda espera un dato o a otra tarea. Mirá el tablero para ver qué falta.'),
        h('div', { class: 'acc' }, h('button', { class: 'btn', type: 'button', onclick: function () { irVista('tablero'); } }, 'Ver el tablero')))];
    }
    const t = tarea(rec.codigo);
    const otras = (D.alternativas || []).map(tarea).filter(Boolean).slice(0, 3);
    return [
      h('div', { class: 'heroe' + (S.anim ? ' entra' : '') },
        h('button', { class: 'play', type: 'button', 'aria-label': 'Empezar: ' + (t ? t.nombre : rec.codigo), onclick: function () { abrirFicha(rec.codigo); } }, PLAY()),
        h('div', { class: 'cuerpo' },
          h('p', { class: 'rot' }, 'Siguiente paso recomendado'),
          h('h2', { class: 'disp' }, t ? t.nombre : rec.codigo),
          h('p', null, rec.por_que), h('p', { class: 'muted' }, rec.como),
          preguntame())),
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
          return h('li', null, h('button', { type: 'button', onclick: function () { abrirFicha(t.codigo); } }, h('b', null, t.nombre), h('small', null, t.detalle)));
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
              h('a', { class: 'btn ch', href: D.proyecto.mesa_url, target: '_blank', rel: 'noopener' }, 'Reclamar en la Mesa'))));
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
    if (!t.insumos.length) return null;
    return h('div', { class: 'bloque' }, h('h3', null, 'Insumos'),
      t.insumos.map(function (i) {
        const reg = i.estado !== 'falta';
        const f = S.insForm && S.insForm.clave === i.clave ? S.insForm : null;
        let estadoTxt = i.estado === 'recibido' ? 'Recibido' : i.estado === 'pedido' ? pedidoTxt(i.dias || 0) : 'Falta';
        return h('div', { class: 'ins ' + i.estado },
          h('div', { class: 't' }, h('b', null, i.nombre), h('span', { class: 'est' }, estadoTxt)),
          i.descripcion ? h('p', { class: 'nota' }, i.descripcion) : null,
          i.sin_registrar ? h('p', { class: 'sr-aviso' }, 'Hay datos cargados, pero el insumo no está registrado.') : null,
          i.tarjeta ? h('p', { class: 'nota' }, 'Tarjeta de la Mesa: ',
            h('a', { href: i.tarjeta.url, target: '_blank', rel: 'noopener' }, i.tarjeta.codigo), ' ', i.tarjeta.titulo || '') : null,
          i.nota ? h('p', { class: 'nota' }, 'Nota: ' + i.nota) : null,
          reg && i.quien ? h('p', { class: 'nota' }, 'Registró ' + i.quien + ' el ' + cuando(i.cuando) + '.') : null,
          f ? formInsumo(t, i, f) : h('div', { class: 'acc' },
            i.estado !== 'recibido' ? h('button', { class: 'btn ch', type: 'button', disabled: S.enviando, onclick: function () { marcarInsumo(t.codigo, i.clave, 'recibido'); } }, 'Marcar recibido') : null,
            i.estado !== 'pedido' ? h('button', { class: 'btn ch', type: 'button', disabled: S.enviando, onclick: function () { S.insForm = { clave: i.clave, tarjeta: '', nota: '', error: '' }; S.enfocar = '#x-ins-tarjeta'; dibujarFicha(); } }, 'Marcar pedido') : null,
            reg && !i.sin_registrar ? h('button', { class: 'btn ch', type: 'button', disabled: S.enviando, onclick: function () { retirarInsumo(t.codigo, i.clave); } }, 'Quitar registro') : null));
      }));
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
    return h('div', { class: 'bloque' + (na ? ' atenuado' : '') }, h('h3', null, rotulo),
      h('p', null, h('b', { class: r[1] }, r[0]), c.resumen ? ' · ' + c.resumen : ''),
      (c.cifras || []).length ? h('div', { class: 'kpis' }, c.cifras.map(function (k) { return h('div', { class: 'kpi' }, h('b', null, num(k.valor)), h('span', null, k.nombre)); })) : null,
      (c.faltan || []).length ? h('div', null, h('p', { class: 'rot' }, 'Falta'), h('ul', { class: 'faltan' }, c.faltan.map(function (x) { return h('li', null, x); }))) : null);
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
    return h('div', { class: 'bloque' }, h('h3', null, 'Decisiones activas'),
      ds.map(function (d) {
        return h('div', { class: 'dec' }, h('b', null, nomDec(d.tipo)), ' · ' + (d.quien || '') + ' · ' + cuando(d.cuando),
          d.motivo ? h('div', { class: 'muted' }, d.motivo) : null);
      }),
      t.a_mano ? h('p', { class: 'nota' }, 'Quedó marcada como hecha a mano. El control, arriba, sigue diciendo lo que ve en el sistema.') : null);
  }
  function seccionHistorial(t) {
    const d = S.det[t.codigo];
    return h('div', { class: 'bloque' }, h('h3', null, 'Historial de la tarea'),
      !d || d.cargando ? h('div', { class: 'esq' }, h('i'), h('i')) :
        d.error ? h('p', { class: 'err', style: 'color:var(--bloq)' }, d.error) :
          d.historial.length ? h('ul', { class: 'hist' }, d.historial.map(function (m) {
            return h('li', null, m.texto, h('small', null, cuando(m.cuando) + (m.quien ? ' · ' + m.quien : '')));
          })) : h('p', { class: 'muted' }, 'Todavía no hay movimientos en esta tarea.'));
  }
  function ficha(t) {
    const frenos = (t.camino || []).map(function (c) { const x = tarea(c); return x ? x.nombre : c; });
    return h('div', { class: 'ficha' + (S.anim ? ' entra' : '') },
      h('div', { class: 'acc' }, h('button', { class: 'btn ch', type: 'button', onclick: volverGuia }, 'Volver a la guía')),
      h('div', { class: 'cab' },
        h('p', { class: 'rot' }, t.codigo + ' · ' + t.grupo + ' · ' + nomModo(t.modo)),
        h('h2', { class: 'disp' }, t.nombre),
        h('div', { class: 'fila' }, pildora(t.estado), marcas(t))),
      t.descripcion ? h('p', null, t.descripcion) : null,
      t.detalle ? h('p', { class: 'muted' }, t.detalle) : null,
      (t.avisos || []).map(function (a) { return h('div', { class: 'aviso' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, 'i'), h('div', null, a)); }),
      frenos.length && !resuelta(t) ? h('p', { class: 'nota' }, 'Para llegar acá antes hay que resolver, en este orden: ' + frenos.join(', ') + '.') : null,
      h('div', { class: 'dos' },
        h('div', null, h('h3', null, 'Necesita'), listaTareas(t.necesita || [], 'No necesita nada antes.')),
        h('div', null, h('h3', null, 'Destraba'), listaTareas((t.destraba && t.destraba.directo) || [], 'No hay otra tarea esperándola.'))),
      seccionInsumos(t),
      seccionControl(t),
      t.confirmacion ? h('div', { class: 'bloque' }, h('h3', null, 'Lo que hay que confirmar'),
        h('p', null, t.confirmacion), t.falta_confirmar ? h('p', { class: 'nota' }, 'Todavía nadie lo confirmó.') : null,
        !(t.acciones && t.acciones.confirmar) && (t.insumos || []).some(function (i) { return i.estado === 'falta' || i.estado === 'pedido'; })
          ? h('p', { class: 'nota nec' }, 'Primero registrá que llegó el insumo.') : null) : null,
      t.donde ? h('div', { class: 'acc' }, h('a', { class: 'btn donde' + (t.estado === 'no_aplica' ? '' : ' p'), href: t.donde.url, target: '_blank', rel: 'noopener' }, 'Ir a la pantalla'),
        h('span', { class: 'nota' }, t.donde.rotulo)) : null,
      seccionDecisiones(t),
      seccionAcciones(t),
      seccionHistorial(t),
      preguntame());
  }
  function dibujarFicha() {
    const cont = $('x-cond');
    if (!cont || !S.abierta) return;
    const t = tarea(S.abierta);
    if (!t) return;
    cont.replaceChildren(ficha(t));
    enfocar();
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
          h('td', { class: 'c-nom' }, h('button', { class: 'tn', type: 'button', onclick: function () { abrirFicha(t.codigo); } }, t.nombre)),
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
    const resuelta = s.estado === 'hecha' || s.estado === 'no_aplica';
    const f = (resuelta ? [] : (s.camino || [])).map(function (c) { return por[c] ? por[c].nombre : c; });
    const lateral = h('aside', { class: 'mficha' + (S.anim ? ' entra' : '') },
      h('div', null, h('p', { class: 'rot' }, s.codigo + ' · ' + s.grupo + ' · ' + nomModo(s.modo)), h('h2', { class: 'disp' }, s.nombre)),
      h('div', { class: 'fila' }, pildora(s.estado), ' ', marcas(s)),
      h('p', null, f.length ? 'Está frenada por ' + f.join(' y ') + '.' : (s.detalle || 'Sin datos todavía.')),
      h('div', null, h('h3', null, 'Necesita'), s.necesita.length ? h('ul', null, s.necesita.map(function (c) { const x = por[c]; return h('li', null, (x ? x.nombre : c) + ' ', h('span', { class: 'muted' }, '· ' + (x ? nomEstado(x.estado).toLowerCase() : ''))); })) : h('p', { class: 'muted' }, 'Nada.')),
      h('div', null, h('h3', null, 'Destraba'), (s.necesitada_por || []).length ? h('ul', null, s.necesitada_por.map(function (c) { return h('li', null, por[c] ? por[c].nombre : c); })) : h('p', { class: 'muted' }, 'Ninguna otra depende de esta.')),
      h('div', { class: 'acc' }, h('button', { class: 'btn p', type: 'button', onclick: function () { abrirFicha(s.codigo); } }, 'Abrir la ficha')),
      preguntame());
    const orden = ['hecha', 'lista', 'en_curso', 'esperando', 'bloqueada', 'no_aplica'];
    return h('div', null,
      h('div', { class: 'ley' }, orden.map(function (e) { return pildora(e); })),
      h('div', { class: 'mapag' },
        h('div', null, h('div', { class: 'lienzo', tabindex: '-1' }, svg),
          h('p', { class: 'nota', style: 'margin-top:8px' }, 'La flecha va de lo que se necesita a lo que lo necesita. Al tocar una tarea se ilumina su camino: de qué depende y qué destraba. Línea roja cortada: todavía frena.')),
        lateral));
  }

  // ------------------------------------------------------------ dibujo general
  function dibujar() {
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
    }
    cont.replaceChildren(nodo);
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
  leerUrl();
  barra();
  cargar(false).then(function () { sincronizarUrl(); });
})();
