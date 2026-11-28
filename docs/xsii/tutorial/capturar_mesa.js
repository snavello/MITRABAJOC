/* Filma el tutorial de XSII contra un servidor LOCAL con la demo cargada.
   Uso (desde la raíz del repo, con DATABASE_URL del .env):
     NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node docs/xsii/tutorial/capturar_mesa.js
   Deja los JPEG en docs/xsii/tutorial/capturas/. Ejecuta las acciones de verdad
   (decisiones, insumos) y por eso arranca llamando a preparar_mesa.py (que usa preparar.py y suma
   los hitos de la Mesa y un usuario del sindicato). Filma SOLO el bloque 5 (capturas 57 en adelante). */
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const path = require('path');
const RAIZ = path.resolve(__dirname, '..', '..', '..');
const OUT = path.join(__dirname, 'capturas');
const BASE = process.env.XSII_URL || 'http://localhost:8765';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ORANGE = '#e8590c';

const cfg = JSON.parse(execSync(`${RAIZ}/.venv/bin/python ${__dirname}/preparar_mesa.py`, { cwd: RAIZ }).toString().trim().split('\n').pop());
const PID = cfg.pid;
const sql = q => execSync(`psql "$DATABASE_URL" -c "${q}"`, { cwd: RAIZ, stdio: 'pipe' });

async function marcar(page, marcas) {
  return page.evaluate(([marcas, color]) => {
    const rects = [];
    const quitar = [];
    marcas.forEach(m => {
      let el = null;
      if (m.css) el = document.querySelector(m.css);
      else if (m.h3) el = [...document.querySelectorAll('h3')].find(x => x.textContent.includes(m.h3));
      if (el && m.h3) el = el.closest('.bloque') || el.parentElement;
      if (m.btn) el = [...document.querySelectorAll('button,a')].find(x => x.textContent.trim() === m.btn);
      if (m.txt) el = [...document.querySelectorAll(m.en || '*')].filter(x => x.children.length === 0 && x.textContent.includes(m.txt))[0];
      if (!el) return;
      const r = el.getBoundingClientRect();
      const ox = el.style.outline, oo = el.style.outlineOffset;
      el.style.outline = '3px solid ' + color; el.style.outlineOffset = '2px';
      quitar.push(() => { el.style.outline = ox; el.style.outlineOffset = oo; });
      const c = document.createElement('div');
      c.className = 'tut-marca';
      c.textContent = m.n;
      c.style.cssText = `position:absolute;z-index:99999;width:26px;height:26px;border-radius:50%;background:${color};color:#fff;font:700 15px/26px system-ui,sans-serif;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.35);left:${r.left + scrollX - 13 + (m.dx || 0)}px;top:${r.top + scrollY - 13 + (m.dy || 0)}px;pointer-events:none`;
      document.body.appendChild(c);
      quitar.push(() => c.remove());
    });
    window.__quitarMarcas = () => quitar.forEach(f => f());
    return true;
  }, [marcas, ORANGE]);
}

// Abre un bloque plegado de la ficha (details.pleg) por el texto de su h3, si está cerrado.
async function abrirBloque(page, titulo) {
  await page.evaluate(t => {
    const h = [...document.querySelectorAll('details.pleg h3')].find(x => x.textContent.includes(t));
    if (!h) throw new Error('no hay bloque plegado: ' + t);
    const d = h.closest('details');
    if (!d.open) d.querySelector('summary').click();
  }, titulo);
  await sleep(400);
}

