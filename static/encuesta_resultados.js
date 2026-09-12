/* Dashboard de una encuesta (SPRINT_ENCUESTAS.md, Fase 4).
 *
 * Esta pantalla NO decide nada: pide /admin/encuesta/resultados y dibuja lo
 * que vuelve. El umbral, el recorte por seccional (N18) y el saneado de los
 * filtros ya vinieron aplicados del servidor -- si un grupo está por debajo
 * del umbral, las preguntas ni siquiera viajan. Esconder algo acá no sería
 * una protección: el JSON se lee con el inspector.
 */
const $ = (id) => document.getElementById(id);
const graficos = {};
let DATOS = null;
// El filtro vive acá y no en el DOM: con pastillas multi-selección, leer el
// estado de los botones cada vez era la fuente de todos los desfasajes.
const FILTRO = { seccional: [], provincia: [], empleador: [], desde: "", hasta: "" };
const VISTA = {};          // cómo se dibuja cada pregunta: barras | torta | tabla
let CAL = { mes: null, eligiendo: false };

function esc(t) {
  return String(t == null ? '' : t).replace(/[<>&"]/g, c =>
    ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

function css(nombre) {
  return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
}

function diaCorto(iso) {
  const p = String(iso || '').split('-');
  return p.length === 3 ? `${p[2]}/${p[1]}` : (iso || '');
}

function selloLegible(sello) {
  const [dia, hora] = String(sello || '').split(' ');
  return hora ? `${fechaLegible(dia)} ${hora}` : fechaLegible(dia);
}

function fechaLegible(iso) {
  const p = String(iso || '').slice(0, 10).split('-');
  return p.length === 3 ? `${p[2]}/${p[1]}/${p[0]}` : (iso || '');
}

/* ---------- Pedir ---------- */

function filtrosDeLaPantalla() {
  const q = new URLSearchParams({ id: ENCUESTA_ID });
  ['seccional', 'provincia', 'empleador'].forEach(c =>
    FILTRO[c].forEach(v => q.append(c, v)));
  if (FILTRO.desde) q.append('desde', FILTRO.desde);
  if (FILTRO.hasta) q.append('hasta', FILTRO.hasta);
  return q;
}

function cuantosFiltros() {
  return ['seccional', 'provincia', 'empleador'].reduce((n, c) => n + FILTRO[c].length, 0)
    + (FILTRO.desde || FILTRO.hasta ? 1 : 0);
}

function alternar(corte, valor) {
  const i = FILTRO[corte].indexOf(valor);
  if (i >= 0) FILTRO[corte].splice(i, 1); else FILTRO[corte].push(valor);
  cerrarCruce();
  cargar();
}

function limpiarFiltros() {
  ['seccional', 'provincia', 'empleador'].forEach(c => { FILTRO[c] = []; });
  FILTRO.desde = FILTRO.hasta = '';
  CAL.eligiendo = false;
  cerrarCruce();
  cargar();
}

async function cargar() {
  try {
    const r = await fetch('/admin/encuesta/resultados?' + filtrosDeLaPantalla().toString());
    if (!r.ok) throw new Error(r.status);
    DATOS = await r.json();
    pintar();
  } catch (e) {
    // El cartel de los filtros se reemplaza al armarlos, así que puede no
    // existir todavía: el error igual tiene que verse en algún lado.
    const nota = $('f-nota');
    if (nota) nota.textContent = 'No se pudieron cargar los resultados.';
    else $('filtros').innerHTML = '<div class="f-nota">No se pudieron cargar los resultados.</div>';
  }
}

/* ---------- Pintar ---------- */

function pintar() {
  const d = DATOS;
  $('enc-titulo').textContent = d.encuesta.titulo;
  pintarFiltros(d);
  pintarDescarga(d);
  pintarIndicadores(d);
  pintarUmbral(d);
  pintarPreguntas(d);
  pintarHistorial(d);
}

function pintarFiltros(d) {
  const cortes = d.encuesta.cortes || [];
  const fijos = d.filtros.fijos || [];
  $('f-cuenta').textContent = cuantosFiltros();
  $('f-cuenta').classList.toggle('hay', cuantosFiltros() > 0);

  let html = '';
  cortes.forEach(corte => {
    const etiqueta = (CORTES[corte] || [corte])[0];
    const valores = (d.filtros.disponibles || {})[corte] || [];
    const fijo = fijos.includes(corte);
    // Con un solo valor no hay nada que filtrar: la pastilla ocuparía lugar
    // para decir "todos son de acá".
    if (valores.length < 2) return;
    html += `<div class="f-grupo">
        <span class="f-label">${esc(etiqueta)}${fijo ? ' · tu seccional' : ''}</span>
        <div class="m-chips">${valores.map(v => `
          <button type="button" class="m-chip ${FILTRO[corte].includes(v.valor) ? 'act' : ''}"
                  ${fijo ? 'disabled' : ''}
                  onclick="alternar('${corte}', '${esc(v.valor)}')">
            ${esc(v.etiqueta)} <span class="n">${v.cantidad}</span></button>`).join('')}
        </div>
      </div>`;
  });
  // El calendario solo si la encuesta duró más de un día: para una ventana
  // de un día es un control que no puede filtrar nada.
  const [vIni, vFin] = d.filtros.ventana || ['', ''];
  if (vIni && vFin && vIni !== vFin) {
    html += `<div class="f-grupo">
        <span class="f-label">Cuándo respondieron</span>
        <div class="cal" id="cal"></div>
      </div>`;
  }
  if (!cortes.length) {
    html = `<div class="f-nota">Esta encuesta anónima no guarda ningún corte:
      solo hay totales generales. Es lo que prometió el disclaimer que vio cada
      afiliado antes de responder.</div>` + html;
  }
  $('f-fila').innerHTML = html || '<div class="f-nota">Sin filtros disponibles.</div>';
  if ($('cal')) pintarCalendario(d);

  const partes = [];
  if (fijos.length) partes.push('Ves la encuesta recortada a tu seccional.');
  partes.push('Las pastillas se combinan: podés marcar varias a la vez.');
  if (FILTRO.desde || FILTRO.hasta) {
    partes.push('El rango de fechas recorta los gráficos y el ritmo, no el padrón: '
      + 'la urna guarda el día en que se respondió, pero el padrón no sabe cuándo '
      + 'respondió cada uno (y es a propósito, es lo que sostiene el anonimato).');
  }
  $('f-nota').textContent = partes.join(' ');
  $('f-limpiar').style.display = cuantosFiltros() ? '' : 'none';
}

/* ---------- Calendario: dos clics arman el rango ---------- */
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
               'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

function pintarCalendario(d) {
  const [vIni, vFin] = d.filtros.ventana;
  const conRespuesta = new Set((d.indicadores.ritmo || []).map(x => x.dia));
  if (!CAL.mes) CAL.mes = (FILTRO.desde || vFin).slice(0, 7);
  const [anio, mes] = CAL.mes.split('-').map(Number);
  const primero = new Date(anio, mes - 1, 1);
  const arranque = (primero.getDay() + 6) % 7;           // lunes primero
  const dias = new Date(anio, mes, 0).getDate();

  let celdas = '';
  for (let i = 0; i < arranque; i++) celdas += '<span></span>';
  for (let n = 1; n <= dias; n++) {
    const iso = `${anio}-${String(mes).padStart(2, '0')}-${String(n).padStart(2, '0')}`;
    const fuera = iso < vIni || iso > vFin;
    const ini = iso === FILTRO.desde, fin = iso === FILTRO.hasta;
    const dentro = FILTRO.desde && FILTRO.hasta && iso > FILTRO.desde && iso < FILTRO.hasta;
    const clases = ['cal-dia'];
    if (conRespuesta.has(iso)) clases.push('conresp');
    if (dentro) clases.push('rango');
    if (ini || fin) clases.push('extremo', ini && fin ? 'solo' : ini ? 'ini' : 'fin');
    celdas += `<button type="button" class="${clases.join(' ')}" ${fuera ? 'disabled' : ''}
      onclick="clicDia('${iso}')">${n}</button>`;
  }
  const anterior = `${anio}-${String(mes).padStart(2, '0')}-01` > vIni;
  const siguiente = `${anio}-${String(mes).padStart(2, '0')}-${dias}` < vFin;
  $('cal').innerHTML = `
    <div class="cal-nav">
      <button type="button" onclick="moverMes(-1)" ${anterior ? '' : 'disabled'}>‹</button>
      <b>${MESES[mes - 1]} ${anio}</b>
      <button type="button" onclick="moverMes(1)" ${siguiente ? '' : 'disabled'}>›</button>
    </div>
    <div class="cal-grid">
      ${['lu', 'ma', 'mi', 'ju', 'vi', 'sá', 'do'].map(x => `<span class="cal-dow">${x}</span>`).join('')}
      ${celdas}
    </div>
    <div class="cal-ayuda">${FILTRO.desde && !FILTRO.hasta
      ? 'Elegí el día de cierre' : FILTRO.desde
        ? `${fechaLegible(FILTRO.desde)} → ${fechaLegible(FILTRO.hasta)}`
        : 'Tocá dos días para armar un rango'}</div>`;
}

function moverMes(paso) {
  const [a, m] = CAL.mes.split('-').map(Number);
  const d = new Date(a, m - 1 + paso, 1);
  CAL.mes = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  pintarCalendario(DATOS);
}

function clicDia(iso) {
  if (!CAL.eligiendo) {
    FILTRO.desde = FILTRO.hasta = iso;
    CAL.eligiendo = true;
    pintarCalendario(DATOS);
    return;                       // todavía no consulto: falta el segundo clic
  }
  CAL.eligiendo = false;
  if (iso < FILTRO.desde) { FILTRO.hasta = FILTRO.desde; FILTRO.desde = iso; }
  else FILTRO.hasta = iso;
  cerrarCruce();
  cargar();
}

function pintarDescarga(d) {
  const btn = $('btn-csv');
  if (!btn) return;
  btn.href = '/admin/encuesta/exportar?' + filtrosDeLaPantalla().toString();
  // Con el grupo por debajo del umbral el servidor rechaza la descarga
  // igual. El botón lo dice ANTES y no deja navegar: si no, el admin se
  // come un JSON de error en pantalla completa en vez de una explicación.
  btn.dataset.frenado = d.oculto ? '1' : '';
  btn.style.opacity = d.oculto ? '.45' : '1';
  btn.title = d.oculto
    ? 'Este grupo no llega al umbral: tampoco se exporta'
    : (d.encuesta.modo === 'anonima'
      ? 'Conteos y porcentajes, con el umbral ya aplicado'
      : 'Una fila por persona, con nombre y CUIL');
  if (!btn.dataset.atado) {
    btn.dataset.atado = '1';
    btn.addEventListener('click', (ev) => {
      if (!btn.dataset.frenado) return;
      ev.preventDefault();
      alert('Este grupo tiene ' + DATOS.respondentes + ' respuestas y hacen falta '
        + DATOS.umbral.minimo + '. En una encuesta anónima un grupo chico deja de ser '
        + 'anónimo, así que tampoco se exporta. Sacá el filtro para bajar el total.');
    });
  }
}

function pintarIndicadores(d) {
  const i = d.indicadores;
  const p = i.participacion;
  $('k-part').textContent = `${p.respondieron} de ${p.padron}`;
  $('k-part-barra').style.width = Math.min(p.porcentaje, 100) + '%';
  $('k-part-pie').textContent = `${p.porcentaje}% del padrón respondió`;

  const a = i.avisos;
  $('k-leidos').textContent = a.enviados ? `${a.leidos} de ${a.enviados}` : 'Sin avisos';
  $('k-leidos-barra').style.width = Math.min(a.porcentaje, 100) + '%';
  $('k-leidos-pie').textContent = a.enviados
    ? `${a.porcentaje}% leyó · ${a.cantidad} envío${a.cantidad === 1 ? '' : 's'}`
    : 'Todavía no le avisaste a nadie';

  const total = (i.ritmo || []).reduce((s, x) => s + x.cantidad, 0);
  const ultimo = (i.ritmo || [])[i.ritmo.length - 1];
  $('k-ritmo').textContent = total || '—';
  $('k-ritmo-pie').textContent = ultimo
    ? `respuestas · última el ${fechaLegible(ultimo.dia)}`
    : 'sin respuestas todavía';
  dibujarRitmo(i.ritmo || []);

  const chip = $('k-estado');
  chip.textContent = i.estado;
  chip.className = 'chip ' + i.estado;
  $('k-estado-pie').textContent = d.encuesta.cerrada_en
    ? `Cerrada a mano el ${fechaLegible(d.encuesta.cerrada_en)}`
    : `${fechaLegible(d.encuesta.fecha_desde)} → ${fechaLegible(d.encuesta.fecha_hasta)}`;

  // La lectura de los dos primeros indicadores JUNTOS, que es de donde sale
  // la decisión de mandar o no un recordatorio.
  const nota = $('lectura-vs-respuesta');
  if (!a.enviados) {
    nota.textContent = 'Nadie recibió el aviso todavía: la participación de arriba no mide'
      + ' interés, mide que la encuesta no se comunicó.';
  } else if (a.porcentaje >= 60 && p.porcentaje < 30) {
    nota.textContent = `Leyeron el ${a.porcentaje}% y respondió el ${p.porcentaje}%: el aviso`
      + ' llegó y no engancha. Un recordatorio más no lo arregla — lo que falla es la encuesta.';
  } else if (a.porcentaje < 40) {
    nota.textContent = `Solo leyó el aviso el ${a.porcentaje}%: el problema es el canal, no la`
      + ' encuesta. Un recordatorio a los que faltan sí mueve la aguja.';
  } else {
    nota.textContent = `Leyeron el ${a.porcentaje}% y respondió el ${p.porcentaje}% del padrón.`;
  }
}

function pintarUmbral(d) {
  const caja = $('umbral');
  if (!d.oculto) { caja.hidden = true; return; }
  caja.hidden = false;
  caja.innerHTML = `<b>Este grupo tiene muy pocas respuestas para mostrarse</b>
    Hay ${d.respondentes} respuesta${d.respondentes === 1 ? '' : 's'} y hacen falta
    ${d.umbral.minimo}. En una encuesta anónima, un grupo chico deja de ser anónimo:
    con dos o tres respuestas de una misma seccional y una empresa, cualquiera sabe
    de quién son. El servidor no las cuenta ni las manda — no es que la pantalla
    las esconda. Sacá el filtro para ver el total general.`;
}

function pintarPreguntas(d) {
  const cont = $('preguntas');
  // Solo los de las preguntas: el del ritmo lo maneja dibujarRitmo, y
  // destruirlo acá lo dejaría en el mapa ya muerto.
  Object.keys(graficos).forEach(k => {
    if (k === 'ritmo') return;
    if (graficos[k] && graficos[k].destroy) graficos[k].destroy();
    delete graficos[k];
  });

  $('sub-preguntas').textContent = d.oculto ? ''
    : `${d.respondentes} ${d.respondentes === 1 ? 'persona respondió' : 'personas respondieron'}`
      + (cuantosFiltros() ? ' en este grupo' : '')
      + ' · tocá cualquier respuesta para ver dónde se concentra';

  if (d.oculto) { cont.innerHTML = ''; return; }
  if (!d.preguntas.length) {
    cont.innerHTML = '<div class="panel"><div class="sub">Todavía no entró ninguna respuesta.</div></div>';
    return;
  }
  cont.innerHTML = d.preguntas.map(p => `
    <div class="panel ${p.ancho === 'mitad' ? 'mitad' : p.ancho === 'tercio' ? 'tercio' : ''}">
      <div class="panel-enc">
        <div>
          <h3>${esc(p.etiqueta)}</h3>
          <div class="sub">${subtituloDe(p)}</div>
        </div>
        ${opcionesDeVista(p)}
      </div>
      <div id="c-${p.id}">${cuerpoDe(p)}</div>
    </div>`).join('');
  d.preguntas.forEach(p => dibujar(p));
}

// Tres formas de leer la misma pregunta. La TABLA no es un adorno: es la
// que da los números exactos, que en un gráfico hay que adivinar o buscar
// con el mouse.
const VISTAS = { barras: 'Barras', torta: 'Torta', tabla: 'Tabla' };

function opcionesDeVista(p) {
  if (!graficable(p)) return '';
  const actual = VISTA[p.id] || 'barras';
  const disponibles = p.tipo_dato === 'escala' || p.tipo_dato === 'ranking'
    ? ['barras', 'tabla'] : ['barras', 'torta', 'tabla'];
  return `<div class="g-ops">${disponibles.map(v =>
    `<button type="button" class="${v === actual ? 'act' : ''}"
             onclick="cambiarVista(${p.id}, '${v}')">${VISTAS[v]}</button>`).join('')}</div>`;
}

function graficable(p) {
  return ['escala', 'ranking', 'seleccion', 'opcion_unica', 'multiple', 'booleano', 'fecha']
    .includes(p.tipo_dato);
}

function cambiarVista(id, vista) {
  VISTA[id] = vista;
  const p = DATOS.preguntas.find(x => x.id === id);
  if (!p) return;
  if (graficos[id] && graficos[id].destroy) { graficos[id].destroy(); delete graficos[id]; }
  const panel = $('c-' + id);
  panel.innerHTML = cuerpoDe(p);
  panel.closest('.panel').querySelector('.g-ops').outerHTML = opcionesDeVista(p);
  dibujar(p);
}

function subtituloDe(p) {
  if (p.tipo_dato === 'multiple') {
    // En una múltiple no se puede saber cuánta GENTE respondió sin un
    // vínculo que la urna no tiene: se informan marcas y se dice así.
    return `${p.respondieron} marca${p.respondieron === 1 ? '' : 's'} · se podía elegir más de una`;
  }
  const n = p.respondieron;
  return `${n} respuesta${n === 1 ? '' : 's'}`;
}

function cuerpoDe(p) {
  const vista = VISTA[p.id] || 'barras';
  if (p.tipo_dato === 'escala') {
    const e = p.escala;
    const resumen = `<div class="resumen-escala">
        <div class="destaca"><b>${e.promedio === null ? '—' : e.promedio}</b>promedio</div>
        <div><b>${e.mediana === null ? '—' : e.mediana}</b>mediana</div>
        <div><b>${e.altos.porcentaje}%</b>en los más altos${e.etiqueta_max
          ? ` (${esc(e.etiqueta_max)})` : ''}</div>
        <div><b>${e.bajos.porcentaje}%</b>en los más bajos${e.etiqueta_min
          ? ` (${esc(e.etiqueta_min)})` : ''}</div>
      </div>`;
    if (vista === 'tabla') return resumen + tablaDe(p, e.distribucion.map(x =>
      ({ clave: x.valor, texto: String(x.valor), cantidad: x.cantidad, porcentaje: x.porcentaje })));
    return resumen + `<div class="grafico" style="height:170px"><canvas id="g-${p.id}"></canvas></div>`
      ;
  }
  if (p.tipo_dato === 'numero') {
    const n = p.numero;
    return `<div class="resumen-escala">
      <div class="destaca"><b>${n.promedio === null ? '—' : n.promedio}</b>promedio</div>
      <div><b>${n.minimo === null ? '—' : n.minimo}</b>mínimo</div>
      <div><b>${n.maximo === null ? '—' : n.maximo}</b>máximo</div></div>`;
  }
  if (p.tipo_dato === 'texto') {
    if (!p.textos.length) return '<div class="sub">Sin respuestas.</div>';
    return `<ul class="lista-textos">${p.textos.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`;
  }
  if (p.tipo_dato === 'fecha') {
    if (!p.fechas.length) return '<div class="sub">Sin respuestas.</div>';
    if (vista === 'tabla') return tablaDe(p, p.fechas.map(x =>
      ({ clave: x.valor, texto: fechaLegible(x.valor), cantidad: x.cantidad, porcentaje: null })));
    return `<div class="grafico" style="height:170px"><canvas id="g-${p.id}"></canvas></div>`;
  }
  if (p.tipo_dato === 'ranking') {
    if (vista === 'tabla') return tablaRanking(p);
    return `<div class="grafico" style="height:${alturaDe(p)}px"><canvas id="g-${p.id}"></canvas></div>`;
  }
  const ops = (p.opciones || []).map(x =>
    ({ clave: x.indice, texto: x.texto, cantidad: x.cantidad, porcentaje: x.porcentaje }));
  if (vista === 'tabla') return tablaDe(p, ops);
  return `<div class="grafico" style="height:${alturaDe(p)}px"><canvas id="g-${p.id}"></canvas></div>`;
}

function tablaDe(p, filas) {
  const total = filas.reduce((s, x) => s + x.cantidad, 0) || 1;
  return `<table class="datos">
    <tr><th>Respuesta</th><th class="num">Cantidad</th><th class="num">%</th></tr>
    ${filas.map(x => `<tr class="clicable" onclick="abrirCruce(${p.id}, '${esc(x.clave)}')">
        <td>${esc(x.texto)}</td>
        <td class="num">${x.cantidad}</td>
        <td class="num">${x.porcentaje === null
          ? Math.round(x.cantidad * 1000 / total) / 10 : x.porcentaje}%</td>
      </tr>`).join('')}
  </table>`;
}

function tablaRanking(p) {
  return `<table class="datos">
    <tr><th>Opción</th><th class="num">Pos. promedio</th><th class="num">1.ª</th></tr>
    ${p.ranking.map(x => `<tr class="clicable" onclick="abrirCruce(${p.id}, '${x.indice}')">
        <td>${esc(x.texto)}</td>
        <td class="num">${x.promedio === null ? '—' : x.promedio}</td>
        <td class="num">${x.primeras}</td>
      </tr>`).join('')}
  </table>`;
}

function alturaDe(p) {
  const filas = (p.ranking || p.opciones || []).length;
  return Math.max(120, 34 * filas);
}

/* ---------- Chart.js ---------- */

function paleta() {
  return {
    apoyo: css('--marca-apoyo') || '#2fa88f',
    acento: css('--marca-acento') || '#e8a33d',
    primario: css('--marca-primario') || '#1a3d6b',
    linea: css('--linea') || '#e4e7ec',
    gris: css('--gris') || '#5b6478',
  };
}

// Serie de colores para la torta: la marca primero, después variaciones
// suyas. Nada de un arcoíris -- son partes de un mismo total.
function tonos(n, base) {
  const salida = [];
  for (let i = 0; i < n; i++) {
    const claro = n === 1 ? 0 : (i / (n - 1)) * 58;
    salida.push(`color-mix(in srgb, ${base} ${100 - claro}%, white)`);
  }
  return salida;
}

function dibujar(p) {
  const vista = VISTA[p.id] || 'barras';
  if (vista === 'tabla') return;
  const cv = document.getElementById('g-' + p.id);
  if (!cv) return;
  const c = paleta();

  if (p.tipo_dato === 'escala') {
    const dist = p.escala.distribucion;
    graficos[p.id] = new Chart(cv, {
      type: 'bar',
      data: { labels: dist.map(x => x.valor),
              datasets: [{ data: dist.map(x => x.cantidad), backgroundColor: c.apoyo,
                           borderRadius: 5 }] },
      options: opciones({ horizontal: false, filas: dist, c, pregunta: p,
                          claves: dist.map(x => x.valor) }),
    });
    return;
  }
  if (p.tipo_dato === 'ranking') {
    // La posición promedio NO se grafica cruda: "1" es lo más prioritario y
    // una barra corta leyéndose como "lo más importante" es exactamente al
    // revés de lo que el ojo espera. Se grafica la prioridad --(n+1) menos
    // la posición promedio--, que arranca en cero y se lee sola; la posición
    // real va en el tooltip, que es donde se la busca.
    const filas = p.ranking.filter(x => x.promedio !== null);
    const n = p.ranking.length;
    graficos[p.id] = new Chart(cv, {
      type: 'bar',
      data: { labels: filas.map(x => x.texto),
              datasets: [{ data: filas.map(x => +((n + 1) - x.promedio).toFixed(2)),
                           backgroundColor: c.acento, borderRadius: 5 }] },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        onClick: (ev, els) => { if (els.length) abrirCruce(p.id, filas[els[0].index].indice); },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (x) => {
            const f = filas[x.dataIndex];
            return `posición promedio ${f.promedio} de ${n} · ${f.primeras} la pusieron primera`;
          } } },
        },
        scales: {
          x: { beginAtZero: true, max: n, grid: { color: c.linea },
               title: { display: true, text: 'prioridad (más larga = más prioritaria)' } },
          y: { grid: { display: false } },
        },
      },
    });
    return;
  }
  if (p.tipo_dato === 'fecha') {
    graficos[p.id] = new Chart(cv, {
      type: 'bar',
      data: { labels: p.fechas.map(x => diaCorto(x.valor)),
              datasets: [{ data: p.fechas.map(x => x.cantidad), backgroundColor: c.apoyo,
                           borderRadius: 5 }] },
      options: opciones({ horizontal: false, filas: p.fechas, c }),
    });
    return;
  }
  const ops = p.opciones || [];
  if (vista === 'torta') {
    graficos[p.id] = new Chart(cv, {
      type: 'doughnut',
      data: { labels: ops.map(x => x.texto),
              datasets: [{ data: ops.map(x => x.cantidad), backgroundColor: tonos(ops.length, c.apoyo),
                           borderWidth: 2, borderColor: '#fff' }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '52%',
        onClick: (ev, els) => { if (els.length) abrirCruce(p.id, ops[els[0].index].indice); },
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 10, font: { size: 11 } } },
          tooltip: { callbacks: { label: (x) =>
            ` ${ops[x.dataIndex].cantidad} · ${ops[x.dataIndex].porcentaje}%` } },
        },
      },
    });
    return;
  }
  graficos[p.id] = new Chart(cv, {
    type: 'bar',
    data: { labels: ops.map(x => x.texto),
            datasets: [{ data: ops.map(x => x.cantidad), backgroundColor: c.apoyo,
                         borderRadius: 5 }] },
    options: opciones({ horizontal: true, filas: ops, c, pregunta: p,
                        claves: ops.map(x => x.indice) }),
  });
}

