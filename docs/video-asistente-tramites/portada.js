/* Escena: la portada de Josefina en el celular (La Bancaria), recorrida despacio. */
const { chromium } = require('playwright');
const { Filmador } = require('./lib');
const BASE = 'https://mitrabajo-pruebas.onrender.com';
const OUT = __dirname + '/../frames/portada';
(async () => {
  const browser = await chromium.launch({ args: ['--lang=es-419', '--accept-lang=es-AR,es'] });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'es-AR', timezoneId: 'America/Argentina/Buenos_Aires' });
  const l = await ctx.newPage();
  await l.goto(BASE + '/ingresar', { waitUntil: 'networkidle' });
  await l.fill('input[name="cuil"]', '27999999994'); await l.fill('input[name="clave"]', '27999');
  await l.click('button[type="submit"]'); await l.waitForLoadState('networkidle'); await l.close();
  const page = await ctx.newPage();
  await page.clock.install({ time: new Date('2026-12-03T07:40:00-03:00') });
  await page.goto(BASE + '/app/inicio', { waitUntil: 'networkidle' });
  const film = new Filmador(page, OUT, { prefix: 'p', mobile: true });
  await film.preparar();
  await page.evaluate(() => { document.body.style.transform = ''; const s = document.getElementById('__film_style'); s.textContent = s.textContent.replace('html,body{overflow:hidden!important}', ''); });
  film.cam = null; film.cursor = undefined; film.t = 0;
  await page.clock.runFor(3000);
  film.marca('portada quieta');
  await film.hasta(4.0);
  // scroll suave hasta las novedades y vuelta
  const alto = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  const fin = 10.0, ini = film.t;
  while (film.t < fin) { const u = (film.t - ini) / (fin - ini); const k = u < .5 ? 4*u*u*u : 1 - Math.pow(-2*u+2,3)/2; await page.evaluate((y) => window.scrollTo(0, y), Math.round(Math.min(alto, 760) * k)); await film.cuadro(1); }
  film.marca('novedades');
  await film.hasta(12.0);
  // tocar Trámites en la barra de abajo (si está en la portada) o el acceso
  const hay = await page.evaluate(() => { const a = Array.from(document.querySelectorAll('a,button')).find((x) => /Tr[aá]mites/.test(x.textContent) && x.offsetParent); if (a) { a.scrollIntoView({ block: 'center' }); return true; } return false; });
  await page.clock.runFor(100);
  await film.hasta(13.0);
  film.marca('fin portada');
  await browser.close();
})().catch((e) => { console.error('ERROR', e); process.exit(1); });
