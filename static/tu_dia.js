/* «Tu día» en la portada del afiliado (docs/chat/2026-10-24-pedido-tu-dia.md).

   La portada se dibuja sin esperar: este script pide /api/tu-dia y llena las
   dos franjas (.pt-dia-esc, a la derecha del saludo en escritorio; .pt-dia-tel,
   debajo de la tapa en el teléfono). Todo texto que viene del servidor va por
   textContent, nunca innerHTML.

   - La hora es la de Buenos Aires que manda el servidor; el reloj del
     dispositivo solo la hace avanzar (nunca es la fuente de la fecha).
   - La línea rota cada `intervalo` segundos y se pausa con el mouse encima,
     con el foco adentro, con la hoja abierta o con la pestaña oculta.
   - Tocar la línea abre la hoja de detalle (#overlay-tudia, familia de la
     noticia): un artículo corto (título, párrafos, enlace a la fuente); tocar
     el clima, el pronóstico con su fuente.
   - Entretenimiento es la trivia del día: diez preguntas de a una, con
     explicación y fuente en cada una, y el puntaje al final con su comentario
     (los textos los manda el servidor). El avance se guarda en localStorage
     POR DÍA, así una recarga retoma donde estaba y, terminada, la hoja muestra
     el resultado; mañana el kit es otro y arranca de cero.
   - El cumpleaños no rota: es un saludo de ocho segundos que se ve una sola
     vez (el servidor guarda el año en que se vio). */
