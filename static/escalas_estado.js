/* Vista de estado de las grillas salariales (Herramientas de /entornos,
   PLAN_CONVENIO_ESCALAS.md D23). La usa alguien del equipo que llega por un aviso:
   tiene que entender en pocos segundos cuál es la escala vigente, si hay algo que
   requiere su acción y qué pasó con cada grilla.
   Todo lo que viene de una nota del sitio, de la IA o de una persona se dibuja con
   textContent: nunca como HTML armado a mano. */
(function () {
  'use strict';
  var API = '/api/entornos/herramientas/escalas';
  var estado = { lista: [], ensayos: [], novedades: [], act: {}, config: {}, tarea: null,
                 detalles: {}, abierta: null, ensayoAbierto: null, firmaRevisar: '' };
  var timer = null;

  // ---------------------------------------------------------------- utilidades de DOM
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
  function mayus(t) { t = String(t || ''); return t.charAt(0).toUpperCase() + t.slice(1); }

  // ---------------------------------------------------------------- formatos argentinos
  var MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
  function periodoLindo(p) {
    var m = /^(\d{4})-(\d{2})$/.exec(String(p || ''));
    return m && MESES[+m[2] - 1] ? MESES[+m[2] - 1] + ' ' + m[1] : (p || '—');
  }
  function fechaCorta(t) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(t || ''));
    return m ? m[3] + '/' + m[2] + '/' + m[1] : '—';
  }
  function cuando(t) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(t || ''));
    return m ? m[3] + '/' + m[2] + '/' + m[1] + ' ' + m[4] + ':' + m[5] : fechaCorta(t);
  }
  function hora(t) {
    var m = /[ T](\d{2}:\d{2})/.exec(String(t || ''));
    return m ? m[1] : '';
  }
  function esNum(v) { return typeof v === 'number' && isFinite(v); }
  function numero(v, dec) { return v.toLocaleString('es-AR', { minimumFractionDigits: dec == null ? 0 : dec, maximumFractionDigits: dec == null ? 4 : dec }); }
  function pesos(v) { return '$ ' + numero(v, 2); }
  function porcentaje(v) { return numero(v, 2).replace(/,00$/, '').replace(/(,\d)0$/, '$1') + ' %'; }
  function miles(v) { return numero(v, 0); }
  // Sacar la jerga interna de los textos que arma el servidor.
  function limpiar(t) {
    return String(t == null ? '' : t).replace(/\s*\(D2\d\)/g, '').replace(/D2\d:\s*/g, '')
      .replace(/(^|[^\d-])(\d{4}-\d{2})(?![\d-])/g, function (m, a, per) { return a + periodoLindo(per); });
  }

  // ---------------------------------------------------------------- pedidos
  function pedir(url, opciones) {
    opciones = opciones || {};
    var init = { method: 'GET', headers: { 'Accept': 'application/json' }, cache: 'no-store' };
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
    a.textContent = texto || '';
    a.hidden = !texto;
    if (texto) a.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function enlace(url, texto) {
    if (!url || String(url).indexOf('https://') !== 0) return null;
    return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text: texto });
  }

  // ---------------------------------------------------------------- vocabulario
  // Los seis controles, en castellano: qué mira cada uno. La clave es la que manda la API.
  var CONTROLES = {
    C1: { nombre: 'La grilla está completa', sub: 'estructura', mira: 'Que tenga las mismas ramas, categorías y adicionales que la grilla anterior, y que no falte ninguna celda.' },
    C2: { nombre: 'Las dos lecturas coinciden', sub: 'doble lectura', mira: 'Que la IA, leyendo el PDF dos veces por separado, haya leído exactamente lo mismo.' },
    C3: { nombre: 'Coincide con el comunicado', sub: 'anclas del comunicado', mira: 'Que el salario inicial, el ROE y el mínimo del Día del Bancario de la grilla sean los que dice el comunicado del sindicato.' },
    C4: { nombre: 'Todos los importes subieron lo mismo', sub: 'el factor del mes', mira: 'Que cada importe sea el del mes anterior multiplicado por el mismo factor, y que ese factor sea el porcentaje que anunció el sindicato.' },
    C5: { nombre: 'Los números tienen sentido', sub: 'coherencia interna', mira: 'Que adentro de la grilla los importes sean coherentes: cada básico es su coeficiente por la unidad, y las escalas no bajan al subir la antigüedad.' },
    C6: { nombre: 'Es el mes correcto', sub: 'período', mira: 'Que sea el mes que sigue al vigente y coincida con el comunicado y con el período impreso en el PDF.' }
  };
  var ESTADOS = {
    publicada: 'Publicada', retenida: 'Retenida: espera tu revisión', descartada: 'Descartada', reemplazada: 'Reemplazada por una versión más nueva'
  };
  var TIPOS_NOTA = { comunicado: 'Comunicado de aumento', grillas: 'Nota con las grillas' };
  var RESULTADOS_NOTA = { publicada: 'Se publicó la grilla', retenida: 'Quedó retenida para revisar', error: 'No se pudo leer', salto: 'Falta un mes en el medio, no se leyó',
                          sin_comunicado: 'Sin comunicado con qué controlarla' };
  var CLAVES = {
    problema: 'Qué pasa', detalle: 'Detalle', antes: 'Antes', ahora: 'Ahora', leido: 'Leído', anterior: 'Mes anterior', nuevo: 'Esta grilla', esperado: 'Esperado',
    desvio: 'Diferencia', permitido: 'Diferencia permitida', grilla: 'En la grilla', comunicado: 'En el comunicado', coincide: '¿Coincide?', vigente: 'Valor vigente',
    calculado: 'Valor calculado', factor: 'Factor', lectura_parcial: 'Se alcanzaba a ver', primera: 'Primera lectura', segunda: 'Segunda lectura', meses: 'Meses',
    valor_vigente: 'Valor vigente', valor_calculado: 'Valor calculado', leido_en_una_lectura: 'Leído en una de las lecturas', texto: 'Explicación',
    porcentaje_del_factor: 'Porcentaje del factor', rama: 'Rama', celdas: 'Celdas', controles: 'Controles que fallarían', cociente_contra_el_anterior: 'Cociente contra el anterior',
    trimestre_anterior: 'Trimestre anterior', publicada: 'Publicada', basico: 'Básico', mas: 'Más'
  };
  var DINERO = { leido: 1, anterior: 1, nuevo: 1, esperado: 1, desvio: 1, permitido: 1, grilla: 1, comunicado: 1, vigente: 1, calculado: 1, primera: 1, segunda: 1,
                 valor_vigente: 1, valor_calculado: 1, leido_en_una_lectura: 1, basico: 1, publicada: 1 };
  var OCULTAS = { etiqueta: 1, ruta: 1, ancla: 1, conservada: 1 };

  function valorLindo(k, v) {
    if (v === null || v === undefined) return 'no se pudo leer';
    if (typeof v === 'boolean') return v ? 'Sí' : 'No';
    if (esNum(v)) {
      if (k === 'factor') return numero(v, 6);
      if (k === 'porcentaje_del_factor') return porcentaje(v);
      if (DINERO[k]) return pesos(v);
      return numero(v, 4);
    }
    if (k === 'meses' && Array.isArray(v)) return v.map(periodoLindo).join(', ');
    if (Array.isArray(v)) return v.map(function (x) { return typeof x === 'object' ? JSON.stringify(x) : valorLindo(k, x); }).join(', ');
    if (typeof v === 'object') {
      return Object.keys(v).map(function (kk) { return (CLAVES[kk] || kk) + ': ' + valorLindo(kk, v[kk]); }).join(' · ');
    }
    return limpiar(v);
  }

  // ---------------------------------------------------------------- lectura de una grilla
  function resultados(g) { return (g && g.controles && g.controles.resultados) || []; }
  function porControl(g, clave) { return resultados(g).filter(function (r) { return r.control === clave; })[0]; }
  function etiquetasDe(g) { return (g && g.celdas_con_etiqueta) || {}; }
  function aprobados(g) {
    var rs = resultados(g);
    return { ok: rs.filter(function (r) { return r.pasa === true; }).length, total: rs.length };
  }
  function origenTexto(g) {
    var corr = g.controles && g.controles.correcciones;
    if (g.origen === 'semilla') return 'Cargada a mano desde el PDF firmado';
    if (g.origen === 'manual') return 'Cargada a mano';
    if (corr && corr.length) return 'Leída por la IA y corregida a mano por ' + (corr[corr.length - 1].quien || 'el equipo');
    return 'Leída sola por la IA';
  }
  function vigente() { return estado.act && estado.act.vigente; }
  function grillaVigente() {
    var v = vigente();
    return estado.lista.filter(function (g) { return g.periodo === v && g.estado === 'publicada'; })[0] || null;
  }
  function retenidas() { return estado.lista.filter(function (g) { return g.estado === 'retenida'; }); }

  // Por qué quedó retenida, en castellano: una lista de {control, lineas}.
  function motivosDe(g) {
    var et = etiquetasDe(g);
    var salida = [];
    resultados(g).forEach(function (r) {
      if (r.pasa !== false) return;
      var c = CONTROLES[r.control] || { nombre: r.nombre || r.control };
      var lineas = [];
      var det = r.detalle || [];
      if (r.control === 'C1') {
        var sinLeer = det.filter(function (d) { return d.problema === 'celda sin leer'; });
        var etq = function (d) { return d.etiqueta || et[d.ruta] || d.ruta || ''; };
        if (sinLeer.length) {
          lineas.push(sinLeer.length === 1
            ? 'No se pudo leer una celda: ' + etq(sinLeer[0]) + '. En el PDF no se lee con claridad (por ejemplo, una firma o una mancha encima).'
            : 'No se pudieron leer ' + sinLeer.length + ' celdas: ' + sinLeer.slice(0, 4).map(etq).join('; ') + (sinLeer.length > 4 ? ' y ' + (sinLeer.length - 4) + ' más' : '') + '.');
        }
        det.forEach(function (d) {
          var p = String(d.problema || '');
          if (p === 'celda sin leer') return;
          if (p === 'forma inválida' && sinLeer.length) return;     // consecuencia de la celda vacía
          if (/^D28:/.test(p) && esNum(d.calculado)) {
            lineas.push('El sistema intentó completar ' + etq(d) + ' por cálculo (' + pesos(d.calculado) + ', el valor vigente por el factor del mes), pero no coincide con lo que se alcanza a ver en el PDF'
              + ((d.lectura_parcial || []).length ? ' («' + d.lectura_parcial.join('» / «') + '»)' : '') + '. Por eso no lo completó: tiene que mirarlo una persona.');
          } else if (/^D28:/.test(p)) {
            lineas.push(limpiar(p) + ((d.celdas || []).length ? ': ' + d.celdas.join('; ') : '') + '.');
          } else if (p === 'forma inválida') {
            lineas.push('La grilla leída está incompleta: ' + limpiar(d.detalle) + '.');
          } else if (p) {
            lineas.push(mayus(limpiar(p)) + (d.etiqueta ? ': ' + d.etiqueta : (d.detalle ? ': ' + limpiar(d.detalle) : '')) + '.');
          }
        });
      } else if (r.control === 'C2') {
        lineas.push('Las dos lecturas del PDF no dicen lo mismo en ' + (det.length + (r.mas || 0)) + ' celda(s)' + (det.length ? ', por ejemplo: ' + det.slice(0, 3).map(function (d) { return et[d.ruta] || d.ruta; }).join('; ') : '') + '.');
      } else if (r.control === 'C3') {
        var malas = det.filter(function (d) { return d.coincide === false; });
        lineas.push('No coincide con el comunicado del sindicato: ' + (malas.length ? malas.map(function (d) { return d.ancla; }).join('; ') : limpiar(r.resumen)) + '.');
      } else if (r.control === 'C4') {
        lineas.push(frase4(g, r));
      } else {
        lineas.push(limpiar(r.resumen));
      }
      salida.push({ control: r.control, nombre: c.nombre, lineas: lineas });
    });
    return salida;
  }

  // C4 en una frase: el factor como porcentaje y comparado con el del comunicado.
  function frase4(g, r) {
    var m = g.controles && g.controles.medidas_c4;
    var com = g.controles && g.controles.comunicado;
    if (!m || !esNum(m.factor)) return limpiar(r.resumen);
    var pct = (m.factor - 1) * 100;
    var t;
    if (r.pasa === true) t = 'Los ' + miles(m.celdas_comparadas) + ' importes comparados subieron todos un ' + porcentaje(pct) + ' (factor ' + numero(m.factor, 5) + '), con una diferencia máxima de ' + pesos(m.desvio_max) + ' por el redondeo.';
    else t = 'Hay ' + ((r.detalle || []).length + (r.mas || 0)) + ' importe(s) que no subieron igual que el resto, que subió un ' + porcentaje(pct) + ' (factor ' + numero(m.factor, 5) + ').';
    if (esNum(m.tolerancia_pesos)) t += ' Se acepta hasta ' + pesos(m.tolerancia_pesos) + ' de diferencia por importe.';
    if (com && esNum(com.porcentaje)) {
      t += ' El comunicado del sindicato dice ' + porcentaje(com.porcentaje) + (Math.abs(pct - com.porcentaje) <= 0.05 + 1e-9 ? ': coinciden.' : ': no coincide.');
    }
    return t;
  }

  function dice(g, r) {
    if (r.control === 'C4') return frase4(g, r);
    return limpiar(r.resumen);
  }

  // ---------------------------------------------------------------- piezas
  function pill(clase, texto) { return h('span', { class: 'pill ' + clase, text: texto }); }

  function itemDetalle(d, et) {
    var titulo = d.etiqueta || et[d.ruta] || d.ancla || d.conservada || '';
    var caja = h('div', { class: 'item' });
    var cabeza = h('div', { class: 't', text: limpiar(titulo || d.problema || d.detalle || '') });
    if (d.ruta) cabeza.setAttribute('title', 'Celda técnica: ' + d.ruta);
    if (d.valor_calculado !== undefined) { cabeza.appendChild(document.createTextNode(' ')); cabeza.appendChild(pill('calculada', 'calculada')); }
    caja.appendChild(cabeza);
    var dl = h('dl');
    Object.keys(d).forEach(function (k) {
      if (OCULTAS[k]) return;
      if (!titulo && (k === 'problema' || k === 'detalle')) { if (k === 'detalle' && d.problema) { /* sigue */ } else return; }
      if (d[k] === undefined) return;
      dl.appendChild(h('dt', { text: CLAVES[k] || mayus(k.replace(/_/g, ' ')) }));
      dl.appendChild(h('dd', { text: valorLindo(k, d[k]) }));
    });
    if (dl.firstChild) caja.appendChild(dl);
    return caja;
  }

  function listaControles(g) {
    var et = etiquetasDe(g);
    var rs = resultados(g);
    var ul = h('ul', { class: 'controles' });
    if (!rs.length) return h('p', { class: 'vacio', text: 'Esta grilla no pasó por los controles automáticos: es una transcripción hecha a mano del PDF firmado.' });
    rs.forEach(function (r) {
      var c = CONTROLES[r.control] || { nombre: r.nombre || r.control, mira: '' };
      var clase = r.pasa === true ? 'pasa' : (r.pasa === false ? 'no-pasa' : 'no-aplica');
      var palabra = r.pasa === true ? 'Pasa' : (r.pasa === false ? 'No pasa' : 'No aplica');
      var li = h('li', { class: 'control ' + clase },
        h('div', { class: 'cab-control' },
          h('div', null, h('span', { class: 'resultado ' + clase, text: palabra })),
          h('div', null,
            h('div', { class: 'nombre', text: c.nombre + (c.sub ? ' — ' + c.sub : '') }),
            h('div', { class: 'que-mira', text: 'Mira: ' + c.mira }),
            h('div', { class: 'dice', text: dice(g, r) }))));
      var det = (r.detalle || []);
      if (det.length) {
        var cuerpo = h('div', { class: 'detalle' });
        det.forEach(function (d) { cuerpo.appendChild(itemDetalle(d, et)); });
        if (r.mas) cuerpo.appendChild(h('p', { class: 'suave chico', text: '… y ' + r.mas + ' más que no se muestran.' }));
        li.appendChild(h('details', null, h('summary', { text: 'Ver el detalle (' + det.length + ')' }), cuerpo));
      }
      ul.appendChild(li);
    });
    return ul;
  }

  // Lo que el sistema hizo por su cuenta: a la vista, sin alarmar.
  function bloqueCuenta(g) {
    var c = g.controles || {};
    var calc = c.celdas_calculadas || [];
    var cons = c.conectividad_conservada || [];
    var notas = c.notas_lectura || [];
    var defectos = c.defectos_respuesta || [];
    var ia = c.ia;
    if (!calc.length && !cons.length && !notas.length && !defectos.length && !ia) return null;
    var caja = h('div', { class: 'cuenta' });
    if (calc.length || cons.length || notas.length || defectos.length) caja.appendChild(h('h4', { text: 'Lo que el sistema hizo por su cuenta' }));
    var ul = h('ul');
    calc.forEach(function (e) {
      ul.appendChild(h('li', null, pill('calculada', 'calculada'), ' ' + limpiar(e.texto || e.etiqueta || e.ruta).replace(/\.?$/, '.') + ' El PDF no dejaba leer esa celda; se calculó como el valor vigente por el factor del mes, con ±1 centavo de incertidumbre por el redondeo.'));
    });
    cons.forEach(function (m) {
      var ms = (m || []).map(periodoLindo);
      ul.appendChild(h('li', { text: 'Conectividad de ' + (ms.length > 1 ? ms[0] + ' a ' + ms[ms.length - 1] : ms[0]) + ': el PDF ya no la trae (el trimestre venció), así que se conservó la de la grilla anterior tal cual estaba publicada.' }));
    });
    if (ul.firstChild) caja.appendChild(ul);
    if (notas.length) {
      caja.appendChild(h('p', { class: 'sub', text: 'Comentarios de la IA al leer el PDF' }));
      var ln = h('ul');
      notas.forEach(function (n) { ln.appendChild(h('li', { text: String(n) })); });
      caja.appendChild(ln);
      caja.appendChild(h('p', { class: 'chico', style: 'margin-top:6px', text: 'Son observaciones de la IA: por sí solas no frenan una grilla.' }));
    }
    if (defectos.length) {
      caja.appendChild(h('p', { class: 'sub', text: 'Problemas al interpretar la respuesta de la IA' }));
      var ld = h('ul');
      defectos.forEach(function (n) { ld.appendChild(h('li', { text: String(n) })); });
      caja.appendChild(ld);
    }
    if (ia) caja.appendChild(h('p', { class: 'costo', text: 'Lectura con IA: ' + miles(ia.llamadas || 0) + ' llamadas, ' + miles(ia.tokens_entrada || 0) + ' unidades de texto leído y ' + miles(ia.tokens_salida || 0) + ' escritas.' }));
    return caja;
  }

  function ficha(g) {
    var dl = h('dl', { class: 'ficha' });
    function par(k, v) { dl.appendChild(h('dt', { text: k })); dl.appendChild(v instanceof Node ? h('dd', null, v) : h('dd', { text: v })); }
    par('De dónde salió', origenTexto(g));
    par('Publicada por el sindicato', fechaCorta(g.publicada_sindicato));
    par('Cargada en el sistema', cuando(g.creada));
    par('Resuelta', g.resuelta_por ? g.resuelta_por + ' · ' + cuando(g.resuelta_en) : 'Todavía no');
    var nota = enlace(g.fuente_nota, 'la nota del sitio'), pdf = enlace(g.fuente_pdf, 'el PDF');
    if (nota || pdf) {
      var span = h('span');
      if (nota) span.appendChild(nota);
      if (nota && pdf) span.appendChild(document.createTextNode(' · '));
      if (pdf) span.appendChild(pdf);
      par('Fuente', span);
    }
    if (g.nota) par('Notas', limpiar(g.nota));
    return dl;
  }

  function cuerpoGrilla(g) {
    var cont = h('div', { class: 'cuerpo' });
    cont.appendChild(ficha(g));
    var cuenta = bloqueCuenta(g);
    if (cuenta) cont.appendChild(cuenta);
    cont.appendChild(h('h4', { text: 'Los seis controles' }));
    cont.appendChild(listaControles(g));
    return cont;
  }

  // ---------------------------------------------------------------- resumen
  function pintarResumen() {
    var cont = vaciar($('resumen'));
    var cfg = estado.config || {};
    var act = estado.act || {};
    // 1. Escala vigente
    var g = grillaVigente();
    var t1 = h('div', { class: 'dato ok' }, h('div', { class: 'rotulo', text: 'Escala vigente' }));
    if (act.vigente) {
      t1.appendChild(h('div', { class: 'grande', text: periodoLindo(act.vigente) }));
      var linea = 'Publicada por el sindicato el ' + fechaCorta(act.vigente_publicada_sindicato || (g && g.publicada_sindicato)) + '.';
      if (g) linea += ' ' + (g.origen === 'semilla' ? 'Cargada a mano' : (g.origen === 'automatica' ? 'Cargada sola por el sistema' : 'Cargada a mano')) + ' el ' + fechaCorta(g.creada) + '.';
      t1.appendChild(h('p', null, linea));
      if (g) {
        var calc = (g.controles && g.controles.celdas_calculadas) || [];
        if (calc.length) t1.appendChild(h('p', { text: 'Incluye ' + calc.length + (calc.length === 1 ? ' celda calculada' : ' celdas calculadas') + ' (no leídas del PDF). Abrila en el historial para ver cuál.' }));
      }
      t1.appendChild(h('p', { text: 'Es la que usa hoy la Calculadora bancaria.' }));
    } else {
      t1.appendChild(h('div', { class: 'grande', text: 'Sin escala' }));
      t1.appendChild(h('p', { text: 'Todavía no hay ninguna grilla publicada.' }));
    }
    // 2. ¿Hay algo para hacer?
    var rets = retenidas();
    var t2 = h('div', { class: 'dato ' + (rets.length ? 'atencion' : 'ok') }, h('div', { class: 'rotulo', text: '¿Hay algo para hacer?' }));
    if (rets.length) {
      t2.appendChild(h('div', { class: 'grande', text: rets.length === 1 ? '1 grilla para revisar' : rets.length + ' grillas para revisar' }));
      t2.appendChild(h('p', null, h('strong', { text: rets.map(function (x) { return periodoLindo(x.periodo); }).join(', ') }), ' no se publicó: el sistema la frenó porque algo no cerró.'));
      t2.appendChild(h('a', { class: 'boton', href: '#revisar', text: 'Ir a revisar' }));
    } else {
      t2.appendChild(h('div', { class: 'grande', text: 'Nada pendiente' }));
      t2.appendChild(h('p', { text: 'No hay grillas esperando que alguien las resuelva.' }));
    }
    var cn = act.comunicado_nuevo;
    if (cn) {
      var yaLeida = rets.some(function (x) { return x.periodo === cn.periodo; });
      t2.appendChild(h('p', { style: 'margin-top:8px' }, h('strong', { text: 'Hay un comunicado nuevo: ' }),
        'el sindicato anunció el aumento de ' + periodoLindo(cn.periodo) + ' el ' + fechaCorta(cn.publicada) + ' y todavía no hay una grilla publicada de ese mes. '
        + (yaLeida ? 'Ya se leyó y espera tu revisión.' : 'El proceso todavía no la cargó.')));
    }
    // 3. Proceso diario
    var t3 = h('div', { class: 'dato ' + (cfg.auto ? 'ok' : '') }, h('div', { class: 'rotulo', text: 'Proceso diario' }));
    t3.appendChild(h('div', { class: 'grande', text: cfg.auto ? 'Prendido' : 'Apagado' }));
    t3.appendChild(h('p', { text: cfg.auto
      ? 'Revisa el sitio del sindicato todos los días a las ' + (cfg.horas || []).join(' y ') + ' (hora de Buenos Aires).'
      : 'No revisa el sitio solo. Para buscar una grilla nueva, usá «Buscar ahora» más abajo.' }));
    if (cfg.ia_disponible === false) t3.appendChild(h('p', { style: 'margin-top:6px', text: 'La lectura con IA no está disponible ahora: ' + (cfg.motivo_ia || 'sin motivo informado') + '.' }));
    cont.appendChild(t1); cont.appendChild(t2); cont.appendChild(t3);
  }

  // ---------------------------------------------------------------- para revisar
  function firmaRevisar() {
    return retenidas().map(function (g) { return g.id + ':' + g.creada + ':' + (g.nota || '').length + ':' + resultados(g).map(function (r) { return r.pasa; }).join(''); }).join('|');
  }
  function pintarRevisar(forzar) {
    var rets = retenidas();
    $('revisar').hidden = !rets.length;
    var firma = firmaRevisar();
    if (!forzar && firma === estado.firmaRevisar) return;
    estado.firmaRevisar = firma;
    var cont = vaciar($('revisar-lista'));
    rets.forEach(function (g) {
      var tarjeta = h('article', { class: 'tarjeta accion', id: 'revisar-' + g.id }, h('p', { class: 'vacio', text: 'Cargando ' + periodoLindo(g.periodo) + '…' }));
      cont.appendChild(tarjeta);
      cargarDetalle(g.id).then(function (d) { vaciar(tarjeta); tarjetaRevisar(tarjeta, d); })
        .catch(function (e) { vaciar(tarjeta); tarjeta.appendChild(h('p', { class: 'vacio', text: 'No se pudo abrir esta grilla: ' + e.message })); });
    });
  }

  function celdasEditables(g) {
    var et = etiquetasDe(g);
    var mapa = {}, orden = [];
    resultados(g).forEach(function (r) {
      (r.detalle || []).forEach(function (d) {
        if (!d || typeof d.ruta !== 'string' || et[d.ruta] === undefined) return;
        if (!mapa[d.ruta]) { mapa[d.ruta] = { ruta: d.ruta, etiqueta: et[d.ruta] || d.etiqueta || d.ruta, sugerido: null, parcial: [], problema: '' }; orden.push(d.ruta); }
        var c = mapa[d.ruta];
        if (esNum(d.calculado)) c.sugerido = d.calculado;
        else if (esNum(d.esperado) && c.sugerido === null) c.sugerido = d.esperado;
        (d.lectura_parcial || []).forEach(function (p) { if (c.parcial.indexOf(p) < 0) c.parcial.push(p); });
        if (d.problema && !/^D28/.test(d.problema) && !c.problema) c.problema = d.problema;
      });
    });
    return orden.map(function (k) { return mapa[k]; });
  }

  function accionFila(boton, texto) {
    var zona = h('div', { style: 'grid-column:1 / -1' });
    return { fila: h('div', { class: 'accion-fila' }, boton, h('p', { text: texto }), zona), zona: zona };
  }
  function pedirConfirmacion(zona, texto, etiqueta, fn, peligro) {
    vaciar(zona);
    var si = h('button', { type: 'button', class: 'boton' + (peligro ? ' peligro firme' : ''), text: etiqueta, onclick: function () { vaciar(zona); fn(); } });
    zona.appendChild(h('div', { class: 'confirmar' + (peligro ? '' : ' neutra'), role: 'alert' },
      h('span', { text: texto }), si, h('button', { type: 'button', class: 'boton claro', text: 'Cancelar', onclick: function () { vaciar(zona); } })));
    si.focus();
  }

  function tarjetaRevisar(tarjeta, g) {
    tarjeta.appendChild(h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center' },
      h('h3', { text: periodoLindo(g.periodo) }), pill('retenida', ESTADOS.retenida)));
    tarjeta.appendChild(h('p', { class: 'suave chico', style: 'margin-top:4px', text: 'Publicada por el sindicato el ' + fechaCorta(g.publicada_sindicato) + ' · leída por el sistema el ' + cuando(g.creada) + '.' }));

    tarjeta.appendChild(h('h4', { text: 'Por qué quedó retenida' }));
    var motivos = motivosDe(g);
    var ul = h('ul', { class: 'motivos' });
    motivos.forEach(function (m) {
      var li = h('li', null, h('b', { text: m.nombre }));
      m.lineas.forEach(function (l) { li.appendChild(h('p', { text: l })); });
      ul.appendChild(li);
    });
    if (!ul.firstChild) ul.appendChild(h('li', { text: 'Algún control no pasó. Mirá el detalle de cada control más abajo.' }));
    tarjeta.appendChild(ul);

    var celdas = celdasEditables(g);
    var pdf = enlace(g.fuente_pdf, 'Abrir el PDF');
    tarjeta.appendChild(h('h4', { text: 'Qué hay que hacer' }));
    var pasos = h('ol', { class: 'pasos' });
    pasos.appendChild(h('li', null, pdf ? pdf : 'Buscá el PDF de esta grilla en el sitio del sindicato', pdf ? ' (se abre en otra pestaña) y mirá ' : ' y mirá ', celdas.length ? 'el valor de ' + (celdas.length === 1 ? 'la celda marcada abajo' : 'las celdas marcadas abajo') + '.' : 'si el problema se ve en el documento.'));
    if (celdas.length) {
      pasos.appendChild(h('li', { text: 'Escribí el valor que ves en el campo de cada celda. Si no estás seguro, podés usar el valor que sugiere el cálculo.' }));
      pasos.appendChild(h('li', { text: 'Tocá «Guardar y volver a controlar». Si ahora pasan los controles, tocá «Publicar».' }));
    } else {
      pasos.appendChild(h('li', { text: 'Este problema no se arregla con una celda. Si la grilla está bien, publicala escribiendo en la nota por qué; si no, descartala.' }));
    }
    tarjeta.appendChild(pasos);

    var entradas = {};
    celdas.forEach(function (c) {
      var valores = planoValores(g.contenido || {});
      var actual = valores[c.ruta];
      var inp = h('input', { type: 'number', step: '0.01', inputmode: 'decimal', id: 'v-' + g.id + '-' + c.ruta, 'aria-label': 'Valor de ' + c.etiqueta });
      inp.value = actual === null || actual === undefined ? '' : String(actual);
      inp.setAttribute('data-original', inp.value);
      entradas[c.ruta] = inp;
      var form = h('div', { class: 'celda-form' },
        h('div', { class: 'nombre', text: c.etiqueta }),
        h('div', { class: 'ruta', text: c.parcial.length ? 'En el PDF se alcanza a ver: ' + c.parcial.join(' / ') : 'El sistema no pudo leer esta celda.' }));
      var fila = h('div', { class: 'fila-campo' }, h('label', { class: 'campo', for: inp.id, style: 'margin:0', text: 'Valor en pesos' }), inp);
      if (c.sugerido !== null) {
        fila.appendChild(h('button', { type: 'button', class: 'boton claro', text: 'Usar el valor del cálculo: ' + pesos(c.sugerido), onclick: function () { inp.value = String(c.sugerido); inp.focus(); } }));
      }
      form.appendChild(fila);
      if (c.sugerido !== null) form.appendChild(h('div', { class: 'ruta', style: 'margin-top:6px', text: 'El cálculo (valor vigente por el factor del mes) da ' + pesos(c.sugerido) + '. Comprobalo contra el PDF antes de usarlo.' }));
      tarjeta.appendChild(form);
    });

    tarjeta.appendChild(h('h4', { text: 'Nota' }));
    tarjeta.appendChild(h('label', { class: 'campo', for: 'nota-' + g.id, text: 'Para dejar constancia (obligatoria si publicás con controles que no pasan)' }));
    var nota = h('textarea', { id: 'nota-' + g.id, maxlength: '500' });
    tarjeta.appendChild(nota);

    var acc = h('div', { class: 'acciones' });
    var guardar = h('button', { type: 'button', class: 'boton', text: 'Guardar y volver a controlar', onclick: function () {
      var cambios = [];
      Object.keys(entradas).forEach(function (ruta) {
        var i = entradas[ruta];
        if (i.value !== i.getAttribute('data-original')) cambios.push({ ruta: ruta, valor: i.value === '' ? null : Number(i.value) });
      });
      if (!cambios.length) { aviso('No cambiaste ninguna celda.', 'info'); return; }
      pedir(API + '/grillas/' + g.id + '/corregir', { cuerpo: { cambios: cambios, nota: nota.value } })
        .then(function () { aviso('Correcciones guardadas. Se repitieron los controles: mirá cómo quedó.', 'verde'); delete estado.detalles[g.id]; return cargar(true); })
        .catch(function (e) { aviso(e.message, 'rojo'); });
    } });
    var a1 = accionFila(guardar, celdas.length ? 'Guarda lo que escribiste y repite los controles. No publica nada.' : 'Solo sirve cuando hay celdas para corregir.');
    if (!celdas.length) guardar.disabled = true;
    var publicar = h('button', { type: 'button', class: 'boton', text: 'Publicar', onclick: function () {
      pedirConfirmacion(a2.zona, '¿Publicar la grilla de ' + periodoLindo(g.periodo) + '? La Calculadora bancaria y la consulta de escalas pasan a usarla en seguida.', 'Sí, publicar', function () {
        pedir(API + '/grillas/' + g.id + '/publicar', { cuerpo: { nota: nota.value } })
          .then(function (r) { aviso('Grilla de ' + periodoLindo(g.periodo) + ' publicada' + (r && r.forzada ? ', con controles sin pasar (queda la constancia)' : '') + '.', 'verde'); return cargar(true); })
          .catch(function (e) { aviso(e.message, 'rojo'); });
      }, false);
    } });
    var a2 = accionFila(publicar, 'Pasa a ser la escala vigente. Si algún control sigue sin pasar, escribí en la nota por qué la publicás.');
    var releer = h('button', { type: 'button', class: 'boton claro', text: 'Volver a leer el PDF', onclick: function () {
      pedirConfirmacion(a3.zona, 'Vuelve a leer el PDF de ' + periodoLindo(g.periodo) + ' dos veces con la IA y gasta créditos. Esta grilla queda como está.', 'Sí, leer de nuevo', function () {
        pedir(API + '/buscar', { cuerpo: { periodo: g.periodo } })
          .then(function () { aviso('Lectura lanzada: tarda unos minutos. El avance se ve en «Acciones del equipo».', 'verde'); return cargar(true); })
          .catch(function (e) { aviso(e.message, 'rojo'); });
      }, false);
    } });
    var a3 = accionFila(releer, 'Útil si el PDF se leyó mal. Gasta IA y deja esta grilla como está.');
    var descartar = h('button', { type: 'button', class: 'boton peligro', text: 'Descartar', onclick: function () {
      pedirConfirmacion(a4.zona, '¿Descartar la grilla de ' + periodoLindo(g.periodo) + '? No se usa y queda registrado quién y cuándo. No se puede deshacer.', 'Sí, descartar', function () {
        pedir(API + '/grillas/' + g.id + '/descartar', { cuerpo: { nota: nota.value } })
          .then(function () { aviso('Grilla descartada.', 'verde'); return cargar(true); })
          .catch(function (e) { aviso(e.message, 'rojo'); });
      }, true);
    } });
    var a4 = accionFila(descartar, 'La saca de circulación (queda en el historial). Usalo si la nota del sitio no era una grilla real o está repetida.');
    [a1, a2, a3, a4].forEach(function (a) { acc.appendChild(a.fila); });
    tarjeta.appendChild(h('h4', { text: 'Qué querés hacer' }));
    tarjeta.appendChild(acc);

    var cuenta = bloqueCuenta(g);
    if (cuenta) tarjeta.appendChild(cuenta);
    tarjeta.appendChild(h('details', { class: 'plegable' }, h('summary', { text: 'Ver los seis controles' }), listaControles(g)));
  }

  function planoValores(obj, pref, out) {
    out = out || {};
    if (obj !== null && typeof obj === 'object') Object.keys(obj).forEach(function (k) { planoValores(obj[k], pref ? pref + '.' + k : k, out); });
    else out[pref] = obj;
    return out;
  }

  // ---------------------------------------------------------------- historial
  function cargarDetalle(id) {
    if (estado.detalles[id]) return Promise.resolve(estado.detalles[id]);
    return pedir(API + '/grillas/' + id).then(function (g) { estado.detalles[id] = g; return g; });
  }
  function resumenFila(g) {
    var a = aprobados(g);
    var partes = [origenTexto(g), 'cargada el ' + cuando(g.creada)];
    if (g.resuelta_por && g.estado !== 'retenida') partes.push('resuelta por ' + g.resuelta_por);
    if (a.total) partes.push(a.ok + ' de ' + a.total + ' controles pasan');
    return partes.join(' · ');
  }
  function filaGrilla(g, atenuada) {
    var li = h('li', { class: 'fila-grilla' + (atenuada ? ' atenuada' : ''), id: 'grilla-' + g.id });
    var abierta = estado.abierta === g.id;
    var panel = h('div', { id: 'panel-' + g.id, hidden: '' });
    var periodo = h('span', { class: 'periodo' }, periodoLindo(g.periodo), pill(g.estado, ESTADOS[g.estado] || g.estado));
    if (g.estado === 'publicada' && g.periodo === vigente()) periodo.appendChild(pill('vigente', 'Vigente'));
    var btn = h('button', { type: 'button', 'aria-expanded': abierta ? 'true' : 'false', 'aria-controls': 'panel-' + g.id },
      periodo, h('span', { class: 'quien', text: resumenFila(g) }), h('span', { class: 'chev', 'aria-hidden': 'true', text: '▾' }));
    btn.addEventListener('click', function () {
      if (estado.abierta === g.id) { estado.abierta = null; pintarHistorial(); return; }
      estado.abierta = g.id; pintarHistorial();
    });
    li.appendChild(btn);
    li.appendChild(panel);
    if (abierta) {
      panel.hidden = false;
      if (g.estado === 'retenida') {
        panel.appendChild(h('div', { class: 'cuerpo' }, h('p', { style: 'margin-top:12px' }, 'Esta grilla espera tu revisión. ', h('a', { href: '#revisar-' + g.id, text: 'Ir a la tarjeta de revisión' }), '.')));
      } else {
        panel.appendChild(h('div', { class: 'cuerpo' }, h('p', { class: 'vacio', text: 'Cargando…' })));
        cargarDetalle(g.id).then(function (d) {
          if (estado.abierta !== g.id) return;
          vaciar(panel); panel.appendChild(cuerpoGrilla(d));
        }).catch(function (e) { vaciar(panel); panel.appendChild(h('div', { class: 'cuerpo' }, h('p', { class: 'vacio', text: e.message }))); });
      }
    }
    return li;
  }
  function pintarHistorial() {
    var vis = vaciar($('historial'));
    var ant = vaciar($('anteriores-lista'));
    var vistas = 0, viejas = 0;
    estado.lista.forEach(function (g) {
      if (g.estado === 'descartada' || g.estado === 'reemplazada') { ant.appendChild(filaGrilla(g, true)); viejas++; }
      else { vis.appendChild(filaGrilla(g, false)); vistas++; }
    });
    if (!vistas) vis.appendChild(h('li', { class: 'vacio', text: 'Todavía no hay grillas.' }));
    $('anteriores').hidden = !viejas;
    $('anteriores-t').textContent = 'Ver anteriores (' + viejas + '): descartadas y reemplazadas';
    // si la abierta está entre las anteriores, se despliega esa sección
    var enAnt = estado.lista.some(function (g) { return g.id === estado.abierta && (g.estado === 'descartada' || g.estado === 'reemplazada'); });
    if (enAnt) $('anteriores').open = true;
  }

  // ---------------------------------------------------------------- tarea en curso
  function pintarTarea(t) {
    var el = $('tarea');
    if (!t) { el.hidden = true; return; }
    el.hidden = false;
    vaciar(el);
    var nombre = t.nombre === 'ensayo' ? 'El ensayo de lectura' : 'La búsqueda';
    if (t.estado === 'corriendo') {
      el.className = 'aviso info tarea';
      el.appendChild(h('strong', { text: nombre + ' está en curso' + (hora(t.desde) ? ' desde las ' + hora(t.desde) : '') + '.' }));
      el.appendChild(h('div', { text: ' Tarda unos minutos y esta pantalla se actualiza sola; podés dejarla abierta.' }));
      el.appendChild(h('div', { class: 'barra', 'aria-hidden': 'true' }, h('i')));
      return;
    }
    if (t.estado === 'error') {
      el.className = 'aviso rojo tarea';
      el.appendChild(h('strong', { text: nombre + ' falló. ' }));
      el.appendChild(document.createTextNode(String(t.error || '')));
      return;
    }
    var r = t.resultado || {};
    el.className = 'aviso verde tarea';
    el.appendChild(h('strong', { text: nombre + ' terminó' + (hora(t.hasta) ? ' a las ' + hora(t.hasta) : '') + '. ' }));
    var partes = [];
    if (r.ok === false) { el.className = 'aviso tarea'; partes.push('No se pudo completar: ' + (r.motivo || 'sin respuesta del sitio') + '. No se publicó nada.'); }
    else if (r.caso_id) partes.push('Ensayo #' + r.caso_id + ': ' + miles(r.distintas_a || 0) + ' celdas distintas en la primera lectura y ' + miles(r.distintas_b || 0) + ' en la segunda, de ' + miles(r.celdas || 0) + '. Abrilo en «Ensayos anteriores».');
    else if (r.leidas && r.leidas.length) partes.push(r.leidas.map(function (l) { return periodoLindo(l.periodo) + ': ' + (l.estado === 'publicada' ? 'se publicó' : (l.estado === 'retenida' ? 'quedó retenida para revisar' : (l.estado || 'sin resultado'))); }).join('; ') + '.');
    else partes.push('No había ninguna grilla nueva para leer, así que no se gastó IA.');
    if (r.mensajes && r.mensajes.length) partes.push(r.mensajes.join(' '));
    el.appendChild(document.createTextNode(partes.join(' ')));
  }

  // ---------------------------------------------------------------- ensayos
  function pintarEnsayos() {
    var ul = vaciar($('ensayos'));
    var sel = vaciar($('ensayo-periodo'));
    estado.lista.filter(function (g) { return g.estado === 'publicada'; }).forEach(function (g) {
      sel.appendChild(h('option', { value: g.periodo, text: periodoLindo(g.periodo) }));
    });
    if (!estado.ensayos.length) { ul.appendChild(h('li', { class: 'vacio', text: 'Todavía no se corrió ningún ensayo.' })); return; }
    estado.ensayos.forEach(function (e) {
      var abierto = estado.ensayoAbierto === e.id;
      var panel = h('div', { id: 'ens-' + e.id, hidden: '' });
      var tokens = e.ia ? miles((e.ia.tokens_entrada || 0) + (e.ia.tokens_salida || 0)) + ' unidades de texto' : '';
      var resumen = 'Celdas distintas de la publicada: ' + miles(e.distintas_a || 0) + ' en la primera lectura y ' + miles(e.distintas_b || 0) + ' en la segunda, de ' + miles(e.celdas || 0) + '.'
        + (tokens ? ' · ' + tokens : '');
      var btn = h('button', { type: 'button', 'aria-expanded': abierto ? 'true' : 'false', 'aria-controls': 'ens-' + e.id },
        h('span', { class: 'periodo' }, 'Ensayo #' + e.id + ' · ' + periodoLindo(e.periodo)),
        h('span', { class: 'quien', text: cuando(e.creado) + ' · ' + (e.quien || '') + ' · ' + resumen }),
        h('span', { class: 'chev', 'aria-hidden': 'true', text: '▾' }));
      btn.addEventListener('click', function () { estado.ensayoAbierto = abierto ? null : e.id; pintarEnsayos(); });
      var li = h('li', { class: 'fila-grilla' }, btn, panel);
      if (abierto) { panel.hidden = false; panel.appendChild(h('div', { class: 'cuerpo' }, h('p', { class: 'vacio', text: 'Cargando…' }))); abrirEnsayo(e.id, panel); }
      ul.appendChild(li);
    });
  }
  function abrirEnsayo(id, panel) {
    pedir(API + '/ensayos/' + id).then(function (e) {
      if (estado.ensayoAbierto !== id) return;
      var cont = h('div', { class: 'cuerpo' });
      var dif = e.diferencias || {};
      [['lectura_a', 'Primera lectura'], ['lectura_b', 'Segunda lectura']].forEach(function (par) {
        var l = dif[par[0]] || {};
        cont.appendChild(h('h4', { text: par[1] }));
        cont.appendChild(h('p', { text: miles(l.iguales || 0) + ' de ' + miles(l.celdas || 0) + ' celdas iguales a la publicada; ' + miles(l.distintas || 0) + ' distintas.' }));
        if ((l.detalle || []).length) {
          var tb = h('table', { class: 'tabla' }, h('thead', null, h('tr', null, h('th', { text: 'Celda' }), h('th', { class: 'der', text: 'Publicada' }), h('th', { class: 'der', text: 'Leída por la IA' }))));
          var cuerpo = h('tbody');
          l.detalle.forEach(function (d) {
            cuerpo.appendChild(h('tr', null, h('td', { text: d.etiqueta }), h('td', { class: 'der', text: esNum(d.publicada) ? pesos(d.publicada) : valorLindo('x', d.publicada) }),
              h('td', { class: 'der', text: esNum(d.leida) ? pesos(d.leida) : valorLindo('x', d.leida) })));
          });
          tb.appendChild(cuerpo);
          cont.appendChild(h('div', { class: 'scroll' }, tb));
        }
      });
      var ctl = (dif.controles || []);
      if (ctl.length) {
        cont.appendChild(h('h4', { text: 'Controles sobre lo que leyó' }));
        cont.appendChild(h('p', { text: ctl.map(function (r) { return (CONTROLES[r.control] ? CONTROLES[r.control].nombre : r.control) + ': ' + (r.pasa === true ? 'pasa' : (r.pasa === false ? 'no pasa' : 'no aplica')); }).join(' · ') }));
      }
      var notas = ((e.real || {}).notas || []);
      if (notas.length) {
        cont.appendChild(h('h4', { text: 'Comentarios de la IA al leer el PDF' }));
        var ul = h('ul', { style: 'padding-left:20px' });
        notas.forEach(function (n) { ul.appendChild(h('li', { text: String(n) })); });
        cont.appendChild(ul);
      }
      cont.appendChild(h('p', { class: 'suave chico', style: 'margin-top:10px', text: 'Duración: ' + ((e.real || {}).segundos != null ? numero(e.real.segundos, 1) + ' segundos' : '—') + '.' }));
      vaciar(panel); panel.appendChild(cont);
    }).catch(function (er) { vaciar(panel); panel.appendChild(h('div', { class: 'cuerpo' }, h('p', { class: 'vacio', text: er.message }))); });
  }

  // ---------------------------------------------------------------- sitio y datos técnicos
  function pintarNovedades() {
    var ul = vaciar($('novedades'));
    if (!estado.novedades.length) ul.appendChild(h('li', { class: 'vacio', text: 'Todavía no se vio nada en el sitio.' }));
    estado.novedades.forEach(function (n) {
      var titulo = enlace(n.url, n.titulo) || h('span', { text: n.titulo });
      var res = n.resultado ? (RESULTADOS_NOTA[n.resultado] || n.resultado) + (n.ultimo_error ? ': ' + n.ultimo_error : '') : 'Vista, sin novedades';
      var meta = (TIPOS_NOTA[n.tipo] || n.tipo) + ' · publicada el ' + fechaCorta(n.publicada) + (n.periodo ? ' · ' + periodoLindo(n.periodo) : '') + ' · ' + res
        + (n.tipo === 'grillas' && n.intentos ? ' · ' + n.intentos + (n.intentos === 1 ? ' lectura' : ' lecturas') : '');
      ul.appendChild(h('li', null, h('div', null, titulo), h('div', { class: 'meta', text: meta })));
    });
  }
  function pintarTecnico() {
    var dl = vaciar($('tecnico'));
    var cfg = estado.config || {};
    function par(k, v) { dl.appendChild(h('dt', { text: k })); dl.appendChild(h('dd', { text: v })); }
    par('Modelo de lectura', cfg.modelo || '—');
    par('Lectura con IA', cfg.ia_disponible ? 'disponible' : 'no disponible: ' + (cfg.motivo_ia || ''));
    par('Proceso diario', cfg.auto ? 'prendido' : 'apagado: ' + (cfg.motivo_auto || ''));
    var t = cfg.tolerancias || {};
    if (esNum(t.c4_pesos)) par('Diferencia aceptada', 'Se acepta hasta ' + pesos(t.c4_pesos) + ' de diferencia por importe al comparar con el comunicado y con el mes anterior.');
  }

  // ---------------------------------------------------------------- preguntas al convenio
  var RESULTADO_CONSULTA = { respondida: ['verde', 'Respondida'], fija: ['reemplazada', 'Respuesta fija'], error: ['descartada', 'Falló la IA'] };
  function pintarConsultas(d) {
    var ul = vaciar($('consultas-lista'));
    var c = (d && d.conteos) || {};
    $('consultas-conteos').textContent = (c.total || 0) + (c.total === 1 ? ' pregunta' : ' preguntas') + ' en total · '
      + (c.respondidas || 0) + ' respondidas · ' + (c.fijas || 0) + ' con la respuesta fija · ' + (c.errores || 0) + ' con error de la IA · '
      + 'enviadas para el sindicato: ' + (c.enviadas || 0) + '.';
    var lista = (d && d.consultas) || [];
    if (!lista.length) { ul.appendChild(h('li', { class: 'vacio', text: 'Todavía nadie envió una pregunta ni quedó sin respuesta.' })); return; }
    lista.forEach(function (q) {
      var r = RESULTADO_CONSULTA[q.resultado] || ['reemplazada', q.resultado || '—'];
      var cab = h('div', { class: 'periodo' });
      if (q.enviada) cab.appendChild(pill('retenida', 'Enviada para el sindicato'));
      cab.appendChild(pill(r[0] === 'verde' ? 'publicada' : r[0], r[1]));
      var meta = (q.enviada && q.enviada_en ? 'Enviada el ' + cuando(q.enviada_en) + ' · ' : '') + 'Hecha el ' + cuando(q.creada);
      var li = h('li', { class: 'tarjeta', style: 'margin:0' }, cab,
        h('p', { style: 'margin-top:8px;font-weight:600;overflow-wrap:anywhere', text: q.pregunta }),
        h('p', { class: 'suave chico', style: 'margin-top:4px', text: meta }));
      if (q.motivo && q.resultado !== 'respondida') li.appendChild(h('p', { class: 'suave chico', text: 'Motivo: ' + q.motivo }));
      ul.appendChild(li);
    });
  }
  function cargarConsultas() {
    return pedir(API + '/consultas').then(pintarConsultas).catch(function (e) {
      vaciar($('consultas-lista')).appendChild(h('li', { class: 'vacio', text: 'No se pudieron leer las preguntas: ' + e.message }));
    });
  }

  // ---------------------------------------------------------------- carga
  function cargar(forzar) {
    return pedir(API + '/grillas').then(function (d) {
      estado.lista = d.grillas; estado.ensayos = d.ensayos; estado.novedades = d.novedades;
      estado.act = d.actualizacion || {}; estado.config = d.config || {}; estado.tarea = d.tarea;
      pintarResumen(); pintarRevisar(!!forzar); pintarHistorial(); pintarTarea(d.tarea); pintarEnsayos(); pintarNovedades(); pintarTecnico();
      var corriendo = d.tarea && d.tarea.estado === 'corriendo';
      $('buscar').disabled = !!corriendo; $('ensayo').disabled = !!corriendo;
      if (corriendo && !timer) timer = setInterval(function () { cargar(false); }, 5000);
      if (!corriendo && timer) { clearInterval(timer); timer = null; }
    }).catch(function (e) { aviso(e.message, 'rojo'); });
  }

  $('buscar').addEventListener('click', function () {
    var p = $('buscar-periodo').value;
    var lanzar = function () {
      pedir(API + '/buscar', { cuerpo: p ? { periodo: p } : {} })
        .then(function () { aviso('Búsqueda lanzada: tarda unos minutos si hay una grilla nueva.', 'verde'); return cargar(false); })
        .catch(function (e) { aviso(e.message, 'rojo'); });
    };
    if (!p) { lanzar(); return; }
    pedirConfirmacion($('buscar-confirmar'), 'Vuelve a leer la nota de ' + periodoLindo(p) + ' dos veces con la IA y gasta créditos. ¿Seguir?', 'Sí, leer ' + periodoLindo(p), lanzar, false);
  });
  $('ensayo').addEventListener('click', function () {
    var p = $('ensayo-periodo').value;
    if (!p) { aviso('Elegí un mes que ya tenga grilla publicada.', 'rojo'); return; }
    pedirConfirmacion($('ensayo-confirmar'), 'El ensayo lee la nota de ' + periodoLindo(p) + ' dos veces con la IA (ocho llamadas) y gasta créditos. No publica nada. ¿Seguir?', 'Sí, lanzar el ensayo', function () {
      pedir(API + '/ensayo', { cuerpo: { periodo: p } })
        .then(function () { aviso('Ensayo lanzado: tarda unos minutos.', 'verde'); return cargar(false); })
        .catch(function (e) { aviso(e.message, 'rojo'); });
    }, false);
  });
  cargar(true);
  cargarConsultas();
})();
