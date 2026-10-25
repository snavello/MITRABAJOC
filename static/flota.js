/* La pastilla flotante de la sesión (Inicio / Salir) se corre al bajar.
   Pauta de SDN: Salir flota abajo, con su rótulo. Pero una pastilla fija
   tapa lo que pasa por debajo (en el teléfono, el botón "Subir un PDF"
   apenas se abre la app). Al bajar se va; al subir, al llegar al final o
   al recibir el foco del teclado, vuelve. Sin JS se queda quieta, como
   antes. Una sola implementación para las cuatro pantallas. */
(function () {
  var SEL = '.flota-sal, .flota-sesion, .pt-sesion, .pt-flota';
  // Solo las que flotan: en el teléfono la de la app va quieta en la barra
  // del nombre (ver trabajador.html).
  // Tampoco la que va anclada al pie del riel del panel (--flota-quieta):
  // ahí no tapa nada.
  var pastillas = Array.prototype.slice.call(document.querySelectorAll(SEL))
    .filter(function (p) {
      var c = getComputedStyle(p);
      return c.position === 'fixed' && c.getPropertyValue('--flota-quieta').trim() !== '1';
    });
  if (!pastillas.length) return;
  var quieto = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  pastillas.forEach(function (p) {
    p.style.transition = quieto ? 'opacity .01s' :
      'transform var(--mov-medio, 240ms) var(--ease-salida, cubic-bezier(.22,.61,.36,1)), opacity var(--mov-medio, 240ms) ease';
    p.addEventListener('focusin', function () { mostrar(true); });
  });
  var ultimo = window.scrollY, visible = true;
  function mostrar(si) {
    if (si === visible) return;
    visible = si;
    pastillas.forEach(function (p) {
      p.style.transform = si ? '' : 'translateY(calc(100% + 28px))';
      p.style.opacity = si ? '' : '0';
      p.style.pointerEvents = si ? '' : 'none';
    });
  }
  var pendiente = false;
  window.addEventListener('scroll', function () {
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(function () {
      pendiente = false;
      var y = window.scrollY, d = y - ultimo;
      var alFinal = window.innerHeight + y >= document.documentElement.scrollHeight - 8;
      if (y < 40 || alFinal || d < -6) mostrar(true);
      else if (d > 6) mostrar(false);
      ultimo = y;
    });
  }, { passive: true });
})();
