/* Panel Sindical (docs/DASHBOARD.md, Fase 2).
   Un único objeto de estado de filtros; cada cambio dispara UNA ronda de
   fetches en paralelo (debounce 250 ms + AbortController). Los agregados
   vienen listos del servidor: acá no se calcula nada de negocio, solo se
   pinta. El color --destacado marca EXCLUSIVAMENTE selecciones y filtros
   activos. */
(function () {
  "use strict";

  var HOY = new Date(); HOY.setHours(0, 0, 0, 0);
  var REDUCIR = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var CONSULTAS_ON = document.querySelector("main").dataset.consultas === "1";
  var ASISTENTE_ON = document.querySelector("main").dataset.asistente === "1";

  var css = getComputedStyle(document.documentElement);
  function color(v) { return css.getPropertyValue(v).trim(); }
  var C = {
    destacado: color("--destacado"),
    primario: color("--marca-primario"),
    acento: color("--marca-acento"),
    apoyo: color("--marca-apoyo"),
    ok: color("--ok"), error: color("--error"), aviso: color("--aviso"),
    gris: color("--gris"), linea: color("--linea"),
  };
  function mezcla(hex, pct) {
    // hex + blanco (pct = cuánto del color queda) -- para atenuar barras.
    var n = parseInt(hex.replace("#", ""), 16);
    var r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    var f = function (x) { return Math.round(x * pct + 255 * (1 - pct)); };
    return "rgb(" + f(r) + "," + f(g) + "," + f(b) + ")";
  }

  var fmtN = function (n) { return (n === null || n === undefined) ? "—" : Number(n).toLocaleString("es-AR"); };
  var fmtM = function (n) { return (n === null || n === undefined) ? "—" : "$ " + Math.round(n).toLocaleString("es-AR"); };
  var fISO = function (d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  };
  var deISO = function (s) { var p = s.split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); };
  var fCorta = function (iso) { var p = iso.split("-"); return p[2] + "/" + p[1]; };
  var fFecha = function (s) {
    // "AAAA-MM-DD[ HH:MM]" -> "dd/mm/aaaa"
    if (!s) return "—";
    var p = s.slice(0, 10).split("-");
    return p[2] + "/" + p[1] + "/" + p[0];
  };
  function esc(t) {
    return String(t === null || t === undefined ? "—" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  var $ = function (id) { return document.getElementById(id); };

  /* ================= Estado ================= */
  var S = {
    desde: new Date(HOY), hasta: new Date(HOY),
    seccionales: new Set(), empresas: new Set(),
    formato: "", salMin: null, salMax: null,
    resultado: "", estadoTramite: "", tipoNotif: "", tema: "",
    tab: "recibos", paginas: 1,
  };
  var LIM = { min: null, max: null };        // límites del slider (en miles)
  var CATALOGO = { seccionales: [], empresas: [] };
  var calVista = new Date(HOY.getFullYear(), HOY.getMonth(), 1);
  var calEligiendo = false;

  /* ================= Serialización en la URL (§4.6) ================= */
  function paramsDeEstado() {
    var q = new URLSearchParams();
    q.set("desde", fISO(S.desde)); q.set("hasta", fISO(S.hasta));
    S.seccionales.forEach(function (id) { q.append("seccionales", id); });
    S.empresas.forEach(function (id) { q.append("empresas", id); });
    if (S.formato) q.set("formato", S.formato);
    if (S.salMin !== null && LIM.min !== null && S.salMin > LIM.min) q.set("sal_min", S.salMin * 1000);
    if (S.salMax !== null && LIM.max !== null && S.salMax < LIM.max) q.set("sal_max", S.salMax * 1000);
    if (S.resultado) q.set("resultado", S.resultado);
    if (S.estadoTramite) q.set("estado_tramite", S.estadoTramite);
    if (S.tipoNotif) q.set("tipo_notif", S.tipoNotif);
    if (S.tema) q.set("tema", S.tema);
    return q;
  }
  function urlCompartible() {
    var q = paramsDeEstado();
    if (S.tab !== "recibos") q.set("tab", S.tab);
    history.replaceState(null, "", location.pathname + "?" + q.toString());
  }
  function estadoDeUrl() { estadoDeParams(new URLSearchParams(location.search)); }

  // Vuelca unos query params sobre el estado. Lo usan la URL al cargar y el
  // Asistente al aplicar filtros: un solo camino para "estado desde afuera".
  function estadoDeParams(q) {
    if (!q.get("desde") || !q.get("hasta")) return;
    try {
      var d = deISO(q.get("desde")), h = deISO(q.get("hasta"));
      if (isNaN(d) || isNaN(h) || h > HOY || d > h) return;
      S.desde = d; S.hasta = h;
    } catch (e) { return; }
    q.getAll("seccionales").forEach(function (v) { if (+v) S.seccionales.add(+v); });
    q.getAll("empresas").forEach(function (v) { if (+v) S.empresas.add(+v); });
    S.formato = ["viejo", "nuevo"].indexOf(q.get("formato")) >= 0 ? q.get("formato") : "";
    if (q.get("sal_min")) S.salMin = Math.round(+q.get("sal_min") / 1000);
    if (q.get("sal_max")) S.salMax = Math.round(+q.get("sal_max") / 1000);
    S.resultado = ["ok", "con_diferencias"].indexOf(q.get("resultado")) >= 0 ? q.get("resultado") : "";
    S.estadoTramite = ["abierto", "en_proceso", "resuelto"].indexOf(q.get("estado_tramite")) >= 0 ? q.get("estado_tramite") : "";
    S.tipoNotif = ["manual", "sistema"].indexOf(q.get("tipo_notif")) >= 0 ? q.get("tipo_notif") : "";
    S.tema = q.get("tema") || "";
    var tabs = ["recibos", "tramites", "notificaciones"].concat(CONSULTAS_ON ? ["consultas"] : []);
    if (tabs.indexOf(q.get("tab")) >= 0) S.tab = q.get("tab");
  }

  /* ================= Ronda de fetches ================= */
  var abortador = null, debounceId = null;

  function pedir(ruta, extra, signal) {
    var q = paramsDeEstado();
    if (extra) Object.keys(extra).forEach(function (k) { q.set(k, extra[k]); });
    return fetch("/admin/dashboard/" + ruta + "?" + q.toString(), { signal: signal })
      .then(function (r) {
        if (r.status === 403) { location.href = "/admin"; throw new Error("sesion"); }
        if (!r.ok) throw new Error(ruta + ": " + r.status);
        return r.json();
      });
  }

  function panelDe(nombre) { return document.querySelector('[data-panel="' + nombre + '"]'); }

  function cargarPanel(nombre, promesa, pintar) {
    var p = panelDe(nombre);
    if (!p) return promesa;
    p.classList.add("cargando"); p.classList.remove("con-error");
    return promesa.then(function (datos) {
      pintar(datos);
      p.classList.remove("cargando");
    }).catch(function (e) {
      if (e.name === "AbortError" || e.message === "sesion") return;
      p.classList.remove("cargando"); p.classList.add("con-error");
    });
  }

  function refrescar() {
    if (abortador) abortador.abort();
    abortador = new AbortController();
    var signal = abortador.signal;
    S.paginas = 1;
    urlCompartible();
    pintarControles();

    var rondas = [
      cargarPanel("serie", pedir("serie-recibos", null, signal), pintarLinea),
      cargarPanel("validacion", pedir("validacion", null, signal), pintarDona),
      cargarPanel("tramites", pedir("tramites-seccional", null, signal), pintarTramites),
      cargarPanel("notif", pedir("notificaciones", null, signal), pintarNotif),
      cargarPanel("empresas", pedir("diferencias-empresa", null, signal), pintarEmpresas),
      cargarPanel("semaforo", pedir("semaforo", null, signal), pintarSemaforo),
      cargarPanel("formato", pedir("formato-semana", null, signal), pintarFormato),
      cargarPanel("explorador", pedir("explorador/" + S.tab, { page: 1, page_size: 10 }, signal),
        function (d) { pintarTabla(d, false); }),
      pintarKPIs(signal),
    ];
    if (CONSULTAS_ON) rondas.push(cargarPanel("bot", pedir("consultas", null, signal), pintarBot));

    // Contadores en vivo de las pestañas NO activas (total con page_size=1).
    tabsDisponibles().forEach(function (t) {
      if (t === S.tab) return;
      pedir("explorador/" + t, { page: 1, page_size: 1 }, signal)
        .then(function (d) { $("cnt-" + t).textContent = fmtN(d.total); })
        .catch(function () { });
    });
    return Promise.all(rondas);
  }

  function cambio() {
    clearTimeout(debounceId);
    debounceId = setTimeout(refrescar, 250);
  }

  function tabsDisponibles() {
    return ["recibos", "tramites", "notificaciones"].concat(CONSULTAS_ON ? ["consultas"] : []);
  }

  /* ================= KPIs ================= */
  function setKpi(id, texto) {
    var el = $(id);
    if (!el) return;
    el.classList.add("flash");
    setTimeout(function () { el.textContent = texto; el.classList.remove("flash"); }, REDUCIR ? 0 : 120);
  }
  function pintarKPIs(signal) {
    var seccion = $("kpis");
    seccion.classList.add("cargando");
    return pedir("kpis", null, signal).then(function (d) {
      var a = d.actual, ant = d.anterior;
      setKpi("v-recibos", fmtN(a.recibos));
      setKpi("v-pdif", String(a.pct_con_diferencias).replace(".", ",") + " %");
      setKpi("v-monto", fmtM(a.monto_observado));
      setKpi("v-enviados", fmtN(a.enviados_sindicato));
      setKpi("v-tramites", fmtN(a.tramites));
      setKpi("v-tabiertos", fmtN(a.tramites_sin_resolver));
      setKpi("v-notif", fmtN(a.notif_enviadas));
      setKpi("v-lectura", a.tasa_lectura === null ? "—" : String(a.tasa_lectura).replace(".", ",") + " %");
      setKpi("v-padron", fmtN(a.padron_registrados) + " / " + fmtN(a.padron_total));
      $("d-padron").textContent = a.padron_total
        ? Math.round(a.padron_registrados / a.padron_total * 100) + "% del padrón" : "";
      if (CONSULTAS_ON) setKpi("v-bot", fmtN(a.consultas));
      var del = $("d-recibos");
      if (!ant.recibos) { del.className = "delta neu"; del.textContent = "s/d período anterior"; }
      else {
        var pct = (a.recibos - ant.recibos) / ant.recibos * 100;
        del.className = "delta " + (pct >= 0 ? "up" : "down");
        del.textContent = (pct >= 0 ? "▲ " : "▼ ") + Math.abs(pct).toFixed(0) + "% vs período anterior";
      }
      $("cnt-tramites").textContent = fmtN(a.tramites);
      if (CONSULTAS_ON && S.tab !== "consultas") $("cnt-consultas").textContent = fmtN(a.consultas || 0);
      $("rango-texto").textContent = fFecha(d.rango.desde) + " – " + fFecha(d.rango.hasta);
      seccion.classList.remove("cargando");
    }).catch(function (e) {
      if (e.name !== "AbortError") seccion.classList.remove("cargando");
    });
  }

  /* ================= Charts ================= */
  Chart.defaults.font.family = css.getPropertyValue("--fuente") || "system-ui, sans-serif";
  Chart.defaults.color = C.gris;
  Chart.defaults.font.size = 11;
  if (REDUCIR) Chart.defaults.animation = false;
  var CH = {};

  function crearCharts() {
    var ctx = $("ch-linea").getContext("2d");
    var grad = ctx.createLinearGradient(0, 0, 0, 220);
    grad.addColorStop(0, mezcla(C.primario, 0.25)); grad.addColorStop(1, "rgba(255,255,255,0)");
    CH.linea = new Chart(ctx, { type: "line",
      data: { labels: [], datasets: [{ data: [], borderColor: C.primario, backgroundColor: grad,
        fill: true, tension: 0.35, borderWidth: 2.5, pointRadius: 0, pointHitRadius: 12, pointHoverRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 9 } },
                  y: { beginAtZero: true, grid: { color: C.linea } } } } });

    CH.dona = new Chart($("ch-dona"), { type: "doughnut",
      data: { labels: ["Correctos", "Con diferencias"],
        datasets: [{ data: [0, 0], backgroundColor: [C.ok, C.error], borderWidth: 3, borderColor: "#fff", hoverOffset: 8 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "62%",
        onClick: function (e, el) {
          if (!el.length) return;
          var v = ["ok", "con_diferencias"][el[0].index];
          S.resultado = S.resultado === v ? "" : v;
          irATab("recibos"); cambio();
        },
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", padding: 14 } } } } });

    CH.tramites = new Chart($("ch-tramites"), { type: "bar",
      data: { labels: [], datasets: [
        { label: "Abiertos", data: [], backgroundColor: C.aviso, borderRadius: 4, maxBarThickness: 30 },
        { label: "En proceso", data: [], backgroundColor: C.apoyo, borderRadius: 4, maxBarThickness: 30 },
        { label: "Resueltos", data: [], backgroundColor: C.ok, borderRadius: 4, maxBarThickness: 30 }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
        onClick: function (e, el) {
          if (!el.length) return;
          var fila = CH.tramites.filasSecc[el[0].index];
          var est = ["abierto", "en_proceso", "resuelto"][el[0].datasetIndex];
          var mismaSecc = fila.seccional_id !== null && S.seccionales.has(fila.seccional_id);
          if (mismaSecc && S.estadoTramite === est) {
            S.seccionales.delete(fila.seccional_id); S.estadoTramite = "";
          } else {
            if (fila.seccional_id !== null) S.seccionales.add(fila.seccional_id);
            S.estadoTramite = est;
          }
          irATab("tramites"); cambio();
        },
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", padding: 12 },
          onClick: function (e, item) {
            var est = ["abierto", "en_proceso", "resuelto"][item.datasetIndex];
            S.estadoTramite = S.estadoTramite === est ? "" : est;
            irATab("tramites"); cambio();
          } } },
        scales: { x: { stacked: true, grid: { color: C.linea } }, y: { stacked: true, grid: { display: false } } } } });
    CH.tramites.filasSecc = [];

    CH.notif = new Chart($("ch-notif"), { type: "bar",
      data: { labels: [], datasets: [
        { label: "Leídas", data: [], backgroundColor: C.primario, borderRadius: 4, maxBarThickness: 22 },
        { label: "No leídas", data: [], backgroundColor: mezcla(C.primario, 0.35), borderRadius: 4, maxBarThickness: 22 }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
        onClick: function (e, el) {
          if (!el.length) return;
          var t = CH.notif.tipos[el[0].index];
          S.tipoNotif = S.tipoNotif === t ? "" : t;
          irATab("notificaciones"); cambio();
        },
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", padding: 12 } } },
        scales: { x: { stacked: true, grid: { color: C.linea } }, y: { stacked: true, grid: { display: false } } } } });
    CH.notif.tipos = [];

    CH.emp = new Chart($("ch-emp"), { type: "bar",
      data: { labels: [], datasets: [{ data: [], backgroundColor: C.error, borderRadius: 6, maxBarThickness: 26 }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
        onClick: function (e, el) {
          if (!el.length) return;
          var emp = CH.emp.filasEmp[el[0].index];
          if (!emp || emp.empresa_id === null) return;   // CUIT fuera del catálogo: no hay filtro posible
          if (S.empresas.has(emp.empresa_id)) S.empresas.delete(emp.empresa_id);
          else S.empresas.add(emp.empresa_id);
          irATab("recibos"); cambio();
        },
        plugins: { legend: { display: false },
          tooltip: { callbacks: { label: function (c) { return fmtM(c.raw); } } } },
        scales: { x: { grid: { color: C.linea },
            ticks: { callback: function (v) { return v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : "$" + Math.round(v / 1000) + "k"; } } },
          y: { grid: { display: false } } } } });
    CH.emp.filasEmp = [];

    if (CONSULTAS_ON) {
      CH.bot = new Chart($("ch-bot"), { type: "bar",
        data: { labels: [], datasets: [{ data: [], backgroundColor: C.primario, borderRadius: 6, maxBarThickness: 26 }] },
        options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
          onClick: function (e, el) {
            if (!el.length) return;
            var t = CH.bot.data.labels[el[0].index];
            S.tema = S.tema === t ? "" : t;
            irATab("consultas"); cambio();
          },
          plugins: { legend: { display: false } },
          scales: { x: { grid: { color: C.linea } }, y: { grid: { display: false } } } } });
    }

    CH.formato = new Chart($("ch-formato"), { type: "bar",
      data: { labels: [], datasets: [
        { label: "Formato anterior", data: [], backgroundColor: "#b9c0cc", borderRadius: 5, maxBarThickness: 30 },
        { label: "Nuevo (Ley 27.802)", data: [], backgroundColor: C.acento, borderRadius: 5, maxBarThickness: 30 }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "circle", padding: 14 } } },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: { color: C.linea } } } } });
  }

  function pintarLinea(d) {
    CH.linea.data.labels = d.serie.map(function (p) { return fCorta(p.dia); });
    CH.linea.data.datasets[0].data = d.serie.map(function (p) { return p.cantidad; });
    CH.linea.update();
  }

  function pintarDona(d) {
    CH.dona.data.datasets[0].data = [d.ok, d.con_diferencias];
    CH.dona.data.datasets[0].offset = ["ok", "con_diferencias"].map(function (v) { return S.resultado === v ? 14 : 0; });
    CH.dona.data.datasets[0].borderColor = ["ok", "con_diferencias"].map(function (v) { return S.resultado === v ? C.destacado : "#fff"; });
    CH.dona.data.datasets[0].backgroundColor = ["ok", "con_diferencias"].map(function (v, i) {
      var base = [C.ok, C.error][i];
      return (S.resultado && S.resultado !== v) ? mezcla(base, 0.3) : base;
    });
    CH.dona.update();
    $("cnt-recibos").textContent = fmtN(d.con_diferencias);
  }

  function pintarTramites(d) {
    var filas = d.seccionales;
    CH.tramites.filasSecc = filas;
    CH.tramites.data.labels = filas.map(function (f) { return f.seccional; });
    var estados = ["abierto", "en_proceso", "resuelto"];
    var bases = [C.aviso, C.apoyo, C.ok];
    var atenSecc = S.seccionales.size > 0, atenEst = !!S.estadoTramite;
    estados.forEach(function (est, i) {
      CH.tramites.data.datasets[i].data = filas.map(function (f) { return f[est]; });
      CH.tramites.data.datasets[i].backgroundColor = filas.map(function (f) {
        var apagado = (atenSecc && !(f.seccional_id !== null && S.seccionales.has(f.seccional_id)))
          || (atenEst && S.estadoTramite !== est);
        return apagado ? mezcla(bases[i], 0.28) : bases[i];
      });
      CH.tramites.data.datasets[i].borderColor = filas.map(function (f) {
        return (f.seccional_id !== null && S.seccionales.has(f.seccional_id)) ? C.destacado : "rgba(0,0,0,0)";
      });
      CH.tramites.data.datasets[i].borderWidth = 2;
    });
    CH.tramites.update();
  }

  function pintarNotif(d) {
    var tipos = d.por_tipo;
    CH.notif.tipos = tipos.map(function (t) { return t.tipo; });
    CH.notif.data.labels = tipos.map(function (t) { return t.etiqueta; });
    CH.notif.data.datasets[0].data = tipos.map(function (t) { return t.leidas; });
    CH.notif.data.datasets[1].data = tipos.map(function (t) { return t.sin_leer; });
    CH.notif.data.datasets[0].backgroundColor = tipos.map(function (t) {
      if (!S.tipoNotif) return C.primario;
      return t.tipo === S.tipoNotif ? C.destacado : mezcla(C.primario, 0.25);
    });
    CH.notif.data.datasets[1].backgroundColor = tipos.map(function (t) {
      var base = mezcla(C.primario, 0.35);
      return (S.tipoNotif && t.tipo !== S.tipoNotif) ? mezcla(C.primario, 0.12) : base;
    });
    CH.notif.update();
    $("notif-resumen").innerHTML =
      '<div class="notif-caja"><div class="n">' + fmtN(d.enviadas) + '</div><div class="t">Enviadas</div></div>' +
      '<div class="notif-caja"><div class="n" style="color:' + C.primario + '">' + fmtN(d.leidas) + '</div><div class="t">Leídas</div></div>' +
      '<div class="notif-caja"><div class="n" style="color:' + C.error + '">' + fmtN(d.sin_leer) + '</div><div class="t">Sin leer</div></div>';
  }

  function pintarEmpresas(d) {
    CH.emp.filasEmp = d.empresas;
    CH.emp.data.labels = d.empresas.map(function (e) { return e.nombre; });
    CH.emp.data.datasets[0].data = d.empresas.map(function (e) { return e.monto; });
    CH.emp.data.datasets[0].backgroundColor = d.empresas.map(function (e) {
      if (!S.empresas.size) return C.error;
      return (e.empresa_id !== null && S.empresas.has(e.empresa_id)) ? C.destacado : mezcla(C.error, 0.25);
    });
    CH.emp.update();
  }

  function pintarBot(d) {
    CH.bot.data.labels = d.temas.map(function (t) { return t.tema; });
    CH.bot.data.datasets[0].data = d.temas.map(function (t) { return t.cantidad; });
    CH.bot.data.datasets[0].backgroundColor = d.temas.map(function (t) {
      if (!S.tema) return C.primario;
      return t.tema === S.tema ? C.destacado : mezcla(C.primario, 0.25);
    });
    CH.bot.update();
  }

  function pintarFormato(d) {
    CH.formato.data.labels = d.semanas.map(function (s) { return fCorta(s.semana); });
    CH.formato.data.datasets[0].data = d.semanas.map(function (s) { return s.clasico; });
    CH.formato.data.datasets[1].data = d.semanas.map(function (s) { return s.nuevo; });
    CH.formato.update();
  }

  function pintarSemaforo(d) {
    var colores = { verde: C.ok, amarillo: C.aviso, rojo: C.error };
    var etiquetas = { verde: "al día", amarillo: "demoradas", rojo: "críticas" };
    $("sem-resumen").innerHTML = ["verde", "amarillo", "rojo"].map(function (k) {
      return '<span><i class="punto" style="background:' + colores[k] + '"></i>' + d.resumen[k] + " " + etiquetas[k] + "</span>";
    }).join("");
    $("sem-lista").innerHTML = d.empresas.map(function (e) {
      var estado = e.estado === "verde" ? "Al día" : (e.estado === "amarillo" ? "Demorado" : "Crítico");
      return '<div class="sem-item" style="--lc:' + colores[e.estado] + '">' +
        '<span class="luz"></span>' +
        '<div><div class="emp">' + esc(e.nombre) + '</div>' +
        '<div class="dep">Último depósito: ' + fFecha(e.ultimo_deposito) + " · " + estado + "</div></div>" +
        '<span class="dias">' + e.dias + " d</span></div>";
    }).join("") || '<div style="color:var(--gris);font-size:12.5px;padding:14px 0">Sin datos de depósitos para los filtros actuales.</div>';
  }

  /* ================= Explorador ================= */
  var TABLAS = {
    recibos: {
      sub: "Recibos con diferencias · ordenados por monto observado · identificados solo si el trabajador los envió",
      head: "<tr><th>Fecha</th><th>Seccional</th><th>Empresa</th><th>Categoría</th><th>Formato</th><th>Bruto</th><th>Dif. detectada</th><th>Enviado</th><th>Trabajador</th><th>CUIL</th><th></th></tr>",
      cols: 11, total: function (n) { return n + " recibos observados"; },
      fila: function (r) {
        return "<tr><td>" + fFecha(r.fecha) + "</td><td>" + esc(r.seccional) + "</td><td>" + esc(r.empresa) + "</td>" +
          "<td>" + esc(r.categoria) + "</td><td>" + (r.formato === "nuevo" ? "Ley 27.802" : (r.formato === "clasico" ? "Anterior" : "—")) + "</td>" +
          '<td class="monto">' + fmtM(r.bruto) + "</td>" +
          '<td class="monto" style="color:' + C.error + '">' + fmtM(r.diferencia) + "</td>" +
          "<td>" + (r.enviado ? "✓ Sí" : "—") + "</td>" +
          "<td>" + esc(r.trabajador_nombre || "Anónimo") + "</td><td class=\"monto\">" + esc(r.trabajador_cuil || "—") + "</td>" +
          '<td><button type="button" class="btn-ver" data-det="recibo" data-id="' + r.id + '">Ver</button></td></tr>';
      },
    },
    tramites: {
      sub: "Detalle de trámites del período · respetando seccional y estado seleccionados",
      head: "<tr><th>N°</th><th>Fecha inicio</th><th>Seccional</th><th>Tipo de trámite</th><th>Estado</th><th>Días</th><th></th></tr>",
      cols: 7, total: function (n) { return n + " trámites"; },
      fila: function (t) {
        var tags = { resuelto: ["ok", "Resuelto"], en_proceso: ["proc", "En proceso"], abierto: ["rev", "Abierto"] };
        var tg = tags[t.estado] || ["rev", t.estado];
        return '<tr><td class="monto">' + esc(t.numero) + "</td><td>" + fFecha(t.fecha_inicio) + "</td><td>" + esc(t.seccional) + "</td>" +
          "<td>" + esc(t.tipo) + '</td><td><span class="tag ' + tg[0] + '">' + tg[1] + "</span></td>" +
          '<td class="monto">' + (t.dias === null ? "—" : t.dias + " d" + (t.sigue ? " y sigue" : "")) + "</td>" +
          '<td><button type="button" class="btn-ver" data-det="tramite" data-id="' + t.id + '">Ver</button></td></tr>';
      },
    },
    consultas: {
      sub: "Consultas de los afiliados al asistente · el tema seleccionado en el gráfico filtra esta lista",
      head: "<tr><th>Fecha</th><th>Seccional</th><th>Tema consultado</th><th>Resolución</th><th></th></tr>",
      cols: 5, total: function (n) { return n + " consultas"; },
      fila: function (c) {
        return "<tr><td>" + fFecha(c.fecha) + "</td><td>" + esc(c.seccional) + "</td><td>" + esc(c.tema) + "</td>" +
          '<td><span class="tag ' + (c.resuelta_por_bot ? "ok" : "rev") + '">' +
          (c.resuelta_por_bot ? "Resuelta por el bot" : "Derivada") + "</span></td>" +
          '<td><button type="button" class="btn-ver" data-det="consulta" data-id="' + c.id + '">Ver</button></td></tr>';
      },
    },
    notificaciones: {
      sub: "Envíos diarios por seccional y tipo · el tipo seleccionado en el gráfico filtra esta lista",
      head: "<tr><th>Fecha</th><th>Seccional</th><th>Tipo</th><th>Enviadas</th><th>Leídas</th><th>Sin leer</th><th>Tasa de lectura</th><th></th></tr>",
      cols: 8, total: function (n) { return n + " filas (día × seccional × tipo)"; },
      fila: function (n) {
        return "<tr><td>" + fFecha(n.fecha) + "</td><td>" + esc(n.seccional) + "</td><td>" + esc(n.etiqueta) + "</td>" +
          '<td class="monto">' + fmtN(n.enviadas) + '</td><td class="monto">' + fmtN(n.leidas) + "</td>" +
          '<td class="monto">' + fmtN(n.sin_leer) + "</td>" +
          '<td><span class="barra-lectura"><i style="width:' + n.tasa_lectura + '%"></i></span><span class="monto">' + n.tasa_lectura + " %</span></td>" +
          '<td><button type="button" class="btn-ver" data-det="notif" data-dia="' + n.fecha + '" data-secc="' + (n.seccional_id || 0) + '" data-tipo="' + n.tipo + '">Ver</button></td></tr>';
      },
    },
  };
  var tablaEstado = { total: 0, mostrando: 0 };

  function pintarTabla(d, agregar) {
    var def = TABLAS[S.tab];
    $("tabla-head").innerHTML = def.head;
    var html = d.items.map(def.fila).join("");
    if (agregar) $("tabla-body").insertAdjacentHTML("beforeend", html);
    else $("tabla-body").innerHTML = html ||
      '<tr><td colspan="' + def.cols + '" class="vacio-exp">Sin registros para los filtros actuales. Probá ampliar el período o quitar filtros.</td></tr>';
    tablaEstado.total = d.total;
    tablaEstado.mostrando = (agregar ? tablaEstado.mostrando : 0) + d.items.length;
    $("tabla-total").textContent = "Mostrando " + fmtN(tablaEstado.mostrando) + " de " + fmtN(d.total) + " · " + def.total(fmtN(d.total));
    $("tabla-sub").textContent = def.sub;
    $("cnt-" + S.tab).textContent = fmtN(d.total);
    $("ver-mas").style.visibility = tablaEstado.mostrando < d.total ? "visible" : "hidden";
    document.querySelectorAll("#tabs-datos .tab-d").forEach(function (b) {
      b.classList.toggle("act", b.dataset.t === S.tab);
    });
  }

  function irATab(tab) {
    if (tabsDisponibles().indexOf(tab) < 0) return;
    S.tab = tab; S.paginas = 1;
  }

  function verMas() {
    S.paginas += 1;
    var p = panelDe("explorador");
    p.classList.add("cargando");
    pedir("explorador/" + S.tab, { page: S.paginas, page_size: 10 }, abortador ? abortador.signal : undefined)
      .then(function (d) { pintarTabla(d, true); p.classList.remove("cargando"); })
      .catch(function (e) {
        if (e.name === "AbortError") return;
        p.classList.remove("cargando"); p.classList.add("con-error");
      });
  }

  /* ================= Modal de detalle ("Ver") ================= */
  function abrirModal(html) {
    $("det-contenido").innerHTML = html;
    $("overlay-det").classList.add("abierto");
  }
  function cerrarModal() { $("overlay-det").classList.remove("abierto"); }

  function filaDet(k, v) {
    return '<div class="det-fila"><span class="k">' + esc(k) + '</span><span class="v">' + v + "</span></div>";
  }

  function htmlRecibo(d) {
    var h = "<h3>Recibo verificado</h3>" +
      '<div class="det-sub">' + fFecha(d.procesado_en) + " · período " + esc(d.periodo || "—") + "</div>";
    if (!d.enviado) {
      h += '<div class="det-anonimo">Recibo anonimizado: el trabajador no lo envió al sindicato, ' +
        "así que no se muestra ningún dato que lo identifique.</div>";
    }
    h += filaDet("Resultado", '<span class="tag ' + (d.estado === "ok" ? "ok" : "dif") + '">' +
      (d.estado === "ok" ? "Sin diferencias" : "Con diferencias") + "</span>");
    if (d.trabajador_nombre) h += filaDet("Trabajador", esc(d.trabajador_nombre) + " · CUIL " + esc(d.trabajador_cuil));
    h += filaDet("Empresa", esc(d.empresa)) + filaDet("Categoría", esc(d.categoria)) +
      filaDet("Formato", d.formato === "nuevo" ? "Ley 27.802 (Anexo III)" : "Anterior") +
      filaDet("Remuneración bruta", '<span class="monto">' + fmtM(d.bruto) + "</span>");
    var lineas = (d.recibo && d.recibo.lineas) || [];
    if (lineas.length) {
      h += '<div class="det-sec">Conceptos del recibo (' + lineas.length + ")</div>";
      lineas.forEach(function (l) {
        var imp = typeof l.importe === "number" ? l.importe : null;
        h += '<div class="det-linea"><span>' + esc(l.descripcion || l.codigo || "—") + "</span>" +
          '<span class="imp' + (imp !== null && imp < 0 ? " neg" : "") + '">' +
          (imp === null ? "—" : fmtM(imp)) + "</span></div>";
      });
    }
    var tot = (d.resultado && d.resultado.totales) || null;
    if (tot) {
      h += '<div class="det-sec">Totales</div>' +
        filaDet("Ingresos", '<span class="monto">' + fmtM(tot.ingresos) + "</span>") +
        filaDet("Descuentos", '<span class="monto">' + fmtM(tot.descuentos) + "</span>") +
        filaDet("Neto", '<span class="monto">' + fmtM(tot.neto) + "</span>");
    }
    var disc = (d.resultado && d.resultado.discrepancias) || [];
    if (disc.length) {
      h += '<div class="det-sec" style="color:' + C.error + '">Discrepancias detectadas (' + disc.length + ')</div><ul class="det-lista">';
      disc.forEach(function (x) { h += "<li>" + esc(x.detalle) + "</li>"; });
      h += "</ul>";
    }
    var alertas = (d.resultado && d.resultado.alertas) || [];
    if (alertas.length) {
      h += '<div class="det-sec" style="color:' + C.aviso + '">Alertas</div><ul class="det-lista">';
      alertas.forEach(function (x) { h += "<li>" + esc(x.detalle) + "</li>"; });
      h += "</ul>";
    }
    return h;
  }

  function htmlTramite(d) {
    var h = "<h3>" + esc(d.numero_expediente) + "</h3>" +
      '<div class="det-sub">' + esc(d.tipo_titulo) + "</div>" +
      filaDet("Estado", esc(d.estado_label)) +
      filaDet("Trabajador", esc(d.trabajador_nombre || "—") + " · CUIL " + esc(d.cuil)) +
      filaDet("Seccional", esc(d.seccional)) +
      filaDet("Iniciado", fFecha(d.creado)) +
      filaDet("Última actualización", fFecha(d.actualizado));
    if ((d.respuestas || []).length) {
      h += '<div class="det-sec">Formulario presentado</div>';
      d.respuestas.forEach(function (r) {
        h += filaDet(r.etiqueta, esc(r.valor_texto || (r.tiene_archivo ? "📎 " + (r.archivo_nombre || "archivo") : "—")));
      });
    }
    // Conversación con el MISMO aspecto que el hilo de /admin y el de la app
    // del trabajador (burbujas estilo WhatsApp), no una lista de notas.
    h += '<div class="det-sec">Conversación' +
      ((d.notas || []).length ? " (" + d.notas.length + ")" : "") + "</div>";
    if (!(d.notas || []).length) {
      h += '<div class="tram-chat-vacio">Todavía no hay mensajes en este trámite.</div>';
    } else {
      h += '<div class="tram-chat">';
      d.notas.forEach(function (n) {
        var propio = n.autor === "admin";
        h += '<div class="tram-chat-fila ' + (propio ? "propio" : "ajeno") + '">' +
          '<span class="tram-chat-avatar-fallback"><svg viewBox="0 0 24 24">' +
          (propio
            ? '<path d="M12 3l7 3v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6z"/><circle cx="12" cy="10" r="2.3"/>'
            : '<circle cx="12" cy="8" r="3.4"/><path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7"/>') +
          "</svg></span>" +
          '<div class="tram-chat-burbuja">' +
          '<div class="tram-chat-remitente">' + (propio ? "Sindicato" : "Afiliado") + "</div>" +
          '<div class="tram-chat-texto">' + esc(n.texto) + "</div>" +
          '<div class="tram-chat-meta">' +
          (n.tiene_adjunto ? "<span>📎 " + esc(n.adjunto_nombre || "adjunto") + "</span>" : "") +
          "<span>" + fFecha(n.creado) + " " + esc((n.creado || "").slice(11, 16)) + "</span>" +
          "</div></div></div>";
      });
      h += "</div>";
    }
    if ((d.log || []).length) {
      h += '<div class="det-sec">Historial</div><ul class="det-lista">';
      d.log.forEach(function (l) { h += "<li>" + fFecha(l.creado) + " — " + esc(l.detalle) + "</li>"; });
      h += "</ul>";
    }
    return h;
  }

  function htmlNotifs(d, dia) {
    var lista = d.notificaciones || [];
    var h = "<h3>Notificaciones del " + fFecha(dia) + "</h3>" +
      '<div class="det-sub">' + lista.length + " envío" + (lista.length === 1 ? "" : "s") + " en esta fila del explorador</div>";
    if (!lista.length) return h + '<div class="det-sub">Sin notificaciones.</div>';
    lista.forEach(function (n) {
      h += '<div class="det-nota admin" style="max-width:100%; margin-left:0">' +
        '<div class="quien">' + esc(n.remitente || "—") + " · " + esc(n.etiqueta) + " · " + fFecha(n.enviado_en) + "</div>" +
        '<div class="quien" style="text-transform:none">Destino: ' + esc(n.destino) + " · " +
        fmtN(n.total_leidas) + "/" + fmtN(n.total_enviadas) + " leídas en total" +
        (n.total_enviadas !== n.enviadas ? " (" + fmtN(n.leidas) + "/" + fmtN(n.enviadas) + " en esta seccional)" : "") + "</div>" +
        '<div style="margin:4px 0 6px">' + esc(n.texto) + "</div>" +
        (n.tiene_adjunto ? '<div class="quien" style="text-transform:none">📎 ' + esc(n.adjunto_nombre || "adjunto") + "</div>" : "") +
        '<button type="button" class="btn-ver" data-dest="' + n.id + '">Destinatarios (' + fmtN(n.total_enviadas) + ")</button>" +
        '<div class="det-destinatarios" id="dest-' + n.id + '"></div></div>';
    });
    return h;
  }

  function verDestinatarios(btn) {
    var nid = btn.dataset.dest;
    var cont = $("dest-" + nid);
    if (cont.dataset.cargado) {          // segundo click: mostrar/ocultar
      cont.style.display = cont.style.display === "none" ? "block" : "none";
      return;
    }
    btn.disabled = true;
    fetch("/admin/dashboard/detalle/notificacion/" + nid + "/destinatarios")
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (d) {
        var h = "";
        d.items.forEach(function (p) {
          h += '<div class="det-linea"><span>' + esc(p.nombre) + ' <span style="color:var(--gris)">· ' +
            esc(p.cuil) + " · " + esc(p.seccional) + "</span></span>" +
            '<span class="imp" style="color:' + (p.leida_en ? C.ok : C.gris) + '">' +
            (p.leida_en ? "✓ Leída " + fFecha(p.leida_en) : "Sin leer") + "</span></div>";
        });
        if (d.recortado) h += '<div class="det-sub" style="margin-top:6px">Mostrando ' +
          d.items.length + " de " + fmtN(d.total) + " destinatarios.</div>";
        cont.innerHTML = h || '<div class="det-sub">Sin destinatarios.</div>';
        cont.dataset.cargado = "1";
      })
      .catch(function () { cont.innerHTML = '<div class="det-sub">No se pudo cargar el listado.</div>'; })
      .finally(function () { btn.disabled = false; });
  }

  function htmlConsulta(d) {
    return "<h3>Consulta al asistente</h3>" +
      '<div class="det-sub">' + fFecha(d.fecha) + " · " + esc(d.seccional) + "</div>" +
      filaDet("Tema", esc(d.tema)) +
      filaDet("Resolución", '<span class="tag ' + (d.resuelta_por_bot ? "ok" : "rev") + '">' +
        (d.resuelta_por_bot ? "Resuelta por el bot" : "Derivada") + "</span>") +
      '<div class="det-sec">Pregunta</div><div style="font-size:13px">' + esc(d.pregunta || "—") + "</div>";
  }

  function verDetalle(btn) {
    var tipo = btn.dataset.det;
    var ruta, render;
    if (tipo === "recibo") { ruta = "detalle/recibo/" + btn.dataset.id; render = htmlRecibo; }
    else if (tipo === "tramite") { ruta = "detalle/tramite/" + btn.dataset.id; render = htmlTramite; }
    else if (tipo === "consulta") { ruta = "detalle/consulta/" + btn.dataset.id; render = htmlConsulta; }
    else {
      ruta = "detalle/notificaciones?dia=" + btn.dataset.dia + "&seccional_id=" + btn.dataset.secc +
        "&tipo=" + btn.dataset.tipo;
      render = function (d) { return htmlNotifs(d, btn.dataset.dia); };
    }
    btn.disabled = true;
    fetch("/admin/dashboard/" + ruta)
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (d) { abrirModal(render(d)); })
      .catch(function () { abrirModal("<h3>No se pudo cargar el detalle</h3><div class='det-sub'>Probá de nuevo en un momento.</div>"); })
      .finally(function () { btn.disabled = false; });
  }

  /* ================= Calendario pintable ================= */
  var MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  function pintarCalendario() {
    var y = calVista.getFullYear(), m = calVista.getMonth();
    $("cal-mes").textContent = MESES[m] + " " + y;
    var html = ["L", "M", "M", "J", "V", "S", "D"].map(function (d) { return '<span class="cal-dow">' + d + "</span>"; }).join("");
    var dow = (new Date(y, m, 1).getDay() + 6) % 7;
    var inicio = new Date(y, m, 1 - dow);
    for (var i = 0; i < 42; i++) {
      var f = new Date(inicio); f.setDate(inicio.getDate() + i);
      var futuro = f > HOY, fuera = f.getMonth() !== m;
      var esIni = f.getTime() === S.desde.getTime(), esFin = f.getTime() === S.hasta.getTime();
      var unSolo = S.desde.getTime() === S.hasta.getTime();
      var enR = f >= S.desde && f <= S.hasta && !unSolo;
      var cls = "cal-dia";
      if (fuera) cls += " fuera";
      if (f.getTime() === HOY.getTime()) cls += " hoyd";
      if (enR && !esIni && !esFin) cls += " rango";
      if (esIni) cls += " extremo " + (unSolo ? "solo" : "ini");
      if (esFin && !unSolo) cls += " extremo fin";
      html += '<button type="button" class="' + cls + '" data-f="' + fISO(f) + '"' + (futuro ? " disabled" : "") + ">" + f.getDate() + "</button>";
    }
    $("cal-grid").innerHTML = html;
    $("cal-grid").querySelectorAll(".cal-dia:not(:disabled)").forEach(function (b) {
      b.onclick = function () {
        var f = deISO(b.dataset.f);
        if (!calEligiendo) {
          S.desde = f; S.hasta = f; calEligiendo = true;
          $("cal-ayuda").innerHTML = "Ahora tocá el día <b>final</b>";
        } else {
          if (f < S.desde) { S.hasta = new Date(S.desde); S.desde = f; } else { S.hasta = f; }
          calEligiendo = false;
          $("cal-ayuda").innerHTML = "Tocá el día <b>inicial</b> y luego el <b>final</b>";
        }
        cambio();
      };
    });
  }

  /* ================= Controles y chips ================= */
  function presetActivo() {
    if (S.hasta.getTime() !== HOY.getTime()) return null;
    var dias = Math.round((S.hasta - S.desde) / 864e5) + 1;
    return { 1: "hoy", 7: "7", 30: "30", 90: "90" }[dias] || null;
  }

  function pintarMultiChips(idCont, items, set) {
    var cont = $(idCont);
    if (!cont.children.length) {
      // Chip "TODAS" explícito: el conjunto vacío YA significa "todas", pero
      // sin este chip el estado por defecto no se veía elegido (§ backlog).
      var todas = document.createElement("button");
      todas.type = "button"; todas.className = "m-chip"; todas.textContent = "TODAS";
      todas.dataset.todas = "1";
      todas.onclick = function () { set.clear(); cambio(); };
      cont.appendChild(todas);
      items.forEach(function (it) {
        var b = document.createElement("button");
        b.type = "button"; b.className = "m-chip"; b.textContent = it.nombre; b.dataset.id = it.id;
        b.onclick = function () {
          var id = +b.dataset.id;
          if (set.has(id)) set.delete(id); else set.add(id);
          cambio();
        };
        cont.appendChild(b);
      });
    }
    cont.querySelectorAll(".m-chip").forEach(function (b) {
      b.classList.toggle("act", b.dataset.todas ? set.size === 0 : set.has(+b.dataset.id));
    });
  }

  function pintarSlider() {
    if (LIM.min === null) return;
    var min = +$("sal-min").value, max = +$("sal-max").value;
    S.salMin = Math.min(min, max); S.salMax = Math.max(min, max);
    $("sal-min-l").textContent = fmtN(S.salMin); $("sal-max-l").textContent = fmtN(S.salMax);
    var pct = function (v) { return (v - LIM.min) / Math.max(1, LIM.max - LIM.min) * 100; };
    $("sal-relleno").style.left = pct(S.salMin) + "%";
    $("sal-relleno").style.width = (pct(S.salMax) - pct(S.salMin)) + "%";
    var activo = S.salMin > LIM.min || S.salMax < LIM.max;
    $("rango-sal").classList.toggle("act", activo);
    $("sal-vals").classList.toggle("act", activo);
  }

  function pintarControles() {
    var p = presetActivo();
    document.querySelectorAll("#presets button").forEach(function (b) { b.classList.toggle("act", b.dataset.p === p); });
    document.querySelectorAll("#f-formato button").forEach(function (b) { b.classList.toggle("act", b.dataset.v === S.formato); });
    pintarMultiChips("secc-chips", CATALOGO.seccionales, S.seccionales);
    pintarMultiChips("emp-chips", CATALOGO.empresas, S.empresas);
    if (LIM.min !== null) {
      $("sal-min").value = S.salMin === null ? LIM.min : S.salMin;
      $("sal-max").value = S.salMax === null ? LIM.max : S.salMax;
      pintarSlider();
    }
    pintarCalendario();
    pintarChips();
  }

  function nombreDe(lista, id) {
    for (var i = 0; i < lista.length; i++) if (lista[i].id === id) return lista[i].nombre;
    return "#" + id;
  }

  function pintarChips() {
    var chips = [];
    var agregar = function (txt, fn) { chips.push({ txt: txt, fn: fn }); };
    S.seccionales.forEach(function (id) {
      agregar("Seccional: " + nombreDe(CATALOGO.seccionales, id), function () { S.seccionales.delete(id); });
    });
    S.empresas.forEach(function (id) {
      agregar("Empresa: " + nombreDe(CATALOGO.empresas, id), function () { S.empresas.delete(id); });
    });
    if (S.formato) agregar("Formato: " + (S.formato === "nuevo" ? "Ley 27.802" : "Anterior"), function () { S.formato = ""; });
    if (S.resultado) agregar("Resultado: " + (S.resultado === "ok" ? "Correctos" : "Con diferencias"), function () { S.resultado = ""; });
    if (S.estadoTramite) {
      var et = { abierto: "Abiertos", en_proceso: "En proceso", resuelto: "Resueltos" }[S.estadoTramite];
      agregar("Trámites: " + et, function () { S.estadoTramite = ""; });
    }
    if (S.tipoNotif) agregar("Notif.: " + (S.tipoNotif === "manual" ? "Comunicaciones" : "Trámites"), function () { S.tipoNotif = ""; });
    if (S.tema) agregar("Tema: " + S.tema, function () { S.tema = ""; });
    if (LIM.min !== null && S.salMin !== null && (S.salMin > LIM.min || S.salMax < LIM.max)) {
      agregar("Bruto: $" + fmtN(S.salMin) + "k – $" + fmtN(S.salMax) + "k", function () { S.salMin = LIM.min; S.salMax = LIM.max; });
    }
    var cont = $("chips");
    cont.innerHTML = chips.map(function (c, i) {
      return '<span class="chipf">' + esc(c.txt) + '<button type="button" data-i="' + i + '" aria-label="Quitar filtro">✕</button></span>';
    }).join("");
    cont.querySelectorAll("button[data-i]").forEach(function (b) {
      b.onclick = function () { chips[+b.dataset.i].fn(); cambio(); };
    });
    var n = $("num-filtros");
    n.style.display = chips.length ? "grid" : "none";
    n.textContent = chips.length;
  }

  function setPreset(p) {
    S.hasta = new Date(HOY); S.desde = new Date(HOY);
    if (p !== "hoy") S.desde.setDate(S.desde.getDate() - (+p - 1));
    calVista = new Date(HOY.getFullYear(), HOY.getMonth(), 1);
    calEligiendo = false;
  }

  function reiniciar() {
    S.seccionales.clear(); S.empresas.clear();
    S.formato = ""; S.resultado = ""; S.estadoTramite = ""; S.tipoNotif = ""; S.tema = "";
    S.salMin = LIM.min; S.salMax = LIM.max;
    S.tab = "recibos"; S.paginas = 1;
    setPreset("hoy");
    refrescar();
  }

  /* ================= Asistente del Panel (docs/ASISTENTE_PANEL.md) ================= */
  var ASIST_HIST = [];          // últimos intercambios, en memoria (nunca localStorage)
  var asistOcupado = false;
  var NOMBRE_TAB = { recibos: "Recibos", tramites: "Trámites", notificaciones: "Notificaciones", consultas: "Consultas" };

  // El estado del panel como lo espera el servidor: las mismas claves que la
  // query string (bruto en pesos) más la pestaña.
  function estadoPlano() {
    var q = paramsDeEstado();
    return {
      desde: q.get("desde"), hasta: q.get("hasta"),
      seccionales: q.getAll("seccionales").map(Number),
      empresas: q.getAll("empresas").map(Number),
      formato: q.get("formato") || "", resultado: q.get("resultado") || "",
      estado_tramite: q.get("estado_tramite") || "", tipo_notif: q.get("tipo_notif") || "",
      sal_min: q.get("sal_min") ? +q.get("sal_min") : null,
      sal_max: q.get("sal_max") ? +q.get("sal_max") : null,
      tema: q.get("tema") || "", tab: S.tab,
    };
  }

  // Reemplaza TODO el estado por el que manda el servidor (o por una foto
  // previa, al "Volver"): mismo camino que al cargar desde la URL.
  function aplicarEstado(filtros) {
    var q = new URLSearchParams();
    Object.keys(filtros).forEach(function (k) {
      var v = filtros[k];
      if (v === null || v === undefined || v === "") return;
      if (Array.isArray(v)) v.forEach(function (x) { q.append(k, x); });
      else q.set(k, v);
    });
    S.seccionales.clear(); S.empresas.clear();
    S.formato = ""; S.resultado = ""; S.estadoTramite = ""; S.tipoNotif = ""; S.tema = "";
    S.salMin = LIM.min; S.salMax = LIM.max;
    S.tab = "recibos"; S.paginas = 1;
    calEligiendo = false;
    estadoDeParams(q);
    calVista = new Date(S.desde.getFullYear(), S.desde.getMonth(), 1);
  }

  function asistAbrir(abrir) {
    var a = $("asist");
    if (!a) return;
    a.classList.toggle("abierto", abrir);
    a.setAttribute("aria-hidden", abrir ? "false" : "true");
    $("btn-asist").setAttribute("aria-expanded", abrir ? "true" : "false");
    if (abrir) setTimeout(function () { $("asist-caja").focus(); }, 80);
  }

  function asistBurbuja(clase, texto) {
    var hilo = $("asist-hilo");
    var b = document.createElement("div");
    b.className = "burb " + clase;
    b.textContent = texto;
    hilo.appendChild(b);
    hilo.scrollTop = hilo.scrollHeight;
    return b;
  }

  function asistPensando() {
    var b = asistBurbuja("bot pensando", "");
    b.setAttribute("aria-label", "Pensando");
    for (var i = 0; i < 3; i++) b.appendChild(document.createElement("span"));
    return b;
  }

  function asistChipAplicado(burbuja, tab, previo) {
    var fila = document.createElement("div");
    fila.className = "aplicado";
    var chip = document.createElement("b");
    chip.textContent = "Filtros aplicados · " + (NOMBRE_TAB[tab] || tab);
    var btn = document.createElement("button");
    btn.type = "button"; btn.textContent = "Volver";
    btn.onclick = function () {
      btn.disabled = true; btn.textContent = "Restaurado";
      aplicarEstado(previo); refrescar();
    };
    fila.appendChild(chip); fila.appendChild(btn);
    burbuja.appendChild(fila);
    $("asist-hilo").scrollTop = $("asist-hilo").scrollHeight;
  }

  function asistAjustar(caja) {
    caja.style.height = "auto";
    caja.style.height = Math.min(caja.scrollHeight, 96) + "px";
  }

  function asistPreguntar() {
    var caja = $("asist-caja"), pregunta = caja.value.trim();
    if (!pregunta || asistOcupado) return;
    caja.value = ""; asistAjustar(caja);
    asistBurbuja("yo", pregunta);
    var pensando = asistPensando();
    asistOcupado = true; $("asist-enviar").disabled = true;
    var previo = estadoPlano();   // foto para "Volver"
    fetch("/admin/dashboard/asistente", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pregunta: pregunta, filtros: previo, historial: ASIST_HIST.slice(-4) }),
    })
      .then(function (r) {
        if (r.status === 403) { location.href = "/admin"; throw new Error("sesion"); }
        return r.json().then(function (d) { return { ok: r.ok, d: d }; });
      })
      .then(function (res) {
        pensando.remove();
        if (!res.ok) {
          var detalle = typeof res.d.detail === "string" ? res.d.detail : "No pude responder.";
          asistBurbuja("bot error", detalle + (res.d.codigo ? "  " + res.d.codigo : ""));
          return;
        }
        var b = asistBurbuja("bot", res.d.respuesta);
        ASIST_HIST.push({ pregunta: pregunta, respuesta: res.d.respuesta, filtros: res.d.filtros });
        if (res.d.aplicar && res.d.filtros) {
          aplicarEstado(res.d.filtros);
          asistChipAplicado(b, res.d.filtros.tab, previo);
          refrescar().then(function () {
            panelDe("explorador").scrollIntoView({ behavior: "smooth", block: "start" });
          });
        }
      })
      .catch(function (e) {
        if (e.message === "sesion") return;
        pensando.remove();
        asistBurbuja("bot error", "No pude conectarme con el servidor. Probá de nuevo.");
      })
      .then(function () { asistOcupado = false; $("asist-enviar").disabled = false; caja.focus(); });
  }

  // El saludo cita una seccional real del sindicato, para que el ejemplo
  // sea uno que de verdad funciona.
  function asistEjemplo() {
    var hola = $("asist-hola");
    if (!hola || !CATALOGO.seccionales.length) return;
    hola.textContent = "Hola. Decime qué querés ver y aplico los filtros del panel. Por ejemplo: «notificaciones sin leer de " +
      CATALOGO.seccionales[0].nombre + " este mes» o «recibos con diferencias del mes pasado».";
  }

  function initAsistente() {
    if (!ASISTENTE_ON || !$("asist")) return;   // sin API key el cajón no existe
    $("btn-asist").onclick = function () { asistAbrir(!$("asist").classList.contains("abierto")); };
    $("asist-cerrar").onclick = function () { asistAbrir(false); };
    $("asist-form").onsubmit = function (e) { e.preventDefault(); asistPreguntar(); };
    var caja = $("asist-caja");
    caja.oninput = function () { asistAjustar(caja); };
    caja.onkeydown = function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); asistPreguntar(); }
    };
  }

  /* ================= Init ================= */
  function initControles() {
    $("hoy-fecha").textContent = HOY.toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    document.querySelectorAll("#presets button").forEach(function (b) {
      b.onclick = function () { setPreset(b.dataset.p); cambio(); };
    });
    document.querySelectorAll("#f-formato button").forEach(function (b) {
      b.onclick = function () { S.formato = b.dataset.v; cambio(); };
    });
    $("cal-prev").onclick = function () { calVista.setMonth(calVista.getMonth() - 1); pintarCalendario(); };
    $("cal-next").onclick = function () { calVista.setMonth(calVista.getMonth() + 1); pintarCalendario(); };
    $("btn-reiniciar").onclick = reiniciar;
    $("ver-mas").onclick = verMas;
    document.querySelectorAll("#tabs-datos .tab-d").forEach(function (b) {
      b.onclick = function () {
        S.tab = b.dataset.t; S.paginas = 1;
        urlCompartible();
        var p = panelDe("explorador");
        p.classList.add("cargando"); p.classList.remove("con-error");
        pedir("explorador/" + S.tab, { page: 1, page_size: 10 })
          .then(function (d) { pintarTabla(d, false); p.classList.remove("cargando"); })
          .catch(function () { p.classList.remove("cargando"); p.classList.add("con-error"); });
      };
    });
    ["sal-min", "sal-max"].forEach(function (id) {
      var el = $(id);
      el.oninput = pintarSlider;
      el.onchange = cambio;
    });
    document.querySelectorAll("[data-reintentar]").forEach(function (b) {
      b.onclick = function () { refrescar(); };
    });
    // "Ver" es delegado: las filas se re-renderizan en cada refresco.
    $("tabla-body").addEventListener("click", function (e) {
      var btn = e.target.closest(".btn-ver");
      if (btn) verDetalle(btn);
    });
    $("det-cerrar").onclick = cerrarModal;
    $("overlay-det").addEventListener("click", function (e) {
      if (e.target === this) { cerrarModal(); return; }
      var btn = e.target.closest("[data-dest]");
      if (btn) verDestinatarios(btn);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { cerrarModal(); asistAbrir(false); }
    });
  }

  function initCatalogo() {
    return fetch("/admin/dashboard/filtros?desde=" + fISO(HOY) + "&hasta=" + fISO(HOY))
      .then(function (r) { if (!r.ok) throw new Error("filtros"); return r.json(); })
      .then(function (d) {
        CATALOGO.seccionales = d.seccionales;
        CATALOGO.empresas = d.empresas;
        if (d.bruto_min !== null && d.bruto_max !== null && d.bruto_max > d.bruto_min) {
          LIM.min = Math.floor(d.bruto_min / 50000) * 50;   // miles, redondeado a 50k
          LIM.max = Math.ceil(d.bruto_max / 50000) * 50;
          ["sal-min", "sal-max"].forEach(function (id) {
            $(id).min = LIM.min; $(id).max = LIM.max; $(id).step = 50;
          });
          if (S.salMin === null) { S.salMin = LIM.min; S.salMax = LIM.max; }
          else { S.salMin = Math.max(LIM.min, S.salMin); S.salMax = Math.min(LIM.max, S.salMax || LIM.max); }
        } else {
          document.querySelector(".slider-wrap").style.display = "none";
        }
      })
      .catch(function () { document.querySelector(".slider-wrap").style.display = "none"; });
  }

  estadoDeUrl();
  crearCharts();
  initControles();
  initAsistente();
  initCatalogo().then(function () { asistEjemplo(); return refrescar(); });
})();
