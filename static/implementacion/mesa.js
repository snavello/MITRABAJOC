/* Mesa de implementación (PLAN_IMPLEMENTACION.md, bloque 3).
   Una sola página con vistas por hash: #pendientes, #tablero, #plan,
   #carpetas, #aprobaciones, #nueva y #t<número> (una tarjeta).
   Reglas: la pantalla NO decide permisos (dibuja lo que `acciones` dice);
   todo texto de una persona entra con nodos de texto, nunca como HTML; toda
   respuesta del servidor pasa por pedirJson(). */
(function () {
  'use strict';

  // ---------------------------------------------------------------- datos
  let DATOS = {};
  try { DATOS = JSON.parse(document.getElementById('impl-datos').textContent) || {}; } catch (e) { DATOS = {}; }
  const LADO = DATOS.lado || 'sindicato';
  const ES_EQUIPO = LADO === 'equipo';
  const PROYECTO = DATOS.proyecto || null;
  const PID = PROYECTO ? PROYECTO.id : null;
  const BASE = '/api/implementacion/p/' + PID + '/';
  const TOPE_ARCHIVO = 20 * 1024 * 1024;
  const TOPE_TOTAL = 40 * 1024 * 1024;
  const TOPE_CANTIDAD = 5;
  // Mismo chequeo que hace el servidor, antes de subir nada.
  function pesoArchivos(files) {
    if (files.length > TOPE_CANTIDAD) return 'Podés subir hasta ' + TOPE_CANTIDAD + ' archivos por vez. Elegiste ' + files.length + '.';
    let total = 0;
    for (const a of files) { if (a.size > TOPE_ARCHIVO) return '«' + a.name + '» pesa más de 20 MB.'; total += a.size; }
    if (total > TOPE_TOTAL) return 'Los archivos juntos pesan más de 40 MB. Mandalos en dos veces.';
    return '';
  }

  const TIPOS = {};
  const ORDEN_TIPOS = [];
  (DATOS.tipos || []).forEach(function (t) { if (t && t.clave) { TIPOS[t.clave] = t; ORDEN_TIPOS.push(t.clave); } });

  const ESTADOS_BASE = { abierta: 'Abierta', en_curso: 'En curso', respondida: 'Respondida', cerrada: 'Cerrada', aprobada: 'Aprobada', rechazada: 'Rechazada' };
  const NOMBRES_ESTADO = Object.assign({}, ESTADOS_BASE);
  (function () {
    const e = DATOS.estados;
    if (Array.isArray(e)) {
      e.forEach(function (x) { if (x && typeof x === 'object') { const k = x.clave || x.estado || x.id; if (k && x.nombre) NOMBRES_ESTADO[k] = x.nombre; } });
    } else if (e && typeof e === 'object') {
      Object.keys(e).forEach(function (k) { if (typeof e[k] === 'string') NOMBRES_ESTADO[k] = e[k]; });
    }
  })();
  const nombreEstado = function (k) { return NOMBRES_ESTADO[k] || (k ? k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' ') : ''); };
  const ABIERTOS = ['abierta', 'en_curso', 'respondida'];

  const S = { token: 0, ultima: null, actual: null, todas: null, plan: null, etapaSel: null, editarPlan: false, sentido: 'entrada' };

  // ---------------------------------------------------------------- DOM
  const $vista = document.getElementById('vista');
  const $aviso = document.getElementById('aviso');
  const $globo = document.getElementById('globo');

  function h(tag, props) {
    const e = document.createElement(tag);
    if (props) Object.keys(props).forEach(function (k) {
      const v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') e.className = v;
      else if (k === 'estilo') Object.keys(v).forEach(function (p) { e.style.setProperty(p, v[p]); });
      else if (k.slice(0, 2) === 'on' && typeof v === 'function') e.addEventListener(k.slice(2), v);
      else if (v === true) e.setAttribute(k, '');
      else e.setAttribute(k, String(v));
    });
    for (let i = 2; i < arguments.length; i++) agregar(e, arguments[i]);
    return e;
  }
  function agregar(e, k) {
    if (k === null || k === undefined || k === false) return;
    if (Array.isArray(k)) { k.forEach(function (x) { agregar(e, x); }); return; }
    e.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  const NS = 'http://www.w3.org/2000/svg';
  function icono(nombre, clase) {
    const s = document.createElementNS(NS, 'svg');
    s.setAttribute('class', 'ic' + (clase ? ' ' + clase : ''));
    s.setAttribute('aria-hidden', 'true');
    const u = document.createElementNS(NS, 'use');
    u.setAttribute('href', '#i-' + nombre);
    s.appendChild(u);
    return s;
  }
  function vaciar(e) { e.replaceChildren(); return e; }

  // ---------------------------------------------------------------- formato
  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const ANIO = new Date().getFullYear();
  function fechaCorta(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || '');
    if (!m) return s || '';
    return (+m[3]) + ' ' + MESES[+m[2] - 1] + (+m[1] !== ANIO ? ' ' + m[1] : '');
  }
  function fechaHora(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(s || '');
    if (!m) return fechaCorta(s);
    return (+m[3]) + ' ' + MESES[+m[2] - 1] + (+m[1] !== ANIO ? ' ' + m[1] : '') + ', ' + m[4] + ':' + m[5];
  }
  function tamano(n) {
    n = +n || 0;
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
    return (n / 1048576).toFixed(1).replace('.', ',') + ' MB';
  }
  const cap = function (s) { s = s || ''; return s.charAt(0).toUpperCase() + s.slice(1); };
  const ladoNombre = function (l) { return l === 'equipo' ? 'Colm3na' : (l === 'sindicato' ? 'Sindicato' : ''); };

  // ---------------------------------------------------------------- red
  function ErrorMesa(mensaje, status) { this.message = mensaje; this.status = status || 0; }
  ErrorMesa.prototype = Object.create(Error.prototype);
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
      // P-14: sin red del dispositivo no es lo mismo que un servidor que no contesta.
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        throw new ErrorMesa('Sin conexión: tu dispositivo no tiene internet. Revisalo y probá de nuevo.', 0);
      }
      throw new ErrorMesa('El servidor no respondió. Probá de nuevo en un momento.', 0);
    }
    if (r.status === 401) {
      // Al ENVIAR no se saca a la persona de la pantalla: perdería lo que escribió.
      const entrada = ES_EQUIPO ? '/entornos' : '/implementacion/ingresar';
      if (opciones && opciones.method === 'POST') {
        throw new ErrorMesa('Tu sesión venció. Abrí ' + entrada + ' en otra pestaña, entrá de nuevo y volvé a enviar: lo que escribiste sigue acá.', 401);
      }
      window.location.href = entrada;
      throw new ErrorMesa('Tu sesión venció. Volvé a entrar.', 401);
    }
    let cuerpo = null;
    if ((r.headers.get('content-type') || '').indexOf('json') !== -1) {
      try { cuerpo = await r.json(); } catch (e) { cuerpo = null; }
    }
    if (!r.ok) {
      const d = cuerpo && detalle(cuerpo.detail);
      throw new ErrorMesa(d || (r.status >= 500
        ? 'El servidor no respondió (HTTP ' + r.status + '). Probá de nuevo en un momento.'
        : 'No se pudo completar la acción (HTTP ' + r.status + ').'), r.status);
    }
    if (cuerpo === null) throw new ErrorMesa('El servidor no respondió como se esperaba (HTTP ' + r.status + ').', r.status);
    return cuerpo;
  }
  const pedir = function (ruta) { return pedirJson(BASE + ruta, { cache: 'no-store' }); };
  const enviarJson = function (ruta, cuerpo) {
    return pedirJson(BASE + ruta, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
  };
  const enviarForm = function (ruta, fd) { return pedirJson(BASE + ruta, { method: 'POST', body: fd }); };

  // ---------------------------------------------------------------- avisos y diálogo
  let tAviso = null;
  function avisar(texto, mal) {
    $aviso.textContent = texto;
    $aviso.className = 'aviso on' + (mal ? ' mal' : '');
    $aviso.hidden = false;
    clearTimeout(tAviso);
    tAviso = setTimeout(function () { $aviso.hidden = true; }, mal ? 7000 : 3500);
  }
  function errorEn(contenedor, texto) {
    let e = contenedor.querySelector(':scope > .err');
    if (!texto) { if (e) e.remove(); return; }
    if (!e) { e = h('div', { class: 'err', role: 'alert' }); contenedor.appendChild(e); }
    e.textContent = texto;
  }

  const $dlg = document.getElementById('dlg');
  function confirmar(o) {
    return new Promise(function (resolver) {
      document.getElementById('dlg-t').textContent = o.titulo;
      document.getElementById('dlg-p').textContent = o.texto || '';
      const $m = document.getElementById('dlg-motivo');
      const $mt = document.getElementById('dlg-motivo-t');
      $m.hidden = !o.motivo;
      $mt.value = '';
      document.getElementById('dlg-motivo-l').textContent = o.motivo || '';
      const si = document.getElementById('dlg-si');
      si.textContent = o.ok || 'Confirmar';
      si.className = 'btn ' + (o.clase || 'pri');
      function cerrar(valor) {
        $dlg.removeEventListener('close', alCerrar);
        document.getElementById('dlg-no').onclick = null;
        if ($dlg.open) $dlg.close();
        resolver(valor);
      }
      function alCerrar() { resolver(null); }
      $dlg.addEventListener('close', alCerrar);
      document.getElementById('dlg-no').onclick = function () { cerrar(null); };
      document.getElementById('dlg-f').onsubmit = function (ev) { ev.preventDefault(); cerrar({ texto: $mt.value.trim() }); };
      $dlg.showModal();
      (o.motivo ? $mt : document.getElementById('dlg-no')).focus();
    });
  }

  // ---------------------------------------------------------------- globo
  function setGlobo(n) {
    n = +n || 0;
    $globo.hidden = n <= 0;
    $globo.textContent = n > 99 ? '99+' : String(n);
    $globo.setAttribute('aria-label', n + ' pendientes');
    const base = 'Mesa de implementación' + (PROYECTO ? ' — ' + PROYECTO.nombre : '');
    document.title = (n > 0 ? '(' + n + ') ' : '') + base;
  }
  async function refrescarGlobo() {
    try { const r = await pedir('resumen'); setGlobo(r.pendientes); return r; } catch (e) { return null; }
  }
  function invalidar() { S.todas = null; }

  // ---------------------------------------------------------------- piezas
  function colorTipo(el, tipo) { el.style.setProperty('--tc', 'var(--tp-' + tipo + ', #566074)'); return el; }
  function chipEspera(t) {
    if (!t.espera) return h('span', { class: 'chip ok' }, icono('check'), nombreEstado(t.estado));
    return h('span', { class: 'chip ' + (t.espera === 'sindicato' ? 'sind' : 'equipo') }, cap(t.espera_texto || ('Espera a ' + (t.espera === 'sindicato' ? 'el sindicato' : 'Colm3na'))));
  }
  function textoVence(t) {
    if (!t.fecha_limite) return h('span', { class: 'venc' }, 'Sin fecha límite');
    return h('span', { class: 'venc' + (t.vencida ? ' vencida' : '') }, (t.vencida ? 'Vencida el ' : 'Vence el ') + fechaCorta(t.fecha_limite));
  }
  function hashDeTarjeta(t) { return t.codigo ? hashDe(t.codigo) : '#t' + t.numero; }
  function tile(t, i) {
    const a = h('a', { class: 'tile entra', href: hashDeTarjeta(t), estilo: { '--i': i || 0 } },
      h('div', { class: 'hd' }, icono((TIPOS[t.tipo] || {}).icono || t.icono || 'inbox'), h('span', null, t.tipo_nombre || (TIPOS[t.tipo] || {}).nombre || t.tipo), h('span', { class: 'n cod' }, t.codigo || ('#' + t.numero))),
      h('div', { class: 'cu' },
        h('h3', null, t.titulo),
        h('div', { class: 'meta' }, chipEspera(t), t.etapa_nombre ? h('span', null, t.etapa_nombre) : null),
        textoVence(t)));
    return colorTipo(a, t.tipo);
  }
  function miniTarjeta(t) {
    const a = h('a', { class: 'mini', href: hashDeTarjeta(t) },
      h('span', { class: 'cod' }, t.codigo || ('#' + t.numero)),
      h('b', null, t.titulo),
      h('small', null, (t.tipo_nombre || '') + (t.espera ? ' · ' + cap(t.espera_texto || '') : ' · ' + nombreEstado(t.estado))),
      t.fecha_limite ? h('small', { style: t.vencida ? 'color:var(--mal)' : null }, (t.vencida ? 'Vencida el ' : 'Vence el ') + fechaCorta(t.fecha_limite)) : null);
    return colorTipo(a, t.tipo);
  }
  function vacio(frase, accion) { return h('div', { class: 'vacio' }, h('p', null, frase), accion || null); }
  function botonNueva(tipo, etiqueta) {
    return h('a', { class: 'btn pri', href: '#nueva' + (tipo ? '?tipo=' + tipo : '') }, icono('mas'), etiqueta || 'Nueva tarjeta');
  }
  function esqueleto(vista) {
    const f = h('div', { 'aria-hidden': 'true' });
    f.appendChild(h('div', { class: 'esq', estilo: { height: '44px', width: '260px' } }));
    if (vista === 'pendientes') f.appendChild(h('div', { class: 'esq-fila' }, [1, 2, 3, 4].map(function () { return h('div', { class: 'esq esq-k' }); })));
    f.appendChild(h('div', { class: 'esq-fila' }, [1, 2, 3].map(function () { return h('div', { class: 'esq esq-t' }); })));
    return f;
  }
  function estadoError(e, reintentar) {
    return h('div', { class: 'vacio' }, h('p', { role: 'alert' }, e.message || 'No se pudo cargar.'),
      reintentar ? h('button', { class: 'btn lisa', type: 'button', onclick: reintentar }, 'Probar de nuevo') : null);
  }

  // ---------------------------------------------------------------- códigos (I12 a I14)
  // El prefijo de cada tipo de tarjeta es parte del contrato (PE, CO, EN, AP, ER, AV).
  const TIPO_DE_PREFIJO = { PE: 'pedido', CO: 'consulta', EN: 'entrega', AP: 'aprobacion', ER: 'error', AV: 'aviso' };
  // I15: -N2 es una nota interna (PE0001-N2) y AI000001 un archivo subido en una; solo el equipo los
  // encuentra, para el sindicato el servidor contesta «no existe» como con cualquier código inventado.
  const CODIGO_RE = /(PE|CO|EN|AP|ER|AV)(\d{4,6})(?:-N?(\d{1,5}))?|(A[RI])(\d{6})|(HI)(\d{4})/gi;
  const CODIGO_SOLO = /^(?:(?:PE|CO|EN|AP|ER|AV)\d{4,6}(?:-N?\d{1,5})?|A[RI]\d{6}|HI\d{4})$/i;
  const esCodigo = function (s) { return CODIGO_SOLO.test((s || '').trim()); };
  const tipoDeCodigo = function (codigo) { return TIPO_DE_PREFIJO[(codigo || '').slice(0, 2).toUpperCase()] || null; };
  const hashDe = function (codigo) { return '#' + codigo; };
  const sinHash = function (s) { const i = (s || '').indexOf('#'); return i === -1 ? '' : s.slice(i + 1); };

  const REDUCIDO = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let tCopiado = null;
  async function copiarTexto(texto) {
    try {
      if (navigator.clipboard && window.isSecureContext !== false) { await navigator.clipboard.writeText(texto); return true; }
    } catch (e) { /* cae al respaldo */ }
    const ta = h('textarea', { 'aria-hidden': 'true', tabindex: '-1', readonly: true, style: 'position:fixed;left:-9999px;top:0;opacity:0' });
    ta.value = texto; document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }
  // Botón «copiar» junto a un código: confirma con un «Copiado» breve.
  function botonCopiar(texto, que) {
    const rot = h('span', { class: 'cp-t' }, 'Copiar');
    const b = h('button', { class: 'cp', type: 'button', 'aria-label': 'Copiar ' + (que || 'el código') + ' ' + texto, title: 'Copiar ' + texto,
      onclick: async function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        const ok = await copiarTexto(texto);
        b.classList.toggle('listo', ok);
        rot.textContent = ok ? 'Copiado' : 'No se pudo';
        avisarCopia(ok ? 'Copiado: ' + texto : 'No se pudo copiar. Seleccionalo y copialo a mano.', !ok);
        clearTimeout(b._t);
        b._t = setTimeout(function () { b.classList.remove('listo'); rot.textContent = 'Copiar'; }, 1600);
      } }, icono('copiar'), rot);
    return b;
  }
  function avisarCopia(texto, mal) {
    const e = document.getElementById('estado-copia');
    if (!e) return;
    e.textContent = texto; clearTimeout(tCopiado);
    tCopiado = setTimeout(function () { e.textContent = ''; }, 2500);
  }
  // El código a la vista: mono, con o sin botón. `plano` = solo texto.
  function codigo(c, opc) {
    opc = opc || {};
    if (!c) return null;
    const s = h('span', { class: 'cod' + (opc.clase ? ' ' + opc.clase : '') }, c);
    if (opc.copiar === false) return s;
    return h('span', { class: 'cod-g' }, s, botonCopiar(c, opc.que));
  }
  // Convierte los códigos de un texto en enlaces con DOM. Solo los de `refs`
  // con existe:true; los demás quedan como texto común, sin marca.
  function enlazar(texto, refs) {
    texto = texto == null ? '' : String(texto);
    const buenos = {};
    (refs || []).forEach(function (r) { if (r && r.existe && r.enlace && r.codigo) buenos[String(r.codigo).toUpperCase()] = r; });
    if (!Object.keys(buenos).length) return [document.createTextNode(texto)];
    const partes = []; let desde = 0; let m;
    CODIGO_RE.lastIndex = 0;
    while ((m = CODIGO_RE.exec(texto)) !== null) {
      const ini = m.index; const fin = ini + m[0].length;
      const antes = ini > 0 ? texto.charAt(ini - 1) : ''; const despues = fin < texto.length ? texto.charAt(fin) : '';
      if (/[A-Za-z0-9_]/.test(antes) || /[A-Za-z0-9_]/.test(despues)) continue;
      const ref = buenos[m[0].toUpperCase()];
      if (!ref) continue;
      if (ini > desde) partes.push(document.createTextNode(texto.slice(desde, ini)));
      partes.push(h('a', { class: 'cod-lnk', href: hashDe(sinHash(ref.enlace) || ref.codigo) }, m[0]));
      desde = fin;
    }
    if (desde < texto.length) partes.push(document.createTextNode(texto.slice(desde)));
    return partes;
  }
  function resaltar(el) {
    if (!el) return false;
    el.classList.remove('resalta'); void el.offsetWidth; el.classList.add('resalta');
    el.scrollIntoView({ behavior: REDUCIDO ? 'auto' : 'smooth', block: 'center' });
    setTimeout(function () { el.classList.remove('resalta'); }, 3200);
    return true;
  }
  const COLOR_SIN_TIPO = 'neutro';
  // Ícono y color de una cosa relacionada, según su clase y su código.
  function marcaDeRelacion(r) {
    const tipoTarjeta = r.tipo === 'tarjeta' || r.tipo === 'mensaje' ? tipoDeCodigo(r.codigo) : null;
    if (tipoTarjeta) return { icono: r.tipo === 'mensaje' ? 'pregunta' : ((TIPOS[tipoTarjeta] || {}).icono || 'inbox'), tipo: tipoTarjeta };
    if (r.tipo === 'archivo') return { icono: 'clip', tipo: null };
    if (r.tipo === 'hito') return { icono: 'plan', tipo: null };
    return { icono: 'inbox', tipo: null };
  }
  const ESTADOS_OTROS = { vigente: 'Vigente', borrado: 'Borrado', pendiente: 'Pendiente', hecho: 'Hecho' };

  // ---------------------------------------------------------------- montaje de vistas
  function marcarNav(vista) {
    document.querySelectorAll('.nv').forEach(function (a) {
      if (vista && a.dataset.vista === vista) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }
  async function montar(vista, constructor) {
    const mi = ++S.token;
    vaciar($vista).appendChild(esqueleto(vista));
    let nodo;
    try { nodo = await constructor(mi); }
    catch (e) { if (mi !== S.token) return; nodo = estadoError(e, function () { montar(vista, constructor); }); }
    if (mi !== S.token || !nodo) return;
    vaciar($vista).appendChild(nodo);
    window.scrollTo(0, 0);
    const t = $vista.querySelector('.titulo, .tj-tit h1');
    if (t) { t.setAttribute('tabindex', '-1'); t.focus({ preventScroll: true }); }
    const luego = S.alTerminar; S.alTerminar = null;
    if (luego) luego();
  }
  function titulo(texto, bajada) {
    return [h('h1', { class: 'titulo' }, texto), bajada ? h('p', { class: 'bajada' }, bajada) : h('p', { class: 'bajada' })];
  }

  async function traerTodas(forzar) {
    if (!S.todas || forzar) S.todas = (await pedir('tarjetas?vista=todas')).tarjetas || [];
    return S.todas;
  }

  // ---------------------------------------------------------------- Mis pendientes
  function vistaPendientes() {
    return montar('pendientes', async function () {
      const r = await Promise.all([pedir('resumen'), pedir('tarjetas?vista=pendientes'), traerTodas(true)]);
      const res = r[0]; const mias = r[1].tarjetas || []; const todas = r[2];
      setGlobo(res.pendientes);
      const ids = {}; mias.forEach(function (t) { ids[t.id] = true; });
      const otro = todas.filter(function (t) { return !ids[t.id] && ABIERTOS.indexOf(t.estado) !== -1 && t.espera; });
      const raiz = h('div', null, titulo('Mis pendientes', 'Lo que espera tu respuesta, primero.'));
      raiz.appendChild(h('div', { class: 'kpis' },
        h('div', { class: 'kpi entra' }, h('b', null, res.pendientes), h('span', null, 'Para responder')),
        h('div', { class: 'kpi entra', estilo: { '--i': 1 } }, h('b', null, res.esperan_otro), h('span', null, 'Esperan al otro lado')),
        h('div', { class: 'kpi entra', estilo: { '--i': 2 } }, h('b', null, res.con_fecha), h('span', null, 'Con fecha límite'), res.vencidas ? h('small', null, res.vencidas + (res.vencidas === 1 ? ' vencida' : ' vencidas')) : null),
        h('a', { class: 'kpi entra', href: '#plan', estilo: { '--i': 3 } }, h('b', null, (res.plan_pct || 0) + '%'), h('span', null, 'Plan completo'))));
      raiz.appendChild(h('h2', { class: 'grupo' }, 'Para responder'));
      raiz.appendChild(mias.length
        ? h('div', { class: 'tiles' }, mias.map(tile))
        : vacio('No tenés nada pendiente. Todo lo que esperaba tu respuesta ya está resuelto.', botonNueva()));
      if (otro.length) {
        raiz.appendChild(h('h2', { class: 'grupo' }, 'Esperando al otro lado'));
        raiz.appendChild(h('div', { class: 'tiles' }, otro.map(tile)));
      }
      return raiz;
    });
  }

  // ---------------------------------------------------------------- Tablero
  function vistaTablero() {
    return montar('tablero', async function () {
      const todas = await traerTodas(true);
      const grupos = [['abierta', 'Abierta'], ['en_curso', 'En curso'], ['respondida', 'Respondida'], ['cerrada', 'Cerrada']];
      const raiz = h('div', null, titulo('Tablero', 'Todas las tarjetas, según en qué estado están.'));
      if (!todas.length) { raiz.appendChild(vacio('Todavía no hay tarjetas. Creá la primera.', botonNueva())); return raiz; }
      raiz.appendChild(h('div', { class: 'cols' }, grupos.map(function (g, i) {
        const lista = todas.filter(function (t) { return g[0] === 'cerrada' ? ABIERTOS.indexOf(t.estado) === -1 : t.estado === g[0]; });
        return h('section', { class: 'col entra', 'aria-label': g[1], estilo: { '--i': i } },
          h('h2', null, g[1], h('span', null, lista.length)),
          lista.length ? lista.map(miniTarjeta) : h('p', { class: 'vacio-col' }, 'Ninguna.'));
      })));
      return raiz;
    });
  }

  // ---------------------------------------------------------------- Plan
  function vistaPlan() {
    return montar('plan', async function (mi) {
      const r = await Promise.all([pedir('plan'), pedir('resumen')]);
      S.plan = r[0].etapas || [];
      setGlobo(r[1].pendientes);
      if (S.etapaSel === null || !S.plan.some(function (e) { return e.id === S.etapaSel; })) {
        const primera = S.plan.find(function (e) { return (e.pct || 0) < 100; }) || S.plan[0];
        S.etapaSel = primera ? primera.id : null;
      }
      return dibujarPlan(r[1].plan_pct);
    });
  }
  function hitosDe(e) { return e.hitos || []; }
  function resumenEtapa(e) {
    const hs = hitosDe(e); const hechos = hs.filter(function (x) { return x.hecho; }).length;
    return { hechos: hechos, total: hs.length };
  }
  function dibujarPlan(pctGeneral) {
    const raiz = h('div', null);
    const cab = h('div', { class: 'cabeza' }, h('div', null, titulo('Plan', 'Seis fases, de punta a punta. Tildá cada hito cuando esté hecho.')));
    if (ES_EQUIPO) cab.appendChild(h('button', { class: 'btn lisa', type: 'button', 'aria-pressed': String(S.editarPlan), onclick: function () { S.editarPlan = !S.editarPlan; refrescarPlan(); } }, icono('lapiz'), S.editarPlan ? 'Listo, terminar de editar' : 'Editar plan'));
    raiz.appendChild(cab);
    if (!S.plan.length) { raiz.appendChild(vacio('Este proyecto todavía no tiene etapas ni hitos.')); return raiz; }
    raiz.appendChild(h('div', { class: 'tira', role: 'group', 'aria-label': 'Fases del plan' }, S.plan.map(function (e, i) {
      const c = resumenEtapa(e); const pct = c.total ? Math.round(100 * c.hechos / c.total) : (e.pct || 0);
      const b = h('button', { class: 'seg entra' + (pct >= 100 ? ' hecha' : ''), type: 'button', 'aria-pressed': String(e.id === S.etapaSel), estilo: { '--i': i },
        onclick: function () { S.etapaSel = e.id; refrescarPlan(); } },
        h('span', { class: 'n' }, 'FASE ' + (i + 1)), h('b', null, e.nombre), h('small', null, c.hechos + ' de ' + c.total + ' hitos'),
        h('div', { class: 'barra', 'aria-hidden': 'true' }, h('i', { estilo: { width: pct + '%' } })));
      return b;
    })));
    const e = S.plan.find(function (x) { return x.id === S.etapaSel; });
    if (e) raiz.appendChild(dibujarEtapa(e));
    return raiz;
  }
  function refrescarPlan() {
    const mi = S.token; const sc = window.scrollY;
    vaciar($vista).appendChild(dibujarPlan());
    window.scrollTo(0, sc);
    $vista.querySelectorAll('.entra').forEach(function (n) { n.classList.remove('entra'); });
    return mi;
  }
  async function recargarPlan() {
    try { const r = await pedir('plan'); S.plan = r.etapas || []; refrescarPlan(); } catch (e) { /* queda lo que se ve */ }
    refrescarGlobo();
  }
  function dibujarEtapa(e) {
    const c = resumenEtapa(e); const pct = c.total ? Math.round(100 * c.hechos / c.total) : 0;
    const card = h('section', { class: 'etapa-card', 'aria-label': e.nombre });
    if (ES_EQUIPO && S.editarPlan) {
      const inp = h('input', { type: 'text', value: e.nombre, maxlength: 80, 'aria-label': 'Nombre de la fase' });
      const fila = h('div', { class: 'edit-fila' }, inp, h('button', { class: 'btn pri chico', type: 'button', onclick: async function (ev) {
        const b = ev.currentTarget; b.disabled = true; errorEn(card, '');
        try { await enviarJson('plan/etapas/' + e.id, { nombre: inp.value.trim() }); avisar('Nombre guardado.'); await recargarPlan(); }
        catch (x) { errorEn(card, x.message); } finally { b.disabled = false; }
      } }, 'Guardar nombre'));
      card.appendChild(fila);
    } else card.appendChild(h('h2', null, e.nombre));
    card.appendChild(h('div', { class: 'barra', 'aria-hidden': 'true' }, h('i', { estilo: { width: pct + '%' } })));
    card.appendChild(h('small', { style: 'color:var(--gris);font-weight:700' }, c.hechos + ' de ' + c.total + ' hitos hechos'));
    const hs = hitosDe(e);
    if (!hs.length) card.appendChild(h('p', { class: 'vacio-col' }, 'Esta fase todavía no tiene hitos.'));
    hs.forEach(function (x) { card.appendChild(dibujarHito(e, x)); });
    if (ES_EQUIPO && S.editarPlan) {
      const inp = h('input', { type: 'text', maxlength: 200, placeholder: 'Nuevo hito', 'aria-label': 'Texto del nuevo hito' });
      card.appendChild(h('div', { class: 'edit-fila', style: 'margin-top:10px' }, inp, h('button', { class: 'btn lisa chico', type: 'button', onclick: async function (ev) {
        const t = inp.value.trim(); if (!t) { errorEn(card, 'Escribí el texto del hito.'); return; }
        const b = ev.currentTarget; b.disabled = true; errorEn(card, '');
        try { await enviarJson('plan/hitos', { etapa_id: e.id, texto: t }); avisar('Hito agregado.'); await recargarPlan(); }
        catch (x) { errorEn(card, x.message); } finally { b.disabled = false; }
      } }, icono('mas'), 'Agregar hito')));
    }
    return card;
  }
  function dibujarHito(e, x) {
    const raiz = h('div', { class: 'hito' + (x.hecho ? ' on' : ''), 'data-codigo': x.codigo || null, id: x.codigo ? 'h-' + x.codigo : null });
    const quien = x.hecho && (x.hecho_por || x.hecho_en) ? h('small', null, 'Hecho' + (x.hecho_por ? ' por ' + x.hecho_por : '') + (x.hecho_en ? ', ' + fechaHora(x.hecho_en) : '')) : null;
    if (ES_EQUIPO && S.editarPlan) {
      const inp = h('input', { type: 'text', value: x.texto, maxlength: 200, 'aria-label': 'Texto del hito' });
      raiz.appendChild(h('div', { class: 'edit-fila' }, inp,
        h('button', { class: 'btn pri chico', type: 'button', onclick: async function (ev) {
          const b = ev.currentTarget; b.disabled = true; errorEn(raiz, '');
          try { await enviarJson('plan/hitos/' + x.id, { texto: inp.value.trim() }); avisar('Hito guardado.'); await recargarPlan(); }
          catch (er) { errorEn(raiz, er.message); } finally { b.disabled = false; }
        } }, 'Guardar'),
        h('button', { class: 'btn no chico', type: 'button', onclick: async function () {
          const ok = await confirmar({ titulo: '¿Quitar este hito?', texto: 'Las tarjetas que colgaban de él quedan sin hito. No se puede deshacer.', ok: 'Quitar hito', clase: 'no' });
          if (!ok) return; errorEn(raiz, '');
          try { await enviarJson('plan/hitos/' + x.id, { borrar: true }); avisar('Hito quitado.'); await recargarPlan(); }
          catch (er) { errorEn(raiz, er.message); }
        } }, icono('basura'), 'Quitar')));
    } else {
      raiz.appendChild(h('button', { class: 'hito-fila', type: 'button', role: 'checkbox', 'aria-checked': String(!!x.hecho), onclick: async function () {
        const antes = !!x.hecho; x.hecho = !antes; if (x.hecho) { x.hecho_por = 'vos'; x.hecho_en = ''; }
        refrescarPlan(); errorEn($vista, '');
        try { await enviarJson('plan/hitos/' + x.id, { hecho: x.hecho }); recargarPlan(); }
        catch (er) { x.hecho = antes; refrescarPlan(); avisar(er.message, true); }
      } }, h('span', { class: 'caja' }, icono('check')), h('span', { class: 'hito-t' }, h('span', { class: 'txt' }, x.texto), quien)));
    }
    if (x.codigo) raiz.appendChild(h('div', { class: 'hito-cod' }, codigo(x.codigo, { que: 'el código del hito' })));
    if ((x.tarjetas || []).length) {
      raiz.appendChild(h('div', { class: 'colgadas' }, x.tarjetas.map(function (t) {
        return colorTipo(h('a', { class: 'colgada', href: t.codigo ? hashDe(t.codigo) : '#t' + t.numero }, h('span', { class: 'cod' }, t.codigo || ('#' + t.numero)), h('span', { class: 'col-t' }, t.titulo), h('small', null, nombreEstado(t.estado))), t.tipo || 'pedido');
      })));
    }
    if (!S.editarPlan) raiz.appendChild(h('div', { class: 'hito-acc' }, h('a', { class: 'btn lisa chico', href: '#nueva?etapa=' + e.id + '&hito=' + x.id }, icono('mas'), 'Tarjeta para este hito')));
    return raiz;
  }

  // ---------------------------------------------------------------- Relacionadas y ficha de archivo
  const ORDEN_REL = ['responde a', 'respondida con', 'menciona', 'mencionada en'];
  function itemRelacion(r, alIr) {
    const m = marcaDeRelacion(r);
    const a = h('a', { class: 'rel-item', href: r.enlace ? hashDe(sinHash(r.enlace) || r.codigo) : hashDe(r.codigo), 'data-tipo': r.tipo || null,
      onclick: function () { if (alIr) alIr(); } },
      icono(m.icono), h('span', { class: 'cod' }, r.codigo), h('span', { class: 'rel-t' }, r.titulo || ''),
      r.estado ? h('small', { class: 'rel-e' }, ESTADOS_OTROS[r.estado] || nombreEstado(r.estado)) : null,
      r.via ? h('small', { class: 'rel-via' }, 'a través de ' + r.via) : null);
    return m.tipo ? colorTipo(a, m.tipo) : a;
  }
  // Agrupa por la frase que manda el servidor; vacío = no se dibuja nada.
  function bloqueRelacionadas(lista, alIr) {
    // Una misma cosa nombrada dos veces por el mismo motivo (la tarjeta y uno de sus
    // mensajes) se muestra una sola vez; queda el «a través de» si lo hay.
    const vistos = {};
    lista = (lista || []).filter(function (r) { return r && r.codigo; }).filter(function (r) {
      const k = (r.texto || '') + '|' + r.codigo;
      if (vistos[k]) { if (r.via && !vistos[k].via) vistos[k].via = r.via; return false; }
      vistos[k] = Object.assign({}, r); return true;
    }).map(function (r) { return vistos[(r.texto || '') + '|' + r.codigo]; });
    if (!lista.length) return null;
    const grupos = {};
    lista.forEach(function (r) { const k = (r.texto || 'relacionada').toLowerCase(); (grupos[k] = grupos[k] || []).push(r); });
    const claves = ORDEN_REL.filter(function (k) { return grupos[k]; }).concat(Object.keys(grupos).filter(function (k) { return ORDEN_REL.indexOf(k) === -1; }));
    return h('section', { class: 'rels', 'aria-label': 'Relacionadas' },
      h('h3', null, 'Relacionadas'),
      claves.map(function (k) {
        return h('div', { class: 'rel-grupo' }, h('h4', null, cap(k)), h('ul', null, grupos[k].map(function (r) { return h('li', null, itemRelacion(r, alIr)); })));
      }));
  }

  const $fa = document.getElementById('ficha-arch');
  const $faCuerpo = document.getElementById('fa-cuerpo');
  function cerrarFicha() { if ($fa.open) $fa.close(); }
  async function abrirFicha(aid, alBorrar) {
    let d;
    try { d = await pedir('archivos/' + aid + '/ficha'); }
    catch (e) { avisar(e.status === 404 ? 'No existe o no lo podés ver.' : e.message, true); return; }
    const a = d.archivo || {}; const tj = d.tarjeta || null;
    function par(dt, dd) { return [h('dt', null, dt), h('dd', null, dd)]; }
    vaciar($faCuerpo);
    $faCuerpo.appendChild(h('div', { class: 'fa-cab' },
      h('h2', { id: 'fa-t' }, 'Ficha del archivo'),
      h('button', { class: 'btn lisa chico', type: 'button', 'aria-label': 'Cerrar la ficha', onclick: cerrarFicha }, icono('cerrar'))));
    if (a.codigo) $faCuerpo.appendChild(h('div', { class: 'fa-cod' }, codigo(a.codigo, { que: 'el código del archivo' })));
    $faCuerpo.appendChild(h('dl', { class: 'fa-dl' },
      par('Nombre', a.nombre || ''),
      par('Tamaño', tamano(a.tamano)),
      par('Lo subió', (a.subido_por || '') + (a.subido_lado ? ' (' + ladoNombre(a.subido_lado) + ')' : '') + (a.subido_en ? ' · ' + fechaHora(a.subido_en) : '')),
      par('Datos personales', a.datos_personales ? h('span', { class: 'chip mal' }, icono('candado'), 'Contiene datos personales') : 'No marcado'),
      a.borrado ? par('Estado', 'Borrado: queda la constancia de que existió') : null,
      tj ? par('Tarjeta que lo contiene', h('a', { class: 'cod-lnk', href: tj.codigo ? hashDe(tj.codigo) : '#t' + tj.numero, onclick: cerrarFicha }, (tj.codigo || ('#' + tj.numero)) + ' · ' + (tj.titulo || ''))) : null));
    const rel = bloqueRelacionadas(d.relacionadas, cerrarFicha);
    if (rel) $faCuerpo.appendChild(rel);
    const acc = h('div', { class: 'fa-acc' });
    if (a.puede_bajar && !a.borrado) acc.appendChild(h('a', { class: 'btn pri chico', href: BASE + 'archivos/' + a.id, download: a.nombre }, icono('bajar'), 'Bajar'));
    else if (a.datos_personales && !a.borrado) acc.appendChild(h('small', { class: 'fa-nota' }, 'Contiene datos personales: solo lo baja quien lo subió o el equipo.'));
    if (a.puede_borrar && !a.borrado) acc.appendChild(h('button', { class: 'btn no chico', type: 'button', onclick: async function () {
      const ok = await confirmar({ titulo: '¿Borrar este archivo?', texto: 'Se borra el archivo y queda la constancia de que existió: nombre, tamaño, quién lo subió y quién lo borró.', ok: 'Borrar archivo', clase: 'no' });
      if (!ok) return;
      try { await enviarJson('archivos/' + a.id + '/borrar', {}); avisar('Archivo borrado.'); cerrarFicha(); invalidar(); (alBorrar || ruta)(); }
      catch (er) { avisar(er.message, true); }
    } }, icono('basura'), 'Borrar'));
    acc.appendChild(h('button', { class: 'btn lisa chico', type: 'button', onclick: cerrarFicha }, 'Cerrar'));
    $faCuerpo.appendChild(acc);
    if (!$fa.open) $fa.showModal();
    const x = $faCuerpo.querySelector('.fa-cab button'); if (x) x.focus();
  }
  function botonFicha(a, alBorrar) {
    return h('button', { class: 'btn lisa chico', type: 'button', onclick: function () { abrirFicha(a.id, alBorrar); } }, icono('enlace'), 'Ficha');
  }

  // ---------------------------------------------------------------- Archivos (fila común)
  function filaArchivo(a, opc) {
    opc = opc || {};
    if (a.borrado) {
      return h('div', { class: 'fila borrado', 'data-codigo': a.codigo || null }, h('div', { class: 'nom' }, a.nombre, h('small', null, 'Archivo borrado · ' + tamano(a.tamano) + (a.subido_por ? ' · lo subió ' + a.subido_por : ''))),
        a.codigo ? codigo(a.codigo, { que: 'el código del archivo' }) : null);
    }
    const tarj = a.tarjeta_codigo || (a.tarjeta_numero ? '#' + a.tarjeta_numero : '');
    const fila = h('div', { class: 'fila', 'data-codigo': a.codigo || null },
      a.codigo ? h('div', { class: 'fila-cod' }, codigo(a.codigo, { que: 'el código del archivo' })) : null,
      h('div', { class: 'nom' }, a.nombre,
        h('small', null, tamano(a.tamano) + ' · ' + (a.subido_por || '') + (a.subido_en ? ' · ' + fechaHora(a.subido_en) : '')),
        opc.tarjeta && tarj ? h('small', null, h('a', { href: a.tarjeta_codigo ? hashDe(a.tarjeta_codigo) : '#t' + a.tarjeta_numero, style: 'text-decoration:underline' }, 'Tarjeta ' + tarj + ' ' + (a.tarjeta_titulo || ''))) : null),
      a.datos_personales ? h('span', { class: 'chip mal' }, icono('candado'), 'Datos personales') : null,
      // I16: de un archivo de una entrega, si quien la recibía la dio por recibida.
      a.tarjeta_tipo === 'entrega' ? (a.recibida_por
        ? h('span', { class: 'chip ok recibida', title: 'Recibida por ' + a.recibida_por + ' · ' + fechaHora(a.recibida_en) }, icono('check'), 'Recibida · ' + a.recibida_por + ' · ' + fechaCorta(a.recibida_en))
        : h('span', { class: 'chip neutro sin-recibir' }, 'Sin dar por recibida')) : null);
    const acc = h('div', { class: 'acc' });
    acc.appendChild(botonFicha(a, opc.alBorrar));
    if (a.puede_bajar) acc.appendChild(h('a', { class: 'btn lisa chico', href: BASE + 'archivos/' + a.id, download: a.nombre }, icono('bajar'), 'Bajar'));
    else if (a.datos_personales) acc.appendChild(h('small', null, 'Contiene datos personales: solo lo baja quien lo subió o el equipo.'));
    if (a.puede_borrar) acc.appendChild(h('button', { class: 'btn no chico', type: 'button', onclick: async function () {
      const ok = await confirmar({ titulo: '¿Borrar este archivo?', texto: 'Se borra el archivo y queda la constancia de que existió: nombre, tamaño, quién lo subió y quién lo borró.', ok: 'Borrar archivo', clase: 'no' });
      if (!ok) return; errorEn(fila, '');
      try { await enviarJson('archivos/' + a.id + '/borrar', {}); avisar('Archivo borrado.'); if (opc.alBorrar) opc.alBorrar(); }
      catch (er) { errorEn(fila, er.message); }
    } }, icono('basura'), 'Borrar'));
    fila.appendChild(acc);
    return fila;
  }

  // ---------------------------------------------------------------- Carpetas
  function vistaCarpetas() {
    return montar('carpetas', async function () {
      const d = await pedir('carpetas?sentido=' + S.sentido);
      const raiz = h('div', null, titulo('Carpetas', 'Los archivos de la mesa, ordenados por fase.'));
      const selector = h('div', { class: 'seg2', role: 'group', 'aria-label': 'Sentido' },
        [['entrada', 'Entrada', 'Lo que mandó el sindicato'], ['salida', 'Salida', 'Lo que mandó el equipo']].map(function (o) {
          return h('button', { type: 'button', 'aria-pressed': String(S.sentido === o[0]), onclick: function () { S.sentido = o[0]; vistaCarpetas(); } }, o[1], h('small', null, o[2]));
        }));
      raiz.appendChild(selector);
      const etapas = (d.etapas || []).filter(function (e) { return (e.archivos || []).length; });
      if (!etapas.length) {
        raiz.appendChild(vacio('Todavía no hay archivos en ' + (S.sentido === 'entrada' ? 'Entrada' : 'Salida') + '. Cuando alguien suba uno en una tarjeta, aparece acá.', botonNueva('entrega', 'Nueva entrega de archivo')));
        return raiz;
      }
      etapas.forEach(function (e) {
        const nombre = (e.etapa && typeof e.etapa === 'object' ? e.etapa.nombre : e.etapa) || 'Sin fase';
        raiz.appendChild(h('h2', { class: 'grupo' }, nombre + ' (' + e.archivos.length + ')'));
        e.archivos.forEach(function (a) { raiz.appendChild(filaArchivo(a, { tarjeta: true, alBorrar: vistaCarpetas })); });
      });
      return raiz;
    });
  }

  // ---------------------------------------------------------------- Aprobaciones
  function chipAprobacion(estado) {
    if (estado === 'aprobada') return h('span', { class: 'chip ok' }, icono('check'), 'Aprobada');
    if (estado === 'rechazada') return h('span', { class: 'chip mal' }, icono('cerrar'), 'Rechazada');
    return h('span', { class: 'chip sind' }, icono('reloj'), 'Esperando decisión');
  }
  function vistaAprobaciones() {
    return montar('aprobaciones', async function () {
      const d = await pedir('aprobaciones');
      const lista = d.aprobaciones || [];
      const raiz = h('div', null);
      raiz.appendChild(h('div', { class: 'cabeza' }, h('div', null, titulo('Aprobaciones', 'Cada autorización formal, con quién y cuándo. No se modifican.')),
        lista.length ? h('a', { class: 'btn lisa', href: BASE + 'aprobaciones.csv', download: 'aprobaciones.csv' }, icono('bajar'), 'Descargar CSV') : null));
      if (!lista.length) { raiz.appendChild(vacio('Todavía no hay aprobaciones. Se piden creando una tarjeta de tipo Aprobación.', botonNueva('aprobacion', 'Pedir una aprobación'))); return raiz; }
      lista.forEach(function (a, i) {
        raiz.appendChild(h('a', { class: 'ap-fila entra', href: a.codigo ? hashDe(a.codigo) : '#t' + a.numero, estilo: { '--i': i } },
          h('div', null, h('span', { class: 'cod' }, a.codigo || ('#' + a.numero)), h('b', null, a.titulo), chipAprobacion(a.estado)),
          h('div', null, h('small', null, 'Pedida por'), a.pedida_por || '—', h('small', null, fechaHora(a.pedida_en))),
          h('div', null, h('small', null, 'Resuelta por'), a.resuelta_por || '—', h('small', null, a.resuelta_en ? fechaHora(a.resuelta_en) : '')),
          h('div', null),
          a.texto ? h('div', { class: 'txt' }, a.texto) : null));
      });
      return raiz;
    });
  }

  // ---------------------------------------------------------------- Nueva tarjeta
  function parseHash() {
    const raw = window.location.hash.slice(1);
    const i = raw.indexOf('?');
    const ruta = i === -1 ? raw : raw.slice(0, i);
    const q = {};
    const dec = function (x) { try { return decodeURIComponent(x); } catch (e) { return x; } };
    if (i !== -1) raw.slice(i + 1).split('&').forEach(function (p) { const kv = p.split('='); if (kv[0]) q[dec(kv[0])] = dec(kv.slice(1).join('=')); });
    return { ruta: ruta, q: q };
  }
  function vistaNueva(q) {
    return montar('nueva', async function () {
      const res = await pedir('resumen');
      setGlobo(res.pendientes);
      const etapas = res.etapas || [];
      // «Responder con…»: la tarjeta o el archivo al que responde esta (por código).
      let origen = null; let origenMal = false;
      if (q.responde_a && esCodigo(q.responde_a)) {
        try {
          const b = await pedir('buscar?codigo=' + encodeURIComponent(q.responde_a.toUpperCase()));
          origen = { codigo: b.codigo || q.responde_a.toUpperCase(), titulo: b.titulo || '' };
        } catch (e) { origenMal = true; }
      } else if (q.responde_a) origenMal = true;
      let tipo = TIPOS[q.tipo] ? q.tipo : null;
      // Un Pedido se contesta, sobre todo, con una Entrega; se puede cambiar.
      if (!tipo && origen && tipoDeCodigo(origen.codigo) === 'pedido' && TIPOS.entrega) tipo = 'entrega';
      const raiz = h('div', null, titulo('Nueva tarjeta', origen ? 'Elegí con qué la respondés.' : 'Elegí qué querés hacer.'));
      if (origen) raiz.appendChild(h('p', { class: 'responde', role: 'status' }, icono('enlace'), h('span', null, 'Responde a ', h('span', { class: 'cod' }, origen.codigo), origen.titulo ? ' · ' + origen.titulo : '')));
      if (origenMal) raiz.appendChild(h('p', { class: 'err', role: 'alert' }, 'No existe o no lo podés ver: ' + q.responde_a + '. La tarjeta se crea sin vincular.'));
      const zonaForm = h('div', null);
      const botones = {};
      raiz.appendChild(h('div', { class: 'tipos', role: 'group', 'aria-label': 'Tipo de tarjeta' }, ORDEN_TIPOS.map(function (k, i) {
        const t = TIPOS[k];
        const b = colorTipo(h('button', { class: 'tipo entra', type: 'button', 'aria-pressed': String(k === tipo), estilo: { '--i': i }, onclick: function () { elegir(k, true); } },
          icono(t.icono || 'inbox'), h('b', null, t.nombre), h('span', null, t.para || '')), k);
        botones[k] = b; return b;
      })));
      raiz.appendChild(zonaForm);

      function elegir(k, enfocar) {
        tipo = k;
        Object.keys(botones).forEach(function (x) { botones[x].setAttribute('aria-pressed', String(x === k)); botones[x].classList.toggle('apagado', x !== k); });
        vaciar(zonaForm).appendChild(formulario(k));
        if (enfocar) { const t = zonaForm.querySelector('#nt-titulo'); if (t) { t.focus({ preventScroll: true }); t.scrollIntoView({ behavior: 'smooth', block: 'center' }); } }
      }
      function formulario(k) {
        const t = TIPOS[k];
        const titulo_ = h('input', { type: 'text', id: 'nt-titulo', maxlength: 140, required: true, autocomplete: 'off' });
        const texto = h('textarea', { id: 'nt-texto', maxlength: 5000, 'aria-describedby': 'nt-ayuda' });
        const selEtapa = h('select', { class: 'campo', id: 'nt-etapa' }, h('option', { value: '' }, 'Sin fase'),
          etapas.map(function (e) { return h('option', { value: e.id }, e.nombre); }));
        if (q.etapa) selEtapa.value = q.etapa;
        const fecha = h('input', { type: 'date', id: 'nt-fecha' });
        const lista = h('ul', null);
        const dp = h('input', { type: 'checkbox', id: 'nt-dp' });
        const dpFila = h('label', { class: 'chk', hidden: true }, dp, 'Los archivos contienen datos personales');
        const archivos = h('input', { type: 'file', id: 'nt-arch', multiple: true });
        archivos.addEventListener('change', function () {
          vaciar(lista);
          Array.prototype.forEach.call(archivos.files, function (f) { lista.appendChild(h('li', null, h('span', null, f.name), h('span', null, tamano(f.size)))); });
          dpFila.hidden = !archivos.files.length;
        });
        const envio = h('div', null);
        const crear = h('button', { class: 'btn pri', type: 'submit' }, icono('enviar'), 'Crear tarjeta');
        const f = h('form', { class: 'form entra', novalidate: true },
          h('p', { class: 'chip neutro', style: 'justify-self:start' }, k === 'aviso' ? 'Un aviso nace cerrada: informa, no espera respuesta.' : (t.cierra || '')),
          h('label', { class: 'l', for: 'nt-titulo' }, 'Título', titulo_),
          h('label', { class: 'l', for: 'nt-texto' }, 'Qué necesitás contar', texto, h('small', { id: 'nt-ayuda' }, 'Con tus palabras, sin apuro. Podés nombrar otra tarjeta o archivo por su código (PE0004, AR000123).')),
          h('div', { class: 'dos' },
            h('label', { class: 'l', for: 'nt-etapa' }, h('span', null, 'Fase ', h('small', null, '(opcional)')), selEtapa),
            h('label', { class: 'l', for: 'nt-fecha' }, h('span', null, 'Fecha límite ', h('small', null, '(opcional)')), fecha)),
          h('div', { class: 'arch' }, h('label', { class: 'l', for: 'nt-arch' }, h('span', null, 'Archivos ', h('small', null, '(opcional, hasta 20 MB cada uno)'))), archivos, lista, dpFila),
          envio, h('div', null, crear));
        f.addEventListener('submit', async function (ev) {
          ev.preventDefault(); errorEn(envio, '');
          if (!titulo_.value.trim()) { errorEn(envio, 'Poné un título.'); titulo_.focus(); return; }
          if (!texto.value.trim()) { errorEn(envio, 'Contanos de qué se trata.'); texto.focus(); return; }
          const pb = pesoArchivos(archivos.files); if (pb) { errorEn(envio, pb); return; }
          const fd = new FormData();
          fd.append('tipo', k); fd.append('titulo', titulo_.value.trim()); fd.append('texto', texto.value.trim());
          if (selEtapa.value) fd.append('etapa_id', selEtapa.value);
          if (q.hito) fd.append('hito_id', q.hito);
          if (origen) fd.append('responde_a', origen.codigo);
          if (fecha.value) fd.append('fecha_limite', fecha.value);
          Array.prototype.forEach.call(archivos.files, function (a) { fd.append('archivos', a); });
          if (archivos.files.length) fd.append('datos_personales', dp.checked ? 'true' : 'false');
          crear.disabled = true; crear.lastChild.textContent = 'Creando…';
          try {
            const d = await enviarForm('tarjetas', fd);
            invalidar(); avisar('Tarjeta creada.');
            window.location.hash = hashDeTarjeta(d.tarjeta);
          } catch (er) { errorEn(envio, er.message); crear.disabled = false; crear.lastChild.textContent = 'Crear tarjeta'; }
        });
        return f;
      }
      if (tipo) elegir(tipo, false);
      return raiz;
    });
  }

  // ---------------------------------------------------------------- Una tarjeta
  async function idDeNumero(n) {
    let t = (S.todas || []).find(function (x) { return x.numero === n; });
    if (!t) { await traerTodas(true); t = S.todas.find(function (x) { return x.numero === n; }); }
    if (!t) throw new ErrorMesa('No existe la tarjeta #' + n + ' en este proyecto.', 404);
    return t.id;
  }
  async function traerTarjeta(id) {
    const d = await pedir('tarjetas/' + id);
    if (d.tarjeta.tipo === 'aviso' && d.tarjeta.autor_lado !== LADO) {
      pedirJson(BASE + 'tarjetas/' + id + '/leido', { method: 'POST' }).then(refrescarGlobo, function () {});
    }
    return d;
  }
  function vistaTarjeta(numero) {
    return montar('tarjeta', async function () {
      let id;
      try { id = await idDeNumero(numero); } catch (e) { if (e.status === 404) { S.actual = null; return noExiste(); } throw e; }
      return dibujarTarjeta(await traerTarjeta(id));
    });
  }
  function noExiste() {
    return h('div', { class: 'vacio' }, h('p', { role: 'alert' }, 'No existe o no lo podés ver.'),
      h('a', { class: 'btn lisa', href: '#' + (S.ultima || 'pendientes') }, icono('volver'), 'Volver'));
  }
  // Un código en el hash (#PE0004, #PE0004-3, #AR000123, #HI0001): se resuelve
  // con buscar?codigo= y se lleva a la cosa. El 404 es el mismo en todos los casos.
  function vistaCodigo(c) {
    c = c.toUpperCase();
    return montar('tarjeta', async function () {
      let r;
      try { r = await pedir('buscar?codigo=' + encodeURIComponent(c)); }
      catch (e) { if (e.status === 404) { S.actual = null; return noExiste(); } throw e; }
      if (r.tipo === 'hito') {
        S.ultima = 'plan'; marcarNav('plan');
        const pr = await Promise.all([pedir('plan'), pedir('resumen')]);
        S.plan = pr[0].etapas || [];
        setGlobo(pr[1].pendientes);
        const et = S.plan.find(function (e) { return hitosDe(e).some(function (x) { return x.id === r.id || x.codigo === r.codigo; }); });
        if (!et) { S.actual = null; return noExiste(); }
        S.etapaSel = et.id;
        S.alTerminar = function () { resaltar($vista.querySelector('[data-codigo="' + r.codigo + '"]')); };
        return dibujarPlan(pr[1].plan_pct);
      }
      if (!r.tarjeta_id) { S.actual = null; return noExiste(); }
      const d = await traerTarjeta(r.tarjeta_id);
      if (r.tipo === 'mensaje' || r.tipo === 'archivo') {
        S.alTerminar = function () {
          const el = $vista.querySelector('[data-codigo="' + r.codigo + '"]');
          if (!resaltar(el) && r.tipo === 'archivo') abrirFicha(r.id);
        };
      }
      return dibujarTarjeta(d);
    });
  }
  function recargarTarjeta() { if (S.actual) montar('tarjeta', async function () { return dibujarTarjeta(await traerTarjeta(S.actual)); }); }
  function reemplazarTarjeta(d) {
    invalidar();
    vaciar($vista).appendChild(dibujarTarjeta(d));
    refrescarGlobo();
  }
  function estadosPermitidos(acc) {
    return (acc.estados || []).map(function (e) { return typeof e === 'string' ? e : (e && (e.clave || e.estado || e.id)); }).filter(Boolean);
  }
  function dibujarTarjeta(d) {
    const t = d.tarjeta; const acc = d.acciones || {};
    const info = TIPOS[t.tipo] || {};
    S.actual = t.id; S.actualCodigo = t.codigo || '';
    const raiz = colorTipo(h('div', { class: 'entra' }), t.tipo);
    raiz.appendChild(h('a', { class: 'volver', href: '#' + (S.ultima || 'pendientes') }, icono('volver'), 'Volver'));
    raiz.appendChild(h('div', { class: 'tj-cab', 'data-codigo': t.codigo || null }, icono(info.icono || t.icono || 'inbox'), h('span', null, t.tipo_nombre || info.nombre || t.tipo),
      h('span', { class: 'n' }, t.codigo ? codigo(t.codigo, { clase: 'en-cab', que: 'el código de la tarjeta' }) : h('span', { class: 'cod en-cab' }, '#' + t.numero))));
    // P-10: una aprobación resuelta se dice UNA vez: el sello, y debajo quién y cuándo.
    const resuelta = t.estado === 'aprobada' || t.estado === 'rechazada';
    // I16: una entrega recibida se dice UNA vez, con el mismo patrón: el sello y debajo quién y cuándo.
    const recibida = t.tipo === 'entrega' && t.estado === 'cerrada' && !!t.recibida_por;
    const chips = h('div', { class: 'chips' });
    if (recibida) {
      chips.appendChild(h('span', { class: 'sello' }, 'Recibida'));
      chips.appendChild(h('small', { class: 'resuelta-por' }, 'por ' + t.recibida_por + ' · ' + fechaHora(t.recibida_en)));
    } else if (resuelta) {
      const rs = (d.eventos || []).filter(function (e) { return e.que === 'resolver'; }).pop();
      chips.appendChild(h('span', { class: t.estado === 'aprobada' ? 'sello' : 'sello rech' }, nombreEstado(t.estado)));
      if (rs) chips.appendChild(h('small', { class: 'resuelta-por' }, 'por ' + (rs.quien || '') + (rs.lado ? ' (' + ladoNombre(rs.lado) + ')' : '') + ' · ' + fechaHora(rs.cuando)));
    } else {
      chips.appendChild(h('span', { class: 'chip neutro' }, nombreEstado(t.estado)));
      chips.appendChild(chipEspera(t));
    }
    if (acc.responder) chips.appendChild(h('a', { class: 'btn lisa chico responder-con', href: '#nueva?responde_a=' + encodeURIComponent(t.codigo || '') + (t.tipo === 'pedido' ? '&tipo=entrega' : '') }, icono('enviar'), 'Responder con…'));
    raiz.appendChild(h('div', { class: 'tj-tit' }, h('h1', null, enlazar(t.titulo, t.refs)), chips));

    // ---- ficha
    const ficha = h('aside', { class: 'ficha', 'aria-label': 'Ficha de la tarjeta' });
    function par(dt, dd, clase) { return [h('dt', null, dt), h('dd', { class: clase || '' }, dd)]; }
    ficha.appendChild(h('dl', null,
      par('Quién tiene que responder', t.espera ? cap(t.espera_texto || '') : 'A nadie: está cerrada'),
      par('Fase', t.etapa_nombre || 'Sin fase'),
      par('Responsable', t.responsable || 'Sin responsable'),
      par('Fecha límite', t.fecha_limite ? fechaCorta(t.fecha_limite) + (t.vencida ? ' (vencida)' : '') : 'Sin fecha límite', t.vencida ? 'vencida' : ''),
      par('La creó', (t.autor_nombre || '') + (t.autor_lado ? ' (' + ladoNombre(t.autor_lado) + ')' : '') + (t.creada_en ? ' · ' + fechaHora(t.creada_en) : '')),
      par('Última actividad', fechaHora(t.actualizada_en))));
    const rel = bloqueRelacionadas(d.relacionadas);
    if (rel) ficha.appendChild(rel);
    const sueltos = (d.archivos || []).filter(function (a) { return !a.mensaje_id; });
    if (sueltos.length) {
      ficha.appendChild(h('h3', null, 'Adjuntos de la tarjeta'));
      sueltos.forEach(function (a) { ficha.appendChild(adjunto(a)); });
    }
    if (t.tipo === 'aviso' && (d.lecturas || []).length) {
      ficha.appendChild(h('h3', null, 'Lo leyeron'));
      ficha.appendChild(h('p', null, d.lecturas.map(function (l) { return l.nombre; }).join(', ')));
    }
    if (acc.reasignar) ficha.appendChild(formReasignar(t));
    // ---- hilo
    const hilo = h('div', { class: 'hilo' });
    const porMensaje = {};
    (d.archivos || []).forEach(function (a) { if (a.mensaje_id) (porMensaje[a.mensaje_id] = porMensaje[a.mensaje_id] || []).push(a); });
    (d.mensajes || []).forEach(function (m) {
      hilo.appendChild(h('article', { class: 'msg' + (m.mio ? ' mio' : '') + (m.solo_equipo ? ' nota' : ''), 'data-codigo': m.codigo || null },
        h('div', { class: 'quien' }, m.autor_nombre, m.autor_lado ? h('span', { class: 'chip ' + (m.autor_lado === 'equipo' ? 'equipo' : 'sind') }, ladoNombre(m.autor_lado)) : null,
          m.solo_equipo ? h('span', { class: 'chip neutro' }, icono('candado'), 'Solo equipo') : null, h('span', { class: 'hora' }, fechaHora(m.creado_en)),
          m.codigo ? h('span', { class: 'msg-cod' }, codigo(m.codigo, { que: 'el código del mensaje' })) : null),
        m.texto ? h('p', null, enlazar(m.texto, m.refs)) : null,
        porMensaje[m.id] ? h('div', { class: 'adjs' }, porMensaje[m.id].map(adjunto)) : null));
    });
    if (!(d.mensajes || []).length) hilo.appendChild(h('p', { class: 'vacio-col' }, 'Todavía no hay mensajes.'));

    if (acc.aprobar) hilo.appendChild(panelDecision(t));
    if (acc.recibido || acc.problema) hilo.appendChild(panelEntrega(t, acc));
    if (acc.responder) hilo.appendChild(redactor(t, acc));
    else if (acc.reabrir) hilo.appendChild(h('div', { class: 'redactor' }, h('p', null, 'Esta tarjeta está cerrada.'), botonReabrir(t)));
    else if (!acc.aprobar && t.tipo === 'aviso') hilo.appendChild(h('p', { class: 'bajada', style: 'margin:0' }, 'Es un aviso: informa y no espera respuesta.'));
    else if (!acc.aprobar && ABIERTOS.indexOf(t.estado) === -1) hilo.appendChild(h('p', { class: 'bajada', style: 'margin:0' }, 'Esta tarjeta está cerrada.'));
    if (acc.responder && acc.reabrir) hilo.appendChild(botonReabrir(t));

    const ev = d.eventos || [];
    if (ev.length) hilo.appendChild(h('details', { class: 'traza' }, h('summary', null, 'Historial de la tarjeta (' + ev.length + ')'),
      h('ol', null, ev.map(function (e) { return h('li', null, h('b', null, e.que || ''), e.texto ? ' ' + e.texto : '', h('small', null, (e.quien || '') + (e.lado ? ' (' + ladoNombre(e.lado) + ')' : '') + ' · ' + fechaHora(e.cuando))); }))));
    raiz.appendChild(h('div', { class: 'tj-grid' }, ficha, hilo));
    return raiz;
  }
  function adjunto(a) {
    if (a.borrado) return h('div', { class: 'adj borrado', 'data-codigo': a.codigo || null }, h('span', { class: 'nom' }, a.nombre), h('small', null, 'Borrado · ' + tamano(a.tamano)), a.codigo ? codigo(a.codigo, { que: 'el código del archivo' }) : null);
    const fila = h('div', { class: 'adj', 'data-codigo': a.codigo || null }, icono('clip'), h('span', { class: 'nom' }, a.nombre), h('small', null, tamano(a.tamano)),
      a.codigo ? codigo(a.codigo, { que: 'el código del archivo' }) : null,
      a.datos_personales ? h('span', { class: 'chip mal' }, icono('candado'), 'Datos personales') : null,
      botonFicha(a, function () { invalidar(); recargarTarjeta(); }));
    if (a.puede_bajar) fila.appendChild(h('a', { class: 'btn lisa chico', href: BASE + 'archivos/' + a.id, download: a.nombre }, icono('bajar'), 'Bajar'));
    if (a.puede_borrar) fila.appendChild(h('button', { class: 'btn no chico', type: 'button', onclick: async function () {
      const ok = await confirmar({ titulo: '¿Borrar este archivo?', texto: 'Se borra el archivo y queda la constancia de que existió: nombre, tamaño, quién lo subió y quién lo borró.', ok: 'Borrar archivo', clase: 'no' });
      if (!ok) return; errorEn(fila, '');
      try { await enviarJson('archivos/' + a.id + '/borrar', {}); avisar('Archivo borrado.'); invalidar(); recargarTarjeta(); }
      catch (er) { avisar(er.message, true); }
    } }, icono('basura'), 'Borrar'));
    return fila;
  }
  function botonReabrir(t) {
    return h('button', { class: 'btn lisa', type: 'button', onclick: async function (ev) {
      const b = ev.currentTarget; b.disabled = true;
      try { const fd = new FormData(); fd.append('estado_nuevo', 'abierta'); reemplazarTarjeta(await enviarForm('tarjetas/' + t.id + '/responder', fd)); avisar('La tarjeta volvió a estar abierta.'); }
      catch (er) { avisar(er.message, true); b.disabled = false; }
    } }, 'Reabrir tarjeta');
  }
  function formReasignar(t) {
    const nom = h('input', { type: 'text', maxlength: 80, value: t.responsable || '', 'aria-label': 'Responsable' });
    const lado = h('select', { class: 'campo', 'aria-label': 'Lado del responsable' }, h('option', { value: 'equipo' }, 'Colm3na'), h('option', { value: 'sindicato' }, 'Sindicato'));
    const cont = h('div', { class: 'edit-fila' });
    const det = h('details', null, h('summary', null, 'Cambiar responsable'), h('div', { style: 'display:grid;gap:8px;margin-top:6px' }, nom, lado, cont,
      h('button', { class: 'btn pri chico', type: 'button', onclick: async function (ev) {
        const b = ev.currentTarget; b.disabled = true; errorEn(cont, '');
        try { reemplazarTarjeta(await enviarJson('tarjetas/' + t.id + '/reasignar', { responsable: nom.value.trim(), responsable_lado: lado.value })); avisar('Responsable actualizado.'); }
        catch (er) { errorEn(cont, er.message); b.disabled = false; }
      } }, 'Guardar')));
    return det;
  }
  function panelDecision(t) {
    const caja = colorTipo(h('div', { class: 'decision' }), t.tipo);
    const sol = h('div', { class: 'botones' });
    caja.appendChild(h('b', null, 'Esta aprobación espera tu decisión'));
    caja.appendChild(h('p', null, 'Es formal y no se puede deshacer: queda registrada con tu nombre y la fecha.'));
    function decidir(aprobar) {
      return async function (ev) {
        const b = ev.currentTarget;
        const ok = await confirmar({
          titulo: aprobar ? '¿Aprobar?' : '¿Rechazar?', ok: aprobar ? 'Sí, aprobar' : 'Sí, rechazar', clase: aprobar ? 'si' : 'no',
          texto: 'Es irreversible: queda registrada con tu nombre y la fecha, y después nadie la puede cambiar. «' + t.titulo + '».',
          motivo: 'Comentario (opcional)'
        });
        if (!ok) return; b.disabled = true; errorEn(caja, '');
        try { reemplazarTarjeta(await enviarJson('tarjetas/' + t.id + '/aprobacion', { aprobar: aprobar, texto: ok.texto || '' })); avisar(aprobar ? 'Quedó aprobada.' : 'Quedó rechazada.'); }
        catch (er) { errorEn(caja, er.message); b.disabled = false; }
      };
    }
    sol.appendChild(h('button', { class: 'btn si', type: 'button', onclick: decidir(true) }, icono('check'), 'Aprobar'));
    sol.appendChild(h('button', { class: 'btn no', type: 'button', onclick: decidir(false) }, icono('cerrar'), 'Rechazar'));
    caja.appendChild(sol);
    return caja;
  }
  // I16: quien recibe una entrega la cierra con un botón, o avisa el problema (texto obligatorio).
  // La pantalla dibuja lo que `acciones` dice (recibido / problema), nada más.
  function panelEntrega(t, acc) {
    const caja = colorTipo(h('div', { class: 'decision entrega-panel', role: 'group', 'aria-label': 'Recibir la entrega' }), t.tipo);
    const botones = h('div', { class: 'botones entrega-botones' });
    const zona = h('div', null);
    const form = h('form', { class: 'entrega-problema', hidden: true, novalidate: true });
    const texto = h('textarea', { id: 'en-prob-t', maxlength: 5000, 'aria-label': 'Contá cuál es el problema', placeholder: 'Contá qué pasa con el archivo (obligatorio)' });
    const enviar = h('button', { class: 'btn no', type: 'submit' }, icono('enviar'), 'Avisar el problema');
    const bRecibido = acc.recibido ? h('button', { class: 'btn si', type: 'button', onclick: async function (ev) {
      const b = ev.currentTarget;
      const ok = await confirmar({ titulo: '¿Dar por recibida?', texto: 'La entrega se cierra y queda anotado que la recibiste vos, con la fecha. «' + t.titulo + '».',
        ok: 'Sí, recibido', clase: 'si', motivo: 'Comentario (opcional)' });
      if (!ok) return; b.disabled = true; errorEn(zona, '');
      try { reemplazarTarjeta(await enviarJson('tarjetas/' + t.id + '/entrega', { recibido: true, texto: ok.texto || '' })); avisar('Entrega recibida.'); }
      catch (er) { errorEn(zona, er.message); b.disabled = false; }
    } }, icono('check'), 'Recibido, está bien') : null;
    const bProblema = acc.problema ? h('button', { class: 'btn no', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'en-prob-f', onclick: function (ev) {
      const abrir = form.hidden; form.hidden = !abrir; ev.currentTarget.setAttribute('aria-expanded', String(abrir));
      if (abrir) texto.focus();
    } }, icono('alerta'), 'Hay un problema') : null;
    form.id = 'en-prob-f';
    form.appendChild(h('label', { class: 'l', for: 'en-prob-t' }, 'Qué pasa con el archivo'));
    form.appendChild(texto);
    form.appendChild(enviar);
    form.addEventListener('submit', async function (ev) {
      ev.preventDefault(); errorEn(zona, '');
      if (!texto.value.trim()) { errorEn(zona, 'Contá cuál es el problema para poder avisarlo.'); texto.focus(); return; }
      enviar.disabled = true;
      try { reemplazarTarjeta(await enviarJson('tarjetas/' + t.id + '/entrega', { recibido: false, texto: texto.value.trim() })); avisar('Le avisamos a quien la mandó.'); }
      catch (er) { errorEn(zona, er.message); enviar.disabled = false; }
    });
    caja.appendChild(h('b', null, 'Esta entrega espera que digas si la recibiste'));
    caja.appendChild(h('p', null, 'Si el archivo está bien, cerrala con «Recibido». Si no, contá el problema y vuelve a quien la mandó.'));
    if (bRecibido) botones.appendChild(bRecibido);
    if (bProblema) botones.appendChild(bProblema);
    caja.appendChild(botones);
    caja.appendChild(form);
    caja.appendChild(zona);
    return caja;
  }
  function redactor(t, acc) {
    const permitidos = estadosPermitidos(acc);
    const texto = h('textarea', { id: 'rd-texto', maxlength: 5000, 'aria-label': 'Tu respuesta', placeholder: 'Escribí tu respuesta' });
    const selEstado = h('select', { id: 'rd-estado' }, h('option', { value: '' }, 'Sin cambiar (' + nombreEstado(t.estado) + ')'),
      permitidos.filter(function (e) { return e !== t.estado; }).map(function (e) { return h('option', { value: e }, nombreEstado(e)); }));
    if (permitidos.indexOf('respondida') !== -1 && t.estado !== 'respondida') selEstado.value = 'respondida';
    const interno = acc.solo_equipo ? h('input', { type: 'checkbox', id: 'rd-int' }) : null;
    const archivos = acc.subir ? h('input', { type: 'file', id: 'rd-arch', multiple: true, 'aria-label': 'Adjuntar archivos' }) : null;
    const dp = acc.subir ? h('input', { type: 'checkbox', id: 'rd-dp' }) : null;
    const dpFila = acc.subir ? h('label', { class: 'chk', hidden: true }, dp, 'Los archivos contienen datos personales') : null;
    if (archivos) archivos.addEventListener('change', function () { dpFila.hidden = !archivos.files.length; });
    const boton = h('button', { class: 'btn pri', type: 'submit' }, icono('enviar'), h('span', null, 'Enviar'));
    const zonaError = h('div', null);
    function rotular() {
      const nota = interno && interno.checked;
      let s = nota ? 'Guardar nota interna' : 'Enviar respuesta';
      if (selEstado.value) s += ' y pasar a ' + nombreEstado(selEstado.value);
      boton.lastChild.textContent = s;
    }
    selEstado.addEventListener('change', rotular);
    if (interno) interno.addEventListener('change', function () { if (interno.checked) selEstado.value = ''; rotular(); });
    rotular();
    const ayudaTxt = h('p', { class: 'ayuda-cod', id: 'rd-ayuda', hidden: true }, 'Podés nombrar otra tarjeta o archivo por su código (PE0004, AR000123) y queda enlazado.');
    const ayudaBtn = h('button', { class: 'ayuda-q', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'rd-ayuda', 'aria-label': 'Ayuda: nombrar otra tarjeta o archivo',
      onclick: function () { const ab = ayudaTxt.hidden; ayudaTxt.hidden = !ab; ayudaBtn.setAttribute('aria-expanded', String(ab)); } }, '?');
    const f = h('form', { class: 'redactor', novalidate: true },
      h('div', { class: 'rd-rot' }, h('label', { class: 'l', for: 'rd-texto' }, 'Tu respuesta'), ayudaBtn), ayudaTxt, texto,
      interno ? h('label', { class: 'chk interno', for: 'rd-int' }, interno, icono('candado'), 'Solo equipo (el sindicato no lo ve)') : null,
      archivos ? h('div', { class: 'arch' }, h('label', { class: 'l', for: 'rd-arch' }, h('span', null, 'Adjuntar archivos')), archivos, dpFila) : null,
      h('div', { class: 'fila-envio' }, h('label', { class: 'l', for: 'rd-estado' }, 'Al enviar, pasa a', selEstado), boton), zonaError);
    f.addEventListener('submit', async function (ev) {
      ev.preventDefault(); errorEn(zonaError, '');
      const hayArchivos = archivos && archivos.files.length;
      if (!texto.value.trim() && !selEstado.value && !hayArchivos) { errorEn(zonaError, 'Escribí algo, adjuntá un archivo o elegí a qué estado pasa.'); texto.focus(); return; }
      if (hayArchivos) { const pb = pesoArchivos(archivos.files); if (pb) { errorEn(zonaError, pb); return; } }
      const fd = new FormData();
      if (texto.value.trim()) fd.append('texto', texto.value.trim());
      if (selEstado.value) fd.append('estado_nuevo', selEstado.value);
      if (interno && interno.checked) fd.append('solo_equipo', 'true');
      if (hayArchivos) { Array.prototype.forEach.call(archivos.files, function (a) { fd.append('archivos', a); }); fd.append('datos_personales', dp.checked ? 'true' : 'false'); }
      boton.disabled = true;
      try { reemplazarTarjeta(await enviarForm('tarjetas/' + t.id + '/responder', fd)); avisar('Enviado.'); }
      catch (er) { errorEn(zonaError, er.message); boton.disabled = false; }
    });
    return f;
  }

  // ---------------------------------------------------------------- búsqueda
  function vistaBuscar(q) {
    return montar('buscar', async function () {
      const d = await pedir('tarjetas?vista=todas&q=' + encodeURIComponent(q));
      const lista = d.tarjetas || [];
      const raiz = h('div', null, titulo('Resultados', lista.length ? lista.length + (lista.length === 1 ? ' tarjeta' : ' tarjetas') + ' con «' + q + '».' : null));
      raiz.appendChild(lista.length ? h('div', { class: 'tiles' }, lista.map(tile)) : vacio('No encontramos tarjetas con «' + q + '». Probá con otra palabra o con un código, por ejemplo PE0004.'));
      return raiz;
    });
  }
  function buscar(valor) {
    const v = (valor || '').trim();
    if (!v) return;
    const destino = esCodigo(v) ? '#' + v.toUpperCase() : '#buscar?q=' + encodeURIComponent(v);
    if (window.location.hash === destino) ruta(); else window.location.hash = destino;
  }
  document.querySelectorAll('[data-buscador]').forEach(function (f) {
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      const inp = f.querySelector('input'); buscar(inp.value);
      if (document.activeElement && document.activeElement.blur && window.matchMedia('(max-width: 860px)').matches) document.activeElement.blur();
    });
  });

  // ---------------------------------------------------------------- rutas
  function ruta() {
    const p = parseHash();
    let r = p.ruta;
    const m = /^t(\d+)$/.exec(r);
    if (m) { marcarNav(S.ultima); vistaTarjeta(+m[1]); return; }
    if (esCodigo(r)) {
      const c = r.toUpperCase();
      // Ya estoy en esa tarjeta: no la rearmo (perdería lo que se está escribiendo).
      const aqui = $vista.querySelector('.tj-cab') && S.actual && (c === S.actualCodigo || $vista.querySelector('[data-codigo="' + c + '"]'));
      if (aqui) { marcarNav(S.ultima); resaltar($vista.querySelector('[data-codigo="' + c + '"]')); return; }
      marcarNav(S.ultima); vistaCodigo(c); return;
    }
    if (r === 'buscar' && !(p.q.q || '').trim()) { window.location.hash = '#pendientes'; return; }
    if (r === 'buscar') { S.actual = null; marcarNav(null); vistaBuscar(p.q.q || ''); return; }
    if (['pendientes', 'tablero', 'plan', 'carpetas', 'aprobaciones', 'nueva'].indexOf(r) === -1) r = 'pendientes';
    S.actual = null;
    if (r !== 'nueva') S.ultima = r;
    marcarNav(r === 'nueva' ? S.ultima : r);
    if (r === 'tablero') vistaTablero();
    else if (r === 'plan') vistaPlan();
    else if (r === 'carpetas') vistaCarpetas();
    else if (r === 'aprobaciones') vistaAprobaciones();
    else if (r === 'nueva') vistaNueva(p.q);
    else vistaPendientes();
  }

  const $sel = document.getElementById('sel-proyecto');
  if ($sel) $sel.addEventListener('change', function () { window.location.href = '/implementacion?p=' + encodeURIComponent($sel.value); });
  window.addEventListener('hashchange', ruta);
  if (!PID) {
    vaciar($vista).appendChild(vacio('No hay un proyecto elegido. Creá uno desde Entornos → Implementación.'));
  } else {
    ruta();
    setInterval(function () { if (!document.hidden) refrescarGlobo(); }, 60000);
  }
})();
