/* Pestaña Trabajadores del panel del sindicato (auditoría de diseño 2026-10,
   bloque 5b).

   - Padron: el listado paginado en el servidor (G4-19). La página trae los
     primeros 50 ya dibujados; buscar y pasar de página piden
     /admin/trabajadores/lista, que devuelve las filas dibujadas con la misma
     plantilla (_padron_filas.html). Acá solo se reemplaza el cuerpo.
   - El menú «Más» de cada fila (G4-15) es un <details>: se abre solo, sin
     JS. Lo único que se agrega es que se cierre al tocar afuera o con Esc, y
     que no queden dos abiertos a la vez.
   - Masivo: el ensayo de la carga masiva (G4-26). «Revisar antes de cargar»
     manda la lista a la MISMA ruta con `ensayo=1`: el servidor la recorre
     con el mismo código que la carga, sin escribir, y dice qué entra y qué
     queda afuera, con su línea y su motivo. Recién ahí se ofrece cargar.

   Necesita NumAR (static/numeros_ar.js). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  // ---------- Listado paginado ----------
  var estado = { pagina: 1, ctrl: null, espera: null };

  function filtros() {
    var qs = new URLSearchParams();
    var cuil = ($('f-trab-cuit') || {}).value || '';
    var nombre = ($('f-trab-nombre') || {}).value || '';
    if (cuil.trim()) qs.set('cuil', cuil.trim());
    if (nombre.trim()) qs.set('nombre', nombre.trim());
    if (($('f-trab-declarados') || {}).checked) qs.set('declarados', '1');
    return qs;
  }

  function pintarCabeza(total, pagina, paginas, porPagina) {
    var cant = $('f-trab-cant');
    if (cant) cant.textContent = NumAR.contar(total, 'trabajador', 'trabajadores') +
      (paginas > 1 ? ' · página ' + NumAR.miles(pagina) + ' de ' + NumAR.miles(paginas) : '');
    var pasos = NumAR.paginador(pagina, paginas, total, porPagina, 'Padron.cargar');
    if ($('padron-paginas')) $('padron-paginas').innerHTML = pasos;
    if ($('padron-paginas-arriba')) $('padron-paginas-arriba').innerHTML = pasos;
  }

  function cargar(pagina) {
    var cuerpo = $('padron-cuerpo');
    if (!cuerpo) return;
    estado.pagina = pagina || 1;
    if (estado.ctrl) estado.ctrl.abort();
    estado.ctrl = new AbortController();
    var qs = filtros();
    qs.set('pagina', estado.pagina);
    cuerpo.setAttribute('aria-busy', 'true');
    fetch('/admin/trabajadores/lista?' + qs, { signal: estado.ctrl.signal, cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (d) {
        cuerpo.innerHTML = d.html;
        cuerpo.removeAttribute('aria-busy');
        if (window.pintarZebra) window.pintarZebra('.fila-trabajador');
        // El título de la pestaña es un solo texto (en los modelos el
        // título es flex y un <span> adentro se separa del paréntesis).
        if ($('trabajadores')) $('trabajadores').textContent = 'Trabajadores (' + NumAR.miles(d.activos) + ' activos)';
        pintarCabeza(d.total, d.pagina, d.paginas, d.por_pagina);
      })
      .catch(function (e) {
        if (e.name === 'AbortError') return;
        cuerpo.removeAttribute('aria-busy');
        cuerpo.innerHTML = '<tr><td colspan="9" class="muted">No se pudo cargar el padrón. ' +
          '<button type="button" class="sec mini" onclick="Padron.cargar(' + estado.pagina + ')">Reintentar</button></td></tr>';
      });
  }

  function buscarPronto() {
    clearTimeout(estado.espera);
    estado.espera = setTimeout(function () { cargar(1); }, 300);
  }

  function limpiar() {
    ['f-trab-cuit', 'f-trab-nombre'].forEach(function (id) { if ($(id)) $(id).value = ''; });
    if ($('f-trab-declarados')) $('f-trab-declarados').checked = false;
    cargar(1);
  }

  window.Padron = { cargar: cargar, buscarPronto: buscarPronto, limpiar: limpiar };

  // ---------- Menú «Más» de cada fila ----------
  // La lista se ubica con position: fixed junto al botón: así ninguna tabla
  // con desplazamiento lateral (la del teléfono) la recorta. Si no entra
  // abajo, se abre hacia arriba.
  function ubicar(d) {
    var lista = d.querySelector('.menu-mas-lista'), boton = d.querySelector('summary');
    if (!lista || !boton) return;
    var r = boton.getBoundingClientRect();
    lista.style.position = 'fixed';
    lista.style.right = 'auto';
    lista.style.top = '0px';
    lista.style.left = '0px';
    var w = lista.offsetWidth, h = lista.offsetHeight;
    var izq = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
    var arriba = r.bottom + 6 + h > window.innerHeight - 8 && r.top - 6 - h > 8;
    lista.style.left = izq + 'px';
    lista.style.top = (arriba ? r.top - 6 - h : r.bottom + 6) + 'px';
  }
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!d.classList || !d.classList.contains('menu-mas') || !d.open) return;
    document.querySelectorAll('details.menu-mas[open]').forEach(function (otro) {
      if (otro !== d) otro.open = false;
    });
    ubicar(d);
  }, true);
  // Al desplazar la página o la tabla, el menú se cierra en vez de quedar
  // flotando lejos de su fila.
  window.addEventListener('scroll', function (e) {
    if (e.target && e.target.closest && e.target.closest('.menu-mas-lista')) return;
    document.querySelectorAll('details.menu-mas[open]').forEach(function (d) { d.open = false; });
  }, true);
  window.addEventListener('resize', function () {
    document.querySelectorAll('details.menu-mas[open]').forEach(function (d) { d.open = false; });
  });
  document.addEventListener('click', function (e) {
    document.querySelectorAll('details.menu-mas[open]').forEach(function (d) {
      if (!d.contains(e.target)) d.open = false;
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('details.menu-mas[open]').forEach(function (d) {
      d.open = false;
      var s = d.querySelector('summary');
      if (s) s.focus();
    });
  });

  // ---------- Ensayo de la carga masiva ----------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function masivoEnsayar() {
    var lista = $('masivo-lista'), caja = $('masivo-ensayo'), cargarBtn = $('masivo-cargar');
    if (!lista || !caja) return;
    if (!lista.value.trim()) {
      caja.classList.remove('oculto');
      caja.innerHTML = '<div class="msg err">Pegá al menos una línea antes de revisar.</div>';
      return;
    }
    var fd = new FormData();
    fd.append('lista', lista.value);
    fd.append('ensayo', '1');
    caja.classList.remove('oculto');
    caja.innerHTML = '<p class="muted">Revisando…</p>';
    if (cargarBtn) cargarBtn.classList.add('oculto');
    fetch('/admin/trabajador/masivo', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || r.status); return d; }); })
      .then(function (d) {
        var entran = d.altas + d.actualizaciones;
        var h = '<div class="msg ' + (entran ? 'ok' : 'err') + '"><b>Revisión:</b> ' +
          NumAR.contar(d.lineas, 'línea leída', 'líneas leídas') + ', <b>' +
          NumAR.contar(d.altas, 'alta nueva', 'altas nuevas') + '</b>' +
          (d.actualizaciones ? ', ' + NumAR.contar(d.actualizaciones, 'actualización', 'actualizaciones') +
            ' de afiliados que ya estaban' : '') +
          (d.afuera.length ? ', <b>' + NumAR.contar(d.afuera_total, 'línea queda', 'líneas quedan') + ' afuera</b>' : '') +
          '. Todavía no se guardó nada.</div>';
        if (d.afuera.length) {
          h += '<h4 class="ensayo-sub">Líneas que quedan afuera</h4><table class="ensayo-tabla"><thead><tr><th>Línea</th><th>Texto</th><th>Por qué</th></tr></thead><tbody>' +
            d.afuera.map(function (x) {
              return '<tr><td class="num">' + NumAR.miles(x.linea) + '</td><td><code>' + esc(x.texto) +
                '</code></td><td>' + esc(x.motivo) + '</td></tr>';
            }).join('') +
            (d.afuera_total > d.afuera.length ? '<tr><td colspan="3" class="muted">… y ' +
              NumAR.miles(d.afuera_total - d.afuera.length) + ' más.</td></tr>' : '') +
            '</tbody></table>';
        }
        caja.innerHTML = h;
        if (cargarBtn) {
          cargarBtn.textContent = d.altas
            ? 'Cargar ' + NumAR.contar(d.altas, 'trabajador', 'trabajadores')
            : 'Guardar ' + NumAR.contar(d.actualizaciones, 'actualización', 'actualizaciones');
          cargarBtn.classList.toggle('oculto', !entran);
        }
        // Con algo para cargar, la acción principal pasa a ser cargar.
        if ($('masivo-revisar')) $('masivo-revisar').classList.toggle('sec', !!entran);
      })
      .catch(function () {
        caja.innerHTML = '<div class="msg err">No se pudo revisar la lista. Probá de nuevo en un momento.</div>';
      });
  }

  // Si se cambia la lista después de revisarla, hay que volver a revisar:
  // lo que se carga tiene que ser exactamente lo que se vio.
  document.addEventListener('input', function (e) {
    if (e.target && e.target.id === 'masivo-lista') {
      var b = $('masivo-cargar'), c = $('masivo-ensayo');
      if (b) b.classList.add('oculto');
      if (c) c.classList.add('oculto');
      if ($('masivo-revisar')) $('masivo-revisar').classList.remove('sec');
    }
  });

  window.masivoEnsayar = masivoEnsayar;

  document.addEventListener('DOMContentLoaded', function () {
    var t = $('padron-tabla');
    if (t) pintarCabeza(+t.dataset.total || 0, 1, +t.dataset.paginas || 1, +t.dataset.porPagina || 50);
  });
})();
