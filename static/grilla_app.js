/* Grilla salarial y convenio — pestaña de /app (PLAN_CONVENIO_ESCALAS.md, D42 a D48).
   Es una CONSULTA: muestra valores sueltos de la grilla, cada uno con su
   etiqueta, y nunca suma ni compara. Todo texto que viene del servidor se
   dibuja con textContent. Se carga al abrir la pestaña por primera vez. */
(function () {
  'use strict';
  var panel = document.getElementById('tp-grilla');
  if (!panel) return;
  var API = '/api/app/grilla';
  var CLAVE = 'colm3na.grilla.seleccion.v1';
  var AVISO_GUARDADA = 'Tu selección guardada ya no está disponible en la grilla actual. Elegí de nuevo.';
  var $ = function (id) { return document.getElementById(id); };

  var estado = {
    iniciada: false, opciones: null, convenio: null, vista: 'grilla',
    sel: { rama: 'administrativa', anios: null, jerarquia: null, titulo: '', caja: false, tramo_roe: null },
    fecha: '', resultado: null, roeAbierto: undefined
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
  function diaMes(iso) { return fechaAr(iso).slice(0, 5); }
  function fechaIsoValida(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof iso === 'string' ? iso : '');
    if (!m) return false;
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
  }
  /* Solo se enlaza a https de labancaria.org; otra cosa no se dibuja como enlace. */
  function urlSegura(u) {
    try {
      var x = new URL(u);
      return x.protocol === 'https:' && (x.hostname === 'labancaria.org' || /\.labancaria\.org$/.test(x.hostname));
    } catch (e) { return false; }
  }
  function ls(accion, valor) {
    try {
      if (accion === 'leer') return window.localStorage.getItem(CLAVE);
      if (accion === 'guardar') window.localStorage.setItem(CLAVE, valor);
      if (accion === 'borrar') window.localStorage.removeItem(CLAVE);
    } catch (e) { /* sin almacenamiento: la pantalla anda igual */ }
    return null;
  }
  /* pedirJson (de la pantalla del afiliado) devuelve el error como HTML listo para
     un aviso; acá se pasa a texto plano. Si esa función no está, se hace el
     mismo recorrido mínimo. */
  async function pedir(url, opciones) {
    if (typeof pedirJson === 'function') return pedirJson(url, opciones);
    var r;
    try { r = await fetch(url, opciones); } catch (e) { throw new Error('No pudimos comunicarnos con el servidor.'); }
    var d = null;
    try { d = await r.json(); } catch (e) { d = null; }
    if (!r.ok) throw new Error((d && typeof d.detail === 'string' && d.detail) || 'El servidor no respondió.');
    return d;
  }
  function textoPlano(msg) {
    return String(msg || '')
      .replace(/<span class="cod-error">(.*?)<\/span>/g, ' ($1)')
      .replace(/<[^>]*>/g, '').trim() || 'No se pudo completar la operación.';
  }
  function error(msg) {
    var e = $('gr-error');
    if (msg) { e.textContent = textoPlano(msg); e.hidden = false; } else { e.hidden = true; }
  }
  function chip(etiqueta) {
    var ref = etiqueta === 'referencia';
    return h('span', { class: 'gr-chip ' + (ref ? 'referencia' : 'publicado'), text: ref ? 'Referencia' : 'Publicado' });
  }

  /* ---------- vistas ---------- */
  var VISTAS = ['carga', 'vacio', 'seleccion', 'escala', 'convenio'];
  function mostrar(vista) {
    VISTAS.forEach(function (v) { $('gr-v-' + v).hidden = (v !== vista); });
    $('gr-v-carga').setAttribute('aria-busy', vista === 'carga' ? 'true' : 'false');
    var enConv = vista === 'convenio';
    $('gr-tab-grilla').setAttribute('aria-current', enConv ? 'false' : 'page');
    $('gr-tab-convenio').setAttribute('aria-current', enConv ? 'page' : 'false');
    error('');
  }
  function irAGrilla() {
    estado.vista = 'grilla';
    if (!estado.opciones) { cargarGrilla(); return; }
    mostrar(estado.resultado ? 'escala' : 'seleccion');
  }
  function irAConvenio() {
    estado.vista = 'convenio';
    mostrar('convenio');
    cargarConvenio();
  }
  function sinGrilla(titulo, texto, reintento) {
    $('gr-vacio-tit').textContent = titulo;
    $('gr-vacio-txt').textContent = texto;
    $('gr-reintentar').hidden = !reintento;
    mostrar('vacio');
  }

  /* ---------- selección ---------- */
  function ramaActual() {
    var rs = estado.opciones.ramas;
    for (var i = 0; i < rs.length; i++) if (rs[i].clave === estado.sel.rama) return rs[i];
    return rs[0];
  }
  function rotuloAnios(lista, i) {
    var a = lista[i], sig = lista[i + 1];
    if (a === 0) return 'Inicial';
    if (sig === undefined) return a + ' años o más';
    if (sig - a > 1) return a + ' a ' + (sig - 1) + ' años';
    return a === 1 ? '1 año' : a + ' años';
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
        type: 'button', class: 'gr-pill', 'aria-pressed': String(it.valor === valorActual), text: it.rotulo,
        onclick: function () { alElegir(it.valor); }
      }));
    });
  }
  function dibujarSeleccion() {
    var o = estado.opciones, s = estado.sel, rama = ramaActual();
    s.rama = rama.clave;
    grupo($('gr-sel-rama'), o.ramas.map(function (r) { return { valor: r.clave, rotulo: r.nombre }; }), s.rama, function (v) {
      var previo = s.anios, cargo = s.jerarquia;
      s.rama = v;
      var nueva = ramaActual();
      s.anios = previo === null ? null : aniosEnLista(nueva.anios, previo);
      if (cargo && nueva.jerarquias.indexOf(cargo) < 0) s.jerarquia = null;
      dibujarSeleccion();
    });
    var hayCargos = rama.jerarquias.length > 0;
    if (!hayCargos) s.jerarquia = null;
    $('gr-campo-jer').hidden = !hayCargos;
    $('gr-nota-jer').hidden = !s.jerarquia;
    var sa = vaciar($('gr-sel-anios'));
    sa.append(h('option', { value: '', text: s.jerarquia ? 'Opcional: tus años' : 'Elegí tus años', disabled: !s.jerarquia, selected: s.anios === null }));
    rama.anios.forEach(function (a, i) {
      sa.append(h('option', { value: String(a), text: rotuloAnios(rama.anios, i), selected: s.anios === a }));
    });
    var sj = vaciar($('gr-sel-jer'));
    sj.append(h('option', { value: '', text: 'No tengo cargo jerárquico', selected: !s.jerarquia }));
    rama.jerarquias.forEach(function (j) { sj.append(h('option', { value: j, text: j, selected: s.jerarquia === j })); });
    grupo($('gr-sel-titulo'), o.titulos.map(function (t) { return { valor: t.clave === 'sin' ? '' : t.clave, rotulo: t.rotulo }; }),
      s.titulo || '', function (v) { s.titulo = v; dibujarSeleccion(); });
    grupo($('gr-sel-caja'), [{ valor: false, rotulo: 'No' }, { valor: true, rotulo: 'Sí' }], !!s.caja, function (v) { s.caja = v; dibujarSeleccion(); });
  }
  function cuerpoSeleccion() {
    var s = estado.sel;
    return {
      rama: s.rama, anios: s.jerarquia ? null : s.anios, jerarquia: s.jerarquia || null,
      titulo: s.titulo || '', caja: !!s.caja, tramo_roe: s.tramo_roe
    };
  }
  /* Lo guardado conserva las dos cosas (antigüedad y cargo); al servidor va una u otra. */
  function selGuardable() { var c = cuerpoSeleccion(); c.anios = estado.sel.anios; return c; }
  async function consultar() {
    estado.resultado = await pedir(API + '/consulta', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seleccion: cuerpoSeleccion() })
    });
  }
  async function verEscala() {
    var s = estado.sel;
    if (!s.jerarquia && s.anios === null) { error('Indicá tus años de antigüedad o elegí un cargo jerárquico.'); return; }
    var btn = $('gr-sel-ver'); btn.disabled = true;
    try {
      await consultar();
      estado.fecha = estado.opciones.hoy;
      if ($('gr-sel-recordar').checked) ls('guardar', JSON.stringify({ sel: selGuardable(), fecha: estado.fecha }));
      else ls('borrar');
      dibujarResultado();
      mostrar('escala');
      window.scrollTo(0, 0);
    } catch (e) { error(e.message); }
    finally { btn.disabled = false; }
  }

  /* ---------- resultado ---------- */
  function resumenSeleccion(r) {
    var s = r.seleccion, rama = null;
    estado.opciones.ramas.forEach(function (x) { if (x.clave === s.rama) rama = x; });
    var tit = { '': 'Sin título', secundario: 'Título secundario', terciario: 'Título terciario', universitario: 'Título universitario' };
    var partes = [rama ? rama.nombre : s.rama, r.categoria];
    var sa = estado.sel.anios;
    if (s.jerarquia && rama && typeof sa === 'number') partes.push('Antigüedad: ' + rotuloAnios(rama.anios, rama.anios.indexOf(sa)));
    partes.push(tit[s.titulo || '']);
    if (s.caja) partes.push('Trabajo en caja');
    return partes.join(' · ');
  }
  function conAlcance(parrafo, texto) {
    vaciar(parrafo);
    var corte = 'esto no es tu sueldo', i = String(texto || '').indexOf(corte);
    if (i < 0) { parrafo.textContent = texto || ''; return; }
    parrafo.append(texto.slice(0, i), h('b', { text: corte }), texto.slice(i + corte.length));
  }
  function dibujarResultado() {
    var r = estado.resultado;
    $('gr-esc-cuando').textContent = 'Según lo que elegiste el ' + fechaAr(estado.fecha || estado.opciones.hoy);
    $('gr-esc-resumen').textContent = resumenSeleccion(r);
    var pend = r.actualizacion_pendiente, pe = $('gr-esc-pendiente');
    var fp = pend && typeof pend === 'object' ? pend.fecha : pend;
    if (fp) { pe.textContent = 'Hay una actualización publicada el ' + diaMes(fp) + '. La estamos cargando.'; pe.hidden = false; } else { pe.hidden = true; }
    $('gr-esc-periodo').textContent = r.nombre || r.periodo;
    var pub = r.publicacion || {};
    var cuando = fechaIsoValida(pub.publicada_sindicato)
      ? ' · grilla publicada el ' + fechaAr(pub.publicada_sindicato)
      : (r.firmada ? ' · grilla firmada el ' + fechaAr(r.firmada) : '');
    $('gr-esc-cct').textContent = 'CCT 18/75' + cuando;
    var fu = $('gr-esc-fuente'), f0 = (r.fuentes || [])[0], enlace = null, txt = 'Ver la fuente';
    if (pub.fuente_pdf && urlSegura(pub.fuente_pdf)) { enlace = pub.fuente_pdf; txt = 'Ver el PDF'; }
    else if (pub.fuente_nota && urlSegura(pub.fuente_nota)) enlace = pub.fuente_nota;
    else if (f0 && urlSegura(f0)) enlace = f0;
    if (enlace) { fu.setAttribute('href', enlace); fu.textContent = txt; fu.hidden = false; } else { fu.removeAttribute('href'); fu.hidden = true; }
    var cont = vaciar($('gr-esc-conceptos'));
    r.conceptos.forEach(function (c) {
      cont.append(h('div', { class: 'gr-conc' },
        h('div', { class: 'gr-fila' }, h('span', { class: 'rot', text: c.rotulo }), h('span', { class: 'gr-imp', text: pesos(c.importe) })),
        h('div', { class: 'gr-meta' }, chip(c.etiqueta), c.nota ? h('span', { class: 'gr-cnota', text: c.nota }) : null)));
    });
    dibujarRoe(r);
    conAlcance($('gr-esc-alcance'), r.alcance);
    dibujarEvolucion(r.evolucion);
  }
  function dibujarRoe(r) {
    var caja = vaciar($('gr-esc-roe')), hayRoe = r.conceptos.some(function (c) { return c.clave === 'roe'; });
    caja.hidden = !hayRoe;
    if (!hayRoe) return;
    var tramo = r.seleccion.tramo_roe;
    var abierto = estado.roeAbierto === undefined ? tramo !== null : estado.roeAbierto;
    caja.append(h('button', {
      type: 'button', class: 'gr-enlace', 'aria-expanded': String(!!abierto),
      text: 'Si conocés el ROE de tu banco, cargalo acá',
      onclick: function () { estado.roeAbierto = !abierto; dibujarRoe(estado.resultado); }
    }));
    if (!abierto) return;
    async function elegir(v) {
      estado.sel.tramo_roe = v;
      try {
        await consultar(); dibujarResultado();
        var g2 = ls('leer');
        if (g2) { var o = JSON.parse(g2); o.sel.tramo_roe = v; o.sel.anios = estado.sel.anios; ls('guardar', JSON.stringify(o)); }
      } catch (e) { error(e.message); }
    }
    var items = estado.opciones.tramos_roe.map(function (t) { return { valor: t.indice, rotulo: t.rotulo }; });
    caja.append(h('p', { class: 'gr-nota', text: 'El valor es mensual. Elegí el tramo de ROE de tu banco.' }));
    var g = h('div', { class: 'gr-pills roe', role: 'group', 'aria-label': 'Tramo de ROE de tu banco' });
    grupo(g, items, tramo, elegir);
    caja.append(g);
    if (tramo !== null) {
      caja.append(h('button', { type: 'button', class: 'gr-enlace', text: 'Quitar', onclick: function () { elegir(null); } }));
    }
  }
  function dibujarEvolucion(evo) {
    var concepto = evo.meses.length && evo.meses[0].concepto === 'conformado' ? 'conformado' : 'básico';
    $('gr-evo-titulo').textContent = 'Cómo cambió el ' + concepto + ' de ' + evo.categoria;
    var cont = vaciar($('gr-evo-filas'));
    evo.meses.forEach(function (m) {
      var pct = m.variacion_pct;
      var txt = pct === null || pct === undefined ? '—' : (pct >= 0 ? '+' : '') + window.NumAR.miles(pct, 2).replace(/,?0+$/, '') + '%';
      cont.append(h('div', { class: 'fila' },
        h('span', { class: 'mes', text: m.nombre || m.periodo }),
        h('span', { class: 'val', text: pesos(m.importe) }),
        chip(m.etiqueta),
        h('span', { class: 'pct', text: txt })));
    });
    $('gr-evo-solo').hidden = evo.meses.length > 1;
    $('gr-evo-texto').textContent = evo.alcance;
  }

  /* ---------- selección guardada ---------- */
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
      if (g.anios !== null && g.anios !== undefined) anios = aniosEnLista(rama.anios, g.anios);
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

  /* ---------- carga de la grilla ---------- */
  async function cargarGrilla() {
    mostrar('carga');
    var o;
    try { o = await pedir(API + '/opciones'); }
    catch (e) {
      sinGrilla('No pudimos cargar la grilla', textoPlano(e.message), true);
      return;
    }
    if (!o || !o.disponible) {
      sinGrilla('Todavía no hay una grilla publicada',
        (o && o.mensaje) || 'Cuando el sindicato publique la grilla salarial, la vas a ver acá.', false);
      return;
    }
    estado.opciones = o;
    var guardado = null, g = ls('leer'), aviso = '';
    if (g) { try { guardado = JSON.parse(g); } catch (e) { guardado = null; } }
    if (g) {
      var sel = guardado && guardado.sel ? validarGuardada(guardado.sel) : null;
      if (!sel) { ls('borrar'); aviso = AVISO_GUARDADA; }
      else {
        estado.sel = sel;
        try {
          await consultar();
          estado.fecha = fechaIsoValida(guardado.fecha) ? guardado.fecha : o.hoy;
          $('gr-sel-recordar').checked = true;
          dibujarSeleccion(); dibujarResultado();
          if (estado.vista === 'grilla') mostrar('escala');
          return;
        } catch (e) {
          ls('borrar'); aviso = AVISO_GUARDADA;
          estado.sel = { rama: 'administrativa', anios: null, jerarquia: null, titulo: '', caja: false, tramo_roe: null };
        }
      }
    }
    dibujarSeleccion();
    if (estado.vista === 'grilla') { mostrar('seleccion'); if (aviso) error(aviso); }
  }

  /* ---------- convenio: secciones y artículos en texto literal ---------- */
  function rotuloArticulo(a) {
    var n = String(a.numero);
    var pref = isNaN(Number(n)) ? 'Disp. transitoria ' + n : 'Art. ' + n;
    return a.titulo ? pref + ' · ' + a.titulo : pref;
  }
  function articulo(a) {
    return h('details', { class: 'gr-art' },
      h('summary', { text: rotuloArticulo(a) }),
      h('div', { class: 'gr-literal', text: a.texto || '' }));
  }
  function seccion(titulo, arts, abierta, unidad) {
    var u = unidad || ['artículo', 'artículos'];
    return h('details', { class: 'gr-sec gr-tarjeta', open: abierta },
      h('summary', {}, h('span', { class: 'n', text: titulo }), h('span', { class: 'c', text: arts.length + (arts.length === 1 ? ' ' + u[0] : ' ' + u[1]) })),
      h('div', { class: 'gr-arts' }, arts.map(articulo)));
  }
  function dibujarConvenio(d) {
    var c = d.convenio || {};
    $('gr-conv-nombre').textContent = c.nombre || 'Convenio colectivo';
    $('gr-conv-desc').textContent = c.descripcion || '';
    $('gr-conv-desc').hidden = !c.descripcion;
    var pdf = $('gr-conv-pdf');
    if (d.pdf) { pdf.setAttribute('href', d.pdf); pdf.hidden = false; } else { pdf.hidden = true; }
    var cuerpo = vaciar($('gr-conv-cuerpo'));
    (d.secciones || []).forEach(function (s) {
      if (s.articulos && s.articulos.length) cuerpo.append(seccion(s.titulo, s.articulos, false));
    });
    if (d.transitorias && d.transitorias.length) cuerpo.append(seccion('Cláusulas transitorias', d.transitorias, false, ['cláusula', 'cláusulas']));
    if (d.cierre) cuerpo.append(h('p', { class: 'gr-cierre', text: d.cierre }));
    if (!cuerpo.firstChild) cuerpo.append(h('p', { class: 'gr-vacio', text: 'Todavía no hay texto del convenio para mostrar.' }));
  }
  async function cargarConvenio() {
    if (estado.convenio) return;
    try {
      estado.convenio = await pedir(API + '/convenio');
      dibujarConvenio(estado.convenio);
    } catch (e) {
      var cuerpo = vaciar($('gr-conv-cuerpo'));
      cuerpo.append(h('div', { class: 'gr-tarjeta gr-aviso-vacio' },
        h('h2', { text: 'No pudimos cargar el convenio' }),
        h('p', { text: textoPlano(e.message) }),
        h('button', { type: 'button', class: 'gr-btn sec', text: 'Volver a intentar', onclick: function () {
          estado.convenio = null;
          vaciar($('gr-conv-cuerpo')).append(h('div', { class: 'gr-esq', style: 'height:56px' }), h('div', { class: 'gr-esq', style: 'height:56px' }));
          cargarConvenio();
        } })));
    }
  }

  /* ---------- arranque (una sola vez, al abrir la pestaña) ---------- */
  function iniciar() {
    if (estado.iniciada) return;
    estado.iniciada = true;
    $('gr-tab-grilla').addEventListener('click', irAGrilla);
    $('gr-tab-convenio').addEventListener('click', irAConvenio);
    $('gr-esc-cambiar').addEventListener('click', function () {
      $('gr-sel-recordar').checked = !!ls('leer');
      dibujarSeleccion(); mostrar('seleccion');
    });
    $('gr-sel-ver').addEventListener('click', verEscala);
    $('gr-sel-anios').addEventListener('change', function (e) { estado.sel.anios = e.target.value === '' ? null : Number(e.target.value); });
    $('gr-sel-jer').addEventListener('change', function (e) { estado.sel.jerarquia = e.target.value || null; dibujarSeleccion(); });
    $('gr-reintentar').addEventListener('click', function () { estado.vista === 'convenio' ? cargarConvenio() : cargarGrilla(); });
    cargarGrilla();
  }

  var btn = document.querySelector('.tab-t[data-tp="grilla"]');
  if (btn) btn.addEventListener('click', iniciar);
  if (panel.classList.contains('activo')) iniciar();
})();
