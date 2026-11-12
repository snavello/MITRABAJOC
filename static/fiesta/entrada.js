/* El ticket de la Fiesta: renueva el QR antes de que venza y comparte el enlace.
   Mismo mecanismo que la credencial del afiliado (trabajador.html, «QR
   efímero»): el servidor firma un código de 10 minutos; acá se pide uno nuevo
   unos segundos antes, y al volver a la pestaña. */
(function () {
  'use strict';
  var raiz = document.getElementById('entrada');
  if (!raiz) return;

  // ---------- QR que se renueva ----------
  var caja = document.getElementById('qr-caja');
  if (caja) {
    var leyenda = document.getElementById('qr-leyenda');
    var aro = document.getElementById('qr-aro');
    var avance = document.getElementById('qr-avance');
    var CIRC = 56.5, MARGEN = 20, renovando = false;
    var total = (parseInt(raiz.dataset.vence, 10) || 600) * 1000;
    var vence = Date.now() + total;

    var mmss = function (ms) {
      var t = Math.max(0, Math.round(ms / 1000));
      return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0');
    };
    var aLaVista = function () { return document.visibilityState === 'visible'; };

    async function renovar() {
      if (renovando) return;
      renovando = true;
      caja.classList.add('renovando');
      try {
        var r = await fetch(raiz.dataset.renovar, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
        if (!r.ok) throw new Error(r.status);
        var d = await r.json();
        if (typeof d.svg !== 'string' || !/^\s*<svg[\s>]/i.test(d.svg)) throw new Error('svg');
        var viejo = caja.querySelector('svg');
        if (viejo) viejo.remove();
        caja.insertAdjacentHTML('afterbegin', d.svg);     // SVG que arma el servidor, sin datos de personas
        total = (d.vence_en || 600) * 1000;
        vence = Date.now() + total;
      } catch (_) {
        // Sin conexión no se puede renovar: se conserva el QR (sigue valiendo
        // hasta que venza) y la leyenda avisa cuando llega a cero.
      } finally {
        renovando = false;
        caja.classList.remove('renovando');
      }
    }

    function tic() {
      var resta = vence - Date.now();
      var vencido = resta <= 0;
      aro.classList.toggle('vencido', vencido);
      leyenda.textContent = vencido ? 'Código vencido: actualizá la pantalla' : 'Se renueva en ' + mmss(resta);
      avance.style.strokeDashoffset = String(CIRC * (1 - Math.max(0, Math.min(1, resta / total))));
      if (resta <= MARGEN * 1000 && aLaVista()) renovar();
    }
    setInterval(tic, 1000);
    tic();
    document.addEventListener('visibilitychange', function () {
      if (aLaVista() && vence - Date.now() <= MARGEN * 1000) renovar();
    });
  }

  // ---------- Compartir enlace ----------
  var btn = document.getElementById('btn-compartir');
  if (btn) {
    var msg = document.getElementById('msg-compartir');
    var original = msg ? msg.textContent : '';
    btn.addEventListener('click', async function () {
      var datos = { title: raiz.dataset.titulo || 'Entrada', text: 'Mi entrada: ' + (raiz.dataset.titulo || ''), url: location.href };
      try {
        if (navigator.share) { await navigator.share(datos); return; }
      } catch (e) {
        if (e && e.name === 'AbortError') return;
      }
      try {
        await navigator.clipboard.writeText(location.href);
        if (msg) msg.textContent = 'Enlace copiado. Pegalo donde quieras guardarlo.';
      } catch (_) {
        if (msg) msg.textContent = 'Copiá el enlace desde la barra del navegador.';
      }
      if (msg) setTimeout(function () { msg.textContent = original; }, 4000);
    });
  }
})();
