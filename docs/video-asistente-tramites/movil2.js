/* Escena del celular: Josefina pide el kit escolar desde la app, en Pruebas. */
const { chromium } = require('playwright');
const { Filmador } = require('./lib');
const BASE = 'https://mitrabajo-pruebas.onrender.com';
const OUT = __dirname + '/../frames/movil2';
const ADJ = __dirname + '/../adjuntos/';
const BAR = parseFloat(process.env.BAR || '1.6');
const T0 = parseFloat(process.env.T0 || '0');
const b = (k) => T0 + k * BAR;

(async () => {
  const browser = await chromium.launch({ args: ['--lang=es-419', '--accept-lang=es-AR,es'] });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'es-AR', timezoneId: 'America/Argentina/Buenos_Aires' });
  const l = await ctx.newPage();
  await l.goto(BASE + '/ingresar', { waitUntil: 'networkidle' });
  await l.fill('input[name="cuil"]', '27999999994'); await l.fill('input[name="clave"]', '27999');
  await l.click('button[type="submit"]'); await l.waitForLoadState('networkidle'); await l.close();

  const page = await ctx.newPage();
  await page.clock.install({ time: new Date('2026-10-26T10:34:00-03:00') });
  page.on('pageerror', (e) => console.log('pageerror:', e.message));
  await page.goto(BASE + '/app?tab=tramites', { waitUntil: 'networkidle' });
  const film = new Filmador(page, OUT, { prefix: 'm', mobile: true });
  await film.preparar();
  await page.evaluate(() => { document.body.style.transform = ''; });   // en el celular no hay cámara: el encuadre se hace al componer
  film.cam = null; film.cursor = undefined;
  film.t = T0;
  await page.clock.runFor(2500);
  await film.esperar(() => document.querySelector('#tram-nuevo-sub') && !/Elegí el formulario/.test(document.querySelector('#tram-nuevo-sub').textContent), { timeout: 15000 }).catch(() => {});
  await page.clock.runFor(200);
  film.marca('bandeja de trámites');
  await film.hasta(b(0.4));
  // tocar "Iniciar un trámite"
  await film.click('#tram-nuevo');
  await film.esperar(() => !!document.querySelector('#tram-tipos-lista .tram-item'));
  await page.clock.runFor(200);
  film.marca('lista de formularios');
  await film.hasta(b(0.8));
  // elegir Kit escolar 2027
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('#tram-tipos-lista .tram-item')).find((x) => /Kit escolar/.test(x.textContent)); if (!b) throw new Error('sin Kit escolar'); b.click(); });
  await film.esperar(() => document.querySelector('#tram-form') && document.querySelector('#tram-form').style.display !== 'none' && document.querySelectorAll('#tram-form-campos input, #tram-form-campos select').length > 3);
  await page.clock.runFor(400);
  film.marca('formulario abierto');
  await film.hasta(b(1.2));
  // completar: en orden de los campos del tipo
  const ids = await page.evaluate(() => Array.from(document.querySelectorAll('#tram-form-campos input, #tram-form-campos select')).map((e) => ({ id: e.id, tipo: e.type || e.tagName.toLowerCase(), tag: e.tagName.toLowerCase() })));
  console.log('  campos:', ids.map((c) => c.id + ':' + c.tipo).join(' '));
  const porTipo = (t) => ids.filter((c) => c.tipo === t);
  const scrollA = async (id) => page.evaluate((i) => { const el = document.getElementById(i); const r = el.getBoundingClientRect(); window.scrollBy(0, r.top - 300); }, id);
  // 1) primera vez: sí
  const chk = porTipo('checkbox')[0]; await film.click('#' + chk.id); await film.hasta(b(1.4));
  // 2) nombre
  const txt = porTipo('text'); await scrollA(txt[0].id);
  await film.escribir('#' + txt[0].id, 'Mateo Nieves', b(1.9), { speed: 1 });
  // 3) DNI (numero = text inputmode decimal)
  await film.escribir('#' + txt[1].id, '58123456', b(2.2));
  // 4) fecha
  const fecha = porTipo('date')[0]; await film.elegir('#' + fecha.id, '2018-03-14');
  // Chromium headless muestra la fecha en formato inglés: para la cámara se dibuja como texto argentino y se restaura antes de enviar.
  await page.evaluate((i) => { const el = document.getElementById(i); el.type = 'text'; el.value = '14/03/2018'; }, fecha.id);
  await film.hasta(b(2.35));
  // 5..7) selects: vínculo, nivel, grado
  const sels = ids.filter((c) => c.tag === 'select');
  await scrollA(sels[0].id);
  const valores = ['Hijo/a', 'Primaria 1.º a 3.º', '3.º', 'Sede de la seccional'];
  for (let i = 0; i < 3; i++) { await film.elegir('#' + sels[i].id, valores[i]); await film.hasta(b(2.35 + 0.15 * (i + 1))); }
  // 8) archivos
  const files = porTipo('file');
  await scrollA(files[0].id);
  await page.setInputFiles('#' + files[0].id, ADJ + 'dni-chico.jpg'); await film.hasta(b(3.0));
  if (files[1]) { await page.setInputFiles('#' + files[1].id, ADJ + 'dni-chico.jpg'); await film.hasta(b(3.15)); }
  if (files[2]) { await page.setInputFiles('#' + files[2].id, ADJ + 'constancia.jpg'); await film.hasta(b(3.3)); }
  // 9) lugar de retiro
  if (sels[3]) { await scrollA(sels[3].id); await film.elegir('#' + sels[3].id, valores[3]); }
  await film.hasta(b(3.5));
  await scrollA('tram-form-enviar');
  await film.hasta(b(3.75));
  film.marca('enviar');
  await page.evaluate((i) => { const el = document.getElementById(i); el.type = 'date'; el.value = '2018-03-14'; }, fecha.id);
  await film.click('#tram-form-enviar');   // el envío lee los valores en el mismo clic
  await page.evaluate((i) => { const el = document.getElementById(i); el.type = 'text'; el.value = '14/03/2018'; }, fecha.id);
  await film.esperar(() => !!document.querySelector('#tram-sello.on'), { timeout: 40000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  film.marca('sello');
  await film.hasta(b(4.6), 0.5);      // el sello en cámara lenta
  await film.hasta(b(5.6), 1);
  await film.esperar(() => /DATOS PRESENTADOS|Estado/i.test(document.body.innerText), { timeout: 20000 }).catch(() => {});
  film.marca('expediente');
  await film.hasta(b(8.0), 1);
  film.marca('fin celular');
  await browser.close();
})().catch((e) => { console.error('ERROR', e); process.exit(1); });
