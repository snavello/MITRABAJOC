/* Escena: la bandeja de Trámites del panel de La Bancaria con el pedido de Josefina. */
const { chromium } = require('playwright');
const { Filmador } = require('./lib');
const BASE = 'https://mitrabajo-pruebas.onrender.com';
const OUT = __dirname + '/../frames/bandeja';
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'es-AR', timezoneId: 'America/Argentina/Buenos_Aires' });
  const l = await ctx.newPage();
  await l.goto(BASE + '/admin', { waitUntil: 'networkidle' });
  await l.fill('input[name="usuario"]', '20333444551'); await l.fill('input[name="clave"]', 'bancaria-demo');
  await l.click('button[type="submit"]'); await l.waitForLoadState('networkidle'); await l.close();
  const page = await ctx.newPage();
  await page.clock.install({ time: new Date('2026-12-03T08:05:00-03:00') });
  await page.goto(BASE + '/admin#tramites', { waitUntil: 'networkidle' });
  const film = new Filmador(page, OUT, { prefix: 'b' });
  await film.preparar();
  await page.clock.runFor(2500);
  await film.esperar(() => Array.from(document.querySelectorAll('tr')).some((tr) => /LABAKIT-2026-\d+/.test(tr.textContent)), { timeout: 30000 });
  // la fila de Josefina más nueva
  const fila = await page.evaluate(() => { const trs = Array.from(document.querySelectorAll('tr')).filter((tr) => /LABAKIT-2026-\d+/.test(tr.textContent) && /Josefina/.test(tr.textContent)); trs.sort((x, y) => x.textContent.localeCompare(y.textContent)); const tr = trs[trs.length - 1]; window.__n = trs.length; if (!tr) return null; tr.scrollIntoView({ block: 'center' }); tr.style.outline = '3px solid #ffb020'; tr.style.outlineOffset = '-3px'; tr.style.background = 'rgba(255,176,32,.14)'; return tr.textContent.replace(/\s+/g, ' ').trim(); });
  console.log('  fila:', fila, 'de', await page.evaluate(() => window.__n));
  await page.evaluate(() => window.scrollTo(0, 0));
  const pagina = await film.rect('.cont, .wrap, main').catch(() => ({ x: 0, w: 1920, cx: 960, y: 0 }));
  film.limites = { l: pagina.x - 30, r: pagina.x + pagina.w + 30 };
  const r = await film.rect('tr[style*="outline"]');
  film.camSet({ x: r.cx, y: r.cy - 160, z: 1.15 }); film.cursor = undefined;
  film.t = 0;
  film.camTo({ x: r.cx, y: r.cy, z: 1.6 }, 5.0);
  await film.hasta(6.0);
  film.marca('fin bandeja');
  await browser.close();
})().catch((e) => { console.error('ERROR', e); process.exit(1); });
