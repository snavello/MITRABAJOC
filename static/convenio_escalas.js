/* Convenio y escalas (PLAN_CONVENIO_ESCALAS.md). Es una CONSULTA: muestra
   valores sueltos de la grilla, cada uno con su etiqueta, y nunca suma ni
   compara. Todo texto que viene de datos se dibuja con textContent. */
(function () {
  'use strict';
  var raiz = document.getElementById('es-raiz');
  if (!raiz) return;
  var API = raiz.getAttribute('data-api');
  var CLAVE = 'colm3na.escalas.seleccion.v1';
  var $ = function (id) { return document.getElementById(id); };

  var estado = {
    opciones: null, convenio: null, sel: { rama: 'administrativa', anios: null, jerarquia: null, titulo: '', caja: false, tramo_roe: null },
    fecha: '', resultado: null, memJer: '', roeAbierto: undefined
  };

  /* ---------- utilidades ---------- */
  function h(tag, props) {
    var e = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      var v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k.indexOf('on') === 0) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) {
      var kids = [].concat(arguments[i]);
      kids.forEach(function (c) {
        if (c === null || c === undefined || c === false) return;
        e.append(c.nodeType ? c : document.createTextNode(String(c)));
      });
    }
    return e;
  }
  function vaciar(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; }
  function pesos(v) { return window.NumAR ? window.NumAR.pesos(v) : '$ ' + v; }
  function fechaAr(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? m[3] + '/' + m[2] + '/' + m[1] : (iso || '');
  }
  /* Solo se enlaza a https de labancaria.org; otra cosa no se dibuja como enlace. */
  function urlSegura(u) {
    try {
      var x = new URL(u);
      return x.protocol === 'https:' && (x.hostname === 'labancaria.org' || /\.labancaria\.org$/.test(x.hostname));
    } catch (e) { return false; }
  }
  function fechaIsoValida(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof iso === 'string' ? iso : '');
    if (!m) return false;
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
  }
  function diaMes(iso) { var f = fechaAr(iso); return f.slice(0, 5); }
  function norm(t) { return String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function ls(accion, valor) {
    try {
      if (accion === 'leer') return window.localStorage.getItem(CLAVE);
      if (accion === 'guardar') window.localStorage.setItem(CLAVE, valor);
      if (accion === 'borrar') window.localStorage.removeItem(CLAVE);
    } catch (e) { /* sin almacenamiento: la pantalla anda igual */ }
    return null;
  }
  function error(msg) {
    var e = $('es-error');
    if (msg) { e.textContent = msg; e.hidden = false; } else { e.hidden = true; }
  }
  function chip(etiqueta) {
    var ref = etiqueta === 'referencia';
    return h('span', { class: 'es-chip ' + (ref ? 'referencia' : 'publicado'), text: ref ? 'Referencia' : 'Publicado' });
  }
  async function pedir(url, opciones) {
    var r;
    try { r = await fetch(url, opciones); } catch (e) { throw new Error('No se pudo conectar con el servidor.'); }
    var d = null;
    try { d = await r.json(); } catch (e) { d = null; }
    if (!r.ok) throw new Error((d && d.detail) || ('El servidor no respondió (' + r.status + ').'));
    return d;
  }

  /* ---------- vistas ---------- */
  function mostrar(vista) {
    ['seleccion', 'escala', 'convenio'].forEach(function (v) { $('vista-' + v).hidden = (v !== vista); });
    var enConv = vista === 'convenio';
    $('tab-escala').setAttribute('aria-current', enConv ? 'false' : 'page');
    $('tab-convenio').setAttribute('aria-current', enConv ? 'page' : 'false');
    $('es-titulo').textContent = vista === 'seleccion' ? 'Tu selección' : 'Convenio y escalas';
    error('');
    if (enConv) cargarConvenio();
  }

  /* ---------- selección ---------- */
  function ramaActual() {
    var rs = estado.opciones.ramas;
    for (var i = 0; i < rs.length; i++) if (rs[i].clave === estado.sel.rama) return rs[i];
    return rs[0];
  }
  function rotuloAnios(lista, i) {
    var a = lista[i], sig = lista[i + 1];
    if (a === 0) return sig === undefined || sig === 1 ? 'Inicial' : 'Inicial';
    var base = a === 1 ? '1 año' : a + ' años';
    if (sig === undefined) return a + ' años o más';
    if (sig - a > 1) return a + ' a ' + (sig - 1) + ' años';
    return base;
  }
  /* Años que no figuran en el selector (17): el tramo que los contiene (15 a 19). */
  function aniosEnLista(lista, n) {
    if (typeof n !== 'number' || !isFinite(n) || n % 1 !== 0 || n < 0 || !lista.length) return null;
    var elegido = lista[0];
    lista.forEach(function (a) { if (n >= a) elegido = a; });
    return elegido;
  }
  function grupo(contenedor, items, valorActual, alElegir) {
    vaciar(contenedor);
    items.forEach(function (it) {
      contenedor.append(h('button', {
        type: 'button', class: 'es-pill', 'aria-pressed': String(it.valor === valorActual), text: it.rotulo,
        onclick: function () { alElegir(it.valor); }
      }));
    });
  }
  function dibujarSeleccion() {
    var o = estado.opciones, s = estado.sel, rama = ramaActual();
    s.rama = rama.clave;
    grupo($('sel-rama'), o.ramas.map(function (r) { return { valor: r.clave, rotulo: r.nombre }; }), s.rama, function (v) {
      var modoJer = s.jerarquia !== null, previo = s.anios;
      s.rama = v; estado.memJer = '';
      s.jerarquia = modoJer ? '' : null;
      var nueva = ramaActual();
      s.anios = previo === null ? null : aniosEnLista(nueva.anios, previo);
      dibujarSeleccion();
    });
    var porJer = s.jerarquia !== null;
    $('campo-anios').hidden = porJer; $('campo-jer').hidden = !porJer;
    $('ir-jerarquia').hidden = !rama.jerarquias.length;
    var sa = vaciar($('sel-anios'));
    sa.append(h('option', { value: '', text: 'Elegí tus años', disabled: true, selected: s.anios === null }));
    rama.anios.forEach(function (a, i) {
      sa.append(h('option', { value: String(a), text: rotuloAnios(rama.anios, i), selected: s.anios === a }));
    });
    var sj = vaciar($('sel-jer'));
    sj.append(h('option', { value: '', text: 'Elegí tu cargo', disabled: true, selected: !s.jerarquia }));
    rama.jerarquias.forEach(function (j) { sj.append(h('option', { value: j, text: j, selected: s.jerarquia === j })); });
    grupo($('sel-titulo'), o.titulos.map(function (t) { return { valor: t.clave === 'sin' ? '' : t.clave, rotulo: t.rotulo }; }),
      s.titulo || '', function (v) { s.titulo = v; dibujarSeleccion(); });
    grupo($('sel-caja'), [{ valor: false, rotulo: 'No' }, { valor: true, rotulo: 'Sí' }], !!s.caja, function (v) { s.caja = v; dibujarSeleccion(); });
  }
  function cuerpoSeleccion() {
    var s = estado.sel;
    return {
      rama: s.rama, anios: s.jerarquia ? null : s.anios, jerarquia: s.jerarquia || null,
      titulo: s.titulo || '', caja: !!s.caja, tramo_roe: s.tramo_roe
    };
  }
  async function verEscala() {
    var s = estado.sel;
    if (s.jerarquia === null && s.anios === null) { error('Indicá los años de antigüedad o un cargo jerárquico.'); return; }
    if (s.jerarquia !== null && !s.jerarquia) { error('Elegí tu cargo jerárquico.'); return; }
    var btn = $('sel-ver'); btn.disabled = true;
    try {
      await consultar();
      estado.fecha = estado.opciones.hoy;
      if ($('sel-recordar').checked) ls('guardar', JSON.stringify({ sel: cuerpoSeleccion(), fecha: estado.fecha }));
      else ls('borrar');
      dibujarResultado();
      mostrar('escala');
    } catch (e) { error(e.message); }
    finally { btn.disabled = false; }
  }
  async function consultar() {
    estado.resultado = await pedir(API + '/consulta', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seleccion: cuerpoSeleccion() })
    });
  }

  /* ---------- resultado ---------- */
  function resumenSeleccion(r) {
    var s = r.seleccion, rama = null;
    estado.opciones.ramas.forEach(function (x) { if (x.clave === s.rama) rama = x; });
    var tit = { '': 'Sin título', secundario: 'Título secundario', terciario: 'Título terciario', universitario: 'Título universitario' };
    var partes = [rama ? rama.nombre : s.rama, r.categoria, tit[s.titulo || '']];
    if (s.caja) partes.push('Trabajo en caja');
    return partes.join(' · ');
  }
  function conAlcance(parrafo, texto) {
    vaciar(parrafo);
    var corte = 'esto no es tu sueldo', i = texto.indexOf(corte);
    if (i < 0) { parrafo.textContent = texto; return; }
    parrafo.append(texto.slice(0, i), h('b', { text: corte }), texto.slice(i + corte.length));
  }
  function dibujarResultado() {
    var r = estado.resultado;
    $('esc-cuando').textContent = 'Según lo que elegiste el ' + fechaAr(estado.fecha || estado.opciones.hoy);
    $('esc-resumen').textContent = resumenSeleccion(r);
    var pend = r.actualizacion_pendiente, pe = $('esc-pendiente');
    var fp = pend && typeof pend === 'object' ? pend.fecha : pend;
    if (fp) { pe.textContent = 'Hay una actualización publicada el ' + diaMes(fp) + '. La estamos cargando.'; pe.hidden = false; } else { pe.hidden = true; }
    $('esc-periodo').textContent = r.nombre || r.periodo;
    var pub = r.publicacion || {};
    var cuando = fechaIsoValida(pub.publicada_sindicato)
      ? ' · grilla publicada el ' + fechaAr(pub.publicada_sindicato)
      : (r.firmada ? ' · grilla firmada el ' + fechaAr(r.firmada) : '');
    $('esc-cct').textContent = 'CCT 18/75' + cuando;
    var fu = $('esc-fuente'), f0 = (r.fuentes || [])[0], enlace = null, txt = 'Ver la fuente';
    if (pub.fuente_pdf && urlSegura(pub.fuente_pdf)) { enlace = pub.fuente_pdf; txt = 'Ver el PDF'; }
    else if (pub.fuente_nota && urlSegura(pub.fuente_nota)) enlace = pub.fuente_nota;
    else if (f0 && urlSegura(f0)) enlace = f0;
    if (enlace) { fu.setAttribute('href', enlace); fu.textContent = txt; fu.hidden = false; } else { fu.removeAttribute('href'); fu.hidden = true; }
    var cont = vaciar($('esc-conceptos'));
    r.conceptos.forEach(function (c) {
      cont.append(h('div', { class: 'es-conc' },
        h('div', { class: 'es-fila' }, h('span', { class: 'rot', text: c.rotulo }), h('span', { class: 'es-imp', text: pesos(c.importe) })),
        h('div', { class: 'es-meta' }, chip(c.etiqueta), c.nota ? h('span', { class: 'nota', text: c.nota }) : null)));
    });
    dibujarRoe(r);
    conAlcance($('esc-alcance'), r.alcance);
    dibujarEvolucion(r.evolucion);
  }
  function dibujarRoe(r) {
    var caja = vaciar($('esc-roe')), hayRoe = r.conceptos.some(function (c) { return c.clave === 'roe'; });
    caja.hidden = !hayRoe;
    if (!hayRoe) return;
    var tramo = r.seleccion.tramo_roe;
    var abierto = estado.roeAbierto === undefined ? tramo !== null : estado.roeAbierto;
    caja.append(h('button', {
      type: 'button', class: 'es-enlace', 'aria-expanded': String(!!abierto),
      text: 'Si conocés el ROE de tu banco, cargalo acá',
      onclick: function () { estado.roeAbierto = !abierto; dibujarRoe(estado.resultado); }
    }));
    if (!abierto) return;
    async function elegir(v) {
      estado.sel.tramo_roe = v;
      try {
        await consultar(); dibujarResultado();
        var g2 = ls('leer');
        if (g2) { var o = JSON.parse(g2); o.sel.tramo_roe = v; ls('guardar', JSON.stringify(o)); }
      } catch (e) { error(e.message); }
    }
    var items = estado.opciones.tramos_roe.map(function (t) { return { valor: t.indice, rotulo: t.rotulo }; });
    caja.append(h('p', { class: 'es-nota', text: 'El valor es mensual. Elegí el tramo de ROE de tu banco.' }));
    var g = h('div', { class: 'es-pills roe', role: 'group', 'aria-label': 'Tramo de ROE de tu banco' });
    grupo(g, items, tramo, elegir);
    caja.append(g);
    if (tramo !== null) {
      caja.append(h('button', { type: 'button', class: 'es-enlace', text: 'Quitar', onclick: function () { elegir(null); } }));
    }
  }
  function dibujarEvolucion(evo) {
    var concepto = evo.meses.length && evo.meses[0].concepto === 'conformado' ? 'conformado' : 'básico';
    $('evo-titulo').textContent = 'Cómo cambió el ' + concepto + ' de ' + evo.categoria;
    var cont = vaciar($('evo-filas'));
    evo.meses.forEach(function (m) {
      var pct = m.variacion_pct;
      var txt = pct === null || pct === undefined ? '—' : (pct >= 0 ? '+' : '') + window.NumAR.miles(pct, 2).replace(/,?0+$/, '') + '%';
      cont.append(h('div', { class: 'fila' },
        h('span', { class: 'mes', text: m.nombre || m.periodo }),
        h('span', { class: 'val', text: pesos(m.importe) }),
        chip(m.etiqueta),
        h('span', { class: 'pct', text: txt })));
    });
    $('evo-solo').hidden = evo.meses.length > 1;
    $('evo-texto').textContent = evo.alcance;
  }

  /* ---------- convenio (segunda versión: D31 a D37) ----------
     Arriba la consulta a la IA, una pregunta por vez y sin historial; debajo las
     preguntas frecuentes por tema; al final, plegado, el texto literal. Todo lo
     que viene del modelo, de las preguntas o del convenio se dibuja con
     textContent; los enlaces a artículos los arma esta pantalla con los números
     que el servidor ya validó. */
  var PREGUNTA_MAX = 300;
  var faq = { cargado: false, cargando: false, items: [], porId: {}, abierta: null };
  var arts = {};            /* artículos ya pedidos, por número */

  function rotuloNumero(a) {
    return isNaN(Number(a.numero)) ? 'Disposición transitoria ' + a.numero : 'Artículo ' + a.numero;
  }
  function rotuloCorto(n) {
    return isNaN(Number(n)) ? 'Disp. transitoria ' + n : 'Art. ' + n;
  }
  function urlHttps(u) {
    try { return new URL(u).protocol === 'https:'; } catch (e) { return false; }
  }
  function parrafos(texto) {
    return String(texto || '').split(/\n\s*\n/).map(function (p) { return p.trim(); }).filter(Boolean);
  }
  function cargandoLinea(texto) {
    return h('p', { class: 'es-vacio mov-cargando', text: texto });
  }

  function renglones(vv) {
    var largo = vv.renglones.length > 6;
    var lista = h('div', {}, vv.renglones.map(function (r) {
      return h('div', { class: 'es-conc', style: 'padding:9px 0' },
        h('div', { class: 'es-fila' }, h('span', { class: 'rot', text: r.rotulo.charAt(0).toUpperCase() + r.rotulo.slice(1) }), h('span', { class: 'es-imp', text: pesos(r.importe) })),
        h('div', { class: 'es-meta' }, chip(r.etiqueta)));
    }));
    if (!largo) return lista;
    return h('details', {}, h('summary', { text: 'Ver todos los valores (' + vv.renglones.length + ')' }), lista);
  }
  /* El texto literal de un artículo (lo que abren las citas y el índice). */
  function panelArticulo(a) {
    var vv = a.valores_vigentes;
    var bloques = [h('div', { class: 'es-hero' },
      h('div', { class: 'es-kicker', text: rotuloNumero(a) }),
      h('h2', { text: a.titulo }))];
    var cuerpo = [h('div', { class: 'es-literal', text: a.texto })];
    if (a.antecedentes) cuerpo.push(h('p', { class: 'es-mute', text: 'Antecedentes: ' + a.antecedentes }));
    if (vv && vv.renglones && vv.renglones.length) {
      cuerpo.push(h('div', { class: 'es-kicker', text: (a.importe_titulo || 'Importe vigente') + ' · ' + (vv.nombre || vv.periodo) }), renglones(vv));
      if (a.importe_nota) cuerpo.push(h('p', { class: 'es-nota', text: a.importe_nota }));
    }
    bloques.push(h('div', { class: 'bloque' }, cuerpo));
    return h('article', { class: 'es-art es-tarjeta', 'data-armado': '' }, bloques);
  }
  async function pedirArticulo(numero) {
    var k = String(numero);
    if (!arts[k]) arts[k] = await pedir(API + '/convenio/articulo/' + encodeURIComponent(k));
    return arts[k];
  }

  /* Citas: botones «Art. 48 · título» que abren el texto del artículo en el lugar,
     y las preguntas frecuentes relacionadas, que llevan a esa pregunta de la lista. */
  function citas(articulos, frecuentes) {
    var cont = h('div', { class: 'es-citas' });
    var panel = h('div', { 'aria-live': 'polite' });
    var abierto = null;
    if (articulos && articulos.length) {
      var lista = h('div', { class: 'es-citas-lista', role: 'group', 'aria-label': 'Artículos del convenio' });
      articulos.forEach(function (ref) {
        var b = h('button', { type: 'button', class: 'es-cita', 'aria-expanded': 'false', text: rotuloCorto(ref.numero) + ' · ' + ref.titulo });
        b.addEventListener('click', async function () {
          var misma = abierto === b;
          if (abierto) abierto.setAttribute('aria-expanded', 'false');
          vaciar(panel); abierto = null;
          if (misma) return;
          abierto = b; b.setAttribute('aria-expanded', 'true');
          panel.append(cargandoLinea('Abriendo el artículo…'));
          try {
            var a = await pedirArticulo(ref.numero);
            if (abierto !== b) return;
            vaciar(panel); panel.append(panelArticulo(a));
          } catch (e) {
            if (abierto !== b) return;
            vaciar(panel); panel.append(h('p', { class: 'es-error', role: 'alert', text: e.message }));
          }
        });
        lista.append(b);
      });
      cont.append(h('div', { class: 'es-citas-etq', text: 'Artículos que lo sostienen' }), lista);
    }
    var rel = (frecuentes || []).filter(function (f) { return faq.porId[f.id]; });
    if (rel.length) {
      cont.append(h('div', { class: 'es-citas-etq', text: 'Preguntas frecuentes relacionadas' }),
        h('div', { class: 'es-citas-lista' }, rel.map(function (f) {
          return h('button', { type: 'button', class: 'es-cita rel', text: f.pregunta, onclick: function () { irAPregunta(f.id); } });
        })));
    }
    cont.append(panel);
    return cont;
  }

  /* ---------- Preguntale al convenio ---------- */
  var enviando = false;
  async function preguntar(ev) {
    ev.preventDefault();
    if (enviando) return;
    var campo = $('pq-texto'), res = vaciar($('pq-resultado'));
    var pregunta = campo.value.replace(/\s+/g, ' ').trim();
    if (pregunta.length < 3) { res.append(h('p', { class: 'es-error', role: 'alert', text: 'Escribí tu pregunta.' })); campo.focus(); return; }
    if (pregunta.length > PREGUNTA_MAX) { res.append(h('p', { class: 'es-error', role: 'alert', text: 'La pregunta pasa de ' + PREGUNTA_MAX + ' caracteres.' })); return; }
    enviando = true; $('pq-enviar').disabled = true;
    res.setAttribute('aria-busy', 'true');
    res.append(cargandoLinea('Buscando la respuesta en el convenio…'));
    try {
      var d = await pedir(API + '/preguntar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pregunta: pregunta })
      });
      await cargarFrecuentes();     /* para saber a qué preguntas frecuentes se puede llevar */
      vaciar(res); res.append(dibujarRespuesta(d));
    } catch (e) {
      vaciar(res); res.append(h('p', { class: 'es-error', role: 'alert', text: e.message }));
    } finally {
      enviando = false; $('pq-enviar').disabled = false; res.removeAttribute('aria-busy');
    }
  }
  function dibujarRespuesta(d) {
    var responde = d.responde === true;
    var caja = h('div', { class: 'es-resp' + (responde ? '' : ' fija'), 'data-armado': '' });
    if (responde) caja.append(h('span', { class: 'es-chip aviso es-etiqueta-ia', text: 'Respuesta generada por IA sobre el texto del convenio' }));
    caja.append(h('p', { class: 'es-resp-texto', text: d.respuesta || '' }));
    if (responde) {
      caja.append(citas(d.articulos, d.frecuentes));
    } else if (d.puede_enviar && d.consulta_id) {
      var estadoEnvio = h('p', { class: 'es-error', role: 'alert', hidden: true });
      var b = h('button', { type: 'button', class: 'es-btn sec', text: 'Enviar mi consulta' });
      b.addEventListener('click', async function () {
        b.disabled = true; estadoEnvio.hidden = true;
        try {
          await pedir(API + '/consultas/' + encodeURIComponent(d.consulta_id) + '/enviar', { method: 'POST' });
          b.textContent = 'Consulta enviada';
        } catch (e) {
          b.disabled = false; estadoEnvio.textContent = e.message; estadoEnvio.hidden = false;
        }
      });
      caja.append(b, estadoEnvio);
    }
    return caja;
  }

  /* ---------- Preguntas frecuentes ---------- */
  function cargarFrecuentes() {
    if (!faq.promesa) faq.promesa = leerFrecuentes();
    return faq.promesa;
  }
  async function leerFrecuentes() {
    faq.cargando = true;
    var lista = $('fq-lista');
    try {
      var d = await pedir(API + '/frecuentes');
      faq.cargado = true;
      construirFrecuentes(d);
    } catch (e) {
      vaciar(lista).append(h('p', { class: 'es-error', role: 'alert', text: e.message }));
    } finally { faq.cargando = false; if (!faq.cargado) faq.promesa = null; }
  }
  function construirFrecuentes(d) {
    var lista = vaciar($('fq-lista')), hayDraft = false;
    faq.items = []; faq.porId = {};
    (d.temas || []).forEach(function (t) {
      if (!t.preguntas || !t.preguntas.length) return;
      var qs = h('div', { class: 'es-qs' });
      var det = h('details', { class: 'es-tema' },
        h('summary', {}, h('span', { class: 'n', text: t.nombre }), h('span', { class: 'c', text: t.preguntas.length + (t.preguntas.length === 1 ? ' pregunta' : ' preguntas') })), qs);
      var tema = { el: det, qs: qs, nombre: t.nombre, items: [], usuario: false };
      det.firstChild.addEventListener('click', function () { tema.usuario = !det.open; });
      t.preguntas.forEach(function (q) {
        if (q.estado === 'sin_revisar') hayDraft = true;
        var boton = h('button', { type: 'button', 'aria-expanded': 'false', text: q.pregunta });
        var fila = h('div', { class: 'es-q' }, boton);
        var item = { q: q, el: fila, boton: boton, tema: tema, cuerpo: null, _n: norm(q.pregunta + ' ' + (q.en_corto || '')) };
        boton.addEventListener('click', function () { alternarPregunta(item); });
        qs.append(fila); tema.items.push(item); faq.items.push(item); faq.porId[q.id] = item;
      });
      lista.append(det);
      tema._n = norm(t.nombre);
    });
    if (!faq.items.length) lista.append(h('p', { class: 'es-vacio', text: 'Todavía no hay preguntas frecuentes cargadas.' }));
    $('fq-aviso').hidden = !hayDraft;
    filtrarFrecuentes();
  }
  /* Renglones: cada "\n" de en_corto es un renglón propio (una escala corta, p. ej.). */
  function renglones(txt) {
    return String(txt || '').split('\n').map(function (r) { return r.trim(); }).filter(Boolean);
  }
  function cuerpoPregunta(q) {
    var c = h('div', { class: 'es-qcuerpo' });
    if (q.estado === 'sin_revisar') c.append(h('span', { class: 'es-sinrev', text: 'sin revisar' }));
    var corto = renglones(q.en_corto);
    if (corto.length) {
      var dir = h('div', { class: 'es-encorto' });
      corto.forEach(function (r) { dir.append(h('p', { text: r })); });
      c.append(dir);
    }
    var ps = parrafos(q.respuesta);
    if (ps.length) {
      var conv = h('div', { class: 'es-bq' }, h('div', { class: 'es-kicker', text: 'Qué dice el convenio' }));
      ps.forEach(function (p) { conv.append(h('p', { text: p })); });
      if (q.articulos && q.articulos.length) conv.append(citas(q.articulos, []));
      c.append(conv);
    }
    if (q.segun_ley || (q.normas && q.normas.length)) {
      var ley = h('div', { class: 'es-ley es-bq' }, h('div', { class: 'es-kicker', text: 'Según la ley' }));
      parrafos(q.segun_ley).forEach(function (p) { ley.append(h('p', { text: p })); });
      if (q.normas && q.normas.length) {
        ley.append(h('ul', {}, q.normas.map(function (n) {
          var txt = [n.norma, n.articulo].filter(Boolean).join(', ');
          var li = h('li', {}, txt);
          if (n.url && urlHttps(n.url)) li.append(' \u00b7 ', h('a', { href: n.url, target: '_blank', rel: 'noopener noreferrer', text: 'Ver la norma' }));
          return li;
        })));
      }
      c.append(ley);
    }
    var fuentes = (q.fuentes_banco || []).filter(function (f) { return f && f.texto; });
    if (q.por_banco || fuentes.length) {
      var ban = h('div', { class: 'es-banco es-bq' }, h('div', { class: 'es-kicker', text: 'En tu banco' }));
      parrafos(q.por_banco).forEach(function (p) { ban.append(h('p', { text: p })); });
      if (fuentes.length) {
        ban.append(h('ul', {}, fuentes.map(function (f) {
          var li = h('li', {}, f.texto);
          if (f.url && urlHttps(f.url)) li.append(' \u00b7 ', h('a', { href: f.url, target: '_blank', rel: 'noopener noreferrer', text: 'Ver la fuente' }));
          return li;
        })));
      }
      ban.append(h('p', { class: 'es-aclara', text: 'Depende de cada banco: confirmalo con tu delegado.' }));
      c.append(ban);
    }
    if (!ps.length) c.append(h('p', { class: 'es-sin-conv', text: 'El convenio 18/75 no regula este punto.' }));
    return c;
  }
  function cerrarPregunta(item) {
    if (!item) return;
    item.boton.setAttribute('aria-expanded', 'false');
    if (item.cuerpo) { item.cuerpo.remove(); item.cuerpo = null; }
    if (faq.abierta === item) faq.abierta = null;
  }
  function alternarPregunta(item) {
    var abierta = item.boton.getAttribute('aria-expanded') === 'true';
    if (faq.abierta && faq.abierta !== item) cerrarPregunta(faq.abierta);
    if (abierta) { cerrarPregunta(item); return; }
    item.boton.setAttribute('aria-expanded', 'true');
    item.cuerpo = cuerpoPregunta(item.q);
    item.el.append(item.cuerpo);
    faq.abierta = item;
  }
  function irAPregunta(id) {
    var item = faq.porId[id];
    if (!item) return;
    $('fq-filtro').value = ''; filtrarFrecuentes();
    item.tema.el.open = true; item.tema.usuario = true;
    if (item.boton.getAttribute('aria-expanded') !== 'true') alternarPregunta(item);
    item.el.classList.remove('marcada'); void item.el.offsetWidth; item.el.classList.add('marcada');
    item.boton.scrollIntoView({ block: 'center', behavior: 'smooth' });
    item.boton.focus({ preventScroll: true });
  }
  /* Filtro en el navegador, sin acentos ni mayúsculas: todas las palabras tienen que estar. */
  function filtrarFrecuentes() {
    var q = norm($('fq-filtro').value).trim(), palabras = q ? q.split(/\s+/) : [], vistas = 0;
    var temas = [];
    faq.items.forEach(function (it) {
      if (temas.indexOf(it.tema) < 0) temas.push(it.tema);
      var ok = !palabras.length || palabras.every(function (p) { return it._n.indexOf(p) >= 0 || it.tema._n.indexOf(p) >= 0; });
      it.el.hidden = !ok;
      if (ok) vistas++;
      if (!ok && faq.abierta === it) cerrarPregunta(it);
    });
    temas.forEach(function (t) {
      var hay = t.items.some(function (it) { return !it.el.hidden; });
      t.el.hidden = !hay;
      t.el.open = palabras.length ? hay : t.usuario;
    });
    $('fq-cant').textContent = palabras.length ? vistas + (vistas === 1 ? ' pregunta' : ' preguntas') : '';
    var lista = $('fq-lista'), vacio = lista.querySelector('.es-vacio.sin-coincidencias');
    if (vacio) vacio.remove();
    if (palabras.length && !vistas && faq.items.length) {
      lista.append(h('p', { class: 'es-vacio sin-coincidencias', text: 'No encontramos preguntas con esas palabras. Probá preguntándole al convenio, arriba.' }));
    }
  }

  /* ---------- Texto del convenio (plegado) ---------- */
  var textoConv = { cargado: false, cargando: false, porNumero: {} };
  async function cargarTextoConvenio() {
    if (textoConv.cargado || textoConv.cargando) return;
    textoConv.cargando = true;
    try {
      var c = await pedir(API + '/convenio');
      c.articulos.forEach(function (a) { textoConv.porNumero[String(a.numero).toUpperCase()] = a; });
      textoConv.cargado = true;
      dibujarIndice(c);
    } catch (e) {
      vaciar($('conv-indice')).append(h('p', { class: 'es-error', role: 'alert', style: 'margin:0 16px 14px', text: e.message }));
    } finally { textoConv.cargando = false; }
  }
  function abrirArticulo(a) {
    var f = $('conv-ficha');
    vaciar(f); f.hidden = false;
    f.append(panelArticulo(a));
    f.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function dibujarIndice(c) {
    var cont = vaciar($('conv-indice'));
    c.grupos.forEach(function (g) {
      cont.append(h('details', {},
        h('summary', {}, h('span', { text: g.titulo }), h('span', { class: 'c', text: g.articulos.length + (g.articulos.length === 1 ? ' artículo' : ' artículos') })),
        g.articulos.map(function (r) {
          var a = textoConv.porNumero[String(r.numero).toUpperCase()];
          return h('button', { type: 'button', class: 'art', onclick: function () { if (a) abrirArticulo(a); } },
            h('span', { class: 'n', text: rotuloCorto(r.numero) }), h('span', { text: r.titulo }));
        })));
    });
    if (c.convenio.fuente && urlSegura(c.convenio.fuente)) {
      cont.append(h('a', { class: 'es-pdf', href: c.convenio.fuente, target: '_blank', rel: 'noopener noreferrer' },
        h('span', { text: 'Índice completo, ' + c.cantidad_articulos + ' artículos' }), h('span', { text: 'PDF oficial' })));
    }
  }

  function cargarConvenio() { cargarFrecuentes(); }
  function iniciarConvenio() {
    $('pq-form').addEventListener('submit', preguntar);
    $('pq-texto').addEventListener('input', function (e) {
      $('pq-cont').textContent = e.target.value.length + ' / ' + PREGUNTA_MAX;
    });
    $('fq-filtro').addEventListener('input', filtrarFrecuentes);
    $('conv-texto').addEventListener('toggle', function (e) { if (e.target.open) cargarTextoConvenio(); });
  }

  /* ---------- arranque ---------- */
  var AVISO_GUARDADA = 'Tu selección guardada ya no coincide con la grilla vigente: elegila de nuevo.';
  /* La selección guardada se vuelve a mirar contra las opciones de hoy; null si ya no vale. */
  function validarGuardada(g) {
    var o = estado.opciones;
    if (!g || typeof g !== 'object') return null;
    var rama = null;
    o.ramas.forEach(function (r) { if (r.clave === g.rama) rama = r; });
    if (!rama) return null;
    var anios = null, jer = null;
    if (typeof g.jerarquia === 'string' && g.jerarquia) {
      if (rama.jerarquias.indexOf(g.jerarquia) < 0) return null;
      jer = g.jerarquia;
    } else {
      if (g.jerarquia !== null && g.jerarquia !== undefined && g.jerarquia !== '') return null;
      anios = aniosEnLista(rama.anios, g.anios);
      if (anios === null) return null;
    }
    var titulo = g.titulo || '';
    if (typeof titulo !== 'string') return null;
    if (titulo && !o.titulos.some(function (t) { return t.clave === titulo; })) return null;
    if (g.caja !== undefined && typeof g.caja !== 'boolean') return null;
    var tramo = g.tramo_roe === undefined ? null : g.tramo_roe;
    if (tramo !== null && !(typeof tramo === 'number' && o.tramos_roe.some(function (t) { return t.indice === tramo; }))) return null;
    return { rama: rama.clave, anios: anios, jerarquia: jer, titulo: titulo, caja: !!g.caja, tramo_roe: tramo };
  }
  async function iniciar() {
    $('tab-escala').addEventListener('click', function () { mostrar(estado.resultado ? 'escala' : 'seleccion'); });
    $('tab-convenio').addEventListener('click', function () { mostrar('convenio'); });
    $('esc-cambiar').addEventListener('click', function () {
      var s = estado.resultado.seleccion;
      estado.sel = { rama: s.rama, anios: s.anios, jerarquia: s.jerarquia, titulo: s.titulo || '', caja: !!s.caja, tramo_roe: s.tramo_roe };
      estado.memJer = s.jerarquia || '';
      if (s.anios !== null) estado.sel.anios = aniosEnLista(ramaActual().anios, s.anios);
      $('sel-recordar').checked = !!ls('leer');
      dibujarSeleccion(); mostrar('seleccion');
    });
    $('sel-ver').addEventListener('click', verEscala);
    $('sel-anios').addEventListener('change', function (e) { estado.sel.anios = Number(e.target.value); });
    $('sel-jer').addEventListener('change', function (e) { estado.sel.jerarquia = e.target.value; estado.memJer = e.target.value; });
    /* Al alternar se conserva lo elegido en cada modo. */
    $('ir-jerarquia').addEventListener('click', function () { estado.sel.jerarquia = estado.memJer || ''; dibujarSeleccion(); });
    $('ir-anios').addEventListener('click', function () { estado.memJer = estado.sel.jerarquia || ''; estado.sel.jerarquia = null; dibujarSeleccion(); });
    iniciarConvenio();

    try {
      var o = await pedir(API + '/opciones');
      if (!o.disponible) { error(o.mensaje); $('tab-escala').disabled = true; mostrar('convenio'); return; }
      estado.opciones = o;
      var guardado = null, g = ls('leer'), aviso = '';
      if (g) { try { guardado = JSON.parse(g); } catch (e) { guardado = null; } }
      if (g) {
        var sel = guardado && guardado.sel ? validarGuardada(guardado.sel) : null;
        if (!sel) { ls('borrar'); guardado = null; aviso = AVISO_GUARDADA; }
        else {
          estado.sel = sel;
          try {
            await consultar();
            estado.fecha = fechaIsoValida(guardado.fecha) ? guardado.fecha : o.hoy;
            $('sel-recordar').checked = true;
            estado.memJer = sel.jerarquia || '';
            dibujarSeleccion(); dibujarResultado(); mostrar('escala'); return;
          } catch (e) {
            ls('borrar'); aviso = AVISO_GUARDADA;
            estado.sel = { rama: 'administrativa', anios: null, jerarquia: null, titulo: '', caja: false, tramo_roe: null };
          }
        }
      }
      dibujarSeleccion(); mostrar('seleccion');
      if (aviso) error(aviso);
    } catch (e) { mostrar('seleccion'); error(e.message); }
  }
  iniciar();
})();
