/* Panel Sindical v2 (PLAN_DASHBOARD_V2.md, D8): el estado de los filtros.

   PURO: no toca el DOM ni la red, así que Node lo importa y lo prueba
   (test_dashboard_v2_nucleo.py). Un solo objeto de estado, con la misma forma
   que el `S` de la v1, y una sola función que lo cambia (`crearReductor`).

   Nació con la línea roja 3 del plan: **los mismos parámetros que la v1**,
   rarezas incluidas, para que una dirección guardada de la v1 abra igual. La
   v1 ya no existe (2026-10-25): test_dashboard_v2_nucleo.py fija ahora esos
   parámetros con casos escritos a mano y con miles de direcciones al azar.

   Diferencias de forma con la v1, que no cambian ningún pedido:
   - Las fechas son texto "AAAA-MM-DD", no objetos Date: se comparan como
     texto y el estado se puede copiar y comparar entero.
   - Seccionales y empresas son listas en el orden en que se eligieron (la v1
     usa Set, que también conserva ese orden). */

export const FORMATOS = ["viejo", "nuevo"];
export const RESULTADOS = ["ok", "con_diferencias"];
export const ESTADOS_TRAMITE = ["abierto", "en_proceso", "resuelto"];
export const TIPOS_NOTIF = ["manual", "sistema"];

export function tabsDisponibles(consultas) {
  return ["recibos", "tramites", "notificaciones"].concat(consultas ? ["consultas"] : []);
}

/* ---------------- Fechas (las mismas cuentas que la v1) ---------------- */

/* Date -> "AAAA-MM-DD", en la hora local, como `fISO` de la v1. */
export function fISO(d) {
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
    String(d.getDate()).padStart(2, "0");
}

/* "AAAA-MM-DD" -> Date, como `deISO` de la v1. Un día que no existe se corre
   (2026-02-30 es el 2 de marzo): así lo hace la v1 y así tiene que quedar. */
function deISO(s) {
  const p = String(s).split("-");
  return new Date(+p[0], +p[1] - 1, +p[2]);
}

/* El texto normalizado de una fecha, o null si no es una fecha. */
export function normalizarFecha(s) {
  const d = deISO(s);
  return isNaN(d) ? null : fISO(d);
}

/* `iso` menos `dias` días, con la cuenta de calendario de la v1 (setDate). */
export function restarDias(iso, dias) {
  const d = deISO(iso);
  d.setDate(d.getDate() - dias);
  return fISO(d);
}

/* ---------------- Estado ---------------- */

/* El período con que abre el panel y al que vuelve "Reiniciar": los últimos
   30 días contando hoy (G7-02). Abría en "Hoy" y, a media mañana, la primera
   vista de la función estrella era todo cero. Un enlace con su período
   explícito sigue mandando. */
export const DIAS_INICIALES = 30;

export function estadoInicial(hoy) {
  return {
    desde: restarDias(hoy, DIAS_INICIALES - 1), hasta: hoy,
    seccionales: [], empresas: [],
    formato: "", salMin: null, salMax: null,
    resultado: "", estadoTramite: "", tipoNotif: "", tema: "",
    afiliado: null,                  // id de Trabajador, nunca el CUIL
    tab: "recibos", paginas: 1,
  };
}

/* Los límites del slider de salario, en miles y redondeados a 50 mil, como
   `initCatalogo` de la v1. Sin rango para mover, {min: null, max: null}: el
   slider no se muestra y el salario nunca viaja. */
export function limitesSalario(brutoMin, brutoMax) {
  if (brutoMin === null || brutoMin === undefined || brutoMax === null ||
      brutoMax === undefined || !(brutoMax > brutoMin)) {
    return { min: null, max: null };
  }
  return { min: Math.floor(brutoMin / 50000) * 50, max: Math.ceil(brutoMax / 50000) * 50 };
}

function agregarIds(lista, valores) {
  const salida = lista.slice();
  valores.forEach((v) => {
    const n = +v;
    if (n && salida.indexOf(n) < 0) salida.push(n);
  });
  return salida;
}

/* Vuelca unos query params sobre un estado, como `estadoDeParams` de la v1:
   lo usan la dirección al cargar y el Asistente al aplicar filtros.

   - Sin `desde` o sin `hasta`, o con fechas que no valen (que no son fecha,
     un `hasta` futuro, `desde` después de `hasta`), NO se aplica nada: queda
     `base` tal cual. Si no, el servidor rechazaría todo con un 422.
   - Lo que no está en su lista cerrada se descarta.
   - Seccionales y empresas se SUMAN a las de `base`. */
