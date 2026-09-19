// Test 3 -- "Filtro frenético" del Panel Sindical: reproduce el cuelgue de
// Pruebas del 2026-09-18 (docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md)
// y mide que la app YA NO se cuelga.
//
// Un admin cambia el filtro de empresa 30 veces en 60 s y, en cada cambio,
// dispara los 12 pedidos del panel A LA VEZ y los ABANDONA a los 250 ms (como
// el navegador viejo: abortar un fetch solo cancela del lado del cliente, el
// servidor termina la consulta igual). Es el PEOR caso: el front nuevo pide de a
// 4 (cola), pero acá se prueba que el servidor se defiende solo, sin ayuda del
// front. En paralelo, 20 lectores recorren la app del trabajador.
//
// Dos fases de 60 s con los mismos 20 lectores:
//   base      solo los lectores.
//   tormenta  los lectores + el admin frenético.
//
// Criterios (los evalúa handleSummary, y los dos primeros también son
// thresholds de k6):
//   1. 0 respuestas 500 en todo el test. Un 503 es esperable y NO es error:
//      es el servidor diciendo "estoy ocupado" (cupo del panel / pool).
//   2. Los lectores no fallan (http_req_failed{grupo:lector} < 1 %).
//   3. p95 de los lectores en "tormenta" <= 2 x su p95 en "base".
//
// Uso (SOLO contra Pruebas, con MOCK_EXTRACTOR=1; nunca demo ni producción --
// correr.sh lo valida):
//   BASE_URL=https://mitrabajo-pruebas.onrender.com \
//   ADMIN_CUIT=20111111110 ADMIN_CLAVE=<clave del admin> \
//   k6 run carga/k6/test3_panel.js
// ADMIN_CUIT default = el Super Admin de UOM de la demo. El sindicato del admin
// tiene que tener el módulo "dashboard" (el lote UOM lo trae) y al menos una
// empresa. Los lectores salen de carga/usuarios.csv, igual que test1.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const BASE_URL = (__ENV.BASE_URL || 'https://mitrabajo-pruebas.onrender.com').replace(/\/$/, '');
const ADMIN_CUIT = __ENV.ADMIN_CUIT || '20111111110';
const ADMIN_CLAVE = __ENV.ADMIN_CLAVE || '';
const RESUMEN = __ENV.RESUMEN_PANEL || 'test3_resumen.json';

const FASE_BASE_MS = 60 * 1000;
const LECTORES = 20;
const CAMBIOS_DE_FILTRO = 30;
const ABANDONO = '250ms';        // a los cuántos ms el "navegador" abandona cada pedido

const errores500 = new Rate('errores_500');     // 500+ salvo 503 (503 = ocupado, esperado)
const panel503 = new Counter('panel_503');
const panelPedidos = new Counter('panel_pedidos');

const usuarios = new SharedArray('usuarios', function () {
  return open('../usuarios.csv')
    .split('\n')
    .slice(1)
    .filter((l) => l.trim())
    .map((l) => {
      const [cuil, clave] = l.trim().split(',');
      return { cuil, clave };
    });
});

export const options = {
  scenarios: {
    lectores: {
      executor: 'constant-vus',
      vus: LECTORES,
      duration: '2m',
      exec: 'lector',
    },
    admin_frenetico: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: CAMBIOS_DE_FILTRO,
      startTime: '60s',
      maxDuration: '90s',
      exec: 'adminFrenetico',
    },
  },
  thresholds: {
    errores_500: ['rate==0'],
    'http_req_failed{grupo:lector}': ['rate<0.01'],
    // Umbrales holgados a propósito: existen para que k6 CREE los submétricos
    // por fase y handleSummary pueda compararlos (el criterio de 2 x lo evalúa
    // handleSummary, porque un threshold no puede comparar dos métricas).
    'http_req_duration{grupo:lector,fase:base}': ['p(95)<60000'],
    'http_req_duration{grupo:lector,fase:tormenta}': ['p(95)<60000'],
  },
};

