/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md): los pedidos al servidor.

   Sin DOM, así que Node lo prueba (test_dashboard_v2_nucleo.py). Cada regla
   viene de la v1 (static/dashboard.js) y costó un incidente (§3.1 del plan):

   - A lo sumo MAX_EN_VUELO pedidos a la vez (`enCola`). Doce simultáneos
     por refresco fueron lo que trabó Pruebas el 2026-09-18; el cupo del
     servidor es de 4.
   - Un 503 es "estoy ocupado", no "el pedido está mal": se reintenta dos
     veces con una espera corta y creciente.
   - Un 403 es una sesión vencida o un permiso quitado: de vuelta a /admin.
   - Cualquier otro error trae el motivo del servidor (`detalle`): un 422
     por el rango de fechas tiene que verse, no dejar el panel en "—".
   - Todo es cancelable con un AbortSignal, también la espera del reintento. */

export const MAX_EN_VUELO = 4;
export const ESPERA_503_MS = [700, 1500];
export const BASE = "/admin/dashboard/";

/* Una espera que se corta si se aborta la ronda. */
export function esperar(ms, signal) {
  return new Promise((resolver, rechazar) => {
    if (signal && signal.aborted) { rechazar(new DOMException("Aborted", "AbortError")); return; }
    const id = setTimeout(resolver, ms);
    if (signal) signal.addEventListener("abort", () => {
      clearTimeout(id);
      rechazar(new DOMException("Aborted", "AbortError"));
    });
  });
}

/* Arma `pedir(ruta, query, signal)`. Lo de afuera se inyecta para poder
   probarlo sin red ni navegador: `fetch`, la espera entre reintentos y qué
   hacer cuando la sesión se perdió. */
export function crearPedir({
  fetch: traer = (...args) => globalThis.fetch(...args),
  esperar: esperarReintento = esperar,
  alPerderSesion = () => { globalThis.location.href = "/admin"; },
} = {}) {
  return function pedir(ruta, query, signal, intento = 0) {
    const texto = query ? query.toString() : "";
    return traer(BASE + ruta + (texto ? "?" + texto : ""), { signal }).then((r) => {
      if (r.status === 403) {
        alPerderSesion();
        throw new Error("sesion");
      }
      if (r.status === 503 && intento < ESPERA_503_MS.length) {
        return esperarReintento(ESPERA_503_MS[intento], signal)
          .then(() => pedir(ruta, query, signal, intento + 1));
      }
      if (r.ok) return r.json();
      return r.json().catch(() => ({})).then((cuerpo) => {
        const e = new Error(ruta + ": " + r.status);
        e.status = r.status;
        e.detalle = (cuerpo && cuerpo.detail) || "";
        throw e;
      });
    });
  };
}

/* Ejecuta `tareas` (funciones que devuelven promesas) en orden, con a lo sumo
   `limite` en vuelo a la vez. Resuelve cuando terminaron todas, bien o mal:
   cada tarea maneja su propio error. Es la `enCola` de la v1. */
export function enCola(tareas, limite = MAX_EN_VUELO) {
  return new Promise((resolver) => {
    let i = 0, vivas = 0, terminadas = 0;
    const total = tareas.length;
    if (!total) { resolver(); return; }
    function fin() {
      vivas--; terminadas++;
      if (terminadas === total) resolver(); else siguiente();
    }
    function siguiente() {
      while (vivas < limite && i < total) {
        const tarea = tareas[i++];
        vivas++;
        Promise.resolve().then(tarea).then(fin, fin);
      }
    }
    siguiente();
  });
}