export function desdeParams(q, { hoy, consultas = false, base = null } = {}) {
  const e = Object.assign(estadoInicial(hoy), base || {});
  if (!q.get("desde") || !q.get("hasta")) return e;
  const d = normalizarFecha(q.get("desde"));
  const h = normalizarFecha(q.get("hasta"));
  if (d === null || h === null || h > hoy || d > h) return e;
  e.desde = d; e.hasta = h;
  e.seccionales = agregarIds(e.seccionales, q.getAll("seccionales"));
  e.empresas = agregarIds(e.empresas, q.getAll("empresas"));
  e.formato = FORMATOS.indexOf(q.get("formato")) >= 0 ? q.get("formato") : "";
  /* El salario viaja en pesos y se guarda en miles. Un `sal_min` que no es
     número no se descarta en la v1: queda "puesto pero inválido", y eso hace
     que se respete el `sal_max` (ver `conLimites`). -Infinity reproduce ese
     caso y, al pasar por los límites, queda en el piso del slider. */
  if (q.get("sal_min")) {
    const v = Math.round(+q.get("sal_min") / 1000);
    e.salMin = isNaN(v) ? -Infinity : v;
  }
  if (q.get("sal_max")) {
    const v = Math.round(+q.get("sal_max") / 1000);
    e.salMax = isNaN(v) ? null : v;
  }
  e.resultado = RESULTADOS.indexOf(q.get("resultado")) >= 0 ? q.get("resultado") : "";
  e.estadoTramite = ESTADOS_TRAMITE.indexOf(q.get("estado_tramite")) >= 0 ? q.get("estado_tramite") : "";
  e.tipoNotif = TIPOS_NOTIF.indexOf(q.get("tipo_notif")) >= 0 ? q.get("tipo_notif") : "";
  e.tema = q.get("tema") || "";
  e.afiliado = +q.get("afiliado") || null;
  if (tabsDisponibles(consultas).indexOf(q.get("tab")) >= 0) e.tab = q.get("tab");
  return e;
}

/* Encaja el salario en los límites del slider, como `initCatalogo` de la v1.
   Rareza de la v1, copiada a propósito: sin `sal_min`, también se descarta el
   `sal_max` de la dirección. */
export function conLimites(e, lim) {
  if (lim.min === null || lim.max === null) return e;
  const s = Object.assign({}, e);
  if (s.salMin === null) { s.salMin = lim.min; s.salMax = lim.max; }
  else { s.salMin = Math.max(lim.min, s.salMin); s.salMax = Math.min(lim.max, s.salMax || lim.max); }
  return s;
}

/* Los query params de un pedido al servidor, en el mismo orden que
   `paramsDeEstado` de la v1. El salario viaja solo si se movió del límite. */
export function aParams(e, lim) {
  const q = new URLSearchParams();
  q.set("desde", e.desde); q.set("hasta", e.hasta);
  e.seccionales.forEach((id) => q.append("seccionales", id));
  e.empresas.forEach((id) => q.append("empresas", id));
  if (e.formato) q.set("formato", e.formato);
  if (e.salMin !== null && lim.min !== null && e.salMin > lim.min) q.set("sal_min", e.salMin * 1000);
  if (e.salMax !== null && lim.max !== null && e.salMax < lim.max) q.set("sal_max", e.salMax * 1000);
  if (e.resultado) q.set("resultado", e.resultado);
  if (e.estadoTramite) q.set("estado_tramite", e.estadoTramite);
  if (e.tipoNotif) q.set("tipo_notif", e.tipoNotif);
  if (e.tema) q.set("tema", e.tema);
  if (e.afiliado) q.set("afiliado", e.afiliado);
  return q;
}

/* La dirección compartible: los params del pedido más la pestaña, si no es la
   de recibos (`urlCompartible` de la v1). */
export function aDireccion(e, lim) {
  const q = aParams(e, lim);
  if (e.tab !== "recibos") q.set("tab", e.tab);
  return q;
}

