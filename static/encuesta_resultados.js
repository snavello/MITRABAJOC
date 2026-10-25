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
let CAL = { mes: null, eligiendo: false, abierto: false, previo: { desde: '', hasta: '' } };

function esc(t) {
  return String(t == null ? '' : t).replace(/[<>&"]/g, c =>
    ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

function css(nombre) {
  return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
}

// Los números en castellano de acá: coma decimal ("54,7") y el % con un
// espacio fino delante ("54,7 %"), como la app ya escribe los importes.
const FORMATO = { 1: new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }),
                  2: new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 }) };
function num(x, decimales = 1) {
  if (x === null || x === undefined || x === '') return '—';
  const n = Number(x);
  return Number.isFinite(n) ? FORMATO[decimales].format(n) : String(x);
}
function pct(x) { return x === null || x === undefined ? '—' : num(x) + '\u202f%'; }
function dif(x) { return (x > 0 ? '+' : '') + num(x); }

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
  CAL.abierto = false;
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
  pintarBajada(d);
  pintarFiltros(d);
  pintarDescarga(d);
  pintarIndicadores(d);
  pintarMapa(d);
  pintarUmbral(d);
  pintarPreguntas(d);
  pintarHistorial(d);
}

// Debajo del título, qué es esta encuesta en una línea: modo, estado y
// ventana ("Anónima · abierta del 16/10 al 06/11/2026").
function pintarBajada(d) {
  const e = d.encuesta, estado = (d.indicadores || {}).estado || '';
  const modo = e.modo === 'anonima' ? 'Anónima' : e.modo === 'nominal' ? 'Nominal' : '';
  const corto = iso => fechaLegible(iso).slice(0, 5);
  let cuando = '';
  if (e.fecha_desde && e.fecha_hasta) {
    const verbo = estado === 'cerrada' ? 'cerrada' : estado === 'abierta' ? 'abierta'
      : estado === 'programada' ? 'programada' : estado;
    cuando = `${verbo} del ${corto(e.fecha_desde)} al ${fechaLegible(e.fecha_hasta)}`;
    if (e.cerrada_en) cuando = `cerrada a mano el ${fechaLegible(e.cerrada_en)}`;
  } else if (estado) cuando = estado;
  $('enc-bajada').textContent = [modo, cuando].filter(Boolean).join(' · ');
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
        <div class="m-chips">${valores.map(v => {
          // La pastilla muestra cuánta gente queda DENTRO de lo ya filtrado,
          // y al lado el total cuando son distintos: "3 / 11" dice de una
          // que el filtro de al lado se llevó puestos a ocho.
          const recortado = v.total !== undefined && v.cantidad !== v.total;
          const clases = ['m-chip', FILTRO[corte].includes(v.valor) ? 'act' : '',
                          v.cantidad === 0 ? 'vacio' : ''].join(' ').trim();
          return `<button type="button" class="${clases}" ${fijo ? 'disabled' : ''}
                  title="${esc(v.etiqueta)}: ${v.cantidad} ${v.cantidad === 1 ? 'respuesta' : 'respuestas'}${
                    recortado ? ' con los filtros puestos, ' + v.total + ' en total' : ''}"
                  onclick="alternar('${corte}', '${esc(v.valor)}')">
            ${esc(v.etiqueta)} <span class="n">${v.cantidad}${
              recortado ? `<i>/${v.total}</i>` : ''}</span></button>`;
        }).join('')}
        </div>
      </div>`;
  });
  // El calendario solo si la encuesta duró más de un día: para una ventana
  // de un día es un control que no puede filtrar nada. Va plegado en un
  // botón que dice el rango: abierto, estiraba la caja hasta 400 px.
  const [vIni, vFin] = d.filtros.ventana || ['', ''];
  if (vIni && vFin && vIni !== vFin) {
    html += `<div class="f-grupo f-cuando">
        <span class="f-label" id="cal-rotulo">Cuándo respondieron</span>
        <button type="button" class="cal-boton ${FILTRO.desde ? 'act' : ''}" id="cal-boton"
                aria-expanded="${CAL.abierto ? 'true' : 'false'}" aria-controls="cal-globo"
                aria-describedby="cal-rotulo" onclick="alternarCalendario()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>
          <span>${textoRango()}</span>
          <svg class="flecha" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <div class="cal-globo" id="cal-globo" ${CAL.abierto ? '' : 'hidden'}><div class="cal" id="cal"></div></div>
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
  if (cuantosFiltros()) {
    partes.push('Los números de las pastillas se recalculan contra lo que ya está '
      + 'filtrado: "3 / 11" quiere decir que de los 11 de ese grupo, 3 quedan dentro '
      + 'del recorte actual. Cada corte se cuenta con los OTROS filtros puestos, no '
      + 'con el suyo, para que siempre se pueda cambiar de opinión.');
  }
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

function textoRango() {
  if (!FILTRO.desde) return 'Todo el período';
  if (CAL.eligiendo) return `Desde el ${fechaLegible(FILTRO.desde)}…`;
  if (FILTRO.desde === FILTRO.hasta) return `El ${fechaLegible(FILTRO.desde)}`;
  return `${fechaLegible(FILTRO.desde).slice(0, 5)} → ${fechaLegible(FILTRO.hasta)}`;
}

function alternarCalendario(abrir) {
  const globo = $('cal-globo');
  if (!globo) return;
  const quiere = abrir === undefined ? globo.hidden : abrir;
  if (!quiere && CAL.eligiendo) {
    // Se cerró con un solo día tocado: vuelve el rango de antes, no queda
    // un filtro a medio armar que la pantalla no consultó.
    FILTRO.desde = CAL.previo.desde; FILTRO.hasta = CAL.previo.hasta;
    CAL.eligiendo = false;
  }
  CAL.abierto = quiere;
  globo.hidden = !quiere;
  $('cal-boton').setAttribute('aria-expanded', quiere ? 'true' : 'false');
  $('cal-boton').querySelector('span').textContent = textoRango();
  if (quiere) pintarCalendario(DATOS);
}

document.addEventListener('click', (ev) => {
  if (CAL.abierto && !ev.target.closest('.f-cuando')) alternarCalendario(false);
});

function pintarCalendario(d) {
  const [vIni, vFin] = d.filtros.ventana;
  const ritmo = d.indicadores.ritmo || [];
  const conRespuesta = new Set(ritmo.map(x => x.dia));
  // Abre en el mes de la última respuesta, no en el del cierre: una
  // encuesta abierta hasta noviembre mostraba un mes vacío.
  const ultima = ritmo.length ? ritmo[ritmo.length - 1].dia : vFin;
  if (!CAL.mes) CAL.mes = (FILTRO.desde || ultima || vFin).slice(0, 7);
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
      <button type="button" onclick="moverMes(-1)" ${anterior ? '' : 'disabled'} aria-label="Mes anterior"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg></button>
      <b>${MESES[mes - 1]} ${anio}</b>
      <button type="button" onclick="moverMes(1)" ${siguiente ? '' : 'disabled'} aria-label="Mes siguiente"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg></button>
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
    CAL.previo = { desde: FILTRO.desde, hasta: FILTRO.hasta };
    FILTRO.desde = FILTRO.hasta = iso;
    CAL.eligiendo = true;
    pintarCalendario(DATOS);
    $('cal-boton').querySelector('span').textContent = textoRango();
    return;                       // todavía no consulto: falta el segundo clic
  }
  CAL.eligiendo = false;
  CAL.abierto = false;            // con el rango armado, el globo se cierra
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
  $('k-part').textContent = `${num(p.respondieron)} de ${num(p.padron)}`;
  $('k-part-barra').style.width = Math.min(p.porcentaje, 100) + '%';
  $('k-part-pie').textContent = `${pct(p.porcentaje)} del padrón respondió`;

  const a = i.avisos;
  $('k-leidos').textContent = a.enviados ? `${num(a.leidos)} de ${num(a.enviados)}` : 'Sin avisos';
  $('k-leidos-barra').style.width = Math.min(a.porcentaje, 100) + '%';
  $('k-leidos-pie').textContent = a.enviados
    ? `${pct(a.porcentaje)} leyó · ${a.cantidad} envío${a.cantidad === 1 ? '' : 's'}`
    : 'Todavía no le avisaste a nadie';

  const total = (i.ritmo || []).reduce((s, x) => s + x.cantidad, 0);
  const ultimo = (i.ritmo || [])[i.ritmo.length - 1];
  $('k-ritmo').textContent = total ? num(total) : '—';
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
    nota.textContent = `Leyeron el ${pct(a.porcentaje)} y respondió el ${pct(p.porcentaje)}: el aviso`
      + ' llegó y no engancha. Un recordatorio más no lo arregla — lo que falla es la encuesta.';
  } else if (a.porcentaje < 40) {
    nota.textContent = `Solo leyó el aviso el ${pct(a.porcentaje)}: el problema es el canal, no la`
      + ' encuesta. Un recordatorio a los que faltan sí mueve la aguja.';
  } else {
    nota.textContent = `Leyeron el ${pct(a.porcentaje)} y respondió el ${pct(p.porcentaje)} del padrón.`;
  }
}

