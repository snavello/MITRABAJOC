/* App del afiliado de la Fiesta (PLAN_FIESTA.md, «La app del afiliado»).
   Una sola página: ingreso -> inicio (evento, tus entradas, reservar) -> pago
   (polling a /api/fiesta/reserva/{id}) -> el ticket en /fiesta/entrada/{id}.
   Los textos de personas siempre con textContent, nunca como HTML. */
(function () {
  'use strict';
  var app = document.getElementById('app');
  if (!app || app.dataset.hayEvento !== '1') return;

  var N = window.NumAR || { miles: function (v) { return String(v); } };
  var $ = function (id) { return document.getElementById(id); };
  var estado = null;            // la última respuesta de /api/fiesta/estado
  var cantidad = 1;
  var initPoints = {};          // reserva_id -> init_point (si el estado no lo trae)
  var pollTimer = null;
  var ocupado = false;

  function pesos(n) { return '$ ' + N.miles(n); }

  // ---------- Red ----------
  // Todo pasa por acá. Un 502/503/504 de Render trae HTML: nunca se muestra
  // «Unexpected token '<'», se dice que el servidor no respondió.
  function errorDe(mensaje, codigo, status) {
    var e = new Error(mensaje);
    e.codigo = codigo || '';
    e.status = status || 0;
    return e;
  }
  async function pedirJson(url, opciones) {
    var r;
    try {
      r = await fetch(url, opciones);
    } catch (_) {
      throw errorDe('No pudimos comunicarnos con el servidor. Revisá tu conexión y probá de nuevo en un minuto.', '', 0);
    }
    var cuerpo = null, hayJson = true;
    try { cuerpo = await r.json(); } catch (_) { hayJson = false; }
    if (!r.ok) {
      if (hayJson && cuerpo && typeof cuerpo.detail === 'string') {
        throw errorDe(cuerpo.detail, (cuerpo.codigo || '') + (cuerpo.ref ? ' · ref ' + cuerpo.ref : ''), r.status);
      }
      if (r.status >= 500 || !hayJson) throw errorDe('El servidor no respondió. Probá de nuevo en un minuto.', 'HTTP ' + r.status, r.status);
      throw errorDe('No se pudo completar la operación. Probá de nuevo en un minuto.', 'HTTP ' + r.status, r.status);
    }
    if (!hayJson) throw errorDe('El servidor no respondió. Probá de nuevo en un minuto.', 'HTTP ' + r.status, r.status);
    return cuerpo;
  }
  function postJson(url, datos) {
    return pedirJson(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                            body: JSON.stringify(datos || {}) });
  }
  function mostrarError(caja, err) {
    caja.querySelector('.msg').textContent = err && err.message ? err.message : 'No se pudo completar la operación.';
    var cod = caja.querySelector('.f-cod');
    cod.textContent = err && err.codigo ? 'Código ' + err.codigo : '';
    cod.classList.toggle('f-oculto', !(err && err.codigo));
    caja.classList.remove('f-oculto');
  }
  function limpiarError(caja) { caja.classList.add('f-oculto'); }

  // ---------- Fechas (texto ISO local, sin zona: no pasan por Date UTC) ----------
  function fechaLarga(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || '');
    if (!m) return '';
    var d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    var t = d.toLocaleDateString('es-AR', { weekday: 'long', day: 'numeric', month: 'long' });
    return t + ', ' + m[4] + ':' + m[5];
  }
  // `vence` es hora de Buenos Aires (UTC-3, sin horario de verano).
  function aMs(iso) {
    if (!iso) return NaN;
    return Date.parse(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso.replace(' ', 'T') + '-03:00');
  }
  function mmss(ms) {
    var t = Math.max(0, Math.round(ms / 1000));
    var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    var dos = function (x) { return String(x).padStart(2, '0'); };
    return (h ? h + ':' + dos(m) : m) + ':' + dos(s);
  }
  function el(tag, clase, texto) {
    var e = document.createElement(tag);
    if (clase) e.className = clase;
    if (texto != null) e.textContent = texto;
    return e;
  }

  // ---------- Vistas ----------
  function ver(id) {
    ['v-ingreso', 'v-inicio'].forEach(function (v) { $(v).classList.toggle('f-oculto', v !== id); });
    $('btn-salir').classList.toggle('f-oculto', id !== 'v-inicio');
    window.scrollTo(0, 0);
  }

  // ---------- Ingreso ----------
  $('form-ingreso').addEventListener('submit', async function (ev) {
    ev.preventDefault();
    var caja = $('err-ingreso'), btn = $('btn-entrar');
    limpiarError(caja);
    var legajo = $('in-legajo').value.trim(), dni = $('in-dni').value.replace(/\D/g, '');
    if (!legajo || !dni) {
      mostrarError(caja, errorDe('Completá tu legajo y tu DNI.', ''));
      return;
    }
    btn.disabled = true;
    try {
      await postJson('/api/fiesta/entrar', { legajo: legajo, dni: dni });
      $('in-dni').value = '';
      await cargarEstado();
    } catch (e) {
      mostrarError(caja, e);
    } finally { btn.disabled = false; }
  });
  $('btn-salir').addEventListener('click', async function () {
    try { await postJson('/api/fiesta/salir', {}); } catch (_) { /* igual se vuelve al ingreso */ }
    estado = null; detener();
    history.replaceState(null, '', location.pathname);
    ver('v-ingreso');
  });

  // ---------- Estado ----------
  async function cargarEstado() {
    try {
      estado = await pedirJson('/api/fiesta/estado', { headers: { 'Accept': 'application/json' } });
    } catch (e) {
      if (e.status === 401) { estado = null; ver('v-ingreso'); return null; }
      if (!$('v-inicio').classList.contains('f-oculto')) { mostrarError($('err-reservar'), e); return null; }
      mostrarError($('err-ingreso'), e); return null;
    }
    pintar();
    ver('v-inicio');
    arrancarPagoDelHash();
    return estado;
  }

  function pintar() {
    var ev = estado.evento || {};
    $('ev-nombre').textContent = ev.nombre || '';
    $('ev-fecha').textContent = fechaLarga(ev.fecha_hora);
    $('ev-lugar').textContent = ev.lugar || '';
    $('ev-dir').textContent = ev.direccion || '';
    var mapa = $('ev-mapa');
    if (ev.url_mapa) { mapa.href = ev.url_mapa; mapa.hidden = false; } else mapa.hidden = true;
    $('ev-dir-caja').hidden = !(ev.direccion || ev.url_mapa);
    var af = estado.afiliado || {};
    $('ev-saludo').textContent = af.nombre ? 'Hola, ' + af.nombre + (af.legajo ? ' · legajo ' + af.legajo : '') : '';
    var q = $('ev-quedan'), generales = estado.disponibles_generales;
    if (generales > 0 && generales <= 50) {
      q.querySelector('.f-pildora').textContent = 'Quedan ' + N.miles(generales) + (generales === 1 ? ' entrada' : ' entradas');
      q.classList.remove('f-oculto');
    } else q.classList.add('f-oculto');
    pintarReservas();
    pintarReservar();
  }

  var RANGO = { pendiente: 0, pagada: 1, vencida: 2, anulada: 3 };
  function pintarReservas() {
    var lista = $('lista-reservas');
    lista.textContent = '';
    var rs = (estado.reservas || []).slice().sort(function (a, b) {
      return (RANGO[a.estado] - RANGO[b.estado]) || (b.id - a.id);
    });
    $('sin-reservas').classList.toggle('f-oculto', rs.length > 0);
    rs.forEach(function (r) {
      var ip = r.init_point || r.url_pago;
      if (ip) initPoints[r.id] = ip;
      if (r.estado === 'pendiente' && typeof r.vence_en === 'number') r._venceMs = Date.now() + r.vence_en * 1000;
      lista.appendChild(tarjetaReserva(r));
    });
  }

  var ROTULO = { pendiente: ['aviso', 'Pendiente de pago'], pagada: ['ok', 'Pagada'], vencida: ['tenue', 'Vencida'], anulada: ['tenue', 'Anulada'] };
  function tarjetaReserva(r) {
    var c = el('div', 'fa-res ' + r.estado);
    c.id = 'res-' + r.id;
    var cab = el('div', 'fa-res-cab');
    var izq = el('div');
    izq.appendChild(el('div', 'fa-res-cant', r.cantidad + (r.cantidad === 1 ? ' persona' : ' personas')));
    if (r.estado === 'pendiente') izq.appendChild(el('div', 'fa-res-imp', pesos(r.importe)));
    cab.appendChild(izq);
    var rot = ROTULO[r.estado] || ['tenue', r.estado];
    cab.appendChild(el('span', 'f-pildora ' + rot[0], rot[1]));
    c.appendChild(cab);

    if (r.estado === 'pendiente') {
      var cu = el('div', 'fa-cuenta');
      cu.dataset.venceMs = String(r._venceMs || aMs(r.vence));
      cu.textContent = ' ';
      c.appendChild(cu);
      var pie = el('div', 'fa-res-pie');
      var pagar = el('button', 'f-btn', 'Pagar ahora');
      pagar.type = 'button';
      pagar.addEventListener('click', function () { pagarAhora(r.id, pagar); });
      pie.appendChild(pagar);
      var anu = el('button', 'fa-link', 'Anular reserva');
      anu.type = 'button';
      anu.addEventListener('click', function () { anular(r.id, anu); });
      pie.appendChild(anu);
      c.appendChild(pie);
    } else if (r.estado === 'pagada') {
      if (r.ingresados > 0) {
        c.appendChild(el('div', 'f-suave', 'Ingresaron ' + r.ingresados + ' de ' + r.cantidad + '.'));
      } else if (!r.entrada_habilitada && r.entrada_desde) {
        var hs = Number(r.horas_antes != null ? r.horas_antes : (estado.evento || {}).horas_antes) || 0;
        c.appendChild(el('div', 'f-suave', 'El QR para el ingreso va a aparecer al menos ' + hs + (hs === 1 ? ' hora' : ' horas') + ' antes del evento.'));
      }
      var pie2 = el('div', 'fa-res-pie');
      var enlace = el("a", "f-btn" + (r.entrada_habilitada ? "" : " f-sec"), "Ver tu entrada");
      enlace.href = r.url_entrada || ('/fiesta/entrada/' + r.id);
      pie2.appendChild(enlace);
      c.appendChild(pie2);
    }
    return c;
  }

  // Cuenta regresiva de las pendientes
  setInterval(function () {
    var algunaVencio = false;
    document.querySelectorAll('.fa-cuenta').forEach(function (n) {
      var ms = Number(n.dataset.venceMs) - Date.now();
      if (isNaN(ms)) { n.textContent = ''; return; }
      if (ms <= 0) { n.textContent = 'La reserva venció'; algunaVencio = true; return; }
      n.textContent = 'Tenés ' + mmss(ms) + ' para pagar';
    });
    if (algunaVencio && !ocupado) { ocupado = true; cargarEstado().finally(function () { ocupado = false; }); }
  }, 1000);

  async function pagarAhora(id, btn) {
    btn.disabled = true;
    try {
      var url = initPoints[id];
      if (!url) {
        var d = await pedirJson('/api/fiesta/reserva/' + id, { headers: { 'Accept': 'application/json' } });
        url = d.init_point || d.url_pago;
        if (d.estado && d.estado !== 'pendiente') { await cargarEstado(); return; }
      }
      if (!url) throw errorDe('No pudimos abrir el pago. Probá de nuevo en un momento.', '');
      location.href = url;
    } catch (e) {
      mostrarError($('err-reservar'), e);
      btn.disabled = false;
    }
  }
  async function anular(id, btn) {
    if (!btn.dataset.seguro) {
      btn.dataset.seguro = '1';
      btn.textContent = 'Confirmá: anular reserva';
      setTimeout(function () { if (btn.isConnected) { delete btn.dataset.seguro; btn.textContent = 'Anular reserva'; } }, 5000);
      return;
    }
    btn.disabled = true;
    try {
      await postJson('/api/fiesta/reserva/' + id + '/anular', {});
      await cargarEstado();
    } catch (e) { mostrarError($('err-reservar'), e); btn.disabled = false; }
  }

  // ---------- Reservar ----------
  function maximo() {
    return Math.max(0, Math.min(estado.disponibles_mias || 0, estado.disponibles_generales || 0));
  }
  function pintarReservar() {
    var max = maximo(), ag = $('reservar-agotado');
    $('reservar-activo').classList.toggle('f-oculto', max <= 0);
    ag.classList.toggle('f-oculto', max > 0);
    if (max <= 0) {
      var tope = (estado.evento || {}).tope_por_afiliado;
      ag.textContent = (estado.disponibles_generales || 0) <= 0
        ? 'Se agotaron las entradas. Si alguna reserva sin pagar vence, vuelven a estar disponibles.'
        : 'Ya reservaste el máximo de ' + tope + (tope === 1 ? ' entrada' : ' entradas') + ' por afiliado.';
      return;
    }
    if (cantidad > max) cantidad = max;
    if (cantidad < 1) cantidad = 1;
    refrescarCantidad();
    var apagado = app.dataset.mpModo === 'apagado' || estado.mp_modo === 'apagado';
    if (apagado) {
      mostrarError($('err-reservar'), errorDe('El cobro no está configurado todavía. Consultá con el sindicato.', 'E-FIESTA-05'));
      $('btn-reservar').disabled = true;
    }
  }
  function refrescarCantidad() {
    var max = maximo(), precio = (estado.evento || {}).precio || 0;
    $('cant').textContent = String(cantidad);
    $('cant-rot').textContent = cantidad + (cantidad === 1 ? ' persona' : ' personas');
    $('total').textContent = pesos(precio * cantidad);
    $('btn-reservar').textContent = 'Reservar y pagar ' + pesos(precio * cantidad);
    $('menos').disabled = cantidad <= 1;
    $('mas').disabled = cantidad >= max;
  }
  $('menos').addEventListener('click', function () { cantidad = Math.max(1, cantidad - 1); refrescarCantidad(); });
  $('mas').addEventListener('click', function () { cantidad = Math.min(maximo(), cantidad + 1); refrescarCantidad(); });
  $('btn-reservar').addEventListener('click', async function () {
    var btn = $('btn-reservar'), caja = $('err-reservar');
    limpiarError(caja);
    btn.disabled = true;
    btn.classList.add('cargando');
    try {
      var d = await postJson('/api/fiesta/reservar', { cantidad: cantidad });
      if (!d.init_point) throw errorDe('No pudimos abrir el pago. Probá de nuevo en un momento.', '');
      initPoints[d.reserva_id] = d.init_point;
      location.href = d.init_point;
    } catch (e) {
      mostrarError(caja, e);
      btn.disabled = false;
      btn.classList.remove('cargando');
      cargarEstado();       // el cupo pudo cambiar mientras se decidía
    }
  });

  // ---------- Pago: polling ----------
  function detener() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }
  function idDelHash() {
    var m = /^#reserva-(\d+)$/.exec(location.hash);
    return m ? +m[1] : null;
  }
  function arrancarPagoDelHash() {
    var id = idDelHash();
    if (!id || pollTimer) return;
    var bloque = $('bloque-pago');
    bloque.classList.remove('f-oculto', 'celebra');
    mostrarPago('espera');
    bloque.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var desde = Date.now();
    (async function ciclo() {
      var fila = null;
      try { fila = await pedirJson('/api/fiesta/reserva/' + id, { headers: { 'Accept': 'application/json' } }); }
      catch (e) { if (e.status === 401) { detener(); ver('v-ingreso'); return; } }
      if (fila) {
        if (fila.init_point || fila.url_pago) initPoints[id] = fila.init_point || fila.url_pago;
        if (fila.estado === 'pagada') return pagoListo(fila);
        if (fila.estado === 'vencida' || fila.estado === 'anulada') return pagoTerminado(fila);
      }
      if (Date.now() - desde >= 120000) return pagoSigue(fila || { id: id, estado: 'pendiente' });
      pollTimer = setTimeout(ciclo, 3000);
    })();
    pollTimer = pollTimer || true;
  }
  function mostrarPago(cual) {
    ['espera', 'ok', 'sigue'].forEach(function (k) { $('pago-' + k).classList.toggle('f-oculto', k !== cual); });
  }
  function soltarHash() { pollTimer = null; history.replaceState(null, '', location.pathname); }
  async function pagoListo(fila) {
    soltarHash();
    mostrarPago('ok');
    $('pago-ok-txt').textContent = fila.cantidad + (fila.cantidad === 1 ? ' entrada' : ' entradas') + ' para ' +
      fila.cantidad + (fila.cantidad === 1 ? ' persona' : ' personas') + '. Ya está en tu cuenta.';
    $('pago-ok-ver').href = fila.url_entrada || ('/fiesta/entrada/' + fila.id);
    var b = $('bloque-pago');
    void b.offsetWidth;
    b.classList.add('celebra');
    await cargarEstadoSinHash();
  }
  function pagoSigue(fila) {
    soltarHash();
    mostrarPago('sigue');
    var btn = $('pago-sigue-pagar');
    btn.classList.remove('f-oculto');
    btn.onclick = function () { pagarAhora(fila.id, btn); };
    if (fila.mp_estado === 'rejected' || fila.mp_estado === 'cancelled') {
      $('pago-sigue-txt').textContent = 'MercadoPago rechazó el pago. Podés intentarlo de nuevo con otro medio mientras la reserva siga vigente.';
    }
  }
  function pagoTerminado(fila) {
    soltarHash();
    mostrarPago('sigue');
    $('pago-sigue-pagar').classList.add('f-oculto');
    $('pago-sigue-txt').textContent = fila.estado === 'vencida'
      ? 'La reserva venció antes de recibir el pago. Si pagaste, avisale al sindicato; si no, podés reservar de nuevo.'
      : 'La reserva fue anulada. Podés reservar de nuevo cuando quieras.';
    cargarEstadoSinHash();
  }
  async function cargarEstadoSinHash() {
    try { estado = await pedirJson('/api/fiesta/estado', { headers: { 'Accept': 'application/json' } }); pintar(); } catch (_) { /* queda lo anterior */ }
  }

  window.addEventListener('hashchange', function () { if (estado) arrancarPagoDelHash(); });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && estado && !pollTimer) cargarEstadoSinHash();
  });

  // ---------- Arranque ----------
  var heroFecha = $('hero-fecha');
  if (heroFecha && heroFecha.dataset.fecha) heroFecha.textContent = fechaLarga(heroFecha.dataset.fecha) || heroFecha.textContent;
  if (app.dataset.sesion === '1') cargarEstado();
})();