/* El estado del panel como lo espera el Asistente (`estadoPlano` de la v1):
   las claves de la dirección, con el salario en pesos y solo si se movió del
   límite, más el afiliado y la pestaña. Es lo que viaja al servidor con cada
   pregunta y la foto que se restaura con "Volver". */
export function estadoPlano(e, lim) {
  const q = aParams(e, lim);
  return {
    desde: q.get("desde"), hasta: q.get("hasta"),
    seccionales: q.getAll("seccionales").map(Number),
    empresas: q.getAll("empresas").map(Number),
    formato: q.get("formato") || "", resultado: q.get("resultado") || "",
    estado_tramite: q.get("estado_tramite") || "", tipo_notif: q.get("tipo_notif") || "",
    sal_min: q.get("sal_min") ? +q.get("sal_min") : null,
    sal_max: q.get("sal_max") ? +q.get("sal_max") : null,
    tema: q.get("tema") || "", afiliado: e.afiliado, tab: e.tab,
  };
}

/* Unos filtros planos (los que manda el Asistente, o la foto de
   `estadoPlano`) como params para la acción "aplicar", con el armado de
   `aplicarEstado` de la v1: lo vacío no viaja y las listas se repiten. */
export function comoParams(filtros) {
  const q = new URLSearchParams();
  Object.keys(filtros || {}).forEach((k) => {
    const v = filtros[k];
    if (v === null || v === undefined || v === "") return;
    if (Array.isArray(v)) v.forEach((x) => q.append(k, x));
    else q.set(k, v);
  });
  return q;
}

/* El atajo de período que corresponde al rango, o null: "hoy", "7", "30" o
   "90" solo si el rango termina hoy y dura eso (`presetActivo` de la v1). */
export function presetActivo(e, hoy) {
  if (e.hasta !== hoy) return null;
  const dias = Math.round((deISO(e.hasta) - deISO(e.desde)) / 864e5) + 1;
  return { 1: "hoy", 7: "7", 30: "30", 90: "90" }[dias] || null;
}

const ESTADO_TRAMITE_TXT = { abierto: "Abiertos", en_proceso: "En proceso", resuelto: "Resueltos" };

function nombreDe(lista, id) {
  const it = (lista || []).find((x) => x.id === id);
  return it ? it.nombre : "#" + id;
}

/* Los filtros puestos, como pastillas que se sacan de a una: el mismo texto y
   el mismo orden que `pintarChips` de la v1. Cada una trae la acción que la
   saca. El período no es una pastilla: siempre hay uno. */
export function filtrosActivos(e, { catalogo = {}, lim = { min: null, max: null }, afiliados = {} } = {}) {
  const salida = [];
  const poner = (campo, valor) => ({ tipo: "poner", campo, valor });
  e.seccionales.forEach((id) => salida.push({ txt: "Seccional: " + nombreDe(catalogo.seccionales, id),
    accion: { tipo: "alternar", campo: "seccionales", id } }));
  e.empresas.forEach((id) => salida.push({ txt: "Empresa: " + nombreDe(catalogo.empresas, id),
    accion: { tipo: "alternar", campo: "empresas", id } }));
  if (e.formato) salida.push({ txt: "Formato: " + (e.formato === "nuevo" ? "Ley 27.802" : "Anterior"),
    accion: poner("formato", "") });
  if (e.resultado) salida.push({ txt: "Resultado: " + (e.resultado === "ok" ? "Correctos" : "Con diferencias"),
    accion: poner("resultado", "") });
  if (e.estadoTramite) salida.push({ txt: "Trámites: " + ESTADO_TRAMITE_TXT[e.estadoTramite],
    accion: poner("estadoTramite", "") });
  if (e.tipoNotif) salida.push({ txt: "Notif.: " + (e.tipoNotif === "manual" ? "Comunicaciones" : "Trámites"),
    accion: poner("tipoNotif", "") });
  if (e.tema) salida.push({ txt: "Tema: " + e.tema, accion: poner("tema", "") });
  if (e.afiliado) salida.push({ txt: "Afiliado: " + (afiliados[e.afiliado] ? afiliados[e.afiliado].nombre : "#" + e.afiliado),
    accion: poner("afiliado", null) });
  if (lim.min !== null && e.salMin !== null && (e.salMin > lim.min || e.salMax < lim.max)) {
    const n = (v) => Number(v).toLocaleString("es-AR");
    salida.push({ txt: "Bruto: $" + n(e.salMin) + "k – $" + n(e.salMax) + "k",
      accion: { tipo: "salario", min: lim.min, max: lim.max } });
  }
  return salida;
}