/* ---------- Mapa de participación por seccional ----------
 *
 * Es la pastilla de seccional dibujada sobre un mapa: tocar una burbuja llama
 * al MISMO `alternar('seccional', ...)` que la pastilla, así que no hay dos
 * estados que se puedan desincronizar. Y por eso el mapa IGNORA el filtro de
 * seccional (viene así del servidor): si lo respetara, tocar una burbuja
 * dejaría el mapa con un solo punto y no habría cómo volver.
 *
 * Los números NO son los de la pastilla, y es a propósito: la pastilla cuenta
 * respuestas en la urna (con el corte congelado al responder) y el mapa cuenta
 * participación en el padrón (que es el único que sabe a cuántos se les
 * preguntó, o sea el único que puede dar un porcentaje). Pueden diferir en una
 * persona que cambió de seccional después de responder; la nota de abajo del
 * mapa lo dice.
 */
let MAPA = null, CAPA_SECC = null;
// Qué burbuja tiene el globo abierto. Hace falta guardarlo porque tocar una
// burbuja recarga el tablero y las burbujas se vuelven a dibujar: sin esto, el
// globo se abre y se cierra solo en el mismo clic, justo cuando la persona
// quiere leer los números de la seccional que acaba de elegir.
let POPUP_SECC = null;

