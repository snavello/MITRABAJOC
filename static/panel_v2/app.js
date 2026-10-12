/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md). Raíz: arma el árbol y lo monta.

   Dirección B, "Sala de mando" (elegida por SDN sobre el mockup de D5): la
   tarjeta oscura con los filtros y los indicadores, y debajo los paneles,
   el mapa y el explorador, como en la v1.

   El recorrido es el de la v1 (static/dashboard.js), en el mismo orden:
   1. el estado sale de la dirección (`desdeParams`, con el saneo de la v1);
   2. se pide el catálogo de filtros y, con sus límites, se encaja el salario;
   3. recién entonces sale la primera ronda: indicadores, los paneles en el
      orden de la v1 y el explorador, en una cola de a MAX_EN_VUELO (el cupo
      del servidor); al terminar, los contadores de las otras pestañas;
   4. cada cambio de filtros actualiza la dirección y, 400 ms después del
      último (D8), sale otra ronda, que cancela a la anterior. Cambiar SOLO
      de pestaña o pedir "Ver más" trae solo el explorador, como la v1.

   Los módulos se importan POR NOMBRE ("panel/html"), nunca por ruta
   ("./html.js"): una ruta saldría sin su sello ?v= y quedaría cacheada una
   hora después de un deploy. test_dashboard_v2.py lo verifica. */
import { render } from "preact";
import { useCallback, useEffect, useReducer, useRef, useState } from "preact/hooks";
import { html } from "panel/html";
import { crearReductor, desdeParams, aParams, aDireccion, limitesSalario, tabsDisponibles } from "panel/estado";
import { crearPedir, enCola, MAX_EN_VUELO } from "panel/api";
import { fFecha, fechaLarga } from "panel/formato";
import { BarraFiltros, Cajon } from "panel/filtros";
import { Kpis } from "panel/kpis";
import { Capa } from "panel/capa";
import { Panel, Serie, Validacion, Tramites, Notificaciones, Empresas, Consultas, Formato, Semaforo,
  MapaSeccionales } from "panel/graficos";
import { Explorador, Detalle } from "panel/explorador";
import { Asistente, BotonAsistente } from "panel/asistente";

const MAIN = document.querySelector("main");
/* Hoy lo dice el SERVIDOR (data-hoy), nunca el reloj del navegador: el
   servidor valida el rango contra la hora de Buenos Aires y un dispositivo
   adelantado pediría "mañana" (§3.1 del plan; misma regla que la v1). */
const HOY = MAIN.dataset.hoy || "";
const CONSULTAS = MAIN.dataset.consultas === "1";
const LOGO = MAIN.dataset.logo || "";
// Sin clave de la API el Asistente no existe: lo dice el servidor, no el JS.
const ASISTENTE = MAIN.dataset.asistente === "1";
const COLMENA = MAIN.dataset.colmena || "";
const TABS = tabsDisponibles(CONSULTAS);
const ESPERA_MS = 400;
const reducir = crearReductor({ hoy: HOY, consultas: CONSULTAS });
const pedir = crearPedir();

/* Los paneles de la ronda, en el orden de la v1 (nombre del panel, ruta). */
const PANELES = [["serie", "serie-recibos"], ["validacion", "validacion"], ["tramites", "tramites-seccional"],
  ["notif", "notificaciones"], ["empresas", "diferencias-empresa"], ["semaforo", "semaforo"],
  ["seccionales-geo", "seccionales-geo"], ["formato", "formato-semana"]];