function opciones({ horizontal, filas, c, pregunta, claves }) {
  return {
    indexAxis: horizontal ? 'y' : 'x',
    responsive: true, maintainAspectRatio: false,
    // Tocar una barra abre el cruce: es la diferencia entre un gráfico que
    // se mira y uno con el que se trabaja.
    onClick: (ev, els) => {
      if (els.length && pregunta && claves) abrirCruce(pregunta.id, claves[els[0].index]);
    },
    onHover: (ev, els) => {
      ev.native.target.style.cursor = (els.length && pregunta) ? 'pointer' : 'default';
    },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (x) => {
        const fila = filas && filas[x.dataIndex];
        const valor = x.parsed[horizontal ? 'x' : 'y'];
        return fila && fila.porcentaje !== undefined && fila.porcentaje !== null
          ? ` ${valor} · ${fila.porcentaje}%` : ` ${valor}`;
      } } },
    },
    scales: {
      x: { beginAtZero: true, grid: { color: c.linea }, ticks: { precision: 0 } },
      y: { beginAtZero: true, grid: { display: !horizontal, color: c.linea },
           ticks: { precision: 0 } },
    },
  };
}

function dibujarRitmo(serie) {
  const cv = $('c-ritmo');
  if (!cv) return;
  if (graficos.ritmo) graficos.ritmo.destroy();
  graficos.ritmo = new Chart(cv, {
    type: 'line',
    data: {
      labels: serie.map(x => diaCorto(x.dia)),
      datasets: [{
        data: serie.map(x => x.cantidad),
        borderColor: css('--marca-primario') || '#1a3d6b',
        backgroundColor: 'transparent', tension: .3, pointRadius: serie.length > 20 ? 0 : 2,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
                 tooltip: { callbacks: { title: (c) => serie[c[0].dataIndex].dia } } },
      scales: { x: { display: false }, y: { display: false, beginAtZero: true } },
    },
  });
}

/* ---------- El cruce: tocar una respuesta y ver dónde se concentra ----
 *
 * Es la pregunta que un sindicato hace de verdad mirando un gráfico: "el
 * 30% dice que el ambiente está tenso... ¿tenso DÓNDE?". Un total no se
 * puede accionar; "el 62% de la sucursal Centro" sí.
 *
 * Lo que se muestra no es el conteo pelado sino la DIFERENCIA contra el
 * general: un conteo no dice si algo se concentra, la distancia sí.
 */
function abrirCruce(preguntaId, opcion) {
  const q = filtrosDeLaPantalla();
  q.set('pregunta', preguntaId);
  q.set('opcion', opcion);
  $('cruce').classList.add('abierto');
  $('velo').classList.add('abierto');
  $('cr-cuerpo').innerHTML = '<div class="sub">Calculando…</div>';
  fetch('/admin/encuesta/cruce?' + q.toString())
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(pintarCruce)
    .catch(() => { $('cr-cuerpo').innerHTML =
      '<div class="sub">No se pudo calcular el cruce.</div>'; });
}

function cerrarCruce() {
  $('cruce').classList.remove('abierto');
  $('velo').classList.remove('abierto');
}

function pintarCruce(d) {
  $('cr-pregunta').textContent = d.pregunta;
  $('cr-opcion').textContent = d.opcion;
  $('cr-cuantos').textContent = d.oculto
    ? `${d.elegidos} de ${d.total}`
    : `${d.elegidos} de ${d.total} respuestas · ${d.porcentaje}%`;

  if (d.oculto) {
    $('cr-cuerpo').innerHTML = `<div class="cr-nota">
      <b>Muy pocas respuestas para abrirlas</b>
      Eligieron esta opción ${d.elegidos} personas y hacen falta ${d.umbral}. En una encuesta
      anónima, abrir un grupo chico por seccional o por empleador deja de ser anónimo:
      con dos o tres respuestas, cualquiera sabe de quién son. El servidor no las
      calcula — no es que la pantalla las esconda.</div>`;
    return;
  }

  let html = '';
  Object.keys(d.cortes).forEach(corte => {
    const bloque = d.cortes[corte];
    const nombre = (CORTES[corte] || [corte])[0];
    if (bloque.filas.length < 2) return;
    html += `<h4>Por ${esc(nombre.toLowerCase())}</h4>
      <div class="sub">Qué porcentaje eligió «${esc(d.opcion)}» en cada uno.
        El general es ${bloque.general}%.</div>`;
    bloque.filas.forEach(f => {
      const signo = f.diferencia > 0 ? 'mas' : f.diferencia < 0 ? 'menos' : 'igual';
      html += `<div class="cr-fila">
          <span class="nom">${esc(f.etiqueta)}<small>${f.cantidad} de ${f.base} respuestas</small></span>
          <span class="pct">${f.dentro}%</span>
          <span class="cr-dif ${signo}">${f.diferencia > 0 ? '+' : ''}${f.diferencia}</span>
          <span class="cr-barra"><i style="width:${Math.min(f.dentro, 100)}%"></i></span>
        </div>`;
    });
    if (bloque.escondidos) {
      html += `<div class="sub" style="margin-top:6px;">${bloque.escondidos}
        grupo${bloque.escondidos === 1 ? '' : 's'} no se muestra${bloque.escondidos === 1 ? '' : 'n'}:
        tienen menos respuestas que el umbral.</div>`;
    }
  });

  if (d.preguntas.length) {
    html += `<h4>Qué más respondió este grupo</h4>
      <div class="sub">Las otras preguntas, contestadas por las mismas
        ${d.preguntas[0].personas} personas.</div>`;
    d.preguntas.forEach(p => {
      html += `<div style="margin-bottom:12px;"><b style="font-size:13px;">${esc(p.etiqueta)}</b>`;
      if (p.tipo_dato === 'escala') {
        html += `<div class="sub">promedio ${p.promedio === null ? '—' : p.promedio}</div>`;
      } else {
        p.opciones.filter(o => o.cantidad).slice(0, 4).forEach(o => {
          html += `<div class="cr-fila">
            <span class="nom">${esc(o.texto)}</span>
            <span class="pct">${o.porcentaje}%</span><span></span>
            <span class="cr-barra"><i style="width:${Math.min(o.porcentaje, 100)}%"></i></span>
          </div>`;
        });
      }
      html += '</div>';
    });
  } else if (!d.puede_cruzar_preguntas) {
    // No es una limitación técnica que haya que disculpar: es la garantía.
    html += `<div class="cr-nota">
      <b>Con las otras preguntas no se puede cruzar</b>
      Esta encuesta es anónima: saber que esta respuesta y otra son de la misma
      persona es justamente lo que la urna no guarda. Se puede ver dónde se
      concentra —seccional, empleador, provincia—, porque eso viaja pegado a
      cada respuesta, pero no qué contestó después el mismo afiliado. En una
      encuesta nominal sí aparece acá.</div>`;
  }

  $('cr-cuerpo').innerHTML = html || '<div class="sub">Sin datos para cruzar.</div>';
}

document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') cerrarCruce(); });

/* ---------- Historial ---------- */

const NOMBRE_EVENTO = {
  edicion: 'Corrección de texto', prorroga: 'Prórroga', cierre: 'Cierre',
  lanzamiento: 'Aviso de lanzamiento', recordatorio: 'Recordatorio',
  noticia: 'Noticia publicada', publicada: 'Publicación', duplicada: 'Duplicada',
  descarga: 'Descarga',
};

function pintarHistorial(d) {
  const filas = d.historial || [];
  $('historial').innerHTML = filas.length
    ? filas.map(v => `<tr>
        <td class="fecha">${esc(selloLegible(v.fecha))}</td>
        <td><b>${esc(NOMBRE_EVENTO[v.evento] || v.evento)}</b></td>
        <td>${esc(v.detalle || '')}</td>
        <td>${esc(v.usuario || '')}</td>
      </tr>`).join('')
    : '<tr><td class="sub">Todavía no hay nada registrado.</td></tr>';
}

/* ---------- Evolución entre tomas (N23) ---------- */
// Se pide UNA vez y no con cada filtro: compara TOMAS, no grupos. Es lo que
// convierte un dato suelto en una herramienta de gestión -- "esto veníamos
// midiendo hace un año".
async function cargarEvolucion() {
  try {
    const r = await fetch('/admin/encuesta/evolucion?id=' + ENCUESTA_ID);
    if (!r.ok) return;
    const d = await r.json();
    if (!d.preguntas.length) return;      // sin con qué comparar, no hay sección
    $('evolucion-seccion').hidden = false;
    $('sub-evolucion').textContent = `${d.tomas.length} tomas de la misma encuesta`;
    $('evolucion').innerHTML = d.preguntas.map((p, i) => `
      <div class="panel mitad">
        <h3>${esc(p.etiqueta)}</h3>
        <div class="sub">${p.tipo_dato === 'escala' ? 'promedio por toma'
          : p.tipo_dato === 'ranking' ? 'posición promedio por toma (más arriba = más prioritario)'
          : '% por toma'}</div>
        <div class="grafico" style="height:210px"><canvas id="ev-${i}"></canvas></div>
      </div>`).join('');
    d.preguntas.forEach((p, i) => dibujarEvolucion(i, p, d.tomas));
  } catch (e) { /* la evolución es un extra: si falla, el dashboard sigue */ }
}

const COLORES_EV = ['--marca-apoyo', '--marca-acento', '--marca-primario', '--gris'];

function dibujarEvolucion(i, p, tomas) {
  const cv = document.getElementById('ev-' + i);
  if (!cv) return;
  graficos['ev' + i] = new Chart(cv, {
    type: 'line',
    data: {
      labels: tomas.map(t => t.fecha_hasta ? diaCorto(t.fecha_hasta) : t.titulo),
      datasets: p.lineas.map((l, n) => ({
        label: l.nombre,
        data: l.valores,
        borderColor: css(COLORES_EV[n % COLORES_EV.length]) || '#2fa88f',
        backgroundColor: 'transparent', tension: .25, borderWidth: 2, pointRadius: 3,
        // Una toma por debajo del umbral no aporta punto; la línea sigue de
        // largo en vez de cortarse y hacer pensar que ahí no hubo encuesta.
        spanGaps: true,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: p.lineas.length > 1, position: 'bottom',
                  labels: { boxWidth: 10, font: { size: 11 } } },
        tooltip: { callbacks: { title: (c) => tomas[c[0].dataIndex].titulo } },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: p.tipo_dato !== 'ranking',
             reverse: p.tipo_dato === 'ranking',
             grid: { color: css('--linea') || '#e4e7ec' } },
      },
    },
  });
}

cargar();
cargarEvolucion();