function pintarMapa(d) {
  const seccion = $('mapa-seccion');
  const m = d.mapa;
  const lista = (m && m.seccionales) || [];
  if (!m || (!lista.length && !(m.sin_ubicar || []).length)) { seccion.hidden = true; return; }
  seccion.hidden = false;

  const caja = $('mapa-seccionales');
  // El tamaño sale de cuánta gente respondió; el color, del porcentaje de su
  // propio padrón, con escala FIJA de 0 a 100: una participación del 70% tiene
  // que verse igual de oscura con el filtro puesto que sin él.
  const maxResp = Math.max(1, ...lista.map(x => x.respondieron || 0));
  const logo = caja.dataset.logo || '';
  const destacado = css('--destacado') || '#E5188F';

  if (window.L && lista.length) {
    caja.hidden = false;
    if (!MAPA) {
      MAPA = MapaMT.crear('mapa-seccionales', { rueda: false });
      // El + y el − abajo a la derecha: arriba a la izquierda tapaban una
      // burbuja (en el teléfono, la de Córdoba).
      if (MAPA && MAPA.mapa.zoomControl) MAPA.mapa.zoomControl.setPosition('bottomright');
      if (MAPA) MAPA.mapa.on('zoomend', () => separarBurbujas());
    }
    if (MAPA) {
      if (CAPA_SECC) MAPA.mapa.removeLayer(CAPA_SECC);
      CAPA_SECC = L.layerGroup().addTo(MAPA.mapa);
      const puntos = [];
      lista.forEach(sec => {
        const elegida = FILTRO.seccional.includes(String(sec.id));
        const burbuja = MapaMT.burbuja(sec.lat, sec.lon, {
          diametro: MapaMT.diametroBurbuja(sec.respondieron, maxResp),
          borde: MapaMT.colorEscala(sec.porcentaje, 100),
          relleno: elegida ? destacado : '#ffffff',
          seleccionada: elegida,
          logo: logo
        });
        burbuja.bindPopup(popupSeccional(sec), { maxWidth: 280 });
        // Pasar el mouse muestra los números; el clic filtra. Son dos cosas
        // distintas y en un mapa que se repinta al filtrar conviene que lo
        // sean: si el globo dependiera del clic, se iría con el repintado.
        burbuja.on('mouseover', () => { POPUP_SECC = sec.id; burbuja.openPopup(); });
        burbuja.on('popupclose', () => { if (POPUP_SECC === sec.id) POPUP_SECC = null; });
        // Con el recorte impuesto (N18) no hay nada que elegir: la burbuja
        // informa y no filtra, igual que la pastilla queda deshabilitada.
        if (!m.impuesto) {
          burbuja.on('click', () => { POPUP_SECC = sec.id; alternar('seccional', String(sec.id)); });
        }
        burbuja._lugar = L.latLng(sec.lat, sec.lon);
        burbuja._diametro = MapaMT.diametroBurbuja(sec.respondieron, maxResp);
        burbuja.addTo(CAPA_SECC);
        if (POPUP_SECC === sec.id) burbuja.openPopup();
        puntos.push([sec.lat, sec.lon]);
      });
      MAPA.refrescar();
      // Se encuadra una sola vez: reencuadrar en cada filtro le movería el
      // mapa abajo de los dedos a quien está mirando una zona.
      if (!MAPA._encuadrado && puntos.length) {
        // 40 px de aire alrededor de las burbujas: con 30 la más grande
        // quedaba cortada contra el borde.
        MAPA.mapa.fitBounds(L.latLngBounds(puntos), { padding: [40, 40], maxZoom: 15 });
        MAPA._encuadrado = true;
      }
      separarBurbujas();
    }
  } else {
    caja.hidden = true;
  }

  $('mapa-leyenda').innerHTML = lista.length
    ? '<span>0\u202f%</span>' + MapaMT.ESCALA.map(c => `<i style="background:${c}"></i>`).join('')
      + '<span>100\u202f%</span><span style="margin-left:10px;">el tamaño es cuánta gente respondió</span>'
    : '';
  pintarSinUbicar(m);

  const partes = [];
  if (lista.length) {
    partes.push('El mapa sale del padrón fijado al publicar: cuánta gente de cada '
      + 'seccional respondió sobre cuánta se le preguntó. Puede diferir en algún caso '
      + 'de los números de las pastillas, que cuentan respuestas en la urna con la '
      + 'seccional que cada uno tenía al responder.');
  }
  if (m.impuesto) partes.push('Ves solo tu seccional, así que las burbujas no filtran.');
  else if (lista.length) partes.push('Tocá una burbuja para filtrar todo el tablero por esa seccional.');
  $('mapa-nota').textContent = partes.join(' ');
}

