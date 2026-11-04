// Test 4 -- Recibos bancarios reales bajo carga (PLAN_PRUEBAS_BANCARIA.md,
// B1, B2, B3 y la prueba de cambio de plan R).
//
// Diferencia con el test 2: sube los recibos del LOTE BANCARIO (PDF digitales
// y fotos), cada uno con la sesión de SU propio CUIL. Con ENMASCARADO=activo
// el servidor corre el OCR (Tesseract) antes de la IA AUNQUE esté
// MOCK_EXTRACTOR=1, así que esto mide CPU que el test 2 nunca vio; y como el
// enmascarado corta un recibo ajeno (E-RECIBO-04) antes de la IA, subir el
// recibo de otro CUIL mediría rechazos.
//
// Necesita MOCK_EXTRACTOR=1 en el servidor (si no, cada subida es una lectura
// real y se paga). Nunca contra la demo.
//
// Preparación (una vez):
//   python carga/lote_bancaria.py extraer           -> carga/recibos_bancaria/
//   DATABASE_URL=... python carga/preparar_bancaria.py --si   -> carga/usuarios_bancaria.csv
//
// Escenarios (ESCENARIO=...):
//   rafagas  (B1/B2) LECTORES constantes (200) + ráfagas RAFAGAS ("2,5,10,20,40")
//            de DURACION_ESCALON (3m) cada una. FORMATO=pdf|jpg|todos (B2).
//   cobro    (B3) lectores que suben a LECTORES (400) en 2 min y se quedan PICO
//            (10m), con SUBIDAS (20) subidas simultáneas durante el pico.
//   continuo (R)  LECTORES (200) navegando DURACION (20m) sin subidas: mientras
//            tanto se cambia el plan desde /entornos -> Planes. Correr con
//            --out json=... y analizar con carga/analizar_corte.py.
//
// Uso:
//   BASE_URL=https://mitrabajo-pruebas.onrender.com ESCENARIO=rafagas \
//     k6 run --out json=carga/log/<carpeta>/test4.ndjson carga/k6/test4_bancaria.js
// Otras: USUARIOS_LECTORES (default ../usuarios_bancaria.csv; los 1.000 de
// ../usuarios.csv no tienen «Tu día»), POR_PERSONA (recibos de cada CUIL que
// se cargan en memoria, 2), MOCK_LATENCIA_S (la del servidor, 15: es la base
// del criterio de las subidas), RESUMEN (test4_resumen.json).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import { open as abrir, SeekMode } from 'k6/experimental/fs';

const BASE_URL = (__ENV.BASE_URL || 'https://mitrabajo-pruebas.onrender.com').replace(/\/$/, '');
if (/mitrabajo\.onrender\.com|mitrabajo-demo/.test(BASE_URL)) {
  throw new Error('Nunca contra la demo.');
}
const ESCENARIO = __ENV.ESCENARIO || 'rafagas';
const FORMATO = (__ENV.FORMATO || 'todos').toLowerCase();
const LECTORES = parseInt(__ENV.LECTORES || (ESCENARIO === 'cobro' ? '400' : '200'), 10);
const RAFAGAS = (__ENV.RAFAGAS || '2,5,10,20,40').split(',').map((x) => parseInt(x, 10));
const DURACION_ESCALON = __ENV.DURACION_ESCALON || '3m';
const PICO = __ENV.PICO || '10m';
const SUBIDAS = parseInt(__ENV.SUBIDAS || '20', 10);
const DURACION = __ENV.DURACION || '20m';
const POR_PERSONA = parseInt(__ENV.POR_PERSONA || '2', 10);
const MOCK_LATENCIA_MS = parseFloat(__ENV.MOCK_LATENCIA_S || '15') * 1000;
const RESUMEN = __ENV.RESUMEN || 'test4_resumen.json';
const DIR = '../recibos_bancaria/';

const subidaMs = new Trend('subida_ms', true);
const erroresSubida = new Rate('errores_subida');
const erroresLector = new Rate('errores_lector');
const recibo04 = new Counter('subida_e_recibo_04');   // pertenencia: tiene que ser 0
const ocupado = new Counter('respuestas_503');         // el servidor dijo "ocupado"
const cincuentos = new Counter('respuestas_500');      // nunca
const tuDiaApagado = new Counter('tu_dia_403');

