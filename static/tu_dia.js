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
     noticia); tocar el clima, el pronóstico con su fuente.
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
        p.chip.textContent = it.chip || '';
        p.chip.classList.toggle('alerta', !!it.alerta);
        p.txt.textContent = it.linea || '';
        p.btn.setAttribute('aria-label', (it.chip ? it.chip + ': ' : '') + (it.linea || '') + '. Tocá para ver el detalle');
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
  function llenarHoja(chip, titulo, parrafos, fuente) {
    document.getElementById('td-det-chip').textContent = chip || '';
    document.getElementById('td-det-titulo').textContent = titulo || '';
    var t = document.getElementById('td-det-texto'); t.replaceChildren();
    (parrafos || []).forEach(function (x) { if (x) t.appendChild(el('p', null, x)); });
    document.getElementById('td-det-extra').replaceChildren();
    var f = document.getElementById('td-det-fuente');
    f.textContent = fuente ? 'Fuente: ' + fuente : ''; f.hidden = !fuente;
  }
  function mostrarHoja() {
    if (!ov) return;
    ov.classList.add('abierto'); abierta = true;
    var x = ov.querySelector('.modal-cerrar-clara'); if (x) x.focus();
  }
  function abrir(it) {
    if (!ov) return;
    llenarHoja(it.chip, it.titulo || it.linea, [it.texto], it.fuente);
    var extra = document.getElementById('td-det-extra');
    if (it.tabla && it.tabla.length) {
      var tabla = el('table', 'pt-dia-tabla');
      it.tabla.forEach(function (fila) {
        var tr = el('tr'); tr.append(el('td', null, fila[0]), el('td', null, fila[1])); tabla.appendChild(tr);
      });
      extra.appendChild(tabla);
    }
    if (it.opciones && it.opciones.length) {
      var ops = el('div', 'pt-dia-opciones'), res = el('p', 'pt-dia-respuesta');
      it.opciones.forEach(function (o, n) {
        var b = el('button', null, o); b.type = 'button';
        b.addEventListener('click', function () {
          Array.prototype.forEach.call(ops.children, function (x, k) {
            x.disabled = true; if (k === it.correcta) x.dataset.ok = 'si';
          });
          if (n !== it.correcta) b.dataset.ok = 'no';
          res.textContent = (n === it.correcta ? '¡Bien! ' : 'Era «' + it.opciones[it.correcta] + '». ') + (it.explicacion || '');
        });
        ops.appendChild(b);
      });
      extra.append(ops, res);
    }
    mostrarHoja();
  }
  function abrirClima() {
    var c = datos.clima;
    var parrafos = ['Ahora: ' + c.temp + '°, ' + (c.texto || '').toLowerCase() + '.'];
    (c.pronostico || []).forEach(function (p) {
      parrafos.push(p.dia.charAt(0).toUpperCase() + p.dia.slice(1) + ': máxima de ' + p.max + '°.');
    });
    llenarHoja('Clima', c.localidad ? 'El clima en ' + c.localidad : 'El clima', parrafos, c.fuente);
    mostrarHoja();
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