async function foto(page, nombre, { sel, marcas = [], pad = 18, maxAlto = 0, clipH3 = '' } = {}) {
  await sleep(700);
  if (clipH3) {
    await page.evaluate(t => { const h = [...document.querySelectorAll('h3')].find(x => x.textContent.includes(t)); (h.closest('.bloque') || h.parentElement).setAttribute('data-tut-clip', '1'); }, clipH3);
    sel = '[data-tut-clip]';
  }
  await marcar(page, marcas);
  const caja = await page.evaluate(([sel, pad]) => {
    const el = sel ? document.querySelector(sel) : document.body;
    const r = el.getBoundingClientRect();
    const x = Math.max(0, r.left + scrollX - pad), y = Math.max(0, r.top + scrollY - pad);
    return { x, y, width: Math.min(r.width + pad * 2, document.documentElement.scrollWidth - x), height: r.height + pad * 2 };
  }, [sel, pad]);
  if (maxAlto && caja.height > maxAlto) caja.height = maxAlto;
  await page.screenshot({ path: `${OUT}/${nombre}.jpg`, type: 'jpeg', quality: 80, fullPage: true, clip: caja });
  await page.evaluate(() => { window.__quitarMarcas && window.__quitarMarcas(); const c = document.querySelector('[data-tut-clip]'); if (c) c.removeAttribute('data-tut-clip'); });
  console.log('captura', nombre);
}

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  await ctx.addCookies([{ name: cfg.cookie_name, value: cfg.cookie, url: BASE }]);
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => errs.push('pageerror ' + e.message));
  const ir = async (q) => { await page.goto(`${BASE}/entornos/xsii/${PID}${q || ''}`); await sleep(1300); };
  const form = async () => { await page.click('form.form button[type=submit]'); await sleep(900); };
  const PLANILLA = path.join(__dirname, 'seccionales-tutorial.csv');

  // A. Se pide la lista de seccionales y el sindicato la sube a la tarjeta de la Mesa
  await ir('?tarea=EST-01');
  await page.click('button:has-text("Marcar pedido")'); await sleep(300);
  await page.fill('#x-ins-tarjeta', cfg.tarjetas[0]);
  await page.fill('#x-ins-nota', 'Se lo pedimos a Marcela, de Afiliaciones.');
  await form(); await sleep(500);
  execSync(`${RAIZ}/.venv/bin/python ${__dirname}/preparar_mesa.py subir ${PID} ${cfg.tarjetas[0]} ${PLANILLA}`, { cwd: RAIZ });
  await ir();
  await foto(page, '57-mesa-guia-llego', { sel: '.heroe', pad: 14, marcas: [{ css: '.llego', n: 1 }] });
  await ir('?tarea=EST-01');
  await foto(page, '58-mesa-ficha-archivos', { sel: '.espera', pad: 10, marcas: [{ css: '.llego', n: 1 }, { btn: 'Usar este archivo', n: 2 }] });
  await page.click('button:has-text("Usar este archivo")'); await sleep(1300);
  await foto(page, '59-mesa-en-uso', { sel: '.espera', pad: 10, marcas: [{ css: '.pil.hecha', n: 1 }] });
  await page.click('button:has-text("Cargar desde la planilla")'); await sleep(1000);
  // Para que entre en una figura se esconde (solo en la captura) lo que está entre el aviso de la Mesa y los botones: la tabla de columnas y las opciones.
  await page.evaluate(() => { const p = document.querySelector('.as-mesa').parentElement; [...p.children].forEach(c => { if (c.matches('.as-mesa, .as-bot, .as-pasos') || c.querySelector('.as-mesa, .as-bot, .as-pasos') || c.contains(document.querySelector('.as-mesa'))) return; if (c.tagName === 'DIV' && c.textContent.includes('Obligatoria') || c.classList.contains('as-opc') || c.querySelector('table')) c.style.display = 'none'; }); });
  await foto(page, '60-mesa-usar-archivo', { sel: '#x-as', pad: 14, maxAlto: 1500, marcas: [{ css: '.as-mesa', n: 1 }, { css: '#x-as-ensayar', n: 2 }, { css: '#x-as-cerrar', n: 3 }] });
  await page.click('#x-as-cerrar'); await sleep(800);
  await ir('?tarea=REC-01');
  await page.click('button:has-text("Marcar recibido")'); await sleep(1100);
  await page.click('button.btn.p:text-is("Confirmar")'); await sleep(1100);

  // B. Los hitos de la Mesa
  await ir('?vista=hitos');
  await foto(page, '62-hitos-vista', { sel: '.hitos', pad: 22, maxAlto: 900, marcas: [{ css: '.hit-k', n: 1, dx: -8 }, { css: '#x-h-todas', n: 2 }, { css: 'details.hit-f', n: 3 }] });
  await page.click('#x-h-todas'); await sleep(1500);
  await foto(page, '63-hitos-para-marcar', { sel: '.hit-prop', pad: 14, marcas: [{ css: '.hit-prop h3', n: 1, dx: -8 }, { css: '.hito.propuesto .pil', n: 2 }, { css: '.hito.propuesto .hito-p', n: 3, dx: -8 }, { css: '.hito.propuesto .btn.p', n: 4 }] });
  await page.click('#x-h-m-' + await page.evaluate(() => document.querySelector('.hit-prop .hito').dataset.hito)); await sleep(700);
  await foto(page, '64-hitos-segundo-toque', { sel: '.hit-prop .hito', pad: 14, marcas: [{ css: '.hit-prop .hito .btn.p', n: 1 }] });
  await page.click('.hit-prop .hito .btn.p'); await sleep(1800);
  await foto(page, '65-hitos-hecho', { sel: '.hitos', pad: 22, maxAlto: 760, marcas: [{ css: '.aviso.exito', n: 1 }, { css: '.hit-k', n: 2, dx: -8 }, { css: '.hit-prop', n: 3 }] });
  console.log('errores de consola:', JSON.stringify(errs));
  await b.close();
})().catch(e => { console.error('FALLO', e); process.exit(1); });