export function setup() {
  if (!ADMIN_CLAVE) {
    throw new Error('Falta ADMIN_CLAVE (la clave del admin de sindicato con el módulo dashboard).');
  }
  // Se prueba al admin ACÁ, antes de arrancar: si la clave está mal o el
  // sindicato no tiene el módulo, el test se corta en un segundo con el motivo,
  // en vez de correr 2 minutos de lectores sin tormenta y dar un veredicto
  // vacío (pasó en la primera corrida contra Pruebas, 2026-09-19).
  entrarComoAdmin();
  return { inicio: Date.now() };
}

function fase(data) {
  return Date.now() - data.inicio < FASE_BASE_MS ? 'base' : 'tormenta';
}

function registrar(res) {
  errores500.add(res.status >= 500 && res.status !== 503);
}

/* ---------------- Lectores: la app del trabajador ---------------- */

export function lector(data) {
  const u = usuarios[(__VU - 1) % usuarios.length];
  const etiquetas = (paso) => ({ tags: { grupo: 'lector', fase: fase(data), paso: paso } });

  let res = http.get(`${BASE_URL}/ingresar`, etiquetas('ingresar'));
  registrar(res);
  res = http.post(`${BASE_URL}/trabajador/login`, { cuil: u.cuil, clave: u.clave },
    Object.assign({ redirects: 5 }, etiquetas('login')));
  registrar(res);
  if (res.url.indexOf('/app/inicio') === -1) { sleep(1); return; }   // sin sesión no sigue

  for (const [ruta, paso] of [['/app/inicio', 'home'], ['/app/notificaciones', 'novedades'],
                              ['/app', 'recibo']]) {
    sleep(1 + Math.random() * 2);
    res = http.get(`${BASE_URL}${ruta}`, etiquetas(paso));
    registrar(res);
    check(res, { [`${paso} 2xx`]: (r) => r.status >= 200 && r.status < 400 });
  }
  sleep(1 + Math.random() * 2);
}

/* ---------------- Admin frenético: el panel ---------------- */

const PANELES = ['kpis', 'serie-recibos', 'validacion', 'diferencias-empresa',
                 'tramites-seccional', 'notificaciones', 'formato-semana',
                 'seccionales-geo', 'semaforo', 'explorador/recibos',
                 'explorador/tramites', 'explorador/notificaciones'];

let logueado = false;
let idsEmpresas = [];

function fechaISO(dias) {
  // AAAA-MM-DD en UTC, de "hoy - dias". Se pide desde AYER: el servidor valida
  // contra la hora de Buenos Aires y rechaza un `hasta` futuro (422), y a partir
  // de las 21:00 de Argentina el día UTC ya es el siguiente.
  return new Date(Date.now() - dias * 86400000).toISOString().slice(0, 10);
}

function entrarComoAdmin() {
  http.post(`${BASE_URL}/admin/login`, { usuario: ADMIN_CUIT, clave: ADMIN_CLAVE },
    { redirects: 5, tags: { grupo: 'admin', paso: 'login' } });
  // Si el login falló no hay cookie y /filtros da 403; si el sindicato no tiene
  // el módulo, también 403. Un solo mensaje que nombra las dos causas.
  const filtros = http.get(`${BASE_URL}/admin/dashboard/filtros`, { tags: { grupo: 'admin', paso: 'filtros' } });
  if (filtros.status !== 200) {
    throw new Error(`/admin/dashboard/filtros devolvió ${filtros.status}: revisar ADMIN_CUIT / ADMIN_CLAVE ` +
                    'y que el sindicato tenga el módulo dashboard.');
  }
  idsEmpresas = (filtros.json('empresas') || []).map((e) => e.id);
  if (idsEmpresas.length === 0) throw new Error('El sindicato del admin no tiene empresas para filtrar.');
  logueado = true;
}

