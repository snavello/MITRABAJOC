/* Modales que se pueden mover, en escritorio.

   Los modales de la app están fijos: el de perfil tapa justo la parte de la
   portada que uno quiere mirar mientras lo llena, y el de un trámite tapa la
   tabla desde la que se abrió. En un teléfono eso da igual (el modal ocupa la
   pantalla entera y no hay nada atrás que mirar), pero en escritorio sobra
   lugar al costado. Pedido de Sd el 2026-09-13, para TODOS los modales.

   Cómo está hecho, y por qué así:

   - **Un solo archivo compartido, cargado por las siete pantallas con
     modales.** La alternativa era repetir el arrastre en cada plantilla, que
     es como terminan tres modales moviéndose y el cuarto no.
   - **Delegado en `document`**, no enganchado modal por modal: los modales de
     esta app se llenan con innerHTML (el detalle de un trámite, el de un
     recibo, el "Ver" del panel), así que cualquier enganche al abrir se
     perdería en el siguiente repintado.
   - **Solo con mouse y pantalla ancha.** En un teléfono el modal es una hoja
     pegada abajo: moverla no tiene sentido y competiría con el scroll del
     contenido.
   - **La posición se resetea al cerrar.** Si quedara guardada, alguien que
     dejó el modal en un costado lo abre la próxima vez ahí y no entiende por
     qué "apareció raro". Y si lo hubiera dejado casi afuera, encima no lo
     encontraría.
   - **El agarre es el encabezado o el título**, nunca la caja entera: un
     modal que se mueve al arrastrar cualquier parte hace imposible
     seleccionar texto adentro.

   No toca nada del HTML de las plantillas: si este archivo no carga, los
   modales siguen funcionando como siempre, quietos. */
(function () {
  "use strict";

  // Las cajas de modal de toda la app. `.modal-recibo-card` NO está: es una
  // tarjeta de contenido ADENTRO de un modal, no un modal.
  var CAJAS = ".modal-hoja, .modal-notif-caja, .modal-articulo, .modal-recibo, .modal-det";
  // De qué se agarra. Los encabezados propios de cada familia de modal, y el
  // título para los que no tienen encabezado (el "Acerca de", el "Ver" del
  // Panel Sindical).
  var AGARRES = ".modal-notif-enc, .modal-articulo-enc, .modal-recibo-enc, h3";
  // Nada de esto arrastra: son cosas para tocar, y varias viven dentro del
  // encabezado (la X de cerrar, el botón de un filtro).
  var INTERACTIVOS = "button, a, input, select, textarea, label, [contenteditable]";
  var FONDOS = ".overlay, .modal-recibo-overlay, .overlay-det";

  var escritorio = window.matchMedia("(min-width: 700px) and (pointer: fine)");
  var movidas = [];  // cajas que se movieron, para reacomodarlas si cambia la ventana

  function trasladar(caja, x, y) {
    caja.dataset.movX = x;
    caja.dataset.movY = y;
    caja.style.transform = (x || y) ? "translate(" + x + "px," + y + "px)" : "";
    if (x || y) {
      if (movidas.indexOf(caja) < 0) movidas.push(caja);
    }
  }

  function resetear(caja) {
    delete caja.dataset.movX;
    delete caja.dataset.movY;
    caja.style.transform = "";
    var i = movidas.indexOf(caja);
    if (i >= 0) movidas.splice(i, 1);
  }

  /* **El modal no se sale de la pantalla.** Primero se probó dejando asomar
     solo un borde, y el resultado fue que arrastrándolo a la derecha la X de
     cerrar quedaba afuera: el modal seguía ahí y no había forma de cerrarlo
     sin volver a traerlo. Así que entra entero.

     El caso raro es un modal MÁS GRANDE que la ventana (uno muy alto en una
     pantalla baja): ahí los límites se invierten y se lo puede correr para
     ver la parte que no se ve, pero nunca dejando un hueco entre el modal y
     el borde. */
  function acotar(izq, arr, ancho, alto) {
    var vw = window.innerWidth, vh = window.innerHeight;
    var maxIzq = Math.max(0, vw - ancho), minIzq = Math.min(0, vw - ancho);
    var maxArr = Math.max(0, vh - alto), minArr = Math.min(0, vh - alto);
    return {
      izq: Math.min(Math.max(izq, minIzq), maxIzq),
      arr: Math.min(Math.max(arr, minArr), maxArr)
    };
  }

  /* Al cerrarse el modal, la posición vuelve al lugar de siempre. Se observa
     el FONDO (que es quien pierde la clase `abierto`) y una sola vez por
     modal arrastrado. */
  function vigilarCierre(caja) {
    var fondo = caja.closest(FONDOS);
    if (!fondo || fondo.dataset.vigilado) return;
    fondo.dataset.vigilado = "1";
    new MutationObserver(function () {
      if (!fondo.classList.contains("abierto")) {
        fondo.querySelectorAll(CAJAS).forEach(resetear);
      }
    }).observe(fondo, { attributes: true, attributeFilter: ["class"] });
  }

  document.addEventListener("pointerdown", function (ev) {
    if (!escritorio.matches || ev.button !== 0) return;
    var blanco = ev.target;
    if (!blanco || !blanco.closest) return;
    if (blanco.closest(INTERACTIVOS)) return;
    var agarre = blanco.closest(AGARRES);
    if (!agarre) return;
    var caja = agarre.closest(CAJAS);
    if (!caja) return;

    var r = caja.getBoundingClientRect();
    var x0 = parseFloat(caja.dataset.movX || 0), y0 = parseFloat(caja.dataset.movY || 0);
    var izq0 = r.left, arr0 = r.top, ancho = r.width, alto = r.height;
    var px = ev.clientX, py = ev.clientY;
    vigilarCierre(caja);
    caja.style.cursor = "grabbing";
    // Sin esto el arrastre selecciona el texto del título y el cursor
    // parpadea entre "mover" y "seleccionar".
    ev.preventDefault();

    function mover(e) {
      var p = acotar(izq0 + (e.clientX - px), arr0 + (e.clientY - py), ancho, alto);
      trasladar(caja, x0 + (p.izq - izq0), y0 + (p.arr - arr0));
    }
    function soltar() {
      document.removeEventListener("pointermove", mover);
      document.removeEventListener("pointerup", soltar);
      document.removeEventListener("pointercancel", soltar);
      caja.style.cursor = "";
    }
    document.addEventListener("pointermove", mover);
    document.addEventListener("pointerup", soltar);
    document.addEventListener("pointercancel", soltar);
  });

  // Achicar la ventana no puede dejar un modal afuera. Y al pasar a ancho de
  // teléfono se vuelven todos a su lugar: ahí el modal es una hoja pegada al
  // borde y un desplazamiento lo dejaría torcido.
  window.addEventListener("resize", function () {
    movidas.slice().forEach(function (caja) {
      if (!escritorio.matches) return resetear(caja);
      var r = caja.getBoundingClientRect();
      var x = parseFloat(caja.dataset.movX || 0), y = parseFloat(caja.dataset.movY || 0);
      var p = acotar(r.left, r.top, r.width, r.height);
      trasladar(caja, x + (p.izq - r.left), y + (p.arr - r.top));
    });
  });
})();
