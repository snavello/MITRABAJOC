/* Filma el tutorial «XSII para implementar La Bancaria» contra un servidor LOCAL con una base DESCARTABLE.
   Uso (desde la raíz del repo; ver LEEME.md para armar la base y el servidor):
     NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
       DATABASE_URL=... XSII_URL=http://localhost:8766 node docs/xsii/tutorial-bancaria/capturar.js
   Deja los JPEG en docs/xsii/tutorial-bancaria/img/. Ejecuta las acciones de verdad (carga seccionales, padrón y
   conceptos) y por eso arranca llamando a preparar.py. Ancho 1280, escala 1, JPEG ~70. */
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const path = require('path');
const RAIZ = path.resolve(__dirname, '..', '..', '..');
const OUT = path.join(__dirname, 'img');
const BASE = process.env.XSII_URL || 'http://localhost:8766';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ORANGE = '#e8590c';
const PY = `${RAIZ}/.venv/bin/python`;

const cfg = JSON.parse(execSync(`${PY} ${__dirname}/preparar.py`, { cwd: RAIZ }).toString().trim().split('\n').pop());
const PID = cfg.pid;
const sqlq = q => execSync(`psql "$DATABASE_URL" -tAc "${q}"`, { cwd: RAIZ }).toString().trim();

async function marcar(page, marcas) {
  return page.evaluate(([marcas, color]) => {
    const quitar = [];
    marcas.forEach(m => {
      let el = null;
      if (m.css) el = document.querySelector(m.css);
      else if (m.h3) el = [...document.querySelectorAll('h3')].find(x => x.textContent.includes(m.h3));
      if (el && m.h3) el = el.closest('.bloque') || el.parentElement;
      if (m.aviso) el = [...document.querySelectorAll('.aviso')].find(x => x.textContent.includes(m.aviso));
      if (m.btn) el = [...document.querySelectorAll('button,a')].find(x => x.textContent.trim() === m.btn);
      if (m.txt) el = [...document.querySelectorAll(m.en || '*')].filter(x => x.children.length === 0 && x.textContent.includes(m.txt))[0];
      if (!el) { console.warn('SIN MARCA', JSON.stringify(m)); return; }
      const r = el.getBoundingClientRect();
      const ox = el.style.outline, oo = el.style.outlineOffset;
      el.style.outline = '3px solid ' + color; el.style.outlineOffset = '2px';
      quitar.push(() => { el.style.outline = ox; el.style.outlineOffset = oo; });
      const c = document.createElement('div');
      c.textContent = m.n;
      c.style.cssText = `position:absolute;z-index:99999;width:26px;height:26px;border-radius:50%;background:${color};color:#fff;font:700 15px/26px system-ui,sans-serif;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.35);left:${r.left + scrollX - 20 + (m.dx || 0)}px;top:${r.top + scrollY - 20 + (m.dy || 0)}px;pointer-events:none`;
      document.body.appendChild(c);
      quitar.push(() => c.remove());
    });
    window.__quitarMarcas = () => quitar.forEach(f => f());
    return true;
  }, [marcas, ORANGE]);
}

async function abrirBloque(page, titulo) {
  await page.evaluate(t => {
    const h = [...document.querySelectorAll('details.pleg h3')].find(x => x.textContent.includes(t));
    if (!h) throw new Error('no hay bloque plegado: ' + t);
    const d = h.closest('details');
    if (!d.open) d.querySelector('summary').click();
  }, titulo);
  await sleep(400);
}

