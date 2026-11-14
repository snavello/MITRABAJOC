/* Pestaña Implementación de /entornos: proyectos y usuarios del sindicato.
   Usa /api/entornos/implementacion/*. Todo texto de una persona entra con
   nodos de texto, nunca como HTML. */
(function () {
  'use strict';
  const API = '/api/entornos/implementacion';
  const $ = function (id) { return document.getElementById(id); };
  let cargado = false;
  let proyectoAbierto = null;

  function h(tag, props) {
    const e = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      const v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') e.className = v;
      else if (k.slice(0, 2) === 'on' && typeof v === 'function') e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : String(v));
    });
    for (let i = 2; i < arguments.length; i++) {
      const k = arguments[i];
      if (k === null || k === undefined || k === false) continue;
      e.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return e;
  }
  async function pedirJson(url, opciones) {
    let r;
    try { r = await fetch(url, Object.assign({ credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } }, opciones || {})); }
    catch (e) { throw new Error('No hay conexión con el servidor.'); }
    let cuerpo = null;
    if ((r.headers.get('content-type') || '').indexOf('json') !== -1) { try { cuerpo = await r.json(); } catch (e) { cuerpo = null; } }
    if (!r.ok) {
      const d = cuerpo && cuerpo.detail;
      throw new Error(typeof d === 'string' && d ? d : (r.status >= 500 ? 'El servidor no respondió (HTTP ' + r.status + ').' : 'No se pudo completar (HTTP ' + r.status + ').'));
    }
    if (cuerpo === null) throw new Error('El servidor no respondió como se esperaba (HTTP ' + r.status + ').');
    return cuerpo;
  }
  const post = function (url, cuerpo) {
    return pedirJson(url, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
  };
  async function copiar(texto) {
    try { if (navigator.clipboard) { await navigator.clipboard.writeText(texto); return true; } } catch (e) { /* respaldo */ }
    const ta = h('textarea', { 'aria-hidden': 'true', tabindex: '-1', readonly: true, style: 'position:fixed;left:-9999px;top:0;opacity:0' });
    ta.value = texto; document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove(); return ok;
  }
  function error(id, texto) { const e = $(id); e.textContent = texto || ''; e.hidden = !texto; }

  async function cargarProyectos() {
    const lista = $('impl-lista'); const estado = $('impl-estado');
    try {
      const d = await pedirJson(API + '/proyectos');
      const ps = d.proyectos || [];
      estado.textContent = ps.length ? ps.length + (ps.length === 1 ? ' proyecto.' : ' proyectos.') : 'Todavía no hay proyectos.';
      lista.replaceChildren();
      if (!ps.length) lista.appendChild(h('p', { class: 'impl-vacio' }, 'Todavía no hay proyectos. Creá el primero abajo.'));
      ps.forEach(function (p) {
        const msg = h('span', { class: 'impl-vacio', role: 'status' });
        lista.appendChild(h('div', { class: 'impl-fila' + (p.activo ? '' : ' inactivo') },
          h('div', { class: 'impl-nom' }, p.nombre, h('small', null, (p.usuarios || 0) + (p.usuarios === 1 ? ' usuario' : ' usuarios') + (p.activo ? '' : ' · inactivo')),
            h('small', { class: 'impl-ingreso' }, 'Ingreso del sindicato: ', h('code', null, '/implementacion/ingresar'), ' ',
              h('button', { class: 'boton suave', type: 'button', 'aria-label': 'Copiar el enlace de ingreso del sindicato', onclick: async function (ev) {
                const b = ev.currentTarget; const ok = await copiar(window.location.origin + '/implementacion/ingresar');
                b.textContent = ok ? 'Copiado' : 'No se pudo'; setTimeout(function () { b.textContent = 'Copiar enlace'; }, 1600);
              } }, 'Copiar enlace'))),
          h('div', { class: 'impl-acc' },
            h('a', { class: 'boton', href: '/implementacion?p=' + p.id, target: '_blank', rel: 'noopener' }, 'Abrir la mesa'),
            h('button', { class: 'boton suave', type: 'button', onclick: function () { abrirUsuarios(p); } }, 'Usuarios'),
            h('button', { class: 'boton suave', type: 'button', onclick: async function (ev) {
              const b = ev.currentTarget; b.disabled = true; msg.textContent = '';
              try { const r = await post(API + '/proyectos/' + p.id + '/hitos-semilla'); msg.textContent = 'Se cargaron ' + (r.cargados || 0) + ' hitos.'; }
              catch (e) { msg.textContent = e.message; } finally { b.disabled = false; }
            } }, 'Cargar hitos de La Bancaria')),
          msg));
      });
    } catch (e) {
      estado.textContent = e.message;
      lista.replaceChildren(h('p', { class: 'impl-error' }, e.message));
    }
  }

  async function abrirUsuarios(p) {
    proyectoAbierto = p;
    $('impl-usuarios').hidden = false;
    $('impl-usuarios-proyecto').textContent = p.nombre;
    $('impl-clave').hidden = true; error('impl-usuario-error', '');
    await cargarUsuarios();
    $('impl-usuarios').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  async function cargarUsuarios() {
    const lista = $('impl-usuarios-lista');
    try {
      const d = await pedirJson(API + '/proyectos/' + proyectoAbierto.id + '/usuarios');
      lista.replaceChildren();
      const us = d.usuarios || [];
      if (!us.length) lista.appendChild(h('p', { class: 'impl-vacio' }, 'Todavía no hay usuarios. Dá de alta el primero abajo.'));
      us.forEach(function (u) {
        lista.appendChild(h('div', { class: 'impl-fila' + (u.activo ? '' : ' inactivo') },
          h('div', { class: 'impl-nom' }, u.nombre, h('small', null, u.mail + (u.debe_cambiar_clave ? ' · todavía no eligió su clave' : '') + (u.activo ? '' : ' · desactivado'))),
          h('div', { class: 'impl-acc' },
            h('button', { class: 'boton suave', type: 'button', onclick: async function (ev) {
              const b = ev.currentTarget; b.disabled = true; error('impl-usuario-error', '');
              try {
                const r = await pedirJson(API + '/proyectos/' + proyectoAbierto.id + '/usuarios/' + u.id + '/restablecer-clave', { method: 'POST' });
                const caja = $('impl-clave');
                caja.replaceChildren(h('b', null, 'Clave transitoria de ' + u.nombre + ': '), h('code', null, r.clave),
                  h('br'), 'Se muestra una sola vez. Pasásela por fuera de la app; va a tener que elegir otra al entrar.');
                caja.hidden = false; await cargarUsuarios();
              } catch (e) { error('impl-usuario-error', e.message); b.disabled = false; }
            } }, 'Restablecer clave'),
            h('button', { class: 'boton suave', type: 'button', onclick: async function (ev) {
              const b = ev.currentTarget; b.disabled = true; error('impl-usuario-error', '');
              try { await post(API + '/proyectos/' + proyectoAbierto.id + '/usuarios/' + u.id + '/estado', { activo: !u.activo }); await cargarUsuarios(); cargarProyectos(); }
              catch (e) { error('impl-usuario-error', e.message); b.disabled = false; }
            } }, u.activo ? 'Desactivar' : 'Activar'))));
      });
    } catch (e) { error('impl-usuario-error', e.message); }
  }

  function iniciar() {
    if (cargado) return; cargado = true;
    cargarProyectos();
    $('impl-proyecto-nuevo').addEventListener('submit', async function (ev) {
      ev.preventDefault(); error('impl-proyecto-error', '');
      const f = ev.currentTarget; const b = f.querySelector('button'); b.disabled = true;
      try { await post(API + '/proyectos', { nombre: f.nombre.value.trim() }); f.reset(); await cargarProyectos(); }
      catch (e) { error('impl-proyecto-error', e.message); } finally { b.disabled = false; }
    });
    $('impl-usuario-nuevo').addEventListener('submit', async function (ev) {
      ev.preventDefault(); error('impl-usuario-error', '');
      if (!proyectoAbierto) return;
      const f = ev.currentTarget; const b = f.querySelector('button'); b.disabled = true;
      try {
        await post(API + '/proyectos/' + proyectoAbierto.id + '/usuarios', { nombre: f.nombre.value.trim(), mail: f.mail.value.trim(), clave_inicial: f.clave_inicial.value });
        f.reset(); $('impl-clave').hidden = true; await cargarUsuarios(); cargarProyectos();
      } catch (e) { error('impl-usuario-error', e.message); } finally { b.disabled = false; }
    });
  }

  const tab = document.querySelector('.etab[data-tab="implementacion"]');
  if (tab) tab.addEventListener('click', iniciar);
  if (window.location.hash === '#implementacion') iniciar();
})();
