const { chromium } = require('playwright');
(async () => {
  const [,, archivo, salida, sel] = process.argv;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 400, height: 800 }, deviceScaleFactor: 1 });
  await p.goto('file://' + archivo); await p.addStyleTag({content: '.cab{display:none}'}); await p.waitForFunction(() => [...document.images].every(i => i.complete), null, {timeout: 20000}).catch(() => {}); await p.evaluate(() => Promise.all([...document.images].map(i => i.decode().catch(() => {})))); await p.evaluate(() => document.fonts.ready); await p.evaluate(() => document.querySelectorAll('.m').forEach(m => m.classList.add('en-vista'))); await p.waitForTimeout(+(process.env.ESPERA || 800));
  const ids = await p.$$eval('.est', es => es.map(e => e.id));
  for (const id of ids) { if (sel && !sel.split(',').includes(id)) continue;
    const el = await p.$(`#${id} .m`);
    await p.evaluate(id => { const m = document.querySelector('#' + id + ' .m'); m.style.transform = 'none'; m.parentElement.style.width = '360px'; m.parentElement.style.height = '740px'; }, id);
    await el.screenshot({ path: `${salida}/${id}.png` }); }
  await b.close();
})();
