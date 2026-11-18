/* Curar las preguntas frecuentes del convenio (Herramientas de /entornos,
   PLAN_CONVENIO_ESCALAS.md D41). La usa gente que no es técnica: hoy el equipo de
   Colm3na, después el sindicato. Todo lo que viene de la base o de lo que escribe una
   persona se dibuja con textContent / nodos: nunca como HTML armado a mano. */
(function () {
  'use strict';
  var API = '/api/entornos/herramientas/escalas';
  var CURADO = API + '/curado';
  var MAX = { id: 60, pregunta: 300, en_corto: 1500, respuesta: 4000, segun_ley: 4000, por_banco: 4000, nota_curador: 2000, detalle: 2000, motivo: 300 };
  var RESERVADAS = { articulos: 1, reordenar: 1, estado: 1, nueva: 1 };
  var CAMPOS = { id: 'Nombre corto', tema: 'Tema', pregunta: 'Pregunta', en_corto: 'Respuesta directa', respuesta: 'Qué dice el convenio',
                 articulos: 'Artículos', segun_ley: 'Según la ley', normas: 'Normas', por_banco: 'En tu banco', fuentes_banco: 'Fuentes',
                 nota_curador: 'Nota para quien cura', motivo: 'Motivo', detalle: 'Detalle', estado: 'Estado', orden: 'Orden', inspirada_en: 'Inspirada en' };
  var ESTADOS = { sin_revisar: 'Sin revisar', revisada: 'Revisada', retirada: 'Retirada' };
  var CONTENIDO = ['tema', 'pregunta', 'en_corto', 'respuesta', 'articulos', 'segun_ley', 'normas', 'por_banco', 'fuentes_banco', 'nota_curador'];

  var est = { temas: [], conteos: {}, preguntas: [], articulos: [], porNumero: {}, filtroEstado: 'sin_revisar', filtroTema: '', q: '', ed: null, ocupado: false };

  // ---------------------------------------------------------------- DOM
  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') el.className = attrs[k];
      else if (k === 'text') el.textContent = attrs[k];
      else if (k.indexOf('on') === 0) el.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== false && attrs[k] != null) el.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      if (Array.isArray(c)) { c.forEach(function (x) { if (x) el.appendChild(x); }); continue; }
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return el;
  }
  function $(id) { return document.getElementById(id); }
  function vaciar(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function norm(t) { return String(t == null ? '' : t).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function cuando(t) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(t || ''));
    return m ? m[3] + '/' + m[2] + '/' + m[1] + ' ' + m[4] + ':' + m[5] : '';
  }
  function renglones(t) { return String(t || '').split('\n').map(function (r) { return r.trim(); }).filter(Boolean); }
  function urlHttps(u) { return typeof u === 'string' && u.indexOf('https://') === 0; }

  // ---------------------------------------------------------------- pedidos
  function pedir(url, cuerpo) {
    var init = { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' };
    if (cuerpo !== undefined) {
      init.method = 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(cuerpo);
    }
    return fetch(url, init).then(function (r) {
      return r.text().then(function (t) {
        var d = null;
        try { d = t ? JSON.parse(t) : null; } catch (e) { d = null; }
        if (!r.ok) {
          var msg = d && d.detail ? (typeof d.detail === 'string' ? d.detail : 'El pedido no es válido.') : ('El servidor respondió ' + r.status + '.');
          var err = new Error(msg);
          err.status = r.status;
          err.errores = d && Array.isArray(d.errores) ? d.errores : null;
          throw err;
        }
        return d;
      });
    }, function () {
      var err = new Error('No se pudo conectar con el servidor. Revisá tu conexión y probá de nuevo.');
      err.red = true;
      throw err;
    });
  }
  function aviso(texto, clase, extra) {
    var a = $('aviso');
    vaciar(a);
    a.className = 'aviso' + (clase ? ' ' + clase : '');
    if (texto) a.appendChild(document.createTextNode(texto));
    if (extra) { a.appendChild(document.createTextNode(' ')); a.appendChild(extra); }
    a.hidden = !texto;
  }

  // ---------------------------------------------------------------- datos
  function ordenTema(clave) {
    for (var i = 0; i < est.temas.length; i++) if (est.temas[i].clave === clave) return i;
    return 999;
  }
  function nombreTema(clave) {
    for (var i = 0; i < est.temas.length; i++) if (est.temas[i].clave === clave) return est.temas[i].nombre;
    return clave || 'Sin tema';
  }
  function ordenar() {
    est.preguntas.sort(function (a, b) {
      return (ordenTema(a.tema) - ordenTema(b.tema)) || (a.orden - b.orden) || (a.id < b.id ? -1 : 1);
    });
  }
  function contar() {
    var c = { sin_revisar: 0, revisada: 0, retirada: 0, total: est.preguntas.length };
    est.preguntas.forEach(function (p) { if (c[p.estado] != null) c[p.estado]++; });
    est.conteos = c;
  }
  function pregunta(clave) {
    for (var i = 0; i < est.preguntas.length; i++) if (est.preguntas[i].id === clave) return est.preguntas[i];
    return null;
  }
  function guardarLocal(p) {
    var hay = false;
    for (var i = 0; i < est.preguntas.length; i++) if (est.preguntas[i].id === p.id) { est.preguntas[i] = p; hay = true; }
    if (!hay) est.preguntas.push(p);
    ordenar(); contar();
  }
  function cargar() {
    var lista = vaciar($('lista'));
    lista.appendChild(h('p', { class: 'vacio', text: 'Cargando las preguntas…' }));
    return Promise.all([pedir(CURADO), pedir(CURADO + '/articulos')]).then(function (r) {
      est.temas = r[0].temas || [];
      est.preguntas = r[0].preguntas || [];
      est.articulos = r[1] || [];
      est.porNumero = {};
      est.articulos.forEach(function (a) { est.porNumero[String(a.numero)] = a.titulo; });
      aviso('');
      ordenar(); contar();
      llenarTemas();
      pintarTodo();
    }).catch(function (e) {
      vaciar(lista);
      lista.appendChild(h('p', { class: 'vacio', text: 'No se pudieron cargar las preguntas.' }));
      vaciar($('resumen'));
      aviso('No se pudieron cargar las preguntas. ' + e.message, 'rojo',
        h('button', { class: 'boton claro chico', type: 'button', text: 'Reintentar', onclick: cargar }));
    });
  }

  // ---------------------------------------------------------------- resumen
  function pintarResumen() {
    var c = est.conteos, r = vaciar($('resumen'));
    var pub = c.sin_revisar + c.revisada;
    var pct = pub ? Math.round(c.revisada * 100 / pub) : 0;
    r.appendChild(h('div', { class: 'tres' },
      h('div', { class: 'dato' + (c.sin_revisar ? ' atencion' : ' ok') }, h('div', { class: 'rotulo', text: 'Sin revisar' }), h('div', { class: 'grande num', text: String(c.sin_revisar) }),
        h('p', { text: 'Esperan que alguien las lea y las dé por buenas.' })),
      h('div', { class: 'dato ok' }, h('div', { class: 'rotulo', text: 'Revisadas' }), h('div', { class: 'grande num', text: String(c.revisada) }),
        h('p', { text: 'Ya las leyó una persona del equipo.' })),
      h('div', { class: 'dato' }, h('div', { class: 'rotulo', text: 'Retiradas' }), h('div', { class: 'grande num', text: String(c.retirada) }),
        h('p', { text: 'No se muestran hasta que se completen y se publiquen.' }))));
    var barra = h('div', { class: 'barra-av', role: 'img', 'aria-label': 'Revisaste ' + c.revisada + ' de ' + pub + ' preguntas publicadas' },
      h('i', { style: 'width:' + pct + '%' }));
    r.appendChild(h('div', { class: 'avance' }, barra,
      h('p', {}, h('strong', { text: 'Revisaste ' + c.revisada + ' de ' + pub + ' preguntas' }), ' (' + pct + ' %).')));
    r.appendChild(h('p', { class: 've-afiliado' }, 'Hoy el afiliado ve las ', h('strong', { text: String(pub) }), ' publicadas',
      c.sin_revisar ? ' (las que siguen sin revisar llevan la marca «sin revisar»)' : '', '; las ', h('strong', { text: String(c.retirada) }), ' retiradas no se muestran.'));
  }

  // ---------------------------------------------------------------- filtros y lista
  function llenarTemas() {
    var s = $('f-tema');
    vaciar(s);
    s.appendChild(h('option', { value: '', text: 'Todos los temas' }));
    est.temas.forEach(function (t) { s.appendChild(h('option', { value: t.clave, text: t.nombre })); });
    s.value = est.filtroTema;
  }
  function pintarPastillas() {
    var c = est.conteos, cont = vaciar($('pastillas'));
    [['sin_revisar', 'Sin revisar', c.sin_revisar], ['revisada', 'Revisadas', c.revisada], ['retirada', 'Retiradas', c.retirada], ['', 'Todas', c.total]].forEach(function (x) {
      cont.appendChild(h('button', { type: 'button', class: 'pastilla', 'aria-pressed': est.filtroEstado === x[0] ? 'true' : 'false',
        onclick: function () { est.filtroEstado = x[0]; pintarLista(); pintarPastillas(); } },
        x[1], h('span', { class: 'n', text: String(x[2] == null ? 0 : x[2]) })));
    });
  }
  function visibles() {
    var q = norm(est.q).trim();
    return est.preguntas.filter(function (p) {
      if (est.filtroEstado && p.estado !== est.filtroEstado) return false;
      if (est.filtroTema && p.tema !== est.filtroTema) return false;
      if (q && norm([p.id, p.pregunta, p.en_corto, p.respuesta, p.segun_ley, p.por_banco].join(' ')).indexOf(q) < 0) return false;
      return true;
    });
  }
  function pintarLista() {
    var cont = vaciar($('lista')), vis = visibles();
    $('f-cuenta').textContent = vis.length === 1 ? 'Se muestra 1 pregunta.' : 'Se muestran ' + vis.length + ' preguntas.';
    if (!vis.length) {
      cont.appendChild(h('p', { class: 'vacio', text: est.preguntas.length ? 'No hay preguntas con estos filtros. Probá con «Todas» o limpiá la búsqueda.' : 'Todavía no hay preguntas cargadas.' }));
      return;
    }
    var grupos = [];
    vis.forEach(function (p) {
      var g = grupos.length ? grupos[grupos.length - 1] : null;
      if (!g || g.tema !== p.tema) { g = { tema: p.tema, items: [] }; grupos.push(g); }
      g.items.push(p);
    });
    grupos.forEach(function (g) {
      var ul = h('ul', { class: 'pregs' });
      g.items.forEach(function (p, i) { ul.appendChild(filaPregunta(p, i, g.items.length)); });
      cont.appendChild(h('section', { class: 'tema-grupo' },
        h('h3', {}, nombreTema(g.tema), h('span', { class: 'c', text: g.items.length + (g.items.length === 1 ? ' pregunta' : ' preguntas') })), ul));
    });
  }
  function filaPregunta(p, i, n) {
    var abierta = est.ed && est.ed.clave === p.id;
    var marcas = h('div', { class: 'marcas' }, h('span', { class: 'pill ' + p.estado, text: ESTADOS[p.estado] || p.estado }));
    if ((p.nota_curador || '').trim()) marcas.appendChild(h('span', { class: 'pill nota', text: 'Tiene una duda para resolver' }));
    return h('li', { class: 'preg' + (abierta ? ' abierta' : '') },
      h('button', { type: 'button', class: 'abrir', 'aria-expanded': abierta ? 'true' : 'false', 'data-clave': p.id, onclick: function () { abrir(p.id); } },
        h('span', { class: 'texto', text: p.pregunta }), marcas),
      h('div', { class: 'orden' },
        h('button', { type: 'button', 'data-mover': p.id + ':-1', 'aria-label': 'Subir «' + p.pregunta + '»', title: 'Subir', disabled: i === 0 ? '' : false, text: '▲', onclick: function () { mover(p, -1); } }),
        h('button', { type: 'button', 'data-mover': p.id + ':1', 'aria-label': 'Bajar «' + p.pregunta + '»', title: 'Bajar', disabled: i === n - 1 ? '' : false, text: '▼', onclick: function () { mover(p, 1); } })));
  }
  function pintarTodo() { pintarResumen(); pintarPastillas(); pintarLista(); }

  // ---------------------------------------------------------------- reordenar
  function mover(p, dir) {
    if (est.ocupado) return;
    var vis = visibles().filter(function (x) { return x.tema === p.tema; });
    var i = vis.map(function (x) { return x.id; }).indexOf(p.id), vecina = vis[i + dir];
    if (!vecina) return;
    var todas = est.preguntas.filter(function (x) { return x.tema === p.tema; }).map(function (x) { return x.id; });
    var a = todas.indexOf(p.id), b = todas.indexOf(vecina.id);
    todas[a] = vecina.id; todas[b] = p.id;
    est.ocupado = true;
    pedir(CURADO + '/reordenar', { tema: p.tema, claves: todas }).then(function (r) {
      (r.preguntas || []).forEach(function (x) { guardarLocal(x); });
      est.ocupado = false;
      pintarLista();
      var b2 = document.querySelector('[data-mover="' + p.id + ':' + dir + '"]');
      if (b2 && !b2.disabled) b2.focus(); else { var o = document.querySelector('[data-mover="' + p.id + ':' + (-dir) + '"]'); if (o) o.focus(); }
    }).catch(function (e) {
      est.ocupado = false;
      aviso('No se pudo cambiar el orden. ' + e.message, 'rojo');
    });
  }

  // ---------------------------------------------------------------- el editor: estado del formulario
  function formDesde(p) {
    p = p || {};
    return {
      id: p.id || '', tema: p.tema || '', pregunta: p.pregunta || '', en_corto: p.en_corto || '', respuesta: p.respuesta || '',
      articulos: (p.articulos || []).slice(), segun_ley: p.segun_ley || '',
      normas: (p.normas || []).map(function (n) { return { norma: n.norma || '', articulo: n.articulo || '', url: n.url || '' }; }),
      por_banco: p.por_banco || '',
      fuentes_banco: (p.fuentes_banco || []).map(function (f) { return { texto: f.texto || '', url: f.url || '' }; }),
      nota_curador: p.nota_curador || ''
    };
  }
  function contenido(f) {
    var vacioN = function (n) { return !n.norma.trim() && !n.articulo.trim() && !n.url.trim(); };
    var vacioF = function (x) { return !x.texto.trim() && !x.url.trim(); };
    return {
      tema: f.tema, pregunta: f.pregunta.trim(), en_corto: f.en_corto.trim(), respuesta: f.respuesta.trim(), articulos: f.articulos.slice(),
      segun_ley: f.segun_ley.trim(), por_banco: f.por_banco.trim(), nota_curador: f.nota_curador.trim(),
      normas: f.normas.filter(function (n) { return !vacioN(n); }).map(function (n) { return { norma: n.norma.trim(), articulo: n.articulo.trim(), url: n.url.trim() }; }),
      fuentes_banco: f.fuentes_banco.filter(function (x) { return !vacioF(x); }).map(function (x) { return { texto: x.texto.trim(), url: x.url.trim() }; })
    };
  }
  function firma(f) { return JSON.stringify([f.id.trim(), contenido(f)]); }
  function hayCambios() {
    var ed = est.ed;
    return !!ed && ed.base !== firma(ed.form);
  }
  function confirmarDescartar() {
    if (!hayCambios()) return true;
    return window.confirm('Tenés cambios sin guardar en esta pregunta. ¿Querés descartarlos?');
  }
  window.addEventListener('beforeunload', function (ev) {
    if (hayCambios()) { ev.preventDefault(); ev.returnValue = ''; }
  });

  var VACIAS = { de: 1, del: 1, la: 1, el: 1, los: 1, las: 1, un: 1, una: 1, y: 1, o: 1, a: 1, en: 1, que: 1, se: 1, mi: 1, me: 1, por: 1, para: 1, con: 1, es: 1, al: 1, lo: 1 };
  function slug(t) {
    var pal = norm(t).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(function (p) { return p && !VACIAS[p]; });
    var out = [], largo = 0;
    for (var i = 0; i < pal.length && out.length < 6; i++) {
      var suma = pal[i].length + (out.length ? 1 : 0);
      if (largo + suma > MAX.id - 4) break;
      out.push(pal[i]); largo += suma;
    }
    var r = out.join('-');
    if (RESERVADAS[r]) r += '-pregunta';
    var base = r, n = 2;
    while (r && pregunta(r)) { r = base + '-' + n; n++; }
    return r;
  }

  // ---------------------------------------------------------------- abrir / cerrar
  function abrir(clave) {
    if (est.ed && est.ed.clave === clave) { $('editor-titulo').focus(); return; }
    if (!confirmarDescartar()) return;
    var p = pregunta(clave);
    if (!p) return;
    est.ed = { clave: clave, orig: p, form: formDesde(p), base: '', historial: null, errHist: '', idManual: true, cargando: false };
    est.ed.base = firma(est.ed.form);
    mostrarEditor();
    pedir(CURADO + '/' + encodeURIComponent(clave)).then(function (r) {
      if (!est.ed || est.ed.clave !== clave) return;
      est.ed.historial = r.historial || [];
      if (r.pregunta) {
        guardarLocal(r.pregunta);
        var cambio = JSON.stringify(contenido(formDesde(r.pregunta))) !== JSON.stringify(contenido(formDesde(est.ed.orig))) || r.pregunta.estado !== est.ed.orig.estado;
        if (cambio && !hayCambios()) {
          est.ed.orig = r.pregunta; est.ed.form = formDesde(r.pregunta); est.ed.base = firma(est.ed.form);
          pintarTodo(); mostrarEditor(true);
          return;
        }
        est.ed.orig = r.pregunta;
        pintarTodo();
      }
      pintarHistorial();
    }).catch(function (e) {
      if (!est.ed || est.ed.clave !== clave) return;
      est.ed.errHist = e.message;
      pintarHistorial();
    });
  }
  function nueva() {
    if (!confirmarDescartar()) return;
    var f = formDesde({});
    f.tema = est.filtroTema || (est.temas[0] && est.temas[0].clave) || '';
    est.ed = { clave: null, orig: null, form: f, base: '', historial: [], errHist: '', idManual: false, cargando: false };
    est.ed.base = firma(est.ed.form);
    mostrarEditor();
  }
  function cerrar() {
    if (!confirmarDescartar()) return;
    est.ed = null;
    $('editor').hidden = true;
    $('lista').parentNode.classList.remove('con-editor');
    document.body.style.overflow = '';
    pintarLista();
  }
  function mostrarEditor(sinFoco) {
    var ed = est.ed;
    $('editor').hidden = false;
    $('lista').parentNode.classList.add('con-editor');
    if (window.matchMedia('(max-width: 979px)').matches) document.body.style.overflow = 'hidden';
    var es = ed.orig ? ed.orig.estado : 'sin_revisar';
    var pill = $('editor-estado');
    pill.className = 'pill ' + (ed.orig ? es : 'sin_revisar');
    pill.textContent = ed.orig ? ESTADOS[es] : 'Nueva';
    $('editor-titulo').textContent = ed.orig ? ed.orig.pregunta : 'Nueva pregunta';
    limpiarErrores();
    pintarDuda();
    dibujarForm();
    dibujarAcciones();
    vaciar($('confirmar-lugar'));
    pintarVista();
    marcarCambios();
    pintarHistorial();
    pintarLista();
    if (!sinFoco) {
      $('editor').scrollTop = 0;
      $('editor-titulo').focus({ preventScroll: true });
      if (!window.matchMedia('(max-width: 979px)').matches) $('editor').scrollIntoView({ block: 'nearest' });
    }
  }
  function pintarDuda() {
    var ed = est.ed, o = ed.orig, d = vaciar($('editor-duda')), r = vaciar($('editor-retiro'));
    var nota = o ? (o.nota_curador || '').trim() : '';
    d.hidden = !nota;
    if (nota) { d.appendChild(h('b', { text: 'Hay una duda para resolver' })); d.appendChild(h('p', { text: nota })); }
    var ret = o && o.estado === 'retirada';
    r.hidden = !ret;
    if (ret) {
      var m = (o.motivo_retiro || '').trim(), frase;
      if (m === 'sin_respuesta') frase = 'Se retiró porque no tenía una respuesta concreta en el convenio ni en la ley.';
      else if (m === 'dudosa') frase = 'Se retiró porque el dato no estaba confirmado.';
      else frase = 'Se retiró' + (m ? '. Motivo: ' + m : '.');
      r.appendChild(h('b', { text: 'Esta pregunta está retirada: el afiliado no la ve' }));
      r.appendChild(h('p', { text: frase }));
      if ((o.detalle_retiro || '').trim()) r.appendChild(h('p', { text: o.detalle_retiro }));
      r.appendChild(h('p', { class: 'suave chico', text: 'Completá lo que falte y tocá «Publicar» para que vuelva a verse.' }));
    }
  }

  // ---------------------------------------------------------------- el editor: formulario
  var uid = 0;
  function campoTexto(clave, rotulo, ayuda, opts) {
    opts = opts || {};
    var f = est.ed.form, id = 'c-' + clave + '-' + (++uid);
    var el = opts.linea ? h('input', { type: 'text', id: id, maxlength: MAX[clave] ? String(MAX[clave] + 200) : false }) : h('textarea', { id: id, class: opts.alta ? 'alta' : '', rows: opts.alta ? '7' : '4' });
    el.value = f[clave];
    var cont = h('span', { class: 'cont num' });
    function actualizar() {
      var n = el.value.length;
      cont.textContent = n + ' / ' + MAX[clave];
      cont.className = 'cont num' + (n > MAX[clave] ? ' pasado' : '');
      if (n > MAX[clave]) cont.textContent += ' (te pasaste ' + (n - MAX[clave]) + ')';
    }
    el.addEventListener('input', function () {
      f[clave] = el.value;
      actualizar();
      if (clave === 'pregunta' && !est.ed.clave && !est.ed.idManual) { f.id = slug(el.value); var i = $('c-id'); if (i) i.value = f.id; }
      cambioForm();
    });
    actualizar();
    var cab = h('label', { for: id, text: rotulo });
    return h('div', { class: 'campo-ed', 'data-campo': clave }, cab, ayuda ? h('p', { class: 'ayuda', text: ayuda }) : null, el,
      h('div', { class: 'pie-campo' }, opts.pie ? h('span', { text: opts.pie }) : h('span'), cont));
  }
  function dibujarForm() {
    var ed = est.ed, f = ed.form, form = vaciar($('form'));
    form.onsubmit = function (ev) { ev.preventDefault(); };
    if (!ed.clave) {
      var inpId = h('input', { type: 'text', id: 'c-id', maxlength: '80', autocapitalize: 'off', spellcheck: 'false' });
      inpId.value = f.id;
      inpId.addEventListener('input', function () { f.id = inpId.value; ed.idManual = true; cambioForm(); });
      form.appendChild(h('div', { class: 'campo-ed', 'data-campo': 'id' },
        h('label', { for: 'c-id', text: 'Nombre corto' }),
        h('p', { class: 'ayuda', text: 'Es el identificador de la pregunta (letras minúsculas, números y guiones). Se arma solo con la pregunta; podés corregirlo ahora, pero después no se puede cambiar.' }),
        inpId));
    } else {
      form.appendChild(h('p', { class: 'suave chico', style: 'margin-bottom:12px', text: 'Nombre corto: ' + ed.clave + ' (no se puede cambiar)' }));
    }
    var sel = h('select', { id: 'c-tema' });
    if (!f.tema) sel.appendChild(h('option', { value: '', text: 'Elegí un tema…' }));
    est.temas.forEach(function (t) { sel.appendChild(h('option', { value: t.clave, text: t.nombre })); });
    sel.value = f.tema;
    sel.addEventListener('change', function () { f.tema = sel.value; cambioForm(); });
    form.appendChild(h('div', { class: 'campo-ed', 'data-campo': 'tema' }, h('label', { for: 'c-tema', text: 'Tema' }),
      h('p', { class: 'ayuda', text: 'Dónde aparece la pregunta en la lista del afiliado.' }), sel));
    form.appendChild(campoTexto('pregunta', 'Pregunta', 'Como la escribiría el afiliado, con signos de pregunta.', { linea: true }));
    form.appendChild(campoTexto('en_corto', 'Respuesta directa', 'Lo primero que lee el afiliado. Corta y concreta, sin importes en pesos. Si es una escala, un renglón por línea.', { alta: false }));
    var conv = h('div', { class: 'bloque-ed' }, h('h4', { text: 'Qué dice el convenio' }));
    conv.appendChild(campoTexto('respuesta', 'Texto', 'Solo lo que dice el convenio. Si escribís algo acá, citá abajo al menos un artículo.', { alta: true }));
    conv.appendChild(bloqueArticulos());
    form.appendChild(conv);
    var ley = h('div', { class: 'bloque-ed' }, h('h4', { text: 'Según la ley' }));
    ley.appendChild(campoTexto('segun_ley', 'Texto', 'Lo que dice la ley (Ley de Contrato de Trabajo y otras). Si escribís algo acá, agregá abajo la norma.', { alta: true }));
    ley.appendChild(bloqueNormas());
    form.appendChild(ley);
    var banco = h('div', { class: 'bloque-ed' }, h('h4', { text: 'En tu banco' }));
    banco.appendChild(campoTexto('por_banco', 'Texto', 'Acuerdos de La Bancaria con bancos puntuales. Es opcional.', { alta: false }));
    banco.appendChild(bloqueFuentes());
    form.appendChild(banco);
    form.appendChild(campoTexto('nota_curador', 'Nota para quien cura', 'Anotá lo que falta confirmar o decidir. El afiliado no ve esta nota.', { alta: false }));
  }
  function cambioForm() {
    pintarVista();
    marcarCambios();
  }
  function marcarCambios() {
    var m = $('sin-guardar');
    if (m) m.hidden = !hayCambios();
  }

  // artículos
  function bloqueArticulos() {
    var f = est.ed.form, cont = h('div', { class: 'campo-ed', 'data-campo': 'articulos' });
    var lectura = h('div', { class: 'lectura-art', hidden: '', 'aria-live': 'polite' });
    var fichas = h('div', { class: 'fichas' });
    var buscar = h('input', { type: 'text', id: 'c-busca-art', autocomplete: 'off', placeholder: 'Número o palabra del título' });
    var res = h('ul', { class: 'res', hidden: '' });
    function pintarFichas() {
      vaciar(fichas);
      if (!f.articulos.length) fichas.appendChild(h('span', { class: 'suave chico', text: 'Todavía no citaste ningún artículo.' }));
      f.articulos.forEach(function (n) {
        var t = est.porNumero[String(n)];
        fichas.appendChild(h('span', { class: 'ficha-art' },
          h('span', { class: 't', text: 'Art. ' + n + (t ? ' · ' + t : '') }),
          h('button', { type: 'button', 'aria-label': 'Leer el texto del artículo ' + n, title: 'Leer el texto', text: '👁', onclick: function () { leer(n); } }),
          h('button', { type: 'button', 'aria-label': 'Quitar el artículo ' + n, title: 'Quitar', text: '✕', onclick: function () {
            f.articulos = f.articulos.filter(function (x) { return String(x) !== String(n); });
            lectura.hidden = true; pintarFichas(); cambioForm();
          } })));
      });
    }
    function leer(n) {
      lectura.hidden = false;
      vaciar(lectura).appendChild(h('p', { class: 'suave', text: 'Cargando el artículo…' }));
      pedir(API + '/convenio/articulo/' + encodeURIComponent(n)).then(function (a) {
        vaciar(lectura);
        lectura.appendChild(h('h5', { text: 'Art. ' + a.numero + ' · ' + (a.titulo || '') }));
        lectura.appendChild(h('p', { text: a.texto || '(Sin texto cargado.)' }));
        lectura.appendChild(h('button', { type: 'button', class: 'boton claro chico', style: 'margin-top:8px', text: 'Cerrar', onclick: function () { lectura.hidden = true; } }));
      }).catch(function (e) { vaciar(lectura).appendChild(h('p', { class: 'err-campo', text: 'No se pudo leer el artículo. ' + e.message })); });
    }
    function filtrar() {
      var q = norm(buscar.value).trim();
      vaciar(res);
      if (!q) { res.hidden = true; return; }
      var hay = est.articulos.filter(function (a) {
        return f.articulos.map(String).indexOf(String(a.numero)) < 0 && (norm(String(a.numero)) === q || norm('art ' + a.numero + ' ' + a.titulo).indexOf(q) >= 0);
      }).slice(0, 12);
      if (!hay.length) res.appendChild(h('li', { class: 'suave chico', style: 'padding:8px', text: 'No hay artículos con eso.' }));
      hay.forEach(function (a) {
        res.appendChild(h('li', {}, h('button', { type: 'button', text: 'Art. ' + a.numero + ' · ' + a.titulo, onclick: function () {
          f.articulos.push(a.numero); buscar.value = ''; res.hidden = true; vaciar(res); pintarFichas(); cambioForm(); buscar.focus();
        } })));
      });
      res.hidden = false;
    }
    buscar.addEventListener('input', filtrar);
    cont.appendChild(h('span', { class: 'rotulo', text: 'Artículos que cita' }));
    cont.appendChild(h('p', { class: 'ayuda', text: 'Los artículos del convenio en que se apoya la respuesta. Tocá el ojo para leer el texto.' }));
    cont.appendChild(fichas);
    cont.appendChild(lectura);
    cont.appendChild(h('label', { for: 'c-busca-art', style: 'font-size:14px;font-weight:600;margin-top:8px;display:block', text: 'Agregar un artículo' }));
    cont.appendChild(h('div', { class: 'buscador-art' }, buscar, res));
    pintarFichas();
    return cont;
  }

  // normas y fuentes: listas de pares
  function bloqueLista(campo, rotulo, ayuda, tipo) {
    var f = est.ed.form, cont = h('div', { class: 'campo-ed', 'data-campo': campo });
    var lista = h('div', { class: 'lista-doble' });
    function pintar() {
      vaciar(lista);
      f[campo].forEach(function (it, i) {
        var fila = h('div', { class: 'fila-i' });
        function entrada(k, rot, ph, ancho) {
          var id = 'c-' + campo + '-' + (++uid), inp = h('input', { type: 'text', id: id, placeholder: ph || false, maxlength: '600' });
          inp.value = it[k];
          inp.addEventListener('input', function () { it[k] = inp.value; cambioForm(); });
          return h('div', { style: ancho ? 'flex:' + ancho : false }, h('label', { for: id, text: rot }), inp);
        }
        if (tipo === 'norma') {
          fila.appendChild(entrada('norma', 'Norma', 'Ej. Ley de Contrato de Trabajo 20.744', '2 1 220px'));
          fila.appendChild(entrada('articulo', 'Artículo', 'Ej. art. 150', '1 1 120px'));
          fila.appendChild(entrada('url', 'Enlace (opcional, https://…)', 'https://', '2 1 220px'));
        } else {
          fila.appendChild(entrada('texto', 'Fuente', 'Ej. Nota del sindicato, marzo 2026', '2 1 220px'));
          fila.appendChild(entrada('url', 'Enlace (opcional, https://…)', 'https://', '2 1 220px'));
        }
        lista.appendChild(h('div', { class: 'item-doble' }, fila,
          h('div', {}, h('button', { type: 'button', class: 'boton peligro chico', text: 'Quitar', 'aria-label': 'Quitar ' + (tipo === 'norma' ? 'la norma ' : 'la fuente ') + (i + 1), onclick: function () {
            f[campo].splice(i, 1); pintar(); cambioForm();
          } }))));
      });
      if (!f[campo].length) lista.appendChild(h('span', { class: 'suave chico', text: tipo === 'norma' ? 'Todavía no agregaste ninguna norma.' : 'Todavía no agregaste ninguna fuente.' }));
    }
    cont.appendChild(h('span', { class: 'rotulo', text: rotulo }));
    cont.appendChild(h('p', { class: 'ayuda', text: ayuda }));
    cont.appendChild(lista);
    cont.appendChild(h('button', { type: 'button', class: 'boton claro chico', text: tipo === 'norma' ? '+ Agregar una norma' : '+ Agregar una fuente', onclick: function () {
      f[campo].push(tipo === 'norma' ? { norma: '', articulo: '', url: '' } : { texto: '', url: '' }); pintar(); cambioForm();
      var ins = lista.querySelectorAll('.item-doble'); var ult = ins[ins.length - 1]; if (ult) { var i1 = ult.querySelector('input'); if (i1) i1.focus(); }
    } }));
    pintar();
    return cont;
  }
  function bloqueNormas() { return bloqueLista('normas', 'Normas que cita', 'Las leyes o normas en que se apoya. El enlace, si lo hay, tiene que empezar con https://.', 'norma'); }
  function bloqueFuentes() { return bloqueLista('fuentes_banco', 'Fuentes', 'De dónde sale lo de cada banco (notas del sindicato, prensa). El enlace es opcional.', 'fuente'); }

  // ---------------------------------------------------------------- errores
  function limpiarErrores() {
    var res = $('editor-resumen-errores');
    res.hidden = true; vaciar(res);
    Array.prototype.forEach.call(document.querySelectorAll('#editor .err-campo'), function (n) { n.parentNode.removeChild(n); });
    Array.prototype.forEach.call(document.querySelectorAll('#editor .campo-ed.error'), function (n) { n.classList.remove('error'); });
  }
  function mostrarErrores(errores, introduccion) {
    limpiarErrores();
    var res = $('editor-resumen-errores');
    res.appendChild(h('b', { text: introduccion || 'No se pudo guardar. Revisá estos puntos:' }));
    var ul = h('ul', { style: 'margin:6px 0 0 18px' });
    var primero = null;
    errores.forEach(function (e0) {
      var e = { campo: e0.campo, mensaje: String(e0.mensaje || '').replace(/^./, function (c) { return c.toUpperCase(); }) };
      var campo = e.campo || '';
      var blanco = campo ? document.querySelector('#editor [data-campo="' + campo + '"]') : null;
      var texto = (CAMPOS[campo] ? CAMPOS[campo] + ': ' : '') + e.mensaje;
      ul.appendChild(h('li', { text: texto }));
      if (blanco) {
        blanco.classList.add('error');
        blanco.appendChild(h('div', { class: 'err-campo', text: e.mensaje }));
        if (!primero) primero = blanco;
      }
    });
    res.appendChild(ul);
    res.hidden = false;
    var objetivo = primero || res;
    objetivo.scrollIntoView({ block: 'center', behavior: 'smooth' });
    var foco = primero ? primero.querySelector('input,textarea,select,button') : null;
    if (foco) foco.focus({ preventScroll: true });
  }

  // ---------------------------------------------------------------- vista previa
  function pintarVista() {
    var ed = est.ed, f = ed.form, cont = vaciar($('editor-vista'));
    cont.appendChild(h('h4', { text: 'Así lo ve el afiliado' }));
    var t = h('div', { class: 'telefono' });
    t.appendChild(h('div', { class: 'q', text: f.pregunta.trim() || '(Todavía no escribiste la pregunta)' }));
    var corto = renglones(f.en_corto);
    if (corto.length) { var d = h('div', { class: 'encorto' }); corto.forEach(function (r) { d.appendChild(h('p', { text: r })); }); t.appendChild(d); }
    var ps = renglones(f.respuesta);
    if (ps.length) {
      var c = h('div', { class: 'bq' }, h('div', { class: 'kicker', text: 'Qué dice el convenio' }));
      ps.forEach(function (p) { c.appendChild(h('p', { text: p })); });
      if (f.articulos.length) {
        var arts = h('div', { class: 'arts' });
        f.articulos.forEach(function (n) { arts.appendChild(h('span', { text: 'Art. ' + n + (est.porNumero[String(n)] ? ' · ' + est.porNumero[String(n)] : '') })); });
        c.appendChild(arts);
      }
      t.appendChild(c);
    }
    var normas = f.normas.filter(function (n) { return n.norma.trim(); });
    if (f.segun_ley.trim() || normas.length) {
      var l = h('div', { class: 'bq' }, h('div', { class: 'kicker', text: 'Según la ley' }));
      renglones(f.segun_ley).forEach(function (p) { l.appendChild(h('p', { text: p })); });
      if (normas.length) {
        l.appendChild(h('ul', {}, normas.map(function (n) {
          var li = h('li', { text: [n.norma.trim(), n.articulo.trim()].filter(Boolean).join(', ') });
          if (urlHttps(n.url.trim())) li.appendChild(document.createTextNode(' · Ver la norma'));
          return li;
        })));
      }
      t.appendChild(l);
    }
    var fuentes = f.fuentes_banco.filter(function (x) { return x.texto.trim(); });
    if (f.por_banco.trim() || fuentes.length) {
      var b = h('div', { class: 'bq' }, h('div', { class: 'kicker', text: 'En tu banco' }));
      renglones(f.por_banco).forEach(function (p) { b.appendChild(h('p', { text: p })); });
      if (fuentes.length) {
        b.appendChild(h('ul', {}, fuentes.map(function (x) {
          var li = h('li', { text: x.texto.trim() });
          if (urlHttps(x.url.trim())) li.appendChild(document.createTextNode(' · Ver la fuente'));
          return li;
        })));
      }
      b.appendChild(h('p', { class: 'suave chico', text: 'Depende de cada banco: confirmalo con tu delegado.' }));
      t.appendChild(b);
    }
    if (!corto.length && !ps.length && !f.segun_ley.trim() && !f.por_banco.trim()) t.appendChild(h('p', { class: 'vacia', text: 'Cuando escribas la respuesta, la vas a ver acá tal cual la lee el afiliado.' }));
    cont.appendChild(t);
    if (ed.orig && ed.orig.estado === 'retirada') cont.appendChild(h('p', { class: 'suave chico', style: 'margin-top:8px', text: 'Esta pregunta está retirada: el afiliado no la ve todavía.' }));
    else if (!ed.orig || ed.orig.estado === 'sin_revisar') cont.appendChild(h('p', { class: 'suave chico', style: 'margin-top:8px', text: 'Mientras no esté revisada, el afiliado la ve con la marca «sin revisar».' }));
  }

  // ---------------------------------------------------------------- acciones
  function boton(texto, clase, fn) {
    var b = h('button', { type: 'button', class: 'boton ' + (clase || ''), text: texto, onclick: fn });
    if (est.ocupado) b.disabled = true;
    return b;
  }
  function dibujarAcciones() {
    var ed = est.ed, a = vaciar($('acciones'));
    if (!ed) return;
    var es = ed.orig ? ed.orig.estado : null;
    if (!ed.orig) {
      a.appendChild(boton('Crear la pregunta', '', function () { guardar('crear'); }));
      a.appendChild(h('span', { class: 'espacio' }));
      a.appendChild(boton('Cancelar', 'claro', cerrar));
      return;
    }
    if (es === 'retirada') {
      a.appendChild(boton('Guardar', 'claro', function () { guardar('guardar'); }));
      a.appendChild(boton('Publicar', '', function () { pedirConfirmacion('publicar'); }));
      return;
    }
    a.appendChild(boton('Guardar cambios', es === 'revisada' ? '' : 'claro', function () { guardar('guardar'); }));
    if (es === 'sin_revisar') a.appendChild(boton('Guardar y marcar revisada', '', function () { pedirConfirmacion('revisar'); }));
    else a.appendChild(boton('Volver a sin revisar', 'claro', function () { guardar('sin_revisar'); }));
    a.appendChild(h('span', { class: 'espacio' }));
    a.appendChild(boton('Retirar', 'peligro', function () { pedirConfirmacion('retirar'); }));
  }
  function pedirConfirmacion(que) {
    var lugar = vaciar($('confirmar-lugar'));
    var botones = h('div', { class: 'botones' });
    var caja;
    if (que === 'revisar') {
      caja = h('div', { class: 'confirmar-ed' }, h('p', { text: 'Marcar como revisada quiere decir que ya la leíste y que la pregunta y la respuesta están bien. Queda anotado tu nombre y la fecha, y se guardan también los cambios que hiciste.' }), botones);
      botones.appendChild(boton('Sí, marcar revisada', '', function () { guardar('revisar'); }));
    } else if (que === 'publicar') {
      caja = h('div', { class: 'confirmar-ed' }, h('p', { text: 'Publicar vuelve a mostrar la pregunta al afiliado, con la marca «sin revisar» hasta que alguien la revise. Se controla que esté completa antes de publicarla.' }), botones);
      botones.appendChild(boton('Sí, publicar', '', function () { guardar('publicar'); }));
    } else {
      var motivo = h('select', { id: 'r-motivo' },
        h('option', { value: 'sin_respuesta', text: 'No tiene una respuesta concreta' }),
        h('option', { value: 'dudosa', text: 'El dato es dudoso o no está confirmado' }));
      var detalle = h('textarea', { id: 'r-detalle', rows: '3', maxlength: String(MAX.detalle + 200) });
      caja = h('div', { class: 'confirmar-ed rojo' },
        h('p', { text: 'Retirar saca la pregunta de lo que ve el afiliado y de lo que usa la IA. No se borra: la podés completar y publicar más adelante.' }),
        h('div', { class: 'campo-ed', 'data-campo': 'motivo' }, h('label', { for: 'r-motivo', text: 'Motivo' }), motivo),
        h('div', { class: 'campo-ed', 'data-campo': 'detalle' }, h('label', { for: 'r-detalle', text: 'Detalle (qué falta o qué hay que confirmar)' }), detalle), botones);
      botones.appendChild(boton('Retirar la pregunta', 'peligro firme', function () { guardar('retirar', { motivo: motivo.value, detalle: detalle.value.trim() }); }));
    }
    botones.appendChild(boton('Cancelar', 'claro', function () { vaciar(lugar); }));
    lugar.appendChild(caja);
    var primero = caja.querySelector('select,textarea,button');
    if (primero) primero.focus({ preventScroll: true });
    caja.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function guardar(accion, extra) {
    var ed = est.ed;
    if (!ed || est.ocupado) return;
    var cuerpo = contenido(ed.form), url, estadoNuevo = null;
    if (accion === 'crear') {
      cuerpo.id = ed.form.id.trim();
      var mismos = est.preguntas.filter(function (p) { return p.tema === cuerpo.tema; });
      cuerpo.orden = mismos.reduce(function (m, p) { return Math.max(m, p.orden || 0); }, 0) + 1;
      url = CURADO;
    } else {
      url = CURADO + '/' + encodeURIComponent(ed.clave);
      if (accion === 'revisar') estadoNuevo = 'revisada';
      else if (accion === 'sin_revisar' || accion === 'publicar') estadoNuevo = 'sin_revisar';
      else if (accion === 'retirar') { estadoNuevo = 'retirada'; cuerpo.motivo = extra.motivo; cuerpo.detalle = extra.detalle; }
      if (estadoNuevo) cuerpo.estado = estadoNuevo;
    }
    est.ocupado = true;
    limpiarErrores();
    aviso('');
    $('editor').classList.add('cargando');
    dibujarAcciones();
    pedir(url, cuerpo).then(function (r) {
      est.ocupado = false;
      $('editor').classList.remove('cargando');
      var p = r.pregunta;
      guardarLocal(p);
      ed.clave = p.id; ed.orig = p; ed.form = formDesde(p); ed.base = firma(ed.form); ed.idManual = true;
      var frase = { crear: 'La pregunta se creó y quedó «sin revisar».', guardar: 'Se guardaron los cambios.', revisar: 'Guardada y marcada como revisada.',
                    sin_revisar: 'Volvió a «sin revisar».', publicar: 'La pregunta se publicó: el afiliado ya la ve.', retirar: 'La pregunta se retiró: el afiliado ya no la ve.' }[accion];
      pintarTodo();
      mostrarEditor(true);
      var sig = null;
      if (accion === 'revisar') sig = proximaSinRevisar(p.id);
      aviso(frase, 'verde', sig ? h('button', { type: 'button', class: 'boton claro chico', text: 'Ir a la siguiente sin revisar', onclick: function () { abrir(sig); } }) : null);
      pedir(CURADO + '/' + encodeURIComponent(p.id)).then(function (x) {
        if (est.ed && est.ed.clave === p.id) { est.ed.historial = x.historial || []; pintarHistorial(); }
      }).catch(function (e) { if (est.ed) { est.ed.errHist = e.message; pintarHistorial(); } });
    }).catch(function (e) {
      est.ocupado = false;
      $('editor').classList.remove('cargando');
      dibujarAcciones();
      if (e.errores && e.errores.length) {
        var errs = e.errores.map(function (x) {
          if (e.status === 409 && x.campo === 'id') return { campo: 'id', mensaje: 'Ya hay una pregunta con ese nombre corto. Cambialo por otro.' };
          return x;
        });
        mostrarErrores(errs);
      } else {
        mostrarErrores([{ campo: '', mensaje: e.message }], e.red ? 'No se pudo conectar.' : 'No se pudo guardar.');
      }
    });
  }
  function proximaSinRevisar(despuesDe) {
    var vis = est.preguntas.filter(function (p) { return p.estado === 'sin_revisar'; });
    if (!vis.length) return null;
    var base = est.preguntas.map(function (p) { return p.id; }).indexOf(despuesDe);
    for (var i = 0; i < est.preguntas.length; i++) {
      var p = est.preguntas[(base + 1 + i) % est.preguntas.length];
      if (p.estado === 'sin_revisar') return p.id;
    }
    return null;
  }

  // ---------------------------------------------------------------- historial
  var ACCIONES = { crear: 'Creó la pregunta', editar: 'Hizo cambios', revisar: 'La marcó como revisada', retirar: 'La retiró', reponer: 'La volvió a publicar', reordenar: 'Cambió el orden' };
  function quePaso(c) {
    if (c.accion === 'reordenar') return ACCIONES.reordenar;
    var antes = c.antes || {}, desp = c.despues || {}, cambios = [];
    CONTENIDO.forEach(function (k) {
      if (c.accion !== 'crear' && JSON.stringify(antes[k]) !== JSON.stringify(desp[k])) cambios.push((CAMPOS[k] || k));
    });
    var txt = ACCIONES[c.accion] || c.accion;
    if (c.accion === 'editar' && antes.estado && antes.estado !== desp.estado) txt = 'La pasó de «' + (ESTADOS[antes.estado] || antes.estado) + '» a «' + (ESTADOS[desp.estado] || desp.estado) + '»';
    if (cambios.length && c.accion !== 'crear') txt += ' en: ' + cambios.join(', ');
    return txt;
  }
  function pintarHistorial() {
    var ed = est.ed, cont = vaciar($('editor-historial'));
    if (!ed || !ed.clave) return;
    cont.appendChild(h('h4', { text: 'Quién cambió qué' }));
    if (ed.errHist) {
      cont.appendChild(h('p', { class: 'err-campo', text: 'No se pudo leer el historial. ' + ed.errHist }));
      return;
    }
    if (ed.historial == null) { cont.appendChild(h('p', { class: 'suave', text: 'Cargando el historial…' })); return; }
    if (!ed.historial.length) { cont.appendChild(h('p', { class: 'suave', text: 'Esta pregunta todavía no tiene cambios registrados.' })); return; }
    var actual = JSON.stringify(contenido(formDesde(ed.orig)));
    var ul = h('ul', { class: 'hist-lista' });
    ed.historial.forEach(function (c) {
      var li = h('li', {}, h('div', { class: 'q' }, h('b', { text: cuando(c.cuando) + ' · ' + (c.quien || 'el sistema') }), h('span', { text: quePaso(c) })));
      var snap = c.despues || {};
      if (c.accion !== 'reordenar' && snap.pregunta != null) {
        if (JSON.stringify(contenido(formDesde(snap))) === actual) li.appendChild(h('span', { class: 'suave chico', text: 'Es la versión actual' }));
        else li.appendChild(h('button', { type: 'button', class: 'boton claro chico', text: 'Volver a esta versión', onclick: function () { cargarVersion(c); } }));
      }
      ul.appendChild(li);
    });
    // Lo que había antes del cambio más viejo de la lista (para una pregunta de la semilla, el texto original).
    var viejo = ed.historial[ed.historial.length - 1], antes = viejo.antes || {};
    if (antes.pregunta != null && viejo.accion !== 'reordenar') {
      var liV = h('li', {}, h('div', { class: 'q' }, h('b', { text: 'Antes del primer cambio de esta lista' }), h('span', { text: 'Cómo estaba la pregunta antes de que se tocara.' })));
      if (JSON.stringify(contenido(formDesde(antes))) === actual) liV.appendChild(h('span', { class: 'suave chico', text: 'Es la versión actual' }));
      else liV.appendChild(h('button', { type: 'button', class: 'boton claro chico', text: 'Volver a esta versión', onclick: function () { cargarVersion({ cuando: '', despues: antes, original: true }); } }));
      ul.appendChild(liV);
    }
    cont.appendChild(ul);
    cont.appendChild(h('p', { class: 'suave chico', style: 'margin-top:8px', text: 'Se muestran los últimos cambios. «Volver a esta versión» carga ese texto en el editor, pero no se guarda hasta que toques «Guardar cambios».' }));
  }
  function cargarVersion(c) {
    var ed = est.ed;
    if (!ed || !ed.orig) return;
    if (hayCambios() && !window.confirm('Esto reemplaza lo que estás escribiendo ahora por esa versión. ¿Seguís?')) return;
    var viejo = formDesde(c.despues);
    viejo.id = ed.form.id;
    ed.form = viejo;
    limpiarErrores();
    dibujarForm();
    pintarVista();
    marcarCambios();
    pintarHistorial();
    aviso('Se cargó en el editor ' + (c.original ? 'la versión original' : 'la versión del ' + cuando(c.cuando)) + '. Todavía no se guardó: tocá «Guardar cambios» para quedarte con ella.', 'info');
    $('form').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- arranque
  function iniciar() {
    $('nueva').addEventListener('click', nueva);
    $('cerrar').addEventListener('click', cerrar);
    $('f-tema').addEventListener('change', function () { est.filtroTema = $('f-tema').value; pintarLista(); });
    $('f-buscar').addEventListener('input', function () { est.q = $('f-buscar').value; pintarLista(); });
    cargar();
  }
  iniciar();
})();
