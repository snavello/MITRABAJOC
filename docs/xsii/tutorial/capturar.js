/* Filma el tutorial de XSII contra un servidor LOCAL con la demo cargada.
   Uso (desde la raíz del repo, con DATABASE_URL del .env):
     NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node docs/xsii/tutorial/capturar.js
   Deja los JPEG en docs/xsii/tutorial/capturas/. Ejecuta las acciones de verdad
   (decisiones, insumos) y por eso arranca llamando a preparar.py, que limpia
   los restos de XSII y crea el proyecto «UOM · Primera versión». */
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const path = require('path');
const RAIZ = path.resolve(__dirname, '..', '..', '..');
const OUT = path.join(__dirname, 'capturas');
const BASE = process.env.XSII_URL || 'http://localhost:8765';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ORANGE = '#e8590c';

const cfg = JSON.parse(execSync(`${RAIZ}/.venv/bin/python ${__dirname}/preparar.py`, { cwd: RAIZ }).toString().trim().split('\n').pop());
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

  // 1. La entrada: /entornos -> Implementación
  await page.goto(`${BASE}/entornos`); await sleep(1200);
  await page.click('button[data-tab="implementacion"]'); await sleep(1500);
  await foto(page, '01-entornos-implementacion', { sel: '.panel-etab[data-panel="implementacion"]', marcas: [{ btn: 'Abrir XSII', n: 1 }, { btn: 'Abrir la mesa', n: 2 }] });

  // 2. La Guía
  await ir();
  await foto(page, '02-guia', { sel: '.app', marcas: [{ css: '#x-avance', n: 1 }, { css: '.heroe', n: 2 }, { css: '.otras', n: 3 }, { css: '.pano', n: 4 }] });
  // 2b. Moverse entre los pasos: Atrás y Adelante (un paso que no es el recomendado)
  await page.click('#x-adelante'); await sleep(900);
  await foto(page, '36-guia-atras-adelante', { sel: '.heroe', pad: 14, marcas: [{ css: '#x-atras', n: 1 }, { css: '#x-adelante', n: 2 }, { css: '.heroe .rot-f .rot', n: 3, dx: -22 }, { css: '.heroe .rot-f .enlace', n: 4, dx: -14 }] });

  // 3. La ficha de una tarea (EST-01)
  await ir('?tarea=EST-01');
  await abrirBloque(page, 'Lo que dice el control');
  await foto(page, '03-ficha-est01', { sel: '.app', marcas: [{ h3: 'Lo que dice el control', n: 1 }, { css: '.btn.donde', n: 2 }, { css: '.sr-aviso', n: 3 }] });

  // 3b. Cargar las seccionales desde la planilla (EST-01): los cuatro momentos, con el servidor real
  const PLANILLA = path.join(__dirname, 'seccionales-tutorial.csv');
  await ir('?tarea=EST-01');
  await page.waitForSelector('#x-as-abrir:not([aria-disabled])');
  await page.click('#x-as-abrir'); await sleep(900);
  await page.setInputFiles('#x-as-archivo', PLANILLA); await sleep(500);
  await foto(page, '37-as-paso1', { sel: '#x-as', pad: 14, maxAlto: 1700, marcas: [{ css: '.as-pasos', n: 1 }, { css: '#x-as-modelo', n: 2 }, { css: '.as-arch', n: 3 }, { css: '.as-pegar', n: 4 }, { css: '.as-opc', n: 5 }] });
  await page.click('#x-as-ensayar'); await page.waitForSelector('.as-nada'); await sleep(900);
  await foto(page, '38-as-ensayo', { sel: '#x-as', pad: 14, marcas: [{ css: '.as-nada', n: 1 }, { css: '.as-kpis', n: 2 }, { css: '.as-tab', n: 3 }] });
  await page.click('#x-as-mapa-sum'); await sleep(500);
  await foto(page, '44-as-columnas', { sel: '#x-as-mapa', pad: 14, marcas: [{ css: '#x-as-map-res', n: 1, dx: 36, dy: -22 }, { css: '.as-mc.sinuso', n: 2 }, { css: '#x-as-map-sinuso', n: 3, dx: -14 }, { css: '.as-mc select', n: 4 }] });
  await page.click('#x-as-mapa-sum'); await sleep(300);
  await page.click('#x-as-k-rechazada'); await sleep(500);
  await foto(page, '39-as-rechazada', { sel: '#x-as', pad: 14, marcas: [{ css: '#x-as-k-rechazada', n: 1 }, { css: '.as-f.rechazada', n: 2 }] });
  await page.click('#x-as-k-rechazada'); await page.click('#x-as-k-dudosa'); await sleep(400);
  await page.locator('.as-f.dudosa', { hasText: 'Neuquén' }).locator('input[type=checkbox]').check(); await sleep(400);
  await foto(page, '40-as-dudosas', { sel: '#x-as', pad: 14, marcas: [{ css: '#x-as-k-dudosa', n: 1 }, { css: '.as-f.dudosa.fuera', n: 2 }, { css: '.as-f.dudosa:not(.fuera)', n: 3 }] });
  await page.click('#x-as-k-dudosa'); await sleep(300);
  await page.click('#x-as-seguir'); await sleep(900);
  await page.click('#x-as-cargar'); await sleep(700);
  await foto(page, '41-as-confirmar', { sel: '#x-as', pad: 14, marcas: [{ css: '.as-res', n: 1 }, { css: '#x-as-cargar', n: 2 }, { css: '#x-as-nocargar', n: 3 }] });
  await page.click('#x-as-cargar'); await page.waitForSelector('#x-as-listo'); await sleep(1100);
  await foto(page, '42-as-control', { sel: '#x-as', pad: 14, marcas: [{ css: '.as-ok', n: 1 }, { css: '.as-ctl', n: 2 }, { css: '.as-sigue', n: 3 }, { css: '#x-as-listo', n: 4 }] });
  await page.click('#x-as-listo'); await sleep(1500);
  await abrirBloque(page, 'Historial de la tarea');
  await foto(page, '43-as-ficha-despues', { sel: '.app', maxAlto: 1700, marcas: [{ h3: 'Insumos', n: 1 }, { btn: 'Confirmar', n: 2 }, { h3: 'Historial de la tarea', n: 3 }] });

  // 4. Pedir un dato al sindicato, a mano (REC-01, «Recibos de muestra»)
  await ir('?tarea=REC-01');
  await foto(page, '04-rec01-falta', { sel: '.ficha', marcas: [{ h3: 'Se espera del sindicato', n: 1 }, { btn: 'Marcar pedido', n: 2 }] });
  await page.click('button:has-text("Marcar pedido")'); await sleep(300);
  await page.fill('#x-ins-tarjeta', cfg.tarjetas[2]);
  await page.fill('#x-ins-nota', 'Se lo pedimos a Marcela, de Afiliaciones.');
  await foto(page, '06-rec01-form-pedido', { sel: '.ficha', marcas: [{ css: '#x-ins-tarjeta', n: 1 }] });
  await form(); await sleep(500);
  await foto(page, '07-rec01-pedido', { sel: '.ficha', marcas: [{ h3: 'Se espera del sindicato', n: 1 }] });

  // 4b. Preguntame sobre el paso recomendado (Guía)
  const abrirPm = async (punto) => { await page.click(`.pm[data-punto="${punto}"] .pm-t`); await sleep(700); };
  const esperaResp = async (punto) => { await page.waitForSelector(`.pm[data-punto="${punto}"] .pm-r`, { timeout: 15000 }); await sleep(900); };
  await ir();
  await abrirPm('recomendada');
  await foto(page, '23-pm-guia-abierto', { sel: '.heroe', pad: 14, marcas: [{ css: '.pm[data-punto="recomendada"] .pm-t', n: 1 }, { css: '.pm[data-punto="recomendada"] .pm-q', n: 2 }, { css: '.pm[data-punto="recomendada"] .pm-campo', n: 3 }] });
  await page.click('.pm[data-punto="recomendada"] .pm-sug >> nth=0');
  await esperaResp('recomendada');
  await foto(page, '24-pm-guia-respuesta', { sel: '.heroe', pad: 14, marcas: [{ css: '.pm[data-punto="recomendada"] .pm-r', n: 1 }, { css: '.pm[data-punto="recomendada"] .pm-cod', n: 2 }, { css: '.pm[data-punto="recomendada"] .pm-r .nota', n: 3 }] });

  // 4c. Preguntame en una ficha: un error (muy corta) y una pregunta escrita a mano (PAD-02)
  await ir('?tarea=PAD-02');
  await abrirPm('tarea');
  await page.fill('.pm[data-punto="tarea"] .pm-campo', 'ok');
  await page.click('.pm[data-punto="tarea"] button[type=submit]'); await sleep(700);
  await foto(page, '25-pm-pregunta-corta', { sel: '.pm[data-punto="tarea"]', pad: 14, marcas: [{ css: '.pm[data-punto="tarea"] .pm-campo', n: 1 }, { css: '.pm[data-punto="tarea"] .err', n: 2 }] });
  await page.fill('.pm[data-punto="tarea"] .pm-campo', '¿Qué la frena hoy?');
  await page.click('.pm[data-punto="tarea"] button[type=submit]');
  await esperaResp('tarea');
  await foto(page, '26-pm-ficha-escrita', { sel: '.pm[data-punto="tarea"]', pad: 14, marcas: [{ css: '.pm[data-punto="tarea"] .pm-campo', n: 1 }, { css: '.pm[data-punto="tarea"] .pm-r', n: 2 }] });

  // 4d. Preguntame en el Mapa
  await ir('?vista=mapa');
  await page.click('g.n[data-n="PAD-02"]'); await sleep(800);
  await abrirPm('mapa');
  await page.click('.pm[data-punto="mapa"] .pm-sug >> nth=1');
  await esperaResp('mapa');
  await foto(page, '27-pm-mapa', { sel: '.app', marcas: [{ css: '.mficha', n: 1 }, { css: '.pm[data-punto="mapa"] .pm-r', n: 2 }] });

  // 4e. El asistente propone un reclamo (PAD-01, «Padrón recibido»)
  await ir('?tarea=PAD-01');
  await foto(page, '04-pad01-falta', { sel: '.ficha', marcas: [{ h3: 'Se espera del sindicato', n: 1 }, { btn: 'Reclamar en la Mesa', n: 2 }] });
  await abrirPm('tarea');
  await page.click('.pm[data-punto="tarea"] .pm-sug >> nth=0');
  await esperaResp('tarea');
  await foto(page, '28-pm-propuesta', { sel: '.pm[data-punto="tarea"]', pad: 14, marcas: [{ css: '.pm[data-punto="tarea"] .pm-r', n: 1 }, { css: '.pm[data-punto="tarea"] form.rc', n: 2 }, { btn: 'Crear en la Mesa', n: 3 }, { btn: 'Descartar', n: 4 }] });
  const ta = page.locator('.pm[data-punto="tarea"] form.rc textarea');
  const previo = await ta.inputValue();
  await ta.fill(previo + ' Si la tienen en Excel, mejor.');
  await foto(page, '29-pm-propuesta-editada', { sel: '.pm[data-punto="tarea"] form.rc', pad: 14, marcas: [{ css: '.pm[data-punto="tarea"] form.rc textarea', n: 1 }] });
  await page.click('.pm[data-punto="tarea"] form.rc button[type=submit]'); await sleep(1800);
  await foto(page, '30-reclamo-creado', { sel: '.app', maxAlto: 1300, marcas: [{ css: '.aviso.exito', n: 1 }, { h3: 'Se espera del sindicato', n: 2 }] });
  await page.goto(`${BASE}/implementacion?p=${PID}`); await sleep(1800);
  await page.click('text=Necesitamos: Planilla del padrón >> nth=0').catch(() => {});
  await sleep(500);
  await page.screenshot({ path: `${OUT}/31-mesa-tarjeta-nueva.jpg`, type: 'jpeg', quality: 80, fullPage: true });
  console.log('captura 31-mesa-tarjeta-nueva');

  // 5a. Confirmar antes de que llegue el insumo
  await ir('?tarea=PAD-01');
  await foto(page, '05-pad01-confirmar-error', { clipH3: 'Lo que hay que confirmar', marcas: [{ txt: 'Primero registrá', n: 1 }] });
  // El aviso de demorado: atrasamos el pedido tres días
  sql("UPDATE xsiiinsumo SET cuando = to_char(now() - interval '3 days','YYYY-MM-DD HH24:MI:SS') WHERE clave='planilla_padron' AND activa");
  await ir();
  await foto(page, '08-guia-demorado', { sel: '.app', marcas: [{ css: '.pano .aviso', n: 1 }, { css: '.pano .aviso button', n: 2 }] });
  // 5b. Reclamar sin asistente: el formulario con el borrador, en modo respuesta
  await page.click('.pano .aviso button:has-text("Reclamar en la Mesa")'); await sleep(1200);
  await foto(page, '32-reclamo-respuesta-form', { sel: '.app', marcas: [{ css: '#x-cond form.rc', n: 1 }, { css: '#x-cond form.rc a', n: 2 }, { btn: 'Responder en la tarjeta', n: 3 }] });
  await page.click('#x-cond form.rc button[type=submit]'); await sleep(1800);
  await foto(page, '33-reclamo-muy-seguido', { sel: '#x-cond form.rc', pad: 14, marcas: [{ css: '#x-cond form.rc .err', n: 1 }] });
  await sleep(65000);
  await page.click('#x-cond form.rc button[type=submit]'); await sleep(1800);
  await foto(page, '35-reclamo-respuesta-hecho', { sel: '.app', maxAlto: 900, marcas: [{ css: '.aviso.exito', n: 1 }] });
  await page.goto(`${BASE}/implementacion?p=${PID}`); await sleep(1800);
  await page.click('text=Necesitamos: Planilla del padrón >> nth=0').catch(() => {});
  await sleep(700);
  await page.screenshot({ path: `${OUT}/34-mesa-tarjeta-respondida.jpg`, type: 'jpeg', quality: 80, fullPage: true });
  console.log('captura 34-mesa-tarjeta-respondida');
  // 4f. Llegó: marcar recibido
  await ir('?tarea=PAD-01');
  await page.click('button:has-text("Marcar recibido")'); await sleep(1100);
  await foto(page, '09-pad01-recibido', { sel: '.ficha', marcas: [{ css: '.ficha .pil', n: 1 }, { h3: 'Insumos', n: 2 }] });
  // 5c. Confirmar
  await page.click('button.btn.p:text-is("Confirmar")'); await sleep(1100);
  await abrirBloque(page, 'Decisiones activas');
  await foto(page, '10-pad01-confirmada', { sel: '.ficha', marcas: [{ css: '.ficha .pil', n: 1 }, { h3: 'Decisiones activas', n: 2 }] });

  // 5d. Cargar el padrón desde la planilla (PAD-02). Antes se confirma Seccionales (EST-01): la carga exige las dos previas resueltas.
  await ir('?tarea=EST-01');
  await page.click('button.btn.p:text-is("Confirmar")'); await sleep(1100);
  const PADRON = path.join(__dirname, 'padron-tutorial.csv');
  await ir('?tarea=PAD-02');
  await page.waitForSelector('#x-as-abrir:not([aria-disabled])');
  await page.click('#x-as-abrir'); await sleep(900);
  await page.setInputFiles('#x-as-archivo', PADRON);
  await page.fill('.as-on input', '2990'); await sleep(400);
  await foto(page, '45-pad-paso1', { sel: '#x-as', pad: 14, maxAlto: 1800, marcas: [{ css: '.as-cols', n: 1 }, { css: '.as-arch', n: 2 }, { css: '.as-opc .as-o:not(.as-on)', n: 3 }, { css: '.as-on input', n: 4 }] });
  await page.click('#x-as-ensayar'); await page.waitForSelector('.as-nada'); await sleep(900);
  await page.click('#x-as-mapa-sum'); await sleep(500);
  await foto(page, '46-pad-columnas', { sel: '#x-as-mapa', pad: 14, marcas: [{ css: '#x-as-map-res', n: 1, dx: 36, dy: -22 }, { css: '.as-mc.sinuso', n: 2 }, { css: '.as-mc.sinuso select', n: 3 }, { css: '#x-as-reensayar-mapa', n: 4 }] });
  await page.locator('.as-mc.sinuso select').selectOption('mail'); await sleep(400);
  await page.click('#x-as-reensayar-mapa'); await page.waitForSelector('.as-nada'); await sleep(1100);
  await foto(page, '47-pad-ensayo', { sel: '#x-as', pad: 14, maxAlto: 1900, marcas: [{ css: '.as-kpis', n: 1 }, { css: '.aviso', n: 2 }, { css: '.as-mots', n: 3 }, { css: '.as-tab', n: 4 }] });
  await page.click('#x-as-k-rechazada'); await sleep(500);
  await foto(page, '48-pad-rechazadas', { sel: '#x-as', pad: 14, maxAlto: 1300, marcas: [{ css: '#x-as-k-rechazada', n: 1 }, { css: '.as-f.rechazada', n: 2 }] });
  await page.click('#x-as-k-rechazada'); await sleep(300);
  await page.click('#x-as-seguir'); await sleep(900);
  await page.click('#x-as-cargar'); await sleep(600);
  await page.click('#x-as-cargar'); await page.waitForSelector('#x-as-listo'); await sleep(1300);
  await foto(page, '49-pad-control', { sel: '#x-as', pad: 14, maxAlto: 1700, marcas: [{ css: '#x-as-comp', n: 1 }, { css: '.as-ctl', n: 2 }, { css: '.as-sigue', n: 3, dx: -14 }] });
  await page.click('#x-as-listo'); await sleep(1300);

  // 6. Un error: completar a mano sin motivo (BAS-02)
  await ir('?tarea=BAS-02');
  await page.click('button:has-text("Completar a mano")'); await sleep(300);
  await form();
  await foto(page, '11-bas02-sin-motivo', { sel: '.ficha', marcas: [{ css: '.ficha .err', n: 1 }] });
  // 7. Completada a mano, con motivo
  await page.fill('#x-motivo', 'El logo lo carga plataforma el lunes; no frena el resto.');
  await form(); await sleep(500);
  await abrirBloque(page, 'Lo que calcula el control'); await abrirBloque(page, 'Decisiones activas');
  await foto(page, '12-bas02-a-mano', { sel: '.ficha', marcas: [{ css: '.ficha .marca-t.mano', n: 1 }, { h3: 'Lo que calcula el control', n: 2 }, { h3: 'Decisiones activas', n: 3 }, { btn: 'Deshacer: completada a mano', n: 4 }] });
  await ir('?vista=tablero');
  await page.click('.filtros button:has-text("Completadas a mano")'); await sleep(500);
  await foto(page, '13-tablero-a-mano', { sel: '.app', marcas: [{ css: '.filtros button[aria-pressed="true"]', n: 1 }, { css: 'tbody .marca-t', n: 2 }] });
  await ir('?tarea=BAS-02');
  await page.click('button:has-text("Deshacer: completada a mano")'); await sleep(1100);
  await abrirBloque(page, 'Historial de la tarea');
  await foto(page, '14-bas02-deshecha', { sel: '.ficha', marcas: [{ css: '.ficha .pil', n: 1 }, { css: '.ficha .hist', n: 2 }] });

  // 8. No aplica y posponer
  await ir('?tarea=COM-03');
  await page.click('button:has-text("No aplica")'); await sleep(300);
  await page.fill('#x-motivo', 'El sindicato no ofrece beneficios en la primera versión.');
  await foto(page, '15-com03-no-aplica-form', { sel: '.ficha', marcas: [{ css: '#x-motivo', n: 1 }] });
  await form(); await sleep(400);
  await foto(page, '16-com03-no-aplica', { sel: '.ficha', marcas: [{ css: '.ficha .pil', n: 1 }, { btn: 'Volver a aplicar', n: 2 }] });
  await ir('?tarea=COM-02');
  await page.click('button:has-text("Posponer")'); await sleep(300);
  await page.fill('#x-motivo', 'Las noticias se cargan después del lanzamiento.');
  await form(); await sleep(400);
  await foto(page, '17-com02-pospuesta', { sel: '.ficha', marcas: [{ css: '.ficha .marca-t', n: 1 }, { btn: 'Retomar', n: 2 }] });

  // 9. Tablero
  await ir('?vista=tablero');
  await foto(page, '18-tablero', { sel: '.app', marcas: [{ css: '.filtros', n: 1 }, { css: 'tbody tr.grp', n: 2 }], maxAlto: 1250 });
  await page.click('.filtros button:has-text("Esperando un dato")'); await sleep(500);
  await foto(page, '19-tablero-esperando', { sel: '.app', marcas: [{ css: '.filtros button[aria-pressed="true"]', n: 1 }] });

  // 10. Mapa
  await ir('?vista=mapa');
  await page.click('g.n[data-n="PAD-02"]'); await sleep(800);
  await foto(page, '20-mapa', { sel: '.app', marcas: [{ css: '.mficha', n: 1 }, { css: '.lienzo', n: 2 }] });

  // 11. El registro
  await ir();
  await foto(page, '21-guia-movimientos', { sel: '.pano', marcas: [{ css: '.pano .log', n: 1 }] });
  await ir('?tarea=PAD-01');
  await abrirBloque(page, 'Historial de la tarea');
  await foto(page, '22-pad01-historial', { sel: '.ficha', marcas: [{ h3: 'Historial de la tarea', n: 1 }] });

  console.log('errores de consola:', JSON.stringify(errs));
  await b.close();
})().catch(e => { console.error('FALLO', e); process.exit(1); });
