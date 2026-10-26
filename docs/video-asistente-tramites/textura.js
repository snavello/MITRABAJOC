/* Renderiza el diagrama del circuito (volcado por asistente2.js) a 3x, para el vuelo 3D. */
const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
const R = path.resolve(__dirname, '..');
(async () => {
  const d = JSON.parse(fs.readFileSync(path.join(R, 'frames/diagrama.json'), 'utf8'));
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8">${d.css.map((h) => `<link rel="stylesheet" href="${h}">`).join('')}
  <style>html,body{margin:0;background:transparent} body{padding:0} .diagrama{display:inline-block} .lienzo{display:inline-block;padding:28px 34px;background:#0e1830;border-radius:18px}</style></head>
  <body><div class="lienzo">${d.html}</div></body></html>`;
  fs.writeFileSync(path.join(R, 'frames/diagrama.html'), html);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 3 });
  const page = await ctx.newPage();
  await page.goto('file://' + path.join(R, 'frames/diagrama.html'), { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(800);
  const el = await page.$('.lienzo'); const box = await el.boundingBox(); console.log('lienzo', box);
  await el.screenshot({ path: path.join(R, 'frames/diagrama.png'), omitBackground: true });
  fs.writeFileSync(path.join(R, 'frames/diagrama_box.json'), JSON.stringify(box));
  await browser.close();
})().catch((e) => { console.error('ERROR', e); process.exit(1); });