/* Dos seccionales vecinas (las del conurbano) caen casi en el mismo punto y
   una burbuja tapa a la otra. Se corren apenas, en píxeles y solo en la
   pantalla, hasta que se toquen sin pisarse; el dato de la seccional no se
   mueve. Se recalcula al hacer zoom, porque lo que se pisa depende de la
   escala. */
function separarBurbujas() {
  if (!MAPA || !CAPA_SECC) return;
  const mapa = MAPA.mapa;
  const marcas = CAPA_SECC.getLayers().filter(m => m._lugar);
  const pos = marcas.map(m => mapa.latLngToLayerPoint(m._lugar));
  for (let vuelta = 0; vuelta < 6; vuelta++) {
    let movio = false;
    for (let i = 0; i < marcas.length; i++) {
      for (let j = i + 1; j < marcas.length; j++) {
        const minimo = (marcas[i]._diametro + marcas[j]._diametro) / 2 + 2;
        let dx = pos[j].x - pos[i].x, dy = pos[j].y - pos[i].y;
        let d = Math.hypot(dx, dy);
        if (d >= minimo) continue;
        if (d < .5) { dx = Math.cos(j); dy = Math.sin(j); d = 1; }
        const empuje = (minimo - d) / 2;
        pos[i] = pos[i].subtract(L.point(dx / d * empuje, dy / d * empuje));
        pos[j] = pos[j].add(L.point(dx / d * empuje, dy / d * empuje));
        movio = true;
      }
    }
    if (!movio) break;
  }
  marcas.forEach((m, i) => m.setLatLng(mapa.layerPointToLatLng(pos[i])));
}