function leerUsuarios(ruta) {
  return open(ruta).split('\n').slice(1).filter((l) => l.trim()).map((l) => {
    const [cuil, clave] = l.trim().split(',');
    return { cuil, clave };
  }).filter((u) => u.clave);
}

const usuariosBancaria = new SharedArray('bancaria', () => leerUsuarios('../usuarios_bancaria.csv'));
const lectores = new SharedArray('lectores',
  () => leerUsuarios(__ENV.USUARIOS_LECTORES || '../usuarios_bancaria.csv'));

// Qué recibos se cargan: POR_PERSONA de cada CUIL con clave, del formato
// pedido. Siempre los mismos (orden del manifiesto).
const muestra = new SharedArray('muestra', () => {
  const conClave = {};
  for (const u of leerUsuarios('../usuarios_bancaria.csv')) conClave[u.cuil] = u.clave;
  const porCuil = {};
  const elegidos = [];
  for (const r of JSON.parse(open(DIR + 'k6.json'))) {
    if (!conClave[r.cuil] || r.error) continue;           // los errores a propósito no son carga
    if (FORMATO !== 'todos' && r.formato !== FORMATO) continue;
    porCuil[r.cuil] = (porCuil[r.cuil] || 0) + 1;
    if (porCuil[r.cuil] <= POR_PERSONA) elegidos.push(Object.assign({ clave: conClave[r.cuil] }, r));
  }
  if (!elegidos.length) throw new Error('No hay recibos para subir: revisar FORMATO y usuarios_bancaria.csv.');
  return elegidos;
});

// k6/experimental/fs: el archivo se lee UNA vez y se comparte entre VUs (con
// open() de siempre, 600 recibos x cientos de VUs no entran en memoria).
const archivos = {};
(async function () {
  if (ESCENARIO === 'continuo') return;
  for (const r of muestra) archivos[r.archivo] = await abrir(DIR + r.archivo);
})();

