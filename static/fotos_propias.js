/* Las fotos de portada PROPIAS del sindicato, en /admin -> Apariencia
   (2026-11-06, pedido de SDN: subir la foto sin depender de que plataforma la
   cargue antes).

   Habla con /admin/apariencia/fotos (JSON, mismo contrato que
   /plataforma/fotos-tema). Los topes (formato, peso, lado mínimo) NO se
   escriben acá: los dicta fotos_tema.py y llegan en los data-* de
   #ap-fotos-propias. Todo lo que viene del servidor (descripciones) se pone
   con textContent o como atributo, nunca como HTML.

   El selector de "Foto de portada" lo dibuja el servidor dentro del
   formulario de Apariencia, así que después de cambiar algo la página se
   recarga para que lo vea (y se vuelve a abrir la foto en la que se estaba).
   Si el formulario tiene cambios sin guardar, NO se recarga: se avisa. */
(function () {
  'use strict';
  var raiz = document.getElementById('ap-fotos-propias');
  if (!raiz) return;
  var $ = function (id) { return document.getElementById(id); };
  var D = raiz.dataset;
  var MAX_BYTES = Number(D.maxBytes), MAX_MB = Math.round(MAX_BYTES / (1024 * 1024));
  var LADO_MIN = Number(D.ladoMinimo), FORMATOS = D.formatos;
  var CLAVE_SESION = 'ap-fotos-propias-abrir';
  var st = { tema: '', nombres: {}, fotos: [], elegida: null, archivo: null, urlLocal: null,
             foco: { x: 0.5, y: 0.5 }, cargado: false };

  function el(tag, clase, texto) {
    var e = document.createElement(tag);
    if (clase) e.className = clase;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }
  function msg(id, texto, tipo) {
    var p = $(id);
    p.textContent = texto || '';
    p.className = 'ap-fp-msg' + (tipo ? ' ' + tipo : '');
    p.hidden = !texto;
  }
  function entre01(v) {
    var n = Number(v);
    return isFinite(n) ? Math.round(Math.min(1, Math.max(0, n)) * 1000) / 1000 : 0.5;
  }
  function urlNorm(f) { return '/foto-tema/' + encodeURIComponent(f.id) + '?v=' + encodeURIComponent(f.v); }
  function urlColor(f) { return '/foto-tema/' + encodeURIComponent(f.id) + '/color?v=' + encodeURIComponent(f.v_color || 0); }
  function formularioSucio() { var a = $('ap-form-sucio'); return !!a && !a.hidden; }

  // El `detail` del servidor (un 400 dice por qué la foto no sirve) o un texto
  // según el código. Nunca se muestra la respuesta cruda.
  function detalle(r) {
    if (r.status === 403) return Promise.resolve('No tenés permiso para esto, o tu sesión venció: volvé a ingresar.');
    return r.json().then(function (j) {
      return (j && typeof j.detail === 'string') ? j.detail
        : 'No se pudo completar (código ' + r.status + '). Probá de nuevo en un momento.';
    }, function () { return 'No se pudo completar (código ' + r.status + '). Probá de nuevo en un momento.'; });
  }
  function tipoValido(file) {
    return /^image\/(jpeg|png|webp)$/.test(file.type) || /\.(jpe?g|png|webp)$/i.test(file.name || '');
  }
  function pedir(url, opciones) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, opciones || {})).then(null, function () { return null; });
  }

  /* ---- después de un cambio: recargar (o avisar) ---- */
  function listo(id, texto) {
    if (formularioSucio()) {
      return cargar(id).then(function () {
        msg('apfp-msg-editar', texto + ' Tenés cambios sin guardar arriba: guardalos y recargá la página para ver esta foto en «Foto de portada».', 'ok');
      });
    }
    try { sessionStorage.setItem(CLAVE_SESION, JSON.stringify({ tema: st.tema, id: id, texto: texto })); } catch (e) { /* sin storage: se recarga igual */ }
    try { history.replaceState(null, '', location.pathname + location.hash); } catch (e) { /* idem */ }
    location.reload();
    return Promise.resolve();
  }

  /* ---- lista ---- */
  function vacio(texto) {
    $('apfp-grilla').replaceChildren();
    $('apfp-cuenta').textContent = '';
    var v = $('apfp-vacio');
    v.textContent = texto;
    v.hidden = false;
  }

  function cargar(idAbrir) {
    var tema = st.tema;
    return pedir('/admin/apariencia/fotos?tema=' + encodeURIComponent(tema)).then(function (r) {
      if (tema !== st.tema) return;                    // se cambió de modelo mientras tanto
      if (!r) { vacio('No se pudo traer la lista: revisá la conexión y volvé a probar.'); return; }
      if (!r.ok) { return detalle(r).then(vacio); }
      return r.json().then(function (data) {
        st.fotos = Array.isArray(data.fotos) ? data.fotos : [];
        st.cargado = true;
        pintarGrilla();
        var id = idAbrir !== undefined ? idAbrir : (st.elegida && st.elegida.id);
        var f = st.fotos.filter(function (x) { return x.id === id; })[0];
        if (f) abrir(f); else cerrar();
      });
    });
  }

  function pintarGrilla() {
    var g = $('apfp-grilla');
    g.replaceChildren();
    $('apfp-cuenta').textContent = '(' + st.fotos.length + ')';
    var v = $('apfp-vacio');
    v.hidden = st.fotos.length > 0;
    if (!st.fotos.length) v.textContent = 'Todavía no subiste fotos para ' + st.nombres[st.tema] + '. Subí la primera desde arriba.';
    st.fotos.forEach(function (f) {
      var b = el('button', 'sec ap-fp-foto');
      b.type = 'button';
      b.dataset.id = String(f.id);
      var img = el('img');
      img.src = urlNorm(f);
      img.alt = f.descripcion || '';
      img.loading = 'lazy';
      img.style.objectPosition = (entre01(f.foco_x) * 100) + '% ' + (entre01(f.foco_y) * 100) + '%';
      var chips = el('span', 'ap-fp-chips');
      if (!f.descripcion) chips.append(el('span', 'ap-fp-chip aviso', 'Falta descripción'));
      if (!f.color) chips.append(el('span', 'ap-fp-chip', 'Solo en gris'));
      var accion = el('span', 'ap-fp-accion', 'Editar');
      accion.setAttribute('aria-hidden', 'true');
      b.append(img, el('span', 'ap-fp-desc', f.descripcion || ''), chips, accion);
      b.addEventListener('click', function () { abrir(f); });
      g.append(b);
    });
    marcar();
  }

  function marcar() {
    var id = st.elegida ? String(st.elegida.id) : null;
    Array.prototype.forEach.call(document.querySelectorAll('#apfp-grilla .ap-fp-foto'), function (b) {
      var si = b.dataset.id === id;
      b.classList.toggle('elegida', si);
      b.setAttribute('aria-pressed', si ? 'true' : 'false');
    });
  }

  /* ---- editor: punto de interés, color, descripción ---- */
  function pintarFoco() {
    var x = st.foco.x * 100, y = st.foco.y * 100;
    $('apfp-punto').style.left = x + '%';
    $('apfp-punto').style.top = y + '%';
    $('apfp-rec-ancho').style.objectPosition = x + '% ' + y + '%';
    $('apfp-rec-alto').style.objectPosition = x + '% ' + y + '%';
  }
  function pintarLienzo() {
    var f = st.elegida;
    if (!f) return;
    var url = (f.color && $('apfp-ver-color').checked) ? urlColor(f) : urlNorm(f);
    ['apfp-ed-img', 'apfp-rec-ancho', 'apfp-rec-alto'].forEach(function (id) { $(id).src = url; });
  }

  function abrir(f) {
    st.elegida = f;
    st.foco = { x: entre01(f.foco_x), y: entre01(f.foco_y) };
    $('apfp-ver-color').checked = false;
    $('apfp-ver-color-l').hidden = !f.color;
    $('apfp-sin-color').hidden = !!f.color;
    pintarLienzo();
    $('apfp-ed-img').alt = f.descripcion || 'Foto sin descripción';
    $('apfp-desc').value = f.descripcion || '';
    pintarFoco();
    $('apfp-ficha').textContent = f.ancho + ' × ' + f.alto + ' px' + (f.creada ? ' · subida el ' + f.creada : '');
    msg('apfp-msg-editar', '');
    $('apfp-editor').hidden = false;
    $('apfp-trabajo').classList.add('editando');
    marcar();
    if (window.matchMedia('(max-width:760px)').matches) $('apfp-editor').scrollIntoView({ block: 'start' });
  }
  function cerrar() {
    st.elegida = null;
    $('apfp-editor').hidden = true;
    $('apfp-trabajo').classList.remove('editando');
    marcar();
  }

  function cambiarTema(tema) {
    if (!st.nombres[tema] || (tema === st.tema && st.cargado)) return Promise.resolve();
    st.tema = tema;
    Array.prototype.forEach.call(raiz.querySelectorAll('input[name="ap-fp-tema"]'), function (r) { r.checked = r.value === tema; });
    $('apfp-modelo-subir').textContent = st.nombres[tema];
    $('apfp-modelo-lista').textContent = st.nombres[tema];
    cerrar();
    $('apfp-grilla').replaceChildren();
    $('apfp-cuenta').textContent = '';
    return cargar(null);
  }

  /* ---- subir ---- */
  function reiniciarZona() {
    st.archivo = null;
    $('apfp-archivo').value = '';
    $('apfp-zona-txt').textContent = 'Arrastrá una foto acá o tocá para elegirla';
    $('apfp-btn-subir').disabled = true;
    $('apfp-previa').hidden = true;
  }

  function elegirArchivo(file) {
    msg('apfp-msg-subir', '');
    if (!file) return;
    if (!tipoValido(file)) { reiniciarZona(); msg('apfp-msg-subir', 'Ese archivo no es una foto ' + FORMATOS + '.', 'error'); return; }
    if (file.size > MAX_BYTES) { reiniciarZona(); msg('apfp-msg-subir', 'La foto pesa más de ' + MAX_MB + ' MB.', 'error'); return; }
    st.archivo = file;
    if (st.urlLocal) URL.revokeObjectURL(st.urlLocal);
    st.urlLocal = URL.createObjectURL(file);
    var previa = $('apfp-previa-img');
    previa.onload = function () {
      // Aviso temprano; el que decide es el servidor.
      if (st.archivo === file && Math.max(previa.naturalWidth, previa.naturalHeight) < LADO_MIN) {
        msg('apfp-msg-subir', 'La foto es muy chica: el lado largo tiene que medir al menos ' + LADO_MIN + ' px.', 'error');
        $('apfp-btn-subir').disabled = true;
      }
    };
    previa.src = st.urlLocal;
    $('apfp-previa').hidden = false;
    $('apfp-zona-txt').textContent = file.name || 'Foto elegida';
    $('apfp-btn-subir').disabled = false;
  }

  function subir() {
    if (!st.archivo) return;
    var tema = st.tema, btn = $('apfp-btn-subir');
    var fd = new FormData();
    fd.append('tema', tema);
    fd.append('archivo', st.archivo);
    fd.append('descripcion', $('apfp-desc-nueva').value.trim());
    fd.append('foco_x', '0.5');
    fd.append('foco_y', '0.5');
    btn.disabled = true;
    btn.textContent = 'Subiendo y normalizando…';
    msg('apfp-msg-subir', '');
    return pedir('/admin/apariencia/fotos', { method: 'POST', body: fd }).then(function (r) {
      btn.textContent = 'Subir foto';
      if (!r || !r.ok) {
        btn.disabled = false;
        return (r ? detalle(r) : Promise.resolve('No se pudo subir: revisá la conexión.'))
          .then(function (t) { msg('apfp-msg-subir', t, 'error'); });
      }
      return r.json().then(function (j) {
        reiniciarZona();
        $('apfp-desc-nueva').value = '';
        return listo(j.id, 'Lista: quedó normalizada y en color (' + j.ancho + ' × ' + j.alto +
                     ' px). Marcá el punto de interés y elegila arriba como portada.');
      });
    });
  }

  /* ---- guardar, reponer, borrar ---- */
  function guardar() {
    var f = st.elegida;
    if (!f) return;
    var fd = new FormData();
    fd.append('descripcion', $('apfp-desc').value.trim());
    fd.append('foco_x', String(st.foco.x));
    fd.append('foco_y', String(st.foco.y));
    var btn = $('apfp-guardar');
    btn.disabled = true;
    return pedir('/admin/apariencia/fotos/' + encodeURIComponent(f.id), { method: 'POST', body: fd }).then(function (r) {
      btn.disabled = false;
      if (!r || !r.ok) {
        return (r ? detalle(r) : Promise.resolve('No se pudo guardar: revisá la conexión.'))
          .then(function (t) { msg('apfp-msg-editar', t, 'error'); });
      }
      return listo(f.id, 'Guardado.');
    });
  }

  function reponer(file) {
    var f = st.elegida;
    if (!f || !file) return;
    if (!tipoValido(file)) { msg('apfp-msg-editar', 'Ese archivo no es una foto ' + FORMATOS + '.', 'error'); return; }
    if (file.size > MAX_BYTES) { msg('apfp-msg-editar', 'La foto pesa más de ' + MAX_MB + ' MB.', 'error'); return; }
    var fd = new FormData();
    fd.append('archivo', file);
    msg('apfp-msg-editar', 'Subiendo y normalizando…');
    return pedir('/admin/apariencia/fotos/' + encodeURIComponent(f.id) + '/archivo', { method: 'POST', body: fd }).then(function (r) {
      $('apfp-archivo-reponer').value = '';
      if (!r || !r.ok) {
        return (r ? detalle(r) : Promise.resolve('No se pudo subir: revisá la conexión.'))
          .then(function (t) { msg('apfp-msg-editar', t, 'error'); });
      }
      return listo(f.id, 'Archivo repuesto: la foto quedó en gris y en color, con el mismo punto de interés.');
    });
  }

  function borrar() {
    var f = st.elegida;
    if (!f) return;
    if (!confirm('¿Borrar esta foto de ' + st.nombres[st.tema] + '? Si es tu portada, el modelo vuelve a la automática. No se puede deshacer.')) return;
    return pedir('/admin/apariencia/fotos/' + encodeURIComponent(f.id) + '/borrar', { method: 'POST' }).then(function (r) {
      if (!r || !r.ok) {
        return (r ? detalle(r) : Promise.resolve('No se pudo borrar: revisá la conexión.'))
          .then(function (t) { msg('apfp-msg-editar', t, 'error'); });
      }
      return listo(null, 'Foto borrada.');
    });
  }

  /* ---- arranque ---- */
  Array.prototype.forEach.call(raiz.querySelectorAll('input[name="ap-fp-tema"]'), function (r) {
    st.nombres[r.value] = r.dataset.nombre;
    r.addEventListener('change', function () { if (r.checked) cambiarTema(r.value); });
  });
  var zona = $('apfp-zona'), input = $('apfp-archivo'), lienzo = $('apfp-lienzo');
  input.addEventListener('change', function () { elegirArchivo(input.files[0]); });
  zona.addEventListener('dragover', function (e) { e.preventDefault(); zona.classList.add('encima'); });
  zona.addEventListener('dragleave', function () { zona.classList.remove('encima'); });
  zona.addEventListener('drop', function (e) {
    e.preventDefault();
    zona.classList.remove('encima');
    elegirArchivo(e.dataTransfer && e.dataTransfer.files[0]);
  });
  $('apfp-btn-subir').addEventListener('click', subir);
  $('apfp-guardar').addEventListener('click', guardar);
  $('apfp-borrar').addEventListener('click', borrar);
  $('apfp-cerrar').addEventListener('click', cerrar);
  $('apfp-ver-color').addEventListener('change', pintarLienzo);
  $('apfp-archivo-reponer').addEventListener('change', function () { reponer($('apfp-archivo-reponer').files[0]); });
  // El punto de interés: un clic sobre la foto, o las flechas del teclado.
  lienzo.addEventListener('click', function (e) {
    var caja = $('apfp-ed-img').getBoundingClientRect();
    if (!caja.width || !caja.height) return;
    st.foco = { x: entre01((e.clientX - caja.left) / caja.width), y: entre01((e.clientY - caja.top) / caja.height) };
    pintarFoco();
  });
  lienzo.addEventListener('keydown', function (e) {
    var paso = { ArrowLeft: [-0.02, 0], ArrowRight: [0.02, 0], ArrowUp: [0, -0.02], ArrowDown: [0, 0.02] }[e.key];
    if (!paso) return;
    e.preventDefault();
    st.foco = { x: entre01(st.foco.x + paso[0]), y: entre01(st.foco.y + paso[1]) };
    pintarFoco();
  });

  // Si la página se recargó por un cambio, volver a la foto en la que se estaba.
  var pendiente = null;
  try {
    var guardado = sessionStorage.getItem(CLAVE_SESION);
    if (guardado) { pendiente = JSON.parse(guardado); sessionStorage.removeItem(CLAVE_SESION); }
  } catch (e) { pendiente = null; }
  var inicial = pendiente && st.nombres[pendiente.tema] ? pendiente.tema
    : (raiz.querySelector('input[name="ap-fp-tema"]:checked') || {}).value;
  if (inicial) {
    cambiarTema(inicial).then(function () {
      if (pendiente) {
        if (pendiente.id) { var f = st.fotos.filter(function (x) { return x.id === pendiente.id; })[0]; if (f) abrir(f); }
        msg(pendiente.id ? 'apfp-msg-editar' : 'apfp-msg-subir', pendiente.texto, 'ok');
        if (pendiente.id && $('apfp-editor').hidden) msg('apfp-msg-subir', pendiente.texto, 'ok');
        raiz.scrollIntoView({ block: 'start' });
      }
    });
  }
})();
