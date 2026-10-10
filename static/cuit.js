/* CUIL / CUIT: el dígito verificador (módulo 11 de AFIP) en el navegador.

   Es una CORTESÍA (PLAN_CUIT_MOD11.md, D7): avisa un número mal tipeado antes
   de mandar el formulario. Quien decide es el servidor (cuit.py, que es la
   única implementación en Python): lo que diga este archivo nunca habilita
   nada. Por eso hace lo mismo que cuit.py, y test_cuit_puertas.py compara los
   pesos y los prefijos de acá con los de allá.

   Algoritmo: pesos 5 4 3 2 7 6 5 4 3 2 sobre los diez primeros dígitos;
   r = 11 - (suma mod 11); r = 11 -> el verificador es 0; r = 10 -> ese
   prefijo no tiene verificador posible y el número es inválido.

   Uso:
     window.CuitMT.esValido("20-20279041-1")              // cualquiera de los dos tipos
     window.CuitMT.esValido("20202790411", "persona")     // un CUIL
     window.CuitMT.esValido("30444640975", "empresa")     // el CUIT de una persona jurídica

   Y se engancha solo a los campos marcados:
     <input data-cuit="persona|empresa|cualquiera">
   Al SALIR del campo, si la persona lo cambió, no está vacío y no es válido,
   lo marca (setCustomValidity + un aviso debajo); al corregirlo, lo limpia.
   Está delegado en `document` porque hay formularios que se arman con
   innerHTML después de cargar la página.

   Solo avisa si la persona CAMBIÓ el valor en esa visita al campo: en una
   edición, el campo viene relleno con un número guardado que puede no cumplir
   el módulo 11 (uno cargado antes de la regla, o de un lote de prueba) y el
   servidor lo acepta tal cual si no se toca (decisión D2). Marcarlo acá
   bloquearía el envío del formulario por un número que el servidor deja pasar.

   Los inputs de LOGIN no llevan data-cuit a propósito: ahí el número se busca
   tal cual, no se valida. */
