/* Vista de estado de las grillas salariales (Herramientas de /entornos,
   PLAN_CONVENIO_ESCALAS.md D23). Todo lo que viene de una nota del sitio o de
   una persona se dibuja con textContent: nunca como HTML armado a mano. */
(function () {
  'use strict';
  var API = '/api/entornos/herramientas/escalas';
  var estado = { grillas: [], tarea: null, abierta: null };
  var timer = null;

  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') el.className = attrs[k];
      else if (k === 'text') el.textContent = attrs[k];
      else if (k.indexOf('on') === 0) el.addEventListener(k.slice(2), attrs[k]);
      else el.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return el;
  }
  function $(id) { return document.getElementById(id); }
  function vaciar(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function fmt(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number') return v.toLocaleString('es-AR', { maximumFractionDigits: 4 });
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }
  function fecha(t) { return t ? String(t).slice(0, 16) : '—'; }

  function pedir(url, opciones) {
    opciones = opciones || {};
    var init = { method: opciones.metodo || 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' };
    if (opciones.cuerpo !== undefined) {
      init.method = 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opciones.cuerpo);
    }
    return fetch(url, init).then(function (r) {
      return r.text().then(function (t) {
        var d = null;
        try { d = t ? JSON.parse(t) : null; } catch (e) { d = null; }
        if (!r.ok) throw new Error((d && d.detail) ? (typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail)) : ('El servidor respondió ' + r.status));
        return d;
      });
    });
  }

  function aviso(texto, clase) {
    var a = $('aviso');
    a.className = 'aviso' + (clase ? ' ' + clase : '');
    a.textContent = texto;
    a.hidden = !texto;
  }

  function plano(obj, pref, out) {
    out = out || {};
    if (obj !== null && typeof obj === 'object') {
      Object.keys(obj).forEach(function (k) { plano(obj[k], pref ? pref + '.' + k : k, out); });
    } else out[pref] = obj;
    return out;
  }

  function chips(controles) {
    var span = h('span');
    var res = (controles && controles.resultados) || [];
    if (!res.length) return h('span', { class: 'muted', text: '—' });
    res.forEach(function (r) {
      var clase = r.pasa === true ? 'ok' : (r.pasa === false ? 'mal' : 'na');
      span.appendChild(h('span', { class: 'ctl ' + clase, title: r.nombre + ': ' + r.resumen, text: r.control }));
    });
    return span;
  }

  function enlace(url, texto) {
    if (!url || url.indexOf('https://') !== 0) return h('span', { class: 'muted', text: '—' });
    return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text: texto });
  }

  // ---------------------------------------------------------------- resumen
  function pintarResumen(d) {
    var dl = vaciar($('resumen'));
    var act = d.actualizacion || {};
    var cfg = d.config || {};
    function par(k, v) { dl.appendChild(h('dt', { text: k })); dl.appendChild(h('dd', { text: v })); }
    par('Grilla vigente', act.vigente || '—');
    par('Comunicado más nuevo sin grilla', act.comunicado_nuevo ? (act.comunicado_nuevo.periodo + ' (publicado el ' + act.comunicado_nuevo.publicada + ')') : 'ninguno');
    par('Proceso diario', cfg.auto ? ('prendido, a las ' + (cfg.horas || []).join(' y ') + ' (hora de Buenos Aires)') : ('apagado: ' + (cfg.motivo_auto || '')));
    par('Modelo de lectura', cfg.modelo || '—');
    par('IA disponible', cfg.ia_disponible ? 'sí' : ('no: ' + (cfg.motivo_ia || '')));
    var t = cfg.tolerancias || {};
    par('Tolerancias', Object.keys(t).map(function (k) { return k + ' = ' + t[k]; }).join(' · '));
    var ret = (d.grillas || []).filter(function (g) { return g.estado === 'retenida'; }).length;
    if (ret) aviso('Hay ' + ret + ' grilla(s) retenida(s) esperando que alguien las resuelva.', '');
    else aviso('', '');
  }

  function pintarTarea(t) {
    var el = $('tarea');
    if (!t) { el.hidden = true; return; }
    el.hidden = false;
    var txt = t.nombre + ': ' + t.estado + (t.desde ? ' (desde ' + t.desde + ')' : '');
    if (t.estado === 'error') txt += ' — ' + t.error;
    if (t.estado === 'terminada' && t.resultado) {
      var r = t.resultado;
      if (r.motivo) txt += ' — ' + r.motivo;
      if (r.leidas) txt += ' — leídas: ' + r.leidas.length;
      if (r.caso_id) txt += ' — ensayo #' + r.caso_id + ': ' + r.distintas_a + ' y ' + r.distintas_b + ' celdas distintas de ' + r.celdas;
    }
    el.className = 'aviso' + (t.estado === 'error' ? ' rojo' : (t.estado === 'terminada' ? ' verde' : ''));
    el.textContent = txt;
  }

  // ---------------------------------------------------------------- tablas
  function pintarGrillas(lista) {
    var tb = vaciar($('grillas'));
    if (!lista.length) tb.appendChild(h('tr', null, h('td', { colspan: '7', class: 'muted', text: 'Todavía no hay grillas.' })));
    lista.forEach(function (g) {
      var tr = h('tr', { class: 'clic', tabindex: '0', onclick: function () { abrir(g.id); }, onkeydown: function (e) { if (e.key === 'Enter') abrir(g.id); } },
        h('td', { text: g.periodo }),
        h('td', null, h('span', { class: 'pill ' + g.estado, text: g.estado })),
        h('td', { text: g.origen }),
        h('td', null, chips(g.controles)),
        h('td', { text: g.publicada_sindicato || '—' }),
        h('td', null, enlace(g.fuente_nota, 'nota'), ' ', enlace(g.fuente_pdf, 'PDF')),
        h('td', { class: 'muted', text: g.resuelta_por ? (g.resuelta_por + ' · ' + fecha(g.resuelta_en)) : '—' }));
      tb.appendChild(tr);
    });
    var sel = vaciar($('ensayo-periodo'));
    lista.filter(function (g) { return g.estado === 'publicada'; }).forEach(function (g) {
      sel.appendChild(h('option', { value: g.periodo, text: g.periodo }));
    });
  }

  function pintarEnsayos(lista) {
    var tb = vaciar($('ensayos'));
    if (!lista.length) tb.appendChild(h('tr', null, h('td', { colspan: '8', class: 'muted', text: 'Todavía no se corrió ningún ensayo.' })));
    lista.forEach(function (e) {
      var tok = e.ia ? (e.ia.tokens_entrada + ' / ' + e.ia.tokens_salida) : '—';
      tb.appendChild(h('tr', { class: 'clic', tabindex: '0', onclick: function () { abrirEnsayo(e.id); }, onkeydown: function (ev) { if (ev.key === 'Enter') abrirEnsayo(e.id); } },
        h('td', { text: '#' + e.id }), h('td', { text: e.periodo }), h('td', { text: fecha(e.creado) }), h('td', { text: e.quien }),
        h('td', { class: 'num', text: fmt(e.celdas) }), h('td', { class: 'num', text: fmt(e.distintas_a) }),
        h('td', { class: 'num', text: fmt(e.distintas_b) }), h('td', { class: 'num', text: tok })));
    });
  }

  function pintarNovedades(lista) {
    var tb = vaciar($('novedades'));
    lista.forEach(function (n) {
      tb.appendChild(h('tr', null,
        h('td', null, n.url && n.url.indexOf('https://') === 0 ? h('a', { href: n.url, target: '_blank', rel: 'noopener noreferrer', text: n.titulo }) : h('span', { text: n.titulo })),
        h('td', { text: n.tipo }), h('td', { text: n.publicada }), h('td', { text: n.periodo || '—' }),
        h('td', { text: n.resultado ? (n.resultado + (n.ultimo_error ? ': ' + n.ultimo_error : '')) : '—' }),
        h('td', { class: 'num', text: n.tipo === 'grillas' ? String(n.intentos) : '—' })));
    });
  }

  // ---------------------------------------------------------------- detalle de una grilla
  function celdasEditables(g) {
    var rutas = {};
    var etiquetas = g.celdas_con_etiqueta || {};
    ((g.controles && g.controles.resultados) || []).forEach(function (r) {
      (r.detalle || []).forEach(function (d) { if (d && typeof d.ruta === 'string' && etiquetas[d.ruta] !== undefined) rutas[d.ruta] = true; });
    });
    return Object.keys(rutas);
  }

  function abrir(id) {
    pedir(API + '/grillas/' + id).then(function (g) {
      estado.abierta = g;
      pintarDetalle(g);
    }).catch(function (e) { aviso(e.message, 'rojo'); });
  }

  function pintarDetalle(g) {
    var sec = $('detalle');
    sec.hidden = false;
    $('detalle-titulo').textContent = 'Grilla ' + g.periodo + ' · #' + g.id + ' · ' + g.estado;
    var cuerpo = vaciar($('detalle-cuerpo'));
    var valores = plano(g.contenido || {});
    var etiquetas = g.celdas_con_etiqueta || {};
    var kv = h('dl', { class: 'kv' });
    [['Origen', g.origen], ['Nota', g.fuente_nota || '—'], ['PDF', g.fuente_pdf || '—'], ['Publicada por el sindicato', g.publicada_sindicato || '—'],
     ['Creada', g.creada], ['Resuelta', g.resuelta_por ? (g.resuelta_por + ' · ' + g.resuelta_en) : '—'], ['Notas', g.nota || '—']
    ].forEach(function (p) { kv.appendChild(h('dt', { text: p[0] })); kv.appendChild(h('dd', { text: p[1], style: 'white-space:pre-wrap' })); });
    cuerpo.appendChild(kv);

    var inputs = {};
    var editables = g.estado === 'retenida';
    var medidas = g.controles && g.controles.medidas_c4;
    if (medidas) cuerpo.appendChild(h('p', { class: 'muted', style: 'margin-top:8px', text: 'Medidas del factor (C4): factor ' + medidas.factor + ' · desvío máximo $' + medidas.desvio_max + ' · exceso máximo sobre lo permitido $' + medidas.exceso_max + ' · ' + medidas.celdas_comparadas + ' celdas · topes de ROE: ' + (medidas.topes_hasta || []).join(', ') }));
    cuerpo.appendChild(h('h3', { text: 'Controles' }));
    ((g.controles && g.controles.resultados) || []).forEach(function (r) {
      var caja = h('div', { class: 'control' + (r.pasa === false ? ' mal' : '') },
        h('h4', null, h('span', { class: 'ctl ' + (r.pasa === true ? 'ok' : (r.pasa === false ? 'mal' : 'na')), text: r.control }), ' ' + r.nombre + ' — ' + (r.pasa === true ? 'pasa' : (r.pasa === false ? 'NO pasa' : 'no aplica / resuelta a mano'))),
        h('p', { class: 'muted', text: r.resumen }));
      if ((r.detalle || []).length) {
        var tabla = h('table');
        (r.detalle || []).forEach(function (d) {
          var fila = h('tr');
          var que = h('td');
          que.appendChild(h('div', { text: d.etiqueta || (d.ruta ? (etiquetas[d.ruta] || d.ruta) : (d.ancla || d.problema || '')) }));
          var resto = Object.keys(d).filter(function (k) { return ['etiqueta', 'ruta', 'ancla'].indexOf(k) < 0; })
            .map(function (k) { return k + ': ' + fmt(d[k]); }).join(' · ');
          if (resto) que.appendChild(h('div', { class: 'muted mono', text: resto }));
          fila.appendChild(que);
          if (editables && typeof d.ruta === 'string' && etiquetas[d.ruta] !== undefined) {
            var inp = h('input', { type: 'number', step: '0.01', 'aria-label': 'Valor de ' + (etiquetas[d.ruta] || d.ruta) });
            inp.value = valores[d.ruta] === null || valores[d.ruta] === undefined ? '' : String(valores[d.ruta]);
            inp.dataset.original = inp.value;
            inputs[d.ruta] = inp;
            fila.appendChild(h('td', null, inp));
          }
          tabla.appendChild(fila);
        });
        caja.appendChild(h('div', { class: 'scroll' }, tabla));
        if (r.mas) caja.appendChild(h('p', { class: 'muted', text: '… y ' + r.mas + ' más.' }));
      }
      cuerpo.appendChild(caja);
    });

    if (editables) {
      cuerpo.appendChild(h('h3', { text: 'Resolver' }));
      var nota = h('textarea', { maxlength: '500', placeholder: 'Nota (obligatoria si se publica con controles que no pasan)', 'aria-label': 'Nota' });
      cuerpo.appendChild(nota);
      var botones = h('div', { class: 'fila', style: 'margin-top:10px' });
      botones.appendChild(h('button', { type: 'button', class: 'suave', text: 'Guardar correcciones y volver a controlar', onclick: function () {
        var cambios = [];
        Object.keys(inputs).forEach(function (ruta) {
          var i = inputs[ruta];
          if (i.value !== i.dataset.original) cambios.push({ ruta: ruta, valor: i.value === '' ? null : Number(i.value) });
        });
        if (!cambios.length) { aviso('No cambiaste ninguna celda.', ''); return; }
        pedir(API + '/grillas/' + g.id + '/corregir', { cuerpo: { cambios: cambios, nota: nota.value } })
          .then(function () { aviso('Correcciones guardadas y controles repetidos.', 'verde'); cargar(); abrir(g.id); })
          .catch(function (e) { aviso(e.message, 'rojo'); });
      } }));
      botones.appendChild(h('button', { type: 'button', text: 'Publicar', onclick: function () {
        if (!confirm('¿Publicar la grilla ' + g.periodo + '? La Calculadora bancaria pasa a usarla.')) return;
        pedir(API + '/grillas/' + g.id + '/publicar', { cuerpo: { nota: nota.value } })
          .then(function (r) { aviso('Grilla publicada' + (r.forzada ? ' (con controles sin pasar)' : '') + '.', 'verde'); sec_cerrar(); cargar(); })
          .catch(function (e) { aviso(e.message, 'rojo'); });
      } }));
      botones.appendChild(h('button', { type: 'button', class: 'suave', text: 'Volver a leer la nota', onclick: function () {
        if (!confirm('Vuelve a leer el PDF de ' + g.periodo + ' dos veces con la IA y gasta créditos. Esta grilla queda como está. ¿Seguir?')) return;
        pedir(API + '/buscar', { cuerpo: { periodo: g.periodo } })
          .then(function () { aviso('Lectura lanzada: tarda unos minutos.', 'verde'); cargar(); })
          .catch(function (e) { aviso(e.message, 'rojo'); });
      } }));
      botones.appendChild(h('button', { type: 'button', class: 'peligro', text: 'Descartar', onclick: function () {
        if (!confirm('¿Descartar la grilla ' + g.periodo + '? Queda registrado quién y cuándo.')) return;
        pedir(API + '/grillas/' + g.id + '/descartar', { cuerpo: { nota: nota.value } })
          .then(function () { aviso('Grilla descartada.', 'verde'); sec_cerrar(); cargar(); })
          .catch(function (e) { aviso(e.message, 'rojo'); });
      } }));
      cuerpo.appendChild(botones);
    }
    sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function sec_cerrar() { $('detalle').hidden = true; estado.abierta = null; }

  // ---------------------------------------------------------------- ensayo
  function abrirEnsayo(id) {
    pedir(API + '/ensayos/' + id).then(function (e) {
      var cont = vaciar($('ensayo-detalle'));
      cont.hidden = false;
      var dif = e.diferencias || {};
      cont.appendChild(h('h3', { text: 'Ensayo #' + e.id + ' · ' + e.periodo + ' · ' + e.quien }));
      ['lectura_a', 'lectura_b'].forEach(function (k) {
        var l = dif[k] || {};
        cont.appendChild(h('p', { text: (k === 'lectura_a' ? 'Primera lectura' : 'Segunda lectura') + ': ' + l.iguales + ' de ' + l.celdas + ' celdas iguales a la publicada; ' + l.distintas + ' distintas.' }));
        if ((l.detalle || []).length) {
          var t = h('table', null, h('tr', null, h('th', { text: 'Celda' }), h('th', { class: 'num', text: 'Publicada' }), h('th', { class: 'num', text: 'Leída' })));
          l.detalle.forEach(function (d) { t.appendChild(h('tr', null, h('td', { text: d.etiqueta }), h('td', { class: 'num', text: fmt(d.publicada) }), h('td', { class: 'num', text: fmt(d.leida) }))); });
          cont.appendChild(h('div', { class: 'scroll' }, t));
        }
      });
      cont.appendChild(h('p', { class: 'muted', text: 'Controles: ' + (dif.controles || []).map(function (r) { return r.control + ' ' + (r.pasa === true ? 'pasa' : (r.pasa === false ? 'NO pasa' : 'no aplica')); }).join(' · ') }));
      cont.appendChild(h('p', { class: 'muted', text: 'Notas de la lectura: ' + (((e.real || {}).notas || []).join(' | ') || 'ninguna') + ' · duración ' + ((e.real || {}).segundos || '—') + ' s' }));
      cont.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }).catch(function (er) { aviso(er.message, 'rojo'); });
  }

  // ---------------------------------------------------------------- carga
  function cargar() {
    return pedir(API + '/grillas').then(function (d) {
      estado.grillas = d.grillas;
      pintarResumen(d); pintarTarea(d.tarea); pintarGrillas(d.grillas); pintarEnsayos(d.ensayos); pintarNovedades(d.novedades);
      var corriendo = d.tarea && d.tarea.estado === 'corriendo';
      $('buscar').disabled = !!corriendo; $('ensayo').disabled = !!corriendo;
      if (corriendo && !timer) timer = setInterval(cargar, 5000);
      if (!corriendo && timer) { clearInterval(timer); timer = null; }
    }).catch(function (e) { aviso(e.message, 'rojo'); });
  }

  $('buscar').addEventListener('click', function () {
    pedir(API + '/buscar', { cuerpo: {} }).then(function () { aviso('Pasada lanzada: tarda unos minutos si hay una nota nueva.', 'verde'); cargar(); })
      .catch(function (e) { aviso(e.message, 'rojo'); });
  });
  $('ensayo').addEventListener('click', function () {
    var p = $('ensayo-periodo').value;
    if (!p) { aviso('Elegí un período con grilla publicada.', 'rojo'); return; }
    if (!confirm('El ensayo lee la nota de ' + p + ' dos veces con la IA (ocho llamadas) y gasta créditos. ¿Seguir?')) return;
    pedir(API + '/ensayo', { cuerpo: { periodo: p } }).then(function () { aviso('Ensayo lanzado: tarda unos minutos.', 'verde'); cargar(); })
      .catch(function (e) { aviso(e.message, 'rojo'); });
  });
  cargar();
})();
