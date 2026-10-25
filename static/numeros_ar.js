/* Números en formato argentino para el panel del sindicato.

   Auditoría de diseño 2026-10 (G4-35): el panel mostraba los números como los
   guarda la base («$1.0», «2.5%», «2026-09», el CUIL sin guiones, «1583
   recibos»). Es el espejo en el navegador de formato_ar.py, con las mismas
   reglas: solo da forma al mostrar, nunca cambia lo que se manda al servidor.
   Un valor que no se entiende vuelve tal cual (o «—» si es un importe:
   nunca «$ 0,00»). */
(function () {
  'use strict';
  var MESES = ['ene.', 'feb.', 'mar.', 'abr.', 'may.', 'jun.', 'jul.', 'ago.',
               'sep.', 'oct.', 'nov.', 'dic.'];

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  function miles(v, decimales) {
    var n = num(v);
    if (n === null) return v == null ? '' : String(v);
    var d = decimales || 0;
    return n.toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function pesos(v) {
    var n = num(v);
    if (n === null) return '—';
    return (n < 0 ? '-' : '') + '$ ' + miles(Math.abs(n), 2);
  }
  function porcentaje(v, decimales) {
    var n = num(v);
    if (n === null) return v == null ? '' : String(v);
    var t = miles(n, decimales == null ? 1 : decimales);
    if (t.indexOf(',') >= 0) t = t.replace(/0+$/, '').replace(/,$/, '');
    return t + '%';
  }
  function periodo(p) {
    var m = /^(\d{4})-(\d{2})$/.exec(String(p || '').trim());
    if (!m || +m[2] < 1 || +m[2] > 12) return p || '';
    return MESES[+m[2] - 1] + ' ' + m[1];
  }
  function cuil(v) {
    var d = String(v || '').replace(/\D/g, '');
    if (d.length !== 11) return v == null ? '' : String(v);
    return d.slice(0, 2) + '-' + d.slice(2, 10) + '-' + d.slice(10);
  }
  function contar(n, singular, plural) {
    return miles(n) + ' ' + (Number(n) === 1 ? singular : plural);
  }
  /* «‹ Anterior · 1–50 de 1.583 · Siguiente ›» (G4-10). `fn` es el nombre de
     una función global que recibe el número de página. Sin más de una
     página no dibuja nada: no hay a dónde ir. */
  function paginador(pagina, paginas, total, porPagina, fn) {
    if (paginas <= 1) return '';
    var desde = (pagina - 1) * porPagina + 1, hasta = Math.min(total, pagina * porPagina);
    return '<button type="button" class="sec mini" ' + (pagina <= 1 ? 'disabled' : '') +
        ' onclick="' + fn + '(' + (pagina - 1) + ')">‹ Anterior</button>' +
      '<span class="lista-tramo">' + miles(desde) + '–' + miles(hasta) + ' de ' + miles(total) + '</span>' +
      '<button type="button" class="sec mini" ' + (pagina >= paginas ? 'disabled' : '') +
        ' onclick="' + fn + '(' + (pagina + 1) + ')">Siguiente ›</button>';
  }
  window.NumAR = { miles: miles, pesos: pesos, porcentaje: porcentaje, periodo: periodo,
                   cuil: cuil, contar: contar, paginador: paginador };
})();
