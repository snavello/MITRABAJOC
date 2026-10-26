const { chromium } = require('playwright');
const { Filmador } = require('./lib');
const modo = process.argv[2] || 'apertura';
const OUT = __dirname + '/../frames/' + modo;
const T0 = parseFloat(process.env.T0 || '0'); const DUR = parseFloat(process.env.DUR || '2.4');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await ctx.newPage();
  await page.clock.install({ time: new Date('2026-10-26T10:30:00-03:00') });
  await page.goto('file://' + __dirname + '/../intro/intro.html' + (modo === 'cierre' ? '?modo=cierre' : ''), { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  const film = new Filmador(page, OUT, { prefix: modo[0] });
  await film.preparar();
  film.cam = null; film.cursor = undefined; film.t = T0;
  await film.hasta(T0 + DUR);
  console.log(modo, film.n, 'cuadros');
  await browser.close();
})().catch((e) => { console.error('ERROR', e); process.exit(1); });
