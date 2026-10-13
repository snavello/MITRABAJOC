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
      // Mientras se está yendo (`mov-sale`, abajo) se queda donde estaba:
      // volver al centro en medio del cierre se vería como un salto.
      if (!fondo.classList.contains("abierto") && !fondo.classList.contains("mov-sale")) {
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

  /* ================= Cómo entran, se arman y se van =================
     El movimiento de los modales (2026-10-13, pedido de SDN después del caso
     cero de la v2 del Panel). La entrada la hace el CSS solo
     (static/movimiento.css); acá va lo que el CSS no puede:

     - **Sostener la salida.** Todos los modales se cierran sacando `abierto`
       del fondo, que vuelve a `display:none` en el acto. Al verlo, se le
       pone `mov-sale`, que lo deja visible el tiempo de irse, y después se
       saca. Las funciones de cerrar de cada pantalla no se tocan.
     - **Armar el contenido pieza por pieza** al abrir, y otra vez cuando
       llega lo que se estaba cargando (`data-armado` + su escalón).
     - **Que esperar sea armar.** Lo que dice "Cargando…" se marca con
       `mov-cargando` y el CSS lo dibuja como la forma de lo que viene.
     - **Crecer de a poco.** Cuando el contenido cambia con el modal abierto
       (llega el detalle de un recibo, la conversación de un trámite), la
       caja pasa de su alto viejo al nuevo en vez de saltar.

     Nada de esto toca lo que hace el modal: si este bloque falla, el modal
     abre y cierra igual, sin movimiento.

     Afuera: el "Ver" del Panel Sindical (`.overlay-det`). La v1 recibe solo
     arreglos mientras SDN decide D9, y la v2 trae su propio movimiento. */
  var FONDOS_MOV = ".overlay, .modal-recibo-overlay, .overlay-ayuda, .overlay-foto-grande";
  var CAJAS_MOV = ":scope > .modal-hoja, :scope > .modal-notif-caja, :scope > .modal-articulo, " +
    ":scope > .modal-recibo, :scope > .overlay-ayuda-caja, :scope > img";
  var CUERPOS = ":scope > .modal-notif-body, :scope > .modal-articulo-body, :scope > .modal-recibo-body";
  // Lo que no se arma: los botones de cerrar van fijos en su esquina, y lo
  // invisible no tiene nada que mostrar (y si se marcara, se armaría tarde,
  // el día que aparezca).
  var NO_ARMAR = ".modal-cerrar, .modal-cerrar-clara, .modal-recibo-cerrar, .overlay-ayuda-cerrar, " +
    "script, style, template, input[type=hidden]";
  var CARGANDO = /^Cargando(…|\.\.\.)$/;
  var ESCALON = 45, TOPE_PIEZAS = 10;
  var reducido = window.matchMedia("(prefers-reduced-motion: reduce)");

  function ms(token, defecto) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
    var n = parseFloat(v);
    if (isNaN(n)) return defecto;
    return /ms$/.test(v) ? n : n * 1000;
  }

  function cajaDe(fondo) {
    try { return fondo.querySelector(CAJAS_MOV); } catch (e) { return null; }
  }

  function visibles(el) {
    return Array.prototype.filter.call(el.children, function (c) {
      return !c.matches(NO_ARMAR) && c.getClientRects().length > 0;
    });
  }

  /* Qué piezas se arman: los bloques del cuerpo. Si el cuerpo tiene una sola
     caja adentro (el contenedor que cada pantalla llena con innerHTML), se
     entra en ella: la pieza es lo que trae, no el contenedor entero. */
  function piezas(caja) {
    var cuerpo = caja.querySelector(CUERPOS) || caja;
    var xs = visibles(cuerpo);
    for (var prof = 0; xs.length === 1 && prof < 2; prof++) {
      var adentro = visibles(xs[0]);
      if (adentro.length < 2) break;
      xs = adentro;
    }
    return xs;
  }

  function desarmar(xs) {
    xs.forEach(function (el) { el.removeAttribute("data-armado"); el.style.animationDelay = ""; });
  }

  /* `extra` son piezas fuera del cuerpo que también se arman (el título que
     decía "Cargando…" y ya dice lo que es). */
  function armar(caja, base, extra) {
    if (caja.tagName === "IMG") return;
    armarLista(caja, (extra || []).concat(piezas(caja)), base);
  }

  function armarLista(caja, xs, base) {
    // Las marcas de la vez anterior se sacan primero y se deja que el
    // navegador lo note: si una pieza ya tenía la marca, volver a ponérsela
    // no reinicia su animación, y lo que llegó del servidor aparecería de
    // golpe sobre un hueco que ya se había "armado" vacío.
    clearTimeout(caja._movArmado);
    desarmar(caja._movPiezas || []);
    void caja.offsetWidth;
    xs.forEach(function (el, i) {
      el.setAttribute("data-armado", "");
      el.style.animationDelay = (base + Math.min(i, TOPE_PIEZAS) * ESCALON) + "ms";
    });
    caja._movPiezas = xs;
    // Una sola limpieza para todas, cuando ya terminaron. Si la marca se
    // quedara, la pieza volvería a armarse cada vez que se oculte y se
    // muestre (una pestaña adentro del modal, por ejemplo).
    caja._movArmado = setTimeout(function () {
      desarmar(xs);
      if (caja._movPiezas === xs) caja._movPiezas = null;
    }, base + TOPE_PIEZAS * ESCALON + ms("--mov-lento", 650) + 120);
  }

  /* Marca con `mov-cargando` lo que dice exactamente "Cargando…" y le saca la
     marca a lo que ya no lo dice. Devuelve si quedó algo esperando. */
  function marcarCarga(caja, soltados) {
    var hay = false;
    var vistos = [];
    var w = document.createTreeWalker(caja, NodeFilter.SHOW_TEXT, null);
    for (var n = w.nextNode(); n; n = w.nextNode()) {
      var el = n.parentElement;
      if (el && CARGANDO.test((n.nodeValue || "").trim()) && CARGANDO.test(el.textContent.trim())) {
        vistos.push(el);
      }
    }
    // La ruedita de las vistas del afiliado y de la empresa (`.cargando` con
    // su `.spin`) es la misma espera con otra cara.
    caja.querySelectorAll(".cargando").forEach(function (el) {
      if (el.querySelector(".spin") && vistos.indexOf(el) < 0) vistos.push(el);
    });
    caja.querySelectorAll(".mov-cargando").forEach(function (el) {
      if (vistos.indexOf(el) >= 0) return;
      el.classList.remove("mov-cargando");
      if (soltados && /^H[1-4]$/.test(el.tagName)) soltados.push(el);
    });
    vistos.forEach(function (el) { el.classList.add("mov-cargando"); hay = true; });
    caja.classList.toggle("mov-esperando", hay);
    return hay;
  }

  /* El alto: se fija el que se veía, se mide el nuevo y se va de uno al otro.
     Todo pasa antes de que el navegador pinte (los MutationObserver corren
     antes), así que nunca se ve el salto. */
  var alturas = typeof ResizeObserver === "function" ? new ResizeObserver(function (es) {
    es.forEach(function (e) {
      if (!e.target.classList.contains("mov-crece")) e.target._movAlto = e.target.offsetHeight;
    });
  }) : null;

  function crecer(caja) {
    if (caja.tagName === "IMG") return;
    var viejo = caja.offsetHeight;  // en medio de otro crecimiento, el alto de ese momento
    if (caja.classList.contains("mov-crece")) {
      caja.style.height = "";
      caja.classList.remove("mov-crece");
    } else if (caja._movAlto) {
      viejo = caja._movAlto;
    }
    var nuevo = caja.offsetHeight;
    caja._movAlto = nuevo;
    if (reducido.matches || !viejo || Math.abs(nuevo - viejo) < 6) return;
    caja.style.height = viejo + "px";
    caja.classList.add("mov-crece");
    void caja.offsetHeight;  // que el navegador tome el alto viejo como punto de partida
    caja.style.height = nuevo + "px";
    clearTimeout(caja._movCrece);
    caja._movCrece = setTimeout(function () {
      caja.classList.remove("mov-crece");
      caja.style.height = "";
      caja._movAlto = caja.offsetHeight;
    }, ms("--mov-lento", 650) + 60);
  }

  function terminarSalida(fondo) {
    clearTimeout(fondo._movSale);
    if (fondo.classList.contains("mov-sale")) fondo.classList.remove("mov-sale");
    fondo.querySelectorAll(CAJAS).forEach(resetear);
  }

  function alAbrir(fondo) {
    var caja = cajaDe(fondo);
    terminarSalida(fondo);
    if (!caja) return;
    if (alturas) alturas.observe(caja);
    caja._movCargando = marcarCarga(caja);
    // Se mide después de marcar la espera: el esqueleto ya es parte del alto
    // con el que entra, no algo que crece después.
    caja._movAlto = caja.offsetHeight;
    armar(caja, 90);
  }

  function alCerrar(fondo) {
    var caja = cajaDe(fondo);
    if (caja && alturas) alturas.unobserve(caja);
    if (caja) {
      clearTimeout(caja._movCrece);
      caja.classList.remove("mov-crece");
      caja.style.height = "";
    }
    fondo.classList.add("mov-sale");
    fondo._movSale = setTimeout(function () { terminarSalida(fondo); },
      (reducido.matches ? 160 : ms("--mov-medio", 320)) + 40);
  }

  function alCambiar(fondo) {
    if (!fondo._movAbierto) return;
    var caja = cajaDe(fondo);
    if (!caja) return;
    var esperaba = caja._movCargando, titulos = [];
    caja._movCargando = marcarCarga(caja, titulos);
    // Llegó lo que se estaba esperando: se arma de nuevo, desde ya, junto con
    // el título que decía "Cargando…". Un repintado cualquiera (un mensaje
    // nuevo en el chat) no se re-arma: ver todo rearmarse cada vez sería ruido.
    if (esperaba && !caja._movCargando) armar(caja, 0, titulos);
    crecer(caja);
  }

  function vigilar(fondo) {
    if (fondo._movVigilado) return;
    fondo._movVigilado = true;
    fondo._movAbierto = fondo.classList.contains("abierto");
    if (fondo._movAbierto) alAbrir(fondo);
    new MutationObserver(function () {
      var abierto = fondo.classList.contains("abierto");
      if (abierto === fondo._movAbierto) return;
      fondo._movAbierto = abierto;
      if (abierto) alAbrir(fondo); else alCerrar(fondo);
    }).observe(fondo, { attributes: true, attributeFilter: ["class"] });
    new MutationObserver(function () { alCambiar(fondo); })
      .observe(fondo, { childList: true, characterData: true, subtree: true });
  }

  /* ---------- Las vistas que se arman como un modal ----------
     Algunas pantallas no abren un modal: cambian de vista adentro de la
     pestaña (los trámites del afiliado y de la empresa: la lista, los
     formularios, el formulario, el detalle). La marca `data-mov-vista` les
     da el mismo tratamiento: al aparecer, sus piezas entran en cascada; lo
     que espera (la ruedita de `.cargando`, o "Cargando…") se dibuja como la
     forma de lo que viene; y cuando llega, lo que llegó se arma. Lo que no
     hacen es crecer de a poco: una vista está en el flujo de la página, y
     animar su alto reacomodaría todo lo de abajo cuadro por cuadro.

     Se vigilan los atributos de cada vista (las pantallas las cambian con
     `style.display` o con la clase `activo` de la pestaña) y, desde la vista
     de más afuera, el contenido de todas las de adentro. */
  function seVe(el) { return el.getClientRects().length > 0; }

  // Lo que llegó, sin repetir lo que ya viene adentro de otra pieza que
  // llegó en el mismo paso, y en el orden en que se lee.
  function llegados(regs) {
    var xs = [];
    regs.forEach(function (r) {
      r.addedNodes.forEach(function (n) {
        if (n.nodeType === 1 && n.isConnected && xs.indexOf(n) < 0 && !n.matches(NO_ARMAR)) xs.push(n);
      });
    });
    xs = xs.filter(function (n) {
      return seVe(n) && !xs.some(function (m) { return m !== n && m.contains(n); });
    });
    return xs.sort(function (a, b) {
      return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    });
  }

  function vigilarVista(v) {
    if (v._movVigilada) return;
    v._movVigilada = true;
    v._movVisible = seVe(v);
    new MutationObserver(function () {
      var ahora = seVe(v);
      if (ahora === v._movVisible) return;
      v._movVisible = ahora;
      if (ahora) armar(v, 0);
    }).observe(v, { attributes: true, attributeFilter: ["style", "class", "hidden"] });
    if (v.parentElement && v.parentElement.closest("[data-mov-vista]")) return;
    v._movCargando = marcarCarga(v);
    new MutationObserver(function (regs) {
      var esperaba = v._movCargando;
      v._movCargando = marcarCarga(v);
      // Llegó lo que se esperaba: se arma lo que llegó. Un repintado sin
      // espera (cambiar un filtro) no se rearma, igual que en los modales.
      if (!esperaba || v._movCargando) return;
      var xs = llegados(regs);
      if (xs.length) armarLista(v, xs, 0);
    }).observe(v, { childList: true, characterData: true, subtree: true });
  }

  function arrancar() {
    document.querySelectorAll(FONDOS_MOV).forEach(vigilar);
    document.querySelectorAll("[data-mov-vista]").forEach(vigilarVista);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar);
  else arrancar();
})();