const avisos = [];
async function foto(page, nombre, { sel, marcas = [], pad = 22, maxAlto = 0, desde = 0, clipH3 = '' } = {}) {
  await sleep(700);
  if (clipH3) {
    await page.evaluate(t => { const h = [...document.querySelectorAll('h3')].find(x => x.textContent.includes(t)); (h.closest('.bloque') || h.parentElement).setAttribute('data-tut-clip', '1'); }, clipH3);
    sel = '[data-tut-clip]';
  }
  await marcar(page, marcas);
  const caja = await page.evaluate(([sel, pad]) => {
    const el = sel ? document.querySelector(sel) : document.body;
    if (!el) throw new Error('no existe ' + sel);
    const r = el.getBoundingClientRect();
    const x = Math.max(0, r.left + scrollX - pad), y = Math.max(0, r.top + scrollY - pad);
    return { x, y, width: Math.min(r.width + pad * 2, document.documentElement.scrollWidth - x), height: r.height + pad * 2 };
  }, [sel, pad]);
  if (desde) { caja.y += desde; caja.height -= desde; }
  if (maxAlto && caja.height > maxAlto) caja.height = maxAlto;
  await page.screenshot({ path: `${OUT}/${nombre}.jpg`, type: 'jpeg', quality: 70, fullPage: true, clip: caja });
  await page.evaluate(() => { window.__quitarMarcas && window.__quitarMarcas(); const c = document.querySelector('[data-tut-clip]'); if (c) c.removeAttribute('data-tut-clip'); });
  console.log('captura', nombre);
}

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
  await ctx.addCookies([{ name: cfg.cookie_name, value: cfg.cookie, url: BASE }]);
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') avisos.push(m.text()); if (m.text().startsWith('SIN MARCA')) avisos.push(m.text()); });
  page.on('pageerror', e => avisos.push('pageerror ' + e.message));
  const ir = async (q) => { await page.goto(`${BASE}/entornos/xsii/${PID}${q || ''}`); await sleep(1300); };
  const form = async () => { await page.click('form.form button[type=submit]'); await sleep(900); };
  const confirmar = async () => { await page.click('button.btn.p:text-is("Confirmar")'); await sleep(1100); };
  const subir = (cod, ruta) => execSync(`${PY} ${__dirname}/preparar.py subir ${PID} ${cod} ${ruta}`, { cwd: RAIZ });
  const SECC = path.join(__dirname, 'datos', 'seccionales-como-viene.csv');
  const PADRON = path.join(__dirname, 'datos', 'padron-ejemplo.csv');

  // ---- Entrar: /entornos -> Implementación
  await page.goto(`${BASE}/entornos`); await sleep(1200);
  await page.click('button[data-tab="implementacion"]'); await sleep(1500);
  await foto(page, 'p02-entornos', { sel: '.panel-etab[data-panel="implementacion"]', maxAlto: 620, marcas: [{ btn: 'Abrir XSII', n: 1 }] });

  // ---- La Guía en un proyecto recién abierto
  await ir();
  await foto(page, 'p03-guia', { sel: '.app', maxAlto: 980, marcas: [{ css: '.av', n: 1 }, { css: '.heroe', n: 2 }, { css: '.otras', n: 3 }, { css: '.pano', n: 4 }] });
  await page.click('#x-adelante'); await sleep(900);
  await foto(page, 'p03-atras-adelante', { sel: '.heroe', pad: 12, maxAlto: 430, marcas: [{ css: '#x-atras', n: 1 }, { css: '.heroe .play', n: 2 }, { css: '#x-adelante', n: 3 }] });
  // Tablero con lo que ya se puede hacer (primera semana)
  await ir('?vista=tablero');
  await page.click('.filtros button:has-text("Se puede hacer")'); await sleep(500);
  await foto(page, 'p14-se-puede-hacer', { sel: '.app', maxAlto: 640, marcas: [{ css: '.filtros button[aria-pressed="true"]', n: 1 }] });

  // ---- La ficha de una tarea (EST-01)
  await ir('?tarea=EST-01');
  await foto(page, 'p05-ficha', { sel: '.ficha', maxAlto: 1010, marcas: [{ h3: 'Qué tenés que hacer', n: 1 }, { css: '.btn.donde', n: 2 }, { h3: 'Se espera del sindicato', n: 3 }] });

  // ---- Pedirle la lista de seccionales al sindicato (reclamo en la Mesa)
  await page.click('button:has-text("Reclamar en la Mesa")'); await sleep(1200);
  await foto(page, 'p06-reclamo', { sel: '.ficha form.rc', pad: 24, marcas: [{ css: 'form.rc textarea', n: 1 }, { css: 'form.rc button[type=submit]', n: 2 }] });
  await page.click('form.rc button[type=submit]'); await sleep(1800);
  const tarjeta = sqlq("SELECT codigo FROM impltarjeta WHERE proyecto_id=" + PID + " ORDER BY id DESC LIMIT 1");
  console.log('tarjeta', tarjeta);
  // Lo que ve el sindicato: Carla entra a la Mesa
  const ctx2 = await b.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
  const mesa = await ctx2.newPage();
  await mesa.goto(`${BASE}/implementacion/ingresar`); await sleep(800);
  await mesa.fill('#im-mail', 'carla.demo@ejemplo.org.ar'); await mesa.fill('#im-clave', 'tutorial-1234');
  await mesa.click('button.enviar'); await sleep(2200);
  console.log('mesa url', mesa.url());
  await mesa.click('text=Necesitamos: Lista de seccionales'); await sleep(1500);
  await mesa.screenshot({ path: `${OUT}/p06-mesa-sindicato.jpg`, type: 'jpeg', quality: 70 });
  console.log('captura p06-mesa-sindicato');
  // El sindicato sube la planilla
  subir(tarjeta, SECC);

  await ir();
  await ir('?tarea=EST-01');
  await foto(page, 'p06-usar-archivo', { sel: '.espera', pad: 10, marcas: [{ css: '.llego', n: 1 }, { btn: 'Usar este archivo', n: 2 }] });
  await page.click('button:has-text("Usar este archivo")'); await sleep(1300);

  // ---- Cargar las seccionales (los cuatro momentos)
  await page.click('button:has-text("Cargar desde la planilla")'); await sleep(1000);
  await page.click('#x-as-ensayar'); await page.waitForSelector('.as-nada'); await sleep(900);
  await foto(page, 'p07-ensayo', { sel: '#x-as', pad: 14, maxAlto: 1250, marcas: [{ css: '.as-nada', n: 1 }, { css: '.as-kpis', n: 2 }, { css: '.as-tab', n: 3 }] });
  await page.click('#x-as-k-dudosa').catch(() => {}); await sleep(500);
  await page.locator('.as-f.dudosa', { hasText: 'Ruta 40' }).locator('input[type=checkbox]').check(); await sleep(400);
  await foto(page, 'p07-dudosas', { sel: '#x-as', pad: 14, maxAlto: 1100, marcas: [{ css: '#x-as-k-dudosa', n: 1 }, { css: '.as-f.dudosa', n: 2 }] });
  await page.click('#x-as-k-dudosa').catch(() => {}); await sleep(300);
  await page.click('#x-as-seguir'); await sleep(900);
  await page.click('#x-as-cargar'); await sleep(700);
  await page.click('#x-as-cargar'); await page.waitForSelector('#x-as-listo'); await sleep(1100);
  await foto(page, 'p07-control', { sel: '#x-as', pad: 14, maxAlto: 1000, marcas: [{ css: '.as-ok', n: 1 }, { css: '.as-ctl', n: 2 }, { css: '#x-as-listo', n: 3 }] });
  await page.click('#x-as-listo'); await sleep(1500);
  await confirmar();  // EST-01: la lista coincide

  // ---- Padrón: llegó la planilla (PAD-01) y se carga (PAD-02)
  await ir('?tarea=PAD-01');
  await page.click('button:has-text("Marcar recibido")'); await sleep(1100);
  await confirmar();
  await ir('?tarea=PAD-02');
  await page.waitForSelector('#x-as-abrir:not([aria-disabled])');
  await page.click('#x-as-abrir'); await sleep(900);
  await page.setInputFiles('#x-as-archivo', PADRON);
  await page.fill('.as-on input', '30'); await sleep(400);
  await page.click('#x-as-ensayar'); await page.waitForSelector('.as-nada'); await sleep(900);
  await foto(page, 'p08-ensayo', { sel: '#x-as', pad: 14, maxAlto: 1060, marcas: [{ css: '.as-kpis', n: 1 }, { aviso: 'declaró', n: 2 }, { css: '.as-mots', n: 3 }] });
  await page.click('#x-as-seguir'); await sleep(900);
  await page.click('#x-as-cargar'); await sleep(600);
  await page.click('#x-as-cargar'); await page.waitForSelector('#x-as-listo'); await sleep(1300);
  await foto(page, 'p08-control', { sel: '#x-as', pad: 14, maxAlto: 1100, marcas: [{ css: '#x-as-comp', n: 1 }, { css: '.as-ctl', n: 2 }, { css: '#x-as-listo', n: 3 }] });
  await page.click('#x-as-listo'); await sleep(1300);

  // ---- Conceptos desde los recibos de muestra (REC-01 -> REC-04)
  await ir('?tarea=REC-01');
  await page.click('button:has-text("Marcar recibido")'); await sleep(1100);
  await confirmar();
  await ir('?tarea=REC-04');
  await page.waitForSelector('#x-as-abrir:not([aria-disabled])');
  await page.click('#x-as-abrir'); await sleep(900);
  const RECIBOS = ['recibo-delta-01.png', 'recibo-delta-02.png', 'recibo-norte-01.png', 'recibo-sur-01.png', 'recibo-borroso.png'].map(n => path.join(__dirname, 'recibos', n));
  await page.setInputFiles('#x-rb-archivos', RECIBOS); await sleep(600);
  await page.click('#x-rb-leer');
  await page.waitForSelector('.rb-prog.fin', { timeout: 60000 }); await sleep(900);
  await foto(page, 'p09-propuestas', { sel: '#x-as', pad: 14, maxAlto: 1000, marcas: [{ css: '.rb-prog', n: 1 }, { css: '.rb-it.fallo', n: 2 }, { css: '.rb-g', n: 3 }] });
  const fila = cod => page.locator('li.rb-f', { has: page.locator('b.rb-cod', { hasText: new RegExp('^' + cod + '$') }) });
  const etiquetar = () => page.evaluate(() => { document.querySelectorAll('li.rb-f').forEach(li => { const c = li.querySelector('.rb-cod').textContent; if (c === '105') { li.setAttribute('data-tut', 'corr'); li.closest('section').setAttribute('data-tut-g', 'g1'); } if (c === '230' && !document.querySelector('[data-tut="desc"]')) { li.setAttribute('data-tut', 'desc'); li.closest('section').setAttribute('data-tut-g', 'g2'); } }); });
  await etiquetar();
  await fila('105').locator('.rb-c:has(label:text-is("Rubro")) select').selectOption('haber'); await sleep(500);
  await fila('230').first().locator('.rb-descartar').click(); await sleep(600);
  await etiquetar();
  await foto(page, 'p09-corregir', { sel: 'li[data-tut="corr"]', pad: 24, marcas: [{ css: '[data-tut="corr"] select[id$="-r"]', n: 1 }] });
  await foto(page, 'p09-descartar', { sel: 'li[data-tut="desc"]', pad: 24, marcas: [{ css: '[data-tut="desc"] .pil', n: 2 }, { css: '[data-tut="desc"] .rb-descartar', n: 3 }] });
  execSync(`${PY} ${__dirname}/unir.py ${OUT}/p09-corregir-descartar.jpg ${OUT}/p09-corregir.jpg ${OUT}/p09-descartar.jpg`, { cwd: RAIZ });
  await page.click('#x-rb-seguir'); await sleep(900);
  await page.click('#x-as-cargar'); await sleep(700);
  await page.click('#x-as-cargar'); await page.waitForSelector('#x-as-listo'); await sleep(1200);
  await foto(page, 'p09-control', { sel: '#x-as', pad: 14, maxAlto: 1100, marcas: [{ css: '.as-ok', n: 1 }, { css: '.as-ctl', n: 2 }, { css: '#x-as-listo', n: 3 }] });
  await page.click('#x-as-listo'); await sleep(1300);

  // ---- Preguntame
  const abrirPm = async (punto) => { await page.click(`.pm[data-punto="${punto}"] .pm-t`); await sleep(700); };
  const esperaResp = async (punto) => { await page.waitForSelector(`.pm[data-punto="${punto}"] .pm-r`, { timeout: 15000 }); await sleep(900); };
  await ir();
  await abrirPm('recomendada');
  await page.click('.pm[data-punto="recomendada"] .pm-sug >> nth=0');
  await esperaResp('recomendada');
  await foto(page, 'p10-pm-respuesta', { sel: '.heroe', pad: 12, maxAlto: 900, marcas: [{ css: '.pm[data-punto="recomendada"] .pm-r', n: 1 }, { css: '.pm[data-punto="recomendada"] .pm-cod', n: 2 }] });

  // ---- Completar a mano, no aplica, posponer, deshacer
  await ir('?tarea=BAS-06');
  await page.click('button:has-text("Completar a mano")'); await sleep(300);
  await form();
  await page.fill('#x-motivo', 'El contrato lo carga plataforma el lunes; no frena el resto.');
  await form(); await sleep(500);
  await abrirBloque(page, 'Historial de la tarea');
  await foto(page, 'p13-a-mano', { sel: '.ficha', maxAlto: 1000, marcas: [{ css: '.ficha .marca-t.mano', n: 1 }, { btn: 'Deshacer: completada a mano', n: 2 }, { h3: 'Historial de la tarea', n: 3 }] });
  await page.click('button:has-text("Deshacer: completada a mano")'); await sleep(1100);
  await ir('?tarea=COM-03');
  await page.click('button:has-text("No aplica")'); await sleep(300);
  await page.fill('#x-motivo', 'El sindicato no ofrece beneficios en la primera versión.');
  await form(); await sleep(400);
  await ir('?tarea=COM-02');
  await page.click('button:has-text("Posponer")'); await sleep(300);
  await page.fill('#x-motivo', 'Las noticias se cargan después del lanzamiento.');
  await form(); await sleep(400);
  await foto(page, 'p13-pospuesta', { sel: '.ficha', maxAlto: 800, marcas: [{ css: '.ficha .marca-t', n: 1 }, { btn: 'Retomar', n: 2 }] });

  // ---- Tablero (estados) y Mapa
  await ir('?vista=tablero');
  await foto(page, 'p04-tablero', { sel: '.app', maxAlto: 1000, marcas: [{ css: '.filtros', n: 1 }, { css: 'tbody tr.grp', n: 2 }] });
  await page.click('.filtros button:has-text("Esperando un dato")'); await sleep(500);
  await foto(page, 'p11-tablero-esperando', { sel: '.app', maxAlto: 520, marcas: [{ css: '.filtros button[aria-pressed="true"]', n: 1 }] });
  await ir('?vista=mapa');
  await page.click('g.n[data-n="PAD-02"]'); await sleep(800);
  await foto(page, 'p11-mapa', { sel: '.app', maxAlto: 900, marcas: [{ css: '.lienzo', n: 1 }, { css: '.mficha', n: 2 }] });

  // ---- Hitos
  await ir('?vista=hitos');
  await page.click('#x-h-todas'); await sleep(1500);
  await foto(page, 'p12-hitos-para-marcar', { sel: '.hit-prop', pad: 14, maxAlto: 800, marcas: [{ css: '.hit-prop h3', n: 1, dx: -8 }, { css: '.hito.propuesto .pil', n: 2 }, { css: '.hito.propuesto .btn.p', n: 3 }] });
  await page.click('#x-h-m-' + await page.evaluate(() => document.querySelector('.hit-prop .hito').dataset.hito)); await sleep(700);
  await page.click('.hit-prop .hito .btn.p'); await sleep(1800);
  await foto(page, 'p12-hitos-hecho', { sel: '.hitos', pad: 16, maxAlto: 800, marcas: [{ css: '.aviso.exito', n: 1 }, { css: '.hit-k', n: 2, dx: -8 }] });

  console.log('AVISOS:', JSON.stringify(avisos, null, 1));
  await b.close();
})().catch(e => { console.error('FALLO', e); process.exit(1); });
