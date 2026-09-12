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
  document.querySelectorAll('select.f-select').forEach(sel => {
    if (sel.value) q.append(sel.dataset.corte, sel.value);
  });
  return q;
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
  pintarIndicadores(d);
  pintarUmbral(d);
  pintarPreguntas(d);
  pintarHistorial(d);
}

function pintarFiltros(d) {
  const cont = $('filtros');
  const cortes = d.encuesta.cortes || [];
  // El desplegable se arma una sola vez: si se rehiciera en cada consulta,
  // recargar cerraría el que el admin acaba de abrir.
  if (!cont.dataset.armado) {
    cont.dataset.armado = '1';
    let html = '';
    cortes.forEach(corte => {
      const etiqueta = (CORTES[corte] || [corte])[0];
      const valores = (d.filtros.disponibles || {})[corte] || [];
      const fijo = (d.filtros.fijos || []).includes(corte);
      const elegido = ((d.filtros.aplicados || {})[corte] || [])[0] || '';
      html += `<div class="f-grupo">
          <label class="f-label" for="f-${corte}">${esc(etiqueta)}</label>
          <select class="f-select" id="f-${corte}" data-corte="${corte}" ${fijo ? 'disabled' : ''}>
            <option value="">Todas</option>
            ${valores.map(v => `<option value="${esc(v.valor)}" ${v.valor === elegido ? 'selected' : ''}>
                ${esc(v.etiqueta)} (${v.cantidad})</option>`).join('')}
          </select>
        </div>`;
    });
    if (!cortes.length) {
      html = `<div class="f-nota">Esta encuesta anónima no guarda ningún corte:
        solo hay totales generales. Es lo que prometió el disclaimer que vio
        cada afiliado antes de responder.</div>`;
    } else {
      const fijos = (d.filtros.fijos || []).length;
      html += `<div class="f-nota" id="f-nota">${fijos
        ? 'Ves la encuesta recortada a tu seccional.'
        : 'Los gráficos y los indicadores se recalculan con el filtro.'}</div>`;
    }
    cont.innerHTML = html;
    cont.querySelectorAll('select.f-select').forEach(sel => {
      sel.addEventListener('change', () => {
        sel.classList.toggle('act', !!sel.value);
        cargar();
      });
      sel.classList.toggle('act', !!sel.value);
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
      + ((d.filtros.aplicados && Object.keys(d.filtros.aplicados).length) ? ' en este grupo' : '');

  if (d.oculto) { cont.innerHTML = ''; return; }
  if (!d.preguntas.length) {
    cont.innerHTML = '<div class="panel"><div class="sub">Todavía no entró ninguna respuesta.</div></div>';
    return;
  }
  cont.innerHTML = d.preguntas.map(p => `
    <div class="panel ${p.ancho === 'mitad' ? 'mitad' : p.ancho === 'tercio' ? 'tercio' : ''}">
      <h3>${esc(p.etiqueta)}</h3>
      <div class="sub">${subtituloDe(p)}</div>
      ${cuerpoDe(p)}
    </div>`).join('');
  d.preguntas.forEach(p => dibujar(p));
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
  if (p.tipo_dato === 'escala') {
    const e = p.escala;
    return `<div class="prom"><b>${e.promedio === null ? '—' : e.promedio}</b>
        <span>promedio de ${e.min} a ${e.max}${e.etiqueta_min
          ? ` · ${esc(e.etiqueta_min)} → ${esc(e.etiqueta_max)}` : ''}</span></div>
      <div class="grafico" style="height:170px"><canvas id="g-${p.id}"></canvas></div>`;
  }
  if (p.tipo_dato === 'numero') {
    const n = p.numero;
    return `<div class="nums">
      <div><b>${n.promedio === null ? '—' : n.promedio}</b>promedio</div>
      <div><b>${n.minimo === null ? '—' : n.minimo}</b>mínimo</div>
      <div><b>${n.maximo === null ? '—' : n.maximo}</b>máximo</div></div>`;
  }
  if (p.tipo_dato === 'texto') {
    if (!p.textos.length) return '<div class="sub">Sin respuestas.</div>';
    return `<ul class="lista-textos">${p.textos.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`;
  }
  if (p.tipo_dato === 'fecha') {
    if (!p.fechas.length) return '<div class="sub">Sin respuestas.</div>';
    return `<div class="grafico" style="height:170px"><canvas id="g-${p.id}"></canvas></div>`;
  }
  return `<div class="grafico" style="height:${alturaDe(p)}px"><canvas id="g-${p.id}"></canvas></div>`;
}

function alturaDe(p) {
  const filas = (p.ranking || p.opciones || []).length;
  return Math.max(120, 34 * filas);
}

/* ---------- Chart.js ---------- */

function dibujar(p) {
  const cv = document.getElementById('g-' + p.id);
  if (!cv) return;
  const apoyo = css('--marca-apoyo') || '#2fa88f';
  const acento = css('--marca-acento') || '#e8a33d';
  const linea = css('--linea') || '#e4e7ec';

  if (p.tipo_dato === 'escala') {
    const dist = p.escala.distribucion;
    graficos[p.id] = new Chart(cv, {
      type: 'bar',
      data: {
        labels: dist.map(x => x.valor),
        datasets: [{ data: dist.map(x => x.cantidad), backgroundColor: apoyo, borderRadius: 5 }],
      },
      options: opciones({ horizontal: false, dist, linea }),
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
      data: {
        labels: filas.map(x => x.texto),
        datasets: [{ data: filas.map(x => +((n + 1) - x.promedio).toFixed(2)),
                     backgroundColor: acento, borderRadius: 5 }],
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => {
            const f = filas[c.dataIndex];
            return `posición promedio ${f.promedio} de ${n} · ${f.primeras}`
              + ` la pusieron primera`;
          } } },
        },
        scales: {
          x: { beginAtZero: true, max: n, grid: { color: linea },
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
      data: {
        labels: p.fechas.map(x => diaCorto(x.valor)),
        datasets: [{ data: p.fechas.map(x => x.cantidad), backgroundColor: apoyo, borderRadius: 5 }],
      },
      options: opciones({ horizontal: false, linea }),
    });
    return;
  }
  const ops = p.opciones || [];
  graficos[p.id] = new Chart(cv, {
    type: 'bar',
    data: {
      labels: ops.map(x => x.texto),
      datasets: [{ data: ops.map(x => x.cantidad), backgroundColor: apoyo, borderRadius: 5 }],
    },
    options: opciones({ horizontal: true, ops, linea }),
  });
}

function opciones({ horizontal, ops, dist, linea }) {
  const porcentajes = ops || dist;
  return {
    indexAxis: horizontal ? 'y' : 'x',
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (c) => {
        const fila = porcentajes && porcentajes[c.dataIndex];
        return fila && fila.porcentaje !== undefined
          ? `${c.parsed[horizontal ? 'x' : 'y']} · ${fila.porcentaje}%`
          : String(c.parsed[horizontal ? 'x' : 'y']);
      } } },
    },
    scales: {
      x: { beginAtZero: true, grid: { color: linea },
           ticks: { precision: 0 } },
      y: { beginAtZero: true, grid: { display: !horizontal, color: linea },
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

cargar();
