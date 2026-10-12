/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md). Raíz: arma el árbol y lo monta.

   Bloque 3: los filtros y los indicadores, en la dirección B "Sala de mando"
   que eligió SDN sobre el mockup de D5. Los gráficos, el explorador y el
   Asistente se suman en los bloques que siguen.

   El recorrido es el de la v1 (static/dashboard.js), en el mismo orden:
   1. el estado sale de la dirección (`desdeParams`, con el saneo de la v1);
   2. se pide el catálogo de filtros y, con sus límites, se encaja el salario;
   3. recién entonces sale la primera ronda de pedidos;
   4. cada cambio de filtros actualiza la dirección y, 400 ms después del
      último (D8), sale otra ronda, que cancela a la anterior.

   Los módulos se importan POR NOMBRE ("panel/html"), nunca por ruta
   ("./html.js"): una ruta saldría sin su sello ?v= y quedaría cacheada una
   hora después de un deploy. test_dashboard_v2.py lo verifica. */
import { render } from "preact";
import { useCallback, useEffect, useReducer, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { crearReductor, desdeParams, aParams, aDireccion, limitesSalario } from "panel/estado";
import { crearPedir, enCola, MAX_EN_VUELO } from "panel/api";
import { fFecha, fechaLarga } from "panel/formato";
import { BarraFiltros, Cajon } from "panel/filtros";
import { Kpis } from "panel/kpis";
import { Capa } from "panel/capa";

const MAIN = document.querySelector("main");
/* Hoy lo dice el SERVIDOR (data-hoy), nunca el reloj del navegador: el
   servidor valida el rango contra la hora de Buenos Aires y un dispositivo
   adelantado pediría "mañana" (§3.1 del plan; misma regla que la v1). */
const HOY = MAIN.dataset.hoy || "";
const CONSULTAS = MAIN.dataset.consultas === "1";
const ESPERA_MS = 400;
const reducir = crearReductor({ hoy: HOY, consultas: CONSULTAS });
const pedir = crearPedir();

function Panel() {
  const [estado, despachar] = useReducer(reducir, null,
    () => desdeParams(new URLSearchParams(location.search), { hoy: HOY, consultas: CONSULTAS }));
  const [catalogo, setCatalogo] = useState(null);       // null: todavía no llegó
  const [lim, setLim] = useState({ min: null, max: null });
  const [afiliados, setAfiliados] = useState({});         // id -> {nombre, cuil...}, para las pastillas
  const [kpis, setKpis] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState(false);
  const [cajon, setCajon] = useState(false);
  const ronda = useRef(null);
  const primera = useRef(true);

  /* 2. El catálogo, con el mismo pedido que la v1. Si falla, el panel sigue:
     sin seccionales para elegir y sin slider de salario. */
  useEffect(() => {
    fetch("/admin/dashboard/filtros?desde=" + HOY + "&hasta=" + HOY)
      .then((r) => { if (!r.ok) throw new Error("filtros"); return r.json(); })
      .then((d) => {
        const l = limitesSalario(d.bruto_min, d.bruto_max);
        setLim(l);
        despachar({ tipo: "encajar", lim: l });
        setCatalogo(d);
      })
      .catch(() => setCatalogo({ seccionales: [], empresas: [] }));
  }, []);

  /* Un enlace con ?afiliado= trae el id sin el nombre: se pide para poder
     escribir la pastilla. Solo resuelve dentro del sindicato. */
  useEffect(() => {
    const id = estado.afiliado;
    if (!catalogo || !id || afiliados[id]) return;
    fetch("/admin/dashboard/afiliados?id=" + id)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => { if (d.items[0]) setAfiliados((x) => Object.assign({}, x, { [d.items[0].id]: d.items[0] })); })
      .catch(() => {});
  }, [catalogo, estado.afiliado]);

  const query = catalogo ? aParams(estado, lim).toString() : null;

  /* La ronda: hoy solo los indicadores; los paneles se suman acá, en la misma
     cola de a MAX_EN_VUELO (el cupo del servidor). */
  const refrescar = useCallback(() => {
    if (query === null) return;
    if (ronda.current) ronda.current.abort();
    const ac = new AbortController();
    ronda.current = ac;
    setCargando(true); setAviso(""); setFallo(false);
    enCola([
      () => pedir("kpis", new URLSearchParams(query), ac.signal)
        .then((d) => { setKpis(d); setCargando(false); })
        .catch((e) => {
          if (e.name === "AbortError" || e.message === "sesion") return;
          setCargando(false); setFallo(true);
          // El motivo del servidor se muestra: un 422 no puede dejar todo en "—".
          setAviso(e.detalle || "");
        }),
    ], MAX_EN_VUELO);
  }, [query]);

  // 4. La dirección compartible, al instante; la ronda, 400 ms después del último cambio.
  useEffect(() => {
    if (query === null) return;
    history.replaceState(null, "", location.pathname + "?" + aDireccion(estado, lim).toString());
  }, [query, estado.tab]);
  useEffect(() => {
    if (query === null) return undefined;
    if (primera.current) { primera.current = false; refrescar(); return undefined; }
    const id = setTimeout(refrescar, ESPERA_MS);
    return () => clearTimeout(id);
  }, [query]);

  // El encabezado común muestra la fecha de hoy y el rango que contestó el servidor.
  useEffect(() => {
    const h = document.getElementById("hoy-fecha");
    if (h) h.textContent = fechaLarga(HOY);
  }, []);
  useEffect(() => {
    const r = document.getElementById("rango-texto");
    if (r && kpis && kpis.rango) r.textContent = fFecha(kpis.rango.desde) + " – " + fFecha(kpis.rango.hasta);
  }, [kpis]);

  const elegirAfiliado = (it) => {
    setAfiliados((x) => Object.assign({}, x, { [it.id]: it }));
    despachar({ tipo: "poner", campo: "afiliado", valor: it.id });
  };
  const comun = { estado, despachar, hoy: HOY, lim, catalogo: catalogo || {} };

  return html`<div class="v2">
    <div class="v2-cabeza">
      <div>
        <h1 class="titulo-pagina">Panel Sindical</h1>
        <p class="v2-bajada">Lo que pasó en tu sindicato en el período elegido.</p>
      </div>
      <a class="v2-volver" href="/admin/dashboard"
        onClick=${(ev) => { ev.preventDefault(); location.href = "/admin/dashboard" + location.search; }}>Ver en la versión actual</a>
    </div>
    ${aviso && html`<div class="aviso-error" role="alert">${aviso}</div>`}
    <section class=${"v2-tablero" + (cargando ? " cargando" : "")} data-panel="kpis" aria-busy=${cargando}>
      <${BarraFiltros} ...${comun} afiliados=${afiliados} abrirCajon=${() => setCajon(true)} />
      <${Kpis} datos=${kpis} consultas=${CONSULTAS} error=${fallo} reintentar=${refrescar} />
    </section>
    <${Capa}><${Cajon} ...${comun} abierto=${cajon} cerrar=${() => setCajon(false)} alElegirAfiliado=${elegirAfiliado} /><//>
  </div>`;
}

render(html`<${Panel} />`, document.getElementById("panel"));
