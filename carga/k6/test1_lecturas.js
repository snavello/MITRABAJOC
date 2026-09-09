// Test 1 -- Lecturas: login -> home -> novedades -> "Tu Recibo" (que en esta
// app trae también Mis Aportes y el semáforo) -> credencial (QR), con
// pausas de 2-5s entre pasos, en escalones de 4 minutos: 50, 100, 200, 400,
// 800 concurrentes. Rutas reales de main.py -- ver carga/README.md para el
// porqué de "mis aportes"/"credencial" no siendo páginas propias.
//
// Uso:
//   BASE_URL=https://mitrabajo-pruebas.onrender.com k6 run \
//     --out json=log/test1_lecturas.json carga/k6/test1_lecturas.js
//
// Corta el escalón (no todo el test, k6 no aborta un escalón puntual) si el
// error rate acumulado supera 20% pasado 1 minuto de arranque -- ver
// resumen.py, que igual recalcula el error% por escalón a partir del JSON
// crudo y es la fuente de verdad para "en qué escalón se cortó".
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const BASE_URL = (__ENV.BASE_URL || 'https://mitrabajo-pruebas.onrender.com').replace(/\/$/, '');
const errores = new Rate('errores_app');

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

// Escalones de 4 minutos cada uno: 30s de rampa + 3m30s sostenidos.
export const options = {
  scenarios: {
    lecturas: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 50 },
        { duration: '3m30s', target: 50 },
        { duration: '30s', target: 100 },
        { duration: '3m30s', target: 100 },
        { duration: '30s', target: 200 },
        { duration: '3m30s', target: 200 },
        { duration: '30s', target: 400 },
        { duration: '3m30s', target: 400 },
        { duration: '30s', target: 800 },
        { duration: '3m30s', target: 800 },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    // Aviso temprano en consola; el corte real por escalón lo decide
    // resumen.py con el detalle por ventana de tiempo (un valor global de
    // k6 no distingue en qué escalón se cruzó el 20%).
    errores_app: [{ threshold: 'rate<0.20', abortOnFail: false }],
  },
};

function pausa() {
  sleep(2 + Math.random() * 3); // 2-5s
}

function marcar(res, nombre) {
  const ok = check(res, { [`${nombre} 2xx/3xx`]: (r) => r.status >= 200 && r.status < 400 });
  errores.add(!ok);
  return ok;
}

export default function () {
  const u = usuarios[(__VU - 1) % usuarios.length];
  const jar = http.cookieJar();

  // 1) login (la pantalla /ingresar primero, como un usuario real)
  let res = http.get(`${BASE_URL}/ingresar`, { tags: { paso: 'ingresar' } });
  marcar(res, 'ingresar');
  pausa();

  res = http.post(
    `${BASE_URL}/trabajador/login`,
    { cuil: u.cuil, clave: u.clave },
    { tags: { paso: 'login' }, redirects: 5 }
  );
  const logueado = marcar(res, 'login') && res.url.indexOf('/app/inicio') !== -1;
  if (!logueado) {
    // Sin sesión no tiene sentido seguir esta iteración -- cuenta como error
    // y se corta acá (no infla el resto de los pasos con 401 en cascada).
    errores.add(true);
    pausa();
    return;
  }
  pausa();

  // 2) home
  res = http.get(`${BASE_URL}/app/inicio`, { tags: { paso: 'home' } });
  marcar(res, 'home');
  pausa();

  // 3) novedades
  res = http.get(`${BASE_URL}/app/notificaciones`, { tags: { paso: 'novedades' } });
  marcar(res, 'novedades');
  pausa();

  // 4) "Tu Recibo" -- trae también Mis Aportes (semáforo) y los datos de
  // Credencial en el mismo contexto server-side (ver carga/README.md).
  res = http.get(`${BASE_URL}/app`, { tags: { paso: 'mis_aportes_y_recibo' } });
  marcar(res, 'app');
  pausa();

  // 5) credencial: QR efímero (requiere credencial ya emitida -- la genera
  // carga/preparar_datos.py para los 1.000 usuarios de prueba).
  res = http.get(`${BASE_URL}/api/credencial/qr`, { tags: { paso: 'credencial' } });
  marcar(res, 'credencial');
}
