/* Escena principal: el Asistente de trámites en Pruebas, filmado con reloj virtual. */
const { chromium } = require('playwright');
const { Filmador } = require('./lib');
const BASE = 'https://mitrabajo-pruebas.onrender.com';
const OUT = __dirname + '/../frames/asistente2';
const BAR = parseFloat(process.env.BAR || '1.0');
const T0 = parseFloat(process.env.T0 || '0');       // cuándo arranca la escena en el video
const HASTA = parseFloat(process.env.HASTA || '99');
const b = (k) => T0 + k * BAR;                          // compás k desde el inicio de la escena

const RELATO = 'En La Bancaria queremos digitalizar el pedido del kit escolar. Lo pide el afiliado titular, uno por cada hijo en edad escolar, entre diciembre y enero. Carga los datos del chico, el nivel y el grado, y sube el DNI y la constancia de alumno regular. Lo revisa Acción Social de la seccional; cuando lo aprueba le avisa dónde retirarlo. Se retira mostrando la credencial.';

async function botonPorTexto(page, re) {
  return page.evaluate((src) => {
    const r = new RegExp(src);
    const b = Array.from(document.querySelectorAll('button')).find((x) => r.test(x.textContent.trim()));
    if (!b) throw new Error('sin botón ' + src);
    b.click(); return true;
  }, re.source);
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, locale: 'es-AR', timezoneId: 'America/Argentina/Buenos_Aires' });
  // login en otra página del mismo contexto
  const l = await ctx.newPage();
  await l.goto(BASE + '/plataforma', { waitUntil: 'networkidle' });
  await l.fill('input[name="usuario"]', 'snavello'); await l.fill('input[name="clave"]', 'Fiesta1996');
  await l.click('button[type="submit"]'); await l.waitForLoadState('networkidle'); await l.close();

  const page = await ctx.newPage();
  await page.clock.install({ time: new Date('2026-10-26T10:30:00-03:00') });
  // la respuesta de la IA se retiene hasta el corte
  let liberar = null, respuestaIA = null;
  await page.route('**/api/entornos/herramientas/asistente/entender', async (route) => {
    const r = await route.fetch();
    const body = await r.body();
    respuestaIA = { status: r.status(), body };
    console.log('  IA respondió', r.status(), body.length, 'bytes');
    await new Promise((res) => { liberar = res; });
    await route.fulfill({ response: r, body });
  });
  await page.goto(BASE + '/entornos/herramientas/asistente-tramites', { waitUntil: 'networkidle' });
  const film = new Filmador(page, OUT, { prefix: 'a' });
  await film.preparar();
  film.t = T0;
  await page.clock.runFor(2500); // que terminen las entradas de la página

  // ---- Paso 1: el relato
  const pagina = await film.rect('.pagina');
  film.limites = { l: pagina.x - 30, r: pagina.x + pagina.w + 30 };
  const tarjeta = await film.rect('section.tarjeta');
  film.camSet({ x: tarjeta.cx, y: tarjeta.cy - 20, z: 1.4 });
  film.cursorSet({ x: tarjeta.cx + 200, y: tarjeta.cy + 200, pulso: 0 });
  // sindicato: La Bancaria
  const valorBancaria = await page.evaluate(() => { const s = document.querySelector('select'); const o = Array.from(s.options).find((x) => /Bancaria/i.test(x.textContent)); return o ? o.value : ''; });
  film.marca('paso 1'); await film.irYClic('select', b(0.8));
  if (valorBancaria) await film.elegir('select', valorBancaria);
  await film.hasta(b(1.2));
  const ta = await film.rect('textarea');
  await film.irYClic('textarea', b(1.7), { dy: -ta.h / 2 + 30, dx: -ta.w / 2 + 60 });
  film.cursor = null;
  film.camTo({ x: ta.cx, y: ta.cy - 20, z: 1.55 }, b(6.0));
  await film.escribir('textarea', RELATO, b(9.5));
  film.marca('relato escrito');
  // ---- clic en Analizar con IA
  film.cursorSet({ x: ta.cx + 100, y: ta.cy + 160, pulso: 0 });
  film.camTo({ x: tarjeta.cx, y: tarjeta.cy + 90, z: 1.45 }, b(10.4));
  await film.irYClic('button.boton-ia', b(10.6));
  film.marca('clic IA');
  const aro = await film.rect('.estado-ia').catch(() => null);
  film.camTo({ x: tarjeta.cx, y: tarjeta.cy + 100, z: 1.6 }, b(12.2));
  // esperar a la IA: la película sigue con el aro mientras la respuesta no llega
  const limite = b(12.6);
  while (film.t < limite - 1e-6) await film.cuadro(1);
  const espera = Date.now();
  while (!respuestaIA && Date.now() - espera < 120000) { await new Promise((r) => setTimeout(r, 300)); }
  if (!respuestaIA) throw new Error('la IA no respondió en 2 minutos');
  film.marca('IA lista, se libera en el corte');
  film.cursor = null;
  liberar();
  page.on('console', (m) => console.log('  console:', m.type(), m.text().slice(0, 300)));
  page.on('pageerror', (e) => console.log('  pageerror:', e.message));
  try { await film.esperar(() => /Esto entendí|Arrancamos/.test(document.querySelector('section.tarjeta h2')?.textContent || ''), { timeout: 12000 }); }
  catch (e) { console.log('  estado:', await page.evaluate(() => ({ estado: document.querySelector('.estado-ia')?.textContent, h2: document.querySelector('section.tarjeta h2')?.textContent, err: document.querySelector('.error, .banner.mal, [role=alert]')?.textContent }))); console.log('  cuerpo IA:', respuestaIA.body.toString().slice(0, 400)); await page.screenshot({ path: __dirname + '/../capturas/debug_paso2.png' }); throw e; }
  await page.clock.runFor(50);
  film.marca('paso 2');
  if (HASTA < 5) { await browser.close(); return; }

  // ---- Paso 2: esto entendí
  const dl = await film.rect('dl.entendi');
  film.camSet({ x: dl.cx, y: dl.cy - 120, z: 1.25 });
  const t2 = film.t;
  film.camTo({ x: dl.cx, y: dl.cy, z: 1.55 }, t2 + 5.5);
  await film.hasta(t2 + 5.4);
  const btnPreg = await film.rect('.acciones .boton:not(.suave)');
  film.cursorSet({ x: btnPreg.cx - 300, y: btnPreg.cy + 120, pulso: 0 });
  film.camTo({ x: dl.cx, y: btnPreg.cy - 200, z: 1.3 }, t2 + 6.4);
  await film.irYClic('.acciones .boton:not(.suave)', t2 + 6.4);
  film.marca('preguntas');
  await page.clock.runFor(30);

  // ---- Paso 3: seis preguntas
  const ritmo = [1.1, 2.6, 1.1, 1.1, 1.1, 1.1];   // segundos; la 2.ª en cámara lenta
  let tq = film.t;
  for (let i = 0; i < 6; i++) {
    const fin = tq + ritmo[i] * BAR;
    const tj = await film.rect('section.tarjeta');
    const opSel = await film.rect('label.op.sel').catch(() => null);
    const foco = opSel || tj;
    if (i === 1) {
      // cámara lenta: zoom a la opción propuesta y su área
      film.camSet({ x: tj.cx, y: tj.cy - 80, z: 1.3 });
      film.camTo({ x: foco.cx, y: foco.cy + 40, z: 1.75 }, fin - 0.5);
      film.cursorSet({ x: foco.cx + 320, y: foco.cy + 90, pulso: 0 });
      film.cursorTo({ x: foco.cx - foco.w / 2 + 40, y: foco.cy }, fin - 1.3);
      await film.hasta(fin - 0.6, 0.45);
      film.pulso(film.t + 0.3);
      await film.hasta(fin - 0.2, 0.6);
      film.cursor = null;
      await film.hasta(fin);
    } else {
      film.camSet({ x: tj.cx, y: tj.cy - 60, z: 1.35 });
      film.camTo({ x: foco.cx, y: foco.cy, z: 1.5 }, fin);
      await film.hasta(fin, 1.35);
    }
    await botonPorTexto(page, i < 5 ? /^Siguiente/ : /^Los datos del formulario/);
    await page.clock.runFor(30);
    tq = fin;
  }
  film.marca('los datos');

  // ---- Paso 4: los datos
  const tj4 = await film.rect('section.tarjeta');
  const cards = await page.evaluate(() => Array.from(document.querySelectorAll('section.tarjeta .campo-card, section.tarjeta [class*="tarjeta-campo"], section.tarjeta .campos > *')).length);
  film.camSet({ x: tj4.cx, y: tj4.y + 260, z: 1.25 });
  const t4 = film.t;
  film.camTo({ x: tj4.cx, y: tj4.y + 900, z: 1.45 }, t4 + 7.5);
  await film.hasta(t4 + 7.3);
  // abrir "Aclaración y validación" del DNI del chico, si existe
  const dni = await page.evaluate(() => { const el = Array.from(document.querySelectorAll('section.tarjeta *')).find((x) => x.children.length === 0 && /DNI del chico/i.test(x.textContent)); if (!el) return null; el.scrollIntoView; return true; });
  await film.hasta(t4 + 7.6);
  const btnRes = await film.rect('.acciones .boton:not(.suave)');
  film.cursorSet({ x: btnRes.cx - 260, y: btnRes.cy + 80, pulso: 0 });
  film.camTo({ x: tj4.cx, y: btnRes.cy - 300, z: 1.3 }, t4 + 8.6);
  await film.irYClic('.acciones .boton:not(.suave)', t4 + 8.6);
  film.marca('resultado');
  await film.esperar(() => !!document.querySelector('.diagrama svg'));
  await page.clock.runFor(30);

  // ---- Paso 5: el resultado: plano del circuito (el vuelo 3D se hace aparte, sobre la textura)
  const t5 = film.t;
  const dia = await film.rect('.diagrama');
  film.camSet({ x: dia.cx, y: dia.cy - 200, z: 1.0 });
  film.camTo({ x: dia.cx, y: dia.cy, z: 1.4 }, t5 + 4.0);
  await film.hasta(t5 + 4.0);
  // textura del diagrama para el vuelo: su HTML + la hoja de estilos, para renderizarlo aparte a 3x
  const fs = require('fs');
  const dump = await page.evaluate(() => ({ html: document.querySelector('.diagrama').outerHTML, css: Array.from(document.querySelectorAll('link[rel=stylesheet]')).map((l) => l.href), vars: getComputedStyle(document.documentElement).cssText }));
  fs.writeFileSync(__dirname + '/../frames/diagrama.json', JSON.stringify(dump));
  film.marca('vista previa');
  const tel = await film.rect('.vp-fila > *');
  film.camTo({ x: tel.cx, y: tel.y + 300, z: 1.55 }, t5 + 6.0);
  await film.hasta(t5 + 6.0);
  film.camTo({ x: tel.cx, y: tel.y + 620, z: 1.55 }, t5 + 9.0);
  await film.hasta(t5 + 9.0);
  film.marca('fin escena asistente');
  await browser.close();
})().catch((e) => { console.error('ERROR', e); process.exit(1); });