function popupSeccional(sec) {
  const fila = (k, v) => `<tr><td>${k}</td><td>${v}</td></tr>`;
  return `<div class="mapa-pop"><b>${esc(sec.nombre)}</b>` +
    (sec.direccion_texto ? `<div class="mapa-pop-dir">${esc(sec.direccion_texto)}</div>` : '') +
    '<table>' +
    fila('Respondieron', sec.respondieron) +
    fila('Padrón de la encuesta', sec.convocados) +
    fila('Participación', pct(sec.porcentaje)) +
    '</table></div>';
}

function pintarSinUbicar(m) {
  const caja = $('mapa-sin-ubicar');
  const faltan = m.sin_ubicar || [];
  if (!faltan.length) { caja.classList.remove('hay'); caja.textContent = ''; return; }
  caja.classList.add('hay');
  // Sin enlace a propósito: quien mira resultados de una encuesta no
  // necesariamente puede editar seccionales, y un enlace que da 403 es peor
  // que una frase que dice dónde se arregla.
  caja.textContent = `${faltan.length === 1 ? 'Esta seccional participó y no está ubicada'
    : 'Estas seccionales participaron y no están ubicadas'} en el mapa: `
    + faltan.map(x => `${x.nombre} (${x.respondieron} de ${x.convocados})`).join(', ')
    + '. Se ubican en la pestaña Seccionales del panel.';
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
        <div class="destaca"><b>${num(e.promedio, 2)}</b>promedio</div>
        <div><b>${num(e.mediana, 2)}</b>mediana</div>
        <div><b>${pct(e.altos.porcentaje)}</b>en los más altos${e.etiqueta_max
          ? ` (${esc(e.etiqueta_max)})` : ''}</div>
        <div><b>${pct(e.bajos.porcentaje)}</b>en los más bajos${e.etiqueta_min
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
      <div class="destaca"><b>${num(n.promedio, 2)}</b>promedio</div>
      <div><b>${num(n.minimo, 2)}</b>mínimo</div>
      <div><b>${num(n.maximo, 2)}</b>máximo</div></div>`;
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
        <td class="num">${num(x.cantidad)}</td>
        <td class="num">${pct(x.porcentaje === null
          ? Math.round(x.cantidad * 1000 / total) / 10 : x.porcentaje)}</td>
      </tr>`).join('')}
  </table>`;
}

function tablaRanking(p) {
  return `<table class="datos">
    <tr><th>Opción</th><th class="num">Pos. promedio</th><th class="num">1.ª</th></tr>
    ${p.ranking.map(x => `<tr class="clicable" onclick="abrirCruce(${p.id}, '${x.indice}')">
        <td>${esc(x.texto)}</td>
        <td class="num">${num(x.promedio, 2)}</td>
        <td class="num">${x.primeras}</td>
      </tr>`).join('')}
  </table>`;
}

function alturaDe(p) {
  const filas = (p.ranking || p.opciones || []).length;
  return Math.max(120, 34 * filas);
}

/* ---------- Chart.js ---------- */

// Los colores de los gráficos los pone el modelo de diseño (--gr-*): con la
// paleta de Colm3na son los del modelo; con la del sindicato, su marca.
function paleta() {
  return {
    apoyo: css('--gr-1') || css('--marca-apoyo') || '#2fa88f',
    acento: css('--gr-2') || css('--marca-acento') || '#e8a33d',
    primario: css('--gr-3') || css('--marca-primario') || '#1a3d6b',
    linea: css('--linea') || '#e4e7ec',
    gris: css('--gr-texto') || css('--gris') || '#5b6478',
  };
}

// Una sola vez: los números de los ejes con coma decimal y las letras del
// modelo en todos los gráficos.
if (window.Chart) {
  Chart.defaults.locale = 'es-AR';
  Chart.defaults.font.family = css('--gr-fuente') || Chart.defaults.font.family;
  Chart.defaults.color = css('--gr-texto') || css('--gris') || Chart.defaults.color;
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
            return `posición promedio ${num(f.promedio, 2)} de ${n} · ${f.primeras} la pusieron primera`;
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
            ` ${num(ops[x.dataIndex].cantidad)} · ${pct(ops[x.dataIndex].porcentaje)}` } },
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
          ? ` ${num(valor)} · ${pct(fila.porcentaje)}` : ` ${num(valor)}`;
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
        borderColor: css('--gr-3') || css('--marca-primario') || '#1a3d6b',
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
    : `${d.elegidos} de ${d.total} respuestas · ${pct(d.porcentaje)}`;

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
        El general es ${pct(bloque.general)}.</div>`;
    let avisoChicos = false;
    bloque.filas.forEach(f => {
      // Un grupo de una o dos personas se muestra, pero sin el chip de
      // diferencia: un porcentaje sobre uno no compara nada, y leído como
      // tendencia manda al sindicato a mirar donde no hay nada.
      const signo = f.poco ? 'igual'
        : f.diferencia > 0 ? 'mas' : f.diferencia < 0 ? 'menos' : 'igual';
      if (f.poco) avisoChicos = true;
      html += `<div class="cr-fila ${f.poco ? 'flojo' : ''}">
          <span class="nom">${esc(f.etiqueta)}<small>${f.cantidad} de ${f.base} respuestas</small></span>
          <span class="pct">${pct(f.dentro)}</span>
          <span class="cr-dif ${signo}">${f.poco ? 'pocas'
            : dif(f.diferencia)}</span>
          <span class="cr-barra"><i style="width:${Math.min(f.dentro, 100)}%"></i></span>
        </div>`;
    });
    if (avisoChicos) {
      html += `<div class="sub" style="margin-top:6px;">«Pocas» = menos de
        ${bloque.minimo_para_comparar} respuestas en ese grupo: el porcentaje es real,
        pero no alcanza para leerlo como una tendencia.</div>`;
    }
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
        html += `<div class="sub">promedio ${num(p.promedio, 2)}</div>`;
      } else {
        p.opciones.filter(o => o.cantidad).slice(0, 4).forEach(o => {
          html += `<div class="cr-fila">
            <span class="nom">${esc(o.texto)}</span>
            <span class="pct">${pct(o.porcentaje)}</span><span></span>
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

// Cuatro colores del modelo; de la quinta línea en adelante el color se
// repite PUNTEADO y con otra forma de punto: con cinco opciones la quinta
// salía igual que la primera y no se sabía cuál era cuál.
const COLORES_EV = ['--gr-1', '--gr-2', '--gr-3', '--gr-4'];
const PUNTOS_EV = ['circle', 'rect', 'triangle', 'rectRot'];

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
        pointBackgroundColor: css(COLORES_EV[n % COLORES_EV.length]) || '#2fa88f',
        borderDash: n >= COLORES_EV.length ? [6, 4] : [],
        pointStyle: PUNTOS_EV[Math.floor(n / COLORES_EV.length) % PUNTOS_EV.length],
        backgroundColor: 'transparent', tension: .25, borderWidth: 2, pointRadius: 3.5,
        // Una toma por debajo del umbral no aporta punto; la línea sigue de
        // largo en vez de cortarse y hacer pensar que ahí no hubo encuesta.
        spanGaps: true,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        // La leyenda dibuja la línea (llena o punteada), no un cuadradito.
        legend: { display: p.lineas.length > 1, position: 'bottom',
                  labels: { usePointStyle: true, pointStyle: 'line', boxWidth: 26, font: { size: 12 } } },
        tooltip: { callbacks: {
          title: (c) => tomas[c[0].dataIndex].titulo,
          label: (x) => ` ${x.dataset.label}: ${p.tipo_dato === 'escala' || p.tipo_dato === 'ranking'
            ? num(x.parsed.y, 2) : pct(x.parsed.y)}` } },
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