/* ---------------- Cambios ---------------- */

function sinFiltros(e, lim) {
  return Object.assign({}, e, {
    seccionales: [], empresas: [],
    formato: "", resultado: "", estadoTramite: "", tipoNotif: "", tema: "", afiliado: null,
    salMin: lim.min, salMax: lim.max,
    tab: "recibos", paginas: 1,
  });
}

function alternarId(lista, id) {
  return lista.indexOf(id) >= 0 ? lista.filter((x) => x !== id) : lista.concat([id]);
}

/* La única función que cambia el estado (D8). `accion` es un objeto
   {tipo, ...} o una lista de ellos, que se aplican en orden: un clic en un
   gráfico filtra Y cambia la pestaña del explorador en un solo paso.

   Todo cambio vuelve a la primera página del explorador, salvo "ver más". */
export function crearReductor({ hoy, consultas = false }) {
  const tabs = tabsDisponibles(consultas);

  function uno(e, a) {
    switch (a.tipo) {
      case "preset": {
        // "hoy", "7", "30" o "90": los últimos N días contando hoy.
        const desde = a.valor === "hoy" ? hoy : restarDias(hoy, +a.valor - 1);
        return Object.assign({}, e, { desde, hasta: hoy, paginas: 1 });
      }
      case "rango":
        return Object.assign({}, e, { desde: a.desde, hasta: a.hasta, paginas: 1 });
      case "alternar":            // seccionales o empresas: suma o saca un id
        return Object.assign({}, e, { [a.campo]: alternarId(e[a.campo], a.id), paginas: 1 });
      case "poner":               // formato, resultado, estadoTramite, tipoNotif, tema, afiliado
        return Object.assign({}, e, { [a.campo]: a.valor, paginas: 1 });
      case "alternarValor":       // el clic en un gráfico: lo mismo otra vez lo apaga
        return Object.assign({}, e, { [a.campo]: e[a.campo] === a.valor ? "" : a.valor, paginas: 1 });
      case "tramiteSeccional": {
        /* El clic en una barra de trámites por seccional × estado: filtra
           seccional Y estado; el mismo clic otra vez saca los dos (la v1, en
           el onClick del gráfico de trámites). */
        const id = a.seccional;
        const misma = id !== null && e.seccionales.indexOf(id) >= 0;
        if (misma && e.estadoTramite === a.estado) {
          return Object.assign({}, e, { seccionales: e.seccionales.filter((x) => x !== id),
            estadoTramite: "", paginas: 1 });
        }
        return Object.assign({}, e, {
          seccionales: id !== null && !misma ? e.seccionales.concat([id]) : e.seccionales,
          estadoTramite: a.estado, paginas: 1 });
      }
      case "salario":
        return Object.assign({}, e, { salMin: a.min, salMax: a.max, paginas: 1 });
      case "encajar":             // llegó el catálogo: el salario entra en los límites
        return conLimites(e, a.lim);
      case "tab":
        // Una pestaña que no existe (consultas apagado) no se elige.
        return tabs.indexOf(a.valor) < 0 ? e : Object.assign({}, e, { tab: a.valor, paginas: 1 });
      case "verMas":
        return Object.assign({}, e, { paginas: e.paginas + 1 });
      case "reiniciar":           // los últimos 30 días, sin filtros, pestaña Recibos
        return Object.assign(sinFiltros(e, a.lim), { desde: restarDias(hoy, DIAS_INICIALES - 1), hasta: hoy });
      case "aplicar": {
        /* Reemplaza TODO el estado por otro en forma de params (el Asistente,
           o una foto previa al "Volver"), como `aplicarEstado` de la v1: se
           limpian los filtros y se vuelca encima. Sin fechas válidas en lo
           que llega, quedan las de antes. La v1 no vuelve a encajar el
           salario en los límites acá, y la v2 tampoco. */
        return desdeParams(a.params, { hoy, consultas, base: sinFiltros(e, a.lim) });
      }
      default:
        throw new Error("acción desconocida: " + a.tipo);
    }
  }

  return function reducir(e, accion) {
    return (Array.isArray(accion) ? accion : [accion]).reduce(uno, e);
  };
}