function PanelSindical() {
  const [estado, despachar] = useReducer(reducir, null,
    () => desdeParams(new URLSearchParams(location.search), { hoy: HOY, consultas: CONSULTAS }));
  const [catalogo, setCatalogo] = useState(null);       // null: todavía no llegó
  const [lim, setLim] = useState({ min: null, max: null });
  const [afiliados, setAfiliados] = useState({});         // id -> {nombre, cuil...}, para las pastillas
  const [paneles, setPaneles] = useState({});             // nombre -> {datos, cargando, error}
  const [contadores, setContadores] = useState({});       // pestaña -> total
  const [aviso, setAviso] = useState("");
  const [cajon, setCajon] = useState(false);
  const [detalle, setDetalle] = useState(null);
  const [asist, setAsist] = useState("cerrado");          // "cerrado", "abierto" o "mini" (celular)
  const ronda = useRef(null);
  const soloExplorador = useRef(null);
  const primera = useRef(true);

  const marcar = (nombre, cambios) => setPaneles((p) => Object.assign({}, p,
    { [nombre]: Object.assign({}, p[nombre], cambios) }));

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

  /* 3. La ronda. Cada tarea pinta su panel apenas llega y maneja su propio
     error: un panel caído no rompe el resto (DASHBOARD.md §4.6). */
  const refrescar = useCallback(() => {
    if (query === null) return;
    if (ronda.current) ronda.current.abort();
    const ac = new AbortController();
    ronda.current = ac;
    const tab = estado.tab;
    setAviso("");
    const nombres = ["kpis"].concat(PANELES.map((x) => x[0]), ["explorador"], CONSULTAS ? ["bot"] : []);
    setPaneles((p) => {
      const n = Object.assign({}, p);
      nombres.forEach((x) => { n[x] = Object.assign({}, p[x], { cargando: true, error: null }); });
      return n;
    });
    const tarea = (nombre, ruta, extra, guardar) => () => {
      if (ac.signal.aborted) return Promise.resolve();
      const q = new URLSearchParams(query);
      Object.keys(extra || {}).forEach((k) => q.set(k, extra[k]));
      return pedir(ruta, q, ac.signal)
        .then((d) => { marcar(nombre, { datos: d, cargando: false, error: null }); if (guardar) guardar(d); })
        .catch((e) => {
          if (e.name === "AbortError" || e.message === "sesion") return;
          marcar(nombre, { cargando: false, error: e.detalle || "" });
          // El motivo del servidor se muestra arriba: un 422 no puede dejar todo en "—".
          if (e.detalle) setAviso(e.detalle);
        });
    };
    const tareas = [tarea("kpis", "kpis")]
      .concat(PANELES.map(([nombre, ruta]) => tarea(nombre, ruta)))
      .concat([tarea("explorador", "explorador/" + tab, { page: 1, page_size: 10 },
        (d) => setContadores((c) => Object.assign({}, c, { [tab]: d.total })))])
      .concat(CONSULTAS ? [tarea("bot", "consultas")] : []);
    // Los contadores de las otras pestañas son decorativos: van DESPUÉS de
    // los paneles, en cola también, y un error ahí no se muestra.
    enCola(tareas, MAX_EN_VUELO).then(() => {
      if (ac.signal.aborted) return undefined;
      return enCola(TABS.filter((t) => t !== tab).map((t) => () => {
        if (ac.signal.aborted) return Promise.resolve();
        const q = new URLSearchParams(query);
        q.set("page", 1); q.set("page_size", 1);
        return pedir("explorador/" + t, q, ac.signal)
          .then((d) => setContadores((c) => Object.assign({}, c, { [t]: d.total })))
          .catch(() => {});
      }), MAX_EN_VUELO);
    });
  }, [query, estado.tab]);

  /* Solo el explorador: al cambiar de pestaña sin cambiar filtros, o con
     "Ver más" (que suma la página siguiente a lo que ya se ve). */
  const cargarExplorador = (pagina, agregar) => {
    if (soloExplorador.current) soloExplorador.current.abort();
    const ac = new AbortController();
    soloExplorador.current = ac;
    const tab = estado.tab;
    const q = new URLSearchParams(query);
    q.set("page", pagina); q.set("page_size", 10);
    marcar("explorador", { cargando: true, error: null });
    pedir("explorador/" + tab, q, ac.signal)
      .then((d) => {
        setPaneles((p) => {
          const previo = (p.explorador && p.explorador.datos) || { items: [] };
          const datos = agregar ? Object.assign({}, d, { items: previo.items.concat(d.items) }) : d;
          return Object.assign({}, p, { explorador: { datos, cargando: false, error: null } });
        });
        setContadores((c) => Object.assign({}, c, { [tab]: d.total }));
      })
      .catch((e) => {
        if (e.name === "AbortError" || e.message === "sesion") return;
        marcar("explorador", { cargando: false, error: e.detalle || "" });
      });
  };

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

  /* Pestaña nueva con los mismos filtros: solo el explorador. Si en el mismo
     paso cambiaron los filtros (un clic en un gráfico filtra Y cambia la
     pestaña), la ronda ya la trae y no se pide dos veces. */
  const tabPrevia = useRef(estado.tab);
  const queryPrevia = useRef(query);
  useEffect(() => {
    if (tabPrevia.current === estado.tab) return;
    tabPrevia.current = estado.tab;
    if (query === null || queryPrevia.current !== query) return;
    cargarExplorador(1, false);
  }, [estado.tab]);
  useEffect(() => {
    if (estado.paginas > 1 && query !== null) cargarExplorador(estado.paginas, true);
  }, [estado.paginas]);
  useEffect(() => { queryPrevia.current = query; });

  // El encabezado común muestra la fecha de hoy y el rango que contestó el servidor.
  useEffect(() => {
    const h = document.getElementById("hoy-fecha");
    if (h) h.textContent = fechaLarga(HOY);
  }, []);
  const kpis = paneles.kpis && paneles.kpis.datos;
  useEffect(() => {
    const r = document.getElementById("rango-texto");
    if (r && kpis && kpis.rango) r.textContent = fFecha(kpis.rango.desde) + " – " + fFecha(kpis.rango.hasta);
  }, [kpis]);

  const registrarAfiliado = (it) => setAfiliados((x) => Object.assign({}, x, { [it.id]: it }));
  const elegirAfiliado = (it) => {
    registrarAfiliado(it);
    despachar({ tipo: "poner", campo: "afiliado", valor: it.id });
  };
  const comun = { estado, despachar, hoy: HOY, lim, catalogo: catalogo || {} };
  const p = (nombre) => paneles[nombre] || {};
  const datos = (nombre) => p(nombre).datos || null;
  const graf = { estado, despachar };
  const reintentar = () => refrescar();
  const kpi = p("kpis");

  return html`<div class="v2">
    <div class="v2-cabeza">
      <div>
        <h1 class="titulo-pagina">Panel Sindical</h1>
        <p class="v2-bajada">Lo que pasó en tu sindicato en el período elegido.</p>
      </div>
      <div class="v2-acciones">
        ${ASISTENTE && html`<${BotonAsistente} modo=${asist} setModo=${setAsist} colmena=${COLMENA} />`}
        <a class="v2-volver" href="/admin/dashboard"
          onClick=${(ev) => { ev.preventDefault(); location.href = "/admin/dashboard" + location.search; }}>Ver en la versión actual</a>
      </div>
    </div>
    ${aviso && html`<div class="aviso-error" role="alert">${aviso}</div>`}
    <section class=${"v2-tablero" + (kpi.cargando ? " cargando" : "")} data-panel="kpis" aria-busy=${!!kpi.cargando}>
      <${BarraFiltros} ...${comun} afiliados=${afiliados} abrirCajon=${() => setCajon(true)} />
      <${Kpis} datos=${kpi.datos || null} consultas=${CONSULTAS}
        error=${kpi.error !== undefined && kpi.error !== null} reintentar=${reintentar} />
    </section>

    <div class="grid v2-grid">
      <${Panel} nombre="serie" titulo="Recibos procesados por día" sub="Volumen de recibos analizados por el validador"
        clase="span8" estado=${p("serie")} reintentar=${reintentar}><${Serie} datos=${datos("serie")} /><//>
      <${Panel} nombre="validacion" titulo="Resultado de validación" sub="Tocá un segmento para filtrar"
        clase="span4" estado=${p("validacion")} reintentar=${reintentar}><${Validacion} datos=${datos("validacion")} ...${graf} /><//>
      <${Panel} nombre="tramites" titulo="Trámites por seccional y estado" sub="Tocá un segmento para filtrar seccional y estado a la vez"
        clase="span4" estado=${p("tramites")} reintentar=${reintentar}><${Tramites} datos=${datos("tramites")} ...${graf} /><//>
      <${Panel} nombre="empresas" titulo="Diferencias detectadas por empresa" sub="Top 6 · monto total observado · tocá para sumar al filtro"
        clase="span4" estado=${p("empresas")} reintentar=${reintentar}><${Empresas} datos=${datos("empresas")} ...${graf} /><//>
      <${Panel} nombre="notif" titulo="Notificaciones · leídas vs. no leídas" sub="Tocá una barra para ver el detalle de ese tipo"
        clase="span4" estado=${p("notif")} reintentar=${reintentar}><${Notificaciones} datos=${datos("notif")} ...${graf} /><//>
      ${CONSULTAS && html`<${Panel} nombre="bot" titulo="Consultas al asistente" sub="Temas más consultados por los afiliados"
        estado=${p("bot")} reintentar=${reintentar}><${Consultas} datos=${datos("bot")} ...${graf} /><//>`}
      <${Panel} nombre="formato" titulo="Adopción del nuevo formato (Ley 27.802)" sub="Recibos por formato, semana a semana"
        clase="span7" estado=${p("formato")} reintentar=${reintentar}><${Formato} datos=${datos("formato")} /><//>
      <${Panel} nombre="semaforo" titulo="Semáforo de aportes"
        sub="Días desde el último depósito que imprime el recibo (formato Ley 27.802 — todavía son pocos recibos en relación al total, tomalo como indicativo)"
        clase="span5" estado=${p("semaforo")} reintentar=${reintentar}><${Semaforo} datos=${datos("semaforo")} /><//>
      <${Panel} nombre="seccionales-geo" titulo="Mapa de seccionales"
        sub=${html`Tocá un marcador para filtrar todo el panel por esa seccional. <b>Afiliados</b> y <b>ingresaron</b> son una foto del padrón y no cambian con el período; los otros cuatro sí.`}
        estado=${p("seccionales-geo")} reintentar=${reintentar}>
        <${MapaSeccionales} datos=${datos("seccionales-geo")} ...${graf} logo=${LOGO} /><//>
      <${Panel} nombre="explorador" titulo="Explorador de datos" estado=${p("explorador")} reintentar=${reintentar}>
        <${Explorador} datos=${datos("explorador")} ...${graf} tabs=${TABS} contadores=${contadores}
          abrirDetalle=${setDetalle} /><//>
    </div>

    <${Capa}>
      <${Cajon} ...${comun} abierto=${cajon} cerrar=${() => setCajon(false)} alElegirAfiliado=${elegirAfiliado} />
      <${Detalle} pedido=${detalle} cerrar=${() => setDetalle(null)} />
      ${ASISTENTE && html`<${Asistente} modo=${asist} setModo=${setAsist} estado=${estado} lim=${lim}
        despachar=${despachar} catalogo=${catalogo || {}} registrarAfiliado=${registrarAfiliado} />`}
    <//>
  </div>`;
}

render(html`<${PanelSindical} />`, document.getElementById("panel"));
