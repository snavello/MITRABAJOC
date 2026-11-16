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
    fecha: '', resultado: null, situacion: null, fichas: []
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
      s.rama = v; s.anios = null; s.jerarquia = null; dibujarSeleccion();
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
    $('esc-cct').textContent = 'CCT 18/75' + (r.firmada ? ' · grilla firmada el ' + fechaAr(r.firmada) : '');
    var fu = $('esc-fuente'), f0 = (r.fuentes || [])[0];
    if (f0 && /^https:\/\//.test(f0)) { fu.setAttribute('href', f0); fu.hidden = false; } else { fu.hidden = true; }
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
    var abierto = estado.roeAbierto || r.seleccion.tramo_roe !== null;
    caja.append(h('button', {
      type: 'button', class: 'es-enlace', 'aria-expanded': String(!!abierto),
      text: 'Si conocés el ROE de tu banco, cargalo acá',
      onclick: function () { estado.roeAbierto = !estado.roeAbierto; dibujarRoe(estado.resultado); }
    }));
    if (!abierto) return;
    var items = [{ valor: null, rotulo: 'Valor del comunicado' }].concat(estado.opciones.tramos_roe.map(function (t) { return { valor: t.indice, rotulo: t.rotulo }; }));
    var g = h('div', { class: 'es-pills', role: 'group', 'aria-label': 'Tramo de ROE de tu banco' });
    grupo(g, items, r.seleccion.tramo_roe, async function (v) {
      estado.sel.tramo_roe = v;
      try {
        await consultar(); dibujarResultado();
        var g2 = ls('leer');
        if (g2) { var o = JSON.parse(g2); o.sel.tramo_roe = v; ls('guardar', JSON.stringify(o)); }
      } catch (e) { error(e.message); }
    });
    caja.append(g);
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

  /* ---------- convenio ---------- */
  async function cargarConvenio() {
    if (estado.convenio) return;
    try {
      estado.convenio = await pedir(API + '/convenio');
      estado.convenio.porNumero = {};
      estado.convenio.articulos.forEach(function (a) {
        a._t = norm(a.titulo); a._x = norm(a.texto);
        estado.convenio.porNumero[String(a.numero).toUpperCase()] = a;
      });
      $('conv-nombre').textContent = '18/75';
      dibujarSituaciones(); dibujarIndice();
    } catch (e) { error(e.message); }
  }
  function etiquetaArts(nums) {
    var t = nums.map(String).slice().sort(function (a, b) {
      var na = Number(a), nb = Number(b);
      if (isNaN(na) && isNaN(nb)) return a.localeCompare(b);
      if (isNaN(na)) return 1; if (isNaN(nb)) return -1; return na - nb;
    });
    var cual = function (n) { return isNaN(Number(n)) ? 'disposición transitoria ' + n : n; };
    if (t.length === 1) return (isNaN(Number(t[0])) ? 'Disp. transitoria ' : 'Art. ') + t[0];
    var partes = t.map(cual);
    return 'Arts. ' + partes.slice(0, -1).join(', ') + ' y ' + partes[partes.length - 1];
  }
  function dibujarSituaciones() {
    var cont = vaciar($('sits'));
    estado.convenio.situaciones.forEach(function (s) {
      cont.append(h('button', {
        type: 'button', class: 'es-sit', 'aria-pressed': String(estado.situacion === s.id),
        onclick: function () { elegirSituacion(s); }
      }, h('span', { class: 'a', text: s.titulo }), h('span', { class: 'b', text: etiquetaArts(s.articulos) })));
    });
  }
  function elegirSituacion(s) {
    var igual = estado.situacion === s.id;
    estado.situacion = igual ? null : s.id;
    dibujarSituaciones();
    var cont = vaciar($('conv-fichas'));
    if (igual) return;
    if (s.nota) cont.append(h('p', { class: 'es-nota', text: s.nota }));
    s.articulos.forEach(function (n) { var a = estado.convenio.porNumero[String(n).toUpperCase()]; if (a) cont.append(ficha(a)); });
    cont.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function abrirArticulo(a) {
    estado.situacion = null; dibujarSituaciones();
    var cont = vaciar($('conv-fichas'));
    cont.append(ficha(a));
    cont.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
  function rotuloNumero(a) {
    return isNaN(Number(a.numero)) ? 'Disposición transitoria ' + a.numero : 'Artículo ' + a.numero;
  }
  function renglones(vv, titulo) {
    var largo = vv.renglones.length > 6;
    var lista = h('div', {}, vv.renglones.map(function (r) {
      return h('div', { class: 'es-conc', style: 'padding:9px 0' },
        h('div', { class: 'es-fila' }, h('span', { class: 'rot', text: r.rotulo.charAt(0).toUpperCase() + r.rotulo.slice(1) }), h('span', { class: 'es-imp', text: pesos(r.importe) })),
        h('div', { class: 'es-meta' }, chip(r.etiqueta)));
    }));
    if (!largo) return lista;
    return h('details', {}, h('summary', { text: 'Ver todos los valores (' + vv.renglones.length + ')' }), lista);
  }
  function ficha(a) {
    var vv = a.valores_vigentes, sin = a.resumen_estado !== 'revisado';
    var hero = h('div', { class: 'es-hero' },
      h('div', { class: 'es-kicker', text: rotuloNumero(a) }),
      /* Solo los arts. 1 a 3 titulan por sí mismos; en los demás el título es un
         rótulo descriptivo y no se presenta como texto del convenio. */
      h('h2', { text: a.titulo }),
      a.resumen ? h('p', { text: a.resumen }) : null);
    var bloques = [hero];
    var resumenEstado = h('div', { class: 'bloque' },
      h('span', { class: 'es-chip aviso', text: sin ? 'Resumen sin revisar por el sindicato' : 'Revisado por ' + (a.revisado_por || 'el sindicato') + (a.revisado_en ? ' el ' + fechaAr(a.revisado_en) : '') }));
    bloques.push(resumenEstado);
    if (vv) {
      bloques.push(h('div', { class: 'bloque' },
        h('div', { class: 'es-kicker', text: (a.importe_titulo || 'Importe vigente') + ' · ' + (vv.nombre || vv.periodo) }),
        renglones(vv),
        a.importe_nota ? h('p', { class: 'es-nota', text: a.importe_nota }) : null));
    }
    bloques.push(h('div', { class: 'bloque' },
      h('details', {}, h('summary', { text: 'Texto del convenio' }),
        h('div', { class: 'es-literal', text: a.texto }),
        a.antecedentes ? h('p', { class: 'es-mute', style: 'margin-top:8px', text: 'Antecedentes: ' + a.antecedentes }) : null)));
    var nota = h('p', { class: 'es-nota', hidden: true, text: 'Esto abriría un trámite de consulta gremial dirigido a tu sindicato. En esta etapa no crea nada.' });
    var acciones = [];
    if (a.agregable) {
      acciones.push(h('button', { type: 'button', class: 'es-btn', text: 'Agregarlo a mi selección', onclick: function () { agregarASeleccion(a.agregable); } }));
    }
    acciones.push(h('button', { type: 'button', class: 'es-btn sec', text: 'Hacer una consulta gremial', onclick: function () { nota.hidden = !nota.hidden; } }), nota);
    bloques.push(h('div', { class: 'es-acciones' }, acciones));
    return h('article', { class: 'es-tarjeta es-ficha' }, bloques);
  }
  function agregarASeleccion(que) {
    if (que === 'caja') estado.sel.caja = true;
    if (!estado.sel.titulo && que === 'titulo') estado.sel.titulo = '';
    dibujarSeleccion(); mostrar('seleccion');
    var destino = que === 'titulo' ? $('campo-titulo') : $('sel-caja').parentNode;
    if (que === 'titulo') error('Elegí tu título para agregarlo a la selección.');
    destino.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  function dibujarIndice() {
    var c = estado.convenio, cont = vaciar($('conv-indice'));
    c.grupos.forEach(function (g) {
      cont.append(h('details', {},
        h('summary', {}, h('span', { text: g.titulo }), h('span', { class: 'c', text: g.articulos.length + (g.articulos.length === 1 ? ' artículo' : ' artículos') })),
        g.articulos.map(function (r) {
          var a = c.porNumero[String(r.numero).toUpperCase()];
          return h('button', { type: 'button', class: 'art', onclick: function () { if (a) abrirArticulo(a); } },
            h('span', { class: 'n', text: isNaN(Number(r.numero)) ? 'Disp. ' + r.numero : 'Art. ' + r.numero }), h('span', { text: r.titulo }));
        })));
    });
    if (c.convenio.fuente && /^https:\/\//.test(c.convenio.fuente)) {
      cont.append(h('a', { class: 'es-pdf', href: c.convenio.fuente, target: '_blank', rel: 'noopener noreferrer' },
        h('span', { text: 'Índice completo, ' + c.cantidad_articulos + ' artículos' }), h('span', { text: 'PDF oficial' })));
    }
  }

  /* buscador: en el navegador, sin acentos ni mayúsculas */
  function buscar() {
    var q = norm($('buscar').value).trim(), res = $('conv-resultados'), cant = $('buscar-cant');
    var hay = q.length > 0;
    $('conv-situaciones').hidden = hay; $('conv-indice').hidden = hay; $('conv-fichas').hidden = hay && false;
    if (!hay) { res.hidden = true; cant.textContent = ''; return; }
    if (!estado.convenio) { return; }
    var palabras = q.split(/\s+/), tit = [], tex = [];
    estado.convenio.articulos.forEach(function (a) {
      var porNum = String(a.numero).toLowerCase() === q;
      var todasT = palabras.every(function (p) { return a._t.indexOf(p) >= 0; });
      var todas = palabras.every(function (p) { return a._t.indexOf(p) >= 0 || a._x.indexOf(p) >= 0; });
      if (porNum || todasT) tit.push(a); else if (todas) tex.push(a);
    });
    var lista = tit.concat(tex);
    cant.textContent = lista.length + (lista.length === 1 ? ' artículo' : ' artículos');
    vaciar(res); res.hidden = false;
    if (!lista.length) { res.append(h('p', { class: 'es-nota', style: 'padding:14px 16px', text: 'No encontramos artículos con esas palabras.' })); return; }
    lista.forEach(function (a) {
      var i = a._x.indexOf(palabras[0]), snip = '';
      if (i >= 0 && a._t.indexOf(palabras[0]) < 0) {
        var ini = Math.max(0, i - 50);
        snip = (ini > 0 ? '…' : '') + a.texto.slice(ini, i + 110).replace(/\s+/g, ' ') + '…';
      }
      res.append(h('button', { type: 'button', onclick: function () { abrirArticulo(a); } },
        h('span', { class: 't', text: rotuloNumero(a) + ' · ' + a.titulo }), snip ? h('span', { class: 's', text: snip }) : null));
    });
  }

  /* ---------- arranque ---------- */
  async function iniciar() {
    $('tab-escala').addEventListener('click', function () { mostrar(estado.resultado ? 'escala' : 'seleccion'); });
    $('tab-convenio').addEventListener('click', function () { mostrar('convenio'); });
    $('esc-cambiar').addEventListener('click', function () {
      var s = estado.resultado.seleccion;
      estado.sel = { rama: s.rama, anios: s.anios, jerarquia: s.jerarquia, titulo: s.titulo || '', caja: !!s.caja, tramo_roe: s.tramo_roe };
      $('sel-recordar').checked = !!ls('leer');
      dibujarSeleccion(); mostrar('seleccion');
    });
    $('sel-ver').addEventListener('click', verEscala);
    $('sel-anios').addEventListener('change', function (e) { estado.sel.anios = Number(e.target.value); });
    $('sel-jer').addEventListener('change', function (e) { estado.sel.jerarquia = e.target.value; });
    $('ir-jerarquia').addEventListener('click', function () { estado.sel.jerarquia = ''; estado.sel.anios = null; dibujarSeleccion(); });
    $('ir-anios').addEventListener('click', function () { estado.sel.jerarquia = null; dibujarSeleccion(); });
    $('esc-ir-recibo').addEventListener('click', function () { $('esc-ir-info').hidden = !$('esc-ir-info').hidden; });
    $('buscar').addEventListener('input', buscar);

    try {
      var o = await pedir(API + '/opciones');
      if (!o.disponible) { error(o.mensaje); $('tab-escala').disabled = true; mostrar('convenio'); return; }
      estado.opciones = o;
      var guardado = null, g = ls('leer');
      if (g) { try { guardado = JSON.parse(g); } catch (e) { guardado = null; } }
      if (guardado && guardado.sel) {
        estado.sel = Object.assign({ tramo_roe: null }, guardado.sel);
        try {
          await consultar(); estado.fecha = guardado.fecha;
          $('sel-recordar').checked = true;
          dibujarSeleccion(); dibujarResultado(); mostrar('escala'); return;
        } catch (e) { ls('borrar'); estado.sel = { rama: 'administrativa', anios: null, jerarquia: null, titulo: '', caja: false, tramo_roe: null }; }
      }
      dibujarSeleccion(); mostrar('seleccion');
    } catch (e) { mostrar('seleccion'); error(e.message); }
  }
  iniciar();
})();
