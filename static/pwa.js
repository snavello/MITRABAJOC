// Instalabilidad de la app del trabajador (PWA). Dos funciones separadas
// a proposito: registrarSW() corre en CUALQUIER pantalla de /app (portada
// y panel), pero el banner de instalacion (initBannerInstalar) SOLO se
// llama desde trabajador.html -- el trabajador ya vio la app funcionando
// antes de que se le ofrezca instalarla.

function registrarSW() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/app" }).catch(() => {});
  }
}

const PWA_CLAVE = "colm3na_pwa_instalar";
const PWA_TOPE_DESCARTES = 5;
const PWA_DIAS_ENTRE_AVISOS = 7;

function _pwaEstado() {
  try {
    return JSON.parse(localStorage.getItem(PWA_CLAVE)) || { descartes: 0, ultimoAviso: 0 };
  } catch (e) {
    return { descartes: 0, ultimoAviso: 0 };
  }
}

function _pwaGuardar(estado) {
  try { localStorage.setItem(PWA_CLAVE, JSON.stringify(estado)); } catch (e) {}
}

function _pwaYaInstalada() {
  return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
}

function _pwaEsMovil() {
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

function _pwaEsIOS() {
  return /iPhone|iPad|iPod/i.test(navigator.userAgent) && !window.MSStream;
}

function _pwaDescartar(estado) {
  estado.descartes += 1;
  estado.ultimoAviso = Date.now();
  _pwaGuardar(estado);
  const banner = document.getElementById("pwa-banner");
  if (banner) banner.remove();
}

function _pwaRenderBanner(onInstalar, textoBoton, textoAviso) {
  const estado = _pwaEstado();
  const div = document.createElement("div");
  div.id = "pwa-banner";
  div.setAttribute("role", "region");
  div.setAttribute("aria-label", "Instalar la app");
  div.style.cssText = "position:fixed; left:12px; right:12px; bottom:calc(76px + env(safe-area-inset-bottom)); z-index:400; " +
    "background:var(--tinta,#152238); color:#fff; border-radius:14px; padding:12px 14px; " +
    "box-shadow:0 6px 24px rgba(0,0,0,.28); display:flex; align-items:center; gap:12px; " +
    "font-family:system-ui,sans-serif; animation:pwaSubir .35s ease-out;";
  div.innerHTML =
    '<div style="flex:1; font-size:13px; line-height:1.4;">' + textoAviso +
    '<div style="opacity:.7; font-size:11.5px; margin-top:2px;">No pide ningún permiso especial.</div></div>' +
    '<button id="pwa-btn-instalar" style="flex-shrink:0; background:var(--marca-acento,#b23a2e); color:#fff; ' +
    'border:none; border-radius:10px; padding:9px 14px; font-size:13px; font-weight:600; cursor:pointer;">' + textoBoton + '</button>' +
    '<button id="pwa-btn-cerrar" aria-label="Cerrar" style="flex-shrink:0; background:none; border:none; ' +
    'color:#fff; opacity:.6; font-size:18px; line-height:1; cursor:pointer; padding:4px;">&times;</button>';

  const estilo = document.createElement("style");
  estilo.textContent = "@keyframes pwaSubir { from { transform:translateY(16px); opacity:0; } to { transform:translateY(0); opacity:1; } }";
  div.appendChild(estilo);
  document.body.appendChild(div);

  document.getElementById("pwa-btn-instalar").addEventListener("click", () => onInstalar(estado));
  document.getElementById("pwa-btn-cerrar").addEventListener("click", () => _pwaDescartar(estado));
}

function initBannerInstalar() {
  if (_pwaYaInstalada() || !_pwaEsMovil()) return;

  const estado = _pwaEstado();
  if (estado.descartes >= PWA_TOPE_DESCARTES) return;
  const diasPasados = (Date.now() - estado.ultimoAviso) / (1000 * 60 * 60 * 24);
  if (estado.ultimoAviso && diasPasados < PWA_DIAS_ENTRE_AVISOS) return;

  if (_pwaEsIOS()) {
    setTimeout(() => {
      _pwaRenderBanner(
        (est) => _pwaDescartar(est),
        "Entendido",
        'Instalá Colm3na: tocá <strong>Compartir</strong> (el ícono de la flecha hacia arriba) y elegí <strong>"Agregar a inicio"</strong>.'
      );
    }, 1500);
    return;
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    setTimeout(() => {
      _pwaRenderBanner(
        async (est) => {
          const banner = document.getElementById("pwa-banner");
          if (banner) banner.remove();
          e.prompt();
          const resultado = await e.userChoice;
          if (resultado.outcome !== "accepted") _pwaDescartar(est);
        },
        "Instalar",
        "Instalá Colm3na en tu celular para acceder más rápido, como cualquier otra app."
      );
    }, 1500);
  });
}
