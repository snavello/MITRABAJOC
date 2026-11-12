/* App del sindicato de la Fiesta (login, panel, puerta, padrón, cortesías,
   configuración). Todo el texto de personas entra con textContent: ningún dato
   se arma como HTML. */
(function () {
  'use strict';
  var B = '/api/fiesta/sindicato/';
  var body = document.body;
  var ROL = body.dataset.rol || '';
  var MP_MODO = body.dataset.mpModo || 'apagado';
  var $ = function (id) { return document.getElementById(id); };

  // ---------- utilidades ----------
  function miles(n) { return window.NumAR && NumAR.miles ? NumAR.miles(n) : String(n); }
  function pesos(n) { return '$ ' + miles(Math.round(Number(n || 0))); } // sin centavos: son entradas enteras

  function fechaCorta(iso) {
    if (!iso) return '';
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    if (!m) return String(iso);
    return m[3] + '/' + m[2] + ' ' + m[4] + ':' + m[5];
  }

  function el(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'class') e.className = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (ev) { e.addEventListener(ev, attrs.on[ev]); });
      else e.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var h = arguments[i];
      if (h == null) continue;
      e.appendChild(typeof h === 'string' ? document.createTextNode(h) : h);
    }
    return e;
  }
  function vaciar(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function lista(d, clave) { return Array.isArray(d) ? d : ((d && d[clave]) || []); }

  // Un 502/503/504 de Render trae HTML: nunca se le muestra eso a nadie.
  function errorServidor(status, extra) {
    var e = new Error('El servidor no respondió' + (status ? ' (código HTTP ' + status + ')' : '') + '. Probá de nuevo en unos segundos.');
    e.status = status; e.esServidor = true;
    if (extra) Object.assign(e, extra);
    return e;
  }
  async function pedirJson(url, opc) {
    opc = opc || {};
    var init = { method: opc.method || 'GET', credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (opc.json !== undefined) { init.method = opc.method || 'POST'; init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opc.json); }
    else if (opc.form) { init.method = 'POST'; init.body = opc.form; }
    else if (init.method === 'POST') { init.headers['Content-Type'] = 'application/json'; init.body = '{}'; }
    var r;
    try { r = await fetch(url, init); } catch (_) { throw errorServidor(0); }
    var data = null, hayJson = true;
    try { data = await r.json(); } catch (_) { hayJson = false; }
    if (r.status === 401 && !opc.sin401) { location.reload(); throw errorServidor(401); }
    if (!r.ok) {
      var msg = hayJson && data && typeof data.detail === 'string' ? data.detail : null;
      if (!msg) throw errorServidor(r.status, { data: data });
      var e = new Error(msg); e.status = r.status; e.codigo = data.codigo || ''; e.data = data;
      throw e;
    }
    if (!hayJson) throw errorServidor(r.status);
    return data;
  }
  function textoError(e) {
    var t = e && e.message ? e.message : 'No se pudo completar la operación.';
    return e && e.codigo ? t + ' (' + e.codigo + ')' : t;
  }
  function mostrar(nodo, texto, esError) {
    if (!nodo) return;
    nodo.textContent = texto || '';
    nodo.hidden = !texto;
    if (esError !== undefined) nodo.classList.toggle('fs-error', !!esError);
  }
  var toastT;
  function toast(t) {
    var n = $('toast'); if (!n) return;
    n.textContent = t; n.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { n.hidden = true; }, 3200);
  }
  function enviando(boton, v) { if (boton) boton.disabled = !!v; }
  function formDatos(f) {
    var o = {};
    new FormData(f).forEach(function (v, k) { o[k] = typeof v === 'string' ? v.trim() : v; });
    return o;
  }
  function pildora(texto, clase) { return el('span', { class: 'fs-pildora ' + (clase || ''), text: texto }); }
  function celda(rotulo, hijo, clase) {
    var td = el('td', { 'data-r': rotulo });
    if (clase) td.className = clase;
    if (hijo != null) td.appendChild(typeof hijo === 'string' ? document.createTextNode(hijo) : hijo);
    return td;
  }
  var ESTADO_CLASE = { pagada: 'ok', pendiente: 'aviso', vencida: '', anulada: 'mal' };

  // ---------- cerrar sesión (siempre que haya sesión) ----------
  var salir = $('btn-salir');
  if (salir) salir.addEventListener('click', async function () {
    try { await pedirJson(B + 'salir', { method: 'POST', sin401: true }); } catch (_) { /* igual se recarga */ }
    location.reload();
  });

  // ---------- login ----------
  var fl = $('form-login');
  if (fl) fl.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var b = fl.querySelector('button'); enviando(b, true); mostrar($('login-error'), '');
    try {
      await pedirJson(B + 'entrar', { json: formDatos(fl), sin401: true });
      location.reload();
    } catch (e) { mostrar($('login-error'), textoError(e), true); enviando(b, false); }
  });

  // ---------- cambio de clave ----------
  var fc = $('form-clave');
  if (fc) fc.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var d = formDatos(fc), b = fc.querySelector('button');
    if (d.nueva !== d.repetir) { mostrar($('clave-error'), 'Las dos claves nuevas no coinciden.', true); return; }
    if (d.nueva === d.actual) { mostrar($('clave-error'), 'La clave nueva tiene que ser distinta de la actual.', true); return; }
    enviando(b, true); mostrar($('clave-error'), '');
    try { await pedirJson(B + 'clave', { json: d }); location.reload(); }
    catch (e) { mostrar($('clave-error'), textoError(e), true); enviando(b, false); }
  });

  if (!$('tabs')) return; // login o cambio de clave: no hay más

  // ---------- pestañas ----------
  var cargadas = {};
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.fs-tab'));
  var cargadores = {
    panel: function () { cargarResumen(); cargarReservas(); },
    puerta: function () { cargarResumenMini(); iniciarCamaraSiCorresponde(); },
    padron: function () { cargarPadron(); },
    cortesias: function () { cargarLeyendaCortesia(); },
    config: function () { cargarConfig(); cargarOperadores(); }
  };
  function activar(nombre) {
    if (!document.querySelector('.fs-tab[data-tab="' + nombre + '"]')) nombre = tabs[0].dataset.tab;
    tabs.forEach(function (t) { t.setAttribute('aria-selected', t.dataset.tab === nombre ? 'true' : 'false'); });
    document.querySelectorAll('.fs-panel').forEach(function (p) { p.hidden = p.dataset.panel !== nombre; });
    if (nombre !== 'puerta') detenerCamara();
    try { history.replaceState(null, '', '#' + nombre); } catch (_) {}
    (cargadores[nombre] || function () {})();
  }
  tabs.forEach(function (t) { t.addEventListener('click', function () { activar(t.dataset.tab); }); });
  // La pestaña inicial se activa al final del script (necesita todo ya definido).
  setTimeout(function () { activar(location.hash.slice(1) || tabs[0].dataset.tab); }, 0);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) detenerCamara();
    else if (location.hash === '#puerta' || ROL === 'puerta') iniciarCamaraSiCorresponde();
  });

  // ---------- PANEL ----------
  async function cargarResumen() {
    var caja = $('contadores'); if (!caja) return;
    try {
      var d = await pedirJson(B + 'resumen'), c = d.contadores || {};
      var fichas = [
        ['Padrón cargado', c.padron, false, c.padron_total > c.padron ? (c.padron_total - c.padron) + ' desactivados' : ''],
        ['Personas pagadas', c.personas_pagadas, true], ['Reservas pagadas', c.pagadas],
        ['Pendientes de pago', c.pendientes], ['Disponibles', c.disponibles, true],
        ['Ya ingresaron', c.ingresadas], ['Recaudado', pesos(c.recaudado)],
        ['Cortesías', c.cortesias], ['Vencidas', c.vencidas]
      ];
      vaciar(caja);
      fichas.forEach(function (f) {
        var v = typeof f[1] === 'string' ? f[1] : miles(f[1] || 0);
        var d1 = el('div', { class: 'fs-cont' + (f[2] ? ' destaca' : '') }, el('b', { text: v }), el('span', { text: f[0] }));
        if (f[3]) d1.appendChild(el('small', { class: 'fs-sub', text: f[3] }));
        caja.appendChild(d1);
      });
    } catch (e) { vaciar(caja); caja.appendChild(el('p', { class: 'fs-aviso fs-error', text: textoError(e) })); }
  }
  function cargarResumenMini() { /* los ingresos se ven en el panel; la puerta no los necesita */ }

  var filtros = $('filtros');
  function consultaFiltros() {
    var p = new URLSearchParams();
    new FormData(filtros).forEach(function (v, k) { v = String(v).trim(); if (v && !(k === 'ingreso' && v === 'todas')) p.set(k, v); });
    return p.toString();
  }
  var tEsp;
  async function cargarReservas() {
    if (!filtros) return;
    var qs = consultaFiltros();
    $('btn-csv').setAttribute('href', '/fiesta/sindicato/reservas.csv' + (qs ? '?' + qs : ''));
    var tb = document.querySelector('#tabla-reservas tbody');
    try {
      var d = await pedirJson(B + 'reservas' + (qs ? '?' + qs : ''));
      var filas = lista(d, 'reservas');
      vaciar(tb);
      $('reservas-vacio').hidden = filas.length > 0;
      var tot = d && d.total != null ? d.total : filas.length;
      $('reservas-cuenta').textContent = filas.length ? miles(tot) + (tot === 1 ? ' reserva' : ' reservas') + (tot > filas.length ? ' (se muestran las primeras ' + miles(filas.length) + ': afiná los filtros)' : '') : '';
      filas.forEach(function (r) { tb.appendChild(filaReserva(r)); });
    } catch (e) { vaciar(tb); mostrarErrorTabla($('reservas-cuenta'), e); }
  }
  function mostrarErrorTabla(nodo, e) { nodo.textContent = textoError(e); }
  filtros && filtros.addEventListener('input', function () { clearTimeout(tEsp); tEsp = setTimeout(cargarReservas, 300); });
  filtros && filtros.addEventListener('submit', function (e) { e.preventDefault(); cargarReservas(); });

  function filaReserva(r) {
    var tr = el('tr');
    var nombre = el('span', { text: r.nombre || '—' });
    var tdN = celda('Nombre', nombre);
    if (r.tipo === 'cortesia') { tdN.appendChild(el('span', { class: 'fs-sub', text: 'Cortesía' + (r.leyenda ? ' · ' + r.leyenda : '') })); }
    if (r.nota) tdN.appendChild(el('span', { class: 'fs-sub', text: 'Nota: ' + r.nota }));
    if (r.sobrecupo) tdN.appendChild(el('span', { class: 'fs-sub', text: 'Sobrecupo: pagó cuando ya no había lugar' }));
    tr.appendChild(tdN);
    tr.appendChild(celda('Legajo', r.legajo || '—'));
    tr.appendChild(celda('DNI', r.dni || '—'));
    tr.appendChild(celda('Personas', String(r.cantidad), 'num'));
    var st = el('span');
    st.appendChild(pildora(r.estado || '', ESTADO_CLASE[r.estado] || ''));
    var cuando = r.estado === 'pagada' ? r.pagada_en : (r.estado === 'pendiente' ? r.vence : r.creada);
    if (cuando) st.appendChild(el('span', { class: 'fs-sub', text: (r.estado === 'pendiente' ? 'vence ' : '') + fechaCorta(cuando) }));
    tr.appendChild(celda('Estado', st));
    var ing = Number(r.ingresados || 0);
    tr.appendChild(celda('Ingresos', ing ? ing + ' de ' + r.cantidad + (r.ultimo_ingreso ? ' · ' + fechaCorta(r.ultimo_ingreso) : '') : '—'));
    var acc = el('td', { class: 'acc' });
    var url = r.url_entrada || ('/fiesta/entrada/' + r.id + (r.token && r.tipo === 'cortesia' ? '?t=' + encodeURIComponent(r.token) : ''));
    if (r.estado === 'pagada') acc.appendChild(el('a', { class: 'fs-btn fs-btn-mini', href: url, target: '_blank', rel: 'noopener', text: 'Ver entrada' }));
    acc.appendChild(el('button', { type: 'button', class: 'fs-btn fs-btn-mini', text: 'Nota', on: { click: function () { editarNota(r); } } }));
    if (r.estado === 'pendiente' || (r.tipo === 'cortesia' && r.estado === 'pagada')) {
      acc.appendChild(el('button', { type: 'button', class: 'fs-btn fs-btn-mini peligro', text: 'Anular', on: { click: function () { anularReserva(r); } } }));
    }
    tr.appendChild(acc);
    return tr;
  }
  async function anularReserva(r) {
    if (!confirm('¿Anular la reserva de ' + (r.nombre || 'esta persona') + '? Las ' + r.cantidad + ' entradas vuelven al cupo.')) return;
    try { await pedirJson(B + 'reserva/' + r.id + '/anular', { method: 'POST' }); toast('Reserva anulada'); cargarReservas(); cargarResumen(); }
    catch (e) { toast(textoError(e)); }
  }
  async function editarNota(r) {
    var n = prompt('Nota de la reserva de ' + (r.nombre || ''), r.nota || '');
    if (n === null) return;
    try { await pedirJson(B + 'reserva/' + r.id + '/nota', { json: { nota: n.trim() } }); cargarReservas(); }
    catch (e) { toast(textoError(e)); }
  }

  // ---------- PUERTA ----------
  var video = $('video'), lienzo = $('lienzo'), ctx = null;
  var stream = null, timer = null, detector = null, ocupado = false, quiereCamara = true;
  var memoria = { texto: '', t: 0 };
  var tCierre = null, pendienteQr = null;

  function msgCamara(t, estado) { $('camara-msg').textContent = t; $('camara-estado').textContent = estado || ''; }
  async function iniciarCamara() {
    if (stream) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      msgCamara('Este navegador no deja usar la cámara (hace falta abrir la página por https). Pegá el texto del QR abajo.', 'Sin cámara');
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    } catch (e) {
      stream = null;
      var negada = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
      msgCamara(negada ? 'No diste permiso para usar la cámara. Habilitala en el navegador, o pegá el texto del QR abajo.'
                       : 'No se encontró una cámara. Pegá el texto del QR abajo.', negada ? 'Permiso negado' : 'Sin cámara');
      $('btn-camara').textContent = 'Reintentar cámara';
      return;
    }
    video.srcObject = stream;
    try { await video.play(); } catch (_) {}
    $('video-caja').classList.add('activa');
    $('btn-camara').textContent = 'Apagar cámara';
    msgCamara('', 'Apuntá al QR de la entrada');
    if (!detector && 'BarcodeDetector' in window) {
      try { detector = new BarcodeDetector({ formats: ['qr_code'] }); } catch (_) { detector = null; }
    }
    clearInterval(timer);
    timer = setInterval(leerCuadro, 100);
  }
  function detenerCamara() {
    clearInterval(timer); timer = null;
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    if (video) video.srcObject = null;
    var caja = $('video-caja'); if (caja) caja.classList.remove('activa');
    var bc = $('btn-camara'); if (bc) bc.textContent = 'Activar cámara';
    var cm = $('camara-msg'); if (cm && !cm.textContent) msgCamara('La cámara está apagada.', '');
  }
  function iniciarCamaraSiCorresponde() { if (quiereCamara) iniciarCamara(); }
  $('btn-camara').addEventListener('click', function () {
    if (stream) { quiereCamara = false; detenerCamara(); msgCamara('La cámara está apagada.', ''); }
    else { quiereCamara = true; iniciarCamara(); }
  });

  async function leerCuadro() {
    if (ocupado || !stream || video.readyState < 2) return;
    ocupado = true;
    try {
      var texto = '';
      if (detector) {
        try { var r = await detector.detect(video); if (r && r.length) texto = r[0].rawValue; }
        catch (_) { detector = null; }
      }
      if (!texto && !detector && window.jsQR) {
        var vw = video.videoWidth, vh = video.videoHeight;
        if (vw) {
          var esc = Math.min(1, 640 / Math.max(vw, vh));
          var w = Math.round(vw * esc), h = Math.round(vh * esc);
          if (lienzo.width !== w || lienzo.height !== h) { lienzo.width = w; lienzo.height = h; }
          ctx = ctx || lienzo.getContext('2d', { willReadFrequently: true });
          ctx.drawImage(video, 0, 0, w, h);
          var c = jsQR(ctx.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: 'dontInvert' });
          if (c) texto = c.data;
        }
      }
      if (texto) await alLeer(texto);
    } finally { if (!pendienteQr && $('res').hidden) ocupado = false; }
  }

  // Del texto del QR: <base>/fiesta/e/{token}?k={codigo}
  function parsearQr(texto) {
    texto = String(texto || '').trim();
    var token = '', k = '';
    try {
      var u = new URL(texto, location.origin);
      var m = u.pathname.match(/\/fiesta\/e\/([^/?#]+)/);
      if (m) { token = decodeURIComponent(m[1]); k = u.searchParams.get('k') || ''; }
    } catch (_) {}
    if (!token) {
      var m2 = texto.match(/\/fiesta\/e\/([A-Za-z0-9_-]+)/), k2 = texto.match(/[?&]k=([^&#\s]+)/);
      if (m2) { token = m2[1]; k = k2 ? decodeURIComponent(k2[1]) : ''; }
    }
    return token && k ? { token: token, k: k } : null;
  }

  async function alLeer(texto) {
    var ahora = Date.now();
    if (texto === memoria.texto && ahora - memoria.t < 5000) return; // el mismo QR seguido
    memoria = { texto: texto, t: ahora };
    ocupado = true;
    var qr = parsearQr(texto);
    if (!qr) return resultado('mal', 'No es una entrada', '', 'Ese código no es de esta fiesta.');
    if ($('chk-elegir').checked) return preguntarCantidad(qr);
    await enviarQr(qr, undefined);
  }

  // Cómo se muestra cada rechazo de /ingreso/qr (y de la verificación previa).
  async function rechazoQr(e, qr) {
    var cod = e.codigo || '';
    if (e.esServidor) return resultado('mal', 'Sin conexión con el servidor', '', 'Volvé a escanear en unos segundos.');
    if (cod === 'E-FIESTA-08') {
      var nom = '', det = '';
      try { // el rechazo no trae a la persona: se la pide sin registrar nada
        var v = await pedirJson(B + 'ingreso/qr', { json: { token: qr.token, k: qr.k, solo_verificar: true } });
        nom = (v.reserva && v.reserva.nombre) || ''; det = v.reserva ? 'Ingresaron las ' + v.reserva.cantidad + ' personas.' : '';
      } catch (_) {}
      return resultado('mal', 'Ya ingresó todo', nom, det);
    }
    if (cod === 'E-FIESTA-07') return resultado('mal', 'Código vencido', '', 'Que la persona renueve la pantalla de su entrada.');
    if (cod === 'E-FIESTA-09') return resultado('mal', 'Reserva sin pagar', '', 'Esta entrada todavía no está paga.');
    if (e.status === 404) return resultado('mal', 'No existe', '', 'Ese código no corresponde a ninguna entrada.');
    resultado('mal', 'No se pudo registrar', '', textoError(e));
  }

  async function enviarQr(qr, cantidad) {
    var cuerpo = { token: qr.token, k: qr.k };
    if (cantidad) cuerpo.cantidad = cantidad;
    try {
      var d = await pedirJson(B + 'ingreso/qr', { json: cuerpo });
      var rs = d.reserva || {};
      var tot = Number(rs.cantidad || 0), antes = Number(d.ya_ingresados || 0), faltan = Number(d.faltan || 0);
      var pasan = Number(d.ingresaron != null ? d.ingresaron : (cantidad || tot));
      var pers = pasan === 1 ? '1 persona' : pasan + ' personas';
      if (antes > 0) {
        resultado('aviso', 'Ya ingresaron ' + antes + ' de ' + tot, rs.nombre, 'Pasan ' + pasan + '.' + (faltan ? ' Faltan ' + faltan + '.' : ''));
      } else {
        resultado('ok', 'Pasa · ' + pers, rs.nombre, faltan ? 'Faltan ' + faltan + ' por ingresar.' : (tot > 1 ? 'Entraron todas.' : ''));
      }
      cargarResumen();
    } catch (e) { await rechazoQr(e, qr); }
  }

  // --- resultado a pantalla completa ---
  var ICONOS = {
    ok: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="21"/><path d="M14 25l7 7 13-15"/></svg>',
    aviso: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="21"/><path d="M24 13v14M24 33v2"/></svg>',
    mal: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="21"/><path d="M16 16l16 16M32 16L16 32"/></svg>',
    pregunta: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="21"/><path d="M18 19a6 6 0 1 1 9 5c-2 1-3 2-3 5M24 34v1"/></svg>'
  };
  function ponerIcono(tipo) {
    var c = $('res-icono'); vaciar(c);
    var doc = new DOMParser().parseFromString(ICONOS[tipo], 'image/svg+xml'); // constante propia, sin datos
    c.appendChild(document.importNode(doc.documentElement, true));
  }
  function resultado(tipo, titulo, nombre, detalle) {
    var r = $('res');
    clearTimeout(tCierre);
    r.className = 'fs-res ' + tipo; r.hidden = false;
    ponerIcono(tipo);
    $('res-titulo').textContent = titulo;
    $('res-nombre').textContent = nombre || '';
    $('res-detalle').textContent = detalle || '';
    $('res-menos').hidden = true;
    $('res-cerrar').textContent = 'Seguir escaneando';
    if (navigator.vibrate) { try { navigator.vibrate(tipo === 'ok' ? 120 : (tipo === 'aviso' ? [120, 80, 120] : [300, 100, 300])); } catch (_) {} }
    tCierre = setTimeout(cerrarResultado, 2500);
  }
  function cerrarResultado() {
    clearTimeout(tCierre);
    $('res').hidden = true; pendienteQr = null; ocupado = false;
  }
  $('res-cerrar').addEventListener('click', cerrarResultado);

  // Elegir cuántas pasan, antes de registrar: primero se verifica (sin registrar)
  // para saber a quién se le abre y cuántas faltan.
  var cant = 1, maxCant = 50;
  async function preguntarCantidad(qr) {
    var v;
    try { v = await pedirJson(B + 'ingreso/qr', { json: { token: qr.token, k: qr.k, solo_verificar: true } }); }
    catch (e) { return rechazoQr(e, qr); }
    var rs = v.reserva || {}, faltan = Number(v.faltan || 0);
    if (faltan <= 0) return rechazoQr({ codigo: 'E-FIESTA-08' }, qr);
    pendienteQr = qr; cant = Math.min(1, faltan); maxCant = faltan;
    var r = $('res');
    clearTimeout(tCierre);
    r.className = 'fs-res pregunta'; r.hidden = false;
    ponerIcono('pregunta');
    $('res-titulo').textContent = '¿Cuántas pasan?';
    $('res-nombre').textContent = rs.nombre || '';
    $('res-detalle').textContent = 'Admite ' + rs.cantidad + ' · faltan ' + faltan + ' por ingresar.';
    $('res-menos').hidden = false; $('cant-valor').textContent = String(cant);
    $('res-cerrar').textContent = 'Cancelar';
  }
  $('cant-menos').addEventListener('click', function () { cant = Math.max(1, cant - 1); $('cant-valor').textContent = cant; });
  $('cant-mas').addEventListener('click', function () { cant = Math.min(maxCant, cant + 1); $('cant-valor').textContent = cant; });
  $('btn-registrar-menos').addEventListener('click', async function () {
    var qr = pendienteQr; if (!qr) return;
    pendienteQr = null; $('res').hidden = true;
    await enviarQr(qr, cant);
  });

  $('form-pegar').addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var t = $('texto-qr').value.trim(); if (!t) return;
    memoria = { texto: '', t: 0 };
    $('texto-qr').value = '';
    await alLeer(t);
  });

  // --- ingreso con documento ---
  var fb = $('form-buscar');
  fb.addEventListener('submit', function (ev) { ev.preventDefault(); buscar(); });
  async function buscar() {
    var q = fb.q.value.trim(); if (!q) return;
    var box = $('buscar-res'); mostrar($('buscar-error'), '');
    try {
      var d = await pedirJson(B + 'buscar?q=' + encodeURIComponent(q)), filas = lista(d, 'resultados');
      if (!filas.length && d && d.reservas) filas = d.reservas;
      vaciar(box);
      if (!filas.length) box.appendChild(el('p', { class: 'fs-vacio', text: 'No hay una entrada pagada ni una cortesía para esa búsqueda.' }));
      filas.forEach(function (r) { box.appendChild(tarjetaBusqueda(r)); });
    } catch (e) { vaciar(box); mostrar($('buscar-error'), textoError(e), true); }
  }
  function tarjetaBusqueda(r) {
    var id = r.reserva_id || r.id, tot = Number(r.cantidad || 0), ing = Number(r.ingresados || 0), falta = Math.max(tot - ing, 0);
    var t = el('div', { class: 'fs-tarjeta' });
    t.appendChild(el('h3', { text: r.nombre || '—' }));
    var fila = el('div', { class: 'fs-fila' });
    fila.appendChild(pildora(r.tipo === 'cortesia' ? 'Cortesía' : (r.estado || ''), ESTADO_CLASE[r.estado] || 'info'));
    if (r.legajo) fila.appendChild(el('span', { text: 'Legajo ' + r.legajo }));
    if (r.dni) fila.appendChild(el('span', { text: 'DNI ' + r.dni }));
    fila.appendChild(el('span', { text: tot + (tot === 1 ? ' persona' : ' personas') }));
    fila.appendChild(el('span', { text: ing ? 'Ingresaron ' + ing + ' de ' + tot : 'Nadie ingresó' }));
    t.appendChild(fila);
    if (r.estado && r.estado !== 'pagada') {
      t.appendChild(el('p', { class: 'fs-aviso fs-error', text: 'Esta reserva no está paga: no puede ingresar.' }));
    } else if (!falta) {
      t.appendChild(el('p', { class: 'fs-aviso', text: 'Ya ingresaron todas las personas.' }));
    } else {
      var f = el('form', { autocomplete: 'off' });
      var inpC = el('input', { name: 'cantidad', type: 'number', min: '1', max: String(falta), value: String(falta), required: '' });
      var inpM = el('input', { name: 'motivo', placeholder: 'Por ejemplo: perdió el teléfono', required: '' });
      var b = el('button', { type: 'submit', class: 'fs-btn fs-btn-oro', text: 'Registrar ingreso' });
      f.appendChild(el('label', { text: 'Personas' }, inpC));
      f.appendChild(el('label', { text: 'Motivo (obligatorio)' }, inpM));
      f.appendChild(b);
      f.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        var motivo = inpM.value.trim();
        if (!motivo) { toast('Escribí el motivo.'); return; }
        enviando(b, true);
        try {
          var d = await pedirJson(B + 'ingreso/documento', { json: { reserva_id: id, cantidad: Number(inpC.value), motivo: motivo } });
          var n = Number(inpC.value);
          resultado('ok', 'Pasa · ' + (n === 1 ? '1 persona' : n + ' personas'), r.nombre, 'Ingreso con documento registrado.');
          buscar(); cargarResumen();
        } catch (e) { toast(textoError(e)); enviando(b, false); }
      });
      t.appendChild(f);
    }
    return t;
  }

  if (ROL !== 'admin') return;

  // ---------- PADRÓN ----------
  var tPad;
  async function cargarPadron() {
    var q = document.querySelector('#form-padron-q input').value.trim();
    var tb = document.querySelector('#tabla-padron tbody');
    try {
      var d = await pedirJson(B + 'padron' + (q ? '?q=' + encodeURIComponent(q) : '')), filas = lista(d, 'padron');
      vaciar(tb);
      $('padron-vacio').hidden = filas.length > 0;
      $('padron-vacio').textContent = q ? 'Nadie coincide con esa búsqueda.' : 'El padrón todavía está vacío.';
      $('padron-cuenta').textContent = filas.length ? miles(filas.length) + (filas.length === 1 ? ' persona' : ' personas') + (d.total ? ' de ' + miles(d.total) : '') : '';
      filas.forEach(function (p) {
        var tr = el('tr');
        tr.appendChild(celda('Nombre', p.nombre));
        tr.appendChild(celda('Legajo', p.legajo));
        tr.appendChild(celda('DNI', p.dni));
        tr.appendChild(celda('Mail', p.mail || '—'));
        tr.appendChild(celda('Estado', pildora(p.activo ? 'activo' : 'inactivo', p.activo ? 'ok' : '')));
        var acc = el('td', { class: 'acc' });
        acc.appendChild(el('button', { type: 'button', class: 'fs-btn fs-btn-mini', text: p.activo ? 'Desactivar' : 'Activar', on: { click: async function () {
          try { await pedirJson(B + 'padron/' + p.id + '/activo', { json: { activo: !p.activo } }); cargarPadron(); }
          catch (e) { toast(textoError(e)); }
        } } }));
        tr.appendChild(acc);
        tb.appendChild(tr);
      });
    } catch (e) { vaciar(tb); $('padron-cuenta').textContent = textoError(e); }
  }
  document.querySelector('#form-padron-q').addEventListener('input', function () { clearTimeout(tPad); tPad = setTimeout(cargarPadron, 300); });
  document.querySelector('#form-padron-q').addEventListener('submit', function (e) { e.preventDefault(); cargarPadron(); });

  $('form-padron').addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var f = ev.target, b = f.querySelector('button'); enviando(b, true);
    try {
      await pedirJson(B + 'padron', { json: formDatos(f) });
      f.reset(); mostrar($('padron-msg'), 'Agregado al padrón.', false); cargarPadron();
    } catch (e) { mostrar($('padron-msg'), textoError(e), true); }
    enviando(b, false);
  });

  var csvForm = $('form-csv');
  csvForm.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var archivo = $('csv-archivo').files[0]; if (!archivo) return;
    var b = csvForm.querySelector('button'); enviando(b, true); mostrar($('csv-msg'), '');
    var fd = new FormData(); fd.append('archivo', archivo);
    try {
      var d = await pedirJson(B + 'padron/csv', { form: fd });
      var errores = Array.isArray(d.errores) ? d.errores : [];
      var validas = Number(d.filas || 0);
      $('csv-ensayo').hidden = false;
      $('csv-resumen').textContent = 'Ensayo: ' + miles(validas) + (validas === 1 ? ' fila se carga' : ' filas se cargan') + ' (' + miles(d.nuevos || 0) + ' nuevas, ' + miles(d.actualizados || 0) + ' ya estaban y se actualizan)' + (errores.length ? ' y ' + errores.length + (errores.length === 1 ? ' tiene error (se deja afuera).' : ' tienen error (se dejan afuera).') : '.');
      var tb = $('csv-errores'); vaciar(tb);
      errores.forEach(function (x) {
        var tr = el('tr');
        tr.appendChild(celda('Línea', String(x.linea != null ? x.linea : x.fila || ''), 'num'));
        tr.appendChild(celda('Problema', x.motivo || x.error || x.mensaje || x.detail || ''));
        tb.appendChild(tr);
      });
      $('csv-errores-caja').hidden = !errores.length;
      $('btn-csv-confirmar').disabled = !validas;
    } catch (e) { $('csv-ensayo').hidden = true; mostrar($('csv-msg'), textoError(e), true); }
    enviando(b, false);
  });
  $('btn-csv-confirmar').addEventListener('click', async function () {
    var archivo = $('csv-archivo').files[0]; if (!archivo) return;
    var b = this; enviando(b, true);
    var fd = new FormData(); fd.append('archivo', archivo); fd.append('confirmar', '1');
    try {
      var d = await pedirJson(B + 'padron/csv', { form: fd });
      var n = Number(d.filas || 0);
      $('csv-ensayo').hidden = true; csvForm.reset();
      mostrar($('csv-msg'), 'Listo: se cargaron ' + miles(n) + ' filas al padrón.', false);
      cargarPadron();
    } catch (e) { mostrar($('csv-msg'), textoError(e), true); enviando(b, false); }
  });
  $('csv-archivo').addEventListener('change', function () { $('csv-ensayo').hidden = true; });

  // ---------- CORTESÍAS ----------
  var leyendaDefault = 'Invitado Especial';
  async function cargarLeyendaCortesia() {
    try {
      var d = await pedirJson(B + 'configuracion'), ev = d.evento || d;
      if (ev.leyenda_cortesia) leyendaDefault = ev.leyenda_cortesia;
    } catch (_) {}
    $('cortesia-leyenda').placeholder = leyendaDefault;
  }
  var cUrl = '';
  $('form-cortesia').addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var f = ev.target, b = f.querySelector('button'), d = formDatos(f);
    d.cantidad = Number(d.cantidad);
    if (!d.leyenda) d.leyenda = leyendaDefault;
    if (!d.mail) delete d.mail;
    enviando(b, true); mostrar($('cortesia-error'), ''); $('cortesia-ok').hidden = true;
    try {
      var r = await pedirJson(B + 'cortesia', { json: d });
      cUrl = new URL(r.url_entrada, location.origin).href;
      $('cortesia-url').value = cUrl;
      $('cortesia-texto').textContent = 'Cortesía emitida para ' + d.nombre + ' (' + d.cantidad + (d.cantidad === 1 ? ' persona' : ' personas') + ').' + (r.mail_enviado ? ' Se le mandó el enlace por mail.' : ' Copiá el enlace y mandáselo.');
      $('btn-compartir').hidden = !navigator.share;
      $('cortesia-ok').hidden = false;
      f.reset();
    } catch (e) { mostrar($('cortesia-error'), textoError(e), true); }
    enviando(b, false);
  });
  $('btn-copiar').addEventListener('click', async function () {
    try { await navigator.clipboard.writeText(cUrl); toast('Enlace copiado'); }
    catch (_) { $('cortesia-url').select(); toast('Seleccionado: copialo con el menú'); }
  });
  $('btn-compartir').addEventListener('click', function () {
    if (navigator.share) navigator.share({ title: 'Tu entrada', url: cUrl }).catch(function () {});
  });

  // ---------- CONFIGURACIÓN ----------
  var eventoId = null;
  var CAMPOS_CFG = ['nombre', 'fecha_hora', 'lugar', 'direccion', 'precio', 'tope_por_afiliado', 'tope_general', 'horas_antes', 'minutos_vencimiento', 'leyenda_cortesia', 'leyenda_ticket'];
  async function cargarConfig() {
    pintarMp();
    try {
      var d = await pedirJson(B + 'configuracion'), ev = d.evento || d, f = $('form-config');
      eventoId = ev.id;
      CAMPOS_CFG.forEach(function (c) {
        if (!f[c]) return;
        var v = ev[c] == null ? '' : ev[c];
        f[c].value = c === 'fecha_hora' ? String(v).slice(0, 16) : v;
      });
      pintarFoto(!!ev.foto);
      if (d.mp_modo) { MP_MODO = d.mp_modo; MP_FALTAN = d.mp_faltantes || []; pintarMp(); }
    } catch (e) { mostrar($('config-msg'), textoError(e), true); }
  }
  $('form-config').addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var f = ev.target, b = f.querySelector('button'), d = formDatos(f);
    ['precio', 'tope_por_afiliado', 'tope_general', 'horas_antes', 'minutos_vencimiento'].forEach(function (k) { d[k] = Number(d[k]); });
    enviando(b, true);
    try { await pedirJson(B + 'configuracion', { json: d }); mostrar($('config-msg'), 'Guardado.', false); }
    catch (e) { mostrar($('config-msg'), textoError(e), true); }
    enviando(b, false);
  });
  function pintarFoto(hay) {
    var v = $('foto-vista');
    v.style.backgroundImage = hay && eventoId ? 'url("/fiesta/foto/' + eventoId + '?v=' + Date.now() + '")' : '';
    v.classList.toggle('con-foto', !!hay);
    $('foto-vacia').hidden = !!hay;
    $('btn-foto-quitar').hidden = !hay;
  }
  $('foto-archivo').addEventListener('change', async function () {
    var a = this.files[0]; if (!a) return;
    var fd = new FormData(); fd.append('archivo', a);
    mostrar($('foto-msg'), 'Subiendo…', false);
    try { await pedirJson(B + 'foto', { form: fd }); pintarFoto(true); mostrar($('foto-msg'), 'Foto guardada.', false); }
    catch (e) { mostrar($('foto-msg'), textoError(e), true); }
    this.value = '';
  });
  $('btn-foto-quitar').addEventListener('click', async function () {
    try { var fq = new FormData(); fq.append('quitar', '1'); await pedirJson(B + 'foto', { form: fq }); pintarFoto(false); mostrar($('foto-msg'), 'Foto quitada.', false); }
    catch (e) { mostrar($('foto-msg'), textoError(e), true); }
  });
  var MP_FALTAN = [];
  function pintarMp() {
    var m = MP_MODO, p = $('mp-pildora'), t = $('mp-texto');
    p.className = 'fs-pildora ' + (m === 'real' ? 'ok' : (m === 'mock' ? 'aviso' : 'mal'));
    p.textContent = m === 'real' ? 'Cobro real activo' : (m === 'mock' ? 'Modo simulado' : 'Cobro apagado');
    t.textContent = m === 'real'
      ? 'MercadoPago está configurado: los pagos van directo a la cuenta del sindicato. El sindicato no maneja la plata.'
      : (m === 'mock'
        ? 'Está activo MP_MOCK=1: los pagos se aprueban a mano en una página de prueba y no se cobra nada. Para cobrar de verdad hay que cargar MP_ACCESS_TOKEN y MP_WEBHOOK_SECRET en el entorno y sacar MP_MOCK.'
        : 'Faltan las variables ' + (MP_FALTAN.length ? MP_FALTAN.join(' y ') : 'MP_ACCESS_TOKEN y MP_WEBHOOK_SECRET') + ' (o MP_MOCK=1 para probar). Mientras tanto nadie puede reservar. Se cargan en el entorno, no desde esta pantalla.');
  }

  // Operadores
  async function cargarOperadores() {
    var tb = document.querySelector('#tabla-ops tbody');
    try {
      var filas = lista(await pedirJson(B + 'operadores'), 'operadores');
      vaciar(tb);
      filas.forEach(function (o) {
        var tr = el('tr');
        tr.appendChild(celda('Usuario', o.usuario));
        tr.appendChild(celda('Nombre', o.nombre));
        tr.appendChild(celda('Rol', o.rol === 'admin' ? 'Administración' : 'Puerta'));
        tr.appendChild(celda('Estado', pildora(o.activo ? 'activo' : 'inactivo', o.activo ? 'ok' : '')));
        var acc = el('td', { class: 'acc' });
        acc.appendChild(el('button', { type: 'button', class: 'fs-btn fs-btn-mini', text: o.activo ? 'Desactivar' : 'Activar', on: { click: async function () {
          try { await pedirJson(B + 'operador/' + o.id + '/activo', { json: { activo: !o.activo } }); cargarOperadores(); }
          catch (e) { mostrar($('op-msg'), textoError(e), true); }
        } } }));
        acc.appendChild(el('button', { type: 'button', class: 'fs-btn fs-btn-mini', text: 'Restablecer clave', on: { click: async function () {
          if (!confirm('¿Restablecer la clave de ' + o.nombre + '? Se muestra una sola vez.')) return;
          try {
            var r = await pedirJson(B + 'operador/' + o.id + '/restablecer', { method: 'POST' });
            var clave = r.clave || r.clave_transitoria || r.transitoria || '';
            mostrar($('op-msg'), 'Clave transitoria de ' + o.nombre + ': ' + clave + ' — anotala ahora, no se vuelve a mostrar. En su próximo ingreso elige una propia.', false);
          } catch (e) { mostrar($('op-msg'), textoError(e), true); }
        } } }));
        tr.appendChild(acc);
        tb.appendChild(tr);
      });
    } catch (e) { vaciar(tb); mostrar($('op-msg'), textoError(e), true); }
  }
  $('form-op').addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var f = ev.target, b = f.querySelector('button'); enviando(b, true);
    try { await pedirJson(B + 'operador', { json: formDatos(f) }); f.reset(); mostrar($('op-msg'), 'Operador agregado.', false); cargarOperadores(); }
    catch (e) { mostrar($('op-msg'), textoError(e), true); }
    enviando(b, false);
  });
})();