(function () {
  'use strict';
  var franjas = Array.prototype.slice.call(document.querySelectorAll('.pt-dia'));
  if (!franjas.length) return;
  var SVG = 'http://www.w3.org/2000/svg';
  var DIAS = ['DOM', 'LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB'];
  var quieto = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var datos = null, items = [], i = 0, pausas = 0, abierta = false, ultimo = Date.now(), intervalo = 6;
  var desfase = 0, volverA = null;

  function ico(id, cls) {
    var s = document.createElementNS(SVG, 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
    if (cls) s.setAttribute('class', cls);
    var u = document.createElementNS(SVG, 'use'); u.setAttribute('href', '#ic-' + id);
    s.appendChild(u); return s;
  }
  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function ocultar() { franjas.forEach(function (f) { f.hidden = true; }); }

  function ahoraBA() { return new Date(Date.now() + desfase); }   // leer con getUTC*
  function horaTexto() {
    var d = ahoraBA();
    var h = String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0');
    return { h: h, f: DIAS[d.getUTCDay()] + ' ' + d.getUTCDate() + '/' + (d.getUTCMonth() + 1) };
  }

  // El servidor dice "mañana" para el día siguiente y "lun", "mar"… para los
  // demás: acá van todos con la misma abreviatura de la fecha ("DOM").
  function diaCorto(dia) {
    if (dia === 'mañana') return DIAS[(ahoraBA().getUTCDay() + 1) % 7];
    return String(dia || '').toUpperCase();
  }

  function construir(aside) {
    var esc = aside.classList.contains('pt-dia-esc');
    aside.classList.remove('cargando');
    aside.replaceChildren();
    var partes = {};
    if (esc) {
      var hora = el('div', 'pt-dia-hora'); partes.h = el('span', 'pt-dia-h'); partes.f = el('span', 'pt-dia-f');
      hora.append(partes.h, partes.f); aside.append(hora, el('span', 'pt-dia-sep'));
    }
    var c = datos.clima;
    if (c) {
      var btnC = el('button', 'pt-dia-clima'); btnC.type = 'button';
      var frase = (c.localidad ? c.localidad + ': ' : '') + c.temp + ' grados, ' + (c.texto || '').toLowerCase() + '.';
      (c.pronostico || []).forEach(function (p) { frase += ' ' + p.dia.charAt(0).toUpperCase() + p.dia.slice(1) + ' ' + p.max + '.'; });
      btnC.setAttribute('aria-label', frase + ' Tocá para ver el pronóstico');
      var ic = el('span', 'pt-dia-ico'); ic.appendChild(ico('clima-' + (c.icono || 'nublado')));
      if (datos.alerta) { var punto = el('span', 'pt-dia-punto'); punto.appendChild(ico('alerta')); ic.appendChild(punto); }
      btnC.append(ic, el('span', 'pt-dia-temp', c.temp + '°'));
      // Auditoría G2-03: cada máxima lleva su día escrito («DOM 20°»), como
      // la fecha de la hora; en un title no lo ve nadie con el dedo.
      if (esc) (c.pronostico || []).forEach(function (p) {
        var x = el('span', 'pt-dia-pron');
        x.append(el('span', 'pt-dia-pron-d', diaCorto(p.dia)), ico('clima-' + p.icono),
                 document.createTextNode(p.max + '°'));
        btnC.appendChild(x);
      });
      btnC.addEventListener('click', function () { volverA = btnC; abrirClima(); });
      aside.appendChild(btnC);
    }
    if (items.length) {
      if (c) aside.appendChild(el('span', 'pt-dia-sep'));
      var btn = el('button', 'pt-dia-linea'); btn.type = 'button';
      var cuerpo = el('span', 'pt-dia-cuerpo'), chip = el('span', 'pt-dia-chip'), txt = el('span', 'pt-dia-texto');
      cuerpo.append(chip, txt); btn.append(cuerpo, ico('chevron', 'pt-dia-flecha'));
      btn.addEventListener('click', function () { volverA = btn; abrir(items[i % items.length]); });
      aside.appendChild(btn);
      partes.btn = btn; partes.cuerpo = cuerpo; partes.chip = chip; partes.txt = txt;
    }
    ['mouseenter', 'focusin'].forEach(function (ev) { aside.addEventListener(ev, function () { pausas++; }); });
    ['mouseleave', 'focusout'].forEach(function (ev) { aside.addEventListener(ev, function () { pausas = Math.max(0, pausas - 1); }); });
    aside._td = partes;
  }

  function ponerHora() {
    var t = horaTexto();
    franjas.forEach(function (f) { var p = f._td; if (p && p.h) { p.h.textContent = t.h; p.f.textContent = t.f; } });
  }

  function pintar(animar) {
    if (!items.length) return;
    var it = items[i % items.length];
    franjas.forEach(function (f) {
      var p = f._td; if (!p || !p.cuerpo) return;
      function poner() {
        var linea = it.preguntas ? lineaTrivia(it) : (it.linea || '');
        p.chip.textContent = it.chip || '';
        p.chip.classList.toggle('alerta', !!it.alerta);
        p.txt.textContent = linea;
        p.btn.setAttribute('aria-label', (it.chip ? it.chip + ': ' : '') + linea + '. Tocá para ver el detalle');
      }
      if (!animar) { poner(); return; }
      p.cuerpo.classList.remove('entra'); p.cuerpo.classList.add('sale');
      setTimeout(function () {
        poner(); p.cuerpo.classList.remove('sale'); void p.cuerpo.offsetWidth; p.cuerpo.classList.add('entra');
      }, quieto ? 160 : 300);
    });
  }

  function tic() {
    ponerHora();
    if (pausas > 0 || abierta || document.hidden || items.length < 2) { ultimo = Date.now(); return; }
    if (Date.now() - ultimo >= intervalo * 1000) { ultimo = Date.now(); i++; pintar(true); }
  }

  // ---------- Hoja de detalle ----------
  var ov = document.getElementById('overlay-tudia');
  function esUrl(u) { return typeof u === 'string' && u.indexOf('https://') === 0; }
  function enlaceFuente(fuente, url) {
    // "Fuente: <nombre>", con el nombre como enlace si hay url (se abre aparte).
    var f = document.createDocumentFragment();
    if (!fuente && !esUrl(url)) return f;
    f.appendChild(document.createTextNode('Fuente: '));
    if (esUrl(url)) {
      var a = el('a', 'pt-dia-enlace', fuente || url);
      a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      a.appendChild(ico('externo', 'pt-dia-ext'));
      f.appendChild(a);
    } else {
      f.appendChild(document.createTextNode(fuente));
    }
    return f;
  }
  function llenarHoja(chip, titulo, parrafos, fuente, url) {
    document.getElementById('td-det-chip').textContent = chip || '';
    document.getElementById('td-det-titulo').textContent = titulo || '';
    var t = document.getElementById('td-det-texto'); t.replaceChildren();
    (parrafos || []).forEach(function (x) { if (x) t.appendChild(el('p', null, x)); });
    document.getElementById('td-det-extra').replaceChildren();
    var f = document.getElementById('td-det-fuente'); f.replaceChildren();
    f.appendChild(enlaceFuente(fuente, url));
    f.hidden = !(fuente || esUrl(url));
  }
  function mostrarHoja() {
    if (!ov) return;
    ov.classList.add('abierto'); abierta = true;
    var x = ov.querySelector('.modal-cerrar-clara'); if (x) x.focus();
  }
  function abrir(it) {
    if (!ov) return;
    if (it.preguntas && it.preguntas.length) { abrirTrivia(it); return; }
    var parrafos = (it.parrafos && it.parrafos.length) ? it.parrafos : [it.texto];
    llenarHoja(it.chip, it.titulo || it.linea, parrafos, it.fuente, it.url);
    var extra = document.getElementById('td-det-extra');
    if (it.tabla && it.tabla.length) {
      var tabla = el('table', 'pt-dia-tabla');
      it.tabla.forEach(function (fila) {
        var tr = el('tr'); tr.append(el('td', null, fila[0]), el('td', null, fila[1])); tabla.appendChild(tr);
      });
      extra.appendChild(tabla);
    }
    mostrarHoja();
  }
  function abrirClima() {
    var c = datos.clima;
    var parrafos = ['Ahora: ' + c.temp + '°, ' + (c.texto || '').toLowerCase() + '.'];
    (c.pronostico || []).forEach(function (p) {
      parrafos.push(p.dia.charAt(0).toUpperCase() + p.dia.slice(1) + ': máxima de ' + p.max + '°.');
    });
    llenarHoja('Clima', c.localidad ? 'El clima en ' + c.localidad : 'El clima', parrafos, c.fuente, c.url);
    mostrarHoja();
  }

  // ---------- La trivia del día ----------
  var CLAVE_TRIVIA = 'tudia_trivia';
  var NIVELES = { facil: 'Fácil', media: 'Media', dificil: 'Difícil' };
  function diaDeHoy() { return (datos && datos.hora_ba ? datos.hora_ba : '').slice(0, 10); }
  function leerAvance(it) {
    // Solo vale el avance de HOY sobre ESTAS preguntas: mañana el kit es otro.
    var g = null;
    try { g = JSON.parse(localStorage.getItem(CLAVE_TRIVIA) || 'null'); } catch (e) { g = null; }
    var ids = it.preguntas.map(function (q) { return q.id; }).join(',');
    if (!g || g.dia !== diaDeHoy() || g.ids !== ids || !Array.isArray(g.respuestas)) {
      g = { dia: diaDeHoy(), ids: ids, respuestas: [] };
    }
    return g;
  }
  function guardarAvance(g) { try { localStorage.setItem(CLAVE_TRIVIA, JSON.stringify(g)); } catch (e) { /* sin memoria: se juega igual */ } }
  function aciertos(it, g) {
    var n = 0;
    g.respuestas.forEach(function (r, k) { if (it.preguntas[k] && r === it.preguntas[k].correcta) n++; });
    return n;
  }
  function lineaTrivia(it) {
    var g = leerAvance(it), total = it.preguntas.length;
    if (g.respuestas.length >= total) return 'Trivia de hoy: sacaste ' + aciertos(it, g) + ' de ' + total + '. Tocá para repasar';
    if (g.respuestas.length) return 'Trivia de hoy: vas por la pregunta ' + (g.respuestas.length + 1) + ' de ' + total;
    return it.linea || '';
  }
  function puntos(it, g, actual) {
    var p = el('span', 'pt-triv-puntos'); p.setAttribute('aria-hidden', 'true');
    it.preguntas.forEach(function (q, k) {
      var i = el('i');
      if (k < g.respuestas.length) i.dataset.r = g.respuestas[k] === q.correcta ? 'si' : 'no';
      if (k === actual) i.className = 'actual';
      p.appendChild(i);
    });
    return p;
  }
  function abrirTrivia(it) {
    llenarHoja(it.chip, it.titulo, [], '', '');
    var g = leerAvance(it);
    if (g.respuestas.length >= it.preguntas.length) resultadoTrivia(it, g, false);
    else preguntaTrivia(it, g);
    mostrarHoja();
  }
  function preguntaTrivia(it, g) {
    var k = g.respuestas.length, q = it.preguntas[k], total = it.preguntas.length;
    var extra = document.getElementById('td-det-extra'); extra.replaceChildren();
    var caja = el('div', 'pt-triv-caja entra');
    var cab = el('div', 'pt-triv-cab');
    var num = el('span', null, 'Pregunta ' + (k + 1) + ' de ' + total);
    cab.append(num, puntos(it, g, k));
    if (NIVELES[q.nivel]) cab.appendChild(el('span', 'pt-triv-nivel', NIVELES[q.nivel]));
    var preg = el('h4', 'pt-triv-preg', q.titulo);
    var ops = el('div', 'pt-dia-opciones'), res = el('div', 'pt-dia-respuesta'), pie = el('div', 'pt-triv-sig');
    res.hidden = true; pie.hidden = true;
    q.opciones.forEach(function (o, n) {
      var b = el('button', null, o); b.type = 'button';
      b.addEventListener('click', function () {
        if (g.respuestas.length !== k) return;
        g.respuestas.push(n); guardarAvance(g);
        Array.prototype.forEach.call(ops.children, function (x, j) { x.disabled = true; if (j === q.correcta) x.dataset.ok = 'si'; });
        if (n !== q.correcta) b.dataset.ok = 'no';
        var ok = n === q.correcta;
        res.replaceChildren(el('b', null, ok ? '¡Bien! ' : 'Era «' + q.opciones[q.correcta] + '». '),
                            document.createTextNode(q.explicacion || ''));
        if (q.fuente || esUrl(q.url)) { var f = el('div', 'pt-triv-fuente'); f.appendChild(enlaceFuente(q.fuente, q.url)); res.appendChild(f); }
        res.hidden = false; pie.hidden = false;
        cab.replaceChild(puntos(it, g, k), cab.children[1]);
        var sig = pie.querySelector('button'); if (sig) sig.focus();
        pintar(false);
      });
      ops.appendChild(b);
    });
    var sig = el('button', null, k + 1 < total ? 'Siguiente' : 'Ver mi puntaje'); sig.type = 'button';
    sig.addEventListener('click', function () {
      if (g.respuestas.length < total) preguntaTrivia(it, g); else resultadoTrivia(it, g, true);
    });
    pie.appendChild(sig);
    caja.append(cab, preg, ops, res, pie);
    extra.appendChild(caja);
    var cuerpo = ov.querySelector('.modal-articulo-body'); if (cuerpo) cuerpo.scrollTop = 0;
  }
  function resultadoTrivia(it, g, recien) {
    var total = it.preguntas.length, n = aciertos(it, g);
    var c = (it.comentarios || [])[n] || { titulo: n + ' de ' + total, texto: '' };
    var extra = document.getElementById('td-det-extra'); extra.replaceChildren();
    var fin = el('div', 'pt-triv-fin entra');
    var num = el('div', 'pt-triv-num'); var cifra = el('span', null, recien && !quieto ? '0' : String(n));
    num.append(cifra, el('small', null, ' / ' + total));
    num.setAttribute('aria-label', 'Sacaste ' + n + ' de ' + total);
    fin.append(num, puntos(it, g, -1), el('div', 'pt-triv-t', c.titulo), el('p', 'pt-triv-x', c.texto),
               el('p', 'pt-triv-manana', 'La trivia se renueva cada madrugada: mañana hay ' + total + ' preguntas nuevas.'));
    var repaso = el('div', 'pt-triv-repaso');
    it.preguntas.forEach(function (q, k) {
      var d = el('details'); d.dataset.r = g.respuestas[k] === q.correcta ? 'si' : 'no';
      var sm = el('summary', null, q.titulo); d.appendChild(sm);
      var cuerpo = el('div', 'pt-triv-rep-cuerpo');
      if (g.respuestas[k] !== q.correcta) cuerpo.appendChild(el('p', null, 'Respondiste «' + q.opciones[g.respuestas[k]] + '». Era «' + q.opciones[q.correcta] + '».'));
      else cuerpo.appendChild(el('p', null, '«' + q.opciones[q.correcta] + '», correcto.'));
      cuerpo.appendChild(el('p', null, q.explicacion || ''));
      if (q.fuente || esUrl(q.url)) { var f = el('div', 'pt-triv-fuente'); f.appendChild(enlaceFuente(q.fuente, q.url)); cuerpo.appendChild(f); }
      d.appendChild(cuerpo); repaso.appendChild(d);
    });
    var ver = el('button', 'pt-triv-ver', 'Repasar las ' + total + ' preguntas'); ver.type = 'button';
    repaso.hidden = true;
    ver.addEventListener('click', function () { repaso.hidden = !repaso.hidden; ver.textContent = repaso.hidden ? 'Repasar las ' + total + ' preguntas' : 'Ocultar el repaso'; });
    fin.append(ver, repaso);
    extra.appendChild(fin);
    if (recien && !quieto) correr(cifra, n, 1200);
    pintar(false);
    var cuerpo2 = ov.querySelector('.modal-articulo-body'); if (cuerpo2) cuerpo2.scrollTop = 0;
  }
  function correr(nodo, hasta, ms) {
    // El puntaje corre hasta su número (mismo gesto que los indicadores del Panel).
    var t0 = null;
    function paso(t) {
      if (t0 === null) t0 = t;
      var x = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - x, 3);
      nodo.textContent = String(Math.round(hasta * e));
      if (x < 1) requestAnimationFrame(paso);
    }
    requestAnimationFrame(paso);
  }
  window.cerrarTuDia = function () {
    if (!ov || !abierta) return;
    ov.classList.remove('abierto'); abierta = false;
    i++; pintar(false); ultimo = Date.now();
    if (volverA) volverA.focus();
  };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && abierta) window.cerrarTuDia(); });

  // ---------- El saludo de cumpleaños ----------
  function cumple(c) {
    var capa = document.getElementById('pt-cumple');
    if (!capa) return;
    document.getElementById('pt-cumple-nombre').textContent = c.nombre || '';
    capa.hidden = false;
    // Se ve una sola vez: se avisa apenas aparece.
    fetch('/api/tu-dia/cumple-visto', { method: 'POST', credentials: 'same-origin' }).catch(function () {});
    var parar = quieto ? function () {} : papelitos(capa.querySelector('canvas'));
    var cerrado = false;
    function cerrar() {
      if (cerrado) return; cerrado = true; parar();
      capa.classList.add('sale');
      setTimeout(function () { capa.hidden = true; }, quieto ? 150 : 420);
    }
    document.getElementById('pt-cumple-x').addEventListener('click', cerrar);
    capa.addEventListener('click', function (e) { if (e.target === capa) cerrar(); });
    setTimeout(cerrar, 8000);
  }
  function papelitos(canvas) {
    if (!canvas || !canvas.getContext) return function () {};
    var ctx = canvas.getContext('2d'), w = 0, h = 0, raf = 0, vivo = true;
    var css = getComputedStyle(document.documentElement);
    var colores = ['--marca-acento', '--marca-primario', '--marca-apoyo', '--marca-base']
      .map(function (v) { return css.getPropertyValue(v).trim(); }).filter(Boolean).concat(['#ffffff', '#f5a623']);
    function medir() { w = canvas.width = window.innerWidth; h = canvas.height = window.innerHeight; }
    medir(); window.addEventListener('resize', medir);
    var p = [];
    for (var k = 0; k < 140; k++) p.push({
      x: Math.random() * w, y: -20 - Math.random() * h * 0.6, vx: (Math.random() - .5) * 2.2, vy: 2 + Math.random() * 3,
      r: Math.random() * Math.PI, vr: (Math.random() - .5) * .2, s: 6 + Math.random() * 7, c: colores[k % colores.length]
    });
    (function cuadro() {
      if (!vivo) return;
      ctx.clearRect(0, 0, w, h);
      p.forEach(function (q) {
        q.x += q.vx; q.y += q.vy; q.r += q.vr; q.vy += .015;
        if (q.y > h + 20) { q.y = -20; q.x = Math.random() * w; q.vy = 2 + Math.random() * 3; }
        ctx.save(); ctx.translate(q.x, q.y); ctx.rotate(q.r); ctx.fillStyle = q.c;
        ctx.fillRect(-q.s / 2, -q.s / 4, q.s, q.s / 2); ctx.restore();
      });
      raf = requestAnimationFrame(cuadro);
    })();
    return function () { vivo = false; cancelAnimationFrame(raf); window.removeEventListener('resize', medir); };
  }

  // ---------- Arranque ----------
  fetch('/api/tu-dia', { credentials: 'same-origin' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) { ocultar(); return; }
      datos = d; intervalo = d.intervalo || 6;
      var base = Date.parse((d.hora_ba || '') + 'Z');
      desfase = isNaN(base) ? 0 : base - Date.now();
      items = (d.alerta ? [{ alerta: true, chip: 'Alerta', linea: d.alerta.texto, titulo: 'Alerta ' + (d.alerta.nivel || ''),
        texto: d.alerta.texto, fuente: d.alerta.fuente }] : []).concat(d.items || []);
      if (d.cumple) cumple(d.cumple);
      if (!d.clima && !items.length) { ocultar(); return; }
      franjas.forEach(construir);
      ponerHora(); pintar(false);
      setInterval(tic, 500);
    })
    .catch(ocultar);
})();
