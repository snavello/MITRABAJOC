/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md). Raíz: arma el árbol y lo monta.

   Bloque 1, el andamio: todavía no hay filtros ni paneles. Lo que se ve
   prueba de punta a punta que la cadena funciona: la plantilla del servidor,
   el importmap con un sello por archivo (D3), Preact y htm vendoreados, un
   módulo propio (`panel/html`) y la fecha de hoy que manda el servidor.

   Los módulos se importan POR NOMBRE ("panel/html"), nunca por ruta
   ("./html.js"): una ruta saldría sin su sello ?v= y quedaría cacheada una
   hora después de un deploy. test_dashboard_v2.py lo verifica. */
import { render } from "preact";
import { html } from "panel/html";

const MAIN = document.querySelector("main");

/* Hoy lo dice el SERVIDOR (data-hoy), nunca el reloj del navegador: el
   servidor valida el rango contra la hora de Buenos Aires y un dispositivo
   adelantado pediría "mañana" (§3.1 del plan; misma regla que la v1). */
const HOY = MAIN.dataset.hoy || "";

function fechaLarga(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  if (!a || !m || !d) return iso;
  return new Date(a, m - 1, d).toLocaleDateString("es-AR",
    { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

/* El enlace a la v1 lleva los filtros que haya en la dirección en el momento
   del clic (D6): las dos versiones leen los mismos parámetros. */
function irALaV1(ev) {
  ev.preventDefault();
  location.href = "/admin/dashboard" + location.search;
}

function Andamio({ hoy }) {
  return html`
    <section class="v2-andamio">
      <h1 class="titulo-pagina">Panel Sindical · versión nueva</h1>
      <p class="v2-bajada">En construcción. Los indicadores y los gráficos se suman por bloques.</p>
      <div class="panel" data-v2="andamio">
        <p>Hoy, según el servidor:</p>
        <p class="v2-hoy" data-v2="hoy">${fechaLarga(hoy)}</p>
        <a class="v2-volver" href="/admin/dashboard" onClick=${irALaV1}>Ver en la versión actual</a>
      </div>
    </section>`;
}

const fecha = document.getElementById("hoy-fecha");
if (fecha && HOY) fecha.textContent = fechaLarga(HOY);

render(html`<${Andamio} hoy=${HOY} />`, document.getElementById("panel"));
