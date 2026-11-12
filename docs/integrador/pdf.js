// Lo usa armar.py --pdf: imprime el HTML en A4 y saca la miniatura de la portada.
const { chromium } = require('playwright');
(async () => {
  const [html, pdf, jpg] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 980, height: 620 } });
  await p.goto('file://' + html, { waitUntil: 'load' });
  await p.waitForTimeout(600);
  await p.locator('.portada').screenshot({ path: jpg, type: 'jpeg', quality: 82 });
  await p.pdf({ path: pdf, format: 'A4', printBackground: true, preferCSSPageSize: true });
  await b.close();
})();