export function adminFrenetico() {
  if (!logueado) entrarComoAdmin();
  // Un filtro distinto en cada cambio: una empresa, dos, otra...
  const n = __ITER;
  const elegidas = [idsEmpresas[n % idsEmpresas.length]];
  if (n % 3 === 1) elegidas.push(idsEmpresas[(n + 1) % idsEmpresas.length]);
  const query = `desde=${fechaISO(31)}&hasta=${fechaISO(1)}&empresas=${elegidas.join(',')}`;

  // Los 12 pedidos juntos y abandonados a los 250 ms. Los que el servidor no
  // alcanzó a contestar quedan con status 0: es a propósito, es el "abort".
  const respuestas = http.batch(PANELES.map((p) => ({
    method: 'GET',
    url: `${BASE_URL}/admin/dashboard/${p}?${query}${p.startsWith('explorador') ? '&page=1&page_size=10' : ''}`,
    params: { timeout: ABANDONO, tags: { grupo: 'panel', fase: 'tormenta' } },
  })));
  for (const r of respuestas) {
    panelPedidos.add(1);
    if (r.status === 503) panel503.add(1);
    if (r.status !== 0) registrar(r);
  }
  sleep(2);            // 30 cambios en ~60 s
}

/* ---------------- Veredicto ---------------- */

function p95(data, nombre) {
  const m = data.metrics[nombre];
  return m && m.values ? m.values['p(95)'] : null;
}

export function handleSummary(data) {
  const base = p95(data, 'http_req_duration{grupo:lector,fase:base}');
  const tormenta = p95(data, 'http_req_duration{grupo:lector,fase:tormenta}');
  const razon = base && tormenta ? tormenta / base : null;
  const e500 = data.metrics.errores_500 ? data.metrics.errores_500.values.rate : null;
  const fallaLectores = data.metrics['http_req_failed{grupo:lector}']
    ? data.metrics['http_req_failed{grupo:lector}'].values.rate : null;
  const veredicto = {
    p95_lectores_base_ms: base,
    p95_lectores_tormenta_ms: tormenta,
    razon_tormenta_sobre_base: razon,
    criterio_2x: razon !== null && razon <= 2,
    tasa_500: e500,
    criterio_cero_500: e500 === 0,
    tasa_falla_lectores: fallaLectores,
    pedidos_del_panel: data.metrics.panel_pedidos ? data.metrics.panel_pedidos.values.count : 0,
    respuestas_503_del_panel: data.metrics.panel_503 ? data.metrics.panel_503.values.count : 0,
  };
  // Sin tormenta no hay veredicto: 30 cambios x 12 paneles = 360 pedidos. Si el
  // admin no pudo entrar, los lectores solos "aprueban" cualquier cosa.
  veredicto.tormenta_ejecutada = veredicto.pedidos_del_panel >= CAMBIOS_DE_FILTRO * PANELES.length * 0.9;
  veredicto.aprobado = veredicto.tormenta_ejecutada && veredicto.criterio_2x &&
    veredicto.criterio_cero_500 && fallaLectores !== null && fallaLectores < 0.01;
  const linea = (k, v) => `  ${k.padEnd(34)} ${v}\n`;
  const texto = '\n=== Test 3: filtro frenético ===\n' +
    linea('p95 lectores, fase base', base === null ? 's/d' : base.toFixed(0) + ' ms') +
    linea('p95 lectores, fase tormenta', tormenta === null ? 's/d' : tormenta.toFixed(0) + ' ms') +
    linea('razón tormenta / base (<= 2)', razon === null ? 's/d' : razon.toFixed(2)) +
    linea('respuestas 500 (deben ser 0)', e500 === null ? 's/d' : (e500 * 100).toFixed(2) + ' %') +
    linea('fallas de lectores (< 1 %)', fallaLectores === null ? 's/d' : (fallaLectores * 100).toFixed(2) + ' %') +
    linea('pedidos del panel / 503', `${veredicto.pedidos_del_panel} / ${veredicto.respuestas_503_del_panel}`) +
    linea('VEREDICTO', veredicto.aprobado ? 'APROBADO'
      : (veredicto.tormenta_ejecutada ? 'NO APROBADO' : 'NO APROBADO: la tormenta no se ejecutó')) + '\n';
  return { stdout: texto, [RESUMEN]: JSON.stringify(veredicto, null, 2) };
}