(function () {
  "use strict";

  var PESOS = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
  var PREFIJOS_PERSONA = ["20", "23", "24", "25", "26", "27"];
  var PREFIJOS_EMPRESA = ["30", "33", "34"];
  var MENSAJE = "El CUIL/CUIT no es válido: revisá los 11 números";
  var MENSAJE_CUIL = "El CUIL no es válido: revisá los 11 números";
  var MENSAJE_CUIT = "El CUIT no es válido: revisá los 11 números";

  function normalizar(valor) {
    return String(valor == null ? "" : valor).replace(/\D/g, "");
  }

  function esValido(valor, de) {
    var d = normalizar(valor);
    if (d.length !== 11) return false;
    var prefijo = d.slice(0, 2);
    var esPersona = PREFIJOS_PERSONA.indexOf(prefijo) >= 0;
    var esEmpresa = PREFIJOS_EMPRESA.indexOf(prefijo) >= 0;
    if (!esPersona && !esEmpresa) return false;
    if (de === "persona" && !esPersona) return false;
    if (de === "empresa" && !esEmpresa) return false;
    var suma = 0;
    for (var i = 0; i < 10; i++) suma += Number(d.charAt(i)) * PESOS[i];
    var r = 11 - (suma % 11);
    if (r === 11) r = 0;
    if (r === 10) return false;
    return r === Number(d.charAt(10));
  }

  var api = { esValido: esValido, normalizar: normalizar, MENSAJE: MENSAJE,
              limpiar: function () {} };   // en la página, la de abajo
  var raiz = (typeof window !== "undefined") ? window
           : (typeof globalThis !== "undefined" ? globalThis : {});
  raiz.CuitMT = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;

  if (typeof document === "undefined") return;   // Node / tests: sin página

  /* ---------- el enganche a los campos marcados ---------- */

  function tipoDe(campo) {
    var t = campo.getAttribute("data-cuit");
    return (t === "persona" || t === "empresa") ? t : undefined;
  }

  function esCampo(el) {
    return !!(el && el.getAttribute && el.hasAttribute("data-cuit")
              && el.tagName === "INPUT");
  }

  function quitarAviso(campo) {
    var a = campo.nextElementSibling;
    if (a && a.classList && a.classList.contains("cuit-aviso")) a.parentNode.removeChild(a);
  }

  function limpiar(campo) {
    campo.setCustomValidity("");
    campo.removeAttribute("aria-invalid");
    if (campo.__cuitBorde !== undefined) {
      campo.style.borderColor = campo.__cuitBorde;
      campo.__cuitBorde = undefined;
    }
    quitarAviso(campo);
  }

  function mensajeDe(campo) {
    return tipoDe(campo) === "persona" ? MENSAJE_CUIL : MENSAJE_CUIT;
  }

  function marcar(campo) {
    var mensaje = mensajeDe(campo);
    campo.setCustomValidity(mensaje);
    campo.setAttribute("aria-invalid", "true");
    if (campo.__cuitBorde === undefined) campo.__cuitBorde = campo.style.borderColor;
    campo.style.borderColor = "#b23a2e";
    quitarAviso(campo);
    var aviso = document.createElement("div");
    aviso.className = "cuit-aviso";
    aviso.setAttribute("role", "alert");
    aviso.textContent = mensaje;
    // El color lo pone cada pantalla con --cuit-aviso-color (las de fondo
    // oscuro lo aclaran); flex-basis para no romper una fila de campos.
    aviso.style.cssText = "display:block;flex:0 0 100%;width:100%;margin-top:4px;" +
      "font-size:12px;line-height:1.35;letter-spacing:0;text-transform:none;font-weight:400;" +
      "color:var(--cuit-aviso-color,#b23a2e)";
    campo.parentNode.insertBefore(aviso, campo.nextSibling);
  }

  /* Pone el veredicto para el valor ACTUAL del campo. Vacío no se juzga: un
     campo opcional vacío sigue siendo opcional y uno obligatorio lo frena su
     propio `required`. */
  function revisar(campo) {
    var v = campo.value;
    campo.__cuitRevisado = v;
    if (normalizar(v) === "" || esValido(v, tipoDe(campo))) limpiar(campo);
    else marcar(campo);
  }

  document.addEventListener("focusin", function (ev) {
    if (esCampo(ev.target)) ev.target.__cuitAlEntrar = ev.target.value;
  });

  document.addEventListener("input", function (ev) {
    var campo = ev.target;
    if (!esCampo(campo)) return;
    // El veredicto anterior era sobre otro texto: mientras escribe, no corre.
    campo.__cuitRevisado = undefined;
    limpiar(campo);
  });

  document.addEventListener("focusout", function (ev) {
    var campo = ev.target;
    if (!esCampo(campo)) return;
    if (campo.value !== campo.__cuitAlEntrar) revisar(campo);       // lo cambió: se juzga
    else if (campo.__cuitRevisado !== campo.value) limpiar(campo);  // no lo tocó: sin veredicto viejo
  });

  /* Antes de que el navegador valide el formulario (al tocar un botón de
     envío, y Enter dentro de un campo lo hace por un clic en el botón por
     defecto) se actualizan los veredictos de los campos marcados:
       - si la persona escribió algo y apretó Enter sin salir del campo, se
         juzga ahí mismo;
       - un veredicto viejo (el campo lo rellenó el código, por ejemplo al
         tocar "Editar") se borra: un número que ya no es el que se juzgó no
         puede quedar bloqueando el envío. */
  function refrescar(form) {
    if (!form || !form.querySelectorAll) return null;
    var campos = form.querySelectorAll("input[data-cuit]");
    var primerMalo = null;
    for (var i = 0; i < campos.length; i++) {
      var c = campos[i];
      if (c === document.activeElement && c.value !== c.__cuitAlEntrar) revisar(c);
      else if (c.__cuitRevisado !== c.value) limpiar(c);
      if (!primerMalo && c.getAttribute("aria-invalid") === "true") primerMalo = c;
    }
    return primerMalo;
  }

  /* Un formulario que el CÓDIGO rellena ("Editar") o vacía ("Cancelar",
     form.reset()) no dispara input ni focusout, así que la marca de un número
     que se juzgó antes quedaba pegada a uno que no tiene nada que ver (QA,
     2026-10-10). `CuitMT.limpiar(formulario o campo)` borra los veredictos;
     las funciones que rellenan un formulario la llaman, y el reset se limpia
     solo. */
  function limpiarTodo(objetivo) {
    if (!objetivo) return;
    var campos = esCampo(objetivo) ? [objetivo]
               : (objetivo.querySelectorAll ? objetivo.querySelectorAll("input[data-cuit]") : []);
    for (var i = 0; i < campos.length; i++) {
      campos[i].__cuitRevisado = undefined;
      campos[i].__cuitAlEntrar = campos[i].value;
      limpiar(campos[i]);
    }
  }
  api.limpiar = limpiarTodo;

  document.addEventListener("reset", function (ev) {
    var form = ev.target;
    setTimeout(function () { limpiarTodo(form); }, 0);   // después de que el reset vacía los campos
  }, true);

  document.addEventListener("click", function (ev) {
    var boton = ev.target && ev.target.closest ? ev.target.closest("button, input[type=submit]") : null;
    if (boton && boton.form && boton.type === "submit") refrescar(boton.form);
  }, true);

  document.addEventListener("submit", function (ev) {
    var malo = refrescar(ev.target);
    if (malo) {
      ev.preventDefault();
      malo.focus();
    }
  }, true);
})();
