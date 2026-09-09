// Test 2 -- Recibos: 200 lectores constantes (mismo journey de lecturas que
// test1, sin el paso de credencial) y, en paralelo, ráfagas de subida de
// recibo (POST /api/leer, multipart) de 2, 5, 10 y 20 simultáneas, 4
// minutos cada escalón. Necesita MOCK_EXTRACTOR=1 en el servidor -- si no,
// cada subida golpea la API real de Anthropic (costo real, y probablemente
// server-side ~15s+ igual, pero facturado).
//
// Uso:
//   BASE_URL=https://mitrabajo-pruebas.onrender.com k6 run \
//     --out json=log/test2_recibos.json carga/k6/test2_recibos.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const BASE_URL = (__ENV.BASE_URL || 'https://mitrabajo-pruebas.onrender.com').replace(/\/$/, '');
const errores = new Rate('errores_app');
const erroresRecibo = new Rate('errores_recibo');

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

// 20 imagenes de recibo sintéticas (carga/recibos/) -- MOCK_EXTRACTOR no
// lee el contenido, así que no importa cuál le toque a cada VU. open() solo
// se puede llamar en el scope de init (una vez por VU, no por iteración) --
// por eso se leen acá arriba, no adentro de subirRecibo().
const imagenesBin = [];
for (let i = 0; i < 20; i++) {
  const nombre = `recibo_demo_${String(i).padStart(2, '0')}.jpg`;
  imagenesBin.push({ nombre, datos: open(`../recibos/${nombre}`, 'b') });
}

function pausa() {
  sleep(2 + Math.random() * 3);
}

function login(u) {
  const res = http.post(
    `${BASE_URL}/trabajador/login`,
    { cuil: u.cuil, clave: u.clave },
    { tags: { paso: 'login' }, redirects: 5 }
  );
  return res.status >= 200 && res.status < 400 && res.url.indexOf('/app/inicio') !== -1;
}

// ---------------- Escenario "lectores": 200 constantes, todo el test ----
function lectores() {
  const u = usuarios[(__VU - 1) % usuarios.length];
  if (!login(u)) {
    errores.add(true);
    pausa();
    return;
  }
  pausa();
  let res = http.get(`${BASE_URL}/app/inicio`, { tags: { paso: 'home' } });
  check(res, { 'home 2xx/3xx': (r) => r.status < 400 }) || errores.add(true);
  pausa();
  res = http.get(`${BASE_URL}/app/notificaciones`, { tags: { paso: 'novedades' } });
  check(res, { 'novedades 2xx/3xx': (r) => r.status < 400 }) || errores.add(true);
  pausa();
  res = http.get(`${BASE_URL}/app`, { tags: { paso: 'app' } });
  check(res, { 'app 2xx/3xx': (r) => r.status < 400 }) || errores.add(true);
  pausa();
}

// ---------------- Escenario "recibos": ráfagas de subida ----------------
function subirRecibo() {
  // Offset alto para no compartir usuarios con el escenario "lectores" y no
  // mezclar su latencia de sesión con la de la subida.
  const u = usuarios[(500 + __VU - 1) % usuarios.length];
  if (!login(u)) {
    erroresRecibo.add(true);
    return;
  }
  const img = imagenesBin[__ITER % imagenesBin.length];
  const datos = http.file(img.datos, img.nombre, 'image/jpeg');
  const res = http.post(
    `${BASE_URL}/api/leer`,
    { archivo: datos },
    { tags: { paso: 'subir_recibo' }, timeout: '60s' }
  );
  const ok = res.status === 200;
  erroresRecibo.add(!ok);
  check(res, { 'subir_recibo 200': () => ok });
}

export const options = {
  scenarios: {
    lectores: {
      executor: 'constant-vus',
      vus: 200,
      duration: '18m30s', // dura los 4 escalones de recibos + colchón
      exec: 'lectores',
    },
    // Cada escalón es su propio executor "ramping-arrival-rate"-like vía
    // constant-vus con startTime escalonado, así las ráfagas son estrictas
    // (N subidas concurrentes sostenidas, no una tasa promedio).
    recibos_2: {
      executor: 'constant-vus', vus: 2, duration: '4m', exec: 'subirRecibo', startTime: '0s',
    },
    recibos_5: {
      executor: 'constant-vus', vus: 5, duration: '4m', exec: 'subirRecibo', startTime: '4m',
    },
    recibos_10: {
      executor: 'constant-vus', vus: 10, duration: '4m', exec: 'subirRecibo', startTime: '8m',
    },
    recibos_20: {
      executor: 'constant-vus', vus: 20, duration: '4m', exec: 'subirRecibo', startTime: '12m',
    },
  },
  thresholds: {
    errores_app: [{ threshold: 'rate<0.20', abortOnFail: false }],
    errores_recibo: [{ threshold: 'rate<0.20', abortOnFail: false }],
  },
};

export { lectores, subirRecibo };
