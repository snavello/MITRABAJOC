// Revisa los diagramas SVG de una parte del documento integrador contra
// DIAGRAMAS.md y saca una imagen de cada uno.
//   node docs/integrador/revisar_diagramas.js docs/integrador/partes/05a-recibos.html [carpeta_png]
// Problemas que detecta: texto que se sale de la caja que lo contiene,
// textos encimados, texto fuera del lienzo, letra de menos de 11 px y
// colores fuera de la paleta. Sale con código 1 si encuentra alguno.
const fs = require('fs');
const path = require('path');
const os = require('os');
const { chromium } = require('playwright');

const PALETA = new Set(['#ffffff', '#fff', '#b8c3d1', '#fff8ec', '#e0951a', '#0a1421', '#aeb9c8', '#eef2f6',
  '#5b6778', '#7a8799', '#f8fafc', '#0d7a5f', '#c0392b', '#b8860b', 'none', 'currentcolor',
  '#e8f5f0', '#fbeceb', '#fbf4e0']);

(async () => {
  const parte = process.argv[2];
  if (!parte) { console.error('uso: node revisar_diagramas.js <parte.html> [carpeta_png]'); process.exit(2); }
  const salida = process.argv[3] || '/tmp/claude-0/-home-user-MITRABAJOC/164c3e45-fe4e-5e22-9d1c-3e1986620d33/scratchpad/diagramas';
  fs.mkdirSync(salida, { recursive: true });
  const css = fs.readFileSync(path.join(__dirname, 'estilo.css'), 'utf8');
  const fuentes = ['barlow-condensed-bold.woff2', 'manrope.woff2'].map(f =>
    `@font-face{font-family:'${f.startsWith('barlow') ? 'Barlow Condensed' : 'Manrope'}';src:url(data:font/woff2;base64,${fs.readFileSync(path.join(__dirname, 'recursos', f)).toString('base64')}) format('woff2');font-weight:200 800}`).join('\n');
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>${fuentes}${css}</style></head><body><main class="doc"><div class="cuerpo">${fs.readFileSync(parte, 'utf8')}</div></main></body></html>`;
  const tmp = path.join(os.tmpdir(), `revisar-${process.pid}.html`);
  fs.writeFileSync(tmp, html);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1100, height: 900 } });
  await p.goto('file://' + tmp);
  await p.evaluate(() => document.fonts.ready);
  const resultado = await p.evaluate((paleta) => {
    const PAL = new Set(paleta);
    const norm = c => (c || '').trim().toLowerCase();
    const figs = [...document.querySelectorAll('figure.fig.diagrama')];
    return figs.map((fig, i) => {
      const svg = fig.querySelector('svg');
      const probs = [];
      if (!svg) return { i, probs: ['sin <svg>'] };
      const vb = svg.viewBox.baseVal;
      const textos = [...svg.querySelectorAll('text')].filter(t => t.textContent.trim());
      const cajas = [...svg.querySelectorAll('rect')].map(r => r.getBBox()).filter(r => r.width > 0 && r.height > 0);
      const bb = textos.map(t => ({ t, r: t.getBBox(), s: t.textContent.trim().slice(0, 40) }));
      for (const { t, r, s } of bb) {
        const fsz = parseFloat(getComputedStyle(t).fontSize);
        if (fsz < 10.9) probs.push(`letra chica (${fsz}px): «${s}»`);
        if (r.x < vb.x - 1 || r.y < vb.y - 1 || r.x + r.width > vb.x + vb.width + 1 || r.y + r.height > vb.y + vb.height + 1)
          probs.push(`fuera del lienzo: «${s}»`);
        const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
        const contiene = cajas.filter(c => cx > c.x && cx < c.x + c.width && cy > c.y && cy < c.y + c.height)
          .sort((a, b2) => a.width * a.height - b2.width * b2.height)[0];
        if (contiene && (r.x < contiene.x + 3 || r.x + r.width > contiene.x + contiene.width - 3))
          probs.push(`se sale de su caja: «${s}»`);
      }
      for (let a = 0; a < bb.length; a++) for (let c = a + 1; c < bb.length; c++) {
        const A = bb[a].r, B = bb[c].r;
        const ix = Math.min(A.x + A.width, B.x + B.width) - Math.max(A.x, B.x);
        const iy = Math.min(A.y + A.height, B.y + B.height) - Math.max(A.y, B.y);
        if (ix > 2 && iy > 3) probs.push(`textos encimados: «${bb[a].s}» / «${bb[c].s}»`);
      }
      const colores = new Set();
      svg.querySelectorAll('*').forEach(el => ['fill', 'stroke'].forEach(at => {
        const v = norm(el.getAttribute(at)); if (v && !v.startsWith('url(') && !PAL.has(v)) colores.add(v);
      }));
      if (colores.size) probs.push(`colores fuera de la paleta: ${[...colores].join(', ')}`);
      const pie = (fig.querySelector('figcaption') || {}).textContent || '';
      return { i, pie: pie.trim().slice(0, 70), probs };
    });
  }, [...PALETA]);
  const figs = await p.locator('figure.fig.diagrama').all();
  const base = path.basename(parte, '.html');
  for (let i = 0; i < figs.length; i++) await figs[i].screenshot({ path: path.join(salida, `${base}-${String(i + 1).padStart(2, '0')}.png`) });
  await b.close();
  fs.unlinkSync(tmp);
  let total = 0;
  for (const r of resultado) {
    console.log(`\n[${String(r.i + 1).padStart(2, '0')}] ${r.pie}`);
    if (!r.probs.length) console.log('    ok');
    r.probs.forEach(x => console.log('    - ' + x));
    total += r.probs.length;
  }
  console.log(`\n${resultado.length} diagramas, ${total} problemas. Imágenes en ${salida}/${base}-NN.png`);
  process.exit(total ? 1 : 0);
})();