const MIME = { pdf: 'application/pdf', jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png' };

function contar(res) {
  if (res.status === 503) ocupado.add(1);
  if (res.status >= 500 && res.status !== 503) cincuentos.add(1);
}

function login(u, tags) {
  const res = http.post(`${BASE_URL}/trabajador/login`, { cuil: u.cuil, clave: u.clave },
    { redirects: 5, tags: Object.assign({ paso: 'login' }, tags) });
  contar(res);
  return res.status < 400 && res.url.indexOf('/app') !== -1;
}

/* ---------------- Lectores ---------------- */

export function lector() {
  const u = lectores[(__VU - 1) % lectores.length];
  const tags = { grupo: 'lector' };
  if (!login(u, tags)) { erroresLector.add(true); sleep(2); return; }
  for (const [ruta, paso] of [['/app/inicio', 'home'], ['/api/tu-dia', 'tu_dia'],
                              ['/app/notificaciones', 'novedades'], ['/app', 'recibo']]) {
    sleep(1 + Math.random() * 2);
    const res = http.get(`${BASE_URL}${ruta}`, { tags: Object.assign({ paso }, tags), timeout: '60s' });
    contar(res);
    if (paso === 'tu_dia' && res.status === 403) { tuDiaApagado.add(1); continue; }
    const ok = res.status >= 200 && res.status < 400;
    erroresLector.add(!ok);
    check(res, { [`${paso} 2xx`]: () => ok });
  }
  sleep(1 + Math.random() * 2);
}

/* ---------------- Subidas ---------------- */

let miCuil = null;
let misRecibos = [];
let logueado = false;

export async function subir() {
  if (!miCuil) {
    const cuils = [...new Set(muestra.map((r) => r.cuil))];
    miCuil = cuils[(__VU - 1) % cuils.length];
    misRecibos = muestra.filter((r) => r.cuil === miCuil);
  }
  const r = misRecibos[__ITER % misRecibos.length];
  const tags = { grupo: 'subida', formato: r.formato, banco: r.banco };
  if (!logueado) {
    logueado = login({ cuil: r.cuil, clave: r.clave }, tags);
    if (!logueado) { erroresSubida.add(true); sleep(2); return; }
  }
  const f = archivos[r.archivo];
  const info = await f.stat();
  const buf = new Uint8Array(info.size);
  await f.read(buf);
  await f.seek(0, SeekMode.Start);
  const ext = r.archivo.split('.').pop().toLowerCase();
  const nombre = r.archivo.split('/').pop();
  const res = http.post(`${BASE_URL}/api/leer`,
    { archivo: http.file(buf.buffer, nombre, MIME[ext] || 'application/octet-stream') },
    { tags: Object.assign({ paso: 'subir_recibo' }, tags), timeout: '90s', responseType: 'text' });
  contar(res);
  let codigo = '';
  try { codigo = res.status !== 200 ? (res.json('codigo') || '') : ''; } catch (e) { codigo = ''; }
  if (codigo === 'E-RECIBO-04') recibo04.add(1);
  if (codigo === 'E-SESION-01' || codigo === 'E-SESION-02' || res.status === 401) logueado = false;   // sesión vencida: reentra
  const ok = res.status === 200;
  erroresSubida.add(!ok);
  subidaMs.add(res.timings.duration, tags);
  check(res, { 'subir_recibo 200': () => ok });
}

/* ---------------- Escenarios ---------------- */

function escenarios() {
  if (ESCENARIO === 'continuo') {
    return { lectores: { executor: 'constant-vus', vus: LECTORES, duration: DURACION, exec: 'lector' } };
  }
  if (ESCENARIO === 'cobro') {
    return {
      lectores: { executor: 'ramping-vus', exec: 'lector', startVUs: 0,
        stages: [{ duration: '2m', target: LECTORES }, { duration: PICO, target: LECTORES },
                 { duration: '30s', target: 0 }] },
      subidas: { executor: 'constant-vus', vus: SUBIDAS, duration: PICO, startTime: '2m', exec: 'subir' },
    };
  }
  const minutos = parseFloat(DURACION_ESCALON);       // "3m" -> 3
  const s = { lectores: { executor: 'constant-vus', vus: LECTORES,
    duration: `${minutos * RAFAGAS.length + 1}m`, exec: 'lector' } };
  RAFAGAS.forEach((n, i) => {
    s[`rafaga_${n}`] = { executor: 'constant-vus', vus: n, duration: DURACION_ESCALON,
      startTime: `${minutos * i}m`, exec: 'subir' };
  });
  return s;
}

function umbrales() {
  // Holgados a propósito: existen para que k6 cree los submétricos que lee
  // handleSummary (el veredicto se evalúa ahí).
  const t = { 'http_req_duration{grupo:lector}': ['p(95)<120000'] };
  if (ESCENARIO === 'rafagas') {
    for (const n of RAFAGAS) {
      t[`subida_ms{scenario:rafaga_${n}}`] = ['p(95)<999999'];
      t[`errores_subida{scenario:rafaga_${n}}`] = ['rate<=1'];
    }
  }
  if (ESCENARIO !== 'continuo') {
    t['subida_ms{formato:pdf}'] = ['p(95)<999999'];
    t['subida_ms{formato:jpg}'] = ['p(95)<999999'];
    t['errores_subida{formato:pdf}'] = ['rate<=1'];
    t['errores_subida{formato:jpg}'] = ['rate<=1'];
  }
  return t;
}

// noCookiesReset: k6 vacía las cookies al terminar cada iteración, y el que
// sube recibos se loguea una vez y sigue subiendo en las siguientes (sin esto,
// de la segunda subida en adelante la app contesta E-SESION-02).
// discardResponseBodies: con 200 lectores y --out json, k6 guardaba cada HTML
// y se quedó sin memoria (14 GB, muerto por el sistema a los 13 minutos de la
// primera corrida en el plan Intermedio). El cuerpo solo hace falta en la
// subida (el código de error), que lo pide con responseType.
export const options = { scenarios: escenarios(), thresholds: umbrales(), noCookiesReset: true,
  discardResponseBodies: true };

/* ---------------- Veredicto ---------------- */

function valores(data, nombre) {
  const m = data.metrics[nombre];
  return m && m.values ? m.values : null;
}

export function handleSummary(data) {
  const lect = valores(data, 'http_req_duration{grupo:lector}');
  const errL = valores(data, 'errores_lector');
  const cuenta = (n) => (valores(data, n) || {}).count || 0;
  const v = {
    escenario: ESCENARIO, formato: FORMATO, lectores: LECTORES,
    lectores_p95_ms: lect ? lect['p(95)'] : null,
    lectores_falla: errL ? errL.rate : null,
    respuestas_500: cuenta('respuestas_500'),
    respuestas_503: cuenta('respuestas_503'),
    e_recibo_04: cuenta('subida_e_recibo_04'),
    tu_dia_403: cuenta('tu_dia_403'),
    por_formato: {}, escalones: {},
  };
  for (const f of ['pdf', 'jpg']) {
    const x = valores(data, `subida_ms{formato:${f}}`);
    const e = valores(data, `errores_subida{formato:${f}}`);
    const n = e ? (e.passes || 0) + (e.fails || 0) : 0;
    if (x && n) v.por_formato[f] = { subidas: n, p50_ms: x.med, p95_ms: x['p(95)'] };
  }
  if (ESCENARIO === 'rafagas') {
    for (const n of RAFAGAS) {
      const x = valores(data, `subida_ms{scenario:rafaga_${n}}`);
      const e = valores(data, `errores_subida{scenario:rafaga_${n}}`);
      v.escalones[n] = { subidas: e ? (e.passes || 0) + (e.fails || 0) : 0, p50_ms: x ? x.med : null,
        p95_ms: x ? x['p(95)'] : null, error: e ? e.rate : null };
    }
  }
  // Criterios del plan: subidas p95 <= latencia del mock + 5 s (lo que el OCR
  // le puede sumar, ENMASCARADO_PRESUPUESTO_MS) y < 1 % de error; 0 respuestas
  // 500 y 0 E-RECIBO-04; lectores < 1 s en el día de cobro.
  const tope = MOCK_LATENCIA_MS + 5000;
  const esc = Object.values(v.escalones);
  v.criterio_subidas = ESCENARIO !== 'rafagas' ||
    esc.every((x) => x.subidas === 0 || (x.p95_ms <= tope && x.error < 0.01));
  v.criterio_cero_500 = v.respuestas_500 === 0;
  v.criterio_pertenencia = v.e_recibo_04 === 0;
  v.criterio_lectores = ESCENARIO !== 'cobro' || (v.lectores_p95_ms !== null && v.lectores_p95_ms < 1000);
  v.aprobado = v.criterio_subidas && v.criterio_cero_500 && v.criterio_pertenencia && v.criterio_lectores;
  const ms = (x) => (x === null || x === undefined ? 's/d' : (x >= 1000 ? (x / 1000).toFixed(1) + ' s' : x.toFixed(0) + ' ms'));
  let txt = `\n=== Test 4: recibos bancarios (${ESCENARIO}, formato ${FORMATO}) ===\n`;
  for (const [n, x] of Object.entries(v.escalones)) {
    txt += `  ráfaga ${String(n).padStart(2)}: ${String(x.subidas).padStart(4)} subidas, p50 ${ms(x.p50_ms)}, p95 ${ms(x.p95_ms)}, error ${x.error === null ? 's/d' : (x.error * 100).toFixed(2) + ' %'}\n`;
  }
  for (const [f, x] of Object.entries(v.por_formato)) txt += `  ${f}: ${x.subidas} subidas, p95 ${ms(x.p95_ms)}\n`;
  txt += `  lectores p95 ${ms(v.lectores_p95_ms)}, falla ${v.lectores_falla === null ? 's/d' : (v.lectores_falla * 100).toFixed(2) + ' %'}\n`;
  txt += `  500: ${v.respuestas_500}   503: ${v.respuestas_503}   E-RECIBO-04: ${v.e_recibo_04}\n`;
  txt += `  VEREDICTO: ${v.aprobado ? 'APROBADO' : 'NO APROBADO'}\n\n`;
  return { stdout: txt, [RESUMEN]: JSON.stringify(v, null, 2) };
}
